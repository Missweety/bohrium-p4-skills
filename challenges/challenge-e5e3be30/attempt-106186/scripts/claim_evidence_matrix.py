#!/usr/bin/env python3
"""claim_evidence_matrix.py - validate a claim-verification matrix and render it as Markdown.

Input JSON:
  {"claims":[{"id","text","verdict","strength",
              "evidence":[{"source","locator","quote","relation"}],
              "note"}],
   "conflicts":[{"claim","evidence_a","evidence_b","question"}]}

verdict: supported | partially_supported | contradicted | insufficient_evidence
strength: strong | moderate | weak | none
relation: supports | contradicts | mixed | context   (default: supports)

Usage:
  python scripts/claim_evidence_matrix.py --matrix work/matrix.json \
      --corpus work/corpus.txt --out work/matrix_report.json \
      [--md /app/output/claim_evidence.md] [--base /input] \
      [--claims work/claims.json] [--allow-extra]

Exit 0 when verdict != fail.
"""
import argparse
import json
import os
import re
import sys
import unicodedata

VERDICTS = {"supported", "partially_supported", "contradicted", "insufficient_evidence"}
STRENGTHS = {"strong", "moderate", "weak", "none"}
RELATIONS = {"supports", "contradicts", "mixed", "context"}
LEGACY = {"partial": "partially_supported", "not_covered": "insufficient_evidence",
          "conflict": "partially_supported"}
COMPARATOR = re.compile(r"(高于|低于|大于|小于|多于|少于|增加|减少|升高|降低|优于|劣于|"
                        r"higher|lower|greater|fewer|more than|less than|increase[sd]?|decrease[sd]?|"
                        r"outperform|superior|inferior|vs\.?|versus)", re.I)
NEGATION = re.compile(r"(不显著|不支持|不一致|不能|不会|不存在|未能|未见|未报告|未纳入|未测试|"
                      r"无显著|无证据|没有|非|never|not\b|no\b|none\b|without|fail(?:s|ed)?\b)", re.I)
MODALITY = re.compile(r"(可能|或许|推测|有望|could|may|might|would|suggest(s|ed)?|potential(ly)?|extrapolat)", re.I)
NUM = re.compile(r"(?<![A-Za-z0-9_])[-+]?\d+(?:[.,]\d+)*\s?[%‰]?")
MIN_QUOTE = 12
PUNCT_MAP = str.maketrans({
    "“": '"', "”": '"', "‘": "'", "’": "'", "—": "-", "–": "-", "‐": "-",
    "，": ",", "。": ".", "；": ";", "：": ":", "！": "!", "？": "?", "（": "(", "）": ")",
    "％": "%", "　": " ", "、": ",", "「": '"', "」": '"',
})


def norm(text):
    return re.sub(r"\s+", " ", text or "").strip()


