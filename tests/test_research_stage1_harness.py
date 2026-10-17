"""propfirm_research.settlement stage-1 families (H027 TAS / signed flow, H028 cross-energy): causal signal rules,
signs, variant-local missing data, the stage-1 screen and the run guards. Synthetic data only."""

import json

import numpy as np
import pandas as pd
import pytest

from propfirm_research import settlement as S
from propfirm_research.data import utc_minutes
from propfirm_research.periods import et_minute_of_day, trading_day

FAR = 10**9
C = "CLH5@2015-02"
EXP = {C: FAR, "CLJ5@2015-03": FAR}
NS = 60_000_000_000


def bars(n_days=150, seed=0, start="2015-01-05", contract=C, plant=None):
    """Synthetic 14:00-16:20 ET minutes, one contract. plant(day_index) -> ticks added from 14:35 on (linear to 16:05)."""
    rng = np.random.default_rng(seed)
    frames = []
    for k, d in enumerate(pd.bdate_range(start, periods=n_days)):
        ts = pd.date_range(f"{d:%Y-%m-%d} 14:00", f"{d:%Y-%m-%d} 16:20", freq="1min",
                           tz="America/New_York").tz_convert("UTC")
        o = 5000.0 + np.cumsum(rng.integers(-2, 3, len(ts))).astype(float)
        if plant is not None:
            minute = np.arange(len(ts))  # 0 = 14:00
            ramp = np.clip((minute - 35) / 90, 0, None)
            o = o + plant(k) * ramp
        c = o + rng.integers(-1, 2, len(ts))
        frames.append(pd.DataFrame({"ts_event_utc": ts, "contract": contract, "open": o,
                                    "high": np.maximum(o, c) + 1, "low": np.minimum(o, c) - 1, "close": c,
                                    "volume": 100.0}))
    df = pd.concat(frames, ignore_index=True)
    df["trading_day"] = trading_day(df["ts_event_utc"])
    df["mod"] = et_minute_of_day(df["ts_event_utc"])
    df["tmin"] = utc_minutes(df["ts_event_utc"])
    return df


def days_of(df):
    return np.unique(df["trading_day"].to_numpy())


def at(day, mod, sec=0):
    return int(S.cutoff_ns(np.array([day]), mod)[0]) + sec * 1_000_000_000


def tas(rows):
    """rows: (day, ET minute, second, raw_symbol, size, side, instrument_id[, known delay s])"""
    out = []
    for r in rows:
        day, mod, sec, sym, size, side, iid = r[:7]
        ev = at(day, mod, sec)
        out.append({"trading_day": day, "event_ns": ev, "known_ns": ev + (r[7] if len(r) > 7 else 0) * 10**9,
                    "mod": mod, "raw_symbol": sym, "is_spread": "-" in sym, "size": size, "side": side,
                    "instrument_id": iid, "diff_ticks": 0})
    return pd.DataFrame(out)


def cl_trades(rows, contract=C, delay_s=0):
    """rows: (day, ET minute, size, side, price, bid, ask); delay_s: receive time after the event (late reports)."""
    out = []
    for day, mod, size, side, price, bid, ask in rows:
        ev = at(day, mod, 10)
        out.append({"trading_day": day, "mod": mod, "event_ns": ev, "known_ns": ev + delay_s * 10**9, "size": size,
                    "side": side, "price": price, "bid": bid, "ask": ask, "contract": contract})
    return pd.DataFrame(out)


# --- signal pieces --------------------------------------------------------------------------------------

def test_quote_rule():
    got = S.quote_side([101, 99, 100, 100, 100], [99, 99, 99, 100, np.nan], [101, 101, 101, 100, 101])
    assert got.tolist() == [1, -1, 0, 0, 0]  # at ask, at bid, inside, locked book, no bid


def test_tas_imbalance_front_mapping_known_at_and_side_rule():
    d = days_of(bars(n_days=5))
    cut = S.cutoff_ns(d, S.ENTRY)
    t = tas([(d[0], 600, 0, "CLTH5", 10, 1, 7), (d[0], 700, 0, "CLTH5", 4, -1, 7),
             (d[0], 700, 0, "CLTJ5", 50, 1, 8),                  # deferred month: not the front
             (d[0], 700, 0, "CLTH5-CLTJ5", 50, 1, 9),            # spread: excluded
             (d[0], 14 * 60 + 34, 59, "CLTH5", 30, 1, 7, 2),      # received after the 14:35 cutoff
             (d[1], 600, 0, "CLTH5", 98, 1, 7), (d[1], 601, 0, "CLTH5", 2, 0, 7),   # 2% without side
             (d[2], 600, 0, "CLTH5", 5, 1, 7), (d[2], 601, 0, "CLTH5", 5, 1, 70),   # two ids for one symbol
             (d[4], 600, 0, "CLTH5", 6, -1, 7)])
    got = S.tas_imbalance(t, d, [C] * 5, cut)
    assert got.loc[d[0], "imb"] == 6 and got.loc[d[0], "ok"]
    assert not got.loc[d[1], "ok"] and not got.loc[d[2], "ok"] and not got.loc[d[3], "ok"]  # d3: no trades
    assert got.loc[d[4], "imb"] == -6 and got.loc[d[4], "ok"]


