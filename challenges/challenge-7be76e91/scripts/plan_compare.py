#!/usr/bin/env python3
"""plan_compare.py - 多候选实验方案的横向比较：统一字段 → 硬约束淘汰 → 可复算评分 → 选择与敏感性。

输入（kernel.py init/index 产出）：
  work/case.raw.json（原始 case.json，含结构化候选/资源合同/参数域，可选）
  work/contract.json, work/evidence.json, work/corpus.txt
输出：
  work/draft.json, work/comparison_matrix.csv

两条候选通道，结构化优先：
  A. case.json 的 candidate_plans / plans / candidates（平台组织方常见格式）
  B. 材料文件中的"方案A/B/C""Plan 1/2/3"或按候选文件分组
只从材料抽数与抽证据：评分是"证据计数 + 成本/时间相对位次"，不是拍脑袋的领域判断；
缺证据的维度记 null 并在可用维度内重新归一权重，且写进 uncertainty。
"""
import argparse
import csv
import json
import os
import re

FILE_HDR = re.compile(r"^===== FILE: (.+?) =====$", re.M)
NUM = r"[-+]?\d+(?:\.\d+)?"
UNIT = r"(℃|°C|K|rpm|μL|uL|µL|mL|L|mg|g|kg|mol|mmol|M|mM|%|h|小时|min|分钟|天|d|次|元|万元|USD|\$|人日|人天|盒|瓶|板|孔)"
VAL = re.compile(r"([A-Za-z\u4e00-\u9fa5µμ°%][\w\u4e00-\u9fa5µμ°%·\-/]{0,18})\s*[:：=]\s*(" + NUM + r")\s*(" + UNIT + r")?")
LIMIT = re.compile(r"(?:≤|<=|不超过|最多|上限|最大|max)\s*[:：]?\s*(" + NUM + r")\s*(" + UNIT + r")?")
LIMIT_NAMED = re.compile(
    r"([A-Za-z\u4e00-\u9fa5µμ°%][\w\u4e00-\u9fa5µμ°%·\-/ ]{0,18}?)\s*"
    r"(?:≤|<=|不超过|最多|上限(?:为|是)?|最大(?:为|是)?|max\.?)\s*[:：]?\s*"
    r"(" + NUM + r")\s*(" + UNIT + r")?", re.I)
PLAN_HDR = re.compile(r"(?:方案|候选|plan|candidate|variant|version|版本)\s*([A-Za-z0-9一二三四五六七八九十1-9])", re.I)
PRICE = re.compile(r"([A-Za-z\u4e00-\u9fa5][\w\u4e00-\u9fa5\-]{0,18})?\s*"
                   r"(?:单价|价格|报价|费用|price|cost)?\s*[:：]?\s*(" + NUM + r")\s*(元|万元|USD|\$)\s*"
                   r"(?:/|每|per)\s*(次|小时|h|人日|人天|盒|瓶|板|管|孔|样本|sample|run)", re.I)
BUDGET = re.compile(r"(?:预算|经费|budget|上限)\D{0,10}(" + NUM + r")\s*(元|万元|USD|\$)", re.I)
DAYS = re.compile(r"(" + NUM + r")\s*(天|日|周|weeks?|days?)", re.I)
TOTAL_COST = re.compile(r"(?:总成本|合计|总计|总额|总费用|total)\D{0,8}(" + NUM + r")\s*(元|万元|USD|\$)", re.I)
COST_PAIR = re.compile(r"([A-Za-z\u4e00-\u9fa5][\w\u4e00-\u9fa5\-]{1,18})\s*[×xX*]\s*(" + NUM + r")\s*"
                       r"(盒|瓶|板|次|h|小时|人日|人天|样本|sample|run)", re.I)
UNAVAIL = ["不可用", "停机", "故障", "已满", "未到货", "缺货", "无货", "无法预约", "超期", "停用",
           "unavailable", "booked", "out of stock"]
FIELD_KW = {
    "objective": ["目标", "目的", "研究问题", "假设", "hypothesis", "objective", "aim"],
    "variables": ["变量", "自变量", "因变量", "variable", "factor"],
    "controls": ["对照", "空白", "阴性", "阳性", "control", "sham"],
    "procedure": ["步骤", "流程", "操作", "procedure", "protocol", "第1步", "步骤1"],
    "parameters": ["参数", "条件", "设置", "parameter", "setting"],
    "resources": ["资源", "设备", "仪器", "耗材", "试剂", "材料", "人员", "equipment", "reagent", "material"],
    "readout": ["判读", "判定", "指标", "终点", "标准", "readout", "endpoint", "criterion"],
    "risk": ["风险", "失败", "备选", "回退", "risk", "failure", "fallback"],
    "cost": ["成本", "费用", "预算", "单价", "cost", "price", "budget"],
}
FIELDS = ["objective", "hypothesis_note", "variables", "controls", "procedure",
          "parameters", "resources", "readout", "cost", "time", "risk", "evidence"]
SEVEN = ["objective", "variables", "controls", "procedure", "parameters", "resources", "readout"]
COST_UNIT = r"(人日|人天|小时|盒|瓶|板|次|管|孔|样本|h)"
COST_QTY = re.compile(r"([A-Za-z\u4e00-\u9fa5][\w\u4e00-\u9fa5\-]{0,18})?\s*(?:[:：=]|×|x|\*)?\s*"
                      r"(" + NUM + r")\s*" + COST_UNIT)
# 行首字段标签优先：标签决定字段，标签后的词（如"低成本"）不再改判
LABEL_MAP = {"目标": "objective", "目的": "objective", "假设": "objective", "研究问题": "objective",
             "变量": "variables", "自变量": "variables", "因变量": "variables",
             "对照": "controls", "对照組": "controls", "control": "controls",
             "步骤": "procedure", "流程": "procedure", "操作": "procedure", "procedure": "procedure",
             "参数": "parameters", "条件": "parameters", "parameters": "parameters",
             "资源": "resources", "设备": "resources", "仪器": "resources", "耗材": "resources",
             "试剂": "resources", "材料": "resources", "resources": "resources",
             "判读": "readout", "指标": "readout", "终点": "readout", "标准": "readout",
             "风险": "risk", "失败模式": "risk", "risk": "risk",
             "成本": "cost", "费用": "cost", "预算": "cost", "cost": "cost",
             "时间": "time", "工期": "time", "time": "time"}

# 结构化候选的键名（归一化后比较）
PLAN_LIST_KEYS = ["candidate_plans", "candidateplans", "candidates", "plans", "variants",
                  "alternatives", "versions", "candidateplanslist"]
PLAN_FIELD_KEYS = {
    "objective": ["objective", "goals", "goal", "aim", "hypothesis", "researchquestion",
                  "question", "description", "summary", "title"],
    "variables": ["variables", "variable", "factors", "independentvariables", "dependentvariables"],
    "controls": ["controls", "control", "comparators", "comparator", "baseline", "reference"],
    "procedure": ["procedure", "protocol", "steps", "workflow", "method", "methods", "process"],
    "parameters": ["parameters", "params", "settings", "conditions", "parametervalues",
                   "parametervalues", "parameterization"],
    "resources": ["resources", "materials", "equipment", "instruments", "reagents",
                  "consumables", "requiredresources", "personnel"],
    "readout": ["readout", "readouts", "endpoint", "endpoints", "outcomes", "outcome",
                "successcriteria", "criteria", "measurements", "indicators"],
    "cost": ["cost", "costs", "budget", "estimatedcost", "price", "pricing"],
    "time": ["time", "duration", "timeline", "days", "schedule", "totaltime"],
    "risk": ["risks", "risk", "limitations", "failuremodes", "mitigation", "mitigations", "contingency"],
    "evidence": ["evidence", "sources", "references", "rationale", "justification", "citations", "basis"],
}
PRICE_KEYS = ["unitprice", "price", "amount", "rate", "cost", "fee"]
DOMAIN_LIST_KEYS = ["parameterdomains", "parameterbounds", "parameterlimits", "domains", "finitedomains",
                    "limits", "parametervalues", "allowedparameters"]
CONTRACT_LIST_KEYS = ["resourcecontract", "resourcerecords", "prices", "pricelist", "costterms",
                      "resources", "booking", "bookings", "availability"]

# 透明权重：评审可改，但默认值固定且写进 scoring
WEIGHTS = {"objective": 0.20, "feasibility": 0.25, "cost": 0.15,
           "time": 0.15, "risk": 0.15, "evidence": 0.10}
MAX_PLANS = 20


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


def norm(s):
    return re.sub(r"[\s_\-]+", "", str(s)).lower()


