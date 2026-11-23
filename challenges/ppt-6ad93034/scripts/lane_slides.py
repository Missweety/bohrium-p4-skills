#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""lane_slides.py - 演示文稿赛道（slides）页级编排脚本。

从共享层已抽好的 doc.json（页/节/句/数值/表格/图注 + 锚点）出发，产出：

  <output>/deck.md             可编辑演示大纲（逐页：主张/要点/讲稿备注/图表引用）
  <output>/slide_evidence.json 页级证据映射（slide_no/title/claim/evidence[]/needs_review）
  <output>/lane_slides.json    产物清单 + 边界三件套 + 论文主线候选
  <work>/lane_slides.log       运行日志（锚点、产物、降级）

可选导出件（缺失即降级并如实标注）：
  <output>/deck.pptx           python-pptx 生成的可编辑演示稿（含备注）
  <output>/deck.pdf            由 deck.pptx 经 soffice 导出的 PDF
  <output>/preview/slide-*.png 由 pdftoppm 渲染的逐页预览

设计边界（见 references/lane_slides.md）：
  * 脚本只做**确定性抽取与装配**：从 doc.json 抽论文主线候选（章节序列、
    每节关键结论句、图表清单与编号交叉核对、核心数值），并按主线排好页序。
  * 每页主张与讲稿备注取自论文原句（逐字），**由模型复核改写**；
    脚本不生成任何论文里没有的论断、数字或术语。

  python3 scripts/lane_slides.py --input /input --output /app/output --work /app/work \
      [--doc /app/work/doc.json] [--max-slides N] [--no-pptx]
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import traceback

# 禁止在脚本目录下生成 __pycache__（评测方禁止 .pyc / __pycache__）
sys.dont_write_bytecode = True

HERE = os.path.dirname(os.path.abspath(__file__))
LANE = "slides"
DEFAULT_MAX_SLIDES = 14

# ----------------------------------------------------------------- 文本工具

TYPHO = {"‘": "'", "’": "'", "“": '"', "”": '"',
         "–": "-", "—": "-", "−": "-", " ": " "}


def norm(text):
    return re.sub(r"\s+", " ", (text or "")).strip()


def canon(text):
    """与共享层 audit_result.py 同口径的排版归一（引文逐字比对用）。"""
    s = (text or "")
    for k, v in TYPHO.items():
        s = s.replace(k, v)
    s = re.sub(r"-\s+", "", s)
    return re.sub(r"\s+", " ", s).strip()


def split_sentences(text):
    """与共享层 doc_extract.split_sentences 完全一致的切分。

    保持一致才能让本脚本的 sent.K 与 doc.json 里 numbers[] 的 sent.K 对齐
    （否则数值锚点会指向另一个句子）。
    """
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


def trim(text, limit=180):
    """把长句裁到可讲述长度：优先在子句边界断开，截断处标省略号。"""
    t = norm(text)
    if len(t) <= limit:
        return t
    cut = t[:limit]
    for sep in ("；", ";", "，", ",", "、"):
        idx = cut.rfind(sep)
        if idx >= limit // 2:
            return cut[:idx].rstrip() + "…"
    idx = cut.rfind(" ")
    if idx > 0:
        cut = cut[:idx]
    return cut.rstrip(" ,;") + "…"


def first_number(text):
    """取一个适合强调的数值：优先带小数位的量值，其次有意义的整数。

    引用编号（[14, 4, 16]）、图表编号（figure 1 / Table 3）、年份都不算论据，
    先剥掉再找，避免把参考文献序号当成"可强调的数据"。
    """
    t = text or ""
    t = re.sub(r"\[[\d\s,;–-]*\]", " ", t)                       # 引用角标
    t = re.sub(r"\[\s*\d+(?:[\s,;]\d+)*\s*$", " ", t)            # 句末未闭合的角标
    t = re.sub(r"\b(figure|fig|table|tab|section|sec|eq|equation|eqn)\s*\.?\s*\d+",
               " ", t, flags=re.I)                                # 图表/章节编号
    t = re.sub(r"\b[A-Z][A-Za-z]{1,6}\s*['’]\s*\d{2}\b", " ", t)      # 数据集年份（WMT'14）
    nums = re.findall(r"\d+(?:[.,]\d+)*", t)
    if not nums:
        return None
    for n in nums:
        if re.search(r"[.,]\d", n):          # 34.8 / 33.30 / 1,700
            return n
    plain = [n for n in nums if not re.fullmatch(r"(19|20)\d{2}", n)]
    for n in plain:
        if len(n) >= 2:                      # 两位及以上整数，排除 2014 这类年份
            return n
    return None


# ----------------------------------------------------------------- 章节角色

ROLE_KEYWORDS = [
    # 顺序即优先级：越具体越靠前（"Model Analysis" 归分析而非方法）
    ("limitations", r"limitation|threat\s+to\s+validity|failure\s*case|局限|不足"),
    ("conclusion", r"conclusion|concluding|final\s+remark|结论|总结"),
    ("related", r"related\s*work|related\s*studies|literature\s*review|文献综述|相关工作|相关研究"),
    ("abstract", r"^\s*abstract\b|摘要"),
    ("analysis", r"\banalysis\b|\bdiscussion\b|interpret|消融|分析|讨论"),
    ("results", r"experimental\s+results?|results?\b|\bperformance\b|\bevaluation\b|"
                r"\bfindings?\b|\bexperiments?\s+on\b|结果|性能|评测|实验结果"),
    ("setup", r"experimental\s+setup|\bsetup\b|\bdataset\b|\btraining\s+details?\b|"
              r"\bimplementation\b|\bparallelization\b|\bconfig\w*\b|\bexperiments?\b|"
              r"数据|实验设置|训练|实现|配置|实验"),
    ("method", r"\bmethod\w*\b|\bmodel\b|\barchitecture\b|\bframework\b|\bapproach\b|"
               r"\bdecoder\b|\bdecoding\b|\bencod\w+\b|方法|模型|架构|框架|解码"),
    ("intro", r"introduction|引言|绪论|研究背景|背景"),
    ("ack", r"acknowledg|致谢|资助"),
    ("refs", r"^\s*references?\b|参考文献|bibliography"),
]
ROLE_LABELS = {
    "abstract": "研究背景与问题",
    "intro": "研究背景与问题",
    "related": "相关工作",
    "method": "方法",
    "setup": "实验设置",
    "results": "关键结果",
    "analysis": "分析与讨论",
    "limitations": "局限",
    "conclusion": "结论",
    "ack": "致谢",
    "refs": "参考文献",
    "other": "补充材料",
}
# 页序优先级：靠前的角色在页数不够时先被保留
ROLE_PRIORITY = {
    "abstract": 0, "intro": 1, "method": 2, "setup": 3, "results": 4,
    "analysis": 5, "conclusion": 6, "limitations": 7, "related": 8,
    "other": 9, "ack": 10, "refs": 10,
}

RESULT_CUES = (
    "achiev", "outperform", "improv", "increas", "decreas", "reduc", "improv",
    "drop", "rise", "gain", "surpass", "exceed", "reach", "yield", "best",
    "better", "worse", "error rate", "accuracy", "bleu", "f1", "precision",
    "recall", "speed", "faster", "state-of-the-art", "state of the art",
    "compar", "versus", " vs ", "baseline", "表明", "提出", "提高", "降低",
    "优于", "达到", "结果", "提升", "实验",
)
TABLE_CUE = re.compile(r"\b(table|tab\.?|figure|fig\.?)\s*(\d+)", re.I)
CAP_HEAD = re.compile(r"^\s*(figure|fig\.?|table|tab\.?|chart|图|表)\s*([0-9]+|[ivxlc]+)", re.I)


def classify_role(title, fallback=""):
    t = (title or "").strip()
    key = t.lower()
    for role, pat in ROLE_KEYWORDS:
        if re.search(pat, key):
            return role
    return fallback or "other"


def is_noise_title(title):
    """判断章节标题是否是版面噪声（表格碎片、图坐标、参考文献残行）。"""
    t = (title or "").strip()
    if not t:
        return True
    if t.lower() == "(preamble)":
        return False
    if "|" in t:
        return True
    if re.search(r"\s{3,}", t):
        return True           # 多栏版面对齐产生的空隙（表格/图坐标残片）
    if re.search(r"[∈∑∫±≤≥→←≈⊗]", t):
        return True
    letters = sum(1 for c in t if c.isalpha())
    digits = sum(1 for c in t if c.isdigit())
    if digits > letters:
        return True
    words = t.split()
    if len(words) == 1:
        # 单个词：纯符号/数字是噪声；纯字母标题（Abstract / Conclusion）保留
        return not (t.replace(" ", "").isalpha() and t[:1].isupper())
    if re.search(r"\s[a-z]$", t):
        return True           # 被行尾截断的词
    if len(words) <= 3 and t.endswith((".", ",", ":", ";", ")")):
        return True
    if re.match(r"^\d+(\.\d+)*\.?\s+[A-Z]", t) and len(words) >= 2:
        return False
    if len(words) >= 3 and t[:1].isupper():
        return False
    return True


