#!/usr/bin/env python3
"""Independent S003 inference from the exported daily gross/trade matrices.

This module deliberately does not import propfirm_research.  All resampling is
implemented here with NumPy, using one common stationary-bootstrap draw for the
whole strategy family on each repetition.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[3]
DEFAULT_INPUT = ROOT / "data/research/s003/r011_export"
DEFAULT_OUTPUT = ROOT / "data/research/replications/S003"


def stationary_indices(rng: np.random.Generator, n: int, mean_block: float) -> np.ndarray:
    """Politis-Romano stationary-bootstrap indices of length n."""
    starts = rng.integers(0, n, size=n)
    restart = rng.random(n) < (1.0 / mean_block)
    restart[0] = True
    out = np.empty(n, dtype=np.int32)
    out[0] = starts[0]
    for i in range(1, n):
        out[i] = starts[i] if restart[i] else (out[i - 1] + 1) % n
    return out


def bootstrap_means(
    x: np.ndarray, draws: int, mean_block: float, seed: int, chunk: int = 100
) -> np.ndarray:
    """Return stationary-bootstrap means; chunking bounds temporary memory."""
    rng = np.random.default_rng(seed)
    n, m = x.shape
    result = np.empty((draws, m), dtype=np.float64)
    for lo in range(0, draws, chunk):
        hi = min(lo + chunk, draws)
        idx = np.stack([stationary_indices(rng, n, mean_block) for _ in range(hi - lo)])
        result[lo:hi] = x[idx].mean(axis=1)
    return result


def romano_wolf(x: np.ndarray, boot_mean: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """One-sided Romano-Wolf step-down max-t with fixed original SEs."""
    n = x.shape[0]
    mean = x.mean(axis=0)
    se = x.std(axis=0, ddof=1) / np.sqrt(n)
    valid = se > 0
    t_obs = np.full(x.shape[1], -np.inf)
    t_obs[valid] = mean[valid] / se[valid]
    t_boot = np.full_like(boot_mean, -np.inf)
    t_boot[:, valid] = (boot_mean[:, valid] - mean[valid]) / se[valid]

    order = np.argsort(-t_obs)
    raw = np.ones(x.shape[1])
    for rank, j in enumerate(order):
        remaining = order[rank:]
        maxima = np.max(t_boot[:, remaining], axis=1)
        raw[j] = (np.count_nonzero(maxima >= t_obs[j]) + 1) / (len(maxima) + 1)
    adjusted = np.empty_like(raw)
    adjusted[order] = np.maximum.accumulate(raw[order])
    return t_obs, adjusted


def ratio_upper_bounds(
    gross: np.ndarray,
    trade: np.ndarray,
    gross_boot: np.ndarray,
    trade_boot: np.ndarray,
    alpha: float = 0.05,
) -> tuple[np.ndarray, np.ndarray, float, int]:
    """Simultaneous upper bounds for E[gross]/E[trade].

    The delta-method influence series supplies each ratio's original standard
    error.  The bootstrap deviations use the ratio in every resample and are
    studentised by that fixed original SE, matching the fixed-SE max-t
    convention used for Romano-Wolf.
    """
    n = gross.shape[0]
    p_trade = trade.mean(axis=0)
    edge = gross.mean(axis=0) / p_trade
    influence = (gross - trade * edge) / p_trade
    se = influence.std(axis=0, ddof=1) / np.sqrt(n)
    usable = np.all(trade_boot > 0, axis=1)
    if usable.sum() < 0.9 * len(usable):
        raise ValueError("more than 10% of ratio-bootstrap draws have a zero denominator")
    boot_edge = gross_boot[usable] / trade_boot[usable]
    max_t = np.max((boot_edge - edge) / se, axis=1)
    # Conservative empirical upper quantile (no interpolation below an order statistic).
    c = float(np.quantile(max_t, 1 - alpha, method="higher"))
    return edge, edge + c * se, c, int((~usable).sum())


def spa_consistent(
    x: np.ndarray, boot_mean: np.ndarray
) -> tuple[float, float, np.ndarray, float]:
    """Hansen consistent SPA against a zero/flat benchmark.

    Long-run standard deviations are estimated as sqrt(n * Var_boot(mean)).
    Plausible null candidates are recentered; clearly inferior candidates keep
    their negative drift, Hansen's consistent recentering rule.
    """
    n = x.shape[0]
    mean = x.mean(axis=0)
    omega = np.sqrt(n) * boot_mean.std(axis=0, ddof=1)
    valid = omega > 0
    t = np.full(x.shape[1], -np.inf)
    t[valid] = np.sqrt(n) * mean[valid] / omega[valid]
    statistic = float(max(0.0, np.max(t)))
    cutoff = -np.sqrt(2.0 * np.log(np.log(n)))
    plausible = t >= cutoff
    recenter = np.where(plausible, mean, 0.0)
    boot_t = np.full_like(boot_mean, -np.inf)
    boot_t[:, valid] = (
        np.sqrt(n) * (boot_mean[:, valid] - recenter[valid]) / omega[valid]
    )
    boot_stat = np.maximum(0.0, np.max(boot_t, axis=1))
    p = float((np.count_nonzero(boot_stat >= statistic) + 1) / (len(boot_stat) + 1))
    return statistic, p, plausible, cutoff


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--draws", type=int, default=10_000)
    parser.add_argument("--mean-block", type=float, default=5.0)
    parser.add_argument("--seed", type=int, default=20261017)
    args = parser.parse_args()

    gross_df = pd.read_parquet(args.input / "gross.parquet")
    trade_df = pd.read_parquet(args.input / "trade.parquet")
    if not gross_df.index.equals(trade_df.index) or not gross_df.columns.equals(trade_df.columns):
        raise ValueError("gross/trade matrices are not aligned")
    if gross_df.shape != (1278, 432):
        raise ValueError(f"unexpected matrix shape: {gross_df.shape}")
    gross = gross_df.to_numpy(dtype=np.float64)
    trade = trade_df.to_numpy(dtype=np.float64)
    if np.any((trade != 0) & (trade != 1)) or np.any((trade == 0) & (gross != 0)):
        raise ValueError("trade flags are not binary or no-trade gross P&L is nonzero")

    # One set of common draws is reused for all endpoints and costs.
    gross_boot = bootstrap_means(gross, args.draws, args.mean_block, args.seed)
    trade_boot = bootstrap_means(trade, args.draws, args.mean_block, args.seed)
    # The independent calls above intentionally use identical RNG streams and
    # therefore identical index matrices, preserving each gross/trade ratio.

    details = pd.DataFrame(index=gross_df.columns)
    summary: dict[str, object] = {
        "n_days": int(gross.shape[0]),
        "n_strategies": int(gross.shape[1]),
        "bootstrap_draws": args.draws,
        "mean_block_days": args.mean_block,
        "seed": args.seed,
    }
    for label, cost in (("base", 2.402), ("stress", 4.402)):
        net = gross - cost * trade
        net_boot = gross_boot - cost * trade_boot
        t, p_adj = romano_wolf(net, net_boot)
        details[f"t_{label}"] = t
        details[f"rw_p_{label}"] = p_adj
        summary[f"romano_wolf_{label}"] = {
            "cost_ticks": cost,
            "min_adjusted_p": float(p_adj.min()),
            "count_adjusted_p_lt_0.05": int(np.count_nonzero(p_adj < 0.05)),
            "min_p_strategy": str(gross_df.columns[np.argmin(p_adj)]),
        }

    edge, upper, critical, excluded = ratio_upper_bounds(gross, trade, gross_boot, trade_boot)
    details["gross_edge_per_trade"] = edge
    details["gross_edge_upper_95"] = upper
    summary["simultaneous_gross_edge_upper_95"] = {
        "critical_value": critical,
        "draws_excluded_for_zero_trade_ratio": excluded,
        "maximum_bound_ticks": float(upper.max()),
        "maximum_bound_strategy": str(gross_df.columns[np.argmax(upper)]),
        "count_bound_below_4.402": int(np.count_nonzero(upper < 4.402)),
        "count_bound_below_2.402": int(np.count_nonzero(upper < 2.402)),
    }

    base = gross - 2.402 * trade
    spa_stat, spa_p, plausible, spa_cutoff = spa_consistent(base, gross_boot - 2.402 * trade_boot)
    summary["spa_consistent_base"] = {
        "statistic": spa_stat,
        "p_value": spa_p,
        "consistent_t_cutoff": spa_cutoff,
        "plausible_candidates": int(plausible.sum()),
    }

    args.output.mkdir(parents=True, exist_ok=True)
    details.index.name = "strategy"
    details.to_parquet(args.output / "part1_strategy_details.parquet")
    (args.output / "part1_summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps(summary, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
