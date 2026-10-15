"""EMA x VWAP, step 1 of 2: grid search + selection on DEVELOPMENT data only (2010-06 -> 2021-12).

Usage:
    python -m propfirm_backtest.search            # full grid (~6,144 configs)
    python -m propfirm_backtest.search --quick    # small grid, pipeline smoke test

This step never loads 2022+ data. It freezes a champion + 3 finalists in frozen_picks.json.
Step 2 (python -m propfirm_backtest.holdout) tests those picks ONCE on 2022 -> today.

Rules frozen before looking at results:
- Score = probability of passing a Topstep 50K Combine (block bootstrap of daily P&L,
  same random days for every config).
- Gates: enough trades, profitable after costs AND with +1 tick extra slippage, profitable in
  most years, no single year/day carrying the result, survivable drawdown.
- Champion = best plateau score (median of neighbouring EMA x timeframe cells) among configs
  passing every gate. A lone spike surrounded by bad neighbours is not trusted.
- The selection method itself is walk-forward tested: each year a champion is picked from
  earlier years only; a PASS verdict requires that procedure to make money out of sample.

Design note: bars and the EMA run continuously across sessions (like one chart on screen);
the session only decides WHEN trading is allowed. Cutoff minutes are handled minute by minute.
"""

import hashlib
import itertools
import json
import math
import sys
import time
from pathlib import Path
from statistics import NormalDist

import numpy as np
import pandas as pd

from propfirm_data.config import DATA_DIR

from . import bars as B
from . import engine as E
from . import indicators as I
from . import propsim as P

OUT_DIR = DATA_DIR / "backtests" / "ema_vwap"
DEV_END = pd.Timestamp("2022-01-01")
STOPS = [0, 10, 15, 20]  # 0 = no stop
ENTRIES = {"cross": E.CROSS, "touch": E.TOUCH}
SESSIONS = list(B.SESSIONS)
KEYS = ["timeframe", "ema", "vwap_anchor", "entry", "stop_ticks", "session"]
BASE_SLIP = 1.0
GATE_SLIP = 2.0  # "survives +1 tick per side"
STRESS_SLIPS = [3.0, 4.0]
N_SIMS = 2000
N_SIMS_WF = 300
SEED = 12345
SOURCE_FILES = ["bars.py", "indicators.py", "engine.py", "propsim.py", "search.py", "holdout.py"]

WF_MIN_TRADES_FLOOR = 100
WF_TRADES_PER_YEAR = 25

GATES = {
    "min_trades": 300,
    "min_positive_year_frac": 0.6,  # years with zero trades count as not positive
    "max_best_year_share": 0.5,
    "max_best_day_share": 0.25,
    "max_p95_drawdown": 1000.0,  # 50% of the $2,000 MLL, within a 60-day attempt
}


# --- calendar -----------------------------------------------------------------------------

class Calendar:
    """Trading days with front-month data; days before DEV_END are development."""

    def __init__(self, m: B.Minutes):
        td = np.unique(m.trading_day[m.front])
        self.days = td
        self.n_dev = int((td < (DEV_END - pd.Timestamp("1970-01-01")).days).sum())
        self.index = np.full(td.max() + 2, -1, dtype=np.int64)
        self.index[td] = np.arange(len(td))
        self.years = pd.to_datetime(td, unit="D").year.to_numpy()
        self.dev_years = np.unique(self.years[:self.n_dev])

    def day_of(self, td: np.ndarray) -> np.ndarray:
        return self.index[td]


# --- one run --------------------------------------------------------------------------------

def simulate(m, bars, bseg, cut, ema, ema_ok, vc, vo, entry, stop, slip, pessimistic=True):
    t = E.run(bars.start, bars.end, bars.close, bseg, ema, ema_ok, vc, vo,
              m.open, m.high, m.low, m.close, cut, m.contract, entry, float(stop), slip, pessimistic)
    if (m.contract[t[0]] != m.contract[t[1]]).any():  # roll-safety invariant
        raise RuntimeError("trade entry and exit on different contracts: engine bug")
    return t


