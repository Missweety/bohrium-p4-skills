#!/usr/bin/env python3
"""svg_render.py - dependency-free SVG renderer (stdlib only).

Implements every chart type used by build_spec (bar, grouped bar, line, scatter,
histogram, box plot, heatmap, multi-panel grid) directly as SVG elements. Text stays
as real <text>/<tspan> nodes in the chosen serif/sans stack including CJK families, so
labels remain selectable, searchable, editable and never become outlined paths.

This is the fallback when matplotlib is missing: no PNG/PDF is invented, the result is
marked partial (rasterisation needs a converter, see render_figure.py / run_case.py).

Usage: python3 scripts/svg_render.py --spec work/chart_spec.json --out work
"""
import argparse
import html
import json
import math
import os
import re

from labels import (ACCENT, OKABE, VIRIDIS, choose_rotation, fmt_label, fmt_num,
                    text_width_px, viridis_index, wrap_label)

FONT = ("'Noto Sans CJK SC','PingFang SC','Microsoft YaHei','Source Han Sans SC',"
        "'WenQuanYi Zen Hei','Hiragino Sans GB',Arial,Helvetica,sans-serif")


def esc(s):
    return html.escape(str(s), quote=True)


def _san(s):
    return re.sub(r"[^A-Za-z0-9_\-]", "_", str(s))[:60]


class Svg:
    def __init__(self, w, h):
        self.w, self.h = w, h
        self.parts = []

    def add(self, s):
        self.parts.append(s)

    def text(self, x, y, s, size=10, anchor="start", fill="#222222", weight="normal",
             rotate=None, eid=None, opacity=None, family=FONT):
        attrs = ['x="%.2f"' % x, 'y="%.2f"' % y, 'font-size="%s"' % size,
                 'font-family="%s"' % family, 'text-anchor="%s"' % anchor,
                 'fill="%s"' % fill]
        if weight != "normal":
            attrs.append('font-weight="%s"' % weight)
        if rotate:
            attrs.append('transform="rotate(%.1f %.2f %.2f)"' % (rotate, x, y))
        if eid:
            attrs.append('id="%s"' % _san(eid))
        if opacity is not None:
            attrs.append('opacity="%s"' % opacity)
        self.add("<text %s>%s</text>" % (" ".join(attrs), esc(s)))

    def multiline(self, x, y, lines, size=9.5, anchor="middle", fill="#222222",
                  rotate=None, eid=None, line_height=None):
        lh = line_height or (size + 1.6)
        attrs = ['x="%.2f"' % x, 'y="%.2f"' % y, 'font-size="%s"' % size,
                 'font-family="%s"' % FONT, 'text-anchor="%s"' % anchor,
                 'fill="%s"' % fill]
        if rotate:
            attrs.append('transform="rotate(%.1f %.2f %.2f)"' % (rotate, x, y))
        if eid:
            attrs.append('id="%s"' % _san(eid))
        spans = []
        for k, ln in enumerate(lines):
            spans.append('<tspan x="%.2f" dy="%s">%s</tspan>'
                         % (x, "0" if k == 0 else "%.1f" % lh, esc(ln)))
        self.add("<text %s>%s</text>" % (" ".join(attrs), "".join(spans)))


def _scale(v, lo, hi, p0, p1):
    if hi == lo:
        hi = lo + 1
    v = min(max(v, min(lo, hi)), max(lo, hi))
    return p0 + (v - lo) / (hi - lo) * (p1 - p0)


def _nice_line(x1, y1, x2, y2, color="#555555", width=1):
    return ('<line x1="%.2f" y1="%.2f" x2="%.2f" y2="%.2f" stroke="%s" '
            'stroke-width="%s"/>' % (x1, y1, x2, y2, color, width))


