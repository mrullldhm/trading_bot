"""S004 stage-1 audit: the acceptance rules and the facts they read (computed with the harness's own rules)."""

import numpy as np
import pandas as pd

from propfirm_research import settlement
from propfirm_research.periods import trading_day
from propfirm_research.studies import s004_stage1_data as A


def facts(**over):
    f = {"cl_minute_volume": {"exact_share": 1.0}, "settlement_vs_vwap": {"within_1_tick_share": 0.99},
         "cl_quote_rule": {"mis_signed_volume_share_estimate": 0.006, "volume_accuracy_when_classified": 0.92},
         "cl_contract_match_days": 500, "cl_contract_compared_days": 500, "tas_front_days_multi_id": 0,
         "tas_front_trades_after_close": 0,
         "coverage_share": {"cl_mbp1": 0.99, "tas_front": 0.97, "RB.v.0": 0.99, "HO.v.0": 0.99, "BZ.v.0": 0.97}}
    f.update(over)
    return f


def test_acceptance_needs_every_rule():
    assert A.acceptance(facts())["all_ok"]
    bad_cases = (dict(cl_minute_volume={"exact_share": 0.98}), dict(cl_contract_match_days=499),
                 dict(tas_front_days_multi_id=1), dict(tas_front_trades_after_close=3),
                 dict(cl_quote_rule={"mis_signed_volume_share_estimate": 0.02, "volume_accuracy_when_classified": 0.92}),
                 dict(coverage_share={"cl_mbp1": 0.08, "tas_front": 0.97, "RB.v.0": 0.99, "HO.v.0": 0.99,
                                      "BZ.v.0": 0.97}),
                 dict(coverage_share={"cl_mbp1": 0.99, "tas_front": 0.97, "RB.v.0": 0.99, "HO.v.0": 0.99,
                                      "BZ.v.0": 0.90}))
    for bad in bad_cases:
        assert not A.acceptance(facts(**bad))["all_ok"], bad


def audit_with_tas(times_et):
    """An Audit holding only front-TAS trades at the given ET clock times (trading day by the 18:00 rule)."""
    a = A.Audit.__new__(A.Audit)
    ts = pd.DatetimeIndex(pd.to_datetime(times_et, format="ISO8601")).tz_localize("America/New_York").tz_convert("UTC")
    ns = ((ts - pd.Timestamp("1970-01-01", tz="UTC")) // pd.Timedelta(1, "ns")).to_numpy("int64")
    days = trading_day(pd.Series(ts))
    a.tas = pd.DataFrame({"trading_day": days, "event_ns": ns, "is_spread": False, "raw_symbol": "CLTN6",
                          "instrument_id": 7, "size": 5, "side": 1, "diff_ticks": 0})
    a.entry = pd.DataFrame({"entry_ok": True, "entry_contract": "CLN6@2016-06"}, index=np.unique(days))
    a.tables, a.facts = {}, {}
    return a


def test_evening_tas_trades_are_inside_the_session_not_after_the_close():
    a = audit_with_tas(["2016-06-01 10:00", "2016-06-01 19:00", "2016-06-01 23:30"])
    a.tas_tables()
    assert a.facts["tas_front_trades_after_close"] == 0
    assert a.facts["tas_front_latest_daytime_trade_et"] == "10:00:00"
    late = audit_with_tas(["2016-06-01 10:00", "2016-06-01 14:30:00.047", "2016-06-01 14:30:01", "2016-06-01 14:31"])
    late.tas_tables()  # a close-time match in the first second is counted apart; from 14:30:01 it is after the close
    assert late.facts["tas_front_trades_in_first_second_after_close"] == 1
    assert late.facts["tas_front_trades_after_close"] == 2


def test_front_tas_symbol_rule_is_shared_with_the_harness():
    assert settlement.front_tas_symbol("CLN6@2016-06") == "CLTN6" and settlement.front_tas_symbol(None) is None
