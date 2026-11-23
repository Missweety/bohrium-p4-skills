#!/usr/bin/env python3
"""Normalize patent publication records and cluster observed patent families.

The helper only normalizes and cross-checks supplied records. It does not
query official registers, browse the web, or decide legal effect.

Usage:
  python3 scripts/patent_normalize.py --input PATH --out DIR \
      [--as-of YYYY-MM-DD] [--max-status-age-days 180]

  PATH is a CSV/TSV/JSON/JSONL file, or a directory scanned in sorted order.
  DIR receives normalized.csv, families.json and issues.csv.

Expected fields (aliases accepted): number, jurisdiction, kind, application_no,
priority, family_id, title, assignee, status, status_date, source_file,
locator, legal_scope.

Exit codes:
  0 completed with no issues
  2 completed with issues (empty input included)
  1 unusable input: bad arguments, path missing, unreadable or unparsable input
"""
import argparse
import csv
import json
import os
import re
import sys
import unicodedata
from datetime import date

SCHEMA_VERSION = "1.0"

KNOWN_JURISDICTIONS = {
    "US", "EP", "WO", "DE", "FR", "GB", "JP", "CN", "KR", "CA", "AU", "IN",
    "BR", "MX", "ES", "IT", "NL", "SE", "DK", "FI", "NO", "PL", "CZ", "AT",
    "CH", "BE", "RU", "UA", "TR", "IL", "SG", "MY", "TH", "VN", "ID", "PH",
    "NZ", "ZA", "EG", "SA", "AE", "AR", "CL", "CO", "PE", "PT", "GR", "HU",
    "RO", "BG", "HR", "SI", "SK", "LT", "LV", "EE", "IS", "IE", "TW", "HK",
    "MO", "CU", "KZ", "MA", "TN", "DZ", "KE", "NG", "GH", "EA", "OA", "AP",
    "GC", "BX",
}
OFFICE_ALIASES = {
    "USPTO": "US", "EPO": "EP", "WIPO": "WO", "JPO": "JP", "CNIPA": "CN",
    "SIPO": "CN", "KIPO": "KR", "DPMA": "DE", "UKIPO": "GB", "INPI": "FR",
    "IPAU": "AU", "CIPO": "CA", "IPOS": "SG", "IPI": "CH", "PRV": "SE",
}
KIND_RE = re.compile(r"^[A-Z]\d{0,2}$")

STATUS_RULES = [
    ("expired", ["expired", "lapsed", "ceased", "失效", "届满", "终止"]),
    ("inactive", ["abandoned", "withdrawn", "revoked", "invalidated",
                  "rejected", "refused", "撤回", "放弃", "驳回", "撤销", "无效"]),
    ("pending", ["pending", "under examination", "examination", "filed",
                 "application", "published", "申请中", "审查中", "审中", "待审", "公开"]),
    ("active", ["active", "granted", "issued", "registered", "in force",
                "valid", "maintained", "授权", "有效", "维持"]),
]
# Checked before any positive substring: negations are ambiguous, not active.
NEGATION_TERMS = ["no longer", "not granted", "not yet granted", "never granted",
                  "not in force", "not active", "not valid", "not enforceable",
                  "未授权", "未生效", "不再有效", "尚未授权", "非有效"]
OFFICIAL_MARKERS = ["uspto", "epo.", "epo_", "/epo", "epo.pdf", "epo.xml",
                    "wipo", "patentscope", "espacenet", "jpo", "cnipa",
                    "kipo", "dpma", "inpi", "ukipo", "ipos", "ipau", "cipo",
                    "official", "register", "gazette", "facsimile"]
SECONDARY_MARKERS = ["google patents", "google-patents", "googlepatents",
                     "freepatentsonline", "justia", "patentguru", "lens.org",
                     "baidu", "zhihu", "sohu", "blog", "medium", "wikidata",
                     "wikipedia", "news", "aggregator", "third-party",
                     "thirdparty"]

