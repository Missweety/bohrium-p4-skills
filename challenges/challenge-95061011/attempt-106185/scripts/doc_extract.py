#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""doc_extract.py - 通用文档抽取内核（纯标准库，无网络）。

把 PDF / TeX / DOCX / MD / TXT 抽成带定位锚点的中间表示，供各赛题的
run_case.py 复用：

  { "meta": {...}, "pages": [...], "units": [...], "numbers": [...],
    "tables": [...], "captions": [...], "text": "..." }

定位锚点规范（全赛道统一）：
  p.N        1-based 页码（PDF 页序，非印刷页码）
  sec.X      章节序号（X 为 1-based 章节序号）
  sent.K     该单元第 K 句
  tab.M      第 M 张表
  row.K      该表第 K 行
  cap.M      第 M 条图注/表注

抽取分级（tier）：
  pdftotext  poppler -layout/-raw（最佳，含版面）
  stdlib     纯标准库 PDF 坐标抽取（无 poppler 时）
  plain-text 非 PDF 直接读取
  unreadable 无文本层（扫描件/加密）—— 上层必须诚实降级，不得编造

CLI:
  python3 doc_extract.py --input FILE --outdir DIR [--extractor auto|pdftotext|stdlib]
                          [--max-pages 60]
输出: <outdir>/doc.json
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
MAX_PAGES = 60
UNIT_WORDS = 400          # 一个"单元"的目标长度
NUM_RE = re.compile(
    r"(?<![\w.])"
    r"(?P<cmp>[<>~≥≤≈±∓]?\s*)?"
    r"(?P<num>\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?)"
    r"(?P<scale>\s*(?:[×xX]\s*10\s*(?:\^|⁻?[⁰¹²³⁴⁵⁶⁷⁸⁹]*)?|e\s*[-+]?\d+))?"
    r"(?P<unit>\s*(?:%|‰|°[CF]?|[a-zA-ZμµΩ][a-zA-ZμµΩ/·\^0-9\-]{0,11}|倍|次))?"
)
UNIT_SUFFIX = re.compile(r"^[\s]*([%‰°]|µ[mug]|m[gL]|s|ms|h|min|d|B|kB|MB|GB|TB|nm|µm|mm|cm|m|km|kg|mg|g|N|Pa|kPa|MPa|GPa|mol|L|mL|Hz|kHz|MHz|GHz|V|mV|kV|A|mA|W|kW|MW|kJ|J|MJ|eV|MeV|GeV|dB|fps|rpm|px|pt|em|count|cells|fold|%|倍|次|个|组|人|天|小时|分钟|秒|年|月|日)?")

