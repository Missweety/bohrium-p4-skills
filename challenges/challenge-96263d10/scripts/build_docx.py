#!/usr/bin/env python3
"""build_docx.py - build a real, editable OOXML .docx from spec.json + inputs.json.

The generated package contains:
  [Content_Types].xml, _rels/.rels, docProps/{core,app}.xml
  word/document.xml, word/styles.xml, word/numbering.xml, word/settings.xml,
  word/fontTable.xml, word/footer1.xml (PAGE field), optional header1.xml,
  copied media parts + relationships.

After writing it reopens its own output (zip + XML parse) and compares the
emitted text with the manuscript blocks. If LibreOffice (soffice) exists, it
renders a real PDF and records the page count read from that PDF; otherwise the
PDF is marked as not produced (never faked).

Outputs (under --output): manuscript_formatted.docx, build_meta.json,
manuscript_formatted.pdf (only when a renderer exists).
"""
import argparse
import datetime
import json
import os
import re
import struct
import sys
import xml.etree.ElementTree as ET
import zipfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common as C  # noqa: E402

W_NS = C.NS["w"]
R_NS = C.NS["r"]
CONTENT_TYPES = "application/vnd.openxmlformats-officedocument.wordprocessingml"
IMAGE_TYPES = {"png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg",
               "gif": "image/gif", "bmp": "image/bmp", "tif": "image/tiff",
               "tiff": "image/tiff", "emf": "image/x-emf", "wmf": "image/x-wmf",
               "svg": "image/svg+xml"}
XML_DECL = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'


def esc(text, attr=False):
    return C.xml_escape(text, attr=attr)


def emu_from_cm(cm):
    return int(round(float(cm) * 360000))


def register_source_namespaces(xml_text):
    for prefix, uri in re.findall(r'xmlns:([A-Za-z0-9_]+)="([^"]+)"', xml_text or ""):
        if prefix == "xml":
            continue
        try:
            ET.register_namespace(prefix, uri)
        except Exception:  # noqa: BLE001
            pass


def image_size(data):
    try:
        if data[:8] == b"\x89PNG\r\n\x1a\n":
            width, height = struct.unpack(">II", data[16:24])
            return int(width), int(height)
        if data[:6] in (b"GIF87a", b"GIF89a"):
            width, height = struct.unpack("<HH", data[6:10])
            return int(width), int(height)
        if data[:2] == b"\xff\xd8":
            idx = 2
            while idx + 9 < len(data):
                if data[idx] != 0xFF:
                    idx += 1
                    continue
                marker = data[idx + 1]
                if marker in (0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7,
                              0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF):
                    height, width = struct.unpack(">HH", data[idx + 5:idx + 9])
                    return int(width), int(height)
                if marker in (0xD8, 0xD9) or 0xD0 <= marker <= 0xD7:
                    idx += 2
                    continue
                seg = struct.unpack(">H", data[idx + 2:idx + 4])[0]
                idx += 2 + seg
    except Exception:  # noqa: BLE001
        pass
    return None


