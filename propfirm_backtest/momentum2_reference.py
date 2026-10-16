"""Slow plain-Python Pine-momentum simulator, written from the rules in momentum2_engine's docstring.
Used only to check the numba engine trade by trade. Shares the prepared inputs (Market: bars, flat
times, EIA and session masks) but none of the signal, order or fill code."""

import math

from . import momentum2_engine as M
from .orb_engine import EXIT_CUTOFF, EXIT_FALLBACK, EXIT_STOP, EXIT_TARGET, EXIT_TIME


def _pine_signal(b, i, d, mult, body_pct, mom_with):
    o, h, l, c = (b[k] for k in ("o", "h", "l", "c"))
    rng = h[i] - l[i]
    body_percent = abs(c[i] - o[i]) / rng * 100 if rng > 0 else 0
    if rng <= 0 or not body_percent < body_pct - 1e-12:
        return False
    if not (d * (c[i] - o[i]) > 0 and d * (c[i] - o[i - 1]) > 0):
        return False
    if not abs(c[i - 3] - o[i - 3]) > abs(c[i - 4] - o[i - 4]) * mult + 1e-12:
        return False
    if mom_with and not d * (c[i - 3] - o[i - 3]) > 0:
        return False
    if d == 1:
        return c[i - 2] > c[i - 3] and c[i - 1] > c[i - 2] and l[i - 2] >= l[i - 3] and l[i - 1] >= l[i - 2]
    return c[i - 2] < c[i - 3] and c[i - 1] < c[i - 2] and h[i - 2] <= h[i - 3] and h[i - 1] <= h[i - 2]


