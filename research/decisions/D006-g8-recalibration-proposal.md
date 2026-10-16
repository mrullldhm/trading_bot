---
id: D006
title: Proposal - replace G8 alone with a Combine-odds gate (pass floor + fail bound)
status: proposed
decided:
approver: owner (pending)
updated: 2026-10-17
---

# D006 — Proposal: recalibrate G8 (D003 step 3)

**Nothing changes until the owner approves this file.** Until then G8 stays as in D003.

## Context
D003 kept G8 (p95 of the worst drop in the first 60 days <= 50% of the account's MLL) and asked for a
written proposal with numbers after S001. S001 ([report](../studies/S001-feasibility/report.md),
validated by Codex in R005) gives those numbers:

| Fact from S001 | Number |
|---|---|
| Base-cost cells (template x frequency x size x edge) | 1,944 |
| Cells meeting G8 | 50 (2.6%) |
| ...of which pass the Combine less than 20% of the time | 8 |
| Cheapest cell meeting G8 **and** pass >= 50% | annual Sharpe 3.1 (stress costs: 3.3) |
| Cheapest cell with pass >= 50% and fail <= 25% (no G8) | Sharpe 1.6 (stress 1.6) |

Two problems with G8 alone:
1. **It rewards inactivity.** An account that barely moves never draws down and never passes
   (Part A: 150K, Sharpe 0.5, $75/day: G8 met, pass ~0%). G8 measures calm, not success.
2. **It roughly doubles the bar.** Sharpe 3.1+ versus ~1.6-2.0 for a good chance of passing.

Codex's candidate (R001: upper bound of P(fail) < 1% with a $500 reserve) has the same first flaw: 4 of
its 58 qualifying cells pass < 20% (the account runs out of days). Its cost with a pass floor: Sharpe 3.1+.

## Options (all with a $500 reserve, DLL on; numbers = cheapest qualifying S001 cell, after costs)
| Option | Rule | Base Sharpe | Stress Sharpe | Qualifying cells (base) |
|---|---|---|---|---|
| 0 Keep | G8 only (status quo) | 3.1 if pass also wanted; G8 alone can be met by losers | 3.3 | 50 |
| 1 Strict | pass >= 50% and UCB95 P(fail) < 1% (Codex + floor) | 3.1 | 3.3 | 54 |
| **2 Middle (recommended)** | **pass >= 50% and UCB95 P(fail) <= 10%**, stress costs | 2.2 | 2.2 | 297 |
| 3 Loose | pass >= 50% and UCB95 P(fail) <= 20% | 2.0 | 2.0 | 459 |

UCB95 P(fail) = the larger of the Wilson bound over all attempts and the one-sided t bound over
independent outer draws (R004 #2). p95 / p99 60-day drops stay **reported** (not gated).

## Recommendation: option 2
- **Why a pass floor:** the goal is to pass; any risk-only gate can be gamed by doing nothing.
- **Why a fail bound and not a drawdown bound:** a failed Combine costs the fee and time, not the account
  balance. What matters is how often we fail before passing, which is exactly P(fail).
- **Why 10% and not 1%:** 1% asks for Sharpe 3+, which no strategy here has come near out of sample. 10%
  with stress costs and a $500 reserve already builds in a safety margin; backtest optimism is handled
  separately by validation, the holdout and the stress-cost requirement.
- **Why stress costs:** G4 already says a strategy must survive worse fills; the gate should be measured there.
- Option 2 keeps the bar high (Sharpe ~2.2+, IC ~0.3 per trade): it does not make passing easy, it stops
  rejecting strategies for being active.

## What would change if approved
- REQUIREMENTS G8 row: replaced by the option-2 rule; p95 / p99 drops still reported.
- `propfirm_research.combine` already reports everything needed (`pass`, `fail`, `fail_ucb95`,
  account-level and propsim-style drops); a helper `gate_g8v2` would be added with tests.
- The frozen propsim / old gate code is not touched; old results stay judged by the old rule.

## Owner decision
- [ ] Option 0 / 1 / 2 / 3 / other: ______
- Date:
