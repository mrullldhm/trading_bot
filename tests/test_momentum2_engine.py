import numpy as np
import pandas as pd
import pytest

from propfirm_backtest import bars as B
from propfirm_backtest import momentum2_engine as M
from propfirm_backtest import momentum2_reference as R
from propfirm_backtest.orb_engine import EXIT_FALLBACK, EXIT_STOP, EXIT_TARGET, EXIT_TIME
from propfirm_data.config import BARS_DIR

COLS = ["day", "in_row", "out_row", "dir", "px_in", "px_out", "mae", "why"]


def bar(o, c, lo=None, hi=None):
    """One 1-minute bar."""
    return [(o, max(o, c) if hi is None else hi, min(o, c) if lo is None else lo, c)]


def inputs(bars, flat=10**9, day=None, contract=None, blocked=None):
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
                np.zeros(nb), np.ones(nb, np.bool_))
    n = len(mins)
    blk = np.zeros(n, np.bool_) if blocked is None else np.asarray(blocked, np.bool_)
    minute_args = (np.arange(n, dtype=np.int64), mins[:, 0], mins[:, 1], mins[:, 2], mins[:, 3],
                   np.full(n, flat, np.int64), np.zeros(n, np.bool_), blk, np.ones((3, n), np.bool_))
    return bar_args, minute_args, int(day.max()) + 1


def sim(bars, slip=1.0, pessimistic=True, flat=10**9, day=None, contract=None, blocked=None, **kw):
    """bars: list of lists of (o, h, l, c) minutes, all on timeframe index 0."""
    kw = {"body_pct": 30.0} | kw
    cfg = M.config(**kw)
    cfg[M.C_TF] = 0
    bar_args, minute_args, nd = inputs(bars, flat, day, contract, blocked)
    t = M.run_trades(cfg, nd, bar_args, minute_args, slip, pessimistic)
    return pd.DataFrame(dict(zip(COLS, t)))


class _Mk:
    """Duck-typed Market over hand-built bars, for the reference simulator."""

    def __init__(self, bars, **kw):
        ba, ma, nd = inputs(bars, **kw)
        keys = ("fs", "fe", "bucket", "day", "contract", "o", "h", "l", "c", "avg", "ok")
        self.off, self.bars = ba[0], dict(zip(keys, ba[1:]))
        f = type("F", (), {})()
        f.tmin, f.open, f.high, f.low, f.close = ma[:5]
        self.flat, f.cut, self.blocked, self.sess = ma[5], ma[6], ma[7], ma[8]
        self.f, self.days = f, np.arange(nd)


# Long: B0 (body 1), B1 momentum (body 4 > 1.5), B2 + B3 higher closes / higher-or-equal lows,
# S (body 1 of range 7 = 14%, c 110 > o[t-1] 107). Stop 106, risk 4, target 110 + 8 = 118.
B0 = bar(100, 101, lo=99, hi=102)
B1 = bar(101, 105, lo=100, hi=106)
B2 = bar(105, 107, lo=104, hi=108)
B3 = bar(107, 109, lo=106, hi=110)
S = bar(109, 110, lo=106, hi=113)
E = bar(111, 113, lo=110, hi=114)  # market fill at the open 111 + 1 tick
RUN = bar(114, 119, lo=113, hi=119)  # one tick through 118
SETUP = [B0, B1, B2, B3, S]


def test_long_to_target():
    t = sim(SETUP + [E, RUN])
    assert len(t) == 1
    r = t.iloc[0]
    assert (r.dir, r.px_in, r.px_out, r.why, r.in_row, r.out_row) == (1, 112.0, 118.0, EXIT_TARGET, 5, 6)


def test_bracket_is_from_the_signal_bar_not_the_fill():
    t = sim(SETUP + [bar(115, 116, lo=114, hi=116), RUN])  # fill 116: target still 118
    assert t.px_in.tolist() == [116.0] and t.px_out.tolist() == [118.0]


def test_pine_literal_threshold():
    assert len(sim(SETUP + [E, RUN], body_pct=0.3)) == 0  # body 1 of range 7 = 14%
    giant = bar(109, 110, lo=106, hi=500)  # body 1 of range 394 = 0.25% < 0.3%: the only way it fires
    assert len(sim([B0, B1, B2, B3, giant, E, RUN], body_pct=0.3)) == 1
    assert len(sim(SETUP + [E, RUN], body_pct=10.0)) == 0  # 14% is not < 10%


