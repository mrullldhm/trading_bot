import numpy as np
import pandas as pd
import pytest

from propfirm_backtest import bars as B
from propfirm_backtest import orb_engine as E
from propfirm_backtest import propsim as P
from propfirm_backtest import orb_reference as R

DAY = "2025-11-04"  # Tuesday, EST (UTC-5)


def bars_df(rows, day=DAY, sym="CLZ5", tail=True):
    """rows: list of (HH:MM ET, open, high, low, close). tail=True adds a 16:30 bar so the
    day is not treated as an early close."""
    rows = list(rows)
    if tail:
        rows.append(("16:30", rows[-1][4], rows[-1][4], rows[-1][4], rows[-1][4]))
    ts = [pd.Timestamp(f"{day} {t}", tz=E.ET).tz_convert("UTC") for t, *_ in rows]
    a = np.array([r[1:] for r in rows], dtype=float)
    return pd.DataFrame({"ts_event_utc": pd.DatetimeIndex(ts).as_unit("ns"), "continuous_symbol": "CL.v.0", "raw_symbol": sym,
                         "open_ticks": a[:, 0], "high_ticks": a[:, 1], "low_ticks": a[:, 2],
                         "close_ticks": a[:, 3], "volume": 10})


def flat_range(start="09:00", n=5, hi=7010, lo=7000):
    """n minutes from `start` spanning exactly [lo, hi]."""
    t0 = pd.Timestamp(f"{DAY} {start}")
    return [((t0 + pd.Timedelta(minutes=k)).strftime("%H:%M"), 7005, hi, lo, 7005) for k in range(n)]


def at(minute_offset, o, h, l, c, start="09:05"):
    t = pd.Timestamp(f"{DAY} {start}") + pd.Timedelta(minutes=minute_offset)
    return (t.strftime("%H:%M"), o, h, l, c)


def market(df, eia=None):
    m = B.build_minutes(df)
    days = np.unique(m.trading_day[m.front])
    return E.Market(m, days, eia), m


def cfg(anchor="et0900", L=5, trigger=E.STOP, buf=0, stop_type=E.OPPOSITE, stop_ticks=0, target_x10=10,
        window=60, flat=60, dirpol=E.BOTH1, width=E.W_NONE, be=0):
    keys = [(a, n) for a in E.ANCHORS for n in E.RANGE_LENGTHS]
    return np.array([keys.index((anchor, L)), trigger, buf, stop_type, stop_ticks, target_x10, window, flat,
                     dirpol, width, be], dtype=np.int64)


def trades(mk, c, **kw):
    t = mk.trades(c, **kw)
    return list(zip(*[x.tolist() for x in t]))


# --- hand-made cases -----------------------------------------------------------------------------

def test_range_and_long_target():
    rows = flat_range() + [at(0, 7008, 7011, 7006, 7010),  # touches 7011 = long level (hi + 1)
                           at(1, 7010, 7030, 7009, 7025),  # 1R: fill 7012, stop 6999 -> R 13, tgt 7025 needs 7026
                           at(2, 7025, 7027, 7020, 7026)]
    mk, _ = market(bars_df(rows))
    (t,) = trades(mk, cfg())
    day, i_in, i_out, d, pin, pout, mae, why = t
    assert d == 1 and pin == 7012 and pout == 7025 and why == E.EXIT_TARGET
    assert i_in == 5 and i_out == 6  # target 7025 needs 7026: reached in the minute at offset 1


def test_no_fill_inside_the_range():
    rows = flat_range(hi=7010) + [at(0, 7005, 7008, 7002, 7005)]
    rows[2] = ("09:02", 7005, 7010, 7000, 7005)
    mk, _ = market(bars_df(rows))
    assert trades(mk, cfg()) == []


def test_pessimistic_same_minute_stop_and_optimistic_bound():
    rows = flat_range() + [at(0, 7008, 7012, 6998, 7000),  # long fills and stop 6999 touched in one minute
                           at(1, 7000, 7040, 7000, 7040)]
    mk, _ = market(bars_df(rows))
    (t,) = trades(mk, cfg())
    assert t[7] == E.EXIT_STOP and t[5] == 6999 - 1
    (o,) = trades(mk, cfg(), pessimistic=False)
    assert o[7] == E.EXIT_TARGET  # optimistic: entry minute ignored, target hit next minute


