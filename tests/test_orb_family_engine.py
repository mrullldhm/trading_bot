import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from propfirm_backtest import bars as B
from propfirm_backtest import orb_engine as E
from propfirm_backtest import orb_family_engine as FE
from propfirm_backtest import orb_family_reference as R

sys.path.insert(0, str(Path(__file__).parent))
from test_orb_engine import at, bars_df, flat_range, random_market  # noqa: E402


def as_floats(trade_list):
    return [tuple(float(x) for x in t) for t in trade_list]


def zab_cfg(mk, anchor="et0900", L=5, entry=FE.IMMEDIATE, atr_x100=0, target_r=10, flat=E.SESSION,
            relvol_x10=0, dirmode=FE.DIR_CANDLE):
    return np.array([mk.table_index(anchor, L), FE.anchor_row(anchor), entry, atr_x100, target_r, flat,
                     relvol_x10, dirmode], dtype=np.int64)


def zab_market(df, eia=None):
    m = B.build_minutes(df)
    return FE.ZabMarket(m, np.unique(m.trading_day[m.front]), eia)


def trades(mk, c, **kw):
    return list(zip(*[x.tolist() for x in mk.trades(c, **kw)]))


# --- ZAB hand-made -------------------------------------------------------------------------------

def candle(direction):
    """09:00-09:05 range 7000..7010, opening 7002 and closing 7008 (up) or the reverse (down)."""
    o, cl = (7002, 7008) if direction > 0 else (7008, 7002)
    rows = [("09:00", o, 7010, 7000, 7005)] + [(f"09:0{k}", 7005, 7006, 7004, 7005) for k in range(1, 4)]
    return rows + [("09:04", 7005, 7007, 7003, cl)]


def test_zab_immediate_long_after_up_candle_with_10r_target():
    rows = candle(+1) + [at(0, 7008, 7012, 7007, 7011), at(1, 7011, 7200, 7010, 7190)]
    mk = zab_market(bars_df(rows))
    (t,) = trades(mk, zab_cfg(mk))
    # fill 09:05 open 7008 + 1 = 7009; stop 6999 -> R 10; target 7109 needs 7110
    assert t[3] == 1 and t[4] == 7009 and t[5] == 7109 and t[7] == E.EXIT_TARGET


def test_zab_down_candle_shorts_and_doji_skips():
    rows = candle(-1) + [at(0, 7002, 7003, 6990, 6991), at(1, 6991, 6992, 6980, 6985)]
    mk = zab_market(bars_df(rows))
    (t,) = trades(mk, zab_cfg(mk, target_r=0, flat=60))
    assert t[3] == -1 and t[4] == 7001
    assert trades(mk, zab_cfg(mk, dirmode=FE.DIR_LONG)) == []  # down candle + long-only = no trade
    doji = candle(+1)
    doji[-1] = ("09:04", 7005, 7007, 7003, 7002)  # closes at the first open
    mk = zab_market(bars_df(doji + [at(0, 7008, 7012, 7007, 7011)]))
    assert trades(mk, zab_cfg(mk)) == []


def test_zab_breakout_waits_for_the_candle_side_edge():
    rows = candle(+1) + [at(0, 7005, 7008, 6990, 6995),  # breaks the LOW first: ignored (up candle)
                         at(1, 6995, 7012, 6994, 7010),  # breaks 7011 = high + 1: long fill 7012
                         at(2, 7010, 7015, 7009, 7014)]
    mk = zab_market(bars_df(rows))
    (t,) = trades(mk, zab_cfg(mk, entry=FE.BREAKOUT, target_r=0, flat=60))
    assert t[3] == 1 and t[4] == 7012 and t[1] == 6


def test_zab_eia_block_cancels_the_day():
    rows = candle(+1) + [at(0, 7008, 7012, 7007, 7011)]
    eia = pd.DataFrame({"date": [pd.Timestamp("2025-11-04")], "minute_et": [9 * 60 + 10]})  # block 08:55-09:25
    mk = zab_market(bars_df(rows), eia)
    assert trades(mk, zab_cfg(mk)) == []


# --- ZAB random cross-check --------------------------------------------------------------------------

@pytest.fixture(scope="module")
def random_zab():
    df, eia = random_market(31, n_days=45, roll_day=30)
    return zab_market(df, eia), eia


