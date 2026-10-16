"""propfirm_research: periods, ledger, prereg + firewall, costs, stats, index. Synthetic data only."""

import json
import re
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from propfirm_research import costs, data, index, ledger, paths, periods, prereg, stats

PKG = Path(__file__).resolve().parent.parent / "propfirm_research"


@pytest.fixture(autouse=True)
def tmp_ledger(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "LEDGER_FILE", tmp_path / "LEDGER.csv")
    monkeypatch.setattr(prereg, "_LIVE", {})
    return tmp_path


def utc(s):
    return pd.Series(pd.to_datetime([s], utc=True))


# --- periods ----------------------------------------------------------------------------------

def test_trading_day_starts_at_18_et_both_dst_regimes():
    d = periods.epoch_day
    from datetime import date
    # winter (EST, UTC-5): 17:59 ET = 22:59 UTC same date; 18:00 ET = 23:00 UTC -> next day
    assert periods.trading_day(utc("2016-01-12 22:59"))[0] == d(date(2016, 1, 12))
    assert periods.trading_day(utc("2016-01-12 23:00"))[0] == d(date(2016, 1, 13))
    # summer (EDT, UTC-4): 18:00 ET = 22:00 UTC
    assert periods.trading_day(utc("2016-07-12 21:59"))[0] == d(date(2016, 7, 12))
    assert periods.trading_day(utc("2016-07-12 22:00"))[0] == d(date(2016, 7, 13))


def test_period_boundaries():
    from datetime import date
    d = periods.epoch_day
    assert periods.period_of(d(date(2016, 12, 31))) == "discovery"
    assert periods.period_of(d(date(2017, 1, 1))) == "validation"
    assert periods.period_of(d(date(2021, 12, 31))) == "validation"
    assert periods.period_of(d(date(2022, 1, 1))) == "holdout"
    assert periods.period_of(d(date(2010, 1, 1))) == "before"


# --- ledger -----------------------------------------------------------------------------------

def test_ledger_append_ids_and_guards():
    assert ledger.append("S001", "descriptive", "discovery", n_tests=3) == "S001-001"
    assert ledger.append("S001", "descriptive", "discovery") == "S001-002"
    with pytest.raises(ledger.LedgerError):
        ledger.append("H001", "validation", "validation")  # no prereg hash
    with pytest.raises(ledger.LedgerError):
        ledger.append("H001", "bogus", "discovery")
    with pytest.raises(ledger.LedgerError):
        ledger.append("H001", "descriptive", "discovery", typo_field=1)
    rows = ledger.read()
    assert list(rows.columns) == ledger.COLUMNS and len(rows) == 2


# --- prereg + firewall ------------------------------------------------------------------------

def spec(period="validation", item_id="H999", **kw):
    s = {"item_id": item_id, "claim": "c", "period": period, "null": "N2", "test": "combined",
         "alpha_one_sided": 0.01, "family": ["v1"], "multiplicity": "single", "signal": "s", "entry": "e",
         "exit": "x", "fee_usd": 4.02, "slip_ticks": 1.0, "stress_slip_ticks": 2.0, "contracts": 1,
         "min_signals": 100, "power_mde": 1.4, "seed": 1, "codex_review": "R999",
         "stopping_rule": prereg.STOPPING_RULE}
    s.update(kw)
    return s


def reg(tmp, item_id="H999", **kw):
    f = tmp / "code.py"
    f.write_text("x = 1")
    return prereg.register(tmp / f"{item_id}-test", spec(item_id=item_id, **kw), [f], [f])


def fake_bars():
    ts = pd.date_range("2016-12-29 14:00", "2017-01-04 14:00", freq="6h", tz="UTC")
    n = len(ts)
    return pd.DataFrame({"ts_event_utc": ts, "continuous_symbol": "CL.v.0", "raw_symbol": "CLG7",
                         "expiration": pd.Timestamp("2017-01-20", tz="UTC"),
                         "open_ticks": np.arange(n) + 5000, "high_ticks": np.arange(n) + 5001,
                         "low_ticks": np.arange(n) + 4999, "close_ticks": np.arange(n) + 5000,
                         "volume": 10.0})


def test_firewall(tmp_ledger, monkeypatch):
    monkeypatch.setattr(data, "_read", lambda *a: fake_bars())
    disc = data.load_front("discovery", "S999", "test")
    assert disc["trading_day"].max() <= periods.bounds("discovery")[1]  # nothing after 2016-12-31
    with pytest.raises(data.FirewallError):
        data.load_front("validation", "H999", "test")
    p = reg(tmp_ledger)
    with prereg.open_run(p) as run:
        val = data.load_front("validation", "H999", "test", run=run)
        assert val["trading_day"].min() >= periods.bounds("validation")[0]
        with pytest.raises(data.FirewallError):
            data.load_front("validation", "H001", "borrowed token", run=run)  # wrong item
        with pytest.raises(data.FirewallError):
            data.load_front("holdout", "H999", "wrong period", run=run)
    with pytest.raises(data.FirewallError):
        data.load_front("validation", "H999", "after close", run=run)  # revoked
    forged = prereg.RunToken("H999", "validation", run.prereg_sha256, "x", True)
    with pytest.raises(data.FirewallError):
        data.load_front("validation", "H999", "forged", run=forged)
    with pytest.raises(prereg.PreregError):
        with prereg.open_run(p):
            pass  # one run, never re-run
    rows = ledger.read()
    assert rows["kind"].tolist().count("prereg") == 1
    assert rows["note"].str.startswith("intent").sum() == rows["note"].str.startswith("done").sum() == 2


