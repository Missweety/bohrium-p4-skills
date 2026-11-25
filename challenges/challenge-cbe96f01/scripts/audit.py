#!/usr/bin/env python3
"""Collect source evidence and render explicitly reviewed findings. Python 3.10+."""
import argparse
import hashlib
import json
import os
import tempfile
from pathlib import Path
import re
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET
import zipfile

FACETS = ("facts", "citation_support", "methods", "statistics", "logic", "academic_norms")
JUDGMENTS = {"confirmed_error", "evidence_gap", "recommendation", "supported",
             "partial_support", "unsupported", "unable_to_determine"}

def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as stream:
        stream.write(json.dumps(value, ensure_ascii=False, indent=2) + "\n")
        temporary = stream.name
    os.replace(temporary, path)

def decode_bytes(raw):
    """Decode real-world text material without inventing characters."""
    for encoding in ("utf-8-sig", "utf-8", "gb18030"):
        try:
            return raw.decode(encoding), encoding
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", "replace"), "utf-8/replace"


def read_text_any(path):
    return decode_bytes(path.read_bytes())[0]


def read_material(path):
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        if not shutil.which("pdftotext"):
            raise ValueError("pdftotext unavailable; render/OCR this file with available tools")
        proc = subprocess.run(["pdftotext", "-layout", str(path), "-"],
                              capture_output=True, timeout=60)
        if proc.returncode:
            raise ValueError("PDF extraction failed")
        return decode_bytes(proc.stdout)[0].split("\f")
    if suffix == ".docx":
        with zipfile.ZipFile(path) as archive:
            root = ET.fromstring(archive.read("word/document.xml"))
        ns = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
        paras = ["".join(p.itertext()) for p in root.findall(".//w:p", ns)]
        return ["\n\n".join(paras)]
    return [read_text_any(path)]

SECTION_HEADING = re.compile(
    r"^\s*(?:#{1,6}\s*)?(?:\d+(?:\.\d+)*\.?\s*)?(references?|reference list|bibliography|"
    r"literature cited|参考文献|参考资料)\s*[::]?\s*$", re.I)
BIB_LINE = re.compile(r"^\s*\[(\d{1,3})\]\s+(\S.*)$")
BIB_NUM_LINE = re.compile(r"^\s*(\d{1,3})[.)]\s+([A-Z\u4e00-\u9fff].{9,})$")
BIB_AUTHOR_YEAR = re.compile(r"^\s*[A-Z][A-Za-z\-']+,\s+[A-Z]")
CITE_GROUP = re.compile(r"\[(\d+(?:\s*[,;–—-]\s*\d+)*)\]")


def expand_citations(token):
    numbers = set()
    for part in re.split(r"[,;]", token):
        part = part.strip()
        if not part:
            continue
        bounds = re.split(r"[–—-]", part)
        try:
            if len(bounds) == 2:
                start, end = int(bounds[0]), int(bounds[1])
                if 0 < end - start <= 50:
                    numbers.update(range(start, end + 1))
            else:
                numbers.add(int(part))
        except ValueError:
            continue
    return numbers


def parse_bibliography(records):
    """Locate the reference section and parse the numbering style actually used.

    Full-text PDFs often keep the whole reference list inside one paragraph and
    use either ``[1]``, ``1.`` or author-year entries. Only a machine-parseable
    numeric numbering may be used to claim that a cited entry is missing.
    """
    bib, ref_records = {}, set()
    ref_section, numbering, author_year = False, False, 0
    for index, record in enumerate(records):
        quote = record["quote"]
        lines = [line for line in quote.splitlines() if line.strip()]
        first = lines[0].strip() if lines else ""
        if SECTION_HEADING.match(first):
            ref_section = True
        if not ref_section and lines:
            numbered = [line for line in lines if BIB_LINE.match(line) or BIB_NUM_LINE.match(line)]
            if len(numbered) >= 2 and len(numbered) >= 0.5 * len(lines):
                ref_section = True
        if not ref_section:
            continue
        ref_records.add(index)
        for line in lines:
            match = BIB_LINE.match(line)
            if match:
                bib.setdefault(int(match.group(1)), record)
                numbering = True
                continue
            match = BIB_NUM_LINE.match(line)
            if match:
                bib.setdefault(int(match.group(1)), record)
                numbering = True
                continue
            if BIB_AUTHOR_YEAR.match(line):
                author_year += 1
    return {"bib": bib, "ref_records": ref_records, "ref_section": ref_section,
            "numbering": numbering, "author_year": author_year}


