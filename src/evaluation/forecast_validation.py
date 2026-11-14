"""Evaluate persisted rolling forecasts and report workload coverage.

This module deliberately evaluates recorded predictions; it does not relabel
historical predictions as forecasts available in a live deployment.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import time
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
CARBON = ROOT / "data/raw/carbon/india_west_carbon_intensity.csv"
FORECASTS = ROOT / "results/forecasting/rolling_seasonal_naive_forecasts.csv"
WORKLOAD = ROOT / "data/processed/workload/workload_cleaned.csv"
OUT = ROOT / "results/forecasting"
HOUR = pd.Timedelta(hours=1)


def validate_rolling_forecasts(forecasts: pd.DataFrame, carbon: pd.DataFrame) -> pd.DataFrame:
    """Validate origin/lead chronology, values, intervals, and observed target."""
    required = {
        "forecast_origin_utc", "timestamp_utc", "horizon_hours",
        "predicted_carbon_intensity", "lower_bound", "upper_bound",
        "actual_carbon_intensity",
    }
    missing = required - set(forecasts.columns)
    if missing:
        raise ValueError(f"Forecast data missing columns: {sorted(missing)}")
    f = forecasts.copy()
    for c in ("forecast_origin_utc", "timestamp_utc"):
        f[c] = pd.to_datetime(f[c], utc=True, errors="raise")
    for c in ("horizon_hours", "predicted_carbon_intensity", "lower_bound", "upper_bound", "actual_carbon_intensity"):
        f[c] = pd.to_numeric(f[c], errors="raise")
    if f[list(required)].isna().any().any():
        raise ValueError("Forecast records must not contain missing required values")
    if not np.isfinite(f[["horizon_hours", "predicted_carbon_intensity", "lower_bound", "upper_bound", "actual_carbon_intensity"]].to_numpy(dtype=float)).all():
        raise ValueError("Forecast values must be finite")
    if (f.horizon_hours < 1).any() or (f.horizon_hours % 1 != 0).any():
        raise ValueError("Forecast horizons must be positive integer hours")
    expected_target = f.forecast_origin_utc + pd.to_timedelta(f.horizon_hours, unit="h")
    if not expected_target.equals(f.timestamp_utc):
        raise ValueError("Forecast target timestamps do not match origin plus horizon")
    if f.duplicated(["forecast_origin_utc", "horizon_hours"]).any():
        raise ValueError("Duplicate origin/horizon predictions")
    if (f.forecast_origin_utc >= f.timestamp_utc).any():
        raise ValueError("Forecast origin must precede target")
    if (f.lower_bound > f.predicted_carbon_intensity).any() or (f.predicted_carbon_intensity > f.upper_bound).any():
        raise ValueError("Prediction intervals must enclose their point prediction")
    if (f.lower_bound < 0).any():
        raise ValueError("Carbon prediction interval lower bounds cannot be negative")
    observed = carbon.set_index("timestamp").carbon_intensity
    actual = f.timestamp_utc.map(observed)
    if actual.isna().any():
        raise ValueError("A forecast target has no observed carbon intensity")
    if not np.allclose(actual.to_numpy(dtype=float), f.actual_carbon_intensity.to_numpy(dtype=float)):
        raise ValueError("Persisted actuals disagree with the source carbon dataset")
    # Both baseline forecast values are computed from data available at the origin.
    by_time = carbon.set_index("timestamp").carbon_intensity
    f["baseline_persistence"] = f.forecast_origin_utc.map(by_time)
    f["baseline_seasonal_naive_24h"] = (f.timestamp_utc - pd.Timedelta(hours=24)).map(by_time)
    if f[["baseline_persistence", "baseline_seasonal_naive_24h"]].isna().any().any():
        raise ValueError("Insufficient historical observations to evaluate a baseline")
    if ((f.timestamp_utc - pd.Timedelta(hours=24)) > f.forecast_origin_utc).any():
        raise ValueError("Seasonal baseline input occurs after the forecast origin")
    if not np.allclose(f.predicted_carbon_intensity, f.baseline_seasonal_naive_24h):
        raise ValueError("Persisted model values do not reproduce the declared 24-hour Seasonal Naive method")
    f["covered"] = f.actual_carbon_intensity.between(f.lower_bound, f.upper_bound, inclusive="both")
    if "covered" in forecasts and not forecasts.covered.astype(bool).equals(f.covered):
        raise ValueError("Persisted interval coverage flags disagree with bounds and actuals")
    if "simulation_hour" in f:
        expected_hour = ((f.timestamp_utc - carbon.timestamp.min()).dt.total_seconds() / 3600).astype(int)
        if not f.simulation_hour.astype(int).equals(expected_hour):
            raise ValueError("simulation_hour does not align to the observed-carbon timeline")
    return f.sort_values(["forecast_origin_utc", "horizon_hours"], kind="stable").reset_index(drop=True)


def _metric_row(frame: pd.DataFrame, model: str, horizon: int | None = None) -> dict:
    y = frame.actual_carbon_intensity.to_numpy(float)
    p = frame[model].to_numpy(float)
    error = p - y
    row = {
        "model": {
            "predicted_carbon_intensity": "rolling_seasonal_naive_24h",
            "baseline_persistence": "persistence_at_origin",
            "baseline_seasonal_naive_24h": "seasonal_naive_24h_baseline",
        }[model],
        "horizon_hours": horizon if horizon is not None else "all",
        "prediction_count": len(frame),
        "mae": float(np.mean(np.abs(error))) if len(error) else None,
        "rmse": float(np.sqrt(np.mean(error**2))) if len(error) else None,
        "mean_error_bias": float(np.mean(error)) if len(error) else None,
    }
    if model == "predicted_carbon_intensity":
        row["prediction_interval_coverage"] = float(frame.covered.mean()) if len(frame) else None
        row["average_interval_width"] = float((frame.upper_bound - frame.lower_bound).mean()) if len(frame) else None
    else:
        row["prediction_interval_coverage"] = None
        row["average_interval_width"] = None
    return row


def evaluate_forecasts(forecasts: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    models = ["predicted_carbon_intensity", "baseline_persistence", "baseline_seasonal_naive_24h"]
    metrics = [_metric_row(forecasts.loc[forecasts.horizon_hours == h], m, int(h)) for h in sorted(forecasts.horizon_hours.unique()) for m in models]
    metrics.extend(_metric_row(forecasts, m) for m in models)
    origin = forecasts.groupby("forecast_origin_utc", sort=True).agg(
        prediction_count=("actual_carbon_intensity", "size"),
        interval_coverage=("covered", "mean"),
        average_interval_width=("upper_bound", lambda x: float("nan")),
    ).reset_index()
    widths = forecasts.assign(interval_width=forecasts.upper_bound - forecasts.lower_bound).groupby("forecast_origin_utc").interval_width.mean()
    origin["average_interval_width"] = origin.forecast_origin_utc.map(widths)
    return pd.DataFrame(metrics), origin


def audit_carbon_files() -> list[dict]:
    records = []
    timestamp_sets: dict[str, set[pd.Timestamp]] = {}
    for path in sorted((ROOT / "data/raw/carbon").rglob("*.csv")):
        d = pd.read_csv(path)
        name = str(path.relative_to(ROOT))
        if {"datetime", "zone", "carbonIntensity"} <= set(d.columns):
            t = pd.to_datetime(d.datetime, utc=True, errors="coerce")
            value = pd.to_numeric(d.carbonIntensity, errors="coerce")
            sorted_t = t.dropna().sort_values()
            deltas = sorted_t.diff().dropna()
            timestamp_sets[name] = set(t.dropna())
            records.append({
                "file": name, "rows": len(d), "format": "timestamp observation",
                "zone": ";".join(sorted(d.zone.dropna().astype(str).unique())),
                "timezone": "UTC (explicit Z/offset timestamps)", "unit": "gCO2eq/kWh per data_provenance.md; source unit not encoded in CSV",
                "first_utc": str(t.min()), "last_utc": str(t.max()), "frequency": str(deltas.mode().iloc[0]) if len(deltas) else "unknown",
                "duplicate_timestamps": int(t.duplicated().sum()), "missing_timestamps": int(t.isna().sum()),
                "missing_expected_intervals": int(max(0, round((sorted_t.max()-sorted_t.min()).total_seconds()/3600)+1-len(sorted_t))) if len(sorted_t) else None,
                "value_min": float(value.min()), "value_max": float(value.max()), "provenance": "Electricity Maps claimed by docs; original retrieval record absent",
            })
        elif {"from", "to", "carbon_intensity"} <= set(d.columns):
            start = pd.to_datetime(d["from"], utc=True, errors="coerce")
            end = pd.to_datetime(d["to"], utc=True, errors="coerce")
            duration = (end-start).dropna()
            valid_start = start.dropna().sort_values()
            interval = duration.mode().iloc[0] if len(duration) else pd.Timedelta(minutes=30)
            timestamp_sets[name] = set(start.dropna())
            records.append({
                "file": name, "rows": len(d), "format": "interval average", "zone": "not present",
                "timezone": "UTC (explicit offsets)", "unit": "not documented/verified", "first_utc": str(start.min()), "last_utc": str(end.max()),
                "frequency": str(duration.mode().iloc[0]) if len(duration) else "unknown", "duplicate_timestamps": int(start.duplicated().sum()),
                "missing_timestamps": int(start.isna().sum()), "missing_expected_intervals": int(max(0, round((valid_start.max()-valid_start.min())/interval)+1-len(valid_start))) if len(valid_start) else None, "value_min": float(d.carbon_intensity.min()),
                "value_max": float(d.carbon_intensity.max()), "provenance": "not documented; files are overlapping January 2025 interval data",
            })
    for record in records:
        own = timestamp_sets.get(record["file"], set())
        other_overlaps = {other: len(own & values) for other, values in timestamp_sets.items() if other != record["file"] and own & values}
        record["overlaps_with_other_files"] = json.dumps(other_overlaps, sort_keys=True)
    return records


def task_coverage(workload_path: Path, forecast_data: pd.DataFrame, carbon_rows: int, chunk_size: int = 100_000) -> dict:
    """Count full workload task coverage using the simulator's hour mapping."""
    sim_start = pd.Timestamp(forecast_data.timestamp_utc.min()) - pd.Timedelta(hours=int(forecast_data.simulation_hour.min()))
    origin_ranges = {}
    for origin, group in forecast_data.groupby("forecast_origin_utc"):
        leads = sorted(group.horizon_hours.astype(int).unique())
        if leads == list(range(1, len(leads) + 1)):
            origin_ranges[int((origin - sim_start).total_seconds() // 3600)] = (leads[0], leads[-1])
    counts = {k: 0 for k in ["total", "cpu_capacity_feasible", "cpu_over_capacity", "forecast_replay_eligible", "forecast_replay_ineligible", "actual_carbon_baseline_covered", "actual_carbon_baseline_uncovered", "forecast_ineligible_actual_covered", "forecast_eligible_actual_covered", "fallback_capacity_and_baseline_carbon_candidates"]}
    min_start = math.inf
    max_end = -math.inf
    for chunk in pd.read_csv(workload_path, chunksize=chunk_size):
        start = pd.to_numeric(chunk.start_time, errors="coerce")
        dur = pd.to_numeric(chunk.duration_seconds if "duration_seconds" in chunk else chunk.duration, errors="coerce")
        cpu = pd.to_numeric(chunk.cpu_cores, errors="coerce")
        first = np.floor(start / 3600).astype("int64")
        last = np.floor((start + dur - 1e-9).clip(lower=0) / 3600).astype("int64")
        origin_ix = first - 1
        eligible = np.zeros(len(chunk), dtype=bool)
        for o, (min_lead, max_lead) in origin_ranges.items():
            mask = origin_ix.to_numpy() == o
            eligible[mask] = (
                (first.to_numpy()[mask] >= o + min_lead)
                & (last.to_numpy()[mask] <= o + max_lead)
            )
        in_timeline = (start >= 0) & (start + dur <= carbon_rows * 3600)
        cpu_ok = cpu <= 8
        fallback_baseline_candidates = cpu_ok & in_timeline
        counts["total"] += len(chunk)
        counts["cpu_capacity_feasible"] += int(cpu_ok.sum())
        counts["cpu_over_capacity"] += int((~cpu_ok).sum())
        counts["forecast_replay_eligible"] += int(eligible.sum())
        counts["forecast_replay_ineligible"] += int((~eligible).sum())
        counts["actual_carbon_baseline_covered"] += int(in_timeline.sum())
        counts["actual_carbon_baseline_uncovered"] += int((~in_timeline).sum())
        counts["forecast_eligible_actual_covered"] += int((eligible & in_timeline).sum())
        counts["forecast_ineligible_actual_covered"] += int((~eligible & in_timeline).sum())
        counts["fallback_capacity_and_baseline_carbon_candidates"] += int(fallback_baseline_candidates.sum())
        min_start = min(min_start, float(start.min()))
        max_end = max(max_end, float((start+dur).max()))
    origins = forecast_data.forecast_origin_utc
    counts.update({"carbon_timeline_hours": carbon_rows, "forecast_target_window_start_utc": forecast_data.timestamp_utc.min().isoformat(), "forecast_target_window_end_utc": forecast_data.timestamp_utc.max().isoformat(), "forecast_origin_window_start_utc": origins.min().isoformat(), "forecast_origin_window_end_utc": origins.max().isoformat(), "forecast_replay_release_hour_buckets_start_utc": (origins.min()+HOUR).isoformat(), "forecast_replay_release_hour_buckets_end_utc": (origins.max()+HOUR).isoformat(), "forecast_targets": int(forecast_data.timestamp_utc.nunique()), "forecast_origins": int(forecast_data.forecast_origin_utc.nunique()), "forecast_horizons": sorted(forecast_data.horizon_hours.astype(int).unique().tolist()), "workload_min_start_seconds": min_start, "workload_max_end_seconds": max_end, "eligibility_definition": "baseline occupied-hour interval is covered by this task's historical rolling-origin forecast; origin is the preceding simulation-hour boundary", "fallback_definition": "fallback scheduler attempts original or capacity-feasible placement within configured delay; candidate count is CPU-feasible tasks whose baseline interval is wholly inside observed carbon coverage; actual capacity outcomes require simulation"})
    return counts


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--carbon", type=Path, default=CARBON)
    parser.add_argument("--forecasts", type=Path, default=FORECASTS)
    parser.add_argument("--workload", type=Path, default=WORKLOAD)
    parser.add_argument("--output", type=Path, default=OUT)
    parser.add_argument("--chunk-size", type=int, default=100_000)
    args = parser.parse_args(argv)
    started = time.perf_counter()
    carbon_raw = pd.read_csv(args.carbon)
    carbon = pd.DataFrame({"timestamp": pd.to_datetime(carbon_raw.datetime, utc=True), "carbon_intensity": pd.to_numeric(carbon_raw.carbonIntensity)})
    carbon = carbon.sort_values("timestamp").reset_index(drop=True)
    raw_forecasts = pd.read_csv(args.forecasts)
    clean = validate_rolling_forecasts(raw_forecasts, carbon)
    metrics, origins = evaluate_forecasts(clean)
    args.output.mkdir(parents=True, exist_ok=True)
    metrics.to_csv(args.output / "forecast_accuracy_by_horizon.csv", index=False)
    origins.to_csv(args.output / "forecast_coverage_by_origin.csv", index=False)
    coverage = task_coverage(args.workload, clean, len(carbon), args.chunk_size)
    coverage["forecast_records"] = len(clean)
    coverage["forecast_interval_coverage"] = float(clean.covered.mean())
    coverage["forecast_origin_precedes_target"] = bool((clean.forecast_origin_utc < clean.timestamp_utc).all())
    coverage["operational_issue_time_verified"] = False
    (args.output / "forecast_coverage.csv").write_text(pd.DataFrame([coverage]).to_csv(index=False), encoding="utf-8")
    inputs = audit_carbon_files()
    carbon_hash = hashlib.sha256(args.carbon.read_bytes()).hexdigest()
    forecast_hash = hashlib.sha256(args.forecasts.read_bytes()).hexdigest()
    summary = {"evaluation_type": "historical rolling-origin backtest; not live deployment", "carbon_source": str(args.carbon.relative_to(ROOT)), "carbon_sha256": carbon_hash, "forecast_source": str(args.forecasts.relative_to(ROOT)), "forecast_sha256": forecast_hash, "forecast_model": "seasonal_naive_24h", "training_split": "first 60% of 216 observations (129); calibration next 20% (43); rolling evaluation after observation 172", "calibration_method": "finite-sample 90% absolute-error quantile from 43 calibration residuals; symmetric interval, lower clipped at zero", "future_data_leakage_check": "passed: seasonal source timestamp is 24 hours before target and never after origin; persisted model predictions reproduce that source value", "evaluation_rows": len(clean), "elapsed_seconds": time.perf_counter()-started, "carbon_dataset_audit": inputs, "workload_coverage": coverage, "results": {"accuracy_csv": "forecast_accuracy_by_horizon.csv", "origin_coverage_csv": "forecast_coverage_by_origin.csv", "coverage_csv": "forecast_coverage.csv"}, "limitations": ["carbon file provenance lacks original retrieval URL/date/API response", "January interval datasets lack verified zone, unit, source, and overlap the main time window", "short 216-hour series; calibration residual dependence undermines nominal conformal guarantees", "forecast origins are replayed timestamps, not operational issue-time logs", "workload timestamps are simulation seconds mapped to carbon index, not real dates", "full simulation not run"]}
    (args.output / "forecast_evaluation_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    # Accuracy plot: point forecast and two baselines for each lead.
    plot = metrics.loc[metrics.horizon_hours != "all"].copy()
    plot["horizon_hours"] = plot.horizon_hours.astype(int)
    fig, ax = plt.subplots(figsize=(8, 4.5))
    for model, group in plot.groupby("model"):
        ax.plot(group.horizon_hours, group.mae, marker="o", label=model)
    ax.set(xlabel="Forecast horizon (hours)", ylabel="MAE (gCO2eq/kWh)", title="Historical rolling-origin forecast accuracy")
    ax.grid(alpha=.25); ax.legend(); fig.tight_layout(); fig.savefig(args.output / "forecast_accuracy_by_horizon.png", dpi=160); plt.close(fig)
    by_h = clean.groupby("horizon_hours").covered.mean()
    fig, ax = plt.subplots(figsize=(8, 4.5))
    ax.bar(by_h.index.astype(int), by_h.values * 100)
    ax.axhline(90, color="black", linestyle="--", label="Nominal interval level (90%)")
    ax.set(xticks=by_h.index.astype(int), xlabel="Forecast horizon (hours)", ylabel="Empirical coverage (%)", ylim=(0, 105), title="Prediction interval coverage by horizon")
    ax.grid(axis="y", alpha=.25); ax.legend(); fig.tight_layout(); fig.savefig(args.output / "forecast_interval_coverage.png", dpi=160); plt.close(fig)
    summary["elapsed_seconds"] = time.perf_counter() - started
    (args.output / "forecast_evaluation_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps({"metrics": metrics.to_dict(orient="records"), "coverage": coverage, "runtime_seconds": summary["elapsed_seconds"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
