#!/usr/bin/env python3
"""template_fit.py - probe a slide template, map page content onto its slots, check compliance.

Subcommands:
  probe      read a .pptx (zip/XML, stdlib) or a template.json spec and emit
             work/template_profile.json + template_profile.md (layouts, slots, theme colors/fonts).
  fit        assign every slide to a layout, fill the title/body/caption/footer slots, then run
             compliance checks (font floor, contrast, whitespace, chars per slide, slot coverage).
  check      re-run the compliance checks against an existing spec + profile.
  finalize   merge skill fields into result.json written by kernel emit.
  selfcheck  verify work/output (spec, deck, notes, slot map, compliance, result).

Template input:
  * .pptx  - layouts read from ppt/slideLayouts/*.xml, colours/fonts from ppt/theme/theme1.xml;
  * .json  - {"slide_size":{...}, "theme":{colors,fonts}, "layouts":[{name, slots:{...}}]};
  * none   - built-in 16:9 default profile, marked in `warnings` and `uncertainty`.

Hard checks: title/body/caption/footer font floors, WCAG contrast, whitespace coverage,
chars per slide, every content page having title+body slots, footer slot presence.

Usage:
  python scripts/template_fit.py probe --template /input/materials/template.pptx --out work
  python scripts/template_fit.py fit --spec work/deck_spec.json --profile work/template_profile.json --out work
Exit 0 = no hard compliance error, 1 = fix layout/spec before delivering.
"""
import argparse
import json
import os
import re
import sys
import zipfile

import spec_io
from kernel import contract_field_names, contract_requirements, schema_problems

EMU = 914400.0
SLOT_ALIAS = {
    "title": ("title", "标题", "标题占位符", "ctrtitle"),
    "body": ("body", "正文", "content", "内容", "obj"),
    "caption": ("caption", "图注", "图注文本", "caption text"),
    "footer": ("footer", "页脚", "ftr"),
    "date": ("date", "dt", "日期"),
    "number": ("sldnum", "slide number", "页码"),
}
MIN_FONT = {"title": 28.0, "body": 18.0, "caption": 12.0, "footer": 9.0}
DEFAULT_CHARS = 380


def _pt(size_attr):
    try:
        value = int(size_attr)
    except (TypeError, ValueError):
        return None
    return round(value / 100.0, 1)


def _box(off, ext):
    if not off or not ext:
        return None
    return [round(int(off.group(1)) / EMU, 2), round(int(off.group(2)) / EMU, 2),
            round(int(ext.group(1)) / EMU, 2), round(int(ext.group(2)) / EMU, 2)]


def _slot_name(ph_type, ph_name):
    low_type = (ph_type or "").lower()
    low_name = (ph_name or "").lower()
    if low_type in ("title", "ctrtitle"):
        return "title"
    if low_type in ("ftr",):
        return "footer"
    if low_type in ("dt",):
        return "date"
    if low_type in ("sldnum",):
        return "number"
    if "caption" in low_name or "图注" in low_name:
        return "caption"
    if low_type in ("body", "obj") or "content" in low_name or "正文" in low_name:
        return "body"
    if not low_type and not low_name:
        return "body"  # OOXML allows omitting type on content placeholders
    return None


def _parse_colors(theme_xml, master_xml=""):
    colors, color_map = {}, {}
    scheme = re.search(r"<a:clrScheme[^>]*>(.*?)</a:clrScheme>", theme_xml, re.S)
    if scheme:
        block = scheme.group(1)
        for key in ("dk1", "lt1", "dk2", "lt2", "accent1", "accent2", "accent3",
                    "accent4", "accent5", "accent6", "hlink", "folHlink"):
            match = re.search(r"<a:%s>(.*?)</a:%s>" % (key, key), block, re.S)
            if not match:
                continue
            srgb = re.search(r'<a:srgbClr val="([0-9A-Fa-f]{6})"', match.group(1))
            sysclr = re.search(r'<a:sysClr[^>]*lastClr="([0-9A-Fa-f]{6})"', match.group(1))
            value = srgb.group(1) if srgb else (sysclr.group(1) if sysclr else None)
            if value:
                colors[key] = "#" + value.upper()
    clr_map = re.search(r"<p:clrMap\b([^>]*)/?>", master_xml)
    if clr_map:
        for key, value in re.findall(r'(\w+)="([^"]+)"', clr_map.group(1)):
            color_map[key] = value
    return colors, color_map


