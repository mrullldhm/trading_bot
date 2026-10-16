---
id: R007
title: Codex adversarial review of the S002 atlas code (before the headline run)
status: resolved
item: S002 + propfirm_research/studies/s002_atlas.py, stats.variance_ratio
codex_job: task-mvbfra37-tc6spv
created: 2026-10-17
updated: 2026-10-17
---

# R007 — Codex review of the S002 atlas code

## Request (summary)
Read-only adversarial review of `studies/s002_atlas.py` and its tests before the headline run: look-ahead
in regimes, day alignment of next-day pairs, minute returns across rolls / days, bins, variance ratios,
EIA selection, event multiples, term structure, sign-rule IC vs S001, the BH family, design coverage.

## Codex output (verbatim)
## Critical

1. Variance-ratio test statistics and p-values are broken.

   - Evidence: [stats.py:83](/home/mrullldhm/personal/propfirm/propfirm_research/stats.py:83), especially [stats.py:101](/home/mrullldhm/personal/propfirm/propfirm_research/stats.py:101). The heteroskedastic variance calculation multiplies the squared-return cross-product ratio by `n`, but the returned statistic at [stats.py:103](/home/mrullldhm/personal/propfirm/propfirm_research/stats.py:103) does not include a compensating sample-size factor.
   - Concrete failure: the existing quick output reports Asia `q=60`, `VR=0.789` on 238,203 observations but `z=-0.013`, `p=0.989`. A 21% VR deviation on that sample cannot coherently have an almost-zero test statistic. Thus all 12 VR p-values and their BH q-values are unusable.
   - Existing tests miss this: [test_research_core.py:208](/home/mrullldhm/personal/propfirm/tests/test_research_core.py:208) only checks that an IID `z` is below 3, while the AR test at [test_research_core.py:213](/home/mrullldhm/personal/propfirm/tests/test_research_core.py:213) asserts only the VR value, not that the test rejects.
   - Fix: implement one internally consistent Lo–MacKinlay heteroskedastic statistic from a cited formula—most directly, remove the extra `n` from `delta` for the current normalization—and test both null size and strong power against simulated AR(1) alternatives.

2. Variance ratios concatenate unrelated session pieces across days and data gaps.

   - Evidence: [s002_atlas.py:149](/home/mrullldhm/personal/propfirm/propfirm_research/studies/s002_atlas.py:149) selects every return having a session clock time, then [stats.py:87](/home/mrullldhm/personal/propfirm/propfirm_research/stats.py:87) drops all NaNs before convolving at [stats.py:94](/home/mrullldhm/personal/propfirm/propfirm_research/stats.py:94).
   - Concrete failure: a 60-period Asia sum can contain the final minutes of trading day \(t\) followed immediately by the first minutes of Asia on trading day \(t+1\). A missing five-minute interval is likewise compressed away and treated as adjacent one-minute observations. These are not 60-minute returns, while their inference is at the minute rather than trading-day level required by [PROTOCOL.md:96](/home/mrullldhm/personal/propfirm/research/PROTOCOL.md:96).
   - Fix: construct complete, consecutive minute grids separately for each trading-day/session; form overlapping \(q\)-minute returns only within each group; then obtain inference from day-level VR estimates or a trading-day/block bootstrap. Never convolve after globally dropping gaps.

## Major

1. “One-minute” returns can actually span multiple minutes.

   - Evidence: [s002_atlas.py:84](/home/mrullldhm/personal/propfirm/propfirm_research/studies/s002_atlas.py:84) checks only equal contract and trading day before applying `np.diff`; it never requires `tmin[i] - tmin[i-1] == 1`.
   - Concrete failure: if 08:59 is absent, the 09:00 return may be `close(09:00)-close(08:58)`. That two-minute move enters the one-minute tails, half-hour realised volatility, event volatility and VR calculations as one observation.
   - Fix: require consecutive UTC minutes in addition to the existing contract/day checks. Report missing-minute rates by bin. The protections against contract changes and trading-day boundaries themselves are correct.

