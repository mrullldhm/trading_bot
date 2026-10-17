---
id: R016
title: Codex blind design consult for stage 1 (H027/H028 families, loader rules, download risks)
status: resolved
item: H027, H028, propfirm_data.stage1, propfirm_research.data
codex_job: forwarder background task bxyid0wmf (Codex job id not reported by the forwarder)
created: 2026-10-17
updated: 2026-10-17
---

# R016 — Codex blind design consult for stage 1

## Request (summary)
Read-only, default Codex model, run during the planning of session 4 (2026-10-17), before any D010
data was bought. Blind in this sense: Codex was pointed at STATUS, PROTOCOL, D008, D010, R012, the
BACKLOG rows H025-H028, the H025 card and the harness code, but not at Claude's own H027/H028 designs,
which Claude wrote into its plan file before reading this answer. Five questions: Q1 frozen H027 family
(<= 4 variants, signs fixed by mechanism, fallback without aggressor side), Q2 frozen H028 family,
Q3 how to adapt the PROTOCOL §4.4 promotion screen to a 2015-16-only first look, Q4 firewall rules and
required tests for the new loaders, Q5 download risks and the line-1 sample acceptance checks. Free
metadata facts given to Codex: `CLT.FUT` maps to TAS outrights and TAS calendar spreads; the trades and
statistics field lists. Raw output kept at `data/research/stage1/R016_codex_raw.md`
(sha256 `109904e1...`); the final wrapper line "[exited with code 0]" is not repeated below.

## Codex output (verbatim)
## Q1. Frozen H027 family

**Repo fact.** H027 must add information beyond OHLCV, run first on 2015–16, and stop unless it has the pre-fixed sign, exceeds 4.402 gross ticks, and clears the power screen ([D008:39-42](/home/mrullldhm/personal/propfirm/research/decisions/D008-direction-after-s003.md:39)). H025’s analogous price-based continuation fell to 1.57 ticks in 2015–16, so H027 must not be interpreted as confirmation merely because it selects the same days ([H025:85-97](/home/mrullldhm/personal/propfirm/research/hypotheses/H025-settlement-continuation/card.md:85)).

**Proposal — common definitions.**

- Count only the outright CLT instrument corresponding to that day’s `CL.v.0` raw contract. Exclude every TAS calendar spread: its direction and allocation between legs are ambiguous. Require the definitions mapping to be unique.
- A trade is usable only if its event time is in the stated window and `ts_recv` is strictly before the decision time.
- Signed imbalance is \(I=\sum s_iq_i\), where verified buyer-aggressor trades have \(s=+1\), seller-aggressor trades \(s=-1\). Unknown-side records are not zero; the entire day is missing if usable-side coverage is below 99%.
- TAS premium score is \(P=\sum q_i\delta_i\), where \(\delta_i\) is the verified TAS differential in CL ticks. Positive \(P\) means long. **Unverified assumption:** positive reported differential represents settlement-plus and is causally available on the trade message. If the sample disproves either point, that variant is unavailable.
- Each score trades only when nonzero and `abs(score)` is strictly above its previous-60-eligible-day 75th percentile, using NumPy linear interpolation. Today is excluded. The first 60 eligible days are warm-up with no trade, following H025’s frozen pattern ([H025:34-47](/home/mrullldhm/personal/propfirm/research/hypotheses/H025-settlement-continuation/card.md:34)).
- Eligibility is determined at entry from signal availability, symbol mapping, side-quality, and entry-contract checks—not from later exit availability. Missing exact exit bars create emitted-but-unevaluable signals, as in the existing harness ([settlement.py:105-125](/home/mrullldhm/personal/propfirm/propfirm_research/settlement.py:105)).

| Variant | Frozen signal and sign | Trade |
|---|---|---|
| H027-v1 TAS inventory | Front-out\-right \(I\), CME-day 18:00 through 14:34:59. **Continuation:** long positive imbalance, short negative. Mechanism: benchmark demand leaves dealers/liquidity providers completing residual inventory transfer after settlement. | Exact 14:35 open → exact 16:05 open |
| H027-v2 TAS premium | Front-out\-right \(P\), 14:25:00–14:34:59. **Continuation:** sign of premium pressure. This tests urgency encoded in the TAS differential rather than aggressor count. | Exact 14:35 → 16:05 |
| H027-v3 late outright flow | `CL.v.0` \(I\), 14:25:00–14:34:59. **Continuation:** sign of imbalance, on the residual-inventory mechanism. | Exact 14:35 → 16:05 |
| H027-v4 hedge-push unwind | `CL.v.0` \(I\), 14:20:00–14:29:59. **Reversal:** trade `-sign(I)`. Mechanism: aggressive settlement hedging temporarily pushes the outright; after the price is fixed, that impact unwinds. The one-minute delay prevents using 14:30 trades at the 14:30 open. | Exact 14:31 → exact 15:00 |

