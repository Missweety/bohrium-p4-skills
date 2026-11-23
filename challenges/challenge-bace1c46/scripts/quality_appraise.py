#!/usr/bin/env python3
"""Validate and summarise structured research-quality appraisal rows (offline, stdlib).

Input rows carry one judgement per study x applicability domain:
  study_id, design, domain, judgement, evidence_file, evidence_locator, quote, note

The tool checks required fields and vocabulary, design-specific mandatory domains,
evidence locator/quote presence, duplicate rows and conflicting designs. It then
aggregates counts per domain and derives an overall judgement as the worst domain,
with an explicit, reasoned override allowed.

Writes:
  appraisal.json  structured appraisal per study + counts + issues
  appraisal.csv   row-level table with validation flags
  issues.csv      every validation issue
  report.md       readable appraisal report
  result.json     output_contract-mapped result when a case file is supplied

Judgement vocabulary: low | some_concerns | high | unclear.
Severity order: low < some_concerns < high. "unclear" is never treated as low.

Usage:
  python quality_appraise.py --input /input --out /app/output
  python quality_appraise.py --input rows.csv --overrides overrides.csv --out out
  python quality_appraise.py --input /input --case /input/case.json --out /app/output

Exit codes: 0 ok, 1 invalid input, 2 completed with validation issues.
"""

import argparse
import csv
import json
import os
import re
import sys
import unicodedata

RULES_VERSION = "quality-appraise/1.0"

JUDGEMENTS = ("low", "some_concerns", "high", "unclear")
SEVERITY = {"low": 0, "some_concerns": 1, "high": 2}

JUDGEMENT_ALIASES = {
    "low": ("low", "low_risk", "lowrisk", "low risk", "lowriskofbias", "低", "低风险"),
    "some_concerns": ("some_concerns", "someconcerns", "some concerns", "moderate",
                      "moderate_risk", "moderaterisk", "中", "中等", "部分担忧", "有些担忧"),
    "high": ("high", "high_risk", "highrisk", "high risk", "高", "高风险"),
    "unclear": ("unclear", "unclear_risk", "no_information", "noinformation", "ni", "unknown",
                "not_reported", "notreported", "无法判断", "不明确", "证据不足", "未报告"),
}

DESIGN_ALIASES = {
    "rct": ("rct", "randomized", "randomised", "randomized_controlled_trial",
            "randomised_controlled_trial", "parallel_rct", "cluster_rct", "crossover_rct",
            "随机对照试验", "随机对照"),
    "observational": ("observational", "observational_study", "cohort", "cohort_study",
                      "prospective_cohort", "retrospective_cohort", "case_control",
                      "cross_sectional", "longitudinal", "队列研究", "病例对照", "横断面", "观察性研究"),
    "diagnostic": ("diagnostic", "diagnostic_accuracy", "diagnostic_study",
                   "diagnostic_test_accuracy", "dta", "诊断准确性", "诊断试验"),
    "systematic_review": ("systematic_review", "systematicreview", "sr", "meta_analysis",
                          "metaanalysis", "meta_analysis_of_observational_studies",
                          "systematic_review_and_meta_analysis", "系统综述", "荟萃分析", "meta分析"),
}

DESIGN_DOMAINS = {
    "rct": {
        "randomization_process": ("randomization", "randomisation", "randomization_process",
                                  "randomisation_process", "sequence_generation",
                                  "allocation_concealment", "random_sequence_generation",
                                  "allocation", "随机化过程", "随机化", "随机序列", "分配隐藏",
                                  "序列生成"),
        "deviations_from_intended_interventions": ("deviations_from_intended_interventions",
                                                   "deviations", "deviation", "protocol_deviations",
                                                   "blinding", "performance_bias", "偏离既定干预",
                                                   "偏离干预", "方案偏离", "实施偏倚", "盲法"),
        "missing_outcome_data": ("missing_outcome_data", "attrition", "incomplete_outcome_data",
                                 "missing_outcomes", "loss_to_follow_up", "结局数据缺失",
                                 "结局缺失", "数据缺失", "失访"),
        "measurement_of_outcome": ("measurement_of_outcome", "measurement_of_outcomes",
                                   "outcome_measurement", "detection_bias",
                                   "blinding_of_outcome_assessment", "结局测量", "结果测量",
                                   "结局评估", "检测偏倚"),
        "selection_of_reported_result": ("selection_of_reported_result", "selective_reporting",
                                         "reporting_bias", "selective_outcome_reporting",
                                         "报告结果选择", "选择性报告", "报告偏倚"),
    },
    "observational": {
        "confounding": ("confounding", "confounding_bias", "confounders", "混杂", "混杂偏倚"),
        "selection_of_participants": ("selection_of_participants", "participant_selection",
                                      "selection_bias", "参与者选择", "研究对象选择",
                                      "选择偏倚"),
        "classification_of_interventions": ("classification_of_interventions",
                                            "intervention_classification", "exposure_classification",
                                            "干预分类", "暴露分类"),
        "missing_data": ("missing_data", "missing_outcome_data", "incomplete_data", "attrition",
                         "数据缺失", "缺失数据", "失访"),
        "measurement_of_outcomes": ("measurement_of_outcomes", "outcome_measurement",
                                    "measurement_of_outcome", "detection_bias", "结局测量",
                                    "结果测量", "检测偏倚"),
        "selection_of_reported_result": ("selection_of_reported_result", "selective_reporting",
                                         "reporting_bias", "报告结果选择", "选择性报告",
                                         "报告偏倚"),
    },
    "diagnostic": {
        "patient_selection": ("patient_selection", "patient_spectrum", "participant_selection",
                              "患者选择", "病例选择", "病例谱"),
        "index_test": ("index_test", "index_test_conduct", "index_test_interpretation",
                       "待评价试验", "指数试验", "待评试验"),
        "reference_standard": ("reference_standard", "reference_test", "reference_standard_conduct",
                               "参考标准", "金标准"),
        "flow_and_timing": ("flow_and_timing", "patient_flow", "timing", "flow", "流程与时机",
                            "病例流程", "时间间隔"),
    },
    "systematic_review": {
        "search_strategy": ("search_strategy", "search", "searching", "literature_search",
                            "检索策略", "文献检索", "检索"),
        "study_selection": ("study_selection", "selection_process", "screening", "研究选择",
                            "文献筛选", "筛选"),
        "data_collection": ("data_collection", "data_extraction", "abstraction", "数据提取",
                            "资料提取"),
        "risk_of_bias_assessment": ("risk_of_bias_assessment", "risk_of_bias", "quality_assessment",
                                    "偏倚风险评估", "风险偏倚", "质量评价"),
        "synthesis": ("synthesis", "evidence_synthesis", "statistical_synthesis", "meta_analysis",
                      "证据合成", "合并分析", "综合分析"),
        "reporting_completeness": ("reporting_completeness", "reporting", "publication_bias",
                                   "报告完整性", "发表偏倚"),
    },
}

