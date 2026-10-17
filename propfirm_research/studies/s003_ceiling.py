"""S003 predictability ceiling on discovery data (research/studies/S003-ceiling/report.md). Kill test.

Unit: (trading day, decision time T). Features use only bars that started before T; the target is the
executable return from the open of the T bar to the open of the exit bar (grid.windows: roll-safe, never
across a contract change; a day-session exit after 16:05 is cut to the flat time).

Models (hyperparameter grids fixed here before any run): ridge, elastic net, shallow gradient-boosted
trees; the benchmark is "no trade" (P&L 0). Nested expanding walk-forward by calendar year: outer test
years 2012..2016, hyperparameters chosen on the last training year (inner walk-forward), training rows
within 1 trading day of the test year dropped (purge + embargo: every horizon ends the same trading day).
Trading rules on each out-of-sample prediction: "all" = sign(pred) every valid day; "conf_base" / "conf_stress"
= only when |pred| > the base (2.402) / stress (4.402) round-trip cost. One trade per day per cell.

Inference (R010): the kill test is the simultaneous one-sided 95% upper bound of every strategy's gross
edge per trade (stationary bootstrap of days, max-t), compared with the stress cost (4.402 ticks).
Also Romano-Wolf step-down max-t on per-day net P&L (no trade = 0) at base and stress costs and Hansen
SPA. The benchmark "no trade" is analytical (P&L 0, zero variance) and sits outside the bootstrap family.
Controls: fold-safe label nulls (labels shifted / block-shuffled inside each calendar year) and random
features (false-positive rate of the whole pipeline), a leaked feature (must be found), planted edges of
1 / 2 / 4 / 8 net ticks with the same planted signal at every size (power, with a confidence interval),
and a negative-control decision time (00:30, own family).

Usage: python -m propfirm_research.studies.s003_ceiling [--quick] [--jobs N]
"""

import argparse
import json
import time
import warnings
from datetime import datetime, timezone

import numpy as np
import pandas as pd
from joblib import Parallel, delayed
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.exceptions import ConvergenceWarning
from sklearn.impute import SimpleImputer
from sklearn.linear_model import ElasticNet, Ridge
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from .. import costs, data, grid, ledger, paths
from ..stats import romano_wolf, simultaneous_upper, spa_test, wilson_upper
from .s002_atlas import eia_calendar_split, fingerprint, minute_returns
from .s001_feasibility import code_hash

ITEM = "S003"
REPORT_DIR = paths.RESEARCH_DIR / "studies" / "S003-ceiling"
F_ = grid.FLAT
FLAT_CLOCK = 16 * 60 + 5
DECISION_TIMES = [20 * 60, 3 * 60, 8 * 60, 9 * 60, 10 * 60 + 35, 12 * 60, 14 * 60, 14 * 60 + 35]
NEGATIVE_CONTROL_TIMES = [30]  # 00:30 ET: quiet hour, own family
HORIZONS = [5, 15, 30, 60, 120, "flat"]
TEST_YEARS = [2012, 2013, 2014, 2015, 2016]
BASE_TICKS = costs.round_trip_ticks(costs.BASE_SLIP)
STRESS_TICKS = costs.round_trip_ticks(costs.STRESS_SLIP)
EIA_MOD = 10 * 60 + 30
STALE_MIN = 15  # the last bar before T must be at most this old, or the day is skipped
SLOPE_STALE_MIN = 10
NORM_DAYS = 20
MODELS = {  # name -> list of parameter dicts (declared before any run)
    "ridge": [{"alpha": a} for a in (1.0, 10.0, 100.0, 1000.0)],
    "enet": [{"alpha": a, "l1_ratio": r} for a in (0.01, 0.1, 1.0) for r in (0.2, 0.8)],
    "gbt": [{"max_depth": d, "max_iter": n, "learning_rate": 0.05, "min_samples_leaf": 100}
            for d in (2, 3) for n in (100, 300)],
}
RULES = ("all", "conf_base", "conf_stress")
N_BOOT = 2000
MEAN_BLOCK = 5.0
N_SHIFTS = 5
N_SHUFFLES = 5
SHUFFLE_BLOCK = 20
N_RANDOM = 3
PLANT_EDGES = [1, 2, 4, 8]
PLANT_REPS = 20
PLANT_CELLS = [(14 * 60 + 35, "flat"), (9 * 60, 60), (3 * 60, 120), (10 * 60 + 35, 30), (14 * 60, 30)]


