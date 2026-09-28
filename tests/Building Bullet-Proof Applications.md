# Building Bullet-Proof Applications



---

## ðŸŽ¯ Tu reto

La API de autenticaciÃ³n de tu empresa estÃ¡ en producciÃ³n, gestionando usuarios y sesiones reales. La semana pasada, un compaÃ±ero subiÃ³ un pequeÃ±o refactor que rompiÃ³ la lÃ³gica de expiraciÃ³n de tokens â€” ninguna prueba lo detectÃ³, y los usuarios reportaron estar bloqueados durante dos horas antes de que alguien se diera cuenta. La respuesta del CTO fue breve y directa: _"Necesitamos una baterÃ­a de pruebas. El cÃ³digo sin tests no es cÃ³digo de producciÃ³n."_

Tu tarea es aÃ±adir una baterÃ­a completa de pruebas unitarias a la API de autenticaciÃ³n que construiste en el hito anterior. TrabajarÃ¡s al nivel de la lÃ³gica de funciones y endpoints â€” no probando la serializaciÃ³n HTTP ni las tuberÃ­as del framework, sino la lÃ³gica de negocio real: Â¿se genera correctamente el token? Â¿Se rechaza un token expirado? Â¿QuÃ© ocurre cuando el campo de contraseÃ±a estÃ¡ vacÃ­o?

No se trata de escribir pruebas por el mero hecho de escribirlas. Se trata de construir la confianza de que cada endpoint se comporta como se espera en condiciones normales, en casos lÃ­mite y en escenarios de fallo â€” los tres pilares de cualquier plan de pruebas serio.

> Tu CTO ha registrado el siguiente ticket:
>
> #### Ticket: AUTH-088 â€” Cobertura de pruebas unitarias para la API de autenticaciÃ³n
>
> **Prioridad:** Alta
>
> **Contexto:** Tras la regresiÃ³n de la semana pasada, requerimos pruebas unitarias en todos los endpoints de autenticaciÃ³n antes de fusionar cualquier nuevo cambio.
>
> **Alcance:**
>
> - La baterÃ­a de pruebas debe cubrir todos los endpoints de la API de autenticaciÃ³n
> - Cada endpoint debe tener como mÃ­nimo: una prueba de camino feliz, una prueba de caso lÃ­mite y una prueba de modo de fallo
> - Usar `pytest` para el backend en FastAPI y `Jest` para la lÃ³gica en TypeScript
> - Las pruebas deben pasar limpiamente con `uv run pytest` y `jest --coverage`
> - No probar la serializaciÃ³n HTTP â€” probar la lÃ³gica
>
> **Entregable:** Una baterÃ­a de pruebas funcional incluida junto al cÃ³digo de la API existente, con un `TESTING.md` breve que explique cÃ³mo ejecutarla.

Antes de escribir tu primera prueba, define tu plan de pruebas: lista los casos que quieres cubrir para cada endpoint, identifica los casos lÃ­mite (campos vacÃ­os, usuarios duplicados, tokens malformados) y piensa quÃ© entradas podrÃ­an producir comportamientos inesperados. Luego usa la IA para que te ayude a generar el cÃ³digo de los tests â€” pero las decisiones sobre _quÃ©_ probar son tuyas.

Este es el tipo de trabajo que distingue a un junior que entrega funcionalidades de un profesional que entrega software fiable.

---

## ðŸŒ± CÃ³mo iniciar el proyecto

TrabajarÃ¡s sobre tu proyecto de API de autenticaciÃ³n existente â€” no hay un repositorio nuevo que clonar.

1. Abre tu proyecto de API de autenticaciÃ³n del hito anterior.
2. Si trabajas en local, asegÃºrate de haber ejecutado `uv sync` para instalar las dependencias.
3. Si usas GitHub Codespaces, reabre tu proyecto existente desde tu perfil de GitHub.

Instala las dependencias de testing si aÃºn no estÃ¡n presentes:

```bash
# Python / FastAPI
uv add --dev pytest pytest-cov httpx

# TypeScript (si aplica)
npm install --save-dev jest @types/jest ts-jest
```

