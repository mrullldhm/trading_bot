"""Slow plain-Python VWAP Break simulator, written independently of vwap_break_engine from the rules in
its docstring. Used only to check the numba engine trade by trade. Shares the prepared inputs
(bars, indicators, flat times) but none of the setup or fill code."""

import math

from .orb_engine import EXIT_CUTOFF, EXIT_FALLBACK, EXIT_STOP, EXIT_TARGET, EXIT_TIME
from . import vwap_break_engine as V


def _touch(lo, hi, line, tol):
    return lo - tol <= line <= hi + tol


def _setup(mk, cfg, i):
    b = mk.bars
    if i == 0 or mk.fs[i] < 0 or mk.fs[i - 1] < 0:
        return None
    if b.contract[i] != b.contract[i - 1] or mk.bar_day[i] != mk.bar_day[i - 1]:
        return None
    if mk.bucket[i] != mk.bucket[i - 1] + 1 or not (mk.ok[i] and mk.ok[i - 1]):
        return None
    p, q = i - 1, i
    tol = cfg[V.K_TOUCH_TOL]
    te = _touch(b.low[p], b.high[p], mk.ema[p], tol)
    ts = _touch(b.low[p], b.high[p], mk.sma[p], tol)
    if not te and not ts:
        return None
    lines = (mk.ema[q], mk.sma[q])
    if b.low[q] > min(lines) and b.high[q] > b.high[p] and b.low[q] > b.low[p]:
        d, level, stop = 1, b.high[q] + 1, b.low[p]
    elif b.high[q] < max(lines) and b.low[q] < b.low[p] and b.high[q] < b.high[p]:
        d, level, stop = -1, b.low[q] - 1, b.high[p]
    else:
        return None
    risk = abs(level - stop)
    dist = abs(b.close[q] - mk.vwap[q])
    k = cfg[V.K_BAND_WIDE] if risk >= cfg[V.K_BAND_WIDE_RISK] else cfg[V.K_BAND]
    if dist <= k * mk.atr14[q]:
        if risk >= cfg[V.K_MAX_RISK]:
            return None
        cls = V.WIDE if risk >= cfg[V.K_WIDE_RISK] else V.NORMAL
        mult = cfg[V.K_R_HOT] if mk.atr14[q] > cfg[V.K_ATR_RATIO] * mk.atr100[q] else cfg[V.K_R]
    elif (cfg[V.K_FAR_ON] and dist >= cfg[V.K_FAR_DIST] and risk < cfg[V.K_FAR_RISK]
          and (mk.ema[q] > mk.sma[q] if d == 1 else mk.ema[q] < mk.sma[q])):
        cls, mult = V.FAR, cfg[V.K_R_SMALL]
    elif cfg[V.K_SCALP_ON] and risk < cfg[V.K_SCALP_RISK]:
        cls, mult = V.SCALP, cfg[V.K_R_SMALL]
    else:
        return None
    return dict(d=d, level=level, stop=stop, target=level + d * math.floor(mult * risk), cls=cls,
                te=te, ts=ts, c3=i + 1, last=i + int(cfg[V.K_EXPIRY_BARS]), risk=risk)


