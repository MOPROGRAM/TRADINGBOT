import os
import sys
import json
import time
import asyncio
import threading
from datetime import datetime, timedelta, timezone
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pathlib import Path

# Add project root to the Python path
sys.path.append(str(Path(__file__).parent.parent))

from exchange import get_exchange, websocket_client
from state import load_state, load_trade_history
from logger import get_logger, LIVE_LOG_FILE
from bot import main_loop, POLL_SECONDS
from shared_state import strategy_params
from signals import check_buy_signal, check_sell_signal
import pandas as pd

logger = get_logger(__name__)
app = FastAPI()
exchange = get_exchange()

# --- Caching Mechanism ---
API_CACHE = None
LAST_API_CALL_TIME = 0
CACHE_DURATION_SECONDS = 1 # Cache for 1 second to reduce load but keep it fresh

def run_bot_in_background():
    """
    Runs the bot's async main_loop in a separate thread.
    """
    logger.info("Starting bot's async main loop in a background thread.")
    # Create a new event loop for the new thread
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    # Run the async main_loop until it completes (which it won't, as it's a while True loop)
    loop.run_until_complete(main_loop())
    loop.close()

@app.on_event("startup")
def startup_event():
    logger.info("Starting bot in a background task...")
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
            lines = f.readlines()
            last_lines = lines[-100:] # Get last 100 lines
            return {"logs": last_lines[::-1]}
    except Exception as e:
        logger.error(f"Error reading live log file: {e}")
        return {"logs": [f"Error reading logs: {e}"]}

@app.get("/api/status")
def get_status():
    global API_CACHE, LAST_API_CALL_TIME
    
    current_time = time.time()
    if API_CACHE and (current_time - LAST_API_CALL_TIME < CACHE_DURATION_SECONDS):
        return API_CACHE

    bot_status = {}
    try:
        with open('web_status.json', 'r') as f:
            bot_status = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError) as e:
        logger.warning(f"Could not read web_status.json: {e}. Using empty status.")

    state = bot_status.get("state", {})
    history = load_trade_history() # History is still loaded from its own file
    
    try:
        seven_days_ago = datetime.now(timezone.utc) - timedelta(days=7)
        
        def parse_timestamp(ts_str):
            if not ts_str: return None
            if ts_str.endswith('Z'): ts_str = ts_str[:-1] + '+00:00'
            try: return datetime.fromisoformat(ts_str)
            except (ValueError, TypeError): return None

        recent_history = [t for t in history if (ts := parse_timestamp(t.get('timestamp'))) and ts > seven_days_ago]

        current_price = bot_status.get("current_price")
        entry_price = state.get('position', {}).get('entry_price')
        pnl = 0
        if state.get('has_position') and isinstance(entry_price, (int, float)) and isinstance(current_price, (int, float)):
            pnl = ((current_price - entry_price) / entry_price) * 100
        
        processed_history = []
        if state.get('has_position'):
            open_position = state.get('position', {}).copy()
            open_position['is_open'] = True
            open_position['pnl_percent'] = pnl
            open_position['exit_price'] = None
            open_position['reason'] = 'Open'
            processed_history.append(open_position)

        for trade in recent_history:
            trade['is_open'] = False
            # Add side and pnl to each trade
            if 'buy' in (trade.get('reason', '').lower()):
                trade['side'] = 'Buy'
            elif 'sell' in (trade.get('reason', '').lower()):
                trade['side'] = 'Sell'
            else:
                trade['side'] = 'N/A'
            
            entry = trade.get('entry_price')
            exit_p = trade.get('exit_price')
            size = trade.get('size')
            if entry and exit_p and size:
                trade['pnl'] = (exit_p - entry) * size
            else:
                trade['pnl'] = 0

            processed_history.append(trade)

        processed_history.sort(key=lambda x: parse_timestamp(x.get('timestamp')) or datetime.min.replace(tzinfo=timezone.utc), reverse=True)

        total_pnl = sum(trade.get('pnl_percent', 0) for trade in history)
        
        balance = bot_status.get("balance", {})
        total_balance_usdt = 0.0
        if balance:
            # This part for total balance calculation can be simplified if the bot provides it
            # For now, keeping the logic but it might be removed if bot handles it.
            usdt_val = balance.get('USDT', 0)
            base_val = balance.get(SYMBOL.split('/')[0], 0)
            if current_price:
                total_balance_usdt = usdt_val + (base_val * current_price)
            else:
                total_balance_usdt = usdt_val

        filtered_balance = {k: v for k, v in balance.items() if v > 0.00000001}

        fresh_data = {
            "symbol": SYMBOL,
            "current_price": current_price,
            "balance": filtered_balance,
            "total_balance_usdt": total_balance_usdt,
            "position": state.get('position', {}),
            "has_position": state.get('has_position', False),
            "pnl": pnl,
            "trade_history": processed_history,
            "total_pnl": total_pnl,
            "signal": bot_status.get("signal", "Initializing"),
            "signal_reason": bot_status.get("signal_reason", "Waiting for bot..."),
            "analysis_details": str(bot_status.get("analysis_details", "Waiting...")),
            "strategy_params": strategy_params,
            "live_candles": bot_status.get("live_candles", []),
            "last_modified": state.get('last_modified'),
            "connection_status": bot_status.get("connection_status", {})
        }
        API_CACHE = fresh_data
        LAST_API_CALL_TIME = time.time()
        return fresh_data
        
    except Exception as e:
        logger.error(f"API Error: {e}", exc_info=True)
        return {
            "symbol": SYMBOL, "current_price": None, "balance": {}, 
            "position": {}, "has_position": False, "pnl": 0, 
            "trade_history": [], "total_pnl": 0, "error": str(e),
            "signal": "API Error", "signal_reason": "Failed to assemble data", 
            "strategy_params": {}, "live_candles": [],
            "last_modified": None, "total_balance_usdt": 0.0,
            "connection_status": {}
        }

