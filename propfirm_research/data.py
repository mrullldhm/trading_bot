"""The ONLY way research code reads market data. Enforces the period firewall (PROTOCOL §2, D001).

- discovery: free (every read is logged);
- validation / holdout: only with a live RunToken from `prereg.open_run(...)` for the same item and period, and
  only from files registered with the same sha256 in that pre-registration (R012 Q4.4), checked before any row
  is read;
- warm-up may reach back into earlier periods (the past), never forward;
- every attempt writes an `intent` ledger row and exactly one terminal row: `done` (with the hash of the files
  read), `failed` or `refused`.

Bars (`load`, `load_front`, `load_second`; one row per traded minute of one continuous series, time-sorted):
ts_event_utc, contract (raw_symbol@YYYY-MM), open/high/low/close (float ticks), volume,
trading_day (days since epoch), mod (ET minute of day), tmin (UTC minutes since epoch).

Stage-1 data (D010, converted by `propfirm_data.stage1_convert`; Codex R016 Q4):
- `load_trades("tas" | "cl_mbp1", ...)`: one row per trade; trading day from ts_event; `known_ns` = ts_recv in ns
  (before 2017 it is a copy of ts_event); a trade may feed a decision at time T only if known_ns < T (`known_before`);
- `load_statistics(...)`: every revision kept; `session_day` from ts_ref, `known_day` from ts_recv; a row is in a
  period only if both days are inside it (nothing published after the period end); `stats_asof` gives the latest
  revision received before a cutoff. CME sends ts_ref only for settlements: other rows (open interest, cleared
  volume, ...) have `ref_missing` and their session_day is the publication day, a label only (S004);
- `load_related(symbol, ...)`: RB.v.0 / HO.v.0 / BZ.v.0 1-minute bars in the bar frame layout; contract =
  instrument id; prices in the market's own ticks.
"""

import hashlib
from pathlib import Path

import numpy as np
import pandas as pd

from propfirm_backtest.bars import contract_key
from propfirm_data.config import BARS_DIR

from . import ledger, paths, prereg
from .periods import bounds, et_minute_of_day, trading_day

COLS = ["ts_event_utc", "continuous_symbol", "raw_symbol", "expiration",
        "open_ticks", "high_ticks", "low_ticks", "close_ticks", "volume"]
STAGE1_DIR = BARS_DIR.parent / "stage1"  # D010 data, written by propfirm_data.stage1_convert
TABLES = {"tas": "tas_trades", "cl_mbp1": "cl_mbp1_1420", "statistics": "statistics", "energy": "energy_ohlcv_1m"}
RELATED = ("RB.v.0", "HO.v.0", "BZ.v.0")
SIDE = {"B": 1, "A": -1}  # aggressor side; anything else (N) is 0 = unknown
NS_PER_MIN = 60_000_000_000
STAT_DELETE = 2  # databento StatUpdateAction.DELETE


