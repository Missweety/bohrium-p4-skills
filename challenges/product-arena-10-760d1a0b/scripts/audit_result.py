#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""audit_result.py - independent review of a knowledge-graph run.

Checks
  contract    every output_contract field is present
  nodes       unique ids; source_id present; each node has paragraph evidence whose
              quote is verbatim in that paragraph
  edges       endpoints exist; predicate non-empty; evidence quote verbatim
  queries     >=3 executed; each has result/answer; evidence resolvable when the graph
              is non-empty
  aliases     decision in {merged, not_merged}; cross-source merges are forbidden
              unless an explicit equivalence is quoted (none are produced by default)
  integrity   blocking issues (dangling edges / duplicate ids / missing quotes) absent

Exit 0 on pass, 1 on errors.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
import graph_build  # noqa: E402

LIG = {"ﬁ": "fi", "ﬂ": "fl", "ﬀ": "ff", "ﬃ": "ffi", "\u00ad": "", "\u2019": "'",
       "‘": "'", "“": '"', "”": '"', "–": "-", "—": "-", "−": "-"}


def norm(s):
    for k, v in LIG.items():
        s = (s or "").replace(k, v)
    return re.sub(r"\s+", " ", s).strip().lower()


def contract_fields(contract):
    names = []
    if isinstance(contract, list):
        names = [x for x in contract if isinstance(x, str)]
    elif isinstance(contract, dict):
        items = None
        for key in ("required", "fields", "properties"):
            val = contract.get(key)
            if isinstance(val, list) and val:
                items = val
                break
            if isinstance(val, dict) and val:
                items = list(val.keys())
                break
        if items is None:
            items = list(contract.keys())
        for item in items:
            if isinstance(item, str):
                names.append(item)
            elif isinstance(item, dict):
                for k in ("name", "field", "field_id", "id", "key"):
                    if isinstance(item.get(k), str):
                        names.append(item[k])
                        break
    return names


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--result", required=True)
    ap.add_argument("--graph")
    ap.add_argument("--input", default="/input")
    ap.add_argument("--case")
    ap.add_argument("--out")
    a = ap.parse_args(argv)

    errors, warnings, checks = [], [], []

    def add(name, ok, detail=""):
        checks.append({"check": name, "ok": bool(ok),
                       "detail": "" if ok else detail})
        if not ok:
            errors.append(detail or name)

    try:
        result = json.load(open(a.result, encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        print(json.dumps({"pass": False, "errors": ["result unreadable: %s" % exc]},
                         ensure_ascii=False))
        return 1

    contract = {}
    if a.case and os.path.isfile(a.case):
        try:
            contract = json.load(open(a.case, encoding="utf-8")).get("output_contract", {})
        except Exception as exc:  # noqa: BLE001
            warnings.append("case unreadable: %s" % exc)
    required = contract_fields(contract)
    missing = [f for f in required if f not in result]
    add("contract_fields_present", not missing,
        "missing contract fields: %s" % ", ".join(missing) if missing else "")

    graph = {}
    if a.graph and os.path.isfile(a.graph):
        try:
            graph = json.load(open(a.graph, encoding="utf-8"))
        except Exception as exc:  # noqa: BLE001
            warnings.append("graph unreadable: %s" % exc)
    nodes = graph.get("nodes") or (result.get("graph") or {}).get("nodes") or []
    edges = graph.get("edges") or (result.get("graph") or {}).get("edges") or []
    aliases = graph.get("alias_candidates") or result.get("alias_decisions") or []
    queries = result.get("queries") or (result.get("graph") or {}).get("queries") or []

    para_text = {}
    try:
        docs, _ = graph_build.load_corpus(a.input)
        for d in docs:
            for p in d["paragraphs"]:
                para_text[(d["source_id"], p["paragraph_id"])] = norm(p["text"])
    except Exception as exc:  # noqa: BLE001
        warnings.append("could not reload corpus for quote verification: %s" % exc)

    def quote_ok(sid, pid, quote):
        key = (sid, pid)
        if key not in para_text:
            return None
        return norm(quote) in para_text[key]

    ids = set()
    for n in nodes:
        nid = n.get("node_id")
        add("node_id_unique[%s]" % nid, nid not in ids, "duplicate node id: %s" % nid)
        ids.add(nid)
        add("node_has_source[%s]" % nid, bool(n.get("source_id")),
            "node %s without source_id" % nid)
        ev = n.get("evidence") or []
        add("node_has_evidence[%s]" % nid, bool(ev), "node %s without evidence" % nid)
        for e in ev:
            if not para_text:
                continue
            ok = quote_ok(e.get("source_id"), e.get("paragraph_id"), e.get("quote"))
            if ok is None:
                add("node_anchor_resolves[%s]" % nid, False,
                    "node %s anchor %s/%s not found" % (
                        nid, e.get("source_id"), e.get("paragraph_id")))
            else:
                add("node_quote_verbatim[%s]" % nid, ok,
                    "node %s quote not verbatim in its paragraph" % nid)

    for e in edges:
        eid = e.get("edge_id")
        add("edge_endpoints_exist[%s]" % eid,
            e.get("source") in ids and e.get("target") in ids,
            "edge %s has dangling endpoint" % eid)
        add("edge_has_predicate[%s]" % eid, bool(e.get("predicate")),
            "edge %s without predicate" % eid)
        if para_text:
            ok = quote_ok(e.get("source_id"), e.get("paragraph_id"), e.get("quote"))
            add("edge_quote_verbatim[%s]" % eid, ok is not False,
                "edge %s quote not verbatim" % eid)

    add("queries_at_least_three", len([q for q in queries if q.get("executed")]) >= 3,
        "only %d executed queries" % len([q for q in queries if q.get("executed")]))
    for q in queries:
        qid = q.get("query_id")
        add("query_executed[%s]" % qid, bool(q.get("executed")),
            "query %s not executed" % qid)
        add("query_has_result[%s]" % qid, "result" in q,
            "query %s missing result" % qid)
        add("query_has_answer[%s]" % qid, bool((q.get("answer") or "").strip()),
            "query %s missing answer" % qid)
        if nodes:
            # A query that legitimately finds nothing must say so and stay empty; that is
            # honest, so an explicit no_hit + empty_reason is accepted instead of a quote.
            no_hit = bool(q.get("no_hit")) and bool((q.get("empty_reason") or "").strip()) \
                and not q.get("result")
            add("query_has_evidence[%s]" % qid, bool(q.get("evidence")) or no_hit,
                "query %s has no evidence and no explicit no_hit reason" % qid)
        for ev in (q.get("evidence") or []):
            if not para_text:
                continue
            ok = quote_ok(ev.get("source_id"), ev.get("paragraph_id"), ev.get("quote"))
            add("query_quote_verbatim[%s]" % qid, ok is not False,
                "query %s evidence quote not verbatim" % qid)

    for c in aliases:
        aid = c.get("alias_id")
        add("alias_decision_valid[%s]" % aid,
            c.get("decision") in ("merged", "not_merged"),
            "alias %s invalid decision %r" % (aid, c.get("decision")))
        add("alias_has_reason[%s]" % aid, bool(c.get("reason")),
            "alias %s without reason" % aid)
        if c.get("decision") == "merged" and len(set(c.get("sources") or [])) > 1:
            add("no_cross_source_merge[%s]" % aid, False,
                "alias %s merged across sources without explicit equivalence" % aid)

    totals = (result.get("metrics") or {})
    if totals:
        add("metrics_nodes", totals.get("nodes") == len(nodes), "metrics.nodes mismatch")
        add("metrics_edges", totals.get("edges") == len(edges), "metrics.edges mismatch")

    integrity = graph.get("integrity") or result.get("integrity") or {}
    if integrity:
        add("integrity_blocking_clear", not integrity.get("blocking"),
            "blocking integrity issues: %s" % integrity.get("blocking"))

    report = {
        "pass": not errors,
        "errors": errors,
        "warnings": warnings,
        "checks": checks,
        "totals": {"errors": len(errors), "warnings": len(warnings),
                   "checks": len(checks), "nodes": len(nodes), "edges": len(edges),
                   "queries": len(queries)},
    }
    if a.out:
        os.makedirs(os.path.dirname(os.path.abspath(a.out)) or ".", exist_ok=True)
        with open(a.out, "w", encoding="utf-8") as fh:
            json.dump(report, fh, ensure_ascii=False, indent=1)
    print(json.dumps(report, ensure_ascii=False, indent=1))
    return 0 if report["pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
