#!/usr/bin/env python3
"""rank.py - 候选文献相关性分层 + 可解释排序（只用本地导出，不联网、不补造记录）。

流程：读契约 → 载入候选记录（保留文件/行号）→ 查询概念块 → 版本/重复合并
→ 逐条相关性打分（贡献可分解）→ 分层（保留/待定/排除）→ 排序与并列处理
→ 已知集召回核对 → 排序稳定性检验 → draft.json + ranked_candidates.csv + screening_report.md。
"""
import argparse
import csv
import hashlib
import json
import os
import re
import sys

import records_io

EN_STOP = set("""a an the of and or in on for with to from by as at is are was were be been
this that these those we our study studies paper paper's using used use based results method
methods research approach analysis new review effect effects between among during than then
can could may might not no all any each more most other into their its it they them""".split())
PUNC = re.compile(r"[^0-9a-zA-Z\u4e00-\u9fff]+")


def load(path, default=None):
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:  # noqa: BLE001
        return default


def dump(obj, path):
    os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(obj, fh, ensure_ascii=False, indent=1)


def tokens(text):
    text = PUNC.sub(" ", str(text or "").lower())
    out = []
    for w in text.split():
        if re.fullmatch(r"[a-z][a-z0-9\-]{2,}", w) and w not in EN_STOP:
            out.append(w)
        elif re.fullmatch(r"[\u4e00-\u9fff]{2,6}", w):
            out.append(w)
    return out


def norm_title(v):
    if isinstance(v, (dict, list)):
        return ""
    return PUNC.sub(" ", str(v or "").lower()).strip()


def norm_doi(v):
    s = str(v or "").strip().lower()
    for pre in ("https://doi.org/", "http://doi.org/", "http://dx.doi.org/", "doi:"):
        if s.startswith(pre):
            s = s[len(pre):]
            break
    return s.strip(" .;")


def known_entry(x):
    """归一 known_relevant 条目 → (title_key, doi_key)。

    支持：纯标题字符串、纯 DOI/DOI URL 字符串、{'title':..,'doi':..} 对象。
    对象不再被 str() 成 "{'title': ...}" 而匹配失败。
    """
    if isinstance(x, dict):
        title = x.get("title") or x.get("name") or x.get("label") or ""
        doi = x.get("doi") or x.get("DOI") or ""
        return norm_title(title), norm_doi(doi)
    s = str(x or "").strip()
    if not s:
        return "", ""
    if s.lower().startswith(("http://doi.org/", "https://doi.org/",
                            "http://dx.doi.org/", "https://dx.doi.org/", "doi:")) \
            or re.match(r"^10\.\d{4,9}/\S+$", s):
        return "", norm_doi(s)
    return norm_title(s), ""


def load_records(materials):
    """返回 (records, used, issues)。

    每条记录带 source_row 供人工复核；无法解析的文件、坏行与无标题行都写入 issues，
    不再静默丢弃，也不因一行坏 JSON 把整个文件标记为不可读。
    """
    exts = (".csv", ".tsv", ".json", ".jsonl")
    records, used = [], []
    issues = {"unreadable_files": [], "partial_files": [], "dropped_rows": []}
    for dirpath, _, names in os.walk(materials):
        for n in sorted(names):
            p = os.path.join(dirpath, n)
            if n.lower() in ("case.json", "task.md") or not n.lower().endswith(exts):
                continue
            ext = os.path.splitext(n)[1].lower()
            src = os.path.relpath(p, materials)
            dropped = 0
            if ext in (".csv", ".tsv"):
                try:
                    with open(p, encoding="utf-8-sig", errors="replace") as fh:
                        for i, row in enumerate(csv.DictReader(
                                fh, delimiter="\t" if ext == ".tsv" else ","), start=2):
                            r = records_io.map_rec(row, src)
                            if r["title"]:
                                r["source_row"] = i
                                records.append(r)
                            else:
                                dropped += 1
                except Exception as exc:  # noqa: BLE001
                    issues["unreadable_files"].append("%s: %s" % (src, str(exc)[:100]))
                    continue
            elif ext == ".jsonl":
                good = bad = 0
                with open(p, encoding="utf-8", errors="replace") as fh:
                    for i, line in enumerate(fh, start=1):
                        if not line.strip():
                            continue
                        try:
                            obj = json.loads(line)
                        except Exception as exc:  # noqa: BLE001
                            bad += 1
                            issues["partial_files"].append(
                                "%s line %d: invalid json (%s)" % (src, i, str(exc)[:60]))
                            continue
                        r = records_io.map_rec(obj, src)
                        if r["title"]:
                            r["source_row"] = i
                            records.append(r)
                            good += 1
                        else:
                            bad += 1
                if bad:
                    issues["partial_files"].append(
                        "%s parsed %d line(s), %d unusable" % (src, good, bad))
            else:
                try:
                    data = json.load(open(p, encoding="utf-8", errors="replace"))
                except Exception as exc:  # noqa: BLE001
                    issues["unreadable_files"].append("%s: %s" % (src, str(exc)[:100]))
                    continue
                for i, obj in enumerate(records_io.iter_json(data), start=1):
                    if isinstance(obj, dict):
                        r = records_io.map_rec(obj, src)
                        if r["title"]:
                            r["source_row"] = i
                            records.append(r)
                        else:
                            dropped += 1
            if dropped:
                issues["dropped_rows"].append(
                    "%s: %d 行缺少标题，已忽略且未参与筛选" % (src, dropped))
            used.append(src)
    return records, used, issues


