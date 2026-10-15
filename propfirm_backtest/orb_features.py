"""Daily features for the ORB families (ZAB, Crabel, Fisher ACD), with no look-ahead.

A "session" for an anchor = anchor time -> 14:30 ET (end of the NYMEX day session) on ONE front
contract. Per trading day: session open, high, low, close (last trade before 14:30 = settlement
PROXY, not the official settlement). Everything a strategy may use on day d is built ONLY from
sessions completed before day d; day d's own session (its later validity included) never matters:
  ATR14     mean of the last 14 available true ranges; a true range uses the previous close of the
            SAME contract, so the first session after a roll has none (no roll gap leaks in) and is skipped
  stretch   Crabel: mean of min(high - open, open - low) over the previous 10 valid sessions
  NR4 / NR7 the previous session's range was the narrowest of the last 4 / 7 sessions
  inside    the previous session was inside the one before it; ID/NR4 = inside AND NR4
  pivot     from the previous session (same contract): P = (H+L+C)/3, BC = (H+L)/2, TC = 2P - BC;
            range [min(BC, TC), max(BC, TC)]
Relative opening volume = today's opening-range volume / mean of the previous 14 valid days' volume in
the same window. It is known at the end of the range, which is when the strategies may use it.
"""

import numpy as np
import pandas as pd

from . import orb_engine as E

SESSION_END_MOD = 14 * 60 + 30
ATR_DAYS = 14
STRETCH_DAYS = 10
RELVOL_DAYS = 14
MIN_SESSION_MINUTES = 60  # fewer traded minutes = no usable session statistics


class Sessions:
    """Per trading day session statistics and the prior-session features for one anchor."""

    def __init__(self, f: E.Front, days: np.ndarray, anchor: str):
        tz, minute, before = E.ANCHORS[anchor]
        start = E.local_tmin(days, minute, tz, before)
        end = E.local_tmin(days, SESSION_END_MOD, E.ET)
        i = np.searchsorted(f.tmin, start)
        j = np.searchsorted(f.tmin, end)
        n = len(f)
        ok = j - i >= MIN_SESSION_MINUTES
        ii, ll = np.where(ok, i, 0), np.where(ok, j - 1, 0)
        ok &= f.contract[ii] == f.contract[ll]
        nd = len(days)
        self.valid = ok
        self.contract = np.where(ok, f.contract[ii], -1)
        self.open = np.full(nd, np.nan)
        self.high = np.full(nd, np.nan)
        self.low = np.full(nd, np.nan)
        self.close = np.full(nd, np.nan)
        if ok.any():
            bounds = np.column_stack([i[ok], j[ok]]).ravel()
            pad = lambda a: np.append(a, a[-1])  # noqa: E731  a session can end at the last row (j == n)
            self.high[ok] = np.maximum.reduceat(pad(f.high), bounds)[::2]
            self.low[ok] = np.minimum.reduceat(pad(f.low), bounds)[::2]
            self.open[ok] = f.open[i[ok]]
            self.close[ok] = f.close[j[ok] - 1]
        # the contract trading at the anchor: known at the anchor, unlike the session's later validity
        first = np.minimum(i, n - 1)
        self.today_contract = np.where(i < n, f.contract[first], -1)
        self._derive()

    def _derive(self):
        """Features of day d use ONLY sessions completed before day d, whatever happens later on day d."""
        idx = np.flatnonzero(self.valid)  # completed sessions with usable statistics, in order
        nd = len(self.valid)
        k = np.searchsorted(idx, np.arange(nd))  # number of usable sessions before each day
        H, L, C, O, K = self.high[idx], self.low[idx], self.close[idx], self.open[idx], self.contract[idx]

        same = np.concatenate([[False], K[1:] == K[:-1]])  # previous usable session = same contract
        prev_c = np.concatenate([[np.nan], C[:-1]])
        tr = np.where(same, np.maximum(H, prev_c) - np.minimum(L, prev_c), np.nan)
        self.atr14 = self._mean_of_last(tr, k, ATR_DAYS)  # roll sessions have no true range: skipped
        self.stretch = self._mean_of_last(np.minimum(H - O, O - L), k, STRETCH_DAYS)

        rng = pd.Series(H - L)
        nr4 = (rng == rng.rolling(4, min_periods=4).min()).to_numpy()
        nr7 = (rng == rng.rolling(7, min_periods=7).min()).to_numpy()
        inside = same & np.concatenate([[False], (H[1:] < H[:-1]) & (L[1:] > L[:-1])])  # roll shifts prices
        has_prev = k >= 1
        prev = np.maximum(k - 1, 0)
        self.nr4 = has_prev & nr4[prev] if len(idx) else np.zeros(nd, bool)
        self.nr7 = has_prev & nr7[prev] if len(idx) else np.zeros(nd, bool)
        self.inside = has_prev & inside[prev] if len(idx) else np.zeros(nd, bool)
        self.idnr4 = self.inside & self.nr4

        self.piv_lo = np.full(nd, np.nan)
        self.piv_hi = np.full(nd, np.nan)
        if len(idx):
            p = (H + L + C) / 3.0
            bc = (H + L) / 2.0
            tc = 2 * p - bc
            ok = has_prev & (K[prev] == self.today_contract)  # pivot only from the same contract
            self.piv_lo[ok] = np.minimum(bc, tc)[prev[ok]]
            self.piv_hi[ok] = np.maximum(bc, tc)[prev[ok]]

    @staticmethod
    def _mean_of_last(x, k, window):
        """Per day: mean of the last `window` non-NaN x among the first k usable sessions (NaN if fewer)."""
        good = np.flatnonzero(~np.isnan(x))
        cum = np.concatenate([[0.0], np.cumsum(x[good])])
        m = np.searchsorted(good, k)  # non-NaN values among the first k sessions
        out = np.full(len(k), np.nan)
        enough = m >= window
        out[enough] = (cum[m[enough]] - cum[m[enough] - window]) / window
        return out


def relative_volume(rvol: np.ndarray, valid: np.ndarray, window: int = RELVOL_DAYS) -> np.ndarray:
    """Today's opening-range volume / mean of the previous `window` valid days (today excluded)."""
    idx = np.flatnonzero(valid)
    mean = pd.Series(rvol[idx]).rolling(window, min_periods=window).mean().shift(1).to_numpy()
    out = np.full(len(rvol), np.nan)
    with np.errstate(divide="ignore", invalid="ignore"):
        out[idx] = np.where(mean > 0, rvol[idx] / mean, np.nan)
    return out
