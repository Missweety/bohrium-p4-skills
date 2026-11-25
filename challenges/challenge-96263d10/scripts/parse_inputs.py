#!/usr/bin/env python3
"""parse_inputs.py - read the case, the manuscript and the target template/spec.

Outputs (under --work):
  inputs.json  normalized manuscript blocks with stable anchors + input manifest
  spec.json    normalized format spec with per-field provenance and conflicts

Supported inputs
  manuscript : .docx (zip+XML), .md, .txt
  template   : .docx (styles.xml + document.xml sectPr), .json, .yaml/.yml,
               .md/.txt prose requirements
  task.md    : prose requirements (lowest precedence, conservative matching)

Legacy .doc / .pdf manuscripts are converted when a converter exists
(textutil/soffice/pdftotext). If no converter exists they are reported as
unsupported instead of being silently skipped.
"""
import argparse
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common as C  # noqa: E402

SIZE_ALIASES = {
    "初号": 42, "小初": 36, "一号": 26, "小一": 24, "二号": 22, "小二": 18,
    "三号": 16, "小三": 15, "四号": 14, "小四": 12, "五号": 10.5,
    "小五": 9, "六号": 7.5, "小六": 6.5,
}
FONT_NAMES = [
    "Liberation Serif", "Liberation Sans", "Times New Roman", "Times",
    "Arial", "Helvetica", "Calibri", "Cambria", "Georgia", "Garamond",
    "Book Antiqua", "Palatino", "宋体", "黑体", "仿宋", "楷体", "楷体_GB2312",
    "仿宋_GB2312", "微软雅黑", "等线", "方正书宋", "华文中宋",
]
MANU_KW = ("manuscript", "draft", "paper", "article", "submission", "source",
           "original", "正文", "稿件", "论文", "原稿", "待排版", "未排版")
TPL_KW = ("template", "spec", "style", "requirement", "format", "guideline",
          "模板", "规格", "格式", "要求", "规范", "投稿", "样式")
REF_HEADINGS = ("references", "reference", "bibliography", "works cited",
                "literature cited", "参考文献", "引用文献", "参考书目")
CAPTION_RE = re.compile(
    r"^\s*(?P<label>Figure|Fig\.?|FIG\.?|Table|Tab\.?|图|表)\s*"
    r"(?P<num>\d+|[IVXLC]+|[一二三四五六七八九十]+)\s*"
    r"(?P<sep>[\.．:：、\-–—]?)\s*(?P<text>.*)$")
HEADING_TEXT_RE = re.compile(
    r"^(?P<num>\d+(?:\.\d+){0,3})[\.、\s]+\S")
CN_CHAPTER_RE = re.compile(r"^第[一二三四五六七八九十百零\d]+[章篇部分]\s*\S")
UNSUPPORTED_CUES = re.compile(
    r"公式|equation|页眉|header|脚注|footnote|水印|watermark|行号|line number|"
    r"上标|superscript|封面|cover page|图表目录|list of figures|"
    r"批注|comment|域代码|field code", re.I)


# ------------------------------------------------------------------ tiny yaml
def parse_simple_yaml(text):
    """Minimal block-YAML parser (nested maps, lists, scalars) with no deps."""
    lines = []
    for raw in text.splitlines():
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        lines.append(raw.rstrip())
    if not lines:
        return None

    def scalar(value):
        value = value.strip()
        if value[:1] in "\"'" and value[-1:] == value[:1] and len(value) >= 2:
            return value[1:-1]
        low = value.lower()
        if low in ("true", "yes", "on"):
            return True
        if low in ("false", "no", "off"):
            return False
        if low in ("null", "none", "~", ""):
            return None
        if re.match(r"^-?\d+$", value):
            return int(value)
        if re.match(r"^-?\d+\.\d+$", value):
            return float(value)
        if value.startswith("[") and value.endswith("]"):
            inner = value[1:-1].strip()
            return [scalar(x) for x in inner.split(",")] if inner else []
        return value

    def parse_block(start, indent):
        node = {}
        items = []
        i = start
        while i < len(lines):
            line = lines[i]
            cur = len(line) - len(line.lstrip())
            if cur < indent:
                break
            if cur > indent:
                i += 1
                continue
            body = line.strip()
            if body.startswith("- "):
                items.append(scalar(body[2:]))
                i += 1
                continue
            if ":" not in body:
                i += 1
                continue
            key, _, rest = body.partition(":")
            key = key.strip()
            rest = rest.strip()
            if rest:
                node[key] = scalar(rest)
                i += 1
            else:
                child_indent = None
                j = i + 1
                while j < len(lines):
                    nxt = lines[j]
                    ni = len(nxt) - len(nxt.lstrip())
                    if ni <= cur:
                        break
                    child_indent = ni
                    break
                if child_indent is None:
                    node[key] = None
                    i += 1
                else:
                    child, i = parse_block(j, child_indent)
                    node[key] = child
        return (items if items and not node else node), i

    parsed, _ = parse_block(0, len(lines[0]) - len(lines[0].lstrip()))
    return parsed if isinstance(parsed, dict) else None


# ------------------------------------------------------------------ value parsers
def to_number(value):
    if isinstance(value, (int, float)):
        return float(value)
    if not isinstance(value, str):
        return None
    m = re.search(r"-?\d+(?:\.\d+)?", value)
    return float(m.group(0)) if m else None


def length_to_cm(value, default_unit="cm"):
    if isinstance(value, (int, float)):
        return float(value) if default_unit == "cm" else None
    if not isinstance(value, str):
        return None
    low = value.strip().lower()
    m = re.search(r"(-?\d+(?:\.\d+)?)\s*(cm|厘米|mm|毫米|pt|磅|inch|in|\"|'')?", low)
    if not m:
        return None
    num = float(m.group(1))
    unit = (m.group(2) or default_unit).lower()
    if unit in ("cm", "厘米"):
        return round(num, 3)
    if unit in ("mm", "毫米"):
        return round(num / 10.0, 3)
    if unit in ("pt", "磅"):
        return round(num * 2.54 / 72.0, 3)
    if unit in ("inch", "in", '"', "''"):
        return round(num * 2.54, 3)
    return round(num, 3)


def size_to_pt(value):
    if isinstance(value, (int, float)):
        return float(value)
    if not isinstance(value, str):
        return None
    text = value.strip()
    for alias, pt in SIZE_ALIASES.items():
        if alias in text:
            return float(pt)
    m = re.search(r"(\d+(?:\.\d+)?)\s*(pt|磅)", text, re.I)
    if m:
        return float(m.group(1))
    num = to_number(text)
    if num and 4 <= num <= 72:
        return num
    return None


def parse_line_spacing(value):
    if isinstance(value, (int, float)):
        return {"type": "multiple", "value": float(value)}
    if isinstance(value, dict):
        kind = str(value.get("type") or value.get("rule") or "multiple").lower()
        if kind in ("exact", "fixed", "固定值"):
            pt = size_to_pt(value.get("value_pt") or value.get("value"))
            return {"type": "exact", "value_pt": pt} if pt else None
        num = to_number(value.get("value") or value.get("multiplier"))
        return {"type": "multiple", "value": num} if num else None
    if not isinstance(value, str):
        return None
    text = value.strip().lower()
    if re.search(r"固定值|exact|fixed", text):
        pt = size_to_pt(text)
        return {"type": "exact", "value_pt": pt} if pt else None
    m = re.search(r"(\d+(?:\.\d+)?)\s*(倍|lines?|line)?", text)
    if m:
        return {"type": "multiple", "value": float(m.group(1))}
    if "single" in text or "单倍" in text:
        return {"type": "multiple", "value": 1.0}
    if "double" in text or "双倍" in text:
        return {"type": "multiple", "value": 2.0}
    return None


def norm_align(value):
    if not isinstance(value, str):
        return None
    low = value.strip().lower()
    table = {"left": "left", "左": "left", "center": "center", "centre": "center",
             "居中": "center", "right": "right", "右": "right",
             "justify": "both", "两端对齐": "both", "both": "both",
             "两端": "both", "distributed": "distribute"}
    for key, val in table.items():
        if key in low:
            return val
    return None


PAPER_SIZES_CM = {"a4": (21.0, 29.7), "a5": (14.8, 21.0), "a3": (29.7, 42.0),
                  "b5": (17.6, 25.0), "letter": (21.59, 27.94),
                  "legal": (21.59, 35.56)}


def page_size_name(width_cm, height_cm):
    if not width_cm or not height_cm:
        return None
    w, h = sorted([width_cm, height_cm])
    known = {"A4": (21.0, 29.7), "A5": (14.8, 21.0), "A3": (29.7, 42.0),
             "B5": (17.6, 25.0), "Letter": (21.59, 27.94),
             "Legal": (21.59, 35.56)}
    for name, (kw, kh) in known.items():
        if abs(w - kw) <= 0.15 and abs(h - kh) <= 0.15:
            return name
    return "custom"


def set_paper_size(sb, name, source, raw=None, priority=2, derive=True):
    """Record a named paper size and derive width/height unless already specified."""
    nm = str(name or "").strip()
    if not nm:
        return
    sb.set("page.size_name", nm, source, raw if raw is not None else name, priority)
    dims = PAPER_SIZES_CM.get(nm.lower())
    if not dims or not derive:
        return
    prov = sb.spec.get("provenance") or {}
    for field, dim in (("page.width_cm", dims[0]), ("page.height_cm", dims[1])):
        if (prov.get(field) or {}).get("priority", 0) <= 0:
            sb.set(field, dim, source, nm, priority)


# ------------------------------------------------------------------ spec builder
def default_spec():
    return {
        "schema": "format-spec/v1",
        "page": {"size_name": "A4", "width_cm": 21.0, "height_cm": 29.7,
                 "orientation": "portrait", "columns": 1,
                 "margins_cm": {"top": 2.54, "bottom": 2.54,
                                "left": 2.54, "right": 2.54}},
        "body": {"font_latin": "Liberation Serif",
                 "font_east_asia": "Liberation Serif", "size_pt": 12.0,
                 "line_spacing": {"type": "multiple", "value": 1.5},
                 "first_line_indent_cm": 0.74, "space_before_pt": 0.0,
                 "space_after_pt": 0.0, "alignment": "both"},
        "headings": {
            "1": {"size_pt": 16.0, "bold": True, "alignment": "left",
                  "space_before_pt": 12.0, "space_after_pt": 6.0,
                  "page_break_before": False},
            "2": {"size_pt": 14.0, "bold": True, "alignment": "left",
                  "space_before_pt": 10.0, "space_after_pt": 4.0,
                  "page_break_before": False},
            "3": {"size_pt": 12.0, "bold": True, "alignment": "left",
                  "space_before_pt": 8.0, "space_after_pt": 3.0,
                  "page_break_before": False},
        },
        "heading_numbering": {
            "enabled": True,
            "levels": [{"ilvl": 0, "numFmt": "decimal", "lvlText": "%1"},
                       {"ilvl": 1, "numFmt": "decimal", "lvlText": "%1.%2"},
                       {"ilvl": 2, "numFmt": "decimal", "lvlText": "%1.%2.%3"}],
        },
        "captions": {
            "figure": {"label": "Figure", "separator": ". ", "position": "below",
                       "size_pt": 10.0, "alignment": "center", "bold": False,
                       "italic": False},
            "table": {"label": "Table", "separator": ". ", "position": "above",
                      "size_pt": 10.0, "alignment": "left", "bold": False,
                      "italic": False},
        },
        "references": {"heading": "References", "style": "numeric_bracket",
                       "size_pt": 10.0, "hanging_indent_cm": 0.74,
                       "line_spacing": 1.0},
        "page_numbers": {"enabled": True, "position": "footer_center",
                         "fmt": "decimal", "start": 1},
        "header": {"enabled": False, "text": None},
        "toc": {"enabled": False},
        "tables": {"style": "grid"},
        "export": {"formats": ["docx"]},
        "provenance": {},
        "conflicts": [],
        "unknown": [],
        "meta": {"template_used": False, "template_path": None,
                 "template_missing": True, "spec_sources": [],
                 "default_fields": []},
    }