FIELD_ALIASES = {
    "number": {"number", "publicationnumber", "pubno", "pubnumber",
               "publication", "documentnumber", "docnumber", "numberoriginal"},
    "jurisdiction": {"jurisdiction", "office", "country", "cc",
                     "jurisdictioncode", "authority"},
    "kind": {"kind", "kindcode", "documentkind"},
    "application_no": {"applicationno", "applicationnumber", "appno",
                       "appnumber", "application"},
    "priority": {"priority", "prioritynumbers", "priorities",
                 "prioritynumber", "priorityno"},
    "family_id": {"familyid", "family", "docdbfamilyid", "inpadocfamilyid",
                  "simplefamily", "familykey"},
    "title": {"title", "inventiontitle", "documenttitle"},
    "assignee": {"assignee", "assignees", "applicant", "applicants", "owner"},
    "status": {"status", "legalstatus", "statusdescription"},
    "status_date": {"statusdate", "legalstatusdate", "statusdatevalue"},
    "source_file": {"sourcefile", "source", "file", "path", "filename"},
    "locator": {"locator", "loc", "position", "location", "page"},
    "legal_scope": {"legalscope", "scope", "license", "licence",
                    "displayrights", "accessscope"},
}
ALL_ALIAS_KEYS = set().union(*FIELD_ALIASES.values())
SKIP_FILENAMES = {
    "case.json", "task.md", "resources.yaml", "environment.yaml",
    # Tool/agent artifacts must never be re-read as source records.
    "matrix.json", "versions.csv", "issues.csv", "result.json", "report.md",
    "translation-log.csv", "claims.csv", "families.json", "normalized.csv",
    "quote-check.json", "source-index.json",
}
RECORD_EXTS = {".csv", ".tsv", ".json", ".jsonl"}
SEVERITY_RANK = {"error": 0, "warning": 1, "info": 2}


class InputError(Exception):
    """Input can not be used at all."""


def canon_key(text):
    return re.sub(r"[^a-z0-9\u3400-\u9fff]", "", str(text or "").lower())


def pick(raw, field, default=""):
    wanted = FIELD_ALIASES[field]
    for key, value in raw.items():
        if canon_key(key) in wanted:
            if isinstance(value, (list, tuple)):
                joined = "; ".join(str(v).strip() for v in value if str(v).strip())
                return joined if joined else default
            if value is None:
                return default
            text = str(value).strip()
            return text if text else default
    return default


def compact(text):
    return re.sub(r"[^0-9A-Z]", "", unicodedata.normalize("NFKC", str(text or "")).upper())


def office_code(raw):
    text = unicodedata.normalize("NFKC", str(raw or "")).strip().upper()
    if not text:
        return ""
    if text in OFFICE_ALIASES:
        return OFFICE_ALIASES[text]
    letters = re.sub(r"[^A-Z]", "", text)
    if 2 <= len(letters) <= 3:
        return letters
    return ""


def parse_publication(raw, jurisdiction_raw, kind_raw):
    text = str(raw or "").strip()
    issues = []
    c = compact(text)
    explicit = office_code(jurisdiction_raw)
    explicit_kind = compact(kind_raw)

    if not c:
        return {"input": text, "cc": explicit, "core": "", "kind": "",
                "normalized": "", "valid": False,
                "issues": [("number_missing", "error", "record has no number")]}

    cc, rest = "", ""
    if explicit:
        if c.startswith(explicit) and re.match(r"^\d", c[len(explicit):]):
            cc, rest = explicit, c[len(explicit):]
        else:
            match = re.match(r"^([A-Z]{2,3})(?=\d)", c)
            if match and match.group(1) in KNOWN_JURISDICTIONS:
                cc, rest = match.group(1), c[len(match.group(1)):]
                issues.append(("jurisdiction_mismatch", "warning",
                               "number prefix %s differs from jurisdiction field %s"
                               % (cc, explicit)))
            else:
                cc, rest = explicit, c
    else:
        match = re.match(r"^([A-Z]{2,3})(?=\d)", c)
        if match and match.group(1) in KNOWN_JURISDICTIONS:
            cc, rest = match.group(1), c[len(match.group(1)):]
        else:
            rest = c
        issues.append(("jurisdiction_missing", "error",
                       "jurisdiction is absent and the number has no known office prefix"))

    if not cc:
        issues.append(("jurisdiction_missing", "error",
                       "jurisdiction is absent and the number has no known office prefix"))
    elif cc not in KNOWN_JURISDICTIONS:
        issues.append(("jurisdiction_unverified", "warning",
                       "jurisdiction code %r is not in the built-in office list" % cc))

    core, kind = "", ""
    match = re.match(r"^(\d+)([A-Z]\d{0,2})?$", rest)
    if match:
        core, kind = match.group(1), match.group(2) or ""
    else:
        core = rest
        issues.append(("number_unparseable", "error",
                       "number body %r is not digits plus an optional kind code" % rest))

    if explicit_kind:
        if kind and kind != explicit_kind:
            issues.append(("kind_mismatch", "warning",
                           "number kind %s differs from kind field %s"
                           % (kind, explicit_kind)))
        elif not kind:
            kind = explicit_kind
    if not kind:
        issues.append(("kind_missing", "warning",
                       "publication kind code is missing; normalized number is incomplete"))
    elif not KIND_RE.fullmatch(kind):
        issues.append(("kind_unverified", "warning",
                       "kind code %r does not match the expected letter+digit form" % kind))

    valid = bool(cc and core and kind and not any(
        code == "number_unparseable" for code, _, _ in issues))
    normalized = (cc + core + kind) if valid else (cc + core + kind if cc else "")
    return {"input": text, "cc": cc, "core": core, "kind": kind,
            "normalized": normalized, "valid": valid, "issues": issues}