def test_zab_engine_matches_reference(random_zab):
    mk, eia = random_zab
    rng = np.random.default_rng(4)
    total = 0
    for _ in range(60):
        anchor = str(rng.choice(FE.FAMILY_ANCHORS))
        L = int(rng.choice(FE.ZabMarket.RANGE_LENGTHS))
        args = dict(entry=int(rng.integers(0, 2)), atr_x100=int(rng.choice([0, 5, 10, 20])),
                    target_r=int(rng.choice([0, 10])), flat_off=int(rng.choice([120, 240, E.SESSION])),
                    relvol_x10=int(rng.choice([0, 10, 15])), dirmode=int(rng.integers(0, 3)))
        pess = bool(rng.integers(0, 2))
        c = zab_cfg(mk, anchor, L, args["entry"], args["atr_x100"], args["target_r"], args["flat_off"],
                    args["relvol_x10"], args["dirmode"])
        got = trades(mk, c, pessimistic=pess)
        want = R.run_zab(mk.f, mk.days, anchor, L, eia=eia, pessimistic=pess, **args)
        assert as_floats(got) == as_floats(want), (anchor, L, args, pess)
        total += len(got)
    assert total > 100  # not vacuous


# --- Crabel ------------------------------------------------------------------------------------------

def crabel_market(df, eia=None):
    m = B.build_minutes(df)
    return FE.CrabelMarket(m, np.unique(m.trading_day[m.front]), eia)


def crabel_cfg(mk, anchor="et0900", L=5, stretch_x100=100, setup=FE.SETUP_NONE, window=120, flat=E.SESSION,
               stop=E.OPPOSITE, dirpol=E.BOTH1):
    return np.array([mk.table_index(anchor, L), FE.anchor_row(anchor), stretch_x100, setup, window, flat, stop,
                     dirpol], dtype=np.int64)


def test_crabel_fills_at_range_plus_stretch_and_stops_at_the_other_level():
    df, eia = random_market(41, n_days=30, roll_day=29)
    mk = crabel_market(df, eia)
    tb, an = mk.table_index("et0900", 5), FE.anchor_row("et0900")
    t = mk.trades(crabel_cfg(mk, window=100_000), pessimistic=False)
    assert len(t[0]) >= 5
    for q in range(len(t[0])):
        d, side = t[0][q], t[3][q]
        s = max(1.0, np.ceil(mk.stretch[an, d]))
        long_lvl, short_lvl = mk.t.hi[tb, d] + s, mk.t.lo[tb, d] - s
        if side == 1:
            assert t[4][q] >= long_lvl + 1  # level + 1 tick slippage (more if price gapped through)
            assert t[7][q] != E.EXIT_STOP or t[5][q] <= short_lvl - 1  # stop = the short trigger level
        else:
            assert t[4][q] <= short_lvl - 1
            assert t[7][q] != E.EXIT_STOP or t[5][q] >= long_lvl + 1


def test_crabel_engine_matches_reference():
    df, eia = random_market(43, n_days=45, roll_day=30)
    mk = crabel_market(df, eia)
    rng = np.random.default_rng(6)
    total = 0
    for _ in range(50):
        anchor = str(rng.choice(FE.FAMILY_ANCHORS))
        L = int(rng.choice(FE.CrabelMarket.RANGE_LENGTHS))
        args = dict(stretch_x100=int(rng.choice([50, 75, 100, 125, 150])), setup=int(rng.integers(0, 5)),
                    window=int(rng.choice([10, 30, 120, 100_000])), flat_off=int(rng.choice([240, E.SESSION])),
                    stop_type=int(rng.choice([E.OPPOSITE, E.MID])), dirpol=int(rng.choice([E.BOTH1, E.LONG, E.SHORT])))
        pess = bool(rng.integers(0, 2))
        c = crabel_cfg(mk, anchor, L, args["stretch_x100"], args["setup"], args["window"], args["flat_off"],
                       args["stop_type"], args["dirpol"])
        got = trades(mk, c, pessimistic=pess)
        want = R.run_crabel(mk.f, mk.days, anchor, L, eia=eia, pessimistic=pess, **args)
        assert as_floats(got) == as_floats(want), (anchor, L, args, pess)
        total += len(got)
    assert total > 100


# --- Fisher ACD --------------------------------------------------------------------------------------

def acd_market(df, eia=None):
    m = B.build_minutes(df)
    return FE.AcdMarket(m, np.unique(m.trading_day[m.front]), eia)


