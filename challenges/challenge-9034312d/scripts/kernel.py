#!/usr/bin/env python3
"""kernel.py - contract guard + material reader for the apparatus/route figure skill.

Stdlib only, no network. Three jobs:

  init   read /input/case.json (tolerant of aliases and malformed JSON), extract the
         output contract in every shape it may appear (list, object, nested schema,
         comma string), record materials and task text into work/case.json.
  emit   write /app/output/result.json with **every** contract field present. Values are
         the real artifacts; unknown fields become null and are listed in
         unmapped_contract_fields. Values are NEVER nested under an extra "fields" key.
  check  fail only on a dishonest result (status=ok with a failed selfcheck, missing
         declared deliverable, empty element_map/caption, or a missing contract field).

It also exposes read_docx/read_xlsx/read_pdf/extract so the extraction stage can read
real materials (PDF text layer, docx, xlsx) instead of guessing from file names.

Usage:
  python3 scripts/kernel.py init  --case /input/case.json --materials /input --work /app/work
  python3 scripts/kernel.py emit  --draft /app/work/draft.json --out /app/output --work /app/work
  python3 scripts/kernel.py check --result /app/output/result.json --work /app/work
"""
import argparse
import hashlib
import html
import json
import os
import re
import sys
import zipfile

# Diagram-first default contract. Extra producer-only keys are added after these.
DEFAULT_CONTRACT = [
    "case_id", "status", "source_file", "exports", "preview", "extraction",
    "element_map", "parts", "connections", "stages", "route_graph", "legend",
    "units", "scale_bar", "caption", "selfcheck", "deliverables", "sources",
    "limits", "uncertainty", "change_log", "metrics",
]
CORE_ALWAYS = ["case_id", "status", "deliverables", "element_map", "caption",
               "selfcheck", "limits", "uncertainty", "sources", "change_log"]
CASE_ID_KEYS = ("case_id", "caseId", "id", "task_id", "instance_id", "challenge_id",
                "uuid", "key")
CONTRACT_KEYS = ("output_contract", "output_contracts", "required_output_fields",
                 "expected_output", "expected_outputs", "outputs", "contract",
                 "output_fields", "result_contract", "deliverable_fields",
                 "required_fields", "result_fields")
TEXT_KEYS = ("task", "task_text", "instruction", "instructions", "prompt", "description",
             "workorder", "work_order", "question", "requirements", "goal", "request")
MATERIAL_KEYS = ("materials", "inputs", "files", "documents", "resources",
                 "attachments", "data", "data_files", "input_files", "artifacts",
                 "source_svg", "svg_path", "figure_svg", "input")
ALLOWED_STATUS = ("ok", "partial", "blocked", "failed", "refused")
TEXT_EXT = {".txt", ".md", ".csv", ".tsv", ".json", ".tex", ".bib", ".yaml", ".yml",
            ".rst", ".html", ".xml"}

