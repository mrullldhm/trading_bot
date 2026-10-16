---
id: R008
title: Codex re-check of the R007 fixes to the S002 atlas
status: resolved
item: S002
codex_job: task-mvbg2dd5-fud3ie
created: 2026-10-17
updated: 2026-10-17
---

# R008 — Codex re-check of the S002 fixes

## Request (summary)
Read-only: verify each R007 finding is fixed; look for new bugs in the rewrite and in items 9-11.

## Codex output (verbatim)
## Verification

- **C1 — Fixed.** Extra `n` removed from VR delta at [stats.py:101](/home/mrullldhm/personal/propfirm/propfirm_research/stats.py:101). `variance_ratio_days` builds q-sums within same-day/gap-delimited runs and bootstraps trading days at [stats.py:145](/home/mrullldhm/personal/propfirm/propfirm_research/stats.py:145).
- **C2 — Fixed.** `serial()` retains NaNs and calls `variance_ratio_days` by session at [s002_atlas.py:201](/home/mrullldhm/personal/propfirm/propfirm_research/studies/s002_atlas.py:201).
- **M1 — Fixed.** Returns require adjacent UTC minutes, same contract and trading day at [s002_atlas.py:100](/home/mrullldhm/personal/propfirm/propfirm_research/studies/s002_atlas.py:100).
- **M2 — Fixed.** Normal and holiday-candidate weeks split at [s002_atlas.py:479](/home/mrullldhm/personal/propfirm/propfirm_research/studies/s002_atlas.py:479); local-pre and matched non-EIA-Wednesday multiples at [s002_atlas.py:271](/home/mrullldhm/personal/propfirm/propfirm_research/studies/s002_atlas.py:271); diluted holiday stratum at [s002_atlas.py:302](/home/mrullldhm/personal/propfirm/propfirm_research/studies/s002_atlas.py:302).
- **M3 — Fixed.** Settlement length is two minutes at [s002_atlas.py:50](/home/mrullldhm/personal/propfirm/propfirm_research/studies/s002_atlas.py:50).
- **M4 — Fixed.** Last common pre-09:00 timestamp, ten-minute staleness, and expiry ordering are enforced at [s002_atlas.py:319](/home/mrullldhm/personal/propfirm/propfirm_research/studies/s002_atlas.py:319).
- **M5 — Partly fixed.** Roll-week regime exists, and missing/aggregate `other` DTE counts are recorded at [s002_atlas.py:343](/home/mrullldhm/personal/propfirm/propfirm_research/studies/s002_atlas.py:343). However, `<=0` and `>40` are merged into one `dte_other` count rather than reported separately.
- **M6 — Partly fixed.** BH attachment and `q < 0.10` are correct at [s002_atlas.py:490](/home/mrullldhm/personal/propfirm/propfirm_research/studies/s002_atlas.py:490) and [s002_atlas.py:524](/home/mrullldhm/personal/propfirm/propfirm_research/studies/s002_atlas.py:524). But three-block estimates are absent from VR and incomplete in events/regimes; new `lead_lag` and `event_paths` retain only 2015–16 estimates. Some registered correlation tests also lose their `key_corr`, so their q-values never reach those tables.
- **M7 — Partly fixed.** Missing minutes, day-separated VR, next-day alignment, synchronized/stale term structure, expiry order, settlement length, q attachment, and VR power/size are tested at [test_research_s002.py:28](/home/mrullldhm/personal/propfirm/tests/test_research_s002.py:28). There is still no roll-week test or integrated assertion that every inferential output has all blocks and q-values.

Minors:

- **Fingerprint — Partly fixed.** Close, volume and contract plus OHLC/tmin are hashed, and the EIA CSV is hashed at [s002_atlas.py:111](/home/mrullldhm/personal/propfirm/propfirm_research/studies/s002_atlas.py:111) and [s002_atlas.py:537](/home/mrullldhm/personal/propfirm/propfirm_research/studies/s002_atlas.py:537). It does not literally hash all returned columns (`ts_event_utc`, `trading_day`, `mod`) or the contract-definition file.
- **Coverage/thin and weekday summaries — Fixed** at [s002_atlas.py:155](/home/mrullldhm/personal/propfirm/propfirm_research/studies/s002_atlas.py:155).
- **Student-t correlation p-values — Fixed** at [stats.py:135](/home/mrullldhm/personal/propfirm/propfirm_research/stats.py:135) and [s002_atlas.py:88](/home/mrullldhm/personal/propfirm/propfirm_research/studies/s002_atlas.py:88).

Items 9–11 are present and the newest smoke folder contains all three outputs. **New major bug:** `lead_lag` and `event_paths` register both correlation and edge tests through `predict()` but only retain the edge key at [s002_atlas.py:453](/home/mrullldhm/personal/propfirm/propfirm_research/studies/s002_atlas.py:453) and [s002_atlas.py:470](/home/mrullldhm/personal/propfirm/propfirm_research/studies/s002_atlas.py:470). Thus displayed correlations have neither q-values nor full block estimates.

**Verdict: not yet OK for the headline run.** The critical numerical defects are closed, but M6 must be completed: expose every registered test’s q-value and all three block estimates in each inferential table, especially VR, regimes, lead-lag and event paths. Add the corresponding schema/roll-week tests. Pytest could not run in the read-only environment because no writable temporary directory exists.

Codex session ID: 01a1467d-3d84-74d1-a29f-b83891fa4ba5
Resume in Codex: codex resume 01a1467d-3d84-74d1-a29f-b83891fa4ba5

## Claude's response
All accepted; none changes a number (the test set and BH pass are the same), they complete the reporting.
While adding block columns, a further problem showed up that neither review had named: variance ratios
on consecutive *traded* minutes select fast markets in thin hours (Asia VR(60) 2.0-2.6 by block vs 1.37
pooled). Codex's R007 wording ("complete consecutive minute grids") was the right fix: VRs now use a
filled minute grid (no-trade minute = unchanged price). Asia then mean-reverts (VR 0.78), consistent
across blocks.

## Resolution
| # | Finding | Action | Status |
|---|---|---|---|
| M5 | DTE <= 0 and > 40 merged | separate labels and manifest counts | fixed |
| M6 | blocks / q missing in VR, regimes, lead_lag, event_paths; corr keys dropped | all three blocks and both q-values (corr and edge) in every inferential table; runtime check that every registered test appears in a table | fixed |
| M7 | roll-week and schema tests | `roll_week_label` test; schema enforced at run time | fixed |
| m | fingerprint | adds trading_day and mod (ts_event_utc is the source of tmin; contract-definition file unchanged, noted) | partly |
| new | VR selection on traded stretches | filled minute grid (`filled_minutes`) + test | fixed |
