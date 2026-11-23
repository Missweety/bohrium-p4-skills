#!/usr/bin/env python3
"""kernel.py - evidence-first execution kernel for the academic-writing skill.

Subcommands (stdlib only, no network):
  init     read case.json, emit contract.json + section_template.json + case.raw.json
  index    discover materials, extract text, emit evidence.json / corpus.txt / facts.json
  build    render work/manuscript.md + source_map.json + todo.md from work/draft.json
  verify   check numbers and citations in a draft against the indexed materials
  emit     merge draft + contract into result.json and copy the editable artifacts
  check    strict delivery gate over an output directory

Design rule: never fabricate. Missing data is written as an explicit placeholder plus
an uncertainty record; it is never filled in from memory or from a topic label.
"""
import argparse
import csv
import hashlib
import json
import os
import re
import sys
import zipfile

DEFAULT_CONTRACT = {
    "artifact_path": "manuscript.md",
    "artifact_format": "md",
    "source_map": [],
    "changes": [],
    "uncertainty": [],
    "limits": "",
    "self_check": {},
    "conflicts": [],
    "todo": [],
    "references": [],
    "figures": [],
    "tables": [],
}
REQUIRED_RESULT_FIELDS = (
    "case_id", "status", "artifact_path", "source_map", "changes",
    "uncertainty", "limits", "self_check",
)
STATUSES = {"ok", "success", "partial", "blocked", "refused"}
UNREADABLE_PREFIX = "[unreadable:"

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
SKIP_DIRS = {"work", "output", "__pycache__", ".git", "node_modules", ".trae"}
SKIP_FILES = {"case.json", "task.md", "SKILL.md", "GITHUB_URL.txt"}

NUM_RE = re.compile(r"(?<![A-Za-z0-9_])[-+]?\d+(?:[.,]\d+)*(?:\s?[%‰])?")
UNIT_RE = re.compile(r"^\s*(%|‰|mg|kg|μg|µg|g|mL|ml|L|μM|µM|mM|nM|nm|mm|cm|km|m|ms|s|min|h|d|"
                     r"°C|K|Pa|kPa|MPa|M|mol|mmol|μmol|µmol|bp|kb|Da|kDa|rpm|Hz|kHz|MHz|V|mA|W)\b")
CITE_RE = re.compile(
    r"(\[[0-9][0-9,\s\-–]*\]|\\cite\{[^}]+\}"
    r"|\([A-Z][A-Za-z\-]+(?:\s(?:et al\.|and\s[A-Z][A-Za-z\-]+))?,?\s?(?:19|20)\d{2}[a-z]?\))"
)
STRUCT_RE = re.compile(
    r"(?:Figure|Fig\.|Table|图|表|Eq\.?|公式|§|#)\s*([0-9]+(?:[.\-][0-9]+)*)", re.I)
PLACEHOLDER_RE = re.compile(r"(?:【待补[:：]\s*([^】]*)】|\[TBD[:：]\s*([^\]]*)\])", re.I)

SECTION_ALIASES = [
    ("Abstract", ["abstract", "摘要"]),
    ("Introduction", ["introduction", "引言", "绪论", "前言"]),
    ("Methods", ["methods", "method", "materials and methods", "材料与方法", "方法", "实验方法"]),
    ("Results", ["results", "结果"]),
    ("Discussion", ["discussion", "讨论"]),
    ("Conclusion", ["conclusion", "conclusions", "结论", "总结"]),
    ("References", ["references", "bibliography", "参考文献"]),
    ("Data availability", ["data availability", "数据可得性", "数据可用性"]),
    ("Funding", ["funding", "基金", "资助"]),
    ("Conflict of interest", ["conflict of interest", "competing interests", "利益冲突"]),
    ("Ethics statement", ["ethics", "伦理"]),
]
SECTION_MIN_WORDS = {
    "Abstract": 80, "Introduction": 120, "Methods": 120, "Results": 120,
    "Discussion": 120, "Conclusion": 40, "References": 0,
}


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
            return "\n".join(rows)
    except Exception as exc:  # noqa: BLE001
        return "%s xlsx unreadable: %s]" % (UNREADABLE_PREFIX, exc)


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
        text = "\n".join((p.extract_text() or "") for p in PdfReader(path).pages)
        if text.strip():
            return text
    except Exception:  # noqa: BLE001
        pass
    return "%s pdf has no readable text layer; render pages and mark quoted content as unverified]" % UNREADABLE_PREFIX


def extract(path):
    """Return extracted text. Only a leading [unreadable: marker marks failure."""
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
        if ext in {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".svg"}:
            return "[asset: image file; inspect visually and record dimensions/content; text not extracted]"
        return "%s unsupported type %s; do not guess its content]" % (UNREADABLE_PREFIX, ext)
    except Exception as exc:  # noqa: BLE001
        return "%s %s: %s]" % (UNREADABLE_PREFIX, ext, exc)


