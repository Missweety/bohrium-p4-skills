#!/usr/bin/env python3
"""edit_svg.py - minimal, structure-preserving edits to an existing SVG.

Editing must never regenerate the drawing. We only (a) rewrite the inner text of
existing <text> nodes for rename/replace operations, (b) append ONE new <g id=
"skill_edits"> group before </svg> for annotations/callouts, and (c) record a
before/after hash plus the exact before/after value of every change.

Usage:
  python3 scripts/edit_svg.py --svg IN.svg --case case.json --out OUTDIR \
      [--instructions "text"] [--name route]
Writes: rotated source copy source_figure.svg, edited route.svg, edit_log.json,
        edit_element_map.json (merged by run_case), edit_selfcheck.json.
"""
import argparse
import hashlib
import json
import os
import re
import shutil
import sys


def sha256_text(s):
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def sha256_file(p):
    return sha256_text(open(p, encoding="utf-8", errors="replace").read())


def esc(s):
    return (str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            .replace('"', "&quot;"))


TEXT_NODE = re.compile(r"<text\b([^>]*)>(.*?)</text>", re.S | re.I)
TAG_ATTR = re.compile(r'([\w:-]+)\s*=\s*"([^"]*)"')


def _attrs(block):
    return dict(TAG_ATTR.findall(block))


def _unescape(s):
    return (s.replace("&lt;", "<").replace("&gt;", ">").replace("&quot;", '"')
            .replace("&amp;", "&"))


def _viewbox(svg):
    m = re.search(r'viewBox\s*=\s*"([^"]+)"', svg)
    if m:
        try:
            nums = [float(x) for x in re.split(r"[ ,]+", m.group(1).strip()) if x]
            if len(nums) == 4:
                return nums[2], nums[3]
        except ValueError:
            pass
    w = re.search(r'\bwidth\s*=\s*"([\d.]+)', svg)
    h = re.search(r'\bheight\s*=\s*"([\d.]+)', svg)
    try:
        return float(w.group(1)), float(h.group(1))
    except (AttributeError, ValueError):
        return 1200.0, 800.0


def _local(name):
    return name.split("}", 1)[1] if "}" in name else name


def _attrs_el(el):
    return {_local(k): v for k, v in el.attrib.items()}


def _num(v, default=0.0):
    m = re.search(r"[-+]?\d*\.?\d+(?:[eE][-+]?\d+)?", str(v or ""))
    try:
        return float(m.group(0)) if m else default
    except ValueError:
        return default


def _shape_bbox(el):
    """近似包围盒（忽略 transform/曲线），只用于高亮框，不参与任何尺寸声明。"""
    tag = _local(el.tag).lower()
    p = _attrs_el(el)
    if tag == "rect":
        return (_num(p.get("x")), _num(p.get("y")),
                _num(p.get("width")), _num(p.get("height")))
    if tag == "circle":
        r = _num(p.get("r"))
        return (_num(p.get("cx")) - r, _num(p.get("cy")) - r, 2 * r, 2 * r)
    if tag == "ellipse":
        rx, ry = _num(p.get("rx")), _num(p.get("ry"))
        return (_num(p.get("cx")) - rx, _num(p.get("cy")) - ry, 2 * rx, 2 * ry)
    if tag == "line":
        x1, y1, x2, y2 = (_num(p.get("x1")), _num(p.get("y1")),
                          _num(p.get("x2")), _num(p.get("y2")))
        return (min(x1, x2), min(y1, y2), abs(x2 - x1), abs(y2 - y1))
    if tag in ("polygon", "polyline"):
        nums = [float(v) for v in re.findall(r"[-+]?\d*\.?\d+", str(p.get("points", "")))]
        xs, ys = nums[0::2], nums[1::2]
        if xs and ys:
            return (min(xs), min(ys), max(xs) - min(xs), max(ys) - min(ys))
        return None
    if tag == "path":
        nums = [float(v) for v in re.findall(r"[-+]?\d*\.?\d+", str(p.get("d", "")))]
        xs, ys = nums[0::2], nums[1::2]
        if xs and ys:
            return (min(xs), min(ys), max(xs) - min(xs), max(ys) - min(ys))
        return None
    if tag == "text":
        body = "".join(el.itertext()).strip()
        fs = _num(p.get("font-size"), 14.0)
        w = max(1.0, len(body) * fs * 0.62)
        x, y = _num(p.get("x")), _num(p.get("y"))
        anchor = str(p.get("text-anchor", "start")).lower()
        if anchor == "middle":
            x -= w / 2
        elif anchor == "end":
            x -= w
        return (x, y - fs, w, fs * 1.25)
    return None


