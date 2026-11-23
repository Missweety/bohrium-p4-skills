#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""extract_sources.py - turn /input materials into anchored paragraphs.

Command (run from anywhere; the Skill lives at /skills/weekly-skill):

    python3 "$SKILL_DIR/scripts/extract_sources.py" --input /input --work /app/work

Supported inputs: PDF (pdftotext, then pypdf/PyPDF2), DOCX (zip + OOXML),
Markdown, plain text, TeX, CSV/TSV, HTML, JSON. /input/case.json and
/input/task.md are metadata and are skipped.

Output: <work>/sources.json

    {
      "case_id": "...",
      "stats": {...},
      "sources": [
        {"id": "S1", "file": "notes.md", "kind": "md", "tier": "text",
         "readable": true, "paragraphs": [
           {"anchor": "S1#p1.3", "text": "...", "page": 1,
            "section": "1.1 背景", "line_start": 12, "line_end": 15}
         ]}
      ],
      "unreadable": [...], "skipped": [...]
    }

Every paragraph keeps its verbatim text. Anchors are the only citation
handles accepted downstream, so a quote can always be checked against the
exact paragraph it came from.
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import os
import re
import shutil
import subprocess
import sys
import zipfile
from html.parser import HTMLParser
from xml.etree import ElementTree as ET

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import common  # noqa: E402

SKIP_NAMES = {"case.json", "task.md", "challenge.json", "readme.md", "config.json"}
SKIP_EXTS = {".pyc", ".pyo", ".so", ".dylib", ".dll", ".exe", ".png", ".jpg",
             ".jpeg", ".gif", ".webp", ".bmp", ".tif", ".tiff", ".zip",
             ".doc", ".ppt", ".pptx", ".xlsx", ".xls", ".mp4", ".mov", ".wav"}
MAX_PARAGRAPHS_PER_FILE = 4000
MAX_PARAGRAPH_CHARS = 12000

W_NS = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


def _mk_para(anchor, text, page=1, section="", line_start=None, line_end=None,
             is_heading=False, in_table=False, table_index=None):
    return {
        "anchor": anchor,
        "text": text,
        "page": page,
        "section": section or "",
        "line_start": line_start,
        "line_end": line_end,
        "is_heading": bool(is_heading),
        "in_table": bool(in_table),
        "table_index": table_index,
    }


def _split_sentences(text):
    parts = re.split(r"(?<=[\u3002\uff01\uff1f.!?])\s*", text)
    return [p.strip() for p in parts if p.strip()]


def _chunk_text(text, limit=1200):
    """Split an over-long block on sentence boundaries without dropping text."""
    if len(text) <= limit + 400:
        return [text]
    out, buf = [], ""
    for sent in _split_sentences(text):
        if not sent:
            continue
        if buf and len(buf) + len(sent) > limit:
            out.append(buf.strip())
            buf = ""
        buf += sent
        if len(buf) > limit * 2:
            out.append(buf[:limit * 2])
            buf = buf[limit * 2:]
    if buf.strip():
        out.append(buf.strip())
    return out or [text]


def _text_blocks(lines, start_line=1):
    """Group non-empty lines into blank-line separated blocks with line numbers."""
    blocks, buf, buf_start = [], [], None
    for idx, raw in enumerate(lines, start=start_line):
        line = raw.rstrip("\n")
        stripped = line.strip()
        if not stripped:
            if buf:
                blocks.append(("\n".join(buf).strip(), buf_start, idx - 1))
                buf, buf_start = [], None
            continue
        if buf_start is None:
            buf_start = idx
        buf.append(line)
    if buf:
        blocks.append(("\n".join(buf).strip(), buf_start, len(lines) + start_line - 1))
    return blocks


def _paragraphs_from_text(text, sid, page=1, start_line=1, section="",
                          skip_comments=False, is_heading=False):
    lines = (text or "").splitlines()
    if skip_comments:
        lines = ["" if ln.lstrip().startswith("%") else ln for ln in lines]
    paras = []
    idx = 0
    for block, lstart, lend in _text_blocks(lines, start_line=start_line):
        if not block:
            continue
        for chunk in _chunk_text(block):
            idx += 1
            paras.append(_mk_para("%s#p%d.%d" % (sid, page, idx), chunk,
                                  page=page, section=section,
                                  line_start=lstart, line_end=lend,
                                  is_heading=is_heading))
            if len(paras) >= MAX_PARAGRAPHS_PER_FILE:
                return paras
    return paras


