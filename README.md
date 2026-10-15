# Topstep CL Trading Bot

The foundation for a planned automated trading bot for a **Topstep** prop-firm account, trading **Crude Oil futures (CL)**. Built step by step by a beginner, with **Claude Code** and **OpenAI Codex** as AI pair-programmers.

Right now it **downloads, converts, validates, and cross-checks** CL historical data. Strategy, backtesting, and live-trading code come next.

> **Status:** Data pipeline and backtester done. Strategies 1-5 (EMA x VWAP, ORB, ZAB, Crabel, Fisher ACD) tested: **all failed** the safety gates. See [Strategy results](#strategy-results). No live-trading code yet.
>
> **Not financial advice.** Most trading strategies lose money. This project is a learning build with heavy safety checks, not a promise of profit.

---

## Table of Contents

1. [What this project is](#what-this-project-is)
2. [Project status](#project-status)
3. [Quick start](#quick-start)
4. [Project structure](#project-structure)
5. [The data pipeline](#the-data-pipeline)
6. [Commands](#commands)
7. [Important: roll days](#important-roll-days)
8. [Safety rules](#safety-rules)
9. [How Claude and Codex work together](#how-claude-and-codex-work-together)
10. [Strategy results](#strategy-results)
11. [Troubleshooting](#troubleshooting)
12. [Documents](#documents)
13. [Contributing](#contributing)
14. [License](#license)

---

## What this project is

| | |
|---|---|
| **Goal** | Pass a Topstep Trading Combine with an automated bot, without breaking any rule |
| **Market** | CL (WTI Crude Oil, NYMEX). $0.01 tick = **$10 per contract** |
| **Platform (planned)** | Python + TopstepX / ProjectX API, running on a personal computer (Topstep bans VPS) |
| **Historical data** | Databento, 1-minute bars, June 2010 to October 2026 (10.4 million bars) |
| **Data cross-check** | Massive (formerly Polygon), last 2 years |
| **Language** | Python 3.12 |

The full beginner guide, covering Topstep rules, CL basics, architecture, roadmap, and benchmarks, is in **[TRADING_BOT_GUIDE.md](TRADING_BOT_GUIDE.md)**.

---

## Project status

The roadmap comes from [TRADING_BOT_GUIDE.md, Section 8](TRADING_BOT_GUIDE.md#8-step-by-step-roadmap).

| Phase | What | Status |
|---|---|---|
| 0 | Learn and set up | ✅ Done |
| 1 | Write the strategy in plain words | 🔁 Strategies 1-5 written and tested. **All failed.** Main blocker: drawdown on 1 CL (see [lessons](#lessons-across-strategies-1-5)) |
| 2 | Get data and handle rollover | ✅ Done: downloaded, validated, cross-checked against Massive (Databento confirmed correct, see [results](#data-quality-results)) |
| 3 | Backtest with real costs | ✅ Backtester built (`propfirm_backtest/`), verified independently by Codex |
| 4 | Robustness testing (out-of-sample, walk-forward, Monte Carlo) | ✅ Built in: holdout, walk-forward, bootstrap Combine simulation, slippage stress |
| 5 | Practice account, 4+ weeks | ⬜ |
| 6 | Trading Combine | ⬜ |
| 7 | Express Funded and beyond | ⬜ |

---

## Quick start

### 1. Requirements

- Python 3.12 (Linux / WSL)
- A [Databento](https://databento.com) account (new accounts get $125 free credit)
- Optional: a [Massive](https://massive.com) account (free Futures Basic tier), only for the cross-check

### 2. Install

```bash
git clone https://github.com/mrullldhm/trading_bot.git propfirm
cd propfirm
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 3. Add your API keys

Create a file called `.env` in the project folder:

```bash
DATABENTO_API_KEY=db-your-key-here
MASSIVE_API_KEY=your-massive-key-here
```

`.env` is listed in `.gitignore`, but that is not a security guarantee. Run `git status --short` before every push, never force-add `.env`, and **never paste keys into a chat, an issue, or a commit**. If a key leaks, regenerate it.

### 4. Get the data

```bash
python -m propfirm_data.download          # free: shows the price, pays nothing
python -m propfirm_data.download --yes    # pays (~$38) and downloads
python -m propfirm_data.validate          # data-quality checks
python -m propfirm_data.crosscheck        # optional: compare with Massive (free, ~15 min)
python -m pytest -q                       # run the automatic tests
```

Full details: **[README_DATA.md](README_DATA.md)**.

---

## Project structure

```
propfirm/
├── README.md                 ← you are here
├── TRADING_BOT_GUIDE.md      ← the full beginner guide (rules, roadmap, benchmarks)
├── README_DATA.md            ← how to download and use the data
├── requirements.txt          ← exact package versions
├── pyproject.toml            ← pytest settings
├── .env                      ← your API keys (never committed)
├── propfirm_data/            ← data pipeline (Python package)
│   ├── config.py             ← all settings in one place (symbols, dates, paths, budget)
│   ├── budget.py             ← cost guard: refuses downloads over budget
│   ├── download.py           ← Databento batch download (pay once, resume free)
│   ├── convert.py            ← raw files → clean Parquet tables; load_bars()
│   ├── validate.py           ← data-quality checks
│   ├── crosscheck.py         ← compare Databento with Massive
│   └── eia_calendar.py       ← EIA release slots to block (from the published rule only)
├── propfirm_backtest/        ← backtester (numba-compiled)
│   ├── bars.py               ← contracts, sessions, timeframe bars, roll schedule
│   ├── indicators.py         ← EMA, anchored VWAP
│   ├── engine.py             ← trade simulator (1-minute fill ordering, stops, cutoffs)
│   ├── propsim.py            ← Topstep Combine simulator + trade metrics
│   ├── search.py             ← strategy 1, step 1: grid search on 2010-2021 only, freezes picks
│   ├── holdout.py            ← strategy 1, step 2: tests the picks ONCE on 2022-today
│   ├── orb_engine.py         ← ORB day simulator + shared fill/exit rules + grid kernels (numba)
│   ├── orb_reference.py      ← slow plain-Python ORB, cross-checks the engine trade by trade
│   ├── orb_search.py         ← strategy 2 (and the shared selection pipeline for 3-5)
│   ├── orb_holdout.py        ← once-only holdout test (ORB; reused by the families)
│   ├── orb_features.py       ← prior-session features: ATR14, stretch, NR4/NR7, inside, pivots
│   ├── orb_family_engine.py  ← strategies 3-5 day simulators (ZAB, Crabel, Fisher ACD)
│   ├── orb_family_reference.py ← slow plain-Python versions of 3-5 + features
│   ├── family_search.py      ← strategies 3-5, step 1 (grids, selection, reports)
│   ├── family_holdout.py     ← strategies 3-5, step 2 (refuses if the champion failed the gates)
│   ├── family_program.py     ← strategies 3-5 as one programme (union DSR/PBO, Holm)
│   ├── audit.py              ← backtest audit: scenarios, positive control, idea-vs-execution, report
│   └── acd_signal_holdout.py ← pre-registered once-only ACD entry-signal test on 2022+
├── tests/                    ← automatic tests (no internet needed)
└── data/                     ← downloaded data (never committed, ~360 MB)
    ├── raw/                  ← original Databento files: raw/{bars,definitions}/<job-id>/*.dbn.zst
    ├── processed/            ← clean Parquet, one file per year
    ├── manifests/            ← record of paid jobs (do not delete)
    └── crosscheck/           ← Massive cache + cross-check report
```

**Why separate files?** Each file has one job and can be tested alone, like departments in a small company. If something breaks, you know where to look.

---

## The data pipeline

```
 Databento (CME data)
        │  download.py: quote → budget check → batch job (billed once) → hash-checked files
        ▼
 data/raw/.../*.dbn.zst      original files, never modified
        │  convert.py: prices → integer ticks, attach real contract symbol + expiry
        ▼
 data/processed/ohlcv-1m/year=YYYY/cl.parquet
        │
        ├── validate.py    duplicates, impossible prices, tick grid, sessions, gaps, rolls
        └── crosscheck.py  same minutes vs a second vendor (Massive)
        ▼
 load_bars()  →  your backtest
```

### What is in the data

| Column | Meaning |
|---|---|
| `ts_event_utc` | Start of the 1-minute bar, in UTC |
| `continuous_symbol` | `CL.v.0` = front contract, `CL.v.1` = next contract (ranked by previous day's volume) |
| `raw_symbol` | The real contract, e.g. `CLN6` = July 2026 |
| `open_ticks` … `close_ticks` | Prices as whole numbers of ticks (1 tick = $0.01). **Use these for calculations** |
| `open` … `close` | Same prices in dollars. Use these for charts |
| `volume` | Contracts traded in that minute |
| `expiration` | When that contract expires |

**Why integer ticks?** Computers store decimals like 90.81 slightly wrong (90.80999…). Whole-number ticks are always exact, so profit/loss math never drifts.

### Using the data

```python
from propfirm_data.convert import load_bars

bars = load_bars()                                   # all years
front = bars[bars["continuous_symbol"] == "CL.v.0"]  # front contract only
```

### Data quality results

| Check | Result |
|---|---|
| Bars | 10,400,832 (June 2010 → 13 Oct 2026) |
| Validation | **PASS (no errors)**: no duplicates, no impossible prices, all on the $0.01 grid, every bar tied to a live contract. Warnings (normal, reviewed): 32,111 bars outside the modelled session (mostly old 16:00–16:15 CT trading), 295 quiet gaps > 15 min, 58 full-closure weekdays |
| Contract rolls | 196 in 16.3 years (≈12/year, as expected) |
| Cross-check vs Massive (Oct 2024 → Oct 2026, CL.v.0) | 99.9% of bars in both vendors · open/high/low exact on 99.93–99.99% · volume exact 99.6% · **close exact 98.2%** (median diff 1 tick) |

**Cross-check verdict: WARN, resolved: Databento is correct.** Both vendors have the same trades: volume and open/high/low match almost perfectly. The only real difference is the **close** on ~1.8% of bars, usually by 1 tick.

We checked the individual trades (Databento `trades` schema, $0.01) for the 4 worst minutes. In **all 4**, Databento's close equals the true last trade; Massive's does not. The cause: one large order hits several price levels in the **same instant** (e.g. fills at 98.82, 98.86, 98.87, 98.88, all with one exchange timestamp and sequence number). The exchange reports them in order, so the last fill (98.88) is the true close. Databento follows exchange order; Massive picks a different price. In one minute Massive also missed trades (volume 1,376 vs 1,540 actual).

Lesson for backtesting: different data vendors can disagree on 1-minute closes, so a strategy should **not depend on an exact 1-minute close** (e.g. "enter only if close = X exactly"). Full report: `data/crosscheck/report.md` (local only).

---

## Commands

| Command | What it does | Costs money? |
|---|---|---|
| `python -m propfirm_data.download` | Shows the price of the download | No |
| `python -m propfirm_data.download --yes` | Submits paid jobs, downloads, converts | **Yes, once** (~$38) |
| `python -m propfirm_data.download --yes --max-budget 50` | Same, with a lower spending cap | Yes, once |
| `python -m propfirm_data.validate` | Data-quality report, exits with an error if data is broken | No |
| `python -m propfirm_data.crosscheck` | Compares the last 2 years with Massive | No (free tier) |
| `python -m propfirm_backtest.search` | Strategy grid search on 2010-2021 (~5 min), freezes picks | No |
| `python -m propfirm_backtest.holdout` | Tests frozen picks on 2022-today. **Runs once only** | No |
| `python -m propfirm_data.eia_calendar` | Builds the EIA release slots to block (needed by strategies 2-5) | No |
| `python -m propfirm_backtest.orb_search [--quick]` | Strategy 2: ORB grid, 1,056,000 configs (~25 min) | No |
| `python -m propfirm_backtest.family_search zab\|crabel\|acd [--quick]` | Strategies 3-5: grid + selection (a few minutes each) | No |
| `python -m propfirm_backtest.family_program` | Strategies 3-5 programme checks (after the three searches) | No |
| `python -m propfirm_backtest.orb_holdout` / `family_holdout <name>` | Holdout of a frozen champion. **Runs once only**; the family version refuses if the champion failed the gates | No |
| `python -m propfirm_backtest.audit scenarios` / `control` / `report` | Backtest audit: re-runs every search under other assumptions (~4 h), the planted-edge control, then the report | No |
| `python -m propfirm_backtest.acd_signal_holdout --register` / `--run` | Freeze the ACD signal test (never reads 2022+), then run it **once only** | No |
| `python -m pytest -q` | Runs all automatic tests | No |

If downloading or converting is interrupted, re-running `download --yes` resumes the recorded jobs **without paying again** (files can be re-downloaded free for 30 days). Exception: if it says *a submit was recorded but no job id was saved*, stop and follow [Troubleshooting](#troubleshooting). Do not submit again blindly.

---

## Important: roll days

`CL.v.0` is not one contract. It is a **chain of monthly contracts glued together**. When it switches to the next month, the price **jumps** even though the market did not move.

**Real example:** 18 May 2026, CLM6 → CLN6 = **−417 ticks**. On 1 contract that looks like a **−$4,170 loss**, which is more than double a 50K account's whole $2,000 loss limit. No real position ever experienced it.

**A backtest must never count a roll jump as profit or loss.**

- In this data, rolls happen mostly at **00:00 UTC** (6–7 PM Chicago); others at a session reopen (22:00 or 23:00 UTC), plus one old exception at 01:15 UTC. **None during US daytime.**
- A daytime strategy that is flat by Topstep's 3:10 PM CT cutoff never crosses a roll.
- The backtest must **crash** if a trade's entry and exit have different `raw_symbol`.

Details: [TRADING_BOT_GUIDE.md → Phase 3 → Roll days](TRADING_BOT_GUIDE.md) and [README_DATA.md → Roll days](README_DATA.md).

---

## Safety rules

### Money (data downloads)
- **Quote first.** Nothing is paid without `--yes`.
- **Budget cap.** Refuses if quote + 10% margin is over the cap (default $60).
- **Pay once.** Batch jobs are billed once. Paid jobs are recorded in `data/manifests/download.json` before submitting.
- **One copy at a time.** A lock file stops two downloads from running together.

### Secrets
- API keys live in `.env`. This code never prints them; the Massive key goes in an HTTPS header (not the URL) and only to `api.massive.com`. Still treat logs and third-party tools as potentially sensitive.
- If a key is ever shared by mistake, **regenerate it** in the provider's portal.

### Trading (planned, from the guide)
- Size from the **Maximum Loss Limit** ($2,000 on 50K), not the account size.
- Every entry has a **server-side stop**; unknown position state means **no new entries**.
- Flat by **3:05 PM CT**; no trading around the **EIA report** (Wed 10:30 ET).
- Only a **personal computer**: Topstep bans VPS, VPN, and cloud servers.

---

## How Claude and Codex work together

Like an **author and an editor**: one writes, the other checks.

```
You write the spec  →  Claude builds + tests  →  Codex reviews (no edits)
        →  You decide  →  Claude fixes  →  tests pass  →  commit
```

- Every module in this repo was **built by Claude and reviewed by Codex** before it ran. Codex's reviews caught real bugs, e.g. a cost-guard hole (`NaN` budget), a job-status bug that would have broken right after paying, and a cross-check counting error.
- Never let both AIs edit the same file at once.
- Anything touching **money, orders, sizing, or keys** needs your approval.

Copy-paste prompts: [TRADING_BOT_GUIDE.md, Section 12](TRADING_BOT_GUIDE.md#12-working-with-claude-code-and-codex-together).

---

## Strategy results

### Strategy 1: EMA x VWAP: ❌ FAILED (2026-10-15)

**Rules:** enter when a candle breaks through VWAP (long above, short below); exit when a candle closes back through the EMA. Same timeframe for both. 1 CL contract, $4.02 fees + 1 tick slippage per side.

**Tested:** 6,144 combinations = 8 timeframes (1–60 min) × 8 EMA lengths (9–200) × 3 VWAP anchors (day / session / week) × 2 entry types (candle close crosses VWAP / price touches VWAP) × 4 stops (none / 10 / 15 / 20 ticks) × 4 sessions (Asian / London / New York / All).

| Finding | Result |
|---|---|
| Settings profitable after costs (2010–2021) | 37 of 6,144 (0.6%), only 3 with +1 tick extra slippage |
| Settings passing every safety gate | **0** |
| "Best" setting (2010–2021) | 60 min / EMA 21 / weekly VWAP / close-cross / no stop / New York: **+$24/trade**, profit factor 1.11 |
| Same setting on unseen 2022–2026 | **−$33/trade**, profit factor 0.90, Combine pass 16% vs fail 78% |
| Walk-forward (pick each year from earlier years only) | No year ever had a qualifying setting |

**What we learned:**
- **Timeframe:** longer is better (60 min is least bad); 1–15 min lose in every setting, because costs eat small moves.
- **Entry:** close-cross beats touch; touch entries never made money.
- **Stops:** tight stops (10 ticks) hurt the most; CL's noise hits them constantly.
- **Session:** no session works; New York has the single best setting but also the worst median.
- **Overfitting is real:** the best of 6,144 tries looked profitable only by luck, and it lost money on new data.
- **Drawdown:** even the best settings had a 95th-percentile drawdown of ~$3,000–4,700 in 60 days, which is more than the $2,000 Topstep limit. 1 CL contract without a stop is too big for a 50K account with this rule.

Full reports (local): `data/backtests/ema_vwap/report.md` (development), `holdout.md` (holdout), `results.csv` (all 6,144).

### Strategies 2-5: the opening-range family

Same discipline as strategy 1: 1 CL, $4.02 fees + 1 tick slippage per side, ambiguous 1-minute fills resolved against us, targets need a 1-tick trade-through, EIA releases blocked ±15 min, flat by 16:00 ET (12:55 on CME short days, before contract expiry). Search on 2010–2021 only; one champion frozen per strategy. Every engine has a separate slow reference that matches it trade for trade; Codex reviewed each strategy and recomputed champion trades from the raw bars.

| # | Strategy (2026-10-15) | Configs | Passed every gate | Best setting found (2010–2021) | Verdict |
|---|---|---|---|---|---|
| 2 | **ORB**: break of the opening range high/low | 1,056,000 | **0** | 09:00 ET, 60-min range, 5-min close entry: **+$19/trade**, PF 1.07, ~$0 with +1 tick | ❌ |
| 3 | **ZAB-inspired**: first candle sets the side (Zarattini, Aziz, Barbon) | 3,456 | **0** | champion −$11/trade; never positive on the main settings | ❌ |
| 4 | **Crabel**: stops at range ± stretch, NR4/NR7/inside-day setups | 7,200 | **0** | champion −$10/trade | ❌ |
| 5 | **Fisher ACD**: A level held for a time, C reversal, pivot bias | 2,880 | **0** | 09:00 ET, 30-min range, pivot-aligned: **+$43/trade**, PF 1.22, **+$23 with +1 tick** | ❌ |

Strategies 3-5 were also judged as one programme (12,809 unique trade streams): no family champion qualified, so no holdout was opened (it would only spend the one look on a known FAIL).

#### Lessons across strategies 1-5

- **Drawdown is the wall, not direction.** Many settings pass every gate *except* the drawdown one: ORB 25, ZAB 15, Crabel 17, **ACD 167**. On 1 CL their worst-case 60-day drawdown is ~$2,100–3,300, above the $1,000 gate (half of Topstep's $2,000 limit). No ACD setting at all gets under $1,000.
- **Micro contracts do not fix it.** Replaying champions at 1-5 MCL ($1/tick, $1.72 fee): fees eat the edge (ACD falls from $43 to $3-15 per trade) and the Combine target is rarely reached in 60 days.
- **Short side and bear market.** Most near-misses are short-only or short-heavy. 2010–2021 includes the 2014–15 and 2020 oil crashes, so part of that "edge" may simply be the trend of that period.
- **What helped:** 09:00 ET (NYMEX open) and London 08:00 beat 08:30 and the 18:00 Globex open; longer ranges (30-60 min) beat 5 min; waiting for a close (or ACD's time acceptance) beat raw stop entries; holding to the session end beat short holds; wide stops beat fixed 15-20 ticks.
- **Luck checks still say no:** walk-forward (picking each year from earlier years only) never found a qualifying setting; deflated Sharpe of the best ACD setting is 2.7% (needs 95%).

Full reports (local): `data/backtests/{orb,zab,crabel,acd}/report.md`, `results.csv.gz` (every config), `champion_trades_dev.csv`, and `data/backtests/orb_families_program.md`.

### Backtest audit: are the FAILs real? (2026-10-16)

The question: did strategies 1-5 fail because they have no edge, or because of a backtest bug, bad data, or rules stricter than Topstep's? Every bias in the engine is **pessimistic** (stop wins ties, targets need a trade-through, 1-2 ticks slippage, $1,000 drawdown gate). A pessimistic bug can never fake a PASS, but it **can** fake a FAIL. So the audit tests both directions. Built by Claude, every step reviewed by Codex.

**Bugs and rule mismatches found and fixed** (all 5 searches re-run afterwards):

| Finding | Effect |
|---|---|
| Flat at 16:00 ET, Topstep allows until 16:10 ET | now exit at the 16:09 open |
| Combine simulation stopped at 60 days; Topstep has no time limit | now 250 days (~1 year of fees); the drawdown gate still measures the first 60 days |
| EMA walk-forward needed 300 trades already in its first 3-year fold | now max(100, 25 per training year), like ORB |
| A day with no daytime data was marked "closed" in advance: a look-ahead for 18:00 ET entries (found by the new truncation test) | 1 day in 12 years affected; fixed in engine and reference |

**What passed:**
- **No look-ahead.** Cutting the data at random minutes, or replacing the future with a random path, changes no earlier decision in any engine. A deliberately planted leak is caught.
- **Accounting.** Long+short pairs cost exactly 2 x (fee + slippage), to 1e-14. Mirrored prices turn every long-only config into the short-only one, trade for trade.
- **Timezone/DST.** Volume spikes sit exactly at 09:00, Wed 10:30 and 14:28 ET in both summer and winter time.
- **Data.** Daily closes match the official WTI spot (EIA via FRED) over 2010-2021, with a median gap of $0.03.
- **Fees and rules** match the Topstep help center ($4.02 CL, $3,000 target, $2,000 MLL, 55% consistency).
- **The pipeline can pass a real edge.** An edge planted in the real data, in ORB's own language, is found from ~$150/trade (gross) when the drawdown gate is off. Noise is never picked.

**Re-run results (rule-fixed engine, 2010-2021):**

| # | Champion $/trade (+1 tick) | Passed every gate | Verdict | Why |
|---|---|---|---|---|
| 1 EMA x VWAP | $24 ($4) | 0 | FAIL | passes only with ALL of: zero costs, optimistic fills, no drawdown gate |
| 2 ORB | $20 ($4) | 0 | FAIL, **no edge after costs** | no edge in the entry signal itself either |
| 3 ZAB | $26 ($6) | 0 | FAIL, **no edge after costs** | no edge in the entry signal itself either |
| 4 Crabel | $85 ($65), 381 trades | 0 | FAIL, **depends on the drawdown gate** | a robust pick appears with the gate at $2,000 (= the whole MLL); its entry edge shows only in 2010-15 |
| 5 Fisher ACD | $45 ($25) | 0 | FAIL, **no edge after costs out of sample** | entry signal shows drift in-sample (best of 2,880, so exploratory) |

**Idea vs execution.** Each champion's entries were frozen and followed with no stop or target, against random entries at the same minute and side in the same weeks. ORB, ZAB and Crabel entries do **not** beat random entries, so better stops or targets cannot rescue them (with no drift, no exit rule creates profit). Stopped-out trades did not recover more often than random ones: the stops are not too tight.

**The real wall is risk, not bugs.** Even a planted edge of ~$150/trade cannot pass the $1,000 p95-drawdown gate on 1 CL; it takes ~$300/trade. CL's normal noise on 1 contract puts the 60-day p95 drawdown at ~$2,300-3,000 for every champion.

**ACD holdout: edge NOT confirmed (2026-10-16).** A pre-registered, once-only test of the ACD champion's entries on 2022+ data (575 signals) found no edge. At 60 minutes the entries did $27/trade *worse* than random entries in the same weeks (randomization p = 0.85). The full strategy with its own exits lost $58/trade (−$33,220). The in-sample drift was selection luck. Report: `data/backtests/acd/signal_holdout.md`. The ACD holdout is now spent.

Full report (local): `data/backtests/audit/report.md`, trade charts `data/backtests/audit/trades_chart.html`. The tables above for strategies 1-5 are from the original run, before these fixes; strategy 1's new picks (`ema_vwap_v2`) have no clean holdout.

---

## Troubleshooting

| Problem | Fix |
|---|---|
| `pip install` fails with `SSL: DECRYPTION_FAILED_OR_BAD_RECORD_MAC` (seen on WSL) | Big wheels fail mid-download. Download each wheel with `curl -C -` in a retry loop, then `pip install --no-index <file>.whl`. Small packages install normally |
| `ABORTED: worst-case spend ...` | The quote is over your budget. Find out why before raising `--max-budget` |
| `a submit was recorded but no job id was saved` | The submit timed out. Check the Databento portal → Download center, copy the job ID into `data/manifests/download.json`. Do **not** just re-run |
| `BentoServerError: 504` | Databento gateway timeout. Free calls retry automatically; for a paid submit, see the row above |
| Cross-check: `rate limited` | Normal on the free tier (5 calls/min). The script waits and continues |
| `Another download is already running` | Wait for the other run to finish |

---

## Documents

| File | What it covers |
|---|---|
| [TRADING_BOT_GUIDE.md](TRADING_BOT_GUIDE.md) | Topstep rules, CL basics, architecture, 7-phase roadmap, benchmarks, position sizing, Claude + Codex workflow, checklists |
| [README_DATA.md](README_DATA.md) | Downloading, validating, and using the historical data |
| `data/crosscheck/report.md` | Latest Databento vs Massive comparison. Local only (not committed), created by `crosscheck` |

---

## Contributing

This is a personal learning project. Open an issue before sending a pull request.

## License

No license is granted yet. Unless a `LICENSE` file is added, all rights are reserved.

---

*Rules and prices in these documents were verified on 2026-10-14. Prop-firm rules and data prices change. Always re-check the official Topstep help center before trading.*
