"""Limpieza y consolidación de la memoria del agente (Hito 8 · Parte 1).

Descarta las propuestas pendientes caducadas (sin respuesta del usuario), elimina
los hechos vencidos según la caducidad de su categoría y aplica los topes de
slots. Todo lo que borra queda en el registro de auditoría.

    python scripts/agent_memory_consolidate.py            # Redis (REDIS_URL)
    python scripts/agent_memory_consolidate.py --show     # además, imprime la memoria consolidada

Se puede programar con cron, como el script nocturno (ver infra/cron/), p. ej.:

    */30 * * * * cd /workspaces/Mi-Contexto-De-Empresa-Marisin && .venv/bin/python scripts/agent_memory_consolidate.py
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv  # noqa: E402

from services.agent.memory.backend import MemoryUnavailable  # noqa: E402
from services.agent.memory.store import build_store  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--backend", choices=["redis", "memory"], default=None)
    parser.add_argument("--show", action="store_true", help="imprime los slots consolidados")
    args = parser.parse_args(argv)
    load_dotenv(ROOT / ".env")

    store = build_store(args.backend)
    try:
        report = store.consolidate()
        output = {"report": report}
        if args.show:
            output["slots"] = [slot.model_dump(mode="json") for slot in store.list_slots()]
    except MemoryUnavailable as exc:
        print(f"La memoria no está disponible: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(output, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
