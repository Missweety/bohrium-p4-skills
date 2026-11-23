#!/usr/bin/env python3
"""Merge multi-database bibliographic records from supplied local files.

Only reads local CSV / TSV / JSON / JSONL. No network. Records are normalised,
clustered by exact DOI / PMID first, then by title-token Jaccard and year
proximity as review candidates. Field values are merged by priority and every
chosen value keeps the database, file and locator it came from.

Outputs under --out:
  merged.json     merged records with per-field source, gaps and stats
  duplicates.csv  exact duplicate groups and fuzzy duplicate candidates
  conflicts.csv   fields whose normalised values disagree across sources
  provenance.csv  one row per cluster/field/source-record value mapping
  issues.csv      dropped rows and recorded anomalies

Usage:
  python3 scripts/merge_records.py --input /input --out /app/work/merged \
      [--fuzzy-threshold 0.9] [--year-tolerance 1] [--fuzzy-merge] \
      [--priority-order crossref,europepmc] [--json]

Exit codes: 0 ok; 2 produced with dropped records, unreadable files, no records
or unresolved source gaps; 1 unusable input.
"""
import argparse
import csv
import json
import os
import re
import sys
import unicodedata
from collections import defaultdict

RECORD_KEYS = ("records", "rows", "data", "works", "items", "results", "papers")
STATUS_KEYS = ("source_status", "db_status", "database_status", "sources", "databases")
QUERY_KEYS = ("queries", "search_queries", "query_log")
TEXT_EXT = {".csv", ".tsv", ".json", ".jsonl"}
MAX_JSON_BYTES = 20 * 1024 * 1024

FIELD_ALIASES = {
    "source_db": ("source_db", "db", "database", "source", "provider", "api",
                  "source_database"),
    "doi": ("doi", "dois", "digital_object_identifier"),
    "pmid": ("pmid", "pubmed_id", "pubmedid", "medline_id", "pm_id"),
    "title": ("title", "paper_title", "article_title", "document_title", "name"),
    "authors": ("authors", "author", "author_list", "author_names", "creators"),
    "year": ("year", "publication_year", "pub_year", "issued", "date",
             "publication_date"),
    "journal": ("journal", "journal_title", "journal_name", "venue",
                "container_title", "source_title"),
    "type": ("type", "document_type", "publication_type", "item_type"),
    "raw_file": ("raw_file", "file", "source_file", "response_file",
                 "source_file_path"),
    "raw_locator": ("raw_locator", "locator", "source_locator", "position",
                    "page", "row"),
    "priority": ("priority", "priority_rank", "source_priority", "rank", "order"),
    "query": ("query", "query_string", "search_query", "queried_with"),
}
FIELDS = ("doi", "pmid", "title", "authors", "year", "journal", "type")
UNKNOWN_VALUES = {"", "na", "n a", "n/a", "unknown", "none", "null", "nan",
                  "not available", "-", "--", "?"}
PRIORITY_RULE = "smaller priority number wins; ties by source_db, file, locator, record_id"

TYPE_MAP = {
    "journalarticle": "journal-article", "article": "journal-article",
    "researcharticle": "journal-article", "reviewarticle": "review",
    "review": "review", "conferencepaper": "conference-paper",
    "proceedingsarticle": "conference-paper", "conference": "conference-paper",
    "preprint": "preprint", "postedcontent": "preprint",
    "bookchapter": "book-chapter", "chapter": "book-chapter",
    "dataset": "dataset", "thesis": "thesis", "dissertation": "thesis",
    "editorial": "editorial", "letter": "letter", "erratum": "erratum",
    "retraction": "retraction", "retractedpublication": "retraction",
}
STOPWORDS = {"a", "an", "the", "of", "for", "and", "in", "on", "to", "with",
             "by", "from", "at", "as", "is", "are", "via", "using", "into"}
DOI_RE = re.compile(r"^10\.\d{4,9}/\S+$", re.I)
YEAR_RE = re.compile(r"(19|20)\d{2}")