def summarize(t, m, cal: Calendar):
    t_in, t_out, t_dir, px_in, px_out, mae, why = t
    pnl = P.trade_pnl_usd(t_dir, px_in, px_out)
    mae_usd = mae * P.TICK_USD + P.FEE_USD
    day = cal.day_of(m.trading_day[t_out])
    day_pnl, day_low = P.daily_series(day, pnl, mae_usd, len(cal.days))
    return pnl, day, why, day_pnl, day_low


def dev_metrics(pnl, day, why, day_pnl, day_low, cal: Calendar) -> dict:
    dev = day < cal.n_dev
    st = P.trade_stats(pnl[dev])
    dp, dl = day_pnl[:cal.n_dev], day_low[:cal.n_dev]
    by_year = pd.Series(dp).groupby(cal.years[:cal.n_dev]).sum()
    total = st["total_usd"]
    sd = dp.std()
    st.update({
        "max_drawdown_usd": P.max_drawdown(dp, dl),
        "positive_year_frac": float((by_year > 0).mean()),
        "best_year_share": by_year.max() / total if total > 0 else np.nan,
        "best_day_share": dp.max() / total if total > 0 else np.nan,
        "sharpe_daily": dp.mean() / sd if sd > 0 else 0.0,
        "pct_stop_exits": float((why[dev] == E.EXIT_STOP).mean()) if dev.any() else np.nan,
        "fallback_exits": int((why[dev] == E.EXIT_FALLBACK).sum()),
    })
    return st


# --- grid -------------------------------------------------------------------------------------

def full_grid():
    return list(itertools.product(B.TIMEFRAMES, I.EMA_LENGTHS, I.VWAP_ANCHORS, ENTRIES, STOPS, SESSIONS))


def grid_runs(m, cal, configs, slip=BASE_SLIP, keep_trades=False, pessimistic=True, verbose=True):
    """Run configs in the given order (sorted by timeframe is fastest).
    Returns (metrics DataFrame, daily P&L, daily intraday low, trades per year, trades)."""
    seg_cut = {s: B.segments(m, s) for s in SESSIONS}
    vwap_min = {}
    rows, dpnl, dlow, ytrades, trades = [], [], [], [], {}
    t0 = time.time()
    current_tf, bars, emas, vwap_bar, bseg_cache = None, None, {}, {}, {}
    for tf, ema_len, anchor, entry, stop, session in configs:
        if tf != current_tf:  # bars + caches rebuilt only when the timeframe changes
            current_tf, bars, emas, vwap_bar, bseg_cache = tf, B.build_bars(m, tf), {}, {}, {}
            if verbose:
                print(f"  timeframe {tf:>2} min: {len(bars):>10,} bars  ({time.time() - t0:.0f}s)", flush=True)
        if ema_len not in emas:
            emas[ema_len] = I.ema(bars, ema_len)
        vkey = (anchor, session if anchor == "session" else None)
        if vkey not in vwap_min:
            vwap_min[vkey] = I.vwap_minutes(m, anchor, session)
        if vkey not in vwap_bar:
            vwap_bar[vkey] = I.vwap_bars(bars, *vwap_min[vkey])
        seg, cut = seg_cut[session]
        if session not in bseg_cache:
            bseg_cache[session] = np.where(seg[bars.start] == seg[bars.end - 1], seg[bars.start], -1)
        t = simulate(m, bars, bseg_cache[session], cut, *emas[ema_len], *vwap_bar[vkey],
                     ENTRIES[entry], stop, slip, pessimistic)
        pnl, day, why, day_pnl, day_low = summarize(t, m, cal)
        row = dict(zip(KEYS, (tf, ema_len, anchor, entry, stop, session)))
        row.update(dev_metrics(pnl, day, why, day_pnl, day_low, cal))
        rows.append(row)
        dpnl.append(day_pnl.astype(np.float32))
        dlow.append(day_low.astype(np.float32))
        ty = cal.years[day[day < cal.n_dev]]
        ytrades.append(np.array([(ty == y).sum() for y in cal.dev_years]))
        if keep_trades:
            trades[len(rows) - 1] = t
    if verbose:
        print(f"  {len(rows):,} runs in {time.time() - t0:.0f}s", flush=True)
    return pd.DataFrame(rows), np.vstack(dpnl), np.vstack(dlow), np.vstack(ytrades), trades