def _parse_fonts(theme_xml):
    fonts = {}
    for key in ("major", "minor"):
        block = re.search(r"<a:%sFont>(.*?)</a:%sFont>" % (key, key), theme_xml, re.S)
        if not block:
            continue
        latin = re.search(r'<a:latin typeface="([^"]*)"', block.group(1))
        ea = re.search(r'<a:ea typeface="([^"]*)"', block.group(1))
        fonts[key] = {"latin": latin.group(1) if latin else "",
                      "ea": ea.group(1) if ea else ""}
    return fonts


def probe_pptx(path):
    warnings, layouts = [], []
    with zipfile.ZipFile(path) as zf:
        names = zf.namelist()
        theme_xml = ""
        for name in names:
            if name.startswith("ppt/theme/theme") and name.endswith(".xml"):
                theme_xml = zf.read(name).decode("utf-8", "replace")
                break
        pres = zf.read("ppt/presentation.xml").decode("utf-8", "replace") \
            if "ppt/presentation.xml" in names else ""
        master_xml = zf.read("ppt/slideMasters/slideMaster1.xml").decode("utf-8", "replace") \
            if "ppt/slideMasters/slideMaster1.xml" in names else ""
        master_sizes = {}
        for style, key in (("titleStyle", "title"), ("bodyStyle", "body")):
            block = re.search(r"<p:%s>(.*?)</p:%s>" % (style, style), master_xml, re.S)
            if block:
                size = re.search(r'<a:defRPr[^>]*\bsz="(\d+)"', block.group(1))
                if size:
                    master_sizes[key] = _pt(size.group(1))
        size = re.search(r'<p:sldSz cx="(\d+)" cy="(\d+)"', pres)
        slide_size = {"w_in": round(int(size.group(1)) / EMU, 2),
                      "h_in": round(int(size.group(2)) / EMU, 2)} if size else \
            {"w_in": 13.333, "h_in": 7.5}
        for name in sorted(n for n in names if re.match(r"ppt/slideLayouts/slideLayout\d+\.xml$", n)):
            xml = zf.read(name).decode("utf-8", "replace")
            csl = re.search(r'<p:cSld name="([^"]*)"', xml)
            layout_name = csl.group(1) if csl else os.path.basename(name)
            slots = {}
            for sp in re.findall(r"<p:sp>.*?</p:sp>", xml, re.S):
                ph = re.search(r"<p:ph\b([^>]*?)/?>", sp)
                if not ph:
                    continue
                attrs = ph.group(1)
                type_match = re.search(r'type="([^"]+)"', attrs)
                name_match = re.search(r'name="([^"]+)"', attrs)
                ph_type = type_match.group(1) if type_match else ""
                ph_name = name_match.group(1) if name_match else ""
                slot = _slot_name(ph_type, ph_name)
                if not slot or slot in slots:
                    continue
                idx = re.search(r'idx="([^"]+)"', attrs)
                off = re.search(r'<a:off x="(-?\d+)" y="(-?\d+)"', sp)
                ext = re.search(r'<a:ext cx="(\d+)" cy="(\d+)"', sp)
                size_pt = None
                for pattern in (r'<a:defRPr[^>]*\bsz="(\d+)"', r'<a:rPr[^>]*\bsz="(\d+)"'):
                    match = re.search(pattern, sp)
                    if match:
                        size_pt = _pt(match.group(1))
                        break
                slots[slot] = {
                    "placeholder": ph_type or slot,
                    "idx": idx.group(1) if idx else "",
                    "font_pt": size_pt if size_pt is not None else master_sizes.get(slot),
                    "box": _box(off, ext),
                }
            if slots:
                layouts.append({"name": layout_name, "slots": slots})
    colors, color_map = _parse_colors(theme_xml, master_xml)
    fonts = _parse_fonts(theme_xml)
    if not colors:
        warnings.append("主题颜色未解析到，对比度检查降级")
    if not layouts:
        warnings.append("未解析到任何版式槽位")
    if not any("footer" in (lay.get("slots") or {}) for lay in layouts):
        warnings.append("模板未提供页脚（ftr）槽位")
    return {
        "source": os.path.basename(path),
        "slide_size": slide_size,
        "theme": {"colors": colors, "color_map": color_map, "fonts": fonts},
        "layouts": layouts,
        "warnings": warnings,
    }