class SpecBuilder:
    """Sets spec values with provenance, precedence and conflict records."""

    def __init__(self):
        self.spec = default_spec()
        for path, value in self._flatten(self.spec).items():
            if path.startswith(("provenance", "conflicts", "unknown", "meta", "schema")):
                continue
            self.spec["provenance"][path] = {
                "source": "builtin-default", "raw": value, "value": value,
                "priority": 0}
            self.spec["meta"]["default_fields"].append(path)

    @staticmethod
    def _flatten(obj, prefix=""):
        out = {}
        if isinstance(obj, dict):
            for key, val in obj.items():
                path = "%s.%s" % (prefix, key) if prefix else str(key)
                if isinstance(val, dict):
                    out.update(SpecBuilder._flatten(val, path))
                else:
                    out[path] = val
        return out

    def get(self, path, default=None):
        node = self.spec
        for part in path.split("."):
            if not isinstance(node, dict) or part not in node:
                return default
            node = node[part]
        return node

    def set(self, path, value, source, raw=None, priority=1):
        if value is None:
            return False
        current = self.get(path)
        prev = self.spec["provenance"].get(path, {})
        prev_pri = prev.get("priority", 0)
        if current is not None and prev_pri > priority:
            if not self._same(current, value):
                self.spec["conflicts"].append({
                    "field": path, "kept": current,
                    "kept_source": prev.get("source", "?"),
                    "ignored": value, "ignored_source": source,
                    "note": "higher-precedence source wins"})
            return False
        if current is not None and not self._same(current, value) and prev_pri == priority:
            self.spec["conflicts"].append({
                "field": path, "kept": current,
                "kept_source": prev.get("source", "?"),
                "ignored": value, "ignored_source": source,
                "note": "same precedence, first source wins"})
            return False
        parts = path.split(".")
        node = self.spec
        for part in parts[:-1]:
            node = node.setdefault(part, {})
            if not isinstance(node, dict):
                return False
        node[parts[-1]] = value
        self.spec["provenance"][path] = {
            "source": source, "raw": raw if raw is not None else value,
            "value": value, "priority": priority}
        if "builtin-default" not in source and path in self.spec["meta"]["default_fields"]:
            self.spec["meta"]["default_fields"].remove(path)
        return True

    @staticmethod
    def _same(a, b):
        if isinstance(a, (int, float)) and isinstance(b, (int, float)):
            return abs(float(a) - float(b)) < 1e-6
        return a == b


# ------------------------------------------------------------------ template docx
def spec_from_docx(path, sb):
    src = os.path.basename(path)
    try:
        docx = C.Docx(path)
    except Exception as exc:  # noqa: BLE001
        return {"error": "%s: %s" % (type(exc).__name__, exc)}
    report = {"used": True, "styles_found": [], "numbering_found": False,
              "footer_found": False, "warnings": []}
    try:
        styles = docx.xml("word/styles.xml")
        doc = docx.xml("word/document.xml")
        smap, by_name = C.style_map(styles)
        dd = C.doc_defaults(styles)
        sect = C.sect_properties(doc)

        if sect.get("page_width_twips") and sect.get("page_height_twips"):
            w_cm = C.twips_to_cm(sect["page_width_twips"])
            h_cm = C.twips_to_cm(sect["page_height_twips"])
            if sect.get("orientation") == "landscape" and w_cm < h_cm:
                w_cm, h_cm = h_cm, w_cm
            sb.set("page.width_cm", w_cm,
                   "%s!word/document.xml#sectPr/pgSz@w" % src,
                   sect["page_width_twips"], 1)
            sb.set("page.height_cm", h_cm,
                   "%s!word/document.xml#sectPr/pgSz@h" % src,
                   sect["page_height_twips"], 1)
            sb.set("page.size_name", page_size_name(w_cm, h_cm),
                   "%s!pgSz" % src, None, 1)
            sb.set("page.orientation",
                   sect.get("orientation") or "portrait",
                   "%s!word/document.xml#sectPr/pgSz@orient" % src, None, 1)
        margins = sect.get("margins_twips") or {}
        for side in ("top", "bottom", "left", "right"):
            if side in margins:
                sb.set("page.margins_cm.%s" % side,
                       C.twips_to_cm(margins[side]),
                       "%s!word/document.xml#sectPr/pgMar@%s" % (src, side),
                       margins[side], 1)
        if sect.get("columns"):
            sb.set("page.columns", int(sect["columns"]),
                   "%s!word/document.xml#sectPr/w:cols@num" % src,
                   sect["columns"], 1)

        normal = None
        for sid, info in smap.items():
            if sid == "Normal" or (info.get("default") and info.get("type") == "paragraph"):
                normal = info
                break
        body_font = (normal or {}).get("font_latin") or dd.get("font_latin")
        body_east = (normal or {}).get("font_east_asia") or dd.get("font_east_asia")
        body_size = (normal or {}).get("size_pt") or dd.get("size_pt")
        body_line = (normal or {}).get("spacing_line") or dd.get("spacing_line")
        body_rule = (normal or {}).get("line_rule") or dd.get("line_rule")
        body_indent = (normal or {}).get("first_line_twips")
        if body_indent is None:
            body_indent = dd.get("first_line_twips")
        body_align = (normal or {}).get("align") or dd.get("align")
        normal_ref = ("%s!word/styles.xml#style[Normal]" % src if normal
                      else "%s!word/styles.xml#docDefaults" % src)
        if body_font:
            sb.set("body.font_latin", body_font, normal_ref + "/w:rFonts@ascii", body_font, 1)
        if body_east:
            sb.set("body.font_east_asia", body_east,
                   normal_ref + "/w:rFonts@eastAsia", body_east, 1)
        if body_size:
            sb.set("body.size_pt", body_size, normal_ref + "/w:sz", body_size, 1)
        if body_line:
            if (body_rule or "auto") == "auto":
                sb.set("body.line_spacing",
                       {"type": "multiple", "value": round(body_line / 240.0, 3)},
                       normal_ref + "/w:spacing@line", body_line, 1)
            else:
                sb.set("body.line_spacing",
                       {"type": "exact", "value_pt": round(body_line / 20.0, 2)},
                       normal_ref + "/w:spacing@line(exact)", body_line, 1)
        if body_indent is not None:
            sb.set("body.first_line_indent_cm", C.twips_to_cm(body_indent),
                   normal_ref + "/w:ind@firstLine", body_indent, 1)
        if body_align:
            sb.set("body.alignment", body_align,
                   normal_ref + "/w:jc", body_align, 1)

        # headings -------------------------------------------------------
        heading_ids = {}
        for ilvl in range(1, 5):
            sid = None
            for cand, info in smap.items():
                if C.heading_level_from_style(cand, info.get("name")) == ilvl:
                    sid = cand
                    break
            if not sid:
                for name_low, cand in by_name.items():
                    if C.heading_level_from_style(cand, name_low) == ilvl:
                        sid = cand
                        break
            if not sid:
                continue
            heading_ids[ilvl] = sid
            info = smap[sid]
            ref = "%s!word/styles.xml#style[%s]" % (src, sid)
            report["styles_found"].append({"level": ilvl, "style_id": sid,
                                           "name": info.get("name")})
            key = str(ilvl)
            base = sb.get("headings.%s" % key) or {}
            if info.get("size_pt"):
                sb.set("headings.%s.size_pt" % key, info["size_pt"], ref + "/w:sz", None, 1)
            if info.get("bold") is not None:
                sb.set("headings.%s.bold" % key, bool(info["bold"]), ref + "/w:b", None, 1)
            if info.get("font_latin"):
                sb.set("headings.%s.font_latin" % key, info["font_latin"],
                       ref + "/w:rFonts@ascii", None, 1)
            if info.get("font_east_asia"):
                sb.set("headings.%s.font_east_asia" % key, info["font_east_asia"],
                       ref + "/w:rFonts@eastAsia", None, 1)
            if info.get("align"):
                sb.set("headings.%s.alignment" % key, info["align"], ref + "/w:jc", None, 1)
            if info.get("before_pt") is not None:
                sb.set("headings.%s.space_before_pt" % key, info["before_pt"],
                       ref + "/w:spacing@before", None, 1)
            if info.get("after_pt") is not None:
                sb.set("headings.%s.space_after_pt" % key, info["after_pt"],
                       ref + "/w:spacing@after", None, 1)
            if info.get("page_break_before") is not None:
                sb.set("headings.%s.page_break_before" % key,
                       bool(info["page_break_before"]), ref + "/w:pageBreakBefore", None, 1)
            if not base.get("size_pt") and not info.get("size_pt"):
                report["warnings"].append(
                    "heading level %d style %s has no explicit size" % (ilvl, sid))

        # heading numbering (reverse-engineer template numbering.xml) ---
        numbering = docx.xml("word/numbering.xml")
        nums, abstracts = C.numbering_map(numbering)
        num_id = None
        for ilvl, sid in sorted(heading_ids.items()):
            if smap[sid].get("num_id"):
                num_id = smap[sid].get("num_id")
                break
        if num_id is None:
            for p in doc.iter(C.qn("w", "p")):
                ppr = p.find(C.qn("w", "pPr"))
                if ppr is None:
                    continue
                pstyle = ppr.find(C.qn("w", "pStyle"))
                if pstyle is None:
                    continue
                if C.heading_level_from_style(pstyle.get(C.qn("w", "val")), ""):
                    numpr = ppr.find(C.qn("w", "numPr"))
                    if numpr is not None:
                        nid = numpr.find(C.qn("w", "numId"))
                        ilvl_el = numpr.find(C.qn("w", "ilvl"))
                        if nid is not None:
                            num_id = nid.get(C.qn("w", "val"))
                            report["numbering_found"] = True
                            break
        levels = []
        if num_id and num_id in nums:
            abstract = abstracts.get(nums[num_id]["abstract"], {})
            for ilvl in range(0, max(3, len(abstract))):
                lvl = abstract.get(ilvl)
                if not lvl:
                    continue
                levels.append({"ilvl": ilvl, "numFmt": lvl.get("numFmt") or "decimal",
                               "lvlText": lvl.get("lvlText") or ""})
                if len(levels) >= 4:
                    break
        if levels:
            report["numbering_found"] = True
            sb.set("heading_numbering.enabled", True,
                   "%s!word/numbering.xml#num[%s]" % (src, num_id), num_id, 1)
            sb.set("heading_numbering.levels", levels,
                   "%s!word/numbering.xml#abstractNum[%s]"
                   % (src, nums[num_id]["abstract"]), levels, 1)
        elif heading_ids:
            # heading styles exist but carry no numbering definition
            sb.set("heading_numbering.enabled", False,
                   "%s!word/styles.xml#heading styles without w:numPr" % src, None, 1)

        # caption style --------------------------------------------------
        for sid, info in smap.items():
            name = (info.get("name") or sid).lower()
            if name in ("caption", "题注") or sid.lower() in ("caption",):
                ref = "%s!word/styles.xml#style[%s]" % (src, sid)
                if info.get("size_pt"):
                    sb.set("captions.figure.size_pt", info["size_pt"], ref + "/w:sz", None, 1)
                    sb.set("captions.table.size_pt", info["size_pt"], ref + "/w:sz", None, 1)
                if info.get("align"):
                    sb.set("captions.figure.alignment", info["align"], ref + "/w:jc", None, 1)
                if info.get("bold") is not None:
                    sb.set("captions.figure.bold", bool(info["bold"]), ref + "/w:b", None, 1)
                    sb.set("captions.table.bold", bool(info["bold"]), ref + "/w:b", None, 1)
                break

        # bibliography style --------------------------------------------
        for sid, info in smap.items():
            name = (info.get("name") or "").lower()
            if name in ("bibliography", "references", "reference", "参考文献"):
                ref = "%s!word/styles.xml#style[%s]" % (src, sid)
                if info.get("size_pt"):
                    sb.set("references.size_pt", info["size_pt"], ref + "/w:sz", None, 1)
                hang = info.get("hanging_twips")
                if hang:
                    sb.set("references.hanging_indent_cm", C.twips_to_cm(hang),
                           ref + "/w:ind@hanging", None, 1)
                break

        # footer / page numbers -----------------------------------------
        if sect.get("footer_ref"):
            footer_name = "word/footer1.xml"
            rels = _rels_map(docx, "word/_rels/document.xml.rels")
            target = rels.get(sect["footer_ref"], {}).get("target")
            if target:
                footer_name = "word/" + target.lstrip("/").replace("word/", "")
            footer_xml = docx.text_xml(footer_name)
            report["footer_found"] = bool(footer_xml)
            if " PAGE " in footer_xml or "PAGE" in footer_xml:
                sb.set("page_numbers.enabled", True,
                       "%s!%s#w:instrText=PAGE" % (src, footer_name), None, 1)
                align = _footer_align(footer_xml)
                if align:
                    sb.set("page_numbers.position", "footer_%s" % align,
                           "%s!%s#w:jc" % (src, footer_name), align, 1)
                if sect.get("page_number_fmt"):
                    sb.set("page_numbers.fmt", sect["page_number_fmt"],
                           "%s!word/document.xml#sectPr/w:pgNumType@fmt" % src, None, 1)
                if sect.get("page_number_start") is not None:
                    sb.set("page_numbers.start", sect["page_number_start"],
                           "%s!word/document.xml#sectPr/w:pgNumType@start" % src, None, 1)
        if sect.get("header_ref"):
            rels = _rels_map(docx, "word/_rels/document.xml.rels")
            target = rels.get(sect["header_ref"], {}).get("target")
            if target:
                header_name = "word/" + target.lstrip("/").replace("word/", "")
                header_text = _header_text(docx.text_xml(header_name))
                if header_text:
                    sb.set("header.enabled", True,
                           "%s!%s" % (src, header_name), None, 1)
                    sb.set("header.text", header_text,
                           "%s!%s#w:t" % (src, header_name), header_text, 1)
    finally:
        docx.close()

    report["styles_found_count"] = len(report["styles_found"])
    return report


