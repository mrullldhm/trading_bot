"""S002 market atlas of CL on discovery data (research/studies/S002-atlas/report.md). Exploratory only.
Reviewed by Codex before the headline run (R007).

Building blocks:
- segment returns come from grid.windows (entry = open of the decision minute, exit = open of the end
  minute, never across a contract change, evening minutes belong to the next trading day);
- 1-minute returns are close-to-close between consecutive UTC minutes of one contract and one trading
  day (a missing minute breaks the chain);
- EIA days = normal weeks of the published-rule calendar (Wednesday 10:30); holiday weeks (several
  candidate slots) are a separate stratum, never picked by volume;
- every p-value goes into one Benjamini-Hochberg pass; each inferential table carries its q-values and
  the three discovery-block estimates. Exploratory threshold q < 0.10 (PROTOCOL §4).

Usage: python -m propfirm_research.studies.s002_atlas [--quick]
"""

import argparse
import hashlib
import json
import time
from datetime import datetime, timezone

import numpy as np
import pandas as pd

from propfirm_backtest import orb_engine as E
from propfirm_data import eia_calendar

from .. import costs, data, grid, ledger, paths
from ..stats import bh_qvalues, clustered_mean, t_pvalue, variance_ratio_days
from .s001_feasibility import code_hash

ITEM = "S002"
REPORT_DIR = paths.RESEARCH_DIR / "studies" / "S002-atlas"
DAY = 18 * 60
BIN = 30
BIN_STARTS = [(DAY + k * BIN) % 1440 for k in range(44)]  # 18:00 .. 15:30, last bin ends 16:00
BLOCKS = {"2010-12": (2010, 2012), "2013-14": (2013, 2014), "2015-16": (2015, 2016)}
SESSIONS = {"asia": (19 * 60, 3 * 60), "london": (3 * 60, 8 * 60), "ny": (8 * 60, 16 * 60 + 5)}
VR_Q = [5, 15, 30, 60]
THIN_LOTS = 5
EIA_MOD = 10 * 60 + 30
Q_DECISION = 0.10
TERM_STALE_MIN = 10  # the front / second pair must be from the same minute, at most this long before 09:00
ROLL_WEEK_DAYS = 7
BASE_TICKS = costs.round_trip_ticks(costs.BASE_SLIP)
STRESS_TICKS = costs.round_trip_ticks(costs.STRESS_SLIP)
F_ = grid.FLAT
EVENTS = [  # (name, ET minute, length in minutes, which days)
    ("09:00 open", 9 * 60, 5, "all"), ("EIA 10:30", EIA_MOD, 5, "eia"),
    ("settlement 14:28-14:30", 14 * 60 + 28, 2, "all"), ("London 03:00", 3 * 60, 5, "all"),
]
WINDOWS = [  # (name, (decision, exit), EIA days only): S001 templates and the BACKLOG / R006 windows
    ("03:00-08:00", (180, 480), False), ("07:56-08:25", (476, 505), False), ("09:00-10:00", (540, 600), False),
    ("09:00-12:00", (540, 720), False), ("09:00-16:05", (540, F_), False), ("09:06-09:30", (546, 570), False),
    ("10:01-10:25 EIA", (601, 625), True), ("10:35-11:30", (635, 690), False),
    ("10:36-11:30 EIA", (636, 690), True), ("14:00-14:30", (840, 870), False), ("14:01-14:30", (841, 870), False),
    ("14:00-16:05", (840, F_), False), ("14:35-16:05", (875, F_), False), ("18:05-20:00", (1085, 1200), False),
    ("20:00-03:00", (1200, 180), False),
]
LEAD_LAG = [  # (name, pre window, target start, EIA days only)
    ("09:00", (510, 540), 540, False), ("14:00", (810, 840), 840, False), ("EIA 10:30", (630, 635), 635, True),
]


def hm(mod: int) -> str:
    return "flat" if mod == F_ else f"{mod // 60:02d}:{mod % 60:02d}"


def year_of(days) -> np.ndarray:
    return pd.to_datetime(np.asarray(days), unit="D").year.to_numpy()


def block_of(days) -> np.ndarray:
    y = year_of(days)
    out = np.full(len(y), "", dtype=object)
    for name, (a, b) in BLOCKS.items():
        out[(y >= a) & (y <= b)] = name
    return out


def block_means(x: pd.Series, prefix: str) -> dict:
    m = x.groupby(block_of(x.index)).mean()
    return {f"{prefix}_{k}": m.get(k, np.nan) for k in BLOCKS}


def corr_p(x: np.ndarray, y: np.ndarray) -> tuple[float, float, int]:
    """Pearson correlation and its two-sided Student-t p-value (n - 2 df)."""
    ok = ~(np.isnan(x) | np.isnan(y))
    x, y = x[ok], y[ok]
    n = len(x)
    if n < 10 or x.std() == 0 or y.std() == 0:
        return np.nan, np.nan, n
    r = float(np.corrcoef(x, y)[0, 1])
    t = r * np.sqrt((n - 2) / max(1 - r * r, 1e-12))
    return r, t_pvalue(float(t), n - 2), n


