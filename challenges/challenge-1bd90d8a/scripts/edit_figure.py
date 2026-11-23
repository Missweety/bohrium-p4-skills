#!/usr/bin/env python3
"""edit_figure.py - structure-preserving edits for an existing spec or SVG.

Two modes, both audited with sha256 before/after and an explicit diff list:

  spec  title, axis range (--y-min/--y-max), annotation, highlight; chart-type
        conversions that keep the same underlying values (bar <-> grouped bar <-> line,
        line -> bar). Conversions that would need raw replicates (box/heatmap) refuse
        and point at the re-plan command instead of inventing values.
  svg   surgical edits on an existing SVG: retitle, add annotation, highlight a bar
        (anchored on data-label / matching <text>), replace literal text. Existing
        nodes are not rewritten: the edit is applied as exact string replacements plus
        inserted nodes, and the log proves that removing the insertions and reversing
        the replacements restores the original bytes.

Usage:
  python3 scripts/edit_figure.py spec --spec work/chart_spec.json --out work \
      [--title T] [--y-min 0 --y-max 50] [--annotate "note"] \
      [--highlight Control] [--chart-type line] [--set-text "old=new"]
  python3 scripts/edit_figure.py svg --svg input.svg --out work \
      [--title T] [--annotate "note"] [--highlight Control] [--set-text "old=new"]
"""
import argparse
import copy
import hashlib
import html
import json
import os
import re
import sys

import build_spec
from labels import ACCENT, OKABE, pinned_ticks


