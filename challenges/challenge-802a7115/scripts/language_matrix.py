#!/usr/bin/env python3
"""Build a multilingual work/version matrix from supplied literature records.

The helper only normalizes and cross-checks supplied records. It does not
search the network, judge topical relevance, translate text or invent missing
metadata.

Usage:
  python3 scripts/language_matrix.py --input PATH --out DIR \
      [--expected-languages en,pt,zh]

  PATH is a CSV/TSV/JSON/JSONL file, or a directory scanned in sorted order.
  DIR receives matrix.json, versions.csv and issues.csv.

Expected fields (aliases accepted): work_id, version_id, language,
version_type, doi, title, translated_from, source_file, locator.
version_type must be one of original, translation, abstract_only, duplicate,
bilingual.

Exit codes:
  0 completed with no issues
  2 completed with issues (empty input included)
  1 unusable input: path missing, unreadable, or no parsable record file
"""
import argparse
import csv
import json
import os
import re
import sys
import unicodedata

SCHEMA_VERSION = "1.0"
VERSION_TYPES = ("original", "translation", "abstract_only", "duplicate", "bilingual")
FULL_TEXT_TYPES = {"original", "translation", "bilingual"}

# Keys are compared after removing spaces, hyphens, underscores and dots.
VERSION_ALIASES = {
    "original": "original", "orig": "original", "sourceversion": "original",
    "translation": "translation", "translated": "translation",
    "fulltranslation": "translation", "fulltexttranslation": "translation",
    "abstractonly": "abstract_only", "abstract": "abstract_only",
    "duplicate": "duplicate", "dup": "duplicate", "duplicated": "duplicate",
    "bilingual": "bilingual", "multilingual": "bilingual",
    "原文": "original", "译文": "translation", "仅摘要": "abstract_only",
    "重复": "duplicate", "双语": "bilingual",
}

NAME_TO_CODE = {
    "english": "en", "portuguese": "pt", "brazilian portuguese": "pt-br",
    "chinese": "zh", "mandarin": "zh", "中文": "zh", "汉语": "zh",
    "普通话": "zh", "简体中文": "zh", "繁体中文": "zh",
    "german": "de", "french": "fr",
    "spanish": "es", "japanese": "ja", "korean": "ko", "russian": "ru",
    "italian": "it", "dutch": "nl", "polish": "pl", "turkish": "tr",
    "swedish": "sv", "danish": "da", "finnish": "fi", "norwegian": "no",
    "czech": "cs", "greek": "el", "hebrew": "he", "thai": "th",
    "vietnamese": "vi", "indonesian": "id", "malay": "ms", "arabic": "ar",
    "persian": "fa", "hindi": "hi", "bengali": "bn", "urdu": "ur",
    "ukrainian": "uk", "romanian": "ro", "hungarian": "hu", "bulgarian": "bg",
    "serbian": "sr", "croatian": "hr", "slovak": "sk", "slovenian": "sl",
    "estonian": "et", "latvian": "lv", "lithuanian": "lt", "catalan": "ca",
    "galician": "gl", "basque": "eu", "welsh": "cy", "irish": "ga",
    "icelandic": "is", "afrikaans": "af", "swahili": "sw", "amharic": "am",
    "tamil": "ta", "telugu": "te", "malayalam": "ml", "kannada": "kn",
    "gujarati": "gu", "punjabi": "pa", "nepali": "ne", "sinhala": "si",
    "burmese": "my", "khmer": "km", "lao": "lo", "georgian": "ka",
    "armenian": "hy", "azerbaijani": "az", "kazakh": "kk", "uzbek": "uz",
    "mongolian": "mn", "tibetan": "bo", "albanian": "sq", "macedonian": "mk",
    "bosnian": "bs", "belarusian": "be", "luxembourgish": "lb", "maltese": "mt",
    "faroese": "fo", "latin": "la", "esperanto": "eo",
}

