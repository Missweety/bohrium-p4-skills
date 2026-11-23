#!/usr/bin/env python3
"""build_spec.py - turn chart_plan.json into chart_spec.json (the only render input).

The spec fixes chart type, per-panel data, axis labels/units, axis bounds and ticks,
legend items, annotations, highlighting and style. Rendering reads nothing else, so
the same spec always yields the same figure and every edit is auditable.

Usage: python3 scripts/build_spec.py --plan work/chart_plan.json --out work \
           [--title "..."] [--source-path /input/data.csv] [--normalized work/normalized_source.csv]
Writes: chart_spec.json
"""
import argparse
import hashlib
import json
import math
import os
import re

import tableio
from labels import OKABE, VIRIDIS, fmt_num, has_cjk, nice_ticks

ERR_TEXT = {"sd": "SD（样本标准差，n-1）", "sem": "SEM（SD/\u221an）",
            "ci95": "95% CI（mean \u00b1 1.96\u00d7SEM）", "none": "无误差线"}


def _r(v):
    return None if v is None else round(float(v), 6)


def display_field(field):
    name, unit = field.get("name", ""), field.get("unit", "")
    if unit and not re.search(r"[\(\[]\s*%s\s*[\)\]]" % re.escape(unit), name):
        return "%s (%s)" % (name, unit)
    return name


def _label_len(labels):
    return max([len(str(x)) for x in labels] or [0])


def build_axis_for_panel(p, error_code):
    ct = p["chart_type"]
    y_field = p.get("fields", {}).get("y", {})
    x_field = p.get("fields", {}).get("x", {})
    y_label = display_field(y_field) if ct != "hist" else "Count"
    if ct == "hist":
        x_field = {"name": display_field(y_field), "unit": y_field.get("unit", ""),
                   "kind": "numeric"}
        y_label = "Count"
    x_label = display_field(x_field) if ct != "hist" else display_field(y_field)
    axis = {"x": {"label": x_label, "unit": x_field.get("unit", ""), "kind": "category"},
            "y": {"label": y_label, "unit": y_field.get("unit", "") if ct != "hist" else "",
                  "kind": "numeric"}}
    if ct in ("bar", "grouped_bar"):
        vals = [v for s in p["series"] for v in s["values"] if v.get("value") is not None]
        tops = [v["value"] + (v.get("error") or 0) for v in vals]
        bottoms = [v["value"] - (v.get("error") or 0) for v in vals]
        hi = max(tops or [1])
        lo = min(bottoms or [0])
        axis["y"].update(nice_ticks(min(lo, 0.0), max(hi, 0.0), zero=(lo >= 0)))
    elif ct == "hist":
        hi = max([b["count"] for b in p["bins"]] or [1])
        axis["y"].update(nice_ticks(0, hi, zero=True))
        lo = p["bins"][0]["lo"] if p["bins"] else 0
        up = p["bins"][-1]["hi"] if p["bins"] else 1
        axis["x"] = {"label": display_field(y_field), "unit": y_field.get("unit", ""),
                     "kind": "numeric"}
        axis["x"].update(nice_ticks(lo, up, zero=False))
    elif ct == "line":
        ys = [pt["y"] + (pt.get("error") or 0) for pt in p["points"]]
        lo = min([pt["y"] - (pt.get("error") or 0) for pt in p["points"]] or [0])
        hi = max(ys or [1])
        pad = (hi - lo) * 0.08 or 1.0
        axis["y"].update(nice_ticks(lo - pad, hi + pad, zero=False))
        axis["x"]["categories"] = p["categories"]
    elif ct == "scatter":
        xs = [pt["x"] for pt in p["points"]]
        ys = [pt["y"] for pt in p["points"]]
        axis["x"] = {"label": display_field(x_field), "unit": x_field.get("unit", ""),
                     "kind": "numeric"}
        pad_x = (max(xs) - min(xs)) * 0.06 or 1.0
        pad_y = (max(ys) - min(ys)) * 0.06 or 1.0
        axis["x"].update(nice_ticks(min(xs) - pad_x, max(xs) + pad_x, zero=False))
        axis["y"].update(nice_ticks(min(ys) - pad_y, max(ys) + pad_y, zero=False))
        axis["legend"] = {"show": False}
    elif ct == "box":
        lows = []
        highs = []
        for b in p["boxes"]:
            lows.append(min([b["min"]] + [o["value"] for o in b["outliers"]] or [b["min"]]))
            highs.append(max([b["max"]] + [o["value"] for o in b["outliers"]] or [b["max"]]))
        lo, hi = min(lows or [0]), max(highs or [1])
        pad = (hi - lo) * 0.08 or 1.0
        axis["y"].update(nice_ticks(lo - pad, hi + pad, zero=False))
        axis["x"]["categories"] = p["categories"]
    elif ct == "heatmap":
        axis["x"] = {"label": x_field.get("name", "condition") or "condition",
                     "unit": "", "kind": "category", "categories": p["col_labels"]}
        axis["y"] = {"label": p.get("fields", {}).get("group", {}).get("name", "row")
                     or "row", "unit": "", "kind": "category",
                     "categories": p["row_labels"]}
        cs = p["color_scale"]
        axis["color"] = {"label": cs.get("label", "value"), "unit": y_field.get("unit", ""),
                         "kind": "numeric", "min": cs.get("min"), "max": cs.get("max")}
        axis["color"].update(nice_ticks(cs.get("min", 0), cs.get("max", 1), zero=False,
                                        target=4))
        axis["color"]["label"] = cs.get("label", "value")
    return axis


