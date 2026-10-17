"""propfirm_research.data stage-1 loaders (D010; Codex R016 Q4): known-at times, CME day edges, period cuts, warm-up,
tokens, statistics vintages, runtime hash check, ledger rows. Synthetic parquet files only."""

from datetime import date

import numpy as np
import pandas as pd
import pytest

from propfirm_research import data, ledger, paths, periods, prereg


@pytest.fixture(autouse=True)
def env(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "LEDGER_FILE", tmp_path / "LEDGER.csv")
    monkeypatch.setattr(prereg, "_LIVE", {})
    monkeypatch.setattr(data, "STAGE1_DIR", tmp_path / "stage1")
    return tmp_path


def ts(*s):
    return pd.Series(pd.to_datetime(list(s), utc=True, format="ISO8601"))


def write(env, table, frame, col="ts_event_utc"):
    for y, g in frame.groupby(frame[col].dt.year):
        p = env / "stage1" / data.TABLES[table] / f"year={y}" / "part.parquet"
        p.parent.mkdir(parents=True, exist_ok=True)
        g.to_parquet(p, index=False)


def tas_rows(event, recv=None, side="B", size=5, symbol="CLTG7", spread=False):
    event = ts(*event)
    recv = event if recv is None else ts(*recv)
    n = len(event)
    return pd.DataFrame({"ts_event_utc": event, "ts_recv_utc": recv, "instrument_id": 7, "raw_symbol": symbol,
                         "is_spread": spread, "diff_ticks": 0, "size": size, "side": side, "action": "T",
                         "flags": 8, "sequence": np.arange(n)})


def stats_rows(rows):
    """rows: (ts_event, ts_recv, ts_ref, stat_type, price_usd or None, quantity or None, update_action, flags)"""
    f = pd.DataFrame(rows, columns=["ev", "recv", "ref", "stat_type", "px", "qty", "update_action", "stat_flags"])
    return pd.DataFrame({
        "ts_event_utc": pd.to_datetime(f["ev"], utc=True), "ts_recv_utc": pd.to_datetime(f["recv"], utc=True),
        "ts_ref_utc": pd.to_datetime(f["ref"], utc=True), "instrument_id": 9, "symbol": "CL.v.0", "source": "cl",
        "stat_type": f["stat_type"],
        "price_fixed": pd.array([None if pd.isna(p) else int(round(p * 1e9)) for p in f["px"]], dtype="Int64"),
        "quantity": pd.array([None if pd.isna(q) else int(q) for q in f["qty"]], dtype="Int64"),
        "update_action": f["update_action"],
        "stat_flags": f["stat_flags"], "sequence": np.arange(len(f))})


def energy_rows(event, symbol="HO.v.0"):
    event = ts(*event)
    n = len(event)
    return pd.DataFrame({"ts_event_utc": event, "continuous_symbol": symbol, "instrument_id": 11, "volume": 3,
                         "tick_fixed": 100_000, "open_ticks": np.arange(n) + 15000, "high_ticks": np.arange(n) + 15001,
                         "low_ticks": np.arange(n) + 14999, "close_ticks": np.arange(n) + 15000,
                         "open": 1.5, "high": 1.5, "low": 1.5, "close": 1.5})


def register(env, files, item_id="H999", period="validation"):
    code = env / "code.py"
    code.write_text("x = 1")
    spec = {"item_id": item_id, "claim": "c", "period": period, "null": "N2", "test": "combined",
            "alpha_one_sided": 0.01, "family": ["v1"], "multiplicity": "single", "signal": "s", "entry": "e",
            "exit": "x", "fee_usd": 4.02, "slip_ticks": 1.0, "stress_slip_ticks": 2.0, "contracts": 1,
            "min_signals": 100, "power_mde": 1.4, "seed": 1, "codex_review": "R999",
            "stopping_rule": prereg.STOPPING_RULE}
    return prereg.register(env / f"{item_id}-x", spec, [code], files)


def table_files(env, table):
    return sorted((env / "stage1" / data.TABLES[table]).rglob("*.parquet"))


# --- known-at and CME day edges ---------------------------------------------------------------------------

def test_trade_known_at_uses_ts_recv_and_equality_is_excluded(env):
    cutoff = pd.Timestamp("2016-06-01 18:35", tz="UTC")  # 14:35 EDT
    write(env, "tas", tas_rows(["2016-06-01 18:34:50", "2016-06-01 18:34:58", "2016-06-01 18:34:59"],
                               recv=["2016-06-01 18:34:59.9", "2016-06-01 18:35:00", "2016-06-01 18:35:00.5"]))
    t = data.load_trades("tas", "discovery", "H027", "t")
    assert data.known_before(t, cutoff.value).tolist() == [True, False, False]  # known, equality, late report


def test_received_before_event_is_rejected_and_logged(env):
    write(env, "tas", tas_rows(["2016-06-01 18:34:59"], recv=["2016-06-01 18:34:58"]))
    with pytest.raises(ValueError):
        data.load_trades("tas", "discovery", "H027", "t")
    assert ledger.read()["note"].str.startswith("failed").sum() == 1


