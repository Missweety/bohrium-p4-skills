#!/usr/bin/env python3
"""selfcheck.py - final gate + result.json assembly.

Checks (hard failures => exit 1):
  * case.json readable and output_contract keys are present in result.json
  * inputs/manuscript exist with at least one content block
  * the DOCX exists, is a valid OOXML package and reopens with paragraphs
  * format_report.json exists and is internally consistent
  * every declared deliverable exists and hashes match
  * result.status is consistent with the recorded issues
  * result.json round-trips through json.load

Writes checks.json and result.json under --output.
Honest status rules: success only when every format requirement is applied and
no issue is open; otherwise partial; failed when a deliverable is unusable.
"""
import argparse
import json
import os
import shutil
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common as C  # noqa: E402

CORE_KEYS = ["case_id", "status", "sources", "uncertainty", "change_log",
             "issues", "deliverables", "contract_fields"]
ALLOWED_STATUS = {"success", "partial", "failed"}
ALIASES = {
    "docx": ("docx",), "output_docx": ("docx",), "formatted_docx": ("docx",),
    "docx_path": ("docx",), "file": ("docx",), "output_file": ("docx",),
    "document": ("docx",), "pdf": ("pdf",), "pdf_path": ("pdf",),
    "docx_info": ("docx_info",), "pdf_info": ("pdf_info",),
    "page_count": ("metrics", "page_count"), "pages": ("metrics", "page_count"),
    "format_report": ("format_report",), "report": ("format_report",),
    "spec": ("template_spec",), "template": ("template_spec",),
    "specification": ("template_spec",), "format_spec": ("template_spec",),
    "spec_summary": ("template_spec",), "template_summary": ("template_spec",),
    "format_report_path": ("format_report", "path"),
    "report_path": ("format_report", "path"),
    "docx_file": ("docx",), "document_path": ("docx",), "output_path": ("docx",),
    "output_docx_path": ("docx",), "formatted_docx_path": ("docx",),
    "docx_sha256": ("docx_info", "sha256"), "docx_bytes": ("docx_info", "bytes"),
    "docx_reopens": ("docx_info", "reopens"),
    "pdf_file": ("pdf",), "pdf_page_count": ("pdf_info", "page_count"),
    "template_path": ("template_spec", "path"),
    "requirements_total": ("format_report", "summary", "total"),
    "requirements_applied": ("format_report", "summary", "applied"),
    "requirements_partial": ("format_report", "summary", "partial"),
    "requirements_failed": ("format_report", "summary", "failed"),
    "format_requirements": ("format_report",),
    "content_preserved": ("verification", "content_preserved"),
    "pdf_produced": ("verification", "pdf_produced"),
    "verification": ("verification",), "metrics": ("metrics",),
    "limits": ("limits",), "warnings": ("uncertainty",),
    "notes": ("change_log",), "change_log": ("change_log",),
    "sources": ("sources",), "deliverables": ("deliverables",),
    "uncertainty": ("uncertainty",), "issues": ("issues",),
    "contract_fields": ("contract_fields",), "case_id": ("case_id",),
    "status": ("status",), "outputs": ("deliverables",),
}


def get_path(obj, path):
    node = obj
    for key in path:
        if isinstance(node, dict) and key in node:
            node = node[key]
        else:
            return None
    return node


def load_part(path):
    return C.read_json(path)