# 已知单位白名单：只有命中白名单才认定为单位，避免 "on"/"Google"/"v3" 之类误判
KNOWN_UNITS = {
    "%", "‰", "°", "°C", "°F", "倍", "次",
    "nm", "µm", "μm", "mm", "cm", "dm", "m", "km", "µm", "um",
    "g", "kg", "mg", "µg", "ng", "t",
    "s", "ms", "µs", "ns", "min", "h", "d", "yr",
    "B", "kB", "MB", "GB", "TB", "KB",
    "N", "kN", "Pa", "kPa", "MPa", "GPa", "bar", "atm",
    "mol", "mmol", "µmol", "mol/L", "mM", "µM", "nM", "M", "m", "L", "mL", "µL",
    "Hz", "kHz", "MHz", "GHz", "THz",
    "V", "mV", "kV", "A", "mA", "µA", "W", "kW", "MW", "mW",
    "J", "kJ", "MJ", "eV", "meV", "keV", "MeV", "GeV",
    "dB", "fps", "rpm", "px", "pt", "em", "bp", "bpm",
    "cells", "cells/µL", "count", "fold", "SD", "SEM", "CI",
    "nmol", "pmol", "kJ/mol", "J/mol", "kcal", "kcal/mol",
    "MWh", "kWh", "Wh", "GB", "MB",
    # 比值型单位（吸附/浓度类论文常用；v1.2.0 缺失导致 45.2 mg/g 的单位被丢弃）
    "mg/g", "mg/L", "mg/l", "g/L", "g/l", "µg/L", "ug/L", "ng/L", "mg/kg",
    "g/kg", "µg/g", "ug/g", "µg/mL", "ug/mL", "mg/mL", "mmol/g", "meq/g",
    "cmol/kg", "mol/kg", "ppm", "ppb", "mg-C/L",
}
SECTION_NUM = re.compile(
    r"^\s*("
    r"(?:\d+(?:\.\d+){0,3})"                                   # 1 / 1.2 / 1.2.3
    r"|(?:[IVXLC]{1,6})"                                       # I / IV / XIV
    r"|(?:第\s*[一二三四五六七八九十百零〇\d]+\s*[章节節部分篇])"   # 第三章
    r"|(?:附录\s*[A-Z\d]+)"                                    # 附录 A
    r")\s*[.、．:：]?\s+\S"
)
HEADING_MAX = 120
SECTION_ROLE_PATTERNS = [
    ("abstract", r"^(abstract|摘\s*要|摘要)$"),
    ("introduction", r"^(introduction|1[\.\s]*introduction|引言|绪论|前言|研究背景|背景)$"),
    ("related", r"^(related\s+work|related\s+studies|literature\s+review|文献综述|相关工作|相关研究)"),
    ("method", r"^(methods?|methodology|materials?\s+and\s+methods?|experimental\s+(section|setup)|方法|材料与方法|实验方法|研究方法|实验设置|模型)"),
    ("setup", r"^(experimental\s+setup|setup|dataset(s)?|data\s+and\s+preprocessing|数据(?:集|来源|预处理)|实验设置|系统架构|材料)"),
    ("results", r"^(results?|findings|实验结果|结果|主要结果|结果与讨论)"),
    ("discussion", r"^(discussion|讨论|结果与讨论|分析与讨论)"),
    ("limitations", r"^(limitations?|threats?\s+to\s+validity|局限性|局限|研究局限|不足)"),
    ("conclusion", r"^(conclusions?|concluding\s+remarks|结论|总结|结语|结论与展望|研究结论)"),
    ("references", r"^(references?|bibliography|参考文献)"),
    ("appendix", r"^(appendix|appendices|附录|补充材料|supplementary)"),
    ("acknowledgements", r"^(acknowledg(e)?ments?|致谢|资助)"),
    ("abstract_zh", r"^(摘要|摘录)"),
]
CAPTION_RE = re.compile(
    r"^\s*(figure|fig\.?|table|tab\.?|chart|scheme|algorithm|图\s*\d|表\s*\d|附图|附表)\s*"
    r"([0-9]+|[ivxlc]+|[一二三四五六七八九十]+)",
    re.I,
)
TABLE_ROW_RE = re.compile(r"^\s*\|.*\|\s*$")
MD_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*)$")
TEX_SECTION_RE = re.compile(r"\\(?:sub)*section\*?\{([^}]*)\}")
TEX_FIGURE_RE = re.compile(r"\\begin\{(figure|table)\*?\}(.*?)\\end\{\1\*?\}", re.S)
CJK_RE = re.compile(r"[\u4e00-\u9fff]")
SENT_END_RE = re.compile(r"(?<=[.!?。！？])[\s　]+|(?<=[\.\u2026])[\s　]+(?=[A-Z(])")


def _run(cmd, timeout=180):
    try:
        p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout)
    except Exception as exc:  # noqa: BLE001
        return None, str(exc)
    if p.returncode != 0:
        return None, p.stderr.decode("utf-8", "replace")[-400:]
    return p.stdout.decode("utf-8", "replace"), ""


def norm(text):
    return re.sub(r"[ \t　]+", " ", (text or "")).strip()


def pages_from_text(text):
    pages = text.split("\f")
    while pages and not pages[-1].strip():
        pages.pop()
    return pages


# ------------------------------------------------------------------ text tiers
def _pdf_page_count(path):
    if not shutil.which("pdfinfo"):
        return None
    out, _ = _run(["pdfinfo", path])
    if not out:
        return None
    m = re.search(r"^Pages:\s+(\d+)", out, re.M)
    return int(m.group(1)) if m else None


def _pdf_meta(path):
    out, _ = _run(["pdfinfo", path])
    meta = {}
    if not out:
        return meta
    for line in out.splitlines():
        if ":" in line:
            k, v = line.split(":", 1)
            meta[k.strip().lower()] = v.strip()
    return meta


