#!/usr/bin/env python3
"""plan_figures.py - decide chart types and compute every plotted value from the table.

Deterministic, table-driven planning. Supported chart types:
  bar, grouped_bar, line, scatter, hist, box, heatmap, panel (multi-panel composition).

Every value in chart_plan.json is computed from the source rows and keeps its 1-based
source row numbers. Nothing is typed in by hand. Summary tables (mean + sd/sem/ci + n)
are recognised and used directly instead of being re-aggregated.

Usage:
  python3 scripts/plan_figures.py --input data.csv --out work \
      [--x COL] [--y COL[,COL]] [--group COL] \
      [--intent auto|bar|grouped_bar|line|scatter|hist|box|heatmap|panel] \
      [--error sd|sem|ci95|none] [--hint "task text or path"] [--dedupe none|exact]
"""
import argparse
import hashlib
import json
import math
import os
import re
import statistics
import sys

import tableio
from labels import OKABE, fmt_num

VALID_TYPES = ("bar", "grouped_bar", "line", "scatter", "hist", "box", "heatmap", "panel")
MEAN_ALIASES = {"mean", "average", "avg", "meanvalue", "estimate", "value", "lsmean",
                "leastsquaresmean", "averagevalue"}
SD_ALIASES = {"sd", "std", "stdev", "standarddeviation", "stddev", "sdvalue", "stds"}
SEM_ALIASES = {"sem", "se", "stderr", "standarderror", "semvalue"}
CI_LO_ALIASES = {"cilow", "cilower", "lowerci", "ci95low", "ci95lower", "lcl", "lower",
                 "cilo", "low95ci", "ci_lower", "confidencelower"}
CI_HI_ALIASES = {"cihigh", "ciupper", "upperci", "ci95high", "ci95upper", "ucl", "upper",
                 "cihi", "high95ci", "ci_upper", "confidenceupper"}
N_ALIASES = {"n", "count", "size", "nsamples", "samplesize", "numberofsamples", "nobs",
             "npergroup", "replicates"}
SIG_ALIASES = {"p", "pvalue", "pval", "sig", "significance", "stars", "significant",
               "padj", "adjp", "qvalue", "fdr"}
GENERIC_METRIC_HINTS = ("value", "weight", "length", "count", "score", "rate", "level",
                        "amount", "conc", "dose", "time", "temp", "height", "width",
                        "expression", "intensity", "abundance")

INTENT_WORDS = [
    ("heatmap", r"热图|热力图|heat\s*map|heatmap"),
    ("box", r"箱线图|箱型图|盒须图|box\s*-?\s*plot|boxplot"),
    ("grouped_bar", r"分组柱|群组柱|grouped\s*bar|clustered\s*bar|簇状柱"),
    ("panel", r"多面板|多图|组合图|分面|子图|multi[\s-]*panel|subplot|panel\s*[abcd]\b|fac(et|etted)"),
    ("bar", r"柱状图|柱形图|条形图|bar\s*chart|bar\s*plot|source_value_chart"),
    ("line", r"折线图|曲线图|时间序列|line\s*chart|line\s*plot|trend"),
    ("scatter", r"散点图|scatter"),
    ("hist", r"直方图|频数分布|histogram|distribution"),
]


def norm_name(raw):
    name = tableio.parse_header(raw)["name"]
    return re.sub(r"[^0-9a-z\u4e00-\u9fff]", "", name.lower())


def find_alias(header, aliases):
    for j, raw in enumerate(header):
        if norm_name(raw) in aliases:
            return raw
    return ""


def quantile(sorted_vals, q):
    if not sorted_vals:
        return None
    if len(sorted_vals) == 1:
        return sorted_vals[0]
    pos = (len(sorted_vals) - 1) * q
    lo = int(pos)
    hi = min(lo + 1, len(sorted_vals) - 1)
    frac = pos - lo
    return sorted_vals[lo] * (1 - frac) + sorted_vals[hi] * frac


def stat_block(values, error_code):
    """values: [(row, float)]. Returns n/mean/sd/sem/ci95/error/error_type."""
    nums = [v for _, v in values]
    n = len(nums)
    if not n:
        return {"n": 0, "mean": None, "sd": None, "sem": None, "ci95": None,
                "error": None, "error_type": None}
    mean = statistics.fmean(nums)
    sd = statistics.stdev(nums) if n > 1 else None
    sem = (sd / math.sqrt(n)) if (sd is not None and n > 1) else None
    ci = (1.96 * sem) if sem is not None else None
    error, etype = None, None
    if n >= 3:
        if error_code == "sd" and sd is not None:
            error, etype = sd, "SD"
        elif error_code == "sem" and sem is not None:
            error, etype = sem, "SEM"
        elif error_code == "ci95" and ci is not None:
            error, etype = ci, "95% CI"
    return {"n": n, "mean": round(mean, 6), "sd": _r(sd), "sem": _r(sem),
            "ci95": _r(ci), "error": _r(error), "error_type": etype}


def _r(v):
    return None if v is None else round(float(v), 6)


def box_block(label, values):
    rows = [r for r, _ in values]
    nums = sorted(v for _, v in values)
    if not nums:
        return None
    q1, med, q3 = quantile(nums, 0.25), quantile(nums, 0.5), quantile(nums, 0.75)
    iqr = q3 - q1
    lo_fence, hi_fence = q1 - 1.5 * iqr, q3 + 1.5 * iqr
    inside = [v for v in nums if lo_fence <= v <= hi_fence]
    outliers = [{"value": round(v, 6), "row": r} for r, v in values
                if v < lo_fence or v > hi_fence]
    return {"label": str(label), "n": len(nums), "min": round(min(inside), 6),
            "q1": round(q1, 6), "median": round(med, 6), "q3": round(q3, 6),
            "max": round(max(inside), 6), "whisker_low_row": _row_of(values, min(inside)),
            "whisker_high_row": _row_of(values, max(inside)),
            "outliers": outliers, "source_rows": rows}


def _row_of(values, target):
    for r, v in values:
        if abs(v - target) < 1e-9:
            return r
    return None