def single(m, cal, cfg, **kw):
    """Trades of one config."""
    return grid_runs(m, cal, [cfg], keep_trades=True, verbose=False, **kw)[4][0]


# --- selection ----------------------------------------------------------------------------------

def gate_mask(df: pd.DataFrame, min_trades: int = GATES["min_trades"]) -> pd.Series:
    g = GATES
    return ((df["trades"] >= min_trades)
            & (df["expectancy_usd"] > 0)
            & (df["expectancy_slip2"] > 0)
            & (df["positive_year_frac"] >= g["min_positive_year_frac"])
            & (df["best_year_share"] <= g["max_best_year_share"])
            & (df["best_day_share"] <= g["max_best_day_share"])
            & (df["p95_drawdown"] <= g["max_p95_drawdown"]))


def wf_min_trades(n_years: int) -> int:
    """Walk-forward folds see only the earlier years: absolute floor + the full gate's per-year rate
    (300 trades over ~11.5 dev years ~ 25/year). A flat 300 would reject slow edges in early folds."""
    return max(WF_MIN_TRADES_FLOOR, WF_TRADES_PER_YEAR * n_years)


def plateau(df: pd.DataFrame, col: str) -> np.ndarray:
    """Median of `col` over the 3x3 neighbourhood of adjacent timeframe x EMA cells
    (same anchor / entry / stop / session)."""
    tf_i = df["timeframe"].map({v: i for i, v in enumerate(B.TIMEFRAMES)}).to_numpy()
    em_i = df["ema"].map({v: i for i, v in enumerate(I.EMA_LENGTHS)}).to_numpy()
    others = list(zip(df["vwap_anchor"], df["entry"], df["stop_ticks"], df["session"]))
    lookup = {(o, a, b): v for o, a, b, v in zip(others, tf_i, em_i, df[col].to_numpy())}
    out = np.empty(len(df))
    for k, (o, a, b) in enumerate(zip(others, tf_i, em_i)):
        vals = [lookup.get((o, a + da, b + db)) for da in (-1, 0, 1) for db in (-1, 0, 1)]
        out[k] = np.median([v for v in vals if v is not None])
    return out


def score(dpnl, dlow, days: slice, n_sims):
    return P.pass_probability(dpnl[:, days].astype(np.float64), dlow[:, days].astype(np.float64), n_sims, SEED)


def rank(df: pd.DataFrame, min_trades: int = GATES["min_trades"]) -> pd.DataFrame:
    df = df.copy()
    df["passes_gates"] = gate_mask(df, min_trades)
    df["plateau_score"] = plateau(df, "pass_prob")
    pool = df[df["passes_gates"]]
    if pool.empty:
        pool = df  # nothing qualifies: still rank for learning, the verdict will be FAIL
    order = pool.sort_values(["plateau_score", "pass_prob"], ascending=False).index
    df["rank"] = np.nan
    df.loc[order, "rank"] = np.arange(1, len(order) + 1)
    return df


