"""Modelo de predicción de ventas de TrackFlow (Random Forest).

Ticket del tech lead a partir de la RFI de Finanzas: ¿es viable predecir los
ingresos de los próximos meses con un margen de error aceptable antes de
construir el dashboard ejecutivo de Thomas?

Fuente de verdad: BRIEFING de sales-forecasting de TrackFlow
(`content/contexts/sales-forecasting/trackflow/trackflow-BRIEFING.es.md` del
syllabus de 4Geeks). Dataset: `data/raw/trackflow_sales.csv`, 120 meses
(2016-01 → 2025-12), fila `consolidated`, target `revenue_eur`.

Criterio de elección del algoritmo — Random Forest y no XGBoost
---------------------------------------------------------------
* **Tamaño de los datos.** Tras construir los lags quedan 72 meses de
  entrenamiento. Con tan pocas filas, el boosting (que corrige el error árbol
  tras árbol) tiende a sobreajustar si no se afina con cuidado
  (learning rate, profundidad, early stopping… y no hay datos para una
  validación temporal seria). El bagging de Random Forest promedia árboles
  independientes y es robusto con sus valores por defecto.
* **Explicabilidad.** El stakeholder es Finanzas: "300 árboles, cada uno
  entrenado con una muestra distinta del histórico, y la predicción es su
  media" se explica en una frase, y la importancia de cada variable sale
  directamente del modelo.
* **Rango de variabilidad gratis.** Cada árbol proyecta su propio escenario de
  24 meses; el abanico entre el percentil 10 y el 90 de esos escenarios es la
  banda de variabilidad que pide el ticket, sin modelos auxiliares.
* **Tiempo de ajuste.** Es un estudio de viabilidad: Random Forest da una
  línea base honesta sin búsqueda de hiperparámetros. XGBoost queda como
  siguiente paso si Finanzas necesita más precisión.

Limitación de los árboles y cómo se resuelve
--------------------------------------------
Un árbol nunca predice fuera del rango que vio al entrenar, y los ingresos de
2024-2025 son mayores que cualquier mes de 2016-2023 (crecimiento del 3-9 %
anual). Por eso el modelo **no predice euros**, sino el **ratio interanual**
`revenue_t / revenue_{t-12}` (≈ 1,03-1,10), que sí está dentro del rango de
entrenamiento. La predicción en euros se reconstruye multiplicando por el
ingreso del mismo mes del año anterior.

Evaluación honesta (sin fuga de datos)
--------------------------------------
* Split 8/2 por años naturales: 2016-2023 entrenamiento, 2024-2025 prueba.
* Todas las features de un mes usan solo meses anteriores (lags causales).
* El pronóstico de prueba es **recursivo a 24 meses**: el modelo nunca ve un
  ingreso real de 2024-2025; cuando necesita un mes de prueba como lag, usa su
  propia predicción. Es el escenario real de Finanzas (predecir sin conocer el
  futuro).
* El escalado se ajusta solo con el conjunto de entrenamiento.

Uso::

    python scripts/sales_forecast.py
    python scripts/sales_forecast.py --output-dir docs/sales-forecast
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestRegressor
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

ROOT = Path(__file__).resolve().parents[1]
CSV_PATH = ROOT / "data" / "raw" / "trackflow_sales.csv"
OUTPUT_DIR = ROOT / "docs" / "sales-forecast"

# Columnas exactas del BRIEFING (§2).
DATE_COLUMN = "month"
TARGET = "revenue_eur"
EXPECTED_COLUMNS = [
    "month",
    "revenue_eur",
    "shipments_processed",
    "avg_revenue_per_shipment_eur",
    "market",
]
NUMERIC_COLUMNS = ["revenue_eur", "shipments_processed", "avg_revenue_per_shipment_eur"]
MARKET = "consolidated"

TRAIN_YEARS = 8
TEST_YEARS = 2
RANDOM_STATE = 42
N_ESTIMATORS = 300
MIN_SAMPLES_LEAF = 2
# Meses de historia que necesita la feature más larga (trailing_growth).
MIN_HISTORY = 24
BAND_PERCENTILES = (10, 90)
PSI_BINS = 5

# Estacionalidad del BRIEFING (§4): pico Black Friday/Navidad y valle de febrero.
PEAK_MONTHS = (11, 12)
LOW_MONTH = 2

FEATURES = [
    "month_sin",
    "month_cos",
    "is_peak_season",
    "is_february",
    "yoy_same_month_last_year",
    "yoy_last_month",
    "trailing_growth",
    "seasonal_index_last_year",
]


# --------------------------------------------------------------------------- #
# Preparación de datos
# --------------------------------------------------------------------------- #
def load_sales(path: Path = CSV_PATH) -> pd.DataFrame:
    """Carga el CSV, valida las columnas del BRIEFING y devuelve la fila consolidada."""
    df = pd.read_csv(path)
    missing = [column for column in EXPECTED_COLUMNS if column not in df.columns]
    if missing:
        raise ValueError(f"Faltan columnas del BRIEFING en {path.name}: {missing}")
    df = df[df["market"] == MARKET].copy()
    if df.empty:
        raise ValueError(f"No hay filas con market == '{MARKET}'")
    df[DATE_COLUMN] = pd.to_datetime(df[DATE_COLUMN])
    return df.sort_values(DATE_COLUMN).reset_index(drop=True)


def clean_sales(df: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    """Trata nulos y meses faltantes sin romper la estacionalidad.

    * Reindexa a una serie mensual completa (un mes ausente pasa a ser nulo).
    * Ingresos/envíos nulos o no positivos → interpolación lineal en el tiempo
      entre los meses vecinos (no se usa la media global, que aplanaría los
      picos de noviembre-diciembre).
    * `avg_revenue_per_shipment_eur` se recalcula a partir de las otras dos.
    """
    data = df.set_index(DATE_COLUMN)
    full_index = pd.date_range(data.index.min(), data.index.max(), freq="MS")
    report = {
        "rows_in": int(len(df)),
        "missing_months": int(len(full_index.difference(data.index))),
        "nulls_before": {c: int(data[c].isna().sum()) for c in NUMERIC_COLUMNS},
    }
    data = data.reindex(full_index)
    for column in ("revenue_eur", "shipments_processed"):
        data[column] = pd.to_numeric(data[column], errors="coerce")
        data.loc[data[column] <= 0, column] = np.nan
        data[column] = data[column].interpolate(method="time", limit_direction="both")
    recomputed = data["revenue_eur"] / data["shipments_processed"]
    data["avg_revenue_per_shipment_eur"] = (
        pd.to_numeric(data["avg_revenue_per_shipment_eur"], errors="coerce")
        .fillna(recomputed.round(2))
    )
    data["market"] = MARKET
    data["shipments_processed"] = data["shipments_processed"].round().astype(int)
    data.index.name = DATE_COLUMN
    clean = data.reset_index()
    report["rows_out"] = int(len(clean))
    report["nulls_after"] = int(clean[NUMERIC_COLUMNS].isna().sum().sum())
    if (clean[TARGET] <= 0).any():
        raise ValueError("revenue_eur debe ser positivo en todos los meses")
    return clean, report


def split_train_test(
    df: pd.DataFrame, train_years: int = TRAIN_YEARS, test_years: int = TEST_YEARS
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Split temporal por años naturales: los primeros 8 entrenan, los 2 últimos prueban."""
    years = sorted(df[DATE_COLUMN].dt.year.unique())
    if len(years) != train_years + test_years:
        raise ValueError(
            f"Se esperaban {train_years + test_years} años y hay {len(years)}: {years}"
        )
    train_set = set(years[:train_years])
    is_train = df[DATE_COLUMN].dt.year.isin(train_set)
    train = df[is_train].reset_index(drop=True)
    test = df[~is_train].reset_index(drop=True)
    if train[DATE_COLUMN].max() >= test[DATE_COLUMN].min():
        raise ValueError("El entrenamiento no puede contener meses posteriores a la prueba")
    return train, test


# --------------------------------------------------------------------------- #
# Features causales
# --------------------------------------------------------------------------- #
def features_for_month(month: pd.Timestamp, history: pd.Series) -> dict:
    """Features de un mes usando SOLO la historia estrictamente anterior a `month`.

    `history` es la serie mensual de ingresos indexada por fecha; puede contener
    predicciones en lugar de reales (pronóstico recursivo).
    """
    past = history[history.index < month]
    if len(past) < MIN_HISTORY:
        raise ValueError(f"{month:%Y-%m} necesita {MIN_HISTORY} meses de historia")

    def lag(k: int) -> float:
        return float(past[month - pd.DateOffset(months=k)])

    last_12 = past.iloc[-12:].sum()
    previous_12 = past.iloc[-24:-12].sum()
    window_last_year = past.iloc[-23:-11]  # 12 meses centrados en t-12 por la izquierda
    return {
        "month_sin": np.sin(2 * np.pi * month.month / 12),
        "month_cos": np.cos(2 * np.pi * month.month / 12),
        "is_peak_season": int(month.month in PEAK_MONTHS),
        "is_february": int(month.month == LOW_MONTH),
        # Crecimiento interanual del mismo mes el año pasado: capta la
        # alternancia 9 % / 3 % del BRIEFING.
        "yoy_same_month_last_year": lag(12) / lag(24),
        # Crecimiento interanual del último mes conocido.
        "yoy_last_month": lag(1) / lag(13),
        # Crecimiento anual acumulado (12 meses vs. 12 anteriores).
        "trailing_growth": last_12 / previous_12,
        # Peso del mismo mes el año pasado frente a la media de su año.
        "seasonal_index_last_year": lag(12) / window_last_year.mean(),
    }


def target_ratio(month: pd.Timestamp, history: pd.Series) -> float:
    """Target del modelo: ratio interanual revenue_t / revenue_{t-12}."""
    return float(history[month] / history[month - pd.DateOffset(months=12)])


def build_training_frame(train: pd.DataFrame) -> pd.DataFrame:
    """Matriz X/y del entrenamiento (los 24 primeros meses solo aportan historia)."""
    history = train.set_index(DATE_COLUMN)[TARGET]
    rows = []
    for month in history.index[MIN_HISTORY:]:
        row = features_for_month(month, history)
        row[DATE_COLUMN] = month
        row["target_ratio"] = target_ratio(month, history)
        rows.append(row)
    return pd.DataFrame(rows)


# --------------------------------------------------------------------------- #
# Modelo y pronóstico
# --------------------------------------------------------------------------- #
def train_model(train: pd.DataFrame, random_state: int = RANDOM_STATE) -> Pipeline:
    """Escalado (ajustado solo con train) + Random Forest con semilla fija.

    Random Forest es invariante a la escala (cada split compara una variable
    consigo misma), así que el StandardScaler no cambia la predicción: se deja
    en el pipeline para cumplir el requisito de escalado y para que el modelo
    sea intercambiable por uno sensible a magnitudes sin tocar el resto.
    """
    frame = build_training_frame(train)
    model = Pipeline(
        [
            ("scaler", StandardScaler()),
            (
                "forest",
                RandomForestRegressor(
                    n_estimators=N_ESTIMATORS,
                    min_samples_leaf=MIN_SAMPLES_LEAF,
                    random_state=random_state,
                    n_jobs=1,
                ),
            ),
        ]
    )
    model.fit(frame[FEATURES], frame["target_ratio"])
    return model


def forecast(model: Pipeline, history: pd.Series, months: pd.DatetimeIndex) -> pd.DataFrame:
    """Pronóstico recursivo: cada árbol proyecta su propio escenario mes a mes.

    `history` solo debe contener meses anteriores a `months[0]` (el
    entrenamiento). La predicción puntual es la media de los escenarios y la
    banda de variabilidad, sus percentiles 10 y 90.
    """
    if (history.index >= months[0]).any():
        raise ValueError("La historia del pronóstico no puede incluir meses a predecir")
    scaler = model.named_steps["scaler"]
    trees = model.named_steps["forest"].estimators_
    paths = np.empty((len(trees), len(months)))
    for i, tree in enumerate(trees):
        path = history.copy()
        for j, month in enumerate(months):
            x = pd.DataFrame([features_for_month(month, path)])[FEATURES]
            ratio = float(tree.predict(scaler.transform(x))[0])
            value = ratio * float(path[month - pd.DateOffset(months=12)])
            path.loc[month] = value
            paths[i, j] = value
    low, high = np.percentile(paths, BAND_PERCENTILES, axis=0)
    return pd.DataFrame(
        {
            DATE_COLUMN: months,
            "prediction_eur": paths.mean(axis=0),
            f"p{BAND_PERCENTILES[0]}_eur": low,
            f"p{BAND_PERCENTILES[1]}_eur": high,
        }
    )


def seasonal_naive(history: pd.Series, months: pd.DatetimeIndex) -> np.ndarray:
    """Línea base: "este mes venderemos lo mismo que el mismo mes del año pasado"."""
    path = history.copy()
    for month in months:
        path.loc[month] = path[month - pd.DateOffset(months=12)]
    return path[months].to_numpy()


# --------------------------------------------------------------------------- #
# Métricas
# --------------------------------------------------------------------------- #
def psi(expected: np.ndarray, actual: np.ndarray, bins: int = PSI_BINS) -> float:
    """Population Stability Index con cortes por cuantiles de la distribución de referencia."""
    expected = np.asarray(expected, dtype=float)
    actual = np.asarray(actual, dtype=float)
    edges = np.unique(np.quantile(expected, np.linspace(0, 1, bins + 1)))
    edges[0], edges[-1] = -np.inf, np.inf
    eps = 1e-4
    e = np.histogram(expected, edges)[0] / len(expected) + eps
    a = np.histogram(actual, edges)[0] / len(actual) + eps
    return float(np.sum((a - e) * np.log(a / e)))


def psi_label(value: float) -> str:
    if value < 0.1:
        return "estable (< 0,10)"
    if value < 0.25:
        return "cambio moderado (0,10-0,25)"
    return "cambio significativo (> 0,25)"


def gini(actual: np.ndarray, predicted: np.ndarray) -> float:
    """Gini de ordenación: cuánto del 'orden real' de los meses respeta la predicción."""
    actual = np.asarray(actual, dtype=float)
    order = np.argsort(-np.asarray(predicted, dtype=float), kind="mergesort")
    cumulative = np.cumsum(actual[order]) / actual.sum()
    expected = np.arange(1, len(actual) + 1) / len(actual)
    return float(np.sum(cumulative - expected) / len(actual))


def normalized_gini(actual: np.ndarray, predicted: np.ndarray) -> float:
    """Gini normalizado: 1 = ordena los meses igual que la realidad; 0 = al azar."""
    return gini(actual, predicted) / gini(actual, actual)


def regression_report(actual: np.ndarray, predicted: np.ndarray) -> dict:
    actual = np.asarray(actual, dtype=float)
    predicted = np.asarray(predicted, dtype=float)
    mse = mean_squared_error(actual, predicted)
    mean_revenue = actual.mean()
    return {
        "mse_eur2": float(mse),
        "rmse_eur": float(np.sqrt(mse)),
        "rmse_pct_of_mean_revenue": float(np.sqrt(mse) / mean_revenue * 100),
        "mse_pct_of_mean_revenue_squared": float(mse / mean_revenue**2 * 100),
        "mae_eur": float(mean_absolute_error(actual, predicted)),
        "mape_pct": float(np.mean(np.abs(actual - predicted) / actual) * 100),
        "r2_score": float(r2_score(actual, predicted)),
        "normalized_gini": float(normalized_gini(actual, predicted)),
    }


# --------------------------------------------------------------------------- #
# Visualización
# --------------------------------------------------------------------------- #
def plot_forecast(train: pd.DataFrame, test: pd.DataFrame, result: pd.DataFrame, path: Path) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.ticker import FuncFormatter

    low_col, high_col = (f"p{p}_eur" for p in BAND_PERCENTILES)
    fig, ax = plt.subplots(figsize=(12, 5.5))
    recent = train[train[DATE_COLUMN] >= test[DATE_COLUMN].min() - pd.DateOffset(months=24)]
    ax.plot(recent[DATE_COLUMN], recent[TARGET], color="#9aa0a6", lw=1.6,
            label="Histórico de entrenamiento (2022-2023)")
    ax.fill_between(result[DATE_COLUMN], result[low_col], result[high_col],
                    color="#4f7cff", alpha=0.18,
                    label=f"Rango de variabilidad (P{BAND_PERCENTILES[0]}-P{BAND_PERCENTILES[1]} de 300 escenarios)")
    ax.plot(result[DATE_COLUMN], result["prediction_eur"], color="#2f55d4", lw=2.2,
            ls="--", marker="o", ms=3.5, label="Predicción Random Forest (media)")
    ax.plot(test[DATE_COLUMN], test[TARGET], color="#111111", lw=2, marker="o", ms=3.5,
            label="Real 2024-2025 (no visto por el modelo)")
    ax.axvline(test[DATE_COLUMN].min(), color="#d93025", lw=1, ls=":")
    ax.text(test[DATE_COLUMN].min(), 0.98, "  inicio de la prueba",
            transform=ax.get_xaxis_transform(), color="#d93025", va="top", fontsize=9)
    ax.yaxis.set_major_formatter(FuncFormatter(lambda v, _: f"{v / 1e6:.1f} M€"))
    ax.set_title("TrackFlow · Ingresos mensuales consolidados: predicción a 24 meses vs. real")
    ax.set_ylabel("revenue_eur")
    ax.grid(alpha=0.25)
    ax.legend(loc="upper left", fontsize=9, frameon=False)
    fig.tight_layout()
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=130)
    plt.close(fig)


# --------------------------------------------------------------------------- #
# Orquestación
# --------------------------------------------------------------------------- #
@dataclass
class ExperimentResult:
    metrics: dict
    predictions: pd.DataFrame


