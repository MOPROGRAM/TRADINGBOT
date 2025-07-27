#!/bin/bash

# The bot logic is now integrated into the web server.
# This script now only starts the web server.

echo "Starting web server with integrated bot logic..."
uvicorn web.main:app --host 0.0.0.0 --port ${PORT:-8000}
