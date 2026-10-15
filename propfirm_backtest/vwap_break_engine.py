"""CL "VWAP Break" simulator (numba): a third-party 5-minute MA-touch breakout, replicated as written.

Source: the "CL VWAP Break Bot (TopstepX)" write-up, rules as of 15 Oct 2026. Parameters were tuned
by its author on 27 Jul - 15 Oct 2026 only, so every earlier year is out of sample for them.

Bars: clock-aligned 5-minute ET bars (bars.build_bars). Lines: EMA20 ("red") and SMA50 ("blue").
VWAP: typical price, anchored to the CME day (18:00 ET = the bot's 06:00 MYT). ATR: Wilder, 5-min.
All three restart per contract. C1, C2, C3 = three consecutive 5-min bars of one contract and day.

Setup, decided at the close of C2 (prices in ticks):
- C1 touches a line: C1.low - tol <= line(C1) <= C1.high + tol (tol = 1.25 ticks).
- Long: C2.low > min(lines at C2), C2.high > C1.high, C2.low > C1.low. Short: mirror.
- Order: stop at C2.high + 1 (long), protective stop at C1.low; risk R = entry - stop.
- dist = |C2.close - VWAP(C2 close)|; band = 0.5 * ATR14 (0.7 * ATR14 when R >= 30).
  Normal / wide: dist <= band and R < 50 -> target 2R, or 2.5R when ATR14 > 1.12 * ATR100.
  Far: dist >= 70, EMA20 on the trade side of SMA50, R < 40 -> 1R.
  Scalp: outside the band, R < 18 -> 1R. Anything else: no trade.
  Target = entry level +/- floor(mult * R) (absolute price, matches the write-up's worked example).
- The order lives through C3 and C4. Cancelled at C3's close if unfilled and C3 touched a line
  that C1 touched (same tol, line value at C3). Cancelled at a flat time, a roll cutoff, or a gap.
- Add-on (optional): once filled, if the target is > 32 ticks from the fill, a stop order for the
  add-on size waits 32 ticks before the target, same stop and target; it ends with the base trade.
- One position at a time; new setups are ignored while an order or a position is open.
- Bot daily stop: once the day's realised P&L <= -$432, no new orders that trading day.

Fills and ambiguity follow orb_engine (stop orders gap-fill at the open, targets need 1 tick
through, stop wins over target in one minute when pessimistic). Add-on in the base trade's exit
minute: pessimistic = filled before a stop / missed before a target; optimistic = the reverse.
Not modelled: the bot's 45 s placement delay, chase re-entries, partial fills, rejections, the
cross-account hedge guard, Topstep's $1,000 Daily Loss Limit (see apply_dll, applied per day).
"""

import numpy as np
from numba import njit

from . import bars as B
from . import indicators as I
from . import orb_engine as E
from .orb_engine import EXIT_FALLBACK, EXIT_STOP, EXIT_TARGET, hold_minute, stop_entry_minute, stop_order_fill
from .orb_search import MCL_FEE_USD, MCL_TICK_USD

TF = 5
EMA_LEN, SMA_LEN, ATR_FAST, ATR_SLOW = 20, 50, 14, 100
DLL = 1000.0  # Topstep 50K Daily Loss Limit

NORMAL, WIDE, SCALP, FAR = 0, 1, 2, 3
CLASS_NAMES = {NORMAL: "normal", WIDE: "wide", SCALP: "scalp", FAR: "far"}

# config vector (float64)
(K_TOUCH_TOL, K_BAND, K_BAND_WIDE, K_BAND_WIDE_RISK, K_WIDE_RISK, K_MAX_RISK, K_SCALP_RISK, K_FAR_DIST,
 K_FAR_RISK, K_R, K_R_HOT, K_ATR_RATIO, K_R_SMALL, K_EXPIRY_BARS, K_CANCEL_TOUCH, K_ADDON, K_ADDON_OFFSET,
 K_DAILY_STOP, K_TICK_USD, K_FEE_USD, K_ADD_TICK_USD, K_ADD_FEE_USD, K_SCALP_ON, K_FAR_ON) = range(24)
N_K = 24

