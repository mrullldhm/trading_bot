"""Stage-1 data handling (D010): the line-1 format check and the DBN -> parquet conversion.

Kept apart from `stage1.py`, which holds the money rules. Neither reads CL bars for analysis; research code reads the
converted files only through `propfirm_research.data`.

check: schema and coverage counts of the line-1 sample, never signed daily aggregates or returns (Codex R016 Q5).
Decision rule frozen before the sample was bought (session-4 plan): CL.v.0 aggressor side on >= 99% of volume
and of records, both codes present -> line 5; below 90% -> line 6; in between -> ask the owner.
"""

import json
from datetime import datetime, timezone
from pathlib import Path

import databento as db
import databento_dbn as d
import numpy as np
import pandas as pd

from .config import DEFINITIONS_FILE, FIXED_PER_TICK
from .convert import attach_raw_symbol
from .stage1 import MANIFEST, OUT, RAW, ROOT, SAMPLE_CHECK, WORK, rel, sha256

FIXED_PER_TAS_TICK = 1_000_000_000  # a CLT price is the TAS differential in ticks, stored as ticks x 1e9
F_BAD_TS_RECV = 8  # Databento flag: ts_recv is not a real capture time
SIDE_OK, SIDE_ASK_FLOOR = 0.99, 0.90
ET = "America/New_York"


def read_dbn(path) -> pd.DataFrame:
    return db.DBNStore.from_file(path).to_df(price_type="fixed", pretty_ts=True, map_symbols=True,
                                             tz="UTC").reset_index()


def side_coverage(df: pd.DataFrame) -> dict:
    signed = df["side"].isin(["A", "B"])
    vol = df["size"].astype(float)
    return {"records": int(len(df)), "volume": int(vol.sum()),
            "side_counts": {k: int(v) for k, v in df["side"].value_counts().items()},
            "coverage_records": float(signed.mean()) if len(df) else float("nan"),
            "coverage_volume": float(vol[signed].sum() / vol.sum()) if vol.sum() else float("nan"),
            "both_codes": bool({"A", "B"} <= set(df["side"]))}


def decide(cov: dict) -> str:
    lo = min(cov["coverage_records"], cov["coverage_volume"])
    if lo >= SIDE_OK and cov["both_codes"]:
        return "line5"
    if lo < SIDE_ASK_FLOOR or not cov["both_codes"]:
        return "line6"
    return "ask_owner"


def front_raw_symbol(cl: pd.DataFrame) -> list[str]:
    """Raw symbol(s) of the CL.v.0 instrument(s) in the sample, from the existing (hash-frozen, read-only) CL
    definitions."""
    defs = pd.read_parquet(DEFINITIONS_FILE)
    ids = set(cl["instrument_id"].astype("int64"))
    return sorted(defs.loc[defs["instrument_id"].isin(ids), "raw_symbol"].unique())


