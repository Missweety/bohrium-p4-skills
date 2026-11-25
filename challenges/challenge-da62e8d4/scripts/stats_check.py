#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""stats_check.py - deterministic re-computation used by the reproduction audit.

Only relations that are fully determined by the text are computed:
  * two-sided Student-t p-value from (t, df)
  * two-sided normal p-value from z
  * percent change from (from, to)
  * CI half-width from standard error (mean, se) -> 1.96*se

No model is trained, no external data is fetched, and nothing is imputed.
Every function returns a JSON-ready dict so the check can be replayed.

CLI:  python3 scripts/stats_check.py --t 2.45 --df 28
"""
from __future__ import annotations

import argparse
import json
import math


def _betacf(a, b, x, max_iter=200, eps=3e-12):
    """Continued fraction for the incomplete beta function (Numerical Recipes)."""
    qab, qap, qam = a + b, a + 1.0, a - 1.0
    c, d = 1.0, 1.0 - qab * x / qap
    if abs(d) < 1e-30:
        d = 1e-30
    d = 1.0 / d
    h = d
    for m in range(1, max_iter + 1):
        m2 = 2 * m
        aa = m * (b - m) * x / ((qam + m2) * (a + m2))
        d = 1.0 + aa * d
        if abs(d) < 1e-30:
            d = 1e-30
        c = 1.0 + aa / c
        if abs(c) < 1e-30:
            c = 1e-30
        d = 1.0 / d
        h *= d * c
        aa = -(a + m) * (qab + m) * x / ((a + m2) * (qap + m2))
        d = 1.0 + aa * d
        if abs(d) < 1e-30:
            d = 1e-30
        c = 1.0 + aa / c
        if abs(c) < 1e-30:
            c = 1e-30
        d = 1.0 / d
        delta = d * c
        h *= delta
        if abs(delta - 1.0) < eps:
            break
    return h


def betai(a, b, x):
    """Regularized incomplete beta I_x(a,b)."""
    if x <= 0.0:
        return 0.0
    if x >= 1.0:
        return 1.0
    lbeta = math.lgamma(a) + math.lgamma(b) - math.lgamma(a + b)
    front = math.exp(math.log(x) * a + math.log(1.0 - x) * b - lbeta) / a
    if x < (a + 1.0) / (a + b + 2.0):
        return front * _betacf(a, b, x)
    return 1.0 - math.exp(math.log(x) * a + math.log(1.0 - x) * b - lbeta) / b * \
        _betacf(b, a, 1.0 - x)


def t_to_p(t, df):
    """Two-sided p-value for Student's t."""
    if df <= 0:
        raise ValueError("df must be positive")
    t = float(t)
    if not math.isfinite(t):
        raise ValueError("t must be finite")
    x = df / (df + t * t)
    return 2.0 * 0.5 * betai(df / 2.0, 0.5, x)


def z_to_p(z):
    """Two-sided p-value for the standard normal."""
    return math.erfc(abs(float(z)) / math.sqrt(2.0))


def percent_change(start, end):
    if start == 0:
        raise ValueError("start must be non-zero")
    return (end - start) / start * 100.0


def ci_half_width(se, z=1.96):
    return z * se


def compare(reported, computed, tol=1e-3):
    """Return consistent / inconsistent / not_checkable with the tolerance used."""
    if reported is None or computed is None:
        return {"verdict": "not_checkable", "tolerance": tol}
    diff = abs(float(reported) - float(computed))
    return {
        "verdict": "consistent" if diff <= tol else "inconsistent",
        "reported": reported,
        "computed": round(computed, 6),
        "abs_diff": round(diff, 6),
        "tolerance": tol,
    }


def main(argv=None):
    ap = argparse.ArgumentParser(description="deterministic statistics check")
    ap.add_argument("--t", type=float)
    ap.add_argument("--df", type=float)
    ap.add_argument("--z", type=float)
    ap.add_argument("--from", dest="start", type=float)
    ap.add_argument("--to", dest="end", type=float)
    a = ap.parse_args(argv)
    out = {}
    if a.t is not None and a.df is not None:
        p = t_to_p(a.t, a.df)
        out["t_to_p"] = {"inputs": {"t": a.t, "df": a.df}, "computed": p,
                         "formula": "two-sided Student-t survival via incomplete beta"}
    if a.z is not None:
        p = z_to_p(a.z)
        out["z_to_p"] = {"inputs": {"z": a.z}, "computed": p,
                         "formula": "two-sided normal via incomplete beta"}
    if a.start is not None and a.end is not None:
        out["percent_change"] = {"inputs": {"from": a.start, "to": a.end},
                                 "computed": percent_change(a.start, a.end)}
    print(json.dumps(out, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
