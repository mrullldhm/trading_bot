"""Backtest audit: is each FAIL a real FAIL? Development data only (2010-06 -> 2021-12).

Usage:
    python -m propfirm_backtest.audit scenarios [--quick]   # re-run every search under other assumptions
    python -m propfirm_backtest.audit control               # positive control: plant an edge, must be found
    python -m propfirm_backtest.audit report                # data + engine checks, verdicts, report.md

Every engine bias is pessimistic, and a pessimistic bug can fake a FAIL (never a PASS). So the audit
asks two things per strategy:
  1. Does the FAIL survive best-case assumptions? (zero cost, optimistic 1-minute fills, no EIA block,
     no drawdown gate). If yes, costs / fill rules / risk gates are not what failed it.
  2. Can the same pipeline find an edge when one exists? (positive control on real data with a planted
     drift). If yes, the gates are not simply impossible to pass.
Output: data/backtests/audit/ (report.md, trades_chart.html, scenario folders). Never loads 2022+.
"""

import json
import math
import os
import subprocess
import sys
import urllib.request
from pathlib import Path
from statistics import NormalDist

import numpy as np
import pandas as pd

from propfirm_data.config import DATA_DIR

from . import bars as B
from . import engine as EN
from . import orb_engine as E
from . import orb_family_engine as FE
from . import orb_features as F
from . import propsim as P
from .orb_search import WF_YEARS

AUDIT_DIR = DATA_DIR / "backtests" / "audit"
STRATEGIES = ["ema_vwap", "orb", "zab", "crabel", "acd"]
TITLES = {"ema_vwap": "1 EMA x VWAP", "orb": "2 ORB", "zab": "3 ZAB", "crabel": "4 Crabel", "acd": "5 Fisher ACD"}
INF = float("inf")

# assumption sets: (fee per round turn, slippage ticks/side, stress-gate slippage, pessimistic fills,
# EIA block on, max p95 drawdown gate)
SCENARIOS = {
    "baseline": dict(fee=P.FEE_USD, slip=1.0, gate_slip=2.0, pessimistic=True, eia=True, max_dd=1000.0),
    "zero_cost": dict(fee=0.0, slip=0.0, gate_slip=1.0, pessimistic=True, eia=True, max_dd=1000.0),
    "risk_2000": dict(fee=P.FEE_USD, slip=1.0, gate_slip=2.0, pessimistic=True, eia=True, max_dd=2000.0),
    "best_case": dict(fee=0.0, slip=0.0, gate_slip=0.0, pessimistic=False, eia=False, max_dd=INF),
}
CONTROL_DRIFTS = [0.0, 0.1, 0.25, 0.5, 1.0]  # planted ticks per minute, for 60 minutes after the breakout
CONTROL_RANGE = (9 * 60, 9 * 60 + 30)  # the 09:00-09:30 ET opening range whose breakout gets the drift
CONTROL_LEN = 60
CONTROL_GATES = {"gates": None, "no_dd_gate": INF}  # name -> p95 drawdown limit override (None = unchanged)
FRED_URL = "https://fred.stlouisfed.org/graph/fredgraph.csv?id=DCOILWTICO"
N_CHART = 30
N_COIN = 20_000
SEED = 2026


# --- scenarios: the real pipelines, re-run under other assumptions (one subprocess each) -----------

def apply_scenario(sc: dict, out_root: Path):
    """Patch the pipeline modules BEFORE anything is compiled (call in a fresh process only).
    numba reads module constants at compile time; the ORB kernels are compiled fresh every run."""
    from . import orb_search as O
    from . import search as S

    P.FEE_USD = sc["fee"]
    for mod in (O, S):
        mod.BASE_SLIP, mod.GATE_SLIP = sc["slip"], sc["gate_slip"]
        mod.GATES["max_p95_drawdown"] = sc["max_dd"]
    pess = sc["pessimistic"]
    O.Dev.kernel.__defaults__ = (pess,)
    O.Dev.daily.__defaults__ = (sc["slip"], pess)
    E.Market.trades.__defaults__ = (None, sc["slip"], pess)
    S.grid_runs.__defaults__ = (sc["slip"], False, pess, True)
    if not sc["eia"]:
        O.load_releases = lambda: None
    O.DATA_DIR = out_root  # family.out_dir -> <out_root>/backtests/<family>
    S.OUT_DIR = out_root / "backtests" / "ema_vwap"
    return O, S


def dump_yearly(path: Path, ypnl, ytr, years):
    path.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(path, ypnl=np.asarray(ypnl, np.float32), ytr=np.asarray(ytr, np.int32),
                        years=np.asarray(years))


def run_worker(scenario: str, strategy: str, quick: bool) -> int:
    root = AUDIT_DIR / scenario
    O, S = apply_scenario(SCENARIOS[scenario], root)
    argv = ["audit"] + (["--quick"] if quick else [])
    suffix = "_quick" if quick else ""
    # keep each config's yearly P&L (the pipelines discard it) for the gate-free walk-forward
    frame = O.metrics_frame

    def metrics_frame(grid, dev, base, slip2):
        df, arr = frame(grid, dev, base, slip2)
        c = grid.canonical
        dump_yearly(root / "backtests" / f"{grid.family.name}{suffix}" / "yearly.npz",
                    arr["ypnl"][c], arr["ytr"][c], dev.years)
        return df, arr
    O.metrics_frame = metrics_frame
    wf = S.walk_forward

    def walk_forward(df, dpnl, dlow, dpnl2, ytrades, cal):
        years = cal.years[:cal.n_dev]
        ypnl = np.stack([dpnl[:, years == y].sum(axis=1) for y in cal.dev_years], axis=1)
        dump_yearly(S.OUT_DIR / "yearly.npz", ypnl, ytrades, cal.dev_years)
        return wf(df, dpnl, dlow, dpnl2, ytrades, cal)
    S.walk_forward = walk_forward
    if strategy == "ema_vwap":
        sys.argv = argv  # search.main itself switches to ema_vwap_quick on --quick
        return S.main() or 0
    from .family_search import FAMILIES
    return O.main(O.ORB if strategy == "orb" else FAMILIES[strategy], argv) or 0


def run_scenarios(quick: bool) -> int:
    for scenario in SCENARIOS:
        for strategy in STRATEGIES:
            print(f"=== scenario {scenario} / {strategy}", flush=True)
            cmd = [sys.executable, "-m", "propfirm_backtest.audit", "_worker", scenario, strategy]
            if subprocess.run(cmd + (["--quick"] if quick else [])).returncode != 0:
                print(f"FAILED: {scenario} / {strategy}")
                return 1
    return 0


# --- positive control: a planted edge in the real development data -----------------------------------

def plant_drift(m: B.Minutes, drift: float) -> B.Minutes:
    """Plant an ORB-shaped edge: on each day, from the first minute that breaks the 09:00-09:30 ET front-month
    range, add `drift` ticks/minute IN THE BREAKOUT DIRECTION for CONTROL_LEN minutes, then hold the offset
    until the day ends. Causal: the breakout is visible when the drift starts. A minute breaking both sides
    plants nothing that day. Offsets are whole ticks, constant inside a minute: every bar stays valid OHLC."""
    if drift == 0:
        return m
    td = m.trading_day
    day_part = (m.et_day == td) & (m.mod < 17 * 60)
    t_min = m.ts // E.NS_PER_MIN
    k = m.front & day_part
    fr = pd.DataFrame({"td": td[k], "mod": m.mod[k], "high": m.high[k], "low": m.low[k], "t": t_min[k]})
    rng = (fr[(fr["mod"] >= CONTROL_RANGE[0]) & (fr["mod"] < CONTROL_RANGE[1])]
           .groupby("td").agg(hi=("high", "max"), lo=("low", "min")))
    after = fr[fr["mod"] >= CONTROL_RANGE[1]].join(rng, on="td", how="inner")
    up, dn = after["high"] > after["hi"], after["low"] < after["lo"]
    first = after[up | dn].groupby("td").head(1)
    side = np.where(first["high"] > first["hi"], 1, 0) - np.where(first["low"] < first["lo"], 1, 0)
    t_break = pd.Series(first["t"].to_numpy(), index=first["td"].to_numpy())
    side_of = pd.Series(side, index=first["td"].to_numpy())
    tb = pd.Series(td).map(t_break).to_numpy()
    sd = pd.Series(td).map(side_of).fillna(0).to_numpy()
    live = day_part & ~np.isnan(tb) & (t_min >= np.nan_to_num(tb, nan=np.inf))
    elapsed = np.clip(t_min - np.nan_to_num(tb), 0, CONTROL_LEN)
    off = np.where(live, np.round(sd * drift * elapsed), 0.0)
    out = B.Minutes(**{k_: getattr(m, k_) for k_ in m.__dataclass_fields__})
    out.open, out.high, out.low, out.close = m.open + off, m.high + off, m.low + off, m.close + off
    return out


