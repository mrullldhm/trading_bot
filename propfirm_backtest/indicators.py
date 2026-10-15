"""EMA, SMA, ATR and anchored VWAP. All prices are in ticks (1 tick = $0.01)."""

import numpy as np
from numba import njit

from .bars import Bars, Minutes, session_mask

VWAP_ANCHORS = ["day", "session", "week"]
EMA_LENGTHS = [9, 13, 20, 21, 34, 50, 100, 200]


@njit(cache=True)
def _ema(close, contract, length):
    """EMA per contract (restarts on a new contract). Returns (ema, valid)."""
    n = len(close)
    out = np.empty(n)
    valid = np.zeros(n, dtype=np.bool_)
    alpha = 2.0 / (length + 1.0)
    count = 0
    for i in range(n):
        if i == 0 or contract[i] != contract[i - 1]:
            out[i] = close[i]
            count = 1
        else:
            out[i] = alpha * close[i] + (1.0 - alpha) * out[i - 1]
            count += 1
        valid[i] = count >= length  # warm-up: need `length` bars of this contract
    return out, valid


def ema(bars: Bars, length: int) -> tuple[np.ndarray, np.ndarray]:
    return _ema(bars.close, bars.contract, length)


@njit(cache=True)
def _sma(close, contract, length):
    """Simple moving average of the last `length` closes of the same contract. Returns (sma, valid)."""
    n = len(close)
    out = np.full(n, np.nan)
    valid = np.zeros(n, dtype=np.bool_)
    total = 0.0
    count = 0
    first = 0  # first row of the current contract
    for i in range(n):
        if i == 0 or contract[i] != contract[i - 1]:
            total = 0.0
            count = 0
            first = i
        total += close[i]
        count += 1
        if i - first >= length:
            total -= close[i - length]
        if count >= length:
            out[i] = total / length
            valid[i] = True
    return out, valid


def sma(bars: Bars, length: int) -> tuple[np.ndarray, np.ndarray]:
    return _sma(bars.close, bars.contract, length)


@njit(cache=True)
def _atr(high, low, close, contract, length):
    """Wilder ATR per contract: seeded with the mean of the first `length` true ranges, then
    atr = (atr * (length - 1) + tr) / length. The first bar of a contract has tr = high - low."""
    n = len(close)
    out = np.full(n, np.nan)
    valid = np.zeros(n, dtype=np.bool_)
    count = 0
    acc = 0.0
    for i in range(n):
        if i == 0 or contract[i] != contract[i - 1]:
            count = 0
            acc = 0.0
            tr = high[i] - low[i]
        else:
            pc = close[i - 1]
            tr = max(high[i] - low[i], abs(high[i] - pc), abs(low[i] - pc))
        count += 1
        if count < length:
            acc += tr
        elif count == length:
            acc = (acc + tr) / length
        else:
            acc = (acc * (length - 1) + tr) / length
        if count >= length:
            out[i] = acc
            valid[i] = True
    return out, valid


def atr(bars: Bars, length: int) -> tuple[np.ndarray, np.ndarray]:
    return _atr(bars.high, bars.low, bars.close, bars.contract, length)


def anchor_ids(m: Minutes, anchor: str, session: str) -> np.ndarray:
    """Group id per minute; VWAP restarts whenever it (or the contract) changes."""
    td = m.trading_day.astype(np.int64)
    if anchor == "day":  # CME trading day, starts 18:00 ET
        base = td
    elif anchor == "week":  # CME week: Sunday 18:00 ET (= Monday trading day) onwards
        base = (td - 4) // 7  # 1970-01-05 (day 4) was a Monday
    elif anchor == "session":  # starts at the chosen session's open
        inside, instance, _ = session_mask(m, session)
        base = np.where(inside, instance, -1 - td)  # outside the session: separate groups
    else:
        raise ValueError(anchor)
    return base * 100_000 + m.contract.astype(np.int64)


@njit(cache=True)
def _vwap(high, low, close, volume, group):
    """Cumulative VWAP of typical price (H+L+C)/3 since the group started.
    out_after[i]  = VWAP including minute i (known at the END of minute i)
    out_before[i] = VWAP through minute i-1 (known at the START of minute i; NaN at a reset)."""
    n = len(close)
    after = np.empty(n)
    before = np.empty(n)
    pv = 0.0
    v = 0.0
    for i in range(n):
        if i == 0 or group[i] != group[i - 1]:
            pv = 0.0
            v = 0.0
        before[i] = pv / v if v > 0 else np.nan
        pv += (high[i] + low[i] + close[i]) / 3.0 * volume[i]
        v += volume[i]
        after[i] = pv / v if v > 0 else np.nan
    return after, before


def vwap_minutes(m: Minutes, anchor: str, session: str) -> tuple[np.ndarray, np.ndarray]:
    return _vwap(m.high, m.low, m.close, m.volume, anchor_ids(m, anchor, session))


def vwap_bars(bars: Bars, after: np.ndarray, before: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Per bar: VWAP at the bar's close, and VWAP frozen at the bar's open (for touch entries).
    The open value uses only minutes completed before the bar started: no look-ahead."""
    return after[bars.end - 1], before[bars.start]
