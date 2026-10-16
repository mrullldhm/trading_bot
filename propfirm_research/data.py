"""The ONLY way research code reads bar data. Enforces the period firewall (PROTOCOL §2, D001).

- discovery: free (every read is logged);
- validation / holdout: only with a live RunToken from `prereg.open_run(...)` for the same item and period;
- warm-up may reach back into earlier periods (the past), never forward.

Returned frame (one row per traded minute of one continuous series, time-sorted):
ts_event_utc, contract (raw_symbol@YYYY-MM), open/high/low/close (float ticks), volume,
trading_day (days since epoch), mod (ET minute of day), tmin (UTC minutes since epoch).
"""

import pandas as pd

from propfirm_backtest.bars import contract_key
from propfirm_data.config import BARS_DIR

from . import ledger, prereg
from .periods import bounds, et_minute_of_day, trading_day

COLS = ["ts_event_utc", "continuous_symbol", "raw_symbol", "expiration",
        "open_ticks", "high_ticks", "low_ticks", "close_ticks", "volume"]


def utc_minutes(ts: pd.Series):
    """UTC minutes since epoch (resolution-safe: pandas 3 may store microseconds, not nanoseconds)."""
    return ((pd.DatetimeIndex(ts).tz_convert("UTC") - pd.Timestamp("1970-01-01", tz="UTC"))
            // pd.Timedelta(minutes=1)).to_numpy("int64")


class FirewallError(PermissionError):
    pass


def _read(symbol: str, first_year: int, last_year: int | None) -> pd.DataFrame:
    filters = [("continuous_symbol", "==", symbol), ("year", ">=", first_year)]
    if last_year is not None:
        filters.append(("year", "<=", last_year))
    return pd.read_parquet(BARS_DIR, columns=COLS, filters=filters)


def _check(period: str, item_id: str, run) -> str:
    if period == "discovery":
        return ""
    if period not in ("validation", "holdout"):
        raise FirewallError(f"unknown period {period!r}")
    if run is None or not prereg.is_live(run):
        raise FirewallError(f"{period} data needs a live run token from prereg.open_run (PROTOCOL §5)")
    if run.period != period or run.item_id != item_id:
        raise FirewallError(f"run token is for {run.item_id}/{run.period}, not {item_id}/{period}")
    return run.prereg_sha256


def load(symbol: str, period: str, item_id: str, purpose: str, run=None,
         warmup_days: int = 0) -> pd.DataFrame:
    if warmup_days < 0:
        raise FirewallError("warmup_days must be >= 0 (warm-up reaches back, never forward)")
    sha = _check(period, item_id, run)
    note = f"{symbol} warmup_days={warmup_days}: {purpose}"
    ledger.append(item_id, "access", period, prereg_sha256=sha, n_tests=0, note=f"intent {note}")
    first, last = bounds(period)
    lo = first - warmup_days
    first_year = int(pd.Timestamp(lo, unit="D").year) - 1
    last_year = None if last is None else int(pd.Timestamp(last, unit="D").year) + 1
    df = _read(symbol, first_year, last_year)
    df = df.sort_values("ts_event_utc").reset_index(drop=True)
    td = trading_day(df["ts_event_utc"])
    keep = td >= lo
    if last is not None:
        keep &= td <= last
    df = df[keep].reset_index(drop=True)
    td = td[keep]
    out = pd.DataFrame({
        "ts_event_utc": df["ts_event_utc"],
        "contract": contract_key(df).to_numpy(),
        "open": df["open_ticks"].to_numpy(float), "high": df["high_ticks"].to_numpy(float),
        "low": df["low_ticks"].to_numpy(float), "close": df["close_ticks"].to_numpy(float),
        "volume": df["volume"].to_numpy(float),
        "trading_day": td,
        "mod": et_minute_of_day(df["ts_event_utc"]),
        "tmin": utc_minutes(df["ts_event_utc"]),
    })
    ledger.append(item_id, "access", period, prereg_sha256=sha, n_tests=0, note=f"done rows={len(out)} {note}")
    return out


def load_front(period, item_id, purpose, run=None, warmup_days=0) -> pd.DataFrame:
    return load("CL.v.0", period, item_id, purpose, run, warmup_days)


def load_second(period, item_id, purpose, run=None, warmup_days=0) -> pd.DataFrame:
    return load("CL.v.1", period, item_id, purpose, run, warmup_days)
