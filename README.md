# Topstep CL Trading Bot

The foundation for a planned automated trading bot for a **Topstep** prop-firm account, trading **Crude Oil futures (CL)**. Built step by step by a beginner, with **Claude Code** and **OpenAI Codex** as AI pair-programmers.

Right now it **downloads, converts, validates, and cross-checks** CL historical data. Strategy, backtesting, and live-trading code come next.

> **Status:** Phase 2 of 7 done (historical data pipeline built, validated, cross-checked). No strategy or live-trading code yet.
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
10. [Troubleshooting](#troubleshooting)
11. [Documents](#documents)
12. [Contributing](#contributing)
13. [License](#license)

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
| 1 | Write the strategy in plain words | ⬜ Next |
| 2 | Get data and handle rollover | ✅ Done: downloaded, validated, cross-checked (see [results](#data-quality-results)) |
| 3 | Backtest with real costs | ⬜ |
| 4 | Robustness testing (out-of-sample, walk-forward, Monte Carlo) | ⬜ |
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
│   └── crosscheck.py         ← compare Databento with Massive
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

**Cross-check verdict: WARN, explained.** Both vendors have the same trades: volume and open/high/low match almost perfectly. The only real difference is the **close** on ~1.8% of bars, usually by 1 tick. The likely cause: when several trades print in the same instant, the two vendors pick a different one as "last" (not yet proven; checking Databento's individual trades for a few of these minutes would settle it for ~$0.01). This does not affect strategy logic much, but a backtest should **not depend on exact 1-minute closes** (e.g. "enter if close = X exactly"). Full report: `data/crosscheck/report.md` (local only).

---

## Commands

| Command | What it does | Costs money? |
|---|---|---|
| `python -m propfirm_data.download` | Shows the price of the download | No |
| `python -m propfirm_data.download --yes` | Submits paid jobs, downloads, converts | **Yes, once** (~$38) |
| `python -m propfirm_data.download --yes --max-budget 50` | Same, with a lower spending cap | Yes, once |
| `python -m propfirm_data.validate` | Data-quality report, exits with an error if data is broken | No |
| `python -m propfirm_data.crosscheck` | Compares the last 2 years with Massive | No (free tier) |
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
