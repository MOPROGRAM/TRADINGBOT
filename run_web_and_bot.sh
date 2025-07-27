#!/bin/bash

# Start the bot in the background
echo "Starting trading bot in the background..."
python bot.py &

# Start the web server in the foreground
echo "Starting web server..."
uvicorn web.main:app --host 0.0.0.0 --port $PORT
