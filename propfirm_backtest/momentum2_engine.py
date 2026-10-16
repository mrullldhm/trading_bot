"""Pine "1-Minute Momentum Strategy" simulator (numba): 5-bar pattern, market entry at the next bar's open.

Port of a TradingView Pine v6 strategy (strategy 8). Bars: clock-aligned ET bars of each timeframe
(momentum_engine.Market, its average-body columns unused), front-month CL only. Prices in ticks.

Signal at the close of bar t (long; short is the mirror: highs for lows, bearish for bullish):
- Bars t-4..t contiguous: same contract, same trading day, consecutive buckets (project rule; Pine has none).
- Momentum: |c-o|[t-3] > mult x |c-o|[t-4]. Pine ignores its colour (mom_dir=any); mom_dir=with needs
  bar t-3 bullish.
- Trend: c[t-2] > c[t-3], c[t-1] > c[t-2], l[t-2] >= l[t-3], l[t-1] >= l[t-2].
- Bar t: range > 0, |c-o| / range x 100 < body_pct (Pine's default 0.3 means 0.3% of the range), c > o,
  c > o[t-1].
- Bracket in absolute prices from bar t, never rebased to the fill: stop = l[t] - stop_buf,
  target = c[t] + ceil(rr x (c[t] - stop)). Signals with c[t] - stop < min_risk are dropped (project filter).

Orders (TradingView broker emulator, pyramiding 1, process_orders_on_close off):
- Flat at t's close: market entry at the open of the next bar of the series, if it is the same contract and
  trading day (bucket gaps allowed: "next available bar"). Dropped if that minute is past flat time, roll
  cutoff, in an EIA block or outside the session (project rules).
- In a trade, same direction: mgmt=tv replaces the bracket with bar t's (live from the next bar on;
  bar t itself ran under the old one); mgmt=ignore does nothing.
- In a trade, opposite direction: mgmt=tv reverses at the next bar's open (old bracket live until then;
  a gap through the old stop/target at that open exits the old trade as stop/target, else 'reverse').
  If that minute is not allowed, the reversal is dropped and the old trade keeps its bracket.
  mgmt=ignore does nothing.

Fills (fill=project, the grid): market fill = open + slip; then orb_engine.hold_minute minute by minute
(stop gapped -> open - slip; stop beats target in one minute; target needs a 1-tick trade-through;
flat 16:09 ET / roll cutoff). fill=tv (Pine-parity rows only, run with slip 0): one step per chart bar,
TradingView's path (open nearer the high: open-high-low-close, else open-low-high-close), touch fills,
both stop and target gapped through fill at the open; flat/cutoff checked at each bar's open.
"""

import numpy as np
from numba import njit, prange

from . import momentum_engine as ME
from . import orb_engine as E
from . import propsim as P
from .orb_engine import EXIT_FALLBACK, EXIT_STOP, EXIT_TARGET, hold_minute, trade_pnl

TIMEFRAMES = ME.TIMEFRAMES
SESSION_NAMES = ME.SESSION_NAMES
BOTH, LONG, SHORT = ME.BOTH, ME.LONG, ME.SHORT
MGMT_NAMES = ["tv", "ignore"]
FILL_NAMES = ["project", "tv"]
MOM_DIR_NAMES = ["any", "with"]
EXIT_REVERSE = 6
E.EXIT_NAMES.setdefault(EXIT_REVERSE, "reverse")  # runtime only: orb_engine.py is in frozen hashes

# config columns (int64 matrix): one row per config
(C_TF, C_MULT10, C_BODY10, C_R10, C_MOM_DIR, C_MGMT, C_STOP_BUF, C_MIN_RISK, C_SESSION, C_DIR, C_FILL) = range(11)
N_CFG_COLS = 11


def config(tf=1, mult=1.5, body_pct=0.3, rr=2.0, mom_dir="any", mgmt="tv", stop_buf=0, min_risk=0,
           session="all", direction="both", fill="project") -> np.ndarray:
    """One engine config row from readable values (defaults = the Pine script's inputs)."""
    return np.array([TIMEFRAMES.index(tf), round(mult * 10), round(body_pct * 10), round(rr * 10),
                     MOM_DIR_NAMES.index(mom_dir), MGMT_NAMES.index(mgmt), stop_buf, min_risk,
                     SESSION_NAMES.index(session), {"both": BOTH, "long": LONG, "short": SHORT}[direction],
                     FILL_NAMES.index(fill)], dtype=np.int64)


