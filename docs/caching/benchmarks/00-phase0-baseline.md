# Baseline de preparación — 2026-11-17

## Procedencia

Transcripción del resultado real de `pytest -q` obtenido durante esta sesión
de Fase 0, antes de los cambios documentales. No se ha repetido la suite para
cerrar la documentación.

```text
................                                                         [100%]
16 passed, 3 warnings in 5.18s
```

Resultado literal solicitado: **16 passed, 3 warnings**. Código de salida: 0.
El plan citaba 9 passed por un recuento antiguo.

Entorno recreado: Python 3.14.2, FastAPI 0.163.1, pytest 9.2.0.
El entorno `.venv` no existía al iniciar la fase; se restauraron las
dependencias del proyecto y su grupo de desarrollo. No se modificaron
manifiestos para ello.

Los warnings procedían del uso de httpx con TestClient y de las dos
notificaciones de deprecación de `on_event` (aplicación y FastAPI).

## Builds

| App | Resultado final | Ejecutor | Evidencia |
|---|---|---|---|
| website | OK | Agente | [Salida](../frontend/build-before-website.txt) |
| backoffice | OK | Marisin en su terminal | [Salida](../frontend/build-before-backoffice.txt) |
| application | OK | Agente | [Salida](../frontend/build-before-application.txt) |

Los dos intentos del agente para backoffice se detuvieron con
`SecurityFatalError` después de compilar, verificar TypeScript y generar las
rutas. Se conservan [intento 1](../frontend/build-before-backoffice-intento1.txt)
e [intento 2](../frontend/build-before-backoffice-intento2.txt).
El resultado final de backoffice fue verificado manualmente por Marisin.
Los logs se conservan sin normalizar: incluyen espacios finales y retornos
de carro emitidos por el progreso del build. `git diff --cached --check`
los señala; no se alteran para preservar la evidencia original.

Comandos de validación, cada uno desde la carpeta de su app:

```sh
# website
NODE_ENV=production npm run build
# backoffice
NODE_ENV=production NEXT_PUBLIC_INVENTORY_API_URL=http://127.0.0.1:8000 npm run build
# application
npm run build
```

Versiones observadas en los logs: website y application, Next.js 16.2.11;
backoffice, Next.js 16.4.4. Los builds no muestran tamaños de JS por ruta.
Se medirán en Fase 5 mediante chunks y verificación manual en Network.

## Rendimiento

Latencias de endpoints, volumen de datos, tamaños JS por ruta, LCP, INP y
CLS: **no medidos** en Fase 0. No se han ejecutado benchmarks ni semillas
de carga. Estos resultados no prueban ninguna mejora de rendimiento.