def sample_check() -> dict:
    files = {"tas": RAW / "sample_clt" / "sample_clt.dbn.zst", "cl": RAW / "sample_cl" / "sample_cl.dbn.zst"}
    tas, cl = read_dbn(files["tas"]), read_dbn(files["cl"])
    tas["spread"] = tas["symbol"].str.contains("-")
    out = {"checked_utc": datetime.now(timezone.utc).isoformat(), "files": {k: {"path": rel(f), "sha256": sha256(f)}
                                                                           for k, f in files.items()}}
    out["side"] = {"cl_v0": side_coverage(cl), "tas_outright": side_coverage(tas[~tas["spread"]]),
                   "tas_spread": side_coverage(tas[tas["spread"]])}
    diff = tas["price"] / FIXED_PER_TAS_TICK
    integral = bool(np.allclose(diff, diff.round()))
    out["tas_price"] = {
        "unit": "TAS differential in ticks = price / 1e9 (fixed)",
        "values_outright": {f"{k:g}": int(v) for k, v in diff[~tas["spread"]].value_counts().sort_index().items()},
        "values_spread": {f"{k:g}": int(v) for k, v in diff[tas["spread"]].value_counts().sort_index().items()},
        "integral_ticks": integral, "max_abs_ticks": float(diff.abs().max()),
        "encoding": "differential_ticks" if integral and diff.abs().max() <= 10 else "unknown",
        "sign_convention": "assumed + = settlement plus; to verify against CLT definitions (line 3)"}
    et = tas["ts_event"].dt.tz_convert(ET)
    out["tas_session"] = {"first_trade_et": str(et.min()), "last_trade_et": str(et.max()),
                          "last_before_1430": bool(et.max().hour * 60 + et.max().minute < 14 * 60 + 30),
                          "raw_symbols": {k: int(v) for k, v in tas["symbol"].value_counts().items()}}
    front = front_raw_symbol(cl)
    tas_front = ["CLT" + s[2:] for s in front]
    out["mapping"] = {"cl_v0_instruments": [int(x) for x in cl["instrument_id"].unique()], "cl_v0_raw": front,
                      "tas_front": tas_front,
                      "tas_front_unique": len(front) == 1
                      and tas.loc[tas["symbol"] == tas_front[0], "instrument_id"].nunique() == 1}
    both = pd.concat([cl.assign(src="cl"), tas.assign(src="tas")])
    lag = (both["ts_recv"] - both["ts_event"]).dt.total_seconds()
    out["timestamps"] = {"recv_minus_event_s": {"min": float(lag.min()), "max": float(lag.max())},
                         "recv_before_event": int((lag < 0).sum()),
                         "bad_ts_recv_flag_share": float(((both["flags"] & F_BAD_TS_RECV) > 0).mean()),
                         "note": "ts_recv equals ts_event and carries the bad-ts_recv flag: before 2017 the known-at "
                                 "rule falls back to ts_event"}
    out["integrity"] = {"actions": {k: int(v) for k, v in both["action"].value_counts().items()},
                        "sequence_monotonic": {s: bool(g["sequence"].is_monotonic_increasing)
                                               for s, g in both.groupby("src")},
                        "identical_rows_cl": int(cl.duplicated(["ts_event", "sequence", "price", "size", "side"]).sum()),
                        "identical_rows_note": "several fills of one aggressive order share time, sequence and price; "
                                               "they are real fills and are never de-duplicated"}
    out["decision"] = decide(out["side"]["cl_v0"])
    out["tas_side_ok"] = decide(out["side"]["tas_outright"]) == "line5"
    out["disclosure"] = ("side shares are counts per side code (needed for 'both codes present'); for one hour "
                         "this equals the hour's signed volume. No returns, no daily aggregates. The H027/H028 "
                         "families were drafted before the sample (plan file) and are not changed by it.")
    return out


def run_check() -> int:
    from propfirm_research import ledger  # research ledger: every look at market data is one row
    out = sample_check()
    WORK.mkdir(parents=True, exist_ok=True)
    SAMPLE_CHECK.write_text(json.dumps(out, indent=1))
    cov = out["side"]["cl_v0"]
    ledger.append("S004", "access", "discovery", n_tests=0,
                  data_sha256=ledger.sha256_files([ROOT / f["path"] for f in out["files"].values()]),
                  output=rel(SAMPLE_CHECK),
                  note=f"D010 line-1 sample format check (2015-06-10 14:00-15:00 ET, schema/coverage only, no returns):"
                       f" CL.v.0 side on {cov['coverage_volume']:.1%} of volume / {cov['coverage_records']:.1%} of "
                       f"records -> {out['decision']}; TAS side ok {out['tas_side_ok']}; TAS price "
                       f"{out['tas_price']['encoding']}")
    print(json.dumps({k: out[k] for k in ("side", "tas_price", "tas_session", "mapping", "timestamps", "decision",
                                          "tas_side_ok")}, indent=1))
    return 0


# --- conversion: DBN -> parquet under data/processed/stage1/<table>/year=YYYY/part.parquet ------------------
# Files are split by the UTC year of ts_event; periods are cut by CME trading day in the loaders.

