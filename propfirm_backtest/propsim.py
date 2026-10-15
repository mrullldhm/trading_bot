"""Trade metrics and a Topstep 50K Trading Combine simulator.

Combine rules modelled (verify on Topstep's help center before relying on them):
- Profit target $3,000.
- Maximum Loss Limit $2,000, trailing the highest END-OF-DAY balance, never moving down,
  locking once it reaches the starting balance. Breached if the balance INCLUDING open
  losses touches it during the day.
- Consistency: best day must be <= 55% of total profit when the target is reached;
  otherwise keep trading (the target effectively rises).
- Daily Loss Limit $1,000 (optional, `apply_dll`): positions are liquidated when the day's
  equity (incl. open losses) reaches -$1,000 and the day is over; the attempt goes on.
- Topstep has no time limit. We cap an attempt at MAX_DAYS trading days (~1 year of monthly fees).
- Drawdown (the p95 gate) is measured over the first DD_WINDOW days of an attempt only, so a longer
  horizon changes the pass/fail odds but not what the drawdown gate means.
"""

import numpy as np
from numba import njit, prange

TICK_USD = 10.0
FEE_USD = 4.02  # round turn, TopstepX CL (verify)
TARGET = 3000.0
MLL = 2000.0
DLL = 1000.0
CONSISTENCY = 0.55
MAX_DAYS = 250
DD_WINDOW = 60
BLOCK = 5  # days per bootstrap block (keeps streaks together)


def trade_pnl_usd(direction, px_in, px_out) -> np.ndarray:
    return direction * (px_out - px_in) * TICK_USD - FEE_USD


def apply_dll(day_pnl: np.ndarray, day_low: np.ndarray, dll: float = DLL) -> tuple[np.ndarray, np.ndarray]:
    """Daily Loss Limit: a day whose intraday low reaches -dll is liquidated at -dll and ends there.
    Approximation: the liquidation fills exactly at the limit, and later trades that day are lost."""
    hit = day_low <= -dll
    return np.where(hit, -dll, day_pnl), np.maximum(day_low, -dll)


@njit(cache=True)
def daily_series(day_idx, pnl, mae_usd, n_days):
    """Per calendar day: total P&L and the lowest intraday equity (incl. open-trade losses).
    Trades must be in time order."""
    day_pnl = np.zeros(n_days)
    day_low = np.zeros(n_days)
    for t in range(len(pnl)):
        d = day_idx[t]
        if d < 0:
            continue
        worst = day_pnl[d] - mae_usd[t]  # deepest point while this trade was open
        if worst < day_low[d]:
            day_low[d] = worst
        day_pnl[d] += pnl[t]
        if day_pnl[d] < day_low[d]:
            day_low[d] = day_pnl[d]
    return day_pnl, day_low


@njit(cache=True)
def max_drawdown(day_pnl, day_low):
    """Largest drop from an end-of-day equity peak to an intraday low."""
    eq = 0.0
    peak = 0.0
    worst = 0.0
    for d in range(len(day_pnl)):
        trough = eq + day_low[d]
        if peak - trough > worst:
            worst = peak - trough
        eq += day_pnl[d]
        if eq > peak:
            peak = eq
    return worst


@njit(cache=True)
def _combine_attempt(day_pnl, day_low, start_days, block):
    """One simulated Combine. Returns (outcome, days_used, max_dd).
    outcome: 1 = passed, -1 = hit the MLL, 0 = ran out of days."""
    bal = 0.0
    eod_peak = 0.0
    floor = -MLL
    best_day = 0.0
    max_dd = 0.0
    n = len(day_pnl)
    d = 0
    for b in range(len(start_days)):
        for o in range(block):
            if d >= MAX_DAYS:
                return 0, d, max_dd
            k = (start_days[b] + o) % n
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
                floor = min(eod_peak - MLL, 0.0)  # trails EOD peak, locks at start balance
            d += 1
            if bal >= TARGET and best_day <= CONSISTENCY * bal:
                return 1, d, max_dd
    return 0, d, max_dd


@njit(cache=True, parallel=True)
def pass_probability(day_pnl, day_low, n_sims, seed):
    """Block-bootstrap many Combine attempts from one strategy's daily history.
    day_pnl/day_low: 2-D (runs, days). Returns per run: pass %, fail %, p95 max drawdown."""
    runs, n = day_pnl.shape
    blocks = MAX_DAYS // BLOCK + 1
    out = np.zeros((runs, 3))
    for r in prange(runs):
        np.random.seed(seed)  # same random days for every config: rankings differ only by strategy
        passed = 0
        failed = 0
        dds = np.empty(n_sims)
        for s in range(n_sims):
            starts = np.random.randint(0, n, blocks)
            res, _, dd = _combine_attempt(day_pnl[r], day_low[r], starts, BLOCK)
            if res == 1:
                passed += 1
            elif res == -1:
                failed += 1
            dds[s] = dd
        out[r, 0] = passed / n_sims
        out[r, 1] = failed / n_sims
        out[r, 2] = np.quantile(dds, 0.95)
    return out


def trade_stats(pnl: np.ndarray) -> dict:
    n = len(pnl)
    if n == 0:
        return {"trades": 0, "win_rate": np.nan, "profit_factor": np.nan, "expectancy_usd": np.nan,
                "total_usd": 0.0, "avg_win_over_loss": np.nan, "max_losing_streak": 0}
    wins, losses = pnl[pnl > 0], pnl[pnl <= 0]
    streak = best = 0
    for p in pnl:
        streak = streak + 1 if p <= 0 else 0
        best = max(best, streak)
    return {
        "trades": n,
        "win_rate": len(wins) / n,
        "profit_factor": wins.sum() / -losses.sum() if losses.sum() < 0 else np.inf,
        "expectancy_usd": pnl.mean(),
        "total_usd": pnl.sum(),
        "avg_win_over_loss": wins.mean() / -losses.mean() if len(wins) and losses.mean() < 0 else np.nan,
        "max_losing_streak": best,
    }