def hm(mod) -> str:
    return f"{mod // 60:02d}:{mod % 60:02d}"


def cell_name(t: int, h) -> str:
    return f"{hm(t)}+{h}"


def make_model(name: str, params: dict):
    if name == "gbt":
        return HistGradientBoostingRegressor(random_state=0, **params)
    est = Ridge(**params) if name == "ridge" else ElasticNet(max_iter=5000, **params)
    return make_pipeline(SimpleImputer(strategy="median"), StandardScaler(), est)


# ---------------------------------------------------------------- features ---------------------------

class Features:
    """Causal features at decision times, from the front (df) and second (df2) month minute frames."""

    def __init__(self, df: pd.DataFrame, df2: pd.DataFrame, eia_days: np.ndarray):
        self.df, self.df2 = df, df2
        self.days = np.unique(df["trading_day"].to_numpy())
        self.eia_days = eia_days
        self.tm = df["tmin"].to_numpy()
        self.close = df["close"].to_numpy()
        self.con = df["contract"].to_numpy()
        self.tday = df["trading_day"].to_numpy()
        vol = df["volume"].to_numpy()
        r1 = minute_returns(df)
        self.cs_r2 = np.r_[0.0, np.cumsum(np.nan_to_num(r1) ** 2)]
        self.cs_vol = np.r_[0.0, np.cumsum(vol)]
        self.cs_pv = np.r_[0.0, np.cumsum(vol * self.close)]
        g = pd.DataFrame({"d": self.tday, "h": df["high"].to_numpy(), "l": df["low"].to_numpy()})
        self.cummax = g.groupby("d")["h"].cummax().to_numpy()
        self.cummin = g.groupby("d")["l"].cummin().to_numpy()
        first = pd.Series(np.arange(len(df))).groupby(self.tday).min()
        self.day_first = first.reindex(self.days).to_numpy()
        last = pd.Series(np.arange(len(df))).groupby(self.tday).max()
        self.day_last = last.reindex(self.days).to_numpy()
        daily = g.groupby("d").agg(h=("h", "max"), l=("l", "min")).reindex(self.days)
        self.prev_hi, self.prev_lo = daily["h"].shift(1).to_numpy(), daily["l"].shift(1).to_numpy()
        w = grid.windows(df, [(18 * 60, F_)], days=self.days)
        self.day_ret = pd.Series(np.where(w["valid"], w["ret_ticks"], np.nan), index=self.days)
        keys = list(pd.unique(self.con))
        self.expiry = dict(zip(keys, grid.E.contract_expiry(keys)))

    def _before(self, t: np.ndarray) -> np.ndarray:
        """Index of the last front bar strictly before UTC minute t (-1 if none)."""
        return np.searchsorted(self.tm, t) - 1

    def _price(self, t, day_ok=True, ref=None) -> np.ndarray:
        """Close of the last bar before t on the same trading day (and same contract as `ref` index)."""
        i = self._before(t)
        ic = np.maximum(i, 0)
        ok = i >= 0
        if day_ok:
            ok &= self.tday[ic] == self.days
        if ref is not None:
            ok &= self.con[ic] == self.con[np.maximum(ref, 0)]
        return np.where(ok, self.close[ic], np.nan)

    def _window_sum(self, cs, t0, t1) -> np.ndarray:
        a, b = np.searchsorted(self.tm, t0), np.searchsorted(self.tm, t1)
        return cs[b] - cs[a]

    def slope(self, t: np.ndarray) -> np.ndarray:
        tm2 = self.df2["tmin"].to_numpy()
        common = np.intersect1d(self.tm, tm2)
        if len(common) == 0:
            return np.full(len(t), np.nan)
        j = np.searchsorted(common, t) - 1
        tc = np.where(j >= 0, common[np.maximum(j, 0)], -10**9)
        i1 = np.minimum(np.searchsorted(self.tm, tc), len(self.tm) - 1)
        i2 = np.minimum(np.searchsorted(tm2, tc), len(tm2) - 1)
        k1, k2 = self.con[i1], self.df2["contract"].to_numpy()[i2]
        ok = (t - tc <= SLOPE_STALE_MIN) & (k1 != k2)
        return np.where(ok, self.df2["close"].to_numpy()[i2] - self.close[i1], np.nan)

    def at(self, T: int) -> pd.DataFrame:
        days = self.days
        t = grid.clock_tmin(days, T)
        i0 = self._before(t)
        i0c = np.maximum(i0, 0)
        fresh = (i0 >= 0) & (self.tday[i0c] == days) & (t - self.tm[i0c] <= STALE_MIN)
        p0 = np.where(fresh, self.close[i0c], np.nan)
        f = {}
        for k in (5, 15, 30, 60, 120):
            f[f"ret_{k}"] = p0 - self._price(t - k, ref=i0)
        first = self.day_first
        same_first = self.con[first] == self.con[i0c]
        f["ret_since_open"] = np.where(same_first, p0 - self.df["open"].to_numpy()[first], np.nan)
        f["ret_since_0900"] = (p0 - self._price(grid.clock_tmin(days, 9 * 60), ref=i0)) if 9 * 60 < T < 18 * 60 \
            else np.full(len(days), np.nan)  # last close before 09:00 = the 09:00 boundary price
        prev_settle_t = np.r_[np.nan, grid.clock_tmin(days, 14 * 60 + 30)[:-1].astype(float)]
        ps = np.full(len(days), np.nan)
        okp = ~np.isnan(prev_settle_t)
        j = self._before(prev_settle_t[okp].astype(np.int64))
        ps[okp] = np.where((j >= 0) & (self.con[np.maximum(j, 0)] == self.con[i0c[okp]]),
                           self.close[np.maximum(j, 0)], np.nan)
        f["ret_since_prev_settle"] = p0 - ps
        prev = self.day_ret.shift(1)
        f["ret_prev_day"] = prev.to_numpy()
        f["ret_5d"] = prev.rolling(5, min_periods=4).sum().to_numpy()  # previous 5 full sessions (roll-safe)
        f["ret_20d"] = prev.rolling(20, min_periods=15).sum().to_numpy()
        rv = np.sqrt(self._window_sum(self.cs_r2, t - 60, t))
        rv = np.where(fresh, rv, np.nan)
        rv_norm = pd.Series(rv).shift(1).rolling(NORM_DAYS, min_periods=10).mean().to_numpy()
        f["rv60_rel"] = rv / rv_norm
        hi, lo = self.cummax[i0c], self.cummin[i0c]
        f["range_pos_today"] = np.where(fresh & (hi > lo), (p0 - lo) / np.where(hi > lo, hi - lo, 1), np.nan)
        prev_con = np.r_[None, self.con[self.day_last[:-1]]]
        f["range_pos_prev"] = np.where((self.prev_hi > self.prev_lo) & (prev_con == self.con[i0c]),
                                       (p0 - self.prev_lo) / (self.prev_hi - self.prev_lo), np.nan)
        prev_last = np.r_[-1, self.day_last[:-1]]
        gap_ok = (prev_last >= 0) & (self.con[np.maximum(prev_last, 0)] == self.con[first])
        f["gap"] = np.where(gap_ok, self.df["open"].to_numpy()[first] - self.close[np.maximum(prev_last, 0)], np.nan)
        v30 = np.where(fresh, self._window_sum(self.cs_vol, t - 30, t), np.nan)
        f["relvol30"] = v30 / pd.Series(v30).shift(1).rolling(NORM_DAYS, min_periods=10).mean().to_numpy()
        v1 = np.where(fresh, self._window_sum(self.cs_vol, t - 1, t), np.nan)  # the minute just before T
        f["relvol_1m"] = v1 / pd.Series(v1).shift(1).rolling(NORM_DAYS, min_periods=10).mean().to_numpy()
        tstart = self.tm[first]
        vsum = self._window_sum(self.cs_vol, tstart, t)
        pvsum = self._window_sum(self.cs_pv, tstart, t)
        f["vwap_dist"] = np.where(fresh & (vsum > 0), p0 - pvsum / np.where(vsum > 0, vsum, 1), np.nan)
        sl = self.slope(t)
        f["slope"] = sl
        con5 = pd.Series(self.con[i0c]).shift(5).to_numpy()
        f["slope_chg5"] = np.where(con5 == self.con[i0c], sl - pd.Series(sl).shift(5).to_numpy(), np.nan)
        dates = pd.to_datetime(days, unit="D")
        f["weekday"] = dates.dayofweek.to_numpy().astype(float)
        eia = np.isin(days, self.eia_days)
        f["eia_day"] = eia.astype(float)
        f["min_from_eia"] = np.where(eia, float(T - EIA_MOD) if T < 18 * 60 else np.nan, 0.0)
        exp = np.array([self.expiry.get(k, -1) for k in self.con[i0c]], dtype=float)
        f["days_to_expiry"] = np.where(fresh & (exp > 0), (exp - t) / 1440, np.nan)
        out = pd.DataFrame(f, index=days)
        out["_valid"] = fresh
        return out


