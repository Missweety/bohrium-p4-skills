#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""qa_review.py - 文献问答赛道的语义复核器（独立进程）。

检查项（每项都能被第二个人独立抽查）：
    Q01 契约齐备：case_id / answers[] / coverage / status / sources / uncertainty / change_log
    Q02 逐题覆盖：case.json 里每个问题都在 answers[] 里出现，**不得省略无法回答的问题**
    Q03 状态合法：每题 status ∈ {answered, partial, insufficient_evidence, input_error}
    Q04 答案非空：status ∈ {answered, partial} 时 answer 必须有实质文本
    Q05 论断结构：每个 claim 有 claim_id / text / kind ∈ {reported, inferred} / evidence[]
    Q06 证据可定位：evidence.paragraph_id 存在于材料段落清单
    Q07 引文逐字命中：evidence.quote 必须是该 paragraph 原文的**连续子串**
    Q08 未完成部分：status ≠ answered 时 unanswered_parts 非空且每项有原因
    Q09 阅读范围：coverage 说明已读章节
    Q10 引用不越界：claims 中的数值必须能在其 evidence 引文所在段落中找到
    Q11 未完成标记：候选残留 needs_review=true 的条目不得直接算作定论

退出码 0 = 通过；1 = 存在必须修复的问题。
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys

VALID_STATUS = ("answered", "partial", "insufficient_evidence", "input_error")
VALID_KIND = ("reported", "inferred")
NUM = re.compile(r"\d+(?:\.\d+)?\s*(?:%|percent\b|per\s*cent\b)?")
PCT_WORD = re.compile(r"(\d+(?:\.\d+)?)\s*(?:percent\b|per\s*cent\b)", re.I)


def numbers_of(text):
    """抽取数值并归一化：90% 与 90 percent 视为同一个数值。"""
    t = (text or "").lower()
    vals = set()
    for m in NUM.finditer(t):
        v = m.group(0).strip()
        if not v:
            continue
        v = PCT_WORD.sub(lambda mm: mm.group(1) + "%", v)
        v = v.replace(" ", "")
        if v.endswith("%"):
            v = v[:-1]
        try:
            vals.add(float(v))
        except ValueError:
            vals.add(v)
    return vals


def norm(text):
    return re.sub(r"\s+", " ", (text or "")).strip()


def load_json(path):
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:
        return None


def para_index(context):
    idx = {}
    for p in (context or {}).get("paragraphs", []) or []:
        pid = p.get("paragraph_id")
        if pid:
            idx[str(pid)] = p.get("text", "")
    return idx


def q_index(context):
    idx = {}
    for q in (context or {}).get("questions", []) or []:
        qid = q.get("question_id")
        if qid:
            idx[str(qid)] = q.get("question", "")
    return idx


