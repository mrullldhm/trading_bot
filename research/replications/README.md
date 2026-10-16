# replications/ (Codex only)

Codex's independent replications live here, one folder per item: `replications/<item-id>/`
(for example `replications/S001/`, `replications/H001/`).

Each folder holds:
- the script(s) Codex wrote, using its own logic for the quantity being checked (it may read the raw
  parquet files and shared reference data, not Claude's `propfirm_research` implementation of that quantity);
- `README.md`: the command that reproduces each number, Codex's numbers, the tolerance used;
- small outputs only. Large outputs go to `data/research/replications/<item-id>/` (git-ignored).

Claude never edits files here. Claude records the comparison (Codex's numbers vs Claude's, PASS/FAIL)
in `research/reviews/R###-*.md`. Rules: PROTOCOL §7 and AGENTS.md.