def control_dir(drift: float, gate: str) -> Path:
    return AUDIT_DIR / f"control_{drift:g}_{gate}"


def control_worker(drift: float, gate: str) -> int:
    from . import orb_search as O
    load = B.load_minutes
    B.load_minutes = lambda **kw: plant_drift(load(**kw), drift)
    if CONTROL_GATES[gate] is not None:
        O.GATES["max_p95_drawdown"] = CONTROL_GATES[gate]
    O.DATA_DIR = control_dir(drift, gate)
    return O.main(O.ORB, ["audit", "--quick"]) or 0


def run_control() -> int:
    for gate in CONTROL_GATES:
        for drift in CONTROL_DRIFTS:
            print(f"=== positive control: drift {drift:g} ticks/min, {gate}", flush=True)
            cmd = [sys.executable, "-m", "propfirm_backtest.audit", "_control", str(drift), gate]
            if subprocess.run(cmd).returncode != 0:
                return 1
    return 0


# --- reading pipeline outputs ---------------------------------------------------------------------------

def out_dir(strategy: str, scenario: str | None = None, quick=False) -> Path:
    base = DATA_DIR if scenario is None else AUDIT_DIR / scenario
    name = "ema_vwap_v2" if strategy == "ema_vwap" and scenario is None else strategy
    return base / "backtests" / (name + ("_quick" if quick else ""))


def load_results(d: Path) -> pd.DataFrame | None:
    for f in ("results.csv.gz", "results.csv"):
        if (d / f).exists():
            return pd.read_csv(d / f)
    return None


def summary(strategy: str, d: Path) -> dict | None:
    """One line per pipeline run: how many configs are profitable / pass the gates / are eligible."""
    df = load_results(d)
    picks = d / "frozen_picks.json"
    if df is None or not picks.exists():
        return None
    fp = json.loads(picks.read_text())
    wf = pd.read_csv(d / "walk_forward.csv") if (d / "walk_forward.csv").exists() else pd.DataFrame()
    champ = df.sort_values("rank").iloc[0]
    eligible = fp.get("champion_eligible", fp.get("champion_passed_gates", False))
    return {
        "configs": len(df),
        "profitable": int((df["expectancy_usd"] > 0).sum()),
        "pass_gates": int(df["passes_gates"].sum()),
        "eligible": int(df["eligible"].sum()) if "eligible" in df else int(df["passes_gates"].sum()),
        "champion_eligible": bool(eligible),
        "champion_expectancy": float(champ["expectancy_usd"]),
        "champion_pass_prob": float(champ.get("pass_prob", np.nan)),
        "wf_total": float(wf["pnl_usd_in_year"].sum()) if len(wf) else np.nan,
        "wf_years_qualified": int((wf["champion"] != "none qualified").sum()) if len(wf) else 0,
        "dsr": fp.get("deflated_sharpe_unique", fp.get("deflated_sharpe", np.nan)),
        "min_p95_dd_profitable": float(df.loc[df["expectancy_usd"] > 0, "p95_drawdown"].min())
        if (df["expectancy_usd"] > 0).any() else np.nan,
    }


def gate_failures(strategy: str, df: pd.DataFrame, max_dd=None) -> pd.DataFrame:
    """Per config: which gate fails (True = fails). Thresholds come from the pipelines' own GATES and every
    test is written as "not (passes)", so NaN fails exactly as in search.gate_mask / orb_search.gate_mask."""
    from . import orb_search as O
    from . import search as S
    g = S.GATES if strategy == "ema_vwap" else O.GATES
    max_dd = g["max_p95_drawdown"] if max_dd is None else max_dd
    out = {"trades": ~(df["trades"] >= g["min_trades"]),
           "profitable": ~(df["expectancy_usd"] > 0),
           "profitable_+1tick": ~(df["expectancy_slip2"].fillna(-1) > 0),
           "positive_years": ~(df["positive_year_frac"] >= g["min_positive_year_frac"]),
           "best_year_share": ~(df["best_year_share"].fillna(INF) <= g["max_best_year_share"]),
           "best_day_share": ~(df["best_day_share"].fillna(INF) <= g["max_best_day_share"]),
           "p95_drawdown": ~(df["p95_drawdown"] <= max_dd)}
    if strategy != "ema_vwap":
        out["trades_per_year"] = ~(df["trades_per_year"] >= g["min_trades_per_year"])
        out["neighbours_profitable"] = ~(df["neighbours_profitable"] >= g["min_neighbours_profitable"])
    return pd.DataFrame(out)


def gate_attribution(strategy: str, df: pd.DataFrame) -> dict:
    """Configs blocked by exactly ONE gate, per gate: which gate is the wall."""
    fails = gate_failures(strategy, df)
    only = fails[fails.sum(axis=1) == 1]
    out = {k: int(v) for k, v in only.sum().items() if v}
    out["_any_single"] = len(only)
    others = fails.drop(columns="p95_drawdown").sum(axis=1) == 0
    out["_dd_relaxed_2000_pass"] = int((others & (df["p95_drawdown"] <= 2000.0)).sum())
    out["_dd_off_pass"] = int(others.sum())
    return out


def gate_free_wf(path: Path) -> dict | None:
    """Economic out-of-sample test with NO robustness gates: each year 2014-2021, pick the config with the
    most P&L in the earlier years only (enough trades), and book its P&L in that unseen year."""
    if not path.exists():
        return None
    z = np.load(path)
    ypnl, ytr, years = z["ypnl"].astype(np.float64), z["ytr"], z["years"]
    total = trades = 0.0
    picks = 0
    from . import search as S
    for y in WF_YEARS:
        prior = years < y
        if not prior.any() or y not in years:
            continue
        need = S.wf_min_trades(int(prior.sum()))
        ok = ytr[:, prior].sum(axis=1) >= need
        if not ok.any():
            continue
        cum = np.where(ok, ypnl[:, prior].sum(axis=1), -np.inf)
        i = int(np.argmax(cum))
        k = int(np.flatnonzero(years == y)[0])
        total += ypnl[i, k]
        trades += ytr[i, k]
        picks += 1
    return {"years": picks, "total_usd": float(total), "per_trade_usd": float(total / trades) if trades else np.nan}


def verdict(base: dict | None, scen: dict, econ: dict) -> str:
    """Per strategy. `base`/`scen`: pipeline summaries (gates + plateau + walk-forward of the selector).
    `econ`: gate-free walk-forward per run (pure out-of-sample money, no robustness rules)."""
    if base is None or not np.isfinite(base.get("wf_total", np.nan)):
        return "INCOMPLETE (baseline run or its walk-forward missing)"
    if base["champion_eligible"] and base["wf_total"] > 0:
        return "PASS (baseline)"
    best = scen.get("best_case")
    e_base, e_best = econ.get("baseline"), econ.get("best_case")
    if best is None or e_base is None or e_best is None or not np.isfinite(best.get("wf_total", np.nan)):
        return "INCOMPLETE (best-case run or the gate-free walk-forward missing)"
    if best["champion_eligible"] and best["wf_total"] > 0:
        flips = [k for k in ("zero_cost", "risk_2000") if scen.get(k) and scen[k]["champion_eligible"]
                 and scen[k]["wf_total"] > 0]
        why = ", ".join(flips) if flips else "only the combination (costs + fills + EIA + drawdown gate)"
        return f"FAIL DEPENDS ON ASSUMPTIONS: robust pass under {why}"
    if e_base["total_usd"] > 0:
        return (f"FAIL ON ROBUSTNESS/RISK, NOT ON MONEY: gate-free walk-forward made ${e_base['total_usd']:,.0f} "
                f"after costs, but no config is robust enough to pick")
    if e_best["total_usd"] > 0:
        return (f"NO EDGE AFTER COSTS: gate-free walk-forward loses after costs, makes "
                f"${e_best['total_usd']:,.0f} only when trading is free and fills are optimistic")
    return "GENUINE FAIL: no out-of-sample edge even trading for free with optimistic fills, with or without gates"


# --- data checks -------------------------------------------------------------------------------------------

