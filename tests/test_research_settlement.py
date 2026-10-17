"""propfirm_research.settlement: causal signals, trailing thresholds, the frozen H025/H026 family, the screen,
and the run's ledger / output bookkeeping (R014)."""

import json
import math

import numpy as np
import pandas as pd
import pytest

from propfirm_research import ledger, paths
from propfirm_research import settlement as S
from propfirm_research.data import utc_minutes
from propfirm_research.periods import et_minute_of_day, trading_day
from propfirm_research.stats import bh_qvalues, t_pvalue

FAR = 10**9
A, B = "CLH5@2015-02", "CLJ5@2015-03"
EXP = {A: FAR, B: FAR}


def market(n_days=90, seed=0, start="2015-01-05", fixed_move=None):
    """Synthetic 14:00-16:20 ET minutes on weekdays, one contract, random-walk prices, random volume.
    fixed_move: every day's 14:25 open -> 14:34 close move is exactly this many ticks, volume constant."""
    rng = np.random.default_rng(seed)
    frames = []
    for d in pd.bdate_range(start, periods=n_days):
        ts = pd.date_range(f"{d:%Y-%m-%d} 14:00", f"{d:%Y-%m-%d} 16:20", freq="1min",
                           tz="America/New_York").tz_convert("UTC")
        o = 5000.0 + np.cumsum(rng.integers(-3, 4, len(ts))).astype(float)
        c = o + rng.integers(-1, 2, len(ts))
        v = rng.integers(50, 500, len(ts)).astype(float)
        if fixed_move is not None:
            o[:] = 5000.0
            c[:] = 5000.0
            c[34] = 5000.0 + fixed_move  # the 14:34 bar (14:00 + 34 minutes)
            v[:] = 100.0
        frames.append(pd.DataFrame({"ts_event_utc": ts, "contract": A, "open": o, "high": np.maximum(o, c) + 2,
                                    "low": np.minimum(o, c) - 2, "close": c, "volume": v}))
    df = pd.concat(frames, ignore_index=True)
    df["trading_day"] = trading_day(df["ts_event_utc"])
    df["mod"] = et_minute_of_day(df["ts_event_utc"])
    df["tmin"] = utc_minutes(df["ts_event_utc"])
    return df


def directions(variants):
    return {k: v["dir"] for k, v in variants.items()}


def on_day(df, days, k, mods):
    return (df["trading_day"] == days[k]) & df["mod"].isin(list(mods))


def test_signals_use_only_bars_from_1425_to_1434():
    df = market()
    base, _ = S.h025_h026(df, expiry_tmin=EXP)
    rng = np.random.default_rng(9)
    for mask in (df["mod"] >= S.ENTRY, df["mod"] < S.SIG_START):
        x = df.copy()
        cols = ["open", "high", "low", "close", "volume"]
        x.loc[mask, cols] = rng.integers(1, 9999, (int(mask.sum()), len(cols))).astype(float)
        got, _ = S.h025_h026(x, expiry_tmin=EXP)
        for k in directions(base):
            assert np.array_equal(got[k]["emitted"], base[k]["emitted"]), k
            assert np.array_equal(got[k]["dir"], base[k]["dir"]), k


def test_trailing_threshold_uses_previous_eligible_days_only():
    rng = np.random.default_rng(1)
    v = rng.normal(size=200)
    e = rng.random(200) > 0.2
    thr = S.trailing_threshold(v, e)
    past = []
    for i in range(200):
        if len(past) >= S.LOOKBACK:
            assert thr[i] == pytest.approx(np.percentile(past[-S.LOOKBACK:], S.PCTL))
        else:
            assert np.isnan(thr[i])
        if e[i]:
            past.append(v[i])
    v2 = v.copy()
    v2[150] += 100.0  # today's value never moves today's threshold
    assert S.trailing_threshold(v2, e)[150] == thr[150]


def test_family_rules():
    df = market(n_days=120, seed=3)
    fam, c = S.h025_h026(df, expiry_tmin=EXP)
    d = directions(fam)
    assert np.array_equal(d["v3_union"] != 0, (d["v1_move_filter"] != 0) | (d["v2_volume_filter"] != 0))
    w26 = fam["v4_h026_short"]["w"]
    assert (d["v4_h026_short"][w26["valid"].to_numpy()] == -1).all()
    assert c["warmup_eligible"] == S.LOOKBACK  # the first 60 eligible days cannot trade
    assert (d["v1_move_filter"][:S.LOOKBACK] == 0).all() and (d["v1_move_filter"] != 0).any()
    sig = S.signals(df, np.unique(df["trading_day"]))
    for name in ("v1_move_filter", "v2_volume_filter"):  # direction always comes from the move
        traded = d[name] != 0
        assert traded.any() and np.array_equal(d[name][traded], np.sign(sig["move"].to_numpy()[traded]))


