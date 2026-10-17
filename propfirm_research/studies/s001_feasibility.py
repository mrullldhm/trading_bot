"""S001 feasibility frontier (research/studies/S001-feasibility/report.md). Reviewed by Codex in R004.

Part A: parametric day P&L (Normal; Student-t df 5 / 3 as a normal scale mixture, so the intraday Brownian
bridge gets each day's latent sigma), no market data.

Part B: real CL discovery noise. Every trading day of the calendar is kept; a template trades on its valid
days (a random 100 / 50 / 25% of them), invalid days (roll, expiry, short session) are no-trade days (0, 0).
Each trade has a random direction (zero edge), then an edge is bent into the price path (grid.planted).
Directions come in antithetic pairs (seed 2k+1 trades the opposite of seed 2k on the same days), so the
random-direction P&L averages to exactly zero edge over each pair; a pair is the independent outer unit.

Edge: gross drift g ticks per trade. e_net = g - 2.402 (after base costs) is the headline axis;
e_net_stress = g - 4.402 is the same strategy with stress fills. A g = 0 row is the zero-edge baseline.

Required edge per criterion, reported two ways: `first` = smallest e_net meeting it; `stable` = smallest
e_net from which it holds at every larger grid point (conservative):
(a) G8: mean p95 60-day drop (propsim convention) <= 50% of the MLL, reserve 0;
(b) pass >= 50% and fail <= 25%, reserve 0;
(c) Codex candidate: upper 95% bound of P(fail) < 1% with a $500 reserve; bound = max(Wilson over pooled
    attempts, one-sided t bound over the pair-level fail rates) (R004 #2).

Usage: python -m propfirm_research.studies.s001_feasibility [--part A|B|both] [--quick] [--seeds N]
"""

import argparse
import hashlib
import json
import platform
import time
from datetime import datetime, timezone
from pathlib import Path

import numba
import numpy as np
import pandas as pd

from propfirm_backtest.propsim import FEE_USD, TICK_USD

from .. import combine, costs, data, grid, ledger, paths
from ..stats import mean_upper, wilson_upper

ITEM = "S001"
TEMPLATES = {  # name -> (decision ET minute, exit ET minute or FLAT); fill at the open of the decision minute
    "03:00-08:00": (3 * 60, 8 * 60),
    "09:00-10:00": (9 * 60, 10 * 60),
    "09:00-12:00": (9 * 60, 12 * 60),
    "09:00-16:05": (9 * 60, grid.FLAT),
    "10:35-11:30": (10 * 60 + 35, 11 * 60 + 30),
    "14:00-14:30": (14 * 60, 14 * 60 + 30),
    "14:00-16:05": (14 * 60, grid.FLAT),
    "14:35-16:05": (14 * 60 + 35, grid.FLAT),
    "20:00-03:00": (20 * 60, 3 * 60),
}
EDGES = [0, 2, 4, 6, 8, 12, 16, 24, 32]  # e_net, ticks per trade after base costs
FREQS = [1.0, 0.5, 0.25]
SLIPS = {"base": costs.BASE_SLIP, "stress": costs.STRESS_SLIP}
SIZES = [("50K", 1), ("100K", 1), ("100K", 2), ("100K", 3), ("150K", 1), ("150K", 2), ("150K", 3), ("150K", 4)]
RESERVES = [0.0, 500.0]
N_SEEDS = 20  # 10 antithetic pairs
N_SIMS = 1000
BASE_TICKS = costs.round_trip_ticks(costs.BASE_SLIP)  # 2.402
STRESS_TICKS = costs.round_trip_ticks(costs.STRESS_SLIP)  # 4.402
BASELINE = -BASE_TICKS  # e_net of the zero-gross-drift row
FAIL_UCB_MAX = 0.01

A_DISTS = {"normal": None, "t5": 5, "t3": 3}
A_SR = [0.5, 1, 1.5, 2, 3, 4, 6]
A_SD = [75, 150, 300, 500]
A_DAYS = 5000

REPORT_DIR = paths.RESEARCH_DIR / "studies" / "S001-feasibility"


def bridge_low(x: np.ndarray, sigma, u: np.ndarray) -> np.ndarray:
    """Minimum of a Brownian bridge from 0 to x with variance sigma^2 (inverse-CDF draw from uniforms u),
    always <= min(0, x). sigma: scalar or one per day."""
    return (x - np.sqrt(x * x - 2 * np.asarray(sigma) ** 2 * np.log(u))) / 2