def _rels_map(docx, name):
    root = docx.xml(name)
    out = {}
    if root is None:
        return out
    for rel in root:
        rid = rel.get("Id")
        if rid:
            out[rid] = {"type": rel.get("Type", ""), "target": rel.get("Target", "")}
    return out


def _footer_align(xml_text):
    m = re.search(r"<w:jc[^>]*w:val=\"(left|center|right|both)\"", xml_text or "")
    return m.group(1) if m else None


def _header_text(xml_text):
    if not xml_text:
        return None
    texts = re.findall(r"<w:t[^>]*>(.*?)</w:t>", xml_text, re.S)
    joined = "".join(re.sub(r"<[^>]+>", "", t) for t in texts).strip()
    return joined or None


# ------------------------------------------------------------------ json spec
def spec_from_json(data, sb, source):
    used = []
    page = _pick(data, "page", "页面", "纸张")
    if isinstance(page, dict):
        has_dims = (any(k in page for k in ("width_cm", "width", "宽")) and
                    any(k in page for k in ("height_cm", "height", "高")))
        for key in ("size_name", "size", "paper", "纸张", "页面大小"):
            if key in page:
                set_paper_size(sb, page[key], "%s#page.%s" % (source, key),
                               page[key], 2, derive=not has_dims)
                used.append("page.size")
                break
        for key in ("width_cm", "width", "宽"):
            if key in page:
                cm = length_to_cm(page[key])
                if cm:
                    sb.set("page.width_cm", cm, "%s#page.%s" % (source, key), page[key], 2)
        for key in ("height_cm", "height", "高"):
            if key in page:
                cm = length_to_cm(page[key])
                if cm:
                    sb.set("page.height_cm", cm, "%s#page.%s" % (source, key), page[key], 2)
        for key in ("margins", "margins_cm", "margin", "页边距"):
            if key in page:
                _apply_margins(page[key], sb, "%s#page.%s" % (source, key), 2)
                used.append("page.margins")
        for key in ("columns", "栏数", "column_count"):
            if key in page:
                num = to_number(page[key])
                if num:
                    sb.set("page.columns", int(num),
                           "%s#page.%s" % (source, key), page[key], 2)
    for key in ("size_name", "page_size", "paper", "纸张", "页面大小"):
        if key in data:
            set_paper_size(sb, data[key], "%s#%s" % (source, key), data[key], 2)
    for key in ("orientation", "方向"):
        if key in data:
            sb.set("page.orientation", str(data[key]).lower(),
                   "%s#%s" % (source, key), data[key], 2)
    for key in ("columns", "栏数", "column_count"):
        if key in data:
            num = to_number(data[key])
            if num:
                sb.set("page.columns", int(num), "%s#%s" % (source, key), data[key], 2)
    for key in ("margins", "margins_cm", "margin", "页边距"):
        if key in data:
            _apply_margins(data[key], sb, "%s#%s" % (source, key), 2)

    body = _pick(data, "body", "text", "正文", "paragraph")
    if isinstance(body, dict):
        _apply_body_json(body, sb, "%s#body" % source)
    for key in ("font", "font_family", "fontFamily", "字体", "body_font"):
        if key in data:
            _apply_font_json(data[key], sb, "%s#%s" % (source, key))
    for key in ("font_size", "fontSize", "size_pt", "字号", "body_font_size"):
        if key in data:
            pt = size_to_pt(data[key])
            if pt:
                sb.set("body.size_pt", pt, "%s#%s" % (source, key), data[key], 2)
    for key in ("line_spacing", "lineSpacing", "行距"):
        if key in data:
            ls = parse_line_spacing(data[key])
            if ls:
                sb.set("body.line_spacing", ls, "%s#%s" % (source, key), data[key], 2)
    for key in ("first_line_indent", "firstLineIndent", "indent", "首行缩进"):
        if key in data:
            cm = _indent_to_cm(data[key], sb.get("body.size_pt") or 12)
            if cm is not None:
                sb.set("body.first_line_indent_cm", cm,
                       "%s#%s" % (source, key), data[key], 2)
    for key in ("alignment", "align", "对齐"):
        if key in data:
            al = norm_align(str(data[key]))
            if al:
                sb.set("body.alignment", al, "%s#%s" % (source, key), data[key], 2)

    headings = _pick(data, "headings", "heading", "标题")
    if isinstance(headings, dict):
        for key, item in headings.items():
            lvl = to_number(re.sub(r"[^0-9]", "", str(key)) or "0")
            if not lvl or not isinstance(item, dict):
                continue
            _apply_heading_json(int(lvl), item, sb, "%s#headings.%s" % (source, key))
    elif isinstance(headings, list):
        for idx, item in enumerate(headings):
            if isinstance(item, dict):
                lvl = int(to_number(item.get("level")) or (idx + 1))
                _apply_heading_json(lvl, item, sb, "%s#headings[%d]" % (source, idx))
    for key in ("heading_numbering", "headingNumbering", "标题编号"):
        if key in data:
            value = data[key]
            if isinstance(value, bool):
                sb.set("heading_numbering.enabled", value,
                       "%s#%s" % (source, key), value, 2)
            elif isinstance(value, dict):
                if "enabled" in value:
                    sb.set("heading_numbering.enabled", bool(value["enabled"]),
                           "%s#%s.enabled" % (source, key), None, 2)
                levels = value.get("levels")
                if isinstance(levels, list):
                    sb.set("heading_numbering.levels", levels,
                           "%s#%s.levels" % (source, key), levels, 2)
            elif isinstance(value, str):
                levels = _numbering_from_pattern(value)
                if levels:
                    sb.set("heading_numbering.enabled", True,
                           "%s#%s" % (source, key), value, 2)
                    sb.set("heading_numbering.levels", levels,
                           "%s#%s" % (source, key), value, 2)

    captions = _pick(data, "captions", "caption", "题注", "图表题注")
    if isinstance(captions, dict):
        for kind in ("figure", "table"):
            item = captions.get(kind) or captions.get("图" if kind == "figure" else "表")
            if isinstance(item, dict):
                _apply_caption_json(kind, item, sb, "%s#captions.%s" % (source, kind))
    for kind, keys in (("figure", ("figure_caption", "{figure_caption}", "图注")),
                       ("table", ("table_caption", "表注"))):
        for key in keys:
            if key in data and isinstance(data[key], dict):
                _apply_caption_json(kind, data[key], sb, "%s#%s" % (source, key))

    refs = _pick(data, "references", "bibliography", "refs", "参考文献")
    if isinstance(refs, dict):
        for key in ("heading", "title", "标题"):
            if key in refs:
                sb.set("references.heading", str(refs[key]).strip(),
                       "%s#references.%s" % (source, key), refs[key], 2)
        for key in ("style", "format", "样式"):
            if key in refs:
                style = _norm_ref_style(str(refs[key]))
                if style:
                    sb.set("references.style", style,
                           "%s#references.%s" % (source, key), refs[key], 2)
        for key in ("size_pt", "font_size", "字号"):
            if key in refs:
                pt = size_to_pt(refs[key])
                if pt:
                    sb.set("references.size_pt", pt,
                           "%s#references.%s" % (source, key), refs[key], 2)
        for key in ("hanging_indent_cm", "hanging_indent", "悬挂缩进"):
            if key in refs:
                cm = _indent_to_cm(refs[key], sb.get("body.size_pt") or 12)
                if cm is not None:
                    sb.set("references.hanging_indent_cm", cm,
                           "%s#references.%s" % (source, key), refs[key], 2)
        for key in ("line_spacing", "行距"):
            if key in refs:
                ls = parse_line_spacing(refs[key])
                if ls:
                    sb.set("references.line_spacing",
                           (ls.get("value") if ls.get("type") == "multiple"
                            else ls.get("value_pt")),
                           "%s#references.%s" % (source, key), refs[key], 2)

    pn = _pick(data, "page_numbers", "pageNumbers", "页码")
    if isinstance(pn, bool):
        sb.set("page_numbers.enabled", pn, "%s#page_numbers" % source, pn, 2)
    elif isinstance(pn, dict):
        if "enabled" in pn:
            sb.set("page_numbers.enabled", bool(pn["enabled"]),
                   "%s#page_numbers.enabled" % source, None, 2)
        for key in ("position", "位置"):
            if key in pn:
                pos = str(pn[key]).lower()
                sb.set("page_numbers.position", _norm_pn_position(pos),
                       "%s#page_numbers.%s" % (source, key), pn[key], 2)
        for key in ("fmt", "format", "格式"):
            if key in pn:
                sb.set("page_numbers.fmt", str(pn[key]).lower(),
                       "%s#page_numbers.%s" % (source, key), pn[key], 2)
        if "start" in pn:
            num = to_number(pn["start"])
            if num is not None:
                sb.set("page_numbers.start", int(num),
                       "%s#page_numbers.start" % source, pn["start"], 2)
    for key in ("page_number", "has_page_number", "带页码"):
        if key in data and isinstance(data[key], bool):
            sb.set("page_numbers.enabled", data[key],
                   "%s#%s" % (source, key), data[key], 2)

    hdr = _pick(data, "header", "页眉")
    if isinstance(hdr, dict):
        if "enabled" in hdr:
            sb.set("header.enabled", bool(hdr["enabled"]),
                   "%s#header.enabled" % source, None, 2)
        for key in ("text", "content", "文本", "内容"):
            if key in hdr and hdr[key]:
                sb.set("header.text", str(hdr[key]),
                       "%s#header.%s" % (source, key), hdr[key], 2)
    for key in ("toc", "table_of_contents", "目录"):
        if key in data:
            value = data[key]
            enabled = value if isinstance(value, bool) else bool(
                value.get("enabled") if isinstance(value, dict) else value)
            sb.set("toc.enabled", enabled, "%s#%s" % (source, key), value, 2)

    exports = _pick(data, "export", "exports", "导出", "output_format")
    if exports:
        formats = exports.get("formats") if isinstance(exports, dict) else exports
        if isinstance(formats, str):
            formats = [formats]
        if isinstance(formats, list):
            formats = [str(f).lower().lstrip(".") for f in formats if f]
            sb.set("export.formats", formats, "%s#export" % source, formats, 2)

    tables_cfg = _pick(data, "tables", "table", "表格")
    if isinstance(tables_cfg, dict):
        for key in ("style", "border", "borders", "样式", "边框"):
            if key in tables_cfg:
                style = str(tables_cfg[key]).lower()
                if "three" in style or "三线" in style:
                    style = "three_line"
                elif "none" in style or "无" in style:
                    style = "none"
                else:
                    style = "grid"
                sb.set("tables.style", style, "%s#tables.%s" % (source, key),
                       tables_cfg[key], 2)
                break
    elif isinstance(tables_cfg, str):
        style = tables_cfg.lower()
        sb.set("tables.style", "three_line" if ("three" in style or "三线" in style)
               else "grid", "%s#tables" % source, tables_cfg, 2)

    known = {"page", "body", "text", "headings", "heading", "captions", "caption",
             "references", "bibliography", "refs", "page_numbers", "pageNumbers",
             "header", "toc", "export", "exports", "schema", "template", "meta"}
    for key in data:
        if key not in known and isinstance(data[key], (str, int, float, bool)):
            sb.spec["unknown"].append({"key": key, "value": data[key],
                                       "source": source})
    return used


