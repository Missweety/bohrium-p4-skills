#!/usr/bin/env python3
"""render.py - emit an editable SVG (real <text>), graph.json and element_map.json.

Every drawn node/edge is a <g> with a <title>/<desc> carrying its source span, so the
figure is both human-readable and machine-auditable. Arrow heads are per-polarity SVG
markers (filled arrow / T-bar / circle / diamond / chevron / open) and every marker has
a labelled legend entry.
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import graphlib as G  # noqa: E402
import layout as L  # noqa: E402

NS = "http://www.w3.org/2000/svg"


def esc(s):
    return G.esc(s)


def parse_span(sp):
    if not sp:
        return {"file": "", "page": None, "section": "", "quote": "", "verified": False}
    loc = sp.get("locator", "")
    page = None
    if loc.startswith("page "):
        try:
            page = int(loc.split()[1])
        except (IndexError, ValueError):
            page = None
    return {"file": sp.get("file", ""), "page": page, "section": loc,
            "quote": sp.get("quote", ""), "verified": bool(sp.get("verified"))}


def first_span(n_or_e):
    ev = n_or_e.get("evidence") or []
    return ev[0] if ev else None


def marker(kind):
    color, m, dash, _, _ = G.KINDS[kind]
    if m == "arrow":
        body = '<path d="M0,0 L12,4.2 L0,8.4 z" fill="%s"/>' % color
        refx, refy, size = 11.5, 4.2, 14
    elif m == "bar":
        body = '<path d="M6,0 L6,12" stroke="%s" stroke-width="3.6" stroke-linecap="round"/>' % color
        refx, refy, size = 6, 6, 14
    elif m == "circle":
        body = ('<circle cx="6" cy="6" r="4.2" fill="#FFFFFF" stroke="%s" stroke-width="2.2"/>'
                % color)
        refx, refy, size = 9, 6, 14
    elif m == "diamond":
        body = ('<path d="M6,0.6 L11.4,6 L6,11.4 L0.6,6 z" fill="%s" stroke="#FFFFFF" '
                'stroke-width="0.8"/>' % color)
        refx, refy, size = 9, 6, 14
    elif m == "chevron":
        body = ('<path d="M2,1 L10,6 L2,11" fill="none" stroke="%s" stroke-width="2.2" '
                'stroke-linecap="round" stroke-linejoin="round"/>' % color)
        refx, refy, size = 9, 6, 14
    else:  # open
        body = ('<path d="M1,1 L11,6 L1,11" fill="none" stroke="%s" stroke-width="2.1" '
                'stroke-linejoin="round"/>' % color)
        refx, refy, size = 9, 6, 14
    return ('<marker id="mk-%s" viewBox="0 0 12 12" refX="%s" refY="%s" markerWidth="%s" '
            'markerHeight="%s" markerUnits="userSpaceOnUse" orient="auto-start-reverse">%s</marker>'
            % (kind, refx, refy, size, size, body))


def style_block():
    return """
    .title-main { font: 700 25px "Noto Sans CJK SC","PingFang SC","Hiragino Sans GB","Microsoft YaHei",sans-serif; fill: #111827; }
    .title-sub  { font: 400 13px "Noto Sans CJK SC","PingFang SC","Hiragino Sans GB",sans-serif; fill: #6B7280; }
    .band-label { font: 600 13px "Noto Sans CJK SC","PingFang SC","Hiragino Sans GB",sans-serif; fill: #374151; }
    .band-empty { font: 400 11.5px "Noto Sans CJK SC","PingFang SC","Hiragino Sans GB",sans-serif; fill: #9CA3AF; }
    .node-label { font-family: "Noto Sans CJK SC","PingFang SC","Hiragino Sans GB","Microsoft YaHei",sans-serif; font-weight: 650; fill: #111827; }
    .node-sub   { font-family: "Noto Sans CJK SC","PingFang SC",sans-serif; fill: #4B5563; }
    .edge-label { font-family: "Noto Sans CJK SC","PingFang SC",sans-serif; font-size: 10.5px; fill: #374151; paint-order: stroke; stroke: #FFFFFF; stroke-width: 4px; stroke-linejoin: round; }
    .legend-title { font: 700 13px "Noto Sans CJK SC","PingFang SC",sans-serif; fill: #111827; }
    .legend-text  { font: 400 11.5px "Noto Sans CJK SC","PingFang SC",sans-serif; fill: #374151; }
    .note-text    { font: 400 11px "Noto Sans CJK SC","PingFang SC",sans-serif; fill: #4B5563; }
    .note-head    { font: 700 12px "Noto Sans CJK SC","PingFang SC",sans-serif; fill: #111827; }
    """


def render(title, spec, lay, caption):
    H, Wd = lay["height"], lay["width"]
    o = []
    a = o.append
    a('<?xml version="1.0" encoding="UTF-8"?>')
    a('<svg xmlns="%s" width="%d" height="%d" viewBox="0 0 %d %d" '
      'role="img" aria-labelledby="fig-title fig-desc" data-generator="mechanism-skill/2.0">'
      % (NS, Wd, H, Wd, H))
    a('<title id="fig-title">%s</title>' % esc(title))
    a('<desc id="fig-desc">%s</desc>' % esc(caption))
    a('<defs>')
    for kind in G.KIND_ORDER:
        a(marker(kind))
    a('<style>%s</style>' % style_block())
    a('</defs>')
    a('<rect id="background" x="0" y="0" width="%d" height="%d" fill="#FFFFFF"/>' % (Wd, H))
    a('<rect x="0" y="0" width="%d" height="4" fill="#0072B2"/>' % Wd)

    # ---------- title
    a('<g id="layer-title">')
    a('<text class="title-main" x="46" y="52">%s</text>' % esc(title))
    a('<text class="title-sub" x="46" y="78">case %s · %d entities · %d relations · '
      'evidence mapped in element_map.json</text>'
      % (esc(spec.get("case_id", "")), len(spec["nodes"]), len(spec["edges"])))
    a('</g>')

    # ---------- compartment bands
    a('<g id="layer-compartments">')
    for b in lay["bands"]:
        a('<g class="compartment" id="band-%s" data-compartment="%s" data-count="%d">'
          % (b["id"], b["id"], b["count"]))
        a('<rect x="40" y="%.1f" width="%d" height="%.1f" rx="10" fill="#F7F9FC" '
          'stroke="#E2E8F0" stroke-width="1.2"/>' % (b["y"], Wd - 80, b["h"]))
        a('<text class="band-label" x="58" y="%.1f">%s · %d</text>'
          % (b["y"] + 22, esc(b["label"]), b["count"]))
        a('<title>%s</title><desc>compartment=%s, entities=%d</desc>'
          % (esc(b["label"]), b["id"], b["count"]))
        if not b["count"]:
            a('<text class="band-empty" x="%d" y="%.1f">（未提取到实体 / none extracted）</text>'
              % (Wd - 330, b["y"] + 30))
        a('</g>')
    a('</g>')

    # ---------- edges
    a('<g id="layer-edges">')
    for e in lay["edges"]:
        color, mk, dash, legend, short = G.KINDS[e["kind"]]
        src = next(n for n in spec["nodes"] if n["id"] == e["source"])
        tgt = next(n for n in spec["nodes"] if n["id"] == e["target"])
        sp = parse_span(first_span(e))
        dash_attr = ' stroke-dasharray="%s"' % dash if dash else ""
        if e.get("status") != "stated":
            dash_attr = ' stroke-dasharray="6 4"'
        start = ' marker-start="url(#mk-%s)"' % mk if mk == "circle" else ""
        a('<g class="edge kind-%s status-%s" id="edge-%s" data-source="%s" data-target="%s" '
          'data-kind="%s" data-status-value="%s">'
          % (e["kind"], e.get("status", "stated"), e["id"], esc(e["source"]),
             esc(e["target"]), e["kind"], e.get("status", "stated")))
        a('<path d="%s" fill="none" stroke="%s" stroke-width="2.4" stroke-linecap="round" '
          'marker-end="url(#mk-%s)"%s%s/>'
          % (e["d"], color, mk, start, dash_attr))
        a('<title>%s → %s (%s)</title>' % (esc(src["label"]), esc(tgt["label"]), esc(legend)))
        a('<desc>%s | source: %s | quote: %s</desc>'
          % (esc(e.get("status", "stated")), esc(sp["file"]), esc(sp["quote"])))
        if len(e["points"]) >= 2:
            lx, ly = label_point(lay, e)
            a('<text class="edge-label" x="%.1f" y="%.1f" text-anchor="middle">%s</text>'
              % (lx, ly, esc(short)))
        a('</g>')
    a('</g>')

    # ---------- nodes
    a('<g id="layer-nodes">')
    for n in lay["nodes"]:
        color = G.TYPES.get(n["type"], G.TYPES["other"])[0]
        sp = parse_span(first_span(n))
        dash = ' stroke-dasharray="6 4"' if n.get("status") != "stated" else ""
        a('<g class="node type-%s status-%s" id="node-%s" data-node-id="%s" data-type="%s" '
          'data-compartment="%s" data-status-value="%s">'
          % (n["type"], n.get("status", "stated"), esc(n["id"]), esc(n["id"]), n["type"],
             n["compartment"], n.get("status", "stated")))
        a(shape_svg(n, color, dash))
        cx = n["x"] + n["w"] / 2.0
        font = n["font"]
        lineh = font * 1.24
        sub_f = 10.5
        nlines = len(n["lines"])
        total = nlines * lineh + sub_f * 1.5
        y0 = n["y"] + (n["h"] - total) / 2.0 + font * 0.92
        for i, line in enumerate(n["lines"]):
            a('<text class="node-label" x="%.1f" y="%.1f" text-anchor="middle" '
              'font-size="%d">%s</text>' % (cx, y0 + i * lineh, font, esc(line)))
        sub = "%s · %s%s" % (L.type_short(n["type"]), L.comp_short(n["compartment"]),
                             " *" if n.get("compartment_inferred") else "")
        a('<text class="node-sub" x="%.1f" y="%.1f" text-anchor="middle" font-size="%.1f">%s</text>'
          % (cx, y0 + nlines * lineh + 3, sub_f, esc(sub)))
        a('<title>%s</title>' % esc(n["label"]))
        a('<desc>type=%s; compartment=%s; status=%s; source=%s; quote=%s</desc>'
          % (n["type"], n["compartment"], n.get("status", "stated"),
             esc(sp["file"] or "case.json"), esc(sp["quote"])))
        a('</g>')
    a('</g>')

    # ---------- legend
    a(render_legend(lay))
    a(render_notes(lay))
    a('</svg>')
    return "\n".join(o)


def shape_svg(n, color, dash):
    x, y, w, h = n["x"], n["y"], n["w"], n["h"]
    fill = color
    op = "0.16" if n["type"] != "cell" else "0.42"
    sh = n.get("shape", "rounded")
    common = ('fill="%s" fill-opacity="%s" stroke="%s" stroke-width="2.2"%s'
              % (fill, op, color, dash))
    if sh == "rect":
        return '<rect x="%.1f" y="%.1f" width="%.1f" height="%.1f" rx="4" %s/>' % (x, y, w, h, common)
    if sh == "ellipse":
        return ('<ellipse cx="%.1f" cy="%.1f" rx="%.1f" ry="%.1f" %s/>'
                % (x + w / 2.0, y + h / 2.0, w / 2.0, h / 2.0, common))
    if sh == "hexagon":
        cx, cy, rx, ry = x + w / 2.0, y + h / 2.0, w / 2.0, h / 2.0
        pts = [(cx - rx, cy), (cx - rx * 0.72, cy - ry), (cx + rx * 0.72, cy - ry),
               (cx + rx, cy), (cx + rx * 0.72, cy + ry), (cx - rx * 0.72, cy + ry)]
        return '<polygon points="%s" %s/>' % (" ".join("%.1f,%.1f" % p for p in pts), common)
    if sh == "diamond":
        cx, cy, rx, ry = x + w / 2.0, y + h / 2.0, w / 2.0, h / 2.0
        pts = [(cx, cy - ry), (cx + rx * 0.9, cy), (cx, cy + ry), (cx - rx * 0.9, cy)]
        return '<polygon points="%s" %s/>' % (" ".join("%.1f,%.1f" % p for p in pts), common)
    return '<rect x="%.1f" y="%.1f" width="%.1f" height="%.1f" rx="16" %s/>' % (x, y, w, h, common)


def label_point(lay, e):
    boxes = [L.box(n) for n in lay["nodes"]
             if n["id"] not in (e["source"], e["target"])]
    for frac in (0.5, 0.42, 0.58, 0.34, 0.66):
        p = L.point_at(e["points"], frac)
        if not any(b["x"] <= p[0] <= b["x"] + b["w"] and b["y"] <= p[1] <= b["y"] + b["h"]
                   for b in boxes):
            return p
    return e["label_xy"]


def render_legend(lay):
    lg = lay["legend"]
    o = ['<g id="layer-legend">',
         '<rect x="%d" y="%d" width="%d" height="%d" rx="10" fill="#F9FAFB" stroke="#E5E7EB"/>'
         % (lg["x"], lg["y"], lg["w"], lg["h"]),
         '<text class="legend-title" x="%d" y="%d">图例 / Legend</text>'
         % (lg["x"] + 16, lg["y"] + 22)]
    kinds = lay["used_kinds"] or G.KIND_ORDER[:4]
    colw = (lg["w"] - 32) / 2.0
    for i, k in enumerate(kinds[:6]):
        col, row = i % 2, i // 2
        x = lg["x"] + 18 + col * colw
        y = lg["y"] + 50 + row * 28
        color, mk, dash, legend, short = G.KINDS[k]
        dash_attr = ' stroke-dasharray="%s"' % dash if dash else ""
        start = ' marker-start="url(#mk-%s)"' % mk if mk == "circle" else ""
        o.append('<path d="M %.1f %.1f L %.1f %.1f" stroke="%s" stroke-width="2.4" '
                 'marker-end="url(#mk-%s)"%s%s fill="none"/>'
                 % (x, y, x + 74, y, color, mk, start, dash_attr))
        o.append('<text class="legend-text" x="%.1f" y="%.1f">%s</text>'
                 % (x + 86, y + 4, esc(legend)))
    ty = lg["y"] + 142
    o.append('<text class="legend-title" x="%d" y="%d">实体类型 / Entity types</text>'
             % (lg["x"] + 16, ty))
    types = lay["used_types"] or ["protein"]
    tcolw = (lg["w"] - 32) / 3.0
    for i, t in enumerate(types[:12]):
        col, row = i % 3, i // 3
        x = lg["x"] + 18 + col * tcolw
        y = ty + 18 + row * 22
        color = G.TYPES[t][0]
        o.append('<rect x="%.1f" y="%.1f" width="20" height="13" rx="3" fill="%s" '
                 'fill-opacity="0.20" stroke="%s" stroke-width="1.6"/>'
                 % (x, y - 10, color, color))
        o.append('<text class="legend-text" x="%.1f" y="%.1f">%s</text>'
                 % (x + 27, y, esc(G.TYPES[t][2])))
    sy = lg["y"] + lg["h"] - 12
    o.append('<text class="note-text" x="%d" y="%d">虚线轮廓/虚线箭头 = 推断或证据不足（inferred / unverified）；'
             '未解决关系不绘制，列于 result.json。</text>' % (lg["x"] + 16, sy))
    o.append('</g>')
    return "\n".join(o)


def render_notes(lay):
    nt = lay["notes"]
    o = ['<g id="layer-notes">',
         '<rect x="%d" y="%d" width="%d" height="%d" rx="10" fill="#FFFFFF" stroke="#E5E7EB"/>'
         % (nt["x"], nt["y"], nt["w"], nt["h"])]
    y = nt["y"] + 22
    for text, head in nt["lines"]:
        cls = "note-head" if head else "note-text"
        for i, line in enumerate(G.wrap(text, nt["w"] - 32, 11)):
            o.append('<text class="%s" x="%d" y="%d">%s</text>'
                     % (cls, nt["x"] + 16, y, esc(line)))
            y += 17 if head else 15
            if y > nt["y"] + nt["h"] - 8:
                break
        if y > nt["y"] + nt["h"] - 8:
            break
    o.append('</g>')
    return "\n".join(o)


# ------------------------------------------------------------------ artifacts
def build_element_map(spec, lay):
    rows = []
    for n in spec["nodes"]:
        sp = parse_span(first_span(n))
        rows.append({
            "element": "node:" + n["id"], "label": n["label"], "kind": "entity",
            "type": n["type"], "compartment": n["compartment"],
            "source": ("%s#%s" % (sp["file"], sp["section"])) if sp["file"] else "",
            "file": sp["file"], "page": sp["page"], "section": sp["section"],
            "quote": sp["quote"], "quote_verified": sp["verified"],
            "data_ref": n.get("data_ref", ""), "status": n.get("status", "stated"),
        })
    for e in spec["edges"]:
        sp = parse_span(first_span(e))
        rows.append({
            "element": "edge:" + e["id"], "label": "%s → %s" % (e["source"], e["target"]),
            "kind": "edge", "type": e["kind"], "compartment": "cross",
            "source": ("%s#%s" % (sp["file"], sp["section"])) if sp["file"] else "",
            "file": sp["file"], "page": sp["page"], "section": sp["section"],
            "quote": sp["quote"], "quote_verified": sp["verified"],
            "data_ref": e.get("data_ref", ""), "status": e.get("status", "stated"),
        })
    for b in lay["bands"]:
        rows.append({
            "element": "compartment:" + b["id"], "label": b["label"],
            "kind": "compartment", "type": "framework", "compartment": b["id"],
            "source": "framework", "file": "", "page": None, "section": "compartments",
            "quote": "compartment band fixed to %s; entities assigned by explicit "
                     "localization or name/type heuristic" % b["id"],
            "quote_verified": True, "data_ref": "compartments[%d]" % G.CANON_ORDER[b["id"]],
            "status": "stated",
        })
    rows.append({
        "element": "legend", "label": "图例 / Legend", "kind": "decoration",
        "type": "legend", "compartment": "none", "source": "figure",
        "file": "", "page": None, "section": "legend",
        "quote": "arrow-head shapes and colours are generated from the same KG vocabulary",
        "quote_verified": True, "data_ref": "used_kinds", "status": "stated",
    })
    return {"schema": "element_map/1.0", "rows": rows,
            "counts": {"entities": len(spec["nodes"]), "edges": len(spec["edges"]),
                       "compartments": len(lay["bands"]), "rows": len(rows)}}


def build_graph(spec, lay):
    pos = {n["id"]: {"label": n["label"], "type": n["type"],
                     "compartment": n["compartment"], "x": n["x"], "y": n["y"],
                     "w": n["w"], "h": n["h"], "status": n.get("status", "stated")}
           for n in lay["nodes"]}
    return {
        "schema": "mechanism-graph/1.0", "case_id": spec.get("case_id"),
        "compartments": [b["id"] for b in lay["bands"]],
        "nodes": pos,
        "edges": [{"id": e["id"], "source": e["source"], "target": e["target"],
                   "kind": e["kind"], "status": e.get("status", "stated"),
                   "route": e.get("route", "")} for e in lay["edges"]],
        "conflicts": spec.get("conflicts", []),
        "isolated_entities": spec.get("isolated_entities", []),
        "unresolved_edges": spec.get("unresolved_edges", []),
    }


def build():
    work = os.environ.get("MECH_WORK", "/app/work")
    out = os.environ.get("MECH_OUT", "/app/output")
    os.makedirs(out, exist_ok=True)
    spec = json.load(open(os.path.join(work, "spec.json"), encoding="utf-8"))
    lay = json.load(open(os.path.join(work, "layout.json"), encoding="utf-8"))
    title = os.environ.get("MECH_TITLE") or "生物机制图与通路图 / Mechanism & pathway diagram"
    caption = os.environ.get("MECH_CAPTION") or ""
    svg = render(title, spec, lay, caption)
    open(os.path.join(out, "figure.svg"), "w", encoding="utf-8").write(svg)
    emap = build_element_map(spec, lay)
    json.dump(emap, open(os.path.join(out, "element_map.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    graph = build_graph(spec, lay)
    json.dump(graph, open(os.path.join(work, "graph.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    print("render: figure.svg %d bytes, %d texts, %d nodes, %d edges, element_map=%d rows"
          % (len(svg.encode("utf-8")), svg.count("<text"), len(spec["nodes"]),
             len(spec["edges"]), len(emap["rows"])))
    return 0


if __name__ == "__main__":
    sys.exit(build())
