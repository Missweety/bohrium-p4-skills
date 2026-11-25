#!/usr/bin/env python3
"""claim_evidence_matrix.py - validate a claim-evidence matrix and render it as Markdown.
Input JSON: {"claims":[{"id","text","state","strength","evidence":[{"source","locator","quote"}],"note"}]}
state: supported | not_covered | conflict   strength: strong | moderate | weak | none
Usage: python scripts/claim_evidence_matrix.py --matrix work/matrix.json \
           --corpus work/corpus.txt --out work/evidence_check.json \
           [--md work/claim_evidence.md] [--base .]
Exit 0 when verdict != fail.
"""
import argparse, json, os, re, sys, unicodedata

STATES = {"supported", "not_covered", "conflict"}
STRENGTHS = {"strong", "moderate", "weak", "none"}
ABS = re.compile(r"(证明|证实|毫无疑问|必然|显著优于|proves|conclusive|undoubtedly|always)")
NUM = re.compile(r"(?<![A-Za-z0-9_])[-+]?\d+(?:[.,]\d+)*\s?[%‰]?")
CLAIM_TAG = re.compile(r"[（(]\s*(C\d+[a-z]?)\s*[）)]")
MIN_QUOTE = 12
PUNCT_MAP = str.maketrans({
    "“": '"', "”": '"', "‘": "'", "’": "'", "—": "-", "–": "-", "‐": "-",
    "，": ",", "。": ".", "；": ";", "：": ":", "！": "!", "？": "?", "（": "(", "）": ")",
    "％": "%", "　": " ", "、": ",", "「": '"', "」": '"',
})


def norm(text):
    return re.sub(r"\s+", " ", text or "").strip()


def defang(text):
    """Loose form for verbatim checks: NFKC + punctuation + collapsed whitespace."""
    text = unicodedata.normalize("NFKC", text or "").translate(PUNCT_MAP)
    return re.sub(r"\s+", " ", text).strip().lower()


def bounded(hay, needle):
    """True when needle occurs at token boundaries, so '12.4%' cannot match inside '112.4%'."""
    if not needle:
        return False
    start = hay.find(needle)
    while start != -1:
        end = start + len(needle)
        before = hay[start - 1] if start else ""
        after = hay[end] if end < len(hay) else ""
        left_bad = bool(before) and (before.isalnum()
                                     or (before == "." and start >= 2 and hay[start - 2].isdigit())
                                     or before in "%‰")
        right_bad = bool(after) and (after.isalnum()
                                     or (after == "." and end + 1 < len(hay) and hay[end + 1].isdigit()))
        if not (needle[0].isascii() and left_bad) and not (needle[-1].isascii() and right_bad):
            return True
        start = hay.find(needle, start + 1)
    return False


def corpus_files(corpus):
    """Split '===== FILE: path =====' blocks into {path: text}."""
    out, cur, buf = {}, None, []
    for line in corpus.splitlines():
        hit = re.match(r"^===== FILE: (.+) =====$", line)
        if hit:
            if cur:
                out[cur] = "\n".join(buf)
            cur, buf = hit.group(1), []
        elif cur is not None:
            buf.append(line)
    if cur:
        out[cur] = "\n".join(buf)
    return out


def add(bucket, cid, kind, message):
    bucket.append({"claim": cid, "type": kind, "message": message})


def check_claim(claim, corpus, base, errors, warnings, files=None):
    cid = str(claim.get("id", "")).strip()
    text = norm(claim.get("text"))
    state, strength = claim.get("state"), claim.get("strength", "moderate")
    note = norm(claim.get("note"))
    evidence = claim.get("evidence") or []
    if state not in STATES:
        add(errors, cid, "bad_state", "state must be one of %s" % sorted(STATES))
    if strength not in STRENGTHS:
        add(errors, cid, "bad_strength", "strength must be one of %s" % sorted(STRENGTHS))
    if not text:
        add(errors, cid, "empty_claim", "claim text is empty")
    if state == "supported" and strength == "none":
        add(errors, cid, "supported_without_strength", "state=supported needs a real strength, not none")
    if state == "not_covered" and strength not in {"none", "weak"}:
        add(warnings, cid, "not_covered_with_strength",
            "state=not_covered should use strength none/weak, got %s" % strength)
    for ev in evidence:
        quote, locator = norm(ev.get("quote")), norm(ev.get("locator"))
        source = str(ev.get("source", "")).strip()
        if not source or not os.path.exists(os.path.join(base, source)):
            add(errors, cid, "missing_source", "evidence source not found: %s" % (source or "(empty)"))
        if not locator:
            add(errors, cid, "missing_locator", "evidence without locator")
        quote_ok = False
        if not quote:
            add(errors, cid, "empty_quote", "evidence without quote")
        elif bounded(norm(corpus), quote):
            quote_ok = True
            if len(quote) < MIN_QUOTE:
                add(warnings, cid, "quote_too_short", "quote shorter than %d chars: %.40s" % (MIN_QUOTE, quote))
        elif defang(quote) and bounded(defang(corpus), defang(quote)):
            quote_ok = True
            # line wrapping / full-width punctuation / dash variants: accept but flag for review
            add(warnings, cid, "quote_normalized_match",
                "quote matches only after punctuation/whitespace normalisation: %.60s" % quote)
        else:
            add(errors, cid, "quote_not_verbatim", "quote not found verbatim in corpus: %.60s" % quote)
        if files and source:
            block = next((t for p, t in files.items() if p.endswith(source) or source.endswith(os.path.basename(p))), None)
            if block is None:
                add(warnings, cid, "source_not_indexed", "source not found in corpus blocks: %s" % source)
            elif quote_ok and quote and not bounded(defang(block), defang(quote)):
                add(errors, cid, "quote_not_in_cited_source",
                    "quote exists in corpus but not in the cited source %s" % source)
    if state == "supported" and not evidence:
        add(errors, cid, "supported_without_evidence", "state=supported needs >=1 evidence")
    if state == "not_covered":
        if evidence:
            add(errors, cid, "not_covered_with_evidence", "state=not_covered must leave evidence empty")
        if not note:
            add(errors, cid, "not_covered_without_note", "record search scope/keywords in note")
    if state == "conflict":
        if len(evidence) < 2:
            add(errors, cid, "conflict_needs_two", "state=conflict needs >=2 conflicting evidence items")
        if not note:
            add(errors, cid, "conflict_without_note", "conflict must list what a human should verify")
    for number in dict.fromkeys(NUM.findall(text)):
        tok = number.strip()
        if tok and not bounded(norm(corpus), tok):
            # substring matching let "12 samples" pass when the material only says "112.4%"
            add(warnings, cid, "number_not_in_corpus", "number %s in claim not found in materials" % tok)
    if ABS.search(text) and strength in {"weak", "none"}:
        add(warnings, cid, "overclaim", "absolute wording with %s evidence strength" % strength)
    return {"id": cid, "text": text, "state": state, "strength": strength,
            "evidence": evidence, "note": note}


