#!/usr/bin/env python3
"""kernel.py - runtime contract guard and material text reader (stdlib only).

The evaluator's case.json may spell output_contract as an object, an array of names,
an array of {name/key/field}, a nested schema or a comma string, and the file may be
malformed. This module never crashes on any of that:

  init   read case.json (alias tolerant), extract every contract field, record materials,
         task text and case hash, write work/case.json. Malformed input -> blocked flag.
  check  fail only on a dishonest result: missing case_id/status, status=ok with a failed
         selfcheck or missing declared deliverables, empty caption/element_map.

Text readers cover txt/md/csv/tsv/json/xlsx/docx/pdf; images are reported as visual
assets, never guessed. No network.

Usage:
  python3 scripts/kernel.py init  --case /input/case.json --materials /input --work /app/work
  python3 scripts/kernel.py check --result /app/output/result.json --work /app/work
"""
import argparse
import hashlib
import json
import os
import re
import sys
import zipfile

DEFAULT_CONTRACT = [
    "case_id", "status", "source_file", "exports", "element_map", "caption",
    "selfcheck", "limits", "uncertainty", "sources", "change_log", "deliverables",
    "metrics",
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
                 "attachments", "data", "data_files", "input_files", "artifacts",
                 "source_svg", "svg_path", "figure_svg", "input")
ALLOWED_STATUS = ("ok", "partial", "blocked", "failed", "refused")

ALIASES = {
    "caseid": "case_id", "id": "case_id", "taskid": "case_id",
    "status": "status", "state": "status", "success": "status",
    "sourcesvg": "source_file", "editablefile": "source_file", "svg": "source_file",
    "figure": "source_file", "source": "source_file", "editable": "source_file",
    "figuresvg": "source_file", "diagram": "source_file",
    "figurepng": "figure_png", "png": "figure_png",
    "figurepdf": "figure_pdf", "pdf": "figure_pdf",
    "exports": "exports", "deliverables": "deliverables", "artifacts": "deliverables",
    "outputfiles": "deliverables",
    "elementmap": "element_map", "sourcemap": "element_map", "provenance": "element_map",
    "mapping": "element_map", "sourcetrace": "element_map", "trace": "element_map",
    "caption": "caption", "figurecaption": "caption",
    "selfcheck": "selfcheck", "check": "selfcheck", "validation": "selfcheck",
    "checks": "selfcheck", "qa": "selfcheck",
    "limits": "limits", "limitations": "limits", "caveats": "limits",
    "uncertainty": "uncertainty", "uncertainties": "uncertainty", "risks": "uncertainty",
    "changelog": "change_log", "changes": "change_log", "editlog": "change_log",
    "revision": "change_log", "diff": "change_log",
    "sources": "sources", "sourcefiles": "sources",
    "metrics": "metrics", "statistics": "metrics", "stats": "metrics",
    "mechanismgraph": "mechanism_graph", "graph": "mechanism_graph",
    "nodes": "nodes", "entities": "nodes", "entitieslist": "nodes",
    "edges": "edges", "relations": "edges", "interactions": "edges",
    "compartments": "compartments", "zones": "compartments", "layers": "compartments",
    "isolatedentities": "isolated_entities", "conflicts": "conflicts",
    "unresolvededges": "unresolved_edges", "code": "code_path", "script": "code_path",
    # documented contract fields that must not be swallowed by substring matching
    "missingrelations": "missing_relations",
    "edgeendpointerrors": "edge_endpoint_errors",
    "tokeninventory": "token_inventory", "tokenrecall": "token_recall",
    "bindingannotations": "binding_annotations",
    "elementmapcounts": "element_map_counts", "inputfiles": "input_files",
    "blockedreason": "blocked_reason",
    "unmappedcontractfields": "unmapped_contract_fields",
}


def sha256_file(path):
    h = hashlib.sha256()
    try:
        with open(path, "rb") as fh:
            for chunk in iter(lambda: fh.read(1 << 20), b""):
                h.update(chunk)
    except OSError:
        return ""
    return h.hexdigest()


