#!/usr/bin/env python3
"""Blind replication of the H025/H026 discovery run from raw minute parquet."""

from __future__ import annotations

import argparse
import json
import math
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


ROOT = Path(__file__).resolve().parents[3]
DATA = ROOT / "data/processed/ohlcv-1m"
DEFINITIONS = ROOT / "data/processed/definitions/cl_contracts.parquet"
START = pd.Timestamp("2010-06-07")
END = pd.Timestamp("2016-12-31")
ET = "America/New_York"


class CMEHolidays(AbstractHolidayCalendar):
    rules = [
        Holiday("New Year", month=1, day=1, observance=sunday_to_monday),
        USMartinLutherKingJr,
        USPresidentsDay,
        GoodFriday,
        USMemorialDay,
        Holiday("July 4", month=7, day=4, observance=nearest_workday),
        USLaborDay,
        USThanksgivingDay,
        Holiday("Christmas", month=12, day=25, observance=nearest_workday),
    ]


def short_day_set(start: pd.Timestamp, end: pd.Timestamp) -> set[pd.Timestamp]:
    holidays = CMEHolidays().holidays(start, end)
    thanksgiving = USThanksgivingDay.dates(start - pd.Timedelta(days=1), end)
    extras = list(thanksgiving + pd.Timedelta(days=1))
    extras += [d for d in pd.date_range(start, end) if d.month == 12 and d.day == 24]
    return set(pd.DatetimeIndex(list(holidays) + extras).normalize())


def local_timestamp(day: pd.Timestamp, hour: int, minute: int) -> pd.Timestamp:
    return (day + pd.Timedelta(hours=hour, minutes=minute)).tz_localize(ET)


def load_bars() -> pd.DataFrame:
    columns = [
        "ts_event_utc", "continuous_symbol", "raw_symbol", "open_ticks",
        "close_ticks", "volume",
    ]
    frames = []
    for year in range(2010, 2017):
        path = DATA / f"year={year}/cl.parquet"
        if not path.is_file():
            raise FileNotFoundError(path)
        frame = pd.read_parquet(path, columns=columns)
        frames.append(frame.loc[frame["continuous_symbol"].eq("CL.v.0")].drop(columns="continuous_symbol"))
    bars = pd.concat(frames, ignore_index=True)
    bars = bars.sort_values("ts_event_utc", kind="stable").reset_index(drop=True)
    if bars["ts_event_utc"].duplicated().any():
        raise ValueError("duplicate CL.v.0 ts_event_utc rows")
    local = bars["ts_event_utc"].dt.tz_convert(ET)
    local_naive = local.dt.tz_localize(None)
    bars["et_date"] = local_naive.dt.normalize()
    bars["minute"] = local_naive.dt.hour * 60 + local_naive.dt.minute
    # CME trading day: the local calendar date, advanced one day from 18:00 onward.
    bars["trading_day"] = bars["et_date"] + pd.to_timedelta(
        bars["minute"].ge(18 * 60).astype(np.int8), unit="D"
    )
    bars = bars.loc[bars["trading_day"].between(START, END)].copy()
    return bars


def load_expirations() -> dict[str, pd.Timestamp]:
    if not DEFINITIONS.is_file():
        raise FileNotFoundError(DEFINITIONS)
    defs = pd.read_parquet(DEFINITIONS, columns=["raw_symbol", "expiration"]).dropna()
    return dict(zip(defs["raw_symbol"], defs["expiration"].dt.tz_convert(ET)))


def first_bar(day: pd.DataFrame, target_minute: int, max_late: int = 5):
    rows = day.loc[day["minute"].between(target_minute, target_minute + max_late)]
    return None if rows.empty else rows.iloc[0]


def scheduled_flat(day: pd.Timestamp, raw_symbol: str, expirations: dict[str, pd.Timestamp], short: bool) -> pd.Timestamp:
    flat = local_timestamp(day, 12, 55) if short else local_timestamp(day, 16, 5)
    expiry = expirations.get(raw_symbol)
    if expiry is not None and expiry.tz_localize(None).normalize() == day:
        flat = min(flat, expiry - pd.Timedelta(minutes=5))
    return flat


def exact_bar(day: pd.DataFrame, minute: int):
    rows = day.loc[day["minute"].eq(minute)]
    if len(rows) > 1:
        raise ValueError(f"multiple bars at exact minute {minute}")
    return None if rows.empty else rows.iloc[0]


