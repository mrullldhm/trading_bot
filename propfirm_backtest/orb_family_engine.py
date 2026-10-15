"""Day simulators for the ORB families: ZAB (strategy 3), Crabel (4), Fisher ACD (5).

All fills and exits use the shared helpers in orb_engine (same pessimistic rules as classic ORB:
stop-order gap fills, stop wins a same-minute stop/target tie, targets need a 1-tick trade-through,
EIA block / roll cutoff make a signal unusable, short days, contract expiry, roll invariant).
Each family has a day function with orb_engine's day-function signature, so the generic kernels
(orb_engine.grid_kernel / daily_kernel / run_trades) run it unchanged.

ZAB-inspired CL (Zarattini, Aziz, Barbon). The first opening-range "candle" (open -> close of the
range window) sets the side: up = long, down = short, unchanged = no trade.
  IMMEDIATE (2023 paper): market order at the first minute after the range.
  BREAKOUT (2024 paper): resting stop 1 tick beyond the range edge on that side, valid until flat.
  Stop: 1 tick beyond the opposite range edge, or k x ATR14 (prior sessions) from the fill, rounded
  out to whole ticks. Target 10R or none; exit at the flat time. Relative opening volume filter
  (today's range volume / mean of the previous 14 days) replaces the paper's cross-section of stocks.

Crabel. Resting stops at OR high + stretch and OR low - stretch (stretch = multiplier x mean of
min(high - open, open - low) over the previous 10 sessions, rounded up, >= 1 tick); the first fill
is the trade. Protective stop = the opposite trigger level (Crabel) or the OR midpoint. Setup filter
from the previous session: NR4, NR7, inside day, ID/NR4. No target; exit at the flat time. This is
classic ORB's STOP trigger with the range edges moved out by the stretch, so it runs on
orb_engine.sim_day (same tested fill rules).

Fisher ACD. A-up = OR high + A, A-down = OR low - A, C-up = OR high + C, C-down = OR low - C, with
A, C = fractions of the prior-session ATR14 (a proxy for Fisher's proprietary values), rounded up.
A level is ACCEPTED after T consecutive clock minutes whose whole bar stayed beyond it (low >= level
for up, high <= level for down; a missing minute restarts the count): conservative time rule.
State machine, one A per day: neutral -> A accepted (enter at the next minute's open; stop B = 1 tick
beyond the opposite OR edge) -> failure when price trades through B (the A trade, if any, is stopped
there) -> C reversal: the opposite C level accepted (enter next open; stop D = 1 tick beyond the
opposite OR edge) -> done. Market states run whether or not a side may be traded (direction / pivot
filters only decide which entries are taken). Pivot filter: session open above the prior-session
pivot range -> longs only, below -> shorts only, inside -> both. No target; exit at the flat time.
"""

import numpy as np
from numba import njit

from . import orb_engine as E
from . import orb_features as F

FAMILY_ANCHORS = ["et0900", "london0800"]
# Every function here calls orb_engine helpers. numba's on-disk cache only notices edits to the file
# that defines a function, so these compile fresh each run (cache=False) and never use stale helpers.


def anchor_row(anchor: str) -> int:
    return FAMILY_ANCHORS.index(anchor)

# --- shared: hold one position until it exits -------------------------------------------------------


@njit(cache=False)
def hold_position(j, check_flat_first, d, fill, stop, tgt, target_on, mae, flat, c0, entry_j,
                  tmin, o, h, l, c, con, cut, slip, pessimistic, n,
                  r_in, r_out, r_dir, r_pin, r_pout, r_mae, r_why):
    """Hold from row j until an exit; records the trade. Returns (n, exit reason, exit row)."""
    nF = len(tmin)
    last_j = max(entry_j, j - 1)
    check = check_flat_first
    while j < nF and con[j] == c0:
        last_j = j
        why, px, mae = E.hold_minute(o[j], h[j], l[j], tmin[j], cut[j], flat, check, d, fill, stop, tgt,
                                     target_on, mae, slip, pessimistic)
        check = True
        if why != 0:
            n = E.record(n, r_in, r_out, r_dir, r_pin, r_pout, r_mae, r_why, entry_j, j, d, fill, px, mae, why)
            return n, why, j
        j += 1
    n = E.record(n, r_in, r_out, r_dir, r_pin, r_pout, r_mae, r_why,
                 entry_j, last_j, d, fill, c[last_j] - d * slip, mae, E.EXIT_FALLBACK)
    return n, E.EXIT_FALLBACK, last_j


