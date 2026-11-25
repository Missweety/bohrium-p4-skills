#!/usr/bin/env python3
"""Validate a mind-map plan and export editable Markdown, FreeMind XML, SVG, CSV and result.json.

The agent authors plan.json; this script performs deterministic structure checks,
quote verification against extracted sources, layout and contract assembly.
It always writes result.json (status success/partial/failed), so a missing or
invalid plan degrades honestly instead of leaving the output directory empty.

Usage:
  python3 build_mindmap.py --plan /app/work/plan.json --sources /app/work/sources.json \
      --case /input/case.json --out /app/output --work /app/work
"""
import argparse
import csv
import html
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET

TYPES = {"question", "method", "evidence", "result", "conclusion", "task", "risk", "concept"}
RELS = {"causes", "depends_on", "supports", "contradicts", "compares", "precedes", "cites", "part_of"}
TYPE_COLOR = {
    "question": "#dbeafe", "method": "#dcfce7", "evidence": "#fef9c3",
    "result": "#e0e7ff", "conclusion": "#fee2e2", "task": "#ffedd5",
    "risk": "#fde68a", "concept": "#f1f5f9",
}
SLOT_ALIASES = {
    "mindmap": "mindmap", "mind_map": "mindmap", "outline": "mindmap",
    "mindmap_md": "mindmap", "导图": "mindmap", "思维导图": "mindmap",
    "nodes": "nodes", "node_list": "nodes", "nodes_csv": "nodes",
    "edges": "edges", "relations": "edges", "edges_csv": "edges",
    "evidence_index": "evidence_index", "evidence": "evidence_index",
    "sources": "sources", "uncertainty": "uncertainty", "change_log": "change_log",
    "changes": "change_log", "status": "status", "case_id": "case_id",
    "issues": "issues", "warnings": "warnings", "stats": "stats",
    "files": "files", "artifacts": "files", "deliverables": "files",
    "svg": "svg", "svg_path": "svg", "preview": "svg", "preview_svg": "svg",
}


def norm(text):
    text = (text or "").replace("\u3000", " ").replace("\xa0", " ")
    text = re.sub(r"\s+", "", text)
    return text


def load_json(path, default=None):
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:  # noqa: BLE001
        return default


def build_quote_index(sources):
    index = {}
    for doc in sources.get("documents", []) or []:
        for para in doc.get("paragraphs", []) or []:
            index[para["anchor"]] = norm(para.get("text"))
    return index


def verify_quote(quote, anchor, index):
    q = norm(quote)
    if not q:
        return False, ""
    if anchor in index and q in index[anchor]:
        return True, anchor
    for a, text in index.items():
        if q and q in text:
            return True, a
    return False, ""


def wrap(label, width):
    lines, cur = [], ""
    for ch in str(label):
        if len(cur) >= width:
            lines.append(cur)
            cur = ""
        cur += ch
    if cur:
        lines.append(cur)
    return lines or [""]