def norm_text(value):
    if value is None:
        return ""
    text = unicodedata.normalize("NFKC", str(value))
    text = re.sub(r"\s+", " ", text)
    return text.strip().casefold()


def norm_title(value):
    if value is None:
        return ""
    text = norm_text(value)
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


def norm_pmid(value):
    if value is None:
        return ""
    text = re.sub(r"(?i)^pmid:\s*", "", str(value).strip())
    return text if re.fullmatch(r"\d{1,12}", text) else ""


def norm_year(value):
    if value is None or str(value).strip() == "":
        return None
    match = YEAR_RE.search(str(value))
    return int(match.group(0)) if match else None


def norm_type(value):
    raw = norm_text(value)
    if not raw:
        return ""
    compact = re.sub(r"[^a-z0-9]", "", raw)
    return TYPE_MAP.get(compact, compact)


def split_authors(value):
    text = unicodedata.normalize("NFKC", str(value or "")).strip()
    if not text:
        return []
    if ";" in text:
        parts = re.split(r"\s*;\s*", text)
    elif re.search(r"\band\b", text, re.I):
        parts = re.split(r"\s+and\s+", text, flags=re.I)
    else:
        chunks = [part.strip() for part in text.split(",") if part.strip()]
        if len(chunks) <= 1:
            parts = chunks or [text]
        elif len(chunks) % 2 == 0 and all(len(chunk.split()) <= 3 for chunk in chunks):
            parts = [" ".join(chunks[index:index + 2])
                     for index in range(0, len(chunks), 2)]
        else:
            parts = chunks
    authors = []
    for part in parts:
        cleaned = re.sub(r"[^\w\s-]", " ", norm_text(part))
        cleaned = re.sub(r"\s+", " ", cleaned).strip()
        if cleaned:
            authors.append(cleaned)
    return authors


def title_tokens(title):
    tokens = [token for token in norm_title(title).split()
              if len(token) > 1 and token not in STOPWORDS]
    return frozenset(tokens)


def jaccard(left, right):
    if not left or not right:
        return 0.0
    union = left | right
    return len(left & right) / len(union) if union else 0.0


def norm_key(key):
    return re.sub(r"[\s-]+", "_", str(key).strip().casefold())


RECORD_MARKERS = frozenset(
    norm_key(alias)
    for field in ("doi", "pmid", "title", "authors", "year", "journal", "type",
                  "raw_file", "raw_locator", "priority")
    for alias in FIELD_ALIASES[field])



def pick(record, aliases):
    for name in aliases:
        if name in record and str(record[name]).strip() != "":
            return record[name]
    return ""


def is_unknown(value):
    if value is None:
        return True
    return norm_text(value) in UNKNOWN_VALUES


class Collector:
    def __init__(self):
        self.files = []
        self.records = []
        self.status = []
        self.queries = []
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
    if keys & {"status", "available", "error"} and not any(
            pick(record, FIELD_ALIASES[f]) for f in ("title", "doi", "pmid")):
        collector.status.append(dict(record, _file=rel, _locator=locator))
        return
    if any(pick(record, FIELD_ALIASES[f]) for f in ("title", "doi", "pmid")):
        collector.records.append(dict(record, _file=rel, _locator=locator))
        return
    if keys & RECORD_MARKERS:
        collector.records.append(dict(record, _file=rel, _locator=locator))
        return
    if pick(record, FIELD_ALIASES["source_db"]) and keys & {"records", "count", "total"}:
        collector.status.append(dict(record, _file=rel, _locator=locator))
        return
    collector.issue("warning", "unclassified_record",
                    "record has no title, DOI or PMID", rel, locator)


