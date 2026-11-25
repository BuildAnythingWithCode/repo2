"""Candidate indicators.

Every function takes the clean daily table and returns one raw series, oriented
so that HIGHER MEANS MORE OVERHEATED (closer to a top).  All of them are causal:
the value for day t uses data up to and including day t only.

Each indicator declares how it should be put on a common scale (``norm``):

  "vol"   The raw value is a distance in log-price space (price vs. some slower
          anchor).  Bitcoin's swings have shrunk steadily as it matured, so a
          distance that marked a top in 2013 is unreachable today.  Dividing by
          long-run volatility measures every distance in "how big is this for
          the Bitcoin of that day", which makes old and new cycles comparable
          without fitting any decay curve.
  "level" Already comparable through time (bounded oscillators, ratios of an
          activity series to its own average, or a ratio to an all-history
          anchor that does not sit around zero); used as is.
  "drift" Has a slow structural drift unrelated to the cycle (for example NVT,
          as more activity moves off-chain); measured against its own trailing
          two-year median first.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

import numpy as np
import pandas as pd

from .config import GENESIS, HALVINGS

YEAR = 365
VOL_WINDOW = 4 * YEAR + 1      # one full halving cycle
VOL_MIN = 180


# ----------------------------------------------------------------------------
# helpers
# ----------------------------------------------------------------------------
def long_vol(df: pd.DataFrame, window: int = VOL_WINDOW, min_periods: int = VOL_MIN) -> pd.Series:
    """Annualised volatility of daily log returns over a full cycle (causal)."""
    return df["ret"].rolling(window, min_periods=min_periods).std() * np.sqrt(YEAR)


def sma(s: pd.Series, n: int, min_frac: float = 1.0) -> pd.Series:
    return s.rolling(n, min_periods=max(1, int(n * min_frac))).mean()


def log_ratio(a: pd.Series, b: pd.Series) -> pd.Series:
    with np.errstate(divide="ignore", invalid="ignore"):
        out = np.log(a / b)
    return out.replace([np.inf, -np.inf], np.nan)


def rsi(price: pd.Series, n: int) -> pd.Series:
    """Wilder RSI on daily closes with period n days, scaled to 0..1."""
    d = np.log(price).diff()
    up = d.clip(lower=0).ewm(alpha=1 / n, min_periods=n, adjust=False).mean()
    dn = (-d.clip(upper=0)).ewm(alpha=1 / n, min_periods=n, adjust=False).mean()
    return up / (up + dn)


def expanding_powerlaw_residual(df: pd.DataFrame, min_days: int = 2 * YEAR) -> pd.Series:
    """log price minus an expanding-window power-law fit, log P = a + b log(days since genesis).

    Refit every day on data up to that day only (closed-form OLS via running sums).
    """
    y = df["logp"].values
    x = np.log((df.index - GENESIS).days.values.astype(float))
    n = np.arange(1, len(y) + 1, dtype=float)
    sx, sy = np.cumsum(x), np.cumsum(y)
    sxx, sxy = np.cumsum(x * x), np.cumsum(x * y)
    denom = n * sxx - sx**2
    with np.errstate(divide="ignore", invalid="ignore"):
        b = (n * sxy - sx * sy) / denom
        a = (sy - b * sx) / n
    resid = y - (a + b * x)
    resid[: min_days] = np.nan
    return pd.Series(resid, index=df.index)


def days_since_last(dates: list[pd.Timestamp], index: pd.DatetimeIndex) -> pd.Series:
    out = pd.Series(np.nan, index=index)
    for d in dates:
        mask = index >= d
        out[mask] = (index[mask] - d).days
    return out


# ----------------------------------------------------------------------------
# registry
# ----------------------------------------------------------------------------
@dataclass
class Feature:
    name: str
    family: str
    norm: str                    # "vol" | "level" | "drift"
    fn: Callable[[pd.DataFrame], pd.Series]
    label: str
    desc: str
    side: str = "both"           # "both", "top" (informative near highs only) or "bottom"


REGISTRY: list[Feature] = []


def feature(name: str, family: str, norm: str, label: str, desc: str, side: str = "both"):
    def deco(fn):
        REGISTRY.append(Feature(name, family, norm, fn, label, desc, side))
        return fn
    return deco


# ---- families: trend (price against slow anchors) and range (price inside its own range) ----
@feature("mayer", "trend", "vol", "Mayer Multiple",
         "Price against its 200-day average.")
def f_mayer(df):
    return log_ratio(df["price"], sma(df["price"], 200))


@feature("ma350", "trend", "vol", "Price / 350-day average",
         "Price against its 350-day average (the base of the Golden Ratio Multiplier).")
def f_ma350(df):
    return log_ratio(df["price"], sma(df["price"], 350))


@feature("ma2y", "trend", "vol", "2-Year MA Multiplier",
         "Price against its 2-year average.")
def f_ma2y(df):
    return log_ratio(df["price"], sma(df["price"], 2 * YEAR))


@feature("ma4y", "trend", "vol", "Price / 4-year average",
         "Price against its 4-year average (close cousin of the 200-week moving average).")
def f_ma4y(df):
    return log_ratio(df["price"], sma(df["price"], 4 * YEAR, min_frac=0.6))


@feature("pi_cycle", "trend", "vol", "Pi Cycle ratio",
         "111-day average against twice the 350-day average; the two cross at blow-off tops.")
def f_pi(df):
    return log_ratio(sma(df["price"], 111), 2 * sma(df["price"], 350))


@feature("powerlaw", "trend", "vol", "Power-law trend deviation",
         "Price against a long-run power-law growth curve refitted every day on past data only.")
def f_powerlaw(df):
    return expanding_powerlaw_residual(df)


@feature("dd_ath", "range", "vol", "Drawdown from all-time high",
         "How far price sits below its record high.", side="bottom")
def f_dd(df):
    return df["logp"] - df["logp"].cummax()


@feature("runup_low", "range", "vol", "Run-up from 4-year low",
         "How far price sits above its lowest close of the past four years.", side="top")
def f_runup(df):
    return df["logp"] - df["logp"].rolling(4 * YEAR, min_periods=YEAR).min()


@feature("range_4y", "range", "level", "Position in 4-year range",
         "Where price sits between its 4-year low and 4-year high (log scale).")
def f_range4(df):
    lo = df["logp"].rolling(4 * YEAR, min_periods=YEAR).min()
    hi = df["logp"].rolling(4 * YEAR, min_periods=YEAR).max()
    return (df["logp"] - lo) / (hi - lo)


@feature("range_2y", "range", "level", "Position in 2-year range",
         "Where price sits between its 2-year low and 2-year high (log scale).")
def f_range2(df):
    lo = df["logp"].rolling(2 * YEAR, min_periods=YEAR).min()
    hi = df["logp"].rolling(2 * YEAR, min_periods=YEAR).max()
    return (df["logp"] - lo) / (hi - lo)


# ---- family: momentum -------------------------------------------------------
def _mom(df, n):
    return (df["logp"] - df["logp"].shift(n)) / np.sqrt(n / YEAR)


@feature("mom_90", "momentum", "vol", "90-day momentum", "Price change over 90 days.")
def f_mom90(df):
    return _mom(df, 90)


@feature("mom_180", "momentum", "vol", "180-day momentum", "Price change over 180 days.")
def f_mom180(df):
    return _mom(df, 180)


@feature("mom_365", "momentum", "vol", "1-year momentum", "Price change over one year.")
def f_mom365(df):
    return _mom(df, 365)


@feature("mom_730", "momentum", "vol", "2-year momentum", "Price change over two years.")
def f_mom730(df):
    return _mom(df, 730)


@feature("rsi_14w", "momentum", "level", "Weekly RSI",
         "Relative Strength Index over roughly 14 weeks.")
def f_rsi_w(df):
    return rsi(df["price"], 98)


@feature("rsi_14m", "momentum", "level", "Monthly RSI",
         "Relative Strength Index over roughly 14 months.")
def f_rsi_m(df):
    return rsi(df["price"], 426)


@feature("sharpe_1y", "momentum", "level", "1-year Sharpe ratio",
         "Return per unit of volatility over the past year.")
def f_sharpe(df):
    r = df["ret"]
    return r.rolling(YEAR).mean() / r.rolling(YEAR).std() * np.sqrt(YEAR)


@feature("macd_w", "momentum", "vol", "Weekly MACD",
         "Gap between the 12-week and 26-week exponential averages of price.")
def f_macd(df):
    fast = df["logp"].ewm(span=84, min_periods=84, adjust=False).mean()
    slow = df["logp"].ewm(span=182, min_periods=182, adjust=False).mean()
    return fast - slow


@feature("bb_20w", "momentum", "level", "20-week Bollinger position",
         "Price against its 20-week average, in units of its own 20-week volatility.")
def f_bb(df):
    m = df["logp"].rolling(140).mean()
    s = df["logp"].rolling(140).std()
    return (df["logp"] - m) / s


# ---- family: on-chain valuation --------------------------------------------
@feature("mvrv", "onchain", "vol", "MVRV",
         "Market value against realized value: price versus the average price coins last moved at.")
def f_mvrv(df):
    return np.log(df["mvrv"])


@feature("mvrv_mom", "onchain", "vol", "MVRV momentum",
         "MVRV against its own 1-year average.")
def f_mvrv_mom(df):
    return log_ratio(df["mvrv"], sma(df["mvrv"], YEAR))


@feature("rcap_growth", "onchain", "vol", "Realized cap growth (90d)",
         "How fast new money is being locked in at higher prices over 90 days.")
def f_rcap_growth(df):
    return log_ratio(df["rcap"], df["rcap"].shift(90))


@feature("rcap_growth_1y", "onchain", "vol", "Realized cap growth (1y)",
         "Growth of realized cap over a year.")
def f_rcap_growth1y(df):
    return log_ratio(df["rcap"], df["rcap"].shift(YEAR))


@feature("nrpl", "onchain", "level", "Net realized profit/loss (90d)",
         "Net profit locked in by coins that moved over 90 days, as a share of market cap. "
         "Derived from the daily change in realized cap minus new issuance.")
def f_nrpl(df):
    net = df["rcap"].diff() - df["iss_usd"]
    return (net / df["mcap"]).rolling(90, min_periods=60).sum()


@feature("rcap_dd", "onchain", "level", "Realized cap drawdown",
         "Realized cap against its record: it only falls when holders sell at a loss in bulk.",
         side="bottom")
def f_rcap_dd(df):
    return log_ratio(df["rcap"], df["rcap"].cummax())


@feature("delta_price", "onchain", "level", "Price / Delta price",
         "Price against Delta price (realized cap minus the all-time average market cap), a classic floor.",
         side="bottom")
def f_delta(df):
    avg_cap = df["mcap"].expanding(min_periods=YEAR).mean()
    delta_cap = (df["rcap"] - avg_cap).where(lambda s: s > 0)
    return log_ratio(df["mcap"], delta_cap)


@feature("top_price", "trend", "level", "Price / Top price",
         "Price against Top price (35 times the all-time average market cap), a classic ceiling.",
         side="top")
def f_top(df):
    avg_cap = df["mcap"].expanding(min_periods=YEAR).mean()
    return log_ratio(df["mcap"], 35 * avg_cap)


@feature("thermo", "onchain", "level", "Thermocap multiple",
         "Market cap against everything miners have ever been paid.")
def f_thermo(df):
    return log_ratio(df["mcap"], df["miner_rev_usd"].fillna(0).cumsum())


@feature("rcap_thermo", "onchain", "level", "Realized cap / Thermocap",
         "Investor cost basis against cumulative miner income.")
def f_rcap_thermo(df):
    return log_ratio(df["rcap"], df["miner_rev_usd"].fillna(0).cumsum())


# ---- family: miners ---------------------------------------------------------
@feature("puell", "miners", "vol", "Puell Multiple",
         "Daily value of newly mined coins against its 1-year average.")
def f_puell(df):
    return log_ratio(df["iss_usd"], sma(df["iss_usd"], YEAR))


@feature("hashprice", "miners", "vol", "Hash price vs. 1-year average",
         "Miner income per unit of hash power against its 1-year average; lows mean miner stress.")
def f_hashprice(df):
    hp = sma(df["miner_rev_usd"], 7) / sma(df["hashrate"], 7)
    return log_ratio(hp, sma(hp, YEAR))


@feature("hash_ribbon", "miners", "level", "Hash ribbon",
         "30-day against 60-day average hash rate; negative means miners are switching off.")
def f_ribbon(df):
    return log_ratio(sma(df["hashrate"], 30), sma(df["hashrate"], 60))


@feature("fee_share", "miners", "level", "Fee share of miner income",
         "Share of miner income coming from fees (30-day average); block space gets bid up in manias.",
         side="top")
def f_fee_share(df):
    return sma(df["fee_usd"], 30) / sma(df["miner_rev_usd"], 30)


# ---- family: network activity ----------------------------------------------
@feature("nvt", "network", "drift", "NVT signal",
         "Market cap against the 90-day average value moved on-chain.")
def f_nvt(df):
    return log_ratio(df["mcap"], sma(df["tx_volume_usd"], 90, min_frac=0.7))


@feature("metcalfe", "network", "drift", "Metcalfe ratio",
         "Market cap against the square of active addresses (30-day average).")
def f_metcalfe(df):
    return log_ratio(df["mcap"], sma(df["adr_active"], 30) ** 2)


@feature("aa_mom", "network", "level", "Active-address momentum",
         "30-day against 1-year average of active addresses.")
def f_aa_mom(df):
    return log_ratio(sma(df["adr_active"], 30), sma(df["adr_active"], YEAR))


@feature("adr_growth", "network", "drift", "Holder-address growth",
         "90-day growth in the number of addresses holding a balance.")
def f_adr_growth(df):
    return log_ratio(df["adr_balance"], df["adr_balance"].shift(90))


@feature("tx_mom", "network", "level", "Transaction momentum",
         "30-day against 1-year average of on-chain transfers.")
def f_tx_mom(df):
    return log_ratio(sma(df["tx_transfers"], 30), sma(df["tx_transfers"], YEAR))


@feature("velocity", "network", "drift", "On-chain velocity",
         "Share of the supply moving on-chain per day (90-day average).")
def f_velocity(df):
    return log_ratio(sma(df["tx_volume_btc"], 90, min_frac=0.7), df["supply"])


@feature("turnover", "network", "drift", "Spot turnover",
         "Exchange spot volume against market cap (30-day average).")
def f_turnover(df):
    return log_ratio(sma(df["spot_volume_usd"], 30), df["mcap"])


@feature("volume_mom", "network", "level", "Volume momentum",
         "30-day against 1-year average of spot volume.")
def f_volmom(df):
    return log_ratio(sma(df["spot_volume_usd"], 30), sma(df["spot_volume_usd"], YEAR))


@feature("ex_netflow", "network", "level", "Exchange net inflow (30d)",
         "Net coins sent to exchanges over 30 days as a share of supply.")
def f_exflow(df):
    return (df["ex_in_btc"] - df["ex_out_btc"]).rolling(30, min_periods=20).sum() / df["supply"]


@feature("ex_supply_chg", "network", "level", "Exchange balance change (90d)",
         "Change in the share of supply held on exchanges over 90 days.")
def f_exsupply(df):
    share = df["ex_supply_btc"] / df["supply"]
    return share - share.shift(90)


# ---- family: sentiment ------------------------------------------------------
@feature("fng", "sentiment", "level", "Fear & Greed (30d)",
         "Crypto Fear & Greed index, 30-day average. Starts in 2018.")
def f_fng(df):
    return sma(df["fng"], 30, min_frac=0.7) / 100.0


@feature("fng_fast", "sentiment", "level", "Fear & Greed (7d)",
         "Crypto Fear & Greed index, 7-day average. Starts in 2018.")
def f_fng_fast(df):
    return sma(df["fng"], 7, min_frac=0.7) / 100.0


@feature("ssr", "sentiment", "drift", "Stablecoin supply ratio",
         "Bitcoin market cap against total stablecoin supply: low means lots of sidelined buying power.")
def f_ssr(df):
    return log_ratio(df["mcap"], df["stable_usd"].where(df["stable_usd"] > 1e9))


@feature("stable_growth", "sentiment", "level", "Stablecoin supply growth (90d)",
         "90-day growth of total stablecoin supply, a gauge of fresh money entering crypto.")
def f_stable_growth(df):
    s = df["stable_usd"].where(df["stable_usd"] > 1e9)
    return log_ratio(s, s.shift(90))


# ---- family: clock (calendar only; reported separately, never in the core score) ----
@feature("halving_clock", "clock", "level", "Halving clock",
         "Fraction of the four-year halving cycle elapsed. Pure calendar, no market data.")
def f_halving(df):
    return days_since_last(HALVINGS, df.index) / (4 * YEAR)


@feature("days_from_ath", "clock", "level", "Days since record high",
         "Days since the last all-time high. Pure calendar.", side="bottom")
def f_days_ath(df):
    is_ath = df["logp"] >= df["logp"].cummax()
    last = pd.Series(np.where(is_ath, np.arange(len(df)), np.nan), index=df.index).ffill()
    return -(np.arange(len(df)) - last)   # negative: long time since ATH = bottom-like


def compute_raw(df: pd.DataFrame, names: list[str] | None = None) -> pd.DataFrame:
    """Raw indicator values (before scaling)."""
    out = {}
    for f in REGISTRY:
        if names is not None and f.name not in names:
            continue
        out[f.name] = f.fn(df)
    return pd.DataFrame(out, index=df.index)


def compute_normalised(df: pd.DataFrame, raw: pd.DataFrame | None = None,
                       vol_window: int = VOL_WINDOW) -> pd.DataFrame:
    """Raw values put on a through-time-comparable scale according to each indicator's ``norm``."""
    raw = compute_raw(df) if raw is None else raw
    vol = long_vol(df, vol_window)
    out = {}
    for f in REGISTRY:
        if f.name not in raw:
            continue
        x = raw[f.name]
        if f.norm == "vol":
            x = x / vol
        elif f.norm == "drift":
            x = x - x.rolling(2 * YEAR, min_periods=YEAR).median()
        out[f.name] = x
    return pd.DataFrame(out, index=df.index)


def meta() -> pd.DataFrame:
    return pd.DataFrame(
        [{"name": f.name, "family": f.family, "norm": f.norm, "label": f.label,
          "desc": f.desc, "side": f.side} for f in REGISTRY]
    ).set_index("name")
