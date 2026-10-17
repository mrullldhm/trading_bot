---
id: R017
title: Codex review of the stage-1 data code, conversion, loaders and the S004 audit
status: resolved
item: propfirm_data.stage1, propfirm_data.stage1_convert, propfirm_research.data, propfirm_research.prereg, S004
codex_job: task-mvcgeu37-f9fppq
created: 2026-10-17
updated: 2026-10-17
---

# R017 — Stage-1 data: money, conversion, loaders, S004

## Request (summary)
Read-only, default Codex model, session 4. The prompt is kept in `data/research/stage1/r017_prompt_draft.md`;
the version sent added the S004 results.

Codex reviewed:
- the paid downloader (money rules);
- the DBN -> parquet conversion;
- the firewall loaders and the prereg per-file hashes;
- the S004 audit and its acceptance rules, including the disclosed quote-rule change;
- the R016 Q4 test list;
- the post-run harness edits promised at the end of R014.

Codex was also asked to rule on a proposed amendment: S004's after-close rule fails on 2 TAS trades stamped
in the first second after 14:30. Evidence log: `data/research/stage1/test_evidence_20261017T134420Z.log`.

## Codex output (verbatim)
## Q1 — Money

**Major — the whole-line reservation is an estimate, not a hard billing cap.** `propfirm_data/stage1.py:340-353,428-443,458-464`; `research/decisions/D010-stage1-data-purchase.md:75-79`. Line 6 reserves a 20-day sample extrapolation plus 10%, then submits 522 requests without obtaining their individual costs. Actual charges could therefore exceed the reservation—and theoretically the $15 cap—even though `reserved_total()` remains below it. Fix: verify and record the actual portal charge now; for future purchases, quote and reserve every day or obtain a vendor-guaranteed whole-line ceiling before submission.

No other money path found. Range and batch calls are durably reserved before submission (`stage1.py:193-203,224-244,304-317`), all reservations remain in the cap (`stage1.py:146-152`), and an uncertain request blocks further spending unless explicitly retried with another reservation (`stage1.py:287-299,394-421,446-464`). The current manifest contains no uncertain requests; its line reservation remains `RESERVED`, while all actual requests are `DONE`.

## Q2 — Conversion

**Major — conversion provenance trusts recorded raw hashes instead of verifying the files it reads.** `propfirm_data/stage1_convert.py:301-320`. `raw_input_hashes()` copies hashes from the purchase manifest but `convert_all()` never checks the current raw bytes against them. A changed raw file could therefore produce new H027/H028 inputs while `convert_manifest.json` continued to claim the old input hash. Fix: hash every raw input immediately before reading, compare it with `stage1.json`, and abort on a missing, extra, or mismatched file.

For this purchase, I independently hashed all 617 raw files named by the purchase manifest: all 617 match. Thus this is a reproducibility weakness, not evidence that the present parquet is wrong.

No timestamp, unit, ordering, partition, or de-duplication defect was found:

- TAS differentials are checked as integral `price / 1e9` ticks and spreads are cross-checked against definitions (`stage1_convert.py:186-201`).
- CL, RB/HO, and BZ tick conversions are explicit (`stage1_convert.py:230-248,256-269`).
- UTC-year partitioning is deliberate, with period filtering later done by CME trading day (`stage1_convert.py:128-144`; `data.py:256-260`).
- Conversion sorts stably and does not deduplicate trades (`stage1_convert.py:135-143,186-211,256-289`). The repeated trade rows documented in `sample_check.json:103-112` are retained.
- The MBP-1 trade rows preserve their carried bid/ask (`stage1_convert.py:256-269`). The repository records the day-one previous-record/pre-trade-book check at `research/journal/2026-10-17-04.md:34-38`; S004 additionally obtains exact CL bar-volume equality over all 7,505 compared minutes (`facts.json:47-51`).
- Raw-symbol attachment is time-aware and rejects unmapped MBP trades (`stage1_convert.py:272-289`; `propfirm_data/convert.py:71-90`).

