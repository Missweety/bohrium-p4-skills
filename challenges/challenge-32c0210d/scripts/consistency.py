#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""consistency.py -- 学位论文长文档的跨章节一致性检查。

检查族（每条都指回 段落号 + 句号 + 字符偏移 + 逐字引文）：
    terminology  缩写冲突/先用后定义/未定义/拉丁词大小写与连字符变体/中文术语截短
    symbol       同一符号多种含义 / 符号先使用后定义
    definition   同一术语在多个章节被重复定义
    numbering    章节号重复或断号、标题层级跳跃、图表号重复/断号/章前缀不符、公式编号断号
    reference    正文引用指向不存在的图表/公式；图表从未被正文引用
    citation     正文编号引用超出参考文献表；参考文献条目从未被引用
    conclusion   同一主语在不同章节出现相反结论（候选，需人工确认）

边界：
    * 只报能在原文逐字找到的内容，不猜数据；
    * 自动修只允许"排版级"变体，且只允许"升格到带大写的规范写法"（不把小写当规范去改专名）；
    * 语义级问题（符号多义、结论相反、编号重排、引用缺失）auto_fixable=False。
"""
from __future__ import annotations

import difflib
import re
from collections import Counter, OrderedDict, defaultdict

import locate

GREEK = "αβγδεζηθικλμνξοπρστυφχψωΑΒΓΔΕΖΗΘΙΚΛΜΝΞΟΠΡΣΤΥΦΧΨΩ"
STOP_LATIN = {
    "the", "and", "for", "with", "that", "this", "these", "those", "from", "into",
    "than", "then", "when", "where", "which", "while", "were", "was", "has", "have",
    "had", "not", "but", "are", "our", "its", "can", "may", "also", "such", "using",
    "used", "use", "based", "between", "under", "over", "each", "both", "more",
    "most", "less", "least", "all", "any", "some", "one", "two", "three", "per",
    "figure", "table", "section", "chapter", "paper", "work", "method", "model",
}
STOP_ACRONYM = {"PDF", "DOCX", "DOC", "DOI", "URL", "HTTP", "HTTPS", "API", "JSON",
                "XML", "CSV", "HTML", "ID", "OK", "AI", "GPU", "CPU", "ISBN", "ISSN"}
GENERIC_CN = {"神经网络", "网络", "模型", "方法", "算法", "系统", "分析", "学习", "数据",
              "实验", "结果", "研究", "训练", "测试", "特征", "参数", "性能", "任务"}
CN_DEF_MARKERS = ("是指", "定义为", "指的是", "被定义为", "记作", "称为")
POS = ("显著提升", "显著提高", "显著改善", "明显提升", "明显提高", "明显优于",
       "有效改善", "优于", "提升了", "提高了")
NEG = ("未显著", "没有显著", "无显著差异", "并未提升", "未见提升", "未见明显改善",
       "不显著", "劣于", "显著下降", "没有提升", "未观察到显著", "未观察到")

ABBR_DEF = re.compile(
    r"(?P<full>[A-Za-z\u4e00-\u9fa5][A-Za-z0-9\u4e00-\u9fa5\-–/、 ]{0,40}?)"
    r"\s*[（(]\s*(?P<abbr>[A-Z][A-Za-z0-9\-]{1,11})\s*[)）]")
LATIN_TOKEN = re.compile(r"(?<![A-Za-z0-9_\-])[A-Za-z][A-Za-z0-9]*(?:[-–][A-Za-z0-9]+)*(?![A-Za-z0-9_\-])")
ACRONYM = re.compile(r"(?<![A-Za-z0-9])([A-Z]{2,8})(?![A-Za-z0-9])")
CN_TERM = re.compile(r"[\u4e00-\u9fa5]{2,16}")
FIG_REF = re.compile(r"(?:图|Fig(?:ure)?\.?)\s*([0-9]{1,2}(?:\s*[-–—.]\s*[0-9]{1,2})?)")
TAB_REF = re.compile(r"(?:表|Table)\s*([0-9]{1,2}(?:\s*[-–—.]\s*[0-9]{1,2})?)")
EQ_REF = re.compile(r"(?:式|Eq(?:uation)?\.?)\s*[（(]?\s*([0-9]{1,2}(?:\s*[-–—.]\s*[0-9]{1,2})?)\s*[)）]?")
EQ_TAG = re.compile(r"[（(]\s*([0-9]{1,2}\s*[-–—.]\s*[0-9]{1,2})\s*[)）]\s*$")
CITE_IN_TEXT = re.compile(r"[\[［]\s*([0-9][0-9,，、\-–—\s]*)\s*[\]］]")
CITE_ENTRY = re.compile(r"^\s*[\[［]?\s*([0-9]{1,3})\s*[\]］.)）]\s*")
SYMBOL_DEF = re.compile(
    r"(?P<sym>[%s]|[A-Za-z]_[A-Za-z0-9{}+]+)\s*(?:表示|代表|定义为|记为|为)\s*"
    r"(?P<meaning>[\u4e00-\u9fa5A-Za-z][\u4e00-\u9fa5A-Za-z0-9 ]{1,18})" % GREEK)
_SENT_BOUNDARY = "。！？!?；;：:"


def _norm_num(s):
    return re.sub(r"\s*[-–—.]\s*", "-", s.strip())


def _squash(s):
    return re.sub(r"[\s\-–—_]", "", s).lower()


def _is_sentence_initial(text, i):
    """i 前只有空白/句末标点/引号 => 句首（标题式大写属惯例，不算变体）。"""
    j = i - 1
    while j >= 0 and text[j] in " \t\u3000":
        j -= 1
    if j < 0:
        return True
    return text[j] in _SENT_BOUNDARY or text[j] in "“”「」\"'（("


def _polarity(q):
    """+1 肯定 / -1 否定 / 0 中性或方向不明。否定词覆盖阳性表述时判为否定。"""
    pos = [(m.start(), m.end()) for w in POS for m in re.finditer(re.escape(w), q)]
    neg = [(m.start(), m.end()) for w in NEG for m in re.finditer(re.escape(w), q)]
    if not pos and not neg:
        return 0
    if not neg:
        return 1
    if not pos:
        return -1

    def negated(p_start):
        for a, _b in neg:
            if a < p_start and not re.search(r"但|但是|然而|不过|却|反而", q[a:p_start]):
                return True
        return False

    return -1 if all(negated(p) for p, _ in pos) else 0


class Analyzer:
    def __init__(self, paragraphs, tables, sections, options=None):
        self.ps = paragraphs
        self.by_id = {p["id"]: p for p in paragraphs}
        self.tables = tables
        self.sections = sections
        self.options = options or {}
        self.findings = []
        self.coverage = OrderedDict()
        self._build_chapter_map()

    # ------------------------------------------------------------------ #
    def add(self, rule, kind, severity, confidence, location, summary, why,
            evidence=None, auto_fixable=False, suggested_fix=None,
            needs_manual=False, extra=None):
        f = {"id": "C%03d" % (len(self.findings) + 1), "rule": rule, "kind": kind,
             "severity": severity, "confidence": confidence, "location": location,
             "summary": summary, "why": why, "evidence": evidence or [],
             "auto_fixable": bool(auto_fixable), "suggested_fix": suggested_fix,
             "needs_manual_confirmation": bool(needs_manual)}
        if extra:
            f.update(extra)
        self.findings.append(f)
        return f

    def _build_chapter_map(self):
        cur = None
        for p in self.ps:
            top = (p.get("section") or "").split(".")[0].lstrip("§")
            if re.fullmatch(r"[0-9]{1,2}", top or ""):
                cur = top
            p["_chapter"] = cur

    def loc(self, p, start, end, quote=None):
        si, (a, b, q) = locate.sentence_at(p["text"], max(0, start))
        return {"paragraph_id": p["id"], "section": p.get("section"),
                "section_title": p.get("section_title"), "sentence_index": si + 1,
                "char_start": start, "char_end": end,
                "anchor_quote": quote if quote is not None else p["text"][start:end],
                "sentence_quote": q, "source_path": p.get("source_path")}

    # ------------------------------------------------------------------ #
    # 术语
    # ------------------------------------------------------------------ #
    def check_terminology(self):
        defs = []
        for p in self.ps:
            for m in ABBR_DEF.finditer(p["text"]):
                full = self._trim_full(m.group("full"))
                abbr = m.group("abbr")
                if not full or len(abbr) < 2:
                    continue
                defs.append({"abbr": abbr, "full": full, "paragraph_id": p["id"],
                             "section": p.get("section"), "start": m.start(),
                             "end": m.end(), "quote": p["text"][m.start():m.end()]})

        by_abbr = defaultdict(list)
        for d in defs:
            by_abbr[d["abbr"]].append(d)
        for abbr, items in by_abbr.items():
            uniq = OrderedDict()
            for d in items:
                uniq.setdefault(_squash(d["full"]), d)
            if len(uniq) > 1:
                first = items[0]
                p = self.by_id[first["paragraph_id"]]
                self.add("terminology.abbr_conflict", "terminology", "high", "high",
                         self.loc(p, first["start"], first["end"], first["quote"]),
                         "缩写 %s 被展开成 %d 种不同全称" % (abbr, len(uniq)),
                         "同一缩写在文中应只有一个规范全称，否则读者无法判断指代对象。",
                         evidence=[{"paragraph_id": d["paragraph_id"], "section": d["section"],
                                    "quote": d["quote"]} for d in items],
                         suggested_fix="确定唯一规范全称（建议取首次定义处），其余位置统一。",
                         needs_manual=True,
                         extra={"abbr": abbr, "variants": [d["full"] for d in items]})

        # 缩写先用后定义 / 从未定义
        acro_use, first_use = Counter(), {}
        for p in self.ps:
            for m in ACRONYM.finditer(p["text"]):
                tok = m.group(1)
                if tok in STOP_ACRONYM:
                    continue
                acro_use[tok] += 1
                first_use.setdefault(tok, (p, m.start(), m.end()))
        defined_at = {d["abbr"]: self.by_id[d["paragraph_id"]]["index"] for d in defs}
        for tok, (p, s, e) in first_use.items():
            if tok in defined_at:
                if p["index"] < defined_at[tok]:
                    self.add("terminology.abbr_used_before_definition", "terminology",
                             "high", "high", self.loc(p, s, e, p["text"][s:e]),
                             "缩写 %s 在定义出现之前已被使用" % tok,
                             "首次出现处应给出全称与缩写；先使用后定义会让读者回溯。",
                             suggested_fix="把首次出现的缩写改为“全称（%s）”，或在此处补全称。" % tok)
            elif acro_use[tok] >= 2 and len(tok) >= 3:
                self.add("terminology.abbr_undefined", "terminology", "medium", "medium",
                         self.loc(p, s, e, p["text"][s:e]),
                         "缩写 %s 全文使用 %d 次但从未定义全称" % (tok, acro_use[tok]),
                         "未定义缩写属于术语不一致，评审通常要求补全称。",
                         suggested_fix="首次出现处补“全称（%s）”，或在术语表登记。" % tok,
                         needs_manual=True)

        # 拉丁词大小写/连字符变体：只统计"非句首"出现，避免把句首大写当变体
        surface, mid, first_seen = defaultdict(Counter), defaultdict(Counter), {}
        for p in self.ps:
            if p.get("is_heading"):
                continue
            for m in LATIN_TOKEN.finditer(p["text"]):
                tok = m.group(0)
                if len(tok) < 4 or tok.lower() in STOP_LATIN or tok.isupper():
                    continue
                if re.search(r"(https?://|@|\\)", p["text"][max(0, m.start() - 8):m.end() + 8]):
                    continue
                key = _squash(tok)
                surface[key][tok] += 1
                if not _is_sentence_initial(p["text"], m.start()):
                    mid[key][tok] += 1
                first_seen.setdefault((key, tok), (p, m.start(), m.end()))
        for key, forms in mid.items():
            if len(forms) < 2 or len(key) < 4 or sum(forms.values()) < 2:
                continue
            variants = list(forms)
            canonical = sorted(variants, key=lambda v: (-forms[v],
                                                        -sum(1 for c in v if c.isupper())))[0]
            host, s, e = first_seen[(key, variants[0])]
            bases = {v[:-1] if (v.lower().endswith("s") and not v.lower().endswith("ss")) else v
                     for v in variants}
            if len(bases) == 1:
                self.add("terminology.latin_plural_variant", "terminology", "low", "low",
                         self.loc(host, s, e, host["text"][s:e]),
                         "同一英文词出现单复数混合写法: %s" % ", ".join(variants),
                         "单复数可能承担语法功能，需人工判断是否统一；不自动改写。",
                         needs_manual=True)
                continue
            upper_canonical = any(c.isupper() for c in canonical)
            self.add("terminology.latin_variant", "terminology", "medium",
                     "high" if upper_canonical else "medium",
                     self.loc(host, s, e, host["text"][s:e]),
                     "同一英文术语存在 %d 种写法: %s" % (len(variants), ", ".join(variants)),
                     "大小写/连字符不一致会让检索、术语表和审稿统计失真。",
                     evidence=[{"paragraph_id": first_seen[(key, v)][0]["id"],
                                "quote": first_seen[(key, v)][0]["text"][
                                    first_seen[(key, v)][1]:first_seen[(key, v)][2]]}
                               for v in variants],
                     auto_fixable=upper_canonical,
                     suggested_fix="统一为写法：%s" % canonical,
                     needs_manual=not upper_canonical,
                     extra={"canonical": canonical, "variants": variants})

        # 中文术语截短：同一缩写对应的规范全称被缩短使用
        for abbr, items in by_abbr.items():
            for d0 in items:
                full = d0["full"]
                if not CN_TERM.fullmatch(full) or len(full) < 4:
                    continue
                for p in self.ps:
                    if p.get("is_heading") or full in p["text"]:
                        continue
                    cands = [c for c in set(CN_TERM.findall(p["text"]))
                             if c not in GENERIC_CN and len(c) >= 3 and c != full
                             and (c in full or full in c) and abs(len(c) - len(full)) <= 3]
                    if not cands:
                        continue
                    cand = min(cands, key=len)
                    off = p["text"].find(cand)
                    self.add("terminology.cn_variant", "terminology", "medium", "medium",
                             self.loc(p, off, off + len(cand)),
                             "术语 “%s” 与已定义全称 “%s”（%s）并用" % (cand, full, abbr),
                             "同一概念的截短写法会造成术语表与正文不一致；是否统一需作者确认。",
                             evidence=[{"paragraph_id": p["id"], "quote": cand}],
                             suggested_fix="统一为 “%s”；如确为不同概念请补定义。" % full,
                             needs_manual=True)
                    break

        # 运行工单显式给定的规范术语
        for bad, good in (self.options.get("canonical_terms") or {}).items():
            for p in self.ps:
                if p.get("in_table"):
                    continue
                off = p["text"].find(bad)
                if off >= 0:
                    self.add("terminology.workorder_term", "terminology", "medium", "high",
                             self.loc(p, off, off + len(bad)),
                             "任务指定统一术语：%s → %s" % (bad, good),
                             "该条来自运行时 organizer-edit-workorder.json 的显式要求。",
                             auto_fixable=True,
                             suggested_fix="把 %s 替换为 %s" % (bad, good),
                             extra={"canonical": good, "variants": [bad]})
                    break

        self.coverage["terminology"] = {
            "checked": True,
            "findings": sum(1 for f in self.findings if f["kind"] == "terminology"),
            "abbreviations_defined": len(defs),
            "latin_terms_indexed": len(surface)}
        return defs

    @staticmethod
    def _trim_full(full):
        full = full.strip(" ，,、：:；;")
        full = re.sub(r"^(?:本文|我们|本研究|该项|该|所提|所提出|提出的|一种|基于|其中)+", "", full)
        if len(full) > 24:
            m = re.search(r"([\u4e00-\u9fa5A-Za-z][\u4e00-\u9fa5A-Za-z\- ]{2,22})$", full)
            full = m.group(1) if m else full[-24:]
        return full.strip()

    # ------------------------------------------------------------------ #
    # 符号
    # ------------------------------------------------------------------ #
    def check_symbols(self):
        table_defs, sym_tables = [], 0
        for t in self.tables:
            if not t["rows"]:
                continue
            head = [str(c) for c in t["rows"][0]]
            if not any(re.search(r"符号|变量|记号|symbol", h, re.I) for h in head):
                continue
            sym_tables += 1
            i_sym = next(i for i, h in enumerate(head)
                         if re.search(r"符号|变量|记号|symbol", h, re.I))
            i_mean = next((i for i, h in enumerate(head)
                           if re.search(r"含义|意义|说明|定义|mean", h, re.I)), None)
            pids = t.get("cell_paragraph_ids") or []
            for ri, row in enumerate(t["rows"][1:], start=1):
                if len(row) <= i_sym or not str(row[i_sym]).strip():
                    continue
                sym = str(row[i_sym]).strip()
                pid = pids[ri][i_sym] if ri < len(pids) and i_sym < len(pids[ri]) else None
                host = self.by_id.get(pid) if pid else None
                off = host["text"].find(sym) if host else 0
                table_defs.append({
                    "symbol": sym,
                    "meaning": str(row[i_mean]).strip() if i_mean is not None and len(row) > i_mean else "",
                    "unit": "", "table_index": t["index"], "paragraph_id": pid,
                    "row_index": ri + 1, "start": off, "end": off + len(sym),
                    "section": host.get("section") if host else None, "quote": sym})

        inline = []
        for p in self.ps:
            if p.get("in_table"):
                continue
            for m in SYMBOL_DEF.finditer(p["text"]):
                inline.append({"symbol": m.group("sym"), "meaning": m.group("meaning").strip(),
                               "paragraph_id": p["id"], "section": p.get("section"),
                               "start": m.start(), "end": m.end(), "quote": m.group(0)})

        defs = OrderedDict()
        for d in table_defs:
            defs.setdefault(d["symbol"], []).append(dict(d, origin="table"))
        for d in inline:
            defs.setdefault(d["symbol"], []).append(dict(d, origin="inline"))

        conflicts = 0
        for sym, items in defs.items():
            meanings = OrderedDict()
            for d in items:
                if d["meaning"]:
                    meanings.setdefault(_squash(d["meaning"]), d)
            if len(meanings) > 1:
                conflicts += 1
                first = items[0]
                host = self.by_id.get(first.get("paragraph_id")) or self.ps[0]
                loc = self.loc(host, first["start"], first["end"], first["quote"])
                self.add("symbol.conflict", "symbol", "high", "high", loc,
                         "符号 %s 有 %d 种不同含义" % (sym, len(meanings)),
                         "同符号多义会直接导致公式与结果解读错误；须人工确定唯一含义或改名。",
                         evidence=[{"paragraph_id": d.get("paragraph_id"),
                                    "section": d.get("section"),
                                    "quote": d["quote"] or ("%s = %s" % (sym, d["meaning"]))}
                                   for d in items],
                         needs_manual=True,
                         suggested_fix="保留一种含义，另一处改用新符号并同步修改公式。",
                         extra={"symbol": sym, "meanings": [d["meaning"] for d in items]})

        for sym, items in defs.items():
            if not re.fullmatch(r"[%s]" % GREEK, sym):
                continue
            pids = [d["paragraph_id"] for d in items if d.get("paragraph_id")]
            if not pids:
                continue
            def_idx = min(self.by_id[x]["index"] for x in pids if x in self.by_id)
            for p in self.ps:
                if p["index"] >= def_idx:
                    break
                off = p["text"].find(sym)
                if off >= 0:
                    self.add("symbol.used_before_definition", "symbol", "medium", "medium",
                             self.loc(p, off, off + len(sym)),
                             "符号 %s 在定义（%s）之前已使用" % (sym, items[0]["meaning"]),
                             "符号应在首次出现处或符号表中定义，否则读者无法解析公式。",
                             suggested_fix="在首次出现处补“%s 表示 %s”，或前移符号表。"
                                           % (sym, items[0]["meaning"]))
                    break

        self.coverage["symbol"] = {
            "checked": True,
            "findings": sum(1 for f in self.findings if f["kind"] == "symbol"),
            "symbols": len(defs), "conflicts": conflicts, "symbol_tables": sym_tables}
        return [{"symbol": sym,
                 "definitions": items,
                 "meanings": sorted({d["meaning"] for d in items if d["meaning"]}),
                 "occurrences": len(items),
                 "status": "conflict" if len({_squash(d["meaning"]) for d in items if d["meaning"]}) > 1 else "ok"}
                for sym, items in defs.items()]

    # ------------------------------------------------------------------ #
    def check_duplicate_definitions(self):
        seen = defaultdict(list)
        pat = re.compile(r"(?:所称的?|所谓的?)?\s*([\u4e00-\u9fa5A-Za-z]{2,12})\s*(?:%s)"
                         % "|".join(CN_DEF_MARKERS))
        for p in self.ps:
            if p.get("in_table"):
                continue
            for m in pat.finditer(p["text"]):
                term = re.sub(r"^(?:本文|文中|本节|此处|该处|本章|所称|所谓|的)+", "", m.group(1))
                if term in ("本文", "文中", "此处", "该", "本节", "上述") or len(term) < 2:
                    continue
                seen[term].append({"paragraph_id": p["id"], "section": p.get("section"),
                                   "start": m.start(), "end": m.end(),
                                   "quote": p["text"][m.start():m.end()]})
        for term, items in seen.items():
            if len(items) >= 2 and len({i["section"] for i in items}) >= 2:
                last = items[-1]
                p = self.by_id[last["paragraph_id"]]
                self.add("definition.duplicate", "definition", "medium", "medium",
                         self.loc(p, last["start"], last["end"]),
                         "术语 “%s” 在 %d 个章节被重复定义" % (term, len({i["section"] for i in items})),
                         "重复定义易出现前后不一致；通常只需首次定义，后文回指。",
                         evidence=[{"paragraph_id": i["paragraph_id"], "section": i["section"],
                                    "quote": i["quote"]} for i in items],
                         suggested_fix="保留首次定义，后文改为回指（“前文定义的%s”）。" % term,
                         needs_manual=True, extra={"term": term})
        self.coverage["definition"] = {
            "checked": True,
            "findings": sum(1 for f in self.findings if f["kind"] == "definition"),
            "terms_defined": len(seen)}

    # ------------------------------------------------------------------ #
    def check_numbering(self):
        chapters = [(locate.heading_number(p["text"])[1], p)
                    for p in self.ps
                    if p.get("is_heading") and locate.heading_number(p["text"])[1]]
        dup = defaultdict(list)
        for num, p in chapters:
            if re.fullmatch(r"[0-9]{1,2}", num):
                dup[num].append(p)
        for num, ps in dup.items():
            if len(ps) > 1:
                p = ps[1]
                off = p["text"].find(num)
                self.add("numbering.chapter_duplicate", "numbering", "high", "high",
                         self.loc(p, off, off + len(num)),
                         "章节号 %s 重复出现 %d 次" % (num, len(ps)),
                         "重复章节号会让目录、交叉引用与页码定位失效。",
                         evidence=[{"paragraph_id": q["id"], "quote": q["text"].strip()} for q in ps],
                         suggested_fix="按顺序重排章号，并同步目录与交叉引用。", needs_manual=True)
        top = sorted({int(n) for n, _ in chapters if re.fullmatch(r"[0-9]{1,2}", n)})
        gaps = [n for n in range(top[0], top[-1] + 1) if n not in top] if top else []
        if gaps:
            p = chapters[0][1]
            self.add("numbering.chapter_gap", "numbering", "medium", "high",
                     self.loc(p, 0, min(len(p["text"]), 24)),
                     "章号不连续，缺 %s" % ", ".join(map(str, gaps)),
                     "断号说明有章节被删或未合入，需确认不是漏章。", needs_manual=True)
        prev_lvl = 0
        for num, p in chapters:
            lvl = locate.heading_number(p["text"])[0]
            if prev_lvl and lvl - prev_lvl > 1:
                off = p["text"].find(num)
                self.add("numbering.heading_level_jump", "numbering", "low", "medium",
                         self.loc(p, off, off + len(num)),
                         "标题层级从 %d 跳到 %d：%s" % (prev_lvl, lvl, p["text"].strip()[:40]),
                         "层级跳跃会让编号体系与样式不一致。", needs_manual=True)
            prev_lvl = lvl

        caps = []
        for p in self.ps:
            if p.get("in_table"):
                continue
            info = locate.caption_info(p)
            if info:
                info.update({"paragraph_id": p["id"], "section": p.get("section"),
                             "chapter": p.get("_chapter"), "text": p["text"].strip()})
                caps.append(info)
        by_kind = defaultdict(list)
        for c in caps:
            by_kind[c["kind"]].append(c)
        for kind, items in by_kind.items():
            label = "图" if kind == "figure" else "表"
            for num, cnt in Counter(c["number"] for c in items).items():
                if cnt > 1:
                    c = next(x for x in items if x["number"] == num)
                    p = self.by_id[c["paragraph_id"]]
                    self.add("numbering.caption_duplicate", "numbering", "high", "high",
                             self.loc(p, 0, min(len(p["text"]), 24)),
                             "%s号 %s 重复 %d 次" % (label, num, cnt),
                             "同一编号对应多个题注会让正文引用产生歧义。",
                             evidence=[{"paragraph_id": x["paragraph_id"], "quote": x["text"]}
                                       for x in items if x["number"] == num],
                             suggested_fix="按出现顺序重排编号并同步正文引用。", needs_manual=True)
            for c in items:
                pre = c.get("chapter_prefix")
                if pre and c.get("chapter") and pre != c["chapter"]:
                    p = self.by_id[c["paragraph_id"]]
                    self.add("numbering.caption_chapter_mismatch", "numbering", "high", "high",
                             self.loc(p, 0, min(len(p["text"]), 24)),
                             "%s%s 出现在第 %s 章" % (label, c["number"], c["chapter"]),
                             "图表号前缀应与所在章一致（本题采用“章-序号”编号）。",
                             suggested_fix="把编号改为 %s-%s，并同步正文引用。"
                                           % (c["chapter"], c["number"].split("-")[-1]),
                             needs_manual=True)
            seq = defaultdict(list)
            for c in items:
                if c.get("chapter_prefix"):
                    seq[c["chapter_prefix"]].append(int(c["number"].split("-")[-1]))
                else:
                    seq["_"].append(int(c["number"]))
            for pre, arr in seq.items():
                if len(arr) < 2:
                    continue
                miss = [n for n in range(min(arr), max(arr) + 1) if n not in arr]
                if miss:
                    c = next((x for x in items if (x.get("chapter_prefix") or "_") == pre), items[0])
                    p = self.by_id[c["paragraph_id"]]
                    self.add("numbering.caption_gap", "numbering", "medium", "high",
                             self.loc(p, 0, min(len(p["text"]), 24)),
                             "%s编号不连续（%s）：缺 %s" % (label, pre, ", ".join(map(str, miss))),
                             "断号通常意味着删图/漏排或编号未重排。", needs_manual=True)

        eqs = [( _norm_num(m.group(1)), p, m.start(1))
               for p in self.ps for m in [EQ_TAG.search(p["text"])] if m]
        for n, cnt in Counter(n for n, _, _ in eqs).items():
            if cnt > 1:
                p = next(q for x, q, _ in eqs if x == n)
                off = p["text"].find(n)
                self.add("numbering.equation_duplicate", "numbering", "medium", "high",
                         self.loc(p, off, off + len(n)),
                         "公式编号 (%s) 重复" % n, "公式编号必须唯一，否则无法被引用。",
                         needs_manual=True)
        by_pre = defaultdict(list)
        for n, _, _ in eqs:
            if "-" in n:
                by_pre[n.split("-")[0]].append(int(n.split("-")[-1]))
        for pre, arr in by_pre.items():
            if len(arr) < 2:
                continue
            miss = [i for i in range(min(arr), max(arr) + 1) if i not in arr]
            if miss:
                p = next(q for x, q, _ in eqs if x.startswith(pre + "-"))
                off = p["text"].find("(")
                self.add("numbering.equation_gap", "numbering", "low", "high",
                         self.loc(p, max(0, off), max(0, off) + 6),
                         "公式编号（%s-*）不连续，缺 %s" % (pre, ", ".join(map(str, miss))),
                         "断号可能来自删公式后未重排。", needs_manual=True)

        self.coverage["numbering"] = {
            "checked": True,
            "findings": sum(1 for f in self.findings if f["kind"] == "numbering"),
            "captions": len(caps), "equations": len(eqs), "headings": len(chapters)}
        return caps, eqs

    # ------------------------------------------------------------------ #
    def check_references(self, caps, eqs):
        targets = {"figure": set(), "table": set()}
        cap_by_key = {}
        for c in caps:
            targets[c["kind"]].add(c["number"])
            cap_by_key[(c["kind"], c["number"])] = c
        eq_set = {n for n, _, _ in eqs}
        cited = {"figure": Counter(), "table": Counter(), "equation": Counter()}
        dangling = 0
        for p in self.ps:
            if p.get("is_heading"):
                continue
            for kind, pat in (("figure", FIG_REF), ("table", TAB_REF), ("equation", EQ_REF)):
                for m in pat.finditer(p["text"]):
                    num = _norm_num(m.group(1))
                    if locate.CAPTION_RE.match(p["text"]) and m.start() < 12:
                        continue
                    cited[kind][num] += 1
                    pool = eq_set if kind == "equation" else targets[kind]
                    if num not in pool:
                        dangling += 1
                        label = {"figure": "图", "table": "表", "equation": "式"}[kind]
                        self.add("reference.dangling", "reference", "high", "high",
                                 self.loc(p, m.start(), m.end()),
                                 "正文引用了不存在的%s号 %s" % (label, num),
                                 "引用目标缺失会让读者无法定位图表/公式；常见于删图后未改正文。",
                                 suggested_fix="补回对应%s或改引到正确的%s号。" % (label, label),
                                 needs_manual=True,
                                 extra={"target_kind": kind, "target_number": num})
        for kind in ("figure", "table"):
            label = "图" if kind == "figure" else "表"
            for num in sorted(targets[kind]):
                if cited[kind][num] == 0:
                    c = cap_by_key[(kind, num)]
                    p = self.by_id[c["paragraph_id"]]
                    self.add("reference.uncited_caption", "reference", "low", "high",
                             self.loc(p, 0, min(len(p["text"]), 24)),
                             "%s%s 在正文中从未被引用" % (label, num),
                             "未被引用的图表通常应删除或补正文说明（部分期刊为硬性要求）。",
                             needs_manual=True)
        self.coverage["reference"] = {
            "checked": True,
            "findings": sum(1 for f in self.findings if f["kind"] == "reference"),
            "dangling": dangling, "figure_targets": len(targets["figure"]),
            "table_targets": len(targets["table"]), "equation_targets": len(eq_set)}

    # ------------------------------------------------------------------ #
    def check_citations(self):
        ref_secs = {s["key"] for s in self.sections
                    if re.search(r"参考文献|引用文献|references", s.get("title") or "", re.I)}
        entries = []
        for p in self.ps:
            if p.get("section") in ref_secs or re.search(
                    r"参考文献|references", p.get("section_title") or "", re.I):
                m = CITE_ENTRY.match(p["text"])
                if m:
                    entries.append({"number": int(m.group(1)), "paragraph_id": p["id"],
                                    "text": p["text"].strip()[:160]})
        entry_nums = {e["number"] for e in entries}
        in_text = []
        for p in self.ps:
            if p.get("section") in ref_secs or p.get("is_heading"):
                continue
            for m in CITE_IN_TEXT.finditer(p["text"]):
                for n in self._expand_cite(m.group(1)):
                    in_text.append((n, p, m.start(), m.end()))
        for n, p, s, e in in_text:
            if entry_nums and n not in entry_nums:
                self.add("citation.undefined_ref", "citation", "high", "high",
                         self.loc(p, s, e),
                         "正文引用 [%d] 在参考文献表中不存在（表内共 %d 条）" % (n, len(entry_nums)),
                         "引用不存在文献属于最严重的可核验性问题。",
                         suggested_fix="补入该文献条目，或核实并改为正确编号。",
                         needs_manual=True, extra={"citation_number": n})
        cited_nums = {n for n, _, _, _ in in_text}
        for e in entries:
            if entry_nums and e["number"] not in cited_nums:
                p = self.by_id[e["paragraph_id"]]
                self.add("citation.orphan_entry", "citation", "low", "medium",
                         self.loc(p, 0, min(len(p["text"]), 24)),
                         "参考文献 [%d] 在正文中从未被引用" % e["number"],
                         "未引用条目通常应删除或补正文引用。", needs_manual=True)
        self.coverage["citation"] = {
            "checked": True,
            "findings": sum(1 for f in self.findings if f["kind"] == "citation"),
            "reference_entries": len(entries), "in_text_citations": len(in_text),
            "reference_section": sorted(ref_secs)}

    @staticmethod
    def _expand_cite(raw):
        out = []
        for part in re.split(r"[,，、]", raw):
            part = part.strip()
            m = re.fullmatch(r"([0-9]+)\s*[-–—]\s*([0-9]+)", part)
            if m and 0 <= int(m.group(2)) - int(m.group(1)) <= 30:
                out.extend(range(int(m.group(1)), int(m.group(2)) + 1))
            elif re.fullmatch(r"[0-9]+", part):
                out.append(int(part))
        return out

    # ------------------------------------------------------------------ #
    def check_conclusions(self, defs):
        entities = {d["abbr"] for d in defs} | set(self.options.get("focus_terms") or [])
        pool = []
        for p in self.ps:
            if p.get("is_heading") or p.get("in_table") or len(p["text"]) < 8:
                continue
            for si, (a, b, q) in enumerate(locate.sentences(p["text"])):
                pool.append({"p": p, "start": a, "end": b, "q": q, "pol": _polarity(q)})
        conflicts = 0
        for ent in entities:
            pos = [s for s in pool if ent and ent in s["q"] and s["pol"] > 0]
            neg = [s for s in pool if ent and ent in s["q"] and s["pol"] < 0]
            if not pos or not neg:
                continue
            if {s["p"]["section"] for s in pos} & {s["p"]["section"] for s in neg}:
                continue
            a, b = pos[0], neg[0]
            conflicts += 1
            self.add("conclusion.cross_section_conflict", "conclusion", "medium", "medium",
                     self.loc(a["p"], a["start"], a["end"], a["q"]),
                     "“%s” 在不同章节出现方向相反的结论" % ent,
                     "跨章节结论冲突需作者确认哪一处为准；脚本只做候选定位，不改写。",
                     evidence=[{"paragraph_id": a["p"]["id"], "section": a["p"]["section"], "quote": a["q"]},
                               {"paragraph_id": b["p"]["id"], "section": b["p"]["section"], "quote": b["q"]}],
                     needs_manual=True, extra={"entity": ent})
        for i in range(len(pool)):
            for j in range(i + 1, len(pool)):
                x, y = pool[i], pool[j]
                if x["pol"] * y["pol"] >= 0 or x["p"]["section"] == y["p"]["section"]:
                    continue
                if min(len(x["q"]), len(y["q"])) < 10:
                    continue
                cp = 0
                for a, b in zip(x["q"], y["q"]):
                    if a != b:
                        break
                    cp += 1
                r = difflib.SequenceMatcher(None, x["q"], y["q"]).ratio()
                if r < 0.62 and cp < 6:
                    continue
                conflicts += 1
                self.add("conclusion.similar_opposite", "conclusion", "medium", "medium",
                         self.loc(x["p"], x["start"], x["end"], x["q"]),
                         "两处表述共享主语但结论方向相反（相似度 %.2f，共同前缀 %d 字）" % (r, cp),
                         "可能是改稿后前后未同步；需作者确认保留哪一处。",
                         evidence=[{"paragraph_id": x["p"]["id"], "section": x["p"]["section"], "quote": x["q"]},
                                   {"paragraph_id": y["p"]["id"], "section": y["p"]["section"], "quote": y["q"]}],
                         needs_manual=True)
        self.coverage["conclusion"] = {
            "checked": True,
            "findings": sum(1 for f in self.findings if f["kind"] == "conclusion"),
            "candidates": conflicts}

    # ------------------------------------------------------------------ #
    def run(self):
        defs = self.check_terminology()
        symbols = self.check_symbols()
        self.check_duplicate_definitions()
        caps, eqs = self.check_numbering()
        self.check_references(caps, eqs)
        self.check_citations()
        self.check_conclusions(defs)
        return {"findings": self.findings, "term_table": defs, "symbol_table": symbols,
                "caption_table": caps,
                "equation_list": [{"number": n, "paragraph_id": p["id"]} for n, p, _ in eqs],
                "coverage": dict(self.coverage),
                "severity_counts": dict(Counter(f["severity"] for f in self.findings))}