def walk_payload(payload, collector, rel, locator):
    if isinstance(payload, list):
        for index, item in enumerate(payload):
            walk_payload(item, collector, rel, "%s[%d]" % (locator, index))
        return
    if not isinstance(payload, dict):
        collector.issue("warning", "unsupported_json_value",
                        "JSON value is neither object nor array", rel, locator)
        return
    matched = False
    for key in STATUS_KEYS:
        value = payload.get(key)
        if isinstance(value, list):
            matched = True
            for index, item in enumerate(value):
                if isinstance(item, dict):
                    collector.status.append(dict(item, _file=rel,
                                                 _locator="%s.%s[%d]" % (locator, key, index)))
    for key in QUERY_KEYS:
        value = payload.get(key)
        if isinstance(value, list):
            matched = True
            for index, item in enumerate(value):
                collector.queries.append({"raw": item, "file": rel,
                                          "locator": "%s.%s[%d]" % (locator, key, index)})
    for key in RECORD_KEYS:
        value = payload.get(key)
        if isinstance(value, list):
            matched = True
            for index, item in enumerate(value):
                if isinstance(item, dict):
                    collector.records.append(dict(item, _file=rel,
                                                  _locator="%s.%s[%d]" % (locator, key, index)))
    known = set(STATUS_KEYS) | set(QUERY_KEYS) | set(RECORD_KEYS) | {"data"}
    for key, value in payload.items():
        if key in known or not isinstance(value, list):
            continue
        for index, item in enumerate(value):
            if not isinstance(item, dict):
                continue
            if any(pick(item, FIELD_ALIASES[f]) for f in ("title", "doi", "pmid")):
                collector.records.append(dict(item, _file=rel,
                                              _locator="%s.%s[%d]" % (locator, key, index)))
            elif pick(item, FIELD_ALIASES["source_db"]) and \
                    {"status", "state", "availability"} & {norm_key(k) for k in item}:
                collector.status.append(dict(item, _file=rel,
                                             _locator="%s.%s[%d]" % (locator, key, index)))
    if matched:
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
                if reader.fieldnames is None:
                    collector.issue("error", "empty_table", "no header row", rel, "")
                    return
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


def load_input(root, collector):
    if not os.path.exists(root):
        return False
    found = False
    for path, rel in iter_input_files(root):
        found = True
        collector.files.append(rel)
        read_file(path, rel, collector)
    return found


def query_map(collector):
    mapping = defaultdict(list)
    for entry in collector.queries:
        raw = entry["raw"]
        if isinstance(raw, dict):
            db = str(pick(raw, FIELD_ALIASES["source_db"])).strip()
            query = str(pick(raw, FIELD_ALIASES["query"])).strip()
            if not query and "query" in raw:
                query = str(raw.get("query"))
            if db and query:
                mapping[db].append(query)
        elif isinstance(raw, str):
            mapping["*"].append(raw)
    return {db: " | ".join(values) for db, values in mapping.items()}


def priority_override(order_text):
    order = {}
    for index, name in enumerate([part.strip() for part in order_text.split(",") if part.strip()]):
        order[name.casefold()] = index + 1
    return order


