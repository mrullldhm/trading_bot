"""Evaluate the third-party "CL VWAP Break" strategy with its published parameters (no fitting).

  python -m propfirm_backtest.vwap_break_eval [--skip-neighbours]   # replicate + oos + neighbours -> report.md

replicate: the author's own window (27 Jul - 15 Oct 2026; our data ends 13 Oct), next to the published
           numbers. Same rules, so this only checks that we built the same strategy.
oos:       2010-06 .. 26 Jul 2026, before the window the parameters were tuned on. The real test.
neighbours: one step either side of each published parameter on the OOS data (reported, never picked).

Verdict uses the orb_search gates (P&L at 1 and 2 ticks slippage, years, concentration, p95 60-day
drawdown) plus the Combine pass rate with Topstep's Daily Loss Limit applied.
"""

import argparse
import json

import numpy as np
import pandas as pd

from propfirm_data.config import ROOT

from . import bars as B
from . import propsim as P
from . import vwap_break_engine as V
from .orb_engine import EXIT_NAMES
from .orb_search import GATES

OUT = ROOT / "data" / "backtests" / "vwap_break"
TUNE_START = "2026-07-27"  # first day of the author's backtest (their 1-minute data starts here)
OOS_START = "2010-06-01"
DATA_END = "2026-10-14"
N_SIMS, SEED = 2000, 12345
PUBLISHED = {"trades": 323, "net_usd": 40878, "win_rate": 0.54, "profit_factor": 1.81, "max_dd_usd": 2931,
             "green_days": 36, "red_days": 23, "months": {7: 2996, 8: 15138, 9: 17854, 10: 4889}}
# (name, overrides) one step either side of each published value
NEIGHBOURS = [
    ("band 0.4", {"band": 0.4}), ("band 0.6", {"band": 0.6}),
    ("touch tol 0.25", {"touch_tol": 0.25}), ("touch tol 2.25", {"touch_tol": 2.25}),
    ("atr ratio 1.0", {"atr_ratio": 1.0}), ("atr ratio 1.25", {"atr_ratio": 1.25}),
    ("R 1.5/2.0", {"r": 1.5, "r_hot": 2.0}), ("R 2.5/3.0", {"r": 2.5, "r_hot": 3.0}),
    ("add-on offset 24", {"addon_offset": 24}), ("add-on offset 40", {"addon_offset": 40}),
    ("far dist 60", {"far_dist": 60}), ("far dist 80", {"far_dist": 80}),
    ("scalp risk 14", {"scalp_risk": 14}), ("scalp risk 22", {"scalp_risk": 22}),
    ("max risk 40", {"max_risk": 40}), ("expiry 3 bars", {"expiry_bars": 3}),
]


def frame(mk: V.Market, t) -> pd.DataFrame:
    df = pd.DataFrame(dict(zip(V.TRADE_COLS, t)))
    df["date"] = pd.to_datetime(mk.days[df["day"]], unit="D")
    df["entry_et"] = pd.to_datetime(mk.f.tmin[df["in_row"]] * 60, unit="s", utc=True).tz_convert(B.ET)
    df["exit_et"] = pd.to_datetime(mk.f.tmin[df["out_row"]] * 60, unit="s", utc=True).tz_convert(B.ET)
    df["cls"] = df["cls"].map(V.CLASS_NAMES)
    df["why"] = df["why"].map(EXIT_NAMES)
    return df


def run(mk, cfg, start, end, slip=1.0, pessimistic=True) -> pd.DataFrame:
    df = frame(mk, mk.trades(cfg, slip=slip, pessimistic=pessimistic))
    return df[(df["date"] >= start) & (df["date"] < end)].reset_index(drop=True)


def daily(df: pd.DataFrame, days: pd.DatetimeIndex) -> tuple[np.ndarray, np.ndarray]:
    idx = days.get_indexer(df["date"])
    return P.daily_series(idx.astype(np.int64), df["pnl_usd"].to_numpy(), df["mae_usd"].to_numpy(), len(days))


