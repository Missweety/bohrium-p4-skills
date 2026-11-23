#!/usr/bin/env python3
"""Index supplied case files and verify verbatim evidence quotes.

This helper only extracts and checks text. It does not judge relevance,
completeness, or whether a quotation supports a scientific claim.

Commands:
  extract --input DIR --out INDEX.json
  verify  --index INDEX.json --claims CLAIMS.json --out REPORT.json

Exit codes: 0 success (all quotes verified), 1 invalid input or failed quote,
2 extraction completed with unreadable files recorded.
"""
import argparse
import csv
import hashlib
import html
import io
import json
import os
import re
import shutil
import subprocess
import sys
import unicodedata
import zipfile
from datetime import datetime, timezone

TEXT_EXT = {".txt", ".md", ".markdown", ".csv", ".tsv", ".json", ".jsonl",
            ".yaml", ".yml", ".xml", ".html", ".htm", ".tex", ".bib", ".ris",
            ".toml", ".ini", ".log"}
MAX_TEXT = 5 * 1024 * 1024


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def norm(text):
    """Normalize for quote matching: unify width/space, repair line-break hyphenation."""
    if not text:
        return ""
    text = unicodedata.normalize("NFKC", text)
    text = text.replace("\u00ad", "")
    text = re.sub(r"(\w)-\s*\n\s*(\w)", r"\1\2", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip().casefold()


def _read_pdf_pdftotext(path):
    exe = shutil.which("pdftotext")
    if not exe:
        return None
    try:
        out = subprocess.run([exe, "-layout", path, "-"], capture_output=True,
                             timeout=120, check=False)
        if out.returncode == 0 and out.stdout.strip():
            return out.stdout.decode("utf-8", "replace")
    except (OSError, subprocess.SubprocessError):
        return None
    return None


def _read_pdf_pypdf(path):
    try:
        import pypdf  # optional
    except ImportError:
        return None
    try:
        reader = pypdf.PdfReader(path)
        return "\n\f\n".join((page.extract_text() or "") for page in reader.pages)
    except Exception:
        return None


def _strip_markup(text):
    text = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", text)
    text = re.sub(r"(?s)<[^>]+>", " ", text)
    return html.unescape(text)


def _docx_text(path):
    try:
        with zipfile.ZipFile(path) as zf:
            raw = zf.read("word/document.xml").decode("utf-8", "replace")
        raw = raw.replace("</w:p>", "\n")
        return _strip_markup(raw)
    except (KeyError, zipfile.BadZipFile, OSError):
        return None


def blocks_for(path, ext):
    """Return (kind, blocks, method, warning). blocks = [(locator, text)]."""
    try:
        if ext == ".pdf":
            text = _read_pdf_pdftotext(path)
            method = "pdftotext"
            if text is None:
                text = _read_pdf_pypdf(path)
                method = "pypdf"
            if text is None:
                return "pdf", [], "unavailable", "no PDF text extractor or encrypted/empty PDF"
            pages = text.split("\f")
            return "pdf", [(f"page:{i}", p) for i, p in enumerate(pages, 1) if p.strip()], method, ""
        if ext in {".csv", ".tsv"}:
            delimiter = "\t" if ext == ".tsv" else ","
            with open(path, encoding="utf-8-sig", errors="replace", newline="") as fh:
                rows = list(csv.reader(fh, delimiter=delimiter))
            blocks = [(f"row:{i}", " | ".join(cells))
                      for i, cells in enumerate(rows, 1) if any(c.strip() for c in cells)]
            return "table", blocks, "csv", ""
        if ext == ".jsonl":
            blocks = []
            with open(path, encoding="utf-8", errors="replace") as fh:
                for i, line in enumerate(fh, 1):
                    if line.strip():
                        blocks.append((f"line:{i}", line.rstrip("\n")))
            return "jsonl", blocks, "text", ""
        if ext == ".json":
            raw = open(path, encoding="utf-8", errors="replace").read()
            blocks = [(f"line:{i}", line) for i, line in enumerate(raw.splitlines(), 1)
                      if line.strip()]
            return "json", blocks, "text", ""
        if ext == ".docx":
            text = _docx_text(path)
            if text is None:
                return "docx", [], "unavailable", "docx text extraction failed"
            blocks = [(f"line:{i}", line) for i, line in enumerate(text.splitlines(), 1)
                      if line.strip()]
            return "docx", blocks, "docx-xml", ""
        if ext in {".html", ".htm", ".xml"}:
            raw = open(path, encoding="utf-8", errors="replace").read()
            text = _strip_markup(raw)
            blocks = [(f"line:{i}", line) for i, line in enumerate(text.splitlines(), 1)
                      if line.strip()]
            return "markup", blocks, "markup-strip", ""
        if ext in TEXT_EXT:
            raw = open(path, encoding="utf-8", errors="replace").read(MAX_TEXT)
            blocks = [(f"line:{i}", line) for i, line in enumerate(raw.splitlines(), 1)
                      if line.strip()]
            return "text", blocks, "utf8", ""
    except (OSError, UnicodeError) as exc:
        return "error", [], "failed", f"{type(exc).__name__}: {exc}"
    return "binary", [], "skipped", "not a supported text format"


def cmd_extract(args):
    if not os.path.isdir(args.input):
        print(f"error: input directory not found: {args.input}", file=sys.stderr)
        return 1
    files, unreadable = [], []
    for dirpath, dirnames, filenames in os.walk(args.input):
        dirnames.sort()
        for name in sorted(filenames):
            path = os.path.join(dirpath, name)
            rel = os.path.relpath(path, args.input)
            if os.path.islink(path):
                unreadable.append({"path": rel, "reason": "symlink skipped"})
                continue
            ext = os.path.splitext(name)[1].lower()
            kind, blocks, method, warning = blocks_for(path, ext)
            text_chars = sum(len(t) for _, t in blocks)
            item = {
                "path": rel,
                "sha256": sha256(path),
                "kind": kind,
                "method": method,
                "blocks": len(blocks),
                "text_chars": text_chars,
            }
            if warning:
                item["warning"] = warning
                unreadable.append({"path": rel, "reason": warning})
            else:
                item["content"] = [{"locator": loc, "text": text} for loc, text in blocks]
            files.append(item)
    index = {
        "root": os.path.abspath(args.input),
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "file_count": len(files),
        "text_file_count": sum(1 for f in files if f.get("content")),
        "unreadable": unreadable,
        "files": files,
    }
    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(index, fh, ensure_ascii=False, indent=1)
    print(f"indexed {len(files)} files ({index['text_file_count']} with text) -> {args.out}")
    if unreadable:
        for item in unreadable:
            print(f"warning: {item['path']}: {item['reason']}", file=sys.stderr)
        return 2
    return 0


def _claims(path):
    data = json.load(open(path, encoding="utf-8"))
    if isinstance(data, dict):
        data = data.get("evidence", data.get("claims", []))
    if not isinstance(data, list):
        raise ValueError("claims must be a list or an object with an evidence/claims list")
    return data


def cmd_verify(args):
    index = json.load(open(args.index, encoding="utf-8"))
    root = index.get("root", "")
    by_path = {f["path"]: f for f in index.get("files", [])}
    results, failed = [], 0
    for i, claim in enumerate(_claims(args.claims), 1):
        item = {"index": i, "ok": False}
        try:
            rel = str(claim["file"])
            locator = str(claim.get("locator", "")).strip()
            quote = str(claim["quote"])
        except (KeyError, TypeError):
            item["reason"] = "claim needs file, locator and quote"
            results.append(item)
            failed += 1
            continue
        item.update({"file": rel, "locator": locator})
        rec = by_path.get(rel)
        if not rec:
            item["reason"] = "file not in index"
        elif rec.get("kind") == "binary":
            item["reason"] = "binary file has no text"
        else:
            current = sha256(os.path.join(root, rel)) if os.path.exists(os.path.join(root, rel)) else None
            if current != rec.get("sha256"):
                item["reason"] = "source hash changed since indexing"
            else:
                block = None
                for candidate in rec.get("content", []):
                    if candidate["locator"] == locator:
                        block = candidate["text"]
                        break
                if block is None:
                    item["reason"] = f"locator not found: {locator}"
                elif norm(quote) and norm(quote) in norm(block):
                    item["ok"] = True
                    item["reason"] = "verbatim quote found"
                else:
                    item["reason"] = "quote not found at locator"
        results.append(item)
        failed += 0 if item["ok"] else 1
    report = {"generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
              "claims": len(results), "verified": len(results) - failed,
              "failed": failed, "results": results}
    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(report, fh, ensure_ascii=False, indent=1)
    print(f"verified {report['verified']}/{report['claims']} claims -> {args.out}")
    return 0 if failed == 0 else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("extract")
    p.add_argument("--input", required=True)
    p.add_argument("--out", required=True)
    p.set_defaults(func=cmd_extract)
    p = sub.add_parser("verify")
    p.add_argument("--index", required=True)
    p.add_argument("--claims", required=True)
    p.add_argument("--out", required=True)
    p.set_defaults(func=cmd_verify)
    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
