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

from .stats import mean_upper, stationary_bootstrap_indices, wilson_upper

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
    """(outcome, days_used, max_dd, max_dd_account): outcome 1 pass, -1 fail, 0 out of days.
    max_dd follows propsim (the strategy's own low, even past the MLL line); max_dd_account stops the
    failing day at the MLL line, where the account is liquidated (R004 #5)."""
    bal = 0.0
    eod_peak = 0.0
    floor = -mll
    best_day = 0.0
    max_dd = 0.0
    max_acc = 0.0
    n = len(day_pnl)
    d = 0
    for b in range(len(starts)):
        for o in range(BLOCK):
            if d >= MAX_DAYS:
                return 0, d, max_dd, max_acc
            k = (starts[b] + o) % n
            low = bal + day_low[k]
            if d < DD_WINDOW:
                max_dd = max(max_dd, eod_peak - low)
                max_acc = max(max_acc, eod_peak - max(low, floor))
            if low <= floor:
                return -1, d + 1, max_dd, max_acc
            bal += day_pnl[k]
            if day_pnl[k] > best_day:
                best_day = day_pnl[k]
            if bal > eod_peak:
                eod_peak = bal
                floor = min(eod_peak - mll, 0.0)
            d += 1
            if bal >= target and best_day <= consistency * bal:
                return 1, d, max_dd, max_acc
    return 0, d, max_dd, max_acc


@njit(cache=False, parallel=True)
def _simulate(day_pnl, day_low, n_sims, seeds, target, mll, consistency):
    """Per run: pass share, fail share, p95 dd, p99 dd, median days of passing attempts (nan if none),
    p95 / p99 of the account-level dd. seeds: one bootstrap seed per run."""
    runs, n = day_pnl.shape
    blocks = MAX_DAYS // BLOCK + 1
    out = np.zeros((runs, 7))
    for r in prange(runs):
        np.random.seed(seeds[r])  # propsim: the same seed (same random days) for every run
        passed = 0
        failed = 0
        dds = np.empty(n_sims)
        acc_dds = np.empty(n_sims)
        pdays = np.empty(n_sims)
        for s in range(n_sims):
            starts = np.random.randint(0, n, blocks)
            res, days, dd, acc_dd = _attempt(day_pnl[r], day_low[r], starts, target, mll, consistency)
            if res == 1:
                pdays[passed] = days
                passed += 1
            elif res == -1:
                failed += 1
            dds[s] = dd
            acc_dds[s] = acc_dd
        out[r, 0] = passed / n_sims
        out[r, 1] = failed / n_sims
        out[r, 2] = np.quantile(dds, 0.95)
        out[r, 3] = np.quantile(dds, 0.99)
        out[r, 4] = np.median(pdays[:passed]) if passed > 0 else np.nan
        out[r, 5] = np.quantile(acc_dds, 0.95)
        out[r, 6] = np.quantile(acc_dds, 0.99)
    return out


def _validate(day_pnl, day_low, acc, contracts, reserve, n_sims):
    if not isinstance(n_sims, (int, np.integer)) or n_sims <= 0:
        raise ValueError("n_sims must be a positive integer")
    if not isinstance(contracts, (int, np.integer)) or not 1 <= contracts <= acc.cl_limit:
        raise ValueError(f"contracts must be an integer in 1..{acc.cl_limit} for {acc.name}")
    if not 0 <= reserve < acc.mll:
        raise ValueError("reserve must be in [0, MLL)")
    if len(day_pnl) == 0 or day_pnl.shape != day_low.shape:
        raise ValueError("day_pnl and day_low must be non-empty and the same length")
    if not (np.isfinite(day_pnl).all() and np.isfinite(day_low).all()):
        raise ValueError("daily series must be finite")
    if (day_low > np.minimum(day_pnl, 0.0) + 1e-9).any():  # R004 #1: the close is on the path
        raise ValueError("day_low must be <= min(0, day_pnl)")


def odds(day_pnl: np.ndarray, day_low: np.ndarray, account: Account | str = "50K", contracts: int = 1,
         dll: bool = True, reserve: float = 0.0, n_sims: int = 2000, seed: int = 12345,
         dll_slip_ticks: float = 1.0) -> dict:
    """Combine odds for ONE daily series (1-contract P&L and intraday low, $, low <= 0).
    reserve: $ kept aside from the MLL (Codex's candidate rule uses $500).
    dll_slip_ticks: ticks per contract lost beyond the DLL on liquidation."""
    acc = ACCOUNTS[account] if isinstance(account, str) else account
    day_pnl, day_low = np.asarray(day_pnl, float), np.asarray(day_low, float)
    _validate(day_pnl, day_low, acc, contracts, reserve, n_sims)
    pnl = np.asarray(day_pnl, float) * contracts
    low = np.asarray(day_low, float) * contracts
    hit_share = float((low <= -acc.dll).mean()) if dll else 0.0
    if dll:
        pnl, low = apply_dll(pnl, low, acc.dll, dll_slip_ticks * 10.0 * contracts)
    r = _simulate(pnl[None, :], low[None, :], n_sims, np.array([seed]), acc.target, acc.mll - reserve,
                  acc.consistency)[0]
    fails = int(round(r[1] * n_sims))
    return {
        "account": acc.name, "contracts": contracts, "dll": dll, "reserve": reserve,
        "pass": float(r[0]), "fail": float(r[1]), "neither": float(1 - r[0] - r[1]),
        "fail_ucb95": wilson_upper(fails, n_sims), "p95_dd": float(r[2]), "p99_dd": float(r[3]),
        "g8_limit": acc.g8_limit, "g8_ok": bool(r[2] <= acc.g8_limit),
        "median_days_pass": float(r[4]) if not math.isnan(r[4]) else float("nan"),
        "dll_hit_days": hit_share, "p95_dd_account": float(r[5]), "p99_dd_account": float(r[6]),
    }


