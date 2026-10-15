"""Audit module logic: planted drift, verdict rules, gate attribution, spot comparison, statistics."""

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from propfirm_backtest import audit as A
from propfirm_backtest import bars as B
from propfirm_backtest import orb_engine as E

sys.path.insert(0, str(Path(__file__).parent))


def day_minutes(day="2025-11-04", start="08:00", end="11:00", path=None):
    mins = pd.date_range(f"{day} {start}", f"{day} {end}", freq="1min", tz=E.ET, inclusive="left")
    c = np.full(len(mins), 7000.0) if path is None else path(mins)
    return pd.DataFrame({"ts_event_utc": mins.tz_convert("UTC").as_unit("ns"), "continuous_symbol": "CL.v.0",
                         "raw_symbol": "CLZ5", "open_ticks": c, "high_ticks": c + 2, "low_ticks": c - 2,
                         "close_ticks": c, "volume": 10})


def breakout_day(direction):
    """09:00-09:29 range 7000..7004, flat until 09:40, then one minute breaking up (+1) or down (-1)."""
    def path(mins):
        c = np.full(len(mins), 7002.0)
        mod = mins.hour * 60 + mins.minute
        c[mod >= 9 * 60 + 40] = 7002.0 + direction * 10
        return c
    return B.build_minutes(day_minutes(path=path))


def test_plant_drift_follows_the_breakout_direction_from_the_breakout_minute():
    m = breakout_day(+1)
    p = A.plant_drift(m, 0.5)
    off = p.close - m.close
    mod = m.mod
    assert (off[mod <= 9 * 60 + 40] == 0).all()  # nothing before or at the breakout minute
    assert off[mod == 9 * 60 + 50][0] == 5  # 10 minutes x 0.5 upwards
    assert off[mod == 10 * 60 + 50][0] == 30  # capped at 60 minutes, then held
    assert ((p.high >= p.close) & (p.low <= p.open)).all()
    assert A.plant_drift(m, 0.0) is m
    down = breakout_day(-1)
    assert (A.plant_drift(down, 1.0).close - down.close)[down.mod == 9 * 60 + 50][0] == -10


def test_plant_drift_needs_a_breakout():
    m = B.build_minutes(day_minutes())  # flat day: never leaves the range
    assert (A.plant_drift(m, 1.0).close == m.close).all()


def summ(eligible, wf):
    return {"champion_eligible": eligible, "wf_total": wf}


def econ(base, best):
    return {"baseline": {"total_usd": base}, "best_case": {"total_usd": best}}


def test_verdict_rules():
    assert A.verdict(None, {}, {}).startswith("INCOMPLETE")
    assert A.verdict(summ(False, float("nan")), {}, {}).startswith("INCOMPLETE")  # missing walk-forward is not a FAIL
    assert A.verdict(summ(True, 100), {}, {}).startswith("PASS")
    assert A.verdict(summ(False, 0), {}, econ(-1, -1)).startswith("INCOMPLETE")  # best case not run
    fail = {"best_case": summ(False, 0)}
    assert A.verdict(summ(False, 0), fail, econ(-5, -1)).startswith("GENUINE FAIL")
    assert A.verdict(summ(False, 0), fail, econ(-5, 300)).startswith("NO EDGE AFTER COSTS")
    assert A.verdict(summ(False, 0), fail, econ(200, 300)).startswith("FAIL ON ROBUSTNESS")  # money, not robust
    v = A.verdict(summ(False, 0), {"best_case": summ(True, 50), "zero_cost": summ(True, 10),
                                   "risk_2000": summ(False, 0)}, econ(-1, 1))
    assert v.startswith("FAIL DEPENDS") and "zero_cost" in v and "risk_2000" not in v


def test_gate_free_walk_forward_uses_only_earlier_years(tmp_path):
    years = np.arange(2010, 2022)
    ypnl = np.zeros((2, len(years)))
    ytr = np.full((2, len(years)), 100)
    ypnl[0, years < 2014] = 1000  # config 0 led the past ...
    ypnl[0, years >= 2014] = -50  # ... then loses: picked every year, books the losses
    ypnl[1, years == 2021] = 10_000  # config 1 only shines later: hindsight must not pick it
    A.dump_yearly(tmp_path / "y.npz", ypnl, ytr, years)
    r = A.gate_free_wf(tmp_path / "y.npz")
    assert r["years"] == 8 and r["total_usd"] < 0
    assert A.gate_free_wf(tmp_path / "missing.npz") is None


