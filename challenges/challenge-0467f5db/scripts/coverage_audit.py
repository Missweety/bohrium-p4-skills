#!/usr/bin/env python3
"""Audit search coverage against a supplied reference set (offline, stdlib only).

Reads a reference set and the records returned by supplied search exports,
matches each reference entry to the record set, and writes:
  coverage.csv   per-reference hit/miss/uncertain matrix
  misses.csv     one row per missed reference, grouped category preserved
  report.md      readable audit report with counts, formulas and limits
  audit.json     structured core result
  result.json    output_contract-mapped result when a case file is supplied

Matching rule (fixed, documented in references/method.md):
  1. exact normalised DOI;
  2. otherwise normalised title equality AND equal year AND author-surname
     Jaccard >= 0.85.
Anything weaker is "uncertain" and is never reported as a hit.

The tool never infers a miss category that is not in the input. Missing
categories are emitted as "unlabeled". Supplemental searches are only
reported as executed when an explicit supplement record says so.

Usage:
  python coverage_audit.py --input /input --out /app/output
  python coverage_audit.py --input refs.csv --refs refs.csv --hits hits.csv --out out
  python coverage_audit.py --input /input --case /input/case.json --out /app/output

Exit codes: 0 ok, 1 invalid input, 2 completed with partial/unreadable data.
"""

import argparse
import csv
import json
import os
import re
import sys
import unicodedata

RULES_VERSION = "coverage-audit/1.0"
AUTHOR_JACCARD = 0.85
NEAR_TITLE_JACCARD = 0.90

REF_HINTS = ("ref", "gold", "known", "includ")
HIT_HINTS = ("hit", "record", "result", "search", "candidate", "export", "screen", "retriev")
AUX_HINTS = ("supplement", "classif", "override", "schema", "manifest")

# ---------------------------------------------------------------- text helpers


def sval(value):
    """Render any cell value as a trimmed string without inventing content."""
    if value is None:
        return ""
    if isinstance(value, (list, tuple)):
        return "; ".join(part for part in (sval(v) for v in value) if part)
    if isinstance(value, dict):
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    return str(value).strip()


def norm_key(key):
    key = unicodedata.normalize("NFKC", str(key)).strip().lower()
    key = re.sub(r"[^0-9a-z\u4e00-\u9fff]+", "_", key)
    return key.strip("_")


def norm_doi(value):
    text = sval(value).lower()
    if not text:
        return ""
    text = re.sub(r"^(https?://(dx\.)?doi\.org/|doi:\s*|doi\s+)", "", text)
    return text.strip().strip(".,; ")


def norm_title(value):
    """Keep only letters/digits: equality is robust to spacing and punctuation."""
    text = unicodedata.normalize("NFKC", sval(value)).casefold()
    text = text.replace("&", "and")
    return "".join(ch for ch in text if ch.isalnum())


def norm_year(value):
    match = re.search(r"(?:19|20)\d{2}", sval(value))
    return match.group(0) if match else ""


def jaccard(left, right):
    if not left or not right:
        return None
    return len(left & right) / len(left | right)


def author_surnames(value):
    """Best-effort surname extraction; set comparison is order independent.

    Delimiters: ; | & 、 and the word "and". With a comma the family name is
    taken from before the comma (whole segment). Without a comma the first
    non-initial token is used (Family Given convention). A Chinese name with
    no spaces is kept as one string.
    """
    raw = sval(value)
    if not raw:
        return set()
    raw = re.sub(r"\([^)]*\)", " ", raw)
    raw = re.sub(r"\bet\s+al\.?", " ", raw, flags=re.I)
    raw = re.sub(r"\d+", " ", raw)

    chunks = []  # (text, keep whole segment as the family name)
    has_delimiter = re.search(r"[;|&、]|\band\b", raw, flags=re.I) is not None
    if has_delimiter:
        for part in re.split(r"\s*(?:;|\||&|、|\band\b)\s*", raw, flags=re.I):
            part = part.strip()
            if not part:
                continue
            if "," in part:
                chunks.append((part.split(",")[0].strip(), True))
            else:
                chunks.append((part, False))
    elif "," in raw:
        parts = [p.strip() for p in raw.split(",") if p.strip()]
        if len(parts) % 2 == 0:
            chunks = [(parts[i], True) for i in range(0, len(parts), 2)]
        else:
            chunks = [(part, False) for part in parts]
    else:
        chunks = [(raw, False)]

    found = set()
    for text, whole in chunks:
        tokens = [t for t in re.split(r"\s+", text.strip().strip(".")) if t]
        tokens = [t for t in tokens if not re.fullmatch(r"[A-Z]\.?", t) and len(t) > 1]
        if not tokens:
            continue
        if whole:
            found.add(" ".join(tokens).casefold())
        else:
            found.add(tokens[0].casefold())
    return found


def title_tokens(normed_title):
    """Character bigrams so CJK and hyphen/space variants compare sensibly."""
    if not normed_title:
        return set()
    if len(normed_title) == 1:
        return {normed_title}
    return {normed_title[i:i + 2] for i in range(len(normed_title) - 1)}


# ---------------------------------------------------------------- table loading


def _delimiter(first_line, ext):
    if ext == ".tsv":
        return "\t"
    return max([",", ";", "\t"], key=first_line.count)


def _normalise_row(row):
    out = {}
    raw = {}
    for key, value in row.items():
        if key is None:
            continue
        nkey = norm_key(key)
        if not nkey:
            continue
        text = sval(value)
        raw.setdefault(nkey, key)
        if nkey not in out or (not out[nkey] and text):
            out[nkey] = text
    out["_raw_keys"] = raw
    return out


def read_table(path):
    ext = os.path.splitext(path)[1].lower()
    rows = []
    if ext in {".csv", ".tsv"}:
        with open(path, encoding="utf-8-sig", errors="replace", newline="") as handle:
            first = handle.readline()
            handle.seek(0)
            reader = csv.DictReader(handle, delimiter=_delimiter(first, ext))
            for row in reader:
                item = _normalise_row(row)
                if any(v for k, v in item.items() if k != "_raw_keys"):
                    rows.append(item)
        return rows
    if ext == ".jsonl":
        with open(path, encoding="utf-8-sig", errors="replace") as handle:
            for line in handle:
                if not line.strip():
                    continue
                try:
                    data = json.loads(line)
                except json.JSONDecodeError as exc:
                    raise ValueError("%s: invalid JSON line: %s" % (path, exc))
                if isinstance(data, dict):
                    rows.append(_normalise_row(data))
        return rows
    if ext == ".json":
        with open(path, encoding="utf-8-sig", errors="replace") as handle:
            try:
                data = json.load(handle)
            except json.JSONDecodeError as exc:
                raise ValueError("%s: invalid JSON: %s" % (path, exc))
        if isinstance(data, list):
            items = data
        elif isinstance(data, dict):
            items = None
            for key in ("rows", "records", "items", "data", "results", "reference_set",
                        "references", "hits", "candidates"):
                value = data.get(key)
                if isinstance(value, list):
                    items = value
                    break
            if items is None:
                items = [data]
        else:
            raise ValueError("%s: JSON root must be an object or array" % path)
        for item in items:
            if isinstance(item, dict):
                rows.append(_normalise_row(item))
        return rows
    raise ValueError("%s: unsupported extension %s" % (path, ext))


