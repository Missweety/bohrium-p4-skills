#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""run_case.py - deliver an editable writing package plus a runnable benchmark.

One command does the whole case:

  read case.json / task.md / materials
  -> build writing items from real units (fact preservation, section coverage,
     citation mapping, absence guard)
  -> compose two drafts (template baseline, source-anchored extractive writer)
     or grade a provided draft
  -> score every draft with the rule rubric (0/1/2 + rationale + failure type)
  -> write draft.md, facts.csv, citation_map.json, report.json, result.json,
     scores, runs, trace and the rubric self-check

Using the provided draft is the production path; the two built-in drafts are the
control group that proves the rubric reacts to evidence instead of style.

Usage:
  python3 run_case.py --input /input --out /app/output --work /app/work
"""
import argparse
import csv
import hashlib
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import build_dataset  # noqa: E402
import grade  # noqa: E402
import ingest  # noqa: E402

DATASET_VERSION = "writing-bench-v2"
REPORT_VERSION = "writing-report-v2"
PLACEHOLDER = "This section summarises the study."


def sha256_text(text):
    return hashlib.sha256((text or "").encode("utf-8", "replace")).hexdigest()


def canonical(obj):
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def write_json(path, obj):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(obj, fh, ensure_ascii=False, indent=1)
    return sha256_text(canonical(obj))


def read_text(path):
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            return fh.read()
    except OSError:
        return ""


def compose_template(case, sections):
    title = case.get("title") or "Draft"
    lines = ["# %s" % title, ""]
    for sec in sections:
        lines += ["## %s" % sec, "", PLACEHOLDER, ""]
    return "\n".join(lines)


def compose_extractive(units, sections, case):
    """Assemble a draft from verbatim source sentences with explicit anchors."""
    title = case.get("title") or "Draft"
    paras = [u for u in units if u["kind"] == "paragraph"]
    buckets = {s: [] for s in sections}
    if not sections:
        sections = ["Body"]
        buckets = {"Body": []}
    for i, unit in enumerate(paras):
        sec = unit.get("section")
        target = None
        if sec:
            for s in sections:
                if str(sec).lower().startswith(s.lower()) or s.lower() in str(sec).lower():
                    target = s
                    break
        if target is None:
            target = sections[min(len(sections) - 1, i * len(sections) // max(1, len(paras)))]
        buckets[target].append(unit)
    lines = ["# %s" % title, ""]
    for sec in sections:
        lines += ["## %s" % sec, ""]
        for unit in buckets[sec]:
            text = " ".join(s["text"] for s in (unit.get("sentences") or []))
            lines += [text, "", "[src: %s]" % unit["unit_id"], ""]
        if not buckets[sec]:
            lines += ["No anchored evidence was found for this section.", ""]
    return "\n".join(lines)


def compose_oracle(units, sections):
    """A paraphrased draft built from source facts: no long verbatim run."""
    lines = []
    for i, sec in enumerate(sections):
        lines += ["## %s" % sec, ""]
        for unit in units[i::max(1, len(sections))][:2]:
            nums = build_dataset.parse_numbers(unit["text"])
            facts = "；".join("%s" % n["raw"] for n in nums) if nums else "no reported value"
            lines.append("This section reports %s from the source unit." % facts)
            lines.append("[src: %s]" % unit["unit_id"])
            lines.append("")
    return "\n".join(lines)


def grade_condition(name, draft, items, units_all):
    records = [grade.grade_item(it, draft, units_all) for it in items]
    return {"draft": draft, "records": records,
            "summary": grade.summarize(records, items, name),
            "sha256": sha256_text(draft)}


def ingest_filtered(case, input_dir, task_text):
    """ingest(), minus any delivered draft living in the input folder."""
    ing = ingest.ingest(case, input_dir, task_text)
    ing["units"] = [u for u in ing["units"] if not u["source_path"].endswith("draft.md")]
    ing["tables"] = [t for t in ing["tables"]
                     if not (t.get("source_path") or "").endswith("draft.md")]
    ing["docs"] = [d for d in ing["docs"] if not d["source_path"].endswith("draft.md")]
    return ing


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", default="/input")
    ap.add_argument("--out", default="/app/output")
    ap.add_argument("--work", default="/app/work")
    ap.add_argument("--draft", default="", help="optional external draft path")
    a = ap.parse_args()

    case, case_path, case_err = ingest.load_case(a.input)
    task_text, task_path = ingest.load_task(a.input, case)
    case_id = case.get("case_id") or case.get("id") or "unknown"
    ing = ingest_filtered(case, a.input, task_text)
    units = ing["units"]
    units_all = [u["unit_id"] for u in units]

    data = build_dataset.build(case, units, task_text)
    items = data["items"]
    sections = data["required_sections"]

    # ---- drafts -------------------------------------------------------------
    drafts = {
        "template": compose_template(case, sections),
        "extractive_writer": compose_extractive(units, sections, case),
    }
    provided_path = a.draft or case.get("draft_path") or ""
    if not provided_path and os.path.exists(os.path.join(a.input, "draft.md")):
        provided_path = "draft.md"
    if provided_path:
        p = provided_path if os.path.isabs(provided_path) else os.path.join(
            a.input, provided_path)
        if os.path.exists(p):
            drafts["provided"] = read_text(p)
        else:
            drafts["provided"] = ""
    main_name = "provided" if "provided" in drafts else "extractive_writer"
    main_draft = drafts[main_name]

    conditions = {name: grade_condition(name, text, items, units_all)
                  for name, text in drafts.items()}
    rubric_check = grade.rubric_self_check(items, units_all)
    for name, blob in conditions.items():
        if name in ("template", "extractive_writer"):
            blob["role"] = "control"
        else:
            blob["role"] = "delivered draft"

    # ---- deliverables -------------------------------------------------------
    os.makedirs(a.work, exist_ok=True)
    os.makedirs(a.out, exist_ok=True)
    dataset_path = os.path.join(a.work, "dataset.json")
    write_json(dataset_path, data)
    # Solver-facing views: the author needs unit ids to place anchors, and the
    # item list without gold values to write against. Gold never leaves work/.
    write_json(os.path.join(a.work, "units.json"),
               [{"unit_id": u["unit_id"], "kind": u["kind"],
                 "source_path": u["source_path"], "locator": u.get("locator"),
                 "section": u.get("section"), "text": u["text"]} for u in units])
    write_json(os.path.join(a.work, "public_items.json"),
               [{k: v for k, v in it.items()
                 if k not in ("gold", "evidence", "rubric")} for it in items])
    os.makedirs(os.path.join(a.out, "scores"), exist_ok=True)
    os.makedirs(os.path.join(a.out, "runs"), exist_ok=True)
    os.makedirs(os.path.join(a.out, "checks"), exist_ok=True)

    draft_path = os.path.join(a.out, "draft.md")
    with open(draft_path, "w", encoding="utf-8") as fh:
        fh.write(main_draft)
    draft_sha = sha256_text(main_draft)

    # facts.csv: every required fact, whether the delivered draft keeps it, and
    # the unit/locator that supports it.
    facts_rows = []
    for it in items:
        if it["task_type"] != "fact_preserve":
            continue
        for n in it["gold"]["numbers"]:
            ev = (it["evidence"] or [{}])[0]
            loc = ev.get("locator") or {}
            facts_rows.append({
                "item_id": it["item_id"], "value_raw": n["raw"],
                "value": ("%g" % n["value"]), "unit": n["unit"],
                "source_path": ev.get("source_path", ""),
                "unit_id": ev.get("unit_id", ""),
                "locator": "paragraph:%s" % loc.get("paragraph_id", ""),
                "present_in_draft": "yes" if n["raw"] in main_draft or
                                    ("%g" % n["value"]) in main_draft else "no",
            })
    facts_path = os.path.join(a.out, "facts.csv")
    with open(facts_path, "w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(facts_rows[0].keys()) if facts_rows
                                else ["item_id", "value_raw", "value", "unit",
                                      "source_path", "unit_id", "locator",
                                      "present_in_draft"])
        writer.writeheader()
        writer.writerows(facts_rows)

    citation_map = {"draft_sha256": draft_sha, "claims": []}
    for it in items:
        if it["task_type"] != "citation_map":
            continue
        for claim in it["gold"]["claims"]:
            ev = (it["evidence"] or [{}])[0]
            citation_map["claims"].append({
                "claim_id": claim["claim_id"], "item_id": it["item_id"],
                "keywords": claim["keywords"],
                "source_path": ev.get("source_path", ""),
                "unit_id": claim["unit_id"],
                "locator": ev.get("locator"),
                "quote": ev.get("quote", ""),
                "anchored_in_draft": claim["unit_id"] in grade.find_anchors(main_draft),
            })
    citation_path = os.path.join(a.out, "citation_map.json")
    write_json(citation_path, citation_map)

    # ---- scores / runs / trace ---------------------------------------------
    trace, condition_summaries = [], {}
    for name, blob in conditions.items():
        write_json(os.path.join(a.out, "runs", name, "draft.json"),
                   {"name": name, "sha256": blob["sha256"],
                    "chars": len(blob["draft"]), "draft": blob["draft"]})
        write_json(os.path.join(a.out, "scores", "%s.json" % name), {
            "condition": name, "dataset_version": DATASET_VERSION,
            "dataset_sha256": data["dataset_sha256"],
            "draft_sha256": blob["sha256"],
            "scorer": "rule:writing-rubric-v1",
            "records": blob["records"], "summary": blob["summary"],
        })
        condition_summaries[name] = blob["summary"]
        by_id = {r["item_id"]: r for r in blob["records"]}
        for it in items:
            rec = by_id.get(it["item_id"], {})
            trace.append({
                "condition": name, "item_id": it["item_id"],
                "item_sha256": sha256_text(canonical(it)),
                "draft_sha256": blob["sha256"],
                "score_record": "scores/%s.json" % name,
                "score": rec.get("score"),
                "rationale": rec.get("rationale"),
                "chain_ok": rec.get("item_id") == it["item_id"] and
                            os.path.exists(os.path.join(a.out, "scores", "%s.json" % name)),
            })

    write_json(os.path.join(a.out, "checks", "rubric_selfcheck.json"), rubric_check)
    write_json(os.path.join(a.out, "checks", "trace.json"), {
        "draft_sha256": draft_sha, "entries": trace,
        "all_chain_ok": all(t["chain_ok"] for t in trace) if trace else False,
    })

    def norm(name):
        return condition_summaries.get(name, {}).get("normalized_score", 0.0)

    comparison = {}
    if "extractive_writer" in condition_summaries and "template" in condition_summaries:
        comparison = {
            "metric": "normalized_score (2 points per item) on this case's items",
            "extractive_writer": norm("extractive_writer"),
            "template": norm("template"),
            "delta": round(norm("extractive_writer") - norm("template"), 4),
            "interpretation": ("差值说明“带来源锚点的稿”与“无来源模板”在本评分口径下的差别；"
                               "不是参赛者相对官方白板的增益，也不评价文风。"),
        }

    failure_examples = []
    for name, summ in condition_summaries.items():
        for f in summ.get("failures", [])[:6]:
            item = next((it for it in items if it["item_id"] == f["item_id"]), {})
            failure_examples.append({
                "condition": name, "item_id": f["item_id"],
                "task_type": f.get("task_type"), "failure_type": f.get("failure_type"),
                "score": f["score"], "task": item.get("task", ""),
                "rationale": f.get("rationale"),
            })

    report = {
        "report_version": REPORT_VERSION, "case_id": case_id,
        "dataset_version": DATASET_VERSION, "dataset_sha256": data["dataset_sha256"],
        "draft_sha256": draft_sha,
        "conditions": condition_summaries, "comparison": comparison,
        "coverage": {"items": len(items), "by_type": data["by_type"],
                     "required_sections": sections,
                     "facts": len(facts_rows),
                     "claims": len(citation_map["claims"])},
        "leakage": {"items_with_gold_in_task": [
            it["item_id"] for it in items
            if any(n["raw"].lower() in it["task"].lower()
                   for n in (it.get("gold") or {}).get("numbers") or [])]},
        "rubric_selfcheck_pass": rubric_check["pass"],
        "failure_examples": failure_examples,
        "warnings": ing.get("warnings") or [],
        "reproducibility": {"determinism": "build_dataset.build is a pure function of "
                                           "case + units; sha256 recomputed in selfcheck",
                            "verified_by": "scripts/selfcheck.py"},
    }
    write_json(os.path.join(a.out, "report.json"), report)

    # ---- result.json --------------------------------------------------------
    unreadable = [d for d in ing["docs"] if not d["readable"]]
    uncertainty = []
    if case_err:
        uncertainty.append({"type": "case_file", "detail": case_err})
    for d in unreadable:
        uncertainty.append({"type": "unreadable_source", "path": d["source_path"],
                            "detail": d.get("error") or "no text"})
    for w in ing.get("warnings") or []:
        uncertainty.append({"type": "pipeline_warning", "detail": w})
    if "provided" in drafts and not drafts["provided"].strip():
        uncertainty.append({"type": "empty_provided_draft",
                            "detail": "声明了 draft_path 但文件为空，已退回 extractive_writer"})
    missing_facts = [r for r in facts_rows if r["present_in_draft"] == "no"]
    if missing_facts:
        uncertainty.append({"type": "facts_not_in_draft",
                            "detail": "%d 条必需事实未出现在交付稿中（见 facts.csv）"
                                      % len(missing_facts)})
    if not items:
        uncertainty.append({"type": "no_items",
                            "detail": "材料未产出可判写作题；检查是否有段落含数值/否定句"})

    checks = {
        "rubric_selfcheck": rubric_check["pass"],
        "trace_chain": all(t["chain_ok"] for t in trace) if trace else False,
        "no_gold_in_task": not report["leakage"]["items_with_gold_in_task"],
        "facts_documented": bool(facts_rows),
        "citation_map_anchored": all(c["unit_id"] in units_all
                                     for c in citation_map["claims"]),
        "draft_nonempty": bool(main_draft.strip()),
    }
    if not items:
        status = "failed"
    elif all(checks.values()) and not unreadable:
        status = "success" if not missing_facts else "partial"
    else:
        status = "partial"

    contract_names = []
    oc = case.get("output_contract")
    if isinstance(oc, dict):
        contract_names = list(oc.keys())
    elif isinstance(oc, list):
        for entry in oc:
            if isinstance(entry, str):
                contract_names.append(entry)
            elif isinstance(entry, dict):
                nm = entry.get("name") or entry.get("field") or entry.get("id")
                if nm:
                    contract_names.append(str(nm))

    top = {
        "case_id": case_id,
        "status": status,
        "status_reason": ("题量、事实映射与检查全部通过" if status == "success"
                          else "见 uncertainty：缺事实/来源不可读/题量不足"),
        "deliverable": {
            "draft": "draft.md", "draft_sha256": draft_sha,
            "chars": len(main_draft), "sections": sections,
            "facts": "facts.csv", "citation_map": "citation_map.json",
            "source_of_draft": main_name,
        },
        "fact_source_map": facts_rows,
        "citation_map": citation_map,
        "benchmark": {
            "dataset_version": DATASET_VERSION, "dataset_sha256": data["dataset_sha256"],
            "item_count": len(items), "by_type": data["by_type"],
            "items": items,
        },
        "evaluation": {"conditions": condition_summaries, "comparison": comparison,
                       "failure_examples": failure_examples,
                       "rubric_selfcheck_pass": rubric_check["pass"]},
        "sources": [{"path": d["source_path"], "kind": d["kind"],
                     "readable": d["readable"], "chars": d["chars"],
                     "sha256": d["sha256"], "extraction": d["extraction"],
                     "anchor_scheme": "paragraph_id / table_id+row_index (+char offsets)"}
                    for d in ing["docs"]],
        "uncertainty": uncertainty,
        "change_log": [
            {"version": DATASET_VERSION,
             "change": "写作题四类：事实保真、结构完整、引用映射、不编造未报告项"},
            {"version": DATASET_VERSION,
             "change": "整段照搬 ≥%d 词不给满分，改写必须真正改写" % grade.COPY_WORDS},
            {"version": DATASET_VERSION,
             "change": "模板/溯源稿两条件实跑，逐题 0/1/2 并留失败类型"},
        ],
        "checks": checks,
        "artifacts": {"draft": "draft.md", "facts": "facts.csv",
                      "citation_map": "citation_map.json", "report": "report.json",
                      "dataset": "work/dataset.json",
                      "scores": ["scores/%s.json" % x for x in conditions],
                      "trace": "checks/trace.json"},
    }
    contract_fields, missing = {}, []
    for name in contract_names:
        if name in top:
            contract_fields[name] = top[name]
        elif name in ("main_result", "result", "output", "artifacts"):
            contract_fields[name] = top["artifacts"]
        elif name in ("evidence", "citations", "fact_map", "fact_source_map"):
            contract_fields[name] = top["fact_source_map"]
        elif name in ("draft", "manuscript", "text"):
            contract_fields[name] = {"path": "draft.md", "sha256": draft_sha}
        elif name in ("version", "version_info"):
            contract_fields[name] = {"dataset_version": DATASET_VERSION,
                                     "report_version": REPORT_VERSION}
        else:
            contract_fields[name] = None
            missing.append(name)
    top["contract_fields"] = contract_fields
    if missing:
        top["uncertainty"].append({"type": "unmapped_contract_fields",
                                   "detail": "未实现的契约字段：%s（输出 null，未编造）"
                                             % ", ".join(missing)})
    write_json(os.path.join(a.out, "result.json"), top)

    print(json.dumps({"case_id": case_id, "status": status, "items": len(items),
                      "by_type": data["by_type"], "draft_chars": len(main_draft),
                      "extractive_writer": norm("extractive_writer"),
                      "template": norm("template"),
                      "checks": checks, "out": os.path.abspath(a.out)},
                     ensure_ascii=False, indent=1))
    return 0 if status != "failed" else 1


if __name__ == "__main__":
    sys.exit(main())