No in-window entry before 14:28: it would mix prediction with the settlement-price formation being measured and would require an unrealistically simultaneous fill. The two signs above are fixed by distinct mechanisms, not selected after seeing results. The competing continuation/unwind mechanisms were already identified as needing a pre-look choice ([R012:204-208](/home/mrullldhm/personal/propfirm/research/reviews/R012-codex-blind-phase-e.md:204)).

**Fallback if sample aggressor side fails.**

Freeze the branch using schema/coverage only, never returns:

1. TAS full-session premium \(P\), continuation, 14:35–16:05.
2. TAS 14:25–14:34 premium \(P\), continuation, 14:35–16:05.
3. MBP-1-classified outright imbalance, 14:25–14:34, continuation, 14:35–16:05.
4. MBP-1-classified outright imbalance, 14:20–14:29, reversal, 14:31–15:00.

Classify only trades at/above the contemporaneous ask as buys and at/below the bid as sells; omit inside-spread, crossed, locked, or stale-quote trades. Require at least 99% classifiable volume per day. If TAS prices are not causal differentials, variants 1–2 become unavailable with \(p=1\); do not invent a tick-rule TAS direction or replace them after observing returns. The approved purchase explicitly permits MBP-1 to replace outright trades when side is missing ([D010:18-33](/home/mrullldhm/personal/propfirm/research/decisions/D010-stage1-data-purchase.md:18)).

Report overlap with H025’s move-filter descriptively, but do not pool H025 returns, add an H025-conditioned variant, or revive H025 from the same 14:35–16:05 outcome.

## Q2. Frozen H028 family

**Repo fact.** The proposed mechanism is convergence toward information in related energy contracts, but RB and HO settle in the same window and BZ is thin; therefore an RB/HO result cannot automatically be called an independent information lead ([R012:204-211](/home/mrullldhm/personal/propfirm/research/reviews/R012-codex-blind-phase-e.md:204)).

**Proposal — exact return and scale.**

For each contract \(j\), use

\[
r_{j,d}=\log(C_{j,d,14:34}/O_{j,d,14:25}),\qquad
z_{j,d}=r_{j,d}/\sigma_{j,d},
\]

where \(\sigma_{j,d}\) is the sample standard deviation of that same return over the previous 20 variant-eligible trading days, today excluded. Require 20 observations and positive finite volatility; do not demean, winsorize, fit weights, or use today in scaling.

| Variant | Signal at 14:35 | Fixed sign/mechanism | Expected trades |
|---|---|---|---:|
| H028-v1 products | \(S=(z_{RB}+z_{HO})/2-z_{CL}\) | `sign(S)`: long CL when products outperform scaled CL, short when they underperform. Interpret narrowly as post-settlement convergence from a relative product-settlement imbalance. | ~480 total / 240 per year |
| H028-v2 BZ | \(S=z_{BZ}-z_{CL}\) | `sign(S)`: CL converges toward BZ. | ~400 total / 200 per year |
| H028-v3 consensus | Let \(u_j=z_j-z_{CL}\). Trade only if \(u_{RB},u_{HO},u_{BZ}\) all have the same nonzero sign; use that sign. | Agreement across all related markets reduces the chance that a single RB/HO settlement flow drives the signal. | ~300 total / 150 per year |

All enter at the exact 14:35 `CL.v.0` open and exit at the exact 16:05 open, with one unchanged CL raw contract. No percentile filter: the original cross-energy proposal was daily and approximately 250 trades/year ([R012:70-84](/home/mrullldhm/personal/propfirm/research/reviews/R012-codex-blind-phase-e.md:70)).

