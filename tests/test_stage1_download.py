"""propfirm_data.stage1: the money rules of the stage-1 downloader (D010, Codex R016 Q5). Fake client, no network."""

import json
from datetime import date
from pathlib import Path
from types import SimpleNamespace

import pytest

from propfirm_data import stage1 as S


class FakeClient:
    """Records every call. `quote` maps a request to its cost; `fail_on` names request starts that raise.
    Each billed call asserts that its reservation is already on disk (R016: reserve before sending)."""

    def __init__(self, manifest: Path, quote=lambda p: 0.01, fail_on=(), fail_submit=()):
        self.manifest, self.quote, self.fail_on, self.fail_submit = manifest, quote, set(fail_on), set(fail_submit)
        self.calls = []
        self.records = lambda p: 5
        self.metadata = SimpleNamespace(get_cost=self._cost, get_record_count=lambda **p: self.records(p))
        self.timeseries = SimpleNamespace(get_range=self._range)
        self.batch = SimpleNamespace(submit_job=self._submit)

    def _on_disk(self, p):
        m = json.loads(self.manifest.read_text())
        mine = [r for r in m["requests"].values() if r.get("params") == {k: p[k] for k in r.get("params") or {}}
                and r.get("params") and r["status"] == "SUBMITTING"]
        assert mine, f"billed call without a SUBMITTING reservation on disk: {p}"
        return mine[0]

    def _cost(self, **p):
        self.calls.append(("cost", p["start"]))
        return self.quote(p)

    def _range(self, path, **p):
        self.calls.append(("range", p["start"]))
        rec = self._on_disk(p)
        assert rec["reserved"] > 0 or rec.get("covered_by"), "a request must be reserved or covered by its line"
        if p["start"] in self.fail_on:
            raise ConnectionError("network down")
        Path(path).write_text("rec\n" * 3)

    def _submit(self, **p):
        self.calls.append(("submit", p["schema"]))
        rec = self._on_disk(p)
        assert rec["reserved"] > 0
        if p["schema"] in self.fail_submit:
            raise TimeoutError("no answer")
        return {"id": f"JOB-{len(self.calls)}"}

    def billed(self):
        return [c for c in self.calls if c[0] in ("range", "submit")]


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setattr(S, "MANIFEST", tmp_path / "stage1.json")  # every function looks it up at call time
    monkeypatch.setattr(S, "RAW", tmp_path / "raw")
    monkeypatch.setattr(S, "SAMPLE_CHECK", tmp_path / "sample_check.json")
    monkeypatch.setattr(S, "dbn_records", lambda path: len(Path(path).read_text().splitlines()))
    return tmp_path


def fresh(env):
    m = S.load_manifest(env / "stage1.json")
    S.save_manifest(m)
    return m


# --- dates ------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("day, start, end", [
    (date(2015, 1, 5), "2015-01-05T19:20:00+00:00", "2015-01-05T19:35:00+00:00"),   # EST
    (date(2015, 7, 6), "2015-07-06T18:20:00+00:00", "2015-07-06T18:35:00+00:00"),   # EDT
    (date(2015, 3, 9), "2015-03-09T18:20:00+00:00", "2015-03-09T18:35:00+00:00"),   # first Monday of EDT
    (date(2015, 11, 2), "2015-11-02T19:20:00+00:00", "2015-11-02T19:35:00+00:00"),  # first Monday back on EST
])
def test_slice_bounds_follow_dst(day, start, end):
    assert S.slice_bounds(day) == (start, end)


def test_weekdays_cover_2015_16():
    d = S.weekdays()
    assert len(d) == 522 and d[0] == date(2015, 1, 1) and d[-1] == date(2016, 12, 30)
    assert all(x.weekday() < 5 for x in d)


def test_sample_is_14_to_15_edt():
    p = S.params("sample_cl")
    assert (p["start"], p["end"]) == ("2015-06-10T18:00:00+00:00", "2015-06-10T19:00:00+00:00")


# --- sample (line 1) ---------------------------------------------------------------------------------------