def ordered_labels(pairs, kind):
    """Unique labels in first-appearance order; dates sorted ascending."""
    seen = []
    for label, _ in pairs:
        label = str(label)
        if label not in seen:
            seen.append(label)
    if kind == "date":
        seen.sort(key=lambda s: s)
    return seen


def detect_summary(table, kinds, opts):
    header = table["header"]
    mean_col = find_alias(header, MEAN_ALIASES)
    sd_col = find_alias(header, SD_ALIASES)
    sem_col = find_alias(header, SEM_ALIASES)
    lo_col = find_alias(header, CI_LO_ALIASES)
    hi_col = find_alias(header, CI_HI_ALIASES)
    n_col = find_alias(header, N_ALIASES)
    has_ci = bool(lo_col and hi_col)
    if not mean_col or not (sd_col or sem_col or has_ci):
        return None
    if kinds.get(mean_col) != "numeric":
        return None
    cats = [h for h in header if kinds.get(h) in ("categorical", "date")]
    return {"mean": mean_col, "sd": sd_col, "sem": sem_col,
            "ci_lo": lo_col, "ci_hi": hi_col, "n": n_col,
            "categories": cats}


def row_number(i):
    return i + 2


def build_summary_panel(table, kinds, summary, opts, x_col, series_col, title, error_code):
    header = table["header"]
    mean_j = header.index(summary["mean"])
    rows = table["rows"]
    x_col = x_col or (summary["categories"][0] if summary["categories"] else "")
    used = {summary["mean"], summary["sd"], summary["sem"], summary["ci_lo"],
            summary["ci_hi"], summary["n"], x_col, series_col}
    series_labels = []
    if not series_col:
        series_labels = [""]
    else:
        series_labels = ordered_labels(
            [(r[header.index(series_col)], r) for r in rows], kinds.get(series_col))
        if len(series_labels) > 8:
            series_labels = series_labels[:7] + ["Other"]

    def pick_error(raw_row):
        """Use the column that actually exists, in the requested order."""
        def val(col):
            if not col:
                return None
            j = header.index(col)
            return tableio.to_number(raw_row[j]) if j < len(raw_row) else None
        sd, sem = val(summary["sd"]), val(summary["sem"])
        lo, hi = val(summary["ci_lo"]), val(summary["ci_hi"])
        if error_code == "none":
            return None, None
        if error_code == "sd" and sd is not None:
            return abs(sd), "SD"
        if error_code == "sem" and sem is not None:
            return abs(sem), "SEM"
        if error_code == "ci95" and lo is not None and hi is not None:
            return abs(hi - lo) / 2.0, "95% CI"
        if sd is not None:
            return abs(sd), "SD"
        if sem is not None:
            return abs(sem), "SEM"
        if lo is not None and hi is not None:
            return abs(hi - lo) / 2.0, "95% CI"
        return None, None

    categories = ordered_labels(
        [(r[header.index(x_col)] if x_col else "all", r) for r in rows],
        kinds.get(x_col, "")) if x_col else ["all"]
    if len(categories) > 12:
        categories = categories[:11] + ["Other"]
    groups = {}
    for i, r in enumerate(rows):
        label = str(r[header.index(x_col)]).strip() if x_col and header.index(x_col) < len(r) else "all"
        if label not in categories:
            label = "Other"
        s_label = str(r[header.index(series_col)]).strip() if series_col else ""
        if series_col and s_label not in series_labels:
            s_label = "Other"
        m = tableio.to_number(r[mean_j]) if mean_j < len(r) else None
        if m is None:
            continue
        err, etype = pick_error(r)
        n_raw = (tableio.to_number(r[header.index(summary["n"])])
                 if summary["n"] and header.index(summary["n"]) < len(r) else None)
        n = int(round(n_raw)) if n_raw is not None else None
        if n is not None and n < 3:
            err, etype = None, None
        groups.setdefault(s_label, {}).setdefault(label, []).append(
            {"value": round(m, 6), "error": _r(err), "error_type": etype, "n": n,
             "source_rows": [row_number(i)], "raw": m})
    series = []
    for k, s_label in enumerate(series_labels):
        cats = []
        for label in categories:
            items = groups.get(s_label, {}).get(label, [])
            if not items:
                continue
            values = [it["raw"] for it in items]
            errors = [it["error"] for it in items if it["error"] is not None]
            ns = [it["n"] for it in items if it["n"] is not None]
            cats.append({"label": label,
                         "value": round(statistics.fmean(values), 6),
                         "error": _r(statistics.fmean(errors)) if errors else None,
                         "error_type": items[0]["error_type"] if errors else None,
                         "n": int(sum(ns)) if ns else None,
                         "source_rows": [r for it in items for r in it["source_rows"]]})
        label = s_label or _display(header[mean_j])
        series.append({"label": label, "color": OKABE[k % len(OKABE)],
                       "error_type": cats[0]["error_type"] if cats else None,
                       "values": cats})
    panel = {"chart_type": "grouped_bar" if series_col else "bar",
             "title": title, "fields": {
                 "x": _field(header, x_col, kinds),
                 "y": _field(header, summary["mean"], kinds),
                 "group": _field(header, series_col, kinds)},
             "categories": categories, "series": series, "points": [], "bins": [],
             "boxes": [], "cells": [], "row_labels": [], "col_labels": [],
             "color_scale": {}, "used_columns": sorted(u for u in used if u)}
    return panel


def _field(header, raw, kinds):
    if not raw:
        return {"raw": "", "name": "", "kind": "", "unit": "", "column": None}
    j = header.index(raw)
    parsed = tableio.parse_header(raw)
    return {"raw": raw, "name": parsed["name"], "unit": parsed["unit"],
            "kind": kinds.get(raw, ""), "column": j}


def _display(raw):
    if not raw:
        return ""
    parsed = tableio.parse_header(raw)
    if parsed["unit"] and parsed["unit"] not in parsed["name"]:
        return "%s (%s)" % (parsed["name"], parsed["unit"])
    return parsed["name"]


