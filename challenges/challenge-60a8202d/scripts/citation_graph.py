#!/usr/bin/env python3
"""Build a source-bound citation graph from edges supplied in the case input.

Only reads local CSV / TSV / JSON / JSONL files. No network, no live database
query, no inferred edges. Every kept edge keeps its source database and exact
file locator so that a reviewer can re-check it.

Outputs under --out:
  graph.json    nodes, unique citation edges, components, shortest paths,
                duplicate/identity merge candidates, issues, stats
  citations.csv one row per supporting evidence record for each unique edge
  issues.csv    dropped edges, missing evidence and other anomalies

Usage:
  python3 scripts/citation_graph.py --input /input --out /app/work/graph \
      [--seeds /input/seeds.csv] [--max-depth 3] [--top-k 50] [--json]

Exit codes: 0 ok; 2 produced with dropped edges, unresolved seeds or no edges;
1 unusable input (missing path or no readable files).
"""
import argparse
import csv
import json
import os
import re
import sys
import unicodedata
from collections import defaultdict, deque

EDGE_KEYS = ("citation_edges", "edges", "citations", "references",
             "citation_records", "edge_list", "links")
PAPER_KEYS = ("papers", "nodes", "works", "literature", "paper_records",
              "bibliography", "paper_meta")
SEED_KEYS = ("seeds", "seed_papers", "seed_ids", "seed_dois", "seed")

FIELD_ALIASES = {
    "source": ("source", "from", "citer", "citing", "citing_paper", "citing_id",
               "citing_doi", "source_doi", "from_doi"),
    "target": ("target", "to", "cited", "cited_paper", "reference", "cited_id",
               "cited_doi", "target_doi", "to_doi"),
    "direction": ("direction", "dir", "relation", "edge_direction",
                  "citation_type", "relation_type"),
    "depth": ("depth", "level", "hop"),
    "source_db": ("source_db", "db", "database", "source_database", "provider"),
    "evidence_file": ("evidence_file", "evidence_path", "file", "source_file",
                      "response_file"),
    "evidence_locator": ("evidence_locator", "locator", "evidence_location",
                         "position", "page", "row"),
}
PAPER_ALIASES = {
    "id": ("id", "paper_id", "record_id", "work_id"),
    "doi": ("doi", "DOI", "dois"),
    "title": ("title", "paper_title", "name"),
    "year": ("year", "publication_year", "pub_year", "date"),
    "source_db": ("source_db", "db", "database", "provider"),
}
CITES_WORDS = {"cites", "cite", "citing", "citations", "references", "reference",
               "ref", "refs", "out", "forward", "outbound", "cites_target"}
CITED_BY_WORDS = {"cited_by", "citedby", "cited-by", "is_cited_by",
                  "cited by", "incoming", "reverse", "in"}

DOI_RE = re.compile(r"^10\.\d{4,9}/\S+$", re.I)
YEAR_RE = re.compile(r"(19|20)\d{2}")
TEXT_EXT = {".csv", ".tsv", ".json", ".jsonl"}
MAX_JSON_BYTES = 20 * 1024 * 1024


def norm_text(value):
    if value is None:
        return ""
    text = unicodedata.normalize("NFKC", str(value))
    text = text.replace("\u00ad", "")
    text = re.sub(r"\s+", " ", text)
    return text.strip().casefold()


def norm_title(value):
    """Case-, width- and punctuation-insensitive title key for identity matching."""
    if value is None:
        return ""
    text = unicodedata.normalize("NFKC", str(value)).casefold()
    text = re.sub(r"[^\w\s]", " ", text, flags=re.UNICODE)
    text = text.replace("_", " ")
    return re.sub(r"\s+", " ", text).strip()


def norm_doi(value):
    if value is None:
        return ""
    text = unicodedata.normalize("NFKC", str(value)).strip()
    text = re.sub(r"(?i)^(https?://(dx\.)?doi\.org/|doi:\s*)", "", text)
    text = text.strip().rstrip(".,;)]}")
    text = text.casefold()
    return text if DOI_RE.match(text) else ""


def norm_year(value):
    if value is None or str(value).strip() == "":
        return None
    match = YEAR_RE.search(str(value))
    return int(match.group(0)) if match else None


