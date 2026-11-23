#!/usr/bin/env python3
"""kernel.py - runtime contract guard: parse case.json, emit result.json, check it.

The evaluator's case.json may spell the contract as an object, an array of names, an
array of {name/key/field} objects, a nested schema, or a comma-separated string. It may
also be malformed. This module never crashes on any of that:

  init   reads case.json (tolerant aliases), extracts every contract field, records
         materials and task text, and writes work/case.json. Malformed input yields a
         blocked contract, not an exception.
  emit   writes /app/output/result.json where **every** contract field is present
         (unknown fields are present as null and listed in unmapped_contract_fields)
         plus case_id, status, deliverables, element_map, caption, selfcheck,
         limits, uncertainty and change_log. It never emits an empty contract.
  check  fails only on a dishonest result: missing case_id/status, status=ok together
         with a failed selfcheck or missing declared deliverables.

Usage:
  python3 scripts/kernel.py init  --case /input/case.json --materials /input --work /app/work
  python3 scripts/kernel.py emit  --draft /app/work/draft.json --out /app/output
  python3 scripts/kernel.py check --result /app/output/result.json
"""
import argparse
import hashlib
import json
import os
import re
import sys

DEFAULT_CONTRACT = [
    "case_id", "status", "figure_svg", "figure_png", "figure_pdf", "caption",
    "element_map", "data_profile", "selfcheck", "deliverables", "sources",
    "limits", "uncertainty", "change_log", "metrics",
]
CASE_ID_KEYS = ("case_id", "caseId", "id", "task_id", "instance_id", "challenge_id",
                "uuid", "key")
CONTRACT_KEYS = ("output_contract", "output_contracts", "required_output_fields",
                 "expected_output", "expected_outputs", "outputs", "contract",
                 "output_fields", "result_contract", "deliverable_fields",
                 "required_fields", "result_fields")
TEXT_KEYS = ("task", "task_text", "instruction", "instructions", "prompt", "description",
             "workorder", "work_order", "question", "requirements", "goal")
MATERIAL_KEYS = ("materials", "inputs", "files", "documents", "resources",
                 "attachments", "data", "data_files", "input_files", "artifacts")
ALLOWED_STATUS = ("ok", "partial", "blocked", "failed", "refused")
REQUIRED_CORE = ["case_id", "status", "deliverables", "element_map", "caption",
                 "selfcheck", "limits", "uncertainty", "change_log", "sources"]

ALIASES = {
    "caseid": "case_id", "id": "case_id", "taskid": "case_id",
    "status": "status", "state": "status", "success": "status",
    "deliverables": "deliverables", "artifacts": "deliverables", "exports": "exports",
    "outputfiles": "deliverables", "files": "deliverables",
    "elementmap": "element_map", "elementmapping": "element_map",
    "elementmappingfile": "element_map_file", "elementsourcemap": "element_map",
    "sourcemap": "element_map", "provenance": "element_map", "mapping": "element_map",
    "trace": "element_map", "sourcetrace": "element_map",
    "evidencemap": "element_map", "evidencemapping": "element_map",
    "elementtrace": "element_map", "traceability": "element_map",
    "datamapping": "element_map", "pointmap": "element_map",
    "figuremap": "element_map", "chartmap": "element_map", "srcmap": "element_map",
    "caption": "caption", "figurecaption": "caption", "legend": "caption",
    "figuresvg": "figure_svg", "svg": "figure_svg", "source": "figure_svg",
    "figurepng": "figure_png", "png": "figure_png", "figurepdf": "figure_pdf",
    "preview": "figure_png", "previewpng": "figure_png", "raster": "figure_png",
    "vector": "figure_svg", "vectorfile": "figure_svg",
    "pdf": "figure_pdf", "figure": "figure_svg",
    "selfcheck": "selfcheck", "check": "selfcheck", "validation": "selfcheck",
    "checks": "selfcheck", "qa": "selfcheck",
    "limits": "limits", "limitations": "limits", "caveats": "limits",
    "uncertainty": "uncertainty", "uncertainties": "uncertainty", "risks": "uncertainty",
    "changelog": "change_log", "editlog": "change_log", "revision": "change_log",
    "changes": "change_log", "diff": "change_log",
    "samplesizes": "sample_sizes", "samplesize": "sample_sizes", "n": "sample_sizes",
    "errorsemantics": "error_semantics", "errortype": "error_semantics",
    "errors": "error_semantics",
    "sources": "sources", "sourcefiles": "sources", "datasource": "sources",
    "inputfiles": "input_files", "inputs": "input_files",
    "code": "code_path", "script": "code_path", "codepath": "code_path",
    "chartspec": "chart_spec", "spec": "chart_spec", "figurespec": "chart_spec",
    "metrics": "metrics", "statistics": "metrics", "stats": "metrics",
    "title": "title", "figuretitle": "title",
    "charttype": "chart_type", "figuretype": "chart_type", "type": "chart_type",
    "panelcount": "panel_count", "panels": "panel_count",
    "dataprofile": "data_profile", "profile": "data_profile",
    "datasnapshot": "data_snapshot", "snapshot": "data_snapshot",
}