The record-count break is real: the conversion manifest has TAS 212,015 → 107,523 records and CL MBP trades 3,987,574 → 1,691,486 (`convert_manifest.json:5-20`). My direct read found volume fell much less—TAS 9.57m → 7.08m lots and CL 7.72m → 6.26m—while average record size rose materially. This is an inference consistent with changed message/fill aggregation. It does not directly bias H027 because its signals are size-weighted, not record-count-weighted, and CL minute volume matches bars exactly. Record counts must not be used as an economic feature or longitudinal quality metric without modelling this structural break.

## Q3 — Loaders and R016 Q4

**Major — registered code is not rechecked before a protected run.** `propfirm_research/prereg.py:72-95,108-120,141-157`. Registration stores only one aggregate `code_sha256`; `open_run()` checks per-file data hashes but never checks current code. Modified signal or transformation code could therefore open validation/holdout under an obsolete preregistration. Fix: store per-file code hashes and validate all of them before creating the one-shot marker, just as data files are checked.

**Minor — access logging is less complete than R016 specified.** `propfirm_research/data.py:129-167`. Terminal rows include the combined processed-file digest, row count, trading-day range, event-time range, and returned-frame digest, but omit receive/reference ranges, per-file hashes, raw instruments, definitions/transformation hashes, and explicit decision cutoffs. Fix: add those fields to the access artifact or a linked machine-readable manifest.

**Minor — correction/cancel semantics lack the promised fixture.** `propfirm_data/stage1_convert.py:186-211,256-269`; `tests/test_stage1_convert.py:109-113`. The existing test merely proves that a non-`T` TAS record is discarded; it does not demonstrate duplicate-sequence, correction, or cancellation treatment. Fix: document the schema semantics and add the exact R016 correction/cancel/duplicate fixture. Actual TAS input contained zero non-trade records (`convert_manifest.json:5-9`), reducing the present-data risk.

Before 2017, using `ts_recv` is equivalent to the documented `ts_event` fallback because every record has flag 8 and the timestamps are equal (`sample_check.json:94-101`). Strict equality exclusion is correctly implemented (`data.py:324-335`).

### R016 Q4 test coverage

| R016 rule | Covered | Missing / limitation |
|---|---|---|
| Receive-time known-at, equality, late reports | `test_trade_known_at_uses_ts_recv_and_equality_is_excluded`, `tests/test_research_stage1_data.py:80`; window test at `tests/test_research_stage1_harness.py:374` | Harness file’s current hash is not covered by the supplied test run |
| `ts_recv < ts_event` rejection | `test_received_before_event_is_rejected_and_logged`, `test_research_stage1_data.py:88` | — |
| Unknown side not zero | `test_side_codes`, `test_research_stage1_data.py:115`; 1% boundary at `test_research_stage1_harness.py:255` | Boundary test currently lacks verified evidence |
| TAS front mapping / spread exclusion | `test_front_tas_symbol_rule_is_shared_with_the_harness`, `tests/test_research_s004.py:54`; session/mapping tests in harness | No standalone ambiguous-map loader fixture |
| Contract roll within signal | `test_endpoints_need_one_contract_and_never_carry_across_days`, `test_research_stage1_harness.py:266` | Current harness hash unverified |
| CME-day DST boundary | `test_cme_day_boundary_every_loader`, `test_research_stage1_data.py:95`; core boundary test at `tests/test_research_core.py:29` | — |
| Period by trading day | `test_period_cut_by_trading_day_not_utc_year`, `test_research_stage1_data.py:108` | — |
| Backward-only warm-up | `test_warmup_reaches_back_only`, `test_research_stage1_data.py:190` | — |
| Live/matching token | `test_protected_periods_need_a_matching_live_token_for_every_loader`, `test_research_stage1_data.py:167` | — |
| Statistics revisions/deletes | `test_statistics_asof_ignores_later_revisions_and_honours_deletes`, `test_research_stage1_data.py:132` | — |
| `ts_ref` and OI availability | `test_statistics_session_from_ts_ref_and_open_interest_timing`, `test_research_stage1_data.py:148` | — |
| BZ staleness/no cross-day fill | `test_endpoints_need_one_contract_and_never_carry_across_days`, `test_research_stage1_harness.py:266` | Current harness hash unverified |
| Variant-local related missingness | `test_missing_related_market_removes_only_its_variants`, `test_research_stage1_harness.py:414` | Current harness hash unverified |
| Runtime data hashes | `test_runtime_hash_mismatch_aborts_before_rows_are_returned`, `test_research_stage1_data.py:200` | Code hashes are not checked |
| Intent + one terminal row | `test_every_attempt_has_an_intent_and_one_terminal_row`, `test_research_stage1_data.py:213` | Detailed R016 metadata is incomplete |
| No alternate reader | `test_no_bar_reads_outside_data_module`, `tests/test_research_core.py:222` | — |
| Corrections/cancels/duplicates | — | Missing |

