#!/usr/bin/env python3
"""selftest.py - synthetic regression test for run_case.py (NOT an official case).

Builds a throw-away case under /tmp with one MathML XML (fraction + sub/superscripts),
one text material and a case.json, runs run_case.py end to end, then checks three
negative paths against the shipped formula_check.py. Every assertion is based on the
actual process output; a failure exits non-zero.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
RUN_CASE = os.path.join(HERE, "run_case.py")
FORMULA_CHECK = os.path.join(HERE, "formula_check.py")

FAILS = []


def check(cond, label, detail=""):
    if cond:
        print("PASS  %s" % label)
    else:
        print("FAIL  %s%s" % (label, (" | " + detail) if detail else ""))
        FAILS.append(label)


def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)


def run(args, cwd=None):
    return subprocess.run([sys.executable] + args, capture_output=True, text=True, cwd=cwd)


CASE = {
    "case_id": "synthetic-formula-selftest",
    "task": "合成测试（非真实论文）：只解析式 (1) 与式 (2)，给出 LaTeX、符号表与推导骨架。",
    "synthetic": True,
    "output_contract": {"required": [
        "case_id", "status", "answer", "structured", "evidence", "uncertainty", "limits"]},
}

PAPER = """Synthetic test material (not a real paper, not an official case).
In Eq. (1), q_m is the maximum adsorption capacity in mg/g and K_L is the Langmuir constant in L/mg.
The equilibrium concentration C_e is measured in mg/L for this synthetic example.
"""

XML = """<?xml version="1.0" encoding="UTF-8"?>
<article xmlns:m="http://www.w3.org/1998/Math/MathML">
  <disp-formula id="eq1">
    <label>Eq. (1)</label>
    <m:math>
      <m:mrow>
        <m:msub><m:mi>q</m:mi><m:mi>e</m:mi></m:msub>
        <m:mo>=</m:mo>
        <m:mfrac>
          <m:mrow>
            <m:msub><m:mi>q</m:mi><m:mi>m</m:mi></m:msub>
            <m:msub><m:mi>K</m:mi><m:mi>L</m:mi></m:msub>
            <m:msub><m:mi>C</m:mi><m:mi>e</m:mi></m:msub>
          </m:mrow>
          <m:mrow>
            <m:mn>1</m:mn><m:mo>+</m:mo>
            <m:msub><m:mi>K</m:mi><m:mi>L</m:mi></m:msub>
            <m:msub><m:mi>C</m:mi><m:mi>e</m:mi></m:msub>
          </m:mrow>
        </m:mfrac>
      </m:mrow>
    </m:math>
  </disp-formula>
  <disp-formula id="eq2">
    <label>Eq. (2)</label>
    <m:math>
      <m:msup><m:mi>x</m:mi><m:mn>2</m:mn></m:msup>
    </m:math>
  </disp-formula>
