"""Validación cruzada temporal del modelo de ventas (`scripts/sales_model_eval.py`).

Comprueba que `TimeSeriesSplit` preserva el orden cronológico en cada fold
(ningún índice de un fold posterior aparece antes que uno de un fold anterior),
que los folds no salen del conjunto de entrenamiento 2016-2023 y que las
features de lag/rolling no filtran información del fold de validación.

    python -m pytest tests/pipelines/test_sales_model_eval.py
"""

import numpy as np
import pandas as pd
import pytest

from scripts import sales_forecast as sf
from scripts import sales_model_eval as ev


@pytest.fixture(scope="module")
def train() -> pd.DataFrame:
    data, _ = sf.clean_sales(sf.load_sales())
    return sf.split_train_test(data)[0]


@pytest.fixture(scope="module")
def folds(train):
    return ev.time_series_folds(train)


def test_there_are_at_least_5_folds(folds):
    assert len(folds) >= 5


def test_each_fold_preserves_chronological_order(folds):
    for fold in folds:
        assert np.array_equal(fold["train_idx"], np.sort(fold["train_idx"]))
        assert np.array_equal(fold["val_idx"], np.sort(fold["val_idx"]))
        assert np.all(np.diff(fold["train_idx"]) == 1)
        assert np.all(np.diff(fold["val_idx"]) == 1)
        assert fold["train_idx"].max() < fold["val_idx"].min()
        assert fold["train_months"].max() < fold["val_months"].min()
        ev.check_fold(fold)


def test_no_index_of_a_later_fold_appears_before_an_earlier_fold(folds):
    for earlier, later in zip(folds, folds[1:]):
        assert later["val_idx"].min() > earlier["val_idx"].max()
        assert later["val_months"].min() > earlier["val_months"].max()
        # ventana creciente: el entrenamiento posterior contiene al anterior
        assert set(earlier["train_idx"]) < set(later["train_idx"])


def test_folds_validate_whole_training_years_and_never_touch_the_test_set(folds):
    assert [fold["val_months"].min().year for fold in folds] == [2019, 2020, 2021, 2022, 2023]
    assert all(len(fold["val_months"]) == 12 for fold in folds)
    assert max(fold["val_months"].max() for fold in folds) < pd.Timestamp("2024-01-01")


def test_check_fold_rejects_a_shuffled_fold(folds):
    shuffled = dict(folds[2])
    shuffled["val_idx"] = shuffled["val_idx"][::-1]
    with pytest.raises(AssertionError):
        ev.check_fold(shuffled)


def test_fold_history_stops_at_the_last_training_month(train, folds):
    series = ev.training_series(train)
    for fold in folds:
        history = ev.fold_history(series, fold)
        assert history.index.max() == fold["train_months"].max()
        assert not history.index.isin(fold["val_months"]).any()


def test_lag_and_rolling_features_do_not_leak_from_the_validation_fold(train, folds):
    """Si cambian los ingresos del fold de validación (y posteriores), ni la matriz
    de entrenamiento del fold ni su pronóstico se mueven."""
    series = ev.training_series(train)
    fold = folds[2]
    tampered = series.copy()
    tampered[tampered.index >= fold["val_months"].min()] *= 5

    original_history = ev.fold_history(series, fold)
    tampered_history = ev.fold_history(tampered, fold)
    pd.testing.assert_series_equal(original_history, tampered_history)

    frame = sf.build_training_frame(original_history.rename(sf.TARGET).reset_index())
    tampered_frame = sf.build_training_frame(tampered_history.rename(sf.TARGET).reset_index())
    pd.testing.assert_frame_equal(frame, tampered_frame)

    model = ev.fit_model(original_history, n_estimators=20)
    before = ev.fast_forecast(model, original_history, fold["val_months"])
    after = ev.fast_forecast(ev.fit_model(tampered_history, n_estimators=20), tampered_history, fold["val_months"])
    np.testing.assert_allclose(before, after)


def test_fast_forecast_matches_the_production_forecast(train):
    history = ev.training_series(train)
    months = pd.date_range("2024-01-01", periods=6, freq="MS")
    model = ev.fit_model(history, n_estimators=15)
    expected = sf.forecast(model, history, months)["prediction_eur"].to_numpy()
    np.testing.assert_allclose(ev.fast_forecast(model, history, months), expected)


def test_fit_model_with_current_params_matches_sales_forecast(train, monkeypatch):
    monkeypatch.setattr(sf, "N_ESTIMATORS", 15)
    history = ev.training_series(train)
    frame = sf.build_training_frame(train)
    expected = sf.train_model(train).predict(frame[sf.FEATURES])
    got = ev.fit_model(history, n_estimators=15).predict(frame[sf.FEATURES])
    np.testing.assert_allclose(got, expected)


def test_metrics_are_reported_as_mean_and_std():
    stat = ev.mean_std([1.0, 2.0, 3.0])
    assert stat == {"mean": 2.0, "std": 1.0}
    err = ev.errors([100.0, 200.0], [110.0, 190.0])
    assert err["mae_eur"] == 10.0 and err["rmse_eur"] == 10.0 and err["bias_eur"] == 0.0
