# Inventario: fase 1

Instalar desde la raiz del repositorio:

```sh
python -m pip install -e .
```

En el archivo `.env` de la raiz, conservar las variables de autenticacion y
anadir `DATABASE_URL` con la URI de Supabase > Connect > Transaction pooler:

```dotenv
DATABASE_URL=postgresql://postgres.PROJECT_REF:PERCENT_ENCODED_PASSWORD@aws-0-REGION.pooler.supabase.com:6543/postgres?sslmode=require
```

Usar el host y usuario exactos del panel de Supabase. Codificar los caracteres
especiales de la contrasena como componentes de URI. No usar la URL HTTP del
proyecto ni las claves anon/service_role. `.env` ya esta excluido por `.gitignore`.
No publicar credenciales ni pegarlas en el chat.

`database.py` carga el entorno sin sobrescribir variables ya exportadas. El motor
usa psycopg2, TLS y `NullPool`: el pool de transacciones lo gestiona Supabase.
Crear el motor no abre conexiones ni crea tablas.

Los futuros endpoints de inventario deben obtener `Session` mediante
`Depends(get_db)`. Cada invocacion obtiene una sesion distinta, cerrada al terminar,
incluso si hay excepciones. La dependencia no confirma transacciones implicitamente.

Sin `DATABASE_URL`, la API existente y TinyDB siguen operativos; invocar `get_db`
produce un error explicito de configuracion. No hay fallback de inventario a TinyDB.
Se conservan la ruta JSON, las tablas existentes (incluidos proveedores y perfiles),
el bloqueo de autenticacion y la funcion de semilla, sin migraciones ni borrados.

Esta fase no introduce modelos, schemas, endpoints, datos semilla de inventario
ni `metadata.create_all`. Para comprobar la conexion real tras configurar la URI:

```sh
python - <<'PY'
from sqlalchemy import text
from services.api.database import get_db

dependency = get_db()
session = next(dependency)
try:
    assert session.exec(text("SELECT 1")).scalar_one() == 1
    print("Supabase: conexion correcta")
finally:
    dependency.close()
PY
```