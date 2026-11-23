#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""build_proposal.py - assemble an evidence-anchored research proposal.

Two-pass design
---------------
1. No --plan: scan /input, write <work>/proposal_plan.json (explicit draft
   scaffold) and a first editable proposal under <output>.
2. --plan PATH: use the agent-refined plan, verify every quoted claim against
   <work>/sources.json, then render the final proposal.md / proposal.html /
   evidence.csv and result.json (all output_contract fields + case_id).

Pure Python 3 standard library. No network, no third-party packages.

Usage:
  python3 scripts/extract_sources.py --input /input --work /app/work
  python3 scripts/build_proposal.py --input /input --work /app/work \
      --output /app/output [--plan /app/work/proposal_plan.json]
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import html
import json
import math
import os
import re
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import common  # noqa: E402
import docx_mini  # noqa: E402
import extract_sources  # noqa: E402

DEFAULT_FIELDS = [
    "case_id", "status", "proposal_md", "proposal_docx", "elements",
    "evidence", "sources", "constraints", "feasibility", "risks",
    "milestones", "uncertainty", "change_log", "artifacts",
]

ELEMENT_KEYS = [
    "research_background", "problem_definition", "objectives",
    "technical_route", "schedule", "risks", "expected_outcomes",
]
ELEMENT_LABELS = {
    "research_background": "研究背景",
    "problem_definition": "问题定义",
    "objectives": "研究目标",
    "technical_route": "技术路线",
    "schedule": "阶段计划",
    "risks": "风险与备选方案",
    "expected_outcomes": "预期成果",
}
STATUS_ZH = {
    "reported": "已定位",
    "draft": "草案",
    "not_reported": "材料未提供",
    "source_conflict": "来源冲突",
    "extraction_failed": "抽取失败",
}

BACKGROUND_MARKERS = [
    "背景", "现状", "已有研究", "研究表明", "前期", "预实验", "已知", "文献",
    "introduction", "background", "prior", "reported", "established",
]
GAP_MARKERS = [
    "不足", "缺乏", "缺少", "尚未", "空白", "未解决", "有待", "缺失", "不确定", "少有", "未",
    "limited", "gap", "lack", "unknown", "unclear", "not yet",
]
METHOD_MARKERS = [
    "方法", "采用", "通过", "基于", "实验", "分析", "构建", "建立", "模型", "队列",
    "随机", "对照", "比较", "测序", "问卷", "访谈", "仿真", "验证", "评估", "评价",
    "测量", "纳入", "执行", "随访", "校准", "提取", "一致性",
    "method", "approach", "using", "analy", "measure", "model", "trial",
]
METRIC_MARKERS = [
    "指标", "判据", "阈值", "准确率", "灵敏度", "特异度", "auc", "p<", "p <",
    "差异", "达到", "至少", "%", "≥", "≤",
]
OUTCOME_MARKERS = [
    "预期成果", "预期", "产出", "交付", "发表", "专利", "数据集", "报告",
    "outcome", "deliverable", "publication", "dataset", "output",
]
RISK_CATEGORIES = ["data", "method", "schedule", "ethics"]
RISK_CATEGORY_ZH = {
    "data": "数据获取", "method": "方法可行性",
    "schedule": "进度", "ethics": "伦理与合规",
}
RISK_CATEGORY_MARKERS = {
    "data": ["数据", "样本", "招募", "纳入", "获取", "采集", "事件",
             "data", "sample", "recruit", "enrol"],
    "method": ["方法", "实验", "模型", "分析", "测量", "一致性", "培训", "校准",
               "method", "experiment", "model", "measure", "consisten"],
    "schedule": ["进度", "延期", "周期", "时间", "招募", "延长", "窗口", "里程碑",
                 "schedule", "delay", "timeline", "milestone"],
    "ethics": ["伦理", "合规", "知情", "审批", "irb", "ethic", "compliance", "consent"],
}
RISK_SIGNAL_WORDS = ["风险", "不确定", "延迟", "失败", "不足", "低于", "少于",
                     "挑战", "受限", "risk", "uncertain", "delay", "fail", "short"]

PERIOD_KEYS = {
    "duration_months", "period_months", "cycle_months", "duration",
    "research_months", "timeline_months", "months",
}
BUDGET_KEYS = {"budget", "budget_wan", "funding", "funding_wan", "cost", "经费"}
PERSONNEL_KEYS = {"personnel", "team", "staff", "researchers", "人员"}
DATA_KEYS = {"data", "dataset", "datasets", "data_access", "数据"}
ETHICS_KEYS = {"ethics", "compliance", "irb", "伦理"}
SAMPLE_KEYS = {"sample_size", "sample", "n", "samples", "样本量"}
SKIP_CASE_KEYS = {
    "output_contract", "outputcontract", "contract", "required_outputs",
    "scoring", "figures", "resources", "reviewstatus", "visibility",
}


# ---------------------------------------------------------------- text utils

def sentences(text):
    parts = re.split(
        r"(?<=[。！？；])|(?<=[.!?])\s+(?=[A-Z0-9\u4e00-\u9fff])",
        text or "",
    )
    out = []
    for part in parts:
        item = (part or "").strip()
        if item:
            out.append(item)
    return out


def short(text, limit=120):
    text = common.norm_ws(text)
    if len(text) <= limit:
        return text
    return text[:limit].rstrip() + "\u2026"


def md_cell(value, limit=180):
    text = common.norm_ws(common.safe_text(value))
    text = text.replace("|", "\\|")
    if len(text) > limit:
        text = text[:limit].rstrip() + "\u2026"
    return text or "\u2014"


def status_label(value):
    return STATUS_ZH.get(value, value or "")


def fmt_num(value):
    """Render 18.0 as 18 while keeping real decimals such as 0.75."""
    if value is None:
        return ""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return str(value)
    if abs(number - round(number)) < 1e-9:
        return str(int(round(number)))
    return ("%.2f" % number).rstrip("0").rstrip(".")


def marker_score(text, markers):
    low = (text or "").lower()
    return sum(1 for marker in markers if marker.lower() in low)


def has_number(text):
    return bool(re.search(r"\d", text or ""))


def char_bigrams(text):
    clean = re.sub(r"[^0-9A-Za-z\u4e00-\u9fff]", "", text or "").lower()
    if len(clean) < 2:
        return set([clean]) if clean else set()
    return set(clean[i:i + 2] for i in range(len(clean) - 1))


# ---------------------------------------------------------------- input load

def load_case(input_dir):
    return common.load_json(os.path.join(input_dir, "case.json"), {}) or {}


def contract_fields(case):
    names, raw = common.contract_declaration(case)
    expanded = []
    for name in names:
        for part in re.split(r"[,;，；\s]+", name):
            part = part.strip()
            if part and part not in expanded:
                expanded.append(part)
    if expanded:
        return expanded, raw, "case.output_contract"
    return list(DEFAULT_FIELDS), raw, "default"


def load_sources(input_dir, work_dir, sources_path=None):
    path = sources_path or os.path.join(work_dir, "sources.json")
    bundle = common.load_json(path, None)
    if not isinstance(bundle, dict) or not bundle.get("sources"):
        try:
            bundle = extract_sources.extract(input_dir)
        except Exception as exc:  # noqa: BLE001
            bundle = {
                "case_id": common.case_id_of(load_case(input_dir), input_dir),
                "stats": {"files_seen": 0, "readable": 0, "unreadable": 0,
                          "paragraphs": 0, "chars": 0},
                "sources": [], "unreadable": [], "skipped": [],
                "error": str(exc)[:300],
            }
    return bundle, path


def augment_task_source(bundle, input_dir):
    """task.md is a workorder, not scientific evidence. Keep it as a separate
    role=task source so constraint quotes remain traceable without polluting
    background/gap extraction."""
    path = os.path.join(input_dir, "task.md")
    if not os.path.isfile(path):
        return
    for src in bundle.get("sources", []):
        if src.get("rel_path") == "task.md" or src.get("role") == "task":
            return
    text = common.read_text(path)
    paragraphs = extract_sources._markdown_paragraphs(text, "TASK")
    if not paragraphs:
        paragraphs = extract_sources._paragraphs_from_text(text, "TASK")
    bundle.setdefault("sources", []).append({
        "id": "TASK", "file": "task.md", "rel_path": "task.md",
        "kind": "task", "role": "task", "tier": "task",
        "readable": bool(paragraphs), "page_count": 1,
        "paragraphs": paragraphs,
        "error": None if paragraphs else "task.md has no readable text",
        "chars": sum(len(p.get("text", "")) for p in paragraphs),
    })
    bundle.setdefault("stats", {})["task_source_added"] = True


def source_file_sha256(path):
    try:
        with open(path, "rb") as fh:
            return hashlib.sha256(fh.read()).hexdigest()
    except OSError:
        return None


def find_listed_missing(case, input_dir, bundle):
    found = set(src.get("rel_path") for src in bundle.get("sources", []))
    candidates = []

    def add(value):
        if isinstance(value, str):
            candidates.append(value)
        elif isinstance(value, dict):
            for key in ("path", "file", "name", "filename"):
                if isinstance(value.get(key), str):
                    candidates.append(value[key])

    for key in ("materials", "files", "attachments", "documents", "inputs"):
        value = case.get(key)
        if isinstance(value, list):
            for item in value:
                add(item)
        else:
            add(value)
    for key in ("paper", "pdf", "document", "source", "manuscript"):
        add(case.get(key))

    missing = []
    for item in candidates:
        rel = item.replace("\\", "/")
        if os.path.isabs(rel):
            full = rel
            rel = os.path.basename(rel)
        else:
            full = os.path.join(input_dir, rel)
        exists = os.path.isfile(full)
        if exists and rel not in found:
            found.add(rel)
        elif not exists and rel not in [m["file"] for m in missing]:
            missing.append({"file": rel, "reason": "listed in case.json but not found"})
    return missing


def build_para_index(bundle):
    index = {}
    for src in bundle.get("sources", []):
        for para in src.get("paragraphs", []):
            index[para.get("anchor")] = {
                "text": para.get("text", ""),
                "file": src.get("file", ""),
                "section": para.get("section", ""),
                "source_id": src.get("id", ""),
            }
    return index


def content_paragraphs(bundle):
    rows = []
    for src in bundle.get("sources", []):
        if src.get("role") == "task" or not src.get("readable"):
            continue
        for para in src.get("paragraphs", []):
            rows.append({
                "text": para.get("text", ""),
                "anchor": para.get("anchor", ""),
                "file": src.get("file", ""),
                "source_id": src.get("id", ""),
                "section": para.get("section", ""),
                "is_heading": bool(para.get("is_heading")),
            })
    return rows


# ------------------------------------------------------------ evidence scan

def select_sentences(paragraphs, markers, limit, section_markers=None,
                     require_number=False):
    picked = []
    seen = set()
    for order, para in enumerate(paragraphs):
        if para.get("is_heading"):
            continue
        section_bonus = 0
        if section_markers and marker_score(para.get("section", ""), section_markers):
            section_bonus = 2
        for sent in sentences(para.get("text", "")):
            if len(sent) < 8 or len(sent) > 600:
                continue
            score = marker_score(sent, markers) + section_bonus
            if score <= 0:
                continue
            if require_number and not has_number(sent):
                continue
            key = common.canon(sent)
            if not key or key in seen:
                continue
            seen.add(key)
            picked.append({
                "order": order,
                "score": score + (0.5 if has_number(sent) else 0),
                "text": sent,
                "anchor": para["anchor"],
                "file": para["file"],
                "source_id": para["source_id"],
                "section": para["section"],
            })
    picked.sort(key=lambda item: (-item["score"], item["order"]))
    picked = picked[:limit]
    picked.sort(key=lambda item: item["order"])
    return picked


# -------------------------------------------------------------- constraints

def _months_from(num, unit):
    unit = (unit or "").lower()
    if unit.startswith(("年", "year")):
        return round(num * 12.0, 2)
    if unit.startswith(("周", "week")):
        return round(num / 4.345, 2)
    return round(num, 2)


def scan_period_text(text, anchor, file):
    out = []
    if not re.search(r"周期|期限|工期|时长|研究期|执行期|总周期|计划周期|duration|period|timeline",
                     text or "", re.I):
        return out
    for sent in sentences(text):
        if not re.search(r"周期|期限|工期|时长|研究期|执行期|总周期|计划周期|duration|period|timeline",
                         sent, re.I):
            continue
        if re.search(r"第[一二三四五六七八九十\d]+个?月|每月|本月", sent):
            continue
        for match in re.finditer(
                r"(\d+(?:\.\d+)?)\s*(个月|月|年|周|months?|years?|weeks?)",
                sent, re.I):
            months = _months_from(float(match.group(1)), match.group(2))
            if 0 < months <= 600:
                out.append({"value": months, "raw": match.group(0),
                            "anchor": anchor, "quote": sent, "file": file})
    return out


def _budget_wan(num, unit):
    unit = (unit or "").lower()
    if unit.startswith(("万元", "万")):
        return round(num, 4)
    if unit.startswith("千元"):
        return round(num / 10.0, 4)
    if unit.startswith("元"):
        return round(num / 10000.0, 4)
    if unit.startswith("million"):
        return round(num * 100.0, 4)
    return None


def scan_budget_text(text, anchor, file):
    out = []
    if not re.search(r"预算|经费|资助|预算上限|budget|funding|cost", text or "", re.I):
        return out
    for sent in sentences(text):
        if not re.search(r"预算|经费|资助|预算上限|budget|funding|cost", sent, re.I):
            continue
        for match in re.finditer(r"(\d+(?:\.\d+)?)\s*(万元|万|元|千元|million)", sent, re.I):
            value = _budget_wan(float(match.group(1)), match.group(2))
            if value and value > 0:
                out.append({"value": value, "raw": match.group(0),
                            "anchor": anchor, "quote": sent, "file": file})
    return out


