#!/usr/bin/env python3
"""Independent replication of five S001 cells.

This file deliberately does not import propfirm_research.  The only project helpers
used are propfirm_backtest.orb_engine.local_tmin and short_days, for the exchange
calendar/time-zone conversion permitted by the replication request.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import sys
from pathlib import Path

import numba
import numpy as np
import pandas as pd
from numba import njit

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from propfirm_backtest.orb_engine import local_tmin, short_days


RAW = ROOT / "data" / "processed" / "ohlcv-1m"
DEFAULT_OUT = ROOT / "data" / "research" / "replications" / "S001"
ET = "America/New_York"
DAY0 = np.datetime64("1970-01-01", "D")
FIRST_DAY = np.datetime64("2010-06-07", "D").astype(int)
LAST_DAY = np.datetime64("2016-12-31", "D").astype(int)
FEE = 4.02
COST = 24.02
TICK_USD = 10.0
BLOCK = 5
MAX_DAYS = 250
DD_DAYS = 60
CONSISTENCY = 0.55
N_DRAWS = 20
N_ATTEMPTS = 1_000
A_DAYS = 50_000
A_ATTEMPTS = 20_000

ACCOUNTS = {
    "50K": {"mll": 2_000.0, "target": 3_000.0, "dll": 1_000.0},
    "150K": {"mll": 4_500.0, "target": 9_000.0, "dll": 3_000.0},
}

CELLS = [
    {"cell": 1, "template": "14:00-14:30", "start": 14 * 60, "end": 14 * 60 + 30,
     "freq": 1.0, "account": "50K", "e_net": 8.0, "reserve": 0.0},
    {"cell": 2, "template": "09:00-10:00", "start": 9 * 60, "end": 10 * 60,
     "freq": 0.5, "account": "150K", "e_net": 8.0, "reserve": 0.0},
    {"cell": 3, "template": "14:35-FLAT", "start": 14 * 60 + 35, "end": None,
     "freq": 0.25, "account": "150K", "e_net": 4.0, "reserve": 500.0},
    {"cell": 4, "template": "09:00-10:00", "start": 9 * 60, "end": 10 * 60,
     "freq": 1.0, "account": "50K", "e_net": -2.402, "reserve": 0.0},
]


def utc_minute(ts) -> np.ndarray:
    return ((pd.DatetimeIndex(ts).tz_convert("UTC") - pd.Timestamp("1970-01-01", tz="UTC"))
            // pd.Timedelta(minutes=1)).to_numpy(np.int64)


def clock_tmin(days: np.ndarray, minute: int) -> np.ndarray:
    return local_tmin(days, minute, ET, days_before=1 if minute >= 18 * 60 else 0)


def load_raw() -> pd.DataFrame:
    cols = ["ts_event_utc", "continuous_symbol", "raw_symbol", "expiration",
            "open_ticks", "high_ticks", "low_ticks"]
    pieces = []
    for year in range(2010, 2017):
        p = RAW / f"year={year}" / "cl.parquet"
        d = pd.read_parquet(p, columns=cols)
        pieces.append(d[d["continuous_symbol"] == "CL.v.0"])
    d = pd.concat(pieces, ignore_index=True).sort_values("ts_event_utc").reset_index(drop=True)
    et = d["ts_event_utc"].dt.tz_convert(ET)
    et_day = (et.dt.tz_localize(None).dt.normalize().to_numpy("datetime64[D]").astype(int))
    mod = (et.dt.hour * 60 + et.dt.minute).to_numpy(np.int32)
    tday = et_day + (mod >= 18 * 60)
    keep = (tday >= FIRST_DAY) & (tday <= LAST_DAY)
    d = d.loc[keep].reset_index(drop=True)
    tday, mod = tday[keep], mod[keep]
    d["tmin"] = utc_minute(d["ts_event_utc"])
    d["trading_day"] = tday
    d["mod"] = mod
    d["contract"] = (d["raw_symbol"].astype(str) + "@"
                     + d["expiration"].dt.strftime("%Y-%m"))
    return d


def schedule(d: pd.DataFrame):
    first = d.groupby("contract", sort=False)["tmin"].min().sort_values()
    nxt = first.shift(-1)
    roll = {c: int(v // 60 * 60) for c, v in nxt.items() if pd.notna(v)}
    expiry = dict(zip(d["contract"], utc_minute(d["expiration"])))
    return roll, expiry


def all_days(d: pd.DataFrame) -> np.ndarray:
    # The raw front series supplies every observed CME session, including sessions
    # where a requested template itself is invalid.
    return np.unique(d["trading_day"].to_numpy(np.int64))


def make_window(d: pd.DataFrame, days: np.ndarray, start_mod: int, end_mod: int | None,
                roll: dict, expiry: dict) -> dict:
    t = d["tmin"].to_numpy(np.int64)
    td = d["trading_day"].to_numpy(np.int64)
    contract = d["contract"].to_numpy(object)
    opn = d["open_ticks"].to_numpy(float)
    high = d["high_ticks"].to_numpy(float)
    low = d["low_ticks"].to_numpy(float)
    flat = clock_tmin(days, 16 * 60 + 5)
    short = short_days(days)
    flat[short] = clock_tmin(days[short], 12 * 60 + 55)
    target0 = clock_tmin(days, start_mod)
    i0 = np.searchsorted(t, target0)
    valid = i0 < len(t)
    safe0 = np.minimum(i0, len(t) - 1)
    valid &= (t[safe0] - target0 <= 5) & (td[safe0] == days)
    day_flat = flat.copy()
    for k, ix in enumerate(safe0):
        c = contract[ix]
        day_flat[k] = min(day_flat[k], expiry[c] - 5, roll.get(c, 2**62) - 5)
    # Apply the stated convention literally: entries in [flat-5, flat) are invalid.
    valid &= t[safe0] < day_flat - 5
    target1 = day_flat if end_mod is None else clock_tmin(days, end_mod)
    valid &= (target1 > target0) & (target1 <= day_flat)
    i1 = np.searchsorted(t, target1)
    safe1 = np.minimum(i1, len(t) - 1)
    valid &= (i1 < len(t)) & (t[safe1] - target1 <= 5)
    valid &= contract[safe1] == contract[safe0]
    valid &= td[safe1] == days
    i0 = np.where(valid, safe0, -1)
    i1 = np.where(valid, safe1, -1)
    ret = np.zeros(len(days), float)
    ret[valid] = opn[i1[valid]] - opn[i0[valid]]
    return {"valid": valid, "i0": i0, "i1": i1, "ret": ret,
            "t": t, "open": opn, "high": high, "low": low}


@njit(cache=True)
def adverse_ticks(t, opn, high, low, i0, i1, direction, drift):
    out = np.zeros(len(i0))
    for k in range(len(i0)):
        if direction[k] == 0 or i0[k] < 0:
            continue
        span = t[i1[k]] - t[i0[k]]
        worst = 0.0
        entry = opn[i0[k]]
        for j in range(i0[k], i1[k]):
            frac = (t[j] - t[i0[k]]) / span
            if direction[k] > 0:
                adverse = entry - (low[j] + drift * frac)
            else:
                adverse = (high[j] - drift * frac) - entry
            if adverse > worst:
                worst = adverse
        out[k] = worst
    return out


def day_series(w: dict, direction: np.ndarray, drift: float):
    traded = direction != 0
    adv = adverse_ticks(w["t"], w["open"], w["high"], w["low"],
                        w["i0"], w["i1"], direction, drift)
    pnl = np.zeros(len(direction))
    mae = np.zeros(len(direction))
    pnl[traded] = (direction[traded] * w["ret"][traded] + drift) * TICK_USD - COST
    mae[traded] = (adv[traded] + 1.0) * TICK_USD + FEE
    low = np.minimum(np.minimum(-mae, pnl), 0.0)
    return pnl, low


def apply_dll(pnl, low, dll, contracts=1):
    p = pnl * contracts
    l = low * contracts
    hit = l <= -dll
    stopped = -(dll + 10.0 * contracts)
    return np.where(hit, stopped, p), np.where(hit, stopped, l), hit


@njit(cache=True)
def simulate(pnl, low, starts, target, mll, consistency):
    n_attempts = starts.shape[0]
    outcomes = np.zeros(n_attempts, np.int8)
    used = np.zeros(n_attempts, np.int16)
    dds = np.zeros(n_attempts)
    n = len(pnl)
    for s in range(n_attempts):
        bal = 0.0
        peak = 0.0
        floor = -mll
        best = 0.0
        worst_dd = 0.0
        day = 0
        done = False
        for b in range(starts.shape[1]):
            for off in range(BLOCK):
                if day >= MAX_DAYS:
                    done = True
                    break
                k = (starts[s, b] + off) % n
                trough = bal + low[k]
                if day < DD_DAYS:
                    drop = peak - trough
                    if drop > worst_dd:
                        worst_dd = drop
                if trough <= floor:
                    outcomes[s] = -1
                    used[s] = day + 1
                    done = True
                    break
                bal += pnl[k]
                if pnl[k] > best:
                    best = pnl[k]
                if bal > peak:
                    peak = bal
                    floor = min(0.0, peak - mll)
                day += 1
                if bal >= target and best <= consistency * bal:
                    outcomes[s] = 1
                    used[s] = day
                    done = True
                    break
            if done:
                break
        if not done:
            used[s] = MAX_DAYS
        dds[s] = worst_dd
    return outcomes, used, dds


def one_simulation(pnl, low, account, reserve, attempts, seed):
    a = ACCOUNTS[account]
    stopped_pnl, stopped_low, hit = apply_dll(pnl, low, a["dll"])
    rng = np.random.Generator(np.random.PCG64DXSM(seed))
    starts = rng.integers(0, len(pnl), size=(attempts, MAX_DAYS // BLOCK + 1), dtype=np.int32)
    outcomes, used, dds = simulate(stopped_pnl, stopped_low, starts, a["target"],
                                   a["mll"] - reserve, CONSISTENCY)
    return outcomes, used, dds, hit


def metrics_from_arrays(outcomes, used, dds):
    passed = outcomes == 1
    return {
        "pass_pct": 100 * passed.mean(),
        "fail_pct": 100 * (outcomes == -1).mean(),
        "p95_drop": float(np.quantile(dds, .95)),
        "median_days_pass": float(np.median(used[passed])) if passed.any() else None,
    }


def moments(series_list):
    x = np.concatenate(series_list)
    mean = float(x.mean())
    sd = float(x.std(ddof=0))
    return mean, mean / sd * np.sqrt(252) if sd else None


def part_b(d, days, roll, expiry, attempts):
    windows = {}
    for c in CELLS:
        key = (c["start"], c["end"])
        if key not in windows:
            windows[key] = make_window(d, days, *key, roll, expiry)
    rows, pair_rows, gross_sd = [], [], {}
    for c in CELLS:
        w = windows[(c["start"], c["end"])]
        valid = w["valid"]
        # With antithetic directions the zero-edge signed-return mean is exactly zero,
        # hence its population SD is the RMS raw return over eligible windows.
        gross_sd[c["template"]] = float(np.sqrt(np.mean(w["ret"][valid] ** 2)))
        drift = c["e_net"] + 2.402
        draw_records = []
        for pair in range(N_DRAWS // 2):
            rng = np.random.Generator(np.random.PCG64DXSM(710_000 + c["cell"] * 100 + pair))
            base_sign = rng.choice(np.array([-1.0, 1.0]), len(days))
            select = rng.random(len(days)) < c["freq"]
            active = valid & select
            for anti in range(2):
                direction = np.where(active, base_sign * (1 if anti == 0 else -1), 0.0)
                pnl, low = day_series(w, direction, drift)
                seed = 920_000 + c["cell"] * 10_000 + pair * 2 + anti
                outcomes, used, dds, hit = one_simulation(
                    pnl, low, c["account"], c["reserve"], attempts, seed)
                draw_records.append({"pair": pair, "anti": anti, "pnl": pnl,
                                     "outcomes": outcomes, "used": used, "dds": dds,
                                     "hit": hit, "trades": int(active.sum())})
        outcomes = np.concatenate([r["outcomes"] for r in draw_records])
        used = np.concatenate([r["used"] for r in draw_records])
        dds = np.concatenate([r["dds"] for r in draw_records])
        mean, sharpe = moments([r["pnl"] for r in draw_records])
        row = {"cell": c["cell"], "part": "B", "template": c["template"],
               "freq": c["freq"], "account": c["account"], "reserve": c["reserve"],
               "e_net": c["e_net"], "g_gross": drift, "valid_days": int(valid.sum()),
               "calendar_days": len(days), "trades": float(np.mean([r["trades"] for r in draw_records])),
               "trade_min": int(min(r["trades"] for r in draw_records)),
               "trade_max": int(max(r["trades"] for r in draw_records)),
               "mean_day_pnl": mean, "annual_sharpe": sharpe,
               "dll_hit_share_pct": 100 * np.mean(np.concatenate([r["hit"] for r in draw_records])),
               "attempts": len(outcomes), **metrics_from_arrays(outcomes, used, dds),
               "gross_return_sd_ticks": gross_sd[c["template"]]}
        rows.append(row)
        for pair in range(N_DRAWS // 2):
            rr = [r for r in draw_records if r["pair"] == pair]
            po = np.concatenate([r["outcomes"] for r in rr])
            pu = np.concatenate([r["used"] for r in rr])
            pd_ = np.concatenate([r["dds"] for r in rr])
            pm, ps = moments([r["pnl"] for r in rr])
            pair_rows.append({"cell": c["cell"], "pair": pair, "trades": rr[0]["trades"],
                              "mean_day_pnl": pm, "annual_sharpe": ps,
                              "dll_hit_share_pct": 100 * np.mean(np.concatenate([r["hit"] for r in rr])),
                              **metrics_from_arrays(po, pu, pd_)})
    # Attach min/max spread across the ten independent antithetic pairs.
    pr = pd.DataFrame(pair_rows)
    spread_cols = ["pass_pct", "fail_pct", "p95_drop", "median_days_pass",
                   "dll_hit_share_pct", "mean_day_pnl", "annual_sharpe"]
    for row in rows:
        q = pr[pr.cell == row["cell"]]
        row["pair_spread"] = {k: [float(q[k].min()), float(q[k].max())] for k in spread_cols}
    return rows, pr, gross_sd


def part_a(attempts):
    rng = np.random.Generator(np.random.PCG64DXSM(3_141_592_653))
    sd = 150.0
    mu = 2.0 * sd / np.sqrt(252)
    pnl = rng.normal(mu, sd, A_DAYS)
    u = rng.random(A_DAYS)
    low = (pnl - np.sqrt(pnl * pnl - 2 * sd * sd * np.log(u))) / 2
    outcomes, used, dds, hit = one_simulation(pnl, low, "50K", 0.0, attempts, 2_718_281_828)
    mean = float(pnl.mean())
    sharpe = mean / pnl.std(ddof=0) * np.sqrt(252)
    return {"cell": 5, "part": "A", "template": "Normal bridge", "freq": 1.0,
            "account": "50K", "reserve": 0.0, "e_net": None, "g_gross": None,
            "valid_days": A_DAYS, "calendar_days": A_DAYS, "trades": A_DAYS,
            "trade_min": A_DAYS, "trade_max": A_DAYS, "mean_day_pnl": mean,
            "annual_sharpe": float(sharpe), "dll_hit_share_pct": 100 * hit.mean(),
            "attempts": attempts, **metrics_from_arrays(outcomes, used, dds),
            "gross_return_sd_ticks": None, "pair_spread": None}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--output", type=Path, default=DEFAULT_OUT)
    ap.add_argument("--attempts", type=int, default=N_ATTEMPTS,
                    help="attempts per Part-B direction draw")
    ap.add_argument("--part-a-attempts", type=int, default=A_ATTEMPTS)
    args = ap.parse_args()
    if args.attempts < 1000:
        raise SystemExit("--attempts must be at least 1000")
    d = load_raw()
    days = all_days(d)
    roll, expiry = schedule(d)
    b_rows, pair_rows, gross_sd = part_b(d, days, roll, expiry, args.attempts)
    a_row = part_a(args.part_a_attempts)
    args.output.mkdir(parents=True, exist_ok=True)
    pair_rows.to_csv(args.output / "pair_metrics.csv", index=False)
    source_sha = hashlib.sha256()
    for year in range(2010, 2017):
        p = RAW / f"year={year}" / "cl.parquet"
        source_sha.update(p.read_bytes())
    result = {
        "method": {"part_b_direction_draws": N_DRAWS, "antithetic_pairs": N_DRAWS // 2,
                   "attempts_per_draw": args.attempts, "part_a_source_days": A_DAYS,
                   "part_a_attempts": args.part_a_attempts, "bootstrap_block": BLOCK,
                   "max_days": MAX_DAYS, "drawdown_days": DD_DAYS,
                   "rng": "numpy PCG64DXSM", "dll_liquidation_slip_ticks": 1,
                   "calendar_helpers": ["propfirm_backtest.orb_engine.local_tmin",
                                        "propfirm_backtest.orb_engine.short_days"]},
        "data": {"rows": len(d), "calendar_days": len(days),
                 "first_day": str(pd.Timestamp(days[0], unit="D").date()),
                 "last_day": str(pd.Timestamp(days[-1], unit="D").date()),
                 "raw_parquet_sha256_combined": source_sha.hexdigest()},
        "versions": {"python": platform.python_version(), "numpy": np.__version__,
                     "pandas": pd.__version__, "numba": numba.__version__},
        "gross_return_sd_ticks": gross_sd,
        "cells": b_rows + [a_row],
    }
    (args.output / "results.json").write_text(json.dumps(result, indent=2) + "\n")
    pd.DataFrame([{k: v for k, v in r.items() if k != "pair_spread"}
                  for r in result["cells"]]).to_csv(args.output / "headline.csv", index=False)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