@njit(cache=False)
def flat_time(rend, sess_end, flat_off):
    return E._flat_deadline(rend, sess_end, 0, flat_off)[0]


# --- ZAB ------------------------------------------------------------------------------------------

Z_TABLE, Z_ANCHOR, Z_ENTRY, Z_STOP_ATR_X100, Z_TARGET_R, Z_FLAT, Z_RELVOL_X10, Z_DIR = range(8)
IMMEDIATE, BREAKOUT = 0, 1
DIR_CANDLE, DIR_LONG, DIR_SHORT = 0, 1, 2


@njit(cache=False)
def zab_day(cfg, d, tables, minutes, slip, pessimistic, r_in, r_out, r_dir, r_pin, r_pout, r_mae, r_why):
    valid, hi, lo, e_idx, rend, ropen, rclose, relvol, atr, sess_end, blocks = tables
    tmin, o, h, l, c, con, cut = minutes
    tb = cfg[Z_TABLE]
    if not valid[tb, d] or sess_end[d] < 0:
        return 0
    thr = cfg[Z_RELVOL_X10] / 10.0
    if thr > 0 and not (relvol[tb, d] >= thr):  # NaN (no history yet) = no trade
        return 0
    side = 1 if rclose[tb, d] > ropen[tb, d] else (-1 if rclose[tb, d] < ropen[tb, d] else 0)
    if side == 0 or (cfg[Z_DIR] == DIR_LONG and side == -1) or (cfg[Z_DIR] == DIR_SHORT and side == 1):
        return 0
    stop_dist = 0.0
    if cfg[Z_STOP_ATR_X100] > 0:
        a = atr[cfg[Z_ANCHOR], d]
        if np.isnan(a):
            return 0
        stop_dist = max(1.0, np.ceil(cfg[Z_STOP_ATR_X100] / 100.0 * a))
    r_end = rend[tb, d]
    flat = flat_time(r_end, sess_end[d], cfg[Z_FLAT])
    if flat <= r_end:
        return 0
    blk = blocks[d]
    e = e_idx[tb, d]
    c0 = con[e]
    target_r = float(cfg[Z_TARGET_R])
    level = hi[tb, d] + 1.0 if side == 1 else lo[tb, d] - 1.0
    nF = len(tmin)
    j = e
    while j < nF and con[j] == c0 and tmin[j] < flat:
        tm = tmin[j]
        if cfg[Z_ENTRY] == IMMEDIATE:
            if cut[j] or E._blocked(blk, tm):
                return 0
            fill = o[j] + side * slip
            intraminute = False
        else:
            if side * ((h[j] if side == 1 else l[j]) - level) < 0:
                j += 1
                continue
            if cut[j] or E._blocked(blk, tm):
                return 0  # the breakout happened when no entry was allowed: side used up
            fill = E.stop_order_fill(o[j], level, side, slip)
            intraminute = True
        stop = fill - side * stop_dist if stop_dist > 0 else (lo[tb, d] - 1.0 if side == 1 else hi[tb, d] + 1.0)
        r = side * (fill - stop)
        if r < 1.0:
            return 0
        tgt = fill + side * np.ceil(target_r * r) if target_r > 0 else 0.0
        if intraminute:
            stopped, mae = E.stop_entry_minute(h[j], l[j], side, fill, stop, slip, pessimistic)
            if stopped:
                return E.record(0, r_in, r_out, r_dir, r_pin, r_pout, r_mae, r_why,
                                j, j, side, fill, stop - side * slip, mae, E.EXIT_STOP)
            n, _, _ = hold_position(j + 1, True, side, fill, stop, tgt, target_r > 0, mae, flat, c0, j,
                                    tmin, o, h, l, c, con, cut, slip, pessimistic, 0,
                                    r_in, r_out, r_dir, r_pin, r_pout, r_mae, r_why)
        else:  # filled at the open: the rest of this minute is a normal holding minute
            n, _, _ = hold_position(j, False, side, fill, stop, tgt, target_r > 0, 0.0, flat, c0, j,
                                    tmin, o, h, l, c, con, cut, slip, pessimistic, 0,
                                    r_in, r_out, r_dir, r_pin, r_pout, r_mae, r_why)
        return n
    return 0


# --- Crabel ---------------------------------------------------------------------------------------

C_TABLE, C_ANCHOR, C_STRETCH_X100, C_SETUP, C_WINDOW, C_FLAT, C_STOP, C_DIR = range(8)
SETUP_NONE, SETUP_NR4, SETUP_NR7, SETUP_INSIDE, SETUP_IDNR4 = range(5)