DEFAULTS = {
    K_TOUCH_TOL: 1.25, K_BAND: 0.5, K_BAND_WIDE: 0.7, K_BAND_WIDE_RISK: 30, K_WIDE_RISK: 40, K_MAX_RISK: 50,
    K_SCALP_RISK: 18, K_FAR_DIST: 70, K_FAR_RISK: 40, K_R: 2.0, K_R_HOT: 2.5, K_ATR_RATIO: 1.12, K_R_SMALL: 1.0,
    K_EXPIRY_BARS: 2, K_CANCEL_TOUCH: 1, K_ADDON: 1, K_ADDON_OFFSET: 32, K_DAILY_STOP: 432,
    # 1 CL + 2 MCL = $12/tick; add-on 6 MCL = $6/tick
    K_TICK_USD: 10.0 + 2 * MCL_TICK_USD, K_FEE_USD: 4.02 + 2 * MCL_FEE_USD,
    K_ADD_TICK_USD: 6 * MCL_TICK_USD, K_ADD_FEE_USD: 6 * MCL_FEE_USD,
    K_SCALP_ON: 1, K_FAR_ON: 1,
}


def config(**overrides) -> np.ndarray:
    """Default (as-published) config; override by lower-case key name, e.g. config(addon=0, band=0.6)."""
    c = np.zeros(N_K)
    for k, v in DEFAULTS.items():
        c[k] = v
    names = {n[2:].lower(): v for n, v in globals().items() if n.startswith("K_") and isinstance(v, int)}
    unknown = set(overrides) - set(names)
    if unknown:
        raise ValueError(f"unknown config keys {sorted(unknown)}; valid: {sorted(names)}")
    for key, v in overrides.items():
        c[names[key]] = v
    return c


# --- indicators (kept here: indicators.py is part of strategy 1's frozen source hash) -------------

@njit(cache=True)
def _sma(close, contract, length):
    """Simple moving average of the last `length` closes of the same contract. Returns (sma, valid)."""
    n = len(close)
    out = np.full(n, np.nan)
    valid = np.zeros(n, dtype=np.bool_)
    total = 0.0
    first = 0  # first row of the current contract
    for i in range(n):
        if i == 0 or contract[i] != contract[i - 1]:
            total = 0.0
            first = i
        total += close[i]
        if i - first >= length:
            total -= close[i - length]
        if i - first + 1 >= length:
            out[i] = total / length
            valid[i] = True
    return out, valid


@njit(cache=True)
def _atr(high, low, close, contract, length):
    """Wilder ATR per contract, seeded with the mean of the first `length` true ranges.
    The first bar of a contract has tr = high - low."""
    n = len(close)
    out = np.full(n, np.nan)
    valid = np.zeros(n, dtype=np.bool_)
    count = 0
    acc = 0.0
    for i in range(n):
        if i == 0 or contract[i] != contract[i - 1]:
            count = 0
            acc = 0.0
            tr = high[i] - low[i]
        else:
            pc = close[i - 1]
            tr = max(high[i] - low[i], abs(high[i] - pc), abs(low[i] - pc))
        count += 1
        if count < length:
            acc += tr
        elif count == length:
            acc = (acc + tr) / length
        else:
            acc = (acc * (length - 1) + tr) / length
        if count >= length:
            out[i] = acc
            valid[i] = True
    return out, valid


def apply_dll(day_pnl: np.ndarray, day_low: np.ndarray, dll: float = DLL) -> tuple[np.ndarray, np.ndarray]:
    """Topstep Daily Loss Limit: a day whose equity low (incl. open losses) reaches -dll is liquidated
    at -dll and ends; the Combine goes on. Assumes the liquidation fills exactly at the limit."""
    hit = day_low <= -dll
    return np.where(hit, -dll, day_pnl), np.maximum(day_low, -dll)


# --- prepared inputs -------------------------------------------------------------------------------