def build_legend(p):
    ct = p["chart_type"]
    items = []
    show = False
    if ct in ("bar", "grouped_bar"):
        if len(p["series"]) > 1:
            show = True
            items = [{"label": s["label"], "color": s["color"], "swatch": "bar"}
                     for s in p["series"]]
    elif ct == "line":
        if len(p["series"]) > 1:
            show = True
            items = [{"label": s["label"], "color": s["color"], "swatch": "line"}
                     for s in p["series"]]
    elif ct == "scatter":
        labels = [s["label"] for s in p["series"] if s["label"]]
        if len(labels) > 1:
            show = True
            items = [{"label": s["label"], "color": s["color"], "swatch": "point"}
                     for s in p["series"] if s["label"]]
    return {"show": show, "position": "best", "items": items}


def panel_annotations(p, plan, error_code):
    ann = []
    fmt = lambda d: ",".join(str(x) for x in (d.get("rows") or [])[:12])
    if p.get("missing", {}).get("count"):
        ann.append({"id": "ann:missing", "kind": "note", "place": "figure_note",
                    "text": "%d row(s) excluded (missing or non-numeric value) rows %s"
                            % (p["missing"]["count"], fmt(p["missing"])),
                    "source": "chart_spec.panels[%s].missing" % p.get("id"),
                    "source_rows": p["missing"].get("rows", [])[:20]})
    if p.get("outliers", {}).get("count"):
        ann.append({"id": "ann:outliers", "kind": "note", "place": "figure_note",
                    "text": "%d IQR outlier(s) retained and flagged (rows %s)"
                            % (p["outliers"]["count"], ",".join(
                                str(x) for x in p["outliers"].get("rows", [])[:12])),
                    "source": "chart_spec.panels[%s].outliers" % p.get("id"),
                    "source_rows": p["outliers"].get("rows", [])[:20]})
    small = []
    for s in p.get("series", []):
        for v in s.get("values", []):
            if v.get("n") is not None and v["n"] < 3:
                small.append(v.get("label"))
    if small:
        ann.append({"id": "ann:small_n", "kind": "note", "place": "figure_note",
                    "text": "n<3 for %s: error bars omitted, values are single/low-n"
                            % ", ".join(sorted(set(str(x) for x in small))[:6]),
                    "source": "chart_spec.panels[%s].series" % p.get("id"),
                    "source_rows": []})
    if p.get("merged"):
        ann.append({"id": "ann:merged", "kind": "note", "place": "figure_note",
                    "text": "categories 12+ merged into Other (display aggregation)",
                    "source": "chart_spec.panels[%s].categories" % p.get("id"),
                    "source_rows": []})
    if p["chart_type"] == "heatmap" and p.get("missing_cells"):
        ann.append({"id": "ann:missing_cells", "kind": "note", "place": "figure_note",
                    "text": "%d empty heatmap cell(s) left blank (no imputation)"
                            % p["missing_cells"],
                    "source": "chart_spec.panels[%s].cells" % p.get("id"),
                    "source_rows": []})
    if p["chart_type"] == "heatmap" and p.get("color_scale", {}).get("units_mixed"):
        ann.append({"id": "ann:mixed_units", "kind": "note", "place": "figure_note",
                    "text": "heatmap columns carry different units: colour encodes raw "
                            "values, compare within a column only",
                    "source": "chart_spec.panels[%s].color_scale" % p.get("id"),
                    "source_rows": []})
    if p["chart_type"] == "line" and p.get("line_aggregated"):
        ann.append({"id": "ann:line_mean", "kind": "note", "place": "figure_note",
                    "text": "replicate x values are shown as the group mean with %s"
                            % ERR_TEXT.get(error_code, error_code),
                    "source": "chart_spec.panels[%s].points" % p.get("id"),
                    "source_rows": []})
    if p.get("summary_mode"):
        ann.append({"id": "ann:summary", "kind": "note", "place": "figure_note",
                    "text": "source table already contains summary statistics: mean and "
                            "error were used directly, not recomputed",
                    "source": "chart_spec.panels[%s]" % p.get("id"), "source_rows": []})
    return ann


