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
import csv
import hashlib
import json
import os
import re
import shutil
import struct
import subprocess
import sys
import zipfile
from xml.etree import ElementTree as ET

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
CAPTION_LABEL_RE = re.compile(
    r"^\s*(fig(?:ure)?\.?|table|tab\.?|chart|scheme|algorithm|图|表|附图|附表)\s*"
    r"([0-9]+|[ivxlc]+|[一二三四五六七八九十]+)\s*"
    r"(?:[|:：.、\-–—]\s*)?(.*)$",
    re.I,
)
MD_EMPH_RE = re.compile(r"\*\*|__")
TABLE_ROW_RE = re.compile(r"^\s*\|.*\|\s*$")
SEP_CELL_RE = re.compile(r"^:?-+:?$")
CAPTION_N_RE = re.compile(r"\bn\s*=\s*(\d+)\b", re.I)
CAPTION_P_RE = re.compile(r"\bp\s*([<>=≤≥])\s*(\d+(?:\.\d+)?)", re.I)
CAPTION_ERR_RE = re.compile(r"\bs\.?\s*e\.?\s*m\.?\b", re.I)
CAPTION_SD_RE = re.compile(r"\bs\.?\s*d\.?\b", re.I)
CAPTION_CI_RE = re.compile(r"\b(?:95\s*%\s*)?CI\b", re.I)
CAPTION_TEST_RE = re.compile(
    r"(?:(?:two-sided|one-sided|two-tailed|one-tailed)\s+)?"
    r"(?:Student'?s?\s+)?"
    r"(?:t-test|ANOVA|Mann[-\u2013]Whitney(?:\s+U)?\s+test|Wilcoxon\s+\w+\s+test|"
    r"chi-square\s+test|Friedman\s+test|Kruskal[-\u2013]Wallis\s+test)",
    re.I,
)
MD_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*)$")
TEX_SECTION_RE = re.compile(r"\\(?:sub)*section\*?\{([^}]*)\}")
TEX_FIGURE_RE = re.compile(r"\\begin\{(figure|table)\*?\}(.*?)\\end\{\1\*?\}", re.S)
CJK_RE = re.compile(r"[\u4e00-\u9fff]")
SENT_END_RE = re.compile(r"(?<=[.!?。！？])[\s　]+|(?<=[\.\u2026])[\s　]+(?=[A-Z(])")


def read_text(path):
    """按 UTF-8 → GB18030 → UTF-16(BOM) 的顺序解码，避免中文材料变成乱码。"""
    with open(path, "rb") as fh:
        raw = fh.read()
    if raw[:2] in (b"\xff\xfe", b"\xfe\xff"):
        return raw.decode("utf-16", "replace")
    for enc in ("utf-8-sig", "gb18030"):
        try:
            return raw.decode(enc)
        except (UnicodeDecodeError, LookupError):
            continue
    return raw.decode("utf-8", "replace")


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
                        "text_path": os.path.basename(out_path), "attempts": attempts,
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
            "text_path": os.path.basename(os.path.join(workdir, "extracted_%s.txt" % mode_used)),
            "attempts": attempts, "truncated": total > len(pages)}
    return text, meta, pages


def tex_to_text(path):
    raw = read_text(path)
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


