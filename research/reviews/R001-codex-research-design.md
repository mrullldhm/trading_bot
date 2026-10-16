---
id: R001
title: Codex independent research-programme proposal (planning stage)
status: resolved
item: programme design (D000 charter)
codex_job: task-mvap3qd5-ag1i2c
created: 2026-10-16
updated: 2026-10-16
---

# R001 — Codex independent research-programme proposal

## Request (summary)
Read-only consult during planning (2026-10-16). Codex read README.md (strategy results, audit),
TRADING_BOT_GUIDE §3/§10/§11 and `data/backtests/audit/report.md`, and was asked to propose,
independently of Claude's draft, a research programme to find a CL intraday strategy from this data
that passes the gates: feasibility check of Claude's Gaussian Monte Carlo, method against selection
luck, top-10 hypotheses, a predictability-ceiling design, kill criteria, and the Claude/Codex split.
At that point the owner had not yet excluded micro contracts (D004 came later), so Codex discusses MCL.

## Codex output (verbatim)

**Bottom line:** The programme should begin with a preregistered predictability-ceiling study, not another parameter grid. One MCL may fit the risk budget, but the preliminary conclusion “1–3 MCL with Sharpe ≥3” is too optimistic: sizing does not improve Sharpe, and two MCL appears to require roughly Sharpe 6 under your simulation.

The existing evidence is unusually strong for a negative result: 1.4M configurations, failed walk-forwards, failed signal randomization, and a successful planted-edge control ([README, “Strategy results”](/home/mrullldhm/personal/propfirm/README.md:318); [audit, “Positive control”](/home/mrullldhm/personal/propfirm/data/backtests/audit/report.md:86)).

## 1 Feasibility

For annualized after-cost Sharpe \(S\),

\[
S=\sqrt{250}\frac{\mu_d}{\sigma_d},
\qquad
\mu_d=\frac{S\sigma_d}{\sqrt{250}}.
\]

Thus:

- \(\sigma_d=\$75,\ S=3 \Rightarrow \mu_d=\$14.23\), or \$3,558 expected annually.
- \(\sigma_d=\$150,\ S=2 \Rightarrow \mu_d=\$18.97\), or \$4,743 annually.
- \(\sigma_d=\$150,\ S=6 \Rightarrow \mu_d=\$56.92\).

Those calculations agree with the Monte Carlo. What is incomplete is the Gaussian assumption: CL returns have jumps, volatility clustering, serial dependence and event-day tails; a Brownian bridge cannot reproduce those. It also needs explicit consistency-rule stopping and uncertainty in estimated \(\mu\).

For one MCL, base round-trip cost is

\[
1.72+2(1\text{ tick}\times \$1)=\$3.72=3.72\text{ ticks},
\]

and the two-tick-per-side stress cost is 5.72 ticks. With \(N\) approximately independent trades/year and trade-return standard deviation \(s_t\) ticks,

\[
e_{\text{net}}=\frac{S s_t}{\sqrt N},\qquad
e_{\text{gross}}=C+e_{\text{net}}.
\]

Assuming 250–500 trades/year and \(s_t=30–60\) ticks, Sharpe 3 requires 4.0–11.4 net ticks/trade: 7.7–15.1 gross ticks at base costs, or 9.7–17.1 under stress. Under your \(\sigma_d=\$75\) case, one trade/day requires 14.23 net ticks; two independent trades/day require about 7.12.

Multiplying MCL contracts scales mean, volatility and drawdown together, so Sharpe is unchanged. Your results imply approximately:

- One MCL: Sharpe 3 may satisfy the gate.
- Two MCL: approximately Sharpe 6 is needed.
- Three MCL: likely implausible without a still higher Sharpe.

The audit’s \$300/trade result is specific to noisy one-CL ORB-like paths, not a universal edge threshold.

Keep \$1,000 as a diagnostic safety reserve, but replace the hard p95 gate with a directly relevant requirement: upper-confidence-bound probability of failing the \$2,000 MLL before passing must be below 1%, with empirical block paths, observed intraday excursions, stressed costs, consistency rules and a \$500 operational reserve. Also report p95/p99 drawdown. This is at least as safe but does not reject a strategy merely because a nonbinding \$1,000 excursion occurs. The current guide itself describes the threshold as a safety gate rather than a profit guarantee ([Guide §10](/home/mrullldhm/personal/propfirm/TRADING_BOT_GUIDE.md:485)).

## 2 Method

Use these dates:

- **Discovery:** 2010-06 through 2016-12.
- **Selection:** purged expanding walk-forward tests for 2017, 2018, …, 2021; aggregate only genuinely out-of-fold returns.
- **Confirmation:** freeze one specification, then open 2022-01 through 2026-10 once.
- **Final evidence:** mandatory 3–6 month prospective paper test.

Because three earlier studies touched 2022+, call it a *quasi-holdout*, even for newly specified hypotheses. It cannot support the same claim as untouched future data.