def _markdown_paragraphs(text, sid):
    lines = (text or "").splitlines()
    paras = []
    section = ""
    buf, buf_start = [], None
    idx = 0

    def flush(end_line):
        nonlocal buf, buf_start, idx
        if not buf:
            return
        block = "\n".join(buf).strip()
        if block:
            for chunk in _chunk_text(block):
                idx += 1
                paras.append(_mk_para("%s#p1.%d" % (sid, idx), chunk,
                                      section=section, line_start=buf_start,
                                      line_end=end_line))
        buf, buf_start = [], None

    for lineno, raw in enumerate(lines, start=1):
        line = raw.rstrip("\n")
        heading = re.match(r"^\s{0,3}(#{1,6})\s+(.*\S)\s*$", line)
        if heading:
            flush(lineno - 1)
            section = heading.group(2).strip()
            idx += 1
            paras.append(_mk_para("%s#p1.%d" % (sid, idx), section,
                                  section=section, line_start=lineno,
                                  line_end=lineno, is_heading=True))
            continue
        if not line.strip():
            flush(lineno - 1)
            continue
        if buf_start is None:
            buf_start = lineno
        buf.append(line)
    flush(len(lines))
    return paras


def _docx_paragraphs(path, sid):
    with zipfile.ZipFile(path) as zf:
        names = set(zf.namelist())
        if "word/document.xml" not in names:
            raise ValueError("DOCX has no word/document.xml")
        data = zf.read("word/document.xml")
    try:
        root = ET.fromstring(data)
    except ET.ParseError as exc:
        raise ValueError("DOCX document.xml is not valid XML: %s" % exc)

    paras = []
    section = ""
    table_index = 0
    idx = 0

    def add(text, is_heading=False, in_table=False):
        nonlocal idx
        text = common.norm_ws(text)
        if not text:
            return
        for chunk in _chunk_text(text):
            idx += 1
            paras.append(_mk_para("%s#p1.%d" % (sid, idx), chunk, section=section,
                                  is_heading=is_heading, in_table=in_table,
                                  table_index=table_index if in_table else None))

    def para_text(p):
        return "".join(node.text or "" for node in p.iter(W_NS + "t"))

    def para_style(p):
        node = p.find(W_NS + "pPr/" + W_NS + "pStyle")
        return node.get(W_NS + "val", "") if node is not None else ""

    def walk(el, in_table=False):
        nonlocal section, table_index
        for child in list(el):
            tag = child.tag if isinstance(child.tag, str) else ""
            if tag == W_NS + "p":
                text = para_text(child)
                style = para_style(child)
                heading = bool(re.match(r"(?i)^(heading|title|\u6807\u9898)", style or ""))
                if heading and not in_table:
                    section = common.norm_ws(text)
                add(text, is_heading=heading and not in_table, in_table=in_table)
            elif tag == W_NS + "tbl":
                table_index += 1
                for row in child.findall(W_NS + "tr"):
                    cells = []
                    for cell in row.findall(W_NS + "tc"):
                        cell_text = " ".join(
                            common.norm_ws(para_text(p))
                            for p in cell.findall(W_NS + "p")
                        ).strip()
                        cells.append(cell_text)
                    if any(cells):
                        add(" | ".join(cells), in_table=True)
            else:
                walk(child, in_table=in_table)

    body = root.find(W_NS + "body")
    if body is None:
        raise ValueError("DOCX has no w:body")
    walk(body)
    if not paras:
        raise ValueError("DOCX produced no text")
    return paras, 1


def _pdf_pages(path):
    """Return (pages, tier, errors). pages is a list of page strings or None."""
    errors = []
    pdftotext = shutil.which("pdftotext")
    if pdftotext:
        try:
            proc = subprocess.run(
                [pdftotext, "-layout", "-enc", "UTF-8", path, "-"],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=180,
            )
            if proc.returncode == 0 and proc.stdout.strip():
                text = proc.stdout.decode("utf-8", "replace")
                pages = text.split("\f")
                if pages and not pages[-1].strip():
                    pages.pop()
                if any(p.strip() for p in pages):
                    return pages, "pdftotext", errors
            errors.append("pdftotext produced no text (returncode=%s)" % proc.returncode)
        except Exception as exc:  # noqa: BLE001
            errors.append("pdftotext failed: %s" % str(exc)[:200])
    else:
        errors.append("pdftotext not installed")
    reader = None
    for module in ("pypdf", "PyPDF2"):
        try:
            mod = __import__(module)
            reader = mod.PdfReader(path)
            break
        except Exception as exc:  # noqa: BLE001
            errors.append("%s unavailable: %s" % (module, str(exc)[:120]))
    if reader is not None:
        try:
            pages = []
            for page in reader.pages:
                try:
                    pages.append(page.extract_text() or "")
                except Exception:  # noqa: BLE001
                    pages.append("")
            if any(p.strip() for p in pages):
                return pages, "pypdf", errors
            errors.append("pypdf extracted no text layer")
        except Exception as exc:  # noqa: BLE001
            errors.append("pypdf failed: %s" % str(exc)[:200])
    return None, None, errors


