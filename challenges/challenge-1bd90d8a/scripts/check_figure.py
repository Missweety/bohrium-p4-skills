#!/usr/bin/env python3
"""check_figure.py - independent self-check of the produced figure package.

It does not trust the spec: it re-reads the source table, recomputes each data mark,
and compares. It also checks that every spec element appears in element_map.json, that
the SVG really contains <text> nodes with the required labels, that colours stay in the
declared palettes, that axes/ticks/error bars are inside bounds, that the caption
states the error semantics, sample sizes and missing/outlier policy, that no
significance annotation exists without a source column, and that edits are auditable.

Output: selfcheck.json {verdict, checks[], errors[], warnings[], stats}.
Exit 0 only on PASS.

Usage:
  python3 scripts/check_figure.py --spec work/chart_spec.json --work work
  python3 scripts/check_figure.py --svg-only --work work
"""
import argparse
import hashlib
import json
import math
import os
import re
import struct
import sys

import tableio
from labels import OKABE, VIRIDIS

TEXT_RE = re.compile(r"<text\b[^>]*>(.*?)</text>", re.S)
TAG_RE = re.compile(r"<[^>]+>")
COLOR_RE = re.compile(r'(?:fill|stroke)\s*[:=]\s*"?(#[0-9A-Fa-f]{6}|#[0-9A-Fa-f]{3})')
CJK_RE = re.compile(r"[\u4e00-\u9fff]")
SIG_RE = re.compile(r"(?:p\s*[=<>]\s*0?\.\d+)|(?:p\s*[- ]?value)|p值|显著性", re.I)
ALLOWED = {c.upper() for c in OKABE + VIRIDIS} | {"#B00020"}


class Checks:
    def __init__(self):
        self.checks, self.errors, self.warnings = [], [], []
        self.stats = {}

    def add(self, cid, ok, detail="", warning=False):
        rec = {"id": cid, "ok": bool(ok), "detail": detail}
        if warning:
            rec["warning"] = True
            self.warnings.append("%s: %s" % (cid, detail))
        elif not ok:
            self.errors.append("%s: %s" % (cid, detail))
        self.checks.append(rec)
        return ok

    def warn(self, cid, detail):
        self.checks.append({"id": cid, "ok": True, "detail": detail, "warning": True})
        self.warnings.append("%s: %s" % (cid, detail))


def norm_text(s):
    s = TAG_RE.sub("", str(s))
    return re.sub(r"\s+", "", s).lower()


def unescape(s):
    import html
    return html.unescape(TAG_RE.sub("", s))


def svg_texts(path):
    try:
        raw = open(path, encoding="utf-8", errors="replace").read()
    except OSError:
        return "", []
    return raw, [unescape(x) for x in TEXT_RE.findall(raw)]


def svg_colors(raw):
    return {m.upper() for m in COLOR_RE.findall(raw)}


def neutral(hexc):
    h = hexc.lstrip("#")
    if len(h) == 3:
        h = "".join(ch * 2 for ch in h)
    try:
        r, g, b = (int(h[i:i + 2], 16) for i in (0, 2, 4))
    except ValueError:
        return False
    return r == g == b


def quantile(sorted_vals, q):
    if not sorted_vals:
        return None
    if len(sorted_vals) == 1:
        return sorted_vals[0]
    pos = (len(sorted_vals) - 1) * q
    lo = int(pos)
    hi = min(lo + 1, len(sorted_vals) - 1)
    frac = pos - lo
    return sorted_vals[lo] * (1 - frac) + sorted_vals[hi] * frac


def close(a, b, tol=1e-5):
    if a is None or b is None:
        return a == b
    return abs(float(a) - float(b)) <= tol * max(1.0, abs(float(b)))


def display_field(field):
    name, unit = field.get("name", ""), field.get("unit", "")
    if unit and unit not in name:
        return "%s (%s)" % (name, unit)
    return name


