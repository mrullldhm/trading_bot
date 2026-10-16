---
id: STATUS
title: Programme status
status: living
updated: 2026-10-17
---

# Status

**Last updated:** 2026-10-17, session 2 ([journal/2026-10-16-02.md](journal/2026-10-16-02.md), [journal/2026-10-17-01.md](journal/2026-10-17-01.md))

| | |
|---|---|
| Phase | **C — Atlas: done.** S001 VALIDATED (R004, R005); S002 VALIDATED (R007 review, R008 re-check, R009 replication 5/5) |
| Active item | **S003 ceiling** (next; needs the owner's scikit-learn approval) |
| Waiting on owner | **D006** (G8 proposal, recommended option 2) and **scikit-learn** approval for S003 |
| Validation families used | 0 / 25 |
| Programme holdout looks | 0 / 1 (2022+ unopened for this programme) |
| Tests | 383 passed (research 74, rest 309; hashed modules untouched) |

## Toolkit (`propfirm_research/`)
| Module | State |
|---|---|
| `paths`, `periods` (trading day, D001 periods) | done |
| `ledger` (append-only LEDGER.csv) | done |
| `prereg` (freeze once, open period once) | done |
| `data` (only reader of bars; firewall; access logging) | done; real-data smoke test OK (2.2M discovery minutes in 17 s) |
| `costs` (CL $24.02 / $44.02) | done |
| `combine` (50K/100K/150K, DLL with liquidation slip, G8 at 50% MLL; equals propsim at 50K/no DLL; `odds_many` batched, account-level drop) | done |
| `stats` (clustered t, Newey-West, BH, Wilson, MDE, variance ratio (fixed R007) + day-clustered VR, t quantile / p) | done; Romano-Wolf / SPA / stationary bootstrap still to add (needed by S003 and validation) |
| `grid` (decision-time windows, flat 16:05, roll-safe, MFE/MAE, planted path drift) | done |
| `studies/s001_feasibility` | done (9 min run) |
| `studies/s002_atlas` | done (~70 s run) |
| `index` (rebuild INDEX.md) | done |

## Next actions (in order)
1. **Owner:** decide D006 (G8); approve or refuse scikit-learn for S003.
2. Add Romano-Wolf / SPA / stationary bootstrap to `stats` (no approval needed).
3. **S003** ceiling (which decision times hold any predictability), Codex review + replication.
4. Then phase E: first hypothesis card from the post-S002 ranking (BACKLOG): H025 settlement
   continuation (conditioned) is the only idea with a measured base; it is decaying, so low prior.
5. Before the first validation run: decision record with the frozen portfolio-building rule (PROTOCOL §2).
6. Deferred minors (efficiency only): fold `odds` into `odds_many`; hoist repeated work in `grid.planted`.

## Phase map
| Phase | Status |
|---|---|
| A Setup | done |
| B Feasibility (S001) | done (validated) |
| C Atlas (S002) | done (validated) |
| D Ceiling (S003) | next (scikit-learn approval) |
| E Hypotheses | 26 ideas in BACKLOG (8 blind from Codex R006, 2 from S002), ranked after S002 |
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
