#!/usr/bin/env python3
"""labels.py - shared text, tick and colour helpers used by every stage.

Single source of truth for:
  * fmt_num            deterministic number formatting (no locale, no float noise)
  * nice_ticks         nice-number axis ranges with 3..8 ticks, always inside bounds
  * wrap_label         width-aware wrapping (spaces for latin, per-char for CJK)
  * text_width_px      conservative glyph width estimate for overlap decisions
  * choose_rotation    tick-label rotation angle so labels do not collide
  * viridis_index      quantise a value into the 10 sampled Viridis levels

Keeping this in one module means plan, spec, render and self-check compute the same
ticks and the same label geometry, so a check can never disagree with the figure.
"""
import math
import re

CJK_RE = re.compile(r"[\u3000-\u9fff\uf900-\ufaff\uff00-\uffef]")
VIRIDIS = ["#440154", "#482878", "#3E4A89", "#31688E", "#26828E", "#1F9E89",
           "#35B779", "#6DCD59", "#B4DE2C", "#FDE725"]
OKABE = ["#0072B2", "#E69F00", "#009E73", "#CC79A7", "#56B4E9", "#D55E00", "#F0E442", "#999999"]
ACCENT = "#D55E00"


def fmt_num(v):
    if v is None:
        return ""
    try:
        v = float(v)
    except (TypeError, ValueError):
        return ""
    if abs(v) < 1e-12:
        return "0"
    if abs(v) >= 1e5 or abs(v) < 1e-4:
        return ("%.3g" % v)
    s = ("%.6g" % v)
    if "e" in s:
        return s
    return s


def fmt_label(v):
    """Value-label formatting: publication style, 4 significant digits at most.

    Axis ticks keep fmt_num (they need tick-step precision); data labels and
    heatmap cells use this so a mean of 1.256667 prints 1.26, not 1.25667.
    """
    if v is None:
        return ""
    try:
        v = float(v)
    except (TypeError, ValueError):
        return ""
    if not math.isfinite(v):
        return ""
    a = abs(v)
    if a == 0:
        return "0"
    if a >= 1000:
        s = "%.0f" % v
    elif a >= 1:
        s = "%.2f" % v
    elif a >= 0.1:
        s = "%.3f" % v
    elif a >= 0.01:
        s = "%.4f" % v
    else:
        return "%.2g" % v
    if "." in s:
        s = s.rstrip("0").rstrip(".")
    return s


def _nice_step(raw):
    if raw <= 0 or not math.isfinite(raw):
        return 1.0
    exp = math.floor(math.log10(raw))
    f = raw / 10 ** exp
    nf = 1 if f <= 1 else 2 if f <= 2 else 2.5 if f <= 2.5 else 5 if f <= 5 else 10
    return nf * 10 ** exp


def nice_ticks(lo, hi, target=5, zero=False, max_ticks=8):
    """Return {min, max, ticks}. Ticks are sorted, inside [min,max], 3..8 in number."""
    lo = 0.0 if zero else float(lo)
    hi = float(hi)
    if not math.isfinite(lo) or not math.isfinite(hi):
        lo, hi = 0.0, 1.0
    if hi <= lo:
        hi = lo + (abs(lo) * 0.1 or 1.0)
    step = _nice_step((hi - lo) / max(target - 1, 1))
    nlo = 0.0 if zero else math.floor(lo / step) * step
    nhi = math.ceil(hi / step) * step
    while nhi <= nlo:
        nhi = nlo + step
    while len([1 for _ in range(int(math.floor((nhi - nlo) / step)) + 1)]) > max_ticks:
        step *= 2
        nlo = 0.0 if zero else math.floor(lo / step) * step
        nhi = math.ceil(hi / step) * step
    count = int(round((nhi - nlo) / step))
    while count < 2:
        step /= 2.0
        count = int(round((nhi - nlo) / step))
    ticks = [round(nlo + step * k, 10) for k in range(count + 1)]
    if len(ticks) > max_ticks:
        stride = int(math.ceil((len(ticks) - 1) / (max_ticks - 1)))
        ticks = ticks[::stride]
        if ticks[-1] != round(nhi, 10):
            ticks.append(round(nhi, 10))
    if len(ticks) < 2:
        ticks = [round(nlo, 10), round(nhi, 10)]
    return {"min": round(min(nlo, ticks[0]), 10), "max": round(max(nhi, ticks[-1]), 10),
            "ticks": [round(float(t), 10) for t in ticks]}