class Market(ME.Market):
    """momentum_engine.Market (same bars, flat times, EIA and session masks) with this engine's trades."""

    def trades(self, cfg, n_days=None, slip=1.0, pessimistic=True):
        n_days = len(self.days) if n_days is None else n_days
        t = run_trades(np.asarray(cfg, np.int64), n_days, self.bar_args(), self.minute_args(), float(slip),
                       pessimistic)
        if len(t[1]) and (self.f.contract[t[1]] != self.f.contract[t[2]]).any():  # roll-safety invariant
            raise RuntimeError("trade entry and exit on different contracts: engine bug")
        return t


# --- engine ----------------------------------------------------------------------------------------

@njit(cache=True)
def _signal(i, d, bo, bh, bl, bc, mult10, body10, mom_with):
    """Pine's enter_long (d=1) / enter_short (d=-1) at the close of bar i (bars i-4..i contiguous)."""
    o_, h_, l_, c_ = bo[i], bh[i], bl[i], bc[i]
    rng = h_ - l_
    if rng <= 0 or abs(c_ - o_) * 1000.0 >= body10 * rng:  # body % < body_pct, exact on whole ticks
        return False
    if d * (c_ - o_) <= 0 or d * (c_ - bo[i - 1]) <= 0:
        return False
    if abs(bc[i - 3] - bo[i - 3]) * 10.0 <= mult10 * abs(bc[i - 4] - bo[i - 4]):
        return False
    if mom_with and d * (bc[i - 3] - bo[i - 3]) <= 0:
        return False
    if d == 1:
        return bc[i - 2] > bc[i - 3] and bc[i - 1] > bc[i - 2] and bl[i - 2] >= bl[i - 3] and bl[i - 1] >= bl[i - 2]
    return bc[i - 2] < bc[i - 3] and bc[i - 1] < bc[i - 2] and bh[i - 2] <= bh[i - 3] and bh[i - 1] <= bh[i - 2]


@njit(cache=True)
def _tv_bar(o_, h_, l_, d, stop, tgt):
    """TradingView chart-bar exit: (reason or 0, price). Gaps fill at the open; touch fills; OHLC path."""
    if d * (o_ - stop) <= 0:
        return EXIT_STOP, o_
    if d * (o_ - tgt) >= 0:
        return EXIT_TARGET, o_
    s_hit = (d == 1 and l_ <= stop) or (d == -1 and h_ >= stop)
    t_hit = (d == 1 and h_ >= tgt) or (d == -1 and l_ <= tgt)
    high_first = (h_ - o_) < (o_ - l_)
    tgt_first = high_first if d == 1 else not high_first
    if t_hit and (tgt_first or not s_hit):
        return EXIT_TARGET, tgt
    if s_hit:
        return EXIT_STOP, stop
    return 0, 0.0


