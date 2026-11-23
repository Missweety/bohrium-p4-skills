#!/usr/bin/env python3
"""pdf_text_fallback.py - dependency-free PDF text extraction with layout order.

Only the Python standard library is used (re, zlib, codecs). It is the second
tier of the extraction chain in paper2notes.py, used when `pdftotext` is not
installed:

  1. pdftotext -layout / -raw          (best quality, needs poppler)
  2. this module                       (pure stdlib, coordinate based)
  3. unreadable                        (scanned / encrypted / broken)

What it supports
  - classic xref PDFs and object streams (/ObjStm)
  - FlateDecode content streams; other filters are reported, not guessed
  - page tree traversal (not byte order), MediaBox based page width
  - text state: Tm/Td/TD/T*/Tf/TL/Tc/Tw/Tz/Ts/Tj/TJ/'/" and q/Q/cm stack
  - fonts: ToUnicode CMap, /Encoding Differences, WinAnsi/MacRoman base
    encodings, /Widths, plus the standard-14 Times/Helvetica/Courier metrics
  - line assembly by y, word gaps from TJ kerning, simple two-column split

What it does not do
  - no OCR, no decryption, no Form XObject content, no Type3 glyph rendering
  - reading order is heuristic; a human/agent must spot-check headings

API: extract(path, max_pages=60) -> dict
     {text, pages_total, pages_used, chars, chars_per_page, truncated,
      warnings, encrypted}
Raises: PdfTextError when the file cannot be parsed at all.
"""

import codecs
import re
import zlib

WS = b"\x00\t\n\x0c\r "
DELIM = b"()<>[]{}/%"
MAX_SPAN = 4000  # guard against pathological content streams

STD_WIDTHS = {
    "times": [250, 333, 408, 500, 500, 833, 778, 333, 333, 333, 500, 564, 250, 333, 250, 278]
             + [500] * 10
             + [278, 278, 564, 564, 564, 444, 921, 722, 667, 667, 722, 611, 556, 722, 722, 333,
                389, 722, 611, 889, 722, 722, 556, 722, 667, 556, 611, 722, 722, 944, 722, 722,
                611, 333, 278, 333, 469, 500, 333, 444, 500, 444, 500, 444, 333, 500, 500, 278,
                278, 500, 278, 778, 500, 500, 500, 500, 333, 389, 278, 500, 500, 722, 500, 500,
                444, 480, 200, 480, 541],
    "times bold": [250, 333, 555, 500, 500, 1000, 833, 333, 333, 333, 500, 570, 250, 333, 250, 278]
                  + [500] * 10
                  + [333, 333, 570, 570, 570, 500, 930, 722, 667, 722, 722, 667, 611, 778, 778,
                     389, 500, 778, 667, 944, 722, 778, 611, 778, 722, 556, 667, 722, 722, 1000,
                     722, 722, 667, 333, 278, 333, 581, 500, 333, 500, 556, 444, 556, 444, 333,
                     500, 556, 278, 333, 556, 278, 833, 556, 500, 556, 556, 444, 389, 333, 556,
                     500, 722, 500, 500, 444, 394, 220, 394, 520],
    "helvetica": [278, 278, 355, 556, 556, 889, 667, 222, 333, 333, 389, 584, 278, 333, 278, 278]
                 + [556] * 10
                 + [278, 278, 584, 584, 584, 556, 1015, 667, 667, 722, 722, 667, 611, 778, 722,
                    278, 500, 667, 556, 833, 722, 778, 667, 778, 722, 667, 611, 722, 667, 944,
                    667, 667, 611, 278, 278, 278, 469, 556, 222, 556, 556, 500, 556, 556, 278,
                    556, 556, 222, 222, 500, 222, 833, 556, 556, 556, 556, 333, 500, 278, 556,
                    500, 722, 500, 500, 500, 334, 260, 334, 584],
    "helvetica bold": [278, 333, 474, 556, 556, 889, 722, 278, 333, 333, 389, 584, 278, 333, 278, 278]
                      + [556] * 10
                      + [333, 333, 584, 584, 584, 611, 975, 722, 667, 722, 722, 667, 611, 778, 722,
                         278, 556, 722, 611, 833, 722, 778, 667, 778, 722, 667, 611, 722, 667,
                         944, 667, 667, 611, 333, 278, 333, 584, 556, 278, 556, 611, 556, 611,
                         556, 333, 611, 611, 278, 278, 556, 278, 889, 611, 611, 611, 611, 389,
                         556, 333, 611, 556, 778, 556, 556, 500, 389, 280, 389, 584],
}


