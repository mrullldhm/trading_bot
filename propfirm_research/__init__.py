"""Research toolkit for the CL strategy research programme (see research/README.md).

Rules that shape this package (research/PROTOCOL.md):
- market data is read only through `propfirm_research.data`, which enforces the period firewall;
- every run and every data access is written to research/LEDGER.csv;
- the hashed modules of propfirm_backtest/ and propfirm_data/ are imported, never edited.
"""