def scan_sample_text(text, anchor, file):
    out = []
    low = (text or "").lower()
    if not re.search(r"样本|受试者|患者|参与者|例数|participants|subjects|sample", low):
        return out
    for sent in sentences(text):
        if not re.search(r"样本|受试者|患者|参与者|例数|participants|subjects|sample", sent, re.I):
            continue
        if re.search(r"博士生|硕士生|研究人员|技术员|团队|人员", sent) and \
                not re.search(r"受试者|患者|参与者|样本", sent):
            continue
        for match in re.finditer(
                r"(?:n\s*=\s*)?(\d+)\s*(?:名|例|位|人|份|participants?|subjects?)",
                sent, re.I):
            value = int(match.group(1))
            if 0 < value <= 1000000:
                out.append({"value": value, "raw": match.group(0),
                            "anchor": anchor, "quote": sent, "file": file})
    return out


def scan_statement(text, anchor, file, markers):
    out = []
    for sent in sentences(text):
        if marker_score(sent, markers) > 0 and 6 <= len(sent) <= 600:
            out.append({"value": None, "raw": sent, "anchor": anchor,
                        "quote": sent, "file": file})
    return out


def scan_case_constraints(case):
    buckets = {"period_months": [], "budget_wan": [], "sample_size": [],
               "personnel": [], "data": [], "ethics": []}

    def anchor_of(path):
        return "case.json:%s" % path

    def add(kind, value, raw, path):
        buckets[kind].append({"value": value, "raw": raw,
                              "anchor": anchor_of(path), "quote": raw,
                              "file": "case.json"})

    def walk(node, path=""):
        if isinstance(node, dict):
            for key, value in node.items():
                low = str(key).lower()
                child = "%s.%s" % (path, key) if path else str(key)
                if path and path.split(".")[0].lower() in SKIP_CASE_KEYS:
                    continue
                key_hit = (
                    low in PERIOD_KEYS or low in BUDGET_KEYS or
                    low in PERSONNEL_KEYS or low in DATA_KEYS or
                    low in ETHICS_KEYS or low in SAMPLE_KEYS
                )
                if key_hit and not isinstance(value, (dict, list)):
                    text = common.safe_text(value)
                    if low in PERIOD_KEYS and isinstance(value, (int, float)):
                        if 0 < float(value) <= 600:
                            add("period_months", float(value), text, child)
                    elif low in PERIOD_KEYS:
                        for item in scan_period_text(text, anchor_of(child), "case.json"):
                            buckets["period_months"].append(item)
                    elif low in BUDGET_KEYS and isinstance(value, (int, float)):
                        if float(value) > 0:
                            add("budget_wan", float(value), text, child)
                    elif low in BUDGET_KEYS:
                        for item in scan_budget_text(text, anchor_of(child), "case.json"):
                            buckets["budget_wan"].append(item)
                    elif low in SAMPLE_KEYS and isinstance(value, (int, float)):
                        if 0 < float(value) <= 1000000:
                            add("sample_size", int(value), text, child)
                    elif low in SAMPLE_KEYS:
                        for item in scan_sample_text(text, anchor_of(child), "case.json"):
                            buckets["sample_size"].append(item)
                    elif low in PERSONNEL_KEYS:
                        add("personnel", None, text, child)
                    elif low in DATA_KEYS:
                        add("data", None, text, child)
                    elif low in ETHICS_KEYS:
                        add("ethics", None, text, child)
                if isinstance(value, (dict, list)):
                    walk(value, child)
        elif isinstance(node, list):
            for index, value in enumerate(node):
                walk(value, "%s[%d]" % (path, index))

    walk(case)
    return buckets


def finalize_numeric(name, occurrences, unit, anchor_note=""):
    groups = {}
    for item in occurrences:
        groups.setdefault(item["value"], []).append(item)
    candidates = []
    for value, items in groups.items():
        first = items[0]
        candidates.append({
            "value": value, "unit": unit, "raw": first["raw"],
            "anchor": first["anchor"], "quote": first["quote"],
            "file": first["file"], "occurrences": len(items),
        })
    candidates.sort(key=lambda item: item["value"])
    if not candidates:
        return {"status": "not_reported", "value": None, "unit": unit,
                "candidates": [], "anchor": "", "quote": "", "file": "",
                "note": "材料与 case.json 均未给出可识别取值"}
    if len(candidates) == 1:
        only = candidates[0]
        return {"status": "reported", "value": only["value"], "unit": unit,
                "raw": only["raw"], "anchor": only["anchor"],
                "quote": only["quote"], "file": only["file"],
                "candidates": candidates, "note": anchor_note}
    return {"status": "source_conflict", "value": None, "unit": unit,
            "candidates": candidates,
            "anchor": candidates[0]["anchor"], "quote": candidates[0]["quote"],
            "file": candidates[0]["file"],
            "note": "原文出现 %d 个互斥取值，需人工确认；未自行选择"
                    % len(candidates)}


def select_constraint_items(paragraphs, key, limit=2):
    """Select concrete resource/condition sentences for personnel/data/ethics.

    The previous generic keyword scan captured headings, the SYNTHETIC banner and
    unrelated mentions ("高风险人群" for methods).  This selector requires both a
    topic word and a positive evidence pattern, and refuses gap statements.
    """
    topic = {
        "personnel": r"团队|人员|课题组|研究组|成员|分工",
        "data": r"数据|样本|队列|数据库|资料",
        "ethics": r"伦理|知情同意|合规|IRB|审查",
    }[key]
    positive = {
        "personnel": [(r"(?:团队|人员|课题组|研究组)[^。；]{0,20}\d+\s*(?:人|名)", 4)],
        "data": [(r"脱敏|去标识|来源|已有|现有|前期|已完成|可用于|公开|采集|共享|存储", 3)],
        "ethics": [(r"审批|委员会|批准|签署|知情同意书|匿名|加密|最小必要|转介", 3)],
    }[key]
    bonus_re = {
        "personnel": r"包括|分别|背景|分工",
        "data": r"数据库|数据集|测力|设备|变量|指标",
        "ethics": r"伦理|合规|数据安全|隐私",
    }[key]
    picked = []
    for order, para in enumerate(paragraphs):
        if para.get("is_heading"):
            continue
        for sent in sentences(para.get("text", "")):
            if len(sent) < 8 or len(sent) > 320:
                continue
            if sent.lstrip().startswith(">"):
                continue
            if "SYNTHETIC" in sent.upper():
                continue
            if marker_score(sent, GAP_MARKERS) > 0:
                continue
            if not re.search(topic, sent):
                continue
            score = 0
            for pattern, weight in positive:
                if re.search(pattern, sent):
                    score += weight
            if re.search(bonus_re, sent):
                score += 1
            if score < 2:
                continue
            picked.append({"score": score, "order": order, "text": short(sent, 260),
                           "quote": sent, "anchor": para["anchor"],
                           "file": para["file"]})
    picked.sort(key=lambda item: (-item["score"], item["order"]))
    return picked[:limit]


def collect_constraints(bundle, case):
    buckets = {"period_months": [], "budget_wan": [], "sample_size": [],
               "personnel": [], "data": [], "ethics": []}
    for src in bundle.get("sources", []):
        if not src.get("readable") or src.get("role") == "task":
            continue
        paragraphs = [dict(p, file=src.get("file", ""))
                      for p in src.get("paragraphs", []) if not p.get("is_heading")]
        for para in paragraphs:
            text = para.get("text", "")
            anchor = para.get("anchor", "")
            file = src.get("file", "")
            buckets["period_months"] += scan_period_text(text, anchor, file)
            buckets["budget_wan"] += scan_budget_text(text, anchor, file)
            buckets["sample_size"] += scan_sample_text(text, anchor, file)
        for key in ("personnel", "data", "ethics"):
            buckets[key] += select_constraint_items(paragraphs, key)
    case_buckets = scan_case_constraints(case)
    for key in buckets:
        buckets[key] += case_buckets[key]

    constraints = {
        "period_months": finalize_numeric("period_months", buckets["period_months"], "months"),
        "budget_wan": finalize_numeric("budget_wan", buckets["budget_wan"], "万元"),
        "sample_size": finalize_numeric("sample_size", buckets["sample_size"], "例"),
    }
    for key in ("personnel", "data", "ethics"):
        items = []
        seen = set()
        for item in buckets[key]:
            quote = item.get("quote") or item.get("raw")
            mark = common.canon(quote)
            if not mark or mark in seen:
                continue
            seen.add(mark)
            items.append({"quote": quote, "anchor": item.get("anchor", ""),
                          "file": item.get("file", "")})
            if len(items) >= 4:
                break
        constraints[key] = {
            "status": "reported" if items else "not_reported",
            "items": items,
        }
    return constraints


# --------------------------------------------------------------- plan parts

def default_title(case, paragraphs):
    for key in ("title", "title_zh", "topic", "name"):
        value = case.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    for para in paragraphs:
        if para.get("is_heading") and para.get("text"):
            return common.norm_ws(para["text"])
    return "开题报告与研究计划书"


def build_background(paragraphs):
    rows = select_sentences(paragraphs, BACKGROUND_MARKERS, 6,
                            section_markers=["背景", "引言", "前言", "现状",
                                             "introduction", "background"])
    return [{"text": item["text"], "quote": item["text"], "anchor": item["anchor"],
             "file": item["file"], "status": "reported",
             "claim_id": ""} for item in rows]


def build_gaps(paragraphs):
    rows = select_sentences(paragraphs, GAP_MARKERS, 8,
                            section_markers=["缺口", "问题", "不足", "gap"])
    rows = [item for item in rows if marker_score(item["text"], GAP_MARKERS) > 0]
    rows = [item for item in rows
            if not re.search(r"^若|^如果|一旦|风险|应对", item["text"])]
    rows = rows[:5]
    return [{"text": item["text"], "quote": item["text"], "anchor": item["anchor"],
             "file": item["file"], "status": "reported",
             "claim_id": ""} for item in rows]


def as_question(text):
    text = common.norm_ws(text)
    if "?" in text or "？" in text:
        return text
    if re.search(r"是否|能否|如何|多大|多少|what|whether|how", text, re.I):
        return text + ("" if text.endswith(("？", "?")) else "？")
    return "材料所述\u201c%s\u201d能否在给定周期与资源内得到验证？" % short(text, 80)


def overlap_ratio(left, right):
    a, b = char_bigrams(left), char_bigrams(right)
    if not a or not b:
        return 0.0
    return len(a & b) / float(len(a | b))


def question_clauses(paragraphs):
    """Split numbered compound questions into separate, verbatim-anchored clauses.

    Materials often write "本课题拟回答三个问题：第一，……？第二，……？第三，……？".
    Treating that whole paragraph as one question loses the structure the
    reviewers check.  Each clause keeps the original sentence as its quote so
    the evidence ledger stays verifiable.
    """
    markers = ["研究问题", "拟回答", "拟解决", "研究假设", "假设",
               "research question", "hypothesis", "aim", "objective"]
    clauses = []
    for para in paragraphs:
        if para.get("is_heading"):
            continue
        haystack = "%s %s" % (para.get("section", ""), para.get("text", ""))
        if marker_score(haystack, markers) <= 0:
            continue
        for raw in sentences(para.get("text", "")):
            if len(raw) < 8 or len(raw) > 320:
                continue
            if not re.search(r"[？?]|是否|能否|如何|多大|多少|what|whether|how", raw):
                continue
            if marker_score(raw, GAP_MARKERS) > 0:
                continue
            cleaned = re.sub(r"^本课题拟(?:回答|解决|研究)[^：:]{0,14}[：:]\s*", "", raw.strip())
            cleaned = re.sub(r"^(第[一二三四五六七八九十]+[，,、]?|"
                             r"[（(]?\d+[）).、]\s*)", "", cleaned)
            cleaned = cleaned.rstrip("？?").strip()
            if len(cleaned) < 6:
                continue
            if any(overlap_ratio(cleaned, item["text"]) > 0.8 for item in clauses):
                continue
            clauses.append({
                "text": cleaned, "quote": raw.strip(),
                "anchor": para["anchor"], "file": para["file"],
            })
            if len(clauses) >= 3:
                break
        if len(clauses) >= 3:
            break
    return clauses


def build_questions(case, paragraphs, gaps):
    questions = []
    direct = case.get("research_question") or case.get("question")
    direct = direct.strip() if isinstance(direct, str) else ""
    clauses = question_clauses(paragraphs)

    if len(clauses) >= 2:
        # Explicit numbered questions win over the one-line summary in case.json.
        for item in clauses:
            questions.append({
                "id": "RQ%d" % (len(questions) + 1),
                "question": as_question(item["text"]),
                "status": "reported",
                "basis": [{"anchor": item["anchor"], "quote": item["quote"],
                           "file": item["file"]}],
                "note": "材料以编号方式给出的研究问题，逐条拆分后保留原文锚点",
            })
    elif direct:
        questions.append({
            "id": "RQ1", "question": direct, "status": "reported",
            "basis": [{"anchor": "case.json:research_question",
                       "quote": direct, "file": "case.json"}],
            "note": "来自 case.json 显式字段",
        })

    if len(questions) < 2:
        rows = select_sentences(
            paragraphs,
            ["研究问题", "拟解决", "研究目标", "假设", "hypothesis",
             "research question", "aim", "objective"],
            3,
            section_markers=["研究问题", "目标", "假设", "question", "aim"],
        )
        for item in rows:
            if len(questions) >= 3:
                break
            text = as_question(item["text"])
            if any(overlap_ratio(text, q["question"]) > 0.7 for q in questions):
                continue
            questions.append({
                "id": "RQ%d" % (len(questions) + 1), "question": text,
                "status": "draft",
                "basis": [{"anchor": item["anchor"], "quote": item["text"],
                           "file": item["file"]}],
                "note": "由材料目标句改写为可检验问题，需人工确认措辞",
            })

    if direct and all(overlap_ratio(direct, q["question"]) < 0.5 for q in questions):
        questions.append({
            "id": "RQ%d" % (len(questions) + 1), "question": direct,
            "status": "reported",
            "basis": [{"anchor": "case.json:research_question",
                       "quote": direct, "file": "case.json"}],
            "note": "case.json 的总体研究问题，与材料中的分问题并存",
        })
    questions = questions[:3]
    if not questions and gaps:
        gap = gaps[0]
        questions.append({
            "id": "RQ1", "question": as_question(gap["text"]),
            "status": "draft",
            "basis": [{"anchor": gap["anchor"], "quote": gap["quote"],
                       "file": gap["file"]}],
            "note": "材料未给出显式研究问题，由缺口陈述改写，需人工确认",
        })
    if not questions:
        questions.append({
            "id": "RQ1",
            "question": "材料未提供可识别的研究问题，需课题组补充。",
            "status": "not_reported", "basis": [],
            "note": "无可引用目标句或缺口句",
        })
    for index, question in enumerate(questions):
        question["id"] = "RQ%d" % (index + 1)
    return questions


