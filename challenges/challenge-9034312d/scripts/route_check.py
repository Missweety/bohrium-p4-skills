#!/usr/bin/env python3
"""route_check.py - 装置图/技术路线图产物机检：图层、标题、图例、单位、比例尺、部件/连线/阶段、证据链。

  python scripts/route_check.py --out work --name route [--json]

检查对象：<name>.svg + <name>_graph.json + element_map.json + geometry.json。
退出码 0=PASS，1=FAIL；报告写入 <out>/selfcheck.json。
"""
import argparse
import json
import os
import re
import sys
import xml.etree.ElementTree as ET

import routelib as r

HEX = re.compile(r"#[0-9A-Fa-f]{6}")
UNIT_TOKENS = ("µm", "μm", "nm", "mm", "cm", "m", "min", "h", "s", "nM", "µM", "μM", "mM", "M",
               "ng", "µg", "μg", "mg", "kg", "mL", "µL", "μL", "L", "Pa", "kPa", "MPa",
               "°C", "K", "rpm", "r/min", "V", "A", "W", "kW", "Hz", "%", "fold", "倍")


def local(tag):
    return tag.rsplit("}", 1)[-1]


def find_id(root, gid):
    for el in root.iter():
        if el.get("id") == gid:
            return el
    return None


def all_text(root):
    return ["".join(el.itertext()) for el in root.iter() if local(el.tag) in ("text", "title", "desc")]


