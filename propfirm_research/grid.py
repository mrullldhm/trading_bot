"""Decision-time windows: per trading day, enter at a clock time, exit at a later clock time or at the flat time.

Conventions (PROTOCOL §4.6):
- the decision at time T uses only bars that started before T; entry = open of the first bar at or after T
  (at most ENTRY_TOL minutes late), i.e. "next-minute open";
- exit = open of the bar that starts exactly at the exit time, never a later bar (D009); if that bar is
  missing the window is invalid and `exit_missing` is True;
- `entry_ok` / `entry_contract`: every check known by the entry time passed (the entry bar itself, at most
  ENTRY_TOL minutes after the decision time; the flat schedule; exit not after the flat time); `valid`
  additionally needs the exact exit bar in the same contract, known only at the exit (R014: callers keep
  entry-time masks and evaluated trades apart);
- flat time per window = the earliest of 16:05 ET (12:55 ET on scheduled short days), 5 min before the
  contract expires, 5 min before the scheduled roll to the next contract (roll = the next contract's first
  front minute floored to the hour, as bars.py; known in advance). A fixed exit after the flat time makes
  the window invalid; exit "FLAT" exits at the flat time; an entry at or after the flat time is invalid
  (so no entry in the last 5 minutes before a roll or expiry);
- unknown expiries of real contracts ("SYM@YYYY-MM") raise instead of trading through expiry;
- MFE / MAE are measured on bars from the entry bar up to (not including) the exit bar.
Returns are raw ticks: costs and direction are applied by the caller.
"""

import numpy as np
import pandas as pd
from numba import njit

from propfirm_backtest import orb_engine as E

ET = "America/New_York"
DAY_START_MOD = 18 * 60
FLAT_MOD = 16 * 60 + 5
SHORT_FLAT_MOD = 12 * 60 + 55
EXPIRY_BUFFER = 5
ROLL_BUFFER = 5
ENTRY_TOL = 5
FLAT = -1  # exit marker: at the day's flat time


def clock_tmin(days: np.ndarray, mod: int) -> np.ndarray:
    """UTC minutes of ET clock time `mod` within each trading day (>= 18:00 means the evening before)."""
    return E.local_tmin(days, mod, ET, days_before=1 if mod >= DAY_START_MOD else 0)


def flat_tmin(days: np.ndarray, flat_mod: int = FLAT_MOD) -> np.ndarray:
    out = clock_tmin(days, flat_mod)
    short = E.short_days(days)
    if short.any():
        out[short] = clock_tmin(days[short], SHORT_FLAT_MOD)
    return out


@njit(cache=False)
def _extremes(high, low, i0, i1):
    n = len(i0)
    hi = np.full(n, np.nan)
    lo = np.full(n, np.nan)
    for k in range(n):
        if i0[k] < 0 or i1[k] <= i0[k]:
            continue
        h = high[i0[k]]
        l_ = low[i0[k]]
        for j in range(i0[k] + 1, i1[k]):
            if high[j] > h:
                h = high[j]
            if low[j] < l_:
                l_ = low[j]
        hi[k] = h
        lo[k] = l_
    return hi, lo