def test_quote_only_without_yes(env):
    m = fresh(env)
    c = FakeClient(env / "stage1.json")
    assert S.cmd_sample(c, m, yes=False, retry_uncertain=False) == S.OK
    assert c.billed() == [] and m["requests"] == {}


def test_sample_reserves_before_each_request_and_records_hashes(env):
    m = fresh(env)
    c = FakeClient(env / "stage1.json", quote=lambda p: 0.02)
    assert S.cmd_sample(c, m, yes=True, retry_uncertain=False) == S.OK
    assert len(c.billed()) == 2
    for n in ("sample_clt", "sample_cl"):
        r = m["requests"][n]
        assert r["status"] == "DONE" and r["records"] == 3 and len(r["sha256"]) == 64
        assert r["reserved"] == pytest.approx(0.02 * S.QUOTE_SAFETY_MARGIN) and r["quote"] == pytest.approx(0.02)
    assert S.cmd_sample(c, m, yes=True, retry_uncertain=False) == S.OK  # already bought: nothing billed again
    assert len(c.billed()) == 2


def test_over_cap_refused_before_any_billed_call(env):
    m = fresh(env)
    c = FakeClient(env / "stage1.json", quote=lambda p: 8.0)  # 2 x 8 x 1.1 > 15
    with pytest.raises(S.StopRun) as e:
        S.cmd_sample(c, m, yes=True, retry_uncertain=False)
    assert e.value.code == S.OVER_BUDGET and c.billed() == [] and m["requests"] == {}


def test_cap_counts_every_earlier_reservation(env):
    m = fresh(env)
    m["requests"]["old"] = {"reserved": 14.99, "status": "DONE", "params": None}
    with pytest.raises(S.StopRun) as e:
        S.cmd_sample(FakeClient(env / "stage1.json"), m, yes=True, retry_uncertain=False)
    assert e.value.code == S.OVER_BUDGET


# --- per-day line (line 5/6) -------------------------------------------------------------------------------

DAYS = [date(2015, 1, 5), date(2015, 1, 6), date(2015, 1, 7), date(2015, 1, 8)]


def with_line(env, name="cl_trades_1420"):
    m = fresh(env)
    m["requests"][f"{name}/line"] = {"reserved": 1.0, "status": "RESERVED", "params": None, "kind": "line_reservation"}
    S.save_manifest(m)
    return m


def test_failure_marks_uncertain_and_stops_the_run(env):
    m = with_line(env)
    bad = S.slice_bounds(DAYS[2])[0]
    c = FakeClient(env / "stage1.json", fail_on={bad})
    with pytest.raises(S.StopRun) as e:
        S.buy_slices(c, m, "cl_trades_1420", DAYS, retry_uncertain=False)
    assert e.value.code == S.STOPPED_UNCERTAIN
    st = {d: m["requests"].get(f"cl_trades_1420/{d}", {}).get("status") for d in DAYS}
    assert st == {DAYS[0]: "DONE", DAYS[1]: "DONE", DAYS[2]: "UNCERTAIN", DAYS[3]: None}
    assert [x for x in c.billed()] == [("range", S.slice_bounds(d)[0]) for d in DAYS[:3]]  # never retried
    on_disk = json.loads((env / "stage1.json").read_text())
    assert on_disk["requests"][f"cl_trades_1420/{DAYS[2]}"]["status"] == "UNCERTAIN"


