"""Post-unblinding comparison of frozen R019 own results with Claude's explore.csv."""

from pathlib import Path
import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
CLAUDE = HERE.parents[1] / "hypotheses/H027-tas-settlement-flow/explore.csv"

MAP = {
    "entry_time_eligible_days": None,
    "emitted_signals": "emitted",
    "evaluated_trades": "n",
    "gross_mean_ticks": "gross",
    "sample_sd_ticks": "sd",
    "one_sided_t": "t",
    "gross_mean_2015": "gross_2015",
    "gross_mean_2016": "gross_2016",
    "net_base_ticks": "net_base",
    "net_stress_ticks": "net_stress",
    "trades_per_year": "trades_per_year",
    "MDE_net_ticks": "mde_net_validation",
    "largest_single_day_share": "max_day_share",
    "stage1_screen_pass": "stage1_pass",
}


def tolerance(item, claude):
    if item in {"emitted_signals", "evaluated_trades"}:
        return 0.01 * abs(float(claude)), "1%"
    if item in {"gross_mean_ticks", "sample_sd_ticks", "gross_mean_2015", "gross_mean_2016",
                "net_base_ticks", "net_stress_ticks", "MDE_net_ticks"}:
        return 0.1, "0.1 tick"
    if item == "trades_per_year":
        return 0.01 * abs(float(claude)), "1%"
    if item == "one_sided_t":
        return 0.01, "0.01"
    if item == "largest_single_day_share":
        return 0.001, "0.001"
    return 0.0, "exact"


def main():
    own = pd.read_csv(HERE / "own_results.csv").set_index("variant")
    claude = pd.read_csv(CLAUDE).set_index("variant")
    rows = []
    for variant, o in own.iterrows():
        for item, source in MAP.items():
            ov = o[item]
            cv = np.nan if source is None else claude.at[variant, source]
            if source is None or pd.isna(cv):
                diff, label, within = np.nan, "not reported", "N/A"
            elif item == "stage1_screen_pass":
                diff, label, within = bool(ov) != bool(cv), "exact", "yes" if bool(ov) == bool(cv) else "no"
            else:
                diff = float(ov) - float(cv)
                tol, label = tolerance(item, cv)
                within = "yes" if abs(diff) <= tol + 1e-12 else "no"
            rows.append({"variant": variant, "item": item, "own": ov, "claude": cv,
                         "difference_own_minus_claude": diff, "tolerance": label, "within_tolerance": within})
    result = pd.DataFrame(rows)
    result.to_csv(HERE / "comparison.csv", index=False, float_format="%.12g")
    comparable = result[result["within_tolerance"].isin(["yes", "no"])]
    verdict = comparable.groupby("variant")["within_tolerance"].apply(lambda x: "MATCH" if (x == "yes").all()
                                                                        else "MISMATCH")
    verdict.rename("verdict").to_csv(HERE / "verdict.csv")
    print(result.to_string(index=False))
    print(verdict.to_string())


if __name__ == "__main__":
    main()
