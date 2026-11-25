#!/usr/bin/env python3
"""run_case.py - 一条命令完成批注抽取→锚定→笔记→关联→检索→审计。

  python3 /skills/weekly-skill/scripts/run_case.py --case /input/case.json --materials /input \
      --work /app/work --out /app/output

只用标准库，不联网。材料为空时 status=blocked，不产出伪清单。退出码恒为 0。
"""
import argparse
import csv
import json
import os
import sys
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import core  # noqa: E402


def dump(obj, path):
    os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(obj, fh, ensure_ascii=False, indent=1)


def write_csv(path, header, rows):
    os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=header, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow({k: ("" if r.get(k) is None else r.get(k)) for k in header})


def match_doc(src, docs):
    if not src:
        return None
    key = core.norm_title(src)
    if not key:
        return None
    best = None
    for d in docs:
        for cand in (d.get("title"), d.get("source_file")):
            ck = core.norm_title(cand)
            if not ck:
                continue
            if key == ck or (len(ck) >= 6 and (ck in key or key in ck)):
                return d
            if len(key) >= 6 and (key in ck):
                best = best or d
    return best


def annot_id(a):
    raw = "|".join(str(a.get(k)) for k in
                   ("doc_id", "page", "type", "quote", "comment", "bbox", "source_ref"))
    return "ann_" + core.short_hash(raw, 12)


def merge_annotations(docs, native, exported, log):
    by_doc = {}
    for a in native:
        by_doc.setdefault(a["_doc"], []).append(a)
    final = list(native)
    used = set()
    for ex in exported:
        doc = ex.get("_doc_rec")
        if not doc:
            final.append(ex)
            continue
        cands = by_doc.get(doc["doc_id"], [])
        best, best_iou = None, 0.0
        for na in cands:
            if id(na) in used or na.get("page") != ex.get("page"):
                continue
            score = core.iou(na.get("bbox"), ex.get("bbox"))
            if score >= 0.3 and score > best_iou:
                best, best_iou = na, score
        if best is not None:
            used.add(id(best))
            best["quote"] = best.get("quote") or ex.get("quote")
            comments = [c for c in (best.get("comment"), ex.get("comment")) if c]
            if len(set(comments)) > 1:
                best["comments"] = sorted(set(comments))
            best["comment"] = best.get("comment") or ex.get("comment")
            best["label"] = ex.get("label") or best.get("label")
            best["color"] = best.get("color") or ex.get("color")
            best["author"] = best.get("author") or ex.get("author")
            best["created"] = best.get("created") or ex.get("created")
            best["merged_from"] = [best.get("source_ref"), ex.get("source_ref")]
            best["quote_source"] = ex.get("source_ref")
            best["merge_basis"] = "same_page_iou_%.2f" % best_iou
            if ex.get("type") not in ("unknown", None):
                best["type"] = best["type"] if best.get("type") != "unknown" else ex["type"]
            log.append({"phase": "merge", "detail": "%s + %s 合并（IoU %.2f）"
                        % (best["source_ref"], ex["source_ref"], best_iou)})
        else:
            final.append(ex)
    seen = []
    deduped = []
    for a in final:
        qn = core.normkey(a.get("quote") or "")
        prev = None
        if len(qn) >= 8:
            for p in seen:
                if p.get("doc_id") != a.get("doc_id"):
                    continue
                if core.normkey(p.get("quote") or "") != qn:
                    continue
                if p.get("page") is not None and a.get("page") is not None \
                        and p.get("page") != a.get("page"):
                    continue
                if p.get("type") not in ("unknown", a.get("type")) \
                        and a.get("type") not in ("unknown", p.get("type")):
                    continue
                pc, ac = (p.get("comment") or "").strip(), (a.get("comment") or "").strip()
                if pc and ac and core.normkey(pc) != core.normkey(ac):
                    continue
                prev = p
                break
        if prev is not None:
            if not prev.get("comment") and a.get("comment"):
                prev["comment"] = a["comment"]
                prev["quote_source"] = a.get("source_ref")
            if prev.get("page") is None and a.get("page") is not None:
                prev["page"] = a["page"]
            if not prev.get("bbox") and a.get("bbox"):
                prev["bbox"] = a["bbox"]
            prev.setdefault("merged_from", [prev.get("source_ref")])
            prev["merged_from"].append(a.get("source_ref"))
            prev["merge_basis"] = "same_doc_quote"
            log.append({"phase": "dedup", "detail": "%s 与 %s 同文档同引文，合并并补齐页码/批注"
                        % (prev.get("source_ref"), a.get("source_ref"))})
            continue
        seen.append(a)
        deduped.append(a)
    return deduped