def norm_direction(value):
    text = norm_text(value)
    text = text.replace("_", " ").replace("-", " ")
    compact = text.replace(" ", "")
    if compact in {w.replace(" ", "").replace("_", "") for w in CITES_WORDS}:
        return "cites"
    if compact in {w.replace(" ", "").replace("_", "") for w in CITED_BY_WORDS}:
        return "cited_by"
    return ""


def norm_key(key):
    return re.sub(r"[\s-]+", "_", str(key).strip().casefold())


def pick(record, aliases):
    for name in aliases:
        if name in record and str(record[name]).strip() != "":
            return record[name]
    return ""


class Collector:
    def __init__(self):
        self.files = []
        self.edges = []
        self.papers = []
        self.seeds = []
        self.issues = []

    def issue(self, severity, code, detail, file="", locator="", raw=None):
        item = {"severity": severity, "code": code, "detail": detail,
                "file": file, "locator": locator}
        if raw is not None:
            item["raw"] = raw
        self.issues.append(item)


def iter_input_files(root):
    if os.path.isfile(root):
        yield root, os.path.basename(root)
        return
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames.sort()
        for name in sorted(filenames):
            if name.startswith("."):
                continue
            if os.path.splitext(name)[1].lower() in TEXT_EXT:
                path = os.path.join(dirpath, name)
                yield path, os.path.relpath(path, root)


def classify(record, collector, rel, locator):
    keys = {norm_key(k) for k in record}
    has_source = bool(pick(record, FIELD_ALIASES["source"]))
    has_target = bool(pick(record, FIELD_ALIASES["target"]))
    has_direction = bool(pick(record, FIELD_ALIASES["direction"]))
    if has_source or has_target or has_direction:
        collector.edges.append(dict(record, _file=rel, _locator=locator))
        return
    if keys & {"role", "is_seed"}:
        role = norm_text(record.get("role", ""))
        if role == "seed" or str(record.get("is_seed", "")).lower() == "true":
            collector.seeds.append({"raw": record, "file": rel, "locator": locator})
            return
    if keys & {"seed", "seed_id", "seed_doi"}:
        collector.seeds.append({"raw": record, "file": rel, "locator": locator})
        return
    if any(pick(record, aliases) for aliases in PAPER_ALIASES.values()):
        collector.papers.append(dict(record, _file=rel, _locator=locator))
        return
    collector.issue("warning", "unclassified_record",
                    "record has no source/target, seed or paper identity", rel, locator)


def walk_payload(payload, collector, rel, locator):
    if isinstance(payload, list):
        for index, item in enumerate(payload):
            walk_payload(item, collector, rel, "%s[%d]" % (locator, index))
        return
    if isinstance(payload, str):
        collector.seeds.append({"raw": payload, "file": rel, "locator": locator})
        return
    if not isinstance(payload, dict):
        collector.issue("warning", "unsupported_json_value",
                        "JSON value is neither object nor array", rel, locator)
        return
    matched_array = False
    for key in SEED_KEYS:
        value = payload.get(key)
        if isinstance(value, list):
            matched_array = True
            for index, item in enumerate(value):
                collector.seeds.append({"raw": item, "file": rel,
                                        "locator": "%s.%s[%d]" % (locator, key, index)})
                if isinstance(item, dict) and pick(item, PAPER_ALIASES["title"]) \
                        and (pick(item, PAPER_ALIASES["doi"]) or pick(item, PAPER_ALIASES["id"])):
                    collector.papers.append(dict(item, _file=rel,
                                                 _locator="%s.%s[%d]" % (locator, key, index)))
    for key in EDGE_KEYS:
        value = payload.get(key)
        if isinstance(value, list):
            matched_array = True
            for index, item in enumerate(value):
                if isinstance(item, dict):
                    collector.edges.append(dict(item, _file=rel,
                                                _locator="%s.%s[%d]" % (locator, key, index)))
                else:
                    collector.issue("warning", "invalid_edge_item",
                                    "edge array item is not an object", rel,
                                    "%s.%s[%d]" % (locator, key, index))
    for key in PAPER_KEYS:
        value = payload.get(key)
        if isinstance(value, list):
            matched_array = True
            for index, item in enumerate(value):
                if isinstance(item, dict):
                    collector.papers.append(dict(item, _file=rel,
                                                 _locator="%s.%s[%d]" % (locator, key, index)))
    known = set(SEED_KEYS) | set(EDGE_KEYS) | set(PAPER_KEYS) | {"data"}
    for key, value in payload.items():
        if key in known or not isinstance(value, list):
            continue
        for index, item in enumerate(value):
            if not isinstance(item, dict):
                continue
            if pick(item, FIELD_ALIASES["source"]) or pick(item, FIELD_ALIASES["target"]) \
                    or pick(item, FIELD_ALIASES["direction"]):
                collector.edges.append(dict(item, _file=rel,
                                            _locator="%s.%s[%d]" % (locator, key, index)))
            elif any(pick(item, aliases) for aliases in PAPER_ALIASES.values()):
                collector.papers.append(dict(item, _file=rel,
                                             _locator="%s.%s[%d]" % (locator, key, index)))
    if matched_array:
        return
    for key in ("input", "case", "materials", "payload", "dataset", "content"):
        if isinstance(payload.get(key), dict):
            walk_payload(payload[key], collector, rel, locator + "." + key)
            return
    if "data" in payload and isinstance(payload["data"], (list, dict)):
        walk_payload(payload["data"], collector, rel, locator + ".data")
        return
    classify(payload, collector, rel, locator)


