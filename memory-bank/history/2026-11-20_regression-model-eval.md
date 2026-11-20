# Plan y registro — Evaluación de un modelo de regresión (TrackFlow)

> **Proyecto 4Geeks:** "Evaluación de un Modelo de Regresión", el ticket del tech lead antes de promover a staging el modelo de ventas.
> **Monorepo:** `Mi-Contexto-De-Empresa-Marisin` (TrackFlow).
> **Rama:** `feature/regression-model-eval`, creada por Marisin **desde `feature/sales-forecast-model`** (`8e4da5d`), porque el PR #26 aún no está mergeado. Cadena: `main ← #26 ← esta`.
> **Ejecución:** sin agente. Claude implementa y entrega un parche (`git am`); Marisin ejecuta pytest y el script, hace push y abre el PR.
> **Fuente de verdad:** BRIEFING de sales-forecasting de TrackFlow y `CONTEXT.md`.

## 0. Reglas

1. Un commit por acción, con prefijo convencional y descripción en español.
2. No se añaden dependencias (`scikit-learn` y `matplotlib` ya están).
3. **La prueba 2024-2025 no se usa** en la evaluación ni para elegir hiperparámetros.
4. El modelo de producción no se modifica en este PR: la acción correctiva se propone con evidencia.

## 1. Rúbrica (resumen)

- `TimeSeriesSplit` con al menos 5 folds sobre el entrenamiento, sin barajar y sin fuga de lags/rolling entre folds; métrica como media ± desviación estándar.
- Curva de aprendizaje (train y validación) guardada en `data/eval/`.
- MAE y RMSE de train y validación; justificación de negocio de la principal según el BRIEFING.
- `data/eval/evaluation_report.md` con diagnóstico explícito y acción correctiva concreta.
- Test en `tests/pipelines/` de que los folds preservan el orden cronológico.
- PR con el diagnóstico en una o dos frases.

## 2. Decisiones (E1–E8)

| # | Decisión | Por qué |
|---|---|---|
| E1 | `TimeSeriesSplit(n_splits=5)` sobre las 72 filas con features (2018-2023): cada fold valida un año natural (2019-2023). | Cinco folds de 12 meses, sin barajar; 2016-2017 solo aportan historia. |
| E2 | Las features de cada fold se recalculan sobre la serie recortada en el último mes de entrenamiento (`fold_history`). | Ningún lag ni ventana rodante puede leer el fold de validación. |
| E3 | Validación recursiva a 12 meses, con las predicciones del modelo como lags. | Mismo uso que en producción y sin ver los reales del año validado. |
| E4 | `fast_forecast` vectorizado, equivalente a `sf.forecast` (hay test). | El barrido (60 entrenamientos) pasa de ~10 min a ~45 s. |
| E5 | `fit_model` replica `sf.train_model` con hiperparámetros (hay test de equivalencia) y no se modifica `sales_forecast.py`. | No crear conflictos con el PR #26 mientras está en revisión. |
| E6 | Métrica principal: **RMSE**. MAE para comunicar y sesgo con signo como complemento. | El error caro es quedarse corto en el pico de noviembre-diciembre (BRIEFING y renovaciones en `CONTEXT.md`). |
| E7 | Error irreducible estimado con un oráculo (nivel real del año y estacionalidad media). | Referencia objetiva para saber si el entrenamiento memoriza ruido. |
| E8 | Barrido de `min_samples_leaf` ∈ {1, 2, 3, 5, 8, 12} y `max_features` ∈ {1.0, 0.5} con la misma validación cruzada. | Evidencia para la acción correctiva. |

## 3. Acciones y commits

| # | Acción | Commit |
|---|---|---|
| 1 | Este plan | `docs: añade el plan de evaluación del modelo de ventas` |
| 2 | `scripts/sales_model_eval.py` + `scripts/README*.md` | `feat: añade la evaluación con validación cruzada temporal del modelo de ventas` |
| 3 | `tests/pipelines/test_sales_model_eval.py` (10 tests) | `test: valida el orden cronológico y la ausencia de fuga en los folds` |
| 4 | `data/eval/` (JSON, 3 gráficos, READMEs) | `docs: añade resultados y gráficos de la evaluación del modelo de ventas` |
| 5 | `data/eval/evaluation_report.md` | `docs: añade el reporte técnico de evaluación del modelo de ventas` |
| 6 | `memory-bank/progress.md` | `docs: registra la evaluación del modelo de ventas en progress` |

## 4. Resultado

**Overfitting moderado.** RMSE de entrenamiento 15.478 ± 3.410 € frente a un error irreducible de 25.253 €; validación 52.095 ± 12.765 €; línea base 81.103 ± 28.129 €. **Acción:** `min_samples_leaf` 2 → 3 y `max_features` 1.0 → 0.5, con validación 48.861 ± 15.067 € (mejora en 4 de 5 folds).

## 5. Registro

- 2026-11-20 — Parche con las acciones 1-6 preparado por Claude; 10 tests nuevos en verde en local.
