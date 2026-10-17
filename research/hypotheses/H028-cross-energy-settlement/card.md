---
id: H028
title: Cross-energy settlement divergence predicts CL after settlement
status: rejected
prior: C+
source: Codex R012 E2 and R016 Q2
created: 2026-10-17
updated: 2026-10-17
---

# H028 — Cross-energy settlement divergence

## 1. Claim
On 2015-16 discovery days, CL moves from 14:35 to 16:05 toward the related energy markets, by more than the
stress cost (4.402 ticks). The related markets are RBOB gasoline (RB), heating oil (HO) and NYMEX Brent (BZ);
"toward" means toward how they moved relative to CL over 14:25-14:34 ET, volatility-scaled.

## 2. Mechanism
- **Catch-up.** Physical and refining information can reach the product and Brent markets at different
  speeds. CL's own settlement flow can hide the common factor in CL's price for a while. Passive CL-only
  participants lose to the convergence that follows.
- **Relative pressure.** CL-specific settlement pressure (H027) that the products do not share should also
  revert relative to them.
- **Sign.** Both stories give the same sign: CL moves toward the related markets.
- **Caveat (R016).** RB and HO settle in the same 14:28-14:30 window, and BZ's settlement convention is
  unverified. An RB/HO result is not proof of an earlier information lead, only of post-settlement
  convergence from relative settlement imbalance. v2 (BZ only) is the separation test. v3 needs every
  market to agree.

## 3. Literature and prior evidence
- Codex R012 E2 and R016 Q2.
- No CL bar evidence exists: S002 and S003 had only CL0 and CL1, and the CL0-CL1 spread predicted nothing
  (K4.7).
- Prior **C+**. Codex R016 gives 4% that any H028 variant survives stage 1.

## 4. Exact definition (causal), frozen before the run
**Data.** CL.v.0, RB.v.0, HO.v.0 and BZ.v.0 1-minute bars (D010 lines 7-8), trading days 2015-01-02 ..
2016-12-30 only. Everything goes through `propfirm_research.data`. Contract = the bar's instrument id.

**Returns, per market j and day.** r_j = log(C_14:34 / O_14:25).
- C_14:34 is the close of the 14:34 bar; O_14:25 is the open of the 14:25 bar.
- CL, RB and HO need both exact bars, in one contract, with no forward fill.
- BZ (thin) uses a staleness rule instead:
  - the start price is the open of the 14:25 bar, or else the close of the last bar starting
    14:22-14:24;
  - the end price is the close of the last bar starting 14:32-14:34;
  - both must be in one contract on the same trading day, with nothing carried across days;
  - otherwise BZ is missing that day.
- For CL, the contract must also be the 14:35 entry contract.

**Volatility scale.** sigma_j is the sample standard deviation (ddof 1) of r_j over the previous 20
trading days on which r_j exists, today excluded.
- It needs 20 such days and a finite sigma_j > 0.
- z_j = r_j / sigma_j.
- No demeaning, no winsorising, no fitted weights.

**Variants (the family, 3 slots).** Every eligible day, no percentile filter:

| v | Score S | Direction | Trade |
|---|---|---|---|
| v1 products | (z_RB + z_HO) / 2 - z_CL | sign(S) | 14:35 -> 16:05 |
| v2 Brent | z_BZ - z_CL | sign(S) | 14:35 -> 16:05 |
| v3 agreement | u_j = z_j - z_CL for RB, HO, BZ; trade only if all three have the same non-zero sign | that sign | 14:35 -> 16:05 |

- S = 0 means no trade.
- Missing BZ removes v2 and v3 on that day, never v1.

**Eligible day (entry time).** The variant's inputs exist, and the 14:35 window is `entry_ok`.
Emitted and evaluated trades follow H025 (D009).

**Fills and costs.** As H027: the open of the 14:35 entry bar, at most 5 minutes late; the exact flat-time
exit bar; base cost $24.02, stress $44.02; one CL.

**Statistics and stage-1 screen.** As H027, except that BH runs over 3 slots:
- q < 0.10;
- gross > 0 in 2015 and in 2016;
- >= 25 trades a year;
- gross > 4.402 ticks;
- net (base) >= 2 x MDE_net;
- the largest single day <= 25% of the total gross;
- no data-integrity failure.

A survivor justifies buying 2010-14 (a new owner decision).

**Ledger.** One exploratory row H028 with n_tests 3. One attempt only: as in H027, an atomic
`stage1_attempt.json` is claimed before any data is read and is never removed (R018 B1).

**Frozen 2026-10-17, before any run**, after Codex R017 GO (data) and R018 follow-up 6 GO (card and harness). Harness `propfirm_research/settlement.py` sha256 `bd2c121744e77c7cb7e781bf9aea162c4ad881b0a16dfc86a40ccf13912f87b7`; package code hash `f4437977a74847aeaa6d3238274dde8fda7d47bb181127d5ba076d564cbb994d`; S004 acceptance `research/studies/S004-stage1-data/facts.json` sha256 `00d0ba379935bbbc58d74fb0ffb11d297d7f08993cd4c0bc4c53b3533e09afdd` (all 12 rules). Nothing above this line changes after the run.

## 5. Discovery exploration
**One run, 2026-10-17, on 2015-16 (stage 1).**
- Command: `.venv/bin/python -m propfirm_research.settlement h028`.
- Ledger: H028-001..009 (n_tests 3).
- Outputs: `data/research/settlement/20261017T141122Z_h028/` and [explore.csv](explore.csv). Run time 23 s.

**Counts.** 516 trading days and 499 valid 14:35 entries.
- Returns exist for CL on 499 days, RB 501, HO 500, BZ 488.
- No CL contract mismatch.

| Variant | Trades (per year) | Gross ticks | sd | t | Gross 2015 / 2016 | Net base | MDE net | Stage-1 screen |
|---|---|---|---|---|---|---|---|---|
| v1 products | 475 (238) | **-0.27** | 18.8 | -0.31 | -1.50 / +0.85 | -2.67 | 1.73 | fail |
| v2 Brent | 462 (231) | **-0.04** | 18.9 | -0.05 | -0.87 / +0.73 | -2.44 | 1.76 | fail |
| v3 agreement | 249 (125) | **-0.65** | 21.0 | -0.49 | -2.57 / +1.50 | -3.06 | 2.67 | fail |

BH q is 0.69 for every slot. **0 of 3 pass.** Overlap with the H025 v1 emitted days is 24-25% (descriptive).

## 6. Pre-registration
None.

## 7. Validation result
-

## 8. Codex replication
[R019](../../reviews/R019-codex-h027-h028-replication.md): a blind replication. **MATCH** on all three variants.

## 9. Verdict and next step
**REJECTED at stage 1.** Over 14:25-14:34, the relative moves of RB, HO and NYMEX Brent against CL carry no
information for CL from 14:35 to 16:05: about 0 gross ticks over 250-475 trades. No 2010-14 purchase is
justified.

## 10. Change log
- 2026-10-17: the one stage-1 run: 0 of 3 pass; Codex R019 MATCH; rejected.
- 2026-10-17: frozen (section 4) after Codex R017 GO and R018 follow-up 6 GO.
- 2026-10-17: Codex R018 (NO-GO, then fixed before any run): one-attempt marker; tests for every variant's
  sign and for missing RB / HO / BZ.
- 2026-10-17: created; the family is Codex R016 Q2, adopted verbatim. The 20-day scale counts the days on
  which that market's return exists.