def locate(snippet, corpus, source):
    idx = corpus.find(snippet[:80])
    if idx < 0:
        return None
    line = corpus.count("\n", 0, idx) + 1
    return {"source": source, "line": line, "offset": idx}


# ---------------------------------------------------------------- discovery
def _resolve_materials(case, case_path):
    base = os.path.dirname(os.path.abspath(case_path))
    roots = []
    declared = pick(case, "materials")
    if isinstance(declared, str):
        declared = [declared]
    if isinstance(declared, list):
        for item in declared:
            if isinstance(item, dict):
                item = item.get("path") or item.get("name")
            if not isinstance(item, str):
                continue
            p = item if os.path.isabs(item) else os.path.join(base, item)
            if os.path.exists(p):
                roots.append(p)
    for name in ("materials", "input", "data", "attachments", "supplementary"):
        p = os.path.join(base, name)
        if os.path.isdir(p):
            roots.append(p)
    if not roots and os.path.isdir(base):
        roots = [base]
    seen, out = set(), []
    for r in roots:
        r = os.path.abspath(r)
        if r not in seen:
            seen.add(r)
            out.append(r)
    return out


def _walk_files(roots):
    seen = set()
    for root in roots:
        if os.path.isfile(root):
            yield root
            continue
        for dirpath, dirnames, names in os.walk(root):
            dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS and not d.startswith(".")]
            for n in sorted(names):
                if n.startswith(".") or n in SKIP_FILES:
                    continue
                p = os.path.join(dirpath, n)
                if p in seen or not os.path.isfile(p):
                    continue
                seen.add(p)
                yield p


def _safe_name(name):
    return re.sub(r"[^A-Za-z0-9._-]+", "_", os.path.basename(str(name)))[:80] or "material.txt"


def materialize_inline(case, workdir):
    """Runtime inputs are sometimes embedded in case.json rather than mounted as files."""
    outs = []
    inline = pick(case, "source_text")
    if isinstance(inline, str) and inline.strip():
        p = os.path.join(workdir, "inline", "source_text.md")
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w", encoding="utf-8") as fh:
            fh.write(inline)
        outs.append(p)
    declared = case.get("materials")
    if isinstance(declared, list):
        for i, item in enumerate(declared, start=1):
            if not isinstance(item, dict):
                continue
            content = item.get("content") or item.get("text")
            if not isinstance(content, str) or not content.strip():
                continue
            p = os.path.join(workdir, "inline", _safe_name(item.get("name") or "material_%d.txt" % i))
            os.makedirs(os.path.dirname(p), exist_ok=True)
            with open(p, "w", encoding="utf-8") as fh:
                fh.write(content)
            outs.append(p)
    return outs


# ---------------------------------------------------------------- fact candidates
def _unit_of(token):
    m = re.match(r"^\s*[-+]?\d+(?:[.,]\d+)*\s*(%|‰|[A-Za-zμµ°]+)?", token)
    return (m.group(1) or "") if m else ""


def _csv_facts(path, text):
    ext = os.path.splitext(path)[1].lower()
    delim = "," if ext == ".csv" else "\t"
    try:
        rows = list(csv.reader(text.splitlines(), delimiter=delim))
    except Exception:  # noqa: BLE001
        return []
    if len(rows) < 2:
        return []
    header = [h.strip() for h in rows[0]]
    facts = []
    for r_i, row in enumerate(rows[1:], start=2):
        for c_i, cell in enumerate(row):
            cell = cell.strip()
            if not cell or not NUM_RE.search(cell):
                continue
            value = NUM_RE.search(cell).group(0).strip()
            col = header[c_i] if c_i < len(header) else "col%d" % (c_i + 1)
            facts.append({
                "value": value,
                "unit": _unit_of(value),
                "source_path": path,
                "locator": "row %d, col %s" % (r_i, col),
                "context": " | ".join("%s=%s" % (header[i], row[i]) for i in range(min(len(header), len(row))) if row[i].strip())[:200],
            })
    return facts


def _line_facts(path, text):
    facts = []
    for i, line in enumerate(text.splitlines(), start=1):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        toks = NUM_RE.findall(stripped)
        if not toks:
            continue
        for tok in dict.fromkeys(toks):
            facts.append({
                "value": tok,
                "unit": _unit_of(tok),
                "source_path": path,
                "locator": "line %d" % i,
                "context": stripped[:200],
            })
    return facts


def build_facts(path, text, cap=4000):
    ext = os.path.splitext(path)[1].lower()
    if ext in {".csv", ".tsv", ".xlsx"}:
        facts = _csv_facts(path, text)
        if facts:
            return facts
    return _line_facts(path, text)