def pinned_ticks(lo, hi, target=5):
    """Axis bounds fixed by an edit instruction: keep exact limits, add interior ticks."""
    lo, hi = float(lo), float(hi)
    if hi <= lo:
        hi = lo + 1.0
    step = _nice_step((hi - lo) / max(target - 1, 1))
    ticks = [round(lo, 10)]
    v = math.ceil((lo + step * 0.5) / step - 1e-9) * step
    while v < hi - 1e-9:
        ticks.append(round(v, 10))
        v += step
    ticks.append(round(hi, 10))
    if len(ticks) > 8:
        stride = int(math.ceil(len(ticks) / 8))
        ticks = ticks[::stride] + [round(hi, 10)]
    return {"min": round(lo, 10), "max": round(hi, 10), "ticks": ticks,
            "pinned": True}


def has_cjk(s):
    return bool(CJK_RE.search(str(s)))


def text_width_px(s, font_px):
    """Conservative width estimate: CJK ~1.0 em, latin ~0.56 em, digits ~0.5 em."""
    w = 0.0
    for ch in str(s):
        if CJK_RE.match(ch):
            w += 1.02 * font_px
        elif ch in "ilj.,:;'|":
            w += 0.28 * font_px
        elif ch.isupper():
            w += 0.66 * font_px
        else:
            w += 0.55 * font_px
    return w


def wrap_label(s, width=14, max_lines=2):
    """Wrap a long tick label. Latin splits on separators, CJK splits per char."""
    s = str(s).strip()
    if width <= 0 or len(s) <= width:
        return [s]
    if has_cjk(s):
        per = max(int(width), 4)
        lines = [s[i:i + per] for i in range(0, len(s), per)]
        if len(lines) > max_lines:
            lines = lines[:max_lines]
            lines[-1] = lines[-1][: max(per - 1, 1)] + "…"
        return lines
    tokens = re.split(r"([ _\-/,:;])", s)
    lines, cur = [], ""
    for tok in tokens:
        if not tok:
            continue
        if len(cur) + len(tok) <= width:
            cur += tok
        else:
            if cur.strip():
                lines.append(cur.strip())
            cur = tok.lstrip(" _-/,:;")
            while len(cur) > width:
                lines.append(cur[:width])
                cur = cur[width:]
    if cur.strip():
        lines.append(cur.strip())
    if len(lines) > max_lines:
        lines = lines[:max_lines]
        lines[-1] = lines[-1][: max(width - 1, 1)] + "…"
    return lines or [s]


def choose_rotation(labels, band_px, font_px):
    """Pick the smallest rotation that keeps neighbouring tick labels apart."""
    labels = [str(x) for x in labels]
    if not labels:
        return 0
    longest = max(text_width_px(x, font_px) for x in labels)
    if longest <= band_px - 2:
        return 0
    if longest * math.cos(math.radians(30)) <= band_px - 2:
        return 30
    if longest * math.cos(math.radians(45)) <= band_px - 2:
        return 45
    return 90


def viridis_index(value, lo, hi, levels=10):
    """Map a value to one of `levels` discrete Viridis colours (keeps palette legal)."""
    if value is None:
        return None
    if hi <= lo:
        return levels // 2
    frac = (float(value) - float(lo)) / (float(hi) - float(lo))
    idx = int(round(min(max(frac, 0.0), 1.0) * (levels - 1)))
    return idx


def viridis_color(value, lo, hi, levels=10):
    idx = viridis_index(value, lo, hi, levels)
    return VIRIDIS[levels // 2] if idx is None else VIRIDIS[idx]


def color_for_series(i):
    return OKABE[i % len(OKABE)]