def test_gap_through_stop_entry_and_protective_stop():
    rows = flat_range() + [at(0, 7020, 7022, 7018, 7020),  # gaps above the long level: fill at open + slip
                           at(1, 6990, 6995, 6985, 6990)]  # gaps below the stop: fill at open - slip
    mk, _ = market(bars_df(rows))
    (t,) = trades(mk, cfg(target_x10=0))
    assert t[4] == 7021 and t[5] == 6989 and t[7] == E.EXIT_STOP


def test_flat_time_exit_at_open():
    rows = flat_range() + [at(0, 7008, 7011, 7006, 7010)] + [at(k, 7012, 7013, 7011, 7012) for k in range(1, 70)]
    mk, _ = market(bars_df(rows))
    (t,) = trades(mk, cfg(target_x10=0, flat=60))
    assert t[7] == E.EXIT_TIME
    exit_ts = pd.Timestamp(mk.f.tmin[t[2]] * E.NS_PER_MIN, tz="UTC").tz_convert(E.ET)
    assert exit_ts.strftime("%H:%M") == "10:05"  # range end 09:05 + 60 min


def test_missing_minutes_in_range():
    rows = flat_range(n=10)
    del rows[2]  # 9 of 10 minutes traded: still a valid 10-minute range
    mk, _ = market(bars_df(rows + [at(5, 7008, 7020, 7006, 7015)]))
    assert len(trades(mk, cfg(L=10))) == 1
    rows = flat_range()
    del rows[2]
    del rows[2]  # 3 of 5 minutes: below 80%, skip the day
    mk, _ = market(bars_df(rows + [at(0, 7008, 7020, 7006, 7015)]))
    assert trades(mk, cfg()) == []


def test_eia_block_consumes_the_side():
    rows = flat_range() + [at(0, 7008, 7011, 7006, 7010),   # long breakout 09:05, inside the block
                           at(10, 7010, 7030, 7009, 7025),
                           at(31, 6990, 6995, 6980, 6985)]  # short breakout 09:36, after the block
    eia = pd.DataFrame({"date": [pd.Timestamp(DAY)], "minute_et": [9 * 60 + 20]})  # block 09:05-09:35
    mk, _ = market(bars_df(rows), eia)
    (t,) = trades(mk, cfg(target_x10=0, window=60, flat=120))
    assert t[3] == -1  # the long side was used up inside the block; the later short is taken
    mk0, _ = market(bars_df(rows))
    assert trades(mk0, cfg(target_x10=0, window=60, flat=120))[0][3] == 1


def test_close5_buckets_anchor_to_range_end():
    rows = flat_range() + [at(0, 7008, 7015, 7006, 7013),  # minute close beyond the level, bar not done
                           at(1, 7013, 7014, 7008, 7009),
                           at(4, 7009, 7010, 7008, 7012),  # 5-min bar [09:05, 09:10) closes 7012 >= 7011
                           at(5, 7014, 7016, 7013, 7015)]  # fill at 09:10 open + slip
    mk, _ = market(bars_df(rows))
    (t,) = trades(mk, cfg(trigger=E.CLOSE5, target_x10=0))
    assert t[3] == 1 and t[4] == 7015
    (t1,) = trades(mk, cfg(trigger=E.CLOSE1, target_x10=0))
    assert t1[4] == 7014  # 1-min close at 09:05 -> fill at 09:06 open 7013 + 1


def test_second_trade_only_after_stop_and_opposite_side():
    rows = flat_range() + [at(0, 7008, 7011, 7006, 7010),
                           at(1, 7005, 7006, 6998, 6999),  # stop 6999 hit -> short level 6999 touched same minute
                           at(2, 6999, 7000, 6995, 6996),  # second trade: short, from the next minute
                           at(3, 6996, 6997, 6970, 6975)]
    mk, _ = market(bars_df(rows))
    t = trades(mk, cfg(dirpol=E.BOTH2, target_x10=0))
    assert [x[3] for x in t] == [1, -1]
    assert t[0][7] == E.EXIT_STOP and t[1][1] == t[0][2] + 1
    assert len(trades(mk, cfg(dirpol=E.BOTH1, target_x10=0))) == 1


