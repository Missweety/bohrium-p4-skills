#!/usr/bin/env python3
"""export.py - SVG -> PNG + PDF with a real fallback chain and quality gates.

Order: cairosvg -> rsvg-convert -> inkscape -> matplotlib re-draw from layout.json.
The matplotlib path re-draws the same geometry (it does not read the SVG), so a
renderer-less host still gets a raster preview instead of a broken promise.

A PNG is accepted only when it is >=800x600, has >1500 unique colours and >1% non-white
pixels; otherwise it is deleted and reported so the caller can mark status=partial.
"""
import json
import os
import re
import shutil
import struct
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import graphlib as G  # noqa: E402


def png_size(path):
    try:
        with open(path, "rb") as fh:
            head = fh.read(24)
        if head[:8] != b"\x89PNG\r\n\x1a\n":
            return None
        return struct.unpack(">II", head[16:24])
    except OSError:
        return None


def png_quality(path):
    info = {"path": path, "bytes": os.path.getsize(path) if os.path.exists(path) else 0}
    size = png_size(path) if info["bytes"] else None
    info["dims"] = size
    if not size:
        info["ok"] = False
        info["reason"] = "not a PNG or missing"
        return info
    try:
        from PIL import Image  # type: ignore
        im = Image.open(path).convert("RGB")
        small = im.resize((min(im.width, 800), min(im.height, 800)))
        colours = small.getcolors(maxcolors=1 << 24) or []
        uniq = len(colours)
        total = sum(c for c, _ in colours) or 1
        nonwhite = sum(c for c, px in colours if not (px[0] > 248 and px[1] > 248 and px[2] > 248))
        info["unique_colours"] = uniq
        info["nonwhite_frac"] = round(nonwhite / float(total), 4)
        info["ok"] = (size[0] >= 800 and size[1] >= 600 and uniq > 1500
                      and info["nonwhite_frac"] > 0.01)
        if not info["ok"]:
            info["reason"] = "low content (dims=%s, colours=%d, nonwhite=%.3f)" % (
                size, uniq, info["nonwhite_frac"])
    except ImportError:
        info["ok"] = size[0] >= 800 and size[1] >= 600
        info["reason"] = "PIL absent; dimension-only check"
    return info


def svg_dims(path):
    import re
    raw = open(path, encoding="utf-8", errors="replace").read(4000)
    m = re.search(r'width="(\d+(?:\.\d+)?)"\s+height="(\d+(?:\.\d+)?)"', raw)
    if m:
        return int(float(m.group(1))), int(float(m.group(2)))
    return 1600, 1200


def via_cairosvg(svg, png, pdf):
    import cairosvg  # type: ignore
    w, h = svg_dims(svg)
    cairosvg.svg2png(url=svg, write_to=png, output_width=w, output_height=h)
    cairosvg.svg2pdf(url=svg, write_to=pdf)
    return "cairosvg"


def via_cli(svg, png, pdf):
    if shutil.which("rsvg-convert"):
        subprocess.run(["rsvg-convert", "-f", "png", "-o", png, svg], check=True)
        subprocess.run(["rsvg-convert", "-f", "pdf", "-o", pdf, svg], check=True)
        return "rsvg-convert"
    if shutil.which("inkscape"):
        subprocess.run(["inkscape", svg, "--export-type=png", "--export-filename=" + png], check=True)
        subprocess.run(["inkscape", svg, "--export-type=pdf", "--export-filename=" + pdf], check=True)
        return "inkscape"
    raise RuntimeError("no rsvg-convert/inkscape")