@pytest.mark.parametrize("before, after", [("2016-01-12 22:59:59", "2016-01-12 23:00:00"),   # EST: 17:59:59 / 18:00
                                           ("2016-07-12 21:59:59", "2016-07-12 22:00:00")])  # EDT
def test_cme_day_boundary_every_loader(env, before, after):
    write(env, "tas", tas_rows([before, after]))
    write(env, "energy", energy_rows([before, after]))
    write(env, "statistics", stats_rows([(before, before, before, 3, 50.0, None, 1, 0),
                                         (after, after, after, 3, 50.0, None, 1, 0)]))
    d0 = periods.trading_day(ts(before))[0]
    assert data.load_trades("tas", "discovery", "H027", "t")["trading_day"].tolist() == [d0, d0 + 1]
    assert data.load_related("HO.v.0", "discovery", "H028", "t")["trading_day"].tolist() == [d0, d0 + 1]
    assert data.load_statistics("discovery", "S004", "t")["session_day"].tolist() == [d0, d0 + 1]


def test_period_cut_by_trading_day_not_utc_year(env):
    # 2016-12-31 18:30 ET is UTC 2016-12-31 23:30 but CME trading day 2017-01-01 (validation)
    write(env, "tas", tas_rows(["2016-12-30 19:00", "2016-12-31 23:30"]))
    t = data.load_trades("tas", "discovery", "H027", "t")
    assert len(t) == 1 and t["trading_day"].max() <= periods.bounds("discovery")[1]


def test_side_codes(env):
    write(env, "tas", tas_rows(["2016-06-01 18:00", "2016-06-01 18:01", "2016-06-01 18:02"], side=["B", "A", "N"]))
    assert data.load_trades("tas", "discovery", "H027", "t")["side"].tolist() == [1, -1, 0]


def test_related_filters_its_symbol_and_keeps_the_bar_layout(env):
    write(env, "energy", pd.concat([energy_rows(["2016-06-01 18:25", "2016-06-01 18:34"]),
                                    energy_rows(["2016-06-01 18:25"], symbol="RB.v.0")]))
    ho = data.load_related("HO.v.0", "discovery", "H028", "t")
    assert len(ho) == 2 and ho["mod"].tolist() == [14 * 60 + 25, 14 * 60 + 34]
    assert {"contract", "open", "close", "trading_day", "tmin"} <= set(ho.columns)
    with pytest.raises(ValueError):
        data.load_related("NG.v.0", "discovery", "H028", "t")


# --- statistics vintages -----------------------------------------------------------------------------------

def test_statistics_asof_ignores_later_revisions_and_honours_deletes(env):
    session = "2016-06-01 04:00"  # ts_ref of the 2016-06-01 session
    write(env, "statistics", stats_rows([
        ("2016-06-01 18:31", "2016-06-01 18:31", session, 3, 49.10, None, 1, 0),   # preliminary at 14:31 ET
        ("2016-06-02 00:30", "2016-06-02 00:30", session, 3, 49.12, None, 1, 1),   # final, evening
        ("2016-06-01 18:40", "2016-06-01 18:40", session, 6, None, 900, 1, 0),     # cleared volume ...
        ("2016-06-01 18:50", "2016-06-01 18:50", session, 6, None, 900, 2, 0),     # ... then deleted
    ]))
    st = data.load_statistics("discovery", "S004", "t")
    at_1435 = data.stats_asof(st, pd.Timestamp("2016-06-01 18:35", tz="UTC").value)
    assert at_1435["price"].tolist() == pytest.approx([49.10])
    later = data.stats_asof(st, pd.Timestamp("2016-06-02 12:00", tz="UTC").value)
    assert later.loc[later["stat_type"] == 3, "price"].tolist() == pytest.approx([49.12])
    assert (later["stat_type"] == 6).sum() == 0  # deleted


def test_statistics_session_from_ts_ref_and_open_interest_timing(env):
    # open interest for the 2016-06-01 session, published the next morning
    write(env, "statistics", stats_rows([("2016-06-02 13:00", "2016-06-02 13:00", "2016-06-01 04:00", 9, None, 5000, 1, 0)]))
    st = data.load_statistics("discovery", "S004", "t")
    d = periods.epoch_day(date(2016, 6, 1))
    assert st["session_day"].tolist() == [d] and st["known_day"].tolist() == [d + 1]
    assert len(data.stats_asof(st, pd.Timestamp("2016-06-01 18:35", tz="UTC").value)) == 0
    assert len(data.stats_asof(st, pd.Timestamp("2016-06-02 18:35", tz="UTC").value)) == 1