def test_resume_needs_the_flag_then_reserves_again(env):
    m = with_line(env)
    bad = S.slice_bounds(DAYS[2])[0]
    c = FakeClient(env / "stage1.json", fail_on={bad})
    with pytest.raises(S.StopRun):
        S.buy_slices(c, m, "cl_trades_1420", DAYS, retry_uncertain=False)
    before = S.reserved_total(m)
    c2 = FakeClient(env / "stage1.json", quote=lambda p: 0.05)
    with pytest.raises(S.StopRun) as e:
        S.buy_slices(c2, m, "cl_trades_1420", DAYS, retry_uncertain=False)
    assert e.value.code == S.STOPPED_UNCERTAIN and c2.billed() == []
    assert S.buy_slices(c2, m, "cl_trades_1420", DAYS, retry_uncertain=True) == S.OK
    assert S.reserved_total(m) == pytest.approx(before + 0.05 * S.QUOTE_SAFETY_MARGIN)  # only the retry is new
    assert all(m["requests"][f"cl_trades_1420/{d}"]["status"] == "DONE" for d in DAYS)
    assert c2.billed() == [("range", S.slice_bounds(d)[0]) for d in DAYS[2:]]  # done days are skipped
    assert m["requests"][f"cl_trades_1420/{DAYS[2]}"]["attempts"] == 2


@pytest.mark.parametrize("left_as", ["final", "partial"])
def test_complete_file_is_recovered_without_new_spend(env, left_as):
    m = with_line(env)
    key = f"cl_trades_1420/{DAYS[0]}"
    m["requests"][key] = {"status": "SUBMITTING", "reserved": 0.0, "quote": 0.0, "attempts": 1, "kind": "range",
                          "params": S.slice_params("cl_trades_1420", DAYS[0]), "covered_by": "cl_trades_1420/line"}
    f = S.raw_path(key)
    f.parent.mkdir(parents=True)
    (f if left_as == "final" else f.with_name(f.name + ".partial")).write_text("rec\n" * 7)  # interrupt after download
    before = S.reserved_total(m)
    assert S.recover_free(m) == [key]
    c = FakeClient(env / "stage1.json")
    assert S.buy_slices(c, m, "cl_trades_1420", DAYS[:1], retry_uncertain=False) == S.OK  # no flag needed
    assert m["requests"][key]["status"] == "DONE" and m["requests"][key]["records"] == 7 and f.exists()
    assert c.calls == [] and S.reserved_total(m) == before


def test_resends_are_inside_the_single_upfront_check(env, monkeypatch):
    small_plan(monkeypatch, line_total=5.0)
    m = fresh(env)
    write_decision(env, "line5")
    c = FakeClient(env / "stage1.json", quote=lambda p: 1.0 if p["start"] == S.START else 1.25,
                   fail_submit={"ohlcv-1m"})
    with pytest.raises(S.StopRun):  # energy_bars fails: 6 x 1.1 + line 5.5 reserved so far
        S.cmd_buy(c, m, "trades", yes=True, retry_uncertain=False, owner_decision=None)
    assert m["requests"]["cl_trades_1420/line"]["status"] == "RESERVED"  # saved before the first submit
    c2 = FakeClient(env / "stage1.json", quote=lambda p: 3.0 if p["schema"] == "ohlcv-1m" else 0.1)
    with pytest.raises(S.StopRun) as e:  # resending energy (3.3) and brent (3.3) would pass $15
        S.cmd_buy(c2, m, "trades", yes=True, retry_uncertain=True, owner_decision=None)
    assert e.value.code == S.OVER_BUDGET and c2.billed() == []
    assert S.reserved_total(m) <= S.CAP_USD


def test_line_reservation_is_on_disk_before_the_first_billed_call(env, monkeypatch):
    small_plan(monkeypatch, line_total=0.4)
    m = fresh(env)
    write_decision(env, "line5")
    seen = []

    class Watching(FakeClient):
        def _submit(self, **p):
            seen.append("cl_trades_1420/line" in json.loads(self.manifest.read_text())["requests"])
            return super()._submit(**p)

    assert S.cmd_buy(Watching(env / "stage1.json", quote=lambda p: 0.1), m, "trades", yes=True,
                     retry_uncertain=False, owner_decision=None) == S.OK
    assert seen and all(seen)


def test_an_edited_manifest_cannot_raise_the_cap(env):
    m = fresh(env)
    m["cap_usd"] = 50.0
    assert S.cap(m) == S.CAP_USD
    with pytest.raises(S.StopRun) as e:
        S.cmd_sample(FakeClient(env / "stage1.json", quote=lambda p: 8.0), m, yes=True, retry_uncertain=False)
    assert e.value.code == S.OVER_BUDGET


