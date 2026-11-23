#!/usr/bin/env python3
"""design_checklist.py - audit an executable experiment plan before delivery.

Hard: six elements; goal transcribed into a testable endpoint; >=5 steps each bound to
parameters/resources/readout/duration; legal parameter basis whose values exist in the
materials; budget, schedule and equipment arithmetic; >=2 controls with excluded
confounds; >=3 five-part risks; 3 genuinely different versions with a recommendation and
a stated sacrifice; no fabricated pilot claim; no textbook-outline phrasing.

Exit 0 when executable and evidence-bound; 1 otherwise.
"""
import argparse, json, os, re, sys

BASIS = {"equipment_spec", "organizer_contract", "literature_in_material", "assumed"}
CTRL = {"negative", "vehicle", "positive", "dose_gradient", "sham"}
NUM = re.compile(r"[-+]?\d+(?:[.,]\d+)?")
PILOT = re.compile(r"(预实验已|已完成预实验|已做过预实验|pilot (study )?(showed|confirmed))", re.I)
ETHICS = re.compile(r"(patient|mice|mouse|human|动物|受试者|临床)", re.I)
# The task text explicitly calls these "textbook table of contents" outputs.
GENERIC = re.compile(r"(准备样品|设置对照|检测分析|统计分析|常规操作|按标准流程|注意安全|严格操作|"
                     r"约一天|大致|左右即可|standard protocol|as usual|carefully follow)", re.I)
DASH = str.maketrans({"–": "-", "—": "-", "−": "-", "~": "-", "，": ",", "。": "."})


def norm(s):
    return re.sub(r"\s+", "", str(s)).lower().translate(DASH)


def num(x):
    m = NUM.search(str(x))
    return float(m.group(0).replace(",", ".")) if m else None


def need(obj, keys, label, errs):
    errs += ["%s missing %s" % (label, k) for k in keys if not str(obj.get(k, "")).strip()]


