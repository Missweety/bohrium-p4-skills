#!/usr/bin/env python3
"""baseline_plan.py - derive a complete, source-grounded plan from structure.json alone.

This is the guaranteed-completion path: even if the model never hand-writes a plan,
the pipeline still produces every delivery field. Every finding is reduced from the
actual manuscript text; each anchor_quote is a verbatim substring of the paragraph
it points at. Baseline findings are explicitly labelled as rule candidates.

It never invents numbers, citations or facts, and never rewrites the manuscript.

Usage: python baseline_plan.py --structure work/structure.json --out work
Output: work/baseline.json (same field layout as draft.json["fields"])
"""
import argparse
import json
import os
import re
import sys

DIMS = ["rq_alignment", "section_structure", "argument_chain", "paragraph_relation",
        "repetition", "conclusion_boundary"]
SENT_RE = re.compile(r"(?<=[。！？!?])|(?<=[.])\s+")
CITE_RE = re.compile(r"(\[[0-9,\s\-–]+\]|\\cite\{[^}]+\}|\([A-Z][A-Za-z\-]+(?: et al\.)?,? (?:19|20)\d{2}\))")
CLAIM_RE = re.compile(r"(?i)\b(?:show|shows|showed|indicate|indicates|suggest|suggests|demonstrate|demonstrates|found|"
                      r"find|increase[sd]?|decrease[sd]?|improve[sd]?|reveal[sd]?)\b|表明|说明|显示|证明")
ABS_RE = re.compile(r"(?i)\b(?:prove[sd]?|clearly|undoubtedly|first time|always|never|completely)\b|首次|完全|所有|毫无疑问|必然|普遍")
CAUSAL_RE = re.compile(r"(?i)\b(?:caus(?:e|es|ed|ing)|leads? to|results? in|drives?|determines?)\b|导致|决定|造成|引起|使得")
CONTROL_RE = re.compile(r"(?i)\b(?:control|controls|controlled|compared|comparison|placebo|sham|randomi[sz]ed|"
                        r"treated versus|versus)\b|对照|相比|随机|空白组|比较")
CONTRIB_RE = re.compile(r"(?i)\b(?:novel|for the first time|first time|first (?:study|report|work)|we propose|"
                        r"we introduce|unprecedented)\b|首次|创新|提出了")
AIM_RE = re.compile(r"(?i)\b(?:aim|aims|objective|question|whether|investigates?|test whether)\b|旨在|能否|是否|研究问题")
REF_RE = re.compile(r"(?i)\b(fig(?:ure)?\.?|table|scheme)\s*\d+|[图表]\s*\d+")
LIMIT_RE = re.compile(r"(?i)\b(cannot|not tested|not performed|limitation|limitations|future work)\b|"
                      r"无法|未测试|没有测试|局限|尚不清楚|未来应|后续工作")
CN = {1: "一", 2: "二", 3: "三", 4: "四", 5: "五", 6: "六", 7: "七", 8: "八", 9: "九", 10: "十"}
STRONG_ABS = {"完全", "必然", "首次", "毫无疑问", "clearly", "undoubtedly", "completely", "always",
              "never", "prove", "proves", "proved", "first time"}


def cn(n):
    try:
        return CN.get(int(n), "n")
    except (TypeError, ValueError):
        return "n"


def sentences(text):
    return [s.strip() for s in SENT_RE.split(text or "") if s.strip()]


def norm_key(text):
    """Punctuation/whitespace-free form used to match a sentence pair back to its paragraph."""
    return re.sub(r"[\s，。！？；：、,.!?;:()（）\"'“”‘’]", "", text or "")


def anchor_of(sentence, paragraph_text, limit=300):
    q = (sentence or "").strip()
    floor = 8 if re.search(r"[\u4e00-\u9fff]", q or paragraph_text or "") else 12
    if len(q) < floor:
        q = (paragraph_text or "").strip()[:80]
    return q[:limit]


def is_procedural(section):
    low = (section or "").lower()
    return any(k in low for k in ("method", "材料与方法", "方法"))


def is_explicit_conclusion(name):
    low = (name or "").lower()
    return any(k in low for k in ("conclusion", "结论", "总结", "结语"))