def norm_identifier(raw):
    return compact(raw)


def parse_priorities(raw):
    if isinstance(raw, (list, tuple)):
        parts = [str(p) for p in raw]
    else:
        parts = re.split(r"[;|]", str(raw or ""))
    tokens = []
    for part in parts:
        token = norm_identifier(part)
        if token:
            tokens.append(token)
    return tokens


def classify_status(raw):
    text = str(raw or "").strip()
    if not text:
        return "", False
    low = re.sub(r"[-_/]+", " ", text.lower())
    low = re.sub(r"\s+", " ", low).strip()
    if any(term in low for term in NEGATION_TERMS):
        return "unknown", False
    for label, needles in STATUS_RULES:
        if any(needle in low for needle in needles):
            return label, True
    return "unknown", False


def parse_status_date(raw):
    text = unicodedata.normalize("NFKC", str(raw or "")).strip()
    if not text:
        return "", "", "missing"
    for fmt, precision in (("%Y-%m-%d", "day"), ("%Y/%m/%d", "day"),
                           ("%Y.%m.%d", "day"), ("%Y%m%d", "day"),
                           ("%Y-%m", "month"), ("%Y/%m", "month"),
                           ("%Y", "year")):
        try:
            parsed = date(*_fmt_parts(text, fmt))
            return parsed.isoformat(), precision, ""
        except (ValueError, TypeError):
            continue
    return "", "", "invalid"


def _fmt_parts(text, fmt):
    if fmt == "%Y-%m-%d":
        y, m, d = text.split("-")
        return int(y), int(m), int(d)
    if fmt == "%Y/%m/%d":
        y, m, d = text.split("/")
        return int(y), int(m), int(d)
    if fmt == "%Y.%m.%d":
        y, m, d = text.split(".")
        return int(y), int(m), int(d)
    if fmt == "%Y%m%d":
        return int(text[:4]), int(text[4:6]), int(text[6:8])
    if fmt == "%Y-%m":
        y, m = text.split("-")
        return int(y), int(m), 1
    if fmt == "%Y/%m":
        y, m = text.split("/")
        return int(y), int(m), 1
    if fmt == "%Y":
        return int(text), 1, 1
    raise ValueError("unknown format")


def classify_source(source_file, legal_scope):
    sf = str(source_file or "").lower().replace("_", "-")
    scope = str(legal_scope or "").strip().lower()
    official_scope = scope in {"official", "primary", "facsimile", "registry", "grant"}
    secondary_scope = scope in {"secondary", "aggregator", "third-party",
                                "thirdparty", "derived", "blog", "news"}
    off_marker = any(marker in sf for marker in OFFICIAL_MARKERS)
    sec_marker = any(marker in sf for marker in SECONDARY_MARKERS)
    codes = []
    if official_scope and sec_marker:
        codes.append(("source_conflict", "warning",
                      "legal_scope is official but source_file looks secondary"))
        return "secondary", codes
    if secondary_scope:
        return "secondary", codes
    if sec_marker:
        return "secondary", codes
    if official_scope or off_marker:
        return "official", codes
    return "unknown", codes


def evidence_strength(source_class, normalized_valid, status_class,
                      status_date_norm):
    # High needs official source, a valid number, a classified status and a
    # dated record; a status substring alone is never enough.
    if (source_class == "official" and normalized_valid
            and status_class not in {"", "unknown"} and status_date_norm):
        return "high"
    if source_class == "official" or normalized_valid:
        return "medium"
    return "low"


def add_issue(issues, seen, severity, code, detail, record=None, **extra):
    record = record or {}
    key = (severity, code, extra.get("record_id", record.get("record_id", "")),
           extra.get("normalized", record.get("normalized", "")),
           extra.get("source_file", record.get("source_file", "")),
           extra.get("locator", record.get("locator", "")), detail)
    if key in seen:
        return
    seen.add(key)
    issues.append({"severity": severity, "code": code,
                   "record_id": extra.get("record_id", record.get("record_id", "")),
                   "normalized": extra.get("normalized", record.get("normalized", "")),
                   "source_file": extra.get("source_file", record.get("source_file", "")),
                   "locator": extra.get("locator", record.get("locator", "")),
                   "detail": detail})


