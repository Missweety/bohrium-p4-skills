#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""docx_mini.py - write a real, reopenable .docx using only the standard library.

Why this file exists
--------------------
The task asks for an editable deliverable.  A Markdown file alone does not
satisfy "editable Word document" and python-docx is not guaranteed to be
installed.  This module writes WordprocessingML directly with zipfile, so the
runtime needs no third-party package.

Supported Markdown subset
-------------------------
  # .. ####      headings (Heading1..Heading4, outline levels preserved)
  - / * / +      bullet list (ListBullet)
  1. 2.          numbered list (ListNumber)
  >              quote
  ```            code block
  | a | b |      real Word table with borders and a shaded header row
  **bold**       inline bold runs (asterisks removed)
  `code`         inline monospace runs
  ---            horizontal rule -> horizontal-rule paragraph

``verify_docx`` reopens the produced file and checks the OOXML package, so a
caller can prove the output is a real DOCX rather than a renamed text file.
"""
from __future__ import annotations

import os
import re
import zipfile
from xml.etree import ElementTree as ET
from xml.sax.saxutils import escape

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
CP = "http://schemas.openxmlformats.org/package/2006/metadata/core-properties"

CONTENT_TYPES = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
<Default Extension="xml" ContentType="application/xml"/>
<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
<Override PartName="/word/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/>
<Override PartName="/docProps/core.xml" ContentType="application/vnd.openxmlformats-package.core-properties+xml"/>
<Override PartName="/docProps/app.xml" ContentType="application/vnd.openxmlformats-officedocument.extended-properties+xml"/>
</Types>"""

ROOT_RELS = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>
<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties" Target="docProps/core.xml"/>
<Relationship Id="rId3" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/extended-properties" Target="docProps/app.xml"/>
</Relationships>"""

DOC_RELS = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>
</Relationships>"""

STYLES = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:styles xmlns:w="%s">
<w:docDefaults><w:rPrDefault><w:rPr>
<w:rFonts w:ascii="Times New Roman" w:hAnsi="Times New Roman" w:eastAsia="SimSun" w:cs="Times New Roman"/>
<w:sz w:val="22"/><w:szCs w:val="22"/>
</w:rPr></w:rPrDefault><w:pPrDefault><w:pPr>
<w:spacing w:after="120" w:line="276" w:lineRule="auto"/>
</w:pPr></w:pPrDefault></w:docDefaults>
<w:style w:type="paragraph" w:default="1" w:styleId="Normal"><w:name w:val="Normal"/></w:style>
<w:style w:type="paragraph" w:styleId="Heading1"><w:name w:val="heading 1"/><w:basedOn w:val="Normal"/>
<w:pPr><w:keepNext/><w:spacing w:before="240" w:after="120"/><w:outlineLvl w:val="0"/></w:pPr>
<w:rPr><w:b/><w:sz w:val="32"/><w:szCs w:val="32"/></w:rPr></w:style>
<w:style w:type="paragraph" w:styleId="Heading2"><w:name w:val="heading 2"/><w:basedOn w:val="Normal"/>
<w:pPr><w:keepNext/><w:spacing w:before="200" w:after="100"/><w:outlineLvl w:val="1"/></w:pPr>
<w:rPr><w:b/><w:sz w:val="28"/><w:szCs w:val="28"/></w:rPr></w:style>
<w:style w:type="paragraph" w:styleId="Heading3"><w:name w:val="heading 3"/><w:basedOn w:val="Normal"/>
<w:pPr><w:keepNext/><w:spacing w:before="160" w:after="80"/><w:outlineLvl w:val="2"/></w:pPr>
<w:rPr><w:b/><w:sz w:val="24"/><w:szCs w:val="24"/></w:rPr></w:style>
<w:style w:type="paragraph" w:styleId="Heading4"><w:name w:val="heading 4"/><w:basedOn w:val="Normal"/>
<w:pPr><w:keepNext/><w:spacing w:before="140" w:after="70"/><w:outlineLvl w:val="3"/></w:pPr>
<w:rPr><w:b/><w:i/><w:sz w:val="22"/><w:szCs w:val="22"/></w:rPr></w:style>
<w:style w:type="paragraph" w:styleId="ListBullet"><w:name w:val="List Bullet"/><w:basedOn w:val="Normal"/>
<w:pPr><w:ind w:left="420" w:hanging="210"/></w:pPr></w:style>
<w:style w:type="paragraph" w:styleId="ListNumber"><w:name w:val="List Number"/><w:basedOn w:val="Normal"/>
<w:pPr><w:ind w:left="420" w:hanging="210"/></w:pPr></w:style>
<w:style w:type="paragraph" w:styleId="Quote"><w:name w:val="Quote"/><w:basedOn w:val="Normal"/>
<w:pPr><w:ind w:left="480"/></w:pPr><w:rPr><w:i/></w:rPr></w:style>
<w:style w:type="paragraph" w:styleId="Code"><w:name w:val="Code"/><w:basedOn w:val="Normal"/>
<w:pPr><w:ind w:left="420"/></w:pPr>
<w:rPr><w:rFonts w:ascii="Consolas" w:hAnsi="Consolas"/><w:sz w:val="20"/></w:rPr></w:style>
<w:style w:type="paragraph" w:styleId="Rule"><w:name w:val="Rule"/><w:basedOn w:val="Normal"/>
<w:pPr><w:pBdr><w:bottom w:val="single" w:sz="6" w:space="1" w:color="BCCCDC"/></w:pBdr></w:pPr></w:style>
</w:styles>""" % W

APP = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Properties xmlns="http://schemas.openxmlformats.org/officeDocument/2006/extended-properties">
<Application>research-proposal-plan (stdlib docx_mini)</Application>
</Properties>"""

HEADING_RE = re.compile(r"^(#{1,6})\s+(.*)$")
BULLET_RE = re.compile(r"^\s*[-*+]\s+(.*)$")
ORDERED_RE = re.compile(r"^\s*(\d+)[.)]\s+(.*)$")
QUOTE_RE = re.compile(r"^\s*>\s?(.*)$")
CODE_FENCE_RE = re.compile(r"^\s*```")
RULE_RE = re.compile(r"^\s*-{3,}\s*$")
TABLE_ROW_RE = re.compile(r"^\s*\|.*\|\s*$")
TABLE_SEP_RE = re.compile(r"^\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)+\|?\s*$")