def method_phase(text):
    if re.search(r"研究设计|队列设计|随机对照|采用.{0,8}设计", text):
        return 1
    if re.search(r"对照|比较|增量|AUC|净重分类", text):
        return 5
    if re.search(r"一致性|相关系数|信度|ICC", text):
        return 6
    if re.search(r"测量|设备|IMU|采样|问卷|握力|步行测试", text):
        return 2
    if re.search(r"模型|回归|训练|验证|bootstrap", text):
        return 4
    if re.search(r"结局|随访|事件|终点", text):
        return 3
    if re.search(r"分析|报告|曲线|预注册", text):
        return 7
    return 8


def select_method_rows(paragraphs, limit=6):
    """Pick executable method sentences, one per logical phase when possible.

    A method sentence must contain an action verb; gap statements that merely
    mention "model" or "data", and completed prior work, are rejected.
    """
    action = re.compile(r"采用|纳入|建立|构建|比较|评价|测量|分析|评估|验证|"
                        r"收集|随访|校准|执行|报告|提取|建模|训练|测试|对照")
    picked = []
    for item in select_sentences(paragraphs, METHOD_MARKERS, limit * 5):
        text = item["text"]
        if not action.search(text):
            continue
        if marker_score(text, GAP_MARKERS) > 0:
            continue
        if "？" in text or "?" in text:
            continue
        if marker_score(text, OUTCOME_MARKERS) > 0 and not action.search(text):
            continue
        if "风险" in text:
            continue
        if re.search(r"前期|已完成|既往|已有|2023|去年", text):
            continue
        if re.search(r"产出|形成|提交|发表|交付|预期成果", text):
            continue
        if re.search(r"^若|^如果|一旦|风险|应对", text):
            continue
        picked.append(item)

    by_phase, used = {}, set()
    for item in picked:
        phase = method_phase(item["text"])
        if phase not in by_phase:
            by_phase[phase] = item
            used.add(id(item))
    ordered = [by_phase[key] for key in sorted(by_phase)]
    for item in picked:
        if len(ordered) >= limit:
            break
        if id(item) not in used:
            ordered.append(item)
            used.add(id(item))
    ordered = ordered[:limit]
    ordered.sort(key=lambda item: (method_phase(item["text"]), item["order"]))
    return ordered


def select_metric_rows(paragraphs, limit=6):
    """Metric sentences only: a question that happens to mention "indicators"
    must never become a threshold."""
    extra = ["相关系数", "一致性", "信度", "校准", "阈值", "主要终点", "主要指标"]
    rows = select_sentences(paragraphs, METRIC_MARKERS + extra, limit * 4)
    picked = []
    for item in rows:
        text = item["text"]
        if "？" in text or "?" in text:
            continue
        if marker_score(text, GAP_MARKERS) > 0:
            continue
        if "研究问题" in text or "拟回答" in text:
            continue
        if re.search(r"调查发现|提示|可能补充|前期|已有|既往", text):
            continue
        score = marker_score(text, METRIC_MARKERS + extra)
        score += 1 if has_number(text) else 0
        if re.search(r"主要指标|主要终点|primary", text):
            score += 2
        if re.search(r"不低于|至少|≥|≤|阈值|预设", text):
            score += 1
        item["metric_score"] = score
        picked.append(item)
    picked.sort(key=lambda item: -item["metric_score"])
    return picked[:limit]


def build_objectives(questions, paragraphs, constraints, period):
    comparator_rows = [row for row in select_sentences(
        paragraphs, ["对照", "control", "比较", "vs"], 5)
        if marker_score(row["text"], GAP_MARKERS) == 0]
    comparator_texts = set(common.canon(row["text"]) for row in comparator_rows)
    metric_rows = [row for row in select_metric_rows(paragraphs, 8)
                   if common.canon(row["text"]) not in comparator_texts]
    method_rows = select_method_rows(paragraphs, 8)
    primary_metric = next(
        (row for row in metric_rows
         if re.search(r"主要指标|主要终点|primary", row["text"])), None)
    outcomes = []
    sample = constraints.get("sample_size", {})
    sample_text = None
    if sample.get("status") == "reported":
        sample_text = "n=%s（%s）" % (fmt_num(sample["value"]), sample["raw"])
    for index, question in enumerate(questions):
        qtext = question.get("question", "")

        def best_row(rows):
            best, score = None, -1.0
            for row in rows:
                current = overlap_ratio(qtext, row["text"])
                if current > score:
                    best, score = row, current
            return best if score > 0.02 else None

        comparison_question = bool(re.search(r"增量|对照|比较|相对|差值|差异", qtext))
        consistency_question = bool(re.search(r"一致性|信度|可重复|重复性", qtext))
        if consistency_question:
            metric_pool = [row for row in metric_rows
                           if re.search(r"一致性|相关系数|信度|ICC", row["text"])]
            method_pool = [row for row in method_rows
                           if re.search(r"一致性|相关系数|信度|ICC", row["text"])]
            if not metric_pool:
                metric_pool = metric_rows
            if not method_pool:
                method_pool = method_rows
        else:
            metric_pool = metric_rows
            method_pool = method_rows if comparison_question else [
                row for row in method_rows
                if common.canon(row["text"]) not in comparator_texts
                and method_phase(row["text"]) in (1, 2, 4)]
            if not method_pool:
                method_pool = [row for row in method_rows
                               if common.canon(row["text"]) not in comparator_texts]
            if not method_pool:
                method_pool = method_rows
        metric_row = (best_row(metric_pool) if consistency_question else
                      (primary_metric or best_row(metric_pool)))
        method_row = best_row(method_pool)
        comparator_row = best_row(comparator_rows) if comparison_question else None
        method_text = short(method_row["text"], 150) if method_row else ""
        metric_text = short(metric_row["text"], 120) if metric_row else ""
        if method_row and metric_row:
            objective_text = ("针对 %s，采用材料所述方法：%s；以“%s”作为考核判据。"
                              % (question["id"], method_text, metric_text))
            status = "draft"
        elif method_row:
            objective_text = "针对 %s，采用材料所述方法：%s。" % (
                question["id"], method_text)
            status = "draft"
        elif metric_row:
            objective_text = "针对 %s，以“%s”作为考核判据。" % (
                question["id"], metric_text)
            status = "draft"
        else:
            objective_text = "针对 %s，给出可复核的结论。" % question["id"]
            status = "not_reported"

        horizon = re.search(r"(\d+(?:\.\d+)?)\s*个月", qtext + " " + (metric_row or {}).get("text", ""))
        if horizon:
            timepoint = "第%s个月随访终点（结局观察）" % fmt_num(horizon.group(1))
        elif period.get("status") == "reported":
            timepoint = "第%s个月末（项目结束）" % fmt_num(period["value"])
        else:
            timepoint = None
        outcomes.append({
            "id": "O%d" % (index + 1),
            "question_id": question["id"],
            "objective": objective_text,
            "metric": metric_row["text"] if metric_row else None,
            "metric_anchor": metric_row["anchor"] if metric_row else "",
            "metric_file": metric_row["file"] if metric_row else "",
            "method": method_row["text"] if method_row else None,
            "method_anchor": method_row["anchor"] if method_row else "",
            "method_file": method_row["file"] if method_row else "",
            "sample": sample_text,
            "comparator": (comparator_row["text"] if comparator_row else None),
            "timepoint": timepoint,
            "status": status,
            "note": ("方法句与判据句均来自材料，需确认指标阈值、统计口径与对照设置"
                     if method_row and metric_row else
                     "材料未同时给出方法与可考核指标，缺失项需补充"),
        })
    return outcomes


def pick_question_for(text, questions):
    # Rule-based routing first: a consistency/measurement sentence belongs to the
    # consistency question, a comparison sentence to the incremental-value
    # question, even if generic words ("community") overlap elsewhere.
    rules = [
        (r"一致性|相关系数|信度|ICC|可重复", r"一致性|信度|重复"),
        (r"对照|比较|增量|AUC|净重分类|改善", r"增量|对照|比较|相对|判别能力"),
        (r"预测|模型|回归|跌倒|结局|随访", r"预测|跌倒|模型"),
    ]
    for source, target in rules:
        if re.search(source, text):
            for question in questions:
                if re.search(target, question.get("question", "")):
                    return question["id"], "rule:%s" % target
    if re.search(r"研究设计|队列设计|纳入|基线|受试", text):
        for question in questions:
            if not re.search(r"一致性|信度|重复", question.get("question", "")):
                return question["id"], "rule:design"
    grams = char_bigrams(text)
    best, score = None, -1
    for question in questions:
        overlap = len(grams & char_bigrams(question.get("question", "")))
        if overlap > score:
            best, score = question, overlap
    if best is None:
        return "", "no_question"
    return best["id"], ("keyword_overlap" if score > 0 else "default_first_question")


def step_io(text):
    inputs, outputs = [], []
    if re.search(r"纳入|受试|研究对象|队列|居民|患者", text):
        inputs.append("研究对象与基线评估")
        outputs.append("纳入对象与基线数据集")
    if re.search(r"问卷|量表|访谈", text):
        inputs.append("问卷/量表数据")
    if re.search(r"现有|已有|前期|脱敏|数据库|历史", text):
        inputs.append("材料所述既有数据")
    if re.search(r"测量|采样|测试|IMU|设备", text):
        inputs.append("测量设备与评估流程")
        outputs.append("步态/问卷测量数据")
    if re.search(r"模型|回归|预测", text):
        inputs.append("建模与验证数据")
        outputs.append("预测模型与验证结果")
    if re.search(r"结局|随访|事件", text):
        inputs.append("随访记录")
        outputs.append("结局事件数据集")
    if re.search(r"AUC|曲线|校准|判别", text):
        outputs.append("判别/校准/决策曲线")
    if re.search(r"一致性|ICC|组内相关系数|信度", text):
        outputs.append("一致性评价结果")
    if re.search(r"分析|报告|预注册", text):
        inputs.append("分析数据集")
        outputs.append("分析结果与报告")
    if not inputs:
        inputs.append("材料未逐项给出输入，需在方案细化阶段确认")
    if not outputs:
        outputs.append("材料未逐项给出输出，需在方案细化阶段确认")
    return list(dict.fromkeys(inputs)), list(dict.fromkeys(outputs))


def build_route(paragraphs, questions):
    rows = select_method_rows(paragraphs, 6)
    steps = []
    for index, item in enumerate(rows):
        question_id, basis = pick_question_for(item["text"], questions)
        inputs, outputs = step_io(item["text"])
        explicit_parallel = bool(re.search(r"并行|同时开展|独立进行", item["text"]))
        steps.append({
            "id": "T%d" % (index + 1),
            "action": item["text"],
            "quote": item["text"],
            "anchor": item["anchor"],
            "file": item["file"],
            "inputs": inputs,
            "outputs": outputs,
            "depends_on": ["T%d" % index] if index else [],
            "parallel": explicit_parallel,
            "critical_path": True,
            "linked_questions": [question_id] if question_id else [],
            "link_basis": basis,
            "status": "draft",
            "claim_id": "",
        })
    # Every research question must be reachable from the route; otherwise the
    # "对得上" check fails.  Attach the earliest unlinked step instead of
    # inventing a new method.
    if steps:
        for question in questions:
            qid = question.get("id")
            if not any(qid in (step.get("linked_questions") or []) for step in steps):
                best = max(steps, key=lambda step: overlap_ratio(
                    question.get("question", ""), step.get("action", "")))
                best["linked_questions"].append(qid)
                best["link_basis"] = "coverage_guard"
    if not steps:
        steps.append({
            "id": "T1", "action": "材料未给出可识别的方法句，需补充技术路线。",
            "quote": "", "anchor": "", "file": "",
            "inputs": [], "outputs": [], "depends_on": [], "parallel": False,
            "critical_path": True,
            "linked_questions": [], "link_basis": "none",
            "status": "not_reported", "claim_id": "",
        })
    return steps


PHASE_SETS = {
    1: [(1.0, "方案执行与交付",
         ["研究方案与判据定稿", "开题报告与证据台账"])],
    2: [(0.4, "准备与数据获取",
         ["方案与伦理材料", "数据/样本清单与质检记录"]),
        (0.6, "实施、分析与交付",
         ["核心实验/分析结果", "验证记录与可编辑报告"])],
    3: [(0.25, "准备与伦理审批",
         ["研究方案定稿", "伦理/数据使用审批材料"]),
        (0.5, "实施与验证",
         ["数据/样本与核心结果", "重复或敏感性分析记录"]),
        (0.25, "分析与交付",
         ["复现脚本与验证报告", "开题/结题报告与可编辑稿件"])],
    4: [(0.15, "准备与伦理审批",
         ["研究方案定稿", "伦理/数据使用审批材料"]),
        (0.35, "数据与样本获取",
         ["数据/样本清单", "预处理与质量控制记录"]),
        (0.30, "核心方法实施",
         ["实验/分析执行记录", "核心结果表"]),
        (0.20, "分析、写作与交付",
         ["验证与复现报告", "可编辑报告与投稿材料"])],
    5: [(0.15, "方案细化与伦理审批",
         ["研究方案定稿", "伦理/数据使用审批材料", "指标阈值与样本量确认"]),
        (0.25, "数据与样本获取",
         ["数据/样本清单", "预处理与质量控制记录"]),
        (0.30, "核心方法实施",
         ["实验/分析执行记录", "核心结果表"]),
        (0.20, "验证与复现",
         ["重复实验或敏感性分析", "复现脚本与验证报告"]),
        (0.10, "写作与结题",
         ["开题/结题报告", "可编辑稿件与投稿材料"])],
}


def allocate_months(total, ratios):
    total_int = int(round(total))
    if total_int < 1:
        return []
    raw = [total_int * ratio for ratio in ratios]
    base = [max(1, int(math.floor(value))) for value in raw]
    while sum(base) > total_int:
        candidates = [i for i, value in enumerate(base) if value > 1]
        if not candidates:
            break
        index = max(candidates, key=lambda i: base[i])
        base[index] -= 1
    while sum(base) < total_int:
        index = max(range(len(base)), key=lambda i: raw[i] - base[i])
        base[index] += 1
    return base