def main(argv=None):
    ap = argparse.ArgumentParser(description="文献问答结果复核")
    ap.add_argument("--result", required=True)
    ap.add_argument("--context", default=None, help="qa_context.json")
    ap.add_argument("--out", default=None, help="复核报告输出路径")
    args = ap.parse_args(argv)

    result = load_json(args.result)
    context = load_json(args.context) if args.context else None
    errors, warnings, checks = [], [], []

    def chk(cid, ok, title, detail="", fix=""):
        checks.append({"code": cid, "title": title,
                       "pass": bool(ok), "detail": detail})
        if not ok:
            errors.append({"code": cid, "detail": detail, "fix": fix})

    def warn(cid, title, detail):
        checks.append({"code": cid, "title": title, "pass": True,
                       "detail": "WARN: " + detail})
        warnings.append({"code": cid, "detail": detail})

    if not isinstance(result, dict):
        print("错误：result 不是合法 JSON 对象", file=sys.stderr)
        return 1

    # Q01 契约齐备
    need = ["case_id", "paper_id", "material_version", "answers", "coverage",
            "status", "sources", "uncertainty", "change_log"]
    missing = [k for k in need if k not in result]
    empty = [k for k in need
             if k in result and k not in ("answers", "sources", "change_log")
             and not str(result.get(k) or "").strip()]
    chk("Q01", not missing and not empty,
        "契约字段齐备",
        ("缺失: %s" % ", ".join(missing) if missing else "")
        + ("；为空: %s" % ", ".join(empty) if empty else "")
        or "全部存在",
        "补齐 result.json 顶层字段：%s" % ", ".join(missing + empty))

    answers = result.get("answers")
    answers = answers if isinstance(answers, list) else []
    paras = para_index(context)
    questions = q_index(context)

    # Q02 逐题覆盖
    got = {str(a.get("question_id")) for a in answers if isinstance(a, dict)}
    if questions:
        lost = sorted(set(questions) - got)
        chk("Q02", not lost, "每个问题都有对应回答项",
            "漏答: %s" % ", ".join(lost) if lost else "覆盖 %d/%d 题"
            % (len(got & set(questions)), len(questions)),
            "无法回答的问题也要给出条目，status=insufficient_evidence 并写明原因")
    else:
        warn("Q02", "每个问题都有对应回答项", "未提供段落/问题清单，跳过覆盖核对")

    # 逐题检查
    for a in answers:
        if not isinstance(a, dict):
            continue
        qid = str(a.get("question_id", "?"))
        st = a.get("status")
        if st not in VALID_STATUS:
            chk("Q03", False, "回答状态合法",
                "question_id=%s status=%r 非法" % (qid, st),
                "status 只能是 %s" % "/".join(VALID_STATUS))
        answer = norm(a.get("answer"))
        if st in ("answered", "partial") and len(answer) < 5:
            chk("Q04", False, "答案有实质文本",
                "question_id=%s status=%s 但 answer 为空或过短" % (qid, st),
                "填上实际回答文本")
        claims = a.get("claims")
        claims = claims if isinstance(claims, list) else []
        if st == "answered" and not claims:
            chk("Q05", False, "论断带证据",
                "question_id=%s status=answered 但 claims 为空" % qid,
                "至少给出一条带 evidence 的论断")
        for c in claims:
            if not isinstance(c, dict):
                continue
            cid = c.get("claim_id")
            if not cid or not norm(c.get("text")):
                chk("Q05", False, "论断结构完整",
                    "question_id=%s 存在缺 claim_id 或 text 的 claim" % qid,
                    "每个 claim 需要 claim_id 与 text")
            if c.get("kind") not in VALID_KIND:
                chk("Q05", False, "论断类型合法",
                    "question_id=%s claim=%s kind=%r 非法" % (qid, cid, c.get("kind")),
                    "kind 只能是 reported / inferred")
            ev = c.get("evidence")
            ev = ev if isinstance(ev, list) else []
            if not ev:
                chk("Q06", False, "证据非空",
                    "question_id=%s claim=%s evidence 为空" % (qid, cid),
                    "每条论断至少给一条 evidence")
            for e in ev:
                if not isinstance(e, dict):
                    continue
                pid = str(e.get("paragraph_id", ""))
                quote = norm(e.get("quote"))
                if pid not in paras:
                    chk("Q06", False, "证据段落可定位",
                        "question_id=%s claim=%s paragraph_id=%s 不在材料段落清单中"
                        % (qid, cid, pid),
                        "paragraph_id 必须来自实际段落编号")
                    continue
                if not quote:
                    chk("Q07", False, "引文非空",
                        "question_id=%s claim=%s 引文为空" % (qid, cid),
                        "补上逐字短引文")
                    continue
                if quote not in norm(paras[pid]):
                    chk("Q07", False, "引文逐字命中锚点段落",
                        "question_id=%s claim=%s paragraph_id=%s 引文非该段原文子串"
                        % (qid, cid, pid),
                        "引文必须是该段落原文的连续子串，逐字复制")
                    continue
            # Q10 按论断聚合后判定
            if ev and c.get("kind") == "reported":
                para_nums = set()
                for e in ev:
                    if not isinstance(e, dict):
                        continue
                    pid = str(e.get("paragraph_id", ""))
                    if pid in paras:
                        para_nums |= numbers_of(norm(paras[pid]))
                claim_nums = numbers_of(norm(c.get("text")))
                missing_nums = claim_nums - para_nums
                if missing_nums:
                    chk("Q10", False, "论断数值可在证据段落中找到",
                        "question_id=%s claim=%s 数值 %s 不在其证据段落中"
                        % (qid, cid, ",".join(sorted(str(x) for x in missing_nums))),
                        "kind=reported 的论断里每个数值都必须在证据段落原文中出现；"
                        "否则改用原文表述、补上对应证据段落，"
                        "或把该论断改标 kind=inferred")

        # Q08 未完成部分
        if st != "answered":
            up = a.get("unanswered_parts")
            up = up if isinstance(up, list) else []
            bad = [u for u in up if not isinstance(u, dict) or not norm(u.get("reason"))]
            if not up:
                chk("Q08", False, "未完成部分有原因",
                    "question_id=%s status=%s 但 unanswered_parts 为空" % (qid, st),
                    "列出未回答的部分与原因")
            elif bad:
                chk("Q08", False, "未完成部分有原因",
                    "question_id=%s 有 %d 条 unanswered_parts 缺 reason" % (qid, len(bad)),
                    "每条未完成部分写明原因")
        # Q11 needs_review 残留
        if a.get("needs_review") is True and st == "answered":
            warn("Q11", "候选标记已清理",
                 "question_id=%s 仍带 needs_review=true" % qid)

    # Q09 阅读范围
    cov = result.get("coverage")
    cov = cov if isinstance(cov, dict) else {}
    if "read_sections" not in cov:
        chk("Q09", False, "阅读范围可核验",
            "coverage 缺 read_sections",
            "coverage 说明已读章节；未读章节与原因写进 unread_sections / reasons")

    report = {
        "pass": not errors,
        "errors": errors,
        "warnings": warnings,
        "checks": checks,
        "totals": {"errors": len(errors), "warnings": len(warnings),
                   "checks": len(checks)},
    }
    out = args.out or os.path.join(os.path.dirname(os.path.abspath(args.result)),
                                   "qa_review.json")
    with open(out, "w", encoding="utf-8") as fh:
        json.dump(report, fh, ensure_ascii=False, indent=2)
    print(json.dumps(report, ensure_ascii=False, indent=2)[:4000])
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
