import numpy as np
import pandas as pd
import pytest

from propfirm_backtest import bars as B
from propfirm_backtest import vwap_break_engine as V
from propfirm_backtest import vwap_break_reference as R
from propfirm_backtest.orb_engine import EXIT_FALLBACK, EXIT_STOP, EXIT_TARGET, EXIT_TIME
from propfirm_data.config import BARS_DIR

LINE = 100.0
FEE, TICK = V.DEFAULTS[V.K_FEE_USD], V.DEFAULTS[V.K_TICK_USD]


def quiet(lo, hi, n=5):
    """n one-minute candles spanning [lo, hi] exactly (open = close = mid)."""
    mid = (lo + hi) / 2
    return [(mid, hi, lo, mid)] * n


def sim(bars, cfg=None, line=LINE, atr14=20.0, atr100=20.0, vwap=105.0, day=None, slip=1.0, pessimistic=True,
        ema=None, sma=None, contract=None, front=None, flat=10**9):
    """bars: list of lists of (o, h, l, c) minutes. Indicators are constant unless given as arrays;
    EMA and SMA both default to `line`."""
    nb = len(bars)
    sizes = [len(b) for b in bars]
    fs = np.concatenate([[0], np.cumsum(sizes)[:-1]]).astype(np.int64)
    fe = fs + np.array(sizes)
    mins = np.array([m for b in bars for m in b], dtype=float)
    hi = np.array([max(m[1] for m in b) for b in bars])
    lo = np.array([min(m[2] for m in b) for b in bars])
    cl = np.array([b[-1][3] for b in bars])
    arr = lambda v: np.full(nb, float(v)) if np.isscalar(v) else np.asarray(v, float)
    day = np.zeros(nb, np.int64) if day is None else np.asarray(day, np.int64)
    contract = np.zeros(nb, np.int32) if contract is None else np.asarray(contract, np.int32)
    if front is not None:  # warm-up (not front month) bars carry no tradable minutes
        fs = np.where(front, fs, -1); fe = np.where(front, fe, -1)
    bar_args = (fs, fe, np.arange(nb, dtype=np.int64) + 1000 * day, day, contract, hi, lo, cl,
                arr(line if ema is None else ema), arr(line if sma is None else sma), arr(atr14), arr(atr100), arr(vwap), np.ones(nb, np.bool_))
    n = len(mins)
    minute_args = (np.arange(n, dtype=np.int64), mins[:, 0], mins[:, 1], mins[:, 2], mins[:, 3],
                   np.full(n, flat, np.int64), np.zeros(n, np.bool_))
    t = V.simulate(V.config() if cfg is None else cfg, bar_args, minute_args, slip, pessimistic)
    return pd.DataFrame(dict(zip(V.TRADE_COLS, t)))


# C1 touches the line (100), C2 clears it and breaks C1's high: long, level 109, stop 95, R 14, target 137
C1 = quiet(95, 105)
C2 = quiet(102, 108)[:4] + [(107, 108, 106, 106)]  # low 102: not itself a touch (tol 1.25)


def test_long_to_target():
    t = sim([C1, C2, quiet(102, 110), quiet(120, 138)])
    assert len(t) == 1
    r = t.iloc[0]
    assert (r.dir, r.px_in, r.px_out, r.why, r.cls, r.risk) == (1, 110.0, 137.0, EXIT_TARGET, V.NORMAL, 14.0)
    assert r.pnl_usd == pytest.approx((137 - 110) * TICK - FEE)
    assert not r.addon  # target 27 ticks from the fill: no add-on


def test_target_needs_one_tick_through():
    t = sim([C1, C2, quiet(102, 110), quiet(120, 137)])  # touches 137, never trades 138
    assert t.why.tolist() == [EXIT_FALLBACK]  # data ends while holding: out at the last close


def test_hot_atr_gives_2_5r():
    t = sim([C1, C2, quiet(102, 110), quiet(120, 145)], atr14=23.0, atr100=20.0)  # 23 > 1.12 * 20
    assert t.px_out.iloc[0] == 109 + np.floor(2.5 * 14)


