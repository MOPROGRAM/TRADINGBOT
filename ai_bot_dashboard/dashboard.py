# ai_bot_dashboard/main.py

import os
import sys
import asyncio
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pathlib import Path

# Add project root to the Python path
sys.path.append(str(Path(__file__).parent.parent))

from shared_state import bot_state
from main import main_loop as bot_logic_task
from websocket_manager import binance_websocket_client

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Start background tasks
    print("--- Starting background tasks (Bot and WebSocket) ---")
    bot_task = asyncio.create_task(bot_logic_task())
    websocket_task = asyncio.create_task(binance_websocket_client())
    yield
    # Clean up the tasks (optional, as Render will kill the process anyway)
    bot_task.cancel()
    websocket_task.cancel()

app = FastAPI(lifespan=lifespan)

# Mount static files
app.mount("/static", StaticFiles(directory="ai_bot_dashboard/static"), name="static")

# Setup templates
templates = Jinja2Templates(directory="ai_bot_dashboard/templates")

# Load symbol from environment
SYMBOL = os.getenv('SYMBOL', 'XLM/USDT')

@app.get("/", response_class=HTMLResponse)
async def read_root(request: Request):
    return templates.TemplateResponse("index.html", {"request": request, "symbol": SYMBOL})

@app.get("/api/status")
def get_status():
    """
    Returns the live state of the bot from the shared state object.
    """
    state = bot_state.get_state()
    state['symbol'] = SYMBOL
    # Add other necessary UI fields if they are not in the bot_state
    state['trade_history'] = state.get('trade_history', [])
    state['total_pnl'] = state.get('total_pnl', 0.0)
    state['analysis_details'] = state.get('analysis_details', 'AI Model Prediction')
    state['connection_status'] = {"websocket": "connected"} # Assume connected if dashboard is up
    return JSONResponse(content=state)
