"""Download CL history from Databento using batch jobs.

Why batch jobs: each job is billed ONCE when submitted. Its files can then be
re-downloaded for free for 30 days, so a flaky internet connection never
costs extra. (Streaming downloads are billed again on every retry.)

Usage:
    python -m propfirm_data.download          # quote only, spends nothing
    python -m propfirm_data.download --yes    # submit jobs (spends credit), download, convert
"""

import argparse
import hashlib
import fcntl
import json
import sys
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

from . import convert
from .budget import BudgetError, check_budget
from .config import (BAR_SYMBOLS, DATASET, DEFAULT_MAX_BUDGET_USD, JOBS, MANIFEST_FILE,
                     QUOTE_SAFETY_MARGIN, RAW_DIR, ROOT, START, STYPE_IN)

POLL_SECONDS = 30
DOWNLOAD_ATTEMPTS = 20
LOCK_FILE = MANIFEST_FILE.with_name("download.lock")


# --- manifest: remembers submitted jobs so we never pay twice -------------------

def load_manifest() -> dict:
    if MANIFEST_FILE.exists():
        return json.loads(MANIFEST_FILE.read_text())
    return {"jobs": {}}


def save_manifest(manifest: dict) -> None:
    MANIFEST_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = MANIFEST_FILE.with_suffix(".partial")
    tmp.write_text(json.dumps(manifest, indent=2))
    tmp.replace(MANIFEST_FILE)  # atomic: never leaves a half-written manifest


def already_reserved(manifest: dict) -> float:
    """Worst-case cost of every job ever submitted (quote x safety margin)."""
    return sum(job.get("reserved_cost", job["quoted_cost"] * QUOTE_SAFETY_MARGIN)
               for job in manifest["jobs"].values())


@contextmanager
def single_instance():
    """Stop two copies of this script from running at once (both could submit a paid job)."""
    LOCK_FILE.parent.mkdir(parents=True, exist_ok=True)
    with LOCK_FILE.open("w") as fh:
        try:
            fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise SystemExit("Another download is already running. Wait for it to finish.") from None
        yield


def mismatched_jobs(manifest: dict) -> list[str]:
    """Saved jobs whose request differs from the current config (config edited after paying)."""
    bad = []
    for name, job in manifest["jobs"].items():
        saved = {k: v for k, v in job["params"].items() if k != "end"}
        current = {k: v for k, v in job_params(name, job["params"]["end"]).items() if k != "end"} \
            if name in JOBS else None
        if saved != current:
            bad.append(name)
    return bad


# --- network helpers ----------------------------------------------------------------

def retry(fn, attempts: int = 5, wait: float = 5.0):
    """Retry free calls (quotes, status checks). Never wrap a billable call in this."""
    for i in range(attempts):
        try:
            return fn()
        except Exception as exc:  # noqa: BLE001 - network errors come in many types
            if i == attempts - 1:
                raise
            print(f"  network error ({exc.__class__.__name__}), retrying in {wait:.0f}s...")
            time.sleep(wait)


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def job_params(name: str, end: str) -> dict:
    return {
        "dataset": DATASET,
        "symbols": BAR_SYMBOLS,
        "stype_in": STYPE_IN,
        "schema": JOBS[name]["schema"],
        "start": START,
        "end": end,
    }


# --- steps ----------------------------------------------------------------------------

def quote_jobs(client, names: list[str], end: str) -> dict[str, float]:
    quotes = {}
    for name in names:
        p = job_params(name, end)
        quotes[name] = retry(lambda p=p: client.metadata.get_cost(**p))
    return quotes


def submit_job(client, manifest: dict, name: str, end: str, quote: float) -> str:
    params = job_params(name, end)
    # Record the spend BEFORE submitting so a crash can never lead to a second paid job.
    manifest["jobs"][name] = {
        "job_id": None,
        "params": params,
        "quoted_cost": quote,
        "reserved_cost": quote * QUOTE_SAFETY_MARGIN,
        "submitted_at": datetime.now(timezone.utc).isoformat(),
    }
    save_manifest(manifest)

    # Not retried on purpose: a retry could create (and bill) a second job.
    job = client.batch.submit_job(
        **params,
        encoding="dbn",
        compression="zstd",
        split_duration=JOBS[name]["split_duration"],
        stype_out="instrument_id",
    )
    manifest["jobs"][name]["job_id"] = job["id"]
    save_manifest(manifest)
    print(f"  submitted {name}: job {job['id']}")
    return job["id"]


