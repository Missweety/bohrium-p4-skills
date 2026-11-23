#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""track_changes.py -- 在段落原文里生成"可逐条接受/拒绝"的 Word 修订标记。

只做三件事，且都只碰命中处：
    replace_quote()  在段落里找到逐字引文，生成 <w:del>旧</w:del> + <w:ins>新</w:ins>
    insert_after()   在引文之后插入 <w:ins>
    accept_all()     生成"全部接受后"的干净稿（去掉 w:del，解包 w:ins）

安全边界：
    * 只在段落的"直接 w:r 子元素"里查找，绝不动已有 w:ins / w:del 内的文字，
      因此可以在已有修订的段落上继续改而不互相污染；
    * 每条修订都有唯一 w:id、w:author、w:date，可在 Word 的"审阅"面板逐条接受/拒绝；
    * 找不到逐字引文时不做任何改动，由调用方记为 skipped。
"""
from __future__ import annotations

import copy
from xml.etree import ElementTree as ET

import docx_io

W = docx_io.W
XML_SPACE = docx_io.XML_SPACE
DEFAULT_AUTHOR = "academic-writing-client"
DEFAULT_DATE = "2026-01-01T00:00:00Z"


def _w(name):
    return "{%s}%s" % (W, name)


def _local(tag):
    return tag.rsplit("}", 1)[-1] if "}" in tag else tag


class IdGen:
    def __init__(self, root, start=9000):
        top = start
        for el in root.iter():
            v = el.get(_w("id"))
            if v and v.isdigit():
                top = max(top, int(v))
        self.n = top

    def next(self):
        self.n += 1
        return self.n


def _run_text(run):
    out = []
    for c in run:
        tag = _local(c.tag)
        if tag == "t":
            out.append(c.text or "")
        elif tag == "tab":
            out.append("\t")
        elif tag in ("br", "cr"):
            out.append("\n")
    return "".join(out)


def _make_run(rpr, text, tag="t"):
    run = ET.Element(_w("r"))
    if rpr is not None:
        run.append(copy.deepcopy(rpr))
    node = ET.SubElement(run, _w(tag))
    node.text = text
    node.set(XML_SPACE, "preserve")
    return run


def _mark(kind, rid, author, date):
    el = ET.Element(_w(kind))
    el.set(_w("id"), str(rid))
    el.set(_w("author"), author)
    el.set(_w("date"), date)
    return el


def _plain_groups(p_elem):
    """把直接子元素里"连续的 w:r"聚成组；遇到 w:ins/w:del 等即断开。"""
    groups, cur = [], []
    for ch in list(p_elem):
        if ch.tag == _w("r"):
            cur.append(ch)
        elif cur:
            groups.append(cur)
            cur = []
    if cur:
        groups.append(cur)
    return groups


def _locate_quote(p_elem, quote):
    if not quote:
        return None
    for group in _plain_groups(p_elem):
        text = "".join(_run_text(r) for r in group)
        i = text.find(quote)
        if i >= 0:
            return group, i, i + len(quote)
    return None


def has_tracked_changes(p_elem):
    for el in p_elem.iter():
        if _local(el.tag) in ("ins", "del"):
            return True
    return False


def _rewrite_group(p_elem, group, start, end, new_text, ids, author, date):
    """把 group 覆盖的 [start,end) 换成 del(旧)+ins(新)；返回改动 run 数。"""
    spans, pos = [], 0
    for r in group:
        t = _run_text(r)
        spans.append((r, pos, pos + len(t)))
        pos += len(t)
    if end > pos:
        return 0
    rebuilt, inserted, touched = [], False, 0
    for r, rs, re_ in spans:
        t = _run_text(r)
        rpr = r.find(_w("rPr"))
        if start == end:
            # 纯插入：在插入点把 run 拆成"前段 + ins + 后段"
            if not inserted and rs <= start <= re_ and (rs < re_ or not t):
                off = start - rs
                prefix, suffix = t[:off], t[off:]
                if prefix:
                    rebuilt.append(_make_run(rpr, prefix))
                ins = _mark("ins", ids.next(), author, date)
                ins.append(_make_run(rpr, new_text))
                rebuilt.append(ins)
                inserted, touched = True, touched + 1
                if suffix:
                    rebuilt.append(_make_run(rpr, suffix))
                continue
            rebuilt.append(r)
            continue
        a, b = max(start, rs), min(end, re_)
        if a >= b:
            rebuilt.append(r)
            continue
        prefix, mid, suffix = t[:a - rs], t[a - rs:b - rs], t[b - rs:]
        if prefix:
            rebuilt.append(_make_run(rpr, prefix))
        if mid:
            d = _mark("del", ids.next(), author, date)
            d.append(_make_run(rpr, mid, "delText"))
            rebuilt.append(d)
            touched += 1
        if not inserted and new_text:
            ins = _mark("ins", ids.next(), author, date)
            ins.append(_make_run(rpr, new_text))
            rebuilt.append(ins)
            inserted = True
        if suffix:
            rebuilt.append(_make_run(rpr, suffix))
    if not rebuilt:
        return 0
    parent = {c: p for p in p_elem.iter() for c in p}.get(group[0])
    if parent is None:
        return 0
    idx = list(parent).index(group[0])
    for r in group:
        parent.remove(r)
    for k, el in enumerate(rebuilt):
        parent.insert(idx + k, el)
    return touched


def replace_quote(para, quote, new_text, ids, author=DEFAULT_AUTHOR, date=DEFAULT_DATE):
    """返回 None(未命中) 或 {"before","after","mode"}。"""
    p_elem = para["xml"]
    hit = _locate_quote(p_elem, quote)
    if not hit:
        return None
    group, s, e = hit
    touched = _rewrite_group(p_elem, group, s, e, new_text, ids, author, date)
    if not touched:
        return None
    para["segments"] = docx_io._collect_segments(p_elem)
    para["text"] = "".join(x["text"] for x in para["segments"])
    return {"before": quote, "after": new_text,
            "mode": "replace" if new_text else "delete", "runs_marked": touched}


def insert_after(para, anchor, new_text, ids, author=DEFAULT_AUTHOR, date=DEFAULT_DATE):
    p_elem = para["xml"]
    hit = _locate_quote(p_elem, anchor)
    if not hit or not new_text:
        return None
    group, s, e = hit
    touched = _rewrite_group(p_elem, group, e, e, new_text, ids, author, date)
    if not touched:
        return None
    para["segments"] = docx_io._collect_segments(p_elem)
    para["text"] = "".join(x["text"] for x in para["segments"])
    return {"before": anchor, "after": anchor + new_text, "mode": "insert",
            "runs_marked": touched}


def count_tracked(p_elem):
    ins = sum(1 for el in p_elem.iter() if _local(el.tag) == "ins")
    dele = sum(1 for el in p_elem.iter() if _local(el.tag) == "del")
    return {"insertions": ins, "deletions": dele}


def accept_all(doc, out_path):
    """生成"全部接受修订"的干净稿：删 w:del，解包 w:ins，去 *Change。"""
    root = copy.deepcopy(doc["root"])
    for parent in list(root.iter()):
        kids = list(parent)
        if not kids:
            continue
        new_kids, changed = [], False
        for ch in kids:
            tag = _local(ch.tag)
            if tag == "del":
                changed = True
                continue
            if tag == "ins":
                changed = True
                new_kids.extend(list(ch))
                continue
            new_kids.append(ch)
        if changed:
            for k in kids:
                parent.remove(k)
            for k in new_kids:
                parent.append(k)
    for parent in list(root.iter()):
        for ch in list(parent):
            if _local(ch.tag).endswith("Change"):
                parent.remove(ch)
    return docx_io.save_docx({"path": doc["path"], "root": root}, out_path)
