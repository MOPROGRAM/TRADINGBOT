import os
import ccxt
import asyncio
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

async def fetch_candles(exchange, symbol, timeframe, limit=100):
    """
    Returns the latest candles from the REST API.
    """
    try:
        return await exchange.fetch_ohlcv(symbol, timeframe, limit=limit)
    except Exception as e:
        logger.error(f"Failed to fetch_ohlcv: {e}")
        return []

async def get_current_price(exchange, symbol):
    """
    Returns the latest price from the REST API.
    """
    try:
        ticker = await exchange.fetch_ticker(symbol)
        return ticker['last']
    except Exception as e:
        logger.error(f"Failed to fetch_ticker: {e}")
        return None

async def create_market_buy_order(exchange, symbol, amount_usdt):
    if DRY_RUN:
        logger.info(f"DRY RUN: Would buy {symbol} with {amount_usdt} USDT.")
        price = await get_current_price(exchange, symbol)
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
        order = await exchange.create_market_buy_order_with_cost(symbol, amount_usdt)
        logger.info(f"Created market buy order: {order}")
        return order
    except ccxt.BaseError as e:
        logger.error(f"Error creating market buy order: {e}")
        return None

async def get_account_balance(exchange):
    if DRY_RUN:
        logger.info("DRY RUN: Simulating account balance.")
        base_currency, quote_currency = SYMBOL.split('/')
        return {
            quote_currency: {"free": 1000.0, "used": 0.0, "total": 1000.0},
            base_currency: {"free": 0.0, "used": 0.0, "total": 0.0} # Start with no base currency
        }
    try:
        balance = await exchange.fetch_balance()
        return {
            asset: data
            for asset, data in balance['total'].items()
            if data > 0
        }
    except ccxt.BaseError as e:
        logger.error(f"Error fetching account balance: {e}")
        return {}

async def fetch_last_buy_trade(exchange, symbol, lookback_limit=25):
    try:
        logger.info(f"Fetching last trades for {symbol} to find entry price...")
        my_trades = await exchange.fetch_my_trades(symbol=symbol, limit=lookback_limit)
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

async def create_market_sell_order(exchange, symbol, size):
    if DRY_RUN:
        logger.info(f"DRY RUN: Would sell {size} of {symbol}.")
        price = await get_current_price(exchange, symbol)
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
        order = await exchange.create_market_sell_order(symbol, size)
        logger.info(f"Created market sell order: {order}")
        return order
    except ccxt.BaseError as e:
        logger.error(f"Error creating market sell order: {e}")
        return None
