---
id: R014
title: Codex blocking review of the H025/H026 settlement harness and cards (before the discovery run)
status: resolved
item: H025, H026, propfirm_research/settlement.py
codex_job: task-mvbrq9bp-g1lg18
created: 2026-10-17
updated: 2026-10-17
---

# R014 — Codex review: H025/H026 harness and cards

## Request (summary)
Read-only, blocking, before any market data were read for H025/H026. Codex reviewed the two cards
(section 4 = frozen definitions from its own R012 Q3), `propfirm_research/settlement.py` and
`tests/test_research_settlement.py`: causality (incl. eligibility, trailing thresholds, rolls, missing
bars, contract check), match between code and cards, statistics and the promotion screen, ledger
accounting, missing tests, and last changes to the frozen definitions. (A first request failed inside
the Codex forwarder: a `-m pytest` in the prompt was parsed as a model name; the resent request was
stopped once this answer arrived, so only one review exists.)

## Codex output (verbatim)
# R014 — Blocking review of H025/H026 settlement discovery harness

## Verdict

**No-go for the discovery run as written.** The numerical family implementation largely matches the cards, but two matters should be resolved before the append-only run: the trade mask uses future window validity and therefore is not fully causal at 14:35, and the ledger records the four-test family twice. The latter would permanently overstate the trial count.

**The frozen definitions should not yet be declared final.** Clarify the missing-exit/contract-change convention, correct the slippage wording, and state explicitly how interior missing signal minutes are treated. No market data have been examined in this review.

## Findings, ranked by severity

### Blocker 1 — The current-day H025 trade mask uses information unavailable at 14:35

**Files:** `propfirm_research/settlement.py:92-103,107-111`; `propfirm_research/grid.py:109-127`; `research/hypotheses/H025-settlement-continuation/card.md:39-45`

**Failure scenario:** `eligible` includes `w_fl["valid"]` and the signal/window contract comparison. `w_fl["valid"]` is not merely an entry-time test: it requires the future exit bar to exist exactly at the computed exit minute and requires its contract to equal the entry contract (`grid.py:109-116`). Therefore, on a day whose 16:05 bar is missing or whose observed exit contract differs, the harness decides retrospectively that no H025 signal occurred (`settlement.py:95-111`). At 14:35, the strategy cannot know whether the 16:05 bar will be missing.

This does **not** contaminate today’s threshold: `trailing_threshold` emits the threshold before appending today and therefore uses only previous eligible days (`settlement.py:72-83`). Previous-day exit validity is known by today. Scheduled short-day, expiry, and roll cutoffs are also intended to be known in advance by `grid` (`grid.py:8-13,95-111`). The narrow look-ahead is current-day outcome observability—especially missing exit data and the realized exit contract—being used to suppress the trade.

D009 expressly declares a missing exact exit bar an invalid window (`research/decisions/D009-strict-exit.md:25-29`), so this is consistent with the project’s chosen backtest convention. It is nevertheless inconsistent with describing the rule as an entirely “causal” executable signal unless the exception is expressly acknowledged. Missingness can also be non-random, so silently treating an attempted but unobservable trade as “no trade” can select the sample.

**Smallest fix:** before the run, amend the frozen definition to say explicitly that this is a complete-window/evaluable-day estimand under D009: a signal that would have been emitted live is retrospectively excluded if its exact exit cannot be evaluated. Report separately:

- causal signals emitted at decision time;
- attempted signals lacking an evaluable exit;
- evaluated trades.

If the intended claim is instead a fully executable live rule, derive the H025 decision mask from information available by entry time and predeclare how attempted trades with unavailable outcomes are handled. Do not silently change between those estimands after seeing results.

### Blocker 2 — The append-only ledger will count one four-test family twice

**File:** `propfirm_research/settlement.py:198-205`

**Failure scenario:** the loop writes one exploratory row for H025 and one for H026, but each row receives:

```python
n_tests=int(tab["in_family"].sum())
```

That value is four on both rows. The permanent ledger therefore represents the shared family as eight tests, although it contains three H025 variants and one H026 variant. The accompanying note says the family is shared, but any aggregation of `n_tests` will double-count it. Accurate trial counting is a core protocol requirement (`research/PROTOCOL.md:14-21,117-126`), and ledger rows are append-only (`propfirm_research/ledger.py:1-4`).

