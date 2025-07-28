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

from exchange import get_exchange, get_current_price, get_account_balance, fetch_candles
from signals import check_buy_signal, check_sell_signal
from state import load_state, load_trade_history
from logger import get_logger, LIVE_LOG_FILE
from bot import run_bot_tick, POLL_SECONDS, TIMEFRAME
from shared_state import status_messages

logger = get_logger(__name__)
app = FastAPI()
exchange = get_exchange()

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

@app.get("/api/logs")
def get_live_logs():
    try:
        if not os.path.exists(LIVE_LOG_FILE):
            return {"logs": ["Log file not created yet."]}
        
        with open(LIVE_LOG_FILE, 'r') as f:
            # Read last N lines for efficiency
            lines = f.readlines()
            last_lines = lines[-50:] # Get last 50 lines
            return {"logs": last_lines[::-1]} # Reverse to show newest first
    except Exception as e:
        logger.error(f"Error reading live log file: {e}")
        return {"logs": [f"Error reading logs: {e}"]}

# Make the status endpoint synchronous
@app.get("/api/status_sync")
def get_status_sync():
    return get_status()

@app.get("/api/status")
def get_status():
    logger.info("API: /api/status called")
    
    # --- Fetch data with individual error handling for robustness ---
    current_price, balance, state, history, candles, signal = None, {}, {}, [], [], "Waiting"

    try:
        logger.info("API: Fetching current price...")
        current_price = get_current_price(exchange, SYMBOL)
    except Exception as e:
        logger.error(f"API: Failed to get current price: {e}", exc_info=True)

    try:
        logger.info("API: Fetching account balance...")
        balance = get_account_balance(exchange)
    except Exception as e:
        logger.error(f"API: Failed to get account balance: {e}", exc_info=True)

    try:
        logger.info("API: Loading state...")
        state = load_state()
    except Exception as e:
        logger.error(f"API: Failed to load state: {e}", exc_info=True)

    try:
        logger.info("API: Loading trade history...")
        history = load_trade_history()
    except Exception as e:
        logger.error(f"API: Failed to load trade history: {e}", exc_info=True)
        
    try:
        logger.info("API: Fetching candles...")
        candles = fetch_candles(exchange, SYMBOL, TIMEFRAME)
        if state.get('has_position'):
            signal = "Waiting"
        elif check_buy_signal(candles):
            signal = "Buy"
        elif check_sell_signal(candles):
            signal = "Sell"
    except Exception as e:
        logger.error(f"API: Failed to fetch candles or determine signal: {e}", exc_info=True)
    # --- End of robust data fetching ---

    try:
        pnl = 0
        if state.get('has_position') and state.get('position', {}).get('entry_price'):
            entry_price = state['position']['entry_price']
            if entry_price and current_price:
                pnl = ((current_price - entry_price) / entry_price) * 100
        
        # Process trade history
        processed_history = []
        
        # Add the current open position to the top of the history list
        if state.get('has_position'):
            open_position = state.get('position', {}).copy()
            open_position['is_open'] = True
            open_position['pnl_percent'] = pnl
            open_position['exit_price'] = None # No exit price for open trades
            open_position['reason'] = 'Open'
            processed_history.append(open_position)

        # Add closed trades from history
        for trade in history:
            trade['is_open'] = False
            processed_history.append(trade)

        # Sort by timestamp descending to show newest first
        processed_history.sort(key=lambda x: x.get('timestamp', 0), reverse=True)

        total_pnl = sum(trade.get('pnl_percent', 0) for trade in history) # Only sum closed trades

        # --- Calculate Total Portfolio Value in USDT ---
        total_portfolio_usdt = 0
        base_currency, quote_currency = SYMBOL.split('/')
        
        quote_balance = balance.get(quote_currency, {}).get('free', 0)
        base_balance = balance.get(base_currency, {}).get('free', 0)
        
        total_portfolio_usdt += quote_balance
        if current_price and base_balance > 0:
            total_portfolio_usdt += base_balance * current_price
        # --- End Calculation ---

        return {
            "symbol": SYMBOL,
            "current_price": current_price,
            "balance": balance,
            "position": state.get('position', {}),
            "has_position": state.get('has_position', False),
            "pnl": pnl,
            "trade_history": processed_history,
            "total_pnl": total_pnl,
            "total_portfolio_usdt": total_portfolio_usdt, # Add new value here
            "candles": candles,
            "signal": signal,
            "status_messages": status_messages
        }
    except Exception as e:
        logger.error(f"API: Error during final data assembly: {e}", exc_info=True)
        # Return a valid structure even on final error to prevent 502
        return {
            "symbol": SYMBOL, "current_price": None, "balance": {}, 
            "position": {}, "has_position": False, "pnl": 0, 
            "trade_history": [], "total_pnl": 0, "error": str(e),
            "candles": [], "signal": "Error",
            "status_messages": status_messages
        }

if __name__ == "__main__":
    import uvicorn
    # This part is for local development, the background task will be started by the startup event
    uvicorn.run(app, host="0.0.0.0", port=8000)
