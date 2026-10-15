"""Opening Range Breakout (ORB) simulator (numba), one trading day at a time.

Works on front-month minutes only (CL.v.0), in "minutes since epoch" (UTC).

Per trading day and (anchor, range length):
  range = high/low of the clock window [start, start+L). Valid only if >= 80% of its minutes traded
  (thin-hour minutes without trades are normal), all on one contract, outside the roll cutoff.
  Entries start at the first minute >= range end, which must be the same contract.

Rules (all prices in ticks, $10 each):
- Long level = range high + 1 + buffer; short level = range low - 1 - buffer.
- Each side breaks out at most once a day ("first breakout"): if the first breakout of a side
  happens when an entry is not allowed (EIA block, roll cutoff), that side is done for the day.
- Triggers: STOP = resting stop order (fills at level + slip, or at open + slip if price gapped
  through); CLOSE1 / CLOSE5 = a 1-min / 5-min bar (5-min buckets anchored to the range end)
  closes beyond the level, filled at the next minute's open + slip.
- Stop: MID (range midpoint, rounded away from entry), OPPOSITE (1 tick beyond the other edge),
  FIXED (n ticks from the fill). R = fill - initial stop, so buffer and gaps are included.
- Target: fill +/- ceil(target_r * R). A limit order: needs a trade 1 tick THROUGH it, fills at
  the target exactly (no improvement on gaps). target_r = 0: no target.
- Breakeven: once price reaches fill + 1R, the stop moves to the fill price from the NEXT minute.
- Protective stop: fills at stop - slip, or open - slip if price gapped through.
- Exit at the open of the first minute >= flat time, or in the roll cutoff (minus slip). Session
  flat = 16:09 ET, 12:55 ET on scheduled short days (CME holiday calendar).
- Ambiguity inside one 1-min candle is resolved pessimistically (pessimistic=True):
  STOP entry + stop touched in the entry minute = stopped; no target in the STOP entry minute
  (a CLOSE entry fills at the minute's open, so the rest of that minute is genuinely after it);
  stop and target in the same minute = stop; both sides touched in one minute = the side
  nearer the open filled first. No same-minute reversal (2nd trade starts the minute after).
  pessimistic=False: the entry minute ignores the stop, and stop+target in one minute = target.
- Direction policy: BOTH1 (first breakout, 1 trade), BOTH2 (a 2nd trade on the opposite side,
  only after a stop-out, before the entry deadline), LONG, SHORT.
- Every trade enters and exits on the same contract inside one trading day.
"""

import numpy as np
import pandas as pd
from numba import njit, prange
from pandas.tseries.holiday import (AbstractHolidayCalendar, GoodFriday, Holiday, USLaborDay,
                                    USMartinLutherKingJr, USMemorialDay, USPresidentsDay,
                                    USThanksgivingDay, nearest_workday,
                                    sunday_to_monday)

from propfirm_data.config import DEFINITIONS_FILE

from . import propsim as P

ET = "America/New_York"
LONDON = "Europe/London"
NS_PER_MIN = 60_000_000_000
MIN_SANE_TMIN, MAX_SANE_TMIN = 10_000_000, 100_000_000  # minutes since epoch: years 1989 .. 2160
SESSION_FLAT_MOD = 16 * 60 + 9  # exit at the 16:09 ET open: Topstep closes everything at 3:10 PM CT = 16:10 ET
SHORT_DAY_FLAT_MOD = 12 * 60 + 55  # CME holiday halts: 13:00 ET (2014-21), 13:15 / 13:45 / 14:30 other years
CLOSE_BUFFER = 5  # flat 5 minutes before a contract expires
EIA_BLOCK = 15  # no entries from 15 min before to 15 min after a release
MAX_BLOCKS = 4
WIDTH_LOOKBACK = 20
MIN_COVERAGE = 0.8  # share of range minutes that must have traded

# anchor name -> (timezone, minute of day, days before the trading day)
ANCHORS = {
    "london0800": (LONDON, 8 * 60, 0),
    "et0830": (ET, 8 * 60 + 30, 0),
    "et0900": (ET, 9 * 60, 0),
    "et1800": (ET, 18 * 60, 1),
}
RANGE_LENGTHS = [5, 10, 15, 30, 60]
TABLE_KEYS = [(a, L) for a in ANCHORS for L in RANGE_LENGTHS]  # row order of DayTables

