"""Grade the risk metric against Bitcoin's whole history and stress-test the recipe.

Writes tables to out/backtest/ and one machine-readable summary (backtest.json):

  pivots.csv         the reading on every historical top and bottom
  timing.csv         price on the 30 highest / lowest readings of each cycle vs. the real turn
  eras.csv           how closely the reading followed the hindsight cycle position, era by era
  zones.csv          what happened to price over the following year, by risk zone
  crossings.csv      where price was when the reading first entered the extreme zones
  strategy.csv       two deliberately simple allocation rules against buy-and-hold
  blind_test.csv     the selection rule re-run with only the data available before each cycle
  robustness.csv     the scorecard when every design choice is nudged
  baselines.csv      the metric next to single famous indicators and the CBBI index
  indicators.csv     every indicator's skill, era by era

Usage:  python3 scripts/run_backtest.py
"""
from __future__ import annotations

import json
import sys
import warnings
from dataclasses import replace
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
warnings.filterwarnings("ignore")

from btcrisk import features as F                                   # noqa: E402
from btcrisk.config import OUT                                      # noqa: E402
from btcrisk.dataset import build_dataset                           # noqa: E402
from btcrisk.evaluate import (CYCLE_BOTTOMS, CYCLE_TOPS, ERAS, best_possible_timing, cycle_pivots,  # noqa: E402
                              cycle_test, era_table, extreme_timing, forward_table, pivot_readings,
                              scorecard, strategy)
from btcrisk.fetch import load_raw                                  # noqa: E402
from btcrisk.labels import ideal_risk                               # noqa: E402
from btcrisk.model import (CORE_LENSES, EXCLUDED, ModelConfig, combine, past_skill, ruler_positions,  # noqa: E402
                           run_model, select_by_rule)
from btcrisk.scoring import squash                                  # noqa: E402

DEST = OUT / "backtest"
SCORE_START = "2013-01-01"


def crossings(risk: pd.Series, price: pd.Series, hi: float = 0.8, lo: float = 0.2) -> pd.DataFrame:
    """For each cycle turn: where was price when the reading first entered the extreme zone,
    and what was the average price across all the days it spent there?"""
    pv = cycle_pivots(price, level="cycle")
    rows = []
    for i in range(1, len(pv)):
        prev, cur = pv.loc[i - 1], pv.loc[i]
        nxt = pv.loc[i + 1, "date"] if i + 1 < len(pv) else risk.dropna().index[-1]
        if str(cur["date"].date()) not in CYCLE_TOPS + CYCLE_BOTTOMS:
            continue
        # the approach to the turn, and the whole swing around it
        lead = risk.loc[prev["date"]: cur["date"]].dropna()
        around = risk.loc[prev["date"]: nxt].dropna()
        if cur["kind"] == "top":
            first = lead[lead >= hi].index.min()
            zone_days = around[around >= hi]
        else:
            first = lead[lead <= lo].index.min()
            zone_days = around[around <= lo]
        zp = price.reindex(zone_days.index)
        rows.append({
            "turn": cur["date"].date(), "kind": cur["kind"], "turn_price": cur["price"],
            "zone": f">= {hi}" if cur["kind"] == "top" else f"<= {lo}",
            "first_entry": first.date() if pd.notna(first) else None,
            "days_before_turn": int((cur["date"] - first).days) if pd.notna(first) else None,
            "price_at_first_entry_vs_turn": float(price[first] / cur["price"]) if pd.notna(first) else np.nan,
            "days_in_zone": int(len(zone_days)),
            "avg_price_in_zone_vs_turn": float(np.exp(np.log(zp / cur["price"]).mean())) if len(zp) else np.nan,
        })
    return pd.DataFrame(rows)


def fmt(d: dict) -> dict:
    return {k: (None if (isinstance(v, float) and not np.isfinite(v)) else (round(float(v), 4) if isinstance(v, (float, np.floating)) else v))
            for k, v in d.items()}