The access arrangement itself is defensible: there is one `load_front` call under H025 with a purpose explicitly naming the joint H025/H026 exploration (`settlement.py:177-180`), and separate exploratory rows are then written for the two items. Internally, that loader writes an “intent” and a “done” access row (`data.py:53-59,82-87`), rather than literally one CSV row, but it is one data-read operation.

**Smallest fix:** allocate `n_tests=3` to H025 and `n_tests=1` to H026, while retaining the shared-family note. Alternatively, put all four tests on one designated family row and use `n_tests=0` on the cross-reference row. The naive row should be explicitly described as a previously established reference, excluded from both BH and the new-test count.

### Major 3 — The cards’ fill wording is directionally wrong or ambiguous

**Files:** `research/hypotheses/H025-settlement-continuation/card.md:43-45`; `research/hypotheses/H026-post-settlement-drift/card.md:31-33`; `propfirm_research/settlement.py:129-155`; `propfirm_research/costs.py:5-19`

**Failure scenario:** both cards say entry open “+ 1 tick” and exit open “+ 1 tick.” Adding the same amount to both prices cancels for a return, and it is wrong for at least one side of each transaction. Adverse slippage is direction-dependent: a long buys above the open and sells below it; a short sells below and buys above.

The implementation itself does not shift fill prices. It computes raw directional gross ticks and subtracts the complete round-trip cost, 2.402 ticks at base and 4.402 at stress (`settlement.py:129-155`; `costs.py:9-19`). That is economically equivalent to one adverse tick per side plus the fee, but the frozen text should not admit a literal same-sign interpretation.

**Smallest fix:** replace both “+ 1 tick” statements with: “Gross return uses the two bar opens; net base subtracts $24.02 per round trip, comprising the $4.02 fee and one adverse tick of slippage on each side. Stress net subtracts $44.02.” No code change is needed.

### Major 4 — The permitted test command did not execute

**Evidence:** `.venv/bin/python -m pytest -q -p no:cacheprovider tests/test_research_settlement.py` exited 1 during pytest initialization. Pytest could not create a capture temporary file because no usable temporary directory was available in `/tmp`, `/var/tmp`, `/usr/tmp`, or the read-only repository. No test was collected or run.

This is an environment failure, not evidence of a code failure. Under the instruction to run the command at most once, it was not retried. Consequently, the test suite is **not verified** in this review.

**Smallest fix:** run the exact command once in an environment with a writable temporary directory before authorizing the discovery run.

### Minor 5 — The promised missing-signal count is incomplete

**Files:** `research/hypotheses/H025-settlement-continuation/card.md:36-39`; `propfirm_research/settlement.py:113-119`

**Failure scenario:** the card says a missing signal endpoint or contract failure means no signal and is “counted.” The only corresponding diagnostic is `signal_missing_on_valid_days`, which counts failures only where the future 14:35-flat window is valid. A day with both a missing signal endpoint and an invalid window is absent from this count. Thus the report cannot recover the total number of signal-definition failures promised by the card.

**Smallest fix:** add a total signal-invalid count over loaded days, plus optional mutually exclusive endpoint-missing, multi-contract, signal/entry-contract mismatch, and window-invalid counts. Retain the current joint diagnostic if useful.

### Minor 6 — BH silently ceases to be a four-hypothesis correction when a p-value is unavailable

**Files:** `propfirm_research/settlement.py:133-138,160-173`; `propfirm_research/stats.py:58-73`; `research/hypotheses/H025-settlement-continuation/card.md:46-53`

**Failure scenario:** a variant with fewer than three trades receives `p_one=NaN`. `bh_qvalues` removes NaNs and uses the number of finite p-values as `m`. Thus the remaining variants would be corrected over fewer than the frozen four hypotheses, while output still describes BH over four. This is unlikely for these high-frequency discovery variants, but it is an avoidable silent weakening of the family correction.

**Smallest fix:** refuse to calculate/promote the family unless all four frozen p-values are finite, or treat a non-testable family member as `p=1` for the frozen four-member BH calculation. Report the variant as inconclusive.

### Minor 7 — The discovery run is not atomic

**File:** `propfirm_research/settlement.py:185-205`