# ---------------------------------------------------------------- bib parsing
def parse_bib(text):
    refs = []
    for block in re.split(r"(?=@\w+\s*\{)", text):
        m = re.match(r"@\w+\s*\{\s*([^,\s]+)\s*,", block)
        if not m:
            continue
        key = m.group(1)
        fields = {k.lower(): v.strip() for k, v in re.findall(r"(\w+)\s*=\s*[\{\"]([^\}\"]*)[\}\"]", block)}
        refs.append({
            "key": key,
            "authors": fields.get("author", ""),
            "year": fields.get("year", ""),
            "title": fields.get("title", ""),
            "venue": fields.get("journal") or fields.get("booktitle") or "",
            "doi": fields.get("doi", ""),
            "source_path": "",
            "locator": "@%s" % key,
        })
    return refs


# ---------------------------------------------------------------- section template
def detect_template(task_text, genre, language):
    text = (task_text or "").lower()
    found = []
    for name, aliases in SECTION_ALIASES:
        if any(a.lower() in text for a in aliases):
            found.append(name)
    if language and str(language).lower().startswith("zh"):
        names = {
            "Abstract": "摘要", "Introduction": "引言", "Methods": "方法", "Results": "结果",
            "Discussion": "讨论", "Conclusion": "结论", "References": "参考文献",
            "Data availability": "数据可得性", "Funding": "基金", "Conflict of interest": "利益冲突",
            "Ethics statement": "伦理声明",
        }
    else:
        names = {}
    sections = []
    for name in found:
        sections.append({
            "name": names.get(name, name),
            "canonical": name,
            "aliases": [name] + [a for a in dict(SECTION_ALIASES)[name]],
            "min_words": SECTION_MIN_WORDS.get(name, 60),
            "required": True,
        })
    if not sections:
        for name, _ in SECTION_ALIASES[:7]:
            sections.append({
                "name": names.get(name, name),
                "canonical": name,
                "aliases": [name] + list(dict(SECTION_ALIASES)[name]),
                "min_words": SECTION_MIN_WORDS.get(name, 60),
                "required": False,
            })
        return {"source": "skill_default_advisory", "genre": genre, "sections": sections,
                "declarations": ["data_availability"],
                "require_references": False, "require_doi": False,
                "note": "task.md did not name sections; set required=true for the sections it asks for"}
    return {"source": "task_detected", "genre": genre, "sections": sections,
            "declarations": ["data_availability"] if "Data availability" in found else [],
            "require_references": "References" in found or "references" in text,
            "require_doi": "doi" in text}


# ---------------------------------------------------------------- commands
def cmd_init(a):
    case_path = find_case_file(a.case)
    out = a.out
    if not case_path:
        dump({"status": "blocked", "missing": "case.json not found",
              "searched": ["/input/case.json", "case.json", "/app/input/case.json"]},
             os.path.join(out, "contract.json"))
        print("blocked: case.json not found")
        return 1
    case = load_json(case_path)
    norm = {k: pick(case, k) for k in ALIASES}
    inline = materialize_inline(case, out)
    contract = norm.get("output_contract") or {}
    if isinstance(contract, list):
        contract = {"fields": contract}
    task = norm.get("task") or ""
    task_md_text = ""
    task_path = os.path.join(os.path.dirname(os.path.abspath(case_path)), "task.md")
    if os.path.exists(task_path):
        task_md_text = open(task_path, encoding="utf-8", errors="replace").read()
    tpl = detect_template(task, norm.get("genre"), norm.get("language"))
    if tpl.get("source") == "skill_default_advisory" and task_md_text.strip():
        broader = detect_template(task + "\n" + task_md_text, norm.get("genre"), norm.get("language"))
        if broader.get("source") == "task_detected":
            for sec in broader.get("sections", []):
                sec["required"] = False
            broader["source"] = "task_md_advisory"
            broader["note"] = ("sections detected from the full brief; set required=true only for the "
                               "sections the actual case instruction asks for")
            tpl = broader
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
        "default_contract": DEFAULT_CONTRACT,
        "materials_discovered": _resolve_materials(case, case_path) + inline,
    }
    dump(result, os.path.join(out, "contract.json"))
    dump(case, os.path.join(out, "case.raw.json"))
    tpl_path = os.path.join(out, "section_template.json")
    if not os.path.exists(tpl_path) or a.force_template:
        dump(tpl, tpl_path)
    else:
        print("keep existing %s (pass --force-template to regenerate)" % tpl_path)
    if not contract:
        print("warn: case.json has no output_contract; skill default contract will be used")
    print("case_id=%s keys=%s materials=%d"
          % (result["case_id"], ",".join(result["raw_keys"]), len(result["materials_discovered"])))
    return 0


