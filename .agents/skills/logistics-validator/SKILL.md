# Skill: Validador de Datos Logísticos (SKU y Envíos)

## Descripción y Objetivo Único
Esta skill tiene como único objetivo verificar y validar de forma estructurada que los objetos de datos de inventario (SKUs) o las solicitudes de envío de última milla cumplan con los esquemas requeridos por los sistemas de TrackFlow antes de ser integrados en las vistas o servicios[cite: 1].

## Inputs Definidos
* `inputData`: Objeto JSON o fragmento de código TypeScript que contiene los datos del SKU, peso, dimensiones o código de seguimiento del transportista.
* `targetContext`: Contexto de destino (ej. almacén de Los Ángeles o Zaragoza)[cite: 2].

## Output Esperado
* Un informe de validación en formato Markdown o JSON que indique claramente si el elemento es `APROBADO` o `RECHAZADO`, detallando los campos faltantes o errores de formato encontrados.

## Criterios de Aceptación Verificables
1. **Verificación de Campos Obligatorios:** El script o agente debe comprobar de manera determinista que existan campos críticos (`sku_id`, `weight_kg`, `destination`).
2. **Control de Tipos Numéricos:** Validar que los pesos y dimensiones sean estrictamente valores numéricos positivos mayores a cero.
3. **Automatización Ejecutable:** La validación debe poder ejecutarse y comprobarse de forma independiente mediante una prueba o script local sin romper el flujo principal de compilación[cite: 1].