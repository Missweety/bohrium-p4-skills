#!/usr/bin/env python3
"""run_case.py - one-command, always-delivering pipeline for the structure-edit skill.

Why this exists: the earlier revision required the model to hand-author five JSON files
before anything was emitted, so a single failed gate step produced *no* result.json.
This runner makes delivery unconditional:

  1. locate case + materials (or inline text), index and probe;
  2. derive a baseline plan from the actual manuscript (baseline_plan.py);
  3. optionally merge a model-authored plan, after strict validation + sanitising;
  4. verify every quote/number, scrub anything not traceable to the source;
  5. emit result.json plus structure_plan.md / diagnosis.csv / edit_plan.csv / outline.md;
  6. run the final check and record its real verdict in self_check.

Exit code is 0 whenever an honest, structurally complete result was written
(including status=blocked/partial with explicit limits). Exit 1 only if nothing
could be written at all.

Usage (skill dir is /skills/weekly-skill at evaluation time):
  python /skills/weekly-skill/scripts/run_case.py --case /input/case.json \
      --work /app/work --out /app/output
"""
import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import kernel  # noqa: E402

DIMS = ["rq_alignment", "section_structure", "argument_chain", "paragraph_relation",
        "repetition", "conclusion_boundary"]
SUPPORTED_EXT = {".txt", ".md", ".tex", ".docx", ".pdf", ".rst", ".html"}
SKIP_NAMES = {"case.json", "task.md", "readme.md", "skill.md", "requirements.txt",
              "environment.yaml", "resources.yaml", "manifest.json",
              "result.json", "diagnosis.csv", "edit_plan.csv", "outline.md",
              "structure_plan.md", "check.json", "plan_check.md", "corpus.txt",
              "evidence.json", "structure.json", "baseline.json", "draft.json",
              "quotes.json", "claims.json", "run_manifest.json"}
SKIP_DIRS = {"work", "out", "output", "outputs", "__pycache__", ".git", "node_modules", "logs"}
LOG = []


def log(msg):
    LOG.append(str(msg))
    print(msg)


def run(args, step, allow_fail=False):
    t0 = time.time()
    proc = subprocess.run([sys.executable] + args, cwd=HERE, capture_output=True, text=True)
    out = (proc.stdout or "") + (proc.stderr or "")
    log("[%s] rc=%d %.1fs :: %s" % (step, proc.returncode, time.time() - t0, " ".join(args[:3])))
    for line in out.strip().splitlines()[:12]:
        log("    " + line)
    if proc.returncode != 0 and not allow_fail:
        log("    (step failed; continuing with honest partial output)")
    return proc.returncode, out


def read_json(path, default=None):
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:  # noqa: BLE001
        return default


def write_json(path, obj):
    os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(obj, fh, ensure_ascii=False, indent=1)


def discover_materials(case_path, extra):
    files, seen = [], set()

    def add(path):
        if not path:
            return
        p = os.path.abspath(path)
        if p in seen or not os.path.isfile(p) or os.path.islink(p):
            return
        if os.path.basename(p).lower() in SKIP_NAMES or os.path.basename(p).startswith("."):
            return
        if os.path.splitext(p)[1].lower() not in SUPPORTED_EXT:
            return
        if os.path.getsize(p) < 120:
            return
        seen.add(p)
        files.append(p)

    for p in extra:
        add(p)
    case = read_json(case_path, {}) or {}

    def walk_strings(obj):
        if isinstance(obj, str):
            if os.path.splitext(obj)[1].lower() in SUPPORTED_EXT:
                yield obj
        elif isinstance(obj, dict):
            for v in obj.values():
                yield from walk_strings(v)
        elif isinstance(obj, list):
            for v in obj:
                yield from walk_strings(v)

    base = os.path.dirname(os.path.abspath(case_path)) if case_path else ""
    for ref in walk_strings(case):
        add(ref)
        add(os.path.join(base, ref))
    roots = [r for r in ("/input", "/app/input") if os.path.isdir(r)]
    if not roots and base:
        roots = [base]
    for root in roots:
        for dirpath, dirnames, names in os.walk(root):
            dirnames[:] = sorted(d for d in dirnames if d not in SKIP_DIRS and not d.startswith("."))
            for n in sorted(names):
                p = os.path.join(dirpath, n)
                if p == os.path.abspath(case_path or ""):
                    continue
                add(p)
    return files


