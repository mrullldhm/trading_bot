"""S003 ceiling helpers (synthetic data only)."""

import numpy as np
import pandas as pd
import pytest

from propfirm_research.studies import s003_ceiling as S
from tests.test_research_combine_grid import EXP, minutes


@pytest.fixture
def known_expiry(monkeypatch):
    far = {**EXP, "CLK6@2016-04": 10**9 + 1}
    monkeypatch.setattr(S.grid.E, "contract_expiry", lambda keys: np.array([far.get(k, 10**9) for k in keys]))


def two_days():
    from propfirm_research.periods import trading_day
    full = pd.concat([minutes(day="2016-03-08", start="08:00", end="16:20"),
                      minutes(day="2016-03-08", start="18:00", end="23:59"),
                      minutes(day="2016-03-09", start="00:00", end="16:20")], ignore_index=True)
    full["trading_day"] = trading_day(full["ts_event_utc"])
    rng = np.random.default_rng(0)
    full["close"] = full["open"] + rng.integers(-2, 3, len(full))
    full["volume"] = rng.integers(1, 50, len(full)).astype(float)
    return full


def test_features_ignore_bars_at_or_after_the_decision_time(known_expiry):
    df = two_days()
    T = 10 * 60 + 35
    base = S.Features(df, df.assign(contract="CLK6@2016-04"), np.array([], dtype=np.int64)).at(T)
    later = df["mod"].between(T, 16 * 60 + 20) & (df["trading_day"] == df["trading_day"].max())
    scr = df.copy()
    scr.loc[later, ["open", "high", "low", "close"]] = 1.0
    scr.loc[later, "volume"] = 999.0
    got = S.Features(scr, scr.assign(contract="CLK6@2016-04"), np.array([], dtype=np.int64)).at(T)
    day2 = base.index.max()
    cols = [c for c in base.columns if c not in ("ret_prev_day", "ret_5d", "ret_20d", "range_pos_prev")]
    pd.testing.assert_series_equal(base.loc[day2, cols], got.loc[day2, cols], check_names=False)


def test_targets_cut_day_session_exits_at_flat(known_expiry):
    df = two_days()
    days = np.unique(df["trading_day"])
    t = S.targets(df, days, 14 * 60 + 35)
    assert t.loc[days[-1], 120] == t.loc[days[-1], "flat"]  # 16:35 cut to 16:05
    assert t.loc[days[-1], 30] == pytest.approx(30.0)  # open rises 1 tick per minute


def test_walk_forward_never_trains_on_the_test_year(monkeypatch):
    log = []

    class Spy:
        def __init__(self, *a, **k):
            pass

        def fit(self, X, y):
            log.append(("fit", X[:, 0].max()))
            return self

        def predict(self, X):
            log.append(("predict", X[:, 0].min()))
            return np.ones(len(X))

    monkeypatch.setattr(S, "make_model", lambda name, params: Spy())
    years = np.repeat(np.arange(2010, 2017), 200)
    X = pd.DataFrame({"day": np.arange(len(years), dtype=float)})
    y = np.random.default_rng(0).normal(size=len(years))
    pred = S.fit_predict("ridge", X, y, years)
    assert np.isnan(pred[years < 2012]).all() and not np.isnan(pred[years >= 2012]).any()
    pairs = [(log[i][1], log[i + 1][1]) for i in range(len(log) - 1) if log[i][0] == "fit" and log[i + 1][0] == "predict"]
    assert len(pairs) == 5 * (1 + len(S.MODELS["ridge"]))  # per test year: inner fits + the final fit
    assert all(fit_max < pred_min - 1 for fit_max, pred_min in pairs)  # purge + embargo before every prediction