def _normalize_slot(name, value):
    aliases = {alias: key for key, names in SLOT_ALIAS.items() for alias in names}
    key = aliases.get(str(name).strip().lower(), str(name).strip().lower())
    if isinstance(value, (int, float)):
        value = {"font_pt": float(value)}
    value = dict(value or {})
    box = value.get("box") or value.get("rect")
    if isinstance(box, dict):
        box = [box.get("x"), box.get("y"), box.get("w"), box.get("h")]
    return key, {
        "placeholder": str(value.get("placeholder") or key),
        "idx": str(value.get("idx") or ""),
        "font_pt": value.get("font_pt", value.get("pt")),
        "box": box,
    }


def normalize_profile(data, source="json"):
    data = dict(data or {})
    size = data.get("slide_size") or {}
    theme = data.get("theme") or {}
    colors = theme.get("colors") or data.get("colors") or {}
    fonts = theme.get("fonts") or data.get("fonts") or {}
    if isinstance(fonts, dict):
        fonts = {key: (val if isinstance(val, dict) else {"latin": str(val), "ea": ""})
                 for key, val in fonts.items()}
    else:
        fonts = {}
    layouts = []
    for raw in data.get("layouts") or []:
        slots = {}
        for name, value in (raw.get("slots") or {}).items():
            key, slot = _normalize_slot(name, value)
            slots[key] = slot
        if slots:
            layouts.append({"name": str(raw.get("name") or "Layout"), "slots": slots})
    return {
        "source": source,
        "slide_size": {"w_in": float(size.get("w_in") or size.get("width_in") or 13.333),
                       "h_in": float(size.get("h_in") or size.get("height_in") or 7.5)},
        "theme": {"colors": {str(k): str(v) for k, v in colors.items()},
                  "color_map": theme.get("color_map") or {},
                  "fonts": fonts},
        "layouts": layouts,
        "warnings": list(data.get("warnings") or []),
    }


def default_profile():
    return {
        "source": "default",
        "slide_size": {"w_in": 13.333, "h_in": 7.5},
        "theme": {"colors": {"dk1": "#1A1A1A", "lt1": "#FFFFFF", "accent1": "#0B5FFF"},
                  "color_map": {"bg1": "lt1", "tx1": "dk1"}, "fonts": {"major": "", "minor": ""}},
        "layouts": [
            {"name": "Title Slide", "slots": {
                "title": {"placeholder": "ctrTitle", "idx": "", "font_pt": 40.0,
                          "box": [1.0, 2.0, 11.3, 1.6]},
                "footer": {"placeholder": "ftr", "idx": "", "font_pt": 10.0,
                           "box": [0.6, 7.0, 8.0, 0.3]}}},
            {"name": "Title and Content", "slots": {
                "title": {"placeholder": "title", "idx": "", "font_pt": 32.0,
                          "box": [0.8, 0.5, 11.7, 1.1]},
                "body": {"placeholder": "body", "idx": "1", "font_pt": 20.0,
                         "box": [0.8, 2.0, 11.7, 4.4]},
                "caption": {"placeholder": "caption", "idx": "", "font_pt": 12.0,
                            "box": [0.8, 6.5, 11.7, 0.5]},
                "footer": {"placeholder": "ftr", "idx": "", "font_pt": 10.0,
                           "box": [0.6, 7.0, 8.0, 0.3]}}},
        ],
        "warnings": ["未提供模板：使用内置 16:9 默认槽位"],
    }


def load_profile(template="", profile=""):
    if profile:
        data = spec_io.load_json(profile)
        if data is None:
            return None
        return normalize_profile(data, os.path.basename(profile))
    if template and os.path.exists(template):
        if template.lower().endswith((".pptx", ".potx", ".pptm")):
            try:
                return probe_pptx(template)
            except Exception as exc:  # noqa: BLE001
                prof = default_profile()
                prof["warnings"].append("模板解析失败（%s），已降级为默认槽位" % exc)
                return prof
        if template.lower().endswith(".json"):
            data = spec_io.load_json(template)
            return normalize_profile(data, os.path.basename(template)) if data is not None else None
    return default_profile()


def choose_layout(profile, kind):
    layouts = profile.get("layouts") or []
    if not layouts:
        return None
    if kind == "title":
        for layout in layouts:
            name = layout["name"].lower()
            if "title slide" in name or "封面" in name or "标题幻灯片" in name:
                return layout
    for layout in layouts:
        name = layout["name"].lower()
        if ("content" in name or "内容" in name or "正文" in name) and "body" in layout["slots"]:
            return layout
    for layout in layouts:
        if "body" in layout["slots"]:
            return layout
    return layouts[0]


