---
id: R011
title: Codex independent replication of S003 (inference + mini-pipeline + controls)
status: resolved
item: S003
codex_job: task-mvbj174u-09cvis
created: 2026-10-17
updated: 2026-10-17
---

# R011 — Codex replication of S003

## Request (summary)
Replication mode (`WRITE only under research/replications/S003/`), blind to Claude's results.
Part 1: recompute Romano-Wolf, simultaneous upper bounds and SPA with Codex's own bootstrap on the
exported out-of-sample strategy matrices (432 strategies x 1,278 days). Part 2: an independent raw-data
mini-pipeline (own features, ridge, walk-forward 2012-2016) for 3 cells, plus within-year circular-shift
nulls and a planted 8-net-tick edge on 14:35 -> 16:05.

## Codex output (verbatim)
Replication completed. Scripts and exact commands are documented in [README.md](/home/mrullldhm/personal/propfirm/research/replications/S003/README.md).

### Part 1 — 10,000 stationary-bootstrap draws

| Statistic | Base cost | Stress cost |
|---|---:|---:|
| Minimum Romano-Wolf adjusted p | 0.962904 | 1.000000 |
| Adjusted p < 0.05 | 0 / 432 | 0 / 432 |

| Simultaneous gross-edge bounds | Result |
|---|---:|
| Max-t critical value | 3.645282 |
| Maximum 95% upper bound | 20.354789 ticks/trade |
| Bounds below 4.402 ticks | 195 / 432 |
| Bounds below 2.402 ticks | 72 / 432 |

Hansen-consistent SPA at base cost:

| Statistic | Value |
|---|---:|
| SPA statistic | 2.005423 |
| SPA p-value | 0.896610 |

Six of 10,000 bootstrap draws had an undefined ratio because at least one sparse strategy had no resampled trades; those six were excluded from the ratio critical-value calculation.

### Part 2 — independent raw-data pipeline

| Cell | Valid OOS days | IC | Gross ticks/trade | t |
|---|---:|---:|---:|---:|
| 14:35 → +60 min | 1,216 | 0.051196 | 0.859375 | 1.803325 |
| 09:00 → +30 min | 1,271 | -0.016718 | 0.425649 | 0.469528 |
| 20:00 → +5 min | 1,163 | 0.175088 | 0.540843 | 3.273088 |

Circular-shift controls on 14:35→16:05:

| Within-year shift | Gross ticks/trade | t | t > 3.5 |
|---:|---:|---:|:---:|
| 61 days | 0.492168 | 0.914515 | No |
| 127 days | 0.450948 | 0.837876 | No |
| 193 days | 0.005771 | 0.010719 | No |

Planted edge: 10/10 repetitions exceeded t = 3.5, a detection share of 1.00. Their t-statistics ranged from 6.984445 to 13.529110.

Key conclusions:

- Kill criterion 1 is not met: 237 of 432 simultaneous bounds remain at or above stress break-even, and the maximum bound is very wide.
- The requested controls behaved correctly, but 10/10 repetitions alone do not precisely establish ≥80% power; the two-sided 95% Wilson lower bound is only about 72%.
- Allowing a stated 16:05 flat to execute at 16:06–16:09 is wrong. This replication requires the exact 16:05 open.
- My R010 item 2 SPA criticism was backwards. Hansen-consistent recentering centers plausible candidates while retaining the negative drift of clearly inferior candidates—the convention used here.

Implementation: [part1_inference.py](/home/mrullldhm/personal/propfirm/research/replications/S003/part1_inference.py) and [part2_mini_pipeline.py](/home/mrullldhm/personal/propfirm/research/replications/S003/part2_mini_pipeline.py). All output assertions passed.

Codex session ID: 01a146c9-4b78-7981-95a0-08496121f310
Resume in Codex: codex resume 01a146c9-4b78-7981-95a0-08496121f310

## Claude's response
### Part 1 (statistics on the same strategies): match
| Quantity | Claude (2,000 draws) | Codex (10,000 draws) |
|---|---|---|
| min Romano-Wolf p, base / stress | 0.9635 / 1.000 | 0.9629 / 1.000 |
| strategies with p < 0.05 | 0 / 0 | 0 / 0 |
| simultaneous critical value c | 3.656 | 3.645 |
| max upper bound (ticks / trade) | 19.83 | 20.35 |
| bounds < 4.402 / < 2.402 | 192 / 71 | 195 / 72 |
| SPA stat / p | 2.040 / 0.869 | 2.005 / 0.897 |
All within bootstrap error. **VALIDATED.**

### Part 2 (independent pipeline): qualitative match
| Cell | Claude ridge IC / gross | Codex ridge IC / gross |
|---|---|---|
| 14:35 +60 | 0.105 / 1.36 | 0.051 / 0.86 |
| 09:00 +30 | 0.103 / 2.31 | -0.017 / 0.43 |
| 20:00 +5 | 0.201 / 0.93 | 0.175 / 0.54 |
Codex used a smaller feature set by design (the request listed 9 features; Claude's has ~25), so ICs
differ; both pipelines find gross edges below the 2.4-tick cost in every cell, a high-IC / tiny-edge
pattern at 20:00 +5 (thin-hour bounce), no false positive under within-year shifts, and the planted
8-tick edge in 10 of 10 repetitions (Claude: 18 of 20). Conclusions agree.

### Convention disagreement (open: owner decides)
Codex holds that a flat exit must use the exact 16:05 bar, never a 16:06-16:09 bar. Claude's view
(R010 #8): it happens on ~1.1% of days, at most 4 minutes late, still before Topstep's 16:10 hard close,
and changing `grid` now shifts the validated S001 / S002 numbers by ~1%. **Recommendation:** adopt
Codex's rule in `grid` before the first pre-registered validation run (so every confirmatory number
uses the strict rule), and leave the exploratory S001-S003 numbers as they are, with this note.

## Resolution
| Item | Status |
|---|---|
| Part 1 statistics | VALIDATED |
| Part 2 pipeline + controls | qualitative match (different feature sets by design) |
| SPA dispute (R010 #2) | closed: Codex agrees with Claude |
| flat-exit convention | open: recommendation above, owner decides |
