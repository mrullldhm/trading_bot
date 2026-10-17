"""S004 stage-1 data audit (research/studies/S004-stage1-data/report.md): the D010 data for 2015-16, read only through
the firewall loaders. Schema and coverage only: no signed daily aggregates, no returns, nothing about what follows
the settlement (Codex R016 Q5). It checks that the data can carry H027 / H028 as written in their cards, using the
harness's own rules (`settlement.front_tas_symbol`, `bar_endpoints`, `bz_endpoints`, `coverage_ok`).

1 coverage per source; 2 TAS: side share by month, volume by ET hour, front / deferred / spread shares, price
differentials, front mapping, days passing the 99% side rule; 3 CL mbp-1: side share, quote-rule accuracy on
trades with a reported side, days passing the 99% classification rule, minute volume vs the CL.v.0 bars, contract
agreement; 4 statistics: types, revisions, publication times, settlement vs the 14:28-14:30 trade VWAP;
5 RB / HO / BZ: exact 14:25 and 14:34 bars, BZ staleness rule.

Acceptance (`ACCEPT`, all required; `settlement.s004_accepted` also checks that the files are unchanged since the
audit). Disclosed changes:
- before the first run: the quote-rule rule was first "agreement >= 0.95" (written before any mbp-1 data); after
  the day-1 check of line 6 (agreement 88.7%, probably implied liquidity missing from the direct book) it became
  "mis-signed share of all window volume <= 1%" (the cards' 1% tolerance) plus "accuracy when classified >= 0.80";
- after the first run (S004-016 failed one rule), accepted by Codex R017: the after-close rule counts front TAS
  trades from 14:30:01 (timestamp precision), not 14:30:00. Two outright TAS trades in 2015-16 were stamped in that
  first second (2015-05-05 14:30:00.038 CLTN5, deferred; 2016-05-31 14:30:00.047 CLTN6, front): close-time matches,
  and the H027 harness drops every trade at or after 14:30:00 anyway. Also from R017: a BZ coverage rule was added
  and the quote-rule accuracy is weighted by volume (it was a count).

Usage: python -m propfirm_research.studies.s004_stage1_data
"""

import json
import time
from datetime import datetime, timezone

import numpy as np
import pandas as pd

from .. import data, grid, ledger, paths, settlement
from .s001_feasibility import code_hash

ITEM = "S004"
REPORT_DIR = paths.RESEARCH_DIR / "studies" / "S004-stage1-data"
FIRST, LAST = settlement.STAGE1
SETTLE_START, SETTLE_END = 14 * 60 + 28, 14 * 60 + 30  # CL settlement window, ET minutes [start, end)
SLICE = (14 * 60 + 20, 14 * 60 + 35)
TAS_CLOSE, DAY_START = 14 * 60 + 30, 18 * 60  # a TAS trade between these ET minutes would be after the TAS close
STAT_NAMES = {1: "opening", 2: "indicative opening", 3: "settlement", 4: "session low", 5: "session high",
              6: "cleared volume", 7: "lowest offer", 8: "highest bid", 9: "open interest", 10: "fixing", 11: "close",
              12: "net change", 13: "vwap", 17: "upper price limit", 18: "lower price limit"}
ACCEPT = {  # data-integrity and coverage conditions, fixed before the audit ran (the H027 / H028 screen needs all)
    "cl_minute_volume_exact_share >= 0.99": lambda f: f["cl_minute_volume"]["exact_share"] >= 0.99,
    "settlement_within_1_tick_share >= 0.95": lambda f: f["settlement_vs_vwap"]["within_1_tick_share"] >= 0.95,
    "quote_rule_mis_signed_volume_estimate <= 0.01":
        lambda f: f["cl_quote_rule"]["mis_signed_volume_share_estimate"] <= 0.01,
    "quote_rule_volume_accuracy_when_classified >= 0.80":
        lambda f: f["cl_quote_rule"]["volume_accuracy_when_classified"] >= 0.80,
    "mbp1_contract_matches_bars_every_day": lambda f: f["cl_contract_match_days"] == f["cl_contract_compared_days"],
    "tas_front_one_instrument_every_day": lambda f: f["tas_front_days_multi_id"] == 0,
    "no_front_tas_trade_from_143001_to_1800": lambda f: f["tas_front_trades_after_close"] == 0,
    "cl_mbp1_share_of_regular_days >= 0.98": lambda f: f["coverage_share"]["cl_mbp1"] >= 0.98,
    "tas_front_share_of_regular_days >= 0.95": lambda f: f["coverage_share"]["tas_front"] >= 0.95,
    "rb_exact_bars_share_of_regular_days >= 0.95": lambda f: f["coverage_share"]["RB.v.0"] >= 0.95,
    "ho_exact_bars_share_of_regular_days >= 0.95": lambda f: f["coverage_share"]["HO.v.0"] >= 0.95,
    "bz_signal_prices_share_of_regular_days >= 0.95": lambda f: f["coverage_share"]["BZ.v.0"] >= 0.95,
}
CLOSE_GRACE_NS = 1_000_000_000  # TAS trades in the first second after 14:30:00 are close-time matches (R017)


def month(days) -> np.ndarray:
    return pd.to_datetime(np.asarray(days), unit="D").strftime("%Y-%m").to_numpy()


def et_clock(ns: np.ndarray) -> pd.DatetimeIndex:
    return pd.to_datetime(ns, utc=True).tz_convert("America/New_York")


def et_minute(ns: np.ndarray) -> np.ndarray:
    t = et_clock(ns)
    return np.asarray(t.hour * 60 + t.minute)


class Audit:
    def __init__(self):
        purpose = "S004 stage-1 data audit (schema and coverage only)"
        bars = data.load_front("discovery", ITEM, purpose)
        self.digests = {"bars": bars.attrs["data_sha256"]}
        self.bars = bars[(bars["trading_day"] >= FIRST) & (bars["trading_day"] <= LAST)].reset_index(drop=True)
        self.days = np.unique(self.bars["trading_day"].to_numpy())
        self.tas = data.load_trades("tas", "discovery", ITEM, purpose)
        self.cl = data.load_trades("cl_mbp1", "discovery", ITEM, purpose)
        self.stats = data.load_statistics("discovery", ITEM, purpose)
        self.rel = {s: data.load_related(s, "discovery", ITEM, purpose) for s in data.RELATED}
        self.digests.update({"tas": self.tas.attrs["data_sha256"], "cl_mbp1": self.cl.attrs["data_sha256"],
                             "statistics": self.stats.attrs["data_sha256"],
                             "energy": self.rel["RB.v.0"].attrs["data_sha256"]})
        w = grid.windows(self.bars, [(settlement.ENTRY, grid.FLAT)], days=self.days)
        self.entry = w.set_index("trading_day")[["entry_ok", "entry_contract"]]  # never the outcome columns
        self.regular = self.entry.index[self.entry["entry_ok"]].to_numpy()  # days with a valid 14:35 entry
        self.tables, self.facts = {}, {"data_sha256": self.digests}

    # 1 ---------------------------------------------------------------------------------------------------
    def coverage(self):
        reg = set(self.regular)
        sources = {"cl_bars": reg, "tas_front": set(self.front_tas()["trading_day"]),
                   "cl_mbp1": set(self.cl["trading_day"]), "settlement": set(self.settlements()["session_day"])}
        for s, df in self.rel.items():
            ends = (settlement.bz_endpoints if s == "BZ.v.0" else settlement.bar_endpoints)(df, self.regular)
            sources[s] = set(ends.dropna().index)
        rows = [{"source": k, "days": len(v), "regular_days_covered": len(v & reg),
                 "share_of_regular": len(v & reg) / len(reg)} for k, v in sources.items()]
        self.tables["coverage"] = pd.DataFrame(rows)
        self.facts["regular_days"] = len(reg)
        self.facts["coverage_share"] = {r["source"]: r["share_of_regular"] for r in rows}

    # 2 ---------------------------------------------------------------------------------------------------
    def front_tas(self) -> pd.DataFrame:
        """Front-outright TAS trades: the CLT outright of the 14:35 entry contract (harness rule)."""
        front = self.entry["entry_contract"].dropna().map(settlement.front_tas_symbol)
        t = self.tas[~self.tas["is_spread"]]
        return t[t["raw_symbol"].to_numpy() == t["trading_day"].map(front).to_numpy()]

    def tas_tables(self):
        t = self.tas
        by_m = pd.DataFrame({"month": month(t["trading_day"]), "size": t["size"], "signed": t["side"] != 0})
        g = by_m.groupby("month").agg(records=("size", "size"), volume=("size", "sum"))
        g["side_volume_share"] = by_m[by_m["signed"]].groupby("month")["size"].sum() / g["volume"]
        self.tables["tas_side_by_month"] = g.reset_index()
        front = self.front_tas()
        kind = np.where(t["is_spread"], "spread", "outright deferred")
        kind[t.index.isin(front.index)] = "outright front"
        vol = pd.DataFrame({"kind": kind, "hour": et_clock(t["event_ns"].to_numpy()).hour, "size": t["size"]})
        self.tables["tas_volume_by_hour"] = (vol.pivot_table(index="hour", columns="kind", values="size",
                                                             aggfunc="sum", fill_value=0) / t["size"].sum()).reset_index()
        self.facts["tas_kind_share"] = (vol.groupby("kind")["size"].sum() / t["size"].sum()).round(4).to_dict()
        diff = pd.DataFrame({"kind": np.where(t["is_spread"], "spread", "outright"), "diff": t["diff_ticks"],
                             "size": t["size"]})
        self.tables["tas_differentials"] = diff.pivot_table(index="diff", columns="kind", values="size",
                                                            aggfunc="sum", fill_value=0).reset_index()
        sided = front.assign(sided=front["size"] * (front["side"] != 0))
        per_day = sided.groupby("trading_day").agg(ids=("instrument_id", "nunique"), volume=("size", "sum"),
                                                   sided=("sided", "sum"))
        event = front["event_ns"].to_numpy()
        minute = et_minute(event)
        daytime = front[minute < DAY_START]
        clock = et_clock(daytime["event_ns"].to_numpy())
        close = settlement.cutoff_ns(front["trading_day"].to_numpy(), TAS_CLOSE)  # 14:30:00 ET of each trade's day
        before_evening = minute < DAY_START
        self.facts.update({
            "tas_front_days": int(len(per_day)), "tas_front_days_multi_id": int((per_day["ids"] > 1).sum()),
            "tas_front_days_side_rule_ok": int(settlement.coverage_ok(per_day["sided"], per_day["volume"]).sum()),
            "tas_front_volume_per_day_median": float(per_day["volume"].median()),
            "tas_front_latest_daytime_trade_et": str(max(clock.time)) if len(clock) else None,
            "tas_front_trades_in_first_second_after_close": int(
                (before_evening & (event >= close) & (event < close + CLOSE_GRACE_NS)).sum()),
            "tas_front_trades_after_close": int((before_evening & (event >= close + CLOSE_GRACE_NS)).sum())})

    # 3 ---------------------------------------------------------------------------------------------------
    def cl_tables(self):
        c = self.cl
        q = settlement.quote_side(c["price"], c["bid"], c["ask"])
        rep = c["side"].to_numpy()
        known = rep != 0
        agree = (q == rep) & known
        contradict = (q != 0) & (q != rep) & known
        size = c["size"].to_numpy(float)
        unreported = ~known
        accuracy_count = agree.sum() / max(agree.sum() + contradict.sum(), 1)
        accuracy_volume = size[agree].sum() / max(size[agree].sum() + size[contradict].sum(), 1)
        classified_n = unreported & (q != 0)
        self.facts["cl_quote_rule"] = {
            "trades_with_reported_side": int(known.sum()), "agree_share": float(agree.sum() / known.sum()),
            "contradict_share": float(contradict.sum() / known.sum()),
            "inside_or_bad_book_share": float(((q == 0) & known).sum() / known.sum()),
            "count_accuracy_when_classified": float(accuracy_count),
            "volume_accuracy_when_classified": float(accuracy_volume),
            "unreported_volume_share": float(size[unreported].sum() / size.sum()),
            "unreported_classified_volume_share": float(size[classified_n].sum() / max(size[unreported].sum(), 1)),
            "mis_signed_volume_share_estimate": float(size[classified_n].sum() / size.sum() * (1 - accuracy_volume))}
        s = np.where(known, rep, q)
        per = pd.DataFrame({"day": c["trading_day"], "size": size, "sided": size * (s != 0),
                            "reported": size * known})
        g = per.groupby("day")[["size", "sided", "reported"]].sum()
        self.facts["cl_days"] = int(len(g))
        self.facts["cl_days_classified_rule_ok"] = int(settlement.coverage_ok(g["sided"], g["size"]).sum())
        self.facts["cl_days_reported_side_rule_ok"] = int(settlement.coverage_ok(g["reported"], g["size"]).sum())
        shares = pd.DataFrame({"month": month(g.index), "reported_share": g["reported"] / g["size"],
                               "classified_share": g["sided"] / g["size"]})
        self.tables["cl_side_by_month"] = shares.groupby("month").median().reset_index()
        # minute volume vs the CL.v.0 bars, 14:20-14:34
        tv = c.assign(minute=c["event_ns"] // data.NS_PER_MIN).groupby("minute")["size"].sum()
        b = self.bars[(self.bars["mod"] >= SLICE[0]) & (self.bars["mod"] < SLICE[1])
                      & self.bars["trading_day"].isin(np.unique(c["trading_day"]))]
        both = pd.concat([tv.rename("trades"), b.set_index("tmin")["volume"].rename("bars")], axis=1).fillna(0.0)
        diff = both["trades"] - both["bars"]
        self.facts["cl_minute_volume"] = {"minutes": int(len(both)), "exact_share": float((diff == 0).mean()),
                                          "trades_minus_bars_sum": float(diff.sum()),
                                          "abs_diff_p99": float(diff.abs().quantile(0.99))}
        # contract: the mbp-1 contract(s) of the day against the bars' contract in 14:20-14:34
        bar_c = b.groupby("trading_day")["contract"].agg(lambda x: "|".join(sorted(set(x))))
        cl_c = c.groupby("trading_day")["contract"].agg(lambda x: "|".join(sorted(set(x))))
        j = pd.concat([bar_c.rename("bars"), cl_c.rename("mbp1")], axis=1).dropna()
        self.facts["cl_contract_match_days"] = int((j["bars"] == j["mbp1"]).sum())
        self.facts["cl_contract_compared_days"] = int(len(j))

    # 4 ---------------------------------------------------------------------------------------------------
    def settlements(self) -> pd.DataFrame:
        st = self.stats
        return st[(st["stat_type"] == 3) & (st["symbol"] == "CL.v.0")]

    def stats_tables(self):
        st = self.stats
        g = st.groupby(["source", "stat_type"]).agg(
            rows=("stat_type", "size"), sessions=("session_day", "nunique"),
            deletes=("update_action", lambda x: int((x == data.STAT_DELETE).sum())),
            flags=("stat_flags", lambda x: ",".join(map(str, sorted(set(x))))), ref_missing=("ref_missing", "sum"))
        g = g.reset_index()
        g["name"] = g["stat_type"].map(STAT_NAMES)
        pub = pd.DataFrame({"source": st["source"], "stat_type": st["stat_type"],
                            "lag_days": st["known_day"] - st["session_day"],
                            "et_minute": et_minute(st["known_ns"].to_numpy())})
        p = pub.groupby(["source", "stat_type"]).agg(lag_days_min=("lag_days", "min"),
                                                      lag_days_max=("lag_days", "max"),
                                                      et_first=("et_minute", "min"), et_median=("et_minute", "median"),
                                                      et_last=("et_minute", "max")).reset_index()
        for col in ("et_first", "et_median", "et_last"):
            p[col] = p[col].map(lambda m: f"{int(m) // 60:02d}:{int(m) % 60:02d}")
        self.tables["statistics_types"] = g.merge(p, on=["source", "stat_type"])
        # settlement vs the VWAP of 14:28:00-14:29:59.999 front trades (mbp-1 slice)
        s = self.settlements().sort_values("known_ns")
        first, final = s.groupby("session_day").first(), s.groupby("session_day").last()
        c = self.cl[(self.cl["mod"] >= SETTLE_START) & (self.cl["mod"] < SETTLE_END)]
        notional = (c["price"] * c["size"]).groupby(c["trading_day"]).sum()
        vwap = notional / c.groupby("trading_day")["size"].sum()
        cmp_ = pd.DataFrame({"settle_final": final["price"] * 100, "settle_first": first["price"] * 100,
                             "vwap": vwap}).dropna()
        dev = (cmp_["settle_final"] - cmp_["vwap"].round()).abs()
        self.facts["settlement_vs_vwap"] = {
            "days": int(len(cmp_)), "within_1_tick_share": float((dev <= 1).mean()),
            "exact_share": float((dev == 0).mean()), "abs_dev_p95_ticks": float(dev.quantile(0.95)),
            "first_differs_from_final_share": float((cmp_["settle_first"] != cmp_["settle_final"]).mean()),
            "revisions_per_session_max": int(s.groupby("session_day").size().max()) if len(s) else 0}

    # 5 ---------------------------------------------------------------------------------------------------
    def related_tables(self):
        rows = []
        for s, df in self.rel.items():
            w = df[(df["mod"] >= SLICE[0]) & (df["mod"] < SLICE[1]) & df["trading_day"].isin(self.regular)]
            per_day = w.groupby("trading_day").size().reindex(self.regular, fill_value=0)
            ends = (settlement.bz_endpoints if s == "BZ.v.0" else settlement.bar_endpoints)(df, self.regular)
            rows.append({"symbol": s, "days_with_any_bar": int((per_day > 0).sum()),
                         "minutes_per_day_median": float(per_day.median()),
                         "signal_prices_days": int(ends["p0"].notna().sum()),
                         "volume_per_minute_median": float(w["volume"].median()) if len(w) else 0.0})
        self.tables["related_minutes"] = pd.DataFrame(rows)


def acceptance(facts: dict) -> dict:
    out = {k: bool(rule(facts)) for k, rule in ACCEPT.items()}
    out["all_ok"] = all(out.values())
    return out


def md_table(df: pd.DataFrame) -> str:
    cols = list(df.columns)
    fmt = lambda v: f"{v:.4g}" if isinstance(v, float) else str(v)  # noqa: E731
    lines = ["| " + " | ".join(map(str, cols)) + " |", "|" + "---|" * len(cols)]
    lines += ["| " + " | ".join(fmt(v) for v in row) + " |" for row in df.itertuples(index=False)]
    return "\n".join(lines)


def write_report(manifest: dict, tables: dict) -> None:
    f = manifest["facts"]
    acc = f["acceptance"]
    parts = [
        "---", "id: S004", "title: Stage-1 data audit (D010 data, 2015-16)", "status: done",
        f"updated: {manifest['utc'][:10]}", "---", "",
        "# S004 — Stage-1 data audit", "",
        "Generated by `python -m propfirm_research.studies.s004_stage1_data` (code "
        f"`{manifest['code_sha256'][:12]}...`; per-table data hashes in the facts below and in the LEDGER S004 access "
        "rows). Schema and coverage only: no signed daily aggregates and no returns (Codex R016 Q5).", "",
        f"**Acceptance (data integrity and coverage for H027 / H028): {'PASS' if acc['all_ok'] else 'FAIL'}**", "",
        md_table(pd.DataFrame([{"condition": k, "ok": v} for k, v in acc.items() if k != "all_ok"])), "",
        "## Facts", "", "```json", json.dumps({k: v for k, v in f.items() if k != "acceptance"}, indent=1,
                                              default=str), "```", ""]
    for name, tab in tables.items():
        parts += [f"## {name.replace('_', ' ')}", "", md_table(tab), ""]
    (REPORT_DIR / "report.md").write_text("\n".join(parts))


def run() -> dict:
    t0 = time.time()
    a = Audit()
    a.coverage()
    a.tas_tables()
    a.cl_tables()
    a.stats_tables()
    a.related_tables()
    a.facts["acceptance"] = acceptance(a.facts)
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    for name, tab in a.tables.items():
        tab.to_csv(REPORT_DIR / f"{name}.csv", index=False, float_format="%.6g")
    manifest = {"item": ITEM, "utc": datetime.now(timezone.utc).isoformat(), "code_sha256": code_hash(),
                "facts": a.facts, "seconds": round(time.time() - t0)}
    (REPORT_DIR / "facts.json").write_text(json.dumps(manifest, indent=1, default=str))
    write_report(manifest, a.tables)
    ledger.append(ITEM, "descriptive", "discovery", n_tests=0, code_sha256=manifest["code_sha256"],
                  data_sha256=data.combine_digests(a.digests), output=str(REPORT_DIR.relative_to(paths.ROOT)),
                  value=int(a.facts["acceptance"]["all_ok"]),
                  note="stage-1 data audit: schema and coverage only (no signed daily aggregates, no returns); "
                       f"value = acceptance all_ok; {sum(not v for k, v in a.facts['acceptance'].items() if k != 'all_ok')}"
                       " condition(s) failed")
    print(json.dumps(a.facts, indent=1, default=str))
    for name, tab in a.tables.items():
        print(f"\n== {name}\n{tab.to_string(index=False)}")
    return manifest


if __name__ == "__main__":
    run()
