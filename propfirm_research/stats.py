"""Statistics without scipy (stdlib NormalDist). Unit of inference: the trading day (PROTOCOL §4.1).

Large-sample normal approximations: fine for hundreds of day clusters, not for tiny samples.
"""

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
        delta = n * ((e[j:] ** 2) @ (e[:-j] ** 2)) / denom
        theta += (2 * (q - j) / q) ** 2 * delta
    z = (vr - 1) / math.sqrt(theta) if theta > 0 else np.nan
    return {"vr": float(vr), "z": float(z), "n": n}
