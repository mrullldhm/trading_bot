# H028 independent replication (R019)

Run from the repository root:

```bash
.venv/bin/python research/replications/H028/replicate.py
```

That single command reproduces every number in `own_results.csv`; `run_metadata.json` records the loaded-day span,
elapsed-years denominator, and raw-return availability. The H028 script reuses only the independently written parquet,
calendar, strict-window, and BH helpers in `research/replications/H027/replicate.py`. It does not import
`propfirm_research.settlement` or `propfirm_research.grid`.

After unblinding, the item-level comparison is reproduced with:

```bash
.venv/bin/python research/replications/H028/compare.py
```

It writes `comparison.csv` and `verdict.csv`, using the tolerances documented in the H027 README. Missing Claude
fields are `N/A` and do not silently become matches.

Literal implementation choices fixed before unblinding:

- A market's 20-observation volatility history is compressed to days where that market's return exists; it uses the
  immediately preceding 20 such observations, excludes today, and uses sample standard deviation (`ddof=1`).
- CL/RB/HO require exact 14:25 and 14:34 bars. BZ uses the exact 14:25 open when present, otherwise the close of the
  last 14:22-14:24 bar; its end is the close of the last 14:32-14:34 bar.
- Entry-time eligible means all variant inputs (including causal volatility scales) exist and the CL window is
  entry-valid. For v3 this is deliberately counted before the agreement rule; “emitted signals” counts the subset on
  which RB, HO, and BZ deviations all have the same nonzero sign.
- Emitted signals include any whose strict exit is later unavailable; evaluated trades require the exact
  same-contract exit.
- The largest-day share is `max(directed gross ticks) / sum(directed gross ticks)`, not the largest absolute move.
- Contract identity and short-day/roll/expiry handling are as documented in the H027 README.