def test_outright_imbalance_window_quote_rule_and_contract():
    d = days_of(bars(n_days=4))
    w = S.RESIDUAL_WINDOW
    t = pd.concat([
        cl_trades([(d[0], 865, 10, 1, 100, 99, 100), (d[0], 870, 3, 0, 99, 99, 100),   # N at the bid: -1
                   (d[0], 875, 50, 1, 100, 99, 100),                                  # 14:35: outside the window
                   (d[1], 866, 99, 1, 100, 99, 100), (d[1], 867, 2, 0, 99.5, 99, 100),  # 2% unclassified
                   (d[2], 866, 5, -1, 99, 99, 100)]),
        cl_trades([(d[3], 866, 5, 1, 100, 99, 100)], contract="CLJ5@2015-03")])       # not the entry contract
    got = S.outright_imbalance(t, d, [C] * 4, w, S.cutoff_ns(d, S.ENTRY))
    assert got.loc[d[0], "imb"] == 7 and got.loc[d[0], "ok"]
    assert not got.loc[d[1], "ok"] and got.loc[d[2], "ok"] and not got.loc[d[3], "ok"]


def daily_flow(df, sign_of_day, tas_size=50, cl_size=40):
    """One front-TAS trade and one window trade per day with the given sign."""
    rows_t, rows_c = [], []
    for k, day in enumerate(days_of(df)):
        s = sign_of_day(k)
        size = 10 + (k * 7) % 41  # varying magnitude so the percentile filter bites
        rows_t.append((day, 600, 0, "CLTH5", size + tas_size, s, 7))
        rows_c.append((day, 866, size + cl_size, s, 100, 99, 100))
        rows_c.append((day, 861, size + cl_size, s, 100, 99, 100))
    return tas(rows_t), cl_trades(rows_c)


def test_h027_signs_follow_the_card():
    sign = lambda k: 1 if (k * 5) % 3 else -1  # noqa: E731
    df = bars(plant=lambda k: 30.0 * sign(k))  # price rises 30 ticks over 14:35-16:05 in the flow's direction
    t, c = daily_flow(df, sign)
    var, counts = S.h027(df, days_of(df), t, c, expiry_tmin=EXP)
    g = {k: float((v["dir"] * v["w"]["ret_ticks"].fillna(0)).sum()) for k, v in var.items()}
    assert g["v1_tas_residual"] > 0 and g["v3_outright_residual"] > 0      # continuation: +sign
    assert g["v2_tas_unwind"] < 0 and g["v4_outright_unwind"] < 0          # unwind: -sign over 14:31-15:00
    assert all(counts[k]["warmup"] == 60 for k in var)                     # first 60 eligible days
    assert all((v["dir"] != 0).sum() > 0 for v in var.values())


def test_h027_ignores_late_reports_and_trades_outside_windows():
    sign = lambda k: 1 if k % 2 else -1  # noqa: E731
    df = bars()
    t, c = daily_flow(df, sign)
    base, _ = S.h027(df, days_of(df), t, c, expiry_tmin=EXP)
    d = days_of(df)
    late = tas([(day, 14 * 60 + 34, 59, "CLTH5", 999, 1, 7, 1) for day in d])          # received at 14:35:00
    after = cl_trades([(day, 875, 999, 1, 100, 99, 100) for day in d] +                  # 14:35, after v3's window
                      [(day, 870, 999, 1, 100, 99, 100) for day in d])                   # 14:30, after v4's window
    got, _ = S.h027(df, d, pd.concat([t, late]), pd.concat([c, after[after["mod"] == 875]]), expiry_tmin=EXP)
    for k in ("v1_tas_residual", "v3_outright_residual"):
        assert np.array_equal(got[k]["dir"], base[k]["dir"]), k
    got4, _ = S.h027(df, d, t, pd.concat([c, after[after["mod"] == 870]]), expiry_tmin=EXP)
    assert np.array_equal(got4["v4_outright_unwind"]["dir"], base["v4_outright_unwind"]["dir"])