class PdfTextError(Exception):
    pass


def std_width(basefont, code):
    name = (basefont or "").lower()
    for key, widths in STD_WIDTHS.items():
        if key in name:
            idx = code - 32
            if 0 <= idx < len(widths):
                return float(widths[idx])
            break
    if "courier" in name or "mono" in name:
        return 600.0
    return 500.0


def skip_ws(data, i):
    n = len(data)
    while i < n:
        c = data[i]
        if c in WS:
            i += 1
        elif c == 0x25:  # comment
            j = data.find(b"\n", i)
            i = n if j < 0 else j + 1
        else:
            break
    return i


class Lexer(object):
    """Tokenizer for PDF content streams and object bodies."""

    def __init__(self, data):
        self.d = data
        self.i = 0

    def tokens(self):
        d, n = self.d, len(self.d)
        while True:
            self.i = skip_ws(d, self.i)
            if self.i >= n:
                return
            c = d[self.i]
            if c == 0x28:
                yield self._string()
            elif c == 0x3C:
                if d[self.i:self.i + 2] == b"<<":
                    self.i += 2
                    yield ("<<", None)
                else:
                    yield self._hex()
            elif c == 0x3E and d[self.i:self.i + 2] == b">>":
                self.i += 2
                yield (">>", None)
            elif c == 0x5B:
                self.i += 1
                yield ("[", None)
            elif c == 0x5D:
                self.i += 1
                yield ("]", None)
            elif c == 0x2F:
                j = self.i + 1
                while j < n and d[j] not in WS and d[j] not in DELIM:
                    j += 1
                name = d[self.i + 1:j].decode("latin-1")
                self.i = j
                yield ("/", name)
            else:
                j = self.i
                while j < n and d[j] not in WS and d[j] not in DELIM:
                    j += 1
                if j == self.i:
                    self.i += 1
                    continue
                tok = d[self.i:j].decode("latin-1")
                self.i = j
                try:
                    yield ("n", float(tok))
                except ValueError:
                    yield ("op", tok)

    def _string(self):
        d, n = self.d, len(self.d)
        i = self.i + 1
        depth = 1
        out = bytearray()
        escapes = {0x6E: 10, 0x72: 13, 0x74: 9, 0x62: 8, 0x66: 12, 0x28: 40, 0x29: 41, 0x5C: 92}
        while i < n:
            c = d[i]
            if c == 0x5C:
                i += 1
                if i >= n:
                    break
                e = d[i]
                if e in escapes:
                    out.append(escapes[e])
                    i += 1
                elif 0x30 <= e <= 0x37:
                    octd = bytearray()
                    k = 0
                    while k < 3 and i < n and 0x30 <= d[i] <= 0x37:
                        octd.append(d[i])
                        i += 1
                        k += 1
                    out.append(int(octd, 8) & 0xFF)
                elif e in (10, 13):
                    i += 1
                    if e == 13 and i < n and d[i] == 10:
                        i += 1
                else:
                    out.append(e)
                    i += 1
            elif c == 0x28:
                depth += 1
                out.append(c)
                i += 1
            elif c == 0x29:
                depth -= 1
                if depth == 0:
                    i += 1
                    break
                out.append(c)
                i += 1
            else:
                out.append(c)
                i += 1
        self.i = i
        return ("s", bytes(out))

    def _hex(self):
        d = self.d
        j = d.find(b">", self.i + 1)
        if j < 0:
            j = len(d)
        raw = re.sub(rb"[^0-9A-Fa-f]", b"", d[self.i + 1:j])
        if len(raw) % 2:
            raw += b"0"
        self.i = j + 1
        return ("s", bytes.fromhex(raw.decode("ascii")))