def test_breakeven_moves_stop_from_next_minute():
    rows = flat_range() + [at(0, 7008, 7011, 7006, 7010),  # fill 7012, R 13 -> BE trigger 7025
                           at(1, 7012, 7025, 7011, 7020),
                           at(2, 7020, 7021, 7005, 7006)]  # back through the fill: exit at 7012 - 1
    mk, _ = market(bars_df(rows))
    (t,) = trades(mk, cfg(be=1, target_x10=0))
    assert t[5] == 7011 and t[7] == E.EXIT_STOP
    (n,) = trades(mk, cfg(be=0, target_x10=0))
    assert n[7] != E.EXIT_STOP


def test_short_day_flattens_at_1255():
    rows = flat_range() + [at(0, 7008, 7011, 7006, 7010)] + [at(k, 7012, 7013, 7011, 7012) for k in range(1, 300)]
    mk, _ = market(bars_df(rows, day="2025-11-28"))  # day after Thanksgiving
    (t,) = trades(mk, cfg(target_x10=0, flat=E.SESSION, window=120))
    exit_ts = pd.Timestamp(mk.f.tmin[t[2]] * E.NS_PER_MIN, tz="UTC").tz_convert(E.ET)
    assert t[7] == E.EXIT_TIME and exit_ts.strftime("%H:%M") == "12:55"


def test_data_gap_is_not_an_early_close():
    rows = flat_range() + [at(0, 7008, 7011, 7006, 7010)] + [at(k, 7012, 7013, 7011, 7012) for k in range(1, 200)]
    mk, _ = market(bars_df(rows))  # normal day, no data 12:24 -> 16:30: the position is stuck in the gap
    (t,) = trades(mk, cfg(target_x10=0, flat=E.SESSION, window=120))
    exit_ts = pd.Timestamp(mk.f.tmin[t[2]] * E.NS_PER_MIN, tz="UTC").tz_convert(E.ET)
    assert t[7] == E.EXIT_TIME and exit_ts.strftime("%H:%M") == "16:30"


def test_expiry_day_flattens_before_expiry():
    rows = flat_range() + [at(0, 7008, 7011, 7006, 7010)] + [at(k, 7012, 7013, 7011, 7012) for k in range(1, 400)]
    mk, _ = market(bars_df(rows))
    with_expiry(mk, 0, DAY)
    (t,) = trades(mk, cfg(target_x10=0, flat=E.SESSION, window=120))
    exit_ts = pd.Timestamp(mk.f.tmin[t[2]] * E.NS_PER_MIN, tz="UTC").tz_convert(E.ET)
    assert t[7] == E.EXIT_TIME and exit_ts.strftime("%H:%M") == "14:25"


def test_short_days_calendar():
    days = np.array([(pd.Timestamp(d) - pd.Timestamp("1970-01-01")).days for d in
                     ["2025-11-27", "2025-11-28", "2025-12-24", "2025-10-13", "2021-06-18", "2022-06-20", "2025-11-26",
                      "2021-12-31", "2010-12-31", "2023-01-02"]])
    assert E.short_days(days).tolist() == [True, True, True, False, False, True, False, False, False, True]


def test_london_anchor_is_dst_aware():
    days = np.array([(pd.Timestamp(d) - pd.Timestamp("1970-01-01")).days for d in ["2025-03-11", "2025-04-08"]])
    t = E.local_tmin(days, 8 * 60, E.LONDON)
    et = [pd.Timestamp(x * E.NS_PER_MIN, tz="UTC").tz_convert(E.ET).strftime("%H:%M") for x in t]
    assert et == ["04:00", "03:00"]  # US on DST, UK not yet -> 04:00 ET; both on DST -> 03:00 ET


def test_width_ratio_excludes_today():
    w = np.arange(1, 23, dtype=float)
    r = E.width_ratio(w, np.ones(22, bool))
    assert np.isnan(r[19]) and r[20] == 21 / np.median(np.arange(1, 21))


# --- random cross-check: numba engine == plain-Python reference --------------------------------