class Market:
    """5-minute bars, indicators and front-month minutes, built once per data load."""

    def __init__(self, m: B.Minutes, strict_expiry=False):
        f = E.Front(m, strict_expiry)
        bars = B.build_bars(m, TF)
        self.f, self.bars = f, bars
        self.ema, ema_ok = I.ema(bars, EMA_LEN)
        self.sma, sma_ok = _sma(bars.close, bars.contract, SMA_LEN)
        self.atr14, a14_ok = _atr(bars.high, bars.low, bars.close, bars.contract, ATR_FAST)
        self.atr100, a100_ok = _atr(bars.high, bars.low, bars.close, bars.contract, ATR_SLOW)
        after, _ = I.vwap_minutes(m, "day", "all")
        self.vwap = after[bars.end - 1]
        self.ok = ema_ok & sma_ok & a14_ok & a100_ok & np.isfinite(self.vwap)

        tradable = m.front[bars.start]  # bars never span a front-month change
        self.fs = np.full(len(bars), -1, np.int64)
        self.fs[tradable] = np.searchsorted(f.src, bars.start[tradable])
        self.fe = np.where(tradable, self.fs + (bars.end - bars.start), -1)
        self.bucket = m.ts[bars.start] // E.NS_PER_MIN // TF
        self.days = np.unique(f.trading_day)
        self.bar_day = np.searchsorted(self.days, m.trading_day[bars.start])
        self.row_day = np.searchsorted(self.days, f.trading_day)
        self.flat = E.session_end(f, self.days)[self.row_day]  # flat-by minute per front row

    def bar_args(self):
        b = self.bars
        return (self.fs, self.fe, self.bucket, self.bar_day, b.contract, b.high, b.low, b.close,
                self.ema, self.sma, self.atr14, self.atr100, self.vwap, self.ok)

    def minute_args(self):
        f = self.f
        return (f.tmin, f.open, f.high, f.low, f.close, self.flat, f.cut)

    def trades(self, cfg, slip=1.0, pessimistic=True):
        t = simulate(np.asarray(cfg, np.float64), self.bar_args(), self.minute_args(), float(slip), pessimistic)
        if len(t[1]) and (self.f.contract[t[1]] != self.f.contract[t[2]]).any():  # roll-safety invariant
            raise RuntimeError("trade entry and exit on different contracts: engine bug")
        return t


# --- engine ----------------------------------------------------------------------------------------

@njit(cache=True)
def _touch(lo, hi, line, tol):
    return lo - tol <= line <= hi + tol


@njit(cache=True)
def _next(i, fs, bucket, bar_day, contract):
    """True if bar i directly follows bar i-1: both tradable, same contract and day, next bucket."""
    return (i > 0 and fs[i] >= 0 and fs[i - 1] >= 0 and contract[i] == contract[i - 1]
            and bar_day[i] == bar_day[i - 1] and bucket[i] == bucket[i - 1] + 1)


@njit(cache=True)
def setup(cfg, i, fs, bucket, bar_day, contract, high, low, close, ema, sma, atr14, atr100, vwap, ok):
    """Setup with C2 = bar i. Returns (dir, level, stop, target, class, touched_ema, touched_sma);
    dir = 0 when there is none."""
    none = (0, 0.0, 0.0, 0.0, -1, False, False)
    if not _next(i, fs, bucket, bar_day, contract) or not ok[i] or not ok[i - 1]:
        return none
    c1, c2 = i - 1, i
    tol = cfg[K_TOUCH_TOL]
    t_ema = _touch(low[c1], high[c1], ema[c1], tol)
    t_sma = _touch(low[c1], high[c1], sma[c1], tol)
    if not (t_ema or t_sma):
        return none
    lower = min(ema[c2], sma[c2])
    upper = max(ema[c2], sma[c2])
    if low[c2] > lower and high[c2] > high[c1] and low[c2] > low[c1]:
        d = 1
        level = high[c2] + 1.0
        stop = low[c1]
    elif high[c2] < upper and low[c2] < low[c1] and high[c2] < high[c1]:
        d = -1
        level = low[c2] - 1.0
        stop = high[c1]
    else:
        return none
    risk = d * (level - stop)
    dist = abs(close[c2] - vwap[c2])
    band = (cfg[K_BAND_WIDE] if risk >= cfg[K_BAND_WIDE_RISK] else cfg[K_BAND]) * atr14[c2]
    if dist <= band:
        if risk >= cfg[K_MAX_RISK]:
            return none
        cls = WIDE if risk >= cfg[K_WIDE_RISK] else NORMAL
        mult = cfg[K_R_HOT] if atr14[c2] > cfg[K_ATR_RATIO] * atr100[c2] else cfg[K_R]
    elif cfg[K_FAR_ON] > 0 and dist >= cfg[K_FAR_DIST] and d * (ema[c2] - sma[c2]) > 0 and risk < cfg[K_FAR_RISK]:
        cls = FAR
        mult = cfg[K_R_SMALL]
    elif cfg[K_SCALP_ON] > 0 and risk < cfg[K_SCALP_RISK]:
        cls = SCALP
        mult = cfg[K_R_SMALL]
    else:
        return none
    target = level + d * np.floor(mult * risk)
    return d, level, stop, target, cls, t_ema, t_sma


