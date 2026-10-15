"""EIA Weekly Petroleum Status Report release times, 2010 -> today.

Usage:
    python -m propfirm_data.eia_calendar        # writes data/reference/eia_releases.csv

EIA keeps no machine-readable archive of past release times, so the slots to block are built from
the published rule ONLY (no market data, so a backtest never uses information it could not have had):
- Normal week: Wednesday 10:30 ET.
- A federal holiday Monday-Wednesday shifts the release (usually Thursday 11:00 ET; Christmas /
  New Year mid-week: Friday; since 2025 often Thursday 12:00 ET). In those weeks EVERY candidate
  slot from the holiday onwards is blocked, so whichever was used is covered.

Volume is used only to CHECK the calendar afterwards: the release minute shows a CL volume spike
(median ~9x the 20 minutes before it, other days ~1.2x). Each blocked slot gets a status
(confirmed = spiked) and the run reports weeks whose biggest candidate spike was NOT blocked
(possible special schedules, or unrelated news).
"""

import sys

import numpy as np
import pandas as pd
from pandas.tseries.holiday import USFederalHolidayCalendar

from .config import BARS_DIR, DATA_DIR

ET = "America/New_York"
OUT_FILE = DATA_DIR / "reference" / "eia_releases.csv"
CONFIRM_RATIO = 3.0  # spike vs median of the 20 minutes before
DETECT_RATIO = 5.0  # "clear spike" for the unblocked-spike check
BASE_MINUTES = 20
MIN_BASE_MINUTES = 15  # baseline needs most of its minutes, or the ratio is meaningless
# (weekday, ET minute of day): Tue..Fri at 10:30 / 11:00 / 12:00
CANDIDATES = [(d, t) for d in (1, 2, 3, 4) for t in (10 * 60 + 30, 11 * 60, 12 * 60)]
WED_1030, THU_1100, FRI_1100 = (2, 630), (3, 660), (4, 660)


def rule_slot(week_start: pd.Timestamp, holidays: set) -> tuple[int, int]:
    """Scheduled slot for the week starting Sunday `week_start`."""
    mon_to_wed = [week_start + pd.Timedelta(days=k) for k in (1, 2, 3)]
    hit = [d for d in mon_to_wed if d in holidays]
    if not hit:
        return WED_1030
    if any(d.month == 12 and d.day == 25 or d.month == 1 and d.day == 1 for d in hit if d.dayofweek >= 1):
        return FRI_1100
    return THU_1100


def spike_scores(et_date: np.ndarray, mod: np.ndarray, volume: np.ndarray) -> pd.DataFrame:
    """Volume at each candidate minute / median volume of the BASE_MINUTES before it.
    Rows: ET dates. Columns: ET minute of day. Missing minute -> NaN."""
    df = pd.DataFrame({"date": et_date, "mod": mod, "volume": volume})
    times = sorted({t for _, t in CANDIDATES})
    lo = min(times) - BASE_MINUTES
    df = df[(df["mod"] >= lo) & (df["mod"] <= max(times))]
    v = df.pivot_table(index="date", columns="mod", values="volume", aggfunc="sum")
    out = {}
    for t in times:
        win = v.reindex(columns=range(t - BASE_MINUTES, t))
        base = win.median(axis=1).where(win.notna().sum(axis=1) >= MIN_BASE_MINUTES)
        at = v[t] if t in v.columns else pd.Series(np.nan, index=v.index)
        out[t] = at / base.where(base > 0)
    res = pd.DataFrame(out)
    res.index = pd.to_datetime(res.index)
    return res


