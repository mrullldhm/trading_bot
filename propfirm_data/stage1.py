"""Stage-1 settlement-flow data for decision D010 (2015-16, hard cap $15): quote, sample, buy.

Lines (research/decisions/D010-stage1-data-purchase.md):
  1  sample: CLT and CL.v.0 trades, 2015-06-10 14:00-15:00 ET           (2 timeseries requests)
  2  CLT (trade-at-settlement) trades, every instrument                  (batch)
  3  CLT definitions                                                     (batch)
  4  statistics: CL.v.0 + CL.v.1, and CLT                                (2 batch jobs)
  5  CL.v.0 trades 14:20-14:35 ET, every weekday, if the sample has the side   (one request per day)
  6  CL.v.0 mbp-1 14:20-14:35 ET, every weekday, only instead of line 5         (one request per day)
  7  RB.v.0 + HO.v.0 1-minute bars;  8  BZ.v.0 1-minute bars           (batch)

Money rules (Codex R016 Q5):
- every billed request is reserved in the manifest (params, quote, quote x margin, status SUBMITTING) before it is
  sent; the cap counts every reservation ever made, whatever its status, so nothing can sneak past it;
- a billed request is never retried automatically: a failure marks it UNCERTAIN and stops the run; a resume with
  --retry-uncertain reserves it again (fresh quote x margin) and retries only while the cap still holds;
- per-day files go to .partial, are read back and hashed, then renamed and marked DONE;
- a per-day line is reserved as a whole before its first request: max(D010 quote, a 20-day sample quote scaled
  to every day) x margin; a sample more than 20% away from the D010 quote stops the run;
- `buy` checks the worst case of everything still to buy against the cap before the first billed call.

Usage:
    python -m propfirm_data.stage1 quote                         # free: quote every item
    python -m propfirm_data.stage1 sample --yes                  # line 1 (spends ~$0.04)
    python -m propfirm_data.stage1 check                         # line-1 format check -> sample_check.json
    python -m propfirm_data.stage1 buy --yes --slices trades     # lines 2-4, 7, 8 + 5 (--slices mbp-1: line 6)
    python -m propfirm_data.stage1 convert                       # DBN -> parquet under data/processed/stage1/
"""

import argparse
import json
import sys
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from . import download
from .budget import BudgetError, check_budget
from .config import DATASET, MANIFEST_FILE, PROCESSED_DIR, QUOTE_SAFETY_MARGIN, RAW_DIR, ROOT

CAP_USD = 15.0
START, END = "2015-01-01", "2017-01-01"  # end exclusive: trading days 2015-01-02 .. 2016-12-30
SAMPLE_START, SAMPLE_END = "2015-06-10T18:00:00+00:00", "2015-06-10T19:00:00+00:00"  # 14:00-15:00 EDT
SLICE_ET = ((14, 20), (14, 35))
ET = ZoneInfo("America/New_York")
D010_SLICE_QUOTES = {"cl_trades_1420": 7.60, "cl_mbp1_1420": 4.24}  # line totals quoted for D010
SAMPLE_DAYS = 20
QUOTE_TOLERANCE = 0.20
MANIFEST = MANIFEST_FILE.with_name("stage1.json")
RAW = RAW_DIR / "stage1"
OUT = PROCESSED_DIR / "stage1"
WORK = ROOT / "data" / "research" / "stage1"  # logs, sample_check.json
SAMPLE_CHECK = WORK / "sample_check.json"

