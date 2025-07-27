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
    except ccxt.errors.Error as e:
        logger.error(f"Error fetching candles for {symbol}: {e}")
        return []

def get_current_price(exchange, symbol):
    try:
        ticker = exchange.fetch_ticker(symbol)
        return ticker['last']
    except ccxt.errors.Error as e:
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
    except ccxt.errors.Error as e:
        logger.error(f"Error creating market buy order: {e}")
        return None

def get_account_balance(exchange):
    if DRY_RUN:
        logger.info("DRY RUN: Simulating account balance.")
        base_currency, quote_currency = "XLM", "USDT"
        return {
            quote_currency: {"free": 1000.0, "total": 1000.0},
            base_currency: {"free": 500.0, "total": 500.0}
        }
    try:
        balance = exchange.fetch_balance()
        # Filter out zero balances for clarity
        return {
            asset: data 
            for asset, data in balance['total'].items() 
            if data > 0
        }
    except ccxt.errors.Error as e:
        logger.error(f"Error fetching account balance: {e}")
        return {}

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
    except ccxt.errors.Error as e:
        logger.error(f"Error creating market sell order: {e}")
        return None