AUTHOR_STOP = ("arxiv", "http", "@", "university", "google", "microsoft",
               "copyright", "all rights", "proceedings", "conference")


def paper_title(doc):
    """从首页版面抽论文题名（跳过 arXiv 戳、作者/邮箱/机构行）。"""
    text = doc.get("text", "") or ""
    page1 = text.split("\f")[0] if "\f" in text else text
    lines = [l.strip() for l in page1.splitlines()]
    title_lines = []
    for line in lines:
        if not line:
            if title_lines:
                break
            continue
        low = line.lower()
        if any(stop in low for stop in AUTHOR_STOP):
            break
        if re.search(r"\b\d{4}\b", line) and len(line) < 40:
            break
        # 作者行：三段以上"首字母+姓氏"或邮箱
        if len(re.findall(r"[A-Z][a-z]+ [A-Z][a-z]+", line)) >= 3:
            break
        if re.search(r"abstract", low):
            break
        title_lines.append(line)
        if len(title_lines) >= 2:
            break
    title = norm(" ".join(title_lines))
    return title[:200]


# ----------------------------------------------------------------- doc 载入

def load_json(path):
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def read_case(input_dir):
    path = os.path.join(input_dir, "case.json")
    if os.path.isfile(path):
        try:
            return load_json(path), path
        except Exception:
            return {}, path
    return {}, path


def case_id_of(case, input_dir):
    for key in ("case_id", "id", "task_id", "name"):
        val = case.get(key)
        if isinstance(val, (str, int)) and str(val).strip():
            return str(val).strip()
    return os.path.basename(os.path.abspath(input_dir)) or "case"


def find_max_slides(case):
    """从 case.json 里找固定页数上限（多种可能的写法）。"""
    hits = []
    keys = ("max_slides", "slide_limit", "max_slide_count", "slide_count_max",
            "slides_max", "num_slides", "slide_count", "slides", "page_limit",
            "max_pages", "页数上限", "幻灯片张数", "页数")
    stack = [case]
    seen = 0
    while stack and seen < 400:
        node = stack.pop()
        seen += 1
        if isinstance(node, dict):
            for k, v in node.items():
                if isinstance(v, (dict, list)):
                    stack.append(v)
                elif isinstance(v, (int, float)) and k.lower() in keys:
                    hits.append(int(v))
                elif isinstance(v, str) and k.lower() in keys:
                    m = re.search(r"\d+", v)
                    if m:
                        hits.append(int(m.group(0)))
        elif isinstance(node, list):
            for item in node:
                if isinstance(item, (dict, list)):
                    stack.append(item)
    hits = [h for h in hits if 3 <= h <= 120]
    return min(hits) if hits else None


def find_first(doc, names):
    """在 case.json 中按候选键名取第一个非空值。"""
    stack = [doc]
    seen = 0
    while stack and seen < 400:
        node = stack.pop()
        seen += 1
        if isinstance(node, dict):
            for k, v in node.items():
                low = str(k).lower()
                if any(n in low for n in names) and isinstance(v, (str, int, float)):
                    if str(v).strip():
                        return str(v).strip()
                if isinstance(v, (dict, list)):
                    stack.append(v)
        elif isinstance(node, list):
            for item in node:
                if isinstance(item, (dict, list)):
                    stack.append(item)
    return ""


def discover_primary(input_dir):
    """在输入目录里挑主材料（与共享层 run_case.py 同思路）。"""
    skip = {"task.md", "case.json", "readme.md", "challenge.json", "config.json"}
    docs = []
    for dirpath, dirnames, filenames in os.walk(input_dir, followlinks=False):
        dirnames[:] = [d for d in dirnames if not d.startswith(".") and d != "__pycache__"]
        for name in sorted(filenames):
            if name.startswith("."):
                continue
            ext = os.path.splitext(name)[1].lower()
            if ext in (".pdf", ".tex", ".docx", ".md", ".txt"):
                full = os.path.join(dirpath, name)
                if os.path.isfile(full) and not os.path.islink(full):
                    docs.append(full)
    for d in docs:
        if os.path.basename(d).lower() not in skip:
            return d
    return docs[0] if docs else None


def load_doc(explicit, work_dir, input_dir):
    """优先用共享层已抽好的 doc.json；没有（或不可用）则就地调用 doc_extract 抽一份。

    共享层 doc_extract 的 --input 必须是**文件**路径；若上游误传目录，会得到
    tier=unreadable 的空 doc.json。此时这里不直接失败，而是回退到自行抽取，
    保证 demo / 评测链路能继续跑完。
    """
    candidates = []
    if explicit:
        candidates.append(explicit)
    candidates.append(os.path.join(work_dir, "doc.json"))
    for path in candidates:
        if path and os.path.isfile(path):
            try:
                doc = load_json(path)
            except Exception as exc:
                return {}, path, "unreadable: %s" % exc
            if doc.get("units") or doc.get("pages"):
                return doc, path, "given"
            # 空壳 doc.json（上游抽取失败）：继续尝试自行抽取
            continue
    # 兜底：调用共享层 doc_extract
    primary = discover_primary(input_dir)
    if not primary:
        return {}, "", "no-material"
    try:
        if HERE not in sys.path:
            sys.path.insert(0, HERE)
        import doc_extract
        doc = doc_extract.build_doc(primary, os.path.join(work_dir, "_extract"))
        path = os.path.join(work_dir, "doc.json")
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(doc, fh, ensure_ascii=False)
        return doc, path, "extracted"
    except Exception as exc:  # noqa: BLE001
        return {}, "", "extract-failed: %s" % str(exc)[:200]


# ----------------------------------------------------------------- 句子层

def unit_sentences(unit):
    """返回 [{k, text, page, offset}]，k 与共享层 sent.K 对齐。"""
    text = unit.get("text", "") or ""
    spans = unit.get("spans") or []

    def page_at(offset):
        for start, end, pno in spans:
            if start <= offset < end:
                return pno
        return spans[-1][2] if spans else unit.get("page_start", 1)

    out = []
    for k, sent in enumerate(split_sentences(text), 1):
        probe = sent[:80]
        off = text.find(probe) if probe else -1
        if off < 0:
            off = text.find(sent[:40]) if len(sent) > 40 else text.find(sent)
        page = page_at(off) if off >= 0 else unit.get("page_start", 1)
        out.append({"k": k, "text": sent, "page": page, "offset": off})
    return out


def abstract_cut(unit):
    """preamble 单元中 "Abstract" 之后的字符偏移；之前的是题名/作者/机构行。

    只做**过滤**不做重编号，保证 sent.K 与共享层 numbers[] 的锚点一致。
    """
    if (unit.get("title") or "").strip().lower() != "(preamble)":
        return 0
    m = re.search(r"\bAbstract\b", unit.get("text", "") or "")
    return m.end() if m else 0


def quote_ok(unit_text, quote):
    return canon(quote) in canon(unit_text)


def safe_quote(unit_text, quote):
    """保证 quote 在章节文本中逐字可见（否则逐字退化为最长命中前缀）。"""
    if quote_ok(unit_text, quote):
        return quote, True
    cut = quote
    while len(cut) > 24:
        cut = cut[:-1].rstrip()
        if quote_ok(unit_text, cut):
            return cut, True
    return quote, False


def score_sentence(sent, role, in_numbers):
    """给句子打分：越像"结论/关键结果"分越高。"""
    t = sent.lower()
    s = 0.0
    for cue in RESULT_CUES:
        if cue in t:
            s += 2.0
            break
    if re.search(r"\d", sent):
        s += 1.2
    if in_numbers:
        s += 1.0
    if re.search(r"\b(table|figure|tab\.?|fig\.?)\s*\d+", sent, re.I):
        s += 1.0
    if re.search(r"\b(than|compared|versus|vs\.?|baseline|ablation)\b", t):
        s += 0.8
    if re.search(r"(相比|相对于|优于|基线|对比)", sent):
        s += 0.8
    if role in ("results", "conclusion", "analysis"):
        s += 1.5
    elif role in ("abstract", "intro"):
        s += 0.8
    if 40 <= len(sent) <= 260:
        s += 1.0
    if len(sent) > 400:
        s -= 1.5
    if len(sent) < 25:
        s -= 1.5
    # 公式/符号残片不是可讲述的句子
    alpha = sum(1 for c in sent if c.isalpha())
    if alpha < len(sent) * 0.55:
        s -= 3.0
    if re.search(r"[{}()\[\]]\s*[a-zA-Z]\s*[=,]", sent):
        s -= 1.5
    # 跨栏/跨行截断出来的半句（"[1], who combine ..." / "1), we believe ..."）
    if not sent[:1].isalpha():
        s -= 3.0
    return s