def extract_pdf(path, workdir, extractor="auto", max_pages=MAX_PAGES):
    """Return (text, meta, pages)."""
    os.makedirs(workdir, exist_ok=True)
    attempts = []
    text = ""
    has_poppler = shutil.which("pdftotext") is not None
    if extractor in ("auto", "pdftotext"):
        if not has_poppler:
            attempts.append({"tool": "pdftotext", "error": "MISSING_POPPLER"})
        else:
            for mode in ("layout", "raw"):
                out_path = os.path.join(workdir, "extracted_%s.txt" % mode)
                cmd = ["pdftotext"]
                if mode == "layout":
                    cmd.append("-layout")
                cmd += ["-f", "1", "-l", str(max_pages), path, out_path]
                out, err = _run(cmd)
                if out is None:
                    attempts.append({"tool": "pdftotext", "mode": mode, "error": err})
                    continue
                if not os.path.exists(out_path):
                    attempts.append({"tool": "pdftotext", "mode": mode, "error": "no output file"})
                    continue
                with open(out_path, "r", encoding="utf-8", errors="replace") as fh:
                    text = fh.read()
                pages = pages_from_text(text)
                total = _pdf_page_count(path)
                chars = len(text.strip())
                cpp = chars / max(1, len(pages))
                attempts.append({"tool": "pdftotext", "mode": mode, "chars": chars,
                                 "pages": total or len(pages), "pages_used": len(pages),
                                 "chars_per_page": round(cpp, 1),
                                 "truncated": bool(total and total > len(pages))})
                if cpp >= 200:
                    break
                text = ""
    if not text and extractor in ("auto", "stdlib"):
        try:
            if HERE not in sys.path:
                sys.path.insert(0, HERE)
            import pdf_text_fallback
            fb = pdf_text_fallback.extract(path, max_pages=max_pages)
            text = fb.get("text", "")
            if text.strip():
                pages = pages_from_text(text)
                out_path = os.path.join(workdir, "extracted_stdlib.txt")
                with open(out_path, "w", encoding="utf-8") as fh:
                    fh.write(text)
                attempts.append({"tool": "stdlib-pdf", "chars": fb["chars"],
                                 "pages": fb["pages_total"], "warnings": fb["warnings"],
                                 "truncated": fb["truncated"]})
                meta = {"tool": "stdlib-pdf", "tier": "stdlib", "mode": "layout",
                        "chars": fb["chars"], "pages": fb["pages_total"],
                        "pages_used": fb["pages_used"],
                        "chars_per_page": fb["chars_per_page"],
                        "text_path": out_path, "attempts": attempts,
                        "truncated": fb["truncated"], "warnings": fb["warnings"]}
                return text, meta, pages
            attempts.append({"tool": "stdlib-pdf", "error": "no text extracted",
                             "encrypted": fb.get("encrypted", False),
                             "warnings": fb.get("warnings", [])})
        except Exception as exc:  # noqa: BLE001
            attempts.append({"tool": "stdlib-pdf", "error": str(exc)[-300:]})
    if not text:
        return "", {"tool": "none", "tier": "unreadable", "mode": "none",
                    "attempts": attempts, "chars": 0, "pages": 0,
                    "text_path": None}, []
    mode_used = attempts[-1].get("mode", "layout")
    pages = pages_from_text(text)
    total = _pdf_page_count(path) or len(pages)
    chars = len(text.strip())
    meta = {"tool": "pdftotext", "tier": "pdftotext", "mode": mode_used,
            "chars": chars, "pages": total, "pages_used": len(pages),
            "chars_per_page": round(chars / max(1, len(pages)), 1),
            "text_path": os.path.join(workdir, "extracted_%s.txt" % mode_used),
            "attempts": attempts, "truncated": total > len(pages)}
    return text, meta, pages


def tex_to_text(path):
    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        raw = fh.read()
    raw = re.sub(r"(?<!\\)%.*", "", raw)
    raw = TEX_FIGURE_RE.sub(" ", raw, flags=re.S)
    raw = re.sub(r"\\(cite|ref|label|footnote|url|includegraphics)\{[^}]*\}", " ", raw)
    raw = re.sub(r"\\(?:sub)*section\*?\{([^}]*)\}", r"\n\n\1\n\n", raw)
    raw = re.sub(r"\\(title|author|date)\{([^}]*)\}", r"\2", raw)
    raw = re.sub(r"\\[a-zA-Z]+\*?(\[[^\]]*\])?(\{[^}]*\})?", " ", raw)
    raw = raw.replace("{", " ").replace("}", " ").replace("~", " ")
    raw = re.sub(r"[ \t]+", " ", raw)
    return raw