def minute_returns(df: pd.DataFrame) -> np.ndarray:
    """Close-to-close return of each minute vs the previous UTC minute, same contract and trading day."""
    c = df["contract"].to_numpy()
    d = df["trading_day"].to_numpy()
    t = df["tmin"].to_numpy()
    ok = (c[1:] == c[:-1]) & (d[1:] == d[:-1]) & (t[1:] - t[:-1] == 1)
    r = np.full(len(df), np.nan)
    r[1:] = np.where(ok, np.diff(df["close"].to_numpy()), np.nan)
    return r


def filled_minutes(df: pd.DataFrame) -> pd.DataFrame:
    """Complete minute grid per (trading day, contract) run, from its first to its last bar: a minute with
    no bar traded nothing, so its close repeats the last one and its return is 0. Returns columns
    day, mod, r (r is NaN on the first minute of each run). For variance ratios: R007 asked for
    consecutive grids, and keeping only unbroken traded stretches selects fast markets in thin hours."""
    t = df["tmin"].to_numpy()
    c = df["close"].to_numpy()
    m = df["mod"].to_numpy()
    d = df["trading_day"].to_numpy()
    k = df["contract"].to_numpy()
    start = np.r_[0, np.flatnonzero((d[1:] != d[:-1]) | (k[1:] != k[:-1])) + 1]
    end = np.r_[start[1:], len(t)]
    out_d, out_m, out_r = [], [], []
    for a, b in zip(start, end):
        idx = t[a:b] - t[a]
        close = np.full(idx[-1] + 1, np.nan)
        close[idx] = c[a:b]
        close = pd.Series(close).ffill().to_numpy()
        r = np.r_[np.nan, np.diff(close)]
        out_d.append(np.full(len(close), d[a]))
        out_m.append((m[a] + np.arange(len(close))) % 1440)
        out_r.append(r)
    return pd.DataFrame({"day": np.concatenate(out_d), "mod": np.concatenate(out_m), "r": np.concatenate(out_r)})


def fingerprint(df: pd.DataFrame) -> dict:
    cols = ["tmin", "trading_day", "mod", "open", "high", "low", "close", "volume"]
    h = hashlib.sha256(df[cols].to_numpy().tobytes())
    h.update("|".join(map(str, df["contract"].to_numpy())).encode())
    return {"rows": len(df), "first": str(df["ts_event_utc"].iloc[0]), "last": str(df["ts_event_utc"].iloc[-1]),
            "sha256_all_columns": h.hexdigest()}


