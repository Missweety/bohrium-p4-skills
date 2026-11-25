"""route_svg.py - 装置/技术路线规格 -> 分层可编辑 SVG + route_graph.json + element_map（仅标准库）。

图层：background / apparatus_panel / connectors / parts / stage_panel / stages /
      legend / units / scale / notes / title
每个部件、连线、阶段都是带 id 的 <g>，<desc> 写入 source 与 data_ref。
"""
import json
import os

import routelib as r
from routelib import KINDS, TYPES, anchor, bx, ct, esc, fit, legend_box, legend_items, tw, wrap


def text(s, x, y, px, color, weight="normal", anchor_="middle", halo=False):
    extra = ' stroke="#FFFFFF" stroke-width="3" paint-order="stroke"' if halo else ""
    return ('<text x="%.1f" y="%.1f" font-family="Arial Unicode MS, PingFang SC, Noto Sans CJK SC, DejaVu Sans, sans-serif" '
            'font-size="%.1f" font-weight="%s" fill="%s" text-anchor="%s"%s>%s</text>'
            % (x, y, px, weight, color, anchor_, extra, esc(s)))


def shape_path(p, shape, stroke, fill, dash):
    x, y, w, h = bx(p)
    st = 'fill="%s" stroke="%s" stroke-width="2"%s' % (fill, stroke, dash)
    if shape in ("circle", "ellipse"):
        return '<ellipse cx="%.1f" cy="%.1f" rx="%.1f" ry="%.1f" %s/>' % (x + w / 2, y + h / 2, w / 2, h / 2, st)
    if shape == "diamond":
        pts = "%.1f,%.1f %.1f,%.1f %.1f,%.1f %.1f,%.1f" % (x + w / 2, y, x + w, y + h / 2, x + w / 2, y + h, x, y + h / 2)
        return '<polygon points="%s" %s/>' % (pts, st)
    if shape == "triangle":
        pts = "%.1f,%.1f %.1f,%.1f %.1f,%.1f" % (x + w / 2, y, x + w, y + h, x, y + h)
        return '<polygon points="%s" %s/>' % (pts, st)
    if shape == "waste":
        q = w * 0.16
        pts = "%.1f,%.1f %.1f,%.1f %.1f,%.1f %.1f,%.1f" % (
            x, y, x + w, y, x + w - q, y + h, x + q, y + h)
        return '<polygon points="%s" %s/>' % (pts, st)
    rx = 8 if shape in ("rounded", "instrument", "column") else 2
    out = '<rect x="%.1f" y="%.1f" width="%.1f" height="%.1f" rx="%d" %s/>' % (x, y, w, h, rx, st)
    if shape == "column":
        for k in range(1, 4):
            yy = y + h * k / 4.0
            out += '<line x1="%.1f" y1="%.1f" x2="%.1f" y2="%.1f" stroke="%s" stroke-width="0.8" opacity="0.45"/>' % (
                x + 4, yy, x + w - 4, yy, stroke)
    if shape == "instrument":
        out += '<rect x="%.1f" y="%.1f" width="%.1f" height="%.1f" rx="2" fill="none" stroke="%s" stroke-width="1"/>' % (
            x + 5, y + 5, w - 10, h * 0.28, stroke)
    return out


def part_body(p, color, muted, dpi):
    x, y, w, h = bx(p)
    pt, lines, sub = r.part_layout(p, dpi)
    px = pt * dpi / 72.0
    lh = px * 1.2
    cy = y + h / 2 - (len(lines) * lh + len(sub) * lh * 0.78) / 2 + px * 0.85
    out = []
    for ln in lines:
        out.append(text(ln, x + w / 2, cy, px, color, "600"))
        cy += lh
    for ln in sub:
        out.append(text(ln, x + w / 2, cy, px * 0.72, muted))
        cy += lh * 0.78
    return "".join(out)


