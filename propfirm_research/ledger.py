"""Append-only research ledger (research/LEDGER.csv): every run and every data access is one row.

The ledger is how the programme counts its tries (PROTOCOL §1.2). Rows are never edited or deleted.
Validation and holdout rows must carry the sha256 of a frozen pre-registration.
"""

import csv
import fcntl
import hashlib
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from . import paths

COLUMNS = ["run_id", "utc", "item_id", "kind", "period", "n_tests", "statistic", "value", "p_value",
           "verdict", "prereg_sha256", "code_sha256", "data_sha256", "output", "note"]
KINDS = {"prior", "synthetic", "access", "descriptive", "exploratory", "prereg", "validation", "holdout",
         "review"}
NEEDS_PREREG = {"validation", "holdout"}


class LedgerError(ValueError):
    pass


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def sha256_files(files) -> str:
    """One hash over several files (sorted by path; each file's path and content)."""
    h = hashlib.sha256()
    for p in sorted(Path(f) for f in files):
        h.update(str(p.name).encode())
        h.update(sha256_file(p).encode())
    return h.hexdigest()


def read() -> pd.DataFrame:
    if not paths.LEDGER_FILE.exists():
        return pd.DataFrame(columns=COLUMNS)
    return pd.read_csv(paths.LEDGER_FILE, dtype=str, keep_default_na=False)


def _next_id(item_id: str, rows: pd.DataFrame) -> str:
    n = int((rows["item_id"] == item_id).sum()) if len(rows) else 0
    return f"{item_id}-{n + 1:03d}"


def append(item_id: str, kind: str, period: str, **fields) -> str:
    """Write one row; returns its run_id. Unknown fields raise (typos must not vanish silently)."""
    if kind not in KINDS:
        raise LedgerError(f"unknown kind {kind!r}; one of {sorted(KINDS)}")
    if kind in NEEDS_PREREG and not fields.get("prereg_sha256"):
        raise LedgerError(f"a {kind} row needs prereg_sha256 (PROTOCOL §5)")
    extra = set(fields) - set(COLUMNS)
    if extra:
        raise LedgerError(f"unknown ledger fields {sorted(extra)}")
    paths.LEDGER_FILE.parent.mkdir(parents=True, exist_ok=True)
    lock = paths.LEDGER_FILE.with_suffix(".lock")
    with open(lock, "w") as lk:
        fcntl.flock(lk, fcntl.LOCK_EX)  # id allocation + append as one transaction
        return _append_locked(item_id, kind, period, fields)


def _append_locked(item_id: str, kind: str, period: str, fields: dict) -> str:
    rows = read()
    run_id = _next_id(item_id, rows)
    row = {c: "" for c in COLUMNS}
    row.update({k: "" if v is None else str(v) for k, v in fields.items()})
    row.update(run_id=run_id, utc=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
               item_id=item_id, kind=kind, period=period)
    new = not paths.LEDGER_FILE.exists()
    with open(paths.LEDGER_FILE, "a", newline="") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNS)
        if new:
            w.writeheader()
        w.writerow(row)
    return run_id


def prereg_registered(prereg_sha: str) -> bool:
    rows = read()
    return bool(len(rows)) and bool(((rows["kind"] == "prereg") & (rows["prereg_sha256"] == prereg_sha)).any())
