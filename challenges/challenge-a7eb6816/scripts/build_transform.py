#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""build_transform.py - assemble and verify a source-faithful genre transform.

The agent authors plan.json (audience, genre, target length, sections,
claim_evidence, glossary, removals, uncertainty). This script performs the
deterministic part: quote verification, number traceability, glossary and
removal accounting, limitation/scope checks, overclaim and fabrication checks,
length/readability metrics computed from the generated text, and contract
assembly. It never invents prose: if the plan contains no text, it writes an
honest failed result instead of a fake article.

Usage:
  python3 scripts/build_transform.py --plan /app/work/plan.json \
      --sources /app/work/sources.json --case /input/case.json \
      --out /app/output --work /app/work

Outputs under --out: transform.md, preservation_map.csv, glossary.csv,
result.json. Exit codes: 0 success/partial, 1 failed (honest, no traceback).
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import re
import sys
from datetime import datetime, timezone

OUT_TRANSFORM = "transform.md"
OUT_MAP = "preservation_map.csv"
OUT_GLOSSARY = "glossary.csv"
GLOSSARY_HEADING = "## 术语与缩写"

COMMON_ACRONYMS = {
    "PDF", "DOI", "URL", "HTML", "XML", "JSON", "CSV", "API", "GPU", "CPU",
    "RAM", "OS", "USA", "EU", "UK", "UN", "WHO", "DNA", "RNA", "AI", "II",
    "III", "IV", "VI", "VII", "VIII", "IX", "XI", "XII", "OK", "ID",
}

GENRE_PROFILES = {
    "popular_science": ("公众科普文章", ["hook", "background", "finding", "evidence",
                                           "significance", "limitations"]),
    "press_release": ("新闻稿", ["lead", "finding", "context", "significance",
                                 "reference", "limitations"]),
    "project_application": ("项目申报材料", ["problem", "objective", "approach",
                                               "preliminary_results", "feasibility",
                                               "risks", "plan"]),
    "policy_brief": ("政策简报", ["problem", "finding", "evidence", "implications",
                                  "limitations"]),
    "executive_summary": ("执行摘要", ["context", "finding", "evidence",
                                       "significance", "limitations"]),
    "technical_summary": ("技术摘要", ["problem", "method", "results",
                                       "limitations", "conclusion"]),
    "lay_summary": ("通俗摘要", ["background", "finding", "evidence",
                                 "significance", "limitations"]),
    "grant_abstract": ("基金摘要", ["problem", "objective", "approach",
                                    "preliminary_results", "significance"]),
    "blog_post": ("博客文章", ["hook", "background", "finding", "evidence",
                               "implications", "limitations"]),
    "stakeholder_brief": ("利益相关方简报", ["finding", "evidence", "implications",
                                             "risks", "limitations"]),
    "news_brief": ("新闻简讯", ["lead", "finding", "significance", "limitations"]),
    "faq": ("问答", ["question", "answer", "evidence", "limitations"]),
}
GENRE_ALIASES = {
    "科普": "popular_science", "科普文章": "popular_science", "公众科普": "popular_science",
    "science_article": "popular_science", "public_science": "popular_science",
    "lay_article": "popular_science",
    "新闻稿": "press_release", "新闻通稿": "press_release", "press": "press_release",
    "项目申报": "project_application", "项目申报材料": "project_application",
    "申报书": "project_application", "project_proposal": "project_application",
    "grant_proposal": "project_application",
    "政策简报": "policy_brief", "policy": "policy_brief",
    "执行摘要": "executive_summary", "summary": "executive_summary",
    "技术摘要": "technical_summary", "技术报告摘要": "technical_summary",
    "通俗摘要": "lay_summary", "plain_language_summary": "lay_summary",
    "基金摘要": "grant_abstract", "博客": "blog_post", "blog": "blog_post",
    "利益相关方简报": "stakeholder_brief", "简报": "stakeholder_brief",
    "新闻简讯": "news_brief", "问答": "faq", "faq_list": "faq",
}
ROLE_KEYWORDS = {
    "hook": ["为什么", "开场", "你可能", "想象", "hook", "why"],
    "lead": ["导语", "开头", "核心发现", "lead"],
    "background": ["背景", "已有", "已知", "此前", "background", "known"],
    "problem": ["问题", "需求", "痛点", "problem", "need", "gap"],
    "objective": ["目标", "目的", "任务", "objective", "aim", "goal"],
    "approach": ["方法", "方案", "技术路线", "approach", "method", "plan"],
    "method": ["方法", "实验设计", "method"],
    "finding": ["发现", "结果", "主要结论", "finding", "result"],
    "results": ["结果", "数据", "result"],
    "preliminary_results": ["初步", "前期", "已有结果", "preliminary"],
    "evidence": ["证据", "数据", "样本", "evidence", "data"],
    "significance": ["意义", "影响", "价值", "significance", "impact"],
    "implications": ["启示", "影响", "implication"],
    "feasibility": ["可行性", "条件", "基础", "feasibility"],
    "risks": ["风险", "不确定性", "risk"],
    "plan": ["计划", "进度", "安排", "plan", "timeline"],
    "reference": ["来源", "原文", "引用", "reference", "citation"],
    "limitations": ["局限", "不足", "边界", "注意", "limitation", "caveat"],
    "conclusion": ["结论", "总结", "conclusion"],
    "question": ["问题", "问答", "question"],
    "answer": ["答", "回答", "answer"],
}

WEAK_SOURCE = ["相关", "关联", "可能", "提示", "初步", "尚需", "有待", "不能排除",
               "不能推断", "无法证明", "并不能", "有限", "不足以", "谨慎",
               "limited", "preliminary", "associated", "association", "correlat",
               "suggests", "may", "might", "could", "potential", "not proof",
               "cannot", "unable", "small sample", "hypothesis"]
WEAK_STRENGTHS = {"association", "correlation", "preliminary", "hypothesis",
                  "exploratory", "weak", "tentative"}
STRONG_OUT = ["证明", "证实", "确定", "必然", "导致", "决定了", "确凿",
              "proves", "demonstrates", "confirms", "causes", "establishes",
              "conclusively", "definitively", "shows that"]
LIMIT_RE = re.compile(
    r"(局限|限制|不足|仅|只能|尚不能|不能|无法|未|有待|尚需|初步|样本量|"
    r"相关而非|相关不等于|不能推断|不宜|风险|谨慎|单中心|单一|外推|"
    r"limited|limitation|small sample|preliminary|suggests|associated|"
    r"correlat|not (?:prove|cause|establish)|cannot|unable|only one|single|"
    r"future work|warrant|caution)", re.I)
PLACEHOLDER_RE = re.compile(
    r"\b(?:TODO|TBD|FIXME|PLACEHOLDER)\b|lorem ipsum|\{\{[^}]+\}\}|"
    r"\[待[^\]]*\]|（待补）|待填写|待补充|此处省略|\bXXX\b", re.I)
HEADING_LINE_RE = re.compile(
    r"^\s*(?:#{1,6}\s*|\d+(?:\.\d+)*[、.\s]|[一二三四五六七八九十]+[、.]|"
    r"（[一二三四五六七八九十\d]+）)")
