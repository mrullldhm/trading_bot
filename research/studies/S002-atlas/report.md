---
id: S002
title: Market atlas of CL (discovery data)
status: validated
period: discovery
created: 2026-10-16
updated: 2026-10-17
---

# S002 — Market atlas

## Question
How does CL behave, minute by minute, session by session, around events and across regimes? Where is
the noise budget spent, and where could predictable structure live? Feeds KNOWLEDGE, the BACKLOG ranking,
S003's decision times, and cost realism.

## Data and method (fixed before running)
Discovery trading days only (2010-06-07 .. 2016-12-31), front month, roll-safe returns (never across a
`raw_symbol` change). Unit of inference: trading day. All tables report the three discovery blocks
(2010-12, 2013-14, 2015-16) and BH q-values across every test in the study (exploratory tier).

1. **Volatility, volume, range by half-hour** (ET, DST-aware) and by weekday: mean, median, p95.
2. **Mean return by half-hour and by session** (Asia 19:00-03:00, London 03:00-08:00, NY 08:00-16:05):
   day-clustered t, sign stability by year.
3. **Serial dependence:** variance ratios (Lo-MacKinlay) per window at 5/15/30/60-minute horizons;
   lag-1 autocorrelation of 30-minute returns by time of day.
4. **Segment-to-segment predictability matrix:** overnight (18:00-09:00) → day; first hour → rest;
   rest-of-day → 14:00-14:30; pre-EIA → post-EIA (Wednesdays); day t → day t+1 session.
5. **Event windows:** 09:00 open, Wed 10:30 EIA (and holiday-shifted slots), 14:28-14:30 settlement,
   London open 03:00: volatility multiples and mean signed drift around each.
6. **Regimes:** term structure (CL1-CL2 slope: backwardation vs contango), realised-vol terciles,
   days to expiry / roll weeks, month of year.
7. **Tails:** distribution of 1-, 30-, 60-minute and session returns; biggest days.
8. **Liquidity by time:** volume per minute and share of thin minutes (< 5 lots) by half-hour, to judge
   whether 1 tick of slippage is realistic off-hours.

**Amendments before the headline run** (none of these was chosen after seeing a full-period number):
- Items 9-11 added at Codex's request ([R006](../../reviews/R006-codex-blind-hypotheses-phase-c.md)):
  9. **Per-window feasibility** (no signals): for the S001 templates and every BACKLOG / R006 window,
     eligible days, return sd, MAE p50 / p95 (long and short pooled), p95 range of the entry and exit
     bars, entry-bar volume, thin-entry share, and the gross ticks per trade needed for Sharpe 2
     (every eligible day traded; base and stress costs).
  10. **CL0 / CL1 lead-lag** at 09:00 (08:30-09:00), 14:00 (13:30-14:00) and EIA 10:30 (10:30-10:35):
      contemporaneous correlation, spread-change distribution, front volume share, and whether the
      CL0-CL1 spread change predicts CL0 over the next 25 / 30 / 55 minutes (sign rule).
  11. **Event paths** (EIA 10:30, settlement 14:25): the first 5 minutes against each later 5-minute
      step up to +60 minutes, and the same 30-minute window on the next trading day; |edge| vs costs.
- EIA days = normal weeks of the published-rule calendar (Wednesday 10:30); holiday weeks are left
  out rather than chosen by volume.
- "Sign rule" metrics: IC = correlation of sign(predictor) with the target return (the S001 IC
  definition, with direction = sign of the predictor); edge = mean of sign(predictor) x target, ticks,
  before costs.
- Smoke runs on 2015-16 only (`--quick`) were used to debug; they are in the ledger.
- After R009: the EIA control "non-EIA Wednesdays" turned out to be 4 holidays (every normal week has a
  Wednesday release). Replaced by Mon / Tue / Thu / Fri of normal weeks. Only that ratio changed.

## Results
Run 2026-10-17 (LEDGER: last S002 `descriptive` row; outputs `data/research/s002/<stamp>_full/` with
`manifest.json`; all tables in this folder as CSV, q-values attached). 1,685 discovery sessions,
295 EIA rule days (normal weeks), 531 holiday-week candidate slots. 323 tests in one BH pass;
**36 with q < 0.10**. Runtime ~70 s. **Status: VALIDATED** by Codex replication [R009](../../reviews/R009-codex-s002-replication.md) (5 of 5;
the EIA control ratio after a fix that R009 forced).

### Headline findings
| # | Finding | Size | Stable? | Tradeable? |
|---|---|---|---|---|
| 1 | **Settlement continuation**: the 14:25-14:35 move predicts 14:35-16:05 in the same direction | corr 0.16, sign IC 0.12, gross 2.6 ticks/trade, q 5e-5 | **decaying**: 4.4 / 2.6 / 0.4 ticks in 2010-12 / 2013-14 / 2015-16 | no: 2.6 gross vs 2.4 cost; S001 needs ~4 net |
| 2 | **Post-settlement drift down**: 14:30-15:00 mean -2.2 ticks | t -5.9, q 1e-7 | yes: negative in 7 of 7 years, all blocks about -2 | no alone: gross Sharpe ~2.3 short, ~0 after 2.4 ticks cost |
| 3 | Short-horizon mean reversion everywhere: VR 0.89-0.94 (NY), 0.87-0.92 (London), 0.78-0.86 (Asia) at 5-60 min | z -5 to -21 | yes, all blocks | no: mostly bid-ask bounce of last-trade prices (strongest where the book is thinnest); a 1-tick cost per side eats it |
| 4 | (Artefact caught) a first version showed Asia *trending* at 30-60 min; it came from keeping only unbroken traded stretches, which in thin hours are the fast-moving ones. On the complete minute grid Asia mean-reverts | | | - |
| 5 | Settlement minutes 14:28-14:30: volume x7.2 vs 13:58-14:13, abs move x1.4; 30 min after, drift -2.0 ticks (q 0.001) | | yes (all blocks) | same as #2 |
| 6 | EIA 10:30: abs 1-minute move over 10:30-10:34 x2.7 vs the same minutes on 1,168 non-release weekdays (volume x4.6), x3.1 vs its own 10:00-10:14 (volume x5.1) | | | no direction: first 5 minutes predict nothing to 11:30 |
| 7 | CL0 / CL1 are 0.99 correlated at 09:00, 14:00, 10:30; the spread change (sd 3-5 ticks) predicts **nothing** for the next 25-55 minutes | all q > 0.6 | | no |
| 8 | Overnight 18:00-09:00 -> NY 09:00-16:05 sign edge 4.6 ticks (IC 0.04) | q 0.33 | mixed (4.9 / -0.7 / 9.4) | no |
| 9 | NY day t -> NY day t+1 reversal (corr -0.07) | q 0.07 | 2015-16 weaker | no: IC 0.05 |