def test_touch_tolerance():
    near = quiet(101.25, 105)  # misses the line by 1.25 ticks: still a touch
    far = quiet(101.5, 105)
    c2 = quiet(102, 108)
    assert len(sim([near, c2, quiet(103, 110), quiet(120, 140)])) == 1
    assert len(sim([far, c2, quiet(103, 110), quiet(120, 140)])) == 0


def test_c2_must_clear_and_stay_inside():
    not_clear = quiet(100, 108)  # low on the line, not above it
    # not_clear itself touches the line, so a later setup may trade; the first one (fill 110) must not
    assert 110.0 not in sim([C1, not_clear, quiet(102, 110), quiet(120, 140)]).px_in.tolist()
    breaks_low = quiet(94, 108)  # C2 low below C1 low: no long
    assert 110.0 not in sim([C1, breaks_low, quiet(102, 110), quiet(120, 140)]).px_in.tolist()


def test_c3_touch_cancels_unfilled_order():
    c3 = quiet(99, 108)  # touches the line, never reaches 109; C4 gaps through 109 (fill 112.5 + 1)
    bars = [C1, C2, c3, quiet(105, 120), quiet(120, 140)]
    assert 113.5 not in sim(bars).px_in.tolist()  # (c3 starts a new setup of its own)
    assert sim(bars, cfg=V.config(cancel_touch=0)).px_in.tolist()[0] == 113.5


def test_order_expires_after_two_bars():
    wait = quiet(102, 108)
    assert len(sim([C1, C2, wait, wait, quiet(105, 140)])) == 0
    assert len(sim([C1, C2, wait, wait, quiet(105, 140)], cfg=V.config(expiry_bars=3))) == 1


def test_band_scalp_far_and_skip():
    # close 106; vwap far away: out of band (10 ticks). R 14 < 18: scalp at 1R
    t = sim([C1, C2, quiet(102, 110), quiet(120, 140)], vwap=150.0)
    assert t.cls.tolist() == [V.SCALP] and t.px_out.iloc[0] == 109 + 14
    # wider stop (R 24): out of band and not scalp; far needs >= 70 ticks and EMA above SMA
    c1 = quiet(85, 105)
    assert len(sim([c1, C2, quiet(102, 110), quiet(120, 140)], vwap=150.0)) == 0


def test_far_needs_trend():
    c1 = quiet(85, 105)  # R 24
    bars = [c1, C2, quiet(102, 110), quiet(120, 140)]
    vw = 106 + 80.0  # 80 ticks from the close
    assert len(sim(bars, vwap=vw)) == 0  # EMA == SMA: no trend
    t = sim(bars, ema=100.5, sma=99.5, vwap=vw)
    assert t.cls.tolist() == [V.FAR] and t.px_out.iloc[0] == 109 + 24


def test_risk_50_skipped_and_wide_class():
    c1_wide = quiet(65, 105)  # R 44: wide (band 0.7 * 20 = 14 >= dist 1)
    t = sim([c1_wide, C2, quiet(102, 110), quiet(120, 200)])
    assert t.cls.tolist() == [V.WIDE]
    c1_skip = quiet(59, 105)  # R 50
    assert len(sim([c1_skip, C2, quiet(102, 110), quiet(120, 200)])) == 0


def test_stop_and_target_same_minute():
    both = [(120, 140, 90, 100)]
    t = sim([C1, C2, quiet(102, 110), both])
    assert t.why.tolist() == [EXIT_STOP] and t.px_out.iloc[0] == 95 - 1
    t = sim([C1, C2, quiet(102, 110), both], pessimistic=False)
    assert t.why.tolist() == [EXIT_TARGET]


def test_entry_minute_stop_is_pessimistic():
    t = sim([C1, C2, [(105, 110, 94, 100)]])
    assert t.why.tolist() == [EXIT_STOP] and t.pnl_usd.iloc[0] == pytest.approx(-(110 - 94) * TICK - FEE)