def add_significance(table, kinds, panels):
    """Only surface significance that is literally present in the source."""
    header = table["header"]
    notes = []
    for raw in header:
        if norm_name(raw) in SIG_ALIASES:
            j = header.index(raw)
            vals = []
            for i, r in enumerate(table["rows"]):
                v = str(r[j]).strip() if j < len(r) else ""
                if v:
                    vals.append({"row": row_number(i), "value": v})
            if vals:
                notes.append({"column": raw, "values": vals,
                              "text": "%s (source-provided, not recomputed): %s"
                                      % (raw, "; ".join("row %d=%s" % (v["row"], v["value"])
                                                        for v in vals[:8]))})
    return notes


def build_bar_panel(table, kinds, x_col, y_col, opts, title, series_col=""):
    header = table["header"]
    xi = header.index(x_col) if x_col else None
    yi = header.index(y_col)
    used_rows, skipped = [], []
    groups = {}
    labels_all = []
    missing_by_group = {}
    for i, r in enumerate(table["rows"]):
        y = tableio.to_number(r[yi]) if yi < len(r) else None
        label = str(r[xi]).strip() if xi is not None and xi < len(r) else "all"
        if not label:
            label = "(no label)"
        if y is None:
            skipped.append(row_number(i))
            missing_by_group[label] = missing_by_group.get(label, 0) + 1
            continue
        if label not in labels_all:
            labels_all.append(label)
        groups.setdefault(label, []).append((row_number(i), y))
        used_rows.append(row_number(i))
    labels = ordered_labels([(l, None) for l in labels_all], kinds.get(x_col, ""))
    if len(labels) > 12:
        keep = labels[:11]
        other = [l for l in labels if l not in keep]
        merged = []
        for l in other:
            merged += groups.pop(l, [])
        if merged:
            groups["Other"] = merged
        labels = keep + ["Other"]

    def make_series(label, subset, color):
        values = []
        for cat in labels:
            items = subset.get(cat, [])
            if not items:
                continue
            st = stat_block(items, opts.error)
            values.append({"label": cat, "value": st["mean"], "error": st["error"],
                           "error_type": st["error_type"], "n": st["n"],
                           "source_rows": [rr for rr, _ in items]})
        return {"label": label, "color": color,
                "error_type": values[0]["error_type"] if values else None,
                "values": values}

    series = []
    if series_col:
        si = header.index(series_col)
        s_labels = ordered_labels(
            [(r[si], r) for r in table["rows"] if str(r[si]).strip()],
            kinds.get(series_col, ""))
        if len(s_labels) > 8:
            s_labels = s_labels[:7] + ["Other"]
        subset = {}
        for i, r in enumerate(table["rows"]):
            y = tableio.to_number(r[yi]) if yi < len(r) else None
            if y is None:
                continue
            lab = str(r[xi]).strip() if xi is not None and xi < len(r) else "all"
            if lab not in labels:
                lab = "Other"
            s_lab = str(r[si]).strip() if si < len(r) else ""
            if s_lab not in s_labels:
                s_lab = "Other"
            subset.setdefault(s_lab, {}).setdefault(lab, []).append((row_number(i), y))
        for k, s_lab in enumerate(s_labels):
            series.append(make_series(s_lab, subset.get(s_lab, {}), OKABE[k % len(OKABE)]))
        chart = "grouped_bar"
    else:
        series = [make_series(_display(y_col), groups, OKABE[0])]
        chart = "bar"
    panel = {"chart_type": chart, "title": title,
             "fields": {"x": _field(header, x_col, kinds), "y": _field(header, y_col, kinds),
                        "group": _field(header, series_col, kinds)},
             "categories": labels, "series": series, "points": [], "bins": [], "boxes": [],
             "cells": [], "row_labels": [], "col_labels": [], "color_scale": {},
             "used_columns": [c for c in (x_col, y_col, series_col) if c],
             "missing_by_group": missing_by_group, "_skipped": skipped}
    return panel


def build_line_panel(table, kinds, x_col, y_col, opts, title, series_col=""):
    header = table["header"]
    xi = header.index(x_col) if x_col else None
    yi = header.index(y_col)
    si = header.index(series_col) if series_col else None
    labels = ordered_labels(
        [(r[xi], r) for r in table["rows"] if xi is not None and xi < len(r)],
        kinds.get(x_col, ""))
    if len(labels) > 24:
        labels = labels[:24]
    s_labels = [""] if not series_col else ordered_labels(
        [(r[si], r) for r in table["rows"] if str(r[si]).strip()], kinds.get(series_col, ""))
    if len(s_labels) > 8:
        s_labels = s_labels[:7] + ["Other"]
    buckets = {}
    skipped = []
    for i, r in enumerate(table["rows"]):
        y = tableio.to_number(r[yi]) if yi < len(r) else None
        if y is None:
            skipped.append(row_number(i))
            continue
        label = str(r[xi]).strip() if xi is not None and xi < len(r) else "all"
        if label not in labels:
            continue
        s_lab = str(r[si]).strip() if si is not None and si < len(r) else ""
        if series_col and s_lab not in s_labels:
            s_lab = "Other"
        buckets.setdefault(s_lab, {}).setdefault(label, []).append((row_number(i), y))
    points = []
    series = []
    repeated = False  # stays False when no series/labels yield any point
    for k, s_lab in enumerate(s_labels):
        sub = buckets.get(s_lab, {})
        if not sub:
            continue
        # replicate x values are aggregated so the line shows the group mean with error
        repeated = any(len(v) > 1 for v in sub.values())
        pts = []
        for pos, label in enumerate(labels):
            items = sub.get(label, [])
            if not items:
                continue
            st = stat_block(items, opts.error)
            pts.append({"x": label, "xi": pos, "y": st["mean"], "error": st["error"],
                        "error_type": st["error_type"], "n": st["n"],
                        "row": items[0][0], "source_rows": [r for r, _ in items],
                        "series": s_lab or _display(y_col)})
        points += pts
        series.append({"label": s_lab or _display(y_col), "color": OKABE[k % len(OKABE)],
                       "error_type": pts[0]["error_type"] if pts else None, "values": []})
    panel = {"chart_type": "line", "title": title,
             "fields": {"x": _field(header, x_col, kinds), "y": _field(header, y_col, kinds),
                        "group": _field(header, series_col, kinds)},
             "categories": labels, "series": series, "points": points, "bins": [],
             "boxes": [], "cells": [], "row_labels": [], "col_labels": [], "color_scale": {},
             "used_columns": [c for c in (x_col, y_col, series_col) if c],
             "line_aggregated": repeated, "_skipped": skipped}
    return panel