def trades(mk, cfg, n_days=None, slip=1.0, pessimistic=True):
    """Same output tuple as Market.trades, as Python lists."""
    n_days = len(mk.days) if n_days is None else n_days
    b, f = mk.bars, mk.f
    tf = int(cfg[M.C_TF])
    mult, body_pct, rr = cfg[M.C_MULT10] / 10, cfg[M.C_BODY10] / 10, cfg[M.C_R10] / 10
    mom_with = cfg[M.C_MOM_DIR] == 1
    tv_mgmt = M.MGMT_NAMES[int(cfg[M.C_MGMT])] == "tv"
    tv_fill = M.FILL_NAMES[int(cfg[M.C_FILL])] == "tv"
    sbuf, min_risk = cfg[M.C_STOP_BUF], max(1, cfg[M.C_MIN_RISK])
    sk = int(cfg[M.C_SESSION])
    allowed = {M.BOTH: (1, -1), M.LONG: (1,), M.SHORT: (-1,)}[int(cfg[M.C_DIR])]
    out = []
    pending = None  # dict(d, stop, tgt, con, day)
    pos = None  # dict(d, fill, stop, tgt, row, day, mae, con)
    last_row = None
    run = 0
    lo, hi = mk.off[tf], mk.off[tf + 1]

    def close(row, px, why, mae):
        out.append((pos["day"], pos["row"], row, pos["d"], pos["fill"], px, mae, why))

    for i in range(lo, hi):
        if b["fs"][i] < 0 or b["day"][i] < 0:
            run, pending = 0, None
            continue
        if b["day"][i] >= n_days:
            break
        if pos and (b["contract"][i] != pos["con"] or b["day"][i] != pos["day"]):
            px = f.close[last_row] - pos["d"] * slip
            close(last_row, px, EXIT_FALLBACK, max(pos["mae"], -pos["d"] * (px - pos["fill"])))
            pos = None
        joined = (i > lo and b["fs"][i - 1] >= 0 and b["contract"][i] == b["contract"][i - 1]
                  and b["day"][i] == b["day"][i - 1] and b["bucket"][i] == b["bucket"][i - 1] + 1)
        run = run + 1 if joined else 1
        first = b["fs"][i]

        # pending market order at this bar's first minute
        if pending:
            p, pending = pending, None
            allowed_now = (b["contract"][i] == p["con"] and b["day"][i] == p["day"] and f.tmin[first] < mk.flat[first]
                           and not f.cut[first] and not mk.blocked[first] and mk.sess[sk, first])
            if allowed_now:
                op = f.open[first]
                if pos:
                    d = pos["d"]
                    if (op - pos["stop"]) * d <= 0:
                        px, why = op - d * slip, EXIT_STOP
                    elif (tv_fill and (op - pos["tgt"]) * d >= 0) or (not tv_fill and (op - pos["tgt"]) * d >= 1):
                        px, why = (op if tv_fill else pos["tgt"]), EXIT_TARGET
                    else:
                        px, why = op - d * slip, M.EXIT_REVERSE
                    close(first, px, why, max(pos["mae"], -d * (px - pos["fill"])))
                pos = dict(d=p["d"], fill=op + p["d"] * slip, stop=p["stop"], tgt=p["tgt"], row=first,
                           day=b["day"][i], mae=0.0, con=b["contract"][i])

        # the bar under the active bracket
        if pos and tv_fill:
            last_row = b["fe"][i] - 1
            d = pos["d"]
            if (f.tmin[first] >= mk.flat[first] or f.cut[first]) and first != pos["row"]:
                why = EXIT_CUTOFF if (f.cut[first] and f.tmin[first] < mk.flat[first]) else EXIT_TIME
                close(first, f.open[first] - d * slip, why, pos["mae"])
                pos = None
            else:
                op, hp, lp = b["o"][i], b["h"][i], b["l"][i]
                stop, tgt = pos["stop"], pos["tgt"]
                res = None
                if d * (op - stop) <= 0:
                    res = (EXIT_STOP, op)
                elif d * (op - tgt) >= 0:
                    res = (EXIT_TARGET, op)
                else:
                    stop_hit = lp <= stop if d == 1 else hp >= stop
                    tgt_hit = hp >= tgt if d == 1 else lp <= tgt
                    up_first = (hp - op) < (op - lp)  # TradingView: open nearer the high goes up first
                    tgt_first = up_first == (d == 1)
                    if tgt_hit and (tgt_first or not stop_hit):
                        res = (EXIT_TARGET, tgt)
                    elif stop_hit:
                        res = (EXIT_STOP, stop)
                if res:
                    why, px = res
                    if why == EXIT_STOP:
                        worst = px
                    elif d * (op - tgt) >= 0 or tgt_first:  # target first: the later adverse leg is after the exit
                        worst = op
                    else:
                        worst = lp if d == 1 else hp
                    close(last_row, px - d * slip if why == EXIT_STOP else px,
                          why, max(pos["mae"], d * (pos["fill"] - worst)))
                    pos = None
                else:
                    pos["mae"] = max(pos["mae"], d * (pos["fill"] - (lp if d == 1 else hp)))
        elif pos:
            for j in range(first, b["fe"][i]):
                last_row = j
                d, fill, stop, tgt = pos["d"], pos["fill"], pos["stop"], pos["tgt"]
                op, hp, lp = f.open[j], f.high[j], f.low[j]
                if f.tmin[j] >= mk.flat[j] or f.cut[j]:
                    why = EXIT_CUTOFF if (f.cut[j] and f.tmin[j] < mk.flat[j]) else EXIT_TIME
                    close(j, op - d * slip, why, pos["mae"])
                    pos = None
                    break
                if d * (op - stop) <= 0:
                    close(j, op - d * slip, EXIT_STOP, max(pos["mae"], d * (fill - op)))
                    pos = None
                    break
                if d * (op - tgt) >= 1:
                    close(j, tgt, EXIT_TARGET, pos["mae"])
                    pos = None
                    break
                stop_hit = lp <= stop if d == 1 else hp >= stop
                tgt_hit = hp >= tgt + 1 if d == 1 else lp <= tgt - 1
                worst = lp if d == 1 else hp
                if stop_hit and (pessimistic or not tgt_hit):
                    close(j, stop - d * slip, EXIT_STOP, max(pos["mae"], d * (fill - stop)))
                    pos = None
                    break
                if tgt_hit:
                    close(j, tgt, EXIT_TARGET, max(pos["mae"], d * (fill - worst)))
                    pos = None
                    break
                pos["mae"] = max(pos["mae"], d * (fill - worst))
        else:
            last_row = b["fe"][i] - 1

        # bar closed: Pine's signal
        if run < 5:
            continue
        for d in allowed:
            if not _pine_signal(b, i, d, mult, body_pct, mom_with):
                continue
            stop = b["l"][i] - sbuf if d == 1 else b["h"][i] + sbuf
            risk = abs(b["c"][i] - stop)
            if risk < min_risk:
                continue
            tgt = b["c"][i] + d * math.ceil(rr * risk - 1e-9)
            if pos is None or (pos["d"] != d and tv_mgmt):
                pending = dict(d=d, stop=stop, tgt=tgt, con=b["contract"][i], day=b["day"][i])
            elif pos["d"] == d and tv_mgmt:
                pos["stop"], pos["tgt"] = stop, tgt
    if pos:
        px = f.close[last_row] - pos["d"] * slip
        close(last_row, px, EXIT_FALLBACK, max(pos["mae"], -pos["d"] * (px - pos["fill"])))
    return out