def read_file(path, rel, collector):
    ext = os.path.splitext(path)[1].lower()
    if ext in {".csv", ".tsv"}:
        delimiter = "\t" if ext == ".tsv" else ","
        try:
            with open(path, encoding="utf-8-sig", errors="replace", newline="") as handle:
                reader = csv.DictReader(handle, delimiter=delimiter)
                for line_no, row in enumerate(reader, start=2):
                    record = {norm_key(k): v for k, v in row.items() if k is not None}
                    classify(record, collector, rel, "row:%d" % line_no)
        except (OSError, csv.Error) as exc:
            collector.issue("error", "unreadable_file", "%s: %s" % (type(exc).__name__, exc),
                            rel, "")
    elif ext == ".jsonl":
        try:
            with open(path, encoding="utf-8", errors="replace") as handle:
                for line_no, line in enumerate(handle, start=1):
                    if not line.strip():
                        continue
                    try:
                        payload = json.loads(line)
                    except ValueError as exc:
                        collector.issue("error", "invalid_json_line", str(exc), rel,
                                        "line:%d" % line_no)
                        continue
                    walk_payload(payload, collector, rel, "line:%d" % line_no)
        except OSError as exc:
            collector.issue("error", "unreadable_file", str(exc), rel, "")
    elif ext == ".json":
        try:
            if os.path.getsize(path) > MAX_JSON_BYTES:
                collector.issue("error", "json_too_large", "over 20MB", rel, "")
                return
            with open(path, encoding="utf-8", errors="replace") as handle:
                payload = json.load(handle)
        except (OSError, ValueError) as exc:
            collector.issue("error", "invalid_json", "%s: %s" % (type(exc).__name__, exc),
                            rel, "")
            return
        walk_payload(payload, collector, rel, "item")
    return


def load_input(root, collector):
    if not os.path.exists(root):
        return False
    found = False
    for path, rel in iter_input_files(root):
        found = True
        collector.files.append(rel)
        read_file(path, rel, collector)
    return found


def paper_node(record, collector):
    doi = norm_doi(pick(record, PAPER_ALIASES["doi"]))
    raw_id = str(pick(record, PAPER_ALIASES["id"])).strip()
    title = str(pick(record, PAPER_ALIASES["title"])).strip()
    year = norm_year(pick(record, PAPER_ALIASES["year"]))
    source_db = str(pick(record, PAPER_ALIASES["source_db"])).strip()
    if doi:
        node = "doi:" + doi
    elif norm_doi(raw_id):
        node = "doi:" + norm_doi(raw_id)
        doi = norm_doi(raw_id)
    elif raw_id:
        node = "ref:" + norm_text(raw_id)
    elif title:
        node = "title:" + norm_title(title) + "|" + (str(year) if year else "na")
    else:
        collector.issue("warning", "paper_without_identity",
                        "paper record has no DOI, id or title",
                        record.get("_file", ""), record.get("_locator", ""))
        return None
    return {"node": node, "doi": doi, "title": title, "year": year,
            "source_db": source_db, "raw_id": raw_id}