## Q4 — S004 and H027/H028 readiness

**Major — BZ has no acceptance gate.** `propfirm_research/studies/s004_stage1_data.py:40-52`. BZ is essential to H028-v2/v3, but acceptance gates only RB and HO. Current BZ coverage is healthy at 97.39% (`facts.json:14-22`), so adding a ≥95% or explicitly chosen ≥97% rule would pass, but the omission allows a future degraded BZ input to be accepted. Fix: add a BZ signal-endpoint coverage rule and disclose that it was added after the first audit.

**Minor — the quote-rule “mis-signed volume share” uses a count error rate.** `s004_stage1_data.py:139-157`. It multiplies unknown-side volume by count-weighted classification error, understating the estimate when contradictory trades are larger. My direct calculation gives volume-weighted accuracy 91.84% and estimated unknown-side mis-sign share 0.586%, versus the reported 95.33% and 0.335%. Both still pass the 80%/1% rules. Fix: weight agreement and contradiction by `size`, rename the figure as an estimate, disclose the corrected values, and rerun S004.

The quote-rule change is legitimate as an explicitly disclosed engineering calibration, not as untouched preregistered evidence. The primary ≤1% tolerance already comes from H027’s data-quality rule (`H027 card:79-86`); the 80% sanity floor was selected after seeing day one and must remain labelled as such. The full-period result still passes after correct volume weighting.

The proposed 14:30:01 rule is legitimate. Both exceptional trades fall within 48 ms of the official close, none occurs at or after 14:30:01, and the signal code independently excludes every event at or after 14:30:00 (`settlement.py:351-362`; `H027 card:71-77`). This amends a data-quality tolerance without changing any signal input. Implement it using nanosecond timestamps—not minute-of-day—and disclose the two records.

The other S004 figures are adequate: exact CL trade/bar volume, contract agreement, settlement/VWAP consistency, unique TAS mapping, and source coverage are strong (`facts.json:13-61`). H027 retains 480 of 499 front-TAS days under its 99% side rule (`facts.json:28-33`), and H028’s current endpoint coverage is ample.

At present, H027/H028 remain mechanically blocked because S004 says `all_ok: false` (`facts.json:63-75`) and the harness refuses such an audit (`settlement.py:538-550`).

## Q5 — R014 post-run harness edits

No logic defect found in the requested edits:

- `FAMILY` and `REFERENCES` separate tested rows from the descriptive reference (`settlement.py:68-69,262-266`).
- `evaluate()` emits a complete schema even for untestable rows (`settlement.py:159-195`).
- `run_h025()` refuses if either card output exists (`settlement.py:247-251`).
- `_mark_failed()` records a FAILED row even when cleanup fails (`settlement.py:224-244`), covered by `tests/test_research_settlement.py:315`.
- A late entry can no longer equal the exit bar (`grid.py:103-122`); a focused test exists at `tests/test_research_combine_grid.py:394`.

**Major — the current stage-1 harness lacks applicable test evidence.** `data/research/stage1/test_evidence_20261017T134420Z.log:1,8,14`. Hash verification found:

- `settlement.py`: expected `5b0bea…`, current `bd2c12…`;
- `test_research_stage1_harness.py`: expected `9929ea…`, current `29fcec…`;
- `R018-codex-h027-h028-card-review.md`: expected `8cf064…`, current `5d6048…`.

Every other one of the 25 listed artifacts matched. Consequently, the 153-pass result applies to the reviewed downloader, converter, loaders, S004, core tests, grid, and settlement tests, but not to the current settlement implementation or current stage-1 harness tests. Fix: produce fresh evidence hashing and exercising the current harness, including the late-entry grid test and all S004 amendments, before claiming the one-shot runs are safe.

