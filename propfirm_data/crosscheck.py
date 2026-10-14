"""Cross-check the last 2 years of Databento CL bars against Massive (free Futures Basic tier).

Usage:
    python -m propfirm_data.crosscheck

Two independent vendors built from the same CME trades should agree almost exactly.
If they do, we can trust the Databento data for backtesting.

Free tier limits: 5 calls/minute, 2 years of history, ~8 hours delay. The script waits
13 s between calls and caches every contract, so a re-run makes zero API calls.
"""

import json
import random
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from datetime import datetime, timedelta, timezone

import pandas as pd
from dotenv import dotenv_values

from .config import BARS_DIR, DATA_DIR, ROOT
from .validate import CHICAGO, roll_points, trading_day

API_HOST = "api.massive.com"
AGGS_URL = f"https://{API_HOST}/futures/v1/aggs/{{ticker}}"
CALL_INTERVAL_SECONDS = 13.0  # 5 calls/minute on the free tier, plus a little slack
MAX_ATTEMPTS = 7
HISTORY_DAYS = 729  # free tier = 2 years; stay one day inside it
DELAY_HOURS = 8  # free tier data is ~8 hours behind
OUT_DIR = DATA_DIR / "crosscheck"
CACHE_DIR = OUT_DIR / "massive"
PRICE_FIELDS = ["open", "high", "low", "close"]
TICK_COLS = [f"{f}_ticks" for f in PRICE_FIELDS]
PASS_EXACT_PCT = 99.0
PASS_MATCH_PCT = 99.0


# --- Massive API ---------------------------------------------------------------------------

def _check_url(url: str) -> None:
    """Only ever send the key to Massive over https (protects against a bad next_url)."""
    parts = urllib.parse.urlsplit(url)
    if parts.scheme != "https" or parts.hostname != API_HOST:
        raise RuntimeError(f"refusing to send API key to {parts.scheme}://{parts.hostname}")


class MassiveClient:
    """Tiny HTTP client: Bearer auth (key never in URLs or logs), rate limit, retries."""

    def __init__(self, api_key: str, interval: float = CALL_INTERVAL_SECONDS):
        self._key = api_key
        self._interval = interval
        self._last_call = 0.0
        self.calls = 0

    def get(self, url: str) -> dict:
        _check_url(url)
        for attempt in range(1, MAX_ATTEMPTS + 1):
            wait = self._interval - (time.monotonic() - self._last_call)
            if wait > 0:
                time.sleep(wait)
            self._last_call = time.monotonic()
            self.calls += 1
            req = urllib.request.Request(url, headers={"Authorization": f"Bearer {self._key}"})
            backoff = min(120.0, 5.0 * 2 ** (attempt - 1)) + random.uniform(0, 2)
            try:
                with urllib.request.urlopen(req, timeout=60) as resp:
                    _check_url(resp.geturl())  # in case of a redirect
                    return json.loads(resp.read())
            except urllib.error.HTTPError as exc:
                if exc.code == 429:
                    retry_after = exc.headers.get("Retry-After")
                    backoff = float(retry_after) if retry_after and retry_after.isdigit() else max(backoff, 60.0)
                    print(f"  rate limited, waiting {backoff:.0f}s")
                elif exc.code >= 500:
                    print(f"  server error {exc.code}, retrying in {backoff:.0f}s")
                else:
                    raise RuntimeError(f"Massive returned HTTP {exc.code}: {exc.read()[:300]!r}") from None
            except (urllib.error.URLError, TimeoutError, ConnectionError, json.JSONDecodeError) as exc:
                print(f"  network error ({exc.__class__.__name__}), attempt {attempt}, retrying in {backoff:.0f}s")
            time.sleep(backoff)
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
    """Fetch every page by following next_url (a cursor; keeps the filters) until it disappears."""
    results, url = [], first_page_url(ticker, start, end)
    while url:
        page = get(url)
        results += page.get("results") or []
        url = page.get("next_url")
    return results


def massive_to_frame(results: list[dict]) -> pd.DataFrame:
    if not results:
        return pd.DataFrame(columns=["raw_symbol", "ts_event_utc", "volume"] + TICK_COLS)
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

def load_recent_bars(start: pd.Timestamp) -> pd.DataFrame:
    """Read only the years and columns we need (the full file is ~10M rows)."""
    cols = ["ts_event_utc", "continuous_symbol", "instrument_id", "raw_symbol", "volume"] + TICK_COLS
    df = pd.read_parquet(BARS_DIR, columns=cols, filters=[("year", ">=", start.year)])
    return df[df["ts_event_utc"] >= start]


