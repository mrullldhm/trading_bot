"""Settlement-window hypothesis harness: H025 / H026 now, later H027 / H028 with their own signals.

Discovery only, exploratory tier (PROTOCOL §4.3-4.5). One family per run: one-sided day-level t of the gross
edge per variant, Benjamini-Hochberg q-values over the frozen family (a variant that cannot be tested keeps
its place with p = 1, so the family never shrinks), the three discovery blocks, base and stress costs, and
the promotion screen of PROTOCOL §4.4 with the §4.5 power rule as an IID screen:
MDE_net = (z_0.99 + z_0.80) * sd / sqrt(5 * trades per year) on the 5 validation years, trades per year =
trades / elapsed calendar years of the loaded days; promotion needs the discovery net edge (base cost)
>= 2 * MDE_net. Variants are frozen in the cards before the run (reviewed in R014).

Conventions:
- signals use only bars that START in [14:25, 14:34] ET of the trading day; the 14:34 bar closes at 14:35:00,
  before the entry. move = close of the 14:34 bar - open of the 14:25 bar; volume = sum over the signal bars
  that exist (interior minutes may be missing). Both end bars must exist and every signal bar must belong to
  one contract, which must be the entry contract;
- entry-time mask vs evaluated trades (R014): a signal is EMITTED from information known by the entry
  (signal bars up to 14:34; the entry bar, the first bar at or after 14:35 and at most 5 minutes late, and its
  contract; the flat schedule); it is EVALUATED only if the exact exit bar exists in the same contract (D009
  complete-case estimand). Emitted-but-unevaluable signals are counted, never traded;
- a filter compares today's value with the 75th percentile (numpy linear interpolation) of the previous 60
  entry-time eligible days, strictly greater; with fewer than 60 earlier eligible days there is no
  threshold and no signal (warm-up);
- one trade per day per variant, so the day-level t is the plain t of the per-trade gross ticks; costs are
  subtracted per round trip (base $24.02 = fee + one adverse tick per side; stress $44.02);
- one run only: the run refuses to start if its card outputs already exist.

Usage: python -m propfirm_research.settlement h025
"""

import argparse
import json
import math
import time
from collections import deque
from datetime import datetime, timezone

import numpy as np
import pandas as pd

from . import data, grid, ledger, paths
from .costs import BASE_TICKS, STRESS_TICKS
from .stats import ND, bh_qvalues, t_pvalue
from .studies.s001_feasibility import code_hash
from .studies.s002_atlas import BLOCKS, block_means, block_of, fingerprint

SIG_START = 14 * 60 + 25
SIG_END = 14 * 60 + 34
ENTRY = 14 * 60 + 35
H026_ENTRY = 14 * 60 + 30
H026_EXIT = 15 * 60
LOOKBACK = 60
PCTL = 75.0
Q_MAX = 0.10
VALIDATION_YEARS = 5
Z_POWER = ND.inv_cdf(0.99) + ND.inv_cdf(0.80)  # one-sided alpha 0.01, power 80%
H025_DIR = paths.RESEARCH_DIR / "hypotheses" / "H025-settlement-continuation"
H026_DIR = paths.RESEARCH_DIR / "hypotheses" / "H026-post-settlement-drift"
FAMILY = {"v1_move_filter": "H025", "v2_volume_filter": "H025", "v3_union": "H025", "v4_h026_short": "H026"}
REFERENCES = {"ref_naive_continuation": "H025"}  # reported, outside BH and the test count


def signals(df: pd.DataFrame, days: np.ndarray) -> pd.DataFrame:
    """Per trading day: move, volume, the signal contract, the failure flags and ok. Only bars starting in
    [SIG_START, SIG_END] are read."""
    sub = df[(df["mod"] >= SIG_START) & (df["mod"] <= SIG_END)]
    first = sub.drop_duplicates("trading_day", keep="first").set_index("trading_day")
    last = sub.drop_duplicates("trading_day", keep="last").set_index("trading_day")
    g = sub.groupby("trading_day", sort=True)
    out = pd.DataFrame({
        "move": last["close"] - first["open"],
        "volume": g["volume"].sum(),
        "sig_contract": first["contract"],
        "ends_ok": (first["mod"] == SIG_START) & (last["mod"] == SIG_END),
        "one_contract": g["contract"].nunique() == 1,
    }).reindex(days)
    for c in ("ends_ok", "one_contract"):
        out[c] = out[c].fillna(False).astype(bool)
    out["ok"] = out["ends_ok"] & out["one_contract"]
    return out


