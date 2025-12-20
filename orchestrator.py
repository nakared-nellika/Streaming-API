"""Orchestrator layer: manages conversation state machine and drives event emission.

Integration uses VBChatbot (LangGraph) which yields streamed chunks and interrupt tuples.
We buffer small chunks into larger text tokens for UI friendliness.
"""

import os
import sys
from pathlib import Path

# Add the services directory to the path for importing
current_dir = Path(__file__).parent
services_dir = current_dir / 'services'
sys.path.insert(0, str(services_dir))

from services.agent import VBChatbot

import asyncio
from enum import Enum
from typing import Dict, Optional, Any

from events import make_event
from buffer import EventBuffer


class State(str, Enum):
    Idle = "Idle"
    WaitingInput = "WaitingInput"
    Analyzing = "Analyzing"
    Generating = "Generating"
    CardReady = "CardReady"
    WaitingAction = "WaitingAction"
    ProcessingAction = "ProcessingAction"
    Completed = "Completed"
    Error = "Error"


class Conversation:
    def __init__(self, conversation_id: str):
        self.id = conversation_id
        self.state: State = State.Idle
        self.sequence = 0
        self.sent_event_ids: set[str] = set()
        self.current_task: Optional[asyncio.Task] = None
        self.vb: Optional[VBChatbot] = None

        # --- added: identity/context ---
        self.user_id: Optional[str] = None
        self.user_info: Dict[str, Any] = {}


