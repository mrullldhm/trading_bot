"""Data periods (decision D001) and the CME trading-day rule.

A CME trading day starts at 18:00 ET the evening before: a minute at or after 18:00 ET belongs to the next
calendar date (same rule as propfirm_backtest/bars.py:49-52). Periods are cut by trading day, never by
UTC timestamp.
"""

from dataclasses import dataclass
from datetime import date

import numpy as np
import pandas as pd

ET = "America/New_York"
DAY_START_MOD = 18 * 60


@dataclass(frozen=True)
class Period:
    name: str
    first: date
    last: date | None  # None = until the end of the data


DISCOVERY = Period("discovery", date(2010, 6, 7), date(2016, 12, 31))
VALIDATION = Period("validation", date(2017, 1, 1), date(2021, 12, 31))
HOLDOUT = Period("holdout", date(2022, 1, 1), None)
PERIODS = {p.name: p for p in (DISCOVERY, VALIDATION, HOLDOUT)}


def epoch_day(d: date) -> int:
    return (pd.Timestamp(d) - pd.Timestamp("1970-01-01")) // pd.Timedelta(days=1)


def bounds(name: str) -> tuple[int, int | None]:
    """(first, last) trading day of a period as days since 1970-01-01 (last None = open-ended)."""
    p = PERIODS[name]
    return epoch_day(p.first), (None if p.last is None else epoch_day(p.last))


def trading_day(ts_utc: pd.Series) -> np.ndarray:
    """Days since 1970-01-01 of the CME trading day of each UTC timestamp."""
    et = pd.DatetimeIndex(ts_utc).tz_convert(ET)
    day = (et.tz_localize(None).normalize() - pd.Timestamp("1970-01-01")) // pd.Timedelta(days=1)
    mod = et.hour * 60 + et.minute
    return np.asarray(day, dtype=np.int64) + (np.asarray(mod) >= DAY_START_MOD)


def et_minute_of_day(ts_utc: pd.Series) -> np.ndarray:
    et = pd.DatetimeIndex(ts_utc).tz_convert(ET)
    return np.asarray(et.hour * 60 + et.minute, dtype=np.int32)


def period_of(day: int) -> str:
    """Period name of one trading day (days since epoch); 'before' for days ahead of discovery."""
    for name in ("holdout", "validation", "discovery"):
        first, _ = bounds(name)
        if day >= first:
            return name
    return "before"
