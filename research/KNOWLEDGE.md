---
id: KNOWLEDGE
title: What we know about CL
status: living
updated: 2026-10-16
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
| K3.6 | Rough feasibility: every workable Combine setup needs an after-cost annual Sharpe of ~2-3+; with 1 CL, G8 passes only at low daily volatility on 100K/150K | EXPLORATORY (Gaussian model) | REQUIREMENTS §7; to be replaced by S001 |

## K4. Time of day and sessions

| ID | Fact | Grade | Source |
|---|---|---|---|
| K4.1 | Anchors that helped breakout-type rules: 09:00 ET (NYMEX open) and London 08:00 beat 08:30 ET; the 18:00 ET Globex open was worst in every view (ORB 0.0% profitable, median −$39) | EXPLORATORY | ORB/ZAB/Crabel/ACD reports |
| K4.2 | EMA x VWAP: New York held the best single config but the worst median (−$35.9); at zero cost Asian and London beat New York | EXPLORATORY | ema_vwap report |
| K4.3 | Momentum Pullback: only the New York session produced any profitable configs | EXPLORATORY | momentum report |

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

## K7. Outside evidence (literature priors, not tested here yet)

| ID | Claim | Grade | Source |
|---|---|---|---|
| K7.1 | Intraday momentum: the rest-of-day return predicts the last 30 minutes in 60+ futures incl. commodities (1974-2020); Sharpe 0.87-1.73 per asset class; reverses over following days | EXPLORATORY (external) | Baltussen et al. 2021 (literature/REFERENCES.md) |
| K7.2 | Crude oil (USO, 2006-2018): first half-hour return predicts the last half-hour; on EIA days the 10:30-11:00 half-hour does instead; the overnight part drives the first half-hour's power | EXPLORATORY (external) | Wen et al.; Wen, Indriawan, Lien, Xu 2023 |
| K7.3 | WTI reacts to EIA inventory surprises within moments; effects last ~25 minutes, then prices retrace quickly | EXPLORATORY (external) | Li & Geman 2018 |
| K7.4 | Gao et al. 2018 did not find intraday momentum in commodity futures in their setup (unclear open/close) | EXPLORATORY (external) | Gao, Han, Li, Zhou 2018 |
