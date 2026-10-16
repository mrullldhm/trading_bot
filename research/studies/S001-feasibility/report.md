---
id: S001
title: Feasibility frontier - what does passing actually require?
status: validated
period: discovery (noise shapes) + synthetic
created: 2026-10-16
updated: 2026-10-17
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

**Amendments before the headline run** (Codex review [R004](../../reviews/R004-codex-s001-code-review.md),
made before any headline number was seen):
- Edge e = net ticks per trade after **base** costs; gross drift g = e + 2.402 ticks. Stress rows use the
  same drift with stress fills (stress-net edge = e - 2). A g = 0 row is the zero-edge baseline.
- The day's low includes the trade's result (`min(MAE, P&L, 0)`): a bad exit price now hits the DLL / MLL.
- Every trading day is kept; days where a template cannot trade (roll, expiry, short session) are no-trade
  days, not deleted days.
- 20 seeds = 10 antithetic pairs (each pair's random-direction P&L cancels exactly), 1,000 attempts each.
  Criterion (c) uses the larger of the pooled Wilson bound and a one-sided t bound over the 10 pair-level
  fail rates (the pair, not the attempt, is the independent unit).
- Student-t days are a normal scale mixture so the intraday bridge gets each day's own volatility.
- Required edge is reported as `first` (smallest e meeting the criterion) and `stable` (holds at every
  larger e too). Sharpe from pooled moments; IC = correlation of direction with the deformed return.
- G8 keeps propsim's drawdown convention; the account-level drop (stopped at the MLL line) is reported too.

## Results
Run 2026-10-16 (LEDGER S001-013 Part B; Part A rerun S001-014 after R005; outputs `data/research/s001/<stamp>_full/` with
`manifest.json`; tables in this folder: `partA.csv`, `partB_summary.csv`, `required_edge.csv`).
1,685 discovery sessions; 1,617-1,684 eligible per template. Runtime 9 min.
**Status: VALIDATED** by Codex replication [R005](../../reviews/R005-codex-s001-replication.md): 5 of 5
cells match (Part A after a moment-matching fix).

### 1. Zero edge loses fast
With no edge (random direction, base costs), 1 CL, every day: pass 12-19%, fail 81-88% on 50K. The
zero-edge pass rate is luck, not skill: it is the floor every real result must beat.

### 2. Required edge, criterion (b) pass >= 50% and fail <= 25% (base costs, `stable` threshold)
Net ticks per trade after costs (`-` = not reached even at 32 ticks):

| Template | 50K x1 | 100K x1 | 100K x2 | 150K x1 | 150K x2 |
|---|---|---|---|---|---|
| 03:00-08:00 | 24 | 16 | 24 | 12 | 24 |
| 09:00-10:00 | 16 | 12 | 24 | 8 | 16 |
| 09:00-12:00 | - | 32 | - | 24 | - |
| 09:00-16:05 | - | - | - | 32 | - |
| 10:35-11:30 | 12 | 12 | 16 | 6 | 12 |
| 14:00-14:30 | 8 | 6 | 12 | 4 | 8 |
| 14:00-16:05 | 12 | 8 | 16 | 6 | 12 |
| 14:35-16:05 | 4 | 4 | 6 | 4 | 4 |
| 20:00-03:00 | 12 | 8 | 16 | 6 | 12 |

(trade every eligible day; 50% / 25% frequency need the same or more ticks per trade.)

In plain terms, at the required edge, **annual Sharpe needed (after costs) is at least 1.6-2.6 for the
best size of each template, usually 3-7**, and the **per-trade IC (correlation of the call with the
move) is at least 0.17-0.3**. Published intraday signals are usually IC 0.02-0.05.
- More contracts never help: each extra CL raises the needed edge (the MLL does not grow with size).
- 150K x1 needs the least edge almost everywhere (most room per $ of noise), but takes longest.
- Short, quiet windows need fewer ticks (14:35-16:05: 4 ticks; 14:00-14:30: 4-8); long holds need many
  (09:00-16:05: 32+), because the noise grows with time held while the planted edge is per trade.

### 3. G8 (p95 60-day drop <= 50% of MLL)
Met in only 50 of 1,944 base-cost cells; 39 of them also pass (b). Every cell that meets both needs an
annual **Sharpe of 3.1 or more** (IC 0.43+). **8 cells meet G8 while passing less than 20% of the time**:
G8 is easiest when the account barely moves (Part A: 150K, SR 0.5, sd $75/day meets G8 and passes ~0%).
G8 measures calm, not success.

### 4. Codex candidate rule (c): UCB of P(fail) < 1% with a $500 reserve
Met in 58 cells; 4 of them pass < 20% (e.g. 14:35-16:05, 25%, 150K x1, e = 4: pass 0.1%, fail 0.5%: the
account just runs out of days). With pass >= 50% added, the cheapest cells need Sharpe 3.1-3.9.

### 5. Part A (parametric, DLL on, minimum annual Sharpe on the grid {0.5..6})
| sd $/day | (b) 50K | (b) 100K | (b) 150K | G8 50K | G8 100K | G8 150K |
|---|---|---|---|---|---|---|
| 75 | 3 | 6 | >6 | 1.5-2 | 0.5 | 0.5 |
| 150 | 1.5 | 3 | 4 | >6 | 4 to >6 | 1-1.5 |
| 300 | 3 | 2 | 2 | >6 | >6 | 6 to >6 |
| 500 | 4-6 | 3-4 | 3 | >6 | >6 | >6 |

Fat tails (t5, t3 with per-day volatility) change these by at most one grid step. Note the opposite
directions: for (b) small accounts want low sd and big accounts want more sd (the target must be reached
in 250 days); for G8 everyone wants low sd.

## What it means
1. **The bar is about 2 or more after-cost annual Sharpe at the best size, and IC ~0.2 per trade.**
   Prior strategies 1-8 were near 0 out of sample. A new idea must look like this *before* costs and
   selection haircuts, or it is not worth testing on validation data.
2. **Use 1 contract; prefer 150K or 100K; prefer short, quiet windows.** Size is the enemy, not the friend.
3. **G8 and rule (c) both reward inactivity** when used alone. Either must be paired with a pass-rate
   floor. This is the input for the D003 proposal (decision D006 draft).
4. REQUIREMENTS §7 now holds the real-data target zone.

## Caveats
Planted edges are constant per trade; real edges vary with regime. Random-direction noise keeps CL's
real fat tails and clustering only within 5-day blocks.

## Reproduce
`.venv/bin/python -m propfirm_research.studies.s001_feasibility` (both parts, ~9 min; `--part A|B`, `--quick`).

## Codex review / replication
- [R004](../../reviews/R004-codex-s001-code-review.md): code review before the run (2 critical, 5 major, 3 minor; 9 fixed, 1 disagreed).
- [R005](../../reviews/R005-codex-s001-replication.md): independent replication of 5 cells: VALIDATED.