def is_speakable(sent, min_len=40, max_len=330):
    """能否作为可讲述的一句（过滤公式残片、目录残片、过短句）。"""
    t = (sent or "").strip()
    if not (min_len <= len(t) <= max_len):
        return False
    if re.search(r"[∈∑∫⊗]", t):
        return False
    if not t[:1].isalpha():
        return False           # 公式/符号开头（", xT ), a standard ..."）
    alpha = sum(1 for c in t if c.isalpha())
    if alpha < len(t) * 0.6:
        return False
    words = t.split()
    if len(words) < 6:
        return False
    # 至少有一个成词的英文 token
    if not any(re.match(r"^[A-Za-z][A-Za-z'-]{2,}$", w) for w in words):
        return False
    return True


# ----------------------------------------------------------------- 主线候选

def build_spine(doc):
    """章节序列（去噪）+ 每节关键结论句 + 角色。"""
    spine = []
    for unit in doc.get("units", []):
        title = (unit.get("title") or "").strip()
        if is_noise_title(title):
            continue
        role = classify_role(title, unit.get("role", "other"))
        if role == "other" and unit.get("role") in ROLE_PRIORITY:
            role = unit["role"]
        sents = unit_sentences(unit)
        if not sents:
            continue
        cut = abstract_cut(unit)
        if cut:
            sents = [s for s in sents if s["offset"] >= cut]
        if not sents:
            continue
        # 本节正文全是表格/图形碎片（无成句正文）→ 标记为不可讲述，交模型处理
        speakable = [s for s in sents if is_speakable(s["text"])]
        if not speakable:
            spine.append({
                "sec_id": unit.get("id"), "title": title, "role": role,
                "role_label": ROLE_LABELS.get(role, "补充材料"),
                "page_start": unit.get("page_start"), "page_end": unit.get("page_end"),
                "words": unit.get("words", 0), "sentences": sents, "key_sentences": [],
                "no_prose": True,
            })
            continue
        numbers_here = set()
        for n in doc.get("numbers", []):
            if n.get("section") == unit.get("id"):
                numbers_here.add(n.get("sentence"))
        scored = sorted(
            ((score_sentence(s["text"], role, s["k"] in numbers_here), s) for s in sents
             if is_speakable(s["text"])),
            key=lambda kv: -kv[0])
        # 可讲述句不足 3 句时，用含数值的句子补位（数值句常带关键指标）
        if len(scored) < 3:
            extra = [(score_sentence(s["text"], role, s["k"] in numbers_here), s)
                     for s in sents
                     if s["k"] in numbers_here and s["k"] not in {x["k"] for _c, x in scored}]
            scored = sorted(scored + extra, key=lambda kv: -kv[0])
        # 标题没给出角色时，用正文内容兜底（结果型小节常被归到 other）
        if role == "other" and scored:
            for _sc, _s in scored[:3]:
                top = _s["text"].lower()
                if re.search(r"\d", top) and any(c in top for c in RESULT_CUES):
                    role = "results"
                    break
        spine.append({
            "sec_id": unit.get("id"),
            "title": title,
            "role": role,
            "role_label": ROLE_LABELS.get(role, "补充材料"),
            "page_start": unit.get("page_start"),
            "page_end": unit.get("page_end"),
            "words": unit.get("words", 0),
            "sentences": sents,
            "key_sentences": [{"k": s["k"], "text": s["text"], "page": s["page"],
                               "score": round(sc, 2)} for sc, s in scored[:3]],
        })
    return spine


def build_caption_index(doc):
    """图注清单 + 表格正文关联 + 与正文引用的编号交叉核对。"""
    caps = []
    for c in doc.get("captions", []):
        text = c.get("text", "") or ""
        m = CAP_HEAD.match(text)
        label, num = None, None
        if m:
            label = m.group(1).lower()
            label = {"fig.": "figure", "fig": "figure", "tab.": "table",
                     "tab": "table", "图": "figure", "表": "table"}.get(label, label)
            num = m.group(2)
        caps.append({
            "anchor": c.get("anchor"),
            "page": c.get("page"),
            "text": text,
            "label": label,
            "num": num,
            "ref": ("%s %s" % (label.capitalize(), num)) if (label and num) else None,
            "body_table": None,
            "cited_from": [],
        })

    # 正文里对图/表的编号引用
    mentions = []
    for unit in doc.get("units", []):
        for s in unit_sentences(unit):
            for m in TABLE_CUE.finditer(s["text"]):
                word = m.group(1).lower()
                label = "table" if word.startswith(("table", "tab")) else "figure"
                mentions.append({
                    "label": label, "num": m.group(2),
                    "anchor": "p.%d/%s/sent.%d" % (s["page"], unit.get("id"), s["k"]),
                    "raw": m.group(0),
                })

    # 表格正文：caption-only 表条目往前找最近的同页 layout 表
    tables = doc.get("tables", [])
    for cap in caps:
        if cap["label"] != "table":
            continue
        twin = None
        for t in tables:
            if t.get("caption") and norm(t["caption"]) == norm(cap["text"]):
                twin = t
                break
        if twin is None:
            continue
        twin_num = int(re.sub(r"\D", "", twin["id"]) or 0)
        best = None
        for t in tables:
            if t.get("layout") == "caption-only" or not t.get("rows"):
                continue
            if t.get("page") != twin.get("page"):
                continue
            tnum = int(re.sub(r"\D", "", t["id"]) or 0)
            if tnum < twin_num and (best is None or tnum > best[0]):
                best = (tnum, t)
        if best:
            cap["body_table"] = best[1]["id"]

    for cap in caps:
        if not cap["ref"]:
            continue
        for m in mentions:
            if m["label"] == cap["label"] and str(m["num"]) == str(cap["num"]):
                cap["cited_from"].append(m["anchor"])

    orphan_tables = [t["id"] for t in tables
                     if t.get("rows") and not any(c.get("body_table") == t["id"] for c in caps)]
    caption_only = [t["id"] for t in tables if t.get("layout") == "caption-only"]
    return caps, mentions, orphan_tables, caption_only


# ----------------------------------------------------------------- 页序装配

