---
id: STATUS
title: Programme status
status: living
updated: 2026-10-17
---

# Status

**Last updated:** 2026-10-17, session 4 ([journal/2026-10-17-04.md](journal/2026-10-17-04.md))

| | |
|---|---|
| Phase | **PAUSED** by the owner ([D011](decisions/D011-direction-after-stage1.md), 2026-10-17). Phase E ended: the settlement-flow track found nothing |
| Active item | none (paused). A restart needs a new decision record: a new information source or market, a staged budget, and a blind Codex consult first |
| Waiting on owner | check the Databento portal: actual stage-1 spend should be about $9.52 (manifest worst case $10.47, cap $15) |
| Validation families used | 0 / 25 |
| Programme holdout looks | 0 / 1 (2022+ unopened for this programme) |
| Tests | 538 passed (428 at entry + 110 new). Stage-1 evidence log: `data/research/stage1/test_evidence_20261017T140154Z.log` |

## Session 4 in one paragraph
- **Data.** The D010 stage-1 data was bought for about $9.5 (sample, TAS, statistics, RB/HO/BZ bars and CL
  mbp-1 slices; line 6 by the owner's choice after the sample).
- **Checks.** The data was converted with its raw hashes verified and audited by S004 (all 12 rules after the
  disclosed R017 amendments). It is read only through the new firewall loaders, which have per-file data and
  code hash checks.
- **Cards.** H027 (TAS / signed flow, 4 variants) and H028 (cross-energy, 3 variants) were frozen after Codex
  R016 (blind design), R017 (data, GO) and R018 (cards and harness, GO after six rounds).
- **Runs.** Each ran once on 2015-16: **0 of 7 survive** (five wrong-signed), and Codex R019 replicated it
  exactly.
- **Consequence.** No 2010-14 purchase. The owner decided D011: **pause**.

## Next actions
1. **Paused (D011).** Nothing runs until a new decision record. On a restart, read D011's options (b) and (c)
   first.
2. **Before any next purchase:** use per-day quotes and reservations instead of a sampled whole-line reservation
   (Codex R017 #3).
3. **Before the first pre-registration** (unchanged from R012 Q4):
   - an explicit combined statistic in the prereg schema;
   - a frozen portfolio / account rule (owner);
   - a design-specific power simulation;
   - a validation dry run.

   Per-file data and code hashes are now checked at `open_run`.
4. **Deferred minors:**
   - per-file metadata in the access rows (R017 #6);
   - fold `odds` into `odds_many`;
   - vectorise the bootstrap;
   - `h025_overlap` recomputes the whole H025 family.

## Toolkit (`propfirm_research/`, `propfirm_data/`)
| Module | State |
|---|---|
| `propfirm_data/stage1.py` | D010 paid downloader: reservation before every billed call; a cap that the manifest cannot raise; UNCERTAIN blocks spending; free recovery of complete files (R016, R017) |
| `propfirm_data/stage1_convert.py` | line-1 sample check; DBN -> parquet under `data/processed/stage1/` after verifying every raw hash against the purchase manifest; provenance manifest |
| `data` | the only reader of market data: bars, `load_trades`, `load_statistics`, `load_related`; per-file runtime hash check for protected periods; an intent row and one terminal row per access; `files_for`, `digest` |
| `prereg` | per-file data **and code** hashes; `open_run` checks both before writing its one-shot marker |
| `settlement` | H025/H026 (parked), H027/H028 (rejected at stage 1); stage-1 screen; atomic one-attempt marker |
| `studies/s004_stage1_data` | stage-1 data audit and acceptance gate (all 12 rules pass) |
| `paths`, `periods`, `ledger`, `costs`, `combine`, `stats`, `grid`, `index`, `studies/s001-s003` | done |

## Phase map
| Phase | Status |
|---|---|
| A-D | done (validated) |
| E Hypotheses | ended: H025 / H026 parked; **H027 / H028 rejected at stage 1**; H029 parked; H030-H032 ideas with low priors |
| Programme | **paused** (D011) |
| F-H | - |

## Key numbers so far
- Prior work: 1,389,977 configurations, 0 passed. S001 bar: annual Sharpe ~1.6-2.6 after costs.
- Promotion bar: a discovery net Sharpe of ~2.85 (validation MDE ~1.42).
- S003: 0 of 432 model strategies beat costs; power 90% at 8 net ticks, 15% at 4.
- H025 best: 5.85 gross ticks (1.6 in 2015-16), parked. H026: 2.25 gross ticks, parked.
- **H027 (2015-16):** TAS imbalance -1.9 / -1.8 gross ticks (wrong sign); outright flow +0.47 (t 0.3);
  unwind -3.6 (wrong sign, t -3.5).
- **H028 (2015-16):** -0.27 / -0.04 / -0.65 gross ticks over 249-475 trades.
- **Stage-1 data facts:** TAS side on ~99.8% of volume; CL side missing on ~7%; mbp-1 tape equals the bars.
  K1.8-K1.11.
- Decisions: D008, D009, D010 (+ the session-4 addendum), **D011 pause**.