GLOBAL_DOMAIN_ALIASES = {}
for _design, _domains in DESIGN_DOMAINS.items():
    for _canonical, _aliases in _domains.items():
        GLOBAL_DOMAIN_ALIASES.setdefault(_canonical, set()).update(_aliases)

ROW_ALIASES = {
    "study_id": ["study_id", "study", "id", "study_identifier", "研究编号", "文献编号", "研究标识"],
    "study_title": ["study_title", "title", "paper_title", "标题", "文献标题"],
    "design": ["design", "study_design", "design_type", "研究设计", "设计", "设计类型"],
    "domain": ["domain", "dimension", "appraisal_domain", "bias_domain", "评价域", "维度", "偏倚域"],
    "judgement": ["judgement", "judgment", "rating", "level", "判断", "等级", "评价"],
    "evidence_file": ["evidence_file", "file", "source_file", "证据文件", "文件"],
    "evidence_locator": ["evidence_locator", "locator", "location", "page", "section",
                         "证据位置", "定位", "位置"],
    "quote": ["quote", "quotation", "evidence_quote", "text", "原文", "引文", "证据片段"],
    "note": ["note", "notes", "comment", "rationale", "reason", "备注", "说明", "理由"],
    "reviewer": ["reviewer", "appraiser", "评价人", "评审人"],
    "overall_override": ["overall_override", "overall", "总体等级", "总体"],
    "overall_reason": ["overall_reason", "override_reason", "reason", "总体理由", "覆盖理由"],
}

AUX_HINTS = ("override", "contract", "schema", "manifest", "supplement", "classif")
ROW_HINTS = ("apprais", "assess", "judg", "rating", "quality", "domain", "row", "table")

# ---------------------------------------------------------------- helpers


def sval(value):
    if value is None:
        return ""
    if isinstance(value, (list, tuple)):
        return "; ".join(part for part in (sval(v) for v in value) if part)
    if isinstance(value, dict):
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    return str(value).strip()


def norm_key(key):
    key = unicodedata.normalize("NFKC", str(key)).strip().lower()
    key = re.sub(r"[^0-9a-z\u4e00-\u9fff]+", "_", key)
    return key.strip("_")


def pick(row, aliases, default=""):
    for alias in aliases:
        key = norm_key(alias)
        if key in row and row[key] != "":
            return row[key]
    return default


def _normalise_row(row):
    out = {}
    for key, value in row.items():
        if key is None:
            continue
        nkey = norm_key(key)
        if not nkey:
            continue
        text = sval(value)
        if nkey not in out or (not out[nkey] and text):
            out[nkey] = text
    return out


def _delimiter(first_line, ext):
    if ext == ".tsv":
        return "\t"
    return max([",", ";", "\t"], key=first_line.count)


def read_table(path):
    ext = os.path.splitext(path)[1].lower()
    rows = []
    if ext in {".csv", ".tsv"}:
        with open(path, encoding="utf-8-sig", errors="replace", newline="") as handle:
            first = handle.readline()
            handle.seek(0)
            reader = csv.DictReader(handle, delimiter=_delimiter(first, ext))
            for row in reader:
                item = _normalise_row(row)
                if any(item.values()):
                    rows.append(item)
        return rows
    if ext == ".jsonl":
        with open(path, encoding="utf-8-sig", errors="replace") as handle:
            for line in handle:
                if not line.strip():
                    continue
                try:
                    data = json.loads(line)
                except json.JSONDecodeError as exc:
                    raise ValueError("%s: invalid JSON line: %s" % (path, exc))
                if isinstance(data, dict):
                    rows.append(_normalise_row(data))
        return rows
    if ext == ".json":
        with open(path, encoding="utf-8-sig", errors="replace") as handle:
            try:
                data = json.load(handle)
            except json.JSONDecodeError as exc:
                raise ValueError("%s: invalid JSON: %s" % (path, exc))
        if isinstance(data, list):
            items = data
        elif isinstance(data, dict):
            items = None
            for key in ("appraisals", "rows", "items", "judgements", "judgments",
                        "ratings", "records", "data", "studies"):
                if isinstance(data.get(key), list):
                    items = data[key]
                    break
            if items is None:
                items = [data]
        else:
            raise ValueError("%s: JSON root must be an object or array" % path)
        for item in items:
            if isinstance(item, dict):
                rows.append(_normalise_row(item))
        return rows
    raise ValueError("%s: unsupported extension %s" % (path, ext))


def canon_design(value):
    key = norm_key(value)
    if not key:
        return "", False
    for design, aliases in DESIGN_ALIASES.items():
        if key == norm_key(design) or key in {norm_key(a) for a in aliases}:
            return design, True
    return sval(value), False


