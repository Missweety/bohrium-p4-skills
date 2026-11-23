#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""locate.py -- 章节树、句级切分、题注与编号定位。

所有定位都能被第二个人复核：section（1 / 2.1 / §A）、paragraph_id（P0001，
文档顺序 1-based）、sentence_index、char_start/char_end、quote（逐字子串）。
"""
from __future__ import annotations

import re

_CN_NUM = "一二三四五六七八九十百0-9１-９"

# 顺序有意义：先匹配最深层，再 1 级，最后"1. xxx"（且不能是 1.1）
HEAD_PATTERNS = [
    (1, re.compile(r"^第\s*([%s]+)\s*章\b" % _CN_NUM)),
    (1, re.compile(r"^(?:Part|PART)\s+([IVXLC0-9]+)\b")),
    (3, re.compile(r"^([0-9]{1,2}\.[0-9]{1,2}\.[0-9]{1,2})\s+\S")),
    (2, re.compile(r"^([0-9]{1,2}\.[0-9]{1,2})\s+\S")),
    (2, re.compile(r"^([0-9]{1,2}\.[0-9]{1,2})\s*[、]")),
    (1, re.compile(r"^([0-9]{1,2})\s*[、.]\s*(?![0-9])\S")),
]
CAPTION_RE = re.compile(r"^\s*(图|表|Fig\.?|Figure|Table)\s*([0-9]+(?:\s*[-–—.]\s*[0-9]+)?)")
SENT_END = "。！？!?；;"
_CLOSE = "”’\"')）]】」"


def style_level(p):
    s = (p.get("style") or "").lower()
    m = re.search(r"(?:heading|标题)\s*([1-9])", s)
    if m:
        return int(m.group(1))
    if "title" in s:
        return 1
    if "subtitle" in s:
        return 2
    return 0


def heading_number(text):
    t = text.strip()
    for lvl, pat in HEAD_PATTERNS:
        m = pat.match(t)
        if m:
            return lvl, m.group(1).strip()
    return 0, None


def is_caption(p):
    return (bool(re.search(r"(?:caption|题注)", (p.get("style") or "").lower()))
            or bool(CAPTION_RE.match(p["text"])))


def caption_info(p):
    m = CAPTION_RE.match(p["text"])
    if not m:
        return None
    kind = "figure" if m.group(1).lower().startswith(("图", "fig")) else "table"
    num = re.sub(r"\s*[-–—.]\s*", "-", m.group(2))
    return {"kind": kind, "number": num,
            "chapter_prefix": num.split("-")[0] if "-" in num else None,
            "label": m.group(0).strip()}


def assign_sections(paragraphs):
    """就地写 section / section_title / is_heading / heading_level，返回章节列表。"""
    sections = [{"key": "§0", "title": "（前置）", "level": 0, "start_index": 0}]
    current = sections[0]
    for p in paragraphs:
        lvl = style_level(p)
        num = None
        if not lvl:
            hlvl, hnum = heading_number(p["text"])
            if hlvl and len(p["text"]) <= 80 and not p["text"].rstrip().endswith(SENT_END):
                lvl, num = hlvl, hnum
        elif p["text"].strip():
            num = heading_number(p["text"])[1]
        if lvl:
            key = num or ("§%s" % _alpha(len(sections)))
            p["is_heading"] = True
            p["heading_level"] = lvl
            p["section"] = key
            p["section_title"] = p["text"].strip()
            current = {"key": key, "title": p["text"].strip(), "level": lvl,
                       "start_index": p["index"]}
            sections.append(current)
            continue
        p["is_heading"] = False
        p["heading_level"] = 0
        p["section"] = current["key"]
        p["section_title"] = current["title"]
    return sections


def _alpha(n):
    out = ""
    n = max(1, n)
    while n:
        n, r = divmod(n - 1, 26)
        out = chr(65 + r) + out
    return out


def sentences(text):
    """[(start,end,text)]；中文句末与英文 ". " 切分，引号内不切。"""
    out, start, i, n = [], 0, 0, len(text)
    while i < n:
        ch = text[i]
        cut = ch in SENT_END
        if not cut and ch == "." and (i + 1 >= n or text[i + 1] in " \t\n"):
            cut = not (text[i - 1].isdigit() if i else False)
        if cut:
            j = i + 1
            while j < n and text[j] in _CLOSE:
                j += 1
            seg = text[start:j].strip()
            if seg:
                lead = len(text[start:j]) - len(text[start:j].lstrip())
                out.append((start + lead, start + lead + len(seg), seg))
            start, i = j, j
            continue
        i += 1
    tail = text[start:].strip()
    if tail:
        lead = len(text[start:]) - len(text[start:].lstrip())
        out.append((start + lead, start + lead + len(tail), tail))
    return out


def sentence_at(text, offset):
    sents = sentences(text)
    for k, (a, b, q) in enumerate(sents):
        if a <= offset < b:
            return k, (a, b, q)
    return (len(sents) - 1, sents[-1]) if sents else (0, (0, 0, text))
