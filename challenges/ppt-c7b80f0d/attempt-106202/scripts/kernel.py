#!/usr/bin/env python3
"""kernel.py - evidence-first execution kernel shared by all Bohrium skills.

Subcommands (all stdlib only, no network):
  init     read /input/case.json (alias tolerant), emit work/contract.json + work/case.json
  index    walk material dir, extract text with locators, emit work/evidence.json
  verify   check a draft against the evidence index (numbers, units, citations, claims)
  emit     merge draft fields + contract into result.json, write md artifacts, run selfcheck
  check    validate an existing output dir against its contract

Design rule: never fabricate. Missing data is reported as missing, never filled in.
"""
import argparse
import csv
import json
import os
import re
import sys
import zipfile

ALIASES = {
    "source_text": ["source_text", "text", "input_text", "manuscript", "content", "document", "paper_text"],
    "case_id": ["case_id", "id", "caseId", "task_id"],
    "task": ["task", "instruction", "question", "prompt", "request"],
    "materials": ["materials", "files", "attachments", "inputs", "resources", "documents"],
    "output_contract": ["output_contract", "outputContract", "expected_output", "schema"],
    "audience": ["audience", "readers", "target_audience"],
    "language": ["target_language", "language", "lang"],
    "genre": ["genre", "document_type", "doc_type", "style", "register"],
}

TEXT_EXT = {".txt", ".md", ".csv", ".tsv", ".json", ".tex", ".bib", ".yaml", ".yml", ".rst", ".html", ".xml"}
NUM_RE = re.compile(r"(?<![A-Za-z0-9_])[-+]?\d+(?:[.,]\d+)*(?:\s?[%‰])?")
CITE_RE = re.compile(r"(\[[0-9,\s\-–]+\]|\\cite\{[^}]+\}|\([A-Z][A-Za-z\-]+(?:\s(?:et al\.|and\s[A-Z][A-Za-z\-]+))?,?\s?(?:19|20)\d{2}[a-z]?\))")


def load_json(path):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def dump(obj, path):
    os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(obj, fh, ensure_ascii=False, indent=1)


def pick(case, key):
    for name in ALIASES.get(key, [key]):
        if name in case and case[name] not in (None, "", [], {}):
            return case[name]
    return None


def contract_field_names(contract):
    """Return ordered field names for dict / list[str] / list[{name,...}] contracts.

    The platform's case.json may declare output_contract as an object, a string
    array, or an array of field-spec objects. All three must map to names without
    raising, otherwise emit writes no result.json.
    """
    if isinstance(contract, dict):
        if "properties" in contract or contract.get("type") == "object":
            return list(contract.get("required", []))
        inner = contract.get("fields")
        if isinstance(inner, (list, dict)):
            return contract_field_names(inner)
        return [str(k) for k in contract.keys()]
    if isinstance(contract, list):
        names = []
        for item in contract:
            if isinstance(item, str) and item.strip():
                names.append(item.strip())
            elif isinstance(item, dict):
                name = item.get("name") or item.get("field") or item.get("key") or item.get("id")
                if name:
                    names.append(str(name))
        return list(dict.fromkeys(names))
    return []


def find_case_file(explicit=None):
    cands = [explicit] if explicit else []
    cands += ["/input/case.json", "case.json", "/app/input/case.json", "./input/case.json"]
    for c in cands:
        if c and os.path.exists(c):
            return c
    return None


# ---------------------------------------------------------------- extraction
def strip_xml(raw):
    raw = re.sub(r"<w:p[ >]", "\n<w:p ", raw)
    raw = re.sub(r"<[^>]+>", "", raw)
    return re.sub(r"\n{3,}", "\n\n", raw)


def read_docx(path):
    out = []
    with zipfile.ZipFile(path) as z:
        names = [n for n in z.namelist() if n.startswith("word/") and n.endswith(".xml")]
        for n in sorted(names):
            if "document" in n:
                out.append(strip_xml(z.read(n).decode("utf-8", "replace")))
    return "\n".join(out)