class Orchestrator:
    def __init__(self, buffer: EventBuffer):
        self.buffer = buffer
        self.conversations: Dict[str, Conversation] = {}
        self._locks: Dict[str, asyncio.Lock] = {}

    def _ensure_conv(self, conversation_id: str) -> Conversation:
        if conversation_id not in self.conversations:
            self.conversations[conversation_id] = Conversation(conversation_id)
            self._locks[conversation_id] = asyncio.Lock()
        return self.conversations[conversation_id]

    # --- added: extract user_id/user_info from envelope ---
    def _extract_user_ctx(self, envelope: Dict[str, Any]) -> Dict[str, Any]:
        payload = envelope.get("payload", {}) or {}
        print("extracting user context from envelope:", envelope)
        user_info = payload.get("user_info") or envelope.get("user_info") or {}
        if not isinstance(user_info, dict):
            user_info = {}

        user_id = (
            envelope.get("user_id")
            or payload.get("user_id")
            or user_info.get("user_id")
        )
        if user_id is not None:
            user_id = str(user_id)

        # keep user_id inside user_info too
        if user_id and "user_id" not in user_info:
            user_info = dict(user_info)
            user_info["user_id"] = user_id

        return {"user_id": user_id, "user_info": user_info}

    async def handle_incoming(self, websocket, envelope: Dict[str, Any]):
        t = envelope.get("type")
        conv_id = envelope.get("conversation_id")
        if not t or not conv_id:
            await self._safe_send_json(websocket, {"type": "error", "payload": {"message": "missing type or conversation_id"}})
            return

        conv = self._ensure_conv(conv_id)

        # --- added: update conv user context when provided ---
        ctx = self._extract_user_ctx(envelope)
        if ctx.get("user_id"):
            conv.user_id = ctx["user_id"]
        if ctx.get("user_info"):
            conv.user_info = ctx["user_info"]

        if t == "resume":
            await self._handle_resume(websocket, conv, envelope)
            return
        if t == "user_message":
            await self._handle_user_message(websocket, conv, envelope)
            return
        if t == "action":
            await self._handle_action(websocket, conv, envelope)
            return
        if t == "stop":
            await self._handle_stop(websocket, conv, envelope)
            return

        await self._emit(websocket, conv, "error", {"message": f"unknown client event type {t}"})

    async def _handle_resume(self, websocket, conv: Conversation, envelope: Dict[str, Any]):
        payload = envelope.get("payload", {})
        last_sequence = payload.get("last_sequence")
        if last_sequence is None:
            await self._emit(websocket, conv, "error", {"message": "resume missing last_sequence"})
            return

        events = self.buffer.replay(conv.id, int(last_sequence))
        for ev in sorted(events, key=lambda e: e.get("sequence", 0)):
            eid = ev.get("event_id")
            if eid and eid in conv.sent_event_ids:
                continue
            ok = await self._safe_send_json(websocket, ev)
            if not ok:
                return
            if eid:
                conv.sent_event_ids.add(eid)

    async def _handle_user_message(self, websocket, conv: Conversation, envelope: Dict[str, Any]):
        payload = envelope.get("payload", {})
        text = payload.get("text", "")

        conv.state = State.Analyzing
        await self._emit(websocket, conv, "status", {"status": "analyzing"})

        # cancel previous task (กรณีผู้ใช้พิมพ์ใหม่ระหว่างกำลัง generate)
        if conv.current_task and not conv.current_task.done():
            conv.current_task.cancel()

        # create chatbot instance for this conversation (kept for resume)
        if conv.vb is None:
            conv.vb = VBChatbot()

        conv.state = State.Generating
        conv.current_task = asyncio.create_task(
            self._run_vb_stream(
                websocket=websocket,
                conv=conv,
                message=text,
                resume=False,
                user_info=conv.user_info,   # --- changed: pass user_info from conv ---
            )
        )

    async def _handle_action(self, websocket, conv: Conversation, envelope: Dict[str, Any]):
        if conv.state != State.WaitingAction:
            await self._emit(websocket, conv, "error", {"message": "no action expected in current state"})
            return

        payload = envelope.get("payload", {})
        action_id = payload.get("id") or payload.get("action") or payload.get("action_id") or ""
        action_id = str(action_id)
        print(f"Received action: {action_id}")

        conv.state = State.ProcessingAction
        await self._emit(websocket, conv, "status", {"status": "processing_action"})

        # *** ไม่ต้อง cancel task เดิม ***
        # เพราะตอน interrupt เรา return ออกจาก _run_vb_stream แล้ว task เดิมจบไปแล้ว

        if conv.vb is None:
            conv.vb = VBChatbot()

        conv.state = State.Generating
        conv.current_task = asyncio.create_task(
            self._run_vb_stream(
                websocket=websocket,
                conv=conv,
                message=action_id,
                resume=True,
                user_info=conv.user_info,   # --- changed: pass user_info from conv ---
            )
        )

    async def _handle_stop(self, websocket, conv: Conversation, envelope: Dict[str, Any]):
        if conv.current_task and not conv.current_task.done():
            conv.current_task.cancel()
            await asyncio.sleep(0)
        conv.state = State.Completed
        await self._emit(websocket, conv, "done", {"message": "stopped"})

    # -------- VBChatbot integration --------

    def _should_flush(self, buf: str) -> bool:
        if not buf:
            return False
        if "\n" in buf:
            return True
        if len(buf) >= 200:
            return True
        if buf.endswith((" ", ".", "!", "?", "…", "ฯ", "。")) and len(buf) >= 25:
            return True
        return False

    def _normalize_chunk(self, s: str) -> str:
        if not s:
            return s
        return s.replace("\r\n", "").replace("\r", "")

    # --- changed: accept user_info param ---
    async def _run_vb_stream(self, websocket, conv: Conversation, message: str, resume: bool = False, user_info: Optional[Dict[str, Any]] = None):
        buffer_text = ""
        try:
            vb = conv.vb or VBChatbot()
            conv.vb = vb

            # fallback user_id if none provided (keeps old demo behavior but not hardcoded only)
            ui = user_info or {}
            if not isinstance(ui, dict):
                ui = {}
            if conv.user_id and "user_id" not in ui:
                ui = dict(ui)
                ui["user_id"] = conv.user_id
            if "user_id" not in ui:
                ui = dict(ui)
                ui["user_id"] = "demo-user-222xxx"

            async for chunk in vb.run(
                thread_id=conv.id,
                message=message,
                resume=resume,
                user_info=ui,  # --- changed: use ui from client/conv ---
            ):
                if conv.state != State.Generating:
                    break

                # INTERRUPT
                if isinstance(chunk, tuple) and len(chunk) >= 2 and chunk[0] == "Interrupt:":
                    question = str(chunk[1])

                    if buffer_text.strip():
                        await self._emit(websocket, conv, "token", {"text": buffer_text})
                        buffer_text = ""

                    await self._emit(websocket, conv, "card", self._build_confirm_card(question))
                    conv.state = State.WaitingAction
                    await self._emit(websocket, conv, "status", {"status": "waiting_action"})
                    return

                # TEXT
                if isinstance(chunk, str) and chunk:
                    buffer_text += self._normalize_chunk(chunk)
                    if self._should_flush(buffer_text):
                        await self._emit(websocket, conv, "token", {"text": buffer_text})
                        buffer_text = ""
                    continue

                # DICT
                if isinstance(chunk, dict):
                    if buffer_text.strip():
                        await self._emit(websocket, conv, "token", {"text": buffer_text})
                        buffer_text = ""

                    et = chunk.get("type")
                    pl = chunk.get("payload", chunk)
                    # LangGraph streaming adapter: treat {"stream": "..."} as token
                    if not et and "stream" in chunk:
                        await self._emit(websocket, conv, "token", {"text": chunk["stream"]})
                        continue
                    # Ensure card-locked status surfaces only after confirm action (resume=True)
                    if et == "status" and isinstance(pl, dict) and pl.get("status") == "Card temporarily locked" and not resume:
                        # Skip early emission to keep ordering below the action card
                        continue
                    if et in ("status", "card", "token", "done", "error"):
                        await self._emit(websocket, conv, et, pl)
                    else:
                        await self._emit(websocket, conv, "status", {"status": "update", "data": chunk})
                    continue

            if buffer_text.strip():
                await self._emit(websocket, conv, "token", {"text": buffer_text})

            conv.state = State.Completed
            print(f"Conversation {resume} completed.")
            await self._emit(websocket, conv, "done", {"message": "completed" if not resume else "action_processed"})

        except asyncio.CancelledError:
            conv.state = State.Completed
            await self._emit(websocket, conv, "status", {"status": "stopped"})
        except Exception as e:
            conv.state = State.Error
            await self._emit(websocket, conv, "error", {"message": str(e)})

    # -------- Safe emit / buffer --------

    async def _safe_send_json(self, websocket, payload: Dict[str, Any]) -> bool:
        """Send json but never crash the whole websocket handler."""
        try:
            await websocket.send_json(payload)
            return True
        except Exception:
            # ถ้า client หลุดไปแล้ว จะส่งไม่ได้ -> อย่าให้ล้ม
            return False

    async def _emit(self, websocket, conv: Conversation, event_type: str, payload: Dict[str, Any]):
        async with self._locks[conv.id]:
            conv.sequence += 1
            seq = conv.sequence
            ev = make_event(event_type, conv.id, seq, payload)

            # --- added: attach user_id at event top-level so client sees it ---
            if conv.user_id:
                ev["user_id"] = conv.user_id

            ok = await self._safe_send_json(websocket, ev)
            if not ok:
                return

            self.buffer.append(conv.id, seq, ev)

            ev_id = ev.get("event_id")
            if ev_id:
                conv.sent_event_ids.add(ev_id)

    # -------- Card --------

    def _build_confirm_card(self, question: str) -> Dict[str, Any]:
        return {
            "title": "Confirm Action",
            "badge": None,
            "sections": [{"kind": "note", "data": {"text": question}}],
            "actions": [
                {"id": "confirm", "label": "Confirm", "style": "primary"},
                {"id": "cancel", "label": "Cancel", "style": "secondary"},
            ],
        }
