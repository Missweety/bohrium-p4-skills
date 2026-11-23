#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""extract_sources.py - anchored extraction of supplied research materials.

Pure Python standard library (no pip, no network). Supported inputs:
PDF, DOCX, Markdown, TXT, TeX, CSV/TSV, HTML. /input/case.json and
/input/task.md are skipped because they describe the task, not the evidence.

Output (sources.json):
  {"input_root": "...",
   "documents": [{"doc": "doc.1", "path": "...", "bytes": 0, "sha256": "...",
                  "engine": "pdftotext|pdf-stdlib|docx-xml|text|tex|csv|html",
                  "readable": true, "warnings": [], "pages": [...],
                  "paragraphs": [{"anchor": "doc.1 p.1 sec.1 para.1",
                                  "page": 1, "section": 1, "text": "..."}],
                  "text": "full normalized text"}],
   "skipped_files": [{"path": "...", "reason": "..."}],
   "readable_documents": 1, "total_paragraphs": 12}

Anchor scheme: doc.N p.N sec.N para.K  (all 1-based; para.K is per document).

Usage:
  python3 scripts/extract_sources.py --input /input --out /app/work/sources.json
Exit codes: 0 readable material found; 2 nothing readable (honest degradation).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import zipfile
import zlib
from html.parser import HTMLParser

SKIP_BASENAMES = {"case.json", "task.md"}
TEXT_EXTS = {".md", ".markdown", ".txt", ".text"}
DOC_EXTS = {".pdf", ".docx", ".tex", ".csv", ".tsv", ".html", ".htm"}
SUPPORTED = TEXT_EXTS | DOC_EXTS

HEADING_RE = re.compile(
    r"^\s*(?:#{1,6}\s+\S"
    r"|(?:\d+(?:\.\d+){0,3}|[IVXLC]{1,6})\s*[.、:：]?\s+\S"
    r"|第\s*[一二三四五六七八九十百零〇\d]+\s*[章节節部分篇]"
    r"|(?:abstract|introduction|related work|methods?|results?|discussion|"
    r"conclusions?|references?|limitations?|摘要|引言|方法|结果|讨论|结论|"
    r"参考文献|局限|不足)\s*$)", re.I)
REFERENCE_START_RE = re.compile(
    r"^\s*(?:references?|bibliography|参考文献|致谢|acknowledg)", re.I)


# --------------------------------------------------------------------- generic
def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def norm_ws(text):
    text = (text or "").replace("\u3000", " ").replace("\xa0", " ")
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{2,}", "\n\n", text)
    return text.strip()


def one_line(text):
    return re.sub(r"\s+", " ", (text or "")).strip()


def read_text(path):
    for enc in ("utf-8", "utf-8-sig", "gb18030", "big5", "latin-1"):
        try:
            with open(path, encoding=enc) as fh:
                return fh.read()
        except (UnicodeDecodeError, LookupError):
            continue
    with open(path, encoding="utf-8", errors="replace") as fh:
        return fh.read()


def split_blocks(text):
    """Split into paragraph-like blocks on blank lines."""
    blocks = []
    for part in re.split(r"\n\s*\n", text or ""):
        part = part.strip()
        if len(part) >= 2:
            blocks.append(part)
    return blocks


def chunk_long_block(block, limit=1100):
    """PDF pages often have no blank lines; keep quote-sized blocks."""
    if len(block) <= limit:
        return [block]
    lines = block.split("\n")
    out, cur, size = [], [], 0
    for line in lines:
        cur.append(line)
        size += len(line) + 1
        if size >= limit * 0.7 and not HEADING_RE.match(line):
            out.append("\n".join(cur).strip())
            cur, size = [], 0
    if cur:
        out.append("\n".join(cur).strip())
    return [b for b in out if len(b) >= 2]


