---
id: H027
title: Signed TAS and outright settlement flow predict the post-settlement move
status: rejected
prior: B-
source: Codex R012 E1 and R016 Q1; Claude (TAS hedging); Ge, Kang, Tang, Yang 2023
created: 2026-10-17
updated: 2026-10-17
---

# H027 — Signed TAS and outright settlement flow

## 1. Claim
On 2015-16 discovery days, when the day's signed trade-at-settlement (TAS) imbalance or the signed outright
flow around the settlement window is in the top quarter of the previous 60 eligible days:
- CL moves *with* the imbalance from 14:35 to 16:05 (v1, v3);
- or CL moves *against* it from 14:31 to 15:00 (v2, v4);
by more than the stress cost (4.402 ticks).

## 2. Mechanism
- **TAS.** Some participants must trade at the official settlement price: index and ETF rolls, hedgers
  marked to settlement, benchmarked funds. They buy or sell TAS, a separate Globex book (`CLT`) that trades
  at the settlement price plus a differential.
- **Dealer hedging.** The dealers on the other side hold a position priced at the settlement (the VWAP of
  14:28:00-14:30:00 ET). They hedge it by trading the outright inside that window. Net customer TAS buying
  therefore means dealers buy the outright during the window.
- **Residual inventory, continuation (v1, v3).** A 2-minute window has limited capacity. Dealers who
  cannot finish their hedge inside it keep trading the same way after 14:30, so the move continues to the
  close. S002's continuation of the 14:25-14:35 move is consistent with this (K4.4).
- **Temporary impact, unwind (v2, v4).** The hedging push moves the price only temporarily. When the push
  stops at 14:30, the impact decays and the price reverses over 14:31-15:00. The unconditional 14:30-15:00
  drift of -2.2 ticks, negative in every year 2010-16 (K4.5), is what an average net buying push that
  unwinds would produce. H026 traded it without knowing the push direction.
- **Who loses.** Benchmark-bound flow, which pays the impact through the settlement price, and late
  liquidity takers.
- **Why it could survive.** The TAS book is public but small. The effect is short-lived, and holding to
  16:05 is risky.
- **New information.** Signed TAS volume and aggressor-signed outright volume. One-minute bars carry
  neither: they have total volume only, and the TAS book is invisible in them. This information is outside
  the S003 ceiling's search space.

## 3. Literature and prior evidence
- S002: settlement continuation 2.6 gross ticks, decaying 4.4 / 2.6 / 0.4 by block (K4.4); post-settlement
  drift -2.2 ticks (K4.5).
- H025: the move-filtered continuation earns 5.85 gross ticks but only 1.57 in 2015-16; power fails (K4.11).
- H026: the short from 14:30 to 15:00 earns 2.25 gross ticks, below cost (K4.12).
- Ge, Kang, Tang, Yang 2023: TAS pressure in the settlement window (April 2020).
  [REFERENCES](../../literature/REFERENCES.md)
- Prior **B-**. Codex R016 gives 7% that any H027 variant survives stage 1. Claude's estimate is a few
  percent.

## 4. Exact definition (causal), frozen before the run

**Data.** All through `propfirm_research.data`, trading days 2015-01-02 .. 2016-12-30 only (stage 1, D008):
- CL.v.0 1-minute bars: outcomes, entry and exit;
- CLT trades (D010 line 2);
- CL.v.0 mbp-1 trade records 14:20-14:35 ET, which carry the aggressor side and the best bid/offer
  (D010 line 6, chosen by the owner after the sample: D010 addendum).

**Entry contract.** The contract of the variant's entry bar: 14:35 for v1/v3, 14:31 for v2/v4
(`grid.windows` `entry_contract`).

**Front TAS.** The CLT outright whose raw symbol is `CLT` plus the entry contract's month code
(CLN5 -> CLTN5).
- TAS calendar spreads are excluded.
- That raw symbol must map to exactly one instrument id on the day; otherwise there is no signal.

**Known-at.** A trade feeds the decision only if its `ts_recv` is strictly before the entry minute
(14:35:00 or 14:31:00 ET). Before 2017, `ts_recv` is a copy of `ts_event` (S004).