def parse_objects(data):
    objs = {}
    for m in re.finditer(rb"(?<![0-9])(\d+)\s+(\d+)\s+obj\b", data):
        start = m.end()
        end = data.find(b"endobj", start)
        if end < 0:
            end = len(data)
        objs[int(m.group(1))] = data[start:end]
    return objs


def stream_bytes(body):
    m = re.search(rb"stream\r?\n", body)
    if not m:
        return None
    start = m.end()
    end = body.find(b"endstream", start)
    if end < 0:
        return None
    return body[start:end].rstrip(b"\r\n")


def inflate(raw, head, warnings=None):
    if b"/FlateDecode" in head:
        try:
            return zlib.decompress(raw)
        except zlib.error:
            try:
                return zlib.decompressobj().decompress(raw)
            except Exception:
                if warnings is not None:
                    warnings.append("flate_decode_failed")
                return b""
    if b"/Filter" in head:
        if warnings is not None:
            for f in re.findall(rb"/(\w+)Decode", head):
                warnings.append("unsupported_filter:%s" % f.decode("latin-1"))
        return b""
    return raw


def obj_stream(objs, warnings):
    extra = {}
    for num, body in list(objs.items()):
        head = body[:body.find(b"stream")] if b"stream" in body else body
        if b"/ObjStm" not in head:
            continue
        try:
            n = int(re.search(rb"/N\s+(\d+)", head).group(1))
            first = int(re.search(rb"/First\s+(\d+)", head).group(1))
            raw = stream_bytes(body)
            if raw is None:
                continue
            data = inflate(raw, head, warnings)
            nums = [int(x) for x in data[:first].split()]
            pairs = [(nums[k], nums[k + 1]) for k in range(0, min(len(nums), 2 * n), 2)]
            for idx, (k, off) in enumerate(pairs):
                s = first + off
                e = first + pairs[idx + 1][1] if idx + 1 < len(pairs) else len(data)
                extra[k] = data[s:e]
        except Exception:
            warnings.append("objstm_parse_failed")
    for k, v in extra.items():
        objs.setdefault(k, v)
    return objs


def token_dict(body):
    """Parse the first <<...>> into {key: raw value bytes}, top level only."""
    if body is None:
        return {}
    i = body.find(b"<<")
    if i < 0:
        return {}
    depth, j = 0, i
    while j < len(body):
        if body[j:j + 2] == b"<<":
            depth += 1
            j += 2
        elif body[j:j + 2] == b">>":
            depth -= 1
            if depth == 0:
                j += 2
                break
            j += 2
        else:
            j += 1
    inner = body[i + 2:j - 2]
    out = {}
    depth, k = 0, 0
    while k < len(inner):
        if inner[k:k + 2] == b"<<":
            depth += 1
            k += 2
        elif inner[k:k + 2] == b">>":
            depth -= 1
            k += 2
        elif inner[k] == 0x2F and depth == 0:
            m = re.match(rb"/([^\s/<>\[\]]+)", inner[k:])
            if not m:
                k += 1
                continue
            key = m.group(1).decode("latin-1")
            k += m.end()
            while k < len(inner) and inner[k] in WS:
                k += 1
            if inner[k:k + 2] == b"<<":
                d2, s2, k = 1, k + 2, k + 2
                while k < len(inner) and d2:
                    if inner[k:k + 2] == b"<<":
                        d2 += 1
                        k += 2
                    elif inner[k:k + 2] == b">>":
                        d2 -= 1
                        k += 2
                    else:
                        k += 1
                out[key] = inner[s2:k - 2]
            elif inner[k:k + 1] == b"[":
                d2, s2, k = 1, k + 1, k + 1
                while k < len(inner) and d2:
                    if inner[k:k + 1] == b"[":
                        d2 += 1
                        k += 1
                    elif inner[k:k + 1] == b"]":
                        d2 -= 1
                        k += 1
                    else:
                        k += 1
                out[key] = inner[s2:k - 1]
            else:
                m2 = re.match(rb"(\d+\s+\d+\s+R|/[^\s/<>\[\]]+|[^\s/<>\[\]]+)", inner[k:])
                if m2:
                    out[key] = m2.group(1)
                    k += m2.end()
                else:
                    k += 1
        else:
            k += 1
    return out


