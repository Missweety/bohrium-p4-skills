#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""citations.py -- 正文引用与参考文献表同步。

处理"新增/删除/重排引用"后的编号更新：
    1. 抽取正文 [n] / [n,m] / [n-m] 引用与参考文献表条目；
    2. 按正文首次出现顺序重排编号，得到 old->new 映射；
    3. 正文引用用 Word 修订标记改写（可逐条接受/拒绝）；
    4. 参考文献条目的前导编号同步改写，并按新编号重排条目顺序；
    5. 输出 citation_map（old/new/首现段落），供人工核对。

不改动任何文献的著录内容（作者、题名、年份），只改编号与顺序。
"""
from __future__ import annotations

import re

import track_changes

CITE_IN_TEXT = re.compile(r"[\[［]\s*([0-9][0-9,，、\-–—\s]*)\s*[\]］]")
CITE_ENTRY = re.compile(r"^\s*[\[［]?\s*([0-9]{1,3})\s*[\]］.)）]\s*")


def _expand(raw):
    out = []
    for part in re.split(r"[,，、]", raw):
        part = part.strip()
        m = re.fullmatch(r"([0-9]+)\s*[-–—]\s*([0-9]+)", part)
        if m and 0 <= int(m.group(2)) - int(m.group(1)) <= 30:
            out.extend(range(int(m.group(1)), int(m.group(2)) + 1))
        elif re.fullmatch(r"[0-9]+", part):
            out.append(int(part))
    return out


def _is_ref_section(p):
    return bool(re.search(r"参考文献|引用文献|references",
                          (p.get("section_title") or "") + " " + (p.get("section") or ""), re.I))


def collect(paragraphs):
    in_text, entries, ref_pids = [], [], set()
    for p in paragraphs:
        if p.get("is_heading"):
            continue
        if _is_ref_section(p):
            m = CITE_ENTRY.match(p["text"])
            if m:
                entries.append({"number": int(m.group(1)), "paragraph_id": p["id"],
                                "quote": m.group(0).strip(), "text": p["text"].strip()[:160]})
                ref_pids.add(p["id"])
            continue
        if p.get("in_table"):
            continue
        for m in CITE_IN_TEXT.finditer(p["text"]):
            in_text.append({"numbers": _expand(m.group(1)), "token": m.group(0).strip(),
                            "paragraph_id": p["id"], "section": p.get("section"),
                            "start": m.start(), "end": m.end()})
    return {"in_text": in_text, "entries": entries}


def build_map(collected):
    """按正文首次出现顺序给出 old->new；未在正文出现的条目排在其后。"""
    order = []
    for c in collected["in_text"]:
        for n in c["numbers"]:
            if n not in order:
                order.append(n)
    for e in sorted(collected["entries"], key=lambda x: x["number"]):
        if e["number"] not in order:
            order.append(e["number"])
    mapping = {old: i + 1 for i, old in enumerate(order)}
    first_seen = {}
    for c in collected["in_text"]:
        for n in c["numbers"]:
            first_seen.setdefault(n, c["paragraph_id"])
    changes = [{"old": old, "new": mapping[old],
                "first_paragraph": first_seen.get(old),
                "changed": mapping[old] != old}
               for old in order]
    return mapping, changes


def renumbered_token(token, mapping):
    raw = CITE_IN_TEXT.match(token).group(1)
    nums = _expand(raw)
    new = [str(mapping.get(n, n)) for n in nums]
    # 连续段用 - 折叠，非连续用逗号
    parts, i = [], 0
    while i < len(new):
        j = i
        while j + 1 < len(new) and int(new[j + 1]) == int(new[j]) + 1:
            j += 1
        parts.append(new[i] if j == i else "%s-%s" % (new[i], new[j]))
        i = j + 1
    body = ",".join(parts)
    return ("[" + body + "]") if token.startswith("[") else ("［" + body + "］")


def apply(doc, collected, mapping, ids, author, date, prefix=""):
    """改写正文与条目编号（带修订标记），并按新编号重排条目。返回变更清单。"""
    by_id = {p["id"]: p for p in doc["paragraphs"]}
    applied, skipped = [], []

    for c in collected["in_text"]:
        new_token = renumbered_token(c["token"], mapping)
        if new_token == c["token"]:
            continue
        p = by_id.get(c["paragraph_id"])
        res = track_changes.replace_quote(p, c["token"], new_token, ids, author, date) if p else None
        rec = {"type": "citation_renumber", "paragraph_id": c["paragraph_id"],
               "section": c.get("section"), "anchor": c["token"],
               "before": c["token"], "after": new_token,
               "numbers": [mapping.get(n, n) for n in c["numbers"]]}
        (applied if res else skipped).append(rec)

    entry_moves = []
    for e in collected["entries"]:
        new_n = mapping.get(e["number"], e["number"])
        if new_n == e["number"]:
            entry_moves.append({"number": new_n, "paragraph_id": e["paragraph_id"]})
            continue
        p = by_id.get(e["paragraph_id"])
        old_tok = re.match(r"^\s*([\[［]?\s*[0-9]{1,3}\s*[\]］.)）])", p["text"]).group(1) if p else None
        new_tok = re.sub(r"[0-9]+", str(new_n), old_tok, count=1) if old_tok else None
        res = track_changes.replace_quote(p, old_tok, new_tok, ids, author, date) if (p and old_tok) else None
        rec = {"type": "reference_renumber", "paragraph_id": e["paragraph_id"],
               "section": e.get("section"), "anchor": old_tok,
               "before": old_tok, "after": new_tok}
        (applied if res else skipped).append(rec)
        entry_moves.append({"number": new_n, "paragraph_id": e["paragraph_id"]})

    reordered = _reorder_entries(doc, entry_moves)
    return {"applied": applied, "skipped": skipped, "reordered": reordered}


def _reorder_entries(doc, entry_moves):
    order = [m["paragraph_id"] for m in sorted(entry_moves, key=lambda x: x["number"])]
    by_id = {p["id"]: p for p in doc["paragraphs"]}
    body = doc["body"]
    kids = list(body)
    elems = [by_id[pid]["xml"] for pid in order if pid in by_id and by_id[pid]["xml"] in kids]
    if len(elems) != len(order) or len(elems) < 2:
        return {"ok": False, "order": order,
                "reason": "条目不是文档正文的直接段落，无法安全移动顺序"}
    pos = min(kids.index(el) for el in elems)
    for el in elems:
        body.remove(el)
    for k, el in enumerate(elems):
        body.insert(pos + k, el)
    return {"ok": True, "order": order}
