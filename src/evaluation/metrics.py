
import numpy as np
import pandas as pd


def calculate_metrics(actual, predicted):
    """
    Calculate MAE, RMSE and sMAPE.
    """

    actual = np.asarray(actual, dtype=float)
    predicted = np.asarray(predicted, dtype=float)

    if len(actual) != len(predicted):
        raise ValueError("Actual and predicted arrays must have equal length.")

    if len(actual) == 0:
        raise ValueError("Cannot evaluate empty arrays.")

    if not np.isfinite(actual).all() or not np.isfinite(predicted).all():
        raise ValueError("Inputs must contain only finite values.")

    errors = actual - predicted

    mae = np.mean(np.abs(errors))
    rmse = np.sqrt(np.mean(errors ** 2))

    denominator = np.abs(actual) + np.abs(predicted)
    valid = denominator != 0

    smape = np.mean(
        2 * np.abs(errors[valid]) / denominator[valid]
    ) * 100 if valid.any() else 0.0

    return {
        "MAE": mae,
        "RMSE": rmse,
        "sMAPE": smape,
    }
