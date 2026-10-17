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
    assert (a.mll, a.target, a.dll, a.dd_limit_d003) == (4500, 9000, 3000, 2250)
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


# --- planted edges (S001) ---------------------------------------------------------------------

def test_planted_zero_drift_equals_trade_usd():
    df = minutes()
    w = grid.windows(df, [(9 * 60, 10 * 60), (9 * 60, grid.FLAT)], expiry_tmin=EXP)
    for d in (np.array([1, -1]), np.array([-1, 0])):
        got = grid.planted(df, w, d, 0.0, slip=1.0, fee=4.02)
        ref = grid.trade_usd(w, d, slip=1.0, fee=4.02)
        assert np.allclose(got[0], ref[0]) and np.allclose(got[1], ref[1])


def test_planted_drift_bends_path_and_exit():
    df = minutes()  # open = 5000 + i, low = open - 3, high = open + 2: a steady rise of 1 tick/min
    w = grid.windows(df, [(9 * 60, 10 * 60)], expiry_tmin=EXP)  # 60 minutes, entry open 5005
    pnl, mae = grid.planted(df, w, np.array([1]), 30.0, slip=1.0, fee=4.02)
    assert pnl[0] == pytest.approx((60 + 30) * 10 - 24.02)
    assert mae[0] == pytest.approx((3 + 1) * 10 + 4.02)  # rising path: worst point is still the entry bar
    # short against a +1/min trend: path p_j - 0.5*j, worst high at the last bar before exit (j = 59)
    pnl_s, mae_s = grid.planted(df, w, np.array([-1]), 30.0, slip=1.0, fee=4.02)
    assert pnl_s[0] == pytest.approx((-60 + 30) * 10 - 24.02)
    assert mae_s[0] == pytest.approx((59 + 2 - 30 * 59 / 60 + 1) * 10 + 4.02)


def test_planted_drift_lowers_short_mae_in_flat_market():
    df = minutes()
    df[["open", "high", "low", "close"]] = df[["open", "high", "low", "close"]].to_numpy() * 0 + [5000, 5002, 4997, 5000]
    w = grid.windows(df, [(9 * 60, 10 * 60)], expiry_tmin=EXP)
    for d in (1, -1):  # symmetric: in a flat market the drift helps both directions equally
        pnl, mae = grid.planted(df, w, np.array([d]), 12.0, slip=1.0, fee=4.02)
        assert pnl[0] == pytest.approx(12 * 10 - 24.02)
    assert grid.planted(df, w, np.array([1]), 12.0, 1.0, 4.02)[1][0] == pytest.approx((3 + 1) * 10 + 4.02)
    assert grid.planted(df, w, np.array([-1]), 12.0, 1.0, 4.02)[1][0] == pytest.approx((2 + 1) * 10 + 4.02)
    bad = grid.windows(df, [(15 * 60, 16 * 60 + 10)], expiry_tmin=EXP)
    with pytest.raises(ValueError):
        grid.planted(df, bad, np.array([1]), 5.0, 1.0, 4.02)


def test_odds_many_equals_odds_per_row():
    rows = [series(s, mu=30, sd=250) for s in (11, 12, 13)]
    pnl = np.vstack([r[0] for r in rows])
    low = np.vstack([r[1] for r in rows])
    many = combine.odds_many(pnl, low, "100K", contracts=2, reserve=500, n_sims=300, seeds=[1, 2, 3])
    for i in range(3):
        one = combine.odds(pnl[i], low[i], "100K", contracts=2, reserve=500, n_sims=300, seed=i + 1)
        assert (many["pass"][i], many["fail"][i]) == pytest.approx((one["pass"], one["fail"]))
        assert many["p95_dd"][i] == pytest.approx(one["p95_dd"])
        assert many["fail_ucb95"][i] == pytest.approx(one["fail_ucb95"])
        assert many["dll_hit_days"][i] == pytest.approx(one["dll_hit_days"])
    with pytest.raises(ValueError):
        combine.odds_many(pnl, -low, "50K", n_sims=10)