def via_matplotlib(lay, png, pdf, title=None):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt  # noqa: E402
    from matplotlib.patches import Rectangle, FancyBboxPatch, Ellipse, Polygon, Circle
    from matplotlib import font_manager  # noqa: E402

    t0 = title or lay.get("title") or "生物机制图与通路图 / Mechanism & pathway diagram"
    t1 = "%d entities · %d relations · evidence mapped in element_map.json" % (
        len(lay["nodes"]), len(lay["edges"]))
    fam = None
    for cand in ("PingFang SC", "Noto Sans CJK SC", "Hiragino Sans GB",
                 "Microsoft YaHei", "Source Han Sans SC", "WenQuanYi Zen Hei"):
        try:
            if any(cand.lower() in f.name.lower() for f in font_manager.fontManager.ttflist):
                fam = cand
                break
        except Exception:  # noqa: BLE001
            pass
    rc = {"font.family": fam or "DejaVu Sans", "axes.unicode_minus": False}
    matplotlib.rcParams.update(rc)

    W, H = lay["width"], lay["height"]
    scale = 100.0
    fig = plt.figure(figsize=(W / scale, H / scale), dpi=scale)
    ax = fig.add_axes([0, 0, 1, 1])
    ax.set_xlim(0, W)
    ax.set_ylim(H, 0)
    ax.axis("off")
    ax.add_patch(Rectangle((0, 0), W, H, facecolor="#FFFFFF", edgecolor="none"))
    ax.add_patch(Rectangle((0, 0), W, 4, facecolor="#0072B2", edgecolor="none"))
    ax.text(46, 52, t0, fontsize=25 * 72 / scale, va="center", fontweight="bold",
            color="#111827")
    ax.text(46, 78, t1, fontsize=13 * 72 / scale, va="center", color="#6B7280")

    for b in lay["bands"]:
        ax.add_patch(FancyBboxPatch((40, b["y"]), W - 80, b["h"],
                                    boxstyle="round,pad=0,rounding_size=10",
                                    facecolor="#F7F9FC", edgecolor="#E2E8F0", linewidth=1.2))
        ax.text(58, b["y"] + 22, "%s · %d" % (b["label"], b["count"]),
                fontsize=13 * 72 / scale, va="center", color="#374151", fontweight="bold")
        if not b["count"]:
            ax.text(W - 330, b["y"] + 30, "（未提取到实体 / none extracted）",
                    fontsize=11 * 72 / scale, va="center", color="#9CA3AF")

    if not lay.get("nodes") and not lay.get("edges"):
        for rt in lay.get("raw_texts", []):
            ha = {"middle": "center", "end": "right"}.get(rt.get("anchor"), "left")
            ax.text(rt["x"], rt["y"], rt["text"], fontsize=rt["size"] * 72 / scale,
                    ha=ha, va="baseline", color="#111827")

    for e in lay["edges"]:
        color, mk, dash, _, short = G.KINDS[e["kind"]]
        pts = e["points"]
        xs = [p[0] for p in pts]
        ys = [p[1] for p in pts]
        ls = "--" if (dash or e.get("status") != "stated") else "-"
        lw = 2.2 * 72 / scale
        ax.plot(xs, ys, color=color, linewidth=lw, linestyle=ls, solid_capstyle="round")
        ex, ey = pts[-1]
        px, py = pts[-2]
        dx, dy = ex - px, ey - py
        import math
        n = math.hypot(dx, dy) or 1
        ux, uy = dx / n, dy / n
        if mk in ("arrow", "open", "chevron"):
            size = 11
            ax.add_patch(Polygon([[ex, ey], [ex - ux * size - uy * 5, ey - uy * size + ux * 5],
                                  [ex - ux * size + uy * 5, ey - uy * size - ux * 5]],
                                 closed=(mk == "arrow"), facecolor=color if mk == "arrow" else "none",
                                 edgecolor=color, linewidth=lw))
        elif mk == "bar":
            ax.plot([ex - uy * 7, ex + uy * 7], [ey + ux * 7, ey - ux * 7],
                    color=color, linewidth=3.0 * 72 / scale)
        elif mk == "circle":
            ax.add_patch(Circle((ex - ux * 5, ey - uy * 5), 4.2, facecolor="#FFFFFF",
                                edgecolor=color, linewidth=1.8))
            sx0, sy0 = pts[0]
            sx1, sy1 = pts[1]
            sn = math.hypot(sx1 - sx0, sy1 - sy0) or 1
            ax.add_patch(Circle((sx0 - (sx1 - sx0) / sn * 5, sy0 - (sy1 - sy0) / sn * 5),
                                4.2, facecolor="#FFFFFF", edgecolor=color, linewidth=1.8))
        elif mk == "diamond":
            ax.add_patch(Polygon([[ex, ey - 5], [ex + 4, ey], [ex, ey + 5], [ex - 4, ey]],
                                 closed=True, facecolor=color, edgecolor="#FFFFFF"))
        lx, ly = e["label_xy"]
        ax.text(lx, ly - 4, short, fontsize=12 * 72 / scale, ha="center", color="#374151",
                bbox=dict(facecolor="white", edgecolor="none", pad=1.0, alpha=0.9))

    for n in lay["nodes"]:
        color = G.TYPES.get(n["type"], G.TYPES["other"])[0]
        x, y, w, h = n["x"], n["y"], n["w"], n["h"]
        op = 0.16 if n["type"] != "cell" else 0.42
        ls = "--" if n.get("status") != "stated" else "-"
        if n.get("shape") == "ellipse":
            ax.add_patch(Ellipse((x + w / 2, y + h / 2), w, h, facecolor=color, alpha=op,
                                 edgecolor=color, linewidth=2.2, linestyle=ls))
        elif n.get("shape") == "hexagon":
            cx, cy, rx, ry = x + w / 2, y + h / 2, w / 2, h / 2
            pts = [(cx - rx, cy), (cx - rx * .72, cy - ry), (cx + rx * .72, cy - ry),
                   (cx + rx, cy), (cx + rx * .72, cy + ry), (cx - rx * .72, cy + ry)]
            ax.add_patch(Polygon(pts, closed=True, facecolor=color, alpha=op,
                                 edgecolor=color, linewidth=2.2, linestyle=ls))
        else:
            rx = 4 if n.get("shape") == "rect" else 16
            ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0,rounding_size=%d" % rx,
                                        facecolor=color, alpha=op, edgecolor=color,
                                        linewidth=2.2, linestyle=ls))
        font = n["font"] * 72 / scale
        lineh = n["font"] * 1.24
        sub_f = 10.5
        total = len(n["lines"]) * lineh + sub_f * 1.5
        y0 = y + (h - total) / 2 + n["font"] * 0.92
        for i, line in enumerate(n["lines"]):
            ax.text(x + w / 2, y0 - 3 + i * lineh, line, fontsize=font, ha="center",
                    va="center", color="#111827", fontweight="bold")
        sub = "%s · %s%s" % (
            G.TYPES.get(n["type"], G.TYPES["other"])[2].split("/")[0].strip(),
            G.CANON_LABEL.get(n["compartment"], n["compartment"]).split("/")[0].strip(),
            " *" if n.get("compartment_inferred") else "")
        ax.text(x + w / 2, y0 - 3 + len(n["lines"]) * lineh + 3, sub,
                fontsize=sub_f * 72 / scale, ha="center", va="center", color="#4B5563")

    for hl in lay.get("highlights", []):
        ax.add_patch(Rectangle((hl["x"], hl["y"]), hl["w"], hl["h"], facecolor="#FDE725",
                               alpha=0.35, edgecolor=hl.get("color", "#B26B00"),
                               linewidth=1.6, linestyle="--"))

    lg = lay["legend"]
    ax.add_patch(FancyBboxPatch((lg["x"], lg["y"]), lg["w"], lg["h"],
                                boxstyle="round,pad=0,rounding_size=10",
                                facecolor="#F9FAFB", edgecolor="#E5E7EB"))
    ax.text(lg["x"] + 16, lg["y"] + 22, "图例 / Legend", fontsize=13 * 72 / scale,
            va="center", fontweight="bold", color="#111827")
    kinds = lay["used_kinds"] or G.KIND_ORDER[:4]
    colw = (lg["w"] - 32) / 2.0
    for i, k in enumerate(kinds[:6]):
        col, row = i % 2, i // 2
        x = lg["x"] + 18 + col * colw
        y = lg["y"] + 50 + row * 28
        color, mk, dash, legend, _ = G.KINDS[k]
        ax.plot([x, x + 74], [y, y], color=color, linewidth=2.2,
                linestyle="--" if dash else "-")
        if mk == "arrow":
            ax.plot(x + 74, y, marker=">", color=color, markersize=9)
        elif mk == "bar":
            ax.plot([x + 74, x + 74], [y - 6, y + 6], color=color, linewidth=3)
        elif mk == "circle":
            ax.plot(x + 74, y, marker="o", markerfacecolor="white",
                    markeredgecolor=color, markersize=6)
        elif mk == "diamond":
            ax.plot(x + 74, y, marker="D", color=color, markersize=5)
        else:
            ax.plot(x + 74, y, marker=">", markerfacecolor="none",
                    markeredgecolor=color, markersize=7)
        ax.text(x + 86, y, legend, fontsize=11.5 * 72 / scale, va="center", color="#374151")

    ty = lg["y"] + 142
    ax.text(lg["x"] + 16, ty, "实体类型 / Entity types", fontsize=13 * 72 / scale,
            va="center", fontweight="bold", color="#111827")
    types = lay["used_types"] or ["protein"]
    tcolw = (lg["w"] - 32) / 3.0
    for i, t in enumerate(types[:12]):
        col, row = i % 3, i // 3
        x = lg["x"] + 18 + col * tcolw
        y = ty + 20 + row * 22
        color = G.TYPES[t][0]
        ax.add_patch(Rectangle((x, y - 6), 20, 13, facecolor=color, alpha=0.22,
                               edgecolor=color, linewidth=1.4))
        ax.text(x + 27, y, G.TYPES[t][2], fontsize=11.5 * 72 / scale, va="center",
                color="#374151")
    ax.text(lg["x"] + 16, lg["y"] + lg["h"] - 12,
            "虚线轮廓/虚线箭头 = 推断或证据不足（inferred / unverified）；未解决关系不绘制，列于 result.json。",
            fontsize=10 * 72 / scale, va="center", color="#4B5563")

    nt = lay["notes"]
    ax.add_patch(FancyBboxPatch((nt["x"], nt["y"]), nt["w"], nt["h"],
                                boxstyle="round,pad=0,rounding_size=10",
                                facecolor="#FFFFFF", edgecolor="#E5E7EB"))
    yy = nt["y"] + 22
    for text, head in nt["lines"]:
        for line in G.wrap(text, nt["w"] - 32, 11):
            ax.text(nt["x"] + 16, yy, line, fontsize=(12 if head else 10.5) * 72 / scale,
                    va="center", color="#111827" if head else "#4B5563",
                    fontweight="bold" if head else "normal")
            yy += 16
            if yy > nt["y"] + nt["h"] - 8:
                break
        if yy > nt["y"] + nt["h"] - 8:
            break

    fig.savefig(png, dpi=scale)
    fig.savefig(pdf, dpi=scale)
    plt.close(fig)
    return "matplotlib" + ("" if fam else " (no CJK font)")