def extract_any(path, workdir, extractor="auto", max_pages=MAX_PAGES):
    ext = os.path.splitext(path)[1].lower()
    if ext in (".txt", ".md", ".rst", ".csv", ".json", ".jsonl", ".tsv"):
        text = read_text(path)
        pages = pages_from_text(text)
        return text, {"tool": "plain-text", "tier": "plain-text", "mode": "as-is",
                      "chars": len(text.strip()), "pages": len(pages),
                      "pages_used": len(pages),
                      "chars_per_page": round(len(text.strip()) / max(1, len(pages)), 1),
                      "text_path": os.path.basename(path), "attempts": [], "truncated": False}, pages
    if ext == ".tex":
        text = tex_to_text(path)
        pages = pages_from_text(text)
        return text, {"tool": "tex", "tier": "plain-text", "mode": "tex",
                      "chars": len(text.strip()), "pages": len(pages),
                      "pages_used": len(pages), "text_path": os.path.basename(path),
                      "attempts": [], "truncated": False}, pages
    if ext == ".docx":
        text = docx_to_text(path)
        pages = pages_from_text(text)
        return text, {"tool": "docx", "tier": "plain-text", "mode": "docx",
                      "chars": len(text.strip()), "pages": len(pages),
                      "pages_used": len(pages), "text_path": os.path.basename(path),
                      "attempts": [], "truncated": False}, pages
    if ext == ".pdf":
        return extract_pdf(path, workdir, extractor, max_pages)
    # 其它：尝试按文本读
    try:
        text = read_text(path)
    except OSError:
        return "", {"tool": "none", "tier": "unreadable", "mode": "none",
                    "attempts": [{"tool": "read", "error": "binary"}], "chars": 0,
                    "pages": 0, "text_path": None}, []
    pages = pages_from_text(text)
    return text, {"tool": "plain-text", "tier": "plain-text", "mode": "as-is",
                  "chars": len(text.strip()), "pages": len(pages),
                  "pages_used": len(pages), "text_path": os.path.basename(path),
                  "attempts": [], "truncated": False}, pages


# ------------------------------------------------------------------ structure
def strip_emphasis(text):
    """去掉 Markdown 粗体/斜体包裹，保留单个 * 这类显著性标记。"""
    return MD_EMPH_RE.sub("", (text or "")).strip()


def caption_match(line):
    """图注/表注行匹配（容忍 **Figure 1 | ...** 这种加粗写法）。"""
    return CAPTION_RE.match(strip_emphasis(line))


def classify_line(line):
    s = line.strip()
    if not s:
        return None
    if MD_HEADING_RE.match(s):
        return ("heading", MD_HEADING_RE.match(s).group(2).strip(), len(MD_HEADING_RE.match(s).group(1)))
    if caption_match(s):
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
                cur = {"id": None, "title": "(preamble)", "role": "preamble",
                       "level": 1, "page_start": pno, "page_end": pno, "lines": []}
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
    if numeric >= 2 or (len(cells) >= 3 and numeric >= 1):
        return True
    # 纯文本表头（如 Dose (µM)  Viability (%)  s.e.m.  n  Significance）：
    # 多列且每列都很短，视为表头行，供后续行挂列名/单位。
    return len(cells) >= 3 and all(len(c) <= 40 for c in cells)


def _parse_caption(text):
    """解析图注/表注：编号、样本量、误差类型、显著性标记、检验方法、p 值。"""
    plain = strip_emphasis(text)
    m = CAPTION_LABEL_RE.match(plain)
    if not m:
        return {"kind": "other", "label": None}
    token = (m.group(1) or "").lower()
    kind = ("figure" if token.startswith(("fig", "chart", "scheme", "algorithm", "图", "附图"))
            else "table")
    num = m.group(2)
    body = (m.group(3) or "").strip()
    n = CAPTION_N_RE.search(plain)
    error = None
    if CAPTION_ERR_RE.search(plain):
        error = "s.e.m."
    elif CAPTION_SD_RE.search(plain):
        error = "s.d."
    elif CAPTION_CI_RE.search(plain):
        error = "CI"
    p = CAPTION_P_RE.search(plain)
    test = CAPTION_TEST_RE.search(plain)
    marks = []
    for mark in re.findall(r"\*{1,3}", plain):
        if mark not in marks:
            marks.append(mark)
    if re.search(r"\bn\.s\.\b", plain, re.I) and "n.s." not in marks:
        marks.append("n.s.")
    return {
        "kind": kind,
        "label": "%s %s" % ("Figure" if kind == "figure" else "Table", num),
        "title": body,
        "n": int(n.group(1)) if n else None,
        "error": error,
        "mean_reported": bool(re.search(r"\bmean\b", plain, re.I)),
        "significance": marks,
        "significance_note": p.group(0) if p else None,
        "p_value": p.group(2) if p else None,
        "test": test.group(0) if test else None,
    }


def _coerce_number(raw):
    """单元格转数值：只接受纯数字（可带比较符/千分位），否则原样返回字符串。"""
    text = (raw or "").strip().replace(",", "")
    m = re.match(r"^[<>~≥≤≈]?\s*([-+]?\d+(?:\.\d+)?)\s*$", text)
    if not m:
        return None
    num = float(m.group(1))
    return int(num) if num.is_integer() and "." not in m.group(1) else num