**TAS imbalance** I_TAS = sum of size x side over the front-TAS trades of the trading day that are known
before the entry.
- The TAS session runs from 18:00 ET the evening before to the TAS close: only trades with `ts_event` before
  14:30:00 ET count (a trade stamped 14:30:00-17:59:59 is outside the session, R018 N1).
- side: buyer aggressor +1, seller aggressor -1.
- If trades without a side make up more than 1% of that volume (side coverage below 99%, R016), there is no
  signal. The test is in whole lots: 100 x signed >= 99 x total.

**Outright flow** I_CL = sum of size x s over CL.v.0 trades with `ts_event` in the variant's window and
known before the entry. Windows: v3 14:25:00-14:34:59.999; v4 14:20:00-14:29:59.999.
- s = the reported aggressor side when present.
- Otherwise, the quote rule against the best bid/offer carried by the trade record: price >= ask gives +1;
  price <= bid gives -1.
- A trade inside the spread, or on a locked or crossed book, is unclassified.
- There is no signal if unclassified volume is more than 1% of the window's volume (same whole-lot test), or
  if any window trade is in a contract other than the entry contract.

**Filter.** |I| must be strictly above the 75th percentile (numpy linear interpolation) of |I| over the
previous 60 eligible days of the same variant, today excluded.
- The first 60 eligible days are warm-up, with no trade.
- I = 0 means no signal.

**Eligible day (entry time).** The signal is available and the variant's window is `entry_ok`. A signal is
emitted at entry; it is evaluated only if the exact exit bar exists in the same contract (D009, the R014
estimand). Emitted but unevaluable signals are counted.

**Variants (the family, 4 slots).**

