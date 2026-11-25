#!/usr/bin/env python3
"""run_case.py - one command for the formula-reading main path (stdlib only).

Reads case.json, indexes real materials (PDF via pdftotext, XML via mathml_extract),
writes honest skeletons for formulas / symbols / derivations / numeric checks, runs the
existing formula_check.py and quote_check.py, then emits result.json + formula_sheet.md +
symbols.csv. Anything that cannot be extracted is marked insufficient_evidence with an
empty latex; nothing is guessed or back-filled.

Usage (runtime):
  python3 scripts/run_case.py --case /input/case.json --work /app/work --out /app/output

Usage (local dry run, no /input):
  python3 scripts/run_case.py --dry-run --case ./input/case.json --out ./out
"""
import argparse
import csv
import json
import os
import re
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
sys.dont_write_bytecode = True  # keep the installed skill directory free of __pycache__
import mathml_extract  # shipped stdlib-only module; reused for MathML -> LaTeX

DEFAULT_FIELDS = ["case_id", "status", "answer", "structured", "evidence", "uncertainty", "limits"]
TEXT_EXT = {".txt", ".md", ".csv", ".tsv", ".json", ".tex", ".rst", ".html", ".bib", ".yaml", ".yml"}
GREEK = {
    "alpha": "α", "beta": "β", "gamma": "γ", "delta": "δ", "epsilon": "ε", "zeta": "ζ",
    "eta": "η", "theta": "θ", "iota": "ι", "kappa": "κ", "lambda": "λ", "mu": "μ",
    "nu": "ν", "xi": "ξ", "pi": "π", "rho": "ρ", "sigma": "σ", "tau": "τ", "upsilon": "υ",
    "phi": "φ", "chi": "χ", "psi": "ψ", "omega": "ω", "Gamma": "Γ", "Delta": "Δ",
    "Theta": "Θ", "Lambda": "Λ", "Xi": "Ξ", "Pi": "Π", "Sigma": "Σ", "Phi": "Φ",
    "Psi": "Ψ", "Omega": "Ω",
}
CUE = r"(?:is|are|denotes|represents|refers to|corresponds to|定义为|表示|指的是|是)"
DECL_RE = re.compile(r"(?:式|公式|Eq\.?|Equation)\s*[（(]?\s*(\d+)\s*[)）]?", re.I)
RANGE_RE = re.compile(r"[（(]?\s*(\d+)\s*[)）]?\s*[-–—~至]\s*[（(]?\s*(\d+)\s*[)）]?")


def load_json(path):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def dump(obj, path):
    os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(obj, fh, ensure_ascii=False, indent=1)


def find_case_file(explicit):
    cands = [explicit] if explicit else []
    cands += ["/input/case.json", "case.json", "/app/input/case.json", "./input/case.json"]
    for c in cands:
        if c and os.path.isfile(c):
            return os.path.abspath(c)
    return None


def _as_field_name(item):
    if isinstance(item, str):
        return item.strip()
    if isinstance(item, dict):
        for key in ("name", "field", "field_id", "id", "key"):
            val = item.get(key)
            if isinstance(val, str) and val.strip():
                return val.strip()
    return None


def contract_fields(contract):
    """Accept {field: type}, [field, ...], {"fields": [...]} or {"required": [...]}.

    Real cases use several shapes; treating {"required": [...]} as field names would
    silently emit a bogus "required" key and drop the real contract.
    """
    names = []
    if isinstance(contract, list):
        names = [_as_field_name(x) for x in contract]
    elif isinstance(contract, dict):
        items = None
        for key in ("required", "fields", "properties"):
            val = contract.get(key)
            if isinstance(val, list) and val:
                items = val
                break
            if isinstance(val, dict) and val:
                items = list(val.keys())
                break
        if items is None:
            items = list(contract.keys())
        names = [_as_field_name(x) for x in items]
    out = []
    for n in names:
        if n and n not in out:
            out.append(n)
    return out


