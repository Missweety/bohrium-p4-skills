#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""audit_result.py - independent review of a reproduction run.

Checks
  contract      all output_contract fields present
  plan          every plan entry has a status in {specified, missing};
                specified entries must carry paragraph_id + quote found in the material
  claims        status vocabulary; inconsistent claims must expose a check with abs_diff
  arithmetic    recompute t->p / z->p / percent change from the stored inputs and
                compare with the stored computed value (guards against hand-written numbers)
  consistency   summary counters equal the actual list lengths

Exit 0 when pass, 1 when errors exist.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
import stats_check  # noqa: E402

CLAIM_STATUS = {"recomputed_consistent", "recomputed_inconsistent",
                "partially_reproduced", "not_reproducible", "not_checkable"}
PLAN_STATUS = {"specified", "missing"}
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
    ap.add_argument("--plan")
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
        print(json.dumps({"pass": False, "errors": ["result unreadable: %s" % exc]},
                         ensure_ascii=False))
        return 1

    contract = {}
    if a.case and os.path.isfile(a.case):
        try:
            with open(a.case, encoding="utf-8") as fh:
                contract = json.load(fh).get("output_contract", {})
        except Exception as exc:  # noqa: BLE001
            warnings.append("case unreadable: %s" % exc)
    required = contract_fields(contract)
    missing = [f for f in required if f not in result]
    add("contract_fields_present", not missing,
        "missing contract fields: %s" % ", ".join(missing) if missing else "")

    doc_text, doc_anchors = "", set()
    if a.doc and os.path.isfile(a.doc):
        try:
            with open(a.doc, encoding="utf-8") as fh:
                doc = json.load(fh)
            doc_text = norm(doc.get("text") or "")
            doc_anchors = {p["paragraph_id"] for p in doc.get("paragraphs") or []}
        except Exception as exc:  # noqa: BLE001
            warnings.append("doc unreadable: %s" % exc)

    payload = {}
    if a.plan and os.path.isfile(a.plan):
        try:
            with open(a.plan, encoding="utf-8") as fh:
                payload = json.load(fh)
        except Exception as exc:  # noqa: BLE001
            warnings.append("plan unreadable: %s" % exc)
    if not payload:
        for key in ("structured", "reproduction"):
            if isinstance(result.get(key), dict) and result[key].get("claims") is not None:
                payload = result[key]
                break

    plan = payload.get("plan") or {}
    for kind, entries in plan.items():
        if entries:
            add("plan_kind_present[%s]" % kind, True)
        elif payload.get("status") == "success":
            add("plan_kind_present[%s]" % kind, False, "plan section %s empty" % kind)
        else:
            warnings.append("plan section %s missing/empty; status=%s（材料未提供，如实留空）"
                            % (kind, payload.get("status")))
        for i, e in enumerate(entries or []):
            add("plan_status_valid[%s.%d]" % (kind, i), e.get("status") in PLAN_STATUS,
                "invalid status %r in plan.%s" % (e.get("status"), kind))
            if e.get("status") == "specified":
                add("plan_has_quote[%s.%d]" % (kind, i), bool((e.get("quote") or "").strip()),
                    "specified plan entry without quote: %s.%d" % (kind, i))
                if doc_text and e.get("quote"):
                    add("plan_quote_in_material[%s.%d]" % (kind, i),
                        norm(e["quote"]) in doc_text,
                        "plan quote not found in material: %s.%d" % (kind, i))
                if doc_anchors:
                    add("plan_anchor_resolves[%s.%d]" % (kind, i),
                        e.get("paragraph_id") in doc_anchors,
                        "plan anchor %r does not resolve" % e.get("paragraph_id"))

    claims = payload.get("claims") or []
    if claims:
        add("claims_non_empty", True)
    elif payload.get("status") == "success":
        add("claims_non_empty", False, "status=success but no claims were extracted")
    else:
        warnings.append("no claims were extracted; status=%s（无可判定陈述，如实留空）"
                        % payload.get("status"))
    for c in claims:
        cid = c.get("claim_id")
        add("claim_status_valid[%s]" % cid, c.get("status") in CLAIM_STATUS,
            "invalid claim status %r for %s" % (c.get("status"), cid))
        add("claim_has_quote[%s]" % cid, bool((c.get("quote") or "").strip()),
            "claim %s without quote" % cid)
        if doc_text and c.get("quote"):
            add("claim_quote_in_material[%s]" % cid, norm(c["quote"]) in doc_text,
                "claim quote not found in material: %s" % cid)
        if c.get("status") == "recomputed_inconsistent":
            bad = [x for x in c.get("checks") or [] if x.get("verdict") == "inconsistent"]
            add("inconsistent_has_evidence[%s]" % cid, bool(bad),
                "inconsistent claim %s has no inconsistent check" % cid)

    for i, ch in enumerate(payload.get("checks") or []):
        test = ch.get("test")
        tag = "%s#%d" % (test, i)
        try:
            if test == "student_t":
                expected = stats_check.t_to_p(ch["inputs"]["t"], ch["inputs"]["df"])
                ok = math.isclose(expected, ch.get("computed_p", -1), rel_tol=1e-9,
                                  abs_tol=1e-6)
            elif test == "normal_z":
                expected = stats_check.z_to_p(ch["inputs"]["z"])
                ok = math.isclose(expected, ch.get("computed_p", -1), rel_tol=1e-9,
                                  abs_tol=1e-6)
            elif test == "percent_change":
                expected = stats_check.percent_change(ch["inputs"]["from"], ch["inputs"]["to"])
                ok = math.isclose(expected, ch.get("computed_pct", 1e9), rel_tol=1e-6,
                                  abs_tol=1e-4)
            else:
                ok, expected = True, None
            add("arithmetic_reproducible[%s]" % tag, ok,
                "%s stored value is not reproducible from its inputs" % tag)
        except Exception as exc:  # noqa: BLE001
            add("arithmetic_reproducible[%s]" % tag, False, "%s: %s" % (tag, exc))

    summary = payload.get("summary") or {}
    if summary:
        add("summary_claims", summary.get("claims") == len(claims),
            "summary.claims=%r but %d claims" % (summary.get("claims"), len(claims)))
        add("summary_checks", summary.get("checks") == len(payload.get("checks") or []),
            "summary.checks mismatch")
        bad = sum(1 for x in payload.get("checks") or []
                  if x.get("verdict") == "inconsistent")
        add("summary_conflicts", summary.get("conflicts") == bad,
            "summary.conflicts=%r but %d inconsistent checks"
            % (summary.get("conflicts"), bad))
        add("summary_status_counts",
            sum(summary.get(k, 0) for k in CLAIM_STATUS) == summary.get("claims"),
            "claim status counters do not add up to claims")

    report = {
        "pass": not errors,
        "errors": errors,
        "warnings": warnings,
        "checks": checks,
        "totals": {"errors": len(errors), "warnings": len(warnings),
                   "checks": len(checks), "claims": len(claims)},
    }
    if a.out:
        os.makedirs(os.path.dirname(os.path.abspath(a.out)) or ".", exist_ok=True)
        with open(a.out, "w", encoding="utf-8") as fh:
            json.dump(report, fh, ensure_ascii=False, indent=1)
    print(json.dumps(report, ensure_ascii=False, indent=1))
    return 0 if report["pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
