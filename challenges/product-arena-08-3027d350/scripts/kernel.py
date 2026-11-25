#!/usr/bin/env python3
"""kernel.py - evidence-first execution kernel for the paper structure parser.

Subcommands (stdlib only, no network):
  init     read case.json (alias tolerant), emit work/contract.json + work/case.raw.json
  index    walk material dirs, extract text with locators, emit work/evidence.json + corpus.txt
  verify   check a draft text against the evidence corpus (whole-token numbers, citations)
  emit     merge draft fields + contract into result.json, write artifacts, report missing fields
  check    validate an existing output dir against its contract and locator table

Exit codes: 0 ok, 1 review/blocked (details on stdout), 2 bad invocation/input.
Design rule: never fabricate. Missing data is reported as missing, never filled in.
"""
import argparse
import hashlib
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
IMAGE_EXT = {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".svg"}
NUMTOK = re.compile(r"\d+(?:[.,]\d+)*")
THOUSANDS = re.compile(r"^\d{1,3}(?:,\d{3})+(?:\.\d+)?$")
CITE_RE = re.compile(r"(\[[0-9,\s\-–]+\]|\\cite\{[^}]+\}|\([A-Z][A-Za-z\-]+(?:\s(?:et al\.|and\s[A-Z][A-Za-z\-]+))?,?\s?(?:19|20)\d{2}[a-z]?\))")
NUM_RE = re.compile(r"(?<![\w.])[-+]?\d+(?:[.,]\d+)*(?![\w])")


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
            return "\n".join(rows), ""
    except Exception as exc:  # noqa: BLE001
        return "", "xlsx_unreadable: %s" % exc


def read_pdf(path):
    """Return (text, reason). Empty text means no usable text layer."""
    note = []
    try:
        import subprocess
        r = subprocess.run(["pdftotext", "-layout", path, "-"], capture_output=True, timeout=60)
        if r.returncode == 0 and r.stdout.strip():
            return r.stdout.decode("utf-8", "replace"), ""
        note.append("pdftotext_empty" if r.returncode == 0 else "pdftotext_rc%d" % r.returncode)
    except FileNotFoundError:
        note.append("pdftotext_missing")
    except Exception as exc:  # noqa: BLE001
        note.append("pdftotext_error:%s" % exc)
    try:
        from pypdf import PdfReader  # type: ignore
        text = "\n".join((p.extract_text() or "") for p in PdfReader(path).pages)
        if text.strip():
            return text, ""
        note.append("pypdf_empty")
    except Exception as exc:  # noqa: BLE001
        note.append("pypdf_error:%s" % exc)
    return "", "no_text_layer(%s)" % ",".join(note)


def read_text(path):
    raw = open(path, "rb").read()
    for enc in ("utf-8-sig", "utf-8", "gb18030"):
        try:
            return raw.decode(enc), enc
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", "replace"), "utf-8/replace"


def extract(path):
    """Return (text, ok, reason, encoding). Never returns a fake placeholder as text."""
    ext = os.path.splitext(path)[1].lower()
    if ext == ".docx":
        try:
            text = read_docx(path)
        except Exception as exc:  # noqa: BLE001
            return "", False, "docx_unreadable: %s" % exc, ""
        return (text, True, "", "utf-8") if text.strip() else ("", False, "docx_no_text", "")
    if ext in {".xlsx", ".xlsm"}:
        text, reason = read_xlsx(path)
        return (text, True, "", "utf-8") if text.strip() else ("", False, reason or "xlsx_no_text", "")
    if ext == ".pdf":
        text, reason = read_pdf(path)
        return text, bool(text.strip()), reason, "utf-8"
    if ext in TEXT_EXT:
        text, enc = read_text(path)
        reason = "replacement_chars" if "\ufffd" in text else ""
        return text, bool(text.strip()), reason, enc
    if ext in IMAGE_EXT:
        return "", False, "image_asset_not_indexed", ""
    return "", False, "unsupported_type:%s" % (ext or "none"), ""


