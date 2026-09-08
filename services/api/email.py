import json
import os
from urllib import error, request


def send_password_reset_email(email: str, token: str) -> None:
  api_key = os.getenv("RESEND_API_KEY")
  frontend_url = os.getenv("FRONTEND_URL")
  sender = os.getenv("AUTH_EMAIL_FROM", "TrackFlow <onboarding@resend.dev>")
  if not api_key or not frontend_url:
    raise RuntimeError("RESEND_API_KEY and FRONTEND_URL must be configured")
  reset_url = f"{frontend_url.rstrip('/')}/reset-password?token={token}"
  payload = json.dumps({
      "from": sender,
      "to": [email],
      "subject": "Restablece tu contraseña de TrackFlow",
      "html": (
          "<p>Hemos recibido una solicitud para restablecer tu contraseña.</p>"
          f'<p><a href="{reset_url}">Restablecer contraseña</a></p>'
          "<p>El enlace caduca en 30 minutos.</p>"
      ),
  }).encode()
  email_request = request.Request(
      "https://api.resend.com/emails",
      data=payload,
      headers={
          "Authorization": f"Bearer {api_key}",
          "Content-Type": "application/json",
          "Accept": "application/json",
          # Sin User-Agent explícito, Cloudflare bloquea "Python-urllib" con un 403 (error 1010).
          "User-Agent": "TrackFlow-API/1.0",
      },
      method="POST",
  )
  try:
    with request.urlopen(email_request, timeout=10):
      pass
  except error.HTTPError as exc:
    detail = exc.read().decode(errors="replace")
    raise RuntimeError(f"Resend API error {exc.code}: {detail}") from exc