def targets(df: pd.DataFrame, days: np.ndarray, T: int) -> pd.DataFrame:
    """Per horizon: executable return (ticks) from the T bar open; day-session exits past 16:05 cut to flat."""
    out = {}
    day_session = 0 <= T < 18 * 60
    for h in HORIZONS:
        if h == "flat":
            end = F_
        else:
            end = (T + h) % 1440
            if day_session and T + h > FLAT_CLOCK:
                end = F_
        w = grid.windows(df, [(T, end)], days=days)
        out[h] = np.where(w["valid"], w["ret_ticks"], np.nan)
    return pd.DataFrame(out, index=days)


# ---------------------------------------------------------------- walk-forward -----------------------

def fit_predict(model: str, X: pd.DataFrame, y: np.ndarray, years: np.ndarray) -> np.ndarray:
    """Out-of-sample predictions for the test years (NaN elsewhere): nested expanding walk-forward."""
    pred = np.full(len(y), np.nan)
    ok = ~np.isnan(y)
    Xv = X.to_numpy(float)
    day_idx = np.arange(len(y))
    for Y in TEST_YEARS:
        test = ok & (years == Y)
        if not test.any():
            continue
        start = day_idx[years == Y].min()
        train = ok & (day_idx < start - 1)  # purge + 1-day embargo
        inner_val = train & (years == Y - 1)
        inner_val_start = day_idx[years == Y - 1].min() if (years == Y - 1).any() else start
        inner_train = train & (day_idx < inner_val_start - 1)
        if train.sum() < 100:
            continue
        best, best_score = MODELS[model][0], -np.inf
        if inner_train.sum() >= 100 and inner_val.sum() >= 50:
            for params in MODELS[model]:
                m = make_model(model, params).fit(Xv[inner_train], y[inner_train])
                p = m.predict(Xv[inner_val])
                score = float(np.mean(np.sign(p) * y[inner_val]))  # sign-rule gross edge
                if score > best_score:
                    best, best_score = params, score
        m = make_model(model, best).fit(Xv[train], y[train])
        pred[test] = m.predict(Xv[test])
    return pred