RUNTIME_FILES = {"case.json", "case.raw.json", "contract.json", "corpus.txt", "evidence.json",
                 "draft.json", "run_log.txt", "result.json", "comparison_matrix.csv",
                 "comparison_report.md", "determinism.json"}


# ---------------------------------------------------------------- text corpus
def split_corpus(corpus):
    marks = list(FILE_HDR.finditer(corpus))
    docs = []
    for i, m in enumerate(marks):
        if os.path.basename(m.group(1)).lower() in RUNTIME_FILES:
            continue                    # 运行时产物不当材料（work 位于 materials 内时）
        start = m.end() + 1
        end = marks[i + 1].start() if i + 1 < len(marks) else len(corpus)
        docs.append((m.group(1), [(n + 1, ln) for n, ln in enumerate(corpus[start:end].splitlines())]))
    return docs


def block_fields(lines):
    """把一个方案块的文本行按七个字段 + 成本/时间/风险归类，并保留行号。"""
    out = {k: [] for k in FIELDS}
    for n, ln in lines:
        s = ln.strip()
        if not s:
            continue
        low = s.lower()
        label = re.match(r"\s*([\u4e00-\u9fa5A-Za-z]{1,6})\s*[:：=]", s)
        hit = LABEL_MAP.get(label.group(1)) if label else None
        if hit is None:
            order = ["risk", "readout", "cost", "resources", "parameters", "controls",
                     "variables", "procedure", "objective"]
            for f in order:
                if any(k.lower() in low for k in FIELD_KW[f]):
                    hit = f
                    break
        if hit:
            out[hit].append({"text": s[:200], "line": n})
        else:
            out["evidence"].append({"text": s[:200], "line": n})
    return out


def parse(corpus):
    docs = split_corpus(corpus)
    blocks, cur = [], None
    for path, lines in docs:
        base = os.path.basename(path).lower()
        cur = None                      # 换文件即结束上一个方案块，避免把报价/说明并进末方案
        mfile = re.search(r"(plan|candidate|proposal|variant|方案|路线)[^/]{0,20}?(v\d+|[abc]|[1-9])", base)
        if mfile:
            cur = {"id": mfile.group(2), "source": os.path.basename(path), "line": 1,
                   "title": "（整份文件为一个候选方案）", "lines": []}
            blocks.append(cur)
        for n, ln in lines:
            hdr = PLAN_HDR.search(ln)
            if hdr and hdr.start() <= 4:
                cur = {"id": (hdr.group(1) or "").strip(), "source": os.path.basename(path),
                       "line": n, "title": ln.strip()[:80], "lines": [(n, ln)]}
                blocks.append(cur)
                continue
            if cur is not None:
                cur["lines"].append((n, ln))
    # 没有显式方案头时，按材料文件分组当候选（数量>1 才有比较意义）
    if len(blocks) < 2:
        blocks = []
        for path, lines in docs:
            body = [(n, ln) for n, ln in lines if ln.strip()]
            if body and any(any(k.lower() in ln.lower() for kws in FIELD_KW.values() for k in kws)
                            for _, ln in body):
                blocks.append({"id": os.path.splitext(os.path.basename(path))[0][:12],
                               "source": os.path.basename(path), "line": 1,
                               "title": "（按文件分组）", "lines": body})
    for b in blocks:
        b["fields"] = block_fields(b["lines"])
        b["text"] = "\n".join(ln for _, ln in b["lines"])
        b["structured"] = False
        b["param_values"] = parse_text_params(b)
    truncated = max(0, len(blocks) - MAX_PLANS)
    return blocks[:MAX_PLANS], truncated


# ---------------------------------------------------------------- structured case
def deep_find(obj, keys, maxdepth=3, prefix=""):
    """在 case.json 顶层及常见嵌套层里找第一个键名匹配的值。"""
    keys_n = {norm(k) for k in keys}
    if maxdepth < 0 or not isinstance(obj, dict):
        return None, None
    for k, v in obj.items():
        if norm(k) in keys_n and v not in (None, "", [], {}):
            return (prefix + k), v
    for k, v in obj.items():
        if isinstance(v, dict) and norm(k) in ("input", "inputs", "data", "payload", "case",
                                               "context", "example", "task", "problem",
                                               "constraints", "constraint", "limits"):
            p, val = deep_find(v, keys, maxdepth - 1, prefix + k + ".")
            if val is not None:
                return p, val
    return None, None


def get_ci(d, keys, default=None):
    if not isinstance(d, dict):
        return default
    for k, v in d.items():
        if norm(k) in {norm(x) for x in keys} and v not in (None, ""):
            return v
    return default


def text_items(value, locator, prefix=""):
    """把任意结构转成可回查的文本条目，带 case.json 路径定位。"""
    out = []
    if value is None:
        return out
    if isinstance(value, dict):
        for k, v in value.items():
            out += text_items(v, "%s.%s" % (locator, k), prefix + ("%s: " % k if not isinstance(v, (dict, list)) else ""))
        return out
    if isinstance(value, list):
        for i, v in enumerate(value):
            out += text_items(v, "%s[%d]" % (locator, i), prefix)
        return out
    s = str(value).strip()
    if not s:
        return out
    return [{"text": (prefix + s)[:300], "line": None, "locator": locator}]


def num_of(v):
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    if isinstance(v, str):
        m = re.search(NUM, v)
        if m:
            try:
                return float(m.group(0))
            except ValueError:
                return None
    return None


def unit_of(v):
    if isinstance(v, str):
        m = re.search(NUM + r"\s*" + UNIT, v)
        if m:
            return m.group(1)
    return ""


def money(amount, cur):
    """把金额归一到 元 / USD，避免 "万元" 与 "元" 被当成不同币种而跳过预算门控。"""
    if amount is None:
        return None, cur
    c = str(cur or "").strip()
    lc = c.lower()
    if c in ("万元", "万"):
        return round(float(amount) * 10000.0, 4), "元"
    if c == "千元":
        return round(float(amount) * 1000.0, 4), "元"
    if c == "$" or lc in ("usd", "dollar", "dollars"):
        return float(amount), "USD"
    return float(amount), c


def structured_params(value, locator):
    """从结构化 parameters 提取 (名称, 数值, 单位, 定位)。"""
    out = []
    if value is None:
        return out
    if isinstance(value, dict):
        for k, v in value.items():
            loc = "%s.%s" % (locator, k)
            unit = get_ci(v, ["unit", "units"], "") if isinstance(v, dict) else unit_of(v)
            raw = get_ci(v, ["value", "amount", "setting", "val"], v) if isinstance(v, dict) else v
            out.append({"name": str(k), "value": num_of(raw), "unit": unit or "",
                        "text": "%s = %s%s" % (k, raw, (" " + unit) if unit else ""), "locator": loc})
    elif isinstance(value, list):
        for i, v in enumerate(value):
            loc = "%s[%d]" % (locator, i)
            if isinstance(v, dict):
                name = get_ci(v, ["name", "parameter", "param", "key"], "param%d" % (i + 1))
                unit = get_ci(v, ["unit", "units"], "")
                raw = get_ci(v, ["value", "amount", "setting"], None)
                out.append({"name": str(name), "value": num_of(raw), "unit": unit or "",
                            "text": "%s = %s%s" % (name, raw, (" " + unit) if unit else ""), "locator": loc})
            else:
                m = VAL.search(str(v))
                if m:
                    out.append({"name": m.group(1), "value": float(m.group(2)), "unit": m.group(3) or "",
                                "text": str(v)[:160], "locator": loc})
                else:
                    out.append({"name": "param%d" % (i + 1), "value": num_of(v), "unit": unit_of(v),
                                "text": str(v)[:160], "locator": loc})
    elif isinstance(value, str):
        for m in VAL.finditer(value):
            out.append({"name": m.group(1), "value": float(m.group(2)), "unit": m.group(3) or "",
                        "text": m.group(0), "locator": locator})
    return out


def parse_text_params(b):
    out = []
    for it in b["fields"]["parameters"]:
        for m in VAL.finditer(it["text"]):
            out.append({"name": m.group(1), "value": float(m.group(2)), "unit": m.group(3) or "",
                        "text": it["text"][:160], "line": it["line"]})
    return out