def test_momentum_is_against_the_one_prior_bar():
    assert len(sim([bar(100, 103, lo=99, hi=104), B1, B2, B3, S, E, RUN])) == 0  # 4 > 1.5 x 3 fails
    assert len(sim(SETUP + [E, RUN], mult=3.0)) == 1
    assert len(sim(SETUP + [E, RUN], mult=4.0)) == 0  # strict: 4 > 4 fails


def test_momentum_colour():
    b1_bear = bar(105, 101, lo=100, hi=106)  # body 4, bearish; B2 still closes above it
    assert len(sim([B0, b1_bear, B2, B3, S, E, RUN])) == 1  # Pine ignores the colour
    assert len(sim([B0, b1_bear, B2, B3, S, E, RUN], mom_dir="with")) == 0


def test_close_above_previous_open_and_trend():
    b3_red = bar(111, 109, lo=106, hi=111)  # still a higher close, but S closes 110 < its open 111
    assert len(sim([B0, B1, B2, b3_red, S, E, RUN])) == 0
    b3_low = bar(107, 109, lo=103, hi=110)  # low 103 < B2's 104
    assert len(sim([B0, B1, B2, b3_low, S, E, RUN])) == 0
    s_red = bar(110, 109, lo=106, hi=113)  # bearish small bar is not a long signal
    assert len(sim([B0, B1, B2, B3, s_red, E, RUN])) == 0


def test_gap_through_stop_at_the_open():
    t = sim(SETUP + [bar(105, 104, lo=103, hi=105), RUN])
    assert (t.px_in.tolist(), t.px_out.tolist(), t.why.tolist()) == ([106.0], [104.0], [EXIT_STOP])


def test_stop_buffer_and_min_risk():
    t = sim(SETUP + [E, RUN], stop_buf=2)  # stop 104, risk 6, target 122
    assert t.why.tolist() == [EXIT_FALLBACK]
    assert len(sim(SETUP + [E, RUN], min_risk=5)) == 0
    assert len(sim(SETUP + [E, RUN], min_risk=4)) == 1


# After the long fills at E: a bearish pattern P0..S2 (short stop 112, target 100), then REV.
P0 = bar(113, 114, lo=112, hi=115)
P1 = bar(116, 112, lo=111, hi=117)
P2 = bar(112, 110, lo=109, hi=113)
P3 = bar(110, 109, lo=108, hi=112)
S2 = bar(109, 108, lo=107, hi=112)
REV = bar(107, 106, lo=105, hi=108)
REVERSAL = SETUP + [E, P0, P1, P2, P3, S2, REV]


def test_opposite_signal_reverses_at_the_next_open():
    t = sim(REVERSAL)
    assert t.dir.tolist() == [1, -1]
    assert t.why.tolist() == [M.EXIT_REVERSE, EXIT_FALLBACK]
    assert t.px_out[0] == 106.0 and t.px_in[1] == 106.0 and t.in_row[1] == t.out_row[0] == 11


def test_ignore_mode_keeps_the_trade():
    t = sim(REVERSAL, mgmt="ignore")
    assert t.dir.tolist() == [1] and t.why.tolist() == [EXIT_STOP] and t.px_out.tolist() == [105.0]


def test_reversal_blocked_keeps_the_old_trade():
    blk = [0] * 11 + [1]
    t = sim(REVERSAL, blocked=blk)
    assert t.dir.tolist() == [1] and t.why.tolist() == [EXIT_STOP]


def test_same_direction_signal_moves_the_bracket():
    # long at E with rr 4 (stop 106, target 126), then a second long pattern X0..X4 below 126:
    # tv moves the bracket to X4's (stop 118); F trades 117 -> stopped at 118 - 1
    xs = [bar(113, 114, lo=112, hi=115), bar(114, 118, lo=113, hi=119), bar(118, 119, lo=117, hi=120),
          bar(119, 121, lo=118, hi=122), bar(121, 122, lo=118, hi=125)]
    bars = SETUP + [E] + xs + [bar(122, 117, lo=117, hi=122)]
    tv = sim(bars, rr=4.0)
    assert (tv.why.tolist(), tv.px_out.tolist(), tv.out_row.tolist()) == ([EXIT_STOP], [117.0], [11])
    assert sim(bars, rr=4.0, mgmt="ignore").why.tolist() == [EXIT_FALLBACK]  # old stop 106 never hit


