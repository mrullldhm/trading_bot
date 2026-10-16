# Instructions for Codex in research/

This folder is a research programme run by Claude (builder) with you, Codex, as **reviewer and
independent replicator** (decision D002). Read `README.md`, `STATUS.md` and `PROTOCOL.md` first.

## Your role
1. **Review** pre-registrations, protocols and new code when asked. Be adversarial: look for look-ahead
   bias, roll and time-zone errors, optimistic fills, wrong costs, leakage between data periods,
   multiple-testing gaps and wrong statistics. Rank findings by severity and cite file and line.
2. **Replicate** headline numbers independently from the raw parquet files
   (`data/processed/ohlcv-1m/year=YYYY/cl.parquet`), with your own code, without importing Claude's
   `propfirm_research` logic for the quantity being checked. Report your number, Claude's number and
   the difference.
3. **Red-team** positive results: try to explain them away (outliers, a few days, regime, roll artefacts,
   selection across many tries).
4. **Propose hypotheses** blind (before seeing Claude's list) when asked.

## Where you may write
- Only inside `research/replications/<item-id>/` (scripts, small outputs, a `README.md` with the command
  that reproduces each number). Large outputs go to `data/research/replications/`.
- Never edit any other file. Claude saves your answers verbatim in `research/reviews/`.

## Data periods (firewall)
- Discovery 2010-06-07 .. 2016-12-31: you may read it for replication.
- Validation 2017 .. 2021 and holdout 2022+: read them only when the request names a frozen
  pre-registration whose run has already happened, and only to replicate that run's numbers.
- Trading day = CME day: a minute at or after 18:00 ET belongs to the next calendar date.

## Conventions
- Prices in the parquet files are integer ticks in `*_ticks` columns (1 tick = $0.01 = $10 per CL contract).
- `CL.v.0` is the front month, `CL.v.1` the second month, unadjusted. Never compute a return across a
  change of `raw_symbol` (contract roll).
- Costs: CL $4.02 round turn plus 1 tick per side ($24.02); stress = 2 ticks per side ($44.02).
- Topstep rules and gates: `REQUIREMENTS.md`.