def _hex(value):
    value = str(value or "").strip().lstrip("#")
    if re.fullmatch(r"[0-9A-Fa-f]{6}", value):
        return tuple(int(value[i:i + 2], 16) for i in (0, 2, 4))
    return None


def _lin(channel):
    channel = channel / 255.0
    return channel / 12.92 if channel <= 0.03928 else ((channel + 0.055) / 1.055) ** 2.4


def luminance(rgb):
    r, g, b = rgb
    return 0.2126 * _lin(r) + 0.7152 * _lin(g) + 0.0722 * _lin(b)


def contrast(fg, bg):
    a, b = luminance(fg), luminance(bg)
    high, low = max(a, b), min(a, b)
    return round((high + 0.05) / (low + 0.05), 2)


def theme_color(profile, key):
    colors = profile.get("theme", {}).get("colors") or {}
    mapping = profile.get("theme", {}).get("color_map") or {}
    name = mapping.get(key, key)
    return _hex(colors.get(name))


def evaluate(spec, profile, max_chars=DEFAULT_CHARS, min_font=None):
    min_font = dict(MIN_FONT, **(min_font or {}))
    checks, slot_map = [], []
    layouts = profile.get("layouts") or []
    used = []
    for slide in spec.get("slides", []):
        layout = choose_layout(profile, slide.get("kind"))
        if layout is None:
            checks.append({"check": "layout", "level": "error",
                           "detail": "第 %d 页无可用版式" % slide["index"]})
            continue
        used.append(layout["name"])
        slots = layout["slots"]
        entry = {"slide": slide["index"], "kind": slide.get("kind"), "layout": layout["name"],
                 "slots": {name: {"placeholder": slot.get("placeholder"),
                                  "font_pt": slot.get("font_pt"),
                                  "box": slot.get("box")}
                           for name, slot in slots.items()}}
        slot_map.append(entry)
        if "title" not in slots:
            checks.append({"check": "slot_coverage", "level": "error",
                           "detail": "第 %d 页所用版式无标题槽位" % slide["index"]})
        if slide.get("kind") != "title" and "body" not in slots:
            checks.append({"check": "slot_coverage", "level": "error",
                           "detail": "第 %d 页所用版式无正文槽位" % slide["index"]})
        if (slide.get("visual") or {}).get("type") in ("figure", "table") and "caption" not in slots:
            checks.append({"check": "slot_coverage", "level": "warning",
                           "detail": "第 %d 页有图表但版式无图注槽位" % slide["index"]})
        chars = spec_io.char_len(slide.get("title")) + spec_io.char_len(slide.get("takeaway")) \
            + sum(spec_io.char_len(b) for b in slide.get("bullets") or [])
        entry["chars"] = chars
        if chars > max_chars:
            checks.append({"check": "chars_per_slide", "level": "error",
                           "detail": "第 %d 页 %d 字 > %d" % (slide["index"], chars, max_chars)})
        elif chars > max_chars * 0.8:
            checks.append({"check": "chars_per_slide", "level": "warning",
                           "detail": "第 %d 页 %d 字接近上限" % (slide["index"], chars)})

    used_names = {item["layout"] for item in slot_map}
    for layout in layouts:
        if layout["name"] not in used_names:
            continue
        slots = layout.get("slots") or {}
        for name, floor in min_font.items():
            slot = slots.get(name)
            if not slot:
                continue
            size = slot.get("font_pt")
            if size is None:
                checks.append({"check": "font_floor", "level": "warning",
                               "detail": "版式 %s 的 %s 槽位未声明字号" % (layout["name"], name)})
            elif float(size) < float(floor):
                checks.append({"check": "font_floor", "level": "error",
                               "detail": "版式 %s 的 %s 字号 %.0f < %.0f pt" % (
                                   layout["name"], name, float(size), float(floor))})

    fg, bg = theme_color(profile, "tx1"), theme_color(profile, "bg1")
    if fg and bg:
        ratio = contrast(fg, bg)
        if ratio < 4.5:
            checks.append({"check": "contrast", "level": "error",
                           "detail": "正文/背景对比度 %.2f < 4.5" % ratio})
        else:
            checks.append({"check": "contrast", "level": "info",
                           "detail": "正文/背景对比度 %.2f" % ratio})
        accent = theme_color(profile, "accent1")
        if accent:
            accent_ratio = contrast(accent, bg)
            if accent_ratio < 3.0:
                checks.append({"check": "contrast", "level": "warning",
                               "detail": "强调色/背景对比度 %.2f < 3.0" % accent_ratio})
    else:
        checks.append({"check": "contrast", "level": "warning",
                       "detail": "缺少主题色，未计算对比度"})

    width = profile["slide_size"]["w_in"]
    height = profile["slide_size"]["h_in"]
    area = max(width * height, 0.01)
    for layout in layouts:
        if layout["name"] not in used_names:
            continue
        boxes = [s.get("box") for s in (layout.get("slots") or {}).values() if s.get("box")]
        if not boxes:
            continue
        coverage = sum(float(b[2]) * float(b[3]) for b in boxes if len(b) == 4) / area
        if coverage > 0.9:
            checks.append({"check": "whitespace", "level": "error",
                           "detail": "版式 %s 槽位覆盖 %.0f%% > 90%%" % (layout["name"], coverage * 100)})
        elif coverage > 0.75:
            checks.append({"check": "whitespace", "level": "warning",
                           "detail": "版式 %s 槽位覆盖 %.0f%% > 75%%" % (layout["name"], coverage * 100)})
        for name, slot in (layout.get("slots") or {}).items():
            box = slot.get("box")
            if box and len(box) == 4 and (float(box[0]) < 0.3 or float(box[1]) < 0.25):
                checks.append({"check": "margin", "level": "warning",
                               "detail": "版式 %s 的 %s 槽位距边过近" % (layout["name"], name)})
                break

    if used and len(set(used)) > 2:
        checks.append({"check": "layout_consistency", "level": "warning",
                       "detail": "整册使用 %d 个版式，需确认页脚/标题位置一致" % len(set(used))})
    if not any("footer" in (lay.get("slots") or {}) for lay in layouts):
        checks.append({"check": "footer", "level": "warning",
                       "detail": "模板无页脚槽位，整册无法统一页脚"})

    errors = [c for c in checks if c["level"] == "error"]
    warnings = [c for c in checks if c["level"] == "warning"]
    return {"ok": not errors, "checks": checks, "slot_map": slot_map,
            "errors": len(errors), "warnings": len(warnings),
            "template": profile.get("source"), "max_chars": max_chars}


