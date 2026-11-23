#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""selfcheck.py - independent verification of one writing-benchmark run.

Re-derives every checkable claim in result.json instead of trusting it:

  1. artefacts exist and parse
  2. case_id consistent with the input
  3. dataset rebuild is deterministic (sha256 equal)
  4. no item task text contains its own gold number
  5. rubric is non-degenerate (gold-only draft -> 2, empty -> 0)
  6. draft.md hash matches the delivered hash
  7. re-grading draft.md reproduces the recorded scores exactly
  8. report aggregates equal recomputed aggregates
  9. trace chain resolves item -> draft -> score
 10. facts.csv rows resolve to real source units and honest presence flags
 11. citation_map anchors resolve to real source units
 12. contract fields present, status honest, no placeholders in the draft

Usage:
  python3 selfcheck.py --input /input --out /app/output --work /app/work
Exit 0 = PASS, 1 = FAIL. Writes <out>/checks.json.
"""
import argparse
import csv
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import build_dataset  # noqa: E402
import grade  # noqa: E402
import ingest  # noqa: E402
import run_case  # noqa: E402

PLACEHOLDERS = ("lorem ipsum", "todo:", "tbd", "[placeholder]", "待填写", "占位文本")


def read_json(path, default=None):
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return default


def read_text(path):
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            return fh.read()
    except OSError:
        return ""


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

    required = ["result.json", "report.json", "draft.md", "facts.csv",
                "citation_map.json", "checks/trace.json",
                "checks/rubric_selfcheck.json", "scores/extractive_writer.json",
                "scores/template.json", "runs/extractive_writer/draft.json"]
    present = {}
    for rel in required:
        p = os.path.join(a.out, rel)
        if rel.endswith(".json"):
            present[rel] = read_json(p)
            ok = present[rel] is not None
        else:
            present[rel] = read_text(p) if os.path.exists(p) else None
            ok = bool(present[rel])
        if not ok:
            issues.append("artefact %s missing or empty" % rel)
    check("artefacts_present", all(v is not None for v in present.values()),
          "missing: %s" % [k for k, v in present.items() if v is None])

    result = present.get("result.json") or {}
    report = present.get("report.json") or {}
    draft = present.get("draft.md") or ""

    case, _, _ = ingest.load_case(a.input)
    case_id = result.get("case_id")
    input_case_id = case.get("case_id") or case.get("id")
    check("case_id_present", bool(case_id) and case_id != "unknown", str(case_id))
    if input_case_id:
        check("case_id_matches_input", case_id == input_case_id,
              "input=%s result=%s" % (input_case_id, case_id))

    # 3) deterministic rebuild
    task_text, _ = ingest.load_task(a.input, case)
    ing = run_case.ingest_filtered(case, a.input, task_text)
    data = build_dataset.build(case, ing["units"], task_text)
    stored_ds = read_json(os.path.join(a.work, "dataset.json")) or {}
    check("deterministic_dataset", data["dataset_sha256"] == stored_ds.get("dataset_sha256"),
          "rebuilt=%s stored=%s" % (data["dataset_sha256"], stored_ds.get("dataset_sha256")))
    check("items_nonempty", len(data["items"]) > 0, "%d items" % len(data["items"]))

    # 4) no gold leak into task
    leaks = [it["item_id"] for it in data["items"]
             if any(n["raw"].lower() in it["task"].lower()
                    for n in (it.get("gold") or {}).get("numbers") or [])]
    check("no_gold_in_task", not leaks, "leaked: %s" % leaks)

    # 5) rubric sanity
    rubric = grade.rubric_self_check(data["items"], [u["unit_id"] for u in ing["units"]])
    check("rubric_selfcheck", rubric["pass"],
          "; ".join("%s=%s" % (r["item_id"], r["checks"]) for r in rubric["items"]
                    if not all(r["checks"].values())))

    # 6) draft hash
    delivered = (result.get("deliverable") or {})
    check("draft_hash_matches", delivered.get("draft_sha256") == run_case.sha256_text(draft),
          "result=%s file=%s" % (delivered.get("draft_sha256"),
                                 run_case.sha256_text(draft)))
    check("draft_nonempty", bool(draft.strip()), "%d chars" % len(draft))

    # 7) regrade delivered draft
    units_all = [u["unit_id"] for u in ing["units"]]
    main_name = delivered.get("source_of_draft") or "extractive_writer"
    stored = read_json(os.path.join(a.out, "scores", "%s.json" % main_name)) or {}
    stored_by_id = {r["item_id"]: r for r in stored.get("records", [])}
    mism = []
    for it in data["items"]:
        fresh = grade.grade_item(it, draft, units_all)
        old = stored_by_id.get(it["item_id"])
        if old is None:
            mism.append("%s: no record" % it["item_id"])
        elif (fresh["score"], fresh["failure_type"]) != (old["score"], old["failure_type"]):
            mism.append("%s: %s->%s" % (it["item_id"], old["score"], fresh["score"]))
    check("regrade_delivered_matches", not mism, "; ".join(mism[:5]))
    check("record_count", len(stored_by_id) == len(data["items"]),
          "records=%d items=%d" % (len(stored_by_id), len(data["items"])))

    # 8) report aggregates
    for cond, summ in (report.get("conditions") or {}).items():
        recs = (read_json(os.path.join(a.out, "scores", "%s.json" % cond)) or {}).get(
            "records", [])
        graded = [r for r in recs if r.get("gradable")]
        cmax = 2 * len(graded)
        expect = round(sum(r["score"] for r in graded) / float(cmax), 4) if cmax else 0.0
        check("report_aggregate:%s" % cond, expect == summ.get("normalized_score"),
              "recomputed=%s report=%s" % (expect, summ.get("normalized_score")))

    # 9) trace
    trace = present.get("checks/trace.json") or {}
    bad = [e["item_id"] for e in trace.get("entries", []) if not e.get("chain_ok")]
    check("trace_chain", not bad and bool(trace.get("entries")), "broken: %s" % bad[:5])

    # 10) facts.csv
    facts_path = os.path.join(a.out, "facts.csv")
    rows = []
    try:
        with open(facts_path, encoding="utf-8") as fh:
            rows = list(csv.DictReader(fh))
    except OSError:
        pass
    check("facts_csv_rows", bool(rows), "no fact rows")
    bad_units = [r.get("unit_id") for r in rows if r.get("unit_id") not in units_all]
    check("facts_units_resolve", not bad_units, "unknown units: %s" % bad_units[:5])
    wrong_flag = [r.get("value_raw") for r in rows
                  if (r.get("present_in_draft") == "yes") !=
                  (r.get("value_raw", "") in draft or r.get("value", "") in draft)]
    check("facts_presence_honest", not wrong_flag, "wrong flags: %s" % wrong_flag[:5])

    # 11) citation map
    cm = present.get("citation_map.json") or {}
    bad_claims = [c.get("claim_id") for c in cm.get("claims", [])
                  if c.get("unit_id") not in units_all]
    check("citation_units_resolve", not bad_claims, "unknown units: %s" % bad_claims[:5])
    check("citation_map_has_claims", bool(cm.get("claims")), "no claims")

    # 12) packaging honesty
    blob = json.dumps(result, ensure_ascii=False).lower()
    found = [p for p in PLACEHOLDERS if p in blob]
    check("no_placeholders_in_result", not found, "found: %s" % found)
    draft_ph = [p for p in PLACEHOLDERS if p in draft.lower()]
    check("no_placeholders_in_draft", not draft_ph, "found: %s" % draft_ph)
    check("contract_fields_present", bool(result.get("contract_fields")),
          "contract_fields empty")
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
    run_case.write_json(os.path.join(a.out, "checks.json"), out)
    print(("PASS" if ok else "FAIL") + " selfcheck: %d checks, %d failed"
          % (len(checks), out["failed"]))
    for c in checks:
        if not c["pass"]:
            print(" -", c["name"], ":", c["detail"])
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
