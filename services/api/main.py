import traceback
import logging
from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse

logger = logging.getLogger(__name__)

app = FastAPI(title="TrackFlow API")

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
            "error_id": error_id
        }
    )