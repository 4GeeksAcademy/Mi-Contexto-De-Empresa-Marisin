"""Memoria persistente del agente de soporte de TrackFlow (Hito 8 · Parte 1).

Memoria **episódica curada**, separada del RAG: el RAG (`trackflow_knowledge`)
sigue siendo una herramienta de solo lectura y este paquete nunca escribe en él.

* `models.py` — contratos: propuesta (`MemoryDraft`), propuesta pendiente,
  hecho consolidado, slot (categoría + ámbito) y evento de auditoría.
* `policy.py` — qué se puede recordar y qué nunca (company-BRIEFING), en código
  determinista: la última palabra no la tiene el LLM.
* `backend.py` — interfaz de almacenamiento: Redis en producción y una versión
  en memoria para los tests.
* `store.py` — interfaz explícita de lectura/escritura: pendientes (una por
  conversación), consolidación por slot, recuerdo, limpieza y auditoría.
* `decision.py` — clasificador de intención de la respuesta del usuario a la
  propuesta pendiente (aprobar, rechazar, editar, cambio de tema, ambiguo).
* `flow.py` — el ciclo propuesta → decisión → consolidación que usan los nodos.
"""