# --- H028 ------------------------------------------------------------------------------------------------

def test_bar_return_needs_both_exact_bars_and_bz_staleness_rule():
    df = bars(n_days=3)
    d = days_of(df)
    r = S.bar_return(df, d)
    a = df[(df["trading_day"] == d[0]) & (df["mod"] == 865)]["open"].iloc[0]
    b = df[(df["trading_day"] == d[0]) & (df["mod"] == 874)]["close"].iloc[0]
    assert r.loc[d[0], "r"] == pytest.approx(np.log(b / a))
    no_1425 = df[~((df["trading_day"] == d[1]) & (df["mod"] == 865))]
    assert np.isnan(S.bar_return(no_1425, d).loc[d[1], "r"])
    # BZ: no 14:25 bar -> start from the 14:23 close; end from the last bar starting 14:32-14:34
    bz = df[(df["mod"] <= 863) | (df["mod"] == 872)]
    got = S.bz_return(bz, d)
    s0 = bz[(bz["trading_day"] == d[0]) & (bz["mod"] == 863)]["close"].iloc[0]
    e0 = bz[(bz["trading_day"] == d[0]) & (bz["mod"] == 872)]["close"].iloc[0]
    assert got.loc[d[0], "r"] == pytest.approx(np.log(e0 / s0))
    stale = df[(df["mod"] <= 861) | (df["mod"] == 872)]  # last early bar 14:21: too old
    assert np.isnan(S.bz_return(stale, d).loc[d[0], "r"])
    nothing_late = df[df["mod"] <= 870]
    assert np.isnan(S.bz_return(nothing_late, d).loc[d[0], "r"])


def test_trailing_sd_uses_previous_existing_days_only():
    r = np.array([1.0, np.nan, 2.0, 4.0, np.nan, 8.0, 16.0])
    got = S.trailing_sd(r, lookback=3)
    assert np.isnan(got[:4]).all()
    assert got[4] == pytest.approx(np.std([1, 2, 4], ddof=1))
    assert got[6] == pytest.approx(np.std([2, 4, 8], ddof=1))


def related(df, seed):
    out = {}
    for i, sym in enumerate(("RB.v.0", "HO.v.0", "BZ.v.0")):
        x = bars(n_days=len(days_of(df)), seed=seed + i, contract=sym)
        out[sym] = x
    return out


def test_h028_missing_brent_is_variant_local():
    df = bars(n_days=60)
    rel = related(df, 10)
    d = days_of(df)
    bz = rel["BZ.v.0"]
    rel["BZ.v.0"] = bz[bz["trading_day"] != d[40]]
    var, _ = S.h028(df, d, rel, expiry_tmin=EXP)
    k = 40
    assert var["v1_products"]["emitted"][k] and not var["v2_brent"]["emitted"][k]
    assert not var["v3_agreement"]["emitted"][k]
    assert not var["v1_products"]["emitted"][:20].any()  # 20-day volatility warm-up


def test_h028_trades_toward_the_related_markets():
    base = bars(n_days=120, seed=3)
    rel = related(base, 20)
    d = days_of(base)
    tmp, _ = S.h028(base, d, rel, expiry_tmin=EXP)
    s = np.sign(tmp["v1_products"]["dir"])  # the side v1 takes each day, from 14:34 information only
    df = bars(n_days=120, seed=3, plant=lambda k: 25.0 * s[k])
    var, _ = S.h028(df, d, rel, expiry_tmin=EXP)
    assert np.array_equal(np.sign(var["v1_products"]["dir"]), s)  # planting after 14:35 changes no signal
    g = float((var["v1_products"]["dir"] * var["v1_products"]["w"]["ret_ticks"].fillna(0)).sum())
    assert g > 0


# --- screen and run guards --------------------------------------------------------------------------------

def screen_variants(gross_by_day, years_days):
    days = np.array(years_days)
    w = pd.DataFrame({"trading_day": days, "valid": True, "ret_ticks": np.asarray(gross_by_day, float)})
    return {"v1": {"w": w, "dir": np.ones(len(days)), "emitted": np.ones(len(days), bool)}}


