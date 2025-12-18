"""Event builder utilities and constants.

Provides helpers to build the unified envelope with server-side event_id, sequence, and timestamp.
"""
import time
import uuid
from typing import Dict, Any

def now_ts_ms() -> int:
    return int(time.time() * 1000)


def make_event(event_type: str, conversation_id: str, sequence: int, payload: Dict[str, Any]) -> Dict[str, Any]:
    """Constructs a unified envelope event for sending to clients.

    Server generates `event_id` (UUID) and `ts` (ms since epoch). The caller is responsible
    for incrementing the conversation sequence and passing it in.
    """
    return {
        "type": event_type,
        "conversation_id": conversation_id,
        "event_id": str(uuid.uuid4()),
        "sequence": sequence,
        "ts": now_ts_ms(),
        "payload": payload,
    }
