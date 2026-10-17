---
id: BACKLOG
title: Hypothesis backlog
status: living
updated: 2026-10-17
---

# Hypothesis backlog

Ranked queue of falsifiable ideas. Each moves `idea → spec → explored → preregistered → validated /
rejected` (PROTOCOL §3). A card is created (`H###-slug/card.md` from `_template.md`) when an idea moves to
`spec`. Ranking is re-done after S002 (atlas) and S003 (ceiling): the ceiling tells us which decision
times and horizons hold any predictability at all.

Prior: **A** = direct literature support on crude oil or futures intraday; **B** = plausible mechanism,
indirect support; **C** = weak prior or cost-heavy. Source: who proposed it (Claude, Codex, both) and
the paper. Every first test uses discovery data only and CL costs (base $24.02, stress $44.02 per round
trip).

**S001 bar (2026-10-16, validated R005):** an idea is worth a pre-registration only if its discovery
estimate, after base costs and before any haircut, is about **IC >= 0.2 per trade / annual Sharpe >= 2 at
1 CL** on its own window. Ideas on short quiet windows (14:00-14:30, 14:35-16:05, 10:35-11:30) start
cheapest (4-8 net ticks per trade); full-session holds (09:00-16:05) need 32+ ticks and drop in priority.

| ID | Hypothesis | Mechanism (why someone loses money to us) | Source | Prior | First test (discovery) | Status |
|---|---|---|---|---|---|---|
| H001 | Return from the prior settlement (14:30 ET) to 14:00 ET predicts 14:00-14:30 and 14:00-16:05 | Dealers short gamma and late-informed traders push in the direction of the day into the close | Baltussen et al. 2021; Gao et al. 2018; both | A | sign-trade at 14:00, day-clustered mean net P&L per horizon; N4 sign-flip null | idea |
| H002 | On EIA days the 10:30-11:00 return predicts the last half-hour; on other days the first half-hour and its overnight part do | Informed traders and thinner liquidity around the release slow price discovery | Wen, Indriawan, Lien, Xu 2023; Claude | A | split days EIA / non-EIA; predictive regression + sign-trade, same horizons as H001 | idea |
| H003 | After the EIA release, the 10:30-10:35 move continues (or fast-reverses) to 11:30 when volume is in the top decile | Information shock vs overreaction; volume separates them | Ederington & Lee 1993; Li & Geman 2018; both | A | Wednesdays 10:35 entry in / against the first move, exit 11:30; matched non-EIA Wednesdays as control | idea |
| H004 | Momentum conditioned on term structure: CL1-CL2 slope x 5/20-day return at 09:00, hold to 16:05 | Backwardation signals scarcity and risk premium; trends persist more in that state | Gorton, Hayashi, Rouwenhorst 2013; Codex | A | interaction coefficient + sign-trade at 09:00 → 16:05; roll-safe returns only | idea |
| H005 | Overnight handoff: the 18:00-09:00 return, split by volume and term structure, predicts 09:00-12:00 | Information-driven overnight moves continue, liquidity-driven ones reverse | Wen 2023; both | B | 09:00 entry, exit 12:00; interaction test | idea |
| H006 | Settlement-to-close reversal: fade an abnormal 14:25-14:35 move at 14:35, exit 16:05 | Benchmark (settlement / TAS) pressure unwinds after the window | Codex | B | matched same-volatility days as control | idea |
| H007 | Volatility decides continuation vs reversal: 30-minute return x realised-vol percentile at 09:30, hold 60 minutes | High-volatility shocks carry information; ordinary moves are noise that reverts | Gao 2018; both | B | pre-declared interaction, one sign rule | idea |
| H008 | Volume-shock continuation: extreme signed return plus extreme same-minute relative volume at hourly marks 09:00-14:00, hold 60 minutes | Unusual volume marks informed pressure | both | B | event study vs matched random entries (N2) | idea |
| H009 | Reversal of the end-of-US-day order imbalance during Asia / London | Dealers lay off inventory overnight (equity "overnight drift" analogue) | Boyarchenko, Larsen, Whelan (NY Fed); Claude | B | 13:30-14:30 move → fade 20:00-03:00 ET; roll days excluded | idea |
| H010 | "Noise area" intraday momentum: break out of the time-of-day noise band from the session open, volatility-sized | Abnormal demand/supply imbalance persists within the day | Zarattini, Aziz, Barbon 2024 (SPY Sharpe 1.33, untested on futures); Claude | B | the published rule, unchanged, on CL; no tuning | idea |
| H011 | Multi-day trend sign (1/5/20-day) at 09:00, hold to 16:05 | Time-series momentum in futures | Moskowitz, Ooi, Pedersen 2012; both | B | sign-trade per lookback; Romano-Wolf over 3 lookbacks | idea |
| H012 | Stable drift in specific half-hours of the day | Recurring flows (hedging, fixing, session hand-offs) | S002 atlas; Claude | C | only half-hours flagged by S002 with q < 0.10 and stable signs | idea |
| H013 | Calendar x regime cells at pre-selected times (08:00, 09:00, 10:35, 14:35) by weekday x backwardation | Weekly hedging and inventory cycles | Codex | C | max-t over 20 pre-declared cells | idea |
| H014 | The same half-hour's return on previous days predicts today's | Repetitive institutional order flow (intraday periodicity) | Heston, Korajczyk, Sadka 2010; Claude | C | lag-1..20-day same-slot regression per half-hour | idea |
| H015 | Front-second spread dislocation: fade a 20-day same-minute spread z-score extreme, hold 60 minutes | Temporary relative pressure between contracts mean-reverts | Codex | C | needs 2 CL legs (double cost); test spread P&L net of 2x costs | idea |
| H016 | Roll-window pressure reversal (within-contract spread changes only) | Index-fund roll flows distort the curve temporarily | Mou 2011; both | C | roll days vs matched non-roll days; drop the 00:00 splice | idea |
| H017 | Pre-settlement prompt pressure: at 14:00, if the 13:30-13:59 CL0-CL1 spread change agrees with the front's return and front volume share is high, trade the spread's direction 14:01-14:30 | Settlement / TAS hedgers push the prompt month first, then the outright | Codex R006 C1; Mou 2011 (indirect) | B | one fixed rule, non-roll days, vs matched 14:01 entries | idea |
| H018 | Pre-EIA positioning drift: on EIA days trade the 09:30-09:59 direction 10:01-10:25, flat before 10:30 | Informed / hedger positioning ahead of the inventory number | Codex R006 C2; Kurov et al. (other releases) | B | sign rule on EIA days vs matched non-EIA weekdays | idea |
| H019 | Prompt-contract EIA overreaction: fade the 10:30-10:34 CL0-CL1 spread change, hold CL0 10:36-11:30 | Headline traders over-express the shock in the prompt month | Codex R006 C3; Li & Geman 2018 | B | sign rule vs plain fade of CL0 (H003); judge on stress costs | idea |
| H020 | NY-open sweep reversal: at 09:05, if CL0 and CL1 08:55-09:04 returns disagree, trade CL0 in CL1's direction 09:06-09:30 | Stops sweep the prompt month; spread arbitrage pulls it back | Codex R006 C4 | C | disagreement rule vs plain opening fade | idea |
| H021 | Asia/London disagreement: at 07:55, if 20:00-03:00 and 03:00-07:54 disagree, trade London's direction 07:56-08:25 | European physical flow corrects thin Asian moves | Codex R006 C5; Boyarchenko et al. (indirect) | B/C | conditional sign rule vs unconditional London momentum | idea |
| H022 | Next-day EIA correction: fade the release-day 10:30-11:00 return the next day 10:35-11:30 | Noisy inventory headline corrected after overnight analysis | Codex R006 C6 | C | one trade per release vs non-EIA Wednesdays | idea |
| H023 | Whole-dollar pin: at 14:00 within 1-10 ticks of a whole dollar, trade toward it 14:01-14:30 | Long-gamma dealer hedging pins strikes into settlement | Codex R006 C7 (no option data) | C | exact rule vs the 11-20 tick band | idea |
| H024 | Globex reopen gap fade: fade 16:05 -> 18:04 gap at 18:05, exit 20:00 | Thin reopen book overshoots | Codex R006 C8; adverse prior (K4.1) | C | one daily sign trade, 2-tick costs | idea |
| H025 | Settlement continuation, conditioned: at 14:35 trade the 14:25-14:35 direction to 16:05 when the move / settlement volume is large | Settlement-benchmarked flow keeps arriving after the window (TAS / index hedges) | S002 (Claude) | C+ | naive base measured (IC 0.12, decaying); conditioning variables fixed before looking | **parked** ([card](H025-settlement-continuation/card.md)): best variant 5.85 gross ticks, decays to 1.6; power fails |
| H026 | Post-settlement drift: 14:30-15:00 is negative on average (-2.2 ticks, every year) | Settlement-window buying unwinds | S002 (Claude) | C | component / filter only (below cost alone) | **parked** ([card](H026-post-settlement-drift/card.md)): 2.25 gross ticks, below cost |
| H027 | TAS / aggressive-flow settlement signal: at 14:34, signed TAS volume and signed aggressive outright volume over 14:25-14:34 (trade only when the imbalance is above its trailing 60-day 75th percentile) predict 14:35-16:05 | Benchmark-bound participants must trade at settlement; dealers who sell TAS hedge in the 14:28-14:30 window and may carry inventory after it. Sign (continuation vs reversal) fixed in the card before looking | Codex R012 E1; Claude (TAS hedging); Ge, Kang, Tang, Yang 2023 (TAS pressure) | B- | buy 2015-16 CLT trades + CL trades 14:20-14:35 (D010); one family of <= 4 variants | idea (needs data) |
| H028 | Cross-energy settlement lead: at 14:34 the vol-scaled RB / HO (/ Brent) return minus CL's over 14:25-14:34 predicts CL 14:35-16:05 | Product markets carry refining information; CL's own settlement flow hides the common factor for a while | Codex R012 E2 | C+ | 1-min RB / HO / BZ bars 2015-16 (D010); RB / HO settle in the same window (contamination risk) | idea (needs data) |
| H029 | EIA consensus surprise: fade / follow actual minus consensus at 10:36-11:30 | Slow participants adjust after the inventory surprise | Codex R012 E3 | C | needs a point-in-time consensus archive | **parked**: MDE 10.3 net ticks on ~250 validation trades (R012) and no auditable consensus data |
| H030 | Option open-interest pin on CL option expiry days, 14:35-16:05 toward the largest nearby-OI strike | Dealers hedging near-expiry gamma pull the price to strikes | Codex R012 E4 | C | needs option OI history; dealer sign unobserved | idea (needs data) |
| H031 | Brent -> CL European handoff: vol-scaled Brent minus CL 03:00-07:54 predicts CL 07:56-08:25 | Brent absorbs European physical news first | Codex R012 E5 | C | Brent 1-min bars (ICE dataset coverage unverified; NYMEX BZ thin) | idea (needs data) |
| H032 | Index roll pressure: short CL 14:35-16:05 on public commodity-index roll days | Index funds sell the front at settlement on roll days | Codex R012 E6 | C- | rebuild the roll calendar from published rules; an index roll is a spread trade and S002 roll weeks showed nothing | idea |

