import asyncio
import json
import time
import websockets

WS_URI = "ws://127.0.0.1:8000/chat/stream"
CONVERSATION_ID = "demo-user-222xxx"

# ใส่ sequence ล่าสุดที่ "client เคยได้รับแล้ว" เพื่อให้ server replay ต่อจาก last_sequence + 1
# แนะนำ: ลองใส่ 0 เพื่อให้ replay ทั้งหมด (ถ้ามีใน buffer)
LAST_SEQUENCE = 0

MAX_WAIT_SECONDS = 15


def now_ms() -> int:
    return int(time.time() * 1000)


async def main():
    async with websockets.connect(WS_URI) as ws:
        resume_event = {
            "type": "resume",
            "conversation_id": CONVERSATION_ID,
            "event_id": f"evt-resume-{now_ms()}",
            "sequence": 1,  # ฝั่ง client ใส่ไว้เฉย ๆ ให้ตรง schema
            "ts": now_ms(),
            "payload": {"last_sequence": LAST_SEQUENCE},
        }

        await ws.send(json.dumps(resume_event))
        print(f"➡ sent resume for conversation_id={CONVERSATION_ID}, last_sequence={LAST_SEQUENCE}")

        start = time.time()
        expected_next_seq = LAST_SEQUENCE + 1

        while True:
            if time.time() - start > MAX_WAIT_SECONDS:
                print(f"⏳ timeout after {MAX_WAIT_SECONDS}s (no done).")
                break

            msg = await ws.recv()
            print("⬅", msg)

            try:
                evt = json.loads(msg)
            except json.JSONDecodeError:
                continue

            # ตรวจสอบ ordering ของ sequence (ช่วยให้มั่นใจว่า replay เรียงถูก)
            seq = evt.get("sequence")
            if isinstance(seq, int):
                if seq < expected_next_seq:
                    print(f"⚠ out-of-order or duplicate sequence: got {seq}, expected >= {expected_next_seq}")
                elif seq > expected_next_seq:
                    print(f"⚠ gap detected: got {seq}, expected {expected_next_seq}")
                    expected_next_seq = seq + 1
                else:
                    expected_next_seq += 1

            # จบเมื่อได้ done
            if evt.get("type") == "done":
                print("✅ done received (replay complete)")
                break


if __name__ == "__main__":
    asyncio.run(main())
