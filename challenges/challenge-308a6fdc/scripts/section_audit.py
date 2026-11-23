#!/usr/bin/env python3
"""section_audit.py - offline, deterministic audit of an academic manuscript draft.

Checks (fail-closed on evidence problems, never fills gaps):
  sections      required headings present and in template order; min word counts
  numbers       every body number is bound to source_map values or the material corpus
  citations     inline citations resolve to a reference entry / bib key / material text
  references    entries have author/year/title/venue; uncited entries are flagged
  figures       every Figure/Table N referenced has a caption, captions are cited
  placeholders  every 【待补：...】/[TBD: ...] has a matching uncertainty record
  conflicts     same claim with different values is kept and must be registered
  declarations  required data/funding/COI/ethics statements are present
  honesty       absolute claims (证明/显著优于/proves) without a citation are flagged

Usage:
  python scripts/section_audit.py --draft work/manuscript.md \
      --map work/source_map.json --template work/section_template.json \
      --corpus work/corpus.txt --plan work/draft.json \
      --references work/references.json work/references.auto.json \
      --todo work/todo.md --out work/audit.json
Exit 0 unless a FAIL-level problem is found.
"""
import argparse
import json
import os
import re

NUM_RE = re.compile(r"(?<![A-Za-z0-9_])[-+]?\d+(?:[.,]\d+)*(?:\s?[%‰])?")
STRUCT_RE = re.compile(r"(?:Figure|Fig\.|Table|图|表|Eq\.?|公式|§|#)\s*([0-9]+(?:[.\-][0-9]+)*)", re.I)
CITE_RE = re.compile(
    r"(\[[0-9][0-9,\s\-–]*\]|\\cite\{[^}]+\}"
    r"|\([A-Z][A-Za-z\-]+(?:\s(?:et al\.|and\s[A-Z][A-Za-z\-]+))?,?\s?(?:19|20)\d{2}[a-z]?\))"
)
ABS_RE = re.compile(r"(证明|证实|毫无疑问|显著优于|完全阻断|proves|demonstrates conclusively|undoubtedly)")
HEAD_RE = re.compile(r"^(#{1,6})\s+(.+)$", re.M)
CAPTION_RE = re.compile(r"^(Figure|Fig\.?|Table|图|表)\s*([0-9]+[A-Za-z]?)\s*[.:：]", re.I | re.M)
REF_REF_RE = re.compile(r"(Figure|Fig\.?|Table|图|表)\s*([0-9]+[A-Za-z]?)", re.I)
PLACEHOLDER_RE = re.compile(r"(?:【(?:待补|待核)[:：]\s*([^】]*)】|\[(?:TBD|待补|待核)[:：]\s*([^\]]*)\])", re.I)
DOI_RE = re.compile(r"10\.\d{4,9}/[^\s\"<>]+")
CONFLICT_LINE_RE = re.compile(
    r"^\s*([A-Za-z\u4e00-\u9fff][\w\u4e00-\u9fff /()\-]{1,60}?)\s*[:=]\s*([-+]?\d+(?:[.,]\d+)*)\s*(%|‰)?\s*$")
REF_HEAD_RE = re.compile(r"(?im)^#{1,6}\s*(?:references|bibliography|参考文献)\s*$")
DECL_PATTERNS = {
    "data_availability": r"(data availability|数据可得性|数据可用性)",
    "funding": r"(funding|基金|资助)",
    "conflict_of_interest": r"(conflict of interest|competing interests|利益冲突)",
    "ethics": r"(ethics|伦理)",
}


def load(path, default):
    if path and os.path.exists(path):
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    return default


def norm_num(tok):
    return str(tok).replace(",", " ").strip()


def num_in_text(tok, text):
    """Token-aware membership: 12.4 is not satisfied by 12.45; 12.4% matches 12.4."""
    core = norm_num(tok).rstrip("%‰")
    if not core:
        return False
    blob = norm_num(text)
    for m in re.finditer(re.escape(core), blob):
        before = blob[m.start() - 1] if m.start() > 0 else ""
        after = blob[m.end()] if m.end() < len(blob) else ""
        if not before.isdigit() and not after.isdigit():
            return True
    return False


def substr_match(needle, haystack):
    needle, haystack = str(needle or "").strip().lower(), str(haystack or "").lower()
    if not needle or not haystack:
        return False
    if needle in haystack:
        return True
    tokens = [t for t in re.split(r"[\s_\-/]+", needle) if len(t) >= 2]
    return bool(tokens) and all(t in haystack for t in tokens)


def word_count(text):
    return len(re.findall(r"[A-Za-z0-9\u4e00-\u9fff]+", text or ""))


