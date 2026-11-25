#!/usr/bin/env python3
"""layout.py - deterministic compartment-band layout with collision-aware routing.

Geometry is computed before drawing so the self-check can assert:
  * every node box lies inside its compartment band and inside the canvas;
  * no two node boxes overlap;
  * no edge polyline cuts through a node it does not connect;
  * long CJK labels are wrapped (never clipped) and stay inside the box.
"""
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import graphlib as G  # noqa: E402

W = 1600
NODE_H = 84
ROW_H = 102
BAND_LABEL = 34
BAND_PAD = 12
TOP = 116
BOTTOM = 306          # legend + notes strip
MIN_H = 1180
FONT = 14
FONT_MIN = 11


def short(label):
    return str(label).split("/")[0].strip()


def type_short(etype):
    lbl = G.TYPES.get(etype, G.TYPES["other"])[2]
    return short(lbl)


def comp_short(comp):
    return short(G.CANON_LABEL.get(comp, comp))


def cols_for(n):
    if n <= 1:
        return 1
    if n == 4:
        return 2
    return min(4, max(2, int(math.ceil(math.sqrt(n)))))


def plan(spec):
    nodes = spec["nodes"]
    by_comp = {c: [] for c, _ in G.COMPARTMENTS}
    for n in nodes:
        by_comp.setdefault(n["compartment"], []).append(n)

    bands = []
    total = TOP + BOTTOM
    for cid, lbl in G.COMPARTMENTS:
        cnt = len(by_comp.get(cid, []))
        if cnt == 0:
            h = 50
            cols, rows = 0, 0
        else:
            cols = cols_for(cnt)
            rows = int(math.ceil(cnt / float(cols)))
            h = BAND_LABEL + rows * ROW_H + BAND_PAD
        bands.append({"id": cid, "label": lbl, "count": cnt, "cols": cols,
                      "rows": rows, "h": h, "y": 0})
        total += h
    H = max(MIN_H, total)
    extra = H - total
    per = extra / float(len(bands))
    y = TOP
    for b in bands:
        b["h"] = int(round(b["h"] + per))
        b["y"] = y
        y += b["h"]

    usable_w = W - 120
    placed = {}
    for b in bands:
        cnt = b["count"]
        if not cnt:
            continue
        cell_w = usable_w / float(b["cols"])
        node_w = min(252, int(cell_w - 28))
        b["node_w"] = node_w
        for i, n in enumerate(by_comp[b["id"]]):
            row, col = divmod(i, b["cols"])
            # balanced last row
            n_in_row = min(b["cols"], cnt - row * b["cols"])
            row_w = n_in_row * cell_w
            x_off = (usable_w - row_w) / 2.0
            x = 60 + x_off + col * cell_w + (cell_w - node_w) / 2.0
            ynode = b["y"] + BAND_LABEL + row * ROW_H + (ROW_H - NODE_H) / 2.0
            box_geom = {"x": round(x, 1), "y": round(ynode, 1), "w": node_w, "h": NODE_H}
            lines, font, trunc = fit_label(n["label"], node_w - 56)
            n2 = dict(n)
            n2.update(box_geom)
            n2["lines"] = lines
            n2["font"] = font
            n2["truncated"] = trunc
            n2["shape"] = G.TYPES.get(n["type"], G.TYPES["other"])[1]
            n2["band"] = b["id"]
            placed[n["id"]] = n2

    # ---- edges
    edges = []
    for e in spec["edges"]:
        s, t = placed.get(e["source"]), placed.get(e["target"])
        if not s or not t:
            continue
        pts, tag = route(s, t, list(placed.values()), W, H)
        d = rounded_path(pts, 14)
        mid = point_at(pts, 0.5)
        e2 = dict(e)
        e2.update({"points": pts, "d": d, "route": tag,
                   "label_xy": mid, "src_box": box(s), "tgt_box": box(t)})
        edges.append(e2)

    used_kinds = []
    for k in G.KIND_ORDER:
        if any(e["kind"] == k for e in spec["edges"]):
            used_kinds.append(k)
    used_types = []
    for t in G.TYPES:
        if any(n["type"] == t for n in nodes):
            used_types.append(t)

    notes = build_notes(spec, H)
    return {"width": W, "height": H, "bands": bands, "nodes": list(placed.values()),
            "edges": edges, "used_kinds": used_kinds, "used_types": used_types,
            "legend": {"x": 40, "y": H - BOTTOM + 22, "w": 860, "h": BOTTOM - 54},
            "notes": notes}