# --- R004 fixes -------------------------------------------------------------------------------

def test_day_low_includes_exit_when_exit_is_worst_price():
    df = minutes()
    df.loc[df["mod"] == 10 * 60, "open"] = 5005 - 150.0  # benign path, exit open gaps 150 ticks down
    w = grid.windows(df, [(9 * 60, 10 * 60)], expiry_tmin=EXP)
    pnl, mae = grid.planted(df, w, np.array([1]), 0.0, slip=1.0, fee=4.02)
    assert mae[0] == pytest.approx((3 + 1) * 10 + 4.02)  # pre-exit excursion is small
    low = grid.one_trade_day_low(pnl, mae)
    assert low[0] == pytest.approx(pnl[0]) and pnl[0] < -1000  # so the DLL sees the loss that day
    capped = combine.apply_dll(pnl, low, 1000.0, 10.0)[0]
    assert capped[0] == pytest.approx(-1010.0)
    with pytest.raises(ValueError):  # a low above the close is now rejected
        combine.odds(pnl, -mae, "50K", n_sims=10)


def test_account_level_drop_stops_at_mll_line():
    pnl = np.array([-1500.0, -100.0])
    low = np.array([-1500.0, -1200.0])  # day 2 dips far below the 50K MLL line (-2000)
    o = combine.odds(pnl, low, "50K", dll=False, n_sims=50)
    assert o["fail"] == 1.0
    assert o["p95_dd_account"] <= 2000.0 + 1e-9 < o["p95_dd"]


def test_odds_many_checks_seeds_and_sims():
    pnl, low = series(3)
    with pytest.raises(ValueError):
        combine.odds_many(np.vstack([pnl, pnl]), np.vstack([low, low]), "50K", seeds=[1])
    with pytest.raises(ValueError):
        combine.odds_many(pnl, low, "50K", seeds=[1.5])
    with pytest.raises(ValueError):
        combine.odds_many(pnl, low, "50K", n_sims=0)


def test_t_quantile_matches_tables():
    from propfirm_research.stats import mean_upper, t_quantile
    assert t_quantile(0.95, 9) == pytest.approx(1.833113, abs=1e-5)
    assert t_quantile(0.975, 4) == pytest.approx(2.776445, abs=1e-5)
    assert t_quantile(0.05, 9) == pytest.approx(-1.833113, abs=1e-5)
    x = np.array([0.0, 0.01, 0.02, 0.0, 0.01])
    assert mean_upper(x) == pytest.approx(x.mean() + 2.131847 * x.std(ddof=1) / np.sqrt(5), abs=1e-6)


def test_odds_many_rejects_shape_mismatch_without_dll():
    pnl, low = series(4)
    with pytest.raises(ValueError):
        combine.odds_many(np.vstack([pnl, pnl]), low[None], "50K", dll=False, n_sims=10)
    with pytest.raises(ValueError):
        combine.odds(pnl, low, "50K", n_sims=0)


def test_gate_g8_d006_rule():
    good_pnl, good_low = series(21, n=600, mu=60.0, sd=150.0)
    g = combine.gate_g8(good_pnl, good_low, "100K", n_sims=1000, n_outer=10, outer_sims=300)
    assert g["g8_rule"] == "D006" and g["reserve"] == 500.0 and g["dll"]
    assert g["fail_ucb95_gate"] >= g["fail_ucb95"]  # outer resamples can only widen the bound
    assert g["g8_ok"] == (g["pass"] >= 0.5 and g["fail_ucb95_gate"] <= 0.10)
    assert g["g8_ok"]  # a strong edge passes
    idle_pnl, idle_low = np.full(600, 1.0), np.full(600, -5.0)  # barely trades: never fails, never passes
    idle = combine.gate_g8(idle_pnl, idle_low, "150K", n_sims=500, n_outer=5, outer_sims=200)
    assert idle["fail"] == 0 and not idle["g8_ok"]  # D006: inactivity no longer passes G8
    diag = combine.gate_g8(good_pnl, good_low, "100K", n_sims=500, n_outer=0)
    assert not diag["g8_ok"]  # without outer draws the result is diagnostic only


