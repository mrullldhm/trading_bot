"""ACD signal holdout: the pre-registered decision rule and the once-only / no-change guards."""

import json

import numpy as np
import pytest

from propfirm_backtest import acd_signal_holdout as H
from propfirm_backtest import audit as A

FROZEN = {"champion_cfg": [3, 0, 30, 100, 150, 50, 1, 1, -1, 0], "source_sha256": "abc"}
Q = [*map(str, A.HORIZONS), "session end"].index(H.HORIZON)
N_H = len(A.HORIZONS) + 1


@pytest.fixture(autouse=True)
def no_real_data(monkeypatch):
    monkeypatch.setattr(H, "data_hash", lambda: "data")


def raw(n, move_ticks, edge_ticks, seed=0, noise=20.0, n_controls=20):
    """Signals whose 60-min move is move_ticks + noise; controls centred edge_ticks below the signal mean."""
    rng = np.random.default_rng(seed)
    move = np.full((n, N_H), np.nan)
    controls = np.full((n, A.N_RANDOM_PER_SIGNAL, N_H), np.nan)
    move[:, Q] = move_ticks + rng.normal(0, noise, n)
    controls[:, :n_controls, Q] = move_ticks - edge_ticks + rng.normal(0, noise, (n, n_controls))
    return {"move": move, "controls_local": controls, "day": np.arange(n)}


def test_decision_rule(monkeypatch):
    monkeypatch.setattr(H, "N_PERMUTATIONS", 999)
    assert H.decide(raw(50, 10, 10))["verdict"] == "INCONCLUSIVE"
    assert H.decide(raw(800, 10, 10, n_controls=3))["verdict"] == "INCONCLUSIVE"  # too few controls per signal
    assert H.decide(raw(800, 0, 0))["verdict"] == "EDGE NOT CONFIRMED"
    d = H.decide(raw(800, 2.0, 5.0))  # beats its controls, but 2 ticks < $24.02 of costs
    assert d["verdict"] == "CONFIRMED EDGE; PROFITABILITY AFTER COSTS NOT CONFIRMED" and d["h1_pass"] and not d["h2_pass"]
    assert H.decide(raw(800, 8.0, 6.0))["verdict"] == "CONFIRMED EDGE AND PROFITABLE AT 60 MIN"
    d = H.decide(raw(800, 8.0, -6.0))  # profitable but worse than random entries: H2 is never tested
    assert d["verdict"] == "EDGE NOT CONFIRMED" and not d["h2_tested"] and not d["h2_pass"]


def test_randomization_test_false_alarm_rate_is_about_alpha(monkeypatch):
    """With independent (exclusive) controls the test holds its 5% level; the design guarantees that."""
    monkeypatch.setattr(H, "N_PERMUTATIONS", 199)
    rng = np.random.default_rng(1)
    alarms = 0
    for k in range(400):
        _, p = H.randomization_p(rng.normal(0, 20, 150), rng.normal(0, 20, (150, A.N_RANDOM_PER_SIGNAL)), seed=k)
        alarms += p < H.ALPHA
    assert 0.025 <= alarms / 400 <= 0.08


def test_randomization_p_detects_a_real_edge(monkeypatch):
    monkeypatch.setattr(H, "N_PERMUTATIONS", 999)
    r = raw(300, 0.0, 6.0)
    t, p = H.randomization_p(r["move"][:, Q], r["controls_local"][:, :, Q])
    assert t == pytest.approx(6.0, abs=2.0) and p < 0.01


def test_registration_is_written_once_and_checked(tmp_path):
    assert H.check_registration(tmp_path, FROZEN) == 1  # not registered: refuse
    assert H.register(tmp_path, FROZEN) == 0
    reg = json.loads((tmp_path / H.PREREG).read_text())
    assert reg["horizon_min"] == "60" and reg["alpha_one_sided"] == 0.05 and reg["test_code_sha256"] == H.code_hash()
    assert reg["data_sha256"] == "data" and "numpy" in reg["environment"] and "one run" in reg["stopping_rule"]
    assert H.register(tmp_path, FROZEN) == 2  # never rewritten
    assert H.check_registration(tmp_path, FROZEN) == 0
    assert H.check_registration(tmp_path, {**FROZEN, "champion_cfg": [9] * 10}) == 3  # champion changed


@pytest.mark.parametrize("what", ["code_hash", "data_hash"])
def test_changed_code_or_data_is_refused(tmp_path, monkeypatch, what):
    H.register(tmp_path, FROZEN)
    monkeypatch.setattr(H, what, lambda: "edited")
    assert H.check_registration(tmp_path, FROZEN) == 3


def test_holdout_opens_once(tmp_path):
    assert H.mark_opened(tmp_path, FROZEN)
    assert json.loads((tmp_path / "holdout_opened.json").read_text())["opened_by"] == "acd_signal_holdout"
    assert not H.mark_opened(tmp_path, FROZEN)


def test_cli_needs_exactly_one_mode():
    assert H.main([]) == 2 and H.main(["--register", "--run"]) == 2