def build_scatter_panel(table, kinds, x_col, y_col, opts, title, group_col=""):
    header = table["header"]
    xi, yi = header.index(x_col), header.index(y_col)
    gi = header.index(group_col) if group_col else None
    points, skipped, rows = [], [], []
    g_labels = [""] if not group_col else ordered_labels(
        [(r[gi], r) for r in table["rows"] if str(r[gi]).strip()], kinds.get(group_col, ""))
    if len(g_labels) > 8:
        g_labels = g_labels[:7] + ["Other"]
    for i, r in enumerate(table["rows"]):
        xv = tableio.to_number(r[xi]) if xi < len(r) else None
        yv = tableio.to_number(r[yi]) if yi < len(r) else None
        if xv is None or yv is None:
            skipped.append(row_number(i))
            continue
        g = str(r[gi]).strip() if gi is not None and gi < len(r) else ""
        if group_col and g not in g_labels:
            g = "Other"
        points.append({"x": round(xv, 6), "y": round(yv, 6), "row": row_number(i),
                       "source_rows": [row_number(i)], "group": g})
        rows.append(row_number(i))
    panel = {"chart_type": "scatter", "title": title,
             "fields": {"x": _field(header, x_col, kinds), "y": _field(header, y_col, kinds),
                        "group": _field(header, group_col, kinds)},
             "categories": [], "series": [
                 {"label": g or _display(y_col), "color": OKABE[k % len(OKABE)],
                  "error_type": None, "values": []} for k, g in enumerate(g_labels)],
             "points": points, "bins": [], "boxes": [], "cells": [],
             "row_labels": [], "col_labels": [], "color_scale": {},
             "used_columns": [c for c in (x_col, y_col, group_col) if c],
             "_skipped": skipped}
    return panel


def build_hist_panel(table, kinds, y_col, opts, title):
    header = table["header"]
    yi = header.index(y_col)
    vals, skipped = [], []
    for i, r in enumerate(table["rows"]):
        v = tableio.to_number(r[yi]) if yi < len(r) else None
        if v is None:
            skipped.append(row_number(i))
            continue
        vals.append((row_number(i), v))
    if not vals:
        return None
    lo, hi = min(v for _, v in vals), max(v for _, v in vals)
    if hi <= lo:
        bins = [{"lo": round(lo - 0.5, 6), "hi": round(hi + 0.5, 6), "count": len(vals),
                 "rows": [r for r, _ in vals]}]
    else:
        width = (hi - lo) / 10
        bins = [{"lo": round(lo + width * k, 6), "hi": round(lo + width * (k + 1), 6),
                 "count": 0, "rows": []} for k in range(10)]
        for r, v in vals:
            idx = min(int((v - lo) / width), 9)
            bins[idx]["count"] += 1
            bins[idx]["rows"].append(r)
    panel = {"chart_type": "hist", "title": title,
             "fields": {"x": {"raw": "", "name": _display(y_col), "kind": "numeric",
                              "unit": tableio.parse_header(y_col)["unit"], "column": yi},
                        "y": _field(header, y_col, kinds),
                        "group": {"raw": "", "name": "", "kind": "", "unit": "", "column": None}},
             "categories": [], "series": [{"label": _display(y_col), "color": OKABE[0],
                                           "error_type": None, "values": []}],
             "points": [], "bins": bins, "boxes": [], "cells": [],
             "row_labels": [], "col_labels": [], "color_scale": {},
             "used_columns": [y_col], "_skipped": skipped}
    return panel


def build_box_panel(table, kinds, x_col, y_col, opts, title):
    header = table["header"]
    xi = header.index(x_col) if x_col else None
    yi = header.index(y_col)
    groups, order, skipped = {}, [], []
    for i, r in enumerate(table["rows"]):
        y = tableio.to_number(r[yi]) if yi < len(r) else None
        if y is None:
            skipped.append(row_number(i))
            continue
        label = str(r[xi]).strip() if xi is not None and xi < len(r) else "all"
        if label not in order:
            order.append(label)
        groups.setdefault(label, []).append((row_number(i), y))
    order = ordered_labels([(l, None) for l in order], kinds.get(x_col, ""))
    if len(order) > 10:
        order = order[:9] + ["Other"]
        groups.setdefault("Other", [])
    boxes = [b for b in (box_block(l, groups.get(l, [])) for l in order) if b]
    panel = {"chart_type": "box", "title": title,
             "fields": {"x": _field(header, x_col, kinds), "y": _field(header, y_col, kinds),
                        "group": {"raw": "", "name": "", "kind": "", "unit": "", "column": None}},
             "categories": order,
             "series": [{"label": _display(y_col), "color": OKABE[0],
                         "error_type": "IQR whiskers (1.5\u00d7IQR)", "values": []}],
             "points": [], "bins": [], "boxes": boxes, "cells": [],
             "row_labels": [], "col_labels": [], "color_scale": {},
             "used_columns": [c for c in (x_col, y_col) if c], "_skipped": skipped}
    return panel