def pick_manuscript(evidence, files):
    readable = [f for f in evidence.get("files", []) if f.get("readable")]
    if not readable:
        return None
    hint = re.compile(r"(manuscript|paper|draft|article|正文|稿件|论文)", re.I)
    named = [f for f in readable if hint.search(os.path.basename(f.get("path", "")))]
    pool = named or readable
    best = max(pool, key=lambda f: f.get("chars", 0))
    path = best.get("path")
    if path and path.startswith("case:"):
        return path.split("case:", 1)[1]
    if files:
        return os.path.basename(path)
    return path


def recompute_coverage(fields, paras_count):
    cov = dict(fields.get("coverage") or {})
    for d in DIMS:
        c = dict(cov.get(d) or {})
        c["checked"] = bool(paras_count)
        c["findings"] = len([x for x in fields.get("diagnosis") or [] if x.get("dimension") == d])
        cov[d] = c
    cov["read_sections"] = cov.get("read_sections") or (["Preamble"] if paras_count else [])
    cov["unread_sections"] = cov.get("unread_sections") or []
    cov["no_issues_found"] = (not fields.get("diagnosis")) and bool(fields.get("no_issues_found"))
    fields["coverage"] = cov


def plan_text(fields):
    parts = []
    for x in fields.get("diagnosis") or []:
        parts += [x.get("problem", ""), x.get("why", ""),
                  (x.get("location") or {}).get("anchor_quote", "")]
    for e in fields.get("edit_plan") or []:
        parts += [e.get("instruction", ""), e.get("preserves", ""), e.get("expected_effect", "")]
    for o in fields.get("outline") or []:
        parts += [str(o.get("role", "")), str(o.get("note", ""))]
    parts += [str(u) for u in fields.get("uncertainty") or []]
    return "\n".join(p for p in parts if p)


PROTECT = [
    (re.compile(r"\b(?:P|S|E|C)\d{2,}\b"), "ID"),
    (re.compile(r"§[0-9A-Za-z.]+"), "SEC"),
    (re.compile(r"第[\d一二三四五六七八九十]+句"), "SENT"),
]


def scrub_numbers(fields, unsupported):
    tokens = sorted({t for t in unsupported if t}, key=len, reverse=True)
    if not tokens:
        return []
    removed = []

    def fix(text):
        text = str(text or "")
        holders = []
        for rx, tag in PROTECT:
            def keep(m, tag=tag):
                holders.append(m.group(0))
                return "@@%s%d@@" % (tag, len(holders) - 1)
            text = rx.sub(keep, text)
        for tok in tokens:
            if tok in text:
                text = text.replace(tok, "（数值待核）")
                removed.append(tok)
        for i, original in enumerate(holders):
            text = re.sub(r"@@(?:ID|SEC|SENT)%d@@" % i, original, text)
        return text

    for x in fields.get("diagnosis") or []:
        for key in ("problem", "why"):
            x[key] = fix(x.get(key))
    for e in fields.get("edit_plan") or []:
        for key in ("instruction", "preserves", "expected_effect", "risk"):
            e[key] = fix(e.get(key))
    for o in fields.get("outline") or []:
        for key in ("role", "note"):
            o[key] = fix(o.get(key))
    fields["uncertainty"] = [fix(u) if isinstance(u, str) else u for u in fields.get("uncertainty") or []]
    return sorted(set(removed))


