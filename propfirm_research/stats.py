"""Statistics without scipy (stdlib NormalDist). Unit of inference: the trading day (PROTOCOL §4.1).

Large-sample normal approximations: fine for hundreds of day clusters, not for tiny samples.
"""

import functools
import math
from statistics import NormalDist

import numpy as np
import pandas as pd

ND = NormalDist()


def wilson_upper(k: int, n: int, conf: float = 0.95) -> float:
    """One-sided upper confidence bound of a proportion k/n (Wilson score)."""
    if n == 0:
        return 1.0
    z = ND.inv_cdf(conf)
    p = k / n
    centre = p + z * z / (2 * n)
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return min(1.0, (centre + half) / (1 + z * z / n))


def clustered_mean(x: np.ndarray, day: np.ndarray) -> dict:
    """Mean of x with a day-clustered standard error. Returns mean, se, t, p (two-sided), n, days."""
    x = np.asarray(x, float)
    day = np.asarray(day)
    ok = ~np.isnan(x)
    x, day = x[ok], day[ok]
    n = len(x)
    if n < 2:
        return {"mean": np.nan, "se": np.nan, "t": np.nan, "p": np.nan, "n": n, "days": 0}
    mean = x.mean()
    resid = pd.Series(x - mean).groupby(day).sum().to_numpy()
    k = len(resid)
    var = (resid ** 2).sum() / n ** 2 * k / max(k - 1, 1)
    se = math.sqrt(var) if var > 0 else np.nan
    t = mean / se if se and se > 0 else np.nan
    p = 2 * (1 - ND.cdf(abs(t))) if not np.isnan(t) else np.nan
    return {"mean": float(mean), "se": se, "t": t, "p": p, "n": n, "days": k}


def newey_west_se(x: np.ndarray, lags: int) -> float:
    """HAC standard error of the mean of a time-ordered series (Bartlett kernel)."""
    x = np.asarray(x, float)
    x = x[~np.isnan(x)]
    n = len(x)
    e = x - x.mean()
    s = (e @ e) / n
    for L in range(1, lags + 1):
        s += 2 * (1 - L / (lags + 1)) * (e[L:] @ e[:-L]) / n
    return math.sqrt(max(s, 0) / n)


def bh_qvalues(p) -> np.ndarray:
    """Benjamini-Hochberg q-values (same order as p; nan stays nan)."""
    p = np.asarray(p, float)
    q = np.full_like(p, np.nan)
    ok = ~np.isnan(p)
    pv = p[ok]
    m = len(pv)
    if m == 0:
        return q
    order = np.argsort(pv)
    ranked = pv[order] * m / np.arange(1, m + 1)
    ranked = np.minimum.accumulate(ranked[::-1])[::-1]
    out = np.empty(m)
    out[order] = np.minimum(ranked, 1.0)
    q[ok] = out
    return q


def mde_annual_sharpe(n_days: int, alpha: float = 0.01, power: float = 0.8, one_sided: bool = True) -> float:
    """Smallest annual Sharpe (daily P&L) detectable with n_days at the given alpha and power."""
    za = ND.inv_cdf(1 - alpha) if one_sided else ND.inv_cdf(1 - alpha / 2)
    zb = ND.inv_cdf(power)
    return (za + zb) / math.sqrt(n_days) * math.sqrt(252)


def variance_ratio(r: np.ndarray, q: int) -> dict:
    """Lo-MacKinlay (1988) variance ratio of overlapping q-period sums of one-period returns r, with the
    unbiased denominators and the heteroskedasticity-robust z. VR > 1 = trending, < 1 = mean-reverting."""
    r = np.asarray(r, float)
    r = r[~np.isnan(r)]
    n = len(r)
    if not 2 <= q < n:
        raise ValueError("need 2 <= q < number of returns")
    mu = r.mean()
    e = r - mu
    var1 = (e @ e) / (n - 1)
    rq = np.convolve(r, np.ones(q), "valid")  # n - q + 1 overlapping sums
    m = q * (n - q + 1) * (1 - q / n)
    varq = ((rq - q * mu) ** 2).sum() / m
    vr = varq / var1
    theta = 0.0
    denom = (e @ e) ** 2
    for j in range(1, q):
        delta = ((e[j:] ** 2) @ (e[:-j] ** 2)) / denom  # R007 #1: an extra factor n here shrank z by sqrt(n)
        theta += (2 * (q - j) / q) ** 2 * delta
    z = (vr - 1) / math.sqrt(theta) if theta > 0 else np.nan
    return {"vr": float(vr), "z": float(z), "n": n}


def _t_cdf(x: float, df: int) -> float:
    """Student-t CDF for x >= 0 by Simpson integration of the density (no scipy)."""
    c = math.exp(math.lgamma((df + 1) / 2) - math.lgamma(df / 2)) / math.sqrt(df * math.pi)
    m = 2000
    u = np.linspace(0.0, x, m + 1)
    w = np.where(np.arange(m + 1) % 2, 4.0, 2.0)
    w[0] = w[-1] = 1.0
    f = (1 + u * u / df) ** (-(df + 1) / 2)
    return min(1.0, 0.5 + c * float(w @ f) * (x / m) / 3)


