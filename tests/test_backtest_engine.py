"""Hand-calculated scenarios for the EMA x VWAP engine (1-minute timeframe: bar = minute)."""

import numpy as np
import pytest

from propfirm_backtest import engine as E


def scenario(closes, opens=None, highs=None, lows=None, vwap=100.0, ema=90.0, seg=None, cut=None,
             vw_open=None, ema_arr=None):
    n = len(closes)
    c = np.array(closes, float)
    o = np.array(opens if opens is not None else closes, float)
    h = np.array(highs if highs is not None else np.maximum(o, c), float)
    lo = np.array(lows if lows is not None else np.minimum(o, c), float)
    vw = np.full(n, vwap, float) if np.isscalar(vwap) else np.array(vwap, float)
    return dict(
        b_start=np.arange(n), b_end=np.arange(1, n + 1), b_close=c,
        b_seg=np.array(seg if seg is not None else [0] * n, np.int64),
        ema=np.array(ema_arr, float) if ema_arr is not None else np.full(n, ema, float),
        ema_ok=np.ones(n, bool), vw_close=vw,
        vw_open=np.array(vw_open, float) if vw_open is not None else vw.copy(),
        m_open=o, m_high=h, m_low=lo, m_close=c,
        m_cut=np.array(cut if cut is not None else [False] * n, bool),
        m_contract=np.zeros(n, np.int32),
    )


def run(sc, entry=E.CROSS, stop=0.0, slip=1.0, pessimistic=True):
    t = E.run(**sc, entry_type=entry, stop_ticks=stop, slip=slip, pessimistic=pessimistic)
    return [dict(i=a, o=b, d=int(d), pin=pi, pout=po, mae=m, why=int(w)) for a, b, d, pi, po, m, w in zip(*t)]


def test_cross_long_enters_next_open_and_exits_on_ema():
    # bar1 closes above VWAP 100 (bar0 below) -> buy bar2 open 103 + 1 slip.
    # bar3 closes 95 < EMA 96 -> sell bar4 open 94 - 1 slip.
    sc = scenario(closes=[99, 101, 104, 95, 94], opens=[99, 100, 103, 104, 94],
                  ema_arr=[90, 90, 90, 96, 96])
    (t,) = run(sc)
    assert (t["i"], t["d"], t["pin"]) == (2, 1, 104.0)
    assert (t["o"], t["pout"], t["why"]) == (4, 93.0, E.EXIT_EMA)


def test_cross_short_mirror():
    sc = scenario(closes=[101, 99, 96, 105, 106], opens=[101, 100, 97, 96, 106], ema_arr=[110, 110, 110, 104, 104])
    (t,) = run(sc)
    assert (t["i"], t["d"], t["pin"]) == (2, -1, 96.0)
    assert (t["o"], t["pout"], t["why"]) == (4, 107.0, E.EXIT_EMA)


def test_cross_suppressed_when_already_below_ema():
    sc = scenario(closes=[99, 101, 102], ema=105.0)
    assert run(sc) == []


def test_no_signal_without_a_real_cross():
    sc = scenario(closes=[101, 102, 103])  # always above VWAP: no cross
    assert run(sc) == []


def test_touch_long_fills_at_rounded_level_plus_slip():
    # bar0 closes below VWAP -> bar1 arms buy stop at ceil(100.3) = 101; high reaches 102.
    sc = scenario(closes=[99, 101.5, 101.5], opens=[99, 100, 101.5], highs=[99, 102, 102], lows=[98, 100, 101],
                  vwap=[100.3, 100.3, 100.3])
    t = run(sc, entry=E.TOUCH)[0]
    assert (t["i"], t["d"], t["pin"]) == (1, 1, 102.0)


def test_touch_gap_through_fills_at_open():
    sc = scenario(closes=[99, 106, 106], opens=[99, 105, 106], highs=[99, 107, 107], lows=[98, 104, 105])
    t = run(sc, entry=E.TOUCH)[0]
    assert t["pin"] == 106.0  # open 105 above level 100 -> 105 + 1 slip


def test_touch_is_directional_never_short_from_below():
    # previous close below VWAP: only a long stop exists, even if price falls hard
    sc = scenario(closes=[99, 90, 90], opens=[99, 99, 90], highs=[99, 99.5, 90], lows=[98, 89, 89])
    assert run(sc, entry=E.TOUCH) == []