**Failure scenario:** the harness creates output directories and writes four files before appending the two ledger rows. The two ledger writes are also separate. A failure after the market-data read could leave outputs without ledger completion, or an H025 exploratory row without the H026 row. That makes the intended “one discovery run” harder to audit.

**Smallest fix:** prepare all output in a temporary run directory, then finalize it only after successful calculation; pre-validate both ledger payloads and document recovery behavior for failure between the two appends. At minimum, ensure a failed attempt is itself logged rather than rerunning invisibly.

### Nit 8 — Two frozen edge-case conventions remain implicit

**Files:** `research/hypotheses/H025-settlement-continuation/card.md:36-41`; `propfirm_research/settlement.py:55-69,177-183`

First, only the 14:25 and 14:34 endpoints are required. Missing interior minutes are allowed; volume becomes the sum of the bars that exist. That follows from `signals`, but the card could be read as requiring all ten minutes.

Second, “trades per year” is implemented using elapsed calendar span:

```python
(days[-1] - days[0] + 1) / 365.25
```

(`settlement.py:180-183`). This is a reasonable interpretation for the partial 2010 discovery year and is preferable to counting seven year labels, but it should be stated so the MDE denominator is frozen unambiguously.

**Smallest fix:** add one sentence covering both conventions. I would retain the elapsed-calendar-span implementation.

## Numbered review

### 1. Causality — **Issue**

The signal measurements themselves read only bars starting from 14:25 through 14:34 (`settlement.py:55-69`). The move is the last bar’s close minus the first bar’s open, and volume is summed only inside that slice (`settlement.py:58-65`). Entry is at 14:35 or up to five minutes late through `grid.windows` (`grid.py:99-104`), so the 14:34 close is available by the nominal entry.

The trailing thresholds are correctly lagged: the percentile is calculated before today is appended, uses a 60-eligible-day deque, and uses NumPy’s default linear percentile interpolation (`settlement.py:72-83`). Strict comparisons are correctly used (`settlement.py:102-104`). The first 60 eligible observations cannot trade; the 61st eligible day can use the preceding 60.

The signal/window contract check excludes a signal formed in a different contract from the 14:35 entry (`settlement.py:94-103`). `grid` also requires entry and exit to use the same contract and incorporates roll/expiry cutoffs (`grid.py:94-116`).

The issue is the current-day use of future window validity described in Blocker 1. Threshold history is causal; current-day inclusion is complete-case rather than fully decision-time causal.

### 2. Match to the frozen cards — **Issue**

The four implemented variants are correct:

- v1: absolute move strictly above its trailing threshold;
- v2: volume strictly above its trailing threshold;
- v3: union;
- v4: valid 14:30–15:00 short;
- naive continuation: separate reference row.

Evidence: `settlement.py:100-112`. Direction is `sign(move)`, so zero move does not trade (`settlement.py:105-111`). Entry/exit windows match the cards and use strict exits through `grid.windows` (`settlement.py:92-93`; `grid.py:109-127`). Costs are 2.402 and 4.402 ticks (`settlement.py:49-50`; `costs.py:9-19`).

The reference is excluded from BH and promotion (`settlement.py:165-173`). The mismatches are the cards’ slippage wording and incomplete diagnostic counting. The future-validity convention also needs to be made explicit before calling the definitions final.

### 3. Statistics — **Clean, subject to the finite-p caveat**

One trade per day makes the ordinary trade-level t statistic a day-level t. The implementation uses sample SD with `ddof=1`, `n-1` degrees of freedom, and converts the two-sided Student-t p-value to the correct upper-tail one-sided p-value (`settlement.py:129-139`; `stats.py:134-139`).

BH is applied only to the four in-family rows; the reference q-value remains NaN (`settlement.py:160-173`). Discovery blocks exactly match 2010–12, 2013–14, and 2015–16 (`s002_atlas.py:38`; `settlement.py:139-150`). The sign gate requires more than zero in at least two blocks and specifically in the final block (`settlement.py:150-155`).

The promotion inequalities match the card: `q < 0.10`, gross strictly greater than 4.402, and base net at least twice MDE (`settlement.py:149-155,171-173`). The mechanism exists in both cards, while the required design-specific simulation is correctly deferred until after this IID screen (`card.md:55-59`).