# canonical name -> accepted spellings (normalised: lowercase, alnum only)
ALIASES = {
    "case_id": ["caseid", "id", "taskid", "instanceid", "challengeid", "uuid", "key"],
    "status": ["status", "state", "success", "resultstatus"],
    "source_file": ["sourcefile", "sourcepath", "svgpath", "figuresvg", "svg", "source"],
    "exports": ["exports", "exportfiles", "renderedfiles"],
    "preview": ["preview", "previewstatus", "renderpreview"],
    "extraction": ["extraction", "extractreport", "extractionreport"],
    "element_map": ["elementmap", "elementmapping", "elementsourcemap", "sourcemap",
                    "provenance", "mapping", "trace", "sourcetrace"],
    "parts": ["parts", "components", "devices", "apparatus", "equipment", "units",
              "nodes", "elements"],
    "connections": ["connections", "links", "pipes", "flows", "connectors", "edges",
                    "tubing"],
    "stages": ["stages", "steps", "phases", "milestones", "workflow", "procedure",
               "route", "stepsflow"],
    "route_graph": ["routegraph", "graph", "diagram", "figuregraph", "apparatusgraph"],
    "legend": ["legend", "linetypes", "linestylelegend", "figurelegend", "legenditems"],
    "units": ["units", "unit", "measurementunits", "unitlabels"],
    "scale_bar": ["scalebar", "scale", "scalenote"],
    "figure_png": ["figurepng", "png", "rasterimage", "previewpng"],
    "figure_pdf": ["figurepdf", "pdf"],
    "caption": ["caption", "figurecaption", "figcaption", "captiontext"],
    "selfcheck": ["selfcheck", "check", "validation", "checks", "qa", "selfchecks"],
    "deliverables": ["deliverables", "artifacts", "outputfiles", "files", "outputs",
                     "deliverablefiles"],
    "sources": ["sources", "sourcefiles", "datasource", "evidencesources", "evidence",
                "references"],
    "limits": ["limits", "limitations", "caveats", "limit"],
    "uncertainty": ["uncertainty", "uncertainties", "risks", "unknowns", "ambiguities"],
    "change_log": ["changelog", "editlog", "revision", "changes", "diff", "changelogtext"],
    "metrics": ["metrics", "statistics", "stats", "numbers"],
    "title": ["title", "figuretitle", "name"],
}
# 中文契约字段名（norm 保留 CJK 后才能命中；否则中文键会被清成空串而丢失）
ZH_ALIASES = {
    "装置清单": "parts", "部件清单": "parts", "设备清单": "parts", "组件清单": "parts",
    "部件": "parts", "组件": "parts", "装置": "parts", "设备": "parts",
    "连接关系": "connections", "连接": "connections", "连线": "connections",
    "流向": "connections", "管路连接": "connections",
    "技术路线": "stages", "路线": "stages", "步骤": "stages", "阶段": "stages",
    "工序": "stages", "流程": "stages",
    "图注": "caption", "图题": "caption", "说明": "caption",
    "自检": "selfcheck", "机检": "selfcheck", "检查": "selfcheck",
    "证据": "element_map", "证据链": "element_map", "元素映射": "element_map",
    "来源映射": "element_map",
    "限制": "limits", "局限": "limits", "限制说明": "limits",
    "不确定度": "uncertainty", "不确定性": "uncertainty", "风险": "uncertainty",
    "图例": "legend", "单位": "units", "比例尺": "scale_bar",
    "标题": "title", "指标": "metrics",
}
# extra producer-only keys emitted even if the contract does not mention them
EXTRA_KEYS = ["title", "exports", "preview", "extraction", "route_graph", "parts",
              "connections", "stages", "legend", "units", "scale_bar", "figure_png",
              "figure_pdf", "metrics", "element_map_file", "caption_file",
              "source_file", "deliverables", "change_details", "input_files",
              "code_path", "success", "contract_fields", "unmapped_contract_fields"]


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
    # 保留 CJK：中文契约键（装置清单/连接关系/…）不能被清成空串
    return re.sub(r"[^0-9a-z\u4e00-\u9fff]", "", str(s).lower())


def canonical(name):
    n = norm(name)
    if n in ZH_ALIASES:
        return ZH_ALIASES[n]
    if n in ALIASES:
        return ALIASES[n][0]
    for target, names in ALIASES.items():
        if n in names:
            return target
    checks = [
        (("caseid",), "case_id"), (("status", "state", "success"), "status"),
        (("sourcefile", "svgpath", "figuresvg"), "source_file"),
        (("export",), "exports"), (("preview", "renderpreview"), "preview"),
        (("extract",), "extraction"),
        (("element", "provenance", "sourcetrace", "mapping"), "element_map"),
        (("component", "apparatus", "device"), "parts"),
        (("connection", "pipe", "flow", "edge"), "connections"),
        (("stage", "step", "phase", "milestone"), "stages"),
        (("routegraph", "diagram", "graph"), "route_graph"),
        (("caption", "figcaption"), "caption"),
        (("selfcheck", "validation", "check"), "selfcheck"),
        (("deliverable", "artifact", "outputfile"), "deliverables"),
        (("sources", "provenance"), "sources"),
        (("limit", "caveat"), "limits"), (("uncertain", "risk"), "uncertainty"),
        (("change", "edit", "diff"), "change_log"), (("metric", "stat"), "metrics"),
        (("title",), "title"),
    ]
    for keys, target in checks:
        if any(k in n for k in keys):
            return target
    return ""