def cmd_index(a):
    case_path = find_case_file(a.case)
    roots = []
    inline = []
    if case_path:
        case = load_json(case_path)
        inline = materialize_inline(case, a.out)
    if a.materials:
        roots = [p for p in a.materials if os.path.exists(p)]
    elif case_path:
        roots = _resolve_materials(load_json(case_path), case_path)
    roots += inline
    if not roots:
        roots = [p for p in ("/input/materials", "/input") if os.path.isdir(p)]
    if not roots:
        print("blocked: no material path found; pass --materials or put source_text in case.json")
        return 1

    items, corpus, facts, refs, skipped = [], [], [], [], []
    for p in _walk_files(roots):
        text = extract(p)
        readable = not text.startswith(UNREADABLE_PREFIX)
        size = os.path.getsize(p)
        items.append({
            "path": p,
            "bytes": size,
            "chars": len(text),
            "readable": readable,
            "ext": os.path.splitext(p)[1].lower(),
            "sha1": hashlib.sha1(open(p, "rb").read()).hexdigest(),
        })
        if not readable:
            skipped.append(p)
            continue
        corpus.append("===== FILE: %s =====\n%s" % (p, text))
        if os.path.splitext(p)[1].lower() == ".bib":
            refs.extend(parse_bib(text))
        else:
            facts.extend(build_facts(p, text))
    if len(facts) > a.fact_cap:
        facts = facts[:a.fact_cap]
    for i, f in enumerate(facts, start=1):
        f["candidate_id"] = "C%04d" % i
    os.makedirs(a.out, exist_ok=True)
    if not items:
        dump({"files": [], "total_chars": 0, "readable_files": [], "unreadable": [],
              "facts_total": 0, "blocked": "no files found under %s" % roots},
             os.path.join(a.out, "evidence.json"))
        print("blocked: no files found under %s; check the --materials path" % roots)
        return 1
    corpus_text = "\n\n".join(corpus)
    dump({"files": items, "total_chars": sum(i["chars"] for i in items),
          "readable_files": [i["path"] for i in items if i["readable"]],
          "unreadable": skipped,
          "facts_total": len(facts), "fact_cap": a.fact_cap},
         os.path.join(a.out, "evidence.json"))
    dump(facts, os.path.join(a.out, "facts.json"))
    auto = os.path.join(a.out, "references.auto.json")
    if refs:
        dump(refs, auto)
    elif os.path.exists(auto):
        os.remove(auto)
    with open(os.path.join(a.out, "corpus.txt"), "w", encoding="utf-8") as fh:
        fh.write(corpus_text)
    for i in items:
        print("%-8s %8d  %s" % ("ok" if i["readable"] else "UNREAD", i["chars"], i["path"]))
    print("facts=%d references_auto=%d unreadable=%d" % (len(facts), len(refs), len(skipped)))
    return 0


# ---------------------------------------------------------------- verification
def _norm_num(tok):
    return tok.replace(",", " ").strip()


def _num_in_text(tok, text):
    """Token-aware membership: 12.4 is not satisfied by 12.45; 12.4% matches 12.4."""
    core = _norm_num(tok).rstrip("%‰")
    if not core:
        return False
    blob = _norm_num(text)
    for m in re.finditer(re.escape(core), blob):
        before = blob[m.start() - 1] if m.start() > 0 else ""
        after = blob[m.end()] if m.end() < len(blob) else ""
        if not before.isdigit() and not after.isdigit():
            return True
    return False


def _load_refs(evidence_dir, plan_path=""):
    refs = []
    for name in ("references.json", "references.auto.json"):
        p = os.path.join(evidence_dir, name)
        if os.path.exists(p):
            data = load_json(p)
            if isinstance(data, list):
                refs.extend(data)
    if plan_path and os.path.exists(plan_path):
        try:
            plan = load_json(plan_path)
            refs.extend(plan.get("references") or [])
        except Exception:  # noqa: BLE001
            pass
    return refs


def _citation_tokens(text):
    return list(dict.fromkeys(m.group(0) for m in CITE_RE.finditer(text)))


def _expand_bracket(tok):
    inner = tok.strip("[]")
    out = []
    for part in re.split(r"[,;]", inner):
        part = part.strip()
        m = re.match(r"^(\d+)\s*[-–]\s*(\d+)$", part)
        if m:
            lo, hi = int(m.group(1)), int(m.group(2))
            if 0 < hi - lo <= 50:
                out.extend(range(lo, hi + 1))
        elif part.isdigit():
            out.append(int(part))
    return out


def _author_year_hit(tok, corpus, refs):
    inner = tok.strip("()")
    m = re.match(r"([A-Z][A-Za-z\-]+).*?((?:19|20)\d{2})", inner)
    if not m:
        return False
    surname, year = m.group(1).lower(), m.group(2)
    if re.search(re.escape(surname) + r"[^\n]{0,60}" + re.escape(year), corpus, re.I):
        return True
    for r in refs:
        authors = str(r.get("authors") or r.get("author") or "")
        if surname in authors.lower() and str(r.get("year") or "") == year:
            return True
    return False


