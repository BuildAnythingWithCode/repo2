"""Assemble one clean daily table from the raw downloads.

Everything downstream (indicators, model, backtest) reads only this table, so the
cleaning rules live in one place:

  * one row per calendar day (UTC), from the first day with a price (2010-07-18);
  * small gaps in a source are forward-filled for at most ``MAX_FFILL`` days, so a
    source that goes quiet shows up as missing instead of silently flat-lining;
  * derived basics that several indicators share (realized cap, miner revenue,
    daily log return) are computed here once.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .fetch import load_raw

MAX_FFILL = 7  # days


def _safe_load(source: str, name: str) -> pd.DataFrame | None:
    try:
        return load_raw(source, name)
    except FileNotFoundError:
        return None


def build_dataset(end: str | pd.Timestamp | None = None) -> pd.DataFrame:
    cm = load_raw("coinmetrics", "btc")
    cm = cm[[c for c in cm.columns if "-status" not in c]]

    first = cm["PriceUSD"].first_valid_index()
    last = cm["PriceUSD"].last_valid_index()
    idx = pd.date_range(first, last, freq="D", name="date")
    df = cm.reindex(idx)

    out = pd.DataFrame(index=idx)
    out["price"] = df["PriceUSD"].ffill(limit=MAX_FFILL)
    out["mcap"] = df["CapMrktCurUSD"].ffill(limit=MAX_FFILL)
    out["mvrv"] = df["CapMVRVCur"].ffill(limit=MAX_FFILL)
    out["supply"] = df["SplyCur"].ffill(limit=MAX_FFILL)
    out["rcap"] = out["mcap"] / out["mvrv"]                      # realized cap
    out["realized_price"] = out["rcap"] / out["supply"]
    out["iss_btc"] = df["IssTotNtv"]
    out["iss_usd"] = df["IssTotUSD"]
    out["fee_btc"] = df["FeeTotNtv"]
    out["fee_usd"] = out["fee_btc"] * out["price"]
    out["miner_rev_usd"] = out["iss_usd"] + out["fee_usd"]
    out["hashrate"] = df["HashRate"]
    out["blocks"] = df["BlkCnt"]
    out["adr_active"] = df["AdrActCnt"]
    out["adr_balance"] = df["AdrBalCnt"]
    out["tx_count"] = df["TxCnt"]
    out["tx_transfers"] = df["TxTfrCnt"]
    out["ex_in_btc"] = df["FlowInExNtv"]
    out["ex_out_btc"] = df["FlowOutExNtv"]
    out["ex_supply_btc"] = df["SplyExNtv"]
    out["spot_volume_usd"] = df["volume_reported_spot_usd_1d"]

    bc = _safe_load("blockchain", "charts")
    if bc is not None:
        bc = bc.reindex(idx)
        out["tx_volume_usd"] = bc["estimated-transaction-volume-usd"].ffill(limit=MAX_FFILL)
        out["tx_volume_btc"] = bc["estimated-transaction-volume"].ffill(limit=MAX_FFILL)
        out["bc_addresses"] = bc["n-unique-addresses"].ffill(limit=MAX_FFILL)
        out["utxo_count"] = bc["utxo-count"].ffill(limit=MAX_FFILL)
        out["difficulty"] = bc["difficulty"].ffill(limit=MAX_FFILL)

    fg = _safe_load("alternative", "fear_greed")
    if fg is not None:
        out["fng"] = fg["fng"].reindex(idx).ffill(limit=MAX_FFILL)

    st = _safe_load("defillama", "stablecoins")
    if st is not None:
        out["stable_usd"] = st["stable_usd"].reindex(idx).ffill(limit=MAX_FFILL)

    cb = _safe_load("coinbase", "btc_usd_daily")
    if cb is not None:
        cb = cb.reindex(idx)
        for c in ("cb_low", "cb_high", "cb_open", "cb_close", "cb_volume"):
            out[c] = cb[c]

    out["logp"] = np.log(out["price"])
    out["ret"] = out["logp"].diff()

    if end is not None:
        out = out.loc[: pd.Timestamp(end)]
    return out
