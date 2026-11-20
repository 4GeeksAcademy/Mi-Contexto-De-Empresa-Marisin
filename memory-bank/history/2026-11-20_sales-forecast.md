# Plan y registro — Predicción de ventas con un modelo de regresión (TrackFlow)

> **Proyecto 4Geeks:** "Predicción de Ventas con un Modelo de Regresión" — ticket del tech lead a partir de la RFI de Finanzas.
> **Monorepo:** `Mi-Contexto-De-Empresa-Marisin` (TrackFlow).
> **Rama:** `feature/sales-forecast-model`, creada por Marisin **desde `main`** (`5ba9f05`, tras mergear la cadena de PR #19–#25).
> **Ejecución:** sin agente en el Codespace. Claude implementa y entrega un parche (`git am`); Marisin añade las dependencias con `uv add`, ejecuta pytest y el script, y hace push y el PR.
> **Fuente de verdad del negocio:** `trackflow-BRIEFING.es.md` de `content/contexts/sales-forecasting/trackflow/` en el syllabus de 4Geeks.

---

## 0. Reglas

1. Un commit por acción, prefijo convencional y descripción en español.
2. Marisin crea la rama, aplica el parche y hace push; nada de `git add .` / `-A`.
3. El parche no toca `pyproject.toml` ni `uv.lock`: `scikit-learn` y `matplotlib` las añade Marisin con `uv add`, en su propio commit (`pandas` ya estaba).
4. El dataset se copia sin alterar; no se genera ni se simula.

## 1. Rúbrica (resumen)

- Cargar `data/raw/trackflow_sales.csv` y verificar las columnas del BRIEFING; tratar nulos; split 8 años / 2 años sin fuga; escalar lo que lo requiera.
- XGBoost o Random Forest con `scikit-learn`, elección justificada en el código.
- MSE, PSI, Gini y K2 Score sobre la prueba; README con qué mide cada una y por qué un MSE bajo no basta.
- Visualización de la predicción con su rango de variabilidad frente a los reales de 2024-2025.
- Semilla fija. Test en `tests/pipelines/` del split 8/2 y de la ausencia de fuga.
- PR hacia `main` con el algoritmo, su justificación y las métricas de prueba.

## 2. Decisiones (S1–S9)

| # | Decisión | Por qué |
|---|---|---|
| S1 | **Random Forest** (`RandomForestRegressor`, 300 árboles, `min_samples_leaf=2`, `random_state=42`). | 72 filas de entrenamiento: el bagging es robusto sin tuning; explicable para Finanzas; la banda de variabilidad sale de los propios árboles. XGBoost, como siguiente paso. |
| S2 | Target = **ratio interanual** `revenue_t / revenue_{t-12}`; los euros se reconstruyen con `revenue_{t-12}`. | Los árboles no extrapolan y 2024-2025 superan todo el histórico. |
| S3 | Split por **años naturales**: 2016-2023 (96 meses) / 2024-2025 (24). | Regla 8/2 del ticket; falla si no hay exactamente 10 años. |
| S4 | Features causales: 2 de calendario cíclico, 2 marcas del BRIEFING (nov-dic, febrero) y 4 lags (crecimiento del mismo mes del año pasado, del último mes, anual acumulado e índice estacional). Requieren 24 meses de historia. | Capturan la alternancia 9 %/3 % y la estacionalidad sin mirar al futuro. |
| S5 | Pronóstico de prueba **recursivo a 24 meses**: cada árbol proyecta su escenario usando sus predicciones como lags. Predicción = media; banda = P10-P90. | Evaluación honesta (el modelo nunca ve un real de prueba) y banda que crece con el horizonte. |
| S6 | Nulos: reindexado mensual + interpolación temporal; `avg_revenue_per_shipment_eur` se recalcula. | La media global aplanaría los picos. El CSV real no tiene nulos (queda registrado). |
| S7 | `StandardScaler` en el `Pipeline`, ajustado solo con train. | Requisito del enunciado; el RF es invariante a la escala (documentado). |
| S8 | **K2 Score = R²** (`r2_score`), declarado como interpretación. Gini = Gini normalizado de ordenación. PSI con 5 cortes por cuantiles de train sobre `revenue_eur`, ingreso por envío, el ratio objetivo y predicción vs. real. MSE en EUR² y RMSE como % del ingreso medio; MAPE para Finanzas. | "K2" no existe en scikit-learn; el BRIEFING pide MSE interpretable. |
| S9 | Línea base naive estacional y ajuste en entrenamiento en `metrics.json`. | Demostrar que el error no es memoria y que el modelo aporta. |

## 3. Hallazgos

| # | Hallazgo |
|---|---|
| H1 | `data/raw/` no tenía `trackflow_sales.csv`: se copia del syllabus (md5 `59975b030da106ecda2c78039652cc6b`). |
| H2 | El CSV solo trae `market = consolidated`: el PSI de mezcla Los Ángeles/Zaragoza que pide el BRIEFING no se puede calcular; se usa el ingreso por envío como indicador y se anota. |
| H3 | Crecimiento real por año: 2017 9,6 % · 2018 1,8 % · 2019 9,4 % · 2020 2,9 % · 2021 8,0 % · 2022 2,8 % · 2023 10,1 % · **2024 4,0 % · 2025 7,9 %** (prueba). |
| H4 | `scripts/` se importa como paquete de espacio de nombres (`from scripts import …`), igual que `nightly_export`. |

## 4. Acciones y commits

| # | Acción | Commit |
|---|---|---|
| 1 | Este plan | `docs: añade el plan del modelo de predicción de ventas` |
| 2 | `data/raw/trackflow_sales.csv` + documentación en `data/raw/README.es.md` | `feat: añade el histórico mensual de ventas de TrackFlow` |
| 3 | `scripts/sales_forecast.py` + `scripts/README*.md` | `feat: añade el modelo de predicción de ventas con Random Forest` |
| 4 | `tests/pipelines/test_sales_forecast_split.py` (11 tests) | `test: valida el split 8/2 años y la ausencia de fuga de datos` |
| 5 | `docs/sales-forecast/` (README, `metrics.json`, `test_predictions.csv`, `forecast.png`) | `docs: añade métricas, gráfico y README del modelo de ventas` |
| 6 | `memory-bank/progress.md` | `docs: registra el modelo de predicción de ventas en progress` |
| 7 | **Marisin:** `uv add scikit-learn matplotlib` | `chore: añade scikit-learn y matplotlib` |

## 5. Resultados (prueba 2024-2025, generados por Claude)

MSE 2.728.405.048 EUR² (RMSE 52.234 € = 4,0 % del ingreso medio) · MAPE 3,43 % · K2 Score (R²) 0,907 · Gini 0,920 · PSI ratio objetivo 0,13 · cobertura de la banda 67 %. Naive estacional: MAPE 7,68 %. Ajuste en train: MAPE 1,47 %.

## 6. Registro

- 2026-11-20 — Parche con las acciones 1-6 preparado por Claude; 11 tests en verde en local.
