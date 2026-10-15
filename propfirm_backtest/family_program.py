"""Strategies 3-5 (ZAB, Crabel, Fisher ACD) as ONE research programme.

Usage:
    python -m propfirm_backtest.family_program     # after family_search zab, crabel and acd

Each family selected its own champion. Testing three families means three chances to get lucky, so
the overfitting checks are also run on the UNION of their configurations:
- deflated Sharpe of each champion against all unique trade streams of the three families
  (conservative) and against the effective number of independent streams (optimistic);
- PBO (CSCV) on a seeded random sample of unique streams from the union;
- ONE primary champion nominated from development data only: the eligible family champion with the
  best Combine score (none if no family champion is eligible);
- after holdouts: Holm correction of the families' bootstrap p-values (alpha = ALPHA).
Report: data/backtests/orb_families_program.md
"""

import json
import sys

import numpy as np
import pandas as pd

from propfirm_data.config import DATA_DIR

from . import bars as B
from . import orb_search as O
from . import search as S
from .family_search import FAMILIES

ALPHA = 0.10
OUT_FILE = DATA_DIR / "backtests" / "orb_families_program.md"
UNIQUE = ["stream_hash", "trades", "total_usd"]


def holm(pvalues: dict, alpha=ALPHA, m=None) -> dict:
    """Holm step-down: {name: rejected?}. Smallest p first; stop at the first non-rejection.
    m = number of hypotheses in the programme (families not yet tested count with p = 1)."""
    order = sorted(pvalues, key=pvalues.get)
    out, m = {}, max(len(order), m or 0)
    stopped = False
    for i, name in enumerate(order):
        stopped = stopped or pvalues[name] > alpha / (m - i)
        out[name] = not stopped
    return out


def nominate(frozen: dict, results: dict):
    """The eligible family champion with the best grid score, or None."""
    best, best_score = None, -np.inf
    for name, fr in frozen.items():
        if not fr["champion_eligible"]:
            continue
        sc = float(results[name].iloc[0]["score"])
        if sc > best_score:
            best, best_score = name, sc
    return best


def locate(grid, part: pd.DataFrame) -> np.ndarray:
    """Grid rows of result rows (matched on the dimension labels)."""
    lab = grid.labels.astype(str)
    key = pd.MultiIndex.from_frame(lab)
    want = pd.MultiIndex.from_frame(part[grid.keys].astype(str))
    pos = key.get_indexer(want)
    if (pos < 0).any():
        raise RuntimeError("result rows do not match the current grid: re-run family_search")
    return pos



def main() -> int:
    frozen, results = {}, {}
    for name, fam in FAMILIES.items():
        f = fam.out_dir / "frozen_picks.json"
        if not f.exists():
            print(f"Missing {f}. Run: python -m propfirm_backtest.family_search {name}")
            return 1
        frozen[name] = json.loads(f.read_text())
        results[name] = pd.read_csv(fam.out_dir / "results.csv.gz")  # sorted by rank: row 0 = champion

    print("Loading development data...", flush=True)
    m = B.load_minutes(end=O.DEV_END)
    cal = S.Calendar(m)
    if cal.n_dev != len(cal.days):
        raise RuntimeError("holdout data must not be loaded here")
    devs = {name: O.Dev(m, cal, fam) for name, fam in FAMILIES.items()}

    union = pd.concat([r.assign(family=n) for n, r in results.items()], ignore_index=True)
    live = union[union["trades"] > 0].drop_duplicates(UNIQUE)
    n_unique = len(live)
    rng = np.random.default_rng(O.SEED)
    sample = live.sample(min(O.N_PBO, n_unique), random_state=O.SEED)
    daily = []
    for name, part in sample.groupby("family"):
        grid = O.Grid(family=FAMILIES[name])
        cfg = grid.cfg[locate(grid, part)]
        daily.append(devs[name].daily(cfg)[0])
    daily = np.vstack(daily)
    pbo = O.pbo_cscv(daily)
    x = daily[daily.std(axis=1) > 0]
    pick = x[rng.choice(len(x), min(O.N_EFF_SAMPLE, len(x)), replace=False)]
    lam = np.clip(np.linalg.eigvalsh(np.corrcoef(pick)), 0, None)
    n_eff = float(min(n_unique, lam.sum() ** 2 / (lam ** 2).sum()))
    sharpe_var = float(np.var(live["sharpe_daily"]))

    rows = []
    for name, fam in FAMILIES.items():
        grid = O.Grid(family=fam)
        champ = results[name].iloc[[0]]
        cd = devs[name].daily(grid.cfg[locate(grid, champ)])[0][0]
        rows.append({"family": name, "champion": fam.label(champ.iloc[0]),
                     "eligible": frozen[name]["champion_eligible"], "trades": int(champ["trades"].iloc[0]),
                     "expectancy": float(champ["expectancy_usd"].iloc[0]), "score": float(champ["score"].iloc[0]),
                     "dsr_union": O.deflated_sharpe(cd, sharpe_var, n_unique),
                     "dsr_union_eff": O.deflated_sharpe(cd, sharpe_var, n_eff)})
    primary = nominate(frozen, results)

    pvals = {}
    for name, fam in FAMILIES.items():
        raw = fam.out_dir / "holdout_raw.json"
        if raw.exists():
            pvals[name] = json.loads(raw.read_text())["stats"].get("p_value", 1.0)
    rejected = holm(pvals, m=len(FAMILIES)) if pvals else {}

    fmt = S.fmt
    L = ["# Strategies 3-5 (ZAB, Crabel, Fisher ACD): programme-level checks", "",
         f"Generated {pd.Timestamp.now(tz='UTC'):%Y-%m-%d %H:%M} UTC. Development data only (2010-06 -> 2021-12), "
         "except the Holm section, which uses holdout results if any were opened.", "",
         f"- Unique trade streams across the three families: {n_unique:,}; effective independent streams "
         f"(lower-bound estimate): {n_eff:,.0f}",
         f"- PBO (CSCV) on {len(daily):,} random unique streams from the union: {fmt(pbo, pct=True)}",
         f"- **Primary champion (nominated before any holdout): {primary or 'none: no family champion passed every gate'}**", "",
         "| Family | Champion | Eligible | Trades | Expectancy | Grid score | DSR (all unique) | DSR (effective) |",
         "|---|---|---|---|---|---|---|---|"]
    for r in rows:
        L.append(f"| {r['family']} | {r['champion']} | {'yes' if r['eligible'] else 'no'} | {r['trades']:,} | "
                 f"{fmt(r['expectancy'], money=True)} | {fmt(r['score'], pct=True)} | {fmt(r['dsr_union'], pct=True)} | "
                 f"{fmt(r['dsr_union_eff'], pct=True)} |")
    L += ["", f"## Holm correction across opened holdouts (alpha {ALPHA:.0%})", ""]
    if pvals:
        L += [f"m = {len(FAMILIES)} (unopened families count as p = 1).", "",
              "| Family | Bootstrap tail probability | Survives Holm |", "|---|---|---|"]
        L += [f"| {n} | {p:.3f} | {'yes' if rejected[n] else 'no'} |" for n, p in sorted(pvals.items(), key=lambda kv: kv[1])]
    else:
        L.append("No holdout opened yet.")
    OUT_FILE.write_text("\n".join(L))
    print(f"Report: {OUT_FILE}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
