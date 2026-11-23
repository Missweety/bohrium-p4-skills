#!/usr/bin/env python3
"""export_preview.py - SVG 导出 PNG/PDF 预览，登记导出参数；无栅格化器时用标准库兜底。

  python scripts/export_preview.py --svg work/mechanism.svg --spec work/spec.json \
      --out work --name mechanism [--formats png,pdf] [--dpi 300] [--draft work/draft.json]

适配顺序：cairosvg -> rsvg-convert -> inkscape -> matplotlib -> stdlib-raster。
最后一级只用标准库按 spec 直接栅格化（形状 + 定位标签 + 位图字体），保证任何环境都有真实
可检视的 PNG/PDF；该路径不渲染中文（用 P#/S# 定位标签，文本见 SVG/JSON），会在 notes 写明。
"""
import argparse
import json
import math
import os
import re
import shutil
import struct
import subprocess
import zlib


def _run(cmd):
    try:
        return subprocess.run(cmd, capture_output=True, timeout=180).returncode == 0
    except Exception:  # noqa: BLE001
        return False


def _cairosvg(svg, out, fmt, dpi):
    try:
        import cairosvg
    except Exception:  # noqa: BLE001
        return False
    try:
        if fmt == "png":
            cairosvg.svg2png(url=svg, write_to=out, dpi=dpi)
        else:
            cairosvg.svg2pdf(url=svg, write_to=out)
        return True
    except Exception:  # noqa: BLE001
        return False


def _rsvg(svg, out, fmt, dpi):
    if not shutil.which("rsvg-convert"):
        return False
    return _run(["rsvg-convert", "-f", fmt, "-o", out, "-d", str(dpi), "-p", str(dpi), svg])


def _inkscape(svg, out, fmt, dpi):
    if not shutil.which("inkscape"):
        return False
    return _run(["inkscape", svg, "--export-type=%s" % fmt,
                 "--export-filename=%s" % out, "--export-dpi=%d" % dpi])


def _anchor(box, tx, ty, shape="rounded"):
    x, y, w, h = box
    cx, cy = x + w / 2, y + h / 2
    dx, dy = tx - cx, ty - cy
    if not (dx or dy):
        return cx, cy
    if shape == "triangle":
        pts = [(cx, y), (x + w, y + h), (x, y + h)]
    elif shape in ("diamond", "valve"):
        pts = [(cx, y), (x + w, cy), (cx, y + h), (x, cy)]
    else:
        pts = None
    if pts:
        best = None
        for i in range(len(pts)):
            x1, y1 = pts[i]
            x2, y2 = pts[(i + 1) % len(pts)]
            ex, ey = x2 - x1, y2 - y1
            den = dx * ey - dy * ex
            if abs(den) < 1e-9:
                continue
            t = ((x1 - cx) * ey - (y1 - cy) * ex) / den
            u = ((x1 - cx) * dy - (y1 - cy) * dx) / den
            if t > 0 and -1e-9 <= u <= 1 + 1e-9 and (best is None or t < best):
                best = t
        if best is not None:
            return cx + dx * best, cy + dy * best
    t = min((w / 2) / abs(dx) if dx else 1e9, (h / 2) / abs(dy) if dy else 1e9)
    return cx + dx * t, cy + dy * t


def _wrap(s, maxw, px):
    toks, buf = [], ""
    for ch in str(s):
        if ord(ch) > 0x2E80 or ch in "，。；：（）、“”":
            if buf:
                toks.append(buf)
                buf = ""
            toks.append(ch)
        elif ch.isspace():
            if buf:
                toks.append(buf)
                buf = ""
            toks.append(" ")
        else:
            buf += ch
    if buf:
        toks.append(buf)
    out, cur = [], ""
    for tok in toks:
        if tok == " ":
            if cur:
                cur += " "
            continue
        width = lambda x: sum(1.0 if ord(c) > 0x2E80 else 0.56 for c in x) * px
        if width(cur + tok) <= maxw:
            cur += tok
            continue
        if cur.strip():
            out.append(cur.rstrip())
        cur = tok
    if cur.strip():
        out.append(cur.rstrip())
    return out


def _fit(s, maxw, px):
    s = str(s)
    if _tw(s, px) <= maxw:
        return s
    out = ""
    for ch in s:
        if _tw(out + ch + "…", px) > maxw:
            break
        out += ch
    return out + "…"