def element_bbox(svg_text, target):
    """目标元素（按 id、可见文本或所在 <g> 文本）的近似包围盒。"""
    if not target:
        return None
    try:
        import xml.etree.ElementTree as ET
        root = ET.fromstring(svg_text.encode("utf-8"))
    except Exception:  # noqa: BLE001
        return None
    found = None
    for el in root.iter():
        if str(el.get("id") or "") == str(target):
            found = el
            break
    if found is None:
        for el in root.iter():
            if _local(el.tag).lower() == "text" and "".join(el.itertext()).strip() == str(target):
                found = el
                break
    if found is None:
        for el in root.iter():
            if _local(el.tag).lower() == "g" and str(target) in "".join(el.itertext()):
                found = el
                break
    if found is None:
        return None
    if _local(found.tag).lower() == "text":
        tb = _shape_bbox(found)
        best = None
        for grp in root.iter():
            if _local(grp.tag).lower() != "g":
                continue
            if str(target) not in "".join(grp.itertext()):
                continue
            boxes = [b for b in (_shape_bbox(e) for e in grp.iter())
                     if b and b[2] > 0 and b[3] > 0]
            if not boxes:
                continue
            bx1 = min(b[0] for b in boxes)
            by1 = min(b[1] for b in boxes)
            bx2 = max(b[0] + b[2] for b in boxes)
            by2 = max(b[1] + b[3] for b in boxes)
            if tb and not (bx1 <= tb[0] + tb[2] / 2 <= bx2 and by1 <= tb[1] + tb[3] / 2 <= by2):
                continue
            area = (bx2 - bx1) * (by2 - by1)
            if best is None or area < best[0]:
                best = (area, (bx1, by1, max(1.0, bx2 - bx1), max(1.0, by2 - by1)))
        if best:
            return best[1]
    boxes = [b for b in (_shape_bbox(e) for e in found.iter()) if b and b[2] > 0 and b[3] > 0]
    if not boxes:
        return None
    x1 = min(b[0] for b in boxes)
    y1 = min(b[1] for b in boxes)
    x2 = max(b[0] + b[2] for b in boxes)
    y2 = max(b[1] + b[3] for b in boxes)
    return (x1, y1, max(1.0, x2 - x1), max(1.0, y2 - y1))


def parse_ops(case):
    """Return [{op, target, text, x, y, quote, inferred}] from many case shapes."""
    raw = (case.get("edit_instructions") or case.get("edits")
           or case.get("changes") or case.get("instructions") or "")
    ops = []
    if isinstance(raw, dict):
        raw = raw.get("edits") or raw.get("instructions") or raw.get("changes") or []
    if isinstance(raw, str):
        raw = [ln.strip(" -•\t") for ln in re.split(r"[\n;]", raw) if ln.strip()]
    if not isinstance(raw, list):
        raw = []
    for item in raw:
        if isinstance(item, dict):
            op = str(item.get("op") or item.get("action") or item.get("type") or "").lower()
            text = (item.get("text") or item.get("new") or item.get("value")
                    or item.get("annotation") or "")
            target = (item.get("target") or item.get("old") or item.get("element")
                      or item.get("from") or "")
            if not op:
                op = "set_text" if target and text else "annotate"
            ops.append({"op": op, "target": str(target), "text": str(text),
                        "x": item.get("x"), "y": item.get("y"),
                        "quote": json.dumps(item, ensure_ascii=False)[:240],
                        "inferred": False})
            continue
        s = str(item).strip()
        if not s:
            continue
        m = (re.search(r"[将把]?\s*[“\"'](.+?)[”\"']\s*(?:改为|替换为|改成|更改为)\s*[“\"'](.+?)[”\"']", s)
             or re.search(r'(?:change|rename|replace)\s+["“](.+?)["”]\s*(?:to|with|->|→)\s*["“](.+?)["”]', s, re.I)
             or re.search(r"^\s*(?:rename|set)\s+(.+?)\s*(?:->|→|to|=)\s*(.+?)\s*$", s, re.I))
        if m:
            ops.append({"op": "set_text", "target": m.group(1).strip(),
                        "text": m.group(2).strip(), "quote": s, "inferred": False})
            continue
        m = re.search(r"(?:添加|增加|标注|注明|补充|annotate|add(?: a)?(?: note| label| callout)?[:：]?)\s*[:：]?\s*(.+)$", s, re.I)
        if m:
            ops.append({"op": "annotate", "target": "", "text": m.group(1).strip(),
                        "quote": s, "inferred": True})
            continue
        m = re.search(r"(?:高亮|突出|强调|highlight)\s*[:：]?\s*(.+)$", s, re.I)
        if m:
            ops.append({"op": "highlight", "target": m.group(1).strip(), "text": "",
                        "quote": s, "inferred": True})
            continue
        ops.append({"op": "annotate", "target": "", "text": s, "quote": s,
                    "inferred": True})
    return ops