def structured_block(plan, idx, base):
    if isinstance(plan, str):
        lines = [(i + 1, ln) for i, ln in enumerate(plan.splitlines())]
        b = {"id": "plan%d" % (idx + 1), "title": "（候选文本）", "source": "case.json",
             "line": None, "locator": "%s[%d]" % (base, idx), "lines": lines,
             "structured": True, "fields": block_fields(lines)}
        b["text"] = plan
        b["param_values"] = parse_text_params(b)
        return b
    if not isinstance(plan, dict):
        return None
    pid = get_ci(plan, ["id", "planid", "candidateid", "name", "label", "version", "title"], "plan%d" % (idx + 1))
    loc = "%s[%d]" % (base, idx)
    b = {"id": str(pid), "title": str(get_ci(plan, ["title", "name", "description"], "候选方案"))[:80],
         "source": "case.json", "line": None, "locator": loc, "lines": [], "structured": True,
         "fields": {k: [] for k in FIELDS}, "raw_keys": sorted(plan.keys())}
    for f, keys in PLAN_FIELD_KEYS.items():
        val = get_ci(plan, keys, None)
        if val is not None:
            b["fields"][f] = text_items(val, "%s.%s" % (loc, norm(keys[0])))
    # 参数单独保留精确数值
    pval = get_ci(plan, PLAN_FIELD_KEYS["parameters"], None)
    b["param_values"] = structured_params(pval, "%s.parameters" % loc)
    b["structured_cost"] = get_ci(plan, ["cost", "costs", "estimatedcost", "totalcost", "price"], None)
    b["structured_time"] = get_ci(plan, ["time", "duration", "timeline", "days", "totaltime"], None)
    b["text"] = "\n".join(x["text"] for f in FIELDS for x in b["fields"][f])
    return b


def structured_blocks(case):
    if not isinstance(case, dict):
        return [], None, 0
    base, plans = deep_find(case, PLAN_LIST_KEYS)
    if not isinstance(plans, list) or not plans:
        return [], None, 0
    blocks = []
    for i, p in enumerate(plans[:MAX_PLANS]):
        b = structured_block(p, i, base)
        if b:
            blocks.append(b)
    return blocks, base, max(0, len(plans) - len(blocks))


# ---------------------------------------------------------------- structured contracts
def structured_contracts(case):
    """从 case.json 提取价格、预算、窗口、不可得资源、有限参数域。"""
    prices, budgets, windows, unavail, domains = [], [], [], [], []
    if not isinstance(case, dict):
        return prices, budgets, windows, unavail, domains

    def add_price(d, path):
        amount = None
        for k in PRICE_KEYS:
            v = get_ci(d, [k], None)
            if v is not None and num_of(v) is not None:
                amount = num_of(v)
                break
        if amount is None:
            return
        item = get_ci(d, ["name", "item", "resource", "consumable", "reagent", "equipment", "service"], "")
        per = get_ci(d, ["per", "unit", "billingunit", "basis"], "")
        cur = get_ci(d, ["currency", "cur"], "元")
        amount, cur = money(amount, cur)
        prices.append({"item": str(item), "amount": amount, "currency": str(cur),
                       "per": str(per), "source": "case.json", "path": path,
                       "quote": json.dumps(d, ensure_ascii=False)[:200]})

    def scan_contract(obj, path, depth=0):
        if depth > 3:
            return
        if isinstance(obj, list):
            for i, v in enumerate(obj):
                scan_contract(v, "%s[%d]" % (path, i), depth + 1)
            return
        if not isinstance(obj, dict):
            return
        keys_n = {norm(k) for k in obj.keys()}
        if keys_n & {norm(k) for k in PRICE_KEYS} and keys_n & {
                norm(k) for k in ["name", "item", "resource", "consumable", "reagent", "equipment", "service"]}:
            add_price(obj, path)
        status = get_ci(obj, ["status", "availability", "state"], "")
        available = get_ci(obj, ["available"], None)
        name = get_ci(obj, ["name", "item", "resource", "equipment", "instrument"], "")
        avail_false = available is False or (
            isinstance(available, str) and available.strip().lower() in
            ("false", "no", "0", "unavailable", "不可用", "否", "n"))
        if name and (avail_false or any(k in str(status) for k in UNAVAIL)):
            unavail.append({"text": "%s %s" % (name, status or "available=false"),
                            "name": str(name), "source": "case.json", "path": path})
        for k, v in obj.items():
            if isinstance(v, (dict, list)):
                scan_contract(v, "%s.%s" % (path, k), depth + 1)

    pbase, rcontract = deep_find(case, CONTRACT_LIST_KEYS)
    if rcontract is not None:
        scan_contract(rcontract, pbase or "resource_contract")

    bpath, bval = deep_find(case, ["budget", "costlimit", "spendlimit", "budgetlimit"])
    if bval is not None:
        amt = num_of(get_ci(bval, ["amount", "value", "total", "limit"], None)) \
            if isinstance(bval, dict) else num_of(bval)
        if amt is not None:
            cur = "元"
            if isinstance(bval, dict):
                cur = get_ci(bval, ["currency", "cur"], "元")
            elif isinstance(bval, str):
                m = re.search(r"(元|万元|USD|\$)", bval)
                cur = m.group(1) if m else "元"
            amt, cur = money(amt, cur)
            budgets.append({"amount": amt, "currency": str(cur), "source": "case.json",
                            "line": None, "path": bpath, "quote": str(bval)[:160]})

    wpath, wval = deep_find(case, ["timewindow", "windowdays", "deadlinedays", "durationlimit",
                                   "timelimit", "deadline", "timewindowdays"])
    if wval is not None:
        amt = num_of(wval)
        if amt is not None:
            unit = unit_of(wval) or "天"
            windows.append({"amount": amt, "unit": unit, "source": "case.json", "line": None,
                            "path": wpath, "quote": str(wval)[:160]})

    dpath, dval = deep_find(case, DOMAIN_LIST_KEYS)
    if dval is not None:
        domains = parse_domains(dval, dpath or "parameter_domains")
    return prices, budgets, windows, unavail, domains


def parse_domains(value, path):
    out = []

    def add(name, lo, hi, values, unit, loc):
        out.append({"name": str(name), "lo": lo, "hi": hi, "values": values,
                    "unit": unit or "", "source": "case.json", "path": loc})

    if isinstance(value, list):
        for i, v in enumerate(value):
            loc = "%s[%d]" % (path, i)
            if isinstance(v, dict):
                name = get_ci(v, ["name", "parameter", "param", "key"], None)
                if name is None:
                    continue
                lo = num_of(get_ci(v, ["min", "minimum", "lower", "low"], None))
                hi = num_of(get_ci(v, ["max", "maximum", "upper", "high"], None))
                vals = get_ci(v, ["values", "allowed", "enum", "choices", "options"], None)
                unit = get_ci(v, ["unit", "units"], "")
                if lo is None and hi is None and not vals:
                    rng = get_ci(v, ["range", "domain", "bounds"], None)
                    lo, hi = parse_range(rng)
                add(name, lo, hi, vals if isinstance(vals, list) else None, unit, loc)
            else:
                m = re.search(r"([^\s:：=]+)\s*[:：=]?\s*(" + NUM + r")\s*[-~至]\s*(" + NUM + r")\s*(" + UNIT + r")?", str(v))
                if m:
                    add(m.group(1), float(m.group(2)), float(m.group(3)), None, m.group(4) or "", loc)
    elif isinstance(value, dict):
        for k, v in value.items():
            loc = "%s.%s" % (path, k)
            if isinstance(v, dict):
                lo = num_of(get_ci(v, ["min", "minimum", "lower"], None))
                hi = num_of(get_ci(v, ["max", "maximum", "upper"], None))
                vals = get_ci(v, ["values", "allowed", "enum", "choices"], None)
                add(k, lo, hi, vals if isinstance(vals, list) else None, get_ci(v, ["unit"], ""), loc)
            elif isinstance(v, list):
                nums = [num_of(x) for x in v]
                nums = [x for x in nums if x is not None]
                if len(nums) >= 2:
                    add(k, min(nums), max(nums), None, "", loc)
                elif len(v) > 1:
                    add(k, None, None, v, "", loc)
            else:
                lo, hi = parse_range(v)
                if lo is None and hi is None and num_of(v) is not None:
                    lo = hi = num_of(v)
                add(k, lo, hi, None, unit_of(v), loc)
    return out


def parse_range(v):
    if v is None:
        return None, None
    if isinstance(v, (list, tuple)) and len(v) >= 2:
        return num_of(v[0]), num_of(v[1])
    if isinstance(v, dict):
        return num_of(get_ci(v, ["min", "minimum"], None)), num_of(get_ci(v, ["max", "maximum"], None))
    m = re.search(r"(" + NUM + r")\s*[-~至]\s*(" + NUM + r")", str(v))
    if m:
        return float(m.group(1)), float(m.group(2))
    return None, None


def names_match(a, b):
    a, b = norm(a), norm(b)
    if not a or not b:
        return False
    return a == b or a in b or b in a