def dbn_files(item: str) -> list:
    return sorted((RAW / item).rglob("*.dbn.zst"))


def write_years(frame: pd.DataFrame, table: str, time_col: str = "ts_event_utc") -> dict:
    out = {}
    for year, g in frame.groupby(frame[time_col].dt.year, sort=True):
        path = OUT / table / f"year={year}" / "part.parquet"
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(path.name + ".partial")
        g.sort_values(time_col, kind="stable").to_parquet(tmp, index=False)
        tmp.replace(path)
        out[int(year)] = len(g)
    return out


def write_one(frame: pd.DataFrame, name: str) -> int:
    path = OUT / name
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".partial")
    frame.to_parquet(tmp, index=False)
    tmp.replace(path)
    return len(frame)


def nullable(series: pd.Series, undefined: int) -> pd.Series:
    """Databento marks a missing value with a sentinel; turn it into a proper missing value."""
    x = series.astype("int64")
    return x.where(x != undefined).astype("Int64")


def to_ticks(fixed: pd.Series, per_tick: int, what: str) -> pd.Series:
    x = fixed.astype("int64")
    off = (x % per_tick) != 0
    if off.any():
        raise ValueError(f"{off.sum()} {what} prices are off the tick grid ({per_tick} fixed units)")
    return x // per_tick


def definitions_frame() -> pd.DataFrame:
    frames = [read_dbn(f) for f in dbn_files("clt_definitions")]
    if not frames:
        raise FileNotFoundError("no CLT definition files: run the purchase first")
    df = pd.concat(frames, ignore_index=True)
    keep = ["ts_recv", "ts_event", "instrument_id", "raw_symbol", "instrument_class", "expiration", "activation",
            "min_price_increment", "display_factor", "underlying_id", "security_update_action", "leg_count",
            "leg_index", "leg_instrument_id", "leg_raw_symbol", "leg_side", "leg_ratio_qty_numerator",
            "leg_ratio_qty_denominator"]
    out = df[[c for c in keep if c in df.columns]].copy()
    out["instrument_id"] = out["instrument_id"].astype("int64")
    out["is_spread"] = out["instrument_class"].astype(str).isin([str(d.InstrumentClass.FUTURE_SPREAD.value),
                                                                  "S", "FUTURE_SPREAD"])
    return out.drop_duplicates().sort_values(["ts_recv", "instrument_id"]).reset_index(drop=True)