def defang(text):
    """Loose form for verbatim checks: NFKC + punctuation + all whitespace removed."""
    text = unicodedata.normalize("NFKC", text or "").translate(PUNCT_MAP)
    return re.sub(r"\s+", "", text).lower()


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
    verdict = claim.get("verdict")
    strength = claim.get("strength", "moderate")
    note = norm(claim.get("note"))
    evidence = claim.get("evidence") or []
    support = [e for e in evidence if norm(e.get("relation", "supports")) == "supports"]
    contra = [e for e in evidence if norm(e.get("relation")) == "contradicts"]

    if verdict in LEGACY:
        add(errors, cid, "legacy_verdict",
            "verdict %r is from v1; use %r from the public v2 contract" % (verdict, LEGACY[verdict]))
    elif verdict not in VERDICTS:
        add(errors, cid, "bad_verdict", "verdict must be one of %s" % sorted(VERDICTS))
    if strength not in STRENGTHS:
        add(errors, cid, "bad_strength", "strength must be one of %s" % sorted(STRENGTHS))
    if not text:
        add(errors, cid, "empty_claim", "claim text is empty")

    for ev in evidence:
        quote, locator = norm(ev.get("quote")), norm(ev.get("locator"))
        source = str(ev.get("source", "")).strip()
        relation = norm(ev.get("relation", "supports"))
        if relation not in RELATIONS:
            add(errors, cid, "bad_relation", "evidence relation must be one of %s" % sorted(RELATIONS))
        if not source or not os.path.exists(os.path.join(base, source)):
            add(errors, cid, "missing_source", "evidence source not found: %s" % (source or "(empty)"))
        if not locator:
            add(errors, cid, "missing_locator", "evidence without locator")
        if not quote:
            add(errors, cid, "empty_quote", "evidence without quote")
        elif len(quote) < MIN_QUOTE:
            add(warnings, cid, "quote_too_short",
                "quote shorter than %d chars: %.40s" % (MIN_QUOTE, quote))
        if quote and quote in norm(corpus):
            pass
        elif quote and defang(quote) in defang(corpus):
            add(warnings, cid, "quote_normalized_match",
                "quote matches only after punctuation/whitespace normalisation: %.60s" % quote)
        elif quote:
            add(errors, cid, "quote_not_verbatim", "quote not found verbatim in corpus: %.60s" % quote)
        if files and source and quote:
            block = next((t for p, t in files.items()
                          if p.endswith(source) or source.endswith(os.path.basename(p))), None)
            if block is None:
                add(warnings, cid, "source_not_indexed", "source not found in corpus blocks: %s" % source)
            elif defang(quote) not in defang(block):
                add(errors, cid, "quote_not_in_cited_source",
                    "quote exists in corpus but not in the cited source %s" % source)

    if verdict in {"supported", "partially_supported"}:
        if not support:
            add(errors, cid, "no_supporting_evidence",
                "verdict=%s needs >=1 evidence with relation=supports" % verdict)
    if verdict == "partially_supported":
        if not note:
            add(errors, cid, "partial_without_gap",
                "verdict=partially_supported must state which part of the claim exceeds the evidence")
        if strength == "strong":
            add(warnings, cid, "partial_strength", "partially_supported rarely qualifies as strong")
    if verdict == "contradicted":
        if not contra:
            add(errors, cid, "contradicted_without_contradiction",
                "verdict=contradicted needs >=1 evidence with relation=contradicts")
        if not note:
            add(errors, cid, "contradicted_without_note",
                "verdict=contradicted must state what the quote says against the claim")
        if strength == "none":
            add(errors, cid, "contradicted_without_strength", "contradicted needs a real strength")
    if verdict == "insufficient_evidence":
        if evidence:
            add(errors, cid, "insufficient_with_evidence",
                "verdict=insufficient_evidence must leave evidence empty; absence of evidence is not proof")
        if not note:
            add(errors, cid, "insufficient_without_scope",
                "record the search scope/keywords and why the material cannot decide the claim")
        if strength not in {"none", "weak"}:
            add(warnings, cid, "insufficient_strength",
                "verdict=insufficient_evidence should use strength none/weak, got %s" % strength)

    if support and contra and verdict not in {"contradicted", "partially_supported"}:
        add(errors, cid, "mixed_evidence_wrong_label",
            "both supporting and contradicting quotes exist; use contradicted or partially_supported")
    if support and contra and verdict == "contradicted" and not note:
        add(errors, cid, "mixed_evidence_without_note", "state how conflicting sources were weighed")

    # Preserve the claim's logical structure: number, comparator, negation, modality.
    quotes_cmp = " ".join(norm(e.get("quote")) for e in evidence if e.get("quote"))
    for number in dict.fromkeys(x.strip() for x in NUM.findall(text) if x.strip()):
        if number not in quotes_cmp and number not in norm(corpus):
            add(warnings, cid, "number_not_in_materials",
                "number %s in claim not found in cited quotes or materials" % number)
    if COMPARATOR.search(text) and evidence and not COMPARATOR.search(quotes_cmp):
        add(warnings, cid, "comparator_not_preserved",
            "claim compares values but the cited quote has no comparator; check direction")
    if NEGATION.search(text) and evidence and not NEGATION.search(quotes_cmp):
        add(warnings, cid, "negation_not_preserved",
            "claim contains negation/absence but the cited quote does not; check scope")
    if MODALITY.search(text) and verdict == "contradicted":
        add(errors, cid, "extrapolation_as_contradiction",
            "unsupported extrapolation (may/could/suggest) is not experimentally disproved; "
            "use insufficient_evidence or partially_supported")

    return {"id": cid, "text": text, "verdict": verdict, "strength": strength,
            "evidence": evidence, "note": note}


