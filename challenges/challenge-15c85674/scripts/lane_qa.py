#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""lane_qa.py - 文献问答赛道的候选生成器（脚本给候选，模型下结论）。

本题（literature-qa）与其它赛题的契约不同：
    输入  /input/case.json     案例与论文标识、材料版本、段落清单、任务说明、问题清单
    输出  /app/output/result.json
          case_id / paper_id / material_version
          answers[]        每题一项：question_id、answer、conditions[]、status、
                            claims[]（claim_id/text/kind/evidence[{paragraph_id,quote}]）、
                            unanswered_parts[]
          coverage         已读章节、未读章节及原因

本脚本只做三件事：
    1. 从 /input 里发现段落清单与问题清单（不假设字段名，做多形态兼容）
    2. 为每个问题检索候选段落，并给出**逐字**的句子引文候选
    3. 装配骨架 result.json：每题都有一项（不省略无法回答的问题），
       候选带 needs_review，答案文本与结论留给上层模型填写

它**不下结论**：候选只保证「这段文字与这个问题共现」，
「这句话是否真的回答了这个问题」由模型逐条判定。
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import traceback

# ---------------------------------------------------------------- 状态词表
ANSWER_STATUS = ("answered", "partial", "insufficient_evidence", "input_error")
CLAIM_KIND = ("reported", "inferred")

QUESTION_KEYS = ("question", "query", "prompt", "question_text", "question_content",
                 "sub_question", "zh_question")
QUESTION_ID_KEYS = ("question_id", "qid", "question_no", "question_index", "q_id", "id")
PARA_ID_KEYS = ("paragraph_id", "para_id", "paragraphId", "paragraph_no", "p_id",
                "paragraph_index", "section_paragraph_id", "id")
PARA_TEXT_KEYS = ("text", "content", "body", "paragraph", "paragraph_text", "raw_text")
SECTION_KEYS = ("section", "section_id", "section_name", "chapter", "chapter_id",
                "section_title")
ID_KEYS = ("case_id", "id", "task_id")
PAPER_KEYS = ("paper_id", "paper", "document_id", "doc_id", "article_id")
VERSION_KEYS = ("material_version", "version", "material_id", "revision")


# ---------------------------------------------------------------- 工具
def norm(text):
    return re.sub(r"\s+", " ", (text or "")).strip()


def load_json(path):
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:
        return None


def iter_dicts(node, depth=0):
    """深度优先遍历所有 dict。"""
    if depth > 12:
        return
    if isinstance(node, dict):
        yield node
        for v in node.values():
            yield from iter_dicts(v, depth + 1)
    elif isinstance(node, list):
        for v in node:
            yield from iter_dicts(v, depth + 1)


def pick_str(d, keys):
    for k in keys:
        v = d.get(k)
        if isinstance(v, str) and v.strip():
            return v.strip()
    return ""


def pick_id(d, keys):
    for k in keys:
        v = d.get(k)
        if isinstance(v, (str, int)) and str(v).strip():
            return str(v).strip()
    return ""


def first_str(obj, keys):
    """在任意嵌套 dict 中按优先级找第一个非空字符串。"""
    if isinstance(obj, dict):
        for k in keys:
            v = obj.get(k)
            if isinstance(v, str) and v.strip():
                return v.strip()
        for v in obj.values():
            got = first_str(v, keys)
            if got:
                return got
    return ""


# ---------------------------------------------------------------- 发现
def discover_paragraphs(root):
    """从 /input 下所有 JSON 里找段落清单。返回 [{paragraph_id, text, section}]。"""
    found = []
    seen = set()

    def add(pid, text, section):
        text = norm(text)
        if not text:
            return
        key = (pid, text[:80])
        if key in seen:
            return
        seen.add(key)
        found.append({"paragraph_id": pid, "text": text, "section": section})

    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        dirnames[:] = sorted(d for d in dirnames
                             if not d.startswith(".") and d != "__pycache__")
        for name in sorted(filenames):
            if not name.lower().endswith(".json"):
                continue
            data = load_json(os.path.join(dirpath, name))
            if data is None:
                continue
            for d in iter_dicts(data):
                pid = pick_id(d, PARA_ID_KEYS)
                text = pick_str(d, PARA_TEXT_KEYS)
                if not text or len(text) < 5:
                    continue
                # 排除明显是问题而非段落的记录
                if any(k in d for k in QUESTION_KEYS) and not pid:
                    continue
                section = pick_str(d, SECTION_KEYS)
                if not pid:
                    pid = "p%d" % (len(found) + 1)
                add(pid, text, section)
    return found


