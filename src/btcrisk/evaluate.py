"""Grade a risk series against hindsight.

The headline questions, in plain terms:
  * Did it read near 1 at the real tops and near 0 at the real bottoms?
  * When it was in its extreme zones, how close was price to the actual top or
    bottom (how good would selling / buying there have been)?
  * In between, did it track where price sat inside the cycle?
  * Did high readings really come before bad returns, and low before good ones?
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .labels import alternate, ideal_risk, multiscale_pivots

ERAS = {
    "2012-14": ("2012-01-01", "2014-12-31"),
    "2015-18": ("2015-01-01", "2018-12-31"),
    "2019-22": ("2019-01-01", "2022-12-31"),
    "2023-25": ("2023-01-01", "2025-10-06"),
}
# The three cycles that are complete AND fully scored: used for the headline grades.
FULL_CYCLES = {k: ERAS[k] for k in ("2015-18", "2019-22", "2023-25")}
CYCLE_TOPS = ["2017-12-16", "2021-11-08", "2025-10-06"]
CYCLE_BOTTOMS = ["2015-01-14", "2018-12-15", "2022-11-09"]


def cycle_pivots(price: pd.Series, start: str = "2011-06-01", level: str = "cycle") -> pd.DataFrame:
    pv = multiscale_pivots(price)
    pv = pv[pv["date"] >= pd.Timestamp(start)]
    keep = ["cycle"] if level == "cycle" else ["cycle", "major"]
    sub = pv[pv["level"].isin(keep)]
    if level == "cycle":
        last_major_top = pv[(pv["level"] == "major") & (pv["kind"] == "top")].tail(1)
        if len(last_major_top) and last_major_top["date"].iloc[0] > sub["date"].max():
            sub = pd.concat([sub, last_major_top])
    return alternate(sub).reset_index(drop=True)


def leg_reference(price: pd.Series, pivots: pd.DataFrame) -> pd.DataFrame:
    """For each day: the top and bottom prices of the leg it belongs to."""
    out = pd.DataFrame(index=price.index, columns=["ref_top", "ref_bottom"], dtype=float)
    pv = pivots.sort_values("date").reset_index(drop=True)
    for i in range(len(pv) - 1):
        a, b = pv.loc[i], pv.loc[i + 1]
        top = a["price"] if a["kind"] == "top" else b["price"]
        bot = a["price"] if a["kind"] == "bottom" else b["price"]
        out.loc[a["date"]: b["date"], "ref_top"] = top
        out.loc[a["date"]: b["date"], "ref_bottom"] = bot
    # after the last pivot only one side is known
    last = pv.iloc[-1]
    col = "ref_top" if last["kind"] == "top" else "ref_bottom"
    out.loc[last["date"]:, col] = last["price"]
    return out


def pivot_readings(risk: pd.Series, price: pd.Series, level: str = "major", window: int = 14) -> pd.DataFrame:
    """Risk reading on (and around) each historical turning point."""
    pv = cycle_pivots(price, level=level)
    rows = []
    for _, r in pv.iterrows():
        d = r["date"]
        w = risk.loc[d - pd.Timedelta(days=window): d + pd.Timedelta(days=window)].dropna()
        if risk.get(d) is None or np.isnan(risk.get(d, np.nan)):
            continue
        rows.append({
            "date": d.date(), "kind": r["kind"], "level": r["level"], "price": r["price"],
            "risk": risk[d],
            "best_in_window": (w.max() if r["kind"] == "top" else w.min()) if len(w) else np.nan,
        })
    return pd.DataFrame(rows)


def summary(risk: pd.Series, price: pd.Series, start: str = "2012-01-01",
            hi: float = 0.9, lo: float = 0.1) -> dict:
    ideal = ideal_risk(price)
    j = pd.concat([risk.rename("risk"), ideal], axis=1).loc[start:].dropna(subset=["risk", "ideal"])
    res: dict = {"n_days": len(j)}
    res["spearman"] = j["risk"].rank().corr(j["ideal"].rank())      # rank correlation without needing scipy
    res["pearson"] = j["risk"].corr(j["ideal"])
    res["mae"] = (j["risk"] - j["ideal"]).abs().mean()
    for era, (a, b) in ERAS.items():
        e = j.loc[a:b]
        res[f"pearson_{era}"] = e["risk"].corr(e["ideal"]) if len(e) > 200 else np.nan

    piv = pivot_readings(risk, price, level="cycle")
    piv = piv[pd.to_datetime(piv["date"]) >= pd.Timestamp(start)]
    res["top_mean"] = piv.loc[piv.kind == "top", "risk"].mean()
    res["top_min"] = piv.loc[piv.kind == "top", "risk"].min()
    res["bot_mean"] = piv.loc[piv.kind == "bottom", "risk"].mean()
    res["bot_max"] = piv.loc[piv.kind == "bottom", "risk"].max()

    ref = leg_reference(price, cycle_pivots(price, level="cycle"))
    k = pd.concat([risk.rename("risk"), price.rename("price"), ref], axis=1).loc[start:].dropna(subset=["risk"])
    hi_days = k[(k["risk"] >= hi) & k["ref_top"].notna()]
    lo_days = k[(k["risk"] <= lo) & k["ref_bottom"].notna()]
    res["hi_share"] = (k["risk"] >= hi).mean()
    res["lo_share"] = (k["risk"] <= lo).mean()
    # geometric mean of price relative to the leg's actual top / bottom
    res["sell_quality"] = float(np.exp(np.log(hi_days["price"] / hi_days["ref_top"]).mean())) if len(hi_days) else np.nan
    res["buy_quality"] = float(np.exp(np.log(lo_days["price"] / lo_days["ref_bottom"]).mean())) if len(lo_days) else np.nan
    return res


def forward_table(risk: pd.Series, price: pd.Series, horizon: int = 365,
                  bins: int = 10, start: str = "2012-01-01") -> pd.DataFrame:
    """Average forward return and worst forward drawdown by risk band."""
    logp = np.log(price)
    rev = logp[::-1]
    fmin = rev.rolling(horizon, min_periods=horizon).min()[::-1].shift(-1)
    fmax = rev.rolling(horizon, min_periods=horizon).max()[::-1].shift(-1)
    df = pd.DataFrame({
        "risk": risk,
        "fwd_ret": np.exp(logp.shift(-horizon) - logp) - 1,
        "fwd_dd": np.exp(np.minimum(fmin - logp, 0)) - 1,
        "fwd_up": np.exp(np.maximum(fmax - logp, 0)) - 1,
    }).loc[start:].dropna()
    edges = np.linspace(0, 1, bins + 1)
    df["band"] = pd.cut(df["risk"], edges, include_lowest=True)
    g = df.groupby("band", observed=False)
    return pd.DataFrame({
        "days": g.size(),
        "median_fwd_return": g["fwd_ret"].median(),
        "mean_fwd_return": g["fwd_ret"].mean(),
        "share_positive": g["fwd_ret"].apply(lambda s: (s > 0).mean()),
        "median_worst_drawdown": g["fwd_dd"].median(),
        "median_best_gain": g["fwd_up"].median(),
    })


def strategy(risk: pd.Series, price: pd.Series, start: str = "2012-01-01",
             kind: str = "linear", fee: float = 0.001) -> dict:
    """Very simple allocation test, with the rest of the money in cash.

    ``linear``: hold (1 - risk) of the portfolio in BTC.
    ``bands``:  all in below a reading of 0.3, all out above 0.7, a sliding share in between.

    The position for day t+1 uses the risk known at the close of day t, and every change of
    position costs ``fee`` (0.1%) of the amount traded.
    """
    r = np.log(price).diff().loc[start:]
    k = risk.reindex(r.index)
    if kind == "linear":
        w = (1 - k)
    elif kind == "bands":            # all-in below 0.3, all-out above 0.7, linear between
        w = ((0.7 - k) / 0.4).clip(0, 1)
    else:
        raise ValueError(kind)
    w = w.shift(1).fillna(0)
    simple = np.exp(r) - 1
    turnover = w.diff().abs().fillna(0)
    port = w * simple - turnover * fee
    eq = (1 + port.fillna(0)).cumprod()
    hodl = (1 + simple.fillna(0)).cumprod()
    years = (r.index[-1] - r.index[0]).days / 365.25

    def stats(e: pd.Series, daily: pd.Series) -> dict:
        dd = (e / e.cummax() - 1).min()
        return {
            "cagr": e.iloc[-1] ** (1 / years) - 1,
            "max_drawdown": dd,
            "sharpe": daily.mean() / daily.std() * np.sqrt(365) if daily.std() > 0 else np.nan,
            "final_multiple": e.iloc[-1],
        }

    return {"strategy": stats(eq, port.fillna(0)), "hodl": stats(hodl, simple.fillna(0)),
            "avg_exposure": float(w.mean())}


def extreme_timing(risk: pd.Series, price: pd.Series, n_days: int = 30,
                   start: str = "2012-01-01") -> pd.DataFrame:
    """Where was price on the n highest-risk days of each cycle (vs. the real top),
    and on the n lowest-risk days (vs. the real bottom)?

    This ignores how the scale is calibrated and asks only about timing: if you
    had acted on the metric's most extreme readings of each cycle, how close to
    the actual turn would you have been?
    """
    cols = ["pivot", "kind", "pivot_price", "price_vs_pivot", "median_days_from_pivot",
            "extreme_reading", "reading_on_pivot"]
    valid = risk.dropna()
    if valid.empty:
        return pd.DataFrame(columns=cols)
    pv = cycle_pivots(price, level="cycle")
    rows = []
    end = valid.index[-1]
    for i, r in pv.iterrows():
        if r["date"] < pd.Timestamp(start):
            continue
        prev_d = pv.loc[i - 1, "date"] if i > 0 else risk.dropna().index[0]
        next_d = pv.loc[i + 1, "date"] if i + 1 < len(pv) else end
        w = risk.loc[prev_d:next_d].dropna()
        if len(w) < n_days * 2:
            continue
        pick = w.nlargest(n_days) if r["kind"] == "top" else w.nsmallest(n_days)
        rel = price.reindex(pick.index) / r["price"]
        rows.append({
            "pivot": r["date"].date(), "kind": r["kind"], "pivot_price": r["price"],
            "price_vs_pivot": float(np.exp(np.log(rel).mean())),
            "median_days_from_pivot": int(np.median((pick.index - r["date"]).days)),
            "extreme_reading": float(pick.max() if r["kind"] == "top" else pick.min()),
            "reading_on_pivot": float(risk.get(r["date"], np.nan)),
        })
    return pd.DataFrame(rows, columns=cols)


def timing_summary(risk: pd.Series, price: pd.Series, n_days: int = 30) -> dict:
    t = extreme_timing(risk, price, n_days)
    tops, bots = t[t.kind == "top"], t[t.kind == "bottom"]
    return {
        "peak_timing": float(np.exp(np.log(tops["price_vs_pivot"]).mean())) if len(tops) else np.nan,
        "peak_worst": float(tops["price_vs_pivot"].min()) if len(tops) else np.nan,
        "trough_timing": float(np.exp(np.log(bots["price_vs_pivot"]).mean())) if len(bots) else np.nan,
        "trough_worst": float(bots["price_vs_pivot"].max()) if len(bots) else np.nan,
    }


def era_table(risk: pd.Series, price: pd.Series, eras: dict | None = None) -> pd.DataFrame:
    """How well the reading followed the hindsight cycle position, era by era."""
    ideal = ideal_risk(price)["ideal"]
    j = pd.concat([risk.rename("risk"), ideal], axis=1).dropna()
    rows = {}
    for era, (a, b) in (eras or ERAS).items():
        e = j.loc[a:b]
        if len(e) < 200:
            continue
        rows[era] = {"days": len(e), "correlation": e["risk"].corr(e["ideal"]),
                     "rank_correlation": e["risk"].rank().corr(e["ideal"].rank()),
                     "mean_abs_error": (e["risk"] - e["ideal"]).abs().mean()}
    return pd.DataFrame(rows).T


def best_possible_timing(price: pd.Series, n_days: int = 30) -> pd.DataFrame:
    """The ceiling for ``extreme_timing``: a perfect indicator would pick the n highest-priced
    days of each cycle for the top and the n lowest-priced days for the bottom."""
    return extreme_timing(np.log(price), price, n_days)[["pivot", "kind", "price_vs_pivot"]].rename(
        columns={"price_vs_pivot": "best_possible"})


def scorecard(risk: pd.Series, price: pd.Series, n_days: int = 30) -> dict:
    """The headline grades, on the three complete cycles since 2015."""
    out: dict = {}
    et = era_table(risk, price, FULL_CYCLES)
    out["tracking"] = float(et["correlation"].mean()) if len(et) else np.nan
    out["tracking_worst_cycle"] = float(et["correlation"].min()) if len(et) else np.nan
    out["mean_abs_error"] = float(et["mean_abs_error"].mean()) if len(et) else np.nan
    tops = pd.Series({d: risk.get(pd.Timestamp(d), np.nan) for d in CYCLE_TOPS})
    bots = pd.Series({d: risk.get(pd.Timestamp(d), np.nan) for d in CYCLE_BOTTOMS})
    out["top_reading_mean"], out["top_reading_lowest"] = float(tops.mean()), float(tops.min())
    out["bottom_reading_mean"], out["bottom_reading_highest"] = float(bots.mean()), float(bots.max())
    t = extreme_timing(risk, price, n_days)
    if len(t):
        t["pivot"] = t["pivot"].astype(str)
        tt, bb = t[t["pivot"].isin(CYCLE_TOPS)], t[t["pivot"].isin(CYCLE_BOTTOMS)]
        out["top_timing"] = float(np.exp(np.log(tt["price_vs_pivot"]).mean())) if len(tt) else np.nan
        out["top_timing_worst"] = float(tt["price_vs_pivot"].min()) if len(tt) else np.nan
        out["bottom_timing"] = float(np.exp(np.log(bb["price_vs_pivot"]).mean())) if len(bb) else np.nan
        out["bottom_timing_worst"] = float(bb["price_vs_pivot"].max()) if len(bb) else np.nan
    valid = risk.dropna()
    out["latest"] = float(valid.iloc[-1]) if len(valid) else np.nan
    return out


def cycle_test(risk: pd.Series, price: pd.Series, start: str, end: str, top: str, bottom: str,
               n_days: int = 30) -> dict:
    """Grades on one unseen stretch [start, end] containing one cycle top and one cycle bottom."""
    ideal = ideal_risk(price)["ideal"]
    j = pd.concat([risk.rename("risk"), ideal], axis=1).loc[start:end].dropna()
    t = extreme_timing(risk, price, n_days)
    t["pivot"] = t["pivot"].astype(str)
    tt, bb = t[t["pivot"] == top], t[t["pivot"] == bottom]
    return {
        "tracking": j["risk"].corr(j["ideal"]),
        "mean_abs_error": (j["risk"] - j["ideal"]).abs().mean(),
        "reading_at_top": risk.get(pd.Timestamp(top), np.nan),
        "top_timing": float(tt["price_vs_pivot"].iloc[0]) if len(tt) else np.nan,
        "reading_at_bottom": risk.get(pd.Timestamp(bottom), np.nan),
        "bottom_timing": float(bb["price_vs_pivot"].iloc[0]) if len(bb) else np.nan,
    }