def test_tv_fill_mode_touch_and_no_slip():
    touch = bar(114, 118, lo=113, hi=118)
    assert sim(SETUP + [E, touch], slip=0.0).why.tolist() == [EXIT_FALLBACK]  # project: needs 119
    t = sim(SETUP + [E, touch], slip=0.0, fill="tv")
    assert (t.px_in.tolist(), t.px_out.tolist(), t.why.tolist()) == ([111.0], [118.0], [EXIT_TARGET])
    both = bar(114, 118, lo=105, hi=118)  # open nearer the high: up first, target before stop
    assert sim(SETUP + [E, both], slip=0.0, fill="tv").why.tolist() == [EXIT_TARGET]
    both_low = bar(108, 118, lo=105, hi=118)  # open nearer the low: stop first
    assert sim(SETUP + [E, both_low], slip=0.0, fill="tv").why.tolist() == [EXIT_STOP]
    gap = bar(120, 121, lo=119, hi=122)  # target gapped: filled at the open
    assert sim(SETUP + [E, gap], slip=0.0, fill="tv").px_out.tolist() == [120.0]


def test_entry_blocked_flat_new_day_contract():
    assert len(sim(SETUP + [E, RUN], blocked=[0, 0, 0, 0, 0, 1, 0])) == 0
    assert len(sim(SETUP + [E, RUN], flat=5)) == 0
    assert sim(SETUP + [E, RUN], flat=6).why.tolist() == [EXIT_TIME]
    assert len(sim(SETUP + [E, RUN], day=[0, 0, 0, 0, 0, 1, 1])) == 0  # next bar is another day
    assert len(sim(SETUP + [E, RUN], day=[0, 0, 1, 1, 1, 1, 1])) == 0  # pattern spans two days
    assert len(sim(SETUP + [E, RUN], contract=[0, 0, 0, 0, 0, 1, 1])) == 0


def test_short_mirror_and_direction_filter():
    flip = lambda bs: [[(300 - o, 300 - l, 300 - h, 300 - c) for o, h, l, c in b] for b in bs]
    bars = SETUP + [E, RUN]
    a = sim(bars, direction="long")
    b = sim(flip(bars), direction="short")
    assert len(sim(flip(bars), direction="long")) == 0
    assert (b.dir.tolist(), b.px_in.tolist(), b.px_out.tolist()) == ([-1], [300 - a.px_in[0]], [300 - a.px_out[0]])


# --- random walks: reference, look-ahead and mirror -------------------------------------------------

def walk(n, seed):
    rng = np.random.default_rng(seed)
    c = 1000 + np.cumsum(rng.integers(-6, 7, n))
    o = np.concatenate([[1000], c[:-1]]) + rng.integers(-1, 2, n)
    h = np.maximum(o, c) + rng.integers(0, 4, n)
    lo = np.minimum(o, c) - rng.integers(0, 4, n)
    return [[(float(a), float(b), float(x), float(d))] for a, b, x, d in zip(o, h, lo, c)]


CASES = [{}, {"mgmt": "ignore"}, {"fill": "tv"}, {"mom_dir": "with", "rr": 1.0, "stop_buf": 2},
         {"direction": "short", "rr": 3.0, "min_risk": 3}, {"mult": 2.0, "body_pct": 40.0, "fill": "tv", "rr": 1.5}]


@pytest.mark.parametrize("seed", [1, 2, 3])
@pytest.mark.parametrize("kw", CASES)
@pytest.mark.parametrize("slip,pessimistic", [(1.0, True), (0.0, False)])
def test_engine_matches_reference_on_walks(seed, kw, slip, pessimistic):
    bars = walk(10000, seed)
    eng = sim(bars, slip=slip, pessimistic=pessimistic, **kw)
    assert len(eng) > 10
    if not kw:
        assert len(eng) > 4 * 1 + 16  # more than run_trades' first buffer: the regrow path ran
    cfg = M.config(**({"body_pct": 30.0} | kw))
    cfg[M.C_TF] = 0
    ref = pd.DataFrame(R.trades(_Mk(bars), cfg, slip=slip, pessimistic=pessimistic), columns=COLS)
    assert np.array_equal(eng[COLS].to_numpy(float), ref[COLS].to_numpy(float))


@pytest.mark.parametrize("seed", [1, 2])
@pytest.mark.parametrize("kw", [{}, {"fill": "tv"}])
def test_no_look_ahead(seed, kw):
    bars = walk(3000, seed)
    full = sim(bars, **kw)
    for cut in [700, 1500, 2400]:
        part = sim(bars[:cut], **kw)
        done = full[full.out_row < cut - 1]
        assert part.iloc[:len(done)].equals(done.reset_index(drop=True))


