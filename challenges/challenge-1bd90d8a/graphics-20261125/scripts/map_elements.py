#!/usr/bin/env python3
"""map_elements.py - write element_map.json, figure_meta.json and caption.md.

The caption is generated from the same spec as the figure: chart type, every axis
label with unit, error-bar semantics, sample sizes, missing/outlier/duplicate policy,
significance provenance (only when the source has it), source hash and the element map.
No sentence claims a value that is not in chart_spec.json.

Usage: python3 scripts/map_elements.py --spec work/chart_spec.json --out work
"""
import argparse
import hashlib
import json
import os
import re

import elements

TYPE_CN = {"bar": "柱状图（柱高=组均值）", "grouped_bar": "分组柱状图（按第二因素分组）",
           "line": "折线图", "scatter": "散点图", "hist": "直方图（10 个等宽分箱）",
           "box": "箱线图（Tukey 1.5×IQR 须，异常值单独标出）",
           "heatmap": "热图（离散 Viridis 色阶）", "panel": "多面板组合图"}


def _fmt(v):
    if v is None:
        return "—"
    try:
        v = float(v)
    except (TypeError, ValueError):
        return str(v)
    return ("%.6g" % v)


def _with_unit(label, unit):
    """Append the unit only when the label does not already carry it."""
    if not unit:
        return label
    if re.search(r"[\(\[]\s*%s\s*[\)\]]" % re.escape(unit), label or ""):
        return label
    return "%s [%s]" % (label, unit)


def _n_range(sizes):
    vals = []

    def walk(x):
        if isinstance(x, dict):
            for v in x.values():
                walk(v)
        elif isinstance(x, (list, tuple)):
            for v in x:
                walk(v)
        elif isinstance(x, (int, float)) and not isinstance(x, bool):
            vals.append(int(x))
    walk(sizes.get("series", sizes) if isinstance(sizes, dict) else sizes)
    if not vals:
        return ""
    if min(vals) == max(vals):
        return "n=%d" % vals[0]
    return "n=%d–%d（最小 %d）" % (min(vals), max(vals), min(vals))


def _low_n(sizes):
    """Bars whose n is below the panel maximum, e.g. one group with a missing row."""
    series = sizes.get("series") if isinstance(sizes, dict) else None
    if not isinstance(series, dict) or not series:
        return []
    pairs = []
    for sname, cats in series.items():
        if not isinstance(cats, dict):
            continue
        for cname, n in cats.items():
            if isinstance(n, (int, float)) and not isinstance(n, bool):
                pairs.append((str(sname), str(cname), int(n)))
    if not pairs:
        return []
    top = max(n for _, _, n in pairs)
    low = sorted([t for t in pairs if t[2] < top], key=lambda t: t[2])
    if not low:
        return []
    out = ["%s/%s n=%d" % (s, c, n) for s, c, n in low[:6]]
    if len(low) > 6:
        out.append("等 %d 处" % (len(low) - 6))
    return out