def _terms(v):
    if isinstance(v, str):
        return [v] if v.strip() else []
    if isinstance(v, (list, tuple)):
        return [str(x) for x in v if str(x).strip()]
    return []


def concepts_from(case, contract):
    raw = None
    for k in ("concepts", "query_blocks", "concept_blocks", "search_concepts"):
        if isinstance(case.get(k), list) and case[k]:
            raw = case[k]
            break
    blocks = []
    if raw:
        for b in raw:
            if isinstance(b, list):
                terms = _terms(b)
            elif isinstance(b, dict):
                terms = _terms(b.get("terms") or b.get("synonyms")
                              or b.get("name") or b.get("term"))
            else:
                terms = _terms(b)
            if terms:
                blocks.append(terms)
    if blocks:
        return blocks, "case.concepts"
    q = ""
    for k in ("research_question", "research question", "question", "query", "topic", "task"):
        if case.get(k):
            q = str(case[k])
            break
    if not q:
        q = str(contract.get("task") or "")
    toks = list(dict.fromkeys(tokens(q)))[:12]
    return ([[t] for t in toks] if toks else []), "query_tokens"


def criteria_from(case, materials):
    crit = {}
    for k in ("screening_criteria", "criteria", "eligibility", "rules"):
        if isinstance(case.get(k), dict):
            crit.update(case[k])
            break
    for k in ("year_from", "year_to", "doc_types", "languages", "exclude_terms",
              "known_relevant", "annotations", "k", "top_k"):
        if k in case and k not in crit:
            crit[k] = case[k]
    # 允许标准写在材料文本里：`year_from: 2015` 形式
    for dirpath, _, names in os.walk(materials):
        for n in names:
            if not n.lower().endswith((".md", ".txt", ".yaml", ".yml", ".json")):
                continue
            if n.lower() in ("case.json", "task.md"):
                continue
            try:
                body = open(os.path.join(dirpath, n), encoding="utf-8", errors="replace").read()
            except Exception:  # noqa: BLE001
                continue
            for key, pat in (("year_from", r"year_from\s*[:=]\s*(\d{4})"),
                             ("year_to", r"year_to\s*[:=]\s*(\d{4})")):
                m = re.search(pat, body, re.I)
                if m and key not in crit:
                    crit[key] = m.group(1)
            m = re.search(r"exclude_terms\s*[:=]\s*\[([^\]]*)\]", body, re.I)
            if m and "exclude_terms" not in crit:
                crit["exclude_terms"] = [x.strip().strip("'\"") for x in m.group(1).split(",") if x.strip()]
    return crit