def as_dict(raw):
    if raw is None:
        return {}
    if isinstance(raw, str):
        raw = raw.encode("latin-1")
    raw = raw.strip()
    if raw.startswith(b"<<"):
        return token_dict(raw)
    return token_dict(b"<< " + raw + b" >>")


def deref(objs, value):
    if value is None:
        return None
    m = re.match(rb"(\d+)\s+\d+\s+R", value.strip())
    if m:
        return objs.get(int(m.group(1)), b"")
    return value


AGL = {
    "space": " ", "exclam": "!", "quotedbl": '"', "numbersign": "#", "dollar": "$", "percent": "%",
    "ampersand": "&", "quoteright": "\u2019", "quotesingle": "'", "parenleft": "(", "parenright": ")",
    "asterisk": "*", "plus": "+", "comma": ",", "hyphen": "-", "period": ".", "slash": "/",
    "zero": "0", "one": "1", "two": "2", "three": "3", "four": "4", "five": "5", "six": "6",
    "seven": "7", "eight": "8", "nine": "9", "colon": ":", "semicolon": ";", "less": "<",
    "equal": "=", "greater": ">", "question": "?", "at": "@", "bracketleft": "[",
    "backslash": "\\", "bracketright": "]", "asciicircum": "^", "underscore": "_",
    "quoteleft": "\u2018", "braceleft": "{", "bar": "|", "braceright": "}", "asciitilde": "~",
    "endash": "\u2013", "emdash": "\u2014", "bullet": "\u2022", "quotedblleft": "\u201c",
    "quotedblright": "\u201d", "quotedblbase": "\u201e", "quotesinglbase": "\u201a",
    "ellipsis": "\u2026", "dagger": "\u2020", "daggerdbl": "\u2021", "section": "\u00a7",
    "paragraph": "\u00b6", "copyright": "\u00a9", "registered": "\u00ae", "trademark": "\u2122",
    "degree": "\u00b0", "plusminus": "\u00b1", "multiply": "\u00d7", "divide": "\u00f7",
    "minus": "\u2212", "fi": "fi", "fl": "fl", "ff": "ff", "ffi": "ffi", "ffl": "ffl",
    "germandbls": "\u00df", "ae": "\u00e6", "AE": "\u00c6", "oe": "\u0153", "OE": "\u0152",
    "oslash": "\u00f8", "Oslash": "\u00d8", "dotlessi": "\u0131", "nbspace": " ",
    "sfthyphen": "\u00ad", "Gamma": "\u0393", "Delta": "\u0394", "Theta": "\u0398",
    "Lambda": "\u039b", "Pi": "\u03a0", "Sigma": "\u03a3", "Phi": "\u03a6", "Psi": "\u03a8",
    "Omega": "\u03a9", "alpha": "\u03b1", "beta": "\u03b2", "gamma": "\u03b3", "delta": "\u03b4",
    "epsilon": "\u03b5", "theta": "\u03b8", "lambda": "\u03bb", "mu": "\u03bc", "pi": "\u03c0",
    "sigma": "\u03c3", "tau": "\u03c4", "phi": "\u03c6", "omega": "\u03c9",
}

