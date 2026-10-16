---
id: PRIOR-WORK
title: Strategies 1-8 and the backtest audit (all failed)
status: done
updated: 2026-10-16
---

# Prior work: strategies 1-8

Everything tested before this programme, distilled. Full reports are local (not in git) under
`data/backtests/<name>/report.md`; the public summary is the repo README, "Strategy results".

Common setup: 1 CL, $4.02 fee + 1 tick slippage per side ($24.02 per round trip), ambiguous minutes
resolved against us, targets need a 1-tick trade-through, EIA releases blocked ±15 min, exit at 16:09 ET,
Combine = Topstep 50K (target $3,000, trailing end-of-day MLL $2,000, 55% consistency), up to 250 days,
2,000 bootstrap attempts. Development data 2010-06 .. 2021-12; holdout 2022+.

## Results

| # | Strategy (hypothesis) | Configs | Champion (dev) | Trades | $/trade | PF | +1 tick | Pass / fail % | p95 60d DD | Verdict |
|---|---|---|---|---|---|---|---|---|---|---|
| 1 | EMA x VWAP: close through VWAP enters, close back through EMA exits | 6,144 | 60m / EMA21 / weekly VWAP / close-cross / no stop / New York | 1,345 | 24.17 | 1.12 | 4.17 | 29.5 / 70.4 | $3,090 | FAIL; holdout −$33/trade |
| 2 | ORB: opening-range breakout continues | 1,056,000 | 09:00 ET / 60m range / 5m close entry / long | 739 | 19.61 | 1.08 | 3.60 | 29.0 / 71.0 | $2,672 | FAIL, no edge after costs |
| 3 | ZAB-inspired: first candle sets the side, relative-volume filter | 3,456 | 09:00 / 5m candle / breakout / 10R / long | 569 | 25.89 | 1.11 | 6.31 | 26.2 / 71.5 | $2,350 | FAIL, no edge after costs |
| 4 | Crabel: stops at range ± stretch, NR4/NR7/inside-day setups | 7,200 | London 08:00 / 1m range / inside day | 381 | 85.43 | 1.33 | 65.43 | 36.1 / 58.6 | $2,322 | FAIL, depends on drawdown gate; PBO 52.9% |
| 5 | Fisher ACD: A level held, C reversal, pivot bias | 2,880 | 09:00 / 30m range / pivot-aligned / flat +240 | 1,156 | 44.83 | 1.23 | 24.83 | 37.6 / 62.3 | $2,858 | FAIL; signal holdout: edge not confirmed |
| 6 | Third-party "CL VWAP Break" bot, published parameters | 1 + 16 neighbours | published | 25,913 (2010-26) | −40.18 | 0.64 | −58.92 | 1.8 / 98.2 | $2,697 | FAIL, no edge even at zero cost |
| 7 | Momentum Pullback candle pattern | 233,280 | 15m / 3x body / 4R / New York | 455 | −2.57 | 0.98 | −17.98 | 13.5 / 58.1 | $1,886 | FAIL, loses before costs |
| 8 | TradingView "1-Minute Momentum" Pine script | 81,000 | 15m / 3x / body < 40% / 4R / short | 473 | −6.18 | 0.96 | −24.55 | 12.2 / 60.1 | $1,968 | FAIL, loses before costs |

Total: **1,389,960 configurations** on 2010-2021 (+17 for strategy 6), ≥ 1.2M unique trade streams,
≥ 273 effective independent trials; ~6.8M evaluations counting audit re-runs. No configuration passed
every gate; no walk-forward year ever produced a qualifying pick.

## The audit (2026-10-15/16): were the failures real?

Yes. Bugs and rule mismatches found were fixed (flat 16:00 → 16:09 ET; Combine horizon 60 → 250 days;
walk-forward minimum; one look-ahead day), and all searches were re-run. Checks passed: no look-ahead,
exact accounting, correct time zones, data matching official WTI spot, Topstep fees and rules, and a
planted edge was found by the pipeline. Verdicts:

| # | Verdict | Why |
|---|---|---|
| 1 EMA x VWAP | FAIL depends on assumptions | robust only with zero costs + optimistic fills + no EIA block + no drawdown gate together |
| 2 ORB | No edge after costs | entry signal no better than random either |
| 3 ZAB | No edge after costs | entry signal no better than random either |
| 4 Crabel | FAIL depends on the drawdown gate | a robust pick exists only with the gate at $2,000; its entry edge only in 2010-15 |
| 5 Fisher ACD | No edge after costs out of sample | in-sample drift was selection luck (2022+ test) |

## Lessons carried into this programme

1. **Drawdown is the wall, not direction.** 1 CL noise alone puts the 60-day p95 drop at $2,300-3,100.
2. **Costs decide.** One extra tick per side kills most edges; edges must be large relative to $24-44.
3. **Selection luck is real.** The best of thousands of in-sample tries (ACD) was worse than random
   entries on new data. Hence: few pre-registered tests instead of grids.
4. **Edges decayed after ~2015.** Discovery must check the latest years separately.
5. **What looked better in-sample:** 09:00 ET and London 08:00 anchors, longer ranges/timeframes,
   close-confirmed entries, wide stops, holding to the session end. Treat as leads, not facts.
6. **Popular retail setups showed no edge on CL**, some not even before costs.
7. **Micro contracts do not fix thin edges** (fees); now out of scope (D004).

## Holdout status

See [HOLDOUTS.md](../HOLDOUTS.md). Opened: strategy 1 (2026-10-15) and ACD (signal test 2026-10-15).
Strategy 6 ran through 2026-07. Unopened but frozen: ORB, ZAB, Crabel, Momentum, Momentum2, EMA v2.