def make_page(spine_sec, page_no, doc, caps):
    """由一个章节生成一页的候选内容（主张/要点/讲稿/图表）。"""
    unit_text = ""
    for unit in doc.get("units", []):
        if unit.get("id") == spine_sec["sec_id"]:
            unit_text = unit.get("text", "") or ""
            break

    evidence = []
    bullets = []
    claim = ""
    used = set()

    for item in spine_sec["key_sentences"]:
        q, ok = safe_quote(unit_text, item["text"])
        loc = "p.%d/%s/sent.%d" % (item["page"], spine_sec["sec_id"], item["k"])
        fig_ref, tab_ref = None, None
        m = TABLE_CUE.search(item["text"])
        if m:
            word = m.group(1).lower()
            if word.startswith(("table", "tab")):
                tab_ref = "%s %s" % ("Table", m.group(2))
            else:
                fig_ref = "%s %s" % ("Figure", m.group(2))
        ev = {
            "locator": loc,
            "quote": q,
            "kind": "claim" if not claim else "bullet",
            "figure_ref": fig_ref,
            "table_ref": tab_ref,
            "verbatim_checked": ok,
        }
        if not claim:
            claim = trim(item["text"], 200)
            ev["kind"] = "claim"
            evidence.append(ev)
        else:
            if len(bullets) < 4:
                bullets.append(trim(item["text"], 150))
                ev["kind"] = "bullet"
                evidence.append(ev)
        used.add(item["k"])
        if len(bullets) >= 4:
            break

    # 要点不够时，从本节其余句子补齐（保持与主张不同）
    if len(bullets) < 3:
        for s in spine_sec["sentences"]:
            if s["k"] in used:
                continue
            if len(s["text"]) < 40 or len(s["text"]) > 320:
                continue
            q, ok = safe_quote(unit_text, s["text"])
            bullets.append(trim(s["text"], 150))
            evidence.append({
                "locator": "p.%d/%s/sent.%d" % (s["page"], spine_sec["sec_id"], s["k"]),
                "quote": q, "kind": "bullet", "figure_ref": None, "table_ref": None,
                "verbatim_checked": ok,
            })
            used.add(s["k"])
            if len(bullets) >= 3:
                break

    # 本页的图表引用：优先取正文在本节明确引用过的图/表，
    # 其次取图注落在本节页范围内、且未被其它节引用的图/表（避免张冠李戴）。
    chart_refs = []
    cited_here = []
    for cap in caps:
        if not cap["ref"]:
            continue
        for loc in cap["cited_from"]:
            if "/%s/sent." % spine_sec["sec_id"] in loc:
                cited_here.append(cap)
                break
    if not cited_here:
        for cap in caps:
            if cap["page"] is None:
                continue
            if not (spine_sec["page_start"] <= cap["page"] <= spine_sec["page_end"]):
                continue
            if cap["cited_from"]:
                continue          # 已被其它节引用，不在这里重复挂
            cited_here.append(cap)
    seen_caps = set()
    for cap in cited_here:
        if cap["anchor"] in seen_caps:
            continue
        seen_caps.add(cap["anchor"])
        chart_refs.append(cap)

    for cap in chart_refs:
        evidence.append({
            "locator": cap["anchor"],
            "quote": cap["text"],
            "kind": "caption",
            "figure_ref": cap["ref"] if cap["label"] == "figure" else None,
            "table_ref": cap["ref"] if cap["label"] == "table" else None,
            "verbatim_checked": True,
        })

    notes = make_notes(spine_sec, evidence, doc, unit_text)
    return {
        "slide_no": page_no,
        "title": spine_sec["title"],
        "role": spine_sec["role"],
        "role_label": spine_sec["role_label"],
        "sec_id": spine_sec["sec_id"],
        "pages": [spine_sec["page_start"], spine_sec["page_end"]],
        "claim": claim,
        "bullets": bullets,
        "notes": notes,
        "chart_refs": [{"ref": c["ref"] or c["text"][:40], "anchor": c["anchor"],
                        "caption": trim(c["text"], 140),
                        "body_table": c.get("body_table"),
                        "cited_from": c["cited_from"]} for c in chart_refs],
        "evidence": evidence,
        "source_sections": [spine_sec["sec_id"]],
        "needs_review": False,
        "review_reasons": [],
    }


def make_notes(spine_sec, evidence, doc, unit_text):
    """讲稿备注三件套：过渡 / 强调 / 被问到时（内容全部来自论文原句）。"""
    claim_ev = next((e for e in evidence if e.get("kind") == "claim"), None)
    bullet_evs = [e for e in evidence if e.get("kind") == "bullet"]

    # 本节里没被页面用掉的、可讲述的句子（讲稿素材，与页面文字不重复）
    used_keys = set()
    for ev in bullet_evs + ([claim_ev] if claim_ev else []):
        m = re.search(r"sent\.(\d+)", ev.get("locator", ""))
        if m:
            used_keys.add(int(m.group(1)))
    spare = [s for s in spine_sec["sentences"]
             if s["k"] not in used_keys and is_speakable(s["text"], 45, 300)]

    # 强调：页面原句里的数字（逐字，不做任何换算）
    emph = None
    for ev in [claim_ev] + bullet_evs:
        if not ev:
            continue
        tok = first_number(ev.get("quote", ""))
        if tok:
            emph = "%s（%s）" % (tok, ev["locator"])
            break
    if emph is None and spare:
        tok = first_number(spare[0]["text"])
        if tok:
            emph = "%s（p.%d/%s/sent.%d）" % (tok, spare[0]["page"],
                                              spine_sec["sec_id"], spare[0]["k"])
    if emph is None:
        if claim_ev:
            emph = "原文「%s」（%s）" % (trim(claim_ev.get("quote", ""), 90),
                                        claim_ev["locator"])
        else:
            emph = "回到本节主张原文（%s）" % spine_sec["sec_id"]

    # 被问到时：同节里未被页面使用、且可讲述的一句 + 其锚点
    backup = None
    for s in spare:
        if emph.endswith("sent.%d）" % s["k"]):
            continue
        backup = "%s（p.%d/%s/sent.%d）" % (trim(s["text"], 150), s["page"],
                                            spine_sec["sec_id"], s["k"])
        break
    if backup is None and spare:
        s = spare[0]
        backup = "%s（p.%d/%s/sent.%d）" % (trim(s["text"], 150), s["page"],
                                            spine_sec["sec_id"], s["k"])
    if backup is None:
        first_ev = (claim_ev or (evidence[0] if evidence else None))
        loc = first_ev.get("locator") if first_ev else spine_sec["sec_id"]
        backup = "回到本节原文：%s（%s）" % (trim(spine_sec["title"], 50), loc)
    return {"transition": "", "emphasis": emph, "backup": backup}


def merge_pages(a, b):
    """页数不够时合并相邻同角色页：主张取前者，要点合并。"""
    merged = dict(a)
    merged["bullets"] = (a["bullets"] + b["bullets"])[:6]
    merged["evidence"] = a["evidence"] + b["evidence"]
    merged["chart_refs"] = a["chart_refs"] + [c for c in b["chart_refs"]
                                              if c["anchor"] not in
                                              [x["anchor"] for x in a["chart_refs"]]]
    merged["source_sections"] = a["source_sections"] + b["source_sections"]
    merged["title"] = a["title"] if a["role"] == b["role"] else "%s / %s" % (a["title"], b["title"])
    merged["notes"] = dict(a["notes"])
    merged["notes"]["backup"] = a["notes"].get("backup") or b["notes"].get("backup")
    merged["review_reasons"] = a["review_reasons"] + b["review_reasons"]
    return merged


def plan_pages(spine, doc, caps, max_slides):
    """按主线排页：标题页 + 章节页（必要时合并/降级为备用页）。"""
    pages = []
    appendix = []
    title = paper_title(doc)

    # 标题页（论文题名 + 摘要里的核心主张）
    front = spine[0] if spine else None
    if front:
        p = make_page(front, 1, doc, caps)
        p["role"] = "title"
        p["role_label"] = "开场"
        p["title"] = title or front["title"]
        p["notes"]["transition"] = "开场：先讲清本文要回答的问题。"
        p["chart_refs"] = []
        p["evidence"] = [e for e in p["evidence"] if e.get("kind") != "caption"]
        pages.append(p)

    body_spine = spine[1:] if front else spine
    for sec in body_spine:
        if sec["role"] in ("ack", "refs"):
            appendix.append({"title": sec["title"], "sec_id": sec["sec_id"],
                             "role": sec["role"], "reason": "致谢/参考文献不做正文页"})
            continue
        if sec.get("no_prose"):
            appendix.append({"title": sec["title"], "sec_id": sec["sec_id"],
                             "role": sec["role"],
                             "reason": "本节抽取到的只有表格/图形碎片，没有成句正文，"
                                       "无法自动成页（模型可据原文补写或并入相邻页）"})
            continue
        pages.append(make_page(sec, len(pages) + 1, doc, caps))

    # 讲稿补白：某节句子太少、被问到时只能"回到本节原文"时，
    # 从全文里另找一句可讲述、且未被任何页面用过的原句做备用证据。
    used_global = set()
    for p in pages:
        for ev in p.get("evidence", []):
            m = re.search(r"/(sec\.\d+)/sent\.(\d+)", ev.get("locator", ""))
            if m:
                used_global.add((m.group(1), int(m.group(2))))
    pool = []
    for sec in spine:
        for s in sec.get("sentences", []):
            key = (sec["sec_id"], s["k"])
            if key in used_global:
                continue
            if not is_speakable(s["text"], 45, 300):
                continue
            pool.append((sec, s))
    if pool:
        for p in pages:
            if not p["notes"]["backup"].startswith("回到本节原文"):
                continue
            for sec, s in pool:
                if sec["sec_id"] == p.get("sec_id"):
                    continue
                p["notes"]["backup"] = "%s（p.%d/%s/sent.%d）" % (
                    trim(s["text"], 150), s["page"], sec["sec_id"], s["k"])
                # 跨节借用时，锚点要落在真实的节上，不能挂在本页的 sec 上
                unit_text = ""
                for u in doc.get("units", []):
                    if u.get("id") == sec["sec_id"]:
                        unit_text = u.get("text", "") or ""
                        break
                q, ok = safe_quote(unit_text, s["text"])
                p["evidence"].append({
                    "locator": "p.%d/%s/sent.%d" % (s["page"], sec["sec_id"], s["k"]),
                    "quote": q, "kind": "backup",
                    "figure_ref": None, "table_ref": None,
                    "verbatim_checked": ok,
                })
                if sec["sec_id"] not in p["source_sections"]:
                    p["source_sections"].append(sec["sec_id"])
                pool.remove((sec, s))
                break

    # 页数收敛：先合并相邻同角色页，再把低优先级页降级为备用页
    def renumber():
        for i, p in enumerate(pages, 1):
            p["slide_no"] = i

    merges = 0
    guard = 0
    while len(pages) > max_slides and guard < 60:
        guard += 1
        cand = None
        for i in range(len(pages) - 1):
            a, b = pages[i], pages[i + 1]
            if a.get("role") == b.get("role") and a.get("role") in ("setup", "other", "results", "method"):
                cand = i
                break
        if cand is not None:
            pages[cand:cand + 2] = [merge_pages(pages[cand], pages[cand + 1])]
            merges += 1
            renumber()
            continue
        drop = None
        for i in range(len(pages) - 1, 0, -1):
            if pages[i].get("role") in ("related", "other", "analysis"):
                drop = i
                break
        if drop is None:
            drop = len(pages) - 1
        moved = pages.pop(drop)
        appendix.append({"title": moved["title"], "sec_id": moved["sec_id"],
                         "role": moved["role"],
                         "reason": "页数上限 %d，本页降级为备用页/问答素材" % max_slides})
        renumber()

    # 过渡语：承接上一页
    for i, p in enumerate(pages):
        if i == 0:
            continue
        prev = pages[i - 1]
        p["notes"]["transition"] = "承接上一页「%s」，转入「%s」。" % (
            trim(prev["title"], 40), trim(p["title"], 40))
    return pages, appendix, merges