The MDE uses gross SD, which equals net SD under a fixed per-trade cost, and uses `5 × trades/year` (`settlement.py:47-50,149`). Trades/year is based on elapsed calendar years of loaded days (`settlement.py:180-183`), not the number of distinct year labels; that is reasonable but should be frozen explicitly.

The daily Sharpe correctly includes no-trade zeros by making an array of all loaded discovery days and placing the `n` net trade returns into it (`settlement.py:145-147`). Their positions do not affect mean or SD. Loaded days, rather than a generic 252-day calendar, form the observed daily series, while annualization uses √252.

### 4. Ledger — **Issue**

One shared `load_front` call is adequate because the purpose names both H025 and H026 (`settlement.py:177-180`), and both are evaluated from the same frame and family. One exploratory row per item is also reasonable for item discoverability.

However, recording `n_tests=4` on each row is not adequate trial accounting. Resolve Blocker 2 before the append-only run. Also note that the loader itself records both intent and completion access rows (`data.py:53-59,82-87`).

### 5. Tests — **Not verified**

The permitted pytest invocation failed before collection because the environment had no writable temporary directory. Static inspection shows useful tests for:

- exclusion of bars outside the signal interval (`tests/test_research_settlement.py:37-47`);
- lagged rolling thresholds (`tests/test_research_settlement.py:50-65`);
- union, direction, v4 short, and warm-up (`tests/test_research_settlement.py:68-80`);
- missing signal endpoint and strict exit (`tests/test_research_settlement.py:83-93`);
- promotion gates and reference exclusion (`tests/test_research_settlement.py:100-120`).

Before trusting the run, add or confirm tests for:

- exact-threshold ties producing no trade;
- move zero producing no trade;
- v2 direction coming from move, not volume;
- signal/entry contract mismatch and multiple contracts inside the signal interval;
- the declared behavior of missing interior signal minutes;
- ineligible gaps not entering the 60-day deque and correct eviction of the 61st-oldest eligible observation;
- late entry at exactly five versus six minutes;
- settlement integration on roll, expiry, and short days;
- attempted signal versus future-invalid outcome counts;
- numerical p-values, four-member BH with a non-testable variant, block boundaries, daily-zero Sharpe, and elapsed-year MDE arithmetic;
- mocked ledger/data calls verifying one shared read, H025/H026 row allocation, and no double-counted tests.

### 6. Changes to frozen definitions — **Issue**

Before data are seen, I would make only clarifying changes, not add variants or tune thresholds:

1. State that missing exact exits are a D009 complete-case convention and distinguish emitted signals from evaluated trades.
2. Rewrite slippage as adverse per-side cost rather than “+1” at both entry and exit.
3. State whether missing interior 14:26–14:33 bars are allowed. The current implementation allows them and sums only observed volume.
4. Define trades/year as trade count divided by the elapsed calendar span from the first through last loaded discovery day.
5. State that a non-testable member does not reduce the frozen BH family below four.

These close ambiguities without reacting to market results.

## Changes required before the discovery run

- Resolve and document the current-day future-validity/complete-case convention.
- Correct ledger trial allocation so the shared family totals four tests, not eight.
- Correct the entry/exit slippage language in both cards.
- Add a total count of signal-definition failures, independent of window validity.
- Prevent BH from silently shrinking below the frozen four-member family.
- Obtain a successful run of the targeted synthetic test file in a writable test environment.

## Optional changes

- Make output and two-item ledger finalization recoverable or atomic.
- Add the missing edge-case and ledger tests listed under item 5.
- Explicitly document interior missing-minute and elapsed-calendar-year conventions.
- Report causal signals emitted, unevaluable outcomes, evaluated trades, and each exclusion reason as separate diagnostics.

Codex session ID: 01a147a8-2aba-7fa2-b730-15dd4862e877
Resume in Codex: codex resume 01a147a8-2aba-7fa2-b730-15dd4862e877

## Claude's response
All findings accepted; no market data had been read. Changes made before the run:
1. **Blocker 1 (current-day validity):** `grid.windows` now also returns `entry_ok` / `entry_contract`
   (decision-time checks only). The harness builds the trailing thresholds and the signal mask from
   decision-time eligibility (signal + `entry_ok` + same contract) and evaluates trades only where the
   window is `valid`. The cards state the D009 complete-case estimand; the output reports `emitted`,
   `unevaluable` and `n` (evaluated) per variant.
