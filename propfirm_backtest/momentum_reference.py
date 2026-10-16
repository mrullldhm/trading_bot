"""Slow plain-Python Momentum Pullback simulator, written from the rules in momentum_engine's docstring.
Used only to check the numba engine trade by trade. Shares the prepared inputs (Market: bars, flat
times, EIA and session masks) but none of the chain, order or fill code."""

import math

from . import momentum_engine as M
from . import propsim as P
from .orb_engine import EXIT_CUTOFF, EXIT_FALLBACK, EXIT_STOP, EXIT_TARGET, EXIT_TIME


class _Order:
    def __init__(self, d, level, stop, base, last):
        self.d, self.level, self.stop, self.base, self.last = d, level, stop, base, last


def trades(mk, cfg, n_days=None, slip=1.0, pessimistic=True):
    """Same output tuple as Market.trades, as Python lists."""
    n_days = len(mk.days) if n_days is None else n_days
    b = mk.bars
    f = mk.f
    tf = int(cfg[M.C_TF])
    min_t, window, sbuf = int(cfg[M.C_MIN_TREND]), int(cfg[M.C_WINDOW]), cfg[M.C_STOP_BUF]
    r_mult = cfg[M.C_R10] / 10
    max_loss = cfg[M.C_MAX_RISK_BP] / 10_000 * M.ACCOUNT_USD
    min_risk = max(1, cfg[M.C_MIN_RISK])
    sess = M.SESSION_NAMES[int(cfg[M.C_SESSION])]
    sk = M.SESSION_NAMES.index(sess)
    allowed = {M.BOTH: (1, -1), M.LONG: (1,), M.SHORT: (-1,)}[int(cfg[M.C_DIR])]
    out = []
    chain = None  # dict(d, m_body, n_t)
    order = None
    pos = None  # dict(d, fill, stop, tgt, row, day, mae, con)
    last_row = None
    lo, hi = mk.off[tf], mk.off[tf + 1]

    def close(p, row, px, why, mae):
        out.append((p["day"], p["row"], row, p["d"], p["fill"], px, mae, why))

    for i in range(lo, hi):
        if b["fs"][i] < 0 or b["day"][i] < 0:
            chain, order = None, None
            continue
        if b["day"][i] >= n_days:
            break
        if pos and b["contract"][i] != pos["con"]:
            px = f.close[last_row] - pos["d"] * slip
            close(pos, last_row, px, EXIT_FALLBACK, max(pos["mae"], -pos["d"] * (px - pos["fill"])))
            pos = None
        prev_ok = (i > lo and b["fs"][i - 1] >= 0 and b["contract"][i] == b["contract"][i - 1]
                   and b["day"][i] == b["day"][i - 1] and b["bucket"][i] == b["bucket"][i - 1] + 1)
        if not prev_ok:
            chain, order = None, None
        for j in range(b["fs"][i], b["fe"][i]):
            last_row = j
            op, hp, lp = f.open[j], f.high[j], f.low[j]
            if order:
                if (f.tmin[j] >= mk.flat[j] or f.cut[j] or mk.blocked[j] or not mk.sess[sk, j]):
                    order = None
                    continue
                d = order.d
                reached = hp >= order.level if d == 1 else lp <= order.level
                if not reached:
                    if (d == 1 and lp < order.base) or (d == -1 and hp > order.base):
                        order = None
                    continue
                gapped = (op >= order.level) if d == 1 else (op <= order.level)
                fill = (op if gapped else order.level) + d * slip
                stop = order.stop
                order = None
                risk = d * (fill - stop)
                tgt = fill + d * math.ceil(r_mult * risk - 1e-9)
                worst = lp if d == 1 else hp
                mae = max(0.0, d * (fill - worst))
                touched = lp <= stop if d == 1 else hp >= stop
                if pessimistic and touched:
                    out.append((b["day"][i], j, j, d, fill, stop - d * slip, d * (fill - stop) + slip, EXIT_STOP))
                    continue
                if not pessimistic:
                    mae = min(mae, d * (fill - stop) + slip)
                pos = dict(d=d, fill=fill, stop=stop, tgt=tgt, row=j, day=b["day"][i], mae=mae,
                           con=b["contract"][i])
                continue
            if not pos:
                continue
            d, fill, stop, tgt = pos["d"], pos["fill"], pos["stop"], pos["tgt"]
            if f.tmin[j] >= mk.flat[j] or f.cut[j]:
                why = EXIT_CUTOFF if (f.cut[j] and f.tmin[j] < mk.flat[j]) else EXIT_TIME
                close(pos, j, op - d * slip, why, pos["mae"])
                pos = None
                continue
            if d * (op - stop) <= 0:
                close(pos, j, op - d * slip, EXIT_STOP, max(pos["mae"], d * (fill - op)))
                pos = None
                continue
            if d * (op - tgt) >= 1:
                close(pos, j, tgt, EXIT_TARGET, pos["mae"])
                pos = None
                continue
            stop_hit = lp <= stop if d == 1 else hp >= stop
            tgt_hit = hp >= tgt + 1 if d == 1 else lp <= tgt - 1
            worst = lp if d == 1 else hp
            if stop_hit and (pessimistic or not tgt_hit):
                close(pos, j, stop - d * slip, EXIT_STOP, max(pos["mae"], d * (fill - stop)))
                pos = None
            elif tgt_hit:
                close(pos, j, tgt, EXIT_TARGET, max(pos["mae"], d * (fill - worst)))
                pos = None
            else:
                pos["mae"] = max(pos["mae"], d * (fill - worst))

        # bar closed
        if order and i >= order.last:
            order = None
        o, h, l, c = b["o"][i], b["h"][i], b["l"][i], b["c"][i]
        body = abs(c - o)
        if chain:
            d = chain["d"]
            holds = l >= b["l"][i - 1] if d == 1 else h <= b["h"][i - 1]
            if not holds:
                chain, order = None, None
            elif body * 100 <= cfg[M.C_S100] * chain["m_body"] and chain["n_t"] >= min_t:
                order = None
                if pos is None and d in allowed:
                    level = (max(o, c) + 1) if d == 1 else (min(o, c) - 1)
                    stop = (l - sbuf) if d == 1 else (h + sbuf)
                    risk = abs(level - stop)
                    if risk >= min_risk and (risk + M.FILTER_SLIP) * P.TICK_USD + P.FEE_USD <= max_loss:
                        order = _Order(d, level, stop, l if d == 1 else h, i + window)
            elif (c - o) * d > 0 and chain["n_t"] < M.MAX_TREND:
                chain["n_t"] += 1
            else:
                chain, order = None, None
        if chain is None and b["ok"][i] and body > 0 and body * 10 >= cfg[M.C_K10] * b["avg"][i] \
                and ((h - l) - body) * 100 <= cfg[M.C_W100] * (h - l):  # exact: prices are whole ticks
            chain = dict(d=1 if c > o else -1, m_body=body, n_t=0)
    if pos:
        px = f.close[last_row] - pos["d"] * slip
        close(pos, last_row, px, EXIT_FALLBACK, max(pos["mae"], -pos["d"] * (px - pos["fill"])))
    return out
