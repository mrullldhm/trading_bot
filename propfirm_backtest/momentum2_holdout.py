"""Strategy 8 (Pine 1-Minute Momentum), step 2 of 2: test the frozen champion ONCE on 2022 -> today.

Usage:
    python -m propfirm_backtest.momentum2_holdout [--open-ineligible]

Same once-only rules and verdict as family_holdout (atomic marker, code + data hash, >= 100 trades,
block-bootstrap lower bound > 0). By default it refuses when the champion failed a development gate
(the verdict is already FAIL and the one look would be spent); --open-ineligible opens it anyway,
only on the user's explicit decision. 2022+ has never been used for this strategy.
"""

import json
import os
import sys

import pandas as pd

from propfirm_data.eia_calendar import load_releases

from . import bars as B
from . import family_holdout as FH
from . import orb_holdout as H
from .momentum2_search import MOMENTUM2

RULE_TEXT = FH.RULE_TEXT.split(" Across strategies")[0]


def main(argv=None) -> int:
    argv = sys.argv if argv is None else argv
    out = MOMENTUM2.out_dir
    frozen, code = H.preflight(out, MOMENTUM2)
    if frozen is None:
        return code
    if not frozen["champion_eligible"] and "--open-ineligible" not in argv:
        print("The champion did not pass every development gate, so the verdict is already FAIL.")
        print("Not opening the holdout (one look only). Use --open-ineligible to open it anyway.")
        return 4
    try:
        fd = os.open(out / "holdout_opened.json", os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        print("Holdout already opened by another run.")
        return 2
    with os.fdopen(fd, "w") as fh:
        json.dump({"opened_utc": pd.Timestamp.now(tz="UTC").isoformat(), "source_sha256": frozen["source_sha256"]},
                  fh, indent=2)
    print("Loading all data (development + holdout)...", flush=True)
    result = H.evaluate(B.load_minutes(), frozen, out, load_releases(), MOMENTUM2, FH.family_verdict, RULE_TEXT)
    print(f"\nVerdict: {result}. Report: {out / 'holdout.md'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
