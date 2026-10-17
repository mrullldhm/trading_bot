---
id: H025
title: Settlement continuation, conditioned on move size or settlement volume
status: parked
prior: C
source: S002 (Claude); variants frozen by Codex R012 Q3
created: 2026-10-17
updated: 2026-10-17
---

# H025 — Settlement continuation, conditioned

## 1. Claim
At 14:35 ET, when the 14:25-14:34 move or volume is in the top quarter of the previous 60 eligible days,
CL keeps moving in the direction of that move until 16:05 ET by more than the stress cost (4.402 ticks).

## 2. Mechanism
Settlement-benchmarked flow (trade-at-settlement orders, index and ETF rolls, hedgers marked to the
settlement price) concentrates around the 14:28-14:30 settlement window. Dealers who absorbed one-sided
demand may still carry inventory after 14:30 and keep trading in the same direction. A large move or
heavy volume in 14:25-14:34 should mark days with more of that flow. Who loses: participants who must
trade at or near settlement regardless of price. Why it could survive: the window is short, the flow is
capacity-limited and holding inventory overnight-free until 16:05 is risky.

## 3. Literature and prior evidence
- S002 (K4.4): the naive 14:25-14:35 -> 14:35-16:05 continuation has sign IC 0.12 and 2.6 gross ticks per
  trade, but decays 4.4 / 2.6 / 0.4 ticks across 2010-12 / 2013-14 / 2015-16. Below the 2.4-tick base cost.
- S003 (K6.7): models with move and volume features at 14:35 reach at most ~2.2 gross ticks out of sample.
- K4.5: the 14:30-15:00 drift is negative on average (see H026), which works against long continuations.
- Baltussen et al. 2021 (hedging-demand intraday momentum, indirect); Ge, Kang, Tang, Yang 2023 (TAS
  pressure in the settlement window, April 2020). [literature/REFERENCES.md](../../literature/REFERENCES.md)
- Prior **C**. Claude and Codex (R012) both expect no variant to be promoted.

## 4. Exact definition (causal), frozen before the run
- Data: `CL.v.0`, discovery trading days only (2010-06-07 .. 2016-12-31), through `propfirm_research.data`.
- Signal bars: bars whose start minute is 14:25 .. 14:34 ET of the trading day. The 14:25 and 14:34 bars
  must both exist (interior minutes may be missing; volume then sums the bars that exist), and every signal
  bar must belong to one contract, which must be the entry contract; else no signal. Each failure reason
  is counted. move = close of the 14:34 bar - open of the 14:25 bar (ticks); volume = sum of the signal
  bars' volume.
- Entry-time eligible day: a signal (bars up to 14:34) and an entry that is valid from what is known by the
  entry: the entry bar is the first bar at or after 14:35, at most 5 minutes late (so 14:40 at the latest),
  in the signal's contract; before the scheduled flat time; not a short day.
- Thresholds: the 75th percentile (numpy linear interpolation) of |move| (or volume) over the previous
  60 entry-time eligible days, today excluded; a filter passes only when strictly greater. Before 60
  eligible days have passed: no threshold, no signal.
- Direction: sign(move); move = 0 means no signal.
- **Estimand (R014, D009 complete case):** a signal is *emitted* from information known by the entry
  (14:40 at the latest); it is *evaluated* only if the exact exit bar exists in the same contract. Emitted signals whose exit cannot be
  evaluated are counted ("unevaluable") and excluded from P&L. Reported per variant: emitted, unevaluable,
  evaluated trades.
- Fills: entry at the open of the first bar at or after 14:35 (at most 5 minutes late); exit at the open
  of the bar at exactly the flat time (16:05 ET; earlier before a roll or expiry). Gross return uses the
  two bar opens; net base subtracts $24.02 per round trip (the $4.02 fee and one adverse tick of slippage
  on each side), stress net subtracts $44.02. 1 CL.
- Family (4 variants, shared with H026; code `python -m propfirm_research.settlement h025`):
  - v1 move filter: |move| > its threshold;
  - v2 volume filter: volume > its threshold;
  - v3 union: v1 or v2 (the intersection is not tested: too few trades);
  - v4 = H026 (fixed short 14:30-15:00).
  Reference row, outside the family: the naive continuation on every eligible day.