**BZ stale/missing policy.** At each cutoff use the last BZ bar ending no more than two minutes before that cutoff; require at least one new BZ bar between the two endpoints. Never carry across a CME trading day. Otherwise BZ is missing, and v2/v3 emit no signal. RB, HO, and CL require exact 14:25 and 14:34 bars; no forward fill. Volatility histories use the identical stale policy.

**Same-window settlements.** v1 remains a legitimate predictive rule but not evidence of earlier physical-information discovery. v2 is the separation test, conditional on verifying BZ’s settlement convention; that convention is currently unverified. v3 requires cross-market agreement. No variant may be re-signed after results.

## Q3. Stage-1 screen

**Proposal.** Do not pretend 2015–16 satisfies the protocol’s three-block persistence condition. Apply this two-stage rule:

1. On 2015–16, run the frozen family once, with BH \(q<0.10\) across every frozen slot; unavailable slots remain with \(p=1\), matching the harness’s fixed-family treatment ([settlement.py:187-202](/home/mrullldhm/personal/propfirm/propfirm_research/settlement.py:187)).
2. To justify buying 2010–14, a variant must have:
   - the pre-fixed strategy sign;
   - positive gross mean separately in 2015 and 2016;
   - at least 25 evaluated trades/year;
   - pooled gross \(>4.402\) ticks;
   - base-cost net mean \(\ge 2MDE\);
   - no single day contributing more than 25% of total gross profit;
   - no timestamp, mapping, or missingness failure.
3. After buying 2010–14, rerun the unchanged family with continuous causal warm-up from 2010. Only then apply the actual requirement: positive in at least two of 2010–12, 2013–14, and 2015–16, including 2015–16 ([PROTOCOL:128-135](/home/mrullldhm/personal/propfirm/research/PROTOCOL.md:128)). The stage-1 look and full discovery run are both ledgered; 2015–16 is not treated as fresh evidence twice.

**Arithmetic.** The harness uses base-cost net, \(2.402\) ticks, for `power_ok`, while separately requiring gross above the 4.402-tick stress cost ([settlement.py:160-182](/home/mrullldhm/personal/propfirm/propfirm_research/settlement.py:160)). Thus:

\[
MDE=3.168\,sd/\sqrt{5T},\quad
gross_{\min}=\max(4.402,\;2.402+2MDE).
\]

Planning values below use the supplied window SDs; the formal run substitutes each variant’s realized SD.

| Variants | Expected evaluated count | Planning SD | MDE | Required gross |
|---|---:|---:|---:|---:|
| H027-v1/v2/v3 | ~110 total / 55 per year | 22.116 | 4.225 | **>10.852 ticks** |
| H027-v4 | ~110 / 55 per year | 14.9; inference from the supplied 14:30–15:00 SD | 2.846 | **>8.095 ticks** |
| H028-v1 | ~480 / 240 per year | 22.116 | 2.023 | **>6.447 ticks** |
| H028-v2 | ~400 / 200 per year; inference because BZ missingness is unknown | 22.116 | 2.216 | **>6.833 ticks** |
| H028-v3 | ~300 / 150 per year; inference | 22.116 | 2.558 | **>7.518 ticks** |

The H027 count follows a top-quartile filter after roughly 60 warm-up days; H028 counts are unfiltered after 20-day warm-up. Below 25/year is inconclusive/kill, not permission to relax the filter. The protocol warns that the IID MDE is only a screen; any survivor still needs design-specific clustered/Romano–Wolf power simulation ([R012:179-185](/home/mrullldhm/personal/propfirm/research/reviews/R012-codex-blind-phase-e.md:179)).

**Probability.** H027: 7%; H028: 4%; **any variant survives stage 1: 10%**. This is deliberately below the earlier 12% prior for the overall new-data direction because the exact base-net \(2MDE\) arithmetic is stricter than the earlier rough 8.4-tick figure ([R012:31-35](/home/mrullldhm/personal/propfirm/research/reviews/R012-codex-blind-phase-e.md:31)).

## Q4. Firewall requirements and review tests

**Proposal — loader semantics.**

