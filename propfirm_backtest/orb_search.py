"""ORB, step 1 of 2: full-factorial grid + selection on DEVELOPMENT data only (2010-06 -> 2021-12).

Usage:
    python -m propfirm_backtest.orb_search            # full grid (1,056,000 configs, ~20 min)
    python -m propfirm_backtest.orb_search --quick    # small grid, pipeline smoke test

Never loads 2022+ data. Freezes ONE champion in frozen_picks.json; finalists are diagnostics only.
Step 2 (python -m propfirm_backtest.orb_holdout) tests the champion ONCE on 2022 -> today.

Rules frozen before looking at results:
- Score = lower 95% bound of the Topstep 50K Combine pass probability (block bootstrap, same
  random days for every config).
- Gates: >= 300 trades and >= 25 trades/year; profitable at 1 AND 2 ticks slippage; profitable in
  >= 60% of years; best year <= 50% and best day <= 25% of profit; p95 drawdown <= $1,000.
- Plateau: median score over the config and its ordinal neighbours (range length, buffer, fixed
  stop size, target, entry window, flat time); >= 60% of neighbours must be profitable.
  Categories (anchor, trigger, direction, width filter, breakeven) have no neighbours.
- Champion = best plateau score among configs passing everything.
- Walk-forward (2014-2021): each year the WHOLE selector (gates + plateau) runs on earlier years
  only; a PASS verdict needs that procedure to make money out of sample.
- Overfitting: deflated Sharpe at the number of unique trade streams and at an effective trial
  count; probability of backtest overfitting (CSCV) on the top configs.
"""

import hashlib
import itertools
import json
import math
import sys
import time
import warnings
from pathlib import Path
from statistics import NormalDist

import numpy as np
import pandas as pd

from propfirm_data.config import DATA_DIR, DEFINITIONS_FILE
from propfirm_data.eia_calendar import OUT_FILE as EIA_FILE
from propfirm_data.eia_calendar import load_releases

from . import bars as B
from . import orb_engine as E
from . import propsim as P
from . import search as S

OUT_DIR = DATA_DIR / "backtests" / "orb"
DEV_END = S.DEV_END
BASE_SLIP, GATE_SLIP = 1.0, 2.0
STRESS_SLIPS = [3.0, 4.0]
N_SIMS, N_SIMS_WF, N_SIMS_FINAL = 2000, 300, 20000
FINAL_BLOCKS = [5, 10, 20]
N_FINALISTS = 20
N_PBO = 5000
N_EFF_SAMPLE = 3000
WF_YEARS = list(range(2014, 2022))
CHUNK = 50_000
SEED = 12345
SOURCE_FILES = ["bars.py", "propsim.py", "search.py", "orb_engine.py", "orb_search.py", "orb_holdout.py",
                "../propfirm_data/eia_calendar.py", "../propfirm_data/config.py"]

GATES = {
    "min_trades": 300,
    "min_trades_per_year": 25,
    "min_positive_year_frac": 0.6,
    "max_best_year_share": 0.5,
    "max_best_day_share": 0.25,
    "max_p95_drawdown": 1000.0,
    "min_neighbours_profitable": 0.6,
}
WF_MIN_TRADES = 100  # early folds have only 3-4 years: absolute floor + the same per-year rate

# dimension -> levels (labels). Order = axis order of the dense grid.
DIMS = {
    "anchor": list(E.ANCHORS),
    "range_min": E.RANGE_LENGTHS,
    "trigger": ["stop", "close1", "close5"],
    "buffer": [0, 2],
    "stop": ["mid", "opposite", "15", "20", "30"],
    "target": ["1R", "1.5R", "2R", "3R", "none"],
    "window_min": [30, 60, 120],
    "flat": ["+60", "+120", "+240", "session"],
    "direction": ["both1", "both2", "long", "short"],
    "width": ["none", "skip_wide", "skip_narrow", "mid_only"],
    "breakeven": ["off", "on"],
}
KEYS = list(DIMS)
TRIGGER_CODE = {"stop": E.STOP, "close1": E.CLOSE1, "close5": E.CLOSE5}
STOP_CODE = {"mid": (E.MID, 0), "opposite": (E.OPPOSITE, 0), "15": (E.FIXED, 15), "20": (E.FIXED, 20),
             "30": (E.FIXED, 30)}
TARGET_X10 = {"1R": 10, "1.5R": 15, "2R": 20, "3R": 30, "none": 0}
FLAT_MIN = {"+60": 60, "+120": 120, "+240": 240, "session": E.SESSION}
DIR_CODE = {"both1": E.BOTH1, "both2": E.BOTH2, "long": E.LONG, "short": E.SHORT}
WIDTH_CODE = {"none": E.W_NONE, "skip_wide": E.W_SKIP_WIDE, "skip_narrow": E.W_SKIP_NARROW, "mid_only": E.W_MID}
# ordinal neighbours: dim -> {level index: [neighbour level indices]}
NEIGHBOURS = {
    "range_min": "linear", "buffer": "linear", "target": "linear", "window_min": "linear", "flat": "linear",
    "stop": {0: [1], 1: [0], 2: [3], 3: [2, 4], 4: [3]},  # range-based stops and fixed stops are separate
}


# --- grid -------------------------------------------------------------------------------------

class Grid:
    """Dense full-factorial grid. Configs with flat +60 and window 120 equal window 60 (the entry
    deadline is capped at the flat time), so they are not run: `twin` maps them to it."""

    def __init__(self, dims=DIMS):
        self.dims = dims
        self.shape = tuple(len(v) for v in dims.values())
        idx = np.indices(self.shape).reshape(len(self.shape), -1).T  # level index per dim
        self.idx = idx
        self.n = len(idx)
        lv = {k: np.asarray(v, dtype=object)[idx[:, a]] for a, (k, v) in enumerate(dims.items())}
        self.labels = pd.DataFrame(lv)
        flat = np.array([FLAT_MIN[x] for x in lv["flat"]])
        window = lv["window_min"].astype(np.int64)
        dup = (flat != E.SESSION) & (window > flat)
        twin = np.arange(self.n)
        if dup.any():
            w_axis = KEYS.index("window_min")
            fixed = idx[dup].copy()
            w_levels = list(dims["window_min"])
            fixed[:, w_axis] = [max(i for i, w in enumerate(w_levels) if w <= f) for f in flat[dup]]
            twin[dup] = np.ravel_multi_index(fixed.T, self.shape)
        self.twin = twin
        self.canonical = twin == np.arange(self.n)
        self.cfg = self._cfg_matrix()
        self.neighbours = neighbour_index(self)

    def _cfg_matrix(self):
        """Engine config rows (orb_engine C_* columns), mapped per level then indexed (fast)."""
        def col(dim, code):
            return np.array([code(v) for v in self.dims[dim]], dtype=np.int64)[self.idx[:, KEYS.index(dim)]]
        anchor, length = self.idx[:, KEYS.index("anchor")], self.idx[:, KEYS.index("range_min")]
        table_of = np.array([[E.TABLE_KEYS.index((a, L)) for L in self.dims["range_min"]] for a in self.dims["anchor"]])
        return np.column_stack([
            table_of[anchor, length],
            col("trigger", TRIGGER_CODE.get), col("buffer", int),
            col("stop", lambda v: STOP_CODE[v][0]), col("stop", lambda v: STOP_CODE[v][1]),
            col("target", TARGET_X10.get), col("window_min", int), col("flat", FLAT_MIN.get),
            col("direction", DIR_CODE.get), col("width", WIDTH_CODE.get), col("breakeven", lambda v: int(v == "on")),
        ])

    def spread(self, values: np.ndarray) -> np.ndarray:
        """Values computed for canonical configs -> every dense config (duplicates copy their twin)."""
        out = np.empty((self.n,) + values.shape[1:], dtype=values.dtype)
        out[self.canonical] = values
        out[~self.canonical] = out[self.twin[~self.canonical]]
        return out


def neighbour_index(grid: Grid) -> np.ndarray:
    """(n, k) neighbour config per ordinal move, mapped to its canonical twin; -1 = none.
    A neighbour that is the config itself (via a duplicate twin) or repeats another one is dropped."""
    moves = []
    for dim, rule in NEIGHBOURS.items():
        if dim not in grid.dims:
            continue
        ax = list(grid.dims).index(dim)
        n = grid.shape[ax]
        maps = ([{i: i - 1 for i in range(1, n)}, {i: i + 1 for i in range(n - 1)}] if rule == "linear"
                else [{i: v[0] for i, v in rule.items() if i < n and v[0] < n},
                      {i: v[1] for i, v in rule.items() if len(v) > 1 and i < n and v[1] < n}])
        for mp in maps:
            src = np.array([mp.get(i, -1) for i in range(n)])
            if (src < 0).all():
                continue
            new = src[grid.idx[:, ax]]
            lv = grid.idx.copy()
            lv[:, ax] = np.maximum(new, 0)
            moves.append(np.where(new >= 0, grid.twin[np.ravel_multi_index(lv.T, grid.shape)], -1))
    if not moves:
        return np.full((grid.n, 0), -1, dtype=np.int64)
    nb = np.stack(moves, axis=1)
    nb[nb == grid.twin[:, None]] = -1
    for k in range(1, nb.shape[1]):
        nb[(nb[:, [k]] == nb[:, :k]).any(axis=1) & (nb[:, k] >= 0), k] = -1
    return nb


def plateau(grid: Grid, score: np.ndarray, profitable: np.ndarray):
    """(median score over self + ordinal neighbours, share of neighbours that are profitable)."""
    nb = grid.neighbours
    has = nb >= 0
    vals = np.where(has, score[np.maximum(nb, 0)], np.nan)
    prof = np.where(has, profitable[np.maximum(nb, 0)].astype(np.float64), np.nan)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)  # configs without neighbours: NaN share
        med = np.nanmedian(np.column_stack([score, vals]), axis=1)
        share = np.nanmean(prof, axis=1) if nb.shape[1] else np.ones(grid.n)
    return med, share


def lower_bound(p: np.ndarray, n: int) -> np.ndarray:
    return p - 1.645 * np.sqrt(p * (1 - p) / n)


# --- running the grid ----------------------------------------------------------------------------

class Dev:
    """Development data, calendar and shared random numbers."""

    def __init__(self, m, cal):
        self.m, self.cal = m, cal
        self.mk = E.Market(m, cal.days, load_releases(), strict_expiry=True)
        self.n = cal.n_dev
        self.years = np.unique(cal.years[:self.n])
        self.year_of_day = np.searchsorted(self.years, cal.years[:self.n]).astype(np.int64)
        self.fold_ends = np.array([(cal.years[:self.n] < y).sum() for y in WF_YEARS], np.int64)
        rng = np.random.default_rng(SEED)
        self.u = rng.random((N_SIMS, P.MAX_DAYS // P.BLOCK + 1))
        self.u_wf = rng.random((N_SIMS_WF, P.MAX_DAYS // P.BLOCK + 1))
        self.hash_w = rng.random(self.n)

    def kernel(self, cfgs, slip, score, pessimistic=True):
        return E.grid_kernel(cfgs, self.n, self.year_of_day, len(self.years), self.fold_ends, self.hash_w,
                             *self.mk.day_args(), *self.mk.minute_args(), float(slip), pessimistic,
                             self.u, self.u_wf, P.BLOCK, score)

    def daily(self, cfgs, slip=BASE_SLIP, pessimistic=True):
        return E.daily_kernel(np.asarray(cfgs, np.int64), self.n, *self.mk.day_args(), *self.mk.minute_args(),
                              float(slip), pessimistic)


def run_grid(dev: Dev, cfgs: np.ndarray, slip: float, score: bool):
    parts = []
    t0 = time.time()
    for s in range(0, len(cfgs), CHUNK):
        parts.append(dev.kernel(cfgs[s:s + CHUNK], slip, score))
        done = min(s + CHUNK, len(cfgs))
        el = time.time() - t0
        print(f"  {done:>9,} / {len(cfgs):,}  ({el:.0f}s, ~{el / done * (len(cfgs) - done):.0f}s left)", flush=True)
    return [np.concatenate([p[k] for p in parts]) for k in range(5)]


def metrics_frame(grid: Grid, dev: Dev, base, slip2) -> tuple[pd.DataFrame, dict]:
    met, ypnl, ytr, ybest, wf = (grid.spread(x) for x in base)
    ypnl2 = grid.spread(slip2[1])
    trades2 = grid.spread(slip2[0])[:, 0]  # trade count can differ at 2 ticks (fills move the stop distance)
    df = grid.labels.copy()
    for k, name in enumerate(E.M_NAMES):
        df[name] = met[:, k]
    trades = df["trades"].to_numpy()
    total = df["total_usd"].to_numpy()
    n_years_span = dev.n / 252.0
    with np.errstate(divide="ignore", invalid="ignore"):
        df["expectancy_usd"] = np.where(trades > 0, total / trades, np.nan)
        df["expectancy_slip2"] = np.where(trades2 > 0, ypnl2.sum(axis=1) / trades2, np.nan)
        df["profit_factor"] = np.where(df["gross_loss"] > 0, df["gross_win"] / df["gross_loss"], np.inf)
        df["win_rate"] = np.where(trades > 0, df["wins"] / trades, np.nan)
        df["trades_per_year"] = trades / n_years_span
        df["positive_year_frac"] = (ypnl > 0).mean(axis=1)
        df["best_year_share"] = np.where(total > 0, ypnl.max(axis=1) / total, np.nan)
        df["best_day_share"] = np.where(total > 0, df["best_day_usd"] / total, np.nan)
    df["score"] = lower_bound(df["pass_prob"].to_numpy(), N_SIMS)
    df["canonical"] = grid.canonical
    return df, {"ypnl": ypnl, "ytr": ytr, "ybest": ybest, "wf": wf, "ypnl2": ypnl2}


def gate_mask(trades, trades_per_year, total, total2, pos_frac, best_year_share, best_day_share, p95dd,
              min_trades):
    g = GATES
    return ((trades >= min_trades) & (trades_per_year >= g["min_trades_per_year"])
            & (total > 0) & (total2 > 0)
            & (pos_frac >= g["min_positive_year_frac"])
            & (best_year_share <= g["max_best_year_share"])
            & (best_day_share <= g["max_best_day_share"])
            & (p95dd <= g["max_p95_drawdown"]))


def select(grid: Grid, gates: np.ndarray, score: np.ndarray, profitable: np.ndarray):
    """The selector (used for the real pick AND inside every walk-forward fold).
    Returns (order of eligible configs best first, plateau score, neighbour share, eligible mask)."""
    plat, share = plateau(grid, score, profitable)
    eligible = gates & (share >= GATES["min_neighbours_profitable"]) & grid.canonical
    pool = np.flatnonzero(eligible)
    order = pool[np.lexsort((-score[pool], -plat[pool]))]
    return order, plat, share, eligible


def rank(grid: Grid, df: pd.DataFrame) -> pd.DataFrame:
    gates = gate_mask(df["trades"].to_numpy(), df["trades_per_year"].to_numpy(), df["total_usd"].to_numpy(),
                      df["expectancy_slip2"].fillna(-1).to_numpy(), df["positive_year_frac"].to_numpy(),
                      df["best_year_share"].fillna(np.inf).to_numpy(), df["best_day_share"].fillna(np.inf).to_numpy(),
                      df["p95_drawdown"].to_numpy(), GATES["min_trades"])
    order, plat, share, eligible = select(grid, gates, df["score"].to_numpy(), df["total_usd"].to_numpy() > 0)
    df = df.copy()
    df["passes_gates"] = gates
    df["plateau_score"] = plat
    df["neighbours_profitable"] = share
    df["eligible"] = eligible
    # eligible configs first; the rest (ranked the same way) only for learning / diagnostics
    rest = np.flatnonzero(grid.canonical & (df["trades"].to_numpy() > 0) & ~eligible)
    rest = rest[np.lexsort((-df["score"].to_numpy()[rest], -plat[rest]))]
    order = np.concatenate([order, rest])
    df["rank"] = np.nan
    df.loc[order, "rank"] = np.arange(1, len(order) + 1)
    return df


def walk_forward(grid: Grid, dev: Dev, df: pd.DataFrame, arr: dict) -> pd.DataFrame:
    """Each fold year: run the whole selector on earlier years only, record the champion's P&L
    in that (unseen) year."""
    ypnl, ytr, ybest, wf, ypnl2 = arr["ypnl"], arr["ytr"], arr["ybest"], arr["wf"], arr["ypnl2"]
    rows = []
    for f, year in enumerate(WF_YEARS):
        k = int(np.searchsorted(dev.years, year))  # years [0, k) are "the past"
        n_days = dev.fold_ends[f]
        total = ypnl[:, :k].sum(axis=1)
        trades = ytr[:, :k].sum(axis=1)
        with np.errstate(divide="ignore", invalid="ignore"):
            pos = total > 0
            gates = gate_mask(trades, trades / (n_days / 252.0), total, ypnl2[:, :k].sum(axis=1),
                              (ypnl[:, :k] > 0).mean(axis=1),
                              np.where(pos, ypnl[:, :k].max(axis=1) / total, np.inf),
                              np.where(pos, ybest[:, :k].max(axis=1) / total, np.inf),
                              wf[:, f, 1], WF_MIN_TRADES)
        score = lower_bound(wf[:, f, 0], N_SIMS_WF)
        order, *_ = select(grid, gates, score, total > 0)
        if len(order) == 0:
            rows.append({"year": year, "champion": "none qualified", "qualified": 0, "pnl_usd_in_year": 0.0})
            continue
        best = order[0]
        rows.append({"year": year, "champion": label(df.loc[best]), "qualified": len(order),
                     "pnl_usd_in_year": float(ypnl[best, k])})
    return pd.DataFrame(rows)


# --- overfitting diagnostics ------------------------------------------------------------------------

def deflated_sharpe(daily: np.ndarray, sharpe_var: float, n_trials: float) -> float:
    """Bailey & Lopez de Prado deflated Sharpe ratio for `n_trials` independent tries."""
    sd = daily.std()
    if sd == 0 or n_trials < 2:
        return float("nan")
    sr = daily.mean() / sd
    nd = NormalDist()
    gamma = 0.5772156649
    sr0 = math.sqrt(sharpe_var) * ((1 - gamma) * nd.inv_cdf(1 - 1 / n_trials)
                                   + gamma * nd.inv_cdf(1 - 1 / (n_trials * math.e)))
    x = daily - daily.mean()
    skew = (x ** 3).mean() / sd ** 3
    kurt = (x ** 4).mean() / sd ** 4
    denom = math.sqrt(max(1e-12, 1 - skew * sr + (kurt - 1) / 4 * sr ** 2))
    return nd.cdf((sr - sr0) * math.sqrt(len(daily) - 1) / denom)


def effective_trials(dev: Dev, grid: Grid, df: pd.DataFrame, rng) -> tuple[int, float]:
    """(unique trade streams, effective number of independent streams). The effective count is the
    participation ratio of the correlation eigenvalues of a random sample of unique streams. It is
    a LOWER bound (the sample cannot show more dimensions than it has), so the deflated Sharpe at
    this count is the OPTIMISTIC one; the count of unique streams gives the conservative one."""
    live = df[df["canonical"] & (df["trades"] > 0)]
    uniq = live.drop_duplicates(["stream_hash", "trades", "total_usd"])
    n_unique = len(uniq)
    pick = uniq.index.to_numpy()
    if len(pick) > N_EFF_SAMPLE:
        pick = rng.choice(pick, N_EFF_SAMPLE, replace=False)
    x, _ = dev.daily(grid.cfg[pick])
    x = x[x.std(axis=1) > 0]
    if len(x) < 2:
        return n_unique, float(n_unique)
    lam = np.clip(np.linalg.eigvalsh(np.corrcoef(x)), 0, None)
    pr = lam.sum() ** 2 / (lam ** 2).sum()  # effective dimensions of the sample
    return n_unique, float(min(n_unique, pr))


def pbo_cscv(daily: np.ndarray, n_blocks=16) -> float:
    """Probability of backtest overfitting (Bailey et al., CSCV): share of in-sample / out-of-sample
    splits where the in-sample best config ranks in the bottom half out of sample."""
    n_cfg, n_days = daily.shape
    edges = np.linspace(0, n_days, n_blocks + 1).astype(int)
    s1 = np.stack([daily[:, a:b].sum(axis=1) for a, b in zip(edges[:-1], edges[1:])], axis=1)
    s2 = np.stack([(daily[:, a:b] ** 2).sum(axis=1) for a, b in zip(edges[:-1], edges[1:])], axis=1)
    cnt = np.diff(edges)
    s1_all, s2_all, n_all = s1.sum(axis=1), s2.sum(axis=1), cnt.sum()

    def sharpe(t1, t2, n):
        mu = t1 / n
        var = t2 / n - mu ** 2
        return mu / np.sqrt(np.where(var > 0, var, np.inf))

    combos = list(itertools.combinations(range(n_blocks), n_blocks // 2))
    below = 0
    for c in combos:
        c = list(c)
        i1, i2, ni = s1[:, c].sum(axis=1), s2[:, c].sum(axis=1), cnt[c].sum()
        best = np.argmax(sharpe(i1, i2, ni))
        oos = sharpe(s1_all - i1, s2_all - i2, n_all - ni)
        ties = (oos == oos[best]).sum() - 1  # other configs with the same OOS Sharpe count half
        rel = ((oos < oos[best]).sum() + 0.5 * ties) / (n_cfg - 1)  # 0 = worst, 1 = best out of sample
        below += rel < 0.5
    return below / len(combos)


# --- finalists ------------------------------------------------------------------------------------

def combine_scores(pnl, low, n_sims, block, seed=SEED):
    u = np.random.default_rng(seed).random((n_sims, P.MAX_DAYS // block + 1))
    return E._bootstrap(pnl, low, len(pnl), u, block)


def to_minute_rows(mk: E.Market, t):
    """Engine trades (front rows) -> the (in, out, dir, px_in, px_out, mae, why) tuple search.py's
    stats helpers expect (rows of Minutes)."""
    return (mk.f.src[t[1]], mk.f.src[t[2]], t[3], t[4], t[5], t[6], t[7])


def period_stats(mk, m, cal, cfg, period, **kw):
    n_days = cal.n_dev if period == "dev" else len(cal.days)
    return S.period_stats(to_minute_rows(mk, mk.trades(cfg, n_days=n_days, **kw)), m, cal, period)


def write_trades(t, mk, m, cal, path):
    """One row per trade, enough to recompute every number independently."""
    pd.DataFrame({
        "trading_day": pd.to_datetime(cal.days[t[0]], unit="D").date,
        "entry_time_utc": pd.to_datetime(mk.f.tmin[t[1]] * E.NS_PER_MIN, utc=True),
        "exit_time_utc": pd.to_datetime(mk.f.tmin[t[2]] * E.NS_PER_MIN, utc=True),
        "contract": [m.contracts[c] for c in mk.f.contract[t[1]]],
        "direction": np.where(t[3] > 0, "long", "short"),
        "entry_ticks": t[4], "exit_ticks": t[5], "mae_ticks": t[6],
        "exit_reason": [E.EXIT_NAMES[int(w)] for w in t[7]],
        "pnl_usd": P.trade_pnl_usd(t[3], t[4], t[5]).round(2),
        "period": np.where(t[0] < cal.n_dev, "dev", "holdout"),
    }).to_csv(path, index=False)


def label(row) -> str:
    return (f"{row['anchor']} / {row['range_min']}m range / {row['trigger']} / buf {row['buffer']} / "
            f"stop {row['stop']} / tgt {row['target']} / window {row['window_min']}m / flat {row['flat']} / "
            f"{row['direction']} / width {row['width']} / BE {row['breakeven']}")


def source_hash() -> str:
    """Code AND the reference data the results depend on (EIA calendar, contract expiries)."""
    h = hashlib.sha256()
    for f in SOURCE_FILES:
        h.update(f.encode() + b"\0" + (Path(__file__).parent / f).resolve().read_bytes())
    for f in [EIA_FILE, DEFINITIONS_FILE]:
        h.update(f.name.encode() + b"\0" + f.read_bytes())
    return h.hexdigest()


# --- main -------------------------------------------------------------------------------------------

def main() -> int:
    global OUT_DIR
    quick = "--quick" in sys.argv
    dims = DIMS
    if quick:
        OUT_DIR = OUT_DIR.parent / "orb_quick"
        dims = {**DIMS, "anchor": ["et0900"], "range_min": [5, 15, 30], "trigger": ["stop", "close5"],
                "width": ["none", "mid_only"]}
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    if (OUT_DIR / "holdout_opened.json").exists():
        print("The holdout was already opened for these picks. Re-running the search now would let")
        print("holdout knowledge leak into new picks. Start a new research folder instead.")
        return 2

    print("Loading development data (2010-06 -> 2021-12 only)...", flush=True)
    m = B.load_minutes(end=DEV_END)
    cal = S.Calendar(m)
    if cal.n_dev != len(cal.days):
        raise RuntimeError("holdout data must not be loaded here")
    dev = Dev(m, cal)
    grid = Grid(dims)
    cfgs = grid.cfg[grid.canonical]
    print(f"  {len(m):,} minutes, {cal.n_dev:,} trading days. Grid: {grid.n:,} dense, {len(cfgs):,} unique", flush=True)

    print(f"Grid at {BASE_SLIP:.0f} tick slippage + Combine scoring...", flush=True)
    base = run_grid(dev, cfgs, BASE_SLIP, True)
    print(f"Grid at {GATE_SLIP:.0f} ticks slippage (stress gate)...", flush=True)
    slip2 = run_grid(dev, cfgs, GATE_SLIP, False)
    df, arr = metrics_frame(grid, dev, base, slip2)
    df = rank(grid, df)
    df[df["canonical"]].sort_values("rank").to_csv(OUT_DIR / "results.csv.gz", index=False)

    print("Walk-forward test of the selection method...", flush=True)
    wf = walk_forward(grid, dev, df, arr)
    wf.to_csv(OUT_DIR / "walk_forward.csv", index=False)

    rng = np.random.default_rng(SEED)
    print("Overfitting diagnostics...", flush=True)
    n_unique, n_eff = effective_trials(dev, grid, df, rng)
    live = df[df["canonical"] & (df["trades"] > 0)].drop_duplicates(["stream_hash", "trades", "total_usd"])
    # PBO universe: a seeded random sample of unique streams, NOT the top of the ranking (which has
    # already seen every CSCV block)
    sample = np.sort(rng.choice(live.index.to_numpy(), min(N_PBO, len(live)), replace=False))
    sample_pnl, _ = dev.daily(grid.cfg[sample])
    pbo = pbo_cscv(sample_pnl)
    sharpe_var = float(np.var(live["sharpe_daily"]))
    ranked = df.dropna(subset=["rank"]).sort_values("rank")
    if ranked.empty:
        raise RuntimeError("no configuration made a single trade: check the data and the day tables")
    champ = ranked.index[0]
    champ_daily = dev.daily(grid.cfg[[champ]])[0][0]
    dsr_unique = deflated_sharpe(champ_daily, sharpe_var, n_unique)
    dsr_eff = deflated_sharpe(champ_daily, sharpe_var, n_eff)

    print("Finalist details...", flush=True)
    finalists = ranked.head(N_FINALISTS)
    detail = []
    fin_pnl, fin_low = dev.daily(grid.cfg[finalists.index])
    for n, (i, row) in enumerate(finalists.iterrows()):
        c = grid.cfg[i]
        st = period_stats(dev.mk, m, cal, c, "dev")
        st["blocks"] = {b: combine_scores(fin_pnl[n], fin_low[n], N_SIMS_FINAL, b) for b in FINAL_BLOCKS}
        if n == 0:
            st["stress"] = {s: period_stats(dev.mk, m, cal, c, "dev", slip=s) for s in STRESS_SLIPS}
            st["optimistic"] = period_stats(dev.mk, m, cal, c, "dev", pessimistic=False)
            t = dev.mk.trades(c, n_days=cal.n_dev)
            write_trades(t, dev.mk, m, cal, OUT_DIR / "champion_trades_dev.csv")
            st["exit_mix"] = pd.Series([E.EXIT_NAMES[int(w)] for w in t[7]]).value_counts(normalize=True).round(3).to_dict()
        detail.append((i, st))

    champ_ok = bool(df.loc[champ, "eligible"])
    frozen = {
        "created_utc": pd.Timestamp.now(tz="UTC").isoformat(),
        "source_sha256": source_hash(),
        "quick": quick,
        "any_config_eligible": bool(df["eligible"].any()),
        "champion_eligible": champ_ok,
        "walk_forward_total_usd": float(wf["pnl_usd_in_year"].sum()),
        "deflated_sharpe_unique": dsr_unique,
        "deflated_sharpe_effective": dsr_eff,
        "pbo": pbo,
        "champion": {k: (v.item() if hasattr(v, "item") else v) for k, v in df.loc[champ, KEYS].items()},
        "champion_cfg": grid.cfg[champ].tolist(),
        "finalists_diagnostic_only": [label(df.loc[i]) for i, _ in detail[1:]],
    }
    (OUT_DIR / "frozen_picks.json").write_text(json.dumps(frozen, indent=2))
    write_report(df, wf, detail, frozen, n_unique, n_eff, cal, grid)
    print(f"\nDevelopment report: {OUT_DIR / 'report.md'}")
    print("Champion frozen. Next (runs ONCE): python -m propfirm_backtest.orb_holdout")
    return 0


def write_report(df, wf, detail, frozen, n_unique, n_eff, cal, grid):
    fmt = S.fmt
    can = df[df["canonical"]]
    L = ["# ORB: development results (2010-06 -> 2021-12)", "",
         f"Generated {pd.Timestamp.now(tz='UTC'):%Y-%m-%d %H:%M} UTC. {len(can):,} unique configurations "
         f"({grid.n:,} in the dense grid), {cal.n_dev:,} trading days.",
         "Costs: $4.02 round turn + 1 tick slippage per side; same-minute ambiguity resolved against us; "
         "targets need a 1-tick trade-through. EIA releases blocked +/-15 min.",
         "Pass % in the tables below = 2,000 fresh Combine simulations per config (the grid score used a "
         "shared set of random days), so it differs slightly from the grid ranking score.",
         "The holdout (2022 -> today) is NOT in this report.", ""]
    wf_total = frozen["walk_forward_total_usd"]
    L += ["## Summary", "",
          f"- Configurations passing every gate: {int(can['passes_gates'].sum()):,}; also on a plateau "
          f"(>= 60% profitable neighbours): **{int(can['eligible'].sum()):,} / {len(can):,}**",
          f"- Profitable after costs: {int((can['total_usd'] > 0).sum()):,} "
          f"(still profitable with +1 tick slippage: {int((can['expectancy_slip2'] > 0).sum()):,})",
          f"- Unique trade streams: {n_unique:,}; effective independent trials (lower-bound estimate): {n_eff:,.0f}",
          f"- Walk-forward of the whole selector (2014-2021): **{fmt(wf_total, money=True)}**",
          f"- Deflated Sharpe of the champion: {fmt(frozen['deflated_sharpe_unique'], pct=True)} at {n_unique:,} unique trials (conservative), "
          f"{fmt(frozen['deflated_sharpe_effective'], pct=True)} at {n_eff:,.0f} effective trials (optimistic). "
          f"The verdict needs the optimistic one >= 95%.",
          f"- Probability of backtest overfitting (CSCV, {N_PBO:,} random unique streams): {fmt(frozen['pbo'], pct=True)} "
          f"(the verdict needs < 50%). PBO only says whether rankings persist; it does not show an edge "
          f"(costs alone make bad configs persistently bad).", ""]
    if not frozen["any_config_eligible"]:
        L += ["**No configuration passed all gates.** The rankings below are for learning only; "
              "ORB should not be traded as specified.", ""]

    L += ["## Champion (frozen for the holdout) + finalists (diagnostics only, never promoted)", "",
          "| # | Settings | Trades | Expectancy | PF | Pass % | Fail % | p95 DD | +1 tick exp. | Pass % blocks 5/10/20 (20k sims) |",
          "|---|---|---|---|---|---|---|---|---|---|"]
    for n, (i, st) in enumerate(detail, 1):
        r = df.loc[i]
        bl = " / ".join(fmt(st["blocks"][b][0], pct=True) for b in FINAL_BLOCKS)
        L.append(f"| {n} | {label(r)} | {st['trades']} | {fmt(st['expectancy_usd'], money=True)} | "
                 f"{fmt(st['profit_factor'])} | {fmt(st['pass_prob'], pct=True)} | {fmt(st['fail_prob'], pct=True)} | "
                 f"{fmt(st['p95_drawdown'], money=True)} | {fmt(float(r['expectancy_slip2']), money=True)} | {bl} |")

    i, st = detail[0]
    L += ["", f"## Champion: {label(df.loc[i])}", ""] + S.benchmark_table(st)
    L += ["", "### Slippage stress and fill-ambiguity bound", "", "| Case | Expectancy | Profit factor | Pass % |",
          "|---|---|---|---|",
          f"| 1 tick/side (base, pessimistic) | {fmt(st['expectancy_usd'], money=True)} | {fmt(st['profit_factor'])} | {fmt(st['pass_prob'], pct=True)} |"]
    for s, sst in st["stress"].items():
        L.append(f"| {int(s)} ticks/side | {fmt(sst['expectancy_usd'], money=True)} | {fmt(sst['profit_factor'])} | {fmt(sst['pass_prob'], pct=True)} |")
    o = st["optimistic"]
    L.append(f"| Optimistic same-minute fills | {fmt(o['expectancy_usd'], money=True)} | {fmt(o['profit_factor'])} | {fmt(o['pass_prob'], pct=True)} |")
    L += ["", "Exit mix: " + ", ".join(f"{k} {100 * v:.1f}%" for k, v in st["exit_mix"].items())]
    L += ["", "### P&L by year", "", "| Year | P&L |", "|---|---|"] + [f"| {y} | {fmt(v, money=True)} |" for y, v in st["by_year"].items()]

    L += ["", "## Walk-forward test of the selector", "",
          "Each year the full selector (gates + plateau) picks a champion from earlier years only; we record what it made in that unseen year.", "",
          "| Year | Configs qualified | Champion chosen from earlier years | P&L that year |", "|---|---|---|---|"]
    L += [f"| {r['year']} | {r['qualified']:,} | {r['champion']} | {fmt(r['pnl_usd_in_year'], money=True)} |" for _, r in wf.iterrows()]
    L.append(f"| **Total** | | | **{fmt(wf_total, money=True)}** |")

    cols = KEYS + ["trades", "expectancy_usd", "expectancy_slip2", "profit_factor", "pass_prob", "plateau_score", "eligible"]
    for by in ["anchor", "range_min", "trigger"]:
        best = can.sort_values("rank").groupby(by, sort=False).head(1).sort_values(by)
        L += ["", f"## Best configuration per {by}", "", "```", best[cols].round(3).to_string(index=False), "```"]
    for by in KEYS:
        g = can.groupby(by).agg(median_expectancy=("expectancy_usd", "median"),
                                share_profitable=("total_usd", lambda s: (s > 0).mean()),
                                best_expectancy=("expectancy_usd", "max"), best_pass_prob=("pass_prob", "max"),
                                eligible=("eligible", "sum"))
        L += ["", f"## Effect of {by} (all configs)", "", "```", g.round(3).to_string(), "```"]
    L += ["", "Files: `results.csv.gz` (every config), `walk_forward.csv`, `frozen_picks.json`, "
          "`champion_trades_dev.csv` (every champion trade, for independent recomputation)."]
    (OUT_DIR / "report.md").write_text("\n".join(L))


if __name__ == "__main__":
    sys.exit(main())