def build_caption(spec, element_payload):
    panels = spec.get("panels", [])
    lines = [spec.get("title", "Figure")]
    if any(has_cjk(p.get("title", "")) for p in panels) or _has_cjk_any(spec):
        pass
    if spec.get("chart_type") == "panel" and len(panels) > 1:
        lines.append("图型：多面板组合图，共 %d 个面板（%s）。" % (
            len(panels), "；".join("%s %s" % (p.get("id"), TYPE_CN.get(p["chart_type"],
                                                                     p["chart_type"]))
                                  for p in panels)))
    else:
        p = panels[0] if panels else {}
        lines.append("图型：%s。" % TYPE_CN.get(p.get("chart_type"),
                                              spec.get("chart_type", "")))
    parts = []
    for p in panels:
        ax = p.get("axis", {})
        x = ax.get("x", {})
        y = ax.get("y", {})
        seg = "%s「%s」" % (p.get("id"), p.get("title", ""))
        if p.get("chart_type") == "heatmap":
            color = ax.get("color", {})
            seg += "：行=%s，列=%s，色阶=%s [%s, %s]" % (
                y.get("label", ""), x.get("label", ""), color.get("label", ""),
                _fmt(color.get("min")), _fmt(color.get("max")))
        else:
            unit_y = y.get("unit") or ""
            unit_x = x.get("unit") or ""
            seg += "：x=%s，y=%s" % (
                _with_unit(x.get("label", ""), unit_x),
                _with_unit(y.get("label", ""), unit_y))
        parts.append(seg)
    lines.append("坐标与单位：" + "；".join(parts) + "。")
    err = spec.get("error_semantics", {})
    lines.append("误差线：%s；n<3 的组不画误差线，单点/低样本量已在图注声明。"
                 % err.get("text", "无误差线"))
    for p in panels:
        sizes = p.get("sample_sizes", {})
        msg = _n_range(sizes)
        low = _low_n(sizes)
        if msg and low:
            msg += "；样本量低于面板最大值的柱：" + "，".join(low)
        if msg:
            lines.append("样本量 %s：%s。" % (p.get("id"), msg))
        else:
            lines.append("样本量 %s：源表未声明（n 未知，误差线仅按源值展示）。"
                         % p.get("id"))
    src = spec.get("source", {})
    lines.append("数据来源：`%s`（sha256 %s…，%s 行）；全部数值由脚本从源表计算，无手填、"
                 "无外部推断。" % (src.get("file", ""), (src.get("sha256") or "")[:12],
                                   src.get("rows")))
    counts = element_payload.get("counts", {})
    lines.append("图元—源行对照：`element_map.json`（%d 个图元，其中 %d 个数据图元，"
                 "每个数据图元都带 source_rows 与列名）。"
                 % (counts.get("total", 0), counts.get("data", 0)))
    if spec.get("significance_provided"):
        sig = [a for a in spec.get("annotations", []) if a.get("kind") == "significance"]
        lines.append("显著性：源表提供了显著性/p 值列，按原文转写，未做任何统计检验。"
                     if sig else "显著性：源表提供了显著性列，未显示。")
    else:
        lines.append("显著性：源表未提供 p 值或显著性标记，因此图中没有任何显著性标注，"
                     "也未进行统计检验。")
    miss = spec.get("missing", {})
    out = spec.get("outliers", {})
    dup = spec.get("duplicates", {})
    bits = []
    if miss.get("count"):
        bits.append("缺失/非数值 %d 行（行号 %s），不插值、不补点"
                    % (miss["count"], ",".join(map(str, miss.get("rows", [])[:10]))))
    else:
        bits.append("缺失/非数值 0 行（无空值或非数值单元格）")
    if out.get("count"):
        bits.append("IQR 异常值 %d 个（行号 %s），保留并标注"
                    % (out["count"], ",".join(map(str, out.get("rows", [])[:10]))))
    if dup.get("count"):
        bits.append("完全重复 %d 行（行号 %s），保留并在图注声明"
                    % (dup["count"], ",".join(map(str, dup.get("rows", [])[:10]))))
    lines.append("数据清洗：%s。" % ("；".join(bits) if bits else
                                "未发现缺失、异常值或重复行（按当前判定标准）"))
    if not out.get("count"):
        lines.append("异常值：按 IQR 1.5 规则未检出，未剔除或改写任何数据点。")
    if spec.get("caveats"):
        lines.append("限制与说明：" + "；".join(spec["caveats"][:8]) + "。")
    return "\n".join(lines) + "\n"


def _has_cjk_any(obj):
    import re
    text = json.dumps(obj, ensure_ascii=False)
    return bool(re.search(r"[\u4e00-\u9fff]", text))


def has_cjk(s):
    import re
    return bool(re.search(r"[\u4e00-\u9fff]", str(s)))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--spec", required=True)
    ap.add_argument("--out", default="work")
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    spec = json.load(open(a.spec, encoding="utf-8"))
    payload = elements.write_map(spec, a.out)
    caption = build_caption(spec, payload)
    with open(os.path.join(a.out, "caption.md"), "w", encoding="utf-8") as fh:
        fh.write(caption)
    meta = {
        "chart_type": spec.get("chart_type"),
        "panel_count": len(spec.get("panels", [])),
        "title": spec.get("title"),
        "source": spec.get("source"),
        "error_semantics": spec.get("error_semantics"),
        "sample_sizes": {p.get("id"): p.get("sample_sizes") for p in spec.get("panels", [])},
        "element_count": payload["counts"]["total"],
        "data_element_count": payload["counts"]["data"],
        "missing": spec.get("missing"),
        "outliers": spec.get("outliers"),
        "duplicates": spec.get("duplicates"),
        "caveats": spec.get("caveats", []),
        "caption_sha256": hashlib.sha256(caption.encode("utf-8")).hexdigest(),
    }
    with open(os.path.join(a.out, "figure_meta.json"), "w", encoding="utf-8") as fh:
        json.dump(meta, fh, ensure_ascii=False, indent=1)
    print("elements=%d data=%d caption_chars=%d"
          % (payload["counts"]["total"], payload["counts"]["data"], len(caption)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