def sha256_text(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def norm(name):
    return re.sub(r"[^0-9a-z]", "", str(name).lower())


def canonical(name):
    n = norm(name)
    if n in ALIASES:
        return ALIASES[n]
    # Error/missing diagnostics are their own fields; never map them onto `edges`
    # just because the name contains "relation"/"edge".
    if any(k in n for k in ("missing", "error", "fail", "unmapped")):
        return ""
    checks = [
        (("caseid",), "case_id"), (("status", "state"), "status"),
        (("sourcefile", "figuresvg", "editablesource", "diagram", "svg"), "source_file"),
        (("figurepng",), "figure_png"), (("figurepdf",), "figure_pdf"),
        (("deliverable", "artifact", "outputfile"), "deliverables"),
        (("elementmap", "provenance", "sourcetrace", "mapping"), "element_map"),
        (("caption",), "caption"),
        (("selfcheck", "validation"), "selfcheck"),
        (("limit", "caveat"), "limits"), (("uncertain", "risk"), "uncertainty"),
        (("change", "editlog", "diff"), "change_log"),
        (("source",), "sources"), (("metric", "stat"), "metrics"),
        (("mechanism", "graph"), "mechanism_graph"), (("node", "entit"), "nodes"),
        (("edge", "relation", "interaction"), "edges"),
        (("compartment", "zone", "layer"), "compartments"),
        (("export",), "exports"), (("code", "script"), "code_path"),
        (("isolated",), "isolated_entities"), (("conflict",), "conflicts"),
        (("unresolved",), "unresolved_edges"),
    ]
    for keys, target in checks:
        if any(k in n for k in keys):
            return target
    return ""


# ------------------------------------------------------------------ text readers
def strip_xml(raw):
    raw = re.sub(r"<w:p[ >]", "\n<w:p ", raw)
    raw = re.sub(r"<w:tab[^>]*/>", "\t", raw)
    raw = re.sub(r"<[^>]+>", "", raw)
    return re.sub(r"\n{3,}", "\n\n", raw)


def read_docx(path):
    try:
        with zipfile.ZipFile(path) as z:
            parts = []
            for name in sorted(z.namelist()):
                if name.startswith("word/") and name.endswith(".xml") and "document" in name:
                    parts.append(strip_xml(z.read(name).decode("utf-8", "replace")))
            return "\n".join(parts)
    except Exception as exc:  # noqa: BLE001
        return "[docx unreadable: %s]" % exc


def read_xlsx(path):
    try:
        with zipfile.ZipFile(path) as z:
            shared = []
            if "xl/sharedStrings.xml" in z.namelist():
                s = z.read("xl/sharedStrings.xml").decode("utf-8", "replace")
                shared = [re.sub(r"<[^>]+>", "", m) for m in re.findall(r"<si>(.*?)</si>", s, re.S)]
            rows = []
            for name in sorted(x for x in z.namelist()
                               if re.match(r"xl/worksheets/sheet\d+\.xml$", x)):
                x = z.read(name).decode("utf-8", "replace")
                for r in re.findall(r"<row[^>]*>(.*?)</row>", x, re.S):
                    cells = []
                    for c in re.findall(r"<c([^>]*)>(.*?)</c>", r, re.S):
                        attrs, body = c
                        inline = re.search(r"<is>.*?<t[^>]*>(.*?)</t>", body, re.S)
                        v = re.search(r"<v>(.*?)</v>", body, re.S)
                        t = re.search(r't="([^"]+)"', attrs)
                        if inline is not None:
                            cells.append(inline.group(1))
                        elif v is None:
                            cells.append("")
                        elif t and t.group(1) == "s":
                            idx = int(v.group(1))
                            cells.append(shared[idx] if idx < len(shared) else "")
                        else:
                            cells.append(v.group(1))
                    rows.append("\t".join(cells))
            return "\n".join(rows)
    except Exception as exc:  # noqa: BLE001
        return "[xlsx unreadable: %s]" % exc


def read_pdf(path):
    try:
        import subprocess
        r = subprocess.run(["pdftotext", "-layout", path, "-"], capture_output=True, timeout=60)
        if r.returncode == 0 and r.stdout.strip():
            return r.stdout.decode("utf-8", "replace")
    except Exception:  # noqa: BLE001
        pass
    try:
        from pypdf import PdfReader  # type: ignore
        pages = []
        for i, page in enumerate(PdfReader(path).pages, 1):
            pages.append("[[page %d]]\n%s" % (i, page.extract_text() or ""))
        return "\n".join(pages)
    except Exception:  # noqa: BLE001
        try:
            import PyPDF2  # type: ignore
            return "\n".join((p.extract_text() or "") for p in PyPDF2.PdfReader(path).pages)
        except Exception:  # noqa: BLE001
            return ("[pdf text layer unavailable: install pdftotext or pypdf; "
                    "do not guess page content]")


TEXT_EXT = {".txt", ".md", ".markdown", ".csv", ".tsv", ".json", ".tex", ".bib",
            ".yaml", ".yml", ".rst", ".html", ".xml"}
IMAGE_EXT = {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".svg", ".gif", ".webp"}


def extract_text(path):
    ext = os.path.splitext(path)[1].lower()
    if ext == ".docx":
        return read_docx(path)
    if ext in {".xlsx", ".xlsm", ".xls"}:
        return read_xlsx(path)
    if ext == ".pdf":
        return read_pdf(path)
    if ext in TEXT_EXT:
        try:
            return open(path, encoding="utf-8", errors="replace").read()
        except OSError as exc:
            return "[unreadable: %s]" % exc
    if ext in IMAGE_EXT:
        return "[image asset: inspect visually; record dimensions/content in notes]"
    return "[unsupported type %s]" % ext


# ------------------------------------------------------------------ case parsing
def read_case(path):
    info = {"blocked": "", "case": {}, "raw_text": "", "sha256": "", "path": path,
            "error": "", "valid_json": False}
    if not path or not os.path.exists(path):
        info["blocked"] = "case.json not found at %s" % path
        return info
    try:
        info["raw_text"] = open(path, encoding="utf-8", errors="replace").read()
        info["sha256"] = sha256_text(info["raw_text"])
        case = json.loads(info["raw_text"])
        info["valid_json"] = True
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
    return out, (type(raw).__name__ if raw is not None else "missing")


def collect_materials(case, base):
    items = []

    def push(v, origin):
        if isinstance(v, str):
            items.append({"path": v if os.path.isabs(v) else os.path.join(base, v),
                          "value": v, "origin": origin})
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
    return "\n\n".join(parts)[:40000]


def cmd_init(a):
    os.makedirs(a.work, exist_ok=True)
    info = read_case(a.case)
    case = info["case"]
    fields, raw_type = extract_contract(case)
    if getattr(a, "contract", ""):
        fields = [x.strip() for x in a.contract.split(",") if x.strip()]
        raw_type = "cli"
    if not fields:
        fields = list(DEFAULT_CONTRACT)
        raw_type = "default"
    cid = case_id_of(case, info["sha256"] or info["path"] or "")
    task_text = task_text_of(case)
    task_md = os.path.join(a.materials, "task.md")
    if os.path.isfile(task_md):
        try:
            extra = open(task_md, encoding="utf-8", errors="replace").read()
            if extra.strip() and extra.strip() not in task_text:
                task_text = (task_text + "\n\n" + extra.strip()).strip()
        except OSError:
            pass
    materials = collect_materials(case, a.materials)
    if not materials and os.path.isdir(a.materials):
        for name in sorted(os.listdir(a.materials)):
            p = os.path.join(a.materials, name)
            if os.path.isfile(p) and name not in ("case.json",):
                materials.append({"path": p, "value": name, "origin": "scan"})
    payload = {
        "case_id": cid,
        "case_path": os.path.abspath(a.case) if a.case else "",
        "case_sha256": info["sha256"],
        "contract_fields": fields,
        "contract_raw_type": raw_type,
        "materials": materials,
        "task_text": task_text_of(case),
        "blocked": info["blocked"],
        "error": info["error"],
        "valid_json": info["valid_json"],
        "case_keys": sorted(case.keys()) if isinstance(case, dict) else [],
        "mode": case.get("mode", "") if isinstance(case, dict) else "",
    }
    with open(os.path.join(a.work, "case.json"), "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=1)
    if payload["task_text"]:
        with open(os.path.join(a.work, "task.md"), "w", encoding="utf-8") as fh:
            fh.write(payload["task_text"])
    print("init: case_id=%s contract=%d fields (%s) materials=%d blocked=%r"
          % (cid, len(fields), raw_type, len(materials), payload["blocked"]))
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
    if res.get("status") == "ok":
        for d in res.get("deliverables") or []:
            if not d.get("exists", True) or not d.get("bytes"):
                problems.append("status=ok but deliverable missing/empty: %s" % d.get("path"))
        for key in ("source_file", "exports"):
            if not res.get(key):
                problems.append("status=ok but %s is empty" % key)
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
    sub = ap.add_subparsers(dest="cmd", required=True)
    p1 = sub.add_parser("init")
    p1.add_argument("--case", default="/input/case.json")
    p1.add_argument("--materials", default="/input")
    p1.add_argument("--work", default="/app/work")
    p1.add_argument("--contract", default="")
    p1.set_defaults(func=cmd_init)
    p2 = sub.add_parser("check")
    p2.add_argument("--result", default="/app/output/result.json")
    p2.add_argument("--work", default="/app/work")
    p2.set_defaults(func=cmd_check)
    a = ap.parse_args()
    return a.func(a)


if __name__ == "__main__":
    sys.exit(main())
