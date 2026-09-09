from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

# Antes de importar los routers: leen configuración (SECRET_KEY, RESEND_API_KEY) desde el entorno.
load_dotenv(Path(__file__).resolve().parents[2] / ".env")

from .database import seed_database
from .routes.incidents import router as incidents_router
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


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    errors = [
        {
            "field": ".".join(str(part) for part in error["loc"] if part != "body"),
            "message": "El valor no es valido",
        }
        for error in exc.errors()
    ]
    return JSONResponse(status_code=400, content={"errors": errors})


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    return JSONResponse(
        status_code=500,
        content={"error": "Se produjo un error interno. Intentalo de nuevo."},
    )


# Incluimos las rutas de proveedores requeridas por la rúbrica
app.include_router(suppliers_router)
app.include_router(auth_router)
app.include_router(incidents_router)