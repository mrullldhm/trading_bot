# CL Strategy Research Programme

An evidence-first search for a CL (NYMEX crude oil futures) intraday strategy that can pass a Topstep
Trading Combine when run by an automated bot. Claude leads and builds; Codex reviews and independently
replicates. Started 2026-10-16.

> **Where are we?** Read [STATUS.md](STATUS.md). It is the single source of truth for the current phase,
> the active item and the next actions.

---

## Start here (new session)

Tell Claude: *"Continue the research in /home/mrullldhm/personal/propfirm/research"*. Then read, in order:

1. [STATUS.md](STATUS.md): current phase, active item, next actions, anything waiting on the owner.
2. [PROTOCOL.md](PROTOCOL.md): the rules (data firewall, statistics, Codex workflow, checklists).
3. The newest file in [journal/](journal/): what happened last session and why.
4. The active item named in STATUS (a study in `studies/` or a hypothesis card in `hypotheses/`).

Before ending a session, run the end-of-session checklist in [PROTOCOL.md §10](PROTOCOL.md#10-session-checklists).

---

## Why this programme exists

Strategies 1-8 ([prior work](prior-work/STRATEGIES-1-8.md)) all failed the gates, and an audit proved the
failures were real. They were *picked first and measured second*: a known setup, a big parameter grid,
then the gates. A big grid manufactures luck: the best of thousands of tries looks good on old data and
fails on new data.

This programme reverses the order. Like a doctor: tests first, diagnosis second, prescription last.

```
 1. MEASURE        S001 feasibility: what Sharpe / edge does passing actually need?
                   S002 atlas: how does CL behave by time of day, session, event, regime?
                   S003 predictability ceiling: how much can these bars predict at all? (kill test)
        │
 2. HYPOTHESES     each with an economic reason + literature + exact definition (hypotheses/BACKLOG.md)
        │          explored on DISCOVERY data only (2010-06 .. 2016-12)
        │
 3. CONFIRM        pre-registration -> Codex review -> ONE validation run (2017 .. 2021)
        │          -> Codex replicates the numbers -> VALIDATED or REJECTED
        │
 4. BUILD          simple strategies from validated signals -> portfolio -> all gates
        │
 5. FINAL EXAM     ONE holdout look (2022+, owner approval) -> practice account (truly unseen data)
```

If the measurements show this data cannot produce a strategy, the programme says so with evidence
(kill criteria in [PROTOCOL.md §4.7](PROTOCOL.md#47-kill-criteria-for-the-whole-programme)) instead of
running yet another grid.

---

## Folder map

| Path | What it holds | Who writes it |
|---|---|---|
| [STATUS.md](STATUS.md) | Living dashboard: phase, active item, next actions, budgets | Claude, every session |
| [PROTOCOL.md](PROTOCOL.md) | The method and the rules | Claude; changes need a decision record |
| [REQUIREMENTS.md](REQUIREMENTS.md) | What "success" means: Topstep rules, gates, costs, target zone | Claude; gate changes need the owner |
| [KNOWLEDGE.md](KNOWLEDGE.md) | Facts about CL, each graded CONFIRMED / VALIDATED / EXPLORATORY / REFUTED | Claude |
| [LEDGER.csv](LEDGER.csv) | Append-only log of every run and every data access | code (`propfirm_research.ledger`) |
| [HOLDOUTS.md](HOLDOUTS.md) | Every look at held-back data, past and present | Claude |
| [INDEX.md](INDEX.md) | Generated table of every item (studies, hypotheses, decisions, reviews) | code (`propfirm_research.index`) |
| [hypotheses/](hypotheses/) | `BACKLOG.md` (ranked queue) + one folder per hypothesis (card, prereg, result) | Claude |
| [studies/](studies/) | Descriptive and diagnostic studies (S001, S002, ...) | Claude (code writes reports) |
| [strategies/](strategies/) | Strategies built from validated hypotheses (later phases) | Claude |
| [decisions/](decisions/) | Decision records: context, options, decision, why, who approved | Claude; owner approves |
| [journal/](journal/) | One file per session: goal, done, results, next | Claude |
| [reviews/](reviews/) | Codex output, verbatim, with Claude's response and a resolution table | Claude saves; Codex authors |
| [replications/](replications/) | Codex's independent replication scripts and outputs | Codex only |
| [literature/](literature/) | Papers, key numbers, which hypothesis each one feeds | Claude |
| [prior-work/](prior-work/) | Strategies 1-8: what failed, why, trial counts | Claude |

Code lives outside this folder, in the `propfirm_research/` package at the repo root (tests in
`tests/test_research_*.py`). Large outputs go to `data/research/` (git-ignored). This folder holds the
reasoning, the decisions and small result tables, and is meant to be committed to git by the owner.

---

## Five rules that matter most

1. **The firewall.** Only discovery data (2010-06 .. 2016-12) may be explored freely. Validation and
   holdout data are read only by a pre-registered run, through `propfirm_research.data`, and every read
   is logged.
2. **Every look counts.** Every run writes a row to `LEDGER.csv`, so the number of tries is always known.
3. **Never edit the hashed modules** of `propfirm_backtest/` and `propfirm_data/` (list in PROTOCOL §9).
   Editing them voids six frozen holdouts.
4. **Codex checks Claude.** Codex reviews every pre-registration before it runs and recomputes every
   headline number on its own. A finding is VALIDATED only if both agree.
5. **The owner decides** gate changes, data purchases, holdout openings and new dependencies.

---

## Owner decisions on record

| ID | Decision |
|---|---|
| [D002](decisions/D002-claude-codex-roles.md) | Codex is reviewer and independent replicator; Claude builds |
| [D003](decisions/D003-gate-policy.md) | Gates stay the official bar; G8 scales to 50% of each account's loss limit; any recalibration only with owner approval after S001 |
| [D004](decisions/D004-sizing-scope.md) | CL contracts only (50K, 100K, 150K Combines); no micro contracts |
| [D005](decisions/D005-daily-loss-limit.md) | Topstep Daily Loss Limit is a hard rule in every simulation |
| [D006](decisions/D006-g8-recalibration-proposal.md) | G8 = pass >= 50% and upper bound of P(fail) <= 10% on stress costs, $500 reserve |
| [D007](decisions/D007-scikit-learn.md) | scikit-learn 1.9.1 added (pinned) for S003 |
| [D008](decisions/D008-direction-after-s003.md) | After S003: staged settlement-flow data track (new information about settlement flow, 2015-16 first) |
| [D009](decisions/D009-strict-exit.md) | Strict exits: never fill after the exit minute; a missing exact exit bar skips the window |
| [D010](decisions/D010-stage1-data-purchase.md) | Stage-1 purchase approved: TAS, signed flow, settlement stats, RB/HO/BZ bars for 2015-16, cap $15 (addendum: line 6 chosen after the sample) |
| [D011](decisions/D011-direction-after-stage1.md) | After stage 1 found nothing: **programme paused**; a restart needs a new decision record |

The founding plan is [decisions/D000-charter.md](decisions/D000-charter.md).

*Not financial advice. Most trading strategies lose money. This is a research record, not a promise.*
