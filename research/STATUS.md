---
id: STATUS
title: Programme status
status: living
updated: 2026-10-16
---

# Status

**Last updated:** 2026-10-16, session 1 ([journal/2026-10-16-01.md](journal/2026-10-16-01.md))

| | |
|---|---|
| Phase | **A — Setup: done.** Docs, protocol review R002, toolkit + code review R003 (all fixed), production-eng gate PASS |
| Active item | **S001 feasibility frontier** (next) |
| Waiting on owner | nothing right now (D003 proposal comes after S001) |
| Validation families used | 0 / 25 |
| Programme holdout looks | 0 / 1 (2022+ unopened for this programme) |
| Tests | research tests 44 passed; existing suite 334 passed (hashed modules untouched) |

## Toolkit (`propfirm_research/`)
| Module | State |
|---|---|
| `paths`, `periods` (trading day, D001 periods) | done |
| `ledger` (append-only LEDGER.csv) | done |
| `prereg` (freeze once, open period once) | done |
| `data` (only reader of bars; firewall; access logging) | done; real-data smoke test OK (2.2M discovery minutes in 17 s) |
| `costs` (CL $24.02 / $44.02) | done |
| `combine` (50K/100K/150K, DLL with liquidation slip, G8 at 50% MLL; equals propsim at 50K/no DLL) | done |
| `stats` (clustered t, Newey-West, BH, Wilson, MDE, variance ratio) | done; Romano-Wolf / SPA / stationary bootstrap still to add (needed by S003 and validation) |
| `grid` (decision-time windows, flat 16:05, roll-safe, MFE/MAE) | done; path-drift planting for S001 still to add |
| `index` (rebuild INDEX.md) | done |

## Next actions (in order)
1. **S001** feasibility frontier (write `studies/s001_feasibility.py`, plant edges into the path per
   R002 #2); Codex replication (R004); fill REQUIREMENTS §7; bring the D003 proposal to the owner.
2. **S002** market atlas; Codex replication (R005); update KNOWLEDGE and BACKLOG.
3. Add Romano-Wolf / SPA / stationary bootstrap to `stats`; **S003** ceiling (owner approval for scikit-learn).
4. Before the first validation run: decision record with the frozen portfolio-building rule (PROTOCOL §2).

## Phase map
| Phase | Status |
|---|---|
| A Setup | done |
| B Feasibility (S001) | next |
| C Atlas (S002) | planned |
| D Ceiling (S003) | planned |
| E Hypotheses | 16 ideas in BACKLOG, none started |
| F-H | - |

## Key numbers so far
- Prior work: 1,389,977 configurations, 0 passed (prior-work/STRATEGIES-1-8.md).
- Rough feasibility: workable Combine setups need an after-cost annual Sharpe of ~2-3+ (REQUIREMENTS §7).
- Discovery smoke test: a 09:00-10:00 ET hour on 1 CL has a standard deviation of 49 ticks ($490).