def build_heatmap_matrix_panel(table, kinds, row_col, value_cols, opts, title):
    header = table["header"]
    ri = header.index(row_col)
    row_labels, cells, skipped = [], [], []
    units = set()
    for i, r in enumerate(table["rows"]):
        label = str(r[ri]).strip() if ri < len(r) else ""
        if not label:
            continue
        row_labels.append(label)
        any_val = False
        for col in value_cols:
            j = header.index(col)
            v = tableio.to_number(r[j]) if j < len(r) else None
            if v is None:
                continue
            any_val = True
            parsed = tableio.parse_header(col)
            if parsed["unit"]:
                units.add(parsed["unit"])
            cells.append({"row_label": label, "col_label": parsed["name"],
                          "value": round(v, 6), "n": 1, "field": col,
                          "column": j, "source_rows": [row_number(i)]})
        if not any_val:
            skipped.append(row_number(i))
    if not cells:
        return None
    vals = [c["value"] for c in cells]
    lo, hi = min(vals), max(vals)
    col_labels = []
    for col in value_cols:
        n = tableio.parse_header(col)["name"]
        if n not in col_labels:
            col_labels.append(n)
    unit = units.pop() if len(units) == 1 else ""
    panel = {"chart_type": "heatmap", "title": title,
             "fields": {"x": {"raw": "", "name": "conditions", "kind": "categorical",
                              "unit": "", "column": None},
                        "y": {"raw": "", "name": "value", "kind": "numeric", "unit": unit,
                              "column": None},
                        "group": _field(header, row_col, kinds),
                        "value_columns": [{"raw": c, "name": tableio.parse_header(c)["name"],
                                           "unit": tableio.parse_header(c)["unit"],
                                           "column": header.index(c)} for c in value_cols]},
             "categories": col_labels,
             "series": [{"label": _display(value_cols[0]) if value_cols else "value",
                         "color": OKABE[0], "error_type": None, "values": []}],
             "points": [], "bins": [], "boxes": [], "cells": cells,
             "row_labels": row_labels, "col_labels": col_labels,
             "color_scale": {"min": round(lo, 6), "max": round(hi, 6),
                             "label": "value (%s)" % unit if unit else "value",
                             "units_mixed": len(units) > 1},
             "used_columns": [row_col] + list(value_cols), "_skipped": skipped,
             "missing_cells": len(row_labels) * len(value_cols) - len(cells)}
    return panel


def build_heatmap_long_panel(table, kinds, row_col, col_col, y_col, opts, title):
    header = table["header"]
    ri, ci, yi = header.index(row_col), header.index(col_col), header.index(y_col)
    bucket, row_order, col_order, skipped = {}, [], [], []
    for i, r in enumerate(table["rows"]):
        v = tableio.to_number(r[yi]) if yi < len(r) else None
        if v is None:
            skipped.append(row_number(i))
            continue
        rl = str(r[ri]).strip() if ri < len(r) else ""
        cl = str(r[ci]).strip() if ci < len(r) else ""
        if not rl or not cl:
            skipped.append(row_number(i))
            continue
        if rl not in row_order:
            row_order.append(rl)
        if cl not in col_order:
            col_order.append(cl)
        bucket.setdefault((rl, cl), []).append((row_number(i), v))
    row_order = row_order[:30]
    col_order = col_order[:12]
    cells = []
    for rl in row_order:
        for cl in col_order:
            items = bucket.get((rl, cl), [])
            if not items:
                continue
            st = stat_block(items, "none")
            cells.append({"row_label": rl, "col_label": cl, "value": st["mean"],
                          "n": st["n"], "field": y_col, "column": yi,
                          "source_rows": [r for r, _ in items]})
    if not cells:
        return None
    vals = [c["value"] for c in cells]
    unit = tableio.parse_header(y_col)["unit"]
    panel = {"chart_type": "heatmap", "title": title,
             "fields": {"x": _field(header, col_col, kinds), "y": _field(header, y_col, kinds),
                        "group": _field(header, row_col, kinds)},
             "categories": col_order,
             "series": [{"label": _display(y_col), "color": OKABE[0],
                         "error_type": None, "values": []}],
             "points": [], "bins": [], "boxes": [], "cells": cells,
             "row_labels": row_order, "col_labels": col_order,
             "color_scale": {"min": round(min(vals), 6), "max": round(max(vals), 6),
                             "label": _display(y_col), "units_mixed": False},
             "used_columns": [row_col, col_col, y_col], "_skipped": skipped,
             "missing_cells": len(row_order) * len(col_order) - len(cells)}
    return panel


def parse_hint(text):
    if not text:
        return ""
    if os.path.isfile(text):
        text = open(text, encoding="utf-8", errors="replace").read()
    low = text.lower()
    for intent, pattern in INTENT_WORDS:
        if re.search(pattern, low):
            return intent
    return ""


def _usable_cat(table, name, max_missing=0.3):
    """A grouping column is usable only if it has >=2 values and is not mostly empty."""
    if not name or name not in table["header"]:
        return False
    j = table["header"].index(name)
    vals = [str(r[j]).strip() if j < len(r) else "" for r in table["rows"]]
    total = len(vals) or 1
    present = [v for v in vals if v.lower() not in tableio.MISSING_TOKENS]
    if len(set(present)) < 2:
        return False  # constant column cannot define groups
    return (total - len(present)) / float(total) <= max_missing