def write_reports(result, out, spec):
    spec_io.dump(result, os.path.join(out, "compliance.json"))
    spec_io.dump({"template": result["template"], "slot_map": result["slot_map"]},
                 os.path.join(out, "slot_map.json"))
    lines = ["# 模板槽位映射", "",
             "| 页 | 页型 | 版式 | 标题槽位 | 正文字号 | 图注槽位 | 页脚槽位 | 字数 |",
             "|-|-|-|-|-|-|-|-|"]
    for item in result["slot_map"]:
        slots = item["slots"]
        lines.append("| %d | %s | %s | %s | %s | %s | %s | %s |" % (
            item["slide"], item.get("kind"), item["layout"],
            (slots.get("title") or {}).get("placeholder") or "—",
            (slots.get("body") or {}).get("font_pt") or "—",
            (slots.get("caption") or {}).get("placeholder") or "—",
            (slots.get("footer") or {}).get("placeholder") or "—",
            item.get("chars", "—")))
    lines += ["", "## 合规检查", "",
              "| 检查 | 级别 | 详情 |", "|-|-|-|"]
    for check in result["checks"]:
        lines.append("| %s | %s | %s |" % (check["check"], check["level"], check["detail"]))
    if not result["checks"]:
        lines.append("| - | - | 无检查项 |")
    lines += ["", "结论：%s（硬错误 %d，警告 %d）" % (
        "PASS" if result["ok"] else "FAIL", result["errors"], result["warnings"])]
    with open(os.path.join(out, "compliance.md"), "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")
    write_profile_md(spec, out, result["template"])


def write_profile_md(profile, out, source=""):
    md = ["# 模板画像（%s）" % (source or profile.get("source") or "unknown"), "",
          "- 画布：%.2f × %.2f in" % (profile.get("slide_size", {}).get("w_in", 0),
                                     profile.get("slide_size", {}).get("h_in", 0)), ""]
    color_rows = (profile.get("theme", {}).get("colors") or {})
    font_rows = (profile.get("theme", {}).get("fonts") or {})
    if color_rows:
        md.append("- 颜色：" + "、".join("%s %s" % (k, v) for k, v in color_rows.items()))
    if font_rows:
        major = font_rows.get("major") or {}
        minor = font_rows.get("minor") or {}
        md.append("- 字体：标题 %s / 正文 %s" % (
            major.get("ea") or major.get("latin") or "未声明",
            minor.get("ea") or minor.get("latin") or "未声明"))
    md.append("")
    for layout in profile.get("layouts") or []:
        md.append("## %s" % layout["name"])
        md.append("")
        md.append("| 槽位 | 占位符 | 字号 | 位置 (in) |")
        md.append("|-|-|-|-|")
        for name, slot in layout["slots"].items():
            md.append("| %s | %s | %s | %s |" % (
                name, slot.get("placeholder"), slot.get("font_pt") or "未声明",
                slot.get("box") or "未声明"))
        md.append("")
    with open(os.path.join(out, "template_profile.md"), "w", encoding="utf-8") as fh:
        fh.write("\n".join(md) + "\n")


