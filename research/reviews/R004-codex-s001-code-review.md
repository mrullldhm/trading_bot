---
id: R004
title: Codex adversarial review of the S001 code (planted edges, batched Combine odds, study script)
status: resolved
item: S001 + propfirm_research/grid.py, combine.py, studies/s001_feasibility.py
codex_job: task-mvb52sls-ni9f4z
created: 2026-10-16
updated: 2026-10-16
---

# R004 — Codex review of the S001 code

## Request (summary)
Read-only adversarial review, before the headline run, of `grid.planted` / `_drift_adverse`,
`combine.odds_many` (+ per-run seeds), `studies/s001_feasibility.py` and the new tests. Asked to challenge
the edge definition (e = net ticks after base cost) and to look for look-ahead, drift sign, MAE, costs, DLL
ordering, reserve, bootstrap seeding, dropped days, the Brownian bridge, the required-edge rule and the
Sharpe / IC translation.

## Codex output (verbatim)
Read-only review completed; no files changed.

## Critical

1. **Terminal losses are omitted from `day_low`, so DLL/MLL first passage is wrong.** [s001_feasibility.py:113](/home/mrullldhm/personal/propfirm/propfirm_research/studies/s001_feasibility.py:113), [s001_feasibility.py:114](/home/mrullldhm/personal/propfirm/propfirm_research/studies/s001_feasibility.py:114), [combine.py:72](/home/mrullldhm/personal/propfirm/propfirm_research/combine.py:72)

   `grid.planted` returns pre-exit MAE, whose bar range excludes the exit bar. Part B sets `day_low = -mae`, but never includes terminal P&L. The frozen implementation explicitly does `day_low = min(day_low, day_pnl)` after each trade. `_attempt` checks MLL only against `day_low` before adding P&L and does not check whether the resulting EOD balance is below the floor.

   Concrete failure: the path is benign until the exit open, which gaps to a −$1,500 result. MAE is only $100, so the $1,000 DLL is not triggered; the simulator books −$1,500 instead of approximately −$1,010. An MLL breach can likewise be detected one day late. This generally makes the frontier harder than reality under DLL, while also misdating MLL failures.

   **Fix:** for a one-trade day use `low[k] = min(-m[k], p[k], 0)`. Add a general validation invariant `day_low <= min(0, day_pnl)` and a regression test where the exit open is the worst price.

2. **The pooled Wilson bound does not include uncertainty from random direction realizations.** [s001_feasibility.py:103](/home/mrullldhm/personal/propfirm/propfirm_research/studies/s001_feasibility.py:103), [s001_feasibility.py:116](/home/mrullldhm/personal/propfirm/propfirm_research/studies/s001_feasibility.py:116), [s001_feasibility.py:135](/home/mrullldhm/personal/propfirm/propfirm_research/studies/s001_feasibility.py:135), [s001_feasibility.py:141](/home/mrullldhm/personal/propfirm/propfirm_research/studies/s001_feasibility.py:141)

   The denominator is reported as `10 × 2,000 = 20,000`, but there are only five independent antithetic direction/mask pairs. The 2,000 inner attempts estimate each fixed empirical row’s conditional bootstrap probability; they do not turn five outer noise realizations into 20,000 independent realizations of the feasibility experiment. Wilson is also being applied to a stratified mixture of potentially different failure probabilities.

   Concrete failure: four direction pairs can have almost zero failure while one adverse pair has materially higher failure. Increasing `n_sims` drives the reported UCB arbitrarily tight even though uncertainty across direction realizations remains essentially unchanged. Criterion (c), the proposed safety gate, can therefore pass spuriously.

   **Fix:** treat each antithetic pair as the outer independent unit. Use many more outer pairs and a hierarchical/cluster bootstrap or a conservative one-sided interval across pair-level probabilities. Alternatively, explicitly define the claim as conditional on ten fixed direction streams and do not present it as a general failure-probability confidence bound.

## Major

