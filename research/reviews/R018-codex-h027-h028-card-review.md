---
id: R018
title: Codex blocking review of the H027 / H028 cards and the stage-1 harness
status: resolved
item: H027, H028, propfirm_research.settlement (stage 1)
codex_job: forwarder background task (Codex job id not reported by the forwarder)
created: 2026-10-17
updated: 2026-10-17
---

# R018 — H027 / H028 cards and the stage-1 harness (blocking, before freeze)

## Request (summary)
Read-only, default Codex model, session 4 (2026-10-17), before any H027 / H028 run.

Codex was asked to review:
- both cards (status spec);
- the stage-1 section of `propfirm_research/settlement.py`, line by line against card section 4;
- the stage-1 harness tests.

It also looked for look-ahead or selection risks. Codex could not run tests, so it got the verbose test log
`data/research/stage1/test_evidence_20261017T080518Z.log`, which lists the sha256 of every file under review.
It was given the data facts known before the S004 audit (TAS side coverage, TAS price units,
ts_recv = ts_event before 2017, the mbp-1 tape check, the quote-rule agreement).

## Codex output (verbatim)
## 1. SHA-256 verification

Verified all 16 manifest entries in `data/research/stage1/test_evidence_20261017T080518Z.log` using `sha256sum -c`. Every file reported `OK`, including both cards, the harness, loaders, shared window code, and tests.

I therefore relied on the log's result: **125 passed in 14.40s**. I did not independently execute the tests, any `propfirm_data.stage1` command, or access Databento.

## 2. Findings

### Blocker

**B1 — The "one run only" guard permits rerunning after results have already been computed and exposed**

- Locations: [settlement.py:551](/home/mrullldhm/personal/propfirm/propfirm_research/settlement.py:551), [settlement.py:585](/home/mrullldhm/personal/propfirm/propfirm_research/settlement.py:585), [settlement.py:599](/home/mrullldhm/personal/propfirm/propfirm_research/settlement.py:599), [test_research_stage1_harness.py:322](/home/mrullldhm/personal/propfirm/tests/test_research_stage1_harness.py:322)
- The guard checks only whether the card's `explore.csv` exists. The harness calculates the table, writes `family.csv` and `manifest.json`, then writes the card, and only afterward appends the successful ledger row. If that append fails, `_mark_failed` deletes `explore.csv` and preserves the result directory as `.failed`.
- The failure test confirms exactly this state: no `explore.csv`, but a retained `.failed` directory. It does not attempt a second run. A second call would pass the guard.
- There is also no atomic per-item claim, so concurrent invocations can both pass the initial existence check.
- Bias mechanism: a failed-but-readable run reveals all 2015–16 results, after which the family can be changed or rerun. The ledger records a failure but does not enforce the claimed stopping rule.
- Minimal required change: atomically claim the H027/H028 attempt before the first market-data read, and refuse whenever an in-progress, failed, or completed attempt already exists. Add tests that a run failing after table creation cannot be rerun and that two simultaneous claims cannot both succeed.

### Major

**M1 — The stage-1-specific tests do not prove all causal signs, cutoffs, missing-data branches, and screen conjuncts**

- Locations: [test_research_stage1_harness.py:134](/home/mrullldhm/personal/propfirm/tests/test_research_stage1_harness.py:134), [test_research_stage1_harness.py:189](/home/mrullldhm/personal/propfirm/tests/test_research_stage1_harness.py:189), [test_research_stage1_harness.py:202](/home/mrullldhm/personal/propfirm/tests/test_research_stage1_harness.py:202), [test_research_stage1_harness.py:223](/home/mrullldhm/personal/propfirm/tests/test_research_stage1_harness.py:223)
- The H027 late-report test exercises the 14:35 TAS equality boundary and out-of-window outright trades, but not:
  - the 14:31 TAS equality boundary for v2;
  - late-received in-window outright trades for v3/v4.
- H028's sign test proves only `v1_products`; it does not independently prove the Brent or three-market agreement directions.
- Variant-local missingness tests only missing BZ. They do not prove that missing RB or HO suppresses v1/v3 while leaving v2 intact.
- The stage-1 screen test has negative cases for annual sign, trade count, and concentration, but not isolated failures for q, stress edge, power, inconclusive slots, or the exact 25% boundary. Shared-family tests cover portions of the underlying machinery, but not every stage-1 conjunction.
- Bias mechanism: a later regression in a cutoff, variant sign, missingness mask, or screen condition could pass the current suite and alter which variant survives the single discovery look.
- Minimal required change: add a table-driven test matrix covering both decision-time equality boundaries, late-received in-window trades for both outright variants, all three H028 directions, missing RB/HO/BZ separately, and one isolated failing case plus exact boundary cases for every stage-1 gate.

### Minor

**N1 — `tas_imbalance` does not itself enforce the card's 14:30 TAS close**

- Locations: [H027 card:71](/home/mrullldhm/personal/propfirm/research/hypotheses/H027-tas-settlement-flow/card.md:71), [settlement.py:346](/home/mrullldhm/personal/propfirm/propfirm_research/settlement.py:346), [s004_stage1_data.py:46](/home/mrullldhm/personal/propfirm/propfirm_research/studies/s004_stage1_data.py:46)
- The card limits TAS to the session ending at 14:30. The function filters by trading day, front symbol, spread status, and `known_ns < entry`, but has no `event_ns < 14:30` condition. Thus v1 could accept 14:30–14:34 events and v2 14:30–14:30:59 events.
- S004 has a gating audit condition that rejects any front TAS trade between 14:30 and 18:00, so an accepted audit protects this particular dataset. The harness nevertheless does not implement the stated rule locally.
- Bias mechanism: malformed or future data containing after-close events would change the score while still being known before entry.
- Minimal required change: enforce the half-open TAS session in `tas_imbalance` and test that 14:29:59 is included while 14:30:00 is excluded.