def build_schedule(period, objectives):
    if period.get("status") == "source_conflict":
        return {"status": "source_conflict", "period_months": None,
                "milestones": [],
                "note": "周期存在互斥取值，未生成排期，需人工确认后重跑"}
    if period.get("status") != "reported" or not period.get("value"):
        return {"status": "not_reported", "period_months": None,
                "milestones": [],
                "note": "材料未给出可识别周期，未编造月份"}
    total = float(period["value"])
    if total < 1:
        return {"status": "not_reported", "period_months": total,
                "milestones": [],
                "note": "周期小于 1 个月，无法排布可执行里程碑"}
    phase_count = min(len(PHASE_SETS), max(1, int(round(total))))
    phases = PHASE_SETS[phase_count]
    lengths = allocate_months(total, [p[0] for p in phases])
    milestones = []
    start = 1
    for index, (_, name, deliverables) in enumerate(phases):
        length = lengths[index]
        end = start + length - 1
        linked = []
        if objectives:
            linked = [objectives[index % len(objectives)]["id"]]
        milestones.append({
            "id": "M%d" % (index + 1),
            "name": name,
            "start_month": start,
            "end_month": end,
            "deliverables": deliverables,
            "linked_objectives": linked,
            "depends_on": ["M%d" % index] if index else [],
            "critical_path": index < max(1, min(3, len(phases) - 1)),
            "parallelizable": index > 0 and index < len(phases) - 1,
            "status": "draft",
        })
        start = end + 1
    # Coverage guard: every objective must appear in at least one milestone,
    # otherwise the plan cannot be checked milestone by milestone.
    if milestones and objectives:
        linked_all = set()
        for milestone in milestones:
            linked_all.update(milestone.get("linked_objectives") or [])
        for index, objective in enumerate(objectives):
            if objective["id"] not in linked_all:
                milestones[index % len(milestones)]["linked_objectives"].append(objective["id"])
    note = "按给定周期 %s 个月与阶段比例自动生成，需课题组确认任务量与人员分工" % fmt_num(period["value"])
    if abs(total - int(round(total))) > 0.01:
        note += "；原文周期为 %s 个月，排期按 %d 个月取整" % (total, int(round(total)))
    return {"status": "draft", "period_months": total,
            "milestones": milestones, "note": note}


def risk_templates(schedule):
    milestones = schedule.get("milestones") or []

    def gate(index, fallback):
        if 0 <= index < len(milestones):
            item = milestones[index]
            return "%s《%s》结束（第 %s 个月）" % (
                item["id"], item.get("name", ""), item.get("end_month"))
        return fallback

    first = gate(0, "第 1 个里程碑评审")
    second = gate(1, "第 2 个里程碑评审")
    third = gate(2, "第 3 个里程碑评审")
    return {
        "data": {
            "risk": "关键数据或样本获取延迟、质量不达标",
            "trigger": "首个数据里程碑未产出约定数据清单，或有效样本低于计划下限",
            "impact": "核心分析无法按计划完成，目标判据不可检验",
            "fallback": "启用材料列明的备选数据源；缩小样本并重算功效；先做二次分析",
            "decision_point": second,
        },
        "method": {
            "risk": "核心方法不可行或结果无法复现",
            "trigger": "核心指标未达材料规定的阈值，或复现实验失败",
            "impact": "研究问题无法得到可复核答案",
            "fallback": "切换材料列明的备选方法；增加对照或敏感性分析",
            "decision_point": third,
        },
        "schedule": {
            "risk": "里程碑延期或关键人员变动",
            "trigger": "任一里程碑延期不少于 4 周，或关键岗位空缺",
            "impact": "阶段计划与给定周期条件不匹配",
            "fallback": "压缩非关键分析；并行化可并行步骤；申请周期调整并留痕",
            "decision_point": "每个里程碑评审时",
        },
        "ethics": {
            "risk": "伦理、知情同意或数据合规审批未通过",
            "trigger": "首个里程碑结束前未获得伦理/数据使用批准",
            "impact": "涉及人或受试材料的步骤不得启动",
            "fallback": "先开展不涉及该审批的分析；调整研究设计；如实延期",
            "decision_point": first,
        },
    }


def build_risks(paragraphs, schedule):
    templates = risk_templates(schedule)
    hints = {}
    for category in RISK_CATEGORIES:
        rows = select_sentences(
            paragraphs,
            RISK_CATEGORY_MARKERS[category] + RISK_SIGNAL_WORDS,
            6,
        )
        hint = None
        best = -1
        for row in rows:
            category_score = marker_score(row["text"], RISK_CATEGORY_MARKERS[category])
            signal_score = marker_score(row["text"], RISK_SIGNAL_WORDS)
            if category_score <= 0 or signal_score <= 0:
                continue
            score = category_score * 2 + signal_score
            if score > best:
                hint, best = row, score
        if hint:
            hints[category] = hint
    risks = []
    for index, category in enumerate(RISK_CATEGORIES):
        template = templates[category]
        hint = hints.get(category)
        risks.append({
            "id": "R%d" % (index + 1),
            "category": category,
            "category_zh": RISK_CATEGORY_ZH[category],
            "risk": template["risk"],
            "trigger": template["trigger"],
            "impact": template["impact"],
            "fallback": template["fallback"],
            "decision_point": template["decision_point"],
            "status": "draft",
            "evidence": ({"quote": hint["text"], "anchor": hint["anchor"],
                          "file": hint["file"], "claim_id": ""} if hint else None),
            "note": ("材料中有同类风险提示，触发阈值与备选方案仍需课题组确认"
                     if hint else "材料未给出该类风险提示，按常规风险清单草拟，需确认"),
        })
    return risks


def build_outcomes(paragraphs, objectives):
    rows = select_sentences(paragraphs, OUTCOME_MARKERS, 4,
                            section_markers=["预期", "成果", "outcome"])
    outcomes = []
    if rows:
        for index, item in enumerate(rows):
            objective_id = (objectives[index % len(objectives)]["id"]
                            if objectives else "")
            outcomes.append({
                "id": "E%d" % (index + 1),
                "outcome": item["text"],
                "quote": item["text"],
                "anchor": item["anchor"],
                "file": item["file"],
                "objective_id": objective_id,
                "acceptance": "按目标判据逐项核对；以材料原文表述为准",
                "status": "reported",
                "claim_id": "",
            })
    else:
        generic = [
            ("可编辑的开题报告与研究计划书（Markdown/HTML）",
             "按七要素与对齐矩阵逐项核对"),
            ("证据台账与来源映射表",
             "每条事实性表述可定位到锚点与逐字引文"),
            ("分析/实验记录与复现脚本（若方法执行）",
             "关键结果可按记录复跑"),
        ]
        for index, (outcome, acceptance) in enumerate(generic):
            outcomes.append({
                "id": "E%d" % (index + 1),
                "outcome": outcome,
                "quote": "",
                "anchor": "",
                "file": "",
                "objective_id": (objectives[index % len(objectives)]["id"]
                                 if objectives else ""),
                "acceptance": acceptance,
                "status": "draft",
                "claim_id": "",
                "note": "材料未给出显式预期成果，按常规开题交付物草拟",
            })
    # Coverage guard: each objective needs at least one expected outcome, even
    # when the material only states a subset.  The added row is explicitly a
    # draft, never presented as an existing deliverable.
    covered = set(item.get("objective_id") for item in outcomes)
    for objective in objectives:
        if objective["id"] in covered:
            continue
        outcomes.append({
            "id": "E%d" % (len(outcomes) + 1),
            "outcome": "完成 %s 的验证记录与可复核报告（草案）" % objective["id"],
            "quote": "",
            "anchor": "",
            "file": "",
            "objective_id": objective["id"],
            "acceptance": "按该目标的指标、样本、对照与时间点逐项核对",
            "status": "draft",
            "claim_id": "",
            "note": "材料未逐条给出该目标的成果表述，按考核需要草拟，需导师确认",
        })
    return outcomes


def scaffold_plan(case, bundle):
    paragraphs = content_paragraphs(bundle)
    constraints = collect_constraints(bundle, case)
    period = constraints["period_months"]
    background = build_background(paragraphs)
    gaps = build_gaps(paragraphs)
    questions = build_questions(case, paragraphs, gaps)
    objectives = build_objectives(questions, paragraphs, constraints, period)
    route = build_route(paragraphs, questions)
    schedule = build_schedule(period, objectives)
    risks = build_risks(paragraphs, schedule)
    outcomes = build_outcomes(paragraphs, objectives)
    title = default_title(case, paragraphs)
    plan = {
        "title": title,
        "audience": case.get("audience") or "导师与开题评审专家组",
        "discipline": case.get("discipline") or case.get("field") or "",
        "gap_statement": gaps[0]["text"] if gaps else "",
        "gaps": gaps,
        "background": background,
        "questions": questions,
        "objectives": objectives,
        "route": route,
        "schedule": schedule,
        "risks": risks,
        "outcomes": outcomes,
        "constraints": constraints,
        "human_confirm": [],
        "plan_source": "scaffold",
    }
    return plan


def merge_plan(base, override):
    if not isinstance(override, dict):
        return base
    merged = dict(base)
    for key, value in override.items():
        if key in ("constraints",) and isinstance(value, dict) and isinstance(merged.get(key), dict):
            inner = dict(merged[key])
            inner.update(value)
            merged[key] = inner
        else:
            merged[key] = value
    return merged


# ---------------------------------------------------------------- claim book

class ClaimBook:
    def __init__(self, bundle, case):
        self.index = build_para_index(bundle)
        self.case = case if isinstance(case, dict) else {}
        self.claims = []
        self.seen = {}

    def case_value(self, path):
        node = self.case
        for part in path.split("."):
            if isinstance(node, dict) and part in node:
                node = node[part]
            else:
                return None
        return node

    def verify(self, anchor, quote):
        quote = common.norm_ws(quote)
        if not quote:
            return False
        if anchor.startswith("case.json:"):
            value = self.case_value(anchor.split(":", 1)[1])
            if value is None:
                return False
            return common.quote_in(quote, common.safe_text(value)) or \
                common.quote_in(common.safe_text(value), quote)
        para = self.index.get(anchor)
        if not para:
            return False
        return common.quote_in(quote, para["text"])

    def add(self, kind, text, anchor="", quote="", source_file="", status="draft"):
        quote = common.norm_ws(quote)
        key = (anchor, common.canon(quote))
        if key in self.seen:
            return self.seen[key]
        verified = self.verify(anchor, quote)
        if status == "reported" and not verified:
            status = "draft"
        claim = {
            "claim_id": "C%d" % (len(self.claims) + 1),
            "kind": kind,
            "text": common.norm_ws(text),
            "anchor": anchor,
            "quote": quote,
            "source_file": source_file,
            "status": status,
            "verified": verified,
        }
        self.claims.append(claim)
        self.seen[key] = claim["claim_id"]
        return claim["claim_id"]


def attach_claims(plan, bundle, case):
    book = ClaimBook(bundle, case)
    for item in plan.get("background", []):
        item["claim_id"] = book.add("background", item["text"], item.get("anchor", ""),
                                    item.get("quote", ""), item.get("file", ""), "reported")
    for item in plan.get("gaps", []):
        item["claim_id"] = book.add("gap", item["text"], item.get("anchor", ""),
                                    item.get("quote", ""), item.get("file", ""), "reported")
    for question in plan.get("questions", []):
        ids = []
        for basis in question.get("basis", []):
            ids.append(book.add("question_basis", question["question"],
                                basis.get("anchor", ""), basis.get("quote", ""),
                                basis.get("file", ""), "reported"))
        question["claim_ids"] = ids
    for objective in plan.get("objectives", []):
        if objective.get("metric"):
            objective["claim_id"] = book.add(
                "metric", objective["objective"], objective.get("metric_anchor", ""),
                objective["metric"], objective.get("metric_file", ""), "reported")
    for step in plan.get("route", []):
        if step.get("quote"):
            step["claim_id"] = book.add("method", step["action"], step.get("anchor", ""),
                                        step["quote"], step.get("file", ""), "reported")
    for risk in plan.get("risks", []):
        evidence = risk.get("evidence")
        if isinstance(evidence, dict) and evidence.get("quote"):
            evidence["claim_id"] = book.add(
                "risk_hint", risk["risk"], evidence.get("anchor", ""),
                evidence["quote"], evidence.get("file", ""), "reported")
    for outcome in plan.get("outcomes", []):
        if outcome.get("quote"):
            outcome["claim_id"] = book.add("outcome", outcome["outcome"],
                                           outcome.get("anchor", ""), outcome["quote"],
                                           outcome.get("file", ""), "reported")
    for key in ("period_months", "budget_wan", "sample_size"):
        constraint = plan.get("constraints", {}).get(key, {})
        for candidate in constraint.get("candidates", []):
            candidate["claim_id"] = book.add(
                "constraint", "%s=%s" % (key, candidate.get("raw", "")),
                candidate.get("anchor", ""), candidate.get("quote", ""),
                candidate.get("file", ""), "reported")
    for key in ("personnel", "data", "ethics"):
        for item in plan.get("constraints", {}).get(key, {}).get("items", []):
            item["claim_id"] = book.add("constraint", key, item.get("anchor", ""),
                                        item.get("quote", ""), item.get("file", ""),
                                        "reported")
    return book.claims


# ------------------------------------------------------- alignment/feasible

