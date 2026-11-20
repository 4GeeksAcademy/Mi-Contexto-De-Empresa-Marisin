"""Evaluación técnica del modelo de predicción de ventas de TrackFlow.

Ticket del tech lead antes de promover el modelo de `scripts/sales_forecast.py`
(Random Forest sobre el ratio interanual de `revenue_eur`) a staging:

1. ¿Underfitting, overfitting o razonablemente bien ajustado?
2. ¿Qué tan estable es si cambia la porción de datos de entrenamiento?
3. Si hay un problema, ¿cuál es la acción correctiva específica?

Todo se calcula **solo sobre el conjunto de entrenamiento** (2016-2023). La
prueba (2024-2025) no se toca: elegir hiperparámetros mirándola la convertiría
en entrenamiento.

Validación cruzada temporal
---------------------------
* `TimeSeriesSplit(n_splits=5)` sobre las 72 filas con features
  (2018-01 → 2023-12; 2016-2017 solo aportan historia a los lags). Cada fold
  valida un año natural completo (2019, 2020, 2021, 2022 y 2023) con todo lo
  anterior como entrenamiento. Sin barajar.
* **Sin fuga de lags/rolling entre folds.** Las features de cada fold se
  recalculan a partir de la serie **recortada en el último mes de
  entrenamiento del fold**: ningún lag ni ventana rodante puede leer un mes del
  fold de validación. La validación es un pronóstico **recursivo a 12 meses**
  (igual que el modelo real): el modelo usa sus propias predicciones como lags y
  nunca ve un ingreso real del año que valida.

Uso::

    python scripts/sales_model_eval.py
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestRegressor
from sklearn.model_selection import TimeSeriesSplit
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

ROOT = Path(__file__).resolve().parents[1]
# Al ejecutarlo como `python scripts/sales_model_eval.py`, Python solo añade
# `scripts/` al path: se añade la raíz del repo para poder importar el paquete.
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import sales_forecast as sf  # noqa: E402
EVAL_DIR = ROOT / "data" / "eval"

N_SPLITS = 5
LEARNING_CURVE_SIZES = list(range(12, 61, 6))  # filas de entrenamiento: 12, 18, …, 60
VALIDATION_HORIZON = 12  # meses validados en cada punto de la curva de aprendizaje
PRIMARY_METRIC = "rmse_eur"

# Hiperparámetros del modelo actual (los de scripts/sales_forecast.py).
CURRENT_PARAMS = {
    "n_estimators": sf.N_ESTIMATORS,
    "min_samples_leaf": sf.MIN_SAMPLES_LEAF,
    "max_features": 1.0,
}
# Rejilla de regularización para la acción correctiva.
REGULARIZATION_GRID = {
    "min_samples_leaf": [1, 2, 3, 5, 8, 12],
    "max_features": [1.0, 0.5],
}


# --------------------------------------------------------------------------- #
# Modelo (mismo pipeline que sales_forecast.train_model, con hiperparámetros)
# --------------------------------------------------------------------------- #
def fit_model(history: pd.Series, **params) -> Pipeline:
    """Entrena con la serie `history` (solo meses de entrenamiento del fold)."""
    config = {**CURRENT_PARAMS, **params}
    frame = sf.build_training_frame(history.rename(sf.TARGET).reset_index())
    model = Pipeline(
        [
            ("scaler", StandardScaler()),
            (
                "forest",
                RandomForestRegressor(
                    n_estimators=config["n_estimators"],
                    min_samples_leaf=config["min_samples_leaf"],
                    max_features=config["max_features"],
                    random_state=sf.RANDOM_STATE,
                    n_jobs=1,
                ),
            ),
        ]
    )
    model.fit(frame[sf.FEATURES], frame["target_ratio"])
    return model


def fast_forecast(model: Pipeline, history: pd.Series, months: pd.DatetimeIndex) -> np.ndarray:
    """Pronóstico recursivo por árbol, vectorizado. Equivale a `sf.forecast` (hay test).

    Devuelve la media de los escenarios de los árboles para cada mes.
    """
    if (history.index >= months[0]).any():
        raise ValueError("La historia no puede incluir meses a pronosticar")
    expected = pd.date_range(history.index[-1] + pd.DateOffset(months=1), periods=len(months), freq="MS")
    if not months.equals(expected):
        raise ValueError("Los meses a pronosticar deben seguir a la historia sin huecos")
    scaler = model.named_steps["scaler"]
    trees = model.named_steps["forest"].estimators_
    n_hist = len(history)
    paths = np.tile(np.append(history.to_numpy(dtype=float), np.zeros(len(months))), (len(trees), 1))
    for j, month in enumerate(months):
        p = n_hist + j
        lag = lambda k: paths[:, p - k]  # noqa: E731
        features = pd.DataFrame(
            {
                "month_sin": np.sin(2 * np.pi * month.month / 12),
                "month_cos": np.cos(2 * np.pi * month.month / 12),
                "is_peak_season": int(month.month in sf.PEAK_MONTHS),
                "is_february": int(month.month == sf.LOW_MONTH),
                "yoy_same_month_last_year": lag(12) / lag(24),
                "yoy_last_month": lag(1) / lag(13),
                "trailing_growth": paths[:, p - 12 : p].sum(1) / paths[:, p - 24 : p - 12].sum(1),
                "seasonal_index_last_year": lag(12) / paths[:, p - 23 : p - 11].mean(1),
            }
        )[sf.FEATURES]
        x = scaler.transform(features)
        ratios = np.array([tree.predict(x[i : i + 1])[0] for i, tree in enumerate(trees)])
        paths[:, p] = ratios * paths[:, p - 12]
    return paths[:, n_hist:].mean(axis=0)


# --------------------------------------------------------------------------- #
# Métricas
# --------------------------------------------------------------------------- #
def errors(actual, predicted) -> dict:
    actual = np.asarray(actual, dtype=float)
    predicted = np.asarray(predicted, dtype=float)
    diff = predicted - actual
    return {
        "mae_eur": float(np.mean(np.abs(diff))),
        "rmse_eur": float(np.sqrt(np.mean(diff**2))),
        "mape_pct": float(np.mean(np.abs(diff) / actual) * 100),
        "bias_eur": float(np.mean(diff)),  # > 0 sobreestima, < 0 subestima
        "annual_bias_pct": float(diff.sum() / actual.sum() * 100),
    }


def mean_std(values) -> dict:
    values = np.asarray(values, dtype=float)
    return {"mean": float(values.mean()), "std": float(values.std(ddof=1))}


# --------------------------------------------------------------------------- #
# Validación cruzada temporal
# --------------------------------------------------------------------------- #
def training_series(train: pd.DataFrame) -> pd.Series:
    return train.set_index(sf.DATE_COLUMN)[sf.TARGET]


def time_series_folds(train: pd.DataFrame, n_splits: int = N_SPLITS) -> list[dict]:
    """Folds de `TimeSeriesSplit` sobre las filas con features, con sus meses."""
    frame = sf.build_training_frame(train)
    months = pd.DatetimeIndex(frame[sf.DATE_COLUMN])
    folds = []
    for number, (train_idx, val_idx) in enumerate(TimeSeriesSplit(n_splits=n_splits).split(frame), 1):
        folds.append(
            {
                "fold": number,
                "train_idx": train_idx,
                "val_idx": val_idx,
                "train_months": months[train_idx],
                "val_months": months[val_idx],
            }
        )
    return folds


def check_fold(fold: dict) -> None:
    """Comprobaciones explícitas: orden cronológico y sin solape."""
    train_idx, val_idx = fold["train_idx"], fold["val_idx"]
    assert np.all(np.diff(train_idx) == 1) and np.all(np.diff(val_idx) == 1), "fold barajado"
    assert train_idx.max() < val_idx.min(), "validación anterior al entrenamiento"
    assert fold["train_months"].max() < fold["val_months"].min(), "meses solapados"
    assert fold["train_months"].is_monotonic_increasing and fold["val_months"].is_monotonic_increasing


def fold_history(series: pd.Series, fold: dict) -> pd.Series:
    """Serie recortada en el último mes de entrenamiento del fold (corte anti-fuga)."""
    history = series[series.index <= fold["train_months"].max()]
    assert history.index.max() < fold["val_months"].min()
    return history


def evaluate_split(series: pd.Series, history: pd.Series, val_months: pd.DatetimeIndex, **params) -> dict:
    """Error de entrenamiento (ajuste dentro de la muestra) y de validación (recursivo)."""
    model = fit_model(history, **params)
    frame = sf.build_training_frame(history.rename(sf.TARGET).reset_index())
    fitted = model.predict(frame[sf.FEATURES]) * history.shift(12).loc[frame[sf.DATE_COLUMN]].to_numpy()
    predicted = fast_forecast(model, history, val_months)
    return {
        "train_rows": int(len(frame)),
        "train": errors(history.loc[frame[sf.DATE_COLUMN]], fitted),
        "validation": errors(series.loc[val_months], predicted),
        "validation_naive": errors(series.loc[val_months], series.loc[val_months - pd.DateOffset(months=12)]),
    }


def cross_validate(train: pd.DataFrame, **params) -> dict:
    series = training_series(train)
    rows = []
    for fold in time_series_folds(train):
        check_fold(fold)
        result = evaluate_split(series, fold_history(series, fold), fold["val_months"], **params)
        rows.append(
            {
                "fold": fold["fold"],
                "train_period": f"{fold['train_months'].min():%Y-%m} → {fold['train_months'].max():%Y-%m}",
                "validation_period": f"{fold['val_months'].min():%Y-%m} → {fold['val_months'].max():%Y-%m}",
                **result,
            }
        )
    summary = {
        split: {metric: mean_std([r[split][metric] for r in rows]) for metric in rows[0][split]}
        for split in ("train", "validation", "validation_naive")
    }
    return {"params": {**CURRENT_PARAMS, **params}, "folds": rows, "summary": summary}


def learning_curve(train: pd.DataFrame, sizes=LEARNING_CURVE_SIZES, **params) -> list[dict]:
    """Error de train y de validación al crecer el entrenamiento (ventana creciente).

    Cada punto entrena con las primeras `size` filas con features y valida los
    12 meses siguientes de forma recursiva (siempre dentro de 2018-2023).
    """
    series = training_series(train)
    months = pd.DatetimeIndex(sf.build_training_frame(train)[sf.DATE_COLUMN])
    points = []
    for size in sizes:
        val_months = months[size : size + VALIDATION_HORIZON]
        if len(val_months) < VALIDATION_HORIZON:
            break
        history = series[series.index <= months[size - 1]]
        result = evaluate_split(series, history, val_months, **params)
        points.append({"train_rows": size, "validation_period": f"{val_months[0]:%Y-%m} → {val_months[-1]:%Y-%m}", **result})
    return points


def noise_floor(train: pd.DataFrame) -> dict:
    """Error irreducible estimado: un 'oráculo' que conoce el nivel real de cada año
    y aplica la estacionalidad media. Lo que queda es el ruido mensual (±5 % del BRIEFING),
    que ningún modelo puede predecir. Un error de train por debajo indica que el modelo
    está memorizando ese ruido.
    """
    data = training_series(train).to_frame("y")
    data["year"], data["month"] = data.index.year, data.index.month
    annual_mean = data.groupby("year")["y"].transform("mean")
    seasonal = (data["y"] / annual_mean).groupby(data["month"]).mean()
    oracle = annual_mean * data["month"].map(seasonal)
    return errors(data["y"], oracle)


def regularization_sweep(train: pd.DataFrame) -> list[dict]:
    rows = []
    for leaf in REGULARIZATION_GRID["min_samples_leaf"]:
        for max_features in REGULARIZATION_GRID["max_features"]:
            cv = cross_validate(train, min_samples_leaf=leaf, max_features=max_features)
            rows.append(
                {
                    "min_samples_leaf": leaf,
                    "max_features": max_features,
                    "train_rmse": cv["summary"]["train"]["rmse_eur"],
                    "validation_rmse": cv["summary"]["validation"]["rmse_eur"],
                    "validation_mae": cv["summary"]["validation"]["mae_eur"],
                    "validation_rmse_by_fold": [f["validation"]["rmse_eur"] for f in cv["folds"]],
                }
            )
    return rows


# --------------------------------------------------------------------------- #
# Gráficos
# --------------------------------------------------------------------------- #
def _plt():
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    return plt


def _keur(ax):
    from matplotlib.ticker import FuncFormatter

    ax.yaxis.set_major_formatter(FuncFormatter(lambda v, _: f"{v / 1000:.0f} k€"))


def plot_learning_curve(points: list[dict], floor: dict, path: Path) -> None:
    plt = _plt()
    sizes = [p["train_rows"] for p in points]
    fig, ax = plt.subplots(figsize=(10, 5.5))
    ax.plot(sizes, [p["train"]["rmse_eur"] for p in points], "o-", color="#2f55d4", lw=2,
            label="Error de entrenamiento (RMSE)")
    ax.plot(sizes, [p["validation"]["rmse_eur"] for p in points], "o-", color="#d93025", lw=2,
            label="Error de validación (RMSE, 12 meses siguientes, recursivo)")
    ax.plot(sizes, [p["validation_naive"]["rmse_eur"] for p in points], ":", color="#777777", lw=1.5,
            label="Línea base: igual que el mismo mes del año anterior")
    ax.axhline(floor["rmse_eur"], color="#188038", ls="--", lw=1.2,
               label=f"Error irreducible estimado (ruido mensual ≈ {floor['rmse_eur'] / 1000:.0f} k€)")
    ax.fill_between(sizes, [p["train"]["rmse_eur"] for p in points],
                    [p["validation"]["rmse_eur"] for p in points], color="#d93025", alpha=0.07)
    _keur(ax)
    ax.set_xlabel("Meses de entrenamiento con features (desde 2018-01)")
    ax.set_ylabel("RMSE de revenue_eur")
    ax.set_title("TrackFlow · Curva de aprendizaje del Random Forest (solo datos 2016-2023)")
    ax.set_ylim(bottom=0)
    ax.grid(alpha=0.25)
    ax.legend(fontsize=9, frameon=False, loc="upper right")
    fig.tight_layout()
    fig.savefig(path, dpi=130)
    plt.close(fig)


def plot_folds(folds: list[dict], cv: dict, path: Path) -> None:
    plt = _plt()
    fig, ax = plt.subplots(figsize=(10, 3.6))
    for fold, row in zip(folds, cv["folds"]):
        y = fold["fold"]
        tr, va = fold["train_months"], fold["val_months"]
        ax.barh(y, (tr.max() - tr.min()).days + 31, left=tr.min(), color="#2f55d4", alpha=0.75, height=0.6)
        ax.barh(y, (va.max() - va.min()).days + 31, left=va.min(), color="#d93025", alpha=0.85, height=0.6)
        ax.text(va.max() + pd.Timedelta(days=45), y, f"RMSE {row['validation']['rmse_eur'] / 1000:.0f} k€",
                va="center", fontsize=8)
    ax.set_yticks([f["fold"] for f in folds], [f"Fold {f['fold']}" for f in folds])
    ax.invert_yaxis()
    ax.set_title("TimeSeriesSplit (5 folds): entrenamiento en azul, validación en rojo, sin barajar")
    ax.set_xlim(pd.Timestamp("2018-01-01"), pd.Timestamp("2025-01-01"))
    ax.grid(axis="x", alpha=0.25)
    fig.tight_layout()
    fig.savefig(path, dpi=130)
    plt.close(fig)


def plot_regularization(rows: list[dict], path: Path) -> None:
    plt = _plt()
    fig, ax = plt.subplots(figsize=(10, 5))
    for max_features, color in ((1.0, "#2f55d4"), (0.5, "#e37400")):
        sub = [r for r in rows if r["max_features"] == max_features]
        leaves = [r["min_samples_leaf"] for r in sub]
        ax.plot(leaves, [r["train_rmse"]["mean"] for r in sub], "o--", color=color, alpha=0.6,
                label=f"Entrenamiento · max_features={max_features}")
        ax.plot(leaves, [r["validation_rmse"]["mean"] for r in sub], "o-", color=color, lw=2,
                label=f"Validación CV · max_features={max_features}")
    current = next(r for r in rows if r["min_samples_leaf"] == CURRENT_PARAMS["min_samples_leaf"]
                   and r["max_features"] == CURRENT_PARAMS["max_features"])
    ax.scatter([current["min_samples_leaf"]], [current["validation_rmse"]["mean"]], s=160,
               facecolors="none", edgecolors="black", zorder=5, label="Modelo actual")
    _keur(ax)
    ax.set_xlabel("min_samples_leaf (más alto = más regularizado)")
    ax.set_ylabel("RMSE medio en los 5 folds")
    ax.set_title("Curva de validación: regularización del Random Forest")
    ax.set_ylim(bottom=0)
    ax.grid(alpha=0.25)
    ax.legend(fontsize=8.5, frameon=False, loc="center right")
    fig.tight_layout()
    fig.savefig(path, dpi=130)
    plt.close(fig)


# --------------------------------------------------------------------------- #
# Orquestación
# --------------------------------------------------------------------------- #
def run(output_dir: Path | None = EVAL_DIR) -> dict:
    data, _ = sf.clean_sales(sf.load_sales())
    train, _ = sf.split_train_test(data)  # la prueba 2024-2025 no se usa aquí

    folds = time_series_folds(train)
    for fold in folds:
        check_fold(fold)
    cv = cross_validate(train)
    points = learning_curve(train)
    floor = noise_floor(train)
    sweep = regularization_sweep(train)
    best = min(sweep, key=lambda r: r["validation_rmse"]["mean"])
    current = next(r for r in sweep if r["min_samples_leaf"] == CURRENT_PARAMS["min_samples_leaf"]
                   and r["max_features"] == CURRENT_PARAMS["max_features"])
    folds_improved = int(np.sum(np.array(best["validation_rmse_by_fold"]) < np.array(current["validation_rmse_by_fold"])))

    results = {
        "scope": "solo entrenamiento 2016-2023 (la prueba 2024-2025 no se toca)",
        "primary_metric": PRIMARY_METRIC,
        "cross_validation": cv,
        "learning_curve": points,
        "noise_floor": floor,
        "regularization_sweep": sweep,
        "recommended": {
            "min_samples_leaf": best["min_samples_leaf"],
            "max_features": best["max_features"],
            "validation_rmse": best["validation_rmse"],
            "current_validation_rmse": current["validation_rmse"],
            "folds_improved": folds_improved,
        },
    }
    if output_dir is not None:
        output_dir.mkdir(parents=True, exist_ok=True)
        (output_dir / "sales_model_cv_results.json").write_text(
            json.dumps(results, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
        plot_learning_curve(points, floor, output_dir / "learning_curve.png")
        plot_folds(folds, cv, output_dir / "cv_folds.png")
        plot_regularization(sweep, output_dir / "validation_curve_regularization.png")
    return results


def _fmt(stat: dict) -> str:
    return f"{stat['mean']:,.0f} ± {stat['std']:,.0f}"


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--output-dir", type=Path, default=EVAL_DIR)
    args = parser.parse_args(argv)
    r = run(args.output_dir)
    s = r["cross_validation"]["summary"]
    for row in r["cross_validation"]["folds"]:
        print(f"Fold {row['fold']}  train {row['train_period']} ({row['train_rows']:>2} meses)  "
              f"valida {row['validation_period']}  RMSE train {row['train']['rmse_eur']:>8,.0f} €  "
              f"RMSE val {row['validation']['rmse_eur']:>8,.0f} €")
    print(f"RMSE  train {_fmt(s['train']['rmse_eur'])} €  |  validación {_fmt(s['validation']['rmse_eur'])} €")
    print(f"MAE   train {_fmt(s['train']['mae_eur'])} €  |  validación {_fmt(s['validation']['mae_eur'])} €")
    print(f"MAPE  train {s['train']['mape_pct']['mean']:.2f} %  |  validación {s['validation']['mape_pct']['mean']:.2f} ± {s['validation']['mape_pct']['std']:.2f} %")
    print(f"Error irreducible estimado: RMSE {r['noise_floor']['rmse_eur']:,.0f} € (MAPE {r['noise_floor']['mape_pct']:.2f} %)")
    rec = r["recommended"]
    print(f"Recomendado: min_samples_leaf={rec['min_samples_leaf']}, max_features={rec['max_features']} → "
          f"RMSE val {_fmt(rec['validation_rmse'])} € (actual {_fmt(rec['current_validation_rmse'])} €; "
          f"mejora en {rec['folds_improved']}/5 folds)")
    print(f"Artefactos en {args.output_dir}")


if __name__ == "__main__":
    main()
