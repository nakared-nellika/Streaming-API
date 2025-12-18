"""FastAPI application exposing the WebSocket `/chat/stream` endpoint.

This module wires the WebSocket gateway to the orchestrator and runs a periodic
cleanup task for the event buffer retention window.
"""
import asyncio
import json
import os
import sys
from pathlib import Path

VB_BACKEND_DIR = Path(os.environ.get("VB_BACKEND_DIR", r"D:\VB-BACKEND\VB-BACKEND")).resolve()

# ทำให้ relative path ใน VB-BACKEND (เช่น prompts/...) ทำงานได้
os.chdir(VB_BACKEND_DIR)

# ทำให้ import `services.*` จาก VB-BACKEND ได้ชัวร์
if str(VB_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(VB_BACKEND_DIR))

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse

from buffer import EventBuffer
from orchestrator import Orchestrator

app = FastAPI()

buffer = EventBuffer()
orch = Orchestrator(buffer)


@app.on_event("startup")
async def startup_tasks():
    # Start a background task to cleanup old buffer entries periodically
    async def _cleanup_loop():
        while True:
            buffer.cleanup()
            await asyncio.sleep(30)

    asyncio.create_task(_cleanup_loop())


@app.websocket("/chat/stream")
async def chat_stream(ws: WebSocket):
    """WebSocket entrypoint for bidirectional streaming chat.

    Clients MUST send and receive messages following the unified envelope.
    Supported client events: `user_message`, `action`, `resume`, `stop`.
    Server emits: `token`, `status`, `card`, `done`, `error`.
    """
    await ws.accept()
    try:
        while True:
            data = await ws.receive_text()
            try:
                envelope = json.loads(data)
            except Exception:
                await ws.send_json({"type": "error", "payload": {"message": "invalid json"}})
                continue

            # Delegate to orchestrator
            await orch.handle_incoming(ws, envelope)

    except WebSocketDisconnect:
        return
