# Research protocol

The rules of the programme. Changing a rule needs a decision record in `decisions/` (and the owner's
approval when it touches gates, data, money or the holdout). Version history is the git log of this file.

Contents: 1 Principles · 2 Data periods and firewall · 3 Items and lifecycle · 4 Statistics ·
5 Pre-registration · 6 Requirements · 7 Claude and Codex · 8 Owner approvals · 9 Code conventions ·
10 Session checklists · 11 Glossary

---

## 1. Principles

1. **Measure before building.** Studies first, hypotheses second, strategies last.
2. **Every look counts.** Every analysis that touches market data is logged in `LEDGER.csv`, including
   the ones that "didn't work". The number of tries decides how much luck to expect.
3. **A reason before a test.** A hypothesis needs an economic story (who loses money to us, and why it
   does not get arbitraged away) and an exact, causal definition before it is tested.
4. **One shot per hypothesis on validation data, one shot per programme on the holdout.**
5. **Simple beats clever.** Few parameters, fixed in advance. No more grids over indicator settings on
   the same bars (D000): 1.39 million configurations already showed where that leads.
6. **Two independent pairs of eyes.** Claude builds; Codex reviews and replicates (D002).
7. **Negative results are results.** A clean "no edge" is recorded with the same care as a success.

---

## 2. Data periods and firewall

Decision [D001](decisions/D001-data-periods.md).

| Period | CME trading days | What it is for | Access |
|---|---|---|---|
| **Discovery** | 2010-06-07 .. 2016-12-31 (~6.5 years) | atlas, ceiling, shaping hypotheses; unlimited looks, all logged | `load_front("discovery", item_id, purpose)` |
| **Validation** | 2017-01-01 .. 2021-12-31 (5 years) | one pre-registered test per hypothesis family | `load_front("validation", item_id, purpose, prereg=path)`; the prereg must be frozen and in the ledger |
| **Holdout** ("quasi") | 2022-01-01 .. data end (~4.8 years) | one pre-registered test of the final portfolio | as validation, plus `approved_by_user: true` in the prereg; an opened marker is written before any data loads |
| **Forward** | practice account | the only truly unseen data | at least 8 weeks; Codex recommends 3-6 months |

- **Trading day** = CME day. A minute at or after 18:00 ET belongs to the next calendar date
  (same rule as `propfirm_backtest/bars.py:49-52`). Periods are cut by trading day, never by UTC timestamp.
- **Warm-up** may read earlier periods (the past is always allowed), never later ones, and only to
  initialise causal state (moving averages, lookback features). Nothing is *fitted* on warm-up rows of
  another period (R002).
- **Validation as walk-forward.** For a fixed rule (no fitted parameters) validation is a single
  out-of-sample test over 2017-2021. For a fitted model, refit once per fold year (2017, 2018, ..., 2021)
  on earlier trading days only, predict the fold year, then test the pooled out-of-fold results once.
  **Purge rule (R002):** a training observation is kept only if its label ends at least one full trading
  day before the fold's first trading day (`label_end < test_start − 1 trading day`); scalers, thresholds
  and feature transforms are fitted on training rows only.
- **Portfolio rule frozen in advance (R002).** Before the first validation run, a deterministic rule for
  building the portfolio from validated signals (membership, weights, sizing per account) is written in a
  decision record. Validation results may decide *which* signals pass, never *how* they are combined.
- **Why "quasi" holdout.** 2022+ was already used by the strategy 1 holdout, the ACD signal test and the
  strategy 6 out-of-sample run ([HOLDOUTS.md](HOLDOUTS.md)). It is still clean for *new* hypotheses, but
  it is not untouched data. That is why the practice account is mandatory.
- **Decay guard.** Strategy edges in 2010-2021 faded after 2015. Discovery results are always reported
  for 2015-2016 separately, and an effect that is absent there is not promoted.
- **The firewall is code, not trust.** `propfirm_research.data` refuses validation or holdout days
  without a frozen pre-registration and logs every read to `LEDGER.csv`. A test scans the package for any
  other way of reading bar files.

---

## 3. Items and lifecycle

| Prefix | Item | Lives in | Template |
|---|---|---|---|
| S### | Study (descriptive or diagnostic, no trading claim) | `studies/S###-slug/report.md` | `studies/_template.md` |
| H### | Hypothesis (a falsifiable claim about returns) | `hypotheses/H###-slug/card.md` (+ `prereg.json`, `result.json`) | `hypotheses/_template.md` |
| D### | Decision record | `decisions/D###-slug.md` | `decisions/_template.md` |
| R### | Codex review or replication report | `reviews/R###-slug.md` | `reviews/_template.md` |
| P### | Prior-work ledger entry (strategies 1-8) | `LEDGER.csv` only | - |

