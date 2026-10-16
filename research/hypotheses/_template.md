---
id: H###
title: <one-line claim>
status: spec            # idea | spec | explored | preregistered | validated | rejected | parked | investigating
prior: A                # A | B | C
source: <paper / study / Codex / owner>
created: YYYY-MM-DD
updated: YYYY-MM-DD
---

# H### — <title>

## 1. Claim
One falsifiable sentence: "At <time ET>, when <condition>, CL moves <direction> over <horizon> by more
than costs."

## 2. Mechanism
Who loses money to this trade, why, and why it is not arbitraged away.

## 3. Literature and prior evidence
Papers (link `literature/REFERENCES.md`), related results from strategies 1-8, related KNOWLEDGE facts.

## 4. Exact definition (causal)
- Data: front month (`CL.v.0`), second month if needed; roll-safe returns only.
- Decision time(s) ET; signal formula using only information available at that minute.
- Entry: next minute's open + slippage. Exit: fixed horizon / 16:05 ET / stop (if any).
- Direction rule, filters, sizing (CL contracts), EIA handling.
- Variants that will be tested together (the family) and why each is needed.

## 5. Discovery exploration
- Command, code hash, ledger run ids.
- Every variant tried (count them), results table with day-clustered t, BH q-values, the three
  discovery blocks (2010-12, 2013-14, 2015-16), costs at 1 and 2 ticks per side.
- Promotion check (PROTOCOL §4.4): q < 0.10 / sign stability incl. 2015-16 / net edge > stress cost /
  mechanism / power.

## 6. Pre-registration
- Null and test for stage 1 (N2/N3/N4) and stage 2 (N1); alpha 0.01 one-sided; multiplicity method.
- Power / MDE for the validation sample.
- Codex review: R###. Frozen file: `prereg.json` (sha256 ...), ledger run id.

## 7. Validation result
`result.json`, ledger run id, verdict, numbers at 1 and 2 ticks per side, decay vs discovery.

## 8. Codex replication
R###: Codex's numbers vs Claude's, difference, tolerance, PASS/FAIL.

## 9. Verdict and next step
VALIDATED / REJECTED / PARKED, with the reason. What it means for the strategy stage.

## 10. Change log
- YYYY-MM-DD: created.
