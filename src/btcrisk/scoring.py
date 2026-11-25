"""Turn indicators into 0..1 scores, and scores into one risk number.

All steps are causal: the score for day t is computed from data up to day t.

Step 1 - a ruler per indicator
    For each indicator keep a running record of where its past *lows* and
    *highs* have been (two quantiles of its own history, with older history
    slowly fading).  Today's position is where today's value sits between those
    two levels: 0 = at the level of past lows, 1 = at the level of past highs.
    The ruler is read with a delay (``lag``) so it cannot stretch during the
    very move it is measuring.

Step 2 - composite
    Average the positions (see ``model.py`` for how indicators are grouped).

Step 3 - S-curve
    A smooth squash maps the composite position onto (0, 1) without ever pinning
    it to the edge, so the most extreme day still gets the most extreme reading.
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


def bands(x: pd.Series, lo_q: float = 0.02, hi_q: float = 0.98,
          halflife: float | None = None, min_obs: int = 365, lag: int = 0) -> pd.DataFrame:
    """The ruler for ``x``: the level of its past lows (``lo``) and past highs (``hi``), day by day.

    ``lag`` (days) hands today the ruler as it stood ``lag`` days ago.  Without it
    the ruler stretches while it is being used: during a blow-off the new record
    values drag the "level of past highs" up with them, so the reading can peak
    months before price does.
    """
    q = decayed_quantiles(x, (lo_q, hi_q), halflife, min_obs)
    if lag:
        q = q.shift(lag)
    q.columns = ["lo", "hi"]
    return q


def position_in(x: pd.Series, band: pd.DataFrame) -> pd.Series:
    """Where ``x`` sits on its ruler: 0 = level of past lows, 1 = level of past highs (not clipped)."""
    width = (band["hi"] - band["lo"]).where((band["hi"] - band["lo"]) > 1e-12)
    return (x - band["lo"]) / width


def squash(u: pd.Series | np.ndarray, edge: float = 0.9):
    """Smooth S-curve from band position to (0, 1).

    Position 0 (level of past lows) maps to ``1 - edge`` and position 1 (level of
    past highs) to ``edge``; beyond that it keeps creeping toward 0 or 1 without
    ever flattening completely, so the most extreme day still gets the most
    extreme reading.
    """
    k = 2.0 * np.log(edge / (1.0 - edge))
    return 1.0 / (1.0 + np.exp(-k * (u - 0.5)))
