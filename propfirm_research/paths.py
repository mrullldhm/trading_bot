"""Where research files live. Tests redirect these through monkeypatch."""

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RESEARCH_DIR = ROOT / "research"
LEDGER_FILE = RESEARCH_DIR / "LEDGER.csv"
OUT_DIR = ROOT / "data" / "research"  # large outputs, git-ignored