def kind_norm(kind):
    kind = str(kind).lower().rstrip(".")
    return "figure" if kind in ("figure", "fig", "图") else "table"


def expand_bracket(tok):
    out = []
    for part in re.split(r"[,;]", tok.strip("[]")):
        part = part.strip()
        m = re.match(r"^(\d+)\s*[-–]\s*(\d+)$", part)
        if m:
            lo, hi = int(m.group(1)), int(m.group(2))
            if 0 < hi - lo <= 50:
                out.extend(range(lo, hi + 1))
        elif part.isdigit():
            out.append(int(part))
    return out


def section_aliases(sec):
    names = [sec.get("canonical"), sec.get("name")] + list(sec.get("aliases") or [])
    return [str(n).strip().lower() for n in names if n]


def find_heading(headings, sec):
    aliases = section_aliases(sec)
    for strict in (True, False):
        for pos, (head, _, level) in enumerate(headings):
            if level == 1:
                continue
            low = head.strip().lower()
            for a in aliases:
                if strict and (low == a or low.startswith(a + " ") or low.startswith(a + ":")
                               or low.startswith(a + "：") or low.startswith(a + "/")):
                    return pos
                if not strict and a in low:
                    return pos
    return None


def parse_reference_entries(text):
    m = REF_HEAD_RE.search(text)
    if not m:
        return [], None
    lines = text[m.end():].splitlines()
    entries, current = [], []
    for line in lines:
        s = line.strip()
        if not s:
            if current:
                entries.append(" ".join(current))
                current = []
            continue
        if re.match(r"^#{1,6}\s+", s):
            break
        if re.match(r"^\[\d+\]", s) or re.match(r"^\d+[.)]\s", s):
            if current:
                entries.append(" ".join(current))
            current = [s]
        elif current:
            current.append(s)
        else:
            current = [s]
    if current:
        entries.append(" ".join(current))
    parsed = []
    for entry in entries:
        m2 = re.match(r"^\[(\d+)\]\s*(.*)$", entry) or re.match(r"^(\d+)[.)]\s*(.*)$", entry)
        parsed.append({"index": int(m2.group(1)) if m2 else None,
                       "raw": m2.group(2) if m2 else entry,
                       "raw_full": entry})
    return parsed, m.start()