def canon_judgement(value):
    key = norm_key(value)
    if not key:
        return "", False, ""
    for canonical, aliases in JUDGEMENT_ALIASES.items():
        if key == norm_key(canonical) or key in {norm_key(a) for a in aliases}:
            note = ""
            if canonical == "some_concerns" and key in {norm_key("moderate"),
                                                        norm_key("moderate_risk"),
                                                        norm_key("moderaterisk")}:
                note = "alias 'moderate' mapped to some_concerns"
            return canonical, True, note
    return sval(value), False, ""


def canon_domain(design, value):
    key = norm_key(value)
    if not key:
        return "", False
    if design in DESIGN_DOMAINS:
        for canonical, aliases in DESIGN_DOMAINS[design].items():
            if key == norm_key(canonical) or key in {norm_key(a) for a in aliases}:
                return canonical, True
    for canonical, aliases in GLOBAL_DOMAIN_ALIASES.items():
        if key == norm_key(canonical) or key in {norm_key(a) for a in aliases}:
            return canonical, False
    return sval(value).strip(), False


def evidence_looks_weak(locator):
    return bool(re.fullmatch(r"\d+(?:\s*[-–]\s*\d+)?", locator))


# ---------------------------------------------------------------- input


def discover_rows(input_path, explicit_rows):
    if explicit_rows:
        return [explicit_rows], []
    limits = []
    if os.path.isfile(input_path):
        return [input_path], limits
    if not os.path.isdir(input_path):
        raise ValueError("input path not found: %s" % input_path)
    candidates = sorted(
        os.path.join(input_path, name) for name in os.listdir(input_path)
        if os.path.splitext(name)[1].lower() in {".csv", ".tsv", ".json", ".jsonl"}
        and os.path.isfile(os.path.join(input_path, name))
        and name.casefold() not in {"case.json", "case.yaml", "case.yml"}
        and not any(hint in name.casefold() for hint in AUX_HINTS)
    )
    if not candidates:
        raise ValueError("%s: no .csv/.tsv/.json/.jsonl appraisal file found" % input_path)

    def has_appraisal_columns(path):
        try:
            rows = read_table(path)[:3]
        except ValueError:
            return False
        keys = {key for row in rows for key in row}
        return (any(norm_key(a) in keys for a in ROW_ALIASES["domain"])
                and any(norm_key(a) in keys for a in ROW_ALIASES["judgement"]))

    hinted = [p for p in candidates if any(h in os.path.basename(p).casefold() for h in ROW_HINTS)]
    matching = [p for p in candidates if has_appraisal_columns(p)]
    if matching:
        return matching, limits
    if len(hinted) == 1:
        return hinted, limits
    if len(candidates) == 1:
        return candidates, limits
    raise ValueError(
        "%s: multiple files and none looks like an appraisal table; pass --rows explicitly. "
        "Files: %s" % (input_path, ", ".join(os.path.basename(p) for p in candidates)))


def load_rows(paths):
    rows = []
    for path in paths:
        for index, row in enumerate(read_table(path), 1):
            row["_source"] = os.path.basename(path)
            row["_row"] = index
            rows.append(row)
    rows.sort(key=lambda r: (r["_source"], r["_row"]))
    return rows


def load_overrides(path):
    if not path:
        return {}
    if not os.path.exists(path):
        raise ValueError("override file not found: %s" % path)
    out = {}
    for row in read_table(path):
        study_id = pick(row, ROW_ALIASES["study_id"])
        overall_raw = pick(row, ROW_ALIASES["overall_override"])
        reason = pick(row, ROW_ALIASES["overall_reason"])
        if study_id:
            out[study_id] = {"overall_raw": overall_raw, "reason": reason}
    return out


def discover_overrides(input_path):
    if not os.path.isdir(input_path):
        return ""
    for name in sorted(os.listdir(input_path)):
        lower = name.casefold()
        if "override" in lower and os.path.splitext(name)[1].lower() in {".csv", ".tsv", ".json", ".jsonl"}:
            return os.path.join(input_path, name)
    return ""


def build_evidence_inventory(input_path):
    inventory = set()
    if not os.path.isdir(input_path):
        return inventory
    for dirpath, dirnames, filenames in os.walk(input_path):
        dirnames.sort()
        for name in sorted(filenames):
            full = os.path.join(dirpath, name)
            inventory.add(os.path.relpath(full, input_path).casefold())
            inventory.add(name.casefold())
    return inventory


def checked_files(input_path):
    """List files inspected under the input path for blocked reporting."""
    if not input_path:
        return []
    if os.path.isfile(input_path):
        return [os.path.basename(input_path)]
    if not os.path.isdir(input_path):
        return []
    names = []
    for dirpath, dirnames, filenames in os.walk(input_path):
        dirnames.sort()
        for name in sorted(filenames):
            names.append(os.path.relpath(os.path.join(dirpath, name), input_path))
    return names


