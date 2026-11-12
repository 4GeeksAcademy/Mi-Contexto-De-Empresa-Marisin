# Evidencia de skill de rendimiento

- **Skill:** `performance` de `addyosmani/web-quality-skills`
- **Fecha de instalación y revisión:** 12 de noviembre de 2026
- **Comando oficial ejecutado:** `npx skills add addyosmani/web-quality-skills --skill performance -y`
- **Fuente oficial:** [skills.sh — performance](https://www.skills.sh/addyosmani/web-quality-skills/performance)
- **Ubicación instalada:** `.agents/skills/performance/`
- **Resultado reportado por el instalador:** “Safe”, 0 alertas de Socket y riesgo bajo de Snyk.

## Recomendaciones relevantes

La skill recomienda distinguir datos de campo (CrUX/RUM) de mediciones de laboratorio (Lighthouse/traza) y de hipótesis obtenidas mediante inspección estática. También aclara que TBT es una métrica de laboratorio y un proxy aproximado de INP, no INP de campo. Para comparativas reproducibles, recomienda mantener ruta, estado de sesión, viewport, navegador, throttling y estado de caché, y usar al menos tres navegaciones equivalentes reportando mediana y rango.

## Aplicación y estado

- **Aplicado al análisis:** `AUDIT.md` marca como hipótesis por verificar el posible efecto de la animación del hero y del estado de carga; el CLS baseline es 0, por lo que el skeleton no se presenta como una mejora demostrada. TBT se registra por separado de INP, y este último permanece como “no capturado”.
- **Pendiente:** La medición baseline transcrita corresponde a los valores Lighthouse disponibles, sin rango ni dimensión numérica de viewport. No se altera ni se fabrican datos retrospectivos. Para una medición posterior repetible se mantendrán las rutas y estados indicados en `AUDIT.md`, y se anotarán las condiciones disponibles; si se hacen tres repeticiones, se informará mediana y rango.
- **Sin cambios de código:** La instalación no modificó la aplicación. Esta skill no aporta auditorías fallidas de SEO o accesibilidad; no se cambian esas áreas hasta disponer de sus resultados concretos.

La guía de medición instalada está en `.agents/skills/performance/references/MEASUREMENT.md`.