def build(case_path, materials):
    worklog = []
    case = core.load_case(case_path) if os.path.exists(case_path) else {
        "case_id": os.path.basename(os.path.abspath(materials)) or "case",
        "raw": {}, "contract_fields": [], "color_legend": {}, "search_questions": []}
    cid = case["case_id"]
    entries = core.index_materials(materials)
    worklog.append({"phase": "index", "detail": "%d 个文件" % len(entries)})

    docs, all_native, doc_diags, skipped = [], [], [], []
    seen_sha = {}
    for e in entries:
        if e["role"] == "unsupported":
            skipped.append({"file": e["path"], "reason": "unsupported_type: %s" % (e["ext"] or "no_ext")})
            continue
        if e["role"] != "document":
            continue
        if not e["readable"]:
            skipped.append({"file": e["path"], "reason": "unreadable_or_symlink"})
            continue
        try:
            if e["ext"] == ".pdf":
                d, anns = core.parse_pdf(e["abs"], e["path"], e["sha256"])
            elif e["ext"] in (".docx", ".docm"):
                d, anns = core.parse_docx(e["abs"], e["path"], e["sha256"])
            elif e["ext"] in (".html", ".htm"):
                d, anns = core.parse_html(e["abs"], e["path"], e["sha256"])
            else:
                d, anns = core.parse_plain(e["abs"], e["path"], e["sha256"])
        except Exception as exc:  # noqa: BLE001
            d = {"source_file": e["path"], "sha256": e["sha256"], "title": None, "pages": None,
                 "permission": "unreadable", "metadata": {}, "kind": e["ext"].lstrip("."),
                 "diagnostics": ["parser_error: %s" % exc], "_page_texts": {}}
            anns = []
        d["doc_id"] = "doc_" + core.short_hash(e["path"] + "|" + (e["sha256"] or ""), 10)
        d["readable"] = bool(e["readable"])
        d["metadata"].setdefault("file_bytes", e["bytes"])
        d["metadata"].setdefault("ext", e["ext"])
        try:
            d["metadata"].setdefault("mtime", core.datetime.fromtimestamp(
                os.path.getmtime(e["abs"]), core.timezone.utc).astimezone().isoformat(timespec="seconds"))
        except Exception:
            pass
        if not d.get("title"):
            d["title"] = os.path.splitext(os.path.basename(e["path"]))[0]
        doc_diags.extend([{"file": e["path"], "detail": x} for x in d.get("diagnostics") or []])
        dup_of = seen_sha.get(e["sha256"])
        if dup_of:
            worklog.append({"phase": "duplicate", "detail": "%s 与 %s 哈希相同，跳过重复解析批注"
                            % (e["path"], dup_of)})
            anns = []
        seen_sha.setdefault(e["sha256"], d["doc_id"])
        for a in anns:
            a["_doc"] = d["doc_id"]
            a["_file"] = e["path"]
            a["doc_id"] = d["doc_id"]
            a["_page_texts"] = d.get("_page_texts")
            a["_fidelity"] = d.get("_page_fidelity")
        all_native.extend(anns)
        docs.append(d)
    worklog.append({"phase": "parse", "detail": "文档 %d，原生批注 %d" % (len(docs), len(all_native))})

    exported, exp_diag = core.load_exports(entries)
    for ex in exported:
        doc = match_doc(ex.get("declared_source") or "", docs)
        ex["_doc_rec"] = doc
        ex["doc_id"] = doc["doc_id"] if doc else None
        ex["_file"] = doc["source_file"] if doc else ex["source_ref"].split(":row")[0]
        ex["_page_texts"] = doc.get("_page_texts") if doc else {}
        ex["_fidelity"] = doc.get("_page_fidelity") if doc else {}
    doc_diags.extend({"file": "export", "detail": x} for x in exp_diag)
    worklog.append({"phase": "exports", "detail": "导出批注 %d 条" % len(exported)})

    version_rel = core.register_documents(docs)
    anns = merge_annotations(docs, all_native, exported, worklog)
    for a in anns:
        core.anchor(a, a.get("_page_texts"), a.get("_fidelity"))
        doc = next((d for d in docs if d["doc_id"] == a.get("doc_id")), None)
        a["_family"] = doc.get("family_id") if doc else None
        a["annotation_id"] = annot_id(a)
        a["source"] = {"file": a.get("_file"), "ref": a.get("source_ref")}
        a["color_meaning"] = case["color_legend"].get(a.get("color") or "")
        if a.get("type") == "unknown":
            a["needs_review"] = True
            worklog.append({"phase": "annotation", "detail": "%s 类型未识别（%s），标记待复核"
                            % (a["source_ref"], a.get("raw_type"))})
    worklog.append({"phase": "anchor", "detail": "批注 %d 条完成锚点校验" % len(anns)})

    conflicts = []
    for a in anns:
        status = (a.get("anchor") or {}).get("status")
        if status in ("quote_not_found", "low_fidelity_text", "text_layer_unavailable",
                      "coordinate_only", "page_unknown"):
            conflicts.append({"type": status, "annotation_id": a["annotation_id"],
                              "quote": (a.get("quote") or "")[:160],
                              "page": a.get("page"),
                              "handling": "保留原值并升级人工，不猜测页码/文字"})
        elif (a.get("anchor") or {}).get("ambiguous"):
            conflicts.append({"type": "ambiguous_anchor", "annotation_id": a["annotation_id"],
                              "quote": (a.get("quote") or "")[:160], "page": a.get("page"),
                              "handling": "记录首个命中区间，升级人工确认"})
    conflicts.extend(core.page_drift(anns))

    notes = core.build_notes(anns)
    entities = []
    for k in ("entities", "entity_vocabulary", "glossary"):
        v = case["raw"].get(k) if isinstance(case["raw"], dict) else None
        if isinstance(v, list):
            entities = [str(x) for x in v]
            break
    links, rejected = core.build_links(notes, anns, entities)
    links_all = links + rejected
    index = core.build_index(notes)
    q_results, q_log = core.run_queries(index, notes, case["search_questions"])

    anchor_counts = {}
    for a in anns:
        st = (a.get("anchor") or {}).get("status") or "unknown"
        anchor_counts[st] = anchor_counts.get(st, 0) + 1
    verified = sum(1 for a in anns if (a.get("anchor") or {}).get("verified"))
    with_quote = sum(1 for a in anns if a.get("quote"))

    unread = [e["path"] for e in entries if not e["readable"]]
    bad_docs = [d["source_file"] for d in docs
                if d.get("permission") in ("unreadable", "encrypted")
                or d.get("text_layer") == "unavailable"]
    if not docs:
        status = "blocked"
    elif unread or bad_docs or conflicts:
        status = "partial"
    else:
        status = "ok"

    limits = []
    if status == "blocked":
        limits.append("输入目录没有可读文档或批注导出，输出为空清单并明确 blocked，未按完成处理。")
    elif status != "ok":
        limits.append("存在不可读/加密/无文本层文件、未通过锚点校验的批注或冲突项，已逐条列明，未按完成处理。")
    limits.append("不解析压缩对象流中的 PDF 批注；不 OCR；颜色含义只取案例图例；"
                  "笔记类型与关联为规则判定，需人工确认 unknown/unverified 项。")
    if not case["raw"]:
        limits.append("未提供 case.json，按默认契约运行，契约字段以材料实际内容为准。")

    inv = [{"path": e["path"], "sha256": e["sha256"], "bytes": e["bytes"],
            "role": e["role"], "readable": e["readable"], "is_symlink": e["is_symlink"]}
           for e in entries]
    doc_out = []
    for d in docs:
        doc_out.append({k: v for k, v in d.items() if not k.startswith("_")})
    ann_out = []
    for a in anns:
        ann_out.append({k: v for k, v in a.items() if not k.startswith("_")})

    metadata_summary = {
        "documents": len(docs),
        "by_kind": {k: sum(1 for d in docs if d.get("kind") == k)
                    for k in sorted({d.get("kind") for d in docs})},
        "missing_title": sum(1 for d in docs if not d.get("title")),
        "encrypted": sum(1 for d in docs if d.get("permission") == "encrypted"),
        "text_layer_chars": sum(int((d.get("metadata") or {}).get("text_layer_chars") or 0)
                                for d in docs),
        "fields_present": sorted({k for d in docs for k in (d.get("metadata") or {})}),
    }

    result = {
        "case_id": cid,
        "status": status,
        "summary": ("%d 个文件 / %d 份文档 / %d 条批注（%d 条有引文，%d 条锚点通过）/ "
                    "%d 条笔记 / %d 条接受关联 / %d 条冲突"
                    % (len(entries), len(docs), len(anns), with_quote, verified,
                       len(notes), sum(1 for l in links if l.get("accepted")),
                       len(conflicts))),
        "input_inventory": inv,
        "documents": doc_out,
        "metadata_summary": metadata_summary,
        "version_relations": version_rel,
        "annotations": ann_out,
        "anchor_quality": {"counts": anchor_counts, "with_quote": with_quote,
                           "verified": verified,
                           "verified_rate": round(verified / max(1, with_quote), 3),
                           "needs_review": sum(1 for a in anns if a.get("needs_review"))},
        "notes": notes,
        "links": links_all,
        "search_index_meta": {"version": index["version"], "note_count": index["note_count"],
                              "vocabulary": index["vocabulary"], "filters": index["filters"]},
        "search_results": q_results,
        "operations_log": worklog,
        "conflicts": conflicts,
        "failures_recovery": {"skipped": skipped, "diagnostics": doc_diags,
                              "encrypted_or_unreadable": bad_docs},
        "uncertainty": sorted({c["type"] for c in conflicts}) + (
            ["存在未验证支撑的笔记"] if any(n.get("support_status") == "unverified" for n in notes) else []),
        "limits": limits,
        "assumptions": ["材料目录即本次可用的全部证据范围",
                        "颜色含义仅来自案例 color_legend，未给出时记为 null",
                        "原生 PDF 批注仅解析可直接读取的对象；压缩对象流退回导出记录"],
        "validation": {"checks": []},
        "changes": [],
        "_contract_fields": case["contract_fields"],
    }
    result["validation"]["checks"] = core.validate(result)
    result = core.finalize_contract(result, case["contract_fields"])
    result["validation"]["checks"] = core.validate(result)
    result.pop("_contract_fields", None)

    artifacts = {"annotations": ann_out, "notes": notes, "links": links_all,
                 "index": index, "search_results": q_results, "search_log": q_log}
    return result, artifacts