def json_record_list(data):
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for key in ("records", "patents", "rows", "data", "items"):
            value = data.get(key)
            if isinstance(value, list):
                return value
        normalised = {canon_key(k) for k in data}
        if normalised & (FIELD_ALIASES["number"] | FIELD_ALIASES["family_id"]):
            return [data]
    return None


def read_input(path):
    if not os.path.exists(path):
        raise InputError("input path does not exist: %s" % path)
    is_dir = os.path.isdir(path)
    if is_dir:
        files = []
        for base, dirs, names in os.walk(path):
            dirs[:] = sorted(d for d in dirs if not d.startswith("."))
            for name in sorted(names):
                if name in SKIP_FILENAMES:
                    continue
                if os.path.splitext(name)[1].lower() in RECORD_EXTS:
                    files.append(os.path.join(base, name))
    else:
        if os.path.splitext(path)[1].lower() not in RECORD_EXTS:
            raise InputError("unsupported input extension: %s "
                             "(expected .csv/.tsv/.json/.jsonl)" % path)
        files = [path]
    if not files:
        raise InputError("no .csv/.tsv/.json/.jsonl record file found under %s" % path)

    items, notes, scanned = [], [], []
    for file_path in files:
        rel = os.path.basename(file_path) if not is_dir else os.path.relpath(file_path, path)
        rel = rel.replace(os.sep, "/")
        ext = os.path.splitext(file_path)[1].lower()
        try:
            if ext in {".csv", ".tsv"}:
                delimiter = "\t" if ext == ".tsv" else ","
                with open(file_path, encoding="utf-8-sig", newline="", errors="replace") as fh:
                    reader = csv.DictReader(fh, delimiter=delimiter)
                    if not reader.fieldnames:
                        notes.append({"file": rel, "note": "empty_or_headerless_csv"})
                        continue
                    recognised = {canon_key(f) for f in reader.fieldnames} & ALL_ALIAS_KEYS
                    if len(recognised) < 2:
                        notes.append({"file": rel,
                                      "note": "csv_skipped_no_recognised_fields",
                                      "fieldnames": reader.fieldnames})
                        continue
                    count = 0
                    for row_no, row in enumerate(reader, start=2):
                        if not any(str(v or "").strip() for v in row.values()):
                            continue
                        items.append({"raw": dict(row), "container_file": rel,
                                      "container_locator": "row:%d" % row_no,
                                      "seq": len(items) + 1})
                        count += 1
                    scanned.append({"file": rel, "records": count, "format": "csv"})
            elif ext == ".json":
                with open(file_path, encoding="utf-8-sig", errors="replace") as fh:
                    data = json.load(fh)
                rows = json_record_list(data)
                if rows is None:
                    notes.append({"file": rel, "note": "json_is_not_a_record_list"})
                    continue
                count = 0
                for i, row in enumerate(rows, start=1):
                    if not isinstance(row, dict):
                        notes.append({"file": rel, "note": "json_record_not_object",
                                      "index": i})
                        continue
                    items.append({"raw": row, "container_file": rel,
                                  "container_locator": "record:%d" % i,
                                  "seq": len(items) + 1})
                    count += 1
                scanned.append({"file": rel, "records": count, "format": "json"})
            else:  # .jsonl
                count = 0
                with open(file_path, encoding="utf-8-sig", errors="replace") as fh:
                    for line_no, line in enumerate(fh, start=1):
                        if not line.strip():
                            continue
                        try:
                            row = json.loads(line)
                        except ValueError as exc:
                            notes.append({"file": rel, "note": "jsonl_line_unparsable",
                                          "line": line_no, "error": str(exc)})
                            continue
                        if not isinstance(row, dict):
                            continue
                        items.append({"raw": row, "container_file": rel,
                                      "container_locator": "line:%d" % line_no,
                                      "seq": len(items) + 1})
                        count += 1
                scanned.append({"file": rel, "records": count, "format": "jsonl"})
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            notes.append({"file": rel, "note": "file_unreadable",
                          "error": "%s: %s" % (type(exc).__name__, exc)})
    if not scanned:
        reasons = "; ".join("%s: %s" % (n["file"], n["note"]) for n in notes)
        raise InputError("no parsable record file under %s (%s)"
                         % (path, reasons or "no supported record data"))
    return items, notes, scanned