class Atlas:
    """Discovery frames and per-day segment returns; each table method registers its tests (keys in
    `key_*` columns) so q-values can be attached after one BH pass over the whole study."""

    def __init__(self, df: pd.DataFrame, df2: pd.DataFrame, eia_days: np.ndarray, shifted: pd.DataFrame):
        self.df, self.df2 = df, df2
        self.days = np.unique(df["trading_day"].to_numpy())
        self.eia_days = eia_days
        self.shifted = shifted  # holiday-week candidate slots: columns day, minute_et
        self.tests = []
        self._seg = {}
        self.r1 = minute_returns(df)
        self.mod = df["mod"].to_numpy()
        self.day = df["trading_day"].to_numpy()
        self.bin = ((self.mod - DAY) % 1440) // BIN
        self.eia_mask = pd.Index(self.days).isin(eia_days)

    def test(self, family: str, name: str, stat: float, p: float, n: int) -> str:
        key = f"{family}|{name}"
        self.tests.append({"key": key, "family": family, "test": name, "stat": stat, "p": p, "n": n})
        return key

    def _seg_of(self, frame, tag, start, end) -> pd.Series:
        key = (tag, start, end)
        if key not in self._seg:
            w = grid.windows(frame, [(start, end)], days=self.days)
            self._seg[key] = pd.Series(np.where(w["valid"], w["ret_ticks"], np.nan), index=self.days)
        return self._seg[key]

    def seg(self, start: int, end: int) -> pd.Series:
        """Per trading day return in ticks of the window (NaN where invalid)."""
        return self._seg_of(self.df, "1", start, end)

    def seg2(self, start: int, end: int) -> pd.Series:
        return self._seg_of(self.df2, "2", start, end)

    # 1 + 8: volatility, volume, range, liquidity by half-hour and weekday
    def by_half_hour(self) -> tuple[pd.DataFrame, pd.DataFrame]:
        df = self.df
        g = pd.DataFrame({"day": self.day, "bin": self.bin, "c": df["contract"].to_numpy(), "r2": self.r1 ** 2,
                          "vol": df["volume"].to_numpy(), "hi": df["high"].to_numpy(), "lo": df["low"].to_numpy(),
                          "thin": df["volume"].to_numpy() < THIN_LOTS})
        g = g[g["bin"] < len(BIN_STARTS)]
        per = g.groupby(["day", "bin"]).agg(n_contracts=("c", "nunique"), rv=("r2", "sum"), volume=("vol", "sum"),
                                             hi=("hi", "max"), lo=("lo", "min"), minutes=("vol", "size"),
                                             thin=("thin", "sum")).reset_index()
        per = per[per["n_contracts"] == 1]
        per["rv"] = np.sqrt(per["rv"])
        per["range"] = per["hi"] - per["lo"]
        per["coverage"] = per["minutes"] / BIN  # share of the 30 minutes with a bar (no bar = no trade)
        per["thin_observed"] = per["thin"] / per["minutes"]
        per["weekday"] = pd.to_datetime(per["day"], unit="D").dt.dayofweek
        q95 = lambda s: s.quantile(0.95)  # noqa: E731
        out = per.groupby("bin").agg(days=("day", "nunique"), rv_mean=("rv", "mean"), rv_median=("rv", "median"),
                                     rv_p95=("rv", q95), range_mean=("range", "mean"), range_p95=("range", q95),
                                     volume_mean=("volume", "mean"), volume_median=("volume", "median"),
                                     coverage=("coverage", "mean"),
                                     thin_share_observed=("thin_observed", "mean")).reset_index()
        out["volume_per_min"] = out["volume_mean"] / BIN
        out["missing_share"] = 1 - out["coverage"]
        out.insert(0, "start", [hm(BIN_STARTS[b]) for b in out["bin"]])
        wk = per.groupby("weekday").agg(rv_mean=("rv", "mean"), rv_median=("rv", "median"), rv_p95=("rv", q95),
                                        range_median=("range", "median"), range_p95=("range", q95),
                                        volume_mean=("volume", "mean"), volume_median=("volume", "median"),
                                        volume_p95=("volume", q95)).reset_index()
        return out, wk

    # 2: mean return by half-hour and session, sign stability by year, blocks
    def mean_returns(self) -> pd.DataFrame:
        rows = []
        specs = [(f"bin {hm(s)}", s, (s + BIN) % 1440) for s in BIN_STARTS] + \
                [(f"session {k}", a, b if b != 16 * 60 + 5 else F_) for k, (a, b) in SESSIONS.items()]
        for name, a, b in specs:
            x = self.seg(a, b)
            cm = clustered_mean(x.to_numpy(), x.index.to_numpy())
            yearly = x.groupby(year_of(x.index)).mean()
            rows.append({"window": name, "start": hm(a), "end": hm(b), "days": cm["n"], "mean_ticks": cm["mean"],
                         "t": cm["t"], "p": cm["p"], "sd_ticks": float(x.std()),
                         "years_same_sign": float((np.sign(yearly) == np.sign(cm["mean"])).mean()),
                         **block_means(x, "mean"), "key_mean": self.test("mean_return", name, cm["t"], cm["p"], cm["n"])})
        return pd.DataFrame(rows)

    # 3: variance ratios per session (filled minute grid, within-day runs, day bootstrap); 30-min autocorr
    def serial(self) -> tuple[pd.DataFrame, pd.DataFrame]:
        rows = []
        fm = filled_minutes(self.df)
        fmod, fday = fm["mod"].to_numpy(), fm["day"].to_numpy()
        blocks = block_of(fday)
        for k, (a, b) in SESSIONS.items():
            inside = (fmod >= a) & (fmod < b) if a < b else (fmod >= a) | (fmod < b)
            r = np.where(inside, fm["r"].to_numpy(), np.nan)
            for q in VR_Q:
                v = variance_ratio_days(r, fday, q, seed=q)
                by_block = {f"vr_{b}": variance_ratio_days(np.where(blocks == b, r, np.nan), fday, q, n_boot=2)["vr"]
                            for b in BLOCKS}
                rows.append({"session": k, "q_minutes": q, "vr": v["vr"], "se": v["se"], "z": v["z"], "p": v["p"],
                             "returns": v["n"], "q_sums": v["q_sums"], "days": v["days"], **by_block,
                             "key_vr": self.test("variance_ratio", f"{k} q={q}", v["z"], v["p"], v["days"])})
        vr = pd.DataFrame(rows)
        rows = []
        for s0, s1 in zip(BIN_STARTS[:-1], BIN_STARTS[1:]):
            x, y = self.seg(s0, s1), self.seg(s1, (s1 + BIN) % 1440)
            r, p, n = corr_p(x.to_numpy(), y.to_numpy())
            blk = {f"corr_{b}": corr_p(x[block_of(x.index) == b].to_numpy(), y[block_of(y.index) == b].to_numpy())[0]
                   for b in BLOCKS}
            rows.append({"from": hm(s0), "to": hm(s1), "autocorr": r, "p": p, "days": n, **blk,
                         "key_ac": self.test("autocorr_30m", f"{hm(s0)}->{hm(s1)}", r, p, n)})
        return vr, pd.DataFrame(rows)

    def predict(self, name: str, x: pd.Series, y: pd.Series, family: str = "segment") -> dict:
        """Predictor x and target y (per day, ticks): correlation, and the naive sign rule (direction =
        sign(x), traded over the target window): its IC (S001 definition) and gross edge per trade."""
        j = pd.concat([x.rename("x"), y.rename("y")], axis=1).dropna()
        j = j[j["x"] != 0]
        r, p, n = corr_p(j["x"].to_numpy(), j["y"].to_numpy())
        edge = np.sign(j["x"]) * j["y"]
        cm = clustered_mean(edge.to_numpy(), j.index.to_numpy())
        ic, _, _ = corr_p(np.sign(j["x"]).to_numpy(), j["y"].to_numpy())
        return {"pair": name, "days": n, "corr": r, "p_corr": p, "sign_ic": ic, "gross_sign_edge_ticks": cm["mean"],
                "sign_edge_t": cm["t"], "p_edge": cm["p"], **block_means(edge, "edge"),
                "key_corr": self.test(family, f"{name} corr", r, p, n),
                "key_edge": self.test(family, f"{name} sign edge", cm["t"], cm["p"], n)}

    # 4: segment-to-segment predictability (shift(-1) = the next trading day in the calendar)
    def segments(self) -> pd.DataFrame:
        S = self.seg
        eia = self.eia_mask
        ny = S(9 * 60, F_)
        rows = [
            self.predict("overnight 18:00-09:00 -> 09:00-16:05", S(18 * 60, 9 * 60), ny),
            self.predict("overnight 18:00-09:00 -> 09:00-10:00", S(18 * 60, 9 * 60), S(9 * 60, 10 * 60)),
            self.predict("first hour 09:00-10:00 -> 10:00-16:05", S(9 * 60, 10 * 60), S(10 * 60, F_)),
            self.predict("first half-hour 09:00-09:30 -> 14:00-14:30", S(9 * 60, 9 * 60 + 30), S(14 * 60, 14 * 60 + 30)),
            self.predict("09:00-14:00 -> 14:00-14:30", S(9 * 60, 14 * 60), S(14 * 60, 14 * 60 + 30)),
            self.predict("09:00-14:00 -> 14:00-16:05", S(9 * 60, 14 * 60), S(14 * 60, F_)),
            self.predict("settlement 14:25-14:35 -> 14:35-16:05", S(14 * 60 + 25, 14 * 60 + 35), S(14 * 60 + 35, F_)),
            self.predict("09:00-14:30 -> 20:00-03:00 next day", S(9 * 60, 14 * 60 + 30), S(20 * 60, 3 * 60).shift(-1)),
            self.predict("EIA days: pre-EIA 09:00-10:30 -> 10:30-11:00", S(9 * 60, EIA_MOD).where(eia),
                         S(EIA_MOD, 11 * 60).where(eia)),
            self.predict("EIA days: pre-EIA 09:00-10:30 -> 10:30-12:00", S(9 * 60, EIA_MOD).where(eia),
                         S(EIA_MOD, 12 * 60).where(eia)),
            self.predict("EIA days: 10:30-10:35 -> 10:35-11:30", S(EIA_MOD, EIA_MOD + 5).where(eia),
                         S(EIA_MOD + 5, 11 * 60 + 30).where(eia)),
            self.predict("non-EIA days: 10:30-10:35 -> 10:35-11:30", S(EIA_MOD, EIA_MOD + 5).where(~eia),
                         S(EIA_MOD + 5, 11 * 60 + 30).where(~eia)),
            self.predict("NY day t -> NY day t+1", ny, ny.shift(-1)),
            self.predict("NY day t -> overnight t+1", ny, S(18 * 60, 9 * 60).shift(-1)),
        ]
        return pd.DataFrame(rows)

    def _abs_mean(self, mask: np.ndarray) -> float:
        return float(np.nanmean(np.abs(self.r1[mask])))

    def _vol_mean(self, mask: np.ndarray) -> float:
        return float(np.nanmean(self.df["volume"].to_numpy()[mask]))

    # 5: event windows
    def events(self) -> pd.DataFrame:
        day_eia = np.isin(self.day, self.eia_days)
        weekday = pd.to_datetime(self.day, unit="D").dayofweek.to_numpy()
        holiday_week = np.isin(sunday_week(self.day), sunday_week(self.shifted["day"].to_numpy()))
        # R009: non-EIA Wednesdays exist only in holiday weeks (4 holidays); use the other weekdays of normal weeks
        control = np.isin(weekday, [0, 1, 3, 4]) & ~holiday_week
        rows = []
        for name, e, length, which in EVENTS:
            ev = (self.mod >= e) & (self.mod < e + length)
            base = (self.mod >= e - 30) & (self.mod < e - 15)
            on = day_eia if which == "eia" else np.ones(len(self.day), bool)
            row = {"event": name, "length_min": length,
                   "abs_ret_vs_local_pre": self._abs_mean(ev & on) / self._abs_mean(base & on),
                   "volume_vs_local_pre": self._vol_mean(ev & on) / self._vol_mean(base & on)}
            if which == "eia":
                row["abs_ret_vs_other_weekdays"] = self._abs_mean(ev & on) / self._abs_mean(ev & control)
                row["volume_vs_other_weekdays"] = self._vol_mean(ev & on) / self._vol_mean(ev & control)
                row["control_days"] = int(len(np.unique(self.day[control])))
            days_mask = pd.Index(self.days).isin(np.unique(self.day[on]))
            for h in (length, 30):
                x = self.seg(e, e + h).where(days_mask)
                cm = clustered_mean(x.to_numpy(), x.index.to_numpy())
                row.update({f"drift_{h}m_ticks": cm["mean"], f"drift_{h}m_t": cm["t"], f"sd_{h}m": float(x.std()),
                            **block_means(x, f"drift_{h}m"),
                            f"key_drift_{h}m": self.test("event_drift", f"{name} +{h}m", cm["t"], cm["p"], cm["n"])})
            first, rest = self.seg(e, e + length).where(days_mask), self.seg(e + length, e + 30).where(days_mask)
            r, p, n = corr_p(first.to_numpy(), rest.to_numpy())
            row.update({"first_to_rest30_corr": r, "days": n,
                        "key_cont": self.test("event_continuation", name, r, p, n)})
            rows.append(row)
        rows.append(self._shifted_eia())
        return pd.DataFrame(rows)

    def _shifted_eia(self) -> dict:
        """Holiday-week EIA stratum: every ex-ante candidate slot (diluted: only one of them is the release)."""
        ev_abs, base_abs, ev_vol, base_vol = [], [], [], []
        vol = self.df["volume"].to_numpy()
        for d, m in zip(self.shifted["day"], self.shifted["minute_et"]):
            on = self.day == d
            ev = on & (self.mod >= m) & (self.mod < m + 5)
            base = on & (self.mod >= m - 30) & (self.mod < m - 15)
            if ev.any() and base.any():
                ev_abs.append(np.nanmean(np.abs(self.r1[ev])))
                base_abs.append(np.nanmean(np.abs(self.r1[base])))
                ev_vol.append(vol[ev].mean())
                base_vol.append(vol[base].mean())
        return {"event": "EIA holiday weeks (all candidate slots)", "length_min": 5, "days": len(ev_abs),
                "abs_ret_vs_local_pre": np.nanmean(ev_abs) / np.nanmean(base_abs) if ev_abs else np.nan,
                "volume_vs_local_pre": np.mean(ev_vol) / np.mean(base_vol) if ev_vol else np.nan}

    def term_structure_0900(self) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        """CL2 - CL1 close (ticks) at the last minute before 09:00 where both traded (<= 10 min stale), with
        the front contract; NaN when not synchronised or when the second does not expire after the front."""
        t9 = grid.clock_tmin(self.days, 9 * 60)
        tm1, tm2 = self.df["tmin"].to_numpy(), self.df2["tmin"].to_numpy()
        common = np.intersect1d(tm1, tm2)
        if len(common) == 0:
            return np.full(len(t9), np.nan), np.full(len(t9), None), t9
        j = np.searchsorted(common, t9) - 1
        tc = np.where(j >= 0, common[np.maximum(j, 0)], -10**9)
        fresh = t9 - tc <= TERM_STALE_MIN
        i1 = np.searchsorted(tm1, tc)
        i2 = np.searchsorted(tm2, tc)
        i1c, i2c = np.minimum(i1, len(tm1) - 1), np.minimum(i2, len(tm2) - 1)
        k1 = self.df["contract"].to_numpy()[i1c]
        k2 = self.df2["contract"].to_numpy()[i2c]
        keys = list(pd.unique(np.concatenate([k1, k2])))
        exp = dict(zip(keys, E.contract_expiry(keys)))
        later = np.array([exp.get(b, -1) > exp.get(a, -1) >= 0 for a, b in zip(k1, k2)])
        ok = fresh & later
        slope = np.where(ok, self.df2["close"].to_numpy()[i2c] - self.df["close"].to_numpy()[i1c], np.nan)
        return slope, np.where(ok, k1, None), t9

    # 6: regimes (labels known before 09:00; tercile cut points use the whole period: exploratory only)
    def regimes(self) -> tuple[pd.DataFrame, dict]:
        slope, k1, t9 = self.term_structure_0900()
        ny = self.seg(9 * 60, F_)
        inside = (self.mod >= 9 * 60) & (self.mod < 16 * 60 + 5)
        rv = pd.Series(self.r1[inside] ** 2).groupby(self.day[inside]).sum() ** 0.5
        rv_prev = rv.reindex(self.days).shift(1).to_numpy()
        keys = [k for k in pd.unique(k1) if k is not None]
        exp = dict(zip(keys, E.contract_expiry(keys)))
        roll_at = grid.roll_schedule(self.df["tmin"].to_numpy(), self.df["contract"].to_numpy())
        dte = np.array([(exp[k] - t) / 1440 if k is not None and exp.get(k, -1) > 0 else np.nan for k, t in zip(k1, t9)])
        dtr = np.array([(roll_at[k] - t) / 1440 if k is not None and k in roll_at else np.nan for k, t in zip(k1, t9)])
        dte_lab = pd.cut(dte, [0, 5, 10, 15, 40], labels=["<=5", "6-10", "11-15", "16-40"]).astype(object)
        dte_lab = np.where(np.isnan(dte), None, np.where(dte <= 0, "<=0 (expired?)", np.where(dte > 40, ">40", dte_lab)))
        labels = {
            "term structure": np.where(np.isnan(slope), None, np.where(slope > 0, "contango", "backwardation")),
            "prior-day NY vol tercile": np.asarray(pd.qcut(rv_prev, 3, labels=["low", "mid", "high"]).astype(object)),
            "days to expiry": dte_lab,
            "roll week": roll_week_label(dtr),
            "month": pd.to_datetime(self.days, unit="D").month.to_numpy(),
        }
        counts = {"term_structure_missing": int(np.isnan(slope).sum()), "dte_le_0": int((dte_lab == "<=0 (expired?)").sum()),
                  "dte_gt_40": int((dte_lab == ">40").sum()),
                  "dte_missing": int(np.isnan(dte).sum()), "roll_missing": int(np.isnan(dtr).sum())}
        on, fh, rest = self.seg(18 * 60, 9 * 60), self.seg(9 * 60, 10 * 60), self.seg(10 * 60, F_)
        rows = []
        for reg, lab in labels.items():
            lab = pd.Series(lab, index=self.days)
            for v in pd.unique(lab.dropna()):
                m = lab == v
                x = ny.where(m)
                cm = clustered_mean(x.to_numpy(), x.index.to_numpy())
                a = self.predict(f"{reg}={v}: overnight -> NY", on.where(m), ny.where(m), "regime_predict")
                b = self.predict(f"{reg}={v}: first hour -> rest", fh.where(m), rest.where(m), "regime_predict")
                rows.append({"regime": reg, "value": v, "days": cm["n"], "ny_mean_ticks": cm["mean"], "ny_t": cm["t"],
                             "ny_sd_ticks": float(x.std()), **block_means(x, "ny_mean"),
                             "key_ny_mean": self.test("regime_mean", f"{reg}={v}", cm["t"], cm["p"], cm["n"]),
                             "overnight_ny_sign_ic": a["sign_ic"], "overnight_ny_edge": a["gross_sign_edge_ticks"],
                             **{f"overnight_ny_edge_{k}": a[f"edge_{k}"] for k in BLOCKS},
                             "key_overnight_ny_corr": a["key_corr"], "key_overnight_ny_edge": a["key_edge"],
                             "firsthour_rest_sign_ic": b["sign_ic"], "firsthour_rest_edge": b["gross_sign_edge_ticks"],
                             **{f"firsthour_rest_edge_{k}": b[f"edge_{k}"] for k in BLOCKS},
                             "key_firsthour_rest_corr": b["key_corr"], "key_firsthour_rest_edge": b["key_edge"]})
        return pd.DataFrame(rows), counts

    # 7: tails
    def tails(self) -> tuple[pd.DataFrame, pd.DataFrame]:
        series = {"1 min": pd.Series(self.r1).dropna(),
                  "30 min (bins)": pd.concat([self.seg(s, (s + BIN) % 1440) for s in BIN_STARTS]).dropna(),
                  "60 min (hour marks)": pd.concat([self.seg(h * 60, (h + 1) * 60 % 1440)
                                                    for h in list(range(18, 24)) + list(range(0, 16))]).dropna(),
                  "NY 09:00-16:05": self.seg(9 * 60, F_).dropna(),
                  "day 18:00-16:05": self.seg(18 * 60, F_).dropna()}
        qs = [0.001, 0.01, 0.05, 0.5, 0.95, 0.99, 0.999]
        rows = []
        for k, s in series.items():
            x = s.to_numpy(float)
            z = (x - x.mean()) / x.std()
            rows.append({"horizon": k, "n": len(x), "sd_ticks": x.std(), "excess_kurtosis": float((z ** 4).mean() - 3),
                         **{f"q{q}": float(np.quantile(x, q)) for q in qs}})
        ny = series["NY 09:00-16:05"]
        big = ny.reindex(ny.abs().sort_values(ascending=False).index[:10])
        top = pd.DataFrame({"date": pd.to_datetime(big.index, unit="D").date, "ny_ticks": big.to_numpy()})
        return pd.DataFrame(rows), top

    # 9: per-window feasibility (no signals): noise, excursions, entry liquidity, ticks needed for Sharpe 2
    def window_table(self) -> pd.DataFrame:
        df = self.df
        tm = df["tmin"].to_numpy()
        rng1 = (df["high"] - df["low"]).to_numpy()
        vol = df["volume"].to_numpy()
        rows = []
        for name, (a, b), eia_only in WINDOWS:
            w = grid.windows(df, [(a, b)], days=self.days)
            ok = w["valid"].to_numpy() & (self.eia_mask if eia_only else True)
            ws = w[ok]
            i0 = np.searchsorted(tm, ws["entry_tmin"].to_numpy())
            i1 = np.searchsorted(tm, ws["exit_tmin"].to_numpy())
            gap = tm[i0] - tm[np.maximum(i0 - 1, 0)]  # minutes since the previous traded bar
            adverse = np.concatenate([ws["mae_long"].to_numpy(), ws["mfe_long"].to_numpy()])  # long and short
            sd = float(ws["ret_ticks"].std())
            net_sr2 = 2 * sd / np.sqrt(252)  # every eligible day traded
            rows.append({"window": name, "eia_days_only": bool(eia_only), "days": int(ok.sum()), "sd_ticks": sd,
                         "mae_p50_ticks": float(np.median(adverse)), "mae_p95_ticks": float(np.quantile(adverse, 0.95)),
                         "entry_bar_range_p95": float(np.quantile(rng1[i0], 0.95)),
                         "exit_bar_range_p95": float(np.quantile(rng1[i1], 0.95)),
                         "entry_bar_volume_median": float(np.median(vol[i0])),
                         "entry_thin_share": float(((vol[i0] < THIN_LOTS) | (gap > 1)).mean()),
                         "net_ticks_for_sr2": net_sr2, "gross_ticks_for_sr2_base": net_sr2 + BASE_TICKS,
                         "gross_ticks_for_sr2_stress": net_sr2 + STRESS_TICKS})
        return pd.DataFrame(rows)

    def _window_volume(self, frame: pd.DataFrame):
        mod, day, vol = frame["mod"].to_numpy(), frame["trading_day"].to_numpy(), frame["volume"].to_numpy()

        def total(a: int, b: int) -> pd.Series:
            inside = (mod >= a) & (mod < b)
            return pd.Series(vol[inside]).groupby(day[inside]).sum().reindex(self.days)
        return total

    # 10: CL0 / CL1 lead-lag around 09:00, 14:00 and the EIA release
    def lead_lag(self) -> pd.DataFrame:
        vol0, vol1 = self._window_volume(self.df), self._window_volume(self.df2)
        rows = []
        for name, (p0, p1), t0, eia_only in LEAD_LAG:
            mask = self.eia_mask if eia_only else np.ones(len(self.days), bool)
            r0, r1 = self.seg(p0, p1).where(mask), self.seg2(p0, p1).where(mask)
            spread = r0 - r1
            share = (vol0(p0, p1) / (vol0(p0, p1) + vol1(p0, p1))).where(mask)
            c, _, n = corr_p(r0.to_numpy(), r1.to_numpy())
            row = {"anchor": name, "pre_window": f"{hm(p0)}-{hm(p1)}", "days": n, "cl0_cl1_corr": c,
                   "spread_sd_ticks": float(spread.std()), "spread_p05": float(spread.quantile(0.05)),
                   "spread_p95": float(spread.quantile(0.95)), "front_volume_share": float(share.mean())}
            for h in (25, 30, 55):
                pr = self.predict(f"{name}: CL0-CL1 spread {hm(p0)}-{hm(p1)} -> CL0 {hm(t0)}+{h}m", spread,
                                  self.seg(t0, t0 + h).where(mask), "lead_lag")
                row.update({f"spread_corr_{h}m": pr["corr"], f"spread_sign_ic_{h}m": pr["sign_ic"],
                            f"spread_edge_{h}m": pr["gross_sign_edge_ticks"],
                            **{f"spread_edge_{h}m_{b}": pr[f"edge_{b}"] for b in BLOCKS},
                            f"key_spread_corr_{h}m": pr["key_corr"], f"key_spread_edge_{h}m": pr["key_edge"]})
            rows.append(row)
        return pd.DataFrame(rows)

    # 11: event paths in 5-minute steps (continuation of the first 5 minutes) and the next day's window
    def event_paths(self) -> pd.DataFrame:
        rows = []
        for name, e, eia_only in (("EIA 10:30", EIA_MOD, True), ("settlement 14:25", 14 * 60 + 25, False)):
            mask = self.eia_mask if eia_only else np.ones(len(self.days), bool)
            first = self.seg(e, e + 5).where(mask)
            steps = [(f"{hm(e + 5)}-{hm(e + k)}", first, self.seg(e + 5, e + k).where(mask), self.seg(e, e + k).where(mask))
                     for k in range(10, 65, 5) if e + k <= 16 * 60 + 5]
            steps.append(("next day same 30m", self.seg(e, e + 30).where(mask), self.seg(e, e + 30).shift(-1), None))
            for label, x, y, cum in steps:
                pr = self.predict(f"{name}: {label}", x, y, "event_path")
                edge = pr["gross_sign_edge_ticks"]
                rows.append({"event": name, "target": label, "cum_sd_ticks": float(cum.std()) if cum is not None else np.nan,
                             "days": pr["days"], "corr": pr["corr"], "sign_ic": pr["sign_ic"], "gross_sign_edge": edge,
                             **{f"edge_{b}": pr[f"edge_{b}"] for b in BLOCKS},
                             "abs_edge_beats_base_cost": abs(edge) > BASE_TICKS,
                             "abs_edge_beats_stress_cost": abs(edge) > STRESS_TICKS,
                             "key_corr": pr["key_corr"], "key_edge": pr["key_edge"]})
        return pd.DataFrame(rows)


