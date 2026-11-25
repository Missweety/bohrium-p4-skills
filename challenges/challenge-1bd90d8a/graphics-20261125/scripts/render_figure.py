#!/usr/bin/env python3
"""render_figure.py - publication-style rendering from chart_spec.json.

Primary renderer: matplotlib (PNG 300 dpi + PDF + SVG with live <text>, not paths).
If matplotlib is unavailable, the caller falls back to svg_render.py (stdlib) and the
result is marked partial; this file never fabricates PNG/PDF.

Every chart type from build_spec is supported: bar, grouped bar, line, scatter,
histogram, box plot, heatmap and multi-panel grids. Axis limits/ticks come from the
spec; labels are wrapped and rotated based on measured band width so they do not
collide. CJK text is kept as text: if no CJK font exists the figure carries a visible
warning and render_meta records it instead of silently drawing replacement boxes.

Usage: python3 scripts/render_figure.py --spec work/chart_spec.json --out work [--formats svg,png,pdf]
"""
import argparse
import json
import math
import os
import re
import struct
import textwrap

import elements
from labels import (ACCENT, OKABE, VIRIDIS, choose_rotation, fmt_label, fmt_num,
                    has_cjk, text_width_px, viridis_index, wrap_label)

CJK_FONT_CANDIDATES = [
    "Noto Sans CJK SC", "Noto Sans CJK JP", "Noto Sans SC", "Source Han Sans SC",
    "Source Han Sans CN", "WenQuanYi Zen Hei", "WenQuanYi Micro Hei", "PingFang SC",
    "Hiragino Sans GB", "Heiti SC", "STHeiti", "SimHei", "Microsoft YaHei",
    "Arial Unicode MS", "Songti SC", "Noto Serif CJK SC",
]


def _luminance(hex_color):
    h = hex_color.lstrip("#")
    r, g, b = (int(h[i:i + 2], 16) / 255.0 for i in (0, 2, 4))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def _setup():
    os.environ.setdefault("SOURCE_DATE_EPOCH", "0")
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib import font_manager
    matplotlib.rcParams.update({
        "svg.fonttype": "none",
        "svg.hashsalt": "source-traced-figure",
        "pdf.fonttype": 42,
        "font.size": 8.5,
        "axes.linewidth": 0.8,
        "axes.edgecolor": "#444444",
        "axes.labelcolor": "#222222",
        "xtick.color": "#333333",
        "ytick.color": "#333333",
        "text.color": "#222222",
        "axes.grid": False,
        "figure.facecolor": "white",
        "savefig.facecolor": "white",
        "axes.unicode_minus": False,
        "path.simplify": False,
    })
    available = {f.name for f in font_manager.fontManager.ttflist}
    found = next((c for c in CJK_FONT_CANDIDATES if c in available), "")
    family = [found] if found else []
    family += ["DejaVu Sans", "Arial", "Helvetica", "sans-serif"]
    matplotlib.rcParams["font.sans-serif"] = family
    matplotlib.rcParams["font.family"] = "sans-serif"
    return plt, found, matplotlib


def _prepare_axes(ax, panel, spec):
    ax.set_axisbelow(True)
    ax.grid(axis="y", color="#E6E6E6", linewidth=0.6, zorder=0)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    ax.spines["left"].set_color("#555555")
    ax.spines["bottom"].set_color("#555555")
    ax.tick_params(labelsize=7.6, length=3, width=0.7, pad=2)


def _set_y(ax, axis):
    ax.set_ylim(axis["min"], axis["max"])
    ax.set_yticks(axis["ticks"])
    ax.set_yticklabels([fmt_num(t) for t in axis["ticks"]])


