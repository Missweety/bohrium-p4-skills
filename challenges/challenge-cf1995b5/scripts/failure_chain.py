#!/usr/bin/env python3
"""Build a deterministic failure-chain and stop-loss table from plan.json.

This is a planning aid: it orders steps, maps declared risks, and flags which step
failures block downstream work. It does not validate scientific feasibility.
"""
import argparse
import json
import os


def load(path):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def dump(obj, path):
    os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(obj, fh, ensure_ascii=False, indent=2)


def as_float(value, default=0.0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def risk_step(risk):
    for key in ("step", "step_id", "after_step", "applies_to"):
        value = risk.get(key)
        if value:
            return str(value)
    return ""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--plan", required=True)
    ap.add_argument("--out", default="work")
    args = ap.parse_args()

    plan = load(args.plan)
    steps = plan.get("steps") or []
    risks = plan.get("risks") or []
    window = as_float((plan.get("schedule") or {}).get("window_hours"), 0.0)

    order = {str(s.get("id", i + 1)): i for i, s in enumerate(steps)}
    by_step = {}
    for risk in risks:
        key = risk_step(risk)
        by_step.setdefault(key, []).append(risk)

    rows = []
    total = 0.0
    retry = 0.0
    for index, step in enumerate(steps):
        sid = str(step.get("id", index + 1))
        duration = as_float(step.get("duration_h"))
        total += duration
        downstream = [str(s.get("id", j + 1)) for j, s in enumerate(steps) if j > index]
        mapped = by_step.get(sid, []) + by_step.get("", [])
        indicator = (step.get("readout") or "").strip()
        first = mapped[0] if mapped else {}
        stop_loss = first.get("stop_loss") or ""
        fallback = first.get("fallback") or ""
        if downstream and not fallback:
            priority = "P0"
        elif downstream:
            priority = "P1"
        else:
            priority = "P2"
        if mapped and priority in ("P0", "P1"):
            retry += duration
        rows.append({
            "step": sid, "action": step.get("action"), "duration_h": duration,
            "detection": indicator or "未声明判读动作",
            "risk_modes": [r.get("mode") for r in mapped if r.get("mode")],
            "threshold": first.get("threshold") or "待确认",
            "stop_loss": stop_loss or "未声明：失败时先停批并补测本步对照",
            "fallback": fallback or "无备选，需人工决策",
            "blocks": downstream,
            "priority": priority,
        })

    overrun = None
    if window:
        overrun = {"planned_h": round(total, 2), "retry_h": round(retry, 2),
                   "window_h": round(window, 2),
                   "exceeds_window": (total + retry) > window,
                   "slack_h": round(window - total - retry, 2)}
    gaps = [r["step"] for r in rows if not r["risk_modes"]]
    report = {
        "steps": len(rows),
        "risks": len(risks),
        "unmapped_steps": gaps,
        "critical_path": rows,
        "retry_budget": overrun,
        "note": "P0=失败即阻塞后续且无备选；P1=阻塞但有备选；P2=仅影响本步。仅编排与算术提示，不验证科学可行性。",
    }
    dump(report, os.path.join(args.out, "failure_chain.json"))

    lines = ["# 失败链与止损优先级", "",
             "| 步骤 | 动作 | 早期信号 | 判据 | 止损 | 备选 | 阻塞后续 | 优先级 |",
             "|---|---|---|---|---|---|---|---|"]
    for row in rows:
        cells = [row["step"], row["action"] or "", row["detection"], row["threshold"],
                 row["stop_loss"], row["fallback"], ", ".join(row["blocks"]) or "—", row["priority"]]
        lines.append("| " + " | ".join(str(c).replace("|", "\\|") for c in cells) + " |")
    if overrun:
        lines += ["", f"计划总时长 {overrun['planned_h']} h，含 P0/P1 一次重试 {overrun['retry_h']} h，"
                      f"窗口 {overrun['window_h']} h，余量 {overrun['slack_h']} h；"
                      f"{'超出窗口' if overrun['exceeds_window'] else '窗口内可执行'}。"]
    if gaps:
        lines += ["", "未映射风险的步骤：" + ", ".join(gaps) + "（需补 failure mode 或说明为何无需）。"]
    with open(os.path.join(args.out, "failure_chain.md"), "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")

    print("steps=%d risks=%d unmapped=%d p0=%d overrun=%s"
          % (len(rows), len(risks), len(gaps),
             sum(1 for r in rows if r["priority"] == "P0"),
             overrun["exceeds_window"] if overrun else "na"))


if __name__ == "__main__":
    main()