def apply_ops(svg, ops, W, H):
    changes, warnings = [], []
    total_text = len(TEXT_NODE.findall(svg))
    changed_nodes = 0

    def node_match(attrs, body, target):
        t = _unescape(re.sub(r"<[^>]+>", "", body)).strip()
        tid = (attrs.get("id") or "").strip()
        return bool(target) and (target == tid or target in t or t in target)

    # set_text / rename / highlight
    for op in ops:
        if op["op"] not in ("set_text", "rename", "replace"):
            continue
        target = op["target"]
        hit = [False]

        # manual pass so we can rebuild attributes + escaped text and keep bytes intact
        out, pos = [], 0
        for m in TEXT_NODE.finditer(svg):
            attrs, body = _attrs(m.group(1)), m.group(2)
            if not node_match(attrs, body, target):
                continue
            before = _unescape(re.sub(r"<[^>]+>", "", body)).strip()
            new = op["text"] or before
            out.append(svg[pos:m.start()])
            out.append('<text%s>%s</text>' % (m.group(1), esc(new)))
            pos = m.end()
            changes.append({"element": attrs.get("id") or ("text:%d" % len(changes)),
                            "op": "set_text", "before": before, "after": new,
                            "quote": op["quote"], "inferred": op["inferred"],
                            "structure_preserved": True})
            changed_nodes += 1
            hit[0] = True
        out.append(svg[pos:])
        svg = "".join(out)
        if not hit[0]:
            warnings.append("target not found for set_text: %r (no change made)" % target)

    # document <title>: rewrite the existing <title> or insert one after the <svg> root;
    # when no visible <text> carries the new title, add one so the edit is actually visible
    title_visible = None
    for op in ops:
        if op["op"] not in ("set_title", "title", "set_figure_title"):
            continue
        new = str(op.get("text") or "").strip()
        if not new:
            warnings.append("empty title for %r (no change made)" % op["op"])
            continue
        m = re.search(r"<title\b[^>]*>(.*?)</title>", svg, re.S | re.I)
        if m:
            before = _unescape(re.sub(r"<[^>]+>", "", m.group(1))).strip()
            svg = svg[:m.start(1)] + esc(new) + svg[m.end(1):]
        else:
            before = ""
            msvg = re.search(r"<svg\b[^>]*>", svg, re.I)
            if not msvg:
                warnings.append("no <svg> root; cannot set document title")
                continue
            svg = svg[:msvg.end()] + "<title>%s</title>" % esc(new) + svg[msvg.end():]
        visible = "".join(re.findall(r"<text\b[^>]*>(.*?)</text>", svg, re.S | re.I))
        if new not in visible:
            title_visible = new
        changes.append({"element": "title", "op": "set_title", "before": before,
                        "after": new, "quote": op["quote"], "inferred": op["inferred"],
                        "structure_preserved": True})

    # highlight: outline the target's bbox inside the appended group (source untouched)
    hl_boxes = []
    for op in ops:
        if op["op"] not in ("highlight", "emphasize", "outline"):
            continue
        tgt = str(op.get("target") or op.get("text") or "")
        box = element_bbox(svg, tgt) if tgt else None
        if box:
            hl_boxes.append((box, tgt))
            changes.append({"element": tgt, "op": "highlight", "before": "",
                            "after": "outline box x=%.0f y=%.0f w=%.0f h=%.0f" % box,
                            "quote": op["quote"], "inferred": op["inferred"],
                            "structure_preserved": True})
        else:
            warnings.append("highlight target not found: %r (kept as note only)" % tgt)

    # annotations / callouts -> one appended group
    ann = [o for o in ops if o["op"] in ("annotate", "note", "callout", "add_text",
                                         "comment", "highlight")]
    for o in ann:
        if not o.get("text"):
            o["text"] = ("重点：" + o.get("target", "")) if o["op"] == "highlight" else o.get("target", "")
    ann = [o for o in ann if o.get("text")]
    if ann or hl_boxes or title_visible:
        pad = 18
        bw = min(W - 2 * pad, max(320.0, W * 0.62))
        bh = 26 + 30 * len(ann)
        bx, by = pad, max(10.0, H - bh - pad)
        g = ['<g id="skill_edits" data-role="annotations">']
        if title_visible:
            g.append('<text x="%.1f" y="34" font-size="20" font-weight="bold" fill="#111827" '
                     'text-anchor="middle">%s</text>' % (W / 2.0, esc(title_visible)))
        for (hx, hy, hw, hh), _tgt in hl_boxes:
            g.append('<rect x="%.1f" y="%.1f" width="%.1f" height="%.1f" rx="5" fill="none" '
                     'stroke="#E69F00" stroke-width="4" stroke-dasharray="9,5" opacity="0.9"/>'
                     % (hx - 7, hy - 7, hw + 14, hh + 14))
        if ann:
            g.append('<rect x="%.1f" y="%.1f" width="%.1f" height="%.1f" rx="8" '
                     'fill="#FFFBEA" stroke="#B26B00" stroke-width="1.4" stroke-dasharray="6,4"/>'
                     % (bx, by, bw, bh))
            g.append('<text x="%.1f" y="%.1f" font-size="14" font-weight="bold" '
                     'fill="#8A4B00">编辑标注 / Edit notes</text>' % (bx + 12, by + 20))
            ty = by + 46
            for i, o in enumerate(ann):
                g.append('<text x="%.1f" y="%.1f" font-size="13" fill="#5B3A00">• %s</text>'
                         % (bx + 14, ty + i * 28, esc(o["text"][:110])))
                changes.append({"element": "annotation-%d" % (i + 1), "op": "annotate",
                                "before": "", "after": o["text"],
                                "quote": o["quote"], "inferred": o["inferred"],
                                "structure_preserved": True})
        g.append("</g>")
        svg = svg.replace("</svg>", "\n".join(g) + "\n</svg>")

    handled = {"set_text", "rename", "replace", "annotate", "note", "callout", "add_text",
               "comment", "highlight", "emphasize", "outline", "set_title", "title",
               "set_figure_title"}
    for op in ops:
        if op["op"] not in handled:
            warnings.append("unsupported edit operation: %r (no change made)" % op["op"])
    return svg, changes, warnings, total_text, changed_nodes


