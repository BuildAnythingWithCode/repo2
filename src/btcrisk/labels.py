"""Hindsight labels used ONLY to grade the metric (and to fit a few weights
inside walk-forward folds).  Nothing here may ever feed the live score.

Two kinds of ground truth:

1. Turning points.  A zig-zag on log price: a top is confirmed once price has
   fallen by ``down`` from it, a bottom once price has risen by ``up`` from it.
   Large thresholds find the handful of cycle turns, small ones find the local
   swings, so every pivot gets a *significance* (the biggest threshold at which
   it still shows up).

2. Oracle risk.  For each day, look ahead ``horizon`` days and ask how much of
   the price range still to come lies below today's price:

       oracle = D / (D + U),  D = log(P_t / min future P),  U = log(max future P / P_t)

   It is exactly 1 at a top (nothing but downside ahead), exactly 0 at a bottom
   and graded in between, which is the "every day gets a score" target.
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


def pivots_frame(pivots: list[Pivot]) -> pd.DataFrame:
    return pd.DataFrame([{"date": p.date, "price": p.price, "kind": p.kind} for p in pivots])


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


def oracle_risk(price: pd.Series, horizon: int) -> pd.Series:
    """Forward-looking range position in [0, 1]; NaN where the look-ahead is incomplete."""
    logp = np.log(price)
    # Forward rolling min/max over (t, t+horizon], via reversed backward windows.
    rev = logp[::-1]
    fmin = rev.rolling(horizon, min_periods=horizon).min()[::-1].shift(-1)
    fmax = rev.rolling(horizon, min_periods=horizon).max()[::-1].shift(-1)
    d = (logp - np.minimum(fmin, logp)).clip(lower=0)
    u = (np.maximum(fmax, logp) - logp).clip(lower=0)
    out = d / (d + u)
    out[(d + u) == 0] = 0.5
    return out.rename(f"oracle_{horizon}")


def forward_extremes(price: pd.Series, horizon: int) -> pd.DataFrame:
    """Max drawdown and max gain (as fractions) over the next ``horizon`` days."""
    logp = np.log(price)
    rev = logp[::-1]
    fmin = rev.rolling(horizon, min_periods=horizon).min()[::-1].shift(-1)
    fmax = rev.rolling(horizon, min_periods=horizon).max()[::-1].shift(-1)
    fret = logp.shift(-horizon) - logp
    return pd.DataFrame(
        {
            f"fwd_dd_{horizon}": np.exp(np.minimum(fmin - logp, 0)) - 1,
            f"fwd_up_{horizon}": np.exp(np.maximum(fmax - logp, 0)) - 1,
            f"fwd_ret_{horizon}": np.exp(fret) - 1,
        }
    )


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