# --- buy: decision gate, both-lines rule, whole-plan cap check --------------------------------------------

def write_decision(env, decision):
    (env / "sample_check.json").write_text(json.dumps({"decision": decision}))


def test_buy_needs_the_sample_decision(env):
    m = fresh(env)
    c = FakeClient(env / "stage1.json")
    with pytest.raises(S.StopRun) as e:
        S.cmd_buy(c, m, "trades", yes=True, retry_uncertain=False, owner_decision=None)
    assert e.value.code == S.REFUSED
    write_decision(env, "line6")
    with pytest.raises(S.StopRun) as e:
        S.cmd_buy(c, m, "trades", yes=True, retry_uncertain=False, owner_decision=None)
    assert e.value.code == S.REFUSED
    write_decision(env, "ask_owner")
    with pytest.raises(S.StopRun) as e:
        S.cmd_buy(c, m, "trades", yes=True, retry_uncertain=False, owner_decision=None)
    assert e.value.code == S.REFUSED and c.billed() == []


def test_never_both_line_5_and_line_6(env):
    m = with_line(env, "cl_trades_1420")
    write_decision(env, "ask_owner")
    with pytest.raises(S.StopRun) as e:
        S.cmd_buy(FakeClient(env / "stage1.json"), m, "mbp-1", yes=True, retry_uncertain=False,
                  owner_decision="line6")
    assert e.value.code == S.REFUSED


def small_plan(monkeypatch, line_total):
    monkeypatch.setattr(S, "weekdays", lambda *a: list(DAYS))
    monkeypatch.setattr(S, "D010_SLICE_QUOTES", {"cl_trades_1420": line_total, "cl_mbp1_1420": line_total})
    monkeypatch.setattr(S, "collect_batch", lambda c, m, n, manifest_path=None: m["requests"][n].update(
        status="DONE", files={}))


def test_buy_checks_the_whole_plan_before_the_first_billed_call(env, monkeypatch):
    small_plan(monkeypatch, line_total=8.0)
    m = fresh(env)
    write_decision(env, "line5")
    # the 6 batch items at 1.0 fit alone; with the 8.0 line reservation the worst case is (6 + 8) x 1.1 > 15
    c = FakeClient(env / "stage1.json", quote=lambda p: 1.0 if p["start"] == S.START else 2.0)
    with pytest.raises(S.StopRun) as e:
        S.cmd_buy(c, m, "trades", yes=True, retry_uncertain=False, owner_decision=None)
    assert e.value.code == S.OVER_BUDGET and c.billed() == [] and m["requests"] == {}


def test_buy_end_to_end_small(env, monkeypatch):
    small_plan(monkeypatch, line_total=0.4)
    m = fresh(env)
    write_decision(env, "line5")
    c = FakeClient(env / "stage1.json", quote=lambda p: 0.1)
    assert S.cmd_buy(c, m, "trades", yes=False, retry_uncertain=False, owner_decision=None) == S.OK
    assert c.billed() == [] and m["requests"] == {}  # quote only
    assert S.cmd_buy(c, m, "trades", yes=True, retry_uncertain=False, owner_decision=None) == S.OK
    assert [b[0] for b in c.billed()] == ["submit"] * len(S.BATCH_ITEMS) + ["range"] * len(DAYS)
    assert m["requests"]["cl_trades_1420/line"]["reserved"] == pytest.approx(0.4 * S.QUOTE_SAFETY_MARGIN)
    assert S.reserved_total(m) == pytest.approx((0.1 * len(S.BATCH_ITEMS) + 0.4) * S.QUOTE_SAFETY_MARGIN)
    assert all(m["requests"][n]["status"] == "DONE" for n in S.BATCH_ITEMS)


