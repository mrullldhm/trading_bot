"""Data-quality checks for the processed CL bars.

Usage:
    python -m propfirm_data.validate

ERROR  = the data is wrong; do not backtest on it until fixed.
WARN   = worth a look; often normal (holidays, quiet minutes, roll days).
"""

import sys
from dataclasses import dataclass, field

import pandas as pd

from .config import BARS_DIR

CHICAGO = "America/Chicago"
SESSION_OPEN_HOUR = 17  # CME Globex CL: Sun-Fri 17:00 -> 16:00 next day (Chicago time)
SESSION_CLOSE_HOUR = 16
GAP_WARN_MINUTES = 15


@dataclass
class Issue:
    level: str  # "ERROR" or "WARN"
    check: str
    count: int
    examples: list = field(default_factory=list)


def _examples(df: pd.DataFrame, mask: pd.Series, n: int = 3) -> list:
    cols = [c for c in ["ts_event_utc", "continuous_symbol", "raw_symbol"] if c in df.columns]
    return df.loc[mask, cols].head(n).astype(str).values.tolist()


def check_duplicates(df: pd.DataFrame) -> list[Issue]:
    dup = df.duplicated(["ts_event_utc", "continuous_symbol"], keep=False)
    return [Issue("ERROR", "duplicate bars", int(dup.sum()), _examples(df, dup))] if dup.any() else []


def check_order(df: pd.DataFrame) -> list[Issue]:
    bad = df.groupby("continuous_symbol")["ts_event_utc"].diff() <= pd.Timedelta(0)
    return [Issue("ERROR", "timestamps not increasing", int(bad.sum()), _examples(df, bad))] if bad.any() else []


def check_prices(df: pd.DataFrame) -> list[Issue]:
    issues = []
    nulls = df[["open_ticks", "high_ticks", "low_ticks", "close_ticks", "volume"]].isna().any(axis=1)
    if nulls.any():
        issues.append(Issue("ERROR", "missing prices/volume", int(nulls.sum()), _examples(df, nulls)))
    # Negative prices are allowed: CL settled below zero in April 2020.
    bad_ohlc = (
        (df["low_ticks"] > df[["open_ticks", "close_ticks"]].min(axis=1))
        | (df["high_ticks"] < df[["open_ticks", "close_ticks"]].max(axis=1))
        | (df["low_ticks"] > df["high_ticks"])
    )
    if bad_ohlc.any():
        issues.append(Issue("ERROR", "low/high do not contain open/close", int(bad_ohlc.sum()), _examples(df, bad_ohlc)))
    neg_vol = df["volume"] < 0
    if neg_vol.any():
        issues.append(Issue("ERROR", "negative volume", int(neg_vol.sum()), _examples(df, neg_vol)))
    mismatch = (df["close"] - df["close_ticks"] / 100).abs() > 1e-9
    if mismatch.any():
        issues.append(Issue("ERROR", "float price != ticks/100", int(mismatch.sum()), _examples(df, mismatch)))
    return issues


def check_contracts(df: pd.DataFrame) -> list[Issue]:
    issues = []
    no_sym = df["raw_symbol"].isna() | (df["raw_symbol"].astype(str).isin(["", "nan", "None"]))
    if no_sym.any():
        issues.append(Issue("ERROR", "bar has no real contract symbol", int(no_sym.sum()), _examples(df, no_sym)))
    if "expiration" in df.columns:
        expired = df["expiration"].notna() & (df["ts_event_utc"] >= df["expiration"])
        if expired.any():
            issues.append(Issue("ERROR", "bar is after its contract expired", int(expired.sum()), _examples(df, expired)))
    return issues


def _chicago(df: pd.DataFrame) -> pd.Series:
    return df["ts_event_utc"].dt.tz_convert(CHICAGO)


def check_session(df: pd.DataFrame) -> list[Issue]:
    local = _chicago(df)
    dow, hour = local.dt.dayofweek, local.dt.hour  # Monday=0 ... Sunday=6
    outside = (
        (dow == 5)                                          # Saturday
        | ((dow == 6) & (hour < SESSION_OPEN_HOUR))         # Sunday before open
        | ((dow == 4) & (hour >= SESSION_CLOSE_HOUR))       # Friday after close
        | ((hour >= SESSION_CLOSE_HOUR) & (hour < SESSION_OPEN_HOUR))  # daily maintenance break
    )
    return [Issue("WARN", "bars outside normal CME session", int(outside.sum()), _examples(df, outside))] if outside.any() else []