def metrics(df: pd.DataFrame, days: pd.DatetimeIndex, combine=True) -> dict:
    pnl = df["pnl_usd"].to_numpy()
    s = P.trade_stats(pnl)
    dp, dl = daily(df, days)
    traded = np.isin(np.arange(len(days)), days.get_indexer(df["date"]))
    years = pd.Series(dp, index=days).groupby(days.year).sum()
    total = dp.sum()
    out = {"trades": s["trades"], "addon_legs": int(df["addon"].sum()), "net_usd": total,
           "win_rate": s["win_rate"], "profit_factor": s["profit_factor"], "expectancy_usd": s["expectancy_usd"],
           "max_dd_usd": P.max_drawdown(dp, dl), "worst_day_usd": dl.min() if len(dl) else 0.0,
           "days_over_dll": int((dl <= -V.DLL).sum()),
           "green_days": int((dp[traded] > 0).sum()), "red_days": int((dp[traded] <= 0).sum()),
           "trades_per_year": s["trades"] / max(len(days) / 252, 1e-9),
           "positive_year_frac": float((years > 0).mean()) if len(years) else np.nan,
           "best_year_share": years.max() / total if total > 0 else np.inf,
           "best_day_share": dp.max() / total if total > 0 else np.inf}
    if combine:
        raw = P.pass_probability(dp[None], dl[None], N_SIMS, SEED)[0]
        dpd, dld = V.apply_dll(dp, dl)
        dll = P.pass_probability(dpd[None], dld[None], N_SIMS, SEED)[0]
        out |= {"pass_prob": raw[0], "fail_prob": raw[1], "p95_dd_60d": raw[2],
                "pass_prob_dll": dll[0], "fail_prob_dll": dll[1], "p95_dd_60d_dll": dll[2]}
    return out


def yearly(df, days):
    dp, _ = daily(df, days)
    return pd.Series(dp, index=days).groupby(days.year).sum()


def gates(m1: dict, net_slip2: float, neighbour_share: float) -> dict:
    """orb_search.gate_mask plus its neighbour gate, on raw (no-DLL) series like orb_search."""
    g = GATES
    return {
        f"trades >= {g['min_trades']}": m1["trades"] >= g["min_trades"],
        f"trades/year >= {g['min_trades_per_year']}": m1["trades_per_year"] >= g["min_trades_per_year"],
        "profitable at 1 tick slip": m1["net_usd"] > 0,
        "profitable at 2 ticks slip": net_slip2 > 0,
        f"positive years >= {g['min_positive_year_frac']:.0%}": m1["positive_year_frac"] >= g["min_positive_year_frac"],
        f"best year <= {g['max_best_year_share']:.0%} of total": m1["best_year_share"] <= g["max_best_year_share"],
        f"best day <= {g['max_best_day_share']:.0%} of total": m1["best_day_share"] <= g["max_best_day_share"],
        f"p95 60-day drawdown <= ${g['max_p95_drawdown']:,.0f}": m1["p95_dd_60d"] <= g["max_p95_drawdown"],
        f"neighbours profitable >= {g['min_neighbours_profitable']:.0%}": neighbour_share >= g["min_neighbours_profitable"],
    }


def fmt(v, kind=""):
    if isinstance(v, (bool, np.bool_)):
        return "PASS" if v else "FAIL"
    if v is None or (isinstance(v, float) and np.isnan(v)):
        return "-"
    if kind == "$":
        return f"${v:,.0f}"
    if kind == "%":
        return f"{v:.1%}"
    if isinstance(v, (int, np.integer)):
        return f"{v:,}"
    return f"{v:,.2f}"


METRIC_ROWS = [("trades", ""), ("addon_legs", ""), ("net_usd", "$"), ("win_rate", "%"), ("profit_factor", ""),
               ("expectancy_usd", "$"), ("max_dd_usd", "$"), ("worst_day_usd", "$"), ("days_over_dll", ""),
               ("green_days", ""), ("red_days", ""), ("pass_prob", "%"), ("fail_prob", "%"),
               ("p95_dd_60d", "$"), ("pass_prob_dll", "%"), ("fail_prob_dll", "%"), ("p95_dd_60d_dll", "$")]


