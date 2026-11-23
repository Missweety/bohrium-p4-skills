#!/usr/bin/env python3
"""route_spec.py - 装置图/技术路线图规格校验、几何自检与重建（仅标准库）。

  build --spec work/spec.json --out work --name route [--strict]
  edit  --spec work/spec.json --patch work/patch.json --out work --name route

错误码见 references/apparatus-spec-schema.md；--strict 有 error 时退出码 1。
"""
import argparse
import json
import sys

import routelib as r
import route_svg
from routelib import KINDS, TYPES, bx, inside, ix, legend_box, legend_items, tw, wrap

MIN_PT = 7.0


def lint(spec):
    fig = spec.get("figure") or {}
    W, H = float(fig.get("width_px", 0)), float(fig.get("height_px", 0))
    parts = {p.get("id"): p for p in spec.get("parts", [])}
    stages = {s.get("id"): s for s in spec.get("stages", [])}
    errs, warns = [], []

    def add(level, code, el, msg):
        (errs if level == "error" else warns).append(
            {"level": level, "code": code, "element": el, "detail": msg})

    if not W or not H:
        add("error", "bad_canvas", "figure", "width_px/height_px 必须为正数")
        return errs, warns
    if not fig.get("title"):
        add("error", "missing_title", "figure", "缺少标题；标题是机检必填项")
    if not parts:
        add("error", "missing_parts", "figure", "没有部件；装置图至少需要一个部件")

    ids = [p.get("id") for p in spec.get("parts", [])] + \
          [c.get("id") for c in spec.get("connections", [])] + list(stages)
    for d in sorted({i for i in ids if ids.count(i) > 1}):
        add("error", "duplicate_id", d, "id 重复")

    app = fig.get("apparatus_bbox") or {"x": 32, "y": 80, "w": W - 64, "h": 600}
    for p in parts.values():
        pid = p.get("id")
        x, y, w, h = bx(p)
        if w <= 0 or h <= 0:
            add("error", "bad_bbox", pid, "宽高必须为正")
        if not inside({"x": 0, "y": 0, "w": W, "h": H}, p, 0):
            add("error", "out_of_canvas", pid, "部件超出画布")
        if not inside(app, p, 2):
            add("error", "part_outside_apparatus", pid, "部件越出装置区")
        if p.get("type") not in TYPES:
            add("error", "bad_part_type", pid, "type 不在 %s 中" % sorted(TYPES))
        shape = p.get("shape") or r.TYPES.get(p.get("type"), ("", "rounded"))[1]
        if shape not in ("rounded", "rect", "circle", "ellipse", "diamond", "triangle", "column", "instrument", "waste"):
            add("error", "bad_shape", pid, "shape 不受支持：%s" % shape)
        pt = float(p.get("font_pt", 9))
        if pt < MIN_PT:
            add("error", "font_too_small", pid, "%.1fpt 小于 %.1fpt" % (pt, MIN_PT))
        ept, lines, sub = r.part_layout(p, float(fig.get("dpi", 300)))
        px = ept * float(fig.get("dpi", 300)) / 72.0
        need = len(lines) * px * 1.22 + 10 + len(sub) * px * 0.72 * 1.35
        if need > h:
            add("error", "text_overflow", pid, "文本需 %.0fpx，部件高 %.0fpx" % (need, h))
        if not r.text_fits(p, float(fig.get("dpi", 300))):
            add("error", "text_outside_shape", pid, "标签宽于形状在文字高度处的内宽")
        if p.get("status", "stated") == "stated" and not p.get("evidence"):
            add("error", "missing_evidence", pid, "stated 部件缺少材料定位")
        if not str(p.get("label", "")).strip():
            add("error", "missing_label", pid, "部件标签为空")

    vals = list(parts.values())
    for i, a in enumerate(vals):
        for b in vals[i + 1:]:
            if ix(a, b) > 8 and not (inside(a, b) or inside(b, a)):
                add("error", "part_overlap", "%s/%s" % (a.get("id"), b.get("id")), "部件重叠")

    linked = set()
    pair_seen = set()
    for c in spec.get("connections", []):
        cid = c.get("id")
        a, b = c.get("from"), c.get("to")
        linked |= {a, b}
        if a not in parts or b not in parts:
            add("error", "bad_connection_ref", cid, "连线引用了不存在的部件")
            continue
        if c.get("kind") not in KINDS:
            add("error", "bad_kind", cid, "kind 不在 %s 中" % sorted(KINDS))
        if not a or not b:
            add("error", "connection_without_direction", cid, "缺少 from/to，无法判断流向")
        if a == b:
            add("warn", "self_loop", cid, "自环需在 notes 说明循环回路")
        if c.get("status", "stated") == "stated" and not c.get("evidence"):
            add("error", "missing_evidence", cid, "stated 连线缺少材料定位")
        if c.get("direction", "forward") not in ("forward", "bidirectional"):
            add("error", "bad_direction", cid, "direction 只能是 forward/bidirectional")
        key = (a, b, c.get("kind"))
        if key in pair_seen:
            add("warn", "duplicate_connection", cid, "重复连线（同 from/to/kind）")
        pair_seen.add(key)
        label = c.get("label") or ""
        if label and tw(label, 7.5 * float(fig.get("dpi", 300)) / 72.0) > 300:
            add("warn", "connection_label_long", cid, "连线标签过长，可能压住部件")

    for p in vals:
        if p.get("id") not in linked and p.get("type") not in ("support", "tubing"):
            add("warn", "isolated_part", p.get("id"), "部件没有连线，检查是否漏画接口")

    if len(spec.get("stages", [])) < 2:
        # 材料本身只给得出 1 个阶段时，宁可输出带告警的单阶段降级图，也不要整包搬空
        add("warn", "too_few_stages", "stages",
            "技术路线只有 %d 个阶段（建议 >=2）；已在 result.limits 说明降级" % len(spec.get("stages", [])))
    orders = sorted(int(s.get("order", 0)) for s in spec.get("stages", []))
    if orders != list(range(1, len(orders) + 1)):
        add("error", "bad_stage_order", "stages", "order 必须从 1 连续编号，当前 %s" % orders)
    panel = fig.get("stage_bbox") or {"x": 32, "y": 760, "w": W - 64, "h": 220}
    milestones = 0
    for s in spec.get("stages", []):
        sid = s.get("id")
        if not s.get("objective"):
            add("error", "missing_objective", sid, "阶段缺少 objective")
        if not s.get("outputs"):
            add("warn", "missing_outputs", sid, "阶段未列 outputs，交付链不完整")
        if s.get("milestone"):
            milestones += 1
        for d in s.get("depends_on") or []:
            if int(d) >= int(s.get("order", 0)):
                add("error", "bad_dependency", sid, "依赖的阶段必须早于当前阶段")
            if not any(int(t.get("order", 0)) == int(d) for t in spec.get("stages", [])):
                add("error", "unknown_dependency", sid, "依赖的阶段序号 %s 不存在" % d)
        if not inside({"x": 0, "y": 0, "w": W, "h": H}, s, 0):
            add("error", "stage_out_of_canvas", sid, "阶段框超出画布")
        if not inside(panel, s, 2):
            add("error", "stage_outside_panel", sid, "阶段框越出时间轴区")
        need = r.stage_layout(s, float(fig.get("dpi", 300)))["need"]
        if need > s.get("h", 100):
            add("error", "stage_text_overflow", sid, "阶段文本需 %.0fpx，框高 %.0fpx" % (need, s.get("h")))
    sval = list(stages.values())
    for i, a in enumerate(sval):
        for b in sval[i + 1:]:
            if ix(a, b) > 4:
                add("error", "stage_overlap", "%s/%s" % (a.get("id"), b.get("id")), "阶段框重叠")
    if milestones == 0:
        # 材料未声明里程碑只告警，不阻断；不得虚构里程碑
        add("warn", "missing_milestone", "stages", "材料未显式声明 milestone（里程碑）")

    items = legend_items(spec)
    lx, ly, lw, lh = legend_box(spec, items, W, H)
    if lx + lw > W or ly + lh > H:
        add("error", "legend_out_of_canvas", "legend", "图例框超出画布")
    if (ly < panel["y"] + panel["h"] and ly + lh > panel["y"]
            and lx < panel["x"] + panel["w"] and lx + lw > panel["x"]):
        add("warn", "legend_overlaps_stage_panel", "legend", "图例与阶段区重叠，调整 figure.legend_at")
    if spec.get("legend"):
        used = {c.get("kind", "flow") for c in spec.get("connections", [])}
        given = {i.get("kind") for i in spec["legend"]}
        for k in sorted(used - given):
            add("warn", "legend_missing_kind", "legend", "缺少 %s 图例" % k)
        for k in sorted(given - used):
            add("warn", "legend_extra_kind", "legend", "%s 图例未被使用" % k)
    if len(items) > 6:
        add("warn", "legend_too_long", "legend", "超过 6 种连线，底部图例区将溢出")

    units = spec.get("units")
    if not isinstance(units, dict) or not units:
        add("warn", "missing_units", "figure", "未提供单位；渲染会写“定性”，需在 uncertainty 说明")
    sb = spec.get("scale_bar") or {}
    label = str(sb.get("label", "")).strip()
    try:
        length = float(sb.get("length_px", 0) or 0)
    except (TypeError, ValueError):
        length = 0
    if not label:
        add("error", "missing_scale_bar", "figure", "缺少比例尺标签（非等比也需显式写 not to scale）")
    if length and not (30 <= length <= 420):
        add("error", "bad_scale_length", "figure", "比例尺长度应在 30–420 px")
    if not length and not any(k in label.lower() for k in ("not to scale", "非等比", "示意")):
        add("error", "missing_scale_length", "figure", "比例尺缺少数值长度，或标签需明确 not to scale")
    return errs, warns


