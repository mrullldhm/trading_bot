---
id: D000
title: Programme charter (the approved founding plan)
status: decided
decided: 2026-10-16
approver: owner
updated: 2026-10-16
---

> Verbatim copy of the plan the owner approved on 2026-10-16 (planning session, Claude + Codex consult).
> Later changes are made by new decision records, never by editing this file.

# Plan: CL strategy research programme in `research/`

## Context

- 8 strategies (EMA x VWAP, ORB, ZAB, Crabel, Fisher ACD, VWAP Break, Momentum Pullback, Pine momentum),
  ~1.39M configs on 2010-2021: **0 passed the gates**. The audit proved the failures are real.
- Why: (1) entry signals do not beat random entries out of sample; (2) costs eat $20-45/trade edges;
  (3) 1 CL puts every champion's p95 60-day drawdown at $2,300-3,100 vs the $1,000 gate (G8).
- Failed method: *pick a known setup -> big parameter grid -> gates*. Big grids manufacture luck
  (ACD: best of 2,880 in-sample, then -$27/trade vs random entries on 2022+).
- User wants: deep, data-driven research on 16 years of CL 1-min data, Claude + Codex together, recorded
  in `research/` so any new session resumes from that folder, until a strategy meets the requirement and
  is profitable, or the evidence says this data cannot produce one.

## Decisions already made