- `ts_recv` defines when a trade/statistic became known. Require `ts_recv < decision_timestamp`; also require the trade’s `ts_event` to lie in the signal window. Defensively reject `ts_recv < ts_event` unless documented as a vendor-clock exception.
- Assign trades and related bars to CME trading day using `ts_event`, with the 18:00 ET boundary and DST-aware `America/New_York` conversion. This is the repository’s period rule ([periods.py:1-6](/home/mrullldhm/personal/propfirm/propfirm_research/periods.py:1)).
- For statistics, preserve every revision. `ts_ref` identifies the referenced session; `ts_recv` controls availability. An as-of query returns the latest revision received before its cutoff—never the eventual final row.
- Preliminary/final settlement interpretation from `update_action`/`stat_flags` is **unverified** until schema values are documented. Do not silently equate “last row in file” with the contemporaneously known settlement.
- Open interest published the next morning cannot be joined to the prior session’s 14:35 signal. It first becomes eligible for a trading day whose decision time is after its actual `ts_recv`.
- Period cuts use CME trading day, not UTC year. Warm-up may extend only backward and must be explicitly flagged so it cannot contribute outcomes or fitted thresholds outside the requested period. This follows the existing firewall rule ([PROTOCOL:38-48](/home/mrullldhm/personal/propfirm/research/PROTOCOL.md:38)).
- The current reader logs intent/completion and enforces tokens but does not record/verify runtime input hashes ([data.py:41-83](/home/mrullldhm/personal/propfirm/propfirm_research/data.py:41)). Each new load must ledger: item, loader/schema, symbols/raw instruments, period, event and receive cutoffs, warm-up, purpose, row count, min/max `ts_event`, `ts_recv`, `ts_ref`, trading-day range, prereg hash, raw-file hashes, definitions hash, and canonical returned-frame hash. Log intent before reading and success/failure afterward.
- Hash every raw DBN/source file, converted parquet, definitions file, symbol-map artifact, and transformation code. Confirm the registered hashes again at execution, as already required by R012 ([R012:177-183](/home/mrullldhm/personal/propfirm/research/reviews/R012-codex-blind-phase-e.md:177)).

**Exact required tests.**

- `test_trade_known_at_uses_ts_recv`: event before cutoff but receive at/after cutoff is excluded.
- `test_trade_window_requires_event_and_receive_cutoffs`: late report from an earlier event window cannot leak in.
- `test_equal_cutoff_timestamp_excluded`: `ts_recv == entry_ts` is not known for that entry.
- `test_trade_action_correction_cancel_handling`: duplicate sequence, correction, and cancel fixtures produce exactly the documented final as-of tape.
- `test_unknown_side_is_not_zero_volume`: unknown side makes the day fail its coverage rule.
- `test_tas_front_outright_mapping_unique`: only the CLT outright mapped to that day’s CL front remains; spreads and ambiguous mappings are rejected.
- `test_contract_roll_inside_signal_rejected`: no return or flow crosses a raw-symbol change.
- `test_cme_day_boundary_dst_all_loaders`: 17:59:59 and 18:00:00 ET map to different trading days in winter and summer. Existing bar tests already exercise this convention ([test_research_core.py:29-37](/home/mrullldhm/personal/propfirm/tests/test_research_core.py:29)).
- `test_period_cut_by_trading_day_not_utc_year`: no 2017 trading day enters discovery even if its UTC timestamp/date appears adjacent.
- `test_warmup_only_reaches_backward`: negative warm-up fails; returned warm-up rows precede the period and cannot become outcomes.
- `test_validation_and_holdout_require_matching_live_token`: missing, forged, wrong-item, wrong-period, and closed tokens all fail, matching existing bar-loader behavior ([test_research_core.py:95-111](/home/mrullldhm/personal/propfirm/tests/test_research_core.py:95)).
- `test_statistics_asof_ignores_later_revision`: a final settlement received later cannot replace the preliminary value at an earlier cutoff.
- `test_statistics_ts_ref_assignment`: statistics attach to the referenced CME session, not blindly to `ts_event` or file date.
- `test_open_interest_unavailable_before_receive_time`: next-morning OI is absent from the preceding 14:35 feature set.
- `test_bz_stale_limit_and_no_cross_day_fill`: two-minute carry is allowed; older or prior-day prices are missing.
- `test_related_bar_missingness_is_variant_local`: missing BZ suppresses v2/v3 but not RB/HO v1.
- `test_runtime_hash_mismatch_aborts_before_rows_returned`: any source/definition/code hash mismatch raises before exposing protected-period data.
- `test_access_ledger_intent_done_and_failure`: every attempted read gets an intent plus exactly one terminal status with hashes/counts.
- `test_no_alternate_market_data_reader`: extend the existing static scan so research modules cannot call parquet/DBN readers outside `propfirm_research.data`; the protocol requires one reader path ([PROTOCOL:55-59](/home/mrullldhm/personal/propfirm/research/PROTOCOL.md:55)).

