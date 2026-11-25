"""Hindsight labels: the answer key the metric is graded against.

Two things are built here, both from price alone and both with full hindsight:

1. Turning points.  A zig-zag on price: a top is confirmed once price has fallen
   by ``down`` from it, a bottom once price has risen by ``up`` from it.  Large
   thresholds find the handful of cycle turns, smaller ones the swings inside a
   cycle, so every pivot is tagged with the biggest threshold at which it still
   shows up.

2. The hindsight value (``ideal_risk``).  For each day, where log price sat
   inside the leg between the two turning points around it: exactly 0 at a
   bottom, exactly 1 at a top and graded in between, which is the "every day
   gets a score" target.

These labels grade the metric, and at design time they decide which indicators
are trusted (``select_by_rule`` in model.py; scripts/run_backtest.py re-runs
that choice blind).  They never enter the daily calculation of the score.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd


@dataclass
class Pivot:
    date: pd.Timestamp
    price: float
    kind: str  # "top" or "bottom"


def zigzag(price: pd.Series, up: float, down: float) -> list[Pivot]:
    """Zig-zag pivots. ``up``/``down`` are fractional moves, e.g. up=1.0 (+100%), down=0.5 (-50%)."""
    p = price.dropna()
    dates, vals = p.index, p.values
    pivots: list[Pivot] = []
    # Start by tracking both extremes until the first confirmed reversal.
    hi_i = lo_i = 0
    direction = 0  # +1 = in an up-leg (looking for a top), -1 = in a down-leg
    for i in range(1, len(vals)):
        v = vals[i]
        if direction >= 0:
            if v > vals[hi_i]:
                hi_i = i
            elif v <= vals[hi_i] * (1 - down):
                # top confirmed at hi_i
                if direction == 0 and vals[lo_i] < vals[hi_i] and lo_i < hi_i:
                    pivots.append(Pivot(dates[lo_i], float(vals[lo_i]), "bottom"))
                pivots.append(Pivot(dates[hi_i], float(vals[hi_i]), "top"))
                direction, lo_i = -1, i
                continue
        if direction <= 0:
            if v < vals[lo_i]:
                lo_i = i
            elif v >= vals[lo_i] * (1 + up):
                if direction == 0 and vals[hi_i] > vals[lo_i] and hi_i < lo_i:
                    pivots.append(Pivot(dates[hi_i], float(vals[hi_i]), "top"))
                pivots.append(Pivot(dates[lo_i], float(vals[lo_i]), "bottom"))
                direction, hi_i = 1, i
    return pivots


# Threshold ladder: (name, decline that confirms a top, rally that confirms a bottom).
# Declines and rallies are matched in log terms: -50% <-> +100%, -33% <-> +50% ...
LADDER = [
    ("cycle", 0.70, 2.3333),   # -70% / +233%: the four-year cycle turns
    ("major", 0.50, 1.0),      # -50% / +100%
    ("swing", 0.3333, 0.50),   # -33% / +50%
    ("minor", 0.20, 0.25),     # -20% / +25%
]


def multiscale_pivots(price: pd.Series) -> pd.DataFrame:
    """All pivots from the ladder, each tagged with its highest significance level."""
    rank = {name: i for i, (name, _, _) in enumerate(LADDER)}
    best: dict[tuple, str] = {}
    for name, down, up in LADDER:
        for pv in zigzag(price, up=up, down=down):
            key = (pv.date, pv.kind)
            if key not in best or rank[name] < rank[best[key]]:
                best[key] = name
    rows = [
        {"date": d, "kind": k, "price": float(price.loc[d]), "level": lvl}
        for (d, k), lvl in best.items()
    ]
    return pd.DataFrame(rows).sort_values("date").reset_index(drop=True)


def leg_position(price: pd.Series, pivots: pd.DataFrame) -> pd.Series:
    """Hindsight position of log price inside the leg between two consecutive pivots.

    0 at a bottom, 1 at a top, linear in log price in between.  Days before the
    first pivot or after the last one are NaN (the leg is not finished, so the
    answer is not known yet).
    """
    logp = np.log(price)
    out = pd.Series(np.nan, index=price.index)
    pv = pivots.sort_values("date").reset_index(drop=True)
    for i in range(len(pv) - 1):
        a, b = pv.loc[i], pv.loc[i + 1]
        if a["kind"] == b["kind"]:
            continue
        lo = min(np.log(a["price"]), np.log(b["price"]))
        hi = max(np.log(a["price"]), np.log(b["price"]))
        seg = logp.loc[a["date"]: b["date"]]
        if hi > lo:
            out.loc[seg.index] = ((seg - lo) / (hi - lo)).clip(0, 1)
    return out


def alternate(pivots: pd.DataFrame) -> pd.DataFrame:
    """Force strict top/bottom alternation, keeping the more extreme of same-kind neighbours."""
    rows: list[dict] = []
    for _, r in pivots.sort_values("date").iterrows():
        r = r.to_dict()
        if rows and rows[-1]["kind"] == r["kind"]:
            better = (r["price"] > rows[-1]["price"]) if r["kind"] == "top" else (r["price"] < rows[-1]["price"])
            if better:
                rows[-1] = r
        else:
            rows.append(r)
    return pd.DataFrame(rows)


def ideal_risk(price: pd.Series, start: str = "2011-06-01") -> pd.DataFrame:
    """Hindsight 'ideal' risk curves at three zoom levels plus their blend.

    ``ideal_cycle`` uses only the big four-year turns, ``ideal_major`` adds the
    -50% / +100% turns (2019 top, March 2020 low, the two 2021 tops), and
    ``ideal_swing`` the -33% / +50% swings.  ``ideal`` is the average of cycle
    and major: the target the metric is graded against.
    """
    pv = multiscale_pivots(price)
    pv = pv[pv["date"] >= pd.Timestamp(start)]
    levels = {
        "cycle": ["cycle"],
        "major": ["cycle", "major"],
        "swing": ["cycle", "major", "swing"],
    }
    out = {}
    for name, keep in levels.items():
        sub = pv[pv["level"].isin(keep)]
        if name == "cycle":
            # The most recent top is not yet "cycle" sized by the -70% rule but is the
            # cycle's record high and confirmed at the major level: treat it as the cycle top.
            last_major_top = pv[(pv["level"] == "major") & (pv["kind"] == "top")].tail(1)
            if len(last_major_top) and last_major_top["date"].iloc[0] > sub["date"].max():
                sub = pd.concat([sub, last_major_top])
        out[f"ideal_{name}"] = leg_position(price, alternate(sub))
    res = pd.DataFrame(out)
    res["ideal"] = res[["ideal_cycle", "ideal_major"]].mean(axis=1, skipna=False)
    return res