def main() -> None:
    DEST.mkdir(parents=True, exist_ok=True)
    df = build_dataset()
    price = df["price"]
    ideal = ideal_risk(price)["ideal"]
    cfg = ModelConfig()

    print("running the model on every indicator ...")
    res = run_model(df, cfg, all_indicators=True)
    risk = res.risk
    meta = F.meta()
    summary: dict = {"data_through": str(risk.dropna().index[-1].date()),
                     "first_score": str(risk.first_valid_index().date())}

    # ---- 1. the headline grades -------------------------------------------------
    card = scorecard(risk, price)
    best = best_possible_timing(price)
    best["pivot"] = best["pivot"].astype(str)
    bt = best[best["pivot"].isin(CYCLE_TOPS)]["best_possible"]
    bb = best[best["pivot"].isin(CYCLE_BOTTOMS)]["best_possible"]
    card["top_timing_best_possible"] = float(np.exp(np.log(bt).mean()))
    card["bottom_timing_best_possible"] = float(np.exp(np.log(bb).mean()))
    summary["scorecard"] = fmt(card)

    piv = pivot_readings(risk, price, level="major")
    piv.to_csv(DEST / "pivots.csv", index=False)

    timing = extreme_timing(risk, price).merge(best_possible_timing(price), on=["pivot", "kind"], how="left")
    timing.to_csv(DEST / "timing.csv", index=False)

    eras = era_table(risk, price)
    eras.to_csv(DEST / "eras.csv")

    zones = forward_table(risk, price, horizon=365, bins=5, start=SCORE_START)
    zones.index = ["0.0-0.2", "0.2-0.4", "0.4-0.6", "0.6-0.8", "0.8-1.0"]
    zones.to_csv(DEST / "zones.csv")

    cross = crossings(risk, price)
    cross.to_csv(DEST / "crossings.csv", index=False)

    rows = []
    for start in ("2013-07-01", "2015-01-01", "2018-01-01"):
        for kind in ("linear", "bands"):
            s = strategy(risk, price, start=start, kind=kind)
            rows.append({"start": start, "rule": kind, "avg_exposure": s["avg_exposure"],
                         **{f"rule_{k}": v for k, v in s["strategy"].items()},
                         **{f"hold_{k}": v for k, v in s["hodl"].items()}})
    pd.DataFrame(rows).to_csv(DEST / "strategy.csv", index=False)

    # ---- 2. every indicator, era by era ----------------------------------------
    cyc = {"2013-17": ("2013-12-05", "2017-12-16"), "2018-21": ("2017-12-17", "2021-11-08"),
           "2022-25": ("2021-11-09", "2025-10-06")}
    ind = pd.DataFrame({name: past_skill(res.score, ideal, a, b, min_days=300) for name, (a, b) in cyc.items()})
    ind["all_history"] = past_skill(res.score, ideal, "2012-01-01", "2025-10-06")
    ind["first_score"] = [str(res.score[c].first_valid_index().date()) if res.score[c].notna().any() else "" for c in ind.index]
    ind["family"] = meta["family"].reindex(ind.index)
    ind["label"] = meta["label"].reindex(ind.index)
    core = {m for members in CORE_LENSES.values() for m in members}
    ind["status"] = ["core" if c in core else ("excluded" if c in EXCLUDED else "context") for c in ind.index]
    ind = ind.sort_values("all_history", ascending=False)
    ind.to_csv(DEST / "indicators.csv")

    # ---- 3. the selection rule, run blind --------------------------------------
    print("blind test of the selection rule ...")
    folds = [
        ("2017-12-16", "2017-12-17", "2021-11-08", "2021-11-08", "2018-12-15"),
        ("2021-11-08", "2021-11-09", "2025-10-06", "2025-10-06", "2022-11-09"),
    ]
    rows, picks = [], {}
    for known_to, a, b, top, bot in folds:
        skill = past_skill(res.score, ideal, "2012-01-01", known_to)
        for thr in (0.70, 0.75, 0.80):
            lenses = select_by_rule(skill, thr)
            comp, _ = combine(res.position, lenses, cfg.min_lenses)
            r = squash(comp, cfg.edge)
            n = sum(len(v) for v in lenses.values())
            rows.append({"designed_with_data_to": known_to, "tested_on": f"{a} to {b}",
                         "recipe": f"rule, bar {thr:.2f} ({n} indicators)", **cycle_test(r, price, a, b, top, bot)})
            if thr == 0.75:
                picks[known_to] = {k: list(v) for k, v in lenses.items()}
        pool = [c for c in res.position.columns if c not in EXCLUDED]
        fam = meta["family"]
        every = {f: tuple(c for c in pool if fam[c] == f) for f in sorted(set(fam[pool]))}
        comp, _ = combine(res.position, every, cfg.min_lenses)
        rows.append({"designed_with_data_to": known_to, "tested_on": f"{a} to {b}",
                     "recipe": f"no selection: all {len(pool)} indicators", **cycle_test(squash(comp, cfg.edge), price, a, b, top, bot)})
        bestname = skill.drop(labels=[c for c in EXCLUDED if c in skill.index]).index[0]
        rows.append({"designed_with_data_to": known_to, "tested_on": f"{a} to {b}",
                     "recipe": f"best single indicator so far ({bestname})", **cycle_test(res.score[bestname], price, a, b, top, bot)})
        rows.append({"designed_with_data_to": "2025-10-06 (final recipe)", "tested_on": f"{a} to {b}",
                     "recipe": "final recipe (chosen knowing this cycle)", **cycle_test(risk, price, a, b, top, bot)})
    blind = pd.DataFrame(rows)
    blind.to_csv(DEST / "blind_test.csv", index=False)
    skill_now = past_skill(res.score, ideal, "2012-01-01", "2025-10-06")
    picks["2025-10-06"] = {k: list(v) for k, v in select_by_rule(skill_now, 0.75).items()}
    summary["rule_picks"] = picks
    same = {k: sorted(v) for k, v in picks["2025-10-06"].items()} == {k: sorted(v) for k, v in CORE_LENSES.items()}
    summary["rule_reproduces_core"] = bool(same)

    # ---- 4. nudge every design choice ------------------------------------------
    print("robustness sweeps ...")
    variants: dict[str, ModelConfig] = {"final recipe": cfg}
    for q in (0.01, 0.05, 0.10):
        variants[f"ruler ends at {q:.0%} / {1 - q:.0%}"] = replace(cfg, lo_q=q, hi_q=1 - q)
    for hl in (4, 6, 12, None):
        variants["history fades: " + (f"half-life {hl}y" if hl else "never")] = replace(cfg, halflife_days=None if hl is None else hl * 365)
    for lag in (0, 180, 730):
        variants[f"ruler delay {lag} days"] = replace(cfg, lag_days=lag)
    for vw in (2, 3, 6):
        variants[f"volatility window {vw}y"] = replace(cfg, vol_window=vw * 365 + 1)
    for name, members in CORE_LENSES.items():
        variants[f"without the {name} lens"] = replace(cfg, lenses={k: v for k, v in CORE_LENSES.items() if k != name})
        if len(members) > 1:
            for m in members:
                variants[f"without {m}"] = replace(cfg, lenses={k: tuple(x for x in v if x != m) for k, v in CORE_LENSES.items()})
    variants["flat average (no lenses)"] = replace(cfg, lenses={m: (m,) for v in CORE_LENSES.values() for m in v}, min_lenses=4)
    variants["with Thermocap multiple added"] = replace(cfg, lenses={**CORE_LENSES, "onchain": ("mvrv", "thermo")})
    rows = {}
    for name, c in variants.items():
        r = risk if name == "final recipe" else run_model(df, c, all_indicators=False).risk
        rows[name] = scorecard(r, price)
    robust = pd.DataFrame(rows).T
    robust.to_csv(DEST / "robustness.csv")
    summary["robustness_range"] = {k: [round(float(robust[k].min()), 3), round(float(robust[k].max()), 3)]
                                   for k in ("tracking", "top_reading_mean", "bottom_reading_mean", "top_timing", "bottom_timing", "latest")}

    # ---- 5. baselines -----------------------------------------------------------
    rows = {"Bitcoin Risk Metric": scorecard(risk, price)}
    for name in ("mvrv", "mayer", "ma4y", "powerlaw", "puell", "rsi_14m", "fng"):
        rows[f"{meta.loc[name, 'label']} alone"] = scorecard(res.score[name], price)
    pool = [c for c in res.position.columns if c not in EXCLUDED]
    rows[f"Plain average of all {len(pool)} indicators"] = scorecard(squash(res.position[pool].mean(axis=1).where(res.position[pool].notna().sum(axis=1) >= 4), cfg.edge), price)
    rows["Halving clock alone (calendar only)"] = scorecard(res.clock, price)
    try:
        cbbi = load_raw("cbbi", "cbbi")
        # "Confidence" is the CBBI index itself; the other columns are its nine ingredients
        rows["CBBI (public index, tuned with hindsight)"] = scorecard(cbbi["cbbi_Confidence"].reindex(price.index), price)
    except Exception as exc:                                         # benchmark only; never fatal
        print("CBBI benchmark skipped:", exc)
    base = pd.DataFrame(rows).T
    base.to_csv(DEST / "baselines.csv")

    (DEST / "backtest.json").write_text(json.dumps(summary, indent=2, default=str))

    pd.set_option("display.width", 250, "display.max_columns", 40, "display.max_rows", 200)
    print("\n== scorecard ==");  print(json.dumps(summary["scorecard"], indent=1))
    print("\n== readings on turning points ==");  print(piv.round(3).to_string(index=False))
    print("\n== timing ==");  print(timing.round(3).to_string(index=False))
    print("\n== eras ==");  print(eras.round(3).to_string())
    print("\n== next-12-month outcomes by zone ==");  print(zones.round(3).to_string())
    print("\n== zone crossings ==");  print(cross.round(3).to_string(index=False))
    print("\n== blind test ==");  print(blind.round(3).to_string(index=False))
    print("\nrule picks:", json.dumps(picks, indent=1), "\nreproduces core:", same)
    print("\n== robustness ==");  print(robust.round(3).to_string())
    print("\n== baselines ==");  print(base.round(3).to_string())
    print("\n== indicators ==");  print(ind.round(2).to_string())


if __name__ == "__main__":
    main()