def test_stage1_screen_rules():
    d15 = [16450 + i for i in range(60)]  # 2015
    d16 = [16900 + i for i in range(60)]  # 2016
    good = screen_variants([20.0] * 60 + [18.0] * 60, d15 + d16)
    tab = S.stage1_table(good, 2.0, 500, ["v1"])
    assert bool(tab.loc[0, "stage1_pass"]) and not bool(tab.loc[0, "promote"])
    bad_year = screen_variants([30.0] * 60 + [-2.0] * 60, d15 + d16)
    assert not S.stage1_table(bad_year, 2.0, 500, ["v1"]).loc[0, "years_ok"]
    one_day = screen_variants([2000.0] + [0.1] * 119, d15 + d16)
    t1 = S.stage1_table(one_day, 2.0, 500, ["v1"])
    assert not t1.loc[0, "day_share_ok"] and not t1.loc[0, "stage1_pass"]
    few = screen_variants([20.0] * 20 + [20.0] * 20, d15[:20] + d16[:20])
    assert not S.stage1_table(few, 2.0, 500, ["v1"]).loc[0, "trades_ok"]  # 20 a year < 25


def test_run_needs_s004_acceptance_and_runs_once(tmp_path, monkeypatch):
    facts = tmp_path / "facts.json"
    monkeypatch.setattr(S, "S004_FACTS", facts)
    monkeypatch.setattr(S, "CARD_DIRS", {"H027": tmp_path / "H027", "H028": tmp_path / "H028"})
    with pytest.raises(RuntimeError):
        S.run_stage1("H027")
    facts.write_text(json.dumps({"facts": {"acceptance": {"all_ok": False}}}))
    with pytest.raises(RuntimeError):
        S.run_stage1("H027")
    (tmp_path / "H028").mkdir()
    (tmp_path / "H028" / "explore.csv").write_text("x")
    with pytest.raises(FileExistsError):
        S.run_stage1("H028")


# --- review follow-ups: exact 1% boundary, endpoint rules, the one-shot run ------------------------------

@pytest.mark.parametrize("unsigned, ok", [(1, True), (2, False)])  # of 100 lots: exactly 1% passes, more fails
def test_side_coverage_boundary_is_exactly_one_percent(unsigned, ok):
    d = days_of(bars(n_days=2))
    t = tas([(d[0], 600, 0, "CLTH5", 100 - unsigned, 1, 7), (d[0], 601, 0, "CLTH5", unsigned, 0, 7)])
    assert bool(S.tas_imbalance(t, d, [C] * 2, S.cutoff_ns(d, S.ENTRY)).loc[d[0], "ok"]) is ok
    c = cl_trades([(d[0], 866, 100 - unsigned, 1, 100, 99, 100), (d[0], 867, unsigned, 0, 99.5, 99, 100)])
    got = S.outright_imbalance(c, d, [C] * 2, S.RESIDUAL_WINDOW, S.cutoff_ns(d, S.ENTRY))
    assert bool(got.loc[d[0], "ok"]) is ok
    assert S.coverage_ok([297], [300]).tolist() == [True]  # integer test: no float rounding at the edge


def test_endpoints_need_one_contract_and_never_carry_across_days():
    df = bars(n_days=3)
    d = days_of(df)
    roll = df.copy()
    roll.loc[(roll["trading_day"] == d[0]) & (roll["mod"] == 874), "contract"] = "CLJ5@2015-03"
    assert np.isnan(S.bar_return(roll, d).loc[d[0], "r"]) and np.isfinite(S.bar_return(roll, d).loc[d[1], "r"])
    bz = df[~((df["trading_day"] == d[1]) & (df["mod"] <= 865))]  # day 2 has no start price of its own
    got = S.bz_return(bz, d)
    assert np.isfinite(got.loc[d[0], "r"]) and np.isnan(got.loc[d[1], "r"])  # nothing borrowed from day 1


def with_digest(frame, tag):
    frame = frame.copy()
    frame.attrs["data_sha256"] = tag * 64
    return frame


def stage1_env(tmp_path, monkeypatch):
    """Point every output of run_stage1 at tmp_path and feed it synthetic data."""
    from propfirm_research import ledger, paths
    sign = lambda k: 1 if (k * 5) % 3 else -1  # noqa: E731
    df = with_digest(bars(plant=lambda k: 30.0 * sign(k)), "a")
    t, c = daily_flow(df, sign)
    rel = {k: with_digest(v, "c") for k, v in related(df, 30).items()}
    monkeypatch.setattr(paths, "LEDGER_FILE", tmp_path / "LEDGER.csv")
    monkeypatch.setattr(paths, "OUT_DIR", tmp_path / "out")
    monkeypatch.setattr(paths, "ROOT", tmp_path)
    monkeypatch.setattr(S, "CARD_DIRS", {"H027": tmp_path / "H027", "H028": tmp_path / "H028"})
    monkeypatch.setattr(S, "s004_accepted", lambda: {"all_ok": True})
    monkeypatch.setattr(S.data, "load_front", lambda *a, **k: df)
    monkeypatch.setattr(S.data, "load_trades", lambda source, *a, **k: with_digest(t if source == "tas" else c, "b"))
    monkeypatch.setattr(S.data, "load_related", lambda symbol, *a, **k: rel[symbol])
    orig = S.grid.windows
    monkeypatch.setattr(S.grid, "windows", lambda d, specs, days=None, expiry_tmin=None:
                        orig(d, specs, days=days, expiry_tmin=EXP))
    return ledger