# ----------------------------------------------------------------- 复核标记

def flag_reviews(pages, caps, mentions, doc, spine):
    """给需要模型/人工复核的页打 needs_review 标记（真实缺口，不写空话）。"""
    reasons = {}
    cap_refs = {c["ref"] for c in caps if c.get("ref")}
    for m in mentions:
        ref = "%s %s" % ("Table" if m["label"] == "table" else "Figure", m["num"])
        if ref not in cap_refs:
            reasons.setdefault(m["anchor"], []).append(
                "正文引用了 %s，但图注清单中找不到同编号图注" % ref)

    for p in pages:
        rs = []
        for ev in p["evidence"]:
            if ev.get("verbatim_checked") is False:
                rs.append("引文未能在该锚点段落逐字命中：%s" % ev.get("locator"))
            for key in ("figure_ref", "table_ref"):
                ref = ev.get(key)
                if ref and ref not in cap_refs:
                    rs.append("页面引用的 %s 在论文图注清单中不存在" % ref)
            loc = ev.get("locator", "")
            if loc.split("/")[0:1] and loc.startswith("p."):
                m = re.match(r"p\.(\d+)", loc)
                if m and int(m.group(1)) > len(doc.get("pages", [])):
                    rs.append("锚点页码超出抽取范围：%s" % loc)
        for cr in p["chart_refs"]:
            if cr.get("body_table") is None and cr.get("ref", "").startswith("Table"):
                rs.append("表 %s 的正文未能自动切分，需人工核对行数据" % cr.get("ref"))
            if not cr.get("cited_from"):
                rs.append("%s 未在正文被明确引用，需确认编号" % (cr.get("ref") or cr.get("anchor")))
        if not p["bullets"]:
            rs.append("本节可用要点不足，需人工补充")
        elif len(p["bullets"]) < 2:
            rs.append("本节可抽取的要点不足 2 条，页面单薄，需人工补充或与相邻页合并")
        if not p["claim"]:
            rs.append("未能抽到可用主张句，需人工补写")
        p["review_reasons"] = sorted(set(rs))
        p["needs_review"] = bool(rs)
    return pages


# ----------------------------------------------------------------- 落盘

def deck_md(pages, appendix, spine, meta):
    lines = []
    lines.append("# 论文转学术 PPT｜演示大纲（机器抽取初稿，待模型复核）")
    lines.append("")
    lines.append("> 本文件由 `scripts/lane_slides.py` 从共享层 `doc.json` 自动装配，"
                 "是**初稿**：每页主张与讲稿备注均为论文原句/原片段抽取，"
                 "**须由模型复核改写**后定稿。逐字引文与锚点见 `slide_evidence.json`。")
    lines.append("")
    lines.append("- 源文件：`%s`" % meta.get("source_file", ""))
    lines.append("- 抽取层级：`%s`（%s 页 / %d 个章节单元 / %d 张表 / %d 条图注 / %d 个数值候选）"
                 % (meta.get("tier", "?"), meta.get("pages", 0), meta.get("units", 0),
                    meta.get("tables", 0), meta.get("captions", 0), meta.get("numbers", 0)))
    lines.append("- 页数：%d（上限 %s）" % (len(pages), meta.get("max_slides")))
    lines.append("- 锚点规范：`p.N` 页码 · `sec.X` 章节单元 · `sent.K` 句 · "
                 "`tab.M/row.K` 表与行 · `cap.M` 图注")
    lines.append("")
    lines.append("## 页面索引")
    lines.append("")
    lines.append("| 页 | 叙事角色 | 页面标题 | 主来源 | 图表引用 | 待复核 |")
    lines.append("|---|---|---|---|---|---|")
    for p in pages:
        charts = "、".join(c.get("ref") or c.get("anchor") for c in p["chart_refs"]) or "—"
        lines.append("| %d | %s | %s | %s | %s | %s |" % (
            p["slide_no"], p["role_label"], trim(p["title"], 60),
            "、".join(p["source_sections"]), charts,
            "是" if p["needs_review"] else "否"))
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("## 论文主线（脚本抽取的候选骨架，供模型取舍）")
    lines.append("")
    lines.append("| 章节 | 角色 | 标题 | 页 | 候选关键句锚点 |")
    lines.append("|---|---|---|---|---|")
    for s in spine:
        anchors = "、".join("p.%d/%s/sent.%d" % (k["page"], s["sec_id"], k["k"])
                            for k in s["key_sentences"][:2])
        lines.append("| %s | %s | %s | %s-%s | %s |" % (
            s["sec_id"], s["role_label"], trim(s["title"], 50),
            s["page_start"], s["page_end"], anchors))
    lines.append("")
    for p in pages:
        lines.append("---")
        lines.append("")
        lines.append("## 第 %d 页｜%s" % (p["slide_no"], p["title"]))
        lines.append("")
        lines.append("- **叙事角色**：%s" % p["role_label"])
        lines.append("- **主张（论文原句抽取，待模型改写）**：%s" % (p["claim"] or "—"))
        lines.append("- **要点**：")
        if p["bullets"]:
            for b in p["bullets"]:
                lines.append("  - %s" % b)
        else:
            lines.append("  - （本节未抽到可讲述要点，见 slide_evidence.json 的待复核项）")
        lines.append("- **讲稿备注**：")
        lines.append("  - 过渡：%s" % (p["notes"].get("transition") or "承接上一页。"))
        lines.append("  - 强调：%s" % p["notes"].get("emphasis", ""))
        lines.append("  - 被问到时：%s" % p["notes"].get("backup", ""))
        if p["chart_refs"]:
            lines.append("- **图表引用**：")
            for c in p["chart_refs"]:
                cited = ("；正文引用位置 %s" % "、".join(c["cited_from"])) if c["cited_from"] else \
                    "；正文未检索到明确引用，需确认编号"
                lines.append("  - %s（%s）%s" % (c.get("ref") or "图/表", c["anchor"], cited))
        else:
            lines.append("- **图表引用**：本节无对应图/表")
        lines.append("- **本页证据锚点**：%s" % "、".join(
            e["locator"] for e in p["evidence"]) or "—")
        if p["needs_review"]:
            lines.append("- **⚠ 待复核**：")
            for r in p["review_reasons"]:
                lines.append("  - %s" % r)
        lines.append("")
    if appendix:
        lines.append("---")
        lines.append("")
        lines.append("## 备用页候选（未成页，可用于问答准备）")
        lines.append("")
        for a in appendix:
            lines.append("- %s（%s）—— %s" % (a["title"], a["sec_id"], a["reason"]))
        lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("## 定稿自检（模型改写后逐条确认）")
    lines.append("")
    lines.append("- [ ] 每页一个主张，且主张能在论文里找到对应原句/图表")
    lines.append("- [ ] 页面上的数字、单位、方法名与论文一致，未换算、未取整")
    lines.append("- [ ] 图/表编号与正文引用一致，未引用不存在的图表")
    lines.append("- [ ] 讲稿备注不是页面文字的复述")
    lines.append("- [ ] 页数不超过上限，受众与时长匹配")
    lines.append("- [ ] 待复核项已逐条处理")
    lines.append("")
    return "\n".join(lines)


