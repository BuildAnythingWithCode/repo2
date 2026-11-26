#!/usr/bin/env python3
"""Prove that no reading ever uses data from its own future.

For each of several past dates, throw away everything after that date, re-run the
model, and compare with the readings from the full history.  If the metric is
honest, every reading up to the cut-off date comes out the same either way: the
days after it cannot have mattered.

Run scripts/update_data.py first.

Usage:  python3 -I scripts/check_no_peeking.py
"""
from __future__ import annotations

import sys
import warnings
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
warnings.filterwarnings("ignore")

from btcrisk.dataset import build_dataset          # noqa: E402
from btcrisk.model import run_model                # noqa: E402

CUTS = ["2013-06-01", "2015-01-14", "2017-12-16", "2018-12-15", "2021-11-08", "2022-11-09", "2025-10-06",
        "2026-06-30"]
TOLERANCE = 1e-9          # readings are quoted to 2 or 3 decimals; rounding noise is around 1e-15


def main() -> int:
    df = build_dataset()
    full = run_model(df, all_indicators=False)
    worst = 0.0
    for day in CUTS:
        cut = run_model(df.loc[:day], all_indicators=False)
        diffs = []
        for name, a, b in (("reading", full.risk, cut.risk), ("halving clock", full.clock, cut.clock)):
            both = pd.concat([a.rename("full"), b.rename("cut")], axis=1).loc[:day]
            if not (both["full"].isna() == both["cut"].isna()).all():
                print(f"{day}: the {name} exists on different days in the two runs")
                return 1
            both = both.dropna()
            diffs.append(float((both["full"] - both["cut"]).abs().max()) if len(both) else 0.0)
        worst = max(worst, *diffs)
        print(f"{day}  reading that day {cut.risk.iloc[-1]:.3f}  largest difference on any earlier day {max(diffs):.1e}")
    if worst > TOLERANCE:
        print(f"FAILED  readings changed by up to {worst:.2e} when later data was removed")
        return 1
    print(f"OK  {len(CUTS)} cut-off dates, largest difference {worst:.1e}: no reading depends on later data")
    return 0


if __name__ == "__main__":
    sys.exit(main())
