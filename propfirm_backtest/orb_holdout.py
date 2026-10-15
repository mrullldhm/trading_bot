"""ORB, step 2 of 2: test the frozen champion ONCE on 2022 -> today.

Usage:
    python -m propfirm_backtest.orb_holdout

Refuses to run if:
- there is no frozen champion (run propfirm_backtest.orb_search first) or it came from --quick,
- the strategy code or its reference data changed after the champion was frozen,
- the holdout was already opened (a second look is no longer an unbiased test),
- an input it needs is missing (checked BEFORE the holdout is marked as opened).

Caveat: 2022+ was already looked at for Strategy 1 (EMA x VWAP), so this is an "ORB confirmation
set", not pristine data. Forward paper trading is the real out-of-sample test.
"""

import json
import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd

from propfirm_data.config import BARS_DIR, DEFINITIONS_FILE
from propfirm_data.eia_calendar import load_releases

from . import bars as B
from . import orb_engine as E
from . import orb_search as O
from . import search as S

HOLDOUT_SLIPS = [2.0, 3.0, 4.0]
MIN_DSR = 0.95
MAX_PBO = 0.5


def preflight(out: Path) -> tuple[dict | None, int]:
    """(frozen picks, 0) when the holdout may be opened, else (None, exit code)."""
    picks_file, marker = out / "frozen_picks.json", out / "holdout_opened.json"
    if not picks_file.exists():
        print("No frozen champion. Run: python -m propfirm_backtest.orb_search")
        return None, 1
    frozen = json.loads(picks_file.read_text())
    if frozen.get("quick"):
        print("The frozen champion comes from a --quick smoke run. Run the full search first.")
        return None, 1
    if marker.exists():
        print(f"Holdout already opened on {json.loads(marker.read_text())['opened_utc']}.")
        print(f"Results: {out / 'holdout.md'}. A second look would not be an unbiased test.")
        return None, 2
    if frozen["source_sha256"] != O.source_hash():
        print("Strategy code or reference data changed after the champion was frozen. Re-run the search first.")
        return None, 3
    missing = [str(p) for p in [BARS_DIR, DEFINITIONS_FILE] if not p.exists()]
    if missing:
        print(f"Missing inputs: {missing}")
        return None, 1
    load_releases()  # raises if the EIA calendar is missing
    return frozen, 0


def verdict(frozen: dict, ho: dict) -> tuple[str, bool, bool]:
    """(PASS/FAIL, development checks ok, holdout checks ok). Rules fixed before the holdout opens."""
    ok_dev = (frozen["champion_eligible"] and frozen["walk_forward_total_usd"] > 0
              and frozen["pbo"] < MAX_PBO and frozen["deflated_sharpe_effective"] >= MIN_DSR)
    ok_ho = (ho["expectancy_usd"] > 0 and ho["stress"][2.0]["expectancy_usd"] > 0
             and ho["pass_prob"] > ho["fail_prob"])
    return ("PASS" if ok_dev and ok_ho else "FAIL"), ok_dev, ok_ho


def evaluate(m, frozen: dict, out: Path, eia) -> str:
    """Run the champion on all data, save raw results first, then the report. Returns the verdict."""
    cal = S.Calendar(m)
    mk = E.Market(m, cal.days, eia, strict_expiry=True)
    print(f"  holdout: {len(cal.days) - cal.n_dev:,} trading days", flush=True)
    cfg = np.array(frozen["champion_cfg"], dtype=np.int64)
    t = mk.trades(cfg)
    O.write_trades(t, mk, m, cal, out / "champion_trades.csv")
    ho = S.period_stats(O.to_minute_rows(mk, t), m, cal, "holdout")
    ho["stress"] = {s: S.period_stats(O.to_minute_rows(mk, mk.trades(cfg, slip=s)), m, cal, "holdout")
                    for s in HOLDOUT_SLIPS}
    result, _, _ = verdict(frozen, ho)
    (out / "holdout_raw.json").write_text(json.dumps({"verdict": result, "stats": ho}, indent=2, default=float))
    write_report(frozen, ho, result, out)
    return result


def main() -> int:
    out = O.OUT_DIR
    frozen, code = preflight(out)
    if frozen is None:
        return code
    # Marker FIRST and atomically (O_EXCL): even a crashed or concurrent run counts as opened.
    try:
        fd = os.open(out / "holdout_opened.json", os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        print("Holdout already opened by another run.")
        return 2
    with os.fdopen(fd, "w") as fh:
        json.dump({"opened_utc": pd.Timestamp.now(tz="UTC").isoformat(), "source_sha256": frozen["source_sha256"]}, fh, indent=2)

    print("Loading all data (development + holdout)...", flush=True)
    result = evaluate(B.load_minutes(), frozen, out, load_releases())
    print(f"\nVerdict: {result}. Report: {out / 'holdout.md'}")
    return 0


def write_report(frozen: dict, ho: dict, result: str, out: Path):
    fmt = S.fmt
    L = ["# ORB: holdout results (2022 -> today), opened once", "",
         f"Opened {pd.Timestamp.now(tz='UTC'):%Y-%m-%d %H:%M} UTC. Champion frozen {frozen['created_utc'][:16]} UTC.", "",
         "Caveat: 2022+ was already viewed for Strategy 1, so this is an ORB confirmation set, not pristine data.", "",
         f"## Verdict: **{result}**", "",
         f"PASS needs ALL of: the champion passed every development gate and the plateau rule; the walk-forward "
         f"selector made money; PBO < {MAX_PBO:.0%}; deflated Sharpe >= {MIN_DSR:.0%} at the (optimistic) effective "
         f"trial count; in the holdout the champion is profitable, also with +1 tick slippage, and passes the "
         f"Combine more often than it fails.", "",
         f"- Champion eligible in development: {'yes' if frozen['champion_eligible'] else '**no**'}",
         f"- Walk-forward selector P&L (2014-2021): {fmt(frozen['walk_forward_total_usd'], money=True)}",
         f"- PBO: {fmt(frozen['pbo'], pct=True)}; deflated Sharpe: {fmt(frozen['deflated_sharpe_unique'], pct=True)} "
         f"(unique trials), {fmt(frozen['deflated_sharpe_effective'], pct=True)} (effective trials)", "",
         f"## Champion: {O.label(frozen['champion'])}", ""] + S.benchmark_table(ho)
    L += ["", "### Slippage stress (holdout)", "", "| Slippage / side | Expectancy | PF | Pass % |", "|---|---|---|---|",
          f"| 1 tick (base) | {fmt(ho['expectancy_usd'], money=True)} | {fmt(ho['profit_factor'])} | {fmt(ho['pass_prob'], pct=True)} |"]
    for s, st in ho["stress"].items():
        L.append(f"| {int(s)} ticks | {fmt(st['expectancy_usd'], money=True)} | {fmt(st['profit_factor'])} | {fmt(st['pass_prob'], pct=True)} |")
    L += ["", "### P&L by year (holdout)", "", "| Year | P&L |", "|---|---|"]
    L += [f"| {y} | {fmt(v, money=True)} |" for y, v in ho["by_year"].items()]
    L += ["", "Champion trades (development + holdout): `champion_trades.csv`. Raw numbers: `holdout_raw.json`."]
    (out / "holdout.md").write_text("\n".join(L))


if __name__ == "__main__":
    sys.exit(main())