def references_from_files(paths):
    refs = []
    for p in paths or []:
        if not p or not os.path.exists(p):
            continue
        data = load(p, [])
        if isinstance(data, dict):
            data = data.get("references") or []
        if isinstance(data, list):
            refs.extend([r for r in data if isinstance(r, dict)])
    return refs


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--draft", required=True)
    ap.add_argument("--map", default="")
    ap.add_argument("--template", default="")
    ap.add_argument("--corpus", default="")
    ap.add_argument("--plan", default="")
    ap.add_argument("--references", nargs="*", default=[])
    ap.add_argument("--todo", default="")
    ap.add_argument("--out", required=True)
    a = ap.parse_args()

    text = open(a.draft, encoding="utf-8").read()
    smap = load(a.map, [])
    if isinstance(smap, dict):
        smap = smap.get("source_map", [])
    tpl = load(a.template, {"sections": []})
    plan = load(a.plan, {}) if a.plan else {}
    corpus = open(a.corpus, encoding="utf-8").read() if a.corpus and os.path.exists(a.corpus) else ""
    refs = references_from_files(a.references) + [r for r in (plan.get("references") or []) if isinstance(r, dict)]
    unique_refs, ref_seen = [], set()
    for r in refs:
        key = str(r.get("key") or "").strip().lower()
        if key and key in ref_seen:
            continue
        if key:
            ref_seen.add(key)
        unique_refs.append(r)
    refs = unique_refs

    problems, warnings = [], []
    headings = [(m.group(2).strip(), m.start(), len(m.group(1))) for m in HEAD_RE.finditer(text)]
    ref_entries, ref_start = parse_reference_entries(text)
    body_text = text[:ref_start] if ref_start is not None else text

    # ------------------------------------------------------------ sections
    sections_missing, out_of_order, word_counts, positions = [], [], {}, []
    for sec in tpl.get("sections", []):
        name = sec.get("name") or sec.get("canonical") or ""
        pos = find_heading(headings, sec)
        if pos is None:
            sections_missing.append(name)
            (problems if sec.get("required") else warnings).append(
                ("missing required section: %s" if sec.get("required") else "section not present (advisory): %s") % name)
            continue
        positions.append((headings[pos][1], name))
        end = headings[pos + 1][1] if pos + 1 < len(headings) else len(text)
        body = re.sub(r"^#{1,6}\s+.*$", "", text[headings[pos][1]:end], flags=re.M)
        word_counts[name] = word_count(body)
        if sec.get("min_words") and word_counts[name] < int(sec["min_words"]):
            warnings.append("section %s short: %d < %d words" % (name, word_counts[name], sec["min_words"]))
    for i in range(1, len(positions)):
        if positions[i][0] < positions[i - 1][0]:
            out_of_order.append("%s before %s" % (positions[i][1], positions[i - 1][1]))
    if out_of_order:
        problems.append("sections out of template order: %s" % "; ".join(out_of_order))

    # ------------------------------------------------------------ numbers
    structural = {norm_num(x) for x in STRUCT_RE.findall(body_text)}
    mapped_values = " ".join(str(e.get("value", "")) for e in smap if isinstance(e, dict))
    uncertainty = [u for u in (plan.get("uncertainty") or []) if isinstance(u, dict)]
    unc_text = " ".join(" ".join(str(v) for v in (u.get("what"), u.get("where"), u.get("why"))) for u in uncertainty)
    numbers = list(dict.fromkeys(NUM_RE.findall(body_text)))
    unbound = [n for n in numbers
               if norm_num(n).rstrip("%‰") not in structural
               and not num_in_text(n, mapped_values)
               and not num_in_text(n, corpus)]
    unrecorded = [n for n in unbound if not num_in_text(n, unc_text)]
    if unrecorded:
        problems.append("numbers not traceable to source_map/corpus: %s" % unrecorded[:20])
    elif unbound:
        warnings.append("numbers only covered by an uncertainty note: %s" % unbound[:20])

    # ------------------------------------------------------------ source map + conflicts
    if not smap:
        warnings.append("source_map is empty: no factual claim is traceable to a material locator")
    for i, e in enumerate(smap):
        if not isinstance(e, dict):
            problems.append("source_map[%d] is not an object" % i)
            continue
        for k in ("claim", "value", "source_path", "locator"):
            if not str(e.get(k, "")).strip():
                problems.append("source_map[%d] missing %s" % (i, k))
        if str(e.get("source_path") or "") and not os.path.exists(str(e["source_path"])):
            warnings.append("source_map[%d] source_path not found: %s" % (i, e["source_path"]))

    grouped = {}
    for e in smap:
        if not isinstance(e, dict):
            continue
        key = re.sub(r"[\s_\-]+", " ", str(e.get("metric") or e.get("claim") or "").strip().lower())
        if key:
            grouped.setdefault(key, []).append(e)
    conflicts = []
    for key, entries in grouped.items():
        values = sorted({norm_num(e.get("value")) for e in entries if str(e.get("value", "")).strip()})
        if len(values) > 1:
            conflicts.append({"where": entries[0].get("locator") or key, "what": key, "values": values,
                              "sources": sorted({str(e.get("source_path")) for e in entries}),
                              "why": "same metric has different values in the materials"})
    conflicts += [c for c in (plan.get("conflicts") or []) if isinstance(c, dict)]
    uniq, seen = [], set()
    for c in conflicts:
        k = (str(c.get("what")), tuple(c.get("values") or []))
        if k not in seen:
            seen.add(k)
            uniq.append(c)
    conflict_unregistered = [c.get("what") for c in uniq
                             if not any(str(u.get("type")) == "conflict"
                                        and (substr_match(c.get("what"), u.get("what"))
                                             or substr_match(c.get("what"), u.get("where")))
                                        for u in uncertainty)]
    if conflict_unregistered:
        problems.append("conflicts not registered in uncertainty: %s" % conflict_unregistered)

    # ------------------------------------------------------------ citations
    cite_tokens = list(dict.fromkeys(CITE_RE.findall(body_text)))
    ref_keys = {str(r.get("key")).lower() for r in refs if r.get("key")}
    ref_section_nums = {e["index"] for e in ref_entries if e.get("index")}
    ref_section_text = " ".join(e["raw_full"] for e in ref_entries).lower()
    unresolved = []
    for c in cite_tokens:
        ok, reason = False, ""
        if c.startswith("\\cite"):
            key = c[len("\\cite{"):-1].strip().lower()
            ok = key in ref_keys or bool(corpus and key in corpus.lower())
            reason = "key not found in bib/reference registry"
        elif c.startswith("["):
            idxs = expand_bracket(c)
            if ref_section_nums:
                ok = all(n in ref_section_nums for n in idxs)
                reason = "numbered citation has no matching reference entry"
            elif refs:
                ok = bool(idxs) and max(idxs) <= len(refs)
                reason = "index exceeds the %d reference entries" % len(refs)
            else:
                ok = bool(corpus) and (c.strip() in corpus or (bool(idxs) and all(
                    re.search(r"\[\s*%d\s*\]" % n, corpus) for n in idxs)))
                reason = "no matching bracketed reference in materials"
        else:
            inner = c.strip("()")
            m = re.match(r"([A-Z][A-Za-z\-]+).*?((?:19|20)\d{2})", inner)
            if m:
                surname, year = m.group(1).lower(), m.group(2)
                ok = bool(ref_section_text and surname in ref_section_text and year in ref_section_text)
                ok = ok or any(surname in str(r.get("authors") or r.get("author") or "").lower()
                               and str(r.get("year") or "") == year for r in refs)
                ok = ok or bool(corpus and re.search(
                    re.escape(surname) + r"[^\n]{0,60}" + re.escape(year), corpus, re.I))
                reason = "author-year citation not found in references/materials"
            else:
                reason = "unparsed citation"
        if not ok:
            unresolved.append({"citation": c, "reason": reason})
    if unresolved:
        problems.append("unresolved citations: %s" % [x["citation"] for x in unresolved][:10])

    # ------------------------------------------------------------ references
    reference_problems = []
    for r in refs:
        authors = str(r.get("authors") or r.get("author") or "").strip()
        missing = [] if authors else ["authors"]
        missing += [k for k in ("year", "title") if not str(r.get(k) or "").strip()]
        if not str(r.get("venue") or r.get("journal") or "").strip():
            missing.append("venue")
        if missing:
            reference_problems.append({"key": r.get("key"), "missing": missing})
        if not str(r.get("doi") or "").strip():
            warnings.append("reference %s has no DOI; left unverified, not invented" % r.get("key"))
    for e in ref_entries:
        if not re.search(r"(19|20)\d{2}", e["raw"]):
            reference_problems.append({"key": e.get("index"), "missing": ["year"]})
        if not DOI_RE.search(e["raw"]):
            warnings.append("reference entry %s has no DOI; left unverified, not invented"
                            % (e.get("index") or e["raw"][:40]))
    if reference_problems:
        (problems if refs else warnings).append("reference entries incomplete: %s" % reference_problems[:10])
    cited_blob = body_text.lower()
    uncited = []
    for r in refs:
        key = str(r.get("key") or "").strip()
        if not key:
            continue
        key_hit = any(key.lower() == c[len("\\cite{"):-1].strip().lower()
                      for c in cite_tokens if c.startswith("\\cite"))
        first_author = re.split(r"[,;]", str(r.get("authors") or r.get("author") or ""))[0].strip().lower()
        if not key_hit and not (first_author and first_author in cited_blob):
            uncited.append(key)
    if uncited:
        warnings.append("reference entries never cited: %s" % uncited[:10])

    # ------------------------------------------------------------ figures / tables
    captions = {(kind_norm(m.group(1)), norm_num(m.group(2))) for m in CAPTION_RE.finditer(body_text)}
    caption_pos = {m.start() for m in CAPTION_RE.finditer(body_text)}
    referenced, figure_problems, table_problems = set(), [], []
    for m in REF_REF_RE.finditer(body_text):
        if m.start() in caption_pos:
            continue
        kind, label = kind_norm(m.group(1)), norm_num(m.group(2))
        referenced.add((kind, label))
        if (kind, label) not in captions:
            (figure_problems if kind == "figure" else table_problems).append(
                "referenced %s %s has no caption" % (m.group(1), m.group(2)))
    for kind, label in sorted(captions - referenced):
        warnings.append("%s %s caption is never cited in the body" % (kind, label))
    for f in (plan.get("figures") or []):
        if isinstance(f, dict):
            num = re.search(r"\d+", str(f.get("label") or ""))
            if num and ("figure", num.group(0)) not in captions:
                figure_problems.append("plan figure %s has no matching caption" % f.get("label"))
    for t in (plan.get("tables") or []):
        if isinstance(t, dict):
            num = re.search(r"\d+", str(t.get("label") or ""))
            if num and ("table", num.group(0)) not in captions:
                table_problems.append("plan table %s has no matching caption" % t.get("label"))
    if figure_problems:
        problems.append("; ".join(sorted(set(figure_problems))))
    if table_problems:
        problems.append("; ".join(sorted(set(table_problems))))

    # ------------------------------------------------------------ placeholders
    placeholders = [m.group(1) or m.group(2) or "" for m in PLACEHOLDER_RE.finditer(text)]
    unregistered = [ph for ph in placeholders
                    if not any(substr_match(ph.split("｜")[0].split("|")[0].strip(), u.get("what"))
                               or substr_match(ph.split("｜")[0].split("|")[0].strip(), u.get("where"))
                               for u in uncertainty)]
    if unregistered:
        problems.append("placeholders without an uncertainty record: %s" % unregistered[:10])

    # ------------------------------------------------------------ declarations
    declarations_missing = [key for key in (tpl.get("declarations") or [])
                            if not re.search(DECL_PATTERNS.get(key, re.escape(key)), text, re.I)]
    if declarations_missing:
        problems.append("missing declarations: %s" % declarations_missing)

    # ------------------------------------------------------------ honesty
    for m in ABS_RE.finditer(body_text):
        window = body_text[max(0, m.start() - 120): m.end() + 120]
        if not re.search(r"\[[0-9,\s\-–]+\]|\\cite\{|\((?:19|20)\d{2}\)", window):
            warnings.append("absolute claim without citation: ...%s..." % window.strip()[:80])

    # ------------------------------------------------------------ cross-file conflict candidates
    conflict_candidates = []
    if corpus:
        seen_lines = {}
        for block in corpus.split("===== FILE: ")[1:]:
            if "\n" not in block:
                continue
            path, body = block.split("\n", 1)
            for ln, line in enumerate(body.splitlines(), start=1):
                m = CONFLICT_LINE_RE.match(line)
                if m:
                    key = re.sub(r"[\s_\-]+", " ", m.group(1).strip().lower()) + (m.group(3) or "")
                    seen_lines.setdefault(key, []).append((m.group(2), path, ln))
        for key, vals in seen_lines.items():
            distinct = {norm_num(v[0]) for v in vals}
            if len(distinct) > 1:
                conflict_candidates.append({"what": key, "values": sorted(distinct),
                                            "locations": ["%s:%d" % (p, ln) for _, p, ln in vals][:6]})

    todo = [{"type": u.get("type") or "uncertain", "where": u.get("where", "-"), "what": u.get("what", "-")}
            for u in uncertainty]
    todo += [{"type": "conflict", "where": c.get("where", "-"), "what": c.get("what", "-")} for c in uniq]
    todo += [{"type": "unbound_number", "where": "body", "what": n} for n in unrecorded]

    verdict = "fail" if problems else ("review" if warnings or uniq or unregistered else "pass")
    report = {
        "verdict": verdict,
        "sections_found": [h for h, _, _ in headings],
        "sections_missing": sections_missing,
        "sections_out_of_order": out_of_order,
        "section_word_counts": word_counts,
        "numbers_total": len(numbers),
        "numbers_unbound": unbound,
        "numbers_not_registered": unrecorded,
        "citations_total": len(cite_tokens),
        "citations_unresolved": unresolved,
        "reference_entries_md": len(ref_entries),
        "reference_entries_structured": len(refs),
        "reference_problems": reference_problems,
        "references_uncited": uncited,
        "figure_problems": sorted(set(figure_problems)),
        "table_problems": sorted(set(table_problems)),
        "placeholders_total": len(placeholders),
        "placeholders_unregistered": unregistered,
        "declarations_missing": declarations_missing,
        "conflicts": uniq,
        "conflicts_unregistered": conflict_unregistered,
        "conflict_candidates_from_materials": conflict_candidates[:20],
        "problems": problems,
        "warnings": warnings[:80],
        "todo": todo,
        "limits": "offline audit; DOI/author metadata is not checked against the web and remains human-verifiable",
    }
    os.makedirs(os.path.dirname(os.path.abspath(a.out)) or ".", exist_ok=True)
    with open(a.out, "w", encoding="utf-8") as fh:
        json.dump(report, fh, ensure_ascii=False, indent=1)
    if a.todo:
        lines = ["# 待补 / 待核清单", "",
                 "由 scripts/section_audit.py 根据本次草稿与材料生成；未确认项禁止当作结论。", ""]
        lines += ["- [%s] %s：%s" % (i["type"], i["where"], i["what"]) for i in todo] if todo else ["- 无。"]
        with open(a.todo, "w", encoding="utf-8") as fh:
            fh.write("\n".join(lines) + "\n")
    print("verdict=%s problems=%d warnings=%d conflicts=%d placeholders=%d"
          % (verdict, len(problems), len(warnings), len(uniq), len(placeholders)))
    for p in problems[:12]:
        print("  !", p)
    for w in warnings[:8]:
        print("  ~", w)
    return 0 if verdict != "fail" else 1


if __name__ == "__main__":
    raise SystemExit(main())