def candidate(fid, facet, severity, basis, action, record):
    return {"id": fid, "facet": facet, "judgment": "evidence_gap", "severity": severity,
            "basis": "自动定位候选（需语义确认）：" + basis, "action": action,
            "evidence": [evidence_of(record)]}


def citation_candidates(records):
    """Leads only: never assert a missing entry unless the numbering is parseable."""
    info = parse_bibliography(records)
    citing = []
    for index, record in enumerate(records):
        if index in info["ref_records"]:
            continue
        for group in CITE_GROUP.findall(record["quote"]):
            for number in expand_citations(group):
                citing.append((number, record))
    if not citing:
        return []
    if not info["ref_section"]:
        return [candidate(
            "CIT-NO-SECTION", "citation_support", "informational",
            "正文出现数字引用标记，但本次材料中未找到参考文献区，可能是摘录或补充材料；"
            "不得据此判定参考文献缺失。",
            "若材料含参考文献区，补充后重新建立索引；若为节选，写明未提供书目并把它记为待核项。",
            citing[0][1])]
    if not info["numbering"]:
        style = "作者-年份" if info["author_year"] else "非方括号编号"
        return [candidate(
            "CIT-STYLE-1", "citation_support", "informational",
            f"已找到参考文献区，但采用{style}著录，无法用编号做机械匹配；本候选只提示人工核对，"
            "不代表条目缺失。",
            "按著录风格逐条人工核对正文引用与书目，确认后再写入 findings。",
            citing[0][1])]
    candidates = []
    missing = sorted({number for number, _ in citing if number not in info["bib"]})
    for number in missing[:5]:
        record = next(record for n, record in citing if n == number)
        candidates.append(candidate(
            f"AUTO-CIT-{number}", "citation_support", "minor",
            f"正文引用 [{number}]，但可解析的书目编号中未找到对应条目，该引用暂不可核验。",
            f"补全或更正参考文献 [{number}] 的条目，并核对正文引用编号与书目一致。", record))
    if len(missing) > 5:
        candidates.append(candidate(
            "AUTO-CIT-MORE", "citation_support", "informational",
            f"另有 {len(missing) - 5} 个正文编号未匹配到书目，已截断显示；请人工核对编号体系。",
            "核对书目编号与正文引用是否使用同一编号体系。", citing[0][1]))
    return candidates


P_VALUE = re.compile(r"\bp\s*(?:值)?\s*(<=|>=|<|≤|=|>|≥)\s*(0?\.\d+)", re.I)
SAMPLE_SIZE = re.compile(r"(?:\bn\s*=\s*|\bN\s*=\s*|样本量\s*[:：=]?\s*)(\d+)")
PERCENT = re.compile(r"(\d+(?:\.\d+)?)\s*%")
SENTENCE_SPLIT = re.compile(r"(?<=[.!?。！？])\s+|(?<=[；;])")
SIGNIFICANCE = re.compile(r"显著|显著性|\bsignificant", re.I)
RETRACTION = re.compile(r"\bretract(?:ed|ion)?\b|撤稿", re.I)
CORRECTION = re.compile(r"\berratum\b|\bcorrigendum\b|更正声明|勘误", re.I)
PREPRINT = re.compile(r"\bpreprint\b|\bmedrxiv\b|\bbiorxiv\b|\barxiv\b", re.I)


def evidence_of(record):
    return {"source_id": record["source_id"], "locator": record["locator"],
            "quote": record["quote"], "sha256": record["sha256"]}


