"""Write the small data files the dashboard reads (out/dashboard/*.json).

Each file is {"rows": [...], "meta": [...]}; ``meta`` carries this script's own
text so a reader of the dashboard can see how every number was made.

  history.json     one row per day: price, the risk reading, the three lenses, the halving clock
  today.json       one row: the latest reading and what surrounds it
  indicators.json  one row per indicator: today's reading, its family, how well it tracked past cycles
  turns.json       the reading on every historical top and bottom
  zones.json       what price did over the following 12 months, by risk zone
  blind.json       the selection rule re-run with only the data available before each cycle
  early.json       where price was when the reading first entered the extreme zones
  grades.json      the headline grades of the backtest
  baselines.json   the same grades for well-known single indicators and a public index
  strategy.json    what a simple "hold less when risk is high" rule would have done

Run scripts/update_data.py and scripts/run_backtest.py first.

Usage:  python3 scripts/export_dashboard.py
"""
from __future__ import annotations

import json
import sys
import warnings
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
warnings.filterwarnings("ignore")

from btcrisk import features as F                                   # noqa: E402
from btcrisk.config import HALVINGS, NEXT_HALVING_EST, OUT          # noqa: E402
from btcrisk.dataset import build_dataset                           # noqa: E402
from btcrisk.evaluate import cycle_pivots, pivot_readings           # noqa: E402
from btcrisk.model import CORE_LENSES, EXCLUDED, LENS_LABELS, run_model, zone  # noqa: E402

DEST = OUT / "dashboard"
BACKTEST = OUT / "backtest"
SOURCES = ("Coin Metrics community API (price, market cap, MVRV, supply, issuance), Blockchain.com charts, "
           "Coinbase Exchange candles, alternative.me Fear & Greed, DefiLlama stablecoins. All free and public.")
REPO = "github.com/BuildAnythingWithCode/repo2 (branch bitcoin-risk-metric)"


def natural(name: str, x: float) -> str:
    """An indicator's raw value in the units people usually quote it in."""
    if x is None or not np.isfinite(x):
        return ""
    e = float(np.exp(x))
    if name in ("mayer", "ma350", "ma2y", "ma4y"):
        return f"{e:.2f}x its average"
    if name == "powerlaw":
        return f"{(e - 1) * 100:+.0f}% vs. trend"
    if name == "dd_ath":
        return f"{(e - 1) * 100:.0f}% from record high"
    if name == "runup_low":
        return f"{e:.2f}x the 4-year low"
    if name in ("range_2y", "range_4y"):
        return f"{x * 100:.0f}% of the way up"
    if name.startswith("mom_"):
        n = int(name.split("_")[1])
        return f"{(np.exp(x * np.sqrt(n / 365)) - 1) * 100:+.0f}% over {n} days"
    if name in ("rsi_14w", "rsi_14m"):
        return f"{x * 100:.0f} out of 100"
    if name in ("mvrv", "puell"):
        return f"{e:.2f}"
    if name == "top_price":
        return f"{e * 100:.0f}% of Top price"
    if name == "thermo":
        return f"{e:.1f}x miner income to date"
    if name in ("fng", "fng_fast"):
        return f"{x * 100:.0f} out of 100"
    if name == "sharpe_1y":
        return f"{x:.2f}"
    return ""


def clean(v):
    if isinstance(v, (np.floating, float)):
        return None if not np.isfinite(v) else float(v)
    if isinstance(v, (np.integer,)):
        return int(v)
    if isinstance(v, (pd.Timestamp, datetime)):
        return v.strftime("%Y-%m-%d")
    return v


def rows_of(frame: pd.DataFrame) -> list[dict]:
    return [{k: clean(v) for k, v in r.items()} for r in frame.to_dict(orient="records")]


