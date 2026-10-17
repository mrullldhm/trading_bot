# R015 — blind H025/H026 replication

Independent replication from the raw 2010–2016 CL one-minute parquet partitions. The script does not
import `propfirm_research`. It prints all headline results, eligibility/evaluation counts, and audit
invariants as JSON.

Run from the repository root:

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python research/replications/H025/replicate.py --json
```

Interpretive choices:

- A loaded trading day is any discovery-period CME trading day with at least one `CL.v.0` row. The CME
  date is the New York local date, advanced by one day for minutes at or after 18:00. Pandas' IANA
  `America/New_York` conversion supplies the historical DST rules.
- Non-eligibility reasons are mutually exclusive and assigned in definition order: scheduled short day,
  missing endpoint, mixed signal contract, missing entry, entry-contract mismatch, entry not before the
  scheduled flat. Interior signal minutes may be absent and the volume is the sum of those present.
- Scheduled flat is 16:05 ET, 12:55 on the engine's permitted scheduled short-day calendar, or five
  minutes before the exchange expiration timestamp when earlier. Short days are excluded before testing
  the H025/H026 afternoon entries. A data-driven future roll time is not inferred; contract equality is
  enforced between signal, entry, and exit so no evaluated return spans a raw-symbol change. As a tested
  alternative, the script counts raw-symbol transitions anywhere in 14:25–16:05; if present, these would
  identify cases potentially affected by treating an observed roll as a flat deadline.
- Threshold histories contain the preceding 60 H025 entry-time eligible days, including days whose exits
  later prove unevaluable and today excluded. NumPy's `method="linear"` percentile and strict `>` are used.
- `move == 0` emits no directional trade, including for the naive continuation, following the explicit
  frozen rule. The script prints the number of such eligible days so the alternative n is transparent.
- A missing-exit count means literally no exact 16:05 row among H025 eligible days. An exact row in a
  different contract is separately counted as a contract mismatch and is unevaluable.
- Block means use evaluated trades whose CME trading date falls in the inclusive named calendar block.
  The t statistic is `mean(x) / (sample_sd(x, ddof=1) / sqrt(n))` over evaluated daily gross ticks.