def choose_plan(table, kinds, opts):
    header = table["header"]
    numeric = [h for h in header if kinds.get(h) == "numeric"]
    date_cols = [h for h in header if kinds.get(h) == "date"]
    cat_cols = [h for h in header if kinds.get(h) == "categorical"]
    usable_cat = [c for c in cat_cols if _usable_cat(table, c)]
    all_rows = table["rows_total"]
    warnings = []
    intent = opts.intent
    if intent == "auto" and opts.hint_intent:
        intent = opts.hint_intent
        warnings.append("intent inferred from task text: %s" % intent)

    def col_or_fail(name, role):
        if not name:
            return ""
        resolved = _resolve(name, header)
        if not resolved:
            raise SystemExit("FAIL: %s %r does not match any column; available: %s"
                             % (role, name, header))
        return resolved

    x = col_or_fail(opts.x, "--x")
    y_list = [col_or_fail(part.strip(), "--y") for part in opts.y.split(",") if part.strip()]
    group = col_or_fail(opts.group, "--group")

    summary = detect_summary(table, kinds, opts)
    if summary and intent in ("auto", "bar", "grouped_bar", "panel"):
        x_col = x or (summary["categories"][0] if summary["categories"] else "")
        series_col = group or (summary["categories"][1] if len(summary["categories"]) > 1 else "")
        title = "%s by %s" % (_display(summary["mean"]), _display(x_col) if x_col else "group")
        panel = build_summary_panel(table, kinds, summary, opts, x_col, series_col, title,
                                    opts.error)
        panel["id"] = "A"
        panel["summary_mode"] = True
        return "panel", [panel], warnings, {"mode": "summary", "summary_columns": summary}

    if not numeric:
        raise SystemExit("FAIL: no numeric column found; cannot map data to marks")

    y_cols = y_list or [c for c in numeric]
    if not x:
        x = (date_cols or usable_cat or cat_cols or [""])[0]
    if not x and intent in ("line", "scatter") and len(numeric) >= 2:
        # two numeric columns and no category/date: the first is the ordered x,
        # the second is the measured y (e.g. "day vs value" -> x=day, y=value)
        x = numeric[0]
    if not y_list:
        # keep a single value column unless a panel/multi-metric shape is implied
        y_cols = [c for c in numeric if c != x]
        if not y_cols:
            y_cols = numeric[:]
    primary_y = y_list[0] if y_list else y_cols[0]

    def single(chart, **kw):
        if chart == "bar":
            x_col = x or (usable_cat[0] if usable_cat else
                          (cat_cols[0] if cat_cols else ""))
            return build_bar_panel(table, kinds, x_col, primary_y, opts,
                                   "%s by %s" % (_display(primary_y), _display(x_col) or "group"),
                                   group)
        if chart == "grouped_bar":
            x_col = x or (usable_cat[0] if usable_cat else
                          (cat_cols[0] if cat_cols else ""))
            pool = [c for c in usable_cat if c != x_col]
            s_col = group or (pool[0] if pool else "")
            if not s_col:
                return build_bar_panel(table, kinds, x_col, primary_y, opts,
                                       "%s by %s" % (_display(primary_y), _display(x_col)), "")
            return build_bar_panel(table, kinds, x_col, primary_y, opts,
                                   "%s by %s and %s" % (_display(primary_y), _display(x_col),
                                                        _display(s_col)), s_col)
        if chart == "line":
            # an ordered x can also be a second numeric column (e.g. day vs value);
            # without this a two-numeric table crashed with no x column at all.
            x_col = x or (date_cols or cat_cols
                          or [c for c in numeric if c != primary_y] or [""])[0]
            if not x_col or x_col == primary_y:
                return None
            return build_line_panel(table, kinds, x_col, primary_y, opts,
                                    "%s over %s" % (_display(primary_y), _display(x_col)),
                                    group)
        if chart == "scatter":
            x_col = x or next((c for c in numeric if c != primary_y), "")
            if not x_col or x_col == primary_y:
                return None
            return build_scatter_panel(table, kinds, x_col, primary_y, opts,
                                       "%s vs %s" % (_display(primary_y), _display(x_col)),
                                       group)
        if chart == "hist":
            return build_hist_panel(table, kinds, primary_y, opts,
                                    "Distribution of %s" % _display(primary_y))
        if chart == "box":
            x_col = x or (cat_cols[0] if cat_cols else "")
            return build_box_panel(table, kinds, x_col, primary_y, opts,
                                   "%s distribution by %s"
                                   % (_display(primary_y), _display(x_col) or "group"))
        return None

    # ---------------------------------------------------------------- explicit intent
    if intent in ("bar", "grouped_bar", "line", "scatter", "hist", "box"):
        panel = single(intent)
        if panel is None:
            raise SystemExit("FAIL: %s needs two distinct numeric columns" % intent)
        panel["id"] = "A"
        return "panel", [panel], warnings, {"mode": "single", "intent": intent}

    # ---------------------------------------------------------------- heatmap
    if intent == "heatmap":
        panel = _heatmap_candidate(table, kinds, opts, x, group, primary_y, warnings)
        if panel is None:
            warnings.append("heatmap requested but no two-factor / matrix shape found; "
                            "falling back to grouped bar")
            panel = single("grouped_bar")
            if panel is None:
                panel = single("bar")
        panel["id"] = "A"
        return "panel", [panel], warnings, {"mode": "single", "intent": "heatmap"}

    # ---------------------------------------------------------------- panel
    if intent == "panel":
        panels = _panel_family(table, kinds, opts, x, y_cols, group, warnings)
        if len(panels) <= 1:
            panel = panels[0] if panels else single("bar")
            panel["id"] = "A"
            return "panel", [panel], warnings, {"mode": "single", "intent": "panel"}
        for k, p in enumerate(panels):
            p["id"] = chr(ord("A") + k)
        return "panel", panels, warnings, {"mode": "panel", "intent": "panel"}

    # ---------------------------------------------------------------- auto
    matrix = _matrix_candidate(table, kinds, x, y_cols, cat_cols)
    if date_cols and numeric:
        panel = build_line_panel(table, kinds, date_cols[0], primary_y, opts,
                                 "%s over %s" % (_display(primary_y), _display(date_cols[0])),
                                 group)
        panel["id"] = "A"
        return "panel", [panel], warnings, {"mode": "single", "reason": "date column"}
    if len(numeric) >= 2 and not cat_cols:
        p = build_scatter_panel(table, kinds, numeric[0], numeric[1], opts,
                                "%s vs %s" % (_display(numeric[1]), _display(numeric[0])),
                                group)
        p["id"] = "A"
        return "panel", [p], warnings, {"mode": "single", "reason": "two numeric columns"}
    if len(numeric) == 1:
        if cat_cols:
            x_col = x or cat_cols[0]
            groups = {str(r[header.index(x_col)]).strip() for r in table["rows"]}
            p = build_bar_panel(table, kinds, x_col, numeric[0], opts,
                                "%s by %s" % (_display(numeric[0]), _display(x_col)), group)
            if p is None:
                p = build_hist_panel(table, kinds, numeric[0], opts,
                                     "Distribution of %s" % _display(numeric[0]))
                p["id"] = "A"
                return "panel", [p], warnings, {"mode": "single", "reason": "no repeated groups"}
            p["id"] = "A"
            return "panel", [p], warnings, {"mode": "single", "reason": "%d categories" % len(groups)}
        p = build_hist_panel(table, kinds, numeric[0], opts,
                             "Distribution of %s" % _display(numeric[0]))
        p["id"] = "A"
        return "panel", [p], warnings, {"mode": "single", "reason": "single numeric column"}
    # >=2 numeric with categories
    if matrix:
        panel = build_heatmap_matrix_panel(table, kinds, matrix, y_cols, opts,
                                           "Heatmap of %s" % _display(y_cols[0]))
        if panel:
            panel["id"] = "A"
            return "panel", [panel], warnings, {"mode": "single", "reason": "matrix shape"}
    if len(usable_cat) >= 2:
        x_col = x or usable_cat[0]
        s_col = group or next((c for c in usable_cat if c != x_col), "")
        p = build_bar_panel(table, kinds, x_col, primary_y, opts,
                            "%s by %s and %s" % (_display(primary_y), _display(x_col),
                                                 _display(s_col)), s_col)
        p["id"] = "A"
        return "panel", [p], warnings, {"mode": "single", "reason": "two categorical factors"}
    panels = _panel_family(table, kinds, opts, x, y_cols, group, warnings)
    for k, p in enumerate(panels):
        p["id"] = chr(ord("A") + k)
    if len(panels) == 1:
        return "panel", panels, warnings, {"mode": "single", "reason": "one usable metric"}
    return "panel", panels, warnings, {"mode": "panel", "reason": "multiple numeric metrics"}


