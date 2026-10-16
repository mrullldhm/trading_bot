#!/usr/bin/env python3
"""Independent S002 headline replication from the raw one-minute parquet files."""

from __future__ import annotations

import json
from pathlib import Path
import sys

import numpy as np
import pandas as pd

# Make the repository package importable when this file is run by path.
ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

# Permitted calendar helper. No propfirm_research code is imported.
from propfirm_backtest.orb_engine import short_days


RAW = ROOT / "data/processed/ohlcv-1m"
EIA_FILE = ROOT / "data/reference/eia_releases.csv"
OUT = ROOT / "data/research/replications/S002/results.json"
ET = "America/New_York"
START = pd.Timestamp("2010-06-07")
END = pd.Timestamp("2016-12-31")
NS_MIN = 60_000_000_000
BLOCKS = {
    "2010-12": (pd.Timestamp("2010-01-01"), pd.Timestamp("2012-12-31")),
    "2013-14": (pd.Timestamp("2013-01-01"), pd.Timestamp("2014-12-31")),
    "2015-16": (pd.Timestamp("2015-01-01"), pd.Timestamp("2016-12-31")),
}


def native(value):
    """Convert numpy/pandas scalars recursively for strict JSON output."""
    if isinstance(value, dict):
        return {str(k): native(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [native(v) for v in value]
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        return None if not np.isfinite(value) else float(value)
    if isinstance(value, float):
        return None if not np.isfinite(value) else value
    if isinstance(value, pd.Timestamp):
        return str(value)
    return value


def mean_t(values: np.ndarray) -> dict:
    z = np.asarray(values, dtype=float)
    z = z[np.isfinite(z)]
    n = len(z)
    mean = float(z.mean()) if n else np.nan
    t = mean / (float(z.std(ddof=1)) / np.sqrt(n)) if n > 1 and z.std(ddof=1) > 0 else np.nan
    return {"n": n, "mean_ticks": mean, "t": t}


def corr(a: np.ndarray, b: np.ndarray) -> float:
    a, b = np.asarray(a, float), np.asarray(b, float)
    return float(np.corrcoef(a, b)[0, 1]) if len(a) > 1 and a.std() > 0 and b.std() > 0 else np.nan


def block_means(frame: pd.DataFrame, column: str) -> dict:
    return {
        name: mean_t(frame.loc[frame.td.between(lo, hi), column].to_numpy())
        for name, (lo, hi) in BLOCKS.items()
    }


def load_raw() -> pd.DataFrame:
    cols = ["ts_event_utc", "continuous_symbol", "raw_symbol", "expiration",
            "open_ticks", "close_ticks", "volume"]
    frames = [pd.read_parquet(RAW / f"year={year}/cl.parquet", columns=cols)
              for year in range(2010, 2017)]
    d = pd.concat(frames, ignore_index=True)
    d["ts"] = pd.to_datetime(d.pop("ts_event_utc"), utc=True)
    d["expiration"] = pd.to_datetime(d["expiration"], utc=True)
    # A one-digit raw symbol is not unique across decades; expiration month makes it unique.
    d["contract"] = d.raw_symbol + "@" + d.expiration.dt.strftime("%Y-%m")
    et = d.ts.dt.tz_convert(ET)
    d["et_date"] = et.dt.tz_localize(None).dt.normalize()
    d["mod"] = et.dt.hour * 60 + et.dt.minute
    d["td"] = d.et_date + pd.to_timedelta(d["mod"].ge(18 * 60).astype(int), unit="D")
    d = d[d.td.between(START, END)].copy()
    return d.sort_values(["ts", "continuous_symbol"]).reset_index(drop=True)


def schedules(raw: pd.DataFrame):
    front = raw[raw.continuous_symbol.eq("CL.v.0")]
    first = front.groupby("contract").ts.min().sort_values()
    # The scheduled roll for a contract is the next contract's first front minute, floored to hour.
    roll = first.shift(-1).dt.floor("h").to_dict()
    expiry = raw.groupby("contract").expiration.first().to_dict()
    return roll, expiry


def add_short_flag(days: pd.DatetimeIndex) -> dict[pd.Timestamp, bool]:
    day_int = ((days - pd.Timestamp("1970-01-01")) // pd.Timedelta(days=1)).to_numpy(np.int64)
    return dict(zip(days, short_days(day_int)))


def local_stamp(day: pd.Timestamp, minute: int, prior_for_evening: bool = False) -> pd.Timestamp:
    date = day - pd.Timedelta(days=1) if prior_for_evening else day
    naive = date + pd.Timedelta(minutes=minute)
    return naive.tz_localize(ET).tz_convert("UTC")


class Windows:
    def __init__(self, front: pd.DataFrame, roll: dict, expiry: dict):
        self.groups = {day: g.sort_values("ts").reset_index(drop=True)
                       for day, g in front.groupby("td", sort=True)}
        self.days = pd.DatetimeIndex(sorted(self.groups))
        self.short = add_short_flag(self.days)
        self.roll, self.expiry = roll, expiry

    def flat(self, day: pd.Timestamp, contract: str) -> pd.Timestamp:
        minute = 12 * 60 + 55 if self.short.get(day, False) else 16 * 60 + 5
        values = [local_stamp(day, minute)]
        exp = self.expiry.get(contract)
        if exp is not None and pd.notna(exp):
            values.append(exp - pd.Timedelta(minutes=5))
        roll = self.roll.get(contract)
        if roll is not None and pd.notna(roll):
            values.append(roll - pd.Timedelta(minutes=5))
        return min(values)

    def one(self, day: pd.Timestamp, a: int, b: int, a_evening=False) -> float:
        g = self.groups.get(day)
        if g is None or g.empty:
            return np.nan
        ta = local_stamp(day, a, a_evening)
        tb = local_stamp(day, b)
        ts_ns = g.ts.astype("int64").to_numpy()
        ia = int(np.searchsorted(ts_ns, ta.value))
        ib = int(np.searchsorted(ts_ns, tb.value))
        if ia >= len(g) or ib >= len(g):
            return np.nan
        late_a = (g.ts.iloc[ia] - ta) / pd.Timedelta(minutes=1)
        late_b = (g.ts.iloc[ib] - tb) / pd.Timedelta(minutes=1)
        if not (0 <= late_a <= 5 and 0 <= late_b <= 5):
            return np.nan
        ca, cb = g.contract.iloc[ia], g.contract.iloc[ib]
        if ca != cb or g.contract.iloc[ia:ib + 1].nunique() != 1:
            return np.nan
        if g.ts.iloc[ib] > self.flat(day, ca):
            return np.nan
        return float(g.open_ticks.iloc[ib] - g.open_ticks.iloc[ia])

    def frame(self, specs: dict[str, tuple[int, int, bool]]) -> pd.DataFrame:
        rows = []
        for day in self.days:
            row = {"td": day}
            for name, (a, b, eve) in specs.items():
                row[name] = self.one(day, a, b, eve)
            rows.append(row)
        return pd.DataFrame(rows)


def item_1_2(windows: Windows):
    f = windows.frame({
        "r1430_1500": (14 * 60 + 30, 15 * 60, False),
        "x": (14 * 60 + 25, 14 * 60 + 35, False),
        "y": (14 * 60 + 35, 16 * 60 + 5, False),
    })
    one = mean_t(f.r1430_1500.to_numpy())
    one["blocks"] = block_means(f, "r1430_1500")
    p = f.dropna(subset=["x", "y"]).query("x != 0").copy()
    p["signed_y"] = np.sign(p.x) * p.y
    two = {
        "n": len(p),
        "pearson_corr_x_y": corr(p.x, p.y),
        "sign_ic": corr(np.sign(p.x), p.y),
        "gross_sign_edge": mean_t(p.signed_y.to_numpy()),
        "blocks": block_means(p, "signed_y"),
    }
    return f, one, two


def eia_calendar() -> tuple[set[pd.Timestamp], set[pd.Timestamp], set[pd.Timestamp]]:
    e = pd.read_csv(EIA_FILE)
    e["date"] = pd.to_datetime(e.date)
    e["week"] = e.date - pd.to_timedelta(e.date.dt.weekday, unit="D")
    rule, normal, holiday = set(), set(), set()
    for week, g in e.groupby("week"):
        week = pd.Timestamp(week)
        if len(g) == 1:
            normal.add(week)
            if g.date.iloc[0].weekday() == 2 and g.time_et.iloc[0] == "10:30":
                rule.add(week)
        else:
            holiday.add(week)
    rule_days = {w + pd.Timedelta(days=2) for w in rule
                 if START <= w + pd.Timedelta(days=2) <= END}
    normal = {w for w in normal if w <= END and w + pd.Timedelta(days=6) >= START}
    holiday = {w for w in holiday if w <= END and w + pd.Timedelta(days=6) >= START}
    return rule_days, normal, holiday


def item_3(front: pd.DataFrame):
    d = front.sort_values("ts").copy()
    d["prev_ts"] = d.ts.shift()
    d["prev_contract"] = d.contract.shift()
    d["prev_td"] = d.td.shift()
    d["abs_cc"] = (d.close_ticks - d.close_ticks.shift()).abs()
    consecutive = ((d.ts.astype("int64") - d.prev_ts.astype("int64")) == NS_MIN)
    valid = consecutive & d.contract.eq(d.prev_contract) & d.td.eq(d.prev_td)
    d.loc[~valid, "abs_cc"] = np.nan
    rule, normal_weeks, holiday_weeks = eia_calendar()
    d["week"] = d.et_date - pd.to_timedelta(d.et_date.dt.weekday, unit="D")
    d["is_rule"] = d.et_date.isin(rule)
    d["is_control"] = d.et_date.dt.weekday.isin([0, 1, 3, 4]) & d.week.isin(normal_weeks)

    def pooled(mask, column):
        z = d.loc[mask, column].dropna()
        return float(z.mean()) if len(z) else np.nan, int(len(z))

    event = d["mod"].between(10 * 60 + 30, 10 * 60 + 34)
    base = d["mod"].between(10 * 60, 10 * 60 + 14)
    out = {"rule_days_calendar_n": len(rule),
           "normal_weeks_calendar_n": len(normal_weeks),
           "holiday_weeks_calendar_n": len(holiday_weeks),
           "control_trading_days_n": int(d.loc[d.is_control, "et_date"].nunique())}
    for col, label in [("abs_cc", "absolute_close_return"), ("volume", "volume")]:
        ev, nev = pooled(d.is_rule & event, col)
        ba, nba = pooled(d.is_rule & base, col)
        co, nco = pooled(d.is_control & event, col)
        out[label] = {
            "event_mean": ev, "event_minute_n": nev,
            "same_day_1000_1014_mean": ba, "same_day_minute_n": nba,
            "ratio_to_same_day": ev / ba if np.isfinite(ba) and ba != 0 else np.nan,
            "normal_week_control_mean": co, "normal_week_control_minute_n": nco,
            "ratio_to_normal_week_controls": ev / co if np.isfinite(co) and co != 0 else np.nan,
        }
    return out


def variance_from_moments(n, total, squares):
    return (squares - total * total / n) / (n - 1) if n > 1 else np.nan


def item_4(front: pd.DataFrame, bootstrap=2000, seed=20261017):
    ny = front[front["mod"].between(8 * 60, 16 * 60 + 4)].copy()
    per_day = []
    for day, gd in ny.groupby("td", sort=True):
        rn, rs, rss = 0, 0.0, 0.0
        qn, qs, qss = 0, 0.0, 0.0
        for _, g in gd.groupby("contract", sort=False):
            g = g.sort_values("ts").drop_duplicates("ts", keep="last")
            if len(g) < 2:
                continue
            grid = pd.date_range(g.ts.iloc[0], g.ts.iloc[-1], freq="1min")
            close = g.set_index("ts").close_ticks.reindex(grid).ffill().to_numpy(float)
            r = np.diff(close)
            if len(r):
                rn += len(r); rs += r.sum(); rss += r @ r
            if len(r) >= 30:
                sums = np.convolve(r, np.ones(30), mode="valid")
                qn += len(sums); qs += sums.sum(); qss += sums @ sums
        if rn and qn:
            per_day.append((day, rn, rs, rss, qn, qs, qss))
    m = np.asarray([x[1:] for x in per_day], float)

    def vr(rows):
        x = rows.sum(axis=0)
        v1 = variance_from_moments(x[0], x[1], x[2])
        vq = variance_from_moments(x[3], x[4], x[5])
        return vq / (30 * v1)

    estimate = vr(m)
    rng = np.random.default_rng(seed)
    boot = np.empty(bootstrap)
    nday = len(m)
    for i in range(bootstrap):
        boot[i] = vr(m[rng.integers(0, nday, nday)])
    return {"q": 30, "trading_days_n": nday, "one_minute_returns_n": int(m[:, 0].sum()),
            "overlapping_sums_n": int(m[:, 3].sum()), "vr": estimate,
            "trading_day_bootstrap_se": float(boot.std(ddof=1)),
            "bootstrap_reps": bootstrap, "bootstrap_seed": seed}


def regimes_at_0900(raw: pd.DataFrame, all_days: pd.DatetimeIndex) -> pd.DataFrame:
    z = raw[raw["mod"].between(8 * 60 + 50, 8 * 60 + 59)].copy()
    f = z[z.continuous_symbol.eq("CL.v.0")][["td", "ts", "close_ticks", "expiration"]]
    s = z[z.continuous_symbol.eq("CL.v.1")][["td", "ts", "close_ticks", "expiration"]]
    both = f.merge(s, on=["td", "ts"], suffixes=("_front", "_second"))
    both = both[both.expiration_second > both.expiration_front]
    both = both.sort_values("ts").groupby("td", as_index=False).tail(1)
    both["slope"] = both.close_ticks_second - both.close_ticks_front
    both["regime"] = np.where(both.slope > 0, "contango", "backwardation")
    out = pd.DataFrame({"td": all_days}).merge(both[["td", "regime", "slope"]], on="td", how="left")
    out["regime"] = out.regime.fillna("unsynchronised")
    return out


def item_5(raw: pd.DataFrame, windows: Windows):
    r = regimes_at_0900(raw, windows.days)
    paths = windows.frame({
        "overnight": (18 * 60, 9 * 60, True),
        "day": (9 * 60, 16 * 60 + 5, False),
    })
    r = r.merge(paths, on="td", how="left")
    counts = r.regime.value_counts().reindex(["contango", "backwardation", "unsynchronised"], fill_value=0)
    out = {"counts": counts.to_dict(), "metrics": {}}
    for regime in ("contango", "backwardation"):
        # Unlike item 2, item 5 does not instruct us to remove x=0; retain it as sign(0)=0.
        x = r[(r.regime == regime) & r.overnight.notna() & r.day.notna()].copy()
        x["edge"] = np.sign(x.overnight) * x.day
        nz = x[x.overnight.ne(0)].copy()
        nz["edge"] = np.sign(nz.overnight) * nz.day
        out["metrics"][regime] = {
            "n": len(x), "zero_predictor_n": int(x.overnight.eq(0).sum()),
            "sign_ic": corr(np.sign(x.overnight), x.day),
            "gross_sign_edge": mean_t(x.edge.to_numpy()),
            "nonzero_only_sensitivity": {
                "n": len(nz), "sign_ic": corr(np.sign(nz.overnight), nz.day),
                "gross_sign_edge": mean_t(nz.edge.to_numpy()),
            },
        }
    return out


def main():
    raw = load_raw()
    roll, expiry = schedules(raw)
    front = raw[raw.continuous_symbol.eq("CL.v.0")].sort_values("ts").copy()
    assert not front.empty and front.td.min() >= START and front.td.max() <= END
    assert not front.ts.duplicated().any(), "front series must have one bar per UTC minute"
    windows = Windows(front, roll, expiry)
    _, one, two = item_1_2(windows)
    result = {
        "period": {"first_trading_day": front.td.min(), "last_trading_day": front.td.max(),
                   "trading_days_n": front.td.nunique(), "front_rows_n": len(front)},
        "1_1430_1500": one,
        "2_predictability": two,
        "3_eia": item_3(front),
        "4_vr30": item_4(front),
        "5_term_structure": item_5(raw, windows),
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(native(result), indent=2, allow_nan=False) + "\n")
    print(json.dumps(native(result), indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
