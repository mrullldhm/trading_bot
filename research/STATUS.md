---
id: STATUS
title: Programme status
status: living
updated: 2026-10-17
---

# Status

**Last updated:** 2026-10-17, session 2 ([journal/2026-10-16-02.md](journal/2026-10-16-02.md))

| | |
|---|---|
| Phase | **B — Feasibility: done.** S001 VALIDATED (Codex review R004, replication R005 5/5) |
| Active item | **S002 market atlas** (next) |
| Waiting on owner | **D006**: G8 recalibration proposal (recommended option 2: pass >= 50% and UCB P(fail) <= 10%, stress costs, $500 reserve) |
| Validation families used | 0 / 25 |
| Programme holdout looks | 0 / 1 (2022+ unopened for this programme) |
| Tests | 368 passed (research 59, rest 309; hashed modules untouched) |

## Toolkit (`propfirm_research/`)
| Module | State |
|---|---|
| `paths`, `periods` (trading day, D001 periods) | done |
| `ledger` (append-only LEDGER.csv) | done |
| `prereg` (freeze once, open period once) | done |
| `data` (only reader of bars; firewall; access logging) | done; real-data smoke test OK (2.2M discovery minutes in 17 s) |
| `costs` (CL $24.02 / $44.02) | done |
| `combine` (50K/100K/150K, DLL with liquidation slip, G8 at 50% MLL; equals propsim at 50K/no DLL; `odds_many` batched, account-level drop) | done |
| `stats` (clustered t, Newey-West, BH, Wilson, MDE, variance ratio, t quantile) | done; Romano-Wolf / SPA / stationary bootstrap still to add (needed by S003 and validation) |
| `grid` (decision-time windows, flat 16:05, roll-safe, MFE/MAE, planted path drift) | done |
| `studies/s001_feasibility` | done (9 min run) |
| `index` (rebuild INDEX.md) | done |

## Next actions (in order)
1. **Owner decides D006** (G8). Until then G8 stays as in D003.
2. **S002** market atlas; Codex replication (R006); update KNOWLEDGE and BACKLOG; rank ideas against
   the S001 bar (IC >= 0.2 / Sharpe >= 2 at 1 CL).
3. Add Romano-Wolf / SPA / stationary bootstrap to `stats`; **S003** ceiling (owner approval for scikit-learn).
4. Before the first validation run: decision record with the frozen portfolio-building rule (PROTOCOL §2).
5. Deferred minors from the S001 production-eng gate: fold `odds` into `odds_many`; hoist repeated work in
   `grid.planted` across slips (efficiency only).

## Phase map
| Phase | Status |
|---|---|
| A Setup | done |
| B Feasibility (S001) | done (validated) |
| C Atlas (S002) | next |
| D Ceiling (S003) | planned |
| E Hypotheses | 16 ideas in BACKLOG, none started |
| F-H | - |

## Key numbers so far
- Prior work: 1,389,977 configurations, 0 passed (prior-work/STRATEGIES-1-8.md).
- **S001 bar**: pass >= 50% / fail <= 25% needs after-cost annual Sharpe ~1.6-2.6 at the best size (1 CL,
  100K/150K, short quiet window) and IC ~0.2 per trade; with G8 it needs Sharpe 3.1+. Prior strategies: ~0.
- G8 alone is met by accounts that barely trade (D006).
- Zero-edge 1 CL every day on 50K: pass 12-19%, fail 81-88%.