def discover_questions(root, case):
    """从 /input 下所有 JSON 里找问题清单。返回 [{question_id, question}]。"""
    found = []
    seen = set()

    def add(qid, text):
        text = norm(text)
        if not text:
            return
        if (qid, text[:60]) in seen:
            return
        seen.add((qid, text[:60]))
        found.append({"question_id": qid, "question": text})

    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        dirnames[:] = sorted(d for d in dirnames
                             if not d.startswith(".") and d != "__pycache__")
        for name in sorted(filenames):
            if not name.lower().endswith(".json"):
                continue
            data = load_json(os.path.join(dirpath, name))
            if data is None:
                continue
            for d in iter_dicts(data):
                qtext = ""
                for k in QUESTION_KEYS:
                    v = d.get(k)
                    if isinstance(v, str) and v.strip():
                        qtext = v.strip()
                        break
                    if isinstance(v, list) and v:
                        parts = [x for x in v if isinstance(x, str)]
                        if parts:
                            qtext = " ".join(parts)
                            break
                if not qtext:
                    continue
                qid = pick_id(d, QUESTION_ID_KEYS)
                if not qid:
                    qid = "q%d" % (len(found) + 1)
                add(qid, qtext)
    if not found:
        # 退化：从 case.json 顶层字符串字段里找
        for d in iter_dicts(case):
            for k in QUESTION_KEYS:
                v = d.get(k)
                if isinstance(v, str) and v.strip():
                    add("q1", v)
                    break
            if found:
                break
    return found


# ---------------------------------------------------------------- 检索
CJK = re.compile(r"[一-鿿]")
WORD = re.compile(r"[A-Za-z0-9][A-Za-z0-9_\-\.]*")
NUM = re.compile(r"\d+(?:\.\d+)?%?")


def tokens(text):
    t = (text or "").lower()
    out = set()
    for w in WORD.findall(t):
        if len(w) >= 2 or w.isdigit():
            out.add(w)
    cjk = CJK.findall(t)
    for i in range(len(cjk) - 1):
        out.add(cjk[i] + cjk[i + 1])
    if cjk:
        out.update(cjk)
    return out


# ---------------------------------------------------------------- 跨语言检索
# 题目给的是**中文问题**，材料是**英文段落**，纯字面重合几乎为零。
# 用一张通用科研中英概念对照表把中文术语扩展成英文检索词，
# 让候选检索在跨语言场景下仍然能召回相关段落。
TERM_TABLE = None


def load_terms():
    global TERM_TABLE
    if TERM_TABLE is not None:
        return TERM_TABLE
    table = {}
    paths = [
        os.path.join(os.path.dirname(os.path.abspath(__file__)),
                     "..", "resources", "bilingual_terms.json"),
        os.path.join(os.path.dirname(os.path.abspath(__file__)),
                     "bilingual_terms.json"),
    ]
    for path in paths:
        data = load_json(path)
        if isinstance(data, dict) and isinstance(data.get("terms"), dict):
            table = data["terms"]
            break
    TERM_TABLE = table
    return table


def expand_query(text):
    """把中文问题里的术语扩展成英文检索词，返回额外的 token 集合。"""
    table = load_terms()
    if not table:
        return set()
    low = (text or "").lower()
    extra = set()
    for cn, ens in table.items():
        if cn in (text or ""):
            for en in ens:
                if len(en) >= 3:
                    extra.add(en.lower())
    # 英文问题里直接出现的英文术语也纳入
    for en in re.findall(r"[A-Za-z][A-Za-z\-]{3,}", low):
        extra.add(en)
    return extra



def sentences(text):
    parts = re.split(r"(?<=[.!?。！？；;])\s+", (text or "").strip())
    return [p for p in (x.strip() for x in parts) if len(p) >= 8]


def score_question(qtext, para, extra=None):
    qtok = tokens(qtext)
    if extra:
        qtok = qtok | set(extra)
    ptok = tokens(para["text"])
    if not qtok:
        return 0.0
    overlap = qtok & ptok
    if not overlap:
        return 0.0
    # 词元数量差异大时用覆盖率，避免长段落仅因 token 多而占优
    base = len(overlap) / float(len(qtok))
    qnums = set(NUM.findall(qtext))
    pnums = set(NUM.findall(para["text"]))
    bonus = 0.15 if (qnums & pnums) else 0.0
    return base + bonus


def candidates_for(question, paragraphs, top_k=5):
    qtext = question["question"]
    extra = expand_query(qtext)
    scored = []
    for para in paragraphs:
        s = score_question(qtext, para, extra)
        if s > 0:
            scored.append((s, para))
    scored.sort(key=lambda x: (-x[0], x[1]["paragraph_id"]))
    qtok = tokens(qtext) | set(extra)
    out = []
    for s, para in scored[:top_k]:
        best = ""
        best_score = -1.0
        for sent in sentences(para["text"]):
            stok = tokens(sent)
            if not stok:
                continue
            ov = len(qtok & stok) / float(len(qtok) or 1)
            if ov > best_score:
                best_score = ov
                best = sent
        if not best:
            best = para["text"][:240]
        out.append({
            "paragraph_id": para["paragraph_id"],
            "section": para.get("section", ""),
            "quote": best,
            "score": round(s, 4),
            "needs_review": True,
        })
    return out