FAB_RE = [
    re.compile(r"(?:我们|笔者|本研究团队|课题组)(?:还)?(?:开展|进行|组织|完成|走访|采访|调查|试用)"
               r"(?:了)?[^。！？\n]{0,30}(?:实验|调查|访谈|采访|试用|测试|用户研究)"),
    re.compile(r"(?:in|during) our (?:survey|interview|trial|user study|field study|experiment)", re.I),
    re.compile(r"we (?:conducted|ran|performed) (?:a |an )?(?:survey|interview|trial|user study|field study|experiment)", re.I),
    re.compile(r"(?:我们|笔者)(?:的)?(?:实验|调查|访谈|试用)[^。！？\n]{0,10}(?:显示|表明|发现|证实)"),
    re.compile(r"(?:我们|笔者)(?:采访|走访|咨询)了[^。！？\n]{0,20}(?:专家|用户|患者|企业|医生)"),
    re.compile(r"(?:专家|用户|患者|客户)(?:表示|反馈|反映)"),
]
ATTR_RE = re.compile(r"(说|表示|指出|称|according to|said|stated)", re.I)
NUM_RE = re.compile(r"(?<![\w.])(\d{1,3}(?:[,，]\d{3})+|\d+)(\.\d+)?\s*(%|‰|％)?")
HYPE_EQUIV = {
    "首次": ["first"], "首个": ["first"], "唯一": ["only", "unique"],
    "领先": ["leading", "state-of-the-art"], "填补空白": ["fill the gap", "first"],
    "突破性": ["breakthrough"], "革命性": ["revolutionary"], "颠覆": ["disruptive"],
    "显著": ["significant"], "大幅": ["substantial", "large", "marked"],
    "彻底": ["completely", "eradicate"], "百分之百": ["100%"],
    "保证": ["guarantee", "ensure"], "必然": ["inevitable", "certainly"],
    "完全": ["completely", "fully"],
}
HYPE_RE = re.compile("|".join(sorted(HYPE_EQUIV, key=len, reverse=True)))


# ----------------------------------------------------------------------- utils
def canon(text):
    s = text or ""
    for a, b in (("‘", "'"), ("’", "'"), ("“", '"'), ("”", '"'),
                 ("–", "-"), ("—", "-"), ("−", "-"), ("\u00a0", " "), ("\u3000", " ")):
        s = s.replace(a, b)
    s = re.sub(r"(?<=[A-Za-z])-\s*\n\s*(?=[a-z])", "", s)
    return re.sub(r"\s+", " ", s).strip()


def squash(text):
    return re.sub(r"\s+", "", canon(text)).lower()


def tokens(text):
    s = canon(text).lower()
    latin = re.findall(r"[a-z0-9]+", s)
    cjk = re.findall(r"[\u4e00-\u9fff]", s)
    grams = [cjk[i] + cjk[i + 1] for i in range(len(cjk) - 1)]
    return set(latin) | set(cjk) | set(grams)


def overlap(container_tokens, part_tokens):
    if not part_tokens:
        return 0.0
    return len(container_tokens & part_tokens) / float(len(part_tokens))


def load_json(path, default=None):
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:  # noqa: BLE001
        return default