def roll_schedule(tmin: np.ndarray, contract: np.ndarray) -> dict:
    """contract -> UTC minute it stops being front (next contract's first minute, floored to the hour)."""
    first = pd.Series(tmin).groupby(contract, sort=False).min().sort_values()
    nxt = first.shift(-1)
    return {c: int(t // 60 * 60) for c, t in nxt.items() if not np.isnan(t)}


def windows(df: pd.DataFrame, specs: list[tuple[int, int]], days: np.ndarray | None = None,
            expiry_tmin: dict | None = None) -> pd.DataFrame:
    """One row per (trading day, spec). specs: (start ET minute-of-day, end ET minute-of-day or FLAT).

    df: frame from propfirm_research.data (time-sorted, columns tmin, contract, open, high, low, trading_day).
    expiry_tmin: contract -> last trading UTC minute (None = look it up from the exchange definitions).
    """
    tmin = df["tmin"].to_numpy()
    opn, high, low = (df[c].to_numpy(float) for c in ("open", "high", "low"))
    contract = df["contract"].to_numpy()
    tday = df["trading_day"].to_numpy()
    if days is None:
        days = np.unique(tday)
    days = np.asarray(days, dtype=np.int64)
    keys = list(pd.unique(contract))
    if expiry_tmin is None:
        expiry_tmin = dict(zip(keys, E.contract_expiry(keys)))
    unknown = [k for k in keys if "@" in str(k) and expiry_tmin.get(k, -1) < 0]
    if unknown:
        raise ValueError(f"no expiry for contracts {unknown[:5]}: refusing to trade through expiry")
    roll_at = roll_schedule(tmin, contract)
    flat = flat_tmin(days)
    n = len(tmin)
    rows = []
    for start_mod, end_mod in specs:
        t0 = clock_tmin(days, start_mod)
        i0 = np.searchsorted(tmin, t0)
        ok = i0 < n
        i0c = np.minimum(i0, n - 1)
        ok &= (tmin[i0c] - t0 <= ENTRY_TOL) & (tday[i0c] == days)
        exp = np.array([expiry_tmin.get(c, -1) for c in contract[i0c]], dtype=np.int64)
        day_flat = np.where((exp >= 0) & (exp - EXPIRY_BUFFER < flat), exp - EXPIRY_BUFFER, flat)
        roll = np.array([roll_at.get(c, -1) for c in contract[i0c]], dtype=np.int64)
        day_flat = np.where((roll >= 0) & (roll - ROLL_BUFFER < day_flat), roll - ROLL_BUFFER, day_flat)
        ok &= tmin[i0c] < day_flat
        t1 = day_flat if end_mod == FLAT else clock_tmin(days, end_mod)
        ok &= t1 > t0
        ok &= t1 <= day_flat
        ok &= tmin[i0c] < t1  # a late entry bar must still start before the exit minute
        entry_ok = ok.copy()  # checks known by the entry time
        i1 = np.searchsorted(tmin, t1)
        i1c = np.minimum(i1, n - 1)
        has_exit = (i1 < n) & (tmin[i1c] == t1)  # D009: exactly the exit minute, never later
        exit_missing = ok & ~has_exit
        ok &= has_exit & (contract[i1c] == contract[i0c])
        a = np.where(ok, i0c, -1)
        b = np.where(ok, i1c, -1)
        hi, lo = _extremes(high, low, a, b)
        entry = np.where(ok, opn[i0c], np.nan)
        exit_ = np.where(ok, opn[i1c], np.nan)
        rows.append(pd.DataFrame({
            "trading_day": days, "start_mod": start_mod, "end_mod": end_mod, "valid": ok,
            "exit_missing": exit_missing, "entry_ok": entry_ok,
            "entry_contract": np.where(entry_ok, contract[i0c], None),
            "contract": np.where(ok, contract[i0c], None),
            "entry_tmin": np.where(ok, tmin[i0c], -1), "exit_tmin": np.where(ok, tmin[i1c], -1),
            "entry": entry, "exit": exit_, "ret_ticks": exit_ - entry,
            "mfe_long": hi - entry, "mae_long": entry - lo,  # ticks, >= 0
        }))
    return pd.concat(rows, ignore_index=True)


def trade_usd(w: pd.DataFrame, direction: np.ndarray, slip: float, fee: float, tick_usd: float = 10.0
              ) -> tuple[np.ndarray, np.ndarray]:
    """1-contract P&L and adverse excursion ($, positive) of trading each window in `direction` (+1/-1/0).
    MAE convention of propsim: adverse ticks + entry slippage, plus the fee."""
    d = np.asarray(direction, float)
    if ((d != 0) & ~w["valid"].to_numpy()).any():
        raise ValueError("a non-zero direction targets an invalid window: filter on `valid` first")
    pnl = d * w["ret_ticks"].to_numpy() * tick_usd - np.abs(d) * (fee + 2 * slip * tick_usd)
    adverse = np.where(d > 0, w["mae_long"].to_numpy(), w["mfe_long"].to_numpy())
    mae = np.abs(d) * ((adverse + slip) * tick_usd + fee)
    flat = d == 0  # no trade: zero P&L and excursion by definition
    return np.where(flat, 0.0, pnl), np.where(flat, 0.0, mae)


@njit(cache=False)
def _drift_adverse(high, low, tmin, i0, i1, sign, drift):
    """Per window: max of -(low') for longs, max of high' for shorts, on a path bent by a linear drift.

    Price at bar j becomes p_j + sign*drift*f_j with f_j = (tmin_j - tmin_i0) / (tmin_i1 - tmin_i0), so the
    drift is 0 at entry and `drift` ticks at the exit open. A bar's low/high gets the drift of the bar's
    start minute: the least helpful point of the bar (conservative for drift >= 0)."""
    n = len(i0)
    out = np.full(n, np.nan)
    for k in range(n):
        if i0[k] < 0 or i1[k] <= i0[k]:
            continue
        span = tmin[i1[k]] - tmin[i0[k]]
        worst = -1e18
        for j in range(i0[k], i1[k]):
            f = (tmin[j] - tmin[i0[k]]) / span
            if sign[k] > 0:
                a = -(low[j] + drift[k] * f)
            else:
                a = high[j] - drift[k] * f
            if a > worst:
                worst = a
        out[k] = worst  # long: -min(low'), short: max(high')
    return out


def planted(df: pd.DataFrame, w: pd.DataFrame, direction: np.ndarray, drift_ticks, slip: float, fee: float,
            tick_usd: float = 10.0) -> tuple[np.ndarray, np.ndarray]:
    """Like `trade_usd`, with a planted edge bent into the price path (R002 #2).

    The trade's path moves `drift_ticks` (scalar or per window) in the trade's direction, linearly from the
    entry open (0) to the exit open (full drift), so exit, MAE, DLL and MLL all see the same deformed path.
    df: the frame the windows came from. drift_ticks = 0 gives exactly `trade_usd`."""
    d = np.asarray(direction, float)
    valid = w["valid"].to_numpy()
    if ((d != 0) & ~valid).any():
        raise ValueError("a non-zero direction targets an invalid window: filter on `valid` first")
    g = np.broadcast_to(np.asarray(drift_ticks, float), d.shape).copy()
    tmin = df["tmin"].to_numpy()
    trade = (d != 0) & valid
    i0 = np.where(trade, np.searchsorted(tmin, w["entry_tmin"].to_numpy()), -1)
    i1 = np.where(trade, np.searchsorted(tmin, w["exit_tmin"].to_numpy()), -1)
    adv = _drift_adverse(df["high"].to_numpy(float), df["low"].to_numpy(float), tmin.astype(np.int64),
                         i0.astype(np.int64), i1.astype(np.int64), np.sign(d), g)
    entry = w["entry"].to_numpy()
    adverse = np.where(d > 0, adv + entry, adv - entry)  # long: entry - min(low'); short: max(high') - entry
    pnl = (d * w["ret_ticks"].to_numpy() + np.abs(d) * g) * tick_usd - np.abs(d) * (fee + 2 * slip * tick_usd)
    mae = np.abs(d) * ((adverse + slip) * tick_usd + fee)
    flat = ~trade
    return np.where(flat, 0.0, pnl), np.where(flat, 0.0, mae)


def one_trade_day_low(pnl: np.ndarray, mae: np.ndarray) -> np.ndarray:
    """Intraday low ($, <= 0) of a day with one trade: the worst of the pre-exit excursion and the result
    itself (the exit price is on the path too: R004 #1, as propsim's min(day_low, day_pnl))."""
    return np.minimum(np.minimum(-np.asarray(mae, float), np.asarray(pnl, float)), 0.0)
