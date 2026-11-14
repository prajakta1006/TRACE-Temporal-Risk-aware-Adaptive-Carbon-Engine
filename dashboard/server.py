"""Local, read-only dashboard server for TRACE result artifacts."""
from __future__ import annotations

import csv
import json
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
WEB = Path(__file__).resolve().parent
RUN = ROOT / "results/phase6/full_real_20261111_run1"
VALIDATION = ROOT / "results/phase6/independent_validation"


def read_json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def read_csv(path: Path, limit: int = 1000):
    try:
        with path.open(encoding="utf-8-sig", newline="") as stream:
            return list(csv.DictReader(stream))[:limit]
    except OSError:
        return []


def number(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def payload():
    result = read_json(RUN / "final_evaluation.json")
    config = read_json(RUN / "phase6_run_configuration.json")
    independent = read_json(VALIDATION / "independent_validation.json")
    cross_check = read_json(VALIDATION / "cross_check_report.json")
    emissions = read_json(VALIDATION / "emissions_recalculation.json")
    event_summary = read_json(RUN / "event_run_summary.json")
    validation_summary = read_json(ROOT / "results/validation/validation_summary.json")
    forecast_summary = read_json(ROOT / "results/forecasting/forecast_evaluation_summary.json")
    forecast_accuracy = read_csv(ROOT / "results/forecasting/forecast_accuracy_by_horizon.csv")
    forecast_coverage = read_csv(ROOT / "results/forecasting/forecast_coverage.csv", 2)
    uncertainty = read_csv(ROOT / "results/forecasting/uncertainty_metrics.csv", 4)
    carbon = read_csv(ROOT / "data/raw/carbon/india_west_carbon_intensity.csv", 1000)
    forecasts = read_csv(ROOT / "results/forecasting/rolling_seasonal_naive_forecasts.csv", 1000)
    intensities = [number(row.get("carbonIntensity")) for row in carbon]
    intensities = [value for value in intensities if value is not None]
    carbon_summary = ({"count": len(intensities), "min": min(intensities), "max": max(intensities),
                       "mean": sum(intensities) / len(intensities), "latest": intensities[-1],
                       "start": carbon[0].get("datetime"), "end": carbon[-1].get("datetime")} if intensities else None)
    return {"available": result is not None, "result": result, "config": config,
            "event_summary": event_summary, "independent": independent,
            "cross_check": cross_check, "emissions_recalculation": emissions,
            "validation_summary": validation_summary, "forecast_summary": forecast_summary,
            "forecast_accuracy": forecast_accuracy, "forecast_coverage": forecast_coverage,
            "uncertainty": uncertainty, "carbon_summary": carbon_summary,
            "carbon": carbon, "forecasts": forecasts,
            "artifact": "results/phase6/full_real_20261111_run1/final_evaluation.json"}


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(WEB), **kwargs)

    def do_GET(self):
        path = urlparse(self.path).path
        if path in ("/api/dashboard", "/api/health"):
            dashboard = payload()
            response = dashboard if path == "/api/dashboard" else {
                "ok": dashboard["available"],
                "validation_passed": bool(dashboard.get("independent", {}).get("completed")),
                "forecast_artifacts_available": bool(dashboard.get("forecast_summary")),
                "carbon_observations": (dashboard.get("carbon_summary") or {}).get("count", 0),
            }
            body = json.dumps(response).encode("utf-8")
            self.send_response(200 if dashboard["available"] else 503)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if urlparse(self.path).path == "/":
            self.path = "/index.html"
        super().do_GET()


if __name__ == "__main__":
    print("TRACE dashboard: http://127.0.0.1:8000")
    ThreadingHTTPServer(("127.0.0.1", 8000), Handler).serve_forever()
