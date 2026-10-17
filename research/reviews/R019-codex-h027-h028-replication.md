---
id: R019
title: Codex blind replication of the H027 / H028 stage-1 runs
status: resolved
item: H027, H028
codex_job: task-mvch9yc4-nzagyc
created: 2026-10-17
updated: 2026-10-17
---

# R019 — Blind replication of H027 and H028 (stage 1, 2015-16)

## Request (summary)
Codex replicated every variant of both frozen families with its own code, written from section 4 of the cards.
- **Mode.** Write access only under `research/replications/H027/` and `H028/`, using the default Codex model.
- **Inputs.** The processed parquet only. Codex did not import `propfirm_research.settlement`.
- **Blindness.** Codex did not open the run outputs before writing its own numbers. The pre-unblinding hashes
  are in `pre_unblind_sha256.txt` in each folder.

Tolerance: counts within 1%, gross within 0.1 tick.

## Codex output (verbatim)
## 1. Own numbers

### H027

| Variant | Eligible days | Signals | Trades | Gross | SD | One-sided t | 2015 gross | 2016 gross | Net base | Net stress | Trades/year | MDE net | Largest-day share | Pass |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|
| v1 TAS residual | 480 | 107 | 107 | -1.925234 | 18.761513 | -1.061469 | -2.914894 | -1.150000 | -4.327234 | -6.327234 | 53.610082 | 3.630319 | -0.330097 | No |
| v2 TAS unwind | 480 | 107 | 107 | -1.785047 | 13.882273 | -1.330090 | -3.617021 | -0.350000 | -4.187047 | -6.187047 | 53.610082 | 2.686195 | -0.162304 | No |
| v3 outright residual | 499 | 110 | 110 | 0.472727 | 17.567019 | 0.282234 | -0.854167 | 1.500000 | -1.929273 | -3.929273 | 55.113169 | 3.352514 | 0.846154 | No |
| v4 outright unwind | 499 | 103 | 103 | -3.592233 | 10.481952 | -3.478091 | -3.025000 | -3.952381 | -5.994233 | -7.994233 | 51.605967 | 2.067247 | -0.059459 | No |

### H028

| Variant | Eligible days | Signals | Trades | Gross | SD | One-sided t | 2015 gross | 2016 gross | Net base | Net stress | Trades/year | MDE net | Largest-day share | Pass |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|
| v1 products | 478 | 478 | 475 | -0.267368 | 18.797222 | -0.310001 | -1.495575 | 0.847390 | -2.669368 | -4.669368 | 237.988683 | 1.726298 | -0.858268 | No |
| v2 Brent | 466 | 465 | 462 | -0.041126 | 18.914938 | -0.046733 | -0.873874 | 0.729167 | -2.443126 | -4.443126 | 231.475309 | 1.761379 | -5.736842 | No |
| v3 agreement | 465 | 250 | 249 | -0.654618 | 21.016919 | -0.491495 | -2.568182 | 1.504274 | -3.056618 | -5.056618 | 124.756173 | 2.665865 | -0.668712 | No |

## 2. Comparison

Differences are own minus Claude. `NR` means Claude’s `explore.csv` did not report the requested field, so tolerance cannot be assessed.

### H027 v1 TAS residual

| Item | Own | Claude | Difference | Within tolerance |
|---|---:|---:|---:|---|
| Eligible days | 480 | NR | — | N/A |
| Signals | 107 | 107 | 0 | Yes |
| Trades | 107 | 107 | 0 | Yes |
| Gross | -1.925234 | -1.925200 | -0.000034 | Yes |
| SD | 18.761513 | 18.762000 | -0.000487 | Yes |
| t | -1.061469 | -1.061500 | 0.000031 | Yes |
| 2015 gross | -2.914894 | -2.914900 | 0.000006 | Yes |
| 2016 gross | -1.150000 | -1.150000 | 0 | Yes |
| Net base | -4.327234 | -4.327200 | -0.000034 | Yes |
| Net stress | -6.327234 | -6.327200 | -0.000034 | Yes |
| Trades/year | 53.610082 | 53.610000 | 0.000082 | Yes |
| MDE net | 3.630319 | 3.630300 | 0.000019 | Yes |
| Largest-day share | -0.330097 | NR | — | N/A |
| Screen pass | No | No | Same | Yes |

### H027 v2 TAS unwind

| Item | Own | Claude | Difference | Within tolerance |
|---|---:|---:|---:|---|
| Eligible days | 480 | NR | — | N/A |
| Signals | 107 | 107 | 0 | Yes |
| Trades | 107 | 107 | 0 | Yes |
| Gross | -1.785047 | -1.785000 | -0.000047 | Yes |
| SD | 13.882273 | 13.882000 | 0.000273 | Yes |
| t | -1.330090 | -1.330100 | 0.000010 | Yes |
| 2015 gross | -3.617021 | -3.617000 | -0.000021 | Yes |
| 2016 gross | -0.350000 | -0.350000 | 0 | Yes |
| Net base | -4.187047 | -4.187000 | -0.000047 | Yes |
| Net stress | -6.187047 | -6.187000 | -0.000047 | Yes |
| Trades/year | 53.610082 | 53.610000 | 0.000082 | Yes |
| MDE net | 2.686195 | 2.686200 | -0.000005 | Yes |
| Largest-day share | -0.162304 | NR | — | N/A |
| Screen pass | No | No | Same | Yes |

### H027 v3 outright residual

| Item | Own | Claude | Difference | Within tolerance |
|---|---:|---:|---:|---|
| Eligible days | 499 | NR | — | N/A |
| Signals | 110 | 110 | 0 | Yes |
| Trades | 110 | 110 | 0 | Yes |
| Gross | 0.472727 | 0.472730 | -0.000003 | Yes |
| SD | 17.567019 | 17.567000 | 0.000019 | Yes |
| t | 0.282234 | 0.282230 | 0.000004 | Yes |
| 2015 gross | -0.854167 | -0.854170 | 0.000003 | Yes |
| 2016 gross | 1.500000 | 1.500000 | 0 | Yes |
| Net base | -1.929273 | -1.929300 | 0.000027 | Yes |
| Net stress | -3.929273 | -3.929300 | 0.000027 | Yes |
| Trades/year | 55.113169 | 55.113000 | 0.000169 | Yes |
| MDE net | 3.352514 | 3.352500 | 0.000014 | Yes |
| Largest-day share | 0.846154 | 0.846150 | 0.000004 | Yes |
| Screen pass | No | No | Same | Yes |

### H027 v4 outright unwind

| Item | Own | Claude | Difference | Within tolerance |
|---|---:|---:|---:|---|
| Eligible days | 499 | NR | — | N/A |
| Signals | 103 | 103 | 0 | Yes |
| Trades | 103 | 103 | 0 | Yes |
| Gross | -3.592233 | -3.592200 | -0.000033 | Yes |
| SD | 10.481952 | 10.482000 | -0.000048 | Yes |
| t | -3.478091 | -3.478100 | 0.000009 | Yes |
| 2015 gross | -3.025000 | -3.025000 | 0 | Yes |
| 2016 gross | -3.952381 | -3.952400 | 0.000019 | Yes |
| Net base | -5.994233 | -5.994200 | -0.000033 | Yes |
| Net stress | -7.994233 | -7.994200 | -0.000033 | Yes |
| Trades/year | 51.605967 | 51.606000 | -0.000033 | Yes |
| MDE net | 2.067247 | 2.067200 | 0.000047 | Yes |
| Largest-day share | -0.059459 | NR | — | N/A |
| Screen pass | No | No | Same | Yes |

### H028 v1 products

| Item | Own | Claude | Difference | Within tolerance |
|---|---:|---:|---:|---|
| Eligible days | 478 | NR | — | N/A |
| Signals | 478 | 478 | 0 | Yes |
| Trades | 475 | 475 | 0 | Yes |
| Gross | -0.267368 | -0.267370 | 0.000002 | Yes |
| SD | 18.797222 | 18.797000 | 0.000222 | Yes |
| t | -0.310001 | -0.310000 | -0.000001 | Yes |
| 2015 gross | -1.495575 | -1.495600 | 0.000025 | Yes |
| 2016 gross | 0.847390 | 0.847390 | 0 | Yes |
| Net base | -2.669368 | -2.669400 | 0.000032 | Yes |
| Net stress | -4.669368 | -4.669400 | 0.000032 | Yes |
| Trades/year | 237.988683 | 237.990000 | -0.001317 | Yes |
| MDE net | 1.726298 | 1.726300 | -0.000002 | Yes |
| Largest-day share | -0.858268 | NR | — | N/A |
| Screen pass | No | No | Same | Yes |

### H028 v2 Brent

| Item | Own | Claude | Difference | Within tolerance |
|---|---:|---:|---:|---|
| Eligible days | 466 | NR | — | N/A |
| Signals | 465 | 465 | 0 | Yes |
| Trades | 462 | 462 | 0 | Yes |
| Gross | -0.041126 | -0.041126 | 0 | Yes |
| SD | 18.914938 | 18.915000 | -0.000062 | Yes |
| t | -0.046733 | -0.046733 | 0 | Yes |
| 2015 gross | -0.873874 | -0.873870 | -0.000004 | Yes |
| 2016 gross | 0.729167 | 0.729170 | -0.000003 | Yes |
| Net base | -2.443126 | -2.443100 | -0.000026 | Yes |
| Net stress | -4.443126 | -4.443100 | -0.000026 | Yes |
| Trades/year | 231.475309 | 231.480000 | -0.004691 | Yes |
| MDE net | 1.761379 | 1.761400 | -0.000021 | Yes |
| Largest-day share | -5.736842 | NR | — | N/A |
| Screen pass | No | No | Same | Yes |

### H028 v3 agreement

| Item | Own | Claude | Difference | Within tolerance |
|---|---:|---:|---:|---|
| Eligible days | 465 | NR | — | N/A |
| Signals | 250 | 250 | 0 | Yes |
| Trades | 249 | 249 | 0 | Yes |
| Gross | -0.654618 | -0.654620 | 0.000002 | Yes |
| SD | 21.016919 | 21.017000 | -0.000081 | Yes |
| t | -0.491495 | -0.491490 | -0.000005 | Yes |
| 2015 gross | -2.568182 | -2.568200 | 0.000018 | Yes |
| 2016 gross | 1.504274 | 1.504300 | -0.000026 | Yes |
| Net base | -3.056618 | -3.056600 | -0.000018 | Yes |
| Net stress | -5.056618 | -5.056600 | -0.000018 | Yes |
| Trades/year | 124.756173 | 124.760000 | -0.003827 | Yes |
| MDE net | 2.665865 | 2.665800 | 0.000065 | Yes |
| Largest-day share | -0.668712 | NR | — | N/A |
| Screen pass | No | No | Same | Yes |

## 3. Verdicts

- H027 v1: **MATCH**
- H027 v2: **MATCH**
- H027 v3: **MATCH**
- H027 v4: **MATCH**
- H028 v1: **MATCH**
- H028 v2: **MATCH**
- H028 v3: **MATCH**

**Overall verdict: MATCH.** Every field available in Claude’s `explore.csv` agrees within tolerance; all seven variants fail the stage-1 screen.

## 4. Files and assumptions

Material files written:

- [H027 README](/home/mrullldhm/personal/propfirm/research/replications/H027/README.md)
- [H027 implementation](/home/mrullldhm/personal/propfirm/research/replications/H027/replicate.py)
- [H027 own results](/home/mrullldhm/personal/propfirm/research/replications/H027/own_results.csv)
- [H027 metadata](/home/mrullldhm/personal/propfirm/research/replications/H027/run_metadata.json)
- [H027 comparison](/home/mrullldhm/personal/propfirm/research/replications/H027/comparison.csv)
- [H027 verdict](/home/mrullldhm/personal/propfirm/research/replications/H027/verdict.csv)
- [H027 pre-unblind hashes](/home/mrullldhm/personal/propfirm/research/replications/H027/pre_unblind_sha256.txt)
- [H028 README](/home/mrullldhm/personal/propfirm/research/replications/H028/README.md)
- [H028 implementation](/home/mrullldhm/personal/propfirm/research/replications/H028/replicate.py)
- [H028 own results](/home/mrullldhm/personal/propfirm/research/replications/H028/own_results.csv)
- [H028 metadata](/home/mrullldhm/personal/propfirm/research/replications/H028/run_metadata.json)
- [H028 comparison](/home/mrullldhm/personal/propfirm/research/replications/H028/comparison.csv)
- [H028 verdict](/home/mrullldhm/personal/propfirm/research/replications/H028/verdict.csv)
- [H028 pre-unblind hashes](/home/mrullldhm/personal/propfirm/research/replications/H028/pre_unblind_sha256.txt)

Assumptions and ambiguities:

- Processed side convention: `B = buyer aggressor (+1)`, `A = seller aggressor (-1)`.
- The TAS session includes the prior evening from 18:00 ET through, but not including, 14:30 ET.
- H028 v3 eligible days count days with all inputs available before applying the agreement condition; agreement determines emitted signals.
- Largest-day share was interpreted literally as `max(daily gross P&L) / total gross P&L`. This produces negative ratios when total P&L is negative. Claude leaves that field blank in those cases; only H027 v3 has a directly comparable positive-total value.
- Claude’s `explore.csv` files do not report entry-time eligible-day counts, so those comparisons are not assessable from the permitted Claude source.
- Both README commands were rerun from clean shells. The own code, results, and metadata retained their recorded pre-unblind SHA-256 hashes.

Codex session ID: 01a14a36-e99d-7b33-b23f-6d8369b7bbf8
Resume in Codex: codex resume 01a14a36-e99d-7b33-b23f-6d8369b7bbf8

## Claude's response
**Agree: MATCH on all seven variants.** Codex's eligible-day counts (480 / 480 / 499 / 499 for H027; 478 and
466 for H028 v1, v2) equal the run's counts. Its H028 v3 "eligible" counts days with every input before the
agreement condition (465), while the run counts days after it (250 signals). Both agree on the 250 emitted
signals and 249 trades.

The "largest-day share" differs only where the total gross is negative. Codex reports the literal ratio there;
the harness leaves it blank, since such a variant fails anyway. The verdict is unchanged: stage 1 found
nothing, and no 2010-14 purchase is justified (D008 kill rule).

## Resolution
| # | Item | Status |
|---|---|---|
| 1 | H027 v1-v4 numbers | MATCH |
| 2 | H028 v1-v3 numbers | MATCH |
| 3 | stage-1 verdict (0 of 7) | confirmed |