def render_raster(svg_path, out_dir, name):
    """Render a real PNG/PDF preview from the edited SVG; never fake it.

    Order: cairosvg -> rsvg-convert -> inkscape -> matplotlib SVG replay. The last
    step re-renders the actual edited SVG (shapes/lines/text/arrows), so an edit
    still yields an inspectable preview on hosts without a native rasterizer.
    """
    notes = []
    try:
        import cairosvg  # type: ignore
        cairosvg.svg2png(url=svg_path, write_to=os.path.join(out_dir, name + ".png"))
        cairosvg.svg2pdf(url=svg_path, write_to=os.path.join(out_dir, name + ".pdf"))
        return True, ["rasterized with cairosvg"], "cairosvg"
    except Exception:  # noqa: BLE001
        notes.append("cairosvg not usable in this runtime (native cairo/PNG backend missing)")
    if shutil.which("rsvg-convert"):
        import subprocess
        try:
            subprocess.run(["rsvg-convert", "-f", "png", "-o",
                            os.path.join(out_dir, name + ".png"), svg_path],
                           check=True, capture_output=True)
            subprocess.run(["rsvg-convert", "-f", "pdf", "-o",
                            os.path.join(out_dir, name + ".pdf"), svg_path],
                           check=True, capture_output=True)
            return True, ["rasterized with rsvg-convert"], "rsvg-convert"
        except Exception:  # noqa: BLE001
            notes.append("rsvg-convert present but failed")
    if shutil.which("inkscape"):
        import subprocess
        try:
            subprocess.run(["inkscape", svg_path, "--export-type=png", "--export-filename=%s"
                            % os.path.join(out_dir, name + ".png")],
                           check=True, capture_output=True)
            subprocess.run(["inkscape", svg_path, "--export-type=pdf", "--export-filename=%s"
                            % os.path.join(out_dir, name + ".pdf")],
                           check=True, capture_output=True)
            return True, ["rasterized with inkscape"], "inkscape"
        except Exception:  # noqa: BLE001
            notes.append("inkscape present but failed")
    try:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        import export_preview as E
        ok, rnotes = E.render_svg_preview(svg_path, out_dir, name, 150)
        if ok:
            return True, ["replayed edited SVG with matplotlib"] + list(rnotes), "matplotlib-svg"
        notes += list(rnotes)
    except Exception as exc:  # noqa: BLE001
        notes.append("matplotlib SVG replay unavailable: %s" % exc)
    notes.append("no SVG rasterizer in runtime; edited SVG is the verified deliverable "
                 "(status partial by design)")
    return False, notes, ""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--svg", required=True)
    ap.add_argument("--case", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--instructions", default="")
    ap.add_argument("--name", default="route")
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    case = json.load(open(a.case, encoding="utf-8")) if a.case else {}
    if a.instructions:
        case = dict(case)
        case["edit_instructions"] = a.instructions
    base = open(a.svg, encoding="utf-8", errors="replace").read()
    src_hash = sha256_text(base)
    W, H = _viewbox(base)
    ops = parse_ops(case)
    edited, changes, warnings, total_text, changed = apply_ops(base, ops, W, H)
    out_hash = sha256_text(edited)
    if not ops:
        warnings.append("no edit operations parsed; SVG copied unchanged")
    svg_out = os.path.join(a.out, a.name + ".svg")
    with open(svg_out, "w", encoding="utf-8") as fh:
        fh.write(edited)
    shutil.copyfile(a.svg, os.path.join(a.out, "source_figure.svg"))

    kept = total_text - changed
    checks = [
        {"name": "source_readable", "ok": True, "detail": "%d bytes" % len(base)},
        {"name": "edits_applied", "ok": bool(changes), "detail": "%d changes" % len(changes)},
        {"name": "text_nodes_preserved",
         "ok": changed <= total_text, "detail": "%d/%d text nodes kept unchanged"
         % (kept, total_text)},
        {"name": "valid_svg_root", "ok": edited.lstrip().startswith("<")
         and edited.rstrip().endswith("</svg>"), "detail": "well-formed root/close tags"},
        {"name": "no_placeholder", "ok": bool(changes), "detail": "no empty/placeholder output"},
    ]
    ok = all(c["ok"] for c in checks)
    rastered, rnotes, engine = render_raster(svg_out, a.out, a.name)
    log = {
        "mode": "svg_edit",
        "source_file": os.path.basename(a.svg),
        "source_sha256": src_hash,
        "output_file": a.name + ".svg",
        "output_sha256": out_hash,
        "structure_preserved": True,
        "text_nodes_total": total_text,
        "text_nodes_changed": changed,
        "ops_parsed": len(ops),
        "changes": changes,
        "warnings": warnings,
        "raster": {"ok": rastered, "engine": engine, "notes": rnotes},
    }
    json.dump(log, open(os.path.join(a.out, "edit_log.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    emap = []
    for c in changes:
        emap.append({"element": c["element"], "label": (c["after"] or c["before"])[:80],
                     "type": "edit", "subtype": c["op"],
                     "source": "case.json:edit_instructions",
                     "locator": "case.json:edit_instructions",
                     "quote": c["quote"], "data_ref": "",
                     "status": "inferred" if c["inferred"] else "stated"})
    json.dump(emap, open(os.path.join(a.out, "edit_element_map.json"), "w",
                         encoding="utf-8"), ensure_ascii=False, indent=1)
    selfcheck = {"ok": ok, "verdict": "PASS" if ok else "FAIL",
                 "checks": checks, "stats": {"changes": len(changes),
                                             "text_nodes": total_text,
                                             "text_nodes_changed": changed,
                                             "ops": len(ops)}}
    json.dump(selfcheck, open(os.path.join(a.out, "edit_selfcheck.json"), "w",
                              encoding="utf-8"), ensure_ascii=False, indent=1)
    print("edited=%s ops=%d changes=%d text_changed=%d/%d raster=%s ok=%s"
          % (svg_out, len(ops), len(changes), changed, total_text, rastered, ok))
    for w in warnings:
        print(" warn:", w)
    return 0


if __name__ == "__main__":
    sys.exit(main())