ENCODINGS = {"cp1252": "cp1252", "mac_roman": "mac_roman"}


def glyph_unicode(name):
    if name in AGL:
        return AGL[name]
    if len(name) == 1:
        return name
    m = re.match(r"uni([0-9A-Fa-f]{4})", name)
    if m:
        return chr(int(m.group(1), 16))
    m = re.match(r"u([0-9A-Fa-f]{4,6})", name)
    if m:
        return chr(int(m.group(1), 16))
    base = name.split(".")[0]
    return AGL.get(base, "")


def utf16_hex(h):
    try:
        return bytes.fromhex(h).decode("utf-16-be", "replace")
    except Exception:
        return ""


def parse_cmap(data):
    text = data.decode("latin-1", "replace")
    mapping, maxlen = {}, 0
    for m in re.finditer(r"begincodespacerange(.*?)endcodespacerange", text, re.S):
        for h in re.findall(r"<([0-9A-Fa-f]+)>", m.group(1)):
            maxlen = max(maxlen, len(h))
    for m in re.finditer(r"beginbfchar(.*?)endbfchar", text, re.S):
        for src, dst in re.findall(r"<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>", m.group(1)):
            maxlen = max(maxlen, len(src))
            mapping[int(src, 16)] = utf16_hex(dst)
    for m in re.finditer(r"beginbfrange(.*?)endbfrange", text, re.S):
        for lo, hi, rest in re.findall(
                r"<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>\s*(<[0-9A-Fa-f]+>|\[[^\]]*\])", m.group(1)):
            lo_i, hi_i = int(lo, 16), int(hi, 16)
            maxlen = max(maxlen, len(lo))
            if rest.startswith("["):
                for k, item in enumerate(re.findall(r"<([0-9A-Fa-f]+)>", rest)):
                    if lo_i + k <= hi_i:
                        mapping[lo_i + k] = utf16_hex(item)
            else:
                base = int(rest.strip("<>"), 16)
                for k in range(hi_i - lo_i + 1):
                    mapping[lo_i + k] = utf16_hex("%04X" % (base + k))
    return (2 if maxlen > 2 else 1), mapping


class Font(object):
    def __init__(self, objs, fbody, warnings):
        self.d = token_dict(fbody)
        self.map, self.code_len = {}, 1
        tb = deref(objs, self.d.get("ToUnicode"))
        if tb:
            raw = stream_bytes(tb)
            head = tb[:tb.find(b"stream")] if b"stream" in tb else tb
            if raw is not None:
                self.code_len, self.map = parse_cmap(inflate(raw, head, warnings))
        self.base_enc = "cp1252"
        self.diffs = {}
        eb = deref(objs, self.d.get("Encoding"))
        if eb is not None:
            ed = as_dict(eb)
            if b"MacRoman" in (ed.get("BaseEncoding") or b""):
                self.base_enc = "mac_roman"
            diff = ed.get("Differences")
            if diff:
                code = 0
                for name, num in re.findall(rb"/([^\s/\[\]<>]+)|(\d+)", diff):
                    if num:
                        code = int(num)
                    else:
                        self.diffs[code] = glyph_unicode(name.decode("latin-1"))
                        code += 1
        if not self.map:
            for code in range(256):
                if code in self.diffs:
                    self.map[code] = self.diffs[code]
                else:
                    try:
                        self.map[code] = bytes([code]).decode(ENCODINGS.get(self.base_enc, "cp1252"))
                    except Exception:
                        self.map[code] = ""
        self.widths, self.first = {}, 0
        w = deref(objs, self.d.get("Widths"))
        if w:
            nums = [float(x) for x in re.findall(rb"-?\d+(?:\.\d+)?", w)]
            try:
                self.first = int(self.d.get("FirstChar") or 0)
            except Exception:
                self.first = 0
            for k, val in enumerate(nums):
                self.widths[self.first + k] = val
        self.basefont = (self.d.get("BaseFont") or b"").decode("latin-1")

    def decode(self, raw):
        if self.code_len == 2:
            return "".join(self.map.get((raw[k] << 8) | raw[k + 1], "")
                           for k in range(0, len(raw) - 1, 2))
        return "".join(self.map.get(c, "") for c in raw)

    def width(self, code):
        if self.widths.get(code):
            return self.widths[code]
        return std_width(self.basefont, code)

    def advance(self, text, raw, size, hscale, tc, tw):
        if len(text) == len(raw):
            total = 0.0
            for code in raw:
                w = self.width(code) * 0.001 * size * hscale + tc
                if code == 32:
                    w += tw
                total += w
            return total
        return len(text) * 0.5 * size * hscale + len(text) * tc


