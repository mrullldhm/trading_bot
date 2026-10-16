---
id: R006
title: Codex blind hypothesis proposals, phase C (before S002 results)
status: resolved
item: BACKLOG (phase C)
codex_job: task-mvbfn6m2-6y4gnm
created: 2026-10-17
updated: 2026-10-17
---

# R006 — Codex blind hypotheses (phase C)

## Request (summary)
Read-only. Propose 6-10 new falsifiable CL intraday hypotheses that could clear the S001 bar (IC ~0.2,
Sharpe >= 2 at 1 CL), not repeating H001-H016, without seeing any S002 output (none existed: the atlas
had not run). Plus measurements the atlas should report so they can be ranked.

## Codex output (verbatim)
I screened these against H001–H016; none is merely a renamed opening-range, generic momentum, settlement unwind, spread-z-score, or roll-pressure test. The hurdle is deliberately severe: after-cost Sharpe ≥2, per-trade IC ≈0.2, stress-cost profitability, and persistence through 2015–2016. That is consistent with the validated [S001 results](/home/mrullldhm/personal/propfirm/research/studies/S001-feasibility/report.md:70) and the programme’s [promotion rules](/home/mrullldhm/personal/propfirm/research/PROTOCOL.md:122).

Common execution convention below: all times ET; the signal uses data only through the preceding minute; enter at the next minute’s open with adverse slippage; fixed exit at the stated minute’s open. Returns must be roll-safe.

## Ranked hypotheses

### 1. C1 — Pre-settlement prompt-pressure continuation

**Hypothesis:** At 14:00, when the 13:30–13:59 change in `CL.v.0 − CL.v.1` has the same sign as the front-month return and the front’s share of combined CL0/CL1 volume exceeds its trailing 60-day same-window 80th percentile, trade `CL.v.0` in the direction of that spread change from 14:01 to 14:30.

- **Mechanism:** Physical hedgers and settlement/TAS benchmark users concentrate prompt-month execution near settlement. Their price-insensitive orders first steepen or flatten the prompt spread, then continue moving the outright front contract. They lose execution cost to traders willing to warehouse the last half-hour. Mandated benchmark timing prevents full arbitrage.
- **Prior: B.** Mou (2011) documents predictable curve pressure from benchmark-constrained commodity flows, but specifically during index rolls—not this daily settlement signal. Storage theory supports information in the prompt spread. See [REFERENCES](/home/mrullldhm/personal/propfirm/research/literature/REFERENCES.md:34).
- **Cheapest discovery test:** One fixed rule, non-roll-splice days only. Compare its net return with matched 14:01 entries having the same direction and nearby volatility. Also test whether the spread/volume condition adds value beyond the sign of the front’s own return.
- **Kill:** Drop if fewer than 300 trades; base-cost Sharpe <2 or IC <0.2; stress mean ≤0; wrong sign in 2015–2016; or the effect exists only in roll weeks, in which case it belongs under H016.
- **Frequency/slippage:** About 20% of sessions, roughly 50/year or 330 over discovery. One tick per side is realistic in the settlement-liquidity window, though stress costs remain mandatory.
- **Data:** `CL.v.0`, `CL.v.1`, settlement time. Available. No official settlement price or TAS data is needed for the first test; both are absent and would be desirable later.

### 2. C2 — Pre-EIA positioning drift

**Hypothesis:** At 10:00 on a scheduled EIA release day, trade in the direction of the 09:30–09:59 `CL.v.0` return from 10:01 to 10:25, exiting before the 10:30 announcement.

