"""Per-contract 1-minute arrays and session-bounded higher-timeframe bars.

Layout: one long array of 1-minute bars, sorted by (contract, time). Each contract keeps a
warm-up tail of its CL.v.1 history so slow indicators are ready when it becomes front month.
Only minutes where the contract is CL.v.0 are tradable.
"""

from dataclasses import dataclass

import numpy as np
import pandas as pd

from propfirm_data.config import BARS_DIR

ET = "America/New_York"
DAY_START_MIN = 18 * 60  # CME trading day starts 18:00 ET
CUTOFF_BUFFER_MIN = 5  # be flat 5 minutes before a session end or a roll
WARMUP_DAYS = 30  # CL.v.1 history kept per contract for indicator warm-up

# (start, end) as ET minutes-of-day, half-open [start, end). start > end means it wraps midnight.
SESSIONS = {
    "asian": (19 * 60, 3 * 60),
    "london": (3 * 60, 8 * 60),
    "newyork": (8 * 60, 16 * 60 + 5),
    "all": (18 * 60, 16 * 60 + 5),
}
SPLIT_MIN = 16 * 60 + 5  # session cutoff not on a timeframe boundary: bars are split here
TIMEFRAMES = [1, 2, 3, 5, 10, 15, 30, 60]


@dataclass
class Minutes:
    ts: np.ndarray  # int64 ns UTC
    contract: np.ndarray  # int32, ordered by front-month start
    open: np.ndarray  # float64 ticks
    high: np.ndarray
    low: np.ndarray
    close: np.ndarray
    volume: np.ndarray  # float64
    front: np.ndarray  # bool: contract is CL.v.0 at this minute
    et_day: np.ndarray  # int32 days since 1970-01-01 of the ET calendar date
    mod: np.ndarray  # int32 ET minute of day
    roll_cutoff: np.ndarray  # bool: within CUTOFF_BUFFER_MIN of this contract's scheduled roll
    contracts: list  # contract index -> raw_symbol

    @property
    def trading_day(self) -> np.ndarray:
        """CME trading day: a session opening 18:00 ET belongs to the next date."""
        return self.et_day + (self.mod >= DAY_START_MIN)

    def __len__(self) -> int:
        return len(self.ts)


def load_minutes(start=None, end=None) -> Minutes:
    cols = ["ts_event_utc", "continuous_symbol", "raw_symbol", "expiration",
            "open_ticks", "high_ticks", "low_ticks", "close_ticks", "volume"]
    filters = []
    if start is not None:
        filters.append(("year", ">=", pd.Timestamp(start).year - 1))
    if end is not None:
        filters.append(("year", "<=", pd.Timestamp(end).year))
    df = pd.read_parquet(BARS_DIR, columns=cols, filters=filters or None)
    df = df.drop(columns="year", errors="ignore")
    if start is not None:
        df = df[df["ts_event_utc"] >= pd.Timestamp(start, tz="UTC") - pd.Timedelta(days=WARMUP_DAYS)]
    if end is not None:
        df = df[df["ts_event_utc"] < pd.Timestamp(end, tz="UTC")]
    return build_minutes(df)


def contract_key(df: pd.DataFrame) -> pd.Series:
    """Unique contract id. CME symbols use a ONE-digit year, so "CLQ0" is both Aug 2010 and
    Aug 2020: the name alone is not unique. Name + expiry month is."""
    if "expiration" in df.columns and df["expiration"].notna().all():
        return df["raw_symbol"] + "@" + df["expiration"].dt.strftime("%Y-%m")
    if "expiration" in df.columns:
        raise ValueError("missing contract expiration: cannot tell CLQ0 (2010) from CLQ0 (2020)")
    return df["raw_symbol"]  # test data without expiries


