"""Orchestrator layer: manages conversation state machine and drives event emission.

This module contains the `Orchestrator` class which receives client events and
emits server events following the required state machine.

Integration uses VBChatbot (LangGraph) which yields streamed chunks and interrupt tuples.
We buffer small chunks into larger text tokens for UI friendliness.
"""

# orchestrator.py (บนสุด)
import sys
sys.path.append("D:/VB-BACKEND/VB-BACKEND")

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

        # Keep chatbot per conversation to preserve runtime context if needed
        self.vb: Optional[VBChatbot] = None


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

    async def handle_incoming(self, websocket, envelope: Dict[str, Any]):
        t = envelope.get("type")
        conv_id = envelope.get("conversation_id")
        if not t or not conv_id:
            await websocket.send_json({"type": "error", "payload": {"message": "missing type or conversation_id"}})
            return

        conv = self._ensure_conv(conv_id)

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
            await websocket.send_json(ev)
            if eid:
                conv.sent_event_ids.add(eid)

    async def _handle_user_message(self, websocket, conv: Conversation, envelope: Dict[str, Any]):
        payload = envelope.get("payload", {})
        text = payload.get("text", "")

        conv.state = State.Analyzing
        await self._emit(websocket, conv, "status", {"status": "analyzing"})

        # cancel previous task
        if conv.current_task and not conv.current_task.done():
            conv.current_task.cancel()

        # create chatbot instance for this conversation (kept for resume)
        conv.vb = VBChatbot()

        conv.state = State.Generating
        conv.current_task = asyncio.create_task(
            self._run_vb_stream(
                websocket=websocket,
                conv=conv,
                message=text,
                resume=False,
                action_id=None,
            )
        )

    async def _handle_action(self, websocket, conv: Conversation, envelope: Dict[str, Any]):
        if conv.state != State.WaitingAction:
            await self._emit(websocket, conv, "error", {"message": "no action expected in current state"})
            return

        payload = envelope.get("payload", {})
        action_id = payload.get("id") or payload.get("action") or payload.get("action_id") or ""
        action_id = str(action_id)

        conv.state = State.ProcessingAction
        await self._emit(websocket, conv, "status", {"status": "processing_action"})

        # cancel any running task
        if conv.current_task and not conv.current_task.done():
            conv.current_task.cancel()

        # resume with action_id
        conv.state = State.Generating
        conv.current_task = asyncio.create_task(
            self._run_vb_stream(
                websocket=websocket,
                conv=conv,
                message=action_id,
                resume=True,
                action_id=action_id,
            )
        )

    async def _handle_stop(self, websocket, conv: Conversation, envelope: Dict[str, Any]):
        if conv.current_task and not conv.current_task.done():
            conv.current_task.cancel()
            await asyncio.sleep(0)
        conv.state = State.Completed
        await self._emit(websocket, conv, "done", {"message": "stopped"})

    # VBChatbot integration

    def _should_flush(self, buf: str) -> bool:
        """Flush policy for buffered text -> token event."""
        if not buf:
            return False
        # flush on newline (paragraph boundaries)
        if "\n" in buf:
            return True
        # flush when buffer is large enough
        if len(buf) >= 80:
            return True
        # flush at sentence-ish boundaries if already has some length
        if buf.endswith((" ", ".", "!", "?", "…", "ฯ", "。")) and len(buf) >= 25:
            return True
        return False

    def _normalize_chunk(self, s: str) -> str:
        """Normalize weird chunking like single chars with lots of spaces/newlines."""
        if not s:
            return s
        # preserve newlines, but collapse excessive spaces
        # do not strip fully; we want spacing to look natural
        return s.replace("\r\n", "\n").replace("\r", "\n")

    async def _run_vb_stream(
        self,
        websocket,
        conv: Conversation,
        message: str,
        resume: bool,
        action_id: Optional[str],
    ):
        buffer_text = ""

        try:
            vb = conv.vb or VBChatbot()
            conv.vb = vb

            # In your VBChatbot, it expects: (thread_id, message, resume, user_info)
            async for chunk in vb.run(
                thread_id=conv.id,
                message=message,
                resume=resume,
                user_info={},
            ):
                # stop if state changed away from Generating (e.g., stop)
                if conv.state != State.Generating:
                    break

                # INTERRUPT: ('Interrupt:', 'question...')
                if isinstance(chunk, tuple) and len(chunk) >= 2 and chunk[0] == "Interrupt:":
                    question = str(chunk[1])

                    # flush remaining buffer first
                    if buffer_text.strip():
                        await self._emit(websocket, conv, "token", {"text": buffer_text})
                        buffer_text = ""

                    conv.state = State.CardReady
                    await self._emit(websocket, conv, "card", self._build_confirm_card(question))

                    conv.state = State.WaitingAction
                    await self._emit(websocket, conv, "status", {"status": "waiting_action"})
                    return

                # TEXT CHUNK
                if isinstance(chunk, str) and chunk:
                    chunk = self._normalize_chunk(chunk)
                    buffer_text += chunk

                    if self._should_flush(buffer_text):
                        await self._emit(websocket, conv, "token", {"text": buffer_text})
                        buffer_text = ""
                    continue

                # DICT/OTHER (future proof)
                if isinstance(chunk, dict):
                    # flush buffer before sending structured event
                    if buffer_text.strip():
                        await self._emit(websocket, conv, "token", {"text": buffer_text})
                        buffer_text = ""

                    et = chunk.get("type")
                    pl = chunk.get("payload", chunk)
                    if et in ("status", "card", "token", "done", "error"):
                        await self._emit(websocket, conv, et, pl)
                    else:
                        await self._emit(websocket, conv, "status", {"status": "update", "data": chunk})
                    continue

            # stream ended normally -> flush tail
            if buffer_text.strip():
                await self._emit(websocket, conv, "token", {"text": buffer_text})
                buffer_text = ""

            conv.state = State.Completed
            # Different done message for resume vs first message (optional)
            await self._emit(websocket, conv, "done", {"message": "completed" if not resume else "action_processed"})

        except asyncio.CancelledError:
            conv.state = State.Completed
            await self._emit(websocket, conv, "status", {"status": "stopped"})
        except Exception as e:
            conv.state = State.Error
            await self._emit(websocket, conv, "error", {"message": str(e)})

    # Event emission

    async def _emit(self, websocket, conv: Conversation, event_type: str, payload: Dict[str, Any]):
        async with self._locks[conv.id]:
            conv.sequence += 1
            seq = conv.sequence
            ev = make_event(event_type, conv.id, seq, payload)
            await websocket.send_json(ev)
            self.buffer.append(conv.id, seq, ev)

            ev_id = ev.get("event_id")
            if ev_id:
                conv.sent_event_ids.add(ev_id)

    # UI Card builders

    def _build_confirm_card(self, question: str) -> Dict[str, Any]:
        return {
            "title": "Confirm Action",
            "badge": None,
            "sections": [
                {"kind": "note", "data": {"text": question}},
            ],
            "actions": [
                {"id": "confirm", "label": "Confirm", "style": "primary"},
                {"id": "cancel", "label": "Cancel", "style": "secondary"},
            ],
        }

    def _build_sample_card(self, prompt: str) -> Dict[str, Any]:
        return {
            "title": "Sample Card",
            "badge": None,
            "sections": [
                {"kind": "note", "data": {"text": f"Summary for: {prompt[:80]}"}},
            ],
            "actions": [
                {"id": "confirm", "label": "Confirm", "style": "primary"},
                {"id": "cancel", "label": "Cancel", "style": "secondary"},
            ],
        }