def _header_units(cells):
    """表头识别：列名、单位（如 Dose (µM)）与语义角色。"""
    header = []
    for idx, cell in enumerate(cells, 1):
        raw = (cell or "").strip()
        name, unit = raw, None
        m = re.match(r"^(.+?)\s*[（(]([^)）]+)[)）]\s*$", raw)
        if m:
            name, unit = m.group(1).strip(), m.group(2).strip()
        low = name.lower()
        if any(k in low for k in ("dose", "concentration", "time", "wavelength")):
            role = "x_axis"
        elif "s.e.m" in low or low in ("sem", "s.d", "s.d.", "sd") or "error" in low or low == "ci":
            role = "error"
        elif low in ("n", "n=") or "sample size" in low:
            role = "sample_size"
        elif "significan" in low or low.startswith("p") or "p-value" in low:
            role = "significance"
        elif unit == "%" or any(k in low for k in
                                ("viability", "response", "signal", "intensity",
                                 "absorbance", "value", "mean")):
            role = "y_axis"
        else:
            role = "value"
        header.append({"index": idx, "name": name, "unit": unit, "role": role, "raw": raw})
    return header


def _row_values(cells, header, row_anchor, quote):
    values = {}
    for i, cell in enumerate(cells):
        h = header[i] if i < len(header) else {"name": "col%d" % (i + 1), "unit": None, "role": "value"}
        num = _coerce_number(cell)
        values[h["name"]] = {
            "value": num if num is not None else (cell or "").strip(),
            "raw": (cell or "").strip(),
            "unit": h.get("unit"),
            "role": h.get("role"),
            "anchor": row_anchor,
            "quote": quote,
        }
    return values


def mine_tables(pages, captions=None):
    """抽取表格行（Markdown 管道表 + pdftotext -layout 空格对齐表）。

    输出每行每列的值：header（列名/单位/角色）、rows（row、anchor、cells、
    values{列名: {value, raw, unit, anchor, quote}}）。锚点：
      tab.M/row.K          数据行（K 从 1 起，表头行不计）
      p.N/tab.M/row.K      带页码的可复核锚点（evidence 使用）
      p.N/tab.M            表头
    只有标题没有行的表保留为 caption-only，并明确标注未切分，不假装已解析。
    """
    captions = captions or []
    cap_by_text = {(c.get("text") or "").strip(): c for c in captions}
    tables = []
    cur = None
    pending_caption = None

    def new_caption_only(cap):
        return {"id": None, "page": cap.get("page", 0),
                "caption": cap.get("text") or "",
                "caption_anchor": cap.get("anchor"),
                "caption_id": cap.get("id"),
                "rows": [], "layout": "caption-only", "_raw_rows": [],
                "note": "caption detected but table body not segmented; read the cited page"}

    for pno, page in enumerate(pages, 1):
        for line in page.split("\n"):
            s = line.strip()
            pipe = bool(TABLE_ROW_RE.match(s))
            layout = (not pipe) and _looks_like_table_row(line)
            if pipe or layout:
                cells = ([c.strip() for c in s.strip("|").split("|")] if pipe
                         else _split_layout_cells(line))
                if cur is None:
                    reused = False
                    if (pending_caption is not None and pending_caption in tables
                            and not pending_caption["_raw_rows"]):
                        cur = pending_caption
                        cur["layout"] = "pipe" if pipe else "layout"
                        cur.pop("note", None)
                        reused = True
                    else:
                        cur = {"id": None, "page": pno, "caption": "",
                               "caption_anchor": None, "caption_id": None,
                               "rows": [], "layout": "pipe" if pipe else "layout",
                               "_raw_rows": []}
                    if not reused:
                        tables.append(cur)
                cur["_raw_rows"].append({"page": pno, "raw": s, "cells": cells})
                pending_caption = None
            else:
                cur = None
                match = caption_match(s)
                if match:
                    cap = cap_by_text.get(s)
                    if cap is None:
                        parsed = _parse_caption(s)
                        cap = {"id": None, "page": pno, "text": s,
                               "anchor": "p.%d/cap.?" % pno, **parsed}
                    if cap.get("kind") == "table":
                        pending_caption = new_caption_only(cap)
                        tables.append(pending_caption)

    for idx, t in enumerate(tables, 1):
        t["id"] = "tab.%d" % idx
        if t["layout"] == "caption-only":
            continue
        raw_rows = t["_raw_rows"]
        sep_idx = None
        for i, rr in enumerate(raw_rows):
            cells = [c for c in rr["cells"] if c.strip()]
            if cells and all(SEP_CELL_RE.match(c.strip()) for c in cells):
                sep_idx = i
                break
        header_cells, header_quote = None, ""
        if sep_idx is not None and sep_idx >= 1:
            header_cells = raw_rows[sep_idx - 1]["cells"]
            header_quote = raw_rows[sep_idx - 1]["raw"]
            data_rows = raw_rows[sep_idx + 1:]
        elif raw_rows and not any(re.search(r"\d", c) for c in raw_rows[0]["cells"]):
            header_cells = raw_rows[0]["cells"]
            header_quote = raw_rows[0]["raw"]
            data_rows = raw_rows[1:]
        else:
            data_rows = raw_rows
        header = _header_units(header_cells) if header_cells else []
        t["header"] = header
        t["header_quote"] = header_quote
        t["header_anchor"] = "p.%d/%s" % (t["page"], t["id"]) if header else None
        rows = []
        for k, rr in enumerate(data_rows, 1):
            row_anchor = "%s/row.%d" % (t["id"], k)
            quote = rr["raw"].strip()
            rows.append({"row": k, "page": rr["page"], "anchor": row_anchor,
                         "page_anchor": "p.%d/%s" % (rr["page"], row_anchor),
                         "raw": rr["raw"], "row_quote": quote,
                         "cells": rr["cells"],
                         "values": _row_values(rr["cells"], header, row_anchor, quote)})
        t["rows"] = rows
        t["data_rows"] = len(rows)
        t.pop("_raw_rows", None)
    return tables