def volume_fingerprint(m: B.Minutes) -> dict:
    """Average volume per ET minute, split by US daylight-saving regime. Known market events must sit at
    the same ET minute in both regimes (a timezone or DST bug shifts one regime by 60 minutes)."""
    f = m.front & (m.et_day == m.trading_day) & (m.mod < 17 * 60)
    utc_mod = (m.ts // 60_000_000_000) % 1440
    dst = ((utc_mod - m.mod) % 1440) == 240  # EDT = UTC-4, EST = UTC-5
    wd = (m.et_day + 3) % 7  # 0 = Monday (1970-01-01 was a Thursday)
    out = {}
    for name, regime in (("daylight", dst), ("standard", ~dst)):
        k = f & regime
        prof = np.bincount(m.mod[k], weights=m.volume[k], minlength=1440) / np.maximum(
            np.bincount(m.mod[k], minlength=1440), 1)
        wed = k & (wd == 2)
        tue = k & (wd == 1)
        mean_at = lambda mask, a, b: float(m.volume[mask & (m.mod >= a) & (m.mod < b)].mean())  # noqa: E731
        win = prof[8 * 60 + 30:10 * 60]
        lags = range(-90, 91)
        out[name] = {
            "nymex_open_ratio": mean_at(k, 540, 545) / mean_at(k, 530, 535),  # 09:00-05 vs 08:50-55
            "eia_wed_vs_tue": mean_at(wed, 630, 632) / mean_at(tue, 630, 632),  # 10:30 Wed vs Tue
            "settlement_ratio": mean_at(k, 868, 871) / mean_at(k, 860, 865),  # 14:28-30 vs 14:20-25
            "peak_minute_0830_1000": f"{(510 + int(np.argmax(win))) // 60:02d}:{(510 + int(np.argmax(win))) % 60:02d}",
            "profile": prof,
        }
    a, b = out["daylight"]["profile"][6 * 60:16 * 60], out["standard"]["profile"][6 * 60:16 * 60]
    corr = {lag: np.corrcoef(a[max(0, lag):len(a) + min(0, lag)], b[max(0, -lag):len(b) - max(0, lag)])[0, 1]
            for lag in lags}
    lag_list = list(corr)
    vals = np.array([corr[k] for k in lag_list])
    out["best_lag_minutes"] = int(lag_list[int(np.nanargmax(vals))]) if np.isfinite(vals).any() else 9999
    for r in ("daylight", "standard"):
        out[r].pop("profile")
    ok = out["best_lag_minutes"] == 0 and all(
        out[r]["nymex_open_ratio"] > 1.2 and out[r]["eia_wed_vs_tue"] > 2 and out[r]["settlement_ratio"] > 1.2
        for r in ("daylight", "standard"))
    out["ok"] = bool(ok)
    return out


def fred_wti(cache: Path) -> pd.Series:
    """Daily WTI Cushing spot (EIA via FRED, free, no key). Cached after the first download."""
    if not cache.exists():
        cache.parent.mkdir(parents=True, exist_ok=True)
        with urllib.request.urlopen(FRED_URL, timeout=60) as r:  # noqa: S310 (fixed https URL)
            cache.write_bytes(r.read())
    return parse_fred(cache.read_text())


def parse_fred(text: str) -> pd.Series:
    from io import StringIO
    df = pd.read_csv(StringIO(text))
    df.columns = ["date", "value"]
    v = pd.to_numeric(df["value"], errors="coerce")  # "." = no fixing that day
    return pd.Series(v.to_numpy(), index=pd.to_datetime(df["date"])).dropna()


def compare_spot(close_usd: pd.Series, spot: pd.Series, contract: pd.Series | None = None) -> dict:
    """Our 14:30 ET front-month close vs the official spot price, same calendar dates.
    Spot tracks the EXPIRING contract; CL.v.0 rolls earlier by volume, so levels differ by the
    calendar spread (normal). Daily returns must still agree closely."""
    j = pd.concat([close_usd.rename("ours"), spot.rename("spot")], axis=1, join="inner").dropna()
    j = j[(j["spot"] > 0) & (j["ours"] > 0)]  # 2020-04-20: spot settled negative
    diff = (j["ours"] - j["spot"]).abs()
    ret = j.pct_change()
    if contract is not None:  # a roll day compares two different contracts: not a data error, skip it
        con = contract.reindex(j.index)
        ret = ret[con.eq(con.shift())]
    ret = ret.dropna()
    ret = ret[(ret.abs() < 0.5).all(axis=1)]
    corr = float(ret["ours"].corr(ret["spot"]))
    out = {"days": len(j), "return_corr": corr, "median_abs_diff_usd": float(diff.median()),
           "share_diff_over_2usd": float((diff > 2).mean()),
           "worst_days": diff.sort_values(ascending=False).head(5).round(2).to_dict()}
    out["ok"] = bool(corr > 0.9 and out["median_abs_diff_usd"] < 1.0)
    return out


def coverage(mk: E.Market, cal_years: np.ndarray) -> pd.DataFrame:
    """Share of trading days with a valid 09:00 ET 30-minute range, per year (thin data silently
    shrinking the sample would show up here)."""
    t = mk.t.keys.index(("et0900", 30)) if ("et0900", 30) in mk.t.keys else 0
    return (pd.DataFrame({"year": cal_years, "valid": mk.t.valid[t]})
            .groupby("year")["valid"].agg(days="size", valid_share="mean").round(3))


# --- engine checks on real data ---------------------------------------------------------------------------

def coin_flip(mk: E.Market, n: int, slip: float, seed=SEED) -> dict:
    """Random daytime minutes; at each, a long AND a short: market in, market out 60 minutes later through
    the engine's own exit code. Accounting check: every pair nets exactly -2 x (fee + 2 x slip x $10)
    (gross sums to 0). Market diagnostic: one random side per pair has mean ~ -(fee + 2 slips)."""
    f = mk.f
    rng = np.random.default_rng(seed)
    ok = (f.mod >= 9 * 60) & (f.mod < 14 * 60) & (f.et_day == f.trading_day)
    cand = np.flatnonzero(ok[:-200])
    r = [np.empty(1, np.int64), np.empty(1, np.int64), np.empty(1, np.int8), np.empty(1), np.empty(1),
         np.empty(1), np.empty(1, np.int8)]
    pair_err, single = [], []
    for k in rng.choice(cand, n, replace=False):
        if f.contract[k] != f.contract[min(k + 120, len(f) - 1)] or f.cut[k]:
            continue
        pnl = {}
        for d in (1, -1):
            fill = f.open[k] + d * slip
            FE.hold_position(k, False, d, fill, fill - d * 1e6, 0.0, False, 0.0, f.tmin[k] + 60, f.contract[k], k,
                             f.tmin, f.open, f.high, f.low, f.close, f.contract, f.cut, slip, True, 0, *r)
            pnl[d] = P.trade_pnl_usd(d, r[3][0], r[4][0])
        pair_err.append(pnl[1] + pnl[-1] + 2 * (P.FEE_USD + 2 * slip * P.TICK_USD))
        single.append(pnl[int(rng.choice([-1, 1]))])
    single = np.array(single)
    if len(single) == 0:
        return {"pairs": 0, "max_pair_error_usd": np.nan, "mean_usd": np.nan, "expected_usd": np.nan,
                "se_usd": np.nan, "z": np.nan, "ok": False}
    expected = -(P.FEE_USD + 2 * slip * P.TICK_USD)
    se = single.std() / math.sqrt(len(single))
    return {"pairs": len(single), "max_pair_error_usd": float(np.abs(pair_err).max()),
            "mean_usd": float(single.mean()), "expected_usd": expected, "se_usd": float(se),
            "z": float((single.mean() - expected) / se),
            "ok": bool(np.abs(pair_err).max() < 1e-6 and abs(single.mean() - expected) < 2.58 * se)}


def fill_audit(mk: E.Market, t, m: B.Minutes, slip=1.0, names=E.EXIT_NAMES) -> dict:
    """Execution realism of one champion's trades."""
    f = mk.f
    d, pin, pout, mae, why = t[3], t[4], t[5], t[6], t[7]
    gap_entry = np.abs(pin - (f.open[t[1]] + d * slip)) < 1e-9
    loss_ticks = -d * (pout - pin)
    vol_in = f.volume[t[1]]
    return {
        "trades": int(len(d)),
        "entries_at_minute_open_pct": float(gap_entry.mean() * 100),  # market / close-confirmed / gapped stop
        "exit_mix_pct": pd.Series([names[int(w)] for w in why]).value_counts(normalize=True)
                          .mul(100).round(1).to_dict(),
        "thin_entry_minute_pct": float((vol_in < 5).mean() * 100),  # fewer than 5 contracts traded that minute
        "mae_below_realized_loss_pct": float(((loss_ticks > mae + slip + 1e-9) & (loss_ticks > 0)).mean() * 100),
        "same_contract": bool((f.contract[t[1]] == f.contract[t[2]]).all()),
        "exit_after_entry": bool((f.tmin[t[2]] >= f.tmin[t[1]]).all()),
    }


def both_sides_ties(mk: E.Market, cfg) -> dict:
    """Days where the first breakout minute touched BOTH levels (the engine then assumes the side nearer
    the open went first). Shows how much the tie rule can matter for a two-sided config."""
    t = mk.t
    tb = int(cfg[E.C_TABLE]) if len(cfg) == E.N_CFG_COLS else None
    if tb is None:
        return {"applies": False}
    f = mk.f
    buf = float(cfg[E.C_BUFFER])
    days = ties = 0
    for d in np.flatnonzero(t.valid[tb]):
        e = t.e_idx[tb, d]
        hi, lo = t.hi[tb, d] + 1 + buf, t.lo[tb, d] - 1 - buf
        j = e
        while j < len(f) and f.contract[j] == f.contract[e] and f.tmin[j] < t.sess_end[d]:
            up, dn = f.high[j] >= hi, f.low[j] <= lo
            if up or dn:
                days += 1
                ties += bool(up and dn)
                break
            j += 1
    return {"applies": True, "breakout_days": days, "tie_days": ties,
            "tie_pct": float(100 * ties / days) if days else 0.0}


def rolling_windows(day_pnl: np.ndarray, day_low: np.ndarray, length: int) -> dict:
    """Real consecutive Combine attempts (every start day, no resampling): pass / fail share."""
    res = [P._combine_attempt(day_pnl, day_low, np.array([s]), length)[0]
           for s in range(0, len(day_pnl) - length + 1)]
    res = np.array(res)
    return {"windows": len(res), "pass_pct": float((res == 1).mean() * 100), "fail_pct": float((res == -1).mean() * 100)}


def hac_effective_n(x: np.ndarray, lags=10) -> float:
    """Effective sample size of an autocorrelated daily series (Bartlett-weighted autocorrelations)."""
    x = x - x.mean()
    v = (x * x).mean()
    if v == 0:
        return float(len(x))
    rho = [(x[k:] * x[:-k]).mean() / v for k in range(1, lags + 1)]
    factor = 1 + 2 * sum((1 - k / (lags + 1)) * r for k, r in enumerate(rho, 1))
    return float(len(x) / max(factor, 1e-9))


def dsr_at(daily: np.ndarray, sharpe_var: float, n_trials: float, n_obs: float) -> float:
    """orb_search.deflated_sharpe with an explicit (effective) sample size. A copy, not a call: orb_search.py
    is part of every frozen pick's source hash, so changing its signature would void those picks."""
    sd = daily.std()
    if sd == 0 or n_trials < 2:
        return float("nan")
    sr = daily.mean() / sd
    nd = NormalDist()
    g = 0.5772156649
    sr0 = math.sqrt(sharpe_var) * ((1 - g) * nd.inv_cdf(1 - 1 / n_trials) + g * nd.inv_cdf(1 - 1 / (n_trials * math.e)))
    x = daily - daily.mean()
    skew, kurt = (x ** 3).mean() / sd ** 3, (x ** 4).mean() / sd ** 4
    denom = math.sqrt(max(1e-12, 1 - skew * sr + (kurt - 1) / 4 * sr ** 2))
    return nd.cdf((sr - sr0) * math.sqrt(max(n_obs - 1, 1)) / denom)


# --- signal edge: is the IDEA right, whatever the stops and targets? ------------------------------------

HORIZONS = [5, 15, 30, 60, 120]  # minutes after the entry; plus "session end"
N_RANDOM_PER_SIGNAL = 20
MAX_HORIZON_GAP = 5  # minutes: a horizon landing further into a data gap is not measured


class Paths:
    """Uncensored price paths after an entry, on the entry's contract, until the day's flat time."""

    def __init__(self, f: E.Front, days: np.ndarray):
        self.f = f
        self.days = days
        self.flat = E.session_end(f, days)
        self.day_of_row = np.searchsorted(days, f.trading_day)
        keys = f.trading_day.astype(np.int64) * 1440 + f.mod
        self.order = np.argsort(keys, kind="stable")
        self.sorted_keys = keys[self.order]

    def row_at(self, trading_day: int, mod: int) -> int:
        """Front row of exactly this trading day and ET minute, -1 if that minute did not trade."""
        key = trading_day * 1440 + mod
        k = np.searchsorted(self.sorted_keys, key)
        return int(self.order[k]) if k < len(self.sorted_keys) and self.sorted_keys[k] == key else -1

    def window(self, row: int, from_open: bool) -> tuple[int, int]:
        """Minutes held: same contract, before the flat time. A fill at the minute's open holds that whole
        minute (from_open); a stop fill inside the minute starts at the next one (its minute traded before it)."""
        f = self.f
        flat = self.flat[self.day_of_row[row]]
        end = int(np.searchsorted(f.tmin, flat))
        nxt = np.flatnonzero(f.contract[row:end] != f.contract[row])
        return row + (0 if from_open else 1), (row + int(nxt[0]) if len(nxt) else end)

    def measure(self, row: int, side: int, ref: float, from_open: bool) -> dict:
        """Signed move at each horizon (ticks) and MFE / MAE up to it. NaN when the horizon is after the flat
        time or falls in a data gap (no trade within MAX_HORIZON_GAP minutes of it)."""
        f = self.f
        a, b = self.window(row, from_open)
        out = {"move": np.full(len(HORIZONS) + 1, np.nan), "mfe": np.full(len(HORIZONS) + 1, np.nan),
               "mae": np.full(len(HORIZONS) + 1, np.nan)}
        if b <= a:
            return out
        fav = side * ((f.high[a:b] if side == 1 else f.low[a:b]) - ref)
        adv = side * (ref - (f.low[a:b] if side == 1 else f.high[a:b]))
        run_fav, run_adv = np.maximum.accumulate(fav), np.maximum.accumulate(adv)
        targets = [f.tmin[row] + h for h in HORIZONS]
        ends = [int(np.searchsorted(f.tmin[a:b], x)) for x in targets]
        ok = [k < b - a and f.tmin[a + k] - x <= MAX_HORIZON_GAP for k, x in zip(ends, targets)] + [True]
        ends.append(b - a)  # session end: the open of the flat minute (or the last minute before it)
        for q, (k, good) in enumerate(zip(ends, ok)):
            if not good or k == 0:
                continue
            j = a + k
            same = j < len(f) and f.contract[j] == f.contract[row]
            px = f.open[j] if same else f.close[j - 1]  # the engine exits at the open of that minute
            out["move"][q] = side * (px - ref)
            out["mfe"][q], out["mae"][q] = run_fav[k - 1], run_adv[k - 1]
        return out

    def ran_after(self, row: int, side: int, ref: float, loss: float) -> bool:
        """After minute `row`, did price reach ref + loss in our favour before the flat time?"""
        a, b = self.window(row, False)
        f = self.f
        best = (f.high[a:b].max() if side == 1 else f.low[a:b].min()) if b > a else ref
        return bool(side * (best - ref) >= loss)

    def stop_then_ran(self, row: int, side: int, ref: float, loss: float) -> int:
        """Random-entry version of the stop hunt: -1 = never fell `loss` against us; 1 = fell, then later
        reached +`loss`; 0 = fell and never recovered."""
        a, b = self.window(row, True)
        f = self.f
        if b <= a:
            return -1
        adv = side * (ref - (f.low[a:b] if side == 1 else f.high[a:b]))
        hit = np.flatnonzero(adv >= loss)
        if not len(hit):
            return -1
        rest = slice(a + hit[0] + 1, b)
        fav = side * ((f.high[rest] if side == 1 else f.low[rest]) - ref)
        return int(len(fav) > 0 and fav.max() >= loss)

    def matched_rows(self, days: np.ndarray, mod: int, skip_day: int, n: int, rng, used=None, side=0) -> list[int]:
        """Up to n rows at this ET minute on distinct random days (without replacement), skipping the
        signal's own day and days on which that minute did not trade. With `used` (a set of (day, minute,
        side)), a control is never reused and claims its slot: controls of different signals stay independent."""
        out = []
        for d in rng.permutation(days):
            if int(d) == skip_day or (used is not None and (int(d), mod, side) in used):
                continue
            r = self.row_at(int(d), mod)
            if r >= 0:
                out.append(r)
                if used is not None:
                    used.add((int(d), mod, side))
                if len(out) == n:
                    break
        return out


def clustered(diff: np.ndarray, day: np.ndarray) -> tuple[float, float, int]:
    """Mean paired difference ($) and its z with trading days as clusters (signals on one day, e.g. an ACD A
    trade and its C reversal, are not independent). Returns (mean $, z, days)."""
    ok = ~np.isnan(diff)
    if ok.sum() < 30:
        return np.nan, np.nan, int(ok.sum())
    by_day = pd.Series(diff[ok]).groupby(day[ok]).sum()
    count = pd.Series(1, index=day[ok]).groupby(day[ok]).sum()
    mean = by_day.sum() / count.sum()
    resid = by_day - mean * count  # per-day sum of deviations: the cluster-robust variance
    k = len(by_day)
    var = (resid ** 2).sum() / count.sum() ** 2 * k / max(k - 1, 1)
    return float(mean * P.TICK_USD), float(mean / math.sqrt(var)) if var > 0 else np.nan, k


def signal_edge(paths: Paths, t, slip: float, stop_exit: int, rng, dev_days: np.ndarray, keep_raw=False,
                exclusive_controls=False) -> dict:
    """Frozen entries of one champion vs random entries at the same ET minute and side. Gross ticks.
    Two matched baselines per signal (without replacement): random days from the whole period ("global"),
    and from the 20 trading days either side ("local": same market regime, so a signal that only rides a
    crash or a trend shows no edge). Paired: each signal minus the mean of its own random entries; z with
    trading days as clusters. Under a martingale (no predictable drift), no stop or target can create gross
    expectancy; a fixed-horizon test cannot rule out every path-dependent exit, so 'no edge' here means
    no demonstrated fixed-horizon edge."""
    f = paths.f
    n_h = len(HORIZONS) + 1
    diff_g, diff_l, sig_move, day, years, first, ctrl_l = [], [], [], [], [], [], []
    mfe = {"signal": [], "random": []}
    mae = {"signal": [], "random": []}
    stop_sig = stop_rnd = stop_n = stop_rnd_n = 0
    seen_days = set()
    # exclusive: each same-weeks control (day, minute, side) serves one signal only, and never a signal's slot
    used = {(int(f.trading_day[r]), int(f.mod[r]), int(d)) for r, d in zip(t[1], t[3])} if exclusive_controls else None
    for q in range(len(t[1])):
        row, side = int(t[1][q]), int(t[3][q])
        ref = float(t[4][q]) - side * slip  # the fill before slippage
        from_open = abs(ref - f.open[row]) < 1e-9
        td, mod = int(f.trading_day[row]), int(f.mod[row])
        k = int(np.searchsorted(dev_days, td))
        local = np.r_[dev_days[max(0, k - 20):k], dev_days[k + 1:k + 21]]
        rows_g = paths.matched_rows(dev_days, mod, td, N_RANDOM_PER_SIGNAL, rng)
        rows_l = paths.matched_rows(local, mod, td, N_RANDOM_PER_SIGNAL, rng, used, side)
        if not rows_g or not rows_l:
            continue
        s_ = paths.measure(row, side, ref, from_open)
        m_g = [paths.measure(r, side, float(f.open[r]), True) for r in rows_g]
        r_l = np.vstack([paths.measure(r, side, float(f.open[r]), True)["move"] for r in rows_l])
        with np.errstate(all="ignore"):
            diff_g.append(s_["move"] - np.nanmean(np.vstack([x["move"] for x in m_g]), axis=0))
            diff_l.append(s_["move"] - np.nanmean(r_l, axis=0))
        sig_move.append(s_["move"])
        pad = np.full((N_RANDOM_PER_SIGNAL, n_h), np.nan)
        pad[:len(r_l)] = r_l
        ctrl_l.append(pad)
        day.append(td)
        years.append(pd.Timestamp(td, unit="D").year)
        first.append(td not in seen_days)
        seen_days.add(td)
        mfe["signal"].append(s_["mfe"])
        mae["signal"].append(s_["mae"])
        mfe["random"].extend(x["mfe"] for x in m_g)
        mae["random"].extend(x["mae"] for x in m_g)
        if int(t[7][q]) == stop_exit:
            loss = side * (ref - (float(t[5][q]) + side * slip))  # entry to stop level, ticks
            if loss >= 1:
                stop_n += 1
                stop_sig += paths.ran_after(int(t[2][q]), side, ref, loss)
                for r in rows_g:
                    o = paths.stop_then_ran(r, side, float(f.open[r]), loss)
                    if o >= 0:
                        stop_rnd_n += 1
                        stop_rnd += o
    as2d = lambda xs: np.vstack(xs) if xs else np.full((0, n_h), np.nan)  # noqa: E731
    sig_move, d_g, d_l = as2d(sig_move), as2d(diff_g), as2d(diff_l)
    day, years, first = np.array(day), np.array(years), np.array(first, bool)
    early = years < 2016
    out = {"signals": len(sig_move), "days": len(set(day.tolist())), "random_per_signal": N_RANDOM_PER_SIGNAL,
           "horizons": []}
    for q, h in enumerate([*map(str, HORIZONS), "session end"]):
        g, z_g, n = clustered(d_g[:, q], day)
        if not np.isfinite(g):
            continue
        loc, z_l, _ = clustered(d_l[:, q], day)
        g1, z1, _ = clustered(d_g[early, q], day[early])
        g2, z2, _ = clustered(d_g[~early, q], day[~early])
        g_first, z_first, _ = clustered(d_g[first, q], day[first])
        med = lambda xs: float(np.nanmedian(as2d(xs)[:, q]) * P.TICK_USD)  # noqa: E731
        out["horizons"].append({
            "horizon": h, "days": n, "signal_usd": float(np.nanmean(sig_move[:, q]) * P.TICK_USD),
            "edge_usd": g, "z": z_g, "local_edge_usd": loc, "local_z": z_l,
            "edge_2010_15": g1, "z_2010_15": z1, "edge_2016_21": g2, "z_2016_21": z2,
            "first_of_day_edge_usd": g_first, "first_of_day_z": z_first,
            "signal_mfe_med": med(mfe["signal"]), "random_mfe_med": med(mfe["random"]),
            "signal_mae_med": med(mae["signal"]), "random_mae_med": med(mae["random"])})
    out["stop_exits"] = stop_n
    p1 = stop_sig / stop_n if stop_n else np.nan
    p2 = stop_rnd / stop_rnd_n if stop_rnd_n else np.nan
    out["stop_then_ran_pct"], out["random_stop_then_ran_pct"] = 100 * p1, 100 * p2
    se = math.sqrt(p1 * (1 - p1) / stop_n + p2 * (1 - p2) / stop_rnd_n) if stop_n and stop_rnd_n else np.nan
    out["stop_hunt_z"] = (p1 - p2) / se if se and se > 0 else np.nan  # trades treated as independent: indicative
    zs = [x["z"] for x in out["horizons"] if np.isfinite(x["z"])]
    out["best_z"] = max(zs) if zs else np.nan
    if keep_raw:  # per signal, ticks: for pre-registered tests on exactly these numbers
        out["raw"] = {"move": sig_move, "diff_local": d_l, "diff_global": d_g, "day": day,
                      "controls_local": np.stack(ctrl_l) if ctrl_l else np.full((0, N_RANDOM_PER_SIGNAL, n_h), np.nan)}
    return out


def signal_verdict(e: dict) -> str:
    """Bonferroni over the horizons (one 'significant' horizon of six is expected by luck at z ~ 2). An edge
    must beat the global AND the local (same-regime) baseline AND be positive in both halves. The champion
    was selected on these same days, so even a pass here is in-sample evidence only."""
    if not e["horizons"]:
        return "too few signals"
    z_crit = NormalDist().inv_cdf(1 - 0.05 / (2 * len(e["horizons"])))
    beat = [x for x in e["horizons"] if x["z"] > z_crit and x["edge_usd"] > 0]
    if not beat:
        return (f"NO DEMONSTRATED DIRECTIONAL EDGE: at no fixed horizon do the signals beat random entries "
                f"(best day-clustered z {e['best_z']:.2f} < {z_crit:.2f})")
    robust = [x for x in beat if x["local_z"] > z_crit  # a half without signals (NaN) does not veto
              and not x["edge_2010_15"] <= 0 and not x["edge_2016_21"] <= 0]
    if not robust:
        return (f"REGIME / LUCK, NOT A SIGNAL: beats random entries over the whole period but not random entries "
                f"in the same weeks, or not in both halves (z > {z_crit:.2f} needed)")
    best = max(robust, key=lambda x: x["local_z"])
    return (f"IN-SAMPLE DIRECTIONAL EDGE at {best['horizon']} min: +${best['edge_usd']:.2f}/trade gross vs random "
            f"(same weeks +${best['local_edge_usd']:.2f}, day-clustered z {best['local_z']:.2f}; both halves "
            f"positive). Selected on these days: exploratory until confirmed out of sample")


# --- trade chart -------------------------------------------------------------------------------------------

def svg_trade(f: E.Front, i_in: int, i_out: int, d: int, pin: float, pout: float, rng_hi=None, rng_lo=None,
              title="") -> str:
    a, b = max(0, i_in - 30), min(len(f) - 1, i_out + 10)
    b = min(b, a + 400)
    lo = min(f.low[a:b + 1].min(), pin, pout) - 2
    hi = max(f.high[a:b + 1].max(), pin, pout) + 2
    if rng_hi is not None:
        lo, hi = min(lo, rng_lo - 2), max(hi, rng_hi + 2)
    W, H = 760, 220
    n = b - a + 1
    x = lambda k: 10 + (k - a) * (W - 20) / max(n, 1)  # noqa: E731
    y = lambda p: 10 + (hi - p) * (H - 20) / max(hi - lo, 1)  # noqa: E731
    bw = max(1.0, (W - 20) / max(n, 1) * 0.7)
    parts = [f'<svg viewBox="0 0 {W} {H}" role="img" aria-label="{title}">']
    if rng_hi is not None:
        for lvl in (rng_hi, rng_lo):
            parts.append(f'<line x1="10" x2="{W - 10}" y1="{y(lvl):.1f}" y2="{y(lvl):.1f}" class="rng"/>')
    for k in range(a, b + 1):
        up = f.close[k] >= f.open[k]
        parts.append(f'<line x1="{x(k):.1f}" x2="{x(k):.1f}" y1="{y(f.high[k]):.1f}" y2="{y(f.low[k]):.1f}" class="wick"/>')
        top, bot = y(max(f.open[k], f.close[k])), y(min(f.open[k], f.close[k]))
        parts.append(f'<rect x="{x(k) - bw / 2:.1f}" y="{top:.1f}" width="{bw:.1f}" height="{max(bot - top, 0.8):.1f}" '
                     f'class="{"up" if up else "dn"}"/>')
    for k, p, cls in ((i_in, pin, "entry"), (i_out, pout, "exit")):
        parts.append(f'<circle cx="{x(k):.1f}" cy="{y(p):.1f}" r="5" class="{cls}"/>')
    parts.append("</svg>")
    return "".join(parts)


def chart_html(sections: list[tuple[str, list[str]]]) -> str:
    css = """
:root{--bg:#fafaf9;--fg:#1c1917;--mut:#57534e;--line:#d6d3d1;--up:#15803d;--dn:#b91c1c;--in:#1d4ed8;--out:#a16207}
@media (prefers-color-scheme:dark){:root{--bg:#1c1917;--fg:#f5f5f4;--mut:#a8a29e;--line:#44403c;--up:#4ade80;--dn:#f87171;--in:#60a5fa;--out:#facc15}}
body{background:var(--bg);color:var(--fg);font:14px/1.5 system-ui,sans-serif;margin:0;padding:16px;max-width:820px;margin:auto}
h1{font-size:20px}h2{font-size:16px;margin-top:32px}p.t{color:var(--mut);margin:12px 0 2px}
svg{width:100%;height:auto;border:1px solid var(--line);border-radius:6px}
.wick{stroke:var(--mut);stroke-width:1}.up{fill:var(--up)}.dn{fill:var(--dn)}
.rng{stroke:var(--mut);stroke-dasharray:4 3}.entry{fill:none;stroke:var(--in);stroke-width:2.5}
.exit{fill:none;stroke:var(--out);stroke-width:2.5}"""
    body = ["<h1>Champion trades on 1-minute candles</h1>",
            "<p>Blue ring = entry fill, amber ring = exit fill, dashed = opening range. Check that every entry "
            "happens after the range and every fill sits at a price the candle actually traded.</p>"]
    for name, items in sections:
        body.append(f"<h2>{name}</h2>")
        body.extend(items)
    return (f"<!doctype html><html><head><meta charset='utf-8'><meta name='viewport' content='width=device-width'>"
            f"<title>Champion trade charts</title><style>{css}</style></head><body>{''.join(body)}</body></html>")


# --- report ------------------------------------------------------------------------------------------------

def champion(strategy: str):
    fp = json.loads((out_dir(strategy) / "frozen_picks.json").read_text())
    if strategy == "ema_vwap":
        return tuple(fp["picks"][0][k] for k in ["timeframe", "ema", "vwap_anchor", "entry", "stop_ticks", "session"])
    return np.array(fp["champion_cfg"], np.int64)


def build_report() -> int:
    from propfirm_data.eia_calendar import load_releases

    from . import orb_search as O
    from . import search as S
    from .family_search import FAMILIES

    AUDIT_DIR.mkdir(parents=True, exist_ok=True)
    L = ["# Backtest audit: is each FAIL a real FAIL?", "",
         f"Generated {pd.Timestamp.now(tz='UTC'):%Y-%m-%d %H:%M} UTC. Development data only (2010-06 -> 2021-12).", ""]
    checks = []  # (check, result, ok)

    print("Loading development data...", flush=True)
    m = B.load_minutes(end=S.DEV_END)
    cal = S.Calendar(m)
    assert cal.n_dev == len(cal.days), "holdout data must not be loaded here"
    eia = load_releases()

    print("Data: volume fingerprint, spot cross-check, coverage...", flush=True)
    vf = volume_fingerprint(m)
    checks.append(("Timezone/DST: volume spikes at 09:00, Wed 10:30, 14:28-30 ET in both regimes; "
                   "best profile lag", f"lag {vf['best_lag_minutes']} min; " + "; ".join(
                       f"{r}: open x{vf[r]['nymex_open_ratio']:.2f}, EIA x{vf[r]['eia_wed_vs_tue']:.2f}, "
                       f"settle x{vf[r]['settlement_ratio']:.2f}, peak {vf[r]['peak_minute_0830_1000']}"
                       for r in ("daylight", "standard")), vf["ok"]))
    mk = E.Market(m, cal.days, eia, strict_expiry=True)
    sess = F.Sessions(mk.f, cal.days, "et0900")
    ours = pd.Series(sess.close / 100.0, index=pd.to_datetime(cal.days, unit="D"))[sess.valid]
    try:
        con = pd.Series(sess.contract, index=pd.to_datetime(cal.days, unit="D"))[sess.valid]
        sp = compare_spot(ours, fred_wti(AUDIT_DIR / "fred_wti.csv"), con)
        checks.append(("Prices vs official WTI spot (EIA via FRED), 2010-2021",
                       f"{sp['days']:,} days, daily-return correlation {sp['return_corr']:.3f}, median |level diff| "
                       f"${sp['median_abs_diff_usd']:.2f}, {sp['share_diff_over_2usd']:.1%} of days > $2", sp["ok"]))
    except OSError as exc:
        sp = None
        checks.append(("Prices vs official WTI spot", f"download failed: {exc}", None))
    cov = coverage(mk, cal.years)

    print("Engine: coin flip on real data...", flush=True)
    cf = {s: coin_flip(mk, N_COIN, s) for s in (0.0, 1.0)}
    for s, r in cf.items():
        checks.append((f"Coin flip, {r['pairs']:,} random long+short 60-min market pairs, slip {s:g}",
                       f"every pair nets 2 x costs (max error ${r['max_pair_error_usd']:.2g}); one random side: mean "
                       f"${r['mean_usd']:.2f} vs expected ${r['expected_usd']:.2f} (z = {r['z']:.2f})", r["ok"]))

    print("Champions: fills, ties, rolling windows, effective-N deflated Sharpe...", flush=True)
    rows, charts = [], []
    rng = np.random.default_rng(SEED)
    for strategy in STRATEGIES:
        if not (out_dir(strategy) / "frozen_picks.json").exists():
            continue
        c = champion(strategy)
        if strategy == "ema_vwap":
            tt = S.single(m, cal, c)
            fmk = E.Market(m, cal.days, eia)  # fill audit on front-month minute rows
            row_of = np.full(len(m), -1)
            row_of[fmk.f.src] = np.arange(len(fmk.f))
            keep = (row_of[tt[0]] >= 0) & (row_of[tt[1]] >= 0)  # EMA trades live on front-month minutes
            t = (None,) + tuple(x[keep] for x in (row_of[tt[0]], row_of[tt[1]], tt[2], tt[3], tt[4], tt[5], tt[6]))
            ties = {"applies": False}
            pnl = P.trade_pnl_usd(tt[2], tt[3], tt[4])
            day = cal.day_of(m.trading_day[tt[1]])
            dp, dl = P.daily_series(day, pnl, tt[5] * P.TICK_USD + P.FEE_USD, cal.n_dev)
            cmk = fmk
        else:
            fam = O.ORB if strategy == "orb" else FAMILIES[strategy]
            cmk = fam.market(m, cal.days, eia, strict_expiry=True)
            t = cmk.trades(c, n_days=cal.n_dev)
            ties = both_sides_ties(cmk, c) if strategy == "orb" else {"applies": False}
            dp, dl = P.daily_series(t[0], P.trade_pnl_usd(t[3], t[4], t[5]), t[6] * P.TICK_USD + P.FEE_USD, cal.n_dev)
        names = EN.EXIT_NAMES if strategy == "ema_vwap" else E.EXIT_NAMES
        fa = fill_audit(cmk, t, m, names=names)
        res = load_results(out_dir(strategy))
        has_trials = res is not None and "sharpe_daily" in res
        sv = float(np.var(res["sharpe_daily"])) if has_trials else np.nan
        n_trials = len(res) if has_trials else 0
        traded = dp != 0
        stop_code = EN.EXIT_STOP if strategy == "ema_vwap" else E.EXIT_STOP
        edge = signal_edge(Paths(cmk.f, cal.days), t, 1.0, stop_code, np.random.default_rng(SEED + 1), cal.days)
        rows.append({"strategy": TITLES[strategy], **fa, "ties": ties, "edge": edge,
                     "rolling_60": rolling_windows(dp, dl, 60), "rolling_250": rolling_windows(dp, dl, 250),
                     "dsr_iid": dsr_at(dp, sv, n_trials, len(dp)) if has_trials else np.nan,
                     "dsr_hac": dsr_at(dp, sv, n_trials, hac_effective_n(dp)) if has_trials else np.nan,
                     "traded_days": int(traded.sum())})
        checks.append((f"{TITLES[strategy]}: every trade enters and exits on one contract, exit after entry",
                       f"{fa['trades']:,} trades", fa["same_contract"] and fa["exit_after_entry"]))
        pick = rng.choice(len(t[1]), min(N_CHART, len(t[1])), replace=False) if len(t[1]) else []
        items = []
        for q in sorted(pick):
            i_in, i_out = int(t[1][q]), int(t[2][q])
            hi = lo = None
            if strategy != "ema_vwap":
                tb = int(c[E.C_TABLE] if strategy == "orb" else c[FE.C_TABLE])
                hi, lo = cmk.t.hi[tb, t[0][q]], cmk.t.lo[tb, t[0][q]]
            ts = pd.Timestamp(int(cmk.f.tmin[i_in]) * E.NS_PER_MIN, tz="UTC").tz_convert(E.ET)
            items.append(f"<p class='t'>{ts:%Y-%m-%d %H:%M} ET, {'long' if t[3][q] > 0 else 'short'}, "
                         f"{names.get(int(t[7][q]), '?')} exit, "
                         f"${P.trade_pnl_usd(t[3][q], t[4][q], t[5][q]):,.0f}</p>")
            items.append(svg_trade(cmk.f, i_in, i_out, int(t[3][q]), float(t[4][q]), float(t[5][q]), hi, lo))
        charts.append((TITLES[strategy], items))

    print("Pipelines: baseline vs scenarios, gate attribution, positive control...", flush=True)
    summ, verdicts, attrib, econ = {}, {}, {}, {}
    for strategy in STRATEGIES:
        base = summary(strategy, out_dir(strategy))
        scen = {k: summary(strategy, out_dir(strategy, k)) for k in SCENARIOS}
        summ[strategy] = (base, scen)
        econ[strategy] = {k: gate_free_wf(out_dir(strategy, k) / "yearly.npz") for k in SCENARIOS}
        verdicts[strategy] = verdict(base, scen, econ[strategy])
        a = scen.get("baseline")
        if base and a:
            same = all(base[k] == a[k] for k in ("configs", "profitable", "pass_gates", "champion_expectancy"))
            checks.append((f"{TITLES[strategy]}: audit re-run reproduces the main run", "identical counts and champion"
                           if same else f"main {base} vs audit {a}", same))
        df = load_results(out_dir(strategy))
        if df is not None:
            attrib[strategy] = gate_attribution(strategy, df)
    ctrl = {}  # drift -> {gate: summary}
    for drift in CONTROL_DRIFTS:
        for gate in CONTROL_GATES:
            s = summary("orb", control_dir(drift, gate) / "backtests" / "orb_quick")
            if s:
                ctrl.setdefault(drift, {})[gate] = s
    passed = lambda s: bool(s and s["champion_eligible"] and s["wf_total"] > 0)  # noqa: E731
    for gate, label in (("no_dd_gate", "without the drawdown gate"), ("gates", "with every gate incl. p95 DD <= $1,000")):
        runs = {d: g.get(gate) for d, g in ctrl.items() if g.get(gate)}
        if not runs:
            continue
        found = [d for d, s in runs.items() if d > 0 and passed(s)]
        noise_ok = not passed(runs.get(0.0))
        checks.append((f"Positive control (ORB quick grid, real minutes, drift planted after the 09:00-09:30 "
                       f"breakout in its direction), {label}",
                       (f"found from drift {min(found):g} ticks/min (~${min(found) * CONTROL_LEN * P.TICK_USD:.0f}/trade)"
                        if found else "NOT found at any drift") + ("" if noise_ok else "; ALSO 'found' with no drift"),
                       (bool(found) and noise_ok) if gate == "no_dd_gate" else None))

    # --- write ---
    L += ["## Verdicts", "", "| Strategy | Verdict |", "|---|---|"]
    L += [f"| {TITLES[s]} | {verdicts[s]} |" for s in STRATEGIES]
    L += ["", "**How to read it.** Two questions, kept apart: (1) is there a ROBUST pick (gates + plateau + "
          "walk-forward), under real or best-case assumptions; (2) is there out-of-sample MONEY at all (gate-free "
          "walk-forward: each year take the most profitable config so far, book the next year). "
          "GENUINE FAIL = no to both, even trading for free with every 1-minute ambiguity resolved in our favour. "
          "NO EDGE AFTER COSTS = money only appears when costs are zero. FAIL ON ROBUSTNESS/RISK = money after "
          "costs, but too fragile or too deep in drawdown for the 50K / 1 CL rules.",
          "", "Strategy 1 note: the EMA x VWAP holdout (2022+) was opened before these rule fixes, so the new "
          "picks in ema_vwap_v2 have NO clean holdout; they are development evidence only.", ""]
    L += ["## Checks", "", "| Check | Result | OK |", "|---|---|---|"]
    L += [f"| {a} | {b} | {'✅' if ok else ('⚠️' if ok is None else '❌')} |" for a, b, ok in checks]
    L += ["", "## Pipelines under other assumptions", "",
          "zero_cost = $0 fee, 0 slip (stress gate +1 tick) · risk_2000 = drawdown gate $2,000 · "
          "best_case = $0 fee, 0 slip, no stress gate, optimistic fills, no EIA block, no drawdown gate", "",
          "Walk-forward = the full selector (gates + plateau) re-run each year 2014-2021 on earlier years only. "
          "Gate-free WF = each year simply take the most profitable config so far (>= 100 and 25/year trades): "
          "pure out-of-sample money, no robustness rules.", "",
          "| Strategy | Run | Configs | Profitable | Pass gates | Eligible | Champion $/trade | Walk-forward $ | "
          "WF years with a pick | Gate-free WF $ | Gate-free WF $/trade | DSR |",
          "|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for s in STRATEGIES:
        base, scen = summ[s]
        for name, r in [("main run", base)] + list(scen.items()):
            if r:
                e = econ[s].get(name) or {}
                L.append(f"| {TITLES[s]} | {name} | {r['configs']:,} | {r['profitable']:,} | {r['pass_gates']:,} | "
                         f"{r['eligible']:,} | {r['champion_expectancy']:.2f} | {r['wf_total']:,.0f} | "
                         f"{r['wf_years_qualified']} / {len(WF_YEARS)} | {e.get('total_usd', float('nan')):,.0f} | "
                         f"{e.get('per_trade_usd', float('nan')):.2f} | {r['dsr']:.3f} |")
    L += ["", "## Which gate is the wall (baseline)", "",
          "Configs that fail exactly ONE gate, by that gate; and configs passing every gate if the drawdown "
          "gate were $2,000 or off (before plateau / walk-forward).", "",
          "| Strategy | Single-gate failures | Pass with DD $2,000 | Pass with DD off |", "|---|---|---|---|"]
    for s, a in attrib.items():
        single = ", ".join(f"{k} {v:,}" for k, v in a.items() if not k.startswith("_")) or "-"
        L.append(f"| {TITLES[s]} | {single} | {a['_dd_relaxed_2000_pass']:,} | {a['_dd_off_pass']:,} |")
    if ctrl:
        L += ["", "## Positive control (planted edge, ORB quick grid, real 2010-2021 minutes)", "",
              "From the first minute that breaks the 09:00-09:30 ET range, the price is pushed in the breakout "
              f"direction by the drift for {CONTROL_LEN} minutes: an edge in ORB's own language, causal. Each "
              "drift runs the full pipeline twice: every gate, and every gate except the p95 drawdown gate. "
              "Detection without the DD gate proves the pipeline can find an edge; the DD-gate column shows "
              "how big an edge must be before 1 CL fits the $1,000 drawdown budget.", "",
              "| Drift ticks/min | ~planted $/trade | Champion $/trade | Lowest p95 DD of a profitable config | "
              "All gates: robust pick, WF $ | No DD gate: robust pick, WF $ |", "|---|---|---|---|---|---|"]
        for d, g in ctrl.items():
            a, b = g.get("gates"), g.get("no_dd_gate")
            ref = a or b
            cell = lambda s: f"{'yes' if passed(s) else 'no'}, {s['wf_total']:,.0f}" if s else "-"  # noqa: E731
            L.append(f"| {d:g} | ~{d * CONTROL_LEN * P.TICK_USD:.0f} | {ref['champion_expectancy']:.2f} | "
                     f"{ref.get('min_p95_dd_profitable', float('nan')):,.0f} | {cell(a)} | {cell(b)} |")
    L += ["", "## Idea vs execution: does the entry signal itself have an edge?", "",
          "Each champion's real entries, frozen, then followed WITHOUT its stops and targets: gross move at each "
          f"horizon vs up to {N_RANDOM_PER_SIGNAL} random entries per signal (distinct days, without replacement) "
          "at the same ET minute and side: on random "
          "development days, and on random days in the same weeks (+-20 trading days: same market regime). All z are day-clustered. If prices after the signal carry no "
          "predictable drift (a martingale), no stop / target / trailing rule can make it profitable (optional "
          "stopping); six fixed horizons cannot rule out every path-dependent exit, so 'no edge' means no "
          "DEMONSTRATED edge. If the signal beats random at some horizon while the strategy loses, the exits are "
          "the suspect. Gross = before fees and slippage. MFE / MAE = best / worst "
          "move up to that horizon, measured past the real exit. Limit: a regime that flips abruptly inside the 20-day "
          "window can still leak into the same-weeks baseline.", ""]
    for r in rows:
        e = r["edge"]
        L += [f"**{r['strategy']}** ({e['signals']:,} signals on {e['days']:,} days, up to {e['random_per_signal']} "
              f"matched random entries each): "
              f"{signal_verdict(e)}", "",
              "| Horizon (min) | Signal $ | Edge vs random $ (z) | Edge vs same weeks $ (z) | 2010-15 $ (z) | "
              "2016-21 $ (z) | First signal of the day $ (z) | MFE med signal / random $ | MAE med signal / random $ |",
              "|---|---|---|---|---|---|---|---|---|"]
        L += [f"| {x['horizon']} | {x['signal_usd']:.2f} | {x['edge_usd']:.2f} ({x['z']:.2f}) | "
              f"{x['local_edge_usd']:.2f} ({x['local_z']:.2f}) | {x['edge_2010_15']:.2f} ({x['z_2010_15']:.2f}) | "
              f"{x['edge_2016_21']:.2f} ({x['z_2016_21']:.2f}) | "
              f"{x['first_of_day_edge_usd']:.2f} ({x['first_of_day_z']:.2f}) | {x['signal_mfe_med']:.0f} / {x['random_mfe_med']:.0f} | "
              f"{x['signal_mae_med']:.0f} / {x['random_mae_med']:.0f} |" for x in e["horizons"]]
        if e["stop_exits"]:
            L += ["", f"Stop hunt: {e['stop_then_ran_pct']:.1f}% of {e['stop_exits']:,} stopped-out trades later "
                  f"reached +1R (entry + the stop distance) before the flat time; random entries that fell the same "
                  f"distance did so {e['random_stop_then_ran_pct']:.1f}% of the time (z {e['stop_hunt_z']:.2f}, "
                  f"trades treated as independent: indicative only). Clearly higher than random would mean stops "
                  f"too tight for this signal; not higher = no sign of that."]
        L += [""]
    L += ["", "## Champion execution audit", "",
          "| Strategy | Trades | Fill at a minute open % (market / close-confirmed / gapped stop) | Thin entry minute (<5 lots) % | Loss beyond MAE % | "
          "Both sides in 1st breakout minute | Real 60-day windows pass/fail % | Real 250-day pass/fail % | DSR iid / HAC |",
          "|---|---|---|---|---|---|---|---|---|"]
    for r in rows:
        tie = (f"{r['ties']['tie_days']} of {r['ties']['breakout_days']} days ({r['ties']['tie_pct']:.1f}%)"
               if r["ties"].get("applies") else "n/a")
        L.append(f"| {r['strategy']} | {r['trades']:,} | {r['entries_at_minute_open_pct']:.1f} | "
                 f"{r['thin_entry_minute_pct']:.1f} | {r['mae_below_realized_loss_pct']:.1f} | {tie} | "
                 f"{r['rolling_60']['pass_pct']:.0f} / {r['rolling_60']['fail_pct']:.0f} | "
                 f"{r['rolling_250']['pass_pct']:.0f} / {r['rolling_250']['fail_pct']:.0f} | "
                 f"{r['dsr_iid']:.3f} / {r['dsr_hac']:.3f} |")
    L += ["", "Exit mix per champion: " + "; ".join(f"{r['strategy']}: {r['exit_mix_pct']}" for r in rows), "",
          "\"Loss beyond MAE\" = losing trades whose realized loss exceeds the recorded adverse excursion + slip "
          "(gap exits at the flat open). Harmless for the Combine simulation, which adds realized P&L to the "
          "intraday low anyway.", "",
          "## Coverage (09:00 ET 30-minute range valid)", "", "| Year | Trading days | Valid share |", "|---|---|---|"]
    L += [f"| {y} | {int(r['days'])} | {r['valid_share']:.3f} |" for y, r in cov.iterrows()]
    L += [""]
    if sp:
        L += ["Largest spot-vs-futures level gaps (roll / expiry calendar spread): " + json.dumps(
            {str(k.date()): v for k, v in sp["worst_days"].items()}), ""]
    L += ["## Covered by automatic tests (tests/test_audit_engine.py)", "",
          "- Look-ahead: cutting the data at a random minute, or replacing everything after it with an unrelated "
          "path, never changes an entry or a closed trade before that minute (ORB, ZAB, Crabel, ACD; day tables; "
          "ATR, stretch, NR4/NR7, inside, pivots, relative volume, width ratio). A planted leak is caught.",
          "- Mirror: reflected prices turn every long-only config into the short-only one, trade for trade, "
          "with pessimistic and optimistic fills.",
          "- Zero sum: paired long/short market trades cost exactly 2 x (fee + 2 slips).",
          "- Positive engine control: a planted post-breakout drift becomes positive expectancy, growing with size.",
          "- Rules: flat by 16:09 ET (Topstep 16:10), no 60-day Combine limit, scaled walk-forward trade minimum.", ""]
    (AUDIT_DIR / "report.md").write_text("\n".join(L))
    (AUDIT_DIR / "trades_chart.html").write_text(chart_html(charts))
    print(f"\nAudit report: {AUDIT_DIR / 'report.md'}\nTrade charts: {AUDIT_DIR / 'trades_chart.html'}")
    return 0


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if not argv:
        print(__doc__)
        return 2
    cmd, quick = argv[0], "--quick" in argv
    if cmd == "scenarios":
        return run_scenarios(quick)
    if cmd == "control":
        return run_control()
    if cmd == "report":
        return build_report()
    if cmd == "_worker":
        return run_worker(argv[1], argv[2], quick)
    if cmd == "_control":
        return control_worker(float(argv[1]), argv[2])
    print(__doc__)
    return 2


if __name__ == "__main__":
    os.environ.setdefault("PYTHONHASHSEED", "0")
    sys.exit(main())