def _tw(s, px):
    return sum(1.0 if ord(c) > 0x2E80 else 0.56 for c in str(s)) * px


KIND_ZH = {"activation": "激活", "inhibition": "抑制", "binding": "结合/募集",
           "modification": "修饰", "transport": "转运", "flow": "流向",
           "pipe": "管路/流体", "energy": "能量", "signal": "信号/数据",
           "gas": "气体", "waste": "废液/废气", "material": "物料"}
# 与 routelib.TYPES 一致的部件描边色；其他图元回退到 stated/inferred 配色
TYPE_COLORS = {"reservoir": "#0072B2", "vessel": "#56B4E9", "pump": "#E69F00",
               "valve": "#D55E00", "reactor": "#009E73", "column": "#CC79A7",
               "detector": "#0072B2", "sensor": "#009E73", "separator": "#56B4E9",
               "instrument": "#0072B2", "waste": "#D55E00", "tubing": "#6B7280",
               "support": "#6B7280"}


def _part_lines(p, dpi):
    """与 routelib.part_layout 一致的部件文字度量：自动降字号至 7pt，最多 2+1 行。"""
    w, h = p.get("w", 100), p.get("h", 50)
    base = float(p.get("font_pt", 9))
    raw = p.get("label", "")
    for i in range(9):
        pt = max(7.0, base - 0.5 * i)
        px = pt * dpi / 72.0
        alll = _wrap(raw, w - 18, px)
        lines = alll[:2] or [""]
        if len(alll) > 2:
            lines[-1] = _fit(lines[-1], w - 18 - px, px) + "…"
        subs = [_fit(p.get("sub", ""), w - 18, px * 0.72)] if p.get("sub") else []
        need = len(lines) * px * 1.22 + 10 + len(subs) * px * 0.72 * 1.35
        if need <= h or pt <= 7.0:
            return pt, lines, subs
    return 7.0, [_fit(raw, w - 18, 7.0 * dpi / 72.0)], []


