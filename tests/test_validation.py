import pandas as pd
import pytest

from propfirm_data import validate
from propfirm_data.convert import ConversionError, attach_raw_symbol, bars_from_df, definitions_from_df

TICK = 10_000_000  # fixed-price units per $0.01


def make_bars(times, closes, symbol="CL.v.0", ids=None, raw="CLZ5"):
    ticks = pd.Series(closes)
    ts = pd.to_datetime(times, utc=True)
    return pd.DataFrame({
        "ts_event_utc": ts,
        "continuous_symbol": symbol,
        "instrument_id": ids or [1] * len(ts),
        "raw_symbol": raw,
        "open_ticks": ticks, "high_ticks": ticks + 2, "low_ticks": ticks - 2, "close_ticks": ticks,
        "open": ticks / 100, "high": (ticks + 2) / 100, "low": (ticks - 2) / 100, "close": ticks / 100,
        "volume": 10,
        "expiration": pd.Timestamp("2030-01-01", tz="UTC"),
    })


# Tuesday 2025-11-04, 09:00-09:02 Chicago (15:00 UTC) = normal session
GOOD_TIMES = ["2025-11-04 15:00", "2025-11-04 15:01", "2025-11-04 15:02"]


def levels(issues):
    return {(i.level, i.check) for i in issues}


def test_clean_data_has_no_issues():
    assert validate.run_all(make_bars(GOOD_TIMES, [6000, 6001, 6002])) == []


def test_duplicate_bar_is_error():
    df = make_bars(["2025-11-04 15:00", "2025-11-04 15:00"], [6000, 6000])
    assert ("ERROR", "duplicate bars") in levels(validate.run_all(df))


def test_high_below_close_is_error():
    df = make_bars(GOOD_TIMES, [6000, 6001, 6002])
    df.loc[1, "high_ticks"] = 5990
    assert any(i.check.startswith("low/high") for i in validate.check_prices(df))


def test_negative_prices_are_allowed():
    # April 2020: CL traded below zero.
    assert validate.check_prices(make_bars(GOOD_TIMES, [-3000, -2990, -2980])) == []


def test_missing_contract_symbol_is_error():
    df = make_bars(GOOD_TIMES, [6000, 6001, 6002], raw=None)
    assert any(i.check == "bar has no real contract symbol" for i in validate.check_contracts(df))


def test_bar_after_expiry_is_error():
    df = make_bars(GOOD_TIMES, [6000, 6001, 6002])
    df["expiration"] = pd.Timestamp("2025-11-04 15:01", tz="UTC")
    assert validate.check_contracts(df)[0].count == 2


def test_saturday_and_maintenance_break_flagged():
    # Saturday 2025-11-08 and Tuesday 16:30 Chicago (22:30 UTC, CST)
    df = make_bars(["2025-11-04 22:30", "2025-11-08 15:00"], [6000, 6001])
    assert validate.check_session(df)[0].count == 2


def test_gap_inside_session_warns():
    df = make_bars(["2025-11-04 15:00", "2025-11-04 15:30"], [6000, 6001])
    assert validate.check_gaps(df)[0].count == 1


def test_trading_day_starts_at_5pm_chicago():
    # 17:30 Chicago on Monday 2025-11-03 belongs to Tuesday's session.
    df = make_bars(["2025-11-03 23:30"], [6000])
    assert str(validate.trading_day(df).iloc[0]) == "2025-11-04"


def test_roll_point_detected_with_jump():
    df = make_bars(GOOD_TIMES, [6000, 6010, 6011], ids=[1, 2, 2])
    df["raw_symbol"] = ["CLZ5", "CLF6", "CLF6"]
    rolls = validate.roll_points(df)
    assert len(rolls) == 1
    assert rolls.iloc[0]["from"] == "CLZ5" and rolls.iloc[0]["to"] == "CLF6"
    assert rolls.iloc[0]["jump_ticks"] == 10  # new contract open 6010 - old contract close 6000


# --- conversion ------------------------------------------------------------------------------

def raw_bars(prices):
    return pd.DataFrame({
        "ts_event": pd.to_datetime(GOOD_TIMES[: len(prices)], utc=True),
        "instrument_id": 1,
        "open": prices, "high": prices, "low": prices, "close": prices,
        "volume": 5, "symbol": "CL.v.0",
    }).set_index("ts_event")


def test_bars_from_df_converts_fixed_prices_to_ticks():
    out = bars_from_df(raw_bars([60_000 * TICK, 60_001 * TICK]))
    assert out["close_ticks"].tolist() == [60_000, 60_001]
    assert out["close"].tolist() == [600.00, 600.01]


def test_off_grid_price_raises():
    with pytest.raises(ConversionError):
        bars_from_df(raw_bars([60_000 * TICK + 1]))


def test_definitions_keep_futures_only_and_join_by_time():
    defs = definitions_from_df(pd.DataFrame({
        "ts_recv": pd.to_datetime(["2025-11-01", "2025-11-01"], utc=True),
        "instrument_id": [1, 99],
        "raw_symbol": ["CLZ5", "CLZ5-CLF6"],
        "instrument_class": ["F", "S"],  # S = spread, must be dropped
        "expiration": pd.to_datetime(["2025-11-20", "2025-11-20"], utc=True),
        "activation": pd.to_datetime(["2024-01-01", "2024-01-01"], utc=True),
    }))
    assert defs["raw_symbol"].tolist() == ["CLZ5"]

    bars = bars_from_df(raw_bars([60_000 * TICK]))
    joined = attach_raw_symbol(bars, defs)
    assert joined["raw_symbol"].tolist() == ["CLZ5"]


def test_missing_weekday_warns():
    # Tue 2025-11-04 and Thu 2025-11-06 present, Wed missing.
    df = make_bars(["2025-11-04 15:00", "2025-11-06 15:00"], [6000, 6001])
    issue = validate.check_missing_days(df)[0]
    assert issue.count == 1 and issue.examples == ["2025-11-05"]


def test_roll_detected_when_only_raw_symbol_changes():
    df = make_bars(GOOD_TIMES, [6000, 6000, 6000], ids=[1, 1, 1])
    df["raw_symbol"] = ["CLZ5", "CLZ5", "CLF6"]
    assert len(validate.roll_points(df)) == 1


def test_forward_fallback_rejects_definition_from_later_contract_life():
    # Only definition for id 1 is a LATER contract activated after the bar: must not be matched.
    defs = pd.DataFrame({
        "ts_recv": pd.to_datetime(["2026-01-01"], utc=True),
        "instrument_id": [1],
        "raw_symbol": ["CLH7"],
        "expiration": pd.to_datetime(["2027-02-20"], utc=True),
        "activation": pd.to_datetime(["2026-01-01"], utc=True),
    })
    joined = attach_raw_symbol(bars_from_df(raw_bars([60_000 * TICK])), defs)
    assert joined["raw_symbol"].isna().all()
