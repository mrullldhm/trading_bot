"""Turn raw Databento DBN files into clean Parquet tables."""

from pathlib import Path

import databento as db
import pandas as pd

from .config import BARS_DIR, DEFINITIONS_FILE, FIXED_PER_TICK, RAW_DIR

PRICE_COLS = ["open", "high", "low", "close"]
BAR_COLUMNS = [
    "ts_event_utc", "continuous_symbol", "instrument_id", "raw_symbol",
    "open_ticks", "high_ticks", "low_ticks", "close_ticks",
    "open", "high", "low", "close", "volume",
]
DEFINITION_COLUMNS = ["ts_recv", "instrument_id", "raw_symbol", "expiration", "activation"]


class ConversionError(Exception):
    pass


def _to_utc(series: pd.Series) -> pd.Series:
    """Accept either datetimes (pretty_ts) or raw ns integers; UINT64_MAX means 'undefined'."""
    if pd.api.types.is_datetime64_any_dtype(series):
        return series.dt.tz_convert("UTC") if series.dt.tz is not None else series.dt.tz_localize("UTC")
    as_int = pd.to_numeric(series, errors="coerce")
    as_int = as_int.where(as_int < 2**63 - 1)
    return pd.to_datetime(as_int, unit="ns", utc=True)


def bars_from_df(df: pd.DataFrame) -> pd.DataFrame:
    """Normalise a to_df(price_type='fixed') OHLCV frame. Prices become integer ticks ($0.01)."""
    if df.empty:
        return pd.DataFrame(columns=[c for c in BAR_COLUMNS if c != "raw_symbol"])
    df = df.reset_index()
    if "symbol" not in df.columns:
        raise ConversionError("bars have no 'symbol' column; symbol mapping failed")

    out = pd.DataFrame({
        "ts_event_utc": _to_utc(df["ts_event"]),
        "continuous_symbol": df["symbol"].astype(str),
        "instrument_id": df["instrument_id"].astype("int64"),
        "volume": df["volume"].astype("int64"),
    })
    for col in PRICE_COLS:
        fixed = df[col].astype("int64")
        off_grid = fixed % FIXED_PER_TICK != 0
        if off_grid.any():
            raise ConversionError(f"{off_grid.sum()} '{col}' prices are not on the $0.01 tick grid")
        out[f"{col}_ticks"] = fixed // FIXED_PER_TICK
        out[col] = out[f"{col}_ticks"] / 100
    return out


def definitions_from_df(df: pd.DataFrame) -> pd.DataFrame:
    """Keep only outright futures (drop spreads) with the columns we need."""
    df = df.reset_index()
    is_future = df["instrument_class"].astype(str).str.upper().isin(["F", "FUTURE"])
    df = df[is_future]
    out = pd.DataFrame({
        "ts_recv": _to_utc(df["ts_recv"]),
        "instrument_id": df["instrument_id"].astype("int64"),
        "raw_symbol": df["raw_symbol"].astype(str),
        "expiration": _to_utc(df["expiration"]),
        "activation": _to_utc(df["activation"]),
    })
    return out.drop_duplicates(["instrument_id", "raw_symbol", "expiration"]).sort_values("ts_recv")


def attach_raw_symbol(bars: pd.DataFrame, definitions: pd.DataFrame) -> pd.DataFrame:
    """Add raw_symbol + expiration using the latest definition published at or before each bar.

    Joining by time (not instrument_id alone) protects against exchange IDs being reused.
    """
    defs = definitions[["ts_recv", "instrument_id", "raw_symbol", "expiration", "activation"]].sort_values("ts_recv")
    bars = bars.drop(columns=["raw_symbol", "expiration"], errors="ignore").sort_values("ts_event_utc")
    kwargs = dict(left_on="ts_event_utc", right_on="ts_recv", by="instrument_id")
    merged = pd.merge_asof(bars, defs, direction="backward", **kwargs)

    # A bar can arrive before that day's definition message; fall back to the next definition,
    # but only if the bar falls inside that contract's life (an ID may be reused later).
    missing = merged["raw_symbol"].isna()
    if missing.any():
        fwd = pd.merge_asof(bars[missing.values], defs, direction="forward", **kwargs)
        ts = fwd["ts_event_utc"]
        alive = (fwd["activation"].isna() | (fwd["activation"] <= ts)) & (fwd["expiration"].isna() | (ts < fwd["expiration"]))
        fwd.loc[~alive, ["raw_symbol", "expiration"]] = None
        merged.loc[missing, ["raw_symbol", "expiration"]] = fwd[["raw_symbol", "expiration"]].values
    return merged.drop(columns=["ts_recv", "activation"])


def _dbn_files(job_name: str) -> list[Path]:
    return sorted((RAW_DIR / job_name).rglob("*.dbn.zst"))


def load_definitions_from_raw() -> pd.DataFrame:
    frames = [definitions_from_df(db.DBNStore.from_file(f).to_df(pretty_ts=True, tz="UTC"))
              for f in _dbn_files("definitions")]
    if not frames:
        raise ConversionError("no definition files found; run the download first")
    return pd.concat(frames).drop_duplicates().sort_values("ts_recv")


def convert_all() -> dict[int, int]:
    """Convert every downloaded file. Returns rows written per year."""
    definitions = load_definitions_from_raw()
    DEFINITIONS_FILE.parent.mkdir(parents=True, exist_ok=True)
    definitions.to_parquet(DEFINITIONS_FILE, index=False)

    files = _dbn_files("bars")
    if not files:
        raise ConversionError("no bar files found; run the download first")

    # Monthly files, grouped by year so memory stays small (~1 year in RAM at a time).
    by_year: dict[int, list[Path]] = {}
    for f in files:
        by_year.setdefault(db.DBNStore.from_file(f).start.year, []).append(f)

    rows = {}
    for year, year_files in sorted(by_year.items()):
        bars = pd.concat(
            bars_from_df(db.DBNStore.from_file(f).to_df(price_type="fixed", pretty_ts=True, map_symbols=True, tz="UTC"))
            for f in year_files
        )
        bars = attach_raw_symbol(bars, definitions)
        bars = bars.sort_values(["continuous_symbol", "ts_event_utc"])[BAR_COLUMNS + ["expiration"]]
        path = BARS_DIR / f"year={year}" / "cl.parquet"
        path.parent.mkdir(parents=True, exist_ok=True)
        bars.to_parquet(path, index=False)
        rows[year] = len(bars)
    return rows


def load_bars() -> pd.DataFrame:
    """Read all processed bars (use this in backtests).

    WARNING: continuous prices jump when raw_symbol changes (contract roll). Never count that
    jump as P&L; see README_DATA.md "Roll days".
    """
    return pd.read_parquet(BARS_DIR)
