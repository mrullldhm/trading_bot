---
id: S003
title: Predictability ceiling (kill test)
status: validated
period: discovery
created: 2026-10-16
updated: 2026-10-17
---

# S003 — Predictability ceiling

## Question
Within a declared class of models and features built from front- and second-month 1-minute OHLCV, how
much of CL's future return can be predicted out of sample, at which decision times and horizons, and
does it beat costs? If not, no rule built from the same inputs can (kill criterion 1, PROTOCOL §4.7).
"Ceiling" = best performance inside this declared class, not proof that no strategy exists.

## Data and method (design merged from Codex R001; frozen before running)
- Discovery trading days only. Unit: (trading day, decision time).
- **Decision times (pre-declared):** 20:00, 03:00, 08:00, 09:00, 10:35, 12:00, 14:00, 14:35 ET.
- **Horizons:** 5, 15, 30, 60, 120 minutes and to 16:05 ET. Executable target: next-minute open to exit
  open, roll-safe, truncated at 16:05 / roll cutoff / expiry.
- **Features (causal):** returns over 5/15/30/60/120 minutes, since 18:00, since 09:00, since the prior
  settlement, prior session, 5- and 20-day; realised volatility vs its time-of-day norm; range position
  in today's and yesterday's range; gap; relative volume (same minute, 20-day norm); VWAP distance;
  CL1-CL2 slope and its 5-day change; weekday, EIA day, minutes to/after EIA, days to expiry, roll flag.
- **Models:** constant-zero benchmark, ridge, elastic net, shallow gradient-boosted trees. Hyperparameter
  ranges declared in code before running.
- **Validation inside discovery:** nested expanding walk-forward by year, purge of the horizon length,
  1-day embargo, non-overlapping positions.
- **Primary output:** cross-fitted net P&L per cell at 1 and 2 ticks per side (CL costs), Romano-Wolf
  max-t over all cells; secondary: out-of-sample IC, hit rate, per-block stability.
- **Controls:** block-shuffled labels and circular shifts (false-positive rate of the whole pipeline);
  random features; one deliberately leaked feature (must be detected); planted edges of 1/2/4/8 net
  ticks (power); negative-control decision times.
- Dependency: scikit-learn (pinned), added with owner approval at the start of S003.

**Implementation choices, fixed before the headline run** (none chosen after a full-period number):
- scikit-learn 1.9.1 (D007). Grids: ridge alpha {1, 10, 100, 1000}; elastic net alpha {0.01, 0.1, 1} x
  l1_ratio {0.2, 0.8}; gradient-boosted trees (HistGradientBoosting) depth {2, 3} x iterations {100, 300},
  learning rate 0.05, min leaf 100. Linear models: median imputation + scaling fitted on training rows.
- Outer test years 2012-2016 (2010-06..2011 is the first training set). Inner selection: train on years
  before Y-1, validate on Y-1, score = sign-rule gross edge. Rows within one trading day of the next
  fold are dropped (every horizon ends inside its trading day, so a 1-day purge + embargo covers it).
- Trading rules: `all` = sign(prediction) every valid day; `conf` = only when |prediction| > 2.402
  ticks (base cost). One trade per cell per day, so positions never overlap within a cell.
- Family: every (cell, model, rule) strategy; Romano-Wolf (1,000 stationary-bootstrap draws, mean
  block 5 days) at base and at stress costs; SPA for the best strategy.
- Controls: 5 circular label shifts (60+ days) and 3 random-feature runs over the full family; planted
  edges of 1 / 2 / 4 / 8 net ticks (target + (e + 2.402) x sign of a random linear combination of 3
  return / VWAP / range features), 5 repetitions each over 5 cells, judged inside the full real family;
  one leaked feature (sign of the target, 70% right); negative-control decision time 00:30 (own family).
- Day-session exits past 16:05 are cut to the flat time; a day is skipped when the last bar before T
  is more than 15 minutes old. Features that are empty by construction at a decision time are dropped.
- Smoke runs (`--quick`: 2 decision times x 2 horizons, few controls, 200 draws) were used for debugging
  and are in the ledger.