def test_gate_attribution_counts_single_gate_failures():
    df = pd.DataFrame({"trades": [500, 500, 100], "expectancy_usd": [5.0, 5.0, 5.0], "expectancy_slip2": [1.0] * 3,
                       "positive_year_frac": [0.8] * 3, "best_year_share": [0.2] * 3, "best_day_share": [0.05] * 3,
                       "p95_drawdown": [1500.0, 800.0, 800.0]})
    a = A.gate_attribution("ema_vwap", df)
    assert a["p95_drawdown"] == 1 and a["trades"] == 1 and a["_any_single"] == 2
    assert a["_dd_relaxed_2000_pass"] == 2 and a["_dd_off_pass"] == 2


def test_parse_fred_drops_missing_and_compare_spot():
    s = A.parse_fred("observation_date,DCOILWTICO\n2020-01-02,61.17\n2020-01-03,.\n2020-01-06,63.27\n")
    assert list(s.values) == [61.17, 63.27]
    idx = pd.bdate_range("2015-01-01", periods=300)
    spot = pd.Series(50 + np.random.default_rng(0).normal(0, 1, 300).cumsum(), index=idx)
    ok = A.compare_spot(spot + 0.3, spot)
    assert ok["ok"] and ok["median_abs_diff_usd"] == pytest.approx(0.3)
    shifted = A.compare_spot(spot.shift(1).dropna(), spot)  # one-day misalignment
    assert not shifted["ok"]


def test_hac_effective_n_shrinks_with_autocorrelation():
    rng = np.random.default_rng(1)
    iid = rng.normal(size=5000)
    ar = np.zeros(5000)
    for k in range(1, 5000):
        ar[k] = 0.6 * ar[k - 1] + rng.normal()
    assert A.hac_effective_n(iid) == pytest.approx(5000, rel=0.15)
    assert A.hac_effective_n(ar) < 0.5 * 5000


def test_rolling_windows_are_real_consecutive_attempts():
    p = np.full(300, 100.0)
    r = A.rolling_windows(p, np.zeros(300), 60)
    assert r["windows"] == 241 and r["pass_pct"] == 100.0  # +$100/day passes on day 30 in every window


def test_gate_failures_match_the_pipeline_gate_masks_including_nan():
    from propfirm_backtest import orb_search as O
    from propfirm_backtest import search as S
    rng = np.random.default_rng(3)
    n = 400
    df = pd.DataFrame({"trades": rng.integers(50, 900, n), "expectancy_usd": rng.normal(0, 10, n),
                       "expectancy_slip2": rng.normal(-5, 10, n), "positive_year_frac": rng.random(n),
                       "best_year_share": rng.random(n), "best_day_share": rng.random(n) * 0.5,
                       "p95_drawdown": rng.uniform(300, 2500, n), "trades_per_year": rng.uniform(5, 80, n)})
    for col in ["p95_drawdown", "positive_year_frac", "best_year_share", "expectancy_slip2"]:
        df.loc[rng.choice(n, 20, replace=False), col] = np.nan
    ema = A.gate_failures("ema_vwap", df).sum(axis=1) == 0
    assert (ema.to_numpy() == S.gate_mask(df).to_numpy()).all()
    orb = A.gate_failures("orb", df.assign(neighbours_profitable=1.0)).sum(axis=1) == 0
    want = O.gate_mask(df["trades"].to_numpy(), df["trades_per_year"].to_numpy(), df["expectancy_usd"].to_numpy(),
                       df["expectancy_slip2"].fillna(-1).to_numpy(), df["positive_year_frac"].to_numpy(),
                       df["best_year_share"].fillna(np.inf).to_numpy(), df["best_day_share"].fillna(np.inf).to_numpy(),
                       df["p95_drawdown"].to_numpy(), O.GATES["min_trades"])
    assert (orb.to_numpy() == want).all()


def test_scenario_patches_target_the_current_signatures():
    """apply_scenario rewrites default arguments by position: a new parameter must break this test, not the audit."""
    import inspect

    from propfirm_backtest import orb_search as O
    from propfirm_backtest import search as S

    def defaults(fn):
        return [k for k, v in inspect.signature(fn).parameters.items() if v.default is not inspect.Parameter.empty]
    assert defaults(O.Dev.kernel) == ["pessimistic"]
    assert defaults(O.Dev.daily) == ["slip", "pessimistic"]
    assert defaults(E.Market.trades) == ["n_days", "slip", "pessimistic"]
    assert defaults(S.grid_runs) == ["slip", "keep_trades", "pessimistic", "verbose"]
    assert {"BASE_SLIP", "GATE_SLIP", "GATES", "load_releases", "DATA_DIR", "metrics_frame"} <= set(vars(O))
    assert {"BASE_SLIP", "GATE_SLIP", "GATES", "OUT_DIR", "walk_forward"} <= set(vars(S))


# --- idea vs execution ------------------------------------------------------------------------------