def test_warmup_reaches_back_never_forward(tmp_ledger, monkeypatch):
    monkeypatch.setattr(data, "_read", lambda *a: fake_bars())
    with prereg.open_run(reg(tmp_ledger)) as run:
        v = data.load_front("validation", "H999", "t", run=run, warmup_days=3)
    assert v["trading_day"].min() < periods.bounds("validation")[0]
    with pytest.raises(data.FirewallError):
        data.load_front("discovery", "S999", "t", warmup_days=-5)


def test_edited_prereg_refused(tmp_ledger):
    p = reg(tmp_ledger)
    s = json.loads(p.read_text())
    s["seed"] = 2
    p.write_text(json.dumps(s))
    with pytest.raises(prereg.PreregError):
        with prereg.open_run(p):
            pass


@pytest.mark.parametrize("bad", [dict(alpha_one_sided=0.05), dict(null="N9"), dict(stopping_rule="maybe"),
                                 dict(family=["a", "b"]), dict(family=["a"] * 5), dict(contracts=0),
                                 dict(codex_review="none"), dict(period="discovery")])
def test_invalid_prereg_refused(tmp_ledger, bad):
    with pytest.raises(prereg.PreregError):
        reg(tmp_ledger, **bad)


def test_prereg_needs_hashes_and_matching_folder(tmp_ledger):
    with pytest.raises(prereg.PreregError):
        prereg.register(tmp_ledger / "H999-x", spec(), [], [])
    f = tmp_ledger / "c.py"
    f.write_text("1")
    with pytest.raises(prereg.PreregError):
        prereg.register(tmp_ledger / "H123-x", spec(), [f], [f])


def test_holdout_needs_owner_approval(tmp_ledger):
    with pytest.raises(prereg.PreregError):
        reg(tmp_ledger, period="holdout")
    p = reg(tmp_ledger, item_id="H998", period="holdout", approved_by_user=True)
    with prereg.open_run(p) as run:
        assert prereg.is_live(run) and run.period == "holdout"


def test_no_bar_reads_outside_data_module():
    pat = re.compile(r"read_parquet|load_bars|load_minutes|BARS_DIR")
    offenders = [f.name for f in PKG.rglob("*.py") if f.name != "data.py" and pat.search(f.read_text())]
    assert offenders == []


# --- costs, stats, index ----------------------------------------------------------------------

def test_costs():
    assert costs.BASE_USD == pytest.approx(24.02)
    assert costs.STRESS_USD == pytest.approx(44.02)
    assert costs.round_trip_usd(3, 1) == pytest.approx(72.06)


def test_clustered_mean_one_obs_per_day_matches_plain_t():
    rng = np.random.default_rng(1)
    x = rng.normal(0.3, 1, 400)
    r = stats.clustered_mean(x, np.arange(400))
    plain_se = x.std(ddof=0) / np.sqrt(400) * np.sqrt(400 / 399)
    assert r["se"] == pytest.approx(plain_se, rel=1e-9) and r["days"] == 400


def test_clustered_mean_inflates_se_for_correlated_days():
    rng = np.random.default_rng(2)
    day = np.repeat(np.arange(200), 5)
    x = np.repeat(rng.normal(0, 1, 200), 5) + rng.normal(0, 0.1, 1000)
    assert stats.clustered_mean(x, day)["se"] > 2 * x.std() / np.sqrt(1000)


def test_bh_known_values():
    q = stats.bh_qvalues([0.01, 0.04, 0.03, 0.5])
    # sorted p .01 .03 .04 .5 -> p*m/rank .04 .06 .0533 .5 -> running min from the right
    assert np.allclose(q, [0.04, 0.16 / 3, 0.16 / 3, 0.5])


def test_wilson_and_mde_and_nw():
    assert stats.wilson_upper(0, 2000) == pytest.approx(0.00135, abs=2e-4)
    assert stats.mde_annual_sharpe(1260) == pytest.approx((2.326 + 0.842) / np.sqrt(1260) * np.sqrt(252), rel=1e-3)
    x = np.random.default_rng(3).normal(size=5000)
    assert stats.newey_west_se(x, 0) == pytest.approx(x.std() / np.sqrt(5000), rel=1e-9)


def test_variance_ratio_iid_near_one_and_trend_above():
    rng = np.random.default_rng(4)
    assert abs(stats.variance_ratio(rng.normal(size=20000), 5)["z"]) < 3
    ar = np.zeros(20000)
    e = rng.normal(size=20000)
    for i in range(1, 20000):
        ar[i] = 0.3 * ar[i - 1] + e[i]
    assert stats.variance_ratio(ar, 5)["vr"] > 1.3


def test_variance_ratio_reference_vector():
    # hand computation with Lo-MacKinlay unbiased denominators
    r = np.array([1.0, -2.0, 3.0, 0.5, -1.0, 2.0])
    n, q, mu = 6, 2, r.mean()
    var1 = ((r - mu) ** 2).sum() / (n - 1)
    rq = r[1:] + r[:-1]
    varq = ((rq - q * mu) ** 2).sum() / (q * (n - q + 1) * (1 - q / n))
    assert stats.variance_ratio(r, 2)["vr"] == pytest.approx(varq / var1)
    with pytest.raises(ValueError):
        stats.variance_ratio(r, 1)


def test_index_builds_from_front_matter(tmp_path):
    (tmp_path / "decisions").mkdir()
    (tmp_path / "decisions" / "D001-x.md").write_text("---\nid: D001\ntitle: X\nstatus: decided  # c\n"
                                                       "updated: 2026-10-16\n---\nbody")
    (tmp_path / "decisions" / "_template.md").write_text("---\nid: D###\n---\n")
    out = index.build(tmp_path)
    assert "| D001 | X | decided | 2026-10-16 | [decisions/D001-x.md]" in out and "D###" not in out