**N2 — The descriptive H025 overlap silently uses evaluated rather than emitted stage-1 signals**

- Locations: [H027 card:92](/home/mrullldhm/personal/propfirm/research/hypotheses/H027-tas-settlement-flow/card.md:92), [H027 card:132](/home/mrullldhm/personal/propfirm/research/hypotheses/H027-tas-settlement-flow/card.md:132), [settlement.py:539](/home/mrullldhm/personal/propfirm/propfirm_research/settlement.py:539)
- `h025_overlap` defines a stage-1 "trade" as `v["dir"] != 0`. `variant_record` zeroes direction when the exact exit is unavailable, so this overlap depends on exit-time validity. H025's side uses its entry-time `emitted` mask.
- This does not affect signals or the screen, but "trade days" is ambiguous and the two sides of the overlap use different estimands.
- Bias mechanism: descriptive overlap can move because an exit bar is missing, even though both signals existed at entry, enabling misleading post-result interpretation.
- Minimal required change: specify emitted or evaluated overlap in the card and use the same definition for both families. Entry-time emitted overlap is the cleaner causal diagnostic.

## 3. Review-area coverage

### 1. Cards

Verified as sound, apart from N1/N2:

- H027's two-by-two family is causal and fixed before outcomes: TAS versus outright flow, crossed with continuation versus unwind.
- Its directions follow the stated mechanisms: `+sign(I)` for residual continuation and `-sign(I)` for temporary-impact unwind.
- The owner-selected mbp-1 source and reported-side-first quote fallback match D010.
- Front-TAS mapping, spread exclusion, strict `ts_recv < decision`, whole-lot 99% coverage, nonzero scores, previous-60-eligible-day percentile, entry-time eligibility, emitted/evaluated distinction, exact exits, costs, four-slot BH family, and stage-1 screen are otherwise determinate.
- H028 fixes the convergence sign before the run. Product, Brent, and agreement variants are fully specified.
- Exact CL/RB/HO endpoints, BZ staleness, market-local previous-20-existing-return volatility, no demeaning/winsorising, variant-local BZ missingness, fills, three-slot BH, and screen are determinate.
- Neither card leaves a direction, threshold, stale-price option, missing-data fallback, or family member to choose after viewing returns.
- The H027 v2 departure from R016 is explicitly disclosed as the pre-look TAS-unwind replacement.

### 2. Harness

Checked every named function:

- `quote_side`: correct ask/bid precedence and rejects missing, locked, crossed, and inside-spread books.
- `coverage_ok`: correctly accepts exactly 1% unsigned and rejects more than 1%.
- `front_tas_symbol`: implements the stated CL-to-CLT month-code mapping.
- `cutoff_ns`: DST-aware ET cutoff, used with strict `<`.
- `tas_imbalance`: front outright, known-at, unique traded instrument and coverage are correct; N1 applies.
- `outright_imbalance`: half-open event windows, strict receive cutoff, reported side first, quote fallback, coverage, and entry-contract enforcement are correct.
- `filtered`: absolute score, previous 60 eligible days, linear percentile, strict `>`, today excluded, zero suppressed.
- `h027`: correct entry contracts, windows, cutoffs, signs, entry-only eligibility, and emitted/evaluated separation.
- `bar_endpoints` / `bar_return`: exact 14:25 open and 14:34 close, same day and contract.
- `bz_endpoints` / `bz_return`: exact-or-stale start, last 14:32–14:34 end, same day and contract, no cross-day carry.
- `trailing_sd`: prior 20 finite observations, today excluded, `ddof=1`.
- `h028`: correct scores, signs, CL-entry contract match, variant-local BZ behavior, and entry-time emission.
- `stage1_table`: all declared screen conjuncts are present; no stage-1 result is marked `promote`.
- `s004_accepted`: requires acceptance and rehashes all audited input tables.
- `h025_overlap`: descriptive only and excluded from screening; N2 applies.
- `run_stage1`: correct period restriction, family sizes, input hash combination, ledger fields, and failure preservation; B1 applies.

The shared `grid.windows` implementation correctly separates `entry_ok` from exact-exit `valid`, permits entries at most five minutes late, and requires the exit bar at the exact exit minute in the same contract.

### 3. Tests

Verified as sound:

- Exact 1% coverage boundary.
- Front-TAS/spread/mapping behavior.
- Basic known-at equality exclusion and outside-window handling.
- H027 continuation versus unwind signs.
- Exact endpoints, contract consistency, no cross-day BZ carry, and BZ staleness.
- Previous-existing-day volatility.
- Missing BZ being local to v2/v3.
- Basic screen behavior and `promote=False`.
- Successful one-run output/ledger behavior, input hashes, S004 hash matching, and preservation of failed outputs.

The unproved cases are listed in M1. The log's pass result is verified evidence for the current files, not evidence for those absent cases.

### 4. Look-ahead and selection risks

Sound:

- Trade records require `ts_recv` strictly before the relevant 14:31/14:35 decision.
- Event windows are half-open.
- Thresholds and volatility scales exclude today and use past eligible/existing observations only.
- Entry eligibility does not depend on exit-bar availability.
- Missing exact exits affect evaluation, not signal emission or thresholds.
- H028 BZ missingness does not remove the products-only variant.
- The 2015–16 screen cannot promote directly to validation; it only permits a new owner decision about 2010–14.
- H025 overlap is not part of BH or the survival screen.

Risks found:

- B1 permits a second result-bearing attempt.
- N1 delegates the TAS-close boundary to S004 instead of enforcing it locally.
- N2 lets exit-time validity affect a descriptive overlap.

Unverified here:

- The full-data S004 audit and R017 review are still pending.
- The supplied empirical data facts and actual 2015–16 data were not independently checked.
- No Databento data or protected-period data were accessed.

**NO-GO to freeze both cards and run each once on 2015–16. Required changes: (1) install an atomic, durable one-attempt guard that also blocks reruns after failed result-bearing attempts; (2) add the missing causal/sign/missingness/screen tests in M1; (3) enforce the TAS 14:30 close in `tas_imbalance`; (4) define and consistently implement emitted-versus-evaluated H025 overlap; (5) complete S004/R017 and obtain S004 acceptance before either run.**

## Claude's response
Agree with every finding. All were fixed before any run, and no H027 / H028 data had been read.

**B1, agree.**
- Before the first data read, `run_stage1` now claims `stage1_attempt.json` in the card folder atomically
  (`O_CREAT | O_EXCL`, the pattern of `prereg.open_run`).
- The marker is never removed. A finished, failed or interrupted attempt blocks every rerun, and the marker
  records DONE or FAILED.
- A refused S004 audit is checked before the claim, so it does not spend the attempt.
- Tests:
  - a run that fails after its table exists cannot be rerun;
  - a second claim fails;
  - a refused audit leaves no marker.

**M1, agree.** The matrix now covers:
- the 14:31 cutoff of v2 against the 14:35 cutoff of v1, using one trade received at 14:31:00;
- late-received in-window trades for v3 and v4, including the equality case;
- each of the three H028 directions, with the CL move planted on that variant's own side;
- missing RB, HO and BZ, each on its own;
- isolated failures of stress, power, years and q (BH forced high);
- an inconclusive slot;
- the strict stress bound (4.40 fails, 4.41 passes);
- the 25-trades-a-year boundary;
- the exact 25% day-share boundary.

One note on that last case. A single day carrying 25% of the gross on two years of data always fails the
power check as well (2 x MDE is about the mean). So that boundary is asserted on its own conjunct, and a case
above it fails the whole screen.

**N1, agree.** `tas_imbalance` keeps only trades with an ET minute before 14:30 or from 18:00, which is the
TAS session of the CME day. A test includes 14:29:59 and the previous evening, and excludes 14:30:00.

**N2, agree.** The overlap now uses emitted (entry-time) masks on both sides. The cards say so, and a test
shows that zeroing every exit leaves the overlap unchanged.

**(5), agree.** The run stays blocked until S004 is accepted and R017 says GO. `s004_accepted` also
re-hashes the audited files.

## Resolution
| # | Finding | Severity | Action | Status |
|---|---|---|---|---|
| B1 | rerun possible after a failed result-bearing attempt | Blocker | atomic, durable `stage1_attempt.json` claimed before any data read; tests | fixed |
| M1 | missing tests for cutoffs, signs, missing data and screen conjuncts | Major | table-driven test matrix (44 harness tests) | fixed |
| N1 | TAS close not enforced in the harness | Minor | session cut at 14:30:00 in `tas_imbalance`; test; card wording | fixed |
| N2 | overlap mixed evaluated and emitted | Minor | emitted masks on both sides; card wording; test | fixed |
| 5 | S004 / R017 before any run | - | S004 all_ok after the R017 amendments; R017 GO (follow-up 1) | resolved |
| F1-F5 | follow-up findings (handler coverage, circular tests, screen anchoring, clean-up masking, DONE-marker recovery) | Major/Minor | fixed in follow-ups 1-5 | resolved (GO in follow-up 6) |

## Follow-up 1 (Codex job task-mvc4ns8e-ck48vn, verbatim)
1. Hash verification: **MATCH** — all 17 files listed in `test_evidence_20261017T081649Z.log` passed `sha256sum -c`; the recorded **151 passed** applies to the current files.

### B1 — NOT RESOLVED

- The S004 audit runs before claiming the attempt, and the claim precedes the first market-data load: [settlement.py:581](/home/mrullldhm/personal/propfirm/propfirm_research/settlement.py:581), [settlement.py:582](/home/mrullldhm/personal/propfirm/propfirm_research/settlement.py:582), [settlement.py:585](/home/mrullldhm/personal/propfirm/propfirm_research/settlement.py:585).
- Claiming uses atomic `O_CREAT | O_EXCL`; existing markers block reruns: [settlement.py:561](/home/mrullldhm/personal/propfirm/propfirm_research/settlement.py:561), [settlement.py:564](/home/mrullldhm/personal/propfirm/propfirm_research/settlement.py:564), [settlement.py:579](/home/mrullldhm/personal/propfirm/propfirm_research/settlement.py:579).
- Normal handled completion/failure records `DONE`/`FAILED`: [settlement.py:626](/home/mrullldhm/personal/propfirm/propfirm_research/settlement.py:626), [settlement.py:628](/home/mrullldhm/personal/propfirm/propfirm_research/settlement.py:628), [settlement.py:630](/home/mrullldhm/personal/propfirm/propfirm_research/settlement.py:630).
- The three requested tests cover duplicate claims, late failure/rerun blocking, and refused-audit behavior: [test_research_stage1_harness.py:489](/home/mrullldhm/personal/propfirm/tests/test_research_stage1_harness.py:489), [test_research_stage1_harness.py:496](/home/mrullldhm/personal/propfirm/tests/test_research_stage1_harness.py:496), [test_research_stage1_harness.py:515](/home/mrullldhm/personal/propfirm/tests/test_research_stage1_harness.py:515).