2. EIA handling omits a fixed-design event class and produces non-comparable multiples.

   - Evidence: the fixed design explicitly includes holiday-shifted EIA slots at [report.md:29](/home/mrullldhm/personal/propfirm/research/studies/S002-atlas/report.md:29), but [s002_atlas.py:314](/home/mrullldhm/personal/propfirm/propfirm_research/studies/s002_atlas.py:314)–[321](/home/mrullldhm/personal/propfirm/propfirm_research/studies/s002_atlas.py:321) retain only weeks having one Wednesday 10:30 calendar row.
   - Concrete failure: holiday weeks, including high-information seasonal weeks, disappear entirely. This selection is rule-based and therefore not outcome look-ahead, but it biases representativeness toward normal Wednesdays and does not implement item 5 as fixed.
   - The event columns also use different denominators: EIA absolute returns are EIA days divided by all non-EIA weekdays at 10:30 ([s002_atlas.py:224](/home/mrullldhm/personal/propfirm/propfirm_research/studies/s002_atlas.py:224)), while EIA volume is event minutes divided by the same EIA days’ earlier minutes ([s002_atlas.py:230](/home/mrullldhm/personal/propfirm/propfirm_research/studies/s002_atlas.py:230)). The two fields consequently do not describe the same kind of “multiple.”
   - Fix: report separately:
     - event/local-prewindow multiples on the same eligible days;
     - EIA/non-EIA multiples against matched non-EIA Wednesdays at 10:30;
     - normal and shifted-release weeks as separate strata.  
     If exact historical shifted timestamps are unavailable, analyse every ex-ante rule candidate and state that dilution explicitly rather than choosing candidates from observed volume.

3. The settlement event window differs from the fixed design.

   - Evidence: the design specifies 14:28–14:30 at [report.md:29](/home/mrullldhm/personal/propfirm/research/studies/S002-atlas/report.md:29). The implementation labels an event at 14:28 but sets every event window to five minutes, 14:28–14:33, at [s002_atlas.py:219](/home/mrullldhm/personal/propfirm/propfirm_research/studies/S002-atlas.py:219)–[223](/home/mrullldhm/personal/propfirm/propfirm_research/studies/S002-atlas.py:223).
   - Concrete failure: ordinary post-settlement movement is attributed to the settlement window, potentially changing both its volatility multiple and its ranking relative to other events.
   - Fix: make event lengths explicit per event and use the fixed two-minute settlement window. Any five-minute variant must be labelled and counted as an additional exploratory test.

4. Term-structure observations are not synchronized.

   - Evidence: [s002_atlas.py:245](/home/mrullldhm/personal/propfirm/propfirm_research/studies/s002_atlas.py:245) independently selects the last front- and second-contract observations before 09:00. [s002_atlas.py:259](/home/mrullldhm/personal/propfirm/propfirm_research/studies/s002_atlas.py:259) merely checks that their contract names differ; it never checks that their timestamps match or are recent.
   - Concrete failure: CL.v.0 could be sampled at 08:59 and CL.v.1 at 08:47, turning an intervening market move into an apparent calendar spread and possibly flipping contango/backwardation.
   - Fix: inner-join CL.v.0 and CL.v.1 by exact `tmin`, choose the last common timestamp strictly before 09:00, and impose/report a staleness limit. Also verify that the second expiry is later than the front expiry.

5. The regime implementation omits “roll weeks” and may mislabel expiry proximity.

   - Evidence: item 6 fixes “days to expiry / roll weeks” at [report.md:31](/home/mrullldhm/personal/propfirm/research/studies/S002-atlas/report.md:31). The code calculates only elapsed UTC days to contract expiration at [s002_atlas.py:264](/home/mrullldhm/personal/propfirm/propfirm_research/studies/s002_atlas.py:264)–[273](/home/mrullldhm/personal/propfirm/propfirm_research/studies/S002-atlas.py:273); no actual front-roll regime is produced.
   - Concrete failure: index/front-month roll pressure normally occurs before expiration, so an expiry bucket can mix roll and non-roll observations and cannot answer the fixed roll-week question.
   - Fix: retain DTE as a separate known-before-09:00 feature, but add days to the ex-ante front-roll time and an explicit roll-week indicator. Report excluded DTE values, including any `<=0` or `>40`.

6. Fixed-design block and multiplicity reporting is incomplete, and the promotion threshold is wrong.

   - Evidence: the design requires all tables to report all three discovery blocks and BH q-values at [report.md:18](/home/mrullldhm/personal/propfirm/research/studies/S002-atlas/report.md:18)–[20](/home/mrullldhm/personal/propfirm/research/studies/S002-atlas/report.md:20). Blocks appear only in mean-return rows and sign-edge rows ([s002_atlas.py:139](/home/mrullldhm/personal/propfirm/propfirm_research/studies/S002-atlas.py:139), [s002_atlas.py:177](/home/mrullldhm/personal/propfirm/propfirm_research/studies/S002-atlas.py:177)); q-values exist only in the detached `tests.csv` at [s002_atlas.py:344](/home/mrullldhm/personal/propfirm/propfirm_research/studies/S002-atlas.py:344).
   - The ledger and console count `q < 0.05` at [s002_atlas.py:359](/home/mrullldhm/personal/propfirm/propfirm_research/studies/S002-atlas.py:359)–[368](/home/mrullldhm/personal/propfirm/propfirm_research/studies/S002-atlas.py:368), whereas the programme’s exploratory and promotion threshold is `q < 0.10` at [PROTOCOL.md:121](/home/mrullldhm/personal/propfirm/research/PROTOCOL.md:121) and [PROTOCOL.md:130](/home/mrullldhm/personal/propfirm/research/PROTOCOL.md:130).
   - Concrete failure: a half-hour with `q=0.07` and stable block signs should feed H012 under the protocol but would not be counted by the run summary. Conversely, regime/event rows can be copied into hypothesis ranking without their q-value or 2015–16 stability being visible.
   - Fix: add stable test IDs and merge q-values into every inferential table; add three-block estimates to every ranking input; summarize both `q<0.10` and, optionally, `q<0.05`, with `q<0.10` as the protocol decision threshold.