- **Mechanism:** Better-informed participants and physical hedgers position gradually before the inventory number; slower hedgers waiting for the deadline pay the drift. Limited risk capacity immediately before a major release may prevent arbitrageurs from leaning against possible information leakage.
- **Prior: B.** Kurov et al. report pre-announcement drift toward subsequent surprises for some macro releases, but the repository has no direct CL/EIA result. See [REFERENCES](/home/mrullldhm/personal/propfirm/research/literature/REFERENCES.md:25).
- **Cheapest discovery test:** One sign trade on every actual EIA date, including holiday shifts. Compare with the identical rule on matched non-EIA weekdays and ensure all positions are flat by 10:25.
- **Kill:** Apply the common S001 thresholds; additionally kill if EIA days do not outperform matched non-EIA days or if the result depends on fewer than 300 releases.
- **Frequency/slippage:** Roughly 50–53/year, about 330–345 discovery trades—just above G1 and therefore power-sensitive. One tick should be plausible at 10:01 and 10:25; do not hold into the release.
- **Data:** `CL.v.0`, EIA calendar. Available. Actual inventory consensus/surprise data is absent, but unnecessary for this first test.

### 3. C3 — Prompt-contract EIA overreaction

**Hypothesis:** At 10:35 on an EIA release day, fade the sign of the 10:30–10:34 change in `CL.v.0 − CL.v.1`; hold `CL.v.0` from 10:36 to 11:30.

- **Mechanism:** Fast headline traders overexpress the inventory shock in the prompt contract, while physical and calendar-spread traders subsequently distinguish a temporary inventory disturbance from a permanent level shock. The front-specific component then mean-reverts.
- **Prior: B.** Li and Geman find that WTI’s EIA response lasts about 25 minutes and then retraces; Halova et al. emphasize announcement noise. Neither directly tests a front-versus-second residual. See [REFERENCES](/home/mrullldhm/personal/propfirm/research/literature/REFERENCES.md:25).
- **Cheapest discovery test:** A single sign rule on every EIA event. Compare it with (a) simply fading the CL0 report return and (b) matched non-EIA Wednesdays. Its value must be incremental to the generic H003 signal.
- **Kill:** Common thresholds, plus drop if the cross-contract residual adds no material expectancy over fading CL0 alone. Also kill if a two-tick entry/exit assumption removes profitability.
- **Frequency/slippage:** About 50/year, 330–345 discovery trades. One tick at 10:36 is possible but optimistic after a large report; this is the strongest case for treating two ticks as the operational base case.
- **Data:** `CL.v.0`, `CL.v.1`, EIA calendar. Available. Trade/order-book data is absent.

### 4. C4 — Front-only NY open sweep reversal

**Hypothesis:** At 09:05, if the signs of the 08:55–09:04 returns of CL0 and CL1 disagree, trade `CL.v.0` in the direction of CL1 from 09:06 to 09:30.

- **Mechanism:** Stops and opening orders can sweep the more actively traded prompt contract without confirmation from the deferred contract. Calendar-spread arbitrageurs and physical participants then pull CL0 back toward the curve’s common move. Front-only momentum traders and triggered stops lose.
- **Prior: C.** Plausible microstructure mechanism, but no supporting paper in the project’s literature list. This is distinct from H015 because it trades one outright leg at a scheduled liquidity transition rather than a two-leg 20-day spread z-score.
- **Cheapest discovery test:** One disagreement rule, compared with matched 09:06 trades and with an unconditional fade of CL0’s opening move.
- **Kill:** Common thresholds; kill if there are fewer than 300 disagreements or if CL1 direction adds no incremental value over generic opening reversal.
- **Frequency/slippage:** Unknown before S002, plausibly 15–35% of sessions or 40–90/year. One tick is realistic after 09:05 given normal NY liquidity.
- **Data:** `CL.v.0`, `CL.v.1`. Available.

### 5. C5 — Asia/London disagreement resolved by European physical flow

**Hypothesis:** At 07:55, when the 20:00–03:00 and 03:00–07:54 CL0 returns have opposite signs, trade in the London-window direction from 07:56 to 08:25.

