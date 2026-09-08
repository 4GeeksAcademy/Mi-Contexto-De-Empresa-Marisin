from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI

# Antes de importar los routers: leen configuración (SECRET_KEY, RESEND_API_KEY) desde el entorno.
load_dotenv(Path(__file__).resolve().parents[2] / ".env")

from .database import seed_database
from .routes.suppliers import router as suppliers_router
from .routes.auth import router as auth_router

app = FastAPI(
    title="TrackFlow - Supplier Directory API",
    version="1.0.0",
    description="API RESTful para la gestión del directorio de proveedores",
)


@app.on_event("startup")
async def startup_event():
    seed_database()


# Incluimos las rutas de proveedores requeridas por la rúbrica
app.include_router(suppliers_router)
app.include_router(auth_router)