### Noise and liquidity (per window, every eligible day; `windows.csv`)
| Window | sd ticks | MAE p95 | Net ticks for Sharpe 2 | Gross needed (base / stress) | Entry-bar volume |
|---|---|---|---|---|---|
| 07:56-08:25 | 21 | 47 | 2.7 | 5.1 / 7.1 | 94 |
| 09:06-09:30 | 27 | 62 | 3.4 | 5.8 / 7.8 | 559 |
| 10:01-10:25 (EIA days) | 22 | 52 | 2.7 | 5.1 / 7.1 | 583 |
| 14:00-14:30 | 37 | 79 | 4.7 | 7.1 / 9.1 | 482 |
| 14:35-16:05 | 22 | 50 | 2.8 | 5.2 / 7.2 | 272 |
| 18:05-20:00 | 20 | 42 | 2.5 | 4.9 / 6.9 | 15 (20% thin entries) |
| 09:00-16:05 | 106 | 220 | 13.4 | 15.8 / 17.8 | 1,444 |

(These per-window "Sharpe 2" ticks trade every eligible day; S001's Combine bar is stricter at
some sizes: compare REQUIREMENTS §7.)

### Other tables
- Half-hours: volatility and volume peak 09:00-11:00 and 14:00-14:30 (1,076 lots/min); Asia 18:30-02:00
  has 15-27 lots/min and 25-40% thin minutes, 83-93% minute coverage.
- Mean returns: only 14:30 (q 1e-7) and 01:00 (-0.7 ticks, q 0.05) clear q < 0.10; no session drifts.
- Term structure: contango 1,315 days vs backwardation 299 (71 days unsynchronised). Overnight -> NY
  sign edge 6.4 ticks in contango (q 0.19), -1.0 in backwardation. Roll weeks: 389 days, nothing.
- Tails: 1-minute excess kurtosis 33; NY session sd 106 ticks, p0.1% -424; biggest day 2011-05-05
  (-673 ticks).

## What it means
1. **No discovery-period effect clears the S001 bar.** The strongest structures (settlement
   continuation IC 0.12; post-settlement drift -2.2 ticks) are real by q-value but sit at or below the
   cost line, and the settlement continuation has faded to ~0.4 ticks by 2015-16. This matches K6.4:
   edges decay after ~2015.
2. **The settlement window is where CL's structure lives.** Both the drift and the continuation sit
   there; the 14:35-16:05 window is cheap (sd 22 ticks, needs ~5.2 gross ticks). A hypothesis that
   *conditions* the settlement continuation (size of the 14:25-14:35 move, volume) is the one idea with
   a measured base, but it must recover ~2-3x the naive edge and survive 2015-16: low prior.
3. **Cross-contract (CL0/CL1) signals look dead** at 09:00, 14:00 and EIA: H017, H019 and H020 lose
   most of their prior.
4. **EIA moves are big but direction-free** after the first 5 minutes: H003, H018, H019, H022 have no
   support here; H002 / H018 need their own test.
5. Short-horizon VR < 1 is a measurement artefact for strategy purposes (bounce); it does not support
   fading 1-15 minute moves after costs. Variance ratios use a complete minute grid (no-trade minute =
   unchanged price): see finding 4 for why.

## Caveats
Everything here is exploratory: many tests on the same data. Nothing in S002 is a tradeable claim until
a hypothesis is pre-registered and validated.

**Exit convention (D009, 2026-10-17).** This study used the earlier rule: an exit could fill at the first bar up to 5 minutes after the exit minute (16:06-16:09 for the 16:05 flat on about 1% of days). These numbers were not re-run: the archived outputs named under Results (`data/research/<study>/<stamp>/` with `manifest.json`) and the tables in this folder are the record. The command below now applies the strict rule (exact exit bar, else the window is skipped and counted), so a rerun can differ slightly wherever an exit bar is missing.

## Reproduce
`.venv/bin/python -m propfirm_research.studies.s002_atlas` (`--quick` = 2015-16 smoke run).

## Codex review / replication
- [R006](../../reviews/R006-codex-blind-hypotheses-phase-c.md): blind hypotheses; asked for items 9-11.
- [R007](../../reviews/R007-codex-s002-code-review.md): code review before the run (2 critical incl. a `stats.variance_ratio` bug, 7 major, 3 minor; all fixed).
- [R008](../../reviews/R008-codex-s002-fix-recheck.md): re-check of the fixes (reporting completeness).
- [R009](../../reviews/R009-codex-s002-replication.md): independent replication, 5 of 5: VALIDATED.
