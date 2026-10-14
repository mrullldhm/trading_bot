"""Cross-check the last 2 years of Databento CL bars against Massive (free Futures Basic tier).

Usage:
    python -m propfirm_data.crosscheck

Two independent vendors built from the same CME trades should agree almost exactly.
If they do, we can trust the Databento data for backtesting.

Free tier limits: 5 calls/minute, 2 years of history, ~8 hours delay. The script waits
13 s between calls and caches every contract, so a re-run makes zero API calls.
"""

import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from datetime import datetime, timedelta, timezone

import pandas as pd
from dotenv import dotenv_values

from .config import DATA_DIR, ROOT
from .convert import load_bars
from .validate import CHICAGO, roll_points, trading_day

AGGS_URL = "https://api.massive.com/futures/v1/aggs/{ticker}"
CALL_INTERVAL_SECONDS = 13.0  # 5 calls/minute on the free tier, plus a little slack
HISTORY_DAYS = 729  # free tier = 2 years; stay one day inside it
DELAY_HOURS = 8  # free tier data is ~8 hours behind
OUT_DIR = DATA_DIR / "crosscheck"
CACHE_DIR = OUT_DIR / "massive"
PRICE_FIELDS = ["open", "high", "low", "close"]
PASS_EXACT_PCT = 99.0
PASS_COVERAGE_PCT = 99.0


# --- Massive API ---------------------------------------------------------------------------

class MassiveClient:
    """Tiny HTTP client: Bearer auth (key never in URLs or logs), rate limit, retries."""

    def __init__(self, api_key: str, interval: float = CALL_INTERVAL_SECONDS):
        self._key = api_key
        self._interval = interval
        self._last_call = 0.0
        self.calls = 0

    def get(self, url: str) -> dict:
        for attempt in range(1, 8):
            wait = self._interval - (time.monotonic() - self._last_call)
            if wait > 0:
                time.sleep(wait)
            self._last_call = time.monotonic()
            self.calls += 1
            req = urllib.request.Request(url, headers={"Authorization": f"Bearer {self._key}"})
            try:
                with urllib.request.urlopen(req, timeout=60) as resp:
                    return json.loads(resp.read())
            except urllib.error.HTTPError as exc:
                if exc.code == 429:
                    print("  rate limited, waiting 60s")
                    time.sleep(60)
                elif exc.code >= 500:
                    print(f"  server error {exc.code}, retrying")
                else:
                    raise RuntimeError(f"Massive returned HTTP {exc.code}: {exc.read()[:300]!r}") from None
            except (urllib.error.URLError, TimeoutError, ConnectionError, json.JSONDecodeError) as exc:
                print(f"  network error ({exc.__class__.__name__}), attempt {attempt}, retrying")
        raise RuntimeError(f"giving up on {url.split('?')[0]}")


def first_page_url(ticker: str, start: pd.Timestamp, end: pd.Timestamp) -> str:
    params = {
        "resolution": "1min",
        "window_start.gte": start.value,  # nanoseconds
        "window_start.lt": end.value,  # exclusive: no overlap between ranges
        "limit": 50000,
        "sort": "window_start.asc",
    }
    return AGGS_URL.format(ticker=ticker) + "?" + urllib.parse.urlencode(params)


def fetch_all(get: Callable[[str], dict], ticker: str, start: pd.Timestamp, end: pd.Timestamp) -> list[dict]:
    """Fetch every page by following next_url until it disappears."""
    results, url = [], first_page_url(ticker, start, end)
    while url:
        page = get(url)
        results += page.get("results") or []
        url = page.get("next_url")
    return results


def massive_to_frame(results: list[dict]) -> pd.DataFrame:
    if not results:
        return pd.DataFrame(columns=["raw_symbol", "ts_event_utc", "volume"] + [f"{f}_ticks" for f in PRICE_FIELDS])
    df = pd.DataFrame(results)
    out = pd.DataFrame({
        "raw_symbol": df["ticker"].astype(str),
        "ts_event_utc": pd.to_datetime(df["window_start"].astype("int64"), unit="ns", utc=True),
        "volume": df["volume"].astype("int64"),
    })
    for f in PRICE_FIELDS:
        out[f"{f}_ticks"] = (df[f].astype(float) * 100).round().astype("int64")  # 1 tick = $0.01
    return out.drop_duplicates(["raw_symbol", "ts_event_utc"])


