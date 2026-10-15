"""EMA x VWAP trade simulator (numba).

Order of events inside each timeframe bar i:
  1. Orders decided at the previous bar's close fill at this bar's first minute open.
  2. Touch entries arm at the bar's open using VWAP frozen at the open.
  3. Walk the bar's 1-minute candles in time order: touch fills, stops, forced cutoff exits.
  4. At the bar's close: EMA exit decision and close-cross entry decision (filled next bar).

Fills are pessimistic: market orders pay `slip` ticks; stops fill at stop - slip, or at
open - slip if price gapped through (stricter than a plain open fill, on purpose). If a touch
entry and its stop are in the same minute, the stop is assumed hit (pessimistic=True); the
optimistic bound (pessimistic=False) assumes it was not.
A position that reaches the end of its segment without a cutoff minute (no trade in the
5-minute window) exits at the NEXT traded minute of the same contract: the first price a
real exit order could have got. Nothing is filled retroactively.
"""

import numpy as np
from numba import njit

CROSS, TOUCH = 0, 1
EXIT_EMA, EXIT_STOP, EXIT_CUTOFF, EXIT_FALLBACK = 1, 2, 3, 4
EXIT_NAMES = {EXIT_EMA: "ema", EXIT_STOP: "stop", EXIT_CUTOFF: "cutoff", EXIT_FALLBACK: "fallback"}


