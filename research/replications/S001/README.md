# S001 independent replication

This replication recomputes the five requested cells directly from the 2010-2016 raw parquet files.
It does not import `propfirm_research`. It uses only
`propfirm_backtest.orb_engine.local_tmin` and `short_days` for ET conversion and the scheduled CME
short-day calendar. Roll times and expiries are derived independently from the raw front-month rows.

From the repository root, run:

```bash
.venv/bin/python research/replications/S001/replicate.py
```

Run the mechanical DLL/MLL/consistency/bridge checks with:

```bash
.venv/bin/python research/replications/S001/verify.py
```

The command uses 20 direction draws (10 independent antithetic pairs), 1,000 Combine attempts per
draw, 50,000 synthetic Normal days and 20,000 Part-A attempts. It writes:

- `data/research/replications/S001/results.json`: full headline results, method, versions and data hash;
- `data/research/replications/S001/headline.csv`: flat headline table;
- `data/research/replications/S001/pair_metrics.csv`: the ten-pair spread diagnostics for Part B.

To rerun with more Monte Carlo attempts (never fewer than 1,000 per Part-B draw):

```bash
.venv/bin/python research/replications/S001/replicate.py --attempts 5000 --part-a-attempts 100000
```

Implementation details follow the request literally: all observed CME trading sessions remain in the
day vector; missing/invalid windows are zero days; a frequency mask is shared within each antithetic
pair; drift is applied to each bar at its start minute; DLL is applied after contract scaling and adds
one tick of liquidation loss; and G8 drawdown records the strategy-path low on the failing day.