def _category_ticks(ax, labels, axis_width_in, font_pt=7.6, max_show=22):
    labels = [str(x) for x in labels]
    if not labels:
        return 0
    band_px = axis_width_in * 96.0 / max(len(labels), 1)
    font_px = font_pt * 96.0 / 72.0
    longest = max([text_width_px(x, font_px) for x in labels] or [1])
    rot = choose_rotation(labels, band_px, font_px)
    if rot == 0 and longest > band_px - 2:
        rot = 30
    # a vertical label can use the free figure height, so wrap wider and allow more
    # lines instead of cutting the category name off with an ellipsis.
    width = 14
    max_lines = 3
    if band_px < 46:
        width = 9
    if band_px < 30:
        width = 6
    if rot == 90:
        width, max_lines = 20, 5
    elif rot:
        width, max_lines = 18, 4
    wrapped = ["\n".join(wrap_label(x, width=width, max_lines=max_lines))
               for x in labels]
    step = 1
    if len(labels) > max_show:
        step = int(math.ceil(len(labels) / float(max_show)))
    positions = list(range(len(labels)))
    ax.set_xticks(positions)
    shown = [wrapped[i] if i % step == 0 else "" for i in positions]
    ax.set_xticklabels(shown, rotation=rot,
                       ha="right" if rot else "center", va="top" if rot else "top",
                       rotation_mode="anchor")
    return rot


def _bar_labels(ax, rects, values, axis, fontsize=6.6):
    span = axis["max"] - axis["min"]
    for rect, v in zip(rects, values):
        if v.get("value") is None:
            continue
        err = v.get("error") or 0
        if v["value"] < 0:
            # a negative bar hangs below zero: its label belongs under the bar,
            # otherwise it is printed on top of the bar and cannot be read
            top = v["value"] - err - (0.015 * span)
            va = "top"
        else:
            top = v["value"] + err + (0.015 * span)
            va = "bottom"
        ax.text(rect.get_x() + rect.get_width() / 2.0, top, fmt_label(v["value"]),
                ha="center", va=va, fontsize=fontsize, color="#222222",
                zorder=6)


def _error_lines(ax, xs, ys, es, cap=0.09):
    """Error bars drawn as plain grey lines so no library default colour leaks in."""
    lo = [y - e for y, e in zip(ys, es)]
    hi = [y + e for y, e in zip(ys, es)]
    ax.vlines(xs, lo, hi, color="#333333", linewidth=0.9, zorder=4)
    ax.hlines(lo, [x - cap for x in xs], [x + cap for x in xs],
              color="#333333", linewidth=0.9, zorder=4)
    ax.hlines(hi, [x - cap for x in xs], [x + cap for x in xs],
              color="#333333", linewidth=0.9, zorder=4)


def _draw_bar(ax, panel, spec, width_in):
    cats = [str(c) for c in panel["categories"]]
    series = panel["series"]
    axis = panel["axis"]
    _set_y(ax, axis["y"])
    n = len(cats)
    ns = max(len(series), 1)
    total = 0.78 if ns > 1 else 0.66
    bw = total / ns
    lookups = []
    show_vals = n * ns <= 18
    for si, s in enumerate(series):
        vals = {v["label"]: v for v in s["values"]}
        xs, ys, es = [], [], []
        for ci, cat in enumerate(cats):
            if cat not in vals:
                continue
            if ns > 1:
                x = ci - total / 2.0 + bw / 2.0 + si * bw
            else:
                x = ci
            v = vals[cat]
            xs.append(x)
            ys.append(v["value"])
            es.append(v.get("error") or 0)
        if not xs:
            continue
        rects = ax.bar(xs, ys, width=bw * 0.92, color=s["color"], edgecolor="white",
                       linewidth=0.6, zorder=3, label=s["label"])
        if any(e > 0 for e in es):
            _error_lines(ax, xs, ys, es)
        if show_vals:
            _bar_labels(ax, rects, [vals[c] for c in cats if c in vals], axis["y"])
        for rect, cat in zip(rects, [c for c in cats if c in vals]):
            lookups.append((si, cat, rect))
    _category_ticks(ax, cats, width_in)
    ax.set_xlabel(axis["x"]["label"], fontsize=8.6, labelpad=3)
    ax.set_ylabel(axis["y"]["label"], fontsize=8.6, labelpad=3)
    if panel.get("legend", {}).get("show"):
        ax.legend(fontsize=7.0, frameon=True, framealpha=0.92, edgecolor="#DDDDDD",
                  ncol=min(3, ns), loc="best", handlelength=1.1, columnspacing=1.0,
                  borderpad=0.3)
    _draw_highlights(ax, panel, lookups, axis)


