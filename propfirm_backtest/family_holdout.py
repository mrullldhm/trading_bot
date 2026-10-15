"""ORB families, step 2 of 2: test a family's frozen champion ONCE on 2022 -> today.

Usage:
    python -m propfirm_backtest.family_holdout zab|crabel|acd

Same once-only rules as orb_holdout.py (atomic marker, code + data hash), plus, decided before any
holdout is opened:
- refuses to open the holdout if the champion did not pass every development gate (the verdict
  would already be FAIL; opening it would only spend the one look);
- PASS also needs >= MIN_HOLDOUT_TRADES holdout trades and a block-bootstrap 90% lower bound of the
  mean daily P&L above zero (a positive point estimate alone is weak evidence);
- Strategies 3-5 are one research programme: if more than one family is opened, family_program.py
  applies a Holm correction across them.
"""

import json
import os
import sys

import numpy as np
import pandas as pd

from propfirm_data.eia_calendar import load_releases

from . import bars as B
from . import orb_holdout as H
from . import propsim as P
from .family_search import FAMILIES, family_from_argv

MIN_HOLDOUT_TRADES = 100
BOOT_SIMS = 10_000
BOOT_BLOCK = 5
LOWER_QUANTILE = 0.10
SEED = 2022


def holdout_daily_pnl(t, cal) -> np.ndarray:
    """Daily P&L over every holdout trading day (days without trades count as 0)."""
    hold = t[0] >= cal.n_dev
    pnl = P.trade_pnl_usd(t[3][hold], t[4][hold], t[5][hold])
    days = np.zeros(len(cal.days) - cal.n_dev)
    np.add.at(days, t[0][hold] - cal.n_dev, pnl)
    return days


def bootstrap_means(daily: np.ndarray, seed=SEED) -> np.ndarray:
    """Block-bootstrapped means of the daily P&L (blocks of BOOT_BLOCK days)."""
    n = len(daily)
    rng = np.random.default_rng(seed)
    n_blocks = int(np.ceil(n / BOOT_BLOCK))
    starts = rng.integers(0, n, (BOOT_SIMS, n_blocks))
    idx = (starts[:, :, None] + np.arange(BOOT_BLOCK)) % n
    return daily[idx.reshape(BOOT_SIMS, -1)[:, :n]].mean(axis=1)


def bootstrap_summary(daily: np.ndarray, seed=SEED) -> tuple[float, float]:
    """(10% quantile of the bootstrapped mean daily P&L, share of bootstrapped means <= 0).
    The second number is a bootstrap TAIL PROBABILITY (not a classical p-value); it is what the
    Holm correction in family_program.py uses."""
    if len(daily) == 0:
        return float("nan"), 1.0
    means = bootstrap_means(daily, seed)
    return float(np.quantile(means, LOWER_QUANTILE)), float((means <= 0).mean())


def family_verdict(frozen, ho, t, cal):
    result, ok_dev, ok_ho = H.verdict(frozen, ho)
    lb, tail = bootstrap_summary(holdout_daily_pnl(t, cal))
    ho["mean_daily_pnl_lower_bound"] = lb
    ho["p_value"] = tail  # bootstrap tail probability of mean <= 0
    ok_ho = ok_ho and ho["trades"] >= MIN_HOLDOUT_TRADES and lb > 0
    return ("PASS" if ok_dev and ok_ho else "FAIL"), ok_dev, ok_ho


RULE_TEXT = (f"PASS needs ALL of: the champion passed every development gate and the plateau rule; the "
             f"walk-forward selector made money; PBO < {H.MAX_PBO:.0%}; deflated Sharpe >= {H.MIN_DSR:.0%} at the "
             f"(optimistic) effective trial count; in the holdout: >= {MIN_HOLDOUT_TRADES} trades, profitable also "
             f"with +1 tick slippage, Combine passes > fails, and the 90% block-bootstrap lower bound of the mean "
             f"daily P&L > $0. Across strategies 3-5 a Holm correction applies (family_program.py).")


def main() -> int:
    family = family_from_argv("family_holdout")
    if family is None:
        return 1
    out = family.out_dir
    frozen, code = H.preflight(out, family)
    if frozen is None:
        return code
    if not frozen["champion_eligible"]:
        print("The champion did not pass every development gate, so the verdict is already FAIL.")
        print("Not opening the holdout: it can only be looked at once. Nothing was marked as opened.")
        return 4
    try:
        fd = os.open(out / "holdout_opened.json", os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        print("Holdout already opened by another run.")
        return 2
    with os.fdopen(fd, "w") as fh:
        json.dump({"opened_utc": pd.Timestamp.now(tz="UTC").isoformat(), "source_sha256": frozen["source_sha256"]}, fh, indent=2)
    print("Loading all data (development + holdout)...", flush=True)
    result = H.evaluate(B.load_minutes(), frozen, out, load_releases(), family, family_verdict, RULE_TEXT)
    print(f"\nVerdict: {result}. Report: {out / 'holdout.md'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
