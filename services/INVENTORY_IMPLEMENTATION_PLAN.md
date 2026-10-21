# Plan de Implementación por Fases: Hito Backend Inventario (TrackFlow)

> **PROPÓSITO DE ESTE DOCUMENTO**: Este fichero contiene las reglas de negocio inquebrantables y los Criterios de Aceptación obligatorios para la implementación del módulo de inventario con Supabase y doble base de datos. La IA debe revisar estrictamente este documento antes de generar cualquier código.

## 📌 Reglas de Negocio Globales (NO NEGOCIABLES)
1. **Doble Base de Datos**: TinyDB se mantiene exclusivamente para usuarios y autenticación. Supabase (PostgreSQL vía SQLModel) gestiona todas las entidades de inventario y órdenes.
2. **Inmutabilidad del Stock**: El stock **NUNCA** es una columna editable directamente en la tabla de productos. Se calcula dinámicamente como: `SUMA(entradas) − SUMA(salidas)` (respetando restricciones por almacén/partición según el `company-BRIEFING.md`).
3. **Validación de Stock Insuficiente**: Si una orden de salida deja el stock en negativo, se debe rechazar **antes de persistir**, respondiendo con un `HTTP 400` y un mensaje descriptivo.
4. **Trazabilidad de Usuario**: Toda orden de entrada o salida debe almacenar el `user_uuid` del usuario autenticado (proveniente de TinyDB). No se replican tablas de usuarios en Supabase.
5. **Separación Estricta**: Los modelos ORM (`models.py`) y los schemas de Pydantic (`schemas.py`) deben estar en archivos separados. **Nunca** se retorna un objeto ORM directamente desde un endpoint.
6. **Inyección de Dependencias**: Usar siempre `Depends(get_db)` para obtener sesiones de SQLModel por petición. Cero variables de sesión globales.

---

## 🚀 FASES DE DESARROLLO

### FASE 1: Configuración de Base de Datos y Dependencias (`database.py`)
- **Objetivo**: Instalar librerías y configurar la doble conexión.
- **Acciones**:
  1. Instalar `sqlmodel` y `psycopg2-binary`.
  2. Configurar la URL de conexión de Supabase (usando Transaction pooler y formato URI) en `.env` (asegurando que `.env` esté en `.gitignore`).
  3. En `database.py`, inicializar el motor de SQLModel para Supabase y mantener el cliente TinyDB.
  4. Crear la dependencia `get_db` para inyectar sesiones por petición.

### FASE 2: Modelos ORM y Esquema (`models.py`)
- **Objetivo**: Definir las tablas relacionales vinculadas al `company-BRIEFING.md`.
- **Acciones**:
  1. Definir el modelo de Producto/SKU con `SQLModel, table=True`.
  2. Definir los modelos de Órdenes de Entrada y Salida con claves foráneas (`FK`) hacia el producto, campos de cantidad, `created_at` y `user_uuid` (como `str`).
  3. Añadir `SQLModel.metadata.create_all(engine)` al inicio de la aplicación para despliegue en desarrollo.

### FASE 3: Schemas Pydantic (`schemas.py`)
- **Objetivo**: Desacoplar validación y serialización de la base de datos.
- **Acciones**:
  1. Crear schemas independientes de request y response para productos y órdenes.
  2. Añadir el campo computado `current_stock` en el schema de respuesta del producto.

### FASE 4: Lógica de Negocio, Validaciones y Router (`routers/inventory.py`)
- **Objetivo**: Exponer la API bajo `/inventory` cumpliendo todas las normativas.
- **Acciones**:
  1. Crear un `APIRouter` con prefijo `/inventory` y registrarlo en `main.py`.
  2. Implementar `GET /inventory/products` (calculando stock dinámico).
  3. Implementar `POST /inventory/products` (requiere auth).
  4. Implementar `GET /inventory/products/{id}`.
  5. Implementar `POST /inventory/orders/inbound` (registra entrada, inyecta `user_uuid` de TinyDB).
  6. Implementar `POST /inventory/orders/outbound` (valida stock disponible; rechaza con `HTTP 400` si hay déficit; registra salida e inyecta `user_uuid`).
  7. Implementar `GET /inventory/orders` (lista órdenes con datos de producto y usuario).

### FASE 5: Datos Semilla (`seed.py`)
- **Objetivo**: Poblar la base de datos con los datos mínimos del briefing.
- **Acciones**:
  1. Crear un script de inicialización (`seed.py`) que inserte los productos, entradas y salidas base.
  2. Verificar que `GET /inventory/products` refleje correctamente los stocks calculados netos.
  