ITEMS = {
    "sample_clt": dict(line=1, mode="range", schema="trades", symbols=["CLT.FUT"], stype_in="parent",
                       start=SAMPLE_START, end=SAMPLE_END),
    "sample_cl": dict(line=1, mode="range", schema="trades", symbols=["CL.v.0"], stype_in="continuous",
                      start=SAMPLE_START, end=SAMPLE_END),
    "tas_trades": dict(line=2, mode="batch", schema="trades", symbols=["CLT.FUT"], stype_in="parent",
                       split_duration="month"),
    "clt_definitions": dict(line=3, mode="batch", schema="definition", symbols=["CLT.FUT"], stype_in="parent",
                            split_duration="none"),
    "statistics_cl": dict(line=4, mode="batch", schema="statistics", symbols=["CL.v.0", "CL.v.1"],
                          stype_in="continuous", split_duration="none"),
    "statistics_clt": dict(line=4, mode="batch", schema="statistics", symbols=["CLT.FUT"], stype_in="parent",
                           split_duration="none"),
    "cl_trades_1420": dict(line=5, mode="slices", schema="trades", symbols=["CL.v.0"], stype_in="continuous"),
    "cl_mbp1_1420": dict(line=6, mode="slices", schema="mbp-1", symbols=["CL.v.0"], stype_in="continuous"),
    "energy_bars": dict(line=7, mode="batch", schema="ohlcv-1m", symbols=["RB.v.0", "HO.v.0"],
                        stype_in="continuous", split_duration="month"),
    "brent_bars": dict(line=8, mode="batch", schema="ohlcv-1m", symbols=["BZ.v.0"], stype_in="continuous",
                       split_duration="month"),
}
BATCH_ITEMS = [n for n, it in ITEMS.items() if it["mode"] == "batch"]
SLICE_FOR = {"trades": "cl_trades_1420", "mbp-1": "cl_mbp1_1420"}
DECISION_FOR = {"cl_trades_1420": "line5", "cl_mbp1_1420": "line6"}

# exit codes
OK, OVER_BUDGET, STOPPED_UNCERTAIN, MISMATCH, REFUSED, QUOTE_OFF = 0, 2, 3, 4, 5, 6


class StopRun(Exception):
    def __init__(self, code: int, message: str):
        super().__init__(message)
        self.code = code


def say(msg: str) -> None:
    print(msg, flush=True)


# --- request parameters ------------------------------------------------------------------------------

def params(name: str, start: str | None = None, end: str | None = None) -> dict:
    it = ITEMS[name]
    return {"dataset": DATASET, "symbols": list(it["symbols"]), "stype_in": it["stype_in"],
            "schema": it["schema"], "start": start or it.get("start", START), "end": end or it.get("end", END)}


def weekdays(start: str = START, end: str = END) -> list[date]:
    """Every Monday-Friday in [start, end); holidays included (an empty day costs nothing)."""
    d, stop, out = date.fromisoformat(start), date.fromisoformat(end), []
    while d < stop:
        if d.weekday() < 5:
            out.append(d)
        d += timedelta(days=1)
    return out


def slice_bounds(day: date) -> tuple[str, str]:
    """14:20-14:35 ET of `day` as UTC ISO strings (Databento's end is exclusive, so 14:35:00 is not included)."""
    (h0, m0), (h1, m1) = SLICE_ET
    a = datetime(day.year, day.month, day.day, h0, m0, tzinfo=ET).astimezone(timezone.utc)
    b = datetime(day.year, day.month, day.day, h1, m1, tzinfo=ET).astimezone(timezone.utc)
    return a.isoformat(), b.isoformat()


def slice_params(name: str, day: date) -> dict:
    return params(name, *slice_bounds(day))


# --- manifest: every reservation, never forgotten ------------------------------------------------------

SUBMITTING, SUBMITTED, DONE, UNCERTAIN, RESERVED = "SUBMITTING", "SUBMITTED", "DONE", "UNCERTAIN", "RESERVED"
OPEN = (SUBMITTING, UNCERTAIN)  # may have been billed, outcome unknown
sha256 = download.sha256


def load_manifest(path: Path | None = None) -> dict:
    path = path or MANIFEST  # looked up at call time, so tests can point it elsewhere
    if path.exists():
        return json.loads(path.read_text())
    return {"cap_usd": CAP_USD, "requests": {}}


def save_manifest(m: dict, path: Path | None = None) -> None:
    path = path or MANIFEST
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".partial")
    tmp.write_text(json.dumps(m, indent=1))
    tmp.replace(path)  # atomic


def reserved_total(m: dict) -> float:
    return sum(r["reserved"] for r in m["requests"].values())


def cap(m: dict) -> float:
    """D010's hard cap; an edited manifest can lower it, never raise it."""
    return min(CAP_USD, m["cap_usd"])


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def rel(path: Path) -> str:
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return str(path)