Residual gap: the first `load_front` call is outside the `try` beginning at line 590. If it raises after the claim, the marker remains nonterminal—neither `FAILED` nor `DONE`—and no test covers that path: [settlement.py:585](/home/mrullldhm/personal/propfirm/propfirm_research/settlement.py:585), [settlement.py:590](/home/mrullldhm/personal/propfirm/propfirm_research/settlement.py:590).

### M1 — NOT RESOLVED

- **Covered — 14:31 versus 14:35 TAS cutoffs:** `test_v2_uses_the_1431_cutoff_and_v1_the_1435_cutoff`, including equality at 14:31:00: [test_research_stage1_harness.py:366](/home/mrullldhm/personal/propfirm/tests/test_research_stage1_harness.py:366).
- **Covered — late in-window outright trades:** `test_late_received_window_trades_are_excluded` covers v3 and v4; v3 includes exact cutoff equality: [test_research_stage1_harness.py:374](/home/mrullldhm/personal/propfirm/tests/test_research_stage1_harness.py:374).
- **Not covered — each H028 direction:** `test_every_h028_variant_trades_toward_its_related_markets` derives the planted outcome from the implementation’s own direction. Reversing a production direction would reverse the plant and still pass: [test_research_stage1_harness.py:389](/home/mrullldhm/personal/propfirm/tests/test_research_stage1_harness.py:389), [test_research_stage1_harness.py:402](/home/mrullldhm/personal/propfirm/tests/test_research_stage1_harness.py:402). The hand calculation at line 408 is disconnected from `h028`.
- **Not fully covered — missing RB/HO/BZ:** all three are parameterized, and v1/v2 locality is proven, but the test never establishes that v3 emitted before removing a market. It can pass when v3 was already false: [test_research_stage1_harness.py:416](/home/mrullldhm/personal/propfirm/tests/test_research_stage1_harness.py:416), [test_research_stage1_harness.py:427](/home/mrullldhm/personal/propfirm/tests/test_research_stage1_harness.py:427).
- **Covered — isolated stress/power/years failures:** `test_screen_isolated_failures`: [test_research_stage1_harness.py:449](/home/mrullldhm/personal/propfirm/tests/test_research_stage1_harness.py:449).
- **Covered — q failure:** forced-high BH q with a previously demonstrated clean fixture: [test_research_stage1_harness.py:444](/home/mrullldhm/personal/propfirm/tests/test_research_stage1_harness.py:444), [test_research_stage1_harness.py:479](/home/mrullldhm/personal/propfirm/tests/test_research_stage1_harness.py:479).
- **Not covered — inconclusive gate:** the two-trade case also fails `trades_ok` and `q_ok`; removing `~inconclusive` from `stage1_pass` would not make the test fail: [test_research_stage1_harness.py:484](/home/mrullldhm/personal/propfirm/tests/test_research_stage1_harness.py:484), [settlement.py:523](/home/mrullldhm/personal/propfirm/propfirm_research/settlement.py:523).
- **Covered — strict stress bound:** 4.40 fails and 4.41 passes: [test_research_stage1_harness.py:461](/home/mrullldhm/personal/propfirm/tests/test_research_stage1_harness.py:461).
- **Covered — exactly 25 trades/year:** [test_research_stage1_harness.py:473](/home/mrullldhm/personal/propfirm/tests/test_research_stage1_harness.py:473).
- **Covered — exact 25% day share:** equality passes its conjunct and above-boundary fails it: [test_research_stage1_harness.py:465](/home/mrullldhm/personal/propfirm/tests/test_research_stage1_harness.py:465).

The 25% argument is **acceptable**. At equality, the concentration necessary over two years inherently defeats the power condition; directly asserting the boundary on `day_share_ok` is therefore the correct test of its inequality.

### N1 — RESOLVED

- `TAS_CLOSE=14:30`, `DAY_START=18:00`, with the half-open session enforced locally: [settlement.py:302](/home/mrullldhm/personal/propfirm/propfirm_research/settlement.py:302), [settlement.py:350](/home/mrullldhm/personal/propfirm/propfirm_research/settlement.py:350), [settlement.py:355](/home/mrullldhm/personal/propfirm/propfirm_research/settlement.py:355).
- The test includes 14:29:59 and an evening trade while excluding 14:30:00: [test_research_stage1_harness.py:357](/home/mrullldhm/personal/propfirm/tests/test_research_stage1_harness.py:357).

Residual gap: none found.

### N2 — RESOLVED

