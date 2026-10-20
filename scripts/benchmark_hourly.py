import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import importlib.util
import time

import pandas as pd

from src.data.hourly_emissions import allocate_hourly_emissions


backup_path = "src/data/hourly_emissions_backup.py"
spec = importlib.util.spec_from_file_location("old_hourly", backup_path)
old_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(old_module)

old_allocate = old_module.allocate_hourly_emissions

carbon = pd.DataFrame({
    "timestamp": pd.date_range(
        "2026-09-22", periods=216, freq="h", tz="UTC"
    ),
    "carbon_intensity": [500.0 + (i % 100) for i in range(216)],
})

n = 5000
workload = pd.DataFrame({
    "job_name": [f"job{i}" for i in range(n)],
    "task_name": ["task"] * n,
    "start_time": [(i * 97) % 700000 for i in range(n)],
    "duration_seconds": [1800 + (i % 7200) for i in range(n)],
    "energy_kwh": [0.01 + (i % 10) * 0.001 for i in range(n)],
})

# Keep the benchmark inside the available carbon window.
workload["start_time"] = workload["start_time"].clip(upper=760000)
workload["duration_seconds"] = workload["duration_seconds"].clip(
    upper=772800 - workload["start_time"]
)

results = {}

for name, function in [
    ("old", old_allocate),
    ("new", allocate_hourly_emissions),
]:
    start = time.perf_counter()
    result = function(workload, carbon)
    elapsed = time.perf_counter() - start

    results[name] = result
    print(f"{name} implementation: {elapsed:.3f} seconds")
    print(f"{name} output rows: {len(result)}")

old_result = results["old"]
new_result = results["new"]

old_energy = old_result["energy_kwh"].sum()
new_energy = new_result["energy_kwh"].sum()
old_emissions = old_result["co2_g"].sum()
new_emissions = new_result["co2_g"].sum()

print(f"Old total energy: {old_energy:.12f} kWh")
print(f"New total energy: {new_energy:.12f} kWh")
print(f"Old total emissions: {old_emissions:.12f} g")
print(f"New total emissions: {new_emissions:.12f} g")

assert len(old_result) == len(new_result)
assert abs(old_energy - new_energy) < 1e-9
assert abs(old_emissions - new_emissions) < 1e-8

print("Benchmark comparison passed.")
