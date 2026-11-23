#!/usr/bin/env python3
"""note_schema_check.py - validate a structured reading note against its source corpus.

Checks (stdlib only, no network):
  skeleton   research_question / methods / data / findings / limitations / reuse_points present
  entries    unique id, non-empty text, kind in {author_claim, inference}, anchor with section
  anchors    quote must be verbatim in corpus; anchor section must exist in paper.sections
  numbers    numbers in note text and in the `value` field must appear in the corpus
  inference  kind=inference entries need `basis` (ids of the claims they rest on)
  conflicts  same `topic` with differing text must carry a `conflict_group`
  reuse      reuse_points need a `use` field

Usage: python scripts/note_schema_check.py --notes work/notes.json \
    --corpus work/corpus.txt --out work/note_check.json
Exit 0 = pass (no errors), 1 = review. Warnings do not fail the run.
"""
import argparse
import json
import os
import re
import sys

FIELDS = ["research_question", "methods", "data", "findings", "limitations", "reuse_points"]
NUM_RE = re.compile(r"(?<![A-Za-z0-9_])[-+]?\d+(?:[.,]\d+)*(?:\s?[%‰])?")
WS = re.compile(r"\s+")


def norm(s):
    return WS.sub(" ", (s or "").replace("\u00ad", "")).strip().lower()


def nums(text):
    return [m.group(0).replace(" ", "") for m in NUM_RE.finditer(text or "")]


def lead_num(s):
    m = re.match(r"\s*(\d+)", str(s))
    return m.group(1) if m else None


def sec_known(sec, sections):
    if not sections:
        return True
    s0 = str(sec).strip().lower()
    for s in sections:
        t = str(s).strip().lower()
        if s0 in t or t in s0 or (lead_num(s0) and lead_num(s0) == lead_num(t)):
            return True
    return False


def check_entry(field, e, corpus, sections, seen):
    errs, warns = [], []
    eid = e.get("id") or "<no-id>"
    if not e.get("id"):
        errs.append({"field": field, "entry": eid, "issue": "missing id"})
    elif eid in seen:
        errs.append({"field": field, "entry": eid, "issue": "duplicate id"})
    seen.add(eid)
    if not (e.get("text") or "").strip():
        errs.append({"field": field, "entry": eid, "issue": "empty text"})
    kind = e.get("kind")
    if kind not in {"author_claim", "inference"}:
        errs.append({"field": field, "entry": eid, "issue": "kind must be author_claim|inference"})
    anchor = e.get("anchor") or {}
    file_sec = anchor.get("section")
    if not file_sec:
        errs.append({"field": field, "entry": eid, "issue": "anchor.section missing"})
    elif not sec_known(file_sec, sections):
        errs.append({"field": field, "entry": eid, "issue": "anchor.section not in paper.sections: %s" % file_sec})
    if not anchor.get("page") and not anchor.get("paragraph"):
        errs.append({"field": field, "entry": eid, "issue": "anchor needs page or paragraph"})
    quote = e.get("quote") or ""
    if not quote.strip():
        errs.append({"field": field, "entry": eid, "issue": "quote missing"})
    elif norm(quote) not in corpus:
        errs.append({"field": field, "entry": eid, "issue": "quote not verbatim in corpus"})
    if kind == "inference" and not e.get("basis"):
        errs.append({"field": field, "entry": eid, "issue": "inference without basis ids"})
    if field == "findings":
        if nums(e.get("text")) and not str(e.get("value") or "").strip():
            warns.append({"field": field, "entry": eid, "issue": "finding has numbers but no value field"})
        if e.get("value"):
            for n in dict.fromkeys(nums(str(e["value"]))):
                if norm(n) not in corpus:
                    errs.append({"field": field, "entry": eid, "issue": "value not in corpus: %s" % n})
    if field == "reuse_points" and not (e.get("use") or "").strip():
        warns.append({"field": field, "entry": eid, "issue": "reuse point without use field"})
    for n in dict.fromkeys(nums(e.get("text"))):
        if norm(n) not in corpus:
            errs.append({"field": field, "entry": eid, "issue": "number not in corpus: %s" % n})
    return errs, warns


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--notes", required=True)
    ap.add_argument("--corpus", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    data = json.load(open(a.notes, encoding="utf-8"))
    corpus = norm(open(a.corpus, encoding="utf-8").read())
    fields = data.get("fields") or {}
    sections = (data.get("paper") or {}).get("sections") or []
    errors, warnings, seen, counts = [], [], set(), {}
    for name in FIELDS:
        entries = fields.get(name) or []
        counts[name] = len(entries)
        if not entries:
            errors.append({"field": name, "entry": "-", "issue": "required field missing or empty"})
            continue
        for e in entries:
            err, warn = check_entry(name, e, corpus, sections, seen)
            errors += err
            warnings += warn
    topics = {}
    for name, entries in fields.items():
        for e in entries:
            if e.get("topic"):
                topics.setdefault(e["topic"], []).append((name, e))
    for topic, items in topics.items():
        if len(items) > 1 and len({norm(i[1].get("text")) for i in items}) > 1:
            if not all(i[1].get("conflict_group") for i in items):
                warnings.append({"field": "conflicts", "entry": topic,
                                 "issue": "divergent notes on same topic without conflict_group"})
    report = {"fields_checked": counts, "entries_total": sum(counts.values()),
              "sections_declared": len(sections), "errors": errors, "warnings": warnings,
              "counts": {"errors": len(errors), "warnings": len(warnings)},
              "verdict": "pass" if not errors else "review"}
    os.makedirs(os.path.dirname(os.path.abspath(a.out)) or ".", exist_ok=True)
    json.dump(report, open(a.out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("verdict=%s errors=%d warnings=%d entries=%d"
          % (report["verdict"], len(errors), len(warnings), report["entries_total"]))
    for e in errors[:10]:
        print("  !", e["field"], e["entry"], "-", e["issue"])
    for w in warnings[:6]:
        print("  ~", w["field"], w["entry"], "-", w["issue"])
    return 0 if not errors else 1


if __name__ == "__main__":
    sys.exit(main())
