"""Slow, plain-Python ORB reference. Written separately from orb_engine (no shared day tables,
no numba) so the two can be compared trade by trade. Same rules: see orb_engine's docstring."""

import math

import numpy as np
import pandas as pd

from . import orb_engine as E


def _utc_min(ts: pd.Timestamp) -> int:
    return int(ts.tz_convert("UTC").value // E.NS_PER_MIN)


def day_setup(f: E.Front, rows: dict, daytime: dict, trading_day: int, anchor: str, L: int,
              eia: pd.DataFrame | None):
    """Range and day limits for one trading day, or None if the day is not tradable."""
    tz, minute, before = E.ANCHORS[anchor]
    date = pd.Timestamp("1970-01-01") + pd.Timedelta(days=trading_day - before)
    start = _utc_min((date + pd.Timedelta(minutes=minute)).tz_localize(tz))
    idx = [rows[start + k] for k in range(L) if start + k in rows]
    if len(idx) < math.ceil(E.MIN_COVERAGE * L):
        return None
    after = idx[-1] + 1
    if after >= len(f) or len({int(f.contract[i]) for i in idx + [after]}) != 1 or any(f.cut[i] for i in idx):
        return None
    day_date = pd.Timestamp("1970-01-01") + pd.Timedelta(days=trading_day)
    daytime = daytime.get(trading_day, [])
    if not daytime:
        return None
    flat_mod = E.SHORT_DAY_FLAT_MOD if E.short_days(np.array([trading_day]))[0] else E.SESSION_FLAT_MOD
    sess_end = _utc_min((day_date + pd.Timedelta(minutes=flat_mod)).tz_localize(E.ET))
    exp = int(f.expiry[f.contract[max(daytime, key=lambda k: f.tmin[k])]])
    if exp >= 0 and exp - E.CLOSE_BUFFER < sess_end:
        sess_end = exp - E.CLOSE_BUFFER
    if sess_end <= start + L:
        return None
    blocks = []
    if eia is not None:
        for _, r in eia[pd.to_datetime(eia["date"]) == day_date].iterrows():
            rel = _utc_min((day_date + pd.Timedelta(minutes=int(r["minute_et"]))).tz_localize(E.ET))
            blocks.append((rel - E.EIA_BLOCK, rel + E.EIA_BLOCK))
    return {"first": after, "rend": start + L, "hi": max(f.high[i] for i in idx),
            "lo": min(f.low[i] for i in idx), "sess_end": sess_end, "blocks": blocks,
            "ropen": f.open[idx[0]], "rclose": f.close[idx[-1]], "rvol": float(sum(f.volume[i] for i in idx))}


def simulate_day(f, s, trigger, buf, stop_type, stop_ticks, target_r, window, flat_off, dirpol, be,
                 slip=1.0, pessimistic=True):
    flat = s["sess_end"] if flat_off == E.SESSION else min(s["rend"] + flat_off, s["sess_end"])
    deadline = min(s["rend"] + window, flat)
    if deadline <= s["rend"]:
        return []
    hi, lo = s["hi"], s["lo"]
    level = {1: hi + 1 + buf, -1: lo - 1 - buf}
    side_open = {1: dirpol != E.SHORT, -1: dirpol != E.LONG}
    max_trades = 2 if dirpol == E.BOTH2 else 1

    def blocked(t):
        return any(a <= t < b for a, b in s["blocks"])

    def make(d, fill):
        if stop_type == E.MID:
            st = math.floor((hi + lo) / 2) if d == 1 else math.ceil((hi + lo) / 2)
        elif stop_type == E.OPPOSITE:
            st = lo - 1 if d == 1 else hi + 1
        else:
            st = fill - d * stop_ticks
        r = d * (fill - st)
        if r < 1:
            return None
        return {"d": d, "fill": fill, "stop": st, "r": r, "be_on": False, "mae": 0.0,
                "tgt": fill + d * math.ceil(target_r * r) if target_r > 0 else None}

    trades, pos, pending = [], None, None
    contract = f.contract[s["first"]]
    j = s["first"]
    last_j = j
    while j < len(f) and f.contract[j] == contract:
        t, o, h, l, c = int(f.tmin[j]), f.open[j], f.high[j], f.low[j], f.close[j]
        fresh = False
        if pos is None and pending is not None:
            d, pending = pending, None
            if t < deadline and not f.cut[j] and not blocked(t):
                pos = make(d, o + d * slip)
                if pos:
                    pos["in"] = j
                    fresh = True
        if pos is None:
            if t >= deadline or t >= flat or len(trades) >= max_trades:
                break
            if trigger == E.STOP:
                hits = [d for d in (1, -1) if side_open[d] and (h >= level[1] if d == 1 else l <= level[-1])]
                if len(hits) == 2:
                    hits = [1] if level[1] - o <= o - level[-1] else [-1]
                if hits:
                    d = hits[0]
                    side_open[d] = False
                    if not (f.cut[j] or blocked(t)):
                        fill = (o if d * (o - level[d]) >= 0 else level[d]) + d * slip
                        pos = make(d, fill)
                        if pos:
                            pos["in"] = j
                            last_j = j
                            pos["mae"] = max(0.0, d * (fill - (l if d == 1 else h)))
                            touched = (l <= pos["stop"]) if d == 1 else (h >= pos["stop"])
                            if pessimistic and touched:
                                trades.append((pos["in"], j, d, fill, pos["stop"] - d * slip,
                                               d * (fill - pos["stop"]) + slip, E.EXIT_STOP))
                                pos = None
                                if dirpol != E.BOTH2 or len(trades) >= max_trades:
                                    break
                            elif not pessimistic:
                                pos["mae"] = min(pos["mae"], d * (fill - pos["stop"]) + slip)
            else:
                if trigger == E.CLOSE1:
                    bar_end, last_of_bar = t + 1, True
                else:
                    bar_end = s["rend"] + 5 * ((t - s["rend"]) // 5 + 1)
                    nxt = j + 1
                    last_of_bar = nxt >= len(f) or f.contract[nxt] != contract or f.tmin[nxt] >= bar_end
                if last_of_bar and bar_end <= deadline:
                    if side_open[1] and c >= level[1]:
                        side_open[1] = False
                        pending = 1
                    elif side_open[-1] and c <= level[-1]:
                        side_open[-1] = False
                        pending = -1
            j += 1
            continue

        d = pos["d"]
        last_j = j
        if not fresh and (t >= flat or f.cut[j]):
            why = E.EXIT_CUTOFF if f.cut[j] and t < flat else E.EXIT_TIME
            trades.append((pos["in"], j, d, pos["fill"], o - d * slip, pos["mae"], why))
            pos = None
            break
        fill, st, tgt = pos["fill"], pos["stop"], pos["tgt"]
        out = None
        if d * (o - st) <= 0:
            pos["mae"] = max(pos["mae"], d * (fill - o))
            out = (o - d * slip, E.EXIT_STOP)
        elif tgt is not None and d * (o - tgt) >= 1:
            out = (tgt, E.EXIT_TARGET)
        else:
            s_hit = l <= st if d == 1 else h >= st
            t_hit = tgt is not None and (h >= tgt + 1 if d == 1 else l <= tgt - 1)
            if s_hit and (pessimistic or not t_hit):
                pos["mae"] = max(pos["mae"], d * (fill - st))
                out = (st - d * slip, E.EXIT_STOP)
            elif t_hit:
                pos["mae"] = max(pos["mae"], d * (fill - (l if d == 1 else h)))
                out = (tgt, E.EXIT_TARGET)
        if out:
            trades.append((pos["in"], j, d, fill, out[0], pos["mae"], out[1]))
            pos = None
            if out[1] != E.EXIT_STOP or dirpol != E.BOTH2 or len(trades) >= max_trades:
                break
            j += 1
            continue
        pos["mae"] = max(pos["mae"], d * (fill - (l if d == 1 else h)))
        if be and not pos["be_on"] and d * ((h if d == 1 else l) - (fill + d * pos["r"])) >= 0:
            pos["be_on"] = True
            if d * (fill - st) > 0:
                pos["stop"] = fill
        j += 1
    if pos is not None:
        trades.append((pos["in"], last_j, pos["d"], pos["fill"], f.close[last_j] - pos["d"] * slip,
                       pos["mae"], E.EXIT_FALLBACK))
    return trades


def width_allowed(mode, ratio):
    if mode == E.W_NONE:
        return True
    if ratio is None or np.isnan(ratio):
        return False
    return {E.W_SKIP_WIDE: ratio <= E.WIDE, E.W_SKIP_NARROW: ratio >= E.NARROW,
            E.W_MID: E.NARROW <= ratio <= E.WIDE}[mode]


def run(f: E.Front, days, anchor, L, trigger, buf, stop_type, stop_ticks, target_r, window, flat_off,
        dirpol, width, be, eia=None, slip=1.0, pessimistic=True):
    """All trades: list of (day_index, in_row, out_row, dir, px_in, px_out, mae, why)."""
    rows = {int(t): k for k, t in enumerate(f.tmin)}  # UTC minute -> row
    daytime = {}  # trading day -> its daytime rows
    for k in range(len(f)):
        if f.trading_day[k] == f.et_day[k] and f.mod[k] < 17 * 60:
            daytime.setdefault(int(f.trading_day[k]), []).append(k)
    setups = [day_setup(f, rows, daytime, int(td), anchor, L, eia) for td in days]
    widths = [s["hi"] - s["lo"] if s else None for s in setups]
    out = []
    for k, s in enumerate(setups):
        if s is None:
            continue
        prev = [w for w in widths[:k] if w is not None][-E.WIDTH_LOOKBACK:]
        ratio = None
        if len(prev) == E.WIDTH_LOOKBACK and np.median(prev) > 0:
            ratio = widths[k] / np.median(prev)
        if not width_allowed(width, ratio):
            continue
        for t in simulate_day(f, s, trigger, buf, stop_type, stop_ticks, target_r, window, flat_off,
                              dirpol, be, slip, pessimistic):
            out.append((k,) + t)
    return out
