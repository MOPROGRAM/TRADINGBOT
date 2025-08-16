# ai_bot_dashboard/main.py

import os
import sys
import json
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pathlib import Path

# Add project root to the Python path
sys.path.append(str(Path(__file__).parent.parent))

from state import load_trade_history

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
    # This is a placeholder. In a real application, this would fetch live data from the bot.
    # For now, we'll return some mock data.
    
    mock_data = {
        "symbol": SYMBOL,
        "current_price": 0.11,
        "balance": {"USDT": 1000, "XLM": 5000},
        "total_balance_usdt": 1550.0,
        "position": {},
        "has_position": False,
        "pnl": 0,
        "trade_history": load_trade_history(), # You might want to create a separate history for the AI bot
        "total_pnl": 0,
        "signal": "Buy",
        "signal_reason": "AI Model Prediction",
        "analysis_details": "EMA crossover ✅ | RSI bullish ✅",
        "strategy_params": {},
        "live_candles": [],
        "last_modified": "2025-08-16T10:30:00Z",
        "connection_status": {"binance": "connected"}
    }
    return mock_data

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8001)