def sha1_of(path):
    return hashlib.sha1(open(path, "rb").read()).hexdigest()


def resolve_material(p, a):
    """Resolve a material path that may be relative to the case file (harness gives /input/case.json)."""
    cands = [p]
    if not os.path.isabs(p):
        if getattr(a, "case", None):
            cands.append(os.path.join(os.path.dirname(os.path.abspath(a.case)), p))
        cp = os.path.join(a.out, "contract.json")
        if os.path.exists(cp):
            try:
                base = os.path.dirname(load_json(cp).get("case_path") or "")
                if base:
                    cands.append(os.path.join(base, p))
            except Exception:  # noqa: BLE001
                pass
        cands.append(os.path.join("/input", p))
    for c in cands:
        if c and os.path.exists(c):
            return c
    return None


# ---------------------------------------------------------------- commands
def cmd_init(a):
    case_path = find_case_file(a.case)
    if not case_path:
        dump({"status": "blocked", "error": "case.json not found", "searched": [a.case] if a.case else []},
             os.path.join(a.out, "contract.json"))
        print("BLOCKED: case.json not found (pass --case or place /input/case.json)")
        return 1
    try:
        case = load_json(case_path)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        dump({"status": "blocked", "error": "case.json is not valid JSON: %s" % exc,
              "case_path": os.path.abspath(case_path)}, os.path.join(a.out, "contract.json"))
        print("BLOCKED: case.json is not valid JSON: %s" % exc)
        return 1
    if not isinstance(case, dict):
        dump({"status": "blocked", "error": "case.json top level must be an object, got %s" % type(case).__name__,
              "case_path": os.path.abspath(case_path)}, os.path.join(a.out, "contract.json"))
        print("BLOCKED: case.json top level must be an object, got %s" % type(case).__name__)
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
        "materials": norm.get("materials") or [],
        "raw_keys": sorted(case.keys()),
        "contract_source": "case.output_contract" if norm.get("output_contract") else "skill_default",
        "contract": contract,
    }
    dump(result, os.path.join(a.out, "contract.json"))
    dump(case, os.path.join(a.out, "case.raw.json"))
    if not contract:
        print("warn: case.json has no output_contract; using skill default contract")
    print("case_id=%s keys=%s materials=%s"
          % (result["case_id"], ",".join(result["raw_keys"]), result["materials"] or "none"))
    return 0


def cmd_index(a):
    missing, items, corpus, unreadable = [], [], [], []
    for raw in a.materials:
        resolved = resolve_material(raw, a)
        if not resolved:
            missing.append(raw)
            print("MISSING %s" % raw)
            continue
        walk = [(resolved, [], [os.path.basename(resolved)])] if os.path.isfile(resolved) else os.walk(resolved)
        for dirpath, dirnames, names in walk:
            dirnames[:] = sorted(d for d in dirnames if not d.startswith("."))
            for n in sorted(names):
                if n.startswith("."):
                    continue
                p = resolved if (dirpath == resolved and n == os.path.basename(resolved)) else os.path.join(dirpath, n)
                if not os.path.isfile(p):
                    continue
                text, ok, reason, enc = extract(p)
                if ok and "\ufffd" in text:
                    reason = "garbled_replacement_chars"
                rec = {"path": p, "bytes": os.path.getsize(p), "chars": len(text), "readable": ok,
                       "reason": reason, "encoding": enc, "sha1": sha1_of(p)}
                items.append(rec)
                if not ok:
                    unreadable.append(p)
                corpus.append("===== FILE: %s =====\n%s"
                              % (p, text if ok else "[unreadable: %s]" % reason))
                print("%-8s %8d  %s%s" % ("ok" if ok else "UNREAD", len(text), p, "" if ok else "  <- " + reason))
    dump({"files": items, "total_chars": sum(i["chars"] for i in items),
          "unreadable": unreadable, "missing_inputs": missing,
          "readable_files": sum(1 for i in items if i["readable"])},
         os.path.join(a.out, "evidence.json"))
    os.makedirs(a.out, exist_ok=True)
    with open(os.path.join(a.out, "corpus.txt"), "w", encoding="utf-8") as fh:
        fh.write("\n\n".join(corpus))
    if not items:
        print("BLOCKED: no readable material indexed (missing=%d); do not invent content"
              % len(missing))
        return 1
    if not any(i["readable"] for i in items):
        print("WARN: every material is unreadable; downstream must report partial/blocked")
        return 1
    if missing:
        print("WARN: %d material(s) missing; record them in limits/uncertainty" % len(missing))
    return 0


