# ai_bot_dashboard/main.py

import os
import sys
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pathlib import Path

# Add project root to the Python path
sys.path.append(str(Path(__file__).parent.parent))

from shared_state import bot_state

app = FastAPI()

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

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8001)