@app.get("/api/backtest")
async def backtest(request: Request):
    logger.info("Starting historical signal analysis (backtest)...")
    try:
        # 1. Fetch a larger dataset for backtesting
        limit = 1000 # Number of candles to backtest on
        logger.info(f"Fetching {limit} candles for primary, 15m, and 1h timeframes...")
        
        # Use asyncio.gather to fetch all candles concurrently
        primary_candles_raw, fifteen_min_candles_raw, trend_candles_raw = await asyncio.gather(
            asyncio.to_thread(exchange.fetch_ohlcv, SYMBOL, '5m', limit=limit),
            asyncio.to_thread(exchange.fetch_ohlcv, SYMBOL, '15m', limit=limit),
            asyncio.to_thread(exchange.fetch_ohlcv, SYMBOL, '1h', limit=limit)
        )

        # Convert to DataFrame for easier manipulation and alignment
        df_primary = pd.DataFrame(primary_candles_raw, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        df_15m = pd.DataFrame(fifteen_min_candles_raw, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        df_trend = pd.DataFrame(trend_candles_raw, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])

        # Convert timestamp to datetime and set as index
        for df in [df_primary, df_15m, df_trend]:
            df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
            df.set_index('timestamp', inplace=True)

        # 2. Initialize backtest state
        trades = []
        in_position = False
        entry_price = 0
        entry_timestamp = None
        min_candles_for_signal = 100 # Minimum number of candles required to generate a signal

        # 3. Iterate through the primary timeframe candles
        logger.info(f"Iterating through {len(df_primary)} primary candles to find signals...")
        for i in range(min_candles_for_signal, len(df_primary)):
            current_timestamp = df_primary.index[i]
            current_price = df_primary['close'].iloc[i]

            # Get historical data slices for signal functions
            # The signal functions expect lists of lists, with an 'is_closed' flag
            # We assume all historical candles are closed (True)
            primary_slice = [row.tolist() + [True] for index, row in df_primary.iloc[:i].iterrows()]
            
            # Align other timeframes to the current primary candle's timestamp
            fifteen_min_slice = [row.tolist() + [True] for index, row in df_15m[df_15m.index <= current_timestamp].iterrows()]
            trend_slice = [row.tolist() + [True] for index, row in df_trend[df_trend.index <= current_timestamp].iterrows()]

            if not in_position:
                # Check for a buy signal
                buy_signal, _ = check_buy_signal(primary_slice, fifteen_min_slice, trend_slice)
                if buy_signal:
                    in_position = True
                    entry_price = current_price
                    entry_timestamp = current_timestamp
                    logger.info(f"Backtest: Buy signal triggered at {entry_timestamp} - Price: {entry_price}")
            else:
                # Check for a sell signal
                sell_signal, _ = check_sell_signal(primary_slice)
                if sell_signal:
                    pnl_percent = ((current_price - entry_price) / entry_price) * 100
                    trades.append({
                        "entry_timestamp": entry_timestamp.isoformat(),
                        "entry_price": entry_price,
                        "exit_timestamp": current_timestamp.isoformat(),
                        "exit_price": current_price,
                        "pnl_percent": pnl_percent
                    })
                    logger.info(f"Backtest: Sell signal triggered at {current_timestamp} - Price: {current_price} | PnL: {pnl_percent:.2f}%")
                    in_position = False
                    entry_price = 0
                    entry_timestamp = None
        
        logger.info(f"Backtest finished. Found {len(trades)} trades.")
        return trades

    except Exception as e:
        logger.error(f"Backtest API Error: {e}", exc_info=True)
        return {"error": f"Failed to run backtest: {e}"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