def numeric_candidates(records):
    """Deterministic numeric-consistency leads; all require semantic confirmation."""
    findings = []
    # 1. A sentence that calls a result significant while reporting p > 0.05.
    for record in records:
        for match in P_VALUE.finditer(record["quote"]):
            operator = match.group(1)
            try:
                value = float(match.group(2))
            except ValueError:
                continue
            if operator in ("=", ">", "≥", ">=") and value > 0.05 + 1e-9 \
                    and SIGNIFICANCE.search(record["quote"]):
                findings.append(candidate(
                    f"NUM-P-{len(findings) + 1}", "statistics", "minor",
                    f"该段自称显著，但同段给出的 p 值为 {operator}{match.group(2)}，"
                    "未达到常用的 0.05 显著性阈值。",
                    "核对原始统计输出；若确为 p>0.05，改写为“未达显著”或补充其他检验依据。",
                    record))
    # 2. Different sample sizes inside one source.
    by_source = {}
    for record in records:
        for match in SAMPLE_SIZE.finditer(record["quote"]):
            by_source.setdefault(record["source_id"], {}).setdefault(int(match.group(1)), record)
    for source_id, values in by_source.items():
        if len(values) > 1:
            chosen = [values[k] for k in sorted(values)[:3]]
            findings.append({
                "id": f"NUM-N-{len(findings) + 1}", "facet": "statistics",
                "judgment": "evidence_gap", "severity": "minor",
                "basis": "自动定位候选（需语义确认）：同一来源出现多个不同的样本量 "
                          + "、".join(f"n={k}" for k in sorted(values)[:3])
                          + "，需确认是否指不同分析集。",
                "action": "在正文、图注和表格中统一样本量口径，或明确写出各分析集与缺失处理。",
                "evidence": [evidence_of(r) for r in chosen]})
    # 3. Three or more percentages in one sentence summing over 100.
    for record in records:
        for sentence in SENTENCE_SPLIT.split(record["quote"]):
            values = [float(v) for v in PERCENT.findall(sentence)]
            if len(values) >= 3 and sum(values) > 100.5:
                findings.append(candidate(
                    f"NUM-PCT-{len(findings) + 1}", "statistics", "informational",
                    f"同一句百分比合计约 {sum(values):.1f}%；若为互斥分组则超过 100%，"
                    "也可能包含多选或独立指标。",
                    "确认百分比基数与是否多选；统一分母并在图注或表注说明。", record))
                break
    return findings[:10]


def source_meta_candidates(records):
    """Retraction / correction / preprint leads, excluding the reference list itself."""
    info = parse_bibliography(records)
    findings = []
    checks = (("RETRACT", RETRACTION, "minor", "出现撤稿相关字样"),
              ("CORR", CORRECTION, "informational", "出现勘误/更正相关字样"),
              ("PREPRINT", PREPRINT, "informational", "出现预印本标识"))
    for tag, pattern, severity, label in checks:
        for index, record in enumerate(records):
            if index in info["ref_records"] or not pattern.search(record["quote"]):
                continue
            findings.append(candidate(
                f"SOURCE-META-{tag}-{len(findings) + 1}", "facts", severity,
                f"{label}，需核对出版状态、版本日期与影响范围。",
                "核对出版商/期刊的正式记录与发表版本；如已撤稿或更正，说明对结论的影响并替换引用。",
                record))
            break
    return findings[:5]