def cmd_probe(a):
    if not a.template or not os.path.exists(a.template):
        print("blocked: template not found:", a.template)
        return 1
    profile = load_profile(a.template)
    if profile is None:
        print("blocked: template unreadable:", a.template)
        return 1
    os.makedirs(a.out, exist_ok=True)
    spec_io.dump(profile, os.path.join(a.out, "template_profile.json"))
    write_profile_md(profile, a.out)
    print("probe: layouts=%d colors=%d warnings=%d" % (
        len(profile["layouts"]), len(profile["theme"]["colors"]), len(profile["warnings"])))
    for warning in profile["warnings"]:
        print("  ~", warning)
    return 0


def _read_spec(path, case=""):
    raw = spec_io.load_json(path)
    if raw is None:
        return None
    return spec_io.normalize_spec(raw, spec_io.load_json(case) if case else None)


def render_outputs(spec, profile, out, template="", want_pptx=True, pptx_out="",
                   base_deck="", materials_dir=""):
    os.makedirs(out, exist_ok=True)
    fitted = json.loads(json.dumps(spec))
    fitted["template"] = {"source": profile.get("source"),
                          "slide_size": profile.get("slide_size"),
                          "layouts": [lay["name"] for lay in profile.get("layouts") or []]}
    for slide in fitted["slides"]:
        layout = choose_layout(profile, slide.get("kind"))
        slide["layout"] = layout["name"] if layout else None
    spec_io.dump(fitted, os.path.join(out, "deck_spec.json"))
    with open(os.path.join(out, "deck.md"), "w", encoding="utf-8") as fh:
        fh.write(spec_io.render_marp(fitted))
    with open(os.path.join(out, "speaker_notes.md"), "w", encoding="utf-8") as fh:
        fh.write(spec_io.render_notes(fitted))
    exports, uncertainty, limits = [], [], []
    render = {"source": "deck_spec.json", "exports": exports, "tool": "none",
              "template": template or profile.get("source"), "pages": []}
    if want_pptx:
        path = pptx_out or os.path.join(out, "deck.pptx")
        built = spec_io.try_pptx(fitted, path, template, base_deck, materials_dir)
        render["tool"] = built.get("tool") or "none"
        render["pages"] = built.get("pages") or []
        render["template_inherited"] = built.get("template_inherited", False)
        if built.get("built") and not render["template_inherited"]:
            limits.append("导出未继承指定模板母版或原始演示稿；需要支持模板的环境重新生成")
        uncertainty.extend(built.get("uncertainty") or [])
        if built["built"]:
            exports.append({"path": os.path.basename(path), "format": "pptx"})
            pdf = spec_io.try_pdf(path, out)
            if pdf["built"]:
                exports.append({"path": os.path.basename(pdf["path"]), "format": "pdf"})
            else:
                limits.append("未生成 PDF 预览：%s" % pdf["reason"])
        else:
            uncertainty.append("未生成 pptx：%s" % built["reason"])
            limits.append("未产出 pptx，已交付规格 JSON、Marp 源与槽位映射")
    else:
        limits.append("按 --no-pptx 跳过 pptx")
    if not exports:
        limits.append("无 PDF/PNG 预览；需要放映件请在有 python-pptx 的环境复跑")
    return fitted, exports, uncertainty, limits, render