@njit(cache=True)
def run(b_start, b_end, b_close, b_seg, ema, ema_ok, vw_close, vw_open,
        m_open, m_high, m_low, m_close, m_cut, m_contract, entry_type, stop_ticks, slip,
        pessimistic=True):
    nb = len(b_start)
    cap = nb + 1
    t_in = np.empty(cap, np.int64)
    t_out = np.empty(cap, np.int64)
    t_dir = np.empty(cap, np.int8)
    t_px_in = np.empty(cap)
    t_px_out = np.empty(cap)
    t_mae = np.empty(cap)
    t_why = np.empty(cap, np.int8)
    k = 0

    pos = 0
    entry_px = 0.0
    stop_px = 0.0
    entry_m = -1
    pos_seg = -1
    mae = 0.0
    last_m = -1  # last minute index seen while holding
    pend = 0  # +1 / -1 = enter at next open, 2 = exit at next open
    pend_seg = -1
    n_min = len(m_open)

    for i in range(nb):
        seg = b_seg[i]
        s = b_start[i]
        e = b_end[i]

        # Segment ended while still holding (no minute traded inside the cutoff window):
        # exit at the next traded minute of the same contract. Counted separately.
        exited_this_bar = False
        if pos != 0 and seg != pos_seg:
            nxt = last_m + 1
            if nxt < n_min and m_contract[nxt] == m_contract[last_m]:
                out_m, px = nxt, m_open[nxt]
            else:
                out_m, px = last_m, m_close[last_m]  # end of data for this contract
            t_in[k] = entry_m; t_out[k] = out_m; t_dir[k] = pos; t_px_in[k] = entry_px
            t_px_out[k] = px - pos * slip; t_mae[k] = mae; t_why[k] = EXIT_FALLBACK
            k += 1
            pos = 0
            pend = 0
        if pend != 0 and (seg < 0 or (pend != 2 and seg != pend_seg)):
            pend = 0

        # 1) orders from the previous close
        if pend == 2 and pos != 0:
            t_in[k] = entry_m; t_out[k] = s; t_dir[k] = pos; t_px_in[k] = entry_px
            t_px_out[k] = m_open[s] - pos * slip; t_mae[k] = mae; t_why[k] = EXIT_EMA
            k += 1
            pos = 0
            exited_this_bar = True  # no touch re-entry in the bar we just left
        elif (pend == 1 or pend == -1) and pos == 0 and not m_cut[s]:
            pos = pend
            entry_px = m_open[s] + pos * slip
            entry_m = s
            pos_seg = seg
            mae = 0.0
            stop_px = entry_px - pos * stop_ticks
        pend = 0

        # 2) arm a touch entry (direction comes from where the previous bar closed)
        armed = 0
        level = 0.0
        if (entry_type == TOUCH and pos == 0 and not exited_this_bar and seg >= 0 and i > 0 and b_seg[i - 1] == seg
                and ema_ok[i - 1] and not np.isnan(vw_open[i]) and not np.isnan(vw_close[i - 1])):
            if b_close[i - 1] < vw_close[i - 1]:
                armed = 1
                level = np.ceil(vw_open[i] - 1e-9)  # buy stop: round up to a real tick
            elif b_close[i - 1] > vw_close[i - 1]:
                armed = -1
                level = np.floor(vw_open[i] + 1e-9)

        # 3) walk the 1-minute candles
        if pos != 0 or armed != 0:
            for j in range(s, e):
                if pos == 0:
                    if armed == 0 or m_cut[j]:
                        break  # no entries inside the cutoff window
                    fill = np.nan
                    if armed == 1:
                        if m_open[j] >= level:
                            fill = m_open[j] + slip  # gapped through the stop
                        elif m_high[j] >= level:
                            fill = level + slip
                    else:
                        if m_open[j] <= level:
                            fill = m_open[j] - slip
                        elif m_low[j] <= level:
                            fill = level - slip
                    if np.isnan(fill):
                        continue
                    pos = armed
                    armed = 0
                    entry_px = fill
                    entry_m = j
                    pos_seg = seg
                    stop_px = entry_px - pos * stop_ticks
                    # worst case for the rest of this minute
                    mae = max(0.0, entry_px - m_low[j]) if pos == 1 else max(0.0, m_high[j] - entry_px)
                    last_m = j
                    touched = (pos == 1 and m_low[j] <= stop_px) or (pos == -1 and m_high[j] >= stop_px)
                    if stop_ticks > 0 and touched and pessimistic:
                        t_in[k] = entry_m; t_out[k] = j; t_dir[k] = pos; t_px_in[k] = entry_px
                        t_px_out[k] = stop_px - pos * slip
                        t_mae[k] = stop_ticks + slip  # loss is capped at the stop fill
                        t_why[k] = EXIT_STOP
                        k += 1
                        pos = 0
                        break
                    if stop_ticks > 0 and not pessimistic:
                        mae = min(mae, stop_ticks + slip)  # optimistic: assume the stop was not hit yet
                    continue

                # holding
                last_m = j
                if m_cut[j]:
                    t_in[k] = entry_m; t_out[k] = j; t_dir[k] = pos; t_px_in[k] = entry_px
                    t_px_out[k] = m_open[j] - pos * slip; t_mae[k] = mae; t_why[k] = EXIT_CUTOFF
                    k += 1
                    pos = 0
                    break
                if stop_ticks > 0:
                    hit = np.nan
                    if pos == 1:
                        if m_open[j] <= stop_px:
                            hit = m_open[j]
                        elif m_low[j] <= stop_px:
                            hit = stop_px
                    else:
                        if m_open[j] >= stop_px:
                            hit = m_open[j]
                        elif m_high[j] >= stop_px:
                            hit = stop_px
                    if not np.isnan(hit):
                        adverse = (entry_px - hit) if pos == 1 else (hit - entry_px)
                        t_in[k] = entry_m; t_out[k] = j; t_dir[k] = pos; t_px_in[k] = entry_px
                        t_px_out[k] = hit - pos * slip; t_mae[k] = max(mae, adverse); t_why[k] = EXIT_STOP
                        k += 1
                        pos = 0
                        break
                adverse = (entry_px - m_low[j]) if pos == 1 else (m_high[j] - entry_px)
                if adverse > mae:
                    mae = adverse

        # 4) decisions at the bar's close (filled at the next bar's open)
        if pos != 0 and ema_ok[i]:
            if (pos == 1 and b_close[i] < ema[i]) or (pos == -1 and b_close[i] > ema[i]):
                pend = 2
        elif (pos == 0 and entry_type == CROSS and seg >= 0 and i > 0 and b_seg[i - 1] == seg
              and ema_ok[i] and not np.isnan(vw_close[i]) and not np.isnan(vw_close[i - 1])):
            # long: crossed up through VWAP and not already on the wrong side of the EMA
            if b_close[i - 1] <= vw_close[i - 1] and b_close[i] > vw_close[i] and b_close[i] >= ema[i]:
                pend = 1
                pend_seg = seg
            elif b_close[i - 1] >= vw_close[i - 1] and b_close[i] < vw_close[i] and b_close[i] <= ema[i]:
                pend = -1
                pend_seg = seg

    if pos != 0:
        t_in[k] = entry_m; t_out[k] = last_m; t_dir[k] = pos; t_px_in[k] = entry_px
        t_px_out[k] = m_close[last_m] - pos * slip; t_mae[k] = mae; t_why[k] = EXIT_FALLBACK
        k += 1

    return (t_in[:k], t_out[:k], t_dir[:k], t_px_in[:k], t_px_out[:k], t_mae[:k], t_why[:k])
