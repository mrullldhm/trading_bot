# CL Historical Data — How to Download

Downloads 1-minute CL (crude oil) bars from Databento, 2010 → today, for backtesting.

## What you get

| Item | Details |
|---|---|
| Bars | 1-minute OHLCV for `CL.v.0` (front contract) and `CL.v.1` (next contract) |
| Contract info | Real contract symbol (e.g. `CLZ5`) and expiry on every bar |
| Format | Parquet, one file per year: `data/processed/ohlcv-1m/year=YYYY/cl.parquet` |
| Raw source files | `data/raw/` (Databento DBN files — keep them, they are the original) |
| Cost | About **$38** of your $125 free credit (quote shown before anything is paid) |

`CL.v.0` = the contract with the most volume **the previous day**. Databento decides the roll, not you.

## ⚠️ Roll days: the fake price jump

Prices are **not adjusted**. When `CL.v.0` switches to the next contract, the price **jumps** even though the market did not move.

**Example:** 18 May 2026, `CL.v.0` switched CLM6 → CLN6 and jumped **−417 ticks** (a fake −$4,170 on 1 contract, more than double a 50K account's $2,000 loss limit). That is the price gap between two different contracts, **not** a market move. **A backtest must never count it as profit or loss.**

Find the roll bars like this:

```python
from propfirm_data.convert import load_bars

bars = load_bars()
front = bars[bars["continuous_symbol"] == "CL.v.0"].sort_values("ts_event_utc")
front["is_roll"] = front["raw_symbol"] != front["raw_symbol"].shift()
front.loc[front.index[0], "is_roll"] = False  # first bar is not a roll
print(front[front["is_roll"]][["ts_event_utc", "raw_symbol", "open"]])
```

Rules: never hold a trade across `is_roll`; entry and exit must have the same `raw_symbol`; reset indicators at the roll. Full explanation: `TRADING_BOT_GUIDE.md` → Phase 3 → "Roll days".

## Steps

```bash
cd ~/personal/propfirm
source .venv/bin/activate

# 1. Free: see the price. Nothing is paid.
python -m propfirm_data.download

# 2. Check your remaining credit in the Databento portal, then pay + download.
python -m propfirm_data.download --yes

# 3. Check data quality.
python -m propfirm_data.validate

# 4. Run the automatic tests (any time you change code).
python -m pytest -q
```

Step 2 can take a while: Databento prepares the files first (the script checks every 30 seconds).

## Safety features

- **Quote first.** Nothing is paid without `--yes`.
- **Budget cap.** Refuses if worst case (quote + 10%) is over `$60`. Change with `--max-budget 50`.
- **Pay once.** Uses Databento *batch jobs*: billed once, files can be re-downloaded **free for 30 days**. If the internet drops, just run step 2 again; it resumes and does **not** pay again.
- **Every file is hash-checked** after download.
- `data/manifests/download.json` remembers which jobs were paid for. **Do not delete it** until the download is complete, or the script will think nothing was paid and quote again.

## If something goes wrong

| Message | What to do |
|---|---|
| `ABORTED: worst-case spend ...` | The quote is bigger than your budget. Don't raise the budget without understanding why. |
| `a submit was recorded but no job id was saved` | The program stopped while submitting. Open the Databento portal → Download center. If a job is there, copy its ID into `download.json`. Do **not** just run again. |
| `job ... is expired` | More than 30 days passed. Files are gone; a new job would cost again. |
| Network errors during download | Normal on flaky connections. Run step 2 again. |

## Using the data in Python

```python
from propfirm_data.convert import load_bars

bars = load_bars()
front = bars[bars["continuous_symbol"] == "CL.v.0"]
```

Use `*_ticks` columns (whole numbers, 1 tick = $0.01 = $10 per contract) for calculations, and `open/high/low/close` (dollars) for charts.

## Keep your key safe

The API key lives only in `.env` (listed in `.gitignore`). Never paste it into a chat or commit it.
