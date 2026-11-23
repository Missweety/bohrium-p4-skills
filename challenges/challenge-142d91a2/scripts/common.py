#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""common.py - shared helpers for the research-proposal skill.

Pure Python 3 standard library. No network, no third-party imports.
Import path: the entry scripts add their own directory to sys.path, so the
package works from any current working directory (for example /app while the
Skill is installed at /skills/weekly-skill).
"""
from __future__ import annotations

import json
import os
import re
import unicodedata

SKILL_NAME = "research-proposal-plan"
SKILL_VERSION = "2.0.0"
ANCHOR_HELP = "S1#p1.3 = 文件 S1 第 1 页第 3 段；case.json:<key> = 案例字段；无分页材料统一写作 p1"

_TYPO_MAP = {
    "\u2018": "'", "\u2019": "'", "\u201c": '"', "\u201d": '"',
    "\u2013": "-", "\u2014": "-", "\u2212": "-", "\u00a0": " ",
    "\u3000": " ",
}

META_CONTRACT_KEYS = {
    "description", "desc", "note", "notes", "_note", "version", "format",
    "schema", "type", "title_zh", "comment",
}
CONTRACT_CONTAINERS = {
    "required", "fields", "properties", "outputs", "deliverables",
    "required_fields", "keys", "items",
}


def ensure_dir(path):
    if path:
        os.makedirs(path, exist_ok=True)
    return path


def norm_ws(text):
    """Collapse all whitespace (including non-breaking spaces) to one space."""
    return re.sub(r"\s+", " ", (text or "")).strip()


def canon(text):
    """Normalise typography, drop all whitespace, lower-case for verbatim checks."""
    s = text or ""
    for k, v in _TYPO_MAP.items():
        s = s.replace(k, v)
    return re.sub(r"\s+", "", s).lower()


def alnum(text):
    """Keep only letters, digits and CJK; used as a tolerant fallback."""
    return re.sub(r"[^0-9A-Za-z\u4e00-\u9fff]", "", text or "")


def quote_in(quote, text):
    """True when `quote` can be found verbatim in `text` (typography tolerant).

    A quote may use an ellipsis to join several excerpts. Every non-trivial
    segment must then be present in the same paragraph.
    """
    q = norm_ws(quote)
    if not q or not text:
        return False
    if canon(q) and canon(q) in canon(text):
        return True
    parts = [p.strip(" .;:,\u2026") for p in re.split(r"\u2026|\.\.\.", q)]
    parts = [p for p in parts if len(canon(p)) >= 8]
    if len(parts) >= 2 and all(canon(p) in canon(text) for p in parts):
        return True
    aq, at = alnum(q), alnum(text)
    return bool(aq) and len(aq) >= 6 and aq in at


def load_json(path, default=None):
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:
        return default


def write_json(path, obj):
    ensure_dir(os.path.dirname(os.path.abspath(path)))
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(obj, fh, ensure_ascii=False, indent=2)
    return path


def read_text(path, limit=None):
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            return fh.read() if limit is None else fh.read(limit)
    except OSError:
        return ""


def flatten_contract(contract):
    """Return an ordered, de-duplicated list of declared field names.

    Accepts every shape seen in the wild:
      - ["proposal_md", "proposal_docx"]
      - {"required": ["proposal_md", ...]}
      - {"fields": {"proposal_md": "...", "risks": "..."}}
      - {"proposal_md": "markdown", "status": "enum"}   (field -> spec)
      - {"type": "object", "properties": {...}}
    """
    out = []

    def add(name):
        if isinstance(name, str):
            name = name.strip()
            if name and name not in out:
                out.append(name)

    def walk(node):
        if node is None:
            return
        if isinstance(node, str):
            add(node)
            return
        if isinstance(node, (list, tuple)):
            for item in node:
                walk(item)
            return
        if isinstance(node, dict):
            for key in CONTRACT_CONTAINERS:
                if key in node:
                    walk(node[key])
            for key, value in node.items():
                if key in META_CONTRACT_KEYS or key in CONTRACT_CONTAINERS:
                    continue
                add(key)
                if isinstance(value, (dict, list)) and not isinstance(value, str):
                    # nested schema: keep the parent key, do not leak spec text
                    pass
            return

    walk(contract)
    return out


def contract_declaration(case):
    """Best-effort normalisation of case.json output_contract."""
    if not isinstance(case, dict):
        return [], None
    raw = case.get("output_contract")
    if raw is None:
        # tolerate a couple of alternate spellings used by some case packs
        for key in ("outputContract", "contract", "required_outputs"):
            if key in case:
                raw = case.get(key)
                break
    return flatten_contract(raw), raw


def case_id_of(case, input_dir=None):
    if isinstance(case, dict):
        for key in ("case_id", "id", "task_id", "name"):
            value = case.get(key)
            if isinstance(value, (str, int)) and str(value).strip():
                return str(value).strip()
    if input_dir:
        base = os.path.basename(os.path.abspath(input_dir))
        if base:
            return base
    return "case"


def number_tokens(text):
    """ASCII numeric tokens with their normalised value (commas removed)."""
    tokens = []
    for match in re.finditer(r"(?<![A-Za-z0-9_])(\d[\d,]*(?:\.\d+)?)(?![\d])", text or ""):
        raw = match.group(1)
        tokens.append({"raw": raw, "value": raw.replace(",", ""),
                       "start": match.start(1), "end": match.end(1)})
    return tokens


def collect_numbers(*texts):
    found = set()
    for text in texts:
        for tok in number_tokens(text if isinstance(text, str) else json.dumps(text, ensure_ascii=False)):
            found.add(tok["value"])
    return found


def cjk_chars(text):
    return sum(1 for ch in (text or "") if "\u4e00" <= ch <= "\u9fff")


def word_stats(text):
    cjk = cjk_chars(text)
    latin = len(re.findall(r"[A-Za-z0-9]+(?:[-'][A-Za-z0-9]+)*", re.sub(r"[\u4e00-\u9fff]", " ", text or "")))
    return cjk, latin, cjk + latin


def safe_text(value):
    """Flatten an arbitrary plan value into readable text without inventing内容."""
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (list, tuple)):
        return "；".join(safe_text(v) for v in value if safe_text(v))
    if isinstance(value, dict):
        parts = []
        for key, val in value.items():
            txt = safe_text(val)
            if txt:
                parts.append("%s: %s" % (key, txt))
        return "；".join(parts)
    return str(value)


def truncated(text, limit=240):
    text = norm_ws(text)
    if len(text) <= limit:
        return text
    return text[:limit].rstrip() + "\u2026"


def relative_to(path, root):
    try:
        return os.path.relpath(path, root)
    except ValueError:
        return os.path.basename(path)


def first_existing(paths):
    for path in paths:
        if path and os.path.isfile(path):
            return path
    return None


def article_text(obj):
    """Deterministic JSON encoding used for number collection."""
    try:
        return json.dumps(obj, ensure_ascii=False, sort_keys=True)
    except TypeError:
        return str(obj)


def nfkc(text):
    return unicodedata.normalize("NFKC", text or "")