def _runs(text):
    """Turn **bold** and `code` spans into Word runs."""
    out = []
    pos = 0
    pattern = re.compile(r"\*\*(.+?)\*\*|`([^`]+)`")
    for match in pattern.finditer(text or ""):
        if match.start() > pos:
            out.append('<w:r><w:t xml:space="preserve">%s</w:t></w:r>'
                       % escape((text or "")[pos:match.start()]))
        if match.group(1) is not None:
            out.append('<w:r><w:rPr><w:b/></w:rPr><w:t xml:space="preserve">%s</w:t></w:r>'
                       % escape(match.group(1)))
        else:
            out.append('<w:r><w:rPr><w:rFonts w:ascii="Consolas" w:hAnsi="Consolas"/>'
                       '<w:sz w:val="20"/></w:rPr><w:t xml:space="preserve">%s</w:t></w:r>'
                       % escape(match.group(2)))
        pos = match.end()
    if pos < len(text or ""):
        out.append('<w:r><w:t xml:space="preserve">%s</w:t></w:r>'
                   % escape((text or "")[pos:]))
    if not out:
        out.append('<w:r><w:t xml:space="preserve"></w:t></w:r>')
    return "".join(out)


def _para(text, style=None, mono=False):
    ppr = '<w:pPr><w:pStyle w:val="%s"/></w:pPr>' % style if style else ""
    if mono:
        run = ('<w:r><w:rPr><w:rFonts w:ascii="Consolas" w:hAnsi="Consolas"/>'
               '<w:sz w:val="20"/></w:rPr><w:t xml:space="preserve">%s</w:t></w:r>'
               % escape(text or ""))
    else:
        run = _runs(text)
    return "<w:p>%s%s</w:p>" % (ppr, run)


def _cell(text, header=False, width=2000):
    shade = '<w:shd w:val="clear" w:color="auto" w:fill="EEF2F6"/>' if header else ""
    bold = "<w:rPr><w:b/></w:rPr>" if header else ""
    return ('<w:tc><w:tcPr><w:tcW w:w="%d" w:type="dxa"/>%s</w:tcPr>'
            '<w:p><w:pPr><w:spacing w:after="40"/></w:pPr>'
            '<w:r>%s<w:t xml:space="preserve">%s</w:t></w:r></w:p></w:tc>'
            % (width, shade, bold, escape(text or "")))


def _table(rows):
    if not rows:
        return ""
    cols = max(len(r) for r in rows)
    width = max(900, int(9000 / max(1, cols)))
    borders = ('<w:tblBorders>'
               + "".join('<w:%s w:val="single" w:sz="4" w:space="0" w:color="BCCCDC"/>' % side
                         for side in ("top", "left", "bottom", "right", "insideH", "insideV"))
               + '</w:tblBorders>')
    header = rows[0]
    body = rows[1:]
    xml = ['<w:tbl><w:tblPr><w:tblW w:w="0" w:type="auto"/>%s</w:tblPr>' % borders]
    xml.append("<w:tr><w:trPr><w:tblHeader/></w:trPr>%s</w:tr>"
               % "".join(_cell((header[i] if i < len(header) else "").strip(), True, width)
                         for i in range(cols)))
    for row in body:
        xml.append("<w:tr>%s</w:tr>"
                   % "".join(_cell((row[i] if i < len(row) else "").strip(), False, width)
                             for i in range(cols)))
    xml.append("</w:tbl>")
    # Word needs a paragraph after a table for stable layout.
    xml.append("<w:p/>")
    return "".join(xml)


def _split_row(line):
    inner = line.strip().strip("|")
    return [part.strip() for part in inner.split("|")]