def write_blocked(out_dir, input_path, case, case_path, reason):
    """Write a status=blocked result.json (and report.md) before exiting non-zero."""
    files = checked_files(input_path)
    guidance = ("输入中没有可用评价行。请先阅读原文，把每项研究每个适用域的判断写入 "
                "/app/work/appraisals.csv（study_id, design, domain, judgement, "
                "evidence_file, evidence_locator, quote, note），再用 "
                "--rows /app/work/appraisals.csv 重跑；非 unclear 判断必须有定位与逐字引文。"
                "无法产出评价行时保持 blocked，不得编造等级或原文。")
    uncertainty = ["blocked: 没有评价行，未生成任何判断、域计数或总体等级。"]
    limits = ["blocked: " + reason]
    result = {
        "case_id": case_id_of(case) if case else "",
        "status": "blocked",
        "reason": reason,
        "blocked_input": guidance,
        "checked_files": files,
        "appraisal": [],
        "appraisal_table": "appraisal.csv",
        "overall": {},
        "overall_summary": "blocked: " + reason,
        "domain_counts": {},
        "issues": [],
        "report": "report.md",
        "evidence": {"inputs": {"input": input_path, "checked_files": files}},
        "uncertainty": uncertainty,
        "limits": limits,
        "changes": [],
        "artifacts": ["result.json", "report.md"],
        "rules_version": RULES_VERSION,
    }
    fields = contract_fields(case) if case else []
    if fields:
        mapped, unused, unresolved = map_contract(fields, {
            "case_id": result["case_id"],
            "status": "blocked",
            "appraisal": [],
            "appraisal_table": "appraisal.csv",
            "overall": {},
            "overall_summary": result["overall_summary"],
            "domain_counts": {},
            "issues": [],
            "report": "report.md",
            "evidence": result["evidence"],
            "uncertainty": uncertainty,
            "limits": limits,
            "changes": [],
        })
        result.update(mapped)
        result["contract_mapping"] = {
            "source": os.path.basename(case_path) if case_path else "",
            "requested_fields": fields,
            "unresolved_fields": unresolved,
            "unused_core_fields": unused,
            "note": "blocked run: no evidence-backed value; do not invent them",
        }

    os.makedirs(out_dir, exist_ok=True)
    with open(os.path.join(out_dir, "result.json"), "w", encoding="utf-8") as handle:
        json.dump(result, handle, ensure_ascii=False, indent=1)
    with open(os.path.join(out_dir, "report.md"), "w", encoding="utf-8") as handle:
        handle.write("# 文献研究质量评价报告\n\n")
        handle.write("- 状态：`blocked`\n")
        handle.write("- 原因：%s\n" % reason)
        handle.write("- 已检查文件：%s\n" % (
            ", ".join("`%s`" % name for name in files) or "(无)"))
        handle.write("\n%s\n" % guidance)
    return result


# ---------------------------------------------------------------- contract


CONTRACT_ALIASES = {
    "case_id": ["case_id", "caseid"],
    "appraisal": ["appraisal", "appraisals", "studies", "evaluation", "quality_appraisal",
                  "quality_evaluation", "study_appraisal"],
    "appraisal_table": ["appraisal_table", "appraisal_csv", "table", "rows", "domain_table"],
    "overall": ["overall", "overall_judgement", "overall_rating", "总体等级"],
    "overall_summary": ["overall_summary", "summary", "conclusions", "headline"],
    "domain_counts": ["domain_counts", "counts", "domain_summary", "domains"],
    "issues": ["issues", "problems", "flags", "quality_issues"],
    "report": ["report", "report_path", "readable_report", "report_file"],
    "evidence": ["evidence", "evidence_map", "sources", "provenance"],
    "uncertainty": ["uncertainty", "uncertainties", "open_questions"],
    "limits": ["limits", "limitations", "constraints"],
    "changes": ["changes", "change_log"],
    "status": ["status", "run_status"],
}


def contract_fields(case):
    if not isinstance(case, dict):
        return []
    contract = case.get("output_contract", case.get("outputContract"))
    if isinstance(contract, list):
        return [sval(item) for item in contract if sval(item)]
    if isinstance(contract, dict):
        return [sval(key) for key in contract if sval(key)]
    if isinstance(contract, str):
        return [part.strip() for part in re.split(r"[,;\n]", contract) if part.strip()]
    return []


def case_id_of(case):
    if not isinstance(case, dict):
        return ""
    for key in ("case_id", "caseId", "id"):
        if sval(case.get(key)):
            return sval(case.get(key))
    return ""


def map_contract(fields, canonical):
    mapped = {}
    used = set()
    unresolved = []
    for field in fields:
        nkey = norm_key(field)
        target = None
        for name, aliases in CONTRACT_ALIASES.items():
            if nkey == norm_key(name) or nkey in {norm_key(a) for a in aliases}:
                target = name
                break
        if target and target in canonical:
            mapped[field] = canonical[target]
            used.add(target)
        elif nkey in canonical:
            mapped[field] = canonical[nkey]
            used.add(nkey)
        else:
            mapped[field] = None
            unresolved.append(field)
    return mapped, sorted(set(canonical) - used), unresolved


# ---------------------------------------------------------------- appraisal


def issue(severity, code, message, study_id="", domain="", row=None, source=""):
    return {"severity": severity, "code": code, "message": message,
            "study_id": study_id, "domain": domain, "row": row, "source_file": source}