# --- D009 strict exits ------------------------------------------------------------------------

def drop(df, mod):
    return df[df["mod"] != mod].reset_index(drop=True)


def test_strict_exit_missing_flat_bar_invalid():
    df = drop(minutes(), 16 * 60 + 5)  # 16:06-16:20 bars still exist: none of them may be used
    w = grid.windows(df, [(9 * 60, grid.FLAT)], expiry_tmin=EXP).iloc[0]
    assert not w.valid and w.exit_missing


def test_strict_exit_missing_fixed_bar_invalid():
    df = minutes()
    full = grid.windows(df, [(9 * 60, 10 * 60)], expiry_tmin=EXP).iloc[0]
    assert full.valid and not full.exit_missing
    w = grid.windows(drop(df, 10 * 60), [(9 * 60, 10 * 60)], expiry_tmin=EXP).iloc[0]
    assert not w.valid and w.exit_missing


@pytest.mark.parametrize("case", ["short_day", "roll", "expiry"])
def test_strict_exit_at_every_cutoff(case):
    if case == "short_day":
        df, exp, cut = minutes(day="2016-11-25", contract="CLF7@2016-12"), {"CLF7@2016-12": FAR}, 12 * 60 + 55
    elif case == "roll":
        df, exp, cut = minutes(roll_at="11:00"), EXP, 10 * 60 + 55
    else:
        df = minutes()
        exp, cut = {"CLJ6@2016-03": int(df.loc[df["mod"] == 14 * 60 + 30, "tmin"].iloc[0])}, 14 * 60 + 25
    ok = grid.windows(df, [(9 * 60, grid.FLAT)], expiry_tmin=exp).iloc[0]
    assert ok.valid and df.set_index("tmin").loc[ok.exit_tmin, "mod"] == cut
    w = grid.windows(drop(df, cut), [(9 * 60, grid.FLAT)], expiry_tmin=exp).iloc[0]
    assert not w.valid and w.exit_missing


def test_valid_exits_never_after_exit_minute():
    df = minutes()
    df = df[np.random.default_rng(3).random(len(df)) > 0.3].reset_index(drop=True)  # 30% of minutes gone
    specs = [(9 * 60, grid.FLAT), (9 * 60, 10 * 60), (10 * 60 + 30, 14 * 60), (14 * 60 + 35, grid.FLAT)]
    w = grid.windows(df, specs, expiry_tmin=EXP)
    want = np.where(w["end_mod"] == grid.FLAT, 16 * 60 + 5, w["end_mod"])
    mod = df.set_index("tmin")["mod"]
    v = w["valid"].to_numpy()
    assert v.any() and w["exit_missing"].any()
    assert (mod.loc[w.loc[v, "exit_tmin"]].to_numpy() == want[v]).all()
    for i in np.flatnonzero(w["exit_missing"].to_numpy()):
        assert want[i] not in set(df["mod"])  # skipped only when the exact exit minute has no bar


def test_contract_change_at_exact_exit_bar_is_invalid_not_missing():
    df = minutes()
    df.loc[[0, df.index[df["mod"] == 10 * 60][0]], "contract"] = "CLK6@2016-04"  # B first, then A; B again at 10:00
    w = grid.windows(df, [(9 * 60, 10 * 60)], expiry_tmin=EXP).iloc[0]
    assert not w.valid and not w.exit_missing


