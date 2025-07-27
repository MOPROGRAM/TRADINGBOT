#!/bin/bash

# The bot is started as a background task by the web server (web/main.py).
# This script is for local development only.
# In production, the render.yaml configuration is used.

echo "Starting web server with integrated bot..."
uvicorn web.main:app --host 0.0.0.0 --port 8000
