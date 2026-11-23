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

def read_material(path):
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        if not shutil.which("pdftotext"):
            raise ValueError("pdftotext unavailable; render/OCR this file with available tools")
        proc = subprocess.run(["pdftotext", "-layout", str(path), "-"],
                              capture_output=True, timeout=60)
        if proc.returncode:
            raise ValueError("PDF extraction failed")
        return proc.stdout.decode("utf-8", "replace").split("\f")
    if suffix == ".docx":
        with zipfile.ZipFile(path) as archive:
            root = ET.fromstring(archive.read("word/document.xml"))
        ns = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
        paras = ["".join(p.itertext()) for p in root.findall(".//w:p", ns)]
        return ["\n\n".join(paras)]
    return [path.read_text(encoding="utf-8")]

BIB_HEADING = re.compile(r"^\s*(references?|reference list|bibliography|literature cited|参考文献)\s*$", re.I)
BIB_ENTRY = re.compile(r"^\s*\[(\d+)\]\s*\S")
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

def citation_candidates(records):
    """Conservative, text-grounded citation checks; never asserts what the source says."""
    bib, citing = {}, []
    for record in records:
        if BIB_ENTRY.match(record["quote"]):
            number = int(BIB_ENTRY.match(record["quote"]).group(1))
            bib.setdefault(number, record)
    for record in records:
        if BIB_ENTRY.match(record["quote"]):
            continue
        for group in CITE_GROUP.findall(record["quote"]):
            for number in expand_citations(group):
                citing.append((number, record))
    findings = []
    if not citing:
        return findings
    missing = sorted({number for number, _ in citing if number not in bib})
    if not bib:
        record = citing[0][1]
        findings.append({
            "id": "AUTO-CIT-1", "facet": "citation_support", "judgment": "evidence_gap",
            "severity": "major",
            "basis": ("自动定位候选（需语义确认）：正文出现数字引用标记，但可用材料中没有可解析的参考文献条目，"
                      "无法核对引用是否支持结论。"),
            "action": "补充完整的参考文献列表及其出处，或删除无法核验的引用标记；保留原始来源链接与访问日期。",
            "evidence": [{"source_id": record["source_id"], "locator": record["locator"],
                          "quote": record["quote"], "sha256": record["sha256"]}]})
        return findings
    for number in missing:
        record = next(record for n, record in citing if n == number)
        findings.append({
            "id": f"AUTO-CIT-{number}", "facet": "citation_support", "judgment": "evidence_gap",
            "severity": "minor",
            "basis": (f"自动定位候选（需语义确认）：正文引用 [{number}]，但参考文献条目中未找到对应编号，"
                      "该引用暂时不可核验。"),
            "action": f"补全或更正参考文献 [{number}] 的条目，并核对正文引用编号与书目一致。",
            "evidence": [{"source_id": record["source_id"], "locator": record["locator"],
                          "quote": record["quote"], "sha256": record["sha256"]}]})
    return findings[:20]

P_VALUE = re.compile(r"\bp\s*(?:值)?\s*[<≤=]\s*(0?\.\d+)", re.I)
SAMPLE_SIZE = re.compile(r"(?:\bn\s*=\s*|\bN\s*=\s*|样本量\s*[:：=]?\s*)(\d+)")
PERCENT = re.compile(r"(\d+(?:\.\d+)?)\s*%")
SIGNIFICANCE = re.compile(r"显著|显著性|\bsignificant", re.I)
RETRACTION = re.compile(r"\bretract(?:ed|ion)?\b|撤稿", re.I)
CORRECTION = re.compile(r"\berratum\b|\bcorrigendum\b|更正声明|勘误", re.I)
PREPRINT = re.compile(r"\bpreprint\b|\bmedrxiv\b|\bbiorxiv\b|\barxiv\b", re.I)


def evidence_of(record):
    return {"source_id": record["source_id"], "locator": record["locator"],
            "quote": record["quote"], "sha256": record["sha256"]}