3. **Invalid roll/short-session windows are deleted rather than retained as no-trade days.** [s001_feasibility.py:88](/home/mrullldhm/personal/propfirm/propfirm_research/studies/s001_feasibility.py:88), [s001_feasibility.py:90](/home/mrullldhm/personal/propfirm/propfirm_research/studies/s001_feasibility.py:90)

   Filtering to `valid` compresses time: every bootstrapped “day” is an eligible day. A strategy that cannot trade on a roll or shortened session should contribute `(pnl, low) = (0, 0)` on that trading day.

   Concrete failure: a 25%-frequency strategy with ten excluded sessions is simulated as trading on 25% of the remaining sessions, and 250 Combine days contain too many opportunities. Passes occur too quickly and pass/fail odds differ from a real 250-session account. Direction of bias is not universal, but positive-edge cells will usually look easier.

   **Fix:** preserve the complete trading-day frame. Set direction to zero on invalid windows and apply frequency masks only to valid opportunities. Report total sessions, eligible windows, and actual trades separately.

4. **The Student-t endpoint is paired with a Gaussian bridge using fixed unconditional volatility.** [s001_feasibility.py:63](/home/mrullldhm/personal/propfirm/propfirm_research/studies/s001_feasibility.py:63), [s001_feasibility.py:74](/home/mrullldhm/personal/propfirm/propfirm_research/studies/s001_feasibility.py:74), [s001_feasibility.py:78](/home/mrullldhm/personal/propfirm/propfirm_research/studies/s001_feasibility.py:78)

   The inverse-minimum formula is correct for Brownian motion conditional on a Gaussian endpoint with variance `sd²`. It is not a coherent Student-t bridge when a t endpoint is drawn and the same fixed `sd` is used for the conditional excursion. The fat-tailed endpoint’s latent volatility is discarded.

   Concrete failure: a t3 day generated by an extreme latent volatility draw still receives ordinary-volatility bridge noise. Intraday extremes, DLL hits, and MLL failures can be materially understated or otherwise distorted.

   **Fix:** generate Student-t days as a normal scale mixture and pass each day’s latent `sigma_i` into the bridge formula. Document that stochastic process. Otherwise label these rows a hybrid sensitivity analysis, not Student-t intraday paths.

5. **Pre-applying the DLL overstates G8 drawdown when the MLL is reached first.** [combine.py:47](/home/mrullldhm/personal/propfirm/propfirm_research/combine.py:47), [combine.py:73](/home/mrullldhm/personal/propfirm/propfirm_research/combine.py:73), [combine.py:143](/home/mrullldhm/personal/propfirm/propfirm_research/combine.py:143)

   The earlier R002 response is sufficient for pass/fail ordering on a continuous path, but not for the recorded maximum drawdown. `apply_dll` replaces the low with `−DLL−slip` before `_attempt` knows the current MLL distance. If MLL is closer, the account should terminate near that closer level, not continue down to the DLL level for G8 measurement.

   Concrete failure: a 50K attempt already $1,500 below its peak has only $500 of MLL room. A subsequent −$1,200 day excursion fails near a $2,000 peak-to-trough drop, but the stored capped low can record roughly $2,510. This makes G8 look harder, especially with the $500 reserve.

   **Fix:** process MLL and DLL inside `_attempt`, using the current balance/floor to identify the closer first-passage level. Record drawdown at that liquidation level plus the appropriate slip.

6. **The Sharpe and IC translations do not represent the planted signal.** [s001_feasibility.py:125](/home/mrullldhm/personal/propfirm/propfirm_research/studies/s001_feasibility.py:125), [s001_feasibility.py:138](/home/mrullldhm/personal/propfirm/propfirm_research/studies/s001_feasibility.py:138), [s001_feasibility.py:143](/home/mrullldhm/personal/propfirm/propfirm_research/studies/s001_feasibility.py:143)

   `sharpe_ann` is averaged across seed-specific ratios instead of computing a Sharpe from pooled first and second moments. `ic = e_net / raw_return_sd` is also not an information coefficient: the planted predictive return is the gross drift `g = e + 2.402`, and the denominator should reflect the deformed return distribution. Frequency and empirical sign/return covariance also matter.

   Concrete failure: at `e=0`, the code reports IC zero even though a 2.402-tick directional price effect was planted to pay base costs. Averaging seed Sharpes can remain nonzero even when antithetic aggregate mean is exactly at its intended value.

   **Fix:** aggregate means and second moments before calculating Sharpe. Compute IC directly as the correlation between direction and the deformed future return on traded days, then aggregate antithetic pairs; report gross ticks, base-net ticks, and stress-net ticks separately.

