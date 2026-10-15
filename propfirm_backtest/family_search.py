"""ORB families, step 1 of 2: grid + selection on DEVELOPMENT data only (2010-06 -> 2021-12).

Usage:
    python -m propfirm_backtest.family_search zab [--quick]       # strategy 3
    python -m propfirm_backtest.family_search crabel [--quick]    # strategy 4
    python -m propfirm_backtest.family_search acd [--quick]       # strategy 5

Same discipline as classic ORB (orb_search.py: gates, plateau, walk-forward replaying the selector,
deflated Sharpe, PBO, finalists, one frozen champion). Results: data/backtests/<family>/.
Step 2 (python -m propfirm_backtest.family_holdout <family>) tests the champion ONCE on 2022+.
"""

import sys

import numpy as np

from . import orb_engine as E
from . import orb_family_engine as FE
from . import orb_search as O

FLAT_MIN = {k: O.FLAT_MIN[k] for k in ("+120", "+240", "session")}
EXTRA_SOURCES = ["orb_features.py", "orb_family_engine.py", "family_search.py", "family_holdout.py"]


def family_table(grid, market_cls) -> np.ndarray:
    """Per config: row of the family's day tables for its (anchor, range length)."""
    keys = [(a, L) for a in FE.FAMILY_ANCHORS for L in market_cls.RANGE_LENGTHS]
    a_idx, l_idx = grid.idx[:, grid.keys.index("anchor")], grid.idx[:, grid.keys.index("range_min")]
    table_of = np.array([[keys.index((a, L)) for L in grid.dims["range_min"]] for a in grid.dims["anchor"]])
    return table_of[a_idx, l_idx]


# --- strategy 3: ZAB ---------------------------------------------------------------------------------

ZAB_STOP = {"opposite": 0, "atr0.05": 5, "atr0.10": 10, "atr0.20": 20}
ZAB_RELVOL = {"none": 0, "1.0": 10, "1.5": 15, "2.0": 20}
ZAB_DIR = {"candle": FE.DIR_CANDLE, "long": FE.DIR_LONG, "short": FE.DIR_SHORT}


def zab_cfg_matrix(grid) -> np.ndarray:
    col = grid.level_codes
    return np.column_stack([
        family_table(grid, FE.ZabMarket), col("anchor", FE.anchor_row),
        col("entry", {"immediate": FE.IMMEDIATE, "breakout": FE.BREAKOUT}.get),
        col("stop", ZAB_STOP.get), col("target", {"10R": 10, "none": 0}.get), col("flat", FLAT_MIN.get),
        col("relvol", ZAB_RELVOL.get), col("direction", ZAB_DIR.get),
    ])


def zab_label(row) -> str:
    return (f"{row['anchor']} / {row['range_min']}m candle / {row['entry']} / stop {row['stop']} / "
            f"tgt {row['target']} / flat {row['flat']} / rel-vol {row['relvol']} / {row['direction']}")


ZAB = O.Family(
    name="zab", title="Strategy 3: ZAB-inspired ORB",
    dims={
        "anchor": FE.FAMILY_ANCHORS,
        "range_min": FE.ZabMarket.RANGE_LENGTHS,
        "entry": ["immediate", "breakout"],
        "stop": list(ZAB_STOP),
        "target": ["10R", "none"],
        "flat": list(FLAT_MIN),
        "relvol": list(ZAB_RELVOL),
        "direction": list(ZAB_DIR),
    },
    neighbours={"range_min": "linear", "stop": {1: [2], 2: [1, 3], 3: [2]}, "flat": "linear", "relvol": "linear"},
    cfg_matrix=zab_cfg_matrix, market=FE.ZabMarket, label=zab_label, best_per=["anchor", "range_min", "entry"],
    quick_dims={"anchor": ["et0900"], "range_min": [5, 15], "relvol": ["none", "1.0"]},
    notes=["ZAB-INSPIRED, not a replication: the papers pick the top 'stocks in play' across thousands of "
           "stocks each day; one contract has no cross-section, so relative volume is a time-series filter "
           "(today's opening volume vs its own 14-day average). ATR14 and relative volume use prior days only.", ""],
    extra_sources=EXTRA_SOURCES,
    holdout_cmd="python -m propfirm_backtest.family_holdout zab")


# --- strategy 4: Crabel ------------------------------------------------------------------------------

UNTIL_FLAT = 100_000  # entry window "session": orders live until the flat time
CRABEL_SETUP = {"none": FE.SETUP_NONE, "nr4": FE.SETUP_NR4, "nr7": FE.SETUP_NR7, "inside": FE.SETUP_INSIDE,
                "id_nr4": FE.SETUP_IDNR4}
CRABEL_EXPIRY = {"10": 10, "30": 30, "120": 120, "session": UNTIL_FLAT}
CRABEL_STOP = {"opposite_level": E.OPPOSITE, "or_mid": E.MID}
SIDES = {"both": O.DIR_CODE["both1"], "long": O.DIR_CODE["long"], "short": O.DIR_CODE["short"]}


