
import pandas as pd

from src.data.hourly_emissions import allocate_hourly_emissions


def test_small_pipeline_smoke_test():
    workload = pd.DataFrame([
        {
            "job_name": "job1",
            "task_name": "task1",
            "start_time": 1800,
            "duration_seconds": 3600,
            "cpu_cores": 1,
            "energy_kwh": 0.01,
        }
    ])

    carbon = pd.DataFrame({
        "timestamp": pd.to_datetime([
            "2026-09-22T00:00:00Z",
            "2026-09-22T01:00:00Z",
        ]),
        "carbon_intensity": [500.0, 700.0],
    })

    result = allocate_hourly_emissions(workload, carbon)

    assert len(result) == 2
    assert abs(result["energy_kwh"].sum() - 0.01) < 1e-12
    assert abs(result["co2_g"].sum() - 6.0) < 1e-12