def _mpl(spec, out, fmt, dpi):
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        from matplotlib import font_manager
        from matplotlib.patches import Ellipse, FancyBboxPatch, Polygon
    except Exception:  # noqa: BLE001
        return False
    try:
        avail = {f.name for f in font_manager.fontManager.ttflist}
        cjk = [n for n in ("Arial Unicode MS", "PingFang SC", "Heiti SC", "Noto Sans CJK SC",
                           "Source Han Sans SC", "Microsoft YaHei", "WenQuanYi Zen Hei")
               if n in avail]
        plt.rcParams["font.sans-serif"] = cjk + ["DejaVu Sans"]
        plt.rcParams["axes.unicode_minus"] = False
    except Exception:  # noqa: BLE001
        pass
    fig_spec = spec.get("figure") or {}
    W, H = fig_spec.get("width_px"), fig_spec.get("height_px")
    if not W or not H:
        return False
    if fmt not in ("png", "pdf"):
        return False
    fh, ax = plt.subplots(figsize=(W / dpi, H / dpi), dpi=dpi)
    fh.subplots_adjust(left=0, right=1, bottom=0, top=1)
    ax.set_position([0, 0, 1, 1])
    ax.set_xlim(0, W)
    ax.set_ylim(H, 0)
    ax.axis("off")
    fh.patch.set_facecolor("#FFFFFF")

    # 装置区 / 技术路线区面板（与 SVG 图层一致）
    for key, label in (("apparatus_bbox", "装置与流向 / Apparatus & flow"),
                       ("stage_bbox", "技术路线与里程碑 / Technical route & milestones")):
        b = fig_spec.get(key)
        if not b:
            continue
        ax.add_patch(FancyBboxPatch((b["x"], b["y"]), b["w"], b["h"],
                                    boxstyle="round,pad=0,rounding_size=6",
                                    linewidth=1, edgecolor="#CBD5E1", facecolor="#F7F9FC"))
        ax.text(b["x"] + 16, b["y"] + 28, label, fontsize=9, color="#6B7280",
                weight="bold", va="baseline")

    # 区室 / 阶段底框
    for g in spec.get("compartments", []):
        x, y, w, h = g.get("x", 0), g.get("y", 0), g.get("w", W), g.get("h", 60)
        ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0,rounding_size=4",
                                    linewidth=1, edgecolor="#CBD5E1", facecolor="#F7F9FC"))
        ax.text(x + 14, y + 26, str(g.get("label", "")), fontsize=10, color="#6B7280",
                weight="bold", va="center")
    for s in spec.get("stages", []):
        x, y, w, h = s.get("x", 0), s.get("y", 0), s.get("w", 200), s.get("h", 90)
        ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0,rounding_size=6",
                                    linewidth=1.2, edgecolor="#0072B2", facecolor="#FFFFFF"))
        # 与 route_svg 一致的四行结构：编号+标题 / objective / 产出 / 里程碑
        pt_t = min(float(s.get("font_pt", 8)), 8.0)
        pt_b = max(6.0, pt_t - 1.5)
        px_t = pt_t * dpi / 72.0
        px_b = pt_b * dpi / 72.0
        all_t = _wrap(s.get("label", ""), w - 72, px_t)
        tlines = all_t[:2] or ["Phase %d" % s.get("order", "")]
        if len(all_t) > 2:
            tlines[-1] = _fit(tlines[-1], w - 72 - px_t, px_t) + "…"
        ax.add_patch(plt.Circle((x + 23, y + 23), 13, facecolor="#0072B2", edgecolor="none"))
        ax.text(x + 23, y + 23, str(s.get("order", "")), fontsize=7.5, color="#FFFFFF",
                ha="center", va="center", weight="bold")
        ty = y + 30
        for ln in tlines:
            ax.text(x + 44, ty, ln, fontsize=pt_t, color="#111827", weight="bold", va="baseline")
            ty += px_t * 0.95
        oy = y + 30 + (len(tlines) - 1) * px_t * 0.95 + px_t * 1.25
        olimit = 3 if len(tlines) == 1 else 2
        _o = str(s.get("objective", "")).strip().rstrip("。.;；,，、:： ")
        _l = str(s.get("label", "")).strip().rstrip("。.;；,，、:： ")
        all_o = _wrap("" if _o == _l else s.get("objective", ""), w - 28, px_b)
        olines = all_o[:olimit]
        if olines and len(all_o) > olimit:
            last = olines[-1]
            olines[-1] = (last + "…") if _tw(last + "…", px_b) <= w - 28 \
                else _fit(last, w - 28 - px_b, px_b) + "…"
        for ln in olines:
            ax.text(x + 14, oy, ln, fontsize=pt_b, color="#111827", va="baseline")
            oy += px_b * 1.05
        if s.get("outputs"):
            ax.text(x + 14, y + h - 40, _fit("→ " + " / ".join(s.get("outputs")), w - 28, px_b * 0.85),
                    fontsize=pt_b * 0.85, color="#0072B2", weight="bold", va="baseline")
        if s.get("milestone"):
            ax.text(x + 14, y + h - 14, _fit("◆ " + str(s["milestone"]), w - 28, px_b * 0.8),
                    fontsize=pt_b * 0.8, color="#009E73", weight="bold", va="baseline")

    nodes = spec.get("nodes") or spec.get("parts") or []
    by_id = {n.get("id"): n for n in nodes}
    # 先画连线再画部件：部件白底会盖住穿过其内部的线段，避免箭头压在部件盒上
    for e in spec.get("edges", []) + spec.get("connections", []):
        a, b = by_id.get(e.get("from")), by_id.get(e.get("to"))
        if not a or not b:
            continue
        ca = (a.get("x", 0), a.get("y", 0), a.get("w", 100), a.get("h", 50))
        cb = (b.get("x", 0), b.get("y", 0), b.get("w", 100), b.get("h", 50))
        x1, y1 = _anchor(ca, cb[0] + cb[2] / 2, cb[1] + cb[3] / 2, a.get("shape", "rounded"))
        x2, y2 = _anchor(cb, ca[0] + ca[2] / 2, ca[1] + ca[3] / 2, b.get("shape", "rounded"))
        ax.annotate("", xy=(x2, y2), xytext=(x1, y1), zorder=1,
                    arrowprops=dict(arrowstyle="->", color="#374151", lw=1.3,
                                    linestyle="--" if e.get("status") == "inferred" else "-"))
        if e.get("label"):
            lpx = 7 * dpi / 72.0
            lw = sum(1.0 if ord(c) > 0x2E80 else 0.56 for c in str(e["label"])) * lpx
            if lw <= 130:
                ax.text((x1 + x2) / 2, (y1 + y2) / 2 - 6, str(e["label"]), fontsize=7,
                        color="#374151", ha="center", va="bottom",
                        bbox=dict(facecolor="white", edgecolor="none", pad=1))
    for n in nodes:
        x, y, w, h = n.get("x", 0), n.get("y", 0), n.get("w", 100), n.get("h", 50)
        color = TYPE_COLORS.get(n.get("type"),
                                {"inferred": "#B26B00", "stated": "#0072B2"}.get(n.get("status"), "#0072B2"))
        shape = n.get("shape", "rounded")
        if shape in ("circle", "ellipse", "cell", "organelle"):
            ax.add_patch(Ellipse((x + w / 2, y + h / 2), w, h, facecolor="#FFFFFF",
                                 edgecolor=color, lw=1.4, zorder=2,
                                 linestyle="--" if n.get("status") == "inferred" else "-"))
        elif shape in ("diamond", "valve"):
            ax.add_patch(Polygon([(x + w / 2, y), (x + w, y + h / 2), (x + w / 2, y + h), (x, y + h / 2)],
                                 closed=True, facecolor="#FFFFFF", edgecolor=color, lw=1.4, zorder=2))
        elif shape == "triangle":
            ax.add_patch(Polygon([(x + w / 2, y), (x + w, y + h), (x, y + h)],
                                 closed=True, facecolor="#FFFFFF", edgecolor=color, lw=1.4, zorder=2))
        else:
            ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0,rounding_size=8",
                                        facecolor="#FFFFFF", edgecolor=color, lw=1.4, zorder=2,
                                        linestyle="--" if n.get("status") == "inferred" else "-"))
        pt, lines, subs = _part_lines(n, dpi)
        px = pt * dpi / 72.0
        lh = px * 1.2
        cy = y + h / 2 - (len(lines) * lh + len(subs) * lh * 0.78) / 2 + px * 0.85
        for ln in lines:
            ax.text(x + w / 2, cy, ln, ha="center", va="baseline", fontsize=pt, color="#111827",
                    weight="bold")
            cy += lh
        for ln in subs:
            ax.text(x + w / 2, cy, ln, ha="center", va="baseline", fontsize=pt * 0.72, color="#6B7280")
            cy += lh * 0.78
    for s in spec.get("stages", []):
        for dep in s.get("depends_on", []) or []:
            other = next((t for t in spec.get("stages", []) if t.get("id") == dep), None)
            if other:
                ax.annotate("", xy=(other.get("x", 0) + other.get("w", 200), other.get("y", 0) + 20),
                            xytext=(s.get("x", 0) - 4, s.get("y", 0) + 20),
                            arrowprops=dict(arrowstyle="<-", color="#6B7280", lw=0.9))

    # 标题
    ax.text(34, 46, str(fig_spec.get("title", "")), fontsize=10, fontweight="bold",
            color="#111827", va="baseline")
    # 图例
    items = spec.get("legend") or []
    if not items:
        kinds = []
        for e in spec.get("edges", []) + spec.get("connections", []):
            if e.get("kind") and e["kind"] not in kinds:
                kinds.append(e["kind"])
        items = [{"text": KIND_ZH.get(k, k), "kind": k} for k in kinds]
    lx, ly = 32, H - 280
    lh = 46 + 38 * max(1, len(items))
    ax.add_patch(FancyBboxPatch((lx, ly), 640, lh, boxstyle="round,pad=0,rounding_size=4",
                                facecolor="#FFFFFF", edgecolor="#CBD5E1", lw=1))
    ax.text(lx + 10, ly + 20, "图例 / Legend", fontsize=7.5, color="#6B7280",
            weight="bold", va="baseline")
    for i, it in enumerate(items):
        yy = ly + 56 + 38 * i
        kind = it.get("kind", "flow")
        color = {"flow": "#0072B2", "material": "#CC79A7", "gas": "#56B4E9",
                 "energy": "#E69F00", "signal": "#009E73", "waste": "#D55E00"}.get(kind, "#374151")
        ls = "--" if it.get("status") == "inferred" else "-"
        ax.annotate("", xy=(lx + 58, yy - 4), xytext=(lx + 10, yy - 4),
                    arrowprops=dict(arrowstyle="->", color=color, lw=1.4, linestyle=ls))
        ax.text(lx + 62, yy, str(it.get("text", it.get("kind", ""))), fontsize=7.5,
                color="#111827", va="center")
    # 单位 / 注释 / 图注
    units = spec.get("units") or {}
    unit_text = ("单位: " + "; ".join("%s=%s" % (k, v) for k, v in units.items())) if units else "单位: 定性"
    for j, ln in enumerate(_wrap(unit_text, W - 690 - 24, 7 * dpi / 72.0)[:2]):
        ax.text(690, H - 42 + j * 26, ln, fontsize=7, color="#6B7280", ha="left", va="baseline")
    notes = spec.get("notes") or []
    if not notes:
        notes = [{"text": "实线=明确；虚线=推断；箭头=流向；菱形=阶段里程碑。"}]
    ny = H - 270
    for i, nt in enumerate(notes):
        ax.text(690, ny + i * 44, str(nt.get("text", "")), fontsize=7.5, color="#6B7280",
                va="center", wrap=True)
    cap = spec.get("caption") or ""
    if cap:
        lines = _wrap(cap, 620, 7 * dpi / 72.0)
        if len(lines) > 5:
            lines = lines[:5]
            lines[-1] += "…"
        for j, ln in enumerate(lines):
            ax.text(690, H - 200 + j * 28, ln, fontsize=7, color="#6B7280", va="center")
    # 比例尺
    sb = spec.get("scale_bar") or {}
    if sb.get("length_px"):
        sx, sy = W - 34 - float(sb["length_px"]), H - 64
        ax.plot([sx, sx + float(sb["length_px"])], [sy, sy], color="#111827", lw=2)
        ax.plot([sx, sx], [sy - 5, sy + 5], color="#111827", lw=2)
        ax.plot([sx + float(sb["length_px"])] * 2, [sy - 5, sy + 5], color="#111827", lw=2)
        ax.text(sx + float(sb["length_px"]) / 2, sy - 10, str(sb.get("label", "")),
                fontsize=8, color="#6B7280", ha="center")
    else:
        ax.text(W - 34, H - 64, str(sb.get("label") or "not to scale / 非等比"),
                fontsize=8, color="#6B7280", ha="right")
    fh.savefig(out, dpi=dpi, facecolor="white")
    plt.close(fh)
    return True