def mat_mul(a, b):
    return (
        a[0] * b[0] + a[1] * b[2], a[0] * b[1] + a[1] * b[3],
        a[2] * b[0] + a[3] * b[2], a[2] * b[1] + a[3] * b[3],
        a[4] * b[0] + a[5] * b[2] + b[4], a[4] * b[1] + a[5] * b[3] + b[5],
    )


def pages_of(objs):
    root = None
    for num, body in objs.items():
        if re.search(rb"/Type\s*/Catalog", body[:600]):
            root = num
            break
    pages = []
    if root is not None:
        queue = [token_dict(objs[root]).get("Pages")]
        seen = set()
        while queue:
            v = queue.pop(0)
            if not v:
                continue
            m = re.match(rb"(\d+)\s+\d+\s+R", v.strip())
            if not m:
                continue
            num = int(m.group(1))
            if num in seen:
                continue
            seen.add(num)
            body = objs.get(num, b"")
            if re.search(rb"/Type\s*/Page\b", body[:500]):
                pages.append(num)
            else:
                kids = token_dict(body).get("Kids") or b""
                queue.extend(mm.group(0) for mm in re.finditer(rb"(\d+)\s+\d+\s+R", kids))
    if not pages:
        for num, body in objs.items():
            if re.search(rb"/Type\s*/Page\b", body[:500]):
                pages.append(num)
        pages.sort()
    return pages


def page_content(objs, pnum, warnings):
    d = token_dict(objs.get(pnum, b""))
    vals = []
    for m in re.finditer(rb"(\d+)\s+\d+\s+R", d.get("Contents") or b""):
        body = objs.get(int(m.group(1)), b"")
        raw = stream_bytes(body)
        head = body[:body.find(b"stream")] if b"stream" in body else body
        if raw is not None:
            vals.append(inflate(raw, head, warnings))
    return b"\n".join(vals)


def page_fonts(objs, pnum, warnings):
    d = token_dict(objs.get(pnum, b""))
    rd = as_dict(deref(objs, d.get("Resources")))
    fonts = {}
    fd = as_dict(deref(objs, rd.get("Font")))
    for name, val in fd.items():
        target = deref(objs, val)
        if isinstance(target, bytes):
            fonts[name] = Font(objs, target, warnings)
    return fonts


