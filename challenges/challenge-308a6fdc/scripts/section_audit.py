#!/usr/bin/env python3
"""section_audit.py - structural + evidence audit for a manuscript draft.

Failures are reserved for fabricated evidence (numbers absent from the sources,
citations that resolve to nothing, source_map locators pointing at missing
files).  Presentation gaps (short sections, missing declarations, unregistered
placeholders/conflicts, figure captions) are warnings so a draft is not thrown
away for a formatting miss.
"""
import argparse
import json
import os
import re
import sys

try:
    from kernel import (REF_HEADINGS, _audit_text, _check_citations,
                        _citation_tokens, _num_value, _numbers, _number_values,
                        _reference_registry)
except Exception:  # pragma: no cover - standalone fallback
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from kernel import (REF_HEADINGS, _audit_text, _check_citations,
                        _citation_tokens, _num_value, _numbers, _number_values,
                        _reference_registry)

PLACEHOLDER_RE = re.compile(
    r"\[(?:待补|待定|待填|TODO|TBD|CITATION|REF|INSERT[^\]]*)\]"
    r"|【[^】]{0,40}(?:待补|待定|待填|TODO|TBD)】|\bTODO\b|\bTBD\b|\bXXX+\b|\?\?\?", re.I)
DECLARATION_TITLES = {
    "data_availability": r"data availability|数据可用性|数据获取",
    "funding": r"funding|基金|资助",
    "conflict_of_interest": r"conflict of interest|competing interests|利益冲突",
    "ethics": r"ethics|伦理",
}


def norm_name(name):
    text = re.sub(r"^\s*(?:\d+(?:\.\d+)*[\.、]?|[一二三四五六七八九十百]+[、.]|第[一二三四五六七八九十百]+[章节])\s*",
                  "", str(name or ""))
    return re.sub(r"[\s:：]+", " ", text).strip().lower()


def split_sections(text):
    sections, cur = [], {"name": "", "level": 0, "lines": []}
    for line in text.splitlines():
        m = re.match(r"^(#{1,6})\s+(.*?)\s*$", line)
        if m:
            sections.append(cur)
            cur = {"name": m.group(2).strip(), "level": len(m.group(1)), "lines": []}
        else:
            cur["lines"].append(line)
    sections.append(cur)
    return [s for s in sections if s["name"] or "".join(s["lines"]).strip()]


def find_section(sections, target):
    want = norm_name(target)
    for sec in sections:
        if norm_name(sec["name"]) == want:
            return sec
    for sec in sections:
        name = norm_name(sec["name"])
        if want and (want in name or name in want):
            return sec
    return None


def word_count(text):
    return len(re.findall(r"[A-Za-z0-9]+|[\u4e00-\u9fff]", text))


def norm_claim(text):
    return re.sub(r"[^a-z0-9]+", " ", str(text or "").lower()).strip()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--draft", required=True)
    ap.add_argument("--map", dest="map_path", default="")
    ap.add_argument("--template", default="")
    ap.add_argument("--corpus", default="")
    ap.add_argument("--plan", default="")
    ap.add_argument("--out", default="work/audit.json")
    a = ap.parse_args()

    draft = open(a.draft, encoding="utf-8", errors="replace").read()
    plan = {}
    if a.plan and os.path.exists(a.plan):
        plan = json.load(open(a.plan, encoding="utf-8"))
    schema = {}
    if a.map_path and os.path.exists(a.map_path):
        raw = json.load(open(a.map_path, encoding="utf-8"))
        schema = raw.get("source_map", raw) if isinstance(raw, dict) else raw
    if not isinstance(schema, list):
        schema = []
    template = {"sections": [], "declarations": []}
    if a.template and os.path.exists(a.template):
        template = json.load(open(a.template, encoding="utf-8"))
    template_sections = template.get("sections", template) if isinstance(template, dict) else template
    if not isinstance(template_sections, list):
        template_sections = []
    corpus = ""
    if a.corpus and os.path.exists(a.corpus):
        corpus = open(a.corpus, encoding="utf-8", errors="replace").read()

    problems, warnings = [], []
    sections = split_sections(draft)

    # ---------------------------------------------------------- sections
    word_counts, positions = {}, []
    for spec in template_sections:
        name = spec.get("name") or spec.get("heading") or ""
        if not name:
            continue
        sec = find_section(sections, name)
        words = word_count("\n".join(sec["lines"])) if sec else 0
        word_counts[name] = words
        min_words = int(spec.get("min_words") or 0)
        required = spec.get("required", True)
        if sec is None:
            (problems if required else warnings).append("section missing: %s" % name)
        elif min_words and words < min_words:
            warnings.append("section %s short: %d < %d words" % (name, words, min_words))
        if sec is not None:
            positions.append((sections.index(sec), name))
    ordered = [name for _, name in sorted(positions)]
    planned = [s.get("name") for s in template_sections
               if find_section(sections, s.get("name") or "") is not None]
    sections_out_of_order = ordered != planned
    if sections_out_of_order:
        warnings.append("sections out of template order: %s vs %s" % (ordered, planned))

    # ---------------------------------------------------------- numbers
    evidence_text = _audit_text(draft)
    tokens = _numbers(evidence_text)
    supported = _number_values(corpus)
    for entry in schema:
        if isinstance(entry, dict):
            for key in ("value", "unit"):
                if entry.get(key) not in (None, ""):
                    val = _num_value(entry[key])
                    if val is not None:
                        supported.add(round(val, 10))
    unsupported = []
    for tok in dict.fromkeys(tokens):
        val = _num_value(tok)
        if val is None:
            continue
        if round(val, 10) not in supported:
            unsupported.append(tok)
    if unsupported:
        if corpus or schema:
            problems.append("numbers not traceable to source_map/corpus: %s" % unsupported[:20])
        else:
            warnings.append("numbers have no evidence corpus to check: %s" % unsupported[:20])

    # ---------------------------------------------------------- citations
    cites = _citation_tokens(draft)
    registry, bib_keys = _reference_registry(corpus)
    citations_unresolved = _check_citations(cites, corpus, registry, bib_keys)
    if citations_unresolved:
        problems.append("citations not resolvable in sources: %s"
                        % [c["citation"] for c in citations_unresolved][:10])

    # ---------------------------------------------------------- source map
    source_map_problems = []
    by_claim = {}
    for i, entry in enumerate(schema):
        if not isinstance(entry, dict):
            source_map_problems.append("source_map[%d] is not an object" % i)
            continue
        missing = [k for k in ("claim", "value", "source_path", "locator")
                   if not str(entry.get(k, "")).strip()]
        if missing:
            source_map_problems.append("source_map[%d] missing %s" % (i, ", ".join(missing)))
        sp = str(entry.get("source_path") or "")
        if sp:
            cand = sp if os.path.isabs(sp) else os.path.join(
                os.path.dirname(os.path.abspath(a.draft)), sp)
            if not os.path.exists(cand) and sp not in corpus:
                source_map_problems.append("source_map[%d] cites a missing file: %s" % (i, sp))
            elif sp not in corpus:
                warnings.append("source_map[%d] source_path not indexed in corpus: %s" % (i, sp))
        value = str(entry.get("value") or "").strip()
        if value and corpus:
            val = _num_value(value)
            hit = (round(val, 10) in _number_values(corpus)) if val is not None \
                else (value.lower() in corpus.lower())
            if not hit:
                warnings.append("source_map[%d] value not found verbatim in sources: %s"
                                % (i, value))
        claim = norm_claim(entry.get("claim"))
        if claim and value:
            by_claim.setdefault(claim, set()).add(value)
    if source_map_problems:
        problems.extend(source_map_problems)
    conflicts = []
    uncertainty = plan.get("uncertainty") or []
    registered = " ".join(str(u) for u in uncertainty).lower()
    for claim, values in by_claim.items():
        if len(values) > 1 and claim not in registered:
            conflicts.append({"claim": claim, "values": sorted(values)})
    if conflicts:
        warnings.append("conflicting values not registered in uncertainty: %s" % conflicts[:5])

    # ---------------------------------------------------------- placeholders
    hits = sorted(set(m.group(0) for m in PLACEHOLDER_RE.finditer(draft)))
    unregistered = [h for h in hits if h.lower() not in registered]
    placeholders_unregistered = []
    if unregistered:
        placeholders_unregistered = unregistered
        warnings.append("placeholders not registered in uncertainty: %s" % unregistered[:10])

    # ---------------------------------------------------------- declarations
    declarations_missing = []
    for key in template.get("declarations") or []:
        pattern = DECLARATION_TITLES.get(key, re.escape(key))
        if not re.search(pattern, draft, re.I):
            declarations_missing.append(key)
    if declarations_missing:
        warnings.append("declarations missing: %s" % declarations_missing)

    # ---------------------------------------------------------- figures
    captions = set((m.group(1).lower(), m.group(2))
                   for m in re.finditer(r"(?im)^\s*(figure|fig\.?|table|图|表)\s*(\d+[a-z]?)\s*[\.:：]",
                                        draft))
    def cap_kind(kind):
        return "figure" if kind.lower().startswith(("fig", "图")) else "table"
    caption_pairs = {(cap_kind(k), n) for k, n in captions}
    figure_problems = []
    for obj in (plan.get("figures") or []) + (plan.get("tables") or []):
        label = str(obj.get("label") or "")
        m = re.search(r"(\d+[A-Za-z]?)", label)
        kind = "table" if re.search(r"table|表", label, re.I) else "figure"
        if m and (kind, m.group(1)) not in caption_pairs:
            figure_problems.append("%s %s has no matching caption" % (kind, m.group(1)))
    if figure_problems:
        warnings.append("figure/table captions incomplete: %s" % figure_problems[:5])

    # ---------------------------------------------------------- references
    reference_problems = []
    for ref in plan.get("references") or []:
        if not isinstance(ref, dict):
            continue
        missing = [k for k in ("authors", "title", "year") if not ref.get(k)]
        if missing:
            reference_problems.append({"key": ref.get("key"), "missing": missing})
        if ref.get("key") and ref["key"] not in corpus:
            reference_problems.append({"key": ref["key"], "missing": ["not in bib corpus"]})
    if reference_problems:
        warnings.append("reference entries incomplete: %s" % reference_problems[:5])

    verdict = "fail" if problems else ("review" if warnings else "pass")
    report = {
        "draft": os.path.abspath(a.draft),
        "sections_found": [s["name"] for s in sections],
        "word_counts": word_counts,
        "sections_missing": [w.split(": ", 1)[1] for w in problems if w.startswith("section missing")]
        or [w.split(": ", 1)[1] for w in warnings if w.startswith("section missing")],
        "sections_out_of_order": ordered if sections_out_of_order else [],
        "numbers_total": len(tokens),
        "numbers_unbound": unsupported,
        "citations_unresolved": [c["citation"] for c in citations_unresolved],
        "conflicts": conflicts,
        "placeholders_unregistered": placeholders_unregistered,
        "declarations_missing": declarations_missing,
        "figure_problems": figure_problems,
        "reference_problems": reference_problems,
        "source_map_problems": source_map_problems,
        "warnings": warnings,
        "problems": problems,
        "verdict": verdict,
    }
    os.makedirs(os.path.dirname(os.path.abspath(a.out)) or ".", exist_ok=True)
    json.dump(report, open(a.out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("verdict=%s problems=%d warnings=%d conflicts=%d placeholders=%d"
          % (verdict, len(problems), len(warnings), len(conflicts), len(placeholders_unregistered)))
    for p in problems:
        print("  !", p)
    for w in warnings:
        print("  ~", w)
    return 0 if verdict != "fail" else 1


if __name__ == "__main__":
    sys.exit(main())
