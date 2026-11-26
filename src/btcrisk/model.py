"""The Bitcoin Risk Metric.

One number per day between 0 and 1.  0 = Bitcoin looks the way it has looked at
cycle lows, 1 = the way it has looked at cycle highs.

Recipe (every step uses data up to that day only):

  1. Compute the core indicators and put each on a through-time-comparable scale.
  2. Read each one on its own ruler: where does today's value sit between the
     level of its past lows (0) and the level of its past highs (1)?  The ruler
     is built from the indicator's own history, lets old history fade slowly,
     and is read with a one-year delay so it cannot stretch during the very move
     it is measuring.
  3. Average the rulers inside each *lens* (a group of indicators that ask the
     same question), then average the lenses.  Three lenses:
        trend    how stretched is price against its long-run trend?
        onchain  how far is price above what holders actually paid?
        range    where is price inside its own recent range?
  4. Squash that average with a smooth S-curve so it lives in (0, 1) and never
     pins at the edge.

The core indicators were not hand-picked: they are the ones whose causal score
tracked the hindsight cycle position with a correlation of at least 0.75
(``select_by_rule``).  ``scripts/run_backtest.py`` re-runs that rule blind for
each past cycle to show what it would have chosen at the time.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from . import features as F
from .clock import cycle_clock
from .scoring import bands, position_in, squash

# Lenses and their indicators (result of the selection rule on data up to the Oct 2025 top).
CORE_LENSES: dict[str, tuple[str, ...]] = {
    "trend": ("ma4y", "ma2y", "powerlaw", "top_price"),
    "onchain": ("mvrv",),
    "range": ("dd_ath", "range_2y"),
}

LENS_LABELS = {
    "trend": "Price vs. its long-run trend",
    "onchain": "Price vs. what holders paid",
    "range": "Position in its own range",
    "momentum": "Momentum",
    "miners": "Miners",
    "network": "Network activity",
    "sentiment": "Sentiment",
}

# Left out of the candidate pool before any testing, for a structural reason.
EXCLUDED = {
    "thermo": "Its yardstick (everything miners have ever earned) grows more slowly after every halving, "
              "so the ratio drifts upward for reasons unrelated to the cycle.",
    "rcap_thermo": "Same yardstick problem as the Thermocap multiple.",
    "halving_clock": "Calendar only; reported separately as the halving clock.",
    "days_from_ath": "Calendar only.",
}

ZONES = [(0.0, 0.2, "Very low"), (0.2, 0.4, "Low"), (0.4, 0.6, "Neutral"),
         (0.6, 0.8, "High"), (0.8, 1.0001, "Very high")]


def zone(r: float) -> str:
    for lo, hi, name in ZONES:
        if lo <= r < hi:
            return name
    return "n/a"


@dataclass(frozen=True)
class ModelConfig:
    lo_q: float = 0.02                 # ruler's low end: the level the indicator stays above 98% of the time
    hi_q: float = 0.98                 # ruler's high end
    halflife_days: float | None = 8 * 365   # how fast old history fades (two cycles); None = never
    lag_days: int = 365                # read the ruler as it stood a year ago
    min_obs: int = 365                 # days of an indicator's history needed before it gets a ruler
    edge: float = 0.9                  # S-curve: position 1 (level of past highs) reads 0.9, position 0 reads 0.1
    vol_window: int = F.VOL_WINDOW     # window of the long-run volatility used to scale distances
    min_lenses: int = 2                # lenses needed for a score
    lenses: dict = field(default_factory=lambda: dict(CORE_LENSES))


@dataclass
class ModelResult:
    risk: pd.Series                    # the headline number
    composite: pd.Series               # average ruler position before the S-curve
    lens_position: pd.DataFrame
    lens_score: pd.DataFrame           # each lens through the same S-curve
    position: pd.DataFrame             # ruler position of every indicator computed
    score: pd.DataFrame                # ...through the S-curve
    raw: pd.DataFrame
    norm: pd.DataFrame
    band: dict                         # indicator -> DataFrame(lo, hi)
    clock: pd.Series
    clock_schedule: pd.DataFrame
    config: ModelConfig


def ruler_positions(norm: pd.DataFrame, cfg: ModelConfig, names=None) -> tuple[pd.DataFrame, dict]:
    """Ruler position of each indicator (and the rulers themselves)."""
    pos, band = {}, {}
    for c in (norm.columns if names is None else names):
        b = bands(norm[c], cfg.lo_q, cfg.hi_q, cfg.halflife_days, cfg.min_obs, cfg.lag_days)
        band[c] = b
        pos[c] = position_in(norm[c], b)
    return pd.DataFrame(pos, index=norm.index), band


def combine(position: pd.DataFrame, lenses: dict, min_lenses: int = 2) -> tuple[pd.Series, pd.DataFrame]:
    """Equal weight inside each lens, then equal weight across the lenses that have data."""
    lens = pd.DataFrame({name: position[list(members)].mean(axis=1) for name, members in lenses.items()})
    need = min(min_lenses, len(lenses))
    comp = lens.mean(axis=1).where(lens.notna().sum(axis=1) >= need)
    return comp, lens


def run_model(df: pd.DataFrame, cfg: ModelConfig | None = None, all_indicators: bool = True) -> ModelResult:
    """Run the metric over the whole table.  ``all_indicators=False`` computes the core ones only (faster)."""
    cfg = cfg or ModelConfig()
    core = [m for members in cfg.lenses.values() for m in members]
    names = None if all_indicators else core
    raw = F.compute_raw(df, names)
    norm = F.compute_normalised(df, raw, cfg.vol_window)
    position, band = ruler_positions(norm, cfg)
    comp, lens = combine(position, cfg.lenses, cfg.min_lenses)
    clock, sched = cycle_clock(df["price"])
    return ModelResult(
        risk=squash(comp, cfg.edge).rename("risk"), composite=comp.rename("composite"),
        lens_position=lens, lens_score=squash(lens, cfg.edge),
        position=position, score=squash(position, cfg.edge),
        raw=raw, norm=norm, band=band, clock=clock, clock_schedule=sched, config=cfg,
    )


# ----------------------------------------------------------------------------
# the selection rule
# ----------------------------------------------------------------------------
def past_skill(score: pd.DataFrame, ideal: pd.Series, start: str, end: str,
               min_days: int = 3 * 365) -> pd.Series:
    """Correlation of each indicator's causal score with the hindsight cycle position
    over [start, end].  Indicators with less than ``min_days`` of scores get NaN."""
    out = {}
    for c in score.columns:
        j = pd.concat([score[c].rename("s"), ideal.rename("ideal")], axis=1).loc[start:end].dropna()
        out[c] = j["s"].corr(j["ideal"]) if len(j) >= min_days else np.nan
    return pd.Series(out).sort_values(ascending=False)


def select_by_rule(skill: pd.Series, threshold: float = 0.75) -> dict[str, tuple[str, ...]]:
    """Keep every indicator whose past skill is at least ``threshold``; group them by family."""
    fam = F.meta()["family"]
    lenses: dict[str, list[str]] = {}
    for name, v in skill.items():
        if name in EXCLUDED or not np.isfinite(v) or v < threshold:
            continue
        lenses.setdefault(fam[name], []).append(name)
    return {k: tuple(v) for k, v in lenses.items()}
