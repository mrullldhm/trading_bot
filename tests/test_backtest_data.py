import numpy as np
import pandas as pd
import pytest

from propfirm_backtest import bars as B
from propfirm_backtest import indicators as I
from propfirm_backtest import propsim as P


def minutes_df(times, sym="CLZ5", cont="CL.v.0", price=7000, vol=10):
    ts = pd.to_datetime(times, utc=True)
    n = len(ts)
    p = np.full(n, price) if np.isscalar(price) else np.array(price)
    return pd.DataFrame({"ts_event_utc": ts, "continuous_symbol": cont, "raw_symbol": sym,
                         "open_ticks": p, "high_ticks": p + 2, "low_ticks": p - 2, "close_ticks": p,
                         "volume": vol})


def et(times):
    """ET wall-clock strings -> UTC strings (Nov 2025: EST = UTC-5)."""
    return [pd.Timestamp(t, tz="America/New_York").tz_convert("UTC") for t in times]


def test_bars_split_at_1605_and_never_span_contracts():
    df = minutes_df(et(["2025-11-04 15:58", "2025-11-04 16:03", "2025-11-04 16:06", "2025-11-04 16:20"]))
    m = B.build_minutes(df)
    b = B.build_bars(m, 60)
    # 15:58 -> 15:00 bucket; 16:03 -> [16:00,16:05); 16:06 + 16:20 -> after the 16:05 split
    assert list(b.start) == [0, 1, 2]
    assert list(b.end) == [1, 2, 4]
    two = B.build_minutes(pd.concat([df, minutes_df(et(["2025-11-04 16:30"]), sym="CLF6")]))
    assert len(B.build_bars(two, 60)) == 4  # new contract = new bar even in the same hour


def test_session_masks_and_cutoff():
    df = minutes_df(et(["2025-11-04 08:00", "2025-11-04 15:59", "2025-11-04 16:00", "2025-11-04 16:05",
                        "2025-11-04 19:00", "2025-11-05 02:56"]))
    m = B.build_minutes(df)
    ny, _, ny_cut = B.session_mask(m, "newyork")
    assert list(ny) == [True, True, True, False, False, False]
    assert list(ny_cut) == [False, False, True, False, False, False]  # last 5 min before 16:05
    asia, inst, asia_cut = B.session_mask(m, "asian")
    assert list(asia) == [False, False, False, False, True, True]
    assert inst[4] == inst[5]  # 19:00 and 02:56 next day = same Asian night
    assert asia_cut[5]


def test_roll_schedule_cutoff_and_front_flag():
    old = minutes_df(et(["2025-11-18 18:50", "2025-11-18 18:56", "2025-11-18 19:30"]), sym="CLZ5")
    old.loc[2, "continuous_symbol"] = "CL.v.1"  # after the roll the old contract is v.1
    new = minutes_df(et(["2025-11-18 19:00", "2025-11-18 19:01"]), sym="CLF6")  # 00:00 UTC = 19:00 EST
    new_v1 = minutes_df(et(["2025-11-10 10:00"]), sym="CLF6", cont="CL.v.1")  # warm-up history
    m = B.build_minutes(pd.concat([old, new, new_v1]))
    assert m.contracts == ["CLZ5", "CLF6"]
    z = m.contract == 0
    assert list(m.roll_cutoff[z]) == [False, True, True]  # from 18:55 ET onwards
    assert list(m.front[m.contract == 1]) == [False, True, True]  # warm-up minute not tradable


def test_ema_warmup_and_restart_per_contract():
    class Bars:  # minimal stand-in
        close = np.array([10.0, 10, 10, 20, 20])
        contract = np.array([0, 0, 0, 1, 1])
    e, ok = I.ema(Bars, 3)
    assert list(ok) == [False, False, True, False, False]
    assert e[3] == 20.0  # restarted on the new contract


def test_vwap_after_and_before_minute():
    hi = np.array([12.0, 22]); lo = np.array([8.0, 18]); cl = np.array([10.0, 20]); vol = np.array([1.0, 3])
    after, before = I._vwap(hi, lo, cl, vol, np.array([1, 1]))
    assert after[0] == 10 and after[1] == pytest.approx((10 + 60) / 4)
    assert np.isnan(before[0]) and before[1] == 10  # known at the start of minute 1


def test_daily_series_tracks_intraday_low():
    pnl, low = P.daily_series(np.array([0, 0]), np.array([100.0, -300.0]), np.array([50.0, 400.0]), 1)
    assert pnl[0] == -200 and low[0] == -300  # 100 banked, then -400 open: 100 - 400


def test_combine_pass_fail_and_trailing_lock():
    days = lambda xs: (np.array(xs, float), np.minimum(np.array(xs, float), 0))
    p, l = days([1000, 1000, 1000])
    assert P._combine_attempt(p, l, np.array([0]), 3)[0:2] == (1, 3)
    p, l = days([-700, -700, -700])
    assert P._combine_attempt(p, l, np.array([0]), 3)[0:2] == (-1, 3)
    # +1500 moves the floor up to -500; a -2100 day (balance -600) breaches the TRAILED floor
    # even though it would not have breached the original -2000 floor
    p, l = days([1500, -2100])
    assert P._combine_attempt(p, l, np.array([0]), 2)[0] == -1
    # consistency: one 2,900 day + 200 = 3,100 total, best day 94% > 55% -> not passed yet
    p, l = days([2900, 200])
    assert P._combine_attempt(p, l, np.array([0]), 2)[0] == 0


def test_trade_pnl_includes_fees():
    assert P.trade_pnl_usd(np.array([1]), np.array([7000.0]), np.array([7010.0]))[0] == pytest.approx(100 - 4.02)


def test_same_symbol_ten_years_apart_are_different_contracts():
    a = minutes_df(et(["2010-07-20 10:00"]), sym="CLQ0")
    a["expiration"] = pd.Timestamp("2010-07-20", tz="UTC")
    b = minutes_df(et(["2020-07-20 10:00"]), sym="CLQ0")
    b["expiration"] = pd.Timestamp("2020-07-21", tz="UTC")
    m = B.build_minutes(pd.concat([a, b]))
    assert len(m.contracts) == 2 and m.contract[0] != m.contract[1]
    assert m.contracts == ["CLQ0@2010-07", "CLQ0@2020-07"]


def test_missing_expiration_is_refused():
    a = minutes_df(et(["2010-07-20 10:00"]), sym="CLQ0")
    a["expiration"] = pd.NaT
    with pytest.raises(ValueError):
        B.build_minutes(a)