def ramp_paths():
    """One day, 08:00-16:30 ET, price rising 1 tick a minute from 7000 (high = close + 1, low = open - 1)."""
    df = day_minutes(end="16:30", path=lambda mins: 7000.0 + np.arange(len(mins)))
    df["open_ticks"] = df["close_ticks"]
    df["high_ticks"], df["low_ticks"] = df["close_ticks"] + 1, df["close_ticks"] - 1
    m = B.build_minutes(df)
    mk = E.Market(m, np.unique(m.trading_day[m.front]), None)
    return A.Paths(mk.f, mk.days), mk.f


def test_paths_measure_uncensored_moves_and_excursions():
    paths, f = ramp_paths()
    row = int(np.flatnonzero(f.mod == 9 * 60)[0])  # 09:00, price 7060
    long = paths.measure(row, 1, 7060.0, False)
    assert long["move"][list(A.HORIZONS).index(30)] == 30  # 09:30 open = 7090
    assert long["mfe"][list(A.HORIZONS).index(30)] == 30  # high of 09:29 = 7089 + 1
    assert long["move"][-1] == 16 * 60 + 9 - 9 * 60  # session end = open of the 16:09 flat minute
    short = paths.measure(row, -1, 7060.0, False)
    assert short["move"][0] == -5 and short["mae"][0] == 5
    late = paths.measure(int(np.flatnonzero(f.mod == 15 * 60 + 30)[0]), 1, 0.0, False)
    assert np.isnan(late["move"][list(A.HORIZONS).index(60)])  # 16:30 is after the flat time: no value
    assert paths.row_at(int(f.trading_day[row]), 9 * 60) == row and paths.row_at(int(f.trading_day[row]), 17 * 60) == -1
    # a fill at the minute's open is exposed to that whole minute: the 09:00 low (7059) counts
    assert paths.measure(row, 1, 7060.0, True)["mae"][0] == 1 and long["mae"][0] <= 0


def test_a_horizon_inside_a_data_gap_is_not_measured():
    df = day_minutes(end="16:30", path=lambda mins: 7000.0 + np.arange(len(mins)))
    mod = pd.DatetimeIndex(df["ts_event_utc"]).tz_convert(E.ET)
    gap = (mod.hour == 10) & (mod.minute < 30)  # 10:00-10:29 missing
    m = B.build_minutes(df[~gap])
    mk = E.Market(m, np.unique(m.trading_day[m.front]), None)
    paths = A.Paths(mk.f, mk.days)
    row = int(np.flatnonzero(mk.f.mod == 9 * 60 + 50)[0])
    out = paths.measure(row, 1, float(mk.f.open[row]), True)
    assert np.isnan(out["move"][list(A.HORIZONS).index(15)])  # 10:05 falls 25 minutes into the gap
    assert np.isfinite(out["move"][list(A.HORIZONS).index(60)])  # 10:50 traded


def test_stop_hunt_helpers():
    paths, f = ramp_paths()
    row = int(np.flatnonzero(f.mod == 9 * 60)[0])
    assert paths.ran_after(row, 1, 7060.0, 50)  # rising market: a long reaches +50 later
    assert not paths.ran_after(row, -1, 7060.0, 50)
    assert paths.stop_then_ran(row, 1, 7060.0, 5) == -1  # never falls 5 against a long
    assert paths.stop_then_ran(row, -1, 7060.0, 5) == 0  # a short falls 5 behind and never recovers


def test_signal_edge_finds_a_planted_edge_and_not_noise():
    from test_audit_engine import planted_market
    from test_orb_engine import cfg as orb_cfg
    c = orb_cfg(L=15, trigger=E.CLOSE1, stop_type=E.OPPOSITE, target_x10=0, window=60, flat=60)
    verdicts = {}
    for drift in (0.0, 1.0):
        mk = planted_market(drift)
        t = mk.trades(c)
        e = A.signal_edge(A.Paths(mk.f, mk.days), t, 1.0, E.EXIT_STOP, np.random.default_rng(0), mk.days)
        verdicts[drift] = A.signal_verdict(e)
        if drift:
            h60 = next(x for x in e["horizons"] if x["horizon"] == "60")
            assert h60["edge_usd"] > 100 and h60["z"] > 5
    assert verdicts[0.0].startswith("NO DEMONSTRATED DIRECTIONAL EDGE")
    assert verdicts[1.0].startswith("IN-SAMPLE DIRECTIONAL EDGE")


def horizon(name, z, edge, local_z=None, h1=1.0, h2=1.0):
    return {"horizon": name, "z": z, "edge_usd": edge, "local_z": z if local_z is None else local_z,
            "local_edge_usd": edge, "edge_2010_15": h1, "edge_2016_21": h2}


