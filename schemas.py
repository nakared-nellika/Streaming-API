"""Pydantic schemas for the unified event envelope and payloads.

All messages use the same envelope structure.
"""
from pydantic import BaseModel, Field
from typing import Any, Dict, Optional


class Envelope(BaseModel):
    type: str
    conversation_id: str
    event_id: Optional[str] = None
    sequence: Optional[int] = None
    ts: Optional[int] = None
    payload: Dict[str, Any] = Field(default_factory=dict)


class ResumePayload(BaseModel):
    last_sequence: int


class UserMessagePayload(BaseModel):
    text: str


class ActionPayload(BaseModel):
    action_id: str
    params: Optional[Dict[str, Any]] = None


class CardSection(BaseModel):
    kind: str
    data: Dict[str, Any]


class CardAction(BaseModel):
    id: str
    label: str
    style: str


class CardPayload(BaseModel):
    title: str
    badge: Optional[str]
    sections: list[CardSection]
    actions: list[CardAction]
