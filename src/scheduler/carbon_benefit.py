"""Calculate carbon savings and risk-adjusted savings for task placement."""

import pandas as pd


def calculate_carbon_benefit(
    energy_kwh: float,
    baseline_predicted: float,
    candidate_predicted: float,
    baseline_upper: float,
    candidate_upper: float,
    risk_weight: float = 0.5,
) -> dict:
    """
    Compare the original execution hour with a candidate execution hour.

    Carbon savings are calculated as:
        baseline emissions - candidate emissions

    The uncertainty penalty considers uncertainty in both hours:
        baseline uncertainty + candidate uncertainty

    Risk-adjusted savings are:
        expected savings - weighted uncertainty penalty

    A higher risk_weight makes the scheduler more conservative.
    """

    values = {
        "energy_kwh": energy_kwh,
        "baseline_predicted": baseline_predicted,
        "candidate_predicted": candidate_predicted,
        "baseline_upper": baseline_upper,
        "candidate_upper": candidate_upper,
    }

    for name, value in values.items():
        if pd.isna(value) or value < 0:
            raise ValueError(f"{name} must be a non-negative number.")

    if baseline_upper < baseline_predicted:
        raise ValueError("baseline_upper cannot be below baseline_predicted.")

    if candidate_upper < candidate_predicted:
        raise ValueError("candidate_upper cannot be below candidate_predicted.")

    if not 0.0 <= risk_weight <= 1.0:
        raise ValueError("risk_weight must be between 0 and 1.")

    baseline_emissions = energy_kwh * baseline_predicted
    candidate_emissions = energy_kwh * candidate_predicted

    expected_savings = baseline_emissions - candidate_emissions

    baseline_uncertainty = baseline_upper - baseline_predicted
    candidate_uncertainty = candidate_upper - candidate_predicted

    uncertainty_penalty = energy_kwh * (
        baseline_uncertainty + candidate_uncertainty
    )

    risk_adjusted_savings = (
        expected_savings - risk_weight * uncertainty_penalty
    )

    return {
        "baseline_emissions_g": baseline_emissions,
        "candidate_emissions_g": candidate_emissions,
        "expected_savings_g": expected_savings,
        "baseline_uncertainty": baseline_uncertainty,
        "candidate_uncertainty": candidate_uncertainty,
        "uncertainty_penalty_g": uncertainty_penalty,
        "risk_adjusted_savings_g": risk_adjusted_savings,
    }