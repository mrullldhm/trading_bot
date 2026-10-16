# strategies/ (later phases)

Empty until at least one hypothesis is VALIDATED (Phase E). Then each strategy gets a folder
`strategies/ST###-slug/` with:
- `spec.md`: the exact rules built only from validated signals (entry, exit, flat 16:05 ET, DLL,
  sizing in CL contracts per account, EIA handling), the pre-declared one-step neighbours for G9;
- results on discovery + validation against G1-G9 and V1-V4 (REQUIREMENTS §3-4), with the account's
  Combine settings and the DLL on;
- the portfolio combination (fixed weights, decided before testing);
- the holdout pre-registration (owner approval) and its result.

No parameter grids (D000). A strategy has few parameters, each taken from its hypothesis card.
