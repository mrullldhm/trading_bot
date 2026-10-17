---
id: KNOWLEDGE
title: What we know about CL
status: living
updated: 2026-10-17
---

# Knowledge base

Facts about CL intraday trading and about this project's pipeline, each with an evidence grade and a
source. Seeded from strategies 1-8 and the backtest audit (all in-sample 2010-2021 unless stated).

| Grade | Meaning |
|---|---|
| **CONFIRMED** | Holds out of sample or was checked independently (second vendor, official data, Codex) |
| **VALIDATED** | Passed a pre-registered validation test in this programme (none yet) |
| **EXPLORATORY** | Seen in-sample only, often the best of many tries. A lead, not a fact |
| **REFUTED** | Tested out of sample and failed |

Paths starting `data/backtests/` are local reports (not in git); `prior-work/STRATEGIES-1-8.md` summarises them.

---

## K1. Data and pipeline

| ID | Fact | Grade | Source |
|---|---|---|---|
| K1.1 | Databento 1-minute bars, 10,400,832 rows (5,653,891 front CL.v.0, 4,746,941 second CL.v.1), 2010-06-07 .. 2026-10-13 UTC; validation PASS (no duplicates, all on the $0.01 grid) | CONFIRMED | README "Data quality results" |
| K1.2 | Daily closes match official WTI spot (EIA via FRED) 2010-2021: return correlation 0.912, median level gap $0.03; largest gaps on roll days (2020-03-27: $6.17) | CONFIRMED | `data/backtests/audit/report.md` |
| K1.3 | Vendor cross-check (Massive, 2024-10 .. 2026-10): OHLC exact 99.93-99.99%, close exact 98.2%; Databento's close is the true last trade. Do not build rules on an exact 1-minute close | CONFIRMED | README; `data/crosscheck/report.md` |
| K1.4 | Rolls happen mostly at 00:00 UTC (19:00/20:00 ET), else at a session reopen; never in US daytime. 196 rolls in 16.3 years. A roll jump (e.g. −417 ticks on 2026-05-18) is not P&L | CONFIRMED | README_DATA "Roll days" |
| K1.5 | Volume spikes line up at 09:00 ET (x2.88 summer / x2.70 winter), Wed 10:30 EIA (x5.30 / x4.41) and 14:28-14:30 settlement (x3.49 / x3.48): the time-zone and DST handling is right | CONFIRMED | audit report "Checks" |
| K1.6 | The engines have no look-ahead (truncation and scramble tests), costs are exact (paired long/short cost 2 x (fee + 2 slips) to 1e-14), mirror symmetry holds | CONFIRMED | audit report; `tests/test_audit_engine.py` |
| K1.7 | The pipeline can find a real edge: a planted post-breakout drift is detected from ~$150/trade with the drawdown gate off | CONFIRMED | audit "Positive control" |

## K2. Costs and noise

| ID | Fact | Grade | Source |
|---|---|---|---|
| K2.1 | A CL round trip costs $24.02 (fee $4.02 + 1 tick per side); random 60-minute trades lose exactly that (−$26.99 vs −$24.02 expected, z −1.06, 19,949 trades) | CONFIRMED | audit "Coin flip" |
| K2.2 | One extra tick per side wipes out most edges: profitable configs fall EMA 40→3, ORB 5,365→312, ACD 1,064→630; champions at 3 ticks per side are near zero or negative except Crabel | EXPLORATORY | prior-work table |
| K2.3 | With zero costs many configs look profitable (ACD 88%, ZAB 68%, Crabel 60%), but the gate-free walk-forward after costs is negative for EMA, ORB, ZAB and ACD; only Crabel stays positive (+$18,566) | EXPLORATORY | audit "Pipelines under other assumptions" |
| K2.4 | Some patterns lose even before costs: VWAP Break (PF 0.93 at zero cost, 2018-2026), Momentum Pullback (−$11 to −$14/trade gross), Pine momentum script (−$6 to −$10/trade gross) | CONFIRMED (over 16 years, both sides) | README strategies 6-8 |

