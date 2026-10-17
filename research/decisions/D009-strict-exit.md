---
id: D009
title: Strict exits - never fill after the exit minute
status: decided
decided: 2026-10-17
approver: owner
updated: 2026-10-17
---

# D009 — Strict exits

## Context
`propfirm_research.grid.windows` filled an exit at the first bar at or after the exit minute, up to 5
minutes late. For the 16:05 flat exit this used a 16:06-16:09 bar on about 1.1% of days (R010 #8).
Codex held that a stated 16:05 flat must never execute later (R011, R012 Q4.1); Claude had kept the
rule because 16:09 is still before Topstep's 16:10 hard close. The owner was asked to decide.

## Options
| Option | For | Against |
|---|---|---|
| keep the 5-minute exit tolerance | no change; S001-S003 conventions unchanged | a backtest exit can happen after the live bot's flat time |
| **strict, missing bar = invalid window** (Codex) | no fill is ever invented after the rule time; matches Codex's independent replications exactly | ~1% of days skipped |
| strict, stale fill (last price before the exit minute) | keeps those days | a price nobody traded at the exit minute; differs from Codex's convention |

## Decision
Owner, 2026-10-17: **strict**. Every exit, flat or fixed horizon, fills at the open of the bar that
starts exactly at the exit minute (16:05 ET, 12:55 ET on short days, 5 minutes before a roll or expiry,
or the fixed exit time). If that bar is missing, the window is invalid. Reports count the skipped
windows. Entries keep their rule (first bar at or after the decision time, at most 5 minutes late).

## Why
The flat time is a hard rule for the live bot; a backtest that exits later than the bot could is
optimistic by construction. Skipping ~1% of days costs almost nothing and keeps Claude's and Codex's
numbers on the same convention.

## Consequences
- `propfirm_research/grid.py` changes (reviewed by Codex, R013); tests cover ordinary, short-day, roll,
  expiry and fixed-horizon exits.
- S001-S003 keep their published numbers (exploratory, not re-run), with a note in each report.
- Every run from 2026-10-17 on, exploratory or confirmatory, uses the strict rule.
