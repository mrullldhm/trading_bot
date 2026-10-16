---
id: R005
title: Codex independent replication of 5 S001 headline cells
status: resolved
item: S001
codex_job: task-mvb5wkr0-ibvxgr
created: 2026-10-16
updated: 2026-10-17
---

# R005 — Codex replication of S001

## Request (summary)
Replication mode (`WRITE only under research/replications/S001/`). Recompute 5 cells from the raw parquet
with Codex's own code and own random seeds, without importing `propfirm_research`, and without seeing
Claude's numbers. Tolerance set in the plan: pass / fail within 3 points, p95 drop within 5%.
Code: `research/replications/S001/` (README, replicate.py, verify.py).

## Codex output (verbatim)
Replication completed with independent code and seeds. No `propfirm_research` modules were imported.

### Headline results

| Cell | Pass | Fail | p95 60-day drop | G8 | Median pass days | DLL-hit days | Eligible days | Trades | Mean day P&L | Annual Sharpe |
|---|---:|---:|---:|---|---:|---:|---:|---:|---:|---:|
| 1 — 14:00→14:30, 100%, 50K, e=8 | 76.47% | 23.54% | $2,460 | Fail | 29 | 1.810% | 1,617 | 1,617 | $76.77 | 3.345 |
| 2 — 09:00→10:00, 50%, 150K, e=8 | 62.37% | 17.21% | $4,471 | Fail | 153 | 0.0208% | 1,684 | 854.9 avg. | $40.59 | 1.827 |
| 3 — 14:35→flat, 25%, 150K, e=4, R=$500 | 0.02% | 0.26% | $1,549 | Pass | 226.5¹ | 0% | 1,617 | 398.0 avg. | $9.45 | 1.422 |
| 4 — 09:00→10:00, 100%, 50K, g=0 | 16.62% | 83.38% | $2,844 | Fail | 22 | 6.261% | 1,684 | 1,684 | −$24.01 | −0.773 |
| 5 — Normal, SD=$150, SR=2, 50K | 80.72% | 12.06% | $1,809 | Fail | 117 | 0% | 50,000² | 50,000² | $19.24 | 2.034 |

G8 limits were $1,000 for 50K and $2,250 for 150K.  
¹ Only four pooled attempts passed cell 3, so its median is very unstable.  
² Synthetic source pool rather than market sessions.

### Direction-draw spread

Ranges are across ten independent antithetic pairs, with 2,000 attempts per pair.

| Cell | Trades | Pass | Fail | p95 drop | Median pass days | Mean day P&L | Sharpe |
|---|---:|---:|---:|---:|---:|---:|---:|
| 1 | 1,617 | 74.00–78.75% | 21.25–26.00% | $2,403–$2,542 | 27.5–30 | $76.77 | 3.345 |
| 2 | 823–908 | 59.35–65.50% | 14.45–19.25% | $4,247–$4,550 | 146–159 | $39.07–$43.11 | 1.771–1.913 |
| 3 | 377–424 | 0–0.10% | 0–0.70% | $1,336–$1,800 | 221.5–226.5¹ | $8.95–$10.07 | 1.329–1.546 |
| 4 | 1,684 | 15.20–18.30% | 81.70–84.80% | $2,802–$2,896 | 21–23 | −$24.01 | −0.773 |

Zero-edge per-trade gross return SD:

- 14:00→14:30: **37.158 ticks**
- 09:00→10:00: **49.295 ticks**
- 14:35→flat: **22.120 ticks**

### Method and artifacts

I read 2,227,364 `CL.v.0` minute bars covering 1,685 CME trading days. Roll and expiry cutoffs were reconstructed from raw front-month transitions and raw expiration timestamps. I used only `propfirm_backtest.orb_engine.local_tmin` and `short_days` for timezone conversion and the scheduled CME short-day calendar.

Part B pooled 20 independent-seed direction streams—ten shared-mask antithetic pairs—with 1,000 attempts per stream. Part A used 50,000 independently generated Normal/bridge days and 20,000 attempts.

Files:

- [README.md](/home/mrullldhm/personal/propfirm/research/replications/S001/README.md)
- [replicate.py](/home/mrullldhm/personal/propfirm/research/replications/S001/replicate.py)
- [verify.py](/home/mrullldhm/personal/propfirm/research/replications/S001/verify.py)
- [results.json](/home/mrullldhm/personal/propfirm/data/research/replications/S001/results.json)
- [pair_metrics.csv](/home/mrullldhm/personal/propfirm/data/research/replications/S001/pair_metrics.csv)