def num_tokens(text):
    out = set()
    for tok in NUMTOK.findall(text):
        out.add(tok.replace(",", "") if THOUSANDS.match(tok) else tok)
    return out


def cmd_verify(a):
    corpus_path = os.path.join(a.evidence_dir, "corpus.txt")
    if not os.path.exists(corpus_path):
        print("FAIL: corpus.txt missing in %s (run index first)" % a.evidence_dir)
        return 2
    corpus = open(corpus_path, encoding="utf-8").read()
    ev_path = os.path.join(a.evidence_dir, "evidence.json")
    ev = load_json(ev_path) if os.path.exists(ev_path) else {}
    draft = open(a.text, encoding="utf-8").read()
    src_nums = num_tokens(corpus)
    numbers = []
    for m in NUM_RE.finditer(draft):
        tok = m.group(0).strip()
        numbers.append(tok.replace(",", "") if THOUSANDS.match(tok) else tok)
    unsupported = [n for n in dict.fromkeys(numbers) if n not in src_nums]
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
        "missing_inputs": ev.get("missing_inputs", []),
        "verdict": "pass" if not unsupported and not missing_cites else "review",
    }
    dump(report, os.path.join(a.out, "claims.json"))
    print("verdict=%s unsupported_numbers=%d citations_not_in_sources=%d"
          % (report["verdict"], len(unsupported), len(missing_cites)))
    for n in unsupported[:20]:
        print("  ? number not in sources:", n)
    for c in missing_cites[:20]:
        print("  ? citation not in sources:", c)
    return 0 if report["verdict"] == "pass" else 1


def contract_field_names(fields):
    if isinstance(fields, list):
        return [str(f) for f in fields]
    if isinstance(fields, dict):
        if isinstance(fields.get("fields"), list):
            return [str(f) for f in fields["fields"]]
        if isinstance(fields.get("required"), list):
            return [str(f) for f in fields["required"]]
        return [str(k) for k in fields]
    return []


def cmd_emit(a):
    cpath = os.path.join(a.contract_dir, "contract.json") if os.path.isdir(a.contract_dir) else a.contract_dir
    if not os.path.exists(cpath):
        print("FAIL: contract.json not found: %s (run init first)" % cpath)
        return 2
    contract = load_json(cpath)
    draft = load_json(a.draft)
    names = contract_field_names(contract.get("contract") or {})
    result = {"case_id": contract.get("case_id"), "status": draft.get("status", "partial")}
    pool = draft.get("fields") if isinstance(draft.get("fields"), dict) else {}
    for name in names:
        result[name] = pool.get(name, draft.get(name))
    for name, val in pool.items():
        result.setdefault(name, val)
    for key in ("uncertainty", "sources", "changes", "self_check", "limits", "artifacts"):
        if key in draft and key not in result:
            result[key] = draft[key]
    result.setdefault("uncertainty", [])
    result.setdefault("sources", [])
    result.setdefault("changes", [])
    if "limits" not in result:
        result["limits"] = draft.get("limits", "")
    os.makedirs(a.out, exist_ok=True)
    dump(result, os.path.join(a.out, "result.json"))
    artifacts = draft.get("artifacts") or (pool.get("artifacts") if isinstance(pool.get("artifacts"), dict) else {}) or {}
    for name, body in artifacts.items():
        p = os.path.join(a.out, name)
        os.makedirs(os.path.dirname(p) or a.out, exist_ok=True)
        with open(p, "w", encoding="utf-8") as fh:
            fh.write(body if isinstance(body, str) else json.dumps(body, ensure_ascii=False, indent=1))
    missing = [k for k in names if result.get(k) is None]
    print("result.json written; contract_fields=%d missing_contract_fields=%s"
          % (len(names), missing or "none"))
    return 1 if missing else 0


