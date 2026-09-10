# services/api/email.py
import json
import urllib.request
import urllib.error
import os
import logging

logger = logging.getLogger(__name__)

def send_reset_email(to_email: str, reset_link: str) -> bool:
    api_key = os.getenv("RESEND_API_KEY")
    from_email = os.getenv("AUTH_EMAIL_FROM", "TrackFlow <onboarding@resend.dev>")
    
    if not api_key:
        logger.error("RESEND_API_KEY is not configured.")
        raise RuntimeError("Configuration error: Email service unavailable.")

    url = "https://api.resend.com/emails"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "User-Agent": "TrackFlow-Backend/1.0"
    }
    payload = {
        "from": from_email,
        "to": [to_email],
        "subject": "Restablecimiento de contraseña - TrackFlow",
        "html": f"<p>Has solicitado restablecer tu contraseña. Haz clic en el siguiente enlace: <a href='{reset_link}'>Restablecer Contraseña</a></p>"
    }
    
    req = urllib.request.Request(url, data=json.dumps(payload).encode('utf-8'), headers=headers, method="POST")
    
    try:
        with urllib.request.urlopen(req, timeout=10) as response:
            return response.status == 200
    except urllib.error.HTTPError as e:
        logger.error(f"External email API HTTP error status: {e.code}")
        raise RuntimeError("El servicio de correo externo rechazó la solicitud.")
    except urllib.error.URLError as e:
        logger.error(f"External email API network connection error: {e.reason}")
        raise RuntimeError("No se pudo conectar con el servicio de correo.")
    except TimeoutError:
        logger.error("External email API request timed out.")
        raise RuntimeError("Tiempo de espera agotado al conectar con el servicio de correo.")
    except Exception as e:
        logger.exception("Unexpected error while sending email.")
        raise RuntimeError("Error interno al enviar el correo de recuperación.")