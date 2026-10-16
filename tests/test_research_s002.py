"""S002 atlas helpers (synthetic data only)."""

import numpy as np
import pandas as pd
import pytest

from propfirm_research.stats import variance_ratio, variance_ratio_days
from propfirm_research.studies import s002_atlas as S
from tests.test_research_combine_grid import EXP, minutes


def epoch_day(date: str) -> int:
    return int((pd.Timestamp(date) - pd.Timestamp("1970-01-01")).days)


def atlas(df, df2=None, eia=()):
    return S.Atlas(df, df if df2 is None else df2, np.array(eia, dtype=np.int64),
                   pd.DataFrame({"day": [], "minute_et": []}))


@pytest.fixture
def known_expiry(monkeypatch):
    far = {**EXP, "CLK6@2016-04": 10**9 + 1}
    monkeypatch.setattr(S.grid.E, "contract_expiry", lambda keys: np.array([far.get(k, 10**9) for k in keys]))
    monkeypatch.setattr(S.E, "contract_expiry", lambda keys: np.array([far.get(k, 10**9) for k in keys]))


def test_eia_split_normal_wednesdays_and_holiday_candidates(monkeypatch):
    rel = pd.DataFrame({"date": pd.to_datetime(["2016-03-09", "2016-05-31", "2016-06-01", "2016-06-02"]),
                        "time_et": ["10:30", "10:30", "11:00", "11:00"], "minute_et": [630, 630, 660, 660]})
    monkeypatch.setattr(S.eia_calendar, "load_releases", lambda: rel)
    days = np.array([epoch_day(d) for d in ("2016-03-09", "2016-05-31", "2016-06-01", "2016-06-02")])
    normal, shifted = S.eia_calendar_split(days)
    assert list(normal) == [epoch_day("2016-03-09")]
    assert len(shifted) == 3 and set(shifted["minute_et"]) == {630, 660}


def test_week_number_starts_on_sunday():
    d = np.array([epoch_day(x) for x in ("2016-03-05", "2016-03-06", "2016-03-12")])  # Sat, Sun, Sat
    w = S.sunday_week(d)
    assert w[0] != w[1] and w[1] == w[2]


def test_predict_sign_rule_edge_and_ic():
    rng = np.random.default_rng(0)
    days = np.arange(18000, 18400)
    x = pd.Series(rng.normal(0, 10, len(days)), index=days)
    at = S.Atlas.__new__(S.Atlas)
    at.tests = []
    r = at.predict("perfect", x, pd.Series(np.sign(x) * 5.0, index=days))
    assert r["gross_sign_edge_ticks"] == pytest.approx(5.0) and r["sign_ic"] == pytest.approx(1.0)
    assert len(at.tests) == 2 and r["key_edge"] == "segment|perfect sign edge"
    r0 = at.predict("unrelated", x, pd.Series(rng.normal(0, 10, len(days)), index=days))
    assert abs(r0["sign_ic"]) < 0.15


def test_minute_returns_break_at_missing_minute_contract_and_day():
    df = minutes()
    df = df.drop(index=10).reset_index(drop=True)  # one missing minute
    r = S.minute_returns(df)
    assert np.isnan(r[0]) and np.isnan(r[10]) and np.nanmax(np.abs(r - 1)) == 0
    two = pd.concat([minutes(day="2016-03-08", end="16:20"), minutes(day="2016-03-09")], ignore_index=True)
    r2 = S.minute_returns(two)
    first_of_day2 = int((two["trading_day"] == two["trading_day"].iloc[-1]).to_numpy().argmax())
    assert np.isnan(r2[first_of_day2])


def test_segments_and_term_structure_on_synthetic_day(known_expiry):
    df = minutes()  # open = close = 5000 + i: +1 tick per minute
    df2 = minutes(contract="CLK6@2016-04")
    df2[["open", "high", "low", "close"]] += 30.0
    at = atlas(df, df2)
    assert at.seg(9 * 60, 10 * 60).iloc[0] == 60
    slope, k1, _ = at.term_structure_0900()
    assert slope[0] == 30 and k1[0] == "CLJ6@2016-03"
    early = minutes(start="08:00")
    stale = minutes(contract="CLK6@2016-04", start="08:00")
    stale = stale[stale["mod"] < 8 * 60 + 40].reset_index(drop=True)  # second month last traded 08:39
    front = early[early["mod"] >= 8 * 60 + 45].reset_index(drop=True)  # front only from 08:45: no common minute <= 10 min old
    s2, _, _ = atlas(front, stale).term_structure_0900()
    assert np.isnan(s2[0])