2. **Blocker 2 (ledger):** `n_tests` is 3 for H025 and 1 for H026 (`N_TESTS`); the note says the naive
   row is a reference outside BH and the test count. A test checks the allocation, the single data read
   and the manifest.
3. **Major 3 (fill wording):** both cards now say: gross return from the two bar opens; net base subtracts
   $24.02 (fee + one adverse tick per side), stress $44.02. No code change was needed.
4. **Major 4 (tests not run by Codex):** Codex's sandbox had no writable temp directory. Claude ran the
   settlement file: 11 passed; with grid / combine / core: 83 passed.
5. **Minor 5 (counts):** counts over all loaded days: `signal_invalid`, `signal_ends_missing`,
   `signal_multi_contract`, `entry_invalid_1435`, `signal_entry_contract_mismatch`, `eligible`,
   `warmup_eligible`, `valid_*`, `exit_missing_*`, `entry_ok_1430`.
6. **Minor 6 (BH):** an untestable member is marked `inconclusive` and enters BH with p = 1, so the family
   stays at 4 (test added).
7. **Minor 7 (atomicity):** outputs are written to `<stamp>_h025.partial`, renamed only after both ledger
   rows; any exception after the data read appends a `FAILED` exploratory row before re-raising.
8. **Nit 8:** the card states that interior signal minutes may be missing and that trades per year use the
   elapsed calendar span.
Tests added from item 5 of the review: ties and zero moves never signal; v1 / v2 direction from the move;
signal / entry contract mismatch and two contracts inside the signal bars; interior missing minute; entry
5 vs 6 minutes late; CME short day; emitted-but-unevaluable count; BH with an untestable member;
statistics by hand (t, one-sided p, daily-zero Sharpe, MDE, trades per year, block count); a mocked run
(one read, ledger allocation 3 / 1, finalised output directory).

## Resolution
| # | Finding | Severity | Action | Status |
|---|---|---|---|---|
| 1 | trade mask used the current day's exit validity | blocker | decision-time mask + complete-case estimand, counts | fixed |
| 2 | family counted twice in the ledger | blocker | n_tests 3 / 1 | fixed |
| 3 | "+1 tick" fill wording | major | cards reworded | fixed |
| 4 | tests not run in Codex's sandbox | major | run by Claude (11 / 83 passed) | fixed |
| 5 | incomplete signal-failure counts | minor | counts over all days | fixed |
| 6 | BH shrinks with a NaN p | minor | p = 1 for untestable members | fixed |
| 7 | non-atomic outputs | minor | .partial directory + FAILED row | fixed |
| 8 | implicit conventions | nit | stated in the card | fixed |

## Follow-up 1 (Codex job task-mvbs3sdk-0s3694, verbatim)
## Verdict per R014 finding

### Blocker 1 — The current-day H025 trade mask uses information unavailable at 14:35 — PARTIAL

Exit-time look-ahead is resolved: `entry_ok` is captured before exit existence and contract are examined, thresholds and emitted masks use `entry_ok` plus the signal/entry contract match, and only evaluated directions require `valid` (`propfirm_research/grid.py:102-120`; `propfirm_research/settlement.py:105-128`).

However, `entry_ok` may select an entry bar up to five minutes after 14:35 and exposes that future bar’s contract (`propfirm_research/grid.py:102-115,129`). The harness uses both to classify decision-time eligibility (`propfirm_research/settlement.py:105-108`), while the card says this information is known and the signal emitted at 14:35 (`research/hypotheses/H025-settlement-continuation/card.md:41-49`). This is causal if “decision time” means the eventual entry time, no later than 14:40, but not as currently frozen as information known at 14:35.

### Blocker 2 — The append-only ledger will count one four-test family twice — RESOLVED

The allocation is fixed at H025 = 3 and H026 = 1, and the two partitions contain the three H025 variants and one H026 variant respectively (`propfirm_research/settlement.py:59,213-217,228-235`). The card records the same allocation and excludes the naive reference (`research/hypotheses/H025-settlement-continuation/card.md:55-67`).

### Major 3 — The cards’ fill wording is directionally wrong or ambiguous — RESOLVED

