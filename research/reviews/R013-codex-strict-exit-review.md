---
id: R013
title: Codex review of the D009 strict-exit change and the G8 text sync
status: resolved
item: propfirm_research/grid.py, combine.py (D009, D006 sync)
codex_job: task-mvbrgewe-hajear
created: 2026-10-17
updated: 2026-10-17
---

# R013 — Codex review: strict exits (D009) and G8 sync

## Request (summary)
Read-only, adversarial. The uncommitted diff of `propfirm_research/grid.py` (strict exits, new
`exit_missing` column, `EXIT_TOL` removed), `combine.py` (header, legacy drawdown keys renamed
`dd_limit_d003` / `dd_d003_ok`, only `gate_g8` sets `g8_ok`), `studies/s001_feasibility.py`, the new D009
tests, PROTOCOL §4.6 / glossary and the D009 notes in the S001-S003 reports. Questions: can a valid
window still exit late (all cutoffs, evening windows, DST); is `exit_missing` exact; MFE/MAE, `trade_usd`,
`planted`, `one_trade_day_low`; broken callers; legacy G8 use; test gaps; wording.

## Codex output (verbatim)
# Findings

1. **Moderate — the superseded D003 drawdown rule remains callable and labelled as G8.**  
   **Files:** `propfirm_research/studies/s001_feasibility.py:174`, `:182`, `:197-200`  
   `summarise_b()` converts `dd_d003_ok` back into `g8_seed_share`, recreates `g8_limit`, and `CRITERIA["a_g8"]` actively evaluates `p95_dd <= g8_limit`. Although S001 is historical rather than confirmatory, this leaves executable programme code where the legacy diagnostic is presented as G8, contrary to `research/PROTOCOL.md:154-157`.  
   **Smallest fix:** rename these current-code fields and criterion to unambiguous D003 names such as `dd_d003_seed_share`, `dd_limit_d003`, and `a_dd_d003`. The frozen historical CSVs and report may retain their original terminology.

2. **Minor — the promise to report exact-exit skips is not implemented by all grid callers.**  
   **Files:** `research/decisions/D009-strict-exit.md:26-29`, `research/PROTOCOL.md:152-153`, `propfirm_research/studies/s001_feasibility.py:115-149`, `propfirm_research/studies/s002_atlas.py:445-460`, `propfirm_research/studies/s003_ceiling.py:220-233`  
   D009 and the protocol say missing exact-exit windows are counted in reports. The new settlement caller does this explicitly at `propfirm_research/settlement.py:113-117`, but S001 reports only total sessions and total eligible windows, S002 reports valid-day counts, and S003 converts invalid targets to `NaN`; none separately reports `exit_missing`. A future rerun of those programs would therefore skip the windows without producing the promised count.  
   **Smallest fix:** add `exit_missing` counts to each study’s diagnostics/report output, or centralize mandatory window diagnostics in a shared helper.

3. **Minor — the historical reports’ reproduction commands now use a different fill convention.**  
   **Files:** `research/studies/S001-feasibility/report.md:130-133`, `research/studies/S002-atlas/report.md:121-124`, `research/studies/S003-ceiling/report.md:127-130`  
   Each note correctly says the published results used the earlier tolerant exit and were not rerun, but the immediately following “Reproduce” command invokes current `grid.windows`, which now applies D009. It therefore cannot exactly reproduce the published tables whenever an exact exit bar is missing.  
   **Smallest fix:** label those commands as reruns under the current D009 convention and identify the archived historical outputs/manifests as the reproducible record, or preserve a versioned legacy runner.

# Numbered checks

1. **Strict exits and `exit_missing`**

   No valid window can exit after its computed exit minute. `grid.windows` finds the insertion point with `searchsorted` and now requires `tmin[i1c] == t1` before validity can remain true (`propfirm_research/grid.py:112-116`). This applies uniformly to fixed exits and to FLAT exits after ordinary, short-day, roll, and expiry cutoffs have selected `t1` (`propfirm_research/grid.py:95-111`).

   Evening windows crossing 18:00 use the CME-day-aware `clock_tmin`: times at or after 18:00 are placed on the preceding calendar date (`propfirm_research/grid.py:34-36`). ET wall-clock times are localized and converted to UTC by `local_tmin`, so the UTC offset follows DST (`propfirm_backtest/orb_engine.py:133-137`). I found no path that reintroduces an exit tolerance.

   Under the function’s documented, time-sorted front-series input, `exit_missing` means that the entry/time/flat checks passed but there was no bar at the exact required exit timestamp (`propfirm_research/grid.py:78-80`, `:101-115`). Other known invalid causes leave it false. A contract mismatch at an existing exact exit bar cannot slip through: validity also requires the exit contract to equal the entry contract (`propfirm_research/grid.py:116`). The roll-derived flat cutoff normally invalidates such a window even earlier (`propfirm_research/grid.py:94-107`).

2. **MFE/MAE, `trade_usd`, `planted`, and `one_trade_day_low`**

   I found no regression. `_extremes` continues to measure entry-bar-through-pre-exit-bar excursions over `[i0, i1)`, which matches the stated convention that the exit bar is excluded (`propfirm_research/grid.py:47-64`, `:14`). Strict exits merely make `i1` exact.

   `trade_usd` uses the exact exit-open return and rejects a non-zero trade on any invalid window (`propfirm_research/grid.py:138-144`). `planted` locates the stored exact entry and exit timestamps, bends the pre-exit path over that exact span, and adds the full drift to exit P&L (`propfirm_research/grid.py:181-196`). An adverse gap at the exit open remains captured because `one_trade_day_low` takes the minimum of pre-exit MAE, final P&L, and zero (`propfirm_research/grid.py:199-202`).