@functools.lru_cache(maxsize=256)
def t_quantile(p: float, df: int) -> float:
    """Student-t quantile (no scipy): bisection on a Simpson-integrated CDF. Accurate to ~1e-6."""
    if not 0 < p < 1 or df < 1:
        raise ValueError("need 0 < p < 1 and df >= 1")
    if p < 0.5:
        return -t_quantile(1 - p, df)
    lo, hi = 0.0, 1.0
    while _t_cdf(hi, df) < p:
        hi *= 2
    for _ in range(60):
        mid = (lo + hi) / 2
        lo, hi = (mid, hi) if _t_cdf(mid, df) < p else (lo, mid)
    return (lo + hi) / 2


def t_pvalue(t: float, df: int) -> float:
    """Two-sided p-value of a Student-t statistic."""
    if math.isnan(t) or df < 1:
        return float("nan")
    x = min(abs(t), 60.0)
    return max(0.0, 2 * (1 - _t_cdf(x, df)))


def variance_ratio_days(r: np.ndarray, day: np.ndarray, q: int, n_boot: int = 500, seed: int = 0) -> dict:
    """Variance ratio of q-period sums built only inside runs of consecutive returns of one trading day
    (r is NaN at every gap; a new day starts a new run), with a trading-day bootstrap z (PROTOCOL: the day
    is the unit of inference). VR > 1 = trending, < 1 = mean-reverting."""
    r = np.asarray(r, float)
    day = np.asarray(day)
    if q < 2:
        raise ValueError("need q >= 2")
    if r.shape != day.shape:
        raise ValueError("r and day must have the same length")
    brk = np.isnan(r) | np.r_[True, day[1:] != day[:-1]]
    run = np.cumsum(brk)
    ok = ~np.isnan(r)
    frame = pd.DataFrame({"r": r[ok], "run": run[ok], "day": day[ok]})
    days = pd.unique(frame["day"])
    di = pd.Index(days)
    s1 = frame.groupby("day")["r"].sum().reindex(days).to_numpy()
    s2 = (frame["r"] ** 2).groupby(frame["day"]).sum().reindex(days).to_numpy()
    n1 = frame.groupby("day").size().reindex(days).to_numpy()
    sums = frame.groupby("run")["r"].transform(lambda x: x.rolling(q).sum())
    full = ~np.isnan(sums.to_numpy())
    qd = frame["day"].to_numpy()[full]
    qs = sums.to_numpy()[full]
    q1 = np.bincount(di.get_indexer(qd), qs, len(days))
    q2 = np.bincount(di.get_indexer(qd), qs ** 2, len(days))
    m1 = np.bincount(di.get_indexer(qd), None, len(days))

    def vr(w):
        n, m = (w * n1).sum(), (w * m1).sum()
        if m < 2 or n < 2:
            return np.nan
        var1 = (w * s2).sum() / n - ((w * s1).sum() / n) ** 2
        varq = (w * q2).sum() / m - ((w * q1).sum() / m) ** 2
        return varq / (q * var1) if var1 > 0 else np.nan

    est = vr(np.ones(len(days)))
    rng = np.random.default_rng(seed)
    boot = np.array([vr(np.bincount(rng.integers(0, len(days), len(days)), minlength=len(days)))
                     for _ in range(n_boot)])
    se = float(np.nanstd(boot, ddof=1))
    z = (est - 1) / se if se > 0 else np.nan
    return {"vr": float(est), "se": se, "z": float(z), "p": 2 * (1 - ND.cdf(abs(z))) if np.isfinite(z) else np.nan,
            "n": int(n1.sum()), "q_sums": int(m1.sum()), "days": len(days)}


def mean_upper(x, conf: float = 0.95) -> float:
    """One-sided upper confidence bound of a mean from independent units (t interval)."""
    x = np.asarray(x, float)
    n = len(x)
    if n < 2:
        return float("nan")
    return float(x.mean() + t_quantile(conf, n - 1) * x.std(ddof=1) / math.sqrt(n))


def stationary_bootstrap_indices(n: int, mean_block: float, rng) -> np.ndarray:
    """Politis-Romano stationary bootstrap: blocks of geometric length (mean `mean_block`) that wrap around."""
    if n < 1 or mean_block < 1:
        raise ValueError("need n >= 1 and mean_block >= 1")
    p = 1.0 / mean_block
    idx = np.empty(n, np.int64)
    idx[0] = rng.integers(n)
    new = rng.random(n) < p
    starts = rng.integers(0, n, n)
    for t in range(1, n):
        idx[t] = starts[t] if new[t] else (idx[t - 1] + 1) % n
    return idx