Both cards now define gross return from the two opens and subtract the complete adverse round-trip costs rather than adding one tick to both fills (`research/hypotheses/H025-settlement-continuation/card.md:51-54`; `research/hypotheses/H026-post-settlement-drift/card.md:31-37`). The implementation uses the corresponding 2.402- and 4.402-tick costs (`propfirm_research/settlement.py:55-56,169-176`).

### Major 4 — The permitted test command did not execute — PARTIAL

The current test file contains substantive synthetic coverage for causality, counts, BH, statistics, ledger allocation, and successful output finalization (`tests/test_research_settlement.py:55-243`). A successful execution is not verifiable from repository files, and this read-only review did not execute pytest.

### Minor 5 — The promised missing-signal count is incomplete — RESOLVED

Diagnostics are computed over the complete loaded-day index and include total signal invalidity, missing endpoints, multi-contract signals, entry invalidity, contract mismatch, eligibility, warm-up, valid windows, and missing exits (`propfirm_research/settlement.py:99-104,130-140`). Per-variant emitted, unevaluable, and evaluated counts are produced separately (`propfirm_research/settlement.py:181-189`).

### Minor 6 — BH silently ceases to be a four-hypothesis correction when a p-value is unavailable — RESOLVED

An untestable family member is marked inconclusive, replaced by `p = 1` for BH, and barred from promotion (`propfirm_research/settlement.py:191-199`). The test constructs exactly four members and checks the resulting four-member correction (`tests/test_research_settlement.py:196-205`); the cards freeze the same rule (`research/hypotheses/H025-settlement-continuation/card.md:61-65`; `research/hypotheses/H026-post-settlement-drift/card.md:38`).

### Minor 7 — The discovery run is not atomic — NOT RESOLVED

The happy path writes into `.partial`, appends H025 then H026, and renames afterward (`propfirm_research/settlement.py:219-236`). However, the exception guard ends before both success-ledger appends, the rename, and the card-output writes (`propfirm_research/settlement.py:207-227`). Consequently, failure during the second ledger append can leave one success row and an orphan `.partial` directory without a `FAILED` row; failures during rename or later output writes are likewise unlogged. Even failures inside the guarded block append `FAILED` without removing the partial directory (`propfirm_research/settlement.py:220-227`). The new run test exercises only the successful path (`tests/test_research_settlement.py:224-243`).

### Nit 8 — Two frozen edge-case conventions remain implicit — RESOLVED

The H025 card expressly permits missing interior signal minutes and defines the elapsed-calendar-span denominator (`research/hypotheses/H025-settlement-continuation/card.md:34-40,61-65`). The implementation matches both conventions (`propfirm_research/settlement.py:62-78,208-210`).

## Anything new that is broken or newly introduced since R014/R013

- **Major:** The new `entry_ok`/`entry_contract` interface is described as information known at 14:35, although it can depend on a bar arriving as late as 14:40. The executable interpretation is recoverable, but the frozen estimand and code terminology disagree (`propfirm_research/grid.py:102-115,129`; `propfirm_research/settlement.py:105-108`; `research/hypotheses/H025-settlement-continuation/card.md:41-49`).
- **Major:** The new failure-handling test does not inject failures into calculation/output writing, either ledger append, rename, or final card writes, so the incomplete `FAILED`/cleanup path is unexercised (`tests/test_research_settlement.py:224-243`; `propfirm_research/settlement.py:224-240`).
- No other breakage was found statically in the new grid columns, emitted/unevaluable counts, four-member BH calculation, or 3/1 ledger allocation.

NO-GO for the single H025/H026 discovery run — remaining blockers: nominal-14:35 eligibility is not frozen consistently with late entries (`propfirm_research/grid.py:102-115`; `research/hypotheses/H025-settlement-continuation/card.md:41-49`); post-read failure logging and `.partial` cleanup do not cover the ledger/rename/output tail (`propfirm_research/settlement.py:224-240`); successful execution of the targeted tests cannot be verified from the repository (`tests/test_research_settlement.py:55`).

Codex session ID: 01a147b1-cc42-7301-be7e-e0fda85c1c1b
Resume in Codex: codex resume 01a147b1-cc42-7301-be7e-e0fda85c1c1b