def appraise(rows, overrides, evidence_inventory):
    issues = []
    prepared = []

    for row in rows:
        study_id = pick(row, ROW_ALIASES["study_id"])
        design_raw = pick(row, ROW_ALIASES["design"])
        domain_raw = pick(row, ROW_ALIASES["domain"])
        judgement_raw = pick(row, ROW_ALIASES["judgement"])
        evidence_file = pick(row, ROW_ALIASES["evidence_file"])
        locator = pick(row, ROW_ALIASES["evidence_locator"])
        quote = pick(row, ROW_ALIASES["quote"])
        note = pick(row, ROW_ALIASES["note"])
        design, design_valid = canon_design(design_raw)
        judgement, judgement_valid, judgement_note = canon_judgement(judgement_raw)
        domain, domain_applicable = canon_domain(design, domain_raw)
        row_no = row["_row"]
        source = row["_source"]

        if not study_id:
            issues.append(issue("error", "missing_study_id",
                                "row has no study_id", "", domain, row_no, source))
        if not design_raw:
            issues.append(issue("error", "missing_design",
                                "row has no study design", study_id, domain, row_no, source))
        elif not design_valid:
            issues.append(issue("error", "unknown_design",
                                "design '%s' is not one of rct/observational/diagnostic/systematic_review"
                                % design_raw, study_id, domain, row_no, source))
        if not domain_raw:
            issues.append(issue("error", "missing_domain",
                                "row has no appraisal domain", study_id, domain, row_no, source))
        if not judgement_raw:
            issues.append(issue("error", "missing_judgement",
                                "row has no judgement", study_id, domain, row_no, source))
        elif not judgement_valid:
            issues.append(issue("error", "invalid_judgement",
                                "judgement '%s' is not low/some_concerns/high/unclear" % judgement_raw,
                                study_id, domain, row_no, source))
        if judgement_note:
            issues.append(issue("warning", "judgement_alias",
                                judgement_note, study_id, domain, row_no, source))

        if judgement_valid and judgement != "unclear":
            for label, value in (("evidence_file", evidence_file),
                                 ("evidence_locator", locator),
                                 ("quote", quote)):
                if not value:
                    issues.append(issue("error", "missing_%s" % label,
                                        "judgement '%s' requires %s" % (judgement, label),
                                        study_id, domain, row_no, source))
        if quote and len(quote) < 12:
            issues.append(issue("warning", "short_quote",
                                "quote shorter than 12 characters; check it is verbatim evidence",
                                study_id, domain, row_no, source))
        if locator and evidence_looks_weak(locator):
            issues.append(issue("warning", "locator_without_unit",
                                "locator '%s' has no page/section/table unit" % locator,
                                study_id, domain, row_no, source))
        if judgement == "unclear" and not note and not quote:
            issues.append(issue("warning", "unclear_without_note",
                                "unclear judgement has no note explaining missing evidence",
                                study_id, domain, row_no, source))
        if evidence_file and evidence_inventory:
            if evidence_file.casefold() not in evidence_inventory:
                issues.append(issue("warning", "evidence_file_not_found",
                                    "evidence_file '%s' not found under the input directory" % evidence_file,
                                    study_id, domain, row_no, source))

        evidence_ok = bool(evidence_file and locator and quote)
        usable = bool(study_id and domain and judgement_valid)
        prepared.append({
            "study_id": study_id,
            "study_title": pick(row, ROW_ALIASES["study_title"]),
            "design": design,
            "design_valid": design_valid,
            "domain": domain,
            "domain_applicable": domain_applicable,
            "judgement": judgement,
            "judgement_valid": judgement_valid,
            "evidence_file": evidence_file,
            "evidence_locator": locator,
            "quote": quote,
            "note": note,
            "reviewer": pick(row, ROW_ALIASES["reviewer"]),
            "overall_override": pick(row, ROW_ALIASES["overall_override"]),
            "overall_reason": pick(row, ROW_ALIASES["overall_reason"]),
            "evidence_ok": evidence_ok,
            "usable": usable,
            "source_file": source,
            "row": row_no,
        })

    # Group usable rows into studies, keeping input order.
    studies = {}
    study_order = []
    for item in prepared:
        if not item["usable"]:
            continue
        sid = item["study_id"]
        if sid not in studies:
            studies[sid] = {"study_id": sid, "study_title": item["study_title"],
                            "design": "", "design_valid": False, "rows": [],
                            "seen_domains": set(), "excluded_duplicates": []}
            study_order.append(sid)
        study = studies[sid]
        if not study["study_title"] and item["study_title"]:
            study["study_title"] = item["study_title"]
        if item["design"]:
            if item["design_valid"]:
                if not study["design_valid"]:
                    study["design"] = item["design"]
                    study["design_valid"] = True
                elif study["design"] != item["design"]:
                    issues.append(issue("error", "design_conflict",
                                        "study has conflicting designs: %s vs %s"
                                        % (study["design"], item["design"]),
                                        sid, item["domain"], item["row"], item["source_file"]))
            elif not study["design"]:
                study["design"] = item["design"]

    # Attach rows, detect duplicates and domain applicability.
    for item in prepared:
        if not item["usable"]:
            continue
        study = studies[item["study_id"]]
        domain = item["domain"]
        if item["judgement_valid"] and item["judgement"] != "unclear" \
                and not item["evidence_ok"]:
            # A level without file/locator/quote cannot support a domain judgement;
            # keep the row visible but exclude it from counts and overall.
            item["included_in_summary"] = False
            study["rows"].append(item)
            issues.append(issue("error", "insufficient_evidence",
                                "judgement '%s' for domain '%s' lacks a complete "
                                "evidence_file/locator/quote; excluded from domain counts "
                                "and overall" % (item["judgement"], domain),
                                item["study_id"], domain, item["row"], item["source_file"]))
            continue
        if domain in study["seen_domains"]:
            item["included_in_summary"] = False
            study["excluded_duplicates"].append(domain)
            issues.append(issue("error", "duplicate_domain",
                                "duplicate row for study/domain; first row kept",
                                item["study_id"], domain, item["row"], item["source_file"]))
            study["rows"].append(item)
            continue
        study["seen_domains"].add(domain)
        item["included_in_summary"] = True
        study["rows"].append(item)
        if item["design_valid"] and study["design"] in DESIGN_DOMAINS:
            applicable = set(DESIGN_DOMAINS[study["design"]].keys())
            if domain not in applicable:
                issues.append(issue("warning", "domain_not_applicable",
                                    "domain '%s' is not in the mandatory set for %s"
                                    % (domain, study["design"]),
                                    item["study_id"], domain, item["row"], item["source_file"]))

    study_outputs = []
    for sid in study_order:
        study = studies[sid]
        design = study["design"]
        applicable_list = sorted(DESIGN_DOMAINS.get(design, {}).keys())
        summary_rows = [r for r in study["rows"] if r.get("included_in_summary")]
        present = {r["domain"] for r in summary_rows}
        missing = [d for d in applicable_list if d not in present]
        for domain in missing:
            issues.append(issue("error", "missing_domain",
                                "mandatory domain '%s' missing for %s" % (domain, design),
                                sid, domain, None, ""))

        counts = {key: 0 for key in JUDGEMENTS}
        for item in summary_rows:
            if item["judgement_valid"]:
                counts[item["judgement"]] += 1

        applicable_set = set(applicable_list)
        eligible = [r for r in summary_rows
                    if r["judgement_valid"]
                    and (not study["design_valid"] or r["domain"] in applicable_set)]
        scored = [r for r in eligible if r["judgement"] in SEVERITY]
        worst_domains = []
        if scored:
            worst = max(SEVERITY[r["judgement"]] for r in scored)
            overall = [name for name, value in SEVERITY.items() if value == worst][0]
            worst_domains = sorted(r["domain"] for r in scored if SEVERITY[r["judgement"]] == worst)
            overall_source = "worst_domain"
        elif any(r["judgement"] == "unclear" for r in eligible):
            overall = "unclear"
            overall_source = "all_unclear"
        else:
            overall = "unknown"
            overall_source = "no_valid_judgement"

        overall_reason = ""
        if overall_source == "no_valid_judgement":
            overall_reason = ("no evidence-backed judgement in the applicable domains; "
                              "the level is left unknown instead of being filled in")
        override = overrides.get(sid)
        if override is None:
            for item in summary_rows + [r for r in study["rows"] if not r.get("included_in_summary")]:
                if item["overall_override"]:
                    override = {"overall_raw": item["overall_override"],
                                "reason": item["overall_reason"]}
                    break
        if override:
            override_value, override_valid, _ = canon_judgement(override["overall_raw"])
            reason = sval(override["reason"])
            if not override_valid:
                issues.append(issue("error", "invalid_override",
                                    "overall override '%s' is not a valid judgement"
                                    % override["overall_raw"], sid, "", None, ""))
            elif not reason:
                issues.append(issue("error", "override_without_reason",
                                    "overall override ignored because reason is empty",
                                    sid, "", None, ""))
            else:
                overall = override_value
                overall_source = "override"
                overall_reason = reason

        if design and design in DESIGN_DOMAINS and missing:
            pass  # missing-domain issues already recorded

        study_outputs.append({
            "study_id": sid,
            "study_title": study["study_title"],
            "design": design,
            "design_valid": study["design_valid"],
            "applicable_domains": applicable_list,
            "present_domains": sorted(present),
            "missing_domains": missing,
            "counts": counts,
            "worst_domains": worst_domains,
            "overall": overall,
            "overall_source": overall_source,
            "overall_reason": overall_reason,
            "excluded_duplicates": sorted(set(study["excluded_duplicates"])),
            "domains": [{
                "domain": r["domain"],
                "judgement": r["judgement"],
                "judgement_valid": r["judgement_valid"],
                "evidence_file": r["evidence_file"],
                "evidence_locator": r["evidence_locator"],
                "quote": r["quote"],
                "note": r["note"],
                "evidence_ok": r["evidence_ok"],
                "applicable": r["domain_applicable"],
                "row": r["row"],
                "source_file": r["source_file"],
            } for r in summary_rows],
        })

    # Aggregate domain counts across studies.
    domain_counts = {}
    for study in study_outputs:
        for item in study["domains"]:
            if not item["judgement_valid"]:
                continue
            bucket = domain_counts.setdefault(item["domain"], {key: 0 for key in JUDGEMENTS})
            bucket[item["judgement"]] += 1

    counts = {
        "studies": len(study_outputs),
        "rows": len(prepared),
        "usable_rows": sum(1 for item in prepared if item["usable"]),
        "by_design": {},
        "by_judgement": {key: 0 for key in JUDGEMENTS},
        "by_domain": {key: domain_counts[key] for key in sorted(domain_counts)},
    }
    for study in study_outputs:
        counts["by_design"][study["design"] or "(unknown)"] = \
            counts["by_design"].get(study["design"] or "(unknown)", 0) + 1
        for key in JUDGEMENTS:
            counts["by_judgement"][key] += study["counts"][key]

    severity_count = {key: sum(1 for i in issues if i["severity"] == key) for key in ("error", "warning")}
    return prepared, study_outputs, counts, issues, severity_count


