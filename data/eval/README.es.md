# Carpeta `data/eval`

Esta carpeta está orientada a **evaluación y validación**: datasets de evaluación, “golden sets”, resultados de experimentos, métricas, y artefactos usados para medir calidad de modelos, RAG, agentes o pipelines.

- **Propósito principal**: centralizar los insumos y salidas de evaluación para asegurar mejoras medibles a lo largo de los hitos del proyecto.
- **Recomendación**: documenta cada set de evaluación (qué mide, cómo se construyó, criterios de éxito) y evita incluir datos sensibles; si es necesario, usa datos sintéticos o anonimizados.

## Evaluación del modelo de predicción de ventas

Generado por `python scripts/sales_model_eval.py`, solo con el entrenamiento 2016-2023 de `data/raw/trackflow_sales.csv`:

- `evaluation_report.md`: reporte técnico con el diagnóstico (overfitting moderado), la validación cruzada temporal, la curva de aprendizaje y la acción correctiva.
- `sales_model_cv_results.json`: métricas por fold, media ± desviación estándar, puntos de la curva de aprendizaje, error irreducible estimado y barrido de regularización.
- `learning_curve.png`, `cv_folds.png` y `validation_curve_regularization.png`.