def extract_page_spans(content, fonts, warnings):
    spans = []
    tm = tlm = (1, 0, 0, 1, 0, 0)
    ctm = (1, 0, 0, 1, 0, 0)
    stack = []
    leading = tc = tw = 0.0
    hscale = 1.0
    rise = 0.0
    font = None
    size = 10.0
    operands = []

    def emit(text, adv):
        m = mat_mul(tm, ctm)
        eff = abs(size * (m[3] if m[3] else 1)) or size
        if text.strip() and len(spans) < MAX_SPAN:
            spans.append({"x": m[4], "y": m[5] + rise, "size": eff,
                          "text": text, "w": max(adv, 0.1), "seq": len(spans)})

    for kind, val in Lexer(content).tokens():
        if kind in ("s", "n", "/", "[", "]", "<<", ">>"):
            operands.append((kind, val))
            continue
        op = val
        nums = [v for k, v in operands if k == "n"]
        try:
            if op == "q":
                stack.append((ctm, font, size, leading, tc, tw, hscale, rise))
            elif op == "Q":
                if stack:
                    ctm, font, size, leading, tc, tw, hscale, rise = stack.pop()
            elif op == "cm" and len(nums) >= 6:
                ctm = mat_mul(tuple(nums[-6:]), ctm)
            elif op == "BT":
                tm = tlm = (1, 0, 0, 1, 0, 0)
            elif op == "Tf":
                names = [v for k, v in operands if k == "/"]
                if names:
                    font = fonts.get(names[-1])
                if nums:
                    size = abs(nums[-1]) or size
            elif op == "Tm" and len(nums) >= 6:
                tm = tlm = tuple(nums[-6:])
            elif op in ("Td", "TD") and len(nums) >= 2:
                if op == "TD":
                    leading = -nums[-1]
                tm = tlm = mat_mul((1, 0, 0, 1, nums[-2], nums[-1]), tlm)
            elif op == "T*":
                tm = tlm = mat_mul((1, 0, 0, 1, 0, -leading), tlm)
            elif op == "TL" and nums:
                leading = nums[-1]
            elif op == "Tc" and nums:
                tc = nums[-1]
            elif op == "Tw" and nums:
                tw = nums[-1]
            elif op == "Tz" and nums:
                hscale = nums[-1] / 100.0
            elif op == "Ts" and nums:
                rise = nums[-1]
            elif op in ("Tj", "'", '"'):
                if op == "'":
                    tm = tlm = mat_mul((1, 0, 0, 1, 0, -leading), tlm)
                elif op == '"':
                    if len(nums) >= 2:
                        tw, tc = nums[-2], nums[-1]
                    tm = tlm = mat_mul((1, 0, 0, 1, 0, -leading), tlm)
                raw = b"".join(v for k, v in operands if k == "s")
                text = font.decode(raw) if font else raw.decode("latin-1", "replace")
                adv = font.advance(text, raw, size, hscale, tc, tw) if font else len(text) * size * 0.5
                emit(text, adv)
                tm = mat_mul((1, 0, 0, 1, adv, 0), tm)
            elif op == "TJ":
                arr, depth = [], 0
                for k, v in operands:
                    if k == "[":
                        depth, arr = depth + 1, []
                    elif k == "]":
                        depth -= 1
                        break
                    elif depth > 0:
                        arr.append((k, v))
                buf, adv = "", 0.0
                for k, v in arr:
                    if k == "s":
                        text = font.decode(v) if font else v.decode("latin-1", "replace")
                        buf += text
                        adv += (font.advance(text, v, size, hscale, tc, tw)
                                if font else len(text) * size * 0.5)
                    elif k == "n":
                        adj = -v / 1000.0 * size * hscale
                        if adj > 0.16 * size and buf and not buf.endswith(" "):
                            buf += " "
                        adv += adj
                emit(buf, adv)
                tm = mat_mul((1, 0, 0, 1, adv, 0), tm)
            elif op == "Do":
                warnings.append("form_xobject_skipped")
        except Exception:
            warnings.append("content_token_skipped")
        operands = []
    return spans


