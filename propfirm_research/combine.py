"""Parameterised Topstep Combine simulator: 50K / 100K / 150K, Daily Loss Limit, G8 at 50% of the MLL.

Same model as propfirm_backtest/propsim.py (which is frozen and hard-codes 50K): trading days are
block-bootstrapped (day P&L and intraday low, no-trade days included), the MLL trails the end-of-day peak
and locks at the start balance, an intraday low touching it fails, the target needs best day <= 55% of the
balance, 250 days max, drawdown measured over the first 60 days. With the 50K preset and the DLL off this
returns exactly propsim.pass_probability (tests/test_research_combine.py).

Daily Loss Limit (D005), day level: a day whose intraday low reaches -DLL is closed at -DLL (positions
liquidated, no more trading that day). Liquidation loses dll_slip_ticks per contract beyond the limit.
"""

import math
from dataclasses import dataclass

import numpy as np
from numba import njit, prange

from .stats import wilson_upper

MAX_DAYS = 250
DD_WINDOW = 60
BLOCK = 5


@dataclass(frozen=True)
class Account:
    name: str
    mll: float
    target: float
    dll: float
    cl_limit: int
    consistency: float = 0.55

    @property
    def g8_limit(self) -> float:
        return 0.5 * self.mll  # D003


ACCOUNTS = {
    "50K": Account("50K", 2000.0, 3000.0, 1000.0, 3),
    "100K": Account("100K", 3000.0, 6000.0, 2000.0, 6),
    "150K": Account("150K", 4500.0, 9000.0, 3000.0, 9),
}


def apply_dll(day_pnl: np.ndarray, day_low: np.ndarray, dll: float, slip_usd: float = 0.0
              ) -> tuple[np.ndarray, np.ndarray]:
    """Day-level DLL. Ordering is safe on a continuous path: if the MLL line sits above -DLL the capped low
    still breaches it, otherwise the DLL fires first (R002 discussion). slip_usd = loss beyond the limit
    on liquidation (gaps, slippage); the strategy engines model it minute by minute."""
    hit = day_low <= -dll
    stop = -dll - slip_usd
    return np.where(hit, stop, day_pnl), np.where(hit, stop, day_low)


@njit(cache=False)
def _attempt(day_pnl, day_low, starts, target, mll, consistency):
    """(outcome, days_used, max_dd): outcome 1 pass, -1 fail, 0 out of days."""
    bal = 0.0
    eod_peak = 0.0
    floor = -mll
    best_day = 0.0
    max_dd = 0.0
    n = len(day_pnl)
    d = 0
    for b in range(len(starts)):
        for o in range(BLOCK):
            if d >= MAX_DAYS:
                return 0, d, max_dd
            k = (starts[b] + o) % n
            low = bal + day_low[k]
            if d < DD_WINDOW and eod_peak - low > max_dd:
                max_dd = eod_peak - low
            if low <= floor:
                return -1, d + 1, max_dd
            bal += day_pnl[k]
            if day_pnl[k] > best_day:
                best_day = day_pnl[k]
            if bal > eod_peak:
                eod_peak = bal
                floor = min(eod_peak - mll, 0.0)
            d += 1
            if bal >= target and best_day <= consistency * bal:
                return 1, d, max_dd
    return 0, d, max_dd


@njit(cache=False, parallel=True)
def _simulate(day_pnl, day_low, n_sims, seed, target, mll, consistency):
    """Per run: pass share, fail share, p95 dd, p99 dd, median days of passing attempts (nan if none)."""
    runs, n = day_pnl.shape
    blocks = MAX_DAYS // BLOCK + 1
    out = np.zeros((runs, 5))
    for r in prange(runs):
        np.random.seed(seed)  # same random days for every run, as propsim
        passed = 0
        failed = 0
        dds = np.empty(n_sims)
        pdays = np.empty(n_sims)
        for s in range(n_sims):
            starts = np.random.randint(0, n, blocks)
            res, days, dd = _attempt(day_pnl[r], day_low[r], starts, target, mll, consistency)
            if res == 1:
                pdays[passed] = days
                passed += 1
            elif res == -1:
                failed += 1
            dds[s] = dd
        out[r, 0] = passed / n_sims
        out[r, 1] = failed / n_sims
        out[r, 2] = np.quantile(dds, 0.95)
        out[r, 3] = np.quantile(dds, 0.99)
        out[r, 4] = np.median(pdays[:passed]) if passed > 0 else np.nan
    return out


def odds(day_pnl: np.ndarray, day_low: np.ndarray, account: Account | str = "50K", contracts: float = 1,
         dll: bool = True, reserve: float = 0.0, n_sims: int = 2000, seed: int = 12345,
         dll_slip_ticks: float = 1.0) -> dict:
    """Combine odds for ONE daily series (1-contract P&L and intraday low, $, low <= 0).
    reserve: $ kept aside from the MLL (Codex's candidate rule uses $500).
    dll_slip_ticks: ticks per contract lost beyond the DLL on liquidation."""
    acc = ACCOUNTS[account] if isinstance(account, str) else account
    if not isinstance(contracts, (int, np.integer)) or not 1 <= contracts <= acc.cl_limit:
        raise ValueError(f"contracts must be an integer in 1..{acc.cl_limit} for {acc.name}")
    if not 0 <= reserve < acc.mll:
        raise ValueError("reserve must be in [0, MLL)")
    day_pnl, day_low = np.asarray(day_pnl, float), np.asarray(day_low, float)
    if len(day_pnl) == 0 or day_pnl.shape != day_low.shape:
        raise ValueError("day_pnl and day_low must be non-empty and the same length")
    if not (np.isfinite(day_pnl).all() and np.isfinite(day_low).all()) or (day_low > 1e-9).any():
        raise ValueError("daily series must be finite and day_low <= 0")
    pnl = np.asarray(day_pnl, float) * contracts
    low = np.asarray(day_low, float) * contracts
    hit_share = float((low <= -acc.dll).mean()) if dll else 0.0
    if dll:
        pnl, low = apply_dll(pnl, low, acc.dll, dll_slip_ticks * 10.0 * contracts)
    r = _simulate(pnl[None, :], low[None, :], n_sims, seed, acc.target, acc.mll - reserve, acc.consistency)[0]
    fails = int(round(r[1] * n_sims))
    return {
        "account": acc.name, "contracts": contracts, "dll": dll, "reserve": reserve,
        "pass": float(r[0]), "fail": float(r[1]), "neither": float(1 - r[0] - r[1]),
        "fail_ucb95": wilson_upper(fails, n_sims), "p95_dd": float(r[2]), "p99_dd": float(r[3]),
        "g8_limit": acc.g8_limit, "g8_ok": bool(r[2] <= acc.g8_limit),
        "median_days_pass": float(r[4]) if not math.isnan(r[4]) else float("nan"),
        "dll_hit_days": hit_share,
    }


def simulate_many(day_pnl2d, day_low2d, account="50K", n_sims=2000, seed=12345) -> np.ndarray:
    """Raw kernel over many runs (no DLL, no scaling): columns pass, fail, p95, p99, median days."""
    acc = ACCOUNTS[account] if isinstance(account, str) else account
    return _simulate(np.ascontiguousarray(day_pnl2d, float), np.ascontiguousarray(day_low2d, float),
                     n_sims, seed, acc.target, acc.mll, acc.consistency)