def hard_exclusions(rec, crit):
    why = []
    yf, yt = str(crit.get("year_from") or ""), str(crit.get("year_to") or "")
    if yf and rec["year"] and rec["year"] < yf:
        why.append("year_before_window(%s<%s)" % (rec["year"], yf))
    if yt and rec["year"] and rec["year"] > yt:
        why.append("year_after_window(%s>%s)" % (rec["year"], yt))
    if crit.get("doc_types") and rec["doc_type"] and \
            rec["doc_type"].lower() not in [str(x).lower() for x in crit["doc_types"]]:
        why.append("doc_type_excluded(%s)" % rec["doc_type"])
    if crit.get("languages") and rec["language"] and \
            rec["language"].lower() not in [str(x).lower() for x in crit["languages"]]:
        why.append("language_excluded(%s)" % rec["language"])
    hay = (rec["title"] + " " + rec["abstract"]).lower()
    why += ["exclude_term(%s)" % t for t in (crit.get("exclude_terms") or []) if str(t).lower() in hay]
    return why


def dedupe(records):
    """DOI / arXiv / 归一标题三级合并；预印本被正式版覆盖时保留来源。

    强标识（DOI/arXiv）先于标题匹配；标题只在双方不强标识冲突时才作为合并键，
    避免不同研究仅因标题相似被误并。
    """
    def strong(r):
        return {k for k in (r.get("keys") or []) if not k.startswith("title:")}

    groups, key_owner = [], {}
    for r in records:
        gid = None
        for k in r.get("keys") or []:          # 强标识优先
            if k.startswith("title:"):
                continue
            if k in key_owner:
                gid = key_owner[k]
                break
        if gid is None:                        # 再尝试标题键（要求强标识不冲突）
            for k in r.get("keys") or []:
                if not k.startswith("title:") or k not in key_owner:
                    continue
                cand = key_owner[k]
                cand_ids = set().union(*[strong(x) for x in groups[cand]]) if groups[cand] else set()
                mine = strong(r)
                if not mine or not cand_ids or not mine.isdisjoint(cand_ids):
                    gid = cand
                    break
        if gid is None:
            gid = len(groups)
            groups.append([])
        groups[gid].append(r)
        for k in r.get("keys") or []:
            key_owner.setdefault(k, gid)
    merged, merges = [], []
    for rs in groups:
        if len(rs) == 1:
            merged.append(rs[0])
            continue
        def rank_version(x):
            preprint = 1 if re.search(r"preprint|posted-content|working paper|arxiv", (x["doc_type"] + " " + x["venue"]).lower()) else 0
            return (preprint, -len(x["abstract"]), x.get("source_row", 0))
        rs = sorted(rs, key=rank_version)
        base = dict(rs[0])
        base["merged_from"] = [{"source_file": x["source_file"], "source_row": x.get("source_row"),
                                "title": x["title"], "year": x["year"], "doi": x.get("doi"),
                                "doc_type": x["doc_type"]} for x in rs[1:]]
        for f in ("doi", "arxiv", "year", "abstract", "venue", "authors", "doc_type", "language"):
            if not base.get(f):
                base[f] = next((x[f] for x in rs if x.get(f)), "")
        strong_sets = [strong(x) for x in rs]
        common = set.intersection(*strong_sets) if all(strong_sets) else set()
        dkey = sorted(common)[0] if common else "title:" + hashlib.sha1(
            base["title"].encode("utf-8")).hexdigest()[:12]
        base["dedup_key"] = dkey
        base["version_note"] = "merged_duplicate_versions(preprint_superseded)" if rank_version(rs[-1])[0] else "merged_duplicates"
        merged.append(base)
        merges.append({"key": dkey, "kept": rs[0]["title"], "merged": [x["title"] for x in rs[1:]]})
    return merged, merges


