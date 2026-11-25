#!/usr/bin/env python3
"""tableio.py - dependency-free table ingestion for scientific data files.

Handles .csv / .tsv / .txt (delimiter and encoding sniffed) and .xlsx through the
standard library zip/xml readers (read-only, no third-party package). Exposes:

  read_table(path)             -> Table dict (header, rows, source metadata)
  read_any(path)               -> Table for csv/tsv/xlsx
  parse_header(name)           -> {"raw", "name", "unit"}  (unit in (g), [mg], /kg, _mm)
  to_number(value)             -> float or None (NA / <LOD / percentages handled)
  classify_columns(table)      -> {column: kind}
  write_normalized_csv(table, path)

No value is ever invented: unparsable cells become None and are counted, never filled.
"""
import csv
import hashlib
import io
import os
import re
import zipfile

MISSING_TOKENS = {
    "", "na", "n/a", "n.a.", "nan", "null", "none", "nil", "-", "--", "---", "—", "–",
    "?", "#n/a", "#na", "空", "无", "缺失", "未测", "nd", "not determined", ".",
}
DATE_RE = re.compile(r"^\d{4}[-/.]\d{1,2}([-/.]\d{1,2})?([ T]\d{1,2}:\d{2}(:\d{2})?)?")
BRACKET_RE = re.compile(r"^(.*?)[\s]*[\(\（\[\【]\s*([^\)\）\]\】]{1,24})\s*[\)\）\]\】]\s*$")
SLASH_RE = re.compile(r"^(.*?)\s*/\s*([A-Za-zµμ°%][A-Za-z0-9µμ°%./·^\-]{0,20})$")
KNOWN_UNITS = {
    "g", "kg", "mg", "ug", "µg", "ng", "pg", "ml", "ul", "µl", "l", "mm", "cm", "m", "km",
    "um", "µm", "nm", "s", "ms", "us", "ns", "h", "hr", "hrs", "min", "mins", "day", "days",
    "d", "wk", "week", "weeks", "yr", "year", "years", "c", "°c", "degc", "k", "pa", "kpa",
    "mpa", "bar", "ppm", "ppb", "mol", "mmol", "umol", "µmol", "rpm", "au", "od", "fold",
    "fc", "pct", "percent", "%", "hz", "khz", "mhz", "v", "mv", "kv", "a", "ma", "ua", "j",
    "kj", "cal", "kcal", "w", "kw", "iu", "units", "u", "mg/ml", "ng/ml", "g/l", "mg/l",
    "mmhg", "psi", "lb", "kg/m2", "cm2", "m2", "count", "counts", "copies", "cells",
}
COLUMN_KINDS = ("numeric", "date", "categorical", "empty", "mixed")
ID_HINT_RE = re.compile(r"(^|[_\s])(id|sample|subject|patient|gene|protein|probe|feature|"
                        r"row|index|name|symbol|label|case|key)([_\s]|$)", re.I)


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _decode(raw):
    for enc in ("utf-8-sig", "utf-8", "gb18030", "big5", "latin-1"):
        try:
            return raw.decode(enc), enc
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", "replace"), "utf-8-replace"


def _sniff_delim(text):
    head = "\n".join(text.splitlines()[:20])
    best, best_n = ",", -1
    for cand in (",", "\t", ";", "|"):
        n = head.count(cand)
        if n > best_n:
            best, best_n = cand, n
    return best if best_n > 0 else ","


def to_number(value):
    """Parse a scientific numeric cell. Returns None for missing/censored values."""
    if value is None:
        return None
    s = str(value).strip()
    if s.lower() in MISSING_TOKENS:
        return None
    s = (s.replace("\u2212", "-").replace("\u00a0", " ").replace("\u2009", "")
         .replace("\u2007", ""))
    if s.startswith("<") or s.startswith(">") or s.startswith("≤") or s.startswith("≥"):
        return None  # censored / limit-of-detection value: never guessed
    s = s.replace(",", "")
    if s.endswith("%"):
        s = s[:-1].strip()
    if s.endswith("×10^") or "^" in s:
        s = s.replace("×10^", "e").replace("^", "e")
    s = re.sub(r"\s+", "", s)
    if not s:
        return None
    try:
        v = float(s)
    except ValueError:
        return None
    if v != v or v in (float("inf"), float("-inf")):  # NaN / inf
        return None
    return v


