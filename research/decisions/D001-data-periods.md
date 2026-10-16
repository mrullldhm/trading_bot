---
id: D001
title: Data periods and the firewall
status: decided
decided: 2026-10-16
approver: Claude + Codex (independently proposed the same discovery window); owner approved the charter
updated: 2026-10-16
---

# D001 — Data periods and the firewall

## Context
16.3 years of 1-minute CL bars (2010-06-07 .. 2026-10-13). 2010-2021 was mined by strategies 1-8
(1.39M configs). 2022+ was touched by three earlier tests (HOLDOUTS.md). A research programme with many
hypotheses needs (a) a place to explore freely, (b) a place to confirm each idea once, (c) a final exam.

## Options
| Option | For | Against |
|---|---|---|
| Chronological: discovery 2010-06..2016-12, validation 2017-2021, holdout 2022+ | tests persistence like real deployment; both early periods contain a crash and calm years; simple to explain | edges that appeared only after 2016 are invisible during discovery |
| Interleaved years (odd / even) | both halves cover every regime | validation is not out-of-time; regime leakage between neighbouring years |
| Reverse (discover 2016-2021, validate 2010-2015) | explores the most recent market | validation looks backwards; harder to explain |
| All 2010-2021 for discovery with walk-forward, holdout only | more discovery data | every idea would need the holdout to be confirmed, so the holdout gets spent many times |

## Decision
| Period | CME trading days | Use |
|---|---|---|
| Discovery | 2010-06-07 .. 2016-12-31 | free exploration, all looks logged |
| Validation | 2017-01-01 .. 2021-12-31 | one pre-registered family test per hypothesis; purged expanding walk-forward with one fold per year for fitted models |
| Quasi-holdout | 2022-01-01 .. data end | one pre-registered test of the final portfolio, owner approval |
| Forward | practice account | ≥ 8 weeks, 3-6 months recommended |

Trading day = CME day (a minute at or after 18:00 ET belongs to the next date). Periods are enforced in
code by `propfirm_research.data` and every access is logged in `LEDGER.csv`.

## Why
Chronological validation answers the question that matters for a live bot: does the effect survive into
later years? Claude and Codex picked the same discovery window independently. Strategy edges faded
after ~2015, so discovery reports 2015-2016 separately and requires the effect there (decay guard).

## Consequences
- Research code must load data only via `propfirm_research.data` (a test enforces it).
- Validation budget: 25 families at one-sided alpha 0.01 (PROTOCOL §4.3).
- The 2022+ result can only be called a quasi-holdout; the practice account is mandatory.
- Revisit only if the validation budget is spent without results, and never after looking at validation data.