- Both overlap operands use entry-time `emitted` masks: [settlement.py:545](/home/mrullldhm/personal/propfirm/propfirm_research/settlement.py:545), [settlement.py:550](/home/mrullldhm/personal/propfirm/propfirm_research/settlement.py:550), [settlement.py:553](/home/mrullldhm/personal/propfirm/propfirm_research/settlement.py:553).
- The test proves changing evaluated directions/exits does not affect overlap: [test_research_stage1_harness.py:523](/home/mrullldhm/personal/propfirm/tests/test_research_stage1_harness.py:523).
- H027 explicitly defines the diagnostic as emitted-versus-emitted: [H027 card.md:133](/home/mrullldhm/personal/propfirm/research/hypotheses/H027-tas-settlement-flow/card.md:133).

Residual gap: none found.

### Card text — RESOLVED

- H027 now specifies the 14:30 TAS close, emitted/evaluated distinction, emitted overlap, and durable one-attempt rule: [H027 card.md:68](/home/mrullldhm/personal/propfirm/research/hypotheses/H027-tas-settlement-flow/card.md:68), [H027 card.md:93](/home/mrullldhm/personal/propfirm/research/hypotheses/H027-tas-settlement-flow/card.md:93), [H027 card.md:133](/home/mrullldhm/personal/propfirm/research/hypotheses/H027-tas-settlement-flow/card.md:133), [H027 card.md:137](/home/mrullldhm/personal/propfirm/research/hypotheses/H027-tas-settlement-flow/card.md:137).
- H028’s scores, convergence directions, missing-BZ behavior, screen, and attempt marker agree with production code: [H028 card.md:57](/home/mrullldhm/personal/propfirm/research/hypotheses/H028-cross-energy-settlement/card.md:57), [H028 card.md:65](/home/mrullldhm/personal/propfirm/research/hypotheses/H028-cross-energy-settlement/card.md:65), [H028 card.md:74](/home/mrullldhm/personal/propfirm/research/hypotheses/H028-cross-energy-settlement/card.md:74), [H028 card.md:85](/home/mrullldhm/personal/propfirm/research/hypotheses/H028-cross-energy-settlement/card.md:85).
- Both change logs reflect the intended revisions: [H027 card.md:157](/home/mrullldhm/personal/propfirm/research/hypotheses/H027-tas-settlement-flow/card.md:157), [H028 card.md:103](/home/mrullldhm/personal/propfirm/research/hypotheses/H028-cross-energy-settlement/card.md:103).

Residual gap: implementation/test deficiencies above do not require card-definition changes.

### New problems introduced

- **Major:** first-load exceptions leave a permanently claimed but nonterminal marker because `load_front` precedes the exception handler: [settlement.py:585](/home/mrullldhm/personal/propfirm/propfirm_research/settlement.py:585), [settlement.py:590](/home/mrullldhm/personal/propfirm/propfirm_research/settlement.py:590).
- **Minor:** terminal marker updates use non-atomic `write_text`; interruption can truncate the audit marker, although existence still blocks reruns: [settlement.py:572](/home/mrullldhm/personal/propfirm/propfirm_research/settlement.py:572).
- **Minor:** module documentation still describes refusal based only on card outputs, omitting the new attempt marker: [settlement.py:25](/home/mrullldhm/personal/propfirm/propfirm_research/settlement.py:25), [settlement.py:31](/home/mrullldhm/personal/propfirm/propfirm_research/settlement.py:31).

**NO-GO** to freeze both cards, still conditional on R017 and an accepted S004 audit. Minimal changes: bring the first load inside the post-claim failure handler and atomically record terminal status; replace H028 sign tests with independently fixed expected directions; require v3 to emit before each missing-market suppression check; add an inconclusive test where every other screen conjunct passes.

Codex session ID: 01a148f3-9507-7442-ac40-bd7a2c4bbcdd
Resume in Codex: codex resume 01a148f3-9507-7442-ac40-bd7a2c4bbcdd

### Resolution after follow-up 1
Agree with every remaining point. All are fixed; still before any H027 / H028 data read.
- **B1 residual (Major).** The first `load_front` is now inside the failure handler. Any failure after the
  claim records FAILED (ledger row + marker), and a test covers a failure in the first read. The terminal
  marker update is atomic (tmp + replace).
- **M1, H028 directions.** These are now fixed from first principles. On controlled days, RB, HO and BZ rise
  (or fall) 2% from 14:25 to 14:34 while CL stays flat, so each variant must buy (or sell) CL. The expectation
  no longer comes from the code's own output.
- **M1, missing markets.** The test first asserts that every variant (v3 included) fires on the controlled day,
  then removes RB, HO or BZ in turn.
- **M1, inconclusive.** The screen conjunction is now one function (`screen_pass`), tested by a full truth
  table: each condition alone blocks a pass, inconclusive included.
- **Minor.** The module docstring describes the attempt marker.

## Follow-up 2 (Codex job task-mvc4wf06-23f5ik, verbatim)
## 1. Hash verification

All seven files match the SHA-256 values recorded in [test_evidence_20261017T082556Z.log](/home/mrullldhm/personal/propfirm/data/research/stage1/test_evidence_20261017T082556Z.log:2):

- `propfirm_research/settlement.py` — MATCH
- `propfirm_research/data.py` — MATCH
- `propfirm_research/grid.py` — MATCH
- `tests/test_research_stage1_harness.py` — MATCH
- `research/hypotheses/H027-tas-settlement-flow/card.md` — MATCH
- `research/hypotheses/H028-cross-energy-settlement/card.md` — MATCH
- `research/reviews/R018-codex-h027-h028-card-review.md` — MATCH

