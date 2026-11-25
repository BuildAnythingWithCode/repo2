"""Turn indicators into 0..1 scores, and scores into one risk number.

All steps are causal: the score for day t is computed from data up to day t.

Step 1 - band score per indicator
    For each indicator keep a running record of where its past *lows* and
    *highs* have been (two quantiles of its own history, with older history
    slowly fading).  Today's score is today's position between those two levels:
    0 = at the level of past lows, 1 = at the level of past highs.

Step 2 - composite
    Weighted average of the available band scores.

Step 3 - stretch
    Averaging pulls values toward the middle (indicators rarely all peak on the
    same day), so the composite is re-spread between its own past low and high
    quantiles, again causally.
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def decayed_quantiles(x: pd.Series, qs: tuple[float, ...], halflife: float | None,
                      min_obs: int = 365) -> pd.DataFrame:
    """Exponentially time-weighted quantiles of the history of ``x`` up to each day.

    ``halflife`` is in days (None = no fading, i.e. plain expanding quantiles).
    Weights are relative, so instead of decaying old points each day we let
    newer points carry proportionally larger fixed weights: same quantiles,
    no rescaling needed.
    """
    vals = x.values.astype(float)
    n = len(vals)
    out = np.full((n, len(qs)), np.nan)
    sorted_v = np.empty(0)
    sorted_w = np.empty(0)
    t_idx = np.arange(n, dtype=float)
    w_all = np.ones(n) if halflife is None else np.power(2.0, (t_idx - t_idx[-1]) / halflife)
    count = 0
    qs_arr = np.asarray(qs)
    for i in range(n):
        v = vals[i]
        if not np.isnan(v):
            pos = np.searchsorted(sorted_v, v)
            sorted_v = np.insert(sorted_v, pos, v)
            sorted_w = np.insert(sorted_w, pos, w_all[i])
            count += 1
        if count >= min_obs:
            cw = np.cumsum(sorted_w)
            # midpoint rule so a single observation sits at the centre of its weight
            cdf = (cw - 0.5 * sorted_w) / cw[-1]
            out[i] = np.interp(qs_arr, cdf, sorted_v)
    return pd.DataFrame(out, index=x.index, columns=[f"q{q:g}" for q in qs])


def band_position(x: pd.Series, lo_q: float = 0.02, hi_q: float = 0.98,
                  halflife: float | None = None, min_obs: int = 365) -> pd.Series:
    """Position of ``x`` between its own historical low level (0) and high level (1).

    Deliberately NOT clipped: a value beyond anything seen before lands above 1
    (or below 0), so the reading keeps moving in a record-breaking run instead of
    sitting pinned at the edge.
    """
    q = decayed_quantiles(x, (lo_q, hi_q), halflife, min_obs)
    lo, hi = q.iloc[:, 0], q.iloc[:, 1]
    width = (hi - lo).where((hi - lo) > 1e-12)
    return (x - lo) / width


def squash(u: pd.Series | np.ndarray, edge: float = 0.9):
    """Smooth S-curve from band position to (0, 1).

    Position 0 (level of past lows) maps to ``1 - edge`` and position 1 (level of
    past highs) to ``edge``; beyond that it keeps creeping toward 0 or 1 without
    ever flattening completely, so the most extreme day still gets the most
    extreme reading.
    """
    k = 2.0 * np.log(edge / (1.0 - edge))
    return 1.0 / (1.0 + np.exp(-k * (u - 0.5)))


def band_score(x: pd.Series, lo_q: float = 0.02, hi_q: float = 0.98,
               halflife: float | None = None, min_obs: int = 365,
               clip: bool = True) -> pd.Series:
    """Band position clipped to [0, 1] (hard-edged variant, kept for comparison)."""
    u = band_position(x, lo_q, hi_q, halflife, min_obs)
    return u.clip(0, 1) if clip else u


def ecdf_score(x: pd.Series, halflife: float | None = None, min_obs: int = 365) -> pd.Series:
    """Time-weighted percentile rank of today's value within its own history."""
    vals = x.values.astype(float)
    n = len(vals)
    out = np.full(n, np.nan)
    sorted_v = np.empty(0)
    sorted_w = np.empty(0)
    t_idx = np.arange(n, dtype=float)
    w_all = np.ones(n) if halflife is None else np.power(2.0, (t_idx - t_idx[-1]) / halflife)
    count = 0
    for i in range(n):
        v = vals[i]
        if np.isnan(v):
            continue
        pos = np.searchsorted(sorted_v, v)
        sorted_v = np.insert(sorted_v, pos, v)
        sorted_w = np.insert(sorted_w, pos, w_all[i])
        count += 1
        if count >= min_obs:
            cw = np.cumsum(sorted_w)
            out[i] = (cw[pos] - 0.5 * sorted_w[pos]) / cw[-1]
    return pd.Series(out, index=x.index)


def score_table(norm: pd.DataFrame, method: str = "band", lo_q: float = 0.02, hi_q: float = 0.98,
                halflife: float | None = None, min_obs: int = 365) -> pd.DataFrame:
    """Apply the chosen scoring to every column."""
    out = {}
    for c in norm.columns:
        if method == "band":
            out[c] = band_score(norm[c], lo_q, hi_q, halflife, min_obs)
        elif method == "position":
            out[c] = band_position(norm[c], lo_q, hi_q, halflife, min_obs)
        elif method == "ecdf":
            out[c] = ecdf_score(norm[c], halflife, min_obs)
        else:
            raise ValueError(method)
    return pd.DataFrame(out, index=norm.index)


def composite(scores: pd.DataFrame, weights: pd.Series | dict | None = None,
              min_features: int = 4) -> pd.Series:
    """Weighted mean over the indicators available on each day."""
    if weights is None:
        weights = pd.Series(1.0, index=scores.columns)
    w = pd.Series(weights, dtype=float).reindex(scores.columns).fillna(0.0)
    avail = scores.notna()
    wsum = (avail * w).sum(axis=1)
    c = (scores.fillna(0) * w).sum(axis=1) / wsum.where(wsum > 0)
    return c.where(avail.sum(axis=1) >= min_features)


def stretch(c: pd.Series, lo_q: float = 0.02, hi_q: float = 0.98,
            halflife: float | None = None, min_obs: int = 365) -> pd.Series:
    """Re-spread the composite between its own past extremes (causal, hard-edged)."""
    return band_score(c, lo_q, hi_q, halflife, min_obs)


def soft_stretch(c: pd.Series, lo_q: float = 0.02, hi_q: float = 0.98,
                 halflife: float | None = None, min_obs: int = 365,
                 edge: float = 0.9) -> pd.Series:
    """Re-spread the composite between its own past extremes, then apply the S-curve."""
    return squash(band_position(c, lo_q, hi_q, halflife, min_obs), edge)