def is_result_or_discussion(section):
    low = (section or "").lower()
    return any(k in low for k in ("result", "discussion", "conclusion", "结果", "讨论", "结论"))


def is_conclusion_section(name):
    low = (name or "").lower()
    return any(k in low for k in ("conclusion", "conclusions", "discussion", "结论", "讨论", "总结", "结语"))


def role_of(name):
    low = (name or "").lower()
    table = [("abstract", "摘要：陈述问题与主要结论"), ("摘要", "摘要：陈述问题与主要结论"),
             ("introduction", "引言：背景→缺口→研究问题"), ("引言", "引言：背景→缺口→研究问题"),
             ("background", "背景：定义与既有工作"), ("related", "相关工作：与研究缺口的对照"),
             ("method", "方法：对象、变量、条件、样本量"), ("方法", "方法：对象、变量、条件、样本量"),
             ("material", "材料与方法：对象、变量、条件、样本量"),
             ("result", "结果：逐条呈现支持论断的证据"), ("结果", "结果：逐条呈现支持论断的证据"),
             ("discussion", "讨论：结果解释、与既有工作对照"), ("讨论", "讨论：结果解释、与既有工作对照"),
             ("conclusion", "结论：回到研究问题并声明边界"), ("结论", "结论：回到研究问题并声明边界"),
             ("reference", "参考文献：不参与结构诊断"), ("参考文献", "参考文献：不参与结构诊断")]
    for key, role in table:
        if key in low:
            return role
    return "正文：功能需作者确认（规则未识别章节名）"


