import os
import sys
import json
import time
import threading
from datetime import datetime, timedelta, timezone
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
from bot import run_bot_tick, POLL_SECONDS
from shared_state import strategy_params

logger = get_logger(__name__)
app = FastAPI()
exchange = get_exchange()

# --- Caching Mechanism (still used for initial load or fallback) ---
API_CACHE = None
LAST_API_CALL_TIME = 0
CACHE_DURATION_SECONDS = 10 # Cache the response for 10 seconds

def run_bot_in_background():
    """
    A simple threading background task to run the bot tick periodically.
    This runs in a separate thread to avoid blocking the FastAPI event loop.
    """
    # Add a more significant delay to ensure the web server starts up and becomes healthy
    # before the bot's first run. This is critical for platforms like Render.
    time.sleep(20) # Initial delay for server startup
    
    while True:
        try:
            logger.info("Running bot tick from background thread...")
            run_bot_tick()
            
            # After running the bot tick, fetch the latest status and broadcast it
            # This needs to be awaited, so the background task must be async
            # No manager.broadcast as websockets are removed
            
        except Exception as e:
            logger.error(f"An error occurred in the bot background thread: {e}", exc_info=True)
        time.sleep(POLL_SECONDS) # Use time.sleep for synchronous functions

@app.on_event("startup")
def startup_event():
    logger.info("Starting bot in a background task...")
    # Use threading.Thread for synchronous background tasks in FastAPI
    thread = threading.Thread(target=run_bot_in_background, daemon=True)
    thread.start()

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
@app.get("/api/status")
def get_status():
    global API_CACHE, LAST_API_CALL_TIME
    
    # Check if a valid cache is available
    current_time = time.time()
    if API_CACHE and (current_time - LAST_API_CALL_TIME < CACHE_DURATION_SECONDS):
        logger.info("API: /api/status called, returning cached response.")
        return API_CACHE

    logger.info("API: /api/status called, fetching fresh data.")
    
    # --- Read bot status from the dedicated JSON file ---
    bot_status = {}
    try:
        with open('web_status.json', 'r') as f:
            bot_status = json.load(f)
    except FileNotFoundError:
        logger.warning("web_status.json not found. Bot might be initializing.")
    except json.JSONDecodeError:
        logger.error("Failed to decode web_status.json.")

    # --- Fetch data with individual error handling for robustness ---
    current_price, balance, state, history = None, {}, {}, []

    # live_candles is now imported directly from shared_state, so no file reading is needed.

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
        
    # --- End of robust data fetching ---

    try:
        # --- Filter trade history for the last 7 days ---
        seven_days_ago = datetime.now(timezone.utc) - timedelta(days=7)
        
        # Ensure timestamps are comparable (handle ISO 8601 strings)
        def parse_timestamp(ts_str):
            if not ts_str:
                return None
            # Handle Z suffix for UTC
            if ts_str.endswith('Z'):
                ts_str = ts_str[:-1] + '+00:00'
            try:
                return datetime.fromisoformat(ts_str)
            except (ValueError, TypeError):
                return None # Or handle other formats if necessary

        recent_history = [
            t for t in history 
            if (ts := parse_timestamp(t.get('timestamp'))) and ts > seven_days_ago
        ]
        # --- End of filtering ---

        pnl = 0
        entry_price = state.get('position', {}).get('entry_price')
        # --- Final PnL Validation ---
        # Ensure both entry_price and current_price are valid numbers before calculation
        if state.get('has_position') and isinstance(entry_price, (int, float)) and isinstance(current_price, (int, float)):
            pnl = ((current_price - entry_price) / entry_price) * 100
        elif state.get('has_position'):
            # If we have a position but can't calculate PnL, log it.
            logger.warning(f"Could not calculate PnL. entry_price: {entry_price}, current_price: {current_price}")
        
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

        # Add closed trades from the RECENT history
        for trade in recent_history:
            trade['is_open'] = False
            processed_history.append(trade)

        # Sort by timestamp descending to show newest first
        processed_history.sort(key=lambda x: x.get('timestamp', 0), reverse=True)

        # Total PnL is calculated on the FULL history for accuracy
        total_pnl = sum(trade.get('pnl_percent', 0) for trade in history)

        # --- Calculate Total Balance in USDT ---
        total_balance_usdt = 0.0
        if balance:
            for currency, data in balance.items():
                if isinstance(data, dict):
                    free_amount = data.get('free', 0.0)
                else:
                    free_amount = data

                if free_amount > 0:
                    if currency == 'USDT':
                        total_balance_usdt += free_amount
                    else:
                        # Try to get price for conversion
                        try:
                            pair = f"{currency}/USDT"
                            price_ticker = exchange.fetch_ticker(pair)
                            price_in_usdt = price_ticker['last']
                            total_balance_usdt += free_amount * price_in_usdt
                        except Exception as e:
                            logger.warning(f"Could not fetch price for {pair} to calculate total USDT balance: {e}")
                            # If price cannot be fetched, just add the amount as is (might be inaccurate)
                            # Or, for safety, skip this currency from total_balance_usdt if conversion fails
                            pass # Skipping for now to avoid inflating total with unconvertible assets

        # --- Filter balance to show only non-zero balances ---
        filtered_balance = {}
        for currency, data in balance.items():
            amount = 0.0
            if isinstance(data, dict):
                amount = data.get('free', 0.0) # Prefer 'free' balance
            else:
                amount = data # If it's just a number

            # Only include if amount is greater than a very small epsilon
            if amount > 0.00000001: # Use a small threshold to filter out dust
                filtered_balance[currency] = amount # Store just the amount for simplicity in UI

        # --- Get AI Model Info ---
        # --- Update Cache ---
        fresh_data = {
            "symbol": SYMBOL,
            "current_price": current_price,
            "balance": filtered_balance, # Use the filtered balance
            "total_balance_usdt": total_balance_usdt, # Add total balance in USDT
            "position": state.get('position', {}),
            "has_position": state.get('has_position', False),
            "pnl": pnl,
            "trade_history": processed_history,
            "total_pnl": total_pnl,
            "signal": bot_status.get("signal", "Initializing"),
            "signal_reason": bot_status.get("signal_reason", "Waiting for bot to start..."),
            "analysis_details": bot_status.get("analysis_details", "Waiting for data..."), # Add this line
            "strategy_params": strategy_params,
            "live_candles": bot_status.get("live_candles", []),
            "status_messages": [], # Status messages are now handled by the bot's log/state
            "last_modified": state.get('last_modified'),
            "ai_model_last_trained": "AI Model Removed", # Indicate AI model is removed
            "last_buy_signal_time": bot_status.get("last_buy_signal_time"), # Add last buy signal time
            "last_sell_signal_time": bot_status.get("last_sell_signal_time") # Add last sell signal time
        }
        API_CACHE = fresh_data
        LAST_API_CALL_TIME = time.time()
        return fresh_data
        
    except Exception as e:
        logger.error(f"API: Error during final data assembly: {e}", exc_info=True)
        # Return a valid structure even on final error to prevent 502
        return {
            "symbol": SYMBOL, "current_price": None, "balance": {}, 
            "position": {}, "has_position": False, "pnl": 0, 
            "trade_history": [], "total_pnl": 0, "error": str(e),
            "signal": "API Error", "signal_reason": "Failed to assemble data", "strategy_params": {}, "live_candles": [],
            "status_messages": [],
            "last_modified": None,
            "total_balance_usdt": 0.0, # Ensure this is always present
            "last_buy_signal_time": None, # Ensure this is always present
            "last_sell_signal_time": None, # Ensure this is always present
            "ai_model_last_trained": "AI Model Removed" # Ensure this is always present
        }

if __name__ == "__main__":
    import uvicorn
    # This part is for local development, the background task will be started by the startup event
    uvicorn.run(app, host="0.0.0.0", port=8000)
