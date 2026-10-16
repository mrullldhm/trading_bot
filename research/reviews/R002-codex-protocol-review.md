---
id: R002
title: Codex review of PROTOCOL, REQUIREMENTS, D001-D005, BACKLOG, S001 design
status: resolved
item: PROTOCOL / REQUIREMENTS / D001 / D003-D005 / S001
codex_job: task-mvb3lwac-6xszhq
created: 2026-10-16
updated: 2026-10-16
---

# R002 — Codex protocol review

## Request (summary)
Read-only adversarial review (first attempt lost in a laptop crash; re-run): firewall / leakage, statistical
protocol, the adapted gates, the Combine and DLL spec, S001 design, costs and fills, factual errors.

## Codex output (verbatim)

Read-only review completed; no files changed.

## Critical

1. **Day-level DLL logic cannot reproduce forced liquidation.** [D005:20](/home/mrullldhm/personal/propfirm/research/decisions/D005-daily-loss-limit.md:20), [REQUIREMENTS:94](/home/mrullldhm/personal/propfirm/research/REQUIREMENTS.md:94), [S001:30](/home/mrullldhm/personal/propfirm/research/studies/S001-feasibility/report.md:30) propose replacing any DLL-hit day by exactly `−DLL`. End-of-day P&L plus one daily low does not reveal whether the trailing MLL was touched first, the liquidation price, or post-threshold slippage. This can convert an actual MLL failure into survival. `propsim` checks MLL against the original intraday low before adding daily P&L ([propsim.py:83](/home/mrullldhm/personal/propfirm/propfirm_backtest/propsim.py:83)); a naïve cap is therefore order-dependent.

   **Fix:** simulate a minute-equity path and process MLL/DLL first passage chronologically, flattening at the next executable open with slippage. If only daily aggregates exist, report bounds rather than exact pass/fail odds.

2. **The planted edge changes terminal P&L but not the path that determines DLL, MLL, MAE, or G8.** [S001:25](/home/mrullldhm/personal/propfirm/research/studies/S001-feasibility/report.md:25)-[32](/home/mrullldhm/personal/propfirm/research/studies/S001-feasibility/report.md:32). Adding `e` ticks after observing the real random-direction path creates an internally impossible trade: terminal profit improves while its intraday trajectory is unchanged. Consequently S001 cannot establish the claimed feasibility frontier or validate the Combine pipeline.

   **Fix:** plant edge causally into minute returns/prices—or state a precise path deformation that preserves OHLC consistency—then recompute entries, exits, MAE, DLL and MLL. Run multiple seeded direction/subsampling realizations and give Monte Carlo uncertainty.

## Major

3. **Validation can leak into portfolio construction and then be re-labelled “development.”** [REQUIREMENTS:79](/home/mrullldhm/personal/propfirm/research/REQUIREMENTS.md:79)-[86](/home/mrullldhm/personal/propfirm/research/REQUIREMENTS.md:86) recompute gates on discovery plus validation after validation results determine which signals survive. It does not prohibit adjusting portfolio membership, weights, sizing, neighbors, or account choice using 2017–2021. Meanwhile 2022+ is already contaminated ([PROTOCOL:45](/home/mrullldhm/personal/propfirm/research/PROTOCOL.md:45)-[47](/home/mrullldhm/personal/propfirm/research/PROTOCOL.md:47)), so the programme has no clean offline final exam.

   **Fix:** preregister a deterministic portfolio-building rule before the first family validation, or reserve a separate portfolio-validation slice. Treat 2022+ as descriptive confirmation only and make the forward account the confirmatory final test.

