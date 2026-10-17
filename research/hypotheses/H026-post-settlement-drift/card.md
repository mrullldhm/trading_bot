---
id: H026
title: Post-settlement drift - short CL from 14:30 to 15:00 ET
status: parked
prior: C
source: S002 (Claude); variant frozen by Codex R012 Q3
created: 2026-10-17
updated: 2026-10-17
---

# H026 — Post-settlement drift

## 1. Claim
From 14:30 to 15:00 ET, CL falls on average by more than the stress cost (4.402 ticks), so a short every
day makes money after costs.

## 2. Mechanism
Buying pressure into the 14:28-14:30 settlement window (benchmark-bound flows, hedges executed at
settlement) is temporary; once the window closes the price gives part of it back. Who loses: buyers who
must transact at settlement. Why it could survive: the reversal is small and short-lived.

## 3. Literature and prior evidence
- S002 (K4.5): 14:30-15:00 averages -2.2 ticks (t -5.9), negative in every year 2010-16 and every block:
  real but below the 2.4-tick base cost, so a short makes about -0.2 ticks net.
- Price impact in NYMEX crude reverses within ~15 minutes and markets are less resilient on roll days
  (Kumar and Venkataraman, Bank of Canada presentation; background only).
- Prior **C**. Codex (R012): it should fail the stress-cost check mechanically.

## 4. Exact definition (causal), frozen before the run
- Data: `CL.v.0`, discovery trading days only, through `propfirm_research.data`.
- Every trading day whose entry is valid from what is known by the entry (`grid.windows` `entry_ok`):
  entry at the open of the first bar at or after 14:30 (at most 5 minutes late); exit at the open of the
  bar at exactly 15:00 (strict exit D009). Direction: short. No return or volume filter. 1 CL.
- Estimand (R014): emitted = entry valid by the entry time (14:35 at the latest); evaluated = the exact
  15:00 bar exists in the same
  contract; unevaluable signals are counted and excluded from P&L.
- Costs: gross return uses the two bar opens; net base subtracts $24.02 per round trip (fee and one
  adverse tick of slippage on each side), stress $44.02.
- Variant v4 of the H025 family (BH q over 4 variants); same statistics and promotion screen as H025 §4.

## 5. Discovery exploration
One run with H025, 2026-10-17 (see the H025 card for command, ledger rows and counts); table
[explore.csv](explore.csv). Variant v4 of the shared family of 4.

| Trades (per year) | Gross ticks (short) | t | q | Net base / stress | Net Sharpe | 2010-12 / 2013-14 / 2015-16 gross | MDE net |
|---|---|---|---|---|---|---|---|
| 1,616 (246) | 2.25 | 6.07 | 3e-9 | -0.16 / -2.16 | -0.16 | 2.04 / 2.84 / 1.92 | 1.34 |

Promotion screen: q and sign pass (positive in every block); **stress cost fails** (2.25 < 4.402) and the
net edge is negative even at base cost, so power fails too. 1 eligible day skipped by the strict exit.

## 6. Pre-registration
Only if it passes every promotion check.

## 7. Validation result
-

## 8. Codex replication
[R015](../../reviews/R015-codex-h025-h026-replication.md), blind, from raw parquet with Codex's own code: every n, gross mean, t and block mean matches to rounding (tolerance n 1%, gross 0.1 tick). **VALIDATED** (the discovery numbers; the verdict is unchanged).

## 9. Verdict and next step
**PARKED** (below cost). The post-settlement drift is real and stable (every block, t 6) but about 2.2
ticks, under the 2.4-tick base cost of a round trip. It stays useful as a component: a reason not to
hold longs through 14:30-15:00, or a timing input for other settlement ideas. No validation family spent.

## 10. Change log
- 2026-10-17: created; definition frozen from Codex R012 Q3 before any run.
- 2026-10-17: discovery run (not promoted); status parked. Codex replication R015: exact match.
- 2026-10-17: R014 clarifications before any run (no data seen): emitted / evaluated estimand, fill
  and cost wording; ledger n_tests 1 (family of 4 shared with H025, counted once).