def test_term_structure_needs_later_second_expiry(monkeypatch):
    df = minutes()
    df2 = minutes(contract="CLK6@2016-04")
    monkeypatch.setattr(S.E, "contract_expiry", lambda keys: np.array([5 if "K6" in k else 10 for k in keys]))
    slope, _, _ = atlas(df, df2).term_structure_0900()
    assert np.isnan(slope[0])


def test_next_day_shift_pairs_day_t_with_t_plus_1(known_expiry):
    full = pd.concat([minutes(day="2016-03-08", start="08:55", end="16:20"),
                      minutes(day="2016-03-08", start="18:00", end="23:59"),
                      minutes(day="2016-03-09", start="00:00", end="16:20")], ignore_index=True)
    from propfirm_research.periods import trading_day
    full["trading_day"] = trading_day(full["ts_event_utc"])
    at = atlas(full)
    nxt = at.seg(18 * 60, 9 * 60).shift(-1)
    d8, d9 = epoch_day("2016-03-08"), epoch_day("2016-03-09")
    assert list(at.days) == [d8, d9]
    assert np.isnan(at.seg(18 * 60, 9 * 60)[d8]) and not np.isnan(nxt[d8])  # day 8's next overnight = 9's


def test_settlement_event_is_two_minutes():
    assert dict((n, length) for n, _, length, _ in S.EVENTS)["settlement 14:28-14:30"] == 2


def test_attach_q_replaces_keys():
    t = pd.DataFrame({"a": [1, 2], "key_mean": ["x", "y"]})
    out = S.attach_q(t, {"x": 0.01, "y": 0.5})
    assert list(out.columns) == ["a", "q_mean"] and list(out["q_mean"]) == [0.01, 0.5]


def test_variance_ratio_rejects_ar1_and_keeps_size():
    rng = np.random.default_rng(3)
    e = rng.normal(size=20000)
    r = e.copy()
    for i in range(1, len(r)):
        r[i] = 0.1 * r[i - 1] + e[i]
    assert variance_ratio(r, 5)["z"] > 8  # R007 #1: z was ~0.09 before the fix
    day = np.repeat(np.arange(100), 200)
    assert variance_ratio_days(r, day, 5)["z"] > 8
    z0 = [variance_ratio_days(rng.normal(size=20000), day, 5, seed=k)["z"] for k in range(20)]
    assert np.mean(np.abs(np.array(z0)) > 1.96) < 0.25  # roughly 5% size under the null


def test_variance_ratio_days_never_crosses_a_day():
    r = np.array([1.0, 1.0, 1.0, -1.0, -1.0, -1.0])
    day = np.array([0, 0, 0, 1, 1, 1])
    v = variance_ratio_days(r, day, 2, n_boot=20)
    assert v["q_sums"] == 4  # (1,1),(1,1),(-1,-1),(-1,-1): no sum spans the day change


def test_roll_week_label():
    got = S.roll_week_label(np.array([np.nan, -1.0, 0.0, 6.9, 7.0, 20.0]))
    assert list(got) == [None, "no", "yes", "yes", "no", "no"]


def test_filled_minutes_repeat_close_over_gaps():
    df = minutes().drop(index=[10, 11]).reset_index(drop=True)  # 2 minutes with no trade
    fm = S.filled_minutes(df)
    assert len(fm) == len(minutes())  # grid restored
    assert fm["r"].iloc[10] == 0 and fm["r"].iloc[11] == 0 and fm["r"].iloc[12] == 3  # price catches up at once
    assert fm["mod"].iloc[0] == 8 * 60 + 55


def test_t_pvalue_and_corr_p():
    from propfirm_research.stats import t_pvalue
    assert t_pvalue(2.0, 10) == pytest.approx(0.0734, abs=2e-4)
    assert t_pvalue(1.96, 200) == pytest.approx(0.0514, abs=3e-4)  # not the normal 0.0500
    assert np.isnan(t_pvalue(float("nan"), 10)) and np.isnan(t_pvalue(1.0, 0))
    rng = np.random.default_rng(1)
    x = rng.normal(size=500)
    r, p, n = S.corr_p(x, x + rng.normal(size=500))
    assert n == 500 and 0.6 < r < 0.8 and p < 1e-10
    assert np.isnan(S.corr_p(x[:5], x[:5])[0])


def test_variance_ratio_days_validates_input():
    with pytest.raises(ValueError):
        variance_ratio_days(np.ones(5), np.zeros(4), 2)
    with pytest.raises(ValueError):
        variance_ratio_days(np.ones(5), np.zeros(5), 1)
    assert np.isnan(variance_ratio_days(np.zeros(50), np.zeros(50), 5, n_boot=5)["vr"])  # zero variance