def _pick(data, *keys):
    for key in keys:
        if key in data:
            return data[key]
    return None


def _apply_margins(value, sb, source, priority):
    if isinstance(value, dict):
        for side, aliases in (("top", ("top", "上")),
                              ("bottom", ("bottom", "下")),
                              ("left", ("left", "左", "inner")),
                              ("right", ("right", "右", "outer"))):
            for alias in aliases:
                if alias in value:
                    cm = length_to_cm(value[alias])
                    if cm is not None:
                        sb.set("page.margins_cm.%s" % side, cm,
                               "%s.%s" % (source, alias), value[alias], priority)
                    break
    elif isinstance(value, (list, tuple)) and len(value) >= 4:
        for side, item in zip(("top", "bottom", "left", "right"), value[:4]):
            cm = length_to_cm(item)
            if cm is not None:
                sb.set("page.margins_cm.%s" % side, cm, source, item, priority)
    else:
        cm = length_to_cm(value)
        if cm is not None:
            for side in ("top", "bottom", "left", "right"):
                sb.set("page.margins_cm.%s" % side, cm, source, value, priority)


def _apply_font_json(value, sb, source):
    if isinstance(value, dict):
        for key in ("latin", "ascii", "west", "西文", "font", "family"):
            if key in value:
                sb.set("body.font_latin", str(value[key]),
                       "%s.%s" % (source, key), value[key], 2)
                break
        for key in ("east_asia", "eastAsia", "中文", "cjk"):
            if key in value:
                sb.set("body.font_east_asia", str(value[key]),
                       "%s.%s" % (source, key), value[key], 2)
                break
    elif isinstance(value, str):
        name = value.strip()
        sb.set("body.font_latin", name, source, value, 2)
        if C.has_cjk(name) or C.has_cjk(sb.get("body.font_east_asia") or ""):
            sb.set("body.font_east_asia", name, source, value, 2)


def _apply_body_json(body, sb, source):
    for key in ("font_latin", "latin_font", "western_font", "西文字体"):
        if key in body:
            sb.set("body.font_latin", str(body[key]),
                   "%s.%s" % (source, key), body[key], 2)
    for key in ("font_east_asia", "east_asia_font", "eastAsia", "cjk_font",
                "中文字体", "中文字体名"):
        if key in body:
            sb.set("body.font_east_asia", str(body[key]),
                   "%s.%s" % (source, key), body[key], 2)
    for key in ("font", "font_family", "family", "字体"):
        if key in body:
            _apply_font_json(body[key], sb, "%s.%s" % (source, key))
            break
    for key in ("size_pt", "font_size", "字号"):
        if key in body:
            pt = size_to_pt(body[key])
            if pt:
                sb.set("body.size_pt", pt, "%s.%s" % (source, key), body[key], 2)
            break
    for key in ("line_spacing", "lineSpacing", "行距"):
        if key in body:
            ls = parse_line_spacing(body[key])
            if ls:
                sb.set("body.line_spacing", ls, "%s.%s" % (source, key), body[key], 2)
            break
    for key in ("first_line_indent_cm", "first_line_indent", "indent", "首行缩进"):
        if key in body:
            cm = _indent_to_cm(body[key], sb.get("body.size_pt") or 12)
            if cm is not None:
                sb.set("body.first_line_indent_cm", cm,
                       "%s.%s" % (source, key), body[key], 2)
            break
    for key in ("alignment", "align", "对齐"):
        if key in body:
            al = norm_align(str(body[key]))
            if al:
                sb.set("body.alignment", al, "%s.%s" % (source, key), body[key], 2)
            break
    for key in ("space_before_pt", "space_after_pt"):
        if key in body:
            num = to_number(body[key])
            if num is not None:
                sb.set("body.%s" % key, num, "%s.%s" % (source, key), body[key], 2)


def _apply_heading_json(level, item, sb, source):
    key = str(level)
    if "size_pt" in item or "font_size" in item or "字号" in item:
        raw = item.get("size_pt", item.get("font_size", item.get("字号")))
        pt = size_to_pt(raw)
        if pt:
            sb.set("headings.%s.size_pt" % key, pt, "%s.size_pt" % source, raw, 2)
    if "bold" in item:
        sb.set("headings.%s.bold" % key, bool(item["bold"]),
               "%s.bold" % source, item["bold"], 2)
    if "alignment" in item or "align" in item:
        raw = item.get("alignment", item.get("align"))
        al = norm_align(str(raw))
        if al:
            sb.set("headings.%s.alignment" % key, al, "%s.align" % source, raw, 2)
    for field in ("space_before_pt", "space_after_pt"):
        if field in item:
            num = to_number(item[field])
            if num is not None:
                sb.set("headings.%s.%s" % (key, field), num,
                       "%s.%s" % (source, field), item[field], 2)
    if "page_break_before" in item:
        sb.set("headings.%s.page_break_before" % key, bool(item["page_break_before"]),
               "%s.page_break_before" % source, None, 2)
    for fkey in ("font", "font_latin", "east_asia"):
        if fkey in item and isinstance(item[fkey], str):
            target = "font_east_asia" if fkey == "east_asia" else "font_latin"
            sb.set("headings.%s.%s" % (key, target), item[fkey],
                   "%s.%s" % (source, fkey), item[fkey], 2)


def _apply_caption_json(kind, item, sb, source):
    if "label" in item:
        sb.set("captions.%s.label" % kind, str(item["label"]),
               "%s.label" % source, item["label"], 2)
    if "separator" in item:
        sb.set("captions.%s.separator" % kind, str(item["separator"]),
               "%s.separator" % source, item["separator"], 2)
    if "position" in item:
        pos = str(item["position"]).lower()
        pos = "below" if pos in ("below", "下", "bottom", "after") else (
            "above" if pos in ("above", "上", "top", "before") else pos)
        sb.set("captions.%s.position" % kind, pos,
               "%s.position" % source, item["position"], 2)
    for key in ("size_pt", "font_size", "字号"):
        if key in item:
            pt = size_to_pt(item[key])
            if pt:
                sb.set("captions.%s.size_pt" % kind, pt,
                       "%s.%s" % (source, key), item[key], 2)
            break
    for key in ("alignment", "align"):
        if key in item:
            al = norm_align(str(item[key]))
            if al:
                sb.set("captions.%s.alignment" % kind, al,
                       "%s.%s" % (source, key), item[key], 2)
            break
    for key in ("bold", "italic"):
        if key in item:
            sb.set("captions.%s.%s" % (kind, key), bool(item[key]),
                   "%s.%s" % (source, key), item[key], 2)


def _indent_to_cm(value, body_pt):
    cm = length_to_cm(value)
    if isinstance(value, str) and re.search(r"字符|字", value):
        num = to_number(value) or 0
        return round(num * body_pt * 2.54 / 72.0, 3)
    return cm


def _norm_ref_style(value):
    low = value.lower()
    if "author" in low or "著者" in low or "出版年" in low:
        return "author_year"
    if "gb" in low or "顺序" in low or "numeric" in low or "数字" in low:
        if "period" in low or "点" in low or "句点" in low:
            return "numeric_period"
        return "numeric_bracket"
    if low in ("numeric_bracket", "numeric_period", "author_year"):
        return low
    if "none" in low or "无" in low:
        return "none"
    return None


def _norm_pn_position(pos):
    low = pos.lower()
    if "right" in low or "右" in low:
        return "footer_right"
    if "header" in low or "页眉" in low:
        return "header_center"
    return "footer_center"


def _numbering_from_pattern(text):
    text = text.strip()
    if not text:
        return None
    if text in ("none", "无", "无编号"):
        return []
    example = text.replace("1.1.1", "%1.%2.%3").replace("1.1", "%1.%2")
    example = example.replace("1", "%1")
    if "%1" not in example:
        return None
    parts = example.split(".")
    levels = []
    for idx, part in enumerate(parts[:4]):
        lvltext = ".".join(parts[:idx + 1])
        levels.append({"ilvl": idx, "numFmt": "decimal", "lvlText": lvltext})
    return levels