# ---------------------------------------------------------------- outputs


def write_csv(path, fieldnames, rows):
    with open(path, "w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def render_report(core):
    lines = []
    lines.append("# 文献研究质量评价报告")
    lines.append("")
    lines.append("> 本报告由 `scripts/quality_appraise.py`（规则版本 %s）基于输入评价行生成。" % RULES_VERSION)
    lines.append("> 每条判断都应对应原文证据位置；“证据不足”不会被补成一个看起来合理的等级。")
    lines.append("")
    lines.append("## 1. 输入与状态")
    lines.append("")
    lines.append("- 输入文件：%s" % (", ".join("`%s`" % name for name in core["inputs"]["row_files"]) or "(无)"))
    lines.append("- 原始行数：%d；可用行数：%d；研究数：%d"
                 % (core["counts"]["rows"], core["counts"]["usable_rows"], core["counts"]["studies"]))
    lines.append("- 状态：`%s`；错误 %d 条，警告 %d 条"
                 % (core["status"], core["issue_summary"]["error"], core["issue_summary"]["warning"]))
    lines.append("- 判定词汇：`low` / `some_concerns` / `high` / `unclear`；"
                 "overall 取最差域（low < some_concerns < high），`unclear` 不参与排序。")
    lines.append("")
    lines.append("## 2. 研究设计与适用域")
    lines.append("")
    lines.append("| study_id | 设计 | 适用域（必填） | 已覆盖 | 缺失 | overall | 来源 |")
    lines.append("|-|-|-|-|-|-|-|")
    for study in core["studies"]:
        lines.append("| %s | %s | %s | %s | %s | %s | %s |" % (
            _cell(study["study_id"]), _cell(study["design"]),
            _cell(", ".join(study["applicable_domains"])),
            _cell(", ".join(study["present_domains"])),
            _cell(", ".join(study["missing_domains"])),
            study["overall"], study["overall_source"]))
    lines.append("")
    lines.append("## 3. 各域判断")
    lines.append("")
    lines.append("| study_id | 域 | 判断 | 证据位置 | 原文片段 |")
    lines.append("|-|-|-|-|-|")
    for study in core["studies"]:
        for item in study["domains"]:
            lines.append("| %s | %s | %s | %s | %s |" % (
                _cell(study["study_id"]), _cell(item["domain"]), item["judgement"],
                _cell("%s %s" % (item["evidence_file"], item["evidence_locator"])),
                _cell(_truncate(item["quote"], 80))))
    lines.append("")
    lines.append("## 4. 域计数")
    lines.append("")
    lines.append("| 域 | low | some_concerns | high | unclear |")
    lines.append("|-|-|-|-|-|")
    for domain in sorted(core["counts"]["by_domain"]):
        bucket = core["counts"]["by_domain"][domain]
        lines.append("| %s | %d | %d | %d | %d |" % (
            domain, bucket["low"], bucket["some_concerns"], bucket["high"], bucket["unclear"]))
    lines.append("")
    lines.append("## 5. 校验问题")
    lines.append("")
    if core["issues"]:
        lines.append("| 级别 | 代码 | study_id | 域 | 行 | 说明 |")
        lines.append("|-|-|-|-|-|-|")
        for item in core["issues"]:
            lines.append("| %s | %s | %s | %s | %s | %s |" % (
                item["severity"], item["code"], _cell(item["study_id"]),
                _cell(item["domain"]), "" if item["row"] is None else item["row"],
                _cell(item["message"])))
        lines.append("")
        lines.append("错误项必须修正后才能声称评价完整；警告项需人工确认，不自动改判。")
    else:
        lines.append("未发现问题。")
    lines.append("")
    lines.append("## 6. 不确定性与限制")
    lines.append("")
    for item in core["uncertainty"]:
        lines.append("- %s" % item)
    for item in core["limits"]:
        lines.append("- %s" % item)
    if not core["uncertainty"] and not core["limits"]:
        lines.append("- 未发现额外限制。")
    lines.append("")
    lines.append("## 7. 人工复核入口")
    lines.append("")
    lines.append("- 逐条核对 `appraisal.csv` 的 `evidence_file` 与 `evidence_locator` 是否指向原文。")
    lines.append("- 对 `unclear` 行确认是否真的“未见迹象/证据不足”，而不是漏读。")
    lines.append("- 对 `overall_source=override` 的行检查理由是否充分。")
    lines.append("- 复核结论写回 `note` 或独立复核表；不直接覆盖原始判断。")
    lines.append("")
    lines.append("## 8. 复跑")
    lines.append("")
    lines.append("```bash")
    lines.append("python scripts/quality_appraise.py --input /input --case /input/case.json --out /app/output")
    lines.append("```")
    lines.append("")
    return "\n".join(lines)


def _cell(value):
    text = sval(value).replace("|", "\\|").replace("\n", " ")
    return text if text else "—"


def _truncate(text, limit):
    text = sval(text)
    return text if len(text) <= limit else text[:limit] + "…"


def embedded_appraisals(case):
    """Return appraisal rows embedded in case.json when they carry domain+judgement."""
    if not isinstance(case, dict):
        return None
    for key in ("appraisals", "rows", "items", "judgements", "judgments", "ratings", "records"):
        value = case.get(key)
        if not isinstance(value, list) or not value or not isinstance(value[0], dict):
            continue
        keys = {norm_key(k) for k in value[0]}
        has_domain = any(norm_key(a) in keys for a in ROW_ALIASES["domain"])
        has_judgement = any(norm_key(a) in keys for a in ROW_ALIASES["judgement"])
        if has_domain and has_judgement:
            return value
    return None


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--input", required=True, help="input directory or appraisal table")
    parser.add_argument("--out", required=True, help="output directory")
    parser.add_argument("--rows", help="explicit appraisal CSV/JSON")
    parser.add_argument("--overrides", help="explicit overall override CSV/JSON")
    parser.add_argument("--case", default="", help="case.json providing case_id and output_contract")
    args = parser.parse_args(argv)

    case = None
    case_path = args.case
    if not case_path:
        candidate = os.path.join(args.input, "case.json") if os.path.isdir(args.input) else \
            os.path.join(os.path.dirname(os.path.abspath(args.input)), "case.json")
        if os.path.isfile(candidate):
            case_path = candidate
    limits = []
    if case_path and os.path.exists(case_path):
        try:
            with open(case_path, encoding="utf-8-sig") as handle:
                case = json.load(handle)
        except (OSError, json.JSONDecodeError) as exc:
            limits.append("case.json unreadable: %s" % exc)

    try:
        items = None if args.rows else embedded_appraisals(case)
        if items is not None:
            paths = [case_path]
            rows = []
            for index, item in enumerate(items, 1):
                if not isinstance(item, dict):
                    continue
                row = _normalise_row(item)
                row["_source"] = os.path.basename(case_path)
                row["_row"] = index
                rows.append(row)
        else:
            paths, extra_limits = discover_rows(args.input, args.rows)
            limits.extend(extra_limits)
            rows = load_rows(paths)
        override_path = args.overrides or discover_overrides(args.input)
        overrides = load_overrides(override_path)
    except (ValueError, OSError) as exc:
        write_blocked(args.out, args.input, case, case_path, str(exc))
        print("error: %s" % exc, file=sys.stderr)
        return 1

    evidence_inventory = build_evidence_inventory(args.input)
    prepared, studies, counts, issues, severity_count = appraise(rows, overrides, evidence_inventory)

    uncertainty = []
    unclear_studies = [s["study_id"] for s in studies
                       if any(d["judgement"] == "unclear" for d in s["domains"])]
    if unclear_studies:
        uncertainty.append("含 unclear 判断的研究：%s（未按低风险处理）" % ", ".join(unclear_studies))
    overridden = [s["study_id"] for s in studies if s["overall_source"] == "override"]
    if overridden:
        uncertainty.append("overall 被理由覆盖：%s（请按理由逐条复核）" % ", ".join(overridden))
    missing_design = sorted({d["study_id"] for d in prepared if not d["design_valid"]})
    if missing_design:
        uncertainty.append("设计缺失或不在四类中的研究：%s；未做适用域完整性判断"
                           % ", ".join(missing_design))
    unknown_studies = [s["study_id"] for s in studies if s["overall"] == "unknown"]
    if unknown_studies:
        uncertainty.append("以下研究在适用域内没有证据齐全的有效判断，overall 记为 unknown：%s"
                           % ", ".join(unknown_studies))
    if not rows:
        uncertainty.append("输入评价行为空，未生成任何判断。")

    if not rows:
        status = "blocked"
    elif severity_count["error"]:
        status = "partial"
    elif limits:
        status = "partial"
    else:
        status = "ok"

    core = {
        "rules_version": RULES_VERSION,
        "status": status,
        "inputs": {
            "input": args.input,
            "row_files": [os.path.basename(p) for p in paths],
            "row_count": len(rows),
            "override_file": os.path.basename(override_path) if override_path else "",
        },
        "vocabulary": {
            "judgement": list(JUDGEMENTS),
            "severity_order": ["low", "some_concerns", "high"],
            "unclear_not_low": True,
            "overall_rule": "worst domain; explicit override requires a non-empty reason",
            "design_domains": {key: sorted(value.keys()) for key, value in DESIGN_DOMAINS.items()},
        },
        "studies": studies,
        "counts": counts,
        "issues": issues,
        "issue_summary": severity_count,
        "uncertainty": uncertainty,
        "limits": limits,
        "artifacts": ["appraisal.json", "appraisal.csv", "issues.csv", "report.md",
                      "result.json"],
        "changes": [],
    }
    core["summary"] = ("%d 项研究、%d 条评价行；overall：%s；错误 %d、警告 %d。"
                       % (len(studies), len(rows),
                          ", ".join("%s=%s" % (s["study_id"], s["overall"]) for s in studies),
                          severity_count["error"], severity_count["warning"]))

    os.makedirs(args.out, exist_ok=True)
    row_fields = ["study_id", "study_title", "design", "domain", "judgement",
                  "evidence_file", "evidence_locator", "quote", "note",
                  "judgement_valid", "evidence_ok", "included_in_summary",
                  "overall_override", "overall_reason", "reviewer",
                  "source_file", "row"]
    row_output = []
    for item in prepared:
        row = dict(item)
        row["included_in_summary"] = item.get("included_in_summary", False)
        row_output.append(row)
    write_csv(os.path.join(args.out, "appraisal.csv"), row_fields, row_output)

    issue_fields = ["severity", "code", "study_id", "domain", "row", "message", "source_file"]
    write_csv(os.path.join(args.out, "issues.csv"), issue_fields, issues)

    with open(os.path.join(args.out, "appraisal.json"), "w", encoding="utf-8") as handle:
        json.dump(core, handle, ensure_ascii=False, indent=1)

    with open(os.path.join(args.out, "report.md"), "w", encoding="utf-8") as handle:
        handle.write(render_report(core))

    result = {
        "case_id": case_id_of(case) if case else "",
        "status": core["status"],
        "appraisal": studies,
        "appraisal_table": "appraisal.csv",
        "overall": {study["study_id"]: {
            "overall": study["overall"],
            "overall_source": study["overall_source"],
            "overall_reason": study["overall_reason"],
            "worst_domains": study["worst_domains"],
        } for study in studies},
        "overall_summary": core["summary"],
        "domain_counts": counts["by_domain"],
        "issues": issues,
        "report": "report.md",
        "evidence": {
            "inputs": core["inputs"],
            "vocabulary": core["vocabulary"],
            "appraisal_json": "appraisal.json",
            "issues_csv": "issues.csv",
        },
        "uncertainty": uncertainty,
        "limits": limits,
        "changes": [],
        "artifacts": core["artifacts"],
        "rules_version": RULES_VERSION,
    }
    fields = contract_fields(case) if case else []
    if fields:
        mapped, unused, unresolved = map_contract(fields, {
            "case_id": result["case_id"],
            "status": result["status"],
            "appraisal": studies,
            "appraisal_table": "appraisal.csv",
            "overall": result["overall"],
            "overall_summary": core["summary"],
            "domain_counts": counts["by_domain"],
            "issues": issues,
            "report": "report.md",
            "evidence": result["evidence"],
            "uncertainty": uncertainty,
            "limits": limits,
            "changes": [],
        })
        result.update(mapped)
        result["contract_mapping"] = {
            "source": os.path.basename(case_path) if case_path else "",
            "requested_fields": fields,
            "unresolved_fields": unresolved,
            "unused_core_fields": unused,
            "note": "unresolved fields have no evidence-backed value in this run; do not invent them",
        }

    with open(os.path.join(args.out, "result.json"), "w", encoding="utf-8") as handle:
        json.dump(result, handle, ensure_ascii=False, indent=1)

    print("studies=%d rows=%d overall=%s errors=%d warnings=%d status=%s -> %s"
          % (len(studies), len(rows),
             ", ".join("%s:%s" % (s["study_id"], s["overall"]) for s in studies),
             severity_count["error"], severity_count["warning"], status, args.out))
    for limit in limits:
        print("warning: %s" % limit, file=sys.stderr)
    return 0 if status == "ok" else (2 if status == "partial" else 1)


if __name__ == "__main__":
    sys.exit(main())