def cmd_fit(a):
    spec = _read_spec(a.spec, a.case)
    if spec is None:
        print("blocked: spec not found:", a.spec)
        return 1
    profile = load_profile(a.template, a.profile)
    if profile is None:
        print("blocked: template/profile unreadable")
        return 1
    min_font = {}
    for pair in (a.min_fonts or "").split(","):
        if "=" in pair:
            name, value = pair.split("=", 1)
            try:
                min_font[name.strip()] = float(value)
            except ValueError:
                pass
    result = evaluate(spec, profile, a.max_chars, min_font)
    evidence_map = []
    for slide in spec["slides"]:
        visual = slide.get("visual") or {}
        if visual.get("type") in ("figure", "table", "schematic", "photo"):
            if not visual.get("caption"):
                result["checks"].append({"check": "figure_caption", "level": "warning",
                                         "detail": "第 %d 页图表缺图注文字" % slide["index"]})
            if not visual.get("path") and visual.get("type") != "table":
                result["checks"].append({"check": "figure_source", "level": "warning",
                                         "detail": "第 %d 页图表未给图像路径，需人工核对来源"
                                                   % slide["index"]})
        if slide.get("evidence"):
            for ev in slide["evidence"]:
                evidence_map.append({"slide": slide["index"], "ref": ev.get("ref"),
                                     "quote": ev.get("quote"), "locator": ev.get("locator")})
        elif slide.get("kind") not in ("title", "backup"):
            result["checks"].append({"check": "page_evidence", "level": "warning",
                                     "detail": "第 %d 页无页级证据定位" % slide["index"]})
    output, exports, uncertainty, limits, render = render_outputs(
        spec, profile, a.out, a.template, a.pptx, a.pptx_out, a.base_deck, a.materials)
    write_reports(result, a.out, profile)
    if result["errors"]:
        limits.append("模板合规硬错误 %d 项，见 compliance.md" % result["errors"])
    uncertainty.extend(profile.get("warnings") or [])
    fields = {
        "template": {"source": profile.get("source"),
                     "slide_size": profile.get("slide_size"),
                     "theme": profile.get("theme")},
        "artifact_path": exports[0]["path"] if exports else "deck.md",
        "artifact_format": "pptx" if exports else "marp-md",
        "slide_count": len(spec_io.content_slides(spec)),
        "deck_outline": output["slides"],
        "slot_map": result["slot_map"],
        "evidence_map": evidence_map,
        "compliance": {"ok": result["ok"], "errors": result["errors"],
                       "warnings": result["warnings"], "checks": result["checks"]},
        "notes_path": "speaker_notes.md",
        "render_log": render,
        "self_check": {"ok": result["ok"], "errors": result["errors"],
                       "warnings": result["warnings"]},
    }
    draft = {"case_id": spec["case_id"],
             "status": "ok" if (result["ok"] and not limits and render.get("template_inherited") and exports and any(x.get("format") == "pdf" for x in exports) and not any(x.get("visual") in ("missing-image", "unreadable-image", "missing-table", "failed") for x in render["pages"])) else "partial",
             "fields": fields, "uncertainty": uncertainty, "changes": [],
             "limits": "；".join(limits), "sources": []}
    spec_io.dump(draft, os.path.join(a.out, "draft.json"))
    print("fit: slides=%d layouts=%d errors=%d warnings=%d pptx=%s" % (
        len(spec["slides"]), len(profile["layouts"]), result["errors"],
        result["warnings"], "yes" if exports else "no"))
    for check in result["checks"]:
        if check["level"] == "error":
            print("  !", check["detail"])
    return 0 if result["ok"] else 1


def cmd_check(a):
    spec = _read_spec(a.spec, a.case)
    if spec is None:
        print("blocked: spec not found:", a.spec)
        return 1
    profile = load_profile(a.template, a.profile)
    if profile is None:
        print("blocked: template/profile unreadable")
        return 1
    result = evaluate(spec, profile, a.max_chars)
    os.makedirs(a.out, exist_ok=True)
    write_reports(result, a.out, profile)
    print("check: errors=%d warnings=%d" % (result["errors"], result["warnings"]))
    for check in result["checks"]:
        if check["level"] == "error":
            print("  !", check["detail"])
    return 0 if result["ok"] else 1