Si tienes dudas sobre cÃ³mo configurar un proyecto desde cero, visita: [cÃ³mo iniciar un proyecto de programaciÃ³n](https://4geeks.com/es/lesson/como-iniciar-un-proyecto-de-programacion).

---

## ðŸ’» QuÃ© debes hacer

### Plan de pruebas

- [ ] Crea un archivo `TESTING.md` en la raÃ­z de tu proyecto documentando: cÃ³mo ejecutar las pruebas, quÃ© cubre cada suite y quÃ© casos decidiste incluir y por quÃ©.
- [ ] Antes de escribir ningÃºn test, lista en `TESTING.md` los casos que planeas cubrir: camino feliz, casos lÃ­mite y modos de fallo para cada endpoint.

### FastAPI â€” pytest

- [ ] Crea un directorio `tests/` en la raÃ­z de tu proyecto FastAPI.
- [ ] Escribe un mÃ³dulo de pruebas para cada endpoint de autenticaciÃ³n (p. ej., `test_register.py`, `test_login.py`, `test_token.py`).
- [ ] Para cada endpoint, implementa como mÃ­nimo:
  - [ ] Una prueba de camino feliz (entrada vÃ¡lida, respuesta esperada)
  - [ ] Una prueba de caso lÃ­mite (entrada en el lÃ­mite: campo vacÃ­o, usuario duplicado, etc.)
  - [ ] Una prueba de modo de fallo (credenciales invÃ¡lidas, token expirado, solicitud malformada)
- [ ] Todas las pruebas deben pasar al ejecutar `uv run pytest` desde la raÃ­z del proyecto.
- [ ] Ejecuta `uv run pytest --cov` y comprueba que tu baterÃ­a alcanza al menos **70% de cobertura** en el mÃ³dulo de autenticaciÃ³n.

### TypeScript â€” Jest (si tu proyecto incluye lÃ³gica de utilidades en TypeScript)

- [ ] Configura Jest con un archivo `jest.config.ts` o `jest.config.js` en la raÃ­z de tu proyecto TypeScript.
- [ ] Escribe pruebas unitarias para cualquier funciÃ³n de utilidad relacionada con la autenticaciÃ³n (generaciÃ³n de tokens, validaciÃ³n, helpers de hash de contraseÃ±as).
- [ ] Para cada funciÃ³n, implementa como mÃ­nimo: una prueba de camino feliz y una prueba de modo de fallo.
- [ ] Todas las pruebas deben pasar al ejecutar `jest --coverage`.

### Flujo de trabajo asistido por IA

- [ ] Usa tu agente de IA para identificar casos de prueba que podrÃ­as haber pasado por alto â€” proporciÃ³nale la lÃ³gica de tu endpoint y pÃ­dele que sugiera casos lÃ­mite.
- [ ] Usa la IA para generar el boilerplate de los tests, pero revisa y entiende cada prueba antes de confirmarla.
- [ ] Si un test generado revela un bug en tu cÃ³digo existente, corrÃ­gelo y documÃ©ntalo en `TESTING.md`.

âš ï¸ **IMPORTANTE:** No pruebes la serializaciÃ³n HTTP ni los internos del framework. Cada test debe afirmar algo sobre la lÃ³gica de negocio de tu aplicaciÃ³n â€” lo que el endpoint _decide_, no cÃ³mo _responde_.

### ðŸ† Actividad extra â€” Cierra el backlog mientras tienes el setup hecho

El CTO marcÃ³ AUTH-088 como el bloqueante, pero hay dos tickets que llevan semanas en el backlog sin que nadie los persiga. Son de baja prioridad â€” nadie los estÃ¡ pidiendo â€” pero ahora que tienes la infraestructura de testing montada, serÃ­a una pena no cerrarlos. Si terminas antes de tiempo, liquÃ­dalos.

> #### Ticket: API-042 â€” Pruebas unitarias para los endpoints del backoffice
>
> **Prioridad:** Baja
>
> **Contexto:** La API del backoffice nunca ha tenido baterÃ­a de pruebas. No se han reportado regresiones, pero probablemente es porque el equipo es pequeÃ±o, no porque el cÃ³digo sea sÃ³lido. Ahora que tenemos `pytest` configurado, ampliemos la cobertura antes de que el equipo crezca.
>
> **Alcance:**
>
> - Elige al menos dos grupos de endpoints del backoffice distintos a la autenticaciÃ³n (p. ej., recursos, usuarios, elementos â€” lo que tenga el dominio de tu empresa)
> - Aplica la misma estructura de tres niveles: camino feliz, caso lÃ­mite, modo de fallo
> - Apunta a un 60% de cobertura en los mÃ³dulos que pruebes â€” el listÃ³n es mÃ¡s bajo que en auth, pero sigue siendo significativo
>
> **Entregable:** Nuevos mÃ³dulos de prueba aÃ±adidos al directorio `tests/` existente. Actualiza `TESTING.md` con los nuevos resultados de cobertura.

> #### Ticket: FE-019 â€” Pruebas unitarias para las funciones de utilidad del frontend
>
> **Prioridad:** Baja
>
> **Contexto:** El frontend ha ido acumulando funciones de utilidad a lo largo de los hitos anteriores â€” validadores de formularios, formateadores de datos, manejadores de respuestas de API â€” que nunca se han probado. Un bug en cualquiera de ellas podrÃ­a romper la UI de forma silenciosa y difÃ­cil de rastrear.
>
> **Alcance:**
>
> - Identifica al menos tres funciones de utilidad o helper en tu frontend Next.js / TypeScript
> - Escribe tests de Jest para cada una: una prueba de camino feliz y una de modo de fallo por funciÃ³n
> - Buenas candidatas: validadores de entrada, formateadores de fechas o monedas, parsers de respuestas, helpers de almacenamiento de tokens
>
> **Entregable:** Un directorio `__tests__/` dentro de tu proyecto frontend con los archivos de prueba. Actualiza `TESTING.md` con las instrucciones para ejecutar los tests del frontend de forma independiente.

- [ ] _(Extra)_ Escribe tests con pytest para al menos dos grupos de endpoints del backoffice, alcanzando un 60% de cobertura en esos mÃ³dulos.
- [ ] _(Extra)_ Escribe tests de Jest para al menos tres funciones de utilidad del frontend (camino feliz + modo de fallo en cada una).
- [ ] _(Extra)_ Actualiza `TESTING.md` con los resultados de cobertura e instrucciones de ejecuciÃ³n para ambas suites adicionales.

---

## âœ… QuÃ© vamos a evaluar

- [ ] Existe un archivo `TESTING.md` que documenta el plan de pruebas, cÃ³mo ejecutarlas y los resultados de cobertura.
- [ ] `uv run pytest` se ejecuta sin errores desde la raÃ­z del proyecto y todas las pruebas pasan.
- [ ] La baterÃ­a incluye pruebas de camino feliz, casos lÃ­mite y modos de fallo para cada endpoint de autenticaciÃ³n.
- [ ] La cobertura del mÃ³dulo de autenticaciÃ³n es igual o superior al 70% (verificada con `uv run pytest --cov`).
- [ ] Las pruebas afirman lÃ³gica de negocio, no serializaciÃ³n HTTP ni comportamiento del framework.
- [ ] Si existen funciones de utilidad en TypeScript, los tests de Jest estÃ¡n presentes y pasan.
- [ ] El flujo asistido por IA es evidente: `TESTING.md` menciona al menos un caso identificado con ayuda de la IA o un bug detectado por la baterÃ­a de pruebas.
- [ ] El cÃ³digo estÃ¡ limpio: los tests tienen nombres claros, siguen una estructura consistente e incluyen comentarios breves que explican las afirmaciones no evidentes.

> **Nota:** La evaluaciÃ³n no requiere un 100% de cobertura. La calidad y el criterio de los casos de prueba importan mÃ¡s que el porcentaje. Un 70% bien razonado vale mÃ¡s que un 95% mecÃ¡nico.

> **Actividad extra:** Las baterÃ­as de pruebas del backoffice y el frontend no son obligatorias para aprobar, pero se reconocerÃ¡n en la evaluaciÃ³n si estÃ¡n presentes y pasan.

---

## ðŸ“¦ CÃ³mo entregar

Sube el repositorio actualizado a GitHub â€” debe contener tu cÃ³digo de API existente mÃ¡s el nuevo directorio `tests/` y el archivo `TESTING.md` â€” y comparte la URL del repositorio con tu instructor segÃºn sus indicaciones.

---

Este y muchos otros proyectos son construidos por estudiantes como parte de los [Coding Bootcamps](https://4geeksacademy.com/) de 4Geeks Academy. Encuentra mÃ¡s acerca de los [cursos](https://4geeksacademy.com/es/comparar-programas) de [IngenierÃ­a de IA](https://4geeksacademy.com/es/coding-bootcamps/ingenieria-ia), [Data Science & Machine Learning](https://4geeksacademy.com/es/coding-bootcamps/curso-datascience-machine-learning), [Ciberseguridad](https://4geeksacademy.com/es/coding-bootcamps/curso-ciberseguridad) y [Full-Stack Software Developer con IA](https://4geeksacademy.com/es/coding-bootcamps/programador-full-stack).