## K3. Risk and the drawdown wall

| ID | Fact | Grade | Source |
|---|---|---|---|
| K3.1 | On 1 CL, every champion's p95 60-day drawdown is $1,886-3,154; with no edge the lowest p95 of any profitable config is $2,244. The $1,000 gate (G8) is the binding constraint | CONFIRMED (structural) | audit "Which gate is the wall" |
| K3.2 | Configs failing only G8: EMA 2, ORB 36, ZAB 12, Crabel 21, ACD 206 | EXPLORATORY | audit |
| K3.3 | A planted ~$150/trade edge passed the simulated Combine 83% of the time (fail 14%) yet G8 rejected it (p95 $1,982). With every gate, an edge needs ~$300/trade on 1 CL | CONFIRMED (pipeline property) | audit positive control |
| K3.4 | Trade MAE on 1 CL: median / p95 ORB $370 / $991, ACD $280 / $950, EMA $280 / $1,088 | EXPLORATORY | prior-work |
| K3.5 | Micro contracts (MCL) did not rescue small edges: fees eat them (ACD $45 → $3-16 per trade at 1-5 MCL); 1 MCL never reaches the target within 250 days. MCL is now out of scope (D004) | CONFIRMED (cost arithmetic) | README lessons; audit |
| K3.6 | Feasibility (S001, real CL discovery noise, planted edges, DLL on): pass >= 50% with fail <= 25% needs an after-cost annual Sharpe of **1.6-2.6 at the best size**, usually 3-7, and a per-trade IC of **0.17-0.3+**; adding G8 raises it to Sharpe **3.1+** (IC 0.43+) | CONFIRMED (Codex replication R005) | `studies/S001-feasibility/report.md` |
| K3.7 | G8 alone, and the fail-bound rule alone, are met by accounts that barely trade: 8 of the 50 G8 cells pass < 20%; Part A 150K, SR 0.5, $75/day meets G8 and passes ~0% | CONFIRMED (R005) | S001 report §3-4; D006 |
| K3.8 | More CL contracts always raise the edge needed (MLL fixed in $); 150K x1 needs the least edge per trade, 50K x1 is quickest but fails most | CONFIRMED (R005) | S001 report §2 |
| K3.9 | Zero-edge 1 CL trade sd (2010-16): 14:35-16:05 22 ticks, 14:00-14:30 37, 09:00-10:00 49. Short quiet windows need 4-8 net ticks per trade; holding 09:00-16:05 needs 32+ | CONFIRMED (R005) | S001 report; R005 |
| K3.10 | Zero edge after costs, 1 CL every day on 50K: pass 12-19%, fail 81-88% (the luck floor) | CONFIRMED (R005 cell 4: 16.5% vs 16.6%) | S001 report §1 |

## K4. Time of day and sessions