def emit_and_check(fields, status, work, out, self_check):
    draft = {"fields": fields, "status": status,
             "limits": fields.get("limits", ""), "uncertainty": fields.get("uncertainty", []),
             "self_check": self_check}
    draft_path = os.path.join(work, "draft.json")
    write_json(draft_path, draft)
    if status in ("ok", "success", "partial"):
        run([os.path.join(HERE, "plan_check.py"), "--draft", draft_path,
             "--corpus", os.path.join(work, "corpus.txt"), "--structure",
             os.path.join(work, "structure.json"), "--out", work], "plan_check_final", allow_fail=True)
        self_check["plan_check_final"] = read_json(os.path.join(work, "plan_check.json"), {}) or {}
    else:
        self_check["plan_check_final"] = {"skipped": "status=%s" % status}
    run([os.path.join(HERE, "kernel.py"), "emit", "--draft", draft_path,
         "--contract-dir", work, "--out", out], "emit", allow_fail=True)
    report_path = os.path.join(work, "check.json")
    run([os.path.join(HERE, "kernel.py"), "check", "--out", out, "--contract-dir", work,
         "--report", report_path], "check", allow_fail=True)
    check = read_json(report_path, {}) or {}
    self_check["post_check"] = {"ok": check.get("ok"), "problems": check.get("problems", []),
                                "warnings": check.get("warnings", [])}
    result_path = os.path.join(out, "result.json")
    res = read_json(result_path, None)
    if res is not None:
        res["self_check"] = self_check
        # A failed final check must not be presented as a clean delivery.
        if check.get("ok") is False:
            res["status"] = "partial" if res.get("status") not in ("blocked", "refused") else res["status"]
            note = "交付自检未通过：" + "；".join(check.get("problems", [])[:5])
            res["limits"] = ((res.get("limits") or "") + "；" + note).strip("；")
        write_json(result_path, res)
    return check


def clean_log(text=""):
    out = text or "\n".join(LOG)
    for path, tag in ((HERE, "$SKILL_DIR"), (os.path.dirname(os.path.abspath(HERE)), "$SKILL_DIR")):
        out = out.replace(path, tag)
    return out