@njit(cache=False)
def crabel_day(cfg, d, tables, minutes, slip, pessimistic, r_in, r_out, r_dir, r_pin, r_pout, r_mae, r_why):
    valid, hi, lo, e_idx, rend, stretch, setups, sess_end, blocks = tables
    tmin, o, h, l, c, con, cut = minutes
    tb = cfg[C_TABLE]
    an = cfg[C_ANCHOR]
    if not valid[tb, d] or sess_end[d] < 0 or np.isnan(stretch[an, d]):
        return 0
    if cfg[C_SETUP] != SETUP_NONE and not setups[an, cfg[C_SETUP], d]:
        return 0
    s = max(1.0, np.ceil(cfg[C_STRETCH_X100] / 100.0 * stretch[an, d]))
    r_end = rend[tb, d]
    flat, deadline = E._flat_deadline(r_end, sess_end[d], cfg[C_WINDOW], cfg[C_FLAT])
    if deadline <= r_end:
        return 0
    # sim_day puts its levels 1 tick beyond hi / lo: shift the edges so the levels are OR +/- stretch
    return E.sim_day(e_idx[tb, d], r_end, hi[tb, d] + s - 1.0, lo[tb, d] - s + 1.0, flat, deadline, blocks[d],
                     tmin, o, h, l, c, con, cut,
                     E.STOP, 0.0, cfg[C_STOP], 0.0, 0.0, cfg[C_DIR], False, slip, pessimistic,
                     r_in, r_out, r_dir, r_pin, r_pout, r_mae, r_why)


# --- Fisher ACD --------------------------------------------------------------------------------------

A_TABLE, A_ANCHOR, A_LEN, A_A_X1000, A_C_X1000, A_ACC_X100, A_PIVOT, A_C_ON, A_FLAT, A_DIR = range(10)
ACD_NEUTRAL, ACD_A_UP, ACD_A_DOWN, ACD_FAILED, ACD_DONE = 0, 1, 2, 3, 4


@njit(cache=False)
def acd_day(cfg, d, tables, minutes, slip, pessimistic, r_in, r_out, r_dir, r_pin, r_pout, r_mae, r_why):
    valid, hi, lo, e_idx, rend, ropen, atr, piv_lo, piv_hi, sess_end, blocks = tables
    tmin, o, h, l, c, con, cut = minutes
    tb = cfg[A_TABLE]
    an = cfg[A_ANCHOR]
    if not valid[tb, d] or sess_end[d] < 0 or np.isnan(atr[an, d]):
        return 0
    allow_long = cfg[A_DIR] != DIR_SHORT
    allow_short = cfg[A_DIR] != DIR_LONG
    if cfg[A_PIVOT] == 1:
        if np.isnan(piv_lo[an, d]):
            return 0
        if ropen[tb, d] > piv_hi[an, d]:
            allow_short = False
        elif ropen[tb, d] < piv_lo[an, d]:
            allow_long = False
    a_val = max(1.0, np.ceil(cfg[A_A_X1000] / 1000.0 * atr[an, d]))
    c_val = max(1.0, np.ceil(cfg[A_C_X1000] / 1000.0 * atr[an, d]))
    need = max(1, int(np.ceil(cfg[A_ACC_X100] / 100.0 * cfg[A_LEN])))
    H, Lo = hi[tb, d], lo[tb, d]
    r_end = rend[tb, d]
    flat = flat_time(r_end, sess_end[d], cfg[A_FLAT])
    if flat <= r_end:
        return 0
    blk = blocks[d]
    e = e_idx[tb, d]
    c0 = con[e]
    nF = len(tmin)
    state = ACD_NEUTRAL
    c_side = 0
    run_up = 0
    run_dn = 0
    run_c = 0
    prev_t = -1
    n = 0
    j = e
    while j < nF and con[j] == c0 and tmin[j] < flat:
        tm = tmin[j]
        step = prev_t == tm - 1
        prev_t = tm
        signal = 0
        if state == ACD_NEUTRAL:
            run_up = (run_up + 1 if step else 1) if l[j] >= H + a_val else 0
            run_dn = (run_dn + 1 if step else 1) if h[j] <= Lo - a_val else 0
            if run_up >= need:
                state = ACD_A_UP
                signal = 1
            elif run_dn >= need:
                state = ACD_A_DOWN
                signal = -1
        elif state == ACD_A_UP or state == ACD_A_DOWN:
            if (state == ACD_A_UP and l[j] <= Lo - 1.0) or (state == ACD_A_DOWN and h[j] >= H + 1.0):
                c_side = -1 if state == ACD_A_UP else 1
                state = ACD_FAILED if cfg[A_C_ON] == 1 else ACD_DONE
                run_c = 0
        if state == ACD_FAILED:  # the bar that failed through B can itself count towards C
            run_c = (run_c + 1 if step else 1) if c_side * ((l[j] if c_side == 1 else h[j]) - (H + c_val if c_side == 1 else Lo - c_val)) >= 0 else 0
            if run_c >= need:
                state = ACD_DONE
                signal = c_side
        if state == ACD_DONE and signal == 0:
            break
        if signal != 0 and ((signal == 1 and allow_long) or (signal == -1 and allow_short)):
            k = j + 1  # accepted at the close of bar j: enter at the next minute's open
            if k < nF and con[k] == c0 and tmin[k] < flat and not cut[k] and not E._blocked(blk, tmin[k]):
                fill = o[k] + signal * slip
                stop = Lo - 1.0 if signal == 1 else H + 1.0
                if signal * (fill - stop) >= 1.0:
                    is_a = state != ACD_DONE
                    n, why, jx = hold_position(k, False, signal, fill, stop, 0.0, False, 0.0, flat, c0, k,
                                               tmin, o, h, l, c, con, cut, slip, pessimistic, n,
                                               r_in, r_out, r_dir, r_pin, r_pout, r_mae, r_why)
                    if not is_a or why != E.EXIT_STOP or cfg[A_C_ON] == 0:
                        break
                    state = ACD_FAILED  # the A trade was stopped at B: that IS the failure
                    c_side = -signal
                    run_c = 0
                    prev_t = tmin[jx] - 1
                    j = jx  # re-read the stop bar: it can count towards C acceptance
                    continue
        if state == ACD_DONE:
            break
        j += 1
    return n


