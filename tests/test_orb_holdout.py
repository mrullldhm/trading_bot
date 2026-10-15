import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from propfirm_backtest import bars as B
from propfirm_backtest import orb_engine as E
from propfirm_backtest import orb_holdout as H
from propfirm_backtest import orb_search as O

sys.path.insert(0, str(Path(__file__).parent))
from test_orb_engine import cfg, random_market  # noqa: E402

FROZEN_OK = {"champion_eligible": True, "walk_forward_total_usd": 1000.0, "pbo": 0.2,
             "deflated_sharpe_effective": 0.97}
HOLDOUT_OK = {"expectancy_usd": 10.0, "stress": {2.0: {"expectancy_usd": 2.0}}, "pass_prob": 0.5, "fail_prob": 0.3}


def test_verdict_pass_needs_everything():
    assert H.verdict(FROZEN_OK, HOLDOUT_OK)[0] == "PASS"
    for key, bad in [("champion_eligible", False), ("walk_forward_total_usd", 0.0), ("pbo", 0.5),
                     ("deflated_sharpe_effective", 0.94)]:
        assert H.verdict({**FROZEN_OK, key: bad}, HOLDOUT_OK)[0] == "FAIL", key
    for ho in [{**HOLDOUT_OK, "expectancy_usd": -1.0}, {**HOLDOUT_OK, "stress": {2.0: {"expectancy_usd": -1.0}}},
               {**HOLDOUT_OK, "pass_prob": 0.3, "fail_prob": 0.3}]:
        assert H.verdict(FROZEN_OK, ho)[0] == "FAIL"


def write_frozen(out: Path, **over):
    out.mkdir(parents=True, exist_ok=True)
    (out / "frozen_picks.json").write_text(json.dumps({"quick": False, "source_sha256": "abc", **over}))


def test_preflight_refuses_without_touching_the_marker(tmp_path, monkeypatch):
    monkeypatch.setattr(O, "source_hash", lambda: "abc")
    assert H.preflight(tmp_path / "none")[1] == 1  # no picks
    write_frozen(tmp_path / "q", quick=True)
    assert H.preflight(tmp_path / "q")[1] == 1
    write_frozen(tmp_path / "h", source_sha256="old")
    assert H.preflight(tmp_path / "h")[1] == 3
    write_frozen(tmp_path / "m")
    (tmp_path / "m" / "holdout_opened.json").write_text(json.dumps({"opened_utc": "x"}))
    assert H.preflight(tmp_path / "m")[1] == 2
    for d in ["q", "h"]:
        assert not (tmp_path / d / "holdout_opened.json").exists()


def test_evaluate_writes_trades_raw_numbers_and_report(tmp_path):
    df, eia = random_market(11)
    m = B.build_minutes(df)
    c = cfg(target_x10=20, flat=120)
    frozen = {**FROZEN_OK, "created_utc": "2026-01-01T00:00", "deflated_sharpe_unique": 0.1,
              "champion_cfg": c.tolist(),
              "champion": {"anchor": "et0900", "range_min": 5, "trigger": "stop", "buffer": 0, "stop": "opposite",
                           "target": "2R", "window_min": 60, "flat": "+120", "direction": "both1",
                           "width": "none", "breakeven": "off"}}
    result = H.evaluate(m, frozen, tmp_path, eia)
    assert result in ("PASS", "FAIL")
    trades = pd.read_csv(tmp_path / "champion_trades.csv")
    raw = json.loads((tmp_path / "holdout_raw.json").read_text())
    assert raw["verdict"] == result and raw["stats"]["trades"] == len(trades) > 0
    assert set(trades["period"]) == {"holdout"}  # synthetic data is all after 2022
    assert trades["pnl_usd"].sum() == pytest.approx(raw["stats"]["total_usd"], abs=0.01 * len(trades))
    assert (tmp_path / "holdout.md").read_text().startswith("# ORB: holdout results")
    mk = E.Market(m, np.unique(m.trading_day[m.front]), eia)
    t = mk.trades(c)
    assert np.allclose(trades["entry_ticks"], t[4]) and np.allclose(trades["exit_ticks"], t[5])
