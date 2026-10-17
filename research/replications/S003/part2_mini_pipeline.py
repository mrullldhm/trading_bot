#!/usr/bin/env python3
"""Independent raw-bar mini-pipeline for S003.

No project research code is imported.  The script reads CL.v.0 directly,
constructs causal features, performs nested expanding walk-forward ridge fits,
and runs the requested null and planted-edge controls.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.impute import SimpleImputer
from sklearn.linear_model import Ridge
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler


ROOT = Path(__file__).resolve().parents[3]
RAW = ROOT / "data/processed/ohlcv-1m"
OUT = ROOT / "data/research/replications/S003"
ALPHAS = (1.0, 10.0, 100.0, 1000.0)
RETURN_COLUMNS = ("ret_5", "ret_15", "ret_30", "ret_60", "ret_120")
FEATURE_COLUMNS = RETURN_COLUMNS + (
    "ret_since_1800",
    "vwap_distance",
    "range_position",
    "rv60_relative_20d",
)


@dataclass(frozen=True)
class Cell:
    name: str
    decision: str
    horizon: int | None


CELLS = (
    Cell("14:35+60", "14:35", 60),
    Cell("09:00+30", "09:00", 30),
    Cell("20:00+5", "20:00", 5),
    Cell("14:35+flat", "14:35", None),
)


def load_bars(raw: Path) -> pd.DataFrame:
    columns = [
        "ts_event_utc", "continuous_symbol", "raw_symbol", "open_ticks",
        "high_ticks", "low_ticks", "close_ticks", "volume",
    ]
    frames = []
    for year in range(2010, 2017):
        part = pd.read_parquet(
            raw / f"year={year}/cl.parquet",
            columns=columns,
            filters=[("continuous_symbol", "==", "CL.v.0")],
        )
        frames.append(part.drop(columns="continuous_symbol"))
    bars = pd.concat(frames, ignore_index=True).sort_values("ts_event_utc")
    bars["ts_et"] = bars["ts_event_utc"].dt.tz_convert("America/New_York")
    local_day = bars["ts_et"].dt.normalize().dt.tz_localize(None)
    after_open = bars["ts_et"].dt.hour >= 18
    bars["trading_day"] = local_day + pd.to_timedelta(after_open.astype(np.int8), unit="D")
    bars = bars[
        bars["trading_day"].between(pd.Timestamp("2010-06-07"), pd.Timestamp("2016-12-31"))
    ].copy()
    if bars.duplicated("ts_event_utc").any():
        raise ValueError("duplicate CL.v.0 minute timestamps")
    return bars


def decision_timestamp(day: pd.Timestamp, hhmm: str) -> pd.Timestamp:
    hour, minute = map(int, hhmm.split(":"))
    calendar_day = day - pd.Timedelta(days=1) if hour >= 18 else day
    return pd.Timestamp(
        year=calendar_day.year,
        month=calendar_day.month,
        day=calendar_day.day,
        hour=hour,
        minute=minute,
        tz="America/New_York",
    )


def exact_row(session: pd.DataFrame, timestamp: pd.Timestamp) -> pd.Series | None:
    pos = session["ts_et"].searchsorted(timestamp)
    if pos < len(session) and session["ts_et"].iloc[pos] == timestamp:
        return session.iloc[pos]
    return None


def asof_open(prior: pd.DataFrame, timestamp: pd.Timestamp, symbol: str) -> float:
    eligible = prior[(prior["ts_et"] <= timestamp) & (prior["raw_symbol"] == symbol)]
    return float(eligible["open_ticks"].iloc[-1]) if len(eligible) else np.nan


def build_cell(groups: dict[pd.Timestamp, pd.DataFrame], cell: Cell) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for day, session in groups.items():
        decision = decision_timestamp(day, cell.decision)
        entry = exact_row(session, decision)
        flat = decision_timestamp(day, "16:05")
        nominal_exit = flat if cell.horizon is None else decision + pd.Timedelta(minutes=cell.horizon)
        exit_time = min(nominal_exit, flat)
        exit_bar = exact_row(session, exit_time)
        if entry is None or exit_bar is None or entry.raw_symbol != exit_bar.raw_symbol:
            continue
        prior = session[session["ts_et"] < decision]
        if prior.empty or decision - prior["ts_et"].iloc[-1] > pd.Timedelta(minutes=15):
            continue
        symbol = str(entry.raw_symbol)
        prior_contract = prior[prior["raw_symbol"] == symbol]
        if prior_contract.empty:
            continue
        last_close = float(prior_contract["close_ticks"].iloc[-1])
        record: dict[str, object] = {
            "trading_day": day,
            "target": float(exit_bar.open_ticks - entry.open_ticks),
        }
        for horizon in (5, 15, 30, 60, 120):
            old = asof_open(prior, decision - pd.Timedelta(minutes=horizon), symbol)
            record[f"ret_{horizon}"] = last_close - old

        session_start = decision_timestamp(day, "18:00")
        since_open = prior_contract[prior_contract["ts_et"] >= session_start]
        if len(since_open):
            record["ret_since_1800"] = (
                last_close - float(since_open.open_ticks.iloc[0])
                if since_open.ts_et.iloc[0] == session_start else np.nan
            )
            weights = since_open.volume.to_numpy(dtype=float)
            typical = (
                since_open.high_ticks.to_numpy(dtype=float)
                + since_open.low_ticks.to_numpy(dtype=float)
                + since_open.close_ticks.to_numpy(dtype=float)
            ) / 3.0
            record["vwap_distance"] = (
                last_close - np.average(typical, weights=weights)
                if weights.sum() > 0 else np.nan
            )
            low = float(since_open.low_ticks.min())
            high = float(since_open.high_ticks.max())
            record["range_position"] = (last_close - low) / (high - low) if high > low else 0.5
        else:
            record.update(ret_since_1800=np.nan, vwap_distance=np.nan, range_position=np.nan)

        last_61 = prior_contract.tail(61).close_ticks.to_numpy(dtype=float)
        record["rv60"] = (
            float(np.sqrt(np.mean(np.diff(last_61) ** 2))) if len(last_61) == 61 else np.nan
        )
        rows.append(record)

    result = pd.DataFrame(rows).sort_values("trading_day").reset_index(drop=True)
    # A causal norm: the current day's RV is divided only by the preceding 20 observations.
    norm = result["rv60"].shift(1).rolling(20, min_periods=20).mean()
    result["rv60_relative_20d"] = result["rv60"] / norm
    return result.drop(columns="rv60")


def ridge_pipeline(alpha: float):
    return make_pipeline(SimpleImputer(strategy="median"), StandardScaler(), Ridge(alpha=alpha))


def walk_forward(frame: pd.DataFrame, target: np.ndarray) -> tuple[np.ndarray, dict[int, float]]:
    x = frame.loc[:, FEATURE_COLUMNS].to_numpy(dtype=float)
    days = pd.to_datetime(frame.trading_day).to_numpy()
    years = pd.DatetimeIndex(days).year.to_numpy()
    prediction = np.full(len(frame), np.nan)
    selected: dict[int, float] = {}
    for test_year in range(2012, 2017):
        val_year = test_year - 1
        val = years == val_year
        inner_train = years < val_year
        outer_train = years < test_year
        test = years == test_year
        # One trading-day embargo at both fitting boundaries.
        if inner_train.any():
            last = np.max(days[inner_train])
            inner_train &= days != last
        if outer_train.any():
            last = np.max(days[outer_train])
            outer_train &= days != last
        if not (inner_train.any() and val.any() and outer_train.any() and test.any()):
            raise ValueError(f"empty walk-forward split for {test_year}")
        scores = []
        for alpha in ALPHAS:
            model = ridge_pipeline(alpha).fit(x[inner_train], target[inner_train])
            val_pred = model.predict(x[val])
            scores.append(float(np.mean(np.sign(val_pred) * target[val])))
        best = ALPHAS[int(np.argmax(scores))]
        selected[test_year] = best
        model = ridge_pipeline(best).fit(x[outer_train], target[outer_train])
        prediction[test] = model.predict(x[test])
    return prediction, selected


def metrics(frame: pd.DataFrame, target: np.ndarray, pred: np.ndarray) -> dict[str, float | int]:
    mask = np.isfinite(pred) & np.isfinite(target)
    y = target[mask]
    p = pred[mask]
    direction = np.sign(p)
    traded = direction != 0
    pnl = direction * y
    edge = float(pnl[traded].mean())
    se = float(pnl.std(ddof=1) / np.sqrt(len(pnl)))
    return {
        "valid_days": int(mask.sum()),
        "trades": int(traded.sum()),
        "ic": float(np.corrcoef(p, y)[0, 1]),
        "gross_edge_per_trade": edge,
        "t": float(pnl.mean() / se),
    }


def circular_within_year(frame: pd.DataFrame, target: np.ndarray, shift: int) -> np.ndarray:
    result = np.empty_like(target)
    years = pd.DatetimeIndex(frame.trading_day).year.to_numpy()
    for year in np.unique(years):
        idx = np.flatnonzero(years == year)
        result[idx] = np.roll(target[idx], shift)
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--raw", type=Path, default=RAW)
    parser.add_argument("--output", type=Path, default=OUT)
    parser.add_argument("--seed", type=int, default=20261017)
    args = parser.parse_args()

    bars = load_bars(args.raw)
    groups = {
        day: group.sort_values("ts_et").reset_index(drop=True)
        for day, group in bars.groupby("trading_day", sort=True)
    }
    del bars
    panels = {cell.name: build_cell(groups, cell) for cell in CELLS}

    main_rows = []
    fold_rows = []
    for cell in CELLS[:3]:
        frame = panels[cell.name]
        target = frame.target.to_numpy(dtype=float)
        pred, chosen = walk_forward(frame, target)
        main_rows.append({"cell": cell.name, **metrics(frame, target, pred)})
        fold_rows.extend(
            {"experiment": cell.name, "test_year": year, "alpha": alpha}
            for year, alpha in chosen.items()
        )

    control_frame = panels["14:35+flat"]
    original = control_frame.target.to_numpy(dtype=float)
    shift_rows = []
    for shift in (61, 127, 193):
        shifted = circular_within_year(control_frame, original, shift)
        pred, chosen = walk_forward(control_frame, shifted)
        result = metrics(control_frame, shifted, pred)
        shift_rows.append({"shift_days": shift, **result, "t_exceeds_3.5": result["t"] > 3.5})
        fold_rows.extend(
            {"experiment": f"shift_{shift}", "test_year": year, "alpha": alpha}
            for year, alpha in chosen.items()
        )

    rng = np.random.default_rng(args.seed)
    plant_rows = []
    for repetition in range(1, 11):
        chosen_features = list(rng.choice(RETURN_COLUMNS, size=3, replace=False))
        coefficients = rng.normal(size=3)
        signal_values = control_frame[chosen_features].to_numpy(dtype=float) @ coefficients
        signal = np.where(signal_values >= 0, 1.0, -1.0)
        planted = original + 10.402 * signal
        pred, chosen = walk_forward(control_frame, planted)
        result = metrics(control_frame, planted, pred)
        plant_rows.append(
            {
                "repetition": repetition,
                "features": ",".join(chosen_features),
                "coefficients": ",".join(f"{v:.10g}" for v in coefficients),
                **result,
                "t_exceeds_3.5": result["t"] > 3.5,
            }
        )
        fold_rows.extend(
            {"experiment": f"plant_{repetition}", "test_year": year, "alpha": alpha}
            for year, alpha in chosen.items()
        )

    main_df = pd.DataFrame(main_rows)
    shift_df = pd.DataFrame(shift_rows)
    plant_df = pd.DataFrame(plant_rows)
    summary = {
        "feature_conventions": {
            "decision_features": "bars with timestamps strictly before decision minute",
            "return": "last pre-decision close minus as-of bar open at decision-horizon; same entry contract",
            "vwap": "session-to-decision volume-weighted typical price; entry contract only",
            "rv_norm": "RMS one-minute close changes over 60 observations / mean of preceding 20 daily values",
            "entry_exit": "exact decision and exit minute opens; same contract; exact 16:05 flat",
            "t": "ordinary daily mean t-statistic",
        },
        "circular_any_t_exceeds_3.5": bool(shift_df["t_exceeds_3.5"].any()),
        "planted_share_t_gt_3.5": float(plant_df["t_exceeds_3.5"].mean()),
        "seed": args.seed,
    }
    args.output.mkdir(parents=True, exist_ok=True)
    main_df.to_csv(args.output / "part2_cells.csv", index=False)
    shift_df.to_csv(args.output / "part2_circular_shifts.csv", index=False)
    plant_df.to_csv(args.output / "part2_planted_edges.csv", index=False)
    pd.DataFrame(fold_rows).to_csv(args.output / "part2_selected_alphas.csv", index=False)
    for name, panel in panels.items():
        safe_name = name.replace(":", "").replace("+", "_")
        panel.to_parquet(args.output / f"part2_panel_{safe_name}.parquet")
    (args.output / "part2_summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print("MAIN")
    print(main_df.to_string(index=False))
    print("\nCIRCULAR SHIFTS")
    print(shift_df.to_string(index=False))
    print("\nPLANTED")
    print(plant_df.to_string(index=False))
    print("\nSUMMARY")
    print(json.dumps(summary, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