def _boot_means(x: np.ndarray, n_boot: int, mean_block: float, seed: int) -> np.ndarray:
    rng = np.random.default_rng(seed)
    n = len(x)
    return np.stack([x[stationary_bootstrap_indices(n, mean_block, rng)].mean(axis=0) for _ in range(n_boot)])


def romano_wolf(x: np.ndarray, n_boot: int = 1000, mean_block: float = 5.0, seed: int = 0) -> dict:
    """Romano-Wolf step-down max-t for H0_k: mean_k <= 0 against mean_k > 0, k = columns of x (rows = days,
    in time order; a day without a trade is 0). Stationary bootstrap of whole rows keeps the dependence
    between cells and over time. Returns per-column t and family-wise adjusted p-values."""
    x = np.asarray(x, float)
    if x.ndim != 2 or len(x) < 10 or not np.isfinite(x).all():
        raise ValueError("x must be a finite 2-D array with >= 10 rows")
    n, k = x.shape
    mean, sd = x.mean(axis=0), x.std(axis=0, ddof=1)
    se = np.where(sd > 0, sd / math.sqrt(n), np.inf)
    t = mean / se
    bm = _boot_means(x, n_boot, mean_block, seed)
    tb = (bm - mean) / se  # centred bootstrap t (null imposed)
    order = np.argsort(-t)
    p_adj = np.empty(k)
    prev = 0.0
    for j, col in enumerate(order):
        rest = order[j:]
        mx = tb[:, rest].max(axis=1)
        p = float(((mx >= t[col]).sum() + 1) / (n_boot + 1))  # never exactly 0
        prev = max(prev, p)  # step-down monotonicity
        p_adj[col] = prev
    return {"t": t, "p_adj": p_adj, "mean": mean, "se": se}


def spa_test(x: np.ndarray, n_boot: int = 1000, mean_block: float = 5.0, seed: int = 0) -> dict:
    """Hansen (2005) SPA test (consistent version) of H0: no column beats 0 (benchmark = flat). x as in
    romano_wolf: per-day excess P&L of each candidate. Small p = the best candidate is real."""
    x = np.asarray(x, float)
    if x.ndim != 2 or len(x) < 10 or not np.isfinite(x).all():
        raise ValueError("x must be a finite 2-D array with >= 10 rows")
    n, k = x.shape
    mean = x.mean(axis=0)
    sd = x.std(axis=0, ddof=1)
    se = np.where(sd > 0, sd / math.sqrt(n), np.inf)
    stat = max(0.0, float((mean / se).max()))
    keep = mean >= -se * math.sqrt(2 * math.log(math.log(n)))  # recentre only plausible nulls
    mu_c = np.where(keep, mean, 0.0)
    bm = _boot_means(x, n_boot, mean_block, seed)
    tb = np.maximum(0.0, ((bm - mu_c) / se).max(axis=1))  # Hansen: d* - g_c(mean)
    return {"stat": stat, "p": float(((tb >= stat).sum() + 1) / (n_boot + 1)), "best": int(np.argmax(mean / se))}


def simultaneous_upper(gross: np.ndarray, trade: np.ndarray, conf: float = 0.95, n_boot: int = 2000,
                       mean_block: float = 5.0, seed: int = 0) -> dict:
    """Simultaneous one-sided upper confidence bounds of the gross edge per trade of K strategies.
    gross, trade: days x K (gross P&L of the day, 0 without a trade; trade flag). Estimand per column:
    sum(gross) / sum(trades). Stationary bootstrap of whole days; bound_k = est_k + c * se_k with c the
    `conf` quantile of max_k (est_k - est*_k) / se_k, so all K bounds hold together with prob. `conf`."""
    g = np.asarray(gross, float)
    tr = np.asarray(trade, bool).astype(float)
    if g.shape != tr.shape or g.ndim != 2 or len(g) < 10:
        raise ValueError("gross and trade must be the same 2-D shape with >= 10 rows")
    n_tr = tr.sum(axis=0)
    has = n_tr > 0
    est = np.where(has, g.sum(axis=0) / np.where(has, n_tr, 1), np.nan)
    rng = np.random.default_rng(seed)
    boots = np.empty((n_boot, g.shape[1]))
    for b in range(n_boot):
        i = stationary_bootstrap_indices(len(g), mean_block, rng)
        nb = tr[i].sum(axis=0)
        boots[b] = np.where(nb > 0, g[i].sum(axis=0) / np.where(nb > 0, nb, 1), np.nan)
    se = np.nanstd(boots, axis=0, ddof=1)
    ok = has & (se > 0)
    if not ok.any():
        raise ValueError("no strategy with trades and bootstrap variation")
    dev = (est[ok] - boots[:, ok]) / se[ok]
    row_max = np.where(np.isnan(dev).all(axis=1), np.nan, np.nanmax(np.where(np.isnan(dev), -np.inf, dev), axis=1))
    c = float(np.nanquantile(row_max, conf))
    upper = np.full(g.shape[1], np.nan)
    upper[ok] = est[ok] + c * se[ok]
    return {"est": est, "se": se, "upper": upper, "c": c}