class Graph:
    def __init__(self):
        self.meta = {}
        self.aliases = {}
        self.title_aliases = {}
        self.alias_collisions = set()

    def register_alias(self, key, node):
        key = norm_text(key)
        if not key:
            return
        if key in self.aliases and self.aliases[key] != node:
            self.alias_collisions.add(key)
            return
        self.aliases[key] = node

    def register_title_alias(self, title, node):
        key = norm_title(title)
        if not key:
            return
        if key in self.title_aliases and self.title_aliases[key] != node:
            self.alias_collisions.add("title:" + key)
            return
        self.title_aliases[key] = node

    def add_paper(self, info):
        node = info["node"]
        meta = self.meta.setdefault(node, {"doi": "", "title": "", "year": None,
                                           "source_dbs": set()})
        if info["doi"]:
            meta["doi"] = meta["doi"] or info["doi"]
        if info["title"]:
            if meta["title"] and norm_title(meta["title"]) != norm_title(info["title"]):
                self.alias_collisions.add("title_conflict:" + node)
            meta["title"] = meta["title"] or info["title"]
        if info["year"] is not None and meta["year"] is None:
            meta["year"] = info["year"]
        if info["source_db"]:
            meta["source_dbs"].add(info["source_db"])
        if info["raw_id"]:
            self.register_alias(info["raw_id"], node)
        if info["title"]:
            self.register_alias(info["title"], node)
            self.register_title_alias(info["title"], node)
        if info["doi"]:
            self.register_alias("doi:" + info["doi"], node)

    def resolve(self, raw):
        text = str(raw).strip()
        doi = norm_doi(text)
        if doi:
            candidate = self.aliases.get(norm_text("doi:" + doi)) or "doi:" + doi
            self.meta.setdefault(candidate, {"doi": doi, "title": "", "year": None,
                                             "source_dbs": set()})
            return candidate
        alias = self.aliases.get(norm_text(text))
        if alias:
            return alias
        alias = self.title_aliases.get(norm_title(text))
        if alias:
            return alias
        node = "ref:" + norm_text(text)
        self.meta.setdefault(node, {"doi": "", "title": "", "year": None,
                                    "source_dbs": set()})
        return node


def validate_edge(record, collector):
    source = str(pick(record, FIELD_ALIASES["source"])).strip()
    target = str(pick(record, FIELD_ALIASES["target"])).strip()
    raw_direction = pick(record, FIELD_ALIASES["direction"])
    rel = record.get("_file", "")
    locator = record.get("_locator", "")
    missing = [name for name, value in (("source", source), ("target", target))
               if not value]
    if not str(raw_direction).strip():
        missing.append("direction")
    if missing:
        collector.issue("error", "missing_required_field",
                        "edge dropped; missing %s" % ",".join(missing), rel, locator,
                        {"source": source, "target": target,
                         "direction": str(raw_direction)})
        return None
    direction = norm_direction(raw_direction)
    if not direction:
        collector.issue("error", "invalid_direction",
                        "edge dropped; direction=%r not in {cites,cited_by}"
                        % str(raw_direction), rel, locator)
        return None
    depth_raw = pick(record, FIELD_ALIASES["depth"])
    depth = 1
    if str(depth_raw).strip() != "":
        try:
            depth = int(float(str(depth_raw)))
            if depth < 1:
                raise ValueError
        except (TypeError, ValueError):
            collector.issue("warning", "invalid_depth",
                            "non-integer depth %r; defaulted to 1" % str(depth_raw),
                            rel, locator)
            depth = 1
    source_db = str(pick(record, FIELD_ALIASES["source_db"])).strip()
    evidence_file = str(pick(record, FIELD_ALIASES["evidence_file"])).strip()
    evidence_locator = str(pick(record, FIELD_ALIASES["evidence_locator"])).strip()
    if not evidence_locator:
        collector.issue("error", "missing_evidence",
                        "edge dropped; evidence_locator missing (no fallback locator "
                        "is invented)", rel, locator,
                        {"source": source, "target": target,
                         "as_provided_direction": str(raw_direction)})
        return None
    missing_evidence = [name for name, value in
                        (("source_db", source_db), ("evidence_file", evidence_file))
                        if not value]
    if missing_evidence:
        collector.issue("warning", "missing_evidence",
                        "edge kept but lacks %s" % ",".join(missing_evidence),
                        rel, locator)
    citer, cited = (source, target) if direction == "cites" else (target, source)
    return {"source_raw": source, "target_raw": target,
            "direction_raw": str(raw_direction), "direction": direction,
            "depth": depth, "source_db": source_db,
            "evidence_file": evidence_file or rel,
            "evidence_locator": evidence_locator,
            "file": rel, "locator": locator, "citer_raw": citer, "cited_raw": cited}


