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
    """Starts the global WebSocket client."""
    websocket_client.start()

def stop_websocket_client():
    """Stops the global WebSocket client."""
    websocket_client.stop()

def fetch_candles(exchange, symbol, timeframe, limit=100):
    """
    Returns the latest candles, primarily from WebSocket cache, with REST API fallback.
    """
    candles = websocket_client.get_kline_data(timeframe)
    if candles and len(candles) >= limit:
        # logger.debug(f"Fetched {len(candles)} {timeframe} candles from WebSocket cache.")
        return list(candles)[-limit:] # Return the last 'limit' candles
    
    logger.warning(f"WebSocket cache for {timeframe} candles is empty or insufficient. Falling back to REST API.")
    try:
        # Fallback to REST API if WebSocket cache is not ready or insufficient
        rest_candles = exchange.fetch_ohlcv(symbol, timeframe, limit=limit)
        if rest_candles:
            # Optionally, update the cache with these candles if needed, but WebSocket should fill it.
            # For now, just return them.
            return rest_candles
        return []
    except Exception as e:
        logger.error(f"Failed to fetch_ohlcv from REST API (fallback): {e}")
        return []

def get_current_price(exchange, symbol):
    """
    Returns the latest price, primarily from WebSocket cache, with REST API fallback.
    """
    price = websocket_client.get_latest_price()
    if price is not None:
        # logger.debug(f"Fetched latest price {price} from WebSocket cache.")
        return price
    
    logger.warning("WebSocket cache for latest price is empty. Falling back to REST API.")
    try:
        # Fallback to REST API if WebSocket cache is not ready
        ticker = exchange.fetch_ticker(symbol)
        return ticker['last']
    except Exception as e:
        logger.error(f"Failed to fetch_ticker from REST API (fallback): {e}")
        return None

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
        return {
            quote_currency: {"free": 1000.0, "used": 0.0, "total": 1000.0},
            base_currency: {"free": 0.0, "used": 0.0, "total": 0.0} # Start with no base currency
        }
    try:
        balance = exchange.fetch_balance()
        return balance['total'] # Return the 'total' balances directly, which is a dict of asset:amount
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