def normalize_record(record, record_id, collector, overrides):
    source_db = str(pick(record, FIELD_ALIASES["source_db"])).strip()
    if not source_db:
        source_db = "unspecified"
        collector.issue("warning", "missing_source_db",
                        "source_db missing; labelled unspecified",
                        record.get("_file", ""), record.get("_locator", ""))
    doi_raw = str(pick(record, FIELD_ALIASES["doi"])).strip()
    pmid_raw = str(pick(record, FIELD_ALIASES["pmid"])).strip()
    doi = norm_doi(doi_raw)
    pmid = norm_pmid(pmid_raw)
    if doi_raw and not doi:
        collector.issue("warning", "invalid_doi",
                        "DOI %r not normalized; ignored for clustering" % doi_raw,
                        record.get("_file", ""), record.get("_locator", ""))
    if pmid_raw and not pmid:
        collector.issue("warning", "invalid_pmid",
                        "PMID %r is not numeric; ignored for clustering" % pmid_raw,
                        record.get("_file", ""), record.get("_locator", ""))
    title_raw = str(pick(record, FIELD_ALIASES["title"])).strip()
    authors_raw = str(pick(record, FIELD_ALIASES["authors"])).strip()
    year_raw = pick(record, FIELD_ALIASES["year"])
    journal_raw = str(pick(record, FIELD_ALIASES["journal"])).strip()
    type_raw = str(pick(record, FIELD_ALIASES["type"])).strip()
    year = norm_year(year_raw)
    if not (doi or pmid or norm_title(title_raw)):
        collector.issue("error", "missing_identity",
                        "record dropped; no DOI, PMID or usable title",
                        record.get("_file", ""), record.get("_locator", ""))
        return None
    if not title_raw:
        collector.issue("warning", "missing_title", "record has no title",
                        record.get("_file", ""), record.get("_locator", ""))
    if year is None and str(year_raw).strip() != "":
        collector.issue("warning", "invalid_year", "year %r not parsed" % str(year_raw),
                        record.get("_file", ""), record.get("_locator", ""))
    priority_raw = pick(record, FIELD_ALIASES["priority"])
    priority = None
    if str(priority_raw).strip() != "":
        try:
            priority = float(str(priority_raw))
        except ValueError:
            collector.issue("warning", "invalid_priority",
                            "priority %r not numeric; default order used" % str(priority_raw),
                            record.get("_file", ""), record.get("_locator", ""))
    if priority is None:
        priority = overrides.get(source_db.casefold(), 1000)
    query = str(pick(record, FIELD_ALIASES["query"])).strip()
    return {
        "record_id": record_id,
        "source_db": source_db,
        "doi": doi,
        "pmid": pmid,
        "title_raw": title_raw,
        "title_key": norm_title(title_raw),
        "title_tokens": title_tokens(title_raw),
        "authors_raw": authors_raw,
        "authors_key": ";".join(split_authors(authors_raw)),
        "year": year,
        "journal_raw": journal_raw,
        "journal_key": norm_title(journal_raw),
        "type_raw": type_raw,
        "type_key": norm_type(type_raw),
        "priority": priority,
        "query": query,
        "raw_file": str(pick(record, FIELD_ALIASES["raw_file"])).strip()
                    or record.get("_file", ""),
        "raw_locator": str(pick(record, FIELD_ALIASES["raw_locator"])).strip()
                       or record.get("_locator", ""),
    }


def field_status(record, field):
    if field == "doi":
        return "present" if record["doi"] else "missing"
    if field == "pmid":
        return "present" if record["pmid"] else "missing"
    if field == "year":
        return "present" if record["year"] is not None else "missing"
    raw = record[field + "_raw"]
    if is_unknown(raw):
        return "unknown" if str(raw).strip() else "missing"
    key = record[field + "_key"]
    return "present" if key else "missing"


def normalized_value(record, field):
    if field == "year":
        return record["year"]
    if field in ("doi", "pmid"):
        return record[field]
    return record[field + "_key"]


class UnionFind:
    def __init__(self, size):
        self.parent = list(range(size))

    def find(self, index):
        while self.parent[index] != index:
            self.parent[index] = self.parent[self.parent[index]]
            index = self.parent[index]
        return index

    def union(self, left, right):
        root_left, root_right = self.find(left), self.find(right)
        if root_left != root_right:
            if root_left < root_right:
                self.parent[root_right] = root_left
            else:
                self.parent[root_left] = root_right


