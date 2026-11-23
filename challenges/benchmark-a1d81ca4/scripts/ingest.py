#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ingest.py - read /input/case.json + task.md + material files into locatable units.

Pure Python 3 standard library. Optional external helper: ``pdftotext`` (preinstalled
pdf-text-tool) when present; otherwise a zlib-based text-stream fallback is used.

Nothing is invented: if a file is unreadable it is recorded with readable=false and
an error string, and no text is fabricated.
"""
import csv
import hashlib
import io
import json
import os
import re
import subprocess
import zipfile
import zlib

TEXT_EXT = {".txt", ".md", ".markdown", ".rst", ".csv", ".tsv", ".json", ".tex",
            ".bib", ".yaml", ".yml", ".html", ".htm", ".xml"}
OFFICE_EXT = {".docx", ".xlsx"}
PDF_EXT = {".pdf"}
SKIP_NAMES = {"case.json", "task.md", "task.markdown", "output_contract.json"}
MATERIAL_KEYS = ["materials", "sources", "documents", "corpus", "files",
                 "attachments", "paragraphs", "tables", "text", "paper_text",
                 "input_text", "content"]
MAX_FILE_BYTES = 4 * 1024 * 1024

CJK_RE = re.compile(r"[\u4e00-\u9fff]")
WORD_RE = re.compile(r"[A-Za-z][A-Za-z0-9_\-\u2019']{1,}")
CJK_RUN_RE = re.compile(r"[\u4e00-\u9fff]{2,}")
HEADING_RE = re.compile(
    r"^(?:#{1,6}\s*)?(?:(?:section|sec\.?|chapter)\s*)?(?:\d+(?:\.\d+)*\.?\s+)?"
    r"[A-Z][A-Za-z0-9 ,/&()\-]{2,70}$")
PARA_LABEL_RE = re.compile(
    r"^(?:P|Para|Paragraph|¶|段落)\s*(\d+)\s*[:：.)、]?\s*(.*)$", re.I)
STOP = set("""a an and or of the to in on for with by from as at is are was were be been
being this that these those it its their our we they he she than then which who whom
what when where how not no if only also such may can could should would will using used
use based into within between among about over under more most less least very both each
other others same different respectively reported report data result results study
sample samples value values fig figure table text""".split())


def sha256_bytes(data):
    return hashlib.sha256(data).hexdigest()


def sha256_file(path):
    h = hashlib.sha256()
    try:
        with open(path, "rb") as fh:
            for chunk in iter(lambda: fh.read(65536), b""):
                h.update(chunk)
        return h.hexdigest()
    except OSError:
        return ""


def sha256_text(text):
    return sha256_bytes(text.encode("utf-8", "replace"))


def decode_text(raw):
    for enc in ("utf-8", "utf-8-sig", "gb18030"):
        try:
            return raw.decode(enc)
        except (UnicodeDecodeError, LookupError):
            continue
    return raw.decode("utf-8", "replace")


def cjk_ratio(text):
    if not text:
        return 0.0
    return len(CJK_RE.findall(text)) / float(len(text))


def content_terms(text):
    """Lowercase ASCII content words plus CJK bigrams, for retrieval/matching."""
    text = text or ""
    terms = []
    for w in WORD_RE.findall(text):
        w = w.lower()
        if len(w) >= 2 and w not in STOP:
            terms.append(w)
    for run in CJK_RUN_RE.findall(text):
        if len(run) <= 2:
            terms.append(run)
        else:
            terms.extend(run[i:i + 2] for i in range(len(run) - 1))
    return terms


def norm_ws(text):
    return re.sub(r"\s+", " ", text or "").strip()


def load_json(path):
    with open(path, "r", encoding="utf-8-sig") as fh:
        return json.load(fh)


def find_case_file(input_dir, explicit=None):
    cands = []
    if explicit:
        cands.append(explicit)
    cands += [os.path.join(input_dir, "case.json"), "/input/case.json",
              "/app/input/case.json", "case.json", "input/case.json"]
    seen = set()
    for c in cands:
        if not c:
            continue
        p = os.path.abspath(c)
        if p in seen:
            continue
        seen.add(p)
        if os.path.isfile(p):
            return p
    return None


def load_case(input_dir, explicit=None):
    path = find_case_file(input_dir, explicit)
    if not path:
        return {}, None, "no case.json found under input dir"
    try:
        case = load_json(path)
    except Exception as exc:  # noqa: BLE001
        return {}, path, "case.json unreadable: %s" % exc
    if not isinstance(case, dict):
        return {"raw_case": case}, path, "case.json is not a JSON object"
    return case, path, None


def load_task(input_dir, case=None):
    cands = []
    if isinstance(case, dict):
        for k in ("task_md", "task_text", "task"):
            v = case.get(k)
            if isinstance(v, str) and len(v) > 30:
                cands.append(("case:%s" % k, v))
    for name in ("task.md", "task.markdown", "TASK.md"):
        p = os.path.join(input_dir, name)
        if os.path.isfile(p):
            cands.append((name, decode_text(open(p, "rb").read())))
            break
    for p in ("/input/task.md", "task.md", "/app/input/task.md"):
        if os.path.isfile(p):
            cands.append((p, decode_text(open(p, "rb").read())))
            break
    if cands:
        return cands[0][1], cands[0][0]
    return "", None


# ---------------------------------------------------------------- file readers
def _strip_xml(raw):
    raw = re.sub(r"<w:p[ >]", "\n<w:p ", raw)
    raw = re.sub(r"</w:p>", "\n", raw)
    raw = re.sub(r"<[^>]+>", "", raw)
    raw = raw.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
    return re.sub(r"\n{3,}", "\n\n", raw)


def read_docx(path):
    out = []
    with zipfile.ZipFile(path) as z:
        for name in sorted(n for n in z.namelist() if n.startswith("word/") and n.endswith(".xml")):
            if "document" in name:
                out.append(_strip_xml(z.read(name).decode("utf-8", "replace")))
    return "\n".join(out)


def read_xlsx(path):
    lines = []
    with zipfile.ZipFile(path) as z:
        names = z.namelist()
        shared = []
        if "xl/sharedStrings.xml" in names:
            s = z.read("xl/sharedStrings.xml").decode("utf-8", "replace")
            for si in re.findall(r"<si>(.*?)</si>", s, re.S):
                shared.append(re.sub(r"<[^>]+>", "", si))
        sheets = sorted(n for n in names if re.match(r"xl/worksheets/sheet\d+\.xml$", n))
        for n in sheets:
            x = z.read(n).decode("utf-8", "replace")
            for row in re.findall(r"<row[^>]*>(.*?)</row>", x, re.S):
                cells = []
                for attrs, body in re.findall(r"<c([^>]*)>(.*?)</c>", row, re.S):
                    v = re.search(r"<v>(.*?)</v>", body, re.S)
                    t = re.search(r't="([^"]+)"', attrs)
                    if v is None:
                        cells.append("")
                    elif t and t.group(1) == "s":
                        idx = int(v.group(1))
                        cells.append(shared[idx] if idx < len(shared) else "")
                    else:
                        cells.append(v.group(1))
                if any(c.strip() for c in cells):
                    lines.append("\t".join(cells))
    return "\n".join(lines)


def _pdf_unescape(s):
    return (s.replace("\\n", "\n").replace("\\r", "\r").replace("\\t", "\t")
             .replace("\\(", "(").replace("\\)", ")").replace("\\\\", "\\"))


def read_pdf_fallback(path):
    data = open(path, "rb").read()
    chunks = []
    for m in re.finditer(rb"stream\r?\n(.*?)endstream", data, re.S):
        raw = m.group(1)
        try:
            dec = zlib.decompress(raw)
        except zlib.error:
            continue
        for enc in re.findall(rb"\(((?:\\.|[^\\()])*)\)\s*Tj", dec, re.S):
            chunks.append(_pdf_unescape(enc.decode("latin-1", "replace")))
        for arr in re.findall(rb"\[(.*?)\]\s*TJ", dec, re.S):
            for enc in re.findall(rb"\(((?:\\.|[^\\()])*)\)", arr, re.S):
                chunks.append(_pdf_unescape(enc.decode("latin-1", "replace")))
        chunks.append("\n")
    text = "".join(chunks)
    text = re.sub(r"[ \t]+", " ", text)
    return text.strip()


def read_pdf(path):
    try:
        r = subprocess.run(["pdftotext", "-layout", path, "-"],
                           capture_output=True, timeout=60)
        if r.returncode == 0 and r.stdout.strip():
            return decode_text(r.stdout), "pdftotext"
    except (OSError, subprocess.SubprocessError):
        pass
    try:
        from pypdf import PdfReader  # type: ignore
        text = "\n".join((p.extract_text() or "") for p in PdfReader(path).pages)
        if text.strip():
            return text, "pypdf"
    except Exception:  # noqa: BLE001
        pass
    text = read_pdf_fallback(path)
    return text, "zlib-stream-fallback"


def read_any(path):
    """Return (text, kind, method, error). kind in text/table/pdf/docx/xlsx."""
    ext = os.path.splitext(path)[1].lower()
    try:
        if ext in PDF_EXT:
            text, method = read_pdf(path)
            return text, "text", method, (None if text.strip() else "pdf has no extractable text layer")
        if ext == ".docx":
            return read_docx(path), "text", "zip-xml", None
        if ext == ".xlsx":
            return read_xlsx(path), "table", "zip-xml", None
        raw = open(path, "rb").read(MAX_FILE_BYTES + 1)
        if len(raw) > MAX_FILE_BYTES:
            return "", "text", "raw", "file exceeds %d bytes; truncated read refused" % MAX_FILE_BYTES
        text = decode_text(raw)
        if ext in (".csv", ".tsv"):
            return text, "table", "raw", None
        return text, "text", "raw", None
    except Exception as exc:  # noqa: BLE001
        return "", "text", "raw", "%s: %s" % (type(exc).__name__, exc)


# ---------------------------------------------------------------- unit building
def split_sentences(text):
    """Sentence spans inside a paragraph, keeping offsets."""
    if not text:
        return []
    bounds = []
    for m in re.finditer(r"[.!?。！？]+[\"')\]]*\s+|[。！？]", text):
        end = m.end()
        while end < len(text) and text[end] in "\"'”’)]}":
            end += 1
        bounds.append(end)
    if not bounds or bounds[-1] < len(text):
        bounds.append(len(text))
    out, start = [], 0
    for end in bounds:
        seg = text[start:end]
        if seg.strip():
            lead = len(seg) - len(seg.lstrip())
            out.append({"text": seg.strip(), "start": start + lead, "end": end})
        start = end
    return out


def looks_like_heading(block):
    first = block.strip().splitlines()[0].strip() if block.strip() else ""
    if not first or len(first) > 90:
        return False
    if first.endswith((".", "。", "!", "?", "；", ";")):
        return False
    if first.startswith("|") or first.startswith("- "):
        return False
    return bool(re.match(r"^(#+|[0-9]+(?:\.[0-9]+)*[.)]?\s+\S|[A-Z][A-Za-z ]{1,40}$|Table\s*\d+|图\s*\d+|表\s*\d+)", first))


def parse_markdown_table(lines):
    rows = []
    for line in lines:
        s = line.strip()
        if not (s.startswith("|") and s.endswith("|")):
            continue
        cells = [c.strip() for c in s.strip("|").split("|")]
        if all(re.match(r"^:?-{2,}:?$", c) for c in cells if c):
            continue
        rows.append(cells)
    if len(rows) < 2:
        return None
    width = max(len(r) for r in rows)
    rows = [r + [""] * (width - len(r)) for r in rows]
    return {"columns": rows[0], "rows": rows[1:]}


def parse_csv_text(text):
    sample = text[:4096]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t")
    except csv.Error:
        dialect = csv.excel
    try:
        rows = list(csv.reader(io.StringIO(text), dialect))
    except csv.Error:
        rows = [line.split("\t") for line in text.splitlines()]
    rows = [r for r in rows if any(c.strip() for c in r)]
    if len(rows) < 2:
        return None
    width = max(len(r) for r in rows)
    rows = [r + [""] * (width - len(r)) for r in rows]
    return {"columns": rows[0], "rows": rows[1:]}


class UnitBuilder(object):
    def __init__(self):
        self.units = []
        self.tables = []
        self._unit_n = 0
        self._table_n = 0

    def _locator(self, **kw):
        loc = {"paragraph_index": None, "section": None, "table_id": None,
               "row_index": None, "row_label": None, "columns": None,
               "char_start": 0, "char_end": None}
        loc.update(kw)
        return loc

    def add_para(self, doc, text, section, label=None, kind="paragraph"):
        text = text.strip()
        if len(text) < 20:
            return
        self._unit_n += 1
        pid = label or ("P%d" % self._unit_n)
        self.units.append({
            "unit_id": "%s#%s" % (doc["source_path"], pid),
            "source_path": doc["source_path"],
            "kind": kind,
            "section": section,
            "text": text,
            "chars": len(text),
            "sentences": split_sentences(text),
            "locator": self._locator(paragraph_id=pid, paragraph_index=self._unit_n,
                                     section=section, char_end=len(text)),
        })

    def add_table(self, doc, table, caption, section, source_kind):
        self._table_n += 1
        tid = "T%d" % self._table_n
        meta = {"table_id": tid, "caption": caption or "", "columns": table["columns"],
                "rows": table["rows"], "source_path": doc["source_path"],
                "section": section, "source_kind": source_kind}
        self.tables.append(meta)
        for i, row in enumerate(table["rows"]):
            label = (row[0] or "").strip() or ("row%d" % (i + 1))
            pairs = []
            for c, v in zip(table["columns"], row):
                if v.strip():
                    pairs.append("%s: %s" % (c.strip() or "col", v.strip()))
            text = "%s — %s" % (label, "; ".join(pairs))
            self.units.append({
                "unit_id": "%s#%s:r%d" % (doc["source_path"], tid, i + 1),
                "source_path": doc["source_path"],
                "kind": "table_row",
                "section": section,
                "text": text,
                "chars": len(text),
                "sentences": [{"text": text, "start": 0, "end": len(text)}],
                "table": {"table_id": tid, "caption": caption or "",
                          "columns": [c.strip() for c in table["columns"]],
                          "values": [v.strip() for v in row],
                          "row_label": label, "row_index": i},
                "locator": self._locator(table_id=tid, row_index=i,
                                         row_label=label,
                                         columns=[c.strip() for c in table["columns"]],
                                         section=section, char_end=len(text)),
            })

    def add_text_doc(self, doc, text):
        section = None
        blocks = [b for b in re.split(r"\n\s*\n", text.replace("\r\n", "\n")) if b.strip()]
        if len(blocks) <= 1:
            lines = [ln for ln in text.splitlines() if ln.strip()]
            labeled = [ln for ln in lines if PARA_LABEL_RE.match(ln.strip())]
            if len(labeled) >= max(2, int(0.5 * len(lines))):
                blocks = labeled
            elif lines:
                blocks = []
                buf = []
                for ln in lines:
                    buf.append(ln)
                    if len(" ".join(buf)) >= 450:
                        blocks.append("\n".join(buf))
                        buf = []
                if buf:
                    blocks.append("\n".join(buf))
        i = 0
        while i < len(blocks):
            block = blocks[i].strip()
            lines = [ln for ln in block.splitlines() if ln.strip()]
            if lines and all(ln.strip().startswith("|") for ln in lines) and len(lines) >= 2:
                table = parse_markdown_table(lines)
                if table:
                    self.add_table(doc, table, section or "", section, "markdown")
                i += 1
                continue
            if looks_like_heading(block):
                section = norm_ws(block.lstrip("# ").strip())
                i += 1
                continue
            label = None
            m = PARA_LABEL_RE.match(block)
            if m:
                label = "P%s" % m.group(1)
                block = m.group(2).strip()
            self.add_para(doc, block, section, label=label)
            i += 1

    def add_table_doc(self, doc, text, source_kind):
        if doc.get("table_hint"):
            table = doc["table_hint"]
        else:
            table = parse_csv_text(text)
        if table:
            self.add_table(doc, table, doc.get("title") or "", None, source_kind)


def extract_tables_from_case(case):
    """Inline tables declared in case.json: [{id, columns, rows}]."""
    out = []
    for key in ("tables", "table"):
        val = case.get(key)
        if isinstance(val, dict):
            val = [val]
        if not isinstance(val, list):
            continue
        for i, t in enumerate(val):
            if not isinstance(t, dict):
                continue
            cols = t.get("columns") or t.get("header") or []
            rows = t.get("rows") or t.get("data") or []
            if isinstance(cols, list) and isinstance(rows, list) and cols and rows:
                out.append({"id": str(t.get("id") or t.get("table_id") or ("T%d" % (i + 1))),
                            "caption": str(t.get("caption") or ""),
                            "columns": [str(c) for c in cols],
                            "rows": [[str(c) for c in r] for r in rows if isinstance(r, list)]})
    return out


def ingest(case, input_dir, task_text=""):
    """Build docs + locatable units. Never fabricates text for unreadable files."""
    docs, warnings, seen_sha, seen_path = [], [], {}, set()

    def add_doc(name, text, kind, method, error=None, table_hint=None, title=None):
        text = text or ""
        sha = sha256_text(text)
        if not error and sha in seen_sha:
            return
        if not error:
            seen_sha[sha] = True
        docs.append({"source_path": name, "sha256": sha, "kind": kind,
                     "chars": len(text), "readable": bool(text) and not error,
                     "extraction": method, "error": error or "",
                     "table_hint": table_hint, "title": title or ""})
        return docs[-1]

    # 1) inline materials / declared files
    for key in MATERIAL_KEYS:
        val = case.get(key)
        if val in (None, "", [], {}):
            continue
        items = val if isinstance(val, list) else [val]
        for idx, item in enumerate(items):
            label = "%s[%d]" % (key, idx)
            if isinstance(item, str):
                cand = item if os.path.isabs(item) else os.path.join(input_dir, item)
                if os.path.isfile(cand):
                    seen_path.add(os.path.abspath(cand))
                    text, kind, method, err = read_any(cand)
                    add_doc(os.path.relpath(cand, input_dir) if os.path.abspath(cand).startswith(
                        os.path.abspath(input_dir)) else os.path.basename(cand),
                        text, kind, method, err, title=label)
                elif len(item.strip()) >= 30:
                    add_doc("inline:%s" % label, item, "text", "inline", None, title=label)
                else:
                    warnings.append("material label without content: %s" % label)
                continue
            if isinstance(item, dict):
                title = str(item.get("id") or item.get("name") or item.get("title") or label)
                path = item.get("path") or item.get("file") or item.get("filename")
                if path and not os.path.isabs(path):
                    cand = os.path.join(input_dir, path)
                else:
                    cand = path
                if cand and os.path.isfile(cand):
                    seen_path.add(os.path.abspath(cand))
                    text, kind, method, err = read_any(cand)
                    add_doc(os.path.relpath(cand, input_dir) if os.path.abspath(cand).startswith(
                        os.path.abspath(input_dir)) else os.path.basename(cand),
                        text, kind, method, err, title=title)
                    continue
                text = item.get("text") or item.get("content") or item.get("body") or ""
                paras = item.get("paragraphs")
                if isinstance(paras, list):
                    chunks = []
                    for p in paras:
                        if isinstance(p, dict):
                            chunks.append("%s %s" % (p.get("id") or "", p.get("text") or ""))
                        else:
                            chunks.append(str(p))
                    text = "\n\n".join([text] + chunks).strip()
                if text.strip():
                    add_doc("inline:%s" % title, text, "text", "inline",
                            title=title)
                else:
                    warnings.append("material dict has no text or readable path: %s" % title)
                continue
            if isinstance(item, (list, tuple)):
                text = "\n".join(str(x) for x in item)
                if text.strip():
                    add_doc("inline:%s" % label, text, "text", "inline", title=label)
            else:
                warnings.append("unsupported material entry at %s" % label)

    # 2) scan material files on disk
    if os.path.isdir(input_dir):
        for dirpath, dirnames, filenames in os.walk(input_dir):
            dirnames[:] = sorted(d for d in dirnames if not d.startswith("."))
            for fn in sorted(filenames):
                if fn.startswith("."):
                    continue
                ext = os.path.splitext(fn)[1].lower()
                if fn in SKIP_NAMES:
                    continue
                if ext not in TEXT_EXT | OFFICE_EXT | PDF_EXT:
                    continue
                p = os.path.join(dirpath, fn)
                if os.path.abspath(p) in seen_path:
                    continue
                rel = os.path.relpath(p, input_dir)
                text, kind, method, err = read_any(p)
                add_doc(rel, text, kind, method, err)

    # 3) inline table declarations
    for t in extract_tables_from_case(case):
        add_doc("inline:table:%s" % t["id"], "", "table", "inline", None, table_hint=t)

    # 4) task.md may carry source excerpts when case.json only points to a workorder
    if not docs and task_text and len(task_text) > 400:
        add_doc("task.md", task_text, "text", "task-md", None, title="task.md")

    builder = UnitBuilder()
    for doc in docs:
        if not doc["readable"]:
            continue
        text = ""
        if doc["kind"] == "table" and doc.get("table_hint"):
            builder.add_table(doc, doc["table_hint"], doc["table_hint"].get("caption", ""),
                              None, "inline")
            continue
        # recover text for docs already read
        if doc["source_path"].startswith("inline:"):
            text = _inline_text(case, doc["source_path"])
        elif doc["source_path"] == "task.md":
            text = task_text
        else:
            p = os.path.join(input_dir, doc["source_path"])
            if os.path.isfile(p):
                text, _, _, _ = read_any(p)
        if doc["kind"] == "table" and not doc.get("table_hint"):
            builder.add_table_doc(doc, text, os.path.splitext(doc["source_path"])[1].lstrip("."))
        else:
            builder.add_text_doc(doc, text)

    return {"docs": docs, "units": builder.units, "tables": builder.tables,
            "warnings": warnings}


def _inline_text(case, source_path):
    """Recover inline text for a doc identifier like inline:materials[0]."""
    m = re.match(r"^inline:(\w+)\[(\d+)\]$", source_path)
    if m:
        key, idx = m.group(1), int(m.group(2))
        val = case.get(key)
        if isinstance(val, list) and idx < len(val) and isinstance(val[idx], str):
            return val[idx]
        return ""
    if source_path.startswith("inline:table:"):
        return ""
    title = source_path[len("inline:"):]
    for key in MATERIAL_KEYS:
        val = case.get(key)
        for item in (val if isinstance(val, list) else [val]):
            if isinstance(item, dict):
                if str(item.get("id") or item.get("name") or item.get("title") or "") == title:
                    text = item.get("text") or item.get("content") or item.get("body") or ""
                    paras = item.get("paragraphs")
                    if isinstance(paras, list):
                        chunks = [str(text)] if text else []
                        for p in paras:
                            chunks.append("%s %s" % (p.get("id") or "", p.get("text") or "")
                                          if isinstance(p, dict) else str(p))
                        text = "\n\n".join(chunks)
                    return text
            elif isinstance(item, str) and source_path.startswith("inline:") and len(item) >= 30:
                return item
    return ""

if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", default="/input")
    ap.add_argument("--out", default="")
    a = ap.parse_args()
    case, path, err = load_case(a.input)
    task_text, task_path = load_task(a.input, case)
    res = ingest(case, a.input, task_text)
    res.update({"case_path": path, "case_error": err, "task_path": task_path})
    blob = json.dumps(res, ensure_ascii=False, indent=1)
    if a.out:
        open(a.out, "w", encoding="utf-8").write(blob)
    print(blob[:4000])
