"""Momentum Pullback simulator (numba): momentum candle, trend candles, small-body candle, break of its body.

Bars: clock-aligned ET bars of each timeframe (bars.build_bars), front-month CL only. Prices in ticks.
A chain lives inside one contract and one trading day, on consecutive buckets; a missing bar,
a new day or a new contract resets it (and cancels a resting order).

Rules (long; short is the mirror: highs for lows, bearish for bullish), decided at each bar's close:
- Momentum M: close > open; body >= k x mean |body| of the previous AVG_LEN bars of the same contract;
  upper + lower wick <= w x range.
- Trend T (after M): close > open and low >= previous bar's low. At most MAX_TREND T bars.
- Small S: body <= s x M's body, any colour, low >= previous bar's low, after >= min_trend T bars.
  Tested BEFORE T: a small bullish bar is an S once min_trend is reached (before that it counts as T).
- Anything else (low < previous low, an opposing bar that is not an S, more than MAX_TREND T bars)
  ends the chain; that same bar may start a new chain as M. S is never M of its own setup.
- Order at S's close: buy stop at max(S.open, S.close) + 1 tick, protective stop S.low - stop_buf.
  Placed only when flat, in an allowed direction, and the planned risk passes the filter:
  min_risk <= level - stop and (level - stop + 2 slippage ticks) x $10 + fee <= max_risk_bp / 1e4 x $50,000.
  Lives for `window` bars after S. A later S of the same chain replaces it (after that bar was
  scanned with the old order; a new order never fills inside its own bar). A T bar keeps it.
- Minute by minute while the order rests: flat time / roll cutoff / EIA block / outside the session
  -> cancelled; price reaches the level -> filled (stop_order_fill: gap = open + slip); else price
  trades below S.low -> cancelled. Both in one minute = filled (then stopped if the stop was touched).
- Risk R = fill - stop (gaps included); target = fill + ceil(R_mult x R), needs a 1-tick trade-through.
- Exits via orb_engine.hold_minute: stop, target, flat 16:09 ET (12:55 short days, expiry), roll cutoff.
  Pessimistic: stop touched in the entry minute = stopped; stop wins over target in one minute.
- One position at a time. No daily stop inside the engine (Topstep's DLL is a Combine-level rule).
"""

import numpy as np
import pandas as pd
from numba import njit, prange

from . import bars as B
from . import orb_engine as E
from . import propsim as P
from .orb_engine import (EXIT_FALLBACK, EXIT_STOP, hold_minute, stop_entry_minute, stop_order_fill,
                         trade_pnl)

TIMEFRAMES = [1, 2, 3, 5, 15]
AVG_LEN = 20
MAX_TREND = 5
ACCOUNT_USD = 50_000.0
FILTER_SLIP = 2.0  # ticks (1 per side) assumed by the risk filter, independent of the simulated slippage
SESSION_NAMES = ["all", "london", "newyork"]
BOTH, LONG, SHORT = 0, 1, 2

# config columns (int64 matrix): one row per config
(C_TF, C_K10, C_W100, C_MIN_TREND, C_S100, C_WINDOW, C_STOP_BUF, C_R10, C_MAX_RISK_BP, C_MIN_RISK,
 C_SESSION, C_DIR) = range(12)
N_CFG_COLS = 12


def config(tf=1, k=2.0, w=0.35, min_trend=1, s=0.4, window=1, stop_buf=0, r=2.0, max_risk_pct=2.0,
           min_risk=0, session="all", direction="both") -> np.ndarray:
    """One engine config row from readable values."""
    return np.array([TIMEFRAMES.index(tf), round(k * 10), round(w * 100), min_trend, round(s * 100), window,
                     stop_buf, round(r * 10), round(max_risk_pct * 100), min_risk, SESSION_NAMES.index(session),
                     {"both": BOTH, "long": LONG, "short": SHORT}[direction]], dtype=np.int64)


# --- prepared inputs -------------------------------------------------------------------------------

