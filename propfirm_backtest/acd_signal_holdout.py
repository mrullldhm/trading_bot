"""Fisher ACD: one pre-registered, once-only holdout test of the ENTRY SIGNAL (2022 -> today).

Usage:
    python -m propfirm_backtest.acd_signal_holdout --register   # freeze the test; never loads 2022+ data
    python -m propfirm_backtest.acd_signal_holdout --run        # runs ONCE; spends the ACD holdout

Why: on 2010-2021 the ACD champion's entries moved +$52-63/trade (gross) more than random entries in the
same weeks over the next 60 minutes (audit report, day-clustered z 4.7). The champion was picked from 2,880
configs on those same days, so that is exploratory. This tests it once on data nobody selected on.

Pre-registered (written to signal_holdout_prereg.json by --register, checked by --run):
- Signals: the frozen ACD champion's real entries on holdout trading days (2022 -> data end), followed
  without stops/targets. Features may use earlier (development) sessions: that is causal warm-up.
- Controls: up to 20 entries at the same ET minute and side, on distinct holdout days (without
  replacement, seeded) within 20 trading days either side; early-2022 signals therefore only get later days.
  Exclusive: a (day, minute, side) control serves ONE signal only, and a slot holding a real signal is never
  a control. Shared controls would carry common noise the relabelling cannot see (simulated false-alarm
  rate 8.5% instead of 5%); exclusive controls keep the test exact.
- H1 (directional edge, primary): T = mean over signals of (60-min gross move - mean of its controls).
  Randomization test: under "no edge" a signal is exchangeable with its controls, so in each of
  N_PERMUTATIONS draws one of the (1 + controls) values per signal is relabelled as the signal. PASS: T > 0
  and one-sided
  p = (1 + #(T_draw >= T)) / (N_PERMUTATIONS + 1) < ALPHA.
- H2 (profitable at a fixed 60-min exit), tested ONLY if H1 passes (fixed sequence: total error <= 5%):
  mean of (60-min gross move - $24.02) per trade, day-clustered one-sided z > 1.645.
- Valid pair = signal with a 60-min value and >= MIN_CONTROLS controls with one. Fewer than MIN_SIGNALS
  valid pairs: INCONCLUSIVE. H2 likewise needs MIN_SIGNALS signals with a 60-min value.
- One run. Never re-run, extended or re-registered. Everything else in the report is descriptive.
The run marks data/backtests/acd/holdout_opened.json, so family_holdout acd can never claim a clean look.
Caveat: 2022+ was already looked at for Strategy 1 (EMA x VWAP), never for ACD.
"""

import hashlib
import json
import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd

from . import audit as A
from . import orb_engine as E
from . import propsim as P

HORIZON = "60"
ALPHA = 0.05  # one-sided
Z_CRIT = 1.645  # one-sided 5%
N_PERMUTATIONS = 10_000
MIN_CONTROLS = 5
SLIP = 1.0
COST_USD = P.FEE_USD + 2 * SLIP * P.TICK_USD
MIN_SIGNALS = 100
SEED = 2022_06
PREREG = "signal_holdout_prereg.json"
REPORT = "signal_holdout.md"
CODE_FILES = ["acd_signal_holdout.py", "audit.py"]


def code_hash() -> str:
    h = hashlib.sha256()
    for name in CODE_FILES:
        h.update(name.encode() + b"\0" + (Path(__file__).parent / name).read_bytes())
    return h.hexdigest()


def data_hash() -> str:
    """The exact dataset (every bar file, bytes): a later download or edit changes it. Reading bytes to hash
    them is not looking at the holdout; nothing is parsed."""
    from propfirm_data.config import BARS_DIR, DEFINITIONS_FILE
    h = hashlib.sha256()
    for path in sorted(BARS_DIR.rglob("*.parquet")) + [DEFINITIONS_FILE]:
        h.update(str(path.relative_to(path.parents[2])).encode() + b"\0" + path.read_bytes())
    return h.hexdigest()


def environment() -> dict:
    import numba
    return {"python": sys.version.split()[0], "numpy": np.__version__, "pandas": pd.__version__,
            "numba": numba.__version__}