def validate(plan, index):
    """Return (errors, warnings, stats); each error/warning is a structured dict."""
    errors, warnings = [], []

    def err(code, detail):
        errors.append({"code": code, "severity": "error", "detail": detail})

    def warn(code, detail):
        warnings.append({"code": code, "severity": "warn", "detail": detail})

    nodes = [n for n in (plan.get("nodes") or []) if isinstance(n, dict)]
    edges = [e for e in (plan.get("edges") or []) if isinstance(e, dict)]
    root = plan.get("root") or {}
    if not root.get("id"):
        err("root_missing", "plan.root.id 缺失：导图没有根节点")
    ids = {}
    for node in nodes:
        nid = node.get("id")
        if not nid:
            err("node_without_id", "存在没有 id 的节点：%s" % node.get("label"))
            continue
        if nid in ids:
            err("duplicate_node_id", "节点 id 重复：%s" % nid)
        ids[nid] = node
        if node.get("type") not in TYPES:
            warn("unknown_node_type", "节点 %s 的 type=%r 不在约定集合内" % (nid, node.get("type")))
        label = (node.get("label") or "").strip()
        if not label:
            err("node_label_missing", "节点 %s 没有 label" % nid)
        elif not 4 <= len(label) <= 40:
            warn("label_length", "节点 %s 的 label 长度 %d 不在建议区间 4–40（硬限 2–60）"
                 % (nid, len(label)))
        conf = node.get("confidence")
        if conf not in {"fact", "summary", "inference"}:
            err("confidence_invalid", "节点 %s 缺少合法的 confidence（fact/summary/inference）" % nid)
        if conf in {"fact", "summary"}:
            ev = node.get("evidence") or {}
            quote = ev.get("quote")
            anchor = ev.get("anchor")
            if not quote or not anchor:
                err("evidence_missing", "节点 %s（%s）缺少 evidence.quote/anchor" % (nid, conf))
                node["verified"] = False
            else:
                ok, hit = verify_quote(quote, anchor, index)
                node["verified"] = ok
                node["verified_anchor"] = hit or anchor
                if ok and hit and hit != anchor:
                    node["evidence"]["anchor"] = hit
                    node["anchor_corrected_from"] = anchor
                    plan.setdefault("change_log", []).append(
                        "node %s 的锚点由 %s 校正为 %s（引文命中）" % (nid, anchor, hit))
                if not ok:
                    err("quote_unverified", "节点 %s 的引文在源文中找不到：%s"
                        % (nid, str(quote)[:80]))
        elif conf == "inference":
            if not (node.get("basis") or "").strip():
                err("inference_without_basis", "节点 %s 标为 inference 但没有 basis" % nid)
            node["verified"] = False
    for node in nodes:
        nid = node.get("id")
        parent = node.get("parent")
        if node is root or nid == root.get("id"):
            continue
        if parent and parent not in ids:
            err("parent_missing", "节点 %s 的 parent=%s 不存在" % (nid, parent))
    # tree depth and reachability
    parent_of = {n.get("id"): n.get("parent") for n in nodes}
    depth = {}
    reachable = {root.get("id")}
    root_present = root.get("id") in ids
    for nid in parent_of:
        if nid == root.get("id"):
            depth[nid] = 1
            continue
        seen, cur, d = set(), nid, 1
        while cur and cur not in (None, root.get("id")) and cur not in seen:
            seen.add(cur)
            cur = parent_of.get(cur)
            d += 1
            if d > 12:
                break
        if root_present:
            if cur == root.get("id"):
                reachable.add(nid)
            else:
                err("unreachable_node", "节点 %s 无法从根节点到达（父链断裂或成环）" % nid)
        elif nid in seen:
            err("cyclic_parent", "节点 %s 的父链成环" % nid)
        else:
            reachable.add(nid)
        depth[nid] = d
    if depth and max(depth.values()) > 6:
        warn("tree_depth", "层级深度 %d 超过建议的 5 层" % max(depth.values()))
    siblings = {}
    for n in nodes:
        if n.get("id") == root.get("id"):
            continue
        key = (n.get("parent"), n.get("type"))
        siblings[key] = siblings.get(key, 0) + 1
    for key, count in siblings.items():
        if count > 9:
            warn("siblings_over_limit", "父节点 %s 下有 %d 个 %s 子节点（建议上限 9）"
                 % (key[0], count, key[1]))
    labels = {}
    for n in nodes:
        key = norm(n.get("label"))
        labels[key] = labels.get(key, 0) + 1
    for key, count in labels.items():
        if key and count > 1:
            warn("duplicate_label", "节点 label 重复 %d 次：%s" % (count, key))
    # edges
    graph = {}
    for e in edges:
        if e.get("from") not in ids or e.get("to") not in ids:
            err("edge_endpoint_missing", "关系端点不存在：%s -> %s" % (e.get("from"), e.get("to")))
            continue
        if e.get("relation") not in RELS:
            warn("unknown_relation", "关系类型 %r 不在约定集合内" % e.get("relation"))
        if e.get("confidence") not in {"fact", "inference"}:
            warn("edge_confidence_missing", "关系 %s->%s 的 confidence 缺失或非法"
                 % (e.get("from"), e.get("to")))
        if e.get("confidence") == "inference" and not (e.get("basis") or "").strip():
            err("inference_edge_without_basis",
                "推断关系 %s->%s 缺少 basis" % (e.get("from"), e.get("to")))
        if e.get("relation") in {"causes", "precedes", "depends_on"}:
            graph.setdefault(e["from"], []).append(e["to"])
    # cycle detection on ordering relations
    state = {}
    cycle = [False]

    def visit(u):
        state[u] = 1
        for v in graph.get(u, []):
            if state.get(v) == 1:
                return True
            if state.get(v) is None and visit(v):
                return True
        state[u] = 2
        return False

    for u in list(graph):
        if state.get(u) is None and visit(u):
            cycle[0] = True
            break
    if cycle[0]:
        err("relation_cycle", "causes/precedes/depends_on 关系中存在环")
    verified = sum(1 for n in nodes if n.get("verified"))
    checked = sum(1 for n in nodes if n.get("confidence") in {"fact", "summary"})
    stats = {
        "node_count": len(nodes), "edge_count": len(edges),
        "verified_nodes": verified, "checked_nodes": checked,
        "verification_rate": round(verified / checked, 4) if checked else 0.0,
        "max_depth": max(depth.values()) if depth else 0,
        "unverified_nodes": [n.get("id") for n in nodes
                             if n.get("confidence") in {"fact", "summary"} and not n.get("verified")],
    }
    return errors, warnings, stats


