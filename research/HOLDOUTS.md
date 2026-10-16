---
id: HOLDOUTS
title: Every look at held-back data
status: living
updated: 2026-10-16
---

# Holdout registry

A holdout is data kept unseen until one final test. Every look is recorded here, forever.

## Programme holdout (this research)

| Period | Status | Opened | By | Result |
|---|---|---|---|---|
| Validation 2017-01-01 .. 2021-12-31 | sealed; one pre-registered family test per hypothesis | - | - | budget used 0 / 25 families |
| Quasi-holdout 2022-01-01 .. data end | **unopened for this programme**; one look for the final portfolio, owner approval required | - | - | - |

Rules: PROTOCOL §2 and §5. The research loader enforces them and logs every access in `LEDGER.csv`.

## Earlier looks at 2022+ (before this programme)

These touched 2022+ data, which is why it is called a *quasi*-holdout: clean for new hypotheses, but
not untouched.

| When (UTC) | What | Looked at | Result |
|---|---|---|---|
| 2026-10-15 00:56 | Strategy 1 EMA x VWAP holdout (v1 picks) | 4 picks: full stats, 1-4 ticks slippage, P&L by year 2022-2026 | −$33/trade, PF 0.90, pass 16% / fail 78%, p95 drop $4,742 |
| 2026-10-15 16:33 → 16:53 | ACD entry-signal test (pre-registered) | 575 signals, 60-minute horizon vs matched random entries; full strategy descriptive | EDGE NOT CONFIRMED: −$27/trade vs random, p = 0.85; strategy −$58/trade |
| 2026-10-15 (commit 81512c3) | Strategy 6 VWAP Break out-of-sample run | published config + 16 neighbours, 2010-06 .. 2026-07, P&L by year 2022-2026 | every year negative |

## Frozen but unopened holdouts of strategies 2-8

Their picks are frozen in `data/backtests/<name>/frozen_picks.json` with a source hash. Editing any
hashed module (PROTOCOL §9) would make them refuse to run. All champions failed the gates, so opening
them would only confirm known failures.

| Strategy | Folder | Status |
|---|---|---|
| 2 ORB | `data/backtests/orb/` | frozen, unopened |
| 3 ZAB | `data/backtests/zab/` | frozen, unopened |
| 4 Crabel | `data/backtests/crabel/` | frozen, unopened |
| 5 ACD | `data/backtests/acd/` | spent (signal test) |
| 7 Momentum Pullback | `data/backtests/momentum/` | frozen, unopened (champion ineligible) |
| 8 Pine momentum | `data/backtests/momentum2/` | frozen, unopened (champion ineligible) |
| 1 EMA x VWAP v2 | `data/backtests/ema_vwap_v2/` | no clean holdout (v1 holdout already opened) |