Before confirmation, preregister feature definitions, roll handling, decision/fill times, horizons, costs, missing-bar rules, model family and hyperparameter bounds, primary statistic, multiplicity universe, gates, Monte Carlo method and immutable code/data hashes. Log every attempted idea, including informal ones.

Use stationary-bootstrap Hansen SPA/White Reality Check during selection, then Romano–Wolf max-\(t\) step-down family-wise error control at 5% across the ten hypotheses, horizons and decision times. DSR and PBO remain secondary diagnostics, not substitutes for a locked holdout. These methods address precisely the data-snooping problem identified by White (2000), Hansen (2005), and Bailey–López de Prado (2014).

Power, assuming 4,000 independent days, 80% power and two-sided 5% significance:

\[
\text{MDE}= (1.96+0.84)/\sqrt{4000}=0.044\sigma,
\]

equivalent to annual Sharpe 0.70. Bonferroni-equivalent control for ten tests raises this to \(0.058\sigma\), Sharpe 0.91. With one 30-tick observation/day, that is 1.73 net ticks. Five independent observations/day reduce it to 0.77 tick; intraday correlation of 0.10 raises it to about 0.92. Intraday bars therefore do not create thousands of independent observations—cluster inference by trading day. The roughly 1,200-day confirmation sample can detect only about Sharpe 1.7 after ten-test correction.

## 3 Top 10 hypotheses

Common first-test pass rule: out-of-fold gross advantage must exceed the 5.72-tick stress cost, Romano–Wolf \(p<.05\), daily Sharpe ≥1.5, and the sign must agree in 2010–15 and 2016–21.

1. **Term-structure-conditioned momentum.** Backwardation proxies scarcity/risk premium (Gorton, Hayashi & Rouwenhorst, 2013, *Fundamentals of Commodity Futures Returns*). At 09:00 ET, interact front/second slope with 5/20-day front return; hold to 16:05; test day-clustered mean net return; pass common rule.

2. **Post-EIA response.** Announcements concentrate price discovery, though rapid adjustment makes this doubtful (Ederington & Lee, 1993, *How Markets Process Information*). Wednesdays at 10:35, trade the 10:30–10:35 direction only after top-decile abnormal volume; exit 11:30; test against matched non-EIA Wednesdays; pass common rule.

3. **Front–second spread dislocation.** Temporary relative pressure may mean-revert. Every 30 minutes from 09:00–14:00, trade front against a causal 20-day same-minute spread z-score; hold 60 minutes; test non-overlapping observations; pass common rule.

4. **Overnight handoff.** Large Globex moves may continue when information-driven and reverse when liquidity-driven. At 09:00, classify 18:00–09:00 return by volume and term structure; hold to noon; test interaction coefficient and trading return; pass common rule.

5. **Multi-day time-series momentum.** Futures trends are established in diversified data, not necessarily standalone CL (Moskowitz, Ooi & Pedersen, 2012, *Time Series Momentum*; Miffre & Rallis, 2007). At 09:00, sign 1/5/20-day roll-safe return; exit 16:05; pass common rule.

6. **Volatility-conditioned continuation/reversal.** High-volatility shocks may continue; ordinary moves may reverse. At 09:30, combine 30-minute return with causal realized-volatility percentile; hold 60 minutes; test the preregistered interaction; pass common rule.

7. **Volume-shock continuation.** Unexpected volume can identify informed price pressure. At each hourly mark 09:00–14:00, trade only when signed return and same-minute relative volume are both extreme; hold 60 minutes; pass common rule.

8. **Settlement-to-close reversal.** Benchmark-related pressure near settlement may unwind. At 14:35, fade the 14:25–14:35 abnormal move; exit 16:05; compare with matched same-volatility days; pass common rule.

9. **Calendar-time seasonality conditional on regime.** Intraday seasonality exists widely, but unconditional effects are easily mined. Preselect only 08:00, 09:00, 10:35 and 14:35; predict the next 60 minutes using weekday × backwardation state; max-\(t\) across 20 cells; pass common rule.

10. **Roll-window pressure reversal.** Front-month switching may create transient distortions, but continuous-series artifacts make the prior weak. On identified roll days, discard the 00:00 splice return; at 09:00 fade only within-contract spread changes; exit noon; compare with matched non-roll days; pass common rule. Theory-of-storage motivation: Working (1949) and Bessembinder et al. (1995), *Mean Reversion…Futures Term Structure*.

## 4 Predictability-ceiling study

Yes—this is the best first kill-test, provided “ceiling” means *best performance within a declared model and feature class*, not proof that no strategy exists.

Use causal features from front/second OHLCV: returns, ranges, realized volatility, volume surprises, VWAP distance, term-structure slope/change, time-of-day, weekday and roll flags. Never compute returns through a continuous-contract splice.

Fix decision times at 08:00, 09:00, 10:35, 12:00 and 14:35 ET; horizons 5, 15, 30, 60, 120 minutes and 16:05. Predict executable next-open returns. Compare ridge, elastic net, shallow boosted trees and a constant-zero benchmark. Use nested expanding walk-forward CV, horizon-length purging, a one-day embargo, day clustering, and non-overlapping live positions.