# ------------------------------------------------------------------ prose spec
def spec_from_text(text, sb, source, priority=2, strict=False):
    hits = []
    lines = text.splitlines()
    body_size = sb.get("body.size_pt") or 12.0
    for idx, line in enumerate(lines):
        raw = line.strip()
        if not raw or raw.startswith("<!--"):
            continue
        low = raw.lower()
        if strict:
            has_keyword = any(k in low for k in (
                "页边距", "margin", "字号", "font", "行距", "line spacing",
                "缩进", "indent", "标题", "heading", "题注", "图注", "表注",
                "caption", "表格", "table", "三线", "边框", "border",
                "参考文献", "reference", "页码", "page number", "目录", "toc",
                "双栏", "两栏", "two-column", "模板", "template",
                "页眉", "header", "公式", "equation", "脚注", "footnote",
                "水印", "watermark", "行号", "line number", "上标", "superscript",
                "封面", "cover page", "纸张", "paper", "开本", "页面尺寸"))
            has_size = bool(re.search(
                r"(?<![A-Za-z])(?:A3|A4|A5|B5|Letter|Legal)(?![A-Za-z])", raw, re.I))
            has_value = has_size or bool(re.search(r"\d", raw)) or any(
                k in low for k in ("必须", "要求", "应当", "需", "需要", "must",
                                   "should", "required", "使用"))
            if not has_keyword or not has_value:
                continue
        loc = "%s#L%d" % (source, idx + 1)

        def hit(field, value, match):
            sb.set(field, value, loc, match, priority)
            hits.append({"field": field, "value": value, "line": idx + 1,
                         "text": raw[:160]})

        # paper size
        for name in ("A3", "A4", "A5", "B5", "Letter", "Legal"):
            if re.search(r"(?<![A-Za-z])%s(?![A-Za-z])" % name, raw, re.I) and re.search(
                    r"纸张|paper|页面|page|开本|尺寸|size", raw, re.I):
                set_paper_size(sb, name, loc, raw, priority)
                hits.append({"field": "page.size_name", "value": name,
                             "line": idx + 1, "text": raw[:160]})
                break
        # margins
        if re.search(r"页边距|margin", low):
            sides = {}
            for side, aliases in (("top", ("上", "top")),
                                  ("bottom", ("下", "bottom")),
                                  ("left", ("左", "left")),
                                  ("right", ("右", "right"))):
                for alias in aliases:
                    m = re.search(r"%s\s*(?:边距|margin)?\s*[：:=为]?\s*"
                                  r"(\d+(?:\.\d+)?)\s*(cm|厘米|mm|毫米|pt|磅|in)?"
                                  % alias, raw, re.I)
                    if m:
                        sides[side] = length_to_cm("".join(m.groups()))
                        break
            if sides:
                for side, cm in sides.items():
                    hit("page.margins_cm.%s" % side, cm, raw)
            else:
                m = re.search(r"页边距\s*[：:=为]?\s*(\d+(?:\.\d+)?)\s*"
                              r"(cm|厘米|mm|毫米|pt|磅|in)", raw, re.I)
                if m:
                    cm = length_to_cm("".join(m.groups()))
                    for side in ("top", "bottom", "left", "right"):
                        hit("page.margins_cm.%s" % side, cm, raw)
            for pair, pair_sides in ((("上下"), ("top", "bottom")),
                                     (("左右"), ("left", "right"))):
                m = re.search(r"%s\s*[：:=为]?\s*(\d+(?:\.\d+)?)\s*"
                              r"(cm|厘米|mm|毫米|pt|磅|in)?" % pair, raw, re.I)
                if m:
                    cm = length_to_cm("".join(g for g in m.groups() if g))
                    if cm is not None:
                        for side in pair_sides:
                            hit("page.margins_cm.%s" % side, cm, raw)
        # columns
        if re.search(r"双栏|两栏|two[- ]column|2[- ]column", low):
            hit("page.columns", 2, raw)
        elif re.search(r"单栏|one[- ]column|single[- ]column|1[- ]column", low):
            hit("page.columns", 1, raw)
        # font family (body unless heading/caption/reference context)
        font_ctx = "body"
        if re.search(r"标题|heading|title", low):
            font_ctx = "heading"
        elif re.search(r"图注|表注|caption", low):
            font_ctx = "caption"
        elif re.search(r"参考文献|reference|bibliography", low):
            font_ctx = "reference"
        found_font = None
        for name in FONT_NAMES:
            if name.lower() in low:
                found_font = name
                break
        if not found_font:
            m = re.search(r"(?:字体|font(?: family)?)\s*[：:=]\s*"
                          r"([A-Za-z][A-Za-z0-9 ._\-]{2,30}|[\u4e00-\u9fa5]{2,8})",
                          raw, re.I)
            if m:
                found_font = m.group(1).strip()
        if found_font:
            if font_ctx == "body":
                hit("body.font_latin", found_font, raw)
                if C.has_cjk(found_font):
                    hit("body.font_east_asia", found_font, raw)
            elif font_ctx == "heading":
                m = re.search(r"([一二三四五1-5])\s*级标题|heading\s*([1-5])", low)
                lvl = None
                if m:
                    token = m.group(1) or m.group(2)
                    lvl = {"一": 1, "二": 2, "三": 3, "四": 4, "五": 5}.get(token) \
                        if token in "一二三四五" else int(token)
                if lvl:
                    hit("headings.%d.font_latin" % lvl, found_font, raw)
                    if C.has_cjk(found_font):
                        hit("headings.%d.font_east_asia" % lvl, found_font, raw)
            elif font_ctx == "caption":
                hit("captions.figure.size_pt",
                    sb.get("captions.figure.size_pt"), raw) if False else None
        # font size
        size = None
        for alias in SIZE_ALIASES:
            if alias in raw:
                size = float(SIZE_ALIASES[alias])
                break
        if size is None:
            m = re.search(r"(\d+(?:\.\d+)?)\s*(pt|磅)", raw, re.I)
            if m:
                size = float(m.group(1))
        if size:
            if font_ctx == "body" and re.search(
                    r"正文|body|字号|font size|小四|五号|小五", low):
                hit("body.size_pt", size, raw)
            elif font_ctx == "heading":
                m = re.search(r"([一二三四五1-5])\s*级标题|heading\s*([1-5])", low)
                lvl = None
                if m:
                    token = m.group(1) or m.group(2)
                    lvl = {"一": 1, "二": 2, "三": 3, "四": 4, "五": 5}[token] \
                        if token in "一二三四五" else int(token)
                if lvl:
                    hit("headings.%d.size_pt" % lvl, size, raw)
            elif font_ctx == "caption":
                kind = "table" if re.search(r"表注|table", low) else "figure"
                hit("captions.%s.size_pt" % kind, size, raw)
            elif font_ctx == "reference":
                hit("references.size_pt", size, raw)
        # heading alignment
        if font_ctx == "heading":
            m = re.search(r"([一二三四五1-5])\s*级标题|heading\s*([1-5])", low)
            lvl = None
            if m:
                token = m.group(1) or m.group(2)
                lvl = {"一": 1, "二": 2, "三": 3, "四": 4, "五": 5}[token] \
                    if token in "一二三四五" else int(token)
            if lvl and re.search(r"居中|center", low):
                hit("headings.%d.alignment" % lvl, "center", raw)
            if lvl and re.search(r"加粗|bold", low):
                hit("headings.%d.bold" % lvl, True, raw)
        # line spacing
        if re.search(r"行距|line spacing|line-spacing", low):
            ls = None
            m = re.search(r"(?:固定值|固定行距|exact)\s*[:：]?\s*(\d+(?:\.\d+)?)\s*(pt|磅)",
                          low)
            if m:
                ls = {"type": "exact", "value_pt": float(m.group(1))}
            else:
                m = re.search(r"(?:行距|line spacing)\s*[:：=为]?\s*"
                              r"(\d+(?:\.\d+)?)\s*(倍|lines?|line)?", low)
                if m:
                    ls = {"type": "multiple", "value": float(m.group(1))}
                elif "single" in low or "单倍" in low:
                    ls = {"type": "multiple", "value": 1.0}
                elif "double" in low or "双倍" in low:
                    ls = {"type": "multiple", "value": 2.0}
            if ls:
                hit("body.line_spacing", ls, raw)
        # first line indent
        if re.search(r"首行缩进|first[- ]line indent", low):
            m = re.search(r"(?:首行缩进|first[- ]line indent)\s*[：:=为]?\s*"
                          r"(\d+(?:\.\d+)?)\s*(字符|字|cm|厘米|pt|磅)?", low)
            if m:
                cm = _indent_to_cm("".join(m.groups()), body_size)
                if cm is not None:
                    hit("body.first_line_indent_cm", cm, raw)
        # caption position
        if re.search(r"图注|表注|caption", low):
            if re.search(r"图注[^。\n]{0,10}在?下|below", low) and re.search(
                    r"图|figure", low):
                hit("captions.figure.position", "below", raw)
            if re.search(r"表注[^。\n]{0,10}在?上|above", low) and re.search(
                    r"表|table", low):
                hit("captions.table.position", "above", raw)
            if re.search(r"图\s*\d|figure\s*\d|fig\.\s*\d", low):
                hit("captions.figure.label", "Figure", raw)
        # tables
        if re.search(r"三线表|three[- ]line", low):
            hit("tables.style", "three_line", raw)
        elif re.search(r"无边框|borderless|无框线", low):
            hit("tables.style", "none", raw)
        elif re.search(r"网格线|all borders|全框线", low):
            hit("tables.style", "grid", raw)
        # reference style
        if re.search(r"参考文献|reference|bibliography|gb/?t", low):
            if re.search(r"gb/?t\s*7714|顺序编码|numeric", low):
                hit("references.style", "numeric_bracket", raw)
            if re.search(r"作者[-－]?出版年|author[- ]year", low):
                hit("references.style", "author_year", raw)
            if re.search(r"悬挂缩进|hanging", low):
                m = re.search(r"(\d+(?:\.\d+)?)\s*(字符|cm|厘米|pt|磅)", low)
                if m:
                    cm = _indent_to_cm("".join(m.groups()), body_size)
                    if cm is not None:
                        hit("references.hanging_indent_cm", cm, raw)
        # page numbers
        if re.search(r"页码|page number", low):
            if re.search(r"无页码|不加页码|no page number|without page", low):
                hit("page_numbers.enabled", False, raw)
            else:
                hit("page_numbers.enabled", True, raw)
                if re.search(r"页脚|footer", low):
                    pos = "footer_right" if re.search(r"右|right", low) else "footer_center"
                    hit("page_numbers.position", pos, raw)
        # toc
        if re.search(r"目录|table of contents|\btoc\b", low) and re.search(
                r"需要|要求|包含|含|must|should|required", low):
            hit("toc.enabled", True, raw)
        # export formats
        if re.search(r"导出|交付|export|output format", low):
            if re.search(r"pdf", low):
                hit("export.formats", ["docx", "pdf"], raw)
            elif re.search(r"docx|word", low):
                hit("export.formats", ["docx"], raw)
        # requirements the writer cannot apply are surfaced instead of dropped
        if strict and UNSUPPORTED_CUES.search(raw):
            meta = sb.spec["meta"]
            bucket = meta.setdefault("unmatched_requirements", [])
            entry = {"text": raw[:200], "source": loc}
            if entry not in bucket and len(bucket) < 20:
                bucket.append(entry)
    return hits


# ------------------------------------------------------------------ manuscript
def _strip_markdown_emphasis(text):
    text = re.sub(r"^[\s>*_]+", "", text)
    text = re.sub(r"[*_]{1,3}(?=[^\s])", "", text)
    text = re.sub(r"[*_]{1,3}$", "", text)
    return text.strip()