def fetch_contract(client: MassiveClient, ticker: str, start: pd.Timestamp, end: pd.Timestamp) -> pd.DataFrame:
    cache = CACHE_DIR / f"{ticker}_{start.value}_{end.value}.parquet"
    if cache.exists():
        return pd.read_parquet(cache)
    df = massive_to_frame(fetch_all(client.get, ticker, start, end))
    cache.parent.mkdir(parents=True, exist_ok=True)
    tmp = cache.with_suffix(".partial")
    df.to_parquet(tmp, index=False)
    tmp.replace(cache)
    return df


# --- Databento side --------------------------------------------------------------------------

def databento_window(bars: pd.DataFrame, now: pd.Timestamp) -> pd.DataFrame:
    """Last 2 years minus the free-tier delay; one row per (contract, minute), v.0 preferred."""
    start = (now - timedelta(days=HISTORY_DAYS)).normalize()
    end = now - timedelta(hours=DELAY_HOURS)
    df = bars[(bars["ts_event_utc"] >= start) & (bars["ts_event_utc"] < end)]
    df = df.sort_values(["raw_symbol", "ts_event_utc", "continuous_symbol"])  # CL.v.0 sorts before CL.v.1
    return df.drop_duplicates(["raw_symbol", "ts_event_utc"], keep="first").reset_index(drop=True)


# --- comparison --------------------------------------------------------------------------------

def compare(db: pd.DataFrame, ms: pd.DataFrame) -> pd.DataFrame:
    """Outer-join both vendors on (contract, minute) and add difference columns."""
    keep = ["raw_symbol", "ts_event_utc", "volume"] + [f"{f}_ticks" for f in PRICE_FIELDS]
    db_cols = keep + (["continuous_symbol"] if "continuous_symbol" in db.columns else [])
    m = db[db_cols].merge(ms[keep], on=["raw_symbol", "ts_event_utc"], how="outer",
                          suffixes=("_db", "_ms"), indicator=True)
    m["side"] = m["_merge"].map({"both": "both", "left_only": "databento_only", "right_only": "massive_only"})
    m = m.drop(columns="_merge")
    for f in PRICE_FIELDS:
        m[f"{f}_diff"] = (m[f"{f}_ticks_ms"] - m[f"{f}_ticks_db"]).abs()
    m["max_diff"] = m[[f"{f}_diff" for f in PRICE_FIELDS]].max(axis=1)
    return m


def summarize(m: pd.DataFrame) -> dict:
    both = m[m["side"] == "both"]
    n_db = int((m["side"] != "massive_only").sum())
    pct = lambda x, n: round(100.0 * x / n, 3) if n else float("nan")  # noqa: E731
    out = {
        "databento_bars": n_db,
        "massive_bars": int((m["side"] != "databento_only").sum()),
        "matched": len(both),
        "databento_only": int((m["side"] == "databento_only").sum()),
        "massive_only": int((m["side"] == "massive_only").sum()),
        "coverage_pct": pct(len(both), n_db),
        "ohlc_exact_pct": pct((both["max_diff"] == 0).sum(), len(both)),
        "ohlc_within_1_tick_pct": pct((both["max_diff"] <= 1).sum(), len(both)),
        "max_diff_ticks": int(both["max_diff"].max()) if len(both) else 0,
        "p99_diff_ticks": float(both["max_diff"].quantile(0.99)) if len(both) else 0.0,
        "volume_exact_pct": pct((both["volume_db"] == both["volume_ms"]).sum(), len(both)),
    }
    for f in PRICE_FIELDS:
        out[f"{f}_exact_pct"] = pct((both[f"{f}_diff"] == 0).sum(), len(both))
    nonzero = both[(both["volume_db"] > 0) & (both["volume_ms"] > 0)]
    out["volume_median_ratio"] = float((nonzero["volume_ms"] / nonzero["volume_db"]).median()) if len(nonzero) else float("nan")
    return out


def add_labels(m: pd.DataFrame, roll_days: set) -> pd.DataFrame:
    m = m.copy()
    m["day"] = trading_day(m)
    m["is_roll_day"] = m["day"].isin(roll_days)
    m["is_wednesday"] = m["ts_event_utc"].dt.tz_convert(CHICAGO).dt.dayofweek == 2  # EIA report day
    m["chicago_hour"] = m["ts_event_utc"].dt.tz_convert(CHICAGO).dt.hour
    return m


def daily_agreement(m: pd.DataFrame) -> dict:
    """Do daily high / low / volume per contract agree when built from each vendor's bars?"""
    agg = {"high_ticks_db": "max", "high_ticks_ms": "max", "low_ticks_db": "min", "low_ticks_ms": "min",
           "volume_db": "sum", "volume_ms": "sum"}
    d = m.groupby(["raw_symbol", "day"]).agg(agg)
    n = len(d)
    return {
        "days": n,
        "daily_high_exact_pct": round(100 * (d["high_ticks_db"] == d["high_ticks_ms"]).mean(), 3) if n else float("nan"),
        "daily_low_exact_pct": round(100 * (d["low_ticks_db"] == d["low_ticks_ms"]).mean(), 3) if n else float("nan"),
        "daily_volume_exact_pct": round(100 * (d["volume_db"] == d["volume_ms"]).mean(), 3) if n else float("nan"),
    }