def walk_forward(df, dpnl, dlow, dpnl2, ytrades, cal):
    """Test the SELECTION METHOD: each year, pick a champion with the full gate set using only
    earlier years, then record what it made in that unseen year."""
    years = cal.years[:cal.n_dev]
    uniq = cal.dev_years
    ypnl = np.stack([dpnl[:, years == y].sum(axis=1) for y in uniq], axis=1)
    rows = []
    for year in range(2014, 2022):
        prefix = int((years < year).sum())
        before = uniq < year
        res = score(dpnl, dlow, slice(0, prefix), N_SIMS_WF)
        total = ypnl[:, before].sum(axis=1)
        safe_total = np.where(total > 0, total, np.nan)
        d = df[KEYS].copy()
        d["pass_prob"] = res[:, 0]
        d["p95_drawdown"] = res[:, 2]
        d["trades"] = ytrades[:, before].sum(axis=1)
        d["expectancy_usd"] = total
        d["expectancy_slip2"] = dpnl2[:, :prefix].sum(axis=1)
        d["positive_year_frac"] = (ypnl[:, before] > 0).mean(axis=1)
        d["best_year_share"] = ypnl[:, before].max(axis=1) / safe_total
        d["best_day_share"] = dpnl[:, :prefix].max(axis=1) / safe_total
        d = rank(d, wf_min_trades(int(before.sum())))
        pool = d[d["passes_gates"]]
        if pool.empty:
            rows.append({"year": year, "champion": "none qualified", "pnl_usd_in_year": 0.0})
            continue
        best = pool.sort_values("rank").index[0]
        rows.append({"year": year, "champion": label(df.loc[best]),
                     "pnl_usd_in_year": float(dpnl[best, :cal.n_dev][years == year].sum())})
    return pd.DataFrame(rows)


def deflated_sharpe(champ_daily: np.ndarray, all_sharpes: np.ndarray) -> float:
    """Bailey & Lopez de Prado. CONSERVATIVE heuristic: treats every config as an independent
    try, although neighbouring configs are highly correlated."""
    n_trials = len(all_sharpes)
    sd = champ_daily.std()
    if sd == 0 or n_trials < 2:
        return float("nan")
    sr = champ_daily.mean() / sd
    nd = NormalDist()
    gamma = 0.5772156649
    sr0 = math.sqrt(np.var(all_sharpes)) * ((1 - gamma) * nd.inv_cdf(1 - 1 / n_trials)
                                             + gamma * nd.inv_cdf(1 - 1 / (n_trials * math.e)))
    x = champ_daily - champ_daily.mean()
    skew = (x ** 3).mean() / sd ** 3
    kurt = (x ** 4).mean() / sd ** 4
    denom = math.sqrt(max(1e-12, 1 - skew * sr + (kurt - 1) / 4 * sr ** 2))
    return nd.cdf((sr - sr0) * math.sqrt(len(champ_daily) - 1) / denom)


def label(row) -> str:
    stop = f"stop {int(row['stop_ticks'])}t" if row["stop_ticks"] else "no stop"
    return (f"{int(row['timeframe'])}m / EMA {int(row['ema'])} / VWAP {row['vwap_anchor']} / "
            f"{row['entry']} / {stop} / {row['session']}")


def source_hash() -> str:
    h = hashlib.sha256()
    for f in SOURCE_FILES:
        h.update(f.encode() + b"\0" + (Path(__file__).parent / f).read_bytes())
    return h.hexdigest()


# --- stats + report helpers (shared with holdout.py) ----------------------------------------

def period_stats(t, m, cal, period: str) -> dict:
    pnl, day, why, day_pnl, day_low = summarize(t, m, cal)
    if period == "dev":
        sl, mask = slice(0, cal.n_dev), day < cal.n_dev
    else:
        sl, mask = slice(cal.n_dev, None), day >= cal.n_dev
    st = P.trade_stats(pnl[mask])
    dp, dl = day_pnl[sl], day_low[sl]
    st["max_drawdown_usd"] = P.max_drawdown(dp, dl)
    st["pass_prob"], st["fail_prob"], st["p95_drawdown"] = P.pass_probability(
        dp[None, :].astype(np.float64), dl[None, :].astype(np.float64), N_SIMS, SEED)[0]
    st["worst_day_usd"], st["best_day_usd"] = float(dp.min()), float(dp.max())
    st["pnl_excl_best_day"] = float(dp.sum() - dp.max())
    mae = t[5][mask] * P.TICK_USD
    st["median_mae_usd"] = float(np.median(mae)) if len(mae) else float("nan")
    st["p95_mae_usd"] = float(np.quantile(mae, 0.95)) if len(mae) else float("nan")
    st["by_year"] = {int(k): float(v) for k, v in pd.Series(dp).groupby(cal.years[sl]).sum().round(0).items()}
    return st