def simulate_many(day_pnl2d, day_low2d, account="50K", n_sims=2000, seed=12345) -> np.ndarray:
    """Raw kernel over many runs (no DLL, no scaling): columns pass, fail, p95, p99, median days,
    account-level p95, p99."""
    acc = ACCOUNTS[account] if isinstance(account, str) else account
    runs = np.asarray(day_pnl2d).shape[0]
    return _simulate(np.ascontiguousarray(day_pnl2d, float), np.ascontiguousarray(day_low2d, float),
                     n_sims, np.full(runs, seed), acc.target, acc.mll, acc.consistency)


def odds_many(day_pnl2d: np.ndarray, day_low2d: np.ndarray, account: Account | str = "50K", contracts: int = 1,
              dll: bool = True, reserve: float = 0.0, n_sims: int = 2000, seeds=None,
              dll_slip_ticks: float = 1.0) -> dict:
    """`odds` for many 1-contract daily series at once (rows = runs), one bootstrap seed per run
    (default 12345 for all, as `odds`). Returns arrays keyed like `odds`; row r equals odds(row r)."""
    acc = ACCOUNTS[account] if isinstance(account, str) else account
    pnl = np.atleast_2d(np.asarray(day_pnl2d, float))
    low = np.atleast_2d(np.asarray(day_low2d, float))
    if pnl.shape != low.shape:
        raise ValueError("day_pnl2d and day_low2d must have the same shape")
    for p_, l_ in zip(pnl, low):  # same validation as odds, per row
        _validate(p_, l_, acc, contracts, reserve, n_sims)
    if seeds is None:
        seeds = np.full(len(pnl), 12345)
    seeds = np.asarray(seeds)
    if seeds.shape != (len(pnl),) or not np.issubdtype(seeds.dtype, np.integer):
        raise ValueError("seeds must be one integer per run")
    seeds = seeds.astype(np.int64)
    pnl, low = pnl * contracts, low * contracts
    hit = (low <= -acc.dll).mean(axis=1) if dll else np.zeros(len(pnl))
    if dll:
        pnl, low = apply_dll(pnl, low, acc.dll, dll_slip_ticks * 10.0 * contracts)
    r = _simulate(np.ascontiguousarray(pnl), np.ascontiguousarray(low), n_sims, seeds, acc.target,
                  acc.mll - reserve, acc.consistency)
    fails = np.rint(r[:, 1] * n_sims).astype(int)
    return {"pass": r[:, 0], "fail": r[:, 1], "neither": 1 - r[:, 0] - r[:, 1], "fails": fails,
            "fail_ucb95": np.array([wilson_upper(int(f), n_sims) for f in fails]),
            "p95_dd": r[:, 2], "p99_dd": r[:, 3], "g8_ok": r[:, 2] <= acc.g8_limit,
            "median_days_pass": r[:, 4], "dll_hit_days": hit,
            "p95_dd_account": r[:, 5], "p99_dd_account": r[:, 6]}


G8_PASS_MIN = 0.50  # D006 option 2 (owner, 2026-10-17)
G8_FAIL_UCB_MAX = 0.10
G8_RESERVE = 500.0


def gate_g8(day_pnl_stress: np.ndarray, day_low_stress: np.ndarray, account: Account | str = "50K",
            contracts: int = 1, n_sims: int = 2000, seed: int = 12345, n_outer: int = 20,
            outer_sims: int = 500, mean_block: float = 20.0) -> dict:
    """G8 as decided in D006: on the STRESS-cost daily series, with a $500 reserve and the DLL on,
    pass >= 50% and the upper 95% bound of P(fail) <= 10%. The bound is the larger of the Wilson bound over
    the attempts and a one-sided t bound over `n_outer` stationary-bootstrap resamples of the strategy's own
    day series (R010 #9: a lucky history must not pass on the Combine simulation's error alone).
    n_outer = 0 gives a diagnostic result that can never pass. Drawdowns are reported, not gated."""
    pnl = np.asarray(day_pnl_stress, float)
    low = np.asarray(day_low_stress, float)
    o = odds(pnl, low, account, contracts, dll=True, reserve=G8_RESERVE, n_sims=n_sims, seed=seed)
    rng = np.random.default_rng(seed)
    outer = []
    for k in range(n_outer):
        i = stationary_bootstrap_indices(len(pnl), mean_block, rng)
        outer.append(odds(pnl[i], low[i], account, contracts, dll=True, reserve=G8_RESERVE, n_sims=outer_sims,
                          seed=seed + 1 + k)["fail"])
    ucb = max(o["fail_ucb95"], mean_upper(outer)) if n_outer >= 2 else float("nan")
    o.update(fail_ucb95_gate=ucb, outer_fail_mean=float(np.mean(outer)) if outer else float("nan"),
             n_outer=n_outer, g8_pass_ok=o["pass"] >= G8_PASS_MIN, g8_fail_ok=bool(ucb <= G8_FAIL_UCB_MAX))
    o["g8_ok"] = bool(n_outer >= 2 and o["g8_pass_ok"] and o["g8_fail_ok"])
    o["g8_rule"] = "D006"
    return o