def parse_header(name):
    """Split a column header into variable name and unit.

    'body_weight (g)' -> name body_weight, unit g
    '浓度/(mg/L)'     -> name 浓度, unit mg/L
    'length_mm'        -> name length, unit mm
    'sample_id'        -> unchanged (id-like suffixes are not units)
    """
    raw = str(name).strip()
    m = BRACKET_RE.match(raw)
    if m and m.group(1).strip():
        return {"raw": raw, "name": m.group(1).strip(), "unit": m.group(2).strip()}
    m = SLASH_RE.match(raw)
    if m and m.group(1).strip():
        unit = m.group(2).strip()
        key = unit.lower()
        if (key in KNOWN_UNITS or any(ch.isupper() for ch in unit)
                or re.search(r"[/·^]", unit) or unit in ("%", "°C")):
            if key not in ("id", "name", "type"):
                return {"raw": raw, "name": m.group(1).strip(), "unit": unit}
    if "_" in raw:
        base, _, suffix = raw.rpartition("_")
        key = suffix.lower()
        if base.strip() and key in KNOWN_UNITS and key not in ("id", "name", "type"):
            base2, _, suffix2 = base.rpartition("_")
            if (suffix2.lower() in KNOWN_UNITS and suffix2.lower() not in
                    ("id", "name", "type") and base2.strip()):
                return {"raw": raw, "name": base2.strip(),
                        "unit": "%s/%s" % (suffix2, suffix)}
            return {"raw": raw, "name": base.strip(), "unit": suffix}
    return {"raw": raw, "name": raw, "unit": ""}


def _column_letter_to_index(ref):
    m = re.match(r"([A-Z]+)", ref or "")
    if not m:
        return None
    idx = 0
    for ch in m.group(1):
        idx = idx * 26 + (ord(ch) - 64)
    return idx - 1


def _xlsx_sheet_rows(z, sheet_name, shared):
    xml = z.read(sheet_name).decode("utf-8", "replace")
    rows = []
    for row_xml in re.findall(r"<row[^>]*>(.*?)</row>", xml, re.S):
        cells = {}
        for attrs, body in re.findall(r"<c([^>]*)>(.*?)</c>", row_xml, re.S):
            ref = (re.search(r'r="([A-Z]+)\d+"', attrs) or [None, ""])[1]
            col = _column_letter_to_index(ref)
            if col is None:
                col = len(cells)
            text = ""
            if 't="inlineStr"' in attrs:
                text = "".join(re.findall(r"<t[^>]*>(.*?)</t>", body, re.S))
            else:
                v = re.search(r"<v>(.*?)</v>", body, re.S)
                if v:
                    val = v.group(1)
                    if 't="s"' in attrs:
                        try:
                            val = shared[int(val)]
                        except (ValueError, IndexError):
                            val = ""
                    text = val
            text = re.sub(r"<[^>]+>", "", text)
            cells[col] = text
        if cells:
            width = max(cells) + 1
            rows.append([cells.get(i, "") for i in range(width)])
    return rows


def read_xlsx(path):
    """Read every sheet with zipfile+regex; return list of (sheet_label, rows)."""
    out = []
    with zipfile.ZipFile(path) as z:
        names = z.namelist()
        shared = []
        if "xl/sharedStrings.xml" in names:
            s = z.read("xl/sharedStrings.xml").decode("utf-8", "replace")
            for si in re.findall(r"<si>(.*?)</si>", s, re.S):
                shared.append("".join(re.findall(r"<t[^>]*>(.*?)</t>", si, re.S)))
        sheet_files = sorted(n for n in names
                             if re.match(r"xl/worksheets/sheet\d+\.xml$", n))
        for i, name in enumerate(sheet_files):
            rows = _xlsx_sheet_rows(z, name, shared)
            if rows:
                out.append(("sheet%d" % (i + 1), rows))
    return out