def verdict(front: dict) -> str:
    ok = front["ohlc_exact_pct"] >= PASS_EXACT_PCT and front["coverage_pct"] >= PASS_COVERAGE_PCT
    return "PASS" if ok else "WARN"


# --- main ------------------------------------------------------------------------------------------

def main() -> int:
    key = dotenv_values(ROOT / ".env").get("MASSIVE_API_KEY")
    if not key:
        print("MASSIVE_API_KEY missing from .env")
        return 1

    now = pd.Timestamp(datetime.now(timezone.utc))
    bars = load_bars()
    db = databento_window(bars, now)
    print(f"Databento: {len(db):,} unique contract-minutes, {db['ts_event_utc'].min()} -> {db['ts_event_utc'].max()}")

    client = MassiveClient(key)
    contracts = db.groupby("raw_symbol")["ts_event_utc"].agg(["min", "max"]).sort_values("min")
    frames = []
    for i, (ticker, row) in enumerate(contracts.iterrows(), 1):
        start, end = row["min"], row["max"] + pd.Timedelta(minutes=1)
        before = client.calls
        frames.append(fetch_contract(client, ticker, start, end))
        used = client.calls - before
        print(f"  [{i}/{len(contracts)}] {ticker}: {len(frames[-1]):,} bars"
              + (f" ({used} API calls)" if used else " (cached)"))
    ms = pd.concat(frames, ignore_index=True)

    m = compare(db, ms)
    # massive_only rows have no continuous_symbol; fill from the contract's most common one
    main_sym = db.groupby("raw_symbol")["continuous_symbol"].agg(lambda s: s.mode().iat[0])
    m["continuous_symbol"] = m["continuous_symbol"].fillna(m["raw_symbol"].map(main_sym))
    rolls = roll_points(bars[bars["ts_event_utc"] >= db["ts_event_utc"].min()])
    del bars
    roll_days = set(trading_day(rolls)) if not rolls.empty else set()
    m = add_labels(m, roll_days)

    sections = {"ALL": summarize(m)}
    for sym in sorted(m["continuous_symbol"].dropna().unique()):
        sections[sym] = summarize(m[m["continuous_symbol"] == sym])
    sections["roll days"] = summarize(m[m["is_roll_day"]])
    sections["Wednesdays (EIA)"] = summarize(m[m["is_wednesday"]])
    daily = daily_agreement(m[m["side"] == "both"])
    front = sections.get("CL.v.0", sections["ALL"])
    result = verdict(front)

    by_hour = (m[m["side"] == "both"].groupby("chicago_hour")["max_diff"]
               .apply(lambda s: round(100 * (s == 0).mean(), 2)).rename("ohlc_exact_pct"))
    worst = m[m["side"] == "both"].sort_values("max_diff", ascending=False).head(50)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    worst.to_csv(OUT_DIR / "worst_mismatches.csv", index=False)
    table = pd.DataFrame(sections).T
    lines = [
        "# Databento vs Massive cross-check (CL 1-minute)", "",
        f"Run: {now:%Y-%m-%d %H:%M} UTC. Range: {db['ts_event_utc'].min()} -> {db['ts_event_utc'].max()}", "",
        f"**Verdict: {result}** (needs CL.v.0 OHLC exact >= {PASS_EXACT_PCT}% and coverage >= {PASS_COVERAGE_PCT}%)", "",
        "## Minute bars", "", "```", table.to_string(), "```", "",
        "## Daily high / low / volume per contract", "", "\n".join(f"- {k}: {v}" for k, v in daily.items()), "",
        "## OHLC exact % by Chicago hour", "", "```", by_hour.to_string(), "```", "",
        "Worst 50 minutes: `worst_mismatches.csv`.",
    ]
    (OUT_DIR / "report.md").write_text("\n".join(lines))

    cols = ["databento_bars", "coverage_pct", "massive_only", "ohlc_exact_pct", "ohlc_within_1_tick_pct",
            "max_diff_ticks", "volume_exact_pct", "volume_median_ratio"]
    print("\n" + table[cols].to_string())
    print("\nDaily:", daily)
    print(f"\nAPI calls this run: {client.calls}")
    print(f"Report: {OUT_DIR / 'report.md'}")
    print(f"\nRESULT: {result}")
    return 0 if result == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