def sha256_text(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def split_sentences(text):
    parts = re.split(r"(?<=[。！？!?])|(?<=\.)(?=\s+[A-Z\"“])|\n{2,}", text or "")
    return [p.strip() for p in parts if p and p.strip()]


def split_blocks(text):
    return [p.strip() for p in re.split(r"\n\s*\n", text or "") if p.strip()]


def number_tokens(text):
    cleaned = re.sub(r"https?://\S+|doi:\S+|\[\d+(?:[-,–]\d+)*\]", " ", text or "")
    out = []
    for m in NUM_RE.finditer(cleaned):
        token = (m.group(1) + (m.group(2) or "")).replace(",", "").replace("，", "")
        if m.group(3):
            token += "%"
        out.append(token)
    return out


def digits_of(token):
    return re.sub(r"[^\d.]", "", token or "")


def body_numbers(body):
    kept = []
    for line in (body or "").split("\n"):
        if line.lstrip().startswith("#"):
            heading = line.lstrip("# ").strip()
            if re.match(r"^(?:\d+(?:\.\d+)*[.、)]?|第[一二三四五六七八九十百零〇\d]+[章节節部分篇])$",
                        heading):
                continue
            kept.append(heading)
            continue
        line = re.sub(r"^\s*(?:\d+[.)、]|[-*•])\s+", "", line)
        kept.append(line)
    return number_tokens("\n".join(kept))


def issue(code, severity, detail, where=""):
    return {"code": code, "severity": severity, "detail": detail, "where": where}


# --------------------------------------------------------------------- sources
def load_sources(path):
    data = load_json(path, {}) or {}
    docs = data.get("documents") or []
    paragraphs = []
    for d in docs:
        plist = d.get("paragraphs") or []
        if not plist and d.get("text"):
            plist = [{"anchor": "%s p.1 sec.1 para.%d" % (d.get("doc", "doc.1"), i + 1),
                      "page": 1, "section": 1, "text": b}
                     for i, b in enumerate(split_blocks(d.get("text")))]
        for p in plist:
            text = p.get("text") or ""
            if not text.strip():
                continue
            paragraphs.append({
                "doc": d.get("doc") or "doc.1",
                "path": d.get("path") or "",
                "anchor": p.get("anchor") or "",
                "page": p.get("page"),
                "section": p.get("section"),
                "heading": bool(p.get("heading")),
                "text": text,
                "sq": squash(text),
            })
    full = "\n".join((d.get("text") or "") for d in docs)
    src_numbers = set(number_tokens(full))
    return data, docs, paragraphs, full, src_numbers


def verify_quote(quote, anchor, paragraphs, full_sq):
    q = squash(quote)
    if not q:
        return False, ""
    for p in paragraphs:
        if p["anchor"] == anchor and q in p["sq"]:
            return True, anchor
    for p in paragraphs:
        if q in p["sq"]:
            return True, p["anchor"]
    if q in full_sq:
        return True, "(spanning paragraphs)"
    return False, ""


# ------------------------------------------------------------------------ plan
def norm_audience(raw):
    if isinstance(raw, str):
        return {"description": raw.strip(), "prior_knowledge": "unknown",
                "purpose": "", "reading_level": ""}
    if isinstance(raw, dict):
        return {
            "description": str(raw.get("who") or raw.get("description") or raw.get("reader") or "").strip(),
            "prior_knowledge": str(raw.get("prior_knowledge") or raw.get("knowledge") or "unknown").strip(),
            "purpose": str(raw.get("purpose") or "").strip(),
            "reading_level": str(raw.get("reading_level") or raw.get("level") or "").strip(),
        }
    return {}


def is_lay_audience(a):
    prior = (a.get("prior_knowledge") or "").lower()
    desc = (a.get("description") or "").lower()
    cues = ("public", "lay", "general", "non-expert", "none", "公众", "大众",
            "普通读者", "非专业", "科普", "外行", "政策", "媒体", "投资")
    if prior in {"none", "lay", "general", "public", "zero", "无", "普通"}:
        return True
    return any(c in desc or c in prior for c in cues)


def norm_genre(raw):
    if isinstance(raw, dict):
        raw = raw.get("type") or raw.get("name") or raw.get("genre") or raw.get("id") or ""
    g = str(raw or "").strip()
    key = g.lower().replace("-", "_").replace(" ", "_")
    if key in GENRE_PROFILES:
        return key, True
    if key in GENRE_ALIASES:
        return GENRE_ALIASES[key], True
    for alias, target in GENRE_ALIASES.items():
        if alias and (alias in g or alias in key):
            return target, True
    return key or "unspecified", False


def norm_sections(plan, claims):
    raw = plan.get("sections")
    sections = []
    if isinstance(raw, dict):
        raw = [{"heading": k, "paragraphs": v} for k, v in raw.items()]
    if isinstance(raw, list):
        for i, s in enumerate(raw, 1):
            if isinstance(s, str):
                s = {"heading": "", "paragraphs": [s]}
            if not isinstance(s, dict):
                continue
            paras = (s.get("paragraphs") or s.get("paras") or s.get("body")
                     or s.get("content") or s.get("text") or [])
            if isinstance(paras, str):
                paras = split_blocks(paras) or [paras]
            paras = [str(p).strip() for p in paras if str(p).strip()]
            sections.append({
                "id": str(s.get("id") or "s%d" % i),
                "heading": str(s.get("heading") or s.get("title") or "第%d节" % i).strip(),
                "role": str(s.get("role") or "").strip().lower(),
                "paragraphs": paras,
            })
    # Fill empty sections from claim output_text grouped by section id.
    by_section = {}
    for c in claims:
        text = c.get("output_text") or ""
        if text:
            by_section.setdefault(c.get("section") or "", []).append(text)
    if sections:
        lookup = {}
        for s in sections:
            for key in (s["id"], s["heading"], s["role"]):
                if key:
                    lookup.setdefault(key, s)
        for s in sections:
            if not s["paragraphs"] and by_section.get(s["id"]):
                s["paragraphs"] = list(by_section[s["id"]])
        for sec_id, texts in by_section.items():
            if not sec_id:
                continue
            target = lookup.get(sec_id) or sections[-1]
            existing = {squash(p) for p in target["paragraphs"]}
            for text in texts:
                if squash(text) not in existing:
                    target["paragraphs"].append(text)
                    existing.add(squash(text))
    elif by_section:
        order = []
        for c in claims:
            sec = c.get("section") or ""
            if sec and sec not in order:
                order.append(sec)
        if order and all(re.match(r"^s\d+$", s) for s in order):
            order = sorted(order, key=lambda s: int(s[1:]))
        titles = plan.get("section_titles") if isinstance(plan.get("section_titles"), dict) else {}
        for i, sec in enumerate(order or [""], 1):
            sections.append({
                "id": sec or "s%d" % i,
                "heading": titles.get(sec) or sec or "正文",
                "role": "",
                "paragraphs": by_section.get(sec, []),
            })
    # Claims with output_text but no section at all.
    if sections and by_section.get(""):
        for s in sections:
            if not s["paragraphs"]:
                s["paragraphs"].extend(by_section[""])
                break
        else:
            sections.append({"id": "s_extra", "heading": "补充", "role": "",
                             "paragraphs": by_section[""]})
    return [s for s in sections if s["paragraphs"] or s["heading"]]


def norm_claims(plan):
    out = []
    raw = plan.get("claim_evidence") or []
    if isinstance(raw, dict):
        raw = [dict(v, id=k) if isinstance(v, dict) else {"id": k, "claim": str(v)}
               for k, v in raw.items()]
    for i, c in enumerate(raw, 1):
        if not isinstance(c, dict):
            c = {"claim": str(c)}
        out.append({
            "id": str(c.get("id") or "c%d" % i),
            "kind": str(c.get("kind") or "claim").strip().lower(),
            "claim": str(c.get("claim") or c.get("text") or c.get("rewrite") or "").strip(),
            "anchor": str(c.get("anchor") or c.get("source_anchor") or "").strip(),
            "quote": str(c.get("quote") or c.get("source_quote") or c.get("evidence") or "").strip(),
            "section": str(c.get("section") or c.get("output_section") or "").strip(),
            "strength": str(c.get("strength") or c.get("claim_strength") or "").strip().lower(),
            "source_strength": str(c.get("source_strength") or "").strip().lower(),
            "output_text": str(c.get("output_text") or c.get("rewritten") or "").strip(),
            "verified": False,
            "verified_anchor": "",
            "output_location": "",
            "output_excerpt": "",
            "match": "",
            "status": "unverified",
        })
    return out


def norm_glossary(plan):
    raw = plan.get("glossary") or []
    if isinstance(raw, dict):
        raw = [{"term": k, "plain": v} for k, v in raw.items()]
    entries = []
    for g in raw:
        if isinstance(g, str):
            g = {"term": g}
        if not isinstance(g, dict):
            continue
        action = str(g.get("action") or "expand").strip().lower()
        action = {"展开": "expand", "解释": "expand", "替换": "replace",
                  "保留": "keep", "沿用": "keep"}.get(action, action)
        if action not in ("expand", "replace", "keep"):
            action = "expand"
        aliases = g.get("aliases") or []
        if isinstance(aliases, str):
            aliases = [aliases]
        entries.append({
            "term": str(g.get("term") or "").strip(),
            "plain": str(g.get("plain") or g.get("plain_language") or g.get("definition")
                         or g.get("explanation") or g.get("gloss") or "").strip(),
            "action": action,
            "aliases": [str(a).strip() for a in aliases if str(a).strip()],
            "occurrences": 0,
            "inline_expanded": None,
            "status": "",
            "source_note": str(g.get("source_note") or g.get("anchor") or "").strip(),
        })
    return [e for e in entries if e["term"]]


def norm_removals(plan):
    raw = plan.get("removals") or []
    out = []
    for r in raw:
        if isinstance(r, str):
            r = {"removed": r}
        if not isinstance(r, dict):
            continue
        risk = str(r.get("risk") or "").strip().lower() or "medium"
        out.append({
            "removed": str(r.get("removed") or r.get("content") or r.get("what") or "").strip(),
            "source_anchor": str(r.get("source_anchor") or r.get("anchor") or "").strip(),
            "reason": str(r.get("reason") or r.get("why") or r.get("rationale") or "").strip(),
            "risk": risk,
        })
    return out


# ---------------------------------------------------------------- text output
def source_title(paragraphs, fallback="成果转化稿"):
    for p in paragraphs:
        text = canon(p["text"])
        if p.get("heading") and 2 <= len(text) <= 90:
            return text.lstrip("# ").strip()
    for p in paragraphs:
        text = canon(p["text"])
        if text and len(text) <= 90 and (text.startswith("#") or not text.endswith(".")):
            return text.lstrip("# ").strip()
    return fallback


def compose_markdown(plan, sections, glossary, title):
    parts = ["# " + title, ""]
    lead = str(plan.get("lead") or plan.get("standfirst") or "").strip()
    if lead:
        parts.extend([lead, ""])
    for s in sections:
        parts.extend(["## " + s["heading"], ""])
        for para in s["paragraphs"]:
            parts.extend([para.strip(), ""])
    appendix = False
    if glossary and plan.get("include_glossary") is not False:
        parts.extend([GLOSSARY_HEADING, ""])
        for g in glossary:
            line = "- **%s**：%s" % (g["term"], g["plain"] or "（原文未给出通俗解释，需作者补充）")
            if g["aliases"]:
                line += "（同义写法：%s）" % "、".join(g["aliases"])
            parts.append(line)
        parts.append("")
        appendix = True
    return "\n".join(parts).rstrip() + "\n", appendix


def split_body(text):
    idx = text.find("\n" + GLOSSARY_HEADING)
    if idx >= 0:
        return text[:idx].rstrip() + "\n", text[idx:]
    if text.lstrip().startswith(GLOSSARY_HEADING):
        return "", text
    return text, ""


def body_paragraphs(sections):
    out = []
    for s in sections:
        for i, para in enumerate(s["paragraphs"], 1):
            out.append({"section": s["id"], "index": i, "text": para,
                        "sq": squash(para)})
    return out


def locate(text, paras, fallback=""):
    candidates = [c for c in (text, fallback) if c and len(squash(c)) >= 4]
    for cand in candidates:
        needle = squash(cand)
        for p in paras:
            if needle in p["sq"]:
                return p, "exact", "%s#p%d" % (p["section"], p["index"])
    best, best_ratio, best_target = None, 0.0, set()
    for cand in candidates:
        target = tokens(cand)
        for p in paras:
            ratio = overlap(tokens(p["text"]), target)
            if ratio > best_ratio:
                best, best_ratio, best_target = p, ratio, target
    if best is not None and best_ratio >= 0.3 and len(best_target) >= 3:
        return best, "fuzzy", "%s#p%d" % (best["section"], best["index"])
    return None, "", ""


# ------------------------------------------------------------------ checks
def check_length(metrics, target, issues):
    if not isinstance(target, dict):
        return
    words, chars = metrics["words"], metrics["chars"]
    max_words = target.get("max_words") or target.get("words")
    max_chars = target.get("max_chars") or target.get("chars")
    min_words = target.get("min_words")
    try:
        if max_words and words > float(max_words) * 1.1:
            issues.append(issue("over_length", "error",
                                "正文 %d 词，超过上限 %s 的 110%%，需删减或调整 target_length"
                                % (words, max_words), "transform.md"))
        elif max_words and words > float(max_words):
            issues.append(issue("over_length_margin", "warn",
                                "正文 %d 词，略超上限 %s" % (words, max_words), "transform.md"))
        if max_chars and chars > float(max_chars) * 1.1:
            issues.append(issue("over_length_chars", "error",
                                "正文 %d 字符，超过上限 %s 的 110%%" % (chars, max_chars),
                                "transform.md"))
        elif max_chars and chars > float(max_chars):
            issues.append(issue("over_length_chars_margin", "warn",
                                "正文 %d 字符，略超上限 %s" % (chars, max_chars), "transform.md"))
        if min_words and words < float(min_words) * 0.9:
            issues.append(issue("under_length", "warn",
                                "正文 %d 词，低于下限 %s 的 90%%" % (words, min_words),
                                "transform.md"))
    except (TypeError, ValueError):
        issues.append(issue("target_length_invalid", "warn",
                            "target_length 不是可比较的数值：%r" % target, "plan"))


def check_numbers(body, src_numbers, declared, issues, paragraphs=None):
    out_tokens = body_numbers(body)
    src_digits = {digits_of(t) for t in src_numbers}
    anchor_by_digits = {}
    for p in paragraphs or []:
        for tok in number_tokens(p["text"]):
            anchor_by_digits.setdefault(digits_of(tok), p["anchor"])
    declared_by_digits = {}
    for d in declared:
        declared_by_digits[digits_of(d["value"])] = d
    rows, unsupported = [], []
    for token in out_tokens:
        digits = digits_of(token)
        exact = token in src_numbers
        digit_hit = digits in src_digits
        declared_hit = digits in declared_by_digits and bool(declared_by_digits[digits]["basis"])
        if exact:
            status = "verbatim"
        elif digit_hit:
            status = "verbatim_digits"
        elif declared_hit:
            status = "derived"
        else:
            status = "unsupported"
            unsupported.append(token)
        rows.append({
            "token": token,
            "digits": digits,
            "status": status,
            "source_anchor": anchor_by_digits.get(digits, ""),
            "basis": declared_by_digits.get(digits, {}).get("basis", "") if status == "derived" else "",
        })
    for token in sorted(set(unsupported)):
        issues.append(issue("unsupported_number", "error",
                            "输出中的数值「%s」未在源文出现，也未在 plan.numbers 中给出推导依据"
                            % token, "transform.md"))
    used = {digits_of(r["token"]) for r in rows}
    for d in declared:
        if digits_of(d["value"]) not in used:
            issues.append(issue("declared_number_unused", "warn",
                                "plan.numbers 声明的「%s」未出现在正文" % d["value"], "plan.numbers"))
    return rows


def check_glossary(body, full_text, glossary, lay, issues):
    body_lower = body.lower()
    total_occ = 0
    for g in glossary:
        term = g["term"]
        pattern = (re.escape(term) if re.search(r"[\u4e00-\u9fff]", term)
                   else r"(?<![A-Za-z])" + re.escape(term) + r"(?![A-Za-z])")
        occ = len(re.findall(pattern, body, re.I))
        g["occurrences"] = occ
        total_occ += occ
        if not g["plain"]:
            issues.append(issue("glossary_plain_missing", "error",
                                "术语「%s」缺少通俗解释" % term, "plan.glossary"))
            g["status"] = "missing_plain"
            continue
        if g["action"] == "replace":
            if occ:
                issues.append(issue("jargon_retained", "warn",
                                    "术语「%s」标记为替换，但正文仍出现 %d 次" % (term, occ),
                                    "transform.md"))
                g["status"] = "retained"
            else:
                g["status"] = "replaced"
            continue
        if occ:
            m = re.search(pattern, body, re.I)
            window = squash(body[max(0, m.start() - 140):m.end() + max(220, len(g["plain"]) + 80)])
            expanded = squash(g["plain"]) in window
            g["inline_expanded"] = expanded
            if g["action"] == "expand" and not expanded:
                issues.append(issue("glossary_not_expanded", "error",
                                    "术语「%s」首次出现处未给出通俗解释" % term, "transform.md"))
                g["status"] = "not_expanded"
            else:
                g["status"] = "expanded" if expanded else "glossary_only"
        else:
            g["inline_expanded"] = None
            g["status"] = "not_in_body"
    # Detect abbreviations that appear in the body but are not glossed.
    covered = set()
    for g in glossary:
        covered.add(g["term"].lower())
        for a in g["aliases"]:
            covered.add(a.lower())
    unglossed = []
    for m in re.finditer(r"(?<![A-Za-z0-9])([a-z]?[A-Z]{2,10})(?![A-Za-z])", body):
        term = m.group(1)
        if len(term) < 2 or term.upper() in COMMON_ACRONYMS:
            continue
        if term.lower() in covered:
            continue
        if term not in unglossed:
            unglossed.append(term)
    if unglossed:
        severity = "error" if lay else "warn"
        issues.append(issue("unglossed_jargon", severity,
                            "正文出现未入术语表的缩写：%s（目标读者为%s）"
                            % (", ".join(unglossed[:12]),
                               "非专业读者" if lay else "专业读者"),
                            "transform.md"))
    return total_occ, unglossed


def removal_matches(removal, para):
    anchor = removal["source_anchor"].strip()
    if anchor:
        if para["anchor"].startswith(anchor):
            return True
        m = re.search(r"(doc\.\d+)\s+p\.(\d+)", anchor)
        if m and para["doc"] == m.group(1) and str(para["page"]) == m.group(2):
            return True
    removed = removal["removed"]
    if removed:
        if squash(removed) and squash(removed) in para["sq"]:
            return True
        if overlap(tokens(para["text"]), tokens(removed)) >= 0.5:
            return True
    return False


def check_omissions(paragraphs, body, removals, issues):
    body_tokens = tokens(body)
    rows = []
    for p in paragraphs:
        text = canon(p["text"])
        if len(text) < 60:
            continue
        if text.startswith("#") or re.match(r"^(references?|bibliography|参考文献|致谢|acknowledg)",
                                             text, re.I):
            continue
        cov = overlap(body_tokens, tokens(text))
        if cov >= 0.12:
            continue
        logged = any(removal_matches(r, p) for r in removals)
        has_num = bool(number_tokens(text))
        has_limit = bool(LIMIT_RE.search(text))
        status = "logged" if logged else "unlogged"
        rows.append({
            "anchor": p["anchor"],
            "excerpt": text[:160],
            "coverage": round(cov, 3),
            "has_number": has_num,
            "has_limitation": has_limit,
            "status": status,
        })
        if not logged and has_num:
            issues.append(issue("omission_unlogged_number", "error",
                                "含数值的源段落未出现在正文，也未登记 removals：%s"
                                % p["anchor"], p["anchor"]))
        elif not logged and has_limit:
            issues.append(issue("omission_unlogged_limitation", "error",
                                "含限定/局限表述的源段落未保留，也未登记 removals：%s"
                                % p["anchor"], p["anchor"]))
        elif not logged:
            issues.append(issue("omission_unlogged", "warn",
                                "源段落未被正文覆盖，也未登记 removals：%s" % p["anchor"],
                                p["anchor"]))
    return rows[:80]


def _limitation_sentences(text):
    """Split a source paragraph, dropping a heading line merged with the body."""
    lines = [ln.strip() for ln in (text or "").split("\n") if ln.strip()]
    if len(lines) > 1:
        first = lines[0]
        headingish = bool(HEADING_LINE_RE.match(first)) or (
            len(first) <= 60 and not re.search(r"[。！？!?；;：:，,]$", first))
        if headingish:
            lines = lines[1:]
    return split_sentences("\n".join(lines))


def check_limitations(paragraphs, claims, removals, body, issues):
    body_tokens = tokens(body)
    body_sq = squash(body)
    total, covered, uncovered = 0, 0, []
    for p in paragraphs:
        for sent in _limitation_sentences(p["text"]):
            s = canon(sent)
            if not (20 <= len(s) <= 400) or not LIMIT_RE.search(s):
                continue
            total += 1
            hit = False
            for c in claims:
                if c["quote"] and (squash(s) in squash(c["quote"]) or
                                   squash(c["quote"]) in squash(s)):
                    hit = True
                    break
                if c["claim"] and overlap(tokens(s), tokens(c["claim"])) >= 0.5:
                    hit = True
                    break
            if not hit:
                for r in removals:
                    if r["source_anchor"] and p["anchor"].startswith(r["source_anchor"]):
                        hit = True
                        break
            sent_tokens = tokens(s)
            if not hit and overlap(body_tokens, sent_tokens) >= 0.45:
                hit = True
            if not hit:
                # Cue-aware fallback: the limiting wording survives even when the
                # surrounding sentence is compressed or reordered.
                cues = [m.group(0) for m in LIMIT_RE.finditer(sent)]
                cue_tokens = set()
                for cue in cues:
                    cue_tokens |= tokens(cue)
                content = sent_tokens - cue_tokens
                if cues and content:
                    cues_kept = all(squash(cue) in body_sq
                                    for cue in cues if len(squash(cue)) >= 1)
                    if cues_kept and overlap(body_tokens, content) >= 0.5:
                        hit = True
            if hit:
                covered += 1
            else:
                uncovered.append({"anchor": p["anchor"], "excerpt": s[:160]})
    if total and covered == 0:
        issues.append(issue("limitations_absent", "error",
                            "源文含 %d 处限定/局限表述，但正文与 claim_evidence 均未保留"
                            % total, "transform.md"))
    for item in uncovered[:5]:
        issues.append(issue("limitation_under_preserved", "warn",
                            "限定表述可能被弱化或遗漏：%s「%s」"
                            % (item["anchor"], item["excerpt"]), item["anchor"]))
    return {"source_limitation_sentences": total, "covered": covered,
            "coverage": round(covered / total, 3) if total else 1.0,
            "uncovered": uncovered[:10]}


def check_strength(claim, issues, para):
    text = claim["quote"] or ""
    src_weak = (claim["source_strength"] in WEAK_STRENGTHS or
                any(w in text.lower() for w in WEAK_SOURCE))
    if not src_weak:
        return
    if claim["strength"] in {"fact", "certain", "proven", "causal"}:
        issues.append(issue("claim_strength_upgrade", "error",
                            "claim %s 的源文为弱/关联性证据，但 strength 标为 %s"
                            % (claim["id"], claim["strength"] or "未标注"), claim["id"]))
        return
    if claim["claim"] and any(w.lower() in claim["claim"].lower() for w in STRONG_OUT):
        issues.append(issue("claim_strength_upgrade", "error",
                            "claim %s 的改写使用强断言措辞，但源文证据较弱" % claim["id"],
                            claim["id"]))
        return
    if para is not None:
        ptext = para["text"].lower()
        strong = [w for w in STRONG_OUT if w.lower() in ptext]
        hedged = any(w in ptext for w in WEAK_SOURCE)
        if strong and not hedged:
            issues.append(issue("claim_strength_upgrade", "error",
                                "claim %s 对应段落使用「%s」等强断言，但源文证据较弱且无限定语"
                                % (claim["id"], strong[0]), claim["id"]))


def check_fabrication(body, full_text, full_sq, allowed_quotes, issues):
    full_tokens = tokens(full_text)
    for pat in FAB_RE:
        for m in pat.finditer(body):
            clause = canon(m.group(0))
            if squash(clause) and squash(clause) in full_sq:
                continue
            if overlap(full_tokens, tokens(clause)) >= 0.7:
                continue
            issues.append(issue("fabricated_experience", "error",
                                "正文出现材料未支持的亲身经历/调研表述：「%s」" % clause[:90],
                                "transform.md"))
    for m in re.finditer(r"[“\"「]([^”\"」\n]{8,200})[”\"」]", body):
        inner = m.group(1)
        if squash(inner) in full_sq or squash(inner) in allowed_quotes:
            continue
        tail = body[m.end():m.end() + 30]
        head = body[max(0, m.start() - 20):m.start()]
        if ATTR_RE.search(tail) or ATTR_RE.search(head):
            issues.append(issue("fabricated_quote", "error",
                                "引号内容在源文中找不到，且带有归属表述：「%s」" % inner[:90],
                                "transform.md"))
        else:
            issues.append(issue("unverified_quotation", "warn",
                                "引号内容在源文中找不到（可能是修辞性引号）：「%s」" % inner[:90],
                                "transform.md"))


def check_hype(body, full_text, issues, uncertainty):
    low = full_text.lower()
    hits = []
    for m in HYPE_RE.finditer(body):
        phrase = m.group(0)
        if phrase in full_text:
            continue
        if any(e in low for e in HYPE_EQUIV.get(phrase, [])):
            continue
        prefix = body[max(0, m.start() - 3):m.start()]
        if any(neg in prefix for neg in ("不", "未", "无法", "不能", "非", "没")):
            continue
        hits.append(phrase)
    for phrase in sorted(set(hits)):
        issues.append(issue("unsupported_superlative", "warn",
                            "正文使用「%s」，源文未见对应强度表述，需确认是否夸大" % phrase,
                            "transform.md"))
    if hits:
        uncertainty.append({"issue": "强度措辞待确认：%s" % "、".join(sorted(set(hits))),
                            "decision": "保留但标为待确认，避免超出源文证据强度",
                            "needs_human": True})


def detect_conflicts(paragraphs):
    cands = [p for p in paragraphs if len(canon(p["text"])) >= 80][:160]
    tok = [tokens(p["text"]) for p in cands]
    num = [set(number_tokens(p["text"])) for p in cands]
    out = []
    for i in range(len(cands)):
        for j in range(i + 1, len(cands)):
            if cands[i]["doc"] != cands[j]["doc"]:
                continue
            inter = len(tok[i] & tok[j])
            if inter < 8:
                continue
            jac = inter / float(len(tok[i] | tok[j]) or 1)
            if jac >= 0.55 and num[i] and num[j] and num[i] != num[j]:
                out.append({
                    "anchor_a": cands[i]["anchor"], "excerpt_a": canon(cands[i]["text"])[:140],
                    "anchor_b": cands[j]["anchor"], "excerpt_b": canon(cands[j]["text"])[:140],
                    "numbers_a": sorted(num[i])[:8], "numbers_b": sorted(num[j])[:8],
                })
            if len(out) >= 8:
                return out
    return out


def check_genre(genre, supported, sections, issues, uncertainty):
    if not supported:
        issues.append(issue("unsupported_genre", "warn",
                            "体裁「%s」不在内置模板中；已按通用结构产出，需人工确认题裁要素"
                            % genre, "plan.genre"))
        uncertainty.append({"issue": "体裁判定：%s 无内置模板" % genre,
                            "decision": "按通用结构产出，未套用特定体裁模板",
                            "needs_human": True})
        return False
    label, roles = GENRE_PROFILES[genre]
    present = set()
    for s in sections:
        if s.get("role"):
            present.add(s["role"])
        hay = (s["heading"] + " " + " ".join(s["paragraphs"][:1])).lower()
        for role, kws in ROLE_KEYWORDS.items():
            if any(k.lower() in hay for k in kws):
                present.add(role)
    missing = [r for r in roles if r not in present]
    for r in missing:
        issues.append(issue("genre_element_missing", "warn",
                            "%s模板建议包含「%s」要素，但未在章节标题或 role 中识别到"
                            % (label, r), "plan.sections"))
        uncertainty.append({"issue": "%s 缺少体裁要素：%s" % (label, r),
                            "decision": "未强行补写无来源内容", "needs_human": True})
    return True


def compute_metrics(body, jargon_occ):
    chars = len(re.sub(r"\s+", "", body))
    cjk = len(re.findall(r"[\u4e00-\u9fff]", body))
    latin_words = re.findall(r"[A-Za-z][A-Za-z'\-]*", body)
    words = cjk + len(latin_words)
    sents = [s for s in split_sentences(body) if canon(s)]
    n_sent = len(sents)
    lens = [len(re.sub(r"\s+", "", s)) for s in sents]
    avg = (sum(lens) / float(n_sent)) if n_sent else 0.0
    long_ratio = (sum(1 for l in lens if l > 60) / float(n_sent)) if n_sent else 0.0
    flesch = None
    if latin_words and len(latin_words) >= 0.5 * max(1, words):
        syl = 0
        for w in latin_words:
            syl += max(1, len(re.findall(r"[aeiouy]+", w.lower())))
        flesch = round(206.835 - 1.015 * (len(latin_words) / float(max(1, n_sent)))
                       - 84.6 * (syl / float(max(1, len(latin_words)))), 1)
    return {
        "chars": chars,
        "words": words,
        "cjk_chars": cjk,
        "latin_words": len(latin_words),
        "sentences": n_sent,
        "avg_sentence_chars": round(avg, 1),
        "long_sentence_ratio": round(long_ratio, 3),
        "jargon_occurrences": jargon_occ,
        "jargon_per_1000_chars": round(jargon_occ / chars * 1000, 1) if chars else 0.0,
        "flesch_reading_ease": flesch,
        "metrics_source": "transform.md#body",
    }


# -------------------------------------------------------------------- contract
def contract_keys(case):
    oc = case.get("output_contract") if isinstance(case, dict) else None
    if oc is None and isinstance(case, dict):
        for alt in ("outputContract", "contract", "required_outputs"):
            if alt in case:
                oc = case.get(alt)
                break
    names = []
    if isinstance(oc, dict):
        for key in oc.keys():
            if key in ("required", "fields", "properties") and isinstance(oc[key], (list, dict)):
                continue
            names.append(key)
        for key in ("required", "fields", "properties"):
            val = oc.get(key)
            if isinstance(val, list):
                for item in val:
                    if isinstance(item, str):
                        names.append(item)
                    elif isinstance(item, dict):
                        n = item.get("name") or item.get("field") or item.get("key") or item.get("id")
                        if n:
                            names.append(n)
            elif isinstance(val, dict):
                names.extend(list(val.keys()))
    elif isinstance(oc, list):
        for item in oc:
            if isinstance(item, str):
                names.append(item)
            elif isinstance(item, dict):
                n = item.get("name") or item.get("field") or item.get("key") or item.get("id")
                if n:
                    names.append(n)
    seen, out = set(), []
    for n in names:
        if isinstance(n, str) and n.strip() and n not in seen:
            seen.add(n)
            out.append(n)
    return out


SLOT_ALIASES = {
    "transform": "transform_md", "transform_md": "transform_md", "article": "transform_md",
    "document": "transform_md", "manuscript": "transform_md", "rewrite": "transform_md",
    "output_text": "transform_md", "final_text": "transform_md", "deliverable": "transform_md",
    "markdown": "transform_md", "transformed_text": "transform_md", "final_markdown": "transform_md",
    "改写稿": "transform_md", "目标产物": "transform_md", "正文": "transform_md",
    "word_count": "word_count", "char_count": "char_count",
    "summary": "summary", "readability_notes": "readability_notes",
    "artifact_path": "artifact_path", "output_path": "artifact_path",
    "file_path": "artifact_path", "deliverable_file": "artifact_path",
    "deliverable_path": "artifact_path", "filename": "artifact_path",
    "preservation": "preservation", "preservation_map": "preservation_rows",
    "claim_map": "preservation_rows", "evidence_map": "preservation_rows",
    "source_map": "preservation_rows", "evidence_index": "preservation_rows",
    "citation_map": "preservation_rows", "claims": "preservation_rows",
    "事实与来源映射": "preservation_rows", "glossary": "glossary_rows",
    "terms": "glossary_rows", "terminology": "glossary_rows", "术语表": "glossary_rows",
    "metrics": "metrics", "readability": "metrics", "length": "metrics",
    "字数": "metrics", "可读性": "metrics", "sources": "sources",
    "uncertainty": "uncertainty", "change_log": "change_log", "changes": "change_log",
    "change_notes": "change_log", "issues": "issues",
    "deliverables": "deliverables", "status": "status", "case_id": "case_id",
    "title": "title", "audience": "audience", "genre": "genre",
    "target_length": "target_length", "limits": "limitations_check",
    "constraints": "limitations_check", "self_check": "self_check",
    "audit": "self_check", "numbers": "numbers", "omissions": "omissions",
    "removals": "removals", "conflicts": "conflicts",
}


def slot_of(name):
    key = (name or "").strip()
    low = key.lower().replace("-", "_").replace(" ", "_")
    return SLOT_ALIASES.get(key) or SLOT_ALIASES.get(low)


def resolve_contract_value(name, slot, result, plan, transform_text):
    provided = plan.get("contract_fields")
    if isinstance(provided, dict) and name in provided and provided[name] is not None:
        return provided[name]
    if slot == "transform_md":
        return transform_text
    if slot == "artifact_path":
        return OUT_TRANSFORM
    if slot == "self_check":
        pr = result.get("preservation", {})
        m = result.get("metrics", {})
        return {
            "claims": pr.get("claim_count"), "verified": pr.get("verified_claims"),
            "verification_rate": pr.get("verification_rate"),
            "unsupported_numbers": sum(1 for n in result.get("numbers", [])
                                       if n.get("status") == "unsupported"),
            "error_issues": sum(1 for i in result.get("issues", [])
                                if i.get("severity") == "error"),
            "metrics": m,
        }
    if slot == "limitations_check":
        return result.get("limitations_check")
    if slot in ("numbers", "omissions", "removals", "conflicts"):
        return result.get(slot)
    if slot == "preservation_rows":
        return result.get("preservation", {}).get("claims", [])
    if slot == "glossary_rows":
        return result.get("glossary", [])
    if slot == "word_count":
        return result.get("metrics", {}).get("words")
    if slot == "char_count":
        return result.get("metrics", {}).get("chars")
    if slot == "summary":
        sections = result.get("transform", {}).get("sections") or []
        return sections[0]["paragraphs"][0] if sections and sections[0]["paragraphs"] else ""
    if slot == "readability_notes":
        m = result.get("metrics", {})
        return ("正文 %s 字符、%s 词；平均句长 %s 字符；术语密度 %s/千字符"
                % (m.get("chars"), m.get("words"), m.get("avg_sentence_chars"),
                   m.get("jargon_per_1000_chars")))
    if slot in ("metrics", "sources", "uncertainty", "change_log", "issues",
                "deliverables", "status", "case_id", "title", "audience",
                "genre", "target_length"):
        return result.get(slot)
    if name in result:
        return result[name]
    if name in plan:
        return plan[name]
    return ""


# ------------------------------------------------------------------------ main
def run(args):
    issues = []
    uncertainty = []
    change_log = []
    plan = load_json(args.plan, None)
    plan_missing = not isinstance(plan, dict)
    if plan_missing:
        plan = {}
        issues.append(issue("plan_missing", "error",
                            "未找到或无法解析 plan.json；没有正文可交付", args.plan))
    sources, docs, paragraphs, full_text, src_numbers = load_sources(args.sources)
    case = load_json(args.case, {}) or {}
    case_id = str(case.get("case_id") or case.get("id") or plan.get("case_id") or "unknown")
    if not docs:
        issues.append(issue("no_readable_sources", "error",
                            "sources.json 中没有可读文档，无法核对事实与数值", args.sources))

    audience = norm_audience(plan.get("audience"))
    genre, genre_supported = norm_genre(plan.get("genre"))
    lay = is_lay_audience(audience)
    target_length = plan.get("target_length") or {}
    if isinstance(target_length, str):
        nums = re.findall(r"\d+", target_length)
        target_length = {"max_words": int(nums[0])} if nums else {}
    if not isinstance(target_length, dict):
        target_length = {}
    claims = norm_claims(plan)
    glossary = norm_glossary(plan)
    removals = norm_removals(plan)
    if not audience:
        issues.append(issue("audience_missing", "warn", "plan.json 未说明目标读者", "plan.audience"))
    if not plan.get("genre"):
        issues.append(issue("genre_missing", "warn", "plan.json 未说明目标体裁", "plan.genre"))
    if not isinstance(target_length, dict) or not target_length:
        issues.append(issue("target_length_missing", "warn",
                            "plan.json 未给出篇幅上限，无法核对篇幅约束", "plan.target_length"))

    sections = norm_sections(plan, claims)
    title = str(plan.get("title") or source_title(paragraphs)).strip()
    transform_text, appendix = compose_markdown(plan, sections, glossary, title)
    body_text, _appendix_text = split_body(transform_text)
    paras = body_paragraphs(sections)

    # claims: quote verification and output location
    full_sq = squash(full_text)
    for c in claims:
        ok, hit = verify_quote(c["quote"], c["anchor"], paragraphs, full_sq)
        c["verified"] = ok
        c["verified_anchor"] = hit
        if not c["quote"]:
            issues.append(issue("claim_missing_quote", "error",
                                "claim %s 没有源文引文，无法核验" % c["id"], c["id"]))
            c["status"] = "missing_quote"
        elif not ok:
            issues.append(issue("quote_unverified", "error",
                                "claim %s 的引文在源文中找不到：%s"
                                % (c["id"], canon(c["quote"])[:90]), c["id"]))
            c["status"] = "unverified"
            uncertainty.append({"issue": "claim %s 引文未核验" % c["id"],
                                "decision": "保留 claim 但标记 unverified，需作者回原文确认",
                                "needs_human": True})
        else:
            if hit and c["anchor"] and hit != c["anchor"] and hit != "(spanning paragraphs)":
                change_log.append("claim %s 锚点由 %s 校正为 %s（引文命中）"
                                  % (c["id"], c["anchor"], hit))
                c["anchor"] = hit
            c["status"] = "verified"
        p, match, loc = locate(c["claim"], paras, c["output_text"])
        if p is None and c["claim"]:
            issues.append(issue("claim_not_in_output", "error",
                                "claim %s 在正文中找不到对应表述" % c["id"], c["id"]))
            c["status"] = "not_in_output" if c["status"] == "verified" else c["status"]
        elif p is not None:
            c["output_location"] = loc
            c["output_excerpt"] = canon(p["text"])[:140]
            c["match"] = match
        check_strength(c, issues, p)
    if not claims:
        issues.append(issue("no_claim_evidence", "error",
                            "plan.claim_evidence 为空：正文没有可回溯的事实映射", "plan.claim_evidence"))

    # numbers
    declared = []
    raw_numbers = plan.get("numbers") or []
    if isinstance(raw_numbers, dict):
        raw_numbers = [{"value": k, "basis": v} for k, v in raw_numbers.items()]
    for d in raw_numbers:
        if isinstance(d, dict):
            declared.append({"value": str(d.get("value") or d.get("token") or "").strip(),
                             "basis": str(d.get("basis") or d.get("derivation") or "").strip(),
                             "anchor": str(d.get("anchor") or "").strip()})
    numbers = check_numbers(body_text, src_numbers, declared, issues, paragraphs)

    # glossary / jargon
    jargon_occ, unglossed = check_glossary(body_text, transform_text, glossary, lay, issues)

    # removals and omissions
    for r in removals:
        if not r["reason"]:
            issues.append(issue("removal_missing_reason", "error",
                                "删除项缺少理由：%s" % (r["removed"] or r["source_anchor"]),
                                "plan.removals"))
        if r["risk"] not in ("none", "low", "medium", "high"):
            issues.append(issue("removal_risk_invalid", "warn",
                                "删除项 risk 取值应为 none/low/medium/high，实际为 %r" % r["risk"],
                                "plan.removals"))
        if r["risk"] == "high":
            uncertainty.append({"issue": "高风险删除：%s" % (r["removed"] or r["source_anchor"]),
                                "decision": "已记录理由，需作者确认",
                                "needs_human": True})
    omissions = check_omissions(paragraphs, body_text, removals, issues)
    limits = check_limitations(paragraphs, claims, removals, body_text, issues)
    conflicts = detect_conflicts(paragraphs)
    for c in conflicts:
        uncertainty.append({"issue": "源文可能存在互斥表述：%s vs %s"
                                       % (c["anchor_a"], c["anchor_b"]),
                            "decision": "两处均保留，未合并，需作者判断",
                            "needs_human": True})
        issues.append(issue("source_conflict", "warn",
                            "源文两处表述高度相似但数值不同：%s vs %s"
                            % (c["anchor_a"], c["anchor_b"]), c["anchor_a"]))
    allowed_quotes = set()
    for q in plan.get("quoted_material") or []:
        if isinstance(q, str):
            allowed_quotes.add(squash(q))
        elif isinstance(q, dict):
            allowed_quotes.add(squash(q.get("quote") or ""))
    check_fabrication(body_text, full_text, full_sq, allowed_quotes, issues)
    check_hype(body_text, full_text, issues, uncertainty)
    for m in sorted(set(x.group(0) for x in PLACEHOLDER_RE.finditer(transform_text))):
        issues.append(issue("placeholder_in_output", "error",
                            "成稿残留占位符：%s" % m, "transform.md"))
        uncertainty.append({"issue": "成稿含占位符 %s" % m,
                            "decision": "必须替换为真实内容或改写，不得当作完成稿",
                            "needs_human": True})

    # genre / audience adaptation
    genre_ok = check_genre(genre, genre_supported, sections, issues, uncertainty)
    if lay and unglossed:
        pass  # already recorded as error for lay audiences
    if lay and not glossary:
        issues.append(issue("no_glossary_for_lay_audience", "error",
                            "目标读者为非专业读者，但 plan.glossary 为空", "plan.glossary"))

    # metrics and length
    metrics = compute_metrics(body_text, jargon_occ)
    check_length(metrics, target_length, issues)
    if lay and metrics["avg_sentence_chars"] > 70 and metrics["sentences"] > 3:
        issues.append(issue("sentences_too_long", "warn",
                            "面向非专业读者，平均句长 %.1f 字符，建议拆分长句"
                            % metrics["avg_sentence_chars"], "transform.md"))
    if lay and metrics["jargon_per_1000_chars"] > 15:
        issues.append(issue("jargon_density_high", "warn",
                            "术语密度 %.1f/千字符，对非专业读者偏高"
                            % metrics["jargon_per_1000_chars"], "transform.md"))

    # status
    has_body = any(s["paragraphs"] for s in sections)
    errors = [i for i in issues if i["severity"] == "error"]
    unlogged_n = sum(1 for o in omissions if o["status"] == "unlogged")
    if not has_body:
        status = "failed"
        status_reason = "正文为空：plan.json 未提供 sections.paragraphs 或 claim_evidence.output_text"
    elif errors or conflicts or unlogged_n:
        status = "partial"
        reasons = []
        if errors:
            reasons.append("%d 项硬性问题" % len(errors))
        if conflicts:
            reasons.append("%d 处源文冲突待人工判断" % len(conflicts))
        if unlogged_n:
            reasons.append("%d 条源文遗漏未登记" % unlogged_n)
        status_reason = "存在 %s（见 issues/uncertainty），已产出可编辑稿但需修复" % "、".join(reasons)
    elif not genre_supported or not audience or not plan.get("genre"):
        status = "partial"
        status_reason = "缺少受众/体裁约束或体裁无内置模板，无法确认改编是否达标"
    else:
        status = "success"
        status_reason = "引文、数值、术语、删除记录与篇幅检查均通过"

    # confidence / uncertainty merge
    for u in plan.get("uncertainty") or []:
        if isinstance(u, str):
            uncertainty.append({"issue": u, "decision": "", "needs_human": True})
        elif isinstance(u, dict):
            uncertainty.append({"issue": str(u.get("issue") or u.get("text") or ""),
                                "decision": str(u.get("decision") or ""),
                                "needs_human": bool(u.get("needs_human", True))})
    seen, unc = set(), []
    for u in uncertainty:
        key = squash(u["issue"])
        if key and key not in seen:
            seen.add(key)
            unc.append(u)

    # change log
    change_log = list(plan.get("change_log") or []) + change_log
    change_log += [
        "读取 sources.json：%d 个文档，%d 个段落，索引数值 %d 个"
        % (len(docs), len(paragraphs), len(src_numbers)),
        "按体裁 %s / 读者 %s 组装 %d 个章节，正文 %d 字符 / %d 词"
        % (genre, audience.get("description") or "未说明", len(sections),
           metrics["chars"], metrics["words"]),
        "核验 claim_evidence：%d 条，引文通过 %d 条"
        % (len(claims), sum(1 for c in claims if c["verified"])),
        "核验数值：%d 个 token，源文命中 %d，推导 %d，无依据 %d"
        % (len(numbers), sum(1 for n in numbers if n["status"].startswith("verbatim")),
           sum(1 for n in numbers if n["status"] == "derived"),
           sum(1 for n in numbers if n["status"] == "unsupported")),
        "术语表：%d 条；删除记录：%d 条；候选遗漏：%d 条（未登记 %d 条）"
        % (len(glossary), len(removals), len(omissions),
           sum(1 for o in omissions if o["status"] == "unlogged")),
        "可读性指标由 transform.md 正文实际计算（非估算）",
        "status=%s：%s" % (status, status_reason),
    ]

    # claims table
    claim_rows = []
    for c in claims:
        claim_rows.append({
            "id": c["id"], "kind": c["kind"], "claim": c["claim"],
            "doc": (re.search(r"(doc\.\d+)", c["anchor"]) or [None, ""])[1]
            if c["anchor"] else "",
            "anchor": c["anchor"], "quote": c["quote"], "verified": c["verified"],
            "strength": c["strength"], "source_strength": c["source_strength"],
            "output_location": c["output_location"], "output_excerpt": c["output_excerpt"],
            "match": c["match"], "status": c["status"],
        })
    verified_count = sum(1 for c in claims if c["verified"])
    located = sum(1 for c in claims if c["output_location"])

    # write files
    os.makedirs(args.out, exist_ok=True)
    os.makedirs(args.work, exist_ok=True)
    path_transform = os.path.join(args.out, OUT_TRANSFORM)
    with open(path_transform, "w", encoding="utf-8") as fh:
        fh.write(transform_text)

    path_map = os.path.join(args.out, OUT_MAP)
    with open(path_map, "w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(["claim_id", "kind", "claim", "source_doc", "anchor", "quote",
                         "quote_verified", "strength", "source_strength",
                         "output_location", "output_excerpt", "match", "status"])
        for r in claim_rows:
            writer.writerow([r["id"], r["kind"], r["claim"], r["doc"], r["anchor"],
                             r["quote"], r["verified"], r["strength"], r["source_strength"],
                             r["output_location"], r["output_excerpt"], r["match"],
                             r["status"]])

    path_gloss = os.path.join(args.out, OUT_GLOSSARY)
    with open(path_gloss, "w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(["term", "plain_language", "action", "aliases", "occurrences",
                         "inline_expanded", "status", "source_note"])
        for g in glossary:
            writer.writerow([g["term"], g["plain"], g["action"], "|".join(g["aliases"]),
                             g["occurrences"], g["inline_expanded"], g["status"],
                             g["source_note"]])

    deliverables = []
    for path in (path_transform, path_map, path_gloss):
        deliverables.append({"name": os.path.basename(path),
                             "path": os.path.join("/app/output", os.path.basename(path))
                             if os.path.abspath(args.out) == os.path.abspath("/app/output")
                             else path,
                             "bytes": os.path.getsize(path),
                             "sha256": sha256_file(path)})

    result = {
        "case_id": case_id,
        "status": status,
        "status_reason": status_reason,
        "sources": [{
            "doc": d.get("doc"), "path": d.get("path"), "sha256": d.get("sha256"),
            "engine": d.get("engine"), "readable": d.get("readable"),
            "paragraphs": len(d.get("paragraphs") or []),
            "warnings": d.get("warnings") or [],
        } for d in docs],
        "uncertainty": unc,
        "change_log": change_log,
        "issues": issues,
        "deliverables": deliverables,
        "transform": {
            "title": title, "genre": genre, "genre_label": GENRE_PROFILES.get(genre, ("自定义", []))[0],
            "audience": audience, "target_length": target_length,
            "sections": [{"id": s["id"], "heading": s["heading"], "role": s["role"],
                          "paragraphs": s["paragraphs"]} for s in sections],
            "file": OUT_TRANSFORM,
            "word_count": metrics["words"], "char_count": metrics["chars"],
        },
        "metrics": metrics,
        "preservation": {
            "claims": claim_rows,
            "claim_count": len(claims),
            "verified_claims": verified_count,
            "verification_rate": round(verified_count / len(claims), 4) if claims else 0.0,
            "located_claims": located,
            "locate_rate": round(located / len(claims), 4) if claims else 0.0,
            "map_file": OUT_MAP,
        },
        "glossary": glossary,
        "removals": removals,
        "omissions": omissions,
        "limitations_check": limits,
        "numbers": numbers,
        "conflicts": conflicts,
        "contract_fields": {},
    }

    # contract
    keys = contract_keys(case)
    if not keys:
        issues.append(issue("output_contract_missing", "warn",
                            "case.json 未声明 output_contract；已输出通用结构字段", "case"))
    body_check = transform_text
    for key in keys:
        slot = slot_of(key)
        value = resolve_contract_value(key, slot, result, plan, body_check)
        result["contract_fields"][key] = value
        result[key] = value
        if value in (None, "", [], {}):
            issues.append(issue("contract_field_empty", "warn",
                                "契约字段 %s 未取到内容，已留空待人工补齐" % key, "result.json"))
    result["issues"] = issues
    result["change_log"] = change_log + [
        "按 output_contract 写入 %d 个字段：%s" % (len(keys), ", ".join(keys) or "无"),
    ]

    result_path = os.path.join(args.out, "result.json")
    with open(result_path, "w", encoding="utf-8") as fh:
        json.dump(result, fh, ensure_ascii=False, indent=1)

    print(json.dumps({
        "case_id": case_id, "status": status, "genre": genre,
        "claims": len(claims), "verified": verified_count,
        "numbers": len(numbers),
        "unsupported_numbers": sum(1 for n in numbers if n["status"] == "unsupported"),
        "errors": len([i for i in issues if i["severity"] == "error"]),
        "warnings": len([i for i in issues if i["severity"] == "warn"]),
        "out": args.out,
    }, ensure_ascii=False))
    return 0 if status in ("success", "partial") else 1