def fmt(x, money=False, pct=False):
    if x is None:
        return "n/a"
    if isinstance(x, float) and np.isnan(x):
        return "n/a"
    if isinstance(x, float) and np.isinf(x):
        return "inf"
    if pct:
        return f"{100 * x:.1f}%"
    if money:
        return f"${x:,.0f}"
    return f"{x:.2f}" if isinstance(x, float) else str(x)


def benchmark_table(st: dict) -> list[str]:
    """Guide Section 10 thresholds."""
    pf, exp = st["profit_factor"], st["expectancy_usd"]
    rows = [
        ("Trades", st["trades"], ">= 300", st["trades"] >= 300),
        ("Profit factor", fmt(pf), ">= 1.20 (good 1.40-1.80)", pf >= 1.2),
        ("Expectancy per trade", fmt(exp, money=True), "> $0 after costs", exp > 0),
        ("Win rate", fmt(st["win_rate"], pct=True), "judge with avg win / loss", None),
        ("Avg win / avg loss", fmt(st["avg_win_over_loss"]), "-", None),
        ("p95 drawdown in a 60-day attempt", fmt(st["p95_drawdown"], money=True), "<= $1,000 (50% of MLL)", st["p95_drawdown"] <= 1000),
        ("Combine pass probability", fmt(st["pass_prob"], pct=True), "higher is better", None),
        ("Combine fail probability", fmt(st["fail_prob"], pct=True), "lower is better", None),
        ("Max losing streak", st["max_losing_streak"], "-", None),
        ("Worst day", fmt(st["worst_day_usd"], money=True), "-", None),
        ("Median / p95 trade MAE", f"{fmt(st['median_mae_usd'], money=True)} / {fmt(st['p95_mae_usd'], money=True)}", "-", None),
        ("Profit excluding best day", fmt(st["pnl_excl_best_day"], money=True), "> $0", st["pnl_excl_best_day"] > 0),
    ]
    out = ["| Metric | Value | Target | OK? |", "|---|---|---|---|"]
    for name, val, target, ok in rows:
        out.append(f"| {name} | {val} | {target} | {'' if ok is None else ('yes' if ok else '**no**')} |")
    return out


# --- main -----------------------------------------------------------------------------------------