# ---------------------------------------------------------------- material reading
def strip_xml(raw):
    raw = re.sub(r"<w:p[ >]", "\n<w:p ", raw)
    raw = re.sub(r"<[^>]+>", "", raw)
    return re.sub(r"\n{3,}", "\n\n", raw)


def read_docx(path):
    out = []
    try:
        with zipfile.ZipFile(path) as z:
            for n in sorted(x for x in z.namelist()
                            if x.startswith("word/") and x.endswith(".xml")):
                if "document" in n:
                    out.append(strip_xml(z.read(n).decode("utf-8", "replace")))
    except Exception as exc:  # noqa: BLE001
        return "[docx unreadable: %s]" % exc
    return "\n".join(out)


def read_xlsx(path):
    """Read every worksheet to tab-separated text (shared strings + inline strings)."""
    try:
        with zipfile.ZipFile(path) as z:
            shared = []
            if "xl/sharedStrings.xml" in z.namelist():
                s = z.read("xl/sharedStrings.xml").decode("utf-8", "replace")
                shared = [html.unescape(re.sub(r"<[^>]+>", "", m))
                          for m in re.findall(r"<si>(.*?)</si>", s, re.S)]
            rows_out = []
            for n in sorted(x for x in z.namelist()
                            if re.match(r"xl/worksheets/sheet\d+\.xml$", x)):
                x = z.read(n).decode("utf-8", "replace")
                rows_out.append("[sheet %s]" % n)
                for r in re.findall(r"<row[^>]*>(.*?)</row>", x, re.S):
                    cells = []
                    for attrs, body in re.findall(r"<c([^>]*)>(.*?)</c>", r, re.S):
                        v = re.search(r"<v>(.*?)</v>", body, re.S)
                        t = re.search(r't="([^"]+)"', attrs)
                        isv = re.search(r"<is>(.*?)</is>", body, re.S)
                        if isv is not None:
                            cells.append(html.unescape(re.sub(r"<[^>]+>", "", isv.group(1))))
                        elif v is None:
                            cells.append("")
                        elif t and t.group(1) == "s":
                            idx = int(v.group(1))
                            cells.append(shared[idx] if idx < len(shared) else "")
                        else:
                            cells.append(html.unescape(v.group(1)))
                    rows_out.append("\t".join(cells))
            return "\n".join(rows_out)
    except Exception as exc:  # noqa: BLE001
        return "[xlsx unreadable: %s]" % exc


def read_pdf(path):
    try:
        import subprocess
        r = subprocess.run(["pdftotext", "-layout", path, "-"],
                           capture_output=True, timeout=60)
        if r.returncode == 0 and r.stdout.strip():
            return r.stdout.decode("utf-8", "replace")
    except Exception:  # noqa: BLE001
        pass
    try:
        from pypdf import PdfReader  # type: ignore
        return "\n".join((p.extract_text() or "") for p in PdfReader(path).pages)
    except Exception:  # noqa: BLE001
        return ("[pdf text layer unavailable: scanned or no pdftotext/pypdf; "
                "do not guess page content]")


def extract(path):
    ext = os.path.splitext(path)[1].lower()
    try:
        if ext == ".docx":
            return read_docx(path)
        if ext in {".xlsx", ".xlsm"}:
            return read_xlsx(path)
        if ext == ".pdf":
            return read_pdf(path)
        if ext in TEXT_EXT:
            return open(path, encoding="utf-8", errors="replace").read()
        if ext in {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".svg", ".gif"}:
            return "[image asset: inspect visually; record size/content in evidence notes]"
    except Exception as exc:  # noqa: BLE001
        return "[unreadable %s: %s]" % (ext, exc)
    return "[unsupported type %s]" % ext


# ---------------------------------------------------------------- case parsing
def read_case(path):
    info = {"blocked": "", "case": {}, "raw_text": "", "sha256": "", "path": path,
            "error": ""}
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
            fields = [x if isinstance(x, str) else (x.get("name") or x.get("key") or "")
                      for x in inner]
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


