"""EMA x VWAP, step 2 of 2: test the frozen picks ONCE on unseen data (2022 -> today).

Usage:
    python -m propfirm_backtest.holdout

Refuses to run if:
- there are no frozen picks (run propfirm_backtest.search first),
- the strategy code changed after the picks were frozen (the picks would no longer match),
- the holdout was already opened (a second look is no longer an unbiased test).
"""

import json
import os
import sys

import numpy as np
import pandas as pd

from . import bars as B
from . import engine as E
from . import propsim as P
from . import search as S


def main() -> int:
    out = S.OUT_DIR
    picks_file, marker = out / "frozen_picks.json", out / "holdout_opened.json"
    if not picks_file.exists():
        print("No frozen picks. Run: python -m propfirm_backtest.search")
        return 1
    if marker.exists():
        print(f"Holdout already opened on {json.loads(marker.read_text())['opened_utc']}.")
        print(f"Results: {out / 'holdout.md'}. A second look would not be an unbiased test.")
        return 2
    frozen = json.loads(picks_file.read_text())
    if frozen["source_sha256"] != S.source_hash():
        print("Strategy code changed after the picks were frozen. Re-run the search first.")
        return 3

    # Create the marker FIRST and atomically (O_EXCL): even if this run crashes, or two runs
    # start together, the holdout counts as opened exactly once.
    try:
        fd = os.open(marker, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        print("Holdout already opened by another run.")
        return 2
    with os.fdopen(fd, "w") as fh:
        json.dump({"opened_utc": pd.Timestamp.now(tz="UTC").isoformat(), "source_sha256": frozen["source_sha256"]}, fh, indent=2)

    print("Loading all data (development + holdout)...", flush=True)
    m = B.load_minutes()
    cal = S.Calendar(m)
    print(f"  holdout: {len(cal.days) - cal.n_dev:,} trading days", flush=True)

    results = []
    for n, pick in enumerate(frozen["picks"], 1):
        cfg = tuple(pick[k] for k in S.KEYS)
        t = S.single(m, cal, cfg)
        ho = S.period_stats(t, m, cal, "holdout")
        ho["stress"] = {s: S.period_stats(S.single(m, cal, cfg, slip=s), m, cal, "holdout") for s in [2.0] + S.STRESS_SLIPS}
        results.append((cfg, ho))
        if n == 1:
            write_trades(t, m, cal, out / "champion_trades.csv")
        print(f"  #{n} {S.label(pick)}: {ho['trades']} trades, expectancy {S.fmt(ho['expectancy_usd'], money=True)}", flush=True)

    champ = results[0][1]
    ok_dev = frozen["champion_passed_gates"] and frozen["walk_forward_total_usd"] > 0
    ok_ho = champ["expectancy_usd"] > 0 and champ["stress"][2.0]["expectancy_usd"] > 0 and champ["pass_prob"] > champ["fail_prob"]
    verdict = "PASS" if ok_dev and ok_ho else "FAIL"

    L = ["# EMA x VWAP: holdout results (2022 -> today), opened once", "",
         f"Opened {pd.Timestamp.now(tz='UTC'):%Y-%m-%d %H:%M} UTC. Picks frozen {frozen['created_utc'][:16]} UTC.", "",
         f"## Verdict: **{verdict}**", "",
         "PASS needs ALL of: the champion passed every development gate; the walk-forward selection method made money; "
         "the champion is profitable in the holdout, also with +1 tick slippage, and passes the Combine more often than it fails.", "",
         f"- Champion passed every development gate: {'yes' if frozen['champion_passed_gates'] else '**no**'}",
         f"- Walk-forward selection method P&L (2014-2021): {S.fmt(frozen['walk_forward_total_usd'], money=True)}",
         f"- Deflated Sharpe (conservative): {S.fmt(frozen['deflated_sharpe'], pct=True)}", "",
         "## All frozen picks on the holdout", "",
         "| # | Settings | Trades | Expectancy | PF | Pass % | Fail % | +1 tick exp. |", "|---|---|---|---|---|---|---|---|"]
    for n, (cfg, ho) in enumerate(results, 1):
        L.append(f"| {n} | {S.label(dict(zip(S.KEYS, cfg)))} | {ho['trades']} | {S.fmt(ho['expectancy_usd'], money=True)} | "
                 f"{S.fmt(ho['profit_factor'])} | {S.fmt(ho['pass_prob'], pct=True)} | {S.fmt(ho['fail_prob'], pct=True)} | "
                 f"{S.fmt(ho['stress'][2.0]['expectancy_usd'], money=True)} |")
    L += ["", f"## Champion: {S.label(frozen['picks'][0])}", ""] + S.benchmark_table(champ)
    L += ["", "### Slippage stress (holdout)", "", "| Slippage / side | Expectancy | PF | Pass % |", "|---|---|---|---|",
          f"| 1 tick (base) | {S.fmt(champ['expectancy_usd'], money=True)} | {S.fmt(champ['profit_factor'])} | {S.fmt(champ['pass_prob'], pct=True)} |"]
    for s, st in champ["stress"].items():
        L.append(f"| {int(s)} ticks | {S.fmt(st['expectancy_usd'], money=True)} | {S.fmt(st['profit_factor'])} | {S.fmt(st['pass_prob'], pct=True)} |")
    L += ["", "### P&L by year (holdout)", "", "| Year | P&L |", "|---|---|"]
    L += [f"| {y} | {S.fmt(v, money=True)} |" for y, v in champ["by_year"].items()]
    L += ["", "Champion trades (development + holdout): `champion_trades.csv`."]
    (out / "holdout.md").write_text("\n".join(L))
    print(f"\nVerdict: {verdict}. Report: {out / 'holdout.md'}")
    return 0


def write_trades(t, m, cal, path):
    pnl = P.trade_pnl_usd(t[2], t[3], t[4])
    pd.DataFrame({
        "entry_time_utc": pd.to_datetime(m.ts[t[0]], utc=True),
        "exit_time_utc": pd.to_datetime(m.ts[t[1]], utc=True),
        "contract": [m.contracts[c] for c in m.contract[t[0]]],
        "direction": np.where(t[2] > 0, "long", "short"),
        "entry_ticks": t[3], "exit_ticks": t[4], "mae_ticks": t[5],
        "exit_reason": [E.EXIT_NAMES[int(w)] for w in t[6]],
        "pnl_usd": pnl.round(2),
        "period": np.where(cal.day_of(m.trading_day[t[1]]) < cal.n_dev, "dev", "holdout"),
    }).to_csv(path, index=False)


if __name__ == "__main__":
    sys.exit(main())