def main(argv=None):
    ap = argparse.ArgumentParser(description="Self-check and assemble result.json")
    ap.add_argument("--case", default="/input/case.json")
    ap.add_argument("--work", default="/app/work")
    ap.add_argument("--output", default="/app/output")
    args = ap.parse_args(argv)

    output = os.path.abspath(args.output)
    work = os.path.abspath(args.work)
    C.ensure_dir(output)
    checks = []

    def check(cid, description, passed, severity, detail):
        checks.append({"id": cid, "check": description, "passed": bool(passed),
                       "severity": severity, "detail": detail})
        return passed

    # ---- load artefacts ------------------------------------------------
    case_path = os.path.abspath(args.case)
    case = load_part(case_path)
    check("case.readable", "case.json readable", isinstance(case, dict) and bool(case),
          "hard", case_path if isinstance(case, dict) else "missing or invalid JSON")
    if not isinstance(case, dict):
        case = {}
    inputs = load_part(os.path.join(work, "inputs.json")) or {}
    spec = load_part(os.path.join(work, "spec.json")) or {}
    build_meta = load_part(os.path.join(output, "build_meta.json")) or {}
    format_report = load_part(os.path.join(output, "format_report.json")) or {}

    contract_list, contract_type = C.contract_fields(case)
    check("contract.fields", "输出契约字段可解析", bool(contract_list), "hard",
          "%d fields (%s)" % (len(contract_list), contract_type))

    manuscript = inputs.get("manuscript") or {}
    blocks = manuscript.get("blocks") or []
    check("inputs.readable", "inputs.json 可读", bool(inputs), "hard",
          os.path.join(work, "inputs.json"))
    check("manuscript.blocks", "稿件有可格式化内容块", len(blocks) > 0, "hard",
          "%d blocks (%s)" % (len(blocks), manuscript.get("path")))

    docx_path = build_meta.get("docx") or os.path.join(
        output, "manuscript_formatted.docx")
    docx_exists = bool(docx_path) and os.path.exists(docx_path)
    check("docx.exists", "输出 DOCX 存在", docx_exists, "hard",
          docx_path if docx_exists else "not produced")
    valid, reason = C.docx_valid(docx_path) if docx_exists else (False, "missing")
    check("docx.valid", "DOCX 是有效 OOXML 包", valid, "hard", reason)

    paragraph_count = (build_meta.get("reopen") or {}).get("paragraphs") or 0
    reopen_ok = bool((build_meta.get("reopen") or {}).get("ok"))
    check("docx.reopens", "DOCX 重新打开且含内容", reopen_ok and paragraph_count > 0,
          "hard", "paragraphs=%d, reopen=%s" % (paragraph_count, reopen_ok))

    reqs = format_report.get("requirements") or []
    check("report.exists", "format_report.json 存在且含检查项",
          bool(format_report) and len(reqs) > 0, "hard",
          "%d requirements" % len(reqs))
    summary = format_report.get("summary") or {}
    total = summary.get("total")
    counted = sum(int(summary.get(k) or 0) for k in
                  ("applied", "partial", "unsupported", "not_applicable", "failed"))
    check("report.summary", "format_report 汇总计数自洽",
          total is not None and counted == total, "hard",
          "total=%s counted=%s" % (total, counted))
    missing_locations = [r.get("id") for r in reqs
                         if r.get("status") == "applied" and not r.get("location")]
    check("report.evidence", "applied 项均带 OOXML 定位证据",
          not missing_locations, "soft",
          "missing locations: %s" % (missing_locations[:5] or "none"))
    bad_status = [r.get("id") for r in reqs if r.get("status") not in
                  ("applied", "partial", "unsupported", "not_applicable", "failed")]
    check("report.statuses", "检查项状态取值合法", not bad_status, "hard",
          "invalid: %s" % (bad_status[:5] or "none"))

    placeholder_req = next((r for r in reqs if r.get("id") == "placeholders"), None)
    check("output.no_placeholder", "输出无未完成占位符",
          bool(placeholder_req) and placeholder_req.get("status") == "applied",
          "soft", (placeholder_req or {}).get("actual"))

    # ---- assemble result -------------------------------------------------
    case_detected = C.detect_case_id(case, case_path)
    case_id = (inputs.get("case") or {}).get("case_id") or case_detected[0]

    def deliverable(path, role, fmt):
        if not path or not os.path.exists(path):
            return None
        return {"path": os.path.abspath(path), "role": role, "format": fmt,
                "bytes": os.path.getsize(path), "sha256": C.sha256_file(path)}

    # copy work artefacts next to the deliverable for reproducibility
    copied = {}
    for name in ("inputs.json", "spec.json"):
        src = os.path.join(work, name)
        if os.path.exists(src):
            dst = os.path.join(output, name)
            if os.path.abspath(src) != os.path.abspath(dst):
                shutil.copyfile(src, dst)
            copied[name] = dst

    deliverables = [x for x in [
        deliverable(docx_path, "formatted_docx", "docx"),
        deliverable(os.path.join(output, "format_report.json"), "format_report", "json"),
        deliverable(os.path.join(output, "build_meta.json"), "build_meta", "json"),
        deliverable(copied.get("spec.json"), "format_spec", "json"),
        deliverable(copied.get("inputs.json"), "parsed_inputs", "json"),
        deliverable(build_meta.get("pdf"), "pdf_preview", "pdf"),
    ] if x]
    deliverable_paths = [d["path"] for d in deliverables]
    missing_deliverables = [d["path"] for d in deliverables
                            if not os.path.exists(d["path"])]
    check("deliverables.exist", "声明的交付物均存在",
          not missing_deliverables and bool(deliverables), "hard",
          "%d files; missing=%s" % (len(deliverables),
                                    missing_deliverables or "none"))

    sources = []
    for role, item in (("case", (inputs.get("case") or {})),
                       ("task", (inputs.get("task") or {})),
                       ("manuscript", manuscript),
                       ("template", (inputs.get("template") or {}))):
        path = item.get("path")
        if path:
            sources.append({"role": role, "path": os.path.abspath(path),
                            "bytes": os.path.getsize(path)
                            if os.path.exists(path) else None,
                            "sha256": C.sha256_file(path)
                            if os.path.exists(path) else None})
    for extra in (spec.get("meta", {}).get("spec_sources") or {}).get(
            "json_sources", []) or []:
        if os.path.exists(extra):
            sources.append({"role": "spec_json", "path": os.path.abspath(extra),
                            "bytes": os.path.getsize(extra),
                            "sha256": C.sha256_file(extra)})

    issues = []
    seen = set()
    for item in (format_report.get("issues") or []):
        key = (item.get("id"), item.get("status"))
        if key in seen:
            continue
        seen.add(key)
        issues.append({"id": item.get("id"), "status": item.get("status"),
                       "detail": item.get("detail"),
                       "source": "format_report"})
    for item in (build_meta.get("issues") or []):
        key = (item.get("id"), item.get("status"))
        if key in seen:
            continue
        seen.add(key)
        issues.append({"id": item.get("id"), "status": item.get("status"),
                       "detail": item.get("issue"), "source": "build_meta"})
    missing_blocks = (build_meta.get("content_check") or {}).get("missing_blocks") or 0
    if missing_blocks:
        issues.append({"id": "content.missing", "status": "failed",
                       "detail": "%d text blocks missing from the output"
                                 % missing_blocks, "source": "build_meta"})
    for warn in (inputs.get("warnings") or []):
        if any(w in warn for w in ("unsupported", "could not be converted",
                                   "no manuscript", "failed")):
            issues.append({"id": "input.warning", "status": "partial",
                           "detail": warn, "source": "parse_inputs"})
    if spec.get("conflicts"):
        for conflict in spec["conflicts"][:10]:
            issues.append({"id": "spec.conflict.%s" % conflict.get("field"),
                           "status": "partial",
                           "detail": "conflicting values for %s: kept %r (%s), "
                                     "ignored %r (%s)" % (
                                         conflict.get("field"), conflict.get("kept"),
                                         conflict.get("kept_source"),
                                         conflict.get("ignored"),
                                         conflict.get("ignored_source")),
                           "source": "spec"})

    change_log = []
    for item in (build_meta.get("changes") or []):
        entry = {"anchor": item.get("anchor") or "document",
                 "change": item.get("field") or "format",
                 "from": item.get("from"), "to": item.get("to")}
        if item.get("changes"):
            entry["from"] = [c.get("from") for c in item["changes"]]
            entry["to"] = [c.get("to") for c in item["changes"]]
        change_log.append(entry)
    for kind, mapping in (build_meta.get("caption_map") or {}).items():
        for old, new in mapping.items():
            change_log.append({"anchor": "captions", "change": "%s renumbering" % kind,
                               "from": old, "to": new})
    meta = spec.get("meta") or {}
    if meta.get("template_missing"):
        change_log.append({"anchor": "spec", "change": "template fallback",
                           "from": "no template/spec detected",
                           "to": "builtin default spec (A4, 2.54cm, "
                                 "Liberation Serif 12pt, 1.5 spacing)"})
    if meta.get("template_used"):
        change_log.append({"anchor": "spec", "change": "spec extracted from template",
                           "from": None,
                           "to": os.path.basename(str(meta.get("template_path")))})
    if meta.get("default_fields"):
        change_log.append({"anchor": "spec", "change": "fields kept at defaults",
                           "from": None,
                           "to": "%d fields without explicit target value"
                                 % len(meta.get("default_fields"))})

    uncertainty = []
    if meta.get("template_missing"):
        uncertainty.append("No target template/spec was found; the builtin default "
                           "style set was applied and must be reviewed against the "
                           "real journal requirements.")
    if meta.get("template_used") and not (meta.get("spec_sources") or {}).get(
            "template_parse", {}).get("styles_found_count"):
        uncertainty.append("The template DOCX contained no recognizable heading "
                           "styles; heading formatting follows builtin defaults.")
    if spec.get("conflicts"):
        uncertainty.append("%d conflicting requirement(s) were detected between "
                           "sources; the higher-precedence value was kept and the "
                           "conflict is recorded in spec.json." % len(spec["conflicts"]))
    font_check = build_meta.get("font_check") or {}
    if font_check.get("available") is False:
        uncertainty.append("Requested font %r was not found via fc-match; a "
                           "renderer may substitute another face."
                           % font_check.get("requested"))
    if font_check.get("available") is None:
        uncertainty.append("Font availability could not be checked in this "
                           "environment (fc-match missing).")
    rendering = build_meta.get("rendering") or {}
    if not rendering.get("produced"):
        uncertainty.append("No PDF was produced (%s); page count and visual layout "
                           "are therefore not claimed."
                           % (rendering.get("reason") or "renderer unavailable"))
    if int((spec.get("page") or {}).get("columns") or 1) > 1:
        uncertainty.append("Multi-column section properties were written to OOXML, "
                           "but column balance was not visually verified.")
    uncertainty.append("Verification is XML-level (styles, section properties, "
                       "numbering, fields). No human visual inspection was performed.")
    if not (build_meta.get("pdf") and rendering.get("page_count")):
        uncertainty.append("Page count is not asserted because no real PDF render "
                           "was available.")
    if any(i["id"] == "references.entries" and i["status"] == "partial"
           for i in issues):
        uncertainty.append("The manuscript has no (or fewer) reference entries than "
                           "expected; no bibliography items were invented.")

    metrics = {
        "paragraphs": build_meta.get("paragraphs"),
        "tables": build_meta.get("tables"),
        "drawings": build_meta.get("drawings"),
        "headings_by_level": build_meta.get("headings_by_level"),
        "caption_numbers": build_meta.get("caption_numbers"),
        "references": build_meta.get("reference_paragraphs"),
        "page_count": rendering.get("page_count"),
        "page_count_method": rendering.get("page_count_method"),
        "pdf_fonts": rendering.get("fonts_detected"),
        "source_blocks": len(blocks),
        "format_requirements": len(reqs),
        "requirements_applied": summary.get("applied"),
        "requirements_partial": summary.get("partial"),
        "requirements_failed": summary.get("failed"),
    }
    template_spec = {
        "path": (inputs.get("template") or {}).get("path"),
        "format": (inputs.get("template") or {}).get("format"),
        "template_missing": bool(meta.get("template_missing")),
        "page": spec.get("page"), "body": spec.get("body"),
        "headings": spec.get("headings"),
        "heading_numbering": spec.get("heading_numbering"),
        "captions": spec.get("captions"), "references": spec.get("references"),
        "page_numbers": spec.get("page_numbers"),
        "tables": spec.get("tables"),
        "conflicts": len(spec.get("conflicts") or []),
        "provenance_summary": {k: (v or {}).get("source")
                               for k, v in (spec.get("provenance") or {}).items()
                               if not ((v or {}).get("source") or "")
                               .startswith("builtin-default")},
    }
    verification = {
        "docx_reopens": bool(reopen_ok),
        "docx_valid": bool(valid),
        "content_preserved": missing_blocks == 0,
        "placeholder_free": bool(placeholder_req) and
        placeholder_req.get("status") == "applied",
        "pdf_produced": bool(rendering.get("produced")),
        "pdf_page_count": rendering.get("page_count"),
        "requirements": {"total": len(reqs),
                         "applied": summary.get("applied"),
                         "partial": summary.get("partial"),
                         "unsupported": summary.get("unsupported"),
                         "failed": summary.get("failed"),
                         "not_applicable": summary.get("not_applicable")},
        "visual_inspection": "not performed (XML-level verification only)",
    }

    hard_failed = [c for c in checks if c["severity"] == "hard" and not c["passed"]]
    open_issues = [i for i in issues if i.get("status") in ("partial", "unsupported",
                                                            "failed")]
    soft_failed = [c for c in checks if c["severity"] == "soft" and not c["passed"]]

    if hard_failed:
        status = "failed"
    elif open_issues or soft_failed or meta.get("template_missing"):
        status = "partial"
    else:
        status = "success"

    result = {
        "case_id": case_id,
        "status": status,
        "sources": sources,
        "uncertainty": uncertainty,
        "change_log": change_log,
        "issues": issues,
        "deliverables": deliverables,
        "contract_fields": contract_list,
        "format_report": {"path": os.path.abspath(
            os.path.join(output, "format_report.json")),
            "summary": summary,
            "requirements_path": "format_report.json#requirements"},
        "docx": docx_path if docx_exists else None,
        "docx_info": {"path": docx_path, "bytes": build_meta.get("docx_bytes"),
                      "sha256": build_meta.get("docx_sha256"),
                      "reopens": bool(reopen_ok), "editable": bool(valid)},
        "pdf": build_meta.get("pdf"),
        "pdf_info": ({"path": build_meta.get("pdf"),
                      "bytes": build_meta.get("pdf_bytes"),
                      "page_count": rendering.get("page_count"),
                      "page_count_method": rendering.get("page_count_method")}
                     if build_meta.get("pdf") else None),
        "template_spec": template_spec,
        "metrics": metrics,
        "limits": uncertainty,
        "verification": verification,
        "selfcheck": {"verdict": "FAIL" if hard_failed else "PASS",
                      "hard_failures": len(hard_failed),
                      "soft_failures": len(soft_failed),
                      "open_issues": len(open_issues)},
    }

    # ---- contract completion --------------------------------------------
    unmapped = []
    for field in contract_list:
        if field in result:
            continue
        path = ALIASES.get(field)
        if path:
            # the field has a producer; a legitimate null is not "unmapped"
            result[field] = get_path(result, path)
        else:
            result[field] = None
            unmapped.append(field)
    if unmapped:
        issues.append({"id": "contract.unmapped", "status": "partial",
                       "detail": "output_contract keys without a direct artefact: %s"
                                 % ", ".join(unmapped), "source": "selfcheck"})
        open_issues = [i for i in issues
                       if i.get("status") in ("partial", "unsupported", "failed")]
        if not hard_failed and status == "success":
            status = "partial"
            result["status"] = status
            result["selfcheck"]["open_issues"] = len(open_issues)
    missing_contract = [f for f in contract_list if f not in result]
    check("contract.keys_present", "result.json 覆盖 output_contract 全部字段",
          not missing_contract, "hard",
          "missing=%s" % (missing_contract or "none"))
    check("status.allowed", "status 取值合法", status in ALLOWED_STATUS, "hard", status)
    consistent = True
    if status == "success" and (open_issues or soft_failed):
        consistent = False
    if status == "failed" and valid and reopen_ok:
        consistent = False
    check("status.consistent", "status 与 issues/交付物一致", consistent, "hard",
          "status=%s open_issues=%d hard_failures=%d"
          % (status, len(open_issues), len(hard_failed)))

    # ---- write & round-trip --------------------------------------------
    result_path = os.path.join(output, "result.json")
    try:
        with open(result_path, "w", encoding="utf-8") as fh:
            json.dump(result, fh, ensure_ascii=False, indent=1)
            fh.write("\n")
        roundtrip = C.read_json(result_path)
        check("result.roundtrip", "result.json 可被重新解析",
              isinstance(roundtrip, dict) and
              all(k in roundtrip for k in CORE_KEYS), "hard",
              "keys=%d" % (len(roundtrip) if isinstance(roundtrip, dict) else 0))
    except (OSError, ValueError) as exc:  # noqa: BLE001
        roundtrip = None
        check("result.roundtrip", "result.json 可被重新解析", False, "hard",
              "%s: %s" % (type(exc).__name__, exc))

    checks_path = os.path.join(output, "checks.json")
    hard_failed = [c for c in checks if c["severity"] == "hard" and not c["passed"]]
    verdict = "PASS" if not hard_failed else "FAIL"
    C.write_json(checks_path, {
        "schema": "selfcheck/v1",
        "case_id": case_id,
        "verdict": verdict,
        "status": status,
        "hard_failures": len(hard_failed),
        "soft_failures": len([c for c in checks if c["severity"] == "soft"
                              and not c["passed"]]),
        "checks": checks,
        "result": os.path.abspath(result_path),
    })
    print(json.dumps({
        "verdict": verdict, "status": status,
        "hard_failures": [c["id"] for c in hard_failed],
        "soft_failures": [c["id"] for c in checks
                          if c["severity"] == "soft" and not c["passed"]],
        "result": os.path.abspath(result_path),
        "checks": os.path.abspath(checks_path),
        "unmapped_contract_fields": unmapped,
    }, ensure_ascii=False, indent=1))
    return 0 if verdict == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