def boundary_fields(case_id, artifacts, sources, uncertainty, change_log, status):
    return {
        "lane": LANE,
        "case_id": case_id,
        "status": status,
        "artifacts": artifacts,
        "sources": sources,
        "uncertainty": uncertainty,
        "change_log": change_log,
    }


def artifact_entry(out_dir, name, kind, degraded=None):
    path = os.path.join(out_dir, name)
    size = os.path.getsize(path) if os.path.isfile(path) else 0
    return {"path": name, "kind": kind, "bytes": size, "degraded": degraded}


# ----------------------------------------------------------------- 可选导出

def _file_hash(path):
    """小文件内容指纹（用于识别"自己上一轮产出的 deck.pptx"）。"""
    try:
        import hashlib
        h = hashlib.sha1()
        with open(path, "rb") as fh:
            h.update(fh.read())
        return h.hexdigest()
    except Exception:  # noqa: BLE001
        return None


def find_template(input_dir, exclude_dir=None):
    """在输入目录里找组织方给定的母版/版式模板 pptx。

    exclude_dir：产物输出目录（输出目录与输入目录同形时，避免把自己生成的
    deck.pptx 当成模板再套一层，保证同输入同输出可重复跑）。
    """
    found = []
    excl = os.path.abspath(exclude_dir) if exclude_dir else None
    for dirpath, dirnames, filenames in os.walk(input_dir, followlinks=False):
        dirnames[:] = [d for d in dirnames if not d.startswith(".") and d != "__pycache__"]
        if excl and os.path.abspath(dirpath).startswith(excl):
            continue
        for name in sorted(filenames):
            if name.lower().endswith(".pptx") and not name.startswith("~$"):
                full = os.path.abspath(os.path.join(dirpath, name))
                if excl and full.startswith(excl):
                    continue
                found.append(full)
    if not found:
        return None
    # 输入目录里若混进了本脚本自己上一轮产出的 deck.pptx（同一文件或内容一致），
    # 不能再当成组织方模板套一层——那会让页数与版式逐轮漂移。
    if excl:
        own = os.path.join(excl, "deck.pptx")
        own_hash = _file_hash(own) if os.path.isfile(own) else None
        kept = []
        for path in found:
            try:
                same = os.path.samefile(path, own)
            except OSError:
                same = False
            if same or (own_hash and _file_hash(path) == own_hash):
                continue
            kept.append(path)
        found = kept
    # 输入目录本身就是"上一轮的产物目录"（同时含 slide_evidence.json 与
    # lane_slides.json）时，其中的 deck.pptx 是自产件而非组织方模板，
    # 不能再套一层（会让页数与版式逐轮漂移）。
    if (os.path.isfile(os.path.join(input_dir, "slide_evidence.json"))
            and os.path.isfile(os.path.join(input_dir, "lane_slides.json"))):
        found = [p for p in found if os.path.basename(p) != "deck.pptx"]
    return found[0] if found else None


def _pick_layouts(prs):
    """挑出母版里的标题版式与标题+正文版式（沿用占位符，不新建空白页）。

    优先按版式名匹配（"Title and Content" / "标题和内容" 作正文页，
    "Title Slide" / "标题幻灯片" 作封面），再退回按占位符类型判断。
    """
    by_name = {}
    for layout in prs.slide_layouts:
        by_name.setdefault(str(getattr(layout, "name", "")).lower(), layout)

    def pick(names, need_body):
        for nm in names:
            for key, layout in by_name.items():
                if nm in key:
                    has_title = has_body = False
                    for ph in layout.placeholders:
                        kind = str(getattr(ph, "placeholder_format", None) and
                                   ph.placeholder_format.type)
                        if "TITLE" in kind:
                            has_title = True
                        elif ("BODY" in kind or "OBJECT" in kind
                              or "SUBTITLE" in kind):
                            has_body = True
                    if has_title and (has_body or not need_body):
                        return layout
        return None

    body_layout = pick(("title and content", "标题和内容", "标题与内容",
                         "content with caption", "section header"), True)
    title_layout = pick(("title slide", "标题幻灯片", "标题页"), False)

    # 名字匹配不到时按占位符类型兜底
    if body_layout is None:
        for layout in prs.slide_layouts:
            has_title = has_body = False
            for ph in layout.placeholders:
                kind = str(getattr(ph, "placeholder_format", None) and
                           ph.placeholder_format.type)
                if "TITLE" in kind:
                    has_title = True
                elif "BODY" in kind or "OBJECT" in kind:
                    has_body = True
            if has_title and has_body:
                body_layout = layout
                break
    if title_layout is None:
        for layout in prs.slide_layouts:
            names = str(getattr(layout, "name", "")).lower()
            if "title slide" in names or "标题幻灯片" in names:
                title_layout = layout
                break
    return title_layout, body_layout


def _clear_slides(prs):
    """删掉模板自带的示例页（只删占位/示例，页数很少时才删）。"""
    xml_slides = prs.slides._sldIdLst
    for sld in list(xml_slides):
        rId = sld.get(
            "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id")
        prs.part.drop_rel(rId)
        xml_slides.remove(sld)


def _export_pptx_mini(pages, out_path, template_path, reason):
    """python-pptx 不可用时的兜底：用纯标准库 pptx_mini 直出 OOXML。

    保证「可编辑演示文件」这一交付项在任意环境下都有产物；
    组织方模板此时无法继承（纯标准库不解析模板），如实标注降级。
    """
    try:
        import pptx_mini
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "degraded": "pptx 导出不可用（%s；pptx_mini 亦不可用：%s）"
                % (reason[:80], str(exc)[:80])}
    try:
        res = pptx_mini.write_pptx(pages, out_path)
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "degraded": "pptx_mini 导出失败：%s" % str(exc)[:120]}
    return {
        "ok": True,
        "degraded": "pptx 由纯标准库 pptx_mini 直出（python-pptx 不可用：%s）；"
                    "占位符与母版继承项无法核验" % reason[:80],
        "note": {
            "writer": "pptx_mini（纯标准库 OOXML 直写）",
            "template": None,
            "template_reason": ("python-pptx 不可用（%s），未能继承组织方模板母版/版式"
                                % reason[:80]) if template_path else None,
            "slides": res.get("slides"),
        },
    }


def export_pptx(pages, out_path, template_path=None):
    """生成可编辑演示稿（含讲稿备注）。

    两条路径：
      1. python-pptx（若镜像预装）——可继承组织方模板的母版/版式/主题。
      2. 纯标准库 pptx_mini——无第三方依赖，任何环境都能产出合法可编辑 pptx。

    给定模板时以模板为底（继承母版/版式/占位符/主题字体与主题色，不硬编码覆盖）。
    """
    try:
        from pptx import Presentation
        from pptx.util import Inches, Pt
    except Exception as exc:  # noqa: BLE001
        return _export_pptx_mini(pages, out_path, template_path, str(exc))
    try:
        note = {"template": template_path or "（未提供模板，使用 python-pptx 默认母版）"}
        if template_path and os.path.isfile(template_path):
            prs = Presentation(template_path)
            note["template"] = template_path
            note["existing_slides"] = len(prs.slides)
            # 模板是"母版/版式"载体：清空其示例页，只保留母版、版式、占位符、
            # 主题字体与主题色。否则新稿会叠加在示例页之上，页数与内容都不可控。
            if len(prs.slides):
                _clear_slides(prs)
                note["cleared_sample_slides"] = len(prs.slides)
        else:
            prs = Presentation()
            prs.slide_width = Inches(13.333)
            prs.slide_height = Inches(7.5)

        title_layout, body_layout = _pick_layouts(prs)
        note["body_layout"] = getattr(body_layout, "name", None)
        note["title_layout"] = getattr(title_layout, "name", None)
        blank = prs.slide_layouts[6] if len(prs.slide_layouts) > 6 else prs.slide_layouts[0]

        for idx, p in enumerate(pages):
            layout = body_layout or blank
            if idx == 0 and title_layout is not None:
                layout = title_layout
            slide = prs.slides.add_slide(layout)
            # 优先写入版式自带的占位符（保留主题字体/配色/字号层级）
            title_ph = body_ph = None
            for ph in slide.placeholders:
                kind = str(getattr(ph, "placeholder_format", None) and
                           ph.placeholder_format.type)
                upper = kind.upper()
                if ("TITLE" in upper and "SUBTITLE" not in upper
                        and title_ph is None):
                    title_ph = ph
                elif (("BODY" in upper or "OBJECT" in upper or "SUBTITLE" in upper)
                      and body_ph is None):
                    body_ph = ph
            if title_ph is not None:
                title_ph.text_frame.text = p["title"]
            else:
                box = slide.shapes.add_textbox(Inches(0.6), Inches(0.5),
                                               Inches(12.1), Inches(1.2))
                tf = box.text_frame
                tf.text = p["title"]
                if tf.paragraphs[0].runs:
                    tf.paragraphs[0].runs[0].font.size = Pt(30)
                    tf.paragraphs[0].runs[0].font.bold = True
            lines = ([p["claim"]] if p["claim"] else []) + p["bullets"]
            if body_ph is not None:
                btf = body_ph.text_frame
                btf.text = lines[0] if lines else ""
                for extra in lines[1:]:
                    btf.add_paragraph().text = extra
            elif lines:
                body = slide.shapes.add_textbox(Inches(0.6), Inches(2.0),
                                                Inches(12.1), Inches(4.6))
                btf = body.text_frame
                btf.word_wrap = True
                btf.text = lines[0]
                for extra in lines[1:]:
                    btf.add_paragraph().text = extra
            try:
                slide.notes_slide.notes_text_frame.text = (
                    "过渡：%s\n强调：%s\n被问到时：%s" % (
                        p["notes"].get("transition", ""), p["notes"].get("emphasis", ""),
                        p["notes"].get("backup", "")))
            except Exception:  # noqa: BLE001
                pass
        prs.save(out_path)
        note["slides"] = len(prs.slides)
        return {"ok": True, "degraded": None, "note": note}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "degraded": "pptx 导出失败：%s" % str(exc)[:160]}


