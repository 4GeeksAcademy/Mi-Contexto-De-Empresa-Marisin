import logging
import time
import traceback
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, Request, Response, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlmodel import SQLModel

# Antes de importar los routers: leen configuración desde el entorno.
load_dotenv(Path(__file__).resolve().parents[2] / ".env")

from . import models
from .database import engine, seed_database
from .routes.auth import router as auth_router
from .routes.incidents import router as incidents_router  # NUEVO
from .routes.inventory import router as inventory_router
from .routes.profiles import router as profiles_router
from .routes.suppliers import router as suppliers_router
from .routes.tasks import router as tasks_router
from .routes.telemetry import router as telemetry_router
from .routes.users import router as users_router

try:
    # API arrancada desde la raíz del repo: `uvicorn services.api.main:app`.
    from services.reporting.router import router as reporting_router
except ModuleNotFoundError as exc:
    if exc.name not in {"services", "services.reporting"}:
        raise
    # Contenedor de Docker: /app es `services/`, así que el paquete es `reporting`.
    from reporting.router import router as reporting_router

try:
    # Asistente comercial RAG (Hito 7). Misma convención de import que reporting.
    from services.knowledge.router import router as knowledge_router
except ModuleNotFoundError as exc:
    if exc.name not in {"services", "services.knowledge"}:
        raise
    from knowledge.router import router as knowledge_router

try:
    # Agente de soporte LangGraph: importar el router compila el grafo al arrancar.
    from services.agent.router import router as agent_router
except ModuleNotFoundError as exc:
    if exc.name not in {"services", "services.agent"}:
        raise
    from agent.router import router as agent_router

try:
    # Recepción de RFPs (Hito 9 · Parte 1): el grafo `rfp_intake` vive en data/pipelines/.
    from services.rfp.router import router as rfp_router
except ModuleNotFoundError as exc:
    if exc.name not in {"services", "services.rfp"}:
        raise
    from rfp.router import router as rfp_router

try:
    # Notificaciones SSE (tiempo real · Parte 1): importarlo registra el broker en el pipeline de RFPs.
    from services.realtime.router import router as realtime_router
except ModuleNotFoundError as exc:
    if exc.name not in {"services", "services.realtime"}:
        raise
    from realtime.router import router as realtime_router

app = FastAPI(
    title="TrackFlow - Supplier Directory API",
    version="1.0.0",
    description="API RESTful para la gestión del directorio de proveedores",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://localhost:3001",
        "http://127.0.0.1:3000",
        "http://127.0.0.1:3001",
    ],
    allow_origin_regex=r"https://.*\.app\.github\.dev",
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

timing_logger = logging.getLogger("api.timing")
timing_logger.setLevel(logging.INFO)
if not timing_logger.handlers:
    timing_handler = logging.StreamHandler()
    timing_handler.setFormatter(logging.Formatter("%(message)s"))
    timing_logger.addHandler(timing_handler)
timing_logger.propagate = False


@app.middleware("http")
async def timing_middleware(request: Request, call_next):
    started_at = time.perf_counter()
    response: Response = await call_next(request)
    elapsed_ms = (time.perf_counter() - started_at) * 1000
    response.headers["X-Response-Time-ms"] = f"{elapsed_ms:.1f}"

    request_path = request.url.path
    if request.url.query:
        request_path = f"{request_path}?{request.url.query}"
    timing_logger.info(
        "%s %s → %s | %.1fms",
        request.method,
        request_path,
        response.status_code,
        elapsed_ms,
    )
    return response


logger = logging.getLogger(__name__)


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    error_id = abs(hash(str(exc))) % 1000000

    # Registrar el error completo en el servidor de forma segura
    logger.error(f"Unhandled internal error [ID: {error_id}] on {request.url.path}: {str(exc)}")
    logger.debug(traceback.format_exc())

    # Respuesta limpia y estructurada para el cliente (sin trazas internas)
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={
            "error": "Internal Server Error",
            "message": "Ha ocurrido un error inesperado en el servidor. Por favor, inténtelo de nuevo más tarde.",
            "error_id": error_id,
        },
    )


@app.on_event("startup")
async def startup_event():
    if engine is not None:
        SQLModel.metadata.create_all(engine)
    seed_database()


# Incluimos todos los routers de la API
app.include_router(suppliers_router)
app.include_router(users_router)
app.include_router(auth_router)
app.include_router(profiles_router)
app.include_router(inventory_router)
app.include_router(incidents_router)  # NUEVO
app.include_router(telemetry_router)
app.include_router(reporting_router)
app.include_router(tasks_router)
app.include_router(knowledge_router)
app.include_router(agent_router)
app.include_router(rfp_router)
app.include_router(realtime_router)
