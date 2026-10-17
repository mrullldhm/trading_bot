# H027 independent replication (R019)

Run from the repository root:

```bash
.venv/bin/python research/replications/H027/replicate.py
```

That single command reproduces every number in `own_results.csv`; `run_metadata.json` records the loaded-day span
used for trades/year. The implementation reads only the processed CL, TAS, and CL mbp-1 parquet files and does not
import `propfirm_research.settlement` or `propfirm_research.grid`.

After unblinding, the item-level comparison is reproduced with:

```bash
.venv/bin/python research/replications/H027/compare.py
```

It writes `comparison.csv` and `verdict.csv`. Counts use the requested 1% tolerance; tick-valued gross, yearly gross,
net, SD, and MDE fields use 0.1 tick; trade rate uses 1%; t uses 0.01; share uses 0.001; boolean verdicts are exact.
Missing Claude fields are `N/A` and do not silently become matches.

Literal implementation choices fixed before unblinding:

- In this processed Databento tape, `B` means buyer aggressor (+1) and `A` means seller aggressor (-1). This is the
  repository's documented conversion convention and is corroborated by the S004 reported-side/quote agreement check.
- The TAS session predicate is wall-clock `[18:00 on the prior date, 14:30 on the trading date)`; in particular,
  previous-evening records are included rather than being discarded by a naive `minute-of-day < 14:30` test.
- A day enters the 60-observation history only when its score is available and the window is entry-valid. Today is
  excluded. Zero is a valid history observation but never emits.
- The 1% coverage test uses integer lots: `100 * classified >= 99 * total`.
- A missing reported side is classified only on a strictly normal book (`bid < ask`); locked/crossed and inside-spread
  records remain unclassified.
- Entry-time eligible days are counted before warm-up and the 75th-percentile filter. Emitted signals include any
  whose strict exit is later unavailable; evaluated trades require the exact same-contract exit.
- The largest-day share is `max(directed gross ticks) / sum(directed gross ticks)`, matching the card's phrase
  “largest single-day gross P&L”; it is not the largest absolute observation.
- Scheduled short days use the repository's documented CME holiday definition. Contract identity is
  `raw_symbol@expiration-month`; scheduled roll is the next contract's first front minute floored to the hour.
- `A`/`B` records take precedence over the quote fallback, as the card specifies. A normal outright window containing
  no trade is treated as an available zero score.