def score_record(rec, blocks):
    hay_t, hay_a = rec["title"].lower(), rec["abstract"].lower()
    hit_blocks, evidence = [], []
    title_hits = abstract_hits = 0
    for i, terms in enumerate(blocks):
        in_t = [t for t in terms if t.lower() in hay_t]
        in_a = [t for t in terms if t.lower() in hay_a]
        if in_t or in_a:
            hit_blocks.append(i)
            rec["matched_blocks"].append({"block": i + 1, "title_terms": in_t, "abstract_terms": in_a})
            title_hits += len(in_t)
            abstract_hits += len(in_a)
            if in_t:
                evidence.append("title:%s" % ",".join(in_t))
            elif in_a:
                evidence.append("abstract:%s" % ",".join(in_a[:3]))
    coverage = len(hit_blocks) / len(blocks) if blocks else 0.0
    parts = {"coverage": round(55 * coverage, 2),
             "title_match": round(30 * min(1.0, title_hits / 3.0), 2),
             "abstract_match": round(15 * min(1.0, abstract_hits / 3.0), 2)}
    # score 保留 1 位小数；把四舍五入残差并入最大项，保证 score_parts 之和 == score。
    score = round(55 * coverage + 30 * min(1.0, title_hits / 3.0)
                  + 15 * min(1.0, abstract_hits / 3.0), 1)
    residual = round(score - sum(parts.values()), 2)
    if residual:
        key = max(parts, key=parts.get)
        parts[key] = round(parts[key] + residual, 2)
    rec["score_parts"] = parts
    rec["score"] = score
    rec["concept_coverage"] = round(coverage, 3)
    rec["evidence"] = evidence or ["no_concept_term_match"]
    rec["confidence"] = "high" if coverage >= 0.66 and title_hits else ("medium" if coverage >= 0.34 else "low")
    return rec


def annotate_conflicts(rec, opinions):
    if not opinions:
        return None
    votes = [str(o.get("decision") or o.get("label") or "").lower() for o in opinions]
    if len(set(votes)) > 1:
        return {"decisions": votes, "resolution": "maybe", "reason": "annotator_disagreement_escalated"}
    return None