def main() -> int:
    global OUT_DIR
    quick = "--quick" in sys.argv
    if quick:
        OUT_DIR = OUT_DIR.parent / "ema_vwap_quick"
        B.TIMEFRAMES[:] = [5, 10, 15]
        I.EMA_LENGTHS[:] = [13, 20, 21, 34]
    tag = next((a.split("=", 1)[1] for a in sys.argv if a.startswith("--folder=")), None)
    if tag:  # new research folder: its holdout is NOT clean if an earlier folder's holdout was opened
        OUT_DIR = OUT_DIR.parent / f"ema_vwap_{tag}"
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    if (OUT_DIR / "holdout_opened.json").exists():
        print("The holdout was already opened for these picks. Re-running the search now would let")
        print("holdout knowledge leak into new picks. Start a new research folder instead.")
        return 2

    print("Loading development data (2010-06 -> 2021-12 only)...", flush=True)
    m = B.load_minutes(end=DEV_END)
    cal = Calendar(m)
    assert cal.n_dev == len(cal.days), "holdout data must not be loaded here"
    print(f"  {len(m):,} minutes, {cal.n_dev:,} trading days", flush=True)

    grid = full_grid()
    print(f"Grid at {BASE_SLIP:.0f} tick slippage ({len(grid):,} configs)...", flush=True)
    df, dpnl, dlow, ytrades, _ = grid_runs(m, cal, grid)
    print(f"Grid at {GATE_SLIP:.0f} ticks slippage (stress gate)...", flush=True)
    df2, dpnl2, _, _, _ = grid_runs(m, cal, grid, slip=GATE_SLIP)
    df["expectancy_slip2"] = df2["expectancy_usd"].to_numpy()

    print("Scoring (Combine simulation)...", flush=True)
    res = score(dpnl, dlow, slice(None), N_SIMS)
    df["pass_prob"], df["fail_prob"], df["p95_drawdown"] = res[:, 0], res[:, 1], res[:, 2]
    df = rank(df)
    df.sort_values("rank").to_csv(OUT_DIR / "results.csv", index=False)

    print("Walk-forward test of the selection method...", flush=True)
    wf = walk_forward(df, dpnl, dlow, dpnl2, ytrades, cal)
    wf.to_csv(OUT_DIR / "walk_forward.csv", index=False)

    picks = df.sort_values("rank").head(4)
    any_qualified = bool(df["passes_gates"].any())
    print("Details for the champion + 3 finalists (development)...", flush=True)
    detail = []
    for _, row in picks.iterrows():
        cfg = tuple(row[k] for k in KEYS)
        st = period_stats(single(m, cal, cfg), m, cal, "dev")
        st["stress"] = {s: period_stats(single(m, cal, cfg, slip=s), m, cal, "dev") for s in STRESS_SLIPS}
        st["optimistic"] = period_stats(single(m, cal, cfg, pessimistic=False), m, cal, "dev")
        st["expectancy_slip2"] = float(row["expectancy_slip2"])
        detail.append((cfg, st))

    dsr = deflated_sharpe(dpnl[picks.index[0]].astype(np.float64), df["sharpe_daily"].to_numpy())
    frozen = {
        "created_utc": pd.Timestamp.now(tz="UTC").isoformat(),
        "source_sha256": source_hash(),
        "any_config_passed_gates": any_qualified,
        "champion_passed_gates": bool(picks.iloc[0]["passes_gates"]),
        "walk_forward_total_usd": float(wf["pnl_usd_in_year"].sum()),
        "deflated_sharpe": dsr,
        "picks": [{k: (v.item() if hasattr(v, "item") else v) for k, v in zip(KEYS, cfg)} for cfg, _ in detail],
    }
    (OUT_DIR / "frozen_picks.json").write_text(json.dumps(frozen, indent=2))
    write_report(df, wf, detail, dsr, any_qualified, cal)
    print(f"\nDevelopment report: {OUT_DIR / 'report.md'}")
    print("Picks frozen. Next (runs ONCE): python -m propfirm_backtest.holdout")
    return 0


