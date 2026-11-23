#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""selfcheck.py - independent verification of a finished transform package.

Checks, from the files on disk (not from build_transform's in-memory state):
  * result.json parses and carries every contract key from case.json
  * required deliverables exist, are non-empty and match declared sha256
  * every number in transform.md is in the sources or has a declared basis
  * every quote marked verified is actually found in the sources
  * removed / omitted material is logged with reason and risk
  * readability metrics recompute from transform.md
  * placeholders, status/issue consistency, length limits

Usage:
  python3 scripts/selfcheck.py --case /input/case.json --out /app/output \
      --sources /app/work/sources.json
Exit code 0 when no hard failure, 1 otherwise. checks.json is always written.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import re
import sys

GLOSSARY_HEADING = "## 术语与缩写"
NUM_RE = re.compile(r"(?<![\w.])(\d{1,3}(?:[,，]\d{3})+|\d+)(\.\d+)?\s*(%|‰|％)?")
COMMON_ACRONYMS = {
    "PDF", "DOI", "URL", "HTML", "XML", "JSON", "CSV", "API", "GPU", "CPU",
    "RAM", "OS", "USA", "EU", "UK", "UN", "WHO", "DNA", "RNA", "AI", "II",
    "III", "IV", "VI", "VII", "VIII", "IX", "XI", "XII", "OK", "ID",
}
PLACEHOLDER_RE = re.compile(
    r"\b(?:TODO|TBD|FIXME|PLACEHOLDER)\b|lorem ipsum|\{\{[^}]+\}\}|"
    r"\[待[^\]]*\]|（待补）|待填写|待补充|此处省略|\bXXX\b", re.I)


# ----------------------------------------------------------------------- utils
def canon(text):
    s = text or ""
    for a, b in (("‘", "'"), ("’", "'"), ("“", '"'), ("”", '"'),
                 ("–", "-"), ("—", "-"), ("−", "-"), ("\u00a0", " "), ("\u3000", " ")):
        s = s.replace(a, b)
    s = re.sub(r"(?<=[A-Za-z])-\s*\n\s*(?=[a-z])", "", s)
    return re.sub(r"\s+", " ", s).strip()


def squash(text):
    return re.sub(r"\s+", "", canon(text)).lower()


def tokens(text):
    s = canon(text).lower()
    latin = re.findall(r"[a-z0-9]+", s)
    cjk = re.findall(r"[\u4e00-\u9fff]", s)
    grams = [cjk[i] + cjk[i + 1] for i in range(len(cjk) - 1)]
    return set(latin) | set(cjk) | set(grams)


def number_tokens(text):
    cleaned = re.sub(r"https?://\S+|doi:\S+|\[\d+(?:[-,–]\d+)*\]", " ", text or "")
    out = []
    for m in NUM_RE.finditer(cleaned):
        token = (m.group(1) + (m.group(2) or "")).replace(",", "").replace("，", "")
        if m.group(3):
            token += "%"
        out.append(token)
    return out


def digits_of(token):
    return re.sub(r"[^\d.]", "", token or "")


def body_numbers(body):
    kept = []
    for line in (body or "").split("\n"):
        if line.lstrip().startswith("#"):
            heading = line.lstrip("# ").strip()
            if re.match(r"^(?:\d+(?:\.\d+)*[.、)]?|第[一二三四五六七八九十百零〇\d]+[章节節部分篇])$",
                        heading):
                continue
            kept.append(heading)
            continue
        line = re.sub(r"^\s*(?:\d+[.)、]|[-*•])\s+", "", line)
        kept.append(line)
    return number_tokens("\n".join(kept))


def split_sentences(text):
    parts = re.split(r"(?<=[。！？!?])|(?<=\.)(?=\s+[A-Z\"“])|\n{2,}", text or "")
    return [p.strip() for p in parts if p and p.strip()]


def load_json(path, default=None):
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:  # noqa: BLE001
        return default


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def split_body(text):
    idx = text.find("\n" + GLOSSARY_HEADING)
    if idx >= 0:
        return text[:idx].rstrip() + "\n"
    if text.lstrip().startswith(GLOSSARY_HEADING):
        return ""
    return text


def compute_metrics(body, glossary):
    chars = len(re.sub(r"\s+", "", body))
    cjk = len(re.findall(r"[\u4e00-\u9fff]", body))
    latin_words = re.findall(r"[A-Za-z][A-Za-z'\-]*", body)
    words = cjk + len(latin_words)
    sents = [s for s in split_sentences(body) if canon(s)]
    n_sent = len(sents)
    lens = [len(re.sub(r"\s+", "", s)) for s in sents]
    avg = (sum(lens) / float(n_sent)) if n_sent else 0.0
    long_ratio = (sum(1 for l in lens if l > 60) / float(n_sent)) if n_sent else 0.0
    flesch = None
    if latin_words and len(latin_words) >= 0.5 * max(1, words):
        syl = sum(max(1, len(re.findall(r"[aeiouy]+", w.lower()))) for w in latin_words)
        flesch = round(206.835 - 1.015 * (len(latin_words) / float(max(1, n_sent)))
                       - 84.6 * (syl / float(max(1, len(latin_words)))), 1)
    jargon = 0
    for g in glossary:
        term = g.get("term") or ""
        if not term:
            continue
        pat = (re.escape(term) if re.search(r"[\u4e00-\u9fff]", term)
               else r"(?<![A-Za-z])" + re.escape(term) + r"(?![A-Za-z])")
        jargon += len(re.findall(pat, body, re.I))
    return {
        "chars": chars, "words": words, "cjk_chars": cjk,
        "latin_words": len(latin_words), "sentences": n_sent,
        "avg_sentence_chars": round(avg, 1),
        "long_sentence_ratio": round(long_ratio, 3),
        "jargon_occurrences": jargon,
        "jargon_per_1000_chars": round(jargon / chars * 1000, 1) if chars else 0.0,
        "flesch_reading_ease": flesch,
    }


def contract_keys(case):
    oc = case.get("output_contract") if isinstance(case, dict) else None
    if oc is None and isinstance(case, dict):
        for alt in ("outputContract", "contract", "required_outputs"):
            if alt in case:
                oc = case.get(alt)
                break
    names = []
    if isinstance(oc, dict):
        for key in oc.keys():
            if key in ("required", "fields", "properties") and isinstance(oc[key], (list, dict)):
                continue
            names.append(key)
        for key in ("required", "fields", "properties"):
            val = oc.get(key)
            if isinstance(val, list):
                for item in val:
                    if isinstance(item, str):
                        names.append(item)
                    elif isinstance(item, dict):
                        n = item.get("name") or item.get("field") or item.get("key") or item.get("id")
                        if n:
                            names.append(n)
            elif isinstance(val, dict):
                names.extend(list(val.keys()))
    elif isinstance(oc, list):
        for item in oc:
            if isinstance(item, str):
                names.append(item)
            elif isinstance(item, dict):
                n = item.get("name") or item.get("field") or item.get("key") or item.get("id")
                if n:
                    names.append(n)
    seen, out = set(), []
    for n in names:
        if isinstance(n, str) and n.strip() and n not in seen:
            seen.add(n)
            out.append(n)
    return out


# ---------------------------------------------------------------------- checks
class Checker:
    def __init__(self):
        self.checks = []

    def add(self, name, ok, detail, severity="hard"):
        self.checks.append({"name": name, "ok": bool(ok), "severity": severity,
                            "detail": detail})

    def hard_failures(self):
        return [c for c in self.checks if not c["ok"] and c["severity"] == "hard"]

    def warnings(self):
        return [c for c in self.checks if not c["ok"] and c["severity"] == "warn"]


def load_sources(path):
    data = load_json(path, None)
    if not isinstance(data, dict):
        return None, [], ""
    paragraphs, texts = [], []
    for d in data.get("documents") or []:
        texts.append(d.get("text") or "")
        for p in d.get("paragraphs") or []:
            text = p.get("text") or ""
            if text.strip():
                paragraphs.append({"anchor": p.get("anchor") or "", "text": text,
                                   "sq": squash(text)})
    return data, paragraphs, "\n".join(texts)


def main(argv=None):
    ap = argparse.ArgumentParser(description="Verify a finished transform package")
    ap.add_argument("--case", default="/input/case.json")
    ap.add_argument("--out", default="/app/output")
    ap.add_argument("--sources", default="/app/work/sources.json")
    args = ap.parse_args(argv)

    chk = Checker()
    out = args.out
    result_path = os.path.join(out, "result.json")
    result = load_json(result_path, None)
    chk.add("result_json_parses", isinstance(result, dict),
            "result.json 可解析" if isinstance(result, dict) else "result.json 缺失或不是 JSON 对象")
    if not isinstance(result, dict):
        result = {}
    case = load_json(args.case, {}) or {}
    if not isinstance(case, dict):
        case = {}

    # --- files
    transform_path = os.path.join(out, "transform.md")
    transform = ""
    if os.path.isfile(transform_path):
        with open(transform_path, encoding="utf-8") as fh:
            transform = fh.read()
    body = split_body(transform)
    chk.add("transform_nonempty", bool(body.strip()), "transform.md 正文非空" if body.strip()
            else "transform.md 缺失或正文为空")
    for name in ("preservation_map.csv", "glossary.csv"):
        path = os.path.join(out, name)
        ok = os.path.isfile(path) and os.path.getsize(path) > 0
        chk.add("file_%s" % name, ok, "%s %s" % (name, "存在且非空" if ok else "缺失或为空"))

    # --- contract
    keys = contract_keys(case)
    if keys:
        missing = [k for k in keys if k not in result]
        nulls = [k for k in keys if result.get(k, None) is None]
        chk.add("contract_keys_present", not missing,
                "契约键齐全" if not missing else "result.json 缺少契约键：%s" % ", ".join(missing))
        chk.add("contract_keys_nonnull", not nulls,
                "契约键均非 null" if not nulls else "契约键为 null：%s" % ", ".join(nulls))
        cf = result.get("contract_fields")
        chk.add("contract_fields_object", isinstance(cf, dict), "contract_fields 为对象")
        if isinstance(cf, dict):
            cf_missing = [k for k in keys if k not in cf]
            mismatch = [k for k in keys if k in cf and k in result and cf[k] != result[k]]
            chk.add("contract_fields_complete", not cf_missing,
                    "contract_fields 覆盖全部契约键" if not cf_missing
                    else "contract_fields 缺少：%s" % ", ".join(cf_missing))
            chk.add("contract_fields_match", not mismatch,
                    "contract_fields 与顶层字段一致" if not mismatch
                    else "不一致：%s" % ", ".join(mismatch))
        if case.get("case_id") or case.get("id"):
            chk.add("case_id_matches", str(result.get("case_id")) == str(case.get("case_id") or case.get("id")),
                    "case_id=%s" % result.get("case_id"))
    else:
        chk.add("contract_declared", False, "case.json 未声明 output_contract", severity="warn")

    # --- sources
    src_data, paragraphs, full_text = load_sources(args.sources)
    chk.add("sources_readable", bool(paragraphs),
            "sources.json 含 %d 个段落" % len(paragraphs) if paragraphs
            else "sources.json 缺失或无段落，无法核对")
    full_sq = squash(full_text)
    src_numbers = set(number_tokens(full_text))
    src_digits = {digits_of(t) for t in src_numbers}

    # --- metrics recompute
    glossary = result.get("glossary") if isinstance(result.get("glossary"), list) else []
    metrics = compute_metrics(body, glossary)
    declared_metrics = result.get("metrics") if isinstance(result.get("metrics"), dict) else {}
    metric_ok = True
    detail = []
    for key in ("chars", "words", "cjk_chars", "latin_words", "sentences"):
        if key in declared_metrics and int(declared_metrics[key]) != metrics[key]:
            metric_ok = False
            detail.append("%s 声明 %s ≠ 复算 %s" % (key, declared_metrics[key], metrics[key]))
    for key in ("avg_sentence_chars", "long_sentence_ratio", "jargon_per_1000_chars"):
        if key in declared_metrics and abs(float(declared_metrics[key]) - metrics[key]) > 0.2:
            metric_ok = False
            detail.append("%s 声明 %s ≠ 复算 %s" % (key, declared_metrics[key], metrics[key]))
    if declared_metrics.get("jargon_occurrences") != metrics["jargon_occurrences"]:
        metric_ok = False
        detail.append("jargon_occurrences 声明 %s ≠ 复算 %s"
                      % (declared_metrics.get("jargon_occurrences"),
                         metrics["jargon_occurrences"]))
    chk.add("metrics_recompute", metric_ok,
            "可读性指标可由 transform.md 复算" if metric_ok else "；".join(detail))

    # --- numbers
    out_tokens = body_numbers(body)
    res_numbers = result.get("numbers") if isinstance(result.get("numbers"), list) else []
    derived = {digits_of(str(n.get("token") or n.get("value") or ""))
               for n in res_numbers if n.get("status") == "derived" and (n.get("basis") or "").strip()}
    unsupported, status_lies = [], []
    for token in out_tokens:
        digs = digits_of(token)
        if token in src_numbers or digs in src_digits:
            continue
        if digs in derived:
            continue
        unsupported.append(token)
    res_by_token = {str(n.get("token")): n for n in res_numbers}
    for token in out_tokens:
        row = res_by_token.get(token)
        if row and row.get("status", "").startswith("verbatim"):
            if digits_of(token) not in src_digits:
                status_lies.append(token)
    chk.add("numbers_traceable", not unsupported,
            "正文 %d 个数值均可在源文或推导依据中找到" % len(out_tokens) if not unsupported
            else "无来源数值：%s" % ", ".join(sorted(set(unsupported))))
    chk.add("numbers_status_truthful", not status_lies,
            "result.numbers 的 verbatim 标记与源文一致" if not status_lies
            else "被标为 verbatim 但源文无此数：%s" % ", ".join(sorted(set(status_lies))))
    declared_tokens = {str(n.get("token")) for n in res_numbers}
    unrecorded = [t for t in out_tokens if t not in declared_tokens
                  and t not in src_numbers and digits_of(t) not in src_digits]
    chk.add("numbers_ledger_complete", not unrecorded,
            "全部无源数值均已登记在 result.numbers" if not unrecorded
            else "未登记的无源数值：%s" % ", ".join(sorted(set(unrecorded))), severity="warn")

    # --- quote verification
    rows = []
    map_path = os.path.join(out, "preservation_map.csv")
    if os.path.isfile(map_path):
        with open(map_path, encoding="utf-8-sig", newline="") as fh:
            rows = list(csv.DictReader(fh))
    claimed_verified = []
    false_claim, understated = [], []
    for r in rows:
        q = r.get("quote") or ""
        if not q:
            continue
        actual = squash(q) in full_sq or any(squash(q) in p["sq"] for p in paragraphs)
        stated = str(r.get("quote_verified")).strip().lower() in ("true", "1", "yes")
        if stated:
            claimed_verified.append(actual)
            if not actual:
                false_claim.append(r.get("claim_id") or "?")
        elif actual:
            understated.append(r.get("claim_id") or "?")
        # output location sanity
        loc = r.get("output_location") or ""
        if stated and loc:
            m = re.match(r"(.+)#p(\d+)$", loc)
            if m:
                excerpt = r.get("output_excerpt") or ""
                if excerpt and squash(excerpt) not in squash(transform):
                    false_claim.append((r.get("claim_id") or "?") + "(location)")
    rate = (sum(1 for x in claimed_verified if x) / float(len(rows))) if rows else 0.0
    chk.add("quotes_verified", not false_claim,
            "preservation_map 中标记为 verified 的引文均命中源文" if not false_claim
            else "标记为 verified 但源文找不到：%s" % ", ".join(map(str, false_claim)))
    if understated:
        chk.add("quotes_understated", False,
                "引文实际可核验但标记为 False：%s" % ", ".join(map(str, understated)),
                severity="warn")
    declared_rate = (result.get("preservation") or {}).get("verification_rate")
    if rows and isinstance(declared_rate, (int, float)):
        chk.add("verification_rate_consistent", abs(float(declared_rate) - rate) <= 0.01,
                "verification_rate 声明 %s，复算 %.3f" % (declared_rate, rate),
                severity="hard" if declared_rate > rate + 0.01 else "warn")
    chk.add("preservation_map_nonempty", bool(rows),
            "preservation_map 含 %d 条 claim" % len(rows) if rows
            else "preservation_map 为空：正文没有可回溯的事实映射")

    # --- removals / omissions
    removals = result.get("removals") if isinstance(result.get("removals"), list) else []
    bad_removals = [str(r.get("removed") or r.get("source_anchor") or "?") for r in removals
                    if not (r.get("reason") or "").strip()]
    bad_risk = [str(r.get("removed") or "?") for r in removals
                if (r.get("risk") or "").lower() not in ("none", "low", "medium", "high")]
    chk.add("removals_have_reason", not bad_removals,
            "删除项均记录了理由" if not bad_removals
            else "删除项缺少理由：%s" % ", ".join(bad_removals))
    chk.add("removals_have_risk", not bad_risk,
            "删除项均给出风险等级" if not bad_risk
            else "删除项风险等级缺失/非法：%s" % ", ".join(bad_risk))
    omissions = result.get("omissions") if isinstance(result.get("omissions"), list) else []
    unlogged = [o for o in omissions if o.get("status") == "unlogged"]
    chk.add("unlogged_omissions", not unlogged,
            "源文遗漏项均已登记" if not unlogged
            else "存在 %d 条未登记遗漏" % len(unlogged),
            severity="hard" if result.get("status") == "success" else "warn")

    # --- placeholders
    found = sorted(set(m.group(0) for m in PLACEHOLDER_RE.finditer(transform)))
    chk.add("no_placeholders", not found,
            "未发现占位符" if not found else "发现占位符：%s" % ", ".join(found))

    # --- length
    target = (result.get("transform") or {}).get("target_length") or {}
    if isinstance(target, dict):
        max_words = target.get("max_words") or target.get("words")
        max_chars = target.get("max_chars") or target.get("chars")
        over = []
        try:
            if max_words and metrics["words"] > float(max_words) * 1.1:
                over.append("词数 %d > 上限 %s 的 110%%" % (metrics["words"], max_words))
            if max_chars and metrics["chars"] > float(max_chars) * 1.1:
                over.append("字符数 %d > 上限 %s 的 110%%" % (metrics["chars"], max_chars))
        except (TypeError, ValueError):
            chk.add("target_length_valid", False, "target_length 数值非法", severity="warn")
        if over:
            chk.add("length_within_limit", False, "；".join(over),
                    severity="hard" if result.get("status") == "success" else "warn")
        else:
            chk.add("length_within_limit", True, "篇幅在上限 110% 以内")

    # --- glossary
    bad_gloss = [g.get("term") or "?" for g in glossary
                 if not (g.get("plain") or "").strip()]
    chk.add("glossary_plain_present", not bad_gloss,
            "术语均有通俗解释" if not bad_gloss
            else "术语缺少解释：%s" % ", ".join(bad_gloss))
    body_abbrevs = set()
    for m in re.finditer(r"(?<![A-Za-z0-9])([a-z]?[A-Z]{2,10})(?![A-Za-z])", body):
        term = m.group(1)
        if len(term) >= 2 and term.upper() not in COMMON_ACRONYMS:
            body_abbrevs.add(term)
    covered = {(g.get("term") or "").lower() for g in glossary}
    for g in glossary:
        for a in g.get("aliases") or []:
            covered.add(str(a).lower())
    unglossed = sorted(t for t in body_abbrevs if t.lower() not in covered)
    chk.add("abbreviations_glossed", not unglossed,
            "正文缩写在术语表或常用白名单内" if not unglossed
            else "未解释缩写：%s" % ", ".join(unglossed), severity="warn")

    # --- deliverables
    deliverables = result.get("deliverables") if isinstance(result.get("deliverables"), list) else []
    bad_deliv = []
    for d in deliverables:
        name = os.path.basename(str(d.get("path") or d.get("name") or ""))
        path = os.path.join(out, name)
        if not name or not os.path.isfile(path):
            bad_deliv.append(name or "?")
            continue
        if d.get("sha256") and sha256_file(path) != d.get("sha256"):
            bad_deliv.append(name + "(sha256)")
        if d.get("bytes") is not None and os.path.getsize(path) != d.get("bytes"):
            bad_deliv.append(name + "(bytes)")
    chk.add("deliverables_match", not bad_deliv,
            "%d 个交付物与实际文件一致" % len(deliverables) if not bad_deliv
            else "交付物不一致：%s" % ", ".join(bad_deliv))

    # --- status consistency
    status = result.get("status")
    issues = result.get("issues") if isinstance(result.get("issues"), list) else []
    errors = [i for i in issues if i.get("severity") == "error"]
    unc = result.get("uncertainty") if isinstance(result.get("uncertainty"), list) else []
    chk.add("status_valid", status in ("success", "partial", "failed"),
            "status=%s" % status)
    if status == "success":
        consistent = not errors and rate >= 0.999 and not unlogged
        chk.add("status_success_consistent", consistent,
                "success 且无 error、引文全验、无未登记遗漏" if consistent
                else "status=success 但有 error/未验引文/未登记遗漏")
        chk.add("success_no_unverified_claims", not [x for x in claimed_verified if not x],
                "success 时不存在未核验 claim" if all(claimed_verified)
                else "success 但存在未核验 claim")
    elif status == "partial":
        chk.add("status_partial_documented", bool(issues or unc),
                "partial 已记录问题或不确定性" if (issues or unc)
                else "partial 但 issues/uncertainty 均为空")
    elif status == "failed":
        chk.add("status_failed_empty", not body.strip(),
                "failed 且正文为空，状态诚实" if not body.strip()
                else "failed 但正文非空，应复核状态", severity="warn")

    # --- write checks.json
    hard = chk.hard_failures()
    warning = chk.warnings()
    payload = {
        "case_id": result.get("case_id") or case.get("case_id") or "unknown",
        "status": status,
        "passed": sum(1 for c in chk.checks if c["ok"]),
        "failed": len(hard),
        "warnings": len(warning),
        "ok": not hard,
        "checks": chk.checks,
        "recomputed": {
            "metrics": metrics,
            "claim_rows": len(rows),
            "verification_rate": round(rate, 4),
            "numbers_in_output": len(out_tokens),
            "unsupported_numbers": sorted(set(unsupported)),
            "omissions_unlogged": len(unlogged),
            "body_sha256": hashlib.sha256(body.encode("utf-8")).hexdigest(),
        },
    }
    os.makedirs(out, exist_ok=True)
    with open(os.path.join(out, "checks.json"), "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=1)
    print(json.dumps({"ok": payload["ok"], "passed": payload["passed"],
                      "failed": len(hard), "warnings": len(warning),
                      "checks": os.path.join(out, "checks.json")}, ensure_ascii=False))
    return 0 if not hard else 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:  # noqa: BLE001
        sys.stderr.write("[selfcheck] %s: %s\n" % (type(exc).__name__, exc))
        try:
            out = "/app/output"
            for i, a in enumerate(sys.argv):
                if a == "--out" and i + 1 < len(sys.argv):
                    out = sys.argv[i + 1]
            os.makedirs(out, exist_ok=True)
            with open(os.path.join(out, "checks.json"), "w", encoding="utf-8") as fh:
                json.dump({"ok": False, "failed": 1,
                           "checks": [{"name": "internal_error", "ok": False,
                                       "severity": "hard", "detail": str(exc)[:300]}]},
                          fh, ensure_ascii=False, indent=1)
        except Exception:  # noqa: BLE001
            pass
        sys.exit(1)