7. The tests do not exercise the highest-risk paths.

   - Evidence: the new suite tests the EIA exclusion, sign IC, a contiguous synthetic return, and the pre-09:00 lookup at [test_research_s002.py:15](/home/mrullldhm/personal/propfirm/tests/test_research_s002.py:15)–[52](/home/mrullldhm/personal/propfirm/tests/test_research_s002.py:52).
   - Concrete failure: every critical/major defect above passes these tests. There is no missing-minute case, day-boundary VR case, cross-day `shift(-1)` assertion, unmatched front/second timestamp case, settlement-length check, roll-week check, or q-value/block-output check.
   - Fix: add synthetic two-day tests with a weekend boundary, missing minutes, mismatched series timestamps, a known roll, and an AR process whose VR statistic must reject.

## Minor

1. The data fingerprint does not cover several inputs that determine the results.

   - Evidence: `data_fingerprint` hashes only `tmin/open/high/low` at [s001_feasibility.py:230](/home/mrullldhm/personal/propfirm/propfirm_research/studies/s001_feasibility.py:230). S002 uses that hash at [s002_atlas.py:354](/home/mrullldhm/personal/propfirm/propfirm_research/studies/s002_atlas.py:354) even though it analyses `close`, `volume`, `contract`, the second series, expiries and the EIA CSV.
   - Concrete failure: changing every volume value or a raw contract assignment leaves the recorded front-data hash unchanged while changing liquidity results or roll safety. Changing the EIA calendar is not recorded at all.
   - Fix: hash all consumed columns and separately hash `eia_releases.csv` and the contract-definition file in the manifest.

2. Half-hour liquidity can conflate absent data with zero trading, and the fixed weekday summaries are incomplete.

   - Evidence: [s002_atlas.py:118](/home/mrullldhm/personal/propfirm/propfirm_research/studies/s002_atlas.py:118) counts every absent row as a thin minute. The weekday output at [s002_atlas.py:126](/home/mrullldhm/personal/propfirm/propfirm_research/studies/s002_atlas.py:126) contains only mean RV and mean volume, while item 1 asks for mean, median and p95 by half-hour and weekday.
   - Concrete failure: a feed outage contributes 30 thin minutes and looks like extreme illiquidity. Weekday ranking cannot distinguish a persistent effect from an outlier-driven mean.
   - Fix: report observed-minute coverage separately; count an absent minute as zero-volume only after verifying expected session availability; add median/p95 range, volume and volatility to weekday summaries.

3. Small regime-cell correlation p-values use a normal approximation.

   - Evidence: [s002_atlas.py:64](/home/mrullldhm/personal/propfirm/propfirm_research/studies/s002_atlas.py:64) calculates the correlation t-statistic but [s002_atlas.py:66](/home/mrullldhm/personal/propfirm/propfirm_research/studies/s002_atlas.py:66) evaluates it with a normal CDF.
   - Concrete failure: month and backwardation cells can have only about 30–50 observations, making raw p-values somewhat anti-conservative before BH.
   - Fix: use the Student-t distribution with `n-2` degrees of freedom, or preferably a trading-day/block permutation for serially dependent daily observations.

## Notes / checks that passed

- Cross-day alignment is correct as written. Because evening minutes are indexed to the following CME trading day, `S(20:00,03:00).shift(-1)` at [s002_atlas.py:198](/home/mrullldhm/personal/propfirm/propfirm_research/studies/s002_atlas.py:198), `ny.shift(-1)` at [s002_atlas.py:208](/home/mrullldhm/personal/propfirm/propfirm_research/studies/s002_atlas.py:208), and overnight `shift(-1)` at [s002_atlas.py:209](/home/mrullldhm/personal/propfirm/propfirm_research/studies/s002_atlas.py:209) align predictor trading day \(t\) with the next observed CME trading day. This needs a regression test because reversing the shift would silently introduce look-ahead.

- The prior-day volatility value is causal—the current day receives the previous trading day’s RV at [s002_atlas.py:261](/home/mrullldhm/personal/propfirm/propfirm_research/studies/s002_atlas.py:261)–[263](/home/mrullldhm/personal/propfirm/propfirm_research/studies/S002-atlas.py:263). The full-period `qcut` at [s002_atlas.py:269](/home/mrullldhm/personal/propfirm/propfirm_research/studies/s002_atlas.py:269) does use future distribution information. For an explicitly exploratory atlas this is acceptable as descriptive stratification, but any reported regime edge is a hypothesis, not a deployable causal result. A promoted rule must refit thresholds using past data only or freeze an economically defined absolute/expanding percentile threshold.