3. **Callers, added column, removed constant, and G8**

   No reference to `EXIT_TOL` remains in the repository search. S001-S003 and settlement access window fields by name, so inserting `exit_missing` does not shift positional data or break them. The changed strict rule does alter eligibility on rerun, as intended by D009; the historical-report issue is finding 3.

   The renamed combine fields are internally consistent at `propfirm_research/combine.py:39-41`, `:163-170`, and `:207-211`. Only `combine.gate_g8` sets an output named `g8_ok` (`propfirm_research/combine.py:219-240`). However, S001 still reconstructs and evaluates the legacy rule under G8 labels, as described in finding 1.

   The targeted combine/grid suite passed: **35 passed**. The S001 and settlement suites also passed: **11 passed**. They were run with bytecode writing and Numba JIT disabled to preserve the read-only constraint.

4. **Test sufficiency**

   The new tests cover the core D009 behavior:

   - Ordinary FLAT with a missing exact bar.
   - Fixed exit present and missing.
   - Exact and missing short-day, roll, and expiry cutoffs.
   - Random missing minutes with an assertion that every valid result exits at its requested minute.

   This is adequate for the central regression, but it does not cover all explicitly requested boundaries. In particular, there is no D009-specific test for an exact exit bar carrying a different contract, an evening window crossing 18:00 with a missing exit, or dates on both sides of DST. There is also no direct truth-table test proving `exit_missing` remains false for invalid reasons other than a missing exit bar.

5. **PROTOCOL and D009 consistency**

   The strict-exit wording matches the implementation: exact exit-bar open, no later substitution, entries retaining their five-minute rule (`research/decisions/D009-strict-exit.md:25-29`; `research/PROTOCOL.md:148-153`; `propfirm_research/grid.py:99-116`).

   The G8 wording correctly identifies `combine.gate_g8` and treats D003 drawdown as diagnostic only (`research/PROTOCOL.md:154-157`, `:305-307`). The remaining inconsistency is executable S001 terminology, not the updated protocol text.

   The statement that skipped exits are counted in reports is only partially implemented, as described in finding 2. The three historical exit-convention notes are factually clear, but their reproduction commands need qualification, as described in finding 3.

# Missing tests

1. **Contract changes at the exact exit bar:** entry in contract A, exact exit timestamp present in contract B; assert `valid == False`, `exit_missing == False`, and no return or excursion is emitted.

2. **`exit_missing` reason classification:** separately exercise late/missing entry, fixed exit after flat, entry at/after flat, contract mismatch, and missing exact exit. Assert only the last case sets `exit_missing`.

3. **Evening window crossing 18:00:** test a `20:00 → 03:00` window with the exact 03:00 bar present and then removed; assert exact UTC/ET exit and correct `exit_missing`.

4. **DST coverage:** use CME trading days immediately after both spring-forward and fall-back transitions, preferably with an evening-to-morning window; assert exact ET exit conversion and missing-exit behavior.

5. **Downstream strict-boundary accounting:** remove an exact exit bar and assert that non-zero `trade_usd` and `planted` directions reject the invalid window, while an exact present exit preserves the expected P&L, MAE, and `one_trade_day_low`.

6. **Multi-day randomized missing bars:** run the randomized property over several days, checking exact timestamps per trading day rather than minute-of-day membership in a single-day frame.

Codex session ID: 01a147a1-2934-7740-a7fb-66bb0e02eb89
Resume in Codex: codex resume 01a147a1-2934-7740-a7fb-66bb0e02eb89

## Claude's response
1. **Agree.** S001's current code now uses D003 names: `dd_d003_seed_share`, `dd_limit_d003`, criterion
   `a_dd_d003`. The published S001 CSVs and report keep their original column names (historical record).
2. **Agree.** Skip counts added where windows are built: S001 `part_b` rows / summary `n_exit_missing` and
   its log line; S002 `window_table` column `exit_missing` and manifest `exit_missing_segments`; S003
   `targets()` (DataFrame attrs) and manifest `exit_missing`. The settlement harness already reported them.
3. **Agree.** The three report notes now say the archived outputs are the record and that the Reproduce
   command applies the strict rule, so a rerun can differ slightly.
Missing tests: all six added to `tests/test_research_combine_grid.py` (contract change at the exact exit
bar, reason classification of `exit_missing`, 20:00 -> 03:00 windows on a plain week and the first
sessions after both DST changes, rejection of trades on skipped windows by `trade_usd` / `planted`, and a
multi-day random-missing-bar property on exact timestamps). Grid, S001-S003 and settlement suites: 76
passed.

## Resolution
| # | Finding | Severity | Action | Status |
|---|---|---|---|---|
| 1 | S001 still labels the D003 drawdown check as G8 | moderate | renamed in current code | fixed |
| 2 | skip counts not reported by S001-S003 | minor | counts in rows / tables / manifests | fixed |
| 3 | reproduce commands now run the strict rule | minor | report notes qualified | fixed |
| T1-T6 | missing tests | - | six tests added | fixed |
