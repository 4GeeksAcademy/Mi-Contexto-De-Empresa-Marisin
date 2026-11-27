# Verificación · Prácticas seguras en la integración de IA (NIST)

- **Quién ejecuta qué:** los tests se ejecutan en cualquier entorno (sin red ni LLM). `uvicorn`, la sonda `scripts/nist_security_probe.py` y la prueba en el backoffice los ejecuta Marisin en el Codespace.
- **Coste:** la sonda **no llama al LLM**: todas sus preguntas son ataques que la guardia de entrada bloquea antes del modelo.

## 1. Tests deterministas

```bash
uv run pytest -q tests/test_nist_secrets.py tests/test_nist_rate_limit.py tests/test_nist_high_value_dispatch.py tests/pipelines/test_nist_input_and_tool_guards.py tests/pipelines/test_nist_prompt_injection.py
```

| Fichero | Qué demuestra |
|---|---|
| `tests/pipelines/test_nist_prompt_injection.py` | **Caso reproducible de prompt injection** (BRIEFING §4): caso 1 por `POST /agent/query` bloqueado sin LLM ni tools y con su decisión en `agent.audit`; 4 variantes ofuscadas; el usuario no puede cerrar `<consulta_usuario>`; caso 2 mostrado como dato; inyección en argumentos de tool rechazada |
| `tests/pipelines/test_nist_input_and_tool_guards.py` | Saneado (NFKC, invisibles, control, repeticiones, longitud) y `tool_call_guard` (catálogo, esquema, órdenes en argumentos, escrituras y acciones del BRIEFING §5 sin confirmación humana) |
| `tests/test_nist_rate_limit.py` | Ventanas por usuario, día y global; 429 con `Retry-After` sin ejecutar el grafo; por usuario; RAG y chat con el mismo presupuesto; evento `rate_limit` |
| `tests/test_nist_high_value_dispatch.py` | 409 sin confirmación y nada registrado; 201 con confirmación y auditoría; un cliente no despacha; stock antes que confirmación |
| `tests/test_nist_secrets.py` | 0 secretos en el repositorio; el escáner detecta claves reales y no imprime el secreto |

## 2. Sonda contra la API en marcha

1. API con un límite bajo para que N5 llegue rápido al 429 (Qdrant y Redis en marcha):
   ```bash
   LLM_RATE_LIMIT_PER_MINUTE=5 uv run uvicorn services.api.main:app --port 8000
   ```
2. En otra terminal, credenciales de staff sin que queden en pantalla ni en el `.env`:
   ```bash
   export TRACKFLOW_STAFF_EMAIL=admin@test.com
   read -rsp "Contraseña de staff: " TRACKFLOW_STAFF_PASSWORD && export TRACKFLOW_STAFF_PASSWORD && echo
   python scripts/nist_security_probe.py --out docs/nist/evidence/nist-probe.json
   unset TRACKFLOW_STAFF_PASSWORD
   ```
3. En la terminal de uvicorn, las líneas `agent_decision {…}` (una por consulta), `guardrail {"guard": "rate_limit"…}` y `high_value_dispatch_blocked {…}`.

| Id | Comprobación | Esperado | Obtenido | Evidencia |
|---|---|---|---|---|
| N1 | Escáner de secretos | 0 hallazgos | _pendiente_ | `nist-probe.png` · `nist-probe.json` |
| N2 | BRIEFING caso 1 como cliente | 200 · blocked · injection | _pendiente_ | ídem |
| N3 | Caso 1 con caracteres invisibles | 200 · blocked · injection | _pendiente_ | ídem |
| N4 | Decisión del agente en el trace | user · blocked · injection | _pendiente_ | ídem |
| N5 | Presupuesto agotado | 429 + `Retry-After` | _pendiente_ | ídem |
| N6 | Resumen de guardrails | `rate_limit:llm_budget` ≥ 1 | _pendiente_ | ídem |
| N7 | Despacho de 500 uds sin confirmación | 409, no registrado | _pendiente_ | ídem · `nist-agent-audit-log.png` |

## 3. Backoffice: confirmación humana de un despacho de alto valor

1. `Inventario → Salidas`, elige un producto con 500 unidades o más en un almacén (p. ej. un SKU `LOAD-…`) y pide una salida de **500**.
2. Aparece el diálogo «Despacho de alto valor: 500 unidades (umbral 500). Requiere confirmación humana explícita…».
3. Pulsa **Cancelar** → «Despacho de alto valor cancelado: no se ha registrado ninguna salida.» (El camino de confirmar está cubierto por `test_high_value_dispatch_with_human_confirmation_is_registered_and_audited`.)

## 4. Evidencias

| Fichero | Qué muestra |
|---|---|
| `evidence/nist-pytest-tests.png` | Los 5 ficheros de tests NIST en verde |
| `evidence/nist-pytest-suite.png` | Suite completa en verde |
| `evidence/nist-secrets-scan.png` · `secrets-scan.json` | `scripts/secrets_scan.py` → PASS, 0 hallazgos |
| `evidence/nist-probe.png` · `nist-probe.json` | Sonda N1–N7 |
| `evidence/nist-agent-audit-log.png` | Log de uvicorn con `agent_decision`, el evento `rate_limit` y `high_value_dispatch_blocked` |
| `evidence/nist-dispatch-confirm.png` | Diálogo de confirmación del despacho de alto valor en el backoffice |