def resolve_input_dir(explicit, case_path):
    if explicit:
        return os.path.abspath(explicit)
    if case_path:
        d = os.path.dirname(case_path)
        if os.path.isdir(os.path.join(d, "materials")) or os.path.isdir(os.path.join(d, "artifacts")):
            return d
        parent = os.path.dirname(d)
        if os.path.basename(d) == "input" and (
                os.path.isdir(os.path.join(parent, "materials")) or os.path.isdir(os.path.join(parent, "artifacts"))):
            return parent
    for c in ("/input", "./input", "/app/input"):
        if os.path.isdir(c):
            return os.path.abspath(c)
    return os.path.abspath(os.path.dirname(case_path)) if case_path else os.getcwd()


def iter_files(root):
    for dirpath, dirnames, names in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if not d.startswith("."))
        for name in sorted(names):
            if not name.startswith("."):
                yield os.path.join(dirpath, name)


def read_pdf_text(path):
    exe = shutil.which("pdftotext")
    if not exe:
        return None, "pdftotext not found on PATH; PDF left unread (content not guessed)"
    try:
        proc = subprocess.run([exe, "-layout", "-f", "1", "-l", "60", path, "-"],
                              capture_output=True, timeout=90)
        text = proc.stdout.decode("utf-8", "replace") if proc.stdout else ""
        if proc.returncode == 0 and text.strip():
            return text, None
        return None, "pdftotext returned no text (image-only or protected); content not guessed"
    except Exception as exc:  # noqa: BLE001
        return None, "pdftotext failed: %s" % exc


def extract_mathml(path):
    """Return (formulas, plain_text, error) using mathml_extract.tex for every <math> node."""
    import xml.etree.ElementTree as ET
    try:
        root = ET.parse(path).getroot()
    except Exception as exc:  # noqa: BLE001
        return [], None, "XML parse failed: %s" % exc
    parents = {c: p for p in root.iter() for c in p}
    formulas = []
    for node in root.iter():
        if mathml_extract.local(node.tag) != "math":
            continue
        chain, cur = [], parents.get(node)
        while cur is not None:
            if cur.get("id"):
                chain.append(cur.get("id"))
            cur = parents.get(cur)
        xml_id = node.get("id") or (chain[0] if chain else "math-%d" % (len(formulas) + 1))
        label = ""
        for k in node.iter():
            if mathml_extract.local(k.tag) == "label":
                label = "".join(k.itertext()).strip()
                break
        formulas.append({
            "xml_id": xml_id,
            "label": label or xml_id,
            "latex": mathml_extract.tex(node),
            "plain": " ".join("".join(node.itertext()).split())[:200],
            "source_ids": chain[:3],
        })
    plain = " ".join("".join(root.itertext()).split())
    return formulas, plain, None


def bracket_depth(latex):
    pairs = {"{": "}", "[": "]", "(": ")"}
    stack, best, i = [], 0, 0
    while i < len(latex):
        ch = latex[i]
        if ch == "\\":
            i += 2
            continue
        if ch in pairs:
            stack.append(pairs[ch])
            best = max(best, len(stack))
        elif ch in ")]}" and stack:
            stack.pop()
        i += 1
    return best


def count_structure(latex):
    return {
        "fractions": len(re.findall(r"\\(?:frac|dfrac|tfrac)", latex)),
        "subscripts": latex.count("_"),
        "superscripts": latex.count("^"),
        "bracket_depth": bracket_depth(latex),
        "sqrt": len(re.findall(r"\\sqrt", latex)),
    }


def symbols_from_latex(latex):
    found = []

    def add(sym):
        if sym and sym not in found:
            found.append(sym)

    for m in re.finditer(r"\\([A-Za-z]+)", latex):
        if m.group(1) in GREEK:
            add(GREEK[m.group(1)])
    body = re.sub(r"\\(?:text|mathrm|operatorname|mbox)\{[^{}]*\}", " ", latex)
    body = re.sub(r"\\[A-Za-z]+", " ", body)
    for m in re.finditer(r"([A-Za-z])(?:_\{([^{}]{1,12})\})?", body):
        add(m.group(1) + ("_" + m.group(2) if m.group(2) else ""))
    return found