def cluster_records(records, threshold, year_tolerance, fuzzy_merge, collector):
    uf = UnionFind(len(records))
    exact_groups = []

    for field, label in (("doi", "doi_exact"), ("pmid", "pmid_exact")):
        groups = defaultdict(list)
        for index, record in enumerate(records):
            if record[field]:
                groups[record[field]].append(index)
        for key in sorted(groups):
            members = groups[key]
            if len(members) > 1:
                for member in members[1:]:
                    uf.union(members[0], member)
                exact_groups.append({"type": label, "key": key,
                                     "members": sorted(members)})

    fuzzy = []
    near = []
    best = {}
    for left in range(len(records)):
        for right in range(left + 1, len(records)):
            if uf.find(left) == uf.find(right):
                continue
            score = jaccard(records[left]["title_tokens"], records[right]["title_tokens"])
            if score < threshold:
                continue
            year_left, year_right = records[left]["year"], records[right]["year"]
            if year_left is None or year_right is None:
                near.append({"pair": (left, right), "jaccard": score,
                             "reason": "year missing; proximity unverified"})
                continue
            delta = abs(year_left - year_right)
            if delta > year_tolerance:
                near.append({"pair": (left, right), "jaccard": score,
                             "reason": "year delta %d exceeds tolerance %d"
                                       % (delta, year_tolerance)})
                continue
            cluster_pair = tuple(sorted((uf.find(left), uf.find(right))))
            entry = {"pair": (left, right), "jaccard": score, "year_delta": delta}
            if cluster_pair not in best or score > best[cluster_pair]["jaccard"]:
                best[cluster_pair] = entry
    for cluster_pair in sorted(best):
        fuzzy.append(best[cluster_pair])
        if fuzzy_merge:
            uf.union(cluster_pair[0], cluster_pair[1])

    near.sort(key=lambda item: (-item["jaccard"], item["pair"]))
    return uf, exact_groups, fuzzy, near


def priority_key(record_id):
    return record_id


def merge_clusters(records, uf, cluster_ids):
    groups = defaultdict(list)
    for index, record in enumerate(records):
        groups[uf.find(index)].append(index)
    merged = []
    provenance = []
    conflicts = []
    for root in sorted(groups, key=lambda item: min(records[index]["record_id"]
                                                    for index in groups[item])):
        members = sorted(groups[root], key=lambda index: records[index]["record_id"])
        cluster_id = cluster_ids[root]
        fields_out = {}
        conflict_rows = []
        record_ids = [records[index]["record_id"] for index in members]
        source_dbs = sorted({records[index]["source_db"] for index in members})
        for field in FIELDS:
            contributing = []
            unknown_seen = False
            for index in members:
                record = records[index]
                status = field_status(record, field)
                if status == "present":
                    contributing.append((record, normalized_value(record, field)))
                elif status == "unknown":
                    unknown_seen = True
            if not contributing:
                fields_out[field] = {
                    "value": None, "normalized": None, "status": "unknown" if unknown_seen
                    else "missing", "source_db": None, "raw_file": None,
                    "raw_locator": None, "source_record": None, "source_count": 0,
                }
            else:
                contributing.sort(key=lambda item: (item[0]["priority"],
                                                    item[0]["source_db"],
                                                    item[0]["raw_file"],
                                                    item[0]["raw_locator"],
                                                    item[0]["record_id"]))
                chosen, chosen_norm = contributing[0]
                distinct = {}
                for record, norm in contributing:
                    distinct.setdefault(str(norm), []).append(record)
                fields_out[field] = {
                    "value": chosen[field + "_raw"] if field not in ("doi", "pmid", "year")
                    else (chosen[field] if field != "year" else chosen["year"]),
                    "normalized": chosen_norm,
                    "status": "present",
                    "source_db": chosen["source_db"],
                    "raw_file": chosen["raw_file"],
                    "raw_locator": chosen["raw_locator"],
                    "source_record": chosen["record_id"],
                    "source_count": len(distinct),
                }
                if len(distinct) > 1:
                    others = sorted(key for key in distinct if key != str(chosen_norm))
                    for other in others:
                        other_records = sorted(distinct[other],
                                               key=lambda record: (record["priority"],
                                                                   record["source_db"],
                                                                   record["record_id"]))
                        representative = other_records[0]
                        conflict_rows.append({
                            "cluster_id": cluster_id,
                            "field": field,
                            "chosen_value": fields_out[field]["value"],
                            "chosen_source": chosen["source_db"],
                            "chosen_normalized": str(chosen_norm),
                            "other_value": representative[field + "_raw"]
                            if field not in ("doi", "pmid", "year")
                            else (representative[field] if field != "year"
                                  else representative["year"]),
                            "other_normalized": other,
                            "other_sources": ";".join(sorted({record["source_db"]
                                                              for record in other_records})),
                            "reason": "normalised values differ across sources",
                        })
            for index in members:
                record = records[index]
                status = field_status(record, field)
                if status == "missing":
                    continue
                value = None
                if status == "present":
                    raw = record[field + "_raw"] if field not in ("doi", "pmid", "year") \
                        else (record[field] if field != "year" else record["year"])
                    value = raw
                selected = (status == "present"
                            and record["record_id"] == fields_out[field]["source_record"])
                provenance.append({
                    "cluster_id": cluster_id,
                    "field": field,
                    "record_id": record["record_id"],
                    "source_db": record["source_db"],
                    "raw_value": value,
                    "normalized_value": normalized_value(record, field) if status == "present"
                    else "",
                    "status": status,
                    "raw_file": record["raw_file"],
                    "raw_locator": record["raw_locator"],
                    "query": record["query"],
                    "selected": "yes" if selected else "no",
                })
        fields_out["doi"]["value"] = fields_out["doi"]["value"] or None
        merged.append({
            "cluster_id": cluster_id,
            "record_ids": record_ids,
            "source_dbs": source_dbs,
            "record_count": len(members),
            "identity": {
                "doi": fields_out["doi"]["value"],
                "pmid": fields_out["pmid"]["value"],
                "title": fields_out["title"]["value"],
                "year": fields_out["year"]["value"],
            },
            "fields": fields_out,
            "conflicts": conflict_rows,
        })
        conflicts.extend(conflict_rows)
    return merged, provenance, conflicts