def test_signal_verdict_corrects_for_many_horizons_regime_and_halves():
    e = {"horizons": [horizon("5", 2.2, 3.0)] + [horizon(str(h), 0.1, 0.1) for h in (15, 30, 60, 120)], "best_z": 2.2}
    assert A.signal_verdict(e).startswith("NO DEMONSTRATED DIRECTIONAL EDGE")  # z 2.2 is luck across 5 horizons
    e["horizons"][0] = horizon("5", 4.0, 3.0)
    assert A.signal_verdict(e).startswith("IN-SAMPLE DIRECTIONAL EDGE at 5")
    e["horizons"][0] = horizon("5", 4.0, 3.0, local_z=0.5)  # only beats random days from other regimes
    assert A.signal_verdict(e).startswith("REGIME / LUCK")
    e["horizons"][0] = horizon("5", 4.0, 3.0, h1=-2.0)  # one half carries it all
    assert A.signal_verdict(e).startswith("REGIME / LUCK")
    e["horizons"][0] = horizon("5", 4.0, 3.0, h1=float("nan"))  # no signals in a half: no veto
    assert A.signal_verdict(e).startswith("IN-SAMPLE DIRECTIONAL EDGE")


def test_signal_that_only_rides_the_regime_is_not_called_an_edge():
    """The daily drift turns slowly (one sine wave over 200 days). A 'signal' that just takes the side of the
    current regime at 10:00 beats random days from the whole period, but not random days from the same weeks."""
    rng = np.random.default_rng(4)
    frames = []
    bdays = pd.bdate_range("2015-01-05", periods=200)
    for k, day in enumerate(bdays):
        mins = pd.date_range(f"{day.date()} 08:00", f"{day.date()} 16:30", freq="1min", tz=E.ET)
        drift = 0.3 * np.sin(2 * np.pi * k / 200)
        c = 7000 + (drift + rng.integers(-2, 3, len(mins))).cumsum()
        frames.append(pd.DataFrame({"ts_event_utc": mins.tz_convert("UTC").as_unit("ns"), "continuous_symbol": "CL.v.0",
                                    "raw_symbol": "CLZ5", "open_ticks": c, "high_ticks": c + 1, "low_ticks": c - 1,
                                    "close_ticks": c, "volume": 10}))
    m = B.build_minutes(pd.concat(frames, ignore_index=True))
    mk = E.Market(m, np.unique(m.trading_day[m.front]), None)
    f = mk.f
    rows = np.flatnonzero(f.mod == 10 * 60)
    side = np.where(np.sin(2 * np.pi * np.arange(len(rows)) / 200) >= 0, 1, -1).astype(np.int8)
    t = (np.arange(len(rows)), rows, rows + 60, side, f.open[rows] + side, f.open[rows + 60] - side,
         np.zeros(len(rows)), np.full(len(rows), E.EXIT_TIME, np.int8))
    e = A.signal_edge(A.Paths(f, mk.days), t, 1.0, E.EXIT_STOP, np.random.default_rng(0), mk.days)
    h60 = next(x for x in e["horizons"] if x["horizon"] == "60")
    assert h60["z"] > 5 and abs(h60["local_z"]) < 3  # the global baseline is fooled, the local one is not
    assert not A.signal_verdict(e).startswith("IN-SAMPLE DIRECTIONAL EDGE")


def test_day_clustering_does_not_count_same_day_copies_as_new_evidence():
    rng = np.random.default_rng(6)
    diff = rng.normal(1.0, 10.0, 400)
    day = np.arange(400)
    _, z_once, n_once = A.clustered(diff, day)
    _, z_twice, n_twice = A.clustered(np.r_[diff, diff], np.r_[day, day])  # every signal duplicated on its day
    assert n_once == n_twice == 400
    assert z_twice == pytest.approx(z_once, rel=0.01)  # naive iid z would grow by sqrt(2)


def test_exclusive_controls_are_never_reused_and_never_a_signal_slot():
    from test_audit_engine import planted_market
    from test_orb_engine import cfg as orb_cfg
    mk = planted_market(0.0, n_days=120)
    t = mk.trades(orb_cfg(L=15, trigger=E.CLOSE1, stop_type=E.OPPOSITE, target_x10=0, window=60, flat=60))
    paths = A.Paths(mk.f, mk.days)
    used = {(int(mk.f.trading_day[r]), int(mk.f.mod[r]), int(d)) for r, d in zip(t[1], t[3])}
    signal_slots = set(used)
    picked = []
    rng = np.random.default_rng(0)
    for r, d in zip(t[1], t[3]):
        rows = paths.matched_rows(mk.days, int(mk.f.mod[r]), int(mk.f.trading_day[r]), 20, rng, used, int(d))
        picked += [(int(mk.f.trading_day[x]), int(mk.f.mod[x]), int(d)) for x in rows]
    assert len(picked) == len(set(picked)) > 0
    assert not set(picked) & signal_slots
