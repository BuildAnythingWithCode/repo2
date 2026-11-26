"""Paths and fixed facts (dates of halvings, known cycle turning points)."""
from __future__ import annotations

from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data"
RAW = DATA / "raw"
PROCESSED = DATA / "processed"
OUT = ROOT / "out"

# A generic client name. Deliberately carries no personal details.
USER_AGENT = "btc-risk-metric/0.1 (open-source research script)"

GENESIS = pd.Timestamp("2009-01-03")

# Block-reward halvings (UTC dates of the halving blocks).
HALVINGS = [
    pd.Timestamp("2012-11-28"),
    pd.Timestamp("2016-07-09"),
    pd.Timestamp("2020-05-11"),
    pd.Timestamp("2024-04-20"),
]
# Next halving is expected around April 2028 (block 1,050,000).
NEXT_HALVING_EST = pd.Timestamp("2028-04-15")