LANG_NAMES = {
    "en": "English", "pt": "Portuguese", "zh": "Chinese", "de": "German",
    "fr": "French", "es": "Spanish", "ja": "Japanese", "ko": "Korean",
    "ru": "Russian", "it": "Italian", "nl": "Dutch", "pl": "Polish",
    "tr": "Turkish", "sv": "Swedish", "da": "Danish", "fi": "Finnish",
    "no": "Norwegian", "nb": "Norwegian Bokmal", "cs": "Czech", "el": "Greek",
    "he": "Hebrew", "th": "Thai", "vi": "Vietnamese", "id": "Indonesian",
    "ms": "Malay", "ar": "Arabic", "fa": "Persian", "hi": "Hindi",
    "bn": "Bengali", "ur": "Urdu", "uk": "Ukrainian", "ro": "Romanian",
    "hu": "Hungarian", "bg": "Bulgarian", "sr": "Serbian", "hr": "Croatian",
    "sk": "Slovak", "sl": "Slovenian", "et": "Estonian", "lv": "Latvian",
    "lt": "Lithuanian", "ca": "Catalan", "gl": "Galician", "eu": "Basque",
    "cy": "Welsh", "ga": "Irish", "is": "Icelandic", "af": "Afrikaans",
    "sw": "Swahili", "am": "Amharic", "ta": "Tamil", "te": "Telugu",
    "ml": "Malayalam", "kn": "Kannada", "gu": "Gujarati", "pa": "Punjabi",
    "ne": "Nepali", "si": "Sinhala", "my": "Burmese", "km": "Khmer",
    "lo": "Lao", "ka": "Georgian", "hy": "Armenian", "az": "Azerbaijani",
    "kk": "Kazakh", "uz": "Uzbek", "mn": "Mongolian", "bo": "Tibetan",
    "sq": "Albanian", "mk": "Macedonian", "bs": "Bosnian", "be": "Belarusian",
    "lb": "Luxembourgish", "mt": "Maltese", "fo": "Faroese", "la": "Latin",
    "eo": "Esperanto", "und": "undetermined", "mul": "multiple",
}

# ISO 639-2/3 codes frequently seen in exports; mapped to the 2-letter key.
ISO3_TO_PRIMARY = {
    "eng": "en", "por": "pt", "zho": "zh", "chi": "zh", "deu": "de", "ger": "de",
    "fra": "fr", "fre": "fr", "spa": "es", "jpn": "ja", "kor": "ko",
    "rus": "ru", "ita": "it", "nld": "nl", "dut": "nl", "pol": "pl",
    "tur": "tr", "swe": "sv", "dan": "da", "fin": "fi", "nor": "no",
    "ces": "cs", "cze": "cs", "ell": "el", "gre": "el", "heb": "he",
    "tha": "th", "vie": "vi", "ind": "id", "msa": "ms", "may": "ms",
    "ara": "ar", "fas": "fa", "per": "fa", "hin": "hi", "ben": "bn",
    "urd": "ur", "ukr": "uk", "ron": "ro", "rum": "ro", "hun": "hu",
    "bul": "bg", "srp": "sr", "hrv": "hr", "slk": "sk", "slo": "sk",
    "slv": "sl", "est": "et", "lav": "lv", "lit": "lt", "cat": "ca",
    "glg": "gl", "eus": "eu", "baq": "eu", "cym": "cy", "wel": "cy",
    "gle": "ga", "iri": "ga", "isl": "is", "ice": "is", "afr": "af",
    "swa": "sw", "amh": "am", "tam": "ta", "tel": "te", "mal": "ml",
    "kan": "kn", "guj": "gu", "pan": "pa", "nep": "ne", "sin": "si",
    "mya": "my", "bur": "my", "khm": "km", "lao": "lo", "kat": "ka",
    "geo": "ka", "hye": "hy", "arm": "hy", "aze": "az", "kaz": "kk",
    "uzb": "uz", "mon": "mn", "bod": "bo", "tib": "bo", "sqi": "sq",
    "alb": "sq", "mkd": "mk", "mac": "mk", "bos": "bs", "bel": "be",
    "ltz": "lb", "mlt": "mt", "fao": "fo", "lat": "la", "epo": "eo",
}
KNOWN_PRIMARY = set(LANG_NAMES) | set(ISO3_TO_PRIMARY)