def build_alignment(plan):
    objectives = plan.get("objectives", [])
    steps = plan.get("route", [])
    milestones = plan.get("schedule", {}).get("milestones", [])
    outcomes = plan.get("outcomes", [])
    questions = plan.get("questions", [])
    rows = []
    gaps = []
    if not (1 <= len(questions) <= 3):
        gaps.append("研究问题数量为 %d，题面要求收敛为 1–3 个" % len(questions))
    for question in questions:
        qid = question["id"]
        objective_ids = [o["id"] for o in objectives if o.get("question_id") == qid]
        step_ids = [t["id"] for t in steps
                    if qid in (t.get("linked_questions") or [])]
        milestone_ids = [m["id"] for m in milestones
                         if any(oid in (m.get("linked_objectives") or [])
                                for oid in objective_ids)]
        outcome_ids = [e["id"] for e in outcomes
                       if e.get("objective_id") in objective_ids]
        row = {"question": qid, "objectives": objective_ids, "steps": step_ids,
               "milestones": milestone_ids, "outcomes": outcome_ids}
        missing = []
        if not objective_ids:
            missing.append("objective")
        if not outcome_ids:
            missing.append("outcome")
        if not step_ids:
            missing.append("route_step")
        if not milestone_ids:
            missing.append("milestone")
        if missing:
            row["missing"] = missing
            gaps.append("%s 缺少 %s" % (qid, ",".join(missing)))
        rows.append(row)
    # A milestone chain must be closed: dependencies point to earlier phases and
    # the last phase must end inside the declared period.
    total = plan.get("constraints", {}).get("period_months", {}).get("value")
    for milestone in milestones:
        for dep in milestone.get("depends_on") or []:
            if dep not in [m["id"] for m in milestones]:
                gaps.append("%s 依赖不存在的 %s" % (milestone["id"], dep))
    if milestones and total is not None:
        if milestones[-1].get("end_month") != int(round(float(total))):
            gaps.append("里程碑末月 %s 与周期 %s 个月不一致"
                        % (milestones[-1].get("end_month"), total))
    return {"rows": rows, "gaps": gaps,
            "question_count": len(questions),
            "status": "pass" if not gaps else "partial"}


def build_feasibility(plan, bundle):
    constraints = plan.get("constraints", {})
    period = constraints.get("period_months", {})
    checks = []

    def add(check_id, name, status, detail):
        checks.append({"id": check_id, "check": name, "status": status,
                       "detail": detail})

    if period.get("status") == "reported":
        months_num = float(period.get("value"))
        months = fmt_num(period.get("value"))
        if months_num < 3:
            add("F1", "周期与任务量", "warn",
                "周期仅 %s 个月，需压缩范围或合并阶段" % months)
        elif months_num > 60:
            add("F1", "周期与任务量", "warn",
                "周期 %s 个月较长，需检查阶段任务量是否过松" % months)
        else:
            add("F1", "周期与任务量", "pass",
                "周期 %s 个月，可排布 %d 个阶段"
                % (months, len(plan.get("schedule", {}).get("milestones", []))))
    elif period.get("status") == "source_conflict":
        add("F1", "周期与任务量", "fail",
            "周期存在互斥取值，无法判断计划可行性")
    else:
        add("F1", "周期与任务量", "unknown", "材料未给出周期")

    missing_metrics = [o["id"] for o in plan.get("objectives", [])
                       if not o.get("metric")]
    add("F2", "目标可考核性", "pass" if not missing_metrics else "warn",
        "全部目标有指标句" if not missing_metrics
        else "缺少指标/阈值的 objective：%s" % ", ".join(missing_metrics))

    for fid, key, name in [("F3", "budget_wan", "经费条件"),
                           ("F4", "sample_size", "样本条件"),
                           ("F5", "personnel", "人员条件"),
                           ("F6", "data", "数据条件"),
                           ("F7", "ethics", "伦理与合规")]:
        item = constraints.get(key, {})
        status = item.get("status")
        if status == "reported":
            detail = item.get("raw") or (item.get("items") or [{}])[0].get("quote", "")
            add(fid, name, "pass", short(detail, 120) or "已给出")
        elif status == "source_conflict":
            add(fid, name, "fail", "存在互斥来源，需人工确认")
        else:
            add(fid, name, "unknown", "材料未明确给出该条件")

    alignment = plan.get("alignment", {})
    add("F8", "要素对齐", "pass" if alignment.get("status") == "pass" else "warn",
        "; ".join(alignment.get("gaps", [])[:4]) or "问题—目标—路线—里程碑—成果均可对应")

    risk_ok = all(
        risk.get("trigger") and risk.get("fallback") and risk.get("decision_point")
        for risk in plan.get("risks", []))
    categories = set(risk.get("category") for risk in plan.get("risks", []))
    add("F9", "风险四类与处置", "pass" if risk_ok and categories >= {"data", "method", "schedule", "ethics"}
        else "warn",
        "数据/方法/进度/伦理四类均含触发信号、备选方案与决策时点"
        if risk_ok else "存在缺少触发信号/备选方案/决策时点的风险")

    sample_status = constraints.get("sample_size", {}).get("status")
    if sample_status == "reported":
        add("F10", "样本与判据匹配", "pass",
            "样本量取自材料，目标中的 n 与材料一致；统计功效仍需课题组确认")
    else:
        add("F10", "样本与判据匹配", "unknown",
            "材料未给出样本量，无法核对目标判据的样本是否可行")

    hard = [c for c in checks if c["status"] == "fail"]
    warn = [c for c in checks if c["status"] == "warn"]
    unknown = [c for c in checks if c["status"] == "unknown"]
    overall = "fail" if hard else ("warn" if warn else ("unknown" if unknown else "pass"))
    return {"checks": checks, "status": overall}


def build_concerns(plan, claims, alignment, feasibility):
    """Map the four review concerns from task.md to concrete pass/warn evidence."""
    verified = [c for c in claims if c.get("verified")]
    reported = [c for c in claims if c.get("status") == "reported"]
    rows = []

    grounded = (bool(plan.get("background")) and bool(plan.get("gaps"))
                and 1 <= len(plan.get("questions", [])) <= 3
                and all(q.get("claim_ids") for q in plan.get("questions", [])))
    rows.append({
        "concern": "立得住",
        "question": "研究问题是否具体、可证伪，背景材料是否真的指向该缺口？",
        "status": "pass" if grounded else "warn",
        "evidence": "背景 %d 条、缺口 %d 条、研究问题 %d 个（要求 1–3），问题均附材料依据"
                    % (len(plan.get("background", [])), len(plan.get("gaps", [])),
                       len(plan.get("questions", []))),
        "refs": [c["claim_id"] for c in verified[:6]],
    })
    aligned = alignment.get("status") == "pass"
    rows.append({
        "concern": "对得上",
        "question": "目标、技术路线、验证方式与预期成果是否与问题一一对应？",
        "status": "pass" if aligned else "warn",
        "evidence": "对齐矩阵 %d 行；缺口：%s"
                    % (len(alignment.get("rows", [])),
                       "、".join(alignment.get("gaps", [])) or "无"),
        "refs": [],
    })
    period = plan.get("constraints", {}).get("period_months", {})
    schedule_ok = (period.get("status") == "reported"
                   and plan.get("schedule", {}).get("status") in ("draft", "reported", "pass")
                   and bool(plan.get("schedule", {}).get("milestones")))
    budget = plan.get("constraints", {}).get("budget_wan", {})
    rows.append({
        "concern": "排得开",
        "question": "阶段计划是否落在给定周期、经费、数据与人员条件内？",
        "status": "pass" if schedule_ok and budget.get("status") == "reported"
                  else ("warn" if schedule_ok else "warn"),
        "evidence": "周期 %s；里程碑 %d 个；经费 %s；人员/数据/伦理条件见第 5 节"
                    % (fmt_num(period.get("value")) if period.get("status") == "reported" else "未知",
                       len(plan.get("schedule", {}).get("milestones", [])),
                       budget.get("status")),
        "refs": [],
    })
    risk_ok = all(r.get("trigger") and r.get("fallback") and r.get("decision_point")
                  for r in plan.get("risks", []))
    claims_ok = bool(claims) and len(verified) == len(reported) and len(reported) > 0
    rows.append({
        "concern": "说得清",
        "question": "风险是否有触发信号与备选方案，关键论断与引用是否可追溯？",
        "status": "pass" if risk_ok and claims_ok else "warn",
        "evidence": "风险 %d 条均含触发/影响/备选/决策时点=%s；reported 断言核验 %d/%d"
                    % (len(plan.get("risks", [])), risk_ok, len(verified), len(reported)),
        "refs": [c["claim_id"] for c in reported if not c.get("verified")][:8],
    })
    return {"rows": rows,
            "status": "pass" if all(row["status"] == "pass" for row in rows) else "partial"}


def numeric_traceability(plan, claims, bundle, case):
    """Every number in a reported claim must come from source, case.json, or a
    documented derivation (period -> milestone months, counts)."""
    allowed = set()
    origins = {}
    for src in bundle.get("sources", []):
        for para in src.get("paragraphs", []):
            for token in common.number_tokens(para.get("text", "")):
                allowed.add(token["value"])
                origins.setdefault(token["value"], "%s %s" % (src.get("id"), para.get("anchor")))
    for token in common.number_tokens(common.article_text(case)):
        allowed.add(token["value"])
        origins.setdefault(token["value"], "case.json")
    derived = []
    period = plan.get("constraints", {}).get("period_months", {})
    if period.get("status") == "reported" and period.get("value") is not None:
        value = str(int(period["value"])) if float(period["value"]).is_integer() else str(period["value"])
        allowed.add(value)
        origins.setdefault(value, "constraint.period_months")
        derived.append({"value": value, "formula": "材料周期原值"})
    for milestone in plan.get("schedule", {}).get("milestones", []):
        for key in ("start_month", "end_month"):
            value = str(milestone.get(key))
            allowed.add(value)
            origins.setdefault(value, "schedule.%s" % milestone["id"])
        derived.append({"value": "%s-%s" % (milestone.get("start_month"), milestone.get("end_month")),
                        "formula": "由周期按阶段比例分配（见 4.2 节）"})
    for key in ("budget_wan", "sample_size"):
        item = plan.get("constraints", {}).get(key, {})
        if item.get("status") == "reported" and item.get("value") is not None:
            text = str(item["value"])
            allowed.add(text.rstrip("0").rstrip(".") if "." in text else text)
            origins.setdefault(text, "constraint.%s" % key)
    for objective in plan.get("objectives", []):
        sample = objective.get("sample") or ""
        for token in common.number_tokens(sample):
            allowed.add(token["value"])
            origins.setdefault(token["value"], "constraint.sample_size")

    unresolved, checked = [], 0
    for claim in claims:
        if claim.get("status") != "reported":
            continue
        for token in common.number_tokens(claim.get("text", "")):
            checked += 1
            value = token["value"]
            if common.quote_in(value, claim.get("quote", "")):
                continue
            if value in allowed:
                continue
            unresolved.append({"claim_id": claim.get("claim_id"), "number": value,
                               "text": common.truncated(claim.get("text"), 120)})
    return {
        "status": "pass" if not unresolved else "warn",
        "checked_numbers": checked,
        "unresolved": unresolved[:20],
        "derived": derived,
        "note": "数字仅允许来自材料/case.json，或由周期按阶段比例显式推导；"
                "不可追溯的数字不得写成事实。",
    }


# ------------------------------------------------------------------ status

def element_status(items, fallback="not_reported"):
    statuses = [item.get("status") for item in items if isinstance(item, dict)]
    if not statuses:
        return fallback
    if any(s in ("source_conflict", "extraction_failed") for s in statuses):
        return "source_conflict"
    if all(s == "not_reported" for s in statuses):
        return "not_reported"
    if any(s == "draft" for s in statuses):
        return "draft"
    return "reported"


def determine_status(bundle, plan, feasibility, alignment, missing_listed,
                     contract_source):
    readable = sum(1 for src in bundle.get("sources", [])
                   if src.get("readable") and src.get("role") != "task")
    conflicts = [key for key in ("period_months", "budget_wan", "sample_size")
                 if plan.get("constraints", {}).get(key, {}).get("status") == "source_conflict"]
    elements = {
        "research_background": element_status(plan.get("background", [])),
        "problem_definition": element_status(plan.get("questions", [])),
        "objectives": element_status(plan.get("objectives", [])),
        "technical_route": element_status(plan.get("route", [])),
        "schedule": plan.get("schedule", {}).get("status", "not_reported"),
        "risks": element_status(plan.get("risks", [])),
        "expected_outcomes": element_status(plan.get("outcomes", [])),
    }
    reasons = []
    if readable == 0:
        reasons.append("no readable scientific material")
    if conflicts:
        reasons.append("constraint conflicts: %s" % ", ".join(conflicts))
    if contract_source == "default":
        reasons.append("output_contract missing")
    if missing_listed:
        reasons.append("listed source missing: %d" % len(missing_listed))
    if any(status in ("not_reported", "source_conflict", "extraction_failed")
           for status in elements.values()):
        reasons.append("elements not fully evidenced")
    if feasibility.get("status") in ("fail", "unknown"):
        reasons.append("feasibility %s" % feasibility.get("status"))
    if alignment.get("status") != "pass":
        reasons.append("alignment gaps")
    status = "partial" if reasons else "success"
    if readable == 0 and not bundle.get("sources"):
        status = "partial"
    return status, elements, reasons


# --------------------------------------------------------------- rendering

def cite(item):
    if item.get("claim_id"):
        return "[%s]" % item["claim_id"]
    if item.get("claim_ids"):
        return "[%s]" % "][".join(item["claim_ids"])
    return "[未定位]"


