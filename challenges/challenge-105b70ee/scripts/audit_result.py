#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""audit_result.py - independent, machine-checkable review of an extraction run.

Checks
  contract  every output_contract field is present in result.json
  rows      one row per requested field_id; status vocabulary; no duplicate ids
  verbatim  reported.value and reported.quote exist in the indexed paragraph text
  anchors   reported.paragraph_id must resolve to an indexed paragraph or table row
  honesty   not_reported has no value; conflicts keep their candidates

Usage:
  python3 scripts/audit_result.py --result /app/output/result.json \
      --case /input/case.json --doc /app/work/doc.json --fields /app/work/field_results.json
Exit 0 when pass, 1 when there are errors.
"""
from __future__ import annotations

import argparse
import json
import os
import re

STATUSES = {"reported", "not_reported", "source_conflict", "extraction_failed"}
LIG = {"ﬁ": "fi", "ﬂ": "fl", "ﬀ": "ff", "ﬃ": "ffi", "\u00ad": "", "\u2019": "'",
       "‘": "'", "“": '"', "”": '"', "–": "-", "—": "-", "−": "-"}


def norm(s):
    for k, v in LIG.items():
        s = (s or "").replace(k, v)
    return re.sub(r"\s+", " ", s).strip().lower()


def contract_fields(contract):
    names = []
    if isinstance(contract, list):
        names = [x for x in contract if isinstance(x, str)]
    elif isinstance(contract, dict):
        items = None
        for key in ("required", "fields", "properties"):
            val = contract.get(key)
            if isinstance(val, list) and val:
                items = val
                break
            if isinstance(val, dict) and val:
                items = list(val.keys())
                break
        if items is None:
            items = list(contract.keys())
        for item in items:
            if isinstance(item, str):
                names.append(item)
            elif isinstance(item, dict):
                for k in ("name", "field", "field_id", "id", "key"):
                    if isinstance(item.get(k), str):
                        names.append(item[k])
                        break
    return names


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--result", required=True)
    ap.add_argument("--case")
    ap.add_argument("--doc")
    ap.add_argument("--fields")
    ap.add_argument("--out")
    a = ap.parse_args(argv)

    errors, warnings, checks = [], [], []

    def add(name, ok, detail=""):
        checks.append({"check": name, "ok": bool(ok), "detail": detail})
        if not ok:
            errors.append(detail or name)

    try:
        with open(a.result, encoding="utf-8") as fh:
            result = json.load(fh)
    except Exception as exc:  # noqa: BLE001
        report = {"pass": False, "errors": ["result.json unreadable: %s" % exc],
                  "warnings": [], "checks": []}
        print(json.dumps(report, ensure_ascii=False))
        return 1

    contract = {}
    if a.case and os.path.isfile(a.case):
        try:
            with open(a.case, encoding="utf-8") as fh:
                contract = json.load(fh).get("output_contract", {})
        except Exception as exc:  # noqa: BLE001
            warnings.append("case.json unreadable: %s" % exc)
    required = contract_fields(contract)
    missing = [f for f in required if f not in result]
    add("contract_fields_present", not missing,
        "missing contract fields: %s" % ", ".join(missing) if missing else "")

    rows = []
    if a.fields and os.path.isfile(a.fields):
        try:
            with open(a.fields, encoding="utf-8") as fh:
                data = json.load(fh)
            rows = data.get("fields") if isinstance(data, dict) else data
        except Exception as exc:  # noqa: BLE001
            warnings.append("field_results unreadable: %s" % exc)
    if not rows:
        for key in ("fields", "results", "items", "records"):
            if isinstance(result.get(key), list) and result[key]:
                first = result[key][0]
                if isinstance(first, dict) and "field_id" in first:
                    rows = result[key]
                    break

    doc_paras, doc_text, anchors = {}, "", set()
    if a.doc and os.path.isfile(a.doc):
        try:
            with open(a.doc, encoding="utf-8") as fh:
                doc = json.load(fh)
            doc_paras = {p["paragraph_id"]: p["text"] for p in doc.get("paragraphs") or []}
            anchors.update(doc_paras)
            for t in doc.get("tables") or []:
                anchors.add(t.get("anchor"))
                anchors.add("%s/row.%s" % (t.get("table_id"), t.get("row")))
            doc_text = norm(doc.get("text") or "")
        except Exception as exc:  # noqa: BLE001
            warnings.append("doc.json unreadable: %s" % exc)

    seen = set()
    for row in rows or []:
        fid = row.get("field_id")
        add("row_has_field_id", bool(fid), "row without field_id" if not fid else "")
        if fid in seen:
            errors.append("duplicate field_id: %s" % fid)
        seen.add(fid)
        status = row.get("status")
        add("status_valid[%s]" % fid, status in STATUSES, "invalid status %r for %s" % (status, fid))
        if status == "reported":
            value, quote = row.get("value"), row.get("quote") or ""
            add("reported_has_value[%s]" % fid, bool(str(value or "").strip()),
                "%s reported without a value" % fid)
            add("reported_has_quote[%s]" % fid, len(quote.strip()) >= 12,
                "%s reported without a usable quote" % fid)
            if value and quote:
                add("value_verbatim_in_quote[%s]" % fid,
                    norm(str(value)) in norm(quote),
                    "%s value %r is not a verbatim substring of its quote" % (fid, value))
            paragraph_id = row.get("paragraph_id")
            add("anchor_resolves[%s]" % fid, (not doc_paras) or paragraph_id in anchors,
                "%s paragraph_id %r does not resolve in doc.json" % (fid, paragraph_id))
            if quote and doc_text:
                add("quote_found_in_material[%s]" % fid, norm(quote) in doc_text,
                    "%s quote not found verbatim in the indexed material" % fid)
            if row.get("experimental_condition"):
                add("condition_verbatim[%s]" % fid,
                    norm(row["experimental_condition"]) in norm(quote),
                    "%s condition is not a substring of its quote" % fid)
            if row.get("comparator"):
                add("comparator_verbatim[%s]" % fid,
                    norm(row["comparator"]) in norm(quote),
                    "%s comparator is not a substring of its quote" % fid)
        elif status in ("not_reported", "extraction_failed"):
            add("no_value_when_missing[%s]" % fid, row.get("value") in (None, ""),
                "%s must not carry a value when %s" % (fid, status))
        elif status == "source_conflict":
            add("conflict_has_candidates[%s]" % fid, bool(row.get("candidates")),
                "%s source_conflict without candidates" % fid)

    requested = None
    if a.fields and os.path.isfile(a.fields):
        try:
            with open(a.fields, encoding="utf-8") as fh:
                requested = json.load(fh).get("requested")
        except Exception:  # noqa: BLE001
            requested = None
    if isinstance(requested, int):
        add("one_row_per_requested_field", len(rows or []) == requested,
            "%d rows for %d requested fields" % (len(rows or []), requested))

    report = {
        "pass": not errors,
        "errors": errors,
        "warnings": warnings,
        "checks": checks,
        "totals": {
            "errors": len(errors),
            "warnings": len(warnings),
            "checks": len(checks),
            "rows": len(rows or []),
            "reported": sum(1 for r in rows or [] if r.get("status") == "reported"),
        },
    }
    if a.out:
        os.makedirs(os.path.dirname(os.path.abspath(a.out)) or ".", exist_ok=True)
        with open(a.out, "w", encoding="utf-8") as fh:
            json.dump(report, fh, ensure_ascii=False, indent=1)
    print(json.dumps(report, ensure_ascii=False, indent=1))
    return 0 if report["pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
