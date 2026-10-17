---
id: D010
title: Stage-1 data purchase for the settlement-flow track (2015-16)
status: decided
decided: 2026-10-17
approver: owner
updated: 2026-10-17
---

# D010 — Stage-1 data purchase (2015-2016 discovery block)

## Context
D008 chose the staged settlement-flow track: buy 2015-2016 first (the decay-guard block), test H027 (TAS /
signed flow) and H028 (cross-energy) there, and buy earlier years only if a signal survives its kill rule.
Quotes below are Databento `metadata.get_cost` results run on 2026-10-17 with the owner's key (free calls,
D008 point 1), dataset GLBX.MDP3, 2015-01-01 .. 2016-12-31 unless noted.

Known risk: before 2017-05-21 Databento's CME data comes from legacy FIX/FAST (MDP2) files, and its issue
tracker has listed a "missing trade side" problem for that era. The signed-flow signal needs the aggressor
side, so a one-hour sample is bought and checked first. Fallback if the side is missing: classify trades
against the best bid / ask (order-book top, line 6) or by the tick rule.

## Options (each line approved separately)
| # | Data | Feeds | Exact quote | Recommendation |
|---|---|---|---|---|
| 1 | Sample: CLT and CL.v.0 trades, 2015-06-10 14:00-15:00 ET | check aggressor side and TAS price format | $0.04 | **yes, first** |
| 2 | CLT (TAS) trades, all instruments, all sessions | H027: TAS volume and price premium | $0.40 | **yes** |
| 3 | CLT definitions | map TAS instruments to contract months | $0.01 | **yes** |
| 4 | Statistics: CL.v.0 + CL.v.1 ($0.02) and CLT ($0.005) | official settlement price, cleared volume, open interest | $0.03 | **yes** |
| 5 | CL.v.0 trades, 14:20-14:35 ET only (sum of 521 daily quotes) | H027: signed outright flow | $7.60 | **yes**, if line 1 shows the side |
| 6 | CL.v.0 order-book top (mbp-1), 14:20-14:35 ET only | fallback classification if the side is missing | ~$4.24 (20-day sample x 26) | only if needed |
| 7 | RB.v.0 and HO.v.0 1-minute bars | H028 cross-energy | $3.27 | **yes** |
| 8 | BZ.v.0 (NYMEX Brent) 1-minute bars | H028 (thin market; ICE Brent not checked) | $1.32 | yes (cheap) |
| - | not proposed: CL.v.0 trades full sessions $117.80; mbp-1 full sessions $82.48; CL statistics 2010-2026 ($0.22 continuous, $6.67 all contracts: includes validation years, against D008 staging) | | | no |

Recommended set (1-5, 7, 8): **$12.67**; if the side is missing, line 6 (~$4.24) replaces line 5.
Budget cap for stage 1: **$15** (guard in the download code, quotes x 1.1 margin).

## Decision
Owner, 2026-10-17: **the recommended set** (lines 1-5, 7, 8; $12.67), hard cap **$15** for stage 1.
1. Buy line 1 (the $0.04 sample) first and check the aggressor side and the TAS price format.
2. If the side is present: lines 2-5, 7, 8. If it is missing: line 6 (~$4.24) replaces line 5.
3. Download, conversion and the firewall loaders happen in the next session (session 4), then Codex
   review R016 before any analysis of the new data.

## Why
Everything except line 5 costs about $5 together and answers the main question (does settlement-flow
information exist in 2015-16 that the bars lack). Line 5 is the only real cost and is needed only for the
signed-flow variant; the $0.04 sample decides whether it works as bought.

## Consequences
- Downloads use a new module (never the hashed `propfirm_data/config.py`): batch jobs for whole-range
  items (billed once, re-download free for 30 days); per-day requests for the 14:20-14:35 slices, each
  quoted before fetching, stopping at the cap.
- New data are read only through firewall loaders in `propfirm_research.data`, reviewed by Codex (R016)
  before any analysis.
- Earlier years (2010-2014) need a new decision after the 2015-16 results.
