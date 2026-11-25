"""Download every raw input the risk metric uses, from free public sources.

Each ``fetch_*`` function returns a tidy ``pandas.DataFrame`` indexed by UTC date
(one row per day unless stated) and never raises on an empty tail: callers decide
what to do with stale data.  ``update_all`` writes one CSV per source under
``data/raw/<source>/`` so a later run can fall back to the last good copy if a
source is down.

Sources (all free, no API keys):
  * Coin Metrics community API  - price and on-chain aggregates, from 2010-07-18
  * Blockchain.com charts API   - transfer volume, addresses, miner revenue ...
  * alternative.me              - Crypto Fear & Greed index, from 2018-02-01
  * DefiLlama                   - total stablecoin supply, from 2017-11-29
  * Coinbase Exchange           - daily OHLCV candles and the live price
  * CBBI (colintalkscrypto.com) - an existing public composite, benchmark only
"""
from __future__ import annotations

import io
import json
import time
from pathlib import Path

import pandas as pd
import requests

from .config import RAW, USER_AGENT

TIMEOUT = 60
_session: requests.Session | None = None


def _http() -> requests.Session:
    global _session
    if _session is None:
        s = requests.Session()
        s.headers.update({"User-Agent": USER_AGENT, "Accept": "application/json, text/csv, */*"})
        _session = s
    return _session


def _get(url: str, params: dict | None = None, retries: int = 4, backoff: float = 2.0) -> requests.Response:
    """GET with polite retry on transient failures (network errors, 429, 5xx)."""
    last: Exception | None = None
    for attempt in range(retries):
        try:
            r = _http().get(url, params=params, timeout=TIMEOUT)
            if r.status_code == 200:
                return r
            if r.status_code in (429, 500, 502, 503, 504):
                last = RuntimeError(f"HTTP {r.status_code} from {url}")
            else:
                r.raise_for_status()
        except requests.RequestException as exc:  # network error, timeout ...
            last = exc
        time.sleep(backoff * (2**attempt))
    raise RuntimeError(f"GET failed after {retries} attempts: {url}: {last}")


# ----------------------------------------------------------------------------
# Coin Metrics community API
# ----------------------------------------------------------------------------
CM_BASE = "https://community-api.coinmetrics.io/v4"
CM_METRICS = [
    "PriceUSD", "CapMrktCurUSD", "CapMVRVCur", "SplyCur",
    "IssTotNtv", "IssTotUSD", "FeeTotNtv", "HashRate", "BlkCnt",
    "AdrActCnt", "AdrBalCnt", "TxCnt", "TxTfrCnt",
    "FlowInExNtv", "FlowOutExNtv", "FlowInExUSD", "FlowOutExUSD", "SplyExNtv",
    "volume_reported_spot_usd_1d", "CapMrktEstUSD", "ROI30d", "ROI1yr",
]


def fetch_coinmetrics(metrics: list[str] | None = None, asset: str = "btc") -> pd.DataFrame:
    """Daily asset metrics for Bitcoin over the full available history."""
    metrics = metrics or CM_METRICS
    url = f"{CM_BASE}/timeseries/asset-metrics"
    params = {
        "assets": asset,
        "metrics": ",".join(metrics),
        "frequency": "1d",
        "page_size": 10000,
        "start_time": "2009-01-03",
        "paging_from": "start",
    }
    rows: list[dict] = []
    while True:
        payload = _get(url, params=params).json()
        rows.extend(payload.get("data", []))
        nxt = payload.get("next_page_url")
        if not nxt:
            break
        url, params = nxt, None
        time.sleep(0.7)  # community tier: 10 requests / 6 s
    df = pd.DataFrame(rows)
    df["date"] = pd.to_datetime(df["time"]).dt.tz_localize(None).dt.normalize()
    df = df.drop(columns=["asset", "time"]).set_index("date").sort_index()
    df = df.apply(pd.to_numeric, errors="coerce")
    return df[~df.index.duplicated(keep="last")]