def test_statistics_published_after_the_period_are_cut(env):
    write(env, "statistics", stats_rows([("2017-01-03 13:00", "2017-01-03 13:00", "2016-12-30 05:00", 9, None, 1, 1, 0),
                                         ("2016-12-30 20:00", "2016-12-30 20:00", "2016-12-30 05:00", 3, 53.7, None, 1, 0)]))
    st = data.load_statistics("discovery", "S004", "t")
    assert st["stat_type"].tolist() == [3]  # the open interest published in 2017 is not discovery data


# --- tokens, warm-up, runtime hashes, ledger --------------------------------------------------------------

def test_protected_periods_need_a_matching_live_token_for_every_loader(env):
    write(env, "tas", tas_rows(["2016-12-29 19:00", "2017-01-04 19:00"]))
    write(env, "energy", energy_rows(["2017-01-04 19:00"]))
    write(env, "statistics", stats_rows([("2017-01-04 20:00", "2017-01-04 20:00", "2017-01-04 05:00", 3, 53.0, None, 1, 0)]))
    calls = [lambda **k: data.load_trades("tas", "validation", "H999", "t", **k),
             lambda **k: data.load_statistics("validation", "H999", "t", **k),
             lambda **k: data.load_related("HO.v.0", "validation", "H999", "t", **k)]
    for call in calls:
        with pytest.raises(data.FirewallError):
            call()
    files = table_files(env, "tas") + table_files(env, "energy") + table_files(env, "statistics")
    p = register(env, files)
    with prereg.open_run(p) as run:
        for call in calls:
            assert len(call(run=run)) >= 1
        with pytest.raises(data.FirewallError):
            data.load_trades("tas", "validation", "H001", "borrowed", run=run)
        with pytest.raises(data.FirewallError):
            data.load_trades("tas", "holdout", "H999", "wrong period", run=run)
    with pytest.raises(data.FirewallError):
        data.load_trades("tas", "validation", "H999", "closed", run=run)


def test_warmup_reaches_back_only(env):
    write(env, "tas", tas_rows(["2016-12-28 19:00", "2017-01-04 19:00"]))
    p = register(env, table_files(env, "tas"))
    with prereg.open_run(p) as run:
        t = data.load_trades("tas", "validation", "H999", "t", run=run, warmup_days=5)
        assert t["trading_day"].min() < periods.bounds("validation")[0]
    with pytest.raises(data.FirewallError):
        data.load_trades("tas", "discovery", "S004", "t", warmup_days=-1)


def test_runtime_hash_mismatch_aborts_before_rows_are_returned(env):
    write(env, "tas", tas_rows(["2017-01-04 19:00"]))
    p = register(env, table_files(env, "tas"))
    with prereg.open_run(p) as run:
        assert len(data.load_trades("tas", "validation", "H999", "t", run=run)) == 1
        write(env, "tas", tas_rows(["2017-01-04 19:00", "2017-01-05 19:00"]))  # same file, new content
        with pytest.raises(data.FirewallError):
            data.load_trades("tas", "validation", "H999", "t", run=run)
        write(env, "tas", tas_rows(["2018-01-04 19:00"]))  # a file the prereg never listed
        with pytest.raises(data.FirewallError):
            data.load_trades("tas", "validation", "H999", "t", run=run)


def test_every_attempt_has_an_intent_and_one_terminal_row(env):
    with pytest.raises(FileNotFoundError):
        data.load_trades("tas", "discovery", "S004", "nothing converted yet")
    write(env, "tas", tas_rows(["2016-06-01 18:00"]))
    data.load_trades("tas", "discovery", "S004", "ok")
    with pytest.raises(data.FirewallError):
        data.load_trades("tas", "validation", "S004", "no token")
    rows = ledger.read()
    kinds = rows["note"].str.extract(r"^(\w+)")[0].tolist()
    assert kinds == ["intent", "failed", "intent", "done", "intent", "refused"]
    done = rows[rows["note"].str.startswith("done")]
    assert len(done["data_sha256"].iloc[0]) == 64


def test_cl_mbp1_trades_carry_contract_price_and_book(env):
    ev = ts("2016-06-01 18:26:00", "2016-06-01 18:26:01")
    write(env, "cl_mbp1", pd.DataFrame({
        "ts_event_utc": ev, "ts_recv_utc": ev, "instrument_id": 5, "raw_symbol": "CLN6",
        "expiration": pd.Timestamp("2016-06-21 18:30", tz="UTC"), "price_ticks": [4900, 4899], "size": [3, 1],
        "side": ["B", "N"], "flags": 8, "sequence": [1, 2], "bid_ticks": [4899.0, 4899.0],
        "ask_ticks": [4900.0, np.nan]}))
    t = data.load_trades("cl_mbp1", "discovery", "H027", "t")
    assert t["contract"].tolist() == ["CLN6@2016-06"] * 2 and t["side"].tolist() == [1, 0]
    assert t["price"].tolist() == [4900, 4899] and t["bid"].tolist() == [4899, 4899] and np.isnan(t["ask"].iloc[1])
    assert t["mod"].tolist() == [14 * 60 + 26] * 2