def write_report(df, wf, detail, dsr, any_qualified, cal):
    L = ["# EMA x VWAP: development results (2010-06 -> 2021-12)", "",
         f"Generated {pd.Timestamp.now(tz='UTC'):%Y-%m-%d %H:%M} UTC. {len(df):,} configurations, {cal.n_dev:,} trading days.",
         "Costs: $4.02 round turn + 1 tick slippage per side; stops 1 tick worse (gap: open - 1 tick).",
         "The holdout (2022 -> today) is NOT in this report. See holdout.md after step 2.", ""]
    wf_total = wf["pnl_usd_in_year"].sum()
    L += ["## Summary", "",
          f"- Configurations passing every gate: **{int(df['passes_gates'].sum()):,} / {len(df):,}**",
          f"- Configurations profitable after costs: {int((df['expectancy_usd'] > 0).sum()):,}"
          f" (still profitable with +1 tick slippage: {int((df['expectancy_slip2'] > 0).sum()):,})",
          f"- Walk-forward of the selection method (2014-2021, picks made with earlier years only): **{fmt(wf_total, money=True)}**",
          f"- Deflated Sharpe of the champion (conservative, assumes {len(df):,} independent tries): {fmt(dsr, pct=True)}", ""]
    if not any_qualified:
        L += ["**No configuration passed all gates.** The rankings below are for learning only; "
              "this strategy should not be traded as specified.", ""]

    L += ["## Champion + 3 finalists (frozen for the holdout)", "",
          "| # | Settings | Trades | Expectancy | PF | Pass % | Fail % | p95 DD | +1 tick exp. |",
          "|---|---|---|---|---|---|---|---|---|"]
    for n, (cfg, st) in enumerate(detail, 1):
        L.append(f"| {n} | {label(dict(zip(KEYS, cfg)))} | {st['trades']} | {fmt(st['expectancy_usd'], money=True)} | "
                 f"{fmt(st['profit_factor'])} | {fmt(st['pass_prob'], pct=True)} | {fmt(st['fail_prob'], pct=True)} | "
                 f"{fmt(st['p95_drawdown'], money=True)} | {fmt(st['expectancy_slip2'], money=True)} |")

    cfg, st = detail[0]
    L += ["", f"## Champion: {label(dict(zip(KEYS, cfg)))}", ""] + benchmark_table(st)
    L += ["", "### Slippage stress and fill-ambiguity bound", "", "| Case | Expectancy | Profit factor | Pass % |", "|---|---|---|---|",
          f"| 1 tick/side (base, pessimistic) | {fmt(st['expectancy_usd'], money=True)} | {fmt(st['profit_factor'])} | {fmt(st['pass_prob'], pct=True)} |"]
    for s, sst in st["stress"].items():
        L.append(f"| {int(s)} ticks/side | {fmt(sst['expectancy_usd'], money=True)} | {fmt(sst['profit_factor'])} | {fmt(sst['pass_prob'], pct=True)} |")
    o = st["optimistic"]
    L.append(f"| Optimistic same-minute fills | {fmt(o['expectancy_usd'], money=True)} | {fmt(o['profit_factor'])} | {fmt(o['pass_prob'], pct=True)} |")
    L += ["", "### P&L by year", "", "| Year | P&L |", "|---|---|"] + [f"| {y} | {fmt(v, money=True)} |" for y, v in st["by_year"].items()]

    L += ["", "## Walk-forward test of the selection method", "",
          "Each year the champion is chosen from earlier years only, then we record what it made in that unseen year.", "",
          "| Year | Champion chosen from earlier years | P&L that year |", "|---|---|---|"]
    L += [f"| {r['year']} | {r['champion']} | {fmt(r['pnl_usd_in_year'], money=True)} |" for _, r in wf.iterrows()]
    L.append(f"| **Total** | | **{fmt(wf_total, money=True)}** |")

    cols = KEYS + ["trades", "expectancy_usd", "expectancy_slip2", "profit_factor", "pass_prob", "plateau_score", "passes_gates"]
    for by in ["session", "timeframe"]:
        best = df.sort_values("rank").groupby(by, sort=False).head(1).sort_values(by)
        L += ["", f"## Best configuration per {by}", "", "```", best[cols].round(3).to_string(index=False), "```"]
    for by in ["session", "timeframe", "ema", "vwap_anchor", "entry", "stop_ticks"]:
        g = df.groupby(by).agg(median_expectancy=("expectancy_usd", "median"),
                               share_profitable=("expectancy_usd", lambda s: (s > 0).mean()),
                               best_expectancy=("expectancy_usd", "max"), best_pass_prob=("pass_prob", "max"))
        L += ["", f"## Effect of {by} (all configs)", "", "```", g.round(3).to_string(), "```"]
    L += ["", "Files: `results.csv` (every config), `walk_forward.csv`, `frozen_picks.json`."]
    (OUT_DIR / "report.md").write_text("\n".join(L))


if __name__ == "__main__":
    sys.exit(main())