def audit_md(result):
    lines = ["# 审计报告 - %s（%s）" % (result["case_id"], core.VERSION), ""]
    lines.append("状态：`%s`；%s" % (result["status"], result["summary"]))
    lines += ["", "## 输入清单", "", "| 文件 | sha256 | 字节 | 角色 | 可读 |", "|-|-|-|-|-|"]
    for e in result["input_inventory"]:
        lines.append("| %s | `%s` | %s | %s | %s |" % (
            e["path"], (e["sha256"] or "")[:16], e["bytes"], e["role"],
            "是" if e["readable"] else "否"))
    lines += ["", "## 锚点质量", ""]
    for k, v in sorted(result["anchor_quality"]["counts"].items(), key=lambda kv: -kv[1]):
        lines.append("- `%s`: %d" % (k, v))
    lines.append("- 有引文 %d 条，锚点通过 %d 条（通过率 %.3f），待复核 %d 条" % (
        result["anchor_quality"]["with_quote"], result["anchor_quality"]["verified"],
        result["anchor_quality"]["verified_rate"], result["anchor_quality"]["needs_review"]))
    lines += ["", "## 版本与重复", ""]
    vr = result["version_relations"]
    if not vr["duplicates"] and not vr["version_families"]:
        lines.append("- 未发现重复或版本族。")
    for d in vr["duplicates"]:
        lines.append("- 重复（sha256 `%s`）：%s" % (d["sha256"][:16], ", ".join(d["files"])))
    for f in vr["version_families"]:
        lines.append("- 版本族 `%s`（%s）：%s" % (
            f["family_id"], f["title_normalized"],
            ", ".join(m["file"] for m in f["members"])))
    lines += ["", "## 笔记与关联", "",
              "- 笔记 %d 条（未验证支撑 %d 条）" % (
                  len(result["notes"]),
                  sum(1 for n in result["notes"] if n["support_status"] == "unverified"))]
    for n in result["notes"][:12]:
        lines.append("- `%s` [%s] %s（支撑 %d 条，页 %s）" % (
            n["note_id"], n["note_type"], (n["claim"] or "")[:80],
            len(n["support"]), n["page"]))
    acc = [l for l in result["links"] if l.get("accepted")]
    rej = [l for l in result["links"] if not l.get("accepted")]
    lines.append("- 接受关联 %d 条，拒绝 %d 条（过度连接控制）" % (len(acc), len(rej)))
    for l in acc[:10]:
        lines.append("  - %s ↔ %s：%s（%s，置信 %.2f）" % (
            l["from_note"], l["to_note"], l["basis"], ", ".join(l["shared"]), l["confidence"]))
    lines += ["", "## 冲突与失败恢复", ""]
    if not result["conflicts"]:
        lines.append("- 无冲突。")
    for c in result["conflicts"][:20]:
        lines.append("- `%s` %s：%s → %s" % (c.get("type"), c.get("annotation_id", ""),
                                            (c.get("quote") or "")[:60], c.get("handling")))
    for s in result["failures_recovery"]["skipped"]:
        lines.append("- 跳过 %s（%s）" % (s["file"], s["reason"]))
    for d in result["failures_recovery"]["diagnostics"][:20]:
        lines.append("- 诊断 %s：%s" % (d["file"], d["detail"]))
    lines += ["", "## 自查", "", "| 检查 | 结果 | 说明 |", "|-|-|-|"]
    for c in result["validation"]["checks"]:
        lines.append("| %s | %s | %s |" % (c["check"], "pass" if c["pass"] else "FAIL",
                                           c["detail"]))
    lines += ["", "## 复跑", "",
              "```bash",
              "python3 /skills/weekly-skill/scripts/run_case.py --case /input/case.json --materials /input \\",
              "  --work /app/work --out /app/output",
              "python3 /skills/weekly-skill/scripts/search.py --index /app/output/search_index.json --query \"关键词\"",
              "```", ""]
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--case", default="/input/case.json")
    ap.add_argument("--materials", default="/input")
    ap.add_argument("--work", default="/app/work")
    ap.add_argument("--out", default="/app/output")
    a = ap.parse_args()
    a.case, a.materials = os.path.abspath(a.case), os.path.abspath(a.materials)
    a.work, a.out = os.path.abspath(a.work), os.path.abspath(a.out)
    os.makedirs(a.work, exist_ok=True)
    os.makedirs(a.out, exist_ok=True)
    try:
        result, arts = build(a.case, a.materials)
    except Exception:  # noqa: BLE001
        tb = traceback.format_exc()
        blocked = {"case_id": os.path.basename(a.materials) or "case", "status": "blocked",
                   "summary": "运行异常，未产出清单", "input_inventory": [], "documents": [],
                   "metadata_summary": {}, "version_relations": {"duplicates": [],
                   "version_families": []}, "annotations": [], "anchor_quality": {"counts": {}},
                   "notes": [], "links": [], "search_index_meta": {}, "search_results": [],
                   "operations_log": [{"phase": "fatal", "detail": tb.splitlines()[-1]}],
                   "conflicts": [], "failures_recovery": {"skipped": [], "diagnostics": [
                       {"file": "runner", "detail": tb.splitlines()[-1]}],
                       "encrypted_or_unreadable": []},
                   "uncertainty": ["运行异常"], "limits": ["运行异常，结果不完整"],
                   "assumptions": [], "validation": {"checks": []}, "changes": []}
        case = core.load_case(a.case) if os.path.exists(a.case) else {"contract_fields": []}
        blocked["_contract_fields"] = case.get("contract_fields") or []
        core.finalize_contract(blocked, blocked["_contract_fields"])
        blocked["validation"] = {"checks": core.validate(blocked)}
        dump(blocked, os.path.join(a.out, "result.json"))
        print("BLOCKED")
        return 0

    dump(result, os.path.join(a.out, "result.json"))
    dump(arts["index"], os.path.join(a.out, "search_index.json"))
    write_csv(os.path.join(a.out, "annotations.csv"),
              ["annotation_id", "doc_id", "type", "page", "quote", "comment", "color",
               "color_meaning", "label", "anchor_status", "anchor_start", "anchor_end",
               "needs_review", "source_file", "source_ref", "merge_basis"],
              [{"annotation_id": x["annotation_id"], "doc_id": x.get("doc_id"),
                "type": x.get("type"), "page": x.get("page"), "quote": x.get("quote"),
                "comment": x.get("comment"), "color": x.get("color"),
                "color_meaning": x.get("color_meaning"), "label": x.get("label"),
                "anchor_status": (x.get("anchor") or {}).get("status"),
                "anchor_start": (x.get("anchor") or {}).get("start"),
                "anchor_end": (x.get("anchor") or {}).get("end"),
                "needs_review": x.get("needs_review"),
                "source_file": (x.get("source") or {}).get("file"),
                "source_ref": (x.get("source") or {}).get("ref"),
                "merge_basis": x.get("merge_basis")} for x in arts["annotations"]])
    write_csv(os.path.join(a.out, "notes.csv"),
              ["note_id", "note_type", "title", "claim", "doc_ids", "page", "annotation_ids",
               "support_status", "tags", "needs_review"],
              [{"note_id": n["note_id"], "note_type": n["note_type"], "title": n["title"],
                "claim": n["claim"], "doc_ids": ";".join(n["doc_ids"]), "page": n["page"],
                "annotation_ids": ";".join(n["annotation_ids"]),
                "support_status": n["support_status"], "tags": ";".join(n["tags"]),
                "needs_review": n["needs_review"]} for n in arts["notes"]])
    write_csv(os.path.join(a.out, "links.csv"),
              ["link_id", "from_note", "to_note", "basis", "shared", "confidence",
               "accepted", "reason"],
              [{"link_id": l["link_id"], "from_note": l["from_note"],
                "to_note": l["to_note"], "basis": l["basis"],
                "shared": ";".join(l["shared"]), "confidence": l["confidence"],
                "accepted": l["accepted"], "reason": l["reason"]} for l in arts["links"]])
    if arts["search_results"]:
        write_csv(os.path.join(a.out, "search_results.csv"),
                  ["question_id", "query", "filters", "rank", "note_id", "score", "title",
                   "doc_ids", "page", "anchor_status"],
                  [{"question_id": r["question_id"], "query": r["query"],
                    "filters": json.dumps(r["filters"], ensure_ascii=False),
                    "rank": r["rank"], "note_id": r["note_id"], "score": r["score"],
                    "title": r["title"], "doc_ids": ";".join(r["doc_ids"] or []),
                    "page": r["page"], "anchor_status": r["anchor_status"]}
                   for r in arts["search_results"]])
    else:
        stale = os.path.join(a.out, "search_results.csv")
        if os.path.exists(stale):
            os.remove(stale)  # 输出目录复用时，清掉上一轮遗留、与本次 result 不一致的产物
    with open(os.path.join(a.out, "audit_report.md"), "w", encoding="utf-8") as fh:
        fh.write(audit_md(result))
    dump({"version": core.VERSION, "generated_at": core.now_iso(),
          "case_id": result["case_id"], "status": result["status"],
          "inputs": [{"path": e["path"], "sha256": e["sha256"]} for e in result["input_inventory"]],
          "counts": {"documents": len(result["documents"]),
                     "annotations": len(result["annotations"]),
                     "notes": len(result["notes"]), "links": len(result["links"])},
          "validation": result["validation"]},
         os.path.join(a.out, "run_manifest.json"))
    with open(os.path.join(a.work, "run_log.json"), "w", encoding="utf-8") as fh:
        json.dump(result["operations_log"], fh, ensure_ascii=False, indent=1)
    ok = all(c["pass"] for c in result["validation"]["checks"])
    print("PASS" if ok and result["status"] != "blocked" else
          ("BLOCKED" if result["status"] == "blocked" else "CHECK_FAIL"))
    print("status=%s annotations=%d notes=%d links=%d"
          % (result["status"], len(result["annotations"]), len(result["notes"]),
             len(result["links"])))
    return 0


if __name__ == "__main__":
    sys.exit(main())