@pytest.mark.parametrize("item, n_tests", [("H027", 4), ("H028", 3)])
def test_run_stage1_writes_one_row_once_and_finalises_outputs(tmp_path, monkeypatch, item, n_tests):
    ledger = stage1_env(tmp_path, monkeypatch)
    S.run_stage1(item)
    rows = ledger.read()
    ex = rows[rows["kind"] == "exploratory"]
    assert len(ex) == 1 and ex["item_id"].iloc[0] == item and ex["n_tests"].iloc[0] == str(n_tests)
    out = tmp_path / ex["output"].iloc[0]
    manifest = json.loads((out / "manifest.json").read_text())
    assert out.is_dir() and not out.name.endswith(".partial") and len(manifest["inputs_sha256"]) == 3 - (item == "H028")
    assert ex["data_sha256"].iloc[0] == manifest["data_sha256"] != manifest["data"]["sha256_all_columns"]
    tab = pd.read_csv(tmp_path / item / "explore.csv")
    assert len(tab) == n_tests and "sign_ok" not in tab and not tab["promote"].any()
    with pytest.raises(FileExistsError):
        S.run_stage1(item)
    assert len(ledger.read()) == len(rows)


def test_run_stage1_failure_before_commit_sets_outputs_aside(tmp_path, monkeypatch):
    ledger = stage1_env(tmp_path, monkeypatch)
    real = ledger.append

    def append(item, kind, period, **f):
        if f.get("verdict") == "EXPLORATORY":
            raise OSError("disk full")
        return real(item, kind, period, **f)

    monkeypatch.setattr(S.ledger, "append", append)
    with pytest.raises(OSError):
        S.run_stage1("H027")
    rows = ledger.read()
    assert rows["verdict"].tolist() == ["FAILED"] and rows["item_id"].tolist() == ["H027"]
    assert not (tmp_path / "H027" / "explore.csv").exists()
    names = sorted(p.name for p in (tmp_path / "out" / "settlement").iterdir())
    assert len(names) == 1 and names[0].endswith(".failed")


def test_s004_acceptance_must_be_about_the_files_the_run_reads(tmp_path, monkeypatch):
    facts = tmp_path / "facts.json"
    monkeypatch.setattr(S, "S004_FACTS", facts)
    monkeypatch.setattr(S.data, "digest", lambda table, period: "same")
    ok = {"facts": {"acceptance": {"all_ok": True}, "data_sha256": {t: "same" for t in S.AUDITED_TABLES}}}
    facts.write_text(json.dumps(ok))
    assert S.s004_accepted()["all_ok"]
    stale = json.loads(json.dumps(ok))
    stale["facts"]["data_sha256"]["cl_mbp1"] = "older"
    facts.write_text(json.dumps(stale))
    with pytest.raises(RuntimeError, match="cl_mbp1"):
        S.s004_accepted()


# --- R018 follow-ups --------------------------------------------------------------------------------------

def test_tas_session_ends_at_the_1430_close():
    d = days_of(bars(n_days=2))
    t = tas([(d[0], 869, 59, "CLTH5", 5, 1, 7),          # 14:29:59: inside the session
             (d[0], 870, 0, "CLTH5", 40, 1, 7),          # 14:30:00: after the close, even though known by 14:35
             (d[0], 19 * 60, 0, "CLTH5", 3, -1, 7)])     # 19:00 the evening before: the session's start
    got = S.tas_imbalance(t, d, [C] * 2, S.cutoff_ns(d, S.ENTRY))
    assert got.loc[d[0], "imb"] == 2 and got.loc[d[0], "volume"] == 8


def test_v2_uses_the_1431_cutoff_and_v1_the_1435_cutoff():
    d = days_of(bars(n_days=2))
    t = tas([(d[0], 600, 0, "CLTH5", 10, 1, 7), (d[0], 869, 59, "CLTH5", 4, 1, 7, 61)])  # known at 14:31:00
    v2 = S.tas_imbalance(t, d, [C] * 2, S.cutoff_ns(d, S.UNWIND_ENTRY))
    v1 = S.tas_imbalance(t, d, [C] * 2, S.cutoff_ns(d, S.ENTRY))
    assert v2.loc[d[0], "imb"] == 10 and v1.loc[d[0], "imb"] == 14