def sunday_week(days) -> np.ndarray:
    """Week number of epoch days, weeks starting on Sunday (epoch day 0 is a Thursday)."""
    return (np.asarray(days, np.int64) + 4) // 7


def roll_week_label(days_to_roll: np.ndarray) -> np.ndarray:
    """"yes" within ROLL_WEEK_DAYS before the scheduled roll, "no" otherwise, None when unknown."""
    d = np.asarray(days_to_roll, float)
    return np.where(np.isnan(d), None, np.where((d >= 0) & (d < ROLL_WEEK_DAYS), "yes", "no"))


def eia_calendar_split(days: np.ndarray) -> tuple[np.ndarray, pd.DataFrame]:
    """(normal-week Wednesday 10:30 release days, holiday-week candidate slots [day, minute_et])."""
    rel = eia_calendar.load_releases()
    d = ((rel["date"] - pd.Timestamp("1970-01-01")) // pd.Timedelta(days=1)).to_numpy()
    rel = rel.assign(day=d, week=sunday_week(d))
    single = rel.groupby("week")["day"].transform("size") == 1
    normal = rel[single & (rel["minute_et"] == EIA_MOD)]
    shifted = rel[~single & rel["day"].isin(days)][["day", "minute_et"]].reset_index(drop=True)
    return np.intersect1d(normal["day"].to_numpy(), days), shifted


def attach_q(table: pd.DataFrame, q: dict) -> pd.DataFrame:
    """Replace every key_* column by its q-value (q_*)."""
    out = table.copy()
    for c in [c for c in out.columns if c.startswith("key_")]:
        out["q_" + c[4:]] = out[c].map(q)
        out = out.drop(columns=c)
    return out


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--quick", action="store_true", help="2015-16 only, no report CSVs (smoke test)")
    a = ap.parse_args(argv)
    t0 = time.time()
    tag = "quick" if a.quick else "full"
    df = data.load_front("discovery", ITEM, f"S002 atlas ({tag}): front month")
    df2 = data.load_second("discovery", ITEM, f"S002 atlas ({tag}): second month for the term structure")
    if a.quick:
        cut = int((pd.Timestamp("2015-01-01") - pd.Timestamp("1970-01-01")).days)
        df = df[df["trading_day"] >= cut].reset_index(drop=True)
        df2 = df2[df2["trading_day"] >= cut].reset_index(drop=True)
    eia_days, shifted = eia_calendar_split(np.unique(df["trading_day"]))
    at = Atlas(df, df2, eia_days, shifted)
    tables = {}
    tables["half_hour"], tables["weekday"] = at.by_half_hour()
    tables["mean_returns"] = at.mean_returns()
    tables["variance_ratio"], tables["autocorr_30m"] = at.serial()
    tables["segments"] = at.segments()
    tables["events"] = at.events()
    tables["regimes"], regime_counts = at.regimes()
    tables["tails"], tables["biggest_days"] = at.tails()
    tables["windows"] = at.window_table()
    tables["lead_lag"] = at.lead_lag()
    tables["event_paths"] = at.event_paths()
    tests = pd.DataFrame(at.tests)
    if not tests["key"].is_unique:
        raise RuntimeError("duplicate test keys would overwrite q-values")
    tests["q"] = bh_qvalues(tests["p"].to_numpy())
    q = dict(zip(tests["key"], tests["q"]))
    shown = {v for t in tables.values() for c in t.columns if c.startswith("key_") for v in t[c].dropna()}
    hidden = set(q) - shown
    if hidden:
        raise RuntimeError(f"{len(hidden)} registered tests have no table column, e.g. {sorted(hidden)[:3]}")
    tables = {k: attach_q(t, q) for k, t in tables.items()}
    tables["tests"] = tests
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out = paths.OUT_DIR / "s002" / f"{stamp}_{tag}"
    out.mkdir(parents=True, exist_ok=True)
    for k, t in tables.items():
        t.to_csv(out / f"{k}.csv", index=False)
        if not a.quick:
            t.to_csv(REPORT_DIR / f"{k}.csv", index=False, float_format="%.5g")
    n_q = int((tests["q"] < Q_DECISION).sum())
    manifest = {"item": ITEM, "stamp": stamp, "tag": tag, "code_sha256": code_hash(), "data": fingerprint(df),
                "data_second": fingerprint(df2), "eia_csv_sha256": ledger.sha256_file(eia_calendar.OUT_FILE),
                "eia_days": int(len(eia_days)), "shifted_candidates": int(len(shifted)), "days": int(len(at.days)),
                "regime_counts": regime_counts, "tests": int(len(tests)), "q_lt_0.10": n_q,
                "seconds": round(time.time() - t0)}
    (out / "manifest.json").write_text(json.dumps(manifest, indent=1, default=str))
    data_sha = hashlib.sha256((manifest["data"]["sha256_all_columns"] + manifest["data_second"]["sha256_all_columns"]
                               + manifest["eia_csv_sha256"]).encode()).hexdigest()
    ledger.append(ITEM, "descriptive", "discovery", n_tests=len(tests), statistic="S002 market atlas (BH over all tests)",
                  value=n_q, verdict="DESCRIPTIVE", code_sha256=manifest["code_sha256"], data_sha256=data_sha,
                  output=str(out.relative_to(paths.ROOT)),
                  note=f"{tag}: {len(at.days)} days, {len(eia_days)} EIA rule days; value = tests with q < {Q_DECISION}")
    with pd.option_context("display.width", 250, "display.max_columns", 30, "display.max_rows", 80):
        print(tests.sort_values("p").head(30).round(4).drop(columns="key").to_string(index=False))
    print(f"S002 {tag}: {len(tests)} tests, {n_q} with q < {Q_DECISION}, {time.time() - t0:.0f} s; outputs {out}")


if __name__ == "__main__":
    main()