def crabel_cfg_matrix(grid) -> np.ndarray:
    col = grid.level_codes
    return np.column_stack([
        family_table(grid, FE.CrabelMarket), col("anchor", FE.anchor_row),
        col("stretch", lambda v: round(float(v) * 100)), col("setup", CRABEL_SETUP.get),
        col("expiry_min", CRABEL_EXPIRY.get), col("flat", FLAT_MIN.get), col("stop", CRABEL_STOP.get),
        col("direction", SIDES.get),
    ])


def crabel_label(row) -> str:
    return (f"{row['anchor']} / {row['range_min']}m OR / stretch x{row['stretch']} / setup {row['setup']} / "
            f"orders {row['expiry_min']}m / flat {row['flat']} / stop {row['stop']} / {row['direction']}")


CRABEL = O.Family(
    name="crabel", title="Strategy 4: Crabel ORB (stretch + contraction setups)",
    dims={
        "anchor": FE.FAMILY_ANCHORS,
        "range_min": FE.CrabelMarket.RANGE_LENGTHS,
        "stretch": ["0.5", "0.75", "1.0", "1.25", "1.5"],
        "setup": list(CRABEL_SETUP),
        "expiry_min": list(CRABEL_EXPIRY),
        "flat": ["+240", "session"],
        "stop": list(CRABEL_STOP),
        "direction": list(SIDES),
    },
    neighbours={"range_min": "linear", "stretch": "linear", "expiry_min": "linear", "flat": "linear"},
    cfg_matrix=crabel_cfg_matrix, market=FE.CrabelMarket, label=crabel_label,
    best_per=["anchor", "setup", "stretch"],
    quick_dims={"anchor": ["et0900"], "range_min": [5], "stretch": ["0.75", "1.0", "1.25"]},
    notes=["Stretch, NR4/NR7/inside/ID-NR4 come from previous sessions (anchor -> 14:30 ET, same contract). "
           "Crabel often held overnight; here every trade exits the same day (Topstep must be flat by 16:10 ET).", ""],
    extra_sources=EXTRA_SOURCES,
    holdout_cmd="python -m propfirm_backtest.family_holdout crabel")


# --- strategy 5: Fisher ACD --------------------------------------------------------------------------

ACD_AC = {"0.05/0.10": (50, 100), "0.075/0.125": (75, 125), "0.10/0.15": (100, 150), "0.125/0.20": (125, 200)}
ACD_DIR = {"both": FE.DIR_CANDLE, "long": FE.DIR_LONG, "short": FE.DIR_SHORT}


def acd_cfg_matrix(grid) -> np.ndarray:
    col = grid.level_codes
    return np.column_stack([
        family_table(grid, FE.AcdMarket), col("anchor", FE.anchor_row), col("range_min", int),
        col("a_c_atr", lambda v: ACD_AC[v][0]), col("a_c_atr", lambda v: ACD_AC[v][1]),
        col("acceptance", lambda v: round(float(v) * 100)), col("pivot", {"off": 0, "aligned": 1}.get),
        col("c_reversal", {"off": 0, "on": 1}.get), col("flat", FLAT_MIN.get), col("direction", ACD_DIR.get),
    ])


def acd_label(row) -> str:
    return (f"{row['anchor']} / {row['range_min']}m OR / A/C {row['a_c_atr']} ATR / accept x{row['acceptance']} OR / "
            f"pivot {row['pivot']} / C {row['c_reversal']} / flat {row['flat']} / {row['direction']}")


ACD = O.Family(
    name="acd", title="Strategy 5: Fisher ACD",
    dims={
        "anchor": FE.FAMILY_ANCHORS,
        "range_min": FE.AcdMarket.RANGE_LENGTHS,
        "a_c_atr": list(ACD_AC),
        "acceptance": ["0.25", "0.5", "1.0"],
        "pivot": ["off", "aligned"],
        "c_reversal": ["off", "on"],
        "flat": ["+240", "session"],
        "direction": list(ACD_DIR),
    },
    neighbours={"range_min": "linear", "a_c_atr": "linear", "acceptance": "linear", "flat": "linear"},
    cfg_matrix=acd_cfg_matrix, market=FE.AcdMarket, label=acd_label, best_per=["anchor", "range_min", "a_c_atr"],
    quick_dims={"anchor": ["et0900"], "range_min": [10, 15], "acceptance": ["0.5"]},
    notes=["A and C values are fractions of the prior-session ATR14 (Fisher's own values were proprietary); "
           "acceptance = T consecutive whole 1-minute bars beyond the level (conservative version of Fisher's "
           "time rule); the pivot filter is an adaptation; the session close is the last trade before 14:30 ET "
           "(a settlement proxy, not the official settlement).", ""],
    extra_sources=EXTRA_SOURCES,
    holdout_cmd="python -m propfirm_backtest.family_holdout acd")

FAMILIES = {"zab": ZAB, "crabel": CRABEL, "acd": ACD}


def family_from_argv(script: str, argv=None):
    """The family named on the command line, or None (usage printed)."""
    names = [a for a in (sys.argv if argv is None else argv)[1:] if not a.startswith("--")]
    if len(names) != 1 or names[0] not in FAMILIES:
        print(f"Usage: python -m propfirm_backtest.{script} {{{'|'.join(FAMILIES)}}} [--quick]")
        return None
    return FAMILIES[names[0]]


def main() -> int:
    family = family_from_argv("family_search")
    return 1 if family is None else O.main(family)


if __name__ == "__main__":
    sys.exit(main())
