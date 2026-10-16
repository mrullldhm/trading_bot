---
id: R003
title: Codex adversarial review of the propfirm_research toolkit code
status: resolved
item: propfirm_research/ + tests/test_research_*.py
codex_job: task-mvb3xqve-oqa5mc
created: 2026-10-16
updated: 2026-10-16
---

# R003 — Codex review of the toolkit code

## Request (summary)
Read-only adversarial review of every module in `propfirm_research/` and its tests, against the frozen
code it wraps (propsim, orb_engine, bars). Codex could not run pytest (no writable temp dir in its
sandbox); findings are from static reading.

## Codex output (verbatim)

## Critical

1. **Protected-period access is not bound to a preregistered run.**  
   [prereg.py:20](/home/mrullldhm/personal/propfirm/propfirm_research/prereg.py:20), [prereg.py:75](/home/mrullldhm/personal/propfirm/propfirm_research/prereg.py:75), [data.py:41](/home/mrullldhm/personal/propfirm/propfirm_research/data.py:41), [data.py:53](/home/mrullldhm/personal/propfirm/propfirm_research/data.py:53)  
   `_OPEN` is a publicly writable dictionary. Once populated—legitimately or directly—one prereg permits unlimited reads during that process, with arbitrary `item_id`, `purpose`, symbol, and warm-up. Thus H002 can read validation using H001’s prereg, and opening once does not enforce “one run.”  
   **Fix:** return an opaque run capability from an atomic context-managed opener; bind it to prereg SHA, `item_id`, period, allowed symbols/files, and code hash; require that capability in `load`; revoke it when the run closes. Validate ledger `item_id` against the prereg.

2. **Invalid preregistrations can be frozen and used to open protected data.**  
   [prereg.py:17](/home/mrullldhm/personal/propfirm/propfirm_research/prereg.py:17), [prereg.py:32](/home/mrullldhm/personal/propfirm/propfirm_research/prereg.py:32), [prereg.py:41](/home/mrullldhm/personal/propfirm/propfirm_research/prereg.py:41)  
   Registration checks only field presence and period. It accepts validation alpha 0.05, arbitrary stopping rules/nulls, string placeholders, empty code/data hashes, missing fee/slippage fields, and no library versions. The test fixture deliberately registers such placeholders at [test_research_core.py:67](/home/mrullldhm/personal/propfirm/tests/test_research_core.py:67). This defeats the protocol’s validation gate.  
   **Fix:** schema-plus-semantic validation: validation alpha exactly 0.01; enumerated null/test/multiplicity/stopping rule; explicit fee/slippage/sizing/family fields; nonempty hashes; environment package versions; matching directory/item ID; holdout approval.

## Major

3. **Grid does not flatten five minutes before a contract roll.**  
   [grid.py:89](/home/mrullldhm/personal/propfirm/propfirm_research/grid.py:89), [grid.py:96](/home/mrullldhm/personal/propfirm/propfirm_research/grid.py:96)  
   It merely rejects a window when entry and scheduled-exit contracts differ. A position ending one to four minutes before the observed switch remains “valid,” contrary to `bars.py`’s five-minute roll cutoff. Windows spanning a roll are discarded using the future exit contract rather than causally exited at the cutoff, creating selection/look-ahead.  
   **Fix:** construct the frozen engine’s roll schedule and set `day_flat=min(session flat, expiry−5, roll−5)`; exit at the first eligible bar there. Test roll−6, roll−5, roll−1 and spanning-roll cases.

4. **Unknown expiry silently disables expiry protection.**  
   [grid.py:77](/home/mrullldhm/personal/propfirm/propfirm_research/grid.py:77), [grid.py:90](/home/mrullldhm/personal/propfirm/propfirm_research/grid.py:90)  
   `contract_expiry()` returning `-1` permits trading through expiry. Real contract keys should fail closed.  
   **Fix:** reject unknown real `raw_symbol@YYYY-MM` expiries, matching `Front(..., strict_expiry=True)`. Add expiry−6/−5/−1 tests.

5. **Invalid grid windows become zero-return trades.**  
   [grid.py:117](/home/mrullldhm/personal/propfirm/propfirm_research/grid.py:117), [grid.py:120](/home/mrullldhm/personal/propfirm/propfirm_research/grid.py:120)  
   `trade_usd` converts invalid-window NaNs to `0.0`, so callers forgetting `valid` silently add artificial flat observations, biasing means, SEs, and DLL simulations.  
   **Fix:** preserve NaN or raise when a nonzero direction targets an invalid window.

6. **Account contract limits are declared but never enforced.**  
   [combine.py:32](/home/mrullldhm/personal/propfirm/propfirm_research/combine.py:32), [combine.py:118](/home/mrullldhm/personal/propfirm/propfirm_research/combine.py:118), [combine.py:125](/home/mrullldhm/personal/propfirm/propfirm_research/combine.py:125)  
   `odds` accepts fractional, zero, negative, or above-limit contracts despite `cl_limit`.  
   **Fix:** require an integer `1 <= contracts <= acc.cl_limit`; validate reserve, array lengths, finiteness, and nonempty samples. Add rejection tests.