def test_addon_fills_and_shares_exit():
    c1 = quiet(75, 105)  # R 34: band 0.7 * 20 = 14; target 109 + 68 = 177; add-on at 145
    t = sim([c1, C2, quiet(102, 110), quiet(120, 150), quiet(150, 178)])
    r = t.iloc[0]
    assert r.addon and r.addon_px == 146.0 and r.px_out == 177.0
    assert r.pnl_usd == pytest.approx((177 - 110) * TICK - FEE + (177 - 146) * 6 - V.DEFAULTS[V.K_ADD_FEE_USD])
    t = sim([c1, C2, quiet(102, 110), quiet(120, 150), quiet(150, 178)], cfg=V.config(addon=0))
    assert not t.addon.iloc[0]


def test_addon_stopped_with_base():
    c1 = quiet(75, 105)
    t = sim([c1, C2, quiet(102, 110), quiet(120, 150), quiet(74, 120)])
    r = t.iloc[0]
    assert r.addon and r.why == EXIT_STOP
    assert r.pnl_usd == pytest.approx((74 - 110) * TICK - FEE + (74 - 146) * 6 - V.DEFAULTS[V.K_ADD_FEE_USD])
    assert r.mae_usd >= -r.pnl_usd


def test_daily_stop_blocks_new_orders_same_day_only():
    c1 = quiet(75, 105)  # R 34 loss ~ $420 + slip + fees > $432
    loser = [c1, C2, quiet(102, 110), quiet(74, 100)]
    again = [C1, C2, quiet(102, 110), quiet(120, 138)]
    assert len(sim(loser + again)) == 1
    t = sim(loser + again, day=[0] * 4 + [1] * 4)
    assert len(t) == 2 and t.day.tolist() == [0, 1]


def test_new_day_kills_pending_order():
    assert len(sim([C1, C2, quiet(105, 140)], day=[0, 0, 1])) == 0


def test_long_short_mirror():
    long_bars = [C1, C2, quiet(102, 110), quiet(120, 138)]
    flip = lambda b: [(-o, -l, -h, -c) for o, h, l, c in b]
    short_bars = [flip(b) for b in long_bars]
    lt = sim(long_bars)
    st = sim(short_bars, line=-LINE, vwap=-105.0)
    assert st.dir.tolist() == [-1] and st.pnl_usd.tolist() == pytest.approx(lt.pnl_usd.tolist())