def box(n):
    return {"x": n["x"], "y": n["y"], "w": n["w"], "h": n["h"]}


def fit_label(text, maxw):
    font = FONT
    lines = G.wrap(text, maxw, font)
    if len(lines) > 3:
        font = 12
        lines = G.wrap(text, maxw, font)
    if len(lines) > 3:
        font = FONT_MIN
        lines = G.wrap(text, maxw, font)
    trunc = False
    if len(lines) > 3:
        lines = lines[:3]
        lines[-1] = lines[-1][:max(1, len(lines[-1]) - 1)] + "…"
        trunc = True
    return lines, font, trunc


# ------------------------------------------------------------------ routing
def seg_hits_box(p, q, b, pad=4):
    """True when segment p-q passes through the padded box."""
    x1, y1 = p
    x2, y2 = q
    bx0, by0 = b["x"] - pad, b["y"] - pad
    bx1, by1 = b["x"] + b["w"] + pad, b["y"] + b["h"] + pad
    dx, dy = x2 - x1, y2 - y1
    tmin, tmax = 0.0, 1.0
    for p0, d, lo, hi in ((x1, dx, bx0, bx1), (y1, dy, by0, by1)):
        if abs(d) < 1e-9:
            if p0 < lo or p0 > hi:
                return False
        else:
            t1, t2 = (lo - p0) / d, (hi - p0) / d
            if t1 > t2:
                t1, t2 = t2, t1
            tmin = max(tmin, t1)
            tmax = min(tmax, t2)
            if tmin > tmax:
                return False
    return True


def route(s, t, nodes, W_, H_):
    sc = G.centre(s)
    tc = G.centre(t)
    sx, sy = G.anchor(s, *tc)
    tx, ty = G.anchor(t, *sc)
    band_bottom = s["y"] + s["h"]
    midx, midy = (sx + tx) / 2.0, (sy + ty) / 2.0
    cands = []
    cands.append(("direct", [(sx, sy), (tx, ty)]))
    cands.append(("elbow-h", [(sx, sy), (sx, midy), (tx, midy), (tx, ty)]))
    cands.append(("elbow-v", [(sx, sy), (midx, sy), (midx, ty), (tx, ty)]))
    cands.append(("right", [(sx, sy), (W_ - 46, sy), (W_ - 46, ty), (tx, ty)]))
    cands.append(("left", [(sx, sy), (46, sy), (46, ty), (tx, ty)]))
    cands.append(("below", [(sx, sy), (sx, band_bottom + 26),
                            (tx, band_bottom + 26), (tx, ty)]))
    cands.append(("tbelow", [(sx, sy), (sx, midy + 30), (tx, midy + 30), (tx, ty)]))

    def score(pts):
        hits = 0
        for n in nodes:
            if n["id"] in (s["id"], t["id"]):
                continue
            b = box(n)
            for a, c in zip(pts, pts[1:]):
                if seg_hits_box(a, c, b):
                    hits += 1
        length = sum(abs(a[0] - c[0]) + abs(a[1] - c[1]) for a, c in zip(pts, pts[1:]))
        bends = len(pts)
        return (hits, length + bends * 12)

    cands.sort(key=lambda kv: score(kv[1]))
    pts, tag = cands[0][1], cands[0][0]

    # Re-attach endpoints to the side the final route actually approaches from.
    # Without this, a route that loops left can end on the top edge of the target and
    # share that point with another edge, making the arrowhead ambiguous.
    def attach_point(n, px, py):
        x, y, w, h = G.bx(n)
        m = 12
        c_y = min(max(py, y + m), y + h - m)
        c_x = min(max(px, x + m), x + w - m)
        if px <= x:
            return (x, c_y), "lr"
        if px >= x + w:
            return (x + w, c_y), "lr"
        if py <= y:
            return (c_x, y), "tb"
        if py >= y + h:
            return (c_x, y + h), "tb"
        return G.anchor(n, px, py), "any"

    if len(pts) >= 2:
        start, smode = attach_point(s, pts[1][0], pts[1][1])
        end, tmode = attach_point(t, pts[-2][0], pts[-2][1])
        mid = list(pts[1:-1])
        if mid:
            if smode == "lr":
                mid.insert(0, (start[0], mid[0][1]))
            elif smode == "tb":
                mid.insert(0, (mid[0][0], start[1]))
            if tmode == "lr":
                mid.append((mid[-1][0], end[1]))
            elif tmode == "tb":
                mid.append((end[0], mid[-1][1]))
        out = [start] + mid + [end]
        pts = [out[0]]
        for p in out[1:]:
            if abs(p[0] - pts[-1][0]) > 0.5 or abs(p[1] - pts[-1][1]) > 0.5:
                pts.append(p)
    return pts, tag


