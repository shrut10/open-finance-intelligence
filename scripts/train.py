#!/usr/bin/env python3
"""Run chronological selection, untouched test evaluation, and final refit.

Run after build_data.py. No network or model pickle is needed.
"""

from __future__ import annotations

import hashlib
import json
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import duckdb  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from sklearn.ensemble import HistGradientBoostingRegressor  # noqa: E402
from sklearn.linear_model import Ridge  # noqa: E402
from sklearn.pipeline import make_pipeline  # noqa: E402
from sklearn.preprocessing import StandardScaler  # noqa: E402

from ofi.data import PARQUET, PROCESSED  # noqa: E402
from ofi.model import ARTIFACTS, FEATURES, build_features  # noqa: E402

TRAIN_END = "2018-12"
VALIDATION_END = "2021-12"
MODELS = ["Persistence", "Seasonal naive", "Ridge regression", "Gradient boosting"]
SEED = 42


def load_frame():
    with duckdb.connect(":memory:") as connection:
        observations = connection.execute(
            "SELECT series_id, date, value FROM read_parquet(?)", [str(PARQUET)]
        ).df()
    observations["month"] = observations.date.dt.to_period("M")
    frame = observations.pivot(index="month", columns="series_id", values="value")
    last_cpi = frame.cpi.last_valid_index()
    return frame.reindex(pd.period_range(frame.index.min(), last_cpi + 1, freq="M"))


def fit_model(name, features, target):
    if name in ("Persistence", "Seasonal naive"):
        return None
    if name == "Ridge regression":
        estimator = make_pipeline(StandardScaler(), Ridge(alpha=10.0))
    elif name == "Gradient boosting":
        estimator = HistGradientBoostingRegressor(
            max_iter=150,
            learning_rate=0.05,
            max_leaf_nodes=7,
            l2_regularization=10.0,
            early_stopping=False,
            random_state=SEED,
        )
    else:
        raise ValueError(name)
    return estimator.fit(features, target)


def predict(name, estimator, features):
    if name == "Persistence":
        return features.cpi_lag_1.to_numpy()
    if name == "Seasonal naive":
        return features.cpi_lag_12.to_numpy()
    return estimator.predict(features)


def metrics(actual, predicted):
    error = np.asarray(actual) - np.asarray(predicted)
    return {
        "mae": round(float(np.mean(abs(error))), 6),
        "rmse": round(float(np.sqrt(np.mean(error**2))), 6),
    }


def end_date(period):
    return period.end_time.date().isoformat()


def block_permutation_importance(name, estimator, features, target, repeats=30, block_length=3):
    """Permute contiguous 3-month blocks to retain some within-block structure.

    This is descriptive prediction sensitivity on test data, not causal effect.
    Correlated features and the block boundaries remain limitations.
    """
    generator = np.random.default_rng(SEED)
    actual = np.asarray(target)
    base_mae = np.mean(abs(actual - predict(name, estimator, features)))
    blocks = [
        np.arange(i, min(i + block_length, len(features)))
        for i in range(0, len(features), block_length)
    ]
    result = []
    for feature in FEATURES:
        differences = []
        for _ in range(repeats):
            order = np.concatenate([blocks[i] for i in generator.permutation(len(blocks))])
            perturbed = features.copy()
            perturbed[feature] = features[feature].to_numpy()[order]
            differences.append(
                np.mean(abs(actual - predict(name, estimator, perturbed))) - base_mae
            )
        result.append(
            {
                "feature": feature,
                "importance": round(float(np.mean(differences)), 6),
                "std": round(float(np.std(differences)), 6),
            }
        )
    return sorted(result, key=lambda item: item["importance"], reverse=True)


def train() -> tuple[dict, dict]:
    frame = load_frame()
    features = build_features(frame)
    usable = features.notna().all(axis=1) & frame.cpi.notna()
    x, y = features.loc[usable], frame.cpi.loc[usable]
    train_index = x.index <= pd.Period(TRAIN_END)
    validation_index = (x.index > pd.Period(TRAIN_END)) & (x.index <= pd.Period(VALIDATION_END))
    test_index = x.index > pd.Period(VALIDATION_END)
    if not (train_index.sum() >= 120 and validation_index.sum() >= 24 and test_index.sum() >= 24):
        raise ValueError("Insufficient observations for the fixed chronological split")
    x_train, y_train = x.loc[train_index], y.loc[train_index]
    x_val, y_val = x.loc[validation_index], y.loc[validation_index]
    x_test, y_test = x.loc[test_index], y.loc[test_index]
    val_results, val_predictions = [], {}
    for name in MODELS:
        fitted = fit_model(name, x_train, y_train)
        val_predictions[name] = predict(name, fitted, x_val)
        val_results.append({"model": name, **metrics(y_val, val_predictions[name])})
    # Selection is frozen before any test outcome is evaluated. Simpler models
    # win exact ties by the stable candidate order above.
    selected = min(val_results, key=lambda item: item["mae"])["model"]
    learned = min(
        (r for r in val_results if r["model"] not in ("Persistence", "Seasonal naive")),
        key=lambda item: item["mae"],
    )["model"]
    val_errors = abs(y_val.to_numpy() - val_predictions[selected])
    quantile_level = min(math.ceil((len(val_errors) + 1) * 0.9) / len(val_errors), 1.0)
    radius = float(np.quantile(val_errors, quantile_level, method="higher"))
    pretest = ~test_index
    fitted_models, test_predictions, test_metrics = {}, {}, []
    for name in MODELS:
        fitted_models[name] = fit_model(name, x.loc[pretest], y.loc[pretest])
        test_predictions[name] = predict(name, fitted_models[name], x_test)
        test_metrics.append({"model": name, **metrics(y_test, test_predictions[name])})
    champion_test = test_predictions[selected]
    metadata = json.loads((PROCESSED / "metadata.json").read_text())
    version = "v1-" + metadata["snapshot_sha256"][:12]
    caveats = [
        "Retrospective evaluation of one latest/revised snapshot, not a real-time vintage backtest. Publication lags reduce look-ahead risk but cannot remove historical revision leakage.",
        "A target-month estimate is made after prior-month CPI becomes available (typically within the target month). This is a next-observation forecast / current-month nowcast, not a forecast issued before that calendar month begins.",
        "Features for target month t use CPI through t−1; Bank Rate and M4 through t−2; unemployment through centre month t−4. No future values, interpolation or backward fills are used.",
        "MGSX is a rolling three-month unemployment estimate labelled by its centre month. Labour Force Survey quality/reweighting changes and overlap affect comparability.",
        "M4 is non-seasonally-adjusted money stock. Its simple 12-month stock growth is not the official flow-adjusted M4 growth rate and can reflect reporting breaks.",
        "The 90% interval uses validation absolute errors. Serial dependence, a short calibration window and structural change mean 90% coverage is not guaranteed. Test coverage is reported explicitly.",
        "One fixed chronological split and a small prespecified candidate set are used. Test results were not used to pick a winner, tune parameters, or calibrate intervals.",
        "Permutation importance is predictive sensitivity, not causality; correlated lag features can substitute for each other. No trading, monetary-policy or investment recommendation is implied.",
    ]
    evaluation = {
        "model_version": version,
        "snapshot_retrieved_at": metadata["retrieved_at"],
        "target": "UK all-items CPI annual inflation rate",
        "unit": "percentage points",
        "split": {
            "train_start": end_date(x_train.index[0]),
            "train_end": end_date(x_train.index[-1]),
            "validation_start": end_date(x_val.index[0]),
            "validation_end": end_date(x_val.index[-1]),
            "test_start": end_date(x_test.index[0]),
            "test_end": end_date(x_test.index[-1]),
        },
        "sample_sizes": {"train": len(x_train), "validation": len(x_val), "test": len(x_test)},
        "selection_rule": "Lowest validation MAE; test outcomes never select the served model.",
        "validation_metrics": val_results,
        "metrics": test_metrics,
        "selected_model": selected,
        "best_learned_model_on_validation": learned,
        "importance_model": selected,
        "importance_method": "Test MAE increase under 30 seeded permutations of contiguous 3-month blocks; percentage points.",
        "importance": block_permutation_importance(
            selected, fitted_models[selected], x_test, y_test
        ),
        "learned_model_importance": block_permutation_importance(
            learned, fitted_models[learned], x_test, y_test
        ),
        "interval": {
            "nominal_coverage": 0.9,
            "radius": round(radius, 6),
            "calibration_period": "2019–2021 validation",
            "calibration_n": len(val_errors),
            "test_coverage": round(
                float(np.mean(abs(y_test.to_numpy() - champion_test) <= radius + 1e-12)), 6
            ),
            "test_mean_width": round(2 * radius, 6),
        },
        "backtest": [
            {
                "date": end_date(period),
                "actual": float(actual),
                "predicted": round(float(predicted), 6),
                "lower": round(float(predicted - radius), 6),
                "upper": round(float(predicted + radius), 6),
            }
            for period, actual, predicted in zip(x_test.index, y_test, champion_test)
        ],
        "caveats": caveats,
    }
    selected_test_mae = next(item["mae"] for item in test_metrics if item["model"] == selected)
    baseline_test_mae = next(item["mae"] for item in test_metrics if item["model"] == "Persistence")
    evaluation["baseline_comparison"] = {
        "baseline": "Persistence",
        "selected_model_test_mae": selected_test_mae,
        "baseline_test_mae": baseline_test_mae,
        "mae_improvement_percent": round(
            (baseline_test_mae - selected_test_mae) / baseline_test_mae * 100, 3
        ),
        "outperforms_baseline_on_test": selected_test_mae < baseline_test_mae,
    }
    evaluation["deployment_assessment"] = (
        "Research demonstration only. The validation-selected model underperforms persistence on the test period; it is not approved for decision-making."
        if selected_test_mae >= baseline_test_mae
        else "Research demonstration only. Lower test MAE in this single retrospective split does not establish real-time production performance."
    )
    next_period = frame.cpi.last_valid_index() + 1
    next_features = features.loc[[next_period]]
    if next_features.isna().any().any():
        missing = next_features.columns[next_features.isna().any()].tolist()
        raise ValueError(f"Cannot issue forecast: missing lagged features {missing}")
    final_fit = fit_model(selected, x, y)
    forecast_value = float(predict(selected, final_fit, next_features)[0])
    forecast = {
        "target": "UK CPI annual inflation — next observation",
        "target_series_id": "cpi",
        "target_date": end_date(next_period),
        "as_of": metadata["retrieved_at"][:10],
        "value": round(forecast_value, 6),
        "lower": round(forecast_value - radius, 6),
        "upper": round(forecast_value + radius, 6),
        "interval_label": "Nominal 90% empirical interval (validation errors; coverage not guaranteed)",
        "model_name": selected,
        "model_version": version,
        "unit": "% year on year",
        "last_observed_value": float(frame.cpi.dropna().iloc[-1]),
        "last_observed_date": end_date(frame.cpi.last_valid_index()),
        "caveat": "Current-month nowcast / next CPI observation. Revised snapshot, not a real-time vintage study. Model selected by validation MAE; empirical uncertainty can under-cover during shocks.",
        "forecast_kind": "next-observation forecast / current-month nowcast",
        "snapshot_retrieved_at": metadata["retrieved_at"],
        "trained_through": end_date(y.index[-1]),
        "features": {column: round(float(next_features[column].iloc[0]), 6) for column in FEATURES},
        "deployment_assessment": evaluation["deployment_assessment"],
    }
    ARTIFACTS.mkdir(exist_ok=True)
    (ARTIFACTS / "forecast.json").write_text(json.dumps(forecast, indent=2, allow_nan=False) + "\n")
    (ARTIFACTS / "model_evaluation.json").write_text(
        json.dumps(evaluation, indent=2, allow_nan=False) + "\n"
    )
    model_record = {
        "version": version,
        "selection": selected,
        "best_learned": learned,
        "random_seed": SEED,
        "features": FEATURES,
        "candidate_parameters": {
            "Ridge regression": {"alpha": 10.0, "scaling": "standardise on training data only"},
            "Gradient boosting": {
                "max_iter": 150,
                "learning_rate": 0.05,
                "max_leaf_nodes": 7,
                "l2_regularization": 10.0,
                "early_stopping": False,
            },
        },
        "training_snapshot_sha256": metadata["snapshot_sha256"],
        "code_sha256": hashlib.sha256(
            Path(__file__).read_bytes()
            + (Path(__file__).resolve().parents[1] / "src/ofi/model.py").read_bytes()
        ).hexdigest(),
        "dependencies": {
            "numpy": np.__version__,
            "pandas": pd.__version__,
            "sklearn": __import__("sklearn").__version__,
        },
        "serving": "Precomputed JSON forecast only. No arbitrary horizon or on-request retraining.",
    }
    (ARTIFACTS / "model_manifest.json").write_text(json.dumps(model_record, indent=2) + "\n")
    return forecast, evaluation


if __name__ == "__main__":
    forecast, evaluation = train()
    print(
        json.dumps(
            {
                "selected_model": evaluation["selected_model"],
                "validation_metrics": evaluation["validation_metrics"],
                "test_metrics": evaluation["metrics"],
                "interval": evaluation["interval"],
                "forecast": forecast,
            },
            indent=2,
        )
    )