def source_health(collector):
    entries = []
    for item in collector.status:
        db = str(pick(item, FIELD_ALIASES["source_db"])).strip() or "unspecified"
        status = str(pick(item, ("status", "state", "availability"))).strip()
        error = str(pick(item, ("error", "message", "detail", "reason"))).strip()
        entries.append({"source_db": db, "status": status or "unspecified",
                        "error": error, "file": item.get("_file", ""),
                        "locator": item.get("_locator", "")})
    return sorted(entries, key=lambda item: (item["source_db"], item["status"]))


def build_gaps(status_entries, records):
    present = defaultdict(int)
    for record in records:
        present[record["source_db"]] += 1
    gaps = []
    healthy = {"ok", "success", "available", "complete", "completed", "200"}
    for entry in status_entries:
        state = entry["status"].casefold()
        if state and state not in healthy:
            gaps.append({"source_db": entry["source_db"],
                         "gap": "source_unavailable_or_incomplete",
                         "detail": entry["error"] or entry["status"]})
        elif present.get(entry["source_db"], 0) == 0:
            gaps.append({"source_db": entry["source_db"], "gap": "no_records",
                         "detail": "source reported healthy but supplied no record"})
    for source_db in sorted(present):
        if not any(entry["source_db"] == source_db for entry in status_entries):
            gaps.append({"source_db": source_db, "gap": "status_unknown",
                         "detail": "records supplied without a declared source status"})
    return gaps


def coverage(records):
    per_source = {}
    for record in records:
        entry = per_source.setdefault(record["source_db"],
                                      {"records": 0,
                                       "fields_present": {field: 0 for field in FIELDS}})
        entry["records"] += 1
        for field in FIELDS:
            if field_status(record, field) == "present":
                entry["fields_present"][field] += 1
    return per_source