def spec(frozen: dict) -> dict:
    return {"family": "acd", "champion_cfg": frozen["champion_cfg"], "champion_source_sha256": frozen["source_sha256"],
            "test_code_sha256": code_hash(), "data_sha256": data_hash(), "environment": environment(),
            "horizon_min": HORIZON, "alpha_one_sided": ALPHA, "h1_test": "randomization (relabel signal vs controls)",
            "n_permutations": N_PERMUTATIONS, "h2_test": "day-clustered z, only if H1 passes",
            "z_crit_one_sided": Z_CRIT, "cost_usd_per_trade": COST_USD, "slip_ticks": SLIP,
            "min_signals": MIN_SIGNALS, "min_controls": MIN_CONTROLS, "seed": SEED,
            "random_per_signal": A.N_RANDOM_PER_SIGNAL,
            "controls": "same ET minute and side, distinct holdout days within +-20 trading days, without "
                        "replacement, exclusive (each control serves one signal; signal slots excluded)",
            "stopping_rule": "one run; never re-run, extended or re-registered"}


def randomization_p(signal: np.ndarray, controls: np.ndarray, seed=SEED) -> tuple[float, float]:
    """(T, one-sided p). signal: (n,), controls: (n, k) NaN-padded. Under no edge, the signal is one more
    draw from the same distribution as its controls: relabel one of the 1 + k values per signal as 'signal'."""
    values = np.column_stack([signal, controls])  # column 0 = the real signal
    valid = ~np.isnan(values)
    k = valid.sum(axis=1)  # 1 + valid controls
    total = np.nansum(values, axis=1)
    stat = lambda pick: np.mean(pick - (total - pick) / (k - 1))  # noqa: E731  treated minus mean of the rest
    observed = stat(values[:, 0])
    order = np.argsort(~valid, axis=1, kind="stable")  # valid values first, per row
    rng = np.random.default_rng(seed)
    hits = 0
    rows = np.arange(len(values))
    for _ in range(N_PERMUTATIONS):
        pick = values[rows, order[rows, (rng.random(len(values)) * k).astype(int)]]
        hits += stat(pick) >= observed
    return float(observed), float((1 + hits) / (N_PERMUTATIONS + 1))


def decide(raw: dict) -> dict:
    """The pre-registered decision on exactly the per-signal numbers of the primary horizon."""
    q = [*map(str, A.HORIZONS), "session end"].index(HORIZON)
    move, controls, day = raw["move"][:, q], raw["controls_local"][:, :, q], raw["day"]
    pair = ~np.isnan(move) & ((~np.isnan(controls)).sum(axis=1) >= MIN_CONTROLS)
    n_pairs, n_moves = int(pair.sum()), int((~np.isnan(move)).sum())
    if n_pairs < MIN_SIGNALS or n_moves < MIN_SIGNALS:
        return {"verdict": "INCONCLUSIVE", "signals": n_moves, "valid_pairs": n_pairs,
                "reason": f"fewer than {MIN_SIGNALS} valid signal/control pairs"}
    t_stat, p = randomization_p(move[pair], controls[pair])
    h1 = bool(t_stat > 0 and p < ALPHA)
    net, z_net, days = A.clustered(move - COST_USD / P.TICK_USD, day)
    h2 = bool(h1 and z_net > Z_CRIT and net > 0)
    verdict = ("CONFIRMED EDGE AND PROFITABLE AT 60 MIN" if h2 else
               "CONFIRMED EDGE; PROFITABILITY AFTER COSTS NOT CONFIRMED" if h1 else "EDGE NOT CONFIRMED")
    return {"verdict": verdict, "signals": n_moves, "valid_pairs": n_pairs, "days": days,
            "h1_edge_usd": t_stat * P.TICK_USD, "h1_p": p, "h1_pass": h1,
            "h2_tested": h1, "h2_net_usd": net, "h2_z": z_net, "h2_pass": h2}


def register(out: Path, frozen: dict) -> int:
    path = out / PREREG
    if path.exists():
        print(f"Already registered ({path}). A registration is never rewritten.")
        return 2
    body = {"registered_utc": pd.Timestamp.now(tz="UTC").isoformat(), **spec(frozen)}
    path.write_text(json.dumps(body, indent=2))
    print(f"Registered: {path}\nNext (runs ONCE): python -m propfirm_backtest.acd_signal_holdout --run")
    return 0


def check_registration(out: Path, frozen: dict) -> int:
    path = out / PREREG
    if not path.exists():
        print("Not registered. Run --register first (it never loads holdout data).")
        return 1
    reg = json.loads(path.read_text())
    now = spec(frozen)
    changed = [k for k in now if reg.get(k) != now[k]]
    if changed:
        print(f"The test or the champion changed since registration: {changed}. Refusing to open the holdout.")
        return 3
    return 0


