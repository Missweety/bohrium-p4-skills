#!/usr/bin/env python3
"""library.py - evidence-first research library organizer (v2).

Copy-based, hash-verified organization of a source library. Standard library
only. Every command writes deterministic JSON (no wall-clock timestamps) so a
repeated run over unchanged inputs produces identical records.

Commands:
  inventory      scan a source tree, sniff real file types, decode text, probe PDFs
  validate-plan  check a plan.json before touching disk
  apply          copy planned files into an output library (strict or --allow-partial)
  dupes          group byte duplicates, shared DOIs and version evidence -> relations.json
  search         search index metadata AND extracted body text -> stdout / queries.json
  report         build result.json from the case output_contract
  check          self-check the output library and result.json
  rollback       remove only copies this tool created whose hash is unchanged
"""
import argparse
import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import unicodedata
from pathlib import Path

TOOL = "library.py"
VERSION = "2.0.0"

INDEX_NAME = "index.json"
OPERATIONS_NAME = "operations.json"
INVENTORY_NAME = "inventory.json"
SKIPPED_NAME = "skipped.json"
RELATIONS_NAME = "relations.json"
QUERIES_NAME = "queries.json"
TREE_NAME = "tree.json"
ROLLBACK_NAME = "rollback.json"
CHECK_NAME = "check.json"
CACHE_DIR = ".library-cache"
CACHE_NAME = "text.json"
INTERNAL_TOP = {
    INDEX_NAME, OPERATIONS_NAME, INVENTORY_NAME, SKIPPED_NAME,
    RELATIONS_NAME, QUERIES_NAME, TREE_NAME, ROLLBACK_NAME, CHECK_NAME,
}

TEXT_EXTS = {
    ".md", ".markdown", ".txt", ".text", ".csv", ".tsv", ".json", ".bib", ".ris",
    ".yaml", ".yml", ".xml", ".html", ".htm", ".tex", ".rst", ".log", ".ini",
    ".cfg", ".toml", ".py", ".sh", ".sql", ".srt", ".vtt",
}
TEXT_READ_LIMIT = 4 * 1024 * 1024          # bytes read for decoding / hashing excerpt
TEXT_STORE_LIMIT = 200_000                 # chars stored per file in the text cache
TEXT_CACHE_TOTAL_LIMIT = 8 * 1024 * 1024   # bytes of text in the cache
EXCERPT_CHARS = [1200]                     # chars of excerpt kept in inventory records
PDF_TIMEOUT = 45
DOI_RE = re.compile(r"\b10\.\d{4,9}/[-._;()/:A-Za-z0-9]+\b")
SURNAME_HINT = re.compile(r"(?im)^\s*(authors?|author list|by)\s*[:：]\s*(.+)$")


class ToolError(Exception):
    """Operational failure that should exit non-zero with a readable message."""


# --------------------------------------------------------------------------
# generic helpers
# --------------------------------------------------------------------------
def nfc(value):
    return unicodedata.normalize("NFC", value)


def posix_rel(path, root):
    return nfc(Path(path).relative_to(root).as_posix())


def digest(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def read_head(path, size=8192):
    try:
        with open(path, "rb") as fh:
            return fh.read(size)
    except OSError:
        return b""


def json_dump_text(obj):
    return json.dumps(obj, ensure_ascii=False, indent=1, sort_keys=False) + "\n"


def save_json(path, obj, force=False):
    """Atomic JSON write; unchanged content is left untouched for idempotency."""
    path = Path(path)
    text = json_dump_text(obj)
    if not force and path.exists():
        try:
            if path.read_text(encoding="utf-8") == text:
                return False
        except (OSError, UnicodeError):
            pass
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".tmp-")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)
    return True


