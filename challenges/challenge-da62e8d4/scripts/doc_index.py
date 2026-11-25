#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""doc_index.py - turn supplied paper materials into addressable paragraphs.

Stdlib only, no network. Every paragraph gets a stable paragraph_id so that each
extracted field can point back to the exact sentence it came from:

  JATS XML      -> the real <p id="..."> attribute (organizer paragraph id)
  PDF           -> p.<page>¶<k>   (1-based PDF page, k-th paragraph on that page)
  MD / TXT / TeX-> ¶<k>          (document order, 1-based)

Unreadable inputs are reported as unreadable with a reason; nothing is guessed.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import zipfile

TEXT_EXT = (".md", ".txt", ".rst", ".tex", ".csv", ".tsv")
SKIP = {"case.json", "task.md", "target-fields.json", "readme.md", "challenge.json"}


def norm(text):
    return re.sub(r"\s+", " ", (text or "")).strip()


def _pdftotext(path, max_pages=40):
    """Return {page: text} via poppler, or (None, reason)."""
    exe = None
    for cand in ("pdftotext",):
        from shutil import which
        exe = which(cand)
    if not exe:
        return None, "pdftotext not installed; PDF left unread (content not guessed)"
    try:
        proc = subprocess.run([exe, "-layout", "-f", "1", "-l", str(max_pages), path, "-"],
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=120)
    except Exception as exc:  # noqa: BLE001
        return None, "pdftotext failed: %s" % exc
    text = proc.stdout.decode("utf-8", "replace")
    if proc.returncode != 0 or not text.strip():
        return None, "pdftotext returned no text layer (scanned or protected)"
    pages = text.split("\f")
    if pages and not pages[-1].strip():
        pages.pop()
    return pages, None


def _docx_text(path):
    with zipfile.ZipFile(path) as zf:
        xml = zf.read("word/document.xml").decode("utf-8", "replace")
    out = []
    for para in re.findall(r"<w:p[ >].*?</w:p>", xml, re.S):
        txt = "".join(re.findall(r"<w:t[^>]*>(.*?)</w:t>", para, re.S))
        txt = (txt.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
               .replace("&quot;", '"').replace("&apos;", "'"))
        if txt.strip():
            out.append(txt.strip())
    return "\n\n".join(out)


def _jats_paragraphs(path):
    """Parse JATS-like XML; keep real paragraph ids and section titles."""
    import xml.etree.ElementTree as ET
    root = ET.parse(path).getroot()
    title_by_sec = {}
    paras = []

    def local(tag):
        return tag.split("}")[-1] if isinstance(tag, str) else ""

    for sec in root.iter():
        if local(sec.tag) != "sec":
            continue
        sid = sec.get("id") or ""
        title = ""
        for child in sec:
            if local(child.tag) == "title":
                title = norm("".join(child.itertext()))
                break
        if sid:
            title_by_sec[sid] = title
    for node in root.iter():
        if local(node.tag) != "p":
            continue
        text = norm("".join(node.itertext()))
        if len(text) < 20:
            continue
        pid = node.get("id")
        paras.append({"pid": pid, "text": text, "section": ""})
    # attach the nearest section title via ancestor walk
    parents = {c: p for p in root.iter() for c in p}
    for rec, node in zip(paras, [n for n in root.iter() if local(n.tag) == "p"]):
        cur = parents.get(node)
        while cur is not None:
            if local(cur.tag) == "sec" and cur.get("id") in title_by_sec:
                rec["section"] = title_by_sec[cur.get("id")]
                break
            cur = parents.get(cur)
    for i, rec in enumerate(paras, 1):
        rec["pid"] = rec["pid"] or "p.%d" % i
    return paras, None


def _raw_blocks(text):
    return [b for b in re.split(r"\n\s*\n", text or "") if b.strip()]


def _text_paragraphs(text):
    blocks = _raw_blocks(text)
    out = []
    for b in blocks:
        s = norm(b)
        if len(s) >= 20:
            out.append(s)
    return out


