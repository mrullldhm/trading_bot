---
id: D005
title: Topstep Daily Loss Limit is a hard rule in every simulation
status: decided
decided: 2026-10-16
approver: owner
updated: 2026-10-16
---

# D005 — Daily Loss Limit

## Context
The owner stated that the strategy will run as a bot on a Topstep account with a $1,000 daily loss limit
(50K). Topstep's help center lists the DLL as 50K $1,000, 100K $2,000, 150K $3,000. Hitting it liquidates
positions and blocks trading until the next session (5:00 PM CT); it is not a rule violation and does not
fail the account. Sources disagree on whether the DLL is active on current TopstepX accounts. The old
Combine simulator (`propsim.py`) did not model it (only `vwap_break_engine.apply_dll` did, as an option).

## Decision
Model the DLL as **on** in every Combine simulation and every strategy backtest of this programme:
- day level (S001, portfolio sims): a day whose intraday low reaches −DLL ends at −DLL;
- minute level (strategy engines, later): when realised + open P&L reaches −DLL, flatten at the next
  minute's open with slippage and stop trading until the next 18:00 ET session.
The bot's own daily stop must sit inside the DLL.

## Why
It is the owner's account setting, and it is conservative: if the DLL turns out to be inactive, results
can only improve.

## Consequences
- `propfirm_research.combine` takes a `dll` parameter, on by default with the account preset.
- Re-verify the DLL status on help.topstep.com before any real Combine.
