#!/usr/bin/env python3
"""run_case.py - one-command end-to-end entry point.

  python3 scripts/run_case.py --case /input/case.json --materials /input \
          --out /app/output --work /app/work

Steps: contract init -> extract -> (blocked | layout -> render -> export -> selfcheck)
-> emit result.json. Edit requests are routed to edit.py. Exceptions still emit a valid
result.json with status=failed so the harness never receives an empty directory.
"""
import argparse
import json
import os
import shutil
import sys
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import check  # noqa: E402
import edit  # noqa: E402
import emit_result  # noqa: E402
import export  # noqa: E402
import extract  # noqa: E402
import graphlib as G  # noqa: E402
import kernel  # noqa: E402
import layout as L  # noqa: E402
import render  # noqa: E402

ARTIFACTS = ("figure.svg", "figure.png", "figure.pdf", "result.json",
             "element_map.json", "selfcheck.json", "caption.md",
             "edit_log.json", "edit_result.json")


def base_caption(spec):
    n, e = len(spec.get("nodes", [])), len(spec.get("edges", []))
    if not n or not e:
        return ("No evidence-backed mechanism could be extracted (entities=%d, relations=%d); "
                "figure withheld rather than drawing an empty placeholder." % (n, e))
    kinds = {}
    for x in spec["edges"]:
        kinds[x["kind"]] = kinds.get(x["kind"], 0) + 1
    kind_txt = ", ".join("%s=%d" % (k, v) for k, v in kinds.items())
    comps = {}
    for x in spec["nodes"]:
        comps[x["compartment"]] = comps.get(x["compartment"], 0) + 1
    comp_txt = ", ".join("%s=%d" % (c, comps.get(c, 0)) for c, _ in G.COMPARTMENTS)
    return ("Biological mechanism/pathway diagram: %d entities (%s), %d directed relations "
            "(%s). Arrow semantics: activation=filled arrow, inhibition=T-bar, binding=open "
            "circle, modification=dashed line + diamond, transport=dash-dot, flow=thin arrow; "
            "dashed outline = inferred. Every entity/edge is traced in element_map.json."
            % (n, comp_txt, e, kind_txt))


