# Carpeta `data/process`

Esta carpeta contiene **datos procesados/intermedios** y/o artefactos derivados de los pipelines (por ejemplo: datasets limpios, features, agregados, tablas intermedias o resultados de transformaciones).

- **Propósito principal**: separar claramente los datos “raw” de los datos listos para análisis/modelado/consumo por apps.
- **Recomendación**: documenta qué pipeline genera cada artefacto, su esquema, periodicidad, y cómo se valida su calidad (checks, constraints, tests de datos).

## `rag.py` — indexación del RAG (Hito 7)

`setup()` lee `docs/company-knowledge-base/`, divide los documentos en chunks semánticos, los embebe con `embed()` (modelo de embeddings, `EMBEDDING_MODEL`) y los guarda en la colección Qdrant `trackflow_knowledge` con IDs deterministas. Ejecútalo con `python -m data.process.rag`. Diseño: `docs/rag/rag-design.md`.
