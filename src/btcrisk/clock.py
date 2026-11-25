"""The halving clock: a calendar-only second opinion, never part of the risk score.

Bitcoin's last three cycles topped 371, 525 and 546 days after a halving and
bottomed 777, 889 and 912 days after it.  This module turns that regularity into
a 0..1 dial (0 = the calendar says "bottom season", 1 = "top season") in a way
that could have been computed at the time:

  * the expected top and bottom for the current halving era are the average
    offsets of *completed* eras only;
  * an era's own top and bottom are taken from turning points that had already
    been confirmed (a 70% fall, then a 233% rise) before the era ended.

It is reported next to the risk score, not inside it: three cycles are far too
few to trust a calendar, and in testing it did not make the score more accurate.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .config import HALVINGS, NEXT_HALVING_EST
from .labels import zigzag


def learned_offsets(price: pd.Series, halvings=HALVINGS, next_est=NEXT_HALVING_EST) -> pd.DataFrame:
    """Days from each halving to its era's cycle top and bottom, for completed eras."""
    H = [pd.Timestamp(h) for h in halvings] + [pd.Timestamp(next_est)]
    rows = []
    for k in range(len(H) - 1):
        start, end = H[k], H[k + 1]
        if end > price.index[-1]:
            break
        pv = zigzag(price.loc[:end], up=2.3333, down=0.70)     # data up to the era's end only
        tops = [x for x in pv if x.kind == "top" and start <= x.date < end]
        if not tops:
            continue
        top = max(tops, key=lambda x: x.price)
        bots = [x for x in pv if x.kind == "bottom" and top.date < x.date < end]
        if not bots:
            continue
        bot = min(bots, key=lambda x: x.price)
        rows.append({"halving": start, "era_end": end, "top": top.date, "bottom": bot.date,
                     "top_offset": (top.date - start).days, "bottom_offset": (bot.date - start).days,
                     "era_days": (end - start).days})
    return pd.DataFrame(rows)


def cycle_clock(price: pd.Series, halvings=HALVINGS, next_est=NEXT_HALVING_EST) -> tuple[pd.Series, pd.DataFrame]:
    """Returns (clock, schedule).

    ``clock`` is NaN until one full halving era has been observed.  ``schedule``
    lists, per era, the expected top and bottom dates the clock was using.
    """
    H = [pd.Timestamp(h) for h in halvings] + [pd.Timestamp(next_est)]
    idx = price.index
    learned = learned_offsets(price, halvings, next_est)
    out = pd.Series(np.nan, index=idx, name="clock")
    sched = []
    for k in range(1, len(H) - 1):
        start, end = H[k], H[k + 1]
        known = learned[learned["era_end"] <= start]
        if known.empty:
            continue
        to, bo = known["top_offset"].mean(), known["bottom_offset"].mean()
        era_len, prev_len = (end - start).days, (start - H[k - 1]).days
        # expected turning points on a day axis measured from this era's halving
        anchors = [(bo - prev_len, 0.0), (to, 1.0), (bo, 0.0), (era_len + to, 1.0)]
        days = (idx - start).days.values.astype(float)
        in_era = (idx >= start) & (idx < end)
        for (d0, v0), (d1, v1) in zip(anchors[:-1], anchors[1:]):
            seg = in_era & (days >= d0) & (days < d1)
            frac = (days[seg] - d0) / (d1 - d0)
            out[seg] = v0 + (v1 - v0) * 0.5 * (1 - np.cos(np.pi * frac))
        sched.append({"halving": start, "expected_top": start + pd.Timedelta(days=round(to)),
                      "expected_bottom": start + pd.Timedelta(days=round(bo)),
                      "top_offset": round(to), "bottom_offset": round(bo), "eras_used": len(known)})
    return out, pd.DataFrame(sched)