STOP, CLOSE1, CLOSE5 = 0, 1, 2
MID, OPPOSITE, FIXED = 0, 1, 2
BOTH1, BOTH2, LONG, SHORT = 0, 1, 2, 3
W_NONE, W_SKIP_WIDE, W_SKIP_NARROW, W_MID = 0, 1, 2, 3
WIDE, NARROW = 1.5, 0.5
SESSION = -1  # flat_offset value: flat at the session end

EXIT_TARGET, EXIT_STOP, EXIT_TIME, EXIT_CUTOFF, EXIT_FALLBACK = 1, 2, 3, 4, 5
EXIT_NAMES = {EXIT_TARGET: "target", EXIT_STOP: "stop", EXIT_TIME: "time", EXIT_CUTOFF: "cutoff",
              EXIT_FALLBACK: "fallback"}

# config columns (int64 matrix): one row per config
C_TABLE, C_TRIGGER, C_BUFFER, C_STOP_TYPE, C_STOP_TICKS, C_TARGET_X10, C_WINDOW, C_FLAT, C_DIRPOL, \
    C_WIDTH, C_BE = range(11)
N_CFG_COLS = 11


# --- data preparation -----------------------------------------------------------------------

class Front:
    """Front-month minutes as flat arrays (time-sorted, one row per traded minute)."""

    def __init__(self, m, strict_expiry=False):
        idx = np.flatnonzero(m.front)
        self.src = idx  # row in Minutes
        self.tmin = m.ts[idx] // NS_PER_MIN
        if len(self.tmin) and not (MIN_SANE_TMIN < self.tmin[0] and self.tmin[-1] < MAX_SANE_TMIN):
            raise ValueError("Minutes.ts must be int64 nanoseconds since epoch (UTC)")
        if len(self.tmin) > 1 and not (np.diff(self.tmin) > 0).all():
            raise ValueError("front-month minutes are not strictly increasing")
        self.open, self.high, self.low, self.close = m.open[idx], m.high[idx], m.low[idx], m.close[idx]
        self.volume = m.volume[idx]
        self.contract = m.contract[idx]
        self.cut = m.roll_cutoff[idx]
        self.trading_day = m.trading_day[idx]
        self.mod = m.mod[idx]
        self.et_day = m.et_day[idx]
        self.expiry = contract_expiry(m.contracts)  # per contract index, UTC minutes (-1 = unknown)
        unknown = [m.contracts[k] for k in np.unique(self.contract) if self.expiry[k] < 0]
        if strict_expiry and unknown and any("@" in c for c in m.contracts):  # "@" = real data with expiries
            raise ValueError(f"no expiry for front contracts {unknown[:5]} (+{max(0, len(unknown) - 5)} more)")

    def __len__(self):
        return len(self.tmin)