def export_pdf(pptx_path, out_dir):
    soffice = shutil.which("soffice") or shutil.which("libreoffice")
    if not soffice:
        return {"ok": False, "degraded": "未找到 soffice，PDF 导出跳过"}
    try:
        subprocess.run([soffice, "--headless", "--convert-to", "pdf", "--outdir", out_dir,
                        pptx_path], stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=240)
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "degraded": "PDF 导出失败：%s" % str(exc)[:120]}
    pdf = os.path.join(out_dir, "deck.pdf")
    if os.path.isfile(pdf):
        return {"ok": True, "degraded": None}
    return {"ok": False, "degraded": "PDF 导出未产出文件"}


def export_png(pdf_path, out_dir, limit=40):
    tool = shutil.which("pdftoppm")
    if not tool:
        return {"ok": False, "degraded": "未找到 pdftoppm，PNG 预览跳过"}
    prev_dir = os.path.join(out_dir, "preview")
    try:
        os.makedirs(prev_dir, exist_ok=True)
        subprocess.run([tool, "-png", "-r", "72", "-f", "1", "-l", str(limit), pdf_path,
                        os.path.join(prev_dir, "slide")],
                       stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=240)
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "degraded": "PNG 渲染失败：%s" % str(exc)[:120]}
    n = len([f for f in os.listdir(prev_dir) if f.endswith(".png")]) if os.path.isdir(prev_dir) else 0
    if n:
        return {"ok": True, "degraded": None, "pages": n}
    return {"ok": False, "degraded": "PNG 渲染未产出图片"}


# ----------------------------------------------------------------- 主流程