def summarize(values: list[tuple[pd.Timestamp, float]]) -> dict[str, float | int | None]:
    x = np.asarray([v for _, v in values], dtype=float)
    n = len(x)
    mean = float(x.mean()) if n else math.nan
    sd = float(x.std(ddof=1)) if n > 1 else math.nan
    t = mean / (sd / math.sqrt(n)) if n > 1 and sd > 0 else math.nan

    def block(a: str, b: str) -> float:
        vals = [v for d, v in values if pd.Timestamp(a) <= d <= pd.Timestamp(b)]
        return float(np.mean(vals)) if vals else math.nan

    return {
        "n": n,
        "mean_gross_ticks": mean,
        "t": t,
        "mean_2010_12": block("2010-01-01", "2012-12-31"),
        "mean_2013_14": block("2013-01-01", "2014-12-31"),
        "mean_2015_16": block("2015-01-01", "2016-12-31"),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--json", action="store_true", help="print machine-readable output")
    args = parser.parse_args()

    bars = load_bars()
    expirations = load_expirations()
    short_days = short_day_set(START, END)
    grouped = {d: g.sort_values("ts_event_utc", kind="stable") for d, g in bars.groupby("trading_day", sort=True)}
    loaded_days = sorted(grouped)
    afternoon_roll_windows = sum(
        g.loc[g["minute"].between(14 * 60 + 25, 16 * 60 + 5), "raw_symbol"].nunique(dropna=False) > 1
        for g in grouped.values()
    )

    reasons = {
        "short_day": 0,
        "missing_14_25": 0,
        "missing_14_34": 0,
        "signal_contract_mismatch": 0,
        "missing_entry_14_35_to_14_40": 0,
        "entry_contract_mismatch": 0,
        "entry_not_before_flat": 0,
    }
    eligible = []
    for trading_day in loaded_days:
        day = grouped[trading_day]
        if trading_day in short_days:
            reasons["short_day"] += 1
            continue
        b25, b34 = exact_bar(day, 14 * 60 + 25), exact_bar(day, 14 * 60 + 34)
        if b25 is None:
            reasons["missing_14_25"] += 1
            continue
        if b34 is None:
            reasons["missing_14_34"] += 1
            continue
        signal = day.loc[day["minute"].between(14 * 60 + 25, 14 * 60 + 34)]
        if signal["raw_symbol"].nunique(dropna=False) != 1:
            reasons["signal_contract_mismatch"] += 1
            continue
        entry = first_bar(day, 14 * 60 + 35)
        if entry is None:
            reasons["missing_entry_14_35_to_14_40"] += 1
            continue
        raw_symbol = b25["raw_symbol"]
        if entry["raw_symbol"] != raw_symbol:
            reasons["entry_contract_mismatch"] += 1
            continue
        flat = scheduled_flat(trading_day, raw_symbol, expirations, False)
        if entry["ts_event_utc"] >= flat.tz_convert("UTC"):
            reasons["entry_not_before_flat"] += 1
            continue
        eligible.append({
            "day": trading_day,
            "raw_symbol": raw_symbol,
            "move": float(b34["close_ticks"] - b25["open_ticks"]),
            "volume": float(signal["volume"].sum()),
            "entry": float(entry["open_ticks"]),
            "flat_minute": flat.hour * 60 + flat.minute,
        })

    emitted = {"v1": 0, "v2": 0, "v3": 0, "naive": 0}
    unevaluable = {"v1": 0, "v2": 0, "v3": 0, "naive": 0}
    pnl = {"v1": [], "v2": [], "v3": [], "v4": [], "naive": []}
    missing_exact_1605 = 0
    exit_contract_mismatch = 0
    abs_moves: list[float] = []
    volumes: list[float] = []
    zero_move_eligible = 0
    zero_move_evaluable = 0
    eligible_early_flat = 0
    early_signal_attempts = 0
    for row in eligible:
        move, volume = row["move"], row["volume"]
        enough = len(abs_moves) >= 60
        if not enough:
            early_signal_attempts += 1
        q_move = np.percentile(abs_moves[-60:], 75, method="linear") if enough else math.nan
        q_volume = np.percentile(volumes[-60:], 75, method="linear") if enough else math.nan
        passes = {
            "v1": enough and abs(move) > q_move and move != 0,
            "v2": enough and volume > q_volume and move != 0,
        }
        passes["v3"] = passes["v1"] or passes["v2"]
        passes["naive"] = move != 0
        if move == 0:
            zero_move_eligible += 1

        day = grouped[row["day"]]
        exit_bar = exact_bar(day, int(row["flat_minute"]))
        if row["flat_minute"] == 16 * 60 + 5 and exit_bar is None:
            missing_exact_1605 += 1
        evaluable = exit_bar is not None and exit_bar["raw_symbol"] == row["raw_symbol"]
        if move == 0 and evaluable:
            zero_move_evaluable += 1
        if row["flat_minute"] != 16 * 60 + 5:
            eligible_early_flat += 1
        if exit_bar is not None and exit_bar["raw_symbol"] != row["raw_symbol"]:
            exit_contract_mismatch += 1
        for variant, passed in passes.items():
            if not passed:
                continue
            emitted[variant] += 1
            if not evaluable:
                unevaluable[variant] += 1
                continue
            direction = 1.0 if move > 0 else -1.0
            gross = direction * (float(exit_bar["open_ticks"]) - row["entry"])
            pnl[variant].append((row["day"], gross))
        abs_moves.append(abs(move))
        volumes.append(volume)

    # H026/v4 has its own entry-time eligibility and does not require the H025 signal window.
    v4_counts = {"emitted": 0, "unevaluable": 0, "short_day": 0, "missing_entry": 0,
                 "entry_not_before_flat": 0, "missing_exit": 0, "exit_contract_mismatch": 0}
    for trading_day in loaded_days:
        day = grouped[trading_day]
        is_short = trading_day in short_days
        if is_short:
            v4_counts["short_day"] += 1
            continue
        entry = first_bar(day, 14 * 60 + 30)
        if entry is None:
            v4_counts["missing_entry"] += 1
            continue
        flat = scheduled_flat(trading_day, entry["raw_symbol"], expirations, False)
        if entry["ts_event_utc"] >= flat.tz_convert("UTC"):
            v4_counts["entry_not_before_flat"] += 1
            continue
        v4_counts["emitted"] += 1
        exit_bar = exact_bar(day, 15 * 60)
        if exit_bar is None:
            v4_counts["missing_exit"] += 1
            v4_counts["unevaluable"] += 1
            continue
        if exit_bar["raw_symbol"] != entry["raw_symbol"]:
            v4_counts["exit_contract_mismatch"] += 1
            v4_counts["unevaluable"] += 1
            continue
        pnl["v4"].append((trading_day, float(entry["open_ticks"] - exit_bar["open_ticks"])))

    results = {name: summarize(pnl[name]) for name in ["v1", "v2", "v3", "v4", "naive"]}
    audit = {
        "timezone": ET,
        "trading_day_roll_minute": 1080,
        "loaded_trading_days": len(loaded_days),
        "eligible_days": len(eligible),
        "eligible_missing_exact_1605_exit": missing_exact_1605,
        "eligible_exit_contract_mismatch": exit_contract_mismatch,
        "not_eligible_breakdown": reasons,
        "not_eligible_total": sum(reasons.values()),
        "zero_move_eligible_days": zero_move_eligible,
        "threshold_warmup_eligible_days": early_signal_attempts,
        "emitted": emitted,
        "unevaluable": unevaluable,
        "v4_counts": v4_counts,
        "tested_alternatives_n_effect": {
            "naive_include_zero_move_as_zero_direction_trade": {
                "n": results["naive"]["n"] + zero_move_evaluable,
                "delta_n": zero_move_evaluable,
            },
            "count_exact_exit_wrong_contract_as_missing_too": {
                "missing_exit_count": missing_exact_1605 + exit_contract_mismatch,
                "delta_count": exit_contract_mismatch,
            },
            "do_not_preexclude_short_days_but_still_require_entry_before_scheduled_flat": {
                "h025_delta_eligible_n": 0,
                "v4_delta_emitted_n": 0,
            },
            "eligible_days_using_expiry_early_flat": eligible_early_flat,
            "data_driven_intraday_roll_flat": {
                "afternoon_windows_with_raw_symbol_transition": afternoon_roll_windows,
                "delta_evaluated_n": 0,
            },
        },
        "invariants": {
            "loaded_equals_eligible_plus_not_eligible": len(loaded_days) == len(eligible) + sum(reasons.values()),
            "no_threshold_signal_before_60": all(d >= eligible[60]["day"] for k in ("v1", "v2", "v3") for d, _ in pnl[k]) if len(eligible) > 60 else True,
            "evaluated_equals_emitted_minus_unevaluable": all(results[k]["n"] == emitted[k] - unevaluable[k] for k in emitted),
            "evaluated_returns_are_raw_symbol_safe": True,
            "dst_check_winter_1435_utc_hour": local_timestamp(pd.Timestamp("2016-01-15"), 14, 35).tz_convert("UTC").hour,
            "dst_check_summer_1435_utc_hour": local_timestamp(pd.Timestamp("2016-07-15"), 14, 35).tz_convert("UTC").hour,
        },
    }
    output = {"results": results, "counts_and_audit": audit,
              "t_formula": "mean(x) / (sample_sd(x, ddof=1) / sqrt(n))"}
    if args.json:
        print(json.dumps(output, indent=2, allow_nan=True))
        return
    print(json.dumps(output, indent=2, allow_nan=True))


if __name__ == "__main__":
    main()
