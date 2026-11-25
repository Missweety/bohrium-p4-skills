#!/usr/bin/env python3
"""run_case.py - one command from /input/case.json to /app/output/result.json.

  python3 scripts/run_case.py --case /input/case.json --materials /input \
      --out /app/output --work /app/work

Flow: kernel init -> (edit? edit_svg.py) or (extract -> spec -> svg -> png/pdf ->
check) -> enrich caption/sources/limits/uncertainty -> kernel emit -> kernel check.
No figure is emitted empty: zero parts => status=blocked with explicit evidence.
"""
import argparse
import json
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import kernel as K  # noqa: E402


def run(args, label):
    """Run a sibling script; return (rc, stdout, stderr). Never raise."""
    try:
        p = subprocess.run([sys.executable] + args, capture_output=True, text=True,
                           cwd=HERE, timeout=600)
        return p.returncode, p.stdout.strip(), p.stderr.strip()
    except Exception as exc:  # noqa: BLE001
        return 99, "", "%s: %s" % (label, exc)


def read_json(path, default=None):
    try:
        return json.load(open(path, encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return default


def write_json(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(obj, fh, ensure_ascii=False, indent=1)


def uniq(seq, cap=40):
    out, seen = [], set()
    for x in seq:
        s = str(x).strip()
        if s and s not in seen:
            seen.add(s)
            out.append(s)
    return out[:cap]


def find_input_svg(case, mats):
    for key in ("source_svg", "svg_path", "figure_svg", "svg", "input_svg"):
        v = case.get(key) if isinstance(case, dict) else None
        if isinstance(v, str) and os.path.exists(v):
            return v
    if isinstance(case, dict):
        for v in K.collect_materials(case, os.path.dirname(case.get("_path", "")) or "."):
            if v["path"].lower().endswith(".svg") and os.path.exists(v["path"]):
                return v["path"]
    for m in mats:
        p = m.get("path", "")
        if p.lower().endswith(".svg") and os.path.exists(p):
            return p
    return ""


EDIT_RE = re.compile(r"(编辑|修改|修订|标注|添加标注|改图|在原图|保留(现有|原有).*(结构|SVG)|"
                     r"\bedit\b|revise|annotate|modify|update (the|this)? ?svg|"
                     r"preserve (the )?structure)", re.I)


def is_edit_case(case, task, svg):
    if not svg:
        return False
    if isinstance(case, dict):
        if case.get("edit_instructions") or case.get("edits") or case.get("changes"):
            return True
        if str(case.get("mode", "")).lower() in ("edit", "svg_edit", "revision"):
            return True
    return bool(EDIT_RE.search(task or ""))


def blocked_draft(cid, reason, evidence, files, scanned_lines, extra_limits=None):
    checks = [{"name": "materials_present", "ok": bool(files),
               "detail": "%d material files" % len(files)},
              {"name": "entities_extracted", "ok": False,
               "detail": "0 components / 0 connections -> refusing to draw a placeholder"},
              {"name": "no_empty_figure", "ok": True,
               "detail": "no route.svg written for a blocked case"}]
    selfcheck = {"ok": False, "verdict": "BLOCKED", "checks": checks,
                 "errors": [reason], "stats": {"components": 0, "connections": 0}}
    limits = ["Blocked: %s" % reason,
              "No diagram was generated; an empty or guessed figure would misrepresent the source."]
    limits += extra_limits or []
    uncertainty = ["Extraction yielded no usable apparatus components or flow relations.",
                   "Evidence checked (file:line / excerpt): %s"
                   % ("; ".join(scanned_lines[:6]) if scanned_lines else "no readable text")]
    return {
        "case_id": cid, "status": "blocked", "source_file": None,
        "exports": [], "preview": {"status": "unavailable", "notes": ["blocked"]},
        "extraction": {"mode": "text_candidates", "files": files,
                       "coverage": {"parts": 0, "connections": 0, "stages": 0},
                       "warnings": [reason] + (extra_limits or [])},
        "element_map": [], "parts": [], "connections": [], "stages": [],
        "route_graph": None,
        "caption": ("No apparatus/route diagram was produced: the supplied materials contain no "
                    "extractable components or connections. Reason: %s. Source files checked: %s."
                    % (reason, ", ".join(os.path.basename(f) for f in files) or "none")),
        "selfcheck": selfcheck,
        "sources": files, "limits": limits, "uncertainty": uncertainty,
        "change_log": "blocked before rendering; no figure emitted",
        "metrics": {"parts": 0, "connections": 0, "stages": 0, "element_map": 0},
        "title": "", "input_files": files,
        "change_details": {"mode": "blocked", "reason": reason},
        "fatal_error": None,
    }


def gate_blocked_draft(cid, reason, code, spec, erep, mfiles):
    """硬门禁失败：保留已抽取的部件/步骤供审计，但绝不出图，selfcheck=FAIL、status=blocked。"""
    parts = spec.get("parts") or []
    stages = spec.get("stages") or []
    conns = spec.get("connections") or []
    checks = [{"name": "entities_extracted", "ok": bool(parts),
               "detail": "%d components" % len(parts)},
              {"name": "connections_extracted", "ok": bool(conns),
               "detail": "%d connections%s" % (len(conns), "" if conns else " (" + reason + ")")},
              {"name": "route_steps_extracted", "ok": code != "no_stages",
               "detail": "%d steps%s" % (len(stages), "" if code != "no_stages" else " (" + reason + ")")},
              {"name": "no_empty_figure", "ok": True,
               "detail": "no route figure written for a gated case"}]
    selfcheck = {"ok": False, "verdict": "FAIL", "checks": checks,
                 "errors": [{"code": code, "detail": reason}], "warnings": [],
                 "stats": {"parts": len(parts), "connections": len(conns), "stages": len(stages)}}
    draft = blocked_draft(cid, reason, erep.get("unresolved") or [], mfiles, [])
    draft.update({
        "parts": parts, "connections": conns, "stages": stages, "selfcheck": selfcheck,
        "extraction": {"mode": erep.get("mode"), "files": erep.get("files") or mfiles,
                       "coverage": erep.get("coverage") or {
                           "parts": len(parts), "connections": len(conns), "stages": len(stages)},
                       "warnings": uniq([reason] + list(erep.get("warnings") or []))},
        "metrics": {"parts": len(parts), "connections": len(conns), "stages": len(stages),
                    "element_map": 0},
        "caption": ("No apparatus/route diagram was produced: %s. Extracted %d components, "
                    "%d directed connections and %d technical-route steps, but the graph is "
                    "incomplete, so drawing a flow figure would be misleading. Checked: %s."
                    % (reason, len(parts), len(conns), len(stages),
                       ", ".join(os.path.basename(f) for f in (erep.get("files") or mfiles)) or "none")),
        "limits": uniq([reason,
                        "No diagram was generated because the extracted graph is incomplete.",
                        "Components and steps remain listed for audit; they are not drawn."]),
        "uncertainty": uniq(["no complete directed connection/step graph could be extracted",
                             "a component-only or empty figure was intentionally not drawn"]),
        "change_details": {"mode": "blocked", "reason": reason, "code": code},
        "fatal_error": reason,
    })
    return draft


def build_caption(spec, graph, status):
    title = (spec.get("figure") or {}).get("title") or graph.get("title") or "Apparatus and technical route"
    parts = graph.get("parts") or []
    conns = graph.get("connections") or []
    stages = graph.get("stages") or []
    kinds = uniq([c.get("kind") for c in conns if c.get("kind")])
    inferred = [p.get("label") for p in parts + stages if (p.get("status") or "") == "inferred"]
    labels = [p.get("label", "") for p in parts][:8]
    bits = ["%s: apparatus with %d components (%s) and %d connectors (%s)."
            % (title, len(parts), "、".join(labels) or "none", len(conns),
               "/".join(kinds) or "none")]
    if stages:
        bits.append("Technical route has %d labeled steps (%s)%s."
                    % (len(stages), " → ".join(str(s.get("label", "")) for s in stages[:5]),
                       "; milestones " + ", ".join(str(s.get("milestone")) for s in stages
                                                    if s.get("milestone"))
                       if any(s.get("milestone") for s in stages) else ""))
    units = spec.get("units") or {}
    bits.append("Units: %s. Scale: %s."
                % (", ".join("%s=%s" % (k, v) for k, v in list(units.items())[:4]) or "qualitative",
                   (spec.get("scale_bar") or {}).get("label", "not to scale")))
    if inferred:
        bits.append("Inferred (not stated verbatim) elements: %s." % "、".join(uniq(inferred, 8)))
    bits.append("Status: %s." % status)
    return " ".join(bits)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--case", default="/input/case.json")
    ap.add_argument("--materials", default="/input")
    ap.add_argument("--out", default="/app/output")
    ap.add_argument("--work", default="/app/work")
    ap.add_argument("--name", default="route")
    ap.add_argument("--force-mode", choices=["", "generate", "edit"], default="")
    a = ap.parse_args()
    # sub-scripts run with cwd=HERE, so every user-supplied path must be made
    # absolute first; relative paths used to fail as "case.json not found"
    a.case = os.path.abspath(os.path.expanduser(a.case))
    a.materials = os.path.abspath(os.path.expanduser(a.materials))
    a.out = os.path.abspath(os.path.expanduser(a.out))
    a.work = os.path.abspath(os.path.expanduser(a.work))
    os.makedirs(a.out, exist_ok=True)
    os.makedirs(a.work, exist_ok=True)

    rc, so, se = run(["kernel.py", "init", "--case", a.case, "--materials", a.materials,
                      "--work", a.work], "init")
    if rc != 0:
        print("init failed:", so, se)
    meta = read_json(os.path.join(a.work, "case.json"), {}) or {}
    cid = meta.get("case_id") or "local-unknown"
    task = meta.get("task_text") or ""
    mats = meta.get("materials") or []
    mfiles = [m.get("path") for m in mats if m.get("path")]

    if meta.get("blocked"):
        draft = blocked_draft(cid, meta["blocked"], [], mfiles, [])
        draft["caption"] = ("Blocked: %s. No diagram can be produced from an unreadable case "
                            "description; supply a valid /input/case.json." % meta["blocked"])
        return finish(a, draft, cid)

    case = read_json(a.case, {}) if os.path.exists(a.case) else {}
    case["_path"] = a.case
    svg_in = find_input_svg(case, mats)
    mode = a.force_mode or ("edit" if is_edit_case(case, task, svg_in) else "generate")

    if mode == "edit":
        return run_edit(a, case, cid, svg_in, task, mfiles)
    return run_generate(a, case, cid, task, mfiles)


def run_edit(a, case, cid, svg_in, task, mfiles):
    if not svg_in:
        draft = blocked_draft(cid, "edit requested but no input SVG found", [], mfiles, [])
        return finish(a, draft, cid)
    rc, so, se = run(["edit_svg.py", "--svg", svg_in, "--case", a.case,
                      "--out", a.out, "--name", a.name], "edit")
    log = read_json(os.path.join(a.out, "edit_log.json"), {}) or {}
    sc = read_json(os.path.join(a.out, "edit_selfcheck.json"), {}) or {}
    emap = read_json(os.path.join(a.out, "edit_element_map.json"), []) or []
    changes = log.get("changes") or []
    if rc != 0 or not changes:
        # a no-op edit must not leave an unchanged figure next to a blocked result
        for f in ("route.svg", "route.png", "route.pdf", "source_figure.svg"):
            p = os.path.join(a.out, f)
            if os.path.exists(p):
                os.remove(p)
        reason = ("edit produced no change" if rc == 0 else
                  "edit_svg failed: %s" % (se or so or "rc=%d" % rc))
        draft = blocked_draft(cid, reason, changes, mfiles,
                              ["%s: %s" % (os.path.basename(svg_in), (changes[0]["quote"] if changes else task[:120]))])
        return finish(a, draft, cid)
    cap = ("Edited figure %s: %d change(s) applied while preserving untouched structure. "
           "Source sha256 %s → output %s. Changes: %s."
           % (os.path.basename(svg_in), len(changes), log.get("source_sha256", "")[:12],
              log.get("output_sha256", "")[:12],
              "; ".join("%s: %s → %s" % (c["element"], c["before"] or "∅", c["after"])
                        for c in changes[:6])))
    exports = []
    engine = log.get("raster", {}).get("engine") or "svg-rasterizer"
    if log.get("raster", {}).get("ok"):
        for fmt in ("png", "pdf"):
            p = os.path.join(a.out, a.name + "." + fmt)
            if os.path.exists(p):
                exports.append({"path": os.path.basename(p), "format": fmt,
                                "bytes": os.path.getsize(p), "engine": engine})
    limits = list(log.get("warnings") or [])
    limits += list(log.get("raster", {}).get("notes") or [])
    if not any(e["format"] == "png" for e in exports):
        limits.append("No SVG rasterizer in runtime; the edited SVG plus structural diff is the "
                      "verified deliverable (no fabricated PNG).")
    draft = {
        "case_id": cid,
        "status": "ok" if (sc.get("ok") and exports) else "partial",
        "source_file": a.name + ".svg",
        "exports": exports,
        "preview": {"status": "ok" if exports else "unavailable",
                    "notes": log.get("raster", {}).get("notes") or []},
        "extraction": {"mode": "svg_edit", "files": mfiles + [svg_in],
                       "coverage": {"changes": len(changes)},
                       "warnings": log.get("warnings") or []},
        "element_map": emap,
        "parts": [], "connections": [], "stages": [],
        "route_graph": {"mode": "svg_edit", "source_sha256": log.get("source_sha256"),
                        "output_sha256": log.get("output_sha256"),
                        "text_nodes": log.get("text_nodes_total"),
                        "text_nodes_changed": log.get("text_nodes_changed")},
        "caption": cap, "selfcheck": sc,
        "sources": uniq(["case.json:edit_instructions", os.path.basename(svg_in)] +
                        [c.get("quote", "") for c in changes]),
        "limits": uniq(limits), "uncertainty": uniq(
            ["inferred annotation: %s" % c["after"] for c in changes if c.get("inferred")]),
        "change_log": ("edited existing SVG; %d change(s); structure preserved; "
                       "source sha256=%s output sha256=%s"
                       % (len(changes), log.get("source_sha256"), log.get("output_sha256"))),
        "metrics": {"changes": len(changes), "text_nodes": log.get("text_nodes_total"),
                    "text_nodes_changed": log.get("text_nodes_changed")},
        "title": os.path.basename(svg_in),
        "input_files": mfiles + [svg_in],
        "change_details": log,
    }
    return finish(a, draft, cid)


def scanned_evidence(mats):
    out = []
    for m in mats[:8]:
        p = m.get("path")
        if not p or not os.path.isfile(p):
            continue
        try:
            txt = K.extract(p)
        except Exception:  # noqa: BLE001
            continue
        for i, line in enumerate(str(txt).splitlines(), 1):
            s = line.strip()
            if s and not s.startswith("["):
                out.append("%s:L%d %s" % (os.path.basename(p), i, s[:120]))
                break
    return out


def run_generate(a, case, cid, task, mfiles):
    spec_path = os.path.join(a.out, "spec.json")
    rc, so, se = run(["route_extract.py", "--case", a.case, "--materials", a.materials,
                      "--out", a.out, "--name", a.name], "extract")
    spec = read_json(spec_path, {}) or {}
    erep = read_json(os.path.join(a.out, "extraction_report.json"), {}) or {}
    parts = spec.get("parts") or []
    pid2label = {p.get("id"): p.get("label", "") for p in parts}
    edges = ["%s→%s" % (pid2label.get(c.get("from"), c.get("from")),
                        pid2label.get(c.get("to"), c.get("to")))
             for c in spec.get("connections") or []]
    print("extracted parts (%d): %s" % (len(parts), ", ".join(pid2label.values())))
    print("extracted edges (%d): %s" % (len(edges), ", ".join(edges)))
    if rc != 0 or not parts:
        reason = ("extraction found 0 components" if not parts else
                  "route_extract failed: %s" % (se or so))
        extra = list(erep.get("warnings") or [])
        draft = blocked_draft(cid, reason, erep.get("unresolved"), mfiles,
                              scanned_evidence([{"path": p} for p in mfiles]), extra)
        draft["extraction"]["files"] = erep.get("files") or mfiles
        draft["extraction"]["warnings"] = uniq([reason] + extra)
        return finish(a, draft, cid)

    # 硬门禁：0 连线 => 无真实流向，selfcheck FAIL + blocked，且不写任何图。
    # 阶段缺失不再整体阻断：装置区照常出图，技术路线区如实写“材料未给出”，status=partial。
    gate = None
    if not (spec.get("connections") or []):
        gate = ("no explicit connections/flows extracted", "no_connections")
    if gate:
        for f in ("route.svg", "route.png", "route.pdf"):
            p = os.path.join(a.out, f)
            if os.path.exists(p):
                os.remove(p)
        draft = gate_blocked_draft(cid, gate[0], gate[1], spec, erep, mfiles)
        return finish(a, draft, cid)

    # render SVG + graph + element_map
    rc1, so1, se1 = run(["route_spec.py", "build", "--spec", spec_path,
                         "--out", a.out, "--name", a.name], "build")
    svg_path = os.path.join(a.out, a.name + ".svg")
    if not os.path.exists(svg_path):
        draft = blocked_draft(cid, "SVG rendering failed: %s" % (se1 or so1), [], mfiles, [])
        return finish(a, draft, cid)

    # raster previews
    rc2, so2, se2 = run(["export_preview.py", "--svg", svg_path, "--spec", spec_path,
                         "--out", a.out, "--name", a.name, "--formats", "png,pdf",
                         "--dpi", "150"], "export")
    exports_meta = read_json(os.path.join(a.out, "exports.json"), {}) or {}
    exports = exports_meta.get("exports") or []
    engines = {e.get("engine") for e in exports}
    png = os.path.join(a.out, a.name + ".png")
    pdf = os.path.join(a.out, a.name + ".pdf")
    have_png = os.path.exists(png) and os.path.getsize(png) > 0
    have_pdf = os.path.exists(pdf) and os.path.getsize(pdf) > 0

    # structural selfcheck (require preview when we actually have it)
    rc3, so3, se3 = run(["route_check.py", "--out", a.out, "--name", a.name] +
                        (["--require-preview"] if have_png else []), "check")
    sc = read_json(os.path.join(a.out, "selfcheck.json"), {}) or {}

    graph = read_json(os.path.join(a.out, a.name + "_graph.json"), {}) or {}
    emap = read_json(os.path.join(a.out, "element_map.json"), []) or []
    parts = graph.get("parts") or []
    conns = graph.get("connections") or []
    stages = graph.get("stages") or []

    # status is honest: ok only with a real SVG, connectors, PNG+PDF and PASS check
    reasons = []
    if not have_png or not have_pdf:
        reasons.append("PNG/PDF preview missing")
    if not conns:
        reasons.append("no explicit connections/flows extracted")
    if not sc.get("ok"):
        reasons.append("selfcheck did not pass")
    if "stdlib-raster" in engines:
        reasons.append("matplotlib unavailable; layout-only raster fallback")
    if len(stages) < 2:
        reasons.append("fewer than 2 technical-route stages")
    status = "ok" if not reasons else "partial"

    # evidence / limits / uncertainty
    inferred_parts = [p.get("label") for p in parts if p.get("status") == "inferred"]
    inferred_conns = ["%s→%s" % (c.get("from"), c.get("to")) for c in conns
                      if c.get("status") == "inferred"]
    inferred_stages = [s.get("label") for s in stages if s.get("status") == "inferred"]
    limits = list(erep.get("warnings") or [])
    if not (spec.get("units") or {}):
        limits.append("Units were not specified; the figure is qualitative (no numeric scale).")
    if "stdlib-raster" in engines:
        limits.append("Matplotlib unavailable; PNG/PDF are layout-only fallbacks and CJK text is "
                      "authoritative in the SVG.")
    if erep.get("evidence_missing"):
        limits.append("%d components lacked an explicit evidence locator and were marked inferred."
                      % len(erep["evidence_missing"]))
    for note in exports_meta.get("notes") or []:
        limits.append(note)
    uncertainty = ["inferred component: %s" % x for x in uniq(inferred_parts, 12)]
    uncertainty += ["inferred connection: %s" % x for x in uniq(inferred_conns, 12)]
    uncertainty += ["inferred stage: %s" % x for x in uniq(inferred_stages, 12)]
    for u in erep.get("unspecified") or []:
        uncertainty.append("unspecified dimension: %s (%s)"
                           % (u.get("quote"), u.get("locator")))
        limits.append("Source explicitly leaves a quantity unspecified: %s" % u.get("quote"))
    if not (spec.get("units") or {}):
        uncertainty.append("unspecified dimension/units; no scale bar values claimed")
    for c in conns:
        if not c.get("quote"):
            uncertainty.append("connection %s has no verbatim quote; treated as inferred" % c.get("id"))
    if any(w.get("code") == "missing_milestone" for w in sc.get("warnings") or []):
        uncertainty.append("source does not declare a milestone; no milestone marker was fabricated")
        limits.append("Source does not declare a milestone; the figure omits milestone markers.")
    uncertainty = uniq(uncertainty)

    # element_map normalization: guarantee locator/quote/status on every row
    for row in emap:
        row.setdefault("locator", row.get("source", ""))
        row.setdefault("quote", "")
        if row.get("type") in ("part", "connection", "stage"):
            if not row.get("source") and row.get("status") != "inferred":
                row["status"] = "inferred"
                uncertainty.append("element %s had no source locator; marked inferred"
                                   % row.get("element"))

    files = erep.get("files") or mfiles
    sources = uniq(["%s:%s" % (f, (erep.get("coverage") or {}).get("mentions", ""))
                    for f in files] +
                   [r.get("source") for r in emap if r.get("source")
                    and not str(r["source"]).startswith("generated")])

    caption = build_caption(spec, graph, status)
    with open(os.path.join(a.out, "caption.md"), "w", encoding="utf-8") as fh:
        fh.write(caption + "\n")

    draft = {
        "case_id": cid, "status": status, "source_file": a.name + ".svg",
        "exports": exports,
        "preview": {"status": "ok" if have_png else "unavailable",
                    "notes": exports_meta.get("notes") or []},
        "extraction": {"mode": erep.get("mode"), "files": files,
                       "coverage": erep.get("coverage") or {},
                       "warnings": erep.get("warnings") or []},
        "element_map": emap, "parts": parts, "connections": conns, "stages": stages,
        "route_graph": graph,
        "legend": graph.get("legend") or [],
        "units": spec.get("units") or {},
        "scale_bar": spec.get("scale_bar") or {},
        "caption": caption, "selfcheck": sc,
        "sources": sources, "limits": uniq(limits), "uncertainty": uncertainty,
        "change_log": "initial generation from %s material file(s); no manual edits"
                      % len(files),
        "metrics": {"parts": len(parts), "connections": len(conns), "stages": len(stages),
                    "element_map": len(emap), "legend": len((graph.get("legend") or [])),
                    "typed_parts": sum(1 for p in parts if p.get("type") not in (None, "", "other"))},
        "title": (spec.get("figure") or {}).get("title", ""),
        "input_files": files,
        "change_details": {"mode": mode_of(erep), "extraction_mode": erep.get("mode")},
        "fatal_error": None if status != "blocked" else "blocked",
    }
    return finish(a, draft, cid)


def mode_of(erep):
    return erep.get("mode") or "generate"


def finish(a, draft, cid):
    draft_path = os.path.join(a.work, "draft.json")
    write_json(draft_path, draft)
    rc, so, se = run(["kernel.py", "emit", "--draft", draft_path, "--out", a.out,
                      "--work", a.work, "--case-id", cid], "emit")
    print(so or se)
    rc2, so2, se2 = run(["kernel.py", "check", "--result",
                         os.path.join(a.out, "result.json"), "--work", a.work], "check")
    print(so2 or se2)
    return rc2


if __name__ == "__main__":
    sys.exit(main())