Mechanical verification checks passed.

### Convention concerns

- I followed the propsim G8 convention, but still disagree with recording the full strategy-path low after the MLL has already been breached. It can overstate the drawdown actually experienced before account liquidation.
- The stated “no entry during the final five minutes before flat” rule is stricter than Claude’s current `grid.py` check, which only requires entry before flat. I implemented the stated rule. It does not affect these requested cells because the relevant expiry and short-session windows are already invalid.

Codex session ID: 01a14578-d45b-7603-8d15-412359dc9bb3
Resume in Codex: codex resume 01a14578-d45b-7603-8d15-412359dc9bb3

## Claude's response
### Comparison (Claude = run S001-013 Part B, S001-014 Part A after the fix below)
| Cell | Pass C / X | Fail C / X | p95 drop C / X | Days C / X | Mean day C / X | Sharpe C / X | Match |
|---|---|---|---|---|---|---|---|
| 1 14:00-14:30, 100%, 50K, e=8 | 76.7 / 76.5 | 23.3 / 23.5 | 2,451 / 2,460 | 29 / 29 | 76.77 / 76.77 | 3.34 / 3.35 | yes |
| 2 09:00-10:00, 50%, 150K, e=8 | 61.6 / 62.4 | 18.4 / 17.2 | 4,423 / 4,471 | 155 / 153 | 39.9 / 40.6 | 1.81 / 1.83 | yes |
| 3 14:35-flat, 25%, 150K, e=4, R500 | 0.09 / 0.02 | 0.50 / 0.26 | 1,610 / 1,549 | (few passes) | 9.51 / 9.45 | 1.39 / 1.42 | yes |
| 4 09:00-10:00, 100%, 50K, g=0 | 16.5 / 16.6 | 83.5 / 83.4 | 2,837 / 2,844 | 22 / 22 | -24.01 / -24.01 | -0.77 / -0.77 | yes |
| 5 Part A Normal, sd 150, SR 2, 50K (first run) | **85.8** / 80.7 | 9.1 / 12.1 | 1,785 / 1,809 | 113 / 117 | | 2.23 / 2.03 | **no** |
| 5 after fix (S001-014) | 81.2 / 80.7 | 11.6 / 12.1 | 1,847 / 1,809 | 118 / 117 | | 2.00 / 2.03 | yes |

Eligible days agree exactly (1,617 / 1,684). Cells 1 and 4 have identical mean day P&L and Sharpe,
because every eligible day is traded and antithetic pairs cancel the random-direction P&L exactly.

### Cell 5 miss: Claude's flaw, fixed
Part A drew one 5,000-day series per cell; its realised Sharpe was 2.23 instead of 2 (sampling error
about ±0.22). The noise is now moment-matched (sample mean 0, sample sd exactly sd, latent sigmas scaled
the same), so the realised Sharpe equals the nominal one. Part A rerun as S001-014; cell 5 then matches.
Part A frontier moved by at most one grid step in a few cells; the report table is updated.

### Convention concerns
1. *G8 full-path low after the MLL breach.* Same point as R004 #5 and the same resolution: G8 keeps
   propsim's convention so earlier strategies stay comparable; the account-level drop is reported next
   to it, and D006 proposes to stop gating on drawdown altogether.
2. *"No entry in the last 5 minutes before flat."* That wording was Claude's prompt, not the code's rule.
   `grid.py` invalidates entries at or after the flat time, where flat already sits 5 minutes before the
   roll or expiry. So the grid rule is "no entry in the last 5 minutes before the roll / expiry", and it is
   what the S001 numbers use. Codex's stricter version changes none of the 5 cells. The grid docstring is
   reworded to say this plainly.

## Resolution
| # | Item | Action | Status |
|---|---|---|---|
| 1-4 | Part B cells | match within tolerance | VALIDATED |
| 5 | Part A cell | Part A noise moment-matched, rerun S001-014, now matches | VALIDATED after fix |
| c1 | G8 convention | kept; account-level drop reported; D006 | no change |
| c2 | entry cut-off wording | grid docstring clarified; no change in numbers | fixed (docs) |