def definition_variants(sym):
    variants = [sym]
    m = re.match(r"^([A-Za-z])_\{?([A-Za-z0-9]{1,12})\}?$", sym)
    if m:
        base, sub = m.groups()
        variants += [base + sub, base + " " + sub, "%s_{%s}" % (base, sub)]
    return list(dict.fromkeys(variants))


def find_definition(sym, lines):
    """Conservative single-line definition lookup; returns dict or None.

    Only verbatim substrings of the source line are returned (meaning / unit / range).
    When the line does not state a unit, unit stays None together with a note, and the
    symbol is never upgraded to author_defined on a guess.
    """
    pats = []
    for var in definition_variants(sym):
        low = var.lower()
        pats.append((low, re.compile(r"(?<![A-Za-z0-9])" + re.escape(low) + r"[^。.;\n]{0,20}?" + CUE, re.I)))
    for rel, line_no, line in lines:
        low = line.lower()
        for var, pat in pats:
            if var not in low:
                continue
            if not pat.search(low) or len(line.strip()) < 12:
                continue
            quote = line.strip()[:280]
            meaning = _meaning_from_quote(sym, quote)
            unit = _unit_from_quote(quote)
            rng = _range_from_quote(quote)
            note = "locator/quote auto-detected"
            note += "; unit=%s" % unit if unit else "; unit not stated on this line"
            if rng:
                note += "; range=%s" % rng
            return {
                "definition_status": "author_defined",
                "meaning": meaning,
                "unit": unit,
                "range": rng,
                "locator": {"source": rel, "scope": "line %d" % line_no},
                "quote": quote,
                "note": note,
            }
    return None


def _meaning_from_quote(sym, quote):
    """Take the verbatim words between the symbol and a definition cue, if present."""
    base = sym.split("_")[0]
    pat = re.compile(
        r"(?<![A-Za-z0-9])" + re.escape(base) + r"[_A-Za-z0-9{}\\ ]{0,6}?\s*"
        r"(?:is|are|denotes|represents|refers to|corresponds to|表示|定义为|指的是)\s+"
        r"(?:the\s+|a\s+|an\s+)?([^,.;。；]{3,70})", re.I)
    m = pat.search(quote)
    if not m:
        return None
    meaning = m.group(1).strip()
    # Trim a trailing unit clause so meaning and unit do not overlap.
    meaning = re.split(r"\s+(?:in|with unit|measured in|单位)\s+", meaning, flags=re.I)[0].strip()
    return meaning or None


UNIT_HINT = re.compile(
    r"(?:\bin\s+|\bmeasured in\s+|\bunits?\s+of\s+|单位为\s*|单位[:：]\s*|单位为\s*)"
    r"([A-Za-zµμ%‰°][A-Za-z0-9µμ%‰°/·^.^+-]{0,14})", re.I)


UNIT_STOP = {"eq", "eq.", "fig", "fig.", "table", "section", "the", "this", "which",
             "our", "study", "paper", "work", "text", "total", "order", "turn"}


def _unit_from_quote(quote):
    for m in UNIT_HINT.finditer(quote):
        unit = m.group(1).strip().rstrip(".,;:")
        if not unit or unit.lower() in UNIT_STOP:
            continue
        # "In Eq. (1)" is a pointer, not a unit; skip ordinals/references.
        if re.fullmatch(r"(?:Eq|Fig|Table|Section|Ref)\.?", m.group(1).strip()):
            continue
        return unit
    return None


RANGE_HINT = re.compile(
    r"(?:\brange\b|\branging\b|取值范围|范围)\s*(?:is|of|为|是|[:：])?\s*"
    r"([<>≤≥≈]?\s*-?\d+(?:\.\d+)?(?:\s*(?:-|–|—|~|至|to)\s*-?\d+(?:\.\d+)?)?)", re.I)


def _range_from_quote(quote):
    m = RANGE_HINT.search(quote)
    return m.group(1).strip() if m else None


def declared_equation_numbers(text):
    nums = []
    for m in RANGE_RE.finditer(text):
        lo, hi = int(m.group(1)), int(m.group(2))
        if 0 < lo <= hi and hi - lo <= 20:
            nums.extend(range(lo, hi + 1))
    nums.extend(int(m.group(1)) for m in DECL_RE.finditer(text))
    return list(dict.fromkeys(nums))