def _caption_parts(text):
    clean = _strip_markdown_emphasis(text)
    m = CAPTION_RE.match(clean)
    if not m:
        return None
    label = m.group("label")
    kind = "figure" if re.match(r"^(图|figure|fig)", label, re.I) else "table"
    return {"kind": kind, "label": label, "number": m.group("num"),
            "separator": m.group("sep") or "", "text": m.group("text").strip(),
            "clean": clean}


def _heading_level_from_text(text):
    m = HEADING_TEXT_RE.match(text.strip())
    if m and len(text.strip()) <= 140:
        depth = m.group("num").count(".")
        if depth <= 3 and re.match(r"^\d+(?:\.\d+){0,3}[\.、\s]+\S", text.strip()):
            return depth + 1
    if CN_CHAPTER_RE.match(text.strip()) and len(text.strip()) <= 100:
        return 1
    return None


class ManuscriptParser(object):
    def __init__(self):
        self.blocks = []
        self.counters = {"H": 0, "P": 0, "C": 0, "T": 0, "R": 0, "F": 0}
        self.stats = {"headings": 0, "paragraphs": 0, "captions": 0,
                      "tables": 0, "figures": 0, "references": 0, "titles": 0,
                      "lists": 0}
        self.warnings = []

    def add(self, block_type, **kw):
        prefix = {"heading": "H", "paragraph": "P", "title": "P", "caption": "C",
                  "table": "T", "reference": "R", "figure": "F",
                  "list_item": "P", "code": "P"}.get(block_type, "P")
        self.counters[prefix] += 1
        anchor = "%s%04d" % (prefix, self.counters[prefix])
        block = {"id": "B%04d" % (len(self.blocks) + 1), "anchor": anchor,
                 "type": block_type, "text": kw.pop("text", "")}
        block.update(kw)
        self.blocks.append(block)
        if block_type == "heading":
            self.stats["headings"] += 1
        elif block_type == "paragraph":
            self.stats["paragraphs"] += 1
        elif block_type == "title":
            self.stats["titles"] += 1
        elif block_type == "caption":
            self.stats["captions"] += 1
        elif block_type == "table":
            self.stats["tables"] += 1
        elif block_type == "figure":
            self.stats["figures"] += 1
        elif block_type == "reference":
            self.stats["references"] += 1
        elif block_type == "list_item":
            self.stats["lists"] += 1
        return block


def parse_docx_manuscript(path):
    parser = ManuscriptParser()
    docx = C.Docx(path)
    try:
        styles = docx.xml("word/styles.xml")
        smap, _ = C.style_map(styles)
        doc = docx.xml("word/document.xml")
        raw_xml = docx.text_xml("word/document.xml")
        rels = _rels_map(docx, "word/_rels/document.xml.rels")
        raw_paragraphs = _extract_raw(raw_xml, "w:p")
        raw_tables = _extract_raw(raw_xml, "w:tbl")
        body = C.body_children(doc)
        p_idx = -1
        t_idx = 0
        refs_mode = False
        first_content_seen = False
        for child in body:
            name = C.local(child.tag)
            if name == "sectPr":
                continue
            if name == "p":
                p_idx += 1
                text = C.paragraph_text(child).strip()
                ppr = child.find(C.qn("w", "pPr"))
                pstyle = None
                if ppr is not None:
                    ps = ppr.find(C.qn("w", "pStyle"))
                    if ps is not None:
                        pstyle = ps.get(C.qn("w", "val"))
                info = smap.get(pstyle or "", {})
                specials = sorted({C.local(el.tag) for el in child.iter()
                                   if C.local(el.tag) in (
                                       "drawing", "pict", "object", "oMath",
                                       "oMathPara", "footnoteReference",
                                       "commentReference", "txbxContent",
                                       "hyperlink")})
                image_rels = []
                for el in child.iter():
                    if C.local(el.tag) == "blip":
                        rid = el.get(C.qn("r", "embed"))
                        if rid:
                            image_rels.append(rid)
                    elif C.local(el.tag) == "imagedata":
                        rid = el.get(C.qn("r", "id"))
                        if rid and rid not in image_rels:
                            image_rels.append(rid)
                if not text and not specials:
                    continue
                level = C.heading_level_from_style(pstyle, info.get("name"))
                if level is None and info.get("outline_level") is not None:
                    level = info["outline_level"] + 1
                if level is None and pstyle is None:
                    level = _heading_level_from_text(text)
                is_caption = bool(text) and _caption_parts(text) is not None
                ref_heading = text.strip().lower().rstrip(":：") in REF_HEADINGS
                is_title_style = (info.get("name") or "").strip().lower() in (
                    "title", "标题", "subtitle") or (pstyle or "").lower() in (
                    "title", "doctitle")
                base = {"source": "%s!word/document.xml#p[%d]" % (
                    os.path.basename(path), p_idx + 1),
                    "source_style": pstyle,
                    "special": specials,
                    "body_index": p_idx}
                if specials:
                    base["raw_kind"] = "special"
                if ref_heading:
                    parser.add("heading", text=text, level=level or 1,
                               heading_role="references", **base)
                    parser.blocks[-1]["level"] = level or 1
                    refs_mode = True
                    first_content_seen = True
                    continue
                if level:
                    parser.add("heading", text=text, level=level, **base)
                    refs_mode = False
                elif is_caption:
                    cap = _caption_parts(text)
                    parser.add("caption", text=text, kind=cap["kind"],
                               label=cap["label"], number=cap["number"],
                               caption_text=cap["text"], **base)
                elif refs_mode:
                    label_index = None
                    m = re.match(r"^\s*\[(\d+)\]|^\s*(\d+)[\.\、]\s+", text)
                    if m:
                        label_index = int(m.group(1) or m.group(2))
                    parser.add("reference", text=text, label_index=label_index, **base)
                elif is_title_style and not first_content_seen:
                    parser.add("title", text=text, **base)
                    first_content_seen = True
                elif image_rels and not text:
                    parser.add("figure", text="", image_rels=image_rels,
                               image_targets=[rels.get(r, {}).get("target")
                                              for r in image_rels], **base)
                else:
                    parser.add("paragraph", text=text, **base)
                    first_content_seen = True
            elif name == "tbl":
                t_idx += 1
                rows = _table_rows(child)
                raw = raw_tables[t_idx - 1] if t_idx - 1 < len(raw_tables) else None
                parser.add("table", text="\t".join(" | ".join(c for c in row) for row in rows),
                           table_index=t_idx, rows=rows,
                           source="%s!word/document.xml#tbl[%d]" % (
                               os.path.basename(path), t_idx),
                           raw_table=raw)
    finally:
        docx.close()
    return parser


def _extract_raw(xml_text, qname):
    """Extract raw substrings of <w:tag>...</w:tag>, aligned with document order."""
    try:
        pat = re.compile(r"<(/?)%s(?=[\s/>])" % re.escape(qname))
    except re.error:
        return []
    out = []
    depth = 0
    start = None
    for match in pat.finditer(xml_text):
        closing = match.group(1) == "/"
        tag_end = xml_text.find(">", match.end())
        if tag_end < 0:
            break
        self_closing = xml_text[tag_end - 1] == "/"
        if closing:
            depth -= 1
            if depth == 0 and start is not None:
                out.append(xml_text[start:tag_end + 1])
                start = None
        elif self_closing:
            if depth == 0:
                out.append(xml_text[match.start():tag_end + 1])
        else:
            if depth == 0:
                start = match.start()
            depth += 1
    return out


def _table_rows(tbl):
    rows = []
    for tr in tbl.findall(C.qn("w", "tr")):
        cells = []
        for tc in tr.findall(C.qn("w", "tc")):
            texts = [C.paragraph_text(p).strip()
                     for p in tc.findall(C.qn("w", "p"))]
            cells.append(" ".join(t for t in texts if t))
        rows.append(cells)
    return rows


def parse_markdown_manuscript(text, ext="md"):
    parser = ManuscriptParser()
    lines = text.splitlines()
    i = 0
    in_fence = False
    fence_buf = []
    refs_mode = False
    pending_para = []
    para_start = [0]

    def flush_para():
        if not pending_para:
            return
        start_line = para_start[0] or cur_line
        joined = " ".join(pending_para).strip()
        pending_para[:] = []
        para_start[0] = 0
        if not joined:
            return
        cap = _caption_parts(joined)
        if refs_mode:
            label_index = None
            m = re.match(r"^\s*\[(\d+)\]|^\s*(\d+)[\.\、]\s+", joined)
            if m:
                label_index = int(m.group(1) or m.group(2))
            parser.add("reference", text=joined, label_index=label_index,
                       line=start_line)
        elif cap:
            parser.add("caption", text=joined, kind=cap["kind"], label=cap["label"],
                       number=cap["number"], caption_text=cap["text"], line=start_line)
        else:
            lvl = _heading_level_from_text(joined) if ext == "txt" else None
            if lvl:
                parser.add("heading", text=joined, level=lvl, line=start_line)
            else:
                parser.add("paragraph", text=joined, line=start_line)

    while i < len(lines):
        line = lines[i]
        cur_line = i + 1
        stripped = line.strip()
        if ext == "md" and stripped.startswith("```"):
            if in_fence:
                parser.add("code", text="\n".join(fence_buf), line=cur_line)
                fence_buf = []
                in_fence = False
            else:
                flush_para()
                in_fence = True
            i += 1
            continue
        if in_fence:
            fence_buf.append(line)
            i += 1
            continue
        if not stripped:
            flush_para()
            i += 1
            continue
        if ext == "md" and stripped.startswith("---") and not pending_para and not parser.blocks:
            end = i + 1
            meta = {}
            while end < len(lines) and lines[end].strip() not in ("---", "..."):
                if ":" in lines[end]:
                    key, _, val = lines[end].partition(":")
                    meta[key.strip().lower()] = val.strip()
                end += 1
            if meta:
                parser.blocks.append({
                    "id": "B%04d" % (len(parser.blocks) + 1), "anchor": "H0000",
                    "type": "frontmatter", "text": "", "meta": meta,
                    "line": 1})
            i = end + 1
            continue
        heading = re.match(r"^(#{1,6})\s+(.*)$", stripped) if ext == "md" else None
        if not heading and len(stripped) <= 50 and \
                stripped.lower().rstrip(":：") in REF_HEADINGS:
            # plain "References" line without markdown heading markers
            flush_para()
            refs_mode = True
            parser.add("heading", text=stripped.rstrip(":："), level=1,
                       heading_role="references", line=cur_line)
            i += 1
            continue
        if heading:
            flush_para()
            level = len(heading.group(1))
            htext = heading.group(2).strip()
            refs_mode = htext.lower().rstrip(":：") in REF_HEADINGS
            role = "references" if refs_mode else None
            parser.add("heading", text=htext, level=min(level, 4),
                       line=cur_line, **({"heading_role": role} if role else {}))
            i += 1
            continue
        if ext == "md" and re.match(r"^(=+|-+)\s*$", stripped) and parser.blocks and \
                pending_para:
            # setext heading
            if stripped.startswith("="):
                htext = " ".join(pending_para).strip()
                pending_para[:] = []
                parser.add("heading", text=htext, level=1, line=cur_line)
            i += 1
            continue
        img = re.match(r"^!\[([^\]]*)\]\(([^)]+)\)\s*$", stripped) if ext == "md" else None
        if img:
            flush_para()
            alt, src = img.group(1), img.group(2)
            parser.add("figure", text=alt, image_path=src, line=cur_line)
            i += 1
            continue
        if ext == "md" and stripped.startswith("|") and "|" in stripped[1:]:
            flush_para()
            table_lines = []
            j = i
            while j < len(lines) and lines[j].strip().startswith("|"):
                table_lines.append(lines[j].strip())
                j += 1
            rows = _parse_pipe_table(table_lines)
            if rows:
                parser.add("table", text="\t".join(" | ".join(r) for r in rows),
                           table_index=parser.stats["tables"] + 1, rows=rows,
                           line=cur_line)
            i = j
            continue
        if ext == "md" and re.match(r"^(```|~~~)", stripped):
            continue
        quote = re.match(r"^>\s?(.*)$", stripped) if ext == "md" else None
        if quote:
            stripped = quote.group(1).strip()
        item = re.match(r"^(?:[-*+]|\d+[\.\)])\s+(.*)$", stripped)
        if item and stripped:
            flush_para()
            marker = stripped[:1]
            kind = "list_item"
            parser.add(kind, text=stripped, marker=marker, line=cur_line)
            i += 1
            continue
        pending_para.append(_strip_markdown_emphasis(stripped) if ext == "md" else stripped)
        if len(pending_para) == 1:
            para_start[0] = cur_line
        i += 1
    flush_para()
    if not in_fence and fence_buf:
        parser.add("code", text="\n".join(fence_buf))
    return parser