FIELD_ALIASES = {
    "work_id": {"workid", "work", "wid", "workidentifier"},
    "version_id": {"versionid", "version", "ver", "versionidentifier", "docid"},
    "language": {"language", "lang", "locale", "languagetag", "languagecode"},
    "version_type": {"versiontype", "type", "versionkind"},
    "doi": {"doi", "digitalobjectidentifier"},
    "title": {"title", "articletitle", "documenttitle"},
    "translated_from": {"translatedfrom", "translationof", "sourceversion",
                        "translatedfromversion", "originalversion"},
    "source_file": {"sourcefile", "source", "file", "path", "filename"},
    "locator": {"locator", "loc", "position", "location", "page"},
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
DOI_RE = re.compile(r"^10\.\d{4,9}/\S+$")
TAG_RE = re.compile(r"^[a-z]{2,3}(-[a-z0-9]{2,8})*$")
LANG_SPLIT_RE = re.compile(r"[;,|/]+")

SEVERITY_RANK = {"error": 0, "warning": 1, "info": 2}


class InputError(Exception):
    """Input cannot be used at all."""


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


def norm_doi(raw):
    text = unicodedata.normalize("NFKC", str(raw or "")).strip()
    text = re.sub(r"^(https?://(dx\.)?doi\.org/|doi:\s*)", "", text, flags=re.I)
    return text.replace(" ", "").rstrip(". ")


def parse_version_type(raw):
    key = canon_key(raw)
    if not key:
        return "", False
    return VERSION_ALIASES.get(key, ""), key in VERSION_ALIASES


def parse_language(raw):
    text = unicodedata.normalize("NFKC", str(raw or "")).strip()
    if not text:
        return {"language": "", "primary": "", "valid": False,
                "verified": False, "reason": "missing"}
    low = text.lower().replace("_", "-")
    name_key = re.sub(r"\s+", " ", low)
    if name_key in NAME_TO_CODE:
        low = NAME_TO_CODE[name_key]
    if TAG_RE.fullmatch(low):
        primary = low.split("-")[0]
        if primary in ISO3_TO_PRIMARY:
            mapped = ISO3_TO_PRIMARY[primary]
            low = mapped + low[len(primary):]
            primary = mapped.split("-")[0]
        verified = primary in KNOWN_PRIMARY
        return {"language": low, "primary": primary, "valid": True,
                "verified": verified,
                "reason": "" if verified else "primary subtag not in built-in list"}
    return {"language": text, "primary": "", "valid": False,
            "verified": False, "reason": "not a BCP-47-like tag or known language name"}


def parse_languages(raw):
    """Parse one or more language values, de-duplicated in input order."""
    text = str(raw or "")
    parts = [part.strip() for part in LANG_SPLIT_RE.split(text) if part.strip()]
    if not parts:
        return [parse_language("")]
    results, seen = [], set()
    for part in parts:
        lang = parse_language(part)
        key = (lang["language"], lang["primary"])
        if key in seen:
            continue
        seen.add(key)
        results.append(lang)
    return results


def add_issue(issues, seen, severity, code, detail,
              work_id="", version_id="", source_file="", locator=""):
    key = (severity, code, work_id, version_id, source_file, locator, detail)
    if key in seen:
        return
    seen.add(key)
    issues.append({"severity": severity, "code": code, "work_id": work_id,
                   "version_id": version_id, "source_file": source_file,
                   "locator": locator, "detail": detail})


def json_record_list(data):
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for key in ("records", "versions", "works", "rows", "data", "items"):
            value = data.get(key)
            if isinstance(value, list):
                return value
        normalised = {canon_key(k) for k in data}
        if normalised & (FIELD_ALIASES["work_id"] | FIELD_ALIASES["version_id"]):
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


def analyse(items, expected_languages):
    issues, seen_issues = [], set()

    def issue(severity, code, detail, rec=None, **extra):
        rec = rec or {}
        add_issue(issues, seen_issues, severity, code, detail,
                  work_id=extra.get("work_id", rec.get("work_id", "")),
                  version_id=extra.get("version_id", rec.get("version_id", "")),
                  source_file=extra.get("source_file", rec.get("source_file", "")),
                  locator=extra.get("locator", rec.get("locator", "")))

    records = []
    for item in items:
        raw = item["raw"]
        work_id = pick(raw, "work_id")
        version_id = pick(raw, "version_id")
        language_raw = pick(raw, "language")
        vtype_raw = pick(raw, "version_type")
        doi_raw = pick(raw, "doi")
        title = pick(raw, "title")
        translated_from = pick(raw, "translated_from")
        source_file = pick(raw, "source_file") or item["container_file"]
        locator = pick(raw, "locator") or item["container_locator"]
        langs = parse_languages(language_raw)
        valid_langs = [lang for lang in langs if lang["valid"]]
        lang_tags = [lang["language"] for lang in valid_langs]
        lang_primaries = sorted({lang["primary"] for lang in valid_langs if lang["primary"]})
        vtype, vtype_ok = parse_version_type(vtype_raw)
        doi = norm_doi(doi_raw)

        rec = {
            "work_id": work_id, "version_id": version_id,
            "language_raw": language_raw, "language": ";".join(lang_tags),
            "language_primary": ";".join(lang_primaries), "language_name":
                ";".join(LANG_NAMES[p] for p in lang_primaries if p in LANG_NAMES),
            "language_valid": bool(valid_langs) and len(valid_langs) == len(langs),
            "language_verified": bool(valid_langs) and all(
                lang["verified"] for lang in valid_langs),
            "languages": langs,
            "version_type_raw": vtype_raw, "version_type": vtype,
            "version_type_valid": vtype_ok, "doi": doi, "title": title,
            "translated_from": translated_from, "source_file": source_file,
            "locator": locator, "container_file": item["container_file"],
            "container_locator": item["container_locator"], "seq": item["seq"],
            "status": "ok", "duplicate_of": "", "flags": [],
        }
        records.append(rec)

        if not work_id:
            issue("error", "work_id_missing", "record has no work_id", rec)
        if not version_id:
            issue("error", "version_id_missing", "record has no version_id", rec)
            rec["flags"].append("orphan_version")
        if not language_raw:
            issue("error", "language_missing", "record has no language", rec)
        else:
            invalid_langs = [lang for lang in langs if not lang["valid"]]
            if invalid_langs:
                issue("error", "language_invalid",
                      "unparsable language value(s): %s" % "; ".join(
                          "%r (%s)" % (lang["language"], lang["reason"])
                          for lang in invalid_langs), rec)
            unverified_langs = [lang for lang in langs
                               if lang["valid"] and not lang["verified"]]
            if unverified_langs:
                issue("warning", "language_unverified",
                      "; ".join("%r: %s" % (lang["language"], lang["reason"])
                                for lang in unverified_langs), rec)
        if not vtype_raw:
            issue("error", "version_type_missing",
                  "record has no version_type", rec)
        elif not vtype_ok:
            issue("error", "version_type_invalid",
                  "version_type %r is not one of %s" % (vtype_raw, ", ".join(VERSION_TYPES)), rec)
        if not title:
            issue("warning", "title_missing", "record has no title", rec)
        if doi_raw and not DOI_RE.match(doi):
            issue("warning", "doi_invalid", "DOI %r is not a valid DOI suffix form" % doi_raw, rec)
        if rec["version_type"] in {"translation", "abstract_only"} and not translated_from:
            if rec["version_type"] == "translation":
                issue("warning", "translation_link_missing",
                      "translation record has no translated_from version_id", rec)
        if not source_file or not locator:
            issue("warning", "provenance_missing",
                  "record lacks source_file or locator", rec)

    ordered = sorted(records, key=lambda r: (
        r["work_id"], r["version_id"], r["language"], r["version_type"],
        r["source_file"], r["locator"], r["seq"]))
    for i, rec in enumerate(ordered, start=1):
        rec["record_id"] = "R%04d" % i

    # Same version_id inside one work with conflicting attributes.
    by_version = {}
    for rec in ordered:
        by_version.setdefault((rec["work_id"], rec["version_id"]), []).append(rec)
    def lang_key(rec):
        return frozenset(tag for tag in rec["language"].split(";") if tag)

    for key, group in by_version.items():
        attrs = {(lang_key(r), r["version_type"], r["doi"]) for r in group}
        if len(attrs) > 1:
            for rec in group:
                rec["status"] = "conflict"
                rec["flags"].append("version_conflict")
                issue("error", "version_conflict",
                      "same work_id/version_id has conflicting language, "
                      "version_type or DOI", rec)

    # Exact duplicates keep the first record, later ones are marked.
    kept = {}
    for rec in ordered:
        key = (rec["work_id"], rec["version_id"], lang_key(rec),
               rec["version_type"], rec["doi"])
        if key in kept:
            rec["status"] = "duplicate"
            rec["duplicate_of"] = kept[key]["record_id"]
            rec["flags"].append("duplicate_version")
            issue("warning", "duplicate_version",
                  "exact duplicate of %s (same work, version, language, type, DOI)"
                  % kept[key]["record_id"], rec)
        else:
            kept[key] = rec

    # Dangling translated_from references.
    work_versions = {(r["work_id"], r["version_id"]) for r in ordered}
    all_versions = {r["version_id"] for r in ordered if r["version_id"]}
    for rec in ordered:
        target = rec["translated_from"]
        if not target:
            continue
        if (rec["work_id"], target) in work_versions:
            continue
        rec["flags"].append("orphan_version")
        if target in all_versions:
            issue("warning", "orphan_cross_work",
                  "translated_from %s exists only under another work_id" % target, rec)
        else:
            issue("error", "orphan_version",
                  "translated_from %s is not present in the supplied records" % target, rec)

    # DOI shared across works or across versions.
    doi_works, doi_versions = {}, {}
    for rec in ordered:
        if not rec["doi"]:
            continue
        doi_works.setdefault(rec["doi"], set()).add(rec["work_id"])
        doi_versions.setdefault((rec["work_id"], rec["doi"]), set()).add(
            (rec["version_id"], rec["language"], rec["version_type"]))
    for doi, works in sorted(doi_works.items()):
        if len(works) > 1:
            issue("warning", "doi_cross_work_conflict",
                  "DOI %s appears under multiple work_id values: %s"
                  % (doi, ", ".join(sorted(works))), work_id="")
    for (work_id, doi), versions in sorted(doi_versions.items()):
        if len(versions) > 1:
            issue("info", "doi_shared_across_versions",
                  "DOI %s is shared by %d versions of work %s; verify publisher "
                  "version numbering" % (doi, len(versions), work_id),
                  work_id=work_id)

    # Work-level matrix.
    works = {}
    for rec in ordered:
        wid = rec["work_id"] or "<missing-work-id>"
        work = works.setdefault(wid, {
            "work_id": wid, "titles": set(), "dois": set(),
            "languages": {}, "records": [],
        })
        work["records"].append(rec)
        if rec["title"]:
            work["titles"].add(rec["title"])
        if rec["doi"]:
            work["dois"].add(rec["doi"])
        for lang in rec["languages"]:
            lang_key = (lang["language"] if lang["valid"] else
                        (lang["language"] or "<unknown>"))
            work["languages"].setdefault(lang_key, {}).setdefault(
                rec["version_type"] or "<unknown>", []).append(
                    rec["version_id"] or "<missing>")

    work_rows = []
    for wid in sorted(works):
        work = works[wid]
        recs = work["records"]
        # Duplicates add no new version; conflicting records still describe a
        # real supplied version, so they stay in coverage and are flagged.
        active = [r for r in recs if r["status"] != "duplicate"]
        coverage = active or recs
        full_langs = sorted({lang["primary"] or lang["language"]
                             for r in coverage
                             if r["version_type"] in FULL_TEXT_TYPES
                             for lang in r["languages"]
                             if lang["valid"] and (lang["primary"] or lang["language"])})
        abstract_langs = sorted({lang["primary"] or lang["language"]
                                 for r in coverage
                                 if r["version_type"] == "abstract_only"
                                 for lang in r["languages"]
                                 if lang["valid"] and (lang["primary"] or lang["language"])})
        flags = set()
        for rec in recs:
            flags.update(rec["flags"])
        has_original = any(r["version_type"] == "original" for r in coverage)
        has_full = any(r["version_type"] in FULL_TEXT_TYPES for r in coverage)
        if not has_original:
            flags.add("original_missing")
        if not has_full and any(r["version_type"] == "abstract_only" for r in coverage):
            flags.add("abstract_only_coverage")
        if len(full_langs) >= 2:
            flags.add("multilingual_work")
        if any(r["status"] == "duplicate" for r in recs):
            flags.add("duplicate_versions")
        if any(r["version_type"] == "bilingual" for r in coverage):
            flags.add("bilingual_present")
        missing = []
        if expected_languages:
            observed = set(full_langs)
            missing = sorted(set(expected_languages) - observed)
            if missing:
                flags.add("missing_language")
                for lang in missing:
                    add_issue(issues, seen_issues, "warning", "language_missing",
                              "work has no full-text record in expected language %s"
                              % lang, work_id=wid)
        if not has_original:
            add_issue(issues, seen_issues, "warning", "original_missing",
                      "work has no record with version_type=original", work_id=wid)

        matrix_langs = {}
        for lang in sorted(work["languages"]):
            matrix_langs[lang] = {
                vtype: sorted(set(ids))
                for vtype, ids in sorted(work["languages"][lang].items())
            }
        work_rows.append({
            "work_id": wid,
            "titles": sorted(work["titles"]),
            "dois": sorted(work["dois"]),
            "record_count": len(recs),
            "distinct_version_ids": sorted({r["version_id"] for r in recs if r["version_id"]}),
            "languages": matrix_langs,
            "full_text_languages": full_langs,
            "abstract_only_languages": abstract_langs,
            "has_original": has_original,
            "missing_expected_languages": missing,
            "flags": sorted(flags),
            "record_ids": [r["record_id"] for r in recs],
        })

    counts = {
        "records_total": len(ordered),
        "works": len(work_rows),
        "distinct_version_ids": len({r["version_id"] for r in ordered if r["version_id"]}),
        "languages_observed": sorted({lang["language"] for r in ordered
                                      for lang in r["languages"] if lang["valid"]}),
        "translations": sum(1 for r in ordered if r["version_type"] == "translation"),
        "abstract_only": sum(1 for r in ordered if r["version_type"] == "abstract_only"),
        "bilingual": sum(1 for r in ordered if r["version_type"] == "bilingual"),
        "duplicates": sum(1 for r in ordered if r["status"] == "duplicate"),
        "conflicts": sum(1 for r in ordered if r["status"] == "conflict"),
        "orphans": sum(1 for r in ordered if "orphan_version" in r["flags"]),
        "issues_error": sum(1 for i in issues if i["severity"] == "error"),
        "issues_warning": sum(1 for i in issues if i["severity"] == "warning"),
        "issues_info": sum(1 for i in issues if i["severity"] == "info"),
    }
    return ordered, work_rows, issues, counts


def sort_issues(issues):
    return sorted(issues, key=lambda i: (
        SEVERITY_RANK.get(i["severity"], 9), i["code"], i["work_id"],
        i["version_id"], i["source_file"], i["locator"], i["detail"]))


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


def main():
    parser = argparse.ArgumentParser(
        description="Build a multilingual work/version matrix from supplied records.")
    parser.add_argument("--input", required=True,
                        help="record file (.csv/.tsv/.json/.jsonl) or a directory")
    parser.add_argument("--out", required=True, help="output directory")
    parser.add_argument("--expected-languages", default="",
                        help="comma-separated target language tags for coverage checks")
    args = parser.parse_args()

    out = args.out
    os.makedirs(out, exist_ok=True)
    expected = []
    try:
        raw_expected = [p.strip() for p in re.split(r"[,;\s]+", args.expected_languages) if p.strip()]
        bad_expected = []
        for token in raw_expected:
            lang = parse_language(token)
            if lang["valid"]:
                expected.append(lang["primary"] or lang["language"])
            else:
                bad_expected.append(token)
        expected = sorted(set(expected))

        items, notes, scanned = read_input(args.input)
        records, works, issues, counts = analyse(items, expected)
        for token in bad_expected:
            add_issue(issues, set(), "warning", "expected_language_invalid",
                      "expected language %r is not a recognised tag" % token)
        issues = sort_issues(issues)
        if not items:
            status = "empty"
            issues.append({"severity": "warning", "code": "input_empty",
                           "work_id": "", "version_id": "", "source_file": "",
                           "locator": "", "detail": "no records parsed from input"})
            issues = sort_issues(issues)
        else:
            status = "issues" if issues else "ok"
        counts["issues_error"] = sum(1 for i in issues if i["severity"] == "error")
        counts["issues_warning"] = sum(1 for i in issues if i["severity"] == "warning")
        counts["issues_info"] = sum(1 for i in issues if i["severity"] == "info")

        matrix = {
            "tool": "language_matrix.py",
            "schema_version": SCHEMA_VERSION,
            "status": status,
            "input": os.path.abspath(args.input),
            "input_files": scanned,
            "input_notes": notes,
            "expected_languages": expected,
            "counts": counts,
            "works": works,
            "issues": issues,
            "notes": {
                "scope": "Supplied records only; no live search, translation or language "
                         "identification service was called.",
                "language_basis": "Language tags are normalized, not re-identified from "
                                  "full text. Verify each record against the actual document.",
                "version_basis": "Version types come from supplied labels; duplicates are "
                                 "exact matches on work_id+version_id+language+type+DOI.",
                "expected_languages": "Per-work coverage is checked only against the tags "
                                      "passed on the command line.",
            },
        }
        write_json(os.path.join(out, "matrix.json"), matrix)

        version_fields = [
            "record_id", "work_id", "version_id", "language", "language_name",
            "language_primary", "language_verified", "version_type", "doi",
            "title", "translated_from", "source_file", "locator",
            "container_file", "container_locator", "record_status",
            "duplicate_of", "flags",
        ]
        version_rows = [{
            "record_id": r["record_id"], "work_id": r["work_id"],
            "version_id": r["version_id"], "language": r["language"],
            "language_name": r["language_name"],
            "language_primary": r["language_primary"],
            "language_verified": str(r["language_verified"]).lower(),
            "version_type": r["version_type"], "doi": r["doi"],
            "title": r["title"], "translated_from": r["translated_from"],
            "source_file": r["source_file"], "locator": r["locator"],
            "container_file": r["container_file"],
            "container_locator": r["container_locator"],
            "record_status": r["status"], "duplicate_of": r["duplicate_of"],
            "flags": ";".join(sorted(r["flags"])),
        } for r in records]
        write_csv(os.path.join(out, "versions.csv"), version_rows, version_fields)

        issue_fields = ["severity", "code", "work_id", "version_id",
                        "source_file", "locator", "detail"]
        write_csv(os.path.join(out, "issues.csv"), issues, issue_fields)

        print(json.dumps({
            "status": status,
            "records": counts["records_total"],
            "works": counts["works"],
            "issues_error": counts["issues_error"],
            "issues_warning": counts["issues_warning"],
            "issues_info": counts["issues_info"],
            "out": out,
        }, ensure_ascii=False))
        return 0 if status == "ok" else 2
    except InputError as exc:
        failure = {
            "tool": "language_matrix.py", "schema_version": SCHEMA_VERSION,
            "status": "failed", "input": os.path.abspath(args.input) if args.input else "",
            "error": str(exc), "counts": {}, "works": [],
            "issues": [{"severity": "error", "code": "input_error",
                        "work_id": "", "version_id": "", "source_file": "",
                        "locator": "", "detail": str(exc)}],
        }
        write_json(os.path.join(out, "matrix.json"), failure)
        write_csv(os.path.join(out, "versions.csv"), [], [
            "record_id", "work_id", "version_id", "language", "language_name",
            "language_primary", "language_verified", "version_type", "doi",
            "title", "translated_from", "source_file", "locator",
            "container_file", "container_locator", "record_status",
            "duplicate_of", "flags"])
        write_csv(os.path.join(out, "issues.csv"), failure["issues"],
                  ["severity", "code", "work_id", "version_id",
                   "source_file", "locator", "detail"])
        print("error: %s" % exc, file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