def read_xlsx(path):
    try:
        with zipfile.ZipFile(path) as z:
            shared = []
            if "xl/sharedStrings.xml" in z.namelist():
                s = z.read("xl/sharedStrings.xml").decode("utf-8", "replace")
                shared = [re.sub(r"<[^>]+>", "", m) for m in re.findall(r"<si>(.*?)</si>", s, re.S)]
            rows = []
            for n in sorted(x for x in z.namelist() if re.match(r"xl/worksheets/sheet\d+\.xml$", x)):
                x = z.read(n).decode("utf-8", "replace")
                for r in re.findall(r"<row[^>]*>(.*?)</row>", x, re.S):
                    cells = []
                    for c in re.findall(r"<c([^>]*)>(.*?)</c>", r, re.S):
                        attrs, body = c
                        v = re.search(r"<v>(.*?)</v>", body, re.S)
                        t = re.search(r't="([^"]+)"', attrs)
                        if v is None:
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
        return "\n".join((p.extract_text() or "") for p in PdfReader(path).pages)
    except Exception:  # noqa: BLE001
        return "[pdf text layer unavailable: install pdftotext or pypdf; do not guess page content]"


def extract(path):
    ext = os.path.splitext(path)[1].lower()
    if ext == ".docx":
        return read_docx(path)
    if ext in {".xlsx", ".xlsm"}:
        return read_xlsx(path)
    if ext == ".pdf":
        return read_pdf(path)
    if ext in TEXT_EXT:
        return open(path, encoding="utf-8", errors="replace").read()
    if ext in {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".svg"}:
        return "[image asset: inspect visually; record尺寸/内容 in evidence notes]"
    return "[unsupported type %s]" % ext


def locate(snippet, corpus, source):
    """Return a human-checkable locator: line number(s) + char offset."""
    idx = corpus.find(snippet[:80])
    if idx < 0:
        return None
    line = corpus.count("\n", 0, idx) + 1
    return {"source": source, "line": line, "offset": idx}


# ---------------------------------------------------------------- commands
def cmd_init(a):
    case_path = find_case_file(a.case)
    if not case_path:
        dump({"status": "blocked", "missing": "case.json not found"}, os.path.join(a.out, "contract.json"))
        print("blocked: case.json not found")
        return 1
    try:
        case = load_json(case_path)
    except (ValueError, UnicodeDecodeError) as exc:
        dump({"status": "blocked", "case_path": os.path.abspath(case_path),
              "missing": "case.json unreadable: %s" % exc},
             os.path.join(a.out, "contract.json"))
        print("blocked: case.json is not valid JSON:", exc)
        return 1
    if not isinstance(case, dict):
        dump({"status": "blocked", "case_path": os.path.abspath(case_path),
              "missing": "case.json is not a JSON object"},
             os.path.join(a.out, "contract.json"))
        print("blocked: case.json is not a JSON object")
        return 1
    norm = {k: pick(case, k) for k in ALIASES}
    contract = norm.get("output_contract") or {}
    if isinstance(contract, list):
        contract = {"fields": contract}
    result = {
        "case_path": os.path.abspath(case_path),
        "case_id": norm.get("case_id") or os.path.splitext(os.path.basename(case_path))[0],
        "task": norm.get("task"),
        "language": norm.get("language"),
        "genre": norm.get("genre"),
        "audience": norm.get("audience"),
        "raw_keys": sorted(case.keys()),
        "contract_source": "case.output_contract" if norm.get("output_contract") else "skill_default",
        "contract": contract,
    }
    dump(result, os.path.join(a.out, "contract.json"))
    dump(case, os.path.join(a.out, "case.raw.json"))
    if not contract:
        print("warn: case.json has no output_contract; using skill default contract")
    print("case_id=%s keys=%s" % (result["case_id"], ",".join(result["raw_keys"])))
    return 0