### Claude's response to follow-up 1
- Blocker 1 wording: `entry_ok` depends on the entry bar (first bar at or after 14:35, at most 5 minutes
  late), so the eligibility is entry-time, not 14:35. grid.py, settlement.py and both cards now say
  "known by the entry (14:40 at the latest)" (H026: 14:35). The rule stays executable live: the bot
  waits for the first trade at or after 14:35 for up to 5 minutes.
- Minor 7: the try block now also covers both success ledger rows, the rename and the card outputs; on
  failure the `.partial` directory becomes `.failed` and a FAILED row lists the rows already written.
  Two failure-injection tests added.
- Major 4: Codex's sandbox cannot run pytest; Claude's run of the settlement, grid/combine and core files:
  85 passed, 0 failed (13 settlement tests).

## Follow-up 2 (Codex job task-mvbsa9ti-qyeeis, verbatim)
## 1. Item 1 — Entry-time wording: RESOLVED

- `grid.py` distinguishes checks known by the actual entry time from exit-time validity (`propfirm_research/grid.py:4-11`).
- The `entry_ok` assignment uses the corrected wording (`propfirm_research/grid.py:103-121`).
- `settlement.py` defines emission using signal bars, the entry bar and its contract, while evaluation requires the later exit (`propfirm_research/settlement.py:11-22`).
- Eligibility is explicitly described as known by entry, no later than 14:40, and excludes exit information (`propfirm_research/settlement.py:96-122`).
- H025 defines entry-time eligibility, the 14:40 limit, and the entry-time estimand consistently (`research/hypotheses/H025-settlement-continuation/card.md:41-50`).
- H026 correctly states that its 14:30 entry may occur at latest at 14:35 (`research/hypotheses/H026-post-settlement-drift/card.md:29-36`).

No remaining wording implies use of information arriving after the selected entry bar.

## 2. Item 2 — Failure handling: PARTIAL

The main `try` covers computation, `.partial` creation and output, both success-ledger appends, rename, and both card outputs (`propfirm_research/settlement.py:211-240`). The handler renames an existing `.partial` directory to `.failed`, records already-written result rows and the exception in a `FAILED` row, then re-raises (`propfirm_research/settlement.py:241-247`).

Remaining second-order inconsistencies:

- If the H026 ledger append fails, the already-appended H025 row points to the intended final path (`propfirm_research/settlement.py:226-235`), but the handler renames the actual directory to `.failed` (`propfirm_research/settlement.py:241-246`). The append-only success row therefore points to a nonexistent path.
- If a card-output operation fails after `.partial` has already been moved to the final path, `tmp.exists()` is false, so the finalized directory remains named as a successful output despite the new `FAILED` row (`propfirm_research/settlement.py:236-246`).
- `load_front`, timestamp/path initialization, and terminal printing remain outside the handler (`propfirm_research/settlement.py:205-210,248-251`). Failures inside the handler’s rename or `FAILED` ledger append also escape before the explicit re-raise (`propfirm_research/settlement.py:242-247`).

## 3. Test evidence

Both failure-injection tests are substantive rather than vacuous: one forces failure before output creation and checks the sole `FAILED` row and absence of output (`tests/test_research_settlement.py:260-267`); the other forces the second success-ledger append to fail and checks the partial success record, `FAILED` row, `.failed` directory, and absent card output (`tests/test_research_settlement.py:270-286`).

However, the second test accepts the stale output pointer without checking that the H025 ledger row’s `output` exists. There is also no injected failure after the `.partial`-to-final move or inside failure handling itself (`tests/test_research_settlement.py:270-286`). The reported 85-pass/13-settlement-test result exists only as a textual claim in R014 and cannot be independently verified from repository artifacts (`research/reviews/R014-codex-h025-h026-harness-review.md:322`).

NO-GO

Codex session ID: 01a147b1-cc42-7301-be7e-e0fda85c1c1b
Resume in Codex: codex resume 01a147b1-cc42-7301-be7e-e0fda85c1c1b