Every Markdown item starts with a small front-matter block (`id`, `title`, `status`, `updated`) so that
`python -m propfirm_research.index` can rebuild `INDEX.md`.

**Hypothesis states**

```
idea ─► spec ─► explored ─► preregistered ─► validated ─► in-strategy
  │       │         │             │             └─► (replication mismatch) ─► investigating
  └───────┴─────────┴─────────────┴─► rejected / parked (with the reason written in the card)
```

- `idea`: one line in `BACKLOG.md`.
- `spec`: a card with rationale, literature and an exact causal definition.
- `explored`: discovery results written in the card, with every variant tried counted in the ledger.
- `preregistered`: `prereg.json` frozen after Codex review.
- `validated` / `rejected`: after the one validation run and Codex's replication.

**Study states:** `planned` → `running` → `done` (or `abandoned`, with the reason).

---

## 4. Statistics

### 4.1 Unit of inference
The trading day. Minutes and bars inside one day are not independent, so standard errors are
day-clustered (`propfirm_backtest/audit.py:616`) or Newey-West with a lag at least the holding period.

### 4.2 Nulls: pick the one that matches the claim (written in the prereg)

| Code | Null | Use for |
|---|---|---|
| N1 | net mean P&L per trade = 0 at the stated costs | "this makes money" (always tested, second) |
| N2 | the signal is no better than matched random entries (same ET minute and side, distinct days within ±20 trading days, exclusive controls, as in `acd_signal_holdout.py`) | timing claims ("entering when X beats entering at that minute anyway") |
| N3 | the signal is no better than random minutes on the same days | time-of-day claims |
| N4a | block-shuffled labels (stationary bootstrap, mean block 5 days) | predictive models and the ceiling study |
| N4b | sign-flipped targets | only when the prereg justifies symmetry of the return distribution |

**One combined claim per variant (R002).** Each variant in a family is tested on one combined statistic
that must show both skill (against its N2/N3/N4 null) and net profit (N1 at stated costs), e.g. the
minimum of the two standardised statistics; Romano-Wolf is applied to that combined statistic across every
variant of the family. Selecting variants on stage 1 and then testing N1 only on the survivors is not
allowed (it inflates error). A family is one hypothesis card with at most 4 pre-declared variants; it
cannot be split or merged to save budget.

### 4.3 Multiple testing, by tier