# ---------------------------------------------------------------- text contracts
def global_contract(docs):
    prices, budgets, windows, unavail, limits = [], [], [], [], []
    for path, lines in docs:
        for n, ln in lines:
            for m in PRICE.finditer(ln):
                amt, cur = money(float(m.group(2)), m.group(3))
                prices.append({"item": (m.group(1) or "").strip(), "amount": amt,
                               "currency": cur, "per": m.group(4),
                               "source": os.path.basename(path), "line": n, "quote": ln.strip()[:160]})
            m = BUDGET.search(ln)
            if m:
                amt, cur = money(float(m.group(1)), m.group(2))
                budgets.append({"amount": amt, "currency": cur,
                                "source": os.path.basename(path), "line": n, "quote": ln.strip()[:160]})
            d = DAYS.search(ln)
            if d and any(k in ln for k in ("窗口", "截止", "货期", "周期", "deadline", "window")):
                windows.append({"amount": float(d.group(1)), "unit": d.group(2),
                                "source": os.path.basename(path), "line": n, "quote": ln.strip()[:160]})
            if any(k in ln for k in UNAVAIL) and not any(
                    k in ln for k in ("风险", "缓解", "回退", "备选", "触发", "后果")):
                # 方案风险叙述里的"已满"不是全局资源合同；只收真正声明资源不可得的材料行
                unavail.append({"text": ln.strip()[:160], "source": os.path.basename(path), "line": n})
            for m in LIMIT_NAMED.finditer(ln):
                name = (m.group(1) or "").strip(" ：:，,。;；")
                if name and len(name) >= 1:
                    limits.append({"name": name, "limit": float(m.group(2)), "unit": m.group(3) or "",
                                   "source": os.path.basename(path), "line": n,
                                   "quote": ln.strip()[:160], "path": None})
    return prices, budgets, windows, unavail, limits


def unit_price_for(item, prices, per_hint):
    # 只按品名匹配；品名缺失的通用报价才按单位兜底，避免把别的耗材单价套过来
    for p in prices:
        if (not per_hint or p["per"] in per_hint) and p["item"] and (p["item"] in item or item in p["item"]):
            return p
    for p in prices:
        if (not per_hint or p["per"] in per_hint) and not p["item"]:
            return p
    return None


GENERIC = {"资源", "设备", "仪器", "耗材", "试剂", "材料", "样本", "说明书", "文献",
           "记录", "手册", "报价", "目录", "现在", "本实验室", "可用", "时段",
           "风险", "缓解", "备选", "回退", "触发", "后果", "方案", "实验", "时间", "窗口",
           "排队", "需排队", "设备已满"}


def key_tokens(text):
    """从"资源不可得"行里抽出可回查的资源名（去掉否定词与泛化词）。"""
    cleaned = text
    for k in UNAVAIL:
        cleaned = cleaned.replace(k, " ")
    toks = re.findall(r"[\u4e00-\u9fa5A-Za-z][\w\u4e00-\u9fa5\-]{1,9}", cleaned)
    return [t for t in toks if len(t) >= 2 and t not in GENERIC]


def structured_cost(plan_cost_value, default_cur=None):
    """结构化 cost 可能是数字/{amount,currency}/[{item,qty,unit_price}]。"""
    items, currency = [], None
    if plan_cost_value is None:
        return None
    if isinstance(plan_cost_value, (int, float)):
        amt, cur = money(float(plan_cost_value), default_cur)
        return {"items": [], "known_subtotal": amt, "unknown_items": 0,
                "is_lower_bound": False, "currency": cur,
                "formula": "total = 材料给出的总成本 %s %s" % (amt, cur or "")}
    if isinstance(plan_cost_value, str):
        amt = num_of(plan_cost_value)
        cur0 = unit_of(plan_cost_value) if re.search(r"元|万元|USD|\$", plan_cost_value) else default_cur
        amt, cur = money(amt, cur0)
        if amt is not None:
            return {"items": [], "known_subtotal": amt, "unknown_items": 0,
                    "is_lower_bound": False, "currency": cur,
                    "formula": "total = 材料给出的总成本 %s %s" % (amt, cur or "")}
        return None
    if isinstance(plan_cost_value, dict):
        amount = num_of(get_ci(plan_cost_value, ["amount", "total", "value", "cost", "subtotal"], None))
        currency = get_ci(plan_cost_value, ["currency", "cur"], default_cur)
        det = get_ci(plan_cost_value, ["items", "breakdown", "lineitems"], None)
        if isinstance(det, list) and det:
            items = []
            for i, it in enumerate(det):
                if not isinstance(it, dict):
                    continue
                qty = num_of(get_ci(it, ["qty", "quantity", "count", "n"], None))
                up = num_of(get_ci(it, ["unitprice", "price", "unitcost", "rate"], None))
                cur_i = get_ci(it, ["currency"], currency) or default_cur
                up, cur_i = money(up, cur_i)
                items.append({"item": str(get_ci(it, ["item", "name", "resource"], "")),
                              "qty": qty, "unit": get_ci(it, ["unit"], ""), "unit_price": up,
                              "currency": cur_i,
                              "subtotal": round(qty * up, 4) if (qty is not None and up is not None) else None,
                              "source": "case.json[%d]" % i})
            known = round(sum(x["subtotal"] for x in items if x["subtotal"] is not None), 4)
            unknown = sum(1 for x in items if x["subtotal"] is None)
            # 明细不全但材料给了明确总额时，总额才是权威口径，不能当作"成本未知"而漏掉预算门控。
            if amount is not None:
                amt, cur = money(amount, currency or default_cur)
                return {"items": items, "known_subtotal": amt, "unknown_items": unknown,
                        "is_lower_bound": False, "currency": cur,
                        "formula": "total = 材料给出的总成本 %s %s（明细 %d 项缺价，不改变总额）"
                                   % (amt, cur or "", unknown)}
            return {"items": items, "known_subtotal": (known if known or not unknown else None),
                    "unknown_items": unknown, "is_lower_bound": bool(unknown),
                    "currency": (money(0, currency)[1] if currency else currency),
                    "formula": "total = Σ(qty × unit_price) = %s（%d 项缺价）" % (known, unknown)}
        if amount is not None:
            amt, cur = money(amount, currency)
            return {"items": [], "known_subtotal": amt, "unknown_items": 0,
                    "is_lower_bound": False, "currency": cur,
                    "formula": "total = 材料给出的总成本 %s %s" % (amt, cur or "")}
    return None


def structured_time(plan_time_value):
    if plan_time_value is None:
        return None
    days = None
    if isinstance(plan_time_value, (int, float)):
        days = float(plan_time_value)
    elif isinstance(plan_time_value, dict):
        weeks = num_of(get_ci(plan_time_value, ["weeks", "week"], None))
        raw = get_ci(plan_time_value, ["days", "totaldays", "duration", "value"], None)
        unit = str(get_ci(plan_time_value, ["unit", "units"], "") or "")
        if weeks is not None:
            days = weeks * 7.0
        elif isinstance(raw, str):
            m = DAYS.search(raw)
            if m:
                days = float(m.group(1)) * (7.0 if m.group(2) in ("周", "weeks", "week") else 1.0)
            else:
                days = num_of(raw)
        else:
            days = num_of(raw)
        if days is not None and unit.strip().lower() in ("周", "weeks", "week"):
            days *= 7.0
    elif isinstance(plan_time_value, str):
        m = DAYS.search(plan_time_value)
        if m:
            days = float(m.group(1)) * (7.0 if m.group(2) in ("周", "weeks", "week") else 1.0)
        else:
            days = num_of(plan_time_value)
    if days is None:
        return None
    return {"days": round(days, 4), "items": [days], "formula": "total = 材料给出的总工期 %s 天" % round(days, 4)}


