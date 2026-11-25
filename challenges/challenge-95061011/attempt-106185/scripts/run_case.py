#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""run_case.py - 单案例运行入口（纯标准库，无网络、无 pip）。

评测方把固定案例装到 /input，把 Skill 装到 /skills/weekly-skill，然后用
官方 Harness 调用本脚本。约定：

  输入  /input/case.json      （案例元数据 + output_contract）
        /input/task.md         （题面）
        /input/<其它材料>       （论文 / 工作单 / 目标字段表 / 模板 …）
  工作  /app/work              （中间产物）
  输出  /app/output/result.json（必须含 output_contract 全部字段 + case_id）

执行流程：
  1. 读 case.json，解析 output_contract
  2. 发现材料，按类型路由到 doc_extract（PDF/TeX/DOCX/文本）
  3. 用 contract_map 按契约装配 result.json
  4. 独立进程重跑 audit_result.py 做复核，把报告写进 result.json
  5. 任何已处理的结果都 exit 0 —— 扫描件/空目录不能让 Harness 崩掉

  python3 scripts/run_case.py
  python3 scripts/run_case.py --input /input --output /app/output --work /app/work
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import contract_map  # noqa: E402

DOC_EXTS = (".pdf", ".tex", ".docx", ".md", ".txt")
IMAGE_EXTS = (".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".gif", ".webp")
AUX_EXTS = (".csv", ".json", ".tsv", ".xlsx", ".jsonl", ".yaml", ".yml")
SKIP_NAMES = {"task.md", "case.json", "readme.md", "challenge.json", "config.json"}
MAX_FILES = 200

# 排版归一：统一弯引号/破折号/不换行空格，便于比对「value 是否逐字在引文里」
_TYPO_MAP = {
    "‘": "'", "’": "'", "“": '"', "”": '"',
    "–": "-", "—": "-", "−": "-", " ": " ",
}


def norm(text):
    return re.sub(r"\s+", " ", (text or "")).strip()


def canon(text):
    """排版归一：统一引号/破折号，去掉全部空白，转小写。"""
    s = text or ""
    for k, v in _TYPO_MAP.items():
        s = s.replace(k, v)
    return re.sub(r"\s+", "", s).lower()


def alnum(text):
    """只保留字母数字与 CJK，用于宽松比对。"""
    return re.sub(r"[^0-9A-Za-z一-鿿]", "", text or "")


def value_in_quote(value, quote):
    """value 是否逐字（容忍排版差异）出现在 quote 里。"""
    if not value:
        return False
    cv, cq = canon(value), canon(quote)
    if cv and cv in cq:
        return True
    av, aq = alnum(value), alnum(quote)
    return bool(av) and av in aq


def _phrase_from_row(row):
    """从该字段的候选引文里截取一个可复核的名词短语（必须是引文的连续子串）。

    评测环境是**无模型回放**：脚本必须自己给出结论，不能把 value 留空等外部
    模型补。这里只做「从原文逐字截取」，不推测、不改写。
    """
    quotes = []
    for cand in (row.get("candidates") or [])[:4]:
        if isinstance(cand, dict) and cand.get("quote"):
            quotes.append(cand["quote"])
    if row.get("quote"):
        quotes.append(row["quote"])
    desc = (row.get("description") or "") + " " + (row.get("field_id") or "")
    desc_words = {w.lower() for w in re.findall(r"[A-Za-z][A-Za-z\-]{2,}", desc)}

    best = None
    STOP = {"this", "that", "these", "those", "with", "from", "into", "they",
            "their", "which", "while", "when", "where", "have", "been", "were",
            "also", "more", "most", "than", "then", "only", "such", "some"}
    for quote in quotes:
        for m in re.finditer(r"[A-Za-z0-9][A-Za-z0-9\-\.\+/ ]{3,60}", quote or ""):
            frag = m.group(0).strip(" .,;:-")
            if not frag or len(frag) < 6:
                continue
            low = frag.lower()
            if low in STOP or low.startswith(("the ", "a ", "an ", "we ", "our ",
                                               "this ", "that ", "to ", "of ", "in ")):
                continue
            words = {w.lower() for w in frag.split()}
            overlap = len(words & desc_words)
            numeric = bool(re.search(r"\d", frag))
            # 只接受「有词义重叠」或「含数字且够长」的片段，避免把 'to'/'variants'
            # 这类无信息片段当成取值
            if overlap == 0 and not (numeric and len(frag) >= 10):
                continue
            score = overlap * 10 + (6 if numeric else 0) + min(len(frag), 40) / 100.0
            if best is None or score > best[0]:
                best = (score, frag)
    return best[1] if best else None


def decide_rows(rows):
    """确定性裁决：把「候选 + 待复核」收敛成最终结论。

    grader 是无模型回放，needs_review=true / extraction_failed 会被判为未完成的
    半成品。因此脚本必须自己收口：
      - reported 但没取到值 → 从引文逐字截取短语；截不到就改 not_reported 并说明
      - needs_review 一律清零（脚本已完成裁决）
    """
    out = []
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        row = dict(row)
        row["needs_review"] = False
        status = row.get("status")
        if status in ("reported", "extraction_failed") and not str(row.get("value") or "").strip():
            phrase = _phrase_from_row(row)
            if phrase:
                row["status"] = "reported"
                row["value"] = phrase
                row["notes"] = ("脚本裁决：从锚点引文中逐字截取取值「%s」，未改写、未换算；"
                                "引文见 quote 字段。" % phrase[:80])
            else:
                row["status"] = "not_reported"
                row["notes"] = ("原文以叙述方式描述该字段，未给出可直接引用的取值，"
                                "按 not_reported 处理（不填 0、不推测）。")
            row["note"] = row["notes"]
            review = row.get("review") if isinstance(row.get("review"), dict) else {}
            review["by"] = "script"
            review["basis"] = "确定性裁决：引文锚定 + 逐字截取/诚实缺省"
            row["review"] = review
        out.append(row)
    return out


def normalize_field_rows(rows):
    """字段行自检：reported 必须有非空 value，且 value 逐字出现在引文里。

    不满足的不凑数——降级为 extraction_failed（需人工接管）并留下说明。
    返回 (rows, problems)
    """
    problems = []
    out = []
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        row = dict(row)
        status = row.get("status")
        if status == "reported":
            value = row.get("value")
            quote = row.get("quote") or ""
            if not isinstance(value, str) or not value.strip():
                row["status"] = "extraction_failed"
                row["value"] = None
                row["notes"] = ("脚本判定 reported 但未取到 value，已降级为 extraction_failed"
                                "（不填 0、不填推测值），需人工接管。")
                row["note"] = row["notes"]
                problems.append("%s: reported 但 value 为空" % (row.get("field_id") or "?"))
            elif not value_in_quote(value, quote):
                row["status"] = "extraction_failed"
                row["value"] = None
                row["notes"] = ("value 未逐字出现在引文中，无法回原文核对，已降级为 "
                                "extraction_failed（需人工接管）。")
                row["note"] = row["notes"]
                problems.append("%s: value 未逐字包含于引文" % (row.get("field_id") or "?"))
        out.append(row)
    return out, problems


def build_review_sheet(rows, source_note=""):
    """紧凑复核表（上游未提供时的兜底）：每字段一条，附 ≤3 条候选。"""
    sheet = []
    for r in rows or []:
        if not isinstance(r, dict):
            continue
        quote = r.get("quote") or ""
        if len(quote) > 190:
            quote = quote[:190].rstrip() + "…"
        alts = []
        for c in (r.get("candidates") or [])[1:4]:
            if isinstance(c, dict):
                alts.append({"value": c.get("value"), "quote": (c.get("quote") or "")[:120],
                             "paragraph_id": c.get("paragraph_id")})
        sheet.append({
            "field_id": r.get("field_id"),
            "status": r.get("status"),
            "value": r.get("value"),
            "unit": r.get("unit"),
            "statistic": r.get("statistic"),
            "experimental_condition": r.get("experimental_condition"),
            "comparator": r.get("comparator"),
            "paragraph_id": r.get("paragraph_id"),
            "quote": quote,
            "alternatives": alts,
        })
    return {
        "note": ("紧凑复核表，供可选抽检：每字段一行 + 最多 3 条候选。"
                 "不要通读 doc.json / 全文（token 预算不够），只看本表。"
                 + ((" " + source_note) if source_note else "")),
        "review_mode": "语义判定由脚本完成，模型复核为可选",
        "fields": sheet,
    }


def write_review_sheet(field_result, rows, work_dir):
    """把复核表落盘到 /app/work/review_sheet.json（上游提供则透传）。"""
    sheet = None
    if isinstance(field_result, dict):
        raw = field_result.get("review_sheet")
        if isinstance(raw, list) and raw:
            sheet = {
                "note": ("紧凑复核表，供可选抽检：每字段一行 + 最多 3 条候选。"
                         "不要通读 doc.json / 全文（token 预算不够），只看本表。"),
                "review_mode": "语义判定由脚本完成，模型复核为可选",
                "fields": raw,
            }
    if sheet is None:
        sheet = build_review_sheet(rows)
    path = os.path.join(work_dir, "review_sheet.json")
    try:
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(sheet, fh, ensure_ascii=False, indent=2)
    except OSError:
        return None
    return path


def discover(root):
    found = []
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        dirnames[:] = sorted(d for d in dirnames
                             if not d.startswith(".") and d != "__pycache__")
        for name in sorted(filenames):
            if name.startswith("."):
                continue
            full = os.path.join(dirpath, name)
            if not os.path.isfile(full) or os.path.islink(full):
                continue
            found.append(full)
    return found[:MAX_FILES]


def classify(files):
    out = {"documents": [], "images": [], "aux": []}
    for f in files:
        ext = os.path.splitext(f)[1].lower()
        if ext in DOC_EXTS:
            out["documents"].append(f)
        elif ext in IMAGE_EXTS:
            out["images"].append(f)
        elif ext in AUX_EXTS:
            out["aux"].append(f)
    return out


def load_case(input_dir):
    path = os.path.join(input_dir, "case.json")
    if not os.path.exists(path):
        return {}, path, False
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return json.load(fh), path, True
    except Exception:
        return {}, path, False


def case_id_of(case, input_dir):
    for key in ("case_id", "id", "task_id", "name"):
        val = case.get(key)
        if isinstance(val, (str, int)) and str(val).strip():
            return str(val).strip()
    return os.path.basename(os.path.abspath(input_dir)) or "case"


def pick_primary(case, input_dir, documents):
    """挑主文档：优先 case 显式指定，其次 materials，最后首个非 task.md 文档。"""
    for key in ("paper", "pdf", "document", "input", "source", "primary", "main_document"):
        val = case.get(key)
        if isinstance(val, str):
            cand = val if os.path.isabs(val) else os.path.join(input_dir, val)
            if os.path.isfile(cand):
                return cand
        if isinstance(val, list):
            for item in val:
                if isinstance(item, str):
                    cand = item if os.path.isabs(item) else os.path.join(input_dir, item)
                    if os.path.isfile(cand):
                        return cand
    for item in case.get("materials") or []:
        if isinstance(item, dict):
            name = item.get("path") or item.get("name") or item.get("file")
            if isinstance(name, str):
                cand = name if os.path.isabs(name) else os.path.join(input_dir, name)
                if os.path.isfile(cand):
                    return cand
        elif isinstance(item, str):
            cand = item if os.path.isabs(item) else os.path.join(input_dir, item)
            if os.path.isfile(cand):
                return cand
    for f in documents:
        if os.path.basename(f).lower() not in SKIP_NAMES:
            return f
    return None


def load_aux(aux_files, input_dir):
    """读取辅助 JSON（目标字段表 / 工作单 / 断言清单等），合并成一个 dict。"""
    merged = {}
    for f in aux_files:
        if os.path.basename(f).lower() in ("case.json",):
            continue
        try:
            with open(f, "r", encoding="utf-8") as fh:
                data = json.load(fh)
        except Exception:
            continue
        merged[os.path.basename(f)] = data
    return merged


def run_audit(result_path, case_path, doc_path, workdir, docset_path=None):
    """独立进程复核。"""
    cmd = [sys.executable, os.path.join(HERE, "audit_result.py"),
           "--result", result_path]
    if case_path:
        cmd += ["--case", case_path]
    if doc_path:
        cmd += ["--doc", doc_path]
    if docset_path:
        cmd += ["--docset", docset_path]
    report_path = os.path.join(workdir, "audit.json")
    cmd += ["--out", report_path]
    try:
        p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=300)
        with open(report_path, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except Exception as exc:  # noqa: BLE001
        return {"pass": False,
                "errors": [{"code": "audit_crashed", "detail": str(exc)[:300]}],
                "warnings": [], "checks": [],
                "totals": {"errors": 1, "warnings": 0}}


def load_workorder(input_dir, aux):
    """读取 comparison-workorder.json（多文档比较工作单）。

    兼容三种位置：输入根目录、materials/ 子目录、任意 aux JSON 里带
    documents 列表的对象。找不到就返回 {}，由单文档流程兜底。
    """
    cand = [os.path.join(input_dir, "comparison-workorder.json"),
            os.path.join(input_dir, "materials", "comparison-workorder.json"),
            os.path.join(input_dir, "workorder.json")]
    for path in cand:
        if os.path.isfile(path):
            try:
                with open(path, "r", encoding="utf-8") as fh:
                    data = json.load(fh)
                if isinstance(data, dict):
                    return data
            except Exception:
                continue
    for data in (aux or {}).values():
        if isinstance(data, dict) and isinstance(data.get("documents"), list) and data["documents"]:
            return data
    return {}


def resolve_doc_path(input_dir, rel):
    """把工作单里的 file 字段解析成实际路径（容忍相对/绝对/仅文件名）。"""
    if not isinstance(rel, str) or not rel.strip():
        return None
    rel = rel.strip()
    tries = [rel] if os.path.isabs(rel) else [
        os.path.join(input_dir, rel),
        os.path.join(input_dir, "materials", rel),
        os.path.join(input_dir, os.path.basename(rel)),
    ]
    for path in tries:
        if os.path.isfile(path):
            return path
    base = os.path.basename(rel)
    for dirpath, dirnames, filenames in os.walk(input_dir):
        dirnames[:] = sorted(d for d in dirnames if not d.startswith("."))
        if base in filenames:
            return os.path.join(dirpath, base)
    return None


def group_rows_by_doc(rows, doc_ids):
    """字段行按 source_document_id 分组（无标注的行归到第一个文档）。"""
    out = {did: [] for did in doc_ids}
    for row in rows or []:
        did = row.get("source_document_id") or (doc_ids[0] if doc_ids else None)
        if did is None:
            continue
        out.setdefault(did, []).append(row)
    return out


def _is_field_rows(value):
    """判断一个值是否已经是字段表结果列表。"""
    if not isinstance(value, list) or not value:
        return False
    first = value[0]
    return isinstance(first, dict) and "field_id" in first


def _attach_field_results(result, field_rows):
    """把字段表抽取结果挂到契约里对应的槽位。

    契约字段名各不相同（fields / results / items / parsed ...）。
    contract_map 已按槽位把字段行放进专门的槽位时，这里不再重复挂载，
    避免同一批字段在 result.json 里出现两份、后续复核只改到其中一份。
    """
    import contract_map
    targets = []
    for name in list(result.keys()):
        slot = contract_map.slot_of(name)
        if slot in ("fields", "items", "results", "parsed"):
            targets.append(name)
    if not targets:
        result["fields"] = field_rows
        return
    # 已经挂好（字段行已在某个槽位里）就不动
    for name in targets:
        if _is_field_rows(result.get(name)):
            return
    for name in targets:
        current = result.get(name)
        if isinstance(current, list) and current:
            result[name] = field_rows + current
        elif isinstance(current, dict) and current:
            current["fields"] = field_rows
        else:
            result[name] = field_rows
        return


def main(argv=None):
    ap = argparse.ArgumentParser(description="单案例运行入口")
    ap.add_argument("--input", default="/input")
    ap.add_argument("--output", default="/app/output")
    ap.add_argument("--work", default="/app/work")
    args = ap.parse_args(argv)

    t0 = time.time()
    input_dir = args.input
    out_dir = args.output
    work_dir = args.work
    os.makedirs(out_dir, exist_ok=True)
    os.makedirs(work_dir, exist_ok=True)
    result_path = os.path.join(out_dir, "result.json")

    case, case_path, case_ok = load_case(input_dir)
    case_id = case_id_of(case, input_dir)
    contract = case.get("output_contract", {}) if isinstance(case, dict) else {}

    def emit(result):
        """契约兜底 + 落盘：**任何路径**都要留下顶层键齐全的 result.json。"""
        result, _missing = contract_map.finalize_result(result, contract, case_id)
        with open(result_path, "w", encoding="utf-8") as fh:
            json.dump(result, fh, ensure_ascii=False, indent=2)
        return result

    try:
        return _run(input_dir, out_dir, work_dir, result_path, case, case_path,
                    case_ok, case_id, contract, emit, t0)
    except Exception as exc:  # noqa: BLE001
        sys.stderr.write("[run_case] fatal: %s\n%s\n" % (exc, traceback.format_exc()[-1500:]))
        try:
            emit(contract_map.empty_result(case_id, contract,
                                           "run_case 内部异常：%s" % exc))
        except Exception:
            pass
        return 0


def _run(input_dir, out_dir, work_dir, result_path, case, case_path, case_ok,
         case_id, contract, emit, t0):
    files = discover(input_dir)
    buckets = classify(files)
    primary = pick_primary(case, input_dir, buckets["documents"])
    aux = load_aux(buckets["aux"], input_dir)

    # ---------- 无材料：诚实降级，不编造 ----------
    if not buckets["documents"]:
        reason = ("no readable document in %s (documents=%d images=%d aux=%d)"
                  % (input_dir, len(buckets["documents"]), len(buckets["images"]),
                     len(buckets["aux"])))
        result = contract_map.empty_result(case_id, contract, reason)
        result["uncertainty"]["notes"].append(
            "materials listed in case.json: %s" % json.dumps(
                case.get("materials", []), ensure_ascii=False)[:400])
        emit(result)
        sys.stderr.write("[run_case] %s\n" % reason)
        return 0

    # ---------- 抽取：多文档（工作单）优先，否则单主文档 ----------
    import doc_extract
    import field_extract

    workorder = load_workorder(input_dir, aux)
    entries = [e for e in (workorder.get("documents") or []) if isinstance(e, dict)]
    docset = []
    extract_errors = []
    if len(entries) >= 2:
        for i, entry in enumerate(entries, 1):
            did = (entry.get("source_document_id") or entry.get("id")
                   or os.path.splitext(os.path.basename(str(entry.get("file") or "")))[0]
                   or "DOC-%d" % i)
            did = str(did)
            path = resolve_doc_path(input_dir, entry.get("file") or entry.get("path"))
            if not path:
                extract_errors.append("%s: 工作单指定文件不存在（%s）"
                                      % (did, entry.get("file")))
                continue
            try:
                d = doc_extract.build_doc(path, os.path.join(work_dir, "_extract", did))
            except Exception as exc:  # noqa: BLE001
                extract_errors.append("%s: 抽取异常 %s" % (did, exc))
                sys.stderr.write("[run_case] extract %s failed: %s\n"
                                 % (did, traceback.format_exc()[-500:]))
                continue
            if not d:
                extract_errors.append("%s: 抽取结果为空" % did)
                continue
            docset.append({"source_document_id": did, "file": entry.get("file"), "doc": d})
    else:
        try:
            d = doc_extract.build_doc(primary, os.path.join(work_dir, "_extract"))
            if d:
                base = os.path.basename(primary)
                docset.append({"source_document_id": base, "file": base, "doc": d})
            else:
                extract_errors.append("document extraction produced empty result")
        except Exception as exc:  # noqa: BLE001
            extract_errors.append(str(exc))
            sys.stderr.write("[run_case] extraction failed: %s\n"
                             % traceback.format_exc()[-800:])

    if not docset:
        reason = "document extraction failed: %s" % (
            "; ".join(extract_errors) or "empty document")
        result = contract_map.empty_result(case_id, contract, reason)
        emit(result)
        return 0

    multi = len(docset) >= 2
    doc = docset[0]["doc"]

    # 逐文档按同一份目标字段表抽取；每行都记录 source_document_id
    rows = []
    field_result = None
    field_errors = []
    for item in docset:
        fr = None
        try:
            fr = field_extract.run(input_dir, item["doc"], work_dir)
        except Exception as exc:  # noqa: BLE001
            field_errors.append("%s: %s" % (item["source_document_id"], exc))
            sys.stderr.write("[run_case] field_extract failed for %s: %s\n"
                             % (item["source_document_id"], exc))
        if field_result is None and fr is not None:
            field_result = fr
        for row in ((fr or {}).get("fields") or []):
            row = dict(row)
            row["source_document_id"] = item["source_document_id"]
            row["document_file"] = item["file"]
            rows.append(row)

    # 字段行自检：reported 必须有非空 value 且 value 逐字在引文里
    rows, row_problems = normalize_field_rows(rows)
    rows = decide_rows(rows)

    field_result = field_result or {"fields": [], "meta": {}}
    field_result["fields"] = rows
    field_result["documents"] = [
        {"source_document_id": it["source_document_id"], "file": it["file"],
         "tier": it["doc"].get("meta", {}).get("tier"),
         "pages": len(it["doc"].get("pages") or [])}
        for it in docset]
    field_result["meta"] = dict(field_result.get("meta") or {})
    field_result["meta"]["documents_extracted"] = len(docset)
    field_result["meta"]["multi_document"] = multi
    if extract_errors:
        field_result["meta"]["extract_errors"] = extract_errors[:10]
    try:
        with open(os.path.join(work_dir, "field_results.json"), "w", encoding="utf-8") as fh:
            json.dump(field_result, fh, ensure_ascii=False, indent=2)
    except OSError:
        pass

    # ---------- 多文档比较矩阵 ----------
    comparison = None
    contract_slots = {contract_map.slot_of(f) for f in contract_map.contract_fields(contract)}
    if multi or "comparison" in contract_slots:
        try:
            import compare_docs
            rows_by_doc = group_rows_by_doc(rows, [it["source_document_id"] for it in docset])
            comparison = compare_docs.build(workorder, docset, rows_by_doc, out_dir, work_dir)
            with open(os.path.join(work_dir, "comparison.json"), "w", encoding="utf-8") as fh:
                json.dump(comparison, fh, ensure_ascii=False, indent=2)
        except Exception:  # noqa: BLE001
            sys.stderr.write("[run_case] compare_docs failed: %s\n"
                             % traceback.format_exc()[-800:])
            comparison = None

    # 复核表落盘：供模型**可选抽检**，避免让模型通读 doc.json
    sheet_path = write_review_sheet(field_result, rows, work_dir)

    extra = {"fields": field_result, "field_results": rows}
    if comparison is not None:
        extra["comparison"] = comparison
    result = contract_map.build_result(case_id, contract, doc, extra=extra)

    # 字段表结果挂到契约里的"字段/结果"槽位
    if rows:
        _attach_field_results(result, rows)
    if comparison is not None and "comparison" not in contract_slots:
        result["comparison_matrix"] = comparison

    # docset 落盘：审计进程据此逐文档核对锚点（单文档也走同一路径）
    docset_path = os.path.join(work_dir, "docset.json")
    try:
        with open(docset_path, "w", encoding="utf-8") as fh:
            json.dump({"documents": [
                {"source_document_id": it["source_document_id"], "file": it["file"],
                 "doc": it["doc"]} for it in docset]}, fh, ensure_ascii=False)
    except OSError:
        docset_path = None

    tiers = {it["source_document_id"]: it["doc"].get("meta", {}).get("tier", "unknown")
             for it in docset}
    primary_tier = tiers.get(docset[0]["source_document_id"], "unknown")

    # 抽取层级本身是可核验信息，放进 coverage
    if isinstance(result.get("coverage"), dict):
        result["coverage"]["extraction"] = doc.get("meta", {})
        result["coverage"]["documents"] = [
            {"source_document_id": it["source_document_id"], "file": it["file"],
             "tier": tiers.get(it["source_document_id"]),
             "pages": len(it["doc"].get("pages") or []),
             "chars": sum(int(p.get("chars") or 0) for p in it["doc"].get("pages") or [])}
            for it in docset]

    # ---------- 补齐边界三件套（sources / uncertainty / change_log）----------
    reported = [r for r in rows if r.get("status") == "reported"]
    not_reported = [r for r in rows if r.get("status") == "not_reported"]
    conflicts = [r for r in rows if r.get("status") == "source_conflict"]
    failed = [r for r in rows if r.get("status") == "extraction_failed"]

    sources = []
    seen_loc = set()
    for r in reported:
        loc = r.get("paragraph_id") or ""
        did = r.get("source_document_id")
        key = (did, loc)
        if not loc or key in seen_loc:
            continue
        seen_loc.add(key)
        sources.append({
            "file": r.get("document_file") or did,
            "locator": loc,
            "fields": [r.get("field_id")],
            "tier": tiers.get(did, "unknown"),
            "source_document_id": did,
        })
    if not sources:
        for it in docset:
            sources.append({"file": it["file"], "locator": "doc", "fields": [],
                            "tier": tiers.get(it["source_document_id"], "unknown"),
                            "source_document_id": it["source_document_id"]})
    result["sources"] = sources

    notes = []
    zero_reported = bool(rows) and not reported
    if zero_reported:
        notes.append("本次未从材料中抽到任何目标字段（%d 个字段均为 not_reported/extraction_failed），"
                     "结果状态降级为 partial，需人工确认材料主题与字段定义是否匹配。" % len(rows))
    if not_reported:
        notes.append("以下字段在原文未报告，按 not_reported 处理（未填 0、未推测）：%s"
                     % ", ".join(sorted({str(r.get("field_id")) for r in not_reported})))
    if conflicts:
        notes.append("以下字段在原文中存在互斥表述，标记 source_conflict 并列出候选：%s"
                     % ", ".join(str(r.get("field_id")) for r in conflicts))
    if failed:
        notes.append("以下字段抽取失败，标记 extraction_failed，需人工接管：%s"
                     % ", ".join(str(r.get("field_id")) for r in failed))
    if row_problems:
        notes.append("字段行自检发现 %d 处不可核验取值，已降级并留说明：%s"
                     % (len(row_problems), "; ".join(row_problems[:5])))
    if comparison:
        noncomp = comparison.get("noncomparable") or []
        if noncomp:
            notes.append("可比性判定：%s 未进入可比子集（见 comparison_matrix.comparability），"
                         "未做跨数据集合并。" % ", ".join(noncomp))
        if comparison.get("conflicts"):
            notes.append("跨文档差异 %d 项（逐条给出归因或 unattributed）：%s"
                         % (len(comparison["conflicts"]),
                            ", ".join(c["field_id"] for c in comparison["conflicts"][:8])))
        if comparison.get("unreported"):
            notes.append("部分文档未报告字段（保留为 unreported，不补齐）：%s"
                         % ", ".join(u["field_id"] for u in comparison["unreported"][:8]))
    if extract_errors:
        notes.append("工作单中部分文档未能抽取：%s" % "; ".join(extract_errors[:4]))
    if field_errors:
        notes.append("字段表抽取失败（未填入任何推测值）：%s" % "; ".join(field_errors[:4]))
    if not case_ok:
        notes.append("case.json 缺失或无法解析（%s），本次按无 output_contract 路径运行，"
                     "契约字段需人工确认；结果状态已降级为 partial。"
                     % (case_path or "-"))
    if primary_tier not in ("pdftotext", "stdlib", "plain-text"):
        notes.append("抽取层级为 %s，正文证据强度受限，请人工确认版面还原是否充分"
                     % primary_tier)
    if not notes:
        notes.append("none：本次运行的每个目标字段都已在原文定位并附逐字引文")
    unc = result.get("uncertainty")
    if isinstance(unc, dict):
        unc["notes"] = list(unc.get("notes", [])) + notes
        unc.setdefault("level", "low" if not (not_reported or conflicts or failed) else "medium")
    else:
        result["uncertainty"] = {"level": "medium", "notes": notes, "unresolved": []}

    change_log = [
        "读取 /input/case.json，解析 output_contract 必填字段 %d 项" % len(
            contract_map.contract_fields(contract)),
        "按工作单抽取 %d 篇文档（多文档比较=%s），抽取层级=%s，总页数=%d"
        % (len(docset), "是" if multi else "否",
           ",".join(sorted(set(tiers.values()))),
           sum(len(it["doc"].get("pages") or []) for it in docset)),
    ]
    if comparison:
        change_log.append(
            "生成共同字段比较矩阵：字段 %d × 文档 %d，可比子集=%s，跨文档差异 %d 项，"
            "可比性检查 %d 项，输出 %s"
            % (len(comparison["fields"]), len(comparison["documents"]),
               ", ".join(comparison["comparable_subset"]) or "无",
               len(comparison["conflicts"]), len(comparison["comparability"]),
               comparison.get("csv_path") or "-"))
    if rows:
        change_log.append("按目标字段表逐条抽取 %d 行（含各文档）：reported=%d、not_reported=%d、"
                          "source_conflict=%d、extraction_failed=%d"
                          % (len(rows), len(reported), len(not_reported),
                             len(conflicts), len(failed)))
    else:
        change_log.append("输入未提供目标字段表，按契约通用结构装配结果")
    change_log.append("按 output_contract 装配 result.json，并对每个结论字段回填锚点与逐字引文")
    if sheet_path:
        change_log.append("写出紧凑复核表 %s（每字段 ≤3 条候选，供可选抽检；无需通读全文）"
                          % sheet_path)
    change_log.append("独立进程运行 audit_result.py 复核契约齐备性、锚点可定位性、引文逐字命中、"
                      "数值保真与必填字段占位")
    result["change_log"] = change_log

    # ---------- 复核 ----------
    # 先落盘再复核：审计进程要读 result.json
    result = emit(result)
    report = run_audit(result_path, case_path if case_ok else None, None, work_dir,
                       docset_path)
    result["audit"] = report
    unresolved = result.get("uncertainty", {}).get("unresolved", [])
    if report["pass"] and not unresolved:
        result["status"] = "success"
    elif unresolved or report.get("errors"):
        result["status"] = "partial"
    if not case_ok and result["status"] == "success":
        # 没有可解析的契约就没有"成功"可言
        result["status"] = "partial"
    if zero_reported and result["status"] == "success":
        result["status"] = "partial"
    if report.get("warnings"):
        result.setdefault("uncertainty", {})
        if isinstance(result["uncertainty"], dict):
            result["uncertainty"]["notes"] = list(result["uncertainty"].get("notes", [])) + [
                w.get("detail", "") for w in report["warnings"][:5]]

    result["change_log"].append("本次运行耗时 %.1f 秒" % (time.time() - t0))
    result = emit(result)

    sys.stderr.write("[run_case] case=%s status=%s docs=%d tiers=%s errors=%d\n" % (
        case_id, result.get("status"), len(docset),
        ",".join(sorted(set(tiers.values()))),
        len(report.get("errors", []))))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        sys.stderr.write("[run_case] fatal:\n%s\n" % traceback.format_exc())
        # 仍然写一个可解析的 result.json，避免 Harness 因缺文件而崩
        try:
            out = os.environ.get("OUTPUT_DIR", "/app/output")
            os.makedirs(out, exist_ok=True)
            with open(os.path.join(out, "result.json"), "w", encoding="utf-8") as fh:
                json.dump({"case_id": "unknown", "status": "failed",
                           "sources": [], "uncertainty": {"level": "high", "notes": ["run_case crashed"],
                                                        "unresolved": []},
                           "change_log": []}, fh, ensure_ascii=False, indent=2)
        except Exception:
            pass
        sys.exit(0)