def render_md(rows, conflicts):
    out = ["# Claim–Evidence 核验表", "",
           "| ID | 待核验论断 | 判定 | 强度 | 证据（quote · source:locator · relation） | 限制 / 缺口 |",
           "|-|-|-|-|-|-|"]
    for r in rows:
        refs = " <br> ".join("%s · %s:%s · %s" % (
            norm(e.get("quote")), e.get("source"), e.get("locator"), e.get("relation", "supports"))
            for e in r["evidence"]) or "—"
        cells = [r["id"], r["text"], r["verdict"], r["strength"], refs, r["note"] or "—"]
        out.append("| " + " | ".join(str(c).replace("|", "\\|") for c in cells) + " |")
    if conflicts:
        out += ["", "## 冲突与待裁决项", ""]
        for c in conflicts:
            out.append("- **%s**：%s ↔ %s；待裁决：%s" % (
                c.get("claim"), c.get("evidence_a"), c.get("evidence_b"), c.get("question")))
    return "\n".join(out) + "\n"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--matrix", required=True)
    ap.add_argument("--corpus", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--md", default="")
    ap.add_argument("--base", default=".")
    ap.add_argument("--claims", default="")
    ap.add_argument("--allow-extra", action="store_true")
    a = ap.parse_args()
    errors, warnings = [], []
    try:
        data = json.load(open(a.matrix, encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        report = {"verdict": "fail", "claims": 0,
                  "by_verdict": {v: 0 for v in sorted(VERDICTS)}, "conflicts": 0,
                  "errors": [{"claim": "", "type": "matrix_unreadable",
                              "message": str(exc)[:240]}],
                  "warnings": []}
        os.makedirs(os.path.dirname(os.path.abspath(a.out)) or ".", exist_ok=True)
        with open(a.out, "w", encoding="utf-8") as fh:
            json.dump(report, fh, ensure_ascii=False, indent=1)
        print("verdict=fail: matrix unreadable (%s)" % exc)
        return 1
    if isinstance(data, dict):
        claims = data.get("claims", [])
        conflicts = data.get("conflicts", []) if isinstance(data.get("conflicts"), list) else []
    else:
        claims, conflicts = data, []
    if not isinstance(claims, list):
        add(errors, "", "bad_matrix_shape", "matrix.claims must be a list, got %s"
            % type(claims).__name__)
        claims = []
    raw_corpus = open(a.corpus, encoding="utf-8", errors="replace").read()
    corpus = norm(raw_corpus)
    files = corpus_files(raw_corpus)
    if not claims:
        add(errors, "", "empty_matrix", "no claims in matrix")

    seen, rows = set(), []
    for claim in claims:
        if not isinstance(claim, dict):
            add(errors, "", "bad_claim_shape",
                "each claim must be an object with id/text/verdict, got %s"
                % type(claim).__name__)
            continue
        cid = str(claim.get("id", "")).strip()
        if cid in seen:
            add(errors, cid, "duplicate_id", "claim id used twice")
        seen.add(cid)
        rows.append(check_claim(claim, corpus, a.base, errors, warnings, files))

    if a.claims and os.path.isfile(a.claims):
        try:
            with open(a.claims, encoding="utf-8") as fh:
                claims_doc = json.load(fh)
            if isinstance(claims_doc, dict):
                expected = {str(c.get("id")) for c in claims_doc.get("claims", [])
                            if isinstance(c, dict)}
            else:
                expected = {str(c.get("id")) for c in claims_doc if isinstance(c, dict)}
        except Exception as exc:  # noqa: BLE001
            add(errors, "", "claims_unreadable", "claims file unreadable: %s" % str(exc)[:200])
            expected = None
        if expected is not None:
            for cid in sorted(expected - seen):
                add(errors, cid, "claim_not_verified", "claim from claims-to-verify.json is missing from the matrix")
            if not a.allow_extra:
                for cid in sorted(seen - expected):
                    add(errors, cid, "unknown_claim", "matrix contains a claim not present in claims-to-verify.json")
    elif a.claims:
        add(errors, "", "claims_file_not_found", "claims file not found: %s" % a.claims)

    for c in conflicts:
        if not (c.get("claim") and c.get("evidence_a") and c.get("evidence_b") and c.get("question")):
            add(errors, str(c.get("claim", "")), "incomplete_conflict",
                "a conflict needs claim, evidence_a, evidence_b and the question to resolve")

    by_verdict = {v: sum(1 for r in rows if r["verdict"] == v) for v in sorted(VERDICTS)}
    report = {"verdict": "fail" if errors else ("review" if warnings else "pass"),
              "claims": len(rows), "by_verdict": by_verdict, "conflicts": len(conflicts),
              "errors": errors, "warnings": warnings}
    os.makedirs(os.path.dirname(os.path.abspath(a.out)) or ".", exist_ok=True)
    with open(a.out, "w", encoding="utf-8") as fh:
        json.dump(report, fh, ensure_ascii=False, indent=1)
    if a.md:
        os.makedirs(os.path.dirname(os.path.abspath(a.md)) or ".", exist_ok=True)
        with open(a.md, "w", encoding="utf-8") as fh:
            fh.write(render_md(rows, conflicts))
    print("verdict=%s claims=%d supported=%d partially_supported=%d contradicted=%d "
          "insufficient_evidence=%d errors=%d warnings=%d"
          % (report["verdict"], len(rows), by_verdict["supported"],
             by_verdict["partially_supported"], by_verdict["contradicted"],
             by_verdict["insufficient_evidence"], len(errors), len(warnings)))
    for e in errors[:10]:
        print("  !", e["claim"], e["type"], e["message"])
    for w in warnings[:8]:
        print("  ~", w["claim"], w["type"], w["message"])
    return 0 if not errors else 1


if __name__ == "__main__":
    sys.exit(main())
