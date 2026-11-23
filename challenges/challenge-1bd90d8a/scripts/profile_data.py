#!/usr/bin/env python3
"""profile_data.py - auditable profile of one data table.

Writes data_profile.json next to the work products: per-column parsed name/unit,
inferred type, missing rate, range, duplicate-row count, IQR outliers and warnings.
Nothing is dropped here; exclusions are only ever declared downstream.

Usage: python3 scripts/profile_data.py --input data.csv --out work
Always exits 0 unless the file cannot be parsed.
"""
import argparse
import json
import os
import sys

import tableio


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", required=True)
    ap.add_argument("--out", default="work")
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    try:
        table = tableio.read_any(a.input)
    except Exception as exc:  # noqa: BLE001
        print("FAIL: %s" % exc)
        return 1
    kinds = tableio.classify_columns(table)
    columns = []
    warnings = []
    for j, raw in enumerate(table["header"]):
        parsed = tableio.parse_header(raw)
        vals = []
        for r in table["rows"]:
            v = r[j] if j < len(r) else ""
            if str(v).strip():
                vals.append(v)
        nums = [tableio.to_number(v) for v in vals]
        nums = [x for x in nums if x is not None]
        unique = len(set(str(v).strip() for v in vals))
        info = {"column": j, "raw": raw, "name": parsed["name"], "unit": parsed["unit"],
                "kind": kinds[raw], "non_null": len(vals),
                "missing": len(table["rows"]) - len(vals),
                "missing_rate": round(1 - len(vals) / max(len(table["rows"]), 1), 4),
                "unique": unique}
        if info["kind"] == "numeric" and nums:
            s = sorted(nums)
            q1, q3 = _quantile(s, 0.25), _quantile(s, 0.75)
            iqr = q3 - q1
            lo, hi = q1 - 1.5 * iqr, q3 + 1.5 * iqr
            info.update({"min": min(nums), "max": max(nums),
                         "mean": round(sum(nums) / len(nums), 6),
                         "iqr_outliers": [x for x in nums if x < lo or x > hi][:20]})
            if info["iqr_outliers"]:
                warnings.append("column %s has %d IQR outlier value(s) (retained, flagged)"
                                % (raw, len(info["iqr_outliers"])))
        elif vals:
            info["top"] = sorted({str(v): vals.count(v) for v in set(vals)}.items(),
                                 key=lambda kv: (-kv[1], kv[0]))[:5]
        if unique == 1 and vals:
            warnings.append("column %s is constant" % raw)
        if not vals:
            warnings.append("column %s is entirely empty" % raw)
        columns.append(info)

    dups = tableio.duplicate_rows(table)
    if dups:
        warnings.append("%d exact duplicate row(s) at rows %s (kept and declared)"
                        % (len(dups), ",".join(map(str, dups[:20]))))
    normalized = os.path.join(a.out, "normalized.csv")
    tableio.write_normalized_csv(table, normalized)
    profile = {
        "input": a.input, "name": table["name"], "encoding": table["encoding"],
        "delimiter": table["delimiter"], "sheet": table.get("sheet", ""),
        "rows": table["rows_total"], "columns": table["columns"],
        "sha256": table["sha256"], "bytes": table["bytes"],
        "header_row": 1, "duplicate_rows": {"count": len(dups), "rows": dups},
        "column_profile": columns, "warnings": warnings,
        "short_rows": table["short_rows"], "extra_cells": table["extra_cells"],
        "normalized": "normalized.csv",
        "normalized_sha256": tableio.sha256_file(normalized),
    }
    with open(os.path.join(a.out, "data_profile.json"), "w", encoding="utf-8") as fh:
        json.dump(profile, fh, ensure_ascii=False, indent=1)
    print("rows=%d cols=%d duplicates=%d warnings=%d sheet=%s"
          % (table["rows_total"], table["columns"], len(dups), len(warnings),
             table.get("sheet", "")))
    for w in warnings[:10]:
        print("  ~", w)
    return 0


def _quantile(sorted_vals, q):
    if not sorted_vals:
        return None
    if len(sorted_vals) == 1:
        return sorted_vals[0]
    pos = (len(sorted_vals) - 1) * q
    lo = int(pos)
    hi = min(lo + 1, len(sorted_vals) - 1)
    frac = pos - lo
    return sorted_vals[lo] * (1 - frac) + sorted_vals[hi] * frac


if __name__ == "__main__":
    sys.exit(main())