def cmd_verify(a):
    corpus = open(os.path.join(a.evidence_dir, "corpus.txt"), encoding="utf-8").read()
    ev = load_json(os.path.join(a.evidence_dir, "evidence.json"))
    draft = open(a.text, encoding="utf-8").read()
    refs = _load_refs(a.evidence_dir, a.plan)
    ref_keys = {str(r.get("key")) for r in refs if r.get("key")}
    numbered_refs = [r for r in refs if str(r.get("index", "")).isdigit()]
    max_ref = max([int(r["index"]) for r in numbered_refs], default=len(refs))

    structural = set(STRUCT_RE.findall(draft))
    numbers, unsupported, structural_nums = [], [], []
    for m in NUM_RE.finditer(draft):
        tok = m.group(0).strip()
        if not tok:
            continue
        numbers.append(tok)
        bare = _norm_num(tok).rstrip("%‰")
        if bare in structural:
            structural_nums.append(tok)
        elif not _num_in_text(tok, corpus):
            unsupported.append(tok)

    unresolved = []
    for c in _citation_tokens(draft):
        if c.startswith("\\cite"):
            key = c[len("\\cite{"):-1].strip()
            if key not in ref_keys and key not in corpus:
                unresolved.append({"citation": c, "reason": "key not in bib/reference registry"})
        elif c.startswith("["):
            idxs = _expand_bracket(c)
            if refs:
                ok = bool(idxs) and max(idxs) <= max_ref
                if not ok:
                    unresolved.append({"citation": c, "reason": "index exceeds %d reference entries" % max_ref})
            else:
                exact = c.strip()
                ok = exact in corpus or (bool(idxs) and all(
                    re.search(r"\[\s*%d\s*\]" % n, corpus) for n in idxs))
                if not ok:
                    unresolved.append({"citation": c, "reason": "no matching bracketed reference in materials"})
        else:
            if not _author_year_hit(c, corpus, refs):
                unresolved.append({"citation": c, "reason": "author-year not found in materials/references"})

    report = {
        "draft": os.path.abspath(a.text),
        "numbers_total": len(numbers),
        "numbers_unique": len(set(numbers)),
        "structural_numbers": sorted(set(structural_nums))[:100],
        "unsupported_numbers": list(dict.fromkeys(unsupported))[:200],
        "citations_unique": len(_citation_tokens(draft)),
        "citations_unresolved": unresolved[:200],
        "references_loaded": len(refs),
        "numbered_reference_max": max_ref,
        "unreadable_sources": ev.get("unreadable", []),
        "verdict": "pass" if not unsupported and not unresolved else "review",
    }
    dump(report, os.path.join(a.out, "claims.json"))
    print("verdict=%s unsupported_numbers=%d citations_unresolved=%d"
          % (report["verdict"], len(report["unsupported_numbers"]), len(unresolved)))
    for n in report["unsupported_numbers"][:20]:
        print("  ? number not in sources:", n)
    for c in unresolved[:10]:
        print("  ? citation:", c["citation"], "-", c["reason"])
    return 0


# ---------------------------------------------------------------- rendering
def _split_words(text):
    return len(re.findall(r"[A-Za-z0-9\u4e00-\u9fff]+", text or ""))


def _render_reference(entry, style, index):
    authors = str(entry.get("authors") or entry.get("author") or "").strip()
    year = str(entry.get("year") or "").strip()
    title = str(entry.get("title") or "").strip()
    venue = str(entry.get("venue") or entry.get("journal") or "").strip()
    volume = str(entry.get("volume") or "").strip()
    pages = str(entry.get("pages") or "").strip()
    doi = str(entry.get("doi") or "").strip()
    body = ", ".join(x for x in (authors, year) if x)
    if title:
        body += (". " if body else "") + title
    if venue:
        body += (". " if body else "") + venue
    if volume:
        body += ", " + volume
    if pages:
        body += ": " + pages
    if doi:
        body += ". doi:" + doi
    body = body.rstrip(".")
    if style == "numbered":
        return "[%d] %s." % (index, body)
    return body + "."


def _detect_style(text, plan):
    if plan.get("reference_style") in ("numbered", "author-year"):
        return plan["reference_style"]
    return "author-year" if re.search(r"\([A-Z][A-Za-z\-]+,?\s?(?:et al\.,?\s?)?(?:19|20)\d{2}\)", text) else "numbered"