def _draw_highlights(ax, panel, lookups, axis):
    for hl in panel.get("highlights", []):
        target = str(hl.get("target", ""))
        for si, cat, rect in lookups:
            if target in (cat, "bar:%s" % cat, "bar:%d|%s" % (si, cat),
                          "value:%s" % cat, "category:%s" % cat):
                pad = rect.get_width() * 0.08
                base = min(0.0, rect.get_height())
                height = abs(rect.get_height())
                ax.add_patch(_rect(rect.get_x() - pad, base, rect.get_width() + 2 * pad,
                                   height, edgecolor=hl.get("color", ACCENT), width=1.7,
                                   zorder=5))
                ax.annotate(hl.get("note") or "highlight",
                            xy=(rect.get_x() + rect.get_width() / 2.0,
                                rect.get_y() + rect.get_height()),
                            xytext=(0, 6), textcoords="offset points", ha="center",
                            fontsize=6.2, color=hl.get("color", ACCENT), zorder=6)


def _rect(x, y, w, h, edgecolor, width, zorder):
    from matplotlib.patches import Rectangle
    return Rectangle((x, y), w, h, fill=False, edgecolor=edgecolor, linewidth=width,
                     zorder=zorder)


def _draw_line(ax, panel, spec, width_in):
    axis = panel["axis"]
    _set_y(ax, axis["y"])
    cats = [str(c) for c in panel["categories"]]
    positions = {c: i for i, c in enumerate(cats)}
    s_by_label = {s["label"]: s for s in panel["series"]}
    for si, s in enumerate(panel["series"]):
        pts = [p for p in panel["points"] if p.get("series") == s["label"]]
        if not pts:
            continue
        xs = [positions[p["x"]] for p in pts]
        ys = [p["y"] for p in pts]
        es = [p.get("error") or 0 for p in pts]
        ax.plot(xs, ys, color=s["color"], linewidth=1.5, marker="o", markersize=3.6,
                markeredgecolor="white", markeredgewidth=0.7, zorder=3,
                label=s["label"] if len(panel["series"]) > 1 else None)
        if any(e > 0 for e in es):
            _error_lines(ax, xs, ys, es)
    _category_ticks(ax, cats, width_in)
    ax.set_xlabel(axis["x"]["label"], fontsize=8.6, labelpad=3)
    ax.set_ylabel(axis["y"]["label"], fontsize=8.6, labelpad=3)
    if panel.get("legend", {}).get("show"):
        ax.legend(fontsize=7.2, frameon=False, loc="upper left",
                  bbox_to_anchor=(0.0, 1.02), handlelength=1.3)


def _draw_scatter(ax, panel, spec, width_in):
    axis = panel["axis"]
    ax.set_xlim(axis["x"]["min"], axis["x"]["max"])
    ax.set_xticks(axis["x"]["ticks"])
    ax.set_xticklabels([fmt_num(t) for t in axis["x"]["ticks"]], fontsize=7.6)
    _set_y(ax, axis["y"])
    groups = [s for s in panel["series"]]
    for s in groups:
        pts = [p for p in panel["points"] if p.get("group") in ("", s["label"])]
        if not pts:
            continue
        ax.scatter([p["x"] for p in pts], [p["y"] for p in pts], s=17,
                   color=s["color"], edgecolors="white", linewidths=0.6, zorder=3,
                   label=s["label"] if panel.get("legend", {}).get("show") else None)
    ax.set_xlabel(axis["x"]["label"], fontsize=8.6, labelpad=3)
    ax.set_ylabel(axis["y"]["label"], fontsize=8.6, labelpad=3)
    if panel.get("legend", {}).get("show"):
        ax.legend(fontsize=7.2, frameon=False, loc="best", markerscale=1.4)


