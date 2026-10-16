---
id: S003
title: Predictability ceiling (kill test)
status: planned
period: discovery
created: 2026-10-16
updated: 2026-10-16
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

## Results
Pending.

## What it means
Pending. Cells whose simultaneous upper bound clears stress break-even become the search space for
hypotheses; if none do and planted 4-8 tick edges are detected with ≥ 80% power, kill criteria 1-2 hold.

## Caveats
A wider model class or new data could still find what this class misses. The 2022+ re-run happens only
inside a pre-registered confirmation, never as part of this study.

## Reproduce
`python -m propfirm_research.studies.s003_ceiling` (to be written).

## Codex review / replication
Planned: design review before running; replication of the null and planted-edge controls.
