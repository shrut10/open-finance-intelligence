import numpy as np
import pandas as pd
import pytest

from ofi.model import FEATURES, build_features, get_evaluation, get_forecast


def synthetic_frame():
    index = pd.period_range("2010-01", periods=60, freq="M")
    return pd.DataFrame(
        {
            "cpi": np.arange(60) / 10,
            "bank_rate": np.arange(60) / 20,
            "m4": np.arange(60) + 100,
            "unemployment": np.arange(60) / 30 + 3,
        },
        index=index,
    )


def test_future_observations_cannot_change_past_features():
    original = synthetic_frame()
    changed = original.copy()
    cutoff = pd.Period("2012-08", freq="M")
    changed.loc[cutoff:, :] = 999999
    original_features, changed_features = build_features(original), build_features(changed)
    pd.testing.assert_frame_equal(original_features.loc[:cutoff], changed_features.loc[:cutoff])


def test_publication_lags_are_enforced_for_each_source():
    frame = synthetic_frame()
    features = build_features(frame)
    target = pd.Period("2013-05", freq="M")
    row = features.loc[target]
    assert row.cpi_lag_1 == frame.loc[target - 1, "cpi"]
    assert row.bank_rate_lag_2 == frame.loc[target - 2, "bank_rate"]
    assert row.unemployment_lag_4 == frame.loc[target - 4, "unemployment"]
    assert row.m4_stock_growth_12_lag_2 == pytest.approx(
        (frame.loc[target - 2, "m4"] / frame.loc[target - 14, "m4"] - 1) * 100
    )


def test_missing_months_are_not_silently_filled_or_shifted():
    frame = synthetic_frame()
    with pytest.raises(ValueError, match="complete"):
        build_features(frame.drop(frame.index[10]))
    frame.loc[frame.index[-2], "cpi"] = np.nan
    assert np.isnan(build_features(frame).iloc[-1].cpi_lag_1)
    assert list(build_features(frame).columns) == FEATURES


def test_persisted_evaluation_agrees_with_predictions_and_selection_rule():
    result = get_evaluation()
    split = result["split"]
    assert (
        split["train_end"]
        < split["validation_start"]
        <= split["validation_end"]
        < split["test_start"]
    )
    winner = min(result["validation_metrics"], key=lambda item: item["mae"])["model"]
    assert result["selected_model"] == winner
    backtest = result["backtest"]
    error = np.array([r["actual"] - r["predicted"] for r in backtest])
    recorded = next(row for row in result["metrics"] if row["model"] == winner)
    assert recorded["mae"] == pytest.approx(np.mean(abs(error)), abs=1e-5)
    assert recorded["rmse"] == pytest.approx(np.sqrt(np.mean(error**2)), abs=1e-5)
    coverage = np.mean(
        [row["lower"] - 1e-6 <= row["actual"] <= row["upper"] + 1e-6 for row in backtest]
    )
    assert result["interval"]["test_coverage"] == pytest.approx(coverage, abs=1e-6)


def test_forecast_is_next_reference_month_with_disclosed_limitations():
    forecast, evaluation = get_forecast(), get_evaluation()
    assert (
        pd.Period(forecast["target_date"], freq="M")
        == pd.Period(forecast["last_observed_date"], freq="M") + 1
    )
    assert forecast["lower"] <= forecast["value"] <= forecast["upper"]
    assert forecast["model_name"] == evaluation["selected_model"]
    assert forecast["model_version"] == evaluation["model_version"]
    assert "nowcast" in forecast["forecast_kind"]
    assert "revised" in " ".join(evaluation["caveats"]).lower()