def merge(dst, src):
    for k, v in src.items():
        if isinstance(v, dict) and isinstance(dst.get(k), dict):
            merge(dst[k], v)
        elif isinstance(v, list) and isinstance(dst.get(k), list):
            idx = {x.get("id"): x for x in dst[k] if isinstance(x, dict)}
            for it in v:
                if isinstance(it, dict) and it.get("id") in idx:
                    merge(idx[it["id"]], it)
                else:
                    dst[k].append(it)
        else:
            dst[k] = v


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    for cmd in ("build", "edit"):
        p = sub.add_parser(cmd)
        p.add_argument("--spec", required=True)
        p.add_argument("--out", required=True)
        p.add_argument("--name", default="route")
        p.add_argument("--strict", action="store_true")
        p.add_argument("--patch")
    a = ap.parse_args()
    spec = json.load(open(a.spec, encoding="utf-8"))
    if a.cmd == "edit":
        merge(spec, json.load(open(a.patch, encoding="utf-8")))
        with open(a.spec, "w", encoding="utf-8") as fh:
            json.dump(spec, fh, ensure_ascii=False, indent=1)
        print("patched:", a.spec)
    errs, warns = lint(spec)
    for x in errs + warns:
        print(" %s %-28s %-16s %s" % (x["level"], x["code"], x["element"], x["detail"]))
    route_svg.render(spec, a.out, a.name, {"errors": errs, "warnings": warns})
    return 1 if (a.strict and errs) else 0


if __name__ == "__main__":
    sys.exit(main())