def mine_captions(pages):
    caps = []
    seen = set()
    for pno, page in enumerate(pages, 1):
        for line in page.split("\n"):
            s = line.strip()
            if not caption_match(s) or s in seen:
                continue
            seen.add(s)
            parsed = _parse_caption(s)
            caps.append({"id": "cap.%d" % (len(caps) + 1), "page": pno,
                         "text": s, "anchor": "p.%d/cap.%d" % (pno, len(caps) + 1),
                         **parsed})
    return caps


def _axis_unit(phrase):
    for unit in sorted(KNOWN_UNITS, key=len, reverse=True):
        if len(unit) < 2 and unit != "%":
            continue
        if re.search(r"(?<![A-Za-z])%s(?![A-Za-z])" % re.escape(unit), phrase):
            if unit in ("M", "m", "g", "s", "d", "A", "N", "J", "L", "V", "W", "B"):
                continue
            return unit
    return None


def _parse_axis_phrase(axis, phrase, anchor, sentence):
    scale = "not_reported"
    if re.search(r"\blog(?:10|2)?\b|\blogarithmic\b", phrase, re.I):
        scale = "log"
    elif re.search(r"\blinear\b", phrase, re.I):
        scale = "linear"
    label = re.split(r"\s+(?:in|as|on|with|measured)\s+", phrase, 1)[0].strip(" ,.;")
    return {
        "axis": axis,
        "label": label or phrase,
        "unit": _axis_unit(phrase),
        "scale": scale,
        "description": phrase,
        "basis": "text_statement",
        "directly_readable_from_figure": False,
        "tick_values": {"status": "not_reported",
                        "reason": "图中刻度值需读图/OCR，当前仅用文本层，不臆造"},
        "anchor": anchor,
        "quote": sentence,
    }