7. **Criterion (c) is evaluated with reserve but its headline companion values come from the no-reserve row.** [s001_feasibility.py:163](/home/mrullldhm/personal/propfirm/propfirm_research/studies/s001_feasibility.py:163), [s001_feasibility.py:169](/home/mrullldhm/personal/propfirm/propfirm_research/studies/s001_feasibility.py:169), [s001_feasibility.py:178](/home/mrullldhm/personal/propfirm/propfirm_research/studies/s001_feasibility.py:178)

   The required edge for (c) uses `r5`, but `pass_at_c` and `fail_at_c` are retrieved unconditionally from `r0`.

   Concrete failure: a row can satisfy the reserved-account failure bound, while the published failure rate beside that criterion describes the less restrictive no-reserve simulation.

   **Fix:** select `r5` when populating all criterion-(c) metrics. Add explicit `reserve_at_*` columns and a test with deliberately different reserve/no-reserve odds.

## Minor

8. **“Decision time” is executed at that minute’s open, contrary to the protocol’s next-minute fill.** [s001_feasibility.py:33](/home/mrullldhm/personal/propfirm/propfirm_research/studies/s001_feasibility.py:33), [grid.py:98](/home/mrullldhm/personal/propfirm/propfirm_research/grid.py:98), [grid.py:102](/home/mrullldhm/personal/propfirm/propfirm_research/grid.py:102)

   Random directions prevent signal look-ahead here, but the sampled volatility and holding period do not match the stated execution convention.

   **Fix:** either shift entry to the next minute’s open or rename the template times as executable entry times and amend the design.

9. **`first_from` is grid-end-sensitive and can turn one noisy high-edge miss into `NaN`.** [s001_feasibility.py:147](/home/mrullldhm/personal/propfirm/propfirm_research/studies/s001_feasibility.py:147)

   Requiring every larger grid point to pass is conservative, but it does not estimate the ordinary “smallest edge meeting the criterion.” A Monte Carlo inversion at 32 ticks invalidates all lower candidates.

   **Fix:** report the pointwise first crossing plus uncertainty, or fit a prespecified monotone curve/isotonic estimate using common random numbers. Keep the current rule only as a separately named conservative threshold.

10. **`odds_many` does not validate the seed vector or simulation count.** [combine.py:175](/home/mrullldhm/personal/propfirm/propfirm_research/combine.py:175), [combine.py:180](/home/mrullldhm/personal/propfirm/propfirm_research/combine.py:180)

   A scalar or short seed array reaches compiled indexed code and can error or read out of bounds; nonpositive `n_sims` also has undefined downstream behavior.

   **Fix:** require `seeds.shape == (runs,)`, integer seeds, and `n_sims > 0`.

## Notes

- The short drift sign is correct: shorts receive a downward path deformation while terminal P&L gains `+g`.
- Applying each bar’s start-of-minute drift to its full range is conservative for a favorable linear drift. The significant excursion defect is omission of the terminal exit P&L, not the within-bar convention.
- Contract scaling and liquidation slip scale consistently. Implementing the $500 reserve as `MLL − reserve` while leaving the official G8 limit unchanged matches the stated candidate rule.
- Using `g=e+2.402` and applying stress costs to the same drift is defensible as a “same alpha, worse execution” stress. However, stress-row `e_net` is then base-cost net edge; actual stress-net edge is `e−2`. The output should name all three quantities to prevent the stress frontier being misread.
- Reproduction is deterministic in principle, but exact headline-cell replication is weakened by overwritable `full` filenames and a code hash that omits dependencies such as `costs.py`, `stats.py`, account presets, environment versions, and a source-data fingerprint. Persist a run manifest and immutable run ID.

