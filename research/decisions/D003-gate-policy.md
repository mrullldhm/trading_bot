---
id: D003
title: Gate policy (G8 scaled per account; recalibration only with owner approval)
status: decided
decided: 2026-10-16
approver: owner
updated: 2026-10-16
---

# D003 — Gate policy

## Context
G8 (p95 of the worst drop in the first 60 days of a simulated Combine ≤ $1,000 on 50K) was the wall for
every strategy. The audit showed G8 rejected a planted $150/trade edge that passed the simulated Combine
83% of the time (fail 14%). A rough planning Monte Carlo suggests G8 demands an after-cost annual Sharpe
of about 3, which is rare. The guide defines this gate as "Monte Carlo p95 drawdown < 50-60% of MLL".

Note: G8 is different from Topstep's Daily Loss Limit (D005). The DLL caps one day's loss; G8 caps the
multi-day drop in backtest simulations.

## Options
| Option | For | Against |
|---|---|---|
| Keep, recalibrate later with numbers | safe now; decision made with real data | possible wasted effort if G8 is unreachable |
| Fixed forever | simplest, safest | may make success impossible on 50K with 1 CL |
| Replace now with a Combine-odds rule | aligned with the real objective | chosen before evidence |

## Decision
**Keep, recalibrate later** (owner's choice):
1. All gates (G1-G9, V1-V10) stay the official bar.
2. G8 scales to 50% of each account's MLL: 50K $1,000, 100K $1,500, 150K $2,250.
3. After S001, if G8 looks too strict, Claude brings a written proposal with the numbers. Candidate
   alternative (from Codex, R001): the upper confidence bound of P(fail before pass) must be < 1%, with
   empirical block paths, observed intraday excursions, stressed costs, consistency rules and a $500
   operational reserve; p95 / p99 drops still reported.
4. Nothing changes without the owner's approval in a new decision record.

## Why
The gate exists for safety: backtests flatter. Changing it before measuring would be choosing the
answer first. S001 will show exactly what G8 costs in pass probability.

## Consequences
- `propfirm_research.combine` computes G8 per account at 50% of MLL.
- S001 must report, for each scenario, both G8 and the Combine pass / fail odds, so the trade-off is visible.