class Builder(object):
    def __init__(self, inputs, spec, output_dir, work_dir):
        self.inputs = inputs
        self.spec = spec
        self.output_dir = output_dir
        self.work_dir = work_dir
        self.manuscript = inputs.get("manuscript") or {}
        self.blocks = list(self.manuscript.get("blocks") or [])
        self.page = spec.get("page") or {}
        self.body = spec.get("body") or {}
        self.headings_spec = spec.get("headings") or {}
        self.captions_spec = spec.get("captions") or {}
        self.refs_spec = spec.get("references") or {}
        self.pn_spec = spec.get("page_numbers") or {}
        self.header_spec = spec.get("header") or {}
        self.num_spec = spec.get("heading_numbering") or {}
        self.tables_spec = spec.get("tables") or {}
        self.export_spec = spec.get("export") or {}
        self.prov = spec.get("provenance") or {}
        self.media = {}
        self.media_seq = 0
        self.rel_media = {}
        self.media_rel = {}
        self.issues = []
        self.warnings = []
        self.changes = []
        self.caption_counters = {"figure": 0, "table": 0}
        self.caption_map = {"figure": {}, "table": {}}
        levels = [dict(x) for x in (self.num_spec.get("levels") or [])]
        if levels:
            for ilvl in range(len(levels), 4):
                levels.append({"ilvl": ilvl, "numFmt": "decimal",
                               "lvlText": ".".join("%%%d" % (i + 1)
                                                   for i in range(ilvl + 1))})
        self.numbering_levels = levels
        self.heading_counters = []
        self.heading_numbers = {}
        self.consumed_captions = set()
        self.source = None
        self.source_children = {"p": [], "tbl": []}
        self.source_rels = {}
        self.table_seq = 0
        self.max_heading_level = max(
            [int(k) for k in self.headings_spec if str(k).isdigit()] + [3])
        self.max_heading_level = max(
            self.max_heading_level,
            max([b.get("level", 1) for b in self.blocks if b["type"] == "heading"] + [1]))
        self.max_heading_level = min(self.max_heading_level, 4)
        self.used_styles = set()

    # ------------------------------------------------------------ helpers
    def prov_source(self, path):
        return (self.prov.get(path) or {}).get("source") or ""

    def spec_is_default(self, path):
        return self.prov_source(path).startswith("builtin-default")

    def ppr(self, style=None, num=None, jc=None, keep_next=False, indent=None,
            page_break_before=False):
        parts = []
        if style:
            parts.append('<w:pStyle w:val="%s"/>' % esc(style, True))
            self.used_styles.add(style)
        if keep_next:
            parts.append("<w:keepNext/>")
        if page_break_before:
            parts.append("<w:pageBreakBefore/>")
        if num:
            num_id, ilvl = num
            parts.append('<w:numPr><w:ilvl w:val="%d"/><w:numId w:val="%s"/></w:numPr>'
                         % (ilvl, num_id))
        if indent:
            left, hanging = indent
            parts.append('<w:ind w:left="%d" w:hanging="%d"/>' % (left, hanging))
        if jc:
            parts.append('<w:jc w:val="%s"/>' % esc(jc, True))
        return "".join(parts)

    def para(self, text="", style=None, num=None, jc=None, keep_next=False,
             runs_xml=None, indent=None, page_break_before=False, preserve=True):
        ppr = self.ppr(style, num, jc, keep_next, indent, page_break_before)
        inner = runs_xml or ""
        if text:
            inner += ('<w:r><w:t xml:space="%s">%s</w:t></w:r>'
                      % ("preserve" if preserve else "default", esc(text)))
        return "<w:p>%s%s</w:p>" % ("<w:pPr>%s</w:pPr>" % ppr if ppr else "", inner)

    # ------------------------------------------------------------ source docx
    def load_source(self):
        path = self.manuscript.get("path")
        if not path or not os.path.exists(path) or self.manuscript.get("format") != "docx":
            return
        try:
            docx = C.Docx(path)
            xml_text = docx.text_xml("word/document.xml")
            register_source_namespaces(xml_text)
            root = ET.fromstring(xml_text.encode("utf-8"))
            body = root.find(C.qn("w", "body"))
            if body is not None:
                for child in body:
                    name = C.local(child.tag)
                    if name in ("p", "tbl"):
                        self.source_children[name].append(child)
            self.source_rels = self._rels(docx)
            self.source = docx
        except Exception as exc:  # noqa: BLE001
            self.warnings.append("source docx re-open failed: %s: %s"
                                 % (type(exc).__name__, exc))
            self.source = None

    @staticmethod
    def _rels(docx):
        root = docx.xml("word/_rels/document.xml.rels")
        out = {}
        if root is None:
            return out
        for rel in root:
            rid = rel.get("Id")
            if rid:
                out[rid] = {"type": rel.get("Type", ""), "target": rel.get("Target", "")}
        return out

    def copy_media(self, rid, add_rel=True):
        """Copy a source image rel into the new package, return new rId."""
        if rid in self.rel_media:
            return self.rel_media[rid]
        rel = self.source_rels.get(rid)
        if not rel:
            return None
        target = (rel.get("target") or "").lstrip("/")
        if not target.startswith("word/"):
            target = "word/" + target
        data = self.source.read(target) if self.source else None
        if not data:
            return None
        ext = os.path.splitext(target)[1].lower().lstrip(".") or "png"
        self.media_seq += 1
        name = "media/image%d.%s" % (self.media_seq, ext)
        self.media[name] = data
        new_rid = "rIdImg%d" % self.media_seq
        self.rel_media[rid] = new_rid
        self.media_rel[new_rid] = name
        return new_rid

    def copy_media_file(self, path):
        try:
            with open(path, "rb") as fh:
                data = fh.read()
        except OSError:
            return None, None
        ext = os.path.splitext(path)[1].lower().lstrip(".") or "png"
        self.media_seq += 1
        name = "media/image%d.%s" % (self.media_seq, ext)
        self.media[name] = data
        rid = "rIdImg%d" % self.media_seq
        self.media_rel[rid] = name
        return rid, (name, data)

    def raw_runs(self, block):
        """Serialise the runs of a source paragraph, remapping image rel ids."""
        idx = block.get("body_index")
        if idx is None or idx >= len(self.source_children["p"]):
            return None
        el = self.source_children["p"][idx]
        pieces = []
        for child in el:
            if C.local(child.tag) in ("pPr", "sectPr"):
                continue
            try:
                pieces.append(ET.tostring(child, encoding="unicode"))
            except Exception:  # noqa: BLE001
                continue
        xml = "".join(pieces)
        for old_rid in list(re.findall(r'r:(?:embed|id|link)="([^"]+)"', xml)):
            new_rid = self.copy_media(old_rid)
            if new_rid:
                xml = re.sub(r'r:(embed|id|link)="%s"' % re.escape(old_rid),
                             lambda m: 'r:%s="%s"' % (m.group(1), new_rid), xml)
        return xml

    # ------------------------------------------------------------ tables
    def raw_table(self, block):
        idx = (block.get("table_index") or 0) - 1
        if idx < 0 or idx >= len(self.source_children["tbl"]):
            return None
        el = self.source_children["tbl"][idx]
        try:
            xml = ET.tostring(el, encoding="unicode")
        except Exception:  # noqa: BLE001
            return None
        for old_rid in list(re.findall(r'r:(?:embed|id|link)="([^"]+)"', xml)):
            new_rid = self.copy_media(old_rid)
            if new_rid:
                xml = re.sub(r'r:(embed|id|link)="%s"' % re.escape(old_rid),
                             lambda m: 'r:%s="%s"' % (m.group(1), new_rid), xml)
        return xml

    def table_borders(self):
        style = (self.tables_spec.get("style") or "grid").lower()
        if style in ("three_line", "three-line", "三线表"):
            return ('<w:tblBorders>'
                    '<w:top w:val="single" w:sz="12" w:space="0" w:color="000000"/>'
                    '<w:left w:val="none" w:sz="0" w:space="0" w:color="auto"/>'
                    '<w:bottom w:val="single" w:sz="12" w:space="0" w:color="000000"/>'
                    '<w:right w:val="none" w:sz="0" w:space="0" w:color="auto"/>'
                    '<w:insideH w:val="none" w:sz="0" w:space="0" w:color="auto"/>'
                    '<w:insideV w:val="none" w:sz="0" w:space="0" w:color="auto"/>'
                    '</w:tblBorders>'), "three_line"
        if style in ("none", "无边框", "borderless"):
            return ('<w:tblBorders>'
                    '<w:top w:val="none" w:sz="0" w:space="0" w:color="auto"/>'
                    '<w:left w:val="none" w:sz="0" w:space="0" w:color="auto"/>'
                    '<w:bottom w:val="none" w:sz="0" w:space="0" w:color="auto"/>'
                    '<w:right w:val="none" w:sz="0" w:space="0" w:color="auto"/>'
                    '<w:insideH w:val="none" w:sz="0" w:space="0" w:color="auto"/>'
                    '<w:insideV w:val="none" w:sz="0" w:space="0" w:color="auto"/>'
                    '</w:tblBorders>'), "none"
        return ('<w:tblBorders>'
                '<w:top w:val="single" w:sz="4" w:space="0" w:color="auto"/>'
                '<w:left w:val="single" w:sz="4" w:space="0" w:color="auto"/>'
                '<w:bottom w:val="single" w:sz="4" w:space="0" w:color="auto"/>'
                '<w:right w:val="single" w:sz="4" w:space="0" w:color="auto"/>'
                '<w:insideH w:val="single" w:sz="4" w:space="0" w:color="auto"/>'
                '<w:insideV w:val="single" w:sz="4" w:space="0" w:color="auto"/>'
                '</w:tblBorders>'), "grid"

    def apply_table_props(self, xml):
        borders, style_name = self.table_borders()
        xml = re.sub(r"<w:tblStyle[^>]*/>", "", xml, count=1)
        xml = xml.replace("<w:tbl>", "<w:tbl>", 1)
        m = re.match(r"<w:tbl[^>]*>", xml)
        if not m:
            return xml
        head = m.group(0)
        rest = xml[m.end():]
        if "<w:tblPr>" in rest[:400]:
            rest = rest.replace(
                "<w:tblPr>",
                '<w:tblPr><w:tblStyle w:val="TableGrid"/>' + borders, 1)
        else:
            rest = ('<w:tblPr><w:tblStyle w:val="TableGrid"/>' + borders +
                    '<w:tblW w:type="auto" w:w="0"/></w:tblPr>' + rest)
        return head + rest

    def build_table(self, block):
        rows = block.get("rows") or []
        cols = max([len(r) for r in rows] + [1])
        usable = C.cm_to_twips(float(self.page.get("width_cm") or 21.0) -
                               float((self.page.get("margins_cm") or {}).get("left") or 2.54) -
                               float((self.page.get("margins_cm") or {}).get("right") or 2.54))
        colw = max(720, int(usable / cols))
        borders, style_name = self.table_borders()
        grid = "".join('<w:gridCol w:w="%d"/>' % colw for _ in range(cols))
        out = ['<w:tbl><w:tblPr><w:tblStyle w:val="TableGrid"/>' + borders +
               '<w:tblW w:type="auto" w:w="0"/></w:tblPr>'
               '<w:tblGrid>%s</w:tblGrid>' % grid]
        for ridx, row in enumerate(rows):
            cells = []
            for cidx in range(cols):
                text = row[cidx] if cidx < len(row) else ""
                tcpr = ""
                if style_name == "three_line" and ridx == 0:
                    tcpr = ('<w:tcPr><w:tcBorders><w:bottom w:val="single" '
                            'w:sz="6" w:space="0" w:color="000000"/></w:tcBorders>'
                            '</w:tcPr>')
                cells.append('<w:tc>%s<w:p>%s</w:p></w:tc>' % (
                    tcpr,
                    '<w:r><w:t xml:space="preserve">%s</w:t></w:r>' % esc(text)
                    if text else ""))
            out.append("<w:tr>%s</w:tr>" % "".join(cells))
        out.append("</w:tbl>")
        return "".join(out)

    # ------------------------------------------------------------ numbering
    def heading_numbering_used(self):
        return bool(self.num_spec.get("enabled")) and bool(self.numbering_levels)

    def heading_number(self, level):
        ilvl = max(0, level - 1)
        while len(self.heading_counters) <= ilvl:
            self.heading_counters.append(0)
        self.heading_counters[ilvl] += 1
        for deeper in range(ilvl + 1, len(self.heading_counters)):
            self.heading_counters[deeper] = 0
        return list(self.heading_counters[:ilvl + 1])

    def format_heading_number(self, counters):
        level = self.numbering_levels[min(len(counters) - 1,
                                          len(self.numbering_levels) - 1)]
        pattern = level.get("lvlText") or "%1"
        out = pattern
        for idx in range(len(counters)):
            out = out.replace("%%%d" % (idx + 1), str(counters[idx]))
        return out

    # ------------------------------------------------------------ captions
    def caption_label(self, kind, block):
        path = "captions.%s.label" % kind
        spec_label = (self.captions_spec.get(kind) or {}).get("label") or (
            "Figure" if kind == "figure" else "Table")
        if not self.spec_is_default(path):
            return spec_label
        if block.get("label"):
            return block["label"]
        return spec_label

    def caption_separator(self, kind, block):
        path = "captions.%s.separator" % kind
        if not self.spec_is_default(path):
            return (self.captions_spec.get(kind) or {}).get("separator") or ". "
        sep = (block.get("separator") or "").strip()
        if sep:
            return sep + (" " if not sep.endswith(" ") else "")
        return ". "

    def caption_align(self, kind):
        cfg = self.captions_spec.get(kind) or {}
        align = cfg.get("alignment") or ("center" if kind == "figure" else "left")
        return align

    def caption_style(self, kind):
        cfg = self.captions_spec.get(kind) or {}
        bold = cfg.get("bold")
        return "Caption"

    def emit_caption(self, block):
        kind = block.get("kind") or "figure"
        self.caption_counters[kind] += 1
        number = self.caption_counters[kind]
        old = str(block.get("number") or "").strip()
        if old and old != str(number):
            self.caption_map[kind][old] = number
        label = self.caption_label(kind, block)
        sep = self.caption_separator(kind, block)
        text = "%s %d%s%s" % (label, number, sep, block.get("caption_text") or "")
        cfg = self.captions_spec.get(kind) or {}
        bold = bool(cfg.get("bold"))
        runs = '<w:r><w:rPr>%s</w:rPr><w:t xml:space="preserve">%s</w:t></w:r>' % (
            ("<w:b/>" if bold else "") + ("<w:i/>" if cfg.get("italic") else ""),
            esc(text))
        jc = self.caption_align(kind)
        return self.para(style="Caption", jc=jc, keep_next=(kind == "table"),
                         runs_xml=runs), text

    # ------------------------------------------------------------ cross refs
    def fix_crossrefs(self, text):
        if not text:
            return text, []
        changed = []
        for kind, mapping in self.caption_map.items():
            if not mapping:
                continue
            labels = ("Figure", "Fig.", "Fig", "图") if kind == "figure" else (
                "Table", "Tab.", "Tab", "表")
            for old, new in mapping.items():
                if str(old) == str(new) or not str(old).isdigit():
                    continue
                for label in labels:
                    pattern = r"(?<![\w])%s\s*%s(?![\d])" % (
                        re.escape(label), re.escape(str(old)))
                    if re.search(pattern, text):
                        def repl(match, new=new, label=label):
                            gap = " " if label.isascii() else ""
                            return "%s%s%s" % (label, gap, new)
                        new_text = re.sub(pattern, repl, text)
                        if new_text != text:
                            changed.append({"label": label, "from": old,
                                            "to": new})
                            text = new_text
        return text, changed

    # ------------------------------------------------------------ figures
    def figure_runs(self, block):
        if block.get("special") and block.get("body_index") is not None:
            raw = self.raw_runs(block)
            if raw:
                return raw
        if block.get("image_path"):
            src = block["image_path"]
            if not os.path.isabs(src):
                base = os.path.dirname(self.manuscript.get("path") or "")
                src = os.path.normpath(os.path.join(base, src))
            if not os.path.exists(src):
                self.issues.append({
                    "id": "figure-missing-%s" % block["anchor"],
                    "issue": "image file not found: %s" % block.get("image_path"),
                    "status": "partial",
                    "anchor": block["anchor"]})
                return ('<w:r><w:t xml:space="preserve">[[missing image: %s]]</w:t></w:r>'
                        % esc(block.get("image_path") or ""))
            rid, media = self.copy_media_file(src)
            if not rid:
                return ""
            name, data = media
            dims = image_size(data)
            if dims:
                px_w, px_h = dims
                width_emu = px_w * 9525
                max_emu = emu_from_cm(float(self.page.get("width_cm") or 21.0) -
                                      float((self.page.get("margins_cm") or {})
                                            .get("left") or 2.54) -
                                      float((self.page.get("margins_cm") or {})
                                            .get("right") or 2.54))
                if width_emu > max_emu:
                    ratio = max_emu / float(width_emu)
                    width_emu = int(width_emu * ratio)
                    height_emu = int(px_h * 9525 * ratio)
                else:
                    height_emu = px_h * 9525
                doc_id = self.media_seq
            else:
                width_emu, height_emu, doc_id = emu_from_cm(12.0), emu_from_cm(8.0), 0
                self.warnings.append("image dimensions unknown for %s; "
                                     "fallback 12x8 cm" % block.get("image_path"))
            return self.drawing(rid, name, width_emu, height_emu, doc_id)
        if block.get("text"):
            return ('<w:r><w:t xml:space="preserve">%s</w:t></w:r>'
                    % esc(block["text"]))
        return ""

    def drawing(self, rid, name, width_emu, height_emu, doc_id):
        pid = "Picture %d" % (doc_id or 1)
        return (
            '<w:r><w:drawing><wp:inline distT="0" distB="0" distL="0" distR="0">'
            '<wp:extent cx="%d" cy="%d"/><wp:docPr id="%d" name="%s"/>'
            '<a:graphic><a:graphicData uri="%s/picture">'
            '<pic:pic><pic:nvPicPr><pic:cNvPr id="%d" name="%s"/><pic:cNvPicPr/>'
            '</pic:nvPicPr><pic:blipFill><a:blip r:embed="%s"/><a:stretch>'
            '<a:fillRect/></a:stretch></pic:blipFill><pic:spPr><a:xfrm>'
            '<a:off x="0" y="0"/><a:ext cx="%d" cy="%d"/></a:xfrm>'
            '<a:prstGeom prst="rect"><a:avLst/></a:prstGeom></pic:spPr></pic:pic>'
            '</a:graphicData></a:graphic></wp:inline></w:drawing></w:r>'
            % (width_emu, height_emu, doc_id or 1, esc(pid, True),
               "http://schemas.openxmlformats.org/drawingml/2006",
               doc_id or 1, esc(pid, True), rid, width_emu, height_emu))

    # ------------------------------------------------------------ styles part
    def style_run_props(self, font_latin=None, font_east=None, size_pt=None,
                        bold=None, italic=None):
        parts = []
        if font_latin or font_east:
            parts.append('<w:rFonts w:ascii="%s" w:hAnsi="%s" w:eastAsia="%s" w:cs="%s"/>'
                         % (esc(font_latin or "", True), esc(font_latin or "", True),
                            esc(font_east or font_latin or "", True),
                            esc(font_latin or "", True)))
        if bold:
            parts.append("<w:b/>")
        if italic:
            parts.append("<w:i/>")
        if size_pt:
            half = C.pt_to_half(size_pt)
            parts.append('<w:sz w:val="%d"/>' % half)
            parts.append('<w:szCs w:val="%d"/>' % half)
        return "".join(parts)

    def style_para_props(self, line_spacing=None, before=None, after=None,
                         indent_cm=None, align=None, outline=None,
                         keep_next=False, hanging_cm=None, page_break_before=False):
        parts = []
        if keep_next:
            parts.append("<w:keepNext/>")
        if page_break_before:
            parts.append("<w:pageBreakBefore/>")
        spacing = ""
        if before is not None:
            spacing += ' w:before="%d"' % int(round(float(before) * 20))
        if after is not None:
            spacing += ' w:after="%d"' % int(round(float(after) * 20))
        if line_spacing:
            if line_spacing.get("type") == "exact":
                spacing += ' w:line="%d" w:lineRule="exact"' % int(
                    round(float(line_spacing.get("value_pt") or 12) * 20))
            else:
                spacing += ' w:line="%d" w:lineRule="auto"' % int(
                    round(240 * float(line_spacing.get("value") or 1)))
        if spacing:
            parts.append("<w:spacing%s/>" % spacing)
        if indent_cm is not None:
            parts.append('<w:ind w:firstLine="%d"/>' % C.cm_to_twips(indent_cm))
        if hanging_cm is not None:
            parts.append('<w:ind w:left="%d" w:hanging="%d"/>'
                         % (C.cm_to_twips(hanging_cm), C.cm_to_twips(hanging_cm)))
        if align:
            parts.append('<w:jc w:val="%s"/>' % esc(align, True))
        if outline is not None:
            parts.append('<w:outlineLvl w:val="%d"/>' % outline)
        return "".join(parts)

    def styles_xml(self):
        body_font = self.body.get("font_latin")
        east = self.body.get("font_east_asia") or body_font
        body_size = self.body.get("size_pt")
        line = self.body.get("line_spacing")
        align = self.body.get("alignment") or "both"
        ffi = self.body.get("first_line_indent_cm")
        styles = []

        normal_rpr = self.style_run_props(body_font, east, body_size)
        normal_ppr = self.style_para_props(
            line, self.body.get("space_before_pt"),
            self.body.get("space_after_pt"), ffi, align)
        styles.append('<w:style w:type="paragraph" w:default="1" w:styleId="Normal">'
                      '<w:name w:val="Normal"/><w:qFormat/><w:pPr>%s</w:pPr>'
                      '<w:rPr>%s</w:rPr></w:style>' % (normal_ppr, normal_rpr))

        title_size = min(24, float(body_size or 12) + 6)
        styles.append('<w:style w:type="paragraph" w:styleId="Title">'
                      '<w:name w:val="Title"/><w:basedOn w:val="Normal"/>'
                      '<w:next w:val="Normal"/><w:qFormat/>'
                      '<w:pPr><w:spacing w:before="240" w:after="240"/>'
                      '<w:jc w:val="center"/></w:pPr>'
                      '<w:rPr><w:b/><w:sz w:val="%d"/><w:szCs w:val="%d"/></w:rPr>'
                      '</w:style>' % (C.pt_to_half(title_size), C.pt_to_half(title_size)))

        for lvl in range(1, self.max_heading_level + 1):
            cfg = self.headings_spec.get(str(lvl)) or {}
            size = cfg.get("size_pt") or max(11, float(body_size or 12) +
                                             (4 - lvl) * 2)
            bold = cfg.get("bold", True)
            halign = cfg.get("alignment") or "left"
            before = cfg.get("space_before_pt")
            after = cfg.get("space_after_pt")
            latin = cfg.get("font_latin") or body_font
            east_h = cfg.get("font_east_asia") or east
            pbb = bool(cfg.get("page_break_before"))
            rpr = self.style_run_props(latin, east_h, size, bold=bold)
            ppr = self.style_para_props(None, before, after, None, halign,
                                        outline=lvl - 1, keep_next=True,
                                        page_break_before=pbb)
            styles.append('<w:style w:type="paragraph" w:styleId="Heading%d">'
                          '<w:name w:val="heading %d"/><w:basedOn w:val="Normal"/>'
                          '<w:next w:val="Normal"/><w:qFormat/><w:pPr>%s</w:pPr>'
                          '<w:rPr>%s</w:rPr></w:style>' % (lvl, lvl, ppr, rpr))

        cap_cfg_fig = self.captions_spec.get("figure") or {}
        cap_cfg_tab = self.captions_spec.get("table") or {}
        cap_size = cap_cfg_fig.get("size_pt") or cap_cfg_tab.get("size_pt") or 10
        cap_bold = bool(cap_cfg_fig.get("bold") or cap_cfg_tab.get("bold"))
        cap_italic = bool(cap_cfg_fig.get("italic") or cap_cfg_tab.get("italic"))
        styles.append('<w:style w:type="paragraph" w:styleId="Caption">'
                      '<w:name w:val="caption"/><w:basedOn w:val="Normal"/>'
                      '<w:next w:val="Normal"/><w:qFormat/>'
                      '<w:pPr><w:spacing w:before="60" w:after="120"/>'
                      '<w:ind w:firstLine="0"/></w:pPr><w:rPr>%s</w:rPr></w:style>'
                      % self.style_run_props(body_font, east, cap_size,
                                             bold=cap_bold, italic=cap_italic))
        ref_size = self.refs_spec.get("size_pt") or 10
        hang = float(self.refs_spec.get("hanging_indent_cm") or 0.74)
        ref_line = self.refs_spec.get("line_spacing")
        ref_line_obj = None
        if ref_line:
            ref_line_obj = {"type": "multiple", "value": float(ref_line)}
        styles.append('<w:style w:type="paragraph" w:styleId="Bibliography">'
                      '<w:name w:val="Bibliography"/><w:basedOn w:val="Normal"/>'
                      '<w:next w:val="Bibliography"/><w:qFormat/><w:pPr>%s</w:pPr>'
                      '<w:rPr>%s</w:rPr></w:style>'
                      % (self.style_para_props(ref_line_obj, 0, 0, align="left",
                                               hanging_cm=hang),
                         self.style_run_props(body_font, east, ref_size)))
        styles.append('<w:style w:type="paragraph" w:styleId="Header">'
                      '<w:name w:val="header"/><w:basedOn w:val="Normal"/>'
                      '<w:pPr><w:pStyle w:val="Header"/><w:jc w:val="center"/></w:pPr>'
                      '<w:rPr><w:sz w:val="20"/><w:szCs w:val="20"/></w:rPr>'
                      '</w:style>'
                      .replace('<w:pPr><w:pStyle w:val="Header"/><w:jc w:val="center"/></w:pPr>',
                               '<w:pPr><w:jc w:val="center"/></w:pPr>'))
        styles.append('<w:style w:type="paragraph" w:styleId="Footer">'
                      '<w:name w:val="footer"/><w:basedOn w:val="Normal"/>'
                      '<w:pPr><w:jc w:val="center"/></w:pPr>'
                      '<w:rPr><w:sz w:val="20"/><w:szCs w:val="20"/></w:rPr>'
                      '</w:style>')
        styles.append('<w:style w:type="table" w:styleId="TableGrid">'
                      '<w:name w:val="Table Grid"/><w:basedOn w:val="TableNormal"/>'
                      '<w:uiPriority w:val="59"/><w:tblPr><w:tblBorders>'
                      '<w:top w:val="single" w:sz="4" w:space="0" w:color="auto"/>'
                      '<w:left w:val="single" w:sz="4" w:space="0" w:color="auto"/>'
                      '<w:bottom w:val="single" w:sz="4" w:space="0" w:color="auto"/>'
                      '<w:right w:val="single" w:sz="4" w:space="0" w:color="auto"/>'
                      '<w:insideH w:val="single" w:sz="4" w:space="0" w:color="auto"/>'
                      '<w:insideV w:val="single" w:sz="4" w:space="0" w:color="auto"/>'
                      '</w:tblBorders><w:tblCellMar><w:left w:w="108" w:type="dxa"/>'
                      '<w:right w:w="108" w:type="dxa"/></w:tblCellMar></w:tblPr>'
                      '</w:style>')
        styles.append('<w:style w:type="table" w:default="1" w:styleId="TableNormal">'
                      '<w:name w:val="Normal Table"/><w:uiPriority w:val="99"/>'
                      '<w:tblPr><w:tblInd w:w="0" w:type="dxa"/><w:tblCellMar>'
                      '<w:top w:w="0" w:type="dxa"/><w:left w:w="108" w:type="dxa"/>'
                      '<w:bottom w:w="0" w:type="dxa"/><w:right w:w="108" w:type="dxa"/>'
                      '</w:tblCellMar></w:tblPr></w:style>')
        return (XML_DECL + '<w:styles xmlns:w="%s" xmlns:r="%s">' % (W_NS, R_NS) +
                '<w:docDefaults><w:rPrDefault><w:rPr>%s</w:rPr></w:rPrDefault>'
                '<w:pPrDefault><w:pPr>%s</w:pPr></w:pPrDefault></w:docDefaults>'
                % (self.style_run_props(body_font, east, body_size),
                   self.style_para_props(line, 0, 0, ffi, align)) +
                "".join(styles) + "</w:styles>")

    def numbering_xml(self):
        def lvl(ilvl, fmt, text, start=1, ind=0):
            return ('<w:lvl w:ilvl="%d"><w:start w:val="%d"/><w:numFmt w:val="%s"/>'
                    '<w:lvlText w:val="%s"/><w:lvlJc w:val="left"/>'
                    '<w:pPr><w:ind w:left="%d" w:firstLine="0"/></w:pPr></w:lvl>'
                    % (ilvl, start, fmt, esc(text, True), ind))
        abstract = ['<w:abstractNum w:abstractNumId="0"><w:multiLevelType w:val="multilevel"/>']
        for ilvl in range(0, 4):
            item = self.numbering_levels[ilvl] if ilvl < len(self.numbering_levels) else {}
            fmt = item.get("numFmt") or "decimal"
            text = item.get("lvlText") or ("%1" if ilvl == 0 else
                                           "".join("%%%d" % (i + 1) for i in range(ilvl + 1)))
            abstract.append(lvl(ilvl, fmt, text))
        abstract.append("</w:abstractNum>")
        ref_style = (self.refs_spec.get("style") or "numeric_bracket")
        ref_text = {"numeric_bracket": "[%1]", "numeric_period": "%1."}.get(
            ref_style, "[%1]")
        ref_abstract = ('<w:abstractNum w:abstractNumId="1">'
                        '<w:multiLevelType w:val="singleLevel"/>'
                        + lvl(0, "decimal", ref_text, ind=C.cm_to_twips(
                            float(self.refs_spec.get("hanging_indent_cm") or 0.74)))
                        + "</w:abstractNum>")
        return (XML_DECL + '<w:numbering xmlns:w="%s">' % W_NS +
                "".join(abstract) + ref_abstract +
                '<w:num w:numId="1"><w:abstractNumId w:val="0"/></w:num>'
                '<w:num w:numId="2"><w:abstractNumId w:val="1"/></w:num>'
                "</w:numbering>")

    # ------------------------------------------------------------ document
    def build_document(self):
        parts = []
        for block in self.blocks:
            if block.get("type") in ("table", "figure") and block.get("caption_block"):
                self.consumed_captions.add(block["caption_block"])
        toc_needed = bool((self.spec.get("toc") or {}).get("enabled"))
        toc_done = False
        for block in self.blocks:
            kind = block.get("type")
            if kind in ("frontmatter",):
                continue
            if kind == "title":
                text = block.get("text") or ""
                parts.append(self.para(text, style="Title", jc="center"))
                if toc_needed and not toc_done:
                    parts.append(self.toc_paragraph())
                    toc_done = True
                continue
            if kind == "heading":
                level = min(int(block.get("level") or 1), 4)
                text = block.get("text") or ""
                role = block.get("heading_role")
                if role == "references":
                    ref_heading = self.refs_spec.get("heading")
                    if ref_heading and not self.spec_is_default(
                            "references.heading") and ref_heading != text:
                        self.changes.append({
                            "anchor": block["anchor"], "field": "reference heading",
                            "from": text, "to": ref_heading})
                        text = ref_heading
                    parts.append(self.para(text, style="Heading%d" % level, jc="left"))
                else:
                    num = None
                    if self.heading_numbering_used():
                        counters = self.heading_number(level)
                        self.heading_numbers[block["anchor"]] = counters
                        num = (1, level - 1)
                        # drop a literal number that duplicates the auto number
                        stripped = re.sub(r"^\s*\d+(?:\.\d+)*[\.、]?\s+", "", text)
                        if stripped and stripped != text and len(stripped) > 1:
                            self.changes.append({
                                "anchor": block["anchor"],
                                "field": "heading numbering",
                                "from": text[:60], "to": stripped[:60]})
                            text = stripped
                    parts.append(self.para(text, style="Heading%d" % level, num=num))
                continue
            if kind == "caption":
                if block["anchor"] in self.consumed_captions:
                    continue
                text, _ = self.emit_caption(block)
                parts.append(text)
                continue
            if kind == "table":
                parts.extend(self.table_with_caption(block))
                continue
            if kind == "figure":
                parts.extend(self.figure_with_caption(block))
                continue
            if kind == "reference":
                parts.append(self.reference_paragraph(block))
                continue
            if kind == "list_item":
                text = block.get("text") or ""
                text = re.sub(r"^[-*+]\s+", "\u2022 ", text)
                parts.append(self.para(text, style="Normal", indent=(720, 360)))
                continue
            if kind == "code":
                text = block.get("text") or ""
                for line in text.split("\n"):
                    parts.append(self.para(line, style="Normal", indent=(360, 0)))
                continue
            # normal paragraph; paragraphs that carry formulas, objects or
            # inline images are copied as raw runs so no content unit is lost
            if block.get("special") and block.get("body_index") is not None:
                raw = self.raw_runs(block)
                if raw:
                    self.warnings.append(
                        "anchor %s contains %s; runs copied verbatim "
                        "(cross-references inside it are not rewritten)"
                        % (block["anchor"], ", ".join(block["special"])))
                    parts.append(self.para(style="Normal", runs_xml=raw))
                    continue
            text, changed = self.fix_crossrefs(block.get("text") or "")
            if changed:
                self.changes.append({"anchor": block["anchor"],
                                     "field": "cross-reference",
                                     "changes": changed})
            parts.append(self.para(text, style="Normal"))
        if toc_needed and not toc_done:
            parts.append(self.toc_paragraph())
        return XML_DECL + (
            '<w:document xmlns:w="%s" xmlns:r="%s" xmlns:m="%s" '
            'xmlns:wp="%s" xmlns:a="%s" xmlns:pic="%s" xmlns:v="%s" '
            'xmlns:o="%s" xmlns:w10="%s" xmlns:w14="%s" xmlns:w15="%s" '
            'xmlns:wps="%s" xmlns:mc="%s" mc:Ignorable="w14 w15">'
            "<w:body>%s%s</w:body></w:document>"
            % (W_NS, R_NS, C.NS["m"], C.NS["wp"], C.NS["a"], C.NS["pic"],
               C.NS["v"], C.NS["o"], C.NS["w10"], C.NS["w14"], C.NS["w15"],
               C.NS["wps"], C.NS["mc"], "".join(parts),
               self.sect_pr()))

    def table_with_caption(self, block):
        out = []
        cap_anchor = block.get("caption_block")
        cap_block = None
        if cap_anchor:
            cap_block = next((b for b in self.blocks if b["anchor"] == cap_anchor), None)
            if cap_block:
                self.consumed_captions.add(cap_anchor)
        pos = (self.captions_spec.get("table") or {}).get("position") or "above"
        if cap_block and pos == "above":
            text, _ = self.emit_caption(cap_block)
            out.append(text)
        raw = self.raw_table(block)
        if raw:
            out.append(self.apply_table_props(raw))
        else:
            if not block.get("rows"):
                self.issues.append({"id": "table-empty-%s" % block["anchor"],
                                    "issue": "table content unavailable",
                                    "status": "partial", "anchor": block["anchor"]})
            out.append(self.build_table(block))
        if cap_block and pos == "below":
            text, _ = self.emit_caption(cap_block)
            out.append(text)
        return out

    def figure_with_caption(self, block):
        out = []
        cap_anchor = block.get("caption_block")
        cap_block = None
        if cap_anchor:
            cap_block = next((b for b in self.blocks if b["anchor"] == cap_anchor), None)
            if cap_block:
                self.consumed_captions.add(cap_anchor)
        pos = (self.captions_spec.get("figure") or {}).get("position") or "below"
        if cap_block and pos == "above":
            text, _ = self.emit_caption(cap_block)
            out.append(text)
        out.append(self.para(style="Normal", jc="center",
                             runs_xml=self.figure_runs(block)))
        if cap_block and pos == "below":
            text, _ = self.emit_caption(cap_block)
            out.append(text)
        return out

    def reference_paragraph(self, block):
        text = block.get("text") or ""
        style = self.refs_spec.get("style") or "numeric_bracket"
        stripped = re.sub(r"^\s*(?:\[\d+\]|\d+[\.\、])\s*", "", text)
        if stripped != text:
            self.changes.append({"anchor": block["anchor"],
                                 "field": "reference numbering",
                                 "from": text[:40], "to": stripped[:40]})
            text = stripped
        text, changed = self.fix_crossrefs(text)
        if changed:
            self.changes.append({"anchor": block["anchor"],
                                 "field": "cross-reference",
                                 "changes": changed})
        num = None if style in ("author_year", "none") else (2, 0)
        return self.para(text, style="Bibliography", num=num, jc="left")

    def toc_paragraph(self):
        title = "Contents"
        if C.has_cjk(self.manuscript_title()):
            title = "\u76ee\u5f55"
        return ('<w:p><w:pPr><w:pStyle w:val="Heading1"/><w:jc w:val="center"/>'
                '</w:pPr><w:r><w:t>%s</w:t></w:r></w:p>'
                '<w:p><w:r><w:fldChar w:fldCharType="begin" w:dirty="true"/></w:r>'
                '<w:r><w:instrText xml:space="preserve"> TOC \\o "1-3" \\h \\z \\u '
                '</w:instrText></w:r><w:r><w:fldChar w:fldCharType="separate"/></w:r>'
                '<w:r><w:t>Update this field to build the table of contents.</w:t>'
                '</w:r><w:r><w:fldChar w:fldCharType="end"/></w:r></w:p>' % title)

    def manuscript_title(self):
        for block in self.blocks:
            if block.get("type") == "title":
                return block.get("text") or ""
        return ""

    def sect_pr(self):
        page = self.page
        width = C.cm_to_twips(float(page.get("width_cm") or 21.0))
        height = C.cm_to_twips(float(page.get("height_cm") or 29.7))
        margins = page.get("margins_cm") or {}
        top = C.cm_to_twips(float(margins.get("top") or 2.54))
        bottom = C.cm_to_twips(float(margins.get("bottom") or 2.54))
        left = C.cm_to_twips(float(margins.get("left") or 2.54))
        right = C.cm_to_twips(float(margins.get("right") or 2.54))
        cols = int(page.get("columns") or 1)
        parts = []
        if (self.header_spec.get("enabled") or self.header_spec.get("text")):
            parts.append('<w:headerReference w:type="default" r:id="rIdHeader"/>')
        if self.pn_spec.get("enabled"):
            parts.append('<w:footerReference w:type="default" r:id="rIdFooter"/>')
        parts.append('<w:pgSz w:w="%d" w:h="%d"%s/>'
                     % (width, height,
                        ' w:orient="landscape"' if width > height else ""))
        parts.append('<w:pgMar w:top="%d" w:right="%d" w:bottom="%d" w:left="%d" '
                     'w:header="720" w:footer="720" w:gutter="0"/>'
                     % (top, right, bottom, left))
        if self.pn_spec.get("enabled"):
            fmt = self.pn_spec.get("fmt") or "decimal"
            if fmt not in ("decimal", "lowerRoman", "upperRoman", "lowerLetter",
                           "upperLetter", "chineseCounting", "chineseCountingThousand"):
                fmt = "decimal"
            start = int(self.pn_spec.get("start") or 1)
            parts.append('<w:pgNumType w:fmt="%s" w:start="%d"/>' % (fmt, start))
        parts.append('<w:cols w:num="%d" w:space="425"/>' % cols)
        parts.append('<w:docGrid w:linePitch="312"/>')
        return "<w:sectPr>%s</w:sectPr>" % "".join(parts)

    def footer_xml(self):
        pos = (self.pn_spec.get("position") or "footer_center")
        jc = "right" if pos.endswith("right") else (
            "left" if pos.endswith("left") else "center")
        return (XML_DECL + '<w:ftr xmlns:w="%s" xmlns:r="%s"><w:p><w:pPr>'
                '<w:pStyle w:val="Footer"/><w:jc w:val="%s"/></w:pPr>'
                '<w:r><w:fldChar w:fldCharType="begin"/></w:r>'
                '<w:r><w:instrText xml:space="preserve"> PAGE </w:instrText></w:r>'
                '<w:r><w:fldChar w:fldCharType="separate"/></w:r>'
                '<w:r><w:t>1</w:t></w:r>'
                '<w:r><w:fldChar w:fldCharType="end"/></w:r></w:p></w:ftr>'
                % (W_NS, R_NS, jc))

    def header_xml(self):
        text = self.header_spec.get("text") or self.manuscript_title() or ""
        return (XML_DECL + '<w:hdr xmlns:w="%s" xmlns:r="%s"><w:p><w:pPr>'
                '<w:pStyle w:val="Header"/><w:jc w:val="center"/></w:pPr>'
                '<w:r><w:t xml:space="preserve">%s</w:t></w:r></w:p></w:hdr>'
                % (W_NS, R_NS, esc(text)))

    # ------------------------------------------------------------ package
    def package(self):
        media_rels = sorted(self.media_rel.items(), key=lambda kv: kv[1])

        rels = ['<Relationship Id="rIdStyles" Type="http://schemas.openxmlformats.org/'
                'officeDocument/2006/relationships/styles" Target="styles.xml"/>',
                '<Relationship Id="rIdNumbering" Type="http://schemas.openxmlformats.org/'
                'officeDocument/2006/relationships/numbering" Target="numbering.xml"/>',
                '<Relationship Id="rIdSettings" Type="http://schemas.openxmlformats.org/'
                'officeDocument/2006/relationships/settings" Target="settings.xml"/>',
                '<Relationship Id="rIdFontTable" Type="http://schemas.openxmlformats.org/'
                'officeDocument/2006/relationships/fontTable" Target="fontTable.xml"/>']
        if self.pn_spec.get("enabled"):
            rels.append('<Relationship Id="rIdFooter" Type="http://schemas.openxmlformats'
                        '.org/officeDocument/2006/relationships/footer" Target="footer1.xml"/>')
        if self.header_spec.get("enabled") or self.header_spec.get("text"):
            rels.append('<Relationship Id="rIdHeader" Type="http://schemas.openxmlformats'
                        '.org/officeDocument/2006/relationships/header" Target="header1.xml"/>')
        for rid, name in media_rels:
            rels.append('<Relationship Id="%s" Type="http://schemas.openxmlformats.org/'
                        'officeDocument/2006/relationships/image" Target="%s"/>'
                        % (rid, name))
        document_rels = (XML_DECL + '<Relationships xmlns="http://schemas.openxmlformats'
                         '.org/package/2006/relationships">' + "".join(rels)
                         + "</Relationships>")

        defaults = [
            '<Default Extension="rels" ContentType="application/vnd.openxmlformats-'
            'package.relationships+xml"/>',
            '<Default Extension="xml" ContentType="application/xml"/>']
        for name in sorted(self.media):
            ext = os.path.splitext(name)[1].lower().lstrip(".")
            ctype = IMAGE_TYPES.get(ext)
            if ctype and ('Extension="%s"' % ext) not in "".join(defaults):
                defaults.append('<Default Extension="%s" ContentType="%s"/>'
                                % (ext, ctype))
        overrides = [
            ('/word/document.xml', CONTENT_TYPES + '.document.main+xml'),
            ('/word/styles.xml', CONTENT_TYPES + '.styles+xml'),
            ('/word/numbering.xml', CONTENT_TYPES + '.numbering+xml'),
            ('/word/settings.xml', CONTENT_TYPES + '.settings+xml'),
            ('/word/fontTable.xml', CONTENT_TYPES + '.fontTable+xml'),
            ('/docProps/core.xml', 'application/vnd.openxmlformats-package.core-properties+xml'),
            ('/docProps/app.xml', 'application/vnd.openxmlformats-officedocument'
             '.extended-properties+xml'),
        ]
        if self.pn_spec.get("enabled"):
            overrides.append(('/word/footer1.xml', CONTENT_TYPES + '.footer+xml'))
        if self.header_spec.get("enabled") or self.header_spec.get("text"):
            overrides.append(('/word/header1.xml', CONTENT_TYPES + '.header+xml'))
        content_types = (XML_DECL + '<Types xmlns="http://schemas.openxmlformats.org/'
                         'package/2006/content-types">' + "".join(defaults) +
                         "".join('<Override PartName="%s" ContentType="%s"/>' % o
                                 for o in overrides) + "</Types>")

        root_rels = (XML_DECL + '<Relationships xmlns="http://schemas.openxmlformats.org/'
                     'package/2006/relationships">'
                     '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/'
                     'officeDocument/2006/relationships/officeDocument" '
                     'Target="word/document.xml"/>'
                     '<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/'
                     'package/2006/relationships/metadata/core-properties" '
                     'Target="docProps/core.xml"/>'
                     '<Relationship Id="rId3" Type="http://schemas.openxmlformats.org/'
                     'officeDocument/2006/relationships/extended-properties" '
                     'Target="docProps/app.xml"/></Relationships>')

        title = self.manuscript_title()
        core = (XML_DECL + '<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/'
                'package/2006/metadata/core-properties" '
                'xmlns:dc="http://purl.org/dc/elements/1.1/" '
                'xmlns:dcterms="http://purl.org/dc/terms/" '
                'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">'
                '<dc:title>%s</dc:title><dc:creator>format-adaptation-skill</dc:creator>'
                '<cp:lastModifiedBy>format-adaptation-skill</cp:lastModifiedBy>'
                '<dcterms:created xsi:type="dcterms:W3CDTF">%s</dcterms:created>'
                '<dcterms:modified xsi:type="dcterms:W3CDTF">%s</dcterms:modified>'
                '</cp:coreProperties>' % (
                    esc(title), self._now(), self._now()))
        app = (XML_DECL + '<Properties xmlns="http://schemas.openxmlformats.org/'
               'officeDocument/2006/extended-properties" xmlns:vt="http://schemas.'
               'openxmlformats.org/officeDocument/2006/docPropsVTypes">'
               '<Application>format-adaptation-skill</Application>'
               '<AppVersion>1.0</AppVersion></Properties>')
        settings = (XML_DECL + '<w:settings xmlns:w="%s"><w:zoom w:percent="100"/>'
                    '<w:defaultTabStop w:val="420"/>'
                    '<w:characterSpacingControl w:val="doNotCompress"/>%s'
                    '</w:settings>'
                    % (W_NS, '<w:updateFields w:val="true"/>'
                       if (self.spec.get("toc") or {}).get("enabled") else ""))
        fonts = sorted({f for f in [
            self.body.get("font_latin"), self.body.get("font_east_asia"),
            *[c.get("font_latin") for c in self.headings_spec.values()
              if isinstance(c, dict)],
            *[c.get("font_east_asia") for c in self.headings_spec.values()
              if isinstance(c, dict)]] if f})
        font_table = (XML_DECL + '<w:fonts xmlns:w="%s">%s</w:fonts>'
                      % (W_NS, "".join(
                          '<w:font w:name="%s"><w:charset w:val="00"/>'
                          '<w:family w:val="roman"/><w:pitch w:val="variable"/>'
                          '</w:font>' % esc(f, True) for f in fonts)))
        parts = {
            "[Content_Types].xml": content_types,
            "_rels/.rels": root_rels,
            "docProps/core.xml": core,
            "docProps/app.xml": app,
            "word/document.xml": self.build_document(),
            "word/styles.xml": self.styles_xml(),
            "word/numbering.xml": self.numbering_xml(),
            "word/settings.xml": settings,
            "word/fontTable.xml": font_table,
            "word/_rels/document.xml.rels": document_rels,
        }
        if self.pn_spec.get("enabled"):
            parts["word/footer1.xml"] = self.footer_xml()
        if self.header_spec.get("enabled") or self.header_spec.get("text"):
            parts["word/header1.xml"] = self.header_xml()
        for name, data in self.media.items():
            parts["word/" + name] = data
        return parts

    @staticmethod
    def _now():
        return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    def write(self, path):
        parts = self.package()
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
            order = ["[Content_Types].xml", "_rels/.rels"]
            for name in order:
                zf.writestr(name, parts.pop(name))
            for name in sorted(parts):
                data = parts[name]
                if isinstance(data, str):
                    data = data.encode("utf-8")
                zf.writestr(name, data)
        return path


# ---------------------------------------------------------------- verify own output
def reopen_and_compare(path, inputs, builder):
    check = {"ok": False, "reason": None, "paragraphs": 0,
             "styles_used": [], "tables": 0, "drawings": 0,
             "headings_by_level": {}, "missing_blocks": [],
             "caption_numbers": [], "reference_paragraphs": 0}
    ok, reason = C.docx_valid(path)
    check["reason"] = reason
    if not ok:
        return check
    docx = C.Docx(path)
    try:
        root = docx.xml("word/document.xml")
        styles_root = docx.xml("word/styles.xml")
        smap, _ = C.style_map(styles_root)
        texts = []
        for p in root.iter(C.qn("w", "p")):
            text = C.paragraph_text(p)
            texts.append(text)
            if text.strip():
                check["paragraphs"] += 1
            ppr = p.find(C.qn("w", "pPr"))
            pstyle = None
            if ppr is not None:
                ps = ppr.find(C.qn("w", "pStyle"))
                if ps is not None:
                    pstyle = ps.get(C.qn("w", "val"))
            if pstyle:
                check["styles_used"].append(pstyle)
                if re.match(r"^Heading([1-4])$", pstyle or ""):
                    lvl = int(pstyle[-1])
                    check["headings_by_level"][str(lvl)] = \
                        check["headings_by_level"].get(str(lvl), 0) + 1
                if pstyle == "Bibliography":
                    check["reference_paragraphs"] += 1
                if pstyle == "Caption":
                    m = re.match(r"^\s*(?:Figure|Fig\.?|图|Table|Tab\.?|表)\s*(\d+)",
                                 text.strip())
                    if m:
                        check["caption_numbers"].append(int(m.group(1)))
            for el in p.iter():
                if C.local(el.tag) == "drawing":
                    check["drawings"] += 1
        check["tables"] = len(list(root.iter(C.qn("w", "tbl"))))
        check["styles_used"] = sorted(set(check["styles_used"]))
        check["defined_styles"] = sorted(smap.keys())
        missing = []
        for block in inputs.get("manuscript", {}).get("blocks") or []:
            kind = block.get("type")
            text = (block.get("text") or "").strip()
            if kind in ("frontmatter", "table", "figure"):
                continue
            if kind == "caption":
                continue
            if kind == "code":
                continue
            if not text:
                continue
            expected, _ = builder.fix_crossrefs(text)
            expected = C.sanitize_text(expected)
            candidates = [expected]
            if kind == "heading":
                # source may carry a literal number while the DOCX renders it
                # through numbering.xml, so the paragraph text has no prefix
                stripped = re.sub(r"^\s*(?:\d+(?:\.\d+)*)[\.\、]?\s+", "",
                                  expected)
                if stripped and stripped != expected:
                    candidates.append(stripped)
            if kind == "reference":
                expected = re.sub(r"^\s*(?:\[\d+\]|\d+[\.\、])\s*", "", expected)
                candidates = [expected]
            hit = any(c and c in t for c in candidates for t in texts)
            if not hit:
                missing.append({"anchor": block.get("anchor"), "type": kind,
                                "excerpt": text[:80]})
            if len(missing) >= 20:
                break
        check["missing_blocks"] = missing
        check["ok"] = True
    except Exception as exc:  # noqa: BLE001
        check["reason"] = "%s: %s" % (type(exc).__name__, exc)
    finally:
        docx.close()
    return check