def random_market(seed, n_days=30, roll_day=15):
    """Random-walk minutes for full sessions (previous day 18:00 -> 16:30 ET), a few quiet minutes,
    and a contract roll at 12:00 ET on `roll_day` (CLZ5 -> CLF6)."""
    rng = np.random.default_rng(seed)
    frames = []
    bdays = pd.bdate_range("2025-11-03", periods=n_days)
    roll_ts = pd.Timestamp(f"{bdays[roll_day].date()} 12:00", tz=E.ET)
    price = 7000
    for k, day in enumerate(bdays):
        prev = day - pd.Timedelta(days=1)  # Monday session opens Sunday 18:00
        mins = pd.date_range(f"{prev.date()} 18:00", f"{day.date()} 16:30", freq="1min", tz=E.ET)
        mins = mins[~((mins.hour == 17) | ((mins.hour >= 16) & (mins.minute > 30) & (mins.day == day.day)))]
        keep = rng.random(len(mins)) > (0.03 if k % 5 else 0.12)  # thin days drop many minutes
        mins = mins[keep]
        steps = rng.integers(-4, 5, len(mins)).cumsum() + price
        price = int(steps[-1])
        o = steps + rng.integers(-1, 2, len(mins))
        c = steps
        h = np.maximum(o, c) + rng.integers(0, 6, len(mins))
        lo = np.minimum(o, c) - rng.integers(0, 6, len(mins))
        frames.append(pd.DataFrame({"ts_event_utc": mins.tz_convert("UTC").as_unit("ns"), "continuous_symbol": "CL.v.0",
                                    "raw_symbol": np.where(mins < roll_ts, "CLZ5", "CLF6"), "open_ticks": o,
                                    "high_ticks": h, "low_ticks": lo, "close_ticks": c, "volume": 10}))
    df = pd.concat(frames, ignore_index=True)
    eia = pd.DataFrame({"date": [d for d in bdays if d.dayofweek == 2], "minute_et": 10 * 60 + 30})
    return df, eia


