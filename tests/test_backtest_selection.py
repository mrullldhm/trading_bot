import json

import numpy as np
import pandas as pd
import pytest

from propfirm_backtest import holdout as H
from propfirm_backtest import search as S


def configs(n_tf=3, n_ema=3):
    rows = []
    for tf in S.B.TIMEFRAMES[:n_tf]:
        for ema in S.I.EMA_LENGTHS[:n_ema]:
            rows.append({"timeframe": tf, "ema": ema, "vwap_anchor": "day", "entry": "cross", "stop_ticks": 0,
                         "session": "newyork", "trades": 500, "expectancy_usd": 5.0, "expectancy_slip2": 2.0,
                         "positive_year_frac": 0.8, "best_year_share": 0.2, "best_day_share": 0.05,
                         "p95_drawdown": 800.0, "pass_prob": 0.3})
    return pd.DataFrame(rows)


def test_gate_failing_config_never_beats_a_gate_passer_even_with_zero_pass_prob():
    df = configs()
    df["pass_prob"] = 0.0  # every gate-passer has a 0% bootstrap estimate
    df.loc[4, ["expectancy_slip2", "pass_prob"]] = [-1.0, 0.9]  # fails the +1 tick gate but scores high
    ranked = S.rank(df)
    champ = ranked.sort_values("rank").iloc[0]
    assert champ["passes_gates"] and champ.name != 4


def test_plateau_prefers_a_stable_region_over_a_lone_spike():
    df = configs()
    df["pass_prob"] = 0.1
    df.loc[0, "pass_prob"] = 0.9  # corner spike, neighbours weak
    plat = S.plateau(df, "pass_prob")
    assert plat[0] == pytest.approx(0.1)


def test_every_gate_is_enforced():
    base = configs(1, 1)
    for col, bad in [("trades", 10), ("expectancy_usd", -1), ("expectancy_slip2", -1), ("positive_year_frac", 0.3),
                     ("best_year_share", 0.9), ("best_day_share", 0.5), ("p95_drawdown", 5000)]:
        assert not S.gate_mask(base.assign(**{col: bad})).iloc[0], col
    assert S.gate_mask(base).iloc[0]


def test_holdout_refuses_second_opening(tmp_path, monkeypatch):
    monkeypatch.setattr(S, "OUT_DIR", tmp_path)
    (tmp_path / "frozen_picks.json").write_text(json.dumps({"source_sha256": S.source_hash()}))
    (tmp_path / "holdout_opened.json").write_text(json.dumps({"opened_utc": "2026-01-01"}))
    assert H.main() == 2


def test_holdout_refuses_changed_code(tmp_path, monkeypatch):
    monkeypatch.setattr(S, "OUT_DIR", tmp_path)
    (tmp_path / "frozen_picks.json").write_text(json.dumps({"source_sha256": "different"}))
    assert H.main() == 3
    assert not (tmp_path / "holdout_opened.json").exists()


def test_walk_forward_trade_minimum_scales_with_fold_years():
    assert S.wf_min_trades(3) == 100  # floor: 3 years x 25 = 75
    assert S.wf_min_trades(8) == 200
    df = configs()
    df["trades"] = 150
    assert not S.gate_mask(df).any()  # full gate: 300
    assert S.gate_mask(df, S.wf_min_trades(4)).all()  # a 4-year fold needs 100