class Renderer:
    def __init__(self, spec):
        self.spec = spec
        self.style = spec["style"]
        self.W = max(int(round(self.style["width_in"] * 96)), 420)
        self.H = max(int(round(self.style["height_in"] * 96)), 300)
        self.svg = Svg(self.W, self.H)
        self.warnings = []
        self.text_count = 0

    # ------------------------------------------------------------------ helpers
    def _notes(self):
        notes = []
        for p in self.spec.get("panels", []):
            for a in p.get("annotations", []):
                if a.get("place") == "figure_note":
                    notes.append("[%s] %s" % (p.get("id"), a.get("text")))
        for a in self.spec.get("annotations", []):
            notes.append(a.get("text", ""))
        return notes

    def _wrapped_notes(self, width_chars):
        notes = self._notes()
        if not notes:
            return []
        text = "  |  ".join(notes[:4])
        if len(notes) > 4:
            text += "  (+%d more in caption.md)" % (len(notes) - 4)
        lines = wrap_label(text, width=width_chars, max_lines=8)
        return lines

    def build(self):
        self.svg.add(
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            '<svg xmlns="http://www.w3.org/2000/svg" width="%d" height="%d" '
            'viewBox="0 0 %d %d" role="img" aria-label="%s">'
            % (self.W, self.H, self.W, self.H, esc(self.spec.get("title", "figure"))))
        self.svg.add('<title>%s</title>' % esc(self.spec.get("title", "figure")))
        self.svg.add('<rect x="0" y="0" width="%d" height="%d" fill="#FFFFFF"/>'
                     % (self.W, self.H))
        note_lines = self._wrapped_notes(max(60, int(self.W / 6.4)))
        note_h = (len(note_lines) * 10 + 14) if note_lines else 0
        top_reserve = 26 if len(self.spec["panels"]) > 1 else 0
        if len(self.spec["panels"]) > 1:
            self.svg.text(10, 19, self.spec["title"], size=13.5, weight="600",
                          eid="fig_title")
            self.text_count += 1
        body = (12, top_reserve + 6, self.W - 24,
                self.H - top_reserve - note_h - 12)
        panels = self.spec["panels"]
        if len(panels) == 1:
            self._panel(panels[0], (8, 8, self.W - 16, self.H - note_h - 18), len(panels))
        else:
            cols = 2 if len(panels) > 2 else 2
            rows = int(math.ceil(len(panels) / cols))
            gap_x, gap_y = 18, 14
            cw = (body[2] - gap_x * (cols - 1)) / cols
            ch = (self.H - top_reserve - note_h - 16) / rows
            for k, p in enumerate(panels):
                x = body[0] + (k % cols) * (cw + gap_x)
                y = top_reserve + 6 + (k // cols) * (ch + gap_y)
                self._panel(p, (x, y, cw, ch - gap_y + 4), len(panels))
        if note_lines:
            y = self.H - note_h + 4
            for ln in note_lines:
                self.svg.text(8, y, ln, size=8, fill="#555555")
                self.text_count += 1
                y += 10
        self.svg.add("</svg>")
        return "\n".join(self.svg.parts), self.warnings

    # ------------------------------------------------------------------ panel
    def _panel(self, p, cell, npanels):
        x, y, w, h = cell
        pid = p.get("id", "A")
        self.svg.add('<g id="panel_%s" transform="translate(%.2f,%.2f)">'
                     % (_san(pid), x, y))
        ct = p["chart_type"]
        left = 62
        right = 30
        if ct == "heatmap":
            row_max = max([text_width_px(str(r), 9) for r in p.get("row_labels", [])] or [40])
            left = int(min(max(84, min(row_max, w * 0.30) + 16), w * 0.40))
            right = 108
        top = 26
        cats = p.get("categories") or [b["label"] for b in p.get("boxes", [])]
        if ct == "heatmap":
            cats = p.get("col_labels", [])
        wrap_w = 14
        band = max((w - left - right) / max(len(cats), 1), 4)
        if band < 44:
            wrap_w = 9
        if band < 26:
            wrap_w = 6
        wrapped = [wrap_label(c, width=wrap_w, max_lines=3) for c in cats]
        max_lines = max([len(x) for x in wrapped] or [1])
        font_tick = 9.5
        rot = choose_rotation([str(c) for c in cats], band, font_tick)
        max_txt_w = max([text_width_px(str(c), font_tick) for c in cats] or [10])
        if ct == "heatmap":
            rot = 30 if max([len(str(c)) for c in cats] or [0]) > 7 else 0
        bottom = 30 + (max_lines - 1) * 10 + (math.sin(math.radians(rot)) * max_txt_w
                                              if rot else 0)
        if ct in ("scatter", "hist", "heatmap"):
            bottom = max(bottom, 42)
        bottom = min(bottom, max(36, h * 0.46))
        plot = (left, top, max(w - left - right, 40), max(h - top - bottom, 60))
        if p.get("title") and npanels > 1:
            self.svg.text(left, 15, p.get("title", ""), size=11.2, weight="600",
                          eid="panel_%s__title" % pid)
            self.text_count += 1
        elif npanels == 1:
            tsize = 13.2 if text_width_px(self.spec.get("title", ""), 13.2) < w - 20 else 10.5
            self.svg.text(2, 16, self.spec.get("title", ""), size=tsize, weight="600",
                          eid="fig_title")
            self.text_count += 1
        axis = p.get("axis", {})
        if ct == "heatmap":
            self._heatmap(p, plot, pid)
        else:
            yax = axis.get("y", {})
            if yax.get("kind") == "numeric":
                self._y_axis(plot, yax, pid)
            if ct in ("bar", "grouped_bar"):
                self._bar(p, plot, pid, band, wrapped, rot)
            elif ct == "line":
                self._line(p, plot, pid, band, wrapped, rot)
            elif ct == "scatter":
                self._scatter(p, plot, pid)
            elif ct == "hist":
                self._hist(p, plot, pid)
            elif ct == "box":
                self._box(p, plot, pid, band, wrapped, rot)
            self._axis_titles(p, plot, pid, bottom)
        if p.get("legend", {}).get("show"):
            self._legend(plot, p["legend"]["items"], pid)
        for ann in p.get("annotations", []):
            if ann.get("place") == "plot":
                lines = wrap_label(ann.get("text", ""), 55, 4)
                for k, ln in enumerate(lines):
                    self.svg.text(plot[0] + 6, plot[1] + 12 + k * 10, ln, size=8,
                                  fill="#444444", eid="panel_%s_plotnote_%d" % (pid, k))
                    self.text_count += 1
        self.svg.add("</g>")

    # ------------------------------------------------------------------ axes
    def _y_axis(self, plot, yax, pid):
        x0, y0, w, h = plot
        lo, hi = yax.get("min"), yax.get("max")
        ticks = yax.get("ticks", [])
        for t in ticks:
            yy = _scale(t, lo, hi, y0 + h, y0)
            self.svg.add(_nice_line(x0, yy, x0 + w, yy, "#E8E8E8", 0.8))
            self.svg.text(x0 - 6, yy + 3.2, fmt_num(t), size=9.2, anchor="end",
                          fill="#333333")
            self.text_count += 1
        self.svg.add(_nice_line(x0, y0, x0, y0 + h, "#555555", 1))
        self.svg.add(_nice_line(x0, y0 + h, x0 + w, y0 + h, "#555555", 1))

    def _axis_titles(self, p, plot, pid, bottom):
        x0, y0, w, h = plot
        ax = p.get("axis", {})
        if ax.get("x", {}).get("label"):
            self.svg.text(x0 + w / 2, y0 + h + bottom - 6, ax["x"]["label"], size=10,
                          anchor="middle", eid="panel_%s__axis_x" % pid)
            self.text_count += 1
        if ax.get("y", {}).get("label"):
            cy = y0 + h / 2
            self.svg.text(12, cy, ax["y"]["label"], size=10, anchor="middle",
                          rotate=-90, eid="panel_%s__axis_y" % pid)
            self.text_count += 1

    def _x_cats(self, plot, cats, wrapped, rot, pid):
        x0, y0, w, h = plot
        n = max(len(cats), 1)
        band = w / n
        step = 1
        if n > 22:
            step = int(math.ceil(n / 22.0))
        for i, lines in enumerate(wrapped):
            if i % step:
                continue
            cx = x0 + band * (i + 0.5)
            if rot:
                self.svg.multiline(cx, y0 + h + 11, lines, size=9.2, anchor="end",
                                   rotate=-rot, eid="panel_%s__cat_%d" % (pid, i))
            else:
                self.svg.multiline(cx, y0 + h + 12, lines, size=9.2, anchor="middle",
                                   eid="panel_%s__cat_%d" % (pid, i))
            self.text_count += 1

    # ------------------------------------------------------------------ charts
    def _bar(self, p, plot, pid, band, wrapped, rot):
        x0, y0, w, h = plot
        cats = [str(c) for c in p["categories"]]
        axis = p["axis"]["y"]
        lo, hi = axis["min"], axis["max"]
        base = _scale(0, lo, hi, y0 + h, y0)
        ns = max(len(p["series"]), 1)
        total = 0.78 if ns > 1 else 0.66
        bw = band * total / ns
        show_vals = len(cats) * ns <= 18
        for si, s in enumerate(p["series"]):
            vals = {v["label"]: v for v in s["values"]}
            for ci, cat in enumerate(cats):
                if cat not in vals:
                    continue
                v = vals[cat]
                cx = x0 + band * (ci + 0.5)
                if ns > 1:
                    cx = cx - band * total / 2 + bw * (si + 0.5)
                top = _scale(v["value"], lo, hi, y0 + h, y0)
                rect_y = min(top, base)
                rect_h = max(abs(base - top), 0.8)
                eid = "panel_%s__bar_%d_%d" % (_san(pid), si, ci)
                self.svg.add('<rect id="%s" data-label="%s" x="%.2f" y="%.2f" '
                             'width="%.2f" height="%.2f" fill="%s"/>'
                             % (eid, esc(cat), cx - bw * 0.46, rect_y, bw * 0.92,
                                rect_h, s["color"]))
                if v.get("error"):
                    e = v["error"]
                    yt = _scale(v["value"] + e, lo, hi, y0 + h, y0)
                    yb = _scale(v["value"] - e, lo, hi, y0 + h, y0)
                    self.svg.add(_nice_line(cx, yt, cx, yb, "#333333", 1))
                    self.svg.add(_nice_line(cx - 3, yt, cx + 3, yt, "#333333", 1))
                    self.svg.add(_nice_line(cx - 3, yb, cx + 3, yb, "#333333", 1))
                    top = yt
                if show_vals:
                    ly = top - 3 if v["value"] >= 0 else max(top, base) + 12
                    self.svg.text(cx, ly, fmt_label(v["value"]), size=7.6,
                                  anchor="middle", fill="#222222",
                                  eid="%s__value" % eid)
                    self.text_count += 1
        self._x_cats(plot, cats, wrapped, rot, pid)
        for hl in p.get("highlights", []):
            target = str(hl.get("target", ""))
            if target.startswith("bar:") or target.startswith("value:"):
                lab = target.split(":", 1)[1]
                for si, s in enumerate(p["series"]):
                    vals = {v["label"]: v for v in s["values"]}
                    for ci, cat in enumerate(cats):
                        if cat != lab or cat not in vals:
                            continue
                        cx = x0 + band * (ci + 0.5)
                        if ns > 1:
                            cx = cx - band * total / 2 + bw * (si + 0.5)
                        v = vals[cat]
                        top = _scale(v["value"], lo, hi, y0 + h, y0)
                        base = _scale(0, lo, hi, y0 + h, y0)
                        ry = min(top, base)
                        rh = max(abs(base - top), 1)
                        self.svg.add('<rect x="%.2f" y="%.2f" width="%.2f" '
                                     'height="%.2f" fill="none" stroke="%s" '
                                     'stroke-width="2" data-highlight="%s"/>'
                                     % (cx - bw * 0.5 - 2, ry - 2, bw + 4, rh + 4,
                                        hl.get("color", ACCENT), esc(lab)))

    def _line(self, p, plot, pid, band, wrapped, rot):
        x0, y0, w, h = plot
        cats = [str(c) for c in p["categories"]]
        pos = {c: i for i, c in enumerate(cats)}
        ax = p["axis"]["y"]
        lo, hi = ax["min"], ax["max"]
        for si, s in enumerate(p["series"]):
            pts = [pt for pt in p["points"] if pt.get("series") == s["label"]]
            if not pts:
                continue
            coords = []
            for pt in pts:
                cx = x0 + band * (pos[pt["x"]] + 0.5)
                cy = _scale(pt["y"], lo, hi, y0 + h, y0)
                coords.append((cx, cy, pt))
                if pt.get("error"):
                    e = pt["error"]
                    yt = _scale(pt["y"] + e, lo, hi, y0 + h, y0)
                    yb = _scale(pt["y"] - e, lo, hi, y0 + h, y0)
                    self.svg.add(_nice_line(cx, yt, cx, yb, "#333333", 1))
                    self.svg.add(_nice_line(cx - 2.5, yt, cx + 2.5, yt, "#333333", 1))
            self.svg.add('<polyline points="%s" fill="none" stroke="%s" '
                         'stroke-width="1.6" stroke-linejoin="round"/>'
                         % (" ".join("%.2f,%.2f" % (cx, cy) for cx, cy, _ in coords),
                            s["color"]))
            for k, (cx, cy, pt) in enumerate(coords):
                self.svg.add('<circle id="panel_%s__point_%d" cx="%.2f" cy="%.2f" '
                             'r="2.8" fill="%s" stroke="#FFFFFF" stroke-width="0.8"/>'
                             % (_san(pid), k, cx, cy, s["color"]))
        self._x_cats(plot, cats, wrapped, rot, pid)

    def _scatter(self, p, plot, pid):
        x0, y0, w, h = plot
        ax, ay = p["axis"]["x"], p["axis"]["y"]
        self._xticks_numeric(plot, ax, pid)
        for s in p["series"]:
            pts = [pt for pt in p["points"] if pt.get("group") in ("", s["label"])]
            for k, pt in enumerate(pts):
                cx = _scale(pt["x"], ax["min"], ax["max"], x0, x0 + w)
                cy = _scale(pt["y"], ay["min"], ay["max"], y0 + h, y0)
                self.svg.add('<circle id="panel_%s__point_%s_%d" cx="%.2f" cy="%.2f" '
                             'r="3.2" fill="%s" stroke="#FFFFFF" stroke-width="0.7"/>'
                             % (_san(pid), _san(s["label"]), k, cx, cy, s["color"]))

    def _xticks_numeric(self, plot, ax, pid):
        x0, y0, w, h = plot
        for t in ax.get("ticks", []):
            xx = _scale(t, ax["min"], ax["max"], x0, x0 + w)
            self.svg.add(_nice_line(xx, y0 + h, xx, y0 + h + 3, "#555555", 1))
            self.svg.text(xx, y0 + h + 13, fmt_num(t), size=8.8, anchor="middle")
            self.text_count += 1

    def _hist(self, p, plot, pid):
        x0, y0, w, h = plot
        ax, ay = p["axis"]["x"], p["axis"]["y"]
        lo, hi = ax["min"], ax["max"]
        color = p["series"][0]["color"] if p["series"] else OKABE[0]
        for k, b in enumerate(p["bins"]):
            left = _scale(b["lo"], lo, hi, x0, x0 + w)
            right = _scale(b["hi"], lo, hi, x0, x0 + w)
            top = _scale(b["count"], ay["min"], ay["max"], y0 + h, y0)
            self.svg.add('<rect id="panel_%s__bin_%d" x="%.2f" y="%.2f" width="%.2f" '
                         'height="%.2f" fill="%s" stroke="#FFFFFF" stroke-width="0.8"/>'
                         % (_san(pid), k, left, top, max(right - left - 0.8, 0.6),
                            y0 + h - top, color))
            if b["count"]:
                self.svg.text((left + right) / 2, top - 3, str(b["count"]), size=7.6,
                              anchor="middle")
                self.text_count += 1
        self._xticks_numeric(plot, ax, pid)

    def _box(self, p, plot, pid, band, wrapped, rot):
        x0, y0, w, h = plot
        ay = p["axis"]["y"]
        lo, hi = ay["min"], ay["max"]
        color = p["series"][0]["color"] if p["series"] else OKABE[0]
        for bi, b in enumerate(p["boxes"]):
            cx = x0 + band * (bi + 0.5)
            bw = band * 0.5
            q1 = _scale(b["q1"], lo, hi, y0 + h, y0)
            q3 = _scale(b["q3"], lo, hi, y0 + h, y0)
            med = _scale(b["median"], lo, hi, y0 + h, y0)
            top = _scale(b["max"], lo, hi, y0 + h, y0)
            bot = _scale(b["min"], lo, hi, y0 + h, y0)
            self.svg.add('<rect id="panel_%s__box_%d" x="%.2f" y="%.2f" width="%.2f" '
                         'height="%.2f" fill="%s" fill-opacity="0.55" stroke="#333333" '
                         'stroke-width="1"/>'
                         % (_san(pid), bi, cx - bw / 2, q3, bw, max(q1 - q3, 1), color))
            self.svg.add(_nice_line(cx, top, cx, bot, "#333333", 1))
            self.svg.add(_nice_line(cx - bw / 4, top, cx + bw / 4, top, "#333333", 1))
            self.svg.add(_nice_line(cx - bw / 4, bot, cx + bw / 4, bot, "#333333", 1))
            self.svg.add(_nice_line(cx - bw / 2, med, cx + bw / 2, med, "#222222", 1.6))
            for o in b.get("outliers", []):
                oy = _scale(o["value"], lo, hi, y0 + h, y0)
                self.svg.add('<circle cx="%.2f" cy="%.2f" r="2.4" fill="#FFFFFF" '
                             'stroke="#333333" stroke-width="0.8"/>' % (cx, oy))
            self.svg.text(cx, top - 4, "n=%s" % (b.get("n") if b.get("n") is not None
                                                 else "?"), size=7.2, anchor="middle",
                          fill="#555555")
            self.text_count += 1
        self._x_cats(plot, [b["label"] for b in p["boxes"]], wrapped, rot, pid)

    def _heatmap(self, p, plot, pid):
        x0, y0, w, h = plot
        rows = [str(r) for r in p["row_labels"]]
        cols = [str(c) for c in p["col_labels"]]
        if not rows or not cols:
            return
        cs = p["color_scale"]
        lo, hi = cs["min"], cs["max"]
        cw, ch = w / len(cols), h / len(rows)
        ridx = {r: i for i, r in enumerate(rows)}
        cidx = {c: i for i, c in enumerate(cols)}
        by = {(c["row_label"], c["col_label"]): c for c in p["cells"]}
        show_vals = len(rows) * len(cols) <= 120
        for ri, rl in enumerate(rows):
            for ci, cl in enumerate(cols):
                cell = by.get((rl, cl))
                x = x0 + ci * cw
                y = y0 + ri * ch
                if cell is None:
                    self.svg.add('<rect x="%.2f" y="%.2f" width="%.2f" height="%.2f" '
                                 'fill="#FFFFFF" stroke="#DDDDDD" stroke-width="0.6"/>'
                                 % (x, y, cw, ch))
                    continue
                idx = viridis_index(cell["value"], lo, hi)
                color = VIRIDIS[idx]
                self.svg.add('<rect id="panel_%s__cell_%d_%d" x="%.2f" y="%.2f" '
                             'width="%.2f" height="%.2f" fill="%s" stroke="#FFFFFF" '
                             'stroke-width="0.6"/>'
                             % (_san(pid), ri, ci, x, y, cw, ch, color))
                if show_vals and cw > 20 and ch > 10:
                    lum = _lum(color)
                    self.svg.text(x + cw / 2, y + ch / 2 + 3, fmt_label(cell["value"]),
                                  size=7.2, anchor="middle",
                                  fill="#FFFFFF" if lum < 0.5 else "#111111")
                    self.text_count += 1
        for ci, cl in enumerate(cols):
            cx = x0 + cw * (ci + 0.5)
            lines = wrap_label(cl, width=max(int(cw / 5.2), 4), max_lines=3)
            rot = 30 if len(cl) > 7 else 0
            self.svg.multiline(cx, y0 + h + 12, lines, size=8.6,
                               anchor="end" if rot else "middle", rotate=-rot if rot else None,
                               eid="panel_%s__col_%d" % (pid, ci))
            self.text_count += 1
        step = max(1, int(math.ceil(len(rows) / 26.0)))
        row_wrap = max(int((x0 - 14) / 5.4), 6)
        for ri, rl in enumerate(rows):
            if ri % step:
                continue
            lines = wrap_label(rl, width=row_wrap, max_lines=2)
            self.svg.multiline(x0 - 6, y0 + ch * (ri + 0.5) - ((len(lines) - 1) * 5.2) + 3,
                               lines, size=8.6, anchor="end")
            self.text_count += 1
        self.svg.text(x0 + w / 2, y0 + h + 34, p["axis"]["x"].get("label", ""), size=10,
                      anchor="middle", eid="panel_%s__axis_x" % pid)
        self.svg.text(12, y0 + h / 2, p["axis"]["y"].get("label", ""), size=10,
                      anchor="middle", rotate=-90, eid="panel_%s__axis_y" % pid)
        self.text_count += 2
        # discrete colour scale legend
        lx = x0 + w + 14
        bh = h / 10.0
        for k in range(10):
            self.svg.add('<rect x="%.2f" y="%.2f" width="13" height="%.2f" fill="%s"/>'
                         % (lx, y0 + k * bh, bh + 0.4, VIRIDIS[9 - k]))
        self.svg.text(lx + 20, y0 + 8, fmt_label(hi), size=8.2)
        self.svg.text(lx + 20, y0 + h, fmt_label(lo), size=8.2)
        mid = (hi + lo) / 2.0
        self.svg.text(lx + 20, y0 + h / 2 + 3, fmt_label(mid), size=8.2)
        self.svg.text(lx + 40, y0 + h / 2, p["axis"]["color"].get("label", "value"),
                      size=8.6, anchor="middle", rotate=-90,
                      eid="panel_%s__axis_color" % pid)
        self.text_count += 4
        self.svg.add(_nice_line(x0, y0, x0 + w, y0, "#555555", 0.6))
        self.svg.add(_nice_line(x0, y0 + h, x0 + w, y0 + h, "#555555", 0.6))

    # ------------------------------------------------------------------ legend
    def _legend(self, plot, items, pid):
        x0, y0, w, h = plot
        fs = 9.0
        widths = [text_width_px(it.get("label", ""), fs) for it in items]
        lw = max(widths or [40]) + 26
        lh = 13 * len(items) + 8
        bx = x0 + w - lw - 4
        by = y0 + 4
        if bx < x0 + 4:
            bx = x0 + 4
        self.svg.add('<rect x="%.2f" y="%.2f" width="%.2f" height="%.2f" fill="#FFFFFF" '
                     'fill-opacity="0.9" stroke="#DDDDDD" stroke-width="0.6"/>'
                     % (bx, by, lw, lh))
        for k, it in enumerate(items):
            y = by + 12 + k * 13
            color = it.get("color", OKABE[0])
            sw = it.get("swatch")
            if sw == "bar":
                self.svg.add('<rect x="%.2f" y="%.2f" width="9" height="9" fill="%s"/>'
                             % (bx + 5, y - 8, color))
            elif sw == "line":
                self.svg.add(_nice_line(bx + 3, y - 3.5, bx + 16, y - 3.5, color, 1.6))
                self.svg.add('<circle cx="%.2f" cy="%.2f" r="2.2" fill="%s"/>'
                             % (bx + 9.5, y - 3.5, color))
            else:
                self.svg.add('<circle cx="%.2f" cy="%.2f" r="3" fill="%s"/>'
                             % (bx + 9, y - 3.5, color))
            self.svg.text(bx + 20, y, it.get("label", ""), size=fs,
                          eid="panel_%s__legend_%d" % (pid, k))
            self.text_count += 1

    def write(self, path):
        content, warnings = self.build()
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(content)
        return {"renderer": "stdlib-svg", "svg_text_nodes": self.text_count + 1,
                "svg_bytes": os.path.getsize(path), "warnings": warnings,
                "cjk_text": self.style.get("cjk", False)}


def _lum(hex_color):
    h = hex_color.lstrip("#")
    r, g, b = (int(h[i:i + 2], 16) / 255.0 for i in (0, 2, 4))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def render(spec, out_dir):
    os.makedirs(out_dir, exist_ok=True)
    r = Renderer(spec)
    path = os.path.join(out_dir, "figure.svg")
    meta = r.write(path)
    with open(os.path.join(out_dir, "render_meta.json"), "w", encoding="utf-8") as fh:
        json.dump(meta, fh, ensure_ascii=False, indent=1)
    return {"svg": path}, meta


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--spec", required=True)
    ap.add_argument("--out", default="work")
    a = ap.parse_args()
    spec = json.load(open(a.spec, encoding="utf-8"))
    paths, meta = render(spec, a.out)
    print("renderer=stdlib-svg svg=%s text_nodes=%d bytes=%d"
          % (paths["svg"], meta["svg_text_nodes"], meta["svg_bytes"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