- Statistics: per variant the one-sided day-level t of the gross edge (one trade per day), BH q over the
  4 variants (a variant with fewer than 3 trades is "inconclusive" and enters BH with p = 1, so the
  family is never smaller than 4), gross mean per discovery block, net at base and stress cost, annual
  Sharpe of the net daily series (no-trade days = 0). Trades per year = evaluated trades / elapsed
  calendar years from the first to the last loaded discovery day.
- Ledger: one data read (item H025); exploratory rows H025 (n_tests 3) and H026 (n_tests 1), so the family
  counts 4 tests once; the naive reference row counts as no new test.
- Promotion screen (PROTOCOL §4.4, all required): q < 0.10; positive gross in at least 2 of the 3 blocks
  including 2015-16; gross > 4.402 ticks; mechanism (section 2); power: discovery net edge at base cost
  >= 2 x MDE_net, MDE_net = 3.168 x sd / sqrt(5 x trades per year) (IID screen; a promoted variant would
  also need a design-specific power simulation, R012 Q4.7, and a red team for outliers, day concentration
  and roll proximity).

## 5. Discovery exploration
One run, 2026-10-17, after Codex review R014 (three follow-ups, GO):
`.venv/bin/python -m propfirm_research.settlement h025`; LEDGER H025-001..003 and H026-001 (code
`f3595789...`, data `e30e4355...`); outputs `data/research/settlement/20261017T024139Z_h025/`; table
[explore.csv](explore.csv). Variants tried: the frozen 4 (BH over 4) plus the naive reference row.

Counts: 1,685 discovery trading days; 68 without a signal (all CME short or holiday sessions, which
also have no valid 14:35 entry); 1,617 entry-time eligible days; the first 60 are warm-up; 18 eligible
days are skipped by the strict exit (no 16:05 bar).

| Variant | Trades (per year) | Gross ticks | t | q | Net base / stress | Net Sharpe | 2010-12 / 2013-14 / 2015-16 gross | MDE net |
|---|---|---|---|---|---|---|---|---|
| v1 move filter | 378 (57.6) | **5.85** | 4.30 | 2e-5 | 3.45 / 1.45 | 0.97 | 9.55 / 5.92 / **1.57** | 4.95 |
| v2 volume filter | 422 (64.2) | 3.25 | 2.52 | 0.006 | 0.85 / -1.15 | 0.25 | 7.33 / 4.24 / **-1.81** | 4.68 |
| v3 union | 641 (97.6) | 3.74 | 3.76 | 1e-4 | 1.34 / -0.66 | 0.52 | 6.24 / 4.44 / 0.22 | 3.61 |
| reference: naive continuation | 1,551 (236) | 2.75 | 4.88 | - | 0.35 / -1.65 | 0.24 | 4.79 / 2.70 / 0.22 | 2.04 |

Promotion screen (PROTOCOL §4.4): **0 of 3 H025 variants promoted.**
- v1: q, sign (positive in all 3 blocks) and stress cost pass; **power fails**: the validation MDE is
  4.95 net ticks, so the discovery net edge would have to be >= 9.9 ticks; it is 3.45. It also decays
  9.5 -> 5.9 -> 1.6 ticks, below the 2.4-tick base cost in 2015-16.
- v2: negative in 2015-16 (sign check fails) and below the stress cost.
- v3: below the stress cost (3.74 < 4.402).

## 6. Pre-registration
Only if a variant passes every promotion check.

## 7. Validation result
-

## 8. Codex replication
[R015](../../reviews/R015-codex-h025-h026-replication.md), blind, from raw parquet with Codex's own code: every n, gross mean, t and block mean matches to rounding (tolerance n 1%, gross 0.1 tick). **VALIDATED** (the discovery numbers; the verdict is unchanged).

## 9. Verdict and next step
**PARKED** (power and decay). Filtering on a large 14:25-14:34 move roughly doubles the naive edge
(5.85 vs 2.75 gross ticks) and gives the programme's first discovery signal with a net Sharpe near 1,
but it fades like the naive effect and sits below cost in the latest block; five validation years could
not confirm anything smaller than ~5 net ticks. No validation family spent. It may only come back as a
new card that adds information the bars lack (for example H027 settlement flow), with its own frozen
family.

## 10. Change log
- 2026-10-17: created; definition frozen from Codex R012 Q3 before any run.
- 2026-10-17: discovery run (0 of 3 promoted); status parked. Codex replication R015: exact match.
- 2026-10-17: R014 clarifications before any run (no data seen): entry-time eligibility and the
  emitted / evaluated estimand, fill and cost wording, interior minutes, trades-per-year denominator,
  BH with an untestable member, ledger allocation.