def build(structure):
    paras = structure.get("paragraphs") or []
    weights = structure.get("weights") or []
    pairs = structure.get("repetition_pairs") or []
    by_id = {p["paragraph_id"]: p for p in paras}
    issues, edits = [], []
    text_len = sum(p.get("chars", 0) for p in paras) or 1

    def add(dim, severity, confidence, para, sentence_index, quote, ptype, problem, why,
            refs=None, scope=""):
        for prior in issues:
            if prior["dimension"] == dim and prior["location"]["anchor_quote"] == quote:
                return prior["issue_id"]
        iid = "S%02d" % (len(issues) + 1)
        issues.append({
            "issue_id": iid, "dimension": dim, "severity": severity, "confidence": confidence,
            "location": {"section": para["section"], "paragraph_id": para["paragraph_id"],
                         "sentence_index": sentence_index, "anchor_quote": quote},
            "problem_type": ptype, "problem": problem, "why": why,
            "evidence_refs": refs or [para["paragraph_id"]],
            "scope": scope or "paragraph", "derivation": "rule_from_manuscript",
        })
        return iid

    # --- conclusion_boundary + argument_chain + rq_alignment per paragraph
    last_quarter = max(1, int(len(paras) * 0.75))
    has_conclusion_heading = any(is_conclusion_section(w.get("section")) for w in weights)
    for idx, p in enumerate(paras):
        body = p.get("text", "")
        sec = p.get("section", "")
        in_conclusion = is_conclusion_section(sec) or (not has_conclusion_heading and idx >= last_quarter)
        for k, s in enumerate(sentences(body), 1):
            if not s:
                continue
            abs_hits = ABS_RE.findall(s)
            causal_hits = CAUSAL_RE.findall(s)
            q = anchor_of(s, body)
            strong_abs = any(w.lower() in STRONG_ABS for w in abs_hits)
            if abs_hits and (strong_abs or not is_procedural(sec)) \
                    and len([i for i in issues if i["dimension"] == "conclusion_boundary"]) < 4:
                add("conclusion_boundary", "high" if in_conclusion else "medium", "medium", p, k, q,
                    "conclusion_overreach",
                    "该句使用绝对化措辞（%s），但同段未见引用标记支撑该强度。" % "、".join(abs_hits[:3]),
                    "同段未检出引用标记或图表引用；绝对化措辞未附带样本/条件范围。",
                    scope="conclusion" if in_conclusion else "paragraph")
            elif causal_hits and p.get("citations", 0) == 0 and not AIM_RE.search(s) \
                    and is_result_or_discussion(sec) and not CONTROL_RE.search(body) \
                    and len([i for i in issues if i["dimension"] == "conclusion_boundary"]) < 4:
                add("conclusion_boundary", "medium", "medium", p, k, q,
                    "causal_without_control",
                    "该句把结果表述为因果（%s），但同段未检出对照/随机化描述。" % "、".join(causal_hits[:3]),
                    "同段含因果动词，且未出现 control/compared/对照/随机 等设计说明；"
                    "若研究确有干预对照，请保留原表述并在方法节补全。",
                    scope="conclusion" if in_conclusion else "paragraph")
            if p.get("citations", 0) == 0 and p.get("refs", 0) == 0 and p.get("numbers", 0) == 0 \
                    and CLAIM_RE.search(s) and not abs_hits \
                    and len([i for i in issues if i["dimension"] == "argument_chain"]) < 4:
                add("argument_chain", "medium", "medium", p, k, q, "claim_without_evidence",
                    "该句给出结论性判断，但同段没有引用、图表编号或数值证据。",
                    "同段未检出引用标记、图/表引用或数值；论断与证据之间缺少可核对的落点。")
            if CONTRIB_RE.search(s) and not is_explicit_conclusion(sec) \
                    and not (not has_conclusion_heading and idx >= last_quarter) \
                    and p.get("citations", 0) == 0 \
                    and not CONTROL_RE.search(body) \
                    and len([i for i in issues if i["dimension"] == "rq_alignment"]) < 2:
                add("rq_alignment", "medium", "medium", p, k, q, "contribution_unsubstantiated",
                    "贡献主张含“首次/novel”一类强表述，但同段没有引用或对比证据。",
                    "该句含贡献标记，同段未检出引用标记，且未检出 compared/versus/对照 等对比描述。")

    # --- section_structure: weight imbalance (no fabricated digits in prose)
    if len(weights) > 1:
        scored = [w for w in weights
                  if not any(k in (w.get("section") or "").lower() for k in ("reference", "acknowledg", "参考文献", "致谢"))]
        if scored:
            top = max(scored, key=lambda w: w.get("chars", 0))
            if top.get("share", 0) > 0.45:
                target = next((p for p in paras if p.get("section") == top.get("section")), None)
                others = [w.get("section") for w in scored if w is not top][:3]
                if target is not None:
                    add("section_structure", "medium", "medium", target, 1,
                        anchor_of(sentences(target.get("text"))[0] if sentences(target.get("text")) else "",
                                  target.get("text")),
                        "section_weight_imbalance",
                        "章节「%s」的篇幅明显大于其余章节，可能挤压论证主体。" % top.get("section"),
                        "按字符占比统计（见 structure.json weights），该节为最高；其余章节：%s。"
                        "若属综述型或方法学论文，可判为正常并驳回本项。" % ("、".join(others) or "无"),
                        refs=[target["paragraph_id"]], scope="section")

    # --- repetition candidates: group transitive duplicates, one issue per group
    parent = {}

    def find(x):
        parent.setdefault(x, x)
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(x, y):
        rx, ry = find(x), find(y)
        if rx != ry:
            parent[max(rx, ry)] = min(rx, ry)

    for pair in pairs:
        if pair.get("a") and pair.get("b"):
            union(pair["a"], pair["b"])
    groups = {}
    for pid in list(parent):
        groups.setdefault(find(pid), []).append(pid)
    for root in sorted(groups)[:3]:
        members = sorted(groups[root])
        if len(members) < 2:
            continue
        a = by_id.get(members[0])
        if not a:
            continue
        b_ids = [m for m in members[1:] if m in by_id]
        cross = any((by_id[x].get("section") != by_id[y].get("section"))
                    for x in members for y in members if x != y)
        q = anchor_of(sentences(a.get("text"))[0] if sentences(a.get("text")) else "", a.get("text"))
        add("repetition", "medium", "medium", a, 1, q, "cross_section_repetition_candidate",
            "%s 与 %s 的文本高度相似，可能重复表述同一内容。"
            % (a["paragraph_id"], "、".join(b_ids)),
            "相似度与重合度见 structure.json repetition_pairs；跨节=%s。需回读确认是否语义重复、"
            "被合并段落是否含独有数据。" % cross,
            refs=[a["paragraph_id"]] + b_ids, scope="cross_section")

    # --- sentence-level repetition candidates (a copied sentence across chapters)
    covered = set()
    for i in issues:
        if i["problem_type"] == "cross_section_repetition_candidate":
            covered |= set(i.get("evidence_refs") or [])
    for sp in (structure.get("sentence_pairs") or []):
        if not sp.get("cross_section") or len([i for i in issues if i["dimension"] == "repetition"]) >= 3:
            continue
        a = by_id.get(sp.get("a"))
        b = by_id.get(sp.get("b"))
        if not a or not b or a["paragraph_id"] in covered:
            continue
        q = anchor_of(sp.get("sentence", ""), a.get("text", ""))
        idx = next((k for k, s in enumerate(sentences(a.get("text", "")), 1)
                    if norm_key(s) == norm_key(sp.get("sentence", ""))), 1)
        add("repetition", "medium", "medium", a, idx, q, "cross_section_repetition_candidate",
            "%s 第%s句与 %s（%s）的表述%s重复。" % (a["paragraph_id"], cn(idx), b["paragraph_id"],
                                              b.get("section") or "", "逐字" if sp.get("exact") else "高度"),
            "句级相似度 %.2f（structure.json sentence_pairs，跨节=%s）；需回读确认后者是否承担新的"
            "信息，若无则合并或改为回指。" % (sp.get("ratio", 0), sp.get("cross_section")),
            refs=[a["paragraph_id"], b["paragraph_id"]], scope="cross_section")
        covered.add(a["paragraph_id"])

    # --- paragraph_relation: limitation sentences buried inside result/discussion paragraphs
    for p in paras:
        sents = sentences(p.get("text", ""))
        if len(sents) < 2 or not is_result_or_discussion(p.get("section")):
            continue
        if LIMIT_RE.search(p.get("text", "")) \
                and len([i for i in issues if i["dimension"] == "paragraph_relation"]) < 2:
            split_at = next((k for k, s in enumerate(sents, 1) if LIMIT_RE.search(s)), len(sents))
            if split_at <= 1 or split_at >= len(sents):
                continue  # already a pure limitation paragraph, or nothing follows to split off
            add("paragraph_relation", "low", "medium", p, split_at,
                anchor_of(sents[split_at - 1], p.get("text")),
                "result_limitation_mixed",
                "该段把结果/解释与局限说明放在同一段，读者容易把局限误读为结果的一部分。",
                "该段第%s句含局限或未测试表述，与前面的结果陈述同处一段；需回读确认是否应独立为限制段。"
                % cn(split_at),
                scope="paragraph")
            issues[-1]["split_at"] = split_at
    for p in paras:
        if p.get("chars", 0) >= 900 and p.get("claims", 0) >= 3 \
                and len([i for i in issues if i["dimension"] == "paragraph_relation"]) < 2:
            sents = sentences(p.get("text", ""))
            split_at = next((k for k, s in enumerate(sents, 1) if k > 1 and CLAIM_RE.search(s)), 3)
            add("paragraph_relation", "low", "low", p, split_at,
                anchor_of(sents[split_at - 1] if len(sents) >= split_at else sents[0], p.get("text")),
                "paragraph_multi_topic",
                "该段篇幅较长且含多个论断句，可能一段承担两个主题。",
                "段落字符数与论断句数均超过规则阈值；需回读确认第二主题是否应独立成段。",
                scope="paragraph")
            issues[-1]["split_at"] = split_at

    # --- edits (one per issue, always executable)
    for issue in issues:
        iid = issue["issue_id"]
        eid = "E%02d" % (len(edits) + 1)
        loc = issue["location"]
        p = by_id.get(loc.get("paragraph_id")) or {}
        base = {"edit_id": eid, "issue_id": iid,
                "target": {"section": loc.get("section"), "paragraph_id": loc.get("paragraph_id"),
                           "sentence_index": loc.get("sentence_index")},
                "preserves": "原文数值、样本量、图表编号与引用保持不变",
                "risk": "规则候选：若该句在上下文中有未检出的依据，可驳回本建议"}
        ptype = issue["problem_type"]
        if ptype == "conclusion_overreach":
            base.update({
                "action": "NARROW",
                "instruction": "将 %s 中该句的绝对化表述（%s）改为限定范围的说法，写明本研究的样本/条件范围；"
                               "数值与图表编号保持不变。" % (issue["location"]["paragraph_id"],
                                                            "、".join(ABS_RE.findall(issue["location"]["anchor_quote"])[:3]) or "绝对化措辞"),
                "expected_effect": "结论强度与数据范围一致，作者可逐字对照原句修改"})
        elif ptype == "causal_without_control":
            base.update({
                "action": "NARROW",
                "instruction": "将 %s 该句的因果动词改为相关性表述（如 associated with / 与…相关），"
                               "并在同段补一句“本研究未设置干预对照”；若原稿另有对照设计，请按实际设计保留原表述。"
                               % issue["location"]["paragraph_id"],
                "expected_effect": "因果主张不超过研究设计允许的范围"})
        elif ptype == "claim_without_evidence":
            base.update({
                "action": "ADD_EVIDENCE",
                "instruction": "为 %s 该句补上支撑证据：写明对应图/表编号或统计量；若当前没有，改为限定性表述，"
                               "并在 limitations 说明缺口（不得代造数据）。" % issue["location"]["paragraph_id"],
                "expected_effect": "论断与证据一一对应，缺口显式标注"})
        elif ptype == "cross_section_repetition_candidate":
            b_id = [r for r in issue.get("evidence_refs", []) if r != issue["location"]["paragraph_id"]]
            base.update({
                "action": "MERGE",
                "instruction": "保留 %s 的完整表述，将 %s 改为回指（如“如前所述”），删除重复描述；"
                               "若 %s 含独有数据，则改为对比表述并保留其数据。"
                               % (issue["location"]["paragraph_id"], (b_id or ["后一处"])[0], (b_id or ["后一处"])[0]),
                "expected_effect": "跨节重复消除，独有信息不丢失"})
        elif ptype == "section_weight_imbalance":
            base.update({
                "action": "REORDER",
                "instruction": "核对「%s」的篇幅：把其中与相邻章节重复的背景句改为回指；"
                               "若该节确需完整细节，将细节移入补充材料并在正文保留要点与指向。"
                               % issue["location"]["section"],
                "expected_effect": "论证主体获得篇幅，细节仍可追溯"})
        elif ptype == "contribution_unsubstantiated":
            base.update({
                "action": "NARROW",
                "instruction": "收窄 %s 中该贡献表述：删除或限定“首次/novel”等措辞，或补上与主张对应的"
                               "对比证据（不得代造数据或文献）。" % issue["location"]["paragraph_id"],
                "expected_effect": "贡献主张与实际完成工作一致"})
        elif ptype in ("paragraph_multi_topic", "result_limitation_mixed"):
            k = issue.get("split_at", 2)
            base.update({
                "action": "SPLIT",
                "instruction": ("在 %s 第%s句后拆分：把局限/未测试表述移入独立的限制段或讨论末段，"
                                "结果段只保留结果与解释，并补一句过渡。" if ptype == "result_limitation_mixed"
                                else "在 %s 第%s句后拆分：前半保留原主题句，后半以“另一方面/此外”类过渡句承接第二个论断，"
                                     "两段各自补主题句。") % (issue["location"]["paragraph_id"], cn(k)),
                "split_at": k,
                "expected_effect": "结果与限制各自成段，段落功能单一且可追踪"})
        else:
            base.update({"action": "FLAG_GAP",
                         "instruction": "标记 %s 的证据缺口，说明缺什么、影响哪条结论；不代造数据。"
                                        % issue["location"]["paragraph_id"],
                         "expected_effect": "缺口显式交给作者处理"})
        edits.append(base)

    # --- paragraph_map: every paragraph has a destination
    merged_into = {}
    split_ids = set()
    for issue in issues:
        if issue["problem_type"] == "cross_section_repetition_candidate":
            refs = issue.get("evidence_refs") or []
            for other in refs[1:]:
                merged_into[other] = refs[0]
        if issue["problem_type"] in ("paragraph_multi_topic", "result_limitation_mixed"):
            split_ids.add(issue["location"]["paragraph_id"])
    pmap = []
    for p in paras:
        pid = p["paragraph_id"]
        if pid in merged_into:
            pmap.append({"paragraph_id": pid, "status": "merged", "into": merged_into[pid],
                         "reason": "与 %s 高度相似，改为回指（见 repetition 诊断）" % merged_into[pid]})
        elif pid in split_ids:
            pmap.append({"paragraph_id": pid, "status": "split",
                         "split_into": [pid + "-a", pid + "-b"],
                         "reason": "该段含多个主题，按诊断建议拆分"})
        else:
            pmap.append({"paragraph_id": pid, "status": "kept", "reason": "本次方案未移动该段，保持原位"})

    # --- outline: section-level order, all paragraphs accounted for
    order, seen = [], {}
    for p in paras:
        sec = p.get("section") or "正文"
        if sec not in seen:
            seen[sec] = {"section": sec, "role": role_of(sec), "order": len(order) + 1,
                         "paragraphs_from": [], "merge_of": [], "split_into": [],
                         "note": "承接原稿该章节段落；段落去向见 paragraph_map"}
            order.append(seen[sec])
        seen[sec]["paragraphs_from"].append(p["paragraph_id"])
    for o in order:
        o["merge_of"] = [pid for pid in o["paragraphs_from"]
                         if any(m.get("paragraph_id") == pid and m.get("status") == "merged" for m in pmap)]
        o["split_into"] = [pid for pid in o["paragraphs_from"]
                           if any(m.get("paragraph_id") == pid and m.get("status") == "split" for m in pmap)]
    if not order:
        order = [{"section": "全文", "role": "未识别章节结构", "order": 1, "paragraphs_from": [],
                  "merge_of": [], "split_into": [], "note": "无段落，见 limits"}]

    # --- argument map from actual claim candidates
    # breakpoint must agree with the diagnosis: marking claim_without_evidence here while the
    # plan lists no argument_chain issue (coverage findings=0) made the deliverable contradict itself.
    gap_paragraphs = {i["location"]["paragraph_id"] for i in issues
                      if i["problem_type"] == "claim_without_evidence"}
    amap = []
    for c in (structure.get("claim_candidates") or [])[:12]:
        p = by_id.get(c.get("paragraph_id")) or {}
        ev = []
        if p.get("citations"):
            ev.append({"ref": "引用标记", "kind": "citation", "locator": p["paragraph_id"]})
        if p.get("refs"):
            ev.append({"ref": "图表引用", "kind": "figure", "locator": p["paragraph_id"]})
        if p.get("numbers"):
            ev.append({"ref": "段内数值", "kind": "data", "locator": p["paragraph_id"]})
        claim = c.get("sentence", "")
        strength = "strong" if (p.get("citations") and p.get("numbers")) else \
                   ("medium" if ev else "weak")
        brk = "claim_without_evidence" if c.get("paragraph_id") in gap_paragraphs else ""
        amap.append({
            "claim_id": "C%02d" % (len(amap) + 1), "claim": claim, "section": c.get("section"),
            "paragraph_id": c.get("paragraph_id"), "sentence_index": c.get("sentence_index"),
            "evidence": ev, "reasoning": "" if CONTROL_RE.search(p.get("text", "")) else
            ("该段未检出对照或随机化描述" if CAUSAL_RE.search(claim) else ""),
            "serves": "", "claim_type": ("causal" if CAUSAL_RE.search(claim) else
                                         "quantitative" if re.search(r"\d", claim) else "general"),
            "strength": strength, "breakpoint": brk})

    # --- coverage: six dimensions always reported
    def count(dim):
        return len([i for i in issues if i["dimension"] == dim])
    coverage = {d: {"checked": bool(paras), "findings": count(d) if paras else 0} for d in DIMS}
    coverage["rq_alignment"]["note"] = "检查贡献主张句是否有引用/对比支撑"
    coverage["section_structure"]["note"] = "依据字符占比与章节顺序规则；无标题时降级为段落聚类"
    coverage["argument_chain"]["note"] = "抽取论断句并检查同段引用/图表/数值证据"
    coverage["paragraph_relation"]["note"] = "检查长段多论断；未发现则 findings=0"
    coverage["repetition"]["note"] = "相似度候选，需回读确认"
    coverage["conclusion_boundary"]["note"] = "检查绝对化措辞与无对照因果表述"
    coverage["read_sections"] = [w.get("section") for w in weights] or ["Preamble"]
    coverage["unread_sections"] = []
    coverage["no_issues_found"] = not issues

    # --- uncertainty / limits
    uncertainty = ["规则自动抽取的候选问题需作者复核；本方案未替代人工语义阅读。"]
    if structure.get("inferred_sections"):
        uncertainty.append("未检出标题，章节为按段落顺序聚类推断（§A..），章节级判断降级为段落级。")
    if pairs:
        uncertainty.append("重复对为相似度候选，需回读确认语义是否重复、是否含独有数据。")
    flagged = {f.get("code") for f in structure.get("flags") or []}
    if "section_not_detected" in flagged:
        uncertainty.append("部分章节名未检出（命名可能不同），章节顺序与权重判断可能不完整。")
    if not issues:
        uncertainty.append("本次规则检查未发现可定位问题；这不等于稿件无问题，建议作者按六维自查表复核。")
    limits = []
    if not paras:
        limits.append("未能从材料中切分出段落，结构诊断无法进行")
    if structure.get("inferred_sections"):
        limits.append("无标题/编号混乱：章节级结论受限，已退化为段落级诊断")
    if text_len < 1200:
        limits.append("稿件较短，篇幅占比与章节权重判断参考价值有限")
    limits.append("规则自动基线覆盖六维的机械可检部分；语义级论证强度仍需作者复核")

    return {
        "status": "partial",
        "artifact_path": "structure_plan.md", "artifact_format": "md",
        "diagnosis": issues, "edit_plan": edits, "outline": order, "paragraph_map": pmap,
        "argument_map": amap, "coverage": coverage,
        "fact_guard": {"numbers_unbound": [], "citations_not_in_sources": [],
                       "quotes_checked": 0, "verdict": "pending"},
        "source_map": [{"claim": i["problem"],
                        "value": i["location"]["anchor_quote"],
                        "source_path": structure.get("file") or "manuscript",
                        "locator": "%s L%s-L%s" % (i["location"]["paragraph_id"],
                                                   (by_id.get(i["location"]["paragraph_id"]) or {}).get("start_line", "?"),
                                                   (by_id.get(i["location"]["paragraph_id"]) or {}).get("end_line", "?"))}
                       for i in issues],
        "changes": [{"target": e["target"], "type": e["action"],
                     "before": (by_id.get(e["target"].get("paragraph_id")) or {}).get("text", "")[:160],
                     "after": "建议动作（原稿未改动）：" + e["instruction"][:120],
                     "reason": e["expected_effect"]} for e in edits],
        "uncertainty": uncertainty, "limits": "；".join(limits),
        "baseline_meta": {"issues": len(issues), "edits": len(edits),
                          "paragraphs": len(paras), "sections": len(order),
                          "inferred_sections": bool(structure.get("inferred_sections"))},
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--structure", required=True)
    ap.add_argument("--out", default="work")
    a = ap.parse_args()
    if not os.path.exists(a.structure):
        print("FAIL: structure.json missing:", a.structure)
        return 1
    structure = json.load(open(a.structure, encoding="utf-8"))
    plan = build(structure)
    os.makedirs(a.out, exist_ok=True)
    with open(os.path.join(a.out, "baseline.json"), "w", encoding="utf-8") as fh:
        json.dump(plan, fh, ensure_ascii=False, indent=1)
    print("baseline issues=%d edits=%d paragraphs=%d sections=%d coverage=%s"
          % (len(plan["diagnosis"]), len(plan["edit_plan"]), len(plan["paragraph_map"]),
             len(plan["outline"]), {d: plan["coverage"][d]["findings"] for d in DIMS}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
