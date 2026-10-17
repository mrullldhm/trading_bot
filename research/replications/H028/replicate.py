"""Independent, blind replication of H028 stage 1.

H027.replicate supplies only this replication's independently written calendar,
window, BH, and parquet helpers; no production settlement/grid code is imported.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO))

from research.replications.H027.replicate import (
    BASE_COST,
    END,
    ET,
    ROOT,
    START,
    STRESS_COST,
    bh_qvalues,
    load_cl,
    make_windows,
    read_stage,
    trading_day,
    utc_clock,
)


OUT = Path(__file__).resolve().parent


def exact_bar(frame: pd.DataFrame, day: pd.Timestamp, minute: int) -> pd.Series | None:
    target = utc_clock(day, minute)
    g = frame.loc[frame["ts_event_utc"].eq(target)]
    return None if len(g) != 1 else g.iloc[0]


def cl_returns(cl: pd.DataFrame, days: pd.DatetimeIndex, w: pd.DataFrame) -> pd.Series:
    out = pd.Series(np.nan, index=days, dtype=float)
    stage = cl.loc[cl["trading_day"].between(START, END)]
    for day in days:
        a = exact_bar(stage, day, 14 * 60 + 25)
        b = exact_bar(stage, day, 14 * 60 + 34)
        if a is None or b is None or not w.at[day, "entry_ok"]:
            continue
        if a["contract"] == b["contract"] == w.at[day, "entry_contract"]:
            out.at[day] = np.log(float(b["open_ticks"] * 0 + b["close_ticks"]) / float(a["open_ticks"]))
    return out


def energy_returns(frame: pd.DataFrame, days: pd.DatetimeIndex, symbol: str) -> pd.Series:
    out = pd.Series(np.nan, index=days, dtype=float)
    x = frame.loc[frame["continuous_symbol"].eq(symbol)].copy()
    for day in days:
        g = x.loc[x["trading_day"].eq(day)]
        if symbol != "BZ.v.0":
            a = exact_bar(g, day, 14 * 60 + 25)
            b = exact_bar(g, day, 14 * 60 + 34)
            if a is not None and b is not None and a["instrument_id"] == b["instrument_id"]:
                out.at[day] = np.log(float(b["close_ticks"]) / float(a["open_ticks"]))
            continue
        exact_start = exact_bar(g, day, 14 * 60 + 25)
        if exact_start is not None:
            start_row, start_px = exact_start, float(exact_start["open_ticks"])
        else:
            lo, hi = utc_clock(day, 14 * 60 + 22), utc_clock(day, 14 * 60 + 25)
            candidates = g.loc[g["ts_event_utc"].ge(lo) & g["ts_event_utc"].lt(hi)]
            if candidates.empty:
                continue
            start_row = candidates.iloc[-1]
            start_px = float(start_row["close_ticks"])
        lo, hi = utc_clock(day, 14 * 60 + 32), utc_clock(day, 14 * 60 + 35)
        candidates = g.loc[g["ts_event_utc"].ge(lo) & g["ts_event_utc"].lt(hi)]
        if candidates.empty:
            continue
        end_row = candidates.iloc[-1]
        if start_row["instrument_id"] == end_row["instrument_id"]:
            out.at[day] = np.log(float(end_row["close_ticks"]) / start_px)
    return out


def causal_z(r: pd.Series) -> pd.Series:
    out = pd.Series(np.nan, index=r.index, dtype=float)
    valid = r.dropna()
    for i in range(20, len(valid)):
        sigma = valid.iloc[i - 20:i].std(ddof=1)
        if np.isfinite(sigma) and sigma > 0:
            out.at[valid.index[i]] = valid.iloc[i] / sigma
    return out


def evaluate(name: str, eligible: pd.Series, direction: pd.Series, w: pd.DataFrame,
             elapsed_years: float) -> tuple[dict, float]:
    emit = eligible & direction.ne(0) & direction.notna()
    evaluated = emit & w["valid"]
    pnl = (direction[evaluated] * w.loc[evaluated, "ret_ticks"]).astype(float)
    n = len(pnl)
    mean = float(pnl.mean()) if n else np.nan
    sd = float(pnl.std(ddof=1)) if n >= 2 else np.nan
    t = float(mean / (sd / np.sqrt(n))) if n >= 2 and sd > 0 else np.nan
    p = float(stats.t.sf(t, n - 1)) if n >= 3 and np.isfinite(t) else 1.0
    tpy = n / elapsed_years
    mde = float(3.168 * sd / np.sqrt(5 * tpy)) if tpy > 0 else np.nan
    total = float(pnl.sum())
    largest_share = float(pnl.max() / total) if n and total != 0 else np.nan
    return {
        "variant": name,
        "entry_time_eligible_days": int(eligible.sum()),
        "emitted_signals": int(emit.sum()),
        "evaluated_trades": n,
        "gross_mean_ticks": mean,
        "sample_sd_ticks": sd,
        "one_sided_t": t,
        "gross_mean_2015": float(pnl[pnl.index.year == 2015].mean()),
        "gross_mean_2016": float(pnl[pnl.index.year == 2016].mean()),
        "net_base_ticks": mean - BASE_COST,
        "net_stress_ticks": mean - STRESS_COST,
        "trades_per_year": tpy,
        "MDE_net_ticks": mde,
        "largest_single_day_share": largest_share,
        "p_one_sided": p,
    }, p


def main() -> None:
    # H028 needs CL close_ticks in addition to the shared window loader's columns.
    cl = load_cl()
    close_parts = [pd.read_parquet(ROOT / f"data/processed/ohlcv-1m/year={y}/cl.parquet",
                                   columns=["ts_event_utc", "continuous_symbol", "close_ticks"])
                   for y in (2014, 2015, 2016)]
    closes = pd.concat(close_parts, ignore_index=True)
    closes = closes.loc[closes["continuous_symbol"].eq("CL.v.0"), ["ts_event_utc", "close_ticks"]]
    cl = cl.merge(closes, on="ts_event_utc", how="left", validate="one_to_one")
    days = pd.DatetimeIndex(sorted(cl.loc[cl["trading_day"].between(START, END), "trading_day"].unique()))
    elapsed_years = ((days[-1] - days[0]).days + 1) / 365.25
    w = make_windows(cl, days, 14 * 60 + 35, None)

    energy = read_stage("energy_ohlcv_1m", ["ts_event_utc", "continuous_symbol", "instrument_id",
                                                    "open_ticks", "close_ticks"])
    energy["trading_day"] = trading_day(energy["ts_event_utc"])
    energy = energy.loc[energy["trading_day"].between(START, END)].sort_values("ts_event_utc")

    returns = {
        "CL": cl_returns(cl, days, w),
        "RB": energy_returns(energy, days, "RB.v.0"),
        "HO": energy_returns(energy, days, "HO.v.0"),
        "BZ": energy_returns(energy, days, "BZ.v.0"),
    }
    z = {k: causal_z(v) for k, v in returns.items()}
    entry = w["entry_ok"]
    eligible1 = entry & z["CL"].notna() & z["RB"].notna() & z["HO"].notna()
    score1 = (z["RB"] + z["HO"]) / 2 - z["CL"]
    direction1 = np.sign(score1)
    eligible2 = entry & z["CL"].notna() & z["BZ"].notna()
    score2 = z["BZ"] - z["CL"]
    direction2 = np.sign(score2)
    eligible3 = entry & z["CL"].notna() & z["RB"].notna() & z["HO"].notna() & z["BZ"].notna()
    u = pd.concat({k: z[k] - z["CL"] for k in ("RB", "HO", "BZ")}, axis=1)
    all_pos = u.gt(0).all(axis=1)
    all_neg = u.lt(0).all(axis=1)
    direction3 = pd.Series(np.where(all_pos, 1.0, np.where(all_neg, -1.0, 0.0)), index=days)

    specs = [("v1_products", eligible1, direction1), ("v2_brent", eligible2, direction2),
             ("v3_agreement", eligible3, direction3)]
    rows, ps = [], []
    for name, eligible, direction in specs:
        row, p = evaluate(name, eligible, direction, w, elapsed_years)
        rows.append(row)
        ps.append(p)
    qs = bh_qvalues(np.asarray(ps))
    for row, q in zip(rows, qs):
        row["bh_q"] = float(q)
        row["stage1_screen_pass"] = bool(
            q < 0.10 and row["gross_mean_2015"] > 0 and row["gross_mean_2016"] > 0 and
            row["trades_per_year"] >= 25 and row["gross_mean_ticks"] > STRESS_COST and
            row["net_base_ticks"] >= 2 * row["MDE_net_ticks"] and
            row["largest_single_day_share"] <= 0.25
        )
    columns = ["variant", "entry_time_eligible_days", "emitted_signals", "evaluated_trades",
               "gross_mean_ticks", "sample_sd_ticks", "one_sided_t", "gross_mean_2015",
               "gross_mean_2016", "net_base_ticks", "net_stress_ticks", "trades_per_year",
               "MDE_net_ticks", "largest_single_day_share", "stage1_screen_pass", "p_one_sided", "bh_q"]
    result = pd.DataFrame(rows)[columns]
    result.to_csv(OUT / "own_results.csv", index=False, float_format="%.12g")
    metadata = {
        "first_loaded_trading_day": str(days[0].date()),
        "last_loaded_trading_day": str(days[-1].date()),
        "loaded_days": len(days),
        "elapsed_years": elapsed_years,
        "raw_return_days": {k: int(v.notna().sum()) for k, v in returns.items()},
    }
    (OUT / "run_metadata.json").write_text(json.dumps(metadata, indent=2) + "\n")
    print(result.to_string(index=False))


if __name__ == "__main__":
    main()
