#!/usr/bin/env python3
"""report_audit.py - 把综述正文与证据表/分级/检索记录做交叉核对。

  python scripts/report_audit.py --report work/report.md --rank work/evidence_rank.json \
      --search-log work/search_log.json --evidence work/evidence.json \
      --out work/report_audit.json [--strict]

检查项：
  1. 八段固定结构是否齐全（研究问题/拆解/证据矩阵/综合结论/冲突与反证/研究空白/待验证/限制）
  2. 「综合结论」段落里每个断言句是否带 [E..] 锚点，锚点是否都在证据表里
  3. stance=refute 的证据是否真的出现在「冲突与反证」段
  4. not_covered 的子问题是否在「研究空白」段落逐条出现，并给检索依据
  5. 材料总数措辞（共 N 篇/份）是否等于 index 的 files_readable
  6. 过度断言措辞（普遍认为/一致表明/已证实）是否有 ≥2 个独立来源 A/B 证据支撑
  7. 禁止措辞（领域空白/尚无研究）是否出现

仅标准库；--strict 时有 error 返回 1。
"""
import argparse
import json
import os
import re
import sys

# 顺序即优先级：tree 的「子问题」是通用词，必须放在最后，
# 否则 SKILL.md 自带的「3. 证据矩阵（按子问题列证据…）」标题会被误判成拆解段。
SECTIONS = [
    ("scope", r"研究问题|问题与范围|research question|scope"),
    ("matrix", r"证据矩阵|evidence matrix|证据表"),
    ("conclusion", r"综合结论|结论|synthesis|findings"),
    ("conflict", r"冲突|反证|conflict|counter"),
    ("gap", r"研究空白|空白|gaps?|research gaps"),
    ("todo", r"待验证|verification|future work|to verify"),
    ("limits", r"限制|局限|limitations?|uncertaint"),
    ("tree", r"拆解|子问题|decomposition|breakdown"),
]
HEAD = re.compile(r"^(#{1,6})\s*(.+)$", re.M)
TAG = re.compile(r"\[(E\d+[a-z]?)(?:\s*,\s*(E\d+[a-z]?))*\]|\[((?:E\d+[a-z]?)(?:\s*,\s*E\d+[a-z]?)+)\]")
ANY_TAG = re.compile(r"E\d+[a-z]?")
SENT = re.compile(r"[^。！？!?\n]+[。！？!?]?")
OVERCLAIM = r"普遍认为|一致表明|广泛共识|已证实|conclusive|universally"
FORBIDDEN = r"领域空白|尚无研究|no research exists|virtually no studies"
COUNT = re.compile(r"共\s*(\d+)\s*(?:篇|份|项)?\s*(?:材料|文献|来源|sources?|papers?)")
STRONG_OK = {"A", "B"}


def load(path, default=None):
    if path and os.path.exists(path):
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    return default


def split_sections(text):
    marks = [(m.start(), len(m.group(1)), m.group(2).strip()) for m in HEAD.finditer(text)]
    out = []
    for i, (pos, lvl, name) in enumerate(marks):
        end = marks[i + 1][0] if i + 1 < len(marks) else len(text)
        out.append((lvl, name, text[pos:end]))
    return out