def _draw_hist(ax, panel, spec, width_in):
    axis = panel["axis"]
    _set_y(ax, axis["y"])
    ax.set_xlim(axis["x"]["min"], axis["x"]["max"])
    ax.set_xticks(axis["x"]["ticks"])
    ax.set_xticklabels([fmt_num(t) for t in axis["x"]["ticks"]], fontsize=7.6)
    color = panel["series"][0]["color"] if panel["series"] else OKABE[0]
    for b in panel["bins"]:
        width = b["hi"] - b["lo"]
        ax.bar(b["lo"], b["count"], width=width, align="edge", color=color,
               edgecolor="white", linewidth=0.6, zorder=3)
    if len(panel["bins"]) <= 10:
        for b in panel["bins"]:
            if b["count"]:
                ax.text(b["lo"] + (b["hi"] - b["lo"]) / 2.0, b["count"] + 0.15,
                        str(b["count"]), ha="center", va="bottom", fontsize=6.2,
                        color="#333333")
    ax.set_xlabel(axis["x"]["label"], fontsize=8.6, labelpad=3)
    ax.set_ylabel("Count", fontsize=8.6, labelpad=3)


def _draw_box(ax, panel, spec, width_in):
    axis = panel["axis"]
    _set_y(ax, axis["y"])
    stats = []
    for b in panel["boxes"]:
        stats.append({"label": str(b["label"]), "med": b["median"], "q1": b["q1"],
                      "q3": b["q3"], "whislo": b["min"], "whishi": b["max"],
                      "fliers": [o["value"] for o in b.get("outliers", [])]})
    color = panel["series"][0]["color"] if panel["series"] else OKABE[0]
    bp = ax.bxp(stats, showfliers=True, patch_artist=True, widths=0.55,
                boxprops={"facecolor": color, "alpha": 0.55, "edgecolor": "#333333",
                          "linewidth": 0.8},
                medianprops={"color": "#222222", "linewidth": 1.3},
                whiskerprops={"color": "#333333", "linewidth": 0.8},
                capprops={"color": "#333333", "linewidth": 0.8},
                flierprops={"marker": "o", "markersize": 3.2, "markerfacecolor": "white",
                            "markeredgecolor": "#333333", "markeredgewidth": 0.7,
                            "linestyle": "none"})
    _category_ticks(ax, [b["label"] for b in panel["boxes"]], width_in)
    ax.set_xlabel(axis["x"]["label"], fontsize=8.6, labelpad=3)
    ax.set_ylabel(axis["y"]["label"], fontsize=8.6, labelpad=3)
    for i, b in enumerate(panel["boxes"], start=1):
        ax.text(i, b["max"], "n=%s" % (b.get("n") if b.get("n") is not None else "?"),
                ha="center", va="bottom", fontsize=5.8, color="#555555")


def _draw_heatmap(ax, panel, spec, width_in):
    from matplotlib.colors import BoundaryNorm, ListedColormap
    row_labels = [str(x) for x in panel["row_labels"]]
    col_labels = [str(x) for x in panel["col_labels"]]
    cs = panel["color_scale"]
    lo, hi = cs["min"], cs["max"]
    grid = [[None] * len(col_labels) for _ in row_labels]
    ridx = {r: i for i, r in enumerate(row_labels)}
    cidx = {c: i for i, c in enumerate(col_labels)}
    for cell in panel["cells"]:
        if cell["row_label"] in ridx and cell["col_label"] in cidx:
            grid[ridx[cell["row_label"]]][cidx[cell["col_label"]]] = cell["value"]
    data = [[(float(v) if v is not None else float("nan")) for v in row] for row in grid]
    cmap = ListedColormap(VIRIDIS)
    bounds = [lo + (hi - lo) * k / 10.0 for k in range(11)]
    if hi <= lo:
        bounds = [lo - 0.5 + k / 10.0 for k in range(11)]
    norm = BoundaryNorm(bounds, cmap.N, clip=True)
    im = ax.imshow(data, cmap=cmap, norm=norm, aspect="auto", interpolation="nearest")
    ax.set_xticks(range(len(col_labels)))
    wrap_width = max(int(width_in * 96.0 / max(len(col_labels), 1) / 6.4), 5)
    ax.set_xticklabels(["\n".join(wrap_label(c, width=wrap_width, max_lines=3))
                        for c in col_labels], fontsize=7.2,
                       rotation=30 if max(len(c) for c in col_labels) > 8 else 0,
                       ha="right" if max(len(c) for c in col_labels) > 8 else "center")
    ax.set_yticks(range(len(row_labels)))
    max_show = 26
    step = max(1, int(math.ceil(len(row_labels) / float(max_show))))
    ax.set_yticklabels([row_labels[i] if i % step == 0 else ""
                        for i in range(len(row_labels))], fontsize=7.0)
    ax.grid(False)
    for side in ("top", "right", "left", "bottom"):
        ax.spines[side].set_visible(False)
    ax.tick_params(length=0)
    show_vals = len(row_labels) * len(col_labels) <= 120
    for r in range(len(row_labels)):
        for c in range(len(col_labels)):
            v = data[r][c]
            if v != v:  # NaN
                continue
            if show_vals:
                idx = viridis_index(v, lo, hi)
                txt = "#FFFFFF" if _luminance(VIRIDIS[idx]) < 0.5 else "#111111"
                ax.text(c, r, fmt_label(v), ha="center", va="center", fontsize=6.2,
                        color=txt)
    ax.set_xlabel(panel["axis"]["x"]["label"], fontsize=8.6, labelpad=4)
    ax.set_ylabel(panel["axis"]["y"]["label"], fontsize=8.6, labelpad=4)
    cbar = ax.figure.colorbar(im, ax=ax, fraction=0.045, pad=0.02, ticks=None)
    cbar.ax.tick_params(labelsize=6.8, length=2)
    _ticks = cbar.get_ticks()
    cbar.set_ticks(_ticks)
    cbar.set_ticklabels([fmt_label(t) for t in _ticks])
    cbar.set_label(panel["axis"]["color"]["label"], fontsize=7.6)
    cbar.outline.set_linewidth(0.5)