def docx_to_text(path):
    with zipfile.ZipFile(path) as zf:
        xml = zf.read("word/document.xml").decode("utf-8", "replace")
    paras = re.findall(r"<w:p[ >].*?</w:p>", xml, re.S)
    lines = []
    for p in paras:
        txt = "".join(re.findall(r"<w:t[^>]*>(.*?)</w:t>", p, re.S))
        txt = (txt.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
               .replace("&quot;", '"').replace("&apos;", "'"))
        if txt.strip():
            lines.append(txt.strip())
    return "\n".join(lines)


def read_text_file(path):
    """按 utf-8-sig → utf-8 → gb18030 依次解码文本文件。

    v1.2.0 一律按 utf-8 + errors=replace 读取，GBK/GB18030 的中文论文会被
    解成替换字符（正文全坏、章节切分为空），导致所有字段 not_reported 却仍
    报 success。这里显式探测编码并记录替换字符数。
    """
    with open(path, "rb") as fh:
        raw = fh.read()
    for enc in ("utf-8-sig", "utf-8", "gb18030"):
        try:
            text = raw.decode(enc)
            return text, {"encoding": enc, "replacement_chars": 0}
        except UnicodeDecodeError:
            continue
    text = raw.decode("utf-8", "replace")
    return text, {"encoding": "utf-8/replace",
                  "replacement_chars": text.count("\ufffd")}


def extract_any(path, workdir, extractor="auto", max_pages=MAX_PAGES):
    ext = os.path.splitext(path)[1].lower()
    if ext in (".txt", ".md", ".rst", ".csv", ".json", ".jsonl", ".tsv"):
        text, enc_meta = read_text_file(path)
        pages = pages_from_text(text)
        return text, {"tool": "plain-text", "tier": "plain-text", "mode": "as-is",
                      "chars": len(text.strip()), "pages": len(pages),
                      "pages_used": len(pages),
                      "chars_per_page": round(len(text.strip()) / max(1, len(pages)), 1),
                      "text_path": path, "attempts": [], "truncated": False,
                      **enc_meta}, pages
    if ext == ".tex":
        text = tex_to_text(path)
        pages = pages_from_text(text)
        return text, {"tool": "tex", "tier": "plain-text", "mode": "tex",
                      "chars": len(text.strip()), "pages": len(pages),
                      "pages_used": len(pages), "text_path": path,
                      "attempts": [], "truncated": False}, pages
    if ext == ".docx":
        text = docx_to_text(path)
        pages = pages_from_text(text)
        return text, {"tool": "docx", "tier": "plain-text", "mode": "docx",
                      "chars": len(text.strip()), "pages": len(pages),
                      "pages_used": len(pages), "text_path": path,
                      "attempts": [], "truncated": False}, pages
    if ext == ".pdf":
        return extract_pdf(path, workdir, extractor, max_pages)
    # 其它：尝试按文本读
    try:
        text, enc_meta = read_text_file(path)
    except OSError:
        return "", {"tool": "none", "tier": "unreadable", "mode": "none",
                    "attempts": [{"tool": "read", "error": "binary"}], "chars": 0,
                    "pages": 0, "text_path": None}, []
    pages = pages_from_text(text)
    return text, {"tool": "plain-text", "tier": "plain-text", "mode": "as-is",
                  "chars": len(text.strip()), "pages": len(pages),
                  "pages_used": len(pages), "text_path": path,
                  "attempts": [], "truncated": False, **enc_meta}, pages


# ------------------------------------------------------------------ structure
def classify_line(line):
    s = line.strip()
    if not s:
        return None
    if MD_HEADING_RE.match(s):
        return ("heading", MD_HEADING_RE.match(s).group(2).strip(), len(MD_HEADING_RE.match(s).group(1)))
    if CAPTION_RE.match(s):
        return ("caption", s, 0)
    if TABLE_ROW_RE.match(s):
        return ("table_row", s, 0)
    if SECTION_NUM.match(s) and len(s) <= HEADING_MAX and not s.endswith((".", "。")):
        return ("heading", s, 1)
    if s.isupper() and 3 <= len(s) <= HEADING_MAX:
        return ("heading", s, 1)
    return ("body", s, 0)


def role_of(title):
    t = re.sub(r"^(?:\d+(?:\.\d+)*\.?|[IVXLC]{1,6}\.?)\s*", "", title or "").strip()
    t = re.sub(r"[.:：\s]+$", "", t)
    key = t.lower()
    for role, pat in SECTION_ROLE_PATTERNS:
        if re.search(pat, key, re.I):
            return role
    return "other"


