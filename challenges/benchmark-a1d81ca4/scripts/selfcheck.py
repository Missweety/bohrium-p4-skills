#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""selfcheck.py - independent verification of one reading-benchmark run.

Re-derives everything that can be re-derived; it does not trust result.json:

  1. required artefacts exist and parse as JSON
  2. case_id is consistent between input, dataset and result
  3. dataset rebuild is deterministic (same dataset_sha256)
  4. dev/test split shares no source unit and no evidence quote
  5. public solver view hides gold answer, evidence and rubric
  6. rubric is non-degenerate (gold -> 2, empty -> 0, overlong -> 0)
  7. stored baseline answers re-grade to exactly the recorded scores
  8. report aggregates equal aggregates recomputed from score records
  9. trace chain resolves item -> answer -> score with matching sha256
 10. no placeholder text stood in for real output

Usage:
  python3 selfcheck.py --input /input --out /app/output --work /app/work
Exit 0 = PASS, 1 = FAIL. Writes <out>/checks.json.
"""
import argparse
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import grade  # noqa: E402
import ingest  # noqa: E402
import run_bench  # noqa: E402

PLACEHOLDERS = ("lorem ipsum", "todo:", "tbd", "[placeholder]", "fill in here",
                "待填写", "占位文本")


def read_json(path):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", default="/input")
    ap.add_argument("--out", default="/app/output")
    ap.add_argument("--work", default="/app/work")
    a = ap.parse_args()

    checks, issues = [], []

    def check(name, ok, detail=""):
        checks.append({"name": name, "pass": bool(ok), "detail": detail})
        if not ok:
            issues.append("%s: %s" % (name, detail))

    required = ["result.json", "report.json", "checks/trace.json",
                "checks/rubric_selfcheck.json", "scores/extractive.json",
                "scores/naive.json", "runs/extractive/answers.json"]
    present = {}
    for rel in required:
        p = os.path.join(a.out, rel)
        try:
            present[rel] = read_json(p)
        except (OSError, ValueError) as exc:
            present[rel] = None
            issues.append("artefact %s unreadable: %s" % (rel, exc))
    check("artefacts_present", all(v is not None for v in present.values()),
          "missing/unreadable: %s" % [k for k, v in present.items() if v is None])

    result = present.get("result.json") or {}
    dataset = read_json(os.path.join(a.work, "dataset.json")) if os.path.exists(
        os.path.join(a.work, "dataset.json")) else {}
    case_id = result.get("case_id")

    # 2) case identity
    case, _, _ = ingest.load_case(a.input)
    input_case_id = case.get("case_id") or case.get("id")
    check("case_id_present", bool(case_id) and case_id != "unknown", str(case_id))
    if input_case_id:
        check("case_id_matches_input", case_id == input_case_id,
              "input=%s result=%s" % (input_case_id, case_id))

    # 3) deterministic rebuild
    task_text, _ = ingest.load_task(a.input, case)
    rebuilt = run_bench.build(case, task_text, a.input, case_id)
    check("deterministic_dataset",
          rebuilt["dataset"]["dataset_sha256"] == dataset.get("dataset_sha256"),
          "rebuilt=%s stored=%s" % (rebuilt["dataset"]["dataset_sha256"],
                                    dataset.get("dataset_sha256")))
    check("items_nonempty", len(rebuilt["dataset"]["items"]) > 0,
          "%d items" % len(rebuilt["dataset"]["items"]))

    items = rebuilt["dataset"]["items"]
    split_doc = read_json(os.path.join(a.work, "split.json")) if os.path.exists(
        os.path.join(a.work, "split.json")) else {}

    # 4) split disjointness (recomputed, not copied)
    split = run_bench.split_items(items)
    check("split_disjoint", not split["shared_units"] and not split["shared_quote_hashes"],
          "shared units=%s quotes=%s" % (split["shared_units"],
                                         split["shared_quote_hashes"]))
    check("split_recorded", set(split["test_item_ids"]) == set(
        split_doc.get("test_item_ids") or []),
          "split.json test ids differ from rebuild")

    # 5) public view
    public = read_json(os.path.join(a.work, "public_test_items.json")) or []
    check("public_hides_gold",
          all("gold_answer" not in p and "evidence" not in p and "rubric" not in p
              for p in public),
          "public items must not expose gold/evidence/rubric")
    check("public_ids_are_test_ids",
          {p["item_id"] for p in public} <= set(split["test_item_ids"]),
          "public view contains non-test items")

    # 6) rubric non-degeneracy
    rubric = grade.rubric_self_check(items)
    check("rubric_selfcheck", rubric["pass"],
          "; ".join("%s=%s" % (r["item_id"], r["checks"]) for r in rubric["items"]
                    if not all(r["checks"].values())))

    # 7) re-grade stored answers
    items_by_id = {it["item_id"]: it for it in items}
    for agent in ("extractive", "naive"):
        ans = read_json(os.path.join(a.out, "runs", agent, "answers.json")) or []
        recs_doc = read_json(os.path.join(a.out, "scores", "%s.json" % agent)) or {}
        stored = {r["item_id"]: r for r in recs_doc.get("records", [])}
        mismatches = []
        for answer in ans:
            item = items_by_id.get(answer.get("item_id"))
            if item is None:
                mismatches.append("%s: unknown item" % answer.get("item_id"))
                continue
            fresh = grade.grade_item(item, answer)
            old = stored.get(item["item_id"])
            if old is None:
                mismatches.append("%s: no stored record" % item["item_id"])
            elif (fresh["score"], fresh["failure_type"]) != (old["score"], old["failure_type"]):
                mismatches.append("%s: %s->%s" % (item["item_id"], old["score"], fresh["score"]))
        check("regrade_matches:%s" % agent, not mismatches, "; ".join(mismatches[:5]))
        check("record_count:%s" % agent, len(stored) == len(ans),
              "records=%d answers=%d" % (len(stored), len(ans)))

    # 8) report aggregates recomputed
    report = present.get("report.json") or {}
    for agent, summ in (report.get("conditions") or {}).items():
        recs = (read_json(os.path.join(a.out, "scores", "%s.json" % agent)) or {}).get(
            "records", [])
        total = sum(r.get("score", 0) for r in recs if r.get("gradable"))
        cmax = 2 * sum(1 for r in recs if r.get("gradable"))
        expect = round(total / float(cmax), 4) if cmax else 0.0
        got = summ.get("normalized_score")
        check("report_aggregate:%s" % agent, expect == got,
              "recomputed=%s report=%s" % (expect, got))
    check("report_has_test_set", (report.get("split") or {}).get("test_items", 0) > 0,
          "report split empty")

    # 9) trace chain
    trace = present.get("checks/trace.json") or {}
    bad = [e["item_id"] for e in trace.get("entries", [])
           if not e.get("chain_ok") or not e.get("answer_path")]
    check("trace_chain", not bad and bool(trace.get("entries")),
          "broken entries: %s" % bad[:5])
    for rel in {e.get("answer_path") for e in trace.get("entries", [])}:
        if rel:
            check("trace_answer_exists:%s" % rel,
                  os.path.exists(os.path.join(a.out, rel)), "missing answer file")

    # 10) placeholders / contract
    blob = json.dumps(result, ensure_ascii=False).lower()
    found = [p for p in PLACEHOLDERS if p in blob]
    check("no_placeholders", not found, "found: %s" % found)
    declared = run_bench.contract_field_names(case)
    if declared:
        check("contract_fields_present", bool(result.get("contract_fields")),
              "result.contract_fields empty")
        missing = [name for name in declared if name not in result]
        check("contract_fields_top_level", not missing, "not at result top level: %s" % missing)
    check("uncertainty_is_list", isinstance(result.get("uncertainty"), list),
          "uncertainty must be a list")
    check("status_honest", result.get("status") in ("success", "partial", "failed"),
          "status=%r" % result.get("status"))
    if result.get("status") == "success":
        check("success_requires_all_checks", all(c["pass"] for c in checks),
              "status=success but some checks failed")

    ok = all(c["pass"] for c in checks)
    out = {"pass": ok, "checks": checks, "issues": issues,
           "checked": len(checks), "failed": len([c for c in checks if not c["pass"]])}
    os.makedirs(a.out, exist_ok=True)
    run_bench.write_json(os.path.join(a.out, "checks.json"), out)

    print(("PASS" if ok else "FAIL") + " selfcheck: %d checks, %d failed"
          % (len(checks), out["failed"]))
    for c in checks:
        if not c["pass"]:
            print(" -", c["name"], ":", c["detail"])
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
