import os
import sys
import asyncio
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pathlib import Path

# Add project root to the Python path
sys.path.append(str(Path(__file__).parent.parent))

from exchange import get_exchange, get_current_price, get_account_balance
from state import load_state, load_trade_history
from logger import get_logger
from bot import run_bot_tick, POLL_SECONDS

logger = get_logger(__name__)
app = FastAPI()

async def run_bot_in_background():
    """
    A simple asyncio background task to run the bot tick periodically.
    """
    while True:
        try:
            logger.info("Running bot tick from background task...")
            run_bot_tick()
        except Exception as e:
            logger.error(f"An error occurred in the bot background task: {e}", exc_info=True)
        await asyncio.sleep(POLL_SECONDS)

@app.on_event("startup")
async def startup_event():
    logger.info("Starting bot as a background task...")
    asyncio.create_task(run_bot_in_background())

# Mount static files
app.mount("/static", StaticFiles(directory="web/static"), name="static")

# Setup templates
templates = Jinja2Templates(directory="web/templates")

# Load symbol from environment
SYMBOL = os.getenv('SYMBOL', 'XLM/USDT')

@app.get("/", response_class=HTMLResponse)
async def read_root(request: Request):
    return templates.TemplateResponse("index.html", {"request": request, "symbol": SYMBOL})

# Make the status endpoint synchronous
@app.get("/api/status_sync")
def get_status_sync():
    return get_status()

@app.get("/api/status")
def get_status():
    try:
        logger.info("API: /api/status called")
        exchange = get_exchange()
        
        logger.info("API: Fetching current price...")
        current_price = get_current_price(exchange, SYMBOL)
        
        logger.info("API: Fetching account balance...")
        balance = get_account_balance(exchange)
        
        logger.info("API: Loading state...")
        state = load_state()
        
        logger.info("API: Loading trade history...")
        history = load_trade_history()

        pnl = 0
        if state.get('has_position') and state.get('position', {}).get('entry_price'):
            entry_price = state['position']['entry_price']
            if entry_price and current_price:
                pnl = ((current_price - entry_price) / entry_price) * 100
        
        total_pnl = sum(trade.get('pnl_percent', 0) for trade in history)

        return {
            "symbol": SYMBOL,
            "current_price": current_price,
            "balance": balance,
            "position": state.get('position', {}),
            "has_position": state.get('has_position', False),
            "pnl": pnl,
            "trade_history": history,
            "total_pnl": total_pnl
        }
    except Exception as e:
        logger.error(f"Error in /api/status: {e}", exc_info=True)
        return {"error": str(e)}

if __name__ == "__main__":
    import uvicorn
    # This part is for local development, the background task will be started by the startup event
    uvicorn.run(app, host="0.0.0.0", port=8000)