def avg_body(o, c, contract, length=AVG_LEN):
    """Mean |close - open| of the previous `length` bars of the same contract (bar itself excluded).
    Returns (avg, valid)."""
    body = np.abs(c - o)
    s = pd.Series(body)
    grp = pd.Series(contract)
    prev = s.groupby(grp).shift(1)
    avg = prev.groupby(grp).rolling(length, min_periods=length).mean().reset_index(level=0, drop=True)
    avg = avg.sort_index().to_numpy()
    return np.nan_to_num(avg), np.isfinite(avg)


def session_ok(mod: np.ndarray) -> np.ndarray:
    """(len(SESSION_NAMES), n) entries allowed at this ET minute of day (bars.SESSIONS windows)."""
    out = np.zeros((len(SESSION_NAMES), len(mod)), dtype=np.bool_)
    for k, name in enumerate(SESSION_NAMES):
        a, b = B.SESSIONS[name]
        out[k] = ((mod >= a) & (mod < b)) if a < b else ((mod >= a) | (mod < b))
    return out


class Market:
    """Bars of every timeframe (concatenated, `off` = first row per timeframe) mapped onto front-month
    minutes, plus per-minute flat time, EIA blocks and session masks. Same constructor as orb_engine.Market."""

    def __init__(self, m, days: np.ndarray, eia: pd.DataFrame | None, strict_expiry=False):
        f = E.Front(m, strict_expiry)
        self.f, self.days, self.eia = f, days, eia
        parts = {k: [] for k in ("fs", "fe", "bucket", "day", "contract", "o", "h", "l", "c", "avg", "ok")}
        off = [0]
        trading_day = m.trading_day
        for tf in TIMEFRAMES:
            b = B.build_bars(m, tf)
            tradable = m.front[b.start]  # bars never span a front-month change
            fs = np.full(len(b), -1, np.int64)
            fs[tradable] = np.searchsorted(f.src, b.start[tradable])
            fe = np.where(tradable, fs + (b.end - b.start), -1)
            day = np.full(len(b), -1, np.int64)
            k = np.searchsorted(days, trading_day[b.start[tradable]])
            day[tradable] = np.where(k < len(days), k, -1)
            avg, ok = avg_body(b.open, b.close, b.contract)
            for key, v in (("fs", fs), ("fe", fe), ("bucket", m.ts[b.start] // E.NS_PER_MIN // tf), ("day", day),
                           ("contract", b.contract.astype(np.int64)), ("o", b.open), ("h", b.high), ("l", b.low),
                           ("c", b.close), ("avg", avg), ("ok", ok)):
                parts[key].append(v)
            off.append(off[-1] + len(b))
        self.bars = {k: np.concatenate(v) for k, v in parts.items()}
        self.off = np.array(off, np.int64)
        row_day = np.searchsorted(days, f.trading_day)
        self.flat = E.session_end(f, days)[np.minimum(row_day, len(days) - 1)]
        self.blocked = blocked_rows(f.tmin, row_day, E.eia_blocks(eia, days))
        self.sess = session_ok(f.mod)

    def bar_args(self):
        b = self.bars
        return (self.off, b["fs"], b["fe"], b["bucket"], b["day"], b["contract"], b["o"], b["h"], b["l"], b["c"],
                b["avg"], b["ok"])

    def minute_args(self):
        f = self.f
        return (f.tmin, f.open, f.high, f.low, f.close, self.flat, f.cut, self.blocked, self.sess)

    def trades(self, cfg, n_days=None, slip=1.0, pessimistic=True):
        """All trades on days [0, n_days): (day, in_row, out_row, dir, px_in, px_out, mae_ticks, why),
        rows index the front-month minutes (orb_engine.run_trades format)."""
        n_days = len(self.days) if n_days is None else n_days
        t = run_trades(np.asarray(cfg, np.int64), n_days, self.bar_args(), self.minute_args(), float(slip),
                       pessimistic)
        if len(t[1]) and (self.f.contract[t[1]] != self.f.contract[t[2]]).any():  # roll-safety invariant
            raise RuntimeError("trade entry and exit on different contracts: engine bug")
        return t


def blocked_rows(tmin, row_day, blocks) -> np.ndarray:
    """Per front minute: inside an EIA block of its trading day."""
    out = np.zeros(len(tmin), dtype=np.bool_)
    ok = row_day < len(blocks)
    for k in range(blocks.shape[1]):
        a = np.full(len(tmin), -1, np.int64)
        z = np.full(len(tmin), -1, np.int64)
        a[ok], z[ok] = blocks[row_day[ok], k, 0], blocks[row_day[ok], k, 1]
        out |= (a >= 0) & (tmin >= a) & (tmin < z)
    return out


# --- engine ----------------------------------------------------------------------------------------

@njit(cache=True)
def _contiguous(i, lo, fs, bucket, day, contract):
    """Bar i directly follows bar i-1 inside one timeframe block: both tradable, same contract and day."""
    return (i > lo and fs[i] >= 0 and fs[i - 1] >= 0 and contract[i] == contract[i - 1]
            and day[i] == day[i - 1] and bucket[i] == bucket[i - 1] + 1)


@njit(cache=True)
def _is_momentum(o, h, l, c, avg, ok, k10, w100):
    body = abs(c - o)
    rng = h - l
    return ok and body > 0 and body * 10.0 >= k10 * avg and (rng - body) * 100.0 <= w100 * rng


@njit(cache=True)
def simulate(cfg, n_days, bar_args, minute_args, slip, pessimistic,
             t_day, t_in, t_out, t_dir, t_pin, t_pout, t_mae, t_why):
    """Writes trades (time order) into the t_* buffers. Returns the count, or -1 if the buffers are full."""
    off, fs, fe, bucket, day, contract, bo, bh, bl, bc, avg, ok = bar_args
    tmin, o, h, l, c, flat, cut, blocked, sess = minute_args
    cap = len(t_day)
    tf = cfg[C_TF]
    k10, w100, s100 = float(cfg[C_K10]), float(cfg[C_W100]), float(cfg[C_S100])
    min_t, window, sbuf = cfg[C_MIN_TREND], cfg[C_WINDOW], float(cfg[C_STOP_BUF])
    r_mult = cfg[C_R10] / 10.0
    max_loss = cfg[C_MAX_RISK_BP] / 1e4 * ACCOUNT_USD
    min_risk = max(1.0, float(cfg[C_MIN_RISK]))
    sk = cfg[C_SESSION]
    dirpol = cfg[C_DIR]
    n = 0
    # chain
    ch = 0; m_body = 0.0; n_t = 0
    # resting order
    pend = False; p_d = 0; p_lvl = 0.0; p_stop = 0.0; p_s_ext = 0.0; p_last = 0
    # position
    pos = False; d = 0; fill = 0.0; stop = 0.0; tgt = 0.0; e_row = 0; e_day = 0; mae = 0.0; pos_con = -1
    last_j = 0
    for i in range(off[tf], off[tf + 1]):
        if fs[i] < 0 or day[i] < 0:  # warm-up history (not front month): nothing can be open or resting
            ch = 0
            pend = False
            continue
        if day[i] >= n_days:
            break
        if pos and contract[i] != pos_con:  # flat/cutoff should have closed it: safety net
            if n >= cap:
                return -1
            px = c[last_j] - d * slip
            n = _rec(n, t_day, t_in, t_out, t_dir, t_pin, t_pout, t_mae, t_why, e_day, e_row, last_j, d, fill, px,
                     max(mae, -d * (px - fill)), EXIT_FALLBACK)
            pos = False
        if not _contiguous(i, off[tf], fs, bucket, day, contract):
            ch = 0
            pend = False
        # --- minutes of bar i: the resting order, then the open position --------------------------
        for j in range(fs[i], fe[i]):
            last_j = j
            if pend:
                if tmin[j] >= flat[j] or cut[j] or blocked[j] or not sess[sk, j]:
                    pend = False
                    continue
                hit = (p_d == 1 and h[j] >= p_lvl) or (p_d == -1 and l[j] <= p_lvl)
                if not hit:
                    if (p_d == 1 and l[j] < p_s_ext) or (p_d == -1 and h[j] > p_s_ext):
                        pend = False  # the small candle's base broke before the entry
                    continue
                pend = False
                d = p_d; stop = p_stop; e_row = j; e_day = day[i]; pos_con = contract[i]
                fill = stop_order_fill(o[j], p_lvl, d, slip)
                risk = d * (fill - stop)
                tgt = fill + d * np.ceil(r_mult * risk - 1e-9)
                stopped, mae = stop_entry_minute(h[j], l[j], d, fill, stop, slip, pessimistic)
                if stopped:
                    if n >= cap:
                        return -1
                    n = _rec(n, t_day, t_in, t_out, t_dir, t_pin, t_pout, t_mae, t_why, e_day, e_row, j, d, fill,
                             stop - d * slip, mae, EXIT_STOP)
                else:
                    pos = True
                continue
            if not pos:
                continue
            why, px, mae = hold_minute(o[j], h[j], l[j], tmin[j], cut[j], flat[j], True, d, fill, stop, tgt,
                                       True, mae, slip, pessimistic)
            if why != 0:
                if n >= cap:
                    return -1
                n = _rec(n, t_day, t_in, t_out, t_dir, t_pin, t_pout, t_mae, t_why, e_day, e_row, j, d, fill, px,
                         mae, why)
                pos = False
        # --- bar i closed: order expiry, then the chain ------------------------------------------
        if pend and i >= p_last:
            pend = False
        o_, h_, l_, c_ = bo[i], bh[i], bl[i], bc[i]
        body = abs(c_ - o_)
        if ch != 0:
            prev_ok = (ch == 1 and l_ >= bl[i - 1]) or (ch == -1 and h_ <= bh[i - 1])
            small = body * 100.0 <= s100 * m_body
            with_trend = ch * (c_ - o_) > 0
            if not prev_ok:
                ch = 0
                pend = False
            elif small and n_t >= min_t:  # S: place or replace the order
                pend = False
                dd = ch
                if not pos and (dirpol == BOTH or (dirpol == LONG and dd == 1) or (dirpol == SHORT and dd == -1)):
                    lvl = (max(o_, c_) + 1.0) if dd == 1 else (min(o_, c_) - 1.0)
                    st = (l_ - sbuf) if dd == 1 else (h_ + sbuf)
                    risk = dd * (lvl - st)
                    if risk >= min_risk and (risk + FILTER_SLIP) * P.TICK_USD + P.FEE_USD <= max_loss:
                        pend = True
                        p_d = dd; p_lvl = lvl; p_stop = st; p_s_ext = l_ if dd == 1 else h_
                        p_last = i + window
            elif with_trend and n_t < MAX_TREND:
                n_t += 1
            else:
                ch = 0
                pend = False
        if ch == 0 and _is_momentum(o_, h_, l_, c_, avg[i], ok[i], k10, w100):
            ch = 1 if c_ > o_ else -1
            m_body = body
            n_t = 0
    if pos:  # data ended while holding (cannot happen with real flat times)
        if n >= cap:
            return -1
        px = c[last_j] - d * slip
        n = _rec(n, t_day, t_in, t_out, t_dir, t_pin, t_pout, t_mae, t_why, e_day, e_row, last_j, d, fill, px,
                 max(mae, -d * (px - fill)), EXIT_FALLBACK)
    return n


@njit(cache=True)
def _rec(n, t_day, t_in, t_out, t_dir, t_pin, t_pout, t_mae, t_why, dy, e_row, j, d, fill, px, mae, why):
    t_day[n] = dy; t_in[n] = e_row; t_out[n] = j; t_dir[n] = d; t_pin[n] = fill; t_pout[n] = px
    t_mae[n] = mae; t_why[n] = why
    return n + 1


@njit(cache=True)
def run_trades(cfg, n_days, bar_args, minute_args, slip, pessimistic):
    """All trades of one config (grows the buffers until they fit)."""
    cap = 4 * n_days + 16
    while True:
        t_day = np.empty(cap, np.int64); t_in = np.empty(cap, np.int64); t_out = np.empty(cap, np.int64)
        t_dir = np.empty(cap, np.int8); t_pin = np.empty(cap); t_pout = np.empty(cap)
        t_mae = np.empty(cap); t_why = np.empty(cap, np.int8)
        k = simulate(cfg, n_days, bar_args, minute_args, slip, pessimistic,
                     t_day, t_in, t_out, t_dir, t_pin, t_pout, t_mae, t_why)
        if k >= 0:
            return t_day[:k], t_in[:k], t_out[:k], t_dir[:k], t_pin[:k], t_pout[:k], t_mae[:k], t_why[:k]
        cap *= 4


# --- many configs (same outputs as orb_engine.grid_kernel / daily_kernel) ------------------------
# These read propsim through orb_engine helpers compiled with cache=False; compiled fresh each run.

@njit(cache=False, parallel=True)
def grid_kernel(cfgs, n_days, year_of_day, n_years, fold_ends, hash_w, bar_args, minute_args, slip, pessimistic,
                u, u_wf, block, score):
    """orb_engine.grid_kernel's metrics for whole-series configs (many trades per day allowed)."""
    n_cfg = cfgs.shape[0]
    n_folds = len(fold_ends)
    met = np.zeros((n_cfg, E.N_M))
    ypnl = np.zeros((n_cfg, n_years))
    ytr = np.zeros((n_cfg, n_years), np.int32)
    ybest = np.zeros((n_cfg, n_years))
    wf = np.zeros((n_cfg, n_folds if score else 0, 2))
    for i in prange(n_cfg):
        t = run_trades(cfgs[i], n_days, bar_args, minute_args, slip, pessimistic)
        pnl = trade_pnl(t[3], t[4], t[5])
        day_pnl, day_low = P.daily_series(t[0], pnl, t[6] * P.TICK_USD + P.FEE_USD, n_days)
        trades = len(pnl); wins = 0; gw = 0.0; gl = 0.0; streak = 0; worst_streak = 0; stops = 0; falls = 0
        for q in range(trades):
            y = year_of_day[t[0][q]]
            ytr[i, y] += 1
            if pnl[q] > 0:
                wins += 1
                gw += pnl[q]
                streak = 0
            else:
                gl -= pnl[q]
                streak += 1
                if streak > worst_streak:
                    worst_streak = streak
            if t[7][q] == EXIT_STOP:
                stops += 1
            elif t[7][q] == EXIT_FALLBACK:
                falls += 1
        for dd in range(n_days):
            y = year_of_day[dd]
            ypnl[i, y] += day_pnl[dd]
            if day_pnl[dd] > ybest[i, y]:
                ybest[i, y] = day_pnl[dd]
        sd = day_pnl.std()
        hsum = 0.0
        for dd in range(n_days):
            hsum += day_pnl[dd] * hash_w[dd]
        met[i, 0] = trades; met[i, 1] = wins; met[i, 2] = gw; met[i, 3] = gl; met[i, 4] = day_pnl.sum()
        met[i, 5] = worst_streak; met[i, 6] = day_pnl.max(); met[i, 7] = P.max_drawdown(day_pnl, day_low)
        met[i, 8] = day_pnl.mean() / sd if sd > 0 else 0.0
        met[i, 9] = stops; met[i, 10] = falls; met[i, 14] = np.round(hsum, 2)
        if score:
            met[i, 11], met[i, 12], met[i, 13] = E._bootstrap(day_pnl, day_low, n_days, u, block)
            for f in range(n_folds):
                p_, _, dd_ = E._bootstrap(day_pnl, day_low, fold_ends[f], u_wf, block)
                wf[i, f, 0] = p_
                wf[i, f, 1] = dd_
    return met, ypnl, ytr, ybest, wf


@njit(cache=False, parallel=True)
def daily_kernel(cfgs, n_days, bar_args, minute_args, slip, pessimistic):
    """Daily P&L and intraday low per config."""
    n_cfg = cfgs.shape[0]
    out_pnl = np.zeros((n_cfg, n_days))
    out_low = np.zeros((n_cfg, n_days))
    for i in prange(n_cfg):
        t = run_trades(cfgs[i], n_days, bar_args, minute_args, slip, pessimistic)
        out_pnl[i], out_low[i] = P.daily_series(t[0], trade_pnl(t[3], t[4], t[5]),
                                                t[6] * P.TICK_USD + P.FEE_USD, n_days)
    return out_pnl, out_low