## Ranking after S002 (2026-10-17; discovery evidence, validated by R009)
Measured in [S002](../studies/S002-atlas/report.md). "Base" = what the atlas saw for the naive version;
bar = S001 (IC ~0.2, ~4-8 net ticks on short windows).

| Rank | Idea | Atlas evidence | Verdict |
|---|---|---|---|
| 1 | **H025** (new, S002): settlement continuation, conditioned (size of the 14:25-14:35 move, settlement volume), trade 14:35-16:05 | naive IC 0.12, gross 2.6 ticks, q 5e-5; **decaying** 4.4 / 2.6 / 0.4 by block | the only measured base; must gain 2-3x and hold in 2015-16. Low-moderate prior |
| 2 | H012 / H026 (new): post-settlement drift, short 14:30-15:00 (or as a filter on H025) | -2.2 ticks, t -5.9, every year, all blocks | stable but below cost alone (gross Sharpe ~2.3, net ~0); keep as a component |
| 3 | H001: 09:00-14:00 -> 14:00-14:30 | edge 0.95 ticks, q 0.73 | weak; test only if cheap |
| 3 | H005 / H004: overnight -> NY, by term structure | 4.6 ticks (IC 0.04); contango 6.4 ticks, q 0.19 | weak, mixed blocks |
| 4 | H006 (fade after settlement) | the atlas shows *continuation*, not reversal | **reversed**: superseded by H025 |
| 4 | H017, H019, H020 (CL0 / CL1 spread signals) | spread change predicts nothing at 09:00, 14:00, EIA (all q > 0.6) | demoted to C- |
| 4 | H003, H018, H022 (EIA direction) | EIA moves 5.5x bigger but direction-free after 5 min | demoted |
| 4 | H009, short-horizon fades | VR < 1 is bid-ask bounce | demoted |
| - | H007, H008, H010, H011, H013-H016, H021, H023, H024 | not measured by the atlas | unchanged; S003 (ceiling) decides which decision times are worth them |