def trades(mk, cfg, slip=1.0, pessimistic=True):
    """List of (day, in_row, out_row, dir, px_in, px_out, why, cls, risk, addon, pnl_usd)."""
    f = mk.f
    b = mk.bars
    out = []
    order = None
    pos = None
    day, day_pnl = None, 0.0
    tick, fee = cfg[V.K_TICK_USD], cfg[V.K_FEE_USD]
    atick, afee = cfg[V.K_ADD_TICK_USD], cfg[V.K_ADD_FEE_USD]

    def close(j, px, why):
        nonlocal pos, day_pnl
        p = pos
        pnl = p["d"] * (px - p["fill"]) * tick - fee
        if p["a_fill"] is not None:
            pnl += p["d"] * (px - p["a_fill"]) * atick - afee
        out.append((day, p["row"], j, p["d"], p["fill"], px, why, p["cls"], p["risk"],
                    p["a_fill"] is not None, pnl))
        day_pnl += pnl
        pos = None

    for i in range(len(b)):
        if mk.fs[i] < 0:
            order = None
            continue
        if pos is not None and b.contract[i] != f.contract[pos["row"]]:  # roll without a cutoff minute
            last = mk.fs[i] - 1
            close(last, f.close[last] - pos["d"] * slip, EXIT_FALLBACK)
        if mk.bar_day[i] != day:
            day, day_pnl = mk.bar_day[i], 0.0
        if order is not None:
            follows = (b.contract[i] == b.contract[i - 1] and mk.bar_day[i] == mk.bar_day[i - 1]
                       and mk.bucket[i] == mk.bucket[i - 1] + 1 and mk.fs[i - 1] >= 0)
            if not follows:
                order = None
        for j in range(mk.fs[i], mk.fe[i]):
            o, h, lo, tm = f.open[j], f.high[j], f.low[j], f.tmin[j]
            closing = tm >= mk.flat[j] or f.cut[j]
            if order is not None:
                if closing:
                    order = None
                    continue
                d, lvl = order["d"], order["level"]
                if not (h >= lvl if d == 1 else lo <= lvl):
                    continue
                fill = (o if d * (o - lvl) >= 0 else lvl) + d * slip
                pos = dict(d=d, fill=fill, stop=order["stop"], tgt=order["target"], cls=order["cls"],
                           risk=order["risk"], row=j, a_fill=None,
                           a_lvl=order["target"] - d * cfg[V.K_ADDON_OFFSET],
                           a_wait=bool(cfg[V.K_ADDON]) and d * (order["target"] - fill) > cfg[V.K_ADDON_OFFSET])
                order = None
                hit_stop = lo <= pos["stop"] if d == 1 else h >= pos["stop"]
                if pessimistic and hit_stop:
                    close(j, pos["stop"] - d * slip, EXIT_STOP)
                continue
            if pos is None:
                continue
            d, stop, tgt = pos["d"], pos["stop"], pos["tgt"]
            a_hit = pos["a_wait"] and (h >= pos["a_lvl"] if d == 1 else lo <= pos["a_lvl"])
            a_px = (o if d * (o - pos["a_lvl"]) >= 0 else pos["a_lvl"]) + d * slip
            if closing:
                close(j, o - d * slip, EXIT_CUTOFF if f.cut[j] and tm < mk.flat[j] else EXIT_TIME)
                continue
            if d * (o - stop) <= 0:
                close(j, o - d * slip, EXIT_STOP)
                continue
            if d * (o - tgt) >= 1:
                close(j, tgt, EXIT_TARGET)
                continue
            s_hit = lo <= stop if d == 1 else h >= stop
            t_hit = h >= tgt + 1 if d == 1 else lo <= tgt - 1
            if s_hit and (pessimistic or not t_hit):
                if a_hit and pessimistic:
                    pos["a_fill"] = a_px
                close(j, stop - d * slip, EXIT_STOP)
            elif t_hit:
                if a_hit and not pessimistic:
                    pos["a_fill"] = a_px
                close(j, tgt, EXIT_TARGET)
            elif a_hit:
                pos["a_fill"] = a_px
                pos["a_wait"] = False
        if order is not None:
            c3_touch = cfg[V.K_CANCEL_TOUCH] and (
                (order["te"] and _touch(b.low[i], b.high[i], mk.ema[i], cfg[V.K_TOUCH_TOL]))
                or (order["ts"] and _touch(b.low[i], b.high[i], mk.sma[i], cfg[V.K_TOUCH_TOL])))
            if (i == order["c3"] and c3_touch) or i >= order["last"]:
                order = None
        if order is None and pos is None and day_pnl > -cfg[V.K_DAILY_STOP]:
            order = _setup(mk, cfg, i)
    if pos is not None:
        close(mk.fe[i] - 1, f.close[mk.fe[i] - 1] - pos["d"] * slip, EXIT_FALLBACK)
    return out