def part_a_days(dist_df, sd: float, rng) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Noise with sample mean exactly 0 and sample sd exactly sd, its per-day latent sigma, bridge uniforms.
    Student-t(df) = normal with sigma_i = s * sqrt(df / chi2_df), s = sd * sqrt((df - 2) / df)."""
    z = rng.standard_normal(A_DAYS)
    if dist_df is None:
        sig = np.full(A_DAYS, float(sd))
    else:
        sig = sd * np.sqrt((dist_df - 2) / dist_df) * np.sqrt(dist_df / rng.chisquare(dist_df, A_DAYS))
    noise = sig * z
    scale = sd / noise.std()  # moment-match so the realised Sharpe equals the nominal one (R005 cell 5)
    return (noise - noise.mean()) * scale, sig * scale, rng.random(A_DAYS)


def part_a(n_sims: int) -> pd.DataFrame:
    rows = []
    for di, (dist, df_) in enumerate(A_DISTS.items()):
        for si, sd in enumerate(A_SD):
            noise, sig, u = part_a_days(df_, sd, np.random.default_rng(1000 + 10 * di + si))
            pnl = np.vstack([sr * sd / np.sqrt(252) + noise for sr in A_SR])  # common random numbers over SR
            low = np.vstack([bridge_low(p, sig, u) for p in pnl])
            for acc in combine.ACCOUNTS:
                for res in RESERVES:
                    o = combine.odds_many(pnl, low, acc, 1, reserve=res, n_sims=n_sims)
                    for i, sr in enumerate(A_SR):
                        rows.append({"dist": dist, "sr": sr, "sd": sd, "account": acc, "reserve": res,
                                     "sr_realised": pnl[i].mean() / pnl[i].std() * np.sqrt(252),
                                     **{k: v[i] for k, v in o.items()}})
    return pd.DataFrame(rows)


def part_b(df: pd.DataFrame, n_seeds: int, n_sims: int, templates: dict, log=print) -> pd.DataFrame:
    drifts = np.array([0.0] + [e + BASE_TICKS for e in EDGES])
    rows = []
    for name, spec in templates.items():
        t0 = time.time()
        w = grid.windows(df, [spec])  # every trading day of the frame
        valid = w["valid"].to_numpy()
        n = len(w)
        ret = w["ret_ticks"].to_numpy()
        for s in range(n_seeds):
            rng = np.random.default_rng(10_000 + s // 2)
            sign = rng.choice([-1.0, 1.0], n) * (-1.0 if s % 2 else 1.0)
            u = rng.random(n)  # nested masks: a 25% day is also a 50% day
            for freq in FREQS:
                d = np.where(valid & (u < freq), sign, 0.0)
                tr = d != 0
                for cost, slip in SLIPS.items():
                    pnl = np.empty((len(drifts), n))
                    low = np.empty((len(drifts), n))
                    for k, g in enumerate(drifts):
                        p, m = grid.planted(df, w, d, g, slip=slip, fee=FEE_USD, tick_usd=TICK_USD)
                        pnl[k], low[k] = p, grid.one_trade_day_low(p, m)
                    seeds = np.full(len(drifts), 50_000 + s)
                    moments = []
                    for k, g in enumerate(drifts):
                        r2 = ret[tr] + d[tr] * g  # deformed return on traded days
                        moments.append({"sum_pnl": pnl[k].sum(), "sum_pnl2": (pnl[k] ** 2).sum(),
                                        "n_tr": int(tr.sum()), "s_d": d[tr].sum(), "s_r": r2.sum(),
                                        "s_rr": (r2 ** 2).sum(), "s_dr": (d[tr] * r2).sum()})
                    for acc, c in SIZES:
                        for res in RESERVES:
                            o = combine.odds_many(pnl, low, acc, c, reserve=res, n_sims=n_sims, seeds=seeds)
                            for k, g in enumerate(drifts):
                                rows.append({
                                    "template": name, "seed": s, "pair": s // 2, "freq": freq, "cost": cost,
                                    "g_gross": g, "e_net": g - BASE_TICKS, "e_net_stress": g - STRESS_TICKS,
                                    "account": acc, "contracts": c, "reserve": res,
                                    "n_sessions": n, "n_eligible": int(valid.sum()),
                                    "n_exit_missing": int(w["exit_missing"].sum()), **moments[k],
                                    **{key: v[k] for key, v in o.items()}})
        log(f"  {name}: {n} sessions, {int(valid.sum())} eligible, {int(w['exit_missing'].sum())} skipped for a "
            f"missing exit bar (D009), {time.time() - t0:.0f} s")
    return pd.DataFrame(rows)


def summarise_b(cells: pd.DataFrame, n_sims: int) -> pd.DataFrame:
    keys = ["template", "freq", "cost", "account", "contracts", "reserve", "e_net"]
    out = []
    for k, grp in cells.groupby(keys):
        pair_fail = grp.groupby("pair")["fail"].mean().to_numpy()
        tot = grp[["sum_pnl", "sum_pnl2", "n_sessions", "n_tr", "s_d", "s_r", "s_rr", "s_dr"]].sum()
        mean = tot.sum_pnl / tot.n_sessions
        var = tot.sum_pnl2 / tot.n_sessions - mean ** 2
        md, mr = tot.s_d / tot.n_tr, tot.s_r / tot.n_tr
        cov = tot.s_dr / tot.n_tr - md * mr
        sdd, sdr = np.sqrt(max(1 - md ** 2, 0)), np.sqrt(max(tot.s_rr / tot.n_tr - mr ** 2, 0))
        wil = wilson_upper(int(grp["fails"].sum()), len(grp) * n_sims)
        tb = mean_upper(pair_fail)
        out.append({
            **dict(zip(keys, k)),
            "g_gross": grp["g_gross"].iloc[0], "e_net_stress": grp["e_net_stress"].iloc[0],
            "seeds": len(grp), "pairs": len(pair_fail),
            "pass": grp["pass"].mean(), "pass_pair_sd": grp.groupby("pair")["pass"].mean().std(ddof=1),
            "fail": grp["fail"].mean(), "fail_pair_max": pair_fail.max(),
            "fail_ucb95": max(wil, tb if np.isfinite(tb) else 1.0), "fail_ucb95_wilson": wil, "fail_ucb95_t": tb,
            "p95_dd": grp["p95_dd"].mean(), "p99_dd": grp["p99_dd"].mean(),
            "p95_dd_account": grp["p95_dd_account"].mean(), "dd_d003_seed_share": grp["dd_d003_ok"].mean(),
            "median_days_pass": grp["median_days_pass"].median(), "dll_hit_days": grp["dll_hit_days"].mean(),
            "sharpe_ann": mean / np.sqrt(var) * np.sqrt(252) if var > 0 else np.nan,
            "ic": cov / (sdd * sdr) if sdd > 0 and sdr > 0 else np.nan,
            "mean_day_1c": mean, "trades_per_session": tot.n_tr / tot.n_sessions,
            "n_sessions": grp["n_sessions"].iloc[0], "n_eligible": grp["n_eligible"].iloc[0],
            "n_exit_missing": grp["n_exit_missing"].iloc[0],
        })
    s = pd.DataFrame(out)
    s["dd_limit_d003"] = s["account"].map({a: v.dd_limit_d003 for a, v in combine.ACCOUNTS.items()})
    return s


def thresholds(e: np.ndarray, ok: np.ndarray) -> tuple[float, float]:
    """(first, stable): smallest e >= 0 meeting ok; smallest e >= 0 from which ok holds for every larger e."""
    order = np.argsort(e)
    e, ok = e[order], ok[order]
    keep = e >= 0
    e, ok = e[keep], ok[keep]
    first = float(e[ok][0]) if ok.any() else float("nan")
    stable = next((float(e[i]) for i in range(len(e)) if ok[i:].all()), float("nan"))
    return first, stable


CRITERIA = {  # name -> (reserve used, test on a summary frame)
    "a_dd_d003": (0.0, lambda r: r["p95_dd"].to_numpy() <= r["dd_limit_d003"].to_numpy()),
    "b_pass50_fail25": (0.0, lambda r: (r["pass"].to_numpy() >= 0.5) & (r["fail"].to_numpy() <= 0.25)),
    "c_failucb1_res500": (500.0, lambda r: r["fail_ucb95"].to_numpy() < FAIL_UCB_MAX),
}


def required_edges(summary: pd.DataFrame) -> pd.DataFrame:
    out = []
    keys = ["template", "freq", "cost", "account", "contracts"]
    for k, grp in summary.groupby(keys):
        row = dict(zip(keys, k))
        r0 = grp[grp["reserve"] == 0]
        base = r0[np.isclose(r0["e_net"], BASELINE)].iloc[0]
        row.update(baseline_pass=base["pass"], baseline_fail=base["fail"])
        for c, (res, test) in CRITERIA.items():
            r = grp[grp["reserve"] == res].sort_values("e_net")
            first, stable = thresholds(r["e_net"].to_numpy(), test(r))
            row[f"{c}_first"], row[f"{c}_stable"] = first, stable
            if not np.isnan(stable):
                at = r[np.isclose(r["e_net"], stable)].iloc[0]  # companions from the criterion's own rows
                row.update({f"{c}_reserve": res, f"{c}_sharpe": at["sharpe_ann"], f"{c}_ic": at["ic"],
                            f"{c}_pass": at["pass"], f"{c}_fail": at["fail"], f"{c}_p95_dd": at["p95_dd"],
                            f"{c}_days": at["median_days_pass"]})
        out.append(row)
    return pd.DataFrame(out)


def code_hash() -> str:
    pkg = Path(combine.__file__).parent
    return ledger.sha256_files(sorted(pkg.rglob("*.py")))


def data_fingerprint(df: pd.DataFrame) -> dict:
    h = hashlib.sha256(df[["tmin", "open", "high", "low"]].to_numpy().tobytes()).hexdigest()
    return {"rows": len(df), "first": str(df["ts_event_utc"].iloc[0]), "last": str(df["ts_event_utc"].iloc[-1]),
            "sha256_tmin_ohl": h}


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--part", choices=["A", "B", "both"], default="both")
    ap.add_argument("--quick", action="store_true", help="2 seeds, 300 attempts, 2 templates (smoke test)")
    ap.add_argument("--seeds", type=int, default=N_SEEDS)
    a = ap.parse_args(argv)
    n_seeds, n_sims = (2, 300) if a.quick else (a.seeds, N_SIMS)
    if a.quick and a.seeds != N_SEEDS:
        raise SystemExit("--seeds has no effect with --quick (2 seeds)")
    if not a.quick and (n_seeds % 2 or n_seeds < 4):
        raise SystemExit("--seeds must be even and >= 4 (at least 2 antithetic pairs for the t bound)")
    templates = dict(list(TEMPLATES.items())[:2]) if a.quick else TEMPLATES
    tag = "quick" if a.quick else "full"
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out = paths.OUT_DIR / "s001" / f"{stamp}_{tag}"
    out.mkdir(parents=True, exist_ok=True)
    manifest = {"item": ITEM, "stamp": stamp, "tag": tag, "part": a.part, "code_sha256": code_hash(),
                "seeds": n_seeds, "n_sims": n_sims, "templates": templates, "edges": EDGES, "freqs": FREQS,
                "sizes": SIZES, "reserves": RESERVES, "slips": SLIPS, "fee": FEE_USD,
                "versions": {"python": platform.python_version(), "numpy": np.__version__,
                             "pandas": pd.__version__, "numba": numba.__version__}}
    log_lines = []

    def log(msg):
        print(msg, flush=True)
        log_lines.append(msg)

    if a.part in ("A", "both"):
        t0 = time.time()
        pa = part_a(n_sims if a.quick else 2000)
        pa.to_parquet(out / "partA.parquet")
        if not a.quick:
            pa.to_csv(REPORT_DIR / "partA.csv", index=False, float_format="%.4f")
        manifest["partA_rows"] = len(pa)
        ledger.append(ITEM, "synthetic", "none", n_tests=len(pa), statistic="Part A parametric Combine odds",
                      verdict="DESCRIPTIVE", code_sha256=manifest["code_sha256"],
                      output=str((out / "partA.parquet").relative_to(paths.ROOT)),
                      note=f"{tag}: normal/t5/t3 (scale mixture) x 7 SR x 4 sd x 3 accounts x 2 reserves, "
                           f"{A_DAYS} days, DLL on")
        log(f"Part A: {len(pa)} cells, {time.time() - t0:.0f} s")

    if a.part in ("B", "both"):
        t0 = time.time()
        df = data.load_front("discovery", ITEM, f"S001 Part B ({tag}): planted-edge feasibility")
        manifest["data"] = data_fingerprint(df)
        cells = part_b(df, n_seeds, n_sims, templates, log)
        cells.to_parquet(out / "partB_cells.parquet")
        summ = summarise_b(cells, n_sims)
        req = required_edges(summ)
        summ.to_parquet(out / "partB_summary.parquet")
        req.to_csv(out / "required_edge.csv", index=False)
        if not a.quick:
            summ.to_csv(REPORT_DIR / "partB_summary.csv", index=False, float_format="%.4f")
            req.to_csv(REPORT_DIR / "required_edge.csv", index=False, float_format="%.4f")
        ledger.append(ITEM, "descriptive", "discovery", n_tests=len(summ),
                      statistic="Part B planted-edge Combine odds", verdict="DESCRIPTIVE",
                      code_sha256=manifest["code_sha256"], data_sha256=manifest["data"]["sha256_tmin_ohl"],
                      output=str((out / "partB_cells.parquet").relative_to(paths.ROOT)),
                      note=f"{tag}: {len(templates)} templates x {n_seeds} seeds ({n_seeds // 2} antithetic pairs) "
                           f"x {len(FREQS)} freqs x 2 costs x {len(SIZES)} sizes x 2 reserves x "
                           f"{len(EDGES) + 1} edges, {n_sims} attempts, DLL on")
        log(f"Part B: {len(cells)} cells, {time.time() - t0:.0f} s")
        cols = ["template", "freq", "account", "contracts", "baseline_pass"] + \
               [f"{c}_{m}" for c in CRITERIA for m in ("first", "stable")]
        with pd.option_context("display.width", 250, "display.max_columns", 30):
            log(req[req["cost"] == "base"][cols].to_string(index=False, float_format=lambda x: f"{x:.2f}"))

    manifest["log"] = log_lines
    (out / "manifest.json").write_text(json.dumps(manifest, indent=1, default=str))
    print(f"outputs: {out}")


if __name__ == "__main__":
    main()
