"""propfirm_data.stage1_convert: the line-1 decision rule and the DBN-frame -> parquet-frame conversions. Synthetic
frames shaped like Databento's `to_df(price_type="fixed", pretty_ts=True, map_symbols=True)` output; no files."""

import databento_dbn as d
import numpy as np
import pandas as pd
import pytest

from propfirm_data import stage1_convert as C

UNDEF = d.UNDEF_PRICE


def ts(*s):
    return pd.Series(pd.to_datetime(list(s), utc=True))


def side_frame(sides, sizes):
    return pd.DataFrame({"side": sides, "size": sizes})


@pytest.mark.parametrize("sides, sizes, want", [
    (["A", "B"] * 50, [1] * 100, "line5"),                     # every trade has a side
    (["A", "B"] * 44 + ["A"] + ["N"] * 11, [1] * 100, "line6"),  # 89%: below the 90% floor
    (["A", "B"] * 45 + ["N"] * 10, [1] * 100, "ask_owner"),     # exactly 90%: the 90-99% band
    (["A", "B"] * 48 + ["N"] * 4, [1] * 100, "ask_owner"),      # 96%
    (["B"] * 100, [1] * 100, "line6"),                         # only one side code
    (["A", "B"] * 50 + ["N"], [1] * 100 + [50], "line6"),       # 99% of records but 67% of volume: the lower decides
])
def test_decision_rule(sides, sizes, want):
    assert C.decide(C.side_coverage(side_frame(sides, sizes))) == want


def test_side_coverage_counts_volume_and_records():
    cov = C.side_coverage(side_frame(["A", "B", "N"], [3, 5, 2]))
    assert cov["coverage_records"] == pytest.approx(2 / 3) and cov["coverage_volume"] == pytest.approx(0.8)
    assert cov["side_counts"] == {"A": 1, "B": 1, "N": 1} and cov["both_codes"]


def tas_df(price_ticks, symbols, ids):
    n = len(price_ticks)
    return pd.DataFrame({"ts_event": ts(*["2015-06-10 18:00"] * n), "ts_recv": ts(*["2015-06-10 18:00"] * n),
                         "instrument_id": ids, "symbol": symbols,
                         "price": [int(p * C.FIXED_PER_TAS_TICK) for p in price_ticks], "size": 5, "side": "B",
                         "action": "T", "flags": 8, "sequence": np.arange(n)})


def test_tas_frame_converts_differentials_and_checks_spread_flags():
    out = C.tas_frame(tas_df([0, 1, -3], ["CLTN5", "CLTN5", "CLTN5-CLTQ5"], [7, 7, 9]), spread_ids={9})
    assert out["diff_ticks"].tolist() == [0, 1, -3] and out["is_spread"].tolist() == [False, False, True]
    with pytest.raises(ValueError):  # the definitions call instrument 7 a spread but its name has no leg separator
        C.tas_frame(tas_df([0], ["CLTN5"], [7]), spread_ids={7})
    bad = tas_df([0], ["CLTN5"], [7])
    bad["price"] = 500_000_000  # half a tick
    with pytest.raises(ValueError):
        C.tas_frame(bad, spread_ids=set())


def test_energy_frame_uses_each_markets_tick():
    df = pd.DataFrame({"ts_event": ts("2015-06-10 18:25", "2015-06-10 18:25"), "symbol": ["RB.v.0", "BZ.v.0"],
                       "instrument_id": [1, 2], "volume": [4, 1],
                       "open": [1_452_300_000, 62_150_000_000], "high": [1_452_400_000, 62_160_000_000],
                       "low": [1_452_200_000, 62_140_000_000], "close": [1_452_300_000, 62_150_000_000]})
    out = C.energy_frame(df)
    assert out["open_ticks"].tolist() == [14523, 6215] and out["open"].tolist() == pytest.approx([1.4523, 62.15])
    off = df.copy()
    off.loc[1, "open"] = 62_155_000_000  # BZ moves in whole cents
    with pytest.raises(ValueError):
        C.energy_frame(off)
    unknown = df.copy()
    unknown.loc[0, "symbol"] = "NG.v.0"
    with pytest.raises(ValueError):
        C.energy_frame(unknown)