def task_text_of(case):
    parts = []
    for k in TEXT_KEYS:
        v = case.get(k) if isinstance(case, dict) else None
        if isinstance(v, str) and v.strip():
            parts.append(v.strip())
        elif isinstance(v, list):
            parts += [str(x) for x in v if str(x).strip()]
    return "\n\n".join(parts)[:20000]


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
    for extra in DEFAULT_CONTRACT:
        if extra not in fields:
            fields.append(extra)
    cid = case_id_of(case, info["sha256"] or info["path"])
    payload = {
        "case_id": cid, "case_path": a.case, "case_sha256": info["sha256"],
        "contract_fields": fields, "contract_raw_type": raw_type,
        "materials": collect_materials(case, a.materials),
        "task_text": task_text_of(case), "blocked": info["blocked"],
        "error": info["error"], "case_keys": sorted(case.keys())
        if isinstance(case, dict) else [],
        "mode": case.get("mode", "") if isinstance(case, dict) else "",
        "hints": {k: case.get(k) for k in ("chart_type", "figure_type", "intent",
                                           "edit_instructions", "edits", "title",
                                           "parts", "connections", "stages", "units",
                                           "scale_bar", "source_svg", "svg_path")
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
    return 0


def _file_record(out_dir, rel, role):
    p = os.path.join(out_dir, rel)
    exists = os.path.exists(p)
    return {"path": rel, "role": role,
            "format": os.path.splitext(rel)[1].lstrip("."),
            "exists": exists, "bytes": os.path.getsize(p) if exists else 0,
            "sha256": sha256_file(p) if exists else ""}


def _read_json_soft(path, default=None):
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:  # noqa: BLE001
        return default


def _autofill(draft, out_dir):
    spec = _read_json_soft(os.path.join(out_dir, "spec.json"), {}) or {}
    graph = _read_json_soft(os.path.join(out_dir, "route_graph.json"), {}) or {}
    selfcheck = _read_json_soft(os.path.join(out_dir, "selfcheck.json"), {}) or {}
    exports = _read_json_soft(os.path.join(out_dir, "exports.json"), {}) or {}
    emap = _read_json_soft(os.path.join(out_dir, "element_map.json"), []) or []
    extract_rep = _read_json_soft(os.path.join(out_dir, "extraction_report.json"), {}) or {}
    caption = draft.get("caption")
    if not caption and os.path.exists(os.path.join(out_dir, "caption.md")):
        caption = open(os.path.join(out_dir, "caption.md"), encoding="utf-8").read()
    draft.setdefault("caption", caption)
    if graph:
        draft.setdefault("route_graph", graph)
        draft.setdefault("parts", graph.get("parts") or [])
        draft.setdefault("connections", graph.get("connections") or [])
        draft.setdefault("stages", graph.get("stages") or [])
        draft.setdefault("title", graph.get("title"))
    if selfcheck:
        draft.setdefault("selfcheck", selfcheck)
    if exports:
        draft.setdefault("exports", exports.get("exports") or [])
        draft.setdefault("preview", {"status": exports.get("preview_status"),
                                     "notes": exports.get("notes") or []})
    if extract_rep:
        draft.setdefault("extraction", {
            "mode": extract_rep.get("mode"),
            "files": extract_rep.get("files") or [],
            "coverage": extract_rep.get("coverage") or {},
            "warnings": extract_rep.get("warnings") or []})
    if emap:
        draft.setdefault("element_map", emap)
    if spec:
        draft.setdefault("source_file", spec.get("figure", {}).get("name", "route") + ".svg")
    if not draft.get("status"):
        ok = (isinstance(selfcheck, dict) and selfcheck.get("ok")
              and os.path.exists(os.path.join(out_dir, "route.png"))
              and os.path.exists(os.path.join(out_dir, "route.pdf")))
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
    cpath = os.path.join(a.work, "case.json") if a.work else ""
    if cpath and os.path.exists(cpath):
        case_doc = json.load(open(cpath, encoding="utf-8"))
        contract = case_doc.get("contract_fields") or contract
        cid = cid or case_doc.get("case_id", "")
    if a.case_id:
        cid = cid or a.case_id
    if not cid:
        cid = "local-unknown"

    draft = _autofill(draft, a.out)
    status = str(draft.get("status") or "partial")
    if status not in ALLOWED_STATUS:
        status = "partial"

    # explicit deliverable roles so every artifact is auditable
    roles = [("route.svg", "figure_svg"), ("route.png", "figure_png"),
             ("route.pdf", "figure_pdf"), ("caption.md", "caption"),
             ("element_map.json", "element_map"), ("spec.json", "spec"),
             ("route_graph.json", "route_graph"), ("selfcheck.json", "selfcheck"),
             ("edit_log.json", "change_log"), ("edit_element_map.json", "element_map"),
             ("edit_selfcheck.json", "selfcheck"),
             ("extraction_report.json", "extraction"),
             ("exports.json", "exports_meta"), ("geometry.json", "geometry"),
             ("source_figure.svg", "input_svg")]
    deliverables = [_file_record(a.out, rel, role) for rel, role in roles
                    if os.path.exists(os.path.join(a.out, rel))]
    missing = [d["path"] for d in deliverables if not d.get("exists")]

    def val(name):
        return draft.get(name)

    limits_value = draft.get("limits") or []
    if isinstance(limits_value, list):
        limits_value = " | ".join(str(x) for x in limits_value)
    values = {
        "case_id": cid, "status": status,
        "source_file": draft.get("source_file") or ("route.svg"
                                                     if os.path.exists(os.path.join(a.out, "route.svg"))
                                                     else ""),
        "exports": draft.get("exports") or [],
        "preview": draft.get("preview") or {"status": "unavailable", "notes": []},
        "extraction": draft.get("extraction") or {},
        "element_map": draft.get("element_map") or [],
        "parts": draft.get("parts") or [],
        "connections": draft.get("connections") or [],
        "stages": draft.get("stages") or [],
        "route_graph": draft.get("route_graph"),
        "legend": draft.get("legend") or [],
        "units": draft.get("units") or {},
        "scale_bar": draft.get("scale_bar") or {},
        "figure_png": "route.png" if os.path.exists(os.path.join(a.out, "route.png")) else None,
        "figure_pdf": "route.pdf" if os.path.exists(os.path.join(a.out, "route.pdf")) else None,
        "caption": draft.get("caption"),
        "selfcheck": draft.get("selfcheck"),
        "deliverables": deliverables,
        "sources": draft.get("sources") or [],
        "limits": limits_value,
        "uncertainty": draft.get("uncertainty") or [],
        "change_log": draft.get("change_log") or "initial generation; no manual edits",
        "metrics": draft.get("metrics") or {},
        "title": draft.get("title") or "",
        "element_map_file": "element_map.json"
        if os.path.exists(os.path.join(a.out, "element_map.json")) else None,
        "caption_file": "caption.md"
        if os.path.exists(os.path.join(a.out, "caption.md")) else None,
        "change_details": draft.get("change_details") or {},
        "input_files": draft.get("input_files") or [],
        "code_path": draft.get("code_path") or "scripts/run_case.py",
        "fatal_error": draft.get("fatal_error"),
    }
    values["success"] = status == "ok"

    if missing and status == "ok":
        status = "partial"
        values["status"] = status
        values["success"] = False
        values["uncertainty"].append("declared deliverables missing: %s"
                                     % ", ".join(missing))

    result = {}
    unmapped = []
    for field in contract:
        target = canonical(field)
        if target and target in values:
            result[field] = values[target]
        else:
            result[field] = None
            unmapped.append(field)
    for core in CORE_ALWAYS:
        if core not in result:
            result[core] = values.get(core)
    for extra in EXTRA_KEYS:
        if extra not in result and extra in values:
            result[extra] = values[extra]
    result["case_id"] = cid
    result["status"] = status
    result["success"] = status == "ok"
    result["contract_fields"] = contract
    result["unmapped_contract_fields"] = unmapped
    # never leave core fields as an empty object/string when the data exists
    if not result.get("element_map"):
        result["element_map"] = values.get("element_map") or []
    if not result.get("caption"):
        result["caption"] = values.get("caption") or ""
    if unmapped:
        if isinstance(result.get("uncertainty"), list):
            result["uncertainty"].append(
                "contract fields without a canonical producer emitted as null: %s"
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
        verdict = str(sc.get("verdict", "PASS" if sc.get("ok") else "FAIL")).upper()
    if res.get("status") == "ok" and verdict == "FAIL":
        problems.append("status=ok but selfcheck verdict=FAIL")
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
