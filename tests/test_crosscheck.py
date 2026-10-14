import pandas as pd
import pytest

from propfirm_data import crosscheck as cc


def bars(times, close_ticks, sym="CLX6", cont="CL.v.0", vol=10):
    t = pd.Series(close_ticks)
    return pd.DataFrame({
        "raw_symbol": sym, "continuous_symbol": cont,
        "ts_event_utc": pd.to_datetime(times, utc=True),
        "open_ticks": t, "high_ticks": t + 1, "low_ticks": t - 1, "close_ticks": t, "volume": vol,
    })


T = ["2026-10-12 15:00", "2026-10-12 15:01", "2026-10-12 15:02"]


def test_fetch_all_follows_next_url_until_absent():
    pages = {
        "first": {"results": [{"a": 1}], "next_url": "p2"},
        "p2": {"results": [{"a": 2}], "next_url": "p3"},
        "p3": {"results": [{"a": 3}]},
    }
    seen = []

    def fake_get(url):
        key = "first" if url.startswith(cc.AGGS_URL.format(ticker="CLX6")) else url
        seen.append(key)
        return pages[key]

    out = cc.fetch_all(fake_get, "CLX6", pd.Timestamp("2026-10-12", tz="UTC"), pd.Timestamp("2026-10-13", tz="UTC"))
    assert [r["a"] for r in out] == [1, 2, 3]
    assert seen == ["first", "p2", "p3"]


def test_first_page_url_uses_nanoseconds_and_exclusive_end():
    url = cc.first_page_url("CLX6", pd.Timestamp("2026-10-12", tz="UTC"), pd.Timestamp("2026-10-13", tz="UTC"))
    assert "window_start.gte=1791763200000000000" in url
    assert "window_start.lt=1791849600000000000" in url
    assert "apiKey" not in url  # key goes in the header only


def test_massive_prices_become_ticks_without_float_error():
    df = cc.massive_to_frame([{"ticker": "CLX6", "window_start": 1791763200000000000,
                               "open": 90.82, "high": 90.9, "low": 90.8, "close": 90.81, "volume": 111}])
    assert df.iloc[0][["open_ticks", "high_ticks", "low_ticks", "close_ticks"]].tolist() == [9082, 9090, 9080, 9081]
    assert df.iloc[0]["ts_event_utc"] == pd.Timestamp("2026-10-12 00:00", tz="UTC")


def test_negative_prices_round_correctly():
    df = cc.massive_to_frame([{"ticker": "CLK0", "window_start": 0, "open": -37.63, "high": -37.6,
                               "low": -40.32, "close": -37.63, "volume": 1}])
    assert df.iloc[0]["low_ticks"] == -4032


def test_compare_counts_exact_one_tick_missing_and_extra():
    db = bars(T, [9000, 9001, 9002])
    ms = bars(T[:2] + ["2026-10-12 15:05"], [9000, 9002, 9100])  # 2nd is 1 tick off, 3rd only in Massive
    s = cc.summarize(cc.compare(db, ms))
    assert s["matched"] == 2 and s["databento_only"] == 1 and s["massive_only"] == 1
    assert s["ohlc_exact_pct"] == 50.0
    assert s["ohlc_within_1_tick_pct"] == 100.0
    assert s["max_diff_ticks"] == 1
    assert s["databento_match_pct"] == round(100 * 2 / 3, 3)
    assert s["massive_match_pct"] == round(100 * 2 / 3, 3)


def test_volume_difference_detected():
    s = cc.summarize(cc.compare(bars(T, [9000] * 3, vol=10), bars(T, [9000] * 3, vol=12)))
    assert s["ohlc_exact_pct"] == 100.0 and s["volume_exact_pct"] == 0.0
    assert s["volume_median_ratio"] == 1.2


def test_window_dedupes_contract_seen_as_v0_and_v1_keeping_v0():
    both = pd.concat([bars(T[:1], [9000], cont="CL.v.1"), bars(T[:1], [9000], cont="CL.v.0")])
    out = cc.databento_window(both, pd.Timestamp("2026-10-14", tz="UTC"))
    assert len(out) == 1 and out.iloc[0]["continuous_symbol"] == "CL.v.0"


def test_window_drops_recent_bars_inside_free_tier_delay():
    now = pd.Timestamp("2026-10-12 18:00", tz="UTC")  # bars at 15:0x are < 8h old
    assert cc.databento_window(bars(T, [9000] * 3), now).empty


def test_verdict_thresholds():
    good = {"ohlc_exact_pct": 99.5, "databento_match_pct": 99.9, "massive_match_pct": 99.9}
    assert cc.verdict(good) == "PASS"
    assert cc.verdict({**good, "ohlc_exact_pct": 98.0}) == "WARN"
    assert cc.verdict({**good, "massive_match_pct": 90.0}) == "WARN"


def test_massive_bars_on_days_contract_left_v0_v1_are_ignored():
    # Databento has CLM5 on Tue 2025-01-21 and Tue 2025-03-25 only (it left the v.0/v.1 pair in between).
    db = pd.concat([bars(["2025-01-21 15:00"], [7000], sym="CLM5", cont="CL.v.1"),
                    bars(["2025-03-25 15:00"], [7100], sym="CLM5", cont="CL.v.0")])
    ms = bars(["2025-01-21 15:00", "2025-02-20 15:00", "2025-03-25 15:00"], [7000, 6900, 7100], sym="CLM5")
    m = cc.compare(db, ms)
    assert len(m) == 2 and (m["side"] == "both").all()  # Feb bar dropped, not counted massive_only
    assert sorted(m["continuous_symbol"]) == ["CL.v.0", "CL.v.1"]  # labelled per day


def test_massive_only_bar_gets_that_days_symbol():
    db = bars(["2025-03-25 15:00"], [7100], sym="CLM5", cont="CL.v.0")
    ms = bars(["2025-03-25 15:00", "2025-03-25 15:07"], [7100, 7101], sym="CLM5")
    m = cc.compare(db, ms)
    extra = m[m["side"] == "massive_only"]
    assert len(extra) == 1 and extra.iloc[0]["continuous_symbol"] == "CL.v.0"


def test_daily_agreement_uses_all_bars_of_each_vendor():
    # Massive misses the minute holding the daily high: daily high must NOT be reported exact.
    db = bars(T, [9000, 9050, 9001])
    ms = bars([T[0], T[2]], [9000, 9001])
    m = cc.add_labels(cc.compare(db, ms), set())
    assert cc.daily_agreement(m)["daily_high_exact_pct"] == 0.0


@pytest.mark.parametrize("url", ["http://api.massive.com/x", "https://evil.example/x", "https://api.massive.com.evil.io/x"])
def test_key_never_sent_off_host(url):
    with pytest.raises(RuntimeError):
        cc._check_url(url)