def _parse_pipe_table(lines):
    rows = []
    for idx, line in enumerate(lines):
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if idx == 1 and all(re.match(r"^:?-{2,}:?$", c or "") for c in cells if c):
            continue
        if idx == 0 and all(re.match(r"^:?-{2,}:?$", c or "") for c in cells if c):
            continue
        rows.append(cells)
    return rows if len(rows) >= 1 else []


def link_captions(parser):
    """Attach neighbouring captions to figures/tables (same for DOCX and markdown)."""
    blocks = parser.blocks
    for idx, block in enumerate(blocks):
        if block["type"] not in ("table", "figure"):
            continue
        prev = blocks[idx - 1] if idx > 0 else None
        nxt = blocks[idx + 1] if idx + 1 < len(blocks) else None
        block["caption_block"] = None
        block["caption_position"] = None
        if block["type"] == "table":
            if prev and prev["type"] == "caption" and prev.get("kind") == "table":
                block["caption_block"] = prev["anchor"]
                block["caption_position"] = "above"
            elif nxt and nxt["type"] == "caption" and nxt.get("kind") == "table":
                block["caption_block"] = nxt["anchor"]
                block["caption_position"] = "below"
        else:
            if nxt and nxt["type"] == "caption" and nxt.get("kind") == "figure":
                block["caption_block"] = nxt["anchor"]
                block["caption_position"] = "below"
            elif prev and prev["type"] == "caption" and prev.get("kind") == "figure":
                block["caption_block"] = prev["anchor"]
                block["caption_position"] = "above"


def finalize_manuscript(parser, path, fmt):
    blocks = parser.blocks
    # Frontmatter applies to the first title.
    front = next((b for b in blocks if b.get("type") == "frontmatter"), None)
    if front and not any(b["type"] == "title" for b in blocks):
        meta = front.get("meta") or {}
        title = meta.get("title")
        if title:
            idx = blocks.index(front)
            blocks.insert(idx + 1, {
                "id": "B-title", "anchor": "P0000", "type": "title",
                "text": title, "frontmatter": True})
            parser.stats["titles"] += 1
    blocks[:] = [b for b in blocks if b.get("type") != "frontmatter"]
    # Title heuristic for md/txt: short first paragraph followed by a heading
    if fmt in ("md", "txt") and blocks and not any(b["type"] == "title" for b in blocks):
        first = blocks[0]
        if first["type"] == "paragraph" and len(first["text"]) <= 180 and \
                re.search(r"[A-Za-z\u4e00-\u9fa5]", first["text"]) and \
                not re.search(r"[.。!?！？]$", first["text"]):
            nxt = blocks[1] if len(blocks) > 1 else None
            if nxt and nxt["type"] == "heading":
                first["type"] = "title"
                parser.stats["titles"] += 1
                parser.stats["paragraphs"] = max(0, parser.stats["paragraphs"] - 1)
    # DOCX heuristic: first short unstyled paragraph before any heading is a title
    if fmt == "docx" and blocks and not any(b["type"] == "title" for b in blocks):
        first = blocks[0]
        if first["type"] == "paragraph" and len(first["text"]) <= 180 and \
                not re.search(r"[.。!?！？]$", first["text"]) and \
                any(b["type"] == "heading" for b in blocks[:8]):
            first["type"] = "title"
            first["title_heuristic"] = True
            parser.stats["titles"] += 1
            parser.stats["paragraphs"] = max(0, parser.stats["paragraphs"] - 1)
    link_captions(parser)
    for idx, block in enumerate(blocks):
        block["order"] = idx + 1
    return {"path": os.path.abspath(path), "format": fmt,
            "sha256": C.sha256_file(path),
            "bytes": os.path.getsize(path) if os.path.exists(path) else 0,
            "blocks": blocks, "stats": parser.stats,
            "warnings": parser.warnings}


# ------------------------------------------------------------------ discovery
def _score_name(path, keywords):
    name = os.path.basename(path).lower()
    return sum(2 for kw in keywords if kw.lower() in name)


def discover_inputs(input_dir, case):
    files = []
    for root, dirs, names in os.walk(input_dir):
        dirs[:] = [d for d in dirs if not d.startswith(".")]
        for name in sorted(names):
            if name.startswith("."):
                continue
            path = os.path.join(root, name)
            if not os.path.isfile(path) or os.path.islink(path):
                continue
            ext = os.path.splitext(name)[1].lower()
            if ext in (".docx", ".doc", ".md", ".txt", ".json", ".yaml", ".yml", ".pdf"):
                files.append(path)
    all_paths = [f for f in files if os.path.basename(f) != "case.json"]
    task_path = next((f for f in all_paths if os.path.basename(f) == "task.md"), None)
    candidates = [f for f in all_paths if os.path.basename(f) != "task.md"]
    explicit = {"template": None, "manuscript": None}
    if isinstance(case, dict):
        for key in ("template_file", "template_path", "template", "style_template"):
            val = case.get(key)
            if isinstance(val, str):
                hit = _resolve_rel(input_dir, val)
                if hit:
                    explicit["template"] = hit
        for key in ("manuscript_file", "manuscript_path", "manuscript",
                    "source_file", "draft", "input_file"):
            val = case.get(key)
            if isinstance(val, str):
                hit = _resolve_rel(input_dir, val)
                if hit:
                    explicit["manuscript"] = hit
    warnings = []
    manuscript = explicit["manuscript"]
    template = explicit["template"]

    def is_template_name(path):
        return _score_name(path, TPL_KW) > 0

    def is_spec_like(path):
        ext = os.path.splitext(path)[1].lower()
        if ext in (".json", ".yaml", ".yml"):
            return True
        if ext in (".md", ".txt"):
            return _has_format_cues(C.read_text(path))
        return False

    # manuscript first: prefer files that are neither spec-like nor named template
    if manuscript is None:
        pool = [p for p in candidates if not is_spec_like(p) and not is_template_name(p)]
        if not pool:
            pool = [p for p in candidates if not is_spec_like(p)]
        best, best_score = None, -999
        for path in pool:
            ext = os.path.splitext(path)[1].lower()
            score = 2 * _score_name(path, MANU_KW)
            if ext == ".docx":
                score += 3
            elif ext == ".pdf":
                score += 2
            elif ext in (".md", ".txt"):
                score += 1
            try:
                if ext == ".docx" and _docx_body_paragraphs(path) > 15:
                    score += 2
            except Exception:  # noqa: BLE001
                pass
            if score > best_score:
                best, best_score = path, score
        if best_score > 0:
            manuscript = best
    # template next: named template, structured spec, or a docx that looks like one
    if template is None:
        best, best_score = None, 0
        for path in candidates:
            if path == manuscript:
                continue
            ext = os.path.splitext(path)[1].lower()
            score = 2 * _score_name(path, TPL_KW)
            if ext in (".json", ".yaml", ".yml"):
                score += 3
            if ext in (".md", ".txt") and _has_format_cues(C.read_text(path)):
                score += 2
            if ext == ".docx" and _looks_like_template(path):
                score += 2
            if score > best_score:
                best, best_score = path, score
        if best_score >= 2:
            template = best
    if manuscript is None and candidates:
        warnings.append("no manuscript identified; candidates: %s"
                        % ", ".join(os.path.basename(f) for f in candidates))
    if template and manuscript and template == manuscript:
        warnings.append("template and manuscript resolved to the same file; "
                        "template ignored")
        template = None
    spec_texts = []
    for path in candidates:
        if path in (template, manuscript):
            continue
        ext = os.path.splitext(path)[1].lower()
        if ext in (".json", ".yaml", ".yml", ".md", ".txt"):
            spec_texts.append(path)
    if task_path:
        spec_texts.append(task_path)
    extra_docx = [p for p in candidates
                  if os.path.splitext(p)[1].lower() == ".docx"
                  and p not in (template, manuscript)
                  and (_looks_like_template(p) or _score_name(p, TPL_KW) > 0)]
    return {"files": files, "manuscript": manuscript, "template": template,
            "spec_texts": spec_texts, "task": task_path,
            "extra_docx": extra_docx, "warnings": warnings}


def _resolve_rel(input_dir, value):
    for base in (input_dir, os.path.dirname(input_dir)):
        candidate = value if os.path.isabs(value) else os.path.join(base, value)
        if os.path.exists(candidate) and os.path.isfile(candidate):
            return os.path.abspath(candidate)
        candidate = os.path.join(input_dir, os.path.basename(value))
        if os.path.exists(candidate):
            return os.path.abspath(candidate)
    return None


def _has_format_cues(text):
    """True only for prose that really reads like a formatting specification."""
    text = text or ""
    if re.search(r"格式要求|排版要求|格式规范|投稿要求|format(?:ting)? requirements?|"
                 r"style (?:spec|guide)|typesetting rules", text, re.I):
        return True
    matches = re.findall(r"\d+(?:\.\d+)?\s*(?:cm|mm|pt|磅|倍|字符|号|英寸|in\b)",
                         text, re.I)
    cues = sum(1 for pattern in (
        r"页边距|margin", r"字体|font", r"字号|font[- ]?size", r"行距|line[- ]?spacing",
        r"缩进|indent", r"题注|caption", r"参考文献|bibliography|GB/?T",
        r"页码|page number", r"栏|columns", r"纸张|paper size") if re.search(
            pattern, text, re.I))
    return len(matches) >= 2 and cues >= 2


def _looks_like_template(path):
    try:
        with C.Docx(path) as docx:
            count = len(docx.names)
            styles = docx.text_xml("word/styles.xml")
            body = docx.text_xml("word/document.xml")
            return count < 25 or (styles and len(body) < 8000)
    except Exception:  # noqa: BLE001
        return False


def _docx_body_paragraphs(path):
    try:
        with C.Docx(path) as docx:
            root = docx.xml("word/document.xml")
            return len(root.findall(".//" + C.qn("w", "p")))
    except Exception:  # noqa: BLE001
        return 0


