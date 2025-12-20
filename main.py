"""FastAPI application exposing the WebSocket `/chat/stream` endpoint.

This module wires the WebSocket gateway to the orchestrator and runs a periodic
cleanup task for the event buffer retention window.
"""
import asyncio
import json
import os
import sys
from pathlib import Path

# Get the current directory (where main.py is located)
CURRENT_DIR = Path(__file__).parent.resolve()

# Set VB_BACKEND_DIR to current directory or environment variable if provided
VB_BACKEND_DIR = Path(os.environ.get("VB_BACKEND_DIR", str(CURRENT_DIR))).resolve()

# ทำให้ relative path ใน VB-BACKEND (เช่น prompts/...) ทำงานได้
os.chdir(VB_BACKEND_DIR)

# ทำให้ import `services.*` จาก VB-BACKEND ได้ชัวร์
if str(VB_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(VB_BACKEND_DIR))

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse

from buffer import EventBuffer
from orchestrator import Orchestrator

app = FastAPI()

# Add CORS middleware for frontend communication
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # In production, specify your frontend URL
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

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
            try:
                data = await ws.receive_text()
                try:
                    envelope = json.loads(data)
                    print("⬅", envelope)
                except json.JSONDecodeError as e:
                    await ws.send_json({
                        "type": "error", 
                        "payload": {
                            "message": f"invalid json: {str(e)}"
                        }
                    })
                    continue

                # Delegate to orchestrator
                await orch.handle_incoming(ws, envelope)

            except Exception as e:
                print(f"Error processing message: {e}")
                await ws.send_json({
                    "type": "error", 
                    "payload": {
                        "message": f"server error: {str(e)}"
                    }
                })

    except WebSocketDisconnect:
        print("Client disconnected")
        return
    except Exception as e:
        print(f"WebSocket error: {e}")
        try:
            await ws.send_json({
                "type": "error", 
                "payload": {
                    "message": f"connection error: {str(e)}"
                }
            })
        except:
            pass  # Connection might be closed already
        return
