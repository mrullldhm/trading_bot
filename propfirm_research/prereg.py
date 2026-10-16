"""Pre-registration: freeze a test spec once, then open its data period exactly once (PROTOCOL §5).

register(item_dir, spec, code_files, data_files)  validates and writes prereg.json (never overwritten)
                                                   plus a ledger row (kind "prereg").
with open_run(prereg_path) as run:                 creates <period>_opened.json atomically (O_EXCL)
    data.load_front(..., run=run)                  BEFORE any data is read; the RunToken is the only key
                                                   to that period, is bound to the prereg's item / period,
                                                   and is revoked when the block ends. A second open refuses.
"""

import importlib.metadata as md
import json
import os
import platform
import secrets
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from . import ledger

REQUIRED = ["item_id", "claim", "period", "null", "test", "alpha_one_sided", "family", "multiplicity",
            "signal", "entry", "exit", "fee_usd", "slip_ticks", "stress_slip_ticks", "contracts",
            "min_signals", "power_mde", "seed", "codex_review", "stopping_rule"]
NULLS = {"N2", "N3", "N4a", "N4b"}  # combined with N1 in one statistic per variant (PROTOCOL §4.2)
MULTIPLICITY = {"romano-wolf", "single"}
STOPPING_RULE = "one run; never re-run, extended or re-registered"
VALIDATION_ALPHA = 0.01
MAX_VARIANTS = 4
PACKAGES = ("numpy", "pandas", "numba", "pyarrow")


class PreregError(RuntimeError):
    pass


def validate(spec: dict, item_dir: Path) -> None:
    missing = [k for k in REQUIRED if k not in spec]
    if missing:
        raise PreregError(f"prereg missing fields: {missing}")
    if not Path(item_dir).name.startswith(spec["item_id"]):
        raise PreregError(f"folder {Path(item_dir).name!r} does not match item_id {spec['item_id']!r}")
    if spec["period"] not in ("validation", "holdout"):
        raise PreregError("period must be 'validation' or 'holdout'")
    if spec["period"] == "validation" and spec["alpha_one_sided"] != VALIDATION_ALPHA:
        raise PreregError(f"validation alpha must be {VALIDATION_ALPHA} one-sided (PROTOCOL §4.3)")
    if spec["period"] == "holdout" and spec.get("approved_by_user") is not True:
        raise PreregError("a holdout prereg needs approved_by_user: true (owner approval)")
    if spec["null"] not in NULLS:
        raise PreregError(f"null must be one of {sorted(NULLS)}")
    if spec["multiplicity"] not in MULTIPLICITY:
        raise PreregError(f"multiplicity must be one of {sorted(MULTIPLICITY)}")
    fam = spec["family"]
    if not isinstance(fam, list) or not 1 <= len(fam) <= MAX_VARIANTS:
        raise PreregError(f"family must list 1..{MAX_VARIANTS} variants")
    if len(fam) > 1 and spec["multiplicity"] != "romano-wolf":
        raise PreregError("several variants need romano-wolf")
    for k in ("fee_usd", "slip_ticks", "stress_slip_ticks", "alpha_one_sided"):
        if not isinstance(spec[k], (int, float)) or spec[k] < 0:
            raise PreregError(f"{k} must be a non-negative number")
    if not isinstance(spec["contracts"], int) or spec["contracts"] < 1:
        raise PreregError("contracts must be a positive integer")
    if spec["stopping_rule"] != STOPPING_RULE:
        raise PreregError(f"stopping_rule must be exactly {STOPPING_RULE!r}")
    if not str(spec["codex_review"]).startswith("R"):
        raise PreregError("codex_review must name the R### review that cleared this prereg")


def register(item_dir: Path, spec: dict, code_files, data_files) -> Path:
    item_dir = Path(item_dir)
    path = item_dir / "prereg.json"
    if path.exists():
        raise PreregError(f"{path} already exists: a pre-registration is never rewritten")
    validate(spec, item_dir)
    if not code_files or not data_files:
        raise PreregError("code_files and data_files are required (their hashes are frozen)")
    full = dict(spec)
    full["registered_utc"] = datetime.now(timezone.utc).isoformat()
    full["code_sha256"] = ledger.sha256_files(code_files)
    full["data_sha256"] = ledger.sha256_files(data_files)
    full["environment"] = {"python": platform.python_version(),
                           **{p: md.version(p) for p in PACKAGES}}
    item_dir.mkdir(parents=True, exist_ok=True)
    with open(path, "x") as f:
        json.dump(full, f, indent=2, default=str)
    sha = ledger.sha256_file(path)
    ledger.append(spec["item_id"], "prereg", spec["period"], prereg_sha256=sha, output=str(path),
                  code_sha256=full["code_sha256"], data_sha256=full["data_sha256"], note="frozen")
    return path


def load(prereg_path: Path) -> tuple[dict, str]:
    """Spec and its sha256; refuses a file that was never registered in the ledger."""
    prereg_path = Path(prereg_path)
    sha = ledger.sha256_file(prereg_path)
    if not ledger.prereg_registered(sha):
        raise PreregError(f"{prereg_path} is not a registered pre-registration (edited or never frozen)")
    return json.loads(prereg_path.read_text()), sha


@dataclass(eq=False)
class RunToken:
    """Key to one protected period for one pre-registered run. Only `open_run` creates live tokens."""
    item_id: str
    period: str
    prereg_sha256: str
    _secret: str = field(repr=False, default="")
    _live: bool = field(repr=False, default=False)


_LIVE: dict[int, str] = {}  # id(token) -> secret; tokens not in here (or revoked) are refused


def is_live(token: "RunToken") -> bool:
    return isinstance(token, RunToken) and token._live and _LIVE.get(id(token)) == token._secret != ""


@contextmanager
def open_run(prereg_path: Path):
    spec, sha = load(prereg_path)
    period = spec["period"]
    validate(spec, Path(prereg_path).parent)
    marker = Path(prereg_path).parent / f"{period}_opened.json"
    try:
        fd = os.open(marker, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        raise PreregError(f"{marker} exists: this test already ran (one run, never re-run)") from None
    with os.fdopen(fd, "w") as f:
        json.dump({"opened_utc": datetime.now(timezone.utc).isoformat(), "prereg_sha256": sha}, f)
    token = RunToken(spec["item_id"], period, sha, secrets.token_hex(16), True)
    _LIVE[id(token)] = token._secret
    ledger.append(spec["item_id"], "access", period, prereg_sha256=sha, note="period opened")
    try:
        yield token
    finally:
        token._live = False
        _LIVE.pop(id(token), None)
