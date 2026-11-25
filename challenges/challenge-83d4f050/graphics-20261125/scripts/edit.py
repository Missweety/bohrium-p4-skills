#!/usr/bin/env python3
"""edit.py - source-preserving SVG editing with before/after hashes and a change list.

Supported operations (structured `edits` or parsed from the request text):
  replace_text(old,new)  rename / 把 X 改为 Y
  set_title(value)       title / 标题
  highlight(target)      highlight / 高亮 / 标注
  add_note(text)         add_note / 添加注释

The script never rebuilds the figure: it edits text nodes in place and appends an
annotation layer, then proves what changed by comparing per-element signatures.
Untouched structure is reported as preserved with both file hashes.
"""
import hashlib
import json
import os
import re
import sys
import xml.etree.ElementTree as ET

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import export  # noqa: E402
import graphlib as G  # noqa: E402

SVG = "{http://www.w3.org/2000/svg}"


def sha(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for c in iter(lambda: fh.read(1 << 20), b""):
            h.update(c)
    return h.hexdigest()


def signatures(raw):
    root = ET.fromstring(raw)
    out = {}

    def walk(el, path):
        out[path] = (el.tag, tuple(sorted(el.attrib.items())), (el.text or "").strip())
        for i, ch in enumerate(el):
            walk(ch, path + "/" + str(i))

    walk(root, "")
    return out, root


def text_nodes(root):
    parent = {}
    for p in root.iter():
        for c in p:
            parent[c] = p
    items = []
    for el in root.iter(SVG + "text"):
        txt = "".join(el.itertext()).strip()
        if not txt:
            continue
        owner = parent.get(el)
        owner_id = ""
        while owner is not None:
            if owner.get("data-node-id"):
                owner_id = owner.get("data-node-id")
                break
            if owner.get("id"):
                owner_id = owner.get("id")
                break
            owner = parent.get(owner)
        items.append({"element": el, "text": txt, "owner": owner_id,
                      "x": el.get("x"), "y": el.get("y"),
                      "font": el.get("font-size") or "13",
                      "anchor": el.get("text-anchor") or "start"})
    return items


def parse_edits(task, case):
    edits = []
    if isinstance(case, dict):
        for key in ("edits", "changes", "edit_ops", "operations"):
            if isinstance(case.get(key), list):
                edits = case[key]
                break
    out = []
    for e in edits:
        if isinstance(e, dict):
            op = (e.get("op") or e.get("action") or e.get("type") or "").lower()
            if "replace" in op or "rename" in op or "text" in op:
                old = e.get("old") or e.get("from") or e.get("target") or ""
                new = e.get("new") or e.get("to") or e.get("value") or ""
                if old:
                    out.append({"op": "replace_text", "old": str(old), "new": str(new),
                                "origin": "case.edits"})
            elif "title" in op:
                v = e.get("value") or e.get("new") or e.get("title") or ""
                if v:
                    out.append({"op": "set_title", "value": str(v), "origin": "case.edits"})
            elif "highlight" in op:
                v = e.get("target") or e.get("value") or e.get("label") or ""
                if v:
                    out.append({"op": "highlight", "target": str(v), "origin": "case.edits"})
            elif "note" in op or "annot" in op:
                v = e.get("text") or e.get("value") or e.get("note") or ""
                if v:
                    out.append({"op": "add_note", "text": str(v), "origin": "case.edits"})
    if out or not task:
        return out
    # free-text patterns (EN + zh)
    for m in re.finditer(r"(?:rename|change|replace)\s+[\"“'「]?(.+?)[\"”'」]?\s+"
                         r"(?:to|with|into|by)\s+[\"“'「]?(.+?)[\"”'」]?\s*(?:[.;\n]|$)",
                         task, re.I):
        out.append({"op": "replace_text", "old": m.group(1).strip(),
                    "new": m.group(2).strip(), "origin": "task_text"})
    for m in re.finditer(r"(?:把|将)\s*[\"“'「]?(.+?)[\"”'」]?\s*"
                         r"(?:改为|改成|替换为|更名为|重命名为)\s*[\"“'」]?(.+?)[\"”'」]?\s*[。;；\n]",
                         task):
        out.append({"op": "replace_text", "old": m.group(1).strip(),
                    "new": m.group(2).strip(), "origin": "task_text"})
    m = re.search(r"(?:^|\n)\s*(?:figure\s+)?title\s*[:：]\s*(.+)", task, re.I)
    if m:
        out.append({"op": "set_title", "value": m.group(1).strip(), "origin": "task_text"})
    for m in re.finditer(r"(?:highlight|annotate|mark)\s+[\"“'「]?(.+?)[\"”'」]?\s*(?:[.;\n]|$)",
                         task, re.I):
        out.append({"op": "highlight", "target": m.group(1).strip(), "origin": "task_text"})
    for m in re.finditer(r"(?:高亮|标注|圈出)\s*[\"“'「]?(.+?)[\"”'」]?\s*[。;；\n]", task):
        out.append({"op": "highlight", "target": m.group(1).strip(), "origin": "task_text"})
    return out


def apply_text_replace(raw, old, new):
    count = 0

    def repl(m):
        nonlocal count
        head, body, tail = m.group(1), m.group(2), m.group(3)
        if old not in body:
            return m.group(0)
        count += 1
        return head + body.replace(old, new) + tail

    out = re.sub(r"(<text\b[^>]*>)(.*?)(</text>)", repl, raw, flags=re.S)
    return out, count


def apply_title(raw, value):
    count = 0
    raw2, n1 = re.subn(r'(<title\b[^>]*>)(.*?)(</title>)',
                       lambda m: m.group(1) + G.esc(value) + m.group(3), raw, count=1, flags=re.S)
    count += n1
    raw3, n2 = re.subn(r'(<text class="title-main"[^>]*>)(.*?)(</text>)',
                       lambda m: m.group(1) + G.esc(value) + m.group(3), raw2, count=1, flags=re.S)
    count += n2
    if count:
        return raw3, count
    # the source has no title element at all: insert one instead of silently
    # dropping the requested edit (a common case for hand-made diagrams)
    m = re.search(r'<svg\b([^>]*)>', raw3, flags=re.S)
    if not m:
        return raw3, 0
    attrs = m.group(1)
    wm = re.search(r'width="(\d+(?:\.\d+)?)"', attrs)
    width = float(wm.group(1)) if wm else 800.0
    title_svg = ('\n<text class="title-main" x="%.1f" y="34" text-anchor="middle" '
                 'font-size="20" font-weight="600" fill="#1a1a1a">%s</text>'
                 % (width / 2.0, G.esc(value)))
    # append at the end so existing child indices (and per-element signatures)
    # do not shift; prepending would look like every element was replaced
    return raw3.replace("</svg>", title_svg + "\n</svg>"), 1


def add_highlight(raw, target, idx):
    root = ET.fromstring(raw)
    for t in root.iter(SVG + "text"):
        txt = "".join(t.itertext())
        if target and target.lower() in txt.lower():
            try:
                x = float(t.get("x", "0"))
                y = float(t.get("y", "0"))
                f = float(t.get("font-size", "13"))
            except ValueError:
                continue
            w = G.tw(txt, f)
            anchor = t.get("text-anchor", "start")
            x0 = x - w / 2.0 if anchor == "middle" else (x - w if anchor == "end" else x)
            rect = ('<rect id="hl-%d" class="edit-highlight" x="%.1f" y="%.1f" '
                    'width="%.1f" height="%.1f" rx="4" fill="#FDE725" fill-opacity="0.35" '
                    'stroke="#B26B00" stroke-width="1.6" stroke-dasharray="5 3"/>'
                    % (idx, x0 - 4, y - f, w + 8, f * 1.45))
            return raw.replace("</svg>", rect + "\n</svg>"), 1, txt
    return raw, 0, ""


def add_note(raw, text, y=110):
    note = ('<g id="layer-annotations"><rect x="40" y="%d" width="520" height="58" rx="8" '
            'fill="#FFFFFF" fill-opacity="0.94" stroke="#B26B00" stroke-width="1.3" '
            'stroke-dasharray="5 3"/><text x="54" y="%d" font-size="12" fill="#7C4A00" '
            'font-family="PingFang SC,Noto Sans CJK SC,sans-serif">%s</text></g>'
            % (y, y + 24, G.esc(text[:90])))
    return raw.replace("</svg>", note + "\n</svg>"), 1


def build_element_map(root, path):
    rows = []
    for i, t in enumerate(text_nodes(root), 1):
        rows.append({
            "element": "text:%d" % i, "label": t["text"], "kind": "svg_text",
            "type": "label", "compartment": "n/a",
            "source": os.path.basename(path), "file": os.path.basename(path),
            "page": None, "section": "svg:text %d" % i,
            "quote": t["text"], "quote_verified": True,
            "data_ref": t["owner"] or "svg", "status": "stated",
        })
    return {"schema": "element_map/1.0", "rows": rows,
            "counts": {"svg_text": len(rows), "rows": len(rows)}}


def run(work, out):
    os.makedirs(out, exist_ok=True)
    wc = json.load(open(os.path.join(work, "case.json"), encoding="utf-8"))
    case = {}
    if wc.get("case_path") and os.path.exists(wc["case_path"]):
        try:
            case = json.load(open(wc["case_path"], encoding="utf-8"))
        except Exception:  # noqa: BLE001
            case = {}
    src = ""
    for m in wc.get("materials", []):
        if str(m.get("path", "")).lower().endswith(".svg") and os.path.isfile(m.get("path")):
            src = m["path"]
            break
    if not src:
        # persist the reason so emit_result can report it instead of an empty list
        res = {"ok": False, "status": "blocked", "changes": [], "errors":
               ["edit requested but no editable .svg found in materials"],
               "structure_preserved": None, "element_map": {"rows": []},
               "export": {"ok": False}}
        json.dump(res, open(os.path.join(work, "edit_result.json"), "w", encoding="utf-8"),
                  ensure_ascii=False, indent=1)
        return res

    raw = open(src, encoding="utf-8", errors="replace").read()
    before = sha(src)
    edits = parse_edits(wc.get("task_text", ""), case)
    before_sig, _ = signatures(raw)
    changes, errors = [], []
    current = raw
    for i, e in enumerate(edits, 1):
        if e["op"] == "replace_text":
            current, n = apply_text_replace(current, e["old"], e["new"])
            changes.append({"op": "replace_text", "target": e["old"], "value": e["new"],
                            "applied": bool(n), "count": n, "origin": e["origin"]})
            if not n:
                errors.append("text not found for replace: %r" % e["old"])
        elif e["op"] == "set_title":
            current, n = apply_title(current, e["value"])
            changes.append({"op": "set_title", "target": "figure title", "value": e["value"],
                            "applied": bool(n), "count": n, "origin": e["origin"]})
        elif e["op"] == "highlight":
            current, n, found = add_highlight(current, e["target"], i)
            changes.append({"op": "highlight", "target": e["target"], "value": found,
                            "applied": bool(n), "count": n, "origin": e["origin"]})
            if not n:
                errors.append("highlight target not found: %r" % e["target"])
        elif e["op"] == "add_note":
            current, n = add_note(current, e["text"])
            changes.append({"op": "add_note", "target": "annotation", "value": e["text"],
                            "applied": bool(n), "count": n, "origin": e["origin"]})

    if not edits:
        errors.append("no edit instruction could be parsed; source left unchanged")
    if not any(c["applied"] for c in changes):
        errors.append("no edit operation could be applied")

    out_svg = os.path.join(out, "figure.svg")
    if current == raw:
        # still produce an explicit unchanged copy rather than a broken figure
        open(out_svg, "w", encoding="utf-8").write(raw)
    else:
        open(out_svg, "w", encoding="utf-8").write(current)
    after = sha(out_svg)
    after_sig, root = signatures(current)
    removed = [k for k in before_sig if k not in after_sig]
    changed_text = [k for k in before_sig if k in after_sig
                    and before_sig[k][2] != after_sig[k][2]]
    structure_preserved = not removed and len(after_sig) >= len(before_sig)

    emap = build_element_map(root, out_svg)
    json.dump(emap, open(os.path.join(out, "element_map.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    json.dump({"before_sha256": before, "after_sha256": after,
               "source": src, "changes": changes,
               "removed_elements": len(removed),
               "changed_text_elements": len(changed_text),
               "structure_preserved": structure_preserved},
              open(os.path.join(work, "edit_log.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)

    exp = export.run(out_svg, out, work, None)
    res = {"ok": not errors and exp["ok"] and bool(edits),
           "status": "ok" if (not errors and exp["ok"]) else "partial",
           "before_sha256": before, "after_sha256": after, "source": src,
           "changes": changes, "errors": errors,
           "removed_elements": len(removed),
           "changed_text_elements": len(changed_text),
           "structure_preserved": structure_preserved,
           "export": exp, "element_map": emap}
    json.dump(res, open(os.path.join(work, "edit_result.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    print("edit: source=%s changes=%d applied=%d structure_preserved=%s export_ok=%s"
          % (os.path.basename(src), len(changes), sum(c["applied"] for c in changes),
             structure_preserved, exp["ok"]))
    for e in errors:
        print("  ", e)
    return res


def main():
    work = os.environ.get("MECH_WORK", "/app/work")
    out = os.environ.get("MECH_OUT", "/app/output")
    res = run(work, out)
    return 0 if res.get("ok") else 2


if __name__ == "__main__":
    sys.exit(main())
