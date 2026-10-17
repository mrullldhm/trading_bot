# S003 independent replication

This directory contains an independent implementation of the requested S003
checks.  Neither script imports `propfirm_research`.  Large/generated outputs
are written to `data/research/replications/S003/`.

## Environment and exact commands

Run from the repository root, `/home/mrullldhm/personal/propfirm`:

```bash
.venv/bin/python research/replications/S003/part1_inference.py --draws 10000
OMP_NUM_THREADS=10 OPENBLAS_NUM_THREADS=10 MKL_NUM_THREADS=10 \
  .venv/bin/python research/replications/S003/part2_mini_pipeline.py
```

The committed scripts default to seed `20261017`.  The completed run used
NumPy 2.5.4, pandas 3.0.6, PyArrow 26.0.0, SciPy 1.18.1, and scikit-learn
1.9.1.

## Part 1 conventions

- A common stationary-bootstrap index draw (geometric block length with mean 5
  days) is applied to the entire 432-strategy family.
- Romano-Wolf is a one-sided, descending step-down max-t test.  Bootstrap means
  are centered by the observed means and studentised with fixed original daily
  standard errors.  P-values use the finite-draw correction.
- Gross edge is the ratio of average daily gross P&L to average daily trade
  flags.  Its standard error uses the ratio influence series.  The max-t
  deviations use the exact ratio in each bootstrap sample and the fixed
  original standard error.  Six of 10,000 samples had no trades for at least
  one of the very sparse strategies (the sparsest has 8 trades), so those six
  undefined whole-family ratio draws were excluded from the critical-value
  quantile.
- SPA long-run standard deviations are estimated from the stationary-bootstrap
  variance of the mean.  Hansen's consistent recentering centers plausible
  candidates and leaves clearly inferior candidates with their negative drift.

Generated files:

- `part1_summary.json`: requested headline statistics.
- `part1_strategy_details.parquet`: per-strategy t-statistics, adjusted
  p-values, gross edge, and simultaneous upper bound.

The 10,000-draw run produced:

| Endpoint | Result |
|---|---:|
| Base Romano-Wolf minimum adjusted p; count below 0.05 | 0.962904; 0 |
| Stress Romano-Wolf minimum adjusted p; count below 0.05 | 1.000000; 0 |
| Gross-edge upper-bound max-t critical value | 3.645282 |
| Maximum simultaneous gross-edge upper bound | 20.354789 ticks/trade |
| Bounds below 4.402 ticks | 195 / 432 |
| Bounds below 2.402 ticks | 72 / 432 |
| Consistent SPA statistic; p-value at base cost | 2.005423; 0.896610 |

## Part 2 conventions

- CME trading day is the New York calendar date, advanced by one day for bars
  at or after 18:00 ET.  Only `CL.v.0` and trading days from 2010-06-07 through
  2016-12-31 are loaded.
- Entry and exit require the exact minute's open and the same `raw_symbol`.
  Flat means the exact 16:05 open; no later substitution is allowed.
- Every feature uses only bars timestamped before the decision minute.  An
  `h`-minute return is the last completed close minus the open of the as-of bar
  at decision minus `h` minutes, on the entry contract.  Session VWAP uses
  volume-weighted typical price.  Realised volatility is the RMS of 60
  one-minute close changes divided by the mean of the preceding 20 daily values
  at that cell.
- For each test year 2012--2016, the preceding year selects ridge alpha by
  sign-rule gross edge after fitting on still earlier years.  The final fold fit
  uses all earlier years.  The last trading day is removed at each fit boundary
  as the one-day embargo.  Median imputation and standardisation are fitted
  inside each training split.
- IC is Pearson correlation.  The sign rule trades on every nonzero prediction.
  Its t-statistic is the ordinary t of daily gross sign-rule P&L.
- Circular shifts are 61, 127, and 193 observations independently within each
  calendar year.  Planted repetitions use three return features sampled
  without replacement and independent standard-normal coefficients.

Generated files include the headline/control CSVs, selected alpha CSV, JSON
summary, and the four daily feature/target panels.  The completed run produced:

| Cell | OOS valid days | IC | Gross ticks/trade | t |
|---|---:|---:|---:|---:|
| 14:35 + 60 min | 1,216 | 0.051196 | 0.859375 | 1.803325 |
| 09:00 + 30 min | 1,271 | -0.016718 | 0.425649 | 0.469528 |
| 20:00 + 5 min | 1,163 | 0.175088 | 0.540843 | 3.273088 |

None of the three circular controls exceeded t = 3.5 (their t-statistics were
0.914515, 0.837876, and 0.010719).  All 10 planted-edge repetitions exceeded
t = 3.5, for a detection share of 1.00.

## Interpretation cautions

The simultaneous ceiling is not below stress cost for all strategies: only
195 of 432 bounds are below 4.402 ticks and the maximum bound is very wide,
driven by a sparse confidence-filtered strategy.  Thus these data do not meet
kill criterion 1.

Allowing a nominal 16:05 flat to use 16:06--16:09 is the wrong convention for a
claim explicitly defined as flat at 16:05.  This replication requires the
exact 16:05 open.  Also, the SPA objection in R010 item 2 was backwards:
Hansen-consistent recentering is the plausible-centered/inferior-unmodified
form implemented here and defended in the response to that review.