def _render_manuscript(plan):
    lines = []
    if plan.get("title"):
        lines += ["# %s" % plan["title"], ""]
    figures = plan.get("figures") or []
    tables = plan.get("tables") or []
    placed_figs, placed_tabs = set(), set()
    for section in plan.get("sections") or []:
        heading = section.get("heading") or section.get("name") or ""
        level = int(section.get("level") or 2)
        if heading:
            lines += ["%s %s" % ("#" * max(1, min(6, level)), heading), ""]
        for para in section.get("paragraphs") or []:
            text = para if isinstance(para, str) else str(para.get("text") or "")
            if not text.strip():
                continue
            if isinstance(para, dict) and para.get("placeholder"):
                text = "【待补：%s】%s" % (para["placeholder"], text)
            lines += [text.strip(), ""]
        body = "\n".join(lines)
        for i, fig in enumerate(figures):
            if i in placed_figs:
                continue
            label = str(fig.get("label") or "Figure %d" % (i + 1))
            if fig.get("section") and str(fig["section"]).lower() == heading.lower():
                lines += ["%s. %s" % (label, str(fig.get("caption") or "").strip()), ""]
                placed_figs.add(i)
            elif not fig.get("section") and re.search(re.escape(label) + r"\b", body):
                lines += ["%s. %s" % (label, str(fig.get("caption") or "").strip()), ""]
                placed_figs.add(i)
        for i, tab in enumerate(tables):
            if i in placed_tabs:
                continue
            label = str(tab.get("label") or "Table %d" % (i + 1))
            if tab.get("section") and str(tab["section"]).lower() == heading.lower():
                lines += ["%s. %s" % (label, str(tab.get("caption") or "").strip()), ""]
                placed_tabs.add(i)
    remaining_figs = [f for i, f in enumerate(figures) if i not in placed_figs]
    remaining_tabs = [t for i, t in enumerate(tables) if i not in placed_tabs]
    if remaining_figs:
        lines += ["## Figures", ""]
        for i, fig in enumerate(figures):
            if i in placed_figs:
                continue
            label = str(fig.get("label") or "Figure %d" % (i + 1))
            lines += ["%s. %s" % (label, str(fig.get("caption") or "").strip()), ""]
    if remaining_tabs:
        lines += ["## Tables", ""]
        for i, tab in enumerate(tables):
            if i in placed_tabs:
                continue
            label = str(tab.get("label") or "Table %d" % (i + 1))
            lines += ["%s. %s" % (label, str(tab.get("caption") or "").strip()), ""]

    headings = [str(s.get("heading") or s.get("name") or "").lower() for s in plan.get("sections") or []]
    refs = plan.get("references") or []
    if refs and not any(h in ("references", "参考文献", "bibliography") for h in headings):
        style = _detect_style("\n".join(lines), plan)
        lines += ["## References", ""]
        for i, r in enumerate(refs, start=1):
            lines += [_render_reference(r, style, i), ""]
    decl = plan.get("declarations") or {}
    decl_titles = {
        "data_availability": "Data availability", "funding": "Funding",
        "conflict_of_interest": "Conflict of interest", "ethics": "Ethics statement",
    }
    for key, title in decl_titles.items():
        val = str(decl.get(key) or "").strip()
        if val and title.lower() not in headings:
            lines += ["## %s" % title, "", val, ""]
    return "\n".join(lines).rstrip() + "\n"


def _write_todo(plan, out_dir):
    uncertainty = plan.get("uncertainty") or []
    conflicts = plan.get("conflicts") or []
    todo = plan.get("todo") or []
    lines = ["# 待补 / 待核清单", "",
             "本文件由 scripts/kernel.py build 生成。以下条目未在材料中得到确认，禁止当作已核实结论。", ""]
    if not uncertainty and not conflicts and not todo:
        lines.append("- 无。")
    for item in conflicts:
        lines.append("- [冲突] %s：%s（%s）" % (item.get("where", "-"), item.get("what", "-"), item.get("why", "")))
    for item in uncertainty:
        lines.append("- [%s] %s：%s（%s）" % (item.get("type", "uncertain"),
                                             item.get("where", "-"), item.get("what", "-"), item.get("why", "")))
    for item in todo:
        if isinstance(item, dict):
            lines.append("- [待核] %s：%s" % (item.get("where", "-"), item.get("what", "-")))
        else:
            lines.append("- [待核] %s" % item)
    with open(os.path.join(out_dir, "todo.md"), "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")


def cmd_build(a):
    plan = load_json(a.draft)
    text = _render_manuscript(plan)
    os.makedirs(a.out, exist_ok=True)
    with open(os.path.join(a.out, "manuscript.md"), "w", encoding="utf-8") as fh:
        fh.write(text)
    source_map = plan.get("source_map") or []
    dump({"source_map": source_map, "entries": len(source_map)}, os.path.join(a.out, "source_map.json"))
    rows = ["claim,value,source_path,locator,fact_id"]
    for e in source_map:
        rows.append(",".join('"%s"' % str(e.get(k, "")).replace('"', '""')
                             for k in ("claim", "value", "source_path", "locator", "fact_id")))
    with open(os.path.join(a.out, "source_map.csv"), "w", encoding="utf-8") as fh:
        fh.write("\n".join(rows) + "\n")
    _write_todo(plan, a.out)
    print("rendered manuscript.md chars=%d sections=%d source_map=%d"
          % (len(text), len(plan.get("sections") or []), len(source_map)))
    return 0