def expected_params(key: str) -> dict | None:
    """The params the current code would send for a manifest key (None for line reservations)."""
    name, _, rest = key.partition("/")
    if name not in ITEMS:
        return None
    if ITEMS[name]["mode"] == "slices":
        return None if rest == "line" else slice_params(name, date.fromisoformat(rest))
    return params(name)


def mismatched(m: dict) -> list[str]:
    """Saved requests whose params differ from what the code would send now (code edited after paying)."""
    bad = []
    for key, r in m["requests"].items():
        exp = expected_params(key)
        if key.partition("/")[0] not in ITEMS or (exp is not None and r.get("params") != exp):
            bad.append(key)
    return bad


def guard(m: dict, new_quotes: dict[str, float]) -> float:
    try:
        return check_budget(new_quotes, reserved_total(m), cap(m))
    except BudgetError as exc:
        raise StopRun(OVER_BUDGET, f"over the cap: {exc}") from None


def reserve(m: dict, key: str, base: dict, quote: float, amount: float, manifest_path: Path | None = None,
            **fields) -> dict:
    """Add a reservation to `key` and mark it SUBMITTING on disk. Call it before the billed request leaves."""
    rec = m["requests"].get(key) or {**base, "quote": 0.0, "reserved": 0.0, "attempts": 0}
    rec.update(status=SUBMITTING, submitted_at=now(), **fields)
    rec["quote"] += quote
    rec["reserved"] += amount
    rec["attempts"] += 1
    m["requests"][key] = rec
    save_manifest(m, manifest_path)
    return rec


# --- one billed timeseries request (the sample, or one day of a per-day line) ---------------------------

def raw_path(key: str) -> Path:
    name, _, rest = key.partition("/")
    return RAW / name / f"{rest or name}.dbn.zst"


def dbn_records(path: Path) -> int:
    """Read the file back (proves it is a complete DBN stream); returns the number of records."""
    import databento as db
    return sum(1 for _ in db.DBNStore.from_file(path))


def mark_done(rec: dict, final: Path, n: int, **fields) -> None:
    rec.update(status=DONE, done_at=now(), records=n, bytes=final.stat().st_size, sha256=sha256(final),
               file=rel(final), **fields)


def fetch_range(client, m: dict, key: str, p: dict, quote: float, amount: float, line: int,
                covered_by: str | None = None, manifest_path: Path | None = None) -> dict:
    """Reserve, send ONE billed request, verify the file, mark DONE. Never retried here."""
    rec = reserve(m, key, {"line": line, "kind": "range", "params": p}, quote, amount, manifest_path,
                  covered_by=covered_by)
    final = raw_path(key)
    partial = final.with_name(final.name + ".partial")
    final.parent.mkdir(parents=True, exist_ok=True)
    try:
        client.timeseries.get_range(**p, path=partial)
    except Exception as exc:  # noqa: BLE001 - any failure may still have been billed
        partial.unlink(missing_ok=True)
        if empty_range(client, p):  # e.g. a CME holiday: no records, so nothing to bill
            rec.update(status=DONE, done_at=now(), records=0, bytes=0, sha256=None, file=None,
                       note=f"no data in this range ({type(exc).__name__})")
            save_manifest(m, manifest_path)
            return rec
        rec.update(status=UNCERTAIN, error=f"{type(exc).__name__}: {exc}"[:300])
        save_manifest(m, manifest_path)
        raise StopRun(STOPPED_UNCERTAIN, f"{key}: request failed ({type(exc).__name__}); marked UNCERTAIN. "
                                         "Check the Databento portal, then resume with --retry-uncertain.") from None
    n = dbn_records(partial)
    partial.replace(final)
    mark_done(rec, final, n)
    save_manifest(m, manifest_path)
    return rec


def empty_range(client, p: dict) -> bool:
    """True only if the free record count says the range holds no data at all."""
    try:
        return download.retry(lambda: client.metadata.get_record_count(**p)) == 0
    except Exception:  # noqa: BLE001 - unknown means not empty
        return False