def write_markdown(plan, nodes, root, out_path, status):
    children = {}
    for n in nodes:
        if n.get("id") == root.get("id"):
            continue
        children.setdefault(n.get("parent"), []).append(n)
    lines = ["# %s" % plan.get("title", "思维导图"), ""]
    if plan.get("purpose"):
        lines.append("- 用途：%s" % plan["purpose"])
    if plan.get("audience"):
        lines.append("- 读者：%s" % plan["audience"])
    lines.append("- 状态：%s" % status)
    lines.append("")

    def emit(nid, level):
        node = next((n for n in nodes if n.get("id") == nid), None)
        if node is None:
            return
        ev = node.get("evidence") or {}
        meta = "[%s/%s]" % (node.get("type", "concept"), node.get("confidence", "inference"))
        anchor = ev.get("anchor") or node.get("verified_anchor") or ""
        lines.append("%s- **%s** %s%s" % ("  " * level, node.get("label", ""), meta,
                                          (" {anchor: %s}" % anchor) if anchor else ""))
        quote = ev.get("quote")
        if quote:
            lines.append("%s  > %s" % ("  " * level, quote.replace("\n", " ")))
        if node.get("basis"):
            lines.append("%s  > 依据：%s" % ("  " * level, node["basis"]))
        for child in children.get(nid, []):
            emit(child.get("id"), level + 1)

    emit(root.get("id"), 0)
    with open(out_path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")


def write_freemind(plan, nodes, root, out_path, status):
    root_el = ET.Element("map", {"version": "1.0.1"})
    ET.SubElement(root_el, "node", {"TEXT": root.get("label", "root"), "ID": root.get("id", "r")})
    top = root_el.find("node")
    ET.SubElement(top, "richcontent", {"TYPE": "NOTE"}).text = "status=%s" % status

    def add(parent_el, parent_id):
        for n in nodes:
            if n.get("parent") != parent_id or n.get("id") == root.get("id"):
                continue
            attrs = {"TEXT": n.get("label", ""), "ID": n.get("id", "")}
            child = ET.SubElement(parent_el, "node", attrs)
            ev = n.get("evidence") or {}
            note = "type=%s; confidence=%s" % (n.get("type"), n.get("confidence"))
            if ev.get("anchor"):
                note += "; anchor=%s" % ev["anchor"]
            if ev.get("quote"):
                note += "; quote=%s" % ev["quote"]
            if n.get("basis"):
                note += "; basis=%s" % n["basis"]
            ET.SubElement(child, "richcontent", {"TYPE": "NOTE"}).text = note
            add(child, n.get("id"))

    add(top, root.get("id"))
    tree = ET.ElementTree(root_el)
    tree.write(out_path, encoding="utf-8", xml_declaration=True)


def layout(nodes, root):
    children = {}
    for n in nodes:
        if n.get("id") == root.get("id"):
            continue
        children.setdefault(n.get("parent"), []).append(n)
    pos = {}
    leaves = []

    def place(nid, depth, seen):
        if nid in seen:
            return 0.0
        seen = seen | {nid}
        kids = [k for k in children.get(nid, []) if k.get("id") not in seen]
        if not kids:
            leaves.append(nid)
            pos[nid] = [depth, len(leaves) - 1]
            return len(leaves) - 1
        ys = [place(k.get("id"), depth + 1, seen) for k in kids]
        pos[nid] = [depth, sum(ys) / float(len(ys))]
        return pos[nid][1]

    place(root.get("id"), 0, set())
    return pos, max(len(leaves), 1)


def write_svg(plan, nodes, edges, root, out_path, status):
    pos, n_leaves = layout(nodes, root)
    max_depth = max((p[0] for p in pos.values()), default=0)
    col_w, row_h = 230, 64
    width = 220 + max_depth * col_w
    height = 40 + n_leaves * row_h
    by_id = {n.get("id"): n for n in nodes}
    parts = ['<svg xmlns="http://www.w3.org/2000/svg" width="%d" height="%d" viewBox="0 0 %d %d">'
             % (width, height, width, height)]
    parts.append('<defs><marker id="arrow" markerWidth="8" markerHeight="8" refX="7" refY="4" orient="auto">'
                 '<path d="M0,0 L8,4 L0,8 z" fill="#475569"/></marker></defs>')
    parts.append('<rect width="100%" height="100%" fill="#ffffff"/>')
    parts.append('<text x="16" y="24" font-family="sans-serif" font-size="16" font-weight="bold">%s</text>'
                 % html.escape(plan.get("title", "Mind map"))[:60])
    parts.append('<text x="16" y="40" font-family="sans-serif" font-size="10" fill="#64748b">status=%s</text>'
                 % html.escape(status))
    coords = {}
    for nid, (depth, y) in pos.items():
        node = by_id.get(nid) or root
        x = 20 + depth * col_w
        cy = 60 + y * row_h
        lines = wrap(node.get("label", ""), 14)
        box_h = 18 + 18 * len(lines)
        coords[nid] = (x, cy - box_h / 2.0, 200, box_h)
    for e in edges:
        if e.get("from") not in coords or e.get("to") not in coords:
            continue
        x1, y1, w1, h1 = coords[e["from"]]
        x2, y2, w2, h2 = coords[e["to"]]
        sx, sy = x1 + w1, y1 + h1 / 2.0
        tx, ty = x2, y2 + h2 / 2.0
        dash = ' stroke-dasharray="5,4"' if e.get("confidence") == "inference" or e.get("relation") == "contradicts" else ""
        parts.append('<path d="M%.1f,%.1f C%.1f,%.1f %.1f,%.1f %.1f,%.1f" fill="none" stroke="#475569" stroke-width="1.3"%s marker-end="url(#arrow)"/>'
                     % (sx, sy, sx + 30, sy, tx - 30, ty, tx - 2, ty, dash))
        mx, my = (sx + tx) / 2.0, (sy + ty) / 2.0 - 3
        parts.append('<text x="%.1f" y="%.1f" font-family="sans-serif" font-size="9" fill="#64748b" text-anchor="middle">%s</text>'
                     % (mx, my, html.escape(e.get("relation", ""))))
    for nid, (x, y, w, h) in coords.items():
        node = by_id.get(nid) or root
        fill = TYPE_COLOR.get(node.get("type"), "#f1f5f9")
        parts.append('<rect x="%.1f" y="%.1f" width="%d" height="%.1f" rx="8" fill="%s" stroke="#64748b" stroke-width="1"/>'
                     % (x, y, w, h, fill))
        lines = wrap(node.get("label", ""), 14)
        for i, line in enumerate(lines):
            parts.append('<text x="%.1f" y="%.1f" font-family="sans-serif" font-size="11" fill="#0f172a">%s</text>'
                         % (x + 8, y + 16 + i * 15, html.escape(line)))
    parts.append("</svg>")
    with open(out_path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(parts))


def write_csv(nodes, out_path):
    with open(out_path, "w", encoding="utf-8", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(["id", "label", "type", "confidence", "anchor", "quote", "verified"])
        for n in nodes:
            ev = n.get("evidence") or {}
            writer.writerow([n.get("id"), n.get("label"), n.get("type"), n.get("confidence"),
                             ev.get("anchor") or n.get("verified_anchor", ""),
                             ev.get("quote", ""), n.get("verified", False)])


def render_png(svg_path, png_path):
    """Best-effort raster preview; returns the tool name or "" when unavailable."""
    if shutil.which("rsvg-convert"):
        try:
            subprocess.run(["rsvg-convert", "-o", png_path, svg_path],
                           check=True, timeout=60, capture_output=True)
            return "rsvg-convert"
        except Exception:  # noqa: BLE001
            return ""
    if importlib.util.find_spec("cairosvg"):
        try:
            import cairosvg  # type: ignore
            cairosvg.svg2png(url=svg_path, write_to=png_path)
            return "cairosvg"
        except Exception:  # noqa: BLE001
            return ""
    return ""


def contract_keys(case):
    oc = case.get("output_contract") if isinstance(case, dict) else None
    if oc is None and isinstance(case, dict):
        for alt in ("outputContract", "contract", "required_outputs"):
            if alt in case:
                oc = case.get(alt)
                break
    names = []
    if isinstance(oc, dict):
        for key in oc.keys():
            if key in ("required", "fields", "properties") and isinstance(oc[key], (list, dict)):
                continue
            names.append(key)
        for key in ("required", "fields", "properties"):
            val = oc.get(key)
            if isinstance(val, list):
                for item in val:
                    if isinstance(item, str):
                        names.append(item)
                    elif isinstance(item, dict):
                        n = item.get("name") or item.get("field") or item.get("key") or item.get("id")
                        if n:
                            names.append(n)
            elif isinstance(val, dict):
                names.extend(list(val.keys()))
    elif isinstance(oc, list):
        for item in oc:
            if isinstance(item, str):
                names.append(item)
            elif isinstance(item, dict):
                n = item.get("name") or item.get("field") or item.get("key") or item.get("id")
                if n:
                    names.append(n)
    seen, out = set(), []
    for n in names:
        if isinstance(n, str) and n.strip() and n not in seen:
            seen.add(n)
            out.append(n)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--plan", default="/app/work/plan.json")
    ap.add_argument("--sources", default="/app/work/sources.json")
    ap.add_argument("--case", default="/input/case.json")
    ap.add_argument("--out", default="/app/output")
    ap.add_argument("--work", default="/app/work")
    a = ap.parse_args()

    plan_raw = load_json(a.plan)
    plan_missing = not isinstance(plan_raw, dict)
    plan = {} if plan_missing else plan_raw
    sources = load_json(a.sources, {}) or {}
    if not isinstance(sources, dict):
        sources = {}
    case = load_json(a.case, {}) or {}
    if not isinstance(case, dict):
        case = {}
    os.makedirs(a.out, exist_ok=True)
    os.makedirs(a.work, exist_ok=True)
    index = build_quote_index(sources)

    nodes = [n for n in (plan.get("nodes") or []) if isinstance(n, dict)]
    edges = [e for e in (plan.get("edges") or []) if isinstance(e, dict)]
    root = plan.get("root") if isinstance(plan.get("root"), dict) else {}
    if not root.get("id"):
        root = {"id": "r", "label": plan.get("title") or "思维导图", "type": "concept"}
    change_log = list(plan.get("change_log") or [])
    if not any(n.get("id") == root.get("id") for n in nodes):
        nodes = [{"id": root.get("id"),
                  "label": root.get("label") or plan.get("title") or "思维导图",
                  "type": "concept", "confidence": "inference", "parent": None,
                  "basis": "根节点由 plan.root/title 生成；材料中没有单一对应段落，需人工确认"}] + nodes
        change_log.append("plan.nodes 缺少根节点，已按 plan.root 生成（confidence=inference）")
    plan["nodes"] = nodes
    plan["root"] = root

    errors, warnings, stats = validate(plan, index)
    issues = list(errors)
    if plan_missing:
        issues.append({"code": "plan_missing", "severity": "error",
                       "detail": "plan.json 缺失或不是 JSON 对象：没有可交付的导图内容（%s）" % a.plan})
    if not index:
        issues.append({"code": "no_readable_sources", "severity": "error",
                       "detail": "sources.json 中没有可读段落，所有引文都无法核验"})
    status = "success"
    if plan_missing or not index or (issues and stats["node_count"] <= 2):
        status = "failed"
    elif issues:
        status = "partial"
    reasons = []
    if plan_missing:
        reasons.append("plan.json 缺失")
    if not index:
        reasons.append("没有可读源文")
    if errors:
        reasons.append("%d 项结构/证据问题" % len(errors))
    if warnings:
        reasons.append("%d 项提示" % len(warnings))
    if status == "success":
        status_reason = "树结构、关系端点与引文核验全部通过"
    elif status == "failed":
        status_reason = "无法形成可核验导图：%s" % "、".join(reasons)
    else:
        status_reason = "已产出可编辑导图，但存在%s（见 issues）" % "、".join(reasons)

    path_md = os.path.join(a.out, "mindmap.md")
    path_mm = os.path.join(a.out, "mindmap.mm")
    path_svg = os.path.join(a.out, "mindmap.svg")
    path_csv = os.path.join(a.out, "nodes.csv")
    write_markdown(plan, nodes, root, path_md, status)
    write_freemind(plan, nodes, root, path_mm, status)
    write_svg(plan, nodes, edges, root, path_svg, status)
    write_csv(nodes, path_csv)
    path_png = os.path.join(a.out, "mindmap.png")
    png_tool = render_png(path_svg, path_png)
    if not png_tool:
        warnings.append({"code": "png_preview_missing", "severity": "warn",
                         "detail": "未找到 rsvg-convert 或 cairosvg，未生成 PNG 预览；SVG 为真实渲染结果"})
    files = {"markdown": path_md, "freemind": path_mm, "svg": path_svg, "csv": path_csv}
    if png_tool:
        files["png"] = path_png

    case_id = case.get("case_id") or case.get("id") or plan.get("case_id") or "unknown"
    evidence_index = {}
    for n in nodes:
        ev = n.get("evidence") or {}
        if ev.get("anchor") and ev.get("quote"):
            evidence_index[ev["anchor"]] = {
                "quote": ev["quote"], "verified": bool(n.get("verified")),
                "doc": ev["anchor"].split()[0],
            }
    result = {
        "case_id": case_id,
        "status": status,
        "status_reason": status_reason,
        "sources": [{"path": d.get("path"), "bytes": d.get("bytes"), "sha256": d.get("sha256"),
                     "readable": d.get("readable"), "engine": d.get("engine"),
                     "anchor_scheme": "doc.N p.N sec.N para.K"} for d in sources.get("documents", [])],
        "uncertainty": plan.get("uncertainty") or [],
        "change_log": change_log,
        "mindmap": {
            "title": plan.get("title"), "purpose": plan.get("purpose"),
            "audience": plan.get("audience"), "root_id": root.get("id"),
            "node_count": stats["node_count"], "edge_count": stats["edge_count"],
            "files": files,
        },
        "nodes": nodes,
        "edges": edges,
        "evidence_index": evidence_index,
        "stats": stats,
        "issues": issues,
        "warnings": warnings,
        "contract_fields": {},
    }
    for w in warnings:
        if w["code"] == "png_preview_missing":
            result["uncertainty"].append({"issue": "PNG 预览未生成",
                                          "decision": "当前环境无 rsvg-convert/cairosvg，交付 SVG 矢量预览",
                                          "needs_human": False})

    contract = {}
    provided = plan.get("contract_fields") if isinstance(plan.get("contract_fields"), dict) else {}
    keys = contract_keys(case)
    if not keys:
        issues.append({"code": "output_contract_missing", "severity": "warn",
                       "detail": "case.json 未声明 output_contract；已输出默认结构字段"})
        change_log.append("output_contract 缺失；输出默认字段")
    for key in keys:
        slot = SLOT_ALIASES.get(key.strip().lower())
        if key in provided:
            value = provided[key]
        elif slot == "svg":
            value = path_svg
        elif slot == "files":
            value = files
        elif slot and slot in result:
            value = result[slot]
        elif key in result:
            value = result[key]
        elif key in plan:
            value = plan[key]
        else:
            value = None
            issues.append({"code": "contract_field_unresolved", "severity": "warn",
                           "detail": "output_contract 字段 %s 未取到内容，已写 null 并标注" % key})
        contract[key] = value
        if value is not None:
            result.setdefault(key, value)
    result["issues"] = issues
    result["change_log"] = change_log
    result["contract_fields"] = contract
    with open(os.path.join(a.out, "result.json"), "w", encoding="utf-8") as fh:
        json.dump(result, fh, ensure_ascii=False, indent=1)
    print(json.dumps({"status": status, "reason": status_reason,
                      "nodes": stats["node_count"], "edges": stats["edge_count"],
                      "verification_rate": stats["verification_rate"],
                      "issues": len(issues), "warnings": len(warnings),
                      "png": png_tool or "none"}, ensure_ascii=False))
    return 0 if status in ("success", "partial") else 1


if __name__ == "__main__":
    sys.exit(main())
