"""Causal feature construction and read-only serving of audited model artifacts.

Training-only scientific libraries are deliberately imported inside functions.
The deployed API reads JSON and never loads pickle files or trains on requests.
"""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ARTIFACTS = ROOT / "artifacts"

FEATURES = [
    "cpi_lag_1",
    "cpi_lag_2",
    "cpi_lag_3",
    "cpi_lag_6",
    "cpi_lag_12",
    "cpi_momentum",
    "cpi_mean_3",
    "bank_rate_lag_2",
    "bank_rate_change_3",
    "m4_stock_growth_12_lag_2",
    "unemployment_lag_4",
    "unemployment_change_3",
    "month_sin",
    "month_cos",
]


def get_forecast() -> dict:
    return json.loads((ARTIFACTS / "forecast.json").read_text())


def get_evaluation() -> dict:
    return json.loads((ARTIFACTS / "model_evaluation.json").read_text())


def build_features(frame):
    """For target month t, use only lagged values and known calendar features.

    Caller supplies an uninterrupted monthly PeriodIndex. No forward/backward
    filling is allowed: a missing observation creates missing features and the
    model fails closed if its next forecast cannot be constructed.
    """
    import numpy as np
    import pandas as pd

    if not isinstance(frame.index, pd.PeriodIndex) or frame.index.freqstr != "M":
        raise ValueError("Features require a monthly PeriodIndex")
    if not frame.index.equals(pd.period_range(frame.index.min(), frame.index.max(), freq="M")):
        raise ValueError("Monthly input index must be complete and sorted")
    features = pd.DataFrame(index=frame.index)
    for lag in (1, 2, 3, 6, 12):
        features[f"cpi_lag_{lag}"] = frame.cpi.shift(lag)
    features["cpi_momentum"] = frame.cpi.shift(1) - frame.cpi.shift(2)
    features["cpi_mean_3"] = frame.cpi.shift(1).rolling(3).mean()
    features["bank_rate_lag_2"] = frame.bank_rate.shift(2)
    features["bank_rate_change_3"] = frame.bank_rate.shift(2) - frame.bank_rate.shift(5)
    features["m4_stock_growth_12_lag_2"] = (frame.m4.shift(2) / frame.m4.shift(14) - 1) * 100
    features["unemployment_lag_4"] = frame.unemployment.shift(4)
    features["unemployment_change_3"] = frame.unemployment.shift(4) - frame.unemployment.shift(7)
    features["month_sin"] = np.sin(2 * np.pi * frame.index.month / 12)
    features["month_cos"] = np.cos(2 * np.pi * frame.index.month / 12)
    return features[FEATURES].replace([np.inf, -np.inf], np.nan)