def analyse(items, as_of, max_age_days):
    issues, seen_issues = [], set()
    records = []

    for item in items:
        raw = item["raw"]
        number = pick(raw, "number")
        jurisdiction = pick(raw, "jurisdiction")
        kind_field = pick(raw, "kind")
        application_no = pick(raw, "application_no")
        priority_raw = raw.get("priority")
        if priority_raw is None:
            for key, value in raw.items():
                if canon_key(key) in FIELD_ALIASES["priority"]:
                    priority_raw = value
                    break
        family_id = pick(raw, "family_id")
        title = pick(raw, "title")
        assignee = pick(raw, "assignee")
        status = pick(raw, "status")
        status_date_raw = pick(raw, "status_date")
        source_file = pick(raw, "source_file") or item["container_file"]
        locator = pick(raw, "locator") or item["container_locator"]
        legal_scope = pick(raw, "legal_scope")

        parsed = parse_publication(number, jurisdiction, kind_field)
        status_class, status_known = classify_status(status)
        status_date_norm, precision, date_error = parse_status_date(status_date_raw)
        priorities = parse_priorities(priority_raw)
        source_class, source_codes = classify_source(source_file, legal_scope)

        rec = {
            "number_input": number, "normalized": parsed["normalized"],
            "jurisdiction": parsed["cc"], "number_core": parsed["core"],
            "kind": parsed["kind"], "kind_valid": bool(parsed["kind"]) and bool(KIND_RE.fullmatch(parsed["kind"])),
            "normalized_valid": parsed["valid"],
            "application_no": application_no,
            "application_no_norm": norm_identifier(application_no),
            "priorities": priorities, "family_id": family_id,
            "title": title, "assignee": assignee, "status": status,
            "status_class": status_class, "status_date": status_date_raw,
            "status_date_norm": status_date_norm, "status_date_precision": precision,
            "source_class": source_class, "legal_scope": legal_scope,
            "source_file": source_file, "locator": locator,
            "container_file": item["container_file"],
            "container_locator": item["container_locator"],
            "seq": item["seq"], "duplicate_of": "", "flags": [],
        }
        rec["evidence_strength"] = evidence_strength(
            source_class, parsed["valid"], status_class, status_date_norm)
        if not parsed["valid"]:
            rec["flags"].append("normalized_invalid")
        if source_class == "secondary":
            rec["flags"].append("source_secondary")
        records.append(rec)

        for code, severity, detail in parsed["issues"]:
            add_issue(issues, seen_issues, severity, code, detail, rec)
        for code, severity, detail in source_codes:
            add_issue(issues, seen_issues, severity, code, detail, rec)
        if not source_file:
            add_issue(issues, seen_issues, "warning", "source_missing",
                      "record has no source_file", rec)
        if not legal_scope:
            add_issue(issues, seen_issues, "warning", "legal_scope_missing",
                      "record has no legal_scope; display rights are unverified", rec)
        if source_class == "secondary":
            add_issue(issues, seen_issues, "warning", "source_secondary",
                      "record comes from a secondary/aggregator source; do not "
                      "report it as official register data", rec)
        elif source_class == "unknown":
            add_issue(issues, seen_issues, "warning", "source_unverified",
                      "source cannot be classified as official or secondary", rec)
        if application_no:
            token = rec["application_no_norm"]
            if len(token) < 4 or not any(ch.isdigit() for ch in token):
                add_issue(issues, seen_issues, "warning", "application_no_invalid",
                          "application number %r looks incomplete" % application_no, rec)
        else:
            add_issue(issues, seen_issues, "warning", "application_no_missing",
                      "record has no application number", rec)
        for token in priorities:
            if not re.match(r"^[A-Z]{2}\d", token):
                add_issue(issues, seen_issues, "warning", "priority_unverified",
                          "priority %r lacks a jurisdiction prefix" % token, rec)
        if not status:
            add_issue(issues, seen_issues, "warning", "status_missing",
                      "record has no legal status", rec)
        elif not status_known:
            add_issue(issues, seen_issues, "warning", "status_unverified",
                      "status text %r was not classified" % status, rec)
        if not status_date_raw:
            add_issue(issues, seen_issues, "warning", "status_date_missing",
                      "record has no status_date", rec)
        elif date_error == "invalid":
            add_issue(issues, seen_issues, "warning", "status_date_invalid",
                      "status_date %r is not a recognised date" % status_date_raw, rec)
        if status_class in {"expired", "inactive"}:
            rec["flags"].append("status_inactive")
            add_issue(issues, seen_issues, "info", "status_inactive",
                      "status %r is classified as %s" % (status, status_class), rec)
        if as_of and status_date_norm:
            delta = (as_of - date.fromisoformat(status_date_norm)).days
            if delta < 0:
                add_issue(issues, seen_issues, "warning", "status_date_future",
                          "status_date %s is after the supplied as-of date %s"
                          % (status_date_norm, as_of.isoformat()), rec)
            elif delta > max_age_days:
                add_issue(issues, seen_issues, "warning", "status_stale",
                          "status_date %s is %d days before as-of %s (limit %d); "
                          "status may have changed" % (status_date_norm, delta,
                                                       as_of.isoformat(), max_age_days), rec)
                rec["flags"].append("status_stale")
                if precision != "day":
                    add_issue(issues, seen_issues, "info", "status_date_low_precision",
                              "status_date precision is %s; staleness is approximate"
                              % precision, rec)

    ordered = sorted(records, key=lambda r: (
        r["normalized"] or "~" + r["number_input"], r["jurisdiction"],
        r["source_file"], r["locator"], r["seq"]))
    for i, rec in enumerate(ordered, start=1):
        rec["record_id"] = "R%04d" % i

    # Duplicate publications and status conflicts on the same normalized number.
    by_number = {}
    for rec in ordered:
        if rec["normalized_valid"]:
            by_number.setdefault(rec["normalized"], []).append(rec)
    for normalized, group in sorted(by_number.items()):
        classes = {r["status_class"] for r in group if r["status_class"]}
        statuses = {r["status"] for r in group if r["status"]}
        if len(classes) > 1:
            for rec in group:
                add_issue(issues, seen_issues, "error", "status_conflict",
                          "same publication has conflicting status classes: %s"
                          % ", ".join(sorted(classes)), rec)
                rec["flags"].append("status_conflict")
        elif len(statuses) > 1:
            add_issue(issues, seen_issues, "info", "status_text_variant",
                      "same status class but different status text: %s"
                      % " | ".join(sorted(statuses)), group[0])
        authority = {"official": 0, "unknown": 1, "secondary": 2}
        canonical_group = sorted(group, key=lambda r: (
            authority.get(r["source_class"], 3), r["record_id"]))
        canonical = canonical_group[0]
        for rec in canonical_group[1:]:
            rec["duplicate_of"] = canonical["record_id"]
            rec["flags"].append("duplicate_record")
            add_issue(issues, seen_issues, "warning", "duplicate_record",
                      "duplicate of %s (same normalized publication number, "
                      "preferring the official source)" % canonical["record_id"], rec)

    # Observed family clustering: explicit family_id edges plus shared priorities.
    parent = list(range(len(ordered)))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[max(ra, rb)] = min(ra, rb)

    family_index, priority_index, number_index = {}, {}, {}
    for idx, rec in enumerate(ordered):
        if rec["normalized_valid"]:
            key = rec["normalized"]
            if key in number_index:
                union(idx, number_index[key])
            else:
                number_index[key] = idx
        fam = re.sub(r"\s+", "", rec["family_id"]).upper()
        if fam:
            if fam in family_index:
                union(idx, family_index[fam])
            else:
                family_index[fam] = idx
        for token in rec["priorities"]:
            if token in priority_index:
                union(idx, priority_index[token])
            else:
                priority_index[token] = idx

    grouped = {}
    for idx, rec in enumerate(ordered):
        grouped.setdefault(find(idx), []).append(rec)

    clusters = []
    for members in grouped.values():
        declared = sorted({re.sub(r"\s+", "", r["family_id"]).upper()
                           for r in members if r["family_id"]})
        priorities = sorted({p for r in members for p in r["priorities"]})
        basis = []
        if declared:
            basis.append("explicit_family_id")
        if priorities:
            basis.append("priority")
        if not basis:
            basis.append("singleton")
        if len(declared) > 1:
            scope = "conflicting_declaration"
        elif declared:
            scope = "declared_family"
        elif priorities:
            scope = "priority_extended"
        else:
            scope = "singleton"
        conflicts = []
        if len(declared) > 1:
            conflicts.append("multiple explicit family_id values linked: %s"
                             % ", ".join(declared))
            add_issue(issues, seen_issues, "error", "family_conflict",
                      "priority links records declaring different family_id values: %s"
                      % ", ".join(declared), members[0])
        if len(priorities) > 1:
            add_issue(issues, seen_issues, "info", "family_multiple_priorities",
                      "observed family contains %d distinct priority numbers; "
                      "simple and extended family scopes differ" % len(priorities),
                      members[0])
        if scope == "singleton" and not members[0]["family_id"]:
            add_issue(issues, seen_issues, "warning", "family_unknown",
                      "record has neither family_id nor priority; no family link "
                      "can be observed", members[0])
        clusters.append({
            "members": members, "declared": declared, "priorities": priorities,
            "basis": basis, "scope": scope, "conflicts": conflicts,
            "titles": sorted({r["title"] for r in members if r["title"]}),
            "assignees": sorted({r["assignee"] for r in members if r["assignee"]}),
        })

    clusters.sort(key=lambda c: (
        min((m["normalized"] or "~" + m["number_input"]) for m in c["members"]),
        min(m["source_file"] for m in c["members"]),
        min(m["record_id"] for m in c["members"])))
    family_rows = []
    for i, cluster in enumerate(clusters, start=1):
        family_id = "FAM-%03d" % i
        members = cluster["members"]
        family_rows.append({
            "family_id": family_id,
            "basis": cluster["basis"],
            "scope": cluster["scope"],
            "declared_family_ids": cluster["declared"],
            "priority_numbers": cluster["priorities"],
            "member_count": len(members),
            "distinct_publications": len({m["normalized"] or m["number_input"] for m in members}),
            "jurisdictions": sorted({m["jurisdiction"] for m in members if m["jurisdiction"]}),
            "statuses": sorted({m["status"] for m in members if m["status"]}),
            "titles": cluster["titles"],
            "assignees": cluster["assignees"],
            "conflicts": cluster["conflicts"],
            "members": [{
                "record_id": m["record_id"], "normalized": m["normalized"],
                "jurisdiction": m["jurisdiction"], "kind": m["kind"],
                "status": m["status"], "status_class": m["status_class"],
                "source_class": m["source_class"],
                "source_file": m["source_file"], "locator": m["locator"],
            } for m in members],
        })
        for member in members:
            member["family_cluster"] = family_id

    # Same number must not land in two clusters.
    number_clusters = {}
    for row in family_rows:
        for member in row["members"]:
            if member["normalized"]:
                number_clusters.setdefault(member["normalized"], set()).add(row["family_id"])
    for normalized, ids in sorted(number_clusters.items()):
        if len(ids) > 1:
            add_issue(issues, seen_issues, "error", "record_conflict_family",
                      "same normalized number appears in multiple clusters: %s"
                      % ", ".join(sorted(ids)), normalized=normalized)

    counts = {
        "records_total": len(ordered),
        "normalized_valid": sum(1 for r in ordered if r["normalized_valid"]),
        "families": len(family_rows),
        "declared_families": sum(1 for f in family_rows if f["scope"] == "declared_family"),
        "priority_extended_families": sum(1 for f in family_rows if f["scope"] == "priority_extended"),
        "singletons": sum(1 for f in family_rows if f["scope"] == "singleton"),
        "duplicates": sum(1 for r in ordered if r["duplicate_of"]),
        "official_sources": sum(1 for r in ordered if r["source_class"] == "official"),
        "secondary_sources": sum(1 for r in ordered if r["source_class"] == "secondary"),
        "unknown_sources": sum(1 for r in ordered if r["source_class"] == "unknown"),
        "status_missing": sum(1 for r in ordered if not r["status"]),
        "status_stale": sum(1 for r in ordered if "status_stale" in r["flags"]),
        "issues_error": sum(1 for i in issues if i["severity"] == "error"),
        "issues_warning": sum(1 for i in issues if i["severity"] == "warning"),
        "issues_info": sum(1 for i in issues if i["severity"] == "info"),
    }
    return ordered, family_rows, issues, counts