def contract_names(case):
    """Field names declared by a runtime output_contract, whatever its nesting."""
    names = []

    def add(value):
        if isinstance(value, str):
            names.append(value)
        elif isinstance(value, dict):
            name = value.get("name") or value.get("field") or value.get("id")
            if isinstance(name, str) and name:
                names.append(name)
            else:  # mapping of field name -> type/spec
                names.extend(str(key) for key in value)
        elif isinstance(value, list):
            for item in value:
                add(item)

    contract = case.get("output_contract") if isinstance(case, dict) else None
    if isinstance(contract, dict):
        containers = {"fields", "required", "optional", "properties", "version"}
        if containers & set(contract):
            add(contract.get("fields"))
            add(contract.get("required"))
            add(contract.get("optional"))
            add(contract.get("properties"))
            for key in contract:
                if key not in containers:
                    names.append(key)
        else:
            for key in contract:
                names.append(key)
    else:
        add(contract)
    seen, out = set(), []
    for name in names:
        if name and name not in seen:
            seen.add(name)
            out.append(name)
    return out


def prepare(source, out):
    case_path = source / "case.json"
    case = json.loads(read_text_any(case_path)) if case_path.exists() else {}
    if not isinstance(case, dict):
        raise ValueError("case.json must be an object")
    records, files, failures = [], [], []
    material_extensions = {".pdf", ".docx", ".txt", ".md", ".tex", ".csv", ".bib", ".ris"}
    out_resolved = out.resolve()
    for path in sorted(source.rglob("*")):
        if (not path.is_file() or path.is_symlink() or path.suffix.lower() not in material_extensions
                or path.name.lower() in {"task.md", "readme.md"}
                or out_resolved == path.resolve() or out_resolved in path.resolve().parents):
            continue
        relative = str(path.relative_to(source))
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        file = {"source_id": relative, "path": str(path.resolve()), "sha256": digest}
        try:
            pages = read_material(path)
            count = 0
            for page_number, text in enumerate(pages, 1):
                if not text.strip():
                    if page_number < len(pages):
                        failures.append({"source_id": relative, "page": page_number, "reason": "empty_text_page"})
                    continue
                for i, paragraph in enumerate(re.split(r"\n\s*\n", text.strip()), 1):
                    records.append({"source_id": relative,
                                    "locator": f"p.{page_number}/para.{i}",
                                    "quote": paragraph.strip(), "sha256": digest})
                    count += 1
            if not count:
                raise ValueError("no readable source text")
            file["paragraphs"] = count
            files.append(file)
        except Exception as exc:
            failures.append({"source_id": relative, "reason": f"{type(exc).__name__}: {exc}"})
    evidence = {"case_id": case.get("case_id", case.get("id")), "sources": files,
                "paragraphs": records, "unreadable": failures}
    write(out / "evidence.json", evidence)
    lines = [f"## {p['source_id']} — {p['locator']}\n\n{p['quote']}\n" for p in records]
    (out / "source-index.md").write_text("\n".join(lines), encoding="utf-8")
    candidates = (citation_candidates(records) + numeric_candidates(records)
                  + source_meta_candidates(records))
    write(out / "review-template.json", {
        "case_id": evidence["case_id"], "summary": "", "findings": [],
        "candidates": candidates,
        "checks": [{"facet": facet, "status": "not_checked", "evidence": [],
                    "reason": "Agent must read actual material"
                              + ("; %d automatic lead(s) await semantic confirmation"
                                 % len(candidates) if candidates else "")
                    } for facet in FACETS]})
    report = {"case_id": evidence["case_id"], "status": "partial" if records else "failed",
              "stage": "evidence_prepared", "sources": files,
              "candidates": len(candidates),
              "uncertainty": failures or ["Scientific review is pending"],
              "change_log": ["Read source files and assigned physical-page paragraph locators",
                             "Wrote %d machine leads; none is a finding until semantically confirmed"
                             % len(candidates)]}
    if not case_path.exists():
        report["uncertainty"].append("case.json missing under input dir; case_id is unknown")
    write(out / "preparation.json", report)
    return report

def check_evidence(items, index):
    if not isinstance(items, list) or not items:
        return ["no evidence"]
    errors = []
    for item in items:
        if not isinstance(item, dict):
            errors.append("evidence item must be an object")
            continue
        quote = item.get("quote")
        source = index.get((item.get("source_id"), item.get("locator")))
        if source is None:
            errors.append("source/locator not found")
        elif not isinstance(quote, str) or not quote.strip() or quote not in source["quote"]:
            errors.append("quote is absent from the cited source paragraph")
        elif item.get("sha256") != source["sha256"]:
            errors.append("source version hash mismatch")
    return errors