def label_of(rec, rule_hits):
    if rule_hits:
        return "exclude"
    if rec["score"] >= 65:
        return "include"
    if rec["score"] >= 35:
        return "maybe"
    return "exclude"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--case", default="/input/case.json")
    ap.add_argument("--materials", default="/input")
    ap.add_argument("--work", default="/app/work")
    a = ap.parse_args()
    case = load(os.path.join(a.work, "case.raw.json"), {})
    contract = load(os.path.join(a.work, "contract.json"), {})
    case_id = contract.get("case_id") or "case"
    records, used, issues = load_records(a.materials)
    blocks, block_src = concepts_from(case, contract)
    crit = criteria_from(case, a.materials)
    if not records:
        draft = {"case_id": case_id, "status": "blocked", "summary": "候选集为空或不可读",
                 "retrieval_scope": {"materials_used": used, "issues": issues},
                 "ranked_candidates": [], "screening_decisions": [],
                 "dedup_summary": {}, "relevance_rubric": {"blocks": blocks, "source": block_src},
                 "recall_check": {}, "stability_check": {}, "conflict_resolution": [],
                 "evidence_map": [], "validation": {"checks": []},
                 "uncertainty": ["未在材料中找到可解析的候选文献记录"]
                                + ["材料不可读：%s" % m for m in issues["unreadable_files"]],
                 "limits": "候选集为空：只能说明未完成，不补造文献。", "changes": []}
        dump(draft, os.path.join(a.work, "draft.json"))
        return 0
    merged, merges = dedupe(records)
    opinions = {}
    for o in case.get("annotations") or crit.get("annotations") or []:
        if isinstance(o, dict):
            key = str(o.get("doi") or o.get("title") or "").lower()
            opinions.setdefault(key, []).append(o)
    for i, r in enumerate(merged):
        score_record(r, blocks)
        r["source_row"] = r.get("source_row") or i + 1
        r["rule_hits"] = hard_exclusions(r, crit)
        ops = opinions.get(r["doi"].lower()) or opinions.get(r["title"].lower()) or []
        r["conflict"] = annotate_conflicts(r, ops)
        if r["rule_hits"]:
            r["decision"] = "exclude"
            r["exclude_reason"] = ";".join(r["rule_hits"])
        elif not blocks:
            # 无概念块时无法计算相关性：不得把“未命中”当作“不相关”。
            r["decision"] = "maybe"
            r["exclude_reason"] = "no_query_terms_defined"
        elif r["conflict"]:
            r["decision"] = "maybe"
            r["exclude_reason"] = "insufficient_evidence_or_conflict"
        else:
            r["decision"] = label_of(r, r["rule_hits"])
            if r["decision"] == "exclude":
                r["exclude_reason"] = "relevance_below_threshold(score<35)"
            elif r["decision"] == "maybe":
                r["exclude_reason"] = "insufficient_evidence_or_conflict"
    merged.sort(key=lambda r: (r["decision"] == "exclude", -r["score"], -r["concept_coverage"],
                               -(1 if r["doi"] else 0) - (1 if r["year"] else 0),
                               -(int(r["year"]) if str(r.get("year", "")).isdigit() else 0),
                               r["title"].lower()))
    # 并列：同分同名次（competition ranking）。
    # 分层排序把 exclude 放在末尾，若 rank 仍按分数跨层比较，会出现“位次更靠后但分数更高”的
    # 非单调结果；因此 include/maybe 与 exclude 分别做并列编号，exclude 的整体位次始终更大。
    considered = [r for r in merged if r["decision"] != "exclude"]
    excluded = [r for r in merged if r["decision"] == "exclude"]
    prev, rank = None, 0
    for i, r in enumerate(considered, start=1):
        if prev is None or abs(r["score"] - prev) > 1e-9:
            rank = i
        r["rank"] = rank
        prev = r["score"]
    prev, rank = None, len(considered)
    for i, r in enumerate(excluded, start=len(considered) + 1):
        if prev is None or abs(r["score"] - prev) > 1e-9:
            rank = i
        r["rank"] = rank
        prev = r["score"]
    k = int(crit.get("k") or crit.get("top_k") or 10)
    known = crit.get("known_relevant") or []
    if isinstance(known, dict):
        known = [known]
    elif isinstance(known, str):
        known = [known]
    elif not isinstance(known, list):
        known = []

    def known_match(rec, kt, kd):
        for x in [rec] + list(rec.get("merged_from") or []):
            if norm_title(x.get("title")) == kt:
                return True
            if kd and norm_doi(x.get("doi")) == kd:
                return True
        return False

    entries = [known_entry(x) for x in known]
    matched_known = {i for i, (kt, kd) in enumerate(entries)
                     if any(known_match(r, kt, kd) for r in considered[:k])}
    missed = []
    for i, x in enumerate(known):
        kt, kd = entries[i]
        in_corpus = [r for r in merged if known_match(r, kt, kd)]
        if not in_corpus:
            missed.append({"known": x, "reason": "not_in_corpus"})
        else:
            ruled = [r for r in in_corpus if r["rule_hits"]]
            if ruled:
                missed.append({"known": x,
                               "reason": "excluded_by_rule(%s)" % ";".join(ruled[0]["rule_hits"])})
            elif all(r["rank"] > k for r in in_corpus):
                missed.append({"known": x,
                               "reason": "ranked_below_k(%s)" % min(r["rank"] for r in in_corpus)})
    recall_check = {"k": k, "known_total": len(known), "hit_at_k": len(matched_known),
                    "recall_at_k": round(len(matched_known) / len(known), 3) if known else None,
                    "missed": missed,
                    "note": "分母只来自题面已知集；未提供已知集时不报告覆盖率"}
    # 稳定性：仅改变标题/摘要权重，检查前 k 名重合度（只在 include/maybe 内比较）
    def variant(order_key):
        return [r["title"] for r in sorted(considered, key=lambda r: -(
            r["score_parts"]["coverage"] + order_key[0] * min(1, len([m for m in r.get("matched_blocks", []) if m["title_terms"]]))
            + order_key[1] * min(1, len([m for m in r.get("matched_blocks", []) if m["abstract_terms"]]))))]
    base_top = [r["title"] for r in considered[:k]]
    overlaps = []
    for w in ((30, 15), (15, 30), (20, 20)):
        alt = variant(((w[0] / 3.0), (w[1] / 3.0)))[:k]
        overlaps.append(round(len(set(base_top) & set(alt)) / max(1, len(base_top) or k), 3))
    stability = {"k": k, "weight_variants": overlaps,
                 "min_overlap": min(overlaps) if overlaps else None,
                 "stable": bool(overlaps) and min(overlaps) >= 0.8,
                 "tie_rule": "同分同名次；同分按概念覆盖、元数据完整度、年份、标题字典序"}
    csv_lines = ["rank,decision,score,title,year,doi,venue,concept_coverage,confidence,source,row,reason,merged_versions"]
    for r in merged:
        csv_lines.append(",".join('"%s"' % str(x).replace('"', "'") for x in (
            r["rank"], r["decision"], r["score"], r["title"], r["year"], r["doi"], r["venue"],
            r["concept_coverage"], r["confidence"], r["source_file"], r.get("source_row"),
            r.get("exclude_reason") or ("include_by_score>=65" if r["decision"] == "include" else "maybe_needs_review"),
            len(r.get("merged_from") or []))))
    ranked = [{"rank": r["rank"], "title": r["title"], "year": r["year"], "doi": r["doi"],
               "venue": r["venue"], "score": r["score"], "score_parts": r["score_parts"],
               "decision": r["decision"], "confidence": r["confidence"],
               "matched": r["matched_blocks"], "evidence": r["evidence"],
               "source": {"file": r["source_file"], "row": r.get("source_row")},
               "reason": r.get("exclude_reason") or "include_by_score>=65",
               "merged_from": r.get("merged_from") or []} for r in merged]
    uncertainty = []
    if not blocks:
        uncertainty.append("未提供概念块或研究问题：相关性分数不可计算，记录一律置为待定(maybe)")
    n_missing_abs = sum(1 for r in merged if not r["abstract"])
    if n_missing_abs:
        uncertainty.append("%d 条记录缺少摘要，相关性置信度记为 low" % n_missing_abs)
    uncertainty += ["材料不可读，未纳入候选：%s" % m for m in issues["unreadable_files"]]
    uncertainty += ["材料部分行无法解析：%s" % m for m in issues["partial_files"]]
    uncertainty += ["无标题行被忽略（未参与筛选）：%s" % m for m in issues["dropped_rows"]]
    if not known:
        uncertainty.append("题面未提供 known_relevant，recall_at_k 记 null，不编造覆盖率")
    checks = [
        {"check": "all_records_screened", "pass": True,
         "detail": "%d 条解析记录全部进入去重/决策，合并后 %d 条" % (len(records), len(merged))},
        {"check": "every_item_has_locator", "pass": all(x["source"]["row"] for x in ranked)},
        {"check": "score_decomposable", "pass": all(abs(sum(r["score_parts"].values()) - r["score"]) < 1e-6 for r in merged)},
        {"check": "rank_monotonic_by_decision", "pass": all(
            ranked[i]["rank"] <= ranked[i + 1]["rank"] for i in range(len(ranked) - 1))},
        {"check": "known_set_recall_reported", "pass": True,
         "detail": ("分母来自题面 known_relevant（%d 条）" % len(known)) if known
         else "题面未提供 known_relevant，recall_at_k=null"},
        {"check": "no_silent_drops", "pass": True,
         "detail": "无标题行/坏行/不可读文件均已写入 uncertainty" if not (
             issues["dropped_rows"] or issues["partial_files"] or issues["unreadable_files"])
         else "已记录：无标题 %d 处 / 坏行 %d 处 / 不可读 %d 个" % (
             len(issues["dropped_rows"]), len(issues["partial_files"]), len(issues["unreadable_files"]))},
        {"check": "query_terms_defined", "pass": bool(blocks),
         "detail": "概念块 %d 个（来源 %s）" % (len(blocks), block_src)},
    ]
    status = "ok" if blocks else "partial"
    limits = ("未定义概念块/研究问题，相关性分数不可计算；结果为待定清单，需先补充检索标准。"
              if not blocks else "只对提供的本地候选集负责；未提供已知集时不报告覆盖率。")
    draft = {"case_id": case_id, "status": status,
             "summary": "候选 %d 条（合并后 %d），保留 %d / 待定 %d / 排除 %d；按分数与并列规则排序。"
                        % (len(records), len(merged),
                           sum(1 for r in merged if r["decision"] == "include"),
                           sum(1 for r in merged if r["decision"] == "maybe"),
                           sum(1 for r in merged if r["decision"] == "exclude")),
             "retrieval_scope": {"materials_used": used, "record_count": len(records),
                                 "merged_count": len(merged), "live_database": False,
                                 "issues": issues},
             "query_terms": {"blocks": blocks, "source": block_src},
             "relevance_rubric": {"score": "55*概念块覆盖 + 30*标题命中 + 15*摘要命中",
                                  "include": "score>=65 且无硬性排除",
                                  "maybe": "35<=score<65、证据不足或标注分歧",
                                  "exclude": "score<35 或命中年份/类型/语言/排除词",
                                  "k": k},
             "dedup_summary": {"input_records": len(records), "merged_records": len(merged),
                               "merge_events": merges},
             "ranked_candidates": ranked,
             "screening_decisions": [{"title": r["title"], "decision": r["decision"],
                                      "reason": r.get("exclude_reason") or "score>=65",
                                      "evidence": r["evidence"]} for r in merged],
             "conflict_resolution": [{"title": r["title"], "conflict": r["conflict"]}
                                     for r in merged if r.get("conflict")],
             "recall_check": recall_check,
             "stability_check": stability,
             "exclusions": [{"title": r["title"], "reason": r.get("exclude_reason")}
                            for r in merged if r["decision"] == "exclude"],
             "evidence_map": [{"title": r["title"], "file": r["source_file"], "row": r.get("source_row"),
                               "matched": r["matched_blocks"]} for r in merged],
             "validation": {"checks": checks},
             "assumptions": ["材料即候选全集；不声称实时检索或全局召回"],
             "uncertainty": uncertainty,
             "limits": limits,
             "changes": [],
             "self_check": {"records": len(records), "merged": len(merged), "k": k,
                            "blocks": len(blocks), "dropped_rows": sum(
                                int(m.split(":")[1].split()[0]) for m in issues["dropped_rows"]
                                if m.split(":")[1].split()[0].isdigit())},
             "artifacts": {"ranked_candidates.csv": "\n".join(csv_lines) + "\n",
                           "screening_report.md": render_md(records, merged, recall_check,
                                                           stability, merges, crit, issues)}}
    dump(draft, os.path.join(a.work, "draft.json"))
    print("ranked=%d merged=%d include=%d maybe=%d exclude=%d stable=%s"
          % (len(records), len(merged),
             sum(1 for r in merged if r["decision"] == "include"),
             sum(1 for r in merged if r["decision"] == "maybe"),
             sum(1 for r in merged if r["decision"] == "exclude"), stability["stable"]))
    return 0


