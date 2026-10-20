
"""Simple CPU-based workload energy estimation.

Assumption: average CPU power is 10 watts per allocated CPU core.
This is an approximation, not a measurement of total server power.
"""

POWER_PER_CORE_WATTS = 10.0
WH_PER_KWH = 1000.0


def estimate_energy_kwh(
    duration_seconds: float,
    cpu_cores: float,
    power_per_core_watts: float = POWER_PER_CORE_WATTS,
) -> float:
    """Estimate CPU energy in kWh from duration and allocated cores."""
    if duration_seconds < 0:
        raise ValueError("duration_seconds cannot be negative")
    if cpu_cores < 0:
        raise ValueError("cpu_cores cannot be negative")
    if power_per_core_watts < 0:
        raise ValueError("power_per_core_watts cannot be negative")

    duration_hours = duration_seconds / 3600.0
    power_kw = cpu_cores * power_per_core_watts / WH_PER_KWH

    return power_kw * duration_hours


def estimate_co2_grams(
    energy_kwh: float,
    carbon_intensity_g_per_kwh: float,
) -> float:
    """Estimate emissions in grams of CO2-equivalent."""
    if energy_kwh < 0:
        raise ValueError("energy_kwh cannot be negative")
    if carbon_intensity_g_per_kwh < 0:
        raise ValueError("carbon intensity cannot be negative")

    return energy_kwh * carbon_intensity_g_per_kwh