def pick(row, aliases, default=""):
    for alias in aliases:
        key = norm_key(alias)
        if key in row and row[key] != "":
            return row[key]
    return default


REF_ALIASES = {
    "ref_id": ["ref_id", "reference_id", "refid", "ref", "id", "key", "编号", "文献编号", "参考编号"],
    "doi": ["doi", "dois", "digital_object_identifier"],
    "title": ["title", "article_title", "paper_title", "name", "标题", "题名", "文献标题"],
    "authors": ["authors", "author", "author_list", "authors_list", "作者"],
    "year": ["year", "publication_year", "pub_year", "published_year", "date", "年份", "发表年份"],
    "include_reason": ["include_reason", "inclusion_reason", "reason", "inclusion", "纳入理由", "纳入原因"],
    "unavailable": ["unavailable", "availability", "status", "access_status", "fulltext_status",
                    "不可用", "状态"],
    "miss_category": ["miss_category", "missed_category", "omission_category",
                      "miss_reason_category", "category", "遗漏类别", "漏检类别", "遗漏类型"],
    "notes": ["note", "notes", "comment", "remarks", "备注", "说明"],
}

HIT_ALIASES = {
    "record_id": ["record_id", "hit_id", "rid", "result_id", "rec_id", "id", "记录编号", "结果编号"],
    "doi": ["doi", "dois", "digital_object_identifier"],
    "title": ["title", "article_title", "paper_title", "name", "标题", "题名", "文献标题"],
    "authors": ["authors", "author", "author_list", "authors_list", "作者"],
    "year": ["year", "publication_year", "pub_year", "published_year", "date", "年份", "发表年份"],
    "query_id": ["query_id", "query", "query_no", "search_id", "strategy_id",
                 "查询编号", "检索式编号", "查询id"],
    "source": ["source", "database", "db", "source_name", "provider", "来源", "数据库"],
}

FALSE_WORDS = {"", "0", "false", "no", "n", "available", "full_text", "fulltext", "included", "ok"}


def parse_unavailable(value):
    text = sval(value)
    if not text:
        return False, ""
    lowered = text.casefold()
    if lowered in FALSE_WORDS:
        return False, ""
    if lowered in {"true", "1", "yes", "y", "unavailable", "retracted", "no_fulltext",
                   "not_available", "embargoed", "missing"}:
        return True, text
    # A free-text status is treated as unavailable only when it says so.
    if any(word in lowered for word in ("unavailable", "retract", "撤稿", "无法获取", "不可用", "missing")):
        return True, text
    return False, ""


def normalise_ref(row):
    unavailable, unavailable_reason = parse_unavailable(pick(row, REF_ALIASES["unavailable"]))
    return {
        "ref_id": pick(row, REF_ALIASES["ref_id"]),
        "doi": pick(row, REF_ALIASES["doi"]),
        "title": pick(row, REF_ALIASES["title"]),
        "authors": pick(row, REF_ALIASES["authors"]),
        "year": pick(row, REF_ALIASES["year"]),
        "include_reason": pick(row, REF_ALIASES["include_reason"]),
        "unavailable": unavailable,
        "unavailable_reason": unavailable_reason,
        "miss_category": pick(row, REF_ALIASES["miss_category"]),
        "notes": pick(row, REF_ALIASES["notes"]),
    }


def normalise_hit(row):
    return {
        "record_id": pick(row, HIT_ALIASES["record_id"]),
        "doi": pick(row, HIT_ALIASES["doi"]),
        "title": pick(row, HIT_ALIASES["title"]),
        "authors": pick(row, HIT_ALIASES["authors"]),
        "year": pick(row, HIT_ALIASES["year"]),
        "query_id": pick(row, HIT_ALIASES["query_id"]),
        "source": pick(row, HIT_ALIASES["source"]),
    }


def guess_kind(rows):
    keys = set()
    for row in rows[:5]:
        keys.update(k for k in row if k != "_raw_keys")
    ref_score = sum(1 for group in ("ref_id", "include_reason", "unavailable", "miss_category")
                    if any(norm_key(a) in keys for a in REF_ALIASES[group]))
    hit_score = sum(1 for group in ("record_id", "query_id", "source")
                    if any(norm_key(a) in keys for a in HIT_ALIASES[group]))
    if ref_score > hit_score:
        return "refs"
    if hit_score > ref_score:
        return "hits"
    return "unknown"


def split_json_file(path):
    with open(path, encoding="utf-8-sig", errors="replace") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        return None
    ref_value = None
    hit_value = None
    for key in ("reference_set", "references", "refs", "gold_set", "known_set"):
        if isinstance(data.get(key), list):
            ref_value = data[key]
            break
    for key in ("hits", "records", "candidates", "results", "search_results", "hit_records"):
        if isinstance(data.get(key), list):
            hit_value = data[key]
            break
    if ref_value is None or hit_value is None:
        return None
    to_rows = lambda items: [_normalise_row(i) for i in items if isinstance(i, dict)]
    return to_rows(ref_value), to_rows(hit_value)