7. **Variance-ratio point estimate omits Lo–MacKinlay finite-sample normalization.**  
   [stats.py:90](/home/mrullldhm/personal/propfirm/propfirm_research/stats.py:90), [stats.py:92](/home/mrullldhm/personal/propfirm/propfirm_research/stats.py:92)  
   The overlapping q-period variance lacks the `(1−q/n)` adjustment, while one-period variance uses divisor `n`; consequently VR—and therefore the robust z—is biased for nontrivial `q/n`. The current test only checks large-sample qualitative behavior.  
   **Fix:** implement the published unbiased denominators and validate against fixed reference vectors; reject `q < 2` or `q >= n`.

8. **Ledger IDs and writes are race-prone, and access is logged after reading.**  
   [ledger.py:50](/home/mrullldhm/personal/propfirm/propfirm_research/ledger.py:50), [ledger.py:64](/home/mrullldhm/personal/propfirm/propfirm_research/ledger.py:64), [data.py:60](/home/mrullldhm/personal/propfirm/propfirm_research/data.py:60), [data.py:78](/home/mrullldhm/personal/propfirm/propfirm_research/data.py:78)  
   Concurrent processes can allocate duplicate run IDs or interleave writes. A crash after parquet access but before line 78 leaves an unlogged look.  
   **Fix:** lock read/ID-allocation/append as one transaction; append an access-intent row before `_read`, then record completion/status separately.

## Minor

9. **Missing boundary coverage.**  
   Tests omit evening starts ≥18:00, DST transition dates, short days, expiry, roll cutoff, sparse/missing flat bars, microsecond-resolution timestamps, repeated protected reads, mismatched prereg/item IDs, and one-cluster/short-series statistical cases. Add focused synthetic tests for each.

The specified test suite could not execute because the read-only environment provides no writable temporary directory; pytest failed before collection. No files were edited. Static comparison found the 50K/no-DLL simulation kernel and RNG call sequence equivalent to `propsim`; costs, trading-day clipping, backward warm-up direction, Wilson bound, BH, and pandas-3-safe `utc_minutes` were otherwise consistent.

Codex session ID: 01a14546-675d-7ed1-a916-21020e602bff
Resume in Codex: codex resume 01a14546-675d-7ed1-a916-21020e602bff

## Claude's response
All findings accepted and fixed. After the fixes: 44 research tests pass; the existing suite passed
(334 tests, run before these fixes; the fixes touch only new files); a real-data smoke test with the
stricter roll and expiry rules ran on discovery data (ledger S000-003/004).

## Resolution
| # | Finding | Severity | Action | Status |
|---|---|---|---|---|
| 1 | Protected access not bound to a run; writable `_OPEN` | critical | `prereg.open_run()` context manager returns a `RunToken` bound to item, period and prereg hash; secret registry; revoked on exit; `data.load` checks item and period match; forged / borrowed / revoked tokens refused (tests) | fixed |
| 2 | Invalid preregs could be frozen | critical | `prereg.validate`: alpha exactly 0.01 for validation, enumerated nulls and multiplicity, ≤ 4 variants (Romano-Wolf if > 1), explicit costs and integer contracts, exact stopping rule, R### review, folder matches item, code and data hashes required, package versions recorded (8 rejection tests) | fixed |
| 3 | No flat 5 min before a roll; roll windows dropped by looking at the future contract | major | `grid.roll_schedule` (next contract's first front minute floored to the hour, as bars.py); flat = min(16:05, expiry−5, roll−5); entries inside the cutoff invalid; tests roll−6/−5/−4/−1/spanning | fixed |
| 4 | Unknown expiry silently disables protection | major | real `SYM@YYYY-MM` contracts without expiry raise; expiry−5 test | fixed |
| 5 | Invalid windows became zero-return trades | major | `trade_usd` raises if a non-zero direction targets an invalid window; zeros only for direction 0 | fixed |
| 6 | Contract limits not enforced | major | `combine.odds` requires integer 1..CL limit; validates reserve, lengths, finiteness, lows ≤ 0 | fixed |
| 7 | Variance ratio lacks Lo-MacKinlay finite-sample denominators | major | unbiased denominators (n−1 and q(n−q+1)(1−q/n)); q in [2, n); hand-computed reference test | fixed |
| 8 | Ledger race; access logged after the read | major | `fcntl` lock around id allocation and append; an "intent" access row before reading, a "done" row after | fixed |
| 9 | Missing boundary tests | minor | added: evening windows (≥ 18:00), short day 12:55, expiry, roll cutoff, repeated / borrowed / forged protected reads, invalid preregs, contracts. Still open: DST-transition-day windows, sparse flat bars, one-cluster stats — add with S002 | partly fixed |
