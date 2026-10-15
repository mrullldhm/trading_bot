# How to Build a Trading Bot for Topstep (Crude Oil) — A Beginner's Guide

> **Who this is for:** someone with zero trading-bot experience who wants to build an automated bot for a Topstep account, trading Crude Oil futures, with help from two AI coding assistants: **Claude Code** and **Codex**.
>
> **Rules verified on:** 2026-10-13. Prop firm rules and fees change often. Every number marked **(verify)** must be checked again on the official Topstep help center before you rely on it.
>
> **Not financial advice.** Most trading strategies lose money. This guide teaches you how to build a bot safely and how to tell a good bot from a lucky one. It does not promise profit.

---

## Table of Contents

1. [Read This First](#1-read-this-first)
2. [How Topstep Works](#2-how-topstep-works)
3. [The Rules Your Bot Must Obey](#3-the-rules-your-bot-must-obey)
4. [Crude Oil Basics (CL)](#4-crude-oil-basics-cl)
5. [Glossary](#5-glossary)
6. [Choosing a Platform and Language](#6-choosing-a-platform-and-language)
7. [How a Trading Bot Is Built (Architecture)](#7-how-a-trading-bot-is-built-architecture)
8. [Step-by-Step Roadmap](#8-step-by-step-roadmap)
9. [Starter Strategy Ideas](#9-starter-strategy-ideas)
10. [Benchmarks: The Numbers to Aim For](#10-benchmarks-the-numbers-to-aim-for)
11. [Position Sizing for Prop Firm Rules](#11-position-sizing-for-prop-firm-rules)
12. [Working with Claude Code and Codex Together](#12-working-with-claude-code-and-codex-together)
13. [Common Beginner Mistakes](#13-common-beginner-mistakes)
14. [Checklists: Go-Live, Daily Operations, Emergencies](#14-checklists-go-live-daily-operations-emergencies)
15. [Resources](#15-resources)

---

## 1. Read This First

### What is a trading bot?

A trading bot is a program that follows fixed rules to buy and sell. It does three jobs, again and again:

1. **Watch** the price.
2. **Decide** if its rules say "enter" or "exit".
3. **Act** by sending orders to the broker.

Think of it like a **very disciplined employee** who follows your written instructions exactly. It never gets scared or greedy. But it is also never smarter than your instructions. If your rules are bad, the bot will lose money very consistently.

### Honest expectations

- **The bot is not the edge. The strategy is.** Code only automates an idea. If the idea does not make money after costs, no amount of code will fix it.
- **Your first goal is not to get rich.** Your first goal is to **pass the Topstep rules without breaking them**. Prop firms fail most people because of rule breaks (losing too much in one day, or too much overall), not because of a lack of profit.
- **Expect this to take months**, not days. A realistic timeline:

| Phase | Typical time |
|---|---|
| Learning + setup | 2–4 weeks |
| Writing and backtesting a strategy | 4–8 weeks |
| Robustness testing | 2–4 weeks |
| Practice (simulated) account | 4+ weeks |
| Trading Combine | 2+ weeks |

### Why the risk manager matters more than the strategy

A prop account is like a **driving test with an instructor who fails you instantly** if you cross a line. A great driver who crosses the line once still fails. Your bot's most important part is the code that **stops it from crossing Topstep's lines**, not the code that finds trades.

---

## 2. How Topstep Works

Topstep first gives you a simulated Trading Combine. If you pass, you normally move to a simulated Express Funded Account that can earn real payouts. Topstep may later call you up to a Live Funded Account that uses real capital.

```
 Practice Account  ──►  Trading Combine  ──►  Express Funded Account (XFA)  ──►  Live Funded Account
 (free practice,        (the "exam":          (simulated, but you can           (real money
  test your bot)         hit profit target     get paid out)                     with Topstep)
                         without breaking
                         rules)
```

- **Practice Account:** a simulated account for testing. Topstep has **no separate API sandbox**, so this is where you test your bot.
- **Trading Combine:** the evaluation. Reach the profit target without hitting the loss limits.
- **Express Funded Account (XFA):** you have passed. Still simulated, but profits can be withdrawn under payout rules.
- **Live Funded Account:** real capital. **Important:** as of the verified date, the TopstepX API is reported to work for simulated accounts (Combine, XFA) but **not Live Funded Accounts** (verify). Ask Topstep support in writing how automation works after a call-up to Live before you depend on it.

---

## 3. The Rules Your Bot Must Obey

**Golden rule:** Topstep's platform is the final authority. Your bot should use **stricter internal limits** than Topstep, so it stops itself before Topstep stops it.

Numbers below are for the standard Trading Combine. **(verify all)**

| Rule | 50K | 100K | 150K | What it means | What your bot should do |
|---|---|---|---|---|---|
| **Maximum Loss Limit (MLL)** | $2,000 | $3,000 | $4,500 | The fail line starts this far below your highest end-of-day balance and trails it upward. It never moves down and stops trailing once it reaches the starting balance. **Open (unrealized) losses** count during the day. | Treat this as your real "account size". Keep a safety buffer. |
| **Profit Target** | $3,000 | $6,000 | $9,000 | Reach this to pass the Combine. | Stop trading once target + consistency rule are safely met. |
| **Consistency Target** | Best day ≤ 55% of total profit | same | same | One huge day cannot make up most of your profit. Going over raises the profit you need to pass instead of failing you (verify). | Lock the bot for the day once daily profit reaches ~45% of the original profit target. |
| **Daily Loss Limit (DLL)** | $1,000 | $2,000 | $3,000 | Optional in Combine/XFA, mandatory in Live (Live: $2,000 / $3,000 / $4,500) (verify). | Use your own daily stop of about 2 losing trades (see Section 11). |
| **Max position size** | 5 contracts overall; CL currently 3 | 10 overall; CL 6 | 15 overall; CL 9 | Energy products like CL may have **lower** product limits than the overall ceiling (verify). XFA Scaling Plan may be lower still. | Before every session, read the limit shown in TopstepX. Use the smallest current limit and block entries if it cannot be confirmed. Never hard-code the scaling table. |
| **Trading hours** | 5:00 PM CT – 3:10 PM CT next day | same | same | Must be flat (no positions) by 3:10 PM CT. Holidays or product schedules may close earlier. No overnight or weekend holds. | Use the `America/Chicago` time zone, not a fixed UTC offset (daylight saving changes). Load that day's official close, reset daily counters at 5:00 PM CT, and finish cancelling + flattening several minutes before the earliest close (normal day: stop entries 3:00 PM CT, flat by 3:05 PM CT). If the calendar is unavailable, do not trade. |

### How the trailing Maximum Loss Limit works (most misunderstood rule)

Example with a 50K account ($2,000 MLL):

| Day | End-of-day balance | Highest EOD balance so far | Fail line |
|---|---|---|---|
| Start | $50,000 | $50,000 | $48,000 |
| Day 1 | $50,800 | $50,800 | $48,800 |
| Day 2 | $50,300 | $50,800 | $48,800 (does **not** move down) |
| Day 3 | $51,500 | $51,500 | $49,500 |

The fail line **follows your best end-of-day balance up, never down**. Before it locks at the starting balance ($50,000), each new end-of-day high moves it up. After it locks, later profits do not move it higher. During the day, if your balance including open trades touches the fail line, you are out immediately.

**Why this matters:** your real risk money is $2,000, not $50,000. Every profit you bank also moves the line closer behind you.

### Automation rules (verify)

- **Bots are allowed** through the TopstepX API, but all trading rules still apply. Bot errors get no exceptions.
- **Run the bot on your own personal computer.** VPS (rented cloud servers), VPNs, and remote servers are prohibited.
- **No high-frequency trading (HFT)**, no rapid-fire trades, no exploiting unrealistic simulated fills, no hedging across accounts.
- **Do not deliberately take maximum size into major news.**
- **API access costs an extra monthly fee.**
- **No API sandbox.** Test in the Practice Account.
- **Topstep does not give coding support** for the API.

---

## 4. Crude Oil Basics (CL)

This guide trades **CL only** (standard WTI Crude Oil futures on NYMEX).

### The contract

| | CL (standard WTI Crude Oil) |
|---|---|
| Size | 1,000 barrels |
| Tick size (smallest price move) | $0.01 |
| Value of one tick | **$10** |
| 10-tick stop costs | $100 (+ slippage + fees) |
| 20-tick stop costs | $200 (+ slippage + fees) |
| Round-turn fee on TopstepX | ~$4.02 (verify) |
| Settlement | Physical delivery (Topstep makes you flat long before this matters) |

### The big risk of trading CL on a small account

**You cannot trade less than 1 contract.** On CL, 1 contract is already a big bet compared to Topstep's loss limit:

| Stop size | Real loss per trade (stop + ~$20 slippage + $4 fee) | Losses to hit $2,000 MLL (50K) | Losses to hit $4,500 MLL (150K) |
|---|---|---|---|
| 10 ticks | ~$124 | ~16 | ~36 |
| 15 ticks | ~$174 | ~11 | ~25 |
| 20 ticks | ~$224 | ~8 | ~20 |

Losing streaks of 8–10 trades happen to most strategies at some point. That means on a **50K account, CL forces you to use tight stops (about 10–15 ticks) and always 1 contract**. If your strategy needs wider stops, choose the **100K or 150K Combine** so the loss limit gives you enough room. Section 11 shows how to decide.

**Good news:** the Practice Account is simulated, so learning on CL there costs you nothing. The risk only becomes real in the Combine.

### Why crude oil is tricky

- **It moves fast.** Price can jump several ticks between when your bot sees a price and when the order fills. A stop loss is a trigger, **not a guaranteed price**.
- **EIA inventory report:** normally **Wednesday 10:30 AM ET**. Price can spike violently. Holidays can change both the **day and the time** (for example Thursday at noon).
  - Bot rule: load the actual release time from the official EIA schedule. **Block new entries from 15 minutes before until at least 15 minutes after** the release. If the calendar is missing or out of date, do not trade.
- **Other news:** OPEC/OPEC+ meetings, wars and sanctions, refinery problems, hurricanes, API inventory (Tuesday afternoon). Many are surprise events, so small size and hard stops matter more than a calendar.
- **Contract rollover:** each futures contract expires monthly. Choose the active month with a written, tested rule (for example: switch when the next contract has more volume for several days in a row), **and** enforce a hard cutoff a few days before CME's last trading date. Never open a position in a contract at or past your cutoff.
- **Liquidity changes by time of day.** CL trades almost 24 hours, but it is busiest during US hours. A good first trading window: **about 8:00 AM – 1:30 PM ET**, excluding news windows.

---

## 5. Glossary

| Term | Simple meaning |
|---|---|
| **Futures contract** | An agreement to buy/sell something later at today's price. You trade price changes, not barrels. |
| **Tick** | The smallest price step. For CL it is $0.01, worth $10 per contract. |
| **Long / Short** | Long = buy, profit if price rises. Short = sell, profit if price falls. |
| **Market order** | Buy/sell now at any price. Fast, but may fill worse. |
| **Limit order** | Buy/sell only at your price or better. May never fill. |
| **Stop order / Stop loss** | An order that triggers when price hits a level, used to cap a loss. |
| **Slippage** | The difference between the price you expected and the price you got. |
| **Commission / Fees** | What you pay per trade. "Round turn" = entry + exit. |
| **R** | Your risk on one trade. If your stop loss is $20, then 1R = $20. A $40 win = +2R. |
| **Backtest** | Running your strategy on past data to see how it would have done. |
| **In-sample / Out-of-sample** | Data used to build the strategy / data kept hidden to test it honestly. |
| **Overfitting** | Tuning rules so they fit past data perfectly but fail on new data. Like memorising exam answers instead of learning the subject. |
| **Look-ahead bias** | A backtest bug where the strategy "sees" future data it could not know at the time. |
| **Drawdown** | The drop from a peak balance to a later low. |
| **Walk-forward test** | Repeatedly building on one period and testing on the next, like a rolling exam. |
| **Monte Carlo** | Shuffling your trade results thousands of times to see the range of possible outcomes, including bad luck. |
| **Kill switch** | Code (and a button) that closes everything and stops the bot immediately. |
| **API** | The connection your code uses to talk to the broker (get prices, send orders). |
| **REST / WebSocket** | Two ways an API talks. REST = you ask, it answers. WebSocket = a live stream of updates. |
| **Reconcile** | Checking your bot's idea of its position against the broker's real position. |

---

## 6. Choosing a Platform and Language

| Option | Language | Good | Bad | Verdict |
|---|---|---|---|---|
| **Python + TopstepX / ProjectX API** | Python | Easiest language for beginners. Best tools for data and testing. Easiest for Claude and Codex to write and review. Official API for prices, account, orders. | Extra API fee. No sandbox. Must run on your own PC. Reported to not support Live Funded accounts yet (verify). You build your own backtester. | **Recommended** |
| NinjaTrader (NinjaScript) | C# | Mature built-in backtester. | Harder language. Topstep says TopstepX is the only platform for new accounts (verify). | Only if your account still supports it |
| Tradovate API | Any | Was used with older Topstep setups. | Unclear support for new Topstep accounts. | Avoid for new projects |
| TradingView (Pine Script) + webhook | Pine | Fast to sketch ideas on a chart. | Cannot reliably track account state, trailing drawdown, partial fills, or emergency flatten. Needs an extra bridge that can fail. | **Prototyping only** |

**Recommendation:** build in **Python** against the **TopstepX/ProjectX API**. Use TradingView only to look at ideas visually.

**Why:** a prop-firm bot lives or dies by its risk control. Python gives you full control of account state, the kill switch, and logs, and it is the language both AI assistants handle best.

### Suggested tools

- **Python 3.12+**
- `pandas` (data tables), `numpy` (math)
- `pytest` (automatic tests)
- `httpx` or `requests` (REST calls), a WebSocket/SignalR client (live data; check the ProjectX docs for which one)
- `matplotlib` (charts of your results)
- **Git** (save versions of your code so you can undo mistakes)
- **VS Code** as your editor

---

## 7. How a Trading Bot Is Built (Architecture)

Think of the bot as a **small company with separate departments**. Each department does one job and can be tested alone.

```
            ┌───────────────┐
            │  Market Data  │  live prices from the API (WebSocket)
            └───────┬───────┘
                    ▼
            ┌───────────────┐
            │   Strategy    │  "Should I buy, sell, or wait?" (pure rules, no orders)
            └───────┬───────┘
                    ▼  signal
            ┌───────────────┐
            │  Risk Engine  │  "Is this allowed?" Topstep rules, daily stop,
            │ + Kill Switch │  size limits, news block, trading hours.  CAN SAY NO.
            └───────┬───────┘
                    ▼  approved order
            ┌───────────────┐
            │Order Executor │  sends entry + protective stop, handles fills/rejects
            └───────┬───────┘
                    ▼
            ┌───────────────┐
            │  Reconciler   │  compares bot's position with broker's real position
            └───────┬───────┘
                    ▼
            ┌───────────────┐
            │ Logger/Alerts │  records everything; messages you when something is wrong
            └───────────────┘
```

### Why separate departments?

- The **strategy never sends orders directly**. Every idea must pass the **risk engine**. This is like needing a manager's signature before spending money.
- You can test each part alone. If something breaks, you know where.

### Safety must-haves (non-negotiable)

1. **No unprotected position.** Every entry needs a protective stop placed **on the server** (at the broker), not only inside your code, so it still protects you if your PC crashes. Use a bracket/OCO order if the API supports it. After every full **or partial** fill, confirm a working stop covers the exact filled quantity. If the stop is rejected, missing, or the wrong size: cancel remaining entry orders and flatten immediately.
2. **Duplicate-order guard.** After a disconnect, the bot must not resend an order that already went through.
3. **Stale-data check.** If prices stop updating for a few seconds, block new entries.
4. **Reconnect reconciliation.** After any reconnect, ask the broker "what is my real position and open orders?" before doing anything.
5. **Unknown state = no new entries.** If the bot is not sure what it holds, it stops entering and asks the broker. If it still cannot find out, it flattens.
6. **Scheduled shutdown.** In this order: stop entries, cancel every working order, confirm the cancels, flatten all positions, then confirm zero positions **and** zero working orders. (Flattening before cancelling can let a leftover order reopen a position.) Finish before Topstep's cutoff or any earlier holiday close.
7. **Daily loss lock and daily profit lock.** Stop for the day once either is hit.
8. **Manual kill switch.** One command or button that closes all positions and stops the bot.
9. **Hard contract limit** in code, lower than Topstep's limit.
10. **Secrets in environment variables**, never written in code or pasted into AI chats.
11. **Platform-side backstop.** Before trading, set a conservative Personal Daily Loss Limit in TopstepX to **Liquidate and Block**, and lock the risk settings for the day. This catches you if the bot, PC, or internet fails. It is a backup, not a replacement for per-trade stops.
12. **Identity checks.** Only allow the configured account ID and the exact CL contract symbol. Show both at startup and block trading if either is different. (One API key can reach several accounts.)
13. **One bot instance only.** Use a lock file so two copies cannot trade the same account.
14. **API failure = no entries.** On expired login, rate limiting, rejected requests, or unclear order confirmations: stop new entries and reconcile before resuming.

### Suggested project folder layout

```
propfirm/
├── config/            settings (risk limits, trading hours) — no secrets
├── data/              downloaded historical prices
├── src/
│   ├── data_feed.py   live + historical prices
│   ├── strategy.py    entry/exit rules only
│   ├── risk.py        Topstep rules, limits, kill switch
│   ├── executor.py    sends and tracks orders
│   ├── reconciler.py  checks real position vs bot position
│   ├── backtest.py    replays history through strategy + risk
│   └── main.py        starts everything
├── tests/             automatic tests for every module
├── logs/              trade and error logs
└── .env               API keys (never commit, never share)
```

---

## 8. Step-by-Step Roadmap

Each phase has a **goal**, **tasks**, and a **"done when"** checklist. Do not skip ahead. Each phase protects you from a different kind of failure.

### Phase 0 — Learn and set up

**Goal:** understand the basics and have a working environment.

- [ ] Read this whole guide once.
- [ ] Open a Topstep account and explore the Practice Account manually.
- [ ] Place a few **manual** CL trades in Practice to feel how fast oil moves.
- [ ] Install Python, VS Code, Git. Set up Claude Code and Codex.
- [ ] Learn basic Python: variables, functions, lists, dictionaries, loops (ask Claude/Codex to teach you with small exercises).
- [ ] Read the ProjectX API docs. Get API access.

**Done when:** you can run a tiny Python script that logs in to the API and prints your Practice account balance.

### Phase 1 — Write the strategy in plain words

> **Strategy log:** Strategy 1, **EMA x VWAP**, was tested on 2026-10-15 across 6,144 settings and **failed** (best setting: +$24/trade on 2010–2021, then −$33/trade on unseen 2022–2026). Details and lessons: README → "Strategy results". Run a new strategy through the same two steps: `propfirm_backtest.search`, then `propfirm_backtest.holdout` once.

**Goal:** a strategy so clear that two different people (or AIs) would code it the same way.

- [ ] Write a one-page **strategy spec**: market, time window, entry rule, stop rule, target rule, exit rule, max trades per day, news blocks.
- [ ] Every rule must be exact. Not "buy when strong", but "buy when price closes above the 15-minute opening range high".

**Done when:** you hand the spec to Codex and Claude separately, and both describe the same trades on the same chart.

**Why:** vague rules hide overfitting and bugs. If you cannot write it down, you cannot test it.

### Phase 2 — Get data and handle rollover

**Goal:** clean historical price data you can trust.

- [ ] Get at least **2–3 years** of 1-minute CL data (see "Where to get the data" below).
- [ ] Handle contract rollover: either test each contract separately, or build a continuous series and never trade the artificial jump at the roll.
- [ ] Check for gaps, bad prices, and duplicate bars (see the checklist below).

**Done when:** a data-quality script reports zero unexplained gaps and you can plot any day correctly.

> **Ready-made downloader:** this project already has a Databento downloader. See [README_DATA.md](README_DATA.md).

#### Where to get the data (verified 2026-10-14 — prices change, verify)

**Why not just use the Topstep API?** Its `retrieveBars` endpoint gives at most **20,000 bars per request** (about 14 trading days of 1-minute bars), allows 50 calls per 30 seconds, and needs the paid API subscription. ProjectX does **not** say how far back its history goes, and a third-party library reports that expired contracts have no minute data. Use it for live trading and for **saving new bars every day from now on**. Do not rely on it for your 3-year history.

| Source | Cost | 1-minute CL history | Verdict |
|---|---|---|---|
| **Databento** | **Free $125 credit** for new accounts (expires after 6 months) | 16+ years, straight from CME | **Recommended — start here** |
| Massive (formerly Polygon) Futures Basic | Free | 2 years | Good free second source to cross-check |
| Yahoo Finance / `yfinance` (`CL=F`) | Free | Only ~8–60 days | Too short |
| TradingView chart export | Free / paid | About 1 year max | **Do not use** — its licence bans using its data for automated trading |
| NinjaTrader free Kinetick | Free | Daily bars only | No 1-minute data |
| Kaggle datasets | Free | Unknown | Unknown source and quality; exploration only |
| Interactive Brokers | Needs a funded account + data subscription | Expired contracts only kept 2 years | Awkward for a beginner |
| Barchart Premier | ~$29.95 for 1 month | ~10 years | Cheapest paid backup |
| Sierra Chart (Denali) | ~$36 for 1 month | Back to 2008 | Paid backup |
| Massive Developer | ~$79 for 1 month | 5 years | Paid backup, clean API |
| CME DataMine | Thousands of dollars | Official exchange data | Overkill for this project |

**Recommended path**

1. **Sign up for Databento.** Before downloading anything, ask its cost-estimate function (`metadata.get_cost`) what the request will cost. Request:
   - Schema: `ohlcv-1m` (1-minute open/high/low/close/volume bars)
   - Symbols: all individual `CL.FUT` contracts for your chosen 3 years
   - Plus the instrument definitions (contract expiry dates)
2. **Keep the contract symbol on every row.** Do not merge everything into one "continuous" series straight away. You need the real contract to handle rollover correctly.
3. **Build two datasets:**
   - **Unadjusted tradable series** with a written roll rule (for example: switch when the next contract has higher daily volume, decided only with information available at that time). Use this for fills, stops, and profit/loss.
   - **Optional back-adjusted series** for indicators only. **Never** use adjusted prices for simulated fills or profit/loss — they are not real prices.
4. **Cross-check** the most recent 2 years against Massive's free tier (`python -m propfirm_data.crosscheck`). ✅ Done: open/high/low/volume match ~99.6–99.99%; closes differ on ~1.8% of bars, and checking the individual trades showed **Databento is correct** (Massive mis-orders fills that happen in the same instant).
5. **If the free credit is not enough,** pay for 1 month of Barchart Premier or Massive Developer, download what you need, then cancel.
6. **From day one of live/practice trading,** save every bar the Topstep API sends you, so your own archive grows.

**Licence note:** most data is for personal use only. Do not share or resell the raw data files.

#### Data-quality checklist (automate this as a script)

- [ ] Timestamps are unique and always increasing. Store in UTC, and keep the CME trading date and Chicago time separately.
- [ ] Session times are correct: Sunday–Friday sessions, the daily 1-hour maintenance break, holidays, and daylight-saving changes.
- [ ] Every bar has `low ≤ open ≤ high` and `low ≤ close ≤ high`, volume ≥ 0, and prices on $0.01 steps.
- [ ] No duplicate bars.
- [ ] Minutes with no trades are kept separate from data that is actually missing. Never fill in missing bars with made-up prices.
- [ ] Daily volume and high/low match a second source on several normal, rollover, and news days.
- [ ] Every rollover date is listed, and price/volume jumps around each roll were inspected by eye.
- [ ] The roll decision uses no future information (no look-ahead).

### Phase 3 — Backtest with real costs

**Goal:** an honest estimate of how the strategy would have done.

- [ ] Code the strategy and risk engine so the **same code** runs in backtest and live.
- [ ] Include fees **and** slippage (see [Section 10](#cost-assumptions)).
- [ ] Simulate Topstep rules in the backtest: trailing MLL, daily stop, flatten time, consistency.
- [ ] Hold back the **most recent 20–30% of data**. Do not look at it yet.
- [ ] Handle **roll days** correctly (see below). The backtest must never count a roll jump as profit or loss.

**Done when:** results on the in-sample data meet the "Minimum" column of the benchmarks.

#### ⚠️ Roll days: the fake price jump

Your data series `CL.v.0` is not one contract. It is a **chain of monthly contracts glued together**. About 12 times a year it switches from the expiring contract to the next one. The two contracts trade at different prices, so the series **jumps** at the switch, even though the market did not move.

**Real example from our data:** on **18 May 2026**, `CL.v.0` switched from **CLM6** (June 2026) to **CLN6** (July 2026). The series jumped **−417 ticks** from the last CLM6 bar to the first CLN6 bar. On 1 CL contract that looks like a **−$4,170 loss**. No real position ever experienced it. It is a **fake jump made by gluing two different contracts together**: mostly the price difference between June oil and July oil, plus whatever the market did between those two bars.

Think of it like comparing the price of a June concert ticket with a July concert ticket. They are different products, so their price difference tells you nothing about how the market moved. (To see the real June–July gap, compare both contracts **at the same minute**. Our data has both: `CL.v.0` and `CL.v.1`.)

**Why it is dangerous:** a single fake −$4,170 jump is twice the whole $2,000 loss limit of a 50K account. If your backtest counts it, the results are garbage: fake blow-ups, or fake big wins if the jump goes your way.

**Rules your backtest must follow:**

1. **Know when rolls happen.** In our data, `CL.v.0` rolls happen mostly at **00:00 UTC** (6–7 PM Chicago, in the evening); the rest at a session reopen (22:00 or 23:00 UTC), plus one old exception at 01:15 UTC. **None during US daytime.** The choice uses the **previous day's volume**, so it is known in advance, with no peeking into the future.
2. **Daytime strategies are safe automatically.** If you only trade US hours (e.g. 8:00 AM–1:30 PM ET) and are flat by Topstep's 3:10 PM CT cutoff, a trade can never cross a roll.
   - If you ever trade the **evening** session (5 PM–midnight UTC), you must flatten before 00:00 UTC, or trade the next contract from the session start (its bars are in `CL.v.1` before the roll).
3. **Safety check:** entry and exit of every trade must have the **same `raw_symbol`**. Make the backtest **crash** if they don't. That means there is a bug.
4. **Indicators** (moving averages, VWAP, ATR) that look back across a roll are distorted by the jump. Either reset them on the roll day, or use a back-adjusted series **for indicators only**. Never use adjusted prices for fills or P&L.
5. **Detect a roll** (for analysis): the bar's `raw_symbol` is different from the previous bar's `raw_symbol`. Note: you only learn this **after** the new bar appears, so it is not a live exit signal. Use rule 1 instead.
6. **Add a test:** feed the backtest a fake roll with a huge jump and check that P&L is unchanged.

**Live bot:** a live bot trades one **specific contract** (e.g. `CLN6`), not `CL.v.0`. It needs its own roll rule: switch to the next contract on a fixed schedule, e.g. a few days before expiry or when the next contract's daily volume is higher, decided before the session opens.

### Phase 4 — Robustness testing

**Goal:** prove the results are not luck or overfitting.

- [ ] **Out-of-sample test:** run once on the held-back data. No changes allowed after.
- [ ] **Walk-forward test:** build on period A, test on period B, slide forward, repeat.
- [ ] **Parameter test:** change each setting a little (e.g. stop 10, 12, 14 ticks). Results should change gently, not collapse.
- [ ] **Cost stress test:** add 1 extra tick of slippage per side. Still profitable?
- [ ] **Monte Carlo:** 10,000 shuffles of your trades. Check chance of hitting the MLL.
- [ ] Ask Codex (or Claude, whichever did not write the backtest) to independently recompute every number from the raw trade list.
- [ ] Confirm **no trade has its entry and exit on different contracts** (`raw_symbol` must match). One such trade can fake thousands of dollars.

**Done when:** all benchmarks in [Section 10](#10-benchmarks-the-numbers-to-aim-for) pass.

### Phase 5 — Practice account (forward test)

**Goal:** prove the live bot behaves like the backtest, with real-time data and real order handling.

- [ ] Run on the Practice Account with **1 CL** for **at least 4 weeks / 40+ trades**.
- [ ] Compare each live trade with what the backtest says should have happened on the same day.
- [ ] In the Practice Account only, run controlled failure tests. First confirm a server-side stop is working. Then test: dropped data connection, stopped program, restart, expired login. Does it reconcile correctly? Never disconnect while a position lacks a confirmed protective stop.

**Done when:** live results are within normal range of backtest, no unexplained trades, and every failure test passed.

### Phase 6 — Trading Combine

**Goal:** pass the evaluation without breaking rules.

- [ ] Trade **1 CL contract only**, using the sizing rules in [Section 11](#11-position-sizing-for-prop-firm-rules).
- [ ] Watch the bot daily. Do not change code mid-Combine except to fix a real bug (and re-test first).
- [ ] Stop trading once the profit target and consistency rule are both met.

**Done when:** Combine passed.

### Phase 7 — Express Funded and beyond

**Goal:** keep the account alive and get paid.

- [ ] Read current XFA payout rules (verify). Reported paths: 5 winning days of $150+, or a consistency path (best day ≤ 40% of profit, 3+ trading days).
- [ ] Follow the XFA Scaling Plan; your bot must read and respect the current size limit.
- [ ] **Ask Topstep in writing** how automated trading works after a call-up to a Live Funded Account, because API support for Live is reported to be missing.

---

## 9. Starter Strategy Ideas

These are **learning examples**, not proven money-makers. Use them to practise the full process. Expect to change or reject them after testing.

### Idea A — Opening Range Breakout (ORB)

**Concept:** the first minutes after the main session opens often set a range. A break out of that range may continue.

- Window: this example uses 9:00 AM ET as its chosen US-morning starting point (CL's electronic market is open almost 24 hours, so this is not "the" market open). Opening range = high and low of 9:00–9:15 AM ET.
- Entry long: a 5-minute bar **closes** above the range high (enter at next bar open).
- Entry short: a 5-minute bar closes below the range low.
- Stop: other side of the range, or a fixed max (e.g. 12 ticks on 50K, 18 ticks on 150K — see Section 11), whichever is smaller. If the range is wider than your max stop, skip the day.
- Target: 1.5R. Or exit at 11:30 AM ET if neither hit.
- Max 1 trade per day. No trades on EIA days between 10:15–10:45 AM ET.

### Idea B — VWAP Pullback

**Concept:** in a trending morning, price often pulls back to the day's average price (VWAP) before continuing.

- Trend filter: price above VWAP for most of the first hour = uptrend (opposite for downtrend).
- Entry: price touches VWAP and the next 5-minute bar closes back in the trend direction.
- Stop: a fixed distance beyond VWAP (e.g. 10–12 ticks on 50K, up to 18 on 150K).
- Target: 1.5–2R, or exit by 1:30 PM ET.
- Max 2 trades per day.

**Why "bar closes" matters:** using the bar's close (and entering on the next bar) prevents look-ahead bias. During a live bar you do not know where it will close.

---

## 10. Benchmarks: The Numbers to Aim For

These are **safety gates**, not profit promises. Every number is measured **after fees and realistic slippage**, and mostly on **out-of-sample** data.

**"Suspicious" means too good to be true.** It usually signals a bug (look-ahead bias, unrealistic fills) or overfitting. Investigate before celebrating.

### Core performance metrics

| Metric | What it means | Minimum | Good | Suspicious |
|---|---|---|---|---|
| **Win rate** | % of trades that make money | No standalone minimum — judge with avg win ÷ avg loss | — | > 75% with normal stops |
| **Profit factor** | Total $ won ÷ total $ lost | 1.20 | 1.40 – 1.80 | > 2.5 on a large sample |
| **Expectancy** | Average profit per trade, in R | +0.10R | +0.20R to +0.35R | > +0.75R over hundreds of trades |
| **Avg win ÷ avg loss** | How big wins are vs losses | No standalone minimum. Combos that meet the other minimums: 50% wins with 1.2:1, or 45% wins with ~1.5:1 | 1.5 – 2.0 (when it fits the win rate) | Judge together with win rate |
| **Sharpe ratio** (daily) | Return vs how bumpy the ride is | 0.8 | 1.2 – 2.0 | > 3 |
| **Sortino ratio** (daily) | Like Sharpe but only punishes downside | 1.2 | 1.8 – 3.0 | > 4 |
| **Recovery factor** | Net profit ÷ max drawdown | 1.5 | > 2.5 | > 5 without a long, varied sample |

**Why win rate alone is useless:** a bot can win 90% of trades and still lose money if one loss wipes out ten wins. Always read win rate **together with** average win ÷ average loss. That combination is what expectancy measures. For example, 40% wins with a 1.5:1 ratio only **breaks even** (0.4 × 1.5 = 0.6 R won vs 0.6 R lost) — and after costs, it loses.

**Expectancy formula:**
```
Expectancy = (Win rate × Avg win) − (Loss rate × Avg loss)
Example: (0.45 × $30) − (0.55 × $20) = $13.50 − $11.00 = +$2.50 per trade
```

### Prop-firm survival metrics (most important for Topstep)

| Metric | Target | Why |
|---|---|---|
| **Max backtest drawdown** | ≤ 30–35% of MLL (50K: ≤ $600–$700) | The future is usually worse than the backtest. You need room. |
| **Monte Carlo 95th percentile drawdown** | < 50–60% of MLL (50K: < $1,000–$1,200) | Even in a bad-luck order of trades, you survive. |
| **Risk of ruin** (chance of hitting MLL in Monte Carlo) | < 1% good, 1–5% marginal, > 5% reject | Estimates failure risk **if future trades look like past trades**. It does not cover the strategy breaking down, worse slippage, software bugs, or new market conditions. |
| **Worst losing streak × 1.5–2** | Uses ≤ 35–40% of MLL | Future losing streaks are usually longer than past ones. |
| **Worst single day** | Smaller than your own daily stop | Proves the daily stop is working in the backtest. |
| **Best single day** | Below the consistency limit (≤ ~45% of target) | Avoids raising your profit target by having one huge day. |

### Sample size and robustness

| Check | Minimum | Better | Why |
|---|---|---|---|
| **Number of trades** | 300+ over 12+ months | 500–1,000 over 2–3 years | Small samples are mostly luck. |
| **Market conditions covered** | Trend + range | Trend, range, high and low volatility, rollovers, news periods | A strategy tested only in one type of market will break when the market changes. |
| **Out-of-sample decay** | Profit factor / expectancy drop ≤ 25–35% | Smaller drop | Some decay is normal. Reject if expectancy turns negative or drawdown doubles. |
| **Parameter sensitivity** | Results stay positive when settings change slightly | Smooth "plateau" of good results | If only one exact setting works, it is overfit. |
| **Monte Carlo runs** | 10,000 | Also shuffle small groups of consecutive trades, so real winning and losing streaks stay together | Shows a wider range of possible luck. |
| **Practice account forward test** | 4 weeks / 40+ trades | 8 weeks | Proves real-time behaviour matches the backtest. |

### Cost assumptions

Always include these. A strategy that only works without costs is not a strategy. **(verify fees)**

| | CL (per contract) |
|---|---|
| Round-turn fee | ~$4.02 |
| **Base slippage** | 1 tick each side = $20 round turn |
| **Stress slippage** | 3–5 ticks each side ($60–$100 round turn), worse around news |

**Rule:** if the strategy stops being profitable when you add **one extra tick of slippage per side**, reject it. Its edge is too thin to survive real trading.

---

## 11. Position Sizing for Prop Firm Rules

### The key idea

**Size from your Maximum Loss Limit, not from the account size.** A "$50K account" really gives you **$2,000 of risk room**. Treat it like a $2,000 account.

### CL means 1 contract — so you control risk with stop size and account size

With CL, the smallest trade (1 contract) already risks $100–$250. So instead of choosing "how many contracts", you choose:

1. **How wide your stop is** (in ticks), and
2. **Which Combine size** (50K, 100K, or 150K) gives enough loss-limit room for that stop.

### The formula

```
Loss per trade (1 CL) = (Stop ticks × $10) + Expected slippage + Round-turn fee

Example: 15-tick stop, 1 tick slippage each side ($20), fee $4.02
Loss per trade = $150 + $20 + $4.02 = $174.02

Losses until MLL is hit = MLL ÷ Loss per trade
  50K  ($2,000):  2,000 ÷ 174 ≈ 11 losses
  150K ($4,500):  4,500 ÷ 174 ≈ 25 losses
```

### How to choose your stop and account size

1. From your backtest, find your **worst losing streak** (e.g. 7 losses in a row).
2. Plan for **2× that streak** (future streaks are often longer): 7 × 2 = 14 losses.
3. Those 14 losses must use **no more than ~40% of the MLL**:
   - 14 × $174 = $2,436 → needs MLL ≥ $2,436 ÷ 0.40 ≈ **$6,090**. Too much even for 150K.
   - So either **tighten the stop** (10 ticks: 14 × $124 = $1,736 → MLL ≥ $4,340 → 150K works), or **find a strategy with shorter losing streaks**.
4. Pick the **smallest Combine** where the numbers fit. If none fit, the strategy is not ready for CL.

### Suggested starting rules

| Setting | 50K ($2,000 MLL) | 150K ($4,500 MLL) |
|---|---|---|
| Contracts | 1 CL, always | 1 CL to start (add a 2nd only after a long, proven track record) |
| Max stop | ~10–12 ticks | ~15–20 ticks |
| Daily stop (your own) | 2 losing trades (~$250–$300) | 2–3 losing trades (~$450–$550) |
| Daily profit lock | ~45% of $3,000 target ≈ $1,350 | ~45% of $9,000 target ≈ $4,050 |

**Always include costs** in the loss estimate, because real fills on CL are often worse than the stop price. And always respect the **smallest** of: your own limit and Topstep's current CL limit.

**Why this matters:** at ~$174 per loss, a 50K account survives only ~11 straight losses. At ~$124 per loss on a 150K account, it survives ~36. How long your losing streaks get depends on your strategy — measure it in the backtest, plan for 2× the worst one, and pick your stop and account size to fit.

---

## 12. Working with Claude Code and Codex Together

Two AI assistants are like **an author and an editor**. One writes, the other checks. Mistakes the writer cannot see are often obvious to the reviewer.

### The working loop

```
 1. YOU write the spec (what the module must do, rules, units, tests)
        │
 2. Claude Code builds the module + tests
        │
 3. Codex reviews (bugs, rule breaks, failure cases) — does NOT edit yet
        │
 4. YOU read the review, decide what to fix
        │
 5. Claude fixes → tests pass → you save a Git commit
        │
 6. Next module: SWAP roles (Codex builds, Claude reviews)
```

### Ground rules

1. **Spec and tests before code.** Write what "correct" means first.
2. **Never let both AIs edit the same file at the same time.** They will overwrite each other.
3. **Swap roles per module**, so neither is the permanent unchecked author.
4. **You approve every change** to order sending, sizing, the risk engine, the kill switch, or credentials. Read these changes line by line, and ask the AI to explain anything unclear.
5. **Never paste API keys or passwords into a prompt.** Keep them in a `.env` file. Make sure logs hide them.
6. **Check AI claims about the API against the official docs.** AIs sometimes invent endpoints or field names that do not exist.
7. **Small steps.** One module per session. Commit to Git after each working step so you can undo.
8. **Ask "why".** When an AI writes something, ask it to explain. That is how you learn.

### Copy-paste prompt templates

**1. Build prompt** (to the builder)
> Implement only the `[module name]` described in the spec below. Do not change any other module. List every assumption you make about the TopstepX/ProjectX API and link the doc page for each. Add pytest tests for: normal case, reconnects, partial fills, duplicate events, stale data, and unknown position state. In unknown state, the code must block new entries. Explain your design in simple English for a beginner.
>
> Spec: [paste spec]

**2. Review prompt** (to the reviewer)
> Review this trading bot code as if one defect could breach a $2,000 trailing drawdown on a Topstep account. Look for: race conditions, wrong CL dollar conversions ($10 per tick per contract), look-ahead bias, optimistic fills, missing session or flatten-time handling, orders that could duplicate after a reconnect, and missing protective stops. Do not rewrite the code. Rank findings by severity and cite exact file and line.

**3. Independent validation prompt** (to whichever AI did not write the backtest)
> Recalculate every reported metric (win rate, profit factor, expectancy, max drawdown, Sharpe, risk of ruin) from the raw trade list, including fees and 1, 2, and 5 ticks of slippage per side. Check that the held-out out-of-sample period was never used for choosing parameters. Explain every difference from the reported numbers.

**4. Teaching prompt** (anytime)
> I am a beginner. Explain what this code does line by line in simple English, and why each part is needed. Then give me one small exercise to check I understood.

---

## 13. Common Beginner Mistakes

| Mistake | Why it hurts | Fix |
|---|---|---|
| **Overfitting** — tuning until the backtest looks perfect | Fits past noise; fails on new data | Few rules, few parameters, out-of-sample + walk-forward tests |
| **Look-ahead bias** — using a bar's close before the bar closed | Backtest looks amazing, live loses | Only act on completed bars; enter on the next bar |
| **Ignoring costs and slippage** | Thin "edges" disappear | Always include fees + slippage; stress test +1 tick |
| **Rollover gaps** in continuous data | Fake profits or losses at the roll. Example: 18 May 2026, CLM6 → CLN6 = −417 ticks = a fake −$4,170 per contract | Daytime trading + flat by 3:10 PM CT never crosses a roll (rolls happen in the evening, mostly 00:00 UTC); crash the backtest if entry and exit `raw_symbol` differ (see Phase 3 "Roll days") |
| **Sizing from $50K instead of $2K** | Account blows up in a few losses | Size from the MLL (Section 11) |
| **Believing a stop guarantees its price** | Oil gaps through stops on news | Smaller size, news blocks, stress slippage |
| **Confusing EOD trailing with intraday trailing** | Wrong safety margin | Model the trailing MLL exactly, verify with Topstep |
| **Hard-coding Topstep rules** | Rules change; bot breaks them | Keep rules in config, re-verify regularly |
| **Trusting local state after a disconnect** | Duplicate orders, double size | Reconcile with the broker after every reconnect |
| **Running on a VPS** | Breaks Topstep's rules | Run on your own computer |
| **Trading big into EIA/OPEC news** | Huge slippage; may break Topstep conduct rules | Block entries around news |
| **Going straight from backtest to Combine** | Live bugs found with real rules at stake | Practice account first, 4+ weeks |
| **Trusting AI-invented API fields** | Code fails silently or sends wrong orders | Check every field against official docs |
| **Changing the bot after a few losing days** | Destroys the statistical edge you tested | Only change with a new full test cycle |
| **Thinking a passed Combine proves an edge** | One pass can be luck | Keep tracking metrics vs backtest |

---

## 14. Checklists: Go-Live, Daily Operations, Emergencies

### Before going live in the Combine

- [ ] All benchmarks in Section 10 passed on out-of-sample data.
- [ ] 4+ weeks in the Practice Account, behaviour matches the backtest.
- [ ] Disconnect, crash, and restart tests all passed.
- [ ] Every entry places a server-side protective stop.
- [ ] Daily stop, daily profit lock, flatten at 3:05 PM CT, news block all tested.
- [ ] Hard contract limit set below Topstep's limit.
- [ ] Kill switch tested.
- [ ] Topstep rules re-verified this week on the help center.
- [ ] Fees re-verified.
- [ ] Alerts reach your phone (e.g. Telegram/Discord/email message).
- [ ] Running on your own computer, with sleep mode off and a stable internet connection.

### Daily routine

**Before the session**
- [ ] Check the economic calendar (EIA, OPEC, Fed, holidays).
- [ ] Confirm the bot is using the correct front-month contract.
- [ ] Confirm the account balance and fail line match your records.
- [ ] Start the bot and confirm it sees live data and the correct position (flat).

**During the session**
- [ ] Check alerts. Do not interfere with trades unless something is clearly broken.

**After the session**
- [ ] Confirm the account is flat.
- [ ] Review the trade log: did every trade follow the rules?
- [ ] Compare today's trades with what the backtest would have done.
- [ ] Update a simple journal (date, P&L, issues).

### Emergency procedure

If anything looks wrong (unexpected position, repeated errors, frozen data, wrong size):

1. **Stop the strategy from sending orders** (kill switch).
2. **Cancel all working orders, flatten all positions**, then log in to TopstepX manually and confirm: zero positions **and** zero working orders.
3. **Save the logs.** Do not restart yet.
4. Find the cause with Claude/Codex using the logs.
5. Fix, test in the Practice Account, then restart.

### Stop conditions (turn the bot off and re-evaluate)

- Live drawdown exceeds the Monte Carlo 95th percentile drawdown.
- Losing streak longer than 2× the worst backtest streak.
- Live results consistently differ from the backtest on the same days.
- Any trade the bot cannot explain from its rules.
- Topstep changes a rule that affects the bot.

---

## 15. Resources

**Topstep official help center** (always the final source for rules):
- [New to Topstep — start here](https://help.topstep.com/en/articles/8284199-new-to-topstep-start-here)
- [TopstepX API access](https://help.topstep.com/en/articles/11187768-topstepx-api-access)
- [TopstepX platform](https://help.topstep.com/en/articles/14434175-topstepx)
- [Maximum Loss Limit](https://help.topstep.com/en/articles/8284204-what-is-the-maximum-loss-limit)
- [Consistency at Topstep](https://help.topstep.com/en/articles/8284208-consistency-at-topstep)
- [Daily Loss Limit](https://help.topstep.com/en/articles/10490293-daily-loss-limit-in-the-trading-combine-and-express-funded-account)
- [Express Funded Account parameters](https://help.topstep.com/en/articles/8284215-express-funded-account-parameters)
- [Scaling Plan](https://help.topstep.com/en/articles/8284223-what-is-the-scaling-plan)
- [Trading hours and products](https://help.topstep.com/en/articles/8284206-when-and-what-products-can-i-trade)
- [Prohibited trading strategies](https://help.topstep.com/en/articles/10305426-prohibited-trading-strategies-at-topstep)
- [TopstepX commissions and fees](https://help.topstep.com/en/articles/8284213-topstepx-commissions-and-fees)

**API**
- ProjectX Gateway API documentation (find the current link from the TopstepX API access article above).

**Market information**
- [EIA Weekly Petroleum Status Report schedule](https://www.eia.gov/petroleum/supply/weekly/)
- CME Group contract specs for CL (search "CME Crude Oil futures contract specs").

**Historical data**
- [ProjectX retrieveBars docs](https://gateway.docs.projectx.com/docs/api-reference/market-data/retrieve-bars/) and [rate limits](https://gateway.docs.projectx.com/docs/getting-started/rate-limits/)
- [Databento pricing](https://databento.com/pricing) and [continuous contracts guide](https://databento.com/docs/examples/symbology/continuous)
- [Massive (Polygon) futures pricing](https://massive.com/pricing?product=futures)
- [Barchart Premier](https://help.barchart.com/support/solutions/articles/242752-what-are-the-benefits-and-cost-of-a-premier-subscription-)
- [Sierra Chart Denali data feed](https://www.sierrachart.com/index.php/h/index.php?page=doc%2FDenaliExchangeDataFeed.php)
- [TradingView data policies](https://www.tradingview.com/policies/) (why not to use exported data)

**Learning**
- Python basics: the official Python tutorial (docs.python.org/3/tutorial).
- Ask Claude or Codex for small daily exercises using the teaching prompt in Section 12.

---

*This guide was planned with input from both Claude and Codex, and reviewed by Codex for factual, math, and safety errors. Rules marked "verify" can change — always check the official Topstep help center.*