DRAW = {"bar": _draw_bar, "grouped_bar": _draw_bar, "line": _draw_line,
        "scatter": _draw_scatter, "hist": _draw_hist, "box": _draw_box,
        "heatmap": _draw_heatmap}


def _note_text(spec):
    notes = []
    for p in spec.get("panels", []):
        for a in p.get("annotations", []):
            if a.get("place") == "figure_note":
                notes.append("[%s] %s" % (p.get("id"), a.get("text")))
    for a in spec.get("annotations", []):
        notes.append(a.get("text", ""))
    return notes


def render(spec, out_dir, formats=("svg", "png", "pdf")):
    plt, cjk_font, _ = _setup()
    fig = plt.figure(figsize=(spec["style"]["width_in"], spec["style"]["height_in"]),
                     dpi=spec["style"]["dpi"])
    panels = spec["panels"]
    notes = _note_text(spec)
    note_block = []
    if notes:
        text = "  |  ".join(notes[:4])
        if len(notes) > 4:
            text += "  (+%d more in caption.md)" % (len(notes) - 4)
        note_block = textwrap.wrap(text, width=104)
        if len(note_block) > 6:
            note_block = note_block[:6]
            note_block[-1] += " …"
    bottom = 0.10 + 0.026 * len(note_block)
    if len(panels) > 1:
        cols = 2 if len(panels) > 2 else 2
        rows = int(math.ceil(len(panels) / cols))
        gs = fig.add_gridspec(rows, cols, left=0.075, right=0.975, top=0.90,
                              bottom=min(bottom, 0.34), hspace=0.62, wspace=0.30)
        fig.suptitle(spec["title"], fontsize=spec["style"]["title_pt"] + 0.5,
                     fontweight="normal", y=0.985)
        axes = []
        for k, p in enumerate(panels):
            ax = fig.add_subplot(gs[k // cols, k % cols])
            axes.append((ax, p))
    else:
        ax = fig.add_subplot(111)
        axes = [(ax, panels[0])]
        ax.set_title(spec["title"], fontsize=spec["style"]["title_pt"],
                     fontweight="normal", loc="left", pad=6)

    layout_ok = True
    for ax, p in axes:
        _prepare_axes(ax, p, spec)
        if len(panels) > 1:
            ax.set_title(p.get("title", ""), fontsize=spec["style"]["title_pt"] - 0.5,
                         fontweight="normal", loc="left", pad=5)
        DRAW[p["chart_type"]](ax, p, spec, spec["style"]["width_in"])
        for ann in p.get("annotations", []):
            if ann.get("place") == "plot":
                ax.text(0.02, 0.96, "\n".join(wrap_label(ann.get("text", ""), 60, 4)),
                        transform=ax.transAxes, ha="left", va="top", fontsize=6.0,
                        color="#444444", zorder=7)

    if len(panels) == 1:
        rect_top = 0.93
        fig.tight_layout(rect=(0.0, min(bottom, 0.30), 1.0, rect_top))
    else:
        try:
            fig.tight_layout(rect=(0.0, min(bottom, 0.34), 1.0, 0.965), h_pad=1.2,
                             w_pad=1.4)
        except Exception:  # noqa: BLE001
            layout_ok = False
    if note_block:
        fig.text(0.008, 0.008, "\n".join(note_block), fontsize=5.9, color="#555555",
                 ha="left", va="bottom", linespacing=1.25)
    if spec.get("style", {}).get("cjk") and not cjk_font:
        fig.text(0.992, 0.008, "WARNING: no CJK font installed; text kept in SVG source",
                 fontsize=5.5, color="#B00020", ha="right", va="bottom")

    os.makedirs(out_dir, exist_ok=True)
    paths = {}
    meta = {"renderer": "matplotlib", "cjk_font": cjk_font,
            "warnings": [], "formats": list(formats), "layout_ok": layout_ok}
    if spec.get("style", {}).get("cjk") and not cjk_font:
        meta["warnings"].append("cjk_font_missing: Chinese labels are kept as text in "
                                "SVG/PDF but may show boxes in raster output")
    svg_path = os.path.join(out_dir, "figure.svg")
    fig.savefig(svg_path, format="svg", metadata={"Date": None, "Creator": None},
                bbox_inches=None)
    paths["svg"] = svg_path
    if "png" in formats:
        png_path = os.path.join(out_dir, "figure.png")
        fig.savefig(png_path, format="png", dpi=spec["style"]["dpi"],
                    metadata={"Software": None})
        paths["png"] = png_path
    if "pdf" in formats:
        pdf_path = os.path.join(out_dir, "figure.pdf")
        fig.savefig(pdf_path, format="pdf", metadata={"CreationDate": None,
                                                      "Producer": None,
                                                      "Creator": None})
        paths["pdf"] = pdf_path
    meta["png"] = _png_info(paths.get("png"))
    meta["svg_text_nodes"] = _svg_text_count(paths["svg"])
    meta["svg_bytes"] = os.path.getsize(paths["svg"])
    with open(os.path.join(out_dir, "render_meta.json"), "w", encoding="utf-8") as fh:
        json.dump(meta, fh, ensure_ascii=False, indent=1)
    plt.close(fig)
    return paths, meta


def _png_info(path):
    if not path or not os.path.exists(path):
        return {}
    raw = open(path, "rb").read(33)
    if len(raw) >= 24 and raw[:8] == b"\x89PNG\r\n\x1a\n":
        w, h = struct.unpack(">II", raw[16:24])
        return {"width": w, "height": h, "bytes": os.path.getsize(path)}
    return {"bytes": os.path.getsize(path)}


def _svg_text_count(path):
    try:
        text = open(path, encoding="utf-8", errors="replace").read()
        return len(re.findall(r"<text\b", text))
    except OSError:
        return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--spec", required=True)
    ap.add_argument("--out", default="work")
    ap.add_argument("--formats", default="svg,png,pdf")
    a = ap.parse_args()
    spec = json.load(open(a.spec, encoding="utf-8"))
    formats = [f.strip() for f in a.formats.split(",") if f.strip()]
    try:
        paths, meta = render(spec, a.out, formats)
    except ImportError as exc:
        print("NO_MATPLOTLIB: %s" % exc)
        return 3
    except Exception as exc:  # noqa: BLE001
        print("FAIL: render error: %s" % exc)
        return 2
    print("renderer=matplotlib cjk_font=%r svg_text=%d png=%s warnings=%d"
          % (meta["cjk_font"], meta["svg_text_nodes"], meta.get("png", {}),
             len(meta["warnings"])))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