def trading_day(df: pd.DataFrame) -> pd.Series:
    """CME trading day: a session that opens 17:00 Chicago belongs to the next calendar date."""
    return (_chicago(df) + pd.Timedelta(hours=24 - SESSION_OPEN_HOUR)).dt.date


def check_gaps(df: pd.DataFrame) -> list[Issue]:
    """Report long silent stretches inside a session. Never fill them: no trades = no bar."""
    front = df[df["continuous_symbol"].str.endswith(".v.0")].copy()
    if front.empty:
        return []
    front["day"] = trading_day(front)
    gap = front.groupby("day")["ts_event_utc"].diff() > pd.Timedelta(minutes=GAP_WARN_MINUTES)
    return [Issue("WARN", f"front-month gaps > {GAP_WARN_MINUTES} min inside a session", int(gap.sum()),
                  _examples(front, gap))] if gap.any() else []


def check_missing_days(df: pd.DataFrame) -> list[Issue]:
    """Weekdays with no front-month bars at all. ~9 CME holidays per year are expected."""
    front = df[df["continuous_symbol"].str.endswith(".v.0")]
    if front.empty:
        return []
    have = set(trading_day(front))
    days = pd.bdate_range(min(have), max(have)).date
    missing = [d for d in days if d not in have]
    if not missing:
        return []
    years = max(1.0, len(days) / 252)
    return [Issue("WARN", f"weekdays with no data ({len(missing) / years:.1f}/year; ~9 holidays/year is normal)",
                  len(missing), [str(d) for d in missing[:5]])]


def roll_points(df: pd.DataFrame) -> pd.DataFrame:
    """Every time the continuous symbol switches to a different real contract."""
    rows = []
    for sym, g in df.sort_values("ts_event_utc").groupby("continuous_symbol"):
        prev = g.shift()
        changed = prev["instrument_id"].notna() & (
            g["instrument_id"].ne(prev["instrument_id"]) | g["raw_symbol"].ne(prev["raw_symbol"])
        )
        for idx in g.index[changed]:
            rows.append({
                "continuous_symbol": sym,
                "ts_event_utc": g.at[idx, "ts_event_utc"],
                "from": prev.at[idx, "raw_symbol"],
                "to": g.at[idx, "raw_symbol"],
                "jump_ticks": int(g.at[idx, "open_ticks"] - prev.at[idx, "close_ticks"]),
            })
    return pd.DataFrame(rows)


def run_all(df: pd.DataFrame) -> list[Issue]:
    issues = []
    for check in (check_duplicates, check_order, check_prices, check_contracts, check_session, check_gaps,
                  check_missing_days):
        issues += check(df)
    return issues


def main() -> int:
    if not BARS_DIR.exists():
        print(f"No data at {BARS_DIR}. Run: python -m propfirm_data.download --yes")
        return 1
    # Keep the order as stored on disk, so check_order can catch files that are out of order.
    df = pd.read_parquet(BARS_DIR).reset_index(drop=True)

    print(f"{len(df):,} bars, {df['ts_event_utc'].min()} -> {df['ts_event_utc'].max()}\n")
    print("Bars per year and symbol:")
    print(df.groupby([df["ts_event_utc"].dt.year, "continuous_symbol"]).size().unstack().to_string(), "\n")

    rolls = roll_points(df)
    front_rolls = rolls[rolls["continuous_symbol"].str.endswith(".v.0")] if not rolls.empty else rolls
    print(f"Front-month rolls: {len(front_rolls)} (about 12 per year expected)")
    if not front_rolls.empty:
        print(front_rolls.tail(5).to_string(index=False), "\n")

    issues = run_all(df)
    for i in issues:
        print(f"[{i.level}] {i.check}: {i.count:,}")
        for ex in i.examples:
            print(f"        e.g. {ex}")
    errors = [i for i in issues if i.level == "ERROR"]
    print("\nRESULT:", "FAIL - fix errors before backtesting" if errors else "PASS (review any warnings)")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