def recover_free(m: dict, manifest_path: Path | None = None) -> list[str]:
    """Open requests whose complete file is on disk (final, or a .partial left by an interrupt) become DONE with
    no new spend. Runs before the uncertainty stop. Returns the recovered keys."""
    recovered = []
    for key, rec in m["requests"].items():
        if rec["status"] not in OPEN or rec.get("kind") != "range":
            continue
        final = raw_path(key)
        partial = final.with_name(final.name + ".partial")
        for candidate in (final, partial):
            if not candidate.exists():
                continue
            try:
                n = dbn_records(candidate)
            except Exception:  # noqa: BLE001 - a broken file proves nothing; it is fetched again later
                candidate.unlink()
                continue
            if candidate is partial:
                partial.replace(final)
            mark_done(rec, final, n, note="recovered from a complete file")
            recovered.append(key)
            break
    if recovered:
        save_manifest(m, manifest_path)
    return recovered


def stop_if_uncertain(m: dict, retry_uncertain: bool) -> None:
    """A request that may have been billed blocks every new billed call until it is dealt with (R016 Q5)."""
    open_keys = [k for k, r in m["requests"].items() if r["status"] in OPEN]
    if open_keys and not retry_uncertain:
        raise StopRun(STOPPED_UNCERTAIN, f"{len(open_keys)} request(s) may have been billed: {open_keys[:3]}. Check "
                                         "the Databento portal, then run again with --retry-uncertain.")


def resend_cost(client, m: dict, key: str, p: dict) -> tuple[float, float]:
    """(fresh quote, reservation) to send an open request once more, inside the cap."""
    quote = download.retry(lambda: client.metadata.get_cost(**p))
    guard(m, {key: quote})
    return quote, quote * QUOTE_SAFETY_MARGIN


# --- batch jobs: billed once at submit, files re-downloadable for free ----------------------------------

def submit_batch(client, m: dict, name: str, quote: float, manifest_path: Path | None = None) -> str:
    p = params(name)
    rec = reserve(m, name, {"line": ITEMS[name]["line"], "kind": "batch", "params": p}, quote,
                  quote * QUOTE_SAFETY_MARGIN, manifest_path, job_id=None)
    try:
        job = client.batch.submit_job(**p, encoding="dbn", compression="zstd",
                                      split_duration=ITEMS[name]["split_duration"], stype_out="instrument_id")
    except Exception as exc:  # noqa: BLE001
        rec.update(status=UNCERTAIN, error=f"{type(exc).__name__}: {exc}"[:300])
        save_manifest(m, manifest_path)
        raise StopRun(STOPPED_UNCERTAIN, f"{name}: submit failed ({type(exc).__name__}); marked UNCERTAIN. Check "
                                         "https://databento.com/portal/download-center before --retry-uncertain.")
    rec.update(status=SUBMITTED, job_id=job["id"])
    save_manifest(m, manifest_path)
    say(f"  submitted {name}: job {job['id']}")
    return job["id"]


def collect_batch(client, m: dict, name: str, manifest_path: Path | None = None) -> None:
    """Wait for a submitted job, download its files (free, hash-checked), record their hashes."""
    rec = m["requests"][name]
    download.wait_until_done(client, rec["job_id"])
    download.download_files(client, f"stage1/{name}", rec["job_id"])
    folder = RAW / name / rec["job_id"]
    rec.update(status=DONE, done_at=now(),
               files={rel(f): sha256(f) for f in sorted(folder.rglob("*")) if f.is_file()})
    save_manifest(m, manifest_path)


# --- commands --------------------------------------------------------------------------------------------