# ---------------------------------------------------------------- 装配
def empty_answers(questions, candidates_map, reason):
    out = []
    for q in questions:
        cands = candidates_map.get(q["question_id"], [])
        status = "insufficient_evidence" if not cands else "partial"
        out.append({
            "question_id": q["question_id"],
            "question": q["question"],
            "answer": "",
            "conditions": [],
            "status": status,
            "claims": [],
            "unanswered_parts": ([] if cands else [{
                "part": "全文",
                "reason": reason,
            }]),
            "candidates": cands,
            "needs_review": True,
        })
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description="文献问答：候选生成 + 骨架装配")
    ap.add_argument("--input", default="/input")
    ap.add_argument("--output", default="/app/output")
    ap.add_argument("--work", default="/app/work")
    args = ap.parse_args(argv)

    in_dir, out_dir, work_dir = args.input, args.output, args.work
    os.makedirs(out_dir, exist_ok=True)
    os.makedirs(work_dir, exist_ok=True)

    case = load_json(os.path.join(in_dir, "case.json")) or {}
    if not isinstance(case, dict):
        case = {}
    contract = case.get("output_contract") or {}
    if not isinstance(contract, dict):
        contract = {}

    case_id = first_str(case, ID_KEYS) or os.path.basename(os.path.abspath(in_dir))
    paper_id = first_str(case, PAPER_KEYS)
    material_version = first_str(case, VERSION_KEYS)

    paragraphs = discover_paragraphs(in_dir)
    questions = discover_questions(in_dir, case)

    cands_map = {}
    for q in questions:
        cands_map[q["question_id"]] = candidates_for(q, paragraphs)

    reason = "未在材料中发现可定位的段落" if not paragraphs else "候选段落均未命中该问题"
    answers = empty_answers(questions, cands_map, reason)

    sections_read = sorted({p["section"] for p in paragraphs if p.get("section")})
    result = {
        "case_id": case_id,
        "paper_id": paper_id,
        "material_version": material_version,
        "status": "partial" if questions else "failed",
        "answers": answers,
        "coverage": {
            "read_sections": sections_read,
            "unread_sections": [],
            "reasons": [] if paragraphs else ["输入中未发现段落清单"],
            "paragraph_count": len(paragraphs),
            "question_count": len(questions),
        },
        "sources": ([{
            "file": "case.json",
            "locator": "paragraph_id=%s" % ", ".join(p["paragraph_id"] for p in paragraphs[:12]),
            "note": "段落清单来源",
        }] if paragraphs else []),
        "uncertainty": {
            "level": "medium" if paragraphs else "high",
            "notes": (["已为每个问题生成候选段落与逐字引文；答案文本与结论尚未填写，"
                       "需由模型逐条复核后写回"] if paragraphs else
                      ["输入中未发现段落清单，无法给出任何有据回答"]),
            "unresolved": [q["question_id"] for q in questions],
        },
        "change_log": [
            "读取 /input/case.json，识别 case_id=%s paper_id=%s material_version=%s"
            % (case_id, paper_id or "(未提供)", material_version or "(未提供)"),
            "发现段落 %d 条、问题 %d 个" % (len(paragraphs), len(questions)),
            "逐题生成候选段落与逐字引文（needs_review=true），答案文本留给模型复核填写",
        ],
    }

    # 若 output_contract 声明了必填字段，确保骨架里有对应槽位
    required = contract.get("required") if isinstance(contract, dict) else None
    if isinstance(required, list):
        for key in required:
            if key in result or key in ("answers", "coverage"):
                continue
            result[key] = [] if key.endswith("s") else {}

    work_payload = {
        "case_id": case_id,
        "paper_id": paper_id,
        "material_version": material_version,
        "paragraphs": paragraphs,
        "questions": questions,
        "candidates": cands_map,
    }
    with open(os.path.join(work_dir, "qa_context.json"), "w", encoding="utf-8") as fh:
        json.dump(work_payload, fh, ensure_ascii=False, indent=2)
    with open(os.path.join(out_dir, "result.json"), "w", encoding="utf-8") as fh:
        json.dump(result, fh, ensure_ascii=False, indent=2)

    sys.stderr.write("[lane_qa] case=%s paragraphs=%d questions=%d\n"
                     % (case_id, len(paragraphs), len(questions)))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        sys.stderr.write("[lane_qa] fatal:\n%s\n" % traceback.format_exc())
        sys.exit(0)