| ID | Decision | By |
|---|---|---|
| D002 | Codex = reviewer + independent replicator; Claude builds | user |
| D003 | Gates stay the official bar. G8 scales to 50% of each account's MLL ($1,000 / $1,500 / $2,250). After S001, if G8 looks too strict, Claude brings a written proposal with numbers (Codex's candidate: upper-bound P(fail before pass) < 1% with stressed costs + $500 reserve, dips still reported). Nothing changes without user approval | user |
| D004 | Sizing: CL only (1 CL on 50K; 100K / 150K Combines may use more CL within Topstep's CL limit). No micros (MCL) | user |
| D005 | Topstep Daily Loss Limit modelled as a hard rule in every simulation: 50K $1,000 / 100K $2,000 / 150K $3,000 (hit = positions liquidated, no trading until next session, account not failed). Bot's own daily stop sits inside it. Sources disagree on whether the DLL is active on current TopstepX accounts; modelled ON regardless (conservative) | user; amounts from Topstep help center |
| D001 | Data periods + firewall (below) | Claude + Codex agree |

## Big picture: evidence first, strategy last

Doctor analogy: tests first, diagnosis second, prescription last. Strategies 1-8 prescribed first.

1. **Feasibility first (S001):** exact Combine odds per account, sizing, Sharpe, DLL -> a numeric target.
2. **Measure predictability before building (S002 atlas, S003 ceiling)** on discovery data only. If the
   best regularised out-of-sample predictor cannot beat costs anywhere, no rule on the same inputs can.
3. **Hypotheses need a reason:** economics + literature + exact definition -> explore on discovery ->
   ONE pre-registered validation run (Codex reviews the pre-registration first, blocking).
4. **Diversify across the day:** non-overlapping intraday windows are close to uncorrelated, so several
   small validated edges can reach a portfolio Sharpe no single one reaches (~ SR x sqrt(k) if independent).
5. **One final holdout look**, then the practice account (the only truly unseen data).
6. **No more indicator grids on the same bars** (Codex rule, adopted).

### Feasibility preview (rough Gaussian Monte Carlo with DLL, run read-only during planning)

SR = annual after-cost Sharpe; sigma = daily P&L std. 250 days, EOD trailing MLL, intraday low via Brownian
bridge, 55% consistency, DLL cap. Real CL P&L is fat-tailed, so reality is worse. 1 CL reference: one
60-minute trade ~ 40-50 ticks std ~ $400-500, so sigma $150/day means trading selectively or briefly.

| Account (G8) | SR | sigma/day | pass % | fail % | median days | p95 60d DD | G8 |
|---|---|---|---|---|---|---|---|
| 50K ($1,000) | 2 | 300 | 63 | 37 | 42 | 3,599 | no |
| 50K | 3 | 150 | 96 | 3 | 93 | 1,537 | no |
| 100K ($1,500) | 3 | 300 | 90 | 9 | 90 | 3,087 | no |
| 100K | 4 | 150 | 95 | 0 | 150 | 1,324 | yes |
| 150K ($2,250) | 2 | 300 | 62 | 8 | 168 | 3,652 | no |
| 150K | 3 | 300 | 89 | 2 | 140 | 3,065 | no |
| 150K | 4 | 150 | 61 | 0 | 204 | 1,333 | yes |

Takeaways: every workable row needs after-cost SR >= ~2-3 (none of strategies 1-8 came close out of
sample); with 1 CL, G8 passes only at low daily sigma on 100K/150K; bigger accounts cut fail rates but are
slower (target/MLL = 1.5 on 50K, 2.0 on 100K/150K); G8 rejects rows with ~2% fail rates -> D003 review.

## `research/` layout (lab notebook; user commits it manually)

```
research/
├── README.md        entry point: goal, one-line status, "Start here" resume steps, folder map
├── CLAUDE.md        auto-loaded when Claude reads research/: resume steps + hard rules (-> PROTOCOL)
├── AGENTS.md        same rules for Codex (Codex reads AGENTS.md)
├── STATUS.md        living dashboard: phase, active item, next 3 actions, waiting-on-user, budgets used
├── PROTOCOL.md      method: periods + firewall, item lifecycle, statistics, multiple testing,
│                    pre-registration, Claude/Codex workflow + how to call Codex, approvals, checklists
├── REQUIREMENTS.md  success definition: Topstep rules per account (verified dates), gates G1-G9 + V1-V9
│                    exactly as coded (file:line), cost model, DLL, feasibility target zone (S001)
├── KNOWLEDGE.md     CL facts graded CONFIRMED / VALIDATED / EXPLORATORY / REFUTED, each with a source link
├── LEDGER.csv       append-only, written by code: every run, period touched, n tests, stat, p, verdict, hashes
├── HOLDOUTS.md      every holdout look so far (EMA, ACD, VWAP Break touched 2022+) + programme status
├── INDEX.md         generated table of all items (id, title, status, updated, link)
├── hypotheses/  BACKLOG.md, _template.md, H###-<slug>/{card.md, prereg.json, result.json}
├── studies/     _template.md, S001-feasibility/, S002-atlas/, S003-ceiling/ (report.md + small tables)
├── strategies/  later: specs + backtests of strategies built from validated hypotheses
├── decisions/   D001..D005 above, then new ones (context, options, decision, why, approver, date)
├── journal/     YYYY-MM-DD-NN.md per session: goal, done, results, decisions, next, files, commit msg
├── reviews/     R###-<topic>.md: Codex output verbatim + Claude response + resolution table
├── replications/ Codex-only: its independent scripts + outputs
├── literature/  REFERENCES.md: papers, key numbers, which hypothesis each feeds
└── prior-work/  STRATEGIES-1-8.md: hypotheses, trial counts (1,389,977), lessons, report paths
```

**Resume protocol** (README + CLAUDE.md): read STATUS -> PROTOCOL -> newest journal -> active item.
A new session only needs: "continue the research in /home/mrullldhm/personal/propfirm/research".
**End of session:** update STATUS, write journal, check ledger rows, update BACKLOG/KNOWLEDGE, regenerate
INDEX, propose a conventional commit message (user commits; no AI attribution lines).

## Research flow

```
idea -> card (rationale, literature, exact causal definition)
     -> explore on DISCOVERY (logged, n variants counted)
     -> prereg.json (hashes, test, power/MDE, stopping rule) -> Codex review (blocking)
     -> ONE validation run -> Codex replication -> VALIDATED / REJECTED
     -> strategy (simple rules, CL sizing, DLL, flat 16:05 ET) -> portfolio -> gates
     -> ONE holdout look (user approval) -> practice account
```

**Data periods (D001)** - split by CME trading day, not UTC timestamp:

| Period | Trading days | Use |
|---|---|---|
| Discovery | 2010-06-07 .. 2016-12-31 (~6.5 y) | atlas, ceiling, idea shaping; unlimited, logged looks |
| Validation | 2017 .. 2021, purged expanding walk-forward, one fold per year (fixed rules = one OOS test) | one pre-registered family test per hypothesis |
| Quasi-holdout | 2022-01-01 .. data end (~4.8 y) | one pre-registered test of the final portfolio; user approval |
| Forward | practice account | >= 8 weeks (Codex recommends 3-6 months) |

Why: chronological = tests persistence like real deployment; both early periods hold a crash and calm
years; Claude and Codex chose the same discovery window independently. "Quasi" because 3 earlier tests
touched 2022+. Known decay risk (strategy edges faded after 2015): discovery reports 2015-16 separately
and requires the effect there too.

**Statistics rules:**
- Unit of inference = trading day (day-clustered or Newey-West); intraday bars are not independent.
- Discovery atlas: BH-FDR q-values, exploratory only. Ceiling + validation families: Romano-Wolf max-t
  (stationary bootstrap); best-of-candidates selection: Hansen SPA / White Reality Check. DSR, PBO secondary.
- Validation: one-sided family alpha 0.01, budget 25 families programme-wide (<= 0.25 expected false
  positives; the holdout catches the rest). Two-stage like the ACD test: skill vs the right null
  (matched random entries / same-day random minutes / zero), then net profit at CL costs.
- Power check before any validation run (Codex numbers: full sample detects SR ~0.7; 5-year validation
  ~1.4 at 80% power; confirmation ~1.2-1.7). Underpowered ideas are tested only as a pre-registered bundle.
- Costs: CL $4.02 round turn + 1 tick/side ($24.02), stress +1 tick/side ($44.02). Ambiguous minutes
  resolved against us. Flat 16:05 ET (live bot plan; Topstep hard close 16:10). EIA block rule per prereg.
- **Firewall is technical:** the research loader refuses validation/holdout days without a registered
  prereg (holdout also needs `approved_by_user` and writes an opened marker before loading), and logs
  every access to LEDGER.csv.

## Code: new package `propfirm_research/` (never edit hashed modules)

Editing bars.py, propsim.py, search.py, orb_engine.py, orb_search.py, orb_holdout.py, eia_calendar.py or
config.py voids 6 unopened frozen holdouts (orb_search.py:61). Import and wrap only. Numba `cache=False`.

| Module | Job | Reuses |
|---|---|---|
| `periods.py` | period table by trading day, firewall checks | trading-day rule of `bars.py:49-52` |
| `data.py` | `load_front/load_second(period, item_id, purpose, prereg=None)`: parquet read with CL.v.0/CL.v.1 filter (~0.2 s), trading-day clip, warm-up from earlier days only, ledger row | `propfirm_data.config.BARS_DIR`, `bars.contract_key` |
| `grid.py` | decision-time grid: next-minute-open entry, forward prices per horizon, MFE/MAE, truncation at 16:05 / roll cutoff / expiry / gaps, EIA flags | `orb_engine.local_tmin`, `session_end`, `short_days`, `eia_blocks`, `CMEHolidays` |
| `features.py` | causal features: multi-window returns, realised vol vs time-of-day norm, range position, gap, relative volume, VWAP distance, weekday, EIA day, days to expiry, CL1-CL2 slope | `orb_features.Sessions`, `indicators.vwap_minutes` |
| `stats.py` | day-clustered t, Newey-West, stationary bootstrap, Romano-Wolf, SPA, BH, power/MDE, variance ratio (stdlib `NormalDist`, no scipy) | `audit.clustered`, `acd_signal_holdout.randomization_p`, `family_program.holm`, `orb_search.deflated_sharpe/pbo_cscv`, `family_holdout.bootstrap_means` |
| `costs.py` | CL round-trip cost by slippage ticks | `propsim.py:18-19` constants |
| `combine.py` | parameterised Combine sim: 50K/100K/150K MLL + target + 55% consistency + DLL + G8 at 50% MLL; day-level DLL (minute-level DLL in later strategy engines). Test: equals `propsim.pass_probability` at 50K, DLL off | `propsim.daily_series`, `trade_stats`, `vwap_break_engine.apply_dll` logic |
| `ledger.py` | append to `research/LEDGER.csv`; validation/holdout rows require a prereg hash | hashing pattern of `acd_signal_holdout.py:60-93` |
| `index.py` | regenerate `research/INDEX.md` from card/study/decision front-matter | - |
| `studies/s00N_*.py` | `python -m propfirm_research.studies.s00N` -> `research/studies/S00N/report.md` | above |

Big outputs -> `data/research/` (gitignored). Tests `tests/test_research_*.py`: firewall refusal + access
logging, static scan (no parquet/`load_bars` reads outside `data.py`), trading-day boundaries, grid
truncation + look-ahead cut test (reuse `tests/test_orb_engine.random_market`), known-answer stats,
combine equivalence + DLL behaviour, ledger guards. scikit-learn (pinned) added only at S003.

## First studies

- **S001 Feasibility frontier.** Grid: account (50K/100K/150K) x CL count (1 .. Topstep CL limit) x SR x
  trades/day x hold, fat-tailed day P&L bootstrapped from discovery random-entry returns, DLL on. Output:
  pass %, fail %, median days, p95 60d DD vs G8, DLL-hit days, fees per pass; required gross edge (ticks)
  per decision time and hold. Feeds REQUIREMENTS target zone and the D003 proposal.
- **S002 Market atlas (discovery).** Vol / volume / mean return by half-hour, session, weekday with
  day-clustered t and year stability; variance ratios per window; segment-to-segment predictability
  (overnight -> day, rest-of-day -> last half-hour, pre/post EIA, day t -> t+1); event windows (09:00,
  Wed 10:30, 14:28-30 settlement, London open); term-structure regimes; roll/expiry weeks; tails; liquidity
  by time (slippage realism).
- **S003 Predictability ceiling (discovery; Codex design merged).** Pre-declared decision times 20:00,
  03:00, 08:00, 09:00, 10:35, 12:00, 14:00, 14:35 ET; horizons 5/15/30/60/120 min and to 16:05; models:
  zero, ridge, elastic net, shallow boosted trees; nested expanding walk-forward, horizon-length purge,
  1-day embargo. Primary output: cross-fitted net P&L at 1 and 2 ticks/side, max-t corrected. Controls:
  block-shuffled labels, random features, a deliberately leaked feature, planted edges of 1/2/4/8 net
  ticks (power), negative-control times.

**Kill criteria (Codex, adopted):** CL-on-OHLCV is declared not viable if (1) the ceiling's simultaneous
95% upper bound is below stress break-even everywhere, (2) the pipeline detects planted 4-8 tick edges
with >= 80% power, (3) no hypothesis family survives validation + holdout, (4) no candidate passes the
gates. Then decision D-next with the user: new information (EIA/API surprise data, trades/depth,
cross-energy markets) or other markets / slower horizons, or stop.

## Hypothesis backlog (merged Claude + Codex; source tag)

| ID | Hypothesis | Source | Prior |
|---|---|---|---|
| H001 | Return prior settlement -> 14:00 predicts 14:00-14:30 and -> 16:05 | Baltussen et al. 2021 JFE; Gao et al. 2018 (Claude) | A |
| H002 | EIA days: 10:30-11:00 return predicts last half-hour; other days: first half-hour / overnight part | Wen, Indriawan, Lien, Xu 2023 EJ (Claude) | A |
| H003 | Post-EIA: 10:30-10:35 direction with top-decile volume -> 11:30 (continuation vs fast reversal) | Ederington & Lee 1993; Li & Geman 2018 (both) | A |
| H004 | Term-structure-conditioned momentum: CL1-CL2 slope x 5/20-day return at 09:00 -> 16:05 | Gorton, Hayashi, Rouwenhorst 2013 (Codex) | A |
| H005 | Overnight handoff: 18:00-09:00 return by volume + term structure -> 09:00-12:00 | Wen 2023 (both) | B |
| H006 | Settlement-to-close reversal: fade 14:25-14:35 abnormal move at 14:35 -> 16:05 | Codex | B |
| H007 | Vol-conditioned continuation vs reversal (30-min return x realised-vol percentile) | Gao 2018 (both) | B |
| H008 | Volume-shock continuation at hourly marks 09:00-14:00 | liquidity vs information (both) | B |
| H009 | Post-US-close order-imbalance reversal in Asia/London | Boyarchenko, Larsen, Whelan, NY Fed (Claude) | B |
| H010 | Noise-area intraday momentum, untested on futures | Zarattini, Aziz, Barbon 2024 (Claude) | B |
| H011 | Multi-day trend sign (1/5/20 d) at 09:00 -> 16:05 | Moskowitz, Ooi, Pedersen 2012 (both) | B |
| H012 | Stable drift in specific half-hours | S002 atlas (Claude) | C |
| H013 | Calendar x regime cells at pre-selected times (max-t over 20 cells) | Codex | C |
| H014 | Same half-hour on prior days predicts today | Heston, Korajczyk, Sadka 2010 (Claude) | C |
| H015 | Front-second spread dislocation (2 CL legs = double cost) | Codex | C |
| H016 | Roll-window pressure reversal (within-contract only) | Mou 2011 (both) | C |

## Claude + Codex workflow (D002)

- **Claude:** pre-registrations, canonical implementation, locked ledger, reports, all docs.
- **Codex** (via `codex:codex-rescue` agent; results fetched with `codex-companion.mjs result <job>`):
  blind hypothesis generation per phase; blocking review of every pre-registration; adversarial review of
  each new module; independent reconstruction of every headline number from raw parquet with its own
  pipeline in `research/replications/` (roll / time-zone / fill / cost logic, hand-checked trades,
  stats, Combine sims); red team of any positive result. Writes only in `research/replications/`.
- Neither changes a spec after seeing validation or holdout results; both publish PASS/FAIL
  independently; a finding is VALIDATED only if the numbers match. All Codex output saved verbatim in
  `research/reviews/` (its planning proposal = R001).
- User approves: gate changes, data purchases, holdout openings, new dependencies, anything touching
  money/orders.

## Roadmap

| Phase | What | Exit | Kill / escalate |
|---|---|---|---|
| A Setup | scaffold, protocol, prior work, ledger seed, toolkit + tests | tests green; Codex R002 (protocol) + R003 (code) resolved | - |
| B Feasibility | S001 | target zone in REQUIREMENTS; D003 proposal decided by user | - |
| C Atlas | S002 | KNOWLEDGE populated; backlog re-ranked | - |
| D Ceiling | S003 | cells worth testing named | kill criteria |
| E Hypotheses | explore -> prereg -> one validation run each | validated signals reach target SR as a bundle | budget of 25 spent |
| F Portfolio | simple rules, CL sizing, DLL, Topstep limits, all gates | G1-G9 + V1-V4 pass | - |
| G Holdout | one pre-registered look, user approval | V5-V9 + G8 pass | fail: back to E, new ideas only |
| H Practice | forward test | live matches backtest | - |

## This session's execution order (each step leaves STATUS consistent, so any stop resumes cleanly)

1. Delete the stray untracked 10-byte file `research` (content `2research`, created today 15:56); build
   the `research/` tree and all docs: README, CLAUDE.md, AGENTS.md, STATUS, PROTOCOL, REQUIREMENTS (gates
   copied from code; Topstep rules per account incl. DLL; consistency % re-verified since sources say 50
   or 55; CL-only cost model; sources + dates), KNOWLEDGE (seeded from the audit and reports, graded),
   LEDGER.csv (prior work: 1,389,977 configs, 2022+ touches), HOLDOUTS, BACKLOG, templates, D001-D005,
   this approved plan as `decisions/D000-charter.md`, prior-work, literature, journal; Codex proposal = R001.
2. Codex review of PROTOCOL + REQUIREMENTS + periods (R002); resolve findings.
3. Build `propfirm_research` core + tests; `python -m pytest -q` green (old + new); production-eng gate;
   Codex adversarial review (R003); fix.
4. S001; Codex replicates headline numbers (R004); write target zone; bring the D003 proposal to the user.
5. S002; Codex replicates 3-5 headline numbers (R005); update KNOWLEDGE + BACKLOG.
6. S003 if time allows (add scikit-learn), otherwise it is the STATUS "next action".
7. Save project memory pointing at `research/README.md` (+ D002-D005); final journal, STATUS, INDEX;
   suggest commit messages.

## Verification

- `python -m pytest -q`: all existing tests + new `test_research_*` pass.
- Firewall: validation/holdout reads without prereg raise; every read writes a ledger row; static scan test.
- `combine.py` equals `propsim.pass_probability` at 50K settings (DLL off); DLL tests cap day loss correctly.
- S003 controls: shuffled labels stay inside the null band; planted 4-8 tick edges are recovered.
- Codex replications match headline numbers within tolerance (recorded in `research/reviews/`).
- Hashed files untouched: `git diff --stat` shows no change to the 8 hashed modules; frozen holdout
  preflight hashes still match.
- Resume dry run: reading only README -> STATUS gives the exact next action.
