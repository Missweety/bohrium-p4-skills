#!/usr/bin/env python3
"""Extract text with stable anchors from supplied scientific materials.

Pure standard library. PDF uses pdftotext when available, then pypdf if installed;
otherwise the file is reported as unreadable instead of being guessed.

Usage: python3 extract_sources.py --input /input --out /app/work/sources.json
"""
import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import zipfile

TEXT_EXT = {".txt", ".md", ".markdown", ".tex", ".csv", ".tsv", ".json", ".html", ".htm", ".xml", ".yaml", ".yml"}


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def norm_ws(text):
    text = text.replace("\u3000", " ").replace("\xa0", " ")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{2,}", "\n", text)
    return text.strip()


def split_paragraphs(text):
    parts = re.split(r"\n\s*\n", text)
    out = []
    for p in parts:
        p = p.strip()
        if len(p) >= 2:
            out.append(p)
    return out


def read_text(path):
    for enc in ("utf-8", "utf-8-sig", "gb18030", "latin-1"):
        try:
            with open(path, encoding=enc) as fh:
                return fh.read()
        except (UnicodeDecodeError, LookupError):
            continue
    with open(path, encoding="utf-8", errors="replace") as fh:
        return fh.read()


def read_docx(path):
    with zipfile.ZipFile(path) as z:
        xml = z.read("word/document.xml").decode("utf-8", "replace")
    xml = re.sub(r"</w:p>", "\n\n", xml)
    xml = re.sub(r"<w:tab[^>]*/>", "\t", xml)
    text = re.sub(r"<[^>]+>", "", xml)
    return text


def read_pdf(path):
    if shutil.which("pdftotext"):
        try:
            out = subprocess.run(["pdftotext", "-layout", path, "-"],
                                 capture_output=True, timeout=120)
            if out.returncode == 0 and out.stdout.strip():
                return out.stdout.decode("utf-8", "replace"), "pdftotext"
        except Exception:  # noqa: BLE001
            pass
    try:
        import pypdf  # type: ignore
        reader = pypdf.PdfReader(path)
        pages = [(p.extract_text() or "") for p in reader.pages]
        return "\f".join(pages), "pypdf"
    except Exception:  # noqa: BLE001
        pass
    try:
        import PyPDF2  # type: ignore
        reader = PyPDF2.PdfReader(path)
        pages = [(p.extract_text() or "") for p in reader.pages]
        return "\f".join(pages), "PyPDF2"
    except Exception:  # noqa: BLE001
        return None, "unreadable"


def parse_pages(raw, engine):
    if engine == "pdftotext" or "\f" in raw:
        return [p for p in raw.split("\f")]
    return [raw]


def extract_file(path, doc_no, input_root="/input"):
    ext = os.path.splitext(path)[1].lower()
    rec = {"doc": "doc.%d" % doc_no, "path": os.path.relpath(path, input_root),
           "bytes": os.path.getsize(path), "sha256": sha256(path),
           "readable": False, "engine": None, "pages": [], "paragraphs": []}
    if ext == ".pdf":
        raw, engine = read_pdf(path)
        rec["engine"] = engine
        if raw is None:
            return rec
        pages = parse_pages(raw, engine)
    elif ext == ".docx":
        try:
            raw = read_docx(path)
            rec["engine"] = "docx-xml"
            pages = [raw]
        except Exception as exc:  # noqa: BLE001
            rec["error"] = str(exc)[:200]
            return rec
    elif ext in TEXT_EXT:
        raw = read_text(path)
        rec["engine"] = "text"
        pages = [raw]
    else:
        rec["engine"] = "skip"
        return rec

    page_no = 0
    sec_no = 0
    for page in pages:
        page_no += 1
        if not page or not page.strip():
            continue
        for para in split_paragraphs(page):
            head = para.strip()
            if re.match(r"^(#{1,6})\s+", head):
                sec_no += 1
            para_no = len(rec["paragraphs"]) + 1
            anchor = "%s p.%d sec.%d para.%d" % (rec["doc"], page_no, max(sec_no, 1), para_no)
            rec["paragraphs"].append({
                "anchor": anchor,
                "page": page_no,
                "section": max(sec_no, 1),
                "text": head[:4000],
                "norm": norm_ws(head)[:4000],
            })
        rec["pages"].append({"page": page_no, "chars": len(page)})
    rec["readable"] = bool(rec["paragraphs"])
    return rec


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", default="/input")
    ap.add_argument("--out", default="/app/work/sources.json")
    a = ap.parse_args()
    docs = []
    skipped = []
    doc_no = 0
    for root, dirs, files in os.walk(a.input):
        dirs[:] = [d for d in dirs if d not in {".git", "__pycache__", "node_modules"}]
        for name in sorted(files):
            path = os.path.join(root, name)
            if name.startswith("."):
                continue
            ext = os.path.splitext(name)[1].lower()
            if ext not in TEXT_EXT and ext not in {".pdf", ".docx"}:
                skipped.append(os.path.relpath(path, a.input))
                continue
            if os.path.abspath(path) in {
                os.path.abspath(os.path.join(a.input, "case.json")),
                os.path.abspath(os.path.join(a.input, "task.md")),
            }:
                continue
            doc_no += 1
            docs.append(extract_file(path, doc_no, a.input))
    payload = {
        "input_root": a.input,
        "documents": docs,
        "skipped_files": skipped,
        "readable_documents": sum(1 for d in docs if d["readable"]),
        "total_paragraphs": sum(len(d["paragraphs"]) for d in docs),
    }
    os.makedirs(os.path.dirname(a.out) or ".", exist_ok=True)
    with open(a.out, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=1)
    print(json.dumps({"documents": len(docs), "readable": payload["readable_documents"],
                      "paragraphs": payload["total_paragraphs"],
                      "skipped": len(skipped)}, ensure_ascii=False))
    if payload["readable_documents"] == 0:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