def panel_caveats(p, error_code):
    cave = []
    if p.get("missing", {}).get("count"):
        cave.append("%s：%d 行缺失或非数值未纳入图面（行号 %s），不插值"
                    % (p.get("id", ""), p["missing"]["count"],
                       ",".join(map(str, p["missing"].get("rows", [])[:12]))))
    if p.get("outliers", {}).get("count"):
        cave.append("%s：%d 个 IQR 异常值保留并在图注标注（行号 %s）"
                    % (p.get("id", ""), p["outliers"]["count"],
                       ",".join(map(str, p["outliers"].get("rows", [])[:12]))))
    if p.get("merged"):
        cave.append("%s：类别超过 12 个，显示为前 11 类 + Other" % p.get("id", ""))
    y_field = p.get("fields", {}).get("y", {})
    if not y_field.get("unit") and p["chart_type"] not in ("heatmap", "hist"):
        cave.append("%s：字段名未含单位，轴标签只写变量名，单位待人工确认"
                    % p.get("id", ""))
    if p["chart_type"] == "heatmap" and p.get("color_scale", {}).get("units_mixed"):
        cave.append("%s：热图各列单位不一致，色阶仅表示原始数值" % p.get("id", ""))
    if p.get("summary_mode"):
        cave.append("%s：源表为汇总统计量（mean + 误差 + n），直接采用，未二次聚合"
                    % p.get("id", ""))
    return cave


