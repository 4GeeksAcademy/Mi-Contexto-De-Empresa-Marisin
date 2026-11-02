# Plan de Implementación por Fases: Hito Backend Inventario (TrackFlow)

> **PROPÓSITO DE ESTE DOCUMENTO**: Este fichero contiene las reglas de negocio inquebrantables y los Criterios de Aceptación obligatorios para la implementación del módulo de inventario con Supabase y doble base de datos. La IA debe revisar estrictamente este documento antes de generar cualquier código.

## 📌 Reglas de Negocio Globales (NO NEGOCIABLES)
1. **Doble Base de Datos**: TinyDB se mantiene exclusivamente para usuarios y autenticación. Supabase (PostgreSQL vía SQLModel) gestiona todas las entidades de inventario y órdenes.
2. **Inmutabilidad del Stock**: El stock **NUNCA** es una columna editable directamente en la tabla de productos. Se calcula dinámicamente como: `SUMA(entradas) − SUMA(salidas)` (respetando restricciones por almacén/partición según el `CONTEXT.md`).
3. **Validación de Stock Insuficiente**: Si una orden de salida deja el stock en negativo, se debe rechazar **antes de persistir**, respondiendo con un `HTTP 400` y un mensaje descriptivo.
4. **Trazabilidad de Usuario**: Toda orden de entrada o salida debe almacenar el `user_uuid` del usuario autenticado (proveniente de TinyDB). No se replican tablas de usuarios en Supabase.
5. **Separación Estricta**: Los modelos ORM (`models.py`) y los schemas de Pydantic (`schemas.py`) deben estar en archivos separados. **Nunca** se retorna un objeto ORM directamente desde un endpoint.
6. **Inyección de Dependencias**: Usar siempre `Depends(get_db)` para obtener sesiones de SQLModel por petición. Cero variables de sesión globales.