def plan_cost(b, prices, default_cur=None):
    s = structured_cost(b.get("structured_cost"), default_cur)
    if s is not None:
        return s
    items, unknown, seen = [], 0, set()
    for m in COST_PAIR.finditer(b["text"]):
        name = (m.group(1) or "").strip()
        qty = float(m.group(2))
        unit = m.group(3)
        p = unit_price_for(name, prices, {unit})
        sub = round(qty * p["amount"], 4) if p else None
        if p is None:
            unknown += 1
        items.append({"item": name, "qty": qty, "unit": unit,
                      "unit_price": (p["amount"] if p else None),
                      "currency": (p["currency"] if p else default_cur),
                      "subtotal": sub, "source": b["source"]})
    for m in COST_QTY.finditer(b["text"]):
        name = (m.group(1) or "").strip()
        val, unit = float(m.group(2)), m.group(3)
        if not name or name in ("工期", "时长", "共", "约", "预算", "总计", "合计"):
            continue
        if any(i["item"] == name and i["qty"] == val and i["unit"] == unit for i in items):
            continue
        if (name, m.start(2)) in seen:
            continue
        seen.add((name, m.start(2)))
        p = unit_price_for(name, prices, {unit})
        subtotal = round(val * p["amount"], 4) if p else None
        if p is None:
            unknown += 1
        items.append({"item": name, "qty": val, "unit": unit,
                      "unit_price": (p["amount"] if p else None),
                      "currency": (p["currency"] if p else default_cur),
                      "subtotal": subtotal, "source": b["source"]})
    known = round(sum(i["subtotal"] for i in items if i["subtotal"] is not None), 4)
    if items and unknown and known == 0:
        known = None                    # 全部单价未知：不把 0 当成"免费"
    if not items:
        m = TOTAL_COST.search(b["text"])
        if m:
            amt, cur = money(float(m.group(1)), m.group(2))
            return {"items": [], "known_subtotal": amt, "unknown_items": 0,
                    "is_lower_bound": False, "currency": cur,
                    "formula": "total = 材料给出的总成本 %s %s" % (amt, cur)}
    formula = ("total = Σ(qty × unit_price) = %s（%d 项单价缺失，结果为下限）"
               % (known, unknown)) if unknown else ("total = Σ(qty × unit_price) = %s" % known)
    return {"items": items[:12], "known_subtotal": known if items else None,
            "unknown_items": unknown,
            "is_lower_bound": bool(unknown),
            "currency": plan_currency(items),
            "formula": formula if items else "材料未给出可解析的数量×单价，成本未知"}


def plan_currency(items):
    curs = {i.get("currency") for i in items if i.get("currency")}
    return curs.pop() if len(curs) == 1 else (None if not curs else "MIXED")


def plan_time(b):
    s = structured_time(b.get("structured_time"))
    if s is not None:
        return s
    days, totals = [], []
    for m in DAYS.finditer(b["text"]):
        unit = m.group(2)
        v = float(m.group(1))
        d = v * 7.0 if unit in ("周", "weeks", "week") else v
        days.append(d)
        line_start = max(0, m.start() - 12)
        ctx = b["text"][line_start:m.end()]
        if any(k in ctx for k in ("工期", "总工期", "总时长", "共计", "合计", "总计", "deadline")):
            totals.append(d)
    if totals:                      # 材料给了总工期就以总工期为准，避免"分步+总计"重复相加
        total = round(max(totals), 4)
        formula = "total = 材料给出的总工期 %s 天（不重复累加分步天数）" % total
    elif days:
        total = round(sum(days), 4)
        formula = "total = Σ(步骤天数) = %s 天" % total
    else:
        total = None
        formula = "材料未给出可解析的工期，时间未知"
    return {"days": total, "items": days[:12], "formula": formula}


def count_risks(b):
    risk_lines = b["fields"]["risk"]
    mitigated = [r for r in risk_lines if any(k in r["text"] for k in ("缓解", "备选", "回退", "降低", "替代"))]
    return {"risk_items": len(risk_lines), "mitigated": len(mitigated),
            "unmitigated": max(0, len(risk_lines) - len(mitigated))}


def evidence_strength(b):
    """证据强度=带文件/行号/结构化路径且含来源线索的条目数，归一 0-5。"""
    pool = b["fields"]["evidence"] + b["fields"]["resources"] + b["fields"]["parameters"]
    src_lines = [e for e in pool
                 if e.get("locator") or any(k in e["text"] for k in (
                     "文献", "手册", "报价", "记录", "日志", "说明书", "reference", "manual",
                     "quote", "目录", "DOI", "doi"))]
    n = len(src_lines)
    return {"evidence_lines": n, "score": min(5, 1 + n), "samples": [e["text"] for e in src_lines[:3]],
            "locators": [e.get("locator") or "%s:%s" % (b["source"], e.get("line")) for e in src_lines[:5]]}


def objective_match(b, task_text):
    goal = " ".join(x["text"] for x in b["fields"]["objective"]) or b["title"]
    toks = [t for t in re.split(r"[^\w\u4e00-\u9fa5]+", task_text or "") if len(t) >= 2][:40]
    hit = sum(1 for t in toks if t.lower() in goal.lower())
    return {"has_objective": bool(b["fields"]["objective"]), "keyword_hits": hit,
            "score": (5 if b["fields"]["objective"] and hit else (4 if b["fields"]["objective"] else 2))}


def param_gates(b, domains, text_limits):
    g = []
    for p in b.get("param_values", []):
        if p.get("value") is None:
            continue
        matched = None
        for d in domains:
            if names_match(p["name"], d["name"]):
                matched = d
                break
        if matched:
            val, unit = p["value"], (p.get("unit") or "").strip()
            dom_unit = (matched.get("unit") or "").strip()
            if unit and dom_unit and unit != dom_unit:
                continue                # 单位不同不硬判，留待确认
            if matched.get("lo") is not None and val < matched["lo"]:
                g.append({"gate": "参数越界", "detail": "%s=%s%s 低于允许下限 %s%s" % (
                    p["name"], val, unit, matched["lo"], unit or dom_unit),
                    "source": "case.json", "locator": p.get("locator"), "line": None})
                continue
            if matched.get("hi") is not None and val > matched["hi"]:
                g.append({"gate": "参数越界", "detail": "%s=%s%s 高于允许上限 %s%s" % (
                    p["name"], val, unit, matched["hi"], unit or dom_unit),
                    "source": "case.json", "locator": p.get("locator"), "line": None})
                continue
            if matched.get("values"):
                allowed = [str(x) for x in matched["values"]]
                if str(p["value"]) not in allowed and p["name"] not in allowed:
                    g.append({"gate": "参数越界", "detail": "%s=%s 不在允许取值 %s 内" % (
                        p["name"], p["value"], "、".join(allowed[:6])),
                        "source": "case.json", "locator": p.get("locator"), "line": None})
                continue
        # 文本上限回退：仅按参数名匹配；无名字的上限只在该单位唯一时使用
        for lim in text_limits:
            if not names_match(p["name"], lim["name"]):
                continue
            unit = (p.get("unit") or "").strip()
            if unit and lim["unit"] and unit != lim["unit"]:
                continue
            if p["value"] > lim["limit"]:
                g.append({"gate": "参数越界", "detail": "%s=%s%s 超过上限 %s%s（%s 行 %s）" % (
                    p["name"], p["value"], unit, lim["limit"], lim["unit"],
                    lim["source"], lim["line"]),
                    "source": lim["source"], "line": lim["line"]})
            break
    return g


def gates(b, cost, tm, unavail, budget, window_days, domains=None, text_limits=None):
    g = []
    for u in unavail:
        toks = [u["name"]] if u.get("name") else key_tokens(u["text"])
        hit = next((t for t in toks if t and t in b["text"]), None)
        if hit:
            g.append({"gate": "资源不可得", "detail": u["text"], "resource": hit,
                      "source": u["source"], "line": u.get("line"),
                      "locator": u.get("path")})
    if budget and budget.get("amount") is not None and cost["known_subtotal"] is not None:
        cur = cost.get("currency")
        if (not cur or not budget.get("currency") or cur == budget.get("currency")) \
                and cost["known_subtotal"] > budget["amount"]:
            g.append({"gate": "超预算", "detail": "成本 %s %s > 预算 %s %s%s" % (
                cost["known_subtotal"], cur or "", budget["amount"], budget.get("currency") or "",
                "（已知项合计，含缺价项，实际只会更高）" if cost["is_lower_bound"] else ""),
                "source": budget.get("source"), "line": budget.get("line"),
                "locator": budget.get("path")})
    if window_days is not None and tm["days"] is not None and tm["days"] > window_days:
        g.append({"gate": "超时间窗口", "detail": "方案工期 %s 天 > 窗口 %s 天" % (tm["days"], window_days),
                  "source": "材料", "line": ""})
    g += param_gates(b, domains or [], text_limits or [])
    seen, out = set(), []
    for x in g:
        k = (x["gate"], x.get("resource") or x.get("detail"))
        if k not in seen:
            seen.add(k)
            out.append(x)
    return out


def score_plan(b, task_text, cost, tm, risks, ev, gate_list):
    sc = {}
    sc["objective"] = objective_match(b, task_text)["score"]
    if gate_list:
        sc["feasibility"] = 0
    elif cost["known_subtotal"] is None:
        sc["feasibility"] = 2                      # 成本完全没有可解析数据，不能当作已核实
    elif cost["unknown_items"]:
        sc["feasibility"] = 3
    else:
        sc["feasibility"] = 5
    sc["risk"] = None if not risks["risk_items"] else max(0, 5 - 2 * risks["unmitigated"])
    sc["evidence"] = ev["score"]
    return sc