def render(evidence_path, review_path, out, case_path=None):
    evidence = json.loads(evidence_path.read_text())
    review = json.loads(review_path.read_text())
    case = {}
    if case_path and Path(case_path).exists():
        case = json.loads(read_text_any(Path(case_path)))
        if not isinstance(case, dict):
            case = {}
    if not isinstance(review, dict):
        raise ValueError("review must be an object")
    index = {(p["source_id"], p["locator"]): p for p in evidence["paragraphs"]}
    errors = []
    if review.get("case_id") != evidence["case_id"]:
        errors.append("case_id mismatch")
    # Check the bound snapshot against the actual files before accepting its quotes.
    for source in evidence["sources"]:
        path = Path(source["path"])
        if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != source["sha256"]:
            errors.append("source changed or disappeared: " + source["source_id"])
    findings = review.get("findings", [])
    checks = review.get("checks", [])
    if not isinstance(findings, list) or not isinstance(checks, list):
        raise ValueError("findings and checks must be lists")
    accepted, rejected, seen = [], [], set()
    for finding in findings:
        problems = []
        if not isinstance(finding, dict):
            rejected.append({"finding": finding, "errors": ["finding must be an object"]})
            continue
        fid = finding.get("id")
        if not isinstance(fid, str) or not fid or fid in seen:
            problems.append("missing or duplicate finding id")
        else:
            seen.add(fid)
        for key in ("facet", "judgment", "severity", "basis", "action", "evidence"):
            if not finding.get(key):
                problems.append("missing " + key)
        if finding.get("facet") not in FACETS:
            problems.append("unknown facet")
        if finding.get("judgment") not in JUDGMENTS:
            problems.append("unknown judgment")
        if finding.get("severity") not in {"major", "minor", "informational"}:
            problems.append("unknown severity")
        basis = str(finding.get("basis") or "")
        if "需语义确认" in basis or str(fid or "").startswith(
                ("AUTO-CIT-", "CIT-", "NUM-", "SOURCE-META-")):
            problems.append("automatic lead not semantically confirmed; rewrite id and basis "
                            "with your own judgement before rendering it as a finding")
        problems.extend(check_evidence(finding.get("evidence"), index))
        if finding.get("judgment") in {"unsupported", "partial_support"} or (
                finding.get("facet") == "citation_support" and finding.get("judgment") == "supported"):
            if len({e.get("source_id") for e in finding.get("evidence", []) if isinstance(e, dict)}) < 2:
                problems.append("citation support requires manuscript and cited-source evidence")
        if problems:
            rejected.append({"finding": finding, "errors": problems})
        else:
            accepted.append(finding)
    checked, by_facet = set(), {}
    for check in checks:
        if not isinstance(check, dict) or check.get("facet") not in FACETS:
            errors.append("malformed or unknown facet check")
            continue
        facet = check["facet"]
        if facet in by_facet:
            errors.append("duplicate facet check: " + facet)
        by_facet[facet] = check
        state = check.get("status")
        if state not in {"checked", "not_checked", "not_applicable", "unable_to_determine"}:
            errors.append("invalid check status: " + facet)
        elif state == "checked":
            bad = check_evidence(check.get("evidence"), index)
            if bad:
                errors.extend(facet + ": " + e for e in bad)
            else:
                checked.add(facet)
        elif not check.get("reason"):
            errors.append("unresolved facet needs reason: " + facet)
    missing = sorted(set(FACETS) - by_facet.keys())
    unfinished = [f for f,c in by_facet.items() if c.get("status") in {"not_checked","unable_to_determine"}]
    uncertainty = evidence["unreadable"] + errors + [
        "unreviewed facet: " + f for f in missing + unfinished]
    if rejected:
        uncertainty.append({"rejected_findings": rejected})
    status = "partial" if uncertainty else "success"
    if not evidence["paragraphs"]:
        status = "failed"
    result = {"case_id": evidence["case_id"], "status": status,
              "summary": review.get("summary", ""), "findings": accepted, "checks": checks,
              "sources": evidence["sources"], "uncertainty": uncertainty,
              "change_log": ["Validated source identity, exact quotes and coverage; rendered reviewed findings"],
              "boundary": "Script validates evidence identity and structure; Agent is responsible for semantic judgments."}
    unmapped = [name for name in contract_names(case) if name not in result]
    for name in unmapped:
        result[name] = None
    if unmapped:
        uncertainty.append({
            "type": "unmapped_contract_fields",
            "detail": "Runtime contract fields without a native renderer mapping were kept as null "
                      "instead of being silently dropped.",
            "fields": unmapped})
    write(out / "result.json", result)
    write(out / "validation.json", {"passed": not (errors or rejected or missing),
                                    "errors": errors, "rejected": rejected, "missing_facets": missing,
                                    "accepted_findings": len(accepted)})
    lines = ["# 科研审查报告", "", result["summary"], "", f"运行状态 {status}", "",
             "|编号|检查面|结论|严重度|", "|---|---|---|---|"]
    for f in accepted:
        lines.append("|" + "|".join(str(f[k]).replace("|", "\\|").replace("\n"," ") for k in
                                  ("id","facet","judgment","severity")) + "|")
    for f in accepted:
        lines.extend(["", f"## {f['id']}", "", str(f["basis"]), "", "修改建议", "", str(f["action"])])
        for e in f["evidence"]:
            lines.extend(["", f"{e['source_id']} — {e['locator']}", "", "> " + e["quote"].replace("\n", "\n> ")])
    lines.extend(["", "## 覆盖与待核", "", json.dumps(checks, ensure_ascii=False, indent=2),
                  "", json.dumps(uncertainty, ensure_ascii=False, indent=2)])
    (out / "review-report.md").write_text("\n".join(lines)+"\n", encoding="utf-8")
    return {"status": status, "accepted": len(accepted), "rejected": len(rejected),
            "validation_passed": not (errors or rejected or missing)}