def run(csv_path: Path = CSV_PATH, output_dir: Path | None = OUTPUT_DIR) -> ExperimentResult:
    raw = load_sales(csv_path)
    data, cleaning = clean_sales(raw)
    train, test = split_train_test(data)

    model = train_model(train)
    history = train.set_index(DATE_COLUMN)[TARGET]
    months = pd.DatetimeIndex(test[DATE_COLUMN])
    result = forecast(model, history, months)
    result["actual_eur"] = test[TARGET].to_numpy()
    result["seasonal_naive_eur"] = seasonal_naive(history, months)

    actual = result["actual_eur"].to_numpy()
    low_col, high_col = (f"p{p}_eur" for p in BAND_PERCENTILES)
    inside = (actual >= result[low_col]) & (actual <= result[high_col])

    # Ajuste dentro de la muestra (one-step con reales): solo para mostrar la
    # diferencia entre "memorizar el pasado" y predecir el futuro.
    frame = build_training_frame(train)
    in_sample_ratio = model.predict(frame[FEATURES])
    lag12 = history.shift(12).loc[frame[DATE_COLUMN]].to_numpy()
    in_sample = regression_report(history.loc[frame[DATE_COLUMN]].to_numpy(), in_sample_ratio * lag12)

    train_ratios = frame["target_ratio"].to_numpy()
    full = data.set_index(DATE_COLUMN)[TARGET]
    test_ratios = np.array([target_ratio(m, full) for m in months])
    psi_values = {
        "revenue_eur": psi(train[TARGET], test[TARGET]),
        "avg_revenue_per_shipment_eur": psi(
            train["avg_revenue_per_shipment_eur"], test["avg_revenue_per_shipment_eur"]
        ),
        "target_yoy_ratio": psi(train_ratios, test_ratios),
        "prediction_vs_actual_test": psi(actual, result["prediction_eur"]),
    }

    forest = model.named_steps["forest"]
    metrics = {
        "dataset": {
            "csv": str(csv_path.relative_to(ROOT)) if csv_path.is_relative_to(ROOT) else str(csv_path),
            "market": MARKET,
            "cleaning": cleaning,
            "train_period": f"{train[DATE_COLUMN].min():%Y-%m} → {train[DATE_COLUMN].max():%Y-%m}",
            "test_period": f"{test[DATE_COLUMN].min():%Y-%m} → {test[DATE_COLUMN].max():%Y-%m}",
            "train_rows": int(len(train)),
            "train_rows_with_features": int(len(frame)),
            "test_rows": int(len(test)),
            "mean_test_monthly_revenue_eur": float(actual.mean()),
        },
        "model": {
            "algorithm": "RandomForestRegressor",
            "target": "ratio interanual revenue_t / revenue_{t-12}",
            "forecast": "recursivo a 24 meses, sin reales de prueba",
            "n_estimators": N_ESTIMATORS,
            "min_samples_leaf": MIN_SAMPLES_LEAF,
            "random_state": RANDOM_STATE,
            "features": FEATURES,
            "feature_importance": {
                name: round(float(value), 4)
                for name, value in sorted(
                    zip(FEATURES, forest.feature_importances_), key=lambda kv: -kv[1]
                )
            },
        },
        "test": {
            **regression_report(actual, result["prediction_eur"]),
            "k2_score_r2": None,  # se rellena abajo (alias explícito de R²)
            "psi": {k: {"value": round(v, 4), "reading": psi_label(v)} for k, v in psi_values.items()},
            "band_coverage_pct": float(inside.mean() * 100),
        },
        "baseline_seasonal_naive_test": regression_report(actual, result["seasonal_naive_eur"]),
        "in_sample_train_one_step": in_sample,
    }
    metrics["test"]["k2_score_r2"] = metrics["test"]["r2_score"]

    if output_dir is not None:
        output_dir.mkdir(parents=True, exist_ok=True)
        (output_dir / "metrics.json").write_text(
            json.dumps(metrics, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
        out = result.copy()
        out[DATE_COLUMN] = out[DATE_COLUMN].dt.strftime("%Y-%m-%d")
        out.round(2).to_csv(output_dir / "test_predictions.csv", index=False)
        plot_forecast(train, test, result, output_dir / "forecast.png")
    return ExperimentResult(metrics=metrics, predictions=result)


def _print_summary(metrics: dict) -> None:
    t = metrics["test"]
    b = metrics["baseline_seasonal_naive_test"]
    s = metrics["in_sample_train_one_step"]
    print(f"Entrenamiento: {metrics['dataset']['train_period']}  |  Prueba: {metrics['dataset']['test_period']}")
    print(f"MSE            : {t['mse_eur2']:,.0f} EUR²  (RMSE {t['rmse_eur']:,.0f} € = {t['rmse_pct_of_mean_revenue']:.2f} % del ingreso medio)")
    print(f"MAE / MAPE     : {t['mae_eur']:,.0f} € / {t['mape_pct']:.2f} %")
    print(f"K2 Score (R²)  : {t['k2_score_r2']:.3f}")
    print(f"Gini normaliz. : {t['normalized_gini']:.3f}")
    for name, value in t["psi"].items():
        print(f"PSI {name:<28}: {value['value']:.4f}  {value['reading']}")
    print(f"Cobertura banda: {t['band_coverage_pct']:.0f} % de los meses reales dentro de P10-P90")
    print(f"Línea base naive estacional: MAPE {b['mape_pct']:.2f} %  |  Ajuste en train: MAPE {s['mape_pct']:.2f} %")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--csv", type=Path, default=CSV_PATH)
    parser.add_argument("--output-dir", type=Path, default=OUTPUT_DIR)
    args = parser.parse_args(argv)
    result = run(args.csv, args.output_dir)
    _print_summary(result.metrics)
    print(f"Artefactos en {args.output_dir}")


if __name__ == "__main__":
    main()
