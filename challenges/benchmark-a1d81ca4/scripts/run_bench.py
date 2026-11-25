#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""run_bench.py - build, run and report one source-conditioned reading benchmark.

Pipeline (all deterministic, Python 3 standard library only):

  ingest  -> locatable units (paragraph / table row) with sha256 per source
  forge   -> hard items (numeric / table / condition / absence / definition /
             relation) each with gold answer, evidence quote + locator, 0/1/2
             rubric and an anti-leakage audit
  split   -> deterministic unit-level dev/test split (no unit, no quote shared)
  solve   -> baseline solvers (extractive, naive) answer the test items
  grade   -> rule-based 0/1/2 records with rationale + failure taxonomy
  report  -> per-condition scores, per-type/per-difficulty buckets, failure
             samples, coverage, leakage audit, traceability chain

Every number in report.json / result.json is computed from the artefacts written
in the same run. Nothing is invented; missing pieces downgrade status to
"partial" or "failed" and are listed under "uncertainty".

Usage:
  python3 run_bench.py --input /input --out /app/output --work /app/work
"""
import argparse
import hashlib
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import baselines  # noqa: E402
import forge  # noqa: E402
import grade  # noqa: E402
import ingest  # noqa: E402

DATASET_VERSION = "reading-bench-v3"
REPORT_VERSION = "reading-report-v3"
SPLIT_DEV_BUCKETS = 30          # 30% of source units go to dev, rest to test
MAX_ANSWER_CHARS = 1200         # public contract: answer budget per item


# ------------------------------------------------------------------ utilities
def sha256_text(text):
    return hashlib.sha256((text or "").encode("utf-8", "replace")).hexdigest()


def canonical_json(obj):
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def sha256_obj(obj):
    return sha256_text(canonical_json(obj))


def write_json(path, obj):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(obj, fh, ensure_ascii=False, indent=1, sort_keys=False)
    return sha256_obj(obj)


def file_sha256(path):
    h = hashlib.sha256()
    try:
        with open(path, "rb") as fh:
            for chunk in iter(lambda: fh.read(65536), b""):
                h.update(chunk)
    except OSError:
        return ""
    return h.hexdigest()


def read_json(path, default=None):
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return default


# ------------------------------------------------------------------ benchmark
def build(case, task_text, input_dir, case_id=None):
    """Deterministic build. Calling twice on the same input yields the same hash."""
    ing = ingest.ingest(case, input_dir, task_text)
    workorder = forge.parse_workorder(case, task_text)
    forged = forge.forge(ing["units"], ing["tables"], workorder, case)
    dataset = {
        "dataset_version": DATASET_VERSION,
        "case_id": case_id or case.get("case_id") or case.get("id") or "unknown",
        "language": forged.get("language"),
        "workorder": workorder,
        "coverage": forged["coverage"],
        "warnings": list(ing.get("warnings") or []) + list(forged.get("warnings") or []),
        "rejected_candidates": len(forged["rejected"]),
        "items": forged["items"],
        "docs": [{"source_path": d["source_path"], "kind": d["kind"],
                  "readable": d["readable"], "chars": d["chars"],
                  "sha256": d["sha256"], "extraction": d["extraction"],
                  "error": d.get("error")} for d in ing["docs"]],
        "unit_count": len(ing["units"]),
        "table_count": len(ing["tables"]),
    }
    dataset["dataset_sha256"] = sha256_obj({
        "version": DATASET_VERSION,
        "items": dataset["items"],
        "docs": dataset["docs"],
        "workorder": dataset["workorder"],
    })
    return {"ingest": ing, "forged": forged, "dataset": dataset}


def split_items(items):
    """Unit-level deterministic split; dev and test never share a source unit.

    Every item of a unit stays on the same side: dropping or leaking an item
    would silently shrink the held-out set and corrupt the reported score.
    """
    by_unit = {}
    for it in items:
        by_unit.setdefault(it["unit_id"], []).append(it)
    dev, test = [], []
    for unit_id, group in by_unit.items():
        bucket = int(hashlib.sha256(unit_id.encode("utf-8")).hexdigest()[:8], 16) % 100
        (dev if bucket < SPLIT_DEV_BUCKETS else test).extend(group)
    # Guarantee both sides are non-empty without splitting a unit.
    if not test:
        test, dev = list(items), []
    elif not dev and len(by_unit) > 1:
        first_unit = test[0]["unit_id"]
        dev = [it for it in test if it["unit_id"] == first_unit]
        test = [it for it in test if it["unit_id"] != first_unit]
    dev_units = {it["unit_id"] for it in dev}
    test_units = {it["unit_id"] for it in test}
    dev_quotes = {sha256_text((it["evidence"][0] or {}).get("quote", "")) for it in dev}
    test_quotes = {sha256_text((it["evidence"][0] or {}).get("quote", "")) for it in test}
    return {
        "policy": "sha256(unit_id) mod 100 < %d -> dev, else test (whole unit kept together)"
                  % SPLIT_DEV_BUCKETS,
        "dev_item_ids": [it["item_id"] for it in dev],
        "test_item_ids": [it["item_id"] for it in test],
        "dev_units": sorted(dev_units),
        "test_units": sorted(test_units),
        "shared_units": sorted(dev_units & test_units),
        "shared_quote_hashes": sorted(dev_quotes & test_quotes),
        "dev": dev,
        "test": test,
    }


def contract_field_names(case):
    """Field names declared by the runtime output_contract, whatever its nesting."""
    names = []

    def add(value):
        if isinstance(value, str):
            names.append(value)
        elif isinstance(value, dict):
            name = value.get("name") or value.get("field") or value.get("id")
            if name:
                names.append(str(name))
            else:  # mapping of field name -> type/spec
                names.extend(str(key) for key in value)
        elif isinstance(value, list):
            for entry in value:
                add(entry)

    contract = case.get("output_contract") if isinstance(case, dict) else None
    if isinstance(contract, dict):
        containers = {"fields", "required", "optional", "properties", "version"}
        if containers & set(contract):
            for key in ("fields", "required", "optional", "properties"):
                add(contract.get(key))
            for key in contract:
                if key not in containers:
                    names.append(key)
        else:
            names.extend(contract.keys())
    else:
        add(contract)
    seen, out = set(), []
    for name in names:
        if name and name not in seen:
            seen.add(name)
            out.append(name)
    return out


def run_conditions(test_items, units, agents):
    public = forge.public_items(test_items)
    runs = baselines.run_baselines(public, units, agents=agents)
    out = {}
    for agent, answers in runs.items():
        by_id = {a["item_id"]: a for a in answers}
        records = [grade.grade_item(it, by_id.get(it["item_id"], {})) for it in test_items]
        out[agent] = {"answers": answers, "records": records,
                      "summary": grade.summarize(records, test_items, agent)}
    return public, out


def answer_case_questions(case, units):
    """If the case states explicit reading questions, answer them with citations."""
    raw = None
    for key in ("questions", "queries", "reading_questions", "qa"):
        val = case.get(key)
        if isinstance(val, list) and val:
            raw = val
            break
    if not raw:
        return [], "case.json 未声明 questions/queries，跳过问答部分（只交付基准题集）"
    index = baselines.build_index(units)
    out = []
    for i, q in enumerate(raw):
        qid = "Q%02d" % (i + 1)
        text = q if isinstance(q, str) else (q.get("question") or q.get("query") or "")
        qid = (q.get("id") if isinstance(q, dict) and q.get("id") else qid)
        if not text:
            continue
        item = {"item_id": qid, "question": text, "task_type": None}
        ans = baselines.extractive_answer(item, units, index)
        ans["method"] = "extractive-v1 (baseline, not gold)"
        ans["answered"] = bool((ans.get("answer") or "").strip())
        ans["status"] = "answered" if ans["answered"] else "unanswered"
        out.append(ans)
    return out, ""


# ------------------------------------------------------------------ artefacts
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", default="/input")
    ap.add_argument("--out", default="/app/output")
    ap.add_argument("--work", default="/app/work")
    ap.add_argument("--agents", default="extractive,naive")
    ap.add_argument("--case-id", default="")
    a = ap.parse_args()

    agents = [x.strip() for x in a.agents.split(",") if x.strip()]
    case, case_path, case_err = ingest.load_case(a.input)
    task_text, task_path = ingest.load_task(a.input, case)
    case_id = a.case_id or case.get("case_id") or case.get("id") or "unknown"

    built = build(case, task_text, a.input, case_id)
    dataset = built["dataset"]
    units = built["ingest"]["units"]
    items = dataset["items"]
    split = split_items(items)
    public, conditions = run_conditions(split["test"], units, agents)
    rubric_check = grade.rubric_self_check(items)
    qa, qa_note = answer_case_questions(case, units)

    # ------------------------------------------------------------ write work
    os.makedirs(a.work, exist_ok=True)
    dataset_path = os.path.join(a.work, "dataset.json")
    write_json(dataset_path, dataset)
    write_json(os.path.join(a.work, "split.json"),
               {k: v for k, v in split.items() if k not in ("dev", "test")})
    write_json(os.path.join(a.work, "public_test_items.json"), public)
    write_json(os.path.join(a.work, "rejected_candidates.json"),
               built["forged"]["rejected"])

    # ------------------------------------------------------------ write output
    os.makedirs(os.path.join(a.out, "scores"), exist_ok=True)
    os.makedirs(os.path.join(a.out, "runs"), exist_ok=True)
    os.makedirs(os.path.join(a.out, "checks"), exist_ok=True)

    condition_summaries, trace = {}, []
    for agent, blob in conditions.items():
        answers_path = os.path.join(a.out, "runs", agent, "answers.json")
        write_json(answers_path, blob["answers"])
        write_json(os.path.join(a.out, "runs", agent, "run_config.json"), {
            "agent": agent,
            "strategy": "baselines.%s" % agent,
            "dataset_sha256": dataset["dataset_sha256"],
            "public_items_sha256": sha256_obj(public),
            "units_sha256": sha256_obj([u["unit_id"] for u in units]),
            "answer_budget_chars": MAX_ANSWER_CHARS,
            "tools": "none (offline, stdlib retrieval)",
        })
        score_doc = {
            "agent": agent,
            "dataset_version": DATASET_VERSION,
            "dataset_sha256": dataset["dataset_sha256"],
            "scorer": "rule:rubric-v1",
            "records": blob["records"],
            "summary": blob["summary"],
        }
        write_json(os.path.join(a.out, "scores", "%s.json" % agent), score_doc)
        condition_summaries[agent] = blob["summary"]
        answers_by_id = {r["item_id"]: r for r in blob["records"]}
        for it in split["test"]:
            rec = answers_by_id.get(it["item_id"], {})
            trace.append({
                "item_id": it["item_id"],
                "item_sha256": sha256_obj(it),
                "answer_path": os.path.relpath(answers_path, a.out),
                "answer_sha256": sha256_obj([x for x in blob["answers"]
                                             if x.get("item_id") == it["item_id"]]),
                "score_record_path": os.path.relpath(
                    os.path.join(a.out, "scores", "%s.json" % agent), a.out),
                "score": rec.get("score"),
                "rationale": rec.get("rationale"),
                "chain_ok": os.path.exists(answers_path) and rec.get("item_id") == it["item_id"],
            })

    write_json(os.path.join(a.out, "checks", "rubric_selfcheck.json"), rubric_check)
    write_json(os.path.join(a.out, "checks", "trace.json"),
               {"dataset_sha256": dataset["dataset_sha256"], "entries": trace,
                "all_chain_ok": all(t["chain_ok"] for t in trace) if trace else False})

    # ------------------------------------------------------------ comparison
    def norm(agent):
        return condition_summaries.get(agent, {}).get("normalized_score", 0.0)

    comparison = {}
    if "extractive" in condition_summaries and "naive" in condition_summaries:
        comparison = {
            "metric": "normalized_score on the held-out test split (2 points per item)",
            "extractive": norm("extractive"),
            "naive": norm("naive"),
            "delta": round(norm("extractive") - norm("naive"), 4),
            "interpretation": ("正差值说明带定位的检索式基线优于无检索控制组；"
                               "该差值只描述本包两个基线，不是参赛者相对官方白板的增益。"),
        }

    failure_examples = []
    for agent, summ in condition_summaries.items():
        for f in summ.get("failures", [])[:6]:
            item = next((it for it in split["test"] if it["item_id"] == f["item_id"]), {})
            failure_examples.append({
                "agent": agent, "item_id": f["item_id"],
                "task_type": f.get("task_type"), "failure_type": f.get("failure_type"),
                "score": f.get("score"), "question": item.get("question", ""),
                "rationale": f.get("rationale"),
            })

    report = {
        "report_version": REPORT_VERSION,
        "case_id": case_id,
        "dataset_version": DATASET_VERSION,
        "dataset_sha256": dataset["dataset_sha256"],
        "conditions": condition_summaries,
        "comparison": comparison,
        "split": {"policy": split["policy"],
                  "dev_items": len(split["dev_item_ids"]),
                  "test_items": len(split["test_item_ids"]),
                  "shared_units": split["shared_units"],
                  "shared_quote_hashes": split["shared_quote_hashes"]},
        "coverage": dataset["coverage"],
        "leakage": {
            "audit": "each item passes forge.leak_check; rejected candidates kept",
            "rejected_candidates": dataset["rejected_candidates"],
            "all_items_clean": all(it.get("leakage_status") == "clean" for it in items),
        },
        "rubric_selfcheck_pass": rubric_check["pass"],
        "failure_examples": failure_examples,
        "warnings": dataset["warnings"],
        "reproducibility": {
            "determinism": "build() twice on the same input yields dataset_sha256",
            "verified_by": "scripts/selfcheck.py (imports run_bench.build)",
        },
    }
    write_json(os.path.join(a.out, "report.json"), report)

    # ------------------------------------------------------------ result.json
    readable_docs = [d for d in dataset["docs"] if d["readable"]]
    unreadable = [d for d in dataset["docs"] if not d["readable"]]
    uncertainty = []
    if case_err:
        uncertainty.append({"type": "case_file", "detail": case_err})
    if len(items) < (dataset["coverage"].get("requested_items") or 0):
        uncertainty.append({
            "type": "coverage_gap",
            "detail": "请求 %s 题，实际生成 %d 题；原因见 warnings"
                      % (dataset["coverage"].get("requested_items"), len(items)),
        })
    for d in unreadable:
        uncertainty.append({"type": "unreadable_source", "path": d["source_path"],
                            "detail": d.get("error") or "no text"})
    if qa_note:
        uncertainty.append({"type": "no_case_questions", "detail": qa_note})
    for ans in qa:
        if not ans.get("answered"):
            uncertainty.append({"type": "unanswered_question",
                                "item_id": ans.get("item_id"),
                                "detail": "检索式基线未找到支持句（%s），未编造答案"
                                          % ans.get("failure_reason")})
    for w in dataset["warnings"]:
        uncertainty.append({"type": "pipeline_warning", "detail": w})

    checks = {
        "rubric_selfcheck": rubric_check["pass"],
        "all_items_clean": all(it.get("leakage_status") == "clean" for it in items),
        "split_disjoint": not split["shared_units"] and not split["shared_quote_hashes"],
        "trace_chain": all(t["chain_ok"] for t in trace) if trace else False,
        "public_hides_gold": all("gold_answer" not in p and "evidence" not in p for p in public),
    }
    if not readable_docs:
        status = "failed"
    elif items and all(checks.values()) and not unreadable and len(items) >= (
            dataset["coverage"].get("requested_items") or 0):
        status = "success"
    else:
        status = "partial"

    contract_names = contract_field_names(case)

    reasons = []
    if not readable_docs:
        reasons.append("无可读来源材料")
    if len(items) < (dataset["coverage"].get("requested_items") or 0):
        reasons.append("题量不足 %s/%s" % (len(items),
                                          dataset["coverage"].get("requested_items")))
    if unreadable:
        reasons.append("有 %d 个来源不可读" % len(unreadable))
    if not all(checks.values()):
        reasons.append("检查未全通过：" + ", ".join(k for k, v in checks.items() if not v))
    top = {
        "case_id": case_id,
        "status": status,
        "status_reason": ("所有检查通过且题量达标" if status == "success"
                          else "; ".join(reasons) or "见 uncertainty"),
        "benchmark": {
            "dataset_version": DATASET_VERSION,
            "dataset_sha256": dataset["dataset_sha256"],
            "item_count": len(items),
            "requested_items": dataset["coverage"].get("requested_items"),
            "by_type": dataset["coverage"].get("by_type"),
            "by_source": dataset["coverage"].get("by_source"),
            "split": {"dev": len(split["dev_item_ids"]),
                      "test": len(split["test_item_ids"])},
        },
        "items": [{
            "item_id": it["item_id"], "task_type": it["task_type"],
            "difficulty": it["difficulty"], "question": it["question"],
            "gold_answer": it["gold_answer"],
            "acceptable_variants": it["acceptable_variants"],
            "evidence": it["evidence"], "rubric": it["rubric"],
            "leakage_status": it["leakage_status"], "data_license": it["data_license"],
        } for it in items],
        "readings": qa,
        "evaluation": {
            "conditions": condition_summaries,
            "comparison": comparison,
            "failure_examples": failure_examples,
            "rubric_selfcheck_pass": rubric_check["pass"],
        },
        "sources": [{"path": d["source_path"], "kind": d["kind"], "readable": d["readable"],
                     "chars": d["chars"], "sha256": d["sha256"],
                     "extraction": d["extraction"],
                     "anchor_scheme": "paragraph_id/table_id+row_index (+char offsets)"}
                    for d in dataset["docs"]],
        "uncertainty": uncertainty,
        "change_log": [
            {"version": DATASET_VERSION,
             "change": "由来源单元构造难例；每题带金标准、证据定位与 0/1/2 锚点"},
            {"version": DATASET_VERSION,
             "change": "按 unit_id 哈希做 dev/test 切分，防止同段泄漏"},
            {"version": DATASET_VERSION,
             "change": "extractive/naive 基线实跑并规则评分，失败样例入库"},
        ],
        "checks": checks,
        "artifacts": {
            "dataset": "work/dataset.json", "split": "work/split.json",
            "public_test_items": "work/public_test_items.json",
            "report": "report.json",
            "scores": ["scores/%s.json" % x for x in conditions],
            "runs": ["runs/%s/answers.json" % x for x in conditions],
            "trace": "checks/trace.json",
        },
    }
    contract_fields, missing = {}, []
    for name in contract_names:
        if name in top:
            value = top[name]
        elif name in ("main_result", "result", "answers"):
            value = {"items": top["items"], "readings": top["readings"]}
        elif name in ("evidence", "citations", "sources_locator"):
            value = top["sources"]
        elif name in ("version", "version_info"):
            value = {"dataset_version": DATASET_VERSION,
                     "report_version": REPORT_VERSION}
        else:
            value = None
            missing.append(name)
        contract_fields[name] = value
        top.setdefault(name, value)
    top["contract_fields"] = contract_fields
    if missing:
        top["uncertainty"].append({"type": "unmapped_contract_fields",
                                   "detail": "未实现的契约字段：%s（输出 null，未编造）"
                                             % ", ".join(missing)})
    write_json(os.path.join(a.out, "result.json"), top)

    print(json.dumps({
        "case_id": case_id, "status": status, "items": len(items),
        "by_type": dataset["coverage"].get("by_type"),
        "test_items": len(split["test_item_ids"]),
        "extractive": norm("extractive"), "naive": norm("naive"),
        "checks": checks,
        "out": os.path.abspath(a.out),
    }, ensure_ascii=False, indent=1))
    return 0 if status != "failed" else 1


if __name__ == "__main__":
    sys.exit(main())