def mine_axes(units):
    """从正文/图注抽取 x/y 轴含义、单位、尺度，并标明是正文陈述还是图中直读。"""
    axes = []
    seen = set()
    for u in units:
        for k, sent in enumerate(split_sentences(u["text"]), 1):
            for m in re.finditer(r"\b([xy])[- ]axis\b", sent, re.I):
                axis = m.group(1).lower()
                if axis in seen:
                    continue
                rest = re.split(r"[;.]", sent[m.end():], 1)[0].strip()
                rest = re.sub(r"^(?:shows?|indicates?|is|represents?|denotes?|plots?|displays?|gives?)\s+",
                              "", rest, flags=re.I).strip(" ,;")
                if not rest:
                    continue
                seen.add(axis)
                axes.append(_parse_axis_phrase(
                    axis, rest, "p.%d/%s/sent.%d" % (u["page_start"], u["id"], k), sent))
    return axes


def _image_size(raw):
    """只读文件头取宽高（PNG/JPEG/GIF/BMP/WebP），不解码像素。"""
    try:
        if raw[:8] == b"\x89PNG\r\n\x1a\n":
            w, h = struct.unpack(">II", raw[16:24])
            return "png", w, h
        if raw[:6] in (b"GIF87a", b"GIF89a"):
            w, h = struct.unpack("<HH", raw[6:10])
            return "gif", w, h
        if raw[:2] == b"BM":
            w, h = struct.unpack("<ii", raw[18:26])
            return "bmp", abs(w), abs(h)
        if raw[:4] == b"RIFF" and raw[8:12] == b"WEBP":
            if raw[12:16] == b"VP8X":
                w = int.from_bytes(raw[24:27], "little") + 1
                h = int.from_bytes(raw[27:30], "little") + 1
                return "webp", w, h
            return "webp", None, None
        if raw[:2] == b"\xff\xd8":
            i = 2
            while i + 9 < len(raw):
                if raw[i] != 0xFF:
                    i += 1
                    continue
                marker = raw[i + 1]
                if marker in (0xD8, 0xD9):
                    i += 2
                    continue
                seg = int.from_bytes(raw[i + 2:i + 4], "big")
                if marker in (0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7,
                              0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF):
                    h, w = struct.unpack(">HH", raw[i + 5:i + 9])
                    return "jpeg", w, h
                i += 2 + seg
    except Exception:
        pass
    return None, None, None


def probe_image(path):
    """登记图片元数据；像素读数不在本 Skill 能力内，由上层明确列为缺口。"""
    try:
        with open(path, "rb") as fh:
            raw = fh.read(65536)
        sha = hashlib.sha256(open(path, "rb").read()).hexdigest()
    except OSError as exc:
        return {"file": os.path.basename(path), "readable": False,
                "diagnostics": ["image_unreadable: %s" % exc]}
    fmt, width, height = _image_size(raw)
    return {"file": os.path.basename(path), "format": fmt, "width": width,
            "height": height, "bytes": os.path.getsize(path), "sha256": sha,
            "readable": True, "pixel_reading": "not_performed",
            "note": "只登记图片元数据；刻度/图例/数据点像素读数未执行，列为缺口，不臆造数值"}


def _matrix_table(header_cells, data_rows, rel, start_index, page=1, caption=""):
    tid = "tab.%d" % start_index
    header = _header_units([str(c) for c in header_cells])
    header_quote = "| " + " | ".join(str(c) for c in header_cells) + " |"
    rows = []
    for k, cells in enumerate(data_rows, 1):
        cells = ["" if c is None else str(c) for c in cells]
        raw = "| " + " | ".join(cells) + " |"
        anchor = "%s/row.%d" % (tid, k)
        rows.append({"row": k, "page": page, "anchor": anchor,
                     "page_anchor": "p.%d/%s" % (page, anchor),
                     "raw": raw, "row_quote": raw, "cells": cells,
                     "values": _row_values(cells, header, anchor, raw)})
    return {"id": tid, "page": page, "caption": caption or rel,
            "caption_anchor": None, "caption_id": None,
            "layout": "tabular_file", "header": header,
            "header_quote": header_quote, "header_anchor": "p.%d/%s" % (page, tid),
            "rows": rows, "data_rows": len(rows)}


