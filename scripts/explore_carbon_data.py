from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from src.data.prepare_carbon import load_carbon


# Project paths
PROJECT_ROOT = Path(__file__).resolve().parents[1]

INPUT_FILE = (
    PROJECT_ROOT
    / "data"
    / "raw"
    / "carbon"
    / "india_west_carbon_intensity.csv"
)

OUTPUT_DIR = PROJECT_ROOT / "results" / "carbon_eda"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


def main():
    # Load and validate carbon-intensity data
    data = load_carbon(str(INPUT_FILE))

    data = data.copy()
    data["timestamp"] = pd.to_datetime(data["timestamp"], utc=True)

    # Extract time-based features for exploration
    data["hour"] = data["timestamp"].dt.hour
    data["date"] = data["timestamp"].dt.date

    # Summary statistics
    summary = data["carbon_intensity"].describe()

    print("\n--- CARBON INTENSITY SUMMARY ---")
    print(summary)

    print("\n--- DATASET INFORMATION ---")
    print("Number of records:", len(data))
    print("First timestamp:", data["timestamp"].min())
    print("Last timestamp:", data["timestamp"].max())
    print("Missing values:", data["carbon_intensity"].isna().sum())

    # Save summary statistics
    summary.to_csv(OUTPUT_DIR / "summary_statistics.csv", header=["value"])

    # 1. Carbon intensity over time
    plt.figure(figsize=(12, 5))
    plt.plot(
        data["timestamp"],
        data["carbon_intensity"],
        linewidth=1.5,
    )
    plt.title("Carbon Intensity Over Time — IN-WE")
    plt.xlabel("Timestamp (UTC)")
    plt.ylabel("Carbon Intensity (gCO2eq/kWh)")
    plt.xticks(rotation=30)
    plt.grid(True, alpha=0.3)
    plt.tight_layout()
    plt.savefig(OUTPUT_DIR / "carbon_intensity_over_time.png", dpi=150)
    plt.close()

    # 2. Average carbon intensity by hour of day
    hourly_average = data.groupby("hour")["carbon_intensity"].mean()

    plt.figure(figsize=(10, 5))
    plt.plot(
        hourly_average.index,
        hourly_average.values,
        marker="o",
    )
    plt.title("Average Carbon Intensity by Hour of Day")
    plt.xlabel("Hour of Day (UTC)")
    plt.ylabel("Average Carbon Intensity (gCO2eq/kWh)")
    plt.xticks(range(24))
    plt.grid(True, alpha=0.3)
    plt.tight_layout()
    plt.savefig(OUTPUT_DIR / "average_by_hour.png", dpi=150)
    plt.close()

    # 3. Daily average carbon intensity
    daily_average = data.groupby("date")["carbon_intensity"].mean()

    plt.figure(figsize=(10, 5))
    plt.plot(
        daily_average.index.astype(str),
        daily_average.values,
        marker="o",
    )
    plt.title("Daily Average Carbon Intensity")
    plt.xlabel("Date (UTC)")
    plt.ylabel("Average Carbon Intensity (gCO2eq/kWh)")
    plt.xticks(rotation=30)
    plt.grid(True, alpha=0.3)
    plt.tight_layout()
    plt.savefig(OUTPUT_DIR / "daily_average.png", dpi=150)
    plt.close()

    # 4. Distribution of carbon intensity
    plt.figure(figsize=(10, 5))
    plt.hist(
        data["carbon_intensity"],
        bins=20,
        edgecolor="black",
    )
    plt.title("Distribution of Carbon Intensity")
    plt.xlabel("Carbon Intensity (gCO2eq/kWh)")
    plt.ylabel("Frequency")
    plt.grid(True, axis="y", alpha=0.3)
    plt.tight_layout()
    plt.savefig(OUTPUT_DIR / "intensity_distribution.png", dpi=150)
    plt.close()

    # Save hourly and daily averages
    hourly_average.to_csv(
        OUTPUT_DIR / "average_by_hour.csv",
        header=["average_carbon_intensity"],
    )

    daily_average.to_csv(
        OUTPUT_DIR / "daily_average.csv",
        header=["average_carbon_intensity"],
    )

    print("\n--- EDA COMPLETE ---")
    print("Output folder:", OUTPUT_DIR)
    print("Generated 4 plots and 3 CSV summary files.")


if __name__ == "__main__":
    main()