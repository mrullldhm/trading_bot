# S002 independent headline replication

This replication reads only the raw discovery parquet files
`data/processed/ohlcv-1m/year=2010..2016/cl.parquet` and the permitted
`data/reference/eia_releases.csv`. It does not import `propfirm_research`. The only reused backtest
logic is `propfirm_backtest.orb_engine.short_days`, for the scheduled CME short-day calendar.

## Exact command

Run from the repository root:

```bash
.venv/bin/python research/replications/S002/replicate.py
```

The command prints the complete result and writes the same JSON to
`data/research/replications/S002/results.json`. Runtime on the replication machine was about 25
seconds.

## Method

- I assign CME trading dates in ET, advancing the date for minutes at or after 18:00. The retained
  dates are 2010-06-07 through 2016-12-31 (the last observed trading date is 2016-12-30).
- Contract identity is `raw_symbol` plus expiration month. Scheduled roll is the next contract's
  first `CL.v.0` minute floored to the hour. A day's flat timestamp is the earliest of 16:05 ET,
  12:55 on scheduled short days, expiration minus five minutes, and scheduled roll minus five
  minutes.
- A segment endpoint is the first front bar at or after the requested time, no more than five
  minutes late. Entry and exit, and every observed front bar between them, must retain one raw
  contract; the exit may equal but may not exceed the flat timestamp.
- Means and t statistics use one observation per valid trading day and the ordinary sample-standard-
  deviation standard error. Item 2 removes `x=0` exactly as requested.
- EIA calendar weeks run Monday through Sunday. A normal week has exactly one CSV row; weeks with
  multiple rows are holiday weeks and are excluded. A rule day is a normal week's Wednesday with its
  sole row at 10:30. The item 3(b') controls are Monday, Tuesday, Thursday, and Friday trading days of
  normal weeks. Close returns are attached to their ending minute and require adjacent UTC minutes,
  one contract, and one trading day. EIA means are pooled across eligible minutes.
- VR(30) uses front closes in `[08:00,16:05)` ET. Within each trading-day/contract run, the minute grid
  spans its first through last observed bar and missing closes are forward-filled. Sample variances
  are formed from pooled first and second moments. Its SE is the standard deviation of 2,000
  trading-day bootstrap estimates, seed 20261017.
- The 09:00 term-structure snapshot is the last exact timestamp shared by CL0 and CL1 in
  08:50--08:59; CL1 must expire later. Item 5 does not explicitly exclude a zero predictor, unlike
  item 2, so its headline retains zeros with `sign(0)=0`; the JSON also contains a nonzero-only
  sensitivity.

## Results

| Quantity | Independent result |
|---|---:|
| 14:30--15:00 mean; t; n | -2.202845 ticks; -5.924673; 1,617 |
| Mean by block (2010--12 / 2013--14 / 2015--16) | -2.036624 / -2.700000 / -1.923848 ticks |
| Corr(x,y); sign IC | 0.163180; 0.118635 |
| Sign edge; t; n | 2.622436 ticks; 4.684774; 1,560 |
| Sign edge by block | 4.404605 / 2.512821 / 0.489669 ticks |
| EIA absolute-return ratio to same-day 10:00--10:14 | 3.072286 |
| EIA absolute-return ratio to normal-week Mon/Tue/Thu/Fri controls | 2.712277 |
| EIA volume ratio to same-day 10:00--10:14 | 5.137892 |
| EIA volume ratio to normal-week Mon/Tue/Thu/Fri controls | 4.630184 |
| Normal-week control trading days | 1,172 |
| NY-session VR(30); day-bootstrap SE | 0.904843; 0.009594 |
| Term counts: contango / backwardation / unsynchronised | 1,315 / 299 / 71 |
| Contango sign IC; edge; n | 0.060002; 6.484553 ticks; 1,230 |
| Backwardation sign IC; edge; n | -0.019579; -1.825623 ticks; 281 |

The zero-predictor handling in item 5 is also not stated. Including versus excluding the 11 zero
overnight returns is immaterial here; the nonzero-only results are in `results.json`.