def wait_until_done(client, job_id: str) -> None:
    while True:
        state = retry(lambda: client.batch.get_job_details(job_id)).get("state")
        if state == "done":
            return
        if state in (None, "expired"):
            raise RuntimeError(f"job {job_id} is {state or 'missing'}; files are no longer available")
        print(f"  job {job_id}: {state}, checking again in {POLL_SECONDS}s")
        time.sleep(POLL_SECONDS)


def download_files(client, name: str, job_id: str) -> int:
    """Download each file of a job, skipping ones already present with a matching hash."""
    out_dir = RAW_DIR / name
    files = retry(lambda: client.batch.list_files(job_id))
    done = 0
    for info in files:
        target = out_dir / job_id / info["filename"]
        expected = str(info.get("hash", "")).removeprefix("sha256:")
        for attempt in range(1, DOWNLOAD_ATTEMPTS + 1):
            if target.exists() and (not expected or sha256(target) == expected):
                break
            target.unlink(missing_ok=True)
            try:
                client.batch.download(job_id, output_dir=out_dir, filename_to_download=info["filename"])
            except Exception as exc:  # noqa: BLE001
                print(f"  {info['filename']}: attempt {attempt} failed ({exc.__class__.__name__}), retrying")
                time.sleep(3)
        else:
            raise RuntimeError(f"could not download {info['filename']} after {DOWNLOAD_ATTEMPTS} attempts")
        done += 1
    print(f"  {name}: {done}/{len(files)} files verified")
    return done


# --- main -------------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--yes", action="store_true", help="actually submit paid jobs (default: quote only)")
    parser.add_argument("--max-budget", type=float, default=DEFAULT_MAX_BUDGET_USD,
                        help=f"hard cap on total spend in USD (default {DEFAULT_MAX_BUDGET_USD})")
    args = parser.parse_args(argv)

    load_dotenv(ROOT / ".env")
    import databento as db  # imported late so --help works without a key
    client = db.Historical()  # reads DATABENTO_API_KEY; never printed

    with single_instance():
        return run(client, args)


def run(client, args) -> int:
    manifest = load_manifest()  # read only after taking the lock
    if bad := mismatched_jobs(manifest):
        print(f"ABORTED: saved jobs {bad} do not match the current config.")
        print(f"Someone changed config.py after paying. Restore it, or move {MANIFEST_FILE} aside on purpose.")
        return 4
    pending = [n for n in JOBS if n not in manifest["jobs"]]

    if pending:
        # Whole days only: cost estimates are most accurate for full days.
        available = retry(lambda: client.metadata.get_dataset_range(dataset=DATASET))
        end = available["end"][:10]
        quotes = quote_jobs(client, pending, end)

        print(f"\nQuote for {DATASET} {', '.join(BAR_SYMBOLS)}  {START} -> {end}")
        for name, q in quotes.items():
            print(f"  {name:12s} ${q:8.2f}")
        print(f"  {'total':12s} ${sum(quotes.values()):8.2f}")
        print(f"  already reserved by earlier runs: ${already_reserved(manifest):.2f}")

        try:
            worst = check_budget(quotes, already_reserved(manifest), args.max_budget)
        except BudgetError as exc:
            print(f"\nABORTED: {exc}")
            return 2
        print(f"  worst case incl. 10% margin: ${worst:.2f}  (budget ${args.max_budget:.2f})")

        if not args.yes:
            print("\nQuote only. Check your remaining credit in the Databento portal,")
            print("then run again with --yes to submit the jobs.")
            return 0

        for name in pending:
            submit_job(client, manifest, name, end, quotes[name])
    else:
        print("All jobs already submitted earlier; nothing new to pay for.")

    for name, job in manifest["jobs"].items():
        if not job.get("job_id"):
            print(f"\n{name}: a submit was recorded but no job id was saved.")
            print("Check https://databento.com/portal/download-center before doing anything else,")
            print(f"then put the job id into {MANIFEST_FILE} by hand.")
            return 3
        wait_until_done(client, job["job_id"])
        download_files(client, name, job["job_id"])

    print("\nConverting to Parquet...")
    rows = convert.convert_all()
    for year, n in rows.items():
        print(f"  {year}: {n:,} bars")
    print("\nDone. Next: python -m propfirm_data.validate")
    return 0


if __name__ == "__main__":
    sys.exit(main())