def write_csv(path, rows, fields):
    with open(path, "w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            flat = {}
            for field in fields:
                value = row.get(field, "")
                if isinstance(value, (dict, list, tuple)):
                    value = json.dumps(value, ensure_ascii=False, sort_keys=True)
                flat[field] = value
            writer.writerow(flat)


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--input", required=True,
                        help="input directory or one CSV/TSV/JSON/JSONL file")
    parser.add_argument("--out", required=True, help="output directory")
    parser.add_argument("--fuzzy-threshold", type=float, default=0.9,
                        help="title token Jaccard threshold for review candidates (default 0.9)")
    parser.add_argument("--year-tolerance", type=int, default=1,
                        help="allowed year difference for fuzzy candidates (default 1)")
    parser.add_argument("--fuzzy-merge", action="store_true",
                        help="also merge fuzzy candidates automatically (default: review only)")
    parser.add_argument("--priority-order", default="",
                        help="fallback source precedence, e.g. crossref,europepmc")
    parser.add_argument("--json", action="store_true", help="print the stats object as JSON")
    args = parser.parse_args()
    if not 0 < args.fuzzy_threshold <= 1:
        print("error: --fuzzy-threshold must be in (0, 1]", file=sys.stderr)
        return 1
    if args.year_tolerance < 0:
        print("error: --year-tolerance must be >= 0", file=sys.stderr)
        return 1

    collector = Collector()
    if not os.path.exists(args.input):
        print("error: input path not found: %s" % args.input, file=sys.stderr)
        return 1
    if not load_input(args.input, collector):
        print("error: no CSV/TSV/JSON/JSONL input files found at %s" % args.input,
              file=sys.stderr)
        return 1

    overrides = priority_override(args.priority_order)
    queries = query_map(collector)
    records = []
    for raw in collector.records:
        record = normalize_record(raw, "R%05d" % (len(records) + 1), collector, overrides)
        if not record:
            continue
        if not record["query"]:
            record["query"] = queries.get(record["source_db"], "") or queries.get("*", "")
        records.append(record)

    dropped = len(collector.records) - len(records)
    if not records:
        collector.issue("error", "no_valid_records",
                        "no record with DOI, PMID or title survived validation")

    uf, exact_groups, fuzzy, near = cluster_records(
        records, args.fuzzy_threshold, args.year_tolerance, args.fuzzy_merge, collector)

    # Map final roots to stable cluster ids ordered by earliest record id.
    roots = defaultdict(list)
    for index, record in enumerate(records):
        roots[uf.find(index)].append(record["record_id"])
    ordered_roots = sorted(roots, key=lambda root: min(roots[root]))
    cluster_ids = {root: "M%04d" % (number + 1)
                   for number, root in enumerate(ordered_roots)}

    merged, provenance, conflicts = merge_clusters(records, uf, cluster_ids)
    status_entries = source_health(collector)
    gaps = build_gaps(status_entries, records)

    duplicate_rows = []
    for group in sorted(exact_groups, key=lambda item: (item["type"], item["key"])):
        root = uf.find(group["members"][0])
        duplicate_rows.append({
            "group_type": group["type"],
            "key": group["key"],
            "cluster_id": cluster_ids.get(root, ""),
            "record_ids": ";".join(records[index]["record_id"] for index in group["members"]),
            "jaccard": "",
            "year_delta": "",
            "decision": "merged",
            "reason": "shared exact normalized identifier",
        })
    for entry in sorted(fuzzy, key=lambda item: (-item["jaccard"], item["pair"])):
        left, right = entry["pair"]
        duplicate_rows.append({
            "group_type": "fuzzy_title_year",
            "key": "%s || %s" % (records[left]["title_key"], records[right]["title_key"]),
            "cluster_id": cluster_ids.get(uf.find(left), ""),
            "record_ids": records[left]["record_id"] + ";" + records[right]["record_id"],
            "jaccard": "%.4f" % entry["jaccard"],
            "year_delta": entry["year_delta"],
            "decision": "merged_by_fuzzy" if args.fuzzy_merge else "candidate_review",
            "reason": "title token Jaccard >= %.2f and year delta <= %d"
                      % (args.fuzzy_threshold, args.year_tolerance),
        })
    for entry in near:
        left, right = entry["pair"]
        duplicate_rows.append({
            "group_type": "fuzzy_near_miss",
            "key": "%s || %s" % (records[left]["title_key"], records[right]["title_key"]),
            "cluster_id": cluster_ids.get(uf.find(left), ""),
            "record_ids": records[left]["record_id"] + ";" + records[right]["record_id"],
            "jaccard": "%.4f" % entry["jaccard"],
            "year_delta": "",
            "decision": "not_merged",
            "reason": entry["reason"],
        })

    severity_order = {"error": 0, "warning": 1, "info": 2}
    issues = sorted(collector.issues, key=lambda item: (severity_order.get(item["severity"], 9),
                                                       item["code"], item["file"],
                                                       item["locator"], item["detail"]))
    stats = {
        "input_files": len(collector.files),
        "record_rows_read": len(collector.records),
        "records_valid": len(records),
        "records_dropped": dropped,
        "clusters": len(merged),
        "multi_record_clusters": sum(1 for item in merged if item["record_count"] > 1),
        "exact_groups": len(exact_groups),
        "fuzzy_candidates": len(fuzzy),
        "fuzzy_near_misses": len(near),
        "conflicts": len(conflicts),
        "sources": len({record["source_db"] for record in records}),
        "gaps": len(gaps),
        "empty_result": len(merged) == 0,
        "issues": {key: sum(1 for item in issues if item["severity"] == key)
                   for key in ("error", "warning", "info")},
    }
    payload = {
        "generated_by": "merge_records.py",
        "scope_note": "Only records supplied in the input files are merged. "
                      "No live database query, no global coverage claim.",
        "input": {"root": os.path.abspath(args.input),
                  "files": collector.files,
                  "record_rows_read": len(collector.records)},
        "params": {
            "fuzzy_threshold": args.fuzzy_threshold,
            "year_tolerance": args.year_tolerance,
            "fuzzy_merge": bool(args.fuzzy_merge),
            "priority_rule": PRIORITY_RULE,
            "fallback_priority_order": [part.strip() for part in
                                        args.priority_order.split(",") if part.strip()],
        },
        "coverage": coverage(records),
        "source_status": status_entries,
        "gaps": gaps,
        "stats": stats,
        "records": merged,
        "issues": issues,
    }
    os.makedirs(args.out, exist_ok=True)
    with open(os.path.join(args.out, "merged.json"), "w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=1)
    write_csv(os.path.join(args.out, "duplicates.csv"), duplicate_rows,
              ["group_type", "key", "cluster_id", "record_ids", "jaccard",
               "year_delta", "decision", "reason"])
    write_csv(os.path.join(args.out, "conflicts.csv"), conflicts,
              ["cluster_id", "field", "chosen_value", "chosen_source",
               "chosen_normalized", "other_value", "other_normalized",
               "other_sources", "reason"])
    write_csv(os.path.join(args.out, "provenance.csv"), provenance,
              ["cluster_id", "field", "record_id", "source_db", "raw_value",
               "normalized_value", "status", "raw_file", "raw_locator", "query",
               "selected"])
    write_csv(os.path.join(args.out, "issues.csv"), issues,
              ["severity", "code", "detail", "file", "locator", "raw"])

    summary = dict(stats, out_dir=os.path.abspath(args.out))
    if args.json:
        print(json.dumps(summary, ensure_ascii=False, indent=1))
    else:
        print("records=%d clusters=%d merged_from_multiple=%d conflicts=%d "
              "fuzzy=%d dropped=%d gaps=%d"
              % (len(records), len(merged), stats["multi_record_clusters"],
                 len(conflicts), len(fuzzy), dropped, len(gaps)))
        print("wrote merged.json, duplicates.csv, conflicts.csv, provenance.csv, "
              "issues.csv -> %s" % args.out)
    error_count = sum(1 for item in issues if item["severity"] == "error")
    blocking_gap = any(gap["gap"] == "source_unavailable_or_incomplete" for gap in gaps)
    if not merged:
        return 2
    if dropped or error_count or blocking_gap:
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