def mark_opened(out: Path, frozen: dict) -> bool:
    try:
        fd = os.open(out / "holdout_opened.json", os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        print("The ACD holdout was already opened.")
        return False
    with os.fdopen(fd, "w") as fh:
        json.dump({"opened_utc": pd.Timestamp.now(tz="UTC").isoformat(), "opened_by": "acd_signal_holdout",
                   "source_sha256": frozen["source_sha256"]}, fh, indent=2)
    return True


def run(out: Path, frozen: dict) -> int:
    from propfirm_data.eia_calendar import load_releases

    from . import bars as B
    from . import search as S
    from .family_search import FAMILIES

    if not mark_opened(out, frozen):
        return 2
    print("Loading all data (development + holdout)...", flush=True)
    m = B.load_minutes()
    cal = S.Calendar(m)
    mk = FAMILIES["acd"].market(m, cal.days, load_releases(), strict_expiry=True)
    t = mk.trades(np.array(frozen["champion_cfg"], np.int64))
    hold = t[0] >= cal.n_dev
    th = tuple(x[hold] for x in t)
    paths = A.Paths(mk.f, cal.days)
    e = A.signal_edge(paths, th, SLIP, E.EXIT_STOP, np.random.default_rng(SEED), cal.days[cal.n_dev:], keep_raw=True,
                      exclusive_controls=True)
    d = decide(e["raw"])
    pnl = P.trade_pnl_usd(th[3], th[4], th[5])
    L = ["# Fisher ACD: pre-registered entry-signal holdout", "",
         f"Run {pd.Timestamp.now(tz='UTC'):%Y-%m-%d %H:%M} UTC on {len(cal.days) - cal.n_dev:,} holdout trading days "
         f"(2022 -> today). Registration: {PREREG}.", "", f"## Verdict: {d['verdict']}", ""]
    if d["verdict"] != "INCONCLUSIVE":
        h2 = ("PASS" if d["h2_pass"] else "not confirmed") if d["h2_tested"] else "not tested (H1 failed); descriptive"
        L += [f"- H1 directional edge at {HORIZON} min vs same-weeks random entries: ${d['h1_edge_usd']:.2f}/trade, "
              f"randomization p = {d['h1_p']:.4f} (needs < {ALPHA}) -> {'PASS' if d['h1_pass'] else 'FAIL'}",
              f"- H2 profitable at a fixed {HORIZON}-min exit after ${COST_USD:.2f} costs: ${d['h2_net_usd']:.2f}/trade, "
              f"day-clustered z {d['h2_z']:.2f} (needs > {Z_CRIT}) -> {h2}",
              f"- {d['signals']:,} signals ({d['valid_pairs']:,} valid pairs) on {d['days']:,} days", ""]
    else:
        L += [f"- {d['reason']} ({d['signals']} signals)", ""]
    L += ["## Descriptive only (not part of the decision)", "",
          "| Horizon (min) | Signal $ | Edge vs random $ (z) | Edge vs same weeks $ (z) |", "|---|---|---|---|"]
    L += [f"| {x['horizon']} | {x['signal_usd']:.2f} | {x['edge_usd']:.2f} ({x['z']:.2f}) | "
          f"{x['local_edge_usd']:.2f} ({x['local_z']:.2f}) |" for x in e["horizons"]]
    L += ["", f"The champion's actual strategy on the holdout (its own stops and exits, $24.02 costs): {len(pnl):,} "
          f"trades, ${pnl.mean() if len(pnl) else float('nan'):.2f}/trade, total ${pnl.sum():,.0f}.", ""]
    (out / REPORT).write_text("\n".join(L))
    (out / "signal_holdout_result.json").write_text(json.dumps(d, indent=2, default=float))
    print(f"\nVerdict: {d['verdict']}. Report: {out / REPORT}")
    return 0


def main(argv=None) -> int:
    from . import orb_holdout as H
    from .family_search import FAMILIES

    argv = sys.argv[1:] if argv is None else argv
    if argv not in (["--register"], ["--run"]):
        print(__doc__)
        return 2
    family = FAMILIES["acd"]
    out = family.out_dir
    frozen, code = H.preflight(out, family)  # quick run, changed code, missing inputs, already opened
    if frozen is None:
        return code
    if argv == ["--register"]:
        return register(out, frozen)
    code = check_registration(out, frozen)
    return code or run(out, frozen)


if __name__ == "__main__":
    sys.exit(main())
