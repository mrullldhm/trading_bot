---
id: D004
title: Sizing scope - CL contracts only, 50K / 100K / 150K Combines
status: decided
decided: 2026-10-16
approver: owner
updated: 2026-10-16
---

# D004 — Sizing scope

## Context
1 CL on a 50K account makes the 60-day p95 drop $2,300-3,100, far above G8. Two ways to shrink risk
relative to the loss limit: smaller contracts (MCL micro, 1/10 of CL) or bigger accounts.

## Options
| Option | For | Against |
|---|---|---|
| 50K + micro (MCL) | fine sizing on the cheapest Combine | costs ~55% more per tick-equivalent ($3.72 vs $2.40 per tick of CL exposure); micro replays of strategies 1-5 lost their edge to fees |
| 50K + 1 CL | cheapest execution | G8 almost unreachable |
| 100K / 150K Combines | 1 CL is a smaller share of a bigger loss limit ($3,000 / $4,500) at CL's lower cost | higher monthly fee; target/MLL is 2.0 instead of 1.5 (relatively more profit needed) |

## Decision
**CL contracts only, on 50K (1 CL), 100K and 150K Combines** (owner's choice). Larger accounts may use
more than 1 CL within Topstep's CL limit (6 on 100K, 9 on 150K; check TopstepX live). No micros.

## Why
The owner prefers CL's cheaper execution; bigger accounts give the room that micros would have given.

## Consequences
- Cost model: CL only ($24.02 base, $44.02 stress per round trip).
- S001 evaluates every account size with 1..N CL.
- Remember that a bigger account needs relatively more profit (target/MLL 2.0 vs 1.5).
- Revisit only if S001 shows CL-only sizing makes every realistic strategy infeasible.
