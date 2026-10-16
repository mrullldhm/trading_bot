"""propfirm_research.combine (equivalence with the frozen propsim, DLL, accounts) and grid (windows)."""

import numpy as np
import pandas as pd
import pytest

from propfirm_backtest import propsim
from propfirm_research import combine, grid


def series(seed, n=400, mu=15.0, sd=300.0):
    rng = np.random.default_rng(seed)
    pnl = rng.normal(mu, sd, n)
    low = np.minimum(0.0, np.minimum(pnl, -np.abs(rng.normal(0, sd, n))))
    return pnl, low


@pytest.mark.parametrize("seed", [0, 1, 2])
def test_equals_propsim_at_50k_without_dll(seed):
    pnl, low = series(seed)
    ref = propsim.pass_probability(pnl[None], low[None], 500, 12345)[0]
    got = combine.simulate_many(pnl[None], low[None], "50K", 500, 12345)[0]
    assert np.allclose(got[:3], ref, atol=1e-12)
    o = combine.odds(pnl, low, "50K", dll=False, n_sims=500)
    assert (o["pass"], o["fail"]) == pytest.approx((ref[0], ref[1]))


def test_dll_caps_days():
    pnl = np.array([-1500.0, 100.0, 200.0])
    low = np.array([-1600.0, -50.0, 0.0])
    p2, l2 = combine.apply_dll(pnl, low, 1000.0)
    assert list(p2) == [-1000.0, 100.0, 200.0] and l2[0] == -1000.0
    pnl, low = series(5, mu=0, sd=900)
    off = combine.odds(pnl, low, "50K", dll=False, n_sims=400)
    on = combine.odds(pnl, low, "50K", dll=True, n_sims=400)
    assert on["dll_hit_days"] > 0
    assert off["dll_hit_days"] == 0  # DLL can raise OR lower failure: a dip-then-recover day becomes -DLL


def test_accounts_and_scaling():
    a = combine.ACCOUNTS["150K"]
    assert (a.mll, a.target, a.dll, a.g8_limit) == (4500, 9000, 3000, 2250)
    pnl, low = series(7, mu=40, sd=200)
    one = combine.odds(pnl, low, "150K", contracts=1, dll=False, n_sims=300)
    two = combine.odds(pnl * 2, low * 2, "150K", contracts=1, dll=False, n_sims=300)  # same as 2 contracts
    via = combine.odds(pnl, low, "150K", contracts=2, dll=False, n_sims=300)
    assert via["pass"] == two["pass"] and via["p95_dd"] == pytest.approx(two["p95_dd"])
    assert one["p95_dd"] < via["p95_dd"]


# --- grid -------------------------------------------------------------------------------------

def minutes(day="2016-03-09", contract="CLJ6@2016-03", start="08:55", end="16:20", roll_at=None):
    """Synthetic front-month minutes on one ET date (EST/EDT handled by pandas), open = row index."""
    ts = pd.date_range(f"{day} {start}", f"{day} {end}", freq="1min", tz="America/New_York").tz_convert("UTC")
    n = len(ts)
    o = 5000.0 + np.arange(n)
    df = pd.DataFrame({"ts_event_utc": ts, "contract": contract, "open": o, "high": o + 2, "low": o - 3,
                       "close": o, "volume": 1.0})
    if roll_at is not None:
        df.loc[ts >= pd.Timestamp(f"{day} {roll_at}", tz="America/New_York"), "contract"] = "CLK6@2016-04"
    from propfirm_research.periods import et_minute_of_day, trading_day
    df["trading_day"] = trading_day(df["ts_event_utc"])
    df["mod"] = et_minute_of_day(df["ts_event_utc"])
    from propfirm_research.data import utc_minutes
    df["tmin"] = utc_minutes(df["ts_event_utc"])
    return df


FAR = 10**9  # expiry far in the future (unknown expiries now raise)
EXP = {"CLJ6@2016-03": FAR, "CLK6@2016-04": FAR}


def test_window_entry_exit_and_extremes():
    df = minutes()
    w = grid.windows(df, [(9 * 60, 10 * 60)], expiry_tmin=EXP).iloc[0]
    assert w.valid and w.entry == 5005.0 and w.exit == 5065.0 and w.ret_ticks == 60
    assert w.mfe_long == (5064 + 2) - 5005 and w.mae_long == 5005 - (5005 - 3)


def test_flat_window_exits_at_1605_and_late_exit_invalid():
    df = minutes()
    w = grid.windows(df, [(9 * 60, grid.FLAT), (15 * 60, 16 * 60 + 10)], expiry_tmin=EXP)
    flat = w.iloc[0]
    assert flat.valid and flat.exit == 5000 + (16 * 60 + 5 - (8 * 60 + 55))
    assert not w.iloc[1].valid  # exit after the flat time