def build_graph(collector):
    graph = Graph()
    for record in collector.papers:
        info = paper_node(record, collector)
        if info:
            graph.add_paper(info)
    for key in sorted(graph.alias_collisions):
        collector.issue("warning", "alias_collision",
                        "ambiguous alias kept first mapping: %s" % key)
    graph.alias_collisions.clear()

    valid = []
    for record in collector.edges:
        edge = validate_edge(record, collector)
        if not edge:
            continue
        edge["citer"] = graph.resolve(edge["citer_raw"])
        edge["cited"] = graph.resolve(edge["cited_raw"])
        if edge["citer"] == edge["cited"]:
            collector.issue("warning", "self_loop",
                            "edge points to itself; kept with zero degree",
                            edge["file"], edge["locator"])
        if edge["source_db"]:
            graph.meta[edge["citer"]]["source_dbs"].add(edge["source_db"])
            graph.meta[edge["cited"]]["source_dbs"].add(edge["source_db"])
        valid.append(edge)
    return graph, valid


def group_edges(valid, collector):
    pairs = defaultdict(list)
    for edge in valid:
        pairs[(edge["citer"], edge["cited"])].append(edge)
    seen_evidence = set()
    for key in sorted(pairs):
        for edge in pairs[key]:
            marker = (key[0], key[1], edge["source_db"], edge["evidence_file"],
                      edge["evidence_locator"])
            if marker in seen_evidence:
                collector.issue("info", "duplicate_edge",
                                "same pair and same evidence locator repeated",
                                edge["file"], edge["locator"])
            seen_evidence.add(marker)
    for (citer, cited) in sorted(pairs):
        if (cited, citer) in pairs and (citer, cited) < (cited, citer):
            collector.issue("warning", "reciprocal_edges",
                            "both directions exist for this pair; verify which is correct",
                            "", "", {"a": citer, "b": cited})
    return pairs


class UnionFind:
    def __init__(self):
        self.parent = {}

    def find(self, node):
        self.parent.setdefault(node, node)
        while self.parent[node] != node:
            self.parent[node] = self.parent[self.parent[node]]
            node = self.parent[node]
        return node

    def union(self, left, right):
        root_left, root_right = self.find(left), self.find(right)
        if root_left != root_right:
            if root_left < root_right:
                self.parent[root_right] = root_left
            else:
                self.parent[root_left] = root_right


def build_nodes(graph, pairs, seeds):
    incident = set()
    for citer, cited in pairs:
        incident.add(citer)
        incident.add(cited)
    for seed in seeds:
        graph.meta.setdefault(seed, {"doi": "", "title": "", "year": None,
                                     "source_dbs": set()})
        if seed not in incident:
            graph.meta[seed].setdefault("source_dbs", set())
    out_degree = defaultdict(int)
    in_degree = defaultdict(int)
    for citer, cited in pairs:
        out_degree[citer] += 1
        in_degree[cited] += 1
    uf = UnionFind()
    for citer, cited in pairs:
        uf.union(citer, cited)
    for node in graph.meta:
        uf.find(node)
    components = defaultdict(list)
    for node in graph.meta:
        components[uf.find(node)].append(node)
    ordered = sorted((sorted(nodes) for nodes in components.values()),
                     key=lambda nodes: nodes[0])
    component_of = {}
    component_list = []
    for index, nodes in enumerate(ordered, start=1):
        name = "C%03d" % index
        component_list.append({"component_id": name, "size": len(nodes),
                               "nodes": nodes,
                               "seed_nodes": [n for n in nodes if n in seeds]})
        for node in nodes:
            component_of[node] = name
    nodes_out = []
    for node in sorted(graph.meta):
        meta = graph.meta[node]
        doi = meta.get("doi") or (node[4:] if node.startswith("doi:") else "")
        nodes_out.append({
            "node_id": node,
            "doi": doi,
            "title": meta.get("title", ""),
            "year": meta.get("year"),
            "source_dbs": sorted(meta.get("source_dbs", [])),
            "is_seed": node in seeds,
            "in_degree": in_degree.get(node, 0),
            "out_degree": out_degree.get(node, 0),
            "degree": in_degree.get(node, 0) + out_degree.get(node, 0),
            "component_id": component_of.get(node, ""),
        })
    return nodes_out, component_list, uf


