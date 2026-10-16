# Instructions for Claude in research/

You are continuing a long-running research programme. Do not start work from memory or from the chat.

## On entry (every session)
1. Read `STATUS.md`, then `PROTOCOL.md`, then the newest file in `journal/`, then the active item named
   in STATUS.
2. Run `python -m pytest -q` from the repo root and note the result in the journal.
3. Tell the owner, in a few lines, where the programme stands and what you will do next.

## Hard rules (details in PROTOCOL.md)
- Read market data only through `propfirm_research.data`. Discovery (2010-06-07 .. 2016-12-31) is free;
  validation (2017-2021) needs a registered pre-registration; holdout (2022+) also needs
  `approved_by_user: true`. Never call `load_bars`, `load_minutes` or `pd.read_parquet` on bar files
  from research code.
- Every run writes a LEDGER.csv row (the code does it; check it happened).
- Never edit the hashed modules listed in PROTOCOL.md §9. Write new modules in `propfirm_research/`.
- A pre-registration is reviewed by Codex (saved in `reviews/`) before it is frozen. Never change a
  frozen spec, and never re-run a validation or holdout test.
- No more parameter grids over indicator settings on the same bars (D000).
- Owner approval needed for: gate changes, data purchases, opening the holdout, new dependencies,
  anything touching money, orders or API keys.
- Git: the owner commits manually. Never run state-changing git commands. Suggest a conventional
  commit message with no AI attribution lines.

## On exit (every session)
Follow PROTOCOL.md §10: update STATUS.md, write `journal/YYYY-MM-DD-NN.md`, check LEDGER rows, update
BACKLOG / KNOWLEDGE, run `python -m propfirm_research.index`, keep tests green, suggest a commit message.

## Style for the owner
The owner is a beginner. Explain why behind every decision, big picture first, tables over prose,
plain words, and an analogy when it helps.
