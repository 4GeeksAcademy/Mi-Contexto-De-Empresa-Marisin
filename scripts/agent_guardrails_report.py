"""Resumen de cuántas veces se activó cada guardrail (Hito 8 · Parte 2).

Mismo resumen que `GET /agent/guardrails/summary`, desde la terminal:

    python scripts/agent_guardrails_report.py
    python scripts/agent_guardrails_report.py --since 2026-11-22T10:00:00+00:00
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

from services.agent.harness import events as guard_events  # noqa: E402
from services.agent.memory.backend import MemoryUnavailable  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--since", default=None, help="ISO 8601: solo eventos desde ese instante")
    parser.add_argument("--recent", action="store_true", help="incluye los últimos 20 eventos")
    args = parser.parse_args(argv)
    load_dotenv(ROOT / ".env")
    try:
        summary = guard_events.get_log().summary(since=args.since)
    except MemoryUnavailable as exc:
        print(f"El registro de guardrails no está disponible: {exc}", file=sys.stderr)
        return 1
    if not args.recent:
        summary.pop("recent", None)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