def trailing_threshold(values: np.ndarray, eligible: np.ndarray, lookback: int = LOOKBACK,
                       pctl: float = PCTL) -> np.ndarray:
    """Per day: the `pctl` percentile of `values` over the previous `lookback` eligible days (today excluded);
    NaN until `lookback` eligible days have passed. Days must be in time order."""
    out = np.full(len(values), np.nan)
    past = deque(maxlen=lookback)
    for i, (v, e) in enumerate(zip(values, eligible)):
        if len(past) == lookback:
            out[i] = np.percentile(np.fromiter(past, float), pctl)
        if e:
            past.append(float(v))
    return out


def h025_h026(df: pd.DataFrame, days: np.ndarray | None = None,
              expiry_tmin: dict | None = None) -> tuple[dict, dict]:
    """The frozen R012 Q3 family plus the naive S002 continuation as a reference outside the family.
    Returns ({variant: {"w": windows, "dir": evaluated direction, "emitted": entry-time signal mask}}, counts)."""
    if days is None:
        days = np.unique(df["trading_day"].to_numpy())
    days = np.asarray(days, dtype=np.int64)
    if not np.all(np.diff(days) > 0):
        raise ValueError("days must be strictly increasing (the trailing thresholds walk forward in time)")
    w = grid.windows(df, [(ENTRY, grid.FLAT), (H026_ENTRY, H026_EXIT)], days=days, expiry_tmin=expiry_tmin)
    w_fl = w[w["start_mod"] == ENTRY].reset_index(drop=True)
    w_26 = w[w["start_mod"] == H026_ENTRY].reset_index(drop=True)
    sig = signals(df, days)
    entry_ok = w_fl["entry_ok"].to_numpy()
    valid = w_fl["valid"].to_numpy()
    same = sig["sig_contract"].to_numpy() == w_fl["entry_contract"].to_numpy()
    eligible = sig["ok"].to_numpy() & entry_ok & same  # known by the entry (<= 14:40), never the exit
    move = sig["move"].to_numpy(float)
    vol = sig["volume"].to_numpy(float)
    thr_m = trailing_threshold(np.abs(move), eligible)
    thr_v = trailing_threshold(vol, eligible)
    side = np.sign(np.nan_to_num(move))
    with np.errstate(invalid="ignore"):
        f_move = eligible & (np.abs(move) > thr_m)
        f_vol = eligible & (vol > thr_v)
    v26_ok = w_26["entry_ok"].to_numpy()

    def variant_record(windows, emitted, direction):
        evaluated = emitted & windows["valid"].to_numpy()
        return {"w": windows, "dir": np.where(evaluated, direction, 0.0), "emitted": emitted}

    variants = {
        "v1_move_filter": variant_record(w_fl, f_move & (side != 0), side),
        "v2_volume_filter": variant_record(w_fl, f_vol & (side != 0), side),
        "v3_union": variant_record(w_fl, (f_move | f_vol) & (side != 0), side),
        "v4_h026_short": variant_record(w_26, v26_ok, -1.0),
        "ref_naive_continuation": variant_record(w_fl, eligible & (side != 0), side),
    }
    counts = {
        "days": int(len(days)),
        "signal_invalid": int((~sig["ok"]).sum()), "signal_ends_missing": int((~sig["ends_ok"]).sum()),
        "signal_multi_contract": int((sig["ends_ok"] & ~sig["one_contract"]).sum()),
        "entry_invalid_1435": int((~entry_ok).sum()),
        "signal_entry_contract_mismatch": int((sig["ok"].to_numpy() & entry_ok & ~same).sum()),
        "eligible": int(eligible.sum()), "warmup_eligible": int((eligible & np.isnan(thr_m)).sum()),
        "valid_1435_flat": int(valid.sum()), "exit_missing_1435_flat": int(w_fl["exit_missing"].sum()),
        "entry_ok_1430": int(v26_ok.sum()), "valid_1430_1500": int(w_26["valid"].sum()),
        "exit_missing_1430_1500": int(w_26["exit_missing"].sum()),
    }
    return variants, counts


