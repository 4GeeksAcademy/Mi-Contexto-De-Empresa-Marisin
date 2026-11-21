"""Pide un access token OAuth (client_credentials) para el servidor MCP de TrackFlow.

Sirve para probar el servidor desde MCP Playground (pegar el token en el campo
Bearer) o desde `scripts/mcp_smoke_test.py`. Lee del `.env`:
`MCP_AUTH_ISSUER`, `MCP_RESOURCE_URL` y las credenciales de la app elegida.

    python scripts/mcp_get_token.py                    # app admin, los 3 scopes
    python scripts/mcp_get_token.py --app agent        # app del agente (solo lectura)
    python scripts/mcp_get_token.py --scopes incidents:read   # token con menos permisos
    python scripts/mcp_get_token.py --claims           # muestra también los claims (sin el token)

Nunca escribe el token en disco ni en el repo; solo lo imprime.
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APPS = {
    "admin": ("MCP_ADMIN_CLIENT_ID", "MCP_ADMIN_CLIENT_SECRET", "incidents:read incidents:write inventory:read"),
    "agent": ("MCP_AGENT_CLIENT_ID", "MCP_AGENT_CLIENT_SECRET", "incidents:read inventory:read"),
}


def request_token(app: str = "admin", scopes: str | None = None) -> dict:
    from dotenv import load_dotenv
    import httpx

    load_dotenv(ROOT / ".env")
    id_var, secret_var, default_scopes = APPS[app]
    issuer = os.environ.get("MCP_AUTH_ISSUER", "").rstrip("/")
    resource = os.environ.get("MCP_RESOURCE_URL", "")
    client_id, secret = os.environ.get(id_var, ""), os.environ.get(secret_var, "")
    missing = [name for name, value in (("MCP_AUTH_ISSUER", issuer), ("MCP_RESOURCE_URL", resource), (id_var, client_id), (secret_var, secret)) if not value]
    if missing:
        raise SystemExit(f"Faltan en .env: {', '.join(missing)}")
    with httpx.Client(timeout=10) as client:
        token_endpoint = client.get(f"{issuer}/.well-known/openid-configuration").json()["token_endpoint"]
        response = client.post(
            token_endpoint,
            data={"grant_type": "client_credentials", "resource": resource, "scope": scopes or default_scopes},
            auth=(client_id, secret),
        )
    if response.status_code != 200:
        raise SystemExit(f"El proveedor rechazó la petición ({response.status_code}): {response.text[:300]}")
    return response.json()


def claims(token: str) -> dict:
    payload = token.split(".")[1]
    return json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--app", choices=APPS, default="admin")
    parser.add_argument("--scopes", help="Scopes separados por espacios (por defecto, los de la app)")
    parser.add_argument("--claims", action="store_true", help="Muestra los claims del token en vez del token")
    args = parser.parse_args()
    token = request_token(args.app, args.scopes)["access_token"]
    if args.claims:
        visible = {key: value for key, value in claims(token).items() if key in {"iss", "aud", "sub", "client_id", "scope", "exp", "iat"}}
        print(json.dumps(visible, indent=2, ensure_ascii=False))
    else:
        print(token)
    return 0


if __name__ == "__main__":
    sys.exit(main())