def group_lines(spans):
    if not spans:
        return []
    spans.sort(key=lambda s: (-round(s["y"], 1), s["x"], s["seq"]))
    dedup = []
    for sp in spans:
        if any(abs(sp["y"] - q["y"]) < 1.0 and abs(sp["x"] - q["x"]) < 1.0 and sp["text"] == q["text"]
               for q in dedup[-6:]):
            continue
        dedup.append(sp)
    lines = []
    for sp in dedup:
        for line in lines[-3:]:
            if abs(line["y"] - sp["y"]) <= max(1.4, 0.45 * sp["size"]):
                line["spans"].append(sp)
                break
        else:
            lines.append({"y": sp["y"], "spans": [sp]})
    out = []
    for line in lines:
        parts = sorted(line["spans"], key=lambda s: (s["x"], s["seq"]))
        buf, prev_end = "", None
        for p in parts:
            if prev_end is not None:
                gap = p["x"] - prev_end
                if gap > 0.55 * max(6.0, p["size"]) and buf and not buf.endswith(" "):
                    buf += "   "  # wide gap: keep table columns separable
                elif gap > 0.16 * max(6.0, p["size"]) and buf and not buf.endswith(" "):
                    buf += " "
            buf += p["text"]
            prev_end = p["x"] + p["w"]
        buf = re.sub(r"[ \t]+", lambda m: m.group(0) if len(m.group(0)) > 1 else " ", buf).strip()
        if buf:
            out.append({"y": line["y"], "x0": min(s["x"] for s in parts),
                        "x1": max(s["x"] + s["w"] for s in parts), "text": buf})
    out.sort(key=lambda l: -l["y"])
    return out


def columnize(lines, width):
    if len(lines) < 8:
        return [l["text"] for l in lines]
    mid = width / 2.0
    right = [l for l in lines if l["x0"] > mid * 0.95]
    left = [l for l in lines if l["x1"] < mid * 1.05]
    if len(right) < 5 or len(left) < 5 or len(right) + len(left) < 0.7 * len(lines):
        return [l["text"] for l in lines]
    right_ids = set(id(l) for l in right)
    left_ids = set(id(l) for l in left)
    full = [l for l in lines if id(l) not in right_ids and id(l) not in left_ids]
    y_right = [l["y"] for l in right]
    y_left = [l["y"] for l in left]
    top = [l for l in full if l["y"] >= max(y_right)]
    bottom = [l for l in full if l["y"] <= min(y_left)]
    middle = [l for l in full if l not in top and l not in bottom]
    out = [l["text"] for l in top]
    out += [l["text"] for l in left]
    out += [l["text"] for l in middle]
    out += [l["text"] for l in right]
    out += [l["text"] for l in bottom]
    return out


def extract(path, max_pages=60):
    with open(path, "rb") as fh:
        data = fh.read()
    if b"/Encrypt" in data[:200000] and re.search(rb"/Encrypt\s+\d+\s+\d+\s+R", data):
        return {"text": "", "pages_total": 0, "pages_used": 0, "chars": 0,
                "chars_per_page": 0, "truncated": False, "encrypted": True,
                "warnings": ["encrypted_pdf"]}
    warnings = []
    objs = obj_stream(parse_objects(data), warnings)
    if not objs:
        raise PdfTextError("no indirect objects found")
    page_nums = pages_of(objs)
    if not page_nums:
        raise PdfTextError("no page objects found")
    used = page_nums[:max_pages]
    texts = []
    for pnum in used:
        d = token_dict(objs.get(pnum, b""))
        width = 612.0
        mb = d.get("MediaBox")
        if mb:
            box = [float(x) for x in re.findall(rb"-?\d+(?:\.\d+)?", mb)]
            if len(box) >= 4:
                width = abs(box[2] - box[0]) or width
        content = page_content(objs, pnum, warnings)
        spans = extract_page_spans(content, page_fonts(objs, pnum, warnings), warnings)
        texts.append("\n".join(columnize(group_lines(spans), width)))
    text = "\f".join(texts)
    uniq = sorted(set(warnings))
    chars = len(text.strip())
    return {
        "text": text,
        "pages_total": len(page_nums),
        "pages_used": len(used),
        "chars": chars,
        "chars_per_page": round(chars / max(1, len(used)), 1),
        "truncated": len(used) < len(page_nums),
        "encrypted": False,
        "warnings": uniq,
    }