def test_exit_missing_only_flags_the_missing_exit_reason():
    df = minutes()
    late_entry = df[(df["mod"] < 9 * 60) | (df["mod"] > 9 * 60 + 6)].reset_index(drop=True)
    cases = [(late_entry, (9 * 60, 10 * 60)),  # entry more than 5 minutes late
             (df, (15 * 60, 16 * 60 + 10)),  # fixed exit after the flat time
             (df, (16 * 60 + 5, grid.FLAT))]  # entry at the flat time
    late_entry_no_exit = drop(late_entry, 10 * 60)  # entry fails first, so the missing exit is not the reason
    cases.append((late_entry_no_exit, (9 * 60, 10 * 60)))
    for frame, spec in cases:
        w = grid.windows(frame, [spec], expiry_tmin=EXP).iloc[0]
        assert not w.valid and not w.exit_missing, spec
    w = grid.windows(drop(df, 10 * 60), [(9 * 60, 10 * 60)], expiry_tmin=EXP).iloc[0]
    assert not w.valid and w.exit_missing


@pytest.mark.parametrize("evening,morning", [("2016-03-08", "2016-03-09"),  # plain week
                                             ("2016-03-13", "2016-03-14"),  # first session after spring-forward
                                             ("2016-11-06", "2016-11-07")])  # first session after fall-back
def test_evening_window_strict_exit_across_1800_and_dst(evening, morning):
    full = pd.concat([minutes(day=evening, start="18:00", end="23:59"),
                      minutes(day=morning, start="00:00", end="16:20")], ignore_index=True)
    w = grid.windows(full, [(20 * 60, 3 * 60)], expiry_tmin=EXP).iloc[0]
    exit_bar = full.set_index("tmin").loc[w.exit_tmin]
    assert w.valid and exit_bar["mod"] == 3 * 60
    assert exit_bar["ts_event_utc"].tz_convert("America/New_York").strftime("%Y-%m-%d %H:%M") == f"{morning} 03:00"
    gone = grid.windows(drop(full, 3 * 60), [(20 * 60, 3 * 60)], expiry_tmin=EXP).iloc[0]
    assert not gone.valid and gone.exit_missing


def test_trades_on_a_skipped_window_are_rejected():
    df = drop(minutes(), 10 * 60)
    w = grid.windows(df, [(9 * 60, 10 * 60)], expiry_tmin=EXP)
    with pytest.raises(ValueError):
        grid.trade_usd(w, np.array([1]), slip=1.0, fee=4.02)
    with pytest.raises(ValueError):
        grid.planted(df, w, np.array([-1]), 5.0, slip=1.0, fee=4.02)
    assert grid.trade_usd(w, np.array([0]), slip=1.0, fee=4.02)[0][0] == 0.0


def test_multi_day_random_missing_bars_exit_at_exact_timestamp():
    days = ["2016-03-07", "2016-03-08", "2016-03-09", "2016-03-10"]
    df = pd.concat([minutes(day=d) for d in days], ignore_index=True)
    df = df[np.random.default_rng(8).random(len(df)) > 0.4].reset_index(drop=True)
    specs = [(9 * 60, grid.FLAT), (9 * 60, 10 * 60), (14 * 60 + 35, grid.FLAT)]
    w = grid.windows(df, specs, expiry_tmin=EXP)
    tday = w["trading_day"].to_numpy(np.int64)
    end = w["end_mod"].to_numpy()
    want = np.where(end == grid.FLAT, grid.flat_tmin(tday),
                    np.array([grid.clock_tmin(np.array([d]), int(m))[0] if m != grid.FLAT else -1
                              for d, m in zip(tday, end)]))
    v = w["valid"].to_numpy()
    assert v.any() and w["exit_missing"].any()
    assert (w.loc[v, "exit_tmin"].to_numpy() == want[v]).all()
    have = set(df["tmin"])
    assert all(want[i] not in have for i in np.flatnonzero(w["exit_missing"].to_numpy()))


def test_late_entry_bar_cannot_be_the_exit_bar():
    df = minutes()
    df = df[(df["mod"] < 9 * 60) | (df["mod"] >= 9 * 60 + 5)].reset_index(drop=True)  # 09:00-09:04 missing
    w = grid.windows(df, [(9 * 60, 9 * 60 + 5)], expiry_tmin=EXP).iloc[0]  # entry would be the 09:05 exit bar
    assert not w.valid and not w.entry_ok and not w.exit_missing
