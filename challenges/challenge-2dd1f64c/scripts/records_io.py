#!/usr/bin/env python3
"""records_io.py - tolerant loader for local literature exports (Crossref / EuropePMC / CSV / JSONL).

Field aliases are resolved case-insensitively; nothing is fetched and nothing is invented:
missing title/doi/year stay empty and are reported as unknown downstream. Stdlib only.
"""
import csv
import hashlib
import json
import os
import re

TAG, WS = re.compile(r"<[^>]+>"), re.compile(r"\s+")
PUNC = re.compile(r"[^0-9a-z\u4e00-\u9fff]+")
FIELDS = ["title", "abstract", "doi", "arxiv", "year", "authors", "venue", "doc_type", "language"]


def pick(o, names):
    low = {str(k).lower(): v for k, v in o.items()}
    for n in names:
        v = low.get(n)
        if v not in (None, "", [], {}):
            return v
    return None


def as_text(v):
    if isinstance(v, list):
        return WS.sub(" ", " ".join(as_text(x) for x in v)).strip()
    if isinstance(v, dict):
        return as_text([v.get(k) for k in ("family", "given", "name", "value")])
    return "" if v is None else WS.sub(" ", TAG.sub(" ", str(v))).strip()


def year_of(v):
    if isinstance(v, dict):
        return year_of(next((v[k] for k in ("date-parts", "year", "value") if k in v), ""))
    if isinstance(v, list):
        return year_of(v[0]) if v else ""
    m = re.search(r"(19|20)\d{2}", str(v))
    return m.group(0) if m else ""


def norm_doi(v):
    return as_text(v).lower().replace("https://doi.org/", "").replace(
        "http://dx.doi.org/", "").strip(" .;")


def map_rec(o, src):
    t = as_text(pick(o, ["title", "article-title", "article_title", "name"]))
    nt = PUNC.sub(" ", t.lower()).strip()
    r = {"title": t, "abstract": as_text(pick(o, ["abstract", "abstracttext", "abstract_text", "summary"])),
         "doi": norm_doi(pick(o, ["doi", "prism:doi"])),
         "arxiv": as_text(pick(o, ["arxiv", "arxiv_id", "arxivid", "eprint"])),
         "year": year_of(pick(o, ["year", "pubyear", "publication_year", "issued", "published",
                                  "first_published", "date"])),
         "authors": as_text(pick(o, ["authors", "author", "authorstring", "author_list"])),
         "venue": as_text(pick(o, ["venue", "journal", "journaltitle", "container-title", "journal_title"])),
         "doc_type": as_text(pick(o, ["type", "doctype", "pubtype", "publication_type"])),
         "language": as_text(pick(o, ["language", "lang"])), "source_file": o.get("_source_file") or src,
         "merged_from": [], "matched_blocks": [], "required_missed": [], "score": 0}
    r["keys"] = [x for x in ("doi:" + r["doi"] if r["doi"] else "",
                             "arxiv:" + r["arxiv"].lower() if r["arxiv"] else "",
                             "title:" + hashlib.sha1(nt.encode("utf-8")).hexdigest()[:12] if nt else "") if x]
    return r


def iter_json(data):
    if isinstance(data, list):
        return data
    low = {str(k).lower(): v for k, v in data.items()}
    for k in ("items", "records", "results", "result", "resultlist", "message", "data"):
        v = low.get(k)
        if isinstance(v, list):
            return v
        if isinstance(v, dict):
            inner = {str(x).lower(): y for x, y in v.items()}
            if isinstance(inner.get("items") or inner.get("result"), list):
                return inner.get("items") or inner.get("result")
    return [data]


def load(paths):
    out = []
    for p in paths:
        ext, src = os.path.splitext(p)[1].lower(), os.path.basename(p)
        if ext in (".csv", ".tsv"):
            with open(p, encoding="utf-8-sig", errors="replace") as fh:
                out += [map_rec(x, src) for x in
                        csv.DictReader(fh, delimiter="\t" if ext == ".tsv" else ",")]
        elif ext == ".jsonl":
            out += [map_rec(json.loads(x), src) for x in open(p, encoding="utf-8") if x.strip()]
        else:
            out += [map_rec(x, src) for x in iter_json(json.load(open(p, encoding="utf-8")))
                    if isinstance(x, dict)]
    return [r for r in out if r["title"]]


def screen(rec, rules):
    why = []
    yf, yt = str(rules.get("year_from") or ""), str(rules.get("year_to") or "")
    if yf and rec["year"] and rec["year"] < yf:
        why.append("year_before_window(%s)" % rec["year"])
    if yt and rec["year"] and rec["year"] > yt:
        why.append("year_after_window(%s)" % rec["year"])
    if rules.get("doc_types") and rec["doc_type"] and \
            rec["doc_type"].lower() not in [d.lower() for d in rules["doc_types"]]:
        why.append("doc_type_excluded(%s)" % rec["doc_type"])
    if rules.get("languages") and rec["language"] and \
            rec["language"].lower() not in [x.lower() for x in rules["languages"]]:
        why.append("language_excluded(%s)" % rec["language"])
    hay = (rec["title"] + " " + rec["abstract"]).lower()
    why += ["exclude_term(%s)" % t for t in rules.get("exclude_terms") or [] if t.lower() in hay]
    return why