def main(argv=None):
    ap = argparse.ArgumentParser(description="演示文稿赛道：页级编排 + 证据映射")
    ap.add_argument("--input", default="/input", help="只读输入目录")
    ap.add_argument("--output", default="/app/output", help="产物输出目录")
    ap.add_argument("--work", default="/app/work", help="中间工作区")
    ap.add_argument("--doc", default=None, help="共享层已抽好的 doc.json")
    ap.add_argument("--max-slides", type=int, default=None, help="覆盖页数上限")
    ap.add_argument("--no-pptx", action="store_true", help="不产出可选 pptx 导出件")
    args = ap.parse_args(argv)

    in_dir, out_dir, work_dir = args.input, args.output, args.work
    os.makedirs(out_dir, exist_ok=True)
    os.makedirs(work_dir, exist_ok=True)
    log_path = os.path.join(work_dir, "lane_slides.log")
    log_lines = []

    def log(msg):
        log_lines.append(msg)
        sys.stderr.write("[lane_slides] %s\n" % msg)

    case, case_path = read_case(in_dir)
    case_id = case_id_of(case, in_dir)
    log("case=%s case.json=%s" % (case_id, case_path))

    doc, doc_path, doc_origin = load_doc(args.doc, work_dir, in_dir)
    log("doc.json=%s origin=%s" % (doc_path or "-", doc_origin))
    if not doc or not doc.get("units"):
        reason = "无可用 doc.json（%s）" % doc_origin
        log("FAILED " + reason)
        with open(log_path, "w", encoding="utf-8") as fh:
            fh.write("\n".join(log_lines) + "\n")
        result = boundary_fields(case_id, [], [], {
            "level": "high", "notes": [reason], "unresolved": ["deck.md", "slide_evidence.json"]},
            ["读取 case.json 并解析输出契约", "未能取得可用的 doc.json，未产出任何页面内容"],
            "failed")
        result["slides"] = []
        with open(os.path.join(out_dir, "lane_slides.json"), "w", encoding="utf-8") as fh:
            json.dump(result, fh, ensure_ascii=False, indent=2)
        print("lane_slides: failed (%s)" % reason)
        return 1

    meta = doc.get("meta", {}) or {}
    tier = meta.get("tier", "unknown")
    if tier not in ("pdftotext", "stdlib"):
        log("抽取层级=%s（非最佳），版面还原受限" % tier)

    max_slides = args.max_slides or find_max_slides(case) or DEFAULT_MAX_SLIDES
    log("页数上限=%d（来源：%s）" % (max_slides, "case.json" if find_max_slides(case) else "默认"))

    spine = build_spine(doc)
    caps, mentions, orphan_tables, caption_only = build_caption_index(doc)
    log("主线候选：章节 %d 节；图注 %d 条；正文编号引用 %d 处" %
        (len(spine), len(caps), len(mentions)))

    pages, appendix, merges = plan_pages(spine, doc, caps, max_slides)
    pages = flag_reviews(pages, caps, mentions, doc, spine)
    flagged = [p["slide_no"] for p in pages if p["needs_review"]]
    log("成页 %d 页；待复核页 %s" % (len(pages), flagged or "无"))

    # ---------------- deck.md ----------------
    deck_meta = {
        "source_file": meta.get("source_file", ""),
        "tier": tier,
        "pages": len(doc.get("pages", [])),
        "units": len(doc.get("units", [])),
        "tables": len(doc.get("tables", [])),
        "captions": len(doc.get("captions", [])),
        "numbers": len(doc.get("numbers", [])),
        "max_slides": max_slides,
    }
    md = deck_md(pages, appendix, spine, deck_meta)
    deck_path = os.path.join(out_dir, "deck.md")
    with open(deck_path, "w", encoding="utf-8") as fh:
        fh.write(md)
    log("写出 deck.md（%d 字节）" % os.path.getsize(deck_path))

    # ---------------- slide_evidence.json ----------------
    evidence_pages = []
    for p in pages:
        evidence_pages.append({
            "slide_no": p["slide_no"],
            "title": p["title"],
            "claim": p["claim"],
            "evidence": p["evidence"],
            "needs_review": p["needs_review"],
            "review_reasons": p["review_reasons"],
            "role_label": p["role_label"],
            "source_sections": p["source_sections"],
        })
    covered = sum(1 for p in evidence_pages if p["evidence"])
    src_file = meta.get("source_file", "")
    sources = []
    seen_loc = set()
    for p in evidence_pages:
        for ev in p["evidence"]:
            loc = ev["locator"]
            if loc in seen_loc:
                continue
            seen_loc.add(loc)
            sources.append({
                "file": src_file,
                "locator": loc,
                "fields": ["slide_%d" % p["slide_no"]],
                "tier": tier,
            })
    unc_notes = []
    unresolved = []
    if tier not in ("pdftotext", "stdlib"):
        unc_notes.append("抽取层级为 %s，版面还原与图表归属存在不确定性" % tier)
    if orphan_tables:
        unc_notes.append("以下表格结构未能与任何图注关联（多为图形坐标残留），未用于页面引用：%s"
                         % "、".join(orphan_tables))
    if caption_only:
        unc_notes.append("以下表/图注只识别到图注、正文未能自动切分，相关页已标记待复核：%s"
                         % "、".join(caption_only))
    missing_ref = []
    cap_refs = {c["ref"] for c in caps if c.get("ref")}
    for m in mentions:
        ref = "%s %s" % ("Table" if m["label"] == "table" else "Figure", m["num"])
        if ref not in cap_refs:
            missing_ref.append("%s@%s" % (ref, m["anchor"]))
    if missing_ref:
        unresolved.append("正文编号引用与图注清单不一致：%s" % "、".join(sorted(set(missing_ref))))
    for p in pages:
        for r in p["review_reasons"]:
            unresolved.append("第 %d 页：%s" % (p["slide_no"], r))
    unc_notes.append("页级证据覆盖率 %d/%d（每页至少一条带锚点的逐字引文）"
                     % (covered, len(evidence_pages)))
    if appendix:
        unc_notes.append("以下章节未成页（降级为备用页/问答素材）：%s"
                         % "、".join("%s(%s)" % (a["title"], a["sec_id"]) for a in appendix))
    uncertainty = {
        "level": "medium" if unresolved else "low",
        "notes": unc_notes,
        "unresolved": sorted(set(unresolved)),
    }
    change_log = [
        "读取 %s，解析 case_id=%s 与固定页数上限=%d" % (case_path, case_id, max_slides),
        "载入 doc.json（来源=%s，tier=%s，章节单元 %d、表格 %d、图注 %d、数值 %d）"
        % (doc_origin, tier, len(doc.get("units", [])), len(doc.get("tables", [])),
           len(doc.get("captions", [])), len(doc.get("numbers", []))),
        "从 doc.json 抽论文主线候选：过滤 %d 个版面噪声章节，按角色重排 %d 个有效章节"
        % (len(doc.get("units", [])) - len(spine), len(spine)),
        "为每页装配主张句/要点/讲稿三件套，讲稿与页面文字取自不同原句（避免复述）",
        "交叉核对图表编号：正文编号引用 %d 处，图注 %d 条，未匹配 %d 处"
        % (len(mentions), len(caps), len(missing_ref)),
        "按上限 %d 收敛页序（合并同角色页 %d 次），产出 deck.md / slide_evidence.json"
        % (max_slides, merges),
    ]
    ev_json = boundary_fields(
        case_id,
        [artifact_entry(out_dir, "deck.md", "editable_source"),
         artifact_entry(out_dir, "slide_evidence.json", "evidence_map")],
        sources, uncertainty, change_log,
        "success" if (pages and not unresolved) else ("partial" if pages else "failed"))
    ev_json["slides"] = evidence_pages
    ev_json["coverage"] = {
        "slides": len(evidence_pages),
        "slides_with_evidence": covered,
        "evidence_coverage": round(covered / len(evidence_pages), 4) if evidence_pages else 0.0,
        "slides_needing_review": len(flagged),
        "figure_table_refs": sum(len(p["chart_refs"]) for p in pages),
        "appendix_sections": len(appendix),
    }
    ev_path = os.path.join(out_dir, "slide_evidence.json")
    # slide_evidence.json 的 artifacts 里含它自己的字节数 → 自引用。
    # 迭代写到不动点（字节数位数变化最多收敛 2 次），保证同输入同输出字节一致。
    for _ in range(4):
        with open(ev_path, "w", encoding="utf-8") as fh:
            json.dump(ev_json, fh, ensure_ascii=False, indent=2)
        size = os.path.getsize(ev_path)
        cur = next((a for a in ev_json["artifacts"] if a["path"] == "slide_evidence.json"),
                    None)
        if cur is not None and cur["bytes"] == size:
            break
        if cur is not None:
            cur["bytes"] = size
    log("写出 slide_evidence.json（%d 页，覆盖率 %s）"
        % (len(evidence_pages), ev_json["coverage"]["evidence_coverage"]))
    log("锚点使用：证据 %d 条，去重后 %d 条；覆盖页码 p.%d-p.%d，章节单元 %d 个，图注锚点 %d 个"
        % (sum(len(p["evidence"]) for p in evidence_pages), len(sources),
           min([p["pages"][0] for p in pages] or [0]),
           max([p["pages"][1] for p in pages] or [0]),
           len({p["source_sections"][0] for p in pages if p["source_sections"]}),
           len([c for c in caps if "cap." in str(c.get("anchor"))])))
    for p in evidence_pages:
        log("  第 %d 页 %s → %s" % (
            p["slide_no"], trim(p["title"], 40),
            "、".join(ev["locator"] for ev in p["evidence"])))

    # ---------------- 可选导出件 ----------------
    degraded = []
    pptx_path = os.path.join(out_dir, "deck.pptx")
    template = find_template(in_dir, exclude_dir=out_dir)
    if template:
        log("发现模板 pptx：%s" % template)
    if args.no_pptx:
        degraded.append("按 --no-pptx 跳过 pptx 导出")
        pptx_res = {"ok": False, "degraded": "按 --no-pptx 跳过"}
    else:
        pptx_res = export_pptx(pages, pptx_path, template)
    if pptx_res.get("ok"):
        log("写出 deck.pptx（%d 字节）%s" % (os.path.getsize(pptx_path),
                                            pptx_res.get("note", {})))
        if pptx_res.get("degraded"):
            degraded.append(pptx_res["degraded"])
    else:
        degraded.append(pptx_res.get("degraded") or "pptx 导出未完成")
        log("pptx 降级：%s" % pptx_res.get("degraded"))

    pdf_res = {"ok": False, "degraded": "无 pptx，跳过 PDF 导出"}
    png_res = {"ok": False, "degraded": "无 PDF，跳过 PNG 渲染"}
    if pptx_res.get("ok"):
        pdf_res = export_pdf(pptx_path, out_dir)
        if pdf_res.get("ok"):
            log("写出 deck.pdf（%d 字节）" % os.path.getsize(os.path.join(out_dir, "deck.pdf")))
            png_res = export_png(os.path.join(out_dir, "deck.pdf"), out_dir)
            if png_res.get("ok"):
                log("写出 preview/*.png（%d 张）" % png_res.get("pages", 0))
            else:
                degraded.append(png_res.get("degraded"))
        else:
            degraded.append(pdf_res.get("degraded"))

    artifacts = [
        artifact_entry(out_dir, "deck.md", "editable_source"),
        artifact_entry(out_dir, "slide_evidence.json", "evidence_map"),
    ]
    if pptx_res.get("ok"):
        art = artifact_entry(out_dir, "deck.pptx", "editable_deck")
        art["template"] = pptx_res.get("note", {}).get("template")
        art["layout"] = pptx_res.get("note", {}).get("body_layout")
        art["slides"] = pptx_res.get("note", {}).get("slides")
        # 纯标准库兜底写出时，要如实标注"未能继承母版/版式/主题"
        if pptx_res.get("note", {}).get("template_reason"):
            art["degraded"] = pptx_res["note"]["template_reason"]
        elif pptx_res.get("degraded"):
            art["degraded"] = pptx_res["degraded"]
        artifacts.append(art)
    if pdf_res.get("ok"):
        artifacts.append(artifact_entry(out_dir, "deck.pdf", "export"))
    if png_res.get("ok"):
        artifacts.append({"path": "preview/", "kind": "render_preview",
                          "bytes": png_res.get("pages", 0), "degraded": None})

    lane_json = boundary_fields(
        case_id, artifacts, sources, uncertainty, change_log,
        "success" if (pages and not unresolved) else ("partial" if pages else "failed"))
    lane_json["slides"] = evidence_pages
    lane_json["spine"] = [{
        "sec_id": s["sec_id"], "title": s["title"], "role": s["role"],
        "role_label": s["role_label"], "pages": [s["page_start"], s["page_end"]],
        "key_sentences": [{"anchor": "p.%d/%s/sent.%d" % (k["page"], s["sec_id"], k["k"]),
                           "quote": trim(k["text"], 200)} for k in s["key_sentences"]],
    } for s in spine]
    lane_json["appendix_candidates"] = appendix
    lane_json["figures"] = [{"anchor": c["anchor"], "ref": c["ref"], "page": c["page"],
                              "caption": c["text"], "body_table": c["body_table"],
                              "cited_from": c["cited_from"]} for c in caps]
    lane_json["coverage"] = ev_json["coverage"]
    lane_json["degraded"] = degraded
    with open(os.path.join(out_dir, "lane_slides.json"), "w", encoding="utf-8") as fh:
        json.dump(lane_json, fh, ensure_ascii=False, indent=2)
    log("写出 lane_slides.json（产物 %d 个）" % len(artifacts))
    log("降级项：%s" % ("；".join(degraded) if degraded else "无（主产物 deck.md 与 slide_evidence.json 均完整）"))

    with open(log_path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(log_lines) + "\n")
    print("lane_slides: case=%s pages=%d evidence=%d/%d degraded=%d -> %s"
          % (case_id, len(pages), covered, len(evidence_pages), len(degraded), out_dir))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:  # noqa: BLE001
        sys.stderr.write("[lane_slides] fatal:\n%s\n" % traceback.format_exc())
        sys.exit(1)