def build_doc(input_dir, max_pages=40):
    """Index every supplied material. Returns doc dict + list of material records."""
    materials, paragraphs, tables = [], [], []
    base = os.path.abspath(input_dir)
    files = []
    for dirpath, dirnames, names in os.walk(base):
        dirnames[:] = sorted(d for d in dirnames if not d.startswith("."))
        for name in sorted(names):
            if name.startswith(".") or name.lower() in SKIP:
                continue
            files.append(os.path.join(dirpath, name))

    counter = 0
    table_counter = 0
    for path in files:
        rel = os.path.relpath(path, base).replace(os.sep, "/")
        ext = os.path.splitext(path)[1].lower()
        rec = {"path": rel, "bytes": os.path.getsize(path), "readable": True, "note": None,
               "kind": ext.lstrip(".") or "unknown"}
        try:
            if ext == ".pdf":
                pages, err = _pdftotext(path, max_pages)
                if pages is None:
                    rec.update(readable=False, note=err)
                else:
                    for pno, ptext in enumerate(pages, 1):
                        for k, para in enumerate(_text_paragraphs(ptext), 1):
                            counter += 1
                            paragraphs.append({"paragraph_id": "p.%d¶%d" % (pno, k),
                                               "text": para, "source_file": rel,
                                               "page": pno, "section": ""})
            elif ext == ".xml":
                try:
                    paras, err = _jats_paragraphs(path)
                except Exception as exc:  # noqa: BLE001
                    paras, err = [], "XML parse failed: %s" % exc
                if err:
                    rec.update(readable=False, note=err)
                for p in paras:
                    counter += 1
                    paragraphs.append({"paragraph_id": p["pid"], "text": p["text"],
                                       "source_file": rel, "page": None,
                                       "section": p["section"]})
            elif ext == ".docx":
                text = _docx_text(path)
                for k, para in enumerate(_text_paragraphs(text), 1):
                    counter += 1
                    paragraphs.append({"paragraph_id": "¶%d" % k, "text": para,
                                       "source_file": rel, "page": None, "section": ""})
            elif ext in TEXT_EXT:
                with open(path, encoding="utf-8", errors="replace") as fh:
                    text = fh.read()
                k = 0
                for raw in _raw_blocks(text):
                    para = norm(raw)
                    if len(para) < 20:
                        continue
                    k += 1
                    counter += 1
                    paragraphs.append({"paragraph_id": "¶%d" % k, "text": para,
                                       "source_file": rel, "page": None, "section": ""})
                    block_rows = _markdown_table_rows(raw, rel, k)
                    if block_rows:
                        table_counter += 1
                        tid = "tab.%d" % table_counter
                        for row in block_rows:
                            row["table_id"] = tid
                            row["anchor"] = "%s/%s/row.%d" % (rel, tid, row["row"])
                            row.pop("_table_no", None)
                            tables.append(row)
            else:
                rec.update(readable=False, note="unsupported type %s (not parsed)" % ext)
        except Exception as exc:  # noqa: BLE001
            rec.update(readable=False, note="read failed: %s" % exc)
        materials.append(rec)

    doc = {
        "meta": {
            "input_dir": base,
            "materials": materials,
            "readable": sum(1 for m in materials if m["readable"]),
            "unreadable": [m["path"] for m in materials if not m["readable"]],
            "paragraphs": len(paragraphs),
        },
        "paragraphs": paragraphs,
        "tables": tables,
        "text": "\n".join(p["text"] for p in paragraphs),
    }
    return doc


def _markdown_table_rows(para, rel, para_no):
    rows = []
    lines = [ln.strip() for ln in para.splitlines() if ln.strip().startswith("|")]
    if len(lines) < 2:
        return rows
    table_no = 0
    for k, line in enumerate(lines, 1):
        cells = [c.strip() for c in line.strip("|").split("|")]
        if all(set(c) <= set("-: ") for c in cells):
            continue
        rows.append({"row": k, "cells": cells,
                     "source_file": rel, "paragraph_id": "¶%d" % para_no,
                     "_table_no": table_no})
    return rows


def main(argv=None):
    import argparse
    ap = argparse.ArgumentParser(description="index paper materials into paragraphs")
    ap.add_argument("--input", default="/input")
    ap.add_argument("--out", default="work/doc.json")
    a = ap.parse_args(argv)
    doc = build_doc(a.input)
    os.makedirs(os.path.dirname(os.path.abspath(a.out)) or ".", exist_ok=True)
    with open(a.out, "w", encoding="utf-8") as fh:
        json.dump(doc, fh, ensure_ascii=False, indent=1)
    print("materials=%d readable=%d paragraphs=%d -> %s" % (
        len(doc["meta"]["materials"]), doc["meta"]["readable"],
        len(doc["paragraphs"]), a.out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