@pytest.mark.parametrize("seed", [4, 5])
def test_mirror(seed):
    bars = walk(3000, seed)
    flip = [[(2000 - o, 2000 - l, 2000 - h, 2000 - c) for o, h, l, c in b] for b in bars]
    a = sim(bars, direction="long")
    b = sim(flip, direction="short")
    assert len(a) > 10 and a.in_row.tolist() == b.in_row.tolist() and a.out_row.tolist() == b.out_row.tolist()
    assert np.allclose(a.px_in, 2000 - b.px_in) and np.allclose(a.px_out, 2000 - b.px_out)


# --- real data: engine == reference ---------------------------------------------------------------

@pytest.mark.skipif(not BARS_DIR.exists(), reason="no CL data")
def test_engine_matches_reference_on_real_data():
    from propfirm_backtest import search as S
    from propfirm_data.eia_calendar import load_releases
    for start, end in [("2012-02-01", "2012-03-01"), ("2020-04-01", "2020-05-01"), ("2021-10-01", "2021-11-01")]:
        m = B.load_minutes(start=start, end=end)
        cal = S.Calendar(m)
        mk = M.Market(m, cal.days, load_releases(), strict_expiry=True)
        for tf in M.TIMEFRAMES:
            for kw, slip, pess in [({}, 1.0, True), ({"mgmt": "ignore", "stop_buf": 2, "rr": 1.5,
                                                     "session": "newyork", "direction": "short"}, 0.0, False),
                                   ({"fill": "tv", "mom_dir": "with", "min_risk": 5}, 0.0, True)]:
                cfg = M.config(tf=tf, body_pct=30.0, **kw)
                t = mk.trades(cfg, slip=slip, pessimistic=pess)
                eng = list(zip(*[a.tolist() for a in t]))
                ref = [(int(a), int(b), int(c), int(d), float(e), float(f), float(g), int(h))
                       for a, b, c, d, e, f, g, h in R.trades(mk, cfg, slip=slip, pessimistic=pess)]
                assert eng == ref, (start, tf, kw)
                assert len(eng) > 0, (start, tf, kw)


def test_tv_fill_mae_ignores_the_leg_after_the_exit():
    up_first = bar(112, 113, lo=105, hi=118)  # open nearer the high: target 118 first, low 105 comes after
    t = sim(SETUP + [bar(111, 112, lo=111, hi=112), up_first], slip=0.0, fill="tv")
    assert t.why.tolist() == [EXIT_TARGET] and t.mae.tolist() == [0.0]  # fill 111, worst seen = open 112
    low_first = bar(110, 118, lo=107, hi=118)  # open nearer the low: dips to 107 (stop 106 holds), then target
    t = sim(SETUP + [bar(111, 112, lo=111, hi=112), low_first], slip=0.0, fill="tv")
    assert t.why.tolist() == [EXIT_TARGET] and t.mae.tolist() == [4.0]


def test_safety_net_closes_on_a_new_contract_or_at_the_end_of_data():
    bars = SETUP + [E, bar(113, 114, lo=112, hi=115), bar(114, 115, lo=113, hi=116)]
    t = sim(bars, contract=[0] * 7 + [1])
    assert t.why.tolist() == [EXIT_FALLBACK] and t.out_row.tolist() == [6] and t.px_out.tolist() == [113.0]
    t = sim(bars[:-1])
    assert t.why.tolist() == [EXIT_FALLBACK] and t.px_out.tolist() == [113.0]
    for kw in ({}, {"fill": "tv"}):
        assert sim(bars, day=[0] * 7 + [1], **kw).why.tolist() == [EXIT_FALLBACK]


def test_kernels_match_trades():
    from propfirm_backtest import propsim as P
    bars = walk(6000, 7)
    day = np.arange(len(bars)) // 1000
    bar_args, minute_args, nd = inputs(bars, day=day)
    cfgs = np.stack([M.config(**({"body_pct": 30.0} | kw)) for kw in CASES])
    cfgs[:, M.C_TF] = 0
    pnl, _ = M.daily_kernel(cfgs, nd, bar_args, minute_args, 1.0, True)
    met = M.grid_kernel(cfgs, nd, np.zeros(nd, np.int64), 1, np.zeros(0, np.int64), np.zeros(nd), bar_args,
                        minute_args, 1.0, True, np.zeros((1, 1)), np.zeros((1, 1)), P.BLOCK, False)[0]
    for k, cfg in enumerate(cfgs):
        t = M.run_trades(cfg, nd, bar_args, minute_args, 1.0, True)
        usd = P.trade_pnl_usd(t[3], t[4], t[5])
        assert len(usd) > 10 and met[k, 0] == len(usd)
        assert np.allclose(pnl[k], np.bincount(t[0], weights=usd, minlength=nd))
        assert np.isclose(met[k, 4], usd.sum())
