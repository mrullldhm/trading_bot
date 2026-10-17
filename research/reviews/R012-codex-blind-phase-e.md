---
id: R012
title: Codex blind consult, phase E (direction, new ideas, H025/H026, pre-validation fixes)
status: resolved
item: programme direction (phase E)
codex_job: task-mvbocs21-zb8y5k
created: 2026-10-17
updated: 2026-10-17
---

# R012 — Codex blind consult for phase E

## Request (summary)
Read-only, run during the planning of session 3 (2026-10-17), before the owner chose a direction.
Blind: Codex was told not to read `hypotheses/BACKLOG.md`, `journal/` or anything under `~/.claude/`
(Claude's own idea list and plan). It read STATUS, PROTOCOL, REQUIREMENTS, KNOWLEDGE, D006, prior work,
the S001-S003 reports and its own R011. Four questions:
1. Rank the directions (a) structural settlement ideas on existing data, (b) new information for CL,
   (c) pause, (d) another route; probability of success, cheapest decisive first test, kill rule; one
   recommendation.
2. 4-8 blind phase-E hypotheses with mechanism, exact causal rule, first test, frequency, kill rule and
   a validation power line.
3. Is a discovery exploration of H025 / H026 worth running, with which (at most 4) frozen variants?
4. What must change in the toolkit or protocol before any validation run?

## Codex output (verbatim)
# R012 — Blind phase-E direction review

## Q1. Direction

Ranking reflects expected value after cost and scope, not probability alone. Probabilities are subjective estimates.

1. **(b) New CL information — recommendation.** **Success probability: 12%.** Acquire CME MDP 3.0 trade-level/MBP-1 data for outright CL and the separately identified CL TAS instruments, initially only 14:20–14:35 ET. Verify TAS symbol coverage and aggressor-side fields with the vendor before purchase. This adds signed participant flow and explicitly settlement-priced volume, neither present among S003’s OHLCV, VWAP, term-structure, and calendar features (`research/studies/S003-ceiling/report.md:23-26`). Mechanism: benchmark/TAS execution can create forced settlement flow and residual dealer inventory—the only area where S002 found repeatable structure (`research/studies/S002-atlas/report.md:64-73`). **Cheapest decisive test:** quote and download only 2015–2016 discovery-window data; freeze two signals—TAS imbalance and total aggressive-volume imbalance through 14:34—then enter 14:35 and exit 16:05. Existing bars supply the outcome. **Kill:** stop before buying earlier years if neither signal has the correct sign, gross edge above 4.402 ticks, and roughly ≥8.4 gross ticks for an adequately powered 60-trade/year rule. If it passes, acquire 2010–2014 and run one logged discovery family. **Size/cost:** prior-belief estimate, not a vendor quote: a time-sliced trade/MBP-1 extract should be a few to tens of compressed GB and a hundreds-to-low-thousands USD purchase; full-session depth could be much larger and cost thousands. **OWNER APPROVAL — data purchase and phase-E direction.**

2. **(a) Existing-data structural settlement ideas.** **Success probability: 3%.** This ranks second because it is cheap, despite the low probability. Settlement continuation averaged only 2.6 gross ticks and fell to 0.4 in 2015–2016; the unconditional drift was 2.2 gross ticks (`research/studies/S002-atlas/report.md:67-68`). S003’s 14:35 models also remained below cost (`research/studies/S003-ceiling/report.md:68-75`). **Cheapest decisive test:** the four fixed variants in Q3, discovery only. **Kill:** no variant advances unless every PROTOCOL §4.4 condition holds, especially positive stress-cost P&L, same sign in 2015–2016, and adequate validation power (`research/PROTOCOL.md:128-143`). Expect zero promotions. **OWNER APPROVAL — direction selection only; no purchase or gate change.**

3. **(c) Pause CL intraday research.** **Success probability: 0% while paused.** This is rational if no data budget is available: 0/432 S003 strategies beat costs and 8-net-tick edges were the smallest reliably detected size (`research/studies/S003-ceiling/report.md:68-96`), while D006 generally requires 8–16 net ticks at the best feasible cells (`research/REQUIREMENTS.md:133-144`). **Cheapest decisive test:** none. Preserve the unopened validation and quasi-holdout. **Kill/restart rule:** reopen only for a named information source with a causal rule, affordable discovery sample, and validation power capable of detecting the required edge. **OWNER APPROVAL — programme direction.**

4. **(d) Restart in another Topstep market.** **Success probability: 8% for an analogous strategy, conditional on a full reset; 0% for the present CL objective.** This ranks below pausing because it discards accumulated CL-specific work and requires new data, feasibility, costs, fills, and market-specific rules. A reasonable first candidate is a liquid equity-index future, but that is prior belief rather than repository evidence. **Cheapest decisive test:** obtain discovery-period one-minute bars for one market and run a reduced S001/S002/S003 sequence before any hypothesis validation. **Kill:** stop if its short-window stress-cost requirement and simultaneous bounds are no better than CL, or if no structural effect clears stress costs in the latest discovery block. **OWNER APPROVAL — change to D004’s CL-only scope, new data purchase, and new market-specific gates/cost model** (`research/README.md:97-105`; `research/REQUIREMENTS.md:114-123`).

**Recommendation:** choose **(b)**, but stage it: quote and test a narrow 2015–2016 settlement-flow extract first. Do not buy full-session order-book history initially.

## Q2. Blind phase-E hypotheses

Power lines use the optimistic single-rule normal approximation

\[
MDE_{net}=(z_{0.99}+z_{0.80})\,sd/\sqrt n
          =3.168\,sd/\sqrt n,
\]

with \(n=1{,}250\times(\text{trades/year}/250)=5\times\text{trades/year}\). The stress round-trip cost is 4.402 ticks (`research/REQUIREMENTS.md:114-122`), so gross edge for 80%-powered rejection is approximately \(4.402+MDE_{net}\). Day clustering, serial dependence, estimation, and Romano–Wolf multiplicity can only worsen these figures.

### E1. Settlement TAS/aggressive-flow continuation

**Data:** repo lacks trade/MBP-1 and TAS data. **OWNER APPROVAL — data purchase.**

**Mechanism:** benchmark-constrained participants must execute at settlement; liquidity providers absorbing a one-sided imbalance carry residual inventory after 14:30. The constraint, short duration, and limited capacity can prevent complete arbitrage.

**Rule:** at 14:34 ET, using only messages timestamped through 14:34:59, calculate signed TAS volume plus signed aggressive outright volume from 14:25–14:34. Trade its sign only when absolute imbalance exceeds its causal trailing-60-day 75th percentile. Enter at the 14:35 open; exit at the exact 16:05 open.

**Cheapest discovery test:** purchase 2015–2016, 14:20–14:35 only; test TAS imbalance and outright imbalance as one two-variant family.

**Frequency:** approximately 60 trades/year.

**Kill:** wrong sign in 2015–2016, fewer than 25 trades/year, gross mean ≤4.402 ticks, or discovery net edge ≤\(2MDE\); thereafter apply all §4.4 conditions.

**Power:** S002 \(sd=22.116\) ticks for 14:35–16:05 (`research/studies/S002-atlas/windows.csv:14`); \(n=5(60)=300\). \(MDE_{net}=3.168(22.116)/\sqrt{300}=4.045\) ticks; stress break-even gross \(=4.402\), powered gross \(\approx8.447\) ticks.

### E2. Cross-energy settlement lead

**Data:** repo lacks Brent, RBOB, and heating-oil bars. **OWNER APPROVAL — data purchase.** Trading remains CL-only, so D004 need not change.

**Mechanism:** physical/refining information can reach related energy contracts at different speeds, while CL settlement flow temporarily obscures CL’s common-factor price. Passive CL-only participants lose to the subsequent convergence.

**Rule:** at 14:34 ET, use returns through 14:34 for Brent, RBOB, HO, and CL over 14:25–14:34. Volatility-scale each using the prior 20 trading days; direction is the sign of the equal-weight related-energy return minus CL’s scaled return. Enter CL at the 14:35 open every eligible day; exit at the exact 16:05 open.

**Cheapest discovery test:** acquire one-minute bars only for the three related contracts and the 14:20–14:35 interval for 2015–2016; one fixed equal-weight rule.

**Frequency:** approximately 250 trades/year.

**Kill:** gross mean ≤4.402 ticks, absence in 2015–2016, or discovery net edge ≤\(2MDE\). Also kill if timestamp/holiday alignment cannot be made fully causal.

**Power:** \(sd=22.116\), \(n=5(250)=1{,}250\). \(MDE_{net}=3.168(22.116)/\sqrt{1250}=1.982\) ticks; powered gross \(\approx6.384\) versus 4.402 break-even.

### E3. EIA consensus-surprise continuation

**Data:** the repo has release dates but not point-in-time consensus forecasts or release-vintage actuals. **OWNER APPROVAL — purchase of a timestamped consensus archive if no auditable free archive exists.**

**Mechanism:** commercial hedgers and slower macro participants adjust after an unexpected physical-stock number; consensus error is information not represented by pre-release CL bars. The weekly frequency and event risk limit arbitrage capacity. EIA provides the weekly actual report and archive, but the forecast consensus must be sourced separately ([EIA WPSR](https://www.eia.gov/petroleum/supply/weekly/)).

**Rule:** at 10:35 ET on scheduled release days, using the crude-inventory actual released by 10:30 and the consensus timestamped before 10:30, set direction to \(-\operatorname{sign}(\text{actual}-\text{consensus})\). Enter at the 10:36 open; exit at the 11:30 open. No price-response filter.

**Cheapest discovery test:** obtain only dated consensus/actual pairs for 2015–2016 and join them to the existing EIA calendar and bars.

**Frequency:** approximately 50 trades/year.

**Kill:** fewer than 25/year, unreliable vintage timestamps, gross mean ≤4.402, no 2015–2016 effect, or discovery net edge ≤\(2MDE\).

**Power:** nearest supplied window is EIA 10:36–11:30, \(sd=51.609\) (`research/studies/S002-atlas/windows.csv:10`); \(n=250\). \(MDE_{net}=3.168(51.609)/\sqrt{250}=10.340\) ticks; powered gross \(\approx14.742\). This is badly underpowered unless the event edge is large.

### E4. Option-open-interest expiry pin

**Data:** repo lacks CL option chains, expiry metadata, and point-in-time open interest. **OWNER APPROVAL — data purchase.**

**Mechanism:** option dealers hedging concentrated near-expiry exposure may transact futures toward a high-open-interest strike. Mandatory hedging and jump risk can leave a limited-capacity edge. The sign of dealer exposure is not directly observed, so this mechanism is uncertain.

**Rule:** at 14:34 ET on CL option-expiry days, use only prior-day published open interest. If CL at 14:34 is 5–20 ticks from the largest nearby-OI strike, trade toward that strike; otherwise no trade. Enter at 14:35 open; exit at exact 16:05 open.

**Cheapest discovery test:** first verify that auditable weekly expiries and point-in-time OI exist for 2015–2016; then buy only expiry, strike, and OI snapshots. One rule, no strike optimization.

**Frequency:** prior-belief estimate 30–50/year; power calculation uses 50. Kill immediately if actual history gives fewer than 25/year.

**Kill:** evidence that OI is revised/non-vintage, frequency below G2, gross mean ≤4.402, no latest-block effect, or discovery net edge ≤\(2MDE\).

**Power:** \(sd=22.116\), \(n=250\). \(MDE_{net}=3.168(22.116)/\sqrt{250}=4.431\) ticks; powered gross \(\approx8.833\).

### E5. Brent-to-CL overnight dislocation at the European/US handoff

**Data:** repo lacks Brent bars. **OWNER APPROVAL — data purchase.**

**Mechanism:** Brent incorporates non-US physical and geopolitical information during European hours; CL may adjust incompletely before US participation increases. Traders requiring WTI exposure, rather than cross-market exposure, can leave a convergence opportunity.

**Rule:** at 07:55 ET, using bars through 07:54, calculate the volatility-scaled Brent return minus CL return from 03:00–07:54. Trade the residual’s sign only when its absolute value exceeds its causal trailing-60-day 80th percentile. Enter CL at 07:56 open; exit at 08:25 open.

**Cheapest discovery test:** acquire 03:00–07:55 Brent one-minute bars for 2015–2016 only; one fixed residual rule.

**Frequency:** approximately 50 trades/year.

**Kill:** timestamp/session mismatch, gross mean ≤4.402, wrong or absent sign in 2015–2016, or discovery net edge ≤\(2MDE\).

**Power:** S002 07:56–08:25 \(sd=21.300\) (`research/studies/S002-atlas/windows.csv:3`); \(n=250\). \(MDE_{net}=3.168(21.300)/\sqrt{250}=4.268\) ticks; powered gross \(\approx8.670\).

### E6. Public commodity-index roll pressure

**Data:** existing CL0/CL1 bars and contract definitions suffice for prices, but the repo lacks an auditable point-in-time index roll calendar/rule history. No purchase is necessarily required; historical rule changes must be documented.

**Mechanism:** commodity-index funds must sell front-month and buy deferred contracts on scheduled roll days. Benchmark mandates create predictable flow that cannot simply be deferred; arbitrageurs bear basis and outright-price risk.

**Rule:** on the pre-specified public index roll dates, at 14:34 ET use only the calendar known before that session. Short one front-month CL at the 14:35 open; exit at exact 16:05 open. No price, contango, or volatility filter. The precise historical roll-day definition must be frozen before viewing returns.

**Cheapest discovery test:** reconstruct and independently verify the 2015–2016 calendar, then run the single rule on existing bars.

**Frequency:** prior-belief estimate about 60 trades/year; uncertain until the historical rule is verified.

**Kill:** calendar cannot be reconstructed without hindsight, fewer than 25 trades/year, gross mean ≤4.402, absence in 2015–2016, or discovery net edge ≤\(2MDE\).

**Power:** \(sd=22.116\), \(n=300\). \(MDE_{net}=3.168(22.116)/\sqrt{300}=4.045\) ticks; powered gross \(\approx8.447\).

## Q3. H025 and H026

**Verdict:** run one cheap discovery family to close the settlement question, but expect no promotion. H025 is worth the small cost; H026 is already economically rejected as a standalone rule because its 2.2-tick gross mean is below the 4.402-tick stress cost (`research/studies/S002-atlas/report.md:67-68`). Do not spend validation budget unless a conditioned H025 variant clears every promotion rule.

Freeze these four variants before looking:

1. **H025 move filter:** at 14:34, direction of the 14:25–14:34 move; trade only if its absolute size exceeds the trailing-60-eligible-day 75th percentile. Enter 14:35 open, exit exact 16:05 open.

2. **H025 volume filter:** same direction and times; trade only if 14:25–14:34 volume exceeds its trailing-60-day 75th percentile.

3. **H025 union filter:** same direction and times; trade when either causal percentile filter is met. Do not test the intersection separately because its likely frequency risks G2 and poor power.

4. **H026 fixed short:** at 14:29, with no return or volume filter, enter short at 14:30 open and exit at 15:00 open. This is a formally executable restatement of the atlas effect, not another threshold search.

Expected outcome against PROTOCOL §4.4:

- H026 should fail rule 3 mechanically unless exploration produces a materially larger number than the already measured 2.2 gross ticks; stress break-even is 4.402 (`research/PROTOCOL.md:128-135`).
- H025 may achieve exploratory \(q<0.10\), but is likely to fail the required 2015–2016 sign/size guard because the parent effect decayed from 4.4 to 0.4 ticks (`research/studies/S002-atlas/report.md:64-68`).
- At about 60 trades/year, H025’s optimistic validation \(MDE_{net}\) is 4.045 ticks and powered gross is 8.447; the discovery net effect would need to be at least about 8.09 ticks under the protocol’s “MDE no larger than half the discovery effect” rule. The naive parent is nowhere close.
- **Expected promotions: 0/4.** A promotion would be surprising and should receive an outlier/day-concentration and roll-proximity red team before preregistration.

## Q4. Required changes before validation

1. **Make the 16:05 exit strict. Blocking. OWNER APPROVAL.** For `FLAT`, require a bar exactly at the computed 16:05/12:55/roll/expiry cutoff; if absent, mark the window invalid—never substitute 16:06–16:09. The current common exit tolerance permits up to five minutes late (`propfirm_research/grid.py:29-31`, `propfirm_research/grid.py:109-114`), despite the protocol requiring flat by 16:05 (`research/PROTOCOL.md:145-151`). Add missing-bar tests for ordinary, short, roll, and expiry cutoffs. Preserve S001–S003 as exploratory historical results with the disclosed convention; do not rerun them. This is the unresolved R011 item (`research/reviews/R011-codex-s003-replication.md:99-112`).

2. **Synchronize the live G8 rule everywhere. Blocking clerical inconsistency; no new gate approval required.** PROTOCOL §4.6 still states the superseded 50%-MLL drawdown gate (`research/PROTOCOL.md:152-153`), while D006 and REQUIREMENTS specify stress-cost pass ≥50% and fail-UCB ≤10% with a $500 reserve (`research/decisions/D006-g8-recalibration-proposal.md:36-55`; `research/REQUIREMENTS.md:49-60`). The `combine.py` module header and ordinary `odds()` output also still describe/report old `g8_ok`; only `gate_g8()` implements D006 (`propfirm_research/combine.py:1-7`, `propfirm_research/combine.py:210-236`). Rename the legacy diagnostic and make confirmatory callers use only `gate_g8`.

3. **Align and strengthen the preregistration schema. Blocking.** PROTOCOL requires separate stage-1/stage-2 tests, filters, sizing, decision times, horizons, bootstrap counts, and environment/data hashes (`research/PROTOCOL.md:168-191`); code instead accepts generic `null`/`test` strings and omits several fields (`propfirm_research/prereg.py:23-31`). Require an explicit combined statistic, all variants, causal thresholds, missing-bar policy, exact entry/exit bars, account, sizing, neighbour set for G9, power inputs, decay rule, and discovery trial count. Validate exact project costs—not merely nonnegative numbers—and enforce the permitted contract/account combinations; current checks do neither (`propfirm_research/prereg.py:38-67`).

4. **Verify frozen data at execution, not only registration. Blocking.** Registration records data hashes (`propfirm_research/prereg.py:70-89`), but the protected loader checks only the run token and then reads the current bar store without comparing its files to those hashes (`propfirm_research/data.py:41-83`). Confirm the exact runtime input hashes before opening validation and include every calendar, definition, external dataset, and code file used.

5. **Freeze the portfolio-building and account-selection rule before the first validation look. Blocking. OWNER APPROVAL — sizing/account rule.** The protocol already requires membership, weights, and sizing to be fixed before validation (`research/PROTOCOL.md:49-51`), and STATUS lists this as unfinished (`research/STATUS.md:46-50`). It must specify how multiple validated signals, simultaneous signals, no-trade days, account size, and the one-CL preference are handled.

6. **If option (b) is chosen, extend the firewall to external data before exploration progresses. OWNER APPROVAL — purchase and any new dependency.** `propfirm_research.data` currently exposes only CL.v.0/v.1 OHLCV (`propfirm_research/data.py:20-21`, `propfirm_research/data.py:86-91`). Add immutable, vintage-aware loaders for trade/TAS or other external inputs, with the same period boundaries, access ledger, hashes, timestamp cutoffs, and warm-up restrictions. Never join revised consensus/OI data as though it were point-in-time.

7. **Add design-specific power simulation before freezing each family.** The simple IID arithmetic in Q2 is only a screen. Use the actual discovery trade mask, day clustering, missing sessions, the exact combined N1-plus-skill statistic, and Romano–Wolf across all variants. Park the family if the simulated 80% MDE exceeds half its discovery net effect, as already required (`research/PROTOCOL.md:137-143`).

8. **Dry-run the exact validation executable on synthetic and discovery data, then make result writing atomic.** The protected period is irreversibly marked open before data loading (`propfirm_research/prereg.py:119-138`); therefore a coding crash consumes the one shot. Before opening validation, verify deterministic seeds, complete outputs, hashes, null controls, strict exits, G1–G9, and D006 on the same code path.

Codex session ID: 01a14751-b011-79d1-b76c-919542026a3d
Resume in Codex: codex resume 01a14751-b011-79d1-b76c-919542026a3d

## Claude's response
Claude's own analysis during planning reached the same direction before reading this answer (TAS data:
dealers who sell trade-at-settlement contracts hedge in the 14:28-14:30 window, so the TAS book shows
the crowded side before the push). The owner chose it the same day (D008).

**Q1 Direction: agree with (b), staged.** Codex's probabilities are subjective. Claude's own estimate
for (b) is lower (a few percent): under PROTOCOL §4.5 a promotable discovery effect needs a net annual
Sharpe of about 2.85 (validation MDE ~1.42 at alpha 0.01 one-sided, 80% power, and MDE <= half the
discovery effect), which no CL signal has come near. (b) still has the best expected value per dollar
because it is the only route that adds information the S003 ceiling never had. Codex's cost guess
(hundreds to low thousands USD) is replaced by exact vendor quotes before any purchase (D010).

**Q2 Ideas** (added to BACKLOG as H027-H032, source Codex R012):
- E1 -> H027 (TAS / aggressive-flow settlement continuation): agree, first priority. The card must fix
  the sign before looking: residual dealer inventory after 14:30 predicts continuation, while a hedging
  push into the window that unwinds after 14:30 predicts reversal (S002 saw both a continuation and a
  negative post-settlement drift). Needs aggressor side on 2015-16 trades: verify before buying.
- E2 -> H028 (cross-energy settlement lead): agree, cheap second (1-minute bars). Note: RB and HO settle
  in the same 14:28-14:30 window, so their own settlement flows can contaminate the residual; NYMEX
  Brent (BZ) is thin and ICE Brent is a different dataset (coverage to be checked).
- E3 -> H029 (EIA consensus surprise): parked on power. MDE 10.3 net ticks on ~250 validation trades is
  far above any plausible post-release drift (S002: direction-free after 5 minutes), and a point-in-time
  consensus archive is not available to us.
- E4 -> H030 (option-OI pin): idea, prior C: needs option open interest history and the dealers' sign
  is unobserved.
- E5 -> H031 (Brent -> CL European handoff): idea; data source unverified.
- E6 -> H032 (index roll pressure): prior C-. An index roll is a spread trade (sell front, buy next), so
  the outright front need not fall, and S002 found nothing in 389 roll-week days. The calendar could be
  rebuilt from published rules if ever needed.

**Q3 H025 / H026: agree.** The four variants are adopted verbatim (with the strict exit of Q4.1) and
frozen in the cards before any run. H026 alone already fails the stress cost; the run closes the
question with real numbers and builds the settlement-window harness that H027 / H028 will reuse.

**Q4 Before validation: agree with all eight.**
1. Strict exit: adopted by the owner (D009). Claude applies it to every exit (fixed horizons too):
   never a bar after the exit minute; a missing exact bar makes the window invalid.
2. G8 text sync: clerical (D006 is decided); done this session.
3, 4, 7, 8. Prereg schema, runtime data-hash check, design-specific power simulation, validation dry run
   with atomic result writing: blockers before the first pre-registration (STATUS).
5. Portfolio / account rule: owner decision before the first validation look (STATUS).
6. Firewall loaders for new data: built and reviewed (R016) before any analysis of new data.

## Resolution
| # | Item | Action | Status |
|---|---|---|---|
| Q1 | direction | owner chose (b) staged + one H025/H026 run (D008) | resolved |
| Q2 | E1-E6 | BACKLOG H027-H032; E3 parked on power | resolved |
| Q3 | H025/H026 variants | adopted verbatim, frozen in the cards | resolved |
| Q4.1 | strict exit | D009; `grid.py` change reviewed in R013 | resolved |
| Q4.2 | G8 text sync | PROTOCOL §4.6, glossary, `combine.py` key rename | resolved |
| Q4.3-4.5, 4.7-4.8 | pre-validation hardening | STATUS blockers before the first prereg | open (tracked) |
| Q4.6 | firewall for new data | step 5 of session 3 plan, review R016 | open (tracked) |