def blocked_result(work, out, case_id, reason, detail="", status="blocked"):
    fields = {
        "case_id": case_id, "status": status, "artifact_path": "structure_plan.md",
        "artifact_format": "md", "diagnosis": [], "edit_plan": [], "outline": [],
        "paragraph_map": [], "argument_map": [], "source_map": [], "changes": [],
        "fact_guard": {"numbers_unbound": [], "citations_not_in_sources": [],
                       "quotes_checked": 0, "verdict": "not_run"},
        "coverage": {d: {"checked": False, "findings": 0} for d in DIMS},
        "uncertainty": [reason] + ([detail] if detail else []),
        "limits": reason + (("；" + detail) if detail else ""),
    }
    for d in DIMS:
        fields["coverage"][d]["note"] = "未执行：缺少可读稿件"
    fields["coverage"]["read_sections"] = []
    fields["coverage"]["unread_sections"] = []
    fields["coverage"]["no_issues_found"] = False
    self_check = {"runner": "run_case/v1.2.0", "status": status, "reason": reason,
                  "steps": clean_log(), "baseline_used": False, "model_plan_used": False}
    check = emit_and_check(fields, status, work, out, self_check)
    return {"status": status, "reason": reason, "check_ok": check.get("ok"), "steps": LOG}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--case", default="")
    ap.add_argument("--work", default="/app/work")
    ap.add_argument("--out", default="/app/output")
    ap.add_argument("--plan", default="", help="optional model-authored plan/draft json")
    ap.add_argument("--materials", nargs="*", default=[])
    a = ap.parse_args()
    # subprocesses run with cwd=HERE; resolve caller-relative paths first so
    # `--case case.json --work work --out out` behaves the same as absolute paths.
    a.case = os.path.abspath(a.case) if a.case else ""
    a.work = os.path.abspath(a.work)
    a.out = os.path.abspath(a.out)
    a.plan = os.path.abspath(a.plan) if a.plan else ""
    a.materials = [os.path.abspath(p) for p in a.materials]
    os.makedirs(a.work, exist_ok=True)
    os.makedirs(a.out, exist_ok=True)

    case_path = kernel.find_case_file(a.case)
    if case_path:
        run([os.path.join(HERE, "kernel.py"), "init", "--case", case_path, "--out", a.work], "init")
    else:
        log("warn: no case.json found; contract defaults will be used")
        run([os.path.join(HERE, "kernel.py"), "init", "--out", a.work], "init", allow_fail=True)
    contract = read_json(os.path.join(a.work, "contract.json"), {}) or {}
    case_id = contract.get("case_id") or "case"

    files = discover_materials(case_path, a.materials)
    if files:
        log("materials=%d: %s" % (len(files), ", ".join(os.path.basename(f) for f in files[:6])))
    index_args = [os.path.join(HERE, "kernel.py"), "index", "--out", a.work, "--materials"] + files
    if case_path:
        index_args += ["--case", case_path]
    run(index_args, "index")
    evidence = read_json(os.path.join(a.work, "evidence.json"), {}) or {}
    readable = [f for f in evidence.get("files", []) if f.get("readable")]
    corpus_chars = sum(f.get("chars", 0) for f in readable)
    if not readable or corpus_chars < 200:
        detail = "可读材料字符数=%d；缺失路径=%s" % (corpus_chars, evidence.get("missing_paths") or [])
        blocked_result(a.work, a.out, case_id,
                       "没有可读稿件文本，无法进行结构诊断（不依据标签猜测内容）", detail)
        return 0

    file_hint = pick_manuscript(evidence, files)
    sp = [os.path.join(HERE, "structure_probe.py"), "--corpus", os.path.join(a.work, "corpus.txt"),
          "--out", a.work]
    if file_hint:
        sp += ["--file", file_hint]
    run(sp, "structure_probe", allow_fail=True)
    structure = read_json(os.path.join(a.work, "structure.json"), {}) or {}
    paras = structure.get("paragraphs") or []
    run([os.path.join(HERE, "repetition_probe.py"), "--structure",
         os.path.join(a.work, "structure.json"), "--out", a.work], "repetition_probe", allow_fail=True)
    structure = read_json(os.path.join(a.work, "structure.json"), {}) or {}
    paras = structure.get("paragraphs") or []
    if not paras:
        blocked_result(a.work, a.out, case_id,
                       "材料可读但未能切分出段落，结构诊断无法进行",
                       "structure_probe 未返回段落；不据领域标签补造内容")
        return 0

    run([os.path.join(HERE, "baseline_plan.py"), "--structure",
         os.path.join(a.work, "structure.json"), "--out", a.work], "baseline_plan", allow_fail=True)
    baseline = read_json(os.path.join(a.work, "baseline.json"), {}) or {}
    if not baseline:
        blocked_result(a.work, a.out, case_id, "基线方案生成失败，未产出可交付结构化结果")
        return 0

    # optional model-authored plan
    model_path = a.plan or os.path.join(a.work, "plan.json")
    if not os.path.exists(model_path):
        alt = os.path.join(a.work, "draft.json")
        model_path = alt if os.path.exists(alt) and os.path.getsize(alt) > 32 else ""
    model = None
    model_meta = {}
    if model_path and os.path.exists(model_path):
        strict_rc, _ = run([os.path.join(HERE, "plan_check.py"), "--draft", model_path,
                            "--corpus", os.path.join(a.work, "corpus.txt"), "--structure",
                            os.path.join(a.work, "structure.json"), "--out", a.work],
                           "plan_check_strict", allow_fail=True)
        san_rc, _ = run([os.path.join(HERE, "plan_check.py"), "--draft", model_path,
                         "--corpus", os.path.join(a.work, "corpus.txt"), "--structure",
                         os.path.join(a.work, "structure.json"), "--out", a.work,
                         "--sanitize", "--out-draft", os.path.join(a.work, "model.sanitized.json")],
                        "plan_check_sanitize", allow_fail=True)
        sanitized = read_json(os.path.join(a.work, "model.sanitized.json"), None)
        report = read_json(os.path.join(a.work, "plan_check.json"), {}) or {}
        model_meta = {"path": "work/" + os.path.basename(model_path), "strict_rc": strict_rc,
                      "sanitize_rc": san_rc, "strict_ok": strict_rc == 0,
                      "dropped": [{"kind": d.get("kind"), "id": d.get("id"), "reason": d.get("reason")}
                                  for d in report.get("dropped", [])]}
        if sanitized and san_rc == 0:
            model = sanitized.get("fields") or {}
            log("model plan accepted after sanitising (dropped=%d)" % len(report.get("dropped", [])))
        else:
            log("model plan rejected; delivering rule-derived baseline instead")
        if sanitized and san_rc == 0:
            m = sanitized.get("fields") or {}
            for arr in ("diagnosis", "edit_plan", "outline", "paragraph_map", "argument_map"):
                if m.get(arr):
                    baseline[arr] = m[arr]
            if (m.get("coverage") or {}):
                for d in DIMS:
                    if (m["coverage"].get(d) or {}).get("checked"):
                        baseline["coverage"][d] = m["coverage"][d]
            if m.get("source_map"):
                baseline["source_map"] = m["source_map"]
            if m.get("changes"):
                baseline["changes"] = m["changes"]
            if m.get("uncertainty"):
                baseline["uncertainty"] = list(dict.fromkeys((baseline.get("uncertainty") or []) + m["uncertainty"]))
            if m.get("limits"):
                baseline["limits"] = "；".join(x for x in (baseline.get("limits"), m["limits"]) if x)

    fields = dict(baseline)
    if model_meta.get("dropped"):
        fields["uncertainty"] = (fields.get("uncertainty") or []) + [
            "门禁拦截了 %d 条无法在原文逐字核验的条目（见 work/plan_check.json dropped）"
            % len(model_meta["dropped"])]
    recompute_coverage(fields, len(paras))

    # quote verification against the actual corpus
    quotes = []
    for x in fields.get("diagnosis") or []:
        loc = x.get("location") or {}
        if loc.get("anchor_quote"):
            quotes.append({"claim": "%s %s" % (x.get("issue_id"), x.get("problem", "")[:60]),
                           "source_path": structure.get("file") or "manuscript",
                           "quote": loc["anchor_quote"], "locator": loc.get("paragraph_id")})
    write_json(os.path.join(a.work, "quotes.json"), quotes)
    run([os.path.join(HERE, "quote_check.py"), "--evidence", os.path.join(a.work, "quotes.json"),
         "--corpus", os.path.join(a.work, "corpus.txt"), "--out",
         os.path.join(a.work, "quote_check.json")], "quote_check", allow_fail=True)
    qc = read_json(os.path.join(a.work, "quote_check.json"), {}) or {}
    if qc.get("failed"):
        bad_rows = [r for r in qc.get("results", []) if r.get("status") != "ok"]
        bad_ids = {str(r.get("claim", "")).split()[0] for r in bad_rows}
        fields["diagnosis"] = [x for x in fields.get("diagnosis") or [] if x.get("issue_id") not in bad_ids]
        keep = {x.get("issue_id") for x in fields["diagnosis"]}
        fields["edit_plan"] = [e for e in fields.get("edit_plan") or [] if e.get("issue_id") in keep]
        fields["uncertainty"] = (fields.get("uncertainty") or []) + [
            "%d 条诊断因引文未能逐字核验被移除" % qc.get("failed", 0)]
        recompute_coverage(fields, len(paras))

    # rebuild bookkeeping from the final (possibly sanitised) diagnosis so nothing dangles
    para_by_id = {p.get("paragraph_id"): p for p in paras}
    fields["source_map"] = []
    for x in fields.get("diagnosis") or []:
        loc = x.get("location") or {}
        p = para_by_id.get(loc.get("paragraph_id")) or {}
        fields["source_map"].append({
            "claim": (x.get("problem") or "")[:120],
            "value": loc.get("anchor_quote", ""),
            "source_path": structure.get("file") or "manuscript",
            "locator": "%s L%s-L%s" % (loc.get("paragraph_id", "?"),
                                       p.get("start_line", "?"), p.get("end_line", "?"))})
    fields["changes"] = []
    for e in fields.get("edit_plan") or []:
        tgt = e.get("target") or {}
        p = para_by_id.get(tgt.get("paragraph_id")) or {}
        fields["changes"].append({
            "target": tgt, "type": e.get("action"),
            "before": (p.get("text") or "")[:160],
            "after": "建议动作（原稿未改动）：" + (e.get("instruction") or "")[:120],
            "reason": e.get("expected_effect") or ""})

    # fact guard: numbers/citations in the narrative must come from the corpus
    removed_numbers = []
    for _ in range(3):
        with open(os.path.join(a.work, "plan_text.txt"), "w", encoding="utf-8") as fh:
            fh.write(plan_text(fields))
        run([os.path.join(HERE, "kernel.py"), "verify", "--text", os.path.join(a.work, "plan_text.txt"),
             "--evidence-dir", a.work, "--out", a.work], "verify", allow_fail=True)
        claims = read_json(os.path.join(a.work, "claims.json"), {}) or {}
        if not claims.get("unsupported_numbers") and not claims.get("citations_not_in_sources"):
            break
        gone = scrub_numbers(fields, claims.get("unsupported_numbers") or [])
        removed_numbers += gone
        if claims.get("citations_not_in_sources"):
            fields["uncertainty"] = (fields.get("uncertainty") or []) + [
                "以下引用标记未出现在材料中，未纳入方案：%s"
                % "、".join(claims["citations_not_in_sources"][:5])]
            break
        if not gone:
            break
    claims = read_json(os.path.join(a.work, "claims.json"), {}) or {}
    if removed_numbers:
        fields["uncertainty"] = (fields.get("uncertainty") or []) + [
            "诊断叙述中未能回溯到原文的数值已替换为“（数值待核）”：%s" % "、".join(sorted(set(removed_numbers))[:8])]
    fields["fact_guard"] = {
        "numbers_unbound": claims.get("unsupported_numbers") or [],
        "citations_not_in_sources": claims.get("citations_not_in_sources") or [],
        "quotes_checked": "%d/%d" % ((qc.get("total", 0) - qc.get("failed", 0)), qc.get("total", 0)),
        "verdict": "pass" if not (claims.get("unsupported_numbers") or claims.get("citations_not_in_sources")) else "review",
    }

    has_issues = bool(fields.get("diagnosis"))
    strict_ok = bool(model_meta.get("strict_ok"))
    status = "ok" if (model is not None and strict_ok and has_issues) else "partial"
    if not has_issues:
        fields["coverage"]["no_issues_found"] = True
        status = "partial"
        fields["limits"] = ((fields.get("limits") or "") + "；规则检查未发现可定位问题，结论已按无问题交付，需作者复核").strip("；")
    fields["status"] = status
    fields["case_id"] = case_id
    fields["artifact_path"] = "structure_plan.md"
    fields["artifact_format"] = "md"

    self_check = {
        "runner": "run_case/v1.2.0", "status": status,
        "baseline_used": True, "model_plan_used": bool(model),
        "model_plan": model_meta,
        "quote_check": {"verdict": qc.get("verdict"), "failed": qc.get("failed", 0),
                        "total": qc.get("total", 0)},
        "fact_guard": fields["fact_guard"],
        "paragraphs": len(paras), "issues": len(fields.get("diagnosis") or []),
        "edits": len(fields.get("edit_plan") or []),
        "structure_inferred": bool(structure.get("inferred_sections")),
    }
    check = emit_and_check(fields, status, a.work, a.out, self_check)
    manifest = {"runner": "run_case/v1.2.0", "case_path": case_path, "case_id": case_id,
                "materials": files, "manuscript_hint": file_hint,
                "commands": LOG, "check": check, "finished_at": time.strftime("%Y-%m-%dT%H:%M:%S")}
    write_json(os.path.join(a.work, "run_manifest.json"), manifest)
    result = read_json(os.path.join(a.out, "result.json"), {}) or {}
    print("DELIVERED status=%s issues=%d edits=%d paragraphs=%d check=%s"
          % (result.get("status"), len(result.get("diagnosis") or []),
             len(result.get("edit_plan") or []), len(paras), "PASS" if check.get("ok") else "FAIL"))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:  # noqa: BLE001
        print("ERROR: %s: %s" % (type(exc).__name__, exc))
        sys.exit(1)
