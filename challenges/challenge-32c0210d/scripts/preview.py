#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""preview.py -- 给可编辑产物生成真实渲染预览，失败就如实说明。

优先 LibreOffice（评测环境声明 office-renderer）：
    soffice --headless --convert-to pdf
产物须以 %PDF 开头且能数到 /Type /Page。降级写清原因，绝不伪造 preview.pdf。
"""
from __future__ import annotations

import html
import os
import re
import shutil
import subprocess
import tempfile

CANDIDATES = ["soffice", "libreoffice", "soffice.bin", "/usr/bin/soffice",
              "/usr/local/bin/soffice", "/opt/libreoffice/program/soffice"]


def find_office():
    for c in CANDIDATES:
        p = shutil.which(c) or (c if os.path.isfile(c) else None)
        if p:
            return p
    return None


def _page_count(pdf_path):
    try:
        data = open(pdf_path, "rb").read()
    except Exception:
        return 0
    if not data.startswith(b"%PDF"):
        return -1
    return len(re.findall(rb"/Type\s*/Page[^s]", data))


def render_pdf(docx_path, out_pdf, timeout=180):
    bin_ = find_office()
    if not bin_:
        return {"status": "unavailable", "reason": "未找到 LibreOffice/soffice",
                "renderer": None, "pdf": None, "pages": 0}
    tmpdir = tempfile.mkdtemp(prefix="preview_")
    try:
        env = dict(os.environ, HOME=tmpdir)
        cmd = [bin_, "--headless", "--norestore", "--nolockcheck",
               "-env:UserInstallation=file://" + os.path.join(tmpdir, "profile"),
               "--convert-to", "pdf", "--outdir", tmpdir, os.path.abspath(docx_path)]
        proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                              timeout=timeout, env=env)
        stem = os.path.splitext(os.path.basename(docx_path))[0] + ".pdf"
        produced = os.path.join(tmpdir, stem)
        if not os.path.exists(produced):
            cand = [f for f in os.listdir(tmpdir) if f.lower().endswith(".pdf")]
            produced = os.path.join(tmpdir, cand[0]) if cand else produced
        pages = _page_count(produced) if os.path.exists(produced) else -1
        if pages <= 0:
            tail = (proc.stderr or b"")[-300:].decode("utf-8", "replace").strip()
            return {"status": "unavailable",
                    "reason": "转换未产出合法 PDF" + (("：" + tail) if tail else ""),
                    "renderer": bin_, "pdf": None, "pages": 0}
        os.makedirs(os.path.dirname(os.path.abspath(out_pdf)) or ".", exist_ok=True)
        shutil.copyfile(produced, out_pdf)
        return {"status": "rendered", "reason": "", "renderer": bin_,
                "pdf": os.path.basename(out_pdf), "pages": pages}
    except subprocess.TimeoutExpired:
        return {"status": "unavailable", "reason": "LibreOffice 转换超时(%ss)" % timeout,
                "renderer": bin_, "pdf": None, "pages": 0}
    except Exception as exc:
        return {"status": "unavailable", "reason": "转换异常: %s" % exc,
                "renderer": bin_, "pdf": None, "pages": 0}
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def render_html(texts, out_html, title="Document preview"):
    body = "\n".join('<p class="ln"><span class="no">%d</span>%s</p>'
                     % (i + 1, html.escape(t) if t.strip() else "&nbsp;")
                     for i, t in enumerate(texts))
    doc = """<!DOCTYPE html>
<html lang="zh"><head><meta charset="utf-8"><title>%s</title>
<style>
body{font:15px/1.85 "Songti SC","SimSun",serif;max-width:900px;margin:2em auto;color:#222}
.ln{display:flex;gap:12px;margin:0 0 .55em}
.no{color:#aaa;font:11px/1.9 monospace;min-width:42px;text-align:right;user-select:none}
</style></head><body>
<h1>%s</h1><p style="color:#888">由修订稿重新抽取正文生成，供无 Office 渲染器时人工核对。</p>
%s
</body></html>""" % (html.escape(title), html.escape(title), body)
    os.makedirs(os.path.dirname(os.path.abspath(out_html)) or ".", exist_ok=True)
    with open(out_html, "w", encoding="utf-8") as fh:
        fh.write(doc)
    return out_html
