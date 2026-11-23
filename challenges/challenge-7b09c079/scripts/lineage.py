#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""lineage.py -- 版本谱系与差异。

每个版本记 sha256、父版本、角色、改动数；原稿与修订稿都在同一目录，可对比、可回退。
不覆盖原稿：v0 只读复制，v1 是新文件。
"""
from __future__ import annotations

import difflib
import hashlib
import os
import shutil


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def snapshot(src, dst):
    os.makedirs(os.path.dirname(os.path.abspath(dst)) or ".", exist_ok=True)
    if os.path.abspath(src) != os.path.abspath(dst):
        shutil.copyfile(src, dst)
    return {"file": os.path.basename(dst), "sha256": sha256(dst), "bytes": os.path.getsize(dst)}


def build(case_id, v0_path, v1_path, changes, note=None):
    v0 = snapshot(v0_path, v0_path)
    v1 = snapshot(v1_path, v1_path)
    return {
        "case_id": case_id,
        "versions": [
            {"version": "v0", "role": "original", "parent": None,
             "file": v0["file"], "sha256": v0["sha256"], "bytes": v0["bytes"],
             "note": "原稿只读副本，回退目标"},
            {"version": "v1", "role": "tracked_revision", "parent": "v0",
             "file": v1["file"], "sha256": v1["sha256"], "bytes": v1["bytes"],
             "changes": changes, "note": note or "含可逐条接受的 Word 修订标记"},
        ],
        "rollback": "把 v1 换回 v0（%s）即回到原稿；原稿未被改写。" % v0["sha256"][:12],
    }


def diff(before_texts, after_texts, name="manuscript"):
    a = "\n".join(before_texts).splitlines(keepends=True)
    b = "\n".join(after_texts).splitlines(keepends=True)
    return "".join(difflib.unified_diff(a, b,
                                        fromfile=name + ".v0", tofile=name + ".v1"))


def changed_lines(before_texts, after_texts):
    sm = difflib.SequenceMatcher(None, before_texts, after_texts)
    adds = dels = 0
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag in ("replace", "delete"):
            dels += i2 - i1
        if tag in ("replace", "insert"):
            adds += j2 - j1
    return {"paragraphs_added": adds, "paragraphs_removed": dels,
            "paragraphs_before": len(before_texts), "paragraphs_after": len(after_texts)}