VERDICT: NO-GO
14:30:01 AMENDMENT: ACCEPT — it tolerates only sub-second close-time matching while the H027 signal independently excludes all trades at or after 14:30:00; disclose the two records and implement the audit boundary at timestamp precision.
REQUIRED FIXES:
1. **Major:** Amend S004 to the 14:30:01 timestamp rule, add a BZ coverage gate, correct the quote-rule calculation to volume weighting, disclose all changes, and rerun S004 once.
2. **Major:** Generate fresh hash-bound test evidence for the current `settlement.py`, current stage-1 harness tests, the amended S004, and the late-entry grid regression.
3. **Major:** Verify and record the actual vendor charge; replace sampled whole-line reservations with a true per-request or vendor-guaranteed ceiling before any future paid run.
4. **Major:** Make conversion verify every raw input hash against the purchase manifest before reading it.
5. **Major:** Store and verify per-file code hashes before a protected run writes its one-shot marker.
6. **Minor:** Complete the R016 access metadata and add documented duplicate/correction/cancel fixtures.

Codex session ID: 01a14a20-c1d5-7002-81e5-d29a777a704c
Resume in Codex: codex resume 01a14a20-c1d5-7002-81e5-d29a777a704c

## Claude's response
Agree with every finding. Fixed in this session:
1. **S004 amendments (Major, item 1).** All disclosed in the S004 docstring and report:
   - the after-close rule now counts front TAS trades from 14:30:01, at timestamp precision; the first-second
     matches are counted apart and listed;
   - a BZ coverage rule (>= 0.95) was added;
   - the quote-rule accuracy and the mis-sign estimate are now weighted by volume.

   S004 was rerun once and **all 12 rules pass**. Volume accuracy is 91.84% and the mis-sign estimate is
   0.586%, both exactly Codex's independent figures.
2. **Fresh evidence (Major, item 2).** A new hash-bound log covers the current `settlement.py`, the stage-1
   harness tests, the amended S004 and its outputs, and the late-entry grid regression
   (`tests/test_research_combine_grid.py`).
3. **Vendor charge (Major, item 3).** The owner checks the Databento portal; expected about $9.52.
   - A true per-request reservation (a quote per day) is made a precondition of the next paid run in STATUS.
   - The 2010-14 purchase needs new items and a new decision anyway.
   - The present purchase is complete with no uncertain request.
4. **Raw-input verification (Major, item 4).** `verify_raw_inputs()` hashes every DBN file before conversion
   and refuses missing, extra or changed files. The real reconversion verified 597 files, and the output
   parquet is byte-identical. Tested.
5. **Code hashes (Major, item 5).** `prereg.register` stores per-file code hashes, and `open_run` checks both
   maps before writing its marker. A test checks that a changed code file is refused and the marker is not
   written.
6. **Minor (item 6).**
   - Access rows now also carry the receive-time (`known_ns`) and session ranges.
   - The trades-schema semantics are documented: trade events only, no correction or cancel records.
   - A test shows identical fills are kept.
   - The full per-file / raw-instrument metadata in every access row is deferred. The combined file digest is
     already in the row, and per-file hashes are in the convert manifest.

The record-count break (2015 -> 2016) is noted in KNOWLEDGE: record counts must never be an economic feature.

## Resolution
| # | Finding | Severity | Action | Status |
|---|---|---|---|---|
| 1 | S004 amendments (14:30:01, BZ gate, volume weighting) | Major | done, disclosed, S004 rerun once: all_ok | fixed |
| 2 | fresh hash-bound evidence | Major | new log for all current files incl. the grid regression | fixed |
| 3 | vendor charge; per-request reservation for future runs | Major | owner checks the portal; per-day quotes required before the next purchase (STATUS) | open (owner / next purchase) |
| 4 | conversion trusts recorded raw hashes | Major | `verify_raw_inputs` before converting; tested; 597 files verified | fixed |
| 5 | code not rechecked before a protected run | Major | per-file code hashes, checked by `open_run` before the marker; tested | fixed |
| 6 | access metadata, duplicate/correction fixture | Minor | ranges added, semantics documented, duplicate test; full per-file metadata deferred | partly fixed |
| A | 14:30:01 amendment | - | accepted by Codex; implemented at timestamp precision | done |

## Follow-up 1 (combined with R018 follow-up 6; Codex job task-mvcgz3to-rfvqup, verbatim)
## 1. Per-item findings