def _pdf_paragraphs(path, sid):
    pages, tier, errors = _pdf_pages(path)
    if pages is None:
        return None, None, ("; ".join(errors[-3:]) or "PDF text extraction failed (scanned PDF?)")
    paras = []
    idx = 0
    for page_no, page_text in enumerate(pages, start=1):
        if not page_text.strip():
            continue
        blocks = _text_blocks(page_text.splitlines())
        for block, _ls, _le in blocks:
            for chunk in _chunk_text(block):
                idx += 1
                paras.append(_mk_para("%s#p%d.%d" % (sid, page_no, idx), chunk,
                                      page=page_no))
                if len(paras) >= MAX_PARAGRAPHS_PER_FILE:
                    return paras, tier, None
    if not paras:
        return None, tier, "PDF has no extractable text layer (scanned PDF?)"
    return paras, tier, None


class _HTMLBlocks(HTMLParser):
    BLOCK = {"p", "div", "section", "article", "br", "li", "tr", "td", "th",
             "table", "ul", "ol", "blockquote", "pre", "h1", "h2", "h3",
             "h4", "h5", "h6"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.blocks = []          # (kind, text)
        self.buf = []
        self.skip = 0
        self.heading_tag = None

    def flush(self):
        text = common.norm_ws(" ".join(self.buf))
        if text:
            self.blocks.append((self.heading_tag or "text", text))
        self.buf = []
        self.heading_tag = None

    def handle_starttag(self, tag, attrs):
        tag = tag.lower()
        if tag in ("script", "style", "noscript"):
            self.skip += 1
            return
        if tag in self.BLOCK:
            self.flush()
            if re.match(r"^h[1-6]$", tag):
                self.heading_tag = tag

    def handle_endtag(self, tag):
        tag = tag.lower()
        if tag in ("script", "style", "noscript"):
            self.skip = max(0, self.skip - 1)
            return
        if tag in self.BLOCK:
            self.flush()

    def handle_data(self, data):
        if not self.skip and data:
            self.buf.append(data)


def _html_paragraphs(path, sid):
    parser = _HTMLBlocks()
    parser.feed(common.read_text(path))
    parser.flush()
    paras, idx, section = [], 0, ""
    for kind, text in parser.blocks:
        if kind.startswith("h"):
            section = text
            idx += 1
            paras.append(_mk_para("%s#p1.%d" % (sid, idx), text, section=section,
                                  is_heading=True))
            continue
        for chunk in _chunk_text(text):
            idx += 1
            paras.append(_mk_para("%s#p1.%d" % (sid, idx), chunk, section=section))
    return paras


def _csv_paragraphs(path, sid):
    raw = common.read_text(path)
    try:
        rows = list(csv.reader(io.StringIO(raw)))
    except csv.Error:
        return _paragraphs_from_text(raw, sid)
    rows = [r for r in rows if any((c or "").strip() for c in r)]
    if not rows:
        return []
    header = [c.strip() for c in rows[0]]
    paras, idx = [], 0
    for row in rows[1:]:
        cells = []
        for i, cell in enumerate(row):
            name = header[i] if i < len(header) and header[i] else "col%d" % (i + 1)
            if (cell or "").strip():
                cells.append("%s=%s" % (name, cell.strip()))
        if not cells:
            continue
        idx += 1
        paras.append(_mk_para("%s#p1.%d" % (sid, idx), "; ".join(cells),
                              section="表格: %s" % os.path.basename(path),
                              in_table=True, table_index=1))
    return paras


def _extract_one(path, sid, rel_path):
    ext = os.path.splitext(path)[1].lower()
    source = {
        "id": sid, "file": os.path.basename(path), "rel_path": rel_path,
        "kind": ext.lstrip("."), "tier": None, "readable": False,
        "page_count": 1, "paragraphs": [], "error": None,
        "chars": 0,
    }
    try:
        if ext == ".pdf":
            paras, tier, error = _pdf_paragraphs(path, sid)
            source["tier"] = tier or "unavailable"
            if paras is None:
                source["error"] = error
                return source
            source["paragraphs"] = paras
            source["page_count"] = max((p["page"] for p in paras), default=1)
        elif ext == ".docx":
            paras, pages = _docx_paragraphs(path, sid)
            source["tier"] = "docx-ooxml"
            source["paragraphs"] = paras
            source["page_count"] = pages
        elif ext in (".md", ".markdown"):
            source["tier"] = "text"
            source["paragraphs"] = _markdown_paragraphs(common.read_text(path), sid)
        elif ext in (".html", ".htm"):
            source["tier"] = "html"
            source["paragraphs"] = _html_paragraphs(path, sid)
        elif ext in (".csv", ".tsv"):
            source["tier"] = "delimited-text"
            source["paragraphs"] = _csv_paragraphs(path, sid)
        elif ext in (".tex", ".latex"):
            source["tier"] = "text"
            source["paragraphs"] = _paragraphs_from_text(
                common.read_text(path), sid, skip_comments=True)
        elif ext == ".json":
            source["tier"] = "text"
            source["paragraphs"] = _paragraphs_from_text(
                common.read_text(path), sid)
        else:
            source["tier"] = "text"
            source["paragraphs"] = _paragraphs_from_text(common.read_text(path), sid)
    except Exception as exc:  # noqa: BLE001
        source["error"] = "%s: %s" % (type(exc).__name__, str(exc)[:300])
        return source
    source["readable"] = bool(source["paragraphs"])
    if not source["readable"]:
        source["error"] = source["error"] or "no extractable text"
    source["chars"] = sum(len(p["text"]) for p in source["paragraphs"])
    return source


def discover(input_dir):
    files, skipped = [], []
    for dirpath, dirnames, filenames in os.walk(input_dir, followlinks=False):
        dirnames[:] = sorted(d for d in dirnames
                             if not d.startswith(".") and d != "__pycache__")
        for name in sorted(filenames):
            if name.startswith("."):
                continue
            full = os.path.join(dirpath, name)
            rel = os.path.relpath(full, input_dir)
            if not os.path.isfile(full) or os.path.islink(full):
                continue
            if name.lower() in SKIP_NAMES:
                skipped.append({"file": rel, "reason": "input metadata"})
                continue
            if os.path.splitext(name)[1].lower() in SKIP_EXTS:
                skipped.append({"file": rel, "reason": "unsupported binary type"})
                continue
            files.append((full, rel))
    return files, skipped


def extract(input_dir):
    case = common.load_json(os.path.join(input_dir, "case.json"), {}) or {}
    case_id = common.case_id_of(case, input_dir)
    files, skipped = discover(input_dir)
    sources, unreadable = [], []
    stats = {"files_seen": len(files), "readable": 0, "unreadable": 0,
             "paragraphs": 0, "chars": 0}
    for index, (full, rel) in enumerate(files, start=1):
        sid = "S%d" % index
        source = _extract_one(full, sid, rel)
        sources.append(source)
        if source["readable"]:
            stats["readable"] += 1
            stats["paragraphs"] += len(source["paragraphs"])
            stats["chars"] += source["chars"]
        else:
            stats["unreadable"] += 1
            unreadable.append({"file": rel, "id": sid,
                               "kind": source["kind"], "error": source["error"]})
    return {
        "case_id": case_id,
        "generator": {"name": common.SKILL_NAME, "version": common.SKILL_VERSION,
                      "script": "extract_sources.py"},
        "anchor_format": common.ANCHOR_HELP,
        "stats": stats,
        "sources": sources,
        "unreadable": unreadable,
        "skipped": skipped,
    }


def main(argv=None):
    ap = argparse.ArgumentParser(description="Extract anchored paragraphs from /input")
    ap.add_argument("--input", default="/input")
    ap.add_argument("--work", default="/app/work")
    ap.add_argument("--out", default=None,
                    help="explicit sources.json path (default: <work>/sources.json)")
    args = ap.parse_args(argv)

    common.ensure_dir(args.work)
    out_path = args.out or os.path.join(args.work, "sources.json")
    try:
        bundle = extract(args.input)
    except Exception as exc:  # noqa: BLE001
        sys.stderr.write("[extract_sources] fatal: %s\n" % str(exc)[:300])
        bundle = {
            "case_id": "unknown", "stats": {"files_seen": 0, "readable": 0,
                                            "unreadable": 0, "paragraphs": 0,
                                            "chars": 0},
            "sources": [], "unreadable": [],
            "skipped": [], "error": str(exc)[:300],
        }
    common.write_json(out_path, bundle)
    stats = bundle.get("stats", {})
    print("sources=%d readable=%d unreadable=%d paragraphs=%d -> %s" % (
        len(bundle.get("sources", [])), stats.get("readable", 0),
        stats.get("unreadable", 0), stats.get("paragraphs", 0), out_path))
    for item in bundle.get("unreadable", []):
        print("UNREADABLE %s (%s)" % (item.get("file"), item.get("error")))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:  # noqa: BLE001
        import traceback
        sys.stderr.write("[extract_sources] unexpected: %s\n" % traceback.format_exc()[-800:])
        sys.exit(0)