Primary output is cross-fitted P&L after 1- and 2-tick-per-side costs—not \(R^2\). Apply the full max-\(t\) correction to models, times and horizons.

Controls:

- Block-shuffled/circularly shifted labels to measure the complete pipeline’s false-positive rate.
- Randomized features and deliberately leaked features to verify detection.
- Planted executable edges of 1, 2, 4 and 8 net ticks to estimate power and attenuation.
- Negative-control decision times.
- Frozen re-run on 2022+ only after all choices are locked.

## 5 Kill criteria

Conclude that **intraday CL from these two OHLCV streams is not presently viable** if:

1. The ceiling study’s simultaneous 95% upper bound is below stress breakeven at every decision/horizon;
2. The pipeline detects planted 4–8-tick edges with at least 80% power;
3. None of the ten preregistered families survives 2017–21 and positive 2022+ confirmation;
4. No candidate achieves positive walk-forward returns at both cost levels, DSR ≥0.95, PBO <0.5 and ≤1% upper-bound failure-before-pass risk.

That conclusion is domain-limited, not “CL is unpredictable.” Next acquire genuinely new information—EIA/API surprises, trade/quote or depth data, cross-energy instruments and contract-specific identifiers—or move to slower horizons/diversified markets. Do not run another indicator grid on the same bars.

## 6 Claude/Codex split

Claude should own the written preregistration, canonical feature/strategy implementation, locked trial ledger and blinded confirmation package.

Codex should independently reconstruct every signal from raw bars, implement a separate reference pipeline, verify roll/time-zone/fill/cost logic, reproduce selected trades by hand, and independently recompute SPA, max-\(t\), DSR, PBO and Combine simulations. Neither should alter specifications after viewing confirmation results. Discrepancies must be resolved against the preregistration before unblinding; both publish PASS/FAIL independently, including negative findings.

Codex session ID: 01a143ca-3a77-7403-863b-5f2f483861d1
Resume in Codex: codex resume 01a143ca-3a77-7403-863b-5f2f483861d1

## Claude's response
Codex and Claude agreed on the core design before seeing each other's drafts: start with a
predictability-ceiling study rather than another grid, the same discovery window (2010-06 .. 2016-12),
pre-registration, and day-level inference. Codex's corrections and additions were adopted as below.

## Resolution
| # | Codex point | Response | Action | Status |
|---|---|---|---|---|
| 1 | Sizing does not change Sharpe; "1-3 MCL with Sharpe ≥ 3" too optimistic (2 MCL ≈ Sharpe 6 under the same G8) | Agree: contracts scale mean, sd and drawdown together | MCL dropped by owner (D004); S001 reports results per CL count and account | resolved |
| 2 | Gaussian model misses jumps, volatility clustering, event tails, consistency stopping, uncertainty in mu | Agree | S001 uses block-bootstrapped real discovery day P&L and edge haircuts | resolved (S001 design) |
| 3 | Replace the hard p95 gate with UCB P(fail before pass) < 1% (+ $500 reserve, stressed costs), still report p95/p99 | Good candidate; owner chose "keep, recalibrate later" | recorded in D003 as the candidate rule | open until S001 |
| 4 | Discovery 2010-06..2016-12; selection = purged expanding walk-forward 2017-2021; confirmation 2022+ once; 3-6 month prospective test | Agree | D001, PROTOCOL §2 (practice ≥ 8 weeks, 3-6 months recommended) | resolved |
| 5 | Call 2022+ a quasi-holdout | Agree | HOLDOUTS.md, PROTOCOL §2 | resolved |
| 6 | Full pre-registration contents and log of every attempted idea | Agree | PROTOCOL §5; LEDGER.csv | resolved |
| 7 | SPA / Reality Check for selection, Romano-Wolf max-t FWER, DSR/PBO secondary | Agree, with tiers | PROTOCOL §4.3 (validation families at one-sided 0.01, budget 25) | resolved |
| 8 | Power: full sample detects SR ~0.7; confirmation ~1.7 after 10-test correction; cluster by day | Agree | PROTOCOL §4.1 and §4.5 | resolved |
| 9 | Ten hypotheses with first tests and a common pass rule | Merged with Claude's list (source tags) | BACKLOG H001-H016; MCL stress cost replaced by CL stress $44.02 per round trip (D004) | resolved |
| 10 | Ceiling design: pre-declared times, horizons 5-120 min + to close, ridge / elastic net / shallow trees vs zero, nested walk-forward, purge + embargo, max-t, controls (shuffled labels, random and leaked features, planted 1/2/4/8-tick edges, negative-control times) | Agree; added 20:00, 03:00 and 14:00 ET decision times to cover overnight hypotheses and H001 | S003 report design | resolved |
| 11 | Four-part kill criteria; next step = new information, not another grid | Agree | PROTOCOL §4.7 | resolved |
| 12 | Claude owns prereg / canonical code / ledger; Codex reconstructs signals and statistics independently; both publish PASS/FAIL | Agree | D002, PROTOCOL §7 | resolved |