@pytest.mark.parametrize("exit_mod,valid", [(10 * 60 + 54, True), (10 * 60 + 55, True), (10 * 60 + 56, False),
                                            (10 * 60 + 59, False), (11 * 60 + 30, False)])
def test_roll_cutoff_five_minutes_before_scheduled_roll(exit_mod, valid):
    df = minutes(roll_at="11:00")  # next contract front from 11:00: old contract flat by 10:55
    w = grid.windows(df, [(9 * 60, exit_mod)], expiry_tmin=EXP).iloc[0]
    assert w.valid == valid


def test_flat_exit_stops_at_roll_cutoff_and_late_entry_invalid():
    df = minutes(roll_at="11:00")
    w = grid.windows(df, [(9 * 60, grid.FLAT), (10 * 60 + 56, grid.FLAT), (11 * 60, 12 * 60)], expiry_tmin=EXP)
    t = df.set_index("tmin")
    assert w.iloc[0].valid and t.loc[w.iloc[0].exit_tmin, "mod"] == 10 * 60 + 55
    assert not w.iloc[1].valid  # entry inside the last 5 minutes before the roll
    assert w.iloc[2].valid and w.iloc[2].contract == "CLK6@2016-04"


def test_expiry_cutoff_and_unknown_expiry_raises():
    df = minutes()
    exp_t = int(df.loc[df["mod"] == 14 * 60 + 30, "tmin"].iloc[0])
    w = grid.windows(df, [(9 * 60, grid.FLAT), (9 * 60, 14 * 60 + 26)], expiry_tmin={"CLJ6@2016-03": exp_t})
    t = df.set_index("tmin")
    assert t.loc[w.iloc[0].exit_tmin, "mod"] == 14 * 60 + 25 and not w.iloc[1].valid
    with pytest.raises(ValueError):
        grid.windows(df, [(9 * 60, 10 * 60)], expiry_tmin={})


def test_evening_window_belongs_to_next_trading_day():
    full = pd.concat([minutes(day="2016-03-08", start="18:00", end="23:59"),
                      minutes(day="2016-03-09", start="00:00", end="16:20")], ignore_index=True)
    w = grid.windows(full, [(20 * 60, 3 * 60)], expiry_tmin=EXP).iloc[0]
    assert full["trading_day"].nunique() == 1  # 18:00 on the 8th already belongs to the 9th
    assert w.valid and w.trading_day == full["trading_day"].iloc[-1]
    start = full.set_index("tmin").loc[w.entry_tmin]
    assert start["mod"] == 20 * 60 and start["ts_event_utc"].tz_convert("America/New_York").day == 8


def test_short_day_flat_1255():
    df = minutes(day="2016-11-25", contract="CLF7@2016-12")  # day after Thanksgiving
    w = grid.windows(df, [(9 * 60, grid.FLAT), (9 * 60, 13 * 60)], expiry_tmin={"CLF7@2016-12": FAR}).iloc[:2]
    t = df.set_index("tmin")
    assert t.loc[w.iloc[0].exit_tmin, "mod"] == 12 * 60 + 55 and not w.iloc[1].valid


def test_contracts_validated():
    pnl, low = series(1)
    for bad in (0, 4, 1.5, -1):
        with pytest.raises(ValueError):
            combine.odds(pnl, low, "50K", contracts=bad, n_sims=10)
    with pytest.raises(ValueError):
        combine.odds(pnl, -low, "50K", n_sims=10)  # positive lows are impossible


def test_window_ignores_future_bars():
    df = minutes()
    base = grid.windows(df, [(9 * 60, 10 * 60)], expiry_tmin=EXP).iloc[0]
    later = df["mod"] >= 10 * 60 + 1
    df.loc[later, ["open", "high", "low", "close"]] = 1.0  # scramble everything after the exit bar
    assert grid.windows(df, [(9 * 60, 10 * 60)], expiry_tmin=EXP).iloc[0].equals(base)


def test_trade_usd_costs_and_mae():
    df = minutes()
    w = grid.windows(df, [(9 * 60, 10 * 60)], expiry_tmin=EXP)
    pnl, mae = grid.trade_usd(w, np.array([1]), slip=1.0, fee=4.02)
    assert pnl[0] == pytest.approx(60 * 10 - 24.02)
    assert mae[0] == pytest.approx((3 + 1) * 10 + 4.02)
    pnl_s, _ = grid.trade_usd(w, np.array([-1]), slip=1.0, fee=4.02)
    assert pnl_s[0] == pytest.approx(-60 * 10 - 24.02)
    bad = grid.windows(df, [(15 * 60, 16 * 60 + 10)], expiry_tmin=EXP)
    with pytest.raises(ValueError):
        grid.trade_usd(bad, np.array([1]), slip=1.0, fee=4.02)
    assert grid.trade_usd(bad, np.array([0]), slip=1.0, fee=4.02)[0][0] == 0.0
