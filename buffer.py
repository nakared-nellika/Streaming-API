"""
Redis-backed event buffer for conversation replay.

This buffer stores full event envelopes in Redis and supports
replay by sequence number. Designed to be a drop-in replacement
for the in-memory EventBuffer used by the orchestrator.
"""
import os
import json
from typing import Dict, List
import redis


class EventBuffer:
    def __init__(
        self,
        redis_url: str | None = None,
        ttl_seconds: int = 300,
    ):
        redis_url = redis_url or os.getenv(
            "REDIS_URL", "redis://localhost:6379"
        )

        self.redis = redis.Redis.from_url(
            redis_url,
            decode_responses=True,
        )
        self.ttl = ttl_seconds

    def _key(self, conversation_id: str) -> str:
        return f"conv:{conversation_id}"

    def append(self, conversation_id: str, sequence: int, event: Dict) -> None:
        """
        Append an event to the conversation buffer.

        Events are stored as JSON strings in a Redis list.
        TTL is refreshed on every append.
        """
        key = self._key(conversation_id)

        # Store full event envelope
        self.redis.rpush(key, json.dumps(event))

        # Refresh TTL so active conversations stay alive
        self.redis.expire(key, self.ttl)

    def replay(self, conversation_id: str, last_sequence: int) -> List[Dict]:
        """
        Replay buffered events with sequence > last_sequence.
        Used by the 'resume' client event.
        """
        key = self._key(conversation_id)

        raw_events = self.redis.lrange(key, 0, -1)
        if not raw_events:
            return []

        events: List[Dict] = []
        for raw in raw_events:
            ev = json.loads(raw)
            if ev.get("sequence", 0) > last_sequence:
                events.append(ev)

        return events
    
    def cleanup(self) -> None:
        """
        No-op cleanup for Redis buffer.

        Redis uses TTL to expire keys automatically,
        so no periodic cleanup is required.
        """
        return

