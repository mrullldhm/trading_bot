"""Strategy 8 (Pine 1-Minute Momentum), step 1 of 2: grid + selection on DEVELOPMENT data only (2010-06 -> 2021-12).

Usage:
    python -m propfirm_backtest.momentum2_search [--quick]

Same discipline as orb_search (gates, plateau, walk-forward replaying the selector, deflated Sharpe,
PBO, finalists, one frozen champion), run through orb_search.main with momentum2_engine's whole-series
kernels swapped in (as momentum_search does). The grid uses project fills; the report adds the Pine
script's own settings with TradingView-style fills (chart-bar path, touch fills, 0 slippage) next to them.
Results: data/backtests/momentum2/. Step 2 (momentum2_holdout) tests the champion ONCE on 2022+.
"""

import contextlib
import sys

import numpy as np
import pandas as pd

from propfirm_data.eia_calendar import load_releases

from . import bars as B
from . import momentum2_engine as ME
from . import orb_search as O
from . import propsim as P
from . import search as S

DIMS = {
    "tf": ME.TIMEFRAMES,
    "mult": [1.5, 2.0, 3.0],
    "body_pct": [0.3, 10.0, 20.0, 30.0, 40.0],
    "rr": [1.0, 1.5, 2.0, 3.0, 4.0],
    "mom_dir": ME.MOM_DIR_NAMES,
    "mgmt": ME.MGMT_NAMES,
    "stop_buf": [0, 2],
    "min_risk": [0, 5, 10],
    "session": ME.SESSION_NAMES,
    "direction": ["both", "long", "short"],
}
NEIGHBOURS = {d: "linear" for d in ["tf", "mult", "body_pct", "rr", "stop_buf", "min_risk"]}
QUICK_DIMS = {"tf": [1, 5], "mult": [1.5], "body_pct": [0.3, 30.0], "stop_buf": [0], "min_risk": [0, 5],
              "session": ["all", "newyork"]}
PINE = dict(tf=1, mult=1.5, body_pct=0.3, rr=2.0, mom_dir="any", mgmt="tv", stop_buf=0, min_risk=0,
            session="all", direction="both")


def cfg_matrix(grid) -> np.ndarray:
    col = grid.level_codes
    return np.column_stack([
        col("tf", ME.TIMEFRAMES.index), col("mult", lambda v: round(v * 10)), col("body_pct", lambda v: round(v * 10)),
        col("rr", lambda v: round(v * 10)), col("mom_dir", ME.MOM_DIR_NAMES.index), col("mgmt", ME.MGMT_NAMES.index),
        col("stop_buf", int), col("min_risk", int), col("session", ME.SESSION_NAMES.index),
        col("direction", {"both": ME.BOTH, "long": ME.LONG, "short": ME.SHORT}.get),
        col("tf", lambda v: 0),  # fill = project
    ])


def label(row) -> str:
    return (f"{row['tf']}m / momentum > {row['mult']}x prior body ({row['mom_dir']}) / body < {row['body_pct']}% / "
            f"{row['rr']}R / mgmt {row['mgmt']} / stop buf {row['stop_buf']} / min risk {row['min_risk']} / "
            f"{row['session']} / {row['direction']}")


MOMENTUM2 = O.Family(
    name="momentum2", title="Pine 1-Minute Momentum", dims=DIMS, neighbours=NEIGHBOURS, cfg_matrix=cfg_matrix,
    market=ME.Market, label=label, best_per=["tf", "body_pct", "rr", "mgmt", "session"], quick_dims=QUICK_DIMS,
    notes=["Rules: see the docstring of propfirm_backtest/momentum2_engine.py. 1 CL per trade, project fills "
           "(1 tick slippage per side, $4.02 fee, stop wins inside a minute, targets need a 1-tick trade-through).",
           "body_pct 0.3 is the script's literal default (0.3% of the range: almost never true); 10-40 test the "
           "likely intent.",
           "mgmt tv = TradingView with pyramiding 1 (same-direction signals move the bracket, opposite ones "
           "reverse); ignore = no new signal while in a trade.", ""],
    extra_sources=["momentum_engine.py", "momentum2_engine.py", "momentum2_search.py", "momentum2_holdout.py",
                   "family_holdout.py", "family_search.py"],
    holdout_cmd="python -m propfirm_backtest.momentum2_holdout")


