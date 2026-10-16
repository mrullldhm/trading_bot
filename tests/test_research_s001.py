"""S001 study helpers (no market data)."""

import numpy as np
import pandas as pd
import pytest

from propfirm_research.studies import s001_feasibility as S


def test_bridge_low_below_zero_and_close():
    rng = np.random.default_rng(0)
    x = rng.normal(0, 300, 10_000)
    low = S.bridge_low(x, 300.0, rng.random(10_000))
    assert (low <= np.minimum(0, x) + 1e-9).all()
    # reflection principle: P(min <= -m) = 2 P(X <= -m) for driftless Brownian motion
    m = 300.0
    assert (low <= -m).mean() == pytest.approx(2 * (x <= -m).mean(), abs=0.02)


@pytest.mark.parametrize("df_", [None, 5, 3])
def test_part_a_days_have_target_sd(df_):
    noise, sig, u = S.part_a_days(df_, 150.0, np.random.default_rng(1))
    assert noise.mean() == pytest.approx(0, abs=10)
    if df_ != 3:  # t3 has infinite fourth moment: sample sd converges slowly
        assert noise.std() == pytest.approx(150, rel=0.05)
    assert (sig > 0).all() and ((u > 0) & (u < 1)).all()


def test_thresholds_first_and_stable():
    e = np.array([-2.4, 0, 2, 4, 6])
    ok = np.array([True, False, True, False, True])
    assert S.thresholds(e, ok) == (2.0, 6.0)
    assert np.isnan(S.thresholds(e, np.zeros(5, bool))[0])


def test_required_edges_take_reserve_rows_for_criterion_c():
    rows = []
    for res, fail_ucb, fail in ((0.0, 0.0, 0.20), (500.0, 0.005, 0.30)):
        for e in (S.BASELINE, 0.0):
            rows.append({"template": "t", "freq": 1.0, "cost": "base", "account": "50K", "contracts": 1,
                         "reserve": res, "e_net": e, "pass": 0.6, "fail": fail, "fail_ucb95": fail_ucb,
                         "p95_dd": 500.0, "g8_limit": 1000.0, "sharpe_ann": 1.0, "ic": 0.1,
                         "median_days_pass": 50.0})
    req = S.required_edges(pd.DataFrame(rows)).iloc[0]
    assert req["c_failucb1_res500_stable"] == 0.0
    assert req["c_failucb1_res500_fail"] == 0.30 and req["c_failucb1_res500_reserve"] == 500.0
    assert req["b_pass50_fail25_fail"] == 0.20