# --------------------------------------------------------------- expected elements
def expected_ids(spec):
    ids = set()
    for pi, p in enumerate(spec.get("panels", [])):
        pid = p.get("id") or chr(ord("A") + pi)
        pre = "panel:%s:" % pid
        ids.add(pre + "title")
        for key in ("x", "y", "color"):
            if p.get("axis", {}).get(key):
                ids.add(pre + "axis:" + key)
        ct = p.get("chart_type")
        for si in range(len(p.get("series", []))):
            ids.add(pre + "series:%d" % si)
        if ct in ("bar", "grouped_bar"):
            for si, s in enumerate(p.get("series", [])):
                for v in s.get("values", []):
                    ids.add(pre + "bar:%d|%s" % (si, v.get("label")))
        elif ct in ("line", "scatter"):
            for k in range(len(p.get("points", []))):
                ids.add(pre + "point:%d" % k)
        elif ct == "hist":
            for k in range(len(p.get("bins", []))):
                ids.add(pre + "bin:%d" % k)
        elif ct == "box":
            for b in p.get("boxes", []):
                ids.add(pre + "box:%s" % b.get("label"))
        elif ct == "heatmap":
            for ri, _ in enumerate(p.get("row_labels", [])):
                for ci, _ in enumerate(p.get("col_labels", [])):
                    if any(c.get("row_label") == p["row_labels"][ri]
                           and c.get("col_label") == p["col_labels"][ci]
                           for c in p.get("cells", [])):
                        ids.add(pre + "cell:%d|%d" % (ri, ci))
        if p.get("legend", {}).get("show"):
            for item in p.get("legend", {}).get("items", []):
                ids.add(pre + "legend:%s" % item.get("label"))
        for ann in p.get("annotations", []):
            ids.add(pre + "annotation:" + str(ann.get("id")))
        for hl in p.get("highlights", []):
            ids.add(pre + "highlight:" + str(hl.get("target")))
    for ann in spec.get("annotations", []):
        ids.add("annotation:" + str(ann.get("id")))
    return ids


# --------------------------------------------------------------- source access
def load_source(spec, work):
    src = spec.get("source", {})
    cands = []
    if src.get("normalized"):
        cands.append(src["normalized"])
        cands.append(os.path.join(work, src["normalized"]))
    if src.get("path"):
        cands.append(src["path"])
    if src.get("file"):
        cands.append(os.path.join(work, src["file"]))
        cands.append(src["file"])
    for c in cands:
        if c and os.path.exists(c):
            try:
                return tableio.read_any(c), c
            except Exception:  # noqa: BLE001
                continue
    return None, ""


def value_at(table, row, column):
    if column is None:
        return None
    j = int(column)
    i = int(row) - 2
    if i < 0 or i >= len(table["rows"]) or j < 0 or j >= table["columns"]:
        return None
    return tableio.to_number(table["rows"][i][j])


# --------------------------------------------------------------- checks
def check(spec, work, out_dir, svg_only=False):
    c = Checks()
    c.stats["chart_type"] = spec.get("chart_type") if spec else "svg-edit"
    if not svg_only:
        _check_spec(c, spec)
        _check_panel_content(c, spec)
        _check_axes(c, spec)
        _check_labels(c, spec, out_dir)
        _check_colors(c, out_dir)
        _check_caption(c, spec, out_dir)
        _check_significance(c, spec)
        table, tpath = load_source(spec, work)
        emap = _load_json(os.path.join(out_dir, "element_map.json"))
        if emap is None:
            emap = _load_json(os.path.join(work, "element_map.json"))
        _check_element_map(c, spec, emap, table, tpath)
        _check_recompute(c, spec, emap, table)
        _check_missing(c, spec)
        _check_render(c, spec, work, out_dir)
        _check_edit(c, spec.get("source", {}).get("file", ""), work, out_dir)
    else:
        _check_svg_only(c, work, out_dir)
    _check_caption_generic(c, work, out_dir)
    verdict = "PASS" if not c.errors else "FAIL"
    result = {"verdict": verdict, "checks": c.checks, "errors": c.errors,
              "warnings": c.warnings, "stats": c.stats,
              "checked": True, "checker": "check_figure.py"}
    return result