def discover(input_path, explicit_refs, explicit_hits):
    """Return (ref_rows, hit_rows, ref_label, hit_label, limits)."""
    limits = []
    ref_rows = read_table(explicit_refs) if explicit_refs else None
    hit_rows = read_table(explicit_hits) if explicit_hits else None
    ref_label = os.path.basename(explicit_refs) if explicit_refs else ""
    hit_label = os.path.basename(explicit_hits) if explicit_hits else ""

    if ref_rows is not None and hit_rows is not None:
        return ref_rows, hit_rows, ref_label, hit_label, limits

    if os.path.isfile(input_path):
        split = None
        if os.path.splitext(input_path)[1].lower() == ".json":
            try:
                split = split_json_file(input_path)
            except (ValueError, json.JSONDecodeError):
                split = None
        if split and ref_rows is None and hit_rows is None:
            ref_rows, hit_rows = split
            return ref_rows, hit_rows, os.path.basename(input_path), os.path.basename(input_path), limits
        rows = read_table(input_path) if ref_rows is None or hit_rows is None else []
        kind = guess_kind(rows)
        if ref_rows is None and kind == "refs":
            ref_rows, ref_label = rows, os.path.basename(input_path)
        elif hit_rows is None and kind == "hits":
            hit_rows, hit_label = rows, os.path.basename(input_path)
        else:
            raise ValueError(
                "%s: cannot tell reference set from hit records; pass --refs and --hits explicitly"
                % input_path)
    elif os.path.isdir(input_path):
        candidates = sorted(
            os.path.join(input_path, name) for name in os.listdir(input_path)
            if os.path.splitext(name)[1].lower() in {".csv", ".tsv", ".json", ".jsonl"}
            and os.path.isfile(os.path.join(input_path, name))
            and name.casefold() not in {"case.json", "case.yaml", "case.yml"}
            and not any(hint in name.casefold() for hint in AUX_HINTS)
        )
        if not candidates:
            raise ValueError("%s: no .csv/.tsv/.json/.jsonl files found" % input_path)
        for path in candidates:
            if os.path.splitext(path)[1].lower() == ".json":
                try:
                    split = split_json_file(path)
                except (ValueError, json.JSONDecodeError):
                    split = None
                if split and ref_rows is None and hit_rows is None:
                    ref_rows, hit_rows = split
                    ref_label = hit_label = os.path.basename(path)
                    break
        if ref_rows is None or hit_rows is None:
            guessed = {}
            for path in candidates:
                try:
                    rows = read_table(path)
                except ValueError as exc:
                    limits.append("skipped unreadable file %s: %s" % (os.path.basename(path), exc))
                    continue
                name = os.path.basename(path).casefold()
                is_ref = any(hint in name for hint in REF_HINTS)
                is_hit = any(hint in name for hint in HIT_HINTS)
                if not rows:
                    # A header-only export is a valid empty result, not a missing file.
                    if is_ref and not is_hit:
                        guessed.setdefault("refs", []).append((path, rows))
                    elif is_hit and not is_ref:
                        guessed.setdefault("hits", []).append((path, rows))
                    else:
                        limits.append("skipped empty file %s" % os.path.basename(path))
                    continue
                if is_ref and not is_hit:
                    kind = "refs"
                elif is_hit and not is_ref:
                    kind = "hits"
                else:
                    kind = guess_kind(rows)
                guessed.setdefault(kind, []).append((path, rows))
            if ref_rows is None and len(guessed.get("refs", [])) == 1:
                path, ref_rows = guessed["refs"][0]
                ref_label = os.path.basename(path)
            if hit_rows is None and len(guessed.get("hits", [])) == 1:
                path, hit_rows = guessed["hits"][0]
                hit_label = os.path.basename(path)
            if len(guessed.get("refs", [])) > 1:
                limits.append("multiple reference-like files found; using none without --refs")
            if len(guessed.get("hits", [])) > 1:
                limits.append("multiple hit-like files found; using none without --hits")
        if ref_rows is None:
            raise ValueError(
                "no reference set identified under %s; pass --refs explicitly. Files: %s"
                % (input_path, ", ".join(os.path.basename(p) for p in candidates)))
    else:
        raise ValueError("input path not found: %s" % input_path)

    if hit_rows is None:
        limits.append("no hit record file identified; coverage is reported as not computable")
    return ref_rows, hit_rows, ref_label, hit_label, limits


# ---------------------------------------------------------------- matching


def _confirmed(method, hits, score, reason, doi_conflict=False):
    return {
        "status": "hit",
        "method": method,
        "matched_record_ids": sorted({h["record_id"] or "<no-id>" for h in hits}),
        "match_score": round(score, 4) if score is not None else None,
        "match_reason": reason,
        "doi_conflict": doi_conflict,
        "candidate_record_id": "",
    }


def _uncertain(record_id, score, reason):
    return {
        "status": "uncertain",
        "method": "none",
        "matched_record_ids": [],
        "match_score": round(score, 4) if score is not None else None,
        "match_reason": reason,
        "doi_conflict": False,
        "candidate_record_id": record_id or "",
    }


def match_reference(ref, hits):
    rdoi = norm_doi(ref["doi"])
    if rdoi:
        exact = [h for h in hits if norm_doi(h["doi"]) == rdoi]
        if exact:
            return _confirmed("doi", exact, 1.0, "exact normalised DOI match")

    rtitle = norm_title(ref["title"])
    ryear = norm_year(ref["year"])
    rauth = author_surnames(ref["authors"])
    if not rtitle:
        return {
            "status": "uncertain", "method": "none", "matched_record_ids": [],
            "match_score": None, "match_reason": "reference has no usable title",
            "doi_conflict": False, "candidate_record_id": "",
        }

    confirmed = []
    best_author = 0.0
    doi_conflict = False
    uncertain = None

    for hit in hits:
        hdoi = norm_doi(hit["doi"])
        htitle = norm_title(hit["title"])
        if not htitle:
            continue
        hyear = norm_year(hit["year"])

        if htitle != rtitle:
            similarity = jaccard(title_tokens(rtitle), title_tokens(htitle))
            if similarity is not None and similarity >= NEAR_TITLE_JACCARD \
                    and ryear and hyear and ryear == hyear:
                candidate = _uncertain(
                    hit["record_id"], similarity,
                    "near title (jaccard %.3f >= %.2f) and equal year, not exact"
                    % (similarity, NEAR_TITLE_JACCARD))
                if uncertain is None or (candidate["match_score"] or 0) > (uncertain["match_score"] or 0):
                    uncertain = candidate
            continue

        if ryear and hyear and ryear != hyear:
            candidate = _uncertain(hit["record_id"], 0.0,
                                   "title matches but year differs (%s vs %s)" % (ryear, hyear))
            if uncertain is None:
                uncertain = candidate
            continue
        if not ryear or not hyear:
            candidate = _uncertain(hit["record_id"], None,
                                   "title matches but year is missing on one side")
            if uncertain is None:
                uncertain = candidate
            continue

        author_score = jaccard(rauth, author_surnames(hit["authors"]))
        if author_score is None:
            candidate = _uncertain(hit["record_id"], None,
                                   "title and year match but author metadata is missing")
            if uncertain is None:
                uncertain = candidate
            continue
        if author_score < AUTHOR_JACCARD:
            candidate = _uncertain(
                hit["record_id"], author_score,
                "title and year match but author jaccard %.3f < %.2f"
                % (author_score, AUTHOR_JACCARD))
            if uncertain is None or (candidate["match_score"] or 0) > (uncertain["match_score"] or 0):
                uncertain = candidate
            continue

        confirmed.append(hit)
        best_author = max(best_author, author_score)
        if rdoi and hdoi and rdoi != hdoi:
            doi_conflict = True

    if confirmed:
        reason = "normalised title + equal year + author jaccard %.3f >= %.2f" % (
            best_author, AUTHOR_JACCARD)
        if doi_conflict:
            reason += "; DOI differs (possible version or metadata conflict)"
        return _confirmed("title_year_author", confirmed, best_author, reason, doi_conflict)

    if uncertain is not None:
        return uncertain

    return {
        "status": "miss", "method": "none", "matched_record_ids": [],
        "match_score": None,
        "match_reason": "no DOI match and no title+year+author match in supplied records",
        "doi_conflict": False, "candidate_record_id": "",
    }