def test_sma_atr_match_pandas():
    rng = np.random.default_rng(1)
    n = 400
    close = 7000 + np.cumsum(rng.integers(-5, 6, n)).astype(float)
    high = close + rng.integers(0, 6, n); low = close - rng.integers(0, 6, n)
    contract = np.repeat([0, 1], n // 2).astype(np.int32)
    s, ok = V._sma(close, contract, 50)
    exp = pd.Series(close).groupby(contract).transform(lambda x: x.rolling(50).mean()).to_numpy()
    assert np.allclose(s[ok], exp[ok]) and (ok == ~np.isnan(exp)).all()
    a, aok = V._atr(high, low, close, contract, 14)
    for k in (0, 1):
        sl = contract == k
        h, l, c = pd.Series(high[sl]), pd.Series(low[sl]), pd.Series(close[sl])
        tr = pd.concat([h - l, (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1)
        w = np.full(sl.sum(), np.nan)
        w[13] = tr[:14].mean()
        for i in range(14, len(w)):
            w[i] = (w[i - 1] * 13 + tr[i]) / 14
        assert np.allclose(a[sl][13:], w[13:]) and not aok[sl][:13].any()


def test_apply_dll():
    p, lo = V.apply_dll(np.array([500.0, -300.0, 200.0]), np.array([-200.0, -1200.0, -1000.0]))
    assert p.tolist() == [500.0, -1000.0, -1000.0] and lo.tolist() == [-200.0, -1000.0, -1000.0]


@pytest.mark.skipif(not BARS_DIR.exists(), reason="no CL data")
def test_engine_matches_reference_on_real_data():
    m = B.load_minutes(start="2026-08-01", end="2026-09-01")
    mk = V.Market(m, strict_expiry=True)
    for cfg, slip, pess in [(V.config(), 1.0, True), (V.config(addon=0, daily_stop=200), 0.0, False)]:
        t = mk.trades(cfg, slip=slip, pessimistic=pess)
        eng = list(zip(*[a.tolist() for a in t[:10]], np.round(t[11], 6).tolist()))
        ref = [(int(a), int(b), int(c), int(d), float(e), float(f), int(g), int(h), float(i), bool(j),
                round(float(k), 6)) for a, b, c, d, e, f, g, h, i, j, k in R.trades(mk, cfg, slip, pess)]
        assert len(eng) > 50 and eng == ref


def test_flat_time_closes_position_and_cancels_orders():
    # minutes are numbered 0..; flat at minute 12 = 3rd minute of the 4th bar
    t = sim([C1, C2, quiet(102, 110), quiet(111, 120)], flat=17)
    assert t.why.tolist() == [EXIT_TIME] and t.out_row.iloc[0] == 17
    assert len(sim([C1, C2, quiet(102, 110)], flat=10)) == 0  # flat before the order can fill


def test_contract_change_while_holding_falls_back_and_counts_for_daily_stop():
    c1 = quiet(75, 105)
    old = [c1, C2, quiet(102, 110), quiet(80, 100)]  # long from 110, still open at the roll
    new = [C1, C2, quiet(102, 110), quiet(120, 138)]
    t = sim(old + new, contract=[0] * 4 + [1] * 4)
    assert t.why.tolist()[0] == EXIT_FALLBACK and len(t) == 2  # out at 90 - 1: -$259
    t = sim(old + new, contract=[0] * 4 + [1] * 4, cfg=V.config(daily_stop=200))
    assert t.why.tolist() == [EXIT_FALLBACK]  # the fallback loss counts toward the daily stop
    assert t.px_out.iloc[0] == 89.0 and t.out_row.iloc[0] == 19


def test_warmup_bars_do_not_reset_the_daily_stop():
    c1 = quiet(75, 105)
    loser = [c1, C2, quiet(102, 110), quiet(74, 100)]
    warm = [quiet(500, 510)] * 2  # next contract's warm-up history, not tradable
    again = [C1, C2, quiet(102, 110), quiet(120, 138)]
    t = sim(loser + warm + again, front=[True] * 4 + [False] * 2 + [True] * 4,
            day=[5] * 4 + [1] * 2 + [5] * 4, contract=[0] * 4 + [1] * 2 + [1] * 4)
    assert len(t) == 1


def test_config_rejects_unknown_keys():
    with pytest.raises(ValueError):
        V.config(bandd=0.4)


def test_gates_pass_and_fail():
    from propfirm_backtest import vwap_break_eval as X
    good = {"trades": 400, "trades_per_year": 30, "net_usd": 5000.0, "positive_year_frac": 0.7,
            "best_year_share": 0.3, "best_day_share": 0.05, "p95_dd_60d": 900.0}
    assert all(X.gates(good, 100.0, 0.8).values())
    for key, bad in [("trades", 10), ("net_usd", -1.0), ("p95_dd_60d", 1500.0), ("best_day_share", 0.4)]:
        assert not all(X.gates(good | {key: bad}, 100.0, 0.8).values())
    assert not all(X.gates(good, -1.0, 0.8).values())
    assert not all(X.gates(good, 100.0, 0.5).values())
    assert not all(X.gates(good, 100.0, float("nan")).values())


def test_metrics_on_known_trades():
    from propfirm_backtest import vwap_break_eval as X
    days = pd.DatetimeIndex(pd.to_datetime(["2020-01-02", "2020-01-03", "2021-01-04"]))
    df = pd.DataFrame({"date": days[[0, 0, 2]], "pnl_usd": [300.0, -100.0, -50.0],
                       "mae_usd": [20.0, 150.0, 60.0], "addon": [False, True, False]})
    m = X.metrics(df, days, combine=False)
    assert (m["trades"], m["addon_legs"], m["net_usd"], m["green_days"], m["red_days"]) == (3, 1, 150.0, 1, 1)
    assert m["worst_day_usd"] == -60.0 and m["positive_year_frac"] == 0.5
    assert m["best_year_share"] == pytest.approx(200 / 150) and m["profit_factor"] == 2.0