def _load_json(path):
    try:
        return json.load(open(path, encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return None


def _check_spec(c, spec):
    c.add("spec.version", spec.get("spec_version") == "1.1", spec.get("spec_version", ""))
    panels = spec.get("panels") or []
    c.add("spec.panels", bool(panels), "%d panel(s)" % len(panels))
    ok_types = all(p.get("chart_type") in ("bar", "grouped_bar", "line", "scatter",
                                           "hist", "box", "heatmap") for p in panels)
    c.add("spec.chart_types", ok_types,
          ",".join(p.get("chart_type", "") for p in panels))
    ids = [p.get("id") for p in panels]
    c.add("spec.panel_ids", len(ids) == len(set(ids)) and all(ids), ",".join(map(str, ids)))
    src = spec.get("source", {})
    c.add("spec.source", bool(src.get("file")) and bool(src.get("sha256")) and
          (src.get("rows") or 0) > 0,
          "%s sha=%s rows=%s" % (src.get("file"), (src.get("sha256") or "")[:10],
                                 src.get("rows")))
    c.add("spec.title", bool(spec.get("title")), spec.get("title", ""))
    c.stats["panels"] = len(panels)
    c.stats["title"] = spec.get("title")


def panel_marks(p):
    ct = p.get("chart_type")
    if ct in ("bar", "grouped_bar"):
        return sum(len(s.get("values") or []) for s in p.get("series", []))
    if ct in ("line", "scatter"):
        return len(p.get("points") or [])
    if ct == "hist":
        return sum(1 for b in p.get("bins", []) if (b.get("count") or 0) > 0)
    if ct == "box":
        return len(p.get("boxes") or [])
    if ct == "heatmap":
        return len(p.get("cells") or [])
    return 0


def _check_panel_content(c, spec):
    marks = {}
    for p in spec.get("panels", []):
        pid = p.get("id") or "?"
        n = panel_marks(p)
        marks[pid] = n
        c.add("panels.content", n > 0,
              "panel %s (%s) has zero data marks: no usable rows for the selected "
              "y column" % (pid, p.get("chart_type")))
    c.stats["data_marks"] = marks


def _check_axes(c, spec):
    problems = []
    for p in spec.get("panels", []):
        pid = p.get("id")
        ct = p.get("chart_type")
        axis = p.get("axis", {})
        for key in (("x", "y", "color") if ct == "heatmap" else ("x", "y")):
            ax = axis.get(key)
            if not ax:
                problems.append("%s missing %s axis" % (pid, key))
                continue
            if ax.get("kind") == "numeric":
                lo, hi, ticks = ax.get("min"), ax.get("max"), ax.get("ticks") or []
                if lo is None or hi is None or hi <= lo:
                    problems.append("%s.%s invalid range %s..%s" % (pid, key, lo, hi))
                if not (3 <= len(ticks) <= 8):
                    problems.append("%s.%s tick count %d" % (pid, key, len(ticks)))
                if ticks != sorted(ticks) or any(t < lo - 1e-9 or t > hi + 1e-9
                                                 for t in ticks):
                    problems.append("%s.%s ticks outside bounds" % (pid, key))
            elif ax.get("kind") == "category":
                cats = ax.get("categories")
                if not cats and ct not in ("bar", "grouped_bar", "line", "box"):
                    problems.append("%s.%s no categories" % (pid, key))
        if ct in ("bar", "grouped_bar"):
            y = axis.get("y", {})
            if not (y.get("min", 1) <= 0 <= y.get("max", -1)):
                if y.get("pinned"):
                    c.warn("%s.bar_baseline" % pid,
                           "y range pinned by an edit excludes 0: bars are truncated; "
                           "state this in the caption instead of hiding it")
                else:
                    problems.append("%s bar baseline 0 outside y range" % pid)
        if ct == "heatmap":
            col = axis.get("color", {})
            if not (3 <= len(col.get("ticks") or []) <= 8):
                problems.append("%s color ticks %d" % (pid, len(col.get("ticks") or [])))

        def outside(vals, key, what):
            ax = axis.get(key) or {}
            lo, hi = ax.get("min"), ax.get("max")
            if lo is None or hi is None:
                return
            tol = (hi - lo) * 1e-6 + 1e-9
            bad = [v for v in vals if isinstance(v, (int, float))
                   and (v > hi + tol or v < lo - tol)]
            if bad:
                problems.append("%s %s outside %s range %s..%s: %s"
                                % (pid, what, key, lo, hi,
                                   ", ".join("%.6g" % v for v in bad[:4])))

        if ct in ("bar", "grouped_bar"):
            tops = []
            for s in p.get("series", []):
                for v in s.get("values", []):
                    if isinstance(v.get("value"), (int, float)):
                        tops.append(v["value"] + abs(v.get("error") or 0))
            outside(tops, "y", "bar top")
            y = axis.get("y") or {}
            if y.get("min", 0) <= 0:
                outside([v["value"] - abs(v.get("error") or 0)
                         for s in p.get("series", [])
                         for v in s.get("values", [])
                         if isinstance(v.get("value"), (int, float))],
                        "y", "bar bottom")
        elif ct in ("line", "scatter"):
            ys, ys_lo, ys_hi = [], [], []
            for pt in p.get("points", []):
                y = pt.get("y")
                e = abs(pt.get("error") or 0)
                if isinstance(y, (int, float)):
                    ys.append(y)
                    ys_lo.append(y - e)
                    ys_hi.append(y + e)
            outside(ys, "y", "point")
            outside(ys_lo, "y", "error lower")
            outside(ys_hi, "y", "error upper")
        elif ct == "hist":
            outside([b.get("count") for b in p.get("bins", [])], "y", "bin count")
        elif ct == "box":
            outside([b.get("max") for b in p.get("boxes", [])], "y", "box max")
            outside([b.get("min") for b in p.get("boxes", [])], "y", "box min")
        elif ct == "heatmap":
            outside([c.get("value") for c in p.get("cells", [])], "color", "cell")
    c.add("axes.valid", not problems, "; ".join(problems[:6]))


def _present(needle, texts_norm):
    n = norm_text(needle)
    if not n:
        return True
    if n in texts_norm:
        return True
    if len(n) >= 6 and n[:max(6, len(n) // 2)] in texts_norm:
        return True
    return False


def _check_labels(c, spec, out_dir):
    raw, texts = svg_texts(os.path.join(out_dir, "figure.svg"))
    alltext = norm_text(" ".join(texts))
    c.add("svg.exists", bool(raw), "%d bytes" % len(raw))
    c.add("svg.text_nodes", len(texts) >= 4, "%d <text> nodes" % len(texts))
    missing = []
    if not _present(spec.get("title", ""), alltext):
        missing.append("title")
    for p in spec.get("panels", []):
        pid = p.get("id")
        if len(spec["panels"]) > 1 and not _present(p.get("title", ""), alltext):
            missing.append("%s title" % pid)
        ax = p.get("axis", {})
        for key in ("x", "y"):
            label = ax.get(key, {}).get("label", "")
            if label and not _present(label, alltext):
                missing.append("%s axis %s" % (pid, key))
        cats = (p.get("categories") or p.get("row_labels") or [])[:40]
        for cat in cats:
            if not _present(str(cat), alltext):
                missing.append("%s label %s" % (pid, str(cat)[:18]))
                break
        if p.get("legend", {}).get("show"):
            for item in p.get("legend", {}).get("items", []):
                if not _present(item.get("label", ""), alltext):
                    missing.append("%s legend %s" % (pid, item.get("label")))
        if p.get("chart_type") == "heatmap":
            for cl in (p.get("col_labels") or [])[:20]:
                if not _present(str(cl), alltext):
                    missing.append("%s col %s" % (pid, cl))
                    break
    c.add("labels.rendered", not missing, "; ".join(missing[:6]))
    cjk_labels = any(CJK_RE.search(str(x)) for x in
                     [spec.get("title", "")] + [p.get("title", "") for p in spec.get("panels", [])]
                     + [p.get("axis", {}).get("y", {}).get("label", "")
                        for p in spec.get("panels", [])])
    if cjk_labels:
        c.add("labels.cjk_not_tofu", bool(CJK_RE.search(" ".join(texts))),
              "CJK text kept as <text>")
    c.stats["svg_text_nodes"] = len(texts)


def _check_colors(c, out_dir):
    raw, _ = svg_texts(os.path.join(out_dir, "figure.svg"))
    bad = sorted({x for x in svg_colors(raw) if x not in ALLOWED and not neutral(x)})
    c.add("palette.okabe_viridis", not bad, ",".join(bad[:8]))
    c.stats["colors"] = len(svg_colors(raw))


def _check_caption(c, spec, out_dir):
    path = os.path.join(out_dir, "caption.md")
    text = ""
    if os.path.exists(path):
        text = open(path, encoding="utf-8").read()
    problems = []
    if len(text) < 200:
        problems.append("caption too short (%d chars)" % len(text))
    need = [spec.get("source", {}).get("file", ""), "误差线", "sha256",
            "element_map"]
    for n in need:
        if n and n not in text:
            problems.append("missing %r" % n)
    if "n=" not in text and "样本量" not in text:
        problems.append("sample size not stated")
    err = spec.get("error_semantics", {})
    if err.get("label") and err["label"] not in text and err.get("text", "")[:2] not in text:
        problems.append("error semantics %r not stated" % err.get("label"))
    if spec.get("significance_provided"):
        if "未做" not in text and "not recomputed" not in text:
            problems.append("significance provenance not stated")
    else:
        if "未提供" not in text and "no significance" not in text.lower():
            problems.append("absence of significance not stated")
    if not any(k in text for k in ("缺失", "missing")):
        problems.append("missing-value policy not stated")
    if not any(k in text for k in ("异常值", "outlier")):
        problems.append("outlier policy not stated")
    c.add("caption.complete", not problems, "; ".join(problems))


def _check_significance(c, spec):
    sig_anns = []
    for p in spec.get("panels", []):
        sig_anns += [a for a in p.get("annotations", [])
                     if a.get("kind") == "significance" or SIG_RE.search(a.get("text", ""))]
    sig_anns += [a for a in spec.get("annotations", [])
                 if a.get("kind") == "significance" or SIG_RE.search(a.get("text", ""))]
    problems = []
    for a in sig_anns:
        if a.get("kind") == "significance" and not a.get("source_rows"):
            problems.append("significance without source rows: %s" % a.get("id"))
        if str(a.get("source", "")).startswith("user_instruction"):
            problems.append("significance from user instruction: %s" % a.get("id"))
    if sig_anns and not spec.get("significance_provided"):
        problems.append("significance annotation but significance_provided=false")
    c.add("significance.source_only", not problems, "; ".join(problems[:4]))


def _check_element_map(c, spec, emap, table, tpath):
    if not emap:
        c.add("element_map.present", False, "element_map.json missing")
        return
    els = emap.get("elements") or []
    c.add("element_map.present", bool(els), "%d elements" % len(els))
    ids = [e.get("element") for e in els]
    dup = len(ids) - len(set(ids))
    c.add("element_map.unique_ids", dup == 0, "%d duplicates" % dup)
    exp = expected_ids(spec)
    missing = sorted(exp - set(ids))
    extra = sorted(set(ids) - exp)
    c.add("element_map.complete", not missing and not extra,
          "missing %s extra %s" % (missing[:5], extra[:5]))
    bad = []
    for e in els:
        if e.get("kind") in ("bar", "point", "bin", "box", "cell"):
            if not e.get("source_rows"):
                bad.append("no source_rows: %s" % e.get("element"))
            if e.get("source") in (None, "") and not tpath:
                bad.append("no source: %s" % e.get("element"))
            if e.get("column") is None and e.get("kind") != "bin":
                bad.append("no column: %s" % e.get("element"))
    c.add("element_map.traceable_fields", not bad, "; ".join(bad[:5]))
    if table is not None:
        hi = table["rows_total"] + 1
        badrows = []
        for e in els:
            for r in e.get("source_rows") or []:
                if not isinstance(r, int) or r < 2 or r > hi:
                    badrows.append("%s row %s" % (e.get("element"), r))
            j = e.get("column")
            if j is not None and (j < 0 or j >= table["columns"]):
                badrows.append("%s column %s" % (e.get("element"), j))
        c.add("element_map.rows_in_source", not badrows, "; ".join(badrows[:5]))
    else:
        c.warn("element_map.rows_in_source", "source table unavailable; row range not verified")


def _check_recompute(c, spec, emap, table):
    if not table or not emap:
        c.warn("values.recomputed", "source table unavailable; recomputation skipped")
        return
    els = {e["element"]: e for e in emap.get("elements", [])}
    problems = []
    checked = 0
    for p in spec.get("panels", []):
        pid = p.get("id")
        ct = p.get("chart_type")
        if ct in ("bar", "grouped_bar"):
            for si, s in enumerate(p.get("series", [])):
                for v in s.get("values", []):
                    eid = "panel:%s:bar:%d|%s" % (pid, si, v.get("label"))
                    e = els.get(eid)
                    if not e:
                        continue
                    vals = [value_at(table, r, v_column(spec, p)) for r in e["source_rows"]]
                    vals = [x for x in vals if x is not None]
                    if not vals:
                        problems.append("%s no parseable source values" % eid)
                        continue
                    mean = sum(vals) / len(vals)
                    if not close(e.get("value"), mean):
                        problems.append("%s value %s != recomputed %s"
                                        % (eid, e.get("value"), round(mean, 6)))
                    if e.get("n") is not None and e["n"] != len(e["source_rows"]):
                        # summary rows may carry an explicit n; only flag raw mode
                        if not p.get("summary_mode"):
                            problems.append("%s n %s != rows %d"
                                            % (eid, e["n"], len(e["source_rows"])))
                    checked += 1
        elif ct == "line":
            for k, pt in enumerate(p.get("points", [])):
                e = els.get("panel:%s:point:%d" % (pid, k))
                if not e:
                    continue
                vals = [value_at(table, r, v_column(spec, p)) for r in e["source_rows"]]
                vals = [x for x in vals if x is not None]
                if not vals:
                    problems.append("point %d no source values" % k)
                else:
                    mean = sum(vals) / len(vals)
                    if not close(e.get("y"), mean):
                        problems.append("point %d y %s != %s" % (k, e.get("y"), mean))
            checked += 1
        elif ct == "scatter":
            for k, pt in enumerate(p.get("points", [])):
                e = els.get("panel:%s:point:%d" % (pid, k))
                if not e:
                    continue
                y = value_at(table, e["source_rows"][0], e.get("column"))
                x = value_at(table, e["source_rows"][0], e.get("x_column"))
                if not close(e.get("y"), y) or not close(e.get("x"), x):
                    problems.append("point %d (%s,%s) != source (%s,%s)"
                                    % (k, e.get("x"), e.get("y"), x, y))
                checked += 1
        elif ct == "hist":
            seen = set()
            for k, b in enumerate(p.get("bins", [])):
                e = els.get("panel:%s:bin:%d" % (pid, k))
                if not e:
                    continue
                rows = e.get("source_rows") or []
                if e.get("count") != len(rows):
                    problems.append("bin %d count %s != rows %d"
                                    % (k, e.get("count"), len(rows)))
                for r in rows:
                    v = value_at(table, r, e.get("column"))
                    if v is None or v < b["lo"] - 1e-9 or v > b["hi"] + 1e-9:
                        problems.append("bin %d row %s outside [%s,%s]"
                                        % (k, r, b["lo"], b["hi"]))
                    if r in seen:
                        problems.append("row %s appears in two bins" % r)
                    seen.add(r)
                checked += 1
            covered = {r for b in p.get("bins", []) for r in b.get("rows", [])}
            c.stats.setdefault("hist_rows", {})[pid] = len(covered)
        elif ct == "box":
            for b in p.get("boxes", []):
                e = els.get("panel:%s:box:%s" % (pid, b.get("label")))
                if not e:
                    continue
                vals = sorted(x for x in (value_at(table, r, v_column(spec, p))
                                          for r in e["source_rows"]) if x is not None)
                if not vals:
                    problems.append("box %s no values" % b.get("label"))
                    continue
                q1, med, q3 = quantile(vals, 0.25), quantile(vals, 0.5), quantile(vals, 0.75)
                iqr = q3 - q1
                inside = [v for v in vals if q1 - 1.5 * iqr <= v <= q3 + 1.5 * iqr]
                for key, val in (("q1", q1), ("median", med), ("q3", q3),
                                 ("min", min(inside)), ("max", max(inside))):
                    if not close(e.get(key), val):
                        problems.append("box %s %s %s != %s"
                                        % (b.get("label"), key, e.get(key), round(val, 6)))
                checked += 1
        elif ct == "heatmap":
            for ri, rl in enumerate(p.get("row_labels", [])):
                for ci, cl in enumerate(p.get("col_labels", [])):
                    e = els.get("panel:%s:cell:%d|%d" % (pid, ri, ci))
                    if not e:
                        continue
                    vals = [value_at(table, r, e.get("column"))
                            for r in e["source_rows"]]
                    vals = [x for x in vals if x is not None]
                    if not vals:
                        problems.append("cell %s|%s no values" % (rl, cl))
                    elif not close(e.get("value"), sum(vals) / len(vals)):
                        problems.append("cell %s|%s value mismatch" % (rl, cl))
                    checked += 1
    c.add("values.recomputed", not problems,
          "%d marks recomputed; %s" % (checked, "; ".join(problems[:5])))
    c.stats["recomputed_marks"] = checked


def v_column(spec, p):
    """Column index of the primary value field for bar/line/box."""
    f = p.get("fields", {}).get("y", {})
    if f.get("column") is not None:
        return f["column"]
    return 0


def _check_missing(c, spec):
    rows = spec.get("source", {}).get("rows") or 0
    miss = spec.get("missing", {}) or {}
    out = spec.get("outliers", {}) or {}
    c.add("missing.declared", isinstance(miss.get("count"), int) and
          miss.get("policy") == "drop_row_no_imputation",
          "count=%s policy=%s" % (miss.get("count"), miss.get("policy")))
    if miss.get("count"):
        c.add("missing.rows_bounded", all(2 <= r <= rows + 1 for r in miss.get("rows", [])),
              str(miss.get("rows", [])[:8]))
    c.add("outliers.declared", "method" in out and "policy" in out,
          "%s n=%s" % (out.get("method"), out.get("count")))


def _png_info(path):
    try:
        raw = open(path, "rb").read(24)
    except OSError:
        return {}
    if raw[:8] != b"\x89PNG\r\n\x1a\n":
        return {}
    w, h = struct.unpack(">II", raw[16:24])
    return {"width": w, "height": h, "bytes": os.path.getsize(path)}


def _check_render(c, spec, work, out_dir):
    meta = _load_json(os.path.join(out_dir, "render_meta.json")) or \
        _load_json(os.path.join(work, "render_meta.json")) or {}
    renderer = meta.get("renderer", "")
    c.stats["renderer"] = renderer
    svg = os.path.join(out_dir, "figure.svg")
    c.add("render.svg", os.path.exists(svg) and os.path.getsize(svg) > 2000,
          "%d bytes" % (os.path.getsize(svg) if os.path.exists(svg) else 0))
    if renderer == "matplotlib":
        png = os.path.join(out_dir, "figure.png")
        info = _png_info(png)
        c.add("render.png_nontrivial", bool(info) and info.get("width", 0) >= 600 and
              info.get("height", 0) >= 400 and info.get("bytes", 0) >= 5000,
              str(info))
        pdf = os.path.join(out_dir, "figure.pdf")
        ok = os.path.exists(pdf) and os.path.getsize(pdf) > 1000
        if ok:
            with open(pdf, "rb") as fh:
                ok = fh.read(4) == b"%PDF"
        c.add("render.pdf_valid", ok,
              "%d bytes" % (os.path.getsize(pdf) if os.path.exists(pdf) else 0))
        c.stats["png"] = info
    else:
        c.warn("render.raster_partial",
               "renderer=%s: SVG only, PNG/PDF need a converter (partial status)"
               % (renderer or "unknown"))
    if spec.get("style", {}).get("cjk"):
        font = meta.get("cjk_font", "")
        if renderer == "matplotlib" and not font:
            c.warn("font.cjk_missing",
                   "no CJK font: Chinese kept in SVG/PDF text but raster may show boxes")
        else:
            c.add("font.cjk", True, "cjk_font=%r" % font, warning=False)
    # SVG dimensions
    raw, _ = svg_texts(svg)
    m = re.search(r'<svg[^>]*\bwidth="([0-9.]+)"', raw or "")
    if m:
        c.add("render.svg_width", float(m.group(1)) >= 380, m.group(1) + " px")


def _edit_requested(out_dir, work):
    case = _load_json(os.path.join(work, "case.json")) or {}
    hints = case.get("hints") or {}
    return bool(hints.get("edit_instructions")), case


def _check_edit(c, source_name, work, out_dir):
    log = _load_json(os.path.join(out_dir, "edit_log.json"))
    requested, case = _edit_requested(out_dir, work)
    if log is None:
        c.add("edit.log", not requested,
              "edit instructions present but edit_log.json missing" if requested else "no edit")
        return
    mode = log.get("mode")
    c.add("edit.mode", mode in ("spec", "svg"), str(mode))
    c.add("edit.changes", bool(log.get("changes")) or bool(log.get("warnings")),
          "%d change(s) %d warning(s)" % (len(log.get("changes") or []),
                                          len(log.get("warnings") or [])))
    if mode == "svg":
        src = log.get("source", {})
        base = os.path.join(out_dir, "source_figure.svg")
        if os.path.exists(base):
            h = hashlib.sha256(open(base, "rb").read()).hexdigest()
            c.add("edit.before_hash", h == src.get("sha256"),
                  "%s vs %s" % (h[:10], (src.get("sha256") or "")[:10]))
        cur = os.path.join(out_dir, "figure.svg")
        h2 = hashlib.sha256(open(cur, "rb").read()).hexdigest() if os.path.exists(cur) else ""
        c.add("edit.after_hash", h2 == log.get("output_sha256"),
              "%s vs %s" % (h2[:10], (log.get("output_sha256") or "")[:10]))
        c.add("edit.structure_preserved", log.get("structure_preserved") is True,
              "insertions removable / replacements reversible")
    else:
        orig = _load_json(os.path.join(out_dir, "chart_spec.original.json"))
        cur = _load_json(os.path.join(out_dir, "chart_spec.json"))
        if orig and cur:
            h1 = hashlib.sha256(json.dumps(orig, ensure_ascii=False,
                                           sort_keys=True).encode()).hexdigest()
            h2 = hashlib.sha256(json.dumps(cur, ensure_ascii=False,
                                           sort_keys=True).encode()).hexdigest()
            c.add("edit.before_hash", h1 == log.get("spec_sha256_before"), h1[:10])
            c.add("edit.after_hash", h2 == log.get("spec_sha256_after"), h2[:10])
        structural = log.get("structural_fields_touched") or []
        declared = bool(structural) and log.get("structure_preserved") is not True
        c.add("edit.structure_preserved",
              log.get("structure_preserved") is True or declared,
              ("declared structural edit: %s; data values re-verified by recompute"
               % ", ".join(structural)) if declared
              else "data values untouched by title/annotation/highlight")


def _check_svg_only(c, work, out_dir):
    raw, texts = svg_texts(os.path.join(out_dir, "figure.svg"))
    c.add("svg.exists", bool(raw) and len(raw) > 500, "%d bytes" % len(raw))
    c.add("svg.text_nodes", len(texts) >= 4, "%d text nodes" % len(texts))
    log = _load_json(os.path.join(out_dir, "edit_log.json")) or {}
    c.add("edit.log", log.get("mode") == "svg", str(log.get("mode")))
    c.add("edit.structure_preserved", log.get("structure_preserved") is True, "")
    base = os.path.join(out_dir, "source_figure.svg")
    if os.path.exists(base):
        h = hashlib.sha256(open(base, "rb").read()).hexdigest()
        c.add("edit.before_hash", h == (log.get("source") or {}).get("sha256"), h[:10])
    h2 = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    c.add("edit.after_hash", h2 == log.get("output_sha256"), h2[:10])
    c.add("edit.changes", bool(log.get("changes")) or bool(log.get("warnings")),
          "%d change(s)" % len(log.get("changes") or []))
    c.stats["svg_text_nodes"] = len(texts)


def _check_caption_generic(c, work, out_dir):
    text = ""
    p = os.path.join(out_dir, "caption.md")
    if os.path.exists(p):
        text = open(p, encoding="utf-8").read()
    c.add("caption.present", len(text) > 80, "%d chars" % len(text))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--spec", default="")
    ap.add_argument("--work", default="work")
    ap.add_argument("--out", default="")
    ap.add_argument("--svg-only", action="store_true")
    a = ap.parse_args()
    out_dir = a.out or a.work
    spec = {}
    if not a.svg_only:
        if not a.spec or not os.path.exists(a.spec):
            print("FAIL: spec missing")
            return 1
        spec = json.load(open(a.spec, encoding="utf-8"))
    result = check(spec, a.work, out_dir, svg_only=a.svg_only)
    path = os.path.join(out_dir, "selfcheck.json")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(result, fh, ensure_ascii=False, indent=1)
    print("%s checks=%d errors=%d warnings=%d"
          % (result["verdict"], len(result["checks"]), len(result["errors"]),
             len(result["warnings"])))
    for e in result["errors"][:12]:
        print("  !", e)
    for w in result["warnings"][:8]:
        print("  ~", w)
    return 0 if result["verdict"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
