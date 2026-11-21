"""Arranca el servidor MCP de TrackFlow.

    python -m mcps.trackflow_mcp

Escucha en 0.0.0.0:`MCP_PORT` (8001 por defecto); el endpoint MCP es `/mcp`.
"""

import logging

import uvicorn

from .config import load_settings
from .server import create_app


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    settings = load_settings()
    logging.getLogger("mcp.audit").info(
        "TrackFlow MCP · recurso %s · issuer %s · API %s", settings.resource_url, settings.auth_issuer, settings.api_url
    )
    uvicorn.run(create_app(settings), host="0.0.0.0", port=settings.port)


if __name__ == "__main__":
    main()
