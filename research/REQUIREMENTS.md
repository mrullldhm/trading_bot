---
id: REQUIREMENTS
title: What success means
status: living
updated: 2026-10-16
---

# Requirements

A strategy succeeds when it (1) obeys every Topstep rule as a bot, (2) passes the project's gates on
development data, and (3) passes the verdict checks, including one look at the holdout, then a practice
account. This file is the reference. Gate changes need the owner (D003).

---

## 1. Goal

Pass a Topstep Trading Combine with an automated bot on CL futures without breaking any rule, then keep
making money in the Express Funded Account. Account sizes in scope: 50K, 100K, 150K (D004).

---

## 2. Topstep rules per account

| Rule | 50K | 100K | 150K | Source / checked |
|---|---|---|---|---|
| Maximum Loss Limit (MLL): trails the best **end-of-day** balance, counts open losses intraday, stops trailing once it reaches the start balance | $2,000 | $3,000 | $4,500 | TRADING_BOT_GUIDE §3 (2026-10-14); README audit re-check (2026-10-15) |
| Profit target | $3,000 | $6,000 | $9,000 | same |
| Target / MLL (higher = harder per unit of risk room) | 1.5 | 2.0 | 2.0 | derived |
| **Daily Loss Limit (DLL)**: hit = positions liquidated, no trading until the next session (5:00 PM CT); not a rule violation, account not failed | $1,000 | $2,000 | $3,000 | Topstep help center via search, 2026-10-16. Sources disagree on whether it is active on current TopstepX accounts; **modelled ON** (D005) |
| Consistency: best day ≤ 55% of total profit (going over raises the target, it does not fail you) | same | same | same | README re-check 2026-10-15 says 55%; some 2026 sources say 50%. **Re-verify before any Combine** |
| Max position | overall 5 / CL 3 | overall 10 / CL 6 | overall 15 / CL 9 | TRADING_BOT_GUIDE §3 (CL product limits); Codex (R002) cites the help center's overall 5 / 10 / 15. **Verify the CL-specific limit** in TopstepX before every session |
| Trading hours | 5:00 PM CT to 3:10 PM CT next day; flat by 3:10 PM CT (16:10 ET); no overnight or weekend holds | | | TRADING_BOT_GUIDE §3 |
| Automation | bots allowed via the TopstepX API; personal computer only (no VPS, VPN, cloud); no HFT; no max size into major news | | | TRADING_BOT_GUIDE §3 |

Bot conventions on top of the rules: flat by **16:05 ET** (3:05 PM CT), 12:55 ET on CME short days,
no entries while the position state is unknown, own daily stop inside the DLL.

---

## 3. Development gates (strategies are judged on 2010-06 .. 2021-12)

Thresholds as coded in `propfirm_backtest/orb_search.py` (selection pipeline of strategies 2-8), where they
were measured at 1 tick per side, pessimistic fills, 1 CL, 50K, no DLL, flat 16:09 ET. This programme
uses **adapted gates** (section "How this programme applies them"): same thresholds, but with the
account's settings, the DLL on, the chosen CL count and flat 16:05 ET. Only the 50K / DLL-off case is
regression-tested against the old code.

| # | Gate | Threshold | Code |
|---|---|---|---|
| G1 | trades | ≥ 300 (≥ 100 inside walk-forward folds) | `orb_search.py:65, 75, 277, 331` |
| G2 | trades per year | ≥ 25 | `orb_search.py:66, 259, 265` |
| G3 | total P&L at 1 tick/side | > 0 | `orb_search.py:278` |
| G4 | total P&L at 2 ticks/side (+1 tick stress) | > 0 | `orb_search.py:51, 253, 278` |
| G5 | share of positive years (no-trade year = not positive) | ≥ 60% | `orb_search.py:67, 266, 279` |
| G6 | best year / total | ≤ 50% | `orb_search.py:68, 267, 280` |
| G7 | best day / total | ≤ 25% | `orb_search.py:69, 268, 281` |
| **G8** | p95 over 2,000 simulated Combines of the worst drop (end-of-day peak minus intraday low) in the first 60 days | ≤ $1,000 on 50K; **programme: 50% of the account's MLL** = $1,000 / $1,500 / $2,250 (D003) | `orb_search.py:70, 282`; `propsim.py:24, 84-85, 122` |
| G9 | plateau: share of one-step neighbour configs with total > 0 | ≥ 60% (a config with no neighbours fails) | `orb_search.py:71, 195-205, 289` |

Selection score (ranking only): one-sided 95% lower bound of the Combine pass rate,
p − 1.645·√(p(1−p)/2000) (`orb_search.py:208-209`).

---

## 4. Verdict checks

| # | Check | Threshold | Data | Code |
|---|---|---|---|---|
| V1 | the champion passed G1-G9 | true | development | `orb_holdout.py:65` |
| V2 | walk-forward of the whole selector | > $0 | development (folds 2014-2021) | `orb_holdout.py:65`; `orb_search.py:548` |
| V3 | PBO (CSCV, 16 blocks) | < 0.50 | development | `orb_holdout.py:33, 66` |
| V4 | deflated Sharpe at the effective trial count | ≥ 0.95 | development | `orb_holdout.py:32, 66` |
| V5 | expectancy at 1 tick/side | > 0 | holdout | `orb_holdout.py:67` |
| V6 | expectancy at 2 ticks/side | > 0 | holdout | `orb_holdout.py:67` |
| V7 | Combine pass rate > fail rate (2,000 sims on holdout days) | true | holdout | `orb_holdout.py:68` |
| V8 | holdout trades | ≥ 100 | holdout | `family_holdout.py:30, 71` |
| V9 | 10% quantile of 10,000 block-bootstrapped means of daily P&L (5-day blocks) | > $0 | holdout | `family_holdout.py:31-34, 46-63` |
| V10 | Holm across strategy families (alpha 0.10) | report only | holdout | `family_program.py:30, 35-44` |