def _purepy(spec, out, fmt, dpi):
    """标准库兜底栅格化：按 spec 直接画形状，文本用 5x7 位图标签（P#/S#）。

    任何环境都能产出真实 PNG/PDF，避免"无 cairosvg/rsvg/inkscape/matplotlib 就没有预览"。
    该路径不渲染中文正文：PNG 只画部件/阶段/连线与编号标签，完整文字看 SVG 与 result.json。
    """
    if not spec or not spec.get("parts"):
        return False
    f = spec.get("figure") or {}
    try:
        W, H = int(f.get("width_px")), int(f.get("height_px"))
    except (TypeError, ValueError):
        return False
    if W <= 0 or H <= 0:
        return False
    scale = max(1.0, min(float(dpi) / 96.0, 2400.0 / max(W, H, 1)))
    cw, ch = int(W * scale), int(H * scale)
    cv = Canvas(cw, ch, (255, 255, 255))
    # 标题条与分区底色
    cv.rect(0, 0, cw, int(56 * scale), (247, 249, 252))
    lines = spec.get("connections") or []
    for c in lines:
        a = next((p for p in spec["parts"] if p.get("id") == c.get("from")), None)
        b = next((p for p in spec["parts"] if p.get("id") == c.get("to")), None)
        if not a or not b:
            continue
        col = COLORS.get(c.get("kind"), (110, 110, 110))
        cv.line(int((a["x"] + a["w"] / 2) * scale), int((a["y"] + a["h"] / 2) * scale),
                int((b["x"] + b["w"] / 2) * scale), int((b["y"] + b["h"] / 2) * scale),
                col, max(1, int(1.6 * scale)), dash=c.get("status") == "inferred")
    for i, p in enumerate(spec["parts"]):
        x, y = int(p["x"] * scale), int(p["y"] * scale)
        w, h = max(1, int(p["w"] * scale)), max(1, int(p["h"] * scale))
        cv.rect(x, y, x + w, y + h, (255, 255, 255))
        cv.frame(x, y, x + w, y + h, COLORS.get(p.get("type"), (110, 110, 110)), max(1, int(1.4 * scale)),
                 dash=p.get("status") == "inferred")
        cv.text(x + 4, y + 4, "P%d" % (i + 1), (17, 24, 39), max(1, int(1.6 * scale)))
    for s in spec.get("stages") or []:
        if not all(k in s for k in ("x", "y", "w", "h")):
            continue
        x, y = int(s["x"] * scale), int(s["y"] * scale)
        w, h = max(1, int(s["w"] * scale)), max(1, int(s["h"] * scale))
        cv.rect(x, y, x + w, y + h, (255, 255, 255))
        cv.frame(x, y, x + w, y + h, (0, 114, 178), max(1, int(1.4 * scale)))
        cv.text(x + 4, y + 4, "S%d" % s.get("order", 0), (17, 24, 39), max(1, int(1.6 * scale)))
    cv.text(int(12 * scale), int(16 * scale), "PREVIEW - LAYOUT ONLY", (107, 114, 128), max(1, int(1.5 * scale)))
    cv.text(int(12 * scale), int(34 * scale),
            "P#=PART S#=STAGE  TEXT:SEE SVG/RESULT.JSON", (107, 114, 128), 1)
    if fmt == "png":
        _write_png(cv, out)
    elif fmt == "pdf":
        _write_pdf(cv, out, W, H, dpi)
    else:
        return False
    return True


