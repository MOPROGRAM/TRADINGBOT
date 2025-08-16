# run_all.py - Single entry point for Render's free tier

import threading
import uvicorn
from ai_bot_dashboard.main import app as fastapi_app
from main import main_loop
import asyncio
import os

def run_dashboard():
    """Runs the FastAPI dashboard."""
    # Render provides the PORT environment variable.
    port = int(os.environ.get("PORT", 10000))
    uvicorn.run(fastapi_app, host="0.0.0.0", port=port)

def run_bot():
    """Runs the trading bot."""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(main_loop())
    loop.close()

if __name__ == "__main__":
    print("--- Starting Dashboard in a background thread ---")
    dashboard_thread = threading.Thread(target=run_dashboard, daemon=True)
    dashboard_thread.start()
    
    print("--- Starting Trading Bot in the main thread ---")
    # Give the dashboard a moment to start up
    import time
    time.sleep(5)
    run_bot()