def split_units(pages):
    """把页面文本切成语义单元（章节），返回 [{id,title,role,level,page_start,page_end,text,spans}]。

    spans 记录每个字符区间所属页码：[(start, end, page), ...]。
    单元常常跨页（长章节），句级锚点必须按 span 定位到真实所在页，
    否则「引文逐字命中锚点页」的复核会失败。
    """
    units = []
    cur = None
    for pno, page in enumerate(pages, 1):
        for raw_line in page.split("\n"):
            cls = classify_line(raw_line)
            if cls is None:
                continue
            kind, payload, level = cls
            if kind == "heading":
                if cur is not None:
                    cur["page_end"] = pno
                    units.append(cur)
                cur = {"id": None, "title": payload, "role": role_of(payload),
                       "level": level, "page_start": pno, "page_end": pno, "lines": []}
            elif cur is None:
                # v1.2.0 在这里丢了第一行正文（文档首行不是标题时整篇变空）
                cur = {"id": None, "title": "(preamble)", "role": "preamble",
                       "level": 1, "page_start": pno, "page_end": pno,
                       "lines": [(pno, payload)]}
            else:
                cur["lines"].append((pno, payload))
    if cur is not None:
        units.append(cur)
    for i, u in enumerate(units, 1):
        u["id"] = "sec.%d" % i
        chunks = []
        spans = []
        pos = 0
        for pno, payload in u["lines"]:
            if chunks:
                pos += 1  # 换行
            start = pos
            pos += len(payload)
            chunks.append(payload)
            spans.append((start, pos, pno))
        u["text"] = "\n".join(chunks)
        if not u["text"] and u.get("title") and u["title"] != "(preamble)":
            # 只有标题、没有正文行的单元（单行文档）也不能是空壳
            u["text"] = u["title"]
        u["spans"] = spans
        u["words"] = len(u["text"].split())
    return units


def page_at_offset(spans, offset):
    """按字符偏移找所在页码。"""
    if not spans:
        return None
    for start, end, pno in spans:
        if start <= offset < end:
            return pno
    return spans[-1][2]


def split_sentences(text):
    text = (text or "").strip()
    if not text:
        return []
    parts = re.split(r"(?<=[.!?。！？])\s+|\n{2,}", text)
    out = []
    for p in parts:
        p = p.strip()
        if p:
            out.append(p)
    if len(out) == 1 and len(out[0]) > 900:
        # 超长段落：按句号再切
        sub = re.split(r"(?<=[.!?。！？])", out[0])
        buf = []
        for s in sub:
            buf.append(s)
            if len(" ".join(buf)) > 600:
                out = out[:1] + [" ".join(x for x in buf if x.strip())]
                buf = []
        if buf:
            out = out[:1] + [" ".join(x for x in buf if x.strip())]
    return out


def mine_numbers(units):
    """抽取数值候选（含单位），带 p.N/sec.X/sent.K 锚点。"""
    rows = []
    for u in units:
        for k, sent in enumerate(split_sentences(u["text"]), 1):
            for m in NUM_RE.finditer(sent):
                raw = m.group(0).strip()
                if not raw or not re.search(r"\d", raw):
                    continue
                unit = (m.group("unit") or "").strip()
                if unit and unit not in KNOWN_UNITS:
                    unit = ""
                ctx = sent[max(0, m.start() - 90):m.end() + 90]
                rows.append({
                    "raw": raw,
                    "value": m.group("num"),
                    "unit": unit,
                    "anchor": "p.%d/%s/sent.%d" % (u["page_start"], u["id"], k),
                    "page": u["page_start"],
                    "section": u["id"],
                    "sentence": k,
                    "context": norm(ctx),
                })
    return rows


def _split_layout_cells(line):
    """pdftotext -layout 输出的表格行：用 2+ 空格切列。"""
    parts = re.split(r"\s{2,}", line.strip())
    return [p.strip() for p in parts if p.strip()]


def _looks_like_table_row(line):
    s = line.rstrip()
    if not s.strip():
        return False
    cells = _split_layout_cells(s)
    if len(cells) < 2:
        return False
    numeric = sum(1 for c in cells if re.search(r"\d", c))
    return numeric >= 2 or (len(cells) >= 3 and numeric >= 1)


