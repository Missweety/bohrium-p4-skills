#!/usr/bin/env python3
"""doc_structure.py - page/block locator map + section tree for layout-extracted text.

Flags repeated page-edge lines as furniture *per file* (a header that repeats on every page of a
3-page paper must be caught even when other files are indexed together), classifies lines
(heading/caption/equation/footnote/reference/body/unreadable), merges adjacent body lines into
blocks carrying per-document page + block_id, and builds a multi-level section tree.

Page numbers restart per source file (`page`) and keep a global reading order (`page_global`), so
`page` stays a real pointer into the original PDF/DOCX. Text is classified, never rewritten, so
undecidable lines stay `body` for review.
"""
import argparse
import csv
import json
import os
import re
import sys
from collections import Counter

HEAD_MD = re.compile(r"^(#{1,6})\s+(\S.*)$")
HEAD_NUM = re.compile(r"^(\d{1,2}(?:\.\d{1,2}){0,3})\.?\s+([A-Z\u00c0-\u024f][^.;:]{2,80})$")
HEAD_CN = re.compile(r"^(?:第[一二三四五六七八九十]+[章节部分]|[一二三四五六七八九十]{1,3}[、.．])\s*(.{2,60})$")
CAPTION = re.compile(
    r"^(?:(?:Figure|Fig\.?|Scheme|Table|Extended Data Fig\.?|Supplementary (?:Fig\.?|Table))"
    r"\s*S?\d+[A-Za-z]?|图\s*\d+|表\s*\d+)[.:：\s]\s*(.*)$", re.I)
REF_HEAD = re.compile(r"^(?:references?|bibliography|literature cited|参考文献)$", re.I)
EQNUM = re.compile(r"\((\d{1,3}[a-z]?)\)\s*$")
FOOTNOTE = re.compile(r"^[*†‡§¶#]")
UNIT_AFTER_NUM = re.compile(r"^\d+(\.\d+)*\s*(?:%|mM|nM|uM|µM|mg|mL|kg|°C|K|s|h|min)\b")
UNREADABLE = re.compile(r"^\[unreadable: .*\]$")


def load_pages(path):
    """Split corpus.txt into per-file pages. Page numbers restart at 1 for each file."""
    text = open(path, encoding="utf-8", errors="replace").read()
    parts = re.split(r"^===== FILE: (.+?) =====[ \t]*$", text, flags=re.M)
    files = [("?", text)] if len(parts) == 1 else [(parts[k], parts[k + 1]) for k in range(1, len(parts), 2)]
    pages = []
    for fname, body in files:
        if body.startswith("\n"):
            body = body[1:]
        chunks = body.split("\f")
        while chunks and not chunks[0].strip():
            chunks = chunks[1:]
        while len(chunks) > 1 and not chunks[-1].strip():
            chunks = chunks[:-1]
        if not chunks:
            chunks = [""]
        for idx, chunk in enumerate(chunks, 1):
            pages.append({"file": fname, "page": idx, "global_page": len(pages) + 1,
                          "lines": [l.rstrip() for l in chunk.split("\n")]})
    return pages


def classify(text, ref_mode):
    if HEAD_MD.match(text):
        m = HEAD_MD.match(text)
        return "heading", len(m.group(1)), "", m.group(2)
    m = HEAD_NUM.match(text)
    if m and not UNIT_AFTER_NUM.match(text):
        return "heading", m.group(1).count(".") + 1, m.group(1), m.group(2)
    m = HEAD_CN.match(text)
    if m:
        return "heading", 1, "", m.group(1)
    if REF_HEAD.match(text):
        return "reference_head", 1, "", text
    if CAPTION.match(text):
        return "caption", 1, "", text
    if len(text) > 8 and EQNUM.search(text) and not text.endswith("."):
        return "equation", 1, "", text
    if FOOTNOTE.match(text):
        return "footnote", 1, "", text
    return ("reference" if ref_mode else "body"), 1, "", text


def dump(obj, path):
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(obj, fh, ensure_ascii=False, indent=1)


def furniture_per_file(pages):
    """A repeated edge line is furniture only relative to its own document."""
    out = {}
    for fname in dict.fromkeys(p["file"] for p in pages):
        fp = [p for p in pages if p["file"] == fname]
        edge = {}
        for p in fp:
            idx = [i for i, l in enumerate(p["lines"]) if l.strip()]
            for i in idx[:2] + idx[-2:]:
                key = re.sub(r"\d+", "#", p["lines"][i].strip())
                if len(key) >= 4:
                    edge.setdefault(key, set()).add(p["page"])
        need = max(2, int(0.6 * len(fp) + 0.999)) if len(fp) >= 2 else len(fp) + 1
        out[fname] = {k for k, s in edge.items() if len(s) >= need}
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", required=True)
    ap.add_argument("--out", default="work")
    a = ap.parse_args()

    if not os.path.exists(a.input):
        print("FAIL: corpus not found: %s (run kernel.py index first)" % a.input)
        return 2
    pages = load_pages(a.input)
    furn = furniture_per_file(pages)

    empty_pages, garbled_pages = [], []
    for p in pages:
        body = [l for l in p["lines"] if l.strip() and not UNREADABLE.match(l.strip())]
        if not body:
            empty_pages.append((p["file"], p["page"]))
        if any("\ufffd" in l for l in p["lines"]):
            garbled_pages.append((p["file"], p["page"]))

    blocks, sections, cur_section = [], [], "S000"
    ref_mode, cur_file = False, None
    for p in pages:
        if p["file"] != cur_file:  # reference mode must not leak across documents
            ref_mode, cur_file = False, p["file"]
        for i, raw in enumerate(p["lines"]):
            text = raw.strip()
            if not text:
                continue
            key = re.sub(r"\d+", "#", text)
            if UNREADABLE.match(text):
                kind, level, number, body = "unreadable", 1, "", text
            elif key in furn.get(p["file"], set()):
                kind, level, number, body = "furniture", 1, "", text
            else:
                kind, level, number, body = classify(text, ref_mode)
            ref_mode = ref_mode or kind == "reference_head"
            prev = blocks[-1] if blocks else None
            if (kind == "body" and prev and prev["type"] == "body" and prev["file"] == p["file"]
                    and prev["page"] == p["page"] and i - prev["_last"] <= 2):
                prev["text"] += " " + text
                prev["lines"] = "p%d:L%d-L%d" % (p["page"], prev["_first"] + 1, i + 1)
                prev["_last"] = i
                continue
            if kind == "heading":
                sections.append({"section_id": "S%03d" % len(sections), "number": number,
                                 "title": body, "level": level, "page_start": p["page"],
                                 "page_global": p["global_page"], "file": p["file"],
                                 "line_start": i + 1})
                cur_section = sections[-1]["section_id"]
            blocks.append({"block_id": "B%04d" % (len(blocks) + 1), "file": p["file"], "page": p["page"],
                           "page_global": p["global_page"],
                           "lines": "p%d:L%d-L%d" % (p["page"], i + 1, i + 1), "type": kind,
                           "level": level, "number": number, "section": cur_section, "text": body,
                           "garbled": "\ufffd" in text, "_first": i, "_last": i})

    last_page = {}
    for p in pages:
        last_page[p["file"]] = max(last_page.get(p["file"], 0), p["page"])
    for n, sec in enumerate(sections):
        same_file_next = [s for s in sections[n + 1:] if s["file"] == sec["file"]]
        sec["page_end"] = same_file_next[0]["page_start"] if same_file_next else last_page[sec["file"]]
        sec["blocks"] = sum(1 for b in blocks if b["section"] == sec["section_id"])
        sec["chars"] = sum(len(b["text"]) for b in blocks if b["section"] == sec["section_id"])

    body_blocks = [b for b in blocks if b["type"] == "body"]
    gap = sum(1 for b in body_blocks if re.search(r"\S {3,}\S", b["text"]))
    signal = round(gap / max(len(body_blocks), 1), 3)
    counts = dict(Counter(b["type"] for b in blocks))
    documents = []
    for fname in dict.fromkeys(p["file"] for p in pages):
        fp = [p for p in pages if p["file"] == fname]
        unread = [p["page"] for p in fp
                  if not [l for l in p["lines"] if l.strip() and not UNREADABLE.match(l.strip())]]
        documents.append({"file": fname, "pages": len(fp),
                          "text_layer": len(unread) < len(fp),
                          "unreadable_pages": unread,
                          "garbled_pages": [p["page"] for p in fp if any("\ufffd" in l for l in p["lines"])]})
    stats = {"pages": len(pages), "documents": len(documents), "empty_pages": [p for _, p in empty_pages],
             "pages_without_text": len(empty_pages), "garbled_pages": [p for _, p in garbled_pages],
             "furniture_patterns": {f: sorted(v) for f, v in furn.items() if v},
             "multi_column_signal": signal,
             "reading_order_risk": "review" if signal > 0.30 else "low", "block_counts": counts}

    os.makedirs(a.out, exist_ok=True)
    for b in blocks:
        b.pop("_first", None)
        b.pop("_last", None)
    dump({"documents": documents, "stats": stats, "sections": sections, "blocks": blocks},
         os.path.join(a.out, "sections.json"))
    dump(stats, os.path.join(a.out, "structure_stats.json"))
    with open(os.path.join(a.out, "locator_table.csv"), "w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["block_id", "file", "page", "page_global", "lines", "type", "level",
                    "number", "section", "garbled", "text"])
        for b in blocks:
            w.writerow([b["block_id"], b["file"], b["page"], b["page_global"], b["lines"], b["type"],
                        b["level"], b["number"], b["section"], b["garbled"], b["text"][:300]])

    lines = ["# 结构大纲（自动生成，供人工核对）", ""]
    for fname in dict.fromkeys(p["file"] for p in pages):
        doc = next(d for d in documents if d["file"] == fname)
        lines.append("## %s" % fname)
        lines.append("- pages: %d, text_layer: %s, unreadable_pages: %s"
                     % (doc["pages"], doc["text_layer"], doc["unreadable_pages"] or "none"))
        for sec in sections:
            if sec["file"] == fname:
                lines.append("  - %s%s %s (p%d-%d, %d blocks, %d chars)"
                             % ("  " * (sec["level"] - 1), sec["number"] or "-", sec["title"],
                                sec["page_start"], sec["page_end"], sec["blocks"], sec["chars"]))
        lines.append("")
    lines.append("block_counts: %s" % json.dumps(counts, ensure_ascii=False))
    with open(os.path.join(a.out, "structure.md"), "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")

    print("pages=%d documents=%d blocks=%d sections=%d empty_pages=%d furniture=%d "
          "multi_column_signal=%.3f\ntypes: %s"
          % (len(pages), len(documents), len(blocks), len(sections), len(empty_pages),
             sum(len(v) for v in furn.values()), signal, json.dumps(counts, ensure_ascii=False)))
    if len(empty_pages) >= 0.6 * max(len(pages), 1):
        print("WARN: >=60% pages carry no text layer -> treat as scanned, mark unreadable, do not guess")
    if garbled_pages:
        print("WARN: replacement chars on pages %s -> mark garbled, do not use for claims"
              % [p for _, p in garbled_pages])
    return 0


if __name__ == "__main__":
    sys.exit(main())
