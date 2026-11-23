#!/usr/bin/env python3
"""check.py - figure-level self-check (stdlib only).

PASS requires that the SVG is a real, non-empty mechanism diagram whose machine record
agrees with the drawing, and that every stated entity/edge quote actually occurs in the
materials. Anything unverified is a warning or is downgraded in status - never hidden.
"""
import json
import os
import re
import sys
import xml.etree.ElementTree as ET

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import graphlib as G  # noqa: E402
import kernel  # noqa: E402
import layout as L  # noqa: E402

SVG = "{http://www.w3.org/2000/svg}"
COLOR_RE = re.compile(r"#[0-9a-fA-F]{6}")
ALLOWED = set(c.lower() for c in G.OKABE_ITO + G.VIRIDIS + list(G.NEUTRAL.values()))


def norm_ws(s):
    return re.sub(r"\s+", " ", str(s)).strip().lower()


def load_corpus(spec):
    texts = []
    for m in spec.get("materials", []):
        if m.get("exists"):
            texts.append(kernel.extract_text(m.get("path", "")))
    return norm_ws("\n".join(texts))


def run(out, work):
    errors, warnings = [], []
    stats = {}
    spec = json.load(open(os.path.join(work, "spec.json"), encoding="utf-8"))
    lay = json.load(open(os.path.join(work, "layout.json"), encoding="utf-8"))
    svg_path = os.path.join(out, "figure.svg")
    emap_path = os.path.join(out, "element_map.json")

    if not os.path.exists(svg_path):
        return {"verdict": "FAIL", "errors": ["figure.svg missing"], "warnings": [],
                "stats": {}}
    raw = open(svg_path, encoding="utf-8").read()
    stats["svg_bytes"] = len(raw.encode("utf-8"))
    try:
        root = ET.fromstring(raw)
    except ET.ParseError as exc:
        return {"verdict": "FAIL", "errors": ["figure.svg is not valid XML: %s" % exc],
                "warnings": [], "stats": stats}

    texts = [t for t in root.iter(SVG + "text")]
    stats["text_elements"] = len(texts)
    stats["nodes"] = len(spec["nodes"])
    stats["edges"] = len(spec["edges"])
    stats["compartments"] = len(lay["bands"])
    if len(texts) < len(spec["nodes"]) + len(spec["edges"]) + 6:
        errors.append("too few real <text> elements (%d)" % len(texts))
    titles = [t for t in root.iter(SVG + "title")]
    if not titles:
        errors.append("no <title> in SVG")

    # zero entity / zero edge == empty mechanism -> must block, never render
    if not spec["nodes"]:
        errors.append("empty_mechanism: zero entities")
    if not spec["edges"]:
        errors.append("empty_mechanism: zero relations")

    # hard gate: mention recall, stated relations, edge endpoints
    inv = spec.get("token_inventory", [])
    if inv:
        node_ids = {n["id"] for n in spec["nodes"]}
        matched = sum(1 for t in inv if t.get("node_id") in node_ids)
        recall = matched / float(len(inv))
        stats["token_recall"] = round(recall, 3)
        if recall < 0.8:
            errors.append("hard_gate: mention recall %.1f%% < 80%% (%d/%d tokens)" %
                          (100.0 * recall, matched, len(inv)))
    else:
        stats["token_recall"] = 1.0
    missing = spec.get("missing_relations", [])
    if missing:
        errors.append("hard_gate: %d stated relation(s) missing: %s" %
                      (len(missing), "; ".join("%s-%s %s" % (m["source"], m["target"],
                                                             m["kind"]) for m in missing[:4])))
    bad_endpoints = spec.get("edge_endpoint_errors", [])
    if bad_endpoints:
        errors.append("hard_gate: edge endpoint(s) not in entities: %s" %
                      ", ".join(x["edge"] for x in bad_endpoints))

    # compartment bands
    bands = {g.get("data-compartment") for g in root.iter(SVG + "g")
             if (g.get("class") or "") == "compartment"}
    for b in lay["bands"]:
        if b["id"] not in bands:
            errors.append("compartment band missing in SVG: %s" % b["id"])

    # node groups
    node_g = [g for g in root.iter(SVG + "g") if (g.get("class") or "").startswith("node ")]
    stats["node_groups"] = len(node_g)
    if len(node_g) != len(spec["nodes"]):
        errors.append("SVG node groups %d != spec nodes %d" % (len(node_g), len(spec["nodes"])))
    for g in node_g:
        if not list(g.iter(SVG + "title")) or not list(g.iter(SVG + "desc")):
            errors.append("node %s lacks title/desc provenance" % g.get("id"))
    edge_g = [g for g in root.iter(SVG + "g") if (g.get("class") or "").startswith("edge ")]
    stats["edge_groups"] = len(edge_g)
    if len(edge_g) != len(spec["edges"]):
        errors.append("SVG edge groups %d != spec edges %d" % (len(edge_g), len(spec["edges"])))
    for g in edge_g:
        if not list(g.iter(SVG + "title")) or not list(g.iter(SVG + "desc")):
            errors.append("edge %s lacks title/desc provenance" % g.get("id"))
        p = next((x for x in g.iter(SVG + "path")), None)
        if p is None or not p.get("marker-end"):
            errors.append("edge %s has no arrow-head marker" % g.get("id"))

    # markers + legend coverage
    ids = {e.get("id") for e in root.iter() if e.get("id")}
    for k in lay["used_kinds"]:
        if "mk-" + k not in ids:
            errors.append("missing marker mk-%s" % k)
    legend = next((g for g in root.iter(SVG + "g") if g.get("id") == "layer-legend"), None)
    legend_text = norm_ws(" ".join(t.text or "" for t in legend.iter(SVG + "text"))) if legend is not None else ""
    if legend is None:
        errors.append("legend layer missing")
    else:
        for k in lay["used_kinds"]:
            if norm_ws(G.KINDS[k][3]) not in legend_text:
                errors.append("legend does not label edge kind %s" % k)

    # element_map coverage + real quotes
    emap = json.load(open(emap_path, encoding="utf-8"))
    rows = emap.get("rows", [])
    stats["element_map_rows"] = len(rows)
    by_el = {r["element"]: r for r in rows}
    corpus = load_corpus(spec)
    trust = os.environ.get("MECH_TRUST_EVIDENCE") == "1"
    for n in spec["nodes"]:
        r = by_el.get("node:" + n["id"])
        if not r:
            errors.append("element_map missing node %s" % n["id"])
            continue
        if n.get("status") == "stated":
            if not r.get("source"):
                errors.append("node %s has no source span" % n["id"])
            if not r.get("quote"):
                warnings.append("node %s has no verbatim quote; downgrade to inferred" % n["id"])
            elif corpus and not trust and norm_ws(r["quote"]) not in corpus:
                errors.append("node %s quote not found in materials" % n["id"])
    for e in spec["edges"]:
        r = by_el.get("edge:" + e["id"])
        if not r:
            errors.append("element_map missing edge %s" % e["id"])
            continue
        if e.get("status") == "stated":
            if not r.get("source"):
                errors.append("edge %s has no source span" % e["id"])
            if not r.get("quote"):
                warnings.append("edge %s has no verbatim quote" % e["id"])
            elif corpus and not trust and norm_ws(r["quote"]) not in corpus:
                errors.append("edge %s quote not found in materials" % e["id"])
    if trust:
        warnings.append("evidence quotes were authored/vision-read; machine quote-match disabled")

    # geometry: inside band, no overlap, labels fit
    boxes = {n["id"]: L.box(n) for n in lay["nodes"]}
    band_of = {b["id"]: b for b in lay["bands"]}
    for n in lay["nodes"]:
        b = band_of[n["compartment"]]
        x, y, w, h = n["x"], n["y"], n["w"], n["h"]
        if not (40 <= x and x + w <= lay["width"] - 40):
            errors.append("node %s outside canvas horizontally" % n["id"])
        if not (b["y"] <= y and y + h <= b["y"] + b["h"] + 1):
            errors.append("node %s outside its compartment band" % n["id"])
        for line in n["lines"]:
            if G.tw(line, n["font"], True) > w - 10:
                errors.append("node %s label overflows box: %r" % (n["id"], line))
        if n.get("truncated"):
            warnings.append("node %s label truncated; inspect for clipping" % n["id"])
    ids_list = list(boxes)
    for i, a in enumerate(ids_list):
        for b in ids_list[i + 1:]:
            if G.intersects(boxes[a], boxes[b]):
                errors.append("node boxes overlap: %s / %s" % (a, b))

    crossings = 0
    for e in lay["edges"]:
        for nid, b in boxes.items():
            if nid in (e["source"], e["target"]):
                continue
            for p, q in zip(e["points"], e["points"][1:]):
                if L.seg_hits_box(p, q, b):
                    crossings += 1
                    break
    stats["edge_node_crossings"] = crossings
    if crossings:
        warnings.append("%d edge segment(s) cross unrelated node boxes; review routing" % crossings)

    # palette discipline
    used = {c.lower() for c in COLOR_RE.findall(raw)}
    bad = sorted(c for c in used if c not in ALLOWED and c != "#ffffff")
    if bad:
        errors.append("off-palette colours: %s" % ", ".join(bad))
    stats["colours"] = len(used)

    # semantics recorded
    kinds = [e["kind"] for e in spec["edges"]]
    stats["edge_kinds"] = {k: kinds.count(k) for k in G.KINDS if kinds.count(k)}
    if spec.get("isolated_entities"):
        warnings.append("isolated entities present: " + ", ".join(spec["isolated_entities"]))
    if spec.get("conflicts"):
        warnings.append("source conflicts recorded: %d" % len(spec["conflicts"]))
    if spec.get("unresolved_edges"):
        warnings.append("unresolved relations withheld: %d" % len(spec["unresolved_edges"]))
    stats["verified_quotes"] = sum(1 for r in rows if r.get("quote_verified"))
    stats["total_provenance_rows"] = len(rows)

    verdict = "PASS" if not errors else "FAIL"
    return {"verdict": verdict, "errors": errors, "warnings": warnings, "stats": stats}


def main():
    work = os.environ.get("MECH_WORK", "/app/work")
    out = os.environ.get("MECH_OUT", "/app/output")
    res = run(out, work)
    json.dump(res, open(os.path.join(work, "selfcheck.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    print("selfcheck: %s (%d errors, %d warnings)"
          % (res["verdict"], len(res["errors"]), len(res["warnings"])))
    for e in res["errors"]:
        print("  ERROR", e)
    for w in res["warnings"]:
        print("  WARN ", w)
    return 0 if res["verdict"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