def test_strategy_rules_and_costs():
    pred = np.array([5.0, -1.0, np.nan, 3.0])
    y = np.array([10.0, 4.0, 7.0, np.nan])
    st = S.strategies(pred, y)
    gross, trade = st["all"]
    assert list(trade) == [True, True, False, False] and list(gross) == [10.0, -4.0, 0.0, 0.0]
    assert list(st["conf_base"][1]) == [True, False, False, False]  # |pred| must exceed 2.402 ticks
    assert list(S.strategies(np.array([3.0, 5.0]), np.array([1.0, 1.0]))["conf_stress"][1]) == [False, True]


def test_label_nulls_stay_inside_each_year():
    years = np.repeat([2012, 2013], 50)
    y = np.arange(100, dtype=float)
    rolled = S.within_year(y, years, lambda v: np.roll(v, 7))
    assert set(rolled[:50]) == set(y[:50]) and set(rolled[50:]) == set(y[50:]) and not np.array_equal(rolled, y)
    shuf = S.within_year(y, years, lambda v: S.block_shuffle(v, np.random.default_rng(0)))
    assert set(shuf[:50]) == set(y[:50]) and sorted(shuf) == sorted(y)
    first_block = shuf[:20]
    assert np.all(np.diff(first_block) == 1) or len(set(np.diff(first_block))) <= 2  # blocks keep their order


def test_hyperparameter_grids_are_declared():
    assert set(S.MODELS) == {"ridge", "enet", "gbt"}
    assert all(len(v) >= 4 for v in S.MODELS.values())
    assert S.TEST_YEARS == [2012, 2013, 2014, 2015, 2016]


def test_evaluate_and_power_table_end_to_end(monkeypatch):
    monkeypatch.setattr(S, "N_BOOT", 200)
    rng = np.random.default_rng(4)
    days = np.arange(15340, 15340 + 1300)  # 2012-01-01 onwards
    years = pd.to_datetime(days, unit="D").year.to_numpy()
    oos = np.isin(years, S.TEST_YEARS)
    y1 = rng.normal(0, 20, len(days))
    good = {"ridge": y1 + rng.normal(0, 5, len(days)), "enet": rng.normal(size=len(days)), "gbt": np.zeros(len(days))}
    noise = {m: rng.normal(size=len(days)) for m in ("ridge", "enet", "gbt")}
    result = {(9 * 60, 30): (good, y1), (14 * 60, 30): (noise, rng.normal(0, 20, len(days)))}
    out = S.evaluate(result, oos, days)
    assert len(out) == 2 * 3 * len(S.RULES)
    best = out.set_index("strategy").loc["09:00+30|ridge|all"]
    assert best["rw_p_base"] < 0.05 and best["gross_per_trade"] > 10
    assert out.set_index("strategy").loc["09:00+30|gbt|all", "trades"] == 0  # pred 0 never trades
    assert out["upper_below_stress_cost"].isna().sum() >= 1  # no trades: no claim
    assert {"net_2012", "net_2013-14", "net_2015-16"} <= set(out.columns)
    ctrl = pd.DataFrame({"control": ["planted_4"] * 4 + ["planted_8"] * 4, "param": [4] * 4 + [8] * 4,
                         "min_rw_p": [0.01, 0.2, 0.5, 0.03, 0.01, 0.01, 0.02, 0.6], "oracle_net_ticks": 1.0})
    pw = S.power_table(ctrl).set_index("planted_net_ticks")
    assert pw.loc[4, "detected"] == 2 and pw.loc[8, "power"] == 0.75
    assert pw.loc[8, "power_lo95"] < 0.75 < pw.loc[8, "power_hi95"]


def test_simultaneous_upper_handles_zero_trade_columns():
    from propfirm_research.stats import simultaneous_upper
    rng = np.random.default_rng(0)
    gross = np.column_stack([rng.normal(0, 10, 300), np.zeros(300)])
    trade = np.column_stack([np.ones(300, bool), np.zeros(300, bool)])
    u = simultaneous_upper(gross, trade, n_boot=100)
    assert np.isfinite(u["upper"][0]) and np.isnan(u["upper"][1])
    with pytest.raises(ValueError):
        simultaneous_upper(np.zeros((300, 2)), np.zeros((300, 2), bool), n_boot=10)