def _xlsx_sheets(path):
    """纯标准库读 xlsx：sharedStrings + 每张工作表 → [[cell,...], ...]。"""
    out = []
    with zipfile.ZipFile(path) as zf:
        names = set(zf.namelist())
        shared = []
        if "xl/sharedStrings.xml" in names:
            root = ET.fromstring(zf.read("xl/sharedStrings.xml"))
            for si in root.iter():
                if si.tag.split("}")[-1] == "si":
                    shared.append("".join(t.text or "" for t in si.iter()
                                          if t.tag.split("}")[-1] == "t"))
        titles = []
        if "xl/workbook.xml" in names:
            root = ET.fromstring(zf.read("xl/workbook.xml"))
            for el in root.iter():
                if el.tag.split("}")[-1] == "sheet":
                    titles.append(el.get("name") or "")
        sheet_names = sorted(n for n in names
                             if re.match(r"xl/worksheets/sheet\d+\.xml$", n))
        for idx, sn in enumerate(sheet_names):
            root = ET.fromstring(zf.read(sn))
            matrix = []
            for row in root.iter():
                if row.tag.split("}")[-1] != "row":
                    continue
                cells = {}
                for c in row:
                    if c.tag.split("}")[-1] != "c":
                        continue
                    col = re.match(r"([A-Z]+)", c.get("r") or "")
                    if not col:
                        continue
                    ci = 0
                    for ch in col.group(1):
                        ci = ci * 26 + (ord(ch) - 64)
                    ci -= 1
                    typ = c.get("t")
                    val = ""
                    if typ == "s":
                        v = next((x for x in c if x.tag.split("}")[-1] == "v"), None)
                        if v is not None and v.text is not None:
                            j = int(v.text)
                            val = shared[j] if 0 <= j < len(shared) else ""
                    elif typ == "inlineStr":
                        val = "".join(t.text or "" for t in c.iter()
                                      if t.tag.split("}")[-1] == "t")
                    else:
                        v = next((x for x in c if x.tag.split("}")[-1] == "v"), None)
                        val = (v.text or "") if v is not None else ""
                    cells[ci] = val
                if cells:
                    width = max(cells) + 1
                    matrix.append([cells.get(i, "") for i in range(width)])
            if matrix:
                out.append((titles[idx] if idx < len(titles) else os.path.basename(sn),
                            matrix))
    return out


def load_tabular(path, rel, start_index):
    """把 CSV/TSV/XLSX 表读成与 mine_tables 相同结构的表；失败返回 ([], 诊断)。"""
    ext = os.path.splitext(path)[1].lower()
    tables, diags = [], []
    try:
        if ext in (".csv", ".tsv"):
            delim = "\t" if ext == ".tsv" else ","
            rows = [r for r in csv.reader(read_text(path).splitlines(), delimiter=delim)
                    if any((c or "").strip() for c in r)]
            if len(rows) >= 2:
                tables.append(_matrix_table(rows[0], rows[1:], rel, start_index,
                                             caption="tabular file: %s" % rel))
        elif ext == ".xlsx":
            for name, matrix in _xlsx_sheets(path):
                if len(matrix) < 2:
                    continue
                tables.append(_matrix_table(matrix[0], matrix[1:], rel,
                                             start_index + len(tables),
                                             caption="xlsx sheet: %s" % name))
    except Exception as exc:  # noqa: BLE001
        diags.append("tabular_unreadable: %s (%s)" % (rel, exc))
    return tables, diags


def build_doc(path, workdir, extractor="auto", max_pages=MAX_PAGES):
    text, meta, pages = extract_any(path, workdir, extractor, max_pages)
    # Markdown 表格行已由 mine_tables 单独解析；从叙述文本剔除，避免坐标轴引文吞掉整张表
    narr_pages = ["\n".join(line for line in p.splitlines()
                            if not line.strip().startswith("|")) for p in pages]
    units = split_units(narr_pages) if narr_pages else []
    meta = dict(meta)
    meta["source_file"] = os.path.basename(path)
    meta["language"] = "zh" if len(CJK_RE.findall(text[:20000])) > 200 else "en"
    captions = mine_captions(narr_pages)
    doc = {
        "meta": meta,
        "pages": [{"page": i + 1, "chars": len(p)} for i, p in enumerate(pages)],
        "units": units,
        "numbers": mine_numbers(units) if units else [],
        "tables": mine_tables(pages, captions),
        "captions": captions,
        "figures": [c for c in captions if c.get("kind") == "figure"],
        "axes": mine_axes(units) if units else [],
        "images": [],
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