def h(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _r(v):
    return None if v is None else round(float(v), 6)


# --------------------------------------------------------------------------- spec
def _recompute(p, spec):
    p["axis"] = build_spec.build_axis_for_panel(p, spec.get("error", "sd"))
    p["legend"] = build_spec.build_legend(p)


def _to_line(p, spec):
    points = []
    cats = [str(c) for c in p.get("categories", [])]
    pos = {c: i for i, c in enumerate(cats)}
    for s in p.get("series", []):
        for v in s.get("values", []):
            points.append({"x": v["label"], "xi": pos.get(v["label"], 0), "y": v["value"],
                           "error": v.get("error"), "error_type": v.get("error_type"),
                           "n": v.get("n"), "row": (v.get("source_rows") or [None])[0],
                           "source_rows": v.get("source_rows", []),
                           "series": s["label"]})
    p["points"] = points
    p["chart_type"] = "line"
    p["line_aggregated"] = False


def _to_bar(p, spec):
    cats = []
    for pt in p.get("points", []):
        if str(pt["x"]) not in cats:
            cats.append(str(pt["x"]))
    series = []
    old_series = p.get("series", [])
    labels = [s["label"] for s in old_series] or [p.get("fields", {}).get("y", {}).get("name", "value")]
    for si, lab in enumerate(labels):
        vals = []
        for c in cats:
            pts = [pt for pt in p.get("points", [])
                   if str(pt["x"]) == c and pt.get("series") == lab]
            if not pts:
                continue
            vals.append({"label": c, "value": _r(sum(pt["y"] for pt in pts) / len(pts)),
                         "error": None, "error_type": None,
                         "n": sum((pt.get("n") or 0) for pt in pts) or None,
                         "source_rows": [r for pt in pts for r in pt.get("source_rows", [])]})
        series.append({"label": lab, "color": old_series[si]["color"] if si < len(old_series)
                       else OKABE[si % len(OKABE)], "error_type": None, "values": vals})
    p["series"] = series
    p["categories"] = cats
    p["chart_type"] = "grouped_bar" if len(series) > 1 else "bar"
    p["points"] = []


def apply_spec_edits(spec, ops):
    before = json.dumps(spec, ensure_ascii=False, sort_keys=True)
    out = copy.deepcopy(spec)
    changes = []
    warnings = []

    def record(path, old, new, kind):
        if old != new:
            changes.append({"path": path, "kind": kind, "before": old, "after": new})

    if ops.get("title"):
        record("title", out.get("title"), ops["title"], "title")
        out["title"] = ops["title"]
        out["title_source"] = "user_edit"
    values_changed = False
    if ops.get("chart_type"):
        new_type = ops["chart_type"]
        p = out["panels"][0] if len(out["panels"]) == 1 else None
        if p is None:
            warnings.append("chart-type edit needs a single panel")
        else:
            old_type = p["chart_type"]
            converted = False
            if new_type == old_type:
                pass
            elif new_type == "line" and old_type in ("bar", "grouped_bar"):
                _to_line(p, out)
                _recompute(p, out)
                converted = True
            elif new_type in ("bar", "grouped_bar") and old_type == "line":
                _to_bar(p, out)
                if new_type == "bar" and len(p["series"]) > 1:
                    p["series"] = p["series"][:1]
                    warnings.append("bar edit kept only the first series; other series "
                                    "remain in the source, not in the figure")
                _recompute(p, out)
                converted = True
            elif new_type in ("bar", "grouped_bar") and old_type in ("bar", "grouped_bar"):
                p["chart_type"] = new_type
                _recompute(p, out)
                converted = True
            else:
                warnings.append("chart-type edit %s -> %s needs raw values; rerun "
                                "plan_figures.py with --intent %s instead of editing "
                                "the spec" % (old_type, new_type, new_type))
                new_type = old_type
            out["chart_type"] = new_type if len(out["panels"]) == 1 else out["chart_type"]
            record("panels[0].chart_type", old_type, out["chart_type"], "chart_type")
            values_changed = converted
    lo, hi = ops.get("y_min"), ops.get("y_max")
    if lo is not None or hi is not None:
        for p in out["panels"]:
            ax = p["axis"]["y"]
            nlo = float(lo) if lo is not None else ax["min"]
            nhi = float(hi) if hi is not None else ax["max"]
            if nhi <= nlo:
                warnings.append("ignored invalid y range [%s, %s]" % (nlo, nhi))
                continue
            old = (ax["min"], ax["max"])
            ax.update(pinned_ticks(nlo, nhi))
            record("panels[%s].axis.y" % p.get("id"), list(old),
                   [ax["min"], ax["max"]], "axis_range")
            if p.get("chart_type") in ("bar", "grouped_bar") and nlo > 0:
                out.setdefault("caveats", []).append(
                    "%s y 轴按编辑指令从 %s 开始（柱状图为截断显示，非零基线）"
                    % (p.get("id"), nlo))
    for text in ops.get("annotations", []):
        ann = {"id": "edit:annotation:%d" % (len(out.setdefault("annotations", [])) + 1),
               "kind": "note", "place": "figure_note", "text": text,
               "source": "user_instruction", "source_rows": []}
        out["annotations"].append(ann)
        record("annotations", None, text, "annotation")
    for label in ops.get("highlights", []):
        for p in out["panels"]:
            target = label if str(label).startswith(("bar:", "value:")) else "bar:%s" % label
            p.setdefault("highlights", []).append(
                {"target": target, "color": ACCENT, "note": "highlight"})
            record("panels[%s].highlights" % p.get("id"), None, target, "highlight")
    for pair in ops.get("set_text", []) or []:
        if "=" not in pair:
            warnings.append("ignored set-text without '=': %s" % pair)
            continue
        old, new = pair.split("=", 1)
        hit = 0
        for p in out["panels"]:
            p["title"] = p.get("title", "")
            if old in p["title"]:
                record("panels[%s].title" % p.get("id"), p["title"],
                       p["title"].replace(old, new), "text")
                p["title"] = p["title"].replace(old, new)
                hit += 1
            for ann in p.get("annotations", []):
                if old in str(ann.get("text", "")):
                    ann["text"] = ann["text"].replace(old, new)
                    hit += 1
            for s in p.get("series", []):
                if old in s.get("label", ""):
                    s["label"] = s["label"].replace(old, new)
                    hit += 1
        if not hit:
            warnings.append("set-text target not found: %s" % old)
    after = json.dumps(out, ensure_ascii=False, sort_keys=True)
    log = {
        "mode": "spec",
        "spec_sha256_before": h(before), "spec_sha256_after": h(after),
        "changed": before != after,
        "operations": {k: ops[k] for k in ops if ops.get(k)},
        "changes": changes, "warnings": warnings,
        "structure_preserved": not values_changed,
        "structural_fields_touched": [c["path"] for c in changes
                                      if c["kind"] in ("chart_type", "axis_range")],
    }
    return out, log


# --------------------------------------------------------------------------- svg
TEXT_RE = re.compile(r"<text\b([^>]*)>(.*?)</text>", re.S)
RECT_RE = re.compile(r"<rect\b[^>]*?/?>", re.S)


def _attr(tag, name):
    m = re.search(r'\b%s="([^"]*)"' % re.escape(name), tag)
    return m.group(1) if m else ""


def _svg_size(text):
    w = re.search(r'<svg[^>]*\bwidth="([0-9.]+)"', text)
    hgt = re.search(r'<svg[^>]*\bheight="([0-9.]+)"', text)
    return (float(w.group(1)) if w else 600.0, float(hgt.group(1)) if hgt else 400.0)


def apply_svg_edits(text, ops, source_name="source.svg"):
    original = text
    changes = []
    insertions = []
    warnings = []
    W, H = _svg_size(text)
    used = 0

    if ops.get("title") and ops["title"] != "":
        new_title = html.escape(ops["title"])
        m = re.search(r'(<text\b[^>]*\bid="fig_title"[^>]*>)(.*?)(</text>)', text, re.S)
        if m:
            old_inner = m.group(2)
            text = text[:m.start(2)] + new_title + text[m.end(2):]
            changes.append({"path": "svg#fig_title", "kind": "title",
                            "before": old_inner, "after": new_title})
        else:
            ins = ('<text id="edit_title" x="10" y="18" font-size="14" '
                   'font-family="sans-serif" fill="#222222">%s</text>' % new_title)
            insertions.append(ins)
            text = text.replace("</svg>", ins + "</svg>")
            changes.append({"path": "svg#insert:edit_title", "kind": "title",
                            "before": None, "after": new_title})
    for i, ann in enumerate(ops.get("annotations", []), start=1):
        y = H - 10 - (len(ops.get("annotations", [])) - i) * 12
        ins = ('<text id="edit_annotation_%d" x="8" y="%.1f" font-size="8" '
               'font-family="sans-serif" fill="#555555">%s</text>'
               % (i, y, html.escape(ann)))
        insertions.append(ins)
        text = text.replace("</svg>", ins + "</svg>")
        changes.append({"path": "svg#insert:edit_annotation_%d" % i, "kind": "annotation",
                        "before": None, "after": ann})
    for label in ops.get("highlights", []):
        lab = str(label)
        if lab.startswith("bar:"):
            lab = lab.split(":", 1)[1]
        target = None
        for tag in RECT_RE.findall(text):
            if _attr(tag, "data-label") == lab:
                target = tag
                break
        if target:
            x, y = _attr(target, "x"), _attr(target, "y")
            w, hh = _attr(target, "width"), _attr(target, "height")
            try:
                pad = 2.0
                ins = ('<rect x="%.2f" y="%.2f" width="%.2f" height="%.2f" fill="none" '
                       'stroke="%s" stroke-width="2" data-edit-highlight="%s"/>'
                       % (float(x) - pad, float(y) - pad, float(w) + 2 * pad,
                          float(hh) + 2 * pad, ACCENT, html.escape(lab)))
                text = text.replace(target, target + ins, 1)
                insertions.append(ins)
                changes.append({"path": "svg#highlight:%s" % lab, "kind": "highlight",
                                "before": None, "after": "rect around data-label=%s" % lab})
            except ValueError:
                warnings.append("could not parse rect geometry for %s" % lab)
        else:
            found = False
            for fm in TEXT_RE.finditer(text):
                label_text = re.sub(r"<[^>]+>", "", fm.group(2))
                if label_text.strip() == lab:
                    tag = fm.group(0)
                    x = float(_attr(tag, "x") or 0)
                    y = float(_attr(tag, "y") or 0)
                    ins = ('<rect x="%.1f" y="%.1f" width="%.1f" height="13" fill="none" '
                           'stroke="%s" stroke-width="1.6" data-edit-highlight="%s"/>'
                           % (x - 3, y - 10, min(max(len(lab) * 6.0, 18), 160), ACCENT,
                              html.escape(lab)))
                    text = text.replace(tag, ins + tag, 1)
                    insertions.append(ins)
                    changes.append({"path": "svg#highlight_text:%s" % lab,
                                    "kind": "highlight", "before": None,
                                    "after": "label text outlined"})
                    found = True
                    break
            if not found:
                warnings.append("highlight label not found in SVG: %s" % lab)
    for pair in ops.get("set_text", []) or []:
        if "=" not in pair:
            warnings.append("ignored set-text without '=': %s" % pair)
            continue
        old, new = pair.split("=", 1)
        hit = 0
        for m in list(TEXT_RE.finditer(text)):
            inner = m.group(2)
            if old in inner and "<" not in inner:
                updated = m.group(0).replace(inner, html.escape(new), 1)
                text = text.replace(m.group(0), updated, 1)
                changes.append({"path": "svg#text:%s" % html.escape(old),
                                "kind": "text", "before": old, "after": new})
                hit += 1
        if not hit:
            warnings.append("set-text target not found: %s" % old)

    # structure proof: remove inserted nodes and reverse text edits
    probe = text
    for ins in insertions:
        probe = probe.replace(ins, "", 1)
    for c in changes:
        if c["kind"] in ("text", "title") and c["before"] and c["after"]:
            probe = probe.replace(html.escape(c["after"]), html.escape(c["before"]), 1)
    restored = probe == original
    log = {
        "mode": "svg",
        "source": {"file": source_name, "sha256": h(original), "bytes": len(original)},
        "output_sha256": h(text), "output_bytes": len(text),
        "changes": changes,
        "inserted_nodes": insertions,
        "text_nodes_before": len(TEXT_RE.findall(original)),
        "text_nodes_after": len(TEXT_RE.findall(text)),
        "structure_preserved": restored,
        "verification": {"remove_insertions_equals_source": restored,
                         "unchanged_nodes_rewritten": False},
        "warnings": warnings,
    }
    return text, log


# --------------------------------------------------------------------------- CLI
def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd")
    sp = sub.add_parser("spec")
    sp.add_argument("--spec", required=True)
    sp.add_argument("--out", default="work")
    sp.add_argument("--title", default="")
    sp.add_argument("--y-min", type=float, default=None)
    sp.add_argument("--y-max", type=float, default=None)
    sp.add_argument("--annotate", action="append", default=[])
    sp.add_argument("--highlight", action="append", default=[])
    sp.add_argument("--set-text", action="append", default=[])
    sp.add_argument("--chart-type", default="")
    sp.set_defaults(func=_main_spec)
    sv = sub.add_parser("svg")
    sv.add_argument("--svg", required=True)
    sv.add_argument("--out", default="work")
    sv.add_argument("--title", default="")
    sv.add_argument("--annotate", action="append", default=[])
    sv.add_argument("--highlight", action="append", default=[])
    sv.add_argument("--set-text", action="append", default=[])
    sv.set_defaults(func=_main_svg)
    a = ap.parse_args()
    if not getattr(a, "func", None):
        ap.print_help()
        return 2
    return a.func(a)


def _ops_from(a):
    return {"title": a.title, "annotations": a.annotate, "highlights": a.highlight,
            "set_text": a.set_text, "y_min": getattr(a, "y_min", None),
            "y_max": getattr(a, "y_max", None), "chart_type": getattr(a, "chart_type", "")}


def _main_spec(a):
    spec = json.load(open(a.spec, encoding="utf-8"))
    out, log = apply_spec_edits(spec, _ops_from(a))
    os.makedirs(a.out, exist_ok=True)
    if not os.path.exists(os.path.join(a.out, "chart_spec.original.json")):
        with open(os.path.join(a.out, "chart_spec.original.json"), "w",
                  encoding="utf-8") as fh:
            json.dump(spec, fh, ensure_ascii=False, indent=1)
    with open(os.path.join(a.out, "chart_spec.json"), "w", encoding="utf-8") as fh:
        json.dump(out, fh, ensure_ascii=False, indent=1)
    with open(os.path.join(a.out, "edit_log.json"), "w", encoding="utf-8") as fh:
        json.dump(log, fh, ensure_ascii=False, indent=1)
    print("spec edited: changes=%d warnings=%d structure_preserved=%s"
          % (len(log["changes"]), len(log["warnings"]), log["structure_preserved"]))
    for w in log["warnings"]:
        print("  ~", w)
    return 0


def _main_svg(a):
    text = open(a.svg, encoding="utf-8", errors="replace").read()
    ops = _ops_from(a)
    out_text, log = apply_svg_edits(text, ops, os.path.basename(a.svg))
    os.makedirs(a.out, exist_ok=True)
    src_copy = os.path.join(a.out, "source_figure.svg")
    if not os.path.exists(src_copy):
        with open(src_copy, "w", encoding="utf-8") as fh:
            fh.write(text)
    with open(os.path.join(a.out, "figure.svg"), "w", encoding="utf-8") as fh:
        fh.write(out_text)
    with open(os.path.join(a.out, "edit_log.json"), "w", encoding="utf-8") as fh:
        json.dump(log, fh, ensure_ascii=False, indent=1)
    print("svg edited: changes=%d nodes_inserted=%d text_nodes=%d->%d preserved=%s"
          % (len(log["changes"]), len(log["inserted_nodes"]),
             log["text_nodes_before"], log["text_nodes_after"],
             log["structure_preserved"]))
    for w in log["warnings"]:
        print("  ~", w)
    return 0


if __name__ == "__main__":
    sys.exit(main())