</article>
"""


def build_positive(root):
    inp = os.path.join(root, "positive", "input")
    write(os.path.join(inp, "case.json"), json.dumps(CASE, ensure_ascii=False, indent=1))
    write(os.path.join(inp, "materials", "paper.txt"), PAPER)
    write(os.path.join(inp, "artifacts", "source-formulas.xml"), XML)
    # Derived subset overlapping the publisher XML: the same Eq. (1)/(2) appear twice.
    write(os.path.join(inp, "artifacts", "publisher-source.xml"), XML)
    return inp


def build_no_formula(root):
    inp = os.path.join(root, "no_formula", "input")
    case = dict(CASE)
    case["case_id"] = "synthetic-no-formula-selftest"
    case["task"] = "合成测试：材料只有结果文字，没有公式表示。"
    write(os.path.join(inp, "case.json"), json.dumps(case, ensure_ascii=False, indent=1))
    write(os.path.join(inp, "materials", "notes.txt"),
          "Synthetic memo: the run reported only a final value, with no typeset formula.\n"
          "No equation was provided in this synthetic fixture.\n")
    return inp


def main():
    root = tempfile.mkdtemp(prefix="formula_selftest_")
    print("synthetic test root:", root, "(非官方案例)")

    # ------------------------------------------------------------ positive path
    inp = build_positive(root)
    out = os.path.join(root, "positive", "out")
    work = os.path.join(root, "positive", "work")
    proc = run([RUN_CASE, "--dry-run", "--case", os.path.join(inp, "case.json"),
                "--input-dir", inp, "--work", work, "--out", out])
    print("run_case rc=%d" % proc.returncode)
    tail = [ln for ln in proc.stdout.splitlines() if ln.strip()][-8:]
    print("\n".join(tail))
    check(proc.returncode == 0, "run_case exits 0", proc.stderr[-300:])

    rp = os.path.join(out, "result.json")
    check(os.path.isfile(rp), "result.json exists")
    result = json.load(open(rp, encoding="utf-8")) if os.path.isfile(rp) else {}
    for field in ("case_id", "status", "answer", "structured", "evidence", "uncertainty", "limits"):
        check(field in result, "result.json has top-level %s" % field)
    check(result.get("case_id") == "synthetic-formula-selftest", "case_id echoed",
          repr(result.get("case_id")))
    check(result.get("status") in {"ok", "partial", "blocked", "refused"}, "status enum",
          repr(result.get("status")))
    check(bool(result.get("evidence")), "evidence is non-empty")
    check(bool((result.get("limits") or "").strip()) == (result.get("status") == "partial"),
          "partial carries limits")

    formulas = ((result.get("structured") or {}).get("formulas") or [])
    check(len(formulas) == 2, "two formulas extracted", str(len(formulas)))
    by_id = {f.get("id"): f for f in formulas}
    f1, f2 = by_id.get("eq1") or {}, by_id.get("eq2") or {}
    check(f1.get("status") == "extracted", "Eq.(1) status=extracted", repr(f1.get("status")))
    st = f1.get("structure") or {}
    check(st.get("fractions") == 1, "Eq.(1) fractions=1", str(st.get("fractions")))
    check(st.get("subscripts") == 6, "Eq.(1) subscripts=6", str(st.get("subscripts")))
    check(st.get("superscripts") == 0, "Eq.(1) superscripts=0", str(st.get("superscripts")))
    check((f2.get("structure") or {}).get("superscripts") == 1, "Eq.(2) superscripts=1",
          str((f2.get("structure") or {}).get("superscripts")))
    syms = {s.get("symbol"): s for s in ((result.get("structured") or {}).get("symbols") or [])}
    check((syms.get("q_m") or {}).get("unit") == "mg/g",
          "q_m unit taken verbatim from the definition line",
          repr((syms.get("q_m") or {}).get("unit")))
    check(bool((syms.get("K_L") or {}).get("meaning")),
          "K_L meaning taken verbatim from the definition line",
          repr((syms.get("K_L") or {}).get("meaning")))
    check(len(formulas) == 2, "overlapping XMLs do not duplicate formulas", str(len(formulas)))

    fc_path = os.path.join(out, "formula_check.json")
    fc = json.load(open(fc_path, encoding="utf-8")) if os.path.isfile(fc_path) else {}
    check(fc.get("verdict") == "pass", "positive formula_check verdict=pass", repr(fc.get("verdict")))
    if fc.get("errors"):
        print("  formula_check errors:", fc["errors"][:5])
    qc_path = os.path.join(out, "quote_check.json")
    qc = json.load(open(qc_path, encoding="utf-8")) if os.path.isfile(qc_path) else {}
    check(qc.get("verdict") == "pass", "positive quote_check verdict=pass", repr(qc.get("verdict")))

    # ------------------------------------------------------------ negative A: no formula
    inp_a = build_no_formula(root)
    out_a = os.path.join(root, "no_formula", "out")
    work_a = os.path.join(root, "no_formula", "work")
    proc_a = run([RUN_CASE, "--dry-run", "--case", os.path.join(inp_a, "case.json"),
                  "--input-dir", inp_a, "--work", work_a, "--out", out_a])
    print("negative A rc=%d" % proc_a.returncode)
    res_a = json.load(open(os.path.join(out_a, "result.json"), encoding="utf-8"))
    fs_a = (res_a.get("structured") or {}).get("formulas") or []
    insufficient = [f for f in fs_a if f.get("status") == "insufficient_evidence"]
    check(proc_a.returncode == 0, "negative A run exits 0")
    check(len(insufficient) >= 1, "negative A has insufficient_evidence", str(len(insufficient)))
    check(all((f.get("latex") or "") == "" for f in insufficient),
          "negative A insufficient formulas have empty latex",
          str([f.get("latex") for f in insufficient]))

    # ------------------------------------------------------------ negative B/C: formula_check gates
    neg = os.path.join(root, "negative_checks")
    good_symbols = {"symbols": [
        {"symbol": "q", "meaning": "heat", "unit": "J", "range": None,
         "definition_status": "unknown", "note": "synthetic: definition not provided"},
        {"symbol": "m", "meaning": "mass", "unit": "kg", "range": None,
         "definition_status": "unknown", "note": "synthetic: definition not provided"},
    ]}
    write(os.path.join(neg, "symbols.json"), json.dumps(good_symbols, ensure_ascii=False))
    write(os.path.join(neg, "derivations.json"), json.dumps({"derivations": []}))
    write(os.path.join(neg, "corpus.txt"), "synthetic corpus for formula_check q = m c\n")

    formulas_b = {"formulas": [{
        "id": "F1", "status": "transcribed", "latex": "q = m c",
        "source": {"path": "materials/x.txt", "locator": "line 1"}, "symbols": ["q", "m"]}]}
    numerics_b = {"numeric_checks": [{
        "formula_id": "F1",
        "inputs": [{"symbol": "q", "value": 1.0, "unit": "J", "sig_figs": 2}],
        "computed": None, "reported": None, "status": "not_checkable",
        "note": "synthetic: m is missing"}]}
    write(os.path.join(neg, "formulas_b.json"), json.dumps(formulas_b, ensure_ascii=False))
    write(os.path.join(neg, "numerics_b.json"), json.dumps(numerics_b, ensure_ascii=False))
    proc_b = run([FORMULA_CHECK, "--formulas", os.path.join(neg, "formulas_b.json"),
                  "--symbols", os.path.join(neg, "symbols.json"),
                  "--derivations", os.path.join(neg, "derivations.json"),
                  "--numerics", os.path.join(neg, "numerics_b.json"),
                  "--corpus", os.path.join(neg, "corpus.txt"),
                  "--out", os.path.join(neg, "report_b.json")])
    rep_b = json.load(open(os.path.join(neg, "report_b.json"), encoding="utf-8"))
    print("negative B verdict=%s errors=%s" % (rep_b.get("verdict"), rep_b.get("errors")[:2]))
    check(proc_b.returncode != 0, "negative B formula_check exits non-zero", str(proc_b.returncode))
    check(rep_b.get("verdict") == "review", "negative B verdict=review", repr(rep_b.get("verdict")))
    check(any("unknown symbol" in e for e in rep_b.get("errors") or []),
          "negative B reports substituting unknown symbol")

    formulas_c = {"formulas": [{
        "id": "F1", "status": "transcribed", "latex": "\\frac{q}{1",
        "source": {"path": "materials/x.txt", "locator": "line 1"}, "symbols": ["q"]}]}
    write(os.path.join(neg, "formulas_c.json"), json.dumps(formulas_c, ensure_ascii=False))
    write(os.path.join(neg, "numerics_c.json"), json.dumps({"numeric_checks": []}))
    proc_c = run([FORMULA_CHECK, "--formulas", os.path.join(neg, "formulas_c.json"),
                  "--symbols", os.path.join(neg, "symbols.json"),
                  "--derivations", os.path.join(neg, "derivations.json"),
                  "--numerics", os.path.join(neg, "numerics_c.json"),
                  "--corpus", os.path.join(neg, "corpus.txt"),
                  "--out", os.path.join(neg, "report_c.json")])
    rep_c = json.load(open(os.path.join(neg, "report_c.json"), encoding="utf-8"))
    print("negative C verdict=%s errors=%s" % (rep_c.get("verdict"), rep_c.get("errors")[:2]))
    check(proc_c.returncode != 0, "negative C formula_check exits non-zero", str(proc_c.returncode))
    check(rep_c.get("verdict") == "review", "negative C verdict=review", repr(rep_c.get("verdict")))
    check(any("unbalanced" in e for e in rep_c.get("errors") or []),
          "negative C reports unbalanced delimiters")

    # ------------------------------------------------------------ negative D: malformed case.json
    inp_d = os.path.join(root, "bad_case", "input")
    write(os.path.join(inp_d, "case.json"), '{"case_id": "synthetic-bad-case", ')
    out_d = os.path.join(root, "bad_case", "out")
    work_d = os.path.join(root, "bad_case", "work")
    proc_d = run([RUN_CASE, "--dry-run", "--case", os.path.join(inp_d, "case.json"),
                  "--input-dir", inp_d, "--work", work_d, "--out", out_d])
    print("negative D rc=%d" % proc_d.returncode)
    check(proc_d.returncode == 0, "negative D malformed case exits 0", proc_d.stderr[-300:])
    rp_d = os.path.join(out_d, "result.json")
    check(os.path.isfile(rp_d), "negative D still writes result.json")
    res_d = json.load(open(rp_d, encoding="utf-8")) if os.path.isfile(rp_d) else {}
    check(res_d.get("status") in {"partial", "blocked"}, "negative D status degrades honestly",
          repr(res_d.get("status")))
    check("case.json" in (res_d.get("limits") or ""), "negative D limits explains the parse error",
          repr(res_d.get("limits"))[:160])

    print("\n%d failure(s)" % len(FAILS))
    if FAILS:
        print("keep test root for inspection:", root)
        return 1
    shutil.rmtree(root, ignore_errors=True)
    print("all synthetic checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
