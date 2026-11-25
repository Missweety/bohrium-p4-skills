#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""repro_plan.py - build a reproduction plan and re-check reported statistics.

Two independent outputs:
  1. plan: data / environment / parameters / commands, each with verbatim evidence
     or an explicit `missing` status (never invented);
  2. checks: deterministic recomputation of relations stated in the text
     (t(df)->p, z->p, from->to percent change). Only text-supplied inputs are used.

Verdict vocabulary per claim:
  recomputed_consistent    numeric relation re-checked and all dependencies present
  recomputed_inconsistent  same, but the reported value disagrees beyond rounding
  partially_reproduced     relation agrees, but data/code/parameters are not fully given
  not_reproducible         no relation can be re-run and dependencies are absent
  not_checkable            relation is stated but inputs (df/p/CI) are incomplete

Stdlib only. No network, no prepared answers.
"""
from __future__ import annotations

import re

import stats_check

SECTION_PATTERNS = {
    "data": re.compile(
        r"(dataset|data set|raw data|public data|GSE\d+|GEO|participants|samples|"
        r"数据集|数据来源|样本)", re.I),
    "environment": re.compile(
        r"(Python\s*\d+(?:\.\d+)?|R\s*\d+(?:\.\d+)?|MATLAB|TensorFlow\s*[\d.]*|"
        r"PyTorch\s*[\d.]*|scikit-learn|statsmodels|NumPy|CUDA\s*[\d.]*|"
        r"软件版本|运行环境)", re.I),
    "parameters": re.compile(
        r"(learning rate|batch size|epochs?|random seed|hyperparameter|"
        r"α|alpha\s*=|参数|学习率|批大小|迭代轮数)", re.I),
    "commands": re.compile(
        r"(^\s*[$>]\s*\S+|python3?\s+\S+\.py|Rscript\s+\S+|bash\s+\S+|"
        r"analysis script|运行命令|执行命令)", re.I),
    "code": re.compile(
        r"(github|gitlab|zenodo|osf\.io|repository|代码仓库|复现代码|"
        r"(?:replication|source|analysis)\s+code|code\s+(?:is|are)\s+available)", re.I),
}

CODE_AVAIL = re.compile(r"(available on request|upon request|应要求|可索取|未公开)", re.I)

PARAM_PATTERNS = [
    ("learning_rate", re.compile(r"learning rate\s*(?:of|=|:)?\s*([\d.eE+-]+)", re.I)),
    ("batch_size", re.compile(r"batch size\s*(?:of|=|:)?\s*(\d+)", re.I)),
    ("epochs", re.compile(r"epochs?\s*(?:of|=|:)?\s*(\d+)", re.I)),
    ("random_seed", re.compile(r"(?:random )?seed\s*(?:of|=|:)?\s*(\d+)", re.I)),
    ("alpha", re.compile(r"(?:α|alpha)\s*=\s*([\d.]+)", re.I)),
    ("学习率", re.compile(r"学习率\s*(?:为|=|:)?\s*([\d.eE+-]+)")),
]

T_RE = re.compile(r"t\s*\(\s*(\d+(?:\.\d+)?)\s*\)\s*[=≈]\s*(-?\d+(?:\.\d+)?)")
Z_RE = re.compile(r"\bz\s*[=≈]\s*(-?\d+(?:\.\d+)?)")
P_RE = re.compile(r"\bp\s*([=<>＜＞≤≥])\s*(0?\.\d+|\d+\.\d+)")
FROM_TO_RE = re.compile(r"from\s*(\d+(?:\.\d+)?)\s*[A-Za-z%µμ/^0-9·. ]{0,8}\s*to\s*(\d+(?:\.\d+)?)", re.I)
PCT_RE = re.compile(r"(-?\d+(?:\.\d+)?)\s*%")
RESULT_CUE = re.compile(
    r"(significant|reduced|increased|improved|decreased|no difference|"
    r"显著|降低|升高|改善|无差异)", re.I)


def _sentences(text):
    parts = re.split(r"(?<=[.!?。！？])\s+", text or "")
    return [p.strip() for p in parts if len(p.strip()) >= 15]


def _decimals(s):
    return len(s.split(".")[1]) if "." in s else 0


def _p_tolerance(reported_text):
    return 0.5 * 10 ** (-max(1, _decimals(reported_text)))


def _build_plan(doc):
    plan = {k: [] for k in SECTION_PATTERNS}
    for para in doc.get("paragraphs") or []:
        for sent in _sentences(para["text"]):
            for kind, pat in SECTION_PATTERNS.items():
                if not pat.search(sent):
                    continue
                entry = {
                    "kind": kind,
                    "paragraph_id": para["paragraph_id"],
                    "source_file": para.get("source_file"),
                    "quote": sent[:320],
                }
                if kind == "parameters":
                    for name, ppat in PARAM_PATTERNS:
                        m = ppat.search(sent)
                        if m:
                            entry["item"] = name
                            entry["value"] = m.group(1)
                            break
                    if "item" not in entry:
                        m = pat.search(sent)
                        entry["item"] = m.group(1) if m else "parameter"
                        entry["value"] = None
                elif kind == "environment":
                    m = pat.search(sent)
                    entry["item"] = "environment"
                    entry["value"] = m.group(1) if m else None
                elif kind == "commands":
                    entry["item"] = "command"
                    entry["value"] = sent.strip()[:240]
                elif kind == "code":
                    m = re.search(r"https?://\S+|github\.com/\S+", sent)
                    entry["item"] = "code"
                    entry["value"] = m.group(0) if m else "code statement"
                    if CODE_AVAIL.search(sent) and not m:
                        entry["status"] = "missing"
                        entry["note"] = "原文仅称可索取/未公开，未提供可执行代码"
                        plan[kind].append(entry)
                        continue
                else:
                    m = pat.search(sent)
                    entry["item"] = "dataset"
                    entry["value"] = m.group(1) if m else None
                entry["status"] = "specified" if entry.get("value") else "missing"
                if entry not in plan[kind]:
                    plan[kind].append(entry)
    for kind in plan:
        if not plan[kind]:
            plan[kind].append({
                "kind": kind, "item": kind, "value": None, "status": "missing",
                "paragraph_id": None, "quote": None,
                "note": "材料中未找到该类信息；未按惯例补默认值。",
            })
    return plan


def _plan_complete(plan):
    return {kind: any(e.get("status") == "specified" for e in items)
            for kind, items in plan.items()}


def _check_sentence(sent, para):
    checks = []
    p_matches = list(P_RE.finditer(sent))
    t_matches = list(T_RE.finditer(sent))
    z_matches = list(Z_RE.finditer(sent))

    for tm in t_matches:
        t_val, df_val = float(tm.group(2)), float(tm.group(1))
        p_after = [pm for pm in p_matches if pm.start() > tm.start()]
        pm = p_after[0] if p_after else (p_matches[0] if p_matches else None)
        computed = stats_check.t_to_p(t_val, df_val)
        base = {
            "test": "student_t",
            "inputs": {"t": t_val, "df": df_val},
            "computed_p": round(computed, 6),
            "formula": "two-sided p = I_{df/(df+t^2)}(df/2, 1/2)",
            "paragraph_id": para["paragraph_id"],
            "quote": sent[:320],
        }
        if pm is None:
            base.update(status="not_checkable", verdict="not_checkable",
                        reason="未报告 p 值，无法与复算结果对照")
            checks.append(base)
            continue
        op, p_text = pm.group(1), pm.group(2)
        reported = float(p_text)
        tol = _p_tolerance(p_text)
        if op in ("<", "＜"):
            verdict = "consistent" if computed < reported else "inconsistent"
        elif op in (">", "＞"):
            verdict = "consistent" if computed > reported else "inconsistent"
        else:
            verdict = "consistent" if abs(computed - reported) <= tol else "inconsistent"
        base.update(status="checked", verdict=verdict, reported_p=reported,
                    reported_operator=op, tolerance=tol,
                    abs_diff=round(abs(computed - reported), 6))
        checks.append(base)

    for zm in z_matches:
        z_val = float(zm.group(1))
        p_after = [pm for pm in p_matches if pm.start() > zm.start()]
        pm = p_after[0] if p_after else None
        computed = stats_check.z_to_p(z_val)
        entry = {
            "test": "normal_z", "inputs": {"z": z_val},
            "computed_p": round(computed, 6),
            "formula": "two-sided p = erfc(|z|/sqrt(2))",
            "paragraph_id": para["paragraph_id"], "quote": sent[:320],
        }
        if pm is None:
            entry.update(status="not_checkable", verdict="not_checkable",
                         reason="未报告 p 值")
        else:
            op, p_text = pm.group(1), pm.group(2)
            reported, tol = float(p_text), _p_tolerance(p_text)
            if op in ("<", "＜"):
                verdict = "consistent" if computed < reported else "inconsistent"
            elif op in (">", "＞"):
                verdict = "consistent" if computed > reported else "inconsistent"
            else:
                verdict = "consistent" if abs(computed - reported) <= tol else "inconsistent"
            entry.update(status="checked", verdict=verdict, reported_p=reported,
                         reported_operator=op, tolerance=tol,
                         abs_diff=round(abs(computed - reported), 6))
        checks.append(entry)

    fm = FROM_TO_RE.search(sent)
    pctm = PCT_RE.search(sent)
    if fm and pctm:
        start, end = float(fm.group(1)), float(fm.group(2))
        computed = stats_check.percent_change(start, end)
        reported = float(pctm.group(1))
        tol = max(0.05, _p_tolerance(pctm.group(1)))
        # "decreased from 82.4 to 79.1 (4.0% reduction)" reports magnitude, not sign.
        directional = re.search(r"decreas|reduc|lower|drop|降低|下降", sent, re.I)
        cmp_computed, cmp_reported = computed, reported
        if directional:
            cmp_computed, cmp_reported = abs(computed), abs(reported)
        checks.append({
            "test": "percent_change",
            "inputs": {"from": start, "to": end},
            "computed_pct": round(computed, 4),
            "reported_pct": reported,
            "formula": "(to - from) / from * 100",
            "verdict": ("consistent" if abs(cmp_computed - cmp_reported) <= tol
                        else "inconsistent"),
            "status": "checked", "tolerance": tol,
            "abs_diff": round(abs(cmp_computed - cmp_reported), 4),
            "paragraph_id": para["paragraph_id"], "quote": sent[:320],
        })
    return checks


def build(doc):
    plan = _build_plan(doc)
    complete = _plan_complete(plan)

    claims, checks = [], []
    for para in doc.get("paragraphs") or []:
        for sent in _sentences(para["text"]):
            sent_checks = _check_sentence(sent, para)
            if not sent_checks and not RESULT_CUE.search(sent):
                continue
            checks.extend(sent_checks)
            verdicts = [c["verdict"] for c in sent_checks]
            if "inconsistent" in verdicts:
                status = "recomputed_inconsistent"
            elif "consistent" in verdicts:
                status = ("recomputed_consistent"
                          if all(complete.values()) else "partially_reproduced")
            elif sent_checks:
                status = "not_checkable"
            else:
                status = "not_reproducible" if not complete["data"] else "not_checkable"
            missing = [k for k, ok in complete.items() if not ok]
            claims.append({
                "claim_id": "C%d" % (len(claims) + 1),
                "claim": sent[:300],
                "paragraph_id": para["paragraph_id"],
                "source_file": para.get("source_file"),
                "quote": sent[:320],
                "status": status,
                "missing_dependencies": missing,
                "checks": sent_checks,
                "note": _verdict_note(status, missing),
            })

    conflicts = [c for c in checks if c.get("verdict") == "inconsistent"]
    summary = {
        "claims": len(claims),
        "recomputed_consistent": sum(1 for c in claims if c["status"] == "recomputed_consistent"),
        "recomputed_inconsistent": sum(1 for c in claims
                                       if c["status"] == "recomputed_inconsistent"),
        "partially_reproduced": sum(1 for c in claims if c["status"] == "partially_reproduced"),
        "not_reproducible": sum(1 for c in claims if c["status"] == "not_reproducible"),
        "not_checkable": sum(1 for c in claims if c["status"] == "not_checkable"),
        "checks": len(checks),
        "conflicts": len(conflicts),
    }
    return {
        "plan": plan,
        "plan_complete": complete,
        "claims": claims,
        "checks": checks,
        "conflicts": conflicts,
        "summary": summary,
    }


def _verdict_note(status, missing):
    if status == "recomputed_consistent":
        return "复算一致，且数据/环境/参数/命令在材料中均有原文依据。"
    if status == "recomputed_inconsistent":
        return "复算与原文报告不一致（超出报告精度容差），需人工核对。"
    if status == "partially_reproduced":
        return "统计关系复算一致，但缺少：%s，只能算部分复现。" % "、".join(missing)
    if status == "not_reproducible":
        return "无可复算关系且缺少数据/命令，无法独立复现；未编造复现结果。"
    return "原文陈述不足以复算（缺 df/p/数据），标为不可核验。"