def mine_tables(pages):
    """抽取表格行。

    两种版式：
      1) Markdown/管道式 `| a | b |`
      2) pdftotext -layout 的空格对齐表格（2+ 空格分列）
    每行带 p.N/tab.M/row.K 锚点；只有标题没有行的表也要保留（caption-only），
    以便上层标注"表格正文未能自动切分"，而不是假装表格已解析。
    """
    tables = []
    cur = None
    for pno, page in enumerate(pages, 1):
        for line in page.split("\n"):
            s = line.strip()
            pipe = bool(TABLE_ROW_RE.match(s))
            layout = (not pipe) and _looks_like_table_row(line)
            if pipe or layout:
                cells = ([c.strip() for c in s.strip("|").split("|")] if pipe
                         else _split_layout_cells(line))
                if cur is None:
                    cur = {"id": "tab.%d" % (len(tables) + 1), "page": pno,
                           "caption": "", "rows": [], "layout": "pipe" if pipe else "layout"}
                cur["rows"].append({"row": len(cur["rows"]) + 1, "page": pno,
                                    "cells": cells,
                                    "anchor": "p.%d/%s/row.%d" % (pno, cur["id"], len(cur["rows"]) + 1)})
            else:
                if cur is not None and len(cur["rows"]) >= 2:
                    tables.append(cur)
                cur = None
                if CAPTION_RE.match(s):
                    tables.append({"id": "tab.%d" % (len(tables) + 1), "page": pno,
                                   "caption": s, "rows": [],
                                   "layout": "caption-only",
                                   "note": "caption detected but table body not segmented; read the cited page"})
    if cur is not None and len(cur["rows"]) >= 2:
        tables.append(cur)
    for idx, t in enumerate(tables, 1):
        t["id"] = "tab.%d" % idx
        for r in t["rows"]:
            r["anchor"] = "p.%d/%s/row.%d" % (r["page"], t["id"], r["row"])
    return tables


def mine_captions(pages):
    caps = []
    for pno, page in enumerate(pages, 1):
        for line in page.split("\n"):
            s = line.strip()
            if CAPTION_RE.match(s) and s not in [c["text"] for c in caps]:
                caps.append({"id": "cap.%d" % (len(caps) + 1), "page": pno,
                             "text": s, "anchor": "p.%d/cap.%d" % (pno, len(caps) + 1)})
    return caps


def build_doc(path, workdir, extractor="auto", max_pages=MAX_PAGES):
    text, meta, pages = extract_any(path, workdir, extractor, max_pages)
    units = split_units(pages) if pages else []
    meta = dict(meta)
    meta["source_file"] = os.path.basename(path)
    meta["language"] = "zh" if len(CJK_RE.findall(text[:20000])) > 200 else "en"
    doc = {
        "meta": meta,
        "pages": [{"page": i + 1, "chars": len(p)} for i, p in enumerate(pages)],
        "units": units,
        "numbers": mine_numbers(units) if units else [],
        "tables": mine_tables(pages),
        "captions": mine_captions(pages),
        "text": text,
    }
    if path.lower().endswith(".pdf"):
        doc["meta"]["pdf_meta"] = _pdf_meta(path)
    return doc


def main(argv=None):
    ap = argparse.ArgumentParser(description="通用文档抽取")
    ap.add_argument("--input", required=True)
    ap.add_argument("--outdir", required=True)
    ap.add_argument("--extractor", default="auto", choices=["auto", "pdftotext", "stdlib"])
    ap.add_argument("--max-pages", type=int, default=MAX_PAGES)
    args = ap.parse_args(argv)
    os.makedirs(args.outdir, exist_ok=True)
    workdir = os.path.join(args.outdir, "_extract")
    doc = build_doc(args.input, workdir, args.extractor, args.max_pages)
    out = os.path.join(args.outdir, "doc.json")
    with open(out, "w", encoding="utf-8") as fh:
        json.dump(doc, fh, ensure_ascii=False, indent=2)
    print("tier=%s pages=%d units=%d numbers=%d tables=%d captions=%d -> %s" % (
        doc["meta"].get("tier"), len(doc["pages"]), len(doc["units"]),
        len(doc["numbers"]), len(doc["tables"]), len(doc["captions"]), out))
    return 0 if doc["meta"].get("tier") != "unreadable" else 2


if __name__ == "__main__":
    sys.exit(main())