Mismatches: none. The matched log records 60 passed, including the requested tests ([log:14](/home/mrullldhm/personal/propfirm/data/research/stage1/test_evidence_20261017T082556Z.log:14), [log:41](/home/mrullldhm/personal/propfirm/data/research/stage1/test_evidence_20261017T082556Z.log:41), [log:53](/home/mrullldhm/personal/propfirm/data/research/stage1/test_evidence_20261017T082556Z.log:53), [log:56](/home/mrullldhm/personal/propfirm/data/research/stage1/test_evidence_20261017T082556Z.log:56)). I did not run tests.

## 2. Items 1–5

1. **NOT RESOLVED — post-claim failure handling.** The first data read is now inside the `try` ([settlement.py:600](/home/mrullldhm/personal/propfirm/propfirm_research/settlement.py:600)), and the test independently forces that read to fail and checks both the FAILED marker and ledger row ([test_research_stage1_harness.py:517](/home/mrullldhm/personal/propfirm/tests/test_research_stage1_harness.py:517)). `_close_attempt` writes a temporary file and atomically replaces the marker ([settlement.py:580](/home/mrullldhm/personal/propfirm/propfirm_research/settlement.py:580)). However, operations at lines 594–599 still occur after the claim but before the handler ([settlement.py:593](/home/mrullldhm/personal/propfirm/propfirm_research/settlement.py:593)). Also, `_mark_failed` is called before `_close_attempt`, without a protective `finally`; if failure-ledger recording raises, terminal marker closure is skipped ([settlement.py:637](/home/mrullldhm/personal/propfirm/propfirm_research/settlement.py:637)). Thus the literal guarantee that every post-claim failure records FAILED in both places is not met.

2. **RESOLVED — H028 directions.** Production calculates the three divergence scores and uses their signs directly ([settlement.py:489](/home/mrullldhm/personal/propfirm/propfirm_research/settlement.py:489), [settlement.py:497](/home/mrullldhm/personal/propfirm/propfirm_research/settlement.py:497)), matching the frozen card ([H028 card.md:59](/home/mrullldhm/personal/propfirm/research/hypotheses/H028-cross-energy-settlement/card.md:59)). The fixture independently makes every related market rise or fall 2% while CL remains flat ([test_research_stage1_harness.py:392](/home/mrullldhm/personal/propfirm/tests/test_research_stage1_harness.py:392)). **Yes, a reversed production direction would fail:** `assert var[name]["dir"][UP] == 1.0` and its DOWN counterpart catch it for every named variant ([test_research_stage1_harness.py:406](/home/mrullldhm/personal/propfirm/tests/test_research_stage1_harness.py:406)).

3. **RESOLVED — missing markets.** The test first proves all three variants emit on the controlled day, then deletes RB, HO, or BZ and compares the complete surviving set against a fixed expected set ([test_research_stage1_harness.py:414](/home/mrullldhm/personal/propfirm/tests/test_research_stage1_harness.py:414)). Production constructs each score from its declared market inputs ([settlement.py:478](/home/mrullldhm/personal/propfirm/propfirm_research/settlement.py:478), [settlement.py:489](/home/mrullldhm/personal/propfirm/propfirm_research/settlement.py:489)). A mutation that failed to remove an affected variant would change the emitted set and fail the assertion at line 423.

4. **NOT RESOLVED — screen truth-table coverage.** Current production correctly requires family membership, conclusiveness, and all six declared conditions ([settlement.py:506](/home/mrullldhm/personal/propfirm/propfirm_research/settlement.py:506)). The truth table would catch removal of the explicit `~inconclusive` conjunct because `inconclusive` is hard-coded into its flip list ([test_research_stage1_harness.py:483](/home/mrullldhm/personal/propfirm/tests/test_research_stage1_harness.py:483)). But it derives the other condition names from production’s own `S.SCREEN`; deleting a condition from `SCREEN` deletes it from the test matrix too. In particular, deleting `trades_ok` would evade this test, while the trade-count boundary test checks only the column and not `stage1_pass` ([test_research_stage1_harness.py:467](/home/mrullldhm/personal/propfirm/tests/test_research_stage1_harness.py:467)). The fixed six-condition card specification is therefore not independently anchored ([H027 card.md:121](/home/mrullldhm/personal/propfirm/research/hypotheses/H027-tas-settlement-flow/card.md:121)).

5. **RESOLVED — module docstring.** The stage-1 documentation now says the attempt is claimed atomically after S004 acceptance, before data reads, and identifies the durable marker ([settlement.py:27](/home/mrullldhm/personal/propfirm/propfirm_research/settlement.py:27), [settlement.py:31](/home/mrullldhm/personal/propfirm/propfirm_research/settlement.py:31)).

## 3. New problems

- **Major:** The failure handler does not cover every operation after `claim_attempt`, despite its comment claiming that it does ([settlement.py:593](/home/mrullldhm/personal/propfirm/propfirm_research/settlement.py:593), [settlement.py:600](/home/mrullldhm/personal/propfirm/propfirm_research/settlement.py:600)).
- **Major:** The screen truth table mirrors `SCREEN`, so removal of a condition from that tuple can make both production and the test omit the same required gate ([settlement.py:506](/home/mrullldhm/personal/propfirm/propfirm_research/settlement.py:506), [test_research_stage1_harness.py:483](/home/mrullldhm/personal/propfirm/tests/test_research_stage1_harness.py:483)).