def cmd_finalize(a):
    draft = spec_io.load_json(os.path.join(a.work, "draft.json"))
    result = spec_io.load_json(os.path.join(a.out, "result.json"))
    if draft is None or result is None:
        print("FAIL: draft.json or result.json missing")
        return 1
    for key, value in (draft.get("fields") or {}).items():
        if result.get(key) in (None, "", [], {}):
            result[key] = value
    if draft.get("case_id"):
        result["case_id"] = draft["case_id"]
    # Never silently promote a prior failed/partial result to success.
    if draft.get("status") and result.get("status") not in ("partial", "blocked", "refused"):
        result["status"] = draft["status"]
    for key in ("uncertainty", "changes", "sources"):
        if not result.get(key) and draft.get(key):
            result[key] = draft[key]
    if not result.get("limits") and draft.get("limits"):
        result["limits"] = draft["limits"]
    contract = spec_io.load_json(os.path.join(a.work, "contract.json")) or {}
    if isinstance(contract, dict):
        raw_contract = contract.get("contract")
        if raw_contract is None:
            raw_contract = contract.get("output_contract", contract)
    else:
        raw_contract = contract
    try:
        expected, schema = contract_requirements(raw_contract)
        invalid = schema_problems(result, schema)
    except ValueError as exc:
        expected, invalid = [], [str(exc)]
    missing = [key for key in expected if result.get(key) is None]
    result["contract_fields"] = len(expected)
    result["contract_missing"] = missing
    if missing or invalid:
        note = "契约字段未产出或类型无效：%s" % "、".join(missing + invalid)
        result["uncertainty"] = list(result.get("uncertainty") or []) + [note]
        result["limits"] = "；".join(x for x in (result.get("limits"), note) if x)
        if result.get("status") not in ("blocked", "refused"):
            result["status"] = "partial"
    result["contract_invalid"] = invalid
    spec_io.dump(result, os.path.join(a.out, "result.json"))
    print("finalize: %d fields merged" % len(draft.get("fields") or {}))
    return 0 if result.get("status") not in ("partial", "blocked", "refused") and not missing and not invalid else 2


def cmd_selfcheck(a):
    problems = []
    spec = spec_io.load_json(os.path.join(a.work, "deck_spec.json"))
    if not spec:
        problems.append("deck_spec.json missing")
        spec = {"slides": [], "template": {}}
    if not spec.get("template"):
        problems.append("deck_spec.json has no template block")
    for name in ("deck.md", "speaker_notes.md", "slot_map.json", "compliance.json"):
        if not os.path.exists(os.path.join(a.work, name)):
            problems.append("%s missing" % name)
    notes = os.path.join(a.work, "speaker_notes.md")
    if os.path.exists(notes):
        count = open(notes, encoding="utf-8").read().count("## 第 ")
        if count != len(spec["slides"]):
            problems.append("speaker_notes sections %d != slides %d" % (count, len(spec["slides"])))
    slot_map = spec_io.load_json(os.path.join(a.work, "slot_map.json"), {})
    if slot_map and len(slot_map.get("slot_map") or []) != len(spec["slides"]):
        problems.append("slot_map entries %d != slides %d" % (
            len(slot_map.get("slot_map") or []), len(spec["slides"])))
    result = spec_io.load_json(os.path.join(a.work, "result.json"))
    if result is not None:
        for key in ("case_id", "status"):
            if not result.get(key):
                problems.append("result.json missing %s" % key)
    print("SELFCHECK PASS" if not problems else "SELFCHECK FAIL")
    for item in problems:
        print(" -", item)
    return 0 if not problems else 1


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("probe")
    p.add_argument("--template", required=True)
    p.add_argument("--out", default="work")
    p.set_defaults(fn=cmd_probe)

    f = sub.add_parser("fit")
    f.add_argument("--spec", required=True)
    f.add_argument("--case", default="")
    f.add_argument("--template", default="")
    f.add_argument("--profile", default="")
    f.add_argument("--out", default="work")
    f.add_argument("--max-chars", type=int, default=DEFAULT_CHARS)
    f.add_argument("--min-fonts", default="")
    f.add_argument("--pptx-out", default="")
    f.add_argument("--no-pptx", dest="pptx", action="store_false")
    f.add_argument("--base-deck", default="", help="起始演示稿：在原页上改，不另起新页")
    f.add_argument("--materials", default="", help="材料目录，用于按图号查找图像文件")
    f.set_defaults(fn=cmd_fit, pptx=True)

    c = sub.add_parser("check")
    c.add_argument("--spec", required=True)
    c.add_argument("--case", default="")
    c.add_argument("--template", default="")
    c.add_argument("--profile", default="")
    c.add_argument("--out", default="work")
    c.add_argument("--max-chars", type=int, default=DEFAULT_CHARS)
    c.set_defaults(fn=cmd_check)

    fin = sub.add_parser("finalize")
    fin.add_argument("--work", default="work")
    fin.add_argument("--out", default="/app/output")
    fin.set_defaults(fn=cmd_finalize)

    s = sub.add_parser("selfcheck")
    s.add_argument("--work", default="work")
    s.set_defaults(fn=cmd_selfcheck)

    args = ap.parse_args()
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