def rounded_path(pts, r=14):
    if len(pts) < 2:
        return ""
    d = "M %.1f %.1f" % pts[0]
    for i in range(1, len(pts) - 1):
        p0, p1, p2 = pts[i - 1], pts[i], pts[i + 1]
        v1 = (p1[0] - p0[0], p1[1] - p0[1])
        v2 = (p2[0] - p1[0], p2[1] - p1[1])
        l1, l2 = math.hypot(*v1) or 1, math.hypot(*v2) or 1
        rr = min(r, l1 / 2.0, l2 / 2.0)
        a = (p1[0] - v1[0] / l1 * rr, p1[1] - v1[1] / l1 * rr)
        b = (p1[0] + v2[0] / l2 * rr, p1[1] + v2[1] / l2 * rr)
        d += " L %.1f %.1f Q %.1f %.1f %.1f %.1f" % (a[0], a[1], p1[0], p1[1], b[0], b[1])
    d += " L %.1f %.1f" % pts[-1]
    return d


def point_at(pts, frac):
    if len(pts) == 1:
        return pts[0]
    total = sum(math.hypot(b[0] - a[0], b[1] - a[1]) for a, b in zip(pts, pts[1:]))
    target, acc = total * frac, 0.0
    for a, b in zip(pts, pts[1:]):
        seg = math.hypot(b[0] - a[0], b[1] - a[1])
        if acc + seg >= target and seg > 0:
            t = (target - acc) / seg
            return (round(a[0] + (b[0] - a[0]) * t, 1), round(a[1] + (b[1] - a[1]) * t, 1))
        acc += seg
    return pts[-1]


def build_notes(spec, H):
    mats = spec.get("materials", [])
    mat_lines = []
    for m in mats[:4]:
        name = os.path.basename(m.get("path", "?"))
        if m.get("exists"):
            mat_lines.append("%s (%s chars)" % (name, m.get("chars", 0)))
        else:
            mat_lines.append("%s (missing)" % name)
    if len(mats) > 4:
        mat_lines.append("+%d more" % (len(mats) - 4))
    total_spans = sum(len(n.get("evidence", [])) for n in spec["nodes"]) + \
        sum(len(e.get("evidence", [])) for e in spec["edges"])
    verified = sum(1 for n in spec["nodes"] for s in n.get("evidence", []) if s.get("verified")) + \
        sum(1 for e in spec["edges"] for s in e.get("evidence", []) if s.get("verified"))
    lines = [
        ("证据 / Evidence", True),
        ("materials: " + ("; ".join(mat_lines) if mat_lines else "none"), False),
        ("quotes verified: %d/%d" % (verified, max(total_spans, 1)), False),
        ("isolated entities: %s" % (", ".join(spec.get("isolated_entities", [])) or "none"), False),
        ("conflicts: %d   unresolved relations: %d"
         % (len(spec.get("conflicts", [])), len(spec.get("unresolved_edges", []))), False),
        ("uncertainty notes: %d (full list in result.json)"
         % len(spec.get("uncertainty", [])), False),
    ]
    return {"x": 930, "y": H - BOTTOM + 22, "w": 630, "h": BOTTOM - 54, "lines": lines}


def build():
    import json
    work = os.environ.get("MECH_WORK", "/app/work")
    spec = json.load(open(os.path.join(work, "spec.json"), encoding="utf-8"))
    out = plan(spec)
    json.dump(out, open(os.path.join(work, "layout.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    print("layout: W=%d H=%d nodes=%d edges=%d kinds=%s"
          % (out["width"], out["height"], len(out["nodes"]), len(out["edges"]),
             ",".join(out["used_kinds"])))
    return 0


if __name__ == "__main__":
    sys.exit(build())