Freeze remains additionally conditional on separate R017 approval and an accepted S004 audit. The two unresolved robustness gaps still block freezing both cards.

NO-GO

Codex session ID: 01a148f9-ba58-73c1-ad9e-6df6412fdaf3
Resume in Codex: codex resume 01a148f9-ba58-73c1-ad9e-6df6412fdaf3

### Resolution after follow-up 2
Agree with both points; both fixed.
- **Claim window.** The claim is now the last statement before the `try`; the stamp and output paths are
  computed before it. In the handler, `_close_attempt(FAILED)` runs in a `finally` around `_mark_failed`, so
  the marker records the failure even if the FAILED ledger row cannot be written. Test:
  `test_marker_is_closed_even_when_the_failed_row_cannot_be_written`.
- **Screen anchoring.** The truth table now uses its own hand-written copy of the card's six conditions
  (`CARD_SCREEN`) and asserts `SCREEN` equals it. Dropping or adding a condition in the code fails the test.

## Follow-up 3 (Codex session 01a148fe-9ab1-7172-9f43-d65520ce3dba, verbatim)
### (a) SHA-256 verification

**MATCH.** Direct `sha256sum` verification matched all five recorded hashes; no mismatches:

- `propfirm_research/settlement.py`
- `tests/test_research_stage1_harness.py`
- H027 card
- H028 card
- R018 review

The hashes are recorded at [test_evidence_20261017T083112Z.log:2](/home/mrullldhm/personal/propfirm/data/research/stage1/test_evidence_20261017T083112Z.log:2), and the log reports 61 passed at [log:76](/home/mrullldhm/personal/propfirm/data/research/stage1/test_evidence_20261017T083112Z.log:76). I did not run tests.

### (b) Item 1 — RESOLVED

- `claim_attempt(item)` is the final statement before the `try`: [settlement.py:599](/home/mrullldhm/personal/propfirm/propfirm_research/settlement.py:599).
- The `try` starts immediately afterward, before the first data read, and covers the processing and result-ledger write: [settlement.py:600](/home/mrullldhm/personal/propfirm/propfirm_research/settlement.py:600), [settlement.py:601](/home/mrullldhm/personal/propfirm/propfirm_research/settlement.py:601), [settlement.py:629](/home/mrullldhm/personal/propfirm/propfirm_research/settlement.py:629), [settlement.py:637](/home/mrullldhm/personal/propfirm/propfirm_research/settlement.py:637).
- The failure handler places `_close_attempt(... status="FAILED")` in a `finally` around `_mark_failed`, so marker closure is attempted even when failure-ledger recording raises: [settlement.py:638](/home/mrullldhm/personal/propfirm/propfirm_research/settlement.py:638), [settlement.py:640](/home/mrullldhm/personal/propfirm/propfirm_research/settlement.py:640), [settlement.py:641](/home/mrullldhm/personal/propfirm/propfirm_research/settlement.py:641).
- `test_failure_in_the_first_data_read_still_closes_the_attempt` forces `load_front` to raise, verifies `FAILED` in both the marker and ledger, and verifies rerun refusal: [test_research_stage1_harness.py:521](/home/mrullldhm/personal/propfirm/tests/test_research_stage1_harness.py:521), [test_research_stage1_harness.py:523](/home/mrullldhm/personal/propfirm/tests/test_research_stage1_harness.py:523), [test_research_stage1_harness.py:526](/home/mrullldhm/personal/propfirm/tests/test_research_stage1_harness.py:526), [test_research_stage1_harness.py:528](/home/mrullldhm/personal/propfirm/tests/test_research_stage1_harness.py:528).
- `test_marker_is_closed_even_when_the_failed_row_cannot_be_written` independently makes `_mark_failed` raise and verifies that the marker nevertheless becomes `FAILED`: [test_research_stage1_harness.py:532](/home/mrullldhm/personal/propfirm/tests/test_research_stage1_harness.py:532), [test_research_stage1_harness.py:535](/home/mrullldhm/personal/propfirm/tests/test_research_stage1_harness.py:535), [test_research_stage1_harness.py:538](/home/mrullldhm/personal/propfirm/tests/test_research_stage1_harness.py:538).
- The evidence log records both tests as passing for the hash-matched files: [log:54](/home/mrullldhm/personal/propfirm/data/research/stage1/test_evidence_20261017T083112Z.log:54), [log:55](/home/mrullldhm/personal/propfirm/data/research/stage1/test_evidence_20261017T083112Z.log:55).

### (c) Item 2 — RESOLVED

