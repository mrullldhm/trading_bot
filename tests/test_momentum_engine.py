import numpy as np
import pandas as pd
import pytest

from propfirm_backtest import bars as B
from propfirm_backtest import momentum_engine as M
from propfirm_backtest import momentum_reference as R
from propfirm_backtest.orb_engine import EXIT_FALLBACK, EXIT_STOP, EXIT_TARGET, EXIT_TIME
from propfirm_data.config import BARS_DIR

COLS = ["day", "in_row", "out_row", "dir", "px_in", "px_out", "mae", "why"]
AVG = 4.0  # average body: momentum at k=2 needs a body >= 8 ticks


def bar(o, c, lo=None, hi=None):
    """One 1-minute bar."""
    return [(o, max(o, c) if hi is None else hi, min(o, c) if lo is None else lo, c)]


def sim(bars, slip=1.0, pessimistic=True, flat=10**9, day=None, contract=None, blocked=None, **kw):
    """bars: list of lists of (o, h, l, c) minutes, all on timeframe index 0 (1 minute per config)."""
    kw = {"k": 2.0, "w": 0.35, "min_trend": 1, "s": 0.4, "window": 1, "r": 2.0} | kw
    cfg = M.config(**kw)
    cfg[M.C_TF] = 0
    nb = len(bars)
    sizes = [len(b) for b in bars]
    fs = np.concatenate([[0], np.cumsum(sizes)[:-1]]).astype(np.int64)
    fe = fs + np.array(sizes)
    mins = np.array([m for b in bars for m in b], dtype=float)
    day = np.zeros(nb, np.int64) if day is None else np.asarray(day, np.int64)
    contract = np.zeros(nb, np.int64) if contract is None else np.asarray(contract, np.int64)
    off = np.array([0] + [nb] * len(M.TIMEFRAMES), np.int64)
    bar_args = (off, fs, fe, np.arange(nb, dtype=np.int64) + 10_000 * day, day, contract,
                np.array([b[0][0] for b in bars], float), np.array([max(x[1] for x in b) for b in bars], float),
                np.array([min(x[2] for x in b) for b in bars], float), np.array([b[-1][3] for b in bars], float),
                np.full(nb, AVG), np.ones(nb, np.bool_))
    n = len(mins)
    blk = np.zeros(n, np.bool_) if blocked is None else np.asarray(blocked, np.bool_)
    minute_args = (np.arange(n, dtype=np.int64), mins[:, 0], mins[:, 1], mins[:, 2], mins[:, 3],
                   np.full(n, flat, np.int64), np.zeros(n, np.bool_), blk, np.ones((3, n), np.bool_))
    t = M.run_trades(cfg, int(day.max()) + 1, bar_args, minute_args, slip, pessimistic)
    return pd.DataFrame(dict(zip(COLS, t)))


# Long setup: M (body 10, wicks 2 of 12), T, S (body 1, base 112): buy stop 116, stop 112.
MB = bar(100, 110, lo=99, hi=111)
TB = bar(110, 114, lo=109, hi=115)
SB = bar(114, 115, lo=112, hi=116)
ENTRY = bar(115, 117, lo=114, hi=118)  # trades 116: fill 117 with 1 tick slippage; risk 5 -> target 127
RUN = bar(120, 128, lo=119, hi=128)  # one tick through 127


def test_long_to_target():
    t = sim([MB, TB, SB, ENTRY, RUN])
    assert len(t) == 1
    r = t.iloc[0]
    assert (r.dir, r.px_in, r.px_out, r.why, r.in_row, r.out_row) == (1, 117.0, 127.0, EXIT_TARGET, 3, 4)


def test_target_scales_with_r_and_needs_trade_through():
    assert sim([MB, TB, SB, ENTRY, RUN], r=3.0).why.tolist() == [EXIT_FALLBACK]  # 132 never traded
    assert sim([MB, TB, SB, ENTRY, bar(120, 127, lo=119, hi=127)]).why.tolist() == [EXIT_FALLBACK]


def test_trigger_is_the_body_not_the_wick():
    s_wick = bar(114, 115, lo=112, hi=125)  # long upper wick: level is still 116
    assert sim([MB, TB, s_wick, ENTRY, RUN]).px_in.tolist() == [117.0]
    assert len(sim([MB, TB, SB, bar(115, 115, lo=114, hi=115)])) == 0  # never reaches 116


def test_opposing_small_candle_and_doji_are_valid():
    assert sim([MB, TB, bar(115, 114, lo=112, hi=116), ENTRY, RUN]).px_in.tolist() == [117.0]
    assert sim([MB, TB, bar(115, 115, lo=112, hi=116), ENTRY, RUN]).px_in.tolist() == [117.0]