def build_minutes(df: pd.DataFrame) -> Minutes:
    df = df.copy()
    df["raw_symbol"] = contract_key(df)
    df["is_front"] = df["continuous_symbol"] == "CL.v.0"
    front = df[df["is_front"]]
    order = front.groupby("raw_symbol")["ts_event_utc"].min().sort_values()
    # Scheduled roll = when the NEXT contract becomes front (Databento switches on hour boundaries).
    roll_at = order.shift(-1).dt.floor("h")
    first_front = order

    df = df[df["raw_symbol"].isin(order.index)]
    df = df.merge(first_front.rename("first_front"), left_on="raw_symbol", right_index=True)
    df = df[df["ts_event_utc"] >= df["first_front"] - pd.Timedelta(days=WARMUP_DAYS)]
    # same contract can appear as v.0 and v.1 at the same minute: keep one row, front wins
    df = (df.sort_values(["raw_symbol", "ts_event_utc", "is_front"], ascending=[True, True, False])
            .drop_duplicates(["raw_symbol", "ts_event_utc"]))

    contract_idx = {sym: i for i, sym in enumerate(order.index)}
    df["contract"] = df["raw_symbol"].map(contract_idx).astype("int32")
    df = df.sort_values(["contract", "ts_event_utc"]).reset_index(drop=True)

    et = df["ts_event_utc"].dt.tz_convert(ET)
    et_day = ((et.dt.tz_localize(None).dt.normalize() - pd.Timestamp("1970-01-01")) // pd.Timedelta(days=1))
    ra = df["raw_symbol"].map(roll_at)
    roll_cutoff = ra.notna() & (df["ts_event_utc"] >= ra - pd.Timedelta(minutes=CUTOFF_BUFFER_MIN))

    return Minutes(
        ts=df["ts_event_utc"].astype("int64").to_numpy(),
        contract=df["contract"].to_numpy(),
        open=df["open_ticks"].to_numpy(np.float64),
        high=df["high_ticks"].to_numpy(np.float64),
        low=df["low_ticks"].to_numpy(np.float64),
        close=df["close_ticks"].to_numpy(np.float64),
        volume=df["volume"].to_numpy(np.float64),
        front=df["is_front"].to_numpy(),
        et_day=et_day.to_numpy(np.int32),
        mod=(et.dt.hour * 60 + et.dt.minute).to_numpy(np.int32),
        roll_cutoff=roll_cutoff.to_numpy(),
        contracts=list(order.index),
    )


def session_mask(m: Minutes, session: str) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Return (in_session, instance_id, cutoff) per minute for one session.

    instance_id: one id per session occurrence (e.g. one Asian night).
    cutoff: minute is inside the last CUTOFF_BUFFER_MIN of the session or before a roll.
    """
    start, end = SESSIONS[session]
    mod = m.mod
    if start < end:
        inside = (mod >= start) & (mod < end)
        instance = m.et_day.astype(np.int64)
    else:
        inside = (mod >= start) | (mod < end)
        instance = m.et_day.astype(np.int64) + (mod >= start)
    cutoff = ((mod >= end - CUTOFF_BUFFER_MIN) & (mod < end)) | m.roll_cutoff
    return inside, instance, cutoff


def segments(m: Minutes, session: str) -> tuple[np.ndarray, np.ndarray]:
    """Segment id per minute (-1 = not tradable): a run of the same contract, front month,
    inside one session occurrence. A position can never live across two segments."""
    inside, instance, cutoff = session_mask(m, session)
    ok = inside & m.front
    seg = np.full(len(m), -1, dtype=np.int64)
    # a segment starts at a tradable minute whose previous row is not tradable,
    # belongs to another contract, or to another session occurrence
    new = ok.copy()
    new[1:] &= ~ok[:-1] | (m.contract[1:] != m.contract[:-1]) | (instance[1:] != instance[:-1])
    ids = np.cumsum(new) - 1
    seg[ok] = ids[ok]
    return seg, cutoff


@dataclass
class Bars:
    tf: int
    start: np.ndarray  # first minute index (inclusive)
    end: np.ndarray  # last minute index (exclusive)
    open: np.ndarray
    high: np.ndarray
    low: np.ndarray
    close: np.ndarray
    contract: np.ndarray

    def __len__(self) -> int:
        return len(self.start)


def build_bars(m: Minutes, tf: int) -> Bars:
    """Clock-aligned ET buckets of `tf` minutes, never spanning a contract, an ET date,
    the 16:05 cutoff, or a change in front-month status."""
    if 1440 % tf:
        raise ValueError("timeframe must divide a day")
    bucket = m.mod // tf
    after_split = m.mod >= SPLIT_MIN
    n = len(m)
    new = np.ones(n, dtype=bool)
    new[1:] = ((m.contract[1:] != m.contract[:-1]) | (m.et_day[1:] != m.et_day[:-1])
               | (bucket[1:] != bucket[:-1]) | (after_split[1:] != after_split[:-1])
               | (m.front[1:] != m.front[:-1]) | (m.roll_cutoff[1:] != m.roll_cutoff[:-1]))
    start = np.flatnonzero(new)
    end = np.append(start[1:], n)
    return Bars(
        tf=tf, start=start, end=end,
        open=m.open[start],
        high=np.maximum.reduceat(m.high, start),
        low=np.minimum.reduceat(m.low, start),
        close=m.close[end - 1],
        contract=m.contract[start],
    )