| v | Score | Direction | Trade |
|---|---|---|---|
| v1 TAS residual | I_TAS, known before 14:35 | +sign(I) | 14:35 -> 16:05 (the day's flat time) |
| v2 TAS unwind | I_TAS, known before 14:31 | -sign(I) | 14:31 -> 15:00 |
| v3 outright residual | I_CL, ts_event 14:25:00-14:34:59 | +sign(I) | 14:35 -> 16:05 |
| v4 outright unwind | I_CL, ts_event 14:20:00-14:29:59 | -sign(I) | 14:31 -> 15:00 |

**Fills and costs.**
- Entry = the open of the first bar at or after the entry minute, at most 5 minutes late.
- Exit = the open of the bar exactly at the exit minute (D009). The flat time is 16:05, or earlier before a
  roll or expiry; short days have no trade.
- Base cost $24.02 per round trip, stress $44.02. One CL.

**Statistics.**
- Per variant: the one-sided day-level t of the gross ticks (one trade a day).
- BH q over the 4 slots. A slot with fewer than 3 trades is inconclusive, with p = 1.
- Gross mean in 2015 and in 2016.
- Net at base and stress cost.
- The annual Sharpe of the net daily series (no-trade days = 0).
- MDE_net = 3.168 x sd / sqrt(5 x trades per year), where trades per year = evaluated trades / elapsed
  years of the loaded 2015-16 days.

**Stage-1 screen (R016 Q3, all required).**
- q < 0.10;
- gross > 0 in 2015 and in 2016;
- >= 25 evaluated trades a year;
- gross > 4.402 ticks;
- net (base) >= 2 x MDE_net;
- the largest single-day gross P&L <= 25% of the variant's total gross P&L;
- no data-integrity failure (S004).

A survivor justifies buying 2010-14 (a new owner decision). The unchanged family then runs on the full
discovery period under the three-block rule of PROTOCOL §4.4. Stage 1 promotes nothing to pre-registration.

**Descriptive only (not tested).** The share of each variant's emitted days (entry-time signal) that are
also H025 v1 emitted days. Both sides use entry-time masks, so a missing exit bar cannot move it (R018 N2).

**Ledger.** One exploratory row H027 with n_tests 4.
- **One attempt only (R018 B1).** Before reading any data, the harness atomically claims `stage1_attempt.json`
  in this folder.
- That file is never removed: a finished, failed or interrupted attempt blocks every rerun.
- A refused S004 audit does not spend the attempt.

**Frozen 2026-10-17, before any run**, after Codex R017 GO (data) and R018 follow-up 6 GO (card and harness). Harness `propfirm_research/settlement.py` sha256 `bd2c121744e77c7cb7e781bf9aea162c4ad881b0a16dfc86a40ccf13912f87b7`; package code hash `f4437977a74847aeaa6d3238274dde8fda7d47bb181127d5ba076d564cbb994d`; S004 acceptance `research/studies/S004-stage1-data/facts.json` sha256 `00d0ba379935bbbc58d74fb0ffb11d297d7f08993cd4c0bc4c53b3533e09afdd` (all 12 rules). Nothing above this line changes after the run.

## 5. Discovery exploration
**One run, 2026-10-17, on 2015-16 (stage 1).**
- Command: `.venv/bin/python -m propfirm_research.settlement h027`.
- Ledger: H027-001..008 (access rows and the exploratory row; n_tests 4).
- Outputs: `data/research/settlement/20261017T140950Z_h027/` and [explore.csv](explore.csv). Run time 78 s.

**Counts.** 516 trading days.
- Front-TAS signal available on 480 days (19 regular days fail the 99% side rule). Outright-flow signal on 499.
- 17 days without a valid entry. The first 60 eligible days are warm-up.
- No emitted signal lost its exit bar.

| Variant | Trades (per year) | Gross ticks | sd | t | Gross 2015 / 2016 | Net base | MDE net | Stage-1 screen |
|---|---|---|---|---|---|---|---|---|
| v1 TAS residual (+, 14:35-16:05) | 107 (53.6) | **-1.93** | 18.8 | -1.06 | -2.91 / -1.15 | -4.33 | 3.63 | fail (wrong sign) |
| v2 TAS unwind (-, 14:31-15:00) | 107 (53.6) | **-1.79** | 13.9 | -1.33 | -3.62 / -0.35 | -4.19 | 2.69 | fail (wrong sign) |
| v3 outright residual (+, 14:35-16:05) | 110 (55.1) | **+0.47** | 17.6 | 0.28 | -0.85 / +1.50 | -1.93 | 3.35 | fail (2015 negative, below stress cost, q 1.0) |
| v4 outright unwind (-, 14:31-15:00) | 103 (51.6) | **-3.59** | 10.5 | -3.48 | -3.03 / -3.95 | -5.99 | 2.07 | fail (wrong sign) |

BH q is 1.0 for every slot. **0 of 4 pass the stage-1 screen.** Overlap with the H025 v1 emitted days is 27-35%
(descriptive).

Observation (not a test): v4's sign is wrong by t -3.5. The 14:20-14:29 signed outright flow *continued* over
14:31-15:00 instead of unwinding, by 3.6 gross ticks.
- This is a result seen after the fact, so it is no finding.
- Even taken at face value, it is below the 4.402-tick stress cost.
- It would need about 6.5 gross ticks to be worth a validation family.

## 6. Pre-registration
None. Stage 1 promotes nothing, and no variant survived.

## 7. Validation result
-

## 8. Codex replication
[R019](../../reviews/R019-codex-h027-h028-replication.md): a blind replication with Codex's own code.
- Every count, gross, sd, t, year split and MDE matches, most to 4 or more decimals.
- **MATCH** on all four variants.

## 9. Verdict and next step
**REJECTED at stage 1** (D008 kill rule).
- Signed TAS imbalance and signed outright flow around the settlement window do not predict CL after 14:30 in
  2015-16 in the direction their mechanisms say. Three of four variants have the wrong sign.
- No 2010-14 purchase is justified.
- The settlement-flow track (D008) ends here. The direction now goes back to the owner (D011).

## 10. Change log
- 2026-10-17: the one stage-1 run: 0 of 4 pass; Codex R019 MATCH; rejected.
- 2026-10-17: frozen (section 4) after Codex R017 GO and R018 follow-up 6 GO.
- 2026-10-17: Codex R018 (NO-GO, then fixed before any run): TAS session cut at 14:30:00, entry-time overlap,
  one-attempt marker, more tests.
- 2026-10-17: before any run, the 1% rule was worded to match R016 and the code: exactly 1% unsigned still
  passes (gate review finding).
- 2026-10-17: created from Codex R016 (blind) and Claude's draft (written before reading R016). v2 is the
  TAS unwind instead of R016's TAS premium (see R016 response). The outright flow uses the mbp-1 data
  (owner, D010 addendum), signed by the reported side and, where it is missing, by the quote rule.