def selfcheck(result_path, case_path, evidence_path, out):
    """Check a finished result.json against the runtime contract and the evidence index."""
    result = json.loads(read_text_any(Path(result_path)))
    case = json.loads(read_text_any(Path(case_path))) if Path(case_path).exists() else {}
    if not isinstance(case, dict):
        case = {}
    errors = []
    warnings = []
    if not isinstance(result, dict):
        raise ValueError("result.json must be an object")
    expected = case.get("case_id", case.get("id"))
    if expected is not None and result.get("case_id") != expected:
        errors.append(f"case_id mismatch: {result.get('case_id')!r} != {expected!r}")
    if result.get("status") not in {"success", "partial", "failed"}:
        errors.append("status must be success/partial/failed")
    for name in contract_names(case):
        if name not in result:
            errors.append("missing contract field: " + str(name))
        elif result.get(name) is None:
            warnings.append("contract field present but unset (Agent must fill it): " + str(name))
    index = {}
    if evidence_path and Path(evidence_path).exists():
        evidence = json.loads(Path(evidence_path).read_text())
        index = {(p["source_id"], p["locator"]): p for p in evidence.get("paragraphs", [])}
    findings = result.get("findings") or []
    checks = result.get("checks") or []
    if not isinstance(findings, list) or not isinstance(checks, list):
        errors.append("findings and checks must be lists")
        findings, checks = [], []
    for finding in findings:
        problems = check_evidence(finding.get("evidence"), index) if index else []
        if problems and not index:
            problems = []
        if problems:
            errors.append(f"finding {finding.get('id')}: " + "; ".join(problems))
        basis = str(finding.get("basis") or "")
        fid = str(finding.get("id") or "")
        if "需语义确认" in basis or fid.startswith(
                ("AUTO-CIT-", "CIT-", "NUM-", "SOURCE-META-")):
            errors.append(f"finding {fid}: automatic lead was not semantically confirmed")
    covered = {c.get("facet") for c in checks if isinstance(c, dict)}
    missing_facets = sorted(set(FACETS) - covered)
    if missing_facets:
        errors.append("missing facet coverage: " + ", ".join(missing_facets))
    checked = {c.get("facet") for c in checks
               if isinstance(c, dict) and c.get("status") == "checked"}
    if not checked:
        errors.append("no facet was actually checked; at least one facet needs a verified status")
    elif result.get("status") == "success":
        unfinished = sorted({c.get("facet") for c in checks if isinstance(c, dict)
                             and c.get("status") in {"not_checked", "unable_to_determine"}})
        if unfinished:
            errors.append("success requires every facet checked: " + ", ".join(unfinished))
    report = {"passed": not errors, "errors": errors, "warnings": warnings,
              "missing_facets": missing_facets,
              "findings": len(findings), "checks": len(checks)}
    write(Path(out) / "selfcheck.json", report)
    return report