def table(cols: dict) -> list[str]:
    names = list(cols)
    L = ["| metric | " + " | ".join(names) + " |", "|---" * (len(names) + 1) + "|"]
    for key, kind in METRIC_ROWS:
        L.append(f"| {key} | " + " | ".join(fmt(cols[n].get(key), kind) for n in names) + " |")
    return L


def md(df: pd.DataFrame, index=True) -> str:
    """DataFrame -> markdown table (no tabulate dependency)."""
    d = df.reset_index() if index else df
    cols = [str(c) for c in d.columns]
    rows = ["| " + " | ".join(cols) + " |", "|---" * len(cols) + "|"]
    for r in d.itertuples(index=False):
        rows.append("| " + " | ".join(fmt(v) if isinstance(v, float) else str(v) for v in r) + " |")
    return "\n".join(rows)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--skip-neighbours", action="store_true")
    a = ap.parse_args(argv)
    OUT.mkdir(parents=True, exist_ok=True)
    pub = V.config()
    no_add = V.config(addon=0)

    print("loading 1-minute CL ...", flush=True)
    m = B.load_minutes(end=DATA_END)
    mk = V.Market(m, strict_expiry=True)
    all_days = pd.DatetimeIndex(pd.to_datetime(mk.days, unit="D"))
    rep_days = all_days[(all_days >= TUNE_START)]
    oos_days = all_days[(all_days >= OOS_START) & (all_days < TUNE_START)]

    # --- replicate ---
    rep = {}
    rep_trades = {}
    for name, cfg, slip in [("published, slip 1", pub, 1.0), ("published, slip 0", pub, 0.0),
                            ("no add-on, slip 1", no_add, 1.0)]:
        df = run(mk, cfg, TUNE_START, DATA_END, slip)
        rep[name] = metrics(df, rep_days, combine=False)
        rep_trades[name] = df
    rep_trades["published, slip 1"].to_csv(OUT / "trades_replicate.csv", index=False)
    rep_month = {n: df.groupby(df["date"].dt.month)["pnl_usd"].sum() for n, df in rep_trades.items()}

    # --- out of sample ---
    oos = {}
    oos_trades = {}
    for name, cfg, slip, pess in [("published", pub, 1.0, True), ("published, slip 2", pub, 2.0, True),
                                  ("published, slip 3", pub, 3.0, True), ("published, optimistic", pub, 1.0, False),
                                  ("no add-on", no_add, 1.0, True), ("no add-on, slip 2", no_add, 2.0, True)]:
        print(f"oos: {name}", flush=True)
        df = run(mk, cfg, OOS_START, TUNE_START, slip, pess)
        oos[name] = metrics(df, oos_days)
        oos_trades[name] = df
    base = oos_trades["published"]
    base.to_csv(OUT / "trades_oos.csv.gz", index=False)
    years = pd.DataFrame({n: yearly(oos_trades[n], oos_days) for n in ["published", "no add-on"]})
    years["trades"] = base.groupby(base["date"].dt.year).size()
    by_side = base.groupby(base["dir"].map({1: "long", -1: "short"}))["pnl_usd"].agg(["count", "sum", "mean"])
    by_cls = base.groupby("cls")["pnl_usd"].agg(["count", "sum", "mean"])
    by_side_year = base.pivot_table(index=base["date"].dt.year, columns=base["dir"].map({1: "long", -1: "short"}),
                                    values="pnl_usd", aggfunc="sum").fillna(0)

    # --- neighbours ---
    nb = []
    if not a.skip_neighbours:
        for name, ov in NEIGHBOURS:
            print(f"neighbour: {name}", flush=True)
            df = run(mk, V.config(**ov), OOS_START, TUNE_START)
            mt = metrics(df, oos_days, combine=False)
            nb.append({"variant": name, "trades": mt["trades"], "net_usd": mt["net_usd"],
                       "profit_factor": mt["profit_factor"], "max_dd_usd": mt["max_dd_usd"]})
    nb = pd.DataFrame(nb)
    share = float((nb["net_usd"] > 0).mean()) if len(nb) else np.nan  # nan fails the neighbour gate

    verdicts = {}
    for name, slip2 in [("published", "published, slip 2"), ("no add-on", "no add-on, slip 2")]:
        verdicts[name] = gates(oos[name], oos[slip2]["net_usd"], share)

    # --- report ---
    L = ["# CL VWAP Break (third-party strategy), published parameters", "",
         "Rules: `propfirm_backtest/vwap_break_engine.py` docstring. Size 1 CL + 2 MCL ($12/tick, "
         f"${pub[V.K_FEE_USD]:.2f} fees per round turn); add-on 6 MCL (${pub[V.K_ADD_FEE_USD]:.2f}). Slippage in ticks "
         "on every stop order (entries, add-on, protective stop) and on time exits; targets fill at the price. "
         "Pessimistic intraminute ordering unless stated. No parameter was fitted here.", "",
         "## 1. Replication (author's window)", "",
         f"{TUNE_START} to {DATA_END} (our data ends 13 Oct; theirs 15 Oct). The author counts add-on fills as "
         "separate trades: compare their 323 with trades + addon_legs.", ""]
    L += table(rep | {"author (published)": PUBLISHED})
    L += ["", "| month | " + " | ".join(rep_month) + " | author |", "|---" * (len(rep_month) + 2) + "|"]
    for mo in [7, 8, 9, 10]:
        L.append(f"| {mo} | " + " | ".join(fmt(s.get(mo, 0.0), "$") for s in rep_month.values())
                 + f" | {fmt(PUBLISHED['months'][mo], '$')} |")
    L += ["", f"## 2. Out of sample: {OOS_START} to {TUNE_START} ({len(oos_days):,} trading days)", ""]
    L += table(oos)
    L += ["", "Combine: Topstep 50K ($3k target, $2k trailing EOD MLL, 55% consistency), "
          f"{N_SIMS} block-bootstrap attempts. `_dll` = Topstep's $1,000 Daily Loss Limit applied "
          "(day liquidated at -$1,000). Gates use the raw series, like orb_search.", "", "### Gates (orb_search.GATES)", "",
          "| gate | published | no add-on |", "|---|---|---|"]
    for g in verdicts["published"]:
        L.append(f"| {g} | {fmt(verdicts['published'][g])} | {fmt(verdicts['no add-on'][g])} |")
    for name, v in verdicts.items():
        L.append(f"\n**{name}: {'PASS' if all(v.values()) else 'FAIL'}** "
                 f"({sum(not x for x in v.values())} of {len(v)} gates failed)")
    L += ["", "### Per year (P&L, slip 1)", "", md(years.round(0)), "",
          "### Long vs short", "", md(by_side.round(1)), "", md(by_side_year.round(0)), "",
          "### By trade class", "", md(by_cls.round(1)), ""]
    if len(nb):
        L += ["## 3. Neighbours (one step from each published value, OOS, slip 1)", "",
              f"Profitable: {share:.0%} (gate: >= {GATES['min_neighbours_profitable']:.0%}).", "",
              md(nb.round(2), index=False), ""]
    L += ["## Not modelled", "",
          "Bot's 45 s order delay and chase re-entries, partial fills, rejections, the hedge guard, "
          "news/EIA effects beyond what is in the prices. Before 2021 MCL did not exist: MCL legs are "
          "CL prices at $1/tick (sizing study)."]
    (OUT / "report.md").write_text("\n".join(L) + "\n")
    (OUT / "summary.json").write_text(json.dumps({"replicate": rep, "oos": oos, "gates": verdicts},
                                                 default=lambda x: x.item() if hasattr(x, "item") else str(x),
                                                 indent=1))
    print("\n".join(L))


if __name__ == "__main__":
    main()