# ---------------------------------------------------------------- optional inputs


def load_classifications(path):
    if not path:
        return {}
    if not os.path.exists(path):
        raise ValueError("classification file not found: %s" % path)
    out = {}
    for row in read_table(path):
        ref_id = pick(row, REF_ALIASES["ref_id"])
        category = pick(row, ["miss_category", "category", "遗漏类别", "漏检类别"])
        if ref_id and category:
            out[ref_id] = {
                "miss_category": category,
                "evidence": pick(row, ["evidence", "evidence_ref", "证据", "依据"]),
                "note": pick(row, ["note", "notes", "备注"]),
            }
    return out


def parse_bool(value):
    text = sval(value).casefold()
    if text in {"1", "true", "yes", "y", "executed", "done", "completed"}:
        return True
    if text in {"0", "false", "no", "n", "", "not_executed", "proposed", "planned", "todo"}:
        return False
    return None


def split_labels(value):
    text = sval(value)
    if not text:
        return []
    if isinstance(value, list):
        return [sval(v) for v in value if sval(v)]
    return [part.strip() for part in re.split(r"[;,|]", text) if part.strip()]


def load_supplements(path):
    if not path:
        return []
    if not os.path.exists(path):
        raise ValueError("supplement file not found: %s" % path)
    rounds = []
    for row in read_table(path):
        category = pick(row, ["miss_category", "category", "遗漏类别", "漏检类别"])
        new_hits_raw = row.get("new_hits", "")
        labels = split_labels(new_hits_raw)
        count = None
        if re.fullmatch(r"\d+", sval(new_hits_raw)):
            count = int(sval(new_hits_raw))
        yield_value = pick(row, ["yield", "yield_count", "新增命中数"])
        if yield_value and re.fullmatch(r"\d+", sval(yield_value)):
            count = int(sval(yield_value))
        elif count is None and labels:
            count = len(labels)
        rounds.append({
            "miss_category": category,
            "proposed_query": pick(row, ["proposed", "proposed_query", "query", "检索式"]),
            "executed": parse_bool(pick(row, ["executed", "status", "已执行"])),
            "new_hits": labels if labels else ([] if count is None else [str(count)]),
            "yield": count,
            "stop_reason": pick(row, ["stop_reason", "stop", "停止理由"]),
            "recovers_ref_ids": split_labels(
                pick(row, ["recovers_ref_ids", "resolved_ref_ids", "补回参考编号"])),
            "screened": pick(row, ["screened", "records_screened", "筛选记录数"]),
            "source": pick(row, ["source", "来源"]),
            "note": pick(row, ["note", "notes", "备注"]),
        })
    rounds.sort(key=lambda r: (r["miss_category"], r["proposed_query"]))
    return rounds


# ---------------------------------------------------------------- contract


CONTRACT_ALIASES = {
    "reference_set": ["reference_set", "references", "refs", "reference_list", "known_set", "gold_set"],
    "coverage": ["coverage", "coverage_metrics", "metrics", "coverage_analysis"],
    "coverage_rate": ["coverage_rate", "coverage_percent", "coverage_ratio", "覆盖率"],
    "matches": ["matches", "hit_matrix", "match_matrix", "per_reference", "comparison", "match_table"],
    "misses": ["misses", "missed", "omissions", "miss_list", "omission_list"],
    "miss_categories": ["miss_categories", "omission_categories", "miss_grouping", "miss_reasons"],
    "supplemental_search": ["supplemental_search", "supplemental", "supplementary", "supplement",
                            "follow_up", "next_queries", "supplemental_queries"],
    "report": ["report", "report_path", "readable_report", "report_file"],
    "evidence": ["evidence", "evidence_map", "sources", "provenance"],
    "uncertainty": ["uncertainty", "uncertainties", "open_questions"],
    "limits": ["limits", "limitations", "constraints"],
    "changes": ["changes", "change_log"],
    "summary": ["summary", "conclusion", "findings", "headline"],
    "status": ["status", "run_status"],
    "case_id": ["case_id", "caseid"],
}


def contract_fields(case):
    if not isinstance(case, dict):
        return []
    contract = case.get("output_contract", case.get("outputContract"))
    if isinstance(contract, list):
        return [sval(item) for item in contract if sval(item)]
    if isinstance(contract, dict):
        return [sval(key) for key in contract if sval(key)]
    if isinstance(contract, str):
        return [part.strip() for part in re.split(r"[,;\n]", contract) if part.strip()]
    return []


def case_id_of(case):
    if not isinstance(case, dict):
        return ""
    for key in ("case_id", "caseId", "id"):
        if sval(case.get(key)):
            return sval(case.get(key))
    return ""


def map_contract(fields, canonical):
    mapped = {}
    used = set()
    unresolved = []
    for field in fields:
        nkey = norm_key(field)
        target = None
        for name, aliases in CONTRACT_ALIASES.items():
            if nkey == norm_key(name) or nkey in {norm_key(a) for a in aliases}:
                target = name
                break
        if target and target in canonical:
            mapped[field] = canonical[target]
            used.add(target)
        elif nkey in canonical:
            mapped[field] = canonical[nkey]
            used.add(nkey)
        else:
            mapped[field] = None
            unresolved.append(field)
    return mapped, sorted(set(canonical) - used), unresolved