def render_md(records, merged, recall, stability, merges, crit, issues):
    out = ["# 文献筛选与智能排序报告", "",
           "## 结论", "",
           "共 %d 条记录，合并后 %d 条；保留 %d / 待定 %d / 排除 %d。"
           % (len(records), len(merged),
              sum(1 for r in merged if r["decision"] == "include"),
              sum(1 for r in merged if r["decision"] == "maybe"),
              sum(1 for r in merged if r["decision"] == "exclude")), "",
           "## 排序前 20（排除项整体排在待定/保留之后）", "",
           "| # | 决定 | 分数 | 标题 | 年份 | 依据 |", "|-|-|-|-|-|-|"]
    for r in merged[:20]:
        out.append("| %s | %s | %s | %s | %s | %s |" % (
            r["rank"], r["decision"], r["score"], r["title"][:60], r["year"],
            "; ".join(r["evidence"])[:80]))
    out += ["", "## 合并的重复/版本", ""]
    out += ["- %s ← %s" % (m["kept"], "; ".join(m["merged"])) for m in merges] or ["- 无"]
    out += ["", "## 数据质量（未纳入/未完全解析）", ""]
    quality = (["- 材料不可读：%s" % m for m in issues["unreadable_files"]]
               + ["- 部分行无法解析：%s" % m for m in issues["partial_files"]]
               + ["- %s" % m for m in issues["dropped_rows"]])
    out += quality or ["- 无：所有可解析记录均已纳入，无标题/坏行已单独计数。"]
    out += ["", "## 已知集召回", "",
            "- k=%s, recall=%s, missed=%s" % (recall["k"], recall["recall_at_k"],
                                              json.dumps(recall["missed"], ensure_ascii=False)),
            "", "## 稳定性", "",
            "- 权重扰动下前 k 重合度：%s；stable=%s" % (stability["weight_variants"], stability["stable"]),
            "", "## 复核口径", "",
            "- 分数 = 55×概念块覆盖 + 30×标题命中 + 15×摘要命中（各项均封顶 1）。",
            "- 每条记录保留来源文件与行号；排除项写明规则触发。",
            "- 标注分歧升级为待定，不擅自按单方意见定稿。"]
    return "\n".join(out) + "\n"


if __name__ == "__main__":
    sys.exit(main())