def sort_issues(issues):
    return sorted(issues, key=lambda i: (
        SEVERITY_RANK.get(i["severity"], 9), i["code"], i["record_id"],
        i["normalized"], i["source_file"], i["locator"], i["detail"]))


def write_json(path, data):
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=2)
        fh.write("\n")


def write_csv(path, rows, fieldnames):
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


NORMALIZED_FIELDS = [
    "record_id", "number_input", "normalized", "normalized_valid", "jurisdiction",
    "number_core", "kind", "kind_valid", "application_no", "application_no_norm",
    "priorities", "family_id", "family_cluster", "title", "assignee", "status",
    "status_class", "status_date", "status_date_norm", "status_date_precision",
    "source_class", "evidence_strength", "legal_scope", "source_file", "locator",
    "container_file", "container_locator", "duplicate_of", "flags",
]
ISSUE_FIELDS = ["severity", "code", "record_id", "normalized",
                "source_file", "locator", "detail"]


def main():
    parser = argparse.ArgumentParser(
        description="Normalize patent records and cluster observed families.")
    parser.add_argument("--input", required=True,
                        help="record file (.csv/.tsv/.json/.jsonl) or a directory")
    parser.add_argument("--out", required=True, help="output directory")
    parser.add_argument("--as-of", default="",
                        help="YYYY-MM-DD reference date for status staleness checks")
    parser.add_argument("--max-status-age-days", type=int, default=180,
                        help="flag status dates older than this many days (default 180)")
    args = parser.parse_args()

    out = args.out
    os.makedirs(out, exist_ok=True)
    try:
        if args.max_status_age_days < 0:
            raise InputError("--max-status-age-days must be >= 0")
        as_of = None
        if args.as_of:
            try:
                as_of = date.fromisoformat(args.as_of.strip())
            except ValueError:
                raise InputError("--as-of must be YYYY-MM-DD, got %r" % args.as_of)
        items, notes, scanned = read_input(args.input)
        records, families, issues, counts = analyse(
            items, as_of, args.max_status_age_days)
        issues = sort_issues(issues)
        if not items:
            status = "empty"
            issues.append({"severity": "warning", "code": "input_empty",
                           "record_id": "", "normalized": "", "source_file": "",
                           "locator": "", "detail": "no records parsed from input"})
            issues = sort_issues(issues)
        else:
            status = "issues" if issues else "ok"
        counts["issues_error"] = sum(1 for i in issues if i["severity"] == "error")
        counts["issues_warning"] = sum(1 for i in issues if i["severity"] == "warning")
        counts["issues_info"] = sum(1 for i in issues if i["severity"] == "info")

        data = {
            "tool": "patent_normalize.py",
            "schema_version": SCHEMA_VERSION,
            "status": status,
            "input": os.path.abspath(args.input),
            "input_files": scanned,
            "input_notes": notes,
            "as_of": as_of.isoformat() if as_of else "",
            "max_status_age_days": args.max_status_age_days,
            "counts": counts,
            "families": families,
            "issues": issues,
            "notes": {
                "family_scope": "Clusters use only explicit family_id values and shared "
                                "priority numbers present in the supplied records. This is "
                                "not an exhaustive DOCDB/INPADOC family.",
                "status_scope": "Legal status is copied from supplied records only; no "
                                "official register, fee or assignment database was queried.",
                "staleness": "Status staleness is evaluated only when --as-of is supplied."
                             if as_of else "No --as-of supplied; status staleness not evaluated.",
                "claims": "Claim text and scope are not parsed by this helper; the caller "
                          "must extract source-located claim versions separately.",
            },
        }
        write_json(os.path.join(out, "families.json"), data)

        rows = []
        for rec in records:
            rows.append({
                "record_id": rec["record_id"],
                "number_input": rec["number_input"],
                "normalized": rec["normalized"],
                "normalized_valid": str(rec["normalized_valid"]).lower(),
                "jurisdiction": rec["jurisdiction"],
                "number_core": rec["number_core"],
                "kind": rec["kind"],
                "kind_valid": str(rec["kind_valid"]).lower(),
                "application_no": rec["application_no"],
                "application_no_norm": rec["application_no_norm"],
                "priorities": ";".join(rec["priorities"]),
                "family_id": rec["family_id"],
                "family_cluster": rec.get("family_cluster", ""),
                "title": rec["title"], "assignee": rec["assignee"],
                "status": rec["status"], "status_class": rec["status_class"],
                "status_date": rec["status_date"],
                "status_date_norm": rec["status_date_norm"],
                "status_date_precision": rec["status_date_precision"],
                "source_class": rec["source_class"],
                "evidence_strength": rec["evidence_strength"],
                "legal_scope": rec["legal_scope"],
                "source_file": rec["source_file"], "locator": rec["locator"],
                "container_file": rec["container_file"],
                "container_locator": rec["container_locator"],
                "duplicate_of": rec["duplicate_of"],
                "flags": ";".join(sorted(rec["flags"])),
            })
        write_csv(os.path.join(out, "normalized.csv"), rows, NORMALIZED_FIELDS)
        write_csv(os.path.join(out, "issues.csv"), issues, ISSUE_FIELDS)

        print(json.dumps({
            "status": status,
            "records": counts["records_total"],
            "families": counts["families"],
            "duplicates": counts["duplicates"],
            "issues_error": counts["issues_error"],
            "issues_warning": counts["issues_warning"],
            "issues_info": counts["issues_info"],
            "out": out,
        }, ensure_ascii=False))
        return 0 if status == "ok" else 2
    except InputError as exc:
        failure = {
            "tool": "patent_normalize.py", "schema_version": SCHEMA_VERSION,
            "status": "failed",
            "input": os.path.abspath(args.input) if args.input else "",
            "as_of": args.as_of, "error": str(exc), "counts": {},
            "families": [],
            "issues": [{"severity": "error", "code": "input_error",
                        "record_id": "", "normalized": "", "source_file": "",
                        "locator": "", "detail": str(exc)}],
        }
        write_json(os.path.join(out, "families.json"), failure)
        write_csv(os.path.join(out, "normalized.csv"), [], NORMALIZED_FIELDS)
        write_csv(os.path.join(out, "issues.csv"), failure["issues"], ISSUE_FIELDS)
        print("error: %s" % exc, file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
