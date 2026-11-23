#!/usr/bin/env python3
"""run_case.py - one-command pipeline for literature review / trend analysis.

Usage:
  python3 scripts/run_case.py --case /input/case.json --work /app/work --out /app/output --mode review
  python3 scripts/run_case.py --case /input/case.json --work /app/work --out /app/output --mode trends
"""
import argparse
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))


def run(script, args, work):
    cmd = [sys.executable] + (["-B"] if "--no-bytecode" in args else []) + [os.path.join(HERE, script)] + \
          [x for x in args if x != "--no-bytecode"]
    print("[run]", script, " ".join(x for x in args if x != "--no-bytecode"))
    r = subprocess.run(cmd, cwd=work)
    if r.returncode != 0:
        label = " ".join([script] + [x for x in args[:1] if not x.startswith("--")])
        raise RuntimeError("%s exited %d" % (label, r.returncode))


def dump(obj, path):
    os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(obj, fh, ensure_ascii=False, indent=1)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--case", default="/input/case.json")
    ap.add_argument("--work", default="/app/work")
    ap.add_argument("--out", default="/app/output")
    ap.add_argument("--mode", choices=["review", "trends"], default="review")
    ap.add_argument("--no-bytecode", action="store_true")
    a = ap.parse_args()
    os.makedirs(a.work, exist_ok=True)
    os.makedirs(a.out, exist_ok=True)
    w = a.work
    try:
        run("kernel.py", ["init", "--case", a.case, "--out", w], w)
        run("engine.py", ["index", "--case", os.path.join(w, "case.raw.json"),
                          "--out", os.path.join(w, "records.json")], w)
        run("engine.py", ["screen", "--case", os.path.join(w, "case.raw.json"),
                          "--index", os.path.join(w, "records.json"),
                          "--out", os.path.join(w, "screening.json")], w)
        run("engine.py", ["matrix", "--screen", os.path.join(w, "screening.json"),
                          "--out", os.path.join(w, "matrix.json")], w)
        run("engine.py", ["themes", "--matrix", os.path.join(w, "matrix.json"),
                          "--out", os.path.join(w, "themes.json")], w)
        if a.mode == "trends":
            run("engine.py", ["trends", "--matrix", os.path.join(w, "matrix.json"),
                              "--themes", os.path.join(w, "themes.json"),
                              "--out", os.path.join(w, "trends.json")], w)
        run("engine.py", ["synthesize", "--mode", a.mode,
                          "--screen", os.path.join(w, "screening.json"),
                          "--matrix", os.path.join(w, "matrix.json"),
                          "--themes", os.path.join(w, "themes.json"),
                          "--trends", os.path.join(w, "trends.json"), "--work", w, "--out", a.out], w)
        run("engine.py", ["verify", "--mode", a.mode,
                          "--screen", os.path.join(w, "screening.json"),
                          "--matrix", os.path.join(w, "matrix.json"),
                          "--themes", os.path.join(w, "themes.json"),
                          "--trends", os.path.join(w, "trends.json"), "--work", w], w)
        run("engine.py", ["emit", "--mode", a.mode,
                          "--index", os.path.join(w, "records.json"),
                          "--screen", os.path.join(w, "screening.json"),
                          "--matrix", os.path.join(w, "matrix.json"),
                          "--themes", os.path.join(w, "themes.json"),
                          "--trends", os.path.join(w, "trends.json"), "--work", w, "--out", a.out], w)
        chk = subprocess.run([sys.executable, os.path.join(HERE, "kernel.py"), "check", "--out", a.out],
                             cwd=w, capture_output=True, text=True)
        print(chk.stdout.strip())
        return 0 if chk.returncode == 0 else 1
    except RuntimeError as exc:
        status = "blocked" if "index exited" in str(exc) or "screen exited" in str(exc) \
            or "matrix exited" in str(exc) or "init exited" in str(exc) else "partial"
        try:
            with open(os.path.join(w, "screening.json"), encoding="utf-8") as fh:
                scr = json.load(fh)
        except Exception:  # noqa: BLE001
            scr = {}
        dump({"case_id": None, "status": status, "mode": a.mode,
              "research_product": None, "evidence_matrix": [],
              "uncertainty": {}, "screening": scr, "checks": {},
              "counts": {"included": len(scr.get("included", [])), "themes": 0, "gaps": 0, "years": 0},
              "failures": [{"reason": str(exc)[:160]}],
              "limits": "运行中止：%s" % str(exc)[:200]}, os.path.join(a.out, "result.json"))
        print("stopped:", exc)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