def value_in_corpus(val, corpus):
    """Return 'exact' | 'loose' | 'missing' for a parameter value against materials."""
    v = norm(val)
    if not v:
        return "exact"
    if v in corpus:
        return "exact"
    toks = re.findall(r"\d+(?:\.\d+)?", v)
    if toks and all(t in corpus for t in toks):
        return "loose"
    return "missing"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--plan", required=True)
    ap.add_argument("--corpus", default="")
    ap.add_argument("--plan-md", default="")
    ap.add_argument("--out", default="work")
    a = ap.parse_args()
    plan = json.load(open(a.plan, encoding="utf-8"))
    corpus = norm(open(a.corpus, encoding="utf-8").read()) if a.corpus and os.path.exists(a.corpus) else ""
    E, W, assumed, loose = [], [], [], []

    if not str(plan.get("goal", "")).strip():
        E.append("goal missing: restate the research goal and its testable endpoint")
    need(plan.get("hypothesis") or {}, ("statement", "direction", "falsify_if", "endpoint"), "hypothesis", E)
    v = plan.get("variables") or {}
    ind, dep, con = v.get("independent") or [], v.get("dependent") or [], v.get("confounders") or []
    for name, items in (("independent", ind), ("dependent", dep), ("confounders", con)):
        if not items:
            E.append("variables.%s missing" % name)
    E += ["independent %s lacks levels/operational" % x.get("name") for x in ind
          if not x.get("levels") or not str(x.get("operational", "")).strip()]
    E += ["dependent %s lacks instrument/unit" % x.get("name") for x in dep
          if not x.get("unit") or not x.get("instrument")]
    E += ["confounder %s has no control measure" % x.get("name") for x in con
          if not str(x.get("control", "")).strip()]
    ctrl = plan.get("controls") or []
    if len(ctrl) < 2:
        E.append("controls < 2: cannot attribute the observed effect")
    E += ["control invalid type: %s" % c.get("type") for c in ctrl if c.get("type") not in CTRL]
    E += ["control %s does not state the confound it excludes" % c.get("type")
          for c in ctrl if not str(c.get("excludes", "")).strip()]
    if ctrl and not any(c.get("type") in {"positive", "vehicle", "dose_gradient", "sham"} for c in ctrl):
        W.append("only negative controls: no positive/vehicle control")

    ss = plan.get("sample_size") or {}
    if (num(ss.get("n_per_group")) or 0) <= 0:
        E.append("sample_size.n_per_group missing/zero")
    if (num(ss.get("groups")) or 0) < 2:
        E.append("sample_size.groups missing (<2)")
    if ss.get("basis") not in {"power", "assumed", "organizer_contract"}:
        E.append("sample_size.basis invalid: %s" % ss.get("basis"))
    if ss.get("basis") == "power":
        miss = [k for k in ("alpha", "power", "effect_size", "sd") if k not in (ss.get("inputs") or {})]
        if miss:
            E.append("power basis missing inputs: %s" % ",".join(miss))
        if not str(ss.get("effect_size_source", "")).strip():
            E.append("power basis missing effect_size_source")

    params = plan.get("parameters") or []
    names = [p.get("name") for p in params if p.get("name")]
    if len(params) < 3:
        E.append("parameters < 3: procedure outline, not an executable protocol")
    for p in params:
        name, basis, val = p.get("name"), p.get("basis"), str(p.get("value", "")).strip()
        if basis not in BASIS:
            E.append("parameter %s invalid basis: %s" % (name, basis))
            continue
        if not val:
            E.append("parameter %s missing value" % name)
        if num(val) is not None and not str(p.get("unit", "")).strip():
            E.append("parameter %s numeric value without unit" % name)
        if not str(p.get("range", "")).strip():
            E.append("parameter %s missing allowed range (units + over-range action)" % name)
        if not str(p.get("action", "")).strip():
            E.append("parameter %s missing out-of-range action" % name)
        if basis == "assumed":
            assumed.append(name)
            need(p, ("assumption", "sensitivity"), "assumed parameter %s" % name, E)
        elif not str(p.get("source", "")).strip():
            E.append("parameter %s basis=%s without source" % (name, basis))
        elif corpus:
            hit = value_in_corpus(val, corpus)
            if hit == "missing":
                E.append("parameter %s value %r not found in materials" % (name, val))
            elif hit == "loose":
                loose.append(name)

    steps = plan.get("steps") or []
    if len(steps) < 5:
        E.append("steps < 5: a protocol needs executable steps, not an outline")
    for s in steps:
        sid = s.get("id") or s.get("step") or "?"
        need(s, ("action", "readout"), "step %s" % sid, E)
        if not (s.get("params") or s.get("parameters")):
            E.append("step %s not bound to any parameter" % sid)
        else:
            refs = s.get("params") or s.get("parameters")
            bad = [r for r in refs if r not in names]
            if bad:
                E.append("step %s references unknown parameter(s): %s" % (sid, ",".join(map(str, bad))))
        if (num(s.get("duration_h")) or 0) <= 0:
            E.append("step %s missing duration_h" % sid)
        if GENERIC.search(str(s.get("action", ""))):
            E.append("step %s uses textbook-outline wording: %r" % (sid, s.get("action")))

    res = plan.get("resources") or {}
    eq, cons = res.get("equipment") or [], res.get("consumables") or []
    if not eq:
        E.append("resources.equipment missing")
    if not cons:
        E.append("resources.consumables missing")
    for e in eq:
        if not str(e.get("model", "")).strip():
            W.append("equipment %s has no model/spec" % e.get("name"))
        need_h, avail = num(e.get("needs_h")), num(e.get("available_h"))
        if need_h is not None and avail is not None and need_h > avail:
            E.append("equipment %s needs %.1fh > available %.1fh" % (e.get("name"), need_h, avail))
    subtotal = 0.0
    for c in cons:
        q, pr = num(c.get("qty")), num(c.get("unit_price"))
        if q is None or pr is None:
            E.append("consumable %s missing qty/unit_price" % c.get("item"))
        else:
            subtotal += q * pr
    budget, sch = plan.get("budget") or {}, plan.get("schedule") or {}
    total, cap = num(budget.get("total")), num(budget.get("cap"))
    if subtotal and total is not None and abs(subtotal - total) > max(1.0, 0.01 * max(subtotal, total)):
        E.append("consumables subtotal %.2f != budget.total %.2f" % (subtotal, total))
    if total is not None and cap is not None and total > cap:
        E.append("budget.total %.2f > cap %.2f" % (total, cap))
    if cap is not None and not str(budget.get("currency", "")).strip():
        E.append("budget without currency")
    sess, per = num(sch.get("sessions")), num(sch.get("hours_per_session"))
    hours, window = num(sch.get("total_hours")), num(sch.get("window_hours"))
    if sess and per and hours is not None and abs(sess * per - hours) > 0.01 * max(1.0, hours):
        E.append("total_hours %.1f != sessions*per_session %.1f" % (hours, sess * per))
    if hours is not None and window is not None and hours > window:
        E.append("total_hours %.1f > window %.1f" % (hours, window))
    step_sum = sum(num(s.get("duration_h")) or 0 for s in steps)
    if hours is not None and step_sum > hours + 0.01:
        W.append("sum(step duration_h)=%.1f exceeds schedule.total_hours=%.1f (check parallelism)" % (step_sum, hours))

    risks = plan.get("risks") or []
    if len(risks) < 3:
        E.append("risks < 3: failure modes are not covered")
    for r in risks:
        need(r, ("mode", "indicator", "threshold", "stop_loss", "fallback"), "risk %s" % r.get("mode"), E)
        if GENERIC.search(str(r.get("fallback", ""))):
            E.append("risk %s fallback is generic: %r" % (r.get("mode"), r.get("fallback")))

    vers = plan.get("versions") or []
    if len(vers) < 3:
        E.append("versions < 3: need baseline/budget/power candidates")
    for x in vers:
        need(x, ("id", "label", "n_per_group", "cost", "hours", "changes"), "version %s" % x.get("id"), E)
        if len(str(x.get("changes", "")).strip()) < 12:
            E.append("version %s changes too thin to be a real design difference" % x.get("id"))
    sig = {(num(x.get("n_per_group")), num(x.get("cost")), num(x.get("hours"))) for x in vers}
    if len(vers) >= 3 and len(sig) < 2:
        E.append("versions share identical n/cost/hours: not genuinely different candidates")
    rec = plan.get("recommendation") or {}
    if not str(rec.get("id", "")).strip():
        E.append("recommendation.id missing")
    elif vers and rec["id"] not in {x.get("id") for x in vers}:
        E.append("recommendation.id %s not among versions" % rec["id"])
    need(rec, ("rationale", "sacrifice"), "recommendation", E)

    confs = plan.get("confirmations") or []
    if not confs:
        E.append("confirmations missing (safety/ethics/equipment availability)")
    for c in confs:
        need(c, ("item", "owner", "why"), "confirmation %s" % c.get("item"), E)
    if corpus and ETHICS.search(corpus) and not any("伦理" in str(c.get("item")) for c in confs):
        E.append("human/animal material present but no ethics confirmation")

    blob = json.dumps(plan, ensure_ascii=False)
    if PILOT.search(blob):
        E.append("plan claims a completed pilot/pre-experiment (fabricated state)")
    if a.plan_md and os.path.exists(a.plan_md):
        md = open(a.plan_md, encoding="utf-8").read()
        if len(md) < 1200:
            W.append("plan.md shorter than 1200 chars: may not be executable")
        if GENERIC.search(md):
            W.append("plan.md contains textbook-outline wording (check against the six-element table)")

    report = {
        "ok": not E, "errors": E, "warnings": W, "assumed_parameters": assumed,
        "loosely_matched_parameters": loose, "consumables_subtotal": round(subtotal, 2),
        "budget_total": total, "budget_cap": cap, "total_hours": hours, "window_hours": window,
        "versions": len(vers), "risks": len(risks), "steps": len(steps),
        "checked": ["hypothesis", "variables", "controls", "sample_size", "parameters",
                    "steps", "resources", "budget", "schedule", "risks", "versions",
                    "recommendation", "confirmations"],
    }
    os.makedirs(a.out, exist_ok=True)
    json.dump(report, open(os.path.join(a.out, "checklist.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    md = ["# 实验方案校验", "",
          "要素：%s；假定参数：%s；步骤 %d；版本 %d；风险 %d"
          % ("通过" if not E else "未通过", ", ".join(assumed) or "无", len(steps), len(vers), len(risks)),
          "算术：耗材 %.2f / 预算 %.2f / 上限 %.2f；工时 %.1f / 窗口 %.1f"
          % (subtotal, total or 0, cap or 0, hours or 0, window or 0),
          "", "## 硬错误"] + (["- %s" % e for e in E] or ["- 无"])
    md += ["", "## 警告"] + (["- %s" % w for w in W] or ["- 无"])
    open(os.path.join(a.out, "checklist.md"), "w", encoding="utf-8").write("\n".join(md) + "\n")
    print("verdict=%s errors=%d warnings=%d assumed=%d steps=%d"
          % ("pass" if not E else "review", len(E), len(W), len(assumed), len(steps)))
    for msg in E[:12]:
        print("  !", msg)
    for msg in W[:6]:
        print("  ~", msg)
    return 0 if not E else 1


if __name__ == "__main__":
    sys.exit(main())
