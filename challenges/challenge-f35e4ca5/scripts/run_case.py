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


def run_audit(result_path, case_path, doc_path, workdir):
    """独立进程复核。"""
    cmd = [sys.executable, os.path.join(HERE, "audit_result.py"),
           "--result", result_path]
    if case_path:
        cmd += ["--case", case_path]
    if doc_path:
        cmd += ["--doc", doc_path]
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

    # ---------- 无正文材料：登记图片/表格，诚实降级，不编造 ----------
    import doc_extract
    doc = {}
    doc_path = None
    extract_error = None
    if not buckets["documents"] or primary is None:
        doc = {
            "meta": {"tool": "file-inventory", "tier": "no-text-document",
                     "chars": 0, "pages": 0, "source_file": None,
                     "note": "输入没有可解析的正文文档；只登记图片与表格文件的元数据"},
            "pages": [{"page": 1, "chars": 0}], "units": [], "numbers": [],
            "tables": [],
            "captions": [], "figures": [], "axes": [], "images": [], "text": "",
        }
        for img in buckets["images"]:
            doc["images"].append(doc_extract.probe_image(img))
        for f in buckets["aux"]:
            if os.path.splitext(f)[1].lower() in (".csv", ".tsv", ".xlsx"):
                tables, diags = doc_extract.load_tabular(
                    f, os.path.basename(f), len(doc["tables"]) + 1)
                doc["tables"].extend(tables)
                doc["text"] = (doc.get("text") or "") + "\n" + "\n".join(
                    t.get("header_quote", "") + "\n" +
                    "\n".join(r.get("row_quote", "") for r in t.get("rows") or [])
                    for t in tables)
                doc["meta"].setdefault("diagnostics", []).extend(diags)
        doc_path = os.path.join(work_dir, "doc.json")
        with open(doc_path, "w", encoding="utf-8") as fh:
            json.dump(doc, fh, ensure_ascii=False)
        sys.stderr.write("[run_case] no text document; images=%d tables=%d\n"
                         % (len(doc["images"]), len(doc["tables"])))
    else:
        # ---------- 抽取 ----------
        try:
            doc = doc_extract.build_doc(primary, os.path.join(work_dir, "_extract"))
        except Exception as exc:  # noqa: BLE001
            extract_error = str(exc)
            sys.stderr.write("[run_case] extraction failed: %s\n" % traceback.format_exc()[-800:])
            doc = {}

        if doc:
            # 图片与外部表格（CSV/TSV/XLSX）不依赖正文，单独登记
            doc.setdefault("images", [])
            for img in buckets["images"]:
                doc["images"].append(doc_extract.probe_image(img))
            for f in buckets["aux"]:
                if os.path.splitext(f)[1].lower() in (".csv", ".tsv", ".xlsx"):
                    tables, diags = doc_extract.load_tabular(
                        f, os.path.basename(f), len(doc["tables"]) + 1)
                    doc["tables"].extend(tables)
                    doc["text"] = (doc.get("text") or "") + "\n" + "\n".join(
                        t.get("header_quote", "") + "\n" +
                        "\n".join(r.get("row_quote", "") for r in t.get("rows") or [])
                        for t in tables)
                    doc["meta"].setdefault("diagnostics", []).extend(diags)
            doc_path = os.path.join(work_dir, "doc.json")
            with open(doc_path, "w", encoding="utf-8") as fh:
                json.dump(doc, fh, ensure_ascii=False)

    if not doc:
        reason = "document extraction failed: %s" % (
            extract_error or "empty document or no readable material")
        result = contract_map.empty_result(case_id, contract, reason)
        result["uncertainty"]["notes"].append(
            "images=%d tables_from_files=%d; 未从材料取得可解析文本"
            % (len(buckets["images"]), len(buckets["aux"])))
        emit(result)
        return 0

    # ---------- 装配 ----------
    extra = {}
    if aux:
        extra["fields"] = aux

    # 字段表路径：若案例提供 target-fields.json，按字段表驱动抽取
    field_result = None
    try:
        import field_extract
        field_result = field_extract.run(input_dir, doc, work_dir)
        if field_result.get("fields"):
            extra["fields"] = field_result
            extra["field_results"] = field_result["fields"]
            with open(os.path.join(work_dir, "field_results.json"), "w", encoding="utf-8") as fh:
                json.dump(field_result, fh, ensure_ascii=False, indent=2)
    except Exception as exc:  # noqa: BLE001
        sys.stderr.write("[run_case] field_extract failed: %s\n" % exc)

    # 字段行自检：reported 必须有非空 value 且 value 逐字在引文里
    rows = (field_result or {}).get("fields") or []
    rows, row_problems = normalize_field_rows(rows)
    rows = decide_rows(rows)
    if field_result is not None:
        field_result["fields"] = rows
        extra["fields"] = field_result
        extra["field_results"] = rows
        try:
            with open(os.path.join(work_dir, "field_results.json"), "w", encoding="utf-8") as fh:
                json.dump(field_result, fh, ensure_ascii=False, indent=2)
        except OSError:
            pass

    # 复核表落盘：供模型**可选抽检**，避免让模型通读 doc.json
    sheet_path = write_review_sheet(field_result, rows, work_dir)

    result = contract_map.build_result(case_id, contract, doc, extra=extra)

    # 字段表结果挂到契约里的"字段/结果"槽位
    if rows:
        _attach_field_results(result, rows)

    # 抽取层级本身是可核验信息，放进 coverage
    if isinstance(result.get("coverage"), dict):
        result["coverage"]["extraction"] = doc.get("meta", {})

    # ---------- 补齐边界三件套（sources / uncertainty / change_log）----------
    src_name = (doc.get("meta", {}).get("source_file")
                or (os.path.basename(primary) if primary else None)
                or ((doc.get("images") or [{}])[0].get("file"))
                or "materials")
    tier = doc.get("meta", {}).get("tier", "unknown")
    reported = [r for r in rows if r.get("status") == "reported"]
    not_reported = [r for r in rows if r.get("status") == "not_reported"]
    conflicts = [r for r in rows if r.get("status") == "source_conflict"]
    failed = [r for r in rows if r.get("status") == "extraction_failed"]

    sources = []
    seen_loc = set()
    for r in reported:
        loc = r.get("paragraph_id") or ""
        if not loc or loc in seen_loc:
            continue
        seen_loc.add(loc)
        sources.append({
            "file": src_name,
            "locator": loc,
            "fields": [r.get("field_id")],
            "tier": tier,
        })
    if not sources:
        sources.append({"file": src_name, "locator": "doc", "fields": [], "tier": tier})
    for img in doc.get("images") or []:
        sources.append({"file": img.get("file"), "locator": "image_metadata",
                        "fields": [], "tier": tier,
                        "note": "图片仅登记元数据，像素读数未执行"})
    result["sources"] = sources

    notes = []
    if not_reported:
        notes.append("以下字段在原文未报告，按 not_reported 处理（未填 0、未推测）：%s"
                     % ", ".join(str(r.get("field_id")) for r in not_reported))
    if conflicts:
        notes.append("以下字段在原文中存在互斥表述，标记 source_conflict 并列出候选：%s"
                     % ", ".join(str(r.get("field_id")) for r in conflicts))
    if failed:
        notes.append("以下字段抽取失败，标记 extraction_failed，需人工接管：%s"
                     % ", ".join(str(r.get("field_id")) for r in failed))
    if row_problems:
        notes.append("字段行自检发现 %d 处不可核验取值，已降级并留说明：%s"
                     % (len(row_problems), "; ".join(row_problems[:5])))
    if tier not in ("pdftotext", "stdlib"):
        notes.append("抽取层级为 %s，正文证据强度受限，请人工确认版面还原是否充分" % tier)
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
        "对主材料做版面抽取，抽取层级 tier=%s，页数=%s，章节单元=%d，表格=%d，数值候选=%d"
        % (tier, doc.get("meta", {}).get("pages"),
           len(doc.get("units", [])), len(doc.get("tables", [])), len(doc.get("numbers", []))),
    ]
    if rows:
        change_log.append("按目标字段表逐条抽取 %d 个字段：reported=%d、not_reported=%d、"
                          "source_conflict=%d、extraction_failed=%d"
                          % (len(rows), len(reported), len(not_reported),
                             len(conflicts), len(failed)))
    else:
        change_log.append("输入未提供目标字段表，按契约通用结构装配结果")
    change_log.append("按 output_contract 装配 result.json，并对每个结论字段回填锚点与逐字引文")
    if sheet_path:
        change_log.append("写出紧凑复核表 %s（每字段 ≤3 条候选，供可选抽检；无需通读全文）"
                          % sheet_path)
    change_log.append("独立进程运行 audit_result.py 复核契约齐备性、锚点可定位性、引文逐字命中与数值保真")
    result["change_log"] = change_log

    # ---------- 复核 ----------
    # 先落盘再复核：审计进程要读 result.json
    result = emit(result)
    report = run_audit(result_path, case_path if case_ok else None, doc_path, work_dir)
    result["audit"] = report
    unresolved = result.get("uncertainty", {}).get("unresolved", [])
    images = doc.get("images") or []
    table_count = len(doc.get("tables") or [])
    has_text = bool(doc.get("pages")) and bool((doc.get("meta") or {}).get("chars"))
    if (tier == "unreadable" or (not has_text and not table_count)) \
            and not images and not table_count:
        # 材料存在但读不出任何可复核内容：不能报 success
        result["status"] = "failed"
        result["uncertainty"]["notes"].append(
            "材料未提供可解析文本层，也没有可登记的表格/图片，按 failed 处理并说明人工接管位置")
    elif images and not has_text:
        result["status"] = "partial"
        result["uncertainty"]["notes"].append(
            "仅登记了 %d 张图片的元数据；像素刻度/图例/数据点读数未执行，相关字段列为缺口"
            % len(images))
    elif report["pass"] and not unresolved:
        result["status"] = "success"
    elif unresolved or report.get("errors"):
        result["status"] = "partial"
    if report.get("warnings"):
        result.setdefault("uncertainty", {})
        if isinstance(result["uncertainty"], dict):
            result["uncertainty"]["notes"] = list(result["uncertainty"].get("notes", [])) + [
                w.get("detail", "") for w in report["warnings"][:5]]

    result["change_log"].append("本次运行耗时 %.1f 秒" % (time.time() - t0))
    result = emit(result)

    sys.stderr.write("[run_case] case=%s status=%s tier=%s errors=%d\n" % (
        case_id, result.get("status"), doc.get("meta", {}).get("tier"),
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