def cmd_index(a):
    roots = [p for p in a.materials if os.path.exists(p)]
    items, corpus = [], []
    for root in roots:
        walk = [(root, [], [os.path.basename(root)])] if os.path.isfile(root) else os.walk(root)
        for dirpath, _, names in walk:
            for n in sorted(names):
                p = dirpath if dirpath == root and not os.path.isdir(root) else os.path.join(dirpath, n)
                if not os.path.isfile(p) or n.startswith("."):
                    continue
                text = extract(p)
                items.append({
                    "path": p,
                    "bytes": os.path.getsize(p),
                    "chars": len(text),
                    "readable": not text.startswith("["),
                    "sha1": __import__("hashlib").sha1(open(p, "rb").read()).hexdigest(),
                })
                corpus.append("===== FILE: %s =====\n%s" % (p, text))
    dump({"files": items, "total_chars": sum(i["chars"] for i in items),
          "unreadable": [i["path"] for i in items if not i["readable"]]},
         os.path.join(a.out, "evidence.json"))
    os.makedirs(a.out, exist_ok=True)
    with open(os.path.join(a.out, "corpus.txt"), "w", encoding="utf-8") as fh:
        fh.write("\n\n".join(corpus))
    for i in items:
        print("%-8s %8d  %s" % ("ok" if i["readable"] else "UNREAD", i["chars"], i["path"]))
    return 0


def cmd_verify(a):
    corpus = open(os.path.join(a.evidence_dir, "corpus.txt"), encoding="utf-8").read()
    ev = load_json(os.path.join(a.evidence_dir, "evidence.json"))
    draft = open(a.text, encoding="utf-8").read()
    numbers = []
    for m in NUM_RE.finditer(draft):
        tok = m.group(0).strip()
        if len(tok) < 2 and not tok.isdigit():
            continue
        numbers.append(tok)
    unsupported = [n for n in dict.fromkeys(numbers) if n not in corpus]
    cites = list(dict.fromkeys(CITE_RE.findall(draft)))
    missing_cites = [c for c in cites if c.strip("[]") not in corpus and c.strip("\\cite{}") not in corpus]
    report = {
        "draft": os.path.abspath(a.text),
        "numbers_total": len(numbers),
        "numbers_unique": len(set(numbers)),
        "unsupported_numbers": unsupported[:200],
        "citations_unique": len(cites),
        "citations_not_in_sources": missing_cites[:200],
        "unreadable_sources": ev.get("unreadable", []),
        "verdict": "pass" if not unsupported and not missing_cites else "review",
    }
    dump(report, os.path.join(a.out, "claims.json"))
    print("verdict=%s unsupported_numbers=%d citations_not_in_sources=%d"
          % (report["verdict"], len(unsupported), len(missing_cites)))
    for n in unsupported[:20]:
        print("  ? number not in sources:", n)
    return 0


def schema_problems(value, schema, path="$"):
    if not isinstance(schema, dict): return []
    types = {"string": str, "number": (int, float), "integer": int, "boolean": bool, "object": dict, "array": list, "null": type(None)}
    kind, errors = schema.get("type"), []
    if kind is not None:
        if kind not in types: return [path + ": unsupported schema type"]
        if not isinstance(value, types[kind]) or (kind in ("number", "integer") and isinstance(value, bool)): return [path + ": expected " + kind]
    if "enum" in schema and value not in schema["enum"]: errors.append(path + ": invalid enum")
    if isinstance(value, dict):
        for k in schema.get("required", []):
            if k not in value or value[k] is None: errors.append(path + "." + k + ": required")
        for k, sub in schema.get("properties", {}).items():
            if k in value and value[k] is not None: errors.extend(schema_problems(value[k], sub, path + "." + k))
    if isinstance(value, list) and isinstance(schema.get("items"), dict):
        for i, item in enumerate(value): errors.extend(schema_problems(item, schema["items"], path + "[" + str(i) + "]"))
    return errors


def contract_validation(result, contract):
    if isinstance(contract, dict) and "fields" in contract:
        contract = contract["fields"]
    if isinstance(contract, list):
        contract = {"type":"object", "properties":{x.get("name"):x for x in contract if isinstance(x,dict) and x.get("name")}}
    if isinstance(contract, dict) and ("properties" in contract or contract.get("type") == "object"):
        return schema_problems(result, contract)
    return []

