---
id: STATUS
title: Programme status
status: living
updated: 2026-10-17
---

# Status

**Last updated:** 2026-10-17, session 3 ([journal/2026-10-17-03.md](journal/2026-10-17-03.md))

| | |
|---|---|
| Phase | **E — Hypotheses: active** on the staged settlement-flow track ([D008](decisions/D008-direction-after-s003.md)) |
| Active item | **Stage-1 data download** ([D010](decisions/D010-stage1-data-purchase.md), approved, cap $15): sample first, then TAS / signed flow / cross-energy data for 2015-16 |
| Waiting on owner | nothing (D010 approved 2026-10-17) |
| Validation families used | 0 / 25 |
| Programme holdout looks | 0 / 1 (2022+ unopened for this programme) |
| Tests | 428 passed (research 119, rest 309; hashed modules untouched) |

## Toolkit (`propfirm_research/`)
| Module | State |
|---|---|
| `paths`, `periods` (trading day, D001 periods) | done |
| `ledger` (append-only LEDGER.csv) | done |
| `prereg` (freeze once, open period once) | done; schema hardening pending (R012 Q4.3) |
| `data` (only reader of bars; firewall; access logging) | done for CL.v.0 / CL.v.1 bars; loaders for the D010 data next (R012 Q4.6) |
| `costs` (CL $24.02 / $44.02; `BASE_TICKS` / `STRESS_TICKS`) | done |
| `combine` (50K/100K/150K, DLL, `gate_g8` per D006; legacy drawdown check = `dd_d003_ok`) | done |
| `stats` (clustered t, Newey-West, BH, Wilson, MDE, variance ratios, stationary bootstrap, Romano-Wolf, SPA, simultaneous bounds) | done |
| `grid` (strict exits D009, `exit_missing`, `entry_ok` / `entry_contract`, roll-safe, MFE/MAE, planted drift) | done (R013) |
| `settlement` (settlement-window hypothesis harness; H025/H026 family) | done (R014, R015) |
| `studies/s001`-`s003` | done (validated; D009 note in each report) |
| `index` (rebuild INDEX.md) | done |

## Next actions (in order)
1. **Download stage 1 (D010)** with a new `propfirm_data` module (never `config.py`): line 1 sample
   ($0.04) first, check the aggressor side and the TAS price format; then lines 2-5, 7, 8 (line 6
   replaces line 5 if the side is missing). Batch jobs for whole ranges, per-day requests for the
   14:20-14:35 slices, budget guard at $15.
2. **Firewall loaders** for trades / statistics / related bars in `propfirm_research.data` (period checks,
   run token, ledger rows, synthetic tests); Codex review **R016** (also glance at the post-run harness
   edits noted at the end of R014).
3. **H027** (TAS / signed flow) and **H028** (cross-energy) cards, <= 4 variants each, frozen after Codex
   review; run on 2015-16 first with the settlement harness. Kill rule: wrong sign, gross <= 4.402 ticks,
   or discovery net edge < 2 x MDE. Only survivors justify buying 2010-14 (new decision).
4. **Before the first pre-registration** (R012 Q4): prereg schema (explicit combined statistic, variants,
   missing-bar policy, account / sizing, G9 neighbours, power inputs, trial count, exact costs); runtime
   data-hash check; frozen portfolio / account rule (owner decision); design-specific power simulation;
   dry run of the validation executable with atomic result writing.
5. Deferred minors (efficiency only): fold `odds` into `odds_many`; hoist repeated work in `grid.planted`;
   vectorise `stationary_bootstrap_indices`; cache strategies in S003.

## Phase map
| Phase | Status |
|---|---|
| A Setup | done |
| B Feasibility (S001) | done (validated) |
| C Atlas (S002) | done (validated) |
| D Ceiling (S003) | done (validated) |
| E Hypotheses | **active**: H025 / H026 parked (0 of 4 promoted, R015 exact); H027 / H028 next on new data; H029 parked |
| F-H | - |

## Key numbers so far
- Prior work: 1,389,977 configurations, 0 passed (prior-work/STRATEGIES-1-8.md).
- **S001 bar**: pass >= 50% / fail <= 25% needs after-cost annual Sharpe ~1.6-2.6 at the best size; with
  the D006 G8 rule ~2.2-2.4 (8-16 net ticks per trade on short windows).
- **Promotion bar (PROTOCOL §4.5)**: validation 2017-21 detects annual Sharpe ~1.42, so a discovery
  signal needs net Sharpe ~2.85 to be worth a validation family.
- **S002**: only settlement structure (continuation 2.6 gross ticks, decaying; 14:30-15:00 drift -2.2).
- **S003**: 0 of 432 model strategies beat costs; power 90% at 8 net ticks, 15% at 4.
- **H025 / H026 (2026-10-17)**: best variant (move filter) 5.85 gross ticks, net Sharpe 0.97, but
  9.5 / 5.9 / 1.6 by block and far below the power bar; H026 short 2.25 gross ticks (below cost). Both
  parked; no validation family spent.
- **D010 quotes**: TAS trades 2015-16 $0.40; CL trades 14:20-14:35 slices $7.60 (full sessions $117.80).
- Decisions this session: D008 (direction), D009 (strict exits), D010 (stage-1 purchase).