@njit(cache=True)
def simulate(cfg, bar_args, minute_args, slip, pessimistic):
    """All trades. Returns (day, in_row, out_row, dir, px_in, px_out, why, class, risk_ticks,
    addon_filled, addon_px, pnl_usd, mae_usd); rows index the front-month minutes."""
    fs, fe, bucket, bar_day, contract, high, low, close, ema, sma, atr14, atr100, vwap, ok = bar_args
    tmin, o, h, l, c, flat, cut = minute_args
    nb = len(fs)
    cap = nb + 1  # at most one trade per bar
    t_day = np.empty(cap, np.int64); t_in = np.empty(cap, np.int64); t_out = np.empty(cap, np.int64)
    t_dir = np.empty(cap, np.int8); t_pin = np.empty(cap); t_pout = np.empty(cap); t_why = np.empty(cap, np.int8)
    t_cls = np.empty(cap, np.int8); t_risk = np.empty(cap); t_add = np.zeros(cap, np.bool_)
    t_apx = np.full(cap, np.nan); t_pnl = np.empty(cap); t_mae = np.empty(cap)
    tick, fee, a_tick, a_fee = cfg[K_TICK_USD], cfg[K_FEE_USD], cfg[K_ADD_TICK_USD], cfg[K_ADD_FEE_USD]
    addon_on = cfg[K_ADDON] > 0
    n = 0
    # pending order
    pend = False
    p_d = 0; p_lvl = 0.0; p_stop = 0.0; p_tgt = 0.0; p_cls = 0; p_te = False; p_ts = False
    p_c3 = 0; p_last = 0
    # open position
    pos = False
    d = 0; fill = 0.0; stop = 0.0; tgt = 0.0; e_row = 0; cls = 0; risk = 0.0
    pos_con = -1
    a_lvl = 0.0; a_wait = False; a_in = False; a_fill = 0.0; worst_usd = 0.0
    # daily stop
    cur_day = -1; day_real = 0.0
    last_j = 0
    for i in range(nb):
        if fs[i] < 0:  # warm-up history (not front month): orders die, positions cannot be open
            pend = False
            continue
        if pos and contract[i] != pos_con:  # flat/cutoff should have closed it: safety net
            px = c[last_j] - d * slip
            pnl = d * (px - fill) * tick - fee
            if a_in:
                pnl += d * (px - a_fill) * a_tick - a_fee
            n = _rec(n, t_day, t_in, t_out, t_dir, t_pin, t_pout, t_why, t_cls, t_risk, t_add, t_apx, t_pnl,
                     t_mae, cur_day, e_row, last_j, d, fill, px, EXIT_FALLBACK, cls, risk, a_in,
                     a_fill if a_in else np.nan, pnl, max(worst_usd, -pnl))
            day_real += pnl
            pos = False
        if bar_day[i] != cur_day:  # front bars are in time order; warm-up bars never reach here
            cur_day = bar_day[i]
            day_real = 0.0
        if pend and not _next(i, fs, bucket, bar_day, contract):
            pend = False  # gap, new day or new contract: the order is gone
        for j in range(fs[i], fe[i]):
            last_j = j
            if pend:
                if tmin[j] >= flat[j] or cut[j]:
                    pend = False
                    continue
                hit = (p_d == 1 and h[j] >= p_lvl) or (p_d == -1 and l[j] <= p_lvl)
                if not hit:
                    continue
                pend = False
                d = p_d; stop = p_stop; tgt = p_tgt; cls = p_cls; e_row = j; pos_con = contract[i]
                fill = stop_order_fill(o[j], p_lvl, d, slip)
                risk = d * (p_lvl - stop)
                a_wait = addon_on and d * (tgt - fill) > cfg[K_ADDON_OFFSET]
                a_lvl = tgt - d * cfg[K_ADDON_OFFSET]
                a_in = False
                stopped, mae = stop_entry_minute(h[j], l[j], d, fill, stop, slip, pessimistic)
                worst_usd = mae * tick + fee
                if stopped:
                    px = stop - d * slip
                    pnl = d * (px - fill) * tick - fee
                    n = _rec(n, t_day, t_in, t_out, t_dir, t_pin, t_pout, t_why, t_cls, t_risk, t_add, t_apx,
                             t_pnl, t_mae, cur_day, e_row, j, d, fill, px, EXIT_STOP, cls, risk, False, np.nan,
                             pnl, max(worst_usd, -pnl))
                    day_real += pnl
                else:
                    pos = True
                continue
            if not pos:
                continue
            why, px, _ = hold_minute(o[j], h[j], l[j], tmin[j], cut[j], flat[j], True, d, fill, stop, tgt,
                                     True, 0.0, slip, pessimistic)
            a_touch = a_wait and ((d == 1 and h[j] >= a_lvl) or (d == -1 and l[j] <= a_lvl))
            if why == 0:
                if a_touch:
                    a_in = True; a_wait = False
                    a_fill = stop_order_fill(o[j], a_lvl, d, slip)
                wp = l[j] if d == 1 else h[j]
            else:
                if a_touch and why == EXIT_STOP and pessimistic and d * (o[j] - stop) > 0:
                    a_in = True  # not a gap stop: assume it reached the add-on first, then the stop
                    a_fill = stop_order_fill(o[j], a_lvl, d, slip)
                elif a_touch and why == EXIT_TARGET and not pessimistic:
                    a_in = True
                    a_fill = stop_order_fill(o[j], a_lvl, d, slip)
                wp = (l[j] if d == 1 else h[j]) if why == EXIT_TARGET else px
            open_loss = d * (fill - wp) * tick + fee + (d * (a_fill - wp) * a_tick + a_fee if a_in else 0.0)
            if open_loss > worst_usd:
                worst_usd = open_loss
            if why != 0:
                pnl = d * (px - fill) * tick - fee
                if a_in:
                    pnl += d * (px - a_fill) * a_tick - a_fee
                n = _rec(n, t_day, t_in, t_out, t_dir, t_pin, t_pout, t_why, t_cls, t_risk, t_add, t_apx,
                         t_pnl, t_mae, cur_day, e_row, j, d, fill, px, why, cls, risk, a_in,
                         a_fill if a_in else np.nan, pnl, max(worst_usd, -pnl))
                day_real += pnl
                pos = False
        # order bookkeeping at the close of bar i
        if pend:
            if i == p_c3 and cfg[K_CANCEL_TOUCH] > 0 and (
                    (p_te and _touch(low[i], high[i], ema[i], cfg[K_TOUCH_TOL]))
                    or (p_ts and _touch(low[i], high[i], sma[i], cfg[K_TOUCH_TOL]))):
                pend = False
            elif i >= p_last:
                pend = False
        if pend or pos or day_real <= -cfg[K_DAILY_STOP]:
            continue
        sd, lvl, st, tg, sc, te, ts_ = setup(cfg, i, fs, bucket, bar_day, contract, high, low, close,
                                             ema, sma, atr14, atr100, vwap, ok)
        if sd != 0:
            pend = True
            p_d = sd; p_lvl = lvl; p_stop = st; p_tgt = tg; p_cls = sc; p_te = te; p_ts = ts_
            p_c3 = i + 1; p_last = i + int(cfg[K_EXPIRY_BARS])
    if pos:  # data ended while holding (cannot happen with real flat times)
        px = c[last_j] - d * slip
        pnl = d * (px - fill) * tick - fee
        if a_in:
            pnl += d * (px - a_fill) * a_tick - a_fee
        n = _rec(n, t_day, t_in, t_out, t_dir, t_pin, t_pout, t_why, t_cls, t_risk, t_add, t_apx, t_pnl, t_mae,
                 cur_day, e_row, last_j, d, fill, px, EXIT_FALLBACK, cls, risk, a_in,
                 a_fill if a_in else np.nan, pnl, max(worst_usd, -pnl))
    return (t_day[:n], t_in[:n], t_out[:n], t_dir[:n], t_pin[:n], t_pout[:n], t_why[:n], t_cls[:n],
            t_risk[:n], t_add[:n], t_apx[:n], t_pnl[:n], t_mae[:n])


@njit(cache=True)
def _rec(n, t_day, t_in, t_out, t_dir, t_pin, t_pout, t_why, t_cls, t_risk, t_add, t_apx, t_pnl, t_mae,
         day, e_row, j, d, fill, px, why, cls, risk, a_in, a_px, pnl, mae):
    t_day[n] = day; t_in[n] = e_row; t_out[n] = j; t_dir[n] = d; t_pin[n] = fill; t_pout[n] = px
    t_why[n] = why; t_cls[n] = cls; t_risk[n] = risk; t_add[n] = a_in; t_apx[n] = a_px
    t_pnl[n] = pnl; t_mae[n] = mae
    return n + 1


TRADE_COLS = ["day", "in_row", "out_row", "dir", "px_in", "px_out", "why", "cls", "risk", "addon", "addon_px",
              "pnl_usd", "mae_usd"]