def databento_window(bars: pd.DataFrame, now: pd.Timestamp) -> pd.DataFrame:
    """Last 2 years minus the free-tier delay; one row per (contract, minute), v.0 preferred."""
    start = (now - timedelta(days=HISTORY_DAYS)).normalize()
    end = now - timedelta(hours=DELAY_HOURS)
    df = bars[(bars["ts_event_utc"] >= start) & (bars["ts_event_utc"] < end)]
    df = df.sort_values(["raw_symbol", "ts_event_utc", "continuous_symbol"])  # CL.v.0 sorts before CL.v.1
    return df.drop_duplicates(["raw_symbol", "ts_event_utc"], keep="first").reset_index(drop=True)


def membership(db: pd.DataFrame) -> pd.DataFrame:
    """(contract, trading day) -> which continuous symbol it was that day (v.0 preferred).

    A contract can leave the v.0/v.1 pair and come back later (e.g. CLM5 in 2025), so we
    compare only on days Databento actually had the contract.
    """
    m = db[["raw_symbol", "continuous_symbol"]].copy()
    m["day"] = trading_day(db)
    return m.sort_values("continuous_symbol").drop_duplicates(["raw_symbol", "day"]).reset_index(drop=True)


# --- comparison --------------------------------------------------------------------------------

def compare(db: pd.DataFrame, ms: pd.DataFrame) -> pd.DataFrame:
    """Outer-join both vendors on (contract, minute), restricted to Databento membership days."""
    keep = ["raw_symbol", "ts_event_utc", "volume"] + TICK_COLS
    ms = ms[keep].copy()
    ms["day"] = trading_day(ms)
    ms = ms.merge(membership(db), on=["raw_symbol", "day"], how="inner")  # drop days outside v.0/v.1

    db = db[keep + ["continuous_symbol"]].copy()
    m = db.merge(ms.drop(columns="day"), on=["raw_symbol", "ts_event_utc"], how="outer",
                 suffixes=("_db", "_ms"), indicator=True)
    # label every row by its own day, not by the contract's most common symbol
    m["continuous_symbol"] = m["continuous_symbol_db"].fillna(m["continuous_symbol_ms"])
    m = m.drop(columns=["continuous_symbol_db", "continuous_symbol_ms"])
    m["side"] = m["_merge"].map({"both": "both", "left_only": "databento_only", "right_only": "massive_only"})
    m = m.drop(columns="_merge")
    for f in PRICE_FIELDS:
        m[f"{f}_diff"] = (m[f"{f}_ticks_ms"] - m[f"{f}_ticks_db"]).abs()
    m["max_diff"] = m[[f"{f}_diff" for f in PRICE_FIELDS]].max(axis=1)
    return m