def test_momentum_needs_big_body_and_small_wicks():
    assert len(sim([bar(100, 107, lo=99, hi=108), TB, SB, ENTRY, RUN])) == 0  # body 7 < 2 x 4
    assert len(sim([bar(100, 110, lo=94, hi=111), TB, SB, ENTRY, RUN])) == 0  # wicks 7 of 17 > 0.35
    assert len(sim([MB, TB, SB, ENTRY, RUN], k=3.0)) == 0  # body 10 < 3 x 4


def test_min_trend_two_needs_a_second_trend_candle():
    # SB counts as the 2nd T (no order at 116); ENTRY (body 2) becomes the S: level 118, RUN gaps to 120
    assert sim([MB, TB, SB, ENTRY, RUN], min_trend=2).px_in.tolist() == [121.0]
    t2 = bar(114, 118, lo=113, hi=118)
    s2 = bar(118, 119, lo=116, hi=120)  # level 120, stop 116
    t = sim([MB, TB, t2, s2, bar(119, 122, lo=118, hi=122), bar(122, 135, lo=121, hi=135)], min_trend=2)
    assert t.px_in.tolist() == [121.0]


def test_small_candle_right_after_momentum_is_not_a_setup():
    assert len(sim([MB, bar(110, 111, lo=109, hi=112), bar(111, 115, lo=110, hi=116)])) == 0


def test_lower_low_breaks_the_chain():
    s_low = bar(114, 115, lo=108, hi=116)  # low below TB's 109
    assert len(sim([MB, TB, s_low, ENTRY, RUN])) == 0


def test_max_trend_candles():
    # trend bars: body 5 (> 0.4 x 10, so never small), each low above the previous low
    ts = [bar(110 + 5 * q, 115 + 5 * q, lo=109 + 5 * q, hi=116 + 5 * q) for q in range(M.MAX_TREND + 1)]

    def tail(top):  # S on top of the last trend bar, then a bar through its body
        return [bar(top, top + 1, lo=top - 1, hi=top + 2), [(top + 1, top + 30, top, top + 30)]]
    assert len(sim([MB] + ts[:-1] + tail(115 + 5 * (M.MAX_TREND - 1)))) == 1  # 5 trend bars: fine
    assert len(sim([MB] + ts + tail(115 + 5 * M.MAX_TREND))) == 0  # 6: chain ended


def test_window_expiry():
    t_mid = bar(112, 115, lo=112, hi=115)  # trend bar (body 3 > 0.25 x 10), stays below 116
    bars = [MB, TB, bar(114, 115, lo=112, hi=116), t_mid, ENTRY, RUN]
    assert 117.0 not in sim(bars, s=0.25, window=1).px_in.tolist()  # (ENTRY itself becomes a new S)
    assert sim(bars, s=0.25, window=2).px_in.tolist() == [117.0]


def test_newer_small_candle_replaces_the_order():
    s2 = bar(113, 113, lo=112, hi=114)  # level 114
    t = sim([MB, TB, SB, s2, bar(113, 115, lo=113, hi=115), bar(116, 130, lo=115, hi=130)])
    assert t.px_in.tolist() == [115.0]


def test_base_break_before_trigger_cancels():
    e = [(115, 115, 111, 114), (114, 118, 113, 117)]  # below 112 first, then through 116
    assert len(sim([MB, TB, SB, e, RUN])) == 0


def test_same_minute_trigger_and_stop():
    e = [(115, 118, 111, 117)]
    t = sim([MB, TB, SB, e, RUN])
    assert t.why.tolist() == [EXIT_STOP] and t.px_out.tolist() == [111.0]  # filled, then stopped (pessimistic)
    t = sim([MB, TB, SB, e, RUN], stop_buf=2)  # stop 110 not touched
    assert t.px_in.tolist() == [117.0] and t.why.tolist() != [EXIT_STOP]


def test_gap_through_level_fills_at_open():
    t = sim([MB, TB, SB, bar(120, 121, lo=119, hi=122), bar(122, 140, lo=121, hi=140)])
    r = t.iloc[0]
    assert r.px_in == 121.0 and r.px_out == 121.0 + 2 * (121 - 112)


def test_risk_filters():
    assert len(sim([MB, TB, SB, ENTRY, RUN], min_risk=5)) == 0  # planned risk 116 - 112 = 4
    wide = [MB, TB, bar(114, 115, lo=90, hi=116)]  # base 90 < TB low: chain breaks anyway
    assert len(sim(wide + [ENTRY])) == 0
    m_big = bar(100, 200, lo=99, hi=201)
    t_big = bar(200, 230, lo=150, hi=231)
    s_big = bar(229, 230, lo=160, hi=231)  # risk 231 - 160 = 71 ticks: $734 planned loss
    e_big = bar(230, 240, lo=229, hi=240)
    assert len(sim([m_big, t_big, s_big, e_big], max_risk_pct=1.0)) == 0
    assert len(sim([m_big, t_big, s_big, e_big], max_risk_pct=2.0)) == 1


