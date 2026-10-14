import pytest

from propfirm_data.budget import BudgetError, check_budget


def test_within_budget_returns_worst_case():
    assert check_budget({"bars": 38.0, "definitions": 0.01}, 0.0, 60.0) == pytest.approx(41.811)


def test_over_budget_after_margin_is_rejected():
    # 55 * 1.10 = 60.5 > 60
    with pytest.raises(BudgetError):
        check_budget({"bars": 55.0}, 0.0, 60.0)


def test_previous_spend_counts_toward_budget():
    with pytest.raises(BudgetError):
        check_budget({"bars": 10.0}, already_reserved=50.0, max_budget=60.0)


def test_nothing_new_costs_nothing():
    assert check_budget({}, already_reserved=40.0, max_budget=60.0) == 40.0


@pytest.mark.parametrize("quotes,budget", [({"bars": -1.0}, 60.0), ({"bars": 1.0}, 0.0)])
def test_invalid_inputs_rejected(quotes, budget):
    with pytest.raises(BudgetError):
        check_budget(quotes, 0.0, budget)


@pytest.mark.parametrize("quotes,reserved,budget", [
    ({"bars": float("nan")}, 0.0, 60.0),
    ({"bars": 1.0}, float("nan"), 60.0),
    ({"bars": 1.0}, 0.0, float("nan")),
    ({"bars": 1.0}, 0.0, float("inf")),
])
def test_nan_and_inf_never_pass(quotes, reserved, budget):
    with pytest.raises(BudgetError):
        check_budget(quotes, reserved, budget)


def test_margin_below_one_rejected():
    with pytest.raises(BudgetError):
        check_budget({"bars": 1.0}, 0.0, 60.0, margin=0.5)


def test_manifest_reserves_margin_for_old_jobs():
    from propfirm_data.download import already_reserved
    manifest = {"jobs": {"bars": {"quoted_cost": 50.0}}}  # old entry without reserved_cost
    assert already_reserved(manifest) == pytest.approx(55.0)


def test_changed_config_is_detected():
    from propfirm_data.download import job_params, mismatched_jobs
    good = {"jobs": {"bars": {"params": job_params("bars", "2026-10-14")}}}
    assert mismatched_jobs(good) == []
    changed = {"jobs": {"bars": {"params": {**job_params("bars", "2026-10-14"), "symbols": ["ES.v.0"]}}}}
    assert mismatched_jobs(changed) == ["bars"]


def test_second_instance_is_blocked(tmp_path, monkeypatch):
    from propfirm_data import download
    monkeypatch.setattr(download, "LOCK_FILE", tmp_path / "x.lock")
    with download.single_instance():
        with pytest.raises(SystemExit):
            with download.single_instance():
                pass