@pytest.mark.parametrize("window, cutoff_mod, mod, delay, counted", [  # trade events are at second 10
    (S.RESIDUAL_WINDOW, S.ENTRY, 870, 280, True),        # in the v3 window, known 14:34:50
    (S.RESIDUAL_WINDOW, S.ENTRY, 870, 290, False),       # known exactly 14:35:00: not before the decision
    (S.RESIDUAL_WINDOW, S.ENTRY, 870, 300, False),       # known 14:35:10: a late report
    (S.UNWIND_WINDOW, S.UNWIND_ENTRY, 865, 340, True),   # in the v4 window, known 14:30:50
    (S.UNWIND_WINDOW, S.UNWIND_ENTRY, 865, 360, False),  # known 14:31:10
])
def test_late_received_window_trades_are_excluded(window, cutoff_mod, mod, delay, counted):
    d = days_of(bars(n_days=2))
    c = pd.concat([cl_trades([(d[0], window[0], 10, 1, 100, 99, 100)]),
                   cl_trades([(d[0], mod, 7, 1, 100, 99, 100)], delay_s=delay)])
    got = S.outright_imbalance(c, d, [C] * 2, window, S.cutoff_ns(d, cutoff_mod))
    assert got.loc[d[0], "imb"] == (17 if counted else 10)


UP, DOWN = 40, 45  # controlled days: the related markets jump while CL stays flat over 14:25-14:34


def controlled_markets(n_days=60):
    """CL and RB / HO / BZ random walks; on day UP every related market rises 2% from the 14:25 open to the 14:34
    close and on day DOWN it falls 2%, while CL's 14:34 close equals its 14:25 open. 2% is about 16 typical sds."""
    df = bars(n_days=n_days, seed=7)
    rel = related(df, 50)
    d = days_of(df)
    for frame, move in [(rel["RB.v.0"], 0.02), (rel["HO.v.0"], 0.02), (rel["BZ.v.0"], 0.02), (df, 0.0)]:
        for k, sign in ((UP, 1), (DOWN, -1)):
            day = frame["trading_day"] == d[k]
            p0 = frame.loc[day & (frame["mod"] == 865), "open"].iloc[0]
            frame.loc[day & (frame["mod"] == 874), "close"] = p0 * np.exp(sign * move)
    return df, rel, d


def test_h028_directions_from_first_principles():
    df, rel, d = controlled_markets()
    var, _ = S.h028(df, d, rel, expiry_tmin=EXP)
    for name in ("v1_products", "v2_brent", "v3_agreement"):
        assert var[name]["dir"][UP] == 1.0, name    # related markets rose more than CL: buy CL
        assert var[name]["dir"][DOWN] == -1.0, name  # they fell: sell CL


@pytest.mark.parametrize("missing, stays", [("RB.v.0", {"v2_brent"}), ("HO.v.0", {"v2_brent"}),
                                            ("BZ.v.0", {"v1_products"})])
def test_missing_related_market_removes_only_its_variants(missing, stays):
    df, rel, d = controlled_markets()
    full, _ = S.h028(df, d, rel, expiry_tmin=EXP)
    names = ("v1_products", "v2_brent", "v3_agreement")
    assert all(full[n]["emitted"][UP] for n in names)  # every variant fires on the controlled day first
    rel[missing] = rel[missing][rel[missing]["trading_day"] != d[UP]]
    var, _ = S.h028(df, d, rel, expiry_tmin=EXP)
    assert {n for n in names if var[n]["emitted"][UP]} == stays


D15 = [16450 + i for i in range(60)]  # 60 days in 2015
D16 = [16900 + i for i in range(60)]  # 60 days in 2016


def screen(values, days=None, **patch):
    days = D15 + D16 if days is None else days
    return S.stage1_table(screen_variants(values, days), 2.0, 500, ["v1"]).iloc[0]


CLEAN = [20.0, 21.0] * 60  # 60 trades a year, small noise: passes every condition


def test_screen_passes_a_clean_case_and_never_promotes():
    row = screen(CLEAN)
    assert row["stage1_pass"] and not row["promote"]