def write(name: str, rows: list[dict], made_from: str) -> None:
    meta = [
        {"label": "export_dashboard.py", "value": Path(__file__).read_text(), "type": "code", "lang": "python"},
        {"label": "Made from", "value": made_from},
        {"label": "Model code", "value": f"src/btcrisk/model.py in {REPO}"},
        {"label": "Raw inputs", "value": SOURCES},
    ]
    (DEST / f"{name}.json").write_text(json.dumps({"rows": rows, "meta": meta}, separators=(",", ":")))
    print(f"  {name}.json  {len(rows)} rows")


def main() -> None:
    DEST.mkdir(parents=True, exist_ok=True)
    df = build_dataset()
    price = df["price"]
    res = run_model(df, all_indicators=True)
    risk = res.risk
    last = risk.dropna().index[-1]
    meta = F.meta()

    # ---- history ---------------------------------------------------------------
    hist = pd.DataFrame({
        "date": df.index.strftime("%Y-%m-%d"),
        "price": price.round(2).values,
        "risk": risk.round(4).values,
        "trend": res.lens_score["trend"].round(4).values,
        "onchain": res.lens_score["onchain"].round(4).values,
        "range": res.lens_score["range"].round(4).values,
        "clock": res.clock.round(4).values,
    })
    hist = hist[hist["price"].notna()]
    write("history", rows_of(hist), "run_model() in src/btcrisk/model.py over the full daily table; one row per day.")

    # ---- today -----------------------------------------------------------------
    def back(days: int) -> float:
        return float(risk.get(last - pd.Timedelta(days=days), np.nan))

    ath_date = price.loc[:last].idxmax()
    piv = cycle_pivots(price, level="cycle")
    last_top = piv[piv["kind"] == "top"].iloc[-1]
    halving = max(h for h in HALVINGS if h <= last)
    sched = res.clock_schedule.iloc[-1]
    since_low = price.loc[last_top["date"]:last]
    r_now = float(risk[last])
    zone_idx = pd.cut(risk.dropna(), [-np.inf, 0.2, 0.4, 0.6, 0.8, np.inf], labels=False, right=False)
    same = (zone_idx != zone_idx.iloc[-1])[::-1]
    days_in_zone = int(same.values.argmax()) if same.any() else len(zone_idx)
    avg_4y = float(price.rolling(4 * 365, min_periods=1).mean()[last])
    n_core = sum(len(v) for v in CORE_LENSES.values())
    today = {
        "date": last, "price": float(price[last]), "risk": r_now, "zone": zone(r_now),
        "zone_index": int(zone_idx.iloc[-1]), "days_in_zone": days_in_zone,
        "zone_since": zone_idx.index[-days_in_zone],
        "risk_1d_ago": back(1), "risk_7d_ago": back(7), "risk_30d_ago": back(30), "risk_90d_ago": back(90),
        "risk_365d_ago": back(365),
        "risk_change_7d": r_now - back(7), "risk_change_30d": r_now - back(30), "risk_change_90d": r_now - back(90),
        "price_30d_ago": float(price.get(last - pd.Timedelta(days=30), np.nan)),
        "price_change_30d": float(price[last] / price.get(last - pd.Timedelta(days=30), np.nan) - 1),
        "trend": float(res.lens_score["trend"][last]), "onchain": float(res.lens_score["onchain"][last]),
        "range": float(res.lens_score["range"][last]),
        "trend_30d_ago": float(res.lens_score["trend"].get(last - pd.Timedelta(days=30), np.nan)),
        "onchain_30d_ago": float(res.lens_score["onchain"].get(last - pd.Timedelta(days=30), np.nan)),
        "range_30d_ago": float(res.lens_score["range"].get(last - pd.Timedelta(days=30), np.nan)),
        "clock": float(res.clock[last]),
        "days_since_halving": int((last - halving).days), "last_halving": halving,
        "clock_expected_top": sched["expected_top"], "clock_expected_bottom": sched["expected_bottom"],
        "clock_next_expected_top": NEXT_HALVING_EST + pd.Timedelta(days=int(sched["top_offset"])),
        "record_high": float(price[ath_date]), "record_high_date": ath_date,
        "from_record_high": float(price[last] / price[ath_date] - 1),
        "days_since_record_high": int((last - ath_date).days),
        "low_since_record_high": float(since_low.min()), "low_since_record_high_date": since_low.idxmin(),
        "risk_at_record_high": float(risk.get(ath_date, np.nan)),
        "mvrv": float(df["mvrv"][last]), "realized_price": float(df["realized_price"][last]),
        "price_vs_realized": float(price[last] / df["realized_price"][last] - 1),
        "avg_4y": avg_4y, "price_vs_avg_4y": float(price[last] / avg_4y - 1),
        "indicators_tested": int(len(res.score.columns)), "indicators_in_score": n_core,
        "volatility_4y": float(F.long_vol(df)[last]),
        "first_score": risk.first_valid_index(),
        "built_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
    }
    write("today", [{k: clean(v) for k, v in today.items()}], "The last row of the model run, plus a few facts about price.")

    # ---- indicators --------------------------------------------------------------
    skill = pd.read_csv(BACKTEST / "indicators.csv", index_col=0) if (BACKTEST / "indicators.csv").exists() else pd.DataFrame()
    lens_of = {m: lens for lens, members in CORE_LENSES.items() for m in members}
    rows = []
    for name in res.score.columns:
        s = res.score[name]
        m = meta.loc[name]
        status = "core" if name in lens_of else ("excluded" if name in EXCLUDED else "context")
        sk = skill.loc[name] if name in skill.index else {}
        rows.append({
            "id": name, "label": "Share of halving cycle elapsed" if name == "halving_clock" else m["label"],
            "what": m["desc"], "family": m["family"],
            "family_label": LENS_LABELS.get(m["family"], m["family"].title()),
            "lens": lens_of.get(name, ""), "status": status,
            "role": {"core": "In the score", "context": "Watched, not in the score",
                     "excluded": "Left out on purpose"}[status],
            "why_excluded": EXCLUDED.get(name, ""),
            "score": clean(s.get(last, np.nan)), "score_30d_ago": clean(s.get(last - pd.Timedelta(days=30), np.nan)),
            "value": natural(name, res.raw[name].get(last, np.nan)).replace("-", "\u2212"),
            "skill": clean(sk.get("all_history", np.nan)) if len(sk) else None,
            "skill_2013_17": clean(sk.get("2013-17", np.nan)) if len(sk) else None,
            "skill_2018_21": clean(sk.get("2018-21", np.nan)) if len(sk) else None,
            "skill_2022_25": clean(sk.get("2022-25", np.nan)) if len(sk) else None,
            "scored_since": str(s.first_valid_index().date()) if s.notna().any() else None,
        })
    order = {"core": 0, "context": 1, "excluded": 2}
    rows.sort(key=lambda r: (order[r["status"]], -(r["skill"] if r["skill"] is not None else -9)))
    write("indicators", rows, "Every indicator's reading on the latest day; skill columns come from scripts/run_backtest.py.")

    # ---- turning points ---------------------------------------------------------
    t = pivot_readings(risk, price, level="major")
    t["date"] = pd.to_datetime(t["date"])
    t = t[t["date"] >= pd.Timestamp("2013-07-01")]
    t["name"] = [f"{d.strftime('%b %Y')} {'top' if k == 'top' else 'bottom'}" for d, k in zip(t["date"], t["kind"])]
    t["size"] = t["level"].map({"cycle": "Cycle turn", "major": "Mid-cycle turn"})
    # the Oct 2025 high is the cycle's record; it only counts as "major" until price has fallen 70% from it
    t.loc[t["date"] == last_top["date"], "size"] = "Cycle turn"
    t = t[["date", "name", "kind", "size", "price", "risk"]]
    write("turns", rows_of(t), "Turning points found by a zig-zag rule on price (a 70% fall or 233% rise marks a cycle turn, "
          "50% / 100% a mid-cycle turn); the reading is the model's value on that day.")

    # ---- backtest tables --------------------------------------------------------
    z = pd.read_csv(BACKTEST / "zones.csv", index_col=0).reset_index().rename(columns={"index": "zone"})
    z["zone_name"] = ["Very low", "Low", "Neutral", "High", "Very high"]
    write("zones", rows_of(z), "scripts/run_backtest.py: every scored day since 2013 grouped by its reading, "
          "then what price did over the following 365 days.")

    b = pd.read_csv(BACKTEST / "blind_test.csv")
    cyc = b["tested_on"].str[:4].map({"2017": "2018-21", "2021": "2022-25"})
    slug = b["recipe"].map(lambda r: "final" if r.startswith("final") else "all" if r.startswith("no selection")
                           else "best1" if r.startswith("best single") else "rule" + r.split("bar 0.")[1][:2])
    b["id"] = slug + "_" + cyc
    b["cycle"] = cyc
    b["row_kind"] = slug.map({"rule75": "Blind: chosen by the rule", "final": "Not blind: the final recipe",
                              "all": "Blind: every indicator, no choosing"}).fillna("Variant")
    write("blind", rows_of(b), "scripts/run_backtest.py: indicators chosen with data up to one cycle top only, "
          "then graded on the cycle that followed.")

    e = pd.read_csv(BACKTEST / "crossings.csv")
    e["turn"] = pd.to_datetime(e["turn"])
    e["name"] = [f"{d.strftime('%b %Y')} {k}" for d, k in zip(e["turn"], e["kind"])]
    e["first_entry_gap"] = e["price_at_first_entry_vs_turn"] - 1      # price then, against the turn's price
    e["avg_gap_in_zone"] = e["avg_price_in_zone_vs_turn"] - 1
    write("early", rows_of(e), "scripts/run_backtest.py: for each cycle turn, where price was when the reading first "
          "crossed 0.8 (tops) or 0.2 (bottoms), and the average price over all days spent beyond it.")

    g = json.loads((BACKTEST / "backtest.json").read_text())
    grades = {**g["scorecard"], "data_through": g["data_through"], "first_score": g["first_score"],
              "rule_reproduces_core": g["rule_reproduces_core"]}
    for k, (lo, hi) in g["robustness_range"].items():
        grades[f"range_{k}_min"], grades[f"range_{k}_max"] = lo, hi
    write("grades", [grades], "scripts/run_backtest.py: grades on the three complete cycles since 2015, and how far "
          "they move when every design choice is nudged.")

    bl = pd.read_csv(BACKTEST / "baselines.csv").rename(columns={"Unnamed: 0": "name"})
    bl["id"] = ["metric" if n == "Bitcoin Risk Metric" else "cbbi" if n.startswith("CBBI") else "clock" if n.startswith("Halving")
                else "average" if n.startswith("Plain") else next(k for k in meta.index if n == f"{meta.loc[k, 'label']} alone")
                for n in bl["name"]]
    bl["kind"] = ["This metric" if n == "Bitcoin Risk Metric" else "Public index" if n.startswith("CBBI")
                  else "Calendar" if n.startswith("Halving") else "Average" if n.startswith("Plain")
                  else "Single indicator" for n in bl["name"]]
    write("baselines", rows_of(bl), "scripts/run_backtest.py: the same grades for single well-known indicators (each on the "
          "same causal 0 to 1 ruler), a plain average of everything, the halving calendar, and CBBI, a public "
          "index that is calibrated with hindsight.")

    st = pd.read_csv(BACKTEST / "strategy.csv")
    st["id"] = st["rule"] + "_" + st["start"].str[:4]
    st["rule_name"] = st["rule"].map({"linear": "Hold (1 - reading) of the money in bitcoin, rebalanced daily",
                                      "bands": "All in below 0.2, all out above 0.8, hold in between"})
    write("strategy", rows_of(st), "scripts/run_backtest.py: two mechanical rules that follow the reading, against simply "
          "holding bitcoin. No fees, no taxes, cash earns nothing.")

    print("latest:", last.date(), "risk", round(r_now, 3), zone(r_now))


if __name__ == "__main__":
    main()