# ---------------------------------------------------------------- outputs


def write_csv(path, fieldnames, rows):
    with open(path, "w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def rate(numerator, denominator):
    if not denominator:
        return None
    return round(numerator / denominator, 4)


def checked_files(input_path):
    """List files inspected under the input path for blocked reporting."""
    if not input_path:
        return []
    if os.path.isfile(input_path):
        return [os.path.basename(input_path)]
    if not os.path.isdir(input_path):
        return []
    names = []
    for dirpath, dirnames, filenames in os.walk(input_path):
        dirnames.sort()
        for name in sorted(filenames):
            names.append(os.path.relpath(os.path.join(dirpath, name), input_path))
    return names


def write_blocked(out_dir, input_path, case, case_path, reason):
    """Write a status=blocked result.json (and report.md) before exiting non-zero."""
    files = checked_files(input_path)
    limits = ["blocked: " + reason]
    uncertainty = ["输入中未识别出参考集，未计算任何覆盖率；不得用推测数据补齐。"]
    result = {
        "case_id": case_id_of(case) if case else "",
        "status": "blocked",
        "reason": reason,
        "checked_files": files,
        "reference_set": None,
        "coverage": None,
        "coverage_rate": None,
        "matches": [],
        "misses": [],
        "miss_categories": [],
        "supplemental_search": None,
        "report": "report.md",
        "uncertainty": uncertainty,
        "limits": limits,
        "changes": [],
        "summary": "blocked: " + reason,
        "artifacts": ["result.json", "report.md"],
        "rules_version": RULES_VERSION,
    }
    fields = contract_fields(case) if case else []
    if fields:
        mapped, unused, unresolved = map_contract(fields, {
            "case_id": result["case_id"],
            "status": "blocked",
            "reference_set": None,
            "coverage": None,
            "coverage_rate": None,
            "matches": [],
            "misses": [],
            "miss_categories": [],
            "supplemental_search": None,
            "report": "report.md",
            "evidence": {
                "inputs": {"input": input_path, "checked_files": files},
                "matching_rule": {
                    "primary": "exact normalised DOI",
                    "fallback": "normalised title equality AND equal year AND "
                                "author-surname Jaccard >= %.2f" % AUTHOR_JACCARD,
                },
            },
            "uncertainty": uncertainty,
            "limits": limits,
            "changes": [],
            "summary": result["summary"],
        })
        result.update(mapped)
        result["contract_mapping"] = {
            "source": os.path.basename(case_path) if case_path else "",
            "requested_fields": fields,
            "unresolved_fields": unresolved,
            "unused_core_fields": unused,
            "note": "blocked run: no evidence-backed value; do not invent them",
        }

    os.makedirs(out_dir, exist_ok=True)
    with open(os.path.join(out_dir, "result.json"), "w", encoding="utf-8") as handle:
        json.dump(result, handle, ensure_ascii=False, indent=1)
    with open(os.path.join(out_dir, "report.md"), "w", encoding="utf-8") as handle:
        handle.write("# 检索覆盖率与遗漏分析报告\n\n")
        handle.write("- 状态：`blocked`\n")
        handle.write("- 原因：%s\n" % reason)
        handle.write("- 已检查文件：%s\n" % (
            ", ".join("`%s`" % name for name in files) or "(无)"))
        handle.write("\n未识别出参考集，未计算覆盖率。补齐参考集或使用 `--refs` 显式指定后重跑。\n")
    return result


def render_report(core):
    lines = []
    lines.append("# 检索覆盖率与遗漏分析报告")
    lines.append("")
    lines.append("> 本报告由 `scripts/coverage_audit.py`（规则版本 %s）基于输入文件生成。" % RULES_VERSION)
    lines.append("> 覆盖率只相对于题面给定的参考集，不代表数据库全局召回。")
    lines.append("")
    lines.append("## 1. 输入与口径")
    lines.append("")
    lines.append("- 参考集：`%s`，%d 条" % (core["inputs"]["reference_file"] or "(未识别)",
                                        core["reference_set"]["total"]))
    lines.append("- 命中记录：`%s`，%d 条" % (core["inputs"]["hit_file"] or "(未识别)",
                                        core["inputs"]["hit_count"]))
    lines.append("- 状态：`%s`" % core["status"])
    lines.append("- 匹配规则：先按规范化 DOI 精确匹配；否则要求规范化标题完全相同、年份相同、"
                 "作者姓氏集合 Jaccard ≥ %.2f。弱于该规则的一律记 `uncertain`，不计入命中。"
                 % AUTHOR_JACCARD)
    lines.append("")
    lines.append("## 2. 覆盖率")
    lines.append("")
    cov = core["coverage"]
    lines.append("| 指标 | 数值 | 公式 |")
    lines.append("|-|-|-|")
    lines.append("| 参考集总数 | %d | — |" % core["reference_set"]["total"])
    lines.append("| 不可用记录（不计入分母） | %d | 见下表 |" % cov["unavailable"])
    lines.append("| 分母 | %d | 总数 − 不可用 |" % cov["denominator"])
    lines.append("| 命中 | %d | DOI 或标题+年份+作者匹配 |" % cov["hits"])
    lines.append("| 遗漏 | %d | 分母 − 命中 − 不确定 |" % cov["misses"])
    lines.append("| 不确定 | %d | 证据不足以判定 |" % cov["uncertain"])
    lines.append("| 覆盖率 | %s | 命中 / 分母 |" % _pct(cov["coverage_rate"]))
    lines.append("| 遗漏率 | %s | 遗漏 / 分母 |" % _pct(cov["miss_rate"]))
    lines.append("| 不确定率 | %s | 不确定 / 分母 |" % _pct(cov["uncertain_rate"]))
    lines.append("| 含全部参考集的覆盖率 | %s | 命中 / 参考集总数 |" % _pct(cov["coverage_over_all"]))
    lines.append("")
    if core["reference_set"]["unavailable_records"]:
        lines.append("### 不可用记录（已单独列出，未静默删除）")
        lines.append("")
        lines.append("| ref_id | 标题 | 原因 |")
        lines.append("|-|-|-|")
        for item in core["reference_set"]["unavailable_records"]:
            lines.append("| %s | %s | %s |" % (_cell(item["ref_id"]), _cell(item["title"]),
                                               _cell(item["reason"])))
        lines.append("")
    if core["reference_set"]["duplicate_groups"]:
        lines.append("### 参考集重复候选（未自动合并）")
        lines.append("")
        for group in core["reference_set"]["duplicate_groups"]:
            lines.append("- `%s`：%s" % (group["key"], ", ".join(group["ref_ids"])))
        lines.append("")
    lines.append("## 3. 逐条命中状态")
    lines.append("")
    lines.append("| ref_id | 标题 | 年份 | 状态 | 依据 | 命中记录 | 漏检类别 |")
    lines.append("|-|-|-|-|-|-|-|")
    for item in core["matches"]:
        lines.append("| %s | %s | %s | %s | %s | %s | %s |" % (
            _cell(item["ref_id"]), _cell(item["title"]), _cell(item["year"]),
            item["status"], _cell(item["match_reason"]),
            _cell(", ".join(item["matched_record_ids"] or [])),
            _cell(item["miss_category"] if item["status"] == "miss" else "")))
    lines.append("")
    lines.append("## 4. 遗漏分组")
    lines.append("")
    if core["miss_categories"]:
        lines.append("| 类别 | 数量 | 来源 | ref_id |")
        lines.append("|-|-|-|-|")
        for group in core["miss_categories"]:
            lines.append("| %s | %d | %s | %s |" % (
                _cell(group["category"]), group["count"], group["source"],
                _cell(", ".join(group["ref_ids"]))))
        lines.append("")
        lines.append("未提供类别的遗漏统一记为 `unlabeled`；本报告不推断原因。")
    else:
        lines.append("无遗漏记录。")
    lines.append("")
    lines.append("## 5. 补检记录与边际收益")
    lines.append("")
    lines.append("> `executed=false` 的行只是模板，表示补检尚未执行；不得在结论中写成已完成。")
    lines.append("")
    lines.append("| 类别 | 拟定查询式 | 已执行 | 新增命中 | 产出 | 停止理由 |")
    lines.append("|-|-|-|-|-|-|")
    for item in core["supplemental_search"]["rounds"]:
        lines.append("| %s | %s | %s | %s | %s | %s |" % (
            _cell(item["miss_category"]), _cell(item["proposed_query"]),
            "yes" if item["executed"] else "no", _cell(item["new_hits"]),
            "" if item["yield"] is None else item["yield"], _cell(item["stop_reason"])))
    lines.append("")
    lines.append("边际收益：%s" % core["supplemental_search"]["marginal_benefit"])
    residual = core["supplemental_search"]["residual_misses"]
    if residual is None:
        lines.append("残余遗漏：无法计算（%s）" % core["supplemental_search"]["residual_note"])
    else:
        lines.append("残余遗漏：%d 条 %s" % (len(residual), ", ".join(residual) if residual else ""))
    lines.append("")
    lines.append("## 6. 不确定性与限制")
    lines.append("")
    for item in core["uncertainty"]:
        lines.append("- %s" % item)
    for item in core["limits"]:
        lines.append("- %s" % item)
    if not core["uncertainty"] and not core["limits"]:
        lines.append("- 未发现额外限制。")
    lines.append("")
    lines.append("## 7. 复跑")
    lines.append("")
    lines.append("```bash")
    lines.append("python scripts/coverage_audit.py --input /input --case /input/case.json --out /app/output")
    lines.append("```")
    lines.append("")
    return "\n".join(lines)


def _cell(value):
    text = sval(value).replace("|", "\\|").replace("\n", " ")
    return text if text else "—"


def _pct(value):
    return "—" if value is None else "%.2f%%" % (value * 100)


def embedded_rows(case, keys):
    """Return a list embedded in case.json (directly or under a nested list)."""
    if not isinstance(case, dict):
        return None
    for key in keys:
        value = case.get(key)
        if isinstance(value, list):
            return value
        if isinstance(value, dict):
            for sub in ("records", "items", "rows", "references", "hits", "candidates"):
                if isinstance(value.get(sub), list):
                    return value[sub]
    return None


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--input", required=True, help="input directory or a table file")
    parser.add_argument("--out", required=True, help="output directory")
    parser.add_argument("--refs", help="explicit reference set CSV/JSON")
    parser.add_argument("--hits", help="explicit hit record CSV/JSON")
    parser.add_argument("--classify", help="optional ref_id -> miss_category mapping with evidence")
    parser.add_argument("--supplements", help="optional executed/proposed supplemental search records")
    parser.add_argument("--case", default="", help="case.json providing case_id and output_contract")
    args = parser.parse_args(argv)

    case = None
    case_path = args.case
    if not case_path:
        if os.path.isdir(args.input):
            default_case = os.path.join(args.input, "case.json")
        else:
            default_case = os.path.join(os.path.dirname(os.path.abspath(args.input)), "case.json")
        if os.path.isfile(default_case):
            case_path = default_case
    limits = []
    if case_path and os.path.exists(case_path):
        try:
            with open(case_path, encoding="utf-8-sig") as handle:
                case = json.load(handle)
        except (OSError, json.JSONDecodeError) as exc:
            limits.append("case.json unreadable: %s" % exc)

    try:
        refs_embedded = None if args.refs else embedded_rows(
            case, ("reference_set", "references", "refs", "gold_set", "known_set"))
        hits_embedded = None if args.hits else embedded_rows(
            case, ("hits", "records", "candidates", "results", "search_results", "hit_records"))
        if refs_embedded is not None and hits_embedded is not None:
            ref_rows = [_normalise_row(item) for item in refs_embedded if isinstance(item, dict)]
            hit_rows = [_normalise_row(item) for item in hits_embedded if isinstance(item, dict)]
            ref_label = hit_label = os.path.basename(case_path)
        else:
            ref_rows, hit_rows, ref_label, hit_label, extra_limits = discover(
                args.input, args.refs, args.hits)
            limits.extend(extra_limits)
        classifications = load_classifications(args.classify)
        supplements = load_supplements(args.supplements)
    except ValueError as exc:
        write_blocked(args.out, args.input, case, case_path, str(exc))
        print("error: %s" % exc, file=sys.stderr)
        return 1

    refs = [normalise_ref(row) for row in ref_rows]
    hits = [normalise_hit(row) for row in hit_rows] if hit_rows is not None else []

    # Fill missing identifiers deterministically.
    for index, ref in enumerate(refs, 1):
        if not ref["ref_id"]:
            ref["ref_id"] = "REF-%03d" % index
    for index, hit in enumerate(hits, 1):
        if not hit["record_id"]:
            hit["record_id"] = "HIT-%03d" % index

    # Duplicate reference candidates (flagged, never silently removed).
    duplicate_map = {}
    for ref in refs:
        key = "doi:" + norm_doi(ref["doi"]) if norm_doi(ref["doi"]) else \
            "title:" + norm_title(ref["title"]) + "|" + norm_year(ref["year"])
        if key in ("doi:", "title:|"):
            continue
        duplicate_map.setdefault(key, []).append(ref["ref_id"])
    duplicate_groups = [
        {"key": key, "ref_ids": sorted(ids)} for key, ids in sorted(duplicate_map.items())
        if len(ids) > 1
    ]

    included = [ref for ref in refs if not ref["unavailable"]]
    unavailable_records = [
        {"ref_id": ref["ref_id"], "title": ref["title"], "year": ref["year"],
         "doi": ref["doi"], "reason": ref["unavailable_reason"] or "marked unavailable"}
        for ref in refs if ref["unavailable"]
    ]

    matches = []
    for ref in sorted(included, key=lambda r: r["ref_id"]):
        if hit_rows is None:
            outcome = {
                "status": "uncertain", "method": "none", "matched_record_ids": [],
                "match_score": None,
                "match_reason": "no hit record file supplied; status cannot be decided",
                "doi_conflict": False, "candidate_record_id": "",
            }
        else:
            outcome = match_reference(ref, hits)
        category = ""
        category_source = ""
        if outcome["status"] != "miss":
            category, category_source = "", ""
        elif ref["miss_category"]:
            category, category_source = ref["miss_category"], "reference_set"
        elif ref["ref_id"] in classifications:
            category = classifications[ref["ref_id"]]["miss_category"]
            category_source = "classify_input"
        else:
            category, category_source = "unlabeled", "unlabeled"
        matches.append({
            "ref_id": ref["ref_id"],
            "doi": ref["doi"],
            "title": ref["title"],
            "authors": ref["authors"],
            "year": ref["year"],
            "include_reason": ref["include_reason"],
            "unavailable": False,
            "status": outcome["status"],
            "match_method": outcome["method"],
            "matched_record_ids": outcome["matched_record_ids"],
            "match_score": outcome["match_score"],
            "match_reason": outcome["match_reason"],
            "doi_conflict": outcome["doi_conflict"],
            "candidate_record_id": outcome["candidate_record_id"],
            "miss_category": category,
            "category_source": category_source,
            "note": ref["notes"],
        })

    hit_count = sum(1 for item in matches if item["status"] == "hit")
    miss_items = [item for item in matches if item["status"] == "miss"]
    uncertain_items = [item for item in matches if item["status"] == "uncertain"]
    denominator = len(included)

    computable = hit_rows is not None and denominator > 0
    coverage = {
        "denominator": denominator,
        "hits": hit_count,
        "misses": len(miss_items),
        "uncertain": len(uncertain_items),
        "unavailable": len(unavailable_records),
        "coverage_rate": rate(hit_count, denominator) if computable else None,
        "miss_rate": rate(len(miss_items), denominator) if computable else None,
        "uncertain_rate": rate(len(uncertain_items), denominator) if computable else None,
        "coverage_over_all": rate(hit_count, len(refs)) if computable else None,
        "computable": computable,
        "formula": {
            "denominator": "reference_total - unavailable",
            "coverage_rate": "hits / denominator",
            "miss_rate": "misses / denominator",
            "uncertain_rate": "uncertain / denominator",
        },
        "uncertain_not_counted_as_hit": True,
    }

    groups = {}
    for item in miss_items:
        category = item["miss_category"] or "unlabeled"
        bucket = groups.setdefault(category, {"category": category, "count": 0,
                                              "ref_ids": [], "statuses": set(),
                                              "sources": set()})
        bucket["count"] += 1
        bucket["ref_ids"].append(item["ref_id"])
        bucket["statuses"].add(item["status"])
        bucket["sources"].add(item["category_source"])
    miss_categories = []
    for category in sorted(groups):
        bucket = groups[category]
        miss_categories.append({
            "category": category,
            "count": bucket["count"],
            "ref_ids": sorted(bucket["ref_ids"]),
            "statuses": sorted(bucket["statuses"]),
            "source": ", ".join(sorted(bucket["sources"])),
        })

    # Supplemental search: executed records pass through, the rest are templates.
    by_category = {}
    for item in supplements:
        by_category.setdefault(item["miss_category"], []).append(item)
    rounds = []
    for group in groups:
        if group in by_category:
            for item in by_category[group]:
                rounds.append(dict(item, template=False))
        else:
            rounds.append({
                "miss_category": group,
                "proposed_query": "",
                "executed": False,
                "new_hits": [],
                "yield": None,
                "stop_reason": "",
                "recovers_ref_ids": [],
                "screened": "",
                "source": "",
                "note": "",
                "template": True,
            })
    for category in sorted(by_category):
        if category not in groups:
            for item in by_category[category]:
                rounds.append(dict(item, template=False))
    rounds.sort(key=lambda r: (r["miss_category"], r["proposed_query"], r["executed"]))

    executed_rounds = [r for r in rounds if r["executed"]]
    new_hit_total = sum((r["yield"] or 0) for r in executed_rounds)
    ref_id_set = {item["ref_id"] for item in matches}
    recovered = set()
    mapping_incomplete = False
    for item in executed_rounds:
        if item["recovers_ref_ids"]:
            recovered.update(item["recovers_ref_ids"])
        elif item["new_hits"]:
            labels = [label for label in item["new_hits"] if not re.fullmatch(r"\d+", label)]
            if not labels or not set(labels) <= ref_id_set:
                mapping_incomplete = True
            else:
                recovered.update(labels)

    residual = None
    residual_note = ""
    if not executed_rounds:
        residual_note = "没有提供已执行的补检记录，无法计算残余遗漏"
    elif mapping_incomplete:
        residual_note = "补检新增命中的记录编号未映射回 ref_id，不能据此宣称遗漏下降"
    else:
        residual = sorted(item["ref_id"] for item in miss_items
                          if item["ref_id"] not in recovered)
        residual_note = "仅按已执行补检记录中显式补回的 ref_id 计算"

    if executed_rounds:
        marginal = ("已执行 %d 轮补检，新增命中合计 %s 条；新增命中需与参考集对齐后才能作为覆盖率提升证据。"
                    % (len(executed_rounds), new_hit_total))
        if recovered:
            marginal += "其中 %d 条已显式映射回参考集 ref_id。" % len(recovered)
    else:
        marginal = "未执行补检：仅给出拟定查询模板，不得声称遗漏已下降。"

    supplemental = {
        "rounds": rounds,
        "executed_rounds": len(executed_rounds),
        "new_hits_total": new_hit_total if executed_rounds else None,
        "marginal_benefit": marginal,
        "residual_misses": residual,
        "residual_note": residual_note,
        "template_only": len(executed_rounds) == 0,
    }

    uncertainty = []
    if uncertain_items:
        uncertainty.append(
            "%d 条参考记录只能判定为 uncertain，未计入覆盖率分子：%s"
            % (len(uncertain_items), ", ".join(item["ref_id"] for item in uncertain_items)))
    for group in duplicate_groups:
        uncertainty.append("参考集存在疑似重复：%s（未自动合并）" % ", ".join(group["ref_ids"]))
    doi_conflicts = [item["ref_id"] for item in matches if item["doi_conflict"]]
    if doi_conflicts:
        uncertainty.append("标题匹配但 DOI 不一致：%s（可能是版本或元数据冲突）"
                           % ", ".join(doi_conflicts))
    if hit_rows is None:
        uncertainty.append("未识别到命中记录文件，覆盖率不可由输入复算。")
    if not refs:
        uncertainty.append("参考集为空，未计算覆盖率。")

    if not refs:
        status = "blocked"
    elif hit_rows is None or denominator == 0:
        status = "partial"
    else:
        status = "ok"
    if limits and status == "ok":
        status = "partial"

    core = {
        "rules_version": RULES_VERSION,
        "status": status,
        "inputs": {
            "input": args.input,
            "reference_file": ref_label,
            "hit_file": hit_label,
            "reference_rows": len(ref_rows) if ref_rows is not None else 0,
            "hit_count": len(hits),
            "classify_file": os.path.basename(args.classify) if args.classify else "",
            "supplement_file": os.path.basename(args.supplements) if args.supplements else "",
        },
        "matching_rule": {
            "primary": "exact normalised DOI",
            "fallback": "normalised title equality AND equal year AND author-surname Jaccard >= %.2f"
                        % AUTHOR_JACCARD,
            "uncertain_never_counted_as_hit": True,
            "near_title_jaccard": NEAR_TITLE_JACCARD,
        },
        "reference_set": {
            "total": len(refs),
            "included": denominator,
            "unavailable": len(unavailable_records),
            "unavailable_records": unavailable_records,
            "duplicate_groups": duplicate_groups,
            "ref_ids": sorted(ref["ref_id"] for ref in refs),
        },
        "coverage": coverage,
        "matches": matches,
        "misses": miss_items,
        "uncertain_records": uncertain_items,
        "miss_categories": miss_categories,
        "supplemental_search": supplemental,
        "uncertainty": uncertainty,
        "limits": limits,
        "artifacts": ["coverage.csv", "misses.csv", "report.md", "result.json", "audit.json"],
        "changes": [],
    }
    core["summary"] = (
        "参考集 %d 条（分母 %d，不可用 %d）；命中 %d，遗漏 %d，不确定 %d；覆盖率 %s。"
        % (len(refs), denominator, len(unavailable_records), hit_count,
           len(miss_items), len(uncertain_items), _pct(coverage["coverage_rate"]))
    )

    os.makedirs(args.out, exist_ok=True)
    coverage_fields = ["ref_id", "doi", "title", "authors", "year", "unavailable", "status",
                       "match_method", "matched_record_ids", "match_score", "match_reason",
                       "doi_conflict", "candidate_record_id", "miss_category", "category_source",
                       "include_reason", "note"]
    coverage_rows = []
    for item in matches:
        row = dict(item)
        row["matched_record_ids"] = "; ".join(row["matched_record_ids"])
        coverage_rows.append(row)
    write_csv(os.path.join(args.out, "coverage.csv"), coverage_fields, coverage_rows)

    miss_fields = ["ref_id", "doi", "title", "authors", "year", "status", "miss_category",
                   "category_source", "match_reason", "candidate_record_id", "include_reason", "note"]
    write_csv(os.path.join(args.out, "misses.csv"), miss_fields, miss_items)

    with open(os.path.join(args.out, "audit.json"), "w", encoding="utf-8") as handle:
        json.dump(core, handle, ensure_ascii=False, indent=1)

    with open(os.path.join(args.out, "report.md"), "w", encoding="utf-8") as handle:
        handle.write(render_report(core))

    # result.json: canonical keys plus dynamic output_contract mapping.
    result = {key: core[key] for key in (
        "status", "reference_set", "coverage", "matches", "misses", "miss_categories",
        "supplemental_search", "uncertainty", "limits", "changes", "summary")}
    result["case_id"] = case_id_of(case) if case else ""
    result["coverage_rate"] = core["coverage"]["coverage_rate"]
    result["artifacts"] = core["artifacts"]
    result["rules_version"] = RULES_VERSION

    fields = contract_fields(case) if case else []
    if fields:
        mapped, unused, unresolved = map_contract(fields, {
            "case_id": result["case_id"],
            "status": core["status"],
            "reference_set": core["reference_set"],
            "coverage": core["coverage"],
            "coverage_rate": core["coverage"]["coverage_rate"],
            "matches": core["matches"],
            "misses": core["misses"],
            "miss_categories": core["miss_categories"],
            "supplemental_search": core["supplemental_search"],
            "report": "report.md",
            "evidence": {
                "inputs": core["inputs"],
                "matching_rule": core["matching_rule"],
                "coverage_csv": "coverage.csv",
                "misses_csv": "misses.csv",
            },
            "uncertainty": core["uncertainty"],
            "limits": core["limits"],
            "changes": core["changes"],
            "summary": core["summary"],
        })
        result.update(mapped)
        result["contract_mapping"] = {
            "source": os.path.basename(case_path) if case_path else "",
            "requested_fields": fields,
            "unresolved_fields": unresolved,
            "unused_core_fields": unused,
            "note": "unresolved fields have no evidence-backed value in this run; do not invent them",
        }

    with open(os.path.join(args.out, "result.json"), "w", encoding="utf-8") as handle:
        json.dump(result, handle, ensure_ascii=False, indent=1)

    print("references=%d included=%d hits=%d misses=%d uncertain=%d coverage=%s status=%s -> %s"
          % (len(refs), denominator, hit_count, len(miss_items), len(uncertain_items),
             coverage["coverage_rate"], status, args.out))
    for limit in limits:
        print("warning: %s" % limit, file=sys.stderr)
    return 0 if status == "ok" else (2 if status == "partial" else 1)


if __name__ == "__main__":
    sys.exit(main())