def sample_days(days: list[date], k: int = SAMPLE_DAYS) -> list[date]:
    step = max(1, len(days) // k)
    return days[step // 2::step][:k]


def slice_line_quote(client, name: str, days: list[date]) -> tuple[float, float]:
    """(reservation basis, scaled sample quote): a free 20-day sample scaled to every day vs the D010 quote."""
    picks = sample_days(days)
    t0 = time.time()
    quotes = []
    for i, d in enumerate(picks, 1):
        quotes.append(download.retry(lambda d=d: client.metadata.get_cost(**slice_params(name, d))))
        say(f"  sample quote {i}/{len(picks)} {d}: ${quotes[-1]:.4f} ({time.time() - t0:.0f} s)")
    scaled = sum(quotes) / len(picks) * len(days)
    d010 = D010_SLICE_QUOTES[name]
    if abs(scaled - d010) / d010 > QUOTE_TOLERANCE:
        raise StopRun(QUOTE_OFF, f"{name}: sample quote scaled to {len(days)} days is ${scaled:.2f}, more than "
                                 f"{QUOTE_TOLERANCE:.0%} away from the D010 quote ${d010:.2f}; ask the owner")
    return max(scaled, d010), scaled


def cmd_quote(client, m: dict) -> int:
    total = 0.0
    for name in [*BATCH_ITEMS, "sample_clt", "sample_cl"]:
        q = download.retry(lambda name=name: client.metadata.get_cost(**params(name)))
        total += q
        say(f"  line {ITEMS[name]['line']} {name:16s} ${q:8.4f}")
    say(f"  total without per-day lines ${total:.2f}; per-day lines (D010): "
        + ", ".join(f"{k} ${v:.2f}" for k, v in D010_SLICE_QUOTES.items()))
    say(f"  already reserved ${reserved_total(m):.4f} of the ${cap(m):.2f} cap")
    return OK


def cmd_sample(client, m: dict, yes: bool, retry_uncertain: bool) -> int:
    recover_free(m)
    stop_if_uncertain(m, retry_uncertain)
    names = ["sample_clt", "sample_cl"]
    todo = [n for n in names if m["requests"].get(n, {}).get("status") != DONE]
    if not todo:
        say("sample already bought")
        return OK
    quotes = {n: download.retry(lambda n=n: client.metadata.get_cost(**params(n))) for n in todo}
    worst = guard(m, quotes)
    say(f"sample quote ${sum(quotes.values()):.4f}; worst case after it ${worst:.4f} (cap ${cap(m):.2f})")
    if not yes:
        say("quote only; run again with --yes to buy")
        return OK
    for n in todo:
        rec = fetch_range(client, m, n, params(n), quotes[n], quotes[n] * QUOTE_SAFETY_MARGIN, line=1)
        say(f"  {n}: {rec['records']:,} records, sha256 {(rec['sha256'] or '')[:12]}")
    return OK


def sample_decision() -> str:
    if not SAMPLE_CHECK.exists():
        raise StopRun(REFUSED, f"no {rel(SAMPLE_CHECK)}: buy and check the line-1 sample first")
    return json.loads(SAMPLE_CHECK.read_text())["decision"]


def cmd_buy(client, m: dict, slices: str, yes: bool, retry_uncertain: bool, owner_decision: str | None,
            only_day: date | None = None) -> int:
    recover_free(m)
    stop_if_uncertain(m, retry_uncertain)
    line_name = SLICE_FOR[slices]
    other = next(n for n in SLICE_FOR.values() if n != line_name)
    if any(k.startswith(other + "/") for k in m["requests"]):
        raise StopRun(REFUSED, f"{other} was already reserved: never buy both line 5 and line 6 (D010)")
    decision = sample_decision()
    wanted = DECISION_FOR[line_name]
    if decision == "ask_owner":
        if owner_decision != wanted:
            raise StopRun(REFUSED, "the sample check says ask_owner: pass --owner-decision "
                                   f"{wanted} only after the owner chose it")
    elif decision != wanted:
        raise StopRun(REFUSED, f"the sample check selected {decision}, not {wanted} ({line_name})")

    days = weekdays()
    if only_day is not None and only_day not in days:
        raise StopRun(REFUSED, f"{only_day} is not a weekday of the line")
    to_send = [n for n in BATCH_ITEMS if n not in m["requests"] or m["requests"][n]["status"] in OPEN]
    new_quotes = {n: download.retry(lambda n=n: client.metadata.get_cost(**params(n))) for n in to_send}
    line_key = f"{line_name}/line"
    scaled = None
    if line_key not in m["requests"]:
        basis, scaled = slice_line_quote(client, line_name, days)
        new_quotes[line_key] = basis
    worst = guard(m, new_quotes)  # one check over everything still to buy, resends included
    say("to buy: " + ", ".join(f"{k} ${v:.3f}" for k, v in new_quotes.items()))
    say(f"worst case incl. x{QUOTE_SAFETY_MARGIN} margin: ${worst:.3f} of the ${cap(m):.2f} cap")
    if not yes:
        say("quote only; run again with --yes to buy")
        return OK

    if line_key not in m["requests"]:  # on disk before the first billed call
        m["requests"][line_key] = {"line": ITEMS[line_name]["line"], "kind": "line_reservation", "params": None,
                                   "quote": new_quotes[line_key], "sample_quote_scaled": scaled,
                                   "reserved": new_quotes[line_key] * QUOTE_SAFETY_MARGIN, "status": RESERVED,
                                   "days": len(days), "attempts": 0, "submitted_at": now()}
        save_manifest(m)
    for n in to_send:
        submit_batch(client, m, n, new_quotes[n])
    for n in BATCH_ITEMS:
        rec = m["requests"][n]
        if rec["status"] == SUBMITTED:
            collect_batch(client, m, n)
            say(f"  {n}: {len(rec['files'])} files")
    if only_day is not None:  # check one day of the line before buying the rest
        days = [only_day]
    return buy_slices(client, m, line_name, days, retry_uncertain)


def buy_slices(client, m: dict, name: str, days: list[date], retry_uncertain: bool,
               manifest_path: Path | None = None) -> int:
    line_key = f"{name}/line"
    t0 = time.time()
    done_before = sum(1 for d in days if m["requests"].get(f"{name}/{d}", {}).get("status") == DONE)
    fetched = 0
    for i, d in enumerate(days, 1):
        key = f"{name}/{d}"
        rec = m["requests"].get(key)
        if rec and rec["status"] == DONE:
            continue
        p = slice_params(name, d)
        if rec is None:
            cost, covered = (0.0, 0.0), line_key  # covered by the whole-line reservation
        else:
            stop_if_uncertain({"requests": {key: rec}}, retry_uncertain)
            cost, covered = resend_cost(client, m, key, p), None
        rec = fetch_range(client, m, key, p, *cost, line=ITEMS[name]["line"], covered_by=covered,
                          manifest_path=manifest_path)
        fetched += 1
        rate = (time.time() - t0) / fetched
        left = sum(1 for x in days[i:] if m["requests"].get(f"{name}/{x}", {}).get("status") != DONE)
        say(f"  {name} {d} [{done_before + fetched}/{len(days)}] {rec['records']:,} records, "
            f"{rec['bytes'] / 1e6:.2f} MB; {rate:.1f} s/request, ~{left * rate / 60:.0f} min left; "
            f"reserved ${reserved_total(m):.3f}")
    say(f"{name}: {len(days)} requested day(s) DONE; reserved ${reserved_total(m):.3f} of ${cap(m):.2f}")
    return OK


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("command", choices=["quote", "sample", "check", "buy", "convert"])
    ap.add_argument("--yes", action="store_true", help="actually spend (default: quote only)")
    ap.add_argument("--slices", choices=sorted(SLICE_FOR), help="buy: line 5 (trades) or line 6 (mbp-1)")
    ap.add_argument("--retry-uncertain", action="store_true", help="reserve and resend requests left UNCERTAIN")
    ap.add_argument("--owner-decision", choices=["line5", "line6"],
                    help="only when the sample check said ask_owner, after the owner chose")
    ap.add_argument("--only-day", type=date.fromisoformat, help="buy: fetch only this day of the per-day line")
    args = ap.parse_args(argv)

    if args.command in ("check", "convert"):
        from . import stage1_convert  # data handling lives apart from the money code
        return stage1_convert.main(args.command)

    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env")
    import databento as db
    client = db.Historical()  # reads DATABENTO_API_KEY; never printed

    with download.single_instance():  # same lock as the bar downloader: one paid script at a time
        m = load_manifest()
        if bad := mismatched(m):
            say(f"ABORTED: saved requests {bad[:5]} do not match the current code (edited after paying?)")
            return MISMATCH
        try:
            if args.command == "quote":
                return cmd_quote(client, m)
            if args.command == "sample":
                return cmd_sample(client, m, args.yes, args.retry_uncertain)
            if not args.slices:
                ap.error("buy needs --slices trades|mbp-1")
            return cmd_buy(client, m, args.slices, args.yes, args.retry_uncertain, args.owner_decision,
                           args.only_day)
        except StopRun as stop:
            say(f"STOPPED: {stop}")
            return stop.code


if __name__ == "__main__":
    sys.exit(main())
