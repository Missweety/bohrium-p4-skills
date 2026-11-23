#!/usr/bin/env python3
"""emit_result.py - assemble result.json with full contract coverage (no "fields" wrapper).

Strategy: build the rich canonical payload first, then for every field the case's
output_contract names, either keep the same-named value or fill it through alias
normalisation (kernel.canonical). Unknown fields become null and are listed in
`unmapped_contract_fields` + `uncertainty` rather than being silently dropped.

status is never "ok" unless selfcheck=PASS and every declared deliverable exists.
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import graphlib as G  # noqa: E402
import kernel  # noqa: E402

CORE = ["case_id", "status", "mode", "source_file", "figure_svg", "figure_png",
        "figure_pdf", "exports", "deliverables", "element_map", "element_map_file",
        "element_map_counts", "caption", "caption_file", "selfcheck", "selfcheck_file",
        "mechanism_graph", "nodes", "edges", "compartments", "isolated_entities",
        "conflicts", "unresolved_edges", "limits", "uncertainty", "sources",
        "change_log", "change_details", "metrics", "input_files", "blocked_reason",
        "unmapped_contract_fields"]


def jload(path, default):
    try:
        return json.load(open(path, encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return default


def rel(out, p):
    return os.path.relpath(p, out) if p else None


def deliverable(out, name, role, fmt=None):
    p = os.path.join(out, name)
    exists = os.path.exists(p)
    return {"path": name, "role": role, "format": fmt or os.path.splitext(name)[1].lstrip("."),
            "exists": exists, "bytes": os.path.getsize(p) if exists else 0,
            "sha256": kernel.sha256_file(p) if exists else ""}


def build_caption(spec, lay, sc, exp, mode="create", edit=None):
    if mode == "edit":
        edit = edit or {}
        ch = edit.get("changes", [])
        applied = sum(1 for c in ch if c.get("applied"))
        return ("生物机制/通路图（编辑）：在原始 SVG 上就地修改 %d 处（%s），未重建图形；"
                "编辑前后 SHA-256 分别为 %s… 与 %s…，删除元素 %d 个，结构保持=%s。"
                "输出仍为可编辑 SVG（真实 <text>）并导出 PNG/PDF。"
                % (applied, "、".join(c["op"] for c in ch if c.get("applied")) or "无",
                   (edit.get("before_sha256") or "")[:12], (edit.get("after_sha256") or "")[:12],
                   edit.get("removed_elements", 0), edit.get("structure_preserved")))
    n, e = len(spec.get("nodes", [])), len(spec.get("edges", []))
    kinds = {}
    for x in spec.get("edges", []):
        kinds[x["kind"]] = kinds.get(x["kind"], 0) + 1
    kind_txt = "、".join("%s %d" % (G.KINDS[k][4], v) for k, v in kinds.items()) or "无"
    comp = {}
    for x in spec.get("nodes", []):
        comp[x["compartment"]] = comp.get(x["compartment"], 0) + 1
    comp_txt = "、".join("%s %d" % (G.CANON_LABEL[c].split("/")[0].strip(), comp.get(c, 0))
                         for c, _ in G.COMPARTMENTS)
    rows = (sc.get("stats", {}) or {}).get("total_provenance_rows", 0)
    ver = (sc.get("stats", {}) or {}).get("verified_quotes", 0)
    mats = [os.path.basename(m.get("path", "")) for m in spec.get("materials", [])
            if m.get("exists")]
    if n == 0 or e == 0:
        return ("生物机制/通路图：未能从所给材料中抽取到可核验的实体与关系（entities=%d, "
                "relations=%d），因此不出图；原因与证据见 uncertainty/sources，避免生成空图或"
                "编造机制。" % (n, e))
    text = ("生物机制图/通路图。共 %d 个实体（%s），按区室分为 %s；%d 条有向关系（%s）。"
            "箭头语义：实心箭头=激活，T 形端=抑制，空心圆端=结合/募集，虚线+菱形=修饰，"
            "点划线+箭头=转运，细箭头=流向；实线为材料明确，虚线轮廓/虚线箭头为推断。"
            % (n, "、".join(sorted({x["type"] for x in spec["nodes"]})), comp_txt, e, kind_txt))
    text += ("证据：%d/%d 条实体/关系在 element_map 中给出文件、页码/行号与原文引文；"
             "带 * 的区室为依据名称/类型的推断。冲突 %d 条、孤立实体 %s、未解决关系 %d 条"
             "（未绘制）。"
             % (ver, rows, len(spec.get("conflicts", [])),
                "、".join(spec.get("isolated_entities", [])) or "无",
                len(spec.get("unresolved_edges", []))))
    if mats:
        text += " 来源材料：%s。" % "、".join(mats[:5])
    if exp and not exp.get("ok"):
        text += " 栅格/PDF 导出不完整（见 limits），SVG 仍可编辑。"
    text += (" 渲染器：%s。" % ",".join(exp.get("methods", [])) if exp else "")
    return text


def cmd_emit(a):
    work, out = a.work, a.out
    wc = jload(os.path.join(work, "case.json"), {})
    contract = wc.get("contract_fields") or list(kernel.DEFAULT_CONTRACT)
    spec = jload(os.path.join(work, "spec.json"), {})
    lay = jload(os.path.join(work, "layout.json"), {})
    sc = jload(os.path.join(work, "selfcheck.json"), {"verdict": "FAIL", "errors": ["no selfcheck"], "warnings": [], "stats": {}})
    exp = jload(os.path.join(work, "export.json"), {})
    graph = jload(os.path.join(work, "graph.json"), {})
    emap = jload(os.path.join(out, "element_map.json"), {"rows": [], "counts": {}})
    edit = jload(os.path.join(work, "edit_result.json"), {})
    mode = "edit" if spec.get("mode") == "edit" or edit else "create"

    limits = list(spec.get("limits", []))
    uncertainty = list(spec.get("uncertainty", []))
    if exp and not exp.get("ok"):
        limits.append("PNG/PDF export incomplete: " + "; ".join(exp.get("errors", [])))
    if exp and "matplotlib" in ",".join(exp.get("methods", [])):
        limits.append("cairosvg/libcairo unavailable in this runtime; PNG/PDF came from the "
                      "matplotlib fallback re-draw (same geometry, font coverage may differ).")
    if exp and "no CJK font" in ",".join(exp.get("methods", [])):
        limits.append("No CJK font was found by the fallback renderer; labels are present in "
                      "the SVG and element_map even if a raster glyph is missing.")
    if mode == "edit":
        for e in edit.get("errors", []):
            uncertainty.append("edit: " + e)
        if not edit.get("structure_preserved", True):
            uncertainty.append("edit removed/reshaped existing elements; review diff.")
    limits.append("Figure is a service-generated reconstruction from the supplied text; "
                  "membrane topology, stoichiometry and kinetics are not inferred beyond "
                  "the extracted statements.")
    limits.append("No external database lookup or network access was used.")

    caption = build_caption(spec, lay, sc, exp, mode, edit)
    open(os.path.join(out, "caption.md"), "w", encoding="utf-8").write(caption + "\n")
    json.dump(emap, open(os.path.join(out, "element_map.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    json.dump(sc, open(os.path.join(out, "selfcheck.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)

    deliverables = []
    for name, role in (("figure.svg", "editable_vector"),
                       ("figure.png", "raster_preview"),
                       ("figure.pdf", "print_pdf"),
                       ("caption.md", "caption"),
                       ("element_map.json", "provenance"),
                       ("selfcheck.json", "self_check")):
        deliverables.append(deliverable(out, name, role))
    exports = [d["path"] for d in deliverables if d["exists"]]

    blocked_reason = ""
    if mode == "create":
        if not spec.get("nodes"):
            blocked_reason = "zero entities extracted from case.json/materials"
        elif not spec.get("edges"):
            blocked_reason = "zero evidence-backed relations extracted; empty mechanism withheld"
        hard = [str(e) for e in sc.get("errors", []) if str(e).startswith("hard_gate:")]
        if not blocked_reason and hard:
            blocked_reason = "; ".join(hard)
        if blocked_reason:
            for name in ("figure.svg", "figure.png", "figure.pdf"):
                p = os.path.join(out, name)
                if os.path.exists(p):
                    os.remove(p)
            deliverables = [d for d in deliverables
                            if d["path"] in ("caption.md", "element_map.json", "selfcheck.json")]
            exports = [d["path"] for d in deliverables if d["exists"]]
            uncertainty.insert(0, blocked_reason + " - no figure emitted (never an empty placeholder).")
            caption = ("生物机制/通路图：未通过完整性硬门（%s）。为避免给出错误机制，"
                       "本次不出图；实体、关系与未解决项保留在 element_map.json 与 "
                       "selfcheck.json 中供复核。" % blocked_reason)
            open(os.path.join(out, "caption.md"), "w", encoding="utf-8").write(caption + "\n")

    has_figs = all(os.path.exists(os.path.join(out, n))
                   for n in ("figure.svg", "figure.png", "figure.pdf"))
    verdict = str(sc.get("verdict", "FAIL")).upper()
    if blocked_reason:
        status = "blocked"
    elif mode == "edit":
        status = "ok" if (edit.get("structure_preserved") and exp.get("ok")
                          and any(c.get("applied") for c in edit.get("changes", []))) else "partial"
    else:
        status = "ok" if (verdict == "PASS" and has_figs and exp.get("ok")) else "partial"
    if mode == "edit" and verdict != "PASS":
        status = "partial" if status == "ok" else status

    sources = []
    for m in spec.get("materials", []):
        sources.append({"file": os.path.basename(m.get("path", "")),
                        "path": m.get("path", ""), "exists": m.get("exists", False),
                        "chars": m.get("chars", 0), "sha256": m.get("sha256", ""),
                        "role": "material"})
    sources.append({"file": "case.json", "path": wc.get("case_path", ""),
                    "sha256": wc.get("case_sha256", ""), "role": "case"})
    if mode == "edit":
        sources.append({"file": os.path.basename(edit.get("source", "")),
                        "path": edit.get("source", ""), "sha256": edit.get("before_sha256", ""),
                        "role": "edited_source_svg"})

    stats = sc.get("stats", {}) or {}
    metrics = dict(stats)
    metrics.update({
        "nodes": len(spec.get("nodes", [])), "edges": len(spec.get("edges", [])),
        "compartments": len([c for c in spec.get("compartments", [])]),
        "element_map_rows": len(emap.get("rows", [])),
        "deliverables": len([d for d in deliverables if d["exists"]]),
        "png_bytes": (exp.get("png", {}) or {}).get("bytes", 0),
        "png_dims": (exp.get("png", {}) or {}).get("dims"),
        "pdf_bytes": (exp.get("pdf", {}) or {}).get("bytes", 0),
        "svg_text_elements": stats.get("text_elements", 0),
        "verified_quotes": stats.get("verified_quotes", 0),
        "isolated_entities": len(spec.get("isolated_entities", [])),
        "conflicts": len(spec.get("conflicts", [])),
        "unresolved_edges": len(spec.get("unresolved_edges", [])),
    })
    if mode == "edit":
        metrics["changed_text_elements"] = edit.get("changed_text_elements", 0)
        metrics["removed_elements"] = edit.get("removed_elements", 0)

    if mode == "edit":
        applied = [c for c in edit.get("changes", []) if c.get("applied")]
        change_log = ("In-place SVG edit: %d/%d operation(s) applied (%s); source %s -> %s; "
                      "structure_preserved=%s."
                      % (len(applied), len(edit.get("changes", [])),
                         ", ".join(c["op"] for c in applied) or "none",
                         (edit.get("before_sha256") or "")[:12],
                         (edit.get("after_sha256") or "")[:12],
                         edit.get("structure_preserved")))
        change_details = {"mode": "edit", "before_sha256": edit.get("before_sha256"),
                          "after_sha256": edit.get("after_sha256"),
                          "changes": edit.get("changes", []),
                          "structure_preserved": edit.get("structure_preserved"),
                          "removed_elements": edit.get("removed_elements", 0),
                          "changed_text_elements": edit.get("changed_text_elements", 0)}
    else:
        change_log = ("Initial mechanism diagram generated from %d material(s): %d entities, "
                      "%d relations, status=%s; case hash %s."
                      % (len([m for m in spec.get("materials", []) if m.get("exists")]),
                         len(spec.get("nodes", [])), len(spec.get("edges", [])), status,
                         (wc.get("case_sha256") or "")[:12]))
        change_details = {"mode": "create", "changes": [],
                          "case_sha256": wc.get("case_sha256")}

    result = {
        "case_id": wc.get("case_id"),
        "status": status,
        "mode": mode,
        "source_file": "figure.svg" if os.path.exists(os.path.join(out, "figure.svg")) else None,
        "figure_svg": "figure.svg" if os.path.exists(os.path.join(out, "figure.svg")) else None,
        "figure_png": "figure.png" if os.path.exists(os.path.join(out, "figure.png")) else None,
        "figure_pdf": "figure.pdf" if os.path.exists(os.path.join(out, "figure.pdf")) else None,
        "exports": exports,
        "deliverables": deliverables,
        "element_map": emap.get("rows", []),
        "element_map_file": "element_map.json",
        "element_map_counts": emap.get("counts", {}),
        "caption": caption,
        "caption_file": "caption.md",
        "selfcheck": sc,
        "selfcheck_file": "selfcheck.json",
        "mechanism_graph": graph or {"nodes": {}, "edges": [],
                                     "compartments": []},
        "nodes": spec.get("nodes", []),
        "edges": spec.get("edges", []),
        "compartments": spec.get("compartments", []),
        "isolated_entities": spec.get("isolated_entities", []),
        "conflicts": spec.get("conflicts", []),
        "unresolved_edges": spec.get("unresolved_edges", []),
        "token_inventory": spec.get("token_inventory", []),
        "token_recall": stats.get("token_recall"),
        "missing_relations": spec.get("missing_relations", []),
        "edge_endpoint_errors": spec.get("edge_endpoint_errors", []),
        "binding_annotations": spec.get("binding_annotations", []),
        "limits": limits,
        "uncertainty": uncertainty,
        "sources": sources,
        "change_log": change_log,
        "change_details": change_details,
        "metrics": metrics,
        "input_files": [{"path": m.get("path"), "exists": m.get("exists", False),
                         "chars": m.get("chars", 0)} for m in spec.get("materials", [])],
        "blocked_reason": blocked_reason,
        "unmapped_contract_fields": [],
    }

    # ---- contract coverage
    unmapped = []
    for f in contract:
        if f in result and result[f] not in (None, "", [], {}):
            continue
        canon = kernel.canonical(f)
        if canon and canon in result and result[canon] not in (None, "", [], {}):
            result[f] = result[canon]
        elif f in result:
            pass
        else:
            result[f] = None
            unmapped.append(f)
    if unmapped:
        result["unmapped_contract_fields"] = unmapped
        result["uncertainty"].append(
            "Unmapped contract fields set to null: " + ", ".join(unmapped))

    # keep every core key present even if None
    for k in CORE:
        result.setdefault(k, None)

    json.dump(result, open(os.path.join(out, "result.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    print("emit: status=%s contract=%d deliverables=%d element_rows=%d unmapped=%d"
          % (status, len(contract), len([d for d in deliverables if d["exists"]]),
             len(result["element_map"]), len(unmapped)))
    return 0


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--work", default=os.environ.get("MECH_WORK", "/app/work"))
    ap.add_argument("--out", default=os.environ.get("MECH_OUT", "/app/output"))
    a = ap.parse_args()
    return cmd_emit(a)


if __name__ == "__main__":
    sys.exit(main())