def utc_minutes(ts: pd.Series):
    """UTC minutes since epoch (resolution-safe: pandas 3 may store microseconds, not nanoseconds)."""
    return ((pd.DatetimeIndex(ts).tz_convert("UTC") - pd.Timestamp("1970-01-01", tz="UTC"))
            // pd.Timedelta(minutes=1)).to_numpy("int64")


def utc_ns(ts: pd.Series) -> np.ndarray:
    return ((pd.DatetimeIndex(ts).tz_convert("UTC") - pd.Timestamp("1970-01-01", tz="UTC"))
            // pd.Timedelta(1, "ns")).to_numpy("int64")


class FirewallError(PermissionError):
    pass


# --- guards shared by every loader ----------------------------------------------------------------------

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


def file_key(path: Path) -> str:
    """How a data file is named in a pre-registration: relative to the repo root when it lives there."""
    try:
        return str(Path(path).resolve().relative_to(paths.ROOT))
    except ValueError:
        return str(Path(path).resolve())


def combine_digests(hashes: dict) -> str:
    h = hashlib.sha256()
    for k in sorted(hashes):
        h.update(f"{k}:{hashes[k]}\n".encode())
    return h.hexdigest()


def _verify(files: list, run) -> str:
    """One sha256 over the files to be read. For a protected period the list must not be empty and every file must
    be registered in the run's pre-registration with exactly this content, else nothing is read (R012 Q4.4)."""
    hashes = {file_key(f): ledger.sha256_file(f) for f in files}
    if run is not None:
        if not hashes:
            raise FirewallError("no data files to read for a protected period")
        registered = getattr(run, "data_files", None) or {}
        bad = sorted(k for k, h in hashes.items() if registered.get(k) != h)
        if bad:
            raise FirewallError(f"data files not registered in the pre-registration or changed since: {bad[:3]}")
    return combine_digests(hashes)


def _year(day: int) -> int:
    return int(pd.Timestamp(day, unit="D").year)


def year_range(period: str, warmup_days: int = 0) -> tuple[int, int | None]:
    """UTC-year partitions that can hold a period's rows. A trading day's events fall on its own UTC date or the
    evening before, so one year back covers 1 January; never a later year (that would read protected files)."""
    first, last = bounds(period)
    return _year(first - warmup_days) - 1, None if last is None else _year(last)


def files_for(table: str, period: str, warmup_days: int = 0) -> list:
    """The exact files a loader reads for `table` ("bars" or a stage-1 table) and period: register these in a
    pre-registration."""
    base = BARS_DIR if table == "bars" else STAGE1_DIR / TABLES[table]
    return _year_files(base, *year_range(period, warmup_days))


def digest(table: str, period: str, warmup_days: int = 0) -> str:
    """The data hash a loader would log for `table` and period, without reading any rows."""
    return _verify(files_for(table, period, warmup_days), None)


def frame_digest(df: pd.DataFrame) -> str:
    return hashlib.sha256(pd.util.hash_pandas_object(df, index=False).to_numpy().tobytes()).hexdigest()


def _ranges(df: pd.DataFrame) -> str:
    if df.empty:
        return "empty"
    parts = [f"days {int(df['trading_day'].min())}-{int(df['trading_day'].max())}"] if "trading_day" in df else []
    if "ts_event_utc" in df:
        parts.append(f"ts_event_utc {df['ts_event_utc'].min()}..{df['ts_event_utc'].max()}")
    for col in ("known_ns",):  # receive (known-at) range of trades and statistics
        if col in df:
            parts.append(f"{col} {int(df[col].min())}..{int(df[col].max())}")
    if "session_day" in df:
        parts.append(f"session_day {int(df['session_day'].min())}-{int(df['session_day'].max())}")
    return "; ".join(parts)


def _access(item_id: str, period: str, run, warmup_days: int, note: str, read):
    """intent row -> guards -> read(lo, last, first_year, last_year) -> done row; refused / failed rows otherwise.
    `read` returns (frame, data_sha256)."""
    claimed = run.prereg_sha256 if run is not None and prereg.is_live(run) else ""
    ledger.append(item_id, "access", period, n_tests=0, prereg_sha256=claimed, note=f"intent {note}")
    try:
        if warmup_days < 0:
            raise FirewallError("warmup_days must be >= 0 (warm-up reaches back, never forward)")
        sha = _check(period, item_id, run)
    except FirewallError as exc:
        ledger.append(item_id, "access", period, n_tests=0, note=f"refused ({exc}) {note}")
        raise
    first, last = bounds(period)
    lo = first - warmup_days
    first_year, last_year = year_range(period, warmup_days)
    try:
        out, data_sha = read(lo, last, first_year, last_year)
    except Exception as exc:
        status = "refused" if isinstance(exc, FirewallError) else "failed"  # e.g. a file hash not in the prereg
        ledger.append(item_id, "access", period, prereg_sha256=sha, n_tests=0,
                      note=f"{status} ({type(exc).__name__}: {exc}) {note}"[:500])
        raise
    out.attrs["data_sha256"] = data_sha  # callers record what they read (S004 facts, run manifests)
    ledger.append(item_id, "access", period, prereg_sha256=sha, n_tests=0, data_sha256=data_sha,
                  note=f"done rows={len(out)} frame={frame_digest(out)[:16]} {_ranges(out)}; {note}")
    return out


def _in_days(td: np.ndarray, lo: int, last: int | None) -> np.ndarray:
    keep = td >= lo
    if last is not None:
        keep &= td <= last
    return keep


# --- CL bars ---------------------------------------------------------------------------------------------

def _bar_files(first_year: int, last_year: int | None) -> list:
    return _year_files(BARS_DIR, first_year, last_year)


def _year_files(base: Path, first_year: int, last_year: int | None) -> list:
    out = []
    for d in sorted(Path(base).glob("year=*")):
        y = int(d.name.split("=", 1)[1])
        if y >= first_year and (last_year is None or y <= last_year):
            out += sorted(d.glob("*.parquet"))
    return out


def _read(symbol: str, files: list) -> pd.DataFrame:
    """Exactly the verified files, nothing else in their folders."""
    frames = [pd.read_parquet(f, columns=COLS, filters=[("continuous_symbol", "==", symbol)]) for f in files]
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(columns=COLS)


def load(symbol: str, period: str, item_id: str, purpose: str, run=None,
         warmup_days: int = 0) -> pd.DataFrame:
    def read(lo, last, first_year, last_year):
        files = _bar_files(first_year, last_year)
        data_sha = _verify(files, run)
        df = _read(symbol, files)
        df = df.sort_values("ts_event_utc").reset_index(drop=True)
        td = trading_day(df["ts_event_utc"])
        keep = _in_days(td, lo, last)
        df = df[keep].reset_index(drop=True)
        td = td[keep]
        return pd.DataFrame({
            "ts_event_utc": df["ts_event_utc"],
            "contract": contract_key(df).to_numpy(),
            "open": df["open_ticks"].to_numpy(float), "high": df["high_ticks"].to_numpy(float),
            "low": df["low_ticks"].to_numpy(float), "close": df["close_ticks"].to_numpy(float),
            "volume": df["volume"].to_numpy(float),
            "trading_day": td,
            "mod": et_minute_of_day(df["ts_event_utc"]),
            "tmin": utc_minutes(df["ts_event_utc"]),
        }), data_sha
    return _access(item_id, period, run, warmup_days, f"{symbol} warmup_days={warmup_days}: {purpose}", read)


def load_front(period, item_id, purpose, run=None, warmup_days=0) -> pd.DataFrame:
    return load("CL.v.0", period, item_id, purpose, run, warmup_days)


def load_second(period, item_id, purpose, run=None, warmup_days=0) -> pd.DataFrame:
    return load("CL.v.1", period, item_id, purpose, run, warmup_days)


# --- stage-1 tables ----------------------------------------------------------------------------------------

def _read_table(files: list) -> pd.DataFrame:
    if not files:
        return pd.DataFrame()
    return pd.concat([pd.read_parquet(f) for f in files], ignore_index=True)


def _stage1(table: str, period: str, item_id: str, purpose: str, run, warmup_days: int, shape):
    """Read one stage-1 table for a period. `shape(df, lo, last)` cuts by trading day and builds the frame."""
    def read(lo, last, first_year, last_year):
        files = _year_files(STAGE1_DIR / TABLES[table], first_year, last_year)
        if not files:
            raise FileNotFoundError(f"no {TABLES[table]} files under {STAGE1_DIR}: convert the stage-1 data first")
        data_sha = _verify(files, run)
        return shape(_read_table(files), lo, last), data_sha
    return _access(item_id, period, run, warmup_days, f"{table} warmup_days={warmup_days}: {purpose}", read)


def load_trades(source: str, period: str, item_id: str, purpose: str, run=None, warmup_days: int = 0) -> pd.DataFrame:
    """source "tas": every CLT trade (outrights and spreads; `diff_ticks` = price differential to the settlement).
    source "cl_mbp1": CL.v.0 trades 14:20-14:35 ET with the best bid / ask before the trade (`bid`, `ask`)."""
    if source not in ("tas", "cl_mbp1"):
        raise ValueError(f"unknown trade source {source!r}")

    def shape(df, lo, last):
        df = df.sort_values(["ts_event_utc", "sequence"], kind="stable").reset_index(drop=True)
        td = trading_day(df["ts_event_utc"])
        keep = _in_days(td, lo, last)
        df, td = df[keep].reset_index(drop=True), td[keep]
        event_ns, known_ns = utc_ns(df["ts_event_utc"]), utc_ns(df["ts_recv_utc"])
        if (known_ns < event_ns).any():
            raise ValueError("a trade is received before it happened (ts_recv < ts_event)")
        out = pd.DataFrame({
            "ts_event_utc": df["ts_event_utc"], "event_ns": event_ns, "known_ns": known_ns, "trading_day": td,
            "mod": et_minute_of_day(df["ts_event_utc"]), "instrument_id": df["instrument_id"].to_numpy("int64"),
            "raw_symbol": df["raw_symbol"].astype(str).to_numpy(), "size": df["size"].to_numpy("int64"),
            "side": df["side"].map(SIDE).fillna(0).astype("int8").to_numpy()})
        if source == "tas":
            out["is_spread"] = df["is_spread"].to_numpy(bool)
            out["diff_ticks"] = df["diff_ticks"].to_numpy("int64")
        else:
            out["contract"] = contract_key(df).to_numpy()
            out["price"] = df["price_ticks"].to_numpy(float)
            out["bid"] = df["bid_ticks"].to_numpy(float)
            out["ask"] = df["ask_ticks"].to_numpy(float)
        return out
    return _stage1("tas" if source == "tas" else "cl_mbp1", period, item_id, purpose, run, warmup_days, shape)


def load_statistics(period: str, item_id: str, purpose: str, run=None, warmup_days: int = 0) -> pd.DataFrame:
    """Every statistics revision of CL.v.0, CL.v.1 and CLT (settlement price, cleared volume, open interest, ...).
    A row belongs to the period only if its session (ts_ref) and its publication (ts_recv) are both inside it.
    `price` = Databento fixed price / 1e9: USD for CL, the TAS differential in ticks for CLT."""
    def shape(df, lo, last):
        df = df.sort_values(["ts_recv_utc", "sequence"], kind="stable").reset_index(drop=True)
        ref = df["ts_ref_utc"]
        session = trading_day(ref.fillna(df["ts_event_utc"]))
        known = trading_day(df["ts_recv_utc"])
        keep = _in_days(session, lo, last) & _in_days(known, lo, last)
        df, session, known = df[keep].reset_index(drop=True), session[keep], known[keep]
        return pd.DataFrame({
            "ts_event_utc": df["ts_event_utc"], "known_ns": utc_ns(df["ts_recv_utc"]),
            "ref_missing": df["ts_ref_utc"].isna().to_numpy(), "session_day": session, "known_day": known,
            "instrument_id": df["instrument_id"].to_numpy("int64"), "symbol": df["symbol"].astype(str).to_numpy(),
            "source": df["source"].astype(str).to_numpy(), "stat_type": df["stat_type"].to_numpy("int64"),
            "price": df["price_fixed"].astype("Float64").to_numpy(float, na_value=np.nan) / 1e9,
            "quantity": df["quantity"].astype("Float64").to_numpy(float, na_value=np.nan),
            "update_action": df["update_action"].to_numpy("int64"), "stat_flags": df["stat_flags"].to_numpy("int64"),
            "sequence": df["sequence"].to_numpy("int64")})
    return _stage1("statistics", period, item_id, purpose, run, warmup_days, shape)


def load_related(symbol: str, period: str, item_id: str, purpose: str, run=None, warmup_days: int = 0) -> pd.DataFrame:
    if symbol not in RELATED:
        raise ValueError(f"unknown related market {symbol!r}; one of {RELATED}")

    def shape(df, lo, last):
        df = df[df["continuous_symbol"] == symbol].sort_values("ts_event_utc").reset_index(drop=True)
        td = trading_day(df["ts_event_utc"])
        keep = _in_days(td, lo, last)
        df, td = df[keep].reset_index(drop=True), td[keep]
        return pd.DataFrame({
            "ts_event_utc": df["ts_event_utc"], "contract": df["instrument_id"].astype(str).to_numpy(),
            "open": df["open_ticks"].to_numpy(float), "high": df["high_ticks"].to_numpy(float),
            "low": df["low_ticks"].to_numpy(float), "close": df["close_ticks"].to_numpy(float),
            "volume": df["volume"].to_numpy(float), "trading_day": td,
            "mod": et_minute_of_day(df["ts_event_utc"]), "tmin": utc_minutes(df["ts_event_utc"])})
    return _stage1("energy", period, item_id, f"{symbol} {purpose}", run, warmup_days, shape)


# --- causal helpers ------------------------------------------------------------------------------------------

def known_before(df: pd.DataFrame, cutoff_ns) -> np.ndarray:
    """Rows a decision at `cutoff_ns` (UTC ns; scalar or per row) may use: received strictly before it."""
    return df["known_ns"].to_numpy() < np.asarray(cutoff_ns)


def stats_asof(stats: pd.DataFrame, cutoff_ns: int) -> pd.DataFrame:
    """Latest revision of each (instrument, stat type, session) received strictly before `cutoff_ns`; a revision
    whose update action is DELETE removes the value. Never the eventual final row (R016 Q4)."""
    known = stats[stats["known_ns"] < cutoff_ns]
    last = known.sort_values(["known_ns", "sequence"], kind="stable").groupby(
        ["instrument_id", "stat_type", "session_day"], sort=False).tail(1)
    return last[last["update_action"] != STAT_DELETE].reset_index(drop=True)


