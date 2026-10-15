"""Slow, plain-Python references for the ORB families (no numba, no day tables), compared trade by
trade with orb_family_engine. Rules: see orb_family_engine's docstring. Prior-session features come
from orb_features (tested on their own)."""

import math

import numpy as np

from . import orb_engine as E
from . import orb_family_engine as FE
from . import orb_features as F
from .orb_reference import day_setup, simulate_day


def index_rows(f):
    rows = {int(t): k for k, t in enumerate(f.tmin)}
    daytime = {}
    for k in range(len(f)):
        if f.trading_day[k] == f.et_day[k] and f.mod[k] < 17 * 60:
            daytime.setdefault(int(f.trading_day[k]), []).append(k)
    return rows, daytime


def hold(f, j, d, fill, stop, tgt, flat, contract, entry_j, check_first, mae, slip, pessimistic):
    """Hold from row j to the exit. Returns (in, out, dir, px_in, px_out, mae, why)."""
    last = max(entry_j, j - 1)
    first = True
    while j < len(f) and f.contract[j] == contract:
        t, o, h, l = int(f.tmin[j]), f.open[j], f.high[j], f.low[j]
        last = j
        if (check_first or not first) and (t >= flat or f.cut[j]):
            why = E.EXIT_CUTOFF if f.cut[j] and t < flat else E.EXIT_TIME
            return (entry_j, j, d, fill, o - d * slip, mae, why)
        first = False
        if d * (o - stop) <= 0:
            return (entry_j, j, d, fill, o - d * slip, max(mae, d * (fill - o)), E.EXIT_STOP)
        if tgt is not None and d * (o - tgt) >= 1:
            return (entry_j, j, d, fill, tgt, mae, E.EXIT_TARGET)
        worst = l if d == 1 else h
        s_hit = l <= stop if d == 1 else h >= stop
        t_hit = tgt is not None and (h >= tgt + 1 if d == 1 else l <= tgt - 1)
        if s_hit and (pessimistic or not t_hit):
            return (entry_j, j, d, fill, stop - d * slip, max(mae, d * (fill - stop)), E.EXIT_STOP)
        if t_hit:
            return (entry_j, j, d, fill, tgt, max(mae, d * (fill - worst)), E.EXIT_TARGET)
        mae = max(mae, d * (fill - worst))
        j += 1
    return (entry_j, last, d, fill, f.close[last] - d * slip, mae, E.EXIT_FALLBACK)


def prior_mean_ratio(values, window):
    """value / mean of the previous `window` non-None values (None where not computable)."""
    out, seen = [], []
    for v in values:
        if v is None:
            out.append(None)
            continue
        out.append(v / np.mean(seen[-window:]) if len(seen) >= window and np.mean(seen[-window:]) > 0 else None)
        seen.append(v)
    return out


def session_features(f, days, anchor):
    """Independent loop version of orb_features.Sessions: per-day ATR14, stretch, NR4/NR7/inside/ID-NR4
    and pivot range, each from sessions completed before the day."""
    tz, minute, before = E.ANCHORS[anchor]
    sess = []
    for td in days:
        start = int(E.local_tmin(np.array([int(td)]), minute, tz, before)[0])
        end = int(E.local_tmin(np.array([int(td)]), F.SESSION_END_MOD, E.ET)[0])
        rows = [k for k in range(len(f)) if start <= f.tmin[k] < end]
        first = next((k for k in range(len(f)) if f.tmin[k] >= start), None)
        today = int(f.contract[first]) if first is not None else -1
        ok = len(rows) >= F.MIN_SESSION_MINUTES and f.contract[rows[0]] == f.contract[rows[-1]] if rows else False
        st = None
        if ok:
            st = dict(o=f.open[rows[0]], h=max(f.high[k] for k in rows), l=min(f.low[k] for k in rows),
                      c=f.close[rows[-1]], k=int(f.contract[rows[0]]))
        sess.append((st, today))
    names = ["atr14", "stretch", "piv_lo", "piv_hi"]
    out = {n: np.full(len(days), np.nan) for n in names}
    for n in ["nr4", "nr7", "inside", "idnr4"]:
        out[n] = np.zeros(len(days), bool)
    done = []  # completed usable sessions
    for d, (st, today) in enumerate(sess):
        trs = [max(b["h"], a["c"]) - min(b["l"], a["c"]) for a, b in zip(done, done[1:]) if a["k"] == b["k"]]
        if len(trs) >= F.ATR_DAYS:
            out["atr14"][d] = np.mean(trs[-F.ATR_DAYS:])
        if len(done) >= F.STRETCH_DAYS:
            out["stretch"][d] = np.mean([min(x["h"] - x["o"], x["o"] - x["l"]) for x in done[-F.STRETCH_DAYS:]])
        if done:
            p, rngs = done[-1], [x["h"] - x["l"] for x in done]
            out["nr4"][d] = len(rngs) >= 4 and rngs[-1] == min(rngs[-4:])
            out["nr7"][d] = len(rngs) >= 7 and rngs[-1] == min(rngs[-7:])
            out["inside"][d] = (len(done) >= 2 and done[-2]["k"] == p["k"] and p["h"] < done[-2]["h"]
                                and p["l"] > done[-2]["l"])
            out["idnr4"][d] = out["inside"][d] and out["nr4"][d]
            if p["k"] == today:
                piv = (p["h"] + p["l"] + p["c"]) / 3
                bc = (p["h"] + p["l"]) / 2
                tc = 2 * piv - bc
                out["piv_lo"][d], out["piv_hi"][d] = min(bc, tc), max(bc, tc)
        if st is not None:
            done.append(st)
    return out


def run_zab(f, days, anchor, L, entry, atr_x100, target_r, flat_off, relvol_x10, dirmode, eia=None,
            slip=1.0, pessimistic=True):
    rows, daytime = index_rows(f)
    setups = [day_setup(f, rows, daytime, int(td), anchor, L, eia) for td in days]
    relvol = prior_mean_ratio([s["rvol"] if s else None for s in setups], F.RELVOL_DAYS)
    atr = session_features(f, days, anchor)["atr14"]
    out = []
    for k, s in enumerate(setups):
        if s is None:
            continue
        if relvol_x10 and not (relvol[k] is not None and relvol[k] >= relvol_x10 / 10):
            continue
        side = int(s["rclose"] > s["ropen"]) - int(s["rclose"] < s["ropen"])
        if side == 0 or (dirmode == FE.DIR_LONG and side < 0) or (dirmode == FE.DIR_SHORT and side > 0):
            continue
        if atr_x100 and np.isnan(atr[k]):
            continue
        flat = s["sess_end"] if flat_off == E.SESSION else min(s["rend"] + flat_off, s["sess_end"])
        contract = f.contract[s["first"]]
        level = s["hi"] + 1 if side == 1 else s["lo"] - 1
        blocked = lambda t: any(a <= t < b for a, b in s["blocks"])  # noqa: E731
        for j in range(s["first"], len(f)):
            t = int(f.tmin[j])
            if f.contract[j] != contract or t >= flat:
                break
            if entry == FE.BREAKOUT and not (f.high[j] >= level if side == 1 else f.low[j] <= level):
                continue
            if f.cut[j] or blocked(t):
                break
            if entry == FE.IMMEDIATE:
                fill = f.open[j] + side * slip
            else:
                fill = (f.open[j] if side * (f.open[j] - level) >= 0 else level) + side * slip
            stop = (fill - side * max(1, math.ceil(atr_x100 / 100 * atr[k])) if atr_x100
                    else (s["lo"] - 1 if side == 1 else s["hi"] + 1))
            r = side * (fill - stop)
            if r < 1:
                break
            tgt = fill + side * math.ceil(target_r * r) if target_r else None
            if entry == FE.BREAKOUT:
                worst = f.low[j] if side == 1 else f.high[j]
                mae = max(0.0, side * (fill - worst))
                touched = f.low[j] <= stop if side == 1 else f.high[j] >= stop
                if pessimistic and touched:
                    out.append((k, j, j, side, fill, stop - side * slip, side * (fill - stop) + slip, E.EXIT_STOP))
                    break
                if not pessimistic:
                    mae = min(mae, side * (fill - stop) + slip)
                out.append((k,) + hold(f, j + 1, side, fill, stop, tgt, flat, contract, j, True, mae, slip, pessimistic))
            else:
                out.append((k,) + hold(f, j, side, fill, stop, tgt, flat, contract, j, False, 0.0, slip, pessimistic))
            break
    return out


def run_crabel(f, days, anchor, L, stretch_x100, setup, window, flat_off, stop_type, dirpol, eia=None,
               slip=1.0, pessimistic=True):
    """Crabel via the classic ORB reference with the range edges moved out by the stretch."""
    rows, daytime = index_rows(f)
    sess = session_features(f, days, anchor)
    flags = {FE.SETUP_NONE: np.ones(len(days), bool), FE.SETUP_NR4: sess["nr4"], FE.SETUP_NR7: sess["nr7"],
             FE.SETUP_INSIDE: sess["inside"], FE.SETUP_IDNR4: sess["idnr4"]}
    out = []
    for k, td in enumerate(days):
        s = day_setup(f, rows, daytime, int(td), anchor, L, eia)
        if s is None or np.isnan(sess["stretch"][k]) or not flags[setup][k]:
            continue
        st = max(1, math.ceil(stretch_x100 / 100 * sess["stretch"][k]))
        s = {**s, "hi": s["hi"] + st - 1, "lo": s["lo"] - st + 1}
        for t in simulate_day(f, s, E.STOP, 0, stop_type, 0, 0, window, flat_off, dirpol, False, slip, pessimistic):
            out.append((k,) + t)
    return out


def run_acd(f, days, anchor, L, a_x1000, c_x1000, acc_x100, pivot, c_on, flat_off, dirmode, eia=None,
            slip=1.0, pessimistic=True):
    """Fisher ACD, written as an event list per day instead of the engine's single loop."""
    rows, daytime = index_rows(f)
    feats = session_features(f, days, anchor)
    need = max(1, math.ceil(acc_x100 / 100 * L))
    out = []
    for k, td in enumerate(days):
        s = day_setup(f, rows, daytime, int(td), anchor, L, eia)
        atr = feats["atr14"][k]
        if s is None or np.isnan(atr):
            continue
        sides = {1: dirmode != FE.DIR_SHORT, -1: dirmode != FE.DIR_LONG}
        if pivot:
            if np.isnan(feats["piv_lo"][k]):
                continue
            if s["ropen"] > feats["piv_hi"][k]:
                sides[-1] = False
            elif s["ropen"] < feats["piv_lo"][k]:
                sides[1] = False
        A = max(1, math.ceil(a_x1000 / 1000 * atr))
        C = max(1, math.ceil(c_x1000 / 1000 * atr))
        H, Lo = s["hi"], s["lo"]
        flat = s["sess_end"] if flat_off == E.SESSION else min(s["rend"] + flat_off, s["sess_end"])
        contract = f.contract[s["first"]]
        blocked = lambda t: any(a <= t < b for a, b in s["blocks"])  # noqa: E731
        window = []
        for j in range(s["first"], len(f)):
            if f.contract[j] != contract or f.tmin[j] >= flat:
                break
            window.append(j)

        def accepted(start_pos, beyond):
            """Position in `window` of the bar completing `need` consecutive clock minutes beyond."""
            run, prev = 0, None
            for p in range(start_pos, len(window)):
                j = window[p]
                ok = beyond(j)
                run = (run + 1 if prev is not None and f.tmin[j] == prev + 1 else 1) if ok else 0
                prev = f.tmin[j]
                if run >= need:
                    return p
            return None

        def first_through(start_pos, through):
            return next((p for p in range(start_pos, len(window)) if through(window[p])), None)

        def enter(p_signal, side):
            """Trade entered at the open after bar p_signal, or None."""
            if not sides[side] or p_signal + 1 >= len(window):
                return None
            j = window[p_signal + 1]
            if f.cut[j] or blocked(int(f.tmin[j])):
                return None
            fill = f.open[j] + side * slip
            stop = Lo - 1 if side == 1 else H + 1
            if side * (fill - stop) < 1:
                return None
            return hold(f, j, side, fill, stop, None, flat, contract, j, False, 0.0, slip, pessimistic)

        up = accepted(0, lambda j: f.low[j] >= H + A)
        dn = accepted(0, lambda j: f.high[j] <= Lo - A)
        if up is None and dn is None:
            continue
        a_side, a_pos = (1, up) if dn is None or (up is not None and up <= dn) else (-1, dn)
        trade = enter(a_pos, a_side)
        if trade is not None:
            out.append((k,) + trade)
            if trade[6] != E.EXIT_STOP or not c_on:
                continue
            fail_pos = window.index(trade[1])
        else:
            if not c_on:
                continue
            fail_pos = first_through(a_pos + 1, lambda j: f.low[j] <= Lo - 1 if a_side == 1 else f.high[j] >= H + 1)
            if fail_pos is None:
                continue
        c_side = -a_side
        level = H + C if c_side == 1 else Lo - C
        c_pos = accepted(fail_pos, lambda j: f.low[j] >= level if c_side == 1 else f.high[j] <= level)
        if c_pos is not None:
            trade = enter(c_pos, c_side)
            if trade is not None:
                out.append((k,) + trade)
    return out