## Q5. Download risks

**Proposal — cap enforcement.**

The approved side-present package is $12.67; at the required 1.10 reservation margin it consumes **$13.937**, leaving only **$1.063** under the $15 cap ([D010:36-42](/home/mrullldhm/personal/propfirm/research/decisions/D010-stage1-data-purchase.md:36)). Therefore:

- Use a single-instance lock.
- Before every billable request, atomically persist exact parameters, quote, 1.10× reservation, deterministic request key, and status `SUBMITTING`.
- The cap includes completed, pending, failed, and uncertain requests, plus the sample and batch jobs.
- Never automatically retry a per-day `timeseries` request. A timeout after submission becomes `UNCERTAIN`; stop the whole run. A retry requires confirming from the vendor portal that it was not billed, or reserving the full request cost again while still remaining below $15.
- Write responses to a partial file, hash/validate them, then atomically rename and mark complete.
- Do not delete or “forget” reservations to create apparent budget room.

These copy the important protections in the existing batch downloader: it records spend before submission, never retries the billable submission, and stops on an unknown job ID ([download.py:122-145](/home/mrullldhm/personal/propfirm/propfirm_data/download.py:122)); the existing budget guard counts previously reserved failed work ([budget.py:18-36](/home/mrullldhm/personal/propfirm/propfirm_data/budget.py:18)). Per-day downloads need the same discipline because, per the prompt fact, retrying is billed again.

**Line-1 acceptance report before further purchase.**

- Side coverage separately for CLT outright, CLT spreads, and `CL.v.0`: at least **99% of trade volume and 99% of trade records** have a documented aggressor value; both buyer and seller codes occur. Anything below that selects the MBP fallback.
- Confirm from the schema—not intuition—that the side is aggressor side. This remains unverified until documented.
- List each CLT raw symbol, classify outright versus spread from definitions, and prove the front-out\-right mapping is unique.
- Show whether CLT `price` is a small TAS differential or a full futures price; report raw units, tick conversion, permitted values, and sign convention. Do not compute a premium signal until this is settled.
- Verify UTC/ET conversion, request half-open endpoints, `ts_event`/`ts_recv` timezone and precision, sequence uniqueness/order, `action` handling, and the share of records received after their intended signal cutoff.
- Produce schema/coverage counts only—no H027 aggregate, price-response plot, or post-entry return. The sample branch may depend only on side availability and price encoding.

**Ways to waste money or leak look-ahead.**

- Retrying a timed-out daily request; submitting the same date under a differently serialized parameter set; concurrent downloaders; or failing to reserve a request before calling.
- Supplying ET strings as UTC, using an inclusive 14:35 endpoint, or accidentally requesting full sessions. Full-session CL trades were explicitly rejected at $117.80 ([D010:30-34](/home/mrullldhm/personal/propfirm/research/decisions/D010-stage1-data-purchase.md:30)).
- Buying line 5 before the sample has selected the side-present branch, or buying both lines 5 and 6.
- Reconstructing a TAS differential with the eventual official settlement, selecting the “final” statistics revision, or using next-morning OI for the preceding settlement decision.
- Mapping the front contract using future volume/OI or a later revised symbol map.
- Changing variants after seeing the sample-day directional flow or CL response. The conditional family above must be frozen before inspecting those outcomes.

## Ranked blocking issues

1. **Aggressor-side meaning/coverage and TAS price encoding are unverified.** Fix: line-1 schema-only report must pass the explicit coverage/unit checks and select the already-frozen branch.
2. **No retry-safe per-day reservation ledger yet protects the $15 cap.** Fix: persist `SUBMITTING/UNCERTAIN` reservations before every billable call and prohibit automatic retries.
3. **External-data firewall loaders and runtime hash verification do not yet exist.** Fix: implement and pass every Q4 test before any H027/H028 analysis.
4. **Statistics revision flags and BZ settlement convention remain unverified.** Fix: document their exact semantics; statistics stay out of causal features and BZ results retain the contamination caveat until verified.


## Claude's response
Claude's own draft (written before reading this answer) had the same common rules and three of the same
H027 ideas: TAS imbalance continuation to 16:05, outright signed flow continuation to 16:05, and an
unwind on 14:31-15:00. It also had an in-window "push" entry at 14:27 and a cross-energy family close to
Q2.

**Q1 H027: agree, with one change.**
- Agree with every common definition:
  - the front outright TAS only;
  - ts_recv strictly before the decision time;
  - a day is missing below 99% side coverage;
  - the H025 percentile filter and warm-up;
  - entry-time eligibility.
- Agree to drop the in-window entry: fills in 14:27-14:30 would be optimistic, and the trade would
  overlap the settlement price formation it measures.
- Change: slot v2 becomes **TAS unwind**, replacing the TAS premium. The signal is the same front-TAS
  imbalance as v1, known before 14:31, traded `-sign` from 14:31 to 15:00. Two reasons:
  - the TAS price encoding is still unverified, so the premium slot could end up as an untestable p = 1
    slot;
  - the unwind is the conditional form of the programme's most stable settlement fact (K4.5: 14:30-15:00
    is negative in every year), tested with the new TAS information.
- The family becomes a 2x2 of source (TAS, outright flow) by mechanism (residual inventory
  continuation, temporary-impact unwind).
- The premium stays in the fallback branch. Codex can reject this change in the blocking card review
  (R018).
- Agree not to pool or revive H025. Overlap with the H025 move filter is reported descriptively only.

**Q2 H028: agree, adopted as proposed.** Three variants, log returns 14:25 open to 14:34 close, a 20-day
volatility scale, the BZ staleness rule and the caveat that the products settle in the same window.

**Q3 Stage-1 screen: agree.** Adopted verbatim in both cards: frozen sign, BH q < 0.10 with untestable
slots at p = 1, positive gross in 2015 and in 2016, >= 25 trades a year, gross > 4.402 ticks,
base net >= 2 x MDE, no day above 25% of the gross profit, no data-integrity failure. A survivor only
justifies the 2010-14 purchase (new owner decision); then the unchanged family reruns under the
three-block rule.

**Q4 Loaders: agree with every rule and test.**
- The runtime hash check (R012 Q4.4) is implemented now for every loader, including the existing bar
  loader.
- `prereg.register` stores per-file hashes. No pre-registration exists yet, so nothing frozen changes.
- Statistics keep every revision; as-of queries are by ts_recv.

**Q5 Download: agree.**
- Every billed call is reserved first (status SUBMITTING) and is never retried automatically: a failure
  becomes UNCERTAIN and stops the run.
- A resume reserves again under the cap.
- The CL slice line is reserved as a whole before its first call.
- Line-1 rule: >= 99% of CL.v.0 volume and records with a side buys line 5, otherwise line 6. A value
  between 90% and 99% stops for the owner.

## Resolution
| # | Item | Action | Status |
|---|---|---|---|
| Q1 | H027 family | adopted as a 2x2 with v2 = TAS unwind (change above); final text in the H027 card, Codex R018 blocking | adopted; frozen with the card (R018 GO) |
| Q1 | no-side fallback | adopted (TAS premium if its encoding is verified, else p = 1; MBP-1 quote rule for outright flow) | adopted |
| Q2 | H028 family | adopted verbatim (3 variants) | adopted; frozen with the card (R018 GO) |
| Q3 | stage-1 screen | adopted verbatim in both cards and in the harness | adopted |
| Q4 | loader rules and tests | implemented in `propfirm_research.data` and the stage-1 loader tests; reviewed in R017 | resolved (R017 GO) |
| Q5 | download discipline, sample rule | implemented in `propfirm_data/stage1.py`; reviewed in R017 | resolved (R017 GO) |
| B1 | side meaning / TAS encoding unverified | line-1 sample gate (phase 2) | resolved (sample: D010 addendum) |
| B2 | retry-safe reservations | SUBMITTING / UNCERTAIN manifest, no automatic billed retry | resolved (R017 GO) |
| B3 | loaders + runtime hash check | built and tested before any H027/H028 analysis | resolved (R017 GO) |
| B4 | statistics flags, BZ settlement convention | statistics used only in S004 checks; BZ caveat in the H028 card | adopted |