def cmd_emit(a):
    cpath = os.path.join(a.contract_dir, "contract.json") if os.path.isdir(a.contract_dir) \
        else a.contract_dir
    contract = (load_json(cpath) or {}) if os.path.exists(cpath) else {}
    draft = load_json(a.draft) or {}
    if isinstance(contract, dict):
        fields = contract.get("contract")
        if fields is None:
            fields = contract.get("output_contract", contract)
    else:
        fields = contract
    names = contract_field_names(fields)
    draft_fields = draft.get("fields") if isinstance(draft.get("fields"), dict) else {}
    case_id = (contract.get("case_id") if isinstance(contract, dict) else None) or draft.get("case_id")
    result = {"case_id": case_id, "status": draft.get("status", "partial")}
    for name in names:
        result[name] = draft_fields.get(name, draft.get(name))
    for name, value in draft_fields.items():
        result.setdefault(name, value)
    result.setdefault("uncertainty", list(draft.get("uncertainty") or []))
    if not os.path.exists(cpath):
        result["uncertainty"].append("契约文件 %s 缺失，result.json 仅含草案字段" % cpath)
    result.setdefault("sources", draft.get("sources", []))
    result.setdefault("changes", draft.get("changes", []))
    result["limits"] = draft.get("limits", "")
    # Validate every destination before writing anything. Refuse paths that escape,
    # symlinks, duplicates, and any attempt to overwrite inputs.
    from pathlib import Path
    out = Path(a.out).absolute()
    if any(c.is_symlink() for c in [out, *out.parents]):
        raise ValueError("symlink output directory refused")
    targets = []
    for name, body in [("result.json", None)] + list((draft.get("artifacts") or {}).items()):
        rel = Path(name)
        if rel.is_absolute() or not rel.parts or any(x in ("..", ".") for x in rel.parts):
            raise ValueError("invalid artifact path")
        target = out / rel
        if not target.resolve().is_relative_to(out.resolve()):
            raise ValueError("artifact escapes output")
        for component in [target, *target.parents]:
            if component.is_symlink(): raise ValueError("symlink artifact path refused")
            if component == out: break
        targets.append((target, body))
    if len({str(p) for p, _ in targets}) != len(targets):
        raise ValueError("duplicate artifact path")
    protected = {Path(a.draft).resolve(), Path(cpath).resolve()}
    if contract.get("case_path"): protected.add(Path(contract["case_path"]).resolve())
    if any(p.resolve() in protected for p, _ in targets):
        raise ValueError("output would overwrite input")
    os.makedirs(out, exist_ok=True)
    dump(result, str(out / "result.json"))
    for target, body in targets[1:]:
        target.parent.mkdir(parents=True, exist_ok=True)
        with open(target, "w", encoding="utf-8") as fh:
            fh.write(body)
    missing = [k for k in names if result.get(k) is None]
    invalid = contract_validation(result, fields)
    if missing or invalid:
        result["status"] = "partial"
        result["limits"] = "; ".join(x for x in (str(result.get("limits") or ""), "missing/invalid contract: " + ", ".join(missing + invalid)) if x)
        dump(result, str(out / "result.json"))
    print("result.json written; contract_fields=%d missing=%s invalid=%s" % (len(names), missing or "none", invalid or "none"))
    return 2 if missing or invalid else 0


def cmd_check(a):
    problems = []
    rp = os.path.join(a.out, "result.json")
    if not os.path.exists(rp):
        problems.append("result.json missing")
    else:
        res = load_json(rp)
        for k in ("case_id", "status"):
            if not res.get(k):
                problems.append("result.json missing %s" % k)
        if res.get("status") not in {"ok", "success", "partial", "blocked", "refused"}:
            problems.append("status must be one of ok/success/partial/blocked/refused")
    print("PASS" if not problems else "FAIL")
    for p in problems:
        print(" -", p)
    return 0 if not problems else 1


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("init"); p.add_argument("--case"); p.add_argument("--out", default="work"); p.set_defaults(fn=cmd_init)
    p = sub.add_parser("index"); p.add_argument("--materials", nargs="+", required=True); p.add_argument("--out", default="work"); p.set_defaults(fn=cmd_index)
    p = sub.add_parser("verify"); p.add_argument("--text", required=True); p.add_argument("--evidence-dir", default="work"); p.add_argument("--out", default="work"); p.set_defaults(fn=cmd_verify)
    p = sub.add_parser("emit"); p.add_argument("--draft", required=True); p.add_argument("--contract-dir", default="work"); p.add_argument("--out", default="/app/output"); p.set_defaults(fn=cmd_emit)
    p = sub.add_parser("check"); p.add_argument("--out", default="/app/output"); p.set_defaults(fn=cmd_check)

    a = ap.parse_args()
    return a.fn(a)


if __name__ == "__main__":
    sys.exit(main())