def classify(name):
    # 先只看标题主干（去掉「（…）」里的说明与冒号后缀），避免模板括号里的
    # 「子问题」「结论」等字样把段落抢走；主干不命中再回退整行匹配。
    for candidate in (re.split(r"[（(：:]", name)[0], name):
        hits = [key for key, pat in SECTIONS if re.search(pat, candidate, re.I)]
        if hits:
            return hits[0]
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--report", required=True)
    ap.add_argument("--rank", default="work/evidence_rank.json")
    ap.add_argument("--search-log", default="work/search_log.json")
    ap.add_argument("--evidence", default="work/evidence.json")
    ap.add_argument("--out", default="work/report_audit.json")
    ap.add_argument("--strict", action="store_true")
    a = ap.parse_args()

    errors, warnings = [], []
    if not os.path.exists(a.report):
        print("FAIL\n - report missing: %s" % a.report)
        return 1
    for label, path, required in (("evidence_rank", a.rank, True),
                                  ("search_log", a.search_log, True),
                                  ("evidence index", a.evidence, True)):
        if not os.path.exists(path):
            (errors if required else warnings).append("%s missing: %s" % (label, path))
    text = open(a.report, encoding="utf-8").read()
    # 标题行可能带模板占位（如「综合结论（…+ [E01,E07]）」），不参与锚点与措辞扫描。
    body_text = "\n".join(l for l in text.splitlines() if not HEAD.match(l))
    rank = load(a.rank, {}) or {}
    search_log = load(a.search_log, []) or []
    if isinstance(search_log, dict):
        search_log = search_log.get("entries") or search_log.get("log") or []
    inventory = load(a.evidence, {}) or {}
    files_readable = inventory.get("files_readable")
    if files_readable is None and isinstance(inventory.get("files"), list):
        files_readable = sum(1 for f in inventory["files"] if f.get("readable"))

    blocks = split_sections(text)
    # 报告常用 # 标题 + ## 八段 + ### 子标题。把「命中段名最多」的层级定为段级，
    # 更深层一律视为段内小标题并入当前段，避免「### 5.1 冲突分析」把正文从第 5 段截走。
    level_hits = {}
    for lvl, name, _ in blocks:
        if classify(name):
            level_hits[lvl] = level_hits.get(lvl, 0) + 1
    section_level = max(level_hits.items(), key=lambda kv: (kv[1], kv[0]))[0] if level_hits else None
    found = {}
    prev = None
    for lvl, name, body in blocks:
        role = classify(name) if lvl == section_level else None
        if role:
            found[role] = found.get(role, "") + body
            prev = role
        elif prev:
            found[prev] += body
    for role, _ in SECTIONS:
        if role not in found:
            errors.append("missing section: %s" % role)

    known = {str(r.get("id")) for r in (rank.get("ranked") or []) if r.get("id")}
    if not known:
        warnings.append("evidence_rank has no ranked evidence: tag checks are limited")

    # 2) conclusion sentences must carry resolvable [E..] tags
    conclusion = found.get("conclusion", "")
    for sent in SENT.findall(conclusion):
        s = sent.strip()
        if len(s) < 24 or re.match(r"^[#|>\s]", s):
            continue
        if not TAG.search(s) and re.search(r"[。！？.!?]$", s):
            errors.append("conclusion sentence without [E..] anchor: %.60s" % s)
    for tag in ANY_TAG.findall(body_text):
        if known and tag not in known:
            errors.append("unknown evidence id in report: %s" % tag)

    # 3) refuting evidence must appear in the conflict section
    refute_ids = {str(r.get("id")) for r in (rank.get("ranked") or [])
                  if str(r.get("stance")) == "refute" and r.get("id")}
    conflict_body = found.get("conflict", "")
    for eid in sorted(refute_ids - set(ANY_TAG.findall(conflict_body))):
        errors.append("refuting evidence %s missing from conflict/counter section" % eid)
    # 有冲突的子问题，冲突段至少要出现该子问题的一条证据（stance=refute 或 mixed）。
    conflict_tags = set(ANY_TAG.findall(conflict_body))
    ids_by_subq = {}
    for r in (rank.get("ranked") or []):
        if r.get("id") and r.get("subq") is not None:
            ids_by_subq.setdefault(str(r.get("subq")), set()).add(str(r.get("id")))
    for c in (rank.get("conflicts") or []):
        sq = str(c.get("subq"))
        if not (ids_by_subq.get(sq, set()) & conflict_tags):
            errors.append("conflict subquestion %s has no evidence in conflict/counter section" % sq)

    # 4) every not_covered subquestion must be reported as a gap, with a search basis
    gap_body = found.get("gap", "")
    gap_ids = list(rank.get("gaps") or [])
    empty_queries = [e for e in search_log if isinstance(e, dict) and e.get("empty")]
    empty_subqs = {str(e.get("subq")) for e in empty_queries if e.get("subq")}
    for qid in gap_ids:
        if str(qid) not in gap_body:
            errors.append("subquestion %s is not_covered but not reported in gap section" % qid)
        elif str(qid) not in empty_subqs and not re.search(r"零命中|0 命中|未命中|no hit|empty", gap_body, re.I):
            warnings.append("gap %s has no zero-hit query recorded as evidence" % qid)
    if re.search(FORBIDDEN, body_text):
        errors.append("forbidden phrasing (领域空白/尚无研究) in report")

    # 5) material count wording must match the index
    if files_readable is not None:
        for n in COUNT.findall(text):
            if int(n) != int(files_readable):
                errors.append("材料数量措辞 %s 与 index 的 files_readable=%s 不一致" % (n, files_readable))

    # 6) overclaim wording needs 2+ independent A/B sources behind its anchors
    ranked = rank.get("ranked") or []
    by_id = {str(r.get("id")): r for r in ranked if r.get("id")}
    for sent in SENT.findall(body_text):
        if not re.search(OVERCLAIM, sent, re.I):
            continue
        tags = [t for t in ANY_TAG.findall(sent) if t in by_id]
        # 综合结论常跨子问题取证：统计该句所引证据里不同 A/B 来源的个数，
        # 而不是要求同一子问题内堆满两个来源（否则合法的跨题综合会被误拦）。
        ab_sources = {str(by_id[t].get("source_path")) for t in tags
                      if str(by_id[t].get("grade")) in STRONG_OK and by_id[t].get("source_path")}
        if len(ab_sources) < 2:
            errors.append("overclaim without 2+ independent A/B sources: %.60s" % sent.strip())

    verdict = "fail" if errors else ("review" if warnings else "pass")
    payload = {"verdict": verdict, "sections_found": sorted(found), "errors": errors,
               "warnings": warnings, "known_evidence": len(known), "files_readable": files_readable,
               "gap_ids": gap_ids, "refute_ids": sorted(refute_ids)}
    os.makedirs(os.path.dirname(os.path.abspath(a.out)) or ".", exist_ok=True)
    with open(a.out, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=1)
    print("verdict=%s sections=%d/8 evidence=%d errors=%d warnings=%d"
          % (verdict, len(found), len(known), len(errors), len(warnings)))
    for e in errors:
        print("  !", e)
    for w in warnings[:8]:
        print("  ~", w)
    return 1 if (errors and a.strict) else 0


if __name__ == "__main__":
    sys.exit(main())