- The sign-rule IC at [s002_atlas.py:176](/home/mrullldhm/personal/propfirm/propfirm_research/studies/s002_atlas.py:176) matches S001’s definition—correlation of the directional call with the subsequent raw move, documented at [S001 report.md:56](/home/mrullldhm/personal/propfirm/research/studies/S001-feasibility/report.md:56). The edge is gross, however; ranking should label it `gross_sign_edge_ticks` and compare it with the 4.402-tick stress-cost hurdle.

- One BH pass over all 247 inferential tests is the sensible family because it exactly follows the explicit S002 convention at [PROTOCOL.md:121](/home/mrullldhm/personal/propfirm/research/PROTOCOL.md:121). Including both correlations and sign edges is conservative and preferable to selecting one after seeing results. The defects are the invalid VR p-values, missing per-table q-values and wrong displayed threshold—not the family definition itself.

- I could not rerun pytest in this read-only environment: pytest failed before collection because no writable temporary directory was available. I made no edits and did not rerun the smoke command; the existing 2015–16 quick artifacts were readable.

## Headline numbers I would independently replicate

1. The strongest `q<0.10` half-hour mean return, including its overall mean, q-value and all three block means.
2. Overnight 18:00–09:00 → NY 09:00–16:05 sign IC and gross sign edge.
3. EIA 10:30 five-minute absolute-return multiple, separately versus its local prewindow and matched non-EIA Wednesdays.
4. One corrected session VR—preferably NY at \(q=30\)—using strictly consecutive within-day minutes.
5. Term-structure regime counts and the overnight→NY edge by contango/backwardation using synchronized front/second prices.

**Verdict: FIX FIRST.** The variance-ratio statistics are currently invalid, and several fixed-design event/regime/reporting requirements could materially distort hypothesis ranking.

Codex session ID: 01a14675-58cd-7bc0-a9c9-a54c26211b03
Resume in Codex: codex resume 01a14675-58cd-7bc0-a9c9-a54c26211b03

## Claude's response
All findings accepted. **C1 is a toolkit bug from session 1** (`stats.variance_ratio`, reviewed in R003
without catching it): an extra factor n in delta made z too small by sqrt(n) (AR(1) phi = 0.1, n = 20,000:
z 0.09 instead of ~12). No earlier result used the function, so nothing published was affected. The
old test only checked an iid z < 3; new tests require rejection of AR(1) and roughly correct size.

## Resolution
| # | Finding | Severity | Action | Status |
|---|---|---|---|---|
| C1 | VR z shrunk by sqrt(n) | critical | delta fixed; tests: AR(1) rejects (z > 8), null size ~5% | fixed |
| C2 | VR across days / gaps, minute-level inference | critical | `stats.variance_ratio_days`: q-sums only inside consecutive same-day runs; trading-day bootstrap z | fixed |
| M1 | 1-minute returns over missing minutes | major | `minute_returns` requires consecutive UTC minutes; coverage per bin reported | fixed |
| M2 | EIA strata and multiples | major | normal weeks; matched non-EIA Wednesdays; local pre-window; holiday-week candidate stratum (diluted, labelled) | fixed |
| M3 | settlement window 5 min instead of 14:28-14:30 | major | per-event lengths; settlement 2 minutes | fixed |
| M4 | term structure not synchronised | major | last common minute before 09:00, <= 10 min stale, second must expire after front | fixed |
| M5 | roll weeks missing; DTE out of range | major | roll-week regime (days to the scheduled roll < 7); DTE "other" / missing counted in the manifest | fixed |
| M6 | q-values / blocks not in tables; threshold 0.05 | major | `key_*` -> `q_*` in every inferential table; block estimates added; decision threshold q < 0.10 | fixed |
| M7 | tests miss risky paths | major | tests: missing minute, day break, next-day shift, stale / unsynchronised term structure, expiry order, settlement length, q attach, VR power / size, VR day break | fixed |
| m1 | fingerprint too narrow | minor | all consumed columns + contract; EIA csv hash in the manifest and ledger | fixed |
| m2 | missing vs thin; weekday stats | minor | coverage and thin-of-observed reported separately; weekday median / p95 | fixed |
| m3 | normal p for small correlations | minor | Student-t p (`stats.t_pvalue`) | fixed |
| n | label gross edge | note | `gross_sign_edge_ticks`; costs compared in event paths | fixed |
| n | full-period terciles | note | kept for the exploratory atlas; any promoted rule must use past-only cut points (BACKLOG rule) | noted |