def sha256_text(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def sha256_file(path):
    h = hashlib.sha256()
    try:
        with open(path, "rb") as fh:
            for chunk in iter(lambda: fh.read(1 << 20), b""):
                h.update(chunk)
    except OSError:
        return ""
    return h.hexdigest()


def norm(s):
    return re.sub(r"[^0-9a-z]", "", str(s).lower())


def canonical(name):
    n = norm(name)
    if n in ALIASES:
        return ALIASES[n]
    checks = [
        (("caseid",), "case_id"), (("status", "success", "state"), "status"),
        (("deliverable", "artifact", "export", "outputfile"), "deliverables"),
        (("element", "mapping", "provenance", "sourcetrace"), "element_map"),
        (("caption", "figcaption"), "caption"),
        (("whitespacefigure", "figurecaption"), "caption"),
        (("svg",), "figure_svg"), (("png",), "figure_png"), (("pdf",), "figure_pdf"),
        (("selfcheck", "validation", "check"), "selfcheck"),
        (("limit", "caveat"), "limits"), (("uncertain", "risk"), "uncertainty"),
        (("change", "edit", "diff"), "change_log"),
        (("samplesize", "samplesizes"), "sample_sizes"),
        (("errorsemantic", "errorbar"), "error_semantics"),
        (("source", "provenance"), "sources"),
        (("code", "script"), "code_path"),
        (("spec",), "chart_spec"), (("metric", "stat"), "metrics"),
        (("title",), "title"), (("charttype", "figuretype"), "chart_type"),
        (("panel",), "panel_count"), (("datafile", "inputfile", "table"), "input_files"),
        (("profile",), "data_profile"), (("snapshot",), "data_snapshot"),
        (("figure", "chart", "image"), "figure_svg"),
    ]
    for keys, target in checks:
        if any(k in n for k in keys):
            return target
    return ""


def extract_contract(case):
    raw = None
    for key in CONTRACT_KEYS:
        if isinstance(case, dict) and key in case and case[key] not in (None, "", [], {}):
            raw = case[key]
            break
    if raw is None and isinstance(case, dict):
        for key in ("result", "output", "expected"):
            inner = case.get(key)
            if isinstance(inner, dict) and any(k in inner for k in CONTRACT_KEYS):
                return extract_contract(inner)
    fields = []
    if isinstance(raw, dict):
        inner = raw.get("properties") or raw.get("fields") or raw.get("required")
        if isinstance(inner, dict):
            fields = list(inner.keys())
        elif isinstance(inner, list):
            fields = inner
        else:
            fields = list(raw.keys())
    elif isinstance(raw, list):
        for item in raw:
            if isinstance(item, str):
                fields.append(item)
            elif isinstance(item, dict):
                for k in ("name", "key", "field", "id", "path"):
                    if item.get(k):
                        fields.append(item[k])
                        break
    elif isinstance(raw, str):
        fields = [x.strip() for x in re.split(r"[,;\n]", raw) if x.strip()]
    out, seen = [], set()
    for f in fields:
        f = str(f).strip()
        if f and f.lower() not in seen:
            seen.add(f.lower())
            out.append(f)
    return out, type(raw).__name__ if raw is not None else "missing"


def read_case(path):
    info = {"blocked": "", "case": {}, "raw_text": "", "sha256": "",
            "path": path, "error": ""}
    if not path or not os.path.exists(path):
        info["blocked"] = "case.json not found"
        return info
    try:
        info["raw_text"] = open(path, encoding="utf-8", errors="replace").read()
        info["sha256"] = sha256_text(info["raw_text"])
        case = json.loads(info["raw_text"])
    except Exception as exc:  # noqa: BLE001
        info["blocked"] = "malformed case.json: %s" % exc
        info["error"] = str(exc)
        return info
    if isinstance(case, list) and case and isinstance(case[0], dict):
        case = case[0]
    if not isinstance(case, dict):
        info["blocked"] = "case.json is not an object (got %s)" % type(case).__name__
        return info
    info["case"] = case
    return info


def case_id_of(case, fallback_seed):
    for k in CASE_ID_KEYS:
        if isinstance(case, dict) and case.get(k):
            return str(case[k])
    return "local-" + hashlib.sha256(fallback_seed.encode("utf-8")).hexdigest()[:10]


def collect_materials(case, base):
    items = []

    def push(v, origin):
        if isinstance(v, str):
            p = v if os.path.isabs(v) else os.path.join(base, v)
            items.append({"path": p, "value": v, "origin": origin})
        elif isinstance(v, dict):
            for k in ("path", "file", "name", "url", "href", "location"):
                if v.get(k):
                    push(v[k], origin)
                    return
        elif isinstance(v, list):
            for x in v:
                push(x, origin)

    for key in MATERIAL_KEYS:
        if isinstance(case, dict) and case.get(key):
            push(case[key], key)
    seen, out = set(), []
    for it in items:
        if it["path"] not in seen:
            seen.add(it["path"])
            out.append(it)
    return out


def task_text_of(case):
    parts = []
    for k in TEXT_KEYS:
        v = case.get(k) if isinstance(case, dict) else None
        if isinstance(v, str) and v.strip():
            parts.append(v.strip())
        elif isinstance(v, list):
            parts += [str(x) for x in v if str(x).strip()]
    return "\n\n".join(parts)[:20000]


def cmd_init(a):
    os.makedirs(a.work, exist_ok=True)
    info = read_case(a.case)
    case = info["case"]
    fields, raw_type = extract_contract(case)
    if a.contract:
        fields = [x.strip() for x in a.contract.split(",") if x.strip()]
        raw_type = "cli"
    if not fields:
        fields = list(DEFAULT_CONTRACT)
        raw_type = "default"
    cid = case_id_of(case, info["sha256"] or info["path"])
    payload = {
        "case_id": cid,
        "case_path": a.case,
        "case_sha256": info["sha256"],
        "contract_fields": fields,
        "contract_raw_type": raw_type,
        "materials": collect_materials(case, a.materials),
        "task_text": task_text_of(case),
        "blocked": info["blocked"],
        "error": info["error"],
        "case_keys": sorted(case.keys()) if isinstance(case, dict) else [],
        "mode": case.get("mode", "") if isinstance(case, dict) else "",
        "hints": {k: case.get(k) for k in ("chart_type", "figure_type", "intent",
                                           "edit_instructions", "workorder", "title")
                  if isinstance(case, dict) and case.get(k)},
    }
    with open(os.path.join(a.work, "case.json"), "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=1)
    if payload["task_text"]:
        with open(os.path.join(a.work, "task.md"), "w", encoding="utf-8") as fh:
            fh.write(payload["task_text"])
    print("case_id=%s contract=%d fields (%s) materials=%d blocked=%r"
          % (cid, len(fields), raw_type, len(payload["materials"]),
             payload["blocked"]))
    for f in fields:
        print("  field:", f)
    return 0


def _file_record(out_dir, rel, role):
    p = os.path.join(out_dir, rel)
    exists = os.path.exists(p)
    return {"path": rel, "role": role, "format": os.path.splitext(rel)[1].lstrip("."),
            "exists": exists, "bytes": os.path.getsize(p) if exists else 0,
            "sha256": sha256_file(p) if exists else ""}


def _read_json_soft(path, default=None):
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:  # noqa: BLE001
        return default


def _autofill(draft, out_dir):
    """Fill an emit draft from the artifacts when the caller did not write one."""
    spec = _read_json_soft(os.path.join(out_dir, "chart_spec.json"), {}) or {}
    selfcheck = _read_json_soft(os.path.join(out_dir, "selfcheck.json"), {}) or {}
    snapshot = _read_json_soft(os.path.join(out_dir, "data_snapshot.json"), {}) or {}
    caption = draft.get("caption")
    if not caption:
        cpath = os.path.join(out_dir, "caption.md")
        if os.path.exists(cpath):
            try:
                caption = open(cpath, encoding="utf-8").read()
            except OSError:
                caption = None
    draft.setdefault("caption", caption)
    panels = spec.get("panels") or []
    draft.setdefault("title", spec.get("title"))
    draft.setdefault("chart_type", spec.get("chart_type"))
    draft.setdefault("panel_count", len(panels))
    draft.setdefault("chart_spec", {"file": "chart_spec.json",
                                    "chart_type": spec.get("chart_type"),
                                    "panels": [p.get("id") for p in panels]}
                     if spec else None)
    draft.setdefault("selfcheck", {k: selfcheck.get(k) for k in
                                   ("verdict", "errors", "warnings")} if selfcheck else None)
    draft.setdefault("error_semantics", spec.get("error_semantics"))
    draft.setdefault("sample_sizes", {p.get("id"): p.get("sample_sizes") for p in panels}
                     if panels else {})
    if not draft.get("sources") and snapshot:
        draft["sources"] = [{"file": snapshot.get("source", ""),
                             "sha256": snapshot.get("source_sha256", ""),
                             "rows": snapshot.get("rows"),
                             "columns": snapshot.get("columns"), "role": "data"}]
    if not draft.get("sources") and isinstance(spec.get("source"), dict):
        src = spec["source"]
        draft["sources"] = [{"file": src.get("file", ""),
                             "sha256": src.get("sha256", ""),
                             "rows": src.get("rows"), "role": "data"}]
    if snapshot:
        draft.setdefault("data_snapshot", snapshot)
    emap = _read_json_soft(os.path.join(out_dir, "element_map.json"), {}) or {}
    if emap:
        els = emap.get("elements") or []
        draft.setdefault("element_map", {"file": "element_map.json",
                                         "counts": emap.get("counts", {}),
                                         "sha256": emap.get("sha256", ""),
                                         "sample": els[:8]})
    profile = _read_json_soft(os.path.join(out_dir, "data_profile.json"), {}) or {}
    if profile:
        draft.setdefault("data_profile", {"file": "data_profile.json",
                                          "rows": profile.get("rows"),
                                          "columns": profile.get("columns"),
                                          "sha256": profile.get("sha256"),
                                          "warnings": (profile.get("warnings") or [])[:10]})
    png = os.path.join(out_dir, "figure.png")
    pdf = os.path.join(out_dir, "figure.pdf")
    if not draft.get("status"):
        ok = (selfcheck.get("verdict") == "PASS" and os.path.exists(png)
              and os.path.exists(pdf))
        draft["status"] = "ok" if ok else "partial"
    return draft


def cmd_emit(a):
    os.makedirs(a.out, exist_ok=True)
    draft = {}
    if a.draft and os.path.exists(a.draft):
        try:
            draft = json.load(open(a.draft, encoding="utf-8"))
        except Exception as exc:  # noqa: BLE001
            draft = {"status": "partial", "uncertainty": ["draft unreadable: %s" % exc]}
    contract = list(DEFAULT_CONTRACT)
    cid = draft.get("case_id", "")
    case_doc = {}
    cpath = os.path.join(a.work, "case.json") if a.work else ""
    if cpath and os.path.exists(cpath):
        case_doc = json.load(open(cpath, encoding="utf-8"))
        contract = case_doc.get("contract_fields") or contract
        cid = cid or case_doc.get("case_id", "")
    if a.case_id:
        cid = a.case_id
    if not cid:
        cid = "local-unknown"

    draft = _autofill(draft, a.out)
    status = str(draft.get("status") or "partial")
    if status not in ALLOWED_STATUS:
        status = "partial"

    deliverables = draft.get("deliverables")
    if not deliverables:
        roles = [("figure.svg", "figure_svg"), ("figure.png", "figure_png"),
                 ("figure.pdf", "figure_pdf"), ("caption.md", "caption"),
                 ("element_map.json", "element_map"),
                 ("chart_spec.json", "chart_spec"),
                 ("selfcheck.json", "selfcheck"), ("edit_log.json", "change_log"),
                 ("data_profile.json", "data_profile")]
        deliverables = [_file_record(a.out, rel, role) for rel, role in roles
                        if os.path.exists(os.path.join(a.out, rel))]
    missing = [d["path"] for d in deliverables if not d.get("exists", True)]

    canon_values = {k: draft.get(k) for k in draft}
    canon_values.update({
        "case_id": cid, "status": status, "deliverables": deliverables,
        "figure_svg": draft.get("figure_svg") or ("figure.svg"
                                                  if os.path.exists(os.path.join(a.out, "figure.svg"))
                                                  else None),
        "figure_png": draft.get("figure_png") or ("figure.png"
                                                  if os.path.exists(os.path.join(a.out, "figure.png"))
                                                  else None),
        "figure_pdf": draft.get("figure_pdf") or ("figure.pdf"
                                                  if os.path.exists(os.path.join(a.out, "figure.pdf"))
                                                  else None),
        "caption": draft.get("caption"),
        "caption_file": draft.get("caption_file") or ("caption.md"
                                                      if os.path.exists(os.path.join(a.out, "caption.md"))
                                                      else None),
        "element_map": draft.get("element_map"),
        "element_map_file": draft.get("element_map_file") or (
            "element_map.json" if os.path.exists(os.path.join(a.out, "element_map.json"))
            else None),
        "selfcheck": draft.get("selfcheck"),
        "selfcheck_file": draft.get("selfcheck_file") or (
            "selfcheck.json" if os.path.exists(os.path.join(a.out, "selfcheck.json"))
            else None),
        "metrics": draft.get("metrics") or {},
        "sources": draft.get("sources") or [],
        "limits": draft.get("limits") or [],
        "uncertainty": draft.get("uncertainty") or [],
        "change_log": draft.get("change_log") or "initial generation from source data; "
                                                  "no manual edits",
        "change_details": draft.get("change_details") or {},
        "sample_sizes": draft.get("sample_sizes") or {},
        "error_semantics": draft.get("error_semantics") or {},
        "title": draft.get("title") or "",
        "chart_type": draft.get("chart_type") or "",
        "panel_count": draft.get("panel_count") or 0,
        "fatal_error": draft.get("fatal_error"),
        "chart_spec": draft.get("chart_spec"),
        "chart_spec_file": draft.get("chart_spec_file") or (
            "chart_spec.json" if os.path.exists(os.path.join(a.out, "chart_spec.json"))
            else None),
        "data_profile": draft.get("data_profile"),
        "data_snapshot": draft.get("data_snapshot"),
        "input_files": draft.get("input_files") or [],
        "code_path": draft.get("code_path") or "scripts/run_case.py",
        "exports": draft.get("exports") or [d["path"] for d in deliverables],
    })

    if missing and status == "ok":
        status = "partial"
        canon_values["status"] = status
        canon_values["uncertainty"].append("declared deliverables missing: %s"
                                           % ", ".join(missing))

    result = {}
    unmapped = []
    for field in contract:
        target = canonical(field)
        if target and target in canon_values and canon_values[target] is not None:
            result[field] = canon_values[target]
        elif target and target in canon_values:
            result[field] = canon_values[target]
        else:
            result[field] = None
            unmapped.append(field)
    for core in REQUIRED_CORE:
        if core not in result:
            target = core
            result[target] = canon_values.get(target)
    for key in ("title", "chart_type", "panel_count", "fatal_error", "error_semantics",
                "sample_sizes",
                "chart_spec", "chart_spec_file", "caption_file", "element_map_file",
                "selfcheck_file", "change_details", "input_files", "exports",
                "data_profile", "data_snapshot", "code_path", "success", "metrics"):
        if key not in result:
            result[key] = canon_values.get(key)
    result["case_id"] = cid
    result["status"] = status
    result["success"] = status == "ok"
    result["contract_fields"] = contract
    result["unmapped_contract_fields"] = unmapped
    if unmapped:
        result.setdefault("uncertainty", [])
        if isinstance(result["uncertainty"], list):
            result["uncertainty"].append(
                "contract fields without a canonical producer were emitted as null: %s"
                % ", ".join(unmapped))

    with open(os.path.join(a.out, "result.json"), "w", encoding="utf-8") as fh:
        json.dump(result, fh, ensure_ascii=False, indent=1)
    print("result.json written: case_id=%s status=%s contract=%d missing=%d unmapped=%d"
          % (cid, status, len(contract), len(missing), len(unmapped)))
    return 0


def cmd_check(a):
    problems = []
    if not os.path.exists(a.result):
        print("FAIL: result.json missing at %s" % a.result)
        return 1
    try:
        res = json.load(open(a.result, encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        print("FAIL: result.json is not valid JSON: %s" % exc)
        return 1
    if not res.get("case_id"):
        problems.append("case_id missing")
    if res.get("status") not in ALLOWED_STATUS:
        problems.append("status invalid: %r" % res.get("status"))
    contract = []
    cpath = os.path.join(a.work, "case.json") if a.work else ""
    if cpath and os.path.exists(cpath):
        contract = json.load(open(cpath, encoding="utf-8")).get("contract_fields") or []
    for f in contract:
        if f not in res:
            problems.append("contract field missing from result.json: %s" % f)
    sc = res.get("selfcheck")
    verdict = ""
    if isinstance(sc, dict):
        verdict = str(sc.get("verdict", sc.get("status", ""))).upper()
    if res.get("status") == "ok" and verdict and verdict != "PASS":
        problems.append("status=ok but selfcheck verdict=%s" % verdict)
    if res.get("status") == "ok" and res.get("fatal_error"):
        problems.append("status=ok but fatal_error is set: %s" % res.get("fatal_error"))
    if res.get("status") == "ok":
        for d in res.get("deliverables") or []:
            if not d.get("exists", True) or not d.get("bytes"):
                problems.append("status=ok but deliverable missing/empty: %s"
                                % d.get("path"))
    if not res.get("caption"):
        problems.append("caption is empty")
    if res.get("status") != "blocked" and not res.get("element_map"):
        problems.append("element_map is empty")
    if problems:
        print("FAIL")
        for p in problems:
            print(" -", p)
        return 1
    print("PASS case_id=%s status=%s contract=%d deliverables=%d selfcheck=%s"
          % (res.get("case_id"), res.get("status"), len(contract),
             len(res.get("deliverables") or []), verdict or "n/a"))
    return 0


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd")
    p1 = sub.add_parser("init")
    p1.add_argument("--case", default="/input/case.json")
    p1.add_argument("--materials", default="/input")
    p1.add_argument("--work", default="/app/work")
    p1.add_argument("--contract", default="")
    p1.set_defaults(func=cmd_init)

    p2 = sub.add_parser("emit")
    p2.add_argument("--draft", default="")
    p2.add_argument("--out", default="/app/output")
    p2.add_argument("--work", default="")
    p2.add_argument("--case-id", default="")
    p2.set_defaults(func=cmd_emit)

    p3 = sub.add_parser("check")
    p3.add_argument("--result", default="/app/output/result.json")
    p3.add_argument("--work", default="")
    p3.set_defaults(func=cmd_check)

    a = ap.parse_args()
    if not getattr(a, "func", None):
        ap.print_help()
        return 2
    return a.func(a)


if __name__ == "__main__":
    sys.exit(main())
