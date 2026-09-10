from fastapi import APIRouter, HTTPException, status
from datetime import datetime
import logging

from services.api.email import send_reset_email

logger = logging.getLogger(__name__)
router = APIRouter()

@router.post("/auth/forgot-password")
def forgot_password(payload: dict):
    user_email = payload.get("email")
    # Lógica de búsqueda de usuario simulada / o real en tu base de datos
    user = {"email": user_email} 
    reset_link = "https://example.com/reset"

    try:
        send_reset_email(user["email"], reset_link)
    except RuntimeError as e:
        logger.error(f"Email dispatch failed for user recovery: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="No se pudo procesar el correo de recuperación en este momento."
        )
    
    return {"message": "Si el correo está registrado, se han enviado las instrucciones."}

@router.post("/auth/reset-password")
def reset_password(payload: dict):
    token_data = {"expires_at": payload.get("expires_at")}
    
    try:
        expires_at = datetime.fromisoformat(token_data["expires_at"])
    except (ValueError, KeyError) as e:
        logger.warning("Corrupted token expiration format encountered in database.")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="El token de recuperación es inválido o está malformado."
        )

    return {"message": "Contraseña restablecida correctamente con éxito."}