def test_slice_quote_far_from_d010_stops(env, monkeypatch):
    small_plan(monkeypatch, line_total=1.0)
    m = fresh(env)
    write_decision(env, "line5")
    c = FakeClient(env / "stage1.json", quote=lambda p: 0.1 if p["start"] == S.START else 0.5)  # 4 x 0.5 = 2.0
    with pytest.raises(S.StopRun) as e:
        S.cmd_buy(c, m, "trades", yes=True, retry_uncertain=False, owner_decision=None)
    assert e.value.code == S.QUOTE_OFF and c.billed() == []


def test_mismatched_params_are_detected(env):
    m = fresh(env)
    m["requests"]["sample_clt"] = {"params": {**S.params("sample_clt"), "start": "2015-06-11T18:00:00+00:00"},
                                   "reserved": 0.01, "status": "DONE"}
    m["requests"]["sample_cl"] = {"params": S.params("sample_cl"), "reserved": 0.01, "status": "DONE"}
    m["requests"]["mystery"] = {"params": {}, "reserved": 0.0, "status": "DONE"}
    assert sorted(S.mismatched(m)) == ["mystery", "sample_clt"]


def test_only_day_fetches_one_day_after_reserving_the_whole_line(env, monkeypatch):
    small_plan(monkeypatch, line_total=0.4)
    m = fresh(env)
    write_decision(env, "ask_owner")
    c = FakeClient(env / "stage1.json", quote=lambda p: 0.1)
    assert S.cmd_buy(c, m, "mbp-1", yes=True, retry_uncertain=False, owner_decision="line6",
                     only_day=DAYS[1]) == S.OK
    assert [b for b in c.billed() if b[0] == "range"] == [("range", S.slice_bounds(DAYS[1])[0])]
    assert m["requests"]["cl_mbp1_1420/line"]["reserved"] == pytest.approx(0.4 * S.QUOTE_SAFETY_MARGIN)
    with pytest.raises(S.StopRun):
        S.cmd_buy(c, m, "mbp-1", yes=True, retry_uncertain=False, owner_decision="line6", only_day=date(2015, 1, 3))


def test_failed_request_on_an_empty_range_is_done_not_uncertain(env):
    m = with_line(env)
    bad = S.slice_bounds(DAYS[1])[0]
    c = FakeClient(env / "stage1.json", fail_on={bad})
    c.records = lambda p: 0 if p["start"] == bad else 5  # a holiday: nothing in the range
    assert S.buy_slices(c, m, "cl_trades_1420", DAYS, retry_uncertain=False) == S.OK
    r = m["requests"][f"cl_trades_1420/{DAYS[1]}"]
    assert r["status"] == "DONE" and r["records"] == 0 and "no data" in r["note"]


def test_failed_batch_submit_is_uncertain_and_resubmitted_only_with_the_flag(env, monkeypatch):
    small_plan(monkeypatch, line_total=0.4)
    m = fresh(env)
    write_decision(env, "line5")
    c = FakeClient(env / "stage1.json", quote=lambda p: 0.1, fail_submit={"definition"})
    with pytest.raises(S.StopRun) as e:
        S.cmd_buy(c, m, "trades", yes=True, retry_uncertain=False, owner_decision=None)
    assert e.value.code == S.STOPPED_UNCERTAIN
    assert m["requests"]["clt_definitions"]["status"] == "UNCERTAIN"
    before = S.reserved_total(m)
    c2 = FakeClient(env / "stage1.json", quote=lambda p: 0.1)
    with pytest.raises(S.StopRun):
        S.cmd_buy(c2, m, "trades", yes=True, retry_uncertain=False, owner_decision=None)
    assert c2.calls == []  # nothing quoted or billed while a request may have been billed
    assert S.cmd_buy(c2, m, "trades", yes=True, retry_uncertain=True, owner_decision=None) == S.OK
    assert m["requests"]["clt_definitions"]["status"] == "DONE"
    assert m["requests"]["clt_definitions"]["attempts"] == 2
    new_spend = S.reserved_total(m) - before  # 4 batch jobs never sent + the resent one; the line was reserved in run 1
    assert new_spend == pytest.approx((4 * 0.1 + 0.1) * S.QUOTE_SAFETY_MARGIN)
