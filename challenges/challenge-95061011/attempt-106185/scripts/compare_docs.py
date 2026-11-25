#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""compare_docs.py - 多文档共同字段比较矩阵（纯标准库）。

输入是「同一工作单下多篇论文」的逐文档字段抽取结果，输出**逐格可回溯**的
比较结构：

  * matrix     字段 × 文档，每格带 source_document_id / paragraph_id / quote
  * relation   同字段跨文档的一致性（agree / differ / unit_mismatch /
               single_source / none）
  * comparability  按工作单要求的六项（task / metric / units / material /
               pollutant / budget）逐项判定能否直接合并
  * comparable_subset  只包含在指标、单位、污染物上真正同口径的文档
  * conflicts  差异结论 + 归因（条件 / 材料 / 单位 / 指标口径）
  * unreported 逐字段列出未报告该字段的文档

设计原则：
  * 不合并不同数据集/不同污染物；不可比就写不可比并保留原值。
  * 每个单元格的取值都来自它标注的那篇论文，单位随值记录。
  * 无法归因的差异明确写 "unattributed"，不编造原因。
"""
from __future__ import annotations

import csv
import os
import re

NUM_RE = re.compile(r"-?\d+(?:\.\d+)?")


def _num(value):
    if not isinstance(value, str):
        return None
    m = NUM_RE.search(value.replace(",", ""))
    if not m:
        return None
    try:
        return float(m.group(0))
    except ValueError:
        return None


def _cell(row, doc_id, doc_meta):
    return {
        "source_document_id": doc_id,
        "document_file": (doc_meta or {}).get("file"),
        "status": row.get("status"),
        "value": row.get("value"),
        "unit": row.get("unit"),
        "statistic": row.get("statistic"),
        "experimental_condition": row.get("experimental_condition"),
        "comparator": row.get("comparator"),
        "paragraph_id": row.get("paragraph_id"),
        "quote": (row.get("quote") or "")[:220],
    }


def _relation(cells):
    """同字段跨文档关系（只统计 reported 的格）。"""
    vals = [(k, c) for k, c in cells.items() if c.get("status") == "reported"]
    if not vals:
        return "none", "所有文档均未报告该字段"
    if len(vals) == 1:
        return "single_source", "仅 %s 报告了该字段，无法跨文档对照" % vals[0][0]
    units = {c.get("unit") or "" for _k, c in vals}
    nums = [(k, _num(c.get("value"))) for k, c in vals]
    if len(units) > 1:
        return "unit_mismatch", "单位不一致：%s；不能直接合并数值" % (
            ", ".join("%s=%s" % (k, c.get("unit") or "无单位") for k, c in vals))
    if all(n is not None for _k, n in nums):
        distinct = {n for _k, n in nums}
        if len(distinct) == 1:
            return "agree", "同单位下数值一致"
        lo = min(distinct)
        hi = max(distinct)
        return "differ", "同单位下数值不同（%.6g ~ %.6g，差 %.6g）" % (lo, hi, hi - lo)
    norm = {str(c.get("value") or "").strip().lower() for _k, c in vals}
    if len(norm) == 1:
        return "agree", "取值文本一致"
    return "differ", "取值不同：%s" % "; ".join(
        "%s=%s" % (k, c.get("value")) for k, c in vals)


def _pollutants(text):
    found = set()
    for m in re.finditer(r"\b(Pb|Cd|Cu|Zn|Ni|Cr|As|Hg|Co|Mn)\b\s*(?:\(\s*(II|III|IV|VI)\s*\))?",
                         text or ""):
        found.add(m.group(1) + ("(%s)" % m.group(2) if m.group(2) else ""))
    return found


def _budget(text):
    out = set()
    for m in re.finditer(r"(\d[\d,]{1,})\s*(?:samples|observations|data points|"
                         r"样本|样品|组实验)", text or "", re.I):
        out.add(m.group(1).replace(",", ""))
    return out


def build(workorder, docset, rows_by_doc, out_dir=None, work_dir=None):
    """装配比较矩阵。

    workorder: comparison-workorder.json（可能为空）
    docset:    [{"source_document_id", "file", "doc"}]（doc 为 doc_extract 结果）
    rows_by_doc: {source_document_id: [字段行]}
    """
    workorder = workorder if isinstance(workorder, dict) else {}
    doc_ids = [d["source_document_id"] for d in docset]
    field_ids = []
    for did in doc_ids:
        for row in rows_by_doc.get(did, []):
            fid = row.get("field_id")
            if fid and fid not in field_ids:
                field_ids.append(fid)

    documents = []
    for d in docset:
        doc = d.get("doc") or {}
        pages = doc.get("pages") or []
        rows = rows_by_doc.get(d["source_document_id"]) or []
        documents.append({
            "source_document_id": d["source_document_id"],
            "file": d.get("file"),
            "tier": doc.get("meta", {}).get("tier", "unknown"),
            "pages": len(pages),
            "chars": sum(int(p.get("chars") or 0) for p in pages),
            "fields_reported": sum(1 for r in rows if r.get("status") == "reported"),
            "fields_total": len(rows),
        })

    matrix = {}
    rows_out = []
    conflicts = []
    unreported = []
    for fid in field_ids:
        cells = {}
        for d in docset:
            did = d["source_document_id"]
            for row in rows_by_doc.get(did, []):
                if row.get("field_id") == fid:
                    cells[did] = _cell(row, did, d)
                    break
        relation, reason = _relation(cells)
        entry = {"field_id": fid, "cells": cells, "relation": relation, "note": reason}
        rows_out.append(entry)
        for did, cell in cells.items():
            matrix.setdefault(did, {})[fid] = cell
        if relation == "differ":
            conflicts.append({
                "field_id": fid,
                "values": {k: {"value": c.get("value"), "unit": c.get("unit"),
                               "paragraph_id": c.get("paragraph_id")}
                           for k, c in cells.items() if c.get("status") == "reported"},
                "reason": reason,
                "attribution": _attribute(fid, cells),
            })
        missing = [did for did in doc_ids if cells.get(did, {}).get("status") != "reported"]
        if missing and len(missing) < len(doc_ids):
            unreported.append({"field_id": fid, "documents": missing})

    comparability = _comparability(workorder, docset, rows_out, rows_by_doc)
    subset = [d["source_document_id"] for d in docset
              if _in_subset(d["source_document_id"], rows_out, comparability)]

    csv_path = None
    if out_dir:
        csv_path = _write_csv(os.path.join(out_dir, "comparison_matrix.csv"),
                              doc_ids, rows_out)
        if work_dir:
            try:
                _write_csv(os.path.join(work_dir, "comparison_matrix.csv"),
                           doc_ids, rows_out)
            except OSError:
                pass

    return {
        "workorder_id": workorder.get("workorder_id"),
        "research_question": workorder.get("research_question"),
        "documents": documents,
        "fields": field_ids,
        "matrix": matrix,
        "rows": rows_out,
        "comparability": comparability,
        "comparable_subset": subset,
        "noncomparable": [did for did in doc_ids if did not in subset],
        "agreements": [r["field_id"] for r in rows_out if r["relation"] == "agree"],
        "conflicts": conflicts,
        "unreported": unreported,
        "csv_path": "comparison_matrix.csv" if csv_path else None,
        "note": ("每个单元格都带 source_document_id 与 paragraph_id，取值逐字来自该文档；"
                 "不可比/未报告的条目保留原值，不做跨数据集合并。"),
    }


def _attribute(fid, cells):
    """差异归因：只写能从原文看出来的证据，看不出来写 unattributed。"""
    conds = {}
    for did, cell in cells.items():
        if cell.get("status") != "reported":
            continue
        if cell.get("experimental_condition"):
            conds[did] = cell["experimental_condition"]
        if cell.get("unit"):
            conds.setdefault("_units", {})[did] = cell["unit"]
    units = conds.pop("_units", {}) if isinstance(conds.get("_units"), dict) else {}
    if units and len(set(units.values())) > 1:
        return "unit_difference: 单位口径不同，需先换算再比较（本工具未换算）"
    if len(set(conds.values())) > 1 and conds:
        return "condition_difference: 实验条件不同（%s）" % "; ".join(
            "%s=%s" % (k, v) for k, v in conds.items())
    if fid in ("adsorbent", "material"):
        return "material_difference: 吸附材料不同，应在材料子组内比较"
    if fid in ("max_capacity", "capacity"):
        return "condition_difference: 容量差异可能来自初始浓度/pH/投加量，需按条件分层"
    return "unattributed: 原文未给出可判定的条件差异，保留原值待人工复核"


def _comparability(workorder, docset, rows_out, rows_by_doc):
    checks = workorder.get("comparability_checks") or [
        "task", "metric", "units", "material", "pollutant", "budget"]
    by_field = {r["field_id"]: r for r in rows_out}
    doc_ids = [d["source_document_id"] for d in docset]

    def covered(fid):
        r = by_field.get(fid)
        if not r:
            return []
        return [d for d in doc_ids if r["cells"].get(d, {}).get("status") == "reported"]

    metric_fields = [f for f in by_field if f in (
        "max_capacity", "capacity", "removal_efficiency", "adsorption_capacity",
        "uptake", "efficiency")]
    units = {}
    for fid in metric_fields:
        r = by_field[fid]
        units[fid] = {c.get("unit") or "" for c in r["cells"].values()
                      if c.get("status") == "reported"}

    materials = {d: next((r["cells"][d].get("value") for r in rows_out
                          if r["field_id"] == "adsorbent" and d in r["cells"]), None)
                 for d in doc_ids}
    pollutants = {d["source_document_id"]: sorted(
        _pollutants((d.get("doc") or {}).get("text", ""))) for d in docset}
    budgets = {d["source_document_id"]: sorted(
        _budget((d.get("doc") or {}).get("text", ""))) for d in docset}

    out = {}
    for name in checks:
        if name == "task":
            out[name] = {
                "status": "comparable" if len(doc_ids) >= 2 else "single_document",
                "reason": "工作单声明单一研究问题；%d 篇文档按同一问题纳入比较" % len(doc_ids),
            }
        elif name == "metric":
            if not metric_fields:
                out[name] = {"status": "unverified", "reason": "字段表中没有可识别的指标字段"}
            else:
                full = [f for f in metric_fields if len(covered(f)) == len(doc_ids)]
                out[name] = {
                    "status": "comparable" if full else "partial",
                    "reason": ("共同指标：%s" % ", ".join(full)) if full else
                              "没有一项指标在全部文档中都报告，只能做部分对照",
                    "fields": metric_fields,
                }
        elif name == "units":
            bad = [f for f, u in units.items() if len(u) > 1]
            empty = [f for f, u in units.items() if not any(u)]
            out[name] = {
                "status": "noncomparable" if bad else ("unverified" if empty else "comparable"),
                "reason": ("单位不一致的指标：%s；需换算后才能合并" % ", ".join(bad)) if bad
                          else ("以下指标未记录单位，不能直接合并数值：%s" % ", ".join(empty))
                          if empty else "指标单位在文档间一致，随值记录",
                "by_field": {f: sorted(u) for f, u in units.items()},
            }
        elif name == "material":
            vals = {k: v for k, v in materials.items() if v}
            same = len({str(v).lower() for v in vals.values()}) <= 1
            out[name] = {
                "status": "comparable" if same else "subgroup_only",
                "reason": ("材料相同：%s" % ", ".join(str(v) for v in vals.values())) if same
                          else "吸附材料不同（%s），只能在材料子组内比较，不做整体合并"
                               % "; ".join("%s=%s" % (k, v) for k, v in vals.items()),
            }
        elif name == "pollutant":
            sets = {k: set(v) for k, v in pollutants.items() if v}
            union = set().union(*sets.values()) if sets else set()
            same = len({frozenset(v) for v in sets.values()}) <= 1
            out[name] = {
                "status": "comparable" if same else "noncomparable",
                "reason": ("污染物一致：%s" % ", ".join(sorted(union))) if same
                          else "污染物不同（%s），不得合并数据集" % (
                              "; ".join("%s=%s" % (k, ",".join(sorted(v)) or "未识别")
                                        for k, v in sets.items()) or "未识别"),
            }
        elif name == "budget":
            sets = {k: set(v) for k, v in budgets.items() if v}
            same = len({frozenset(v) for v in sets.values()}) <= 1
            out[name] = {
                "status": "comparable" if same else "not_equal",
                "reason": "样本量/预算不同（%s），不把不同样本量的结果直接合并统计" % (
                    "; ".join("%s=%s" % (k, ",".join(sorted(v)) or "未报告")
                              for k, v in sets.items())) if not same else "样本量口径一致",
            }
        else:
            out[name] = {"status": "unverified", "reason": "工作单要求但本工具未实现该项判定"}
    return out


def _in_subset(doc_id, rows_out, comparability):
    if len(rows_out) == 0:
        return False
    if comparability.get("pollutant", {}).get("status") == "noncomparable":
        return False
    if comparability.get("units", {}).get("status") == "noncomparable":
        return False
    if comparability.get("metric", {}).get("status") == "unverified":
        return False
    return True


def _write_csv(path, doc_ids, rows_out):
    with open(path, "w", encoding="utf-8", newline="") as fh:
        writer = csv.writer(fh)
        header = ["field_id"]
        for did in doc_ids:
            header += ["%s.value" % did, "%s.unit" % did, "%s.paragraph_id" % did]
        header += ["relation", "note"]
        writer.writerow(header)
        for r in rows_out:
            line = [r["field_id"]]
            for did in doc_ids:
                cell = r["cells"].get(did) or {}
                line += [cell.get("value") or "", cell.get("unit") or "",
                         cell.get("paragraph_id") or ""]
            line += [r["relation"], r["note"]]
            writer.writerow(line)
    return path