def _finalize(header, body, path, delimiter, encoding, sheet=""):
    header = [str(h).strip() for h in header]
    seen, unique = {}, []
    for h in header:
        h = h or "column"
        if h in seen:
            seen[h] += 1
            unique.append("%s_%d" % (h, seen[h]))
        else:
            seen[h] = 0
            unique.append(h)
    width = len(unique)
    rows, extra_cells, short_rows = [], 0, 0
    for r in body:
        r = list(r)
        if len(r) > width:
            extra_cells += len(r) - width
        if 0 < len(r) < width:
            short_rows += 1
        rows.append([str(r[i]).strip() if i < len(r) else "" for i in range(width)]
                    + ([] if width else []))
    return {
        "path": path, "name": os.path.basename(path), "header": unique,
        "header_parsed": [parse_header(h) for h in unique],
        "rows": rows, "rows_total": len(rows), "columns": width,
        "delimiter": delimiter, "encoding": encoding, "sheet": sheet,
        "sha256": sha256_file(path), "bytes": os.path.getsize(path),
        "extra_cells": extra_cells, "short_rows": short_rows,
    }


def read_table(path):
    raw = open(path, "rb").read()
    text, encoding = _decode(raw)
    delimiter = _sniff_delim(text)
    reader = csv.reader(io.StringIO(text), delimiter=delimiter)
    records = [r for r in reader if any(str(c).strip() for c in r)]
    if not records:
        raise ValueError("empty table: %s" % os.path.basename(path))
    return _finalize(records[0], records[1:], path, delimiter, encoding)


def read_any(path):
    """Return the best table in a csv/tsv/txt or xlsx workbook.

    For xlsx the sheet with the most numeric cells wins; the chosen sheet and the
    number of sheets are recorded so the choice can be audited.
    """
    ext = os.path.splitext(path)[1].lower()
    if ext in (".xlsx", ".xlsm"):
        sheets = read_xlsx(path)
        if not sheets:
            raise ValueError("xlsx has no readable worksheet: %s" % os.path.basename(path))
        scored = []
        for label, rows in sheets:
            body = rows[1:]
            numeric = sum(1 for r in body for c in r if to_number(c) is not None)
            scored.append((numeric, len(body), label, rows))
        scored.sort(key=lambda t: (-t[0], -t[1], t[2]))
        numeric, _, label, rows = scored[0]
        table = _finalize(rows[0], rows[1:], path, ",", "xlsx", label)
        table.update({"sheet": label, "sheets": [s[2] for s in scored],
                      "sheet_choice": scored[0][2], "sheet_numeric_cells": numeric})
        return table
    return read_table(path)


def _looks_like_ymd(vals):
    """8-digit integers such as 20240101 are dates, not measurements."""
    hits = 0
    for v in vals:
        if len(v) == 8 and v.isdigit() and v[:2] in ("19", "20"):
            y, m, d = int(v[:4]), int(v[4:6]), int(v[6:])
            if 1900 <= y <= 2099 and 1 <= m <= 12 and 1 <= d <= 31:
                hits += 1
    return bool(vals) and hits / float(len(vals)) >= 0.8


def classify_columns(table):
    kinds = {}
    for j, name in enumerate(table["header"]):
        vals = [str(r[j]).strip() for r in table["rows"] if j < len(r) and str(r[j]).strip()]
        if not vals:
            kinds[name] = "empty"
            continue
        date_ratio = sum(1 for v in vals if DATE_RE.match(v)) / len(vals)
        if date_ratio >= 0.8 or _looks_like_ymd(vals):
            kinds[name] = "date"
            continue
        nums = [v for v in vals if to_number(v) is not None]
        if len(nums) / len(vals) >= 0.6:
            kinds[name] = "numeric"
        else:
            kinds[name] = "categorical"
    return kinds


def column_values(table, column):
    """Yield (row_number_1based, raw_value, parsed_number_or_None)."""
    j = table["header"].index(column)
    for i, r in enumerate(table["rows"]):
        raw = r[j] if j < len(r) else ""
        yield i + 2, raw, to_number(raw)


def write_normalized_csv(table, path):
    os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(table["header"])
        w.writerows(table["rows"])
    return path


def duplicate_rows(table):
    seen, dups = set(), []
    for i, r in enumerate(table["rows"]):
        key = tuple(r)
        if key in seen:
            dups.append(i + 2)
        seen.add(key)
    return dups
