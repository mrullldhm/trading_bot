---
id: R009
title: Codex independent replication of 5 S002 headline numbers
status: resolved
item: S002
codex_job: task-mvbgcoo2-ftattm (+ follow-up task-mvbgnn5s-tuoc8a)
created: 2026-10-17
updated: 2026-10-17
---

# R009 — Codex replication of S002

## Request (summary)
Replication mode (`WRITE only under research/replications/S002/`), blind to Claude's results. Five
numbers from the raw parquet with Codex's own code (no `propfirm_research` imports): 14:30-15:00 drift;
settlement continuation; EIA activity multiples; NY VR(30) on a filled minute grid; term-structure
counts and the overnight -> NY sign rule by regime. Follow-up: the EIA control ratio with a corrected
control set.

## Codex output (verbatim)
### Main job
Replication completed and rerun with byte-identical output.

| Item | Independent result |
|---|---|
| 1. 14:30→15:00 | Mean **−2.202845 ticks**, t **−5.924673**, n=1,617 |
| Block means | 2010–12 **−2.036624**; 2013–14 **−2.700000**; 2015–16 **−1.923848** ticks |
| 2. Corr(x,y) / sign IC | **0.163180 / 0.118635**, n=1,560 |
| Gross sign edge | **2.622436 ticks**, t **4.684774** |
| Edge by block | **4.404605 / 2.512821 / 0.489669** ticks |
| 3. EIA absolute return | Event mean **12.537627 ticks/min**; baseline **4.080879**; ratio **3.072286** |
| EIA volume | Event mean **3,334.395 lots/min**; baseline **648.981**; ratio **5.137892** |
| Non-EIA Wednesday ratios | **Undefined**: zero eligible control Wednesdays |
| 4. VR(30) | **0.904843**, trading-day bootstrap SE **0.009594** |
| 5. Term counts | Contango **1,315**; backwardation **299**; unsynchronised **71** |
| Contango sign rule | IC **0.060002**; edge **6.484553 ticks**, n=1,230 |
| Backwardation sign rule | IC **−0.019579**; edge **−1.825623 ticks**, n=281 |

Method: standalone raw-parquet calculation, roll-safe contract keys, CME ET trading dates, requested 16:05 flat, scheduled short days, expiry/roll cutoffs, and 2,000 day-bootstrap replications. Only `orb_engine.short_days` and the permitted EIA calendar were reused; no `propfirm_research` imports.

The problematic convention is the non-EIA-Wednesday control: all 343 discovery weeks are either 296 rule weeks or 47 holiday weeks, so the requested control set is empty. Item 5 also leaves zero predictors ambiguous; the headline includes them as `sign(0)=0`, while the JSON includes nonzero-only sensitivity results.

Files:

- [README.md](/home/mrullldhm/personal/propfirm/research/replications/S002/README.md)
- [replicate.py](/home/mrullldhm/personal/propfirm/research/replications/S002/replicate.py)
- [results.json](/home/mrullldhm/personal/propfirm/data/research/replications/S002/results.json)

Codex session ID: 01a14684-94f7-7850-b62c-b19004c515ae
Resume in Codex: codex resume 01a14684-94f7-7850-b62c-b19004c515ae

### Follow-up job
- Absolute 1-minute return ratio: **2.712277**
- Mean control absolute return: **4.622547 ticks/min**
- Volume ratio: **4.630184**
- Mean control volume: **720.143103 lots/min**
- Control trading days: **1,172**

Codex session ID: 01a14684-94f7-7850-b62c-b19004c515ae
Resume in Codex: codex resume 01a14684-94f7-7850-b62c-b19004c515ae

## Claude's response
### Comparison (Claude = final S002 run; X = Codex)
| # | Quantity | Claude | Codex | Match |
|---|---|---|---|---|
| 1 | 14:30-15:00 mean / t / days | -2.2028 / -5.925 / 1,617 | -2.2028 / -5.925 / 1,617 | exact |
| 1 | block means | -2.037 / -2.700 / -1.924 | -2.037 / -2.700 / -1.924 | exact |
| 2 | settlement corr / sign IC | 0.161 / 0.119 (1,578 days) | 0.163 / 0.119 (1,560) | yes |
| 2 | gross sign edge / t | 2.63 / 4.73 | 2.62 / 4.68 | yes |
| 2 | edge by block | 4.43 / 2.59 / 0.41 | 4.40 / 2.51 / 0.49 | yes |
| 3a | EIA abs-return / volume vs own 10:00-10:14 | 3.072 / 5.138 | 3.072 / 5.138 | exact |
| 3b | vs the same minutes on other weekdays of normal weeks | 2.712 / 4.630 (1,168 days) | 2.712 / 4.630 (1,172) | yes |
| 4 | NY VR(30) / bootstrap se | 0.9041 / 0.0095 | 0.9048 / 0.0096 | yes |
| 5 | contango / backwardation / unsynchronised days | 1,315 / 299 / 71 | 1,315 / 299 / 71 | exact |
| 5 | overnight -> NY in contango: IC / edge | 0.060 / 6.44 | 0.060 / 6.48 | yes |
| 5 | in backwardation: IC / edge | -0.010 / -0.97 | -0.020 / -1.83 | yes within noise (both ~0; n ~280, sd ~92 ticks) |

The 18-day difference in item 2 and the 4-day difference in the control set come from small differences
in window validity (late bars, roll cut-offs); they do not move any conclusion.

### Convention points
1. **EIA control set (Codex was right; Claude's bug).** Every normal week has a Wednesday release, so
   "non-EIA Wednesdays" exist only in holiday weeks. Claude's code had silently used the 4 holiday
   Wednesdays (2012-07-04, 2013-12-25, 2014-01-01, 2015-11-11), and the published x5.5 was meaningless.
   Replaced by Mon / Tue / Thu / Fri of normal weeks: x2.7. Both now agree.
2. **x = 0 days in item 5.** Claude drops x = 0 (no direction); Codex keeps them as zero trades. That
   explains part of the backwardation gap; both are kept as reported.

## Resolution
| # | Item | Status |
|---|---|---|
| 1, 2, 3a, 4, 5 | match | VALIDATED |
| 3b | control set bug fixed in `s002_atlas.events`; rerun; match | VALIDATED after fix |
| c2 | x = 0 handling | documented, no change |