def fetch_coinmetrics_reference_rate(asset: str = "btc") -> pd.DataFrame:
    """Most recent daily reference rates (covers today, which asset-metrics lags)."""
    url = f"{CM_BASE}/timeseries/asset-metrics"
    params = {"assets": asset, "metrics": "ReferenceRateUSD", "frequency": "1d", "page_size": 100}
    payload = _get(url, params=params).json()
    df = pd.DataFrame(payload.get("data", []))
    if df.empty:
        return pd.DataFrame(columns=["ReferenceRateUSD"])
    df["date"] = pd.to_datetime(df["time"]).dt.tz_localize(None).dt.normalize()
    df = df.set_index("date")[["ReferenceRateUSD"]].apply(pd.to_numeric, errors="coerce")
    return df.sort_index()


# ----------------------------------------------------------------------------
# Blockchain.com charts
# ----------------------------------------------------------------------------
BC_BASE = "https://api.blockchain.info/charts"
BC_CHARTS = [
    "estimated-transaction-volume-usd",  # USD value moved on-chain (change-adjusted estimate)
    "estimated-transaction-volume",      # same, in BTC
    "output-volume",                     # raw BTC output volume
    "n-unique-addresses",
    "n-transactions",
    "n-transactions-excluding-popular",
    "miners-revenue",                    # USD, block reward + fees
    "transaction-fees-usd",
    "transaction-fees",
    "hash-rate",
    "difficulty",
    "market-price",
    "trade-volume",
    "utxo-count",
    "total-bitcoins",
    "cost-per-transaction",
    "mempool-size",
    "avg-block-size",
]


def fetch_blockchain_chart(name: str) -> pd.Series:
    params = {"timespan": "all", "sampled": "false", "metadata": "false", "cors": "true", "format": "json"}
    payload = _get(f"{BC_BASE}/{name}", params=params).json()
    vals = payload.get("values", [])
    s = pd.Series(
        [v["y"] for v in vals],
        index=pd.to_datetime([v["x"] for v in vals], unit="s").normalize(),
        name=name,
        dtype="float64",
    )
    s = s[~s.index.duplicated(keep="last")].sort_index()
    s.index.name = "date"
    return s


def fetch_blockchain(charts: list[str] | None = None) -> pd.DataFrame:
    out = {}
    for name in charts or BC_CHARTS:
        try:
            out[name] = fetch_blockchain_chart(name)
        except Exception as exc:  # one missing chart must not sink the run
            print(f"  ! blockchain.com chart '{name}' failed: {exc}")
        time.sleep(0.4)
    return pd.DataFrame(out).sort_index()


# ----------------------------------------------------------------------------
# Fear & Greed
# ----------------------------------------------------------------------------
def fetch_fear_greed() -> pd.DataFrame:
    payload = _get("https://api.alternative.me/fng/", params={"limit": 0, "format": "json"}).json()
    rows = payload.get("data", [])
    df = pd.DataFrame(
        {
            "fng": [float(r["value"]) for r in rows],
            "fng_label": [r.get("value_classification", "") for r in rows],
        },
        index=pd.to_datetime([int(r["timestamp"]) for r in rows], unit="s").normalize(),
    )
    df.index.name = "date"
    return df[~df.index.duplicated(keep="last")].sort_index()


# ----------------------------------------------------------------------------
# Stablecoin supply (DefiLlama)
# ----------------------------------------------------------------------------
def fetch_stablecoins() -> pd.DataFrame:
    rows = _get("https://stablecoins.llama.fi/stablecoincharts/all").json()
    idx = pd.to_datetime([int(r["date"]) for r in rows], unit="s").normalize()
    usd = [float((r.get("totalCirculatingUSD") or {}).get("peggedUSD", float("nan"))) for r in rows]
    df = pd.DataFrame({"stable_usd": usd}, index=idx)
    df.index.name = "date"
    return df[~df.index.duplicated(keep="last")].sort_index()