def cmd_check(a):
    problems = []
    rp = os.path.join(a.out, "result.json")
    res = None
    if not os.path.exists(rp):
        problems.append("result.json missing")
    else:
        try:
            res = load_json(rp)
        except json.JSONDecodeError as exc:
            problems.append("result.json is not valid JSON: %s" % exc)
    if res is not None:
        for k in ("case_id", "status"):
            if not res.get(k):
                problems.append("result.json missing %s" % k)
        if res.get("status") not in {"ok", "success", "partial", "blocked", "refused"}:
            problems.append("status must be one of ok/success/partial/blocked/refused")
        if res.get("status") in {"partial", "blocked"} and not str(res.get("limits") or "").strip():
            problems.append("status=%s requires a non-empty limits field" % res.get("status"))
        if a.contract_dir:
            cpath = os.path.join(a.contract_dir, "contract.json")
            if os.path.exists(cpath):
                names = contract_field_names(load_json(cpath).get("contract") or {})
                lost = [k for k in names if res.get(k) is None]
                if lost:
                    problems.append("contract fields missing in result.json: %s" % lost)
            else:
                problems.append("contract.json not found in %s" % a.contract_dir)
        lt_cands = [os.path.join(a.out, "locator_table.csv")]
        if a.work_dir:
            lt_cands.append(os.path.join(a.work_dir, "locator_table.csv"))
        elif a.contract_dir:
            lt_cands.append(os.path.join(a.contract_dir, "locator_table.csv"))
        known = set()
        for lt in lt_cands:
            if os.path.exists(lt):
                import csv as _csv
                with open(lt, encoding="utf-8") as fh:
                    for row in _csv.DictReader(fh):
                        known.add(row.get("block_id"))
                break
        ev = res.get("evidence")
        if isinstance(ev, list) and known:
            unknown = [e.get("block_id") for e in ev
                       if isinstance(e, dict) and e.get("block_id") and e.get("block_id") not in known]
            if unknown:
                problems.append("evidence block_id not in locator_table.csv: %s" % unknown[:5])
        structured = res.get("structured") if isinstance(res.get("structured"), dict) else {}
        for t in structured.get("tables") or []:
            if isinstance(t, dict) and t.get("csv_path") and not os.path.exists(os.path.join(a.out, t["csv_path"])):
                problems.append("tables[].csv_path missing on disk: %s" % t["csv_path"])
    print("PASS" if not problems else "FAIL")
    for p in problems:
        print(" -", p)
    return 0 if not problems else 1


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("init"); p.add_argument("--case"); p.add_argument("--out", default="work"); p.set_defaults(fn=cmd_init)
    p = sub.add_parser("index"); p.add_argument("--materials", nargs="+", required=True)
    p.add_argument("--case", help="case.json path used to resolve relative material paths")
    p.add_argument("--out", default="work"); p.set_defaults(fn=cmd_index)
    p = sub.add_parser("verify"); p.add_argument("--text", required=True); p.add_argument("--evidence-dir", default="work")
    p.add_argument("--out", default="work"); p.set_defaults(fn=cmd_verify)
    p = sub.add_parser("emit"); p.add_argument("--draft", required=True); p.add_argument("--contract-dir", default="work")
    p.add_argument("--out", default="/app/output"); p.set_defaults(fn=cmd_emit)
    p = sub.add_parser("check"); p.add_argument("--out", default="/app/output")
    p.add_argument("--contract-dir", default=None)
    p.add_argument("--work-dir", default=None, help="dir holding locator_table.csv for evidence cross-check")
    p.set_defaults(fn=cmd_check)

    a = ap.parse_args()
    return a.fn(a)


if __name__ == "__main__":
    sys.exit(main())