def check(out, name, require_preview=False):
    errors, warnings, checks = [], [], []

    def ok(code, msg, detail=""):
        checks.append({"code": code, "ok": True, "detail": detail or msg})

    def bad(code, msg, detail=""):
        errors.append({"code": code, "detail": detail or msg})
        checks.append({"code": code, "ok": False, "detail": detail or msg})

    svg_path = os.path.join(out, name + ".svg")
    graph_path = os.path.join(out, name + "_graph.json")
    if not os.path.exists(svg_path):
        bad("missing_svg", "缺少 %s" % svg_path)
        return finish(out, checks, errors, warnings, {})
    if not os.path.exists(graph_path):
        bad("missing_graph", "缺少 %s（parts/connections/stages JSON）" % graph_path)
        return finish(out, checks, errors, warnings, {})
    if require_preview:
        png = os.path.join(out, name + ".png")
        if not os.path.exists(png) or os.path.getsize(png) == 0:
            bad("missing_preview", "缺少可检视的 PNG 预览：%s" % png)
        else:
            ok("preview", "PNG 预览存在", "%d bytes" % os.path.getsize(png))

    graph = json.load(open(graph_path, encoding="utf-8"))
    try:
        root = ET.parse(svg_path).getroot()
    except Exception as exc:  # noqa: BLE001
        bad("svg_parse", "SVG 无法解析：%s" % exc)
        return finish(out, checks, errors, warnings, {})
    if local(root.tag) != "svg":
        bad("svg_root", "根元素不是 svg")
    else:
        ok("svg_parse", "SVG XML 解析通过")

    text_all = "\n".join(all_text(root))
    ids = {el.get("id") for el in root.iter() if el.get("id")}
    required = ["layer_background", "layer_apparatus_panel", "layer_connectors", "layer_parts",
                "layer_stage_panel", "layer_stages", "layer_legend", "layer_units",
                "layer_scale", "layer_notes", "layer_title"]
    miss = [x for x in required if x not in ids]
    if miss:
        bad("missing_layers", "缺少图层：%s" % miss)
    else:
        ok("layers", "11 个必需图层齐全")

    title = str(graph.get("title", "")).strip()
    t_el = find_id(root, "fig_title")
    t_text = (t_el.text or "").strip() if t_el is not None else ""
    if not title:
        bad("missing_title", "graph.title 为空")
    elif not t_text or title not in text_all:
        bad("title_not_rendered", "标题未出现在 SVG 的 <title>/<text> 中", title)
    else:
        ok("title", "标题存在于 <title> 与图面", title)

    parts = graph.get("parts", [])
    conns = graph.get("connections", [])
    stages = graph.get("stages", [])
    pids, cids, sids = [p.get("id") for p in parts], [c.get("id") for c in conns], [s.get("id") for s in stages]
    for d in sorted({i for i in pids + cids + sids if (pids + cids + sids).count(i) > 1}):
        bad("duplicate_id", "id 重复：%s" % d)
    ok("structured_json", "parts/connections/stages JSON 可读",
       "parts=%d connections=%d stages=%d" % (len(parts), len(conns), len(stages)))
    if not parts or not stages:
        bad("empty_structure", "部件/阶段不能为空")
    if not conns:
        # 硬门禁：没有连线就不是“装置连接图”，必须 FAIL，状态由 run_case 置为 blocked
        bad("no_connections", "没有任何连线/箭头：图退化为部件陈列")
    if stages and any(not str(s.get("objective", "")).strip() for s in stages):
        bad("stage_without_step", "存在没有任何步骤/目标的空阶段")

    # 单位/参数被误当成部件（结构化字段 units/scale 与 parts 混淆时的典型失败）
    unit_like = [p.get("label") for p in parts
                 if str(p.get("label", "")).strip() in UNIT_TOKENS
                 or str(p.get("label", "")).strip() in ("温度", "压力", "流量", "单位", "参数")]
    if unit_like:
        bad("unit_as_part", "这些“部件”实际是单位/参数：%s" % unit_like)
    if len(parts) < 3 or len(conns) < 2:
        warnings.append({"code": "thin_structure",
                         "detail": "仅 %d 个部件 / %d 条连线，图面信息量不足；核对输入是否被正确解析"
                                   % (len(parts), len(conns))})
    untyped = [p.get("id") for p in parts if p.get("type") == "other"]
    if parts and len(untyped) > len(parts) / 2:
        warnings.append({"code": "weak_typing",
                         "detail": "%d/%d 个部件类型仍为 other，图元语义弱，建议补 type"
                                   % (len(untyped), len(parts))})

    labels = [str(p.get("label", "")).strip() for p in parts]
    dup_labels = sorted({x for x in labels if x and labels.count(x) > 1})
    if dup_labels:
        bad("duplicate_part_label", "部件标签重复（同一实体被画成多个节点）：%s" % dup_labels)
    MERGED = re.compile(r"(连接到|连接至|连接|接入|再进入|进入|流入|送入|下端接|上端接|"
                        r"顶部连接|出口接|入口接|经)")
    merged = [x for x in labels if MERGED.search(x)]
    if merged:
        bad("merged_part_label", "部件标签含连接关系（两个实体被并成一个节点）：%s" % merged)

    for p in parts:
        if p.get("type") not in r.TYPES:
            bad("bad_part_type", "部件 %s 类型无效：%s" % (p.get("id"), p.get("type")))
    for c in conns:
        if c.get("from") not in pids or c.get("to") not in pids:
            bad("bad_connection_ref", "连线 %s 端点不存在" % c.get("id"))
        if c.get("kind") not in r.KINDS:
            bad("bad_kind", "连线 %s 类型无效：%s" % (c.get("id"), c.get("kind")))
        if not c.get("from") or not c.get("to"):
            bad("connection_without_direction", "连线 %s 缺少 from/to" % c.get("id"))
        if c.get("direction", "forward") not in ("forward", "bidirectional"):
            bad("bad_direction", "连线 %s direction 无效" % c.get("id"))

    # 抽取到的有向连线清单：无论 PASS/FAIL 都打印，便于逐条核对方向
    label_of = {p.get("id"): str(p.get("label", "")).strip() for p in parts}
    actual_edges = [(label_of.get(c.get("from"), str(c.get("from"))),
                     label_of.get(c.get("to"), str(c.get("to")))) for c in conns]
    edge_list = ["%s→%s" % (a, b) for a, b in actual_edges]
    ok("edge_list", "抽取到 %d 条有向连线" % len(edge_list), ", ".join(edge_list))

    # 期望图门禁：部件集合、连线方向/完整性、阶段数（材料给了期望才启用）
    expected = graph.get("expected") or {}
    exp_parts = [str(x).strip() for x in (expected.get("parts") or []) if str(x).strip()]
    exp_edges = []
    for e in expected.get("edges") or []:
        if isinstance(e, (list, tuple)) and len(e) == 2:
            exp_edges.append((str(e[0]).strip(), str(e[1]).strip()))
        elif isinstance(e, dict) and e.get("from") and e.get("to"):
            exp_edges.append((str(e["from"]).strip(), str(e["to"]).strip()))
        else:
            bits = re.split(r"\s*(?:→|->|—>|⇒|=>)\s*", str(e))
            if len(bits) == 2 and all(bits):
                exp_edges.append((bits[0].strip(), bits[1].strip()))
    actual_parts = [label_of.get(pid, "") for pid in pids]
    if exp_parts:
        missing = [x for x in exp_parts if x not in actual_parts]
        extra = [x for x in actual_parts if x not in exp_parts]
        if missing:
            bad("missing_node", "缺少材料要求的部件：%s" % missing)
        if extra:
            bad("extra_node", "出现材料未支持的部件：%s" % extra)
        if not missing and not extra:
            ok("expected_parts", "部件集合与期望一致", "%d 个" % len(exp_parts))
    if exp_edges:
        pool = set(actual_edges)
        exp_set = set(exp_edges)
        reversed_edges = [e for e in exp_edges if e not in pool and (e[1], e[0]) in pool]
        missing = [e for e in exp_edges if e not in pool and e not in reversed_edges]
        extra = [e for e in actual_edges if e not in exp_set]
        if reversed_edges:
            bad("wrong_edge_direction", "供料/流向与材料相反：%s"
                % ["%s→%s" % e for e in reversed_edges])
        if missing:
            bad("missing_edge", "缺少期望的有向连线：%s" % ["%s→%s" % e for e in missing])
        if extra:
            bad("extra_edge", "出现材料未支持的有向连线：%s" % ["%s→%s" % e for e in extra])
        if not (reversed_edges or missing or extra):
            ok("expected_edges", "有向连线与期望完全一致", "%d 条" % len(exp_edges))
    min_conn = int(expected.get("min_connections") or len(exp_edges) or 0)
    if min_conn and len(conns) < min_conn:
        bad("too_few_connections", "仅有 %d 条连线，少于要求的 %d 条" % (len(conns), min_conn))
    exp_stages = int(expected.get("stages") or 0)
    if exp_stages and len(stages) != exp_stages:
        bad("wrong_stage_count", "阶段数为 %d，期望 %d" % (len(stages), exp_stages))

    orders = sorted(int(s.get("order", 0)) for s in stages)
    if orders != list(range(1, len(orders) + 1)):
        bad("bad_stage_order", "阶段 order 不是 1..n：%s" % orders)
    else:
        ok("stage_order", "阶段按 1..n 连续编号", str(orders))
    if not any(s.get("milestone") for s in stages):
        # 材料没声明里程碑不是硬错误：发警告，由 uncertainty 说明，不单独 FAIL
        warnings.append({"code": "missing_milestone",
                         "detail": "材料未显式声明里程碑；图中不虚构里程碑"})
    else:
        ok("milestones", "至少一个阶段含里程碑",
           ", ".join(str(s.get("milestone")) for s in stages if s.get("milestone")))
    for s in stages:
        if not str(s.get("objective", "")).strip():
            bad("missing_objective", "阶段 %s 缺少 objective" % s.get("id"))
        for d in s.get("depends_on") or []:
            if int(d) >= int(s.get("order", 0)):
                bad("bad_dependency", "阶段 %s 依赖了不早于自身的阶段 %s" % (s.get("id"), d))

    # rendered groups
    pmap = {p.get("id"): p for p in parts}
    for p in parts:
        el = find_id(root, p.get("id"))
        if el is None:
            bad("part_not_rendered", "部件 %s 未渲染" % p.get("id"))
            continue
        t = el.find("{*}title")
        d = el.find("{*}desc")
        dtxt = (d.text or "").strip() if d is not None else ""
        if not (t is not None and (t.text or "").strip()):
            bad("part_without_title", "部件 %s 缺少 <title>" % p.get("id"))
        if "source:" not in dtxt or (p.get("status") == "stated" and "MISSING" in dtxt):
            bad("part_without_source", "部件 %s 缺少有效来源" % p.get("id"), dtxt)
    for c in conns:
        el = find_id(root, c.get("id"))
        if el is None:
            bad("connection_not_rendered", "连线 %s 未渲染" % c.get("id"))
            continue
        d = el.find("{*}desc")
        dtxt = (d.text or "").strip() if d is not None else ""
        if "source:" not in dtxt or (c.get("status") == "stated" and "MISSING" in dtxt):
            bad("connection_without_source", "连线 %s 缺少有效来源" % c.get("id"), dtxt)
    for s in stages:
        el = find_id(root, s.get("id"))
        if el is None:
            bad("stage_not_rendered", "阶段 %s 未渲染" % s.get("id"))
            continue
        d = el.find("{*}desc")
        dtxt = (d.text or "").strip() if d is not None else ""
        if "source:" not in dtxt:
            bad("stage_without_source", "阶段 %s 缺少来源" % s.get("id"), dtxt)

    lp = find_id(root, "layer_parts")
    lc = find_id(root, "layer_connectors")
    ls = find_id(root, "layer_stages")
    cp = len([x for x in lp.iter() if local(x.tag) == "g" and x.get("id") and x is not lp]) if lp is not None else 0
    cc = len([x for x in lc.iter() if local(x.tag) == "g" and x.get("id") and x is not lc]) if lc is not None else 0
    cs = len([x for x in ls.iter() if local(x.tag) == "g" and x.get("data-order")]) if ls is not None else 0
    if cp != len(parts):
        bad("part_count_mismatch", "layer_parts 中 %d 个部件，JSON 有 %d 个" % (cp, len(parts)))
    else:
        ok("part_count", "部件数与 JSON 一致", str(cp))
    if cc != len(conns):
        bad("connection_count_mismatch", "layer_connectors 中 %d 条连线，JSON 有 %d 条" % (cc, len(conns)))
    else:
        ok("connection_count", "连线数与 JSON 一致", str(cc))
    rendered_edges = {x.get("id") for x in lc.iter()
                      if local(x.tag) == "g" and x.get("id") and x is not lc} if lc is not None else set()
    extra_edges = sorted(rendered_edges - set(cids))
    if extra_edges:
        bad("edge_not_in_graph", "图面画出了抽取图中不存在的连线：%s" % extra_edges)
    if cs != len(stages):
        bad("stage_count_mismatch", "layer_stages 中 %d 个阶段，JSON 有 %d 个" % (cs, len(stages)))
    else:
        ok("stage_count", "阶段数与 JSON 一致", str(cs))
    stage_text = "".join(ls.itertext()) if ls is not None else ""
    for n in orders:
        if str(n) not in stage_text:
            bad("stage_number_missing", "阶段编号 %s 未出现在图面" % n)
    if any(s.get("milestone") for s in stages):
        if "◆" not in text_all and 'data-milestone="1"' not in ET.tostring(root, encoding="unicode"):
            bad("milestone_not_rendered", "已声明里程碑但未在 SVG 中标记")
        else:
            ok("milestone_rendered", "里程碑标记存在")
    else:
        ok("milestone_rendered", "材料无里程碑声明，跳过里程碑渲染检查")

    # legend
    legend_el = find_id(root, "layer_legend")
    legend_text = "".join(legend_el.itertext()) if legend_el is not None else ""
    if legend_el is None or not legend_text.strip():
        bad("missing_legend", "缺少图例或图例为空")
    else:
        used = {c.get("kind") for c in conns}
        lack = [k for k in used if r.KIND_LABELS.get(k, k).split(" / ")[0] not in legend_text]
        if lack:
            bad("legend_missing_kind", "图例未解释连线类型：%s" % lack)
        else:
            ok("legend", "图例覆盖所有连线类型", ",".join(sorted(used)))

    # units
    unit_el = find_id(root, "layer_units")
    unit_text = "".join(unit_el.itertext()).strip() if unit_el is not None else ""
    has_unit = any(tok in unit_text for tok in UNIT_TOKENS) or ("定性" in unit_text)
    if unit_el is None or not unit_text or not has_unit:
        bad("missing_units", "缺少单位行或单位不可识别", unit_text)
    else:
        ok("units", "单位行存在", unit_text)

    # scale
    scale_el = find_id(root, "layer_scale")
    scale_text = "".join(scale_el.itertext()).strip() if scale_el is not None else ""
    has_line = any(local(x.tag) == "line" for x in (scale_el.iter() if scale_el is not None else []))
    nts = any(k in scale_text.lower() for k in ("not to scale", "非等比", "示意"))
    if scale_el is None or not ((has_line and any(t in scale_text for t in UNIT_TOKENS)) or nts):
        bad("missing_scale_bar", "缺少比例尺（数值+单位）或 not-to-scale 标识", scale_text)
    else:
        ok("scale_bar", "比例尺存在", scale_text)

    # palette
    used_colors = set()
    for el in root.iter():
        for attr in ("fill", "stroke"):
            v = el.get(attr)
            if v and HEX.fullmatch(v):
                used_colors.add(v.lower())
    outside = sorted(used_colors - r.ALLOWED_COLORS)
    if outside:
        bad("palette_not_colorblind_safe", "出现 Okabe-Ito/Viridis 之外的彩色值：%s" % outside)
    else:
        ok("palette", "配色全部来自 Okabe-Ito/Viridis", ",".join(sorted(used_colors)))

    # element map
    emp = os.path.join(out, "element_map.json")
    if not os.path.exists(emp):
        bad("missing_element_map", "缺少 element_map.json")
    else:
        emap = json.load(open(emp, encoding="utf-8"))
        have = {e.get("element") for e in emap}
        missing = [i for i in pids + cids + sids if i not in have]
        if missing:
            bad("element_map_incomplete", "element_map 缺少部件/连线/阶段：%s" % missing[:8])
        else:
            ok("element_map", "element_map 覆盖全部结构化元素", "entries=%d" % len(emap))
        nosrc = [e.get("element") for e in emap
                 if e.get("status") == "stated" and not str(e.get("source", "")).strip()]
        if nosrc:
            bad("element_map_no_source", "以下元素缺少 source：%s" % nosrc[:8])

    return finish(out, checks, errors, warnings,
                  {"parts": len(parts), "connections": len(conns), "stages": len(stages),
                   "milestones": sum(1 for s in stages if s.get("milestone")),
                   "colors": len(used_colors), "edges": edge_list})


def finish(out, checks, errors, warnings, stats):
    report = {"ok": not errors, "verdict": "PASS" if not errors else "FAIL",
              "checks": checks, "errors": errors, "warnings": warnings, "stats": stats}
    os.makedirs(out, exist_ok=True)
    with open(os.path.join(out, "selfcheck.json"), "w", encoding="utf-8") as fh:
        json.dump(report, fh, ensure_ascii=False, indent=1)
    return report


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="work")
    ap.add_argument("--name", default="route")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--require-preview", action="store_true",
                    help="导出后复检：要求同目录存在非空 PNG 预览")
    a = ap.parse_args()
    rep = check(a.out, a.name, a.require_preview)
    if a.json:
        print(json.dumps(rep, ensure_ascii=False, indent=1))
    else:
        print("PASS" if rep["ok"] else "FAIL")
        edges = (rep.get("stats") or {}).get("edges") or []
        print("extracted edges (%d): %s" % (len(edges), ", ".join(edges)))
        for e in rep["errors"]:
            print(" - [%s] %s" % (e["code"], e["detail"]))
        print("stats:", json.dumps(rep["stats"], ensure_ascii=False))
    return 0 if rep["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