def main():
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="mode", required=True)
    p = sub.add_parser("prepare")
    p.add_argument("--input", type=Path, default=Path("/input"))
    p.add_argument("--out", type=Path, default=Path("/app/work/audit"))
    p = sub.add_parser("render")
    p.add_argument("--evidence", type=Path, required=True)
    p.add_argument("--review", type=Path, required=True)
    p.add_argument("--case", type=Path, default=Path("/input/case.json"))
    p.add_argument("--out", type=Path, default=Path("/app/output"))
    p = sub.add_parser("selfcheck")
    p.add_argument("--result", type=Path, required=True)
    p.add_argument("--case", type=Path, default=Path("/input/case.json"))
    p.add_argument("--evidence", type=Path, default=Path("/app/work/audit/evidence.json"))
    p.add_argument("--out", type=Path, default=Path("/app/work"))
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    if args.mode == "selfcheck":
        report = selfcheck(args.result, args.case, args.evidence, args.out)
        print(json.dumps(report, ensure_ascii=False))
        return 0 if report["passed"] else 1
    case_id = None
    if args.mode == "render":
        try:
            case_id = json.loads(args.evidence.read_text()).get("case_id")
        except Exception:
            pass
        write(args.out / "result.json", {"case_id": case_id, "status": "partial",
                                        "uncertainty": ["Review rendering in progress"],
                                        "sources": [], "change_log": ["Rendering started"]})
        write(args.out / "validation.json", {"passed": False, "errors": ["Rendering in progress"]})
        (args.out / "review-report.md").write_text("# 审查处理中\n\n本次运行尚未完成。\n", encoding="utf-8")
    try:
        result = prepare(args.input, args.out) if args.mode == "prepare" else render(
            args.evidence, args.review, args.out, args.case)
    except Exception as exc:
        result = {"status": "failed", "error": f"{type(exc).__name__}: {exc}",
                  "sources": [], "uncertainty": [str(exc)], "change_log": ["failed attempt recorded"]}
        result["case_id"] = case_id
        write(args.out / "failure.json", result)
        if args.mode == "prepare":
            write(args.out / "preparation.json", result)
            write(args.out / "evidence.json", {"case_id": case_id, "sources": [], "paragraphs": [],
                                               "unreadable": [result["error"]]})
            (args.out / "source-index.md").write_text("# 输入准备失败\n", encoding="utf-8")
        if args.mode == "render":
            write(args.out / "result.json", result)
            write(args.out / "validation.json", {"passed": False, "errors": [result["error"]]})
            (args.out / "review-report.md").write_text(
                "# 审查失败\n\n" + result["error"] + "\n", encoding="utf-8")
    print(json.dumps(result if args.mode == "render" or result.get("error") else {
        k:result[k] for k in ("case_id","status","stage")},ensure_ascii=False))
    return 1 if result.get("status") == "failed" else 0

if __name__ == "__main__":
    sys.exit(main())