def bfs(start, adjacency, max_depth):
    distance = {start: 0}
    previous = {}
    queue = deque([start])
    while queue:
        node = queue.popleft()
        if distance[node] >= max_depth:
            continue
        for neighbour in sorted(adjacency.get(node, ())):
            if neighbour not in distance:
                distance[neighbour] = distance[node] + 1
                previous[neighbour] = node
                queue.append(neighbour)
    return distance, previous


def build_paths(seed_nodes, pairs, edge_index, max_depth, top_k, collector):
    adjacency = defaultdict(set)
    reverse = defaultdict(set)
    for citer, cited in pairs:
        adjacency[citer].add(cited)
        reverse[cited].add(citer)
    entries = []
    for seed in sorted(seed_nodes):
        for mode, graph in (("forward", adjacency), ("reverse", reverse)):
            distance, previous = bfs(seed, graph, max_depth)
            for target in sorted(distance):
                if target == seed or distance[target] == 0:
                    continue
                chain = [target]
                cursor = target
                while cursor != seed:
                    cursor = previous[cursor]
                    chain.append(cursor)
                chain.reverse()
                hops = []
                for left, right in zip(chain, chain[1:]):
                    supporting = edge_index.get((left, right))
                    if supporting is None:
                        supporting = edge_index.get((right, left), [])
                        canonical = (right, left)
                    else:
                        canonical = (left, right)
                    first = supporting[0] if supporting else {}
                    hops.append({
                        "from": left,
                        "to": right,
                        "relation": "cites" if mode == "forward" else "cited_by",
                        "traversal": mode,
                        "canonical_edge": "%s -> %s" % canonical,
                        "source_db": first.get("source_db", ""),
                        "evidence_file": first.get("evidence_file", ""),
                        "evidence_locator": first.get("evidence_locator", ""),
                        "supporting_evidence": len(supporting),
                    })
                entries.append({"seed": seed, "target": target, "mode": mode,
                                "length": distance[target], "hops": hops})
    entries.sort(key=lambda item: (item["length"], item["seed"], item["target"], item["mode"]))
    if len(entries) > top_k:
        collector.issue("info", "paths_truncated",
                        "kept %d of %d seed-target paths (--top-k)" % (top_k, len(entries)))
    return entries[:top_k]


def merge_candidates(graph):
    by_doi = defaultdict(set)
    by_title_year = defaultdict(set)
    for node, meta in graph.meta.items():
        doi = meta.get("doi") or (node[4:] if node.startswith("doi:") else "")
        if doi:
            by_doi[doi].add(node)
        title = norm_title(meta.get("title"))
        year = meta.get("year")
        if title and year is not None:
            by_title_year[(title, year)].add(node)
    candidates = []
    for doi in sorted(by_doi):
        members = sorted(by_doi[doi])
        if len(members) > 1:
            candidates.append({
                "type": "doi_exact", "key": doi, "action": "review_only",
                "reason": "multiple graph nodes share one normalized DOI",
                "members": [member_view(graph, node) for node in members],
            })
    for (title, year) in sorted(by_title_year):
        members = sorted(by_title_year[(title, year)])
        if len(members) > 1:
            candidates.append({
                "type": "title_year_exact", "key": "%s|%s" % (title, year),
                "action": "review_only",
                "reason": "same normalized title and year, different identifiers",
                "members": [member_view(graph, node) for node in members],
            })
    return candidates


def member_view(graph, node):
    meta = graph.meta[node]
    return {"node_id": node, "doi": meta.get("doi", ""), "title": meta.get("title", ""),
            "year": meta.get("year"), "source_dbs": sorted(meta.get("source_dbs", []))}