- **Mechanism:** Thin Asian speculative or inventory flow is corrected when European physical merchants and energy desks enter. US pre-open participants then reinforce the European repricing. The Asia-side inventory holders lose when they liquidate before the US data window.
- **Prior: B/C.** The mechanism is plausible and Boyarchenko et al. provide an indirect equity-futures analogy for overnight inventory resolution, but there is no crude-specific support. See [REFERENCES](/home/mrullldhm/personal/propfirm/research/literature/REFERENCES.md:23).
- **Cheapest discovery test:** One conditional sign rule. Compare with unconditional continuation of the 03:00–07:54 move and matched random 07:56 entries.
- **Kill:** Common thresholds; kill if the disagreement condition does not improve expectancy over unconditional London momentum or if thin-minute incidence makes one-tick fills implausible.
- **Frequency/slippage:** Approximately 40–55% of sessions, perhaps 100–135/year. One tick may be realistic near 08:00 but needs explicit atlas confirmation. Exiting before 08:30 avoids scheduled US releases.
- **Data:** `CL.v.0`; no event calendar required. Available.

### 6. C6 — Next-day correction of a noisy EIA shock

**Hypothesis:** At 10:35 on the first trading day after an EIA release, fade the release-day 10:30–11:00 CL0 return and exit at 11:30.

- **Mechanism:** Inventory estimates are noisy and frequently revised. Speculators and hedgers reacting mechanically to the headline may create a temporary risk transfer that fundamental participants correct after overnight analysis.
- **Prior: C.** Li and Geman support rapid same-day retracement, and Halova et al. support announcement noise, but that evidence arguably predicts that correction will already be finished before the next day. No direct next-day evidence is listed.
- **Cheapest discovery test:** One trade per release, mapped to the next trading day, with holiday shifts handled from the calendar. Compare with the same next-day window following non-EIA Wednesdays.
- **Kill:** Common thresholds; immediately drop if the release-day return has no next-day predictive coefficient or if any reversal is confined to the release day.
- **Frequency/slippage:** About 50/year and borderline 300+ discovery trades. One tick is realistic at 10:35 on an ordinary non-release day.
- **Data:** `CL.v.0`, EIA calendar. Available.

### 7. C7 — Whole-dollar option-gamma pin into settlement

**Hypothesis:** At 14:00, if the 13:59 CL0 price lies 1–10 ticks from the nearest whole-dollar price, trade toward that whole dollar from 14:01 to 14:30.

- **Mechanism:** Dealers long gamma buy below and sell above a concentrated strike while urgent hedgers continue using the settlement window. The hedge flow can pull price toward a strike even when the fundamental expected return is zero.
- **Prior: C.** No supporting options-pin paper is in the project literature. Without strike open interest, “nearest whole dollar” is only a crude proxy for the true gamma concentration.
- **Cheapest discovery test:** The exact distance rule above, with no fitted threshold. Report attraction versus movement away from the strike and compare against prices 11–20 ticks away.
- **Kill:** Common thresholds; also kill if trade count is below 300 or if attraction is no stronger near whole dollars than in the adjacent distance band.
- **Frequency/slippage:** Roughly 20% of uniformly distributed cent prices, about 45–55/year. One tick is realistic at 14:01 and near settlement.
- **Data:** `CL.v.0`, settlement time. Available. CL option strikes, expiries, dealer gamma, and open interest are absent; without them this cannot graduate beyond a coarse proxy.

### 8. C8 — Globex reopening-gap fade

**Hypothesis:** At 18:05, excluding any CL0 raw-symbol change, fade the gap from the 16:05 price to the 18:04 close; exit at 20:00.