@pytest.mark.parametrize("values, failing", [
    ([4.0, 4.8] * 60, "stress_ok"),                  # mean 4.40: not above the 4.402-tick stress cost
    ([50.0, -30.0] * 60, "power_ok"),                # mean 10, sd 40: net 7.6 < 2 x MDE 14.7
    ([20.0, 21.0] * 30 + [0.0] * 60, "years_ok"),    # 2016 gross exactly 0
])
def test_screen_isolated_failures(values, failing):
    row = screen(values)
    assert not row[failing] and not row["stage1_pass"]
    others = [c for c in ("q_ok", "years_ok", "trades_ok", "stress_ok", "power_ok", "day_share_ok") if c != failing]
    assert all(row[c] for c in others), {c: row[c] for c in others}


def test_screen_stress_cost_is_a_strict_bound():
    assert not screen([4.0, 4.8] * 60)["stress_ok"] and screen([4.0, 4.82] * 60)["stress_ok"]


def test_screen_day_share_boundary():
    # one day carrying a quarter of the gross also fails power; the conjunct itself is tested here
    exact = screen([20.0] * 119 + [2380.0 / 3])
    above = screen([20.0] * 119 + [800.0])
    assert exact["max_day_share"] == pytest.approx(0.25) and exact["day_share_ok"]
    assert above["max_day_share"] > 0.25 and not above["day_share_ok"] and not above["stage1_pass"]


def test_screen_trades_per_year_boundary():
    ok = screen([20.0, 21.0] * 25, days=D15[:25] + D16[:25])     # exactly 25 a year
    short = screen([20.0, 21.0] * 24 + [20.0], days=D15[:25] + D16[:24])  # 24.5 a year
    assert ok["trades_ok"] and not short["trades_ok"]


def test_screen_q_and_inconclusive_slots_fail(monkeypatch):
    monkeypatch.setattr(S, "bh_qvalues", lambda p: np.full(len(p), 0.2))
    row = screen(CLEAN)
    assert not row["q_ok"] and not row["stage1_pass"]
    monkeypatch.undo()
    two = screen_variants([20.0, 21.0], [16450, 16900])  # fewer than 3 trades: inconclusive, p = 1
    row = S.stage1_table(two, 2.0, 500, ["v1"]).iloc[0]
    assert row["inconclusive"] and not row["stage1_pass"]


CARD_SCREEN = ("q_ok", "years_ok", "trades_ok", "stress_ok", "power_ok", "day_share_ok")  # card section 4, by hand


def test_screen_conjunction_truth_table():
    assert sorted(S.SCREEN) == sorted(CARD_SCREEN)  # the code may not drop or add a condition of the card
    base = {"in_family": True, "inconclusive": False, **{c: True for c in CARD_SCREEN}}
    assert bool(S.screen_pass(pd.DataFrame([base])).iloc[0])
    for flip in ["in_family", "inconclusive", *CARD_SCREEN]:
        row = {**base, flip: not base[flip]}
        assert not bool(S.screen_pass(pd.DataFrame([row])).iloc[0]), flip  # each condition alone blocks a pass


def test_attempt_claim_is_atomic_and_never_released(tmp_path, monkeypatch):
    monkeypatch.setattr(S, "CARD_DIRS", {"H027": tmp_path / "H027"})
    S.claim_attempt("H027")
    with pytest.raises(FileExistsError):
        S.claim_attempt("H027")


def test_failed_attempt_blocks_every_rerun(tmp_path, monkeypatch):
    ledger = stage1_env(tmp_path, monkeypatch)
    real = ledger.append

    def append(item, kind, period, **f):
        if f.get("verdict") == "EXPLORATORY":
            raise OSError("disk full")
        return real(item, kind, period, **f)

    monkeypatch.setattr(S.ledger, "append", append)
    with pytest.raises(OSError):
        S.run_stage1("H027")
    marker = json.loads((tmp_path / "H027" / S.ATTEMPT_MARKER).read_text())
    assert marker["status"] == "FAILED"
    monkeypatch.setattr(S.ledger, "append", real)
    with pytest.raises(FileExistsError):  # results were computed once: never again
        S.run_stage1("H027")


def test_failure_in_the_first_data_read_still_closes_the_attempt(tmp_path, monkeypatch):
    ledger = stage1_env(tmp_path, monkeypatch)
    monkeypatch.setattr(S.data, "load_front", lambda *a, **k: (_ for _ in ()).throw(OSError("bars unreadable")))
    with pytest.raises(OSError):
        S.run_stage1("H028")
    assert json.loads((tmp_path / "H028" / S.ATTEMPT_MARKER).read_text())["status"] == "FAILED"
    assert ledger.read()["verdict"].tolist() == ["FAILED"]
    with pytest.raises(FileExistsError):
        S.run_stage1("H028")


