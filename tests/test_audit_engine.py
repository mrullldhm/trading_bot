"""Audit: engine-level proofs on synthetic data (no data dir needed).

- Look-ahead: cutting the data at T (or replacing everything after T) never changes a decision made
  before T, for every ORB-family engine, its day tables and its prior-session features.
- Mirror: reflecting prices (p -> K - p) turns a long-only config into the short-only one, trade for
  trade. A side-specific bug (sign, rounding, tie order) breaks this.
- Zero sum: a long and a short market trade over the same minutes cost exactly 2 x (fee + 2 slips).
- Positive control: a planted post-breakout drift shows up as positive expectancy, growing with the drift.
"""

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from propfirm_backtest import bars as B
from propfirm_backtest import orb_engine as E
from propfirm_backtest import orb_family_engine as FE
from propfirm_backtest import orb_features as F
from propfirm_backtest import orb_search as O
from propfirm_backtest import propsim as P
from propfirm_backtest.family_search import FAMILIES

sys.path.insert(0, str(Path(__file__).parent))
from test_orb_engine import cfg as orb_cfg  # noqa: E402
from test_orb_engine import random_market  # noqa: E402

MARKETS = {"orb": E.Market, "zab": FE.ZabMarket, "crabel": FE.CrabelMarket, "acd": FE.AcdMarket}
ROLL_DAY = 15  # random_market's daytime roll (real rolls are at night; see the truncation test)


def build(df, days, eia, name):
    m = B.build_minutes(df)
    return MARKETS[name](m, days, eia)


def random_cfgs(name, n, seed):
    rng = np.random.default_rng(seed)
    if name == "orb":
        return [orb_cfg(anchor=str(rng.choice(list(E.ANCHORS))), L=int(rng.choice(E.RANGE_LENGTHS)),
                        trigger=int(rng.integers(0, 3)), buf=int(rng.choice([0, 2])),
                        stop_type=int(rng.integers(0, 3)), stop_ticks=int(rng.choice([15, 20, 30])),
                        target_x10=int(rng.choice([0, 10, 15, 20, 30])), window=int(rng.choice([30, 60, 120])),
                        flat=int(rng.choice([60, 120, 240, E.SESSION])), dirpol=int(rng.integers(0, 4)),
                        width=int(rng.integers(0, 4)), be=int(rng.integers(0, 2))) for _ in range(n)]
    grid = O.Grid(family=FAMILIES[name])
    return list(grid.cfg[rng.choice(grid.n, n, replace=False)])


def keyed(mk, t):
    """Trades as comparable tuples: (entry minute, exit minute, side, entry px, exit px, reason)."""
    return [(int(mk.f.tmin[i]), int(mk.f.tmin[o]), int(d), float(a), float(b), int(w))
            for i, o, d, a, b, w in zip(t[1], t[2], t[3], t[4], t[5], t[7])]


def cut_times(df, days, rng, n):
    """Random cut minutes (UTC ns) inside daytime hours, away from the daytime roll in random_market."""
    roll_day = pd.Timestamp(int(days[ROLL_DAY]), unit="D")
    out = []
    while len(out) < n:
        d = pd.Timestamp(int(rng.choice(days)), unit="D")
        if d == roll_day:
            continue
        hhmm = int(rng.integers(8 * 60, 16 * 60))
        out.append(pd.Timestamp(f"{d.date()} {hhmm // 60:02d}:{hhmm % 60:02d}", tz=E.ET).tz_convert("UTC"))
    return out


def perturb(df, T, how, rng):
    """Data as a live trader at minute T could know it: cut at T, or with a different future after T."""
    before = df[df["ts_event_utc"] < T]
    if how == "cut":
        return before
    after = df[df["ts_event_utc"] >= T].copy()
    shift = rng.integers(-40, 41, len(after)).cumsum().astype(float)  # an unrelated random path
    for col in ["open_ticks", "high_ticks", "low_ticks", "close_ticks"]:
        after[col] = after[col] + shift
    after["high_ticks"] = after[["open_ticks", "high_ticks", "low_ticks", "close_ticks"]].max(axis=1)
    after["low_ticks"] = after[["open_ticks", "high_ticks", "low_ticks", "close_ticks"]].min(axis=1)
    return pd.concat([before, after], ignore_index=True)