- **Mechanism:** Reopening market orders hit a partially replenished book and stale limit orders, causing a temporary overshoot. Liquidity providers earn the reversal as the evening book fills in; impatient reopen traders lose.
- **Prior: C.** No supporting literature in the repository. Prior work also found the 18:00 anchor especially poor, which is adverse evidence.
- **Cheapest discovery test:** One daily sign trade, roll/splice days excluded, compared with matched non-gap-direction entries. Stratify only diagnostically by gap magnitude; do not select a threshold afterward.
- **Kill:** Common thresholds; kill if two-tick stress is non-positive or if S002 shows enough thin minutes/p95 one-minute range that one-tick execution is not credible.
- **Frequency/slippage:** Roughly 240–250/year. One tick is doubtful at 18:06; this probably requires two ticks per side and therefore faces a higher effective bar.
- **Data:** `CL.v.0` and raw-symbol continuity. Available.

## My actual confidence

Only C1–C3 look worth immediate discovery effort. Even those are unlikely to attain IC 0.2: the project notes that published intraday signals are commonly around 0.02–0.05, while S001 requires roughly 0.17–0.30 ([S001](/home/mrullldhm/personal/propfirm/research/studies/S001-feasibility/report.md:87)).

Most likely failures:

- **C8:** poor historical prior at the Globex open and doubtful one-tick fills.
- **C7:** strike proximity without option open interest is an exceptionally noisy proxy.
- **C6:** the literature suggests EIA retracement occurs quickly, probably before the next day.
- **C5:** the physical-flow story may be real but too weak relative to two-sided costs.
- **C4:** because CL0 normally leads CL1, apparent “front-only sweeps” may be information discovery rather than noise.

The weekly EIA hypotheses also sit barely above the 300-trade gate. Missing releases or conditional filtering could make validation underpowered even if discovery expectancy looks good.

## Three S002 measurements I would request

1. **Window-specific feasibility table:** For every proposed entry/exit pair, report eligible days, gross-return standard deviation, MAE/MFE, p95 one-minute entry/exit range, volume, thin-minute share, and the gross ticks required to produce after-cost Sharpe 2. This is more rank-useful than half-hour volatility alone.

2. **CL0/CL1 lead-lag atlas:** At 09:00, EIA 10:30, and settlement 14:00, report contemporaneous correlation, spread-change distribution, front-volume share, and whether CL0-minus-CL1 residuals predict the next 25/30/55 minutes, separately across the three discovery blocks. The current S002 design includes regimes but not this cross-contract event decomposition.

3. **Event-path decomposition:** For EIA and settlement days, report cumulative returns and reversals in 5-minute increments, plus the following trading day’s same-time window. Include base/stress break-even effect sizes and 2015–2016 stability. This would distinguish C2/C3/C6 and show whether any apparent edge has already decayed.

No files were changed, and I did not inspect any S002 output; the design file still reports results as pending.

Codex session ID: 01a14672-6d6b-76f0-8ede-735f2ad13533
Resume in Codex: codex resume 01a14672-6d6b-76f0-8ede-735f2ad13533

## Claude's response
- All eight go into BACKLOG as H017-H024 (C1-C8, Codex's ranking and priors kept). Ranking is redone after
  S002 together with H001-H016.
- I agree with Codex's own honesty note: C1-C3 are the only ones worth early effort; the weekly EIA ideas
  (C2, C3, C6) sit near the 300-trade floor, so validation power is a real constraint (G1).
- C3's "two ticks as the operational base case" after a report is right: EIA-minute ideas must be judged
  on stress costs.
- The three requested atlas measurements are added to S002 **before the headline run** (amendment
  recorded in the S002 report): a per-window feasibility table (no signals, only noise / excursion /
  liquidity and the gross ticks needed for Sharpe 2), a CL0/CL1 lead-lag decomposition at 09:00, 10:30
  and 14:00, and an event path in 5-minute steps with the next day's same window.

## Resolution
| # | Item | Action | Status |
|---|---|---|---|
| C1-C8 | hypotheses | BACKLOG H017-H024 | done |
| m1 | window feasibility table | S002 item 9 | done |
| m2 | CL0/CL1 lead-lag | S002 item 10 | done |
| m3 | event path, 5-minute steps | S002 item 11 | done |