def evaluate(w: pd.DataFrame, direction: np.ndarray, years: float, n_days: int) -> dict:
    """Per-variant statistics and the promotion screen (q is added by the caller over the family). The schema
    is the same for every variant; with fewer than 3 trades the statistics are NaN and every check fails."""
    if years <= 0 or n_days < 1:
        raise ValueError("need years > 0 and n_days >= 1")
    d = np.asarray(direction, float)
    if ((d != 0) & ~w["valid"].to_numpy()).any():
        raise ValueError("a direction targets an invalid window")
    trade = d != 0
    g = d[trade] * w["ret_ticks"].to_numpy()[trade]
    day = w["trading_day"].to_numpy()[trade]
    n = len(g)
    out = {"n": n, "trades_per_year": n / years, "gross": np.nan, "sd": np.nan, "t": np.nan, "p_one": np.nan,
           "net_base": np.nan, "net_stress": np.nan, "sharpe_net_base_ann": np.nan,
           **{f"gross_{k}": np.nan for k in BLOCKS}, **{f"n_{k}": int((block_of(day) == k).sum()) for k in BLOCKS},
           "mde_net_validation": np.nan, "sign_ok": False, "stress_ok": False, "power_ok": False}
    if n < 3:
        return out
    mean, sd = float(g.mean()), float(g.std(ddof=1))
    t = mean / (sd / math.sqrt(n)) if sd > 0 else np.nan
    p2 = t_pvalue(t, n - 1)
    blocks = block_means(pd.Series(g, index=day), "gross")
    daily = np.zeros(n_days)
    daily[:n] = g - BASE_TICKS  # no-trade days are zero; order is irrelevant for mean / sd
    daily_sd = daily.std(ddof=1)
    net_base = mean - BASE_TICKS
    mde = Z_POWER * sd / math.sqrt(VALIDATION_YEARS * n / years)
    positive = [blocks[f"gross_{k}"] > 0 for k in BLOCKS]
    out.update({
        "gross": mean, "sd": sd, "t": t, "p_one": p2 / 2 if t > 0 else 1 - p2 / 2,
        "net_base": net_base, "net_stress": mean - STRESS_TICKS,
        "sharpe_net_base_ann": float(daily.mean() / daily_sd * math.sqrt(252)) if daily_sd > 0 else np.nan,
        **blocks, "mde_net_validation": mde,
        "sign_ok": bool(sum(positive) >= 2 and positive[-1]), "stress_ok": bool(mean > STRESS_TICKS),
        "power_ok": bool(net_base >= 2 * mde),
    })
    return out


def family_table(variants: dict, years: float, n_days: int, in_family: set) -> pd.DataFrame:
    """One row per variant; BH and promotion only over `in_family`, the other rows are references."""
    rows = []
    for name, v in variants.items():
        emitted = np.asarray(v["emitted"], bool)
        rows.append({"variant": name, "in_family": name in in_family, "emitted": int(emitted.sum()),
                     "unevaluable": int((emitted & (v["dir"] == 0)).sum()),
                     **evaluate(v["w"], v["dir"], years, n_days)})
    tab = pd.DataFrame(rows)
    fam = tab["in_family"].to_numpy()
    tab["inconclusive"] = fam & tab["p_one"].isna().to_numpy()
    tab["q"] = np.nan
    tab.loc[fam, "q"] = bh_qvalues(tab.loc[fam, "p_one"].fillna(1.0).to_numpy())  # the family stays whole
    tab["q_ok"] = tab["q"] < Q_MAX
    tab["promote"] = (tab["in_family"] & ~tab["inconclusive"] & tab["q_ok"] & tab["sign_ok"] & tab["stress_ok"]
                      & tab["power_ok"])
    return tab


def _write_csv_atomic(path, frame: pd.DataFrame) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    frame.to_csv(tmp, index=False, float_format="%.5g")
    tmp.replace(path)


def _mark_failed(exc: Exception, stamp: str, final, tmp, written: list, cards_done: list) -> None:
    """A run that failed after the data were read is marked and logged, never rerun silently (R014).
    Ledger rows are the commit point and come last: if some were written they point at `final`, which then
    stays in place with an INCOMPLETE marker; otherwise every output of this run is set aside as .failed.
    The FAILED row is written even when this clean-up itself fails."""
    cleanup_error = None
    try:
        if written:
            (final / "INCOMPLETE").write_text(f"result rows written: {written}; {type(exc).__name__}: {exc}\n")
        else:
            for path in cards_done:
                path.unlink(missing_ok=True)
            for d in (tmp, final):
                if d.exists():
                    d.rename(final.with_name(final.name + ".failed"))
    except Exception as err:
        cleanup_error = err
    cleanup = f"; clean-up failed: {type(cleanup_error).__name__}: {cleanup_error}" if cleanup_error else ""
    ledger.append("H025", "exploratory", "discovery", n_tests=0, verdict="FAILED",
                  note=f"run {stamp} failed after reading data; result rows already written: {written or 'none'}; "
                       f"{type(exc).__name__}: {exc}{cleanup}")


def run_h025() -> None:
    cards = {"H025": H025_DIR / "explore.csv", "H026": H026_DIR / "explore.csv"}
    done_before = [str(p) for p in cards.values() if p.exists()]
    if done_before:
        raise FileExistsError(f"H025/H026 already ran (outputs exist: {done_before}); one run only")
    t0 = time.time()
    df = data.load_front("discovery", "H025", "H025/H026 settlement family exploration (R012 Q3 variants)")
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    final = paths.OUT_DIR / "settlement" / f"{stamp}_h025"
    tmp = final.with_name(final.name + ".partial")
    written, cards_done = [], []
    try:
        days = np.unique(df["trading_day"].to_numpy())
        years = (days[-1] - days[0] + 1) / 365.25
        variants, counts = h025_h026(df, days)
        tab = family_table(variants, years, len(days), set(FAMILY))
        tab["item"] = tab["variant"].map({**FAMILY, **REFERENCES})
        n_family = int(tab["in_family"].sum())
        parts = {item: tab[(tab["item"] == item) & tab["in_family"]] for item in cards}
        n_tests = {item: len(part) for item, part in parts.items()}
        manifest = {"items": list(cards), "stamp": stamp, "code_sha256": code_hash(), "data": fingerprint(df),
                    "years": years, "counts": counts, "lookback": LOOKBACK, "pctl": PCTL, "q_max": Q_MAX,
                    "base_ticks": BASE_TICKS, "stress_ticks": STRESS_TICKS, "n_tests": n_tests,
                    "seconds": round(time.time() - t0)}
        tmp.mkdir(parents=True, exist_ok=False)
        tab.to_csv(tmp / "family.csv", index=False)
        (tmp / "manifest.json").write_text(json.dumps(manifest, indent=1, default=str))
        tmp.rename(final)
        for item, path in cards.items():
            _write_csv_atomic(path, tab[tab["item"] == item])
            cards_done.append(path)
        for item, part in parts.items():  # commit point: ledger rows last
            ledger.append(item, "exploratory", "discovery", n_tests=n_tests[item],
                          statistic=f"settlement family (R012 Q3): one-sided t of gross ticks, BH over {n_family} "
                                    f"variants",
                          value=int(part["promote"].sum()), p_value=float(part["q"].min()),
                          verdict="EXPLORATORY", code_sha256=manifest["code_sha256"],
                          data_sha256=manifest["data"]["sha256_all_columns"],
                          output=str(final.relative_to(paths.ROOT)),
                          note=f"run {stamp}; value = variants promoted of {len(part)}; family of {n_family} split "
                               f"{n_tests}; naive reference row outside BH and the test count; counts {counts}")
            written.append(item)
    except Exception as exc:
        _mark_failed(exc, stamp, final, tmp, written, cards_done)
        raise
    with pd.option_context("display.width", 250, "display.max_columns", 40):
        print(tab.round(4).to_string(index=False))
    print(json.dumps(counts))
    print(f"H025/H026: promoted {int(tab['promote'].sum())} of {n_family}; outputs {final}; {time.time() - t0:.0f} s")


def main(argv=None) -> None:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("family", choices=["h025"])
    p.parse_args(argv)
    run_h025()


if __name__ == "__main__":
    main()