### Claude's response to follow-up 2
- Item 1: resolved (Codex).
- Item 2: `run_h025` now writes every output first and the ledger rows last (the commit point): `.partial`
  -> final directory -> card CSVs (each written atomically via a .tmp file) -> H025 row -> H026 row. On a
  failure before any result row, every output of the run is set aside (`.failed`, card CSVs of this run
  removed); if a result row was already written, the final directory stays where that row points and gets
  an `INCOMPLETE` marker. Either way a FAILED row lists the rows already written. Outside the handler:
  `load_front` logs its own intent row before reading and a done row after, so a failed read is visible;
  stamp / path set-up cannot touch data; printing happens after the commit. A failure inside the handler
  itself escapes with its own exception, and the access rows still record the look.
- Tests: failure on the second result row (pointer valid, INCOMPLETE marker), failure on the first result
  row and failure while writing a card CSV (outputs set aside, FAILED row only). Evidence file with file
  hashes and verbose output: `data/research/settlement/test_evidence_20261017T023701Z.log` (87 passed:
  settlement 15, grid/combine, core).

## Follow-up 3 (Codex job task-mvbshajs-4m3hqn, verbatim)
## Failure handling — RESOLVED

`run_h025` now follows the intended commit order:

1. Create `.partial` outputs and rename them to the final directory (`propfirm_research/settlement.py:248-251`).
2. Write both card CSVs through temporary files followed by atomic replacement (`propfirm_research/settlement.py:204-208,252-254`).
3. Append H025 and then H026 result rows as the final commit stage (`propfirm_research/settlement.py:255-264`).

On failure before any result row, `_mark_failed` removes completed card CSVs and renames either `.partial` or final output to `.failed` (`propfirm_research/settlement.py:217-225`). After a result row, it preserves the final directory targeted by that row, adds `INCOMPLETE`, records the rows already written in a `FAILED` ledger row, and re-raises the original exception (`propfirm_research/settlement.py:211-225,265-267`).

The tests cover:

- Failure before output creation (`tests/test_research_settlement.py:260-267`).
- Failure on the second result row, including a valid first-row output pointer and `INCOMPLETE` marker (`tests/test_research_settlement.py:285-294`).
- Failure on the first result row and during card output, with outputs set aside and only a `FAILED` row committed (`tests/test_research_settlement.py:297-317`).

Acceptable second-order notes: temporary card `.tmp` files are not explicitly removed if their write or replacement fails; failures inside `_mark_failed` itself remain best-effort; `load_front` and post-commit console printing are outside the handler (`propfirm_research/settlement.py:228-235,268-271`). None compromises the normal single discovery run’s result accounting.

## Test evidence — VERIFIED

The evidence records 87 collected tests and 87 passes (`data/research/settlement/test_evidence_20261017T023701Z.log:10-26,100`). Read-only `sha256sum` produced exact matches for all three recorded files:

- `propfirm_research/settlement.py`: `100034910506441aeda8e3e219c4e44d18c366c8cc754af65212fdb457f6ab48`
- `propfirm_research/grid.py`: `a397aba8888fa595e61ab0c56842b1560c2ffe1d6103512d6832a9e532f7d1c9`
- `tests/test_research_settlement.py`: `2aa542cacb603c131de59d7cebaaab3694783c81e17bfa474294b22edcbd3dd5`

These equal the hashes recorded in the evidence file (`data/research/settlement/test_evidence_20261017T023701Z.log:3-5`).

GO

Codex session ID: 01a147b1-cc42-7301-be7e-e0fda85c1c1b
Resume in Codex: codex resume 01a147b1-cc42-7301-be7e-e0fda85c1c1b

### Resolution after follow-up 3
GO from Codex. The second-order notes (leftover `.tmp` on a failed card write, best-effort handler, `load_front`
and printing outside the handler) are accepted as notes. The single H025/H026 discovery run follows.

### Note: edits after the run (production-eng gate, 2026-10-17)
After the single run, a review subagent's findings were fixed in `settlement.py` (one family map
`FAMILY` / `REFERENCES` instead of name prefixes; `h025_h026` returns `(variants, counts)`; full-schema
`evaluate`; block helpers from S002; cost constants from `costs.py`; one `grid.windows` call; the run
refuses to start if its card outputs exist; the FAILED row is written even if clean-up fails) and in
`grid.py` (a late entry bar may no longer be the exit bar: `tmin[entry] < exit minute`). None changes an
H025 / H026 number (both windows are 30-90 minutes long); the run's ledger code hash `f3595789...` is the
pre-edit tree, and the test-evidence log above predates these edits. Codex is asked to glance at them
with R016.
