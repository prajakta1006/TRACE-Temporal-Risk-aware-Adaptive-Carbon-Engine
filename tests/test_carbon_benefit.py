import pytest

from src.scheduler.carbon_benefit import calculate_carbon_benefit


def test_calculate_carbon_benefit():
    result = calculate_carbon_benefit(
        energy_kwh=0.02,
        baseline_predicted=600,
        candidate_predicted=450,
        baseline_upper=650,
        candidate_upper=500,
        risk_weight=0.5,
    )

    assert result["baseline_emissions_g"] == pytest.approx(12.0)
    assert result["candidate_emissions_g"] == pytest.approx(9.0)
    assert result["expected_savings_g"] == pytest.approx(3.0)
    assert result["uncertainty_penalty_g"] == pytest.approx(2.0)
    assert result["risk_adjusted_savings_g"] == pytest.approx(2.0)


def test_zero_risk_weight():
    result = calculate_carbon_benefit(
        energy_kwh=0.02,
        baseline_predicted=600,
        candidate_predicted=450,
        baseline_upper=650,
        candidate_upper=500,
        risk_weight=0,
    )

    assert result["risk_adjusted_savings_g"] == pytest.approx(3.0)


def test_invalid_risk_weight():
    with pytest.raises(ValueError):
        calculate_carbon_benefit(
            energy_kwh=0.02,
            baseline_predicted=600,
            candidate_predicted=450,
            baseline_upper=650,
            candidate_upper=500,
            risk_weight=1.5,
        )


def test_upper_bound_below_prediction():
    with pytest.raises(ValueError):
        calculate_carbon_benefit(
            energy_kwh=0.02,
            baseline_predicted=600,
            candidate_predicted=450,
            baseline_upper=550,
            candidate_upper=500,
        )


def test_negative_energy():
    with pytest.raises(ValueError):
        calculate_carbon_benefit(
            energy_kwh=-0.02,
            baseline_predicted=600,
            candidate_predicted=450,
            baseline_upper=650,
            candidate_upper=500,
        )