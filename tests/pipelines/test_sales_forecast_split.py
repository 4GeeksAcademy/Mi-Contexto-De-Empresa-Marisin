"""Split 8/2 años y ausencia de fuga de datos del modelo de ventas (`scripts/sales_forecast.py`).

Usa el dataset real `data/raw/trackflow_sales.csv` (BRIEFING de TrackFlow:
120 meses de 2016-01 a 2025-12, fila `consolidated`).

    python -m pytest tests/pipelines/test_sales_forecast_split.py
"""

import numpy as np
import pandas as pd
import pytest

from scripts import sales_forecast as sf


@pytest.fixture(scope="module")
def sales() -> pd.DataFrame:
    data, _ = sf.clean_sales(sf.load_sales())
    return data


@pytest.fixture(scope="module")
def split(sales):
    return sf.split_train_test(sales)


def test_dataset_matches_briefing(sales):
    assert list(sf.load_sales().columns) == sf.EXPECTED_COLUMNS
    assert len(sales) == 120
    assert sales["month"].min() == pd.Timestamp("2016-01-01")
    assert sales["month"].max() == pd.Timestamp("2025-12-01")
    assert (sales["revenue_eur"] > 0).all()
    assert set(sales["market"]) == {"consolidated"}


def test_split_uses_first_8_years_for_train_and_last_2_for_test(split):
    train, test = split
    assert sorted(train["month"].dt.year.unique()) == list(range(2016, 2024))
    assert sorted(test["month"].dt.year.unique()) == [2024, 2025]
    assert len(train) == 8 * 12
    assert len(test) == 2 * 12


def test_split_has_no_overlap_and_respects_time_order(sales, split):
    train, test = split
    assert set(train["month"]).isdisjoint(set(test["month"]))
    assert train["month"].max() < test["month"].min()
    assert len(train) + len(test) == len(sales)


def test_split_rejects_a_dataset_without_exactly_10_years(sales):
    with pytest.raises(ValueError):
        sf.split_train_test(sales[sales["month"].dt.year < 2025])


def test_training_matrix_only_contains_training_months(split):
    train, test = split
    frame = sf.build_training_frame(train)
    assert frame["month"].max() < test["month"].min()
    assert len(frame) == len(train) - sf.MIN_HISTORY


def test_features_ignore_the_month_itself_and_any_future_value(sales):
    history = sales.set_index("month")["revenue_eur"]
    month = pd.Timestamp("2024-01-01")
    original = sf.features_for_month(month, history)
    tampered = history.copy()
    tampered[tampered.index >= month] *= 10  # 2024-2025 alterados
    assert sf.features_for_month(month, tampered) == original


def test_forecast_refuses_history_that_includes_test_months(sales, split):
    _, test = split
    model = sf.train_model(split[0])
    history = sales.set_index("month")["revenue_eur"]
    with pytest.raises(ValueError):
        sf.forecast(model, history, pd.DatetimeIndex(test["month"]))


def test_test_predictions_do_not_depend_on_real_test_values(split, monkeypatch):
    """Si cambiamos los ingresos reales de 2024-2025, la predicción no se mueve."""
    monkeypatch.setattr(sf, "N_ESTIMATORS", 20)
    train, test = split
    model = sf.train_model(train)
    history = train.set_index("month")["revenue_eur"]
    months = pd.DatetimeIndex(test["month"])
    before = sf.forecast(model, history, months)["prediction_eur"].to_numpy()

    tampered_test = test.assign(revenue_eur=test["revenue_eur"] * 3)
    tampered_train, _ = sf.split_train_test(pd.concat([train, tampered_test]))
    model_again = sf.train_model(tampered_train)
    after = sf.forecast(model_again, tampered_train.set_index("month")["revenue_eur"], months)
    np.testing.assert_allclose(before, after["prediction_eur"].to_numpy())


def test_model_is_reproducible_with_fixed_seed(split, monkeypatch):
    monkeypatch.setattr(sf, "N_ESTIMATORS", 20)
    train, test = split
    months = pd.DatetimeIndex(test["month"])[:6]
    history = train.set_index("month")["revenue_eur"]
    first = sf.forecast(sf.train_model(train), history, months)
    second = sf.forecast(sf.train_model(train), history, months)
    pd.testing.assert_frame_equal(first, second)


def test_clean_sales_fills_nulls_and_missing_months_by_interpolation(sales):
    broken = sales.copy()
    broken.loc[5, "revenue_eur"] = np.nan
    broken = broken.drop(index=10)  # un mes ausente
    clean, report = sf.clean_sales(broken)
    assert len(clean) == 120
    assert report["missing_months"] == 1
    assert report["nulls_before"]["revenue_eur"] == 1
    assert report["nulls_after"] == 0
    neighbours = sales.loc[[4, 6], "revenue_eur"].mean()
    assert clean.loc[5, "revenue_eur"] == pytest.approx(neighbours, rel=0.02)


def test_metrics_helpers():
    actual = np.array([1.0, 2.0, 3.0, 4.0])
    assert sf.normalized_gini(actual, actual) == pytest.approx(1.0)
    assert sf.normalized_gini(actual, actual[::-1]) < 0
    rng = np.random.default_rng(0)
    sample = rng.normal(size=500)
    assert sf.psi(sample, sample) == pytest.approx(0.0, abs=1e-9)
    assert sf.psi(sample, sample + 3) > 0.25
