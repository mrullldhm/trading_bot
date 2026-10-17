---
id: R010
title: Codex adversarial review of the S003 ceiling code (before the headline run)
status: resolved
item: S003 + stats (romano_wolf, spa_test, bootstrap) + combine.gate_g8
codex_job: task-mvbhoqm0-pcvbzk
created: 2026-10-17
updated: 2026-10-17
---

# R010 — Codex review of the S003 code

## Request (summary)
Read-only adversarial review before the headline run: feature causality, targets, walk-forward leakage,
inner selection, Romano-Wolf / SPA correctness, fairness of the planted-edge power test and the null
controls, design gaps, and the new D006 gate helper.

## Codex output (verbatim)
Verdict: **FIX FIRST.** The current run cannot support either S003 kill criterion 1 or 2. I found no obvious ordinary price/volume/VWAP look-ahead in the main feature calculations, and the year-boundary embargo is adequate, but the statistical endpoint and controls need correction before the expensive run.

## Critical

1. **The required simultaneous upper bounds are not computed.**  
   [s003_ceiling.py:316](/home/mrullldhm/personal/propfirm/propfirm_research/studies/s003_ceiling.py:316), [s003_ceiling.py:439](/home/mrullldhm/personal/propfirm/propfirm_research/studies/s003_ceiling.py:439), [report.md:60](/home/mrullldhm/personal/propfirm/research/studies/S003-ceiling/report.md:60)

   `evaluate()` returns means, t-statistics, and adjusted p-values. A failure to reject profitability is not evidence that the upper bound is below stress break-even.

   Failure scenario: every strategy has `rw_p_stress=1`, but sampling uncertainty still permits a gross edge of 6 ticks/trade. The code could nevertheless be summarized as “nothing beats stress costs,” improperly satisfying kill criterion 1.

   Fix: predefine the estimand and construct simultaneous one-sided 95% upper confidence bounds by bootstrap inversion. For `conf`, bootstrap and studentize the ratio `sum(gross)/sum(trades)` rather than comparing a daily mean to a per-trade cost. Report each cell/model/rule gross-edge UCB and compare it with 4.402 ticks.

2. **The Hansen-consistent SPA recentering is reversed.**  
   [stats.py:241](/home/mrullldhm/personal/propfirm/propfirm_research/stats.py:241), especially [stats.py:252](/home/mrullldhm/personal/propfirm/propfirm_research/stats.py:252)-[255](/home/mrullldhm/personal/propfirm/propfirm_research/stats.py:255)

   The consistent SPA bootstrap statistic should be based on:

   `bootstrap_mean - observed_mean + observed_mean * keep`

   The code instead computes:

   `bootstrap_mean - observed_mean * keep`

   Thus plausible nulls are centered when they should retain their local mean, while clearly inferior candidates are left uncentered when they should be centered.

   Failure scenario: the composition of many weakly negative strategies changes the bootstrap maximum and can make SPA either too liberal or too conservative.

   Fix: use `(bm - mean + mu_c) / se`, then validate against a reference implementation over null, local-alternative, and many-inferior-model cases. SPA should also use an appropriate long-run variance estimate for the stationary data.

3. **The power/control suite cannot establish kill criterion 2 as implemented.**  
   [report.md:33](/home/mrullldhm/personal/propfirm/research/studies/S003-ceiling/report.md:33), [s003_ceiling.py:375](/home/mrullldhm/personal/propfirm/propfirm_research/studies/s003_ceiling.py:375)-[418](/home/mrullldhm/personal/propfirm/propfirm_research/studies/s003_ceiling.py:418)

   Problems:

   - The frozen block-shuffled-label control is absent.
   - Circular shifts cross outer-fold/year boundaries and wrap late-2016 labels into 2010 training rows.
   - The planted direction changes with edge size because the seed is `1000 * e + r`; 1/2/4/8 ticks are therefore not paired power experiments.
   - The claimed net edge is not exactly `e`: oracle net is `e + mean(sign_signal * original_y)`.
   - Five repetitions only estimate power in 20-point increments and cannot substantiate “power ≥80%” with useful confidence.

   The quick run already shows the instability: planted 1/2/4/8 adjusted p-values were 0.78, 0.985, 0, 0. Changing signals between effect sizes makes that sequence hard to interpret.

   Fix: add the frozen block-shuffle control; shift within folds/years or lag without wrapping; reuse the same `(cell, coefficients, signal)` for every edge size; report the realized oracle gross/net edge; and use enough repetitions to provide a power confidence interval. Preserve the full 288-strategy family in every replicate.

## Major

4. **The roll feature uses the future realized roll boundary.**  
   [s003_ceiling.py:118](/home/mrullldhm/personal/propfirm/propfirm_research/studies/s003_ceiling.py:118), [s003_ceiling.py:207](/home/mrullldhm/personal/propfirm/propfirm_research/studies/s003_ceiling.py:207), [grid.py:67](/home/mrullldhm/personal/propfirm/propfirm_research/grid.py:67)

   `roll_schedule()` infers a contract’s roll time from the future first observation of the next front contract in the completed dataset. Changing a future bar can therefore change a historical `roll_week` feature.

   Failure scenario: variations or data gaps in the vendor’s realized switch date become a predictive feature unavailable at the historical decision time, inflating the ceiling near rolls.

   Fix: derive roll state from an ex-ante calendar/rule known on the decision date, or remove the feature. Apply the same causal schedule to target truncation.

5. **The base-cost confidence threshold is not adequate for a stress-cost ceiling.**  
   [s003_ceiling.py:269](/home/mrullldhm/personal/propfirm/propfirm_research/studies/s003_ceiling.py:269)-[276](/home/mrullldhm/personal/propfirm/propfirm_research/studies/s003_ceiling.py:276)

   Both base and stress evaluations use `|pred| > 2.402`. A strategy that sensibly trades only predictions above 4.402 ticks under stress is missing.

   Failure scenario: many 3-tick predictions and a smaller set of 6-tick predictions make both `all` and base-`conf` lose after stress costs, while a stress-specific rule profits. This biases the claimed stress ceiling downward.

   Fix: predeclare separate `conf_base` and `conf_stress` rules, include both in the same multiplicity family, and use the applicable rule for the corresponding break-even claim.

6. **Several implemented features differ materially from the frozen design.**  
   [s003_ceiling.py:167](/home/mrullldhm/personal/propfirm/propfirm_research/studies/s003_ceiling.py:167)-[199](/home/mrullldhm/personal/propfirm/propfirm_research/studies/s003_ceiling.py:199)

   - “Relative volume at the same minute” is implemented as trailing 30-minute volume normalized across days.
   - `ret_5d` and `ret_20d` sum five/twenty completed sessions and then add the current partial session, effectively 5+partial and 20+partial.
   - `ret_since_0900` uses the price after the 09:00 minute rather than the 09:00 boundary.
   - Yesterday’s range is not guarded against a contract change.
   - Five-day slope change can span a roll and acquire a mechanical curve jump.

   Failure scenario: the intended predictive feature is omitted, lowering the ceiling, while cross-contract price-level discontinuities can raise it.

   Fix: reconcile every feature with an explicit timestamp/value formula, reset price-level features at rolls, and add exact-value tests around 09:00, settlement, session boundaries, and contract changes.

7. **The frozen negative-label control is not valid across the walk-forward folds.**  
   [s003_ceiling.py:377](/home/mrullldhm/personal/propfirm/propfirm_research/studies/s003_ceiling.py:377)-[380](/home/mrullldhm/personal/propfirm/propfirm_research/studies/s003_ceiling.py:380)

   Whole-sample `np.roll` moves labels between years and wraps the end of the discovery sample into the beginning. Date, EIA, expiry, volatility-regime, and seasonal structure can remain associated after such a shift.

   Fix: perform the declared null transformation independently inside each outer experiment, preserving its train/validation/test boundary and discarding rather than wrapping edge observations.

8. **Flat exits can occur after 16:05.**  
   [grid.py:109](/home/mrullldhm/personal/propfirm/propfirm_research/grid.py:109)-[119](/home/mrullldhm/personal/propfirm/propfirm_research/grid.py:119)

   `searchsorted()` plus `EXIT_TOL=5` permits a nominal 16:05 exit at 16:06–16:10 if the 16:05 bar is missing.

   Failure scenario: a favorable move after the required flat time enters the target, and 16:10 reaches the hard-close boundary.

   Fix: require the flat-time bar exactly, use an explicitly conservative pre-flat price, or invalidate the day. Report the number of late entry/exit substitutions before running.

9. **G8 can pass without the required outer-draw uncertainty bound.**  
   [combine.py:215](/home/mrullldhm/personal/propfirm/propfirm_research/combine.py:215)-[228](/home/mrullldhm/personal/propfirm/propfirm_research/combine.py:228), [D006:36](/home/mrullldhm/personal/propfirm/research/decisions/D006-g8-recalibration-proposal.md:36)

   `outer_fail_rates` is optional. When omitted, the gate uses only the Wilson uncertainty from the 2,000 simulated attempts and ignores uncertainty in the historical daily series.

   Failure scenario: a short, lucky P&L sample has estimated failure below 10% with a tight Monte Carlo Wilson interval but highly uncertain true failure odds, yet `g8_ok=True`.

   Fix: require independent outer resamples for production gate decisions; validate their number, independence, and `[0,1]` range. Permit Wilson-only output as diagnostic, but not a passing G8 verdict.

## Minor

10. **Bootstrap p-values can be reported as zero.**  
    [stats.py:235](/home/mrullldhm/personal/propfirm/propfirm_research/stats.py:235), [stats.py:256](/home/mrullldhm/personal/propfirm/propfirm_research/stats.py:256)

    Use `(exceedances + 1) / (n_boot + 1)`. The quick output already reports planted p-values of exactly zero. For a headline 95% bound over 288 strategies, 1,000 draws also give fairly noisy tail estimates; use more draws for the final inference.

11. **The constant-zero benchmark is implicit rather than reported.**  
    [s003_ceiling.py:58](/home/mrullldhm/personal/propfirm/propfirm_research/studies/s003_ceiling.py:58)

    Flat is the comparison for SPA, but the frozen model list includes a constant-zero benchmark. Include it explicitly in output or state that it is analytical and excluded from Romano–Wolf because its variance is zero.

12. **The negative-control family omits the flat horizon.**  
    [s003_ceiling.py:421](/home/mrullldhm/personal/propfirm/propfirm_research/studies/s003_ceiling.py:421)

    The frozen wording says the negative-control decision time has its own family. Excluding `00:30→flat` weakens that control without explanation.

13. **The quick-run description is inaccurate.**  
    [report.md:55](/home/mrullldhm/personal/propfirm/research/studies/S003-ceiling/report.md:55), [s003_ceiling.py:350](/home/mrullldhm/personal/propfirm/propfirm_research/studies/s003_ceiling.py:350)-[362](/home/mrullldhm/personal/propfirm/propfirm_research/studies/s003_ceiling.py:362)

    It is described as a 2015–16 smoke run, but `oos` still includes 2012–2016. The artifact contains 1,277 OOS observations for some strategies, confirming it was not restricted to 2015–16.

## Notes / checks that passed

- Feature prices, ranges, volume, VWAP and realized volatility generally end strictly before the decision time; rolling norms use `shift(1)`.
- The target and feature arrays are aligned by trading day.
- The outer/inner split excludes the immediately preceding trading-day row. Because every label ends within its own CME trading day, this is adequate even for `20:00→16:05`.
- Hyperparameter selection is genuinely nested. One validation year is noisy and may lower power, but it does not leak the outer year.
- Romano–Wolf’s core centering, descending step-down subsets, monotonic adjusted p-values, and one-sided maximum are otherwise implemented consistently with the declared fixed-original-SE algorithm.
- “One trade per cell per day” does prevent overlap within an individual strategy. Trades from different cells overlap, but those are separate candidate strategies rather than one portfolio.
- Costs are charged only on actual trades, and no-trade days are represented as zero.

## Numbers I would independently replicate after fixes

- Valid-day counts and exact feature/target values for sampled normal, missing-bar, roll, expiry, short-session, EIA, 09:00, 14:30, and 20:00 days.
- For every fold: last inner-training label end, first inner-validation decision, last outer-training label end, and first test decision.
- Per strategy: OOS observations, trades, gross ticks/trade, base and stress net ticks/trade, daily mean, IC, hit rate, and block results.
- The best strategy and every simultaneous gross-edge upper bound at both costs.
- Romano–Wolf adjusted p-values from an independent stationary-bootstrap implementation, using substantially more draws.
- Corrected SPA statistic and p-value.
- Whole-pipeline false-positive counts for block shuffles, fold-safe circular shifts, and random features.
- For every planted replicate: selected features/coefficients, oracle realized edge, and detection result; then the power estimate and confidence interval for 4- and 8-tick edges.
- Leak-control detection and the complete 00:30 negative-control family.
- As a smoke-run checksum, I would first reproduce the existing artifact’s 24 strategies, the `09:00+30|gbt|conf` 1,021 trades / 3.327 gross / 0.925 base-net ticks per trade, and SPA p=0.755 before comparing corrected statistics.

Codex session ID: 01a146a6-cbf8-7d52-a1b9-3b5e1d102d26
Resume in Codex: codex resume 01a146a6-cbf8-7d52-a1b9-3b5e1d102d26

## Claude's response
| # | Agree? | Why / what |
|---|---|---|
| 1 | **Agree** (critical) | Not rejecting is not a ceiling. Added `stats.simultaneous_upper` (max-t bootstrap of the ratio estimator gross / trades) and made it the kill test against the 4.402-tick stress cost. |
| 2 | **Disagree** | Hansen's consistent SPA bootstraps d* - g_c(mean) with g_c(x) = x for plausible nulls (x >= -threshold) and 0 for clearly inferior ones: plausible nulls are centred, inferior ones keep their negative mean. The code does exactly that (`bm - mu_c`, `mu_c = mean` where plausible, else 0). The proposed `bm - mean + mean*keep` would leave the plausible nulls *uncentred* and centre the inferior ones, the reverse of the test. Tests: a null of slightly negative candidates does not reject; a planted winner does. Bootstrap p-values now use (exceed + 1) / (n + 1). |
| 3 | **Agree** | Block shuffle added; label nulls stay inside each calendar year (no wrap across folds); planted signal fixed per repetition and reused for every edge size; realised oracle edge reported; 20 repetitions per size with a Wilson interval on power; full family in every replicate. |
| 4 | **Agree** | `roll_week` dropped (the vendor roll date is not known ex ante). The roll cut-off of target windows stays (it only invalidates days; it never chooses a direction). |
| 5 | **Agree** | Rules `conf_base` (2.402) and `conf_stress` (4.402) in the same family. |
| 6 | **Agree** | 09:00 boundary price; 5 / 20-day = previous full sessions only; previous-day range NaN across a contract change; slope change NaN across a roll; same-minute relative volume added. |
| 7 | **Agree** | Same fix as 3. |
| 8 | **Partly** | Counted: 18 of ~1,680 days (1.1%) per flat window exit up to 4 minutes late (latest 16:09). That is still inside Topstep's 16:10 hard close; 16:05 is the programme's buffer. Changing `grid` now would change the validated S001 / S002 numbers by ~1% for no safety gain, so it is documented, not changed. |
| 9 | **Agree** | `gate_g8` now always adds a t bound over 20 stationary-bootstrap resamples of the strategy's own day series; without outer draws it can only be diagnostic (`g8_ok` False). |
| 10 | Agree | (exceed + 1) / (n + 1); 2,000 draws in the headline run. |
| 11 | Agree | "No trade" benchmark stated as analytical (P&L 0, outside the bootstrap family). |
| 12 | Agree | 00:30 negative control now includes the flat horizon. |
| 13 | Agree | `--quick` = 2 decision times x 2 horizons, not a 2015-16 run; report wording fixed. |

## Resolution
| # | Finding | Severity | Status |
|---|---|---|---|
| 1 | no simultaneous upper bound | critical | fixed |
| 2 | SPA recentring | critical (disputed) | no change; Codex agreed in the follow-up below |
| 3, 7 | controls / power | critical / major | fixed |
| 4 | roll feature uses the future | major | fixed (dropped) |
| 5 | stress rule | major | fixed |
| 6 | feature definitions | major | fixed |
| 8 | late flat exits | major | partly: documented (1.1% of days, <= 16:09) |
| 9 | G8 without outer uncertainty | major | fixed |
| 10-13 | minors | minor | fixed |

## Follow-up on #2 (Codex job task-mvbictr4-chiply, verbatim)
I agree; Claude’s reasoning is correct, and R010 finding #2 should be withdrawn. Hansen’s consistent recentering subtracts the sample mean for plausible null candidates and leaves clearly inferior candidates at their negative mean, exactly as `bm - mu_c` implements. My proposed expression reversed those cases. The tests are useful corroboration, though the defining reason is the formula itself.

Codex session ID: 01a146a6-cbf8-7d52-a1b9-3b5e1d102d26
Resume in Codex: codex resume 01a146a6-cbf8-7d52-a1b9-3b5e1d102d26

Resolution of #2: **Codex agrees** (also restated in R011). No change; closed.