def relative_scores(rows, field):
    """只在通过硬门控的幸存者内做相对位次；币种不一致或可比数<2 → None。"""
    key = "known_subtotal" if field == "cost" else "days"
    vals = [(i, r[field]) for i, r in enumerate(rows)
            if not r["gates"] and r[field].get(key) is not None]
    if field == "cost":
        curs = {v.get("currency") for _, v in vals}
        if len(curs) > 1:
            return {i: None for i, _ in vals}, "成本币种不一致（%s），未做跨币种排名" % "、".join(sorted(str(c) for c in curs))
        nums = [v["known_subtotal"] for _, v in vals]
    else:
        nums = [v["days"] for _, v in vals]
    if len(nums) < 2:
        return {i: None for i, _ in vals}, None
    uniq = sorted(set(nums))
    if len(uniq) < 2:
        # 所有幸存者数值完全相同：没有相对位次可言，不能按枚举顺序人为拉开 5 分 vs 2 分。
        return {vals[k][0]: 5.0 for k in range(len(vals))}, \
            ("%s 在所有可比幸存者中完全相同，位次未产生区分" % ("成本" if field == "cost" else "工期"))
    score_by = {v: round(5 - 3 * pos / (len(uniq) - 1), 2) for pos, v in enumerate(uniq)}
    return {vals[k][0]: score_by[nums[k]] for k in range(len(vals))}, None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--work", default="work")
    ap.add_argument("--budget", type=float, default=None)
    ap.add_argument("--window", type=float, default=None)
    a = ap.parse_args()
    cp = os.path.join(a.work, "corpus.txt")
    if not os.path.exists(cp):
        print("blocked: work/corpus.txt missing (run kernel.py index first)")
        return 1
    corpus = open(cp, encoding="utf-8").read()
    contract = load(os.path.join(a.work, "contract.json"), {})
    evidence = load(os.path.join(a.work, "evidence.json"), {})
    case_raw = load(os.path.join(a.work, "case.raw.json"), {})
    docs = split_corpus(corpus)
    task_text = str(contract.get("task") or "")
    prices, budgets, windows, unavail, text_limits = global_contract(docs)
    s_prices, s_budgets, s_windows, s_unavail, domains = structured_contracts(case_raw)
    prices += s_prices
    budgets += s_budgets
    windows += s_windows
    unavail += s_unavail

    blocks, sbase, truncated = structured_blocks(case_raw)
    if blocks:
        input_mode = "case.json:%s（%d 个结构化候选）" % (sbase, len(blocks))
    else:
        blocks, truncated = parse(corpus)
        input_mode = "materials（%d 个文件切分候选）" % len(blocks)
    # 重复方案 id 会破坏矩阵、舍弃理由与选择的可读性：加后缀区分并记录。
    dup_ids, seen_ids = [], {}
    for b in blocks:
        base_id = b["id"]
        n = seen_ids.get(base_id, 0) + 1
        seen_ids[base_id] = n
        if n > 1:
            b["id"] = "%s#%d" % (base_id, n)
            dup_ids.append(base_id)
    budget = {"amount": a.budget, "currency": "", "source": "--budget", "line": ""} if a.budget is not None \
        else (budgets[0] if budgets else None)
    window_days = a.window if a.window is not None else (windows[0]["amount"] if windows else None)

    default_cur = (budgets[0]["currency"] if budgets else (prices[0]["currency"] if prices else None))
    costs = [plan_cost(b, prices, default_cur) for b in blocks]
    times = [plan_time(b) for b in blocks]
    rows = []
    for i, b in enumerate(blocks):
        risks = count_risks(b)
        ev = evidence_strength(b)
        gl = gates(b, costs[i], times[i], unavail, budget, window_days, domains, text_limits)
        sc = score_plan(b, task_text, costs[i], times[i], risks, ev, gl)
        present = [f for f in SEVEN if b["fields"][f]]
        rows.append({"id": b["id"] or "?", "source": b["source"], "line": b["line"],
                     "locator": b.get("locator"), "title": b["title"],
                     "fields_present": present,
                     "missing_fields": [f for f in SEVEN if f not in present],
                     "field_values": {f: [x["text"] for x in b["fields"][f][:6]] for f in SEVEN},
                     "cost": costs[i], "time": times[i], "risks": risks,
                     "evidence_strength": ev, "gates": gl, "scores": sc})

    cost_scores, cost_warn = relative_scores(rows, "cost")
    time_scores, time_warn = relative_scores(rows, "time")
    for i, r in enumerate(rows):
        r["scores"]["cost"] = cost_scores.get(i)
        r["scores"]["time"] = time_scores.get(i)
        total_w = sum(WEIGHTS[k] for k, v in r["scores"].items() if v is not None)
        weighted = round(sum(WEIGHTS[k] * v for k, v in r["scores"].items() if v is not None)
                         / (total_w or 1), 3)
        r["scores"]["total_w"] = round(total_w, 3)
        r["weighted"] = (0.0 if r["gates"] else weighted)
        r["unscored"] = [k for k, v in r["scores"].items() if v is None and k in WEIGHTS]

    survivors = [r for r in rows if not r["gates"]]
    ranked = sorted(survivors, key=lambda r: r["weighted"], reverse=True)
    best = ranked[0] if ranked else None
    runner = ranked[1] if len(ranked) > 1 else None
    sensitivity = []
    if best and runner:
        gap = round(best["weighted"] - runner["weighted"], 3)
        diff = {k: (round(runner["scores"].get(k) or 0, 2), round(best["scores"].get(k) or 0, 2))
                for k in WEIGHTS if runner["scores"].get(k) is not None}
        weaker = [k for k, (rv, bv) in diff.items() if bv > rv]
        sensitivity.append({"question": "次优 %s 是否可能反超 %s" % (runner["id"], best["id"]),
                            "score_gap": gap,
                            "flip_condition": ("若把 %s 的权重提高到足以覆盖 %.3f 的差距，或该维度证据显著改善"
                                               % ("、".join(weaker) or "任一维度", gap)) if gap > 0
                            else "两方案打平，需补一条判别性证据（如成本上限或关键指标）再定"})
        for k in weaker:
            w = WEIGHTS[k]
            need = round(w * 2, 2)
            sensitivity.append({"question": "权重敏感性：%s" % k,
                                "score_gap": gap, "current_weight": w,
                                "what_if": "把 %s 权重翻倍到 %.2f，且其余权重按比例缩减" % (k, need)})
    if not survivors:
        sensitivity.append({"question": "全部候选被淘汰时的替代路径",
                            "score_gap": None,
                            "flip_condition": "按 gates 逐条列出淘汰原因；建议放宽预算/改设备档期/缩小参数窗口后重评，不硬选"})

    criteria = [{"criterion": k, "weight": w,
                 "definition": {"objective": "目标/假设与题面一致且有可检验表述",
                                "feasibility": "设备、耗材、档期、参数、审批在本实验室可满足（硬门控）",
                                "cost": "Σ(数量×单价)，含机时与人力；仅幸存者内相对位次",
                                "time": "样品准备+排期+执行+表征+返工的总工期；仅幸存者内相对位次",
                                "risk": "风险条目的触发条件、后果、缓解与回退完整度",
                                "evidence": "带文件行号或 case.json 路径的来源支撑条数（文献/手册/报价/记录）"}[k]}
                for k, w in WEIGHTS.items()]
    comparison_matrix = [{"plan": r["id"], "source": r["source"], "locator": r["locator"],
                          "field_values": r["field_values"],
                          "fields_present": r["fields_present"],
                          "objective_score": r["scores"]["objective"],
                          "feasible": not r["gates"],
                          "eliminated_by": [g["gate"] for g in r["gates"]],
                          "cost_known": r["cost"]["known_subtotal"],
                          "currency": r["cost"].get("currency"),
                          "cost_lower_bound": r["cost"]["is_lower_bound"],
                          "time_days": r["time"]["days"], "risk_items": r["risks"]["risk_items"],
                          "risk_unmitigated": r["risks"]["unmitigated"],
                          "evidence_lines": r["evidence_strength"]["evidence_lines"],
                          "weighted": r["weighted"]} for r in rows]

    if len(blocks) < 2:
        reason = ("仅有 %d 个候选，无法做横向比较；本结果只给该候选的门控、证据与缺口，"
                  "不代表最优选择。" % len(blocks))
        choice = "single_candidate"
    elif best:
        other_gates = sorted({g["gate"] for r in rows if r is not best for g in r["gates"]})
        reason = ("在 %d 个候选中，%s 通过全部硬约束，加权分 %.2f 最高（权重：%s）。"
                  % (len(rows), best["id"], best["weighted"],
                     "、".join("%s %.2f" % (k, v) for k, v in WEIGHTS.items())))
        if other_gates:
            reason += "其余候选被淘汰的门控：%s。" % "、".join(other_gates)
        reason += "逐条舍弃理由见 rejected。"
        choice = "selected"
    else:
        reason = "全部候选均未通过硬约束，不给出可执行选择；请按 gates 修正约束或方案后重评。"
        choice = "no_feasible_plan"
    def reject_reason(r):
        if r["gates"]:
            return "硬约束未通过：" + "；".join(
                "%s（%s）" % (g["gate"], g.get("resource") or g["detail"]) for g in r["gates"])
        if best and abs(r["weighted"] - best["weighted"]) < 1e-9:
            return "与 %s 加权分相同（%.2f，并列），未选；需补一条判别性证据再定" % (
                best["id"], r["weighted"])
        return "加权分 %.2f 低于 %s 的 %.2f" % (r["weighted"], best["id"], best["weighted"])

    recommendation = {"choice": choice, "plan_id": (best["id"] if best else None),
                      "rationale": reason,
                      "rejected": [{"plan": r["id"], "reason": reject_reason(r)}
                                   for r in rows if r is not best],
                      "sensitivity": sensitivity}

    gates_all = [{"plan": r["id"], **g} for r in rows for g in r["gates"]]
    risks = [{"trigger": "候选方案被淘汰但未给替代路径",
              "consequence": "实验停摆或临时改用未评估路线",
              "mitigation": "为每个被淘汰方案保留一条回退：缩小参数窗口/改设备/拆批次"}]
    for r in rows:
        if r["missing_fields"]:
            risks.append({"trigger": "方案 %s 缺字段：%s" % (r["id"], "、".join(r["missing_fields"])),
                          "consequence": "无法横向对照，评分可能失真",
                          "mitigation": "按统一模板补齐或明确标注未知，不参与对应维度打分"})
    if unavail:
        risks.append({"trigger": "资源不可得记录 %d 条" % len(unavail),
                      "consequence": "方案在'现在可做'层面不成立",
                      "mitigation": "核对货期/档期，必要时改为可预约时段内可完成的缩减版"})
    exceptions = [{"case": "候选全部不可行", "action": "输出淘汰原因与放宽建议，不硬选；status=partial"},
                  {"case": "材料缺单价/工期", "action": "对应维度记 null，权重在可用维度内归一，并写明下限"},
                  {"case": "方案字段不全", "action": "缺哪个字段就标哪个，不用通用流程文本填充"},
                  {"case": "设备不可得/档期冲突", "action": "该方案直接淘汰（硬门控），并给出最近可预约替代"},
                  {"case": "成本币种不一致", "action": "不做跨币种位次，成本维度置 null 并在 uncertainty 说明"},
                  {"case": "重复运行结果不一致", "action": "检查是否同一材料版本；记录输入 sha1 与运行参数"}]
    confirmations = [{"item": "方案 %s 的设备量程与安全边界" % r["id"],
                      "why": "材料可能只写文献区间，需本实验室设备手册确认",
                      "evidence": [{"source": r["source"], "line": r["line"], "locator": r["locator"]}]}
                     for r in rows][:6]
    confirmations.append({"item": "预算与人力单价口径", "why": "材料未给单价时成本为下限，需财务确认",
                          "evidence": ([{"source": budget["source"], "line": budget.get("line"),
                                         "locator": budget.get("path")}] if budget else [])})
    evidence_map = []
    for b in blocks:
        for f, items in b["fields"].items():
            for it in items[:2]:
                evidence_map.append({"claim": "%s 的 %s" % (b["id"], f),
                                     "source": b["source"], "line": it.get("line"),
                                     "locator": it.get("locator"), "quote": it["text"][:150]})
    for p in prices:
        evidence_map.append({"claim": "单价 %s %s/%s" % (p["amount"], p["currency"], p["per"]),
                             "source": p["source"], "line": p.get("line"),
                             "locator": p.get("path"), "quote": p["quote"]})
    for b in budgets:
        evidence_map.append({"claim": "预算 %s %s" % (b["amount"], b["currency"]),
                             "source": b["source"], "line": b.get("line"),
                             "locator": b.get("path"), "quote": b["quote"]})
    for u in unavail:
        evidence_map.append({"claim": "资源不可得", "source": u["source"],
                             "line": u.get("line"), "locator": u.get("path"), "quote": u["text"]})
    for d in domains:
        evidence_map.append({"claim": "参数域 %s %s" % (d["name"], (
            ("[%s, %s]" % (d["lo"], d["hi"])) if d.get("lo") is not None or d.get("hi") is not None
            else "允许值 %s" % "、".join(str(x) for x in (d.get("values") or [])))),
            "source": d["source"], "locator": d["path"], "line": None,
            "quote": json.dumps({k: v for k, v in d.items() if k in ("name", "lo", "hi", "values", "unit")},
                                ensure_ascii=False)})

    cost_data = any(c["known_subtotal"] is not None for c in costs)
    uncertainty = (["未识别出 ≥2 个候选方案；比较结论不可用"] if len(blocks) < 2 else [])
    if truncated:
        uncertainty.append("输入候选数超过展示上限 %d：本次只比较前 %d 个，其余 %d 个未纳入"
                           % (MAX_PLANS, len(blocks), truncated))
    if dup_ids:
        uncertainty.append("存在重复方案 id（%s），已加 #n 后缀区分"
                           % "、".join(sorted(set(dup_ids))))
    if time_warn:
        uncertainty.append(time_warn)
    if not cost_data:
        uncertainty.append("材料/case.json 未给出可解析的成本数据，成本为下限或未知")
    if not any(t["days"] is not None for t in times):
        uncertainty.append("材料未给出工期，时间维度未参与归一")
    if cost_warn:
        uncertainty.append(cost_warn)
    if not domains:
        uncertainty.append("未识别到有限参数域；参数越界门控仅依赖文本上限")
    if len(survivors) == 1:
        uncertainty.append("仅 %d 个方案通过硬约束，成本/时间不做相对位次（位次需要 ≥2 个可比幸存者）" % len(survivors))
    for r in rows:
        if r["cost"]["known_subtotal"] is None:
            uncertainty.append("方案 %s 成本缺少可解析的数量×单价，未参与成本比较" % r["id"])
        elif r["cost"]["unknown_items"]:
            uncertainty.append("方案 %s 有 %d 项缺单价，成本为下限" % (r["id"], r["cost"]["unknown_items"]))
        if r["unscored"]:
            uncertainty.append("方案 %s 的 %s 维度未参与归一（缺数据、已淘汰，或幸存者可比较少）"
                               % (r["id"], "、".join(r["unscored"])))

    input_versions = {"case.json": contract.get("case_sha1"),
                      "materials": {f.get("path"): f.get("sha1") for f in evidence.get("files", [])},
                      "input_mode": input_mode,
                      "weights": WEIGHTS}
    validation = {"checks": [
        {"check": "候选数量与字段齐全度", "result": ("PASS" if len(blocks) >= 2 else "FAIL"),
         "detail": "%d 个候选（%s）；残缺字段统计见 comparison_matrix.csv" % (len(blocks), input_mode)},
        {"check": "矩阵含七字段实际取值",
         "result": ("PASS" if all(not r["missing_fields"] for r in rows) else "PARTIAL"),
         "detail": "；".join("%s 缺 %s" % (r["id"], "、".join(r["missing_fields"]))
                            for r in rows if r["missing_fields"]) or "全部方案七字段齐全"},
        {"check": "硬约束逐条判定",
         "result": ("PASS" if (domains or text_limits or unavail or budget or window_days is not None)
                    else "PARTIAL"),
         "detail": "淘汰 %d 条（%s）；约束来源：%s" % (
             len(gates_all), "、".join(g["gate"] for g in gates_all) or "无",
             "、".join(x for x, ok in (("参数域", bool(domains)), ("文本上限", bool(text_limits)),
                                      ("资源可用性", bool(unavail)), ("预算", bool(budget)),
                                      ("时间窗口", window_days is not None)) if ok) or "未提供")},
        {"check": "参数域来源", "result": ("PASS" if domains else "PARTIAL"),
         "detail": "%d 个有限参数域（case.json）" % len(domains)},
        {"check": "成本复算", "result": ("PASS" if any(c["known_subtotal"] is not None for c in costs) else "PARTIAL"),
         "detail": "; ".join(c["formula"] for c in costs[:3])},
        {"check": "时间复算", "result": ("PASS" if any(t["days"] is not None for t in times) else "PARTIAL"),
         "detail": "; ".join(t["formula"] for t in times[:3])},
        {"check": "相对位次仅用幸存者",
         "result": ("PASS" if len(survivors) >= 2 else "N/A"),
         "detail": "幸存者 %d 个；成本位次覆盖 %d 个，时间位次覆盖 %d 个%s" % (
             len(survivors),
             len([r for r in rows if r["scores"].get("cost") is not None]),
             len([r for r in rows if r["scores"].get("time") is not None]),
             "" if len(survivors) >= 2 else "（不足 2 个，未做位次）")},
        {"check": "权重与得分可复算", "result": "PASS",
         "detail": "加权分=Σ(权重×得分)/Σ可用权重；权重见 scoring.weights"},
    ], "arithmetic_recomputed": True,
        "rerun": "python3 scripts/run_case.py --case /input/case.json --materials /input --work /app/work --out /app/output"}

    fields = {
        "summary": reason, "recommendation": recommendation,
        "comparison_matrix": comparison_matrix, "plans": [
            {"id": r["id"], "title": r["title"], "source": r["source"], "line": r["line"],
             "locator": r["locator"], "fields_present": r["fields_present"],
             "fields_missing": r["missing_fields"]} for r in rows],
        "criteria": criteria,
        "scoring": {"weights": WEIGHTS, "ranked": [{"plan": r["id"], "weighted": r["weighted"],
                                                    "scores": {k: r["scores"].get(k) for k in WEIGHTS}} for r in ranked],
                    "eliminated": [{"plan": r["id"], "gates": [g["gate"] for g in r["gates"]]}
                                   for r in rows if r["gates"]]},
        "cost_model": {"currency": (prices[0]["currency"] if prices else None),
                       "budget": budget, "per_plan": [
                           {"plan": r["id"], **{k: r["cost"][k] for k in
                                                ("known_subtotal", "currency", "unknown_items",
                                                 "is_lower_bound", "formula")}}
                           for r in rows]},
        "risks": risks, "exceptions": exceptions, "confirmations": confirmations,
        "evidence_map": evidence_map, "validation": validation,
        "assumptions": [{"item": "权重", "detail": "默认权重为评审可改的显式设定，不是领域真理"},
                        {"item": "成本口径", "detail": "只汇总材料给出的数量×单价；缺失项不计入并标下限"},
                        {"item": "时间口径", "detail": "汇总材料写明的步骤天数/周数，未计未写明的排队时间"},
                        {"item": "输入通道", "detail": input_mode}],
        "variables": [{"plan": b["id"], "items": [x["text"] for x in b["fields"]["variables"][:4]]}
                      for b in blocks],
        "controls": [{"plan": b["id"], "items": [x["text"] for x in b["fields"]["controls"][:4]]}
                     for b in blocks],
        "procedure": [{"plan": b["id"], "items": [x["text"] for x in b["fields"]["procedure"][:8]]}
                      for b in blocks],
        "parameters": [{"plan": b["id"], "items": [x["text"] for x in b["fields"]["parameters"][:8]]}
                       for b in blocks],
        "resources": [{"plan": b["id"], "items": [x["text"] for x in b["fields"]["resources"][:8]]}
                      for b in blocks],
        "readout": [{"plan": b["id"], "items": [x["text"] for x in b["fields"]["readout"][:4]]}
                    for b in blocks],
        "uncertainty": uncertainty,
        "limits": "", "changes": [],
    }
    status = "ok"
    if truncated:
        status = "partial"
        fields["limits"] = ("输入候选 %d 个，仅比较前 %d 个（超过展示上限 %d）；其余候选未纳入结论"
                            % (len(blocks) + truncated, len(blocks), MAX_PLANS))
    if len(blocks) < 2 or not blocks:
        status = "partial"
        fields["limits"] = "候选方案不足 2 个，无法完成横向比较"
    if not cost_data:
        fields["limits"] = (fields["limits"] + "；" if fields["limits"] else "") + "材料缺成本数据，成本维度不完整"
    if not survivors and blocks:
        status = "partial"
        fields["limits"] = (fields["limits"] + "；" if fields["limits"] else "") + \
            "全部候选未通过硬约束，不给出可执行选择"
    draft = {"status": status, "fields": fields, "uncertainty": fields["uncertainty"],
             "sources": [f.get("path") for f in evidence.get("files", [])],
             "input_mode": input_mode, "input_versions": input_versions,
             "limits": fields["limits"],
             "self_check": {"plans": len(blocks), "survivors": len(survivors),
                            "selected": (best["id"] if best else None),
                            "structured_candidates": len(blocks) if blocks and blocks[0].get("structured") else 0},
             "artifacts": {}}

    md = ["# 实验方案比较与选择", "", "## 结论", "", reason, "",
          "## 横向比较矩阵", "",
          "| 方案 | 来源 | 目标 | 变量 | 对照 | 步骤 | 参数 | 资源 | 判读 | 成本 | 工期(天) | 硬约束 | 加权分 |",
          "|-|-|-|-|-|-|-|-|-|-|-|-|-|"]

    def cell(r, f):
        vals = r["field_values"][f]
        return ("；".join(vals)[:70] + ("…" if len("；".join(vals)) > 70 else "")) if vals else "—"

    for r in rows:
        md.append("| %s | %s%s | %s | %s | %s | %s | %s | %s | %s | %s | %s | %s | %s |" % (
            r["id"], r["source"], (" " + (r["locator"] or "")) if r["locator"] else "",
            cell(r, "objective"), cell(r, "variables"), cell(r, "controls"), cell(r, "procedure"),
            cell(r, "parameters"), cell(r, "resources"), cell(r, "readout"),
            (str(r["cost"]["known_subtotal"]) if r["cost"]["known_subtotal"] is not None else "未知")
            + (" " + str(r["cost"].get("currency")) if r["cost"].get("currency") else ""),
            r["time"]["days"] if r["time"]["days"] is not None else "未知",
            "通过" if not r["gates"] else "淘汰", r["weighted"]))
    md += ["", "## 评分口径", ""] + ["- %s（权重 %.2f）：%s" % (c["criterion"], c["weight"], c["definition"])
                                     for c in criteria]
    md += ["", "## 淘汰与舍弃理由", ""]
    for r in rows:
        if r["gates"]:
            md.append("- %s 淘汰：%s" % (r["id"], "；".join("%s（%s）" % (g["gate"], g["detail"]) for g in r["gates"])))
        elif r is not best:
            md.append("- %s 未选：%s" % (r["id"], "加权分 %.2f 低于 %s" % (
                r["weighted"], best["id"] if best else "-")))
    md += ["", "## 成本与时间复算", ""]
    for c in costs[:6]:
        md.append("- %s" % c["formula"])
    for t in times[:6]:
        md.append("- %s" % t["formula"])
    md += ["", "## 敏感性", ""] + ["- %s → %s" % (s.get("question"), s.get("flip_condition") or s.get("what_if"))
                                   for s in sensitivity]
    md += ["", "## 校验", ""] + ["- %s：%s（%s）" % (c["check"], c["result"], c["detail"])
                                 for c in validation["checks"]]
    if uncertainty:
        md += ["", "## 不确定性", ""] + ["- " + x for x in uncertainty]
    draft["artifacts"]["comparison_report.md"] = "\n".join(md).strip() + "\n"
    dump(draft, os.path.join(a.work, "draft.json"))

    with open(os.path.join(a.work, "comparison_matrix.csv"), "w", encoding="utf-8", newline="") as fh:
        cols = ["plan", "source", "locator"] + SEVEN + [
            "fields_present", "fields_missing", "feasible", "eliminated_by",
            "cost_known", "currency", "cost_lower_bound", "unknown_items", "time_days",
            "risk_items", "risk_unmitigated", "evidence_lines", "weighted"]
        w = csv.DictWriter(fh, fieldnames=cols)
        w.writeheader()
        for r in rows:
            row = {"plan": r["id"], "source": r["source"], "locator": r["locator"] or "",
                   "fields_present": len(r["fields_present"]),
                   "fields_missing": "、".join(r["missing_fields"]) or "-",
                   "feasible": "是" if not r["gates"] else "否",
                   "eliminated_by": "、".join(g["gate"] for g in r["gates"]) or "-",
                   "cost_known": ("" if r["cost"]["known_subtotal"] is None else r["cost"]["known_subtotal"]),
                   "currency": r["cost"].get("currency") or "",
                   "cost_lower_bound": "是" if r["cost"]["is_lower_bound"] else "否",
                   "unknown_items": r["cost"]["unknown_items"],
                   "time_days": r["time"]["days"] if r["time"]["days"] is not None else "",
                   "risk_items": r["risks"]["risk_items"],
                   "risk_unmitigated": r["risks"]["unmitigated"],
                   "evidence_lines": r["evidence_strength"]["evidence_lines"],
                   "weighted": r["weighted"]}
            for f in SEVEN:
                row[f] = "；".join(r["field_values"][f])[:160]
            w.writerow(row)
    print("plans=%d survivors=%d selected=%s status=%s mode=%s" % (
        len(blocks), len(survivors), (best["id"] if best else None), status, input_mode))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
