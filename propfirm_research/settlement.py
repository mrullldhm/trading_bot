"""Settlement-window hypothesis harness: H025 / H026 (existing bars) and the stage-1 families H027 / H028 (D010 data).

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

Stage 1 (H027 TAS / signed flow, H028 cross-energy; cards section 4, Codex R016): 2015-16 trading days only; the
same windows, fills, costs, estimand and BH as above; the stage-1 screen (`stage1_table`) replaces the three-block
sign check: q < 0.10, gross > 0 in 2015 and in 2016, >= 25 trades a year, gross > stress cost, net >= 2 x MDE,
no single day above 25% of the gross P&L. A pass only justifies buying 2010-14; nothing is promoted. A run needs
the S004 data audit's acceptance (on the same files) and then claims its one attempt atomically
(`stage1_attempt.json` in the card folder, never removed, R018 B1) before reading any data.

Usage: python -m propfirm_research.settlement h025 | h027 | h028
"""

import argparse
import json
import math
import os
import time
from collections import deque
from datetime import date, datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from . import data, grid, ledger, paths
from .costs import BASE_TICKS, STRESS_TICKS
from .periods import epoch_day
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


def variant_record(windows: pd.DataFrame, emitted: np.ndarray, direction) -> dict:
    """Emitted at entry; evaluated (non-zero direction) only where the exact exit bar exists (D009, R014)."""
    evaluated = emitted & windows["valid"].to_numpy()
    return {"w": windows, "dir": np.where(evaluated, direction, 0.0), "emitted": emitted}


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


def _mark_failed(exc: Exception, stamp: str, final, tmp, written: list, cards_done: list, item: str = "H025") -> None:
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
    ledger.append(item, "exploratory", "discovery", n_tests=0, verdict="FAILED",
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


# --- stage 1 (D008, D010): H027 TAS / signed flow, H028 cross-energy, on 2015-16 only ----------------------

STAGE1 = (epoch_day(date(2015, 1, 1)), epoch_day(date(2016, 12, 31)))
UNWIND_ENTRY, UNWIND_EXIT = 14 * 60 + 31, 15 * 60
RESIDUAL_WINDOW, UNWIND_WINDOW = (14 * 60 + 25, 14 * 60 + 35), (14 * 60 + 20, 14 * 60 + 30)  # ts_event ET minutes
TAS_CLOSE, DAY_START = 14 * 60 + 30, 18 * 60  # the TAS session of a CME day: 18:00 ET the evening before -> 14:30
SIDE_RULE_PERCENT = 99  # a day needs >= 99% of its volume signed (R016); integer test, no float edge
VOL_DAYS = 20
MIN_TRADES_PER_YEAR = 25
DAY_SHARE_MAX = 0.25
H027_DIR = paths.RESEARCH_DIR / "hypotheses" / "H027-tas-settlement-flow"
H028_DIR = paths.RESEARCH_DIR / "hypotheses" / "H028-cross-energy-settlement"
S004_FACTS = paths.RESEARCH_DIR / "studies" / "S004-stage1-data" / "facts.json"
ATTEMPT_MARKER = "stage1_attempt.json"
AUDITED_TABLES = ("bars", "tas", "cl_mbp1", "statistics", "energy")
STAGE1_FAMILIES = {
    "H027": ["v1_tas_residual", "v2_tas_unwind", "v3_outright_residual", "v4_outright_unwind"],
    "H028": ["v1_products", "v2_brent", "v3_agreement"],
}
CARD_DIRS = {"H027": H027_DIR, "H028": H028_DIR}


def quote_side(price, bid, ask) -> np.ndarray:
    """+1 at or above the ask, -1 at or below the bid, 0 inside the spread or on a locked / crossed / empty book."""
    price, bid, ask = (np.asarray(x, float) for x in (price, bid, ask))
    ok = np.isfinite(bid) & np.isfinite(ask) & (ask > bid)
    return np.where(ok & (price >= ask), 1, np.where(ok & (price <= bid), -1, 0)).astype(np.int8)


def cutoff_ns(days: np.ndarray, mod: int) -> np.ndarray:
    """UTC ns of ET clock time `mod` on each trading day: a trade feeds the decision only if known strictly before."""
    return grid.clock_tmin(np.asarray(days, np.int64), mod).astype(np.int64) * data.NS_PER_MIN


def coverage_ok(sided, volume) -> np.ndarray:
    """Traded volume and at least 99% of it signed; exactly 1% unsigned still passes (card section 4)."""
    sided, volume = np.asarray(sided, float), np.asarray(volume, float)
    with np.errstate(invalid="ignore"):
        return (volume > 0) & (100 * sided >= SIDE_RULE_PERCENT * volume)


def front_tas_symbol(contract) -> str | None:
    """CLT outright for a CL contract key: CLN5@2015-07 -> CLTN5."""
    return None if contract is None or pd.isna(contract) else "CLT" + str(contract).split("@")[0][2:]


def _per_day(frame: pd.DataFrame, days: np.ndarray, cutoff: np.ndarray) -> pd.DataFrame:
    """Rows of `frame` on `days` that are known before that day's cutoff."""
    frame = frame[frame["trading_day"].isin(days)]
    cut = pd.Series(cutoff, index=days).reindex(frame["trading_day"]).to_numpy()
    return frame[frame["known_ns"].to_numpy() < cut]


def tas_imbalance(tas: pd.DataFrame, days: np.ndarray, entry_contract, cutoff: np.ndarray) -> pd.DataFrame:
    """Per day: signed front-outright TAS volume of the TAS session (events before the 14:30 close) known before the
    cutoff. ok needs one instrument id for the front raw symbol (CLT + the entry contract's month code), traded
    volume, and a side on >= 99% of it."""
    front = pd.Series([front_tas_symbol(c) for c in entry_contract], index=days)
    in_session = (tas["mod"] < TAS_CLOSE) | (tas["mod"] >= DAY_START)
    t = _per_day(tas[~tas["is_spread"] & in_session], days, cutoff)
    t = t[t["raw_symbol"].to_numpy() == front.reindex(t["trading_day"]).to_numpy()]
    g = t.assign(signed=t["size"] * t["side"], sided=t["size"] * (t["side"] != 0)).groupby("trading_day")
    out = pd.DataFrame({"imb": g["signed"].sum(), "volume": g["size"].sum(), "sided": g["sided"].sum(),
                        "ids": g["instrument_id"].nunique()}).reindex(days)
    out["ok"] = (out["ids"] == 1).to_numpy() & coverage_ok(out["sided"], out["volume"])
    return out


def outright_imbalance(cl: pd.DataFrame, days: np.ndarray, entry_contract, window: tuple[int, int],
                       cutoff: np.ndarray) -> pd.DataFrame:
    """Per day: signed CL.v.0 volume of trades with ts_event in the ET-minute window [a, b), known before the cutoff;
    side = the reported aggressor, else the quote rule. ok needs >= 99% classified volume and every trade in the
    entry contract."""
    c = _per_day(cl[(cl["mod"] >= window[0]) & (cl["mod"] < window[1])], days, cutoff)
    rep = c["side"].to_numpy()
    s = np.where(rep != 0, rep, quote_side(c["price"], c["bid"], c["ask"]))
    want = pd.Series(list(entry_contract), index=days).reindex(c["trading_day"]).to_numpy()
    g = c.assign(signed=c["size"] * s, sided=c["size"] * (s != 0),
                 other=(c["contract"].to_numpy() != want).astype(int)).groupby("trading_day")
    out = pd.DataFrame({"imb": g["signed"].sum(), "volume": g["size"].sum(), "sided": g["sided"].sum(),
                        "other_contract": g["other"].sum()}).reindex(days)
    out["ok"] = coverage_ok(out["sided"], out["volume"]) & (out["other_contract"] == 0).to_numpy()
    return out


def filtered(score: np.ndarray, eligible: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """(fires, threshold): |score| strictly above the 75th percentile of the previous 60 eligible days."""
    thr = trailing_threshold(np.abs(score), eligible)
    with np.errstate(invalid="ignore"):
        fire = eligible & (np.abs(score) > thr) & (score != 0)
    return fire, thr


def h027(df: pd.DataFrame, days: np.ndarray, tas: pd.DataFrame, cl: pd.DataFrame,
         expiry_tmin: dict | None = None) -> tuple[dict, dict]:
    """The frozen H027 family (card section 4). Returns ({variant: record}, counts)."""
    days = np.asarray(days, dtype=np.int64)
    if not np.all(np.diff(days) > 0):
        raise ValueError("days must be strictly increasing")
    w = grid.windows(df, [(ENTRY, grid.FLAT), (UNWIND_ENTRY, UNWIND_EXIT)], days=days, expiry_tmin=expiry_tmin)
    w_res = w[w["start_mod"] == ENTRY].reset_index(drop=True)
    w_unw = w[w["start_mod"] == UNWIND_ENTRY].reset_index(drop=True)
    specs = {  # variant: (windows, signal, direction sign)
        "v1_tas_residual": (w_res, tas_imbalance(tas, days, w_res["entry_contract"], cutoff_ns(days, ENTRY)), 1.0),
        "v2_tas_unwind": (w_unw, tas_imbalance(tas, days, w_unw["entry_contract"], cutoff_ns(days, UNWIND_ENTRY)),
                          -1.0),
        "v3_outright_residual": (w_res, outright_imbalance(cl, days, w_res["entry_contract"], RESIDUAL_WINDOW,
                                                           cutoff_ns(days, ENTRY)), 1.0),
        "v4_outright_unwind": (w_unw, outright_imbalance(cl, days, w_unw["entry_contract"], UNWIND_WINDOW,
                                                         cutoff_ns(days, UNWIND_ENTRY)), -1.0),
    }
    variants, counts = {}, {"days": int(len(days))}
    for name, (wv, sig, sign) in specs.items():
        score = sig["imb"].to_numpy(float)
        eligible = sig["ok"].to_numpy() & wv["entry_ok"].to_numpy()
        fire, thr = filtered(score, eligible)
        variants[name] = variant_record(wv, fire, sign * np.sign(np.nan_to_num(score)))
        counts[name] = {"signal_ok": int(sig["ok"].sum()), "eligible": int(eligible.sum()),
                        "warmup": int((eligible & np.isnan(thr)).sum()), "emitted": int(fire.sum()),
                        "entry_invalid": int((~wv["entry_ok"]).sum()),
                        "exit_missing": int((fire & wv["exit_missing"].to_numpy()).sum())}
    return variants, counts


def bar_endpoints(bars: pd.DataFrame, days: np.ndarray) -> pd.DataFrame:
    """Per day: open of the 14:25 bar and close of the 14:34 bar, both present and in one contract."""
    a = bars[bars["mod"] == SIG_START].drop_duplicates("trading_day").set_index("trading_day")
    b = bars[bars["mod"] == SIG_END].drop_duplicates("trading_day").set_index("trading_day")
    j = a[["open", "contract"]].join(b[["close", "contract"]], lsuffix="_a", rsuffix="_b", how="inner")
    j = j[j["contract_a"] == j["contract_b"]]
    return pd.DataFrame({"p0": j["open"], "p1": j["close"], "contract": j["contract_a"]}).reindex(days)


def bz_endpoints(bars: pd.DataFrame, days: np.ndarray) -> pd.DataFrame:
    """BZ staleness rule: start = open of the 14:25 bar, else close of the last bar starting 14:22-14:24; end = close
    of the last bar starting 14:32-14:34; one contract, one trading day (nothing carried across days)."""
    g = bars[(bars["mod"] >= SIG_START - 3) & (bars["mod"] <= SIG_END)]
    at = g[g["mod"] == SIG_START].drop_duplicates("trading_day").set_index("trading_day")
    early = g[g["mod"] < SIG_START].groupby("trading_day").last()
    end = g[g["mod"] >= SIG_END - 2].groupby("trading_day").last()
    p0 = at["open"].combine_first(early["close"])
    c0 = at["contract"].combine_first(early["contract"])
    j = pd.DataFrame({"p0": p0, "c0": c0}).join(end[["close", "contract"]], how="inner")
    j = j[j["c0"] == j["contract"]]
    return pd.DataFrame({"p0": j["p0"], "p1": j["close"], "contract": j["contract"]}).reindex(days)


def _log_return(ends: pd.DataFrame) -> pd.DataFrame:
    return pd.DataFrame({"r": np.log(ends["p1"] / ends["p0"]), "contract": ends["contract"]})


def bar_return(bars: pd.DataFrame, days: np.ndarray) -> pd.DataFrame:
    """Per day: log(close of the 14:34 bar / open of the 14:25 bar), both bars present, one contract."""
    return _log_return(bar_endpoints(bars, days))


def bz_return(bars: pd.DataFrame, days: np.ndarray) -> pd.DataFrame:
    return _log_return(bz_endpoints(bars, days))


def trailing_sd(r: np.ndarray, lookback: int = VOL_DAYS) -> np.ndarray:
    """Per day: sample sd (ddof 1) of r over the previous `lookback` days on which r exists, today excluded;
    NaN until `lookback` such days have passed."""
    out = np.full(len(r), np.nan)
    past = deque(maxlen=lookback)
    for i, v in enumerate(r):
        if len(past) == lookback:
            out[i] = np.std(np.fromiter(past, float), ddof=1)
        if np.isfinite(v):
            past.append(float(v))
    return out


def h028(df: pd.DataFrame, days: np.ndarray, related: dict, expiry_tmin: dict | None = None) -> tuple[dict, dict]:
    """The frozen H028 family (card section 4). related: {"RB.v.0": bars, "HO.v.0": bars, "BZ.v.0": bars}."""
    days = np.asarray(days, dtype=np.int64)
    if not np.all(np.diff(days) > 0):
        raise ValueError("days must be strictly increasing")
    w = grid.windows(df, [(ENTRY, grid.FLAT)], days=days, expiry_tmin=expiry_tmin).reset_index(drop=True)
    entry_ok = w["entry_ok"].to_numpy()
    ret = {"CL": bar_return(df, days), "RB": bar_return(related["RB.v.0"], days),
           "HO": bar_return(related["HO.v.0"], days), "BZ": bz_return(related["BZ.v.0"], days)}
    cl_ok = ret["CL"]["contract"].to_numpy() == w["entry_contract"].to_numpy()
    ret["CL"].loc[~cl_ok, "r"] = np.nan  # the CL return must be in the entry contract
    z = {}
    for k, v in ret.items():
        r = v["r"].to_numpy(float)
        sd = trailing_sd(r)
        with np.errstate(invalid="ignore", divide="ignore"):
            z[k] = np.where(np.isfinite(sd) & (sd > 0), r / sd, np.nan)
    with np.errstate(invalid="ignore"):
        s1 = (z["RB"] + z["HO"]) / 2 - z["CL"]
        s2 = z["BZ"] - z["CL"]
        u = np.vstack([z["RB"] - z["CL"], z["HO"] - z["CL"], z["BZ"] - z["CL"]])
        agree = np.all(np.isfinite(u), axis=0) & (np.all(u > 0, axis=0) | np.all(u < 0, axis=0))
        s3 = np.where(agree, np.sign(u[0]), np.nan)
    variants, counts = {}, {"days": int(len(days)), "entry_ok": int(entry_ok.sum()),
                            "returns": {k: int(v["r"].notna().sum()) for k, v in ret.items()},
                            "cl_contract_mismatch": int((~cl_ok & entry_ok & ret["CL"]["contract"].notna().to_numpy()).sum())}
    for name, score in (("v1_products", s1), ("v2_brent", s2), ("v3_agreement", s3)):
        ok = np.isfinite(score)
        fire = ok & entry_ok & (np.nan_to_num(score) != 0)
        variants[name] = variant_record(w, fire, np.sign(np.nan_to_num(score)))
        counts[name] = {"signal_ok": int(ok.sum()), "emitted": int(fire.sum()),
                        "exit_missing": int((fire & w["exit_missing"].to_numpy()).sum())}
    return variants, counts


SCREEN = ("q_ok", "years_ok", "trades_ok", "stress_ok", "power_ok", "day_share_ok")


def screen_pass(tab: pd.DataFrame) -> pd.Series:
    """The stage-1 screen: a family member that is testable and meets every condition in SCREEN."""
    return tab["in_family"] & ~tab["inconclusive"] & tab[list(SCREEN)].all(axis=1)


def stage1_table(variants: dict, years: float, n_days: int, family: list) -> pd.DataFrame:
    """family_table plus the stage-1 screen (R016 Q3). Stage 1 never promotes to a pre-registration: `stage1_pass`
    only justifies buying 2010-14 (a new owner decision)."""
    tab = family_table(variants, years, n_days, set(family))
    extra = []
    for name in tab["variant"]:
        v = variants[name]
        trade = v["dir"] != 0
        g = v["dir"][trade] * v["w"]["ret_ticks"].to_numpy()[trade]
        yr = pd.to_datetime(v["w"]["trading_day"].to_numpy()[trade], unit="D").year
        by = pd.Series(g).groupby(yr).mean()
        total = g.sum()
        extra.append({"gross_2015": by.get(2015, np.nan), "gross_2016": by.get(2016, np.nan),
                      "max_day_share": float(g.max() / total) if len(g) and total > 0 else np.nan})
    tab = pd.concat([tab, pd.DataFrame(extra)], axis=1)
    tab["years_ok"] = (tab["gross_2015"] > 0) & (tab["gross_2016"] > 0)
    tab["trades_ok"] = tab["trades_per_year"] >= MIN_TRADES_PER_YEAR
    tab["day_share_ok"] = tab["max_day_share"] <= DAY_SHARE_MAX
    tab["stage1_pass"] = screen_pass(tab)
    tab["promote"] = False
    three_block = ["sign_ok"] + [c for c in tab.columns if c.endswith(("2010-12", "2013-14"))]
    return tab.drop(columns=three_block)  # the three-block screen does not apply to a 2015-16 run


def s004_accepted() -> dict:
    """The run needs the S004 audit's acceptance (the 'no data-integrity failure' condition of the screen), made on
    exactly the files the run will read."""
    if not S004_FACTS.exists():
        raise RuntimeError("no S004 facts: run the stage-1 data audit first")
    facts = json.loads(S004_FACTS.read_text())["facts"]
    if not facts.get("acceptance", {}).get("all_ok"):
        raise RuntimeError(f"S004 did not accept the data: {facts.get('acceptance')}")
    audited = facts.get("data_sha256") or {}
    stale = sorted(t for t in AUDITED_TABLES if audited.get(t) != data.digest(t, "discovery"))
    if stale:
        raise RuntimeError(f"data changed since the S004 audit (rerun S004): {stale}")
    return facts["acceptance"]


def h025_overlap(df: pd.DataFrame, days: np.ndarray, variants: dict) -> dict:
    """Descriptive only: share of each variant's emitted days (entry-time signal) that are also H025 v1 emitted
    days. Both sides use the entry-time mask, so a missing exit bar cannot move it."""
    all_days = np.unique(df["trading_day"].to_numpy())
    h25, _ = h025_h026(df, all_days)
    v1 = pd.Series(h25["v1_move_filter"]["emitted"], index=all_days).reindex(days, fill_value=False).to_numpy()
    out = {}
    for name, v in variants.items():
        emitted = np.asarray(v["emitted"], bool)
        out[name] = float((emitted & v1).sum() / emitted.sum()) if emitted.any() else float("nan")
    return out


def claim_attempt(item: str) -> Path:
    """Atomically claim the one stage-1 attempt of `item` before any market data is read. The marker is never removed:
    a finished, failed or interrupted attempt blocks every rerun (R018 B1)."""
    marker = CARD_DIRS[item] / ATTEMPT_MARKER
    marker.parent.mkdir(parents=True, exist_ok=True)
    try:
        fd = os.open(marker, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        raise FileExistsError(f"{item}: a stage-1 attempt already exists ({marker}); one attempt only") from None
    with os.fdopen(fd, "w") as f:
        json.dump({"claimed_utc": datetime.now(timezone.utc).isoformat(), "pid": os.getpid()}, f)
    return marker


def _close_attempt(marker: Path, **fields) -> None:
    """Record the attempt's end; replace atomically so an interrupt never truncates the marker."""
    claim = json.loads(marker.read_text())
    tmp = marker.with_name(marker.name + ".tmp")
    tmp.write_text(json.dumps({**claim, **fields}))
    tmp.replace(marker)


def _finish_marker(marker: Path, **fields) -> list:
    """Record the attempt's end; if that fails, write a fresh marker that does not depend on reading the old one.
    Returns the problems met; never raises (the claimed marker exists either way, so reruns stay blocked)."""
    problems = []
    try:
        _close_attempt(marker, **fields)
    except BaseException as err:
        problems.append(f"attempt marker not closed: {type(err).__name__}: {err}")
        try:
            tmp_marker = marker.with_name(marker.name + ".tmp")
            tmp_marker.write_text(json.dumps({**fields, "problems": [*fields.get("problems", []), *problems]}))
            tmp_marker.replace(marker)
        except BaseException as err2:
            problems.append(f"fallback marker not written: {type(err2).__name__}: {err2}")
    return problems


def run_stage1(item: str) -> None:
    card = CARD_DIRS[item] / "explore.csv"
    if card.exists() or (CARD_DIRS[item] / ATTEMPT_MARKER).exists():
        raise FileExistsError(f"{item} already has a stage-1 attempt; one attempt only")
    acceptance = s004_accepted()  # a refused audit does not spend the attempt
    t0 = time.time()
    purpose = f"{item} stage-1 family run (2015-16, card section 4)"
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    final = paths.OUT_DIR / "settlement" / f"{stamp}_{item.lower()}"
    tmp = final.with_name(final.name + ".partial")
    written, cards_done = [], []
    marker = claim_attempt(item)
    try:  # everything after the claim, the first data read included, ends DONE or FAILED
        df = data.load_front("discovery", item, purpose)
        all_days = np.unique(df["trading_day"].to_numpy())
        days = all_days[(all_days >= STAGE1[0]) & (all_days <= STAGE1[1])]
        if item == "H027":
            tas = data.load_trades("tas", "discovery", item, purpose)
            cl = data.load_trades("cl_mbp1", "discovery", item, purpose)
            variants, counts = h027(df, days, tas, cl)
        else:
            related = {s: data.load_related(s, "discovery", item, purpose) for s in data.RELATED}
            variants, counts = h028(df, days, related)
        years = (days[-1] - days[0] + 1) / 365.25
        family = STAGE1_FAMILIES[item]
        tab = stage1_table(variants, years, len(days), family)
        tab["item"] = item
        overlap = h025_overlap(df, days, variants)
        inputs = {"bars": df.attrs["data_sha256"], **({"tas": tas.attrs["data_sha256"],
                                                       "cl_mbp1": cl.attrs["data_sha256"]} if item == "H027" else
                                                      {"energy": related["RB.v.0"].attrs["data_sha256"]})}
        manifest = {"item": item, "stamp": stamp, "code_sha256": code_hash(), "data": fingerprint(df),
                    "inputs_sha256": inputs, "data_sha256": data.combine_digests(inputs),
                    "years": years, "counts": counts, "h025_v1_overlap": overlap, "s004_acceptance": acceptance,
                    "base_ticks": BASE_TICKS, "stress_ticks": STRESS_TICKS, "seconds": round(time.time() - t0)}
        tmp.mkdir(parents=True, exist_ok=False)
        tab.to_csv(tmp / "family.csv", index=False)
        (tmp / "manifest.json").write_text(json.dumps(manifest, indent=1, default=str))
        tmp.rename(final)
        _write_csv_atomic(card, tab)
        cards_done.append(card)
        ledger.append(item, "exploratory", "discovery", n_tests=len(family),
                      statistic=f"stage-1 family (R016): one-sided t of gross ticks, BH over {len(family)} variants",
                      value=int(tab["stage1_pass"].sum()), p_value=float(tab["q"].min()), verdict="EXPLORATORY",
                      code_sha256=manifest["code_sha256"], data_sha256=manifest["data_sha256"],
                      output=str(final.relative_to(paths.ROOT)),
                      note=f"run {stamp}; 2015-16 only; value = variants passing the stage-1 screen of {len(family)}; "
                           f"counts {counts}")
        written.append(item)
    except BaseException as exc:  # an interrupt also ends the attempt as FAILED
        problems = []  # clean-up errors are noted on the original error, never raised in its place
        error = f"{type(exc).__name__}: {exc}"[:300]
        try:
            _mark_failed(exc, stamp, final, tmp, written, cards_done, item=item)
        except BaseException as err:
            problems.append(f"FAILED ledger row not written: {type(err).__name__}: {err}")
        problems += _finish_marker(marker, status="FAILED", stamp=stamp, error=error, problems=list(problems))
        for note in problems:
            exc.add_note(note)
        raise
    for problem in _finish_marker(marker, status="DONE", stamp=stamp, output=str(final.relative_to(paths.ROOT))):
        print(f"WARNING: {problem} (the run is committed in the ledger; the marker still blocks a rerun)")
    with pd.option_context("display.width", 250, "display.max_columns", 50):
        print(tab.round(4).to_string(index=False))
    print(json.dumps({"counts": counts, "h025_v1_overlap": overlap}, default=str))
    print(f"{item}: stage-1 pass {int(tab['stage1_pass'].sum())} of {len(family)}; outputs {final}; "
          f"{time.time() - t0:.0f} s")


def main(argv=None) -> None:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("family", choices=["h025", "h027", "h028"])
    a = p.parse_args(argv)
    if a.family == "h025":
        run_h025()
    else:
        run_stage1(a.family.upper())


if __name__ == "__main__":
    main()