def conn_d(a, b):
    x1, y1 = anchor(a, *ct(b))
    x2, y2 = anchor(b, *ct(a))
    dx, dy = x2 - x1, y2 - y1
    if abs(dx) >= abs(dy):
        mx = (x1 + x2) / 2
        return "M%.1f,%.1f L%.1f,%.1f L%.1f,%.1f L%.1f,%.1f" % (x1, y1, mx, y1, mx, y2, x2, y2), mx, (y1 + y2) / 2
    my = (y1 + y2) / 2
    return "M%.1f,%.1f L%.1f,%.1f L%.1f,%.1f L%.1f,%.1f" % (x1, y1, x1, my, x2, my, x2, y2), (x1 + x2) / 2, my


def render(spec, out, name, report):
    fig = spec["figure"]
    W, H, dpi = int(fig["width_px"]), int(fig["height_px"]), int(fig.get("dpi", 300))
    pal = r.NEUTRAL
    parts = {p["id"]: p for p in spec.get("parts", [])}
    stages = {s["id"]: s for s in spec.get("stages", [])}

    L = ['<?xml version="1.0" encoding="UTF-8"?>',
         '<svg xmlns="http://www.w3.org/2000/svg" width="%d" height="%d" viewBox="0 0 %d %d" role="img" '
         'aria-labelledby="fig_title fig_desc">' % (W, H, W, H),
         '<title id="fig_title">%s</title>' % esc(fig.get("title") or "Apparatus and technical route"),
         '<desc id="fig_desc">%s</desc>' % esc(fig.get("description") or
                                               "Editable apparatus and technical-route figure: parts, connectors and staged milestones."),
         '<defs>']
    for kind, (color, dash, label) in KINDS.items():
        L.append('<marker id="mk_%s" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="8" markerHeight="8" '
                 'orient="auto-start-reverse"><path d="M0,0 L10,5 L0,10 z" fill="%s"/></marker>'
                 % (kind, color))
    L.append('</defs>')
    L.append('<g id="layer_background"><rect width="%d" height="%d" fill="%s"/></g>'
             % (W, H, fig.get("background", "#FFFFFF")))

    # apparatus panel
    app = fig.get("apparatus_bbox") or {"x": 16.0, "y": 72.0, "w": W - 32.0, "h": 660.0}
    L.append('<g id="layer_apparatus_panel"><title>装置区</title>'
             '<rect x="%.1f" y="%.1f" width="%.1f" height="%.1f" rx="6" fill="%s" stroke="%s"/>%s</g>'
             % (app["x"], app["y"], app["w"], app["h"], pal["panel_fill"], pal["stroke"],
                text("装置与流向 / Apparatus & flow", app["x"] + 16, app["y"] + 28,
                     9 * dpi / 72.0, pal["muted"], "700", "start")))

    # connectors
    L.append('<g id="layer_connectors">')
    for c in spec.get("connections", []):
        a, b = parts.get(c.get("from")), parts.get(c.get("to"))
        if not a or not b:
            continue
        color, kdash, _ = KINDS.get(c.get("kind"), KINDS["flow"])
        d, lx, ly = conn_d(a, b)
        dash = kdash
        if c.get("status") == "inferred":
            dash = (dash + " 6 4").strip()
        dash_attr = ' stroke-dasharray="%s"' % dash if dash else ""
        start = ' marker-start="url(#mk_%s)"' % c.get("kind") if c.get("direction") == "bidirectional" else ""
        L.append('<g id="%s" data-kind="%s" data-status="%s"><title>%s to %s</title>'
                 '<desc>source: %s; data_ref: %s; medium: %s; rate: %s; direction: %s</desc>'
                 '<path d="%s" fill="none" stroke="%s" stroke-width="2.4"%s%s marker-end="url(#mk_%s)"/></g>'
                 % (c["id"], c.get("kind"), c.get("status", "stated"),
                    esc(a.get("label", "")), esc(b.get("label", "")),
                    esc(c.get("evidence", "MISSING")), esc(c.get("data_ref", "")),
                    esc(c.get("medium", "")), esc(c.get("rate", "")), esc(c.get("direction", "forward")),
                    d, color, dash_attr, start, c.get("kind")))
        label = c.get("label") or ""
        if not label and (c.get("medium") or c.get("rate")):
            label = " ".join(x for x in (c.get("medium"), c.get("rate")) if x)
        if label and tw(label, 7.5 * dpi / 72.0) <= 160:
            L.append(text(label, lx, ly - 8, 7.5 * dpi / 72.0, color, "600", "middle", True))
    L.append('</g>')

    # parts
    L.append('<g id="layer_parts">')
    for p in spec.get("parts", []):
        ptype = p.get("type", "other")
        color = TYPES.get(ptype, TYPES["other"])[0]
        shape = p.get("shape") or (TYPES.get(ptype) or ("", "rounded"))[1]
        dash = ' stroke-dasharray="7 5"' if p.get("status") == "inferred" else ""
        L.append('<g id="%s" data-type="%s" data-status="%s">'
                 '<title>%s</title><desc>source: %s; data_ref: %s; role: %s</desc>%s%s</g>'
                 % (p["id"], ptype, p.get("status", "stated"), esc(p.get("label", "")),
                    esc(p.get("evidence", "MISSING")), esc(p.get("data_ref", "")),
                    esc(r.TYPE_LABELS.get(ptype, ptype)),
                    shape_path(p, shape, color, "#FFFFFF", dash),
                    part_body(p, pal["text"], pal["muted"], dpi)))
    L.append('</g>')

    # type color chips are part of each group; add a compact type key in notes instead

    # stage panel
    sp = fig.get("stage_bbox") or {"x": 16.0, "y": 740.0, "w": W - 32.0, "h": 250.0}
    L.append('<g id="layer_stage_panel"><title>技术路线区</title>'
             '<rect x="%.1f" y="%.1f" width="%.1f" height="%.1f" rx="6" fill="%s" stroke="%s"/>%s</g>'
             % (sp["x"], sp["y"], sp["w"], sp["h"], pal["panel_fill"], pal["stroke"],
                text("技术路线与里程碑 / Technical route & milestones", sp["x"] + 16, sp["y"] + 28,
                     9 * dpi / 72.0, pal["muted"], "700", "start")))

    # component type key: shapes and colours carry the part type, so the figure
    # must say what they mean (the old note only explained the milestone diamond)
    type_items = r.type_key_items(spec)
    if type_items:
        ps = 6.4 * dpi / 72.0
        kx = sp["x"] + 520.0
        L.append('<g id="layer_type_key"><title>部件类型图例 / Component type key</title>')
        L.append(text("类型 / Type:", kx, sp["y"] + 24.0, ps, pal["muted"], "700", "start"))
        x, y = kx + 66.0, sp["y"] + 24.0
        row = 0
        for it in type_items:
            need = 20.0 + tw(it["label"], ps) + 10.0
            if x + need > W - 14:
                row += 1
                if row > 1:
                    L.append(text("…", x, y, ps, pal["muted"], "normal", "start"))
                    break
                x, y = kx + 66.0, y + 13.0
            L.append(shape_path({"x": x, "y": y - 10, "w": 12, "h": 11}, it["shape"],
                                it["color"], "#FFFFFF", ""))
            L.append(text(it["label"], x + 16, y, ps, pal["text"], "normal", "start"))
            x += need
        L.append('</g>')

    L.append('<g id="layer_stages">')
    by_order = {int(s.get("order", 0)): s for s in spec.get("stages", [])}
    for s in spec.get("stages", []):
        x, y, w, h = bx(s)
        order = int(s.get("order", 0))
        L.append('<g id="%s" data-order="%d" data-milestone="%s">'
                 '<title>%s</title><desc>source: %s; data_ref: %s; objective: %s; outputs: %s</desc>'
                 '<rect x="%.1f" y="%.1f" width="%.1f" height="%.1f" rx="6" fill="#FFFFFF" stroke="%s" stroke-width="1.6"/>'
                 % (s["id"], order, "1" if s.get("milestone") else "0",
                    esc("Phase %d: %s" % (order, s.get("label", ""))),
                    esc(s.get("evidence", "MISSING")), esc(s.get("evidence", "spec.stages")),
                    esc(s.get("objective", "")), esc(", ".join(s.get("outputs") or [])),
                    x, y, w, h, "#0072B2"))
        # 阶段卡四行结构：编号+标题 / objective / 产出 / 里程碑，互不重叠
        lay = r.stage_layout(s, dpi)
        px_t, px_b = lay["px_title"], lay["px_body"]
        L.append('<circle cx="%.1f" cy="%.1f" r="13" fill="#0072B2"/>%s'
                 % (x + 23, y + 23, text(str(order), x + 23, y + 32, 7.5 * dpi / 72.0, "#FFFFFF", "700")))
        ty = y + lay["title_y"]
        for ln in lay["title_lines"]:
            L.append(text(ln, x + 44, ty, px_t, pal["text"], "700", "start"))
            ty += px_t * 0.95
        oy = y + lay["objective_y"]
        for ln in lay["objective_lines"]:
            L.append(text(ln, x + 14, oy, px_b, pal["text"], "normal", "start"))
            oy += px_b * 1.05
        if s.get("outputs"):
            L.append(text(fit("→ " + " / ".join(s.get("outputs")), w - 28, px_b * 0.85),
                          x + 14, y + lay["output_y"], px_b * 0.85, "#0072B2", "600", "start"))
        if s.get("milestone"):
            L.append(text(fit("◆ " + str(s["milestone"]), w - 28, px_b * 0.8),
                          x + 14, y + lay["milestone_y"], px_b * 0.8, "#009E73", "600", "start"))
        L.append('</g>')
    # dependencies
    for s in spec.get("stages", []):
        for dep in s.get("depends_on") or []:
            prev = by_order.get(int(dep))
            if not prev:
                continue
            x1, y1 = bx(prev)[0] + bx(prev)[2], bx(prev)[1] + 26
            x2, y2 = bx(s)[0], bx(s)[1] + 26
            L.append('<g id="dep_%s_%s" data-kind="dependency"><title>dependency</title>'
                     '<desc>source: spec.stages; data_ref: depends_on</desc>'
                     '<path d="M%.1f,%.1f L%.1f,%.1f L%.1f,%.1f L%.1f,%.1f" fill="none" stroke="#6B7280" '
                     'stroke-width="1.2" stroke-dasharray="4 3" marker-end="url(#mk_signal)"/></g>'
                     % (s["id"], dep, x1, y1, (x1 + x2) / 2, y1, (x1 + x2) / 2, y2, x2 - 2, y2))
    L.append('</g>')

    # legend
    items = legend_items(spec)
    lx, ly, lw, lh = legend_box(spec, items, W, H)
    L.append('<g id="layer_legend"><title>图例 / Legend</title>'
             '<rect x="%.1f" y="%.1f" width="%.1f" height="%.1f" rx="4" fill="#FFFFFF" stroke="%s"/>'
             % (lx, ly, lw, lh, pal["stroke"]))
    L.append(text("图例 / Legend", lx + 10, ly + 20, 7.5 * dpi / 72.0, pal["muted"], "700", "start"))
    for i, it in enumerate(items):
        kind = it.get("kind", "flow")
        color, kdash, _ = KINDS.get(kind, KINDS["flow"])
        yy = ly + 56 + 38 * i
        dash = kdash
        if it.get("status") == "inferred":
            dash = (dash + " 6 4").strip()
        dash_attr = ' stroke-dasharray="%s"' % dash if dash else ""
        L.append('<g id="%s"><title>%s</title><path d="M%.1f,%.1f L%.1f,%.1f" fill="none" stroke="%s" '
                 'stroke-width="2.4"%s marker-end="url(#mk_%s)"/>%s</g>'
                 % (it.get("id", "lg%d" % i), esc(it.get("text", "")), lx + 10, yy - 4, lx + 54, yy - 4,
                    color, dash_attr, kind,
                    text(it.get("text", ""), lx + 62, yy, 7.5 * dpi / 72.0, pal["text"], "normal", "start")))
    L.append('</g>')

    # units
    units = spec.get("units") or {}
    if isinstance(units, dict) and units:
        unit_text = "单位 / Units: " + "; ".join("%s=%s" % (k, v) for k, v in units.items())
    else:
        unit_text = "单位 / Units: 定性（材料未给定量单位）"
    ulines = wrap(unit_text, W - 690 - 24, 7.0 * dpi / 72.0)[:2]
    L.append('<g id="layer_units"><title>单位</title>%s</g>'
             % "".join(text(ln, 690, H - 42 + i * 26, 7.0 * dpi / 72.0, pal["muted"],
                            "normal", "start") for i, ln in enumerate(ulines)))

    # scale
    sb = spec.get("scale_bar") or {}
    label = str(sb.get("label", ""))
    try:
        length = float(sb.get("length_px", 0) or 0)
    except (TypeError, ValueError):
        length = 0
    L.append('<g id="layer_scale"><title>比例尺 / Scale</title>')
    if length > 0:
        sx, sy = W - 34 - length, H - 64
        L.append('<line x1="%.1f" y1="%.1f" x2="%.1f" y2="%.1f" stroke="%s" stroke-width="3"/>'
                 '<line x1="%.1f" y1="%.1f" x2="%.1f" y2="%.1f" stroke="%s" stroke-width="2"/>'
                 '<line x1="%.1f" y1="%.1f" x2="%.1f" y2="%.1f" stroke="%s" stroke-width="2"/>'
                 % (sx, sy, sx + length, sy, pal["text"], sx, sy - 6, sx, sy + 6, pal["text"],
                    sx + length, sy - 6, sx + length, sy + 6, pal["text"]))
        L.append(text(label, sx + length / 2, sy - 12, 8 * dpi / 72.0, pal["muted"]))
    else:
        L.append(text(label or "not to scale / 非等比", W - 34, H - 62, 8 * dpi / 72.0, pal["muted"], "normal", "end"))
    L.append('</g>')

    # notes + caption
    L.append('<g id="layer_notes">')
    notes = list(spec.get("notes") or [])
    if not notes:
        notes = [{"id": "note_key",
                  "text": "实线=材料明确；虚线=推断；箭头=流向；形状与颜色=部件类型（见技术路线区标题行）；◆=里程碑。"}]
    y0 = H - 250
    for i, nt in enumerate(notes):
        lines = wrap(nt.get("text", ""), 650, 7.5 * dpi / 72.0)
        L.append('<g id="%s"><title>%s</title>%s</g>'
                 % (nt.get("id", "note%d" % i), esc(nt.get("text", "")),
                    "".join(text(ln, 690, y0 + i * 52 + j * 32, 7.5 * dpi / 72.0,
                                 pal["muted"], "normal", "start") for j, ln in enumerate(lines))))
    caption = spec.get("caption") or ""
    if caption:
        lines = wrap(caption, 620, 7.0 * dpi / 72.0)
        if len(lines) > 5:
            lines = lines[:5]
            lines[-1] = lines[-1].rstrip() + "…"
        for j, ln in enumerate(lines):
            L.append(text(ln, 690, H - 210 + j * 28, 7.0 * dpi / 72.0, pal["muted"], "normal", "start"))
    L.append('</g>')

    L.append('<g id="layer_title"><title>%s</title>%s</g>'
             % (esc(fig.get("title", "")),
                text(fit(fig.get("title", ""), W - 68, 10 * dpi / 72.0), 34, 46,
                     10 * dpi / 72.0, pal["text"], "700", "start")))
    L.append('</svg>')

    os.makedirs(out, exist_ok=True)
    path = os.path.join(out, name + ".svg")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(L))

    graph = {
        "figure_type": "apparatus_route", "title": fig.get("title", ""),
        "parts": [{"id": p["id"], "label": p.get("label", ""), "type": p.get("type", "other"),
                   "status": p.get("status", "stated"), "evidence": p.get("evidence", ""),
                   "quote": p.get("quote", ""),
                   "data_ref": p.get("data_ref", ""), "sub": p.get("sub", "")}
                  for p in spec.get("parts", [])],
        "connections": [{"id": c["id"], "from": c.get("from"), "to": c.get("to"),
                         "kind": c.get("kind"), "direction": c.get("direction", "forward"),
                         "label": c.get("label", ""), "medium": c.get("medium", ""),
                         "rate": c.get("rate", ""), "status": c.get("status", "stated"),
                         "evidence": c.get("evidence", ""), "quote": c.get("quote", ""),
                         "data_ref": c.get("data_ref", "")}
                        for c in spec.get("connections", [])],
        "stages": [{"id": s["id"], "order": s.get("order"), "label": s.get("label", ""),
                    "objective": s.get("objective", ""), "methods": s.get("methods") or [],
                    "inputs": s.get("inputs") or [], "outputs": s.get("outputs") or [],
                    "depends_on": s.get("depends_on") or [], "milestone": s.get("milestone", ""),
                    "status": s.get("status", "stated"), "evidence": s.get("evidence", ""),
                    "quote": s.get("quote", "")}
                   for s in spec.get("stages", [])],
        "units": spec.get("units") or {}, "scale_bar": spec.get("scale_bar") or {},
        "expected": spec.get("expected") or {},
        "legend": items,
    }
    with open(os.path.join(out, name + "_graph.json"), "w", encoding="utf-8") as fh:
        json.dump(graph, fh, ensure_ascii=False, indent=1)

    emap = [{"element": p["id"], "label": p.get("label", ""), "type": "part",
             "subtype": p.get("type", ""), "source": p.get("evidence", ""),
             "locator": p.get("evidence", ""), "quote": p.get("quote", ""),
             "data_ref": p.get("data_ref") or p.get("evidence", ""),
             "status": p.get("status", "stated")} for p in spec.get("parts", [])]
    emap += [{"element": c["id"], "label": "%s -> %s" % (c.get("from"), c.get("to")),
              "type": "connection", "subtype": c.get("kind"),
              "source": c.get("evidence", ""), "locator": c.get("evidence", ""),
              "quote": c.get("quote", ""),
              "data_ref": c.get("data_ref") or c.get("evidence", ""),
              "status": c.get("status", "stated")} for c in spec.get("connections", [])]
    emap += [{"element": s["id"], "label": "Phase %s: %s" % (s.get("order"), s.get("label", "")),
              "type": "stage", "subtype": "milestone" if s.get("milestone") else "phase",
              "source": s.get("evidence", ""), "locator": s.get("evidence", ""),
              "quote": s.get("quote", ""),
              "data_ref": s.get("evidence", "") or "spec.stages",
              "status": s.get("status", "stated")} for s in spec.get("stages", [])]
    emap += [{"element": it.get("id", ""), "label": it.get("text", ""), "type": "legend",
              "source": "generated:legend-auto", "locator": "derived from connection kinds",
              "quote": "", "data_ref": "", "status": "generated"}
             for it in items]
    emap += [{"element": "units", "label": unit_text, "type": "units",
              "source": "generated:units-note", "locator": "spec.units",
              "quote": "", "data_ref": "spec.units", "status": "generated"},
             {"element": "scale", "label": label, "type": "scale",
              "source": "generated:scale-bar", "locator": "spec.scale_bar",
              "quote": "", "data_ref": "spec.scale_bar", "status": "generated"}]
    with open(os.path.join(out, "element_map.json"), "w", encoding="utf-8") as fh:
        json.dump(emap, fh, ensure_ascii=False, indent=1)

    report.update({"svg": name + ".svg", "graph": name + "_graph.json",
                   "canvas": {"width_px": W, "height_px": H, "dpi": dpi},
                   "stats": {"parts": len(parts), "connections": len(spec.get("connections", [])),
                             "stages": len(stages), "legend": len(items), "elements": len(emap)}})
    with open(os.path.join(out, "geometry.json"), "w", encoding="utf-8") as fh:
        json.dump(report, fh, ensure_ascii=False, indent=1)
    print("svg=%s parts=%d connections=%d stages=%d errors=%d warnings=%d"
          % (path, len(parts), len(spec.get("connections", [])), len(stages),
             len(report.get("errors", [])), len(report.get("warnings", []))))
    return 0
