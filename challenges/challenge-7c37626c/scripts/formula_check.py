#!/usr/bin/env python3
"""formula_check.py - gate formula restoration, symbols, derivations and numeric checks.

Usage: python scripts/formula_check.py --formulas work/formulas.json --symbols work/symbols.json \
           --derivations work/derivations.json --numerics work/numeric_checks.json \
           --corpus work/corpus.txt --out work/formula_check.json [--tol 0.01]
Exit 0 when verdict=pass. Stdlib only, no network.
"""
import argparse, json, re, sys

FS = {"transcribed", "extracted", "insufficient_evidence"}
DS = {"author_defined", "context_inferred", "conventional", "unknown"}
NS = {"consistent", "inconsistent", "not_checkable"}
LIG = {"ﬁ": "fi", "ﬂ": "fl", "ﬀ": "ff", "ﬃ": "ffi", "\u00ad": "", "\u2019": "'"}
def norm(s):
    for k, v in LIG.items(): s = s.replace(k, v)
    return re.sub(r"\s+", " ", s).strip().lower()
def blank(v):
    return v is None or (isinstance(v, str) and not v.strip())
def load(path, key):
    data = json.load(open(path, encoding="utf-8"))
    return data.get(key, []) if isinstance(data, dict) else data
def balanced(s):
    pairs, stack, i = {"{": "}", "[": "]", "(": ")"}, [], 0
    while i < len(s):
        if s[i] == "\\": i += 2; continue
        if s[i] in pairs: stack.append(pairs[s[i]])
        elif s[i] in ")]}" and (not stack or stack.pop() != s[i]): return False
        i += 1
    return not stack
