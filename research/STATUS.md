---
id: STATUS
title: Programme status
status: living
updated: 2026-10-17
---

# Status

**Last updated:** 2026-10-17, session 2 ([journal/2026-10-16-02.md](journal/2026-10-16-02.md), [journal/2026-10-17-01.md](journal/2026-10-17-01.md), [journal/2026-10-17-02.md](journal/2026-10-17-02.md))

| | |
|---|---|
| Phase | **D — Ceiling: done.** S001, S002, S003 all VALIDATED by Codex (S003: R010 review, R011 replication) |
| Active item | **Owner decision on direction** (phase E, see Next actions) |
| Waiting on owner | (1) direction after S003; (2) flat-exit convention (R011): strict 16:05 bar before validation runs |
| Validation families used | 0 / 25 |
| Programme holdout looks | 0 / 1 (2022+ unopened for this programme) |
| Tests | 397 passed (research 88, rest 309; hashed modules untouched) |

## Toolkit (`propfirm_research/`)
| Module | State |
|---|---|
| `paths`, `periods` (trading day, D001 periods) | done |
| `ledger` (append-only LEDGER.csv) | done |
| `prereg` (freeze once, open period once) | done |
| `data` (only reader of bars; firewall; access logging) | done; real-data smoke test OK (2.2M discovery minutes in 17 s) |
| `costs` (CL $24.02 / $44.02) | done |
| `combine` (50K/100K/150K, DLL with liquidation slip, G8 at 50% MLL; equals propsim at 50K/no DLL; `odds_many` batched, account-level drop) | done |
| `stats` (clustered t, Newey-West, BH, Wilson, MDE, variance ratio + day-clustered VR, t quantile / p, stationary bootstrap, Romano-Wolf, SPA, simultaneous upper bounds) | done |
| `grid` (decision-time windows, flat 16:05, roll-safe, MFE/MAE, planted path drift) | done |
| `studies/s001_feasibility` | done (9 min run) |
| `studies/s002_atlas` | done (~70 s run) |
| `studies/s003_ceiling` | done (14 min run; scikit-learn 1.9.1, D007) |
| `combine.gate_g8` | G8 per D006 (pass >= 50%, UCB P(fail) <= 10%, stress costs, $500 reserve, outer resamples) |
| `index` (rebuild INDEX.md) | done |

## Next actions (in order)
1. **Owner: choose the direction** (Claude's recommendation first):
   a. **Phase E on structural ideas only**: H025 settlement continuation (conditioned) and H026, each
      pre-registered with a power plan (validation 2017-2021); low prior, cheap.
   b. **New information**: data the ceiling did not have (e.g. CME settlement / TAS volume, options
      open interest, EIA consensus surprises, other markets such as Brent / RBOB / HO). Data purchases
      need owner approval.
   c. Pause CL intraday research (the measured evidence says the easy edges are not there).
2. **Owner: flat-exit convention** (R011 open item): adopt the strict 16:05 bar in `grid` before any
   validation run (recommended).
3. Before the first validation run: decision record with the frozen portfolio-building rule (PROTOCOL §2).
4. Deferred minors (efficiency only): fold `odds` into `odds_many`; hoist repeated work in `grid.planted`;
   vectorise `stationary_bootstrap_indices`; cache strategies in S003.

## Phase map
| Phase | Status |
|---|---|
| A Setup | done |
| B Feasibility (S001) | done (validated) |
| C Atlas (S002) | done (validated) |
| D Ceiling (S003) | done (validated) |
| E Hypotheses | 26 ideas in BACKLOG, ranked after S002 and S003; waiting on direction |
| F-H | - |

## Key numbers so far
- Prior work: 1,389,977 configurations, 0 passed (prior-work/STRATEGIES-1-8.md).
- **S001 bar**: pass >= 50% / fail <= 25% needs after-cost annual Sharpe ~1.6-2.6 at the best size (1 CL,
  100K/150K, short quiet window) and IC ~0.2 per trade; with G8 it needs Sharpe 3.1+. Prior strategies: ~0.
- G8 alone is met by accounts that barely trade (D006).
- Zero-edge 1 CL every day on 50K: pass 12-19%, fail 81-88%.
- **S002**: no discovery effect clears the bar. Strongest: settlement continuation (IC 0.12, gross 2.6
  ticks, decaying to 0.4 by 2015-16) and a -2.2 tick 14:30-15:00 drift (every year, below cost).
- CL0 / CL1 spread signals and EIA direction: nothing.
- **S003**: 0 of 432 model strategies beat costs (RW min p 0.96, SPA 0.87); nulls clean; power 90% at
  8 net ticks, 15% at 4: the data rule out 8+ tick edges only.
- **D006 decided** (option 2) and **D007** (scikit-learn 1.9.1) on 2026-10-17.
