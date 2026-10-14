"""Shared settings for the CL data pipeline."""

from pathlib import Path

DATASET = "GLBX.MDP3"  # CME Globex (includes NYMEX crude oil)
BAR_SYMBOLS = ["CL.v.0", "CL.v.1"]  # front + next contract, ranked by previous day's volume
STYPE_IN = "continuous"
START = "2010-06-06"  # first day Databento has GLBX.MDP3 data

# Databento "fixed" prices are integers in units of 1e-9 USD.
FIXED_PER_USD = 1_000_000_000
TICK_USD = 0.01
FIXED_PER_TICK = 10_000_000  # 0.01 / 1e-9
TICK_VALUE_USD = 10.0  # one CL tick on one contract

DEFAULT_MAX_BUDGET_USD = 60.0
QUOTE_SAFETY_MARGIN = 1.10  # get_cost is an estimate; assume it can be 10% low

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
RAW_DIR = DATA_DIR / "raw"
PROCESSED_DIR = DATA_DIR / "processed"
BARS_DIR = PROCESSED_DIR / "ohlcv-1m"
DEFINITIONS_FILE = PROCESSED_DIR / "definitions" / "cl_contracts.parquet"
MANIFEST_FILE = DATA_DIR / "manifests" / "download.json"

# Two batch jobs. Each is billed once; files can be re-downloaded free for 30 days.
JOBS = {
    "definitions": {"schema": "definition", "split_duration": "none"},
    "bars": {"schema": "ohlcv-1m", "split_duration": "month"},
}
