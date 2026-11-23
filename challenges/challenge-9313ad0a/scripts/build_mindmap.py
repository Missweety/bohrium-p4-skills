#!/usr/bin/env python3
"""Validate a mind-map plan and export editable Markdown, FreeMind XML, SVG, CSV and result.json.

The agent authors plan.json; this script performs deterministic structure checks,
quote verification against extracted sources, layout and contract assembly.

Usage:
  python3 build_mindmap.py --plan /app/work/plan.json --sources /app/work/sources.json \
      --case /input/case.json --out /app/output --work /app/work
"""
import argparse
import csv
import html
import json
import math
import os
import re
import xml.etree.ElementTree as ET

TYPES = {"question", "method", "evidence", "result", "conclusion", "task", "risk", "concept"}
RELS = {"causes", "depends_on", "supports", "contradicts", "compares", "precedes", "cites", "part_of"}
TYPE_COLOR = {
    "question": "#dbeafe", "method": "#dcfce7", "evidence": "#fef9c3",
    "result": "#e0e7ff", "conclusion": "#fee2e2", "task": "#ffedd5",
    "risk": "#fde68a", "concept": "#f1f5f9",
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
    for doc in sources.get("documents", []):
        for para in doc.get("paragraphs", []):
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
    issues, warnings = [], []
    nodes = plan.get("nodes") or []
    edges = plan.get("edges") or []
    root = plan.get("root") or {}
    if not root.get("id"):
        issues.append("plan.root.id missing")
    ids = {}
    for node in nodes:
        nid = node.get("id")
        if not nid:
            issues.append("node without id: %s" % node.get("label"))
            continue
        if nid in ids:
            issues.append("duplicate node id: %s" % nid)
        ids[nid] = node
        if node.get("type") not in TYPES:
            warnings.append("node %s has unknown type %r" % (nid, node.get("type")))
        label = (node.get("label") or "").strip()
        if not 2 <= len(label) <= 60:
            warnings.append("node %s label length %d outside 4-40 target" % (nid, len(label)))
        conf = node.get("confidence")
        if conf not in {"fact", "summary", "inference"}:
            issues.append("node %s missing valid confidence" % nid)
        if conf in {"fact", "summary"}:
            ev = node.get("evidence") or {}
            quote = ev.get("quote")
            anchor = ev.get("anchor")
            if not quote or not anchor:
                issues.append("node %s (%s) lacks quote/anchor" % (nid, conf))
                node["verified"] = False
            else:
                ok, hit = verify_quote(quote, anchor, index)
                node["verified"] = ok
                node["verified_anchor"] = hit or anchor
                if ok and hit and hit != anchor:
                    node["evidence"]["anchor"] = hit
                    node["anchor_corrected_from"] = anchor
                    plan.setdefault("change_log", []).append(
                        "node %s anchor corrected from %s to %s by quote match" % (nid, anchor, hit))
                if not ok:
                    issues.append("node %s quote not found in source" % nid)
        elif conf == "inference":
            if not (node.get("basis") or "").strip():
                issues.append("node %s inference without basis" % nid)
            node["verified"] = False
    for node in nodes:
        nid = node.get("id")
        parent = node.get("parent")
        if node is root or nid == root.get("id"):
            continue
        if parent and parent not in ids:
            issues.append("node %s parent %s missing" % (nid, parent))
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
                issues.append("node %s is not reachable from root (parent chain broken or cyclic)" % nid)
        elif nid in seen:
            issues.append("node %s parent chain is cyclic" % nid)
        else:
            reachable.add(nid)
        depth[nid] = d
    if depth and max(depth.values()) > 6:
        warnings.append("tree depth %d exceeds 5" % max(depth.values()))
    siblings = {}
    for n in nodes:
        if n.get("id") == root.get("id"):
            continue
        key = (n.get("parent"), n.get("type"))
        siblings[key] = siblings.get(key, 0) + 1
    for key, count in siblings.items():
        if count > 9:
            warnings.append("parent %s has %d %s children (limit 9)" % (key[0], count, key[1]))
    labels = {}
    for n in nodes:
        key = norm(n.get("label"))
        labels[key] = labels.get(key, 0) + 1
    for key, count in labels.items():
        if key and count > 1:
            warnings.append("duplicate label: %s" % key)
    # edges
    graph = {}
    for e in edges:
        if e.get("from") not in ids or e.get("to") not in ids:
            issues.append("edge endpoint missing: %s -> %s" % (e.get("from"), e.get("to")))
            continue
        if e.get("relation") not in RELS:
            warnings.append("unknown relation %r" % e.get("relation"))
        if e.get("confidence") == "inference" and not (e.get("basis") or "").strip():
            issues.append("inference edge %s->%s lacks basis" % (e.get("from"), e.get("to")))
        if e.get("relation") in {"causes", "precedes", "depends_on"}:
            graph.setdefault(e["from"], []).append(e["to"])
    # cycle detection on ordering relations
    state = {}

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
            issues.append("cycle detected in ordering relations")
            break
    verified = sum(1 for n in nodes if n.get("verified"))
    checked = sum(1 for n in nodes if n.get("confidence") in {"fact", "summary"})
    stats = {
        "node_count": len(nodes), "edge_count": len(edges),
        "verified_nodes": verified, "checked_nodes": checked,
        "verification_rate": round(verified / checked, 4) if checked else 1.0,
        "max_depth": max(depth.values()) if depth else 0,
    }
    return issues, warnings, stats


def write_markdown(plan, nodes, root, out_path):
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


def write_freemind(plan, nodes, root, out_path):
    root_el = ET.Element("map", {"version": "1.0.1"})
    ET.SubElement(root_el, "node", {"TEXT": root.get("label", "root"), "ID": root.get("id", "r")})
    top = root_el.find("node")

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

    def place(nid, depth):
        kids = children.get(nid, [])
        if not kids:
            leaves.append(nid)
            pos[nid] = [depth, len(leaves) - 1]
            return len(leaves) - 1
        ys = [place(k.get("id"), depth + 1) for k in kids]
        pos[nid] = [depth, sum(ys) / float(len(ys))]
        return pos[nid][1]

    place(root.get("id"), 0)
    return pos, max(len(leaves), 1)


def write_svg(plan, nodes, edges, root, out_path):
    pos, n_leaves = layout(nodes, root)
    max_depth = max((p[0] for p in pos.values()), default=0)
    col_w, row_h = 230, 64
    width = 220 + max_depth * col_w
    height = 40 + n_leaves * row_h
    by_id = {n.get("id"): n for n in nodes}
    parts = ['<svg xmlns="http://www.w3.org/2000/svg" width="%d" height="%d" viewBox="0 0 %d %d">' % (width, height, width, height)]
    parts.append('<defs><marker id="arrow" markerWidth="8" markerHeight="8" refX="7" refY="4" orient="auto">'
                 '<path d="M0,0 L8,4 L0,8 z" fill="#475569"/></marker></defs>')
    parts.append('<rect width="100%" height="100%" fill="#ffffff"/>')
    parts.append('<text x="16" y="24" font-family="sans-serif" font-size="16" font-weight="bold">%s</text>'
                 % html.escape(plan.get("title", "Mind map"))[:60])
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


def contract_keys(case):
    oc = case.get("output_contract") if isinstance(case, dict) else None
    if isinstance(oc, dict):
        return list(oc.keys())
    if isinstance(oc, list):
        keys = []
        for item in oc:
            if isinstance(item, str):
                keys.append(item)
            elif isinstance(item, dict):
                keys.append(item.get("name") or item.get("field") or item.get("key"))
        return [k for k in keys if k]
    return []


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--plan", default="/app/work/plan.json")
    ap.add_argument("--sources", default="/app/work/sources.json")
    ap.add_argument("--case", default="/input/case.json")
    ap.add_argument("--out", default="/app/output")
    ap.add_argument("--work", default="/app/work")
    a = ap.parse_args()
    plan = load_json(a.plan)
    if not isinstance(plan, dict):
        raise SystemExit("plan.json missing or invalid")
    sources = load_json(a.sources, {}) or {}
    case = load_json(a.case, {}) or {}
    os.makedirs(a.out, exist_ok=True)
    index = build_quote_index(sources)
    issues, warnings, stats = validate(plan, index)
    nodes = plan.get("nodes") or []
    edges = plan.get("edges") or []
    root = plan.get("root") or {"id": "r", "label": plan.get("title", "root"), "type": "concept"}
    if not any(n.get("id") == root.get("id") for n in nodes):
        nodes = [{"id": root.get("id", "r"), "label": root.get("label", "root"),
                  "type": "concept", "confidence": "summary",
                  "parent": None, "verified": False}] + nodes
    path_md = os.path.join(a.out, "mindmap.md")
    path_mm = os.path.join(a.out, "mindmap.mm")
    path_svg = os.path.join(a.out, "mindmap.svg")
    path_csv = os.path.join(a.out, "nodes.csv")
    write_markdown(plan, nodes, root, path_md)
    write_freemind(plan, nodes, root, path_mm)
    write_svg(plan, nodes, edges, root, path_svg)
    write_csv(nodes, path_csv)

    case_id = case.get("case_id") or case.get("id") or plan.get("case_id") or "unknown"
    evidence_index = {}
    for n in nodes:
        ev = n.get("evidence") or {}
        if ev.get("anchor") and ev.get("quote"):
            evidence_index[ev["anchor"]] = {
                "quote": ev["quote"], "verified": bool(n.get("verified")), "doc": ev["anchor"].split()[0],
            }
    status = "success"
    if issues:
        status = "partial" if stats["node_count"] > 2 else "failed"
    if not index:
        status = "failed"
        issues.append("no readable source paragraphs")
    result = {
        "case_id": case_id,
        "status": status,
        "sources": [{"path": d.get("path"), "bytes": d.get("bytes"), "sha256": d.get("sha256"),
                     "readable": d.get("readable"), "engine": d.get("engine"),
                     "anchor_scheme": "doc.N p.N sec.N para.K"} for d in sources.get("documents", [])],
        "uncertainty": plan.get("uncertainty") or [],
        "change_log": plan.get("change_log") or [],
        "mindmap": {
            "title": plan.get("title"), "purpose": plan.get("purpose"),
            "audience": plan.get("audience"), "root_id": root.get("id"),
            "node_count": stats["node_count"], "edge_count": stats["edge_count"],
            "files": {"markdown": path_md, "freemind": path_mm, "svg": path_svg, "csv": path_csv},
        },
        "nodes": nodes,
        "edges": edges,
        "evidence_index": evidence_index,
        "stats": stats,
        "issues": [],
        "contract_fields": {},
    }
    contract = {}
    provided = plan.get("contract_fields") or {}
    keys = contract_keys(case)
    if not keys:
        issues.append("output_contract missing in case.json; default result fields emitted")
        plan.setdefault("change_log", []).append("output_contract missing; emitted default fields")
    for key in keys:
        if key in provided:
            value = provided[key]
        elif key in result:
            value = result[key]
        elif key in plan:
            value = plan[key]
        else:
            value = None
            issues.append("output_contract field %s not provided" % key)
        contract[key] = value
        if value is not None:
            result.setdefault(key, value)
    if issues and status == "success":
        status = "partial" if stats["node_count"] > 2 else "failed"
    result["status"] = status
    result["issues"] = issues + warnings
    result["change_log"] = plan.get("change_log") or []
    result["contract_fields"] = contract
    with open(os.path.join(a.out, "result.json"), "w", encoding="utf-8") as fh:
        json.dump(result, fh, ensure_ascii=False, indent=1)
    print(json.dumps({"status": status, "nodes": stats["node_count"], "edges": stats["edge_count"],
                      "verification_rate": stats["verification_rate"],
                      "issues": len(issues), "warnings": len(warnings)}, ensure_ascii=False))
    if status == "failed":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