def summarize(m: pd.DataFrame) -> dict:
    both = m[m["side"] == "both"]
    n_db = int((m["side"] != "massive_only").sum())
    n_ms = int((m["side"] != "databento_only").sum())
    pct = lambda x, n: round(100.0 * x / n, 3) if n else float("nan")  # noqa: E731
    out = {
        "databento_bars": n_db,
        "massive_bars": n_ms,
        "matched": len(both),
        "databento_only": n_db - len(both),
        "massive_only": n_ms - len(both),
        "databento_match_pct": pct(len(both), n_db),  # % of Databento bars Massive also has
        "massive_match_pct": pct(len(both), n_ms),  # % of Massive bars Databento also has
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


def add_labels(m: pd.DataFrame, front_roll_days: set) -> pd.DataFrame:
    m = m.copy()
    m["day"] = trading_day(m)
    m["is_front_roll_day"] = m["day"].isin(front_roll_days)
    # EIA report is normally Wednesday 10:30 ET; use the CME trading day, not the calendar day
    m["is_wednesday_session"] = pd.to_datetime(m["day"]).dt.dayofweek == 2
    m["chicago_hour"] = m["ts_event_utc"].dt.tz_convert(CHICAGO).dt.hour
    return m


def daily_agreement(m: pd.DataFrame) -> dict:
    """Daily high/low/volume per contract, each vendor built from ALL of its own bars."""
    def per_vendor(side: str, suffix: str) -> pd.DataFrame:
        rows = m[m["side"].isin(["both", side])]
        return rows.groupby(["raw_symbol", "day"]).agg(
            high=(f"high_ticks_{suffix}", "max"), low=(f"low_ticks_{suffix}", "min"), volume=(f"volume_{suffix}", "sum"))

    d = per_vendor("databento_only", "db").join(per_vendor("massive_only", "ms"), how="outer",
                                                lsuffix="_db", rsuffix="_ms")
    complete = d.dropna()
    n = len(complete)
    pct = lambda s: round(100 * s.mean(), 3) if n else float("nan")  # noqa: E731
    return {
        "contract_days": len(d),
        "days_in_both": n,
        "daily_high_exact_pct": pct(complete["high_db"] == complete["high_ms"]),
        "daily_low_exact_pct": pct(complete["low_db"] == complete["low_ms"]),
        "daily_volume_exact_pct": pct(complete["volume_db"] == complete["volume_ms"]),
    }


def verdict(front: dict) -> str:
    ok = (front["ohlc_exact_pct"] >= PASS_EXACT_PCT
          and front["databento_match_pct"] >= PASS_MATCH_PCT
          and front["massive_match_pct"] >= PASS_MATCH_PCT)
    return "PASS" if ok else "WARN"


# --- main ------------------------------------------------------------------------------------------

def main() -> int:
    key = dotenv_values(ROOT / ".env").get("MASSIVE_API_KEY")
    if not key:
        print("MASSIVE_API_KEY missing from .env")
        return 1

    now = pd.Timestamp(datetime.now(timezone.utc))
    recent = load_recent_bars((now - timedelta(days=HISTORY_DAYS)).normalize())
    db = databento_window(recent, now)
    print(f"Databento: {len(db):,} unique contract-minutes, {db['ts_event_utc'].min()} -> {db['ts_event_utc'].max()}")

    # Fetch each contract's full first..last range (one request range = fewer calls; cached).
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

    front_rolls = roll_points(recent[recent["continuous_symbol"] == "CL.v.0"])
    del recent
    front_roll_days = set(trading_day(front_rolls)) if not front_rolls.empty else set()
    m = add_labels(compare(db, ms), front_roll_days)

    sections = {"ALL": summarize(m)}
    for sym in sorted(m["continuous_symbol"].dropna().unique()):
        sections[sym] = summarize(m[m["continuous_symbol"] == sym])
    sections["CL.v.0 on front roll days"] = summarize(m[m["is_front_roll_day"] & (m["continuous_symbol"] == "CL.v.0")])
    sections["CL.v.0 Wednesday sessions (EIA)"] = summarize(m[m["is_wednesday_session"] & (m["continuous_symbol"] == "CL.v.0")])
    daily = daily_agreement(m)
    front = sections.get("CL.v.0", sections["ALL"])
    result = verdict(front)

    by_hour = (m[(m["side"] == "both") & (m["continuous_symbol"] == "CL.v.0")].groupby("chicago_hour")["max_diff"]
               .apply(lambda s: round(100 * (s == 0).mean(), 2)).rename("ohlc_exact_pct"))
    worst = m[m["side"] == "both"].sort_values("max_diff", ascending=False).head(50)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    worst.to_csv(OUT_DIR / "worst_mismatches.csv", index=False)
    table = pd.DataFrame(sections).T
    lines = [
        "# Databento vs Massive cross-check (CL 1-minute)", "",
        f"Run: {now:%Y-%m-%d %H:%M} UTC. Range: {db['ts_event_utc'].min()} -> {db['ts_event_utc'].max()}", "",
        f"**Verdict: {result}** (CL.v.0 needs OHLC exact >= {PASS_EXACT_PCT}% and both match % >= {PASS_MATCH_PCT}%)", "",
        "Compared only on (contract, trading day) pairs where Databento had the contract as CL.v.0 or CL.v.1.", "",
        "## Minute bars", "", "```", table.to_string(), "```", "",
        "## Daily high / low / volume per contract (each vendor from all its own bars)", "",
        "\n".join(f"- {k}: {v}" for k, v in daily.items()), "",
        "## CL.v.0 OHLC exact % by Chicago hour", "", "```", by_hour.to_string(), "```", "",
        "Worst 50 minutes: `worst_mismatches.csv`.",
    ]
    (OUT_DIR / "report.md").write_text("\n".join(lines))

    cols = ["databento_bars", "databento_match_pct", "massive_match_pct", "ohlc_exact_pct",
            "ohlc_within_1_tick_pct", "max_diff_ticks", "volume_exact_pct", "volume_median_ratio"]
    print("\n" + table[cols].to_string())
    print("\nDaily:", daily)
    print(f"\nAPI calls this run: {client.calls}")
    print(f"Report: {OUT_DIR / 'report.md'}")
    print(f"\nRESULT: {result}")
    return 0 if result == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