- Production declares the six screen conditions independently in `SCREEN`, and `screen_pass` requires all six plus family membership and conclusiveness: [settlement.py:506](/home/mrullldhm/personal/propfirm/propfirm_research/settlement.py:506), [settlement.py:509](/home/mrullldhm/personal/propfirm/propfirm_research/settlement.py:509), [settlement.py:511](/home/mrullldhm/personal/propfirm/propfirm_research/settlement.py:511).
- The test now contains its own hand-written `CARD_SCREEN`, rather than deriving it from production: [test_research_stage1_harness.py:483](/home/mrullldhm/personal/propfirm/tests/test_research_stage1_harness.py:483).
- It asserts multiset equality between production `SCREEN` and `CARD_SCREEN`, then flips family membership, conclusiveness, and each hand-written condition individually and requires every flip to block the pass: [test_research_stage1_harness.py:486](/home/mrullldhm/personal/propfirm/tests/test_research_stage1_harness.py:486), [test_research_stage1_harness.py:487](/home/mrullldhm/personal/propfirm/tests/test_research_stage1_harness.py:487), [test_research_stage1_harness.py:490](/home/mrullldhm/personal/propfirm/tests/test_research_stage1_harness.py:490).
- Those six conditions agree with the card specification: [H027 card.md:121](/home/mrullldhm/personal/propfirm/research/hypotheses/H027-tas-settlement-flow/card.md:121).
- The hash-matched evidence records the test as passing: [log:51](/home/mrullldhm/personal/propfirm/data/research/stage1/test_evidence_20261017T083112Z.log:51).

### (d) New problems

- **Major — the original run exception is masked when `_mark_failed` raises.** In the named second test, the first read raises `"bars unreadable"` and `_mark_failed` then raises `"ledger unwritable"`: [test_research_stage1_harness.py:534](/home/mrullldhm/personal/propfirm/tests/test_research_stage1_harness.py:534), [test_research_stage1_harness.py:535](/home/mrullldhm/personal/propfirm/tests/test_research_stage1_harness.py:535). Although the `finally` closes the marker, the new exception from `_mark_failed` prevents execution from reaching the bare `raise` intended to re-raise the original exception: [settlement.py:637](/home/mrullldhm/personal/propfirm/propfirm_research/settlement.py:637), [settlement.py:639](/home/mrullldhm/personal/propfirm/propfirm_research/settlement.py:639), [settlement.py:642](/home/mrullldhm/personal/propfirm/propfirm_research/settlement.py:642). The test only requires an unspecified `OSError`, so it passes with the wrong exception: [test_research_stage1_harness.py:536](/home/mrullldhm/personal/propfirm/tests/test_research_stage1_harness.py:536). The marker preserves the original error text, but callers receive the cleanup/ledger error instead.
- **Minor — marker closure can itself mask the original exception and leave a nonterminal marker.** `_close_attempt` performs an unguarded marker read, temporary write, and replace, any of which can raise: [settlement.py:580](/home/mrullldhm/personal/propfirm/propfirm_research/settlement.py:580), [settlement.py:582](/home/mrullldhm/personal/propfirm/propfirm_research/settlement.py:582), [settlement.py:584](/home/mrullldhm/personal/propfirm/propfirm_research/settlement.py:584), [settlement.py:585](/home/mrullldhm/personal/propfirm/propfirm_research/settlement.py:585). The current tests cover `_mark_failed` failure, not `_close_attempt` failure.

NO-GO to freeze both cards, conditional on the separate data review R017 and an accepted S004 audit.

### Resolution after follow-up 3
Agree; fixed.
- The handler now catches errors from both clean-up steps (`_mark_failed`, `_close_attempt`). It records them
  in the marker (`problems`) and attaches them as notes, then re-raises the original error.
- If the marker cannot be closed, the claimed marker still exists, so a rerun stays blocked.
- Tests:
  - the original error ("bars unreadable") survives a failing ledger row and a failing marker close;
  - the notes name the clean-up error;
  - a rerun is still refused.

## Follow-up 4 (verbatim summary of the Codex verdicts)
Codex marked (a), (b), (d), (f) and (g) RESOLVED and (c) and (e) NOT RESOLVED. New problems:
- **Major:** the marker cannot record its own close failure.
- **Minor:** clean-up failures that are not `Exception` (KeyboardInterrupt, SystemExit) can still mask the
  original error.

Verdict: NO-GO, also conditional on R017 GO and S004 acceptance. The full text is in the session transcript.

### Resolution after follow-up 4
Both fixed.
- The handler catches `BaseException`, both around the run and around each clean-up step.
- If `_close_attempt` fails, a fresh FAILED marker is written atomically. That write does not read the old
  marker, and if it also fails, a note says so.
- Test: `test_both_cleanups_failing_still_leave_a_failed_marker_and_the_original_error` (46 harness tests
  pass).
- Follow-up 5 is still to be sent.

## Follow-up 5 (Codex, verbatim summary)
Every check RESOLVED:
- the outer handler and each clean-up step catch BaseException;
- a fresh atomic FAILED marker is written when `_close_attempt` fails;
- the fallback's own failure is noted;
- the original error is re-raised;
- the named test passes on hash-matched files.

New Minor: the DONE marker close on the success path has no recovery path. Verdict: NO-GO until that path is
hardened; still conditional on R017 GO and S004 acceptance.

### Resolution after follow-up 5
Fixed. One finisher, `_finish_marker`, closes the attempt on both paths, with the same atomic fallback, and it
never raises.
- On success, a marker-close problem is printed as a warning. The run is already committed in the ledger, and
  the claimed marker still blocks a rerun.
- Test: `test_a_successful_run_survives_a_failed_done_marker_close` (47 harness tests pass).

## Follow-up 6 (combined with R017 follow-up 1; Codex job task-mvcgz3to-rfvqup)
Verbatim in [R017](R017-codex-stage1-data-review.md) (Follow-up 1 section). For this review: R018-FU6 **RESOLVED**, and verdict (b) **GO to freeze both cards and run each once on 2015-16**, after updating the stale STATUS (done).