def test_mbp1_trades_keep_trades_with_the_book_and_undefined_sides_empty():
    df = pd.DataFrame({"ts_event": ts(*["2015-06-10 18:28"] * 3), "ts_recv": ts(*["2015-06-10 18:28"] * 3),
                       "instrument_id": 401155, "action": ["A", "T", "T"], "side": ["B", "B", "N"],
                       "price": [60_000_000_000, 60_010_000_000, 60_000_000_000], "size": [3, 2, 1], "flags": 8,
                       "sequence": [1, 2, 3], "bid_px_00": [60_000_000_000, 60_000_000_000, UNDEF],
                       "ask_px_00": [60_010_000_000, 60_010_000_000, 60_010_000_000]})
    out = C.mbp1_trades(df)
    assert len(out) == 2 and out["price_ticks"].tolist() == [6001, 6000]
    assert out["bid_ticks"].iloc[0] == 6000 and np.isnan(out["bid_ticks"].iloc[1])
    assert out["ask_ticks"].tolist() == [6001, 6001] and out["side"].tolist() == ["B", "N"]


def test_stats_frame_turns_sentinels_into_missing_values():
    df = pd.DataFrame({"ts_event": ts("2015-01-02 19:30", "2015-01-03 07:07"),
                       "ts_recv": ts("2015-01-02 19:30", "2015-01-03 07:07"),
                       "ts_ref": pd.Series(pd.to_datetime(["2015-01-02", None], utc=True)),
                       "instrument_id": [1, 1], "symbol": ["CL.v.0"] * 2, "stat_type": [3, 9],
                       "price": [52_690_000_000, UNDEF], "quantity": [d.UNDEF_STAT_QUANTITY, 311984],
                       "update_action": [1, 1], "stat_flags": [4, 0], "sequence": [5, 6]})
    out = C.stats_frame(df, "cl")
    assert out["price_fixed"].tolist()[0] == 52_690_000_000 and pd.isna(out["price_fixed"].iloc[1])
    assert pd.isna(out["quantity"].iloc[0]) and out["quantity"].iloc[1] == 311984
    assert out["ts_ref_utc"].isna().tolist() == [False, True] and (out["source"] == "cl").all()


def test_write_years_splits_by_utc_year_and_sorts(tmp_path, monkeypatch):
    monkeypatch.setattr(C, "OUT", tmp_path)
    f = pd.DataFrame({"ts_event_utc": ts("2016-01-01 00:30", "2015-12-31 23:30", "2015-06-01 12:00"), "x": [3, 2, 1]})
    assert C.write_years(f, "t") == {2015: 2, 2016: 1}
    y15 = pd.read_parquet(tmp_path / "t" / "year=2015" / "part.parquet")
    assert y15["x"].tolist() == [1, 2] and not list(tmp_path.rglob("*.partial"))


def test_tas_frame_keeps_trade_records_only():
    df = tas_df([0, 1], ["CLTN5", "CLTN5"], [7, 7])
    df.loc[1, "action"] = "C"  # a cancel or correction record never enters the tape
    out = C.tas_frame(df, spread_ids=set())
    assert len(out) == 1 and out["diff_ticks"].tolist() == [0]


def test_identical_fills_are_kept_not_deduplicated():
    df = tas_df([0, 0, 0], ["CLTN5"] * 3, [7, 7, 7])
    df["sequence"] = 5  # one aggressive order filled against three resting orders: same time, sequence, price, size
    assert len(C.tas_frame(df, spread_ids=set())) == 3


def test_conversion_refuses_raw_files_that_differ_from_the_purchase_manifest(tmp_path, monkeypatch):
    import json
    raw = tmp_path / "data" / "raw" / "stage1" / "tas_trades" / "JOB"
    raw.mkdir(parents=True)
    f = raw / "a.dbn.zst"
    f.write_bytes(b"bought")
    monkeypatch.setattr(C, "ROOT", tmp_path)
    monkeypatch.setattr(C, "RAW", tmp_path / "data" / "raw" / "stage1")
    monkeypatch.setattr(C, "rel", lambda path: str(path.relative_to(tmp_path)))
    manifest = tmp_path / "stage1.json"
    key = "data/raw/stage1/tas_trades/JOB/a.dbn.zst"
    manifest.write_text(json.dumps({"requests": {"tas_trades": {"files": {key: C.sha256(f)}}}}))
    monkeypatch.setattr(C, "MANIFEST", manifest)
    assert C.verify_raw_inputs() == 1
    f.write_bytes(b"changed")
    with pytest.raises(ValueError, match="changed"):
        C.verify_raw_inputs()
    f.write_bytes(b"bought")
    (raw / "b.dbn.zst").write_bytes(b"not bought")
    with pytest.raises(ValueError, match="extra"):
        C.verify_raw_inputs()
    (raw / "b.dbn.zst").unlink()
    f.unlink()  # a bought file that is gone
    with pytest.raises(ValueError, match=r"missing \['data/raw/stage1/tas_trades/JOB/a.dbn.zst'\]"):
        C.verify_raw_inputs()