# ----------------------------------------------------------------------------
# Coinbase candles
# ----------------------------------------------------------------------------
def fetch_coinbase_daily(start: str = "2015-07-20", product: str = "BTC-USD") -> pd.DataFrame:
    """Daily OHLCV from Coinbase Exchange (300 candles per request)."""
    url = f"https://api.exchange.coinbase.com/products/{product}/candles"
    out: list[list] = []
    cur = pd.Timestamp(start, tz="UTC")
    end_all = pd.Timestamp.now(tz="UTC").normalize() + pd.Timedelta(days=1)
    step = pd.Timedelta(days=299)
    while cur < end_all:
        stop = min(cur + step, end_all)
        params = {"granularity": 86400, "start": cur.isoformat(), "end": stop.isoformat()}
        data = _get(url, params=params).json()
        if isinstance(data, list):
            out.extend(data)
        cur = stop + pd.Timedelta(days=1)
        time.sleep(0.25)
    df = pd.DataFrame(out, columns=["ts", "low", "high", "open", "close", "volume"])
    df["date"] = pd.to_datetime(df["ts"], unit="s").dt.normalize()
    df = df.drop(columns="ts").drop_duplicates("date").set_index("date").sort_index()
    return df.add_prefix("cb_")


def fetch_spot_price(product: str = "BTC-USD") -> tuple[float, pd.Timestamp]:
    """Latest traded price, for the intraday reading."""
    r = _get(f"https://api.exchange.coinbase.com/products/{product}/ticker").json()
    return float(r["price"]), pd.Timestamp(r["time"]).tz_convert("UTC")


# ----------------------------------------------------------------------------
# CBBI (benchmark only: its inputs are normalised with hindsight)
# ----------------------------------------------------------------------------
def fetch_cbbi() -> pd.DataFrame:
    payload = _get("https://colintalkscrypto.com/cbbi/data/latest.json").json()
    cols = {}
    for key, series in payload.items():
        if not isinstance(series, dict):
            continue
        s = pd.Series(series, dtype="float64")
        s.index = pd.to_datetime(s.index.astype("int64"), unit="s").normalize()
        cols[f"cbbi_{key}"] = s
    df = pd.DataFrame(cols).sort_index()
    df.index.name = "date"
    return df


# ----------------------------------------------------------------------------
# Orchestration
# ----------------------------------------------------------------------------
def _save(df: pd.DataFrame, source: str, name: str) -> Path:
    folder = RAW / source
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{name}.csv"
    df.to_csv(path)
    return path


def update_all(verbose: bool = True) -> dict[str, str]:
    """Refresh every source. Returns {source: 'ok' | error text}."""
    status: dict[str, str] = {}
    jobs = [
        ("coinmetrics", "btc", fetch_coinmetrics),
        ("coinmetrics", "reference_rate", fetch_coinmetrics_reference_rate),
        ("blockchain", "charts", fetch_blockchain),
        ("alternative", "fear_greed", fetch_fear_greed),
        ("defillama", "stablecoins", fetch_stablecoins),
        ("coinbase", "btc_usd_daily", fetch_coinbase_daily),
        ("cbbi", "cbbi", fetch_cbbi),
    ]
    for source, name, fn in jobs:
        key = f"{source}/{name}"
        t0 = time.time()
        try:
            df = fn()
            if df is None or len(df) == 0:
                raise RuntimeError("empty response")
            path = _save(df, source, name)
            status[key] = "ok"
            if verbose:
                print(
                    f"  ok  {key:32s} {len(df):6d} rows  {df.index.min().date()} .. {df.index.max().date()}"
                    f"  ({time.time() - t0:4.1f}s) -> {path.relative_to(RAW.parent.parent)}"
                )
        except Exception as exc:
            status[key] = f"error: {exc}"
            if verbose:
                print(f"  !!  {key:32s} {exc}")
    (RAW / "fetch_status.json").write_text(
        json.dumps({"fetched_at": pd.Timestamp.now(tz="UTC").isoformat(), "status": status}, indent=2)
    )
    return status


def load_raw(source: str, name: str) -> pd.DataFrame:
    df = pd.read_csv(RAW / source / f"{name}.csv", index_col=0, parse_dates=True)
    df.index.name = "date"
    return df.sort_index()