def main(argv=None):
    ap = argparse.ArgumentParser(description="Build a source-faithful genre transform")
    ap.add_argument("--plan", default="/app/work/plan.json")
    ap.add_argument("--sources", default="/app/work/sources.json")
    ap.add_argument("--case", default="/input/case.json")
    ap.add_argument("--out", default="/app/output")
    ap.add_argument("--work", default="/app/work")
    args = ap.parse_args(argv)
    try:
        return run(args)
    except Exception as exc:  # noqa: BLE001
        sys.stderr.write("[build_transform] %s: %s\n" % (type(exc).__name__, exc))
        try:
            os.makedirs(args.out, exist_ok=True)
            payload = {
                "case_id": "unknown", "status": "failed",
                "status_reason": "内部异常：%s" % exc,
                "sources": [], "uncertainty": [{"issue": "内部异常", "decision": "",
                                                "needs_human": True}],
                "change_log": [], "issues": [issue("internal_error", "error", str(exc)[:300])],
                "deliverables": [], "contract_fields": {},
            }
            with open(os.path.join(args.out, "result.json"), "w", encoding="utf-8") as fh:
                json.dump(payload, fh, ensure_ascii=False, indent=1)
            with open(os.path.join(args.out, OUT_TRANSFORM), "w", encoding="utf-8") as fh:
                fh.write("# 成果转化稿\n\n本次运行失败，未生成正文。\n")
        except Exception:  # noqa: BLE001
            pass
        return 1


if __name__ == "__main__":
    sys.exit(main())
