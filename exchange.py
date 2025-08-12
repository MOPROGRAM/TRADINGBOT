import os
import ccxt
from dotenv import load_dotenv
from logger import get_logger
import time
from websocket_client import BinanceWebSocketClient # Import the new WebSocket client

load_dotenv()
logger = get_logger(__name__)

API_KEY = os.getenv('BINANCE_API_KEY')
API_SECRET = os.getenv('BINANCE_API_SECRET')
DRY_RUN = os.getenv('DRY_RUN', 'True').lower() == 'true'
SYMBOL = os.getenv('SYMBOL', 'XLM/USDT')
TIMEFRAME = os.getenv('TIMEFRAME', '5m')
TREND_TIMEFRAME = os.getenv('TREND_TIMEFRAME', '1h') # Ensure this is defined for WebSocket client
FIFTEEN_MIN_TIMEFRAME = '15m' # Hardcode 15m for EMA 200

# Initialize WebSocket client globally
# It will be started/stopped by bot.py
websocket_client = BinanceWebSocketClient(
    symbol=SYMBOL,
    kline_intervals=[TIMEFRAME, FIFTEEN_MIN_TIMEFRAME, TREND_TIMEFRAME]
)

def get_exchange():
    """Initializes the exchange object."""
    exchange = ccxt.binance({
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

def start_websocket_client():
    """Starts the global WebSocket client and waits for it to be initialized."""
    websocket_client.start()
    logger.info("Waiting for WebSocket client to initialize...")
    initialized = websocket_client.initialized.wait(timeout=30) # Wait for up to 30 seconds
    if initialized:
        logger.info("WebSocket client initialized successfully.")
    else:
        logger.error("WebSocket client failed to initialize within the timeout period.")

def stop_websocket_client():
    """Stops the global WebSocket client."""
    websocket_client.stop()

def fetch_candles(exchange, symbol, timeframe, limit=100):
    """
    Returns the latest candles, primarily from WebSocket cache, with a robust REST API fallback.
    """
    # Attempt to get data from the WebSocket cache first
    candles = websocket_client.get_kline_data(timeframe)
    
    # Check if the cached data is sufficient
    if len(candles) >= limit:
        # logger.debug(f"Using WebSocket cache for {timeframe}. Cache size: {len(candles)}, required: {limit}")
        return list(candles)[-limit:]

    # If cache is insufficient, log it and fall back to REST API
    logger.warning(f"WebSocket cache for {timeframe} is insufficient (have {len(candles)}, need {limit}). Fetching via REST API.")
    
    try:
        # Fetch historical data using the exchange's fetch_ohlcv method
        historical_candles_raw = exchange.fetch_ohlcv(symbol, timeframe, limit=limit)
        
        # The WebSocket client expects an 'is_closed' flag. We assume historical candles are closed.
        historical_candles = [candle + [True] for candle in historical_candles_raw]
        
        logger.info(f"Successfully fetched {len(historical_candles)} candles for {timeframe} via REST API.")
        return historical_candles
        
    except (ccxt.RateLimitExceeded, ccxt.DDoSProtection) as e:
        logger.error(f"REST API call for {timeframe} failed due to rate limit/DDoS protection: {e}")
        return [] # Return empty list on failure
    except Exception as e:
        logger.error(f"An unexpected error occurred during REST API fallback for {timeframe}: {e}", exc_info=True)
        return [] # Return empty list on failure

def get_current_price(exchange, symbol):
    """
    Returns the latest price, primarily from WebSocket cache, with REST API fallback.
    """
    price = websocket_client.get_latest_price()
    if price is None:
        logger.warning("WebSocket cache for latest price is empty. No price available.")
    return price

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
        # In dry run, return a simple dictionary similar to the 'free' balance structure.
        return {
            quote_currency: 1000.0,
            base_currency: 0.0
        }
    try:
        balance_data = exchange.fetch_balance()
        # The 'free' key contains a dictionary of available balances for each currency.
        if isinstance(balance_data, dict) and 'free' in balance_data and isinstance(balance_data['free'], dict):
            return balance_data['free']
        else:
            logger.error(f"fetch_balance returned an unexpected data structure: {balance_data}. Returning an empty dict.")
            return {}
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

def get_trading_fees(exchange, symbol):
    """Fetches the trading fees for a given symbol."""
    try:
        fees = exchange.fetch_trading_fees()
        if symbol in fees:
            return fees[symbol]['taker']
        else:
            logger.warning(f"Could not find fee information for {symbol}. Returning default 0.001.")
            return 0.001 # Default fee if not found
    except ccxt.BaseError as e:
        logger.error(f"Error fetching trading fees: {e}")
        return 0.001 # Default fee on error