def write_selfcheck(work, out, res):
    json.dump(res, open(os.path.join(work, "selfcheck.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    json.dump(res, open(os.path.join(out, "selfcheck.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)


def normalize_spec(raw, wc):
    """Accept a hand/vision-authored spec (see references/pathway-spec-schema.md)."""
    spec = dict(raw)
    spec.setdefault("mode", "create")
    spec.setdefault("case_id", wc.get("case_id"))
    if not spec.get("materials"):
        spec["materials"] = [{"path": m.get("path"), "exists": True,
                              "chars": 0} for m in wc.get("materials", [])]
    default_file = os.path.basename((wc.get("materials") or [{}])[0].get("path", "") or "case.json")
    nodes, by_key = [], {}
    for i, n in enumerate(spec.get("nodes", [])):
        label = str(n.get("label") or n.get("name") or "").strip()
        if not label:
            continue
        raw_type = n.get("type")
        etype = G.norm_type(raw_type) if raw_type else G.heuristic_type(label)
        comp = G.norm_compartment(n.get("compartment"))
        inferred = False
        if not comp:
            comp = G.heuristic_compartment(label, etype)
            inferred = True
        ev = n.get("evidence") or []
        if isinstance(ev, str):
            ev = [{"file": default_file, "locator": "authored", "quote": ev, "verified": True}]
        ev = [e if isinstance(e, dict) else {"file": default_file, "locator": "authored",
                                             "quote": str(e), "verified": True} for e in ev]
        for e in ev:
            e.setdefault("file", default_file)
            e.setdefault("locator", "authored")
            e.setdefault("quote", "")
            e.setdefault("verified", True)
        n2 = {"id": n.get("id") or G.slug(label), "label": label, "type": etype,
              "compartment": comp, "compartment_inferred": inferred,
              "aliases": [str(a) for a in (n.get("aliases") or [])],
              "evidence": ev, "origin": "authored", "status": n.get("status", "stated"),
              "data_ref": n.get("data_ref", "nodes[%d]" % i),
              "note": n.get("note", "")}
        nodes.append(n2)
        by_key[G.node_key(label)] = n2
        for a in n2["aliases"]:
            by_key.setdefault(G.node_key(a), n2)
    edges, seen, unresolved = [], set(), []
    for i, e in enumerate(spec.get("edges", [])):
        if not isinstance(e, dict):
            continue
        s = by_key.get(G.node_key(e.get("source", "")))
        t = by_key.get(G.node_key(e.get("target", "")))
        k = G.norm_kind(e.get("kind"))
        if not s or not t or not k:
            unresolved.append({"source_text": e.get("source"), "target_text": e.get("target"),
                               "kind_raw": e.get("kind"), "reason": "manual spec endpoint/kind invalid"})
            continue
        key = (s["id"], t["id"], k)
        if key in seen:
            continue
        seen.add(key)
        ev = e.get("evidence") or []
        if isinstance(ev, str):
            ev = [{"file": default_file, "locator": "authored", "quote": ev, "verified": True}]
        ev = [x if isinstance(x, dict) else {"file": default_file, "locator": "authored",
                                             "quote": str(x), "verified": True} for x in ev]
        for x in ev:
            x.setdefault("file", default_file)
            x.setdefault("locator", "authored")
            x.setdefault("quote", "")
            x.setdefault("verified", True)
        edges.append({"id": e.get("id") or "e%d" % (len(edges) + 1),
                      "source": s["id"], "target": t["id"], "kind": k,
                      "status": e.get("status", "stated"), "evidence": ev,
                      "label": G.KINDS[k][4], "note": e.get("note", ""),
                      "data_ref": e.get("data_ref", "edges[%d]" % i)})
    deg = {n["id"]: 0 for n in nodes}
    for e in edges:
        deg[e["source"]] = deg.get(e["source"], 0) + 1
        deg[e["target"]] = deg.get(e["target"], 0) + 1
    spec.update({
        "nodes": nodes, "edges": edges,
        "compartments": [{"id": c, "label": lbl, "order": G.CANON_ORDER[c]}
                         for c, lbl in G.COMPARTMENTS],
        "isolated_entities": [n["label"] for n in nodes if deg.get(n["id"], 0) == 0],
        "conflicts": list(spec.get("conflicts") or []),
        "unresolved_edges": list(spec.get("unresolved_edges") or []) + unresolved,
        "uncertainty": list(spec.get("uncertainty") or []),
        "limits": list(spec.get("limits") or []),
    })
    for n in nodes:
        if n["compartment_inferred"]:
            spec["uncertainty"].append(
                "%s: compartment inferred as %s in authored spec." % (n["label"], n["compartment"]))
    return spec


def run_edit(work, out, spec):
    res = edit.run(work, out)
    # edit_log.json is documented as an output; publish it next to the figure
    for name in ("edit_log.json", "edit_result.json"):
        src = os.path.join(work, name)
        if os.path.exists(src):
            shutil.copyfile(src, os.path.join(out, name))
    ok = res.get("ok")
    export_errors = [str(e) for e in (res.get("export") or {}).get("errors", [])]
    errors = list(res.get("errors", []))
    if not ok and not errors:
        # never report FAIL with an empty reason list
        errors = export_errors or ["edit finished but export did not pass its quality gate"]
    sc = {
        "verdict": "PASS" if ok else "FAIL",
        "errors": errors,
        "warnings": [] if res.get("structure_preserved", True) else ["structure not preserved"],
        "stats": {"mode": "edit", "changes": len(res.get("changes", [])),
                  "applied": sum(1 for c in res.get("changes", []) if c.get("applied")),
                  "structure_preserved": res.get("structure_preserved"),
                  "element_map_rows": len(res.get("element_map", {}).get("rows", [])),
                  "text_elements": len(res.get("element_map", {}).get("rows", []))},
    }
    write_selfcheck(work, out, sc)
    exp = res.get("export", {})
    json.dump(exp, open(os.path.join(work, "export.json"), "w", encoding="utf-8"), indent=1)
    return sc


def run_create(work, out, spec, title):
    nodes, edges = spec.get("nodes", []), spec.get("edges", [])
    if not nodes or not edges:
        sc = {"verdict": "FAIL",
              "errors": ["empty_mechanism: entities=%d relations=%d" % (len(nodes), len(edges))],
              "warnings": ["figure withheld (never emit an empty/placeholder diagram)"],
              "stats": {"nodes": len(nodes), "edges": len(edges), "text_elements": 0}}
        write_selfcheck(work, out, sc)
        return sc

    lay = L.plan(spec)
    json.dump(lay, open(os.path.join(work, "layout.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    caption = base_caption(spec)
    svg = render.render(title, spec, lay, caption)
    open(os.path.join(out, "figure.svg"), "w", encoding="utf-8").write(svg)
    emap = render.build_element_map(spec, lay)
    json.dump(emap, open(os.path.join(out, "element_map.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    json.dump(render.build_graph(spec, lay),
              open(os.path.join(work, "graph.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    exp = export.run(os.path.join(out, "figure.svg"), out, work,
                     os.path.join(work, "layout.json"), title=title)
    json.dump(exp, open(os.path.join(work, "export.json"), "w", encoding="utf-8"), indent=1)
    sc = check.run(out, work)
    write_selfcheck(work, out, sc)
    print("run: nodes=%d edges=%d kinds=%s selfcheck=%s export=%s"
          % (len(nodes), len(edges), ",".join(lay["used_kinds"]), sc["verdict"], exp["ok"]))
    return sc


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--case", default="/input/case.json")
    ap.add_argument("--materials", default="/input")
    ap.add_argument("--out", default="/app/output")
    ap.add_argument("--work", default="/app/work")
    ap.add_argument("--title", default="")
    ap.add_argument("--contract", default="")
    ap.add_argument("--spec", default="",
                    help="hand/vision-authored spec.json (skips automatic extraction)")
    ap.add_argument("--trust-evidence", action="store_true",
                    help="manual path: quotes were authored from reading the figure/PDF; "
                         "disable machine quote-match (still requires non-empty source+quote)")
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    os.makedirs(a.work, exist_ok=True)
    os.environ["MECH_WORK"] = a.work
    os.environ["MECH_OUT"] = a.out
    for name in ARTIFACTS:
        p = os.path.join(a.out, name)
        if os.path.exists(p):
            os.remove(p)
    # keep the work dir but clear derived files
    for name in ("spec.json", "layout.json", "selfcheck.json", "export.json",
                 "graph.json", "edit_result.json", "edit_log.json"):
        p = os.path.join(a.work, name)
        if os.path.exists(p):
            os.remove(p)

    wc = {}
    try:
        kernel.cmd_init(argparse.Namespace(case=a.case, materials=a.materials,
                                           work=a.work, contract=a.contract))
        wc = json.load(open(os.path.join(a.work, "case.json"), encoding="utf-8"))
        if a.spec:
            raw = json.load(open(a.spec, encoding="utf-8"))
            spec = normalize_spec(raw, wc)
            if a.trust_evidence:
                os.environ["MECH_TRUST_EVIDENCE"] = "1"
                for n in spec["nodes"]:
                    for ev in n.get("evidence", []):
                        ev["verified"] = False
                for e in spec["edges"]:
                    for ev in e.get("evidence", []):
                        ev["verified"] = False
                spec["limits"].append(
                    "Evidence quotes were authored from visual/PDF inspection; the machine "
                    "quote-match gate was disabled for this manual path.")
            json.dump(spec, open(os.path.join(a.work, "spec.json"), "w", encoding="utf-8"),
                      ensure_ascii=False, indent=1)
        else:
            extract.build()
            spec = json.load(open(os.path.join(a.work, "spec.json"), encoding="utf-8"))
        case = {}
        if wc.get("case_path") and os.path.exists(wc["case_path"]):
            try:
                case = json.load(open(wc["case_path"], encoding="utf-8"))
            except Exception:  # noqa: BLE001
                case = {}
        title = a.title or (case.get("title") if isinstance(case, dict) else "") or \
            "生物机制图与通路图 / Mechanism & pathway diagram"
        if spec.get("mode") == "edit":
            run_edit(a.work, a.out, spec)
        else:
            run_create(a.work, a.out, spec, title)
    except Exception as exc:  # noqa: BLE001
        traceback.print_exc()
        err = "%s: %s" % (type(exc).__name__, exc)
        write_selfcheck(a.work, a.out,
                        {"verdict": "FAIL", "errors": [err], "warnings": [],
                         "stats": {"exception": err}})
        # write a minimal spec so emit can still produce a complete, honest result
        if not os.path.exists(os.path.join(a.work, "spec.json")):
            json.dump({"mode": (wc.get("mode") or "create") if isinstance(wc, dict) else "create",
                       "nodes": [], "edges": [], "compartments": [],
                       "isolated_entities": [], "conflicts": [], "unresolved_edges": [],
                       "uncertainty": ["pipeline exception: " + err], "limits": [],
                       "materials": []},
                      open(os.path.join(a.work, "spec.json"), "w", encoding="utf-8"),
                      ensure_ascii=False, indent=1)
        if not os.path.exists(os.path.join(a.work, "case.json")):
            json.dump({"case_id": "local-error", "contract_fields": kernel.DEFAULT_CONTRACT,
                       "materials": [], "case_sha256": ""},
                      open(os.path.join(a.work, "case.json"), "w", encoding="utf-8"),
                      ensure_ascii=False, indent=1)

    emit_result.cmd_emit(argparse.Namespace(work=a.work, out=a.out))
    # kernel-level contract validation (non-fatal print; result.json already written)
    try:
        kernel.cmd_check(argparse.Namespace(result=os.path.join(a.out, "result.json"),
                                            work=a.work))
    except SystemExit:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
