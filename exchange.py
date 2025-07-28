import os
import ccxt
from dotenv import load_dotenv
from logger import get_logger

load_dotenv()
logger = get_logger(__name__)

API_KEY = os.getenv('BINANCE_API_KEY')
API_SECRET = os.getenv('BINANCE_API_SECRET')
DRY_RUN = os.getenv('DRY_RUN', 'True').lower() == 'true'

def get_exchange():
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

def fetch_candles(exchange, symbol, timeframe, limit=3):
    try:
        candles = exchange.fetch_ohlcv(symbol, timeframe, limit=limit)
        # CCXT returns: [timestamp, open, high, low, close, volume]
        # We only need: [timestamp, open, high, low, close]
        return [[c[0], c[1], c[2], c[3], c[4]] for c in candles]
    except ccxt.BaseError as e:
        logger.error(f"Error fetching candles for {symbol}: {e}")
        return []

def get_current_price(exchange, symbol):
    try:
        ticker = exchange.fetch_ticker(symbol)
        return ticker['last']
    except ccxt.BaseError as e:
        logger.error(f"Error fetching current price for {symbol}: {e}")
        return None

def create_market_buy_order(exchange, symbol, amount_usdt):
    if DRY_RUN:
        logger.info(f"DRY RUN: Would buy {symbol} with {amount_usdt} USDT.")
        # Simulate a buy order
        price = get_current_price(exchange, symbol)
        if not price:
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
        base_currency, quote_currency = "XLM", "USDT"
        return {
            quote_currency: {"free": 1000.0, "used": 0.0, "total": 1000.0},
            base_currency: {"free": 500.0, "used": 0.0, "total": 500.0}
        }
    try:
        balance = exchange.fetch_balance()
        # Return the full structure for assets with a total balance > 0
        return {
            asset: data
            for asset, data in balance.items()
            if isinstance(data, dict) and data.get('total') is not None and data['total'] > 0
        }
    except ccxt.BaseError as e:
        logger.error(f"Error fetching account balance: {e}")
        return {}

def fetch_last_buy_trade(exchange, symbol, lookback_limit=25):
    """
    Fetches the last buy trade for a given symbol to determine the entry price.
    """
    try:
        logger.info(f"Fetching last trades for {symbol} to find entry price...")
        my_trades = exchange.fetch_my_trades(symbol=symbol, limit=lookback_limit)
        
        # Filter for buy trades and sort by timestamp descending (newest first)
        buy_trades = [trade for trade in my_trades if trade.get('side') == 'buy']
        
        if not buy_trades:
            logger.warning(f"No buy trades found for {symbol} in the last {lookback_limit} trades.")
            return None
            
        last_buy = buy_trades[-1] # The last one in the fetched list is the most recent
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
