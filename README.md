# FastAPI WebSocket Streaming Chat API

This project implements a **WebSocket-based streaming chat backend**
designed to support **token streaming, interactive UI cards, user actions,
and reconnect/resume** using a unified event protocol.

The system is designed to be **LLM-agnostic** and **production-ready**,
with Redis-backed buffering for reliable resume after disconnects.

---

## Features

- WebSocket endpoint at `/chat/stream`
- Unified JSON event envelope for all client/server messages
- Orchestrator-driven **conversation state machine**
- **Redis-backed event buffer** (5-minute TTL) for reconnect/resume
- Token streaming (simulated, Gemini hooks ready)
- Interactive cards with user actions
- Resume support via `last_sequence`
- No authentication (per requirements)

---

## Architecture Overview