def with_expiry(mk, contract, day, hhmm="14:30"):
    """Give `contract` an expiry (normally read from the exchange definitions) and rebuild the tables."""
    mk.f.expiry[contract] = int(pd.Timestamp(f"{day} {hhmm}", tz=E.ET).value // E.NS_PER_MIN)
    mk.t = E.DayTables(mk.f, mk.days, mk.eia)
    return mk


def as_floats(trade_list):
    return [tuple(float(x) for x in t) for t in trade_list]


@pytest.mark.parametrize("seed", [1, 2, 3])
def test_engine_matches_reference_on_random_configs(seed):
    df, eia = random_market(seed)
    mk, _ = market(df, eia)
    with_expiry(mk, 1, pd.bdate_range("2025-11-03", periods=30)[25].date())  # CLF6 expires on day 25
    rng = np.random.default_rng(seed + 100)
    for _ in range(40):
        L = int(rng.choice(E.RANGE_LENGTHS))
        anchor = str(rng.choice(list(E.ANCHORS)))
        c = cfg(anchor=anchor, L=L, trigger=int(rng.integers(0, 3)), buf=int(rng.choice([0, 2])),
                stop_type=int(rng.integers(0, 3)), stop_ticks=int(rng.choice([15, 20, 30])),
                target_x10=int(rng.choice([0, 10, 15, 20, 30])), window=int(rng.choice([30, 60, 120])),
                flat=int(rng.choice([60, 120, 240, E.SESSION])), dirpol=int(rng.integers(0, 4)),
                width=int(rng.integers(0, 4)), be=int(rng.integers(0, 2)))
        pess = bool(rng.integers(0, 2))
        got = trades(mk, c, pessimistic=pess)
        want = R.run(mk.f, mk.days, anchor, L, int(c[1]), int(c[2]), int(c[3]), int(c[4]), c[5] / 10,
                     int(c[6]), int(c[7]), int(c[8]), int(c[9]), int(c[10]), eia=eia, pessimistic=pess)
        assert as_floats(got) == as_floats(want), c


def test_kernels_match_trade_list_metrics():
    df, eia = random_market(7)
    mk, _ = market(df, eia)
    cfgs = np.stack([cfg(dirpol=d, target_x10=t, flat=f) for d in range(4) for t in (0, 20) for f in (60, E.SESSION)])
    n = len(mk.days)
    years = np.where(np.arange(n) < n // 2, 0, 1).astype(np.int64)
    fold_ends = np.array([n // 2, n], np.int64)
    u = np.random.default_rng(0).random((200, 13))
    hash_w = np.random.default_rng(1).random(n)
    met, ypnl, ytr, ybest, wf = E.grid_kernel(mk.day_fn, cfgs, n, years, 2, fold_ends, hash_w, mk.day_args(),
                                              mk.minute_args(), 1.0, True, u, u, 5, True)
    dpnl, dlow = E.daily_kernel(mk.day_fn, cfgs, n, mk.day_args(), mk.minute_args(), 1.0, True)
    M = {k: i for i, k in enumerate(E.M_NAMES)}
    for i, c in enumerate(cfgs):
        t = mk.trades(c)
        pnl = P.trade_pnl_usd(t[3], t[4], t[5])
        day_pnl, day_low = P.daily_series(t[0], pnl, t[6] * P.TICK_USD + P.FEE_USD, n)
        st = P.trade_stats(pnl)
        np.testing.assert_allclose(dpnl[i], day_pnl)
        np.testing.assert_allclose(dlow[i], day_low)
        assert met[i, M["trades"]] == st["trades"]
        assert met[i, M["wins"]] == (pnl > 0).sum()
        assert met[i, M["total_usd"]] == pytest.approx(pnl.sum())
        assert met[i, M["max_losing_streak"]] == st["max_losing_streak"]
        assert met[i, M["best_day_usd"]] == pytest.approx(day_pnl.max())
        assert met[i, M["max_drawdown_usd"]] == pytest.approx(P.max_drawdown(day_pnl, day_low))
        assert met[i, M["stop_exits"]] == (t[7] == E.EXIT_STOP).sum()
        assert met[i, M["fallback_exits"]] == (t[7] == E.EXIT_FALLBACK).sum()
        assert met[i, M["stream_hash"]] == pytest.approx(np.round((day_pnl * hash_w).sum(), 2))
        assert ytr[i].tolist() == [int((years[t[0]] == y).sum()) for y in (0, 1)]
        assert ypnl[i] == pytest.approx([day_pnl[years == y].sum() for y in (0, 1)])
        assert ybest[i] == pytest.approx([max(0.0, day_pnl[years == y].max()) for y in (0, 1)])
        p_, f_, dd = E._bootstrap(day_pnl, day_low, n, u, 5)
        assert (met[i, M["pass_prob"]], met[i, M["fail_prob"]], met[i, M["p95_drawdown"]]) == pytest.approx((p_, f_, dd))
        assert tuple(wf[i, 0]) == pytest.approx(E._bootstrap(day_pnl, day_low, n // 2, u, 5)[::2])
        assert 0 <= p_ + f_ <= 1
    assert met[:, M["trades"]].sum() > 50  # not vacuous


def test_close_signal_at_deadline_does_not_fill():
    # window 30: deadline 09:35. 1-min bar 09:34 closes beyond -> fill would be 09:35 = deadline: no trade
    rows = flat_range() + [at(29, 7008, 7012, 7006, 7012), at(30, 7012, 7014, 7011, 7013)]
    mk, _ = market(bars_df(rows))
    assert trades(mk, cfg(trigger=E.CLOSE1, window=30, target_x10=0)) == []
    rows = flat_range() + [at(28, 7008, 7012, 7006, 7012), at(29, 7012, 7014, 7011, 7013)]
    mk, _ = market(bars_df(rows))
    assert len(trades(mk, cfg(trigger=E.CLOSE1, window=30, target_x10=0))) == 1


def test_target_needs_trade_through_also_on_open():
    rows = flat_range() + [at(0, 7008, 7011, 7006, 7010),  # fill 7012, R 13, target 7025
                           at(1, 7025, 7025, 7020, 7022),  # opens AT the target: not filled
                           at(2, 7022, 7026, 7021, 7024)]  # trades through: filled at 7025
    mk, _ = market(bars_df(rows))
    (t,) = trades(mk, cfg())
    assert t[7] == E.EXIT_TARGET and t[5] == 7025 and t[2] == t[1] + 2
