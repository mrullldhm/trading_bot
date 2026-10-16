---
id: S001
title: Feasibility frontier - what does passing actually require?
status: planned
period: discovery (noise shapes) + synthetic
created: 2026-10-16
updated: 2026-10-16
---

# S001 — Feasibility frontier

## Question
What after-cost performance must a CL strategy have to pass a Topstep Combine under the project's rules,
for each account (50K / 100K / 150K) and CL contract count, with the Daily Loss Limit on? And how strict
is G8 compared with the real pass / fail odds (input to the D003 proposal)?

## Data and method (fixed before running)
**Part A — parametric grid (no market data).** Day P&L drawn i.i.d. from a Student-t (df 3 and 5) and a
Normal with annual Sharpe SR ∈ {0.5, 1, 1.5, 2, 3, 4, 6} and daily sd ∈ {75, 150, 300, 500} $/day,
intraday low via Brownian bridge. Through `propfirm_research.combine` per account with the DLL on.

**Part B — real CL noise with planted edges (discovery days only).** For each trade template
(decision time ET → exit): 03:00→08:00, 09:00→10:00, 09:00→12:00, 09:00→16:05, 10:35→11:30, 14:00→14:30,
14:00→16:05, 14:35→16:05, 20:00→03:00 (roll days excluded):
1. on every discovery trading day, the gross P&L of a random-direction 1 CL trade (zero edge by
   construction) with real intraday path, MAE and costs ($24.02 base, $44.02 stress);
2. plant an edge of e net ticks per trade, e ∈ {0, 2, 4, 6, 8, 12, 16, 24, 32}, **into the price path**
   (R002): a linear drift in the trade's direction from entry (0) to exit (e ticks), so the exit, MAE,
   DLL and MLL all see the same deformed path; several seeds of direction / day sampling, with Monte Carlo
   uncertainty reported;
3. trade frequency: every day, or a random 50% / 25% of days (selective strategies);
4. contracts: 1 CL on 50K; 1-3 CL on 100K; 1-4 CL on 150K (within Topstep CL limits 6 / 9);
5. Combine simulation: day-level block bootstrap (5-day blocks), 2,000 attempts, 250 days, trailing MLL,
   55% consistency, DLL on; report pass %, fail %, median days to pass, p95 / p99 60-day drop, G8
   (50% of MLL), DLL-hit days, and the upper 95% bound of P(fail before pass).

**Required edge** per template / frequency / account / contracts = smallest e that meets each criterion:
(a) G8; (b) pass ≥ 50% and fail ≤ 25%; (c) Codex's candidate: upper bound of P(fail before pass) < 1%
with a $500 reserve. Then translate e into an information coefficient and an annual Sharpe.

**Checks.** `combine.py` reproduces `propsim.pass_probability` at 50K with the DLL off; with e = 0 the pass
rate sits near the zero-edge baseline (~25-40% before costs, lower after).

## Results
Pending.

## What it means
Pending. Will fill REQUIREMENTS §7 (target zone) and the D003 proposal.

## Caveats
Planted edges are constant per trade; real edges vary with regime. Random-direction noise keeps CL's
real fat tails and clustering only within 5-day blocks.

## Reproduce
`python -m propfirm_research.studies.s001_feasibility` (to be written).

## Codex review / replication
Planned: R004 (independent re-computation of 3-5 headline cells).