def markdown_to_body(md_text):
    """Convert the supported Markdown subset into WordprocessingML paragraphs."""
    paras = []
    in_code = False
    lines = (md_text or "").split("\n")
    index = 0
    while index < len(lines):
        line = lines[index].rstrip()
        if CODE_FENCE_RE.match(line):
            in_code = not in_code
            index += 1
            continue
        if in_code:
            paras.append(_para(line, "Code", mono=True))
            index += 1
            continue
        if TABLE_ROW_RE.match(line):
            block = []
            while index < len(lines) and TABLE_ROW_RE.match(lines[index].strip()):
                block.append(lines[index])
                index += 1
            rows = []
            for row_index, raw in enumerate(block):
                if row_index == 1 and TABLE_SEP_RE.match(raw):
                    continue
                rows.append(_split_row(raw))
            paras.append(_table(rows))
            continue
        if not line.strip():
            paras.append(_para(""))
            index += 1
            continue
        match = HEADING_RE.match(line)
        if match:
            level = min(len(match.group(1)), 4)
            paras.append(_para(match.group(2).strip(), "Heading%d" % level))
            index += 1
            continue
        if RULE_RE.match(line):
            paras.append(_para("", "Rule"))
            index += 1
            continue
        match = BULLET_RE.match(line)
        if match:
            paras.append(_para("• " + match.group(1).strip(), "ListBullet"))
            index += 1
            continue
        match = ORDERED_RE.match(line)
        if match:
            paras.append(_para("%s. %s" % (match.group(1), match.group(2).strip()),
                               "ListNumber"))
            index += 1
            continue
        match = QUOTE_RE.match(line)
        if match:
            paras.append(_para(match.group(1), "Quote"))
            index += 1
            continue
        paras.append(_para(line))
        index += 1
    return "".join(paras)


def _core_xml(title):
    return ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<cp:coreProperties xmlns:cp="%s" '
            'xmlns:dc="http://purl.org/dc/elements/1.1/" '
            'xmlns:dcterms="http://purl.org/dc/terms/" '
            'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">'
            '<dc:title>%s</dc:title><dc:creator>research-proposal-plan</dc:creator>'
            '<cp:lastModifiedBy>research-proposal-plan</cp:lastModifiedBy>'
            '</cp:coreProperties>' % (CP, escape(title or "Research proposal")))


def write_docx(markdown_text, out_path, title=None):
    """Write an editable DOCX and return a summary dictionary."""
    body = markdown_to_body(markdown_text)
    sect = ('<w:sectPr><w:pgSz w:w="11906" w:h="16838"/>'
            '<w:pgMar w:top="1440" w:right="1440" w:bottom="1440" w:left="1440" '
            'w:header="851" w:footer="992" w:gutter="0"/></w:sectPr>')
    document = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
                '<w:document xmlns:w="%s" xmlns:r="%s"><w:body>%s%s</w:body></w:document>'
                % (W, R, body, sect))
    tmp = out_path + ".tmp"
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("[Content_Types].xml", CONTENT_TYPES)
        zf.writestr("_rels/.rels", ROOT_RELS)
        zf.writestr("word/document.xml", document)
        zf.writestr("word/styles.xml", STYLES)
        zf.writestr("word/_rels/document.xml.rels", DOC_RELS)
        zf.writestr("docProps/core.xml", _core_xml(title))
        zf.writestr("docProps/app.xml", APP)
    if os.path.exists(out_path):
        os.remove(out_path)
    os.rename(tmp, out_path)
    return verify_docx(out_path)


def verify_docx(path):
    """Reopen a DOCX package and validate its OOXML parts.

    Returns {"ok": bool, "bytes": int, "paragraphs": int, "tables": int,
             "has_document_xml": bool, "error": str|None}
    """
    result = {"ok": False, "bytes": 0, "paragraphs": 0, "tables": 0,
              "has_document_xml": False, "has_styles": False, "error": None}
    try:
        result["bytes"] = os.path.getsize(path)
        with zipfile.ZipFile(path) as zf:
            names = set(zf.namelist())
            result["has_document_xml"] = "word/document.xml" in names
            result["has_styles"] = "word/styles.xml" in names
            if not result["has_document_xml"]:
                result["error"] = "missing word/document.xml"
                return result
            root = ET.fromstring(zf.read("word/document.xml"))
            body = root.find(W_BODY)
            if body is None:
                result["error"] = "document.xml has no w:body"
                return result
            result["paragraphs"] = len(list(body.iter(W_P)))
            result["tables"] = len(list(body.iter(W_TBL)))
            # A document with no text at all is not a usable deliverable.
            text = "".join(node.text or "" for node in body.iter(W_T))
            if not text.strip():
                result["error"] = "document.xml contains no readable text"
                return result
            result["text_chars"] = len(text)
            result["ok"] = True
    except Exception as exc:  # noqa: BLE001
        result["error"] = "%s: %s" % (type(exc).__name__, str(exc)[:200])
    return result


W_BODY = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}body"
W_P = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}p"
W_TBL = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}tbl"
W_T = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}t"