- After R010: kill test = simultaneous 95% upper bound of gross edge per trade vs the stress cost; rules
  `all`, `conf_base`, `conf_stress`; roll-week feature dropped; fold-safe label nulls + block shuffle;
  paired planted signals, 20 repetitions per size; 2,000 bootstrap draws. Flat exits may use a bar up
  to 4 minutes after 16:05 on ~1% of days (still before the 16:10 hard close; R010 #8).

## Results
Run 2026-10-17 (LEDGER: S003 `exploratory` rows; outputs `data/research/s003/<stamp>_full/` with
`manifest.json`; tables here: `strategies.csv`, `controls.csv`, `power.csv`, `negative_control.csv`).
48 cells x 3 models x 3 rules = **432 strategies**, out-of-sample 2012-2016 (1,278 days). Runtime 14 min.
**Status: VALIDATED** (statistics) by Codex replication [R011](../../reviews/R011-codex-s003-replication.md); its independent mini-pipeline agrees qualitatively.

### 1. Nothing predicts after costs
| Test | Result |
|---|---|
| Romano-Wolf, base cost | **0 of 432** strategies with adjusted p < 0.05 (smallest 0.96) |
| Romano-Wolf, stress cost | 0 of 432 (smallest 1.00) |
| Hansen SPA (best strategy vs no trade) | p = 0.87 |
| Best net per trade (with >= 200 trades) | 14:35 +60 min, elastic net, `conf_stress`: -0.2 ticks base |
| Highest out-of-sample IC | 0.20-0.22 at 20:00 +5 min, but only 0.9 gross ticks per trade (tiny thin-hour moves; bounce) |

### 2. The pipeline works (controls)
| Control | Runs | Smallest adjusted p | Verdict |
|---|---|---|---|
| labels shifted inside each year | 5 | 0.69 | no false positive |
| labels block-shuffled inside each year | 5 | 0.98 | no false positive |
| random features | 3 | 1.00 | no false positive |
| negative-control time 00:30 (own family, 54 strategies) | 1 | 0.97 | nothing |
| leaked feature, 70% right (pre-declared) | 1 | **0.091: not found** | see power: ~2.4 net ticks, below the detectable size |
| leaked feature 90% / 80% right (**post hoc**, after the run, sanity only) | 2 | 0.0005 / 0.0005 | found |

### 3. Power: what size of edge this study can see
| Planted net ticks per trade | Repetitions | Detected (RW p < 0.05 in the full family) | Power (95% CI) |
|---|---|---|---|
| 1 | 20 | 0 | 0% (0-12%) |
| 2 | 20 | 0 | 0% (0-12%) |
| 4 | 20 | 3 | 15% (6-32%) |
| **8** | 20 | 18 | **90% (74-97%)** |

(Realised oracle edge ~0.16 ticks below the planted size: chance correlation of the planted sign with the
original returns.)

### 4. Simultaneous upper bounds (the kill test)
Critical value c = 3.66 (432 strategies). The 95% simultaneous upper bound of gross edge per trade is
below the stress cost (4.402) for 192 of 432 strategies and below the base cost for 71. Every strategy of
only 2 cells is bounded below the stress cost (10:35 +5 min, 14:00 +15 min); in 16 of 48 cells even the
best-bounded strategy could still hide more than 4.4 gross ticks. The long holds (to 16:05 from 03:00,
08:00, 09:00, 20:00) have bounds of 11-20 ticks: their noise (sd ~100 ticks) is too large to rule
anything out.

## What it means
1. **No predictability was found in this model class on discovery data**, with clean null controls.
   Together with S002 this closes the easy doors: price, volume, range, VWAP, term-structure and calendar
   features at 8 decision times do not forecast CL well enough to beat costs.
2. **But the kill criteria do not formally hold.** Criterion 1 (every upper bound below stress costs)
   fails for 240 strategies, and criterion 2 (>= 80% power at 4-8 ticks) holds only at 8 ticks. Five
   out-of-sample years cannot rule out edges of 4-8 net ticks, which is exactly the size S001 says can
   pass the Combine on short windows. "Nothing found" here means "no edge of ~8+ ticks", not "no edge".
3. **Practical consequences** for phase E:
   - A hypothesis that needs < 8 net ticks per trade can only be confirmed with more data: validation
     (2017-2021) adds 5 years; ideas should be pre-registered with that power in mind (G1 >= 300 trades
     is not enough at 4 ticks).
   - Quiet short windows remain the right search space (their bounds are tight); full-session holds
     are both expensive (S001) and unknowable (bounds 11-20 ticks).
   - Any idea must bring information that is NOT in these features (event content, order flow, other
     markets), or a structural mechanism (settlement flows, S002 K4.4-K4.5).

## Caveats
A wider model class or new data could still find what this class misses. The 2022+ re-run happens only
inside a pre-registered confirmation, never as part of this study.

**Exit convention (D009, 2026-10-17).** This study used the earlier rule: an exit could fill at the first bar up to 5 minutes after the exit minute (16:06-16:09 for the 16:05 flat on about 1% of days). These numbers were not re-run: the archived outputs named under Results (`data/research/<study>/<stamp>/` with `manifest.json`) and the tables in this folder are the record. The command below now applies the strict rule (exact exit bar, else the window is skipped and counted), so a rerun can differ slightly wherever an exit bar is missing.

## Reproduce
`.venv/bin/python -m propfirm_research.studies.s003_ceiling` (`--quick` smoke run; `--jobs N`).

## Codex review / replication
- [R010](../../reviews/R010-codex-s003-code-review.md): code review before the run (3 critical, 6 major, 4 minor; all fixed except SPA #2, disputed with reasoning, and #8, documented).
- [R011](../../reviews/R011-codex-s003-replication.md): replication: statistics VALIDATED; independent mini-pipeline agrees qualitatively; flat-exit convention open (owner).