def contract_expiry(contracts: list) -> np.ndarray:
    """Last trading minute of each contract (from the exchange definitions; known in advance).
    Contract keys are "RAWSYMBOL@YYYY-MM" (expiry month); unknown keys get -1."""
    out = np.full(len(contracts), -1, dtype=np.int64)
    if not any("@" in c for c in contracts):
        return out  # test data without expiries
    if not DEFINITIONS_FILE.exists():
        raise FileNotFoundError(f"{DEFINITIONS_FILE} missing: expiry days cannot be flattened")
    d = pd.read_parquet(DEFINITIONS_FILE, columns=["raw_symbol", "expiration"]).dropna()
    key = d["raw_symbol"] + "@" + d["expiration"].dt.strftime("%Y-%m")
    exp = dict(zip(key, (d["expiration"].dt.tz_convert("UTC").dt.tz_localize(None)
                         .to_numpy("datetime64[ns]").astype(np.int64) // NS_PER_MIN)))
    for k, c in enumerate(contracts):
        out[k] = exp.get(c, -1)
    return out


def local_tmin(days: np.ndarray, minute: int, tz: str, days_before: int = 0) -> np.ndarray:
    """Wall-clock `minute` in `tz` on date (day - days_before) -> UTC minutes since epoch."""
    d = pd.to_datetime(np.asarray(days, dtype=np.int64) - days_before, unit="D") + pd.Timedelta(minutes=minute)
    utc = pd.DatetimeIndex(d).tz_localize(tz).tz_convert("UTC").tz_localize(None)
    return (utc.to_numpy("datetime64[ns]").astype(np.int64)) // NS_PER_MIN


class DayTables:
    """Per (anchor, range length) x trading day: range, entry start row, filters, session end.
    Also the range's first open, last close and volume (used by the ORB families)."""

    def __init__(self, f: Front, days: np.ndarray, eia: pd.DataFrame | None, keys=None):
        self.keys = TABLE_KEYS if keys is None else keys
        n_t, n_d = len(self.keys), len(days)
        self.valid = np.zeros((n_t, n_d), dtype=np.bool_)
        self.hi = np.zeros((n_t, n_d))
        self.lo = np.zeros((n_t, n_d))
        self.e_idx = np.zeros((n_t, n_d), dtype=np.int64)
        self.rend = np.zeros((n_t, n_d), dtype=np.int64)
        self.ratio = np.full((n_t, n_d), np.nan)
        self.ropen = np.zeros((n_t, n_d))
        self.rclose = np.zeros((n_t, n_d))
        self.rvol = np.zeros((n_t, n_d))
        self.sess_end = session_end(f, days)
        self.blocks = eia_blocks(eia, days)
        cut_cum = np.concatenate([[0], np.cumsum(f.cut)])
        n = len(f)
        for t, (anchor, L) in enumerate(self.keys):
            tz, minute, before = ANCHORS[anchor]
            start = local_tmin(days, minute, tz, before)
            self.rend[t] = start + L
            i = np.searchsorted(f.tmin, start)  # first row of the range
            j = np.searchsorted(f.tmin, start + L)  # first row after it (entries start here)
            ok = (j < n) & (j - i >= min_minutes(L)) & (self.sess_end > start + L)
            ii, ll = np.where(ok, i, 0), np.where(ok, j - 1, 0)
            ok &= f.contract[ii] == f.contract[ll]
            ok &= f.contract[np.where(ok, j, 0)] == f.contract[ii]
            ok &= (cut_cum[ll + 1] - cut_cum[ii]) == 0
            if ok.any():
                bounds = np.column_stack([i[ok], j[ok]]).ravel()  # windows are disjoint and sorted
                self.hi[t, ok] = np.maximum.reduceat(f.high, bounds)[::2]
                self.lo[t, ok] = np.minimum.reduceat(f.low, bounds)[::2]
                self.rvol[t, ok] = np.add.reduceat(f.volume, bounds)[::2]
                self.ropen[t, ok] = f.open[i[ok]]
                self.rclose[t, ok] = f.close[j[ok] - 1]
            self.valid[t] = ok
            self.e_idx[t] = np.where(ok, j, 0)
            self.ratio[t] = width_ratio(self.hi[t] - self.lo[t], ok)


def min_minutes(L: int) -> int:
    """Minutes that must have traded inside an L-minute range. A minute with no trade is normal
    in thin hours (its high/low are simply not part of the range); many missing = data outage."""
    return int(np.ceil(MIN_COVERAGE * L))


def width_ratio(width: np.ndarray, valid: np.ndarray) -> np.ndarray:
    """Today's range width / median width of the previous WIDTH_LOOKBACK valid days (today excluded)."""
    s = pd.Series(np.where(valid, width, np.nan))
    v = s.dropna()
    med = v.rolling(WIDTH_LOOKBACK, min_periods=WIDTH_LOOKBACK).median().shift(1)
    out = np.full(len(width), np.nan)
    out[v.index] = (v / med.where(med > 0)).to_numpy()
    return out


class CMEHolidays(AbstractHolidayCalendar):
    """US holidays on which CME energy closes or halts early (Columbus / Veterans Day trade normally)."""
    rules = [
        Holiday("New Year", month=1, day=1, observance=sunday_to_monday),  # Saturday: Dec 31 trades normally
        USMartinLutherKingJr, USPresidentsDay, GoodFriday, USMemorialDay,
        Holiday("Juneteenth", month=6, day=19, start_date="2022-01-01", observance=nearest_workday),
        Holiday("July 4", month=7, day=4, observance=nearest_workday),
        USLaborDay, USThanksgivingDay,
        Holiday("Christmas", month=12, day=25, observance=nearest_workday),
    ]


def short_days(days: np.ndarray) -> np.ndarray:
    """Trading days (days since epoch) with a scheduled short session: CME holidays, the day after
    Thanksgiving, Christmas Eve. Known in advance, so using them is not look-ahead."""
    dates = pd.to_datetime(np.asarray(days, dtype=np.int64), unit="D")
    if len(dates) == 0:
        return np.zeros(0, dtype=bool)
    hol = CMEHolidays().holidays(dates.min(), dates.max())
    thanks = USThanksgivingDay.dates(dates.min() - pd.Timedelta(days=1), dates.max())
    extra = pd.DatetimeIndex(list(thanks + pd.Timedelta(days=1))
                             + [d for d in dates if d.month == 12 and d.day == 24])
    return dates.isin(hol) | dates.isin(extra)


def session_end(f: Front, days: np.ndarray) -> np.ndarray:
    """Per trading day: the flat-by minute, all known in advance:
    16:09 ET; 12:55 ET on a scheduled short day; 5 min before the front contract expires
    (on its last day it can still be the front month, and it stops trading at 14:30 ET).
    Never derived from whether the day later HAS data: an evening (18:00 ET) entry cannot know that.
    Unscheduled data gaps are NOT treated as closes: a position runs into them as in real life."""
    out = local_tmin(days, SESSION_FLAT_MOD, ET)
    short = short_days(days)
    out[short] = local_tmin(days[short], SHORT_DAY_FLAT_MOD, ET)
    day_rows = np.flatnonzero((f.trading_day == f.et_day) & (f.mod < 17 * 60))  # daytime part of the session
    td = f.trading_day[day_rows]
    last_row = pd.Series(day_rows).groupby(td).max()
    k = np.searchsorted(days, last_row.index.to_numpy())
    exp = f.expiry[f.contract[last_row.to_numpy()]]
    expiring = (exp >= 0) & (exp - CLOSE_BUFFER < out[k])
    out[k[expiring]] = exp[expiring] - CLOSE_BUFFER
    return out


def eia_blocks(eia: pd.DataFrame | None, days: np.ndarray) -> np.ndarray:
    """(n_days, MAX_BLOCKS, 2) [start, end) UTC minutes where entries are blocked; -1 = unused."""
    out = np.full((len(days), MAX_BLOCKS, 2), -1, dtype=np.int64)
    if eia is None or eia.empty:
        return out
    eday = ((pd.to_datetime(eia["date"]) - pd.Timestamp("1970-01-01")) // pd.Timedelta(days=1)).to_numpy()
    rel = np.array([local_tmin([d], int(mn), ET)[0] for d, mn in zip(eday, eia["minute_et"])])
    pos = {d: k for k, d in enumerate(days)}
    count = np.zeros(len(days), dtype=np.int64)
    for d, r in zip(eday, rel):
        k = pos.get(d)
        if k is None:
            continue
        if count[k] >= MAX_BLOCKS:
            raise ValueError(f"more than {MAX_BLOCKS} EIA slots on one day")
        out[k, count[k]] = (r - EIA_BLOCK, r + EIA_BLOCK)
        count[k] += 1
    return out


# --- one day ----------------------------------------------------------------------------------

@njit(cache=True)
def _blocked(blk, tm):
    for k in range(blk.shape[0]):
        if blk[k, 0] <= tm < blk[k, 1]:
            return True
    return False


# --- fill / exit helpers shared by every ORB-family simulator ------------------------------------

@njit(cache=True)
def stop_order_fill(o_j, level, d, slip):
    """Resting stop order at `level` (direction d) triggered this minute."""
    return (o_j if d * (o_j - level) >= 0 else level) + d * slip


@njit(cache=True)
def stop_entry_minute(h_j, l_j, d, fill, stop, slip, pessimistic):
    """The minute a STOP-order entry filled (mid-minute, order of prices unknown).
    Returns (stopped out in this minute, MAE in ticks)."""
    worst = l_j if d == 1 else h_j
    mae = max(0.0, d * (fill - worst))
    touched = (d == 1 and l_j <= stop) or (d == -1 and h_j >= stop)
    if pessimistic and touched:
        return True, d * (fill - stop) + slip
    if not pessimistic:
        mae = min(mae, d * (fill - stop) + slip)
    return False, mae


@njit(cache=True)
def hold_minute(o_j, h_j, l_j, tm, cut_j, flat, check_flat, d, fill, stop, tgt, target_on, mae, slip,
                pessimistic):
    """One minute while holding. Returns (exit reason or 0, exit price, MAE).
    Order: flat/cutoff at the open; stop gapped through; target gapped through (needs 1 tick through,
    filled at the target); then intraminute stop vs target (stop wins when pessimistic)."""
    if check_flat and (tm >= flat or cut_j):
        return (EXIT_CUTOFF if cut_j and tm < flat else EXIT_TIME), o_j - d * slip, mae
    if d * (o_j - stop) <= 0:
        return EXIT_STOP, o_j - d * slip, max(mae, d * (fill - o_j))
    if target_on and d * (o_j - tgt) >= 1.0:
        return EXIT_TARGET, tgt, mae
    s_hit = (d == 1 and l_j <= stop) or (d == -1 and h_j >= stop)
    t_hit = target_on and ((d == 1 and h_j >= tgt + 1.0) or (d == -1 and l_j <= tgt - 1.0))
    worst = l_j if d == 1 else h_j
    if s_hit and (not t_hit or pessimistic):
        return EXIT_STOP, stop - d * slip, max(mae, d * (fill - stop))
    if t_hit:
        return EXIT_TARGET, tgt, max(mae, d * (fill - worst))
    return 0, np.nan, max(mae, d * (fill - worst))


@njit(cache=True)
def breakeven_stop(h_j, l_j, d, fill, stop, be_lvl):
    """(new stop, triggered): once price reaches be_lvl the stop moves to the fill (next minute on)."""
    best = h_j if d == 1 else l_j
    if d * (best - be_lvl) >= 0:
        return (fill if d * (fill - stop) > 0 else stop), True
    return stop, False


@njit(cache=True)
def record(n, r_in, r_out, r_dir, r_pin, r_pout, r_mae, r_why, entry_j, j, d, fill, px, mae, why):
    r_in[n] = entry_j; r_out[n] = j; r_dir[n] = d; r_pin[n] = fill
    r_pout[n] = px; r_mae[n] = mae; r_why[n] = why
    return n + 1


@njit(cache=True)
def range_stop(stop_type, d, hi, lo, fill, stop_ticks):
    if stop_type == MID:
        mid = (hi + lo) / 2.0
        return np.floor(mid) if d == 1 else np.ceil(mid)
    if stop_type == OPPOSITE:
        return lo - 1.0 if d == 1 else hi + 1.0
    return fill - d * stop_ticks


@njit(cache=True)
def sim_day(e, rend, hi, lo, flat, deadline, blk,
            tmin, o, h, l, c, con, cut,
            trigger, buf, stop_type, stop_ticks, target_r, dirpol, be, slip, pessimistic,
            r_in, r_out, r_dir, r_pin, r_pout, r_mae, r_why):
    """Simulate one classic-ORB day. Writes up to 2 trades into the r_* arrays; returns the count."""
    nF = len(tmin)
    lvl_long = hi + 1.0 + buf
    lvl_short = lo - 1.0 - buf
    used_long = dirpol == SHORT
    used_short = dirpol == LONG
    max_tr = 2 if dirpol == BOTH2 else 1
    target_on = target_r > 0
    c0 = con[e]
    n = 0
    pos = 0
    pend = 0
    fill = 0.0
    stop = 0.0
    tgt = 0.0
    be_lvl = 0.0
    be_on = False
    mae = 0.0
    entry_j = -1
    last_j = -1
    j = e
    while j < nF:
        tm = tmin[j]
        if con[j] != c0:
            break  # contract changed: handled after the loop
        just_filled = False

        if pos == 0:
            if pend != 0:
                d = pend
                pend = 0
                if tm < deadline and not cut[j] and not _blocked(blk, tm):
                    fill = o[j] + d * slip
                    stop = range_stop(stop_type, d, hi, lo, fill, stop_ticks)
                    r = d * (fill - stop)
                    if r >= 1.0:
                        pos = d
                        entry_j = j
                        tgt = fill + d * np.ceil(target_r * r) if target_on else 0.0
                        be_lvl = fill + d * r
                        be_on = False
                        mae = 0.0
                        just_filled = True  # filled at the open: rest of this minute is a normal holding minute
            if pos == 0:
                if tm >= deadline or tm >= flat or n >= max_tr:
                    break
                if trigger == STOP:
                    lt = (not used_long) and h[j] >= lvl_long
                    st = (not used_short) and l[j] <= lvl_short
                    if lt and st:  # both sides in one minute: the one nearer the open went first
                        if lvl_long - o[j] <= o[j] - lvl_short:
                            st = False
                        else:
                            lt = False
                    if lt or st:
                        d = 1 if lt else -1
                        if d == 1:
                            used_long = True
                        else:
                            used_short = True
                        if cut[j] or _blocked(blk, tm):
                            j += 1
                            continue
                        fill = stop_order_fill(o[j], lvl_long if d == 1 else lvl_short, d, slip)
                        stop = range_stop(stop_type, d, hi, lo, fill, stop_ticks)
                        r = d * (fill - stop)
                        if r < 1.0:
                            j += 1
                            continue
                        pos = d
                        entry_j = j
                        last_j = j
                        tgt = fill + d * np.ceil(target_r * r) if target_on else 0.0
                        be_lvl = fill + d * r
                        be_on = False
                        stopped, mae = stop_entry_minute(h[j], l[j], d, fill, stop, slip, pessimistic)
                        if stopped:
                            n = record(n, r_in, r_out, r_dir, r_pin, r_pout, r_mae, r_why,
                                       entry_j, j, d, fill, stop - d * slip, mae, EXIT_STOP)
                            pos = 0
                            if dirpol != BOTH2 or n >= max_tr:
                                break
                    j += 1
                    continue
                else:
                    # close-confirmed: is minute j the last of its bar?
                    if trigger == CLOSE1:
                        bar_end = tm + 1
                        is_end = True
                    else:
                        k = (tm - rend) // 5
                        bar_end = rend + 5 * (k + 1)
                        is_end = (j + 1 >= nF) or con[j + 1] != c0 or tmin[j + 1] >= bar_end
                    if is_end and bar_end <= deadline:
                        if (not used_long) and c[j] >= lvl_long:
                            used_long = True
                            pend = 1
                        elif (not used_short) and c[j] <= lvl_short:
                            used_short = True
                            pend = -1
                    j += 1
                    continue

        # holding
        d = pos
        last_j = j
        why, px, mae = hold_minute(o[j], h[j], l[j], tm, cut[j], flat, not just_filled, d, fill, stop, tgt,
                                   target_on, mae, slip, pessimistic)
        if why != 0:
            n = record(n, r_in, r_out, r_dir, r_pin, r_pout, r_mae, r_why, entry_j, j, d, fill, px, mae, why)
            pos = 0
            if why != EXIT_STOP or dirpol != BOTH2 or n >= max_tr:
                break
            j += 1
            continue
        if be and not be_on:
            stop, be_on = breakeven_stop(h[j], l[j], d, fill, stop, be_lvl)
        j += 1

    if pos != 0:  # window ran out without a flat minute (contract change / end of data)
        n = record(n, r_in, r_out, r_dir, r_pin, r_pout, r_mae, r_why,
                   entry_j, last_j, pos, fill, c[last_j] - pos * slip, mae, EXIT_FALLBACK)
    return n


@njit(cache=True)
def _flat_deadline(rend, sess_end, window, flat_off):
    flat = sess_end if flat_off == SESSION else min(rend + flat_off, sess_end)
    return flat, min(rend + window, flat)


@njit(cache=True)
def _day_allowed(width_mode, ratio):
    if width_mode == W_NONE:
        return True
    if np.isnan(ratio):
        return False
    if width_mode == W_SKIP_WIDE:
        return ratio <= WIDE
    if width_mode == W_SKIP_NARROW:
        return ratio >= NARROW
    return NARROW <= ratio <= WIDE


@njit(cache=True)
def orb_day(cfg, d, tables, minutes, slip, pessimistic, r_in, r_out, r_dir, r_pin, r_pout, r_mae, r_why):
    """Classic ORB day function: trades of one config on day d (0 if the day is not traded).
    Every family has a day function with this signature; the kernels below take it as an argument."""
    valid, hi, lo, e_idx, rend, ratio, sess_end, blocks = tables
    tmin, o, h, l, c, con, cut = minutes
    tb = cfg[C_TABLE]
    if not valid[tb, d] or sess_end[d] < 0 or not _day_allowed(cfg[C_WIDTH], ratio[tb, d]):
        return 0
    flat, deadline = _flat_deadline(rend[tb, d], sess_end[d], cfg[C_WINDOW], cfg[C_FLAT])
    if deadline <= rend[tb, d]:
        return 0
    return sim_day(e_idx[tb, d], rend[tb, d], hi[tb, d], lo[tb, d], flat, deadline, blocks[d],
                   tmin, o, h, l, c, con, cut,
                   cfg[C_TRIGGER], float(cfg[C_BUFFER]), cfg[C_STOP_TYPE], float(cfg[C_STOP_TICKS]),
                   cfg[C_TARGET_X10] / 10.0, cfg[C_DIRPOL], cfg[C_BE] == 1, slip, pessimistic,
                   r_in, r_out, r_dir, r_pin, r_pout, r_mae, r_why)


# --- one config: full trade list ----------------------------------------------------------------

@njit(cache=False)
def run_trades(day_fn, cfg, n_days, tables, minutes, slip, pessimistic):
    """All trades of one config. Returns (day, in_row, out_row, dir, px_in, px_out, mae, why)."""
    cap = 2 * n_days + 2
    t_day = np.empty(cap, np.int64); t_in = np.empty(cap, np.int64); t_out = np.empty(cap, np.int64)
    t_dir = np.empty(cap, np.int8); t_pin = np.empty(cap); t_pout = np.empty(cap)
    t_mae = np.empty(cap); t_why = np.empty(cap, np.int8)
    r_in = np.empty(2, np.int64); r_out = np.empty(2, np.int64); r_dir = np.empty(2, np.int8)
    r_pin = np.empty(2); r_pout = np.empty(2); r_mae = np.empty(2); r_why = np.empty(2, np.int8)
    k = 0
    for d in range(n_days):
        nt = day_fn(cfg, d, tables, minutes, slip, pessimistic, r_in, r_out, r_dir, r_pin, r_pout, r_mae, r_why)
        for q in range(nt):
            t_day[k] = d; t_in[k] = r_in[q]; t_out[k] = r_out[q]; t_dir[k] = r_dir[q]
            t_pin[k] = r_pin[q]; t_pout[k] = r_pout[q]; t_mae[k] = r_mae[q]; t_why[k] = r_why[q]
            k += 1
    return t_day[:k], t_in[:k], t_out[:k], t_dir[:k], t_pin[:k], t_pout[:k], t_mae[:k], t_why[:k]


# --- many configs ---------------------------------------------------------------------------------
# Functions below read propsim (constants, Combine rules). numba's on-disk cache only notices edits
# to THIS file, so they are compiled fresh each run (cache=False) to never use stale propsim rules.

# metric columns of grid_kernel's output
M_NAMES = ["trades", "wins", "gross_win", "gross_loss", "total_usd", "max_losing_streak", "best_day_usd",
           "max_drawdown_usd", "sharpe_daily", "stop_exits", "fallback_exits", "pass_prob", "fail_prob",
           "p95_drawdown", "stream_hash"]
N_M = len(M_NAMES)


@njit(cache=False)
def trade_pnl(direction, px_in, px_out):
    """Same formula as propsim.trade_pnl_usd, usable inside numba."""
    return direction * (px_out - px_in) * P.TICK_USD - P.FEE_USD


@njit(cache=False)
def _bootstrap(day_pnl, day_low, n_use, u, block):
    """Combine pass / fail / p95 drawdown on days [0, n_use) with common random numbers u."""
    n_sims = u.shape[0]
    passed = 0
    failed = 0
    dds = np.empty(n_sims)
    starts = np.empty(u.shape[1], np.int64)
    for s in range(n_sims):
        for b in range(u.shape[1]):
            starts[b] = int(u[s, b] * n_use)
        res, _, dd = P._combine_attempt(day_pnl[:n_use], day_low[:n_use], starts, block)
        if res == 1:
            passed += 1
        elif res == -1:
            failed += 1
        dds[s] = dd
    return passed / n_sims, failed / n_sims, np.quantile(dds, 0.95)


@njit(cache=False, parallel=True)
def grid_kernel(day_fn, cfgs, n_days, year_of_day, n_years, fold_ends, hash_w,
                tables, minutes, slip, pessimistic, u, u_wf, block, score):
    """Metrics for every config on days [0, n_days).
    Returns (metrics [n_cfg, N_M], yearly P&L [n_cfg, n_years], yearly trades, yearly best day,
             walk-forward fold scores [n_cfg, n_folds, 2] = pass prob, p95 drawdown on the fold prefix).
    score=False skips the Combine bootstraps (pass/fail/p95 and fold scores stay 0)."""
    n_cfg = cfgs.shape[0]
    n_folds = len(fold_ends)
    met = np.zeros((n_cfg, N_M))
    ypnl = np.zeros((n_cfg, n_years))
    ytr = np.zeros((n_cfg, n_years), np.int32)
    ybest = np.zeros((n_cfg, n_years))
    wf = np.zeros((n_cfg, n_folds if score else 0, 2))
    for i in prange(n_cfg):
        cfg = cfgs[i]
        r_in = np.empty(2, np.int64); r_out = np.empty(2, np.int64); r_dir = np.empty(2, np.int8)
        r_pin = np.empty(2); r_pout = np.empty(2); r_mae = np.empty(2); r_why = np.empty(2, np.int8)
        day_pnl = np.zeros(n_days)
        day_low = np.zeros(n_days)
        trades = 0; wins = 0; gw = 0.0; gl = 0.0; streak = 0; worst_streak = 0; stops = 0; falls = 0
        for d in range(n_days):
            nt = day_fn(cfg, d, tables, minutes, slip, pessimistic,
                        r_in, r_out, r_dir, r_pin, r_pout, r_mae, r_why)
            if nt == 0:
                continue
            y = year_of_day[d]
            p_day, low_day = P.daily_series(np.zeros(nt, np.int64),
                                            trade_pnl(r_dir[:nt], r_pin[:nt], r_pout[:nt]),
                                            r_mae[:nt] * P.TICK_USD + P.FEE_USD, 1)
            day_pnl[d] = p_day[0]
            day_low[d] = low_day[0]
            for q in range(nt):
                pnl = trade_pnl(r_dir[q], r_pin[q], r_pout[q])
                trades += 1
                ytr[i, y] += 1
                if pnl > 0:
                    wins += 1
                    gw += pnl
                    streak = 0
                else:
                    gl -= pnl
                    streak += 1
                    if streak > worst_streak:
                        worst_streak = streak
                if r_why[q] == EXIT_STOP:
                    stops += 1
                elif r_why[q] == EXIT_FALLBACK:
                    falls += 1
            ypnl[i, y] += day_pnl[d]
            if day_pnl[d] > ybest[i, y]:
                ybest[i, y] = day_pnl[d]
        sd = day_pnl.std()
        hsum = 0.0
        for d in range(n_days):
            hsum += day_pnl[d] * hash_w[d]
        met[i, 0] = trades; met[i, 1] = wins; met[i, 2] = gw; met[i, 3] = gl; met[i, 4] = day_pnl.sum()
        met[i, 5] = worst_streak; met[i, 6] = day_pnl.max(); met[i, 7] = P.max_drawdown(day_pnl, day_low)
        met[i, 8] = day_pnl.mean() / sd if sd > 0 else 0.0
        met[i, 9] = stops; met[i, 10] = falls; met[i, 14] = np.round(hsum, 2)
        if score:
            met[i, 11], met[i, 12], met[i, 13] = _bootstrap(day_pnl, day_low, n_days, u, block)
            for f in range(n_folds):
                p_, _, dd_ = _bootstrap(day_pnl, day_low, fold_ends[f], u_wf, block)
                wf[i, f, 0] = p_
                wf[i, f, 1] = dd_
    return met, ypnl, ytr, ybest, wf


@njit(cache=False, parallel=True)
def daily_kernel(day_fn, cfgs, n_days, tables, minutes, slip, pessimistic):
    """Daily P&L and intraday low per config (for the small sets that need full series)."""
    n_cfg = cfgs.shape[0]
    out_pnl = np.zeros((n_cfg, n_days))
    out_low = np.zeros((n_cfg, n_days))
    for i in prange(n_cfg):
        t = run_trades(day_fn, cfgs[i], n_days, tables, minutes, slip, pessimistic)
        out_pnl[i], out_low[i] = P.daily_series(t[0], trade_pnl(t[3], t[4], t[5]),
                                                t[6] * P.TICK_USD + P.FEE_USD, n_days)
    return out_pnl, out_low


class Market:
    """Everything the classic-ORB kernels need, built once. Families subclass it and swap
    `day_fn` / `day_args`."""

    day_fn = orb_day

    def __init__(self, m, days: np.ndarray, eia: pd.DataFrame | None, strict_expiry=False):
        self.f = Front(m, strict_expiry)
        self.days = days
        self.eia = eia
        self.t = DayTables(self.f, days, eia)

    def day_args(self):
        t = self.t
        return (t.valid, t.hi, t.lo, t.e_idx, t.rend, t.ratio, t.sess_end, t.blocks)

    def minute_args(self):
        f = self.f
        return (f.tmin, f.open, f.high, f.low, f.close, f.contract, f.cut)

    def trades(self, cfg, n_days=None, slip=1.0, pessimistic=True):
        n_days = len(self.days) if n_days is None else n_days
        t = run_trades(self.day_fn, np.asarray(cfg, np.int64), n_days, self.day_args(), self.minute_args(),
                       float(slip), pessimistic)
        if len(t[1]) and (self.f.contract[t[1]] != self.f.contract[t[2]]).any():  # roll-safety invariant
            raise RuntimeError("trade entry and exit on different contracts: engine bug")
        return t
