#!/usr/bin/env python3
"""
Simple test client for WebSocket chat endpoint.
This script tests the send/receive functionality between frontend and backend.
"""

import asyncio
import json
import websockets
import time

async def test_chat():
    """Test sending and receiving messages via WebSocket"""
    uri = "ws://localhost:8000/chat/stream"
    
    try:
        print("🔗 Connecting to WebSocket...")
        async with websockets.connect(uri) as websocket:
            print("✅ Connected successfully!")
            
            # Test 1: Send a user message
            test_message = {
                "type": "user_message",
                "conversation_id": "test-conv-123",
                "event_id": f"evt-{int(time.time())}",
                "sequence": 1,
                "ts": int(time.time() * 1000),
                "payload": {
                    "text": "สวัสดีครับ ช่วยทดสอบการส่งข้อความหน่อย",
                    "user_info": {
                        "user_id": "test-user",
                        "name": "Test User"
                    }
                }
            }
            
            print("📤 Sending message:", test_message["payload"]["text"])
            await websocket.send(json.dumps(test_message))
            
            # Listen for responses
            print("👂 Listening for responses...")
            response_count = 0
            timeout_seconds = 30
            
            try:
                while response_count < 10:  # Limit responses to avoid infinite loop
                    response = await asyncio.wait_for(
                        websocket.recv(), 
                        timeout=timeout_seconds
                    )
                    
                    try:
                        data = json.loads(response)
                        response_count += 1
                        
                        print(f"📥 Response {response_count}:")
                        print(f"   Type: {data.get('type')}")
                        
                        if data.get("type") == "token":
                            text = data.get("payload", {}).get("text", "")
                            print(f"   Text: {repr(text)}")
                        elif data.get("type") == "status":
                            status = data.get("payload", {}).get("status", "")
                            print(f"   Status: {status}")
                        elif data.get("type") == "done":
                            print("   ✅ Conversation completed!")
                            break
                        elif data.get("type") == "error":
                            error_msg = data.get("payload", {}).get("message", "")
                            print(f"   ❌ Error: {error_msg}")
                            break
                        else:
                            print(f"   Data: {data}")
                            
                    except json.JSONDecodeError:
                        print(f"   📥 Raw response: {response}")
                        
            except asyncio.TimeoutError:
                print(f"⏰ Timeout after {timeout_seconds} seconds")
                
            print("🎯 Test completed!")
            
    except ConnectionRefusedError:
        print("❌ Cannot connect to WebSocket. Make sure the backend server is running on localhost:8000")
    except Exception as e:
        print(f"❌ Error: {e}")

async def main():
    print("🚀 Starting WebSocket Chat Test")
    print("Make sure your backend is running with: uvicorn main:app --reload")
    print("-" * 50)
    await test_chat()
    print("-" * 50)
    print("✨ Test finished!")

if __name__ == "__main__":
    asyncio.run(main())