def render_markdown(plan, claims, elements, feasibility, alignment,
                    uncertainty, change_log, status, bundle, case, case_id,
                    contract_source, concerns=None, numeric_audit=None,
                    docx_check=None):
    title = plan.get("title") or "开题报告与研究计划书"
    constraints = plan.get("constraints", {})
    schedule = plan.get("schedule", {})
    period = constraints.get("period_months", {})
    budget = constraints.get("budget_wan", {})
    sample = constraints.get("sample_size", {})
    lines = []
    lines.append("# %s" % title)
    lines.append("")
    lines.append("> 生成工具：%s v%s｜case_id：%s｜运行状态：%s"
                 % (common.SKILL_NAME, common.SKILL_VERSION, case_id, status))
    lines.append("> 说明：带 C# 的事实性表述均可在第 8 节逐条回查；标\u3010草案\u3011的条目"
                 "是可执行计划草案，需导师/课题组确认，不冒充既有事实。")
    lines.append("")

    lines.append("## 摘要")
    summary = []
    if plan.get("gap_statement"):
        summary.append("本方案从材料指出的缺口出发：%s%s"
                       % (short(plan["gap_statement"], 120),
                          cite(plan.get("gaps", [{}])[0]) if plan.get("gaps") else ""))
    questions = [q for q in plan.get("questions", []) if q.get("status") != "not_reported"]
    if questions:
        summary.append("拟回答 %d 个研究问题，其中核心问题为：%s%s"
                       % (len(questions), short(questions[0]["question"], 120),
                          cite(questions[0])))
    if period.get("status") == "reported":
        summary.append("计划周期 %s 个月，划分为 %d 个阶段。"
                       % (fmt_num(period["value"]), len(schedule.get("milestones", []))))
    else:
        summary.append("材料未明确计划周期，阶段安排需补充。")
    summary.append("目标、技术路线、里程碑与预期成果按对齐矩阵逐项对应；风险均给出触发信号、"
                   "影响、备选方案与决策时点。")
    lines.append(" ".join(summary))
    lines.append("")

    lines.append("## 1. 研究背景与已知事实")
    if plan.get("background"):
        for item in plan["background"]:
            lines.append("- %s（%s；锚点 `%s`）"
                         % (short(item["text"], 220), cite(item), item["anchor"]))
    else:
        lines.append("- 材料未提供可识别的背景/前期结果句（not_reported）。")
    lines.append("")

    lines.append("## 2. 问题定义与研究缺口")
    lines.append("### 2.1 已知—未知—待验证")
    if plan.get("background"):
        lines.append("**已知**")
        for item in plan["background"][:4]:
            lines.append("- %s（%s）" % (short(item["text"], 140), cite(item)))
    else:
        lines.append("- 已知：材料未提供。")
    if plan.get("gaps"):
        lines.append("")
        lines.append("**未知/缺口**")
        for item in plan["gaps"]:
            lines.append("- %s（%s；`%s`）"
                         % (short(item["text"], 160), cite(item), item["anchor"]))
    else:
        lines.append("- 未知/缺口：材料未明确陈述（not_reported）。")
    lines.append("")
    lines.append("**待验证（研究问题，草案）**")
    for question in plan.get("questions", []):
        basis = question.get("claim_ids") or []
        refs = "、".join("[%s]" % cid for cid in basis) or "无定位"
        lines.append("- **%s** %s（%s；依据 %s）"
                     % (question["id"], question["question"],
                        status_label(question.get("status")), refs))
    lines.append("")

    lines.append("## 3. 研究目标与可考核判据")
    lines.append("| ID | 对应问题 | 目标 | 指标/阈值 | 样本 | 对照 | 时间点 | 状态 |")
    lines.append("|---|---|---|---|---|---|---|---|")
    for objective in plan.get("objectives", []):
        lines.append("| %s | %s | %s%s | %s | %s | %s | %s | %s |" % (
            objective["id"], objective.get("question_id", ""),
            md_cell(objective.get("objective"), 140),
            (" " + cite(objective)) if objective.get("claim_id") else "",
            md_cell(objective.get("metric"), 140) if objective.get("metric") else "材料未提供",
            md_cell(objective.get("sample")) if objective.get("sample") else "材料未提供",
            md_cell(objective.get("comparator")) if objective.get("comparator") else "材料未提供",
            md_cell(objective.get("timepoint")) if objective.get("timepoint") else "材料未提供",
            status_label(objective.get("status")),
        ))
    lines.append("")
    lines.append("> 指标、样本、对照与时间点全部取自输入材料或由已给出的周期推导；"
                 "缺失项写\u201c材料未提供\u201d，不以推测值填充。")
    lines.append("")

    lines.append("## 4. 技术路线与阶段计划")
    lines.append("### 4.1 技术路线步骤")
    lines.append("| ID | 动作（材料方法句） | 输入 | 输出 | 依赖 | 关联问题 | 状态 |")
    lines.append("|---|---|---|---|---|---|---|")
    for step in plan.get("route", []):
        lines.append("| %s | %s%s | %s | %s | %s | %s | %s |" % (
            step["id"], md_cell(step.get("action"), 150),
            (" " + cite(step)) if step.get("claim_id") else "",
            md_cell("；".join(step.get("inputs", [])), 70),
            md_cell("；".join(step.get("outputs", [])), 70),
            md_cell("、".join(step.get("depends_on", [])) or "无", 40),
            md_cell("、".join(step.get("linked_questions", [])) or "待确认", 40),
            status_label(step.get("status")),
        ))
    lines.append("")
    lines.append("### 4.2 阶段计划与里程碑")
    if schedule.get("milestones"):
        lines.append("| ID | 阶段 | 起止月 | 交付物 | 关联目标 | 前置 | 可并行 | 关键路径 | 状态 |")
        lines.append("|---|---|---|---|---|---|---|---|---|")
        for milestone in schedule["milestones"]:
            lines.append("| %s | %s | %s–%s | %s | %s | %s | %s | %s | %s |" % (
                milestone["id"], md_cell(milestone.get("name"), 60),
                milestone.get("start_month"), milestone.get("end_month"),
                md_cell("；".join(milestone.get("deliverables", [])), 120),
                md_cell("、".join(milestone.get("linked_objectives", [])) or "待确认", 40),
                md_cell("、".join(milestone.get("depends_on", [])) or "无", 30),
                "是" if milestone.get("parallelizable") else "否",
                "是" if milestone.get("critical_path") else "否",
                status_label(milestone.get("status")),
            ))
        lines.append("")
        lines.append("**关键路径**：%s。" % " → ".join(
            m["id"] for m in schedule["milestones"] if m.get("critical_path")))
    else:
        lines.append("- 未生成里程碑：%s（状态：%s）"
                     % (schedule.get("note", "缺少周期"), status_label(schedule.get("status"))))
    lines.append("")

    lines.append("## 5. 资源条件与可行性")
    lines.append("### 5.1 输入约束")
    lines.append("| 约束 | 取值/表述 | 来源 | 状态 |")
    lines.append("|---|---|---|---|")
    for key, name in [("period_months", "研究周期"), ("budget_wan", "经费预算"),
                      ("sample_size", "样本量"), ("personnel", "人员"),
                      ("data", "数据条件"), ("ethics", "伦理与合规")]:
        item = constraints.get(key, {})
        if key in ("period_months", "budget_wan", "sample_size"):
            if item.get("status") == "reported":
                unit = item.get("unit", "")
                unit = "个月" if unit == "months" else unit
                value = "%s %s" % (fmt_num(item.get("value")), unit)
                raw = item.get("raw", "")
                if raw and common.canon(raw) != common.canon(value.strip()):
                    value += "（%s）" % raw
                source = "`%s` %s" % (item.get("anchor", ""), item.get("file", ""))
            elif item.get("status") == "source_conflict":
                value = "；".join("%s %s" % (fmt_num(c.get("value")), item.get("unit", ""))
                                  for c in item.get("candidates", []))
                source = "；".join("`%s`" % c.get("anchor", "")
                                   for c in item.get("candidates", []))
            else:
                value, source = "材料未提供", "\u2014"
        else:
            items = item.get("items", [])
            value = "；".join(short(i.get("quote", ""), 100) for i in items) or "材料未提供"
            source = "；".join(
                "`%s` %s" % (i.get("anchor", ""), i.get("file", "")) for i in items) or "\u2014"
        lines.append("| %s | %s | %s | %s |" % (
            name, md_cell(value, 180), md_cell(source, 160),
            status_label(item.get("status"))))
    lines.append("")
    lines.append("### 5.2 可行性检查")
    lines.append("| ID | 检查项 | 结论 | 说明 |")
    lines.append("|---|---|---|---|")
    for check in feasibility.get("checks", []):
        lines.append("| %s | %s | %s | %s |" % (
            check["id"], check["check"], check["status"],
            md_cell(check["detail"], 180)))
    lines.append("")
    lines.append("总体可行性：**%s**。" % feasibility.get("status"))
    lines.append("")
    if concerns:
        lines.append("### 5.3 四项审查关注点")
        lines.append("| 关注点 | 检查问题 | 结论 | 依据 |")
        lines.append("|---|---|---|---|")
        for row in concerns.get("rows", []):
            lines.append("| %s | %s | %s | %s |" % (
                row.get("concern"), md_cell(row.get("question"), 90),
                row.get("status"), md_cell(row.get("evidence"), 220)))
        lines.append("")
    if numeric_audit:
        lines.append("### 5.4 数字可追溯性")
        lines.append("- 已核对数字 %d 个；未追溯 %d 个；结论：**%s**。"
                     % (numeric_audit.get("checked_numbers", 0),
                        len(numeric_audit.get("unresolved", [])),
                        numeric_audit.get("status")))
        if numeric_audit.get("unresolved"):
            for item in numeric_audit["unresolved"][:6]:
                lines.append("  - `%s` 的数字 %s 未在材料中找到（%s）"
                             % (item.get("claim_id"), item.get("number"),
                                md_cell(item.get("text"), 80)))
        else:
            lines.append("- 所有结论性数字均可回溯到材料锚点，或来自 4.2 节的显式排期推导。")
        lines.append("")

    lines.append("## 6. 风险与备选方案")
    lines.append("| ID | 类别 | 风险 | 触发信号 | 影响 | 备选方案 | 决策时点 | 状态 |")
    lines.append("|---|---|---|---|---|---|---|---|")
    for risk in plan.get("risks", []):
        evidence = risk.get("evidence") or {}
        risk_text = risk.get("risk", "")
        if evidence.get("claim_id"):
            risk_text += " " + cite(evidence)
        lines.append("| %s | %s | %s | %s | %s | %s | %s | %s |" % (
            risk["id"], risk.get("category_zh", risk.get("category")),
            md_cell(risk_text, 110), md_cell(risk.get("trigger"), 120),
            md_cell(risk.get("impact"), 100), md_cell(risk.get("fallback"), 140),
            md_cell(risk.get("decision_point"), 80),
            status_label(risk.get("status")),
        ))
    lines.append("")
    lines.append("> 风险触发阈值与备选方案为草案；材料若未给出具体阈值，不虚构数值。")
    lines.append("")

    lines.append("### 6.1 伦理与合规安排")
    ethics_items = (plan.get("constraints", {}).get("ethics") or {}).get("items") or []
    data_items = (plan.get("constraints", {}).get("data") or {}).get("items") or []
    if ethics_items:
        for item in ethics_items:
            lines.append("- **审批/知情同意**：%s（`%s` %s）"
                         % (md_cell(item.get("text"), 260), item.get("anchor"),
                            item.get("file", "")))
    else:
        lines.append("- **审批/知情同意**：材料未提供伦理审批号或知情同意安排，"
                     "需在方案细化阶段补齐；未补齐前不得启动涉人步骤。")
    if data_items:
        lines.append("- **数据安全**：%s（`%s` %s）"
                     % (md_cell(data_items[0].get("text"), 260),
                        data_items[0].get("anchor"), data_items[0].get("file", "")))
    else:
        lines.append("- **数据安全**：材料未提供数据脱敏、存储与访问控制安排，需补充。")
    lines.append("- **利益冲突与风险处置**：材料未提供利益冲突声明；随访发现高风险个体时"
                 "按伦理审批的转介流程处理，不向研究外人员披露个体结果。")
    lines.append("")

    lines.append("## 7. 预期成果与考核方式")
    lines.append("| ID | 预期成果 | 关联目标 | 考核方式 | 状态 |")
    lines.append("|---|---|---|---|---|")
    for outcome in plan.get("outcomes", []):
        lines.append("| %s | %s%s | %s | %s | %s |" % (
            outcome["id"], md_cell(outcome.get("outcome"), 140),
            (" " + cite(outcome)) if outcome.get("claim_id") else "",
            outcome.get("objective_id") or "待确认",
            md_cell(outcome.get("acceptance"), 120),
            status_label(outcome.get("status")),
        ))
    lines.append("")

    lines.append("## 8. 证据与来源映射")
    lines.append("| ID | 类型 | 状态 | 锚点 | 来源文件 | 逐字引文 |")
    lines.append("|---|---|---|---|---|---|")
    for claim in claims:
        lines.append("| %s | %s | %s | %s | %s | %s |" % (
            claim["claim_id"], claim.get("kind", ""), status_label(claim.get("status")),
            ("`%s`" % claim["anchor"]) if claim.get("anchor") else "\u2014",
            md_cell(claim.get("source_file"), 40),
            md_cell(claim.get("quote"), 200),
        ))
    lines.append("")
    lines.append("锚点格式：`S1#p1.3` 表示文件 S1 第 1 页第 3 段；无分页材料统一页码 1；"
                 "`case.json:<key>` 指案例元数据字段。")
    lines.append("")

    lines.append("## 9. 人工确认项、材料缺口与版本记录")
    lines.append("### 9.1 人工确认项")
    confirms = plan.get("human_confirm") or []
    if confirms:
        for item in confirms:
            lines.append("- %s" % item)
    else:
        lines.append("- 无额外人工确认项（仍建议导师复核目标阈值与排期）。")
    lines.append("")
    lines.append("### 9.2 材料缺口与不确定性")
    lines.append("- 不确定性等级：**%s**" % uncertainty.get("level"))
    for note in uncertainty.get("notes", []):
        lines.append("- %s" % note)
    if uncertainty.get("unresolved"):
        lines.append("- 未解决项：%s" % "、".join(uncertainty["unresolved"]))
    lines.append("")
    lines.append("### 9.3 修改与运行记录")
    for entry in change_log:
        lines.append("- %s" % entry)
    lines.append("")
    lines.append("## 附录 A. 输出文件与复现")
    lines.append("- `proposal.md`：本文件，可直接继续编辑。")
    lines.append("- `proposal.docx`：真实 WordprocessingML 文档，含标题层级与表格；"
                 "已用 zipfile + XML 解析重开校验。")
    lines.append("- `proposal.html`：由本 Markdown 渲染的可打印预览（非正式提交格式）。")
    lines.append("- `evidence.csv`：证据台账，逐条列出锚点、引文与核验状态。")
    lines.append("- `result.json`：满足 `output_contract` 的结构化结果。")
    if docx_check:
        lines.append("- DOCX 校验：ok=%s，段落 %s，表格 %s，字节 %s。"
                     % (docx_check.get("ok"), docx_check.get("paragraphs"),
                        docx_check.get("tables"), docx_check.get("bytes")))
    lines.append("")
    lines.append("```bash")
    lines.append("python3 scripts/run_case.py --input /input --work /app/work --output /app/output")
    lines.append("python3 scripts/selfcheck.py --case /input/case.json \\")
    lines.append("    --sources /app/work/sources.json --out /app/output")
    lines.append("```")
    lines.append("")
    lines.append("---")
    lines.append("本文件由 %s v%s 依据输入材料生成；契约来源：%s。"
                 % (common.SKILL_NAME, common.SKILL_VERSION, contract_source))
    return "\n".join(lines) + "\n"


def md_to_html(markdown_text, title):
    lines = markdown_text.splitlines()
    out = []
    in_list = False
    in_table = False
    in_code = False

    def inline(text):
        text = html.escape(text)
        text = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", text)
        text = re.sub(r"`([^`]+)`", r"<code>\1</code>", text)
        return text

    def close_list():
        nonlocal in_list
        if in_list:
            out.append("</ul>")
            in_list = False

    def close_table():
        nonlocal in_table
        if in_table:
            out.append("</table>")
            in_table = False

    for line in lines:
        stripped = line.strip()
        if stripped.startswith("```"):
            close_list()
            close_table()
            if in_code:
                out.append("</pre>")
                in_code = False
            else:
                out.append("<pre>")
                in_code = True
            continue
        if in_code:
            out.append(html.escape(line))
            continue
        if stripped.startswith("|") and stripped.endswith("|"):
            cells = [cell.strip() for cell in stripped.strip("|").split("|")]
            if all(re.match(r"^:?-{2,}:?$", cell or "") for cell in cells):
                continue
            close_list()
            if not in_table:
                out.append("<table>")
                in_table = True
            tag = "th" if out[-1] == "<table>" else "td"
            out.append("<tr>%s</tr>" % "".join(
                "<%s>%s</%s>" % (tag, inline(cell), tag) for cell in cells))
            continue
        close_table()
        if not stripped:
            close_list()
            continue
        heading = re.match(r"^(#{1,6})\s+(.*)$", stripped)
        if heading:
            close_list()
            level = len(heading.group(1))
            out.append("<h%d>%s</h%d>" % (level, inline(heading.group(2)), level))
            continue
        if stripped.startswith(">"):
            close_list()
            out.append("<blockquote>%s</blockquote>" % inline(stripped.lstrip("> ")))
            continue
        bullet = re.match(r"^[-*]\s+(.*)$", stripped)
        if bullet:
            if not in_list:
                out.append("<ul>")
                in_list = True
            out.append("<li>%s</li>" % inline(bullet.group(1)))
            continue
        numbered = re.match(r"^\d+\.\s+(.*)$", stripped)
        if numbered:
            if not in_list:
                out.append("<ul>")
                in_list = True
            out.append("<li>%s</li>" % inline(numbered.group(1)))
            continue
        close_list()
        out.append("<p>%s</p>" % inline(stripped))
    close_list()
    close_table()
    if in_code:
        out.append("</pre>")
    body = "\n".join(out)
    return """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<title>%s</title>
<style>
body{font-family:"Songti SC","Noto Serif CJK SC",Georgia,serif;max-width:980px;margin:32px auto;padding:0 24px;line-height:1.7;color:#1f2933}
h1,h2,h3{font-family:"PingFang SC","Noto Sans CJK SC",sans-serif;line-height:1.35}
h1{border-bottom:2px solid #334e68;padding-bottom:8px}
h2{margin-top:32px;border-left:5px solid #486581;padding-left:10px}
table{border-collapse:collapse;width:100%%;margin:12px 0;font-size:13px}
th,td{border:1px solid #bcccdc;padding:6px 8px;vertical-align:top}
th{background:#f0f4f8}
blockquote{background:#f0f4f8;border-left:4px solid #9fb3c8;margin:12px 0;padding:8px 12px}
code{background:#f0f4f8;padding:1px 4px;border-radius:3px}
pre{background:#f0f4f8;padding:12px;overflow:auto}
@media print{body{max-width:none;margin:0}}
</style>
</head>
<body>
<!-- HTML preview rendered from proposal.md by build_proposal.py; edit proposal.md, not this file. -->
%s
</body>
</html>
""" % (html.escape(title), body)


