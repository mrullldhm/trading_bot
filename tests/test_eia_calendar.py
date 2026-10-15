import numpy as np
import pandas as pd

from propfirm_data import eia_calendar as C


def holidays(*days):
    return {pd.Timestamp(d) for d in days}


def test_rule_slot_holiday_shifts():
    sun = pd.Timestamp("2019-05-26")  # Memorial Day Monday 05-27
    assert C.rule_slot(sun, holidays("2019-05-27")) == C.THU_1100
    assert C.rule_slot(sun, set()) == C.WED_1030
    assert C.rule_slot(pd.Timestamp("2019-12-22"), holidays("2019-12-25")) == C.FRI_1100  # Christmas Wed
    assert C.rule_slot(pd.Timestamp("2017-12-24"), holidays("2017-12-25")) == C.THU_1100  # Christmas Mon
    assert C.rule_slot(pd.Timestamp("2019-11-24"), holidays("2019-11-28")) == C.WED_1030  # Thanksgiving Thu


def scores_frame(values: dict) -> pd.DataFrame:
    """values: {(date, minute): score}; every other candidate scores 1.0."""
    days = pd.date_range("2019-05-19", "2019-06-08")
    s = pd.DataFrame(1.0, index=days, columns=[630, 660, 720])
    for (d, t), v in values.items():
        s.at[pd.Timestamp(d), t] = v
    return s


def test_build_is_rule_only_and_blocks_all_holiday_slots():
    s = scores_frame({("2019-05-22", 630): 9.0,   # normal week: Wed 10:30, confirmed
                      ("2019-06-06", 720): 8.0})  # spike off the rule: NOT blocked, only reported
    out, misses = C.build(s, "2019-05-19", "2019-06-08")
    rows = {(str(d), t): st for d, t, st in zip(out["date"], out["time_et"], out["status"])}
    assert rows[("2019-05-22", "10:30")] == "confirmed"
    assert ("2019-06-06", "12:00") not in rows and ("2019-06-05", "10:30") in rows
    assert list(misses["date"].astype(str)) == ["2019-06-06"]
    holiday_week = [k for k in rows if "2019-05-28" <= k[0] <= "2019-05-31"]  # Memorial Day Mon 05-27
    assert len(holiday_week) == len(C.CANDIDATES)  # Tue..Fri x 3 times all blocked


def test_spike_scores_ratio():
    day = np.array(["2019-05-22"] * 21)
    mod = np.arange(610, 631)
    vol = np.full(21, 10.0)
    vol[-1] = 90.0
    s = C.spike_scores(day, mod, vol)
    assert s.loc[pd.Timestamp("2019-05-22"), 630] == 9.0
    assert np.isnan(s.loc[pd.Timestamp("2019-05-22"), 660])