def test_marker_is_closed_even_when_the_failed_row_cannot_be_written(tmp_path, monkeypatch):
    stage1_env(tmp_path, monkeypatch)
    monkeypatch.setattr(S.data, "load_front", lambda *a, **k: (_ for _ in ()).throw(OSError("bars unreadable")))
    monkeypatch.setattr(S, "_mark_failed", lambda *a, **k: (_ for _ in ()).throw(OSError("ledger unwritable")))
    with pytest.raises(OSError, match="bars unreadable") as e:  # the original error, not the clean-up error
        S.run_stage1("H027")
    assert any("ledger unwritable" in n for n in e.value.__notes__)
    marker = json.loads((tmp_path / "H027" / S.ATTEMPT_MARKER).read_text())
    assert marker["status"] == "FAILED" and "ledger unwritable" in marker["problems"][0]


def test_original_error_survives_a_failed_marker_close_and_reruns_stay_blocked(tmp_path, monkeypatch):
    stage1_env(tmp_path, monkeypatch)
    monkeypatch.setattr(S.data, "load_front", lambda *a, **k: (_ for _ in ()).throw(OSError("bars unreadable")))
    monkeypatch.setattr(S, "_close_attempt", lambda *a, **k: (_ for _ in ()).throw(OSError("marker unwritable")))
    with pytest.raises(OSError, match="bars unreadable") as e:
        S.run_stage1("H028")
    assert any("marker unwritable" in n for n in e.value.__notes__)
    monkeypatch.undo()
    stage1_env(tmp_path, monkeypatch)
    with pytest.raises(FileExistsError):  # the claimed marker blocks a rerun even without a status
        S.run_stage1("H028")


def test_refused_audit_does_not_spend_the_attempt(tmp_path, monkeypatch):
    stage1_env(tmp_path, monkeypatch)
    monkeypatch.setattr(S, "s004_accepted", lambda: (_ for _ in ()).throw(RuntimeError("S004 not accepted")))
    with pytest.raises(RuntimeError):
        S.run_stage1("H028")
    assert not (tmp_path / "H028" / S.ATTEMPT_MARKER).exists()


def test_h025_overlap_uses_entry_time_masks(monkeypatch):
    sign = lambda k: 1 if k % 2 else -1  # noqa: E731
    df = bars()
    t, c = daily_flow(df, sign)
    d = days_of(df)
    var, _ = S.h027(df, d, t, c, expiry_tmin=EXP)
    orig = S.grid.windows
    monkeypatch.setattr(S.grid, "windows", lambda dd, specs, days=None, expiry_tmin=None:
                        orig(dd, specs, days=days, expiry_tmin=EXP))
    v = var["v1_tas_residual"]
    before = S.h025_overlap(df, d, {"v1": v})["v1"]
    no_exits = {**v, "dir": np.zeros_like(v["dir"])}  # as if every exit bar were missing
    assert np.isfinite(before) and S.h025_overlap(df, d, {"v1": no_exits})["v1"] == before


def test_both_cleanups_failing_still_leave_a_failed_marker_and_the_original_error(tmp_path, monkeypatch):
    stage1_env(tmp_path, monkeypatch)
    monkeypatch.setattr(S.data, "load_front", lambda *a, **k: (_ for _ in ()).throw(OSError("bars unreadable")))
    monkeypatch.setattr(S, "_mark_failed", lambda *a, **k: (_ for _ in ()).throw(KeyboardInterrupt()))
    monkeypatch.setattr(S, "_close_attempt", lambda *a, **k: (_ for _ in ()).throw(OSError("marker unwritable")))
    with pytest.raises(OSError, match="bars unreadable") as e:
        S.run_stage1("H027")
    assert any("KeyboardInterrupt" in n for n in e.value.__notes__)
    marker = json.loads((tmp_path / "H027" / S.ATTEMPT_MARKER).read_text())
    assert marker["status"] == "FAILED" and len(marker["problems"]) == 2


def test_a_successful_run_survives_a_failed_done_marker_close(tmp_path, monkeypatch):
    ledger = stage1_env(tmp_path, monkeypatch)
    monkeypatch.setattr(S, "_close_attempt", lambda *a, **k: (_ for _ in ()).throw(OSError("marker unwritable")))
    S.run_stage1("H028")  # committed results are not reported as a failure
    assert ledger.read()["verdict"].tolist() == ["EXPLORATORY"]
    marker = json.loads((tmp_path / "H028" / S.ATTEMPT_MARKER).read_text())
    assert marker["status"] == "DONE" and "marker unwritable" in marker["problems"][0]
    monkeypatch.undo()
    stage1_env(tmp_path, monkeypatch)
    with pytest.raises(FileExistsError):
        S.run_stage1("H028")
