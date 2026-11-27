# Inventario de sistemas de IA de TrackFlow

Inventario de **todo lo construido hasta ahora** en el fork que usa un modelo (LLM, embeddings o modelo predictivo) o que decide qué hace un agente. Parte de la tabla de la sección 3 del BRIEFING y la completa con lo que de verdad existe en el código.

- **Responsable de negocio:** la persona que decide qué debe hacer el componente y acepta su riesgo (dueña de los datos y de las reglas).
- **Responsable técnico:** quien lo opera y corrige. El equipo técnico es el de Andrés Kim (CTO, Zaragoza); a falta de una persona de seguridad dedicada, **Andrés Kim es el responsable de seguridad de IA** (acción G-1 del informe).
- **Datos:** B2C = contacto y direcciones de destinatarios finales; B2B = datos contractuales y de volumen de las marcas (confidenciales por contrato). Son los datos más sensibles según el BRIEFING §2.

## 1. Componentes de la sección 3 del BRIEFING

| Componente (BRIEFING) | ¿Existe en el fork? | Dónde | Responsable de negocio | Responsable técnico | Riesgo principal (BRIEFING) | Estado del control |
|---|---|---|---|---|---|---|
| Agente de soporte 24/7 (CX) | **Sí** | `services/agent/` (grafo LangGraph), `POST /agent/query`, chat `WS /agent/chat` | **Valentina Cruz** (CX Manager) | Andrés Kim (CTO) | Prompt injection para obtener datos de otro pedido o cliente | Controlado: caso 1 del BRIEFING bloqueado (`tests/pipelines/test_nist_prompt_injection.py`) |
| Motor de selección de carrier | **No** (`grep` sin coincidencias, ver OWASP §6.3) | — | **Carlos Vega** (Última milla) | Andrés Kim | *Excessive agency*: confirmar el envío sin validar coste o reglas | No aplica. El agente no tiene tools de escritura; `change_carrier`/`carrier_assign` ya exigen confirmación humana en `tool_call_guard` (§5.3) |
| RAG de políticas de devolución y SLA por país | **Sí** | `data/pipelines/rag.py`, Qdrant (`trackflow_knowledge`), `docs/company-knowledge-base/` | **Sofía Ramos** (devoluciones) y **Carlos Vega** (SLA de entrega) | Andrés Kim | Fuga de reglas confidenciales de un cliente B2B a otro | Controlado: el corpus solo tiene políticas generales de TrackFlow, sin reglas por cliente; bloqueo por país; chunks aislados |
| Motor de aprobación automática de devoluciones | **No** | — | **Sofía Ramos** (Logística inversa) | Andrés Kim | Aprobar devoluciones fuera de las reglas (alto impacto económico) | No aplica. Hoy todas las devoluciones pasan por revisión humana (CONTEXT). `returns_approve` exige confirmación humana (§5.1) |

## 2. Resto de componentes de IA construidos

| Componente | Qué hace | Dónde | Responsable de negocio | Responsable técnico | Datos que toca |
|---|---|---|---|---|---|
| Enrutador híbrido del agente | Decide si la pregunta va al RAG o a una tool (LLM con JSON validado + reglas de respaldo) | `services/agent/routing.py` | Valentina Cruz | Andrés Kim | Pregunta del cliente |
| Harness y guardrails del agente | Guardia de entrada, autorización de pedidos, aislamiento, guardia de salida, eventos | `services/agent/harness/` | Valentina Cruz | Andrés Kim | Pregunta, chunks, campos de tools |
| Validación de llamadas a tools (nuevo) | Única puerta antes de ejecutar una tool; registro de acciones irreversibles | `services/agent/harness/tool_call_guard.py` | Andrés Kim | Andrés Kim | Argumentos de las tools |
| Presupuesto de llamadas al LLM (nuevo) | Límite por usuario y global en las entradas que llaman al modelo | `services/agent/harness/usage_limits.py` | Andrés Kim | Andrés Kim | Id y rol del usuario |
| Chat de soporte por WebSocket | Streaming de la respuesta del agente, interrupción | `services/agent/chat/`, tablas `chat_sessions`/`chat_messages` | Valentina Cruz | Andrés Kim | Conversaciones de clientes (B2C/B2B) |
| Servidor MCP con OAuth | Tools de incidencias e inventario para el agente (solo lectura para él) | `mcps/trackflow_mcp/` | Ana Whitfield (inventario) y Valentina Cruz (incidencias) | Andrés Kim | Incidencias, stock y `client_name` de las marcas (B2B) |
| Memoria del agente | Hechos aprobados por humanos (reglas de carrier, incidentes, preferencias B2B) | `services/agent/memory/` (Redis) | Valentina Cruz | Andrés Kim | Reglas operativas, preferencias de informes B2B |
| Asistente comercial RAG | Responde con la voz de ventas sobre la base de conocimiento | `services/knowledge/`, `POST /knowledge/query` | **Miguel Torres** (Comercial) | Andrés Kim | Políticas y tarifas públicas |
| Flujo agéntico de RFPs · recepción | Clasifica el PDF, extrae metadatos, reparte por departamento | `data/pipelines/rfp_intake/` | Miguel Torres | Andrés Kim | RFP de un prospecto (B2B confidencial) |
| Flujo agéntico de RFPs · borradores | Un generador LLM por departamento + evaluadores deterministas | `data/pipelines/rfp_intake/drafting/` | Ana Whitfield (almacén), Carlos Vega (última milla), Sofía Ramos (inversa) | Andrés Kim | Metadatos de la RFP, tarifas de referencia |
| Flujo agéntico de RFPs · aprobación | `interrupt()` por departamento, árbitro de conflictos, documento final | `data/pipelines/rfp_intake/approval/` | Miguel Torres (cierre) y cada responsable de departamento (visto bueno) | Andrés Kim | Propuesta económica B2B |
| Modelo de predicción de ventas | Random Forest de ingresos mensuales para Finanzas | `scripts/sales_forecast.py`, `docs/sales-forecast/` | **Thomas Harry** (CEO, dashboard ejecutivo) | Andrés Kim | Ingresos agregados (sin datos personales) |
| Notificaciones SSE de RFPs | Avisa al backoffice de RFPs nuevas (no llama a modelos; muestra su salida) | `services/realtime/` | Miguel Torres | Andrés Kim | Metadatos de la RFP |