def _num(v, default=0.0):
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def _parse_path(d):
    pts = []
    for cmd, nums in re.findall(r"([MLQ])\s*([-\d.,\s]+)", d or ""):
        v = [float(x) for x in re.findall(r"-?\d+\.?\d*", nums)]
        if cmd in ("M", "L") and len(v) >= 2:
            pts.append((v[0], v[1]))
        elif cmd == "Q" and len(v) >= 4 and pts:
            p0 = pts[-1]
            c, p1 = (v[0], v[1]), (v[2], v[3])
            for t in (0.33, 0.66):
                x = (1 - t) ** 2 * p0[0] + 2 * (1 - t) * t * c[0] + t * t * p1[0]
                y = (1 - t) ** 2 * p0[1] + 2 * (1 - t) * t * c[1] + t * t * p1[1]
                pts.append((x, y))
            pts.append(p1)
    return pts


def _shape_box(el):
    tag = el.tag.split("}")[-1]
    if tag == "rect":
        x, y = _num(el.get("x")), _num(el.get("y"))
        return x, y, _num(el.get("width")), _num(el.get("height")), "rect"
    if tag == "ellipse":
        cx, cy = _num(el.get("cx")), _num(el.get("cy"))
        rx, ry = _num(el.get("rx")), _num(el.get("ry"))
        return cx - rx, cy - ry, 2 * rx, 2 * ry, "ellipse"
    if tag == "polygon":
        nums = [float(v) for v in re.findall(r"-?\d+\.?\d*", el.get("points", ""))]
        xs, ys = nums[0::2], nums[1::2]
        if xs and ys:
            return min(xs), min(ys), max(xs) - min(xs), max(ys) - min(ys), "polygon"
    return None


