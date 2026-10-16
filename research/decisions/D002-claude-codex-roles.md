---
id: D002
title: Claude builds, Codex reviews and replicates
status: decided
decided: 2026-10-16
approver: owner
updated: 2026-10-16
---

# D002 — Claude builds, Codex reviews and replicates

## Context
The owner asked Claude and Codex to research together. The repo's guide (TRADING_BOT_GUIDE §12) uses an
author / editor loop. In research, the biggest risks are self-deception (bugs that flatter results,
selection luck), so independent checking matters more than speed.

## Options
| Option | For | Against |
|---|---|---|
| Reviewer + independent replicator | strongest verification; no edit clashes | slower |
| Co-builder (role swap per module) | faster | edit clashes; checker is also an author |
| Reviewer only | cheapest | no independent recomputation |

## Decision
**Reviewer + independent replicator** (owner's choice).
- Claude: pre-registrations, canonical code (`propfirm_research/`), studies, reports, ledger, all docs.
- Codex: blocking review of every pre-registration; adversarial review of each new module; independent
  recomputation of every headline number from raw parquet in `research/replications/<item>/`;
  red team of positive results; blind hypothesis proposals each phase.
- Codex writes only in `research/replications/`. Claude saves Codex output verbatim in `reviews/`.
- A finding is VALIDATED only if both numbers match. Neither changes a spec after seeing results.

## Why
Two independent implementations that agree are much harder to fool than one implementation checked by
reading. Codex already showed its value here (bugs caught in every earlier module).

## Consequences
How to call Codex is in PROTOCOL §7. Every review gets an R### file with a resolution table.