# --- markets ----------------------------------------------------------------------------------------

class FamilyMarket(E.Market):
    """Front minutes + per-family day tables. Subclasses set RANGE_LENGTHS, day_fn, _build()."""

    RANGE_LENGTHS: list = []

    def __init__(self, m, days, eia, strict_expiry=False):
        self.f = E.Front(m, strict_expiry)
        self.days = days
        self.eia = eia
        self.keys = [(a, L) for a in FAMILY_ANCHORS for L in self.RANGE_LENGTHS]
        self.t = E.DayTables(self.f, days, eia, keys=self.keys)
        self.sessions = [F.Sessions(self.f, days, a) for a in FAMILY_ANCHORS]
        self.atr = np.vstack([s.atr14 for s in self.sessions])
        self._build()

    def _build(self):
        pass

    def table_index(self, anchor, L):
        return self.keys.index((anchor, L))


class ZabMarket(FamilyMarket):
    RANGE_LENGTHS = [5, 15, 30]
    day_fn = zab_day

    def _build(self):
        t = self.t
        self.relvol = np.vstack([F.relative_volume(t.rvol[k], t.valid[k]) for k in range(len(self.keys))])

    def day_args(self):
        t = self.t
        return (t.valid, t.hi, t.lo, t.e_idx, t.rend, t.ropen, t.rclose, self.relvol, self.atr,
                t.sess_end, t.blocks)



class CrabelMarket(FamilyMarket):
    RANGE_LENGTHS = [1, 5, 15]
    day_fn = crabel_day

    def _build(self):
        self.stretch = np.vstack([s.stretch for s in self.sessions])
        flags = np.zeros((len(FAMILY_ANCHORS), SETUP_IDNR4 + 1, len(self.days)), dtype=np.bool_)
        for a, s in enumerate(self.sessions):
            flags[a, SETUP_NONE] = True
            flags[a, SETUP_NR4], flags[a, SETUP_NR7] = s.nr4, s.nr7
            flags[a, SETUP_INSIDE], flags[a, SETUP_IDNR4] = s.inside, s.idnr4
        self.setups = flags

    def day_args(self):
        t = self.t
        return (t.valid, t.hi, t.lo, t.e_idx, t.rend, self.stretch, self.setups, t.sess_end, t.blocks)


class AcdMarket(FamilyMarket):
    RANGE_LENGTHS = [5, 10, 15, 20, 30]
    day_fn = acd_day

    def _build(self):
        self.piv_lo = np.vstack([s.piv_lo for s in self.sessions])
        self.piv_hi = np.vstack([s.piv_hi for s in self.sessions])

    def day_args(self):
        t = self.t
        return (t.valid, t.hi, t.lo, t.e_idx, t.rend, t.ropen, self.atr, self.piv_lo, self.piv_hi,
                t.sess_end, t.blocks)