def test_ties_and_zero_moves_never_signal():
    df = market(n_days=80, seed=2, fixed_move=5)  # every move and volume equal: never strictly above
    days = np.unique(df["trading_day"])
    zero = (df["trading_day"] == days[70]) & (df["mod"] == S.SIG_END)
    df.loc[zero, "close"] = 5000.0  # a zero move on day 70
    fam, counts = S.h025_h026(df, expiry_tmin=EXP)
    for name in ("v1_move_filter", "v2_volume_filter", "v3_union"):
        assert not fam[name]["emitted"].any(), name
    ref = fam["ref_naive_continuation"]["emitted"]  # CME short days (e.g. 2015-01-19) are never eligible
    assert ref.sum() == counts["eligible"] - 1 and not ref[70]


def test_signal_failures_and_entry_timing_are_counted():
    df = market(n_days=100, seed=4)
    days = np.unique(df["trading_day"])
    short_days = S.h025_h026(df, days=days, expiry_tmin=EXP)[1]["entry_invalid_1435"]
    df.loc[0, "contract"] = B  # B appears first, so it never becomes A's successor (no roll cutoff for A)
    df.loc[on_day(df, days, 70, range(S.SIG_START, S.SIG_END + 1)), "contract"] = B  # signal in B, entry in A
    df.loc[on_day(df, days, 72, [14 * 60 + 30]), "contract"] = B  # two contracts inside the signal bars
    for k in (74, 78):  # make sure those two days have a non-zero move
        start_open = df.loc[on_day(df, days, k, [S.SIG_START]), "open"].to_numpy()
        df.loc[on_day(df, days, k, [S.SIG_END]), "close"] = start_open + 3
    late_ok = on_day(df, days, 74, range(S.ENTRY, S.ENTRY + 5))  # entry at 14:40: 5 minutes late, allowed
    late_bad = on_day(df, days, 76, range(S.ENTRY, S.ENTRY + 6))  # entry at 14:41: 6 minutes late
    interior = on_day(df, days, 78, [14 * 60 + 30])  # an interior signal minute missing is allowed
    vol78 = df.loc[on_day(df, days, 78, range(S.SIG_START, S.SIG_END + 1)) & ~interior, "volume"].sum()
    df = df[~(late_ok | late_bad | interior)].reset_index(drop=True)
    fam, c = S.h025_h026(df, days=days, expiry_tmin=EXP)
    assert c["signal_entry_contract_mismatch"] == 1 and c["signal_multi_contract"] == 1
    assert c["entry_invalid_1435"] == short_days + 1  # only the 6-minute-late entry is added
    sig = S.signals(df, days)
    assert sig["ok"].iloc[78] and sig["volume"].iloc[78] == vol78
    ref = fam["ref_naive_continuation"]["emitted"]
    assert not ref[70] and not ref[72] and not ref[76] and ref[74] and ref[78]


def test_missing_signal_or_exit_bar():
    df = market(n_days=100, seed=4)
    days = np.unique(df["trading_day"])
    k = 80
    gone = on_day(df, days, k, [S.SIG_START]) | on_day(df, days, k + 1, [16 * 60 + 5])
    fam, c = S.h025_h026(df[~gone].reset_index(drop=True), days=days, expiry_tmin=EXP)
    for name in ("v1_move_filter", "v2_volume_filter", "v3_union", "ref_naive_continuation"):
        assert fam[name]["dir"][k] == 0 and fam[name]["dir"][k + 1] == 0 and not fam[name]["emitted"][k]
    ref = fam["ref_naive_continuation"]
    assert ref["emitted"][k + 1]  # emitted at 14:35 from what was known, but its exit cannot be evaluated
    assert c["signal_invalid"] == 1 and c["signal_ends_missing"] == 1 and c["exit_missing_1435_flat"] == 1
    tab = S.family_table(fam, 1.0, len(days), set(S.FAMILY)).set_index("variant")
    assert tab.loc["ref_naive_continuation", "unevaluable"] == 1


def test_short_day_never_signals():
    df = market(n_days=60, seed=6, start="2016-10-03")  # includes Friday 2016-11-25 (12:55 ET flat)
    days = np.unique(df["trading_day"])
    k = int(np.flatnonzero(pd.to_datetime(days, unit="D") == pd.Timestamp("2016-11-25"))[0])
    fam, _ = S.h025_h026(df, expiry_tmin=EXP)
    assert not fam["ref_naive_continuation"]["emitted"][k] and not fam["v4_h026_short"]["emitted"][k]