# ---------------------------------------------------------------- emit / check
def _contract_of(contract_path):
    if not os.path.exists(contract_path):
        return {}
    data = load_json(contract_path)
    contract = data.get("contract") or {}
    return contract if isinstance(contract, dict) else {}


def cmd_emit(a):
    contract_path = os.path.join(a.contract_dir, "contract.json") \
        if os.path.isdir(a.contract_dir) else a.contract_dir
    contract = _contract_of(contract_path)
    draft = load_json(a.draft)
    fields = draft.get("fields") if isinstance(draft.get("fields"), dict) else {}

    result = {}
    for key in REQUIRED_RESULT_FIELDS:
        result[key] = DEFAULT_CONTRACT.get(key)
    for key, default in DEFAULT_CONTRACT.items():
        if result.get(key) is None:
            result[key] = default
    if os.path.exists(contract_path):
        result["case_id"] = load_json(contract_path).get("case_id")
    result["case_id"] = draft.get("case_id") or result.get("case_id")
    result["status"] = draft.get("status", "partial")

    for key, value in fields.items():
        if value is not None:
            result[key] = value
    for key, value in draft.items():
        if key in ("fields", "artifacts", "sections"):
            continue
        if value is not None:
            result[key] = value

    # artifacts and their declared paths
    artifacts = draft.get("artifacts") if isinstance(draft.get("artifacts"), dict) else {}
    if not artifacts and os.path.exists(os.path.join(a.work_dir, "manuscript.md")):
        artifacts["manuscript.md"] = open(os.path.join(a.work_dir, "manuscript.md"), encoding="utf-8").read()
    if "manuscript.md" not in artifacts and draft.get("sections"):
        artifacts["manuscript.md"] = _render_manuscript(draft)
    if not artifacts and result.get("status") in ("blocked", "refused"):
        artifacts["manuscript.md"] = (
            "# 无法完成\n\nstatus: %s\n\n%s\n"
            % (result.get("status"),
               str(result.get("limits") or "材料不足，未生成稿件。请补齐材料后重跑。")))
    result.setdefault("artifact_path", "manuscript.md")
    if not result.get("artifact_format"):
        result["artifact_format"] = os.path.splitext(str(result.get("artifact_path")))[1].lstrip(".") or "md"

    # source map: draft wins, else build output
    if not result.get("source_map"):
        sm = os.path.join(a.work_dir, "source_map.json")
        if os.path.exists(sm):
            result["source_map"] = load_json(sm).get("source_map", [])
    for key in ("source_map", "changes", "uncertainty", "conflicts", "todo", "references", "figures", "tables"):
        if result.get(key) is None:
            result[key] = []
    if result.get("limits") is None:
        result["limits"] = ""

    # audit summary and hard stop on fail
    if a.audit and os.path.exists(a.audit):
        audit = load_json(a.audit)
        result["self_check"] = {
            "audit_verdict": audit.get("verdict"),
            "sections_missing": audit.get("sections_missing", []),
            "sections_out_of_order": audit.get("sections_out_of_order", []),
            "numbers_unbound": audit.get("numbers_unbound", []),
            "citations_unresolved": audit.get("citations_unresolved", []),
            "conflicts": audit.get("conflicts", []),
            "placeholders_unregistered": audit.get("placeholders_unregistered", []),
            "figure_problems": audit.get("figure_problems", []),
            "declarations_missing": audit.get("declarations_missing", []),
            "reference_problems": audit.get("reference_problems", []),
        }
        if audit.get("todo"):
            result["todo"] = audit["todo"]
        if audit.get("conflicts"):
            result["conflicts"] = audit["conflicts"]
        if audit.get("verdict") == "fail":
            result["status"] = "partial"
            result["limits"] = (str(result.get("limits") or "") +
                                " | audit failed: see self_check").strip(" |")
    if a.source_map and os.path.exists(a.source_map):
        result["source_map"] = load_json(a.source_map).get("source_map", result["source_map"])
    if not result.get("self_check"):
        result["self_check"] = {"audit_verdict": "not_run"}

    os.makedirs(a.out, exist_ok=True)
    dump(result, os.path.join(a.out, "result.json"))
    for name, body in artifacts.items():
        p = os.path.join(a.out, name)
        os.makedirs(os.path.dirname(p) or a.out, exist_ok=True)
        with open(p, "w", encoding="utf-8") as fh:
            fh.write(body)
    # copy companion artifacts so reviewers can re-check without the work dir
    for name in ("source_map.json", "source_map.csv", "todo.md", "audit.json", "claims.json", "facts.json"):
        src = os.path.join(a.work_dir, name)
        if os.path.exists(src) and not os.path.exists(os.path.join(a.out, name)):
            data = open(src, "rb").read()
            with open(os.path.join(a.out, name), "wb") as fh:
                fh.write(data)

    missing = [k for k in contract if result.get(k) is None]
    print("result.json written; contract_fields=%d missing_contract_fields=%s"
          % (len(contract), missing or "none"))
    return 1 if missing else 0