## After S003 (2026-10-17)
The ceiling found nothing in OHLCV-derived features at 8 decision times and can only rule out ~8+ net
tick edges (K6.7-K6.9). Consequences for every card:
- an idea built only from OHLCV / range / VWAP / term-structure / calendar features at these times starts
  with a **low prior** (the ceiling already searched that space for 8+ tick edges);
- a 4-8 tick idea needs validation power planning: with ~250 trades/year, 2017-2021 adds ~1,250 trades;
  write the minimum detectable edge into each pre-registration;
- ideas with information outside the ceiling's features (settlement-flow structure H025 / H026, event
  content, other markets, order flow) are the ones worth a card.

## After R012 (2026-10-17): direction D008
Owner chose the staged settlement-flow data track ([D008](../decisions/D008-direction-after-s003.md)).
Promotion arithmetic for every card (PROTOCOL §4.5): validation 2017-2021 (~1,250 days) detects an
annual Sharpe of ~1.42 on the daily P&L series; promotion needs MDE <= half the discovery effect, so the
discovery estimate must reach a **net annual Sharpe of ~2.85**. Per trade: MDE_net ~ 3.168 x sd /
sqrt(5 x trades per year); e.g. 14:35-16:05 (sd 22 ticks) at 60 trades a year needs a discovery net
edge of ~8 ticks.

| Rank | Idea | Why here | Next |
|---|---|---|---|
| 1 | H027 TAS / signed flow | new information at the settlement window | quotes, then 2015-16 data (D010) |
| 2 | H028 cross-energy | cheap 1-min bars; settlement window | quotes with H027 |
| - | H025 / H026 | existing data; Codex's 4 frozen variants | **done 2026-10-17: 0 / 4 promoted, both parked** |
| 4 | H030, H031, H032 | data unverified or weak mechanism | ideas |
| - | H029 | parked on power | - |

## Parked / rejected
- H029 (2026-10-17): parked on power (R012) and data availability; no card.
- H025 (2026-10-17): parked after the discovery run (power fails; decays to 1.6 gross ticks in 2015-16).
- H026 (2026-10-17): parked after the discovery run (2.25 gross ticks, below the base cost).

Strategies 1-8 are in `prior-work/STRATEGIES-1-8.md`; do not re-test them in another costume.

## Rules for adding ideas
- One line here first, with mechanism and source. No card until it is picked up.
- An idea without a mechanism goes to "Parked" with the note "no rationale".
- Codex is asked for blind ideas at the start of each phase (PROTOCOL §7); they are added with source "Codex".