def frame(ret, days):
    return pd.DataFrame({"trading_day": days, "valid": True, "ret_ticks": ret})


def variant(ret, days, d):
    return {"w": frame(ret, days), "dir": d, "emitted": d != 0}


def discovery_days():
    days = pd.bdate_range("2010-06-07", "2016-12-30")
    return ((days - pd.Timestamp("1970-01-01")) // pd.Timedelta(days=1)).to_numpy(np.int64)


def test_screen_promotes_only_a_large_stable_edge():
    days = discovery_days()
    noise = np.random.default_rng(5).normal(0, 22, len(days))
    years = (days[-1] - days[0] + 1) / 365.25
    one = np.ones(len(days))
    fam = {"big": variant(30 + noise, days, one), "small": variant(2 + noise, days, one),
           "early_only": variant(np.where(days < days[len(days) // 2], 30, -5) + noise, days, one),
           "short": variant(-30 + noise, days, one), "ref_x": variant(noise, days, one)}
    tab = S.family_table(fam, years, len(days), {"big", "small", "early_only", "short"}).set_index("variant")
    assert tab.loc["big", "promote"] and tab.loc["big", "power_ok"] and tab.loc["big", "stress_ok"]
    assert not tab.loc["small", "stress_ok"] and not tab.loc["small", "promote"]
    assert not tab.loc["short", "promote"] and tab.loc["short", "p_one"] > 0.99
    assert not tab.loc["early_only", "sign_ok"] and not tab.loc["early_only", "promote"]  # decay guard
    assert np.isnan(tab.loc["ref_x", "q"]) and not tab.loc["ref_x", "promote"]
    with pytest.raises(ValueError):
        bad = frame(noise, days)
        bad.loc[0, "valid"] = False
        S.evaluate(bad, one, years, len(days))


def test_untestable_member_keeps_the_family_at_four():
    days = discovery_days()
    noise = np.random.default_rng(7).normal(0, 22, len(days))
    one, two = np.ones(len(days)), np.r_[1.0, 1.0, np.zeros(len(days) - 2)]
    fam = {"a": variant(8 + noise, days, one), "b": variant(1 + noise, days, one),
           "c": variant(noise, days, one), "d": variant(noise, days, two)}  # d: 2 trades, untestable
    tab = S.family_table(fam, 6.5, len(days), set(fam)).set_index("variant")
    assert tab.loc["d", "inconclusive"] and not tab.loc["d", "promote"]
    p = tab.loc[["a", "b", "c"], "p_one"].to_numpy()
    assert np.allclose(tab.loc[["a", "b", "c"], "q"].to_numpy(), bh_qvalues(np.r_[p, 1.0])[:3])


def test_statistics_by_hand():
    days = discovery_days()[:40]
    g = np.array([10.0, -4, 6, 2, 8, -2, 4, 12, 0, 6])
    d = np.r_[np.ones(10), np.zeros(30)]
    ret = np.r_[g, np.zeros(30)]
    out = S.evaluate(frame(ret, days), d, years=2.0, n_days=40)
    mean, sd = g.mean(), g.std(ddof=1)
    t = mean / (sd / math.sqrt(10))
    assert out["gross"] == pytest.approx(mean) and out["t"] == pytest.approx(t)
    assert out["p_one"] == pytest.approx(t_pvalue(t, 9) / 2)
    daily = np.r_[g - S.BASE_TICKS, np.zeros(30)]
    assert out["sharpe_net_base_ann"] == pytest.approx(daily.mean() / daily.std(ddof=1) * math.sqrt(252))
    assert out["mde_net_validation"] == pytest.approx(S.Z_POWER * sd / math.sqrt(5 * 10 / 2.0))
    assert out["trades_per_year"] == 5.0 and out["n_2010-12"] == 10


def run_env(tmp_path, monkeypatch):
    """Redirect every output of run_h025 to tmp_path and feed it synthetic data; returns the list of reads."""
    df = market(n_days=150, seed=11)
    monkeypatch.setattr(paths, "LEDGER_FILE", tmp_path / "LEDGER.csv")
    monkeypatch.setattr(paths, "OUT_DIR", tmp_path / "out")
    monkeypatch.setattr(S, "H025_DIR", tmp_path / "H025")
    monkeypatch.setattr(S, "H026_DIR", tmp_path / "H026")
    monkeypatch.setattr(paths, "ROOT", tmp_path)
    reads = []
    monkeypatch.setattr(S.data, "load_front", lambda *a, **k: reads.append(a) or df)
    orig = S.grid.windows  # synthetic contracts: pass test expiries instead of exchange definitions
    monkeypatch.setattr(S.grid, "windows", lambda d, specs, days=None, expiry_tmin=None:
                        orig(d, specs, days=days, expiry_tmin=EXP))
    return reads


def test_run_writes_four_tests_once_and_finalises_outputs(tmp_path, monkeypatch):
    reads = run_env(tmp_path, monkeypatch)
    S.run_h025()
    rows = ledger.read()
    assert len(reads) == 1
    ex = rows[rows["kind"] == "exploratory"].set_index("item_id")
    assert ex.loc["H025", "n_tests"] == "3" and ex.loc["H026", "n_tests"] == "1"
    out = list((tmp_path / "out" / "settlement").iterdir())
    assert len(out) == 1 and not out[0].name.endswith(".partial")
    assert json.loads((out[0] / "manifest.json").read_text())["n_tests"] == {"H025": 3, "H026": 1}
    assert (tmp_path / "H025" / "explore.csv").exists() and (tmp_path / "H026" / "explore.csv").exists()
    with pytest.raises(FileExistsError):  # one run only
        S.run_h025()
    assert len(reads) == 1 and len(ledger.read()) == len(rows)


def test_failure_before_outputs_logs_failed_row(tmp_path, monkeypatch):
    run_env(tmp_path, monkeypatch)
    monkeypatch.setattr(S, "family_table", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    with pytest.raises(RuntimeError):
        S.run_h025()
    rows = ledger.read()
    assert rows["verdict"].tolist() == ["FAILED"] and "none" in rows["note"].iloc[0]
    assert not (tmp_path / "out" / "settlement").exists() or not any((tmp_path / "out" / "settlement").iterdir())


def flaky_ledger(monkeypatch, bad_item):
    real = ledger.append

    def append(item, kind, period, **f):
        if item == bad_item and f.get("verdict") == "EXPLORATORY":
            raise OSError("disk full")
        return real(item, kind, period, **f)

    monkeypatch.setattr(S.ledger, "append", append)


def settlement_dirs(tmp_path):
    return sorted(p.name for p in (tmp_path / "out" / "settlement").iterdir())


def test_failure_in_second_ledger_row_keeps_pointer_valid(tmp_path, monkeypatch):
    run_env(tmp_path, monkeypatch)
    flaky_ledger(monkeypatch, "H026")
    with pytest.raises(OSError):
        S.run_h025()
    rows = ledger.read()
    assert rows["verdict"].tolist() == ["EXPLORATORY", "FAILED"] and "H025" in rows["note"].iloc[1]
    out = tmp_path / rows["output"].iloc[0]
    assert out.is_dir() and (out / "INCOMPLETE").exists() and (out / "manifest.json").exists()
    assert (tmp_path / "H025" / "explore.csv").exists()


@pytest.mark.parametrize("where", ["first_ledger_row", "card_output"])
def test_failure_before_commit_sets_outputs_aside(tmp_path, monkeypatch, where):
    run_env(tmp_path, monkeypatch)
    if where == "first_ledger_row":
        flaky_ledger(monkeypatch, "H025")
    else:
        real = S._write_csv_atomic

        def write(path, frame):
            if "H026" in str(path):
                raise OSError("disk full")
            real(path, frame)

        monkeypatch.setattr(S, "_write_csv_atomic", write)
    with pytest.raises(OSError):
        S.run_h025()
    rows = ledger.read()
    assert rows["verdict"].tolist() == ["FAILED"] and "none" in rows["note"].iloc[0]
    names = settlement_dirs(tmp_path)
    assert len(names) == 1 and names[0].endswith(".failed")
    assert not (tmp_path / "H025" / "explore.csv").exists() and not (tmp_path / "H026" / "explore.csv").exists()



def test_failed_cleanup_still_writes_the_failed_row(tmp_path, monkeypatch):
    run_env(tmp_path, monkeypatch)
    real = S._write_csv_atomic
    broken = False

    def write(path, frame):
        nonlocal broken
        if "H026" in str(path):
            broken = True
            raise RuntimeError("card write failed")
        real(path, frame)

    monkeypatch.setattr(S, "_write_csv_atomic", write)
    real_rename = type(tmp_path).rename

    def rename(self, target):  # renames work until the card write has failed, then the clean-up breaks
        if broken:
            raise OSError("rename failed")
        return real_rename(self, target)

    monkeypatch.setattr(type(tmp_path), "rename", rename)
    with pytest.raises(RuntimeError, match="card write failed"):
        S.run_h025()
    rows = ledger.read()
    assert rows["verdict"].tolist() == ["FAILED"] and "clean-up failed" in rows["note"].iloc[0]


def test_days_must_be_increasing():
    df = market(n_days=70)
    days = np.unique(df["trading_day"])
    with pytest.raises(ValueError):
        S.h025_h026(df, days=days[::-1], expiry_tmin=EXP)
