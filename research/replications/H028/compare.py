"""Post-unblinding comparison of frozen R019 own results with Claude's explore.csv."""

import importlib.util
from pathlib import Path

source = Path(__file__).resolve().parents[1] / "H027/compare.py"
spec = importlib.util.spec_from_file_location("r019_compare_common", source)
module = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(module)
module.HERE = Path(__file__).resolve().parent
module.CLAUDE = module.HERE.parents[1] / "hypotheses/H028-cross-energy-settlement/explore.csv"
module.main()
