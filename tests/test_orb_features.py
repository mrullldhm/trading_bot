import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from propfirm_backtest import bars as B
from propfirm_backtest import orb_engine as E
from propfirm_backtest import orb_features as F

sys.path.insert(0, str(Path(__file__).parent))
from test_orb_engine import random_market  # noqa: E402


def build(df):
    m = B.build_minutes(df)
    f = E.Front(m)
    days = np.unique(f.trading_day)
    return f, days


@pytest.fixture(scope="module")
def market():
    df, _ = random_market(21, n_days=40, roll_day=25)
    return df


def test_features_use_only_prior_sessions(market):
    f, days = build(market)
    base = F.Sessions(f, days, "et0900")
    d = 18
    day = pd.Timestamp(days[d], unit="D").date()
    et = market["ts_event_utc"].dt.tz_convert(E.ET)
    today = (et.dt.date == day) & (et.dt.hour >= 9)
    bumped = market.copy()
    for col in ["open_ticks", "high_ticks", "low_ticks", "close_ticks"]:
        bumped.loc[today, col] += np.where(np.arange(today.sum()) % 2, 37, -55)
    bumped.loc[today, "high_ticks"] = bumped.loc[today, ["open_ticks", "high_ticks", "close_ticks"]].max(axis=1) + 3
    bumped.loc[today, "low_ticks"] = bumped.loc[today, ["open_ticks", "low_ticks", "close_ticks"]].min(axis=1) - 3
    f2, days2 = build(bumped)
    after = F.Sessions(f2, days2, "et0900")
    assert after.high[d] != base.high[d]  # the perturbation really changed today's session
    for name in ["atr14", "stretch", "nr4", "nr7", "inside", "idnr4", "piv_lo", "piv_hi"]:
        a, b = getattr(base, name), getattr(after, name)
        np.testing.assert_array_equal(a[:d + 1], b[:d + 1], err_msg=name)  # today and earlier unchanged
    assert not np.allclose(base.atr14[d + 1:d + 5], after.atr14[d + 1:d + 5])  # later days do change


def test_atr_and_stretch_values(market):
    f, days = build(market)
    s = F.Sessions(f, days, "et0900")
    idx = np.flatnonzero(s.valid)
    k = 20
    d = idx[k]
    prev = idx[k - 14:k]
    tr = []
    for p in prev:
        q = idx[np.searchsorted(idx, p) - 1]
        assert s.contract[p] == s.contract[q]
        tr.append(max(s.high[p], s.close[q]) - min(s.low[p], s.close[q]))
    assert s.atr14[d] == pytest.approx(np.mean(tr))
    pr = idx[k - 10:k]
    assert s.stretch[d] == pytest.approx(np.mean(np.minimum(s.high[pr] - s.open[pr], s.open[pr] - s.low[pr])))


def test_roll_gap_never_enters_atr_or_pivot(market):
    f, days = build(market)
    s = F.Sessions(f, days, "et0900")
    idx = np.flatnonzero(s.valid)
    k = np.flatnonzero(s.contract[idx][1:] != s.contract[idx][:-1])[0] + 1
    first_new = idx[k]
    assert np.isnan(s.piv_lo[first_new])  # pivot from the old contract is not used on the new one
    assert np.isfinite(s.piv_lo[idx[k + 1]])
    # ATR on the session after the roll = mean of the last 14 same-contract true ranges (roll one skipped)
    H, L, C, K = s.high[idx], s.low[idx], s.close[idx], s.contract[idx]
    trs = [max(H[p], C[p - 1]) - min(L[p], C[p - 1]) for p in range(1, k + 1) if K[p] == K[p - 1]]
    assert s.atr14[idx[k + 1]] == pytest.approx(np.mean(trs[-14:]))


def test_nr_and_inside_flags():
    s = F.Sessions.__new__(F.Sessions)
    n = 9
    s.valid = np.ones(n, bool)
    s.contract = np.zeros(n, int)
    s.high = np.array([110, 112, 111, 110, 109, 120, 125, 118, 130.0])
    s.low = np.array([100, 99, 101, 102, 103, 100, 95, 105, 100.0])
    s.open = s.close = (s.high + s.low) / 2
    s.today_contract = np.zeros(n, int)
    s._derive()
    # session 4 (109/103, range 6) is narrowest of last 4 and 7?, flags appear on session 5
    assert s.nr4[5] and s.inside[4] and s.inside[5]
    assert not s.nr7[5]  # fewer than 7 sessions before it
    assert s.inside[8] and not s.nr4[8]  # session 7 inside session 6, but range 13 not narrowest of 4


def test_relative_volume_excludes_today():
    v = np.arange(1, 17, dtype=float)
    r = F.relative_volume(v, np.ones(16, bool), window=14)
    assert np.isnan(r[13]) and r[14] == pytest.approx(15 / np.mean(np.arange(1, 15)))


def test_a_later_outage_on_day_d_does_not_remove_its_features(market):
    f, days = build(market)
    base = F.Sessions(f, days, "et0900")
    d = 20
    day = pd.Timestamp(days[d], unit="D").date()
    et = market["ts_event_utc"].dt.tz_convert(E.ET)
    after_10 = (et.dt.date == day) & (et.dt.hour >= 10) & (et.dt.hour < 17)
    f2, days2 = build(market[~after_10])  # data stops at 10:00: day d's session becomes unusable
    cut = F.Sessions(f2, days2, "et0900")
    assert base.valid[d] and not cut.valid[d]
    for name in ["atr14", "stretch", "nr4", "nr7", "inside", "piv_lo", "piv_hi"]:
        assert np.array_equal(getattr(base, name)[d], getattr(cut, name)[d], equal_nan=True), name


def test_features_match_independent_reference_around_the_roll(market):
    from propfirm_backtest import orb_family_reference as R
    f, days = build(market)
    s = F.Sessions(f, days, "et0900")
    ref = R.session_features(f, days, "et0900")
    for name in ["atr14", "stretch", "nr4", "nr7", "inside", "idnr4", "piv_lo", "piv_hi"]:
        np.testing.assert_allclose(getattr(s, name).astype(float), ref[name].astype(float), err_msg=name)
    roll = np.flatnonzero(np.diff(s.contract[s.valid]) != 0)
    assert len(roll) == 1
    assert np.isfinite(s.atr14[np.flatnonzero(s.valid)[roll[0] + 2]])  # ATR available right after the roll


def test_session_can_end_on_the_last_row_of_data(market):
    et = market["ts_event_utc"].dt.tz_convert(E.ET)
    last_day = et.dt.date.max()
    cut = market[~((et.dt.date == last_day) & (et.dt.hour * 60 + et.dt.minute >= 14 * 60))]  # data ends 14:00
    f, days = build(cut)
    s = F.Sessions(f, days, "et0900")  # must not raise
    et_cut = cut["ts_event_utc"].dt.tz_convert(E.ET)
    today = cut[(et_cut.dt.date == last_day) & (et_cut.dt.hour >= 9)]
    assert s.valid[-1]
    assert s.high[-1] == today["high_ticks"].max() and s.low[-1] == today["low_ticks"].min()
