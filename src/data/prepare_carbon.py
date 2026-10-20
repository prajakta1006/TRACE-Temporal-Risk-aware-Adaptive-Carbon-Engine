
"""Load and validate carbon-intensity data."""

from pathlib import Path

import pandas as pd


def load_carbon(
    csv_path: str | Path,
    zone: str = "IN-WE",
) -> pd.DataFrame:
    """Load carbon intensity for one zone and report hourly gaps."""
    path = Path(csv_path)

    if not path.is_file():
        raise FileNotFoundError(f"Carbon data file not found: {path}")

    df = pd.read_csv(path)

    required = {"zone", "datetime", "carbonIntensity"}
    missing = required - set(df.columns)

    if missing:
        raise ValueError(f"Missing required columns: {sorted(missing)}")

    df = df.loc[df["zone"] == zone].copy()

    if df.empty:
        raise ValueError(f"No carbon data found for zone {zone!r}")

    df["timestamp"] = pd.to_datetime(
        df["datetime"], utc=True, errors="raise"
    )
    df["carbon_intensity"] = pd.to_numeric(
        df["carbonIntensity"], errors="raise"
    )

    if df[["timestamp", "carbon_intensity"]].isna().any().any():
        raise ValueError("Carbon data contains missing values")

    if (df["carbon_intensity"] < 0).any():
        raise ValueError("Carbon intensity cannot be negative")

    if df["timestamp"].duplicated().any():
        raise ValueError("Duplicate carbon timestamps found")

    df = df.sort_values("timestamp").reset_index(drop=True)

    # Check whether timestamps follow an hourly interval.
    intervals = df["timestamp"].diff().dropna()
    irregular = intervals != pd.Timedelta(hours=1)

    print(f"Zone: {zone}")
    print(f"Records: {len(df)}")
    print(f"First timestamp: {df['timestamp'].min()}")
    print(f"Last timestamp: {df['timestamp'].max()}")
    print(f"Non-hourly intervals: {int(irregular.sum())}")

    return df[["timestamp", "zone", "carbon_intensity"]]
