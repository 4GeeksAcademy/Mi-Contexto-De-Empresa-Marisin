"""Sonda del WebSocket del chat de soporte: evidencia medible del abort y del rechazo sin token.

Con el modelo a ~200 tokens/s una persona no puede interrumpir a mitad de los
tokens desde la UI; esta sonda sí: con `--interrupt-after N` envía
`interrupt_requested` **en cuanto recibe** el `token_chunk` N (antes de leer
otro frame) y cuenta los tokens del mensaje viejo en tres tramos:

* antes de enviar la interrupción;
* en vuelo: entre el envío y `generation_interrupted` (ya estaban en la red o en
  la cola del socket; es normal que haya alguno);
* **después de `generation_interrupted`** — la métrica del abort, debe ser 0.

Uso (el JWT del backoffice va en la variable `TRACKFLOW_TOKEN`; nunca se imprime):

    python scripts/agent_chat_ws_probe.py --no-token
    python scripts/agent_chat_ws_probe.py --question "¿Cuál es la ventana de devolución en España?"
    python scripts/agent_chat_ws_probe.py --question "…" --interrupt-after 5 \\
        --new-input "espera, quiero hacer una devolución, no rastrear el pedido"

Sin `--session` crea una sesión nueva (`POST /agent/chat/sessions`). Sale con
código 1 si llega algún token del mensaje viejo tras `generation_interrupted`.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime

from websockets.asyncio.client import connect
from websockets.exceptions import ConnectionClosed

TOKEN_ENV = "TRACKFLOW_TOKEN"
DEFAULT_BASE_URL = "http://127.0.0.1:8000"
UNKNOWN_SESSION = "chat_000000000000"


class Clock:
    def __init__(self) -> None:
        self.start = time.perf_counter()

    def ms(self) -> float:
        return (time.perf_counter() - self.start) * 1000


def redact(text: str) -> str:
    return re.sub(r"token=[^&\s]+", "token=[redacted]", text)


def log(clock: Clock, text: str) -> None:
    wall = datetime.now().strftime("%H:%M:%S.%f")[:-3]
    print(f"{wall} [+{clock.ms():8.1f} ms] {text}", flush=True)


def describe(event: dict) -> str:
    name, data = event.get("event"), event.get("data") or {}
    if name == "token_chunk":
        return f"token_chunk   {data.get('message_id')} #{data.get('sequence')} {data.get('token')!r}"
    if name == "session_snapshot":
        active = data.get("active_generation")
        return (f"session_snapshot mensajes={len(data.get('messages') or [])} "
                f"status={(data.get('session') or {}).get('status')} en_curso={active and active.get('message_id')}")
    if name == "generation_completed":
        answer = (data.get("answer") or "").replace("\n", " ")
        return f"generation_completed {data.get('message_id')} status={data.get('status')} answer={answer[:80]!r}…"
    if name == "user_message":
        return f"user_message  {data.get('message_id')} {data.get('text')!r}"
    if name == "chat_error":
        return f"chat_error    code={data.get('code')} {data.get('detail')!r}"
    rest = {key: value for key, value in data.items() if key != "session_id"}
    return f"{name} {json.dumps(rest, ensure_ascii=False)}"


def create_session(base_url: str, token: str, client_id: str) -> str:
    request = urllib.request.Request(
        f"{base_url}/agent/chat/sessions", method="POST",
        data=json.dumps({"client_id": client_id}).encode(),
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {token}"},
    )
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            return json.load(response)["session_id"]
    except urllib.error.HTTPError as error:
        sys.exit(f"POST /agent/chat/sessions → HTTP {error.code}: {error.read().decode(errors='replace')[:200]}")


def ws_url(base_url: str, session_id: str, token: str | None) -> str:
    url = re.sub(r"^http", "ws", base_url.rstrip("/")) + f"/agent/chat/sessions/{session_id}/ws"
    return f"{url}?token={token}" if token else url


async def probe_no_token(args: argparse.Namespace) -> int:
    clock = Clock()
    url = ws_url(args.base_url, args.session or UNKNOWN_SESSION, None)
    log(clock, f"→ conectando SIN token a {url}")
    frames = 0
    async with connect(url, open_timeout=10) as ws:
        try:
            while True:
                raw = await asyncio.wait_for(ws.recv(), timeout=args.timeout)
                frames += 1
                log(clock, f"✗ frame inesperado: {raw[:120]}")
        except ConnectionClosed as closed:
            code = closed.rcvd.code if closed.rcvd else None
            reason = closed.rcvd.reason if closed.rcvd else ""
            log(clock, f"← cerrado con {code} ({reason}) tras {frames} frames")
    ok = code == 4401 and frames == 0
    print(f"\nresultado: close_code={code} frames_before_close={frames} → {'OK' if ok else 'FALLO'}")
    return 0 if ok else 1


async def probe_chat(args: argparse.Namespace, token: str) -> int:
    session_id = args.session or create_session(args.base_url, token, args.client_id)
    clock = Clock()
    url = ws_url(args.base_url, session_id, token)
    log(clock, f"→ conectando a {redact(url)}")
    stats = {"before": 0, "in_flight": 0, "after": 0, "new": 0}
    old_id = new_id = None
    sent_at = first_token_at = last_old_token_at = interrupt_at = ack_at = None
    done_reason = "timeout"

    async with connect(url, open_timeout=10, max_size=2**22) as ws:
        first = json.loads(await asyncio.wait_for(ws.recv(), timeout=args.timeout))
        log(clock, f"← {describe(first)}")
        if first.get("event") != "session_snapshot":
            print("✗ el primer frame no es session_snapshot")
            return 1
        await ws.send(json.dumps({"event": "user_message", "data": {"session_id": session_id, "text": args.question}}))
        sent_at = clock.ms()
        log(clock, f"→ user_message {args.question!r}")

        deadline = time.monotonic() + args.timeout
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            try:
                raw = await asyncio.wait_for(ws.recv(), timeout=remaining)
            except asyncio.TimeoutError:
                if ack_at is not None and not args.new_input:
                    done_reason = f"{args.grace:.1f} s de espera tras generation_interrupted sin más tokens"
                break
            event = json.loads(raw)
            name, data = event.get("event"), event.get("data") or {}
            log(clock, f"← {describe(event)}")
            message_id = data.get("message_id")

            if name == "generation_started":
                if old_id is None:
                    old_id = message_id
                elif interrupt_at is not None and message_id != old_id:
                    new_id = message_id
            elif name == "token_chunk" and message_id == old_id:
                if ack_at is not None:
                    stats["after"] += 1
                    log(clock, "✗ token del mensaje viejo DESPUÉS de generation_interrupted")
                elif interrupt_at is not None:
                    stats["in_flight"] += 1
                else:
                    stats["before"] += 1
                    first_token_at = first_token_at or clock.ms()
                last_old_token_at = clock.ms()
                if args.interrupt_after and interrupt_at is None and data.get("sequence", 0) >= args.interrupt_after:
                    # En cuanto llega el token N: interrumpir antes de leer otro frame.
                    payload = {"session_id": session_id}
                    if args.new_input:
                        payload["new_input"] = args.new_input
                    await ws.send(json.dumps({"event": "interrupt_requested", "data": payload}))
                    interrupt_at = clock.ms()
                    log(clock, f"→ interrupt_requested tras el token #{data.get('sequence')}"
                               + (f" con new_input={args.new_input!r}" if args.new_input else ""))
            elif name == "token_chunk" and message_id == new_id:
                stats["new"] += 1
            elif name == "generation_interrupted" and message_id == old_id:
                ack_at = clock.ms()
                if not args.new_input:
                    deadline = time.monotonic() + args.grace  # se sigue escuchando por si llega algo tardío
            elif name == "generation_completed":
                if message_id == old_id and interrupt_at is None:
                    done_reason = "respuesta completa (sin interrupción)"
                    break
                if message_id == old_id:
                    done_reason = "la respuesta terminó antes de que llegara la interrupción"
                    break
                if message_id == new_id:
                    done_reason = "respuesta del turno nuevo completa"
                    break
            elif name == "chat_error" and data.get("code") == "nothing_to_interrupt":
                done_reason = "nothing_to_interrupt: la respuesta ya había terminado"
                break

    print("\n── resumen ─────────────────────────────────────────────")
    print(f"session_id = {session_id}")
    print(f"old_message_id = {old_id}")
    if first_token_at is not None and sent_at is not None:
        print(f"first_token_ms (desde user_message) = {first_token_at - sent_at:.0f}")
    print(f"tokens_before_interrupt = {stats['before']}")
    if args.interrupt_after:
        print(f"tokens_in_flight (entre el envío y generation_interrupted) = {stats['in_flight']}")
        if interrupt_at is not None and ack_at is not None:
            print(f"interrupt_to_generation_interrupted_ms = {ack_at - interrupt_at:.0f}")
        print(f"tokens_after_interrupt_for_old_message = {stats['after']}")
        print(f"new_message_id = {new_id}")
        print(f"tokens_new_message = {stats['new']}")
    elif first_token_at is not None and last_old_token_at is not None and stats["before"] > 1:
        seconds = (last_old_token_at - first_token_at) / 1000
        print(f"streaming_ms = {seconds * 1000:.0f} (~{stats['before'] / seconds:.0f} tokens/s)" if seconds else "")
    print(f"fin: {done_reason}")
    if args.interrupt_after and ack_at is None:
        print("⚠ no llegó generation_interrupted: prueba con un --interrupt-after menor")
        return 1
    return 1 if stats["after"] else 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--base-url", default=os.environ.get("TRACKFLOW_API_URL", DEFAULT_BASE_URL))
    parser.add_argument("--no-token", action="store_true", help="conecta sin JWT: espera el cierre 4401 sin eventos")
    parser.add_argument("--session", help="session_id existente (si no, se crea una con --client-id)")
    parser.add_argument("--client-id", default="ecowear_usa")
    parser.add_argument("--question", default="¿Cuál es la ventana de devolución estándar en España?")
    parser.add_argument("--interrupt-after", type=int, default=0, metavar="N",
                        help="envía interrupt_requested en cuanto recibe el token_chunk N")
    parser.add_argument("--new-input", help="new_input de la interrupción (empieza un turno nuevo)")
    parser.add_argument("--timeout", type=float, default=60.0, help="segundos máximos de espera")
    parser.add_argument("--grace", type=float, default=2.0,
                        help="segundos escuchando tras generation_interrupted (sin --new-input)")
    args = parser.parse_args()

    if args.no_token:
        return asyncio.run(probe_no_token(args))
    token = os.environ.get(TOKEN_ENV)
    if not token:
        print(f"Falta el JWT del backoffice en la variable {TOKEN_ENV}.", file=sys.stderr)
        return 2
    return asyncio.run(probe_chat(args, token))


if __name__ == "__main__":
    sys.exit(main())