def test_stop_hits_and_gap_fill():
    # long from bar2 open 103 (+1 = 104), stop 10 ticks = 94. bar3 opens 90: gapped -> fill 90 - 1.
    sc = scenario(closes=[99, 101, 104, 92], opens=[99, 100, 103, 90], highs=[99, 101, 104, 93], lows=[98, 100, 102, 89])
    t = run(sc, stop=10)[0]
    assert (t["o"], t["why"], t["pout"]) == (3, E.EXIT_STOP, 89.0)
    assert t["mae"] == pytest.approx(14.0)  # 104 - 90


def test_stop_intrabar():
    sc = scenario(closes=[99, 101, 104, 99], opens=[99, 100, 103, 100], highs=[99, 101, 104, 100], lows=[98, 100, 102, 93])
    t = run(sc, stop=10)[0]
    assert (t["why"], t["pout"]) == (E.EXIT_STOP, 93.0)  # stop 94 - 1 slip


def test_touch_entry_and_stop_same_minute_is_pessimistic():
    sc = scenario(closes=[99, 95, 95], opens=[99, 100, 95], highs=[99, 102, 95], lows=[98, 50, 94])
    t = run(sc, entry=E.TOUCH, stop=10)[0]
    assert t["i"] == t["o"] == 1 and t["why"] == E.EXIT_STOP
    assert t["mae"] == 11  # capped at stop + slip, not the minute's low of 50


def test_optimistic_bound_does_not_assume_the_stop():
    sc = scenario(closes=[99, 95, 95], opens=[99, 100, 95], highs=[99, 102, 95], lows=[98, 85, 94])
    t = run(sc, entry=E.TOUCH, stop=10, pessimistic=False)[0]
    assert t["i"] == 1 and t["o"] > 1


def test_cutoff_forces_exit_at_open_and_blocks_entries():
    sc = scenario(closes=[99, 101, 104, 105, 106], opens=[99, 100, 103, 105, 106],
                  cut=[False, False, False, True, True])
    (t,) = run(sc)
    assert (t["o"], t["why"], t["pout"]) == (3, E.EXIT_CUTOFF, 104.0)
    # a signal whose fill would land in the cutoff window is dropped
    sc2 = scenario(closes=[99, 101, 104], cut=[False, False, True])
    assert run(sc2) == []


def test_new_segment_never_carries_a_position():
    # signal at bar1, segment changes at bar2: pending entry is cancelled
    sc = scenario(closes=[99, 101, 104, 105], seg=[0, 0, 1, 1])
    assert run(sc) == []


def test_fallback_exit_uses_next_traded_minute_not_the_past():
    sc = scenario(closes=[99, 101, 104, 105, 106], opens=[99, 100, 103, 107, 106], seg=[0, 0, 0, -1, -1])
    (t,) = run(sc)
    assert (t["o"], t["why"], t["pout"]) == (3, E.EXIT_FALLBACK, 106.0)  # next open 107 - 1 slip


def test_no_touch_reentry_in_the_bar_of_an_ema_exit():
    # long via cross; bar3 closes below EMA and below VWAP -> exit at bar4 open.
    # bar4 trades back above VWAP but must NOT re-enter in that same bar.
    sc = scenario(closes=[99, 101, 104, 95, 103, 103], opens=[99, 100, 103, 104, 96, 103],
                  highs=[99, 101, 104, 104, 104, 103], lows=[98, 100, 102, 95, 96, 103],
                  ema_arr=[90, 90, 90, 96, 96, 96])
    trades = run(sc, entry=E.TOUCH)
    assert all(t["i"] != 4 for t in trades)


def test_no_look_ahead_future_bars_do_not_change_past_trades():
    rng = np.random.default_rng(1)
    closes = 100 + np.cumsum(rng.normal(0, 2, 400)).round()
    sc = scenario(closes=closes, vwap=100 + np.cumsum(rng.normal(0, 0.5, 400)), ema_arr=closes - 3)
    full = run(sc, stop=10)
    for k in sc:  # scramble everything after bar 200
        if isinstance(sc[k], np.ndarray) and k not in ("b_start", "b_end"):
            sc[k] = sc[k].copy()
            sc[k][201:] = sc[k][201:][::-1]
    cut = run(sc, stop=10)
    before = [t for t in full if t["o"] < 200]
    assert before == [t for t in cut if t["o"] < 200]