4. **Walk-forward purge/embargo is ambiguous and incomplete.** [PROTOCOL:41](/home/mrullldhm/personal/propfirm/research/PROTOCOL.md:41)-[44](/home/mrullldhm/personal/propfirm/research/PROTOCOL.md:44) does not specify which rows are purged, whether label intervals rather than observation dates control overlap, or how annual-fold outputs enter later training. Warm-up ([PROTOCOL:40](/home/mrullldhm/personal/propfirm/research/PROTOCOL.md:40)) is also not distinguished from fitting transformations.

   **Fix:** require `label_end < test_start − 1 trading day` for every training observation, fit scalers/features only on training rows, allow pre-period bars solely for causal state initialization, and add boundary tests around 18:00 ET, year-end and DST.

5. **The two-stage test does not automatically control family error after variant selection.** [PROTOCOL:102](/home/mrullldhm/personal/propfirm/research/PROTOCOL.md:102)-[113](/home/mrullldhm/personal/propfirm/research/PROTOCOL.md:113). Testing N1 only on variants selected by correlated N2/N3/N4 results can exceed alpha. N4 also treats block-shuffling and sign-flipping as interchangeable, although sign-flipping requires symmetry/exchangeability.

   **Fix:** define one combined null/test statistic per variant, apply Romano–Wolf to the combined claims across every variant, and preregister a valid resampling scheme. Define family boundaries mechanically so the 25-family budget cannot be gamed by bundling.

6. **The power rule is backwards.** [PROTOCOL:124](/home/mrullldhm/personal/propfirm/research/PROTOCOL.md:124)-[128](/home/mrullldhm/personal/propfirm/research/PROTOCOL.md:128). Putting an underpowered idea in a multiplicity-adjusted bundle ordinarily reduces power; it does not repair the deficient sample.

   **Fix:** park it, enlarge the prespecified sample, or test a scientifically justified aggregate/portfolio endpoint with its own power calculation.

7. **V2–V4 are materially weakened relative to the cited pipeline.** REQUIREMENTS substitutes “fixed-rule validation positive” for walk-forward selection ([REQUIREMENTS:83](/home/mrullldhm/personal/propfirm/research/REQUIREMENTS.md:83)); the original re-runs the entire selector in each fold ([orb_search.py:315](/home/mrullldhm/personal/propfirm/propfirm_backtest/orb_search.py:315)-[340](/home/mrullldhm/personal/propfirm/propfirm_backtest/orb_search.py:340)). It also proposes PBO only over neighbors and DSR from ledger trial count ([REQUIREMENTS:84](/home/mrullldhm/personal/propfirm/research/REQUIREMENTS.md:84)), whereas the code uses a broad sample/variance from unique explored streams ([orb_search.py:506](/home/mrullldhm/personal/propfirm/propfirm_backtest/orb_search.py:506)-[522](/home/mrullldhm/personal/propfirm/propfirm_backtest/orb_search.py:522)).

   **Fix:** walk forward the complete portfolio selector; compute PBO/DSR over the full candidate universe and its dependence structure.

8. **“Exactly as coded” conflicts with the new conventions.** [REQUIREMENTS:43](/home/mrullldhm/personal/propfirm/research/REQUIREMENTS.md:43)-[55](/home/mrullldhm/personal/propfirm/research/REQUIREMENTS.md:55) claims equivalence, but the old code has fixed 50K settings, no DLL, 1 CL, and exits at 16:09 ET ([orb_engine.py:23](/home/mrullldhm/personal/propfirm/propfirm_backtest/orb_engine.py:23)-[24](/home/mrullldhm/personal/propfirm/propfirm_backtest/orb_engine.py:24)), not the programme’s 16:05 ET ([PROTOCOL:135](/home/mrullldhm/personal/propfirm/research/PROTOCOL.md:135)).

   **Fix:** call these adapted gates and specify formulas for portfolios, account sizes, contract counts, DLL and the 16:05 exit; regression-test only the DLL-off 50K compatibility case.

## Minor

9. **Current contract limits are stale.** D004 says 3/6/9 ([D004:24](/home/mrullldhm/personal/propfirm/research/decisions/D004-sizing-scope.md:24)-[25](/home/mrullldhm/personal/propfirm/research/decisions/D004-sizing-scope.md:25)); current official parameters list 5/10/15. The 55% consistency rule is currently correct, and the DLL is an optional selected feature, not a universal Combine rule. [Topstep parameters](https://help.topstep.com/en/articles/8284197-trading-combine-parameters), [DLL rules](https://help.topstep.com/en/articles/10490293-daily-loss-limit-in-the-trading-combine-and-express-funded-account), [consistency](https://help.topstep.com/en/articles/8284208-consistency-at-topstep).

   **Fix:** update limits and describe DLL as an owner-selected account configuration, retaining the dated re-verification requirement.

10. **Cost wording is ambiguous.** [PROTOCOL:120](/home/mrullldhm/personal/propfirm/research/PROTOCOL.md:120) says “net edge … exceeds stress cost”; net edge has already deducted costs. The actual `$24.02/$44.02` arithmetic and roll-safety logic are correct.

   **Fix:** say either “gross edge exceeds $44.02” or “P&L remains positive after $44.02 costs.”

Codex session ID: 01a1453e-0ede-7630-bea1-32f6cc5a77e7
Resume in Codex: codex resume 01a1453e-0ede-7630-bea1-32f6cc5a77e7

## Claude's response
Most findings accepted. One partly disputed:

**#1 (DLL ordering).** On a continuous intraday path the two limits are levels, so the first one touched
is the one closer to the start of the day. If the MLL line is above −DLL (relative to the day's start),
the capped low −DLL is still below the line and the simulator still fails the attempt. If it is below,
the DLL fires first and the capped day is the true outcome. The day-level cap therefore does not turn an
MLL failure into survival. The real gaps are (a) slippage past the limit and (b) the day low being built
from per-trade MAE. Fix: liquidation now costs `dll_slip_ticks` per contract beyond the limit
(`combine.apply_dll`), and strategy engines will apply the DLL minute by minute (D005).

## Resolution
| # | Finding | Severity | Action | Status |
|---|---|---|---|---|
| 1 | Day-level DLL cap | critical (partly disputed) | ordering argued safe; added liquidation slippage `dll_slip_ticks`; minute-level DLL in strategy engines | resolved |
| 2 | Planted edge changes P&L but not the path | critical | S001 plants a linear drift into the price path (exit, MAE, DLL, MLL all see it); several seeds with MC uncertainty | resolved (S001 design) |
| 3 | Validation can leak into portfolio construction | major | PROTOCOL §2: portfolio-building rule frozen in a decision record before the first validation run; practice account = confirmatory final test | resolved |
| 4 | Purge / embargo ambiguous | major | PROTOCOL §2: `label_end < test_start − 1 trading day`; transforms fitted on training rows only; warm-up only initialises state. Tests cover 18:00 ET and DST; year-end boundary test to add with the first fitted model | resolved |
| 5 | Two-stage test after variant selection inflates error; N4 mixes two nulls | major | PROTOCOL §4.2: one combined statistic per variant, Romano-Wolf across all variants; N4 split into N4a / N4b; family = one card, ≤ 4 variants | resolved |
| 6 | Power rule backwards | major | PROTOCOL §4.5: underpowered ideas are parked; only a justified aggregate endpoint with its own power calculation | resolved |
| 7 | V2-V4 weakened | major | REQUIREMENTS §4: walk forward the complete selector; PBO / DSR over the full candidate universe with effective trial count | resolved |
| 8 | "Exactly as coded" conflicts with new conventions | major | REQUIREMENTS §3: renamed "adapted gates"; only the 50K / DLL-off case is regression-tested | resolved |
| 9 | Contract limits stale; DLL optional | minor | REQUIREMENTS §2: overall 5 / 10 / 15 vs CL 3 / 6 / 9 both shown, verify live; DLL already described as owner-selected (D005) | resolved |
| 10 | "Net edge exceeds stress cost" ambiguous | minor | PROTOCOL §4.4 reworded: gross edge exceeds $44.02 | resolved |
