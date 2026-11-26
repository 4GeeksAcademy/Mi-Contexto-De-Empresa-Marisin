"""Chat del First-line CX agent por WebSocket (Sistemas en tiempo real · Parte 2).

El agente no cambia: este subpaquete solo es el canal. `router.py` expone
`POST /agent/chat/sessions` y el WebSocket `/agent/chat/sessions/{session_id}/ws`;
`turns.py` es el productor único por sesión (llama a `runner.run_agent` con
tokens y cancelación); `pubsub.py` reparte los eventos del canal
`chat.<session_id>` a todas las conexiones; `store.py` persiste sesiones y mensajes.
"""