def layout_from_svg(path):
    """Recover a drawing plan from an SVG produced by render.py (edit-mode fallback).

    If the file is foreign (no node/edge groups), every <text> is replayed at its own
    coordinates so the raster still shows the edited content instead of a blank frame.
    """
    import xml.etree.ElementTree as ET
    NS = "{http://www.w3.org/2000/svg}"
    root = ET.parse(path).getroot()
    W = _num(root.get("width"), 1600)
    H = _num(root.get("height"), 1200)
    lay = {"width": int(W), "height": int(H), "bands": [], "nodes": [], "edges": [],
           "used_kinds": [], "used_types": [], "raw_texts": [], "highlights": [],
           "title": ""}
    for t in root.iter(NS + "text"):
        if t.get("class") == "title-main":
            lay["title"] = "".join(t.itertext())
            break
    for r in root.iter(NS + "rect"):
        if r.get("class") == "edit-highlight":
            lay["highlights"].append({"x": _num(r.get("x")), "y": _num(r.get("y")),
                                      "w": _num(r.get("width")), "h": _num(r.get("height")),
                                      "color": r.get("stroke") or "#B26B00"})
    lay["legend"] = {"x": 40, "y": H - 306 + 22, "w": 860, "h": 252}
    lay["notes"] = {"x": 930, "y": H - 306 + 22, "w": 630, "h": 252,
                    "lines": [("编辑来源 / Edited source", True),
                              (os.path.basename(path), False),
                              ("geometry copied from the supplied SVG", False)]}

    for g in root.iter(NS + "g"):
        cls = g.get("class") or ""
        if cls == "compartment":
            rect = next((c for c in g if c.tag == NS + "rect"), None)
            if rect is None:
                continue
            txt = next((t for t in g.iter(NS + "text") if t.get("class") == "band-label"), None)
            lbl = txt.text if txt is not None else g.get("data-compartment", "")
            lbl = str(lbl).rsplit(" · ", 1)[0]
            lay["bands"].append({
                "id": g.get("data-compartment", ""),
                "label": lbl,
                "count": int(_num(g.get("data-count"), 0)),
                "y": _num(rect.get("y")), "h": _num(rect.get("height")),
                "cols": 1, "rows": 1,
            })
        elif cls.startswith("node "):
            shape = None
            for c in g:
                shape = _shape_box(c)
                if shape:
                    break
            if not shape:
                continue
            x, y, w, h, kind = shape
            texts = [t for t in g.iter(NS + "text")]
            labels = [t.text or "" for t in texts if t.get("class") == "node-label"]
            sub = next((t.text or "" for t in texts if t.get("class") == "node-sub"), "")
            font = _num(texts[0].get("font-size"), 14) if texts else 14
            lay["nodes"].append({
                "id": g.get("data-node-id") or (g.get("id") or "").replace("node-", ""),
                "label": " ".join(labels) or (texts[0].text if texts else ""),
                "type": g.get("data-type", "other"),
                "compartment": g.get("data-compartment", "cytoplasm"),
                "status": g.get("data-status-value", "stated"),
                "x": x, "y": y, "w": w, "h": h, "shape": kind,
                "lines": labels or [""], "font": font, "truncated": False,
                "compartment_inferred": "*" in (sub or ""),
            })
        elif cls.startswith("edge "):
            p = next((c for c in g.iter(NS + "path")), None)
            pts = _parse_path(p.get("d")) if p is not None else []
            if len(pts) < 2:
                continue
            txt = next((t.text or "" for t in g.iter(NS + "text")
                        if t.get("class") == "edge-label"), "")
            lay["edges"].append({
                "id": g.get("id", "").replace("edge-", ""),
                "source": g.get("data-source", ""), "target": g.get("data-target", ""),
                "kind": g.get("data-kind", "activation"),
                "status": g.get("data-status-value", "stated"),
                "points": pts, "label_xy": pts[len(pts) // 2], "label": txt,
                "d": p.get("d") if p is not None else "",
            })

    for t in root.iter(NS + "text"):
        if not (t.get("class") or "").startswith(("node-", "edge-", "title-", "band-",
                                                  "legend-", "note-")):
            lay["raw_texts"].append({"x": _num(t.get("x")), "y": _num(t.get("y")),
                                     "size": _num(t.get("font-size"), 13),
                                     "anchor": t.get("text-anchor", "start"),
                                     "text": "".join(t.itertext())})
    for k in G.KIND_ORDER:
        if any(e["kind"] == k for e in lay["edges"]):
            lay["used_kinds"].append(k)
    for t in G.TYPES:
        if any(n["type"] == t for n in lay["nodes"]):
            lay["used_types"].append(t)
    return lay


def run(svg, out_dir, work, layout_path=None, title=None):
    os.makedirs(out_dir, exist_ok=True)
    png = os.path.join(out_dir, "figure.png")
    pdf = os.path.join(out_dir, "figure.pdf")
    for p in (png, pdf):
        if os.path.exists(p):
            os.remove(p)
    methods, errors = [], []
    try:
        methods.append(via_cairosvg(svg, png, pdf))
    except Exception as exc:  # noqa: BLE001
        errors.append("cairosvg: %s" % exc)
    if not (os.path.exists(png) and os.path.exists(pdf)):
        try:
            methods.append(via_cli(svg, png, pdf))
        except Exception as exc:  # noqa: BLE001
            errors.append("cli: %s" % exc)
    if not (os.path.exists(png) and os.path.exists(pdf)) and layout_path and \
            os.path.exists(layout_path):
        try:
            lay = json.load(open(layout_path, encoding="utf-8"))
            methods.append(via_matplotlib(lay, png, pdf, title))
        except Exception as exc:  # noqa: BLE001
            errors.append("matplotlib: %s" % exc)
    if not (os.path.exists(png) and os.path.exists(pdf)) and os.path.exists(svg):
        try:
            lay = layout_from_svg(svg)
            methods.append(via_matplotlib(lay, png, pdf, title) + " (from-svg)")
        except Exception as exc:  # noqa: BLE001
            errors.append("matplotlib(from-svg): %s" % exc)

    info = png_quality(png) if os.path.exists(png) else {"ok": False, "reason": "missing",
                                                         "bytes": 0, "dims": None}
    pdf_info = {"path": pdf, "bytes": os.path.getsize(pdf) if os.path.exists(pdf) else 0,
                "ok": False}
    if pdf_info["bytes"] > 1000:
        with open(pdf, "rb") as fh:
            pdf_info["ok"] = fh.read(4) == b"%PDF"
    if not info.get("ok"):
        errors.append("PNG failed quality gate: %s" % info.get("reason"))
    if not pdf_info["ok"]:
        errors.append("PDF missing/invalid")
    return {"methods": methods, "png": info, "pdf": pdf_info,
            "errors": errors, "ok": bool(info.get("ok") and pdf_info["ok"])}


def main():
    work = os.environ.get("MECH_WORK", "/app/work")
    out = os.environ.get("MECH_OUT", "/app/output")
    svg = os.path.join(out, "figure.svg")
    if not os.path.exists(svg):
        print("export: figure.svg missing")
        return 1
    res = run(svg, out, work, os.path.join(work, "layout.json"))
    json.dump(res, open(os.path.join(work, "export.json"), "w", encoding="utf-8"), indent=1)
    print("export: methods=%s png=%s pdf=%s ok=%s"
          % (res["methods"], res["png"].get("dims"), res["pdf"]["bytes"], res["ok"]))
    for e in res["errors"]:
        print("  ", e)
    return 0 if res["ok"] else 2


if __name__ == "__main__":
    sys.exit(main())
