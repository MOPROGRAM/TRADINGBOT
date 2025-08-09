import os
import ccxt.pro as ccxtpro  # Use ccxt.pro for websocket support
import asyncio
import threading
from dotenv import load_dotenv
from logger import get_logger
import time

load_dotenv()
logger = get_logger(__name__)

API_KEY = os.getenv('BINANCE_API_KEY')
API_SECRET = os.getenv('BINANCE_API_SECRET')
DRY_RUN = os.getenv('DRY_RUN', 'True').lower() == 'true'
SYMBOL = os.getenv('SYMBOL', 'XLM/USDT')
TIMEFRAME = os.getenv('TIMEFRAME', '5m')

# --- Global state for live data from WebSocket ---
live_price = {'price': None, 'timestamp': None}
live_candles = []
# A lock to ensure thread-safe access to the global variables
data_lock = threading.Lock()

def get_exchange():
    """Initializes the exchange object."""
    # Use the async-supported exchange class from ccxt.pro
    exchange = ccxtpro.binance({
        'apiKey': API_KEY,
        'secret': API_SECRET,
        'options': {
            'defaultType': 'spot',
        },
    })
    if DRY_RUN:
        exchange.set_sandbox_mode(True)
        logger.info("Exchange is in SANDBOX mode.")
    return exchange

async def watch_trades_and_candles(exchange):
    """The main WebSocket loop to watch trades and candles."""
    global live_price, live_candles
    
    while True:
        try:
            # Watch both streams concurrently
            trades, candles = await asyncio.gather(
                exchange.watch_trades(SYMBOL),
                exchange.watch_ohlcv(SYMBOL, TIMEFRAME)
            )
            
            # --- Process Trades ---
            if trades:
                latest_trade = trades[-1]
                with data_lock:
                    live_price['price'] = latest_trade['price']
                    live_price['timestamp'] = latest_trade['timestamp']
                logger.info(f"Live price updated: {live_price['price']:.4f}")

            # --- Process Candles ---
            if candles:
                with data_lock:
                    # This gives us the full list of candles from the stream
                    live_candles = candles
                logger.info(f"Live candles updated. Total candles: {len(live_candles)}")

        except Exception as e:
            logger.error(f"WebSocket error: {e}. Reconnecting in 15 seconds...")
            await asyncio.sleep(15)
            # The loop will automatically try to reconnect on the next iteration

def start_websocket_client():
    """Starts the WebSocket client in a separate thread."""
    def loop_in_thread():
        logger.info("WebSocket thread started.")
        exchange = get_exchange()
        # Set a new asyncio event loop for this thread
        asyncio.set_event_loop(asyncio.new_event_loop())
        loop = asyncio.get_event_loop()
        loop.run_until_complete(watch_trades_and_candles(exchange))
        # This part is reached if the loop exits, which it shouldn't in normal operation
        loop.run_until_complete(exchange.close())
        logger.info("WebSocket thread finished.")

    thread = threading.Thread(target=loop_in_thread, daemon=True)
    thread.start()
    logger.info("WebSocket client initiated in a background thread.")
    # Give the websocket a moment to connect and fetch initial data
    time.sleep(10)

# --- Modified functions to use live data ---

def fetch_candles(exchange, symbol, timeframe, limit=100):
    """
    Returns the latest candles from the live WebSocket data.
    The exchange, symbol, timeframe, and limit arguments are kept for compatibility
    with the existing bot logic, but the data comes from the global state.
    """
    with data_lock:
        if not live_candles:
            logger.warning("`fetch_candles` called but live_candles is empty. Waiting for WebSocket data.")
            # Fallback to REST API for initial fetch if needed, though start_websocket_client has a sleep timer
            try:
                return exchange.fetch_ohlcv(symbol, timeframe, limit=limit)
            except Exception as e:
                logger.error(f"Fallback fetch_ohlcv failed: {e}")
                return []
        # Return a copy to avoid modification issues
        return list(live_candles)

def get_current_price(exchange, symbol):
    """
    Returns the latest price from the live WebSocket data.
    """
    with data_lock:
        if live_price['price'] is None:
            logger.warning("`get_current_price` called but live_price is None. Waiting for WebSocket data.")
            # Fallback for initial price
            try:
                ticker = exchange.fetch_ticker(symbol)
                return ticker['last']
            except Exception as e:
                logger.error(f"Fallback fetch_ticker failed: {e}")
                return None
        return live_price['price']

# --- Unchanged functions below (for now) ---

def create_market_buy_order(exchange, symbol, amount_usdt):
    if DRY_RUN:
        logger.info(f"DRY RUN: Would buy {symbol} with {amount_usdt} USDT.")
        price = get_current_price(exchange, symbol)
        if not price:
            logger.error("DRY RUN failed: Could not get current price for simulation.")
            return None
        return {
            "price": price,
            "amount": amount_usdt / price,
            "cost": amount_usdt,
            "symbol": symbol,
            "datetime": exchange.iso8601(exchange.milliseconds()),
        }

    try:
        # Using the regular (non-async) method for a one-off action
        order = exchange.create_market_buy_order_with_cost(symbol, amount_usdt)
        logger.info(f"Created market buy order: {order}")
        return order
    except ccxt.BaseError as e:
        logger.error(f"Error creating market buy order: {e}")
        return None

def get_account_balance(exchange):
    if DRY_RUN:
        logger.info("DRY RUN: Simulating account balance.")
        base_currency, quote_currency = SYMBOL.split('/')
        return {
            quote_currency: {"free": 1000.0, "used": 0.0, "total": 1000.0},
            base_currency: {"free": 0.0, "used": 0.0, "total": 0.0} # Start with no base currency
        }
    try:
        balance = exchange.fetch_balance()
        return {
            asset: data
            for asset, data in balance.items()
            if isinstance(data, dict) and data.get('total') is not None and data['total'] > 0
        }
    except ccxt.BaseError as e:
        logger.error(f"Error fetching account balance: {e}")
        return {}

def fetch_last_buy_trade(exchange, symbol, lookback_limit=25):
    try:
        logger.info(f"Fetching last trades for {symbol} to find entry price...")
        my_trades = exchange.fetch_my_trades(symbol=symbol, limit=lookback_limit)
        buy_trades = [trade for trade in my_trades if trade.get('side') == 'buy']
        if not buy_trades:
            logger.warning(f"No buy trades found for {symbol} in the last {lookback_limit} trades.")
            return None
        buy_trades.sort(key=lambda t: t['timestamp'])
        last_buy = buy_trades[-1]
        logger.info(f"Found last buy trade: {last_buy}")
        return last_buy
    except ccxt.BaseError as e:
        logger.error(f"Error fetching my trades for {symbol}: {e}")
        return None

def create_market_sell_order(exchange, symbol, size):
    if DRY_RUN:
        logger.info(f"DRY RUN: Would sell {size} of {symbol}.")
        price = get_current_price(exchange, symbol)
        if not price:
            logger.error("DRY RUN failed: Could not get current price for simulation.")
            return None
        return {
            "price": price,
            "amount": size,
            "cost": size * price,
            "symbol": symbol,
            "datetime": exchange.iso8601(exchange.milliseconds()),
        }

    try:
        order = exchange.create_market_sell_order(symbol, size)
        logger.info(f"Created market sell order: {order}")
        return order
    except ccxt.BaseError as e:
        logger.error(f"Error creating market sell order: {e}")
        return None