## Overall verdict

**Fix first.** In particular, the missing terminal low invalidates DLL/MLL outcomes, and the pooled Wilson calculation cannot support criterion (c)’s advertised safety claim. After those and the invalid-day handling are corrected, the headline study is reasonable to run.

Codex session ID: 01a14563-a05e-7300-a353-ea0f80057ea7
Resume in Codex: codex resume 01a14563-a05e-7300-a353-ea0f80057ea7

## Claude's response
| # | Agree? | Why |
|---|---|---|
| 1 | **Agree** (critical bug) | The frozen propsim does `day_low = min(day_low, day_pnl)`; I used the pre-exit MAE only, so a bad exit open never reached the DLL / MLL check that day. |
| 2 | **Agree** | The outer random unit is the direction/mask stream, not the bootstrap attempt. With 5 pairs the pooled 20,000-attempt Wilson bound was far too tight. |
| 3 | **Agree** | Dropping roll / holiday days compresses the calendar; a strategy that cannot trade that day still lives through it. |
| 4 | **Agree** | Draw t days as a normal scale mixture and give the bridge each day's latent sigma. |
| 5 | **Partly** | G8 is defined by propsim's convention (the drop is measured on the strategy's own path, even past liquidation), and every earlier strategy was gated that way, so G8 stays as is. But the account-level drop (stopped at the MLL line) is what the D003 proposal needs, so it is now reported next to it. |
| 6 | **Agree** | Sharpe from pooled moments; IC = corr(direction, deformed return) on traded days; gross / base-net / stress-net ticks all reported. |
| 7 | **Agree** (bug) | (c) companion values now come from the reserve row. |
| 8 | **Disagree** | Grid convention (PROTOCOL §4.6, grid.py docstring): the decision at T uses bars that *started before* T and fills at the open of the bar starting at T: that is the next available price after the decision. No change. |
| 9 | **Agree** | Report both the pointwise first crossing and the conservative "holds from here up" threshold. |
| 10 | **Agree** | Validate seeds shape and n_sims. |
| notes | **Agree** | Each run writes to its own time-stamped folder with a manifest (code hash over the whole package, data fingerprint, versions, settings). |

## Resolution
| # | Finding | Severity | Action | Status |
|---|---|---|---|---|
| 1 | terminal loss missing from day low | critical | `low = min(-mae, pnl, 0)` in S001; `_validate` now rejects `day_low > min(0, day_pnl)`; regression test with the exit open as worst price | fixed |
| 2 | pooled Wilson bound ignores outer uncertainty | critical | 20 seeds = 10 antithetic pairs (1,000 attempts each); criterion (c) uses the max of the pooled Wilson bound and a one-sided 95% t bound over the 10 pair-level fail rates | fixed |
| 3 | invalid windows deleted | major | full trading-day calendar kept; invalid days are (0, 0) no-trade days; frequency mask on valid days only; sessions / eligible / trades reported | fixed |
| 4 | t endpoint with Gaussian-bridge sigma | major | scale-mixture t with per-day latent sigma in the bridge | fixed |
| 5 | DLL pre-applied overstates drawdown when MLL is closer | major (partly) | G8 kept on propsim convention; kernel also returns the account-level drop (low floored at the MLL line on the failing day); p95 of both reported | fixed (reported) |
| 6 | Sharpe / IC translation | major | pooled moments; IC by correlation; gross / net / stress-net ticks columns | fixed |
| 7 | (c) companion values from no-reserve row | major | taken from the reserve row; `reserve_at_*` columns | fixed |
| 8 | decision time vs next-minute fill | minor | disagree: convention already next-bar (see response) | no change |
| 9 | `first_from` grid-end sensitive | minor | both pointwise and conservative thresholds reported | fixed |
| 10 | `odds_many` input checks | minor | seeds shape / integer, n_sims > 0 checked; tests | fixed |
| notes | run identity | note | time-stamped output folder + manifest.json | fixed |
