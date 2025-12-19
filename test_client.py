import asyncio
import json
import time
import websockets

from websockets.exceptions import ConnectionClosed

WS_URI = "ws://127.0.0.1:9000/chat/stream"
CONVERSATION_ID = "demo-1"

USER_TEXT = "Hello, I see unusual charges on my card"
ACTION_ID = "confirm"  # เปลี่ยนเป็น "cancel" เพื่อทดสอบอีกปุ่ม

# ป้องกัน loop ค้าง ถ้า server ยังไม่ส่ง done
MAX_WAIT_SECONDS = 20


def now_ms() -> int:
    return int(time.time() * 1000)


async def test():
    async with websockets.connect(WS_URI) as ws:
        # 1) ส่ง user_message
        user_event = {
            "type": "user_message",
            "conversation_id": CONVERSATION_ID,
            "event_id": f"evt-user-{now_ms()}",
            "sequence": 1,
            "ts": now_ms(),
            "payload": {"text": USER_TEXT},
        }
        await ws.send(json.dumps(user_event))
        print("➡ sent user_message")

        action_sent = False
        start = time.time()

        # 2) ฟัง stream
        while True:
            # timeout กันค้าง
            if time.time() - start > MAX_WAIT_SECONDS:
                print(f"⏳ timeout after {MAX_WAIT_SECONDS}s (no done).")
                break

            msg = await ws.recv()
            print("⬅", msg)

            try:
                data = json.loads(msg)
            except json.JSONDecodeError:
                continue
            
            # 3) ถ้า server รอ action → ส่ง action กลับ (ครั้งเดียว)
            if (
                not action_sent
                and data.get("type") == "status"
                and data.get("payload", {}).get("status") == "waiting_action"
            ):
                action_event = {
                    "type": "action",
                    "conversation_id": CONVERSATION_ID,
                    "event_id": f"evt-action-{now_ms()}",
                    # sequence ฝั่ง client: ถ้า backend ไม่ require ก็ใส่เลขอะไรก็ได้
                    # แต่ใส่ให้มีไว้เพื่อสอดคล้อง schema
                    "sequence": 2,
                    "ts": now_ms(),
                    "payload": {"action_id": ACTION_ID, "args": {}},
                }
                await ws.send(json.dumps(action_event))
                action_sent = True
                print(f"➡ sent action: {ACTION_ID}")

            # 4) จบเมื่อได้ done
            if data.get("type") == "done":
                print("done received")
                break


if __name__ == "__main__":
    asyncio.run(test())