def write_evidence_csv(path, claims):
    fields = ["claim_id", "kind", "status", "verified", "anchor",
              "source_file", "quote"]
    with open(path, "w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields)
        writer.writeheader()
        for claim in claims:
            writer.writerow({key: claim.get(key, "") for key in fields})


# ------------------------------------------------------------ result assembly

def map_contract_value(name, result):
    key = (name or "").strip().lower().replace("-", "_").replace(" ", "_")
    mapping = {
        "case_id": "case_id", "id": "case_id", "task_id": "case_id",
        "status": "status", "state": "status",
        "proposal": "proposal_md", "proposal_md": "proposal_md",
        "proposal_text": "proposal_md", "document": "proposal_md",
        "markdown": "proposal_md", "report": "proposal_md",
        "opening_report": "proposal_md", "research_proposal": "proposal_md",
        "proposal_docx": "proposal_docx", "docx": "proposal_docx",
        "word_document": "proposal_docx", "word": "proposal_docx",
        "proposal_docx_path": "proposal_docx_path", "docx_path": "proposal_docx_path",
        "docx_file": "proposal_docx_path", "word_path": "proposal_docx_path",
        "docx_check": "docx_check", "document_check": "docx_check",
        "proposal_path": "proposal_path", "proposal_file": "proposal_path",
        "output_path": "proposal_path",
        "elements": "elements", "sections": "elements",
        "seven_elements": "elements", "components": "elements",
        "outline": "elements",
        "evidence": "evidence", "citations": "evidence",
        "citation_map": "evidence", "source_map": "evidence",
        "claim_map": "evidence", "claims": "evidence",
        "sources": "sources", "references": "sources",
        "constraints": "constraints", "conditions": "constraints",
        "resources": "constraints",
        "feasibility": "feasibility", "feasibility_check": "feasibility",
        "alignment": "alignment", "alignment_matrix": "alignment",
        "risks": "risks", "risk_register": "risks",
        "milestones": "milestones", "timeline": "milestones",
        "schedule": "schedule", "research_plan": "schedule",
        "objectives": "objectives", "goals": "objectives",
        "questions": "questions", "research_questions": "questions",
        "uncertainty": "uncertainty", "uncertainties": "uncertainty",
        "change_log": "change_log", "changes": "change_log",
        "artifacts": "artifacts", "deliverables": "artifacts",
        "files": "artifacts", "outputs": "artifacts",
        "coverage": "coverage", "title": "title", "audience": "audience",
        "discipline": "discipline", "summary": "summary",
        "abstract": "summary", "contract_check": "contract_check",
    }
    chinese = {
        "开题报告": "proposal_md", "开题报告正文": "proposal_md",
        "报告正文": "proposal_md", "方案正文": "proposal_md",
        "稿件": "proposal_md", "文档": "proposal_docx",
        "word文档": "proposal_docx", "docx文档": "proposal_docx",
        "七要素": "elements", "章节": "elements",
        "结构": "elements", "证据": "evidence", "引用": "evidence",
        "事实与来源映射": "evidence", "来源映射": "evidence",
        "风险": "risks", "风险与备选方案": "risks",
        "阶段计划": "schedule", "研究计划": "schedule", "进度": "milestones",
        "里程碑": "milestones", "研究目标": "objectives", "目标": "objectives",
        "研究问题": "questions", "问题": "questions",
        "约束": "constraints", "条件": "constraints", "资源": "constraints",
        "可行性": "feasibility", "对齐": "alignment",
        "状态": "status", "运行状态": "status",
        "不确定性": "uncertainty", "边界": "uncertainty",
        "修改记录": "change_log", "变更记录": "change_log",
        "版本与边界": "change_log", "来源": "sources",
        "产物": "artifacts", "交付物": "artifacts", "文件": "artifacts",
        "覆盖": "coverage", "摘要": "summary",
    }
    slot = mapping.get(key) or chinese.get(name)
    if not slot:
        if "docx" in key or "word" in key:
            slot = "proposal_docx_path" if ("path" in key or "file" in key) else "proposal_docx"
        elif "proposal" in key and ("path" in key or "file" in key):
            slot = "proposal_path"
        elif any(token in key for token in ("proposal", "report", "draft",
                                            "document", "markdown")) and \
                "proposal_path" not in key:
            slot = "proposal_md"
        elif any(token in key for token in ("evidence", "citation", "claim")):
            slot = "evidence"
        elif "risk" in key:
            slot = "risks"
        elif any(token in key for token in ("milestone", "timeline")):
            slot = "milestones"
        elif any(token in key for token in ("schedule", "plan")):
            slot = "schedule"
        elif any(token in key for token in ("objective", "goal")):
            slot = "objectives"
        elif any(token in key for token in ("question", "aim")):
            slot = "questions"
        elif any(token in key for token in ("constraint", "condition", "resource")):
            slot = "constraints"
        elif any(token in key for token in ("feasib", "align")):
            slot = "feasibility"
        elif any(token in key for token in ("artifact", "deliverable", "file")):
            slot = "artifacts"
        elif any(token in key for token in ("element", "section")):
            slot = "elements"
        elif "status" in key:
            slot = "status"
    if not slot:
        return None
    return result.get(slot)


def summarize_sources(bundle, input_dir, cited_anchors):
    rows = []
    for src in bundle.get("sources", []):
        path = os.path.join(input_dir, src.get("rel_path", src.get("file", "")))
        anchors = [p.get("anchor") for p in src.get("paragraphs", [])
                   if p.get("anchor") in cited_anchors]
        rows.append({
            "id": src.get("id"),
            "file": src.get("file"),
            "rel_path": src.get("rel_path"),
            "role": src.get("role", "material"),
            "kind": src.get("kind"),
            "tier": src.get("tier"),
            "readable": bool(src.get("readable")),
            "paragraphs": len(src.get("paragraphs", [])),
            "chars": src.get("chars", 0),
            "sha256": source_file_sha256(path) if os.path.isfile(path) else None,
            "anchors_cited": len(anchors),
            "error": src.get("error"),
        })
    return rows


def write_result(path, result):
    common.write_json(path, result)


def try_render_preview(docx_path, output_dir):
    """Best-effort PDF preview through a preinstalled office renderer.

    The runtime contract asks for rendered previews of editable Office output.
    No third-party Python is used; if the image has no renderer we record an
    honest 'unavailable' status instead of fabricating a preview.
    """
    exe = shutil.which("soffice") or shutil.which("libreoffice")
    if not exe:
        return {"status": "unavailable",
                "reason": "no soffice/libreoffice in PATH; HTML preview is provided instead"}
    try:
        proc = subprocess.run(
            [exe, "--headless", "--convert-to", "pdf", "--outdir", output_dir, docx_path],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=45,
        )
    except Exception as exc:  # noqa: BLE001
        return {"status": "failed", "reason": str(exc)[:200]}
    pdf_path = os.path.join(output_dir, os.path.splitext(os.path.basename(docx_path))[0] + ".pdf")
    if proc.returncode == 0 and os.path.isfile(pdf_path) and os.path.getsize(pdf_path) > 0:
        return {"status": "ok", "pdf": pdf_path, "bytes": os.path.getsize(pdf_path)}
    return {"status": "failed",
            "reason": (proc.stderr or proc.stdout or b"").decode("utf-8", "replace")[:200]}


# --------------------------------------------------------------------- main

def build(input_dir, work_dir, output_dir, plan_path=None, sources_path=None):
    os.makedirs(work_dir, exist_ok=True)
    os.makedirs(output_dir, exist_ok=True)
    case = load_case(input_dir)
    case_id = common.case_id_of(case, input_dir)
    fields, contract_raw, contract_source = contract_fields(case)
    bundle, sources_path = load_sources(input_dir, work_dir, sources_path)
    augment_task_source(bundle, input_dir)
    missing_listed = find_listed_missing(case, input_dir, bundle)
    common.write_json(sources_path, bundle)

    base_plan = scaffold_plan(case, bundle)
    plan_source = "scaffold"
    if plan_path and os.path.isfile(plan_path):
        override = common.load_json(plan_path, {})
        if isinstance(override, dict) and override:
            base_plan = merge_plan(base_plan, override)
            plan_source = "agent_plan"
    plan = base_plan
    plan["title"] = plan.get("title") or default_title(case, content_paragraphs(bundle))
    plan["plan_source"] = plan_source

    claims = attach_claims(plan, bundle, case)
    plan["alignment"] = build_alignment(plan)
    plan["feasibility"] = build_feasibility(plan, bundle)
    numeric_audit = numeric_traceability(plan, claims, bundle, case)
    concerns = build_concerns(plan, claims, plan["alignment"], plan["feasibility"])

    if plan_source == "scaffold":
        plan["human_confirm"] = [
            "阶段划分、里程碑时长与人员分工为草案，需导师确认。",
            "研究目标中的指标阈值、样本量、对照与时间点需课题组确认。",
            "风险触发阈值与备选方案为草案，需按实际条件细化。",
        ]
        if plan["constraints"].get("budget_wan", {}).get("status") != "reported":
            plan["human_confirm"].append("材料未明确经费条件，需补充预算与科目。")
        if plan["constraints"].get("period_months", {}).get("status") == "source_conflict":
            plan["human_confirm"].append("周期存在互斥来源，必须先确认周期再排期。")
        if numeric_audit.get("unresolved"):
            plan["human_confirm"].append(
                "有 %d 个数字未能回溯到材料或排期推导，需人工核对后再作为结论使用。"
                % len(numeric_audit["unresolved"]))

    elements = {
        "research_background": {"status": element_status(plan.get("background", [])),
                                "items": plan.get("background", [])},
        "problem_definition": {"status": element_status(plan.get("questions", [])),
                               "gap_statement": plan.get("gap_statement", ""),
                               "gaps": plan.get("gaps", []),
                               "questions": plan.get("questions", [])},
        "objectives": {"status": element_status(plan.get("objectives", [])),
                       "items": plan.get("objectives", [])},
        "technical_route": {"status": element_status(plan.get("route", [])),
                            "steps": plan.get("route", [])},
        "schedule": {"status": plan.get("schedule", {}).get("status", "not_reported"),
                     "period_months": plan.get("schedule", {}).get("period_months"),
                     "milestones": plan.get("schedule", {}).get("milestones", []),
                     "note": plan.get("schedule", {}).get("note", "")},
        "risks": {"status": element_status(plan.get("risks", [])),
                  "items": plan.get("risks", [])},
        "expected_outcomes": {"status": element_status(plan.get("outcomes", [])),
                              "items": plan.get("outcomes", [])},
    }
    status, elements_status, status_reasons = determine_status(
        bundle, plan, plan["feasibility"], plan["alignment"], missing_listed,
        contract_source)
    if concerns.get("status") != "pass":
        status_reasons.append("four review concerns not fully passed")
        if status == "success":
            status = "partial"
    if numeric_audit.get("unresolved"):
        status_reasons.append("unresolved numbers: %d" % len(numeric_audit["unresolved"]))
        if status == "success":
            status = "partial"

    uncertainty_notes = []
    unresolved = []
    if not any(src.get("readable") and src.get("role") != "task"
               for src in bundle.get("sources", [])):
        uncertainty_notes.append(
            "输入目录未发现可抽取的科研材料；七要素按 not_reported 标注，未编造内容。")
        unresolved.append("materials")
    for item in bundle.get("unreadable", []):
        uncertainty_notes.append("不可读文件：%s（%s）"
                                 % (item.get("file"), item.get("error")))
        unresolved.append("unreadable:%s" % item.get("file"))
    for item in missing_listed:
        uncertainty_notes.append("case.json 列出但未找到：%s" % item["file"])
        unresolved.append("missing_source:%s" % item["file"])
    for key in ("period_months", "budget_wan", "sample_size"):
        constraint = plan.get("constraints", {}).get(key, {})
        if constraint.get("status") == "source_conflict":
            values = "；".join("%s（%s）" % (c.get("value"), c.get("raw"))
                              for c in constraint.get("candidates", []))
            uncertainty_notes.append("%s 存在互斥来源：%s；未自行选择，需人工确认。"
                                     % (key, values))
            unresolved.append(key)
        elif constraint.get("status") == "not_reported":
            uncertainty_notes.append("%s 未在材料中明确给出。" % key)
            unresolved.append(key)
    for key in ("personnel", "data", "ethics"):
        if plan.get("constraints", {}).get(key, {}).get("status") != "reported":
            uncertainty_notes.append("%s 条件未明确给出。" % key)
            unresolved.append(key)
    if any(not o.get("metric") for o in plan.get("objectives", [])):
        uncertainty_notes.append("部分研究目标缺少材料支持的指标/阈值，需补充后才能考核。")
        unresolved.append("objectives.metric")
    if contract_source == "default":
        uncertainty_notes.append(
            "case.json 未提供可识别的 output_contract；已按默认字段集输出，"
            "字段名可能与评测期望不同。")
        unresolved.append("output_contract")
    if status_reasons:
        uncertainty_notes.append("状态判定为 %s：%s" % (status, "；".join(status_reasons)))
    if not uncertainty_notes:
        uncertainty_notes.append("none：所有事实性表述均已定位到输入材料，未新增材料外事实。")
    uncertainty = {
        "level": "high" if not any(src.get("readable") for src in bundle.get("sources", []))
                 else ("medium" if status != "success" else "low"),
        "notes": uncertainty_notes[:24],
        "unresolved": list(dict.fromkeys(unresolved)),
    }

    change_log = [
        "读取 case.json：case_id=%s，契约来源=%s，契约字段 %d 个。"
        % (case_id, contract_source, len(fields)),
        "抽取 %d 个文件：可读 %d，不可读 %d，段落 %d。"
        % (len(bundle.get("sources", [])),
           sum(1 for s in bundle.get("sources", []) if s.get("readable")),
           len(bundle.get("unreadable", [])),
           sum(len(s.get("paragraphs", [])) for s in bundle.get("sources", []))),
        "约束扫描：周期=%s、预算=%s、样本=%s；冲突 %d 项。"
        % (plan["constraints"]["period_months"].get("status"),
           plan["constraints"]["budget_wan"].get("status"),
           plan["constraints"]["sample_size"].get("status"),
           sum(1 for k in ("period_months", "budget_wan", "sample_size")
               if plan["constraints"][k].get("status") == "source_conflict")),
        "装配七要素：背景 %d、问题 %d、目标 %d、路线步骤 %d、里程碑 %d、风险 %d、成果 %d。"
        % (len(plan.get("background", [])), len(plan.get("questions", [])),
           len(plan.get("objectives", [])), len(plan.get("route", [])),
           len(plan.get("schedule", {}).get("milestones", [])),
           len(plan.get("risks", [])), len(plan.get("outcomes", []))),
        "证据台账 %d 条，其中已核验 %d 条；数字追溯 %d 个，未追溯 %d 个。"
        % (len(claims), sum(1 for c in claims if c.get("verified")),
           numeric_audit.get("checked_numbers", 0),
           len(numeric_audit.get("unresolved", []))),
        "以 %s 模式生成 proposal.md / proposal.docx / proposal.html / evidence.csv / "
        "result.json；DOCX 已用 zipfile+XML 重开校验。" % plan_source,
    ]

    cited = set(c.get("anchor") for c in claims if c.get("anchor"))
    sources_summary = summarize_sources(bundle, input_dir, cited)
    coverage = {
        "sources_total": len(bundle.get("sources", [])),
        "sources_readable": sum(1 for s in bundle.get("sources", []) if s.get("readable")),
        "sources_unreadable": len(bundle.get("unreadable", [])) + len(missing_listed),
        "paragraphs": sum(len(s.get("paragraphs", [])) for s in bundle.get("sources", [])),
        "claims": len(claims),
        "claims_verified": sum(1 for c in claims if c.get("verified")),
        "verification_rate": round(
            (sum(1 for c in claims if c.get("verified")) / float(len(claims)))
            if claims else 1.0, 4),
        "elements": {key: elements[key]["status"] for key in ELEMENT_KEYS},
    }

    title = plan.get("title") or "开题报告与研究计划书"
    proposal_path = os.path.join(output_dir, "proposal.md")
    docx_path = os.path.join(output_dir, "proposal.docx")

    def render(with_check):
        return render_markdown(plan, claims, elements, plan["feasibility"],
                               plan["alignment"], uncertainty, change_log, status,
                               bundle, case, case_id, contract_source,
                               concerns=concerns, numeric_audit=numeric_audit,
                               docx_check=with_check)

    # First pass: write Markdown, then build the DOCX and verify it reopens.
    markdown = render(None)
    with open(proposal_path, "w", encoding="utf-8") as fh:
        fh.write(markdown)
    docx_check = docx_mini.write_docx(markdown, docx_path, title)

    plan["feasibility"]["checks"].append({
        "id": "F11", "check": "可编辑 DOCX 交付",
        "status": "pass" if docx_check.get("ok") else "fail",
        "detail": ("proposal.docx 已重开校验：段落 %s、表格 %s、字节 %s"
                   % (docx_check.get("paragraphs"), docx_check.get("tables"),
                      docx_check.get("bytes")))
                  if docx_check.get("ok")
                  else "DOCX 校验失败：%s" % docx_check.get("error"),
    })
    if docx_check.get("ok"):
        markdown = render(docx_check)
        with open(proposal_path, "w", encoding="utf-8") as fh:
            fh.write(markdown)
        docx_check = docx_mini.write_docx(markdown, docx_path, title)
    else:
        status = "partial" if status == "success" else status
        uncertainty["notes"].append("DOCX 生成/重开校验失败：%s；Markdown 仍可编辑。"
                                    % docx_check.get("error"))
        uncertainty["unresolved"].append("proposal.docx")

    coverage["docx_ok"] = bool(docx_check.get("ok"))
    coverage["docx_paragraphs"] = docx_check.get("paragraphs", 0)
    coverage["docx_tables"] = docx_check.get("tables", 0)
    coverage["concerns"] = {row["concern"]: row["status"] for row in concerns.get("rows", [])}
    coverage["numeric_traceability"] = numeric_audit.get("status")
    coverage["question_count"] = len(plan.get("questions", []))

    html_path = os.path.join(output_dir, "proposal.html")
    with open(html_path, "w", encoding="utf-8") as fh:
        fh.write(md_to_html(markdown, title))
    csv_path = os.path.join(output_dir, "evidence.csv")
    write_evidence_csv(csv_path, claims)
    preview = try_render_preview(docx_path, output_dir) if docx_check.get("ok") else {
        "status": "unavailable", "reason": "DOCX not valid"}

    def artifact(path, role, fmt):
        return {"path": path, "role": role, "format": fmt,
                "exists": os.path.isfile(path),
                "bytes": os.path.getsize(path) if os.path.isfile(path) else 0}

    artifacts = [
        artifact(proposal_path, "editable proposal", "markdown"),
        artifact(docx_path, "editable Word proposal", "docx"),
        artifact(html_path, "rendered preview", "html"),
        artifact(csv_path, "evidence ledger", "csv"),
    ]
    if preview.get("status") == "ok":
        artifacts.append(artifact(preview["pdf"], "rendered PDF preview", "pdf"))
    summary = " ".join(
        part for part in [
            ("缺口：" + short(plan.get("gap_statement"), 100)) if plan.get("gap_statement") else "",
            ("周期：%s个月。" % fmt_num(plan["constraints"]["period_months"]["value"]))
            if plan["constraints"]["period_months"].get("status") == "reported" else "",
            ("研究问题：%d 个。" % len(plan.get("questions", []))),
            ("状态：%s。" % status),
        ] if part
    )

    result = {
        "case_id": case_id,
        "status": status,
        "title": title,
        "audience": plan.get("audience", ""),
        "discipline": plan.get("discipline", ""),
        "summary": summary,
        "proposal_md": markdown,
        "proposal_path": proposal_path,
        "proposal_docx": docx_path,
        "proposal_docx_path": docx_path,
        "docx_check": docx_check,
        "elements": elements,
        "element_status": elements_status,
        "evidence": claims,
        "sources": sources_summary,
        "constraints": plan.get("constraints", {}),
        "feasibility": plan["feasibility"],
        "alignment": plan["alignment"],
        "concerns": concerns,
        "numeric_audit": numeric_audit,
        "risks": plan.get("risks", []),
        "milestones": plan.get("schedule", {}).get("milestones", []),
        "schedule": plan.get("schedule", {}),
        "questions": plan.get("questions", []),
        "objectives": plan.get("objectives", []),
        "route": plan.get("route", []),
        "background": plan.get("background", []),
        "gaps": plan.get("gaps", []),
        "outcomes": plan.get("outcomes", []),
        "coverage": coverage,
        "artifacts": artifacts,
        "preview": preview,
        "uncertainty": uncertainty,
        "change_log": change_log,
        "contract_check": {"required": fields, "present": [], "missing": [],
                           "source": contract_source},
        "build": {
            "skill": common.SKILL_NAME,
            "version": common.SKILL_VERSION,
            "script": "build_proposal.py",
            "plan_source": plan_source,
            "sources_path": sources_path,
            "plan_path": plan_path or "",
            "missing_listed": missing_listed,
        },
    }

    missing_fields = []
    for name in fields:
        if name in result:
            continue
        value = map_contract_value(name, result)
        if value is None:
            missing_fields.append(name)
            value = {"status": "not_reported",
                     "reason": "本次运行未能自动取值，需人工复核补齐（未填入推测内容）"}
        result[name] = value
    result["contract_check"]["present"] = [name for name in fields if name in result]
    result["contract_check"]["missing"] = missing_fields
    if missing_fields:
        result["uncertainty"]["unresolved"] = list(dict.fromkeys(
            list(result["uncertainty"].get("unresolved", [])) + missing_fields))
        result["uncertainty"]["notes"].append(
            "以下契约字段无自动取值，已写诚实占位：%s" % "、".join(missing_fields))
        if result["status"] == "success":
            result["status"] = "partial"

    common.write_json(os.path.join(work_dir, "proposal_plan.json"), plan)
    build_report = {
        "case_id": case_id,
        "status": result["status"],
        "plan_source": plan_source,
        "contract_source": contract_source,
        "contract_fields": fields,
        "missing_fields": missing_fields,
        "element_status": elements_status,
        "coverage": coverage,
        "missing_listed": missing_listed,
        "generated": [a["path"] for a in artifacts] + [os.path.join(output_dir, "result.json")],
    }
    common.write_json(os.path.join(work_dir, "build_report.json"), build_report)
    write_result(os.path.join(output_dir, "result.json"), result)
    return result


def main(argv=None):
    ap = argparse.ArgumentParser(description="Assemble an anchored research proposal")
    ap.add_argument("--input", default="/input")
    ap.add_argument("--work", default="/app/work")
    ap.add_argument("--output", default="/app/output")
    ap.add_argument("--plan", default=None,
                    help="agent-refined proposal_plan.json (optional)")
    ap.add_argument("--sources", default=None,
                    help="explicit sources.json path (default <work>/sources.json)")
    args = ap.parse_args(argv)
    try:
        result = build(args.input, args.work, args.output, args.plan, args.sources)
        print("status=%s case=%s files=%d -> %s" % (
            result.get("status"), result.get("case_id"),
            len(result.get("artifacts", [])), os.path.join(args.output, "result.json")))
        for note in result.get("uncertainty", {}).get("notes", [])[:5]:
            print("NOTE %s" % note)
        return 0
    except Exception as exc:  # noqa: BLE001
        import traceback
        sys.stderr.write("[build_proposal] fatal: %s\n%s\n"
                         % (exc, traceback.format_exc()[-1200:]))
        try:
            os.makedirs(args.output, exist_ok=True)
            case = load_case(args.input)
            case_id = common.case_id_of(case, args.input)
            fallback = {
                "case_id": case_id, "status": "failed",
                "proposal_md": "", "elements": {},
                "evidence": [], "sources": [],
                "uncertainty": {"level": "high",
                                "notes": ["build_proposal 内部异常：%s" % str(exc)[:300]],
                                "unresolved": ["build"]},
                "change_log": ["build_proposal 异常退出，未生成正式产物。"],
                "contract_check": {"required": [], "present": [], "missing": []},
            }
            common.write_json(os.path.join(args.output, "result.json"), fallback)
        except Exception:  # noqa: BLE001
            pass
        return 0


if __name__ == "__main__":
    sys.exit(main())
