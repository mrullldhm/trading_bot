---
id: D008
title: Direction after S003 - staged settlement-flow data track
status: decided
decided: 2026-10-17
approver: owner
updated: 2026-10-17
---

# D008 — Direction after S003: settlement-flow data, bought in stages

## Context
- S001, S002 and S003 are VALIDATED (R005, R009, R011). The 1-minute CL bars hold no edge that beats
  costs; S003 can only rule out edges of 8+ net ticks (power 90% at 8, 15% at 4), while the Combine
  needs 4-8 net ticks on short windows (8-16 under the D006 G8 rule). Kill criteria 1-2 (PROTOCOL §4.7)
  do not formally hold: five out-of-sample years are too few to prove a negative.
- The only measured structure is around settlement (S002 K4.4, K4.5), below cost and decaying.
- PROTOCOL §4.5: validation 2017-2021 detects an annual Sharpe of ~1.42; promotion needs the MDE to be
  at most half the discovery effect, i.e. a discovery net Sharpe of ~2.85.
- Codex's blind consult [R012](../reviews/R012-codex-blind-phase-e.md) and Claude's own analysis both
  recommended new information about settlement flow: TAS (trade-at-settlement, Globex `CLT`, in
  Databento GLBX.MDP3 since 2010-06-06) and aggressor-signed trade flow, bought in stages.

## Options
| Option | For | Against |
|---|---|---|
| (a) structural settlement ideas on existing data only | free | Codex odds ~3%; the power rule needs a 3-4x larger conditional edge than the naive one |
| **(b) new CL information about settlement flow, staged** | the only route with information S003 never had; sits where S002 found structure; small first purchase | costs money; low prior all the same (Codex ~12%, Claude a few percent) |
| (c) pause | no cost | no chance of success while paused |
| (d) another Topstep market | literature on equity-index intraday momentum | full reset of S001-S003; D004 change; Codex ~8% and ranks it below pausing |

## Decision
Owner, 2026-10-17 (session 3 planning): **(b), staged**, plus one cheap H025 / H026 discovery run with
Codex's four frozen variants (R012 Q3).
1. **API key:** Claude may run free Databento calls with the owner's key: `metadata.*` (get_cost,
   get_record_count, get_dataset_range, list_schemas, ...) and `symbology.resolve`. No billed call
   (`timeseries.get_range`, `batch.submit_job`) without an approved line in a purchase decision (D010).
2. **Purchases:** decided per dataset after exact quotes; no blanket budget.
3. **Staging:** 2015-2016 first (the decay-guard block). Earlier discovery years (2010-2014) only if a
   2015-2016 signal survives its kill rule (right sign, gross edge above the 4.402-tick stress cost,
   discovery net edge >= 2 x MDE). Validation years (2017-2021) only after a frozen pre-registration.
4. New data are inputs only: trading stays CL contracts (D004 unchanged).

## Why
Every idea built from OHLCV features at these decision times is already inside the S003 search space,
which found nothing; repeating that space cannot help. Settlement flow is new information tied to the
one place CL shows structure, and the first stage is small enough to stop cheaply if 2015-2016 shows
nothing. Running H025 / H026 once closes the existing-data settlement question with real numbers and
builds the harness the new signals will reuse.

## Consequences
- New data enter only through firewall loaders in `propfirm_research.data`, reviewed by Codex before
  any analysis (R012 Q4.6).
- Hypotheses from R012 enter the BACKLOG as H027-H032.
- Revisit when stage 1 is done: if every stage-1 signal fails its kill rule, the owner decides between
  deeper data (e.g. order book), another market, or a pause, with the kill-criteria evidence.