def cmd_check(a):
    problems, warns = [], []
    out = a.out
    rp = os.path.join(out, "result.json")
    if not os.path.exists(rp):
        print("FAIL\n - result.json missing")
        return 1
    res = load_json(rp)
    for k in REQUIRED_RESULT_FIELDS:
        if res.get(k) in (None, ""):
            if k == "limits" and res.get("status") not in ("partial", "blocked"):
                continue
            problems.append("result.json missing %s" % k)
    if res.get("status") not in STATUSES:
        problems.append("status must be one of %s" % "/".join(sorted(STATUSES)))
    if res.get("status") in ("partial", "blocked") and not str(res.get("limits") or "").strip():
        problems.append("status=%s but limits is empty" % res["status"])
    for key in ("source_map", "changes", "uncertainty"):
        if not isinstance(res.get(key), list):
            problems.append("%s must be a list" % key)
    for i, entry in enumerate(res.get("source_map") or []):
        if not isinstance(entry, dict):
            problems.append("source_map[%d] is not an object" % i)
            continue
        for k in ("claim", "value", "source_path", "locator"):
            if not str(entry.get(k, "")).strip():
                problems.append("source_map[%d] missing %s" % (i, k))
        sp = str(entry.get("source_path") or "")
        if os.path.isabs(sp):
            if not os.path.exists(sp):
                warns.append("source_map[%d] source_path not found now: %s" % (i, sp))
        elif sp and not os.path.exists(sp) and not os.path.exists(os.path.join(out, sp)):
            warns.append("source_map[%d] relative source_path unresolved: %s" % (i, sp))

    artifact = str(res.get("artifact_path") or "")
    ap = os.path.join(out, artifact) if artifact else ""
    if not artifact:
        problems.append("artifact_path empty")
    elif not os.path.exists(ap):
        problems.append("artifact missing: %s" % artifact)
    elif os.path.getsize(ap) < 32:
        problems.append("artifact is empty/truncated: %s" % artifact)
    if not os.path.exists(os.path.join(out, "manuscript.md")):
        problems.append("manuscript.md missing (the editable deliverable)")
    audit_path = os.path.join(out, "audit.json")
    if os.path.exists(audit_path):
        verdict = load_json(audit_path).get("verdict")
        if verdict == "fail" and res.get("status") == "ok":
            problems.append("audit verdict=fail but status=ok")
    elif res.get("status") in ("ok", "success", "partial"):
        problems.append("audit.json missing")

    if not isinstance(res.get("self_check"), dict) or not res["self_check"].get("audit_verdict"):
        problems.append("self_check.audit_verdict missing")

    cp = os.path.join(a.contract_dir, "contract.json") if a.contract_dir else ""
    if cp and os.path.exists(cp):
        for name in _contract_of(cp):
            if name not in res or res.get(name) is None:
                problems.append("result.json missing contract field %s" % name)
            elif name != "limits" and isinstance(res.get(name), str) and not res[name].strip():
                problems.append("result.json empty contract field %s" % name)
    elif a.contract_dir:
        warns.append("contract.json not found; skipped contract-field check")

    print("PASS" if not problems else "FAIL")
    for p in problems:
        print(" -", p)
    for w in warns:
        print(" ~", w)
    return 0 if not problems else 1


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("init"); p.add_argument("--case"); p.add_argument("--out", default="work")
    p.add_argument("--force-template", action="store_true"); p.set_defaults(fn=cmd_init)
    p = sub.add_parser("index"); p.add_argument("--materials", nargs="*"); p.add_argument("--case")
    p.add_argument("--out", default="work"); p.add_argument("--fact-cap", type=int, default=4000)
    p.set_defaults(fn=cmd_index)
    p = sub.add_parser("build"); p.add_argument("--draft", required=True); p.add_argument("--out", default="work")
    p.set_defaults(fn=cmd_build)
    p = sub.add_parser("verify"); p.add_argument("--text", required=True)
    p.add_argument("--evidence-dir", default="work"); p.add_argument("--plan", default="")
    p.add_argument("--out", default="work"); p.set_defaults(fn=cmd_verify)
    p = sub.add_parser("emit"); p.add_argument("--draft", required=True)
    p.add_argument("--contract-dir", default="work"); p.add_argument("--work-dir", default="work")
    p.add_argument("--audit", default=""); p.add_argument("--source-map", default="")
    p.add_argument("--out", default="/app/output"); p.set_defaults(fn=cmd_emit)
    p = sub.add_parser("check"); p.add_argument("--out", default="/app/output")
    p.add_argument("--contract-dir", default="work"); p.set_defaults(fn=cmd_check)

    a = ap.parse_args()
    return a.fn(a)


if __name__ == "__main__":
    sys.exit(main())
