---
id: D011
title: Direction after stage 1 - the settlement-flow track found nothing
status: decided
decided: 2026-10-17
approver: owner
updated: 2026-10-17
---

# D011 — Direction after stage 1 (owner decision)

## Context
D008 said: "if every stage-1 signal fails its kill rule, the owner decides between deeper data (e.g. order book),
another market, or a pause, with the kill-criteria evidence." That is where we are.

**Stage 1 (session 4).**
- Money: about $9.5 of the $15 cap (D010; the owner is to confirm the actual figure in the Databento portal).
- Data: TAS trades, aggressor-signed CL flow (mbp-1), settlement statistics and RB/HO/BZ bars for 2015-16.
  The data were audited (S004: trade volume equals bar volume in every one of 7,505 minutes) and reviewed by
  Codex (R017 GO).
- Families: H027 (TAS / signed flow, 4 variants) and H028 (cross-energy, 3 variants), frozen after Codex R018
  and run once each.
- **Result: 0 of 7 survive.** Five have the wrong sign; the best right-signed variant earns +0.47 gross ticks
  (t 0.28). Codex's blind replication matched exactly (R019).

**Where the whole programme stands (PROTOCOL §4.7 kill criteria).**
| Criterion | State |
|---|---|
| 1. The S003 ceiling is below stress break-even | Mostly met. 0 of 432 bar-based model strategies beat costs. Short quiet windows are bounded below the stress cost; long holds cannot be bounded (K6.7, K6.9) |
| 2. The pipeline would see a 4-8 tick edge | Partly met. Planted 8-tick edges are found 90% of the time, 4-tick edges only 15% (K6.8) |
| 3. No family survives validation and the holdout | Met by default. No family ever qualified for validation: H025/H026 0 of 4, H027/H028 0 of 7 (0 of 25 validation families used) |
| 4. No candidate passes the gates | Met. Strategies 1-8: 1,389,977 configurations, 0 passed |

Everything that had a reason to work at the settlement window has now been tested, with information the bars
lack, and it did not work.

## Options
| Option | What it means | For | Against | Cost |
|---|---|---|---|---|
| **(a) Pause the CL intraday programme** | Record the negative result; keep the code, the data and the unopened validation and holdout | The evidence is broad and consistent; no further spending; everything stays reusable | No chance of a strategy while paused | $0 |
| (b) Deeper CL data | e.g. full-depth order book (MBO) at the settlement window, or option open interest (H030) | The only route that stays on CL | Each new source so far added nothing; low prior; MBO is bigger and costlier (exact quote needed) | an exact quote is needed first |
| (c) Another Topstep market, full reset | One liquid equity-index future (e.g. ES); rerun the S001 → S002 → S003 sequence before any hypothesis | Stronger published intraday evidence for equity indices (Gao et al. 2018; Baltussen et al. 2021); the toolkit, firewall and Codex workflow carry over | Changes D004 (CL only); new data purchase; weeks of work; Codex R012 gave it 8% | data quote needed (1-minute bars are usually cheap) |

Not an option: slower horizons on CL. The Combine needs the account flat every day (16:10 ET), so multi-day holds
do not fit.

## Recommendation (Claude)
**(a) pause**, unless the owner wants to keep going. In that case, **(c) with a hard budget and the same
staged discipline**, before anything in (b).
- **Why not (b) first.** The most promising CL structure (settlement) has now been tested with new information
  in three independent ways (TAS, signed flow, related markets), and all three came back empty or with the
  wrong sign. Deeper data at the same place has a low prior and a higher price.
- **Why (c) over (b).** It is a new information set with stronger published evidence, and the programme's
  method transfers unchanged. Before any choice of market, a blind Codex consult (as R012) should rank the
  candidates.

## Decision
**Owner, 2026-10-17: (a) pause the CL intraday programme.**
- Spending: no further data purchases.
- Research: no new hypothesis runs.
- Kept intact for reuse: the code, the data, the ledger, and the unopened validation (2017-21) and holdout
  (2022+) periods.
- The negative result is recorded in KNOWLEDGE (K1.8-K1.11, K4.13-K4.14), the H027 / H028 cards and
  R016-R019.

## Consequences
- STATUS shows the programme as paused. The validation budget (0 of 25) and the holdout look (0 of 1) are
  unspent.
- Restarting needs a new decision record. It must name a new information source or market, a staged budget,
  and a blind Codex consult first (see options (b) and (c) above).
- If the programme restarts with a new purchase, per-day quotes are required (Codex R017 #3).