def cell_job(X: pd.DataFrame, y: np.ndarray, years: np.ndarray) -> dict:
    X = X.loc[:, X.nunique(dropna=True) > 1]  # e.g. "since 09:00" at 09:00 is empty by construction
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", ConvergenceWarning)
        return {m: fit_predict(m, X, y, years) for m in MODELS}


def strategies(pred: np.ndarray, y: np.ndarray) -> dict:
    """Per rule: (gross per-day P&L in ticks with 0 for no trade, trade flag)."""
    out = {}
    have = ~np.isnan(pred) & ~np.isnan(y)
    threshold = {"all": 0.0, "conf_base": BASE_TICKS, "conf_stress": STRESS_TICKS}
    for rule in RULES:
        trade = have & (np.abs(np.nan_to_num(pred)) > threshold[rule]) & (np.nan_to_num(pred) != 0)
        gross = np.where(trade, np.sign(np.nan_to_num(pred)) * np.nan_to_num(y), 0.0)
        out[rule] = (gross, trade)
    return out


def run_pipeline(feats: dict, targs: dict, cells: list, years: np.ndarray, jobs: int,
                 transform=None) -> dict:
    """{cell: {model: oos prediction}}. transform(cell, X, y) -> (X, y) for controls."""
    work = []
    for T, h in cells:
        X = feats[T].drop(columns="_valid")
        y = np.where(feats[T]["_valid"], targs[T][h].to_numpy(), np.nan)
        if transform is not None:
            X, y = transform((T, h), X, y)
        work.append(((T, h), X, y))
    res = Parallel(n_jobs=jobs)(delayed(cell_job)(X, y, years) for _, X, y in work)
    return {c: (r, y) for (c, _, y), r in zip(work, res)}