def build(scores: pd.DataFrame, start, end) -> tuple[pd.DataFrame, pd.DataFrame]:
    """(slots to block: date, time_et, status, spike; weeks with an unblocked clear spike)."""
    holidays = set(USFederalHolidayCalendar().holidays(start, end))
    first = pd.Timestamp(start)
    weeks = pd.date_range(first - pd.Timedelta(days=(first.dayofweek + 1) % 7), end, freq="7D")
    rows, misses = [], []

    def score(day, t):
        return scores.at[day, t] if day in scores.index and t in scores.columns else np.nan

    for ws in weeks:
        rule = rule_slot(ws, holidays)
        if rule == WED_1030:
            slots = [WED_1030]
        else:  # holiday week: block every candidate from the day after the first holiday
            hol = min(d for d in (ws + pd.Timedelta(days=k) for k in (1, 2, 3)) if d in holidays)
            slots = [(d, t) for d, t in CANDIDATES if ws + pd.Timedelta(days=d + 1) > hol]
        week_rows = []
        for d, t in slots:
            day = ws + pd.Timedelta(days=d + 1)
            if day in holidays or not (first <= day < pd.Timestamp(end)):
                continue
            sc = score(day, t)
            week_rows.append((day, t, "confirmed" if sc >= CONFIRM_RATIO else "unconfirmed", sc))
        rows += week_rows
        cand = [(ws + pd.Timedelta(days=d + 1), t) for d, t in CANDIDATES]
        cand = [(day, t, score(day, t)) for day, t in cand if first <= day < pd.Timestamp(end)]
        cand = [c for c in cand if not np.isnan(c[2])]
        if cand and week_rows:
            best = max(cand, key=lambda c: c[2])
            if best[2] >= DETECT_RATIO and (best[0], best[1]) not in {(r[0], r[1]) for r in week_rows}:
                misses.append((best[0].date(), f"{best[1] // 60:02d}:{best[1] % 60:02d}", best[2]))
    out = pd.DataFrame(rows, columns=["date", "minute_et", "status", "spike"])
    out = out.sort_values(["date", "minute_et"]).drop_duplicates(["date", "minute_et"])
    out["time_et"] = out["minute_et"].map(lambda m: f"{m // 60:02d}:{m % 60:02d}")
    out["date"] = out["date"].dt.date
    return (out[["date", "time_et", "status", "spike"]].reset_index(drop=True),
            pd.DataFrame(misses, columns=["date", "time_et", "spike"]))


def load_releases(path=OUT_FILE) -> pd.DataFrame:
    """Slots to block. Raises if the file is missing: no calendar = no trading."""
    if not path.exists():
        raise FileNotFoundError(f"{path} missing. Run: python -m propfirm_data.eia_calendar")
    df = pd.read_csv(path, parse_dates=["date"])
    hm = df["time_et"].str.split(":", expand=True).astype(int)
    df["minute_et"] = hm[0] * 60 + hm[1]
    return df


def main() -> int:
    print("Loading front-month volume...", flush=True)
    df = pd.read_parquet(BARS_DIR, columns=["ts_event_utc", "volume"], filters=[("continuous_symbol", "==", "CL.v.0")])
    et = df["ts_event_utc"].dt.tz_convert(ET)
    scores = spike_scores(et.dt.date.to_numpy(), (et.dt.hour * 60 + et.dt.minute).to_numpy(),
                          df["volume"].to_numpy())
    start = et.min().tz_localize(None).normalize()
    end = et.max().tz_localize(None).normalize() + pd.Timedelta(days=1)
    out, misses = build(scores, start, end)
    OUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(OUT_FILE, index=False)
    misses.to_csv(OUT_FILE.with_name("eia_unblocked_spikes.csv"), index=False)
    wk = pd.to_datetime(out["date"]).dt.to_period("W-SAT")
    confirmed = out.groupby(wk)["status"].apply(lambda s: (s == "confirmed").any())
    print(f"{len(confirmed):,} weeks, {int(confirmed.sum()):,} with a confirmed spike in a blocked slot")
    by_year = misses.groupby(pd.to_datetime(misses["date"]).dt.year).size() if len(misses) else pd.Series(dtype=int)
    print(f"Weeks whose biggest spike (>= {DETECT_RATIO}x) was NOT blocked: {len(misses)} "
          f"(by year: {by_year.to_dict()})")
    print(f"Wrote {OUT_FILE} ({len(out):,} slots to block)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