def build(plan, title="", source_path="", normalized=""):
    panels = []
    style_cjk = False
    annotations_global = []
    caveats = []
    outl = plan.get("outliers", {})
    for k, p in enumerate(plan["panels"]):
        p = json.loads(json.dumps(p))
        p["id"] = p.get("id") or chr(ord("A") + k)
        p["axis"] = build_axis_for_panel(p, plan.get("error", "sd"))
        p["legend"] = build_legend(p)
        p["missing"] = p.get("missing") or {"count": 0, "rows": [],
                                            "policy": "drop_row_no_imputation",
                                            "declared": True}
        p["outliers"] = p.get("outliers") or dict(outl)
        p["highlights"] = p.get("highlights") or []
        p["caveats"] = panel_caveats(p, plan.get("error", "sd"))
        ann = panel_annotations(p, plan, plan.get("error", "sd"))
        for a in ann:
            a["id"] = "p%s:%s" % (p["id"], a["id"])
        p["annotations"] = ann
        p["sample_sizes"] = sample_sizes(p)
        style_cjk = style_cjk or has_cjk(p.get("title", "")) or any(
            has_cjk(x) for x in p.get("categories", [])) or has_cjk(
            p["axis"]["x"].get("label", "")) or has_cjk(p["axis"]["y"].get("label", ""))
        panels.append(p)
        caveats += p["caveats"]

    for sig in plan.get("significance", []):
        annotations_global.append({
            "id": "ann:sig:%s" % sig["column"], "kind": "significance",
            "place": "figure_note", "text": sig["text"],
            "source": "source_column:%s" % sig["column"],
            "source_rows": [v["row"] for v in sig["values"][:20]]})

    if plan.get("duplicates", {}).get("count"):
        caveats.append("%d 行完全重复（行号 %s）：默认保留并在图注声明，未自动去重"
                       % (plan["duplicates"]["count"],
                          ",".join(map(str, plan["duplicates"].get("rows", [])[:12]))))
    if plan.get("missing", {}).get("count"):
        caveats.append("共 %d 行无任何可用于绘图的数值（行号 %s），不插值、不补点"
                       % (plan["missing"]["count"],
                          ",".join(map(str, plan["missing"].get("rows", [])[:12]))))
    if plan.get("significant_requested_without_source"):
        caveats.append("任务提到显著性但源表无 p 值列：未做统计检验，未添加显著性标记")

    agg_rows, agg_vals = [], []
    for p in panels:
        po = p.get("outliers") or {}
        agg_rows += [r for r in po.get("rows") or [] if r not in agg_rows]
        agg_vals += [v for v in po.get("values") or [] if v not in agg_vals]
    if agg_rows and not outl.get("count"):
        outl = {"method": outl.get("method", "IQR_1.5"), "count": len(agg_rows),
                "rows": sorted(agg_rows), "values": agg_vals,
                "policy": outl.get("policy", "retained_and_flagged")}

    if not title:
        title = _default_title(plan, panels)
    width_in, height_in = _figure_size(panels)
    top_type = panels[0]["chart_type"] if len(panels) == 1 else plan["chart_type"]
    spec = {
        "spec_version": "1.1",
        "chart_id": "figure",
        "chart_type": top_type,
        "source": {
            "file": plan["source"]["file"],
            "path": source_path or plan["source"].get("path", ""),
            "sha256": plan["source"]["sha256"],
            "bytes": plan["source"].get("bytes"),
            "rows": plan["rows_total"],
            "header_row": 1,
            "sheet": plan["source"].get("sheet", ""),
            "normalized": normalized,
        },
        "title": title,
        "title_source": "default",
        "palette": {"name": "Okabe-Ito", "colors": OKABE, "viridis": VIRIDIS},
        "style": {"width_in": width_in, "height_in": height_in, "dpi": 300,
                  "font_pt": 8.5, "title_pt": 10, "line_width": 1.2,
                  "marker_size": 3.4, "bar_width_ratio": 0.68, "grid": True,
                  "cjk": style_cjk},
        "panels": panels,
        "error": plan.get("error", "sd"),
        "error_semantics": {"code": plan.get("error", "sd"),
                            "label": {"sd": "SD", "sem": "SEM", "ci95": "95% CI",
                                      "none": "none"}.get(plan.get("error", "sd")),
                            "text": ERR_TEXT.get(plan.get("error", "sd"), ""),
                            "plan_text": plan.get("error_semantics", "")},
        "missing": plan.get("missing", {}),
        "outliers": outl,
        "duplicates": plan.get("duplicates", {}),
        "significance_provided": bool(plan.get("significance")),
        "annotations": annotations_global,
        "caveats": caveats,
        "layout": {"mode": "grid" if len(panels) > 1 else "single",
                   "panel_count": len(panels),
                   "columns": 2 if len(panels) > 2 else len(panels)},
        "selection": plan.get("selection", {}),
        "warnings": plan.get("warnings", []),
    }
    return spec