def check_future_independence(name, how, n_random=6, n_targeted=15):
    """Returns (entries compared on the cut day, closed trades compared). Raises AssertionError on a leak.
    Cuts: random daytime minutes, plus minutes just after real entries (the decision-dense spots)."""
    df, eia = random_market(7, n_days=30, roll_day=ROLL_DAY)
    full_m = B.build_minutes(df)
    days = np.unique(full_m.trading_day[full_m.front])
    full = MARKETS[name](full_m, days, eia)
    rng = np.random.default_rng(11)
    cfgs = random_cfgs(name, 25, 3)
    runs = {tuple(c): keyed(full, full.trades(c)) for c in cfgs}
    entries = sorted({x[0] for v in runs.values() for x in v})
    roll_day = int(days[ROLL_DAY])
    targeted = [e for e in rng.permutation(entries) if (e // 1440) != roll_day][:n_targeted]
    cuts = cut_times(df, days, rng, n_random) + [
        pd.Timestamp(int(e + rng.integers(1, 30)) * E.NS_PER_MIN, tz="UTC") for e in targeted]
    same_day = closed = 0
    for T in cuts:
        t_min = T.value // E.NS_PER_MIN
        part = build(perturb(df, T, how, rng), days, eia, name)
        for c in cfgs:
            a = runs[tuple(c)]
            b = keyed(part, part.trades(c))
            ea = [(x[0], x[2], x[3]) for x in a if x[0] < t_min]
            assert ea == [(x[0], x[2], x[3]) for x in b if x[0] < t_min], (name, how, T, c)
            same_day += sum(1 for x in ea if t_min - x[0] < 24 * 60)
            done_a = [x for x in a if x[1] < t_min]
            done_b = [x for x in b if x[1] < t_min and not (how == "cut" and x[5] == E.EXIT_FALLBACK)]
            assert done_a == done_b, (name, how, T, c)
            closed += len(done_a)
    return same_day, closed


@pytest.mark.parametrize("name", list(MARKETS))
@pytest.mark.parametrize("how", ["cut", "scramble"])
def test_no_decision_before_t_depends_on_data_after_t(name, how):
    same_day, closed = check_future_independence(name, how)
    assert same_day >= 20 and closed >= 200  # the comparisons are not vacuous


def test_a_planted_look_ahead_is_caught(monkeypatch):
    """Control for the test above: a width filter that peeks at the next 19 days must be detected."""
    def leaky(width, valid):
        v = pd.Series(np.where(valid, width, np.nan)).dropna()
        med = v[::-1].rolling(E.WIDTH_LOOKBACK, min_periods=1).median()[::-1]
        out = np.full(len(width), np.nan)
        out[v.index] = (v / med).to_numpy()
        return out
    monkeypatch.setattr(E, "width_ratio", leaky)
    with pytest.raises(AssertionError):
        check_future_independence("orb", "scramble")


def test_prior_session_features_and_day_tables_ignore_the_future():
    df, eia = random_market(8, n_days=30, roll_day=ROLL_DAY)
    full_m = B.build_minutes(df)
    days = np.unique(full_m.trading_day[full_m.front])
    full = FE.AcdMarket(full_m, days, eia)
    rng = np.random.default_rng(5)
    for T in cut_times(df, days, rng, 8):
        part = FE.AcdMarket(B.build_minutes(perturb(df, T, "scramble", rng)), days, eia)
        today = int(np.searchsorted(days, (T.tz_convert(E.ET).tz_localize(None).normalize()
                                           - pd.Timestamp("1970-01-01")).days))
        k = slice(0, today + 1)  # days up to and including the cut day: features come from earlier days
        for a, b in zip(full.sessions, part.sessions):
            for attr in ["atr14", "stretch", "nr4", "nr7", "inside", "idnr4", "piv_lo", "piv_hi"]:
                np.testing.assert_array_equal(getattr(a, attr)[k], getattr(b, attr)[k], err_msg=f"{attr} {T}")
        k = slice(0, today)  # day tables of days that ended before the cut day
        np.testing.assert_array_equal(full.t.valid[:, k], part.t.valid[:, k])
        np.testing.assert_array_equal(full.t.ratio[:, k], part.t.ratio[:, k])
        np.testing.assert_array_equal(F.relative_volume(full.t.rvol[0], full.t.valid[0])[k],
                                      F.relative_volume(part.t.rvol[0], part.t.valid[0])[k])


# --- mirror ---------------------------------------------------------------------------------------

K = 20_000.0


def mirror(df):
    out = df.copy()
    out["open_ticks"], out["close_ticks"] = K - df["open_ticks"], K - df["close_ticks"]
    out["high_ticks"], out["low_ticks"] = K - df["low_ticks"], K - df["high_ticks"]
    return out


def one_side(name, c, side):
    """The same config, long-only (side=1) or short-only (side=-1)."""
    c = np.array(c)
    if name in ("orb", "crabel"):
        col = E.C_DIRPOL if name == "orb" else FE.C_DIR
        c[col] = E.LONG if side == 1 else E.SHORT
    elif name == "zab":
        c[FE.Z_DIR] = FE.DIR_LONG if side == 1 else FE.DIR_SHORT
    else:
        c[FE.A_DIR] = FE.DIR_LONG if side == 1 else FE.DIR_SHORT
    return c


@pytest.mark.parametrize("name", list(MARKETS))
@pytest.mark.parametrize("pessimistic", [True, False])
def test_mirror_long_equals_short(name, pessimistic):
    df, eia = random_market(9, n_days=30, roll_day=ROLL_DAY)
    m = B.build_minutes(df)
    days = np.unique(m.trading_day[m.front])
    orig = MARKETS[name](m, days, eia)
    refl = build(mirror(df), days, eia, name)
    for c in random_cfgs(name, 40, 4):
        a = refl.trades(one_side(name, c, 1), pessimistic=pessimistic)
        b = orig.trades(one_side(name, c, -1), pessimistic=pessimistic)
        np.testing.assert_array_equal(a[1], b[1])
        np.testing.assert_array_equal(a[2], b[2])
        np.testing.assert_array_equal(a[3], -b[3])
        np.testing.assert_array_equal(a[4], K - b[4])
        np.testing.assert_array_equal(a[5], K - b[5])
        np.testing.assert_array_equal(a[6], b[6])  # adverse excursion is side-free
        np.testing.assert_array_equal(a[7], b[7])
        np.testing.assert_allclose(P.trade_pnl_usd(a[3], a[4], a[5]), P.trade_pnl_usd(b[3], b[4], b[5]))


# --- zero sum ---------------------------------------------------------------------------------------

@pytest.mark.parametrize("slip", [0.0, 1.0, 2.0])
def test_paired_long_short_market_trades_cost_exactly_fees_and_slippage(slip):
    """A long and a short entered at the same minute's open and closed at the same flat minute, through
    the real exit code (hold_position): gross P&L sums to 0; net = -2 x (fee + 2 x slip x $10)."""
    df, eia = random_market(10, n_days=10, roll_day=8)
    mk = E.Market(B.build_minutes(df), np.unique(B.build_minutes(df).trading_day), eia)
    f = mk.f
    rng = np.random.default_rng(1)
    r = [np.empty(1, np.int64), np.empty(1, np.int64), np.empty(1, np.int8), np.empty(1), np.empty(1),
         np.empty(1), np.empty(1, np.int8)]
    n_pairs = 0
    for k in rng.choice(len(f) - 200, 300, replace=False):
        if f.contract[k] != f.contract[k + 120] or f.cut[k:k + 121].any():
            continue
        flat = f.tmin[k] + 60
        pnl = []
        for d in (1, -1):
            fill = f.open[k] + d * slip
            stop = fill - d * 1e6  # never hit
            FE.hold_position(k, False, d, fill, stop, 0.0, False, 0.0, flat, f.contract[k], k,
                             f.tmin, f.open, f.high, f.low, f.close, f.contract, f.cut, slip, True, 0, *r)
            assert r[6][0] == E.EXIT_TIME
            pnl.append(P.trade_pnl_usd(d, r[3][0], r[4][0]))
        assert pnl[0] + pnl[1] == pytest.approx(-2 * (P.FEE_USD + 2 * slip * P.TICK_USD), abs=1e-9)
        n_pairs += 1
    assert n_pairs > 100


# --- positive control ---------------------------------------------------------------------------------

def planted_market(drift, seed=0, n_days=400):
    """Flat noise all day, except a planted trend of `drift` ticks/minute for 60 minutes after the
    09:00-09:15 range, in the direction the range closed (up or down, random per day)."""
    rng = np.random.default_rng(seed)
    frames = []
    price = 7000.0
    for day in pd.bdate_range("2025-01-06", periods=n_days):
        mins = pd.date_range(f"{day.date()} 08:00", f"{day.date()} 16:30", freq="1min", tz=E.ET)
        side = rng.choice([-1, 1])
        step = rng.integers(-3, 4, len(mins)).astype(float)
        mod = mins.hour * 60 + mins.minute
        step[(mod >= 9 * 60 + 10) & (mod < 9 * 60 + 15)] += side * 2  # the range closes on its side
        step[(mod >= 9 * 60 + 15) & (mod < 10 * 60 + 15)] += side * drift
        c = price + step.cumsum()
        price = c[-1]
        o = np.concatenate([[c[0]], c[:-1]])
        frames.append(pd.DataFrame({
            "ts_event_utc": mins.tz_convert("UTC").as_unit("ns"), "continuous_symbol": "CL.v.0",
            "raw_symbol": "CLZ5", "open_ticks": o, "high_ticks": np.maximum(o, c) + 1,
            "low_ticks": np.minimum(o, c) - 1, "close_ticks": c, "volume": 10}))
    df = pd.concat(frames, ignore_index=True)
    m = B.build_minutes(df)
    return E.Market(m, np.unique(m.trading_day[m.front]), None)


def test_planted_edge_is_found_and_grows_with_its_size():
    c = orb_cfg(L=15, trigger=E.CLOSE1, stop_type=E.OPPOSITE, target_x10=0, window=60, flat=60)
    means = []
    for drift in [0.0, 0.5, 1.0, 2.0]:
        mk = planted_market(drift)
        t = mk.trades(c)
        means.append(P.trade_pnl_usd(t[3], t[4], t[5]).mean())
    assert means[0] < 0  # no edge: costs make it lose
    assert means[1] > 0 and means[3] > means[2] > means[1]  # the engine captures a real edge
