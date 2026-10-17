---
id: R015
title: Codex blind replication of the H025/H026 discovery run
status: resolved
item: H025, H026
codex_job: task-mvbspsn8-teyo6c
created: 2026-10-17
updated: 2026-10-17
---

# R015 — Codex replication of H025 / H026

## Request (summary)
Replication mode (`WRITE only under research/replications/H025/`), blind: Codex was told not to read
Claude's explore.csv files, `data/research/settlement/` or the H025/H026 ledger rows. From the raw parquet
files and the frozen card definitions (section 4), with its own code, report per variant n, mean gross
ticks, t and block means, plus the day counts. Tolerance: n within 1%, gross within 0.1 tick.

## Codex output (verbatim)
| Variant | n | Mean gross ticks | t | 2010–12 | 2013–14 | 2015–16 |
|---|---:|---:|---:|---:|---:|---:|
| v1 | 378 | 5.852 | 4.297 | 9.547 | 5.917 | 1.567 |
| v2 | 422 | 3.249 | 2.520 | 7.331 | 4.238 | -1.814 |
| v3 | 641 | 3.739 | 3.763 | 6.245 | 4.438 | 0.216 |
| v4 | 1,616 | 2.245 | 6.074 | 2.037 | 2.840 | 1.924 |
| Naive continuation | 1,551 | 2.750 | 4.885 | 4.791 | 2.695 | 0.217 |

Counts:

- Loaded trading days: **1,685**
- Eligible H025 days: **1,617**
- Eligible days missing the exact 16:05 exit: **18**
- Not eligible: 68
  - Short day: 41
  - Missing 14:25: 2
  - Missing 14:34: 25
  - Signal-contract mismatch: 0
  - Missing 14:35–14:40 entry: 0
  - Entry-contract mismatch: 0
  - Entry not before flat: 0

Exact reproduction command:

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python research/replications/H025/replicate.py --json
```

Files written:

- [replicate.py](/home/mrullldhm/personal/propfirm/research/replications/H025/replicate.py)
- [README.md](/home/mrullldhm/personal/propfirm/research/replications/H025/README.md)

Interpretive choices:

- Loaded days are discovery-period CME dates having at least one `CL.v.0` row. New York dates advance at 18:00; IANA timezone conversion handles DST.
- Failure reasons are mutually exclusive in frozen-definition order. This affects only the breakdown, not eligibility.
- Short days were excluded before afternoon entry checks. Keeping them and enforcing entry-before-flat changed H025 eligibility and v4 emissions by **0**.
- Expiration flat time is five minutes before the exchange timestamp when earlier. No eligible day used an early expiry flat.
- I did not infer a future roll deadline from observed data. There were **0** raw-symbol transitions during 14:25–16:05, so that alternative changed evaluated n by **0**. Signal, entry, and exit contract equality was enforced.
- `move = 0` emits no naive trade. Counting evaluable zero moves as zero-direction trades would increase naive n from **1,551 to 1,599**.
- “Missing exit” means no exact 16:05 row. Counting wrong-contract exact rows too changes the count by **0**.
- Block assignment uses the CME trading date. Entry occurs during that date’s daytime session.
- Thresholds use only the immediately preceding 60 eligible days, including subsequently unevaluable days; today is excluded, interpolation is NumPy linear, and comparison is strict `>`.
- The t statistic is `mean(x) / (sample_sd(x, ddof=1) / sqrt(n))` over evaluated daily gross-tick returns.

Codex session ID: 01a147c1-77a9-7380-8096-c3f238ec4704
Resume in Codex: codex resume 01a147c1-77a9-7380-8096-c3f238ec4704

## Claude's response
| Variant | n (Claude / Codex) | Gross ticks | t | 2010-12 | 2013-14 | 2015-16 |
|---|---|---|---|---|---|---|
| v1 move filter | 378 / 378 | 5.8519 / 5.852 | 4.2968 / 4.297 | 9.5474 / 9.547 | 5.9174 / 5.917 | 1.5667 / 1.567 |
| v2 volume filter | 422 / 422 | 3.2488 / 3.249 | 2.5195 / 2.520 | 7.3309 / 7.331 | 4.2378 / 4.238 | -1.8143 / -1.814 |
| v3 union | 641 / 641 | 3.7395 / 3.739 | 3.7628 / 3.763 | 6.2445 / 6.245 | 4.4375 / 4.438 | 0.2157 / 0.216 |
| v4 H026 short | 1,616 / 1,616 | 2.2450 / 2.245 | 6.0737 / 6.074 | 2.0366 / 2.037 | 2.8405 / 2.840 | 1.9238 / 1.924 |
| naive reference | 1,551 / 1,551 | 2.7498 / 2.750 | 4.8849 / 4.885 | 4.7911 / 4.791 | 2.6955 / 2.695 | 0.2167 / 0.217 |

Counts match too: 1,685 trading days, 1,617 eligible, 18 eligible days without the exact 16:05 bar, 68
not eligible. Claude's counts are not mutually exclusive (68 days fail both the signal and the entry
checks); Codex's exclusive breakdown (41 CME short days, 2 missing 14:25 bars, 25 missing 14:34 bars) is
consistent with that. Codex's interpretive choices (no roll inferred from future data, zero moves emit
no trade, thresholds from the previous 60 eligible days including later-unevaluable ones) are the
frozen ones. **VALIDATED**: every number matches to rounding.

## Resolution
| Item | Status |
|---|---|
| v1-v4 and the naive reference: n, gross, t, blocks | VALIDATED (exact) |
| day counts | VALIDATED (consistent breakdown) |
| verdict | H025 and H026 parked (0 of 4 promoted) stands |
