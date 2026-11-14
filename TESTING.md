# Plan de Pruebas y Auditoría — TrackFlow (Auth API)

Este documento detalla el plan de pruebas unitarias y de integración implementado para asegurar la robustez de la API de autenticación de TrackFlow (Ticket AUTH-088), cumpliendo con los estándares de la rúbrica del programa.

## 1. Instrucciones de Ejecución

Para ejecutar la batería de pruebas y verificar la cobertura del código, utiliza los siguientes comandos desde la raíz del proyecto con el entorno virtual activo:

```bash
# Ejecutar la suite de pruebas completa con pytest
uv run pytest

# Ejecutar las pruebas y generar el reporte detallado de cobertura
uv run pytest --cov=auth --cov-report=term-missing