def render_md(rows):
    out = ["# Claim–Evidence 表", "",
           "| ID | 论断 | 三态 | 强度 | 证据（quote · source:locator） | 待核 / 说明 |",
           "|-|-|-|-|-|-|"]
    def cell(value):
        return str(value).replace("|", "\\|").replace("\r", " ").replace("\n", " ")

    for r in rows:
        refs = " <br> ".join("%s · %s:%s" % (cell(norm(e.get("quote"))), e.get("source"), e.get("locator"))
                             for e in r["evidence"]) or "—"
        cells = [r["id"], r["text"], r["state"], r["strength"], refs, r["note"] or "—"]
        out.append("| " + " | ".join(cell(c) for c in cells) + " |")
    return "\n".join(out) + "\n"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--matrix", required=True)
    ap.add_argument("--corpus", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--md", default="")
    ap.add_argument("--base", default=".", help="base dir for relative evidence source paths")
    ap.add_argument("--manuscript", default="")
    a = ap.parse_args()
    errors, warnings = [], []
    for path, label in ((a.matrix, "matrix"), (a.corpus, "corpus")):
        if not os.path.exists(path):
            print("missing %s: %s" % (label, path))
            return 2
    try:
        data = json.load(open(a.matrix, encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        print("matrix is not valid JSON (%s): %s" % (a.matrix, exc))
        return 2
    claims = data.get("claims", []) if isinstance(data, dict) else data
    if isinstance(claims, dict):
        claims = list(claims.values())
    raw_corpus = open(a.corpus, encoding="utf-8", errors="replace").read()
    corpus = norm(raw_corpus)
    files = corpus_files(raw_corpus)
    if not claims:
        add(errors, "", "empty_matrix", "no claims in matrix")
    seen, rows = set(), []
    for claim in claims:
        if not isinstance(claim, dict):
            add(errors, "", "bad_claim_entry", "claim entry must be an object, got %s" % type(claim).__name__)
            continue
        cid = str(claim.get("id", "")).strip()
        if cid in seen:
            add(errors, cid, "duplicate_id", "claim id used twice")
        seen.add(cid)
        rows.append(check_claim(claim, corpus, a.base, errors, warnings, files))
    if a.manuscript and os.path.isfile(a.manuscript):
        text = open(a.manuscript, encoding="utf-8", errors="replace").read()
        tagged = set(CLAIM_TAG.findall(text))
        for row in rows:
            if row["state"] == "supported" and row["id"] and row["id"] not in tagged:
                add(errors, row["id"], "claim_missing_in_manuscript",
                    "supported claim %s is not cited in the manuscript" % row["id"])
            if row["state"] == "conflict" and row["id"] and row["id"] not in tagged:
                add(warnings, row["id"], "conflict_not_flagged_in_manuscript",
                    "conflict claim %s should be flagged as pending verification in text" % row["id"])
        for cid in sorted(tagged - seen):
            add(errors, cid, "unknown_claim_id_in_manuscript",
                "manuscript cites %s but the matrix has no such claim" % cid)
    elif a.manuscript:
        add(errors, "", "manuscript_not_found", "manuscript path not found: %s" % a.manuscript)
    by_state = {s: sum(1 for r in rows if r["state"] == s) for s in sorted(STATES)}
    report = {"verdict": "fail" if errors else ("review" if warnings else "pass"),
              "claims": len(rows), "by_state": by_state,
              "errors": errors, "warnings": warnings}
    os.makedirs(os.path.dirname(os.path.abspath(a.out)) or ".", exist_ok=True)
    with open(a.out, "w", encoding="utf-8") as fh:
        json.dump(report, fh, ensure_ascii=False, indent=1)
    if a.md:
        os.makedirs(os.path.dirname(os.path.abspath(a.md)) or ".", exist_ok=True)
        with open(a.md, "w", encoding="utf-8") as fh:
            fh.write(render_md(rows))
    print("verdict=%s claims=%d supported=%d not_covered=%d conflict=%d errors=%d warnings=%d"
          % (report["verdict"], len(rows), by_state["supported"], by_state["not_covered"],
             by_state["conflict"], len(errors), len(warnings)))
    for e in errors[:10]:
        print("  !", e["claim"], e["type"], e["message"])
    for w in warnings[:8]:
        print("  ~", w["claim"], w["type"], w["message"])
    return 0 if not errors else 1


if __name__ == "__main__":
    sys.exit(main())