def family_matrix(result: dict, oos: np.ndarray, cost: float) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Per-day net P&L matrix (OOS days x strategies) and a per-strategy summary."""
    cols, rows = {}, []
    for (T, h), (preds, y) in result.items():
        for model, pred in preds.items():
            for rule, (gross, trade) in strategies(pred, y).items():
                net = np.where(trade, gross - cost, 0.0)[oos]
                name = f"{cell_name(T, h)}|{model}|{rule}"
                cols[name] = net
                tr = trade[oos]
                p, yy = pred[oos], y[oos]
                ok = ~np.isnan(p) & ~np.isnan(yy)
                ic = float(np.corrcoef(p[ok], yy[ok])[0, 1]) if ok.sum() > 10 and np.std(p[ok]) > 0 else np.nan
                rows.append({"strategy": name, "decision": hm(T), "horizon": h, "model": model, "rule": rule,
                             "trades": int(tr.sum()), "oos_ic": ic,
                             "hit_rate": float((gross[oos][tr] > 0).mean()) if tr.any() else np.nan,
                             "gross_per_trade": float(gross[oos][tr].mean()) if tr.any() else np.nan,
                             "net_per_trade": float(net[tr].mean()) if tr.any() else np.nan,
                             "net_total_ticks": float(net.sum())})
    return pd.DataFrame(cols), pd.DataFrame(rows)


def gross_matrices(result: dict, oos: np.ndarray) -> tuple[np.ndarray, np.ndarray, list]:
    g, t, names = [], [], []
    for (T, h), (preds, y) in result.items():
        for model, pred in preds.items():
            for rule, (gross, trade) in strategies(pred, y).items():
                g.append(gross[oos])
                t.append(trade[oos])
                names.append(f"{cell_name(T, h)}|{model}|{rule}")
    return np.column_stack(g), np.column_stack(t), names


def evaluate(result: dict, oos: np.ndarray, days: np.ndarray, seed: int = 0) -> pd.DataFrame:
    out = None
    for label, cost in (("base", BASE_TICKS), ("stress", STRESS_TICKS)):
        mat, summ = family_matrix(result, oos, cost)
        rw = romano_wolf(mat.to_numpy(), n_boot=N_BOOT, mean_block=MEAN_BLOCK, seed=seed)
        summ[f"t_{label}"] = rw["t"]
        summ[f"rw_p_{label}"] = rw["p_adj"]
        if label == "base":
            yrs = pd.to_datetime(days[oos], unit="D").year.to_numpy()
            for name, block in (("2012", [2012]), ("2013-14", [2013, 2014]), ("2015-16", [2015, 2016])):
                m = np.isin(yrs, block)
                summ[f"net_{name}"] = mat[m].sum().to_numpy()
            out = summ
        else:
            out["net_per_trade_stress"] = summ["net_per_trade"].to_numpy()
            out["t_stress"], out["rw_p_stress"] = summ["t_stress"].to_numpy(), summ["rw_p_stress"].to_numpy()
    g, tr, names = gross_matrices(result, oos)
    ub = simultaneous_upper(g, tr, n_boot=N_BOOT, mean_block=MEAN_BLOCK, seed=seed + 1)
    assert list(out["strategy"]) == names
    out["gross_upper95_simultaneous"] = ub["upper"]
    known = ~np.isnan(ub["upper"])  # NaN = no trades or no bootstrap variation: no claim either way
    out["upper_below_stress_cost"] = pd.array(np.where(known, ub["upper"] < STRESS_TICKS, False), dtype="boolean")
    out.loc[~known, "upper_below_stress_cost"] = pd.NA
    out["upper_below_base_cost"] = pd.array(np.where(known, ub["upper"] < BASE_TICKS, False), dtype="boolean")
    out.loc[~known, "upper_below_base_cost"] = pd.NA
    out.attrs["c"] = ub["c"]
    return out


def best_rw(result: dict, oos: np.ndarray, seed: int) -> float:
    mat, _ = family_matrix(result, oos, BASE_TICKS)
    return float(romano_wolf(mat.to_numpy(), n_boot=N_BOOT, mean_block=MEAN_BLOCK, seed=seed)["p_adj"].min())


def within_year(y: np.ndarray, years: np.ndarray, f) -> np.ndarray:
    """Apply a label permutation f inside each calendar year, so no label crosses a walk-forward fold."""
    out = y.copy()
    for Y in np.unique(years):
        m = years == Y
        out[m] = f(y[m])
    return out


def block_shuffle(v: np.ndarray, rng) -> np.ndarray:
    blocks = [v[i:i + SHUFFLE_BLOCK] for i in range(0, len(v), SHUFFLE_BLOCK)]
    return np.concatenate([blocks[k] for k in rng.permutation(len(blocks))])


def power_table(controls: pd.DataFrame) -> pd.DataFrame:
    """Detection rate (min RW p < 0.05 for the planted cell) per edge size, with a Wilson 95% interval."""
    rows = []
    for e, g in controls[controls["control"].str.startswith("planted_")].groupby("param"):
        k, n = int((g["min_rw_p"] < 0.05).sum()), len(g)
        lo = 1 - wilson_upper(n - k, n)
        rows.append({"planted_net_ticks": e, "reps": n, "detected": k, "power": k / n, "power_lo95": lo,
                     "power_hi95": wilson_upper(k, n), "oracle_net_ticks_mean": g["oracle_net_ticks"].mean()})
    return pd.DataFrame(rows)


# ---------------------------------------------------------------- main -------------------------------

def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--quick", action="store_true", help="2 decision times x 2 horizons, few controls, 200 draws")
    ap.add_argument("--jobs", type=int, default=10)
    a = ap.parse_args(argv)
    t_start = time.time()
    tag = "quick" if a.quick else "full"
    global N_BOOT
    times = [9 * 60, 14 * 60 + 35] if a.quick else DECISION_TIMES
    horizons = [30, "flat"] if a.quick else HORIZONS
    n_shifts, n_shuffles, n_random, reps = (1, 1, 1, 2) if a.quick else (N_SHIFTS, N_SHUFFLES, N_RANDOM, PLANT_REPS)
    if a.quick:
        N_BOOT = 200

    df = data.load_front("discovery", ITEM, f"S003 ceiling ({tag}): front month")
    df2 = data.load_second("discovery", ITEM, f"S003 ceiling ({tag}): second month (slope feature)")
    eia_days, _ = eia_calendar_split(np.unique(df["trading_day"]))
    F = Features(df, df2, eia_days)
    days = F.days
    years = pd.to_datetime(days, unit="D").year.to_numpy()
    oos = np.isin(years, TEST_YEARS)
    all_times = times + ([] if a.quick else NEGATIVE_CONTROL_TIMES)
    feats = {T: F.at(T) for T in all_times}
    targs = {T: targets(df, days, T) for T in all_times}
    cells = [(T, h) for T in times for h in horizons]
    cells = list(dict.fromkeys(cells))
    print(f"features built: {len(days)} days, {len(cells)} cells, {time.time() - t_start:.0f} s", flush=True)

    real = run_pipeline(feats, targs, cells, years, a.jobs)
    summary = evaluate(real, oos, days)
    spa = spa_test(family_matrix(real, oos, BASE_TICKS)[0].to_numpy(), n_boot=N_BOOT, mean_block=MEAN_BLOCK)
    print(f"real run done, {time.time() - t_start:.0f} s", flush=True)

    controls = []
    rng = np.random.default_rng(2026)
    for k in range(n_shifts):  # fold-safe: labels rolled inside each calendar year (no wrap across folds)
        shift = int(rng.integers(20, 200))
        res = run_pipeline(feats, targs, cells, years, a.jobs,
                           transform=lambda c, X, y, s_=shift: (X, within_year(y, years, lambda v: np.roll(v, s_))))
        controls.append({"control": "circular_shift_in_year", "rep": k, "param": shift, "min_rw_p": best_rw(res, oos, k)})
    for k in range(n_shuffles):  # blocks of 20 days shuffled inside each calendar year
        g = np.random.default_rng(300 + k)
        res = run_pipeline(feats, targs, cells, years, a.jobs,
                           transform=lambda c, X, y, g_=g: (X, within_year(y, years, lambda v: block_shuffle(v, g_))))
        controls.append({"control": "block_shuffle_in_year", "rep": k, "param": SHUFFLE_BLOCK,
                         "min_rw_p": best_rw(res, oos, 20 + k)})
    for k in range(n_random):
        r2 = np.random.default_rng(100 + k)
        res = run_pipeline(feats, targs, cells, years, a.jobs,
                           transform=lambda c, X, y, g=r2: (pd.DataFrame(g.normal(size=X.shape), index=X.index), y))
        controls.append({"control": "random_features", "rep": k, "min_rw_p": best_rw(res, oos, 10 + k)})

    def with_cell(cell, X, y):
        """The real family with one cell replaced (planted / leaked runs keep the full family size)."""
        res = run_pipeline(feats, targs, [cell], years, a.jobs, transform=lambda c, X_, y_: (X, y))
        fam = dict(real)
        fam[cell] = res[cell]
        mat, summ = family_matrix(fam, oos, BASE_TICKS)
        rw = romano_wolf(mat.to_numpy(), n_boot=N_BOOT, mean_block=MEAN_BLOCK, seed=7)
        mask = summ["strategy"].str.startswith(cell_name(*cell) + "|").to_numpy()
        return float(rw["p_adj"][mask].min())

    plant_cells = [c for c in PLANT_CELLS if c in cells] or cells[:1]
    for r in range(reps):  # the same planted signal for every edge size (paired)
        cell = plant_cells[r % len(plant_cells)]
        X = feats[cell[0]].drop(columns="_valid")
        y = np.where(feats[cell[0]]["_valid"], targs[cell[0]][cell[1]].to_numpy(), np.nan)
        g = np.random.default_rng(1000 + r)
        pool = [c for c in X.columns if c.startswith("ret_") or c in ("vwap_dist", "range_pos_today")]
        cols = list(g.choice(pool, 3, replace=False))
        coef = g.normal(size=3)
        z = X[cols].fillna(0).to_numpy()
        z = (z - z.mean(axis=0)) / np.where(z.std(axis=0) > 0, z.std(axis=0), 1)
        sgn = np.sign(z @ coef)
        for e in PLANT_EDGES:
            y_pl = y + (e + BASE_TICKS) * sgn  # an oracle trading sgn earns about e net ticks
            ok = oos & ~np.isnan(y_pl) & (sgn != 0)
            realised = float(np.mean(sgn[ok] * y_pl[ok]) - BASE_TICKS)
            controls.append({"control": f"planted_{e}", "rep": r, "cell": cell_name(*cell), "param": e,
                             "features": "+".join(cols), "oracle_net_ticks": realised,
                             "min_rw_p": with_cell(cell, X, y_pl)})
    leak_cell = plant_cells[0]
    X = feats[leak_cell[0]].drop(columns="_valid").copy()
    y = np.where(feats[leak_cell[0]]["_valid"], targs[leak_cell[0]][leak_cell[1]].to_numpy(), np.nan)
    gl = np.random.default_rng(55)
    X["leak"] = np.sign(np.nan_to_num(y)) * np.where(gl.random(len(y)) < 0.3, -1, 1)  # 70% right sign
    controls.append({"control": "leaked_feature", "rep": 0, "cell": cell_name(*leak_cell),
                     "min_rw_p": with_cell(leak_cell, X, y)})
    neg = None
    if not a.quick:
        neg_cells = [(T, h) for T in NEGATIVE_CONTROL_TIMES for h in HORIZONS]
        neg_res = run_pipeline(feats, targs, neg_cells, years, a.jobs)
        neg = evaluate(neg_res, oos, days, seed=3)
    controls = pd.DataFrame(controls)
    print(f"controls done, {time.time() - t_start:.0f} s", flush=True)

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out = paths.OUT_DIR / "s003" / f"{stamp}_{tag}"
    out.mkdir(parents=True, exist_ok=True)
    power = power_table(controls)
    tables = {"strategies": summary, "controls": controls, "power": power}
    if neg is not None:
        tables["negative_control"] = neg
    for k, t in tables.items():
        t.to_csv(out / f"{k}.csv", index=False)
        if not a.quick:
            t.to_csv(REPORT_DIR / f"{k}.csv", index=False, float_format="%.5g")
    n_sig = int((summary["rw_p_base"] < 0.05).sum())
    n_sig_stress = int((summary["rw_p_stress"] < 0.05).sum())
    manifest = {"item": ITEM, "stamp": stamp, "tag": tag, "code_sha256": code_hash(), "data": fingerprint(df),
                "data_second": fingerprint(df2), "cells": [cell_name(*c) for c in cells], "models": MODELS,
                "test_years": TEST_YEARS, "n_boot": N_BOOT, "strategies": len(summary),
                "rw_sig_base": n_sig, "rw_sig_stress": n_sig_stress, "spa": spa,
                "simultaneous_c": summary.attrs.get("c"),
                "all_upper_below_stress": bool(summary["upper_below_stress_cost"].dropna().all()),
                "strategies_without_bound": int(summary["upper_below_stress_cost"].isna().sum()),
                "max_gross_upper95": float(summary["gross_upper95_simultaneous"].max()),
                "seconds": round(time.time() - t_start)}
    (out / "manifest.json").write_text(json.dumps(manifest, indent=1, default=str))
    ledger.append(ITEM, "exploratory", "discovery", n_tests=len(summary),
                  statistic="S003 ceiling: Romano-Wolf over all (cell, model, rule) strategies, base cost",
                  value=n_sig, p_value=float(summary["rw_p_base"].min()), verdict="DESCRIPTIVE",
                  code_sha256=manifest["code_sha256"], data_sha256=manifest["data"]["sha256_all_columns"],
                  output=str(out.relative_to(paths.ROOT)),
                  note=f"{tag}: {len(cells)} cells x {len(MODELS)} models x {len(RULES)} rules; value = RW p<0.05 "
                       f"at base; stress {n_sig_stress}; SPA p {spa['p']:.3f}; controls {len(controls)} runs")
    with pd.option_context("display.width", 250, "display.max_columns", 30):
        print(summary.sort_values("rw_p_base").head(15).round(3).to_string(index=False))
        print(controls.drop(columns=[c for c in ("features",) if c in controls]).round(4).to_string(index=False))
        print(power.round(3).to_string(index=False))
        print(f"max simultaneous gross upper bound {summary['gross_upper95_simultaneous'].max():.2f} ticks "
              f"(stress cost {STRESS_TICKS:.3f}); all below stress: {manifest['all_upper_below_stress']}")
    print(f"S003 {tag}: {len(summary)} strategies, RW p<0.05 base {n_sig} / stress {n_sig_stress}, SPA p "
          f"{spa['p']:.3f}, {time.time() - t_start:.0f} s; outputs {out}")


if __name__ == "__main__":
    main()
