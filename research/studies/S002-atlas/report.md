---
id: S002
title: Market atlas of CL (discovery data)
status: planned
period: discovery
created: 2026-10-16
updated: 2026-10-16
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

## Results
Pending.

## What it means
Pending.

## Caveats
Everything here is exploratory: many tests on the same data. Nothing in S002 is a tradeable claim until
a hypothesis is pre-registered and validated.

## Reproduce
`python -m propfirm_research.studies.s002_atlas` (to be written).

## Codex review / replication
Planned: R005 (3-5 headline numbers recomputed from raw parquet).