### How this programme applies them (adapted gates; revised after Codex review R002)
- G1-G9 are computed for the final strategy or portfolio on discovery + validation (2010-06 .. 2021-12),
  the same 12 years the old pipeline used, with the account's Combine settings, the DLL on, the chosen
  CL count and flat 16:05 ET. The portfolio is built by the rule frozen before the first validation run
  (PROTOCOL §2), so validation data cannot shape it.
- G9 needs one-step neighbours: every strategy prereg declares its neighbour set in advance (as
  `vwap_break_eval.py` did with 16 variants).
- V2: walk forward the **complete selector** (which signals pass, the frozen portfolio rule, sizing), one
  fold per year 2014-2021 on earlier years only, as `orb_search.walk_forward` does; total > $0.
- V3 (PBO) and V4 (deflated Sharpe) are computed over the **full candidate universe**: every variant
  explored in discovery for the hypotheses involved (from the ledger), with its dependence structure
  (effective trial count as in `orb_search.effective_trials`), not only the declared neighbours.
- Holdout 2022+: V5-V9 plus G8 recomputed on holdout days, plus the combined skill test of PROTOCOL §4.2.
  Because 2022+ was touched before (HOLDOUTS.md), it is a quasi-holdout; the **practice account is the
  confirmatory final test**.

---

## 5. Combine simulation (how odds are computed)

`propsim.py` (fixed 50K constants, compiled; do not edit) and its parameterised twin
`propfirm_research/combine.py`:
- resamples **trading days** (day P&L and intraday low, including no-trade days) in blocks of 5 days,
  up to 250 days, 2,000 attempts;
- fail when the intraday low touches the trailing MLL line (checked before the day's P&L is added);
- the line follows new end-of-day highs, capped at the start balance;
- pass when the balance reaches the target and the best day is ≤ 55% of the balance;
- `combine.py` adds the account presets, the DLL (a day whose low reaches −DLL is closed at −DLL) and
  G8 at 50% of the MLL. With 50K settings and the DLL off it must equal `propsim.pass_probability`.

---

## 6. Costs (CL only, D004)

| Item | Value |
|---|---|
| Tick value | $10 per tick per contract |
| Fee | $4.02 round turn (project-verified 2026-10-15) |
| Base slippage | 1 tick per side: $24.02 per round trip |
| Stress slippage (G4, V6) | 2 ticks per side: $44.02 |
| Diagnostics | 3 and 4 ticks per side |
| Not used | MCL micro: $1.72 round turn, $1 per tick (Topstep help center, Oct 2026), excluded by D004 |

---

## 7. Feasibility target zone

**Preliminary** (rough Gaussian Monte Carlo run during planning, 2026-10-16; to be replaced by S001).
SR = annual after-cost Sharpe; sigma = daily P&L standard deviation at the chosen size. 20,000 paths,
250 days, end-of-day trailing MLL, intraday low via a Brownian bridge, 55% consistency, DLL cap. Real CL
P&L is fat-tailed, so reality is worse. For scale: one 60-minute trade on 1 CL has a standard deviation
of about 40-50 ticks ($400-500).

| Account (G8 limit) | SR | sigma $/day | pass % | fail % | median days to pass | p95 60-day drop | G8 |
|---|---|---|---|---|---|---|---|
| 50K ($1,000) | 1 | 150 | 49 | 33 | 139 | 2,127 | no |
| 50K | 2 | 150 | 81 | 12 | 119 | 1,803 | no |
| 50K | 2 | 300 | 63 | 37 | 42 | 3,599 | no |
| 50K | 3 | 150 | 96 | 3 | 93 | 1,537 | no |
| 50K | 4 | 300 | 89 | 11 | 32 | 2,658 | no |
| 100K ($1,500) | 2 | 300 | 73 | 23 | 113 | 3,608 | no |
| 100K | 3 | 300 | 90 | 9 | 90 | 3,087 | no |
| 100K | 4 | 150 | 95 | 0 | 150 | 1,324 | yes |
| 150K ($2,250) | 2 | 300 | 62 | 8 | 168 | 3,652 | no |
| 150K | 3 | 300 | 89 | 2 | 140 | 3,065 | no |
| 150K | 4 | 150 | 61 | 0 | 204 | 1,333 | yes |
| 150K | 4 | 300 | 99 | 0.3 | 113 | 2,644 | no |

Without the DLL, at 50K, G8 is met at sigma $75/day (SR 2: pass 36%, p95 $900; SR 3: pass 73%, median
178 days, p95 $769); at sigma $150 even SR 6 misses it narrowly (p95 $1,032).

What it means:
- Every workable row needs an after-cost Sharpe of roughly **2-3 or more**. No strategy so far came
  close out of sample.
- With 1 CL, G8 passes only when daily sigma is low (about $150), which means trading selectively
  (not every day) or briefly, on 100K/150K.
- Bigger accounts sharply cut the fail rate (150K, SR 3, sigma 300: fail 2%) but take longer
  (target/MLL 2.0 vs 1.5).
- G8 rejects rows that fail only ~2% of the time. Whether G8 should change is the D003 question,
  answered with S001's real-data numbers.

---

## 8. Change policy

Gates and this file's thresholds change only through a decision record approved by the owner (D003).
Facts about Topstep (rules, fees) must be re-verified on help.topstep.com before any real Combine, and
the date of the last check written here.