## 3. Terceros: quién responde de cada control

Cuando el modelo, la herramienta o la infraestructura la provee un tercero, la responsabilidad es **compartida**: el proveedor responde de lo que opera; TrackFlow responde de qué datos le envía, cómo configura el servicio y cómo custodia las credenciales. En RGPD el proveedor que trata datos personales por cuenta de TrackFlow es **encargado del tratamiento** (art. 28) y necesita contrato; en CCPA es **service provider/contractor** y necesita contrato con las restricciones de uso.

| Tercero | Componente que lo usa | Responde el proveedor de… | Responde TrackFlow de… | Responsable en TrackFlow |
|---|---|---|---|---|
| **Pasarela LLM de 4Geeks** (`llm.4geeks.ai`, compatible con OpenAI; enruta a modelos de OpenRouter) | Agente CX, enrutador, asistente comercial, RFPs; embeddings | Disponibilidad, seguridad de su infraestructura, comportamiento del modelo y retención de lo que recibe según sus condiciones | **Minimización**: no enviar datos personales de terceros (la guardia de entrada bloquea antes del modelo); guardrails y guardia de salida; presupuesto de llamadas; custodia y rotación de `LLM_API_KEY`; contrato de encargo y transferencias internacionales (los modelos se sirven desde EE. UU.) | Andrés Kim |
| **Logto Cloud** (proveedor OAuth) | Servidor MCP | Firma y emisión de tokens, disponibilidad del tenant | Apps M2M con mínimo privilegio (el agente solo `*:read`), audiencia del recurso, custodia de `MCP_*_CLIENT_SECRET`, revocación | Andrés Kim |
| **Supabase** (PostgreSQL gestionado) | Inventario, RFPs, chat, telemetría | Infraestructura, cifrado en reposo, copias según el plan contratado | Credenciales (`DATABASE_URL`), qué datos se guardan, retención, ejercicio de derechos (acceso y supresión de conversaciones) | Andrés Kim |
| **Resend** (email transaccional) | Recuperación de contraseña | Entrega y seguridad del envío | Solo envía el enlace de recuperación; `RESEND_API_KEY` en el entorno | Andrés Kim |
| **GitHub / Codespaces** (4Geeks) | Repositorio y entorno de desarrollo | Seguridad de la plataforma | Ningún secreto en el repo (escáner `scripts/secrets_scan.py` en el CI), `.env` fuera de git | Andrés Kim |
| Librerías (LangGraph, `langchain-mcp-adapters`, `mcp`, `qdrant-client`, MarkItDown…) | Agente, MCP, RAG, RFPs | — (código abierto) | Versiones fijadas con hash (`uv.lock`), `pip-audit`/`npm audit` (OWASP A06) | Andrés Kim |
| Qdrant y Redis | RAG, memoria, colas | — (autoalojados en Docker) | Todo: solo en loopback (OWASP C5); pendiente API key y `requirepass` (riesgo residual OWASP R5) | Andrés Kim |
