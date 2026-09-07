# Propuesta de Arquitectura: TrackFlow

## 1. Introducción
TrackFlow es una empresa logística con operaciones transfronterizas (EE. UU. y España) que actualmente sufre de una alta fragmentación tecnológica, resultando en ineficiencias operativas y falta de visibilidad global. Esta propuesta busca sentar las bases de un backend unificado, modular y escalable, diseñado para servir como el "cerebro" central que conecte las distintas áreas del negocio —incluyendo **Operaciones de Almacén, Gestión de Transportistas, Logística Inversa, CX, Comercial, el departamento de Tecnología y la Dirección Ejecutiva**— garantizando que tanto la operativa diaria como la toma de decisiones estratégicas se basen en datos estructurados en tiempo real.

## 2. Patrón Arquitectónico: Arquitectura en Capas orientada a Dominios (DDD)
Proponemos una **Arquitectura en Capas orientada a Dominios**. A diferencia de una estructura monolítica rígida, este patrón nos permite:

*   **Separación de Responsabilidades:** Cada módulo (Almacén, Logística, CX, etc.) funciona como un dominio independiente, lo cual es crítico dado que los procesos de un almacén en Zaragoza no necesariamente deben mezclarse con la lógica de selección de transportistas en EE. UU.
*   **Escalabilidad:** Al desacoplar los dominios, el equipo de tecnología puede implementar actualizaciones o integraciones con nuevas APIs de transportistas sin afectar la estabilidad del resto del sistema.
*   **Única Fuente de Verdad:** Centralizar la lógica de negocio en una capa de servicios permite que tanto la web pública como el backoffice operen bajo los mismos criterios, eliminando los errores de transcripción manual que afectan actualmente a la empresa.

## 3. Estructura de carpetas y módulos
Para mantener la coherencia y facilitar la navegación, adoptaremos una estructura modular basada en dominios. Esta organización asegura que, cuando el equipo de tecnología crezca, sea fácil identificar dónde reside cada funcionalidad:

```text
app/
├── api/                # Routers organizados por dominio
│   ├── warehouse/      # Endpoints de Operaciones de Almacén
│   ├── logistics/      # Gestión de transportistas y tracking
│   ├── reverse/        # Logística inversa y devoluciones
│   ├── cx/             # Atención al cliente y RAG
│   ├── commercial/     # CRM y gestión de clientes
│   ├── telemetry/      # Logs y monitorización para el equipo técnico
│   └── executive/      # KPIs y reportes para Dirección
├── agents/             # Módulo especializado en orquestación de IA
│   ├── rag/            # Búsqueda semántica y base de conocimiento
│   ├── workflow/       # Orquestación de agentes autónomos
│   └── tools/          # MCP y herramientas para agentes
├── services/           # Lógica de negocio reutilizable (servicios puros)
├── models/             # Esquemas de datos (Pydantic models)
├── core/               # Configuración global, seguridad y CORS
└── main.py             # Punto de entrada de la aplicación

```
## 4. Organización de Routers y Endpoints
Siguiendo las convenciones de FastAPI, no aglutinaremos todas las rutas en un solo archivo. Cada subdirectorio en `api/` contendrá su propio `router.py`, que luego será importado en el `main.py` mediante `app.include_router()`.

*   **Criterio de agrupación:** Se agruparán por responsabilidad de dominio. Por ejemplo, el router de `warehouse/` gestionará tanto la consulta de inventario como las alertas de stock bajo[cite: 4].
*   **Separación Frontend-Backend:** Dado que el frontend (Next.js) es un sistema separado, nuestra API expondrá endpoints REST que devolverán datos en formato JSON[cite: 3].
*   **CORS:** Configuraremos el middleware de CORS en `core/` para permitir peticiones únicamente desde los dominios autorizados de nuestros entornos de desarrollo y producción[cite: 3].
*   **Variables de Entorno:** Toda la configuración sensible (claves de APIs, URLs de bases de datos) se gestionará mediante variables de entorno, garantizando que el sistema sea adaptable a los dos entornos operativos (EE. UU. y España)[cite: 3, 4].

## 5. Visión estratégica: IA y Orquestación
TrackFlow tiene una hoja de ruta centrada en la automatización inteligente[cite: 4]. Por ello, la arquitectura incluye desde el primer día un módulo de `agents/`. Esto permite:

*   **Modularizar el código de IA:** Evita que la lógica de los LLMs (como el uso de Groq o modelos de Meta) se mezcle con la lógica operativa[cite: 4].
*   **Preparación para RAG y MCP:** Al crear este espacio, estamos preparados para integrar en el futuro la base de conocimiento semántica para CX y los protocolos MCP sin necesidad de refactorizar el backend principal[cite: 4].

## 6. Riesgos y puntos de atención
Para garantizar el éxito de esta estructura, debemos gestionar proactivamente los siguientes riesgos:

*   **Riesgo de "Espagueti de Servicios":** Si la capa de `services/` no se mantiene estrictamente aislada, la lógica de negocio podría filtrarse hacia los routers de la API. *Mitigación:* Implementar Code Reviews estrictas que prohíban llamadas directas a bases de datos o lógica compleja dentro de los archivos `router.py`.
*   **Complejidad en la Latencia de Integraciones:** TrackFlow depende de múltiples APIs externas (transportistas, etc.). Centralizar estas llamadas en un backend unificado podría crear cuellos de botella[cite: 4]. *Mitigación:* Diseñar la capa de servicios con mecanismos de *caching* (ej. Redis) y colas de tareas para procesos que no requieran respuesta inmediata.
*   **Desalineación entre equipos:** Dada la naturaleza transfronteriza (EE. UU. y España), el equipo de cada región podría intentar implementar soluciones locales que diverjan de la arquitectura global[cite: 4]. *Mitigación:* Mantener este documento como una "verdad viva" en el repositorio, donde cualquier cambio en la estructura deba ser consensuado y documentado en el `memory-bank`[cite: 3].