def parse_seed_value(value):
    text = str(value).strip()
    if not text:
        return []
    if os.path.isfile(text) and os.path.splitext(text)[1].lower() in TEXT_EXT:
        collector = Collector()
        read_file(text, os.path.basename(text), collector)
        seeds = [item["raw"] for item in collector.seeds]
        if not seeds:
            seeds = list(collector.papers)
        return seeds
    return [part.strip() for part in text.split(",") if part.strip()]


def seed_ref(raw):
    if isinstance(raw, str):
        return raw
    if isinstance(raw, dict):
        for key in ("doi", "DOI", "id", "paper_id", "seed", "seed_id", "title"):
            value = raw.get(key)
            if value is not None and str(value).strip() != "":
                return value
    return ""


def write_csv(path, rows, fields):
    with open(path, "w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            flat = {}
            for field in fields:
                value = row.get(field, "")
                if isinstance(value, (dict, list)):
                    value = json.dumps(value, ensure_ascii=False, sort_keys=True)
                flat[field] = value
            writer.writerow(flat)


def write_outputs(out_dir, graph, pairs, nodes_out, components, paths,
                  candidates, collector, seeds, stats):
    os.makedirs(out_dir, exist_ok=True)
    edges_out = []
    citation_rows = []
    edge_index = {}
    for edge_id, (citer, cited) in enumerate(sorted(pairs), start=1):
        supporting = sorted(pairs[(citer, cited)],
                            key=lambda item: (item["source_db"], item["evidence_file"],
                                              item["evidence_locator"]))
        edge_index[(citer, cited)] = supporting
        evidence = [{"source_db": item["source_db"],
                     "evidence_file": item["evidence_file"],
                     "evidence_locator": item["evidence_locator"],
                     "as_provided_source": item["source_raw"],
                     "as_provided_target": item["target_raw"],
                     "as_provided_direction": item["direction_raw"],
                     "depth": item["depth"]} for item in supporting]
        edges_out.append({"edge_id": "E%04d" % edge_id, "citer": citer, "cited": cited,
                          "relation": "cites", "evidence_count": len(evidence),
                          "evidence": evidence})
        for item in evidence:
            citation_rows.append({
                "edge_id": "E%04d" % edge_id,
                "citer": citer,
                "cited": cited,
                "relation": "cites",
                "as_provided_source": item["as_provided_source"],
                "as_provided_target": item["as_provided_target"],
                "as_provided_direction": item["as_provided_direction"],
                "source_db": item["source_db"],
                "evidence_file": item["evidence_file"],
                "evidence_locator": item["evidence_locator"],
                "depth": item["depth"],
            })
    # Paths need the edge index, which is fully built only now.
    paths = build_paths([node for node in seeds if node in graph.meta], pairs,
                        edge_index, stats["max_depth"], stats["top_k"], collector)
    severity_order = {"error": 0, "warning": 1, "info": 2}
    issues = sorted(collector.issues, key=lambda item: (severity_order.get(item["severity"], 9),
                                                       item["code"], item["file"],
                                                       item["locator"], item["detail"]))
    stats["issues"] = {key: sum(1 for item in issues if item["severity"] == key)
                       for key in ("error", "warning", "info")}
    stats["edges_unique"] = len(edges_out)
    stats["edges_dropped"] = stats["edge_records_read"] - stats["edges_valid_records"]
    stats["merge_candidates"] = len(candidates)
    stats["paths"] = len(paths)
    payload = {
        "generated_by": "citation_graph.py",
        "scope_note": "Only edges supplied in the input files are represented. "
                      "No live database query, no inferred or completed edges.",
        "input": {"root": os.path.abspath(stats["root"]),
                  "files": collector.files,
                  "edge_records_read": stats["edge_records_read"]},
        "seeds": stats["seed_entries"],
        "stats": {key: value for key, value in stats.items()
                  if key not in ("root", "max_depth", "top_k", "seed_entries")},
        "nodes": nodes_out,
        "edges": edges_out,
        "components": components,
        "paths": paths,
        "merge_candidates": candidates,
        "issues": issues,
    }
    with open(os.path.join(out_dir, "graph.json"), "w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=1)
    write_csv(os.path.join(out_dir, "citations.csv"), citation_rows,
              ["edge_id", "citer", "cited", "relation", "as_provided_source",
               "as_provided_target", "as_provided_direction", "source_db",
               "evidence_file", "evidence_locator", "depth"])
    write_csv(os.path.join(out_dir, "issues.csv"), issues,
              ["severity", "code", "detail", "file", "locator", "raw"])
    return payload, issues


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--input", required=True,
                        help="input directory or one CSV/TSV/JSON/JSONL file")
    parser.add_argument("--out", required=True, help="output directory")
    parser.add_argument("--seeds", default="",
                        help="comma-separated seed identifiers or a seed CSV/JSON file")
    parser.add_argument("--max-depth", type=int, default=3,
                        help="maximum BFS hops for path search (default 3)")
    parser.add_argument("--top-k", type=int, default=50,
                        help="maximum number of seed-target paths to keep (default 50)")
    parser.add_argument("--json", action="store_true", help="print the stats object as JSON")
    args = parser.parse_args()
    if args.max_depth < 1:
        print("error: --max-depth must be >= 1", file=sys.stderr)
        return 1
    if args.top_k < 1:
        print("error: --top-k must be >= 1", file=sys.stderr)
        return 1

    collector = Collector()
    if not os.path.exists(args.input):
        print("error: input path not found: %s" % args.input, file=sys.stderr)
        return 1
    if not load_input(args.input, collector):
        print("error: no CSV/TSV/JSON/JSONL input files found at %s" % args.input,
              file=sys.stderr)
        return 1

    graph, valid = build_graph(collector)
    pairs = group_edges(valid, collector)

    raw_seeds = [seed_ref(item["raw"]) for item in collector.seeds]
    raw_seeds += parse_seed_value(args.seeds) if args.seeds else []
    raw_seeds = [item for item in raw_seeds if str(item).strip() != ""]
    unique_seeds = []
    seen_seeds = set()
    for raw in raw_seeds:
        marker = str(seed_ref(raw)).strip().casefold()
        if marker and marker not in seen_seeds:
            seen_seeds.add(marker)
            unique_seeds.append(raw)
    raw_seeds = unique_seeds
    seed_nodes = []
    seed_entries = []
    for raw in raw_seeds:
        node = graph.resolve(raw)
        seed_entries.append({"raw": str(seed_ref(raw)), "node_id": node,
                             "present_in_edges": False})
        if node not in seed_nodes:
            seed_nodes.append(node)
    if not seed_nodes:
        collector.issue("warning", "no_seed",
                        "no seed identifier supplied; paths cannot be computed")

    nodes_out, components, _ = build_nodes(graph, pairs, set(seed_nodes))
    incident = {node for pair in pairs for node in pair}
    for entry in seed_entries:
        entry["present_in_edges"] = entry["node_id"] in incident
        if not entry["present_in_edges"]:
            collector.issue("warning", "seed_not_in_edges",
                            "seed %r has no supplied citation edge" % entry["raw"])
    candidates = merge_candidates(graph)
    stats = {
        "root": args.input,
        "input_files": len(collector.files),
        "edge_records_read": len(collector.edges),
        "edges_valid_records": len(valid),
        "nodes": len(nodes_out),
        "components": len(components),
        "seeds": len(seed_nodes),
        "max_depth": args.max_depth,
        "top_k": args.top_k,
        "seed_entries": seed_entries,
        "empty_graph": len(pairs) == 0,
    }
    payload, issues = write_outputs(args.out, graph, pairs, nodes_out, components, [],
                                    candidates, collector, seed_nodes, stats)
    error_count = sum(1 for item in issues if item["severity"] == "error")
    unresolved = sum(1 for item in issues if item["code"] == "seed_not_in_edges")
    summary = payload["stats"]
    summary["out_dir"] = os.path.abspath(args.out)
    if args.json:
        print(json.dumps(summary, ensure_ascii=False, indent=1))
    else:
        print("nodes=%d edges=%d components=%d paths=%d candidates=%d "
              "dropped=%d errors=%d" % (summary["nodes"], summary["edges_unique"],
                                        summary["components"], summary["paths"],
                                        summary["merge_candidates"],
                                        summary["edges_dropped"], error_count))
        print("wrote graph.json, citations.csv, issues.csv -> %s" % args.out)
    if not pairs:
        print("warning: no valid citation edges; graph is empty", file=sys.stderr)
        return 2
    if error_count or unresolved:
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