| Item | Verdict | File:line evidence | One-line reason |
|---|---|---|---|
| R017-1 | RESOLVED | [s004_stage1_data.py:12](/home/mrullldhm/personal/propfirm/propfirm_research/studies/s004_stage1_data.py:12), [s004_stage1_data.py:45](/home/mrullldhm/personal/propfirm/propfirm_research/studies/s004_stage1_data.py:45), [s004_stage1_data.py:137](/home/mrullldhm/personal/propfirm/propfirm_research/studies/s004_stage1_data.py:137), [s004_stage1_data.py:153](/home/mrullldhm/personal/propfirm/propfirm_research/studies/s004_stage1_data.py:153), [facts.json:65](/home/mrullldhm/personal/propfirm/research/studies/S004-stage1-data/facts.json:65) | The disclosed nanosecond 14:30:01 rule counts first-second matches separately, BZ has a ≥95% endpoint gate, and quote accuracy/mis-sign are volume-weighted; all 12 rules pass. |
| R017-2 | RESOLVED | [evidence log:2](/home/mrullldhm/personal/propfirm/data/research/stage1/test_evidence_20261017T140154Z.log:2), [evidence log:136](/home/mrullldhm/personal/propfirm/data/research/stage1/test_evidence_20261017T140154Z.log:136), [evidence log:173](/home/mrullldhm/personal/propfirm/data/research/stage1/test_evidence_20261017T140154Z.log:173), [evidence log:233](/home/mrullldhm/personal/propfirm/data/research/stage1/test_evidence_20261017T140154Z.log:233), [evidence log:235](/home/mrullldhm/personal/propfirm/data/research/stage1/test_evidence_20261017T140154Z.log:235) | Fresh hash-bound evidence covers the current harness, S004 amendments, preregistration fix, and late-entry regression, with 200 passes. |
| R017-3 | AGREE | [STATUS.md:17](/home/mrullldhm/personal/propfirm/research/STATUS.md:17) | The actual charge remains an owner check, while per-day quotes and reservations are explicitly mandatory before another purchase; this does not affect the completed data’s validity. |
| R017-4 | RESOLVED | [stage1_convert.py:298](/home/mrullldhm/personal/propfirm/propfirm_data/stage1_convert.py:298), [stage1_convert.py:312](/home/mrullldhm/personal/propfirm/propfirm_data/stage1_convert.py:312), [test_stage1_convert.py:122](/home/mrullldhm/personal/propfirm/tests/test_stage1_convert.py:122), [convert_manifest.json:22](/home/mrullldhm/personal/propfirm/data/research/stage1/convert_manifest.json:22) | `verify_raw_inputs` checks missing, extra, and changed DBN inputs before conversion; the manifest records 597 verified files. |
| R017-5 | RESOLVED | [prereg.py:72](/home/mrullldhm/personal/propfirm/propfirm_research/prereg.py:72), [prereg.py:83](/home/mrullldhm/personal/propfirm/propfirm_research/prereg.py:83), [prereg.py:109](/home/mrullldhm/personal/propfirm/propfirm_research/prereg.py:109), [prereg.py:143](/home/mrullldhm/personal/propfirm/propfirm_research/prereg.py:143), [test_research_core.py:352](/home/mrullldhm/personal/propfirm/tests/test_research_core.py:352) | Registration stores per-file code/data hashes, and `open_run` validates both maps before creating the one-shot marker; the test changes code and confirms no marker appears. |
| R017-6 | ACCEPTABLE | [data.py:133](/home/mrullldhm/personal/propfirm/propfirm_research/data.py:133), [stage1_convert.py:186](/home/mrullldhm/personal/propfirm/propfirm_data/stage1_convert.py:186), [test_stage1_convert.py:116](/home/mrullldhm/personal/propfirm/tests/test_stage1_convert.py:116) | Receive/session ranges were added, schema semantics are documented, and identical fills are retained; deferring richer per-file access metadata is acceptable because combined digests and the conversion manifest preserve current-run provenance. |
| R018-FU6 | RESOLVED | [settlement.py:580](/home/mrullldhm/personal/propfirm/propfirm_research/settlement.py:580), [settlement.py:588](/home/mrullldhm/personal/propfirm/propfirm_research/settlement.py:588), [settlement.py:654](/home/mrullldhm/personal/propfirm/propfirm_research/settlement.py:654), [settlement.py:665](/home/mrullldhm/personal/propfirm/propfirm_research/settlement.py:665), [test_research_stage1_harness.py:591](/home/mrullldhm/personal/propfirm/tests/test_research_stage1_harness.py:591) | `_finish_marker` supplies the same non-raising atomic fallback on FAILED and DONE paths; the success test forces `_close_attempt` to fail, preserves the committed run, writes DONE, and confirms rerun refusal. |