def convert_legacy(path, work, warnings):
    """Convert .doc/.pdf inputs with whatever local converter exists."""
    ext = os.path.splitext(path)[1].lower()
    os.makedirs(work, exist_ok=True)
    if ext == ".doc":
        textutil = C.which("textutil")
        if textutil:
            out = os.path.join(work, "converted_manuscript.txt")
            rc, _, err = C.run([textutil, "-convert", "txt", "-output", out, path],
                               timeout=90)
            if rc == 0 and os.path.exists(out):
                return out, "textutil -convert txt"
            warnings.append("textutil failed: %s" % err.strip()[:200])
        soffice = C.which("soffice") or C.which("libreoffice")
        if soffice:
            rc, _, err = C.run([soffice, "--headless", "--convert-to", "docx",
                                "--outdir", work, path], timeout=180)
            out = os.path.join(work, os.path.splitext(os.path.basename(path))[0] + ".docx")
            if rc == 0 and os.path.exists(out):
                return out, "soffice --convert-to docx"
            warnings.append("soffice conversion failed: %s" % err.strip()[:200])
        warnings.append("legacy .doc could not be converted (no textutil/soffice)")
        return None, None
    if ext == ".pdf":
        pdftotext = C.which("pdftotext")
        if pdftotext:
            out = os.path.join(work, "converted_manuscript.txt")
            rc, _, err = C.run([pdftotext, "-layout", path, out], timeout=120)
            if rc == 0 and os.path.exists(out):
                return out, "pdftotext -layout"
            warnings.append("pdftotext failed: %s" % err.strip()[:200])
        warnings.append("PDF manuscript needs a text layer and pdftotext; "
                        "not extracted in this environment")
        return None, None
    return None, None


# ------------------------------------------------------------------ main
def main(argv=None):
    ap = argparse.ArgumentParser(description="Parse manuscript + target template/spec")
    ap.add_argument("--input", default="/input", help="case directory or case.json")
    ap.add_argument("--work", default="/app/work", help="work directory")
    ap.add_argument("--manuscript", help="explicit manuscript path")
    ap.add_argument("--template", help="explicit template/spec path")
    args = ap.parse_args(argv)

    input_path = os.path.abspath(args.input)
    if os.path.isdir(input_path):
        input_dir = input_path
        case_path = os.path.join(input_dir, "case.json")
    else:
        input_dir = os.path.dirname(input_path)
        case_path = input_path
    os.makedirs(args.work, exist_ok=True)
    case = C.read_json(case_path, {}) or {}
    warnings = []
    if not case:
        warnings.append("case.json missing or unreadable: %s" % case_path)

    discovery = discover_inputs(input_dir, case)
    warnings.extend(discovery["warnings"])
    manuscript_path = os.path.abspath(args.manuscript) if args.manuscript \
        else discovery["manuscript"]
    template_path = os.path.abspath(args.template) if args.template \
        else discovery["template"]

    # ---- spec -------------------------------------------------------
    sb = SpecBuilder()
    spec_report = {"template": None, "text_sources": [], "json_sources": []}
    # a template DOCX may coexist with a JSON/YAML spec; parse the DOCX first so
    # the structured spec can override it
    for path in discovery.get("extra_docx") or []:
        try:
            extra = spec_from_docx(path, sb)
            spec_report.setdefault("extra_templates", []).append(
                {"path": path, "parse": extra})
            sb.spec["meta"]["template_used"] = True
            if not sb.spec["meta"].get("template_path"):
                sb.spec["meta"]["template_path"] = path
            sb.spec["meta"]["template_missing"] = False
            for warn in extra.get("warnings", []):
                warnings.append("template: " + warn)
        except Exception as exc:  # noqa: BLE001
            warnings.append("extra template parse failed (%s): %s: %s"
                            % (os.path.basename(path), type(exc).__name__, exc))
    if template_path:
        ext = os.path.splitext(template_path)[1].lower()
        spec_report["template"] = {"path": template_path, "format": ext.lstrip(".")}
        sb.spec["meta"]["template_used"] = True
        sb.spec["meta"]["template_path"] = template_path
        sb.spec["meta"]["template_missing"] = False
        try:
            if ext == ".docx":
                result = spec_from_docx(template_path, sb)
                spec_report["template_parse"] = result
                for warn in result.get("warnings", []):
                    warnings.append("template: " + warn)
            elif ext in (".json", ".yaml", ".yml"):
                data = C.read_json(template_path) if ext == ".json" else None
                if data is None:
                    parsed = parse_simple_yaml(C.read_text(template_path))
                    data = parsed
                if isinstance(data, dict):
                    spec_from_json(data, sb, os.path.basename(template_path))
                    spec_report["json_sources"].append(template_path)
                else:
                    warnings.append("template %s is not parseable JSON/YAML; "
                                    "treated as prose requirements"
                                    % os.path.basename(template_path))
                    spec_from_text(C.read_text(template_path), sb,
                                   os.path.basename(template_path), 2, strict=False)
                    spec_report["text_sources"].append(template_path)
            else:
                spec_from_text(C.read_text(template_path), sb,
                               os.path.basename(template_path), 2, strict=False)
                spec_report["text_sources"].append(template_path)
        except Exception as exc:  # noqa: BLE001
            warnings.append("template parse failed (%s): %s"
                            % (type(exc).__name__, exc))
            spec_report["template"]["error"] = "%s: %s" % (type(exc).__name__, exc)

    # spec_texts: other md/txt/json files + task.md (task.md lowest precedence)
    for path in discovery["spec_texts"]:
        ext = os.path.splitext(path)[1].lower()
        is_task = os.path.basename(path) == "task.md"
        try:
            if ext == ".json":
                data = C.read_json(path)
                if isinstance(data, dict):
                    spec_from_json(data, sb, os.path.basename(path))
                    spec_report["json_sources"].append(path)
                else:
                    warnings.append("spec json ignored (not an object): %s"
                                    % os.path.basename(path))
            elif ext in (".yaml", ".yml"):
                data = parse_simple_yaml(C.read_text(path))
                if isinstance(data, dict):
                    spec_from_json(data, sb, os.path.basename(path))
                    spec_report["json_sources"].append(path)
                else:
                    spec_from_text(C.read_text(path), sb, os.path.basename(path),
                                   2, strict=False)
                    spec_report["text_sources"].append(path)
            else:
                hits = spec_from_text(C.read_text(path), sb, os.path.basename(path),
                                      3 if is_task else 2, strict=is_task)
                spec_report["text_sources"].append(path)
                if hits:
                    spec_report.setdefault("text_hits", []).extend(hits)
        except Exception as exc:  # noqa: BLE001
            warnings.append("spec source %s failed: %s: %s"
                            % (os.path.basename(path), type(exc).__name__, exc))

    # default page dimensions follow the size name when only the name was given
    name = (sb.get("page.size_name") or "").upper()
    dims = {"A3": (29.7, 42.0), "A4": (21.0, 29.7), "A5": (14.8, 21.0),
            "B5": (17.6, 25.0), "LETTER": (21.59, 27.94),
            "LEGAL": (21.59, 35.56)}
    if name in dims:
        width, height = dims[name]
        if sb.get("page.width_cm") in (21.0, None) and name != "A4":
            sb.set("page.width_cm", width, "derived from page.size_name", name, 0)
            sb.set("page.height_cm", height, "derived from page.size_name", name, 0)

    # ---- manuscript --------------------------------------------------
    man = None
    man_warnings = []
    if not manuscript_path:
        man_warnings.append("no manuscript file detected under /input")
    else:
        ext = os.path.splitext(manuscript_path)[1].lower()
        fmt = ext.lstrip(".")
        if ext == ".docx":
            try:
                parser = parse_docx_manuscript(manuscript_path)
                man = finalize_manuscript(parser, manuscript_path, "docx")
            except Exception as exc:  # noqa: BLE001
                man_warnings.append("DOCX parse failed (%s): %s"
                                    % (type(exc).__name__, exc))
                man = None
        elif ext == ".md":
            text = C.read_text(manuscript_path)
            if not text.strip():
                man_warnings.append("manuscript Markdown is empty")
            parser = parse_markdown_manuscript(text, "md")
            man = finalize_manuscript(parser, manuscript_path, "md")
        elif ext == ".txt":
            text = C.read_text(manuscript_path)
            if not text.strip():
                man_warnings.append("manuscript text is empty")
            parser = parse_markdown_manuscript(text, "txt")
            man = finalize_manuscript(parser, manuscript_path, "txt")
        elif ext in (".doc", ".pdf"):
            converted, how = convert_legacy(manuscript_path, args.work, man_warnings)
            if converted:
                cext = os.path.splitext(converted)[1].lower()
                if cext == ".docx":
                    parser = parse_docx_manuscript(converted)
                    man = finalize_manuscript(parser, converted, "docx")
                    man["original_path"] = manuscript_path
                    man["converted_by"] = how
                    man_warnings.append(
                        "legacy input converted with %s; layout fidelity not "
                        "fully preserved" % how)
                else:
                    parser = parse_markdown_manuscript(C.read_text(converted), "txt")
                    man = finalize_manuscript(parser, converted, "txt")
                    man["original_path"] = manuscript_path
                    man["converted_by"] = how
                    man_warnings.append(
                        "legacy input converted with %s; rich objects may be lost" % how)
            else:
                man_warnings.append("unsupported manuscript format %s; no converter "
                                    "available" % ext)
        else:
            man_warnings.append("unsupported manuscript format %s" % ext)
    if man:
        warnings.extend(man_warnings)
        if not man["blocks"]:
            warnings.append("manuscript parsed but produced zero content blocks")
    else:
        warnings.extend(man_warnings)

    inputs = {
        "schema": "inputs/v1",
        "input_dir": input_dir,
        "case": {
            "path": case_path,
            "sha256": C.sha256_file(case_path) if os.path.exists(case_path) else None,
            "case_id": C.detect_case_id(case, case_path)[0],
            "case_id_source": C.detect_case_id(case, case_path)[1],
            "contract_fields": C.contract_fields(case)[0],
            "contract_raw_type": C.contract_fields(case)[1],
            "output_contract": case.get("output_contract") if isinstance(case, dict)
            else None,
        },
        "task": {"path": discovery["task"],
                 "sha256": C.sha256_file(discovery["task"])
                 if discovery["task"] else None},
        "manuscript": man,
        "template": {"path": template_path,
                     "format": os.path.splitext(template_path)[1].lstrip(".")
                     if template_path else None,
                     "sha256": C.sha256_file(template_path)
                     if template_path else None},
        "file_manifest": [{"path": path, "bytes": os.path.getsize(path),
                           "sha256": C.sha256_file(path)}
                          for path in discovery["files"]],
        "warnings": warnings,
    }
    spec = sb.spec
    spec["meta"]["spec_sources"] = spec_report
    text_hits = spec_report.get("text_hits") or []
    has_spec = bool(template_path) or bool(spec_report.get("json_sources")) or \
        bool(spec_report.get("extra_templates")) or \
        bool(spec_report.get("text_sources") and text_hits)
    if not has_spec:
        warnings.append("no template or parseable format requirements were detected; "
                        "builtin default spec is used")
    spec["meta"]["template_missing"] = not has_spec
    C.write_json(os.path.join(args.work, "inputs.json"), inputs)
    C.write_json(os.path.join(args.work, "spec.json"), spec)

    summary = {
        "work": os.path.abspath(args.work),
        "manuscript": man["path"] if man else None,
        "manuscript_format": man["format"] if man else None,
        "blocks": len(man["blocks"]) if man else 0,
        "template": template_path,
        "template_missing": bool(spec["meta"].get("template_missing")),
        "spec_conflicts": len(spec["conflicts"]),
        "warnings": warnings,
    }
    print(json.dumps(summary, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