def _resolve(name, header):
    if not name:
        return ""
    if name in header:
        return name
    key = re.sub(r"[\s_\-()\[\]（）]", "", str(name)).lower()
    for h in header:
        if re.sub(r"[\s_\-()\[\]（）]", "", h).lower() == key:
            return h
    cands = [h for h in header if re.sub(r"[\s_\-()\[\]（）]", "", h).lower().startswith(key)]
    return cands[0] if len(cands) == 1 else ""


def _matrix_candidate(table, kinds, x, y_cols, cat_cols):
    """Return a row-label column when the table looks like rows x conditions."""
    header = table["header"]
    for cand in [x] + cat_cols:
        if not cand:
            continue
        j = header.index(cand)
        vals = [str(r[j]).strip() for r in table["rows"] if j < len(r)]
        if len(vals) != table["rows_total"] or len(set(vals)) != len(vals):
            continue
        if table["rows_total"] < 3:
            continue
        numeric_cols = [h for h in header if kinds.get(h) == "numeric" and h != cand]
        if len(numeric_cols) < 2:
            continue
        generic = [c for c in numeric_cols
                   if any(k in tableio.parse_header(c)["name"].lower()
                          for k in GENERIC_METRIC_HINTS)]
        if generic and table["rows_total"] < 8:
            continue  # looks like per-sample metrics, not a condition matrix
        return cand
    return ""


def _heatmap_candidate(table, kinds, opts, x, group, primary_y, warnings):
    header = table["header"]
    cat_cols = [h for h in header if kinds.get(h) == "categorical"]
    numeric = [h for h in header if kinds.get(h) == "numeric"]
    if group and x and primary_y:
        return build_heatmap_long_panel(table, kinds, group, x, primary_y, opts,
                                        "%s heatmap: %s by %s"
                                        % (_display(primary_y), _display(group), _display(x)))
    if x and len(numeric) >= 2:
        rc = _matrix_candidate(table, kinds, x, numeric, cat_cols)
        if rc:
            cols = [c for c in numeric if c != rc]
            return build_heatmap_matrix_panel(table, kinds, rc, cols, opts,
                                              "Heatmap across %d conditions" % len(cols))
    if len(cat_cols) >= 2 and numeric:
        return build_heatmap_long_panel(table, kinds, cat_cols[0], cat_cols[1], numeric[0],
                                        opts, "%s heatmap by %s and %s"
                                        % (_display(numeric[0]), _display(cat_cols[0]),
                                           _display(cat_cols[1])))
    if len(numeric) >= 2 and cat_cols:
        rc = _matrix_candidate(table, kinds, "", numeric, cat_cols)
        if rc:
            cols = [c for c in numeric if c != rc]
            return build_heatmap_matrix_panel(table, kinds, rc, cols, opts,
                                              "Heatmap across %d conditions" % len(cols))
    return None