def formula_numbers(f):
    raw = "%s %s" % (f.get("label") or "", f.get("xml_id") or f.get("id") or "")
    found = re.findall(r"\d+", raw)
    return int(found[-1]) if found else None


def rel(path, root):
    try:
        return os.path.relpath(path, root).replace(os.sep, "/")
    except ValueError:
        return os.path.basename(path)


def pick_field(name, base):
    key = name.lower()
    if key in base:
        return base[key]
    aliases = {
        "summary": "answer", "result": "answer", "conclusion": "answer",
        "analysis": "structured", "details": "structured", "structured_result": "structured",
        "citations": "evidence", "quotes": "evidence",
        "gaps": "uncertainty", "unknowns": "uncertainty",
        "limitation": "limits", "limitations": "limits",
    }
    if key in aliases:
        return base[aliases[key]]
    if key == "formula_sheet":
        return "formula_sheet.md"
    if key == "symbols_table":
        return "symbols.csv"
    # Unknown contract field: attach the structured payload instead of null, and mark
    # the fallback so a reviewer can see the name was not recognized.
    fallback = dict(base.get("structured") or {})
    fallback["_contract_field"] = name
    fallback["_note"] = "字段名未在别名表中，已用 structured 填充，需人工确认"
    return fallback


def build_answer(counts, status):
    return (
        "已索引材料 {files} 个（可读 {readable}，不可读 {unreadable}）；从 mathml/source-formulas 抽取公式 "
        "{extracted} 个，declared 未覆盖 {insufficient} 个；符号 {symbols} 个（已定位定义 {defined}，unknown {unknown}）；"
        "推导骨架 {derivations} 条；数值核验 0 条（材料中未定位到可复算输入，全部 not_checkable）。"
        "status={status}。详见 structured、formula_sheet.md 与 symbols.csv。"
    ).format(status=status, **counts)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--case", help="path to case.json")
    ap.add_argument("--input-dir", help="input root containing materials/ and artifacts/")
    ap.add_argument("--work", help="work dir (default /app/work; ./work with --dry-run)")
    ap.add_argument("--out", help="output dir (default /app/output; ./out with --dry-run)")
    ap.add_argument("--dry-run", action="store_true", help="local run without /input; requires --case")
    a = ap.parse_args()

    if a.dry_run and not a.case:
        ap.error("--dry-run requires --case <sample case.json>")
    work = os.path.abspath(a.work or ("./work" if a.dry_run else "/app/work"))
    out = os.path.abspath(a.out or ("./out" if a.dry_run else "/app/output"))
    os.makedirs(work, exist_ok=True)
    os.makedirs(out, exist_ok=True)

    case_path = find_case_file(a.case)
    case, case_error = {}, None
    if case_path:
        try:
            case = load_json(case_path)
        except Exception as exc:  # noqa: BLE001
            # A malformed case.json must not crash the harness: fall back to the default
            # contract, say so in limits, and still emit a contract-complete result.json.
            case_error = "case.json 无法解析（%s），已回退默认契约，未猜测字段内容" % exc
    input_dir = resolve_input_dir(a.input_dir, case_path)
    fields = contract_fields(case.get("output_contract")) or DEFAULT_FIELDS
    case_id = case.get("case_id") or case.get("id") or (
        os.path.splitext(os.path.basename(case_path))[0] if case_path else "unknown")

    task_text = " ".join(str(case.get(k) or "") for k in ("task", "question", "focus", "scope"))
    task_md = os.path.join(input_dir, "task.md")
    if os.path.isfile(task_md):
        task_text += " " + open(task_md, encoding="utf-8", errors="replace").read()

    # ---------------------------------------------------------------- index real materials
    roots = [os.path.join(input_dir, "materials"), os.path.join(input_dir, "artifacts")]
    if not any(os.path.isdir(r) for r in roots):
        roots = [input_dir]
    skip_names = {"case.json", "task.md"}
    materials, corpus_blocks, lines = [], [], []
    extracted, xml_seen = [], []
    for root in roots:
        if not os.path.isdir(root):
            continue
        for path in iter_files(root):
            name = os.path.basename(path)
            if name in skip_names:
                continue
            relpath = rel(path, input_dir)
            ext = os.path.splitext(path)[1].lower()
            text, note, readable = None, None, True
            if ext == ".pdf":
                text, note = read_pdf_text(path)
                readable = text is not None
                if not readable:
                    text = "[PDF unreadable: %s]" % note
            elif ext == ".xml":
                xml_formulas, plain, err = extract_mathml(path)
                if err:
                    readable, note, text = False, err, "[XML unreadable: %s]" % err
                else:
                    text = plain or ""
                    xml_seen.append(relpath)
                    for f in xml_formulas:
                        f["_source_path"] = relpath
                        f["_source_file"] = name
                        extracted.append(f)
            elif ext in TEXT_EXT:
                try:
                    text = open(path, encoding="utf-8", errors="replace").read()
                except Exception as exc:  # noqa: BLE001
                    readable, note, text = False, str(exc), "[unreadable: %s]" % exc
            else:
                readable, note, text = False, "unsupported type %s (content not guessed)" % ext, \
                    "[unsupported type %s]" % ext
            materials.append({"path": relpath, "bytes": os.path.getsize(path),
                              "chars": len(text or ""), "readable": readable, "note": note})
            corpus_blocks.append("===== FILE: %s =====\n%s" % (relpath, text or ""))
            if readable:
                for i, line in enumerate((text or "").splitlines(), 1):
                    if line.strip():
                        lines.append((relpath, i, line.strip()))

    corpus_path = os.path.join(work, "corpus.txt")
    with open(corpus_path, "w", encoding="utf-8") as fh:
        fh.write("\n\n".join(corpus_blocks))

    # ---------------------------------------------------------------- formulas
    formulas, used_ids, seen_sig = [], set(), {}
    for item in extracted:
        fid = item["xml_id"]
        sig = (item["xml_id"], item.get("latex") or "")
        if sig in seen_sig:
            # publisher-source.xml and source-formulas.xml overlap: keep one entry per
            # real formula instead of emitting duplicate "_x" copies that inflate counts
            # and duplicate the symbol table.
            kept = seen_sig[sig]
            kept["source"].setdefault("also_in", []).append(item["_source_path"])
            continue
        while fid in used_ids:
            fid += "_x"
        used_ids.add(fid)
        latex = item["latex"]
        record = {
            "id": fid,
            "label": item["label"],
            "status": "extracted",
            "latex": latex,
            "source": {"path": item["_source_path"], "locator": "xml:%s" % item["xml_id"],
                       "xml_id": item["xml_id"], "quote": (item.get("plain") or "")[:200]},
            "structure": count_structure(latex),
            "symbols": symbols_from_latex(latex),
            "conditions": [],
            "uncertainty": ["LaTeX is a MathML skeleton; verify against the printed formula"],
        }
        seen_sig[sig] = record
        formulas.append(record)

    covered = {formula_numbers(f) for f in extracted}
    covered.discard(None)
    declared = declared_equation_numbers(task_text)
    for num in declared:
        if num in covered:
            continue
        fid = "F%d" % num
        while fid in used_ids:
            fid += "_x"
        used_ids.add(fid)
        decl = "Eq. (%d)" % num
        quote = decl if decl in task_text else "Eq. %d" % num
        formulas.append({
            "id": fid, "label": "Eq. (%d)" % num, "status": "insufficient_evidence", "latex": "",
            "reason": "no formula representation for Eq. (%d) in the indexed materials" % num,
            "source": {"path": "task.md", "locator": "task.md:declared", "quote": quote},
            "structure": {"fractions": 0, "subscripts": 0, "superscripts": 0, "bracket_depth": 0},
            "symbols": [], "conditions": [],
            "uncertainty": ["declared in the task but not extractable; content not guessed"],
        })
    if not formulas:
        formulas.append({
            "id": "F0", "label": "no formula representation", "status": "insufficient_evidence",
            "latex": "", "reason": "no MathML/LaTeX formula representation found in indexed materials",
            "source": {"path": None, "locator": "index"},
            "structure": {"fractions": 0, "subscripts": 0, "superscripts": 0, "bracket_depth": 0},
            "symbols": [], "conditions": [],
            "uncertainty": ["formula content not available; nothing was inferred"],
        })

    # ---------------------------------------------------------------- symbols
    symbols, seen = [], set()
    for f in formulas:
        for sym in f.get("symbols") or []:
            if sym in seen:
                continue
            seen.add(sym)
            guess = find_definition(sym, lines)
            if guess:
                entry = {"symbol": sym}
                entry.update(guess)
            else:
                entry = {
                    "symbol": sym, "meaning": None, "unit": None, "range": None,
                    "definition_status": "unknown", "locator": None,
                    "note": "definition/unit not located automatically; confirm in source or keep unknown",
                }
            symbols.append(entry)

    # ---------------------------------------------------------------- derivations skeleton
    derivations = []
    for f in formulas:
        if f["status"] == "insufficient_evidence":
            continue
        derivations.append({
            "formula_id": f["id"],
            "target": f["label"],
            "steps": [{"n": 1, "expr": f["latex"],
                       "basis": "source formula as extracted from %s" % f["source"]["locator"]}],
            "assumptions": [], "approximations": [], "boundary": None, "depends_on": [],
            "note": "skeleton only; algebra steps, assumptions and boundary need human/model completion",
        })

    # ---------------------------------------------------------------- numeric checks skeleton
    not_checkable = []
    for f in formulas:
        if f["status"] == "insufficient_evidence":
            continue
        not_checkable.append({
            "formula_id": f["id"],
            "missing_inputs": f.get("symbols") or [],
            "status": "not_checkable",
            "note": "no numeric values with units located in the indexed materials",
        })

    formulas_obj = {"formulas": formulas,
                    "note": "extracted = MathML skeleton; insufficient_evidence carries empty latex"}
    symbols_obj = {"symbols": symbols}
    derivations_obj = {"derivations": derivations, "note": "only step 1 (source restatement) is automatic"}
    numerics_obj = {"numeric_checks": [], "not_checkable": not_checkable,
                    "note": "no numeric inputs were located; missing values are not filled with 0"}
    dump(formulas_obj, os.path.join(work, "formulas.json"))
    dump(symbols_obj, os.path.join(work, "symbols.json"))
    dump(derivations_obj, os.path.join(work, "derivations.json"))
    dump(numerics_obj, os.path.join(work, "numeric_checks.json"))

    quotes = [{"claim": s["symbol"], "source_path": s["locator"].get("source"),
               "locator": s["locator"].get("scope"), "quote": s["quote"]}
              for s in symbols if s.get("quote")]
    if quotes:
        dump(quotes, os.path.join(work, "quotes.json"))

    # ---------------------------------------------------------------- run shipped checkers
    def run_check(script, args):
        proc = subprocess.run([sys.executable, os.path.join(HERE, script)] + args,
                              capture_output=True, text=True)
        print(proc.stdout.strip())
        if proc.stderr.strip():
            print(proc.stderr.strip(), file=sys.stderr)
        return proc.returncode

    fc_out = os.path.join(work, "formula_check.json")
    run_check("formula_check.py", [
        "--formulas", os.path.join(work, "formulas.json"),
        "--symbols", os.path.join(work, "symbols.json"),
        "--derivations", os.path.join(work, "derivations.json"),
        "--numerics", os.path.join(work, "numeric_checks.json"),
        "--corpus", corpus_path, "--out", fc_out,
    ])
    formula_report = load_json(fc_out) if os.path.isfile(fc_out) else {"verdict": "missing", "errors": []}

    qc_out = os.path.join(work, "quote_check.json")
    quote_report = {"verdict": "skipped", "failed": 0}
    if os.path.isfile(os.path.join(work, "quotes.json")):
        run_check("quote_check.py", [
            "--evidence", os.path.join(work, "quotes.json"),
            "--corpus", corpus_path, "--out", qc_out,
        ])
        if os.path.isfile(qc_out):
            quote_report = load_json(qc_out)

    # ---------------------------------------------------------------- build result
    readable_any = any(m["readable"] and m["chars"] > 0 for m in materials)
    known = [s for s in symbols if s["definition_status"] in {"author_defined", "context_inferred", "conventional"}]
    unknown = [s["symbol"] for s in symbols if s["definition_status"] == "unknown"]
    insufficient = [f for f in formulas if f["status"] == "insufficient_evidence"]

    if not materials or not readable_any:
        status = "blocked"
        limits = "没有可读材料：%s。未猜测任何公式或符号。" % (
            "；".join(m["note"] for m in materials if m.get("note")) or "materials 目录为空")
    elif (insufficient or unknown or not derivations or not not_checkable
          or formula_report.get("verdict") != "pass" or quote_report.get("verdict") == "review"):
        status = "partial"
        limits = "自动骨架：公式由 MathML 抽取，符号定义/单位、推导步骤与数值输入仍需人工或模型按原文补齐。"
    else:
        status = "ok"
    if case_error and status == "ok":
        status = "partial"
        limits = ""

    counts = {
        "files": len(materials), "readable": sum(1 for m in materials if m["readable"]),
        "unreadable": sum(1 for m in materials if not m["readable"]),
        "extracted": sum(1 for f in formulas if f["status"] == "extracted"),
        "insufficient": len(insufficient), "symbols": len(symbols),
        "defined": len(known), "unknown": len(unknown), "derivations": len(derivations),
    }

    evidence = []
    for relpath, line_no, line in lines[:1]:
        evidence.append({"claim": "材料可读并已索引（原文片段）", "source_path": relpath,
                         "locator": "line %d" % line_no, "quote": line[:280]})
    for f in formulas:
        src = f.get("source") or {}
        quote = (src.get("quote") or "").strip()
        if quote and src.get("path"):
            evidence.append({"claim": "公式 %s（%s）的结构来源" % (f["id"], f["label"]),
                             "source_path": src.get("path"),
                             "locator": src.get("locator"), "quote": quote[:280]})
    for s in known:
        evidence.append({"claim": "符号 %s 的原文定义" % s["symbol"],
                         "source_path": s["locator"].get("source"),
                         "locator": s["locator"].get("scope"), "quote": s["quote"]})

    uncertainty = []
    for s in symbols:
        if s["definition_status"] == "unknown":
            uncertainty.append("符号 %s 缺原文定义/单位，保持 unknown，未用于数值代入" % s["symbol"])
    for f in insufficient:
        uncertainty.append("%s（%s）无可抽取的公式表示：%s" % (f["id"], f["label"], f.get("reason")))
    if not not_checkable:
        uncertainty.append("没有任何可复算的数值输入（都未定位到），numeric_checks 为空")
    if case_error:
        uncertainty.append(case_error)
        limits = (limits + "；" if limits else "") + case_error

    answer = build_answer(counts, status)
    structured = {
        "formulas": formulas,
        "symbols": symbols,
        "derivations": derivations,
        "numeric_checks": [],
        "not_checkable": not_checkable,
        "insufficient_evidence": [{"formula_id": f["id"], "label": f["label"],
                                   "reason": f.get("reason")} for f in insufficient],
        "unknown_symbols": unknown,
        "check_summary": {"formula_check": formula_report.get("verdict"),
                          "formula_check_errors": formula_report.get("errors", []),
                          "quote_check": quote_report.get("verdict"),
                          "quote_check_failed": quote_report.get("failed", 0)},
        "artifacts": {"formula_sheet": "formula_sheet.md", "symbols_csv": "symbols.csv",
                      "formulas": "formulas.json", "derivations": "derivations.json",
                      "numeric_checks": "numeric_checks.json"},
        "materials": materials,
        "scope": {"input_dir": input_dir, "declared_equations": declared,
                  "task_excerpt": task_text.strip()[:600]},
        "counts": counts,
    }

    base = {
        "case_id": case_id, "status": status, "answer": answer, "structured": structured,
        "evidence": evidence, "uncertainty": uncertainty, "limits": limits,
        "sources": [m["path"] for m in materials], "metrics": counts,
        "formula_sheet": "formula_sheet.md", "symbols_table": "symbols.csv",
    }
    result = {}
    for name in fields:
        result[name] = pick_field(name, base)
    for name, value in base.items():
        result.setdefault(name, value)
    dump(result, os.path.join(out, "result.json"))

    # ---------------------------------------------------------------- markdown + csv
    md = ["# 公式页（自动骨架）", "",
          "> 由 `scripts/run_case.py` 生成：只包含实际索引/抽取内容；未抽取项标 `insufficient_evidence`，",
          "> 不反推公式、不补单位、不填默认数值。", "",
          "## 材料", ""]
    for m in materials:
        md.append("- `%s` — %s%s" % (m["path"], "可读 %d 字符" % m["chars"] if m["readable"] else "不可读",
                                    "（%s）" % m["note"] if m.get("note") else ""))
    md += ["", "## 公式", ""]
    for f in formulas:
        md += ["### %s — %s" % (f["id"], f["label"]), "",
               "- status: `%s`" % f["status"]]
        if f["status"] == "insufficient_evidence":
            md += ["- latex: （空）", "- reason: %s" % f.get("reason"), ""]
            continue
        md += ["- LaTeX: `%s`" % f["latex"],
               "- 结构: %s" % json.dumps(f["structure"], ensure_ascii=False),
               "- 来源: `%s`（%s）" % (f["source"]["path"], f["source"]["locator"]),
               "- 符号: %s" % (", ".join(f["symbols"]) or "（未识别）"), ""]
    md += ["## 符号表", ""]
    for s in symbols:
        md.append("- `%s` — %s，单位 %s，定义状态 `%s`，%s" % (
            s["symbol"], s.get("meaning") or "待补", s.get("unit") or "待补",
            s["definition_status"], (s.get("locator") or {}).get("scope") or "无定位"))
    md += ["", "## 推导（骨架）", ""]
    for d in derivations:
        md.append("- `%s`: 仅第 1 步（原式重述），依据 `%s`；代数步骤/假设/边界待补" % (
            d["formula_id"], d["steps"][0]["basis"]))
    md += ["", "## 数值核验", "",
           "未定位到带单位的可复算输入，`numeric_checks` 为空；缺项不填 0。", "",
           "## 仍需人工/模型补齐", ""]
    for item in uncertainty:
        md.append("- " + item)
    md.append("- formula_check: %s；quote_check: %s" % (
        formula_report.get("verdict"), quote_report.get("verdict")))
    with open(os.path.join(out, "formula_sheet.md"), "w", encoding="utf-8") as fh:
        fh.write("\n".join(md) + "\n")

    with open(os.path.join(out, "symbols.csv"), "w", encoding="utf-8", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(["symbol", "meaning", "unit", "range", "definition_status", "locator", "quote"])
        for s in symbols:
            loc = s.get("locator") or {}
            writer.writerow([s["symbol"], s.get("meaning") or "", s.get("unit") or "",
                             s.get("range") or "", s["definition_status"],
                             "%s %s" % (loc.get("source") or "", loc.get("scope") or ""),
                             s.get("quote") or ""])

    for name in ("formulas.json", "symbols.json", "derivations.json", "numeric_checks.json",
                 "formula_check.json", "quote_check.json", "corpus.txt", "quotes.json"):
        src = os.path.join(work, name)
        if os.path.isfile(src):
            shutil.copyfile(src, os.path.join(out, name))

    # ---------------------------------------------------------------- honest TODO list
    print("\n仍需人工/模型补齐：")
    if unknown:
        print("  - 符号缺定义/单位: %s" % ", ".join(unknown))
    for f in insufficient:
        print("  - insufficient_evidence: %s（%s）%s" % (f["id"], f["label"], f.get("reason")))
    for item in not_checkable:
        print("  - 数值 not_checkable: %s（缺输入: %s）" % (
            item["formula_id"], ", ".join(item["missing_inputs"]) or "none"))
    if derivations:
        print("  - 推导待补: %s（当前仅原式重述）" % ", ".join(d["formula_id"] for d in derivations))
    print("status=%s -> %s" % (status, os.path.join(out, "result.json")))
    return 0


if __name__ == "__main__":
    sys.exit(main())