## 2. R017-1 figures

- Volume-weighted quote-rule accuracy: `0.9184024740468913` = **91.8402474%**, in [facts.json:41](/home/mrullldhm/personal/propfirm/research/studies/S004-stage1-data/facts.json:41) and [report.md:68](/home/mrullldhm/personal/propfirm/research/studies/S004-stage1-data/report.md:68).
- Estimated mis-signed volume share: `0.005855139554528759` = **0.5855140%**, in [facts.json:44](/home/mrullldhm/personal/propfirm/research/studies/S004-stage1-data/facts.json:44) and [report.md:71](/home/mrullldhm/personal/propfirm/research/studies/S004-stage1-data/report.md:71).
- They match the independently obtained **91.84% / 0.586%** after rounding.
- `all_ok` is **true** at [facts.json:78](/home/mrullldhm/personal/propfirm/research/studies/S004-stage1-data/facts.json:78); the generated report correspondingly says **PASS** at [report.md:12](/home/mrullldhm/personal/propfirm/research/studies/S004-stage1-data/report.md:12).

## 3. SHA-256 check

Direct `sha256sum -c` verification covered all **25 files** listed at [evidence log:2-26](/home/mrullldhm/personal/propfirm/data/research/stage1/test_evidence_20261017T140154Z.log:2).

- Mismatches: **none**
- Listed files missing: **none**
- Listed files unverifiable: **none**
- Tests were not rerun.

## 4. New problems

- **Minor — STATUS.md is stale despite being the designated source of truth.** It still reports the failed 10-of-11 S004 audit, an unimplemented amendment, and pending R017/R018 review at [STATUS.md:23](/home/mrullldhm/personal/propfirm/research/STATUS.md:23), while the accepted rerun is `all_ok: true`. Its test counts and prereg description are also stale at [STATUS.md:20](/home/mrullldhm/personal/propfirm/research/STATUS.md:20) and [STATUS.md:44](/home/mrullldhm/personal/propfirm/research/STATUS.md:44). This matters because STATUS is explicitly the operational source of truth at [README.md:7](/home/mrullldhm/personal/propfirm/research/README.md:7), and its current instructions could prompt an unnecessary additional S004 rerun. It does not invalidate the data or one-shot guards.
- **Minor — missing-input behavior lacks a focused regression assertion.** Production detects missing raw files at [stage1_convert.py:304](/home/mrullldhm/personal/propfirm/propfirm_data/stage1_convert.py:304), but the test exercises changed and extra files only at [test_stage1_convert.py:135](/home/mrullldhm/personal/propfirm/tests/test_stage1_convert.py:135). The reviewed implementation is correct, but the missing-file branch could regress unnoticed.

**(a) GO for using the stage-1 data in H027 / H028** — all twelve audit gates pass with the independently matching volume-weighted figures, and current provenance and test artifacts are hash-verified.

**(b) GO to freeze both cards and run each once on 2015-16** — the remaining R018 success-path failure mode is recovered by the shared finisher, while S004 rehashing and durable attempt markers protect each single-shot run; update the stale STATUS record before execution.

Codex session ID: 01a14a2f-3048-7881-a614-3c79f997f5f4
Resume in Codex: codex resume 01a14a2f-3048-7881-a614-3c79f997f5f4

### Resolution after follow-up 1
**GO** for using the stage-1 data in H027 / H028. The two Minors were fixed before the runs:
- STATUS.md was brought up to date;
- `test_conversion_refuses_raw_files_that_differ_from_the_purchase_manifest` now also covers a missing raw
  file.

Item 3 (the vendor charge, and per-day quotes before the next purchase) stays tracked in STATUS.