def sample_sizes(p):
    ct = p["chart_type"]
    if ct in ("bar", "grouped_bar"):
        return {"series": {s["label"]: {v["label"]: v.get("n") for v in s.get("values", [])}
                           for s in p["series"]},
                "missing_by_group": p.get("missing_by_group") or {}}
    if ct == "box":
        return {b["label"]: b.get("n") for b in p["boxes"]}
    if ct == "line":
        return {pt["x"]: pt.get("n") for pt in p.get("points", [])}
    if ct == "scatter":
        return {"n": len(p.get("points", []))}
    if ct == "hist":
        return {"n": sum(b.get("count", 0) for b in p.get("bins", []))}
    if ct == "heatmap":
        return {"cells": len(p.get("cells", [])),
                "rows": len(p.get("row_labels", []))}
    return {}


def _default_title(plan, panels):
    if len(panels) == 1:
        return panels[0].get("title") or "Figure"
    names = [p.get("title", "") for p in panels]
    short = []
    for n in names:
        if " by " in n:
            short.append(n.split(" by ")[0])
        elif " over " in n:
            short.append(n.split(" over ")[0])
        elif "Distribution of " in n:
            short.append(n.replace("Distribution of ", ""))
        elif " distribution by " in n:
            short.append(n.split(" distribution by ")[0])
        else:
            short.append(n)
    return "Multi-panel: " + " | ".join(short[:4])


def _figure_size(panels):
    if len(panels) == 1:
        p = panels[0]
        ct = p["chart_type"]
        cats = p.get("categories") or p.get("row_labels") or []
        longest = _label_len(cats)
        if ct == "heatmap":
            w = max(4.8, 0.48 * len(p.get("col_labels", [])) + 2.6)
            h = max(3.4, 0.30 * len(p.get("row_labels", [])) + 1.8)
            return round(min(w, 8.2), 2), round(min(h, 8.2), 2)
        if ct == "grouped_bar":
            w = 6.4 if len(cats) > 6 else 5.4
            return round(min(w + (0.06 * max(longest - 10, 0)), 8), 2), 3.9
        if ct in ("bar", "box", "line"):
            w = 5.4 + min(max(longest - 8, 0) * 0.07, 1.4)
            h = 3.7 + (0.35 if longest > 16 else 0)
            return round(w, 2), round(h, 2)
        return 5.4, 3.6
    cols = 2 if len(panels) > 2 else len(panels)
    rows = int(math.ceil(len(panels) / cols))
    return 7.2, round(2.6 * rows + 0.7, 2)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--plan", required=True)
    ap.add_argument("--out", default="work")
    ap.add_argument("--title", default="")
    ap.add_argument("--source-path", default="")
    ap.add_argument("--normalized", default="")
    ap.add_argument("--name", default="chart_spec.json")
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    plan = json.load(open(a.plan, encoding="utf-8"))
    spec = build(plan, a.title, a.source_path, a.normalized)
    path = os.path.join(a.out, a.name)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(spec, fh, ensure_ascii=False, indent=1)
    print("spec=%s chart=%s panels=%d title=%r annotations=%d caveats=%d"
          % (path, spec["chart_type"], len(spec["panels"]), spec["title"],
             len(spec["annotations"]) + sum(len(p["annotations"]) for p in spec["panels"]),
             len(spec["caveats"])))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