@njit(cache=True)
def simulate(cfg, n_days, bar_args, minute_args, slip, pessimistic,
             t_day, t_in, t_out, t_dir, t_pin, t_pout, t_mae, t_why):
    """Writes trades (time order) into the t_* buffers. Returns the count, or -1 if the buffers are full."""
    off, fs, fe, bucket, day, contract, bo, bh, bl, bc, _avg, _ok = bar_args
    tmin, o, h, l, c, flat, cut, blocked, sess = minute_args
    cap = len(t_day)
    tf = cfg[C_TF]
    mult10, body10, r_mult = float(cfg[C_MULT10]), float(cfg[C_BODY10]), cfg[C_R10] / 10.0
    mom_with = cfg[C_MOM_DIR] == 1
    tv_mgmt = cfg[C_MGMT] == 0
    tv_fill = cfg[C_FILL] == 1
    sbuf, min_risk = float(cfg[C_STOP_BUF]), float(cfg[C_MIN_RISK])
    sk = cfg[C_SESSION]
    dirpol = cfg[C_DIR]
    lo = off[tf]
    n = 0
    run = 0  # contiguous bars ending at i
    # pending market order for the next bar: entry (flat) or reversal (in a trade)
    pend = False; p_d = 0; p_stop = 0.0; p_tgt = 0.0; p_con = -1; p_day = -1
    # position
    pos = False; d = 0; fill = 0.0; stop = 0.0; tgt = 0.0; e_row = 0; e_day = 0; mae = 0.0; pos_con = -1
    last_j = 0
    for i in range(lo, off[tf + 1]):
        if fs[i] < 0 or day[i] < 0:  # warm-up history (not front month): nothing can be open or resting
            run = 0
            pend = False
            continue
        if day[i] >= n_days:
            break
        if pos and (contract[i] != pos_con or day[i] != e_day):  # flat/cutoff should have closed it: safety net
            if n >= cap:
                return -1
            px = c[last_j] - d * slip
            n = _rec(n, t_day, t_in, t_out, t_dir, t_pin, t_pout, t_mae, t_why, e_day, e_row, last_j, d, fill, px,
                     max(mae, -d * (px - fill)), EXIT_FALLBACK)
            pos = False
        run = run + 1 if (i > lo and fs[i - 1] >= 0 and contract[i] == contract[i - 1] and day[i] == day[i - 1]
                          and bucket[i] == bucket[i - 1] + 1) else 1
        # --- the pending order fills at this bar's first minute (or is dropped) ----------------------
        if pend:
            pend = False
            j = fs[i]
            if (contract[i] == p_con and day[i] == p_day and tmin[j] < flat[j] and not cut[j] and not blocked[j]
                    and sess[sk, j]):
                if pos:  # reversal: the old trade leaves at this open
                    if d * (o[j] - stop) <= 0:
                        why = EXIT_STOP; px = o[j] - d * slip
                    elif d * (o[j] - tgt) >= (0.0 if tv_fill else 1.0):
                        why = EXIT_TARGET; px = o[j] if tv_fill else tgt
                    else:
                        why = EXIT_REVERSE; px = o[j] - d * slip
                    if n >= cap:
                        return -1
                    n = _rec(n, t_day, t_in, t_out, t_dir, t_pin, t_pout, t_mae, t_why, e_day, e_row, j, d, fill,
                             px, max(mae, -d * (px - fill)), why)
                pos = True
                d = p_d; stop = p_stop; tgt = p_tgt; e_row = j; e_day = day[i]; pos_con = contract[i]
                fill = o[j] + d * slip
                mae = 0.0
        # --- bar i under the active bracket -------------------------------------------------------
        if pos and tv_fill:
            j = fs[i]
            last_j = fe[i] - 1
            if tmin[j] >= flat[j] or cut[j]:
                if j != e_row:  # an entry at this open was already checked against flat/cutoff
                    why = E.EXIT_CUTOFF if (cut[j] and tmin[j] < flat[j]) else E.EXIT_TIME
                    if n >= cap:
                        return -1
                    n = _rec(n, t_day, t_in, t_out, t_dir, t_pin, t_pout, t_mae, t_why, e_day, e_row, j, d, fill,
                             o[j] - d * slip, mae, why)
                    pos = False
            if pos:
                why, px = _tv_bar(bo[i], bh[i], bl[i], d, stop, tgt)
                worst = bl[i] if d == 1 else bh[i]
                if why != 0:
                    if n >= cap:
                        return -1
                    if why == EXIT_STOP:
                        worst = px
                    elif px == bo[i] or ((bh[i] - bo[i]) < (bo[i] - bl[i])) == (d == 1):
                        worst = bo[i]  # target at the open, or reached on the first leg: no adverse leg before it
                    n = _rec(n, t_day, t_in, t_out, t_dir, t_pin, t_pout, t_mae, t_why, e_day, e_row, last_j, d,
                             fill, px - d * slip if why == EXIT_STOP else px, max(mae, d * (fill - worst)), why)
                    pos = False
                else:
                    mae = max(mae, d * (fill - worst))
        elif pos:
            for j in range(fs[i], fe[i]):
                last_j = j
                why, px, mae = hold_minute(o[j], h[j], l[j], tmin[j], cut[j], flat[j], True, d, fill, stop, tgt,
                                           True, mae, slip, pessimistic)
                if why != 0:
                    if n >= cap:
                        return -1
                    n = _rec(n, t_day, t_in, t_out, t_dir, t_pin, t_pout, t_mae, t_why, e_day, e_row, j, d, fill,
                             px, mae, why)
                    pos = False
                    break
        else:
            last_j = fe[i] - 1
        # --- bar i closed: the signal ---------------------------------------------------------------
        if run < 5:
            continue
        for dd in (1, -1):
            if not (dirpol == BOTH or (dirpol == LONG and dd == 1) or (dirpol == SHORT and dd == -1)):
                continue
            if not _signal(i, dd, bo, bh, bl, bc, mult10, body10, mom_with):
                continue
            st = (bl[i] - sbuf) if dd == 1 else (bh[i] + sbuf)
            risk = dd * (bc[i] - st)
            if risk < max(1.0, min_risk):
                continue
            tg = bc[i] + dd * np.ceil(r_mult * risk - 1e-9)
            if not pos:
                pend = True
            elif dd == d:
                if tv_mgmt:
                    stop = st; tgt = tg
                continue
            elif tv_mgmt:
                pend = True
            else:
                continue
            p_d = dd; p_stop = st; p_tgt = tg; p_con = contract[i]; p_day = day[i]
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


# --- many configs (same outputs as momentum_engine.grid_kernel / daily_kernel) -------------------
# Copies of momentum_engine's kernels (numba cannot take run_trades as an argument); compiled fresh each run.

@njit(cache=False, parallel=True)
def grid_kernel(cfgs, n_days, year_of_day, n_years, fold_ends, hash_w, bar_args, minute_args, slip, pessimistic,
                u, u_wf, block, score):
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