def tas_frame(df: pd.DataFrame, spread_ids: set) -> pd.DataFrame:
    """Trade records only (action T); the caller counts the rest. Databento's trades schema carries trade events
    only (no separate correction or cancel records). Identical rows are separate fills of one aggressive order and
    are kept."""
    df = df[df["action"] == "T"]
    diff = df["price"].astype("int64")
    if (diff % FIXED_PER_TAS_TICK != 0).any():
        raise ValueError("a TAS price is not a whole number of ticks")
    raw = df["symbol"].astype(str)
    is_spread = df["instrument_id"].astype("int64").isin(spread_ids)
    if (is_spread != raw.str.contains("-")).any():
        raise ValueError("TAS spread flag from the definitions disagrees with the raw symbol")
    return pd.DataFrame({
        "ts_event_utc": df["ts_event"], "ts_recv_utc": df["ts_recv"],
        "instrument_id": df["instrument_id"].astype("int64"), "raw_symbol": raw, "is_spread": is_spread.to_numpy(),
        "diff_ticks": (diff // FIXED_PER_TAS_TICK).astype("int64"), "size": df["size"].astype("int64"),
        "side": df["side"].astype(str), "action": df["action"].astype(str), "flags": df["flags"].astype("int16"),
        "sequence": df["sequence"].astype("int64")})


def convert_tas(defs: pd.DataFrame) -> dict:
    spread_ids = set(defs.loc[defs["is_spread"], "instrument_id"])
    frames, other = [], 0
    for f in dbn_files("tas_trades"):
        raw = read_dbn(f)
        other += int((raw["action"] != "T").sum())
        frames.append(tas_frame(raw, spread_ids))
    return {**write_years(pd.concat(frames, ignore_index=True), "tas_trades"), "dropped_non_trade_records": other}


def stats_frame(df: pd.DataFrame, source: str) -> pd.DataFrame:
    return pd.DataFrame({
        "ts_event_utc": df["ts_event"], "ts_recv_utc": df["ts_recv"],
        "ts_ref_utc": df["ts_ref"],  # pretty_ts: the session date for settlements, NaT where CME sends none
        "instrument_id": df["instrument_id"].astype("int64"), "symbol": df["symbol"].astype(str), "source": source,
        "stat_type": df["stat_type"].astype("int64"), "price_fixed": nullable(df["price"], d.UNDEF_PRICE),
        "quantity": nullable(df["quantity"], d.UNDEF_STAT_QUANTITY), "update_action": df["update_action"].astype("int64"),
        "stat_flags": df["stat_flags"].astype("int64"), "sequence": df["sequence"].astype("int64")})


def convert_statistics() -> dict:
    frames = [stats_frame(read_dbn(f), src) for src, item in (("cl", "statistics_cl"), ("clt", "statistics_clt"))
              for f in dbn_files(item)]
    return write_years(pd.concat(frames, ignore_index=True), "statistics")


ENERGY_FIXED_PER_TICK = {"RB": 100_000, "HO": 100_000, "BZ": 10_000_000}  # RB/HO $0.0001, BZ $0.01


def energy_frame(df: pd.DataFrame) -> pd.DataFrame:
    sym = df["symbol"].astype(str)
    root = sym.str.split(".").str[0]
    per_tick = root.map(ENERGY_FIXED_PER_TICK)
    if per_tick.isna().any():
        raise ValueError(f"unknown energy roots {sorted(set(root[per_tick.isna()]))}")
    out = pd.DataFrame({"ts_event_utc": df["ts_event"], "continuous_symbol": sym,
                        "instrument_id": df["instrument_id"].astype("int64"),
                        "volume": df["volume"].astype("int64"), "tick_fixed": per_tick.astype("int64")})
    for col in ("open", "high", "low", "close"):
        fixed = df[col].astype("int64")
        if (fixed % out["tick_fixed"] != 0).any():
            raise ValueError(f"{col} prices off the tick grid")
        out[f"{col}_ticks"] = fixed // out["tick_fixed"]
        out[col] = fixed / 1e9
    return out


def convert_energy() -> dict:
    frames = [energy_frame(read_dbn(f)) for item in ("energy_bars", "brent_bars") for f in dbn_files(item)]
    return write_years(pd.concat(frames, ignore_index=True), "energy_ohlcv_1m")


def mbp1_trades(df: pd.DataFrame) -> pd.DataFrame:
    """Trade records of one mbp-1 file, with the best bid / ask the record carries (the book before the trade's
    own updates: MDP3 sends the trade summary first; S004 checks this on the reported sides)."""
    t = df[df["action"] == "T"]
    bid = nullable(t["bid_px_00"], d.UNDEF_PRICE)
    ask = nullable(t["ask_px_00"], d.UNDEF_PRICE)
    return pd.DataFrame({
        "ts_event_utc": t["ts_event"].to_numpy(), "ts_recv_utc": t["ts_recv"].to_numpy(),
        "instrument_id": t["instrument_id"].astype("int64").to_numpy(),
        "price_ticks": to_ticks(t["price"], FIXED_PER_TICK, "trade").to_numpy(),
        "size": t["size"].astype("int64").to_numpy(), "side": t["side"].astype(str).to_numpy(),
        "flags": t["flags"].astype("int16").to_numpy(), "sequence": t["sequence"].astype("int64").to_numpy(),
        "bid_ticks": (bid // FIXED_PER_TICK).astype("Float64").to_numpy(float, na_value=np.nan),
        "ask_ticks": (ask // FIXED_PER_TICK).astype("Float64").to_numpy(float, na_value=np.nan)})


def convert_mbp1() -> dict:
    """Per-day mbp-1 files -> trades with the book; raw symbols from the existing CL definitions (read only)."""
    defs = pd.read_parquet(DEFINITIONS_FILE)
    frames, audit = [], []
    for f in dbn_files("cl_mbp1_1420"):
        df = read_dbn(f)
        tr = mbp1_trades(df)
        tr["ts_event_utc"] = pd.to_datetime(tr["ts_event_utc"], utc=True)
        tr["ts_recv_utc"] = pd.to_datetime(tr["ts_recv_utc"], utc=True)
        frames.append(tr)
        audit.append({"file": f.name, "records": len(df), "actions": df["action"].value_counts().to_dict(),
                      "trades": len(tr), "trade_volume": int(tr["size"].sum()),
                      "instruments": sorted(int(x) for x in tr["instrument_id"].unique())})
    trades = attach_raw_symbol(pd.concat(frames, ignore_index=True), defs)
    if trades["raw_symbol"].isna().any():
        raise ValueError("an mbp-1 trade has no CL contract in the definitions")
    (WORK / "mbp1_audit.json").write_text(json.dumps(audit, indent=0, default=str))
    return write_years(trades, "cl_mbp1_1420")


CONVERTED_ITEMS = ("clt_definitions", "tas_trades", "statistics_cl", "statistics_clt", "energy_bars", "brent_bars",
                   "cl_mbp1_1420")


def verify_raw_inputs() -> int:
    """Every DBN file the conversion reads must be one the purchase manifest recorded, with the same sha256, and every
    recorded file must still exist (R017). Returns the number of files checked."""
    expected = {k: v for k, v in raw_input_hashes().items() if k.endswith(".dbn.zst")}
    read = {rel(f) for item in CONVERTED_ITEMS for f in dbn_files(item)}
    extra = sorted(read - set(expected))
    missing = sorted(k for k in expected if k.split("/")[3] in CONVERTED_ITEMS and not (ROOT / k).exists())
    changed = sorted(k for k in read & set(expected) if sha256(ROOT / k) != expected[k])
    if extra or missing or changed:
        raise ValueError(f"raw inputs differ from the purchase manifest: extra {extra[:3]}, missing {missing[:3]}, "
                         f"changed {changed[:3]}")
    return len(read)


def convert_all() -> dict:
    checked = verify_raw_inputs()  # before any byte is converted
    defs = definitions_frame()
    out = {"clt_definitions": write_one(defs, "clt_definitions.parquet"), "tas_trades": convert_tas(defs),
           "statistics": convert_statistics(), "energy_ohlcv_1m": convert_energy()}
    if dbn_files("cl_mbp1_1420"):
        out["cl_mbp1_1420"] = convert_mbp1()
    out["raw_inputs_verified"] = checked
    return out


def raw_input_hashes() -> dict:
    """Hashes of the bought DBN files, as recorded by the purchase manifest when they arrived."""
    m = json.loads(MANIFEST.read_text())
    out = {}
    for rec in m["requests"].values():
        out.update(rec.get("files") or {})
        if rec.get("file"):
            out[rec["file"]] = rec["sha256"]
    return out


def main(command: str) -> int:
    if command == "check":
        return run_check()
    rows = convert_all()
    code = Path(__file__).parent
    record = {"converted_utc": datetime.now(timezone.utc).isoformat(), "rows": rows,
              "code_sha256": {f.name: sha256(f) for f in (code / "stage1.py", code / "stage1_convert.py")},
              "inputs": {f: h for f, h in raw_input_hashes().items()},
              "files": {rel(f): sha256(f) for f in sorted(OUT.rglob("*.parquet"))}}
    (WORK / "convert_manifest.json").write_text(json.dumps(record, indent=1))
    print(json.dumps(rows, indent=1))
    return 0
