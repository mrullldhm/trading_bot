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

## Parked / rejected
None yet. Strategies 1-8 are in `prior-work/STRATEGIES-1-8.md`; do not re-test them in another costume.

## Rules for adding ideas
- One line here first, with mechanism and source. No card until it is picked up.
- An idea without a mechanism goes to "Parked" with the note "no rationale".
- Codex is asked for blind ideas at the start of each phase (PROTOCOL §7); they are added with source "Codex".