def _write_png(cv, path):
    raw = bytearray()
    stride = cv.w * 3
    for y in range(cv.h):
        raw.append(0)
        raw += cv.buf[y * stride:(y + 1) * stride]
    def chunk(tag, data):
        c = struct.pack(">I", len(data)) + tag + data
        return c + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
    ihdr = struct.pack(">IIBBBBB", cv.w, cv.h, 8, 2, 0, 0, 0)
    with open(path, "wb") as fh:
        fh.write(b"\x89PNG\r\n\x1a\n")
        fh.write(chunk(b"IHDR", ihdr))
        fh.write(chunk(b"IDAT", zlib.compress(bytes(raw), 6)))
        fh.write(chunk(b"IEND", b""))


def _write_pdf(cv, path, W, H, dpi):
    """单页 PDF：把同一张栅格作为 FlateDecode 图像嵌入，页面尺寸按 dpi 换算为 pt。"""
    pw, ph = W * 72.0 / float(dpi), H * 72.0 / float(dpi)
    raw = bytearray()
    stride = cv.w * 3
    for y in range(cv.h):
        raw += cv.buf[y * stride:(y + 1) * stride]
    data = zlib.compress(bytes(raw), 6)
    objs = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        ("<< /Type /Page /Parent 2 0 R /MediaBox [0 0 %.2f %.2f] /Resources << /XObject << /Im0 4 0 R >> >> "
         "/Contents 5 0 R >>" % (pw, ph)).encode("ascii"),
        ("<< /Type /XObject /Subtype /Image /Width %d /Height %d /ColorSpace /DeviceRGB "
         "/BitsPerComponent 8 /Filter /FlateDecode /Length %d >>\nstream\n" % (cv.w, cv.h, len(data))
         ).encode("ascii") + data + b"\nendstream",
    ]
    content = ("q %.2f 0 0 %.2f 0 0 cm /Im0 Do Q" % (pw, ph)).encode("ascii")
    objs.append(("<< /Length %d >>\nstream\n" % len(content)).encode("ascii") + content + b"\nendstream")
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for i, body in enumerate(objs, 1):
        offsets.append(len(out))
        out += ("%d 0 obj\n" % i).encode("ascii") + body + b"\nendobj\n"
    xref = len(out)
    out += ("xref\n0 %d\n" % (len(objs) + 1)).encode("ascii")
    out += b"0000000000 65535 f \n"
    for off in offsets:
        out += ("%010d 00000 n \n" % off).encode("ascii")
    out += ("trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objs) + 1, xref)).encode("ascii")
    with open(path, "wb") as fh:
        fh.write(bytes(out))


COLORS = {"reservoir": (0, 114, 178), "vessel": (86, 180, 233), "pump": (230, 159, 0),
          "valve": (213, 94, 0), "reactor": (0, 158, 115), "column": (204, 121, 167),
          "detector": (0, 114, 178), "sensor": (0, 158, 115), "separator": (86, 180, 233),
          "instrument": (0, 114, 178), "waste": (213, 94, 0), "tubing": (107, 114, 128),
          "support": (107, 114, 128), "other": (107, 114, 128),
          "flow": (0, 114, 178), "material": (204, 121, 167), "gas": (86, 180, 233),
          "energy": (230, 159, 0), "signal": (0, 158, 115)}

FONT5 = {
    "0": "01110 10001 10011 10101 11001 10001 01110",
    "1": "00100 01100 00100 00100 00100 00100 01110",
    "2": "01110 10001 00001 00010 00100 01000 11111",
    "3": "11111 00010 00100 00010 00001 10001 01110",
    "4": "00010 00110 01010 10010 11111 00010 00010",
    "5": "11111 10000 11110 00001 00001 10001 01110",
    "6": "00110 01000 10000 11110 10001 10001 01110",
    "7": "11111 00001 00010 00100 01000 01000 01000",
    "8": "01110 10001 10001 01110 10001 10001 01110",
    "9": "01110 10001 10001 01111 00001 00010 01100",
    "A": "01110 10001 10001 11111 10001 10001 10001",
    "B": "11110 10001 10001 11110 10001 10001 11110",
    "C": "01110 10001 10000 10000 10000 10001 01110",
    "D": "11100 10010 10001 10001 10001 10010 11100",
    "E": "11111 10000 10000 11110 10000 10000 11111",
    "F": "11111 10000 10000 11110 10000 10000 10000",
    "G": "01110 10001 10000 10111 10001 10001 01111",
    "H": "10001 10001 10001 11111 10001 10001 10001",
    "I": "01110 00100 00100 00100 00100 00100 01110",
    "J": "00111 00010 00010 00010 00010 10010 01100",
    "K": "10001 10010 10100 11000 10100 10010 10001",
    "L": "10000 10000 10000 10000 10000 10000 11111",
    "M": "10001 11011 10101 10101 10001 10001 10001",
    "N": "10001 11001 10101 10011 10001 10001 10001",
    "O": "01110 10001 10001 10001 10001 10001 01110",
    "P": "11110 10001 10001 11110 10000 10000 10000",
    "Q": "01110 10001 10001 10001 10101 10010 01101",
    "R": "11110 10001 10001 11110 10100 10010 10001",
    "S": "01111 10000 10000 01110 00001 00001 11110",
    "T": "11111 00100 00100 00100 00100 00100 00100",
    "U": "10001 10001 10001 10001 10001 10001 01110",
    "V": "10001 10001 10001 10001 10001 01010 00100",
    "W": "10001 10001 10001 10101 10101 11011 10001",
    "X": "10001 10001 01010 00100 01010 10001 10001",
    "Y": "10001 10001 01010 00100 00100 00100 00100",
    "Z": "11111 00001 00010 00100 01000 10000 11111",
    "-": "00000 00000 00000 11111 00000 00000 00000",
    ".": "00000 00000 00000 00000 00000 01100 01100",
    "/": "00001 00010 00010 00100 01000 01000 10000",
    ":": "00000 01100 01100 00000 01100 01100 00000",
    " ": "00000 00000 00000 00000 00000 00000 00000",
}


class Canvas(object):
    """极简 RGB 画布：矩形/线/边框/位图文本，够用于布局预览。"""

    def __init__(self, w, h, bg):
        self.w, self.h = w, h
        self.buf = bytearray(bytes(bg) * (w * h))

    def _px(self, x, y, col):
        if 0 <= x < self.w and 0 <= y < self.h:
            i = (y * self.w + x) * 3
            self.buf[i:i + 3] = bytes(col)

    def rect(self, x0, y0, x1, y1, col):
        x0, x1 = max(0, int(x0)), min(self.w, int(x1))
        y0, y1 = max(0, int(y0)), min(self.h, int(y1))
        if x1 <= x0 or y1 <= y0:
            return
        row = bytes(col) * (x1 - x0)
        for y in range(y0, y1):
            i = (y * self.w + x0) * 3
            self.buf[i:i + len(row)] = row

    def frame(self, x0, y0, x1, y1, col, t, dash=False):
        for k in range(t):
            for x in range(int(x0) + k, int(x1) - k):
                if dash and (x // 6) % 2:
                    continue
                self._px(x, int(y0) + k, col)
                self._px(x, int(y1) - k - 1, col)
            for y in range(int(y0) + k, int(y1) - k):
                if dash and (y // 6) % 2:
                    continue
                self._px(int(x0) + k, y, col)
                self._px(int(x1) - k - 1, y, col)

    def line(self, x0, y0, x1, y1, col, t, dash=False):
        dx, dy = abs(x1 - x0), -abs(y1 - y0)
        sx, sy = (1 if x0 < x1 else -1), (1 if y0 < y1 else -1)
        err, n = dx + dy, 0
        x, y = x0, y0
        while True:
            n += 1
            if not (dash and (n // 8) % 2):
                for ox in range(-t, t + 1):
                    for oy in range(-t, t + 1):
                        self._px(x + ox, y + oy, col)
            if x == x1 and y == y1:
                break
            e2 = 2 * err
            if e2 >= dy:
                err += dy
                x += sx
            if e2 <= dx:
                err += dx
                y += sy

    def text(self, x, y, s, col, size=1):
        cx = int(x)
        for ch in str(s).upper():
            g = FONT5.get(ch)
            if g is None:
                cx += 6 * size
                continue
            for r, row in enumerate(g.split(" ")):
                for c, bit in enumerate(row):
                    if bit == "1":
                        self.rect(cx + c * size, int(y) + r * size,
                                  cx + c * size + size, int(y) + r * size + size, col)
            cx += 6 * size


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--svg", required=True)
    ap.add_argument("--spec")
    ap.add_argument("--out", default="work")
    ap.add_argument("--name", default="figure")
    ap.add_argument("--formats", default="png,pdf")
    ap.add_argument("--dpi", type=int, default=300)
    ap.add_argument("--draft")
    a = ap.parse_args()
    spec, W, H = {}, None, None
    if a.spec and os.path.exists(a.spec):
        with open(a.spec, encoding="utf-8") as fh:
            spec = json.load(fh)
        f = spec.get("figure") or {}
        W, H = f.get("width_px"), f.get("height_px")
    if not W or not H:
        head = open(a.svg, encoding="utf-8").read(800)
        mw, mh = re.search(r'width="(\d+)"', head), re.search(r'height="(\d+)"', head)
        W = int(mw.group(1)) if mw else None
        H = int(mh.group(1)) if mh else None
    os.makedirs(a.out, exist_ok=True)
    exports, notes = [], []
    engines = (("cairosvg", _cairosvg), ("rsvg-convert", _rsvg),
               ("inkscape", _inkscape), ("matplotlib", _mpl), ("stdlib-raster", _purepy))
    for fmt in [f.strip().lower() for f in a.formats.split(",") if f.strip()]:
        out = os.path.join(a.out, "%s.%s" % (a.name, fmt))
        for engine, fn in engines:
            try:
                spec_engine = engine in ("matplotlib", "stdlib-raster")
                ok = fn(spec, out, fmt, a.dpi) if spec_engine else fn(a.svg, out, fmt, a.dpi)
            except Exception:  # noqa: BLE001
                ok = False
            if ok and os.path.exists(out) and os.path.getsize(out) > 0:
                exports.append({"path": os.path.basename(out), "format": fmt, "width_px": W,
                                "height_px": H, "dpi": a.dpi, "engine": engine})
                if engine == "stdlib-raster":
                    notes.append("%s 由标准库兜底栅格化：只画布局与 P#/S# 编号，中文文本以 SVG 为准" % fmt)
                break
        else:
            notes.append("%s 导出失败：cairosvg/rsvg-convert/inkscape/matplotlib/stdlib-raster 均不可用" % fmt)
    status = "ok" if any(e["format"] == "png" for e in exports) else "preview_unavailable"
    if status != "ok":
        notes.append("已保留 SVG 矢量源；PNG 预览缺失需写入 uncertainty")
    rep = {"svg": os.path.basename(a.svg), "preview_status": status, "exports": exports, "notes": notes}
    with open(os.path.join(a.out, "exports.json"), "w", encoding="utf-8") as fh:
        json.dump(rep, fh, ensure_ascii=False, indent=1)
    if a.draft and os.path.exists(a.draft):
        with open(a.draft, encoding="utf-8") as fh:
            draft = json.load(fh)
        draft.setdefault("fields", {})["exports"] = exports
        draft["fields"]["preview_status"] = status
        with open(a.draft, "w", encoding="utf-8") as fh:
            json.dump(draft, fh, ensure_ascii=False, indent=1)
    print("preview_status=%s exports=%s" % (status, [(e["path"], e["engine"]) for e in exports]))
    for n in notes:
        print(" -", n)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
