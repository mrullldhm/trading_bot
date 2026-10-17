---
id: D007
title: Add scikit-learn (pinned) for S003
status: decided
decided: 2026-10-17
approver: owner
updated: 2026-10-17
---

# D007 — scikit-learn for the S003 ceiling

## Context
S003 needs penalised linear models and shallow gradient-boosted trees inside a nested walk-forward
(design merged from Codex R001). New dependencies need owner approval (PROTOCOL §8).

## Options
| Option | For | Against |
|---|---|---|
| scikit-learn, pinned | standard, tested implementations; no hand-written boosting bugs | new dependency (+ scipy, joblib, threadpoolctl, narwhals) |
| numpy-only linear models | no new code to trust | no tree model: a weaker ceiling |

## Decision
**scikit-learn 1.9.1** (owner: "yes proceed scikit-learn"). Released 2026-09-10 on PyPI; installed into
`.venv`; pinned in `requirements.txt` with its dependencies: scipy 1.18.1, joblib 1.6.0, threadpoolctl
3.7.0, narwhals 2.27.1. numpy stayed at 2.5.4.

## Consequences
- Only `propfirm_research` study code may import it; hashed modules are untouched.
- `stats` stays scipy-free (its own t quantile / p-value), so the toolkit's statistics do not change
  with the new dependency.