def content_stats(inputs, check):
    source_chars = sum(len((b.get("text") or "")) for b in
                       (inputs.get("manuscript") or {}).get("blocks") or [])
    return {"source_chars": source_chars,
            "output_paragraphs": check.get("paragraphs"),
            "missing_blocks": len(check.get("missing_blocks") or [])}


# ---------------------------------------------------------------- main
def main(argv=None):
    ap = argparse.ArgumentParser(description="Build formatted DOCX from spec + inputs")
    ap.add_argument("--work", default="/app/work")
    ap.add_argument("--output", default="/app/output")
    ap.add_argument("--name", default="manuscript_formatted")
    ap.add_argument("--no-render", action="store_true",
                    help="skip PDF rendering even if soffice exists")
    args = ap.parse_args(argv)

    os.makedirs(args.work, exist_ok=True)
    os.makedirs(args.output, exist_ok=True)
    inputs = C.read_json(os.path.join(args.work, "inputs.json"))
    spec = C.read_json(os.path.join(args.work, "spec.json"))
    meta = {"schema": "build-meta/v1", "status": "failed", "docx": None,
            "pdf": None, "warnings": [], "issues": [], "changes": [],
            "rendering": {"attempted": False, "produced": False, "reason": None}}
    if not inputs or not spec:
        meta["error"] = "inputs.json or spec.json missing/unreadable"
        C.write_json(os.path.join(args.output, "build_meta.json"), meta)
        print(json.dumps(meta, ensure_ascii=False, indent=1))
        return 2

    manuscript = inputs.get("manuscript") or {}
    if not manuscript.get("blocks"):
        meta["error"] = "no manuscript content blocks; refusing to fabricate a document"
        meta["manuscript"] = manuscript.get("path")
        C.write_json(os.path.join(args.output, "build_meta.json"), meta)
        print(json.dumps(meta, ensure_ascii=False, indent=1))
        return 2

    builder = Builder(inputs, spec, args.output, args.work)
    builder.load_source()
    docx_path = os.path.join(args.output, args.name + ".docx")
    builder.write(docx_path)
    meta["docx"] = os.path.abspath(docx_path)
    meta["docx_bytes"] = os.path.getsize(docx_path)
    meta["docx_sha256"] = C.sha256_file(docx_path)

    check = reopen_and_compare(docx_path, inputs, builder)
    meta["reopen"] = check
    meta["content_check"] = content_stats(inputs, check)
    meta["paragraphs"] = check.get("paragraphs")
    meta["tables"] = check.get("tables")
    meta["drawings"] = check.get("drawings")
    meta["headings_by_level"] = check.get("headings_by_level")
    meta["caption_numbers"] = check.get("caption_numbers")
    meta["reference_paragraphs"] = check.get("reference_paragraphs")
    meta["used_styles"] = check.get("styles_used")
    meta["issues"] = builder.issues
    meta["warnings"] = builder.warnings
    meta["changes"] = builder.changes
    meta["heading_numbers"] = builder.heading_numbers
    meta["caption_map"] = builder.caption_map
    meta["page"] = {"width_cm": builder.page.get("width_cm"),
                    "height_cm": builder.page.get("height_cm"),
                    "margins_cm": builder.page.get("margins_cm"),
                    "columns": builder.page.get("columns")}

    # ---- optional real PDF render -----------------------------------
    want_pdf = "pdf" in [str(x).lower() for x in
                         (builder.export_spec.get("formats") or [])]
    soffice = C.which("soffice") or C.which("libreoffice")
    if not check.get("ok"):
        meta["status"] = "failed"
        meta["error"] = "produced docx did not reopen: %s" % check.get("reason")
    elif soffice and not args.no_render:
        meta["rendering"]["attempted"] = True
        render_dir = os.path.join(args.work, "render")
        C.ensure_dir(render_dir)
        rc, out, err = C.run([soffice, "--headless", "--norestore",
                              "--convert-to", "pdf", "--outdir", render_dir,
                              docx_path], timeout=240)
        pdf_src = os.path.join(render_dir, args.name + ".pdf")
        if rc == 0 and os.path.exists(pdf_src) and os.path.getsize(pdf_src) > 1000:
            pdf_dst = os.path.join(args.output, args.name + ".pdf")
            with open(pdf_src, "rb") as fh:
                data = fh.read()
            with open(pdf_dst, "wb") as fh:
                fh.write(data)
            pages, method = C.pdf_page_count(pdf_dst)
            fonts = C.pdf_fonts(pdf_dst)
            meta["pdf"] = os.path.abspath(pdf_dst)
            meta["pdf_bytes"] = os.path.getsize(pdf_dst)
            meta["pdf_sha256"] = C.sha256_file(pdf_dst)
            meta["rendering"].update({
                "produced": True, "engine": soffice,
                "page_count": pages, "page_count_method": method,
                "fonts_detected": fonts.get("base_fonts"),
                "font_embedding_markers": fonts.get("embedding_markers"),
                "page_count_verified_by": method})
            meta["page_count"] = pages
        else:
            meta["rendering"]["reason"] = (
                "soffice exited %d; %s" % (rc, (err or out).strip()[:300]))
    else:
        meta["rendering"]["attempted"] = False
        meta["rendering"]["reason"] = (
            "LibreOffice (soffice) not installed" if not soffice
            else "rendering disabled by --no-render")
    if want_pdf and not meta["rendering"].get("produced"):
        meta["issues"].append({
            "id": "pdf-not-produced", "status": "partial",
            "issue": "spec requests PDF export but no PDF was produced: %s"
                     % meta["rendering"].get("reason")})

    # font availability
    family = (spec.get("body") or {}).get("font_latin")
    available, matched, detail = C.font_available(family)
    meta["font_check"] = {"requested": family, "available": available,
                          "matched": matched, "detail": detail}
    if available is False:
        # the DOCX still carries the requested font name; this is a renderer
        # limitation, so it is surfaced as uncertainty rather than a format error
        meta["warnings"].append(
            "font %r is not installed; renderers may substitute %r"
            % (family, matched or "another face"))

    if check.get("ok"):
        meta["status"] = "built"
    C.write_json(os.path.join(args.output, "build_meta.json"), meta)
    print(json.dumps({
        "status": meta["status"], "docx": meta["docx"],
        "bytes": meta.get("docx_bytes"), "paragraphs": meta.get("paragraphs"),
        "tables": meta.get("tables"), "drawings": meta.get("drawings"),
        "pdf": meta.get("pdf"), "page_count": meta.get("page_count"),
        "missing_blocks": len(check.get("missing_blocks") or []),
        "issues": [i["id"] for i in meta["issues"]],
    }, ensure_ascii=False, indent=1))
    return 0 if meta["status"] == "built" else 1


if __name__ == "__main__":
    sys.exit(main())