def acd_cfg(mk, anchor="et0900", L=5, a_x1000=100, c_x1000=150, acc_x100=50, pivot=0, c_on=1, flat=E.SESSION,
            dirmode=FE.DIR_CANDLE):
    return np.array([mk.table_index(anchor, L), FE.anchor_row(anchor), L, a_x1000, c_x1000, acc_x100, pivot, c_on,
                     flat, dirmode], dtype=np.int64)


def test_acd_engine_matches_reference():
    df, eia = random_market(47, n_days=45, roll_day=30)
    mk = acd_market(df, eia)
    rng = np.random.default_rng(8)
    total = 0
    for _ in range(60):
        anchor = str(rng.choice(FE.FAMILY_ANCHORS))
        L = int(rng.choice(FE.AcdMarket.RANGE_LENGTHS))
        ac = [(50, 100), (75, 125), (100, 150), (125, 200)][int(rng.integers(0, 4))]
        args = dict(a_x1000=ac[0], c_x1000=ac[1], acc_x100=int(rng.choice([25, 50, 100])),
                    pivot=int(rng.integers(0, 2)), c_on=int(rng.integers(0, 2)),
                    flat_off=int(rng.choice([240, E.SESSION])), dirmode=int(rng.integers(0, 3)))
        pess = bool(rng.integers(0, 2))
        c = acd_cfg(mk, anchor, L, args["a_x1000"], args["c_x1000"], args["acc_x100"], args["pivot"], args["c_on"],
                    args["flat_off"], args["dirmode"])
        got = trades(mk, c, pessimistic=pess)
        want = R.run_acd(mk.f, mk.days, anchor, L, eia=eia, pessimistic=pess, **args)
        assert as_floats(got) == as_floats(want), (anchor, L, args, pess)
        total += len(got)
    assert total > 50


def test_acd_acceptance_failure_and_c_reversal_on_real_shapes():
    """Every A trade enters after `need` full bars beyond A; every second trade is a C reversal on the
    other side, entered after the first was stopped at B."""
    df, eia = random_market(47, n_days=45, roll_day=30)
    mk = acd_market(df, eia)
    c = acd_cfg(mk, L=10, a_x1000=50, c_x1000=100, acc_x100=50)
    t = mk.trades(c)
    tb, an = mk.table_index("et0900", 10), FE.anchor_row("et0900")
    seen_c = 0
    for d in np.unique(t[0]):
        q = np.flatnonzero(t[0] == d)
        A = max(1.0, np.ceil(0.05 * mk.atr[an, d]))
        H, Lo = mk.t.hi[tb, d], mk.t.lo[tb, d]
        side = t[3][q[0]]
        prev = range(t[1][q[0]] - 5, t[1][q[0]])  # the 5 bars before the entry minute were all beyond A
        assert all((mk.f.low[j] >= H + A) if side == 1 else (mk.f.high[j] <= Lo - A) for j in prev)
        if len(q) == 2:
            seen_c += 1
            assert t[7][q[0]] == E.EXIT_STOP and t[3][q[1]] == -side and t[1][q[1]] > t[2][q[0]]
    assert len(np.unique(t[0])) > 5


def test_acd_bar_gapping_through_b_and_c_counts_for_c():
    """need = 1: the first bar after the range is wholly above A-up (accepted), the next one gaps
    below B and is wholly below C-down: the C short must enter on the very next open."""
    rows = flat_range(start="09:00", n=5, hi=7010, lo=7000)
    rows += [at(0, 7030, 7034, 7030, 7032),   # whole bar above A-up (7010 + A)
             at(1, 7031, 7033, 7030, 7032),   # long filled here at the open
             at(2, 6960, 6962, 6950, 6955),   # gaps below B (6999) and wholly below C-down
             at(3, 6954, 6956, 6940, 6945),   # C short fills at this open
             at(4, 6945, 6946, 6930, 6935)]
    df = bars_df(rows)
    mk = acd_market(df)
    an = FE.anchor_row("et0900")
    d = 0
    mk.atr[an, d] = 100.0  # A = 5, C = 10 ticks with 0.05 / 0.10
    t = trades(mk, acd_cfg(mk, L=5, a_x1000=50, c_x1000=100, acc_x100=20))
    assert [x[3] for x in t] == [1, -1]
    assert t[0][7] == E.EXIT_STOP and t[1][1] == t[0][2] + 1 and t[1][4] == 6953