def read_json(path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except (OSError, ValueError) as exc:
        raise ToolError("cannot read JSON %s: %s" % (path, exc))


def is_reserved_target(rel):
    parts = rel.split("/")
    if parts and parts[0] in INTERNAL_TOP:
        return True
    if any(p == CACHE_DIR for p in parts):
        return True
    return False


def safe_target(root, name):
    """Validate a plan-relative destination and return the absolute Path."""
    if not isinstance(name, str) or not name.strip():
        raise ToolError("invalid target: empty path")
    if name.startswith("/") or name.startswith("\\"):
        raise ToolError("invalid target (absolute path): %s" % name)
    rel = nfc(name.replace("\\", "/"))
    if "\x00" in rel:
        raise ToolError("invalid target (control character): %s" % name)
    parts = [p for p in rel.split("/") if p not in ("", ".")]
    if not parts or any(p == ".." for p in parts):
        raise ToolError("invalid target (path escape): %s" % name)
    for part in parts:
        if len(part.encode("utf-8")) > 255:
            raise ToolError("invalid target (component over 255 bytes): %s" % name)
    rel = "/".join(parts)
    if len(rel.encode("utf-8")) > 1000:
        raise ToolError("invalid target (path too long): %s" % name)
    if is_reserved_target(rel):
        raise ToolError("target name reserved for library records: %s" % rel)
    current = Path(root)
    for part in parts:
        current = current / part
        if current.is_symlink():
            raise ToolError("target passes through a symlink: %s" % rel)
    root_real = Path(root).resolve()
    try:
        if not current.resolve(strict=False).is_relative_to(root_real):
            raise ToolError("target escapes output root: %s" % rel)
    except OSError as exc:
        raise ToolError("cannot resolve target %s: %s" % (rel, exc))
    return Path(root) / Path(*parts)


# --------------------------------------------------------------------------
# type sniffing, decoding, PDF probing
# --------------------------------------------------------------------------
MAGIC = [
    (b"%PDF", "pdf"),
    (b"PK\x03\x04", "zip"),
    (bytes.fromhex("d0cf11e0a1b11ae1"), "ole"),
    (b"\x89PNG\r\n\x1a\n", "image"),
    (b"\xff\xd8\xff", "image"),
    (b"GIF87a", "image"),
    (b"GIF89a", "image"),
    (b"II*\x00", "image"),
    (b"MM\x00*", "image"),
    (b"BM", "image"),
    (b"RIFF", "riff"),
    (b"%!PS", "postscript"),
    (b"{\\rtf", "rtf"),
    (b"SQLite format 3\x00", "sqlite"),
    (b"\x1f\x8b", "gzip"),
    (b"\x7fELF", "elf"),
]


def sniff_kind(head):
    for magic, kind in MAGIC:
        if head.startswith(magic):
            return kind
    if len(head) > 262 and head[257:262] == b"ustar":
        return "tar"
    return "unknown"


def decode_bytes(raw):
    """Return (text, encoding, confidence). Order is deterministic."""
    if raw.startswith(b"\xef\xbb\xbf"):
        try:
            return raw.decode("utf-8-sig"), "utf-8-sig", "high"
        except UnicodeDecodeError:
            pass
    if raw.startswith(b"\xff\xfe"):
        try:
            return raw.decode("utf-16"), "utf-16-le", "high"
        except UnicodeDecodeError:
            pass
    if raw.startswith(b"\xfe\xff"):
        try:
            return raw.decode("utf-16"), "utf-16-be", "high"
        except UnicodeDecodeError:
            pass
    for encoding, confidence in (("utf-8", "high"), ("gb18030", "medium"), ("big5", "medium")):
        try:
            return raw.decode(encoding), encoding, confidence
        except UnicodeDecodeError:
            continue
    return raw.decode("latin-1"), "latin-1", "low"


def read_text_file(path, limit=TEXT_READ_LIMIT):
    """Decode a text file with encoding fallback. Returns a dict."""
    try:
        with open(path, "rb") as fh:
            raw = fh.read(limit)
            more = fh.read(1)
    except OSError as exc:
        return {"status": "unreadable", "error": str(exc), "text": "", "truncated": False}
    if b"\x00" in raw[:8192] and not raw.startswith((b"\xff\xfe", b"\xfe\xff")):
        return {"status": "binary", "encoding": None, "confidence": "n/a", "text": "",
                "truncated": bool(more)}
    text, encoding, confidence = decode_bytes(raw)
    return {
        "status": "ok",
        "encoding": encoding,
        "confidence": confidence,
        "fallback": encoding not in ("utf-8", "utf-8-sig"),
        "text": text,
        "chars": len(text),
        "truncated": bool(more),
    }


def run_tool(cmd, timeout):
    try:
        proc = subprocess.run(cmd, capture_output=True, timeout=timeout)
        return proc.returncode, proc.stdout, proc.stderr.decode("utf-8", "replace")
    except FileNotFoundError:
        return None, b"", "tool-not-found"
    except subprocess.TimeoutExpired:
        return -1, b"", "timeout"


def probe_pdf(path):
    """Return {pdf_status, pages, text, error}. pdf_status in ok/not_a_pdf/encrypted/no_text_layer/pdf_error/unavailable."""
    head = read_head(path, 1024)
    if b"%PDF-" not in head:
        return {"pdf_status": "not_a_pdf", "pages": None, "text": "",
                "error": "no %PDF- header in first 1024 bytes"}
    info = {"pdf_status": "pdf_error", "pages": None, "text": "", "error": ""}
    rc, out, err = run_tool(["pdfinfo", str(path)], PDF_TIMEOUT)
    if rc is None:
        info["error"] = "pdfinfo not installed"
        info["pdf_status"] = "unavailable"
        return info
    info_text = out.decode("utf-8", "replace")
    pages = None
    for line in info_text.splitlines():
        if line.lower().startswith("pages:"):
            try:
                pages = int(line.split(":", 1)[1].strip())
            except ValueError:
                pages = None
    info["pages"] = pages
    lowered = (info_text + "\n" + err).lower()
    encrypted = bool(re.search(r"(?m)^encrypted:\s*yes", info_text, re.I)) or "incorrect password" in lowered
    if rc != 0:
        if "may not be a pdf" in lowered or "couldn't find trailer" in lowered or "could not find trailer" in lowered:
            info["pdf_status"] = "not_a_pdf"
        elif encrypted or "password" in lowered:
            info["pdf_status"] = "encrypted"
        else:
            info["pdf_status"] = "pdf_error"
        info["error"] = (err or info_text).strip()[:500]
        return info
    if encrypted:
        info["pdf_status"] = "encrypted"
        info["error"] = "pdfinfo reports Encrypted: yes"
        return info
    trc, tout, terr = run_tool(["pdftotext", "-layout", str(path), "-"], PDF_TIMEOUT)
    if trc is None:
        info["pdf_status"] = "unavailable"
        info["error"] = "pdftotext not installed"
        return info
    text = tout.decode("utf-8", "replace")
    if trc != 0:
        tlow = (terr + text).lower()
        if "may not be a pdf" in tlow or "couldn't find trailer" in tlow:
            info["pdf_status"] = "not_a_pdf"
        elif "password" in tlow:
            info["pdf_status"] = "encrypted"
        else:
            info["pdf_status"] = "pdf_error"
        info["error"] = (terr or text).strip()[:500]
        return info
    if not text.strip():
        info["pdf_status"] = "no_text_layer"
        info["error"] = "pdftotext returned no text (scanned image or empty page)"
        return info
    info["pdf_status"] = "ok"
    info["text"] = text
    if pages is None:
        pages = text.count("\f") + 1
        info["pages"] = pages
    return info


def hint_locator(text, offset, kind):
    if kind == "pdf":
        return "page %d" % (text[:offset].count("\f") + 1)
    return "line %d" % (text[:offset].count("\n") + 1)


def metadata_hints(text, kind):
    """Cheap, evidence-located metadata hints. Never invents: each has a locator."""
    hints = {}
    lines = text.splitlines(True)
    offsets = []
    pos = 0
    for line in lines:
        offsets.append(pos)
        pos += len(line)
    for idx, raw_line in enumerate(lines):
        line = raw_line.rstrip("\r\n")
        locator = hint_locator(text, offsets[idx], kind)
        m = re.match(r"(?i)^\s*(?:title|article title)\s*[:：]\s*(.+)$", line)
        if m and "title" not in hints:
            hints["title"] = {"value": m.group(1).strip(), "locator": locator}
        m = SURNAME_HINT.match(line)
        if m and "authors" not in hints:
            raw = m.group(2).strip()
            parts = [p.strip() for p in re.split(r"[;；]", raw) if p.strip()]
            hints["authors"] = {"value": parts or [raw], "locator": locator}
        m = re.match(r"(?i)^\s*(?:year|published|publication year)\s*[:：]\s*(19\d{2}|20\d{2})\b", line)
        if m and "year" not in hints:
            hints["year"] = {"value": int(m.group(1)), "locator": locator}
        if DOI_RE.search(line) and "doi" not in hints:
            hints["doi"] = {"value": DOI_RE.search(line).group(0), "locator": locator}
    if kind == "text":
        for idx, raw_line in enumerate(lines[:30]):
            line = raw_line.rstrip("\r\n")
            if "title" not in hints and line.startswith("# "):
                title = line[2:].strip()
                if title:
                    hints["title"] = {"value": title, "locator": hint_locator(text, offsets[idx], kind)}
                    break
        for idx, raw_line in enumerate(lines[:40]):
            if "year" not in hints:
                m = re.search(r"\b(19\d{2}|20\d{2})\b", raw_line)
                if m:
                    hints["year"] = {"value": int(m.group(1)),
                                     "locator": hint_locator(text, offsets[idx] + m.start(), kind)}
    if not text:
        return hints
    if "doi" not in hints:
        m = DOI_RE.search(text)
        if m:
            hints["doi"] = {"value": m.group(0), "locator": hint_locator(text, m.start(), kind)}
    return hints


def extract_entry(path, ext, kind, magic=None):
    """Extract text/encoding/PDF facts. A .pdf suffix is always probed, even if the bytes disagree."""
    result = {
        "kind": kind,
        "text": "",
        "encoding": None,
        "encoding_confidence": None,
        "encoding_fallback": False,
        "text_status": "not_extracted",
        "pdf_status": None,
        "pages": None,
        "error": None,
        "truncated": False,
    }
    if kind == "pdf" or ext == ".pdf":
        probe = probe_pdf(path)
        result["pdf_status"] = probe["pdf_status"]
        result["pages"] = probe["pages"]
        result["error"] = probe["error"] or None
        if probe["pdf_status"] == "ok":
            result["kind"] = "pdf"
            result["text"] = probe["text"]
            result["text_status"] = "ok"
            result["encoding"] = "pdf-text-layer"
        else:
            result["text_status"] = probe["pdf_status"]
        return result
    if ext in TEXT_EXTS or magic == "text" or kind == "unknown":
        decoded = read_text_file(path)
        result["text_status"] = decoded["status"]
        result["text"] = decoded.get("text", "")
        result["encoding"] = decoded.get("encoding")
        result["encoding_confidence"] = decoded.get("confidence")
        result["encoding_fallback"] = bool(decoded.get("fallback"))
        result["truncated"] = bool(decoded.get("truncated"))
        result["error"] = decoded.get("error")
    else:
        result["text_status"] = "binary_skipped"
    return result


# --------------------------------------------------------------------------
# inventory
# --------------------------------------------------------------------------
def scan_tree(root, extract=True):
    """Walk root without following symlinks. Returns list of entries in stable order.

    extract=False skips hashing/decoding/text extraction (fast path for plan validation).
    """
    root = Path(root).resolve()
    entries = []

    def walk(base, depth):
        try:
            scanned = list(os.scandir(base))
        except OSError as exc:
            entries.append({
                "path": posix_rel(base, root) if base != root else ".",
                "type": "directory",
                "status": "unreadable_directory",
                "error": str(exc),
                "depth": depth,
            })
            return
        for ent in sorted(scanned, key=lambda e: nfc(e.name)):
            path = Path(ent.path)
            rel = posix_rel(path, root)
            raw_name = ent.name
            row = {
                "path": rel,
                "name": nfc(raw_name),
                "depth": depth,
                "nfc_normalized": nfc(raw_name) == raw_name,
            }
            try:
                st = ent.stat(follow_symlinks=False)
                row["mode"] = oct(stat.S_IMODE(st.st_mode))
                row["size_bytes"] = st.st_size
                if ent.is_symlink():
                    target = os.readlink(path)
                    resolved = Path(target) if os.path.isabs(target) else (path.parent / target)
                    inside = False
                    try:
                        inside = resolved.resolve(strict=False).is_relative_to(root)
                    except OSError:
                        inside = False
                    readable = False
                    target_kind = None
                    target_sha = None
                    target_size = None
                    target_is_dir = None
                    try:
                        if inside and resolved.exists():
                            readable = os.access(resolved, os.R_OK)
                            target_kind = sniff_kind(read_head(resolved, 1024))
                            target_is_dir = resolved.is_dir()
                            if resolved.is_file() and readable:
                                target_sha = digest(resolved)
                                target_size = resolved.stat().st_size
                    except OSError as exc:
                        row["target_error"] = str(exc)
                    row.update({
                        "type": "symlink",
                        "status": "symlink_recorded" if inside else "symlink_outside_root",
                        "target": target,
                        "target_inside_root": inside,
                        "target_readable": readable,
                        "target_is_dir": target_is_dir,
                        "target_kind": target_kind,
                        "target_sha256": target_sha,
                        "target_size_bytes": target_size,
                    })
                    entries.append(row)
                    continue
                if ent.is_dir(follow_symlinks=False):
                    row.update({"type": "directory", "status": "inventoried"})
                    entries.append(row)
                    walk(path, depth + 1)
                    continue
                if ent.is_file(follow_symlinks=False):
                    ext = path.suffix.lower()
                    readable = os.access(path, os.R_OK)
                    row.update({
                        "type": "file",
                        "status": "ok",
                        "ext": ext,
                        "empty": st.st_size == 0,
                        "readable": readable,
                    })
                    if not readable:
                        row.update({
                            "status": "unreadable",
                            "kind": "unknown",
                            "content_kind": None,
                            "text_status": "unreadable",
                            "error": "file is not readable by this process",
                        })
                        entries.append(row)
                        continue
                    head = read_head(path, 8192)
                    magic = sniff_kind(head)
                    if magic == "unknown" and b"\x00" not in head[:8192]:
                        decoded_probe = read_text_file(path, 65536)
                        magic = "text" if decoded_probe.get("status") == "ok" else "binary"
                    kind = "pdf" if (magic == "pdf" or ext == ".pdf") else magic
                    expected = None
                    if ext == ".pdf":
                        expected = "pdf"
                    elif ext in TEXT_EXTS:
                        expected = "text"
                    elif ext in (".png", ".jpg", ".jpeg", ".gif", ".tif", ".tiff", ".bmp", ".webp"):
                        expected = "image"
                    row.update({
                        "content_kind": magic,
                        "kind": kind,
                        "type_matches_extension": True if expected is None else (magic == expected),
                    })
                    if not extract:
                        entries.append(row)
                        continue
                    try:
                        row["sha256"] = digest(path)
                        facts = extract_entry(path, ext, kind, magic)
                        text = facts.pop("text", "")
                        row.update(facts)
                        row["chars"] = len(text)
                        row["lines"] = text.count("\n") + 1 if text else 0
                        row["excerpt"] = text[:EXCERPT_CHARS[0]]
                        row["hints"] = metadata_hints(text, kind)
                        row["_text"] = text
                    except OSError as exc:
                        row.update({"status": "unreadable", "error": str(exc),
                                    "text_status": "unreadable"})
                    entries.append(row)
                    continue
                row.update({"type": "special", "status": "skipped_special_file"})
                entries.append(row)
            except OSError as exc:
                row.update({"type": "unknown", "status": "unreadable", "error": str(exc)})
                entries.append(row)

    walk(root, 0)
    return entries


def summarize_entries(entries):
    counts = {}
    for row in entries:
        counts[row.get("type", "unknown")] = counts.get(row.get("type", "unknown"), 0) + 1
    unreadable = [r["path"] for r in entries if r.get("status") == "unreadable"
                  or r.get("status") == "unreadable_directory"]
    pdfs = {}
    for row in entries:
        if row.get("kind") == "pdf" and row.get("pdf_status"):
            pdfs[row["pdf_status"]] = pdfs.get(row["pdf_status"], 0) + 1
    encodings = {}
    for row in entries:
        if row.get("encoding") and row.get("type") == "file":
            encodings[row["encoding"]] = encodings.get(row["encoding"], 0) + 1
    return {"counts_by_type": counts, "unreadable": unreadable,
            "pdf_status": pdfs, "encodings": encodings,
            "files": sum(1 for r in entries if r.get("type") == "file")}


def public_entries(entries):
    out = []
    for row in entries:
        clean = {k: v for k, v in row.items() if not k.startswith("_")}
        out.append(clean)
    return out


def build_manifest(root):
    """Full scan with internal text retained for cache building."""
    entries = scan_tree(root)
    return entries


def write_cache(out, entries, existing=None):
    cache = existing or {}
    stored = 0
    truncated_files = []
    for row in entries:
        if row.get("type") != "file" or row.get("status") != "ok":
            continue
        sha = row.get("sha256")
        text = row.get("_text") or ""
        if not sha:
            continue
        if len(text) > TEXT_STORE_LIMIT:
            truncated_files.append(row["path"])
            text = text[:TEXT_STORE_LIMIT]
        if stored + len(text.encode("utf-8", "replace")) > TEXT_CACHE_TOTAL_LIMIT:
            truncated_files.append(row["path"])
            continue
        stored += len(text.encode("utf-8", "replace"))
        cache[sha] = {
            "path": row["path"],
            "kind": row.get("kind"),
            "encoding": row.get("encoding"),
            "pdf_status": row.get("pdf_status"),
            "pages": row.get("pages"),
            "text": text,
        }
    payload = {
        "tool": TOOL, "version": VERSION, "method": "sha256-keyed extracted text",
        "truncated_files": sorted(set(truncated_files)),
        "files": cache,
    }
    save_json(Path(out) / CACHE_DIR / CACHE_NAME, payload)
    return payload


def load_cache(out):
    data = read_json(Path(out) / CACHE_DIR / CACHE_NAME)
    return data or {"files": {}, "truncated_files": []}


def entry_text(out, entry, cache):
    sha = entry.get("sha256")
    if sha and sha in cache.get("files", {}):
        return cache["files"][sha].get("text", ""), "cache"
    target = Path(out) / entry["target"]
    if not target.is_file():
        return "", "missing"
    facts = extract_entry(target, target.suffix.lower(), entry.get("kind") or "unknown")
    return facts.get("text", ""), "re-extracted"


# --------------------------------------------------------------------------
# plan validation
# --------------------------------------------------------------------------
def load_plan(path):
    data = read_json(path)
    if data is None:
        raise ToolError("plan not found: %s" % path)
    if isinstance(data, list):
        data = {"files": data}
    if not isinstance(data, dict) or not isinstance(data.get("files"), list):
        raise ToolError("plan must be an object with a 'files' list")
    return data


def build_source_map(root):
    """Map NFC relative path -> actual Path, without following symlinks."""
    mapping = {}
    for row in scan_tree(root, extract=False):
        if row.get("type") in ("file", "symlink", "directory"):
            mapping[row["path"]] = root / Path(row["path"])
    return mapping


def plan_errors_and_ops(root, out, plan, entries=None, previous=None):
    inventory_rows = entries if entries is not None else scan_tree(root, extract=False)
    source_map = {}
    for row in inventory_rows:
        if row.get("type") in ("file", "symlink", "directory"):
            source_map[row["path"]] = root / Path(row["path"])
    prev_by_key = {}
    for rec in (previous or {}).get("operations", []):
        prev_by_key[(nfc(str(rec.get("source") or "")), nfc(str(rec.get("target") or "")))] = rec
    errors = []
    warnings = []
    candidates = []
    seen_targets = {}
    seen_sources = {}

    for pos, item in enumerate(plan["files"]):
        label = "files[%d]" % pos
        row = {"index": pos, "source": None, "target": None}
        if not isinstance(item, dict):
            errors.append({"code": "invalid_item", "item": label,
                           "message": "plan item must be an object"})
            continue
        src_raw = item.get("source")
        tgt_raw = item.get("target")
        row.update({"source": src_raw, "target": tgt_raw,
                    "metadata": item.get("metadata") or {},
                    "tags": item.get("tags") or [],
                    "version_relation": item.get("version_relation"),
                    "evidence": item.get("evidence"),
                    "reason": item.get("reason"),
                    "raw": item})
        failures = []

        if not isinstance(src_raw, str) or not src_raw.strip():
            failures.append(("source_missing_in_plan", "source is required"))
        if not isinstance(tgt_raw, str) or not tgt_raw.strip():
            failures.append(("target_missing_in_plan", "target is required"))
        ev = item.get("evidence")
        if not ev or (isinstance(ev, list) and not [x for x in ev if str(x).strip()]):
            failures.append(("evidence_missing", "evidence (locator) is required"))
        if not item.get("reason") or not str(item.get("reason")).strip():
            failures.append(("reason_missing", "reason is required"))
        if item.get("tags") is not None and not isinstance(item.get("tags"), list):
            failures.append(("tags_not_list", "tags must be a list"))
        if item.get("metadata") is not None and not isinstance(item.get("metadata"), dict):
            failures.append(("metadata_not_object", "metadata must be an object"))

        src_path = None
        src_rel = None
        if isinstance(src_raw, str) and src_raw.strip():
            src_rel = nfc(src_raw.replace("\\", "/").lstrip("./")) if not src_raw.startswith("..") else nfc(src_raw)
            if src_rel.startswith("../") or src_rel == "..":
                failures.append(("source_escape", "source escapes the source root: %s" % src_raw))
            elif src_rel not in source_map:
                failures.append(("source_missing", "source does not exist in inventory: %s" % src_raw))
            else:
                src_path = source_map[src_rel]
                row["path_actual"] = str(src_path)
                row["source_rel"] = src_rel
        tgt_path = None
        tgt_rel = None
        if isinstance(tgt_raw, str) and tgt_raw.strip():
            try:
                tgt_path = safe_target(out, tgt_raw)
                tgt_rel = posix_rel(tgt_path, Path(out))
                row["target_rel"] = tgt_rel
            except ToolError as exc:
                failures.append(("target_invalid", str(exc)))

        if src_path is not None:
            try:
                lst = os.lstat(src_path)
            except OSError as exc:
                failures.append(("source_unreadable", "cannot stat source: %s" % exc))
                lst = None
            if lst is not None:
                if stat.S_ISLNK(lst.st_mode):
                    failures.append(("source_symlink",
                                     "source is a symlink; plan the real file instead (%s)" % os.readlink(src_path)))
                elif not stat.S_ISREG(lst.st_mode):
                    failures.append(("source_not_regular_file", "source is not a regular file"))
                elif not os.access(src_path, os.R_OK):
                    failures.append(("source_unreadable", "source is not readable"))
                if not failures:
                    try:
                        row["sha256"] = digest(src_path)
                        row["size_bytes"] = lst.st_size
                    except OSError as exc:
                        failures.append(("source_unreadable", "cannot read source: %s" % exc))
                    if tgt_rel and Path(tgt_rel).suffix.lower() != src_path.suffix.lower():
                        warnings.append({"code": "suffix_changed", "item": src_rel,
                                         "message": "target suffix %s differs from source suffix %s"
                                                    % (Path(tgt_rel).suffix, src_path.suffix)})
                    meta = row.get("metadata") or {}
                    missing = [k for k in ("title", "authors", "year", "doi") if not meta.get(k)]
                    if missing:
                        warnings.append({"code": "metadata_incomplete", "item": src_rel,
                                         "message": "missing metadata fields: " + ", ".join(missing)})

        if tgt_rel:
            key = tgt_rel.casefold()
            seen_targets.setdefault(key, []).append(src_rel)
            if tgt_path.exists() and not tgt_path.is_file():
                failures.append(("target_not_file", "target exists and is not a regular file: %s" % tgt_rel))
            elif tgt_path.is_file() and row.get("sha256") and digest(tgt_path) != row["sha256"]:
                recorded = prev_by_key.get((nfc(str(src_rel or "")), nfc(str(tgt_rel))))
                if recorded is None:
                    failures.append((
                        "interrupted_partial",
                        "target exists with different content and no operation record "
                        "(likely an interrupted partial copy); delete or rename it before "
                        "retrying, or pass --allow-partial to skip: %s" % tgt_rel))
                else:
                    failures.append(("target_conflict",
                                     "target exists with different content (overwrite refused): %s" % tgt_rel))
        if src_rel:
            seen_sources.setdefault(src_rel.casefold(), []).append(tgt_rel)

        row["failures"] = [{"code": c, "message": m} for c, m in failures]
        candidates.append(row)

    # duplicate targets / sources
    dup_targets = {k: v for k, v in seen_targets.items() if len(v) > 1}
    dup_sources = {k: v for k, v in seen_sources.items() if len(v) > 1}
    for key, sources in dup_targets.items():
        for row in candidates:
            if not row.get("target_rel"):
                continue
            if row["target_rel"].casefold() == key:
                if not any(f["code"] == "duplicate_target" for f in row["failures"]):
                    row["failures"].append({"code": "duplicate_target",
                                            "message": "duplicate target name among: %s" % ", ".join(str(s) for s in sources)})
    for key, targets in dup_sources.items():
        for row in candidates:
            if row.get("source_rel") and row["source_rel"].casefold() == key:
                if not any(f["code"] == "duplicate_source" for f in row["failures"]):
                    row["failures"].append({"code": "duplicate_source",
                                            "message": "source planned more than once (targets: %s)" % ", ".join(str(t) for t in targets)})

    valid, invalid = [], []
    for row in candidates:
        (invalid if row["failures"] else valid).append(row)
        for failure in row["failures"]:
            errors.append({"code": failure["code"], "item": row.get("source") or ("files[%d]" % row["index"]),
                           "message": failure["message"], "target": row.get("target")})

    file_keys = {r["path"].casefold() for r in inventory_rows if r.get("type") == "file"}
    planned_keys = {r["source_rel"].casefold() for r in candidates if r.get("source_rel")} & file_keys
    covered_keys = {r["source_rel"].casefold() for r in valid if r.get("source_rel")} & file_keys

    excluded_specs = plan.get("exclude")
    if excluded_specs is None:
        excluded_specs = []
    if not isinstance(excluded_specs, list):
        excluded_specs = [excluded_specs]
    excluded, excluded_keys = [], set()
    for pos, item in enumerate(excluded_specs):
        if isinstance(item, str):
            src, reason = item, "explicitly excluded in plan"
        elif isinstance(item, dict):
            src = item.get("source") or item.get("path")
            reason = item.get("reason") or "explicitly excluded in plan (no reason supplied)"
        else:
            warnings.append({"code": "invalid_exclude", "item": "exclude[%d]" % pos,
                             "message": "exclude item must be a string or an object"})
            continue
        if not isinstance(src, str) or not src.strip():
            warnings.append({"code": "invalid_exclude", "item": "exclude[%d]" % pos,
                             "message": "exclude item has no source path"})
            continue
        rel = nfc(src.replace("\\", "/").lstrip("./"))
        record = {"source": rel, "reason": str(reason), "status": "found"}
        if source_map.get(rel, None) is not None and source_map[rel].is_file():
            excluded_keys.add(rel.casefold())
        else:
            record["status"] = "not_found"
            warnings.append({"code": "exclude_not_found", "item": rel,
                             "message": "excluded path is not an inventoried regular file"})
        excluded.append(record)

    unplanned_files, total = [], 0
    symlinks, unreadable = [], []
    for row in inventory_rows:
        if row.get("type") == "file":
            total += 1
            key = row["path"].casefold()
            if key not in planned_keys and key not in excluded_keys:
                unplanned_files.append({"source": row["path"],
                                        "reason": "source file has no plan entry and no exclude reason"})
        elif row.get("type") == "symlink":
            symlinks.append({"path": row["path"], "target": row.get("target"),
                             "target_inside_root": row.get("target_inside_root")})
        if row.get("status") in ("unreadable", "unreadable_directory"):
            unreadable.append(row["path"])

    coverage = {
        "total": total,
        "planned": len(planned_keys),
        "covered": len(covered_keys),
        "unplanned": len(unplanned_files),
        "source_files": total,
        "unplanned_files": unplanned_files,
        "excluded": excluded,
        "excluded_count": len(excluded),
        "symlinks": symlinks,
        "unreadable": unreadable,
    }
    if unplanned_files:
        warnings.append({"code": "unplanned_files", "item": "plan",
                         "message": "%d inventoried file(s) have no plan entry (recorded as not_in_plan)"
                                    % len(unplanned_files)})

    return valid, invalid, errors, warnings, coverage


def skipped_from_invalid(invalid, stage):
    skipped = []
    for row in invalid:
        reason = "; ".join("%s: %s" % (f["code"], f["message"]) for f in row["failures"])
        skipped.append({
            "source": row.get("source"),
            "target": row.get("target"),
            "codes": [f["code"] for f in row["failures"]],
            "reason": reason,
            "stage": stage,
        })
    return skipped


# --------------------------------------------------------------------------
# commands
# --------------------------------------------------------------------------
def cmd_inventory(args):
    EXCERPT_CHARS[0] = max(200, int(getattr(args, "excerpt_chars", 1200) or 1200))
    source = Path(args.source)
    if not source.is_dir():
        raise ToolError("source directory not found: %s" % args.source)
    source = source.resolve()
    out = Path(args.out)
    if args.text_cache:
        cache_dir = Path(args.text_cache).resolve()
        if cache_dir == source or cache_dir.is_relative_to(source):
            raise ToolError("--text-cache must live outside the source tree: %s" % args.text_cache)
    entries = build_manifest(source)
    payload = {
        "tool": TOOL,
        "version": VERSION,
        "source_root": str(source),
        "summary": summarize_entries(entries),
        "entries": public_entries(entries),
        "method": {
            "type_detection": "magic bytes first, extension only as fallback",
            "text_decoding": ["utf-8-sig", "utf-8", "gb18030", "big5", "latin-1(fallback)"],
            "pdf": "pdfinfo for pages/encryption, pdftotext -layout for text",
            "paths": "Unicode NFC normalized relative posix paths",
            "symlinks": "recorded, never followed outside source root",
        },
    }
    if out.exists() and out.is_dir():
        out = out / "inventory.json"
    elif str(args.out).endswith("/"):
        out = out / "inventory.json"
    if out.resolve().is_relative_to(source):
        raise ToolError("inventory output must live outside the source tree")
    save_json(out, payload)
    # optional text cache for later dupes/search even before apply
    if args.text_cache:
        write_cache(Path(args.text_cache), entries, existing=load_cache(args.text_cache).get("files"))
    print(json.dumps({"status": "ok", "entries": len(entries),
                      "summary": payload["summary"], "out": str(out)}, ensure_ascii=False))
    return 0


def cmd_validate_plan(args):
    root = Path(args.source).resolve()
    out = Path(args.out).resolve()
    if not root.is_dir():
        raise ToolError("source directory not found: %s" % args.source)
    plan = load_plan(args.plan)
    previous = read_json(out / OPERATIONS_NAME) or {"operations": []}
    valid, invalid, errors, warnings, coverage = plan_errors_and_ops(
        root, out, plan, previous=previous)
    result = {
        "ok": not errors,
        "source_root": str(root),
        "output_root": str(out),
        "counts": {"planned": len(plan["files"]), "valid": len(valid),
                   "invalid": len(invalid), "errors": len(errors)},
        "errors": errors,
        "warnings": warnings,
        "coverage": coverage,
    }
    print(json.dumps(result, ensure_ascii=False, indent=1))
    return 0 if not errors else 1


def cmd_apply(args):
    EXCERPT_CHARS[0] = max(200, int(getattr(args, "excerpt_chars", 1200) or 1200))
    root = Path(args.source).resolve()
    out = Path(args.out).resolve()
    if not root.is_dir():
        raise ToolError("source directory not found: %s" % args.source)
    if out == root or out.is_relative_to(root) or root.is_relative_to(out):
        raise ToolError("source and output directories must not overlap")
    plan = load_plan(args.plan)
    operations_path = out / OPERATIONS_NAME
    previous = read_json(operations_path) or {"operations": []}
    entries = build_manifest(root)  # one inventory scan, reused for validation and annotation
    valid, invalid, errors, warnings, coverage = plan_errors_and_ops(
        root, out, plan, entries=entries, previous=previous)

    skipped = skipped_from_invalid(invalid, "validate-plan")
    for rec in coverage.get("unplanned_files", []):
        skipped.append({"source": rec["source"], "target": None,
                        "codes": ["not_in_plan"], "reason": rec["reason"],
                        "stage": "coverage"})
    excluded = coverage.get("excluded", [])
    if errors and not args.allow_partial:
        raise ToolError("plan validation failed (%d issue(s)); nothing was written. "
                        "Run validate-plan, fix the plan, or pass --allow-partial. First issue: %s"
                        % (len(errors), errors[0]["message"]))
    structural_codes = {"target_invalid", "target_missing_in_plan", "invalid_item",
                        "source_missing_in_plan"}
    if (not valid and errors and all(e["code"] in structural_codes for e in errors)):
        raise ToolError("plan has no valid items (%d structural issue(s)); nothing was written. "
                        "First issue: %s" % (len(errors), errors[0]["message"]))

    prev_by_key = {(nfc(r.get("source", "")), nfc(r.get("target", ""))): r
                   for r in previous.get("operations", [])}

    computed = []
    for row in valid:
        target = safe_target(out, row["target"])
        exists = target.is_file()
        action = "create"
        if exists:
            action = "reuse" if digest(target) == row["sha256"] else "conflict"
        computed.append({"row": row, "target": target, "action": action,
                         "sha256": row["sha256"], "size_bytes": row["size_bytes"]})

    if args.dry_run:
        preview = {
            "dry_run": True,
            "status": "partial" if skipped else "ok",
            "would_write": len(computed),
            "operations": [],
            "skipped": skipped,
            "excluded": excluded,
            "warnings": warnings,
            "coverage": coverage,
        }
        for item in computed:
            row = item["row"]
            preview["operations"].append({
                "source": row["source"], "target": row["target"],
                "sha256": item["sha256"], "size_bytes": item["size_bytes"],
                "action": item["action"],
                "would_overwrite": item["action"] == "conflict",
            })
        print(json.dumps(preview, ensure_ascii=False, indent=1))
        return 0

    def flush_operations():
        save_json(operations_path, {"tool": TOOL, "version": VERSION,
                                    "source_root": str(root),
                                    "operations": list(prev_by_key.values())})

    out.mkdir(parents=True, exist_ok=True)
    index_files = []
    operations = []
    failures = []
    pending_flush = 0
    for item in computed:
        row = item["row"]
        target = item["target"]
        source = Path(row.get("path_actual") or (root / Path(nfc(str(row["source"]).replace("\\", "/")))))
        if item["action"] == "conflict":
            failures.append({"source": row["source"], "target": row["target"],
                             "reason": "target content changed since validation; overwrite refused"})
            continue
        key = (nfc(str(row["source"])), nfc(str(row["target"])))
        owned_before = bool((prev_by_key.get(key) or {}).get("created"))
        created = False
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            if not target.exists():
                fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                try:
                    with os.fdopen(fd, "wb") as dst, open(source, "rb") as src:
                        shutil.copyfileobj(src, dst, 1024 * 1024)
                        dst.flush()
                        os.fsync(dst.fileno())
                    created = True
                except Exception:
                    if target.exists():
                        target.unlink()
                    raise
            actual = digest(target)
            if actual != item["sha256"]:
                raise ToolError("copy verification failed for %s" % row["target"])
        except (OSError, ToolError) as exc:
            failures.append({"source": row["source"], "target": row["target"], "reason": str(exc)})
            skipped.append({"source": row["source"], "target": row["target"],
                            "codes": ["copy_failed"], "reason": str(exc), "stage": "copy"})
            continue
        if created:
            action = "created"
        elif owned_before:
            action = "reused"
        else:
            action = "reused_external"
        op = {
            "source": row["source"],
            "target": row["target"],
            "sha256": item["sha256"],
            "size_bytes": item["size_bytes"],
            "action": action,
            "created": created or owned_before,
            "verified": True,
            "metadata": row.get("metadata") or {},
            "tags": row.get("tags") or [],
            "version_relation": row.get("version_relation"),
            "evidence": row.get("evidence"),
            "reason": row.get("reason"),
        }
        operations.append(op)
        prev_by_key[key] = op
        pending_flush += 1
        if pending_flush >= 50:
            flush_operations()
            pending_flush = 0
        index_files.append({
            "source": row["source"],
            "target": row["target"],
            "sha256": item["sha256"],
            "size_bytes": item["size_bytes"],
            "metadata": row.get("metadata") or {},
            "tags": row.get("tags") or [],
            "version_relation": row.get("version_relation"),
            "evidence": row.get("evidence"),
            "reason": row.get("reason"),
            "kind": None,
        })
    flush_operations()

    # annotate index entries with inventory facts (kind, encoding, pdf status)
    by_source = {row["path"]: row for row in entries}
    for item in index_files:
        src_row = by_source.get(nfc(item["source"]))
        if not src_row:
            continue
        item["kind"] = src_row.get("kind")
        item["encoding"] = src_row.get("encoding")
        item["encoding_confidence"] = src_row.get("encoding_confidence")
        item["text_status"] = src_row.get("text_status")
        item["pdf_status"] = src_row.get("pdf_status")
        item["pages"] = src_row.get("pages")
        item["hints"] = src_row.get("hints") or {}

    index = {
        "tool": TOOL,
        "version": VERSION,
        "source_root": str(root),
        "output_root": str(out),
        "status": "ok" if not skipped else "partial",
        "files": index_files,
        "counts": {"indexed": len(index_files), "skipped": len(skipped),
                   "unplanned": coverage.get("unplanned", 0),
                   "excluded": len(excluded)},
        "coverage": coverage,
    }
    save_json(out / INDEX_NAME, index)
    save_json(out / INVENTORY_NAME, {
        "tool": TOOL, "version": VERSION, "source_root": str(root),
        "summary": summarize_entries(entries), "entries": public_entries(entries),
    })
    save_json(out / SKIPPED_NAME, {"tool": TOOL, "version": VERSION,
                                   "skipped": skipped, "excluded": excluded,
                                   "count": len(skipped), "excluded_count": len(excluded)})
    tree = build_tree(index_files)
    save_json(out / TREE_NAME, {"tool": TOOL, "version": VERSION,
                                "root": str(out), "tree": tree,
                                "counts": {"files": len(index_files),
                                           "directories": count_dirs(tree)}})
    write_cache(out, entries)

    result = {
        "status": "ok" if not skipped and not failures else ("partial" if index_files else "blocked"),
        "indexed": len(index_files),
        "skipped": len(skipped),
        "excluded": len(excluded),
        "created_now": sum(1 for op in operations if op["action"] == "created"),
        "verified_existing": sum(1 for op in operations if op["action"] != "created"),
        "failed": len(failures),
        "warnings": warnings,
        "coverage": coverage,
        "index": str(out / INDEX_NAME),
    }
    print(json.dumps(result, ensure_ascii=False, indent=1))
    return 0 if index_files or not plan["files"] else 1


def build_tree(index_files):
    root = {"name": ".", "type": "directory", "children": [], "files": 0, "bytes": 0}
    nodes = {"": root}
    for item in index_files:
        parts = item["target"].split("/")
        parent_key = ""
        for idx, part in enumerate(parts):
            key = "/".join(parts[:idx + 1])
            if key not in nodes:
                node = {"name": part, "type": "directory", "children": [], "files": 0, "bytes": 0}
                nodes[parent_key]["children"].append(node)
                nodes[key] = node
            if idx == len(parts) - 1:
                nodes[key]["type"] = "file"
                nodes[key]["sha256"] = item["sha256"]
                nodes[key]["size_bytes"] = item["size_bytes"]
            parent_key = key
    def roll(node):
        if node["type"] == "file":
            return 1, node.get("size_bytes", 0)
        files = 0
        size = 0
        for child in node["children"]:
            f, b = roll(child)
            files += f
            size += b
        node["files"] = files
        node["bytes"] = size
        node["children"].sort(key=lambda c: (c["type"] != "directory", c["name"]))
        return files, size
    roll(root)
    return root


def count_dirs(tree):
    if tree.get("type") != "directory":
        return 0
    return 1 + sum(count_dirs(child) for child in tree.get("children", []))


# --------------------------------------------------------------------------
# relations
# --------------------------------------------------------------------------
VERSION_PATTERNS = [
    ("preprint", re.compile(r"\bpreprints?\b|\barxiv\b|\bbiorxiv\b|\bmedrxiv\b|\bnot\s+peer[-\s]?reviewed\b", re.I),
     ()),
    ("published", re.compile(r"(?<!un)\bpublished\b|\bcamera[-\s]?ready\b|\bpeer[-\s]?reviewed\b", re.I),
     ("not ", "non ", "never ")),
    ("supplementary", re.compile(r"\bsupplementary\b|\bsupporting\s+information\b", re.I), ()),
    ("correction", re.compile(r"\bcorrections?\b|\berratum\b|\bcorrigendum\b", re.I), ()),
    ("accepted_manuscript", re.compile(r"\baccepted\s+manuscript\b", re.I), ()),
]


def locate(text, offset, is_pdf):
    if is_pdf:
        page = text[:offset].count("\f") + 1
        return "page %d" % page
    line = text[:offset].count("\n") + 1
    return "line %d" % line


def snippet(text, offset, length=140):
    start = max(0, offset - 40)
    chunk = re.sub(r"\s+", " ", text[start:offset + length]).strip()
    return chunk[:length]


def find_version_evidence(text, is_pdf):
    found = {}
    for label, pattern, negations in VERSION_PATTERNS:
        for match in pattern.finditer(text):
            window = text[max(0, match.start() - 40):match.start()].casefold()
            if any(word in window for word in negations):
                continue
            found[label] = {
                "locator": locate(text, match.start(), is_pdf),
                "snippet": snippet(text, match.start()),
                "match": match.group(0),
            }
            break
    return found


def file_facts(index, cache, entry):
    text, source = entry_text(index["output_root"], entry, cache)
    is_pdf = entry.get("kind") == "pdf"
    return text, is_pdf, source


def rel_entry(entry, extra=None):
    row = {"target": entry["target"], "source": entry.get("source"),
           "sha256": entry.get("sha256"), "size_bytes": entry.get("size_bytes")}
    if extra:
        row.update(extra)
    return row


def version_rank(labels):
    order = ["published", "correction", "accepted_manuscript", "preprint", "supplementary"]
    for name in order:
        if name in labels:
            return name
    return None


def cmd_dupes(args):
    out = Path(args.out).resolve()
    index = read_json(out / INDEX_NAME)
    if not index or not index.get("files"):
        raise ToolError("index.json missing or empty; run apply first")
    index["output_root"] = index.get("output_root") or str(out)
    cache = load_cache(out)
    files = index["files"]

    # byte duplicates
    by_hash = {}
    for entry in files:
        if entry.get("sha256"):
            by_hash.setdefault(entry["sha256"], []).append(entry)

    relations = []
    for sha, members in sorted(by_hash.items()):
        if len(members) < 2:
            continue
        preferred = sorted(members, key=lambda m: canonical_key(m["target"], m.get("kind")))[0]
        others = [m for m in members if m is not preferred]
        relations.append({
            "type": "byte_identical",
            "sha256": sha,
            "size_bytes": members[0].get("size_bytes"),
            "members": [rel_entry(m) for m in members],
            "evidence": [{"locator": "sha256", "value": sha,
                          "snippet": "%d files share identical bytes" % len(members)}],
            "recommendation": {
                "keep": preferred["target"],
                "archive": [m["target"] for m in others],
                "manual_confirm": [],
                "auto_delete": False,
                "reason": "byte-identical copies; keep one canonical path and archive the rest",
            },
        })

    # DOI groups and version evidence
    facts = {}
    for entry in files:
        text, is_pdf, origin = file_facts(index, cache, entry)
        dois = []
        for match in DOI_RE.finditer(text):
            value = match.group(0).rstrip(".,;:)]}")
            if value not in [d["value"] for d in dois]:
                dois.append({"value": value,
                             "locator": locate(text, match.start(), is_pdf),
                             "snippet": snippet(text, match.start())})
        metadata_doi = (entry.get("metadata") or {}).get("doi")
        if metadata_doi and metadata_doi not in [d["value"] for d in dois]:
            dois.append({"value": metadata_doi, "locator": "plan metadata", "snippet": "plan metadata doi"})
        facts[entry["target"]] = {
            "entry": entry,
            "text": text,
            "is_pdf": is_pdf,
            "text_origin": origin,
            "dois": dois,
            "versions": find_version_evidence(text, is_pdf),
        }

    by_doi = {}
    for target, fact in facts.items():
        for doi in fact["dois"]:
            by_doi.setdefault(doi["value"].lower(), []).append((target, doi))

    version_links = []
    for doi, members in sorted(by_doi.items()):
        distinct = {target for target, _ in members}
        if len(distinct) < 2:
            continue
        hashes = {facts[t]["entry"].get("sha256") for t in distinct}
        labels = {t: set(facts[t]["versions"].keys()) for t in distinct}
        conflict = len(hashes) > 1
        related = [rel_entry(facts[t]["entry"], {
            "doi": doi,
            "version_labels": sorted(labels[t]),
            "evidence": [{"locator": facts[t]["dois"][0]["locator"] if facts[t]["dois"] else "unknown",
                          "value": doi,
                          "snippet": facts[t]["dois"][0]["snippet"] if facts[t]["dois"] else ""}]
                        + [{"locator": ev["locator"], "value": label, "snippet": ev["snippet"]}
                           for label, ev in sorted(facts[t]["versions"].items())],
        }) for t in sorted(distinct, key=lambda t: canonical_key(t, facts[t]["entry"].get("kind")))]

        if conflict:
            relations.append({
                "type": "same_doi_different_content",
                "doi": doi,
                "members": related,
                "evidence": [{"locator": m["evidence"][0]["locator"] if m["evidence"] else "unknown",
                              "value": doi, "snippet": "shared DOI %s" % doi} for m in related],
                "recommendation": {
                    "keep": None,
                    "archive": [],
                    "manual_confirm": sorted(distinct),
                    "auto_delete": False,
                    "reason": "same DOI but different bytes; confirm which version is authoritative before archiving",
                },
            })
        if conflict and any(labels[t] for t in distinct):
            ranks = {t: version_rank(labels[t]) for t in distinct}
            supplementary = [t for t in distinct if "supplementary" in labels[t]]
            ranked = [t for t in distinct if ranks[t] and t not in supplementary]
            if len(ranked) >= 2 and len({ranks[t] for t in ranked}) >= 2:
                best = sorted(ranked, key=lambda t: (["published", "correction", "accepted_manuscript", "preprint", "supplementary"].index(ranks[t]), canonical_key(t, facts[t]["entry"].get("kind"))))[0]
                roles = {ranks[t] for t in ranked}
                if supplementary:
                    roles.add("supplementary")
                version_links.append({
                    "type": "version_relation",
                    "doi": doi,
                    "subtype": "+".join(sorted(roles)),
                    "members": related,
                    "evidence": [{"locator": ev["locator"], "value": label,
                                  "snippet": "%s: %s" % (target, ev["snippet"])}
                                 for target in sorted(distinct, key=lambda t: canonical_key(t, facts[t]["entry"].get("kind")))
                                 for label, ev in sorted(facts[target]["versions"].items())],
                    "recommendation": {
                        "keep": best,
                        "archive": [t for t in ranked if t != best],
                        "keep_as_attachment": supplementary,
                        "manual_confirm": [],
                        "auto_delete": False,
                        "reason": "explicit version markers in the text; published/corrected version is preferred for citation, supplementary kept as attachment",
                    },
                })
    relations.extend(version_links)

    alias_links = find_aliases(files, facts)

    payload = {
        "tool": TOOL,
        "version": VERSION,
        "method": {
            "byte_duplicates": "sha256 over full file bytes",
            "doi_groups": "explicit DOI strings in extracted text or plan metadata",
            "version_evidence": ["preprint/arxiv", "published/camera-ready/peer-reviewed",
                                 "supplementary", "correction/erratum", "accepted manuscript"],
            "policy": "recommendations only; never delete or overwrite",
        },
        "relations": relations,
        "alias_links": alias_links,
        "stats": {
            "byte_duplicate_groups": sum(1 for r in relations if r["type"] == "byte_identical"),
            "doi_groups": sum(1 for r in relations if r["type"] == "same_doi_different_content"),
            "version_links": len(version_links),
            "alias_links": len(alias_links),
            "files_considered": len(files),
        },
        "uncertainty": [
            {"issue": "text_unavailable", "target": t,
             "detail": "no extracted text; DOI/version relations may be incomplete"}
            for t, f in facts.items() if f["text_origin"] != "cache" or not f["text"]
        ],
    }
    save_json(out / RELATIONS_NAME, payload)
    print(json.dumps({"status": "ok", "stats": payload["stats"],
                      "out": str(out / RELATIONS_NAME)}, ensure_ascii=False, indent=1))
    return 0


def canonical_key(target, kind=None):
    low = target.casefold()
    penalty = 1 if any(token in low for token in ("duplicate", "copy", "backup", "old", "final", "v2")) else 0
    mismatch = 0
    ext = Path(target).suffix.lower()
    if kind == "pdf" and ext != ".pdf":
        mismatch = 1
    elif kind == "text" and ext not in TEXT_EXTS:
        mismatch = 1
    return (penalty, mismatch, target.count("/"), low)


ALIAS_RE = re.compile(
    r"(?i)(?:\balias\b|别名)\s*[:：]?\s*[\"'“]?([^\"'”\n]+?)[\"'”]?\s*(?:->|=>|→|:|：|＝|=)\s*(\S+)")
SEE_RE = re.compile(r"(?:参见|详见)\s*[:：]?\s*[《\"'“]?([^\s\"'”》,，。;；)）]+)")


def find_aliases(files, facts):
    by_basename = {}
    for entry in files:
        for key in (Path(entry["target"]).name, Path(entry.get("source") or "").name):
            if key:
                by_basename.setdefault(nfc(key).casefold(), entry["target"])

    def resolve(pointer):
        return by_basename.get(nfc(Path(pointer).name).casefold())

    def link(alias, pointer, target, text, offset, fact, form):
        resolved = resolve(pointer)
        return {
            "alias": alias,
            "pointer": pointer,
            "resolved_target": resolved,
            "declared_in": target,
            "form": form,
            "evidence": {"locator": locate(text, offset, fact["is_pdf"]),
                         "snippet": snippet(text, offset)},
            "status": "resolved" if resolved else "unresolved",
            "auto_delete": False,
        }

    links = []
    for target, fact in sorted(facts.items()):
        text = fact["text"]
        folded = text.casefold()
        if ("alias" not in folded and "别名" not in text
                and "参见" not in text and "详见" not in text):
            continue
        seen = set()
        for match in ALIAS_RE.finditer(text):
            alias = match.group(1).strip()
            pointer = match.group(2).strip().strip("().,")
            key = (alias, pointer, match.start())
            if key in seen:
                continue
            seen.add(key)
            links.append(link(alias, pointer, target, text, match.start(), fact, "alias"))
        for match in SEE_RE.finditer(text):
            pointer = match.group(1).strip()
            key = (None, pointer, match.start())
            if key in seen:
                continue
            seen.add(key)
            links.append(link(None, pointer, target, text, match.start(), fact, "see_also"))
    return links


# --------------------------------------------------------------------------
# search
# --------------------------------------------------------------------------
def metadata_blob(entry):
    meta = entry.get("metadata") or {}
    parts = [entry.get("target", ""), entry.get("source", ""),
             " ".join(str(t) for t in entry.get("tags") or []),
             json.dumps(meta, ensure_ascii=False)]
    return "\n".join(parts)


STOPWORDS = {
    "the", "a", "an", "of", "and", "or", "to", "in", "on", "for", "with", "which",
    "what", "who", "where", "when", "how", "is", "are", "was", "were", "does", "do",
    "did", "this", "that", "these", "those", "from", "by", "as", "at", "it", "its",
    "any", "all", "file", "files", "document", "documents", "paper", "papers",
    "的", "了", "是", "在", "和", "与", "有", "哪些", "哪个", "什么", "如何",
}


def query_terms(query):
    tokens = re.findall(r"[A-Za-z0-9]+|[\u4e00-\u9fff]{2,}", nfc(query))
    out = []
    for token in tokens:
        low = token.casefold()
        if low in STOPWORDS or len(token) < 2:
            continue
        if low not in out:
            out.append(low)
    return out


def collect_texts(out, index, cache):
    """Extract every indexed file's text exactly once per search run."""
    texts = {}
    for entry in index["files"]:
        texts[entry["target"]] = entry_text(out, entry, cache)
    return texts


def search_one(index, texts, query):
    needle = nfc(query).casefold()
    hits = []
    files_matched = set()
    for entry in index["files"]:
        meta_fields = [("target", entry.get("target", "")),
                       ("source", entry.get("source", ""))]
        for key, value in (entry.get("metadata") or {}).items():
            if isinstance(value, (str, int, float)):
                meta_fields.append(("metadata." + key, str(value)))
        meta_fields.append(("tags", ", ".join(str(t) for t in entry.get("tags") or [])))
        for field, value in meta_fields:
            if needle and needle in nfc(str(value)).casefold():
                hits.append({"target": entry["target"], "field": field,
                             "locator": {"type": "metadata", "field": field},
                             "snippet": str(value)[:160]})
                files_matched.add(entry["target"])
        text, origin = texts.get(entry["target"], ("", "missing"))
        if not text:
            continue
        is_pdf = entry.get("kind") == "pdf"
        lowered = text.casefold()
        start = 0
        per_file = 0
        while per_file < 20:
            idx = lowered.find(needle, start) if needle else -1
            if idx < 0:
                break
            hits.append({
                "target": entry["target"],
                "field": "content",
                "locator": {"type": "page" if is_pdf else "line",
                            "value": (text[:idx].count("\f") + 1) if is_pdf else (text[:idx].count("\n") + 1)},
                "snippet": snippet(text, idx),
                "text_source": origin,
            })
            files_matched.add(entry["target"])
            start = idx + max(1, len(needle))
            per_file += 1
    mode = "phrase"
    if not hits and needle:
        # natural-language fallback: score files by how many distinctive query terms they contain
        terms = query_terms(query)
        docs = []
        df = {}
        for entry in index["files"]:
            text, origin = texts.get(entry["target"], ("", "missing"))
            haystack = (metadata_blob(entry) + "\n" + text).casefold()
            docs.append((entry, text, origin, haystack))
            for term in terms:
                if term in haystack:
                    df[term] = df.get(term, 0) + 1
        limit = max(1, int(len(docs) * 0.4))
        distinctive = [t for t in terms if df.get(t, 0) <= limit]
        threshold = max(1, round(0.6 * len(terms)))
        per_file_hits = []
        for entry, text, origin, haystack in docs:
            matched = [t for t in distinctive if t in haystack]
            if len(matched) < threshold:
                continue
            per_file_hits.append((entry, text, origin, matched))
        for entry, text, origin, matched in per_file_hits:
            is_pdf = entry.get("kind") == "pdf"
            idx = min([text.casefold().find(t) for t in matched if text.casefold().find(t) >= 0] or [-1])
            locator = {"type": "metadata", "field": "terms"} if idx < 0 else {
                "type": "page" if is_pdf else "line",
                "value": (text[:idx].count("\f") + 1) if is_pdf else (text[:idx].count("\n") + 1)}
            hits.append({
                "target": entry["target"],
                "field": "content" if idx >= 0 else "metadata",
                "locator": locator,
                "snippet": snippet(text, idx) if idx >= 0 else metadata_blob(entry)[:160],
                "matched_terms": matched,
                "term_coverage": round(len(matched) / max(1, len(terms)), 2),
                "text_source": origin,
            })
            files_matched.add(entry["target"])
        hits.sort(key=lambda h: (-h.get("term_coverage", 0), h["target"]))
        mode = "terms"
    result = {"query": query, "normalized": needle, "mode": mode, "count": len(hits),
              "files_matched": len(files_matched), "hits": hits,
              "answered": bool(hits)}
    if not hits:
        result["reason"] = "no phrase or distinctive-term match in metadata or extracted body text"
    return result


def load_queries(path):
    try:
        text = Path(path).read_text(encoding="utf-8")
    except OSError as exc:
        raise ToolError("cannot read queries file: %s" % exc)
    stripped = text.strip()
    if stripped.startswith("["):
        data = json.loads(stripped)
        return [str(q) for q in data]
    if stripped.startswith("{"):
        data = json.loads(stripped)
        for key in ("queries", "questions"):
            if isinstance(data.get(key), list):
                return [str(q.get("query") if isinstance(q, dict) else q) for q in data[key]]
        raise ToolError("queries JSON must contain a 'queries' or 'questions' list")
    return [line.strip() for line in text.splitlines() if line.strip()]


def cmd_search(args):
    out = Path(args.out).resolve()
    index = read_json(out / INDEX_NAME)
    if not index or not index.get("files"):
        raise ToolError("index.json missing or empty; run apply first")
    cache = load_cache(out)
    texts = collect_texts(out, index, cache)  # one extraction round for the whole run
    if args.queries_file:
        queries = load_queries(args.queries_file)
        results = [search_one(index, texts, q) for q in queries]
        payload = {
            "tool": TOOL, "version": VERSION, "output_root": str(out),
            "queries": results,
            "summary": {"queries": len(results),
                        "answered": sum(1 for r in results if r["answered"]),
                        "unanswered": [r["query"] for r in results if not r["answered"]],
                        "text_files_available": len(cache.get("files", {}))},
        }
        if cache.get("truncated_files"):
            payload["uncertainty"] = [{"issue": "text_cache_truncated",
                                       "files": cache["truncated_files"]}]
        save_json(out / QUERIES_NAME, payload)
        print(json.dumps({"status": "ok", "queries": len(results),
                          "answered": payload["summary"]["answered"],
                          "out": str(out / QUERIES_NAME)}, ensure_ascii=False))
        return 0
    if not args.query:
        raise ToolError("pass --query or --queries-file")
    print(json.dumps(search_one(index, texts, args.query), ensure_ascii=False, indent=1))
    return 0


# --------------------------------------------------------------------------
# report
# --------------------------------------------------------------------------
def contract_names(contract, depth=0):
    """Return ordered list of (name, spec) top-level contract fields across shapes."""
    if depth > 4 or contract is None:
        return []
    if isinstance(contract, str):
        try:
            return contract_names(json.loads(contract), depth + 1)
        except ValueError:
            return []
    if isinstance(contract, list):
        names = []
        for item in contract:
            if isinstance(item, str):
                names.append((item, None))
            elif isinstance(item, dict):
                if isinstance(item.get("name"), str):
                    names.append((item["name"], item))
                elif isinstance(item.get("field"), str):
                    names.append((item["field"], item))
        return names
    if isinstance(contract, dict):
        for wrapper in ("output_contract", "contract", "result_schema", "schema"):
            if wrapper in contract:
                inner = contract_names(contract[wrapper], depth + 1)
                if inner:
                    return inner
        if isinstance(contract.get("fields"), (list, dict)):
            return contract_names(contract["fields"], depth + 1)
        if isinstance(contract.get("properties"), dict):
            required = contract.get("required") or []
            names = []
            for key, spec in contract["properties"].items():
                entry = dict(spec) if isinstance(spec, dict) else {"type": spec}
                entry["required"] = key in required
                names.append((key, entry))
            return names
        if isinstance(contract.get("required"), list) and all(isinstance(n, str) for n in contract["required"]):
            return [(n, None) for n in contract["required"]]
        skip = {"type", "required", "description", "title", "$schema", "additionalProperties",
                "properties", "items", "definitions", "$defs", "examples", "version",
                "case_id", "output_contract_total"}
        names = []
        for key, spec in contract.items():
            if key in skip:
                continue
            names.append((key, spec if isinstance(spec, (dict, list, str)) else {"type": type(spec).__name__}))
        return names
    return []


ALIASES = {
    "caseid": "case_id", "id": "case_id", "case": "case_id",
    "status": "status", "runstatus": "status",
    "files": "files", "filelist": "files", "libraryfiles": "files", "documents": "files",
    "items": "files", "organizedfiles": "files", "fileinventory": "files",
    "inventory": "inventory", "inputinventory": "inventory", "libraryinventory": "inventory",
    "tree": "tree", "directorytree": "tree", "folderstructure": "tree",
    "directorystructure": "tree", "librarystructure": "tree", "structure": "tree",
    "duplicates": "duplicates", "duplicatefiles": "duplicates", "dupes": "duplicates",
    "redundantfiles": "duplicates",
    "versions": "versions", "versionrelations": "versions", "relations": "relations",
    "relationship": "relations", "versioning": "versions",
    "queries": "queries", "queryanswers": "queries", "answers": "queries",
    "qa": "queries",
    "questions": "queries", "searchresults": "queries", "questionanswers": "queries",
    "changes": "changes", "changelog": "changes", "operations": "changes",
    "operationlog": "changes", "log": "changes", "audit": "changes", "actions": "changes",
    "uncertainty": "uncertainty", "uncertainties": "uncertainty",
    "limitations": "uncertainty", "notes": "uncertainty", "openquestions": "uncertainty",
    "summary": "summary", "overview": "summary", "abstract": "summary",
    "skipped": "skipped", "failures": "skipped", "errors": "skipped",
    "excluded": "skipped", "unprocessed": "skipped",
    "metadata": "metadata", "sourcemetadata": "metadata", "bibliographicdata": "metadata",
    "classification": "files", "organized": "files", "organization": "summary",
    "duplicategroup": "duplicates", "versiongroup": "versions",
    "sources": "sources", "provenance": "sources", "sourceversions": "sources",
    "permissions": "permissions", "access": "permissions",
    "hashes": "hashes", "checksums": "hashes", "sha256": "hashes",
}


def normalize_field(name):
    low = re.sub(r"[^a-z0-9]", "", nfc(name).casefold())
    if low.endswith("ies"):
        low = low[:-3] + "y"
    elif low.endswith("s") and low not in ("status", "hashes"):
        low = low[:-1]
    return low


def resolve_field(name, model):
    norm = normalize_field(name)
    target = ALIASES.get(norm) or ALIASES.get(norm + "s")
    if target is None:
        for alias, key in ALIASES.items():
            if norm and (norm in alias or alias in norm) and len(norm) >= 4:
                target = key
                break
    if target is None:
        return None, "unrecognized contract field; no verified mapping"
    return model.get(target), None


def cmd_report(args):
    out = Path(args.out).resolve()
    case_path = Path(args.case) if args.case else None
    case = None
    if case_path and case_path.exists():
        case = read_json(case_path)
        if case is None:
            raise ToolError("case file is empty: %s" % case_path)
    elif case_path and not case_path.exists():
        raise ToolError("case file not found: %s" % case_path)

    contract = None
    case_id = args.case_id
    if isinstance(case, list):
        contract = case
        case = None
    if isinstance(case, dict):
        case_id = case_id or case.get("case_id") or case.get("id")
        contract = case.get("output_contract") or case.get("outputContract") or case.get("contract")
        if contract is None and ("properties" in case or "fields" in case):
            contract = case
    if args.contract:
        contract = read_json(args.contract)
        if contract is None:
            raise ToolError("contract file not found: %s" % args.contract)
    names = contract_names(contract)
    if args.fields:
        names = [(n.strip(), None) for n in args.fields.split(",") if n.strip()]
    contract_missing = False
    if not names:
        contract_missing = True
        names = [("case_id", {"type": "string"}), ("status", {"type": "string"}),
                 ("files", {"type": "array"})]
        notes_default = "case output_contract unavailable; emitted the generic schema and flagged uncertainty"
    else:
        notes_default = None

    index = read_json(out / INDEX_NAME)
    operations = read_json(out / OPERATIONS_NAME) or {"operations": []}
    relations = read_json(out / RELATIONS_NAME) or {"relations": [], "alias_links": []}
    try:
        queries = read_json(out / QUERIES_NAME)
    except ToolError as exc:
        queries = None
        query_error = str(exc)
    else:
        query_error = None
    skipped_doc = read_json(out / SKIPPED_NAME) or {"skipped": []}
    inventory = read_json(out / INVENTORY_NAME) or {"entries": []}
    tree_doc = read_json(out / TREE_NAME)
    if tree_doc is None and index:
        tree_doc = {"tree": build_tree(index.get("files", []))}

    files = (index or {}).get("files", [])
    skipped = skipped_doc.get("skipped", [])
    excluded = skipped_doc.get("excluded", [])
    inventory_entries = inventory.get("entries", [])
    query_results = (queries or {}).get("queries", [])
    unanswered = [{"query": q.get("query"), "reason": q.get("reason") or "no evidence found"}
                  for q in query_results if not q.get("answered")]
    coverage = (index or {}).get("coverage")
    if coverage is None and index:
        total = sum(1 for r in inventory_entries if r.get("type") == "file")
        coverage = {"total": total, "planned": len(files), "covered": len(files),
                    "unplanned": max(0, total - len(files)), "unplanned_files": [],
                    "excluded": []}
    meta_by_source = {}
    for entry in files:
        meta_by_source[nfc(entry.get("source") or "")] = entry.get("metadata") or {}
    uncertain = []

    for row in inventory_entries:
        if row.get("status") in ("unreadable", "unreadable_directory"):
            uncertain.append({"item": row.get("path"), "issue": "unreadable",
                              "detail": row.get("error"), "action": "reported, not processed"})
        if row.get("pdf_status") in ("not_a_pdf", "encrypted", "no_text_layer", "pdf_error"):
            uncertain.append({"item": row.get("path"), "issue": "pdf_" + row["pdf_status"],
                              "detail": row.get("error"), "action": "recorded; no text trusted"})
        if row.get("encoding_fallback"):
            uncertain.append({"item": row.get("path"), "issue": "encoding_fallback",
                              "detail": "decoded as %s (confidence %s)"
                                        % (row.get("encoding"), row.get("encoding_confidence")),
                              "action": "verify manually"})
        if row.get("type") == "symlink":
            uncertain.append({"item": row.get("path"), "issue": "symlink_not_copied",
                              "detail": "link target %s (inside_root=%s)"
                                        % (row.get("target"), row.get("target_inside_root")),
                              "action": "plan the real file when authorized"})
        if row.get("type") == "file" and row.get("status") == "ok":
            hints = row.get("hints") or {}
            planned_meta = meta_by_source.get(nfc(row.get("path") or "")) or {}
            if not (planned_meta.get("title") or hints.get("title")):
                uncertain.append({"item": row.get("path"), "issue": "metadata_incomplete",
                                  "detail": "no explicit title in plan metadata, filename or text",
                                  "action": "left as null/unknown; never fabricated"})
    for row in skipped:
        uncertain.append({"item": row.get("source"), "issue": "skipped_" + ",".join(row.get("codes") or []),
                          "detail": row.get("reason"), "action": "excluded from output; see skipped"})
    for link in relations.get("alias_links", []):
        if link.get("status") != "resolved":
            uncertain.append({"item": link.get("declared_in"), "issue": "alias_unresolved",
                              "detail": link.get("pointer"), "action": "manual confirmation"})
    cache = load_cache(out)
    if cache.get("truncated_files"):
        uncertain.append({"item": "text cache", "issue": "text_truncated",
                          "detail": ", ".join(cache["truncated_files"]),
                          "action": "search/relation coverage reduced"})
    if query_error:
        uncertain.append({"item": "queries", "issue": "queries_unreadable",
                          "detail": query_error, "action": "rerun search --queries-file"})
    if queries is None:
        uncertain.append({"item": "queries", "issue": "no_queries_run",
                          "detail": "no readable queries.json found", "action": "run search --queries-file"})
    if unanswered:
        uncertain.append({"item": "queries", "issue": "unanswered_questions",
                          "detail": "%d question(s) have no matching evidence: %s"
                                    % (len(unanswered), "; ".join(str(u["query"]) for u in unanswered)),
                          "action": "report the evidence as absent; do not guess"})
    if contract_missing:
        uncertain.append({"item": "output_contract", "issue": "contract_missing_or_unparseable",
                          "detail": "case output_contract was missing, unreadable or yielded no field names",
                          "action": "emitted generic case_id/status/files; status downgraded to partial"})
    if coverage and coverage.get("unplanned"):
        uncertain.append({"item": "coverage", "issue": "unplanned_source_files",
                          "detail": "%d source file(s) are not covered by the plan: %s"
                                    % (coverage["unplanned"],
                                       "; ".join(r.get("source") or "" for r in coverage.get("unplanned_files", []))),
                          "action": "listed as not_in_plan; add plan entries or an explicit exclude reason"})

    status = "ok"
    if not files:
        status = "blocked"
    elif skipped or uncertain:
        status = "partial"

    changes = [{
        "source": op.get("source"), "target": op.get("target"),
        "action": op.get("action"), "sha256": op.get("sha256"),
        "verified": op.get("verified"),
    } for op in operations.get("operations", [])]

    permissions = {}
    for row in inventory_entries:
        if row.get("mode"):
            permissions[row.get("path")] = row["mode"]

    model = {
        "case_id": case_id,
        "status": status,
        "files": files,
        "inventory": {
            "source_root": inventory.get("source_root"),
            "summary": inventory.get("summary"),
            "entries": inventory_entries,
        },
        "tree": (tree_doc or {}).get("tree"),
        "duplicates": [r for r in relations.get("relations", []) if r.get("type") == "byte_identical"],
        "versions": [r for r in relations.get("relations", []) if r.get("type") != "byte_identical"],
        "relations": relations.get("relations", []),
        "queries": query_results,
        "unanswered": unanswered,
        "changes": changes,
        "skipped": skipped,
        "excluded": excluded,
        "coverage": coverage,
        "uncertainty": uncertain,
        "summary": {
            "indexed_files": len(files),
            "skipped": len(skipped),
            "excluded": len(excluded),
            "unplanned": (coverage or {}).get("unplanned", 0),
            "unanswered_queries": len(unanswered),
            "byte_duplicate_groups": sum(1 for r in relations.get("relations", []) if r.get("type") == "byte_identical"),
            "version_relations": sum(1 for r in relations.get("relations", []) if r.get("type") != "byte_identical"),
            "queries_answered": sum(1 for q in query_results if q.get("answered")),
            "output_root": str(out),
        },
        "metadata": {entry["target"]: entry.get("metadata", {}) for entry in files},
        "sources": [{"target": entry["target"], "source": entry["source"],
                     "sha256": entry.get("sha256")} for entry in files],
        "hashes": {entry["target"]: entry.get("sha256") for entry in files},
        "permissions": permissions or None,
    }

    result = {}
    field_notes = {}
    missing = []
    for name, spec in names:
        value, note = resolve_field(name, model)
        spec_type = None
        if isinstance(spec, dict):
            spec_type = spec.get("type")
        elif isinstance(spec, str) and spec in ("array", "object", "string", "number", "boolean"):
            spec_type = spec
        if value is not None:
            if spec_type == "array" and isinstance(value, dict):
                value = [{"key": k, "value": v} for k, v in value.items()]
                note = "converted an object into a key/value array to honour the declared type"
            elif spec_type == "object" and isinstance(value, list):
                value = {"items": value, "count": len(value)}
                note = "wrapped an array in an object to honour the declared type"
        if note is None and value is None and normalize_field(name) in ALIASES:
            note = "no verified data available for this field in the current run"
        if note is None and value is None and normalize_field(name) not in ALIASES:
            note = "contract field name not mapped; left null instead of guessing"
        if value is None and note:
            field_notes[name] = note
            missing.append(name)
        elif note:
            field_notes[name] = note
        result[name] = value

    # structural evidence is always present, even if not named by the contract
    for key in ("case_id", "status", "files", "tree", "duplicates", "versions",
                "relations", "changes", "queries", "unanswered", "coverage", "excluded",
                "uncertainty", "skipped", "summary", "permissions"):
        result.setdefault(key, model.get(key))
    result["tool"] = {"name": TOOL, "version": VERSION}
    result["field_notes"] = field_notes
    if notes_default:
        result["field_notes"]["_contract"] = notes_default
    if missing:
        status = "blocked" if not files else "partial"
        result["status"] = status
    if args.result:
        result_path = Path(args.result)
    else:
        result_path = out.parent / "result.json"
    save_json(result_path, result)
    print(json.dumps({"status": status, "result": str(result_path),
                      "contract_fields": [n for n, _ in names],
                      "missing_or_unmapped": missing,
                      "files_indexed": len(files)}, ensure_ascii=False, indent=1))
    return 0 if files else 1


# --------------------------------------------------------------------------
# check
# --------------------------------------------------------------------------
def cmd_check(args):
    out = Path(args.out).resolve()
    problems = []
    warnings = []
    index = read_json(out / INDEX_NAME)
    if index is None:
        problems.append("missing index.json")
        index = {"files": []}
    files = index.get("files", [])
    indexed_targets = set()
    for entry in files:
        target = out / entry["target"]
        indexed_targets.add(entry["target"])
        if not target.is_file():
            problems.append("indexed file missing on disk: %s" % entry["target"])
            continue
        if not entry.get("sha256"):
            problems.append("indexed file has no sha256: %s" % entry["target"])
            continue
        if digest(target) != entry["sha256"]:
            problems.append("hash mismatch on disk: %s" % entry["target"])
        if entry.get("size_bytes") is not None and target.stat().st_size != entry["size_bytes"]:
            problems.append("size mismatch on disk: %s" % entry["target"])
    for path in out.rglob("*"):
        if not path.is_file():
            continue
        rel = posix_rel(path, out)
        if rel.split("/")[0] in INTERNAL_TOP or rel.startswith(CACHE_DIR + "/"):
            continue
        if rel not in indexed_targets:
            problems.append("unindexed file in output library: %s" % rel)
    skipped_doc = read_json(out / SKIPPED_NAME) or {"skipped": []}
    for row in skipped_doc.get("skipped", []):
        if not str(row.get("reason") or "").strip():
            problems.append("skipped entry without reason: %s" % row.get("source"))
    queries_path = out / QUERIES_NAME
    if queries_path.exists():
        try:
            query_doc = read_json(queries_path)
        except ToolError as exc:
            problems.append("queries.json unreadable: %s" % exc)
        else:
            if not isinstance(query_doc, dict) or not isinstance(query_doc.get("queries"), list):
                problems.append("queries.json malformed: expected an object with a 'queries' list")
    result = None
    if args.result:
        result_path = Path(args.result)
        result = read_json(result_path)
        if result is None:
            problems.append("result.json missing or unreadable: %s" % result_path)
        else:
            if not result.get("case_id"):
                problems.append("result.json missing case_id")
            if result.get("status") not in ("ok", "partial", "blocked"):
                problems.append("result.json status must be ok/partial/blocked")
    if args.case:
        try:
            case = read_json(args.case)
        except ToolError as exc:
            problems.append("case file unreadable: %s" % exc)
            case = None
        contract = None
        if isinstance(case, dict):
            contract = case.get("output_contract") or case.get("contract")
            if contract is None and ("properties" in case or "fields" in case):
                contract = case
        elif isinstance(case, list):
            contract = case
        names = [n for n, _ in contract_names(contract)]
        if result and names:
            for name in names:
                if name not in result:
                    problems.append("result.json missing contract field: %s" % name)
    if args.require_relations and not (out / RELATIONS_NAME).exists():
        problems.append("relations.json missing (dupes not run)")
    if not files:
        problems.append("index contains no files")
    report = {
        "ok": not problems,
        "output_root": str(out),
        "indexed_files": len(files),
        "checked_targets": len(indexed_targets),
        "problems": problems,
        "warnings": warnings,
    }
    if args.write:
        save_json(out / CHECK_NAME, report)
    print(json.dumps(report, ensure_ascii=False, indent=1))
    return 0 if report["ok"] else 1


# --------------------------------------------------------------------------
# rollback
# --------------------------------------------------------------------------
def cmd_rollback(args):
    out = Path(args.out).resolve()
    log = read_json(out / OPERATIONS_NAME)
    if log is None:
        raise ToolError("operations.json not found in %s" % out)
    results = []
    for op in reversed(log.get("operations", [])):
        target_name = op.get("target")
        state = "not_owned"
        try:
            target = safe_target(out, target_name)
        except ToolError as exc:
            results.append({"target": target_name, "status": "invalid_target", "detail": str(exc)})
            continue
        if op.get("created") and target.is_file():
            if digest(target) == op.get("sha256"):
                target.unlink()
                state = "removed"
                parent = target.parent
                while parent != out and parent.is_dir():
                    try:
                        parent.rmdir()
                    except OSError:
                        break
                    parent = parent.parent
            else:
                state = "modified_preserved"
        elif op.get("created"):
            state = "already_absent"
        else:
            if target.is_file() and digest(target) == op.get("sha256"):
                state = "preserved_reused_copy"
            else:
                state = "modified_preserved"
        results.append({"target": target_name, "status": state, "sha256": op.get("sha256")})
    payload = {"tool": TOOL, "version": VERSION, "rollback": results,
               "summary": {s: sum(1 for r in results if r["status"] == s)
                           for s in sorted({r["status"] for r in results})}}
    save_json(out / ROLLBACK_NAME, payload)
    print(json.dumps(payload["summary"], ensure_ascii=False))
    return 0


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------
def build_parser():
    parser = argparse.ArgumentParser(prog=TOOL, description="Evidence-first research library organizer")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("inventory", help="scan source tree and classify real file types")
    p.add_argument("--source", required=True)
    p.add_argument("--out", required=True, help="inventory.json path or directory")
    p.add_argument("--text-cache", help="optional workspace for extracted text cache")
    p.add_argument("--excerpt-chars", type=int, default=1200,
                   help="characters of text kept in inventory excerpts (default 1200)")
    p.set_defaults(func=cmd_inventory)

    p = sub.add_parser("validate-plan", help="validate plan.json without writing")
    p.add_argument("--source", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--plan", required=True)
    p.set_defaults(func=cmd_validate_plan)

    p = sub.add_parser("apply", help="copy planned files into the output library")
    p.add_argument("--source", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--plan", required=True)
    p.add_argument("--allow-partial", action="store_true",
                   help="skip invalid/missing/unreadable sources and record them in skipped.json")
    p.add_argument("--dry-run", action="store_true", help="show operations without writing")
    p.add_argument("--excerpt-chars", type=int, default=1200,
                   help="characters of text kept in inventory excerpts (default 1200)")
    p.set_defaults(func=cmd_apply)

    p = sub.add_parser("dupes", help="detect byte duplicates, shared DOIs and version evidence")
    p.add_argument("--out", required=True)
    p.set_defaults(func=cmd_dupes)

    p = sub.add_parser("search", help="search metadata and extracted body text")
    p.add_argument("--out", required=True)
    p.add_argument("--query")
    p.add_argument("--queries-file")
    p.set_defaults(func=cmd_search)

    p = sub.add_parser("report", help="assemble result.json from the case output_contract")
    p.add_argument("--out", required=True)
    p.add_argument("--case", help="path to /input/case.json")
    p.add_argument("--case-id")
    p.add_argument("--contract", help="optional standalone contract JSON")
    p.add_argument("--fields", help="comma-separated field names, overrides the contract")
    p.add_argument("--result", help="result.json path (default: sibling of --out)")
    p.set_defaults(func=cmd_report)

    p = sub.add_parser("check", help="self-check output library and result.json")
    p.add_argument("--out", required=True)
    p.add_argument("--result")
    p.add_argument("--case")
    p.add_argument("--require-relations", action="store_true")
    p.add_argument("--write", action="store_true", help="also write check.json")
    p.set_defaults(func=cmd_check)

    p = sub.add_parser("rollback", help="remove only unchanged copies created by this tool")
    p.add_argument("--out", required=True)
    p.set_defaults(func=cmd_rollback)
    return parser


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except ToolError as exc:
        print("error: %s" % exc, file=sys.stderr)
        return 1
    except BrokenPipeError:
        return 0
    except KeyboardInterrupt:
        print("error: interrupted", file=sys.stderr)
        return 130


if __name__ == "__main__":
    sys.exit(main())
