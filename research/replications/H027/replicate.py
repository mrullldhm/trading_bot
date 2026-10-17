"""Independent, blind replication of H027 stage 1.

This module intentionally does not import propfirm_research.settlement or grid.
It implements card section 4 directly from the processed parquet files.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
from pandas.tseries.holiday import (
    AbstractHolidayCalendar,
    GoodFriday,
    Holiday,
    USLaborDay,
    USMartinLutherKingJr,
    USMemorialDay,
    USPresidentsDay,
    USThanksgivingDay,
    nearest_workday,
    sunday_to_monday,
)
from scipy import stats


ROOT = Path(__file__).resolve().parents[3]
OUT = Path(__file__).resolve().parent
ET = "America/New_York"
START = pd.Timestamp("2015-01-02")
END = pd.Timestamp("2016-12-30")
ENTRY_TOL_MIN = 5
BASE_COST = 2.402
STRESS_COST = 4.402


class CMEHolidays(AbstractHolidayCalendar):
    rules = [
        Holiday("New Year", month=1, day=1, observance=sunday_to_monday),
        USMartinLutherKingJr,
        USPresidentsDay,
        GoodFriday,
        USMemorialDay,
        Holiday("Juneteenth", month=6, day=19, start_date="2022-01-01", observance=nearest_workday),
        Holiday("July 4", month=7, day=4, observance=nearest_workday),
        USLaborDay,
        USThanksgivingDay,
        Holiday("Christmas", month=12, day=25, observance=nearest_workday),
    ]


def trading_day(ts: pd.Series) -> pd.Series:
    et = ts.dt.tz_convert(ET)
    day = et.dt.tz_localize(None).dt.normalize()
    return day + pd.to_timedelta((et.dt.hour >= 18).astype(int), unit="D")


def utc_clock(day: pd.Timestamp, minute: int) -> pd.Timestamp:
    d = day - pd.Timedelta(days=1) if minute >= 18 * 60 else day
    return (d + pd.Timedelta(minutes=minute)).tz_localize(ET).tz_convert("UTC")


def short_days(days: pd.DatetimeIndex) -> set[pd.Timestamp]:
    holidays = CMEHolidays().holidays(days.min(), days.max())
    thanksgiving = USThanksgivingDay.dates(days.min() - pd.Timedelta(days=1), days.max())
    extra = pd.DatetimeIndex(list(thanksgiving + pd.Timedelta(days=1)) +
                             [d for d in days if d.month == 12 and d.day == 24])
    return set(holidays.union(extra))


def load_cl() -> pd.DataFrame:
    cols = ["ts_event_utc", "continuous_symbol", "raw_symbol", "expiration", "open_ticks"]
    parts = [pd.read_parquet(ROOT / f"data/processed/ohlcv-1m/year={y}/cl.parquet", columns=cols)
             for y in (2014, 2015, 2016)]
    x = pd.concat(parts, ignore_index=True)
    x = x.loc[x["continuous_symbol"].eq("CL.v.0")].copy()
    x["trading_day"] = trading_day(x["ts_event_utc"])
    x["contract"] = x["raw_symbol"].astype(str) + "@" + x["expiration"].dt.strftime("%Y-%m")
    return x.sort_values("ts_event_utc", kind="stable").reset_index(drop=True)


def make_windows(cl: pd.DataFrame, days: pd.DatetimeIndex, entry_min: int, exit_min: int | None) -> pd.DataFrame:
    """Literal implementation of the documented grid entry/strict-exit rules."""
    ts = cl["ts_event_utc"].array.asi8
    td = cl["trading_day"].to_numpy()
    contract = cl["contract"].to_numpy()
    raw = cl["raw_symbol"].to_numpy()
    opn = cl["open_ticks"].to_numpy(float)
    expirations = dict(zip(cl["contract"], cl["expiration"]))
    first = cl.groupby("contract", sort=False)["ts_event_utc"].min().sort_values()
    next_first = first.shift(-1)
    roll = {c: t.floor("h") for c, t in next_first.items() if pd.notna(t)}
    shorts = short_days(days)
    rows = []
    n = len(cl)
    for day in days:
        target = utc_clock(day, entry_min)
        i = int(np.searchsorted(ts, target.value))
        entry_ok = i < n
        if entry_ok:
            delay = (cl.at[i, "ts_event_utc"] - target) / pd.Timedelta(minutes=1)
            entry_ok = delay <= ENTRY_TOL_MIN and td[i] == np.datetime64(day)
        if not entry_ok:
            rows.append({"trading_day": day, "entry_ok": False, "valid": False})
            continue
        c = contract[i]
        flat = utc_clock(day, 12 * 60 + 55 if day in shorts else 16 * 60 + 5)
        exp = expirations[c]
        if pd.notna(exp):
            flat = min(flat, exp - pd.Timedelta(minutes=5))
        if c in roll:
            flat = min(flat, roll[c] - pd.Timedelta(minutes=5))
        target_exit = flat if exit_min is None else utc_clock(day, exit_min)
        entry_ok = bool(target_exit > target and target_exit <= flat and cl.at[i, "ts_event_utc"] < target_exit)
        if not entry_ok:
            rows.append({"trading_day": day, "entry_ok": False, "valid": False})
            continue
        j = int(np.searchsorted(ts, target_exit.value))
        exact = j < n and ts[j] == target_exit.value
        valid = bool(exact and contract[j] == c)
        rows.append({
            "trading_day": day,
            "entry_ok": True,
            "valid": valid,
            "entry_contract": c,
            "entry_raw": raw[i],
            "entry_ticks": opn[i],
            "exit_ticks": opn[j] if valid else np.nan,
            "ret_ticks": opn[j] - opn[i] if valid else np.nan,
        })
    return pd.DataFrame(rows).set_index("trading_day")


def read_stage(table: str, columns: list[str]) -> pd.DataFrame:
    return pd.concat([
        pd.read_parquet(ROOT / f"data/processed/stage1/{table}/year={y}/part.parquet", columns=columns)
        for y in (2015, 2016)
    ], ignore_index=True)


def tas_scores(tas: pd.DataFrame, w: pd.DataFrame, entry_min: int) -> pd.Series:
    out = pd.Series(np.nan, index=w.index, dtype=float)
    for day in w.index[w["entry_ok"]]:
        raw = "CLT" + str(w.at[day, "entry_raw"])[2:]
        in_session = (tas["event_mod"] >= 18 * 60) | (tas["event_mod"] < 14 * 60 + 30)
        g = tas.loc[(tas["trading_day"] == day) & ~tas["is_spread"] & tas["raw_symbol"].eq(raw) &
                    in_session &
                    (tas["ts_recv_utc"] < utc_clock(day, entry_min))]
        if g["instrument_id"].nunique() != 1 or g.empty:
            continue
        signed = g["side"].isin(["A", "B"])
        total_vol = int(g["size"].sum())
        signed_vol = int(g.loc[signed, "size"].sum())
        if 100 * signed_vol < 99 * total_vol:
            continue
        sign = g["side"].map({"B": 1, "A": -1}).fillna(0)
        out.at[day] = float((g["size"] * sign).sum())
    return out


def outright_scores(flow: pd.DataFrame, w: pd.DataFrame, start_min: int, end_min: int,
                    entry_min: int) -> pd.Series:
    out = pd.Series(np.nan, index=w.index, dtype=float)
    for day in w.index[w["entry_ok"]]:
        g = flow.loc[(flow["trading_day"] == day) & (flow["event_mod"] >= start_min) &
                     (flow["event_mod"] < end_min) &
                     (flow["ts_recv_utc"] < utc_clock(day, entry_min))]
        if g.empty:
            out.at[day] = 0.0
            continue
        if not g["raw_symbol"].eq(w.at[day, "entry_raw"]).all():
            continue
        side = g["side"].map({"B": 1.0, "A": -1.0})
        missing = side.isna()
        book_ok = g["bid_ticks"].notna() & g["ask_ticks"].notna() & (g["bid_ticks"] < g["ask_ticks"])
        side.loc[missing & book_ok & (g["price_ticks"] >= g["ask_ticks"])] = 1.0
        side.loc[missing & book_ok & (g["price_ticks"] <= g["bid_ticks"])] = -1.0
        classified = side.notna()
        total_vol = int(g["size"].sum())
        class_vol = int(g.loc[classified, "size"].sum())
        if 100 * class_vol < 99 * total_vol:
            continue
        out.at[day] = float((g.loc[classified, "size"] * side.loc[classified]).sum())
    return out


def bh_qvalues(p: np.ndarray) -> np.ndarray:
    order = np.argsort(p)
    ranked = p[order] * len(p) / np.arange(1, len(p) + 1)
    ranked = np.minimum.accumulate(ranked[::-1])[::-1]
    out = np.empty_like(ranked)
    out[order] = np.minimum(ranked, 1.0)
    return out


def evaluate(name: str, score: pd.Series, w: pd.DataFrame, direction_sign: int,
             elapsed_years: float) -> tuple[dict, float]:
    eligible = score.notna() & w["entry_ok"]
    ordered = score.loc[eligible]
    emit = pd.Series(False, index=w.index)
    for i in range(60, len(ordered)):
        threshold = np.quantile(np.abs(ordered.iloc[i - 60:i].to_numpy()), 0.75, method="linear")
        value = ordered.iloc[i]
        if value != 0 and abs(value) > threshold:
            emit.at[ordered.index[i]] = True
    directions = np.sign(score) * direction_sign
    evaluated = emit & w["valid"]
    pnl = (directions[evaluated] * w.loc[evaluated, "ret_ticks"]).astype(float)
    n = len(pnl)
    mean = float(pnl.mean()) if n else np.nan
    sd = float(pnl.std(ddof=1)) if n >= 2 else np.nan
    t = float(mean / (sd / np.sqrt(n))) if n >= 2 and sd > 0 else np.nan
    p = float(stats.t.sf(t, n - 1)) if n >= 3 and np.isfinite(t) else 1.0
    tpy = n / elapsed_years
    mde = float(3.168 * sd / np.sqrt(5 * tpy)) if tpy > 0 else np.nan
    total = float(pnl.sum())
    largest_share = float(pnl.max() / total) if n and total != 0 else np.nan
    result = {
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
    }
    return result, p


def main() -> None:
    cl = load_cl()
    days = pd.DatetimeIndex(sorted(cl.loc[cl["trading_day"].between(START, END), "trading_day"].unique()))
    elapsed_years = ((days[-1] - days[0]).days + 1) / 365.25
    w35 = make_windows(cl, days, 14 * 60 + 35, None)
    w31 = make_windows(cl, days, 14 * 60 + 31, 15 * 60)

    tas = read_stage("tas_trades", ["ts_event_utc", "ts_recv_utc", "instrument_id", "raw_symbol",
                                           "is_spread", "size", "side"])
    tas["trading_day"] = trading_day(tas["ts_event_utc"])
    et = tas["ts_event_utc"].dt.tz_convert(ET)
    tas["event_mod"] = et.dt.hour * 60 + et.dt.minute + et.dt.second / 60 + et.dt.microsecond / 60e6
    tas = tas.loc[tas["trading_day"].between(START, END)]

    flow = read_stage("cl_mbp1_1420", ["ts_event_utc", "ts_recv_utc", "price_ticks", "size", "side",
                                              "bid_ticks", "ask_ticks", "raw_symbol"])
    flow["trading_day"] = trading_day(flow["ts_event_utc"])
    et = flow["ts_event_utc"].dt.tz_convert(ET)
    flow["event_mod"] = et.dt.hour * 60 + et.dt.minute + et.dt.second / 60 + et.dt.microsecond / 60e6
    flow = flow.loc[flow["trading_day"].between(START, END)]

    specs = [
        ("v1_tas_residual", tas_scores(tas, w35, 14 * 60 + 35), w35, 1),
        ("v2_tas_unwind", tas_scores(tas, w31, 14 * 60 + 31), w31, -1),
        ("v3_outright_residual", outright_scores(flow, w35, 14 * 60 + 25, 14 * 60 + 35,
                                                  14 * 60 + 35), w35, 1),
        ("v4_outright_unwind", outright_scores(flow, w31, 14 * 60 + 20, 14 * 60 + 30,
                                                14 * 60 + 31), w31, -1),
    ]
    rows, ps = [], []
    for name, score, window, sign in specs:
        row, p = evaluate(name, score, window, sign, elapsed_years)
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
    metadata = {"first_loaded_trading_day": str(days[0].date()), "last_loaded_trading_day": str(days[-1].date()),
                "loaded_days": len(days), "elapsed_years": elapsed_years}
    (OUT / "run_metadata.json").write_text(json.dumps(metadata, indent=2) + "\n")
    print(result.to_string(index=False))


if __name__ == "__main__":
    main()