# ------------------------------------------------------------------------ html
class _TextHTML(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []
        self.skip = 0
        self.block_tags = {"p", "div", "br", "li", "tr", "h1", "h2", "h3",
                           "h4", "h5", "h6", "section", "article", "table"}

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style", "noscript"):
            self.skip += 1
        elif tag in self.block_tags:
            self.parts.append("\n\n")

    def handle_endtag(self, tag):
        if tag in ("script", "style", "noscript") and self.skip:
            self.skip -= 1
        elif tag in self.block_tags:
            self.parts.append("\n\n")

    def handle_data(self, data):
        if not self.skip and data.strip():
            self.parts.append(data.strip() + " ")

    def text(self):
        raw = "".join(self.parts)
        raw = re.sub(r"[ \t]+", " ", raw)
        return re.sub(r"\n{3,}", "\n\n", raw).strip()


def html_to_text(path):
    parser = _TextHTML()
    parser.feed(read_text(path))
    parser.close()
    return parser.text()


# ------------------------------------------------------------------------- tex
def tex_to_text(path):
    raw = read_text(path)
    raw = re.sub(r"(?<!\\)%.*", "", raw)
    raw = re.sub(r"\\begin\{(figure|table|equation)\*?\}.*?\\end\{\1\*?\}", " ", raw, flags=re.S)
    raw = re.sub(r"\\(?:sub)*section\*?\{([^}]*)\}", r"\n\n\1\n\n", raw)
    raw = re.sub(r"\\(?:title|author|date)\{([^}]*)\}", r"\n\n\1\n\n", raw)
    raw = re.sub(r"\\(?:cite|ref|label|url|includegraphics|footnote)\{[^}]*\}", " ", raw)
    raw = re.sub(r"\\[a-zA-Z]+\*?(\[[^\]]*\])?(\{[^}]*\})?", " ", raw)
    raw = raw.replace("{", " ").replace("}", " ").replace("~", " ")
    raw = re.sub(r"[ \t]+", " ", raw)
    return raw.strip()


# ------------------------------------------------------------------------ docx
def docx_to_text(path):
    with zipfile.ZipFile(path) as zf:
        xml = zf.read("word/document.xml").decode("utf-8", "replace")
    xml = re.sub(r"<w:tab[^>]*/>", "\t", xml)
    xml = re.sub(r"</w:p>", "\n\n", xml)
    xml = re.sub(r"<w:br[^>]*/>", "\n", xml)
    text = re.sub(r"<[^>]+>", "", xml)
    text = (text.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
            .replace("&quot;", '"').replace("&apos;", "'"))
    return text


# ------------------------------------------------------------------------- csv
def csv_to_text(path):
    import csv
    delim = "\t" if path.lower().endswith(".tsv") else None
    rows = []
    with open(path, encoding="utf-8-sig", errors="replace", newline="") as fh:
        if delim:
            reader = csv.reader(fh, delimiter=delim)
        else:
            sample = fh.read(4096)
            fh.seek(0)
            try:
                dialect = csv.Sniffer().sniff(sample, delimiters=",;\t|")
            except Exception:  # noqa: BLE001
                dialect = csv.excel
            reader = csv.reader(fh, dialect)
        for row in reader:
            cells = [c.strip() for c in row if c.strip()]
            if cells:
                rows.append(" | ".join(cells))
    return "\n\n".join(rows)


# --------------------------------------------------------------------- PDF core
# Tier 1: pdftotext (poppler, preinstalled in the eval image).
# Tier 2: compact stdlib parser (objects, ObjStm, Flate, ToUnicode, Tj/TJ).
# Tier 3: unreadable -> reported honestly, never guessed.
class _PdfError(Exception):
    pass


_PDF_WS = b"\x00\t\n\x0c\r "
_PDF_DELIM = b"()<>[]{}/%"


def _pdf_objects(data):
    objs = {}
    for m in re.finditer(rb"(?<![0-9])(\d+)\s+(\d+)\s+obj\b", data):
        end = data.find(b"endobj", m.end())
        objs[int(m.group(1))] = data[m.end():end if end >= 0 else len(data)]
    return objs


def _pdf_stream(body):
    m = re.search(rb"stream\r?\n", body)
    if not m:
        return None
    end = body.find(b"endstream", m.end())
    if end < 0:
        return None
    return body[m.end():end].rstrip(b"\r\n")


def _pdf_inflate(raw, head, warnings):
    if b"/FlateDecode" in head:
        try:
            return zlib.decompress(raw)
        except zlib.error:
            try:
                return zlib.decompressobj().decompress(raw)
            except Exception:  # noqa: BLE001
                warnings.append("flate_decode_failed")
                return b""
    if b"/Filter" in head:
        for f in re.findall(rb"/(\w+)Decode", head):
            warnings.append("unsupported_filter:%s" % f.decode("latin-1"))
        return b""
    return raw


def _pdf_objstm(objs, warnings):
    extra = {}
    for num, body in list(objs.items()):
        head = body[:body.find(b"stream")] if b"stream" in body else body
        if b"/ObjStm" not in head:
            continue
        try:
            n = int(re.search(rb"/N\s+(\d+)", head).group(1))
            first = int(re.search(rb"/First\s+(\d+)", head).group(1))
            raw = _pdf_stream(body)
            if raw is None:
                continue
            data = _pdf_inflate(raw, head, warnings)
            nums = [int(x) for x in data[:first].split()]
            pairs = [(nums[k], nums[k + 1]) for k in range(0, min(len(nums), 2 * n), 2)]
            for idx, (k, off) in enumerate(pairs):
                start = first + off
                end = first + pairs[idx + 1][1] if idx + 1 < len(pairs) else len(data)
                extra[k] = data[start:end]
        except Exception:  # noqa: BLE001
            warnings.append("objstm_parse_failed")
    for k, v in extra.items():
        objs.setdefault(k, v)
    return objs


def _pdf_dict(body):
    if not body:
        return {}
    i = body.find(b"<<")
    if i < 0:
        return {}
    depth, j = 0, i
    while j < len(body):
        if body[j:j + 2] == b"<<":
            depth += 1
            j += 2
        elif body[j:j + 2] == b">>":
            depth -= 1
            if depth == 0:
                j += 2
                break
            j += 2
        else:
            j += 1
    inner = body[i + 2:max(i + 2, j - 2)]
    out, depth, k = {}, 0, 0
    while k < len(inner):
        if inner[k:k + 2] == b"<<":
            depth += 1
            k += 2
        elif inner[k:k + 2] == b">>":
            depth -= 1
            k += 2
        elif inner[k] == 0x2F and depth == 0:
            m = re.match(rb"/([^\s/<>\[\]]+)", inner[k:])
            if not m:
                k += 1
                continue
            key = m.group(1).decode("latin-1")
            k += m.end()
            while k < len(inner) and inner[k] in _PDF_WS:
                k += 1
            if inner[k:k + 2] == b"<<":
                d2, s2, k = 1, k + 2, k + 2
                while k < len(inner) and d2:
                    if inner[k:k + 2] == b"<<":
                        d2 += 1
                        k += 2
                    elif inner[k:k + 2] == b">>":
                        d2 -= 1
                        k += 2
                    else:
                        k += 1
                out[key] = b"<<" + inner[s2:k - 2] + b">>"
            elif inner[k:k + 1] == b"[":
                d2, s2, k = 1, k + 1, k + 1
                while k < len(inner) and d2:
                    if inner[k:k + 1] == b"[":
                        d2 += 1
                        k += 1
                    elif inner[k:k + 1] == b"]":
                        d2 -= 1
                        k += 1
                    else:
                        k += 1
                out[key] = inner[s2:k - 1]
            else:
                m2 = re.match(rb"(\d+\s+\d+\s+R|/[^\s/<>\[\]]+|[^\s/<>\[\]]+)", inner[k:])
                if m2:
                    out[key] = m2.group(1)
                    k += m2.end()
                else:
                    k += 1
        else:
            k += 1
    return out


def _pdf_deref(objs, value):
    if value is None:
        return None
    m = re.match(rb"(\d+)\s+\d+\s+R", value.strip())
    if m:
        return objs.get(int(m.group(1)), b"")
    return value


def _pdf_utf16(hexstr):
    try:
        return bytes.fromhex(hexstr).decode("utf-16-be", "replace")
    except Exception:  # noqa: BLE001
        return ""


def _pdf_cmap(data, warnings):
    text = data.decode("latin-1", "replace")
    mapping, maxlen = {}, 1
    for m in re.finditer(r"beginbfchar(.*?)endbfchar", text, re.S):
        for src, dst in re.findall(r"<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>", m.group(1)):
            maxlen = max(maxlen, len(src))
            mapping[int(src, 16)] = _pdf_utf16(dst)
    for m in re.finditer(r"beginbfrange(.*?)endbfrange", text, re.S):
        for lo, hi, rest in re.findall(
                r"<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>\s*(<[0-9A-Fa-f]+>|\[[^\]]*\])", m.group(1)):
            lo_i, hi_i = int(lo, 16), int(hi, 16)
            maxlen = max(maxlen, len(lo))
            if rest.startswith("["):
                for k, item in enumerate(re.findall(r"<([0-9A-Fa-f]+)>", rest)):
                    if lo_i + k <= hi_i:
                        mapping[lo_i + k] = _pdf_utf16(item)
            else:
                base = int(rest.strip("<>"), 16)
                for k in range(hi_i - lo_i + 1):
                    mapping[lo_i + k] = _pdf_utf16("%04X" % (base + k))
    if not mapping:
        warnings.append("pdf_toUnicode_missing")
    return (2 if maxlen > 2 else 1), mapping


def _pdf_page_nums(objs):
    pages, root = [], None
    for num, body in objs.items():
        if re.search(rb"/Type\s*/Catalog", body[:800]):
            root = num
            break
    if root is not None:
        queue = [_pdf_dict(objs[root]).get("Pages")]
        seen = set()
        while queue:
            val = queue.pop(0)
            m = re.match(rb"(\d+)\s+\d+\s+R", (val or b"").strip())
            if not m:
                continue
            num = int(m.group(1))
            if num in seen:
                continue
            seen.add(num)
            body = objs.get(num, b"")
            if re.search(rb"/Type\s*/Page\b", body[:600]):
                pages.append(num)
            else:
                kids = _pdf_dict(body).get("Kids") or b""
                queue.extend(m.group(0) for m in re.finditer(rb"(\d+)\s+\d+\s+R", kids))
    if not pages:
        for num, body in objs.items():
            if re.search(rb"/Type\s*/Page\b", body[:600]):
                pages.append(num)
        pages.sort()
    return pages


def _pdf_lex(content):
    """Yield ('s', bytes) for literal/hex strings and ('o', op) tokens."""
    i, n = 0, len(content)
    while i < n:
        c = content[i]
        if c in _PDF_WS:
            i += 1
            continue
        if c == 0x25:  # comment
            j = content.find(b"\n", i)
            i = n if j < 0 else j + 1
            continue
        if c == 0x28:  # literal string
            i += 1
            depth, buf = 1, bytearray()
            esc = {0x6E: 10, 0x72: 13, 0x74: 9, 0x62: 8, 0x66: 12,
                   0x28: 40, 0x29: 41, 0x5C: 92}
            while i < n:
                ch = content[i]
                if ch == 0x5C:
                    i += 1
                    if i >= n:
                        break
                    e = content[i]
                    if e in esc:
                        buf.append(esc[e])
                        i += 1
                    elif 0x30 <= e <= 0x37:
                        octd = bytearray()
                        for _ in range(3):
                            if i < n and 0x30 <= content[i] <= 0x37:
                                octd.append(content[i])
                                i += 1
                        buf.append(int(octd, 8) & 0xFF if octd else 0)
                    elif e in (10, 13):
                        i += 1
                        if e == 13 and i < n and content[i] == 10:
                            i += 1
                    else:
                        buf.append(e)
                        i += 1
                elif ch == 0x28:
                    depth += 1
                    buf.append(ch)
                    i += 1
                elif ch == 0x29:
                    depth -= 1
                    if depth == 0:
                        i += 1
                        break
                    buf.append(ch)
                    i += 1
                else:
                    buf.append(ch)
                    i += 1
            yield ("s", bytes(buf))
            continue
        if c == 0x3C and content[i:i + 2] != b"<<":
            j = content.find(b">", i + 1)
            if j < 0:
                j = n
            raw = re.sub(rb"[^0-9A-Fa-f]", b"", content[i + 1:j])
            if len(raw) % 2:
                raw += b"0"
            try:
                yield ("s", bytes.fromhex(raw.decode("ascii")))
            except ValueError:
                pass
            i = j + 1
            continue
        if c == 0x2F:  # name
            j = i + 1
            while j < n and content[j] not in _PDF_WS and content[j] not in _PDF_DELIM:
                j += 1
            yield ("n", content[i + 1:j])
            i = j
            continue
        if c in b"[]":
            yield ("br", bytes([c]))
            i += 1
            continue
        if c in b"<>":
            i += 2  # << or >> dictionary marker
            continue
        j = i
        while j < n and content[j] not in _PDF_WS and content[j] not in _PDF_DELIM:
            j += 1
        if j == i:
            i += 1
            continue
        tok = content[i:j]
        i = j
        try:
            float(tok)
            yield ("num", tok)
        except ValueError:
            yield ("o", tok)


def _pdf_decode(raw, code_len, mapping):
    if code_len == 2:
        return "".join(mapping.get((raw[k] << 8) | raw[k + 1], "")
                       for k in range(0, len(raw) - 1, 2))
    return "".join(mapping.get(b, "") for b in raw)


def _pdf_font_maps(objs, page_body, warnings):
    fonts = {}
    latin1 = {b: bytes([b]).decode("latin-1") for b in range(256)}
    rd = _pdf_dict(_pdf_deref(objs, _pdf_dict(page_body).get("Resources")) or b"")
    fd = _pdf_dict(_pdf_deref(objs, rd.get("Font")) or b"")
    for name, val in fd.items():
        fbody = _pdf_deref(objs, val) or b""
        fdict = _pdf_dict(fbody)
        cmap_ref = _pdf_deref(objs, fdict.get("ToUnicode"))
        if not cmap_ref:
            fonts[name] = (1, latin1)
            continue
        head = cmap_ref[:cmap_ref.find(b"stream")] if b"stream" in cmap_ref else cmap_ref
        raw = _pdf_stream(cmap_ref)
        if raw is None:
            fonts[name] = (1, latin1)
            continue
        code_len, mapping = _pdf_cmap(_pdf_inflate(raw, head, warnings), warnings)
        fonts[name] = (code_len, mapping) if mapping else (1, latin1)
    return fonts


def _pdf_page_content(objs, page_body, warnings):
    out = []
    for m in re.finditer(rb"(\d+)\s+\d+\s+R", _pdf_dict(page_body).get("Contents") or b""):
        body = objs.get(int(m.group(1)), b"")
        head = body[:body.find(b"stream")] if b"stream" in body else body
        raw = _pdf_stream(body)
        if raw is not None:
            out.append(_pdf_inflate(raw, head, warnings))
    return b"\n".join(out)


def _pdf_extract_page(content, fonts, warnings):
    pieces, cur_font = [], None
    operands = []
    for kind, val in _pdf_lex(content):
        if kind == "br":
            continue
        if kind in ("s", "n", "num"):
            operands.append((kind, val))
            continue
        op = val.decode("latin-1", "replace")
        if op == "Tf":
            names = [v for k, v in operands if k == "n"]
            if names:
                cur_font = fonts.get(names[-1].decode("latin-1"))
        elif op in ("Tj", "'", '"'):
            raw = b"".join(v for k, v in operands if k == "s")
            pieces.append(_pdf_decode(raw, *(cur_font or (1, {}))))
            if op in ("'", '"'):
                pieces.append("\n")
        elif op == "TJ":
            buf = []
            for k, v in operands:
                if k == "s":
                    buf.append(v)
                elif k == "num":
                    try:
                        if float(v) < -120 and buf:
                            buf.append(b" ")
                    except ValueError:
                        pass
            if buf:
                pieces.append(_pdf_decode(b"".join(buf), *(cur_font or (1, {}))))
        elif op in ("T*", "Td", "TD"):
            pieces.append("\n")
        elif op in ("ET", "BT"):
            pieces.append("\n")
        operands = []
    if not pieces:
        return ""
    text = "".join(pieces)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _pdf_stdlib(path, max_pages, warnings):
    with open(path, "rb") as fh:
        data = fh.read()
    if re.search(rb"/Encrypt\s+\d+\s+\d+\s+R", data[:300000]):
        warnings.append("encrypted_pdf")
        return []
    objs = _pdf_objstm(_pdf_objects(data), warnings)
    if not objs:
        raise _PdfError("no indirect objects")
    page_nums = _pdf_page_nums(objs)
    if not page_nums:
        raise _PdfError("no page objects")
    pages = []
    for pnum in page_nums[:max_pages]:
        body = objs.get(pnum, b"")
        content = _pdf_page_content(objs, body, warnings)
        pages.append(_pdf_extract_page(content, _pdf_font_maps(objs, body, warnings), warnings))
    if len(page_nums) > max_pages:
        warnings.append("truncated_to_%d_pages" % max_pages)
    return pages


def pdf_pages(path, max_pages, warnings):
    if shutil.which("pdftotext"):
        try:
            proc = subprocess.run(
                ["pdftotext", "-layout", "-f", "1", "-l", str(max_pages), path, "-"],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=180)
            if proc.returncode == 0 and proc.stdout.strip():
                pages = proc.stdout.decode("utf-8", "replace").split("\f")
                while pages and not pages[-1].strip():
                    pages.pop()
                return pages, "pdftotext"
            warnings.append("pdftotext_empty")
        except Exception as exc:  # noqa: BLE001
            warnings.append("pdftotext_error:%s" % str(exc)[:80])
    try:
        pages = _pdf_stdlib(path, max_pages, warnings)
        if pages and any(p.strip() for p in pages):
            warnings.append("used_stdlib_pdf_fallback")
            return pages, "pdf-stdlib"
    except Exception as exc:  # noqa: BLE001
        warnings.append("stdlib_pdf_error:%s" % str(exc)[:120])
    return [], "unreadable"


# ---------------------------------------------------------------- anchoring
def _section_of(block, sec_no):
    if HEADING_RE.match(block):
        return sec_no + 1, True
    return max(sec_no, 1), False


def extract_file(path, doc_no, input_root, max_pages):
    ext = os.path.splitext(path)[1].lower()
    rec = {
        "doc": "doc.%d" % doc_no,
        "path": os.path.relpath(path, input_root).replace(os.sep, "/"),
        "bytes": os.path.getsize(path),
        "sha256": sha256_file(path),
        "engine": "skip",
        "readable": False,
        "warnings": [],
        "pages": [],
        "paragraphs": [],
        "text": "",
    }
    try:
        if ext == ".pdf":
            pages, engine = pdf_pages(path, max_pages, rec["warnings"])
        elif ext == ".docx":
            engine = "docx-xml"
            pages = [docx_to_text(path)]
        elif ext == ".tex":
            engine = "tex"
            pages = [tex_to_text(path)]
        elif ext in (".csv", ".tsv"):
            engine = "csv"
            pages = [csv_to_text(path)]
        elif ext in (".html", ".htm"):
            engine = "html"
            pages = [html_to_text(path)]
        else:
            engine = "text"
            pages = [read_text(path)]
    except Exception as exc:  # noqa: BLE001
        rec["engine"] = "error"
        rec["warnings"].append("read_error:%s" % str(exc)[:160])
        return rec

    rec["engine"] = engine
    if not pages or not any(p and p.strip() for p in pages):
        rec["warnings"].append("no_text_extracted")
        return rec

    sec_no = 0
    para_no = 0
    for page_no, page in enumerate(pages, 1):
        if not page or not page.strip():
            rec["pages"].append({"page": page_no, "chars": 0})
            continue
        page = norm_ws(page)
        blocks = []
        for block in split_blocks(page):
            blocks.extend(chunk_long_block(block))
        for block in blocks:
            block = block.strip()
            if len(block) < 2:
                continue
            sec_no, is_head = _section_of(block, sec_no)
            para_no += 1
            rec["paragraphs"].append({
                "anchor": "%s p.%d sec.%d para.%d" % (rec["doc"], page_no, sec_no, para_no),
                "page": page_no,
                "section": sec_no,
                "heading": bool(is_head),
                "text": block[:8000],
            })
        rec["pages"].append({"page": page_no, "chars": len(page)})

    rec["text"] = norm_ws("\n".join(pages))[:1000000]
    rec["readable"] = bool(rec["paragraphs"])
    return rec


def main(argv=None):
    ap = argparse.ArgumentParser(description="Extract anchored source text")
    ap.add_argument("--input", default="/input")
    ap.add_argument("--out", default="/app/work/sources.json")
    ap.add_argument("--max-pages", type=int, default=80)
    args = ap.parse_args(argv)

    documents, skipped = [], []
    for root, dirs, files in os.walk(args.input):
        dirs[:] = sorted(d for d in dirs if not d.startswith(".") and d != "__pycache__")
        for name in sorted(files):
            path = os.path.join(root, name)
            rel = os.path.relpath(path, args.input).replace(os.sep, "/")
            if os.path.islink(path):
                skipped.append({"path": rel, "reason": "symlink_skipped"})
                continue
            if name.startswith("."):
                skipped.append({"path": rel, "reason": "hidden_file"})
                continue
            if name in SKIP_BASENAMES:
                skipped.append({"path": rel, "reason": "task_metadata_not_evidence"})
                continue
            if os.path.splitext(name)[1].lower() not in SUPPORTED:
                skipped.append({"path": rel, "reason": "unsupported_extension"})
                continue
            documents.append(extract_file(path, len(documents) + 1, args.input, args.max_pages))

    payload = {
        "input_root": os.path.abspath(args.input),
        "documents": documents,
        "skipped_files": skipped,
        "readable_documents": sum(1 for d in documents if d["readable"]),
        "total_paragraphs": sum(len(d["paragraphs"]) for d in documents),
        "anchor_scheme": "doc.N p.N sec.N para.K (1-based; para.K per document)",
    }
    out_dir = os.path.dirname(os.path.abspath(args.out))
    os.makedirs(out_dir, exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=1)
    print(json.dumps({
        "documents": len(documents),
        "readable": payload["readable_documents"],
        "paragraphs": payload["total_paragraphs"],
        "skipped": len(skipped),
        "out": args.out,
    }, ensure_ascii=False))
    return 0 if payload["readable_documents"] else 2


if __name__ == "__main__":
    sys.exit(main())