class Momentum2Dev(O.Dev):
    """orb_search.Dev with the whole-series kernels of momentum2_engine."""

    def kernel(self, cfgs, slip, score, pessimistic=True):
        return ME.grid_kernel(np.asarray(cfgs, np.int64), self.n, self.year_of_day, len(self.years), self.fold_ends,
                              self.hash_w, self.mk.bar_args(), self.mk.minute_args(), float(slip), pessimistic,
                              self.u, self.u_wf, P.BLOCK, score)

    def daily(self, cfgs, slip=O.BASE_SLIP, pessimistic=True):
        return ME.daily_kernel(np.asarray(cfgs, np.int64), self.n, self.mk.bar_args(), self.mk.minute_args(),
                               float(slip), pessimistic)


@contextlib.contextmanager
def momentum2_dev():
    saved = O.Dev
    O.Dev = Momentum2Dev
    try:
        yield
    finally:
        O.Dev = saved


def summary(t, n_days) -> dict:
    """Trades -> headline numbers (net of the $4.02 fee; 'gross' adds the fee back)."""
    pnl = P.trade_pnl_usd(t[3], t[4], t[5])
    n = len(pnl)
    win, loss = pnl[pnl > 0].sum(), -pnl[pnl <= 0].sum()
    return {"trades": n, "per_day": n / n_days, "net_usd": pnl.sum(), "exp_usd": pnl.mean() if n else np.nan,
            "gross_exp_usd": pnl.mean() + P.FEE_USD if n else np.nan, "win_rate": (pnl > 0).mean() if n else np.nan,
            "pf": win / loss if loss > 0 else np.nan}


def pine_section(out_dir) -> list[str]:
    """The script's own settings (and the 30% twin) under project and TradingView-style fills, dev data only."""
    m = B.load_minutes(end=O.DEV_END)
    cal = S.Calendar(m)
    mk = ME.Market(m, cal.days, load_releases(), strict_expiry=True)
    rows = []
    for name, body in [("Pine literal (body < 0.3%)", 0.3), ("Pine, body < 30%", 30.0)]:
        for fill, slip in [("project", 1.0), ("project", 0.0), ("tv", 0.0)]:
            cfg = ME.config(**(PINE | {"body_pct": body, "fill": fill}))
            rows.append((name, fill, slip, summary(mk.trades(cfg, n_days=cal.n_dev, slip=slip), cal.n_dev)))
    fmt = S.fmt
    L = ["", "## The script's own settings (1 min, momentum 1.5x, 2R, mgmt tv, all hours, both directions)", "",
         "| Settings | Fills | Slippage | Trades | Per day | Net | Expectancy | Before fee | Win rate | PF |",
         "|---|---|---|---|---|---|---|---|---|---|"]
    for name, fill, slip, s in rows:
        L.append(f"| {name} | {fill} | {slip:.0f} | {s['trades']} | {s['per_day']:.2f} | {fmt(s['net_usd'], money=True)} | "
                 f"{fmt(s['exp_usd'], money=True)} | {fmt(s['gross_exp_usd'], money=True)} | "
                 f"{fmt(s['win_rate'], pct=True)} | {fmt(s['pf'])} |")
    L += ["", "TradingView fills: one step per chart bar, open-high-low-close path when the open is nearer the "
          "high, touch fills, gaps fill at the open. Still 1 CL, $4.02 fee, flat 16:09 ET, EIA blocks."]
    return L


def main(argv=None) -> int:
    argv = sys.argv if argv is None else argv
    with momentum2_dev():
        code = O.main(MOMENTUM2, argv)
    if code == 0:
        out_dir = MOMENTUM2.out_dir.parent / "momentum2_quick" if "--quick" in argv else MOMENTUM2.out_dir
        rep = out_dir / "report.md"
        rep.write_text(rep.read_text() + "\n".join(pine_section(out_dir)) + "\n")
    return code


if __name__ == "__main__":
    sys.exit(main())