def _panel_family(table, kinds, opts, x, y_cols, group, warnings):
    header = table["header"]
    cat_cols = [h for h in header if kinds.get(h) == "categorical"]
    date_cols = [h for h in header if kinds.get(h) == "date"]
    numeric = [h for h in header if kinds.get(h) == "numeric"]
    metrics = [c for c in y_cols if c in numeric]
    if group and len(metrics) > 1:
        metrics = metrics[:1]
    if len(metrics) > 4:
        warnings.append("%d numeric metrics found; the first 4 are shown as panels" % len(metrics))
        metrics = metrics[:4]
    panels = []
    if not metrics:
        return panels
    if not cat_cols and not date_cols and len(metrics) >= 2:
        # no grouping factor: first panel is a scatter, the rest are distributions
        p = build_scatter_panel(table, kinds, metrics[0], metrics[1], opts,
                                "%s vs %s" % (_display(metrics[1]), _display(metrics[0])),
                                group)
        if p:
            panels.append(p)
        for m in metrics[2:]:
            q = build_hist_panel(table, kinds, m, opts, "Distribution of %s" % _display(m))
            if q:
                panels.append(q)
        return panels
    for m in metrics:
        if group:
            p = build_bar_panel(table, kinds, x or (cat_cols or [""])[0], m, opts,
                                "%s by %s" % (_display(m), _display(x)), group)
        elif date_cols:
            p = build_line_panel(table, kinds, date_cols[0], m, opts,
                                 "%s over %s" % (_display(m), _display(date_cols[0])), "")
        elif cat_cols:
            p = build_bar_panel(table, kinds, x or cat_cols[0], m, opts,
                                "%s by %s" % (_display(m), _display(x or cat_cols[0])), "")
        else:
            p = build_hist_panel(table, kinds, m, opts, "Distribution of %s" % _display(m))
        if p is not None:
            panels.append(p)
    return panels


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", required=True)
    ap.add_argument("--out", default="work")
    ap.add_argument("--x", default="")
    ap.add_argument("--y", default="")
    ap.add_argument("--group", default="")
    ap.add_argument("--intent", default="auto", choices=("auto",) + VALID_TYPES)
    ap.add_argument("--error", default="sd", choices=("sd", "sem", "ci95", "none"))
    ap.add_argument("--hint", default="", help="task text or a path to task.md")
    ap.add_argument("--dedupe", default="none", choices=("none", "exact"))
    ap.add_argument("--name", default="chart_plan.json")
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    try:
        table = tableio.read_any(a.input)
    except Exception as exc:  # noqa: BLE001
        print("FAIL: cannot read table: %s" % exc)
        return 1
    kinds = tableio.classify_columns(table)
    opt = argparse.Namespace(**vars(a))
    opt.hint_intent = parse_hint(a.hint)

    if a.dedupe == "exact":
        dups = set(tableio.duplicate_rows(table))
        if dups:
            table["rows"] = [r for i, r in enumerate(table["rows"]) if (i + 2) not in dups]
            table["rows_total"] = len(table["rows"])
            kinds = tableio.classify_columns(table)

    chart, panels, warnings, selection = choose_plan(table, kinds, opt)
    panels = [p for p in panels if p]
    if not panels:
        print("FAIL: no usable chart shape for this table")
        return 1
    if len(panels) > 1:
        chart = "panel"

    # ---------------------------------------------------------- coverage / missing
    usable_rows = set()
    outlier_pairs = []
    for p in panels:
        used = set()
        if p["chart_type"] in ("bar", "grouped_bar"):
            for s in p["series"]:
                for v in s["values"]:
                    rows = v.get("source_rows", [])
                    used |= set(rows)
                    if v.get("value") is not None:
                        outlier_pairs.append((rows[0] if rows else None, v["value"]))
        elif p["chart_type"] == "line":
            for pt in p["points"]:
                used |= set(pt.get("source_rows", []))
                outlier_pairs.append((pt["row"], pt["y"]))
        elif p["chart_type"] == "scatter":
            for pt in p["points"]:
                used.add(pt["row"])
                outlier_pairs.append((pt["row"], pt["y"]))
        elif p["chart_type"] == "hist":
            for b in p["bins"]:
                used |= set(b["rows"])
        elif p["chart_type"] == "box":
            for b in p["boxes"]:
                used |= set(b["source_rows"])
                outlier_pairs.append((b["source_rows"][0] if b["source_rows"] else None,
                                      b["median"]))
                for o in b["outliers"]:
                    outlier_pairs.append((o.get("row"), o["value"]))
        elif p["chart_type"] == "heatmap":
            for c in p["cells"]:
                used |= set(c.get("source_rows", []))
                outlier_pairs.append((c["source_rows"][0] if c["source_rows"] else None,
                                      c["value"]))
        p["covered_rows"] = sorted(used)
        usable_rows |= used
        p["missing"] = {"count": table["rows_total"] - len(used),
                        "rows": [r for r in range(2, table["rows_total"] + 2)
                                 if r not in used],
                        "policy": "drop_row_no_imputation", "declared": True}
    all_rows = list(range(2, table["rows_total"] + 2))
    missing_rows = [r for r in all_rows if r not in usable_rows]

    # IQR outliers on the plotted numeric values (retained, only flagged)
    outlier_rows = set()
    vals = [v for _, v in outlier_pairs if v is not None]
    if len(vals) >= 4:
        s = sorted(vals)
        q1, q3 = quantile(s, 0.25), quantile(s, 0.75)
        lo, hi = q1 - 1.5 * (q3 - q1), q3 + 1.5 * (q3 - q1)
        for row, v in outlier_pairs:
            if v is None or row is None:
                continue
            if v < lo or v > hi:
                outlier_rows.add(row)
    dup = tableio.duplicate_rows(table)
    sig = add_significance(table, kinds, panels)

    plan = {
        "input": table["name"],
        "source": {"file": table["name"], "sha256": table["sha256"],
                   "bytes": table["bytes"], "rows": table["rows_total"],
                   "header_row": 1, "sheet": table.get("sheet", ""),
                   "encoding": table["encoding"], "delimiter": table["delimiter"]},
        "rows_total": table["rows_total"],
        "chart_type": chart,
        "columns": [{"raw": raw, "name": tableio.parse_header(raw)["name"],
                     "unit": tableio.parse_header(raw)["unit"], "kind": kinds[raw],
                     "column": j} for j, raw in enumerate(table["header"])],
        "selection": selection,
        "error": a.error,
        "error_semantics": {
            "sd": "SD = sample standard deviation (n-1)",
            "sem": "SEM = SD / sqrt(n)",
            "ci95": "95% CI = mean \u00b1 1.96 * SEM",
            "none": "no error bars",
        }[a.error],
        "panels": panels,
        "missing": {"count": len(missing_rows), "rows": missing_rows,
                    "policy": "drop_row_no_imputation", "declared": True},
        "duplicates": {"count": len(dup), "rows": dup, "policy": "retained_and_declared"},
        "outliers": {"method": "IQR_1.5", "count": len(outlier_rows),
                     "rows": sorted(outlier_rows), "policy": "retained_and_flagged"},
        "significance": sig,
        "warnings": warnings,
        "hint_intent": opt.hint_intent,
    }
    path = os.path.join(a.out, a.name)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(plan, fh, ensure_ascii=False, indent=1)
    print("chart=%s panels=%d types=%s missing=%d duplicates=%d outliers=%d warnings=%d"
          % (chart, len(panels), [p["chart_type"] for p in panels], len(missing_rows),
             len(dup), len(outlier_rows), len(warnings)))
    for w in warnings[:10]:
        print("  ~", w)
    return 0


if __name__ == "__main__":
    sys.exit(main())