| Tier | Where | Method |
|---|---|---|
| Exploratory | S002 atlas, discovery exploration in cards | Benjamini-Hochberg q-values across every test in that study; q < 0.10 means "worth a closer look", nothing more |
| Families | S003 ceiling cells; the variants inside one prereg | Romano-Wolf max-t step-down with a stationary bootstrap (mean block 5 days); family-wise error |
| Selection | picking the best of several candidates | Hansen SPA (or White Reality Check) |
| Validation | one prereg = one family | one-sided family alpha **0.01**; **budget 25 families** programme-wide (at most 0.25 expected false positives if every idea were wrong) |
| Holdout | the final portfolio | one pre-registered test, no multiplicity; criteria in REQUIREMENTS §4 |
| Diagnostics | everywhere | deflated Sharpe (with the programme's trial count from LEDGER) and PBO, reported but never sufficient |

### 4.4 Promotion from discovery to pre-registration
All of these, written in the card:
1. q < 0.10 in the discovery exploration;
2. same sign in at least 2 of 3 discovery blocks (2010-2012, 2013-2014, 2015-2016), including 2015-2016;
3. P&L per trade at the planned hold stays positive after **stress** costs (2 ticks per side, $44.02 per
   CL round trip), i.e. the gross edge exceeds $44.02;
4. an economic rationale;
5. a power check (4.5) that says the validation test can see it.

### 4.5 Power
Before spending a validation family, compute the minimum detectable effect (MDE) at 80% power for the
planned sample. Rule of thumb: the 5-year validation sample detects an annual Sharpe of about 1.4 at
one-sided alpha 0.01; the full 16 years about 0.7; the holdout about 1.2-1.7. If the MDE is larger than
half the discovery effect, the idea is **parked** (R002: bundling it with others does not create power).
It may come back only as part of a justified aggregate endpoint (e.g. a pre-declared portfolio of signals)
that has its own power calculation.

### 4.6 Costs, fills and Topstep mechanics (D004, D005)
- CL only: $4.02 round-turn fee + 1 tick slippage per side = **$24.02** per round trip (base);
  **stress** = 2 ticks per side = $44.02; diagnostics at 3-4 ticks.
- Market entry = next minute's open + slippage. Ambiguous minutes resolve against us. Targets need a
  1-tick trade-through (fill rules of `propfirm_backtest/orb_engine.py:273-340`).
- Flat by **16:05 ET** (the live bot's plan; Topstep's hard close is 16:10 ET), 12:55 ET on CME short
  days, 5 minutes before expiry; never hold across a contract roll.
- Exits fill at the open of the bar that starts exactly at the exit minute, never a later bar; a missing
  exit bar makes the window invalid and is counted in the report (D009, 2026-10-17).
- Combine simulations use `propfirm_research.combine` with the account's MLL, target, 55% consistency
  rule and **Daily Loss Limit switched on**. G8 is `combine.gate_g8` (D006): on the stress-cost daily
  series with a $500 reserve, pass >= 50% and the upper 95% bound of P(fail) <= 10%. The old D003 rule
  (p95 60-day drop <= 50% of the MLL) is reported as the diagnostic `dd_d003_ok`, never used as the gate.

### 4.7 Kill criteria for the whole programme
Adopted from Codex (R001). CL-on-OHLCV is declared not viable when all four hold:
1. the S003 ceiling's simultaneous 95% upper bound is below stress break-even at every decision time and
   horizon;
2. the same pipeline detects planted edges of 4-8 net ticks with at least 80% power (so a real edge
   would have been seen);
3. no hypothesis family survives validation and the holdout;
4. no candidate passes the gates.
Then the owner decides (decision record): new information (EIA/API surprise data, trades or order-book
data, other energy contracts), other markets or slower horizons, or stop.

---

## 5. Pre-registration

A frozen JSON file, `hypotheses/H###-slug/prereg.json`, written by `propfirm_research.prereg` and never
edited. Fields (extending `data/backtests/acd/signal_holdout_prereg.json`):

| Field | Meaning |
|---|---|
| `item_id`, `registered_utc` | which hypothesis, when frozen |
| `claim` | one falsifiable sentence |
| `period` | `validation` or `holdout` |
| `null_stage1`, `test_stage1` | N2/N3/N4 and the exact test (randomization, Romano-Wolf, ...) |
| `test_stage2` | N1 at stated costs (day-clustered one-sided t) |
| `alpha_one_sided` | 0.01 for validation |
| `family` | every variant tested together (e.g. 2-3 horizons) and the multiplicity method |
| `signal`, `entry`, `exit`, `filters`, `sizing` | the exact causal rules |
| `decision_times_et`, `horizons_min` | when and how long |
| `fee_usd`, `slip_ticks`, `stress_slip_ticks` | costs |
| `min_signals`, `inconclusive_rule` | what counts as too little data |
| `power_mde` | the MDE computed before freezing |
| `seed`, `n_permutations` / `n_bootstrap` | reproducibility |
| `code_sha256`, `data_sha256`, `environment` | hashes of the code and data files, library versions |
| `codex_review` | the `R###` id of the blocking review |
| `approved_by_user` | holdout only |
| `stopping_rule` | "one run; never re-run, extended or re-registered" |

**Procedure:** Claude drafts the prereg section of the card → Codex reviews (R###) → Claude resolves the
findings → `python -m propfirm_research.prereg register <item>` freezes the JSON and writes a ledger row →
`run` executes once and writes `result.json` and a ledger row → Codex replicates → the card gets the verdict.

---

## 6. Requirements

What a strategy must achieve: [REQUIREMENTS.md](REQUIREMENTS.md) (Topstep rules per account, gates
G1-G9 and verdict checks V1-V10 exactly as coded, costs, the feasibility target zone).

---

## 7. Claude and Codex

Decision [D002](decisions/D002-claude-codex-roles.md): author and editor, plus an independent replicator.

| | Claude | Codex |
|---|---|---|
| Builds | specs, pre-registrations, `propfirm_research` code, studies, reports, all docs, the ledger | nothing in the main code |
| Checks | its own tests | blocking review of every prereg; adversarial review of every new module; red team of positive results |
| Replicates | - | every headline number, from raw parquet, with its own code in `research/replications/<item>/` |
| Proposes | hypotheses | hypotheses, blind, at the start of each phase |

Rules:
- Never both editing the same file. Codex writes only in `research/replications/`.
- Neither changes a spec after seeing validation or holdout results. Both publish PASS/FAIL independently.
- A finding is VALIDATED only when Claude's and Codex's numbers match within the stated tolerance.
- Disagreements are resolved against the pre-registration; if still open, the owner decides. The
  resolution goes in the review file.

**How to call Codex (from Claude Code):**
1. Use the Agent tool with `subagent_type: "codex:codex-rescue"`. Start the prompt with
   `READ-ONLY review, no edits.` for reviews, or `WRITE only under research/replications/<item>/.` for
   replications. Point it at `research/AGENTS.md`.
2. The forwarder starts a Codex job and returns a job id. Fetch the answer with
   `node ~/.claude/plugins/cache/openai-codex/codex/<version>/scripts/codex-companion.mjs result <job-id>`
   (`status <job-id>` shows progress; `ls ~/.claude/plugins/cache/openai-codex/codex/` gives the version).
3. Save the answer verbatim as `reviews/R###-slug.md` using `reviews/_template.md`, then add Claude's
   response and a resolution table.

---

## 8. Owner approvals

The owner (not Claude, not Codex) decides:
- any change to a gate or to the gate policy (D003);
- buying data;
- opening the holdout (the prereg needs `approved_by_user: true`);
- adding a dependency to `requirements.txt`;
- anything touching money, orders, position sizing in a live account, or API keys;
- deleting research records.

---

## 9. Code conventions

- New code goes in the `propfirm_research/` package at the repo root; tests in
  `tests/test_research_*.py`, synthetic data only, no network.
- **Never edit these files.** Their SHA-256 hashes are frozen inside six unopened holdouts (orb, zab,
  crabel, momentum, momentum2, ema_vwap_v2); an edit makes their holdout refuse to run
  (`orb_search.py:61`):
  `propfirm_backtest/bars.py`, `propsim.py`, `search.py`, `orb_engine.py`, `orb_search.py`,
  `orb_holdout.py`, `propfirm_data/eia_calendar.py`, `propfirm_data/config.py`, and the data files
  `data/reference/eia_releases.csv` and `data/processed/definitions/cl_contracts.parquet` (do not
  regenerate them). Import and wrap instead.
- numba functions in new modules use `cache=False` (the disk cache can miss upstream edits).
- Every study is runnable as `python -m propfirm_research.studies.<module>` and writes its report to
  `research/studies/S###-slug/` and a ledger row. Large files go to `data/research/`.
- Reports state the command, the code hash and the data hash that produced them.

---

## 10. Session checklists

**Start**
1. Read STATUS, PROTOCOL, the newest journal entry, the active item.
2. `python -m pytest -q` (note the result).
3. `git status --short` (note uncommitted research files from last time).

**End**
1. `STATUS.md`: phase, active item, next actions, waiting-on-owner, budgets.
2. `journal/YYYY-MM-DD-NN.md`: goal, what was done, results with links, decisions, problems, next
   actions, files changed, suggested commit message.
3. Every run has its ledger row.
4. `hypotheses/BACKLOG.md` and `KNOWLEDGE.md` updated if anything changed.
5. `python -m propfirm_research.index` to rebuild INDEX.md.
6. Tests green.
7. Suggest a conventional commit message (`docs: ...`, `feat: ...`); the owner commits.

---

## 11. Glossary

| Term | Plain meaning |
|---|---|
| Tick | Smallest CL price step, $0.01 = $10 per contract |
| Round trip | Entry plus exit of one trade; costs are quoted per round trip |
| Sharpe ratio (annual) | Average return divided by its wobble, scaled to a year. 1 = decent, 2 = strong, 3+ = rare |
| IC (information coefficient) | Correlation between a prediction and what happened next. 0.05 is useful, 0.2 is exceptional |
| t-statistic, p-value | How surprising a result is if there were no edge. Small p = surprising |
| Multiple testing | Try enough things and some look great by luck. FDR, FWER, Romano-Wolf and SPA correct for that |
| Pre-registration | Writing down the exact test before seeing the data, so the test cannot be bent afterwards |
| Discovery / validation / holdout | Practice exam / mock exam / final exam. Study the first freely; take the others once |
| Walk-forward | Fit on the past only, test on the next year, repeat |
| Purge, embargo | Gaps between fitting and testing data so information cannot leak across |
| Deflated Sharpe (DSR) | Sharpe corrected for how many things were tried |
| PBO | Probability that the in-sample winner is a below-median performer out of sample |
| MLL | Topstep's Maximum Loss Limit: fail line that trails the best end-of-day balance |
| DLL | Topstep's Daily Loss Limit: hitting it closes positions and stops trading for that day only |
| G8 | Project gate (D006): in simulated Combines on stress costs with a $500 reserve, pass at least 50% of the time and keep the upper 95% bound of the fail rate at or below 10%. (Before D006: the worst drop in the first 60 days within 50% of the MLL in 95% of attempts) |
| MAE / MFE | Worst / best price move during a trade |
| Planted edge | A fake, known edge added to real data to prove the pipeline can find edges |
