"""Strategy 7 (Momentum Pullback), step 1 of 2: grid + selection on DEVELOPMENT data only (2010-06 -> 2021-12).

Usage:
    python -m propfirm_backtest.momentum_search [--quick]

Same discipline as orb_search (gates, plateau, walk-forward replaying the selector, deflated Sharpe,
PBO, finalists, one frozen champion), run through orb_search.main. Only the kernels differ: this
strategy trades many times a day, and orb_engine.grid_kernel holds at most 2 trades per day.
orb_search.py is part of the frozen source hash of unopened holdouts, so it is not edited; its
Dev class is swapped for MomentumDev while main runs.
Results: data/backtests/momentum/. Step 2 (momentum_holdout) tests the champion ONCE on 2022+.
"""

import contextlib
import sys

import numpy as np
import pandas as pd

from . import momentum_engine as ME
from . import orb_search as O
from . import propsim as P
from . import search as S

DIMS = {
    "tf": ME.TIMEFRAMES,
    "k": [1.5, 2.0, 3.0],
    "w": [0.2, 0.35],
    "min_trend": [1, 2],
    "s": [0.25, 0.4],
    "window": [1, 2, 3],
    "stop_buf": [0, 2],
    "r": [1.0, 1.5, 2.0, 2.5, 3.0, 4.0],
    "max_risk_pct": [0.5, 1.0, 2.0],
    "min_risk": [0, 5],
    "session": ME.SESSION_NAMES,
    "direction": ["both", "long", "short"],
}
NEIGHBOURS = {d: "linear" for d in ["tf", "k", "w", "min_trend", "s", "window", "stop_buf", "r", "max_risk_pct",
                                    "min_risk"]}
QUICK_DIMS = {"tf": [1, 5], "k": [2.0], "w": [0.35], "s": [0.4], "stop_buf": [0], "max_risk_pct": [1.0],
              "min_risk": [0], "session": ["all", "newyork"]}
FAITHFUL_MIN_R = 2.0  # the trader's rule: target at least 2:1; lower R levels are exploratory


def cfg_matrix(grid) -> np.ndarray:
    col = grid.level_codes
    return np.column_stack([
        col("tf", ME.TIMEFRAMES.index), col("k", lambda v: round(v * 10)), col("w", lambda v: round(v * 100)),
        col("min_trend", int), col("s", lambda v: round(v * 100)), col("window", int), col("stop_buf", int),
        col("r", lambda v: round(v * 10)), col("max_risk_pct", lambda v: round(v * 100)), col("min_risk", int),
        col("session", ME.SESSION_NAMES.index), col("direction", {"both": ME.BOTH, "long": ME.LONG, "short": ME.SHORT}.get),
    ])


def label(row) -> str:
    return (f"{row['tf']}m / momentum {row['k']}x avg body, wick <= {row['w']} / >= {row['min_trend']} trend / "
            f"small <= {row['s']} x M / window {row['window']} / stop buf {row['stop_buf']} / {row['r']}R / "
            f"risk <= {row['max_risk_pct']}% / min risk {row['min_risk']} / {row['session']} / {row['direction']}")


MOMENTUM = O.Family(
    name="momentum", title="Momentum Pullback", dims=DIMS, neighbours=NEIGHBOURS, cfg_matrix=cfg_matrix,
    market=ME.Market, label=label, best_per=["tf", "r", "session", "direction"], quick_dims=QUICK_DIMS,
    notes=["Rules: see the docstring of propfirm_backtest/momentum_engine.py. 1 CL per trade; 'risk <= X%' "
           "skips setups whose planned loss (stop distance + 2 ticks slippage, plus fee) exceeds X% of $50,000.",
           f"R below {FAITHFUL_MIN_R:.0f} is exploratory (the trader's rule is at least 2:1); the faithful-only "
           "champion is listed at the end.",
           "The trader's example charts are XAUUSD and EURUSD; this tests the pattern on CL only.",
           "Entry window 1/2/3 mostly gives identical trades: the bar after S either fills, ends the chain "
           "or becomes the new S (which restarts the window).", ""],
    # family_holdout.py holds the holdout verdict; family_search.py is imported by it
    extra_sources=["momentum_engine.py", "momentum_search.py", "momentum_holdout.py", "family_holdout.py",
                   "family_search.py"],
    holdout_cmd="python -m propfirm_backtest.momentum_holdout")


class MomentumDev(O.Dev):
    """orb_search.Dev with the whole-series kernels of momentum_engine."""

    def kernel(self, cfgs, slip, score, pessimistic=True):
        return ME.grid_kernel(np.asarray(cfgs, np.int64), self.n, self.year_of_day, len(self.years), self.fold_ends,
                              self.hash_w, self.mk.bar_args(), self.mk.minute_args(), float(slip), pessimistic,
                              self.u, self.u_wf, P.BLOCK, score)

    def daily(self, cfgs, slip=O.BASE_SLIP, pessimistic=True):
        return ME.daily_kernel(np.asarray(cfgs, np.int64), self.n, self.mk.bar_args(), self.mk.minute_args(),
                               float(slip), pessimistic)


@contextlib.contextmanager
def momentum_dev():
    saved = O.Dev
    O.Dev = MomentumDev
    try:
        yield
    finally:
        O.Dev = saved


def faithful_section(out_dir) -> list[str]:
    """Best configs with R >= FAITHFUL_MIN_R (same ranking as the main table)."""
    df = pd.read_csv(out_dir / "results.csv.gz")
    f = df[(df["r"] >= FAITHFUL_MIN_R) & df["rank"].notna()].sort_values("rank").head(10)
    L = ["", f"## Faithful rules only (R >= {FAITHFUL_MIN_R:.0f}): top 10 by the same ranking", "",
         "| Rank | Settings | Trades | Expectancy | +1 tick | PF | Pass % | p95 DD | Eligible |",
         "|---|---|---|---|---|---|---|---|---|"]
    fmt = S.fmt
    for _, r in f.iterrows():
        L.append(f"| {int(r['rank'])} | {label(r)} | {int(r['trades'])} | {fmt(r['expectancy_usd'], money=True)} | "
                 f"{fmt(r['expectancy_slip2'], money=True)} | {fmt(r['profit_factor'])} | {fmt(r['pass_prob'], pct=True)} | "
                 f"{fmt(r['p95_drawdown'], money=True)} | {'yes' if r['eligible'] else 'no'} |")
    return L


def main(argv=None) -> int:
    argv = sys.argv if argv is None else argv
    with momentum_dev():
        code = O.main(MOMENTUM, argv)
    if code == 0:
        out_dir = MOMENTUM.out_dir.parent / "momentum_quick" if "--quick" in argv else MOMENTUM.out_dir
        rep = out_dir / "report.md"
        rep.write_text(rep.read_text() + "\n".join(faithful_section(out_dir)) + "\n")
    return code


if __name__ == "__main__":
    sys.exit(main())
