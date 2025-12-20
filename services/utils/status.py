from datetime import datetime, timezone
from zoneinfo import ZoneInfo
import json, asyncio, aiofiles, os

# Get the directory where this script is located
current_dir = os.path.dirname(os.path.abspath(__file__))
# Navigate to the mock_data directory relative to this script's location
mock_data_dir = os.path.join(current_dir, "..", "mock_data")

async def append_status(user_id: str, status: dict, path=None):
    if path is None:
        path = os.path.join(mock_data_dir, "status_db.ndjson")
    event = {
        "user_id": user_id,
        "ts": datetime.now(ZoneInfo("Asia/Bangkok")).isoformat(),
        **status
    }
    async with aiofiles.open(path, "a", encoding="utf-8") as f:
        await f.write(json.dumps(event, ensure_ascii=False) + "\n")

async def get_status(user_id: str, path=None):
    if path is None:
        path = os.path.join(mock_data_dir, "status_db.ndjson")
    status = {}
    try:
        async with aiofiles.open(path, "r", encoding="utf-8") as f:
            async for line in f:
                event = json.loads(line)
                if event["user_id"] == user_id:
                    status.update({k: v for k, v in event.items() if k not in ["user_id", "ts"]})
    except FileNotFoundError:
        # If file doesn't exist yet, return empty status
        pass
    return status