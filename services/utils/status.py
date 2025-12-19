from datetime import datetime, timezone
from zoneinfo import ZoneInfo
import json, asyncio, aiofiles
async def append_status(user_id: str, status: dict, path="mock_data/status_db.ndjson"):
    event = {
        "user_id": user_id,
        "ts": datetime.now(ZoneInfo("Asia/Bangkok")).isoformat(),
        **status
    }
    async with aiofiles.open(path, "a", encoding="utf-8") as f:
        await f.write(json.dumps(event, ensure_ascii=False) + "\n")
async def get_status(user_id: str, path="mock_data/status_db.ndjson"):
    status = {}
    async with aiofiles.open(path, "r", encoding="utf-8") as f:
        async for line in f:
            event = json.loads(line)
            if event["user_id"] == user_id:
                status.update({k: v for k, v in event.items() if k not in ["user_id", "ts"]})
    return status