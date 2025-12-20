#!/bin/bash

echo "🚀 Starting VB Chatbot Backend Server..."
echo "=================================="

# Check if virtual environment exists
if [ ! -d "venv" ]; then
    echo "Creating virtual environment..."
    python3 -m venv venv
fi

# Activate virtual environment
echo "Activating virtual environment..."
source venv/bin/activate

# Install dependencies
echo "Installing dependencies..."
pip install -r requirements.txt

# Start the server
echo "Starting FastAPI server..."
echo "WebSocket endpoint will be available at: ws://localhost:8000/chat/stream"
echo "Press Ctrl+C to stop the server"
echo "=================================="

uvicorn main:app --reload --host 0.0.0.0 --port 8000