| ID | Fact | Grade | Source |
|---|---|---|---|
| K4.1 | Anchors that helped breakout-type rules: 09:00 ET (NYMEX open) and London 08:00 beat 08:30 ET; the 18:00 ET Globex open was worst in every view (ORB 0.0% profitable, median −$39) | EXPLORATORY | ORB/ZAB/Crabel/ACD reports |
| K4.2 | EMA x VWAP: New York held the best single config but the worst median (−$35.9); at zero cost Asian and London beat New York | EXPLORATORY | ema_vwap report |
| K4.3 | Momentum Pullback: only the New York session produced any profitable configs | EXPLORATORY | momentum report |
| K4.4 | **Settlement continuation**: the 14:25-14:35 move predicts 14:35-16:05 in the same direction (corr 0.16, sign IC 0.12, gross 2.6 ticks/trade, q 5e-5) but it **decays**: 4.4 / 2.6 / 0.4 ticks in 2010-12 / 2013-14 / 2015-16. Below cost (2.4) on average | CONFIRMED (discovery, R009) | S002 report |
| K4.5 | **Post-settlement drift**: 14:30-15:00 averages -2.2 ticks (t -5.9), negative in every year 2010-16 and every block; below cost alone | CONFIRMED (discovery, R009) | S002 report |
| K4.6 | EIA 10:30: the 10:30-10:34 move is x2.7 the same minutes on other weekdays (volume x4.6) and x3.1 its own 10:00-10:14; the first 5 minutes predict nothing to 11:30 | CONFIRMED (discovery, R009) | S002 report |
| K4.7 | CL0 and CL1 move together (corr 0.99 over 30 minutes at 09:00 / 14:00); the CL0-CL1 spread change (sd 3-5 ticks) predicts nothing for the next 25-55 minutes | CONFIRMED (discovery; counts by R009) | S002 lead-lag table |
| K4.8 | 1-60 minute returns mean-revert (VR 0.89-0.94 NY, 0.87-0.92 London, 0.78-0.86 Asia) in every block: mostly bid-ask bounce of last-trade prices, not a tradeable edge. Variance ratios must use a filled minute grid; unbroken traded stretches select fast markets in thin hours | CONFIRMED (R009 VR(30) 0.904 vs 0.905) | S002, R008 |
| K4.9 | Liquidity: Asia 18:30-02:00 has 15-27 lots/min and 25-40% thin minutes (< 5 lots), 83-93% minute coverage; 18:05 entries are thin 20% of the time; 09:00-11:00 and 14:00-14:30 carry 670-1,080 lots/min | CONFIRMED (descriptive) | S002 half-hour table |
| K4.10 | Contango dominated 2010-16 (1,315 vs 299 synchronised days); no term-structure regime changes the naive overnight -> NY or first-hour -> rest rules beyond noise (best q 0.19) | CONFIRMED (counts R009) | S002 regimes |
| K4.11 | **Conditioned settlement continuation (H025)**: trading the 14:25-14:34 direction at 14:35 to 16:05 only when the absolute move is above its trailing 60-day 75th percentile gives 5.85 gross ticks per trade (378 trades, t 4.3, net Sharpe 0.97 at base cost), twice the naive 2.75, but it decays 9.5 / 5.9 / 1.6 ticks by block (below cost in 2015-16) and is far from validatable (needs ~10 net ticks). A volume filter does worse (2015-16 negative) | CONFIRMED (discovery, one frozen family; Codex replication R015 exact) | hypotheses/H025 card |
| K4.12 | **Executable post-settlement short (H026)**: short 14:30 -> 15:00 every day earns 2.25 gross ticks (1,616 trades, t 6.1, positive in every block) = -0.16 net at base cost | CONFIRMED (discovery; R015 exact) | hypotheses/H026 card |

## K5. Direction, holding period, stops, filters

| ID | Fact | Grade | Source |
|---|---|---|---|
| K5.1 | Short side looked better in 2010-2021 (ACD short median +$0.32 vs long −$12.1; Crabel short −$2.3 vs long −$25.5), but that period holds the 2014-15 and 2020 crashes, and ORB/ZAB champions were long-only | EXPLORATORY (likely period drift) | ACD, Crabel reports |
| K5.2 | Holding to the session end beat fixed exits (ACD 49% profitable vs 25%; ZAB 42% vs 24%; Crabel 46% vs 31%); the gross value of signals grew with the horizon | EXPLORATORY | ORB family reports |
| K5.3 | Longer timeframes and longer opening ranges were better (EMA: 1-15 min 0% profitable, 60 min ~4%; ORB 60-min range 2.0% vs ≤ 0.1% for 5-15 min) | EXPLORATORY | ema_vwap, orb reports |
| K5.4 | Waiting for a close (or ACD's time acceptance) beat raw stop entries; touch entries never made money | EXPLORATORY | orb, ema_vwap reports |
| K5.5 | Wide stops beat tight ones (EMA: no stop best, 10 ticks worst; ORB: range-opposite stop best; ZAB: wider ATR stops better). Stopped-out trades recovered *less* often than random entries, so stops were not "too tight" | EXPLORATORY | audit "Stop hunt" |
| K5.6 | Filters that helped in-sample: ZAB relative volume ≥ 2.0 (56.5% profitable vs 5.8% unfiltered); Crabel NR7 (53.6% vs 17.9%); ACD pivot alignment (57.8% vs 16.1%) | EXPLORATORY | ZAB, Crabel, ACD reports |

## K6. Edges and their decay

| ID | Fact | Grade | Source |
|---|---|---|---|
| K6.1 | ORB, ZAB and Crabel entries do not beat random entries (same minute, same side, same weeks) at any horizon from 5 minutes to session end | CONFIRMED (in-sample null) | audit "Idea vs execution" |
| K6.2 | ACD entries beat random by +$52/trade at 60 min in-sample (z 4.68), then did **$27/trade worse** than random on 2022+ (p 0.85); the full strategy lost $58/trade on 2022+ | REFUTED | `data/backtests/acd/signal_holdout.md` |
| K6.3 | EMA x VWAP champion: +$24/trade in-sample, **−$33/trade** on 2022+ (PF 0.90, pass 16% vs fail 78%) | REFUTED | `data/backtests/ema_vwap/holdout.md` |
| K6.4 | Champions earned mostly early: ORB 2010-13 +$17,786 vs 2014-21 −$3,294; ZAB 2010-15 +$12,657 vs 2016-21 +$2,076; Crabel's entry edge exists only in 2010-15 (z 3.2-3.5). Edges decay after ~2015 | EXPLORATORY (consistent pattern) | prior-work; audit |
| K6.5 | A tuned 2.5-month backtest says nothing: VWAP Break claimed +$40,878 (PF 1.81) on its own window, lost $40/trade over 16 years, every year negative | CONFIRMED | `data/backtests/vwap_break/report.md` |
| K6.6 | Walk-forward (pick each year from earlier years only) never found a qualifying config for any of strategies 1-8 | CONFIRMED | all reports |
| K6.7 | **Ceiling (S003)**: ridge / elastic net / boosted trees on ~25 causal OHLCV, range, VWAP, term-structure and calendar features at 8 decision times x 6 horizons: 0 of 432 strategies significant after costs (Romano-Wolf min p 0.96; SPA p 0.87); null controls clean | CONFIRMED (discovery OOS 2012-16, R011) | S003 report |
| K6.8 | Power of 5 out-of-sample years: a planted 8-net-tick edge is found 90% of the time (74-97%), 4 ticks 15%, 1-2 ticks never. Absence of evidence here rules out ~8+ tick edges only; the Combine bar on short windows is 4-8 ticks | CONFIRMED (R011: 10 of 10 at 8 ticks) | S003 report |
| K6.9 | Long holds cannot be bounded: simultaneous 95% upper bounds of gross edge per trade reach 11-20 ticks for holds to 16:05 from 03:00 / 08:00 / 09:00 / 20:00; tight bounds only on short quiet windows (e.g. 10:35 +5, 14:00 +15 below the stress cost for every model) | CONFIRMED (R011) | S003 report |

## K7. Outside evidence (literature priors, not tested here yet)

| ID | Claim | Grade | Source |
|---|---|---|---|
| K7.1 | Intraday momentum: the rest-of-day return predicts the last 30 minutes in 60+ futures incl. commodities (1974-2020); Sharpe 0.87-1.73 per asset class; reverses over following days | EXPLORATORY (external) | Baltussen et al. 2021 (literature/REFERENCES.md) |
| K7.2 | Crude oil (USO, 2006-2018): first half-hour return predicts the last half-hour; on EIA days the 10:30-11:00 half-hour does instead; the overnight part drives the first half-hour's power | EXPLORATORY (external) | Wen et al.; Wen, Indriawan, Lien, Xu 2023 |
| K7.3 | WTI reacts to EIA inventory surprises within moments; effects last ~25 minutes, then prices retrace quickly | EXPLORATORY (external) | Li & Geman 2018 |
| K7.4 | Gao et al. 2018 did not find intraday momentum in commodity futures in their setup (unclear open/close) | EXPLORATORY (external) | Gao, Han, Li, Zhou 2018 |