def main():
    ap = argparse.ArgumentParser()
    for flag in ("--formulas", "--symbols", "--derivations", "--numerics", "--corpus", "--out"):
        ap.add_argument(flag, required=True)
    ap.add_argument("--tol", type=float, default=0.01)
    a = ap.parse_args()
    formulas, symbols = load(a.formulas, "formulas"), load(a.symbols, "symbols")
    derivs, numerics = load(a.derivations, "derivations"), load(a.numerics, "numeric_checks")
    corpus = norm(open(a.corpus, encoding="utf-8").read())
    errors, warnings, fmap, smap = [], [], {}, {}
    E, W = errors.append, warnings.append
    for f in formulas:
        fid = f.get("id")
        if blank(fid) or fid in fmap:
            E("formula: missing/duplicate id %r" % fid); continue
        fmap[fid] = f
        st = f.get("status")
        if st not in FS:
            E("formula[%s] invalid status %r" % (fid, st)); continue
        if st == "insufficient_evidence":
            if not blank(f.get("latex")): E("formula[%s] insufficient_evidence must not carry latex" % fid)
            if blank(f.get("reason")): E("formula[%s] insufficient_evidence needs a reason" % fid)
            continue
        latex = f.get("latex") or ""
        if blank(latex): E("formula[%s] missing latex" % fid)
        elif not balanced(latex): E("formula[%s] unbalanced delimiters in latex" % fid)
        src = f.get("source") or {}
        if blank(src.get("path")) or blank(src.get("locator")):
            E("formula[%s] needs source.path and source.locator" % fid)
        if not f.get("symbols"): W("formula[%s] declares no symbols" % fid)
    used = set()
    for s in symbols:
        name = s.get("symbol")
        if blank(name) or name in smap:
            E("symbol: missing/duplicate %r" % name); continue
        smap[name] = s
        st = s.get("definition_status")
        if st not in DS: E("symbol[%s] invalid definition_status %r" % (name, st))
        if st in {"author_defined", "context_inferred"}:
            loc = s.get("locator") or {}
            if not any(not blank(loc.get(k)) for k in ("page", "paragraph_id", "formula", "scope")):
                E("symbol[%s] %s needs locator" % (name, st))
            q = s.get("quote") or ""
            if len(q.strip()) < 12: E("symbol[%s] definition quote shorter than 12 chars" % name)
            elif norm(q) not in corpus: E("symbol[%s] definition quote not verbatim" % name)
            if st == "context_inferred" and blank(s.get("inference_basis")):
                E("symbol[%s] context_inferred needs inference_basis" % name)
        if st == "conventional" and blank(s.get("basis")): E("symbol[%s] conventional needs basis" % name)
        if st == "unknown" and blank(s.get("note")): E("symbol[%s] unknown needs note" % name)
        if "unit" not in s: E("symbol[%s] missing unit key (use null with note)" % name)
        elif blank(s.get("unit")) and blank(s.get("note")): E("symbol[%s] missing unit needs note" % name)
    for f in formulas:
        for name in f.get("symbols") or []:
            used.add(name)
            if name not in smap: E("formula[%s] symbol %s missing from symbol table" % (f.get("id"), name))
    for name in smap:
        if name not in used: W("symbol[%s] not referenced by any formula" % name)
    for d in derivs:
        fid = d.get("formula_id")
        if fid not in fmap: E("derivation references unknown formula %r" % fid)
        if blank(d.get("target")): W("derivation[%s] missing target" % fid)
        steps = d.get("steps") or []
        if not steps: E("derivation[%s] has no steps" % fid)
        if [s.get("n") for s in steps] != list(range(1, len(steps) + 1)):
            E("derivation[%s] step numbers must be 1..n in order" % fid)
        for s in steps:
            if blank(s.get("expr")) or blank(s.get("basis")):
                E("derivation[%s] step %s needs expr and basis" % (fid, s.get("n")))
        if "assumptions" not in d: W("derivation[%s] missing assumptions field" % fid)
        for dep in d.get("depends_on") or []:
            if dep not in fmap: E("derivation[%s] depends on unknown formula %s" % (fid, dep))
    for n in numerics:
        fid, st = n.get("formula_id"), n.get("status")
        f = fmap.get(fid)
        if not f: E("numeric check references unknown formula %r" % fid)
        elif f.get("status") == "insufficient_evidence":
            E("numeric check on %s without a formula representation" % fid)
        if st not in NS: E("numeric[%s] invalid status %r" % (fid, st))
        inputs = n.get("inputs") or []
        if not inputs: E("numeric[%s] needs inputs" % fid)
        for inp in inputs:
            sym = inp.get("symbol")
            if sym not in smap: E("numeric[%s] input symbol %s not in symbol table" % (fid, sym))
            elif smap[sym].get("definition_status") == "unknown":
                E("numeric[%s] substitutes unknown symbol %s" % (fid, sym))
            if not isinstance(inp.get("value"), (int, float)):
                E("numeric[%s] input %s has non-numeric value" % (fid, sym))
            if blank(inp.get("unit")): E("numeric[%s] input %s missing unit (use '1')" % (fid, sym))
            if not isinstance(inp.get("sig_figs"), int) or inp.get("sig_figs", 0) < 1:
                E("numeric[%s] input %s missing sig_figs" % (fid, sym))
        comp = n.get("computed") or {}
        if st == "consistent":
            if not isinstance(comp.get("value"), (int, float)) or blank(comp.get("unit")):
                E("numeric[%s] consistent needs computed value and unit" % fid)
            rep = n.get("reported") or {}
            if not isinstance(rep.get("value"), (int, float)):
                E("numeric[%s] consistent needs a reported value to compare" % fid)
            elif isinstance(comp.get("value"), (int, float)):
                c, r = comp["value"], rep["value"]
                rel = abs(c - r) / abs(r) if r else abs(c - r)
                if rel > a.tol:
                    E("numeric[%s] computed %.4g vs reported %.4g exceeds tol %g" % (fid, c, r, a.tol))
        if st == "not_checkable" and blank(n.get("note")):
            E("numeric[%s] not_checkable needs note listing missing inputs" % fid)
        if st == "inconsistent" and blank(n.get("note")):
            E("numeric[%s] inconsistent needs note on likely cause" % fid)

    report = {"verdict": "pass" if not errors else "review", "errors": errors, "warnings": warnings,
              "counts": {"formulas": len(formulas), "symbols": len(symbols),
                         "derivations": len(derivs), "numeric_checks": len(numerics),
                         "insufficient_evidence": sum(1 for f in formulas if f.get("status") == "insufficient_evidence"),
                         "unknown_symbols": sum(1 for s in symbols if s.get("definition_status") == "unknown")}}
    with open(a.out, "w", encoding="utf-8") as fh: json.dump(report, fh, ensure_ascii=False, indent=1)
    print("verdict=%s errors=%d warnings=%d %s" % (report["verdict"], len(errors), len(warnings),
                                                   json.dumps(report["counts"], ensure_ascii=False)))
    for e in errors[:20]: print("  !", e)
    return 0 if not errors else 1

if __name__ == "__main__":
    sys.exit(main())