def numeric_candidates(records):
    """Deterministic numeric-consistency candidates; all require semantic confirmation."""
    findings = []
    # 1. A paragraph that calls a result significant while reporting p >= 0.05.
    for record in records:
        for match in P_VALUE.finditer(record["quote"]):
            try:
                value = float(match.group(1))
            except ValueError:
                continue
            if value >= 0.05 and SIGNIFICANCE.search(record["quote"]):
                findings.append({
                    "id": f"NUM-P-{len(findings) + 1}", "facet": "statistics",
                    "judgment": "evidence_gap", "severity": "major",
                    "basis": (f"自动定位候选（需语义确认）：该段自称显著，但同段给出的 p 值为 {match.group(1)}，"
                              "未达到常用的 0.05 显著性阈值。"),
                    "action": "核对原始统计输出；若确为 p≥0.05，改写为“未达显著”或补充其他检验依据。",
                    "evidence": [evidence_of(record)]})
    # 2. Conflicting sample sizes inside one source.
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
                "basis": ("自动定位候选（需语义确认）：同一来源出现多个不同的样本量 "
                          + "、".join(f"n={k}" for k in sorted(values)[:3]) + "，需确认是否指不同分析集。"),
                "action": "在正文、图注和表格中统一样本量口径，或明确写出各分析集与缺失处理。",
                "evidence": [evidence_of(r) for r in chosen]})
    # 3. Percentages that exceed 100 in a single paragraph (multi-select artefacts excepted).
    for record in records:
        values = [float(v) for v in PERCENT.findall(record["quote"])]
        if len(values) >= 2 and sum(values) > 100.5:
            findings.append({
                "id": f"NUM-PCT-{len(findings) + 1}", "facet": "statistics",
                "judgment": "evidence_gap", "severity": "minor",
                "basis": (f"自动定位候选（需语义确认）：同段百分比合计约 {sum(values):.1f}%，"
                          "若为互斥分组则超过 100%。"),
                "action": "确认百分比基数与是否多选；统一分母并在图注或表注说明。",
                "evidence": [evidence_of(record)]})
    return findings[:10]


def source_meta_candidates(records):
    """Flag retraction / correction / preprint markers for manual confirmation."""
    findings = []
    checks = (("RETRACT", RETRACTION, "major", "出现撤稿相关字样"),
              ("CORR", CORRECTION, "minor", "出现勘误/更正相关字样"),
              ("PREPRINT", PREPRINT, "informational", "出现预印本标识"))
    for tag, pattern, severity, label in checks:
        for record in records:
            if not pattern.search(record["quote"]):
                continue
            findings.append({
                "id": f"SOURCE-META-{tag}-{len(findings) + 1}", "facet": "facts",
                "judgment": "evidence_gap", "severity": severity,
                "basis": f"自动定位候选（需语义确认）：{label}，需核对出版状态、版本日期与影响范围。",
                "action": "核对出版商/期刊的正式记录与发表版本；如已撤稿或更正，说明对结论的影响并替换引用。",
                "evidence": [evidence_of(record)]})
            break
    return findings[:5]


def prepare(source, out):
    case = json.loads((source / "case.json").read_text()) if (source / "case.json").exists() else {}
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
    write(out / "review-template.json", {
        "case_id": evidence["case_id"], "summary": "",
        "findings": (citation_candidates(records) + numeric_candidates(records)
                     + source_meta_candidates(records))[:20],
        "checks": [{"facet": facet, "status": "not_checked", "evidence": [],
                    "reason": "Agent must read actual material" + (
                        "; automatic candidates were pre-filled" if facet in {"citation_support", "statistics", "facts"} else "")
                    } for facet in FACETS]})
    report = {"case_id": evidence["case_id"], "status": "partial" if records else "failed",
              "stage": "evidence_prepared", "sources": files,
              "uncertainty": failures or ["Scientific review is pending"],
              "change_log": ["Read source files and assigned physical-page paragraph locators"]}
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

def render(evidence_path, review_path, out):
    evidence = json.loads(evidence_path.read_text())
    review = json.loads(review_path.read_text())
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
    result = json.loads(Path(result_path).read_text())
    case = json.loads(Path(case_path).read_text()) if Path(case_path).exists() else {}
    errors = []
    if not isinstance(result, dict):
        raise ValueError("result.json must be an object")
    expected = case.get("case_id", case.get("id")) if isinstance(case, dict) else None
    if expected is not None and result.get("case_id") != expected:
        errors.append(f"case_id mismatch: {result.get('case_id')!r} != {expected!r}")
    if result.get("status") not in {"success", "partial", "failed"}:
        errors.append("status must be success/partial/failed")
    contract = case.get("output_contract") if isinstance(case, dict) else None
    required = []
    if isinstance(contract, dict):
        fields = contract.get("fields", contract.get("required", contract))
        if isinstance(fields, dict):
            required = [k for k in fields if k]
        elif isinstance(fields, list):
            required = [f if isinstance(f, str) else (f.get("id") or f.get("name"))
                        for f in fields if isinstance(f, (str, dict))]
    for name in required:
        if name and name not in result:
            errors.append("missing contract field: " + str(name))
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
    covered = {c.get("facet") for c in checks if isinstance(c, dict)}
    missing_facets = sorted(set(FACETS) - covered)
    if missing_facets:
        errors.append("missing facet coverage: " + ", ".join(missing_facets))
    report = {"passed": not errors, "errors": errors, "missing_facets": missing_facets,
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
            args.evidence, args.review, args.out)
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
    return 0

if __name__ == "__main__":
    sys.exit(main())