def test_direction_filter_and_short_mirror():
    flip = lambda bs: [[(300 - o, 300 - l, 300 - h, 300 - c) for o, h, l, c in b] for b in bs]
    bars = [MB, TB, SB, ENTRY, RUN]
    long_t = sim(bars, direction="long")
    short_t = sim(flip(bars), direction="short")
    assert len(sim(flip(bars), direction="long")) == 0
    assert (short_t.dir.tolist(), short_t.px_in.tolist(), short_t.px_out.tolist()) == (
        [-1], [300 - long_t.px_in[0]], [300 - long_t.px_out[0]])


def test_flat_time_and_eia_block():
    assert sim([MB, TB, SB, ENTRY, RUN], flat=4).why.tolist() == [EXIT_TIME]
    assert len(sim([MB, TB, SB, ENTRY, RUN], flat=3)) == 0  # order dies at the flat minute
    assert 117.0 not in sim([MB, TB, SB, ENTRY, RUN], blocked=[0, 0, 0, 1, 0]).px_in.tolist()


def test_new_day_and_new_contract_reset_the_chain():
    bars = [MB, TB, SB, ENTRY, RUN]
    assert len(sim(bars, day=[0, 0, 1, 1, 1])) == 0
    assert len(sim(bars, contract=[0, 0, 0, 1, 1])) == 0


# --- random walks: look-ahead and mirror --------------------------------------------------------

def walk(n, seed):
    rng = np.random.default_rng(seed)
    c = 1000 + np.cumsum(rng.integers(-6, 7, n))
    o = np.concatenate([[1000], c[:-1]]) + rng.integers(-1, 2, n)
    h = np.maximum(o, c) + rng.integers(0, 3, n)
    lo = np.minimum(o, c) - rng.integers(0, 3, n)
    return [[(float(a), float(b), float(x), float(d))] for a, b, x, d in zip(o, h, lo, c)]


@pytest.mark.parametrize("seed", [1, 2, 3])
def test_no_look_ahead(seed):
    bars = walk(3000, seed)
    full = sim(bars, window=3, k=1.5)
    assert len(full) > 20
    for cut in [700, 1500, 2400]:
        part = sim(bars[:cut], window=3, k=1.5)
        done = full[full.out_row < cut - 1]
        assert part.iloc[:len(done)].equals(done.reset_index(drop=True))


@pytest.mark.parametrize("seed", [4, 5])
def test_mirror(seed):
    bars = walk(3000, seed)
    flip = [[(2000 - o, 2000 - l, 2000 - h, 2000 - c) for o, h, l, c in b] for b in bars]
    a = sim(bars, direction="long", window=2, k=1.5)
    b = sim(flip, direction="short", window=2, k=1.5)
    assert len(a) > 10 and a.in_row.tolist() == b.in_row.tolist() and a.out_row.tolist() == b.out_row.tolist()
    assert np.allclose(a.px_in, 2000 - b.px_in) and np.allclose(a.px_out, 2000 - b.px_out)


# --- real data: engine == reference ---------------------------------------------------------------

@pytest.mark.skipif(not BARS_DIR.exists(), reason="no CL data")
def test_engine_matches_reference_on_real_data():
    from propfirm_backtest import search as S
    from propfirm_data.eia_calendar import load_releases
    # load_minutes(start=) also keeps the 30 days before `start` (warm-up), so each slice is ~2 months
    for start, end in [("2012-02-01", "2012-03-01"), ("2020-04-01", "2020-05-01"), ("2021-10-01", "2021-11-01")]:
        m = B.load_minutes(start=start, end=end)
        cal = S.Calendar(m)
        mk = M.Market(m, cal.days, load_releases(), strict_expiry=True)
        for tf in M.TIMEFRAMES:
            for kw, slip, pess in [({}, 1.0, True), ({"min_trend": 2, "window": 3, "stop_buf": 2, "r": 1.5,
                                                     "session": "newyork", "direction": "short"}, 0.0, False)]:
                cfg = M.config(tf=tf, k=1.5, **kw)
                t = mk.trades(cfg, slip=slip, pessimistic=pess)
                eng = list(zip(*[a.tolist() for a in t]))
                ref = [(int(a), int(b), int(c), int(d), float(e), float(f), float(g), int(h))
                       for a, b, c, d, e, f, g, h in R.trades(mk, cfg, slip=slip, pessimistic=pess)]
                assert eng == ref, (start, tf, kw)
