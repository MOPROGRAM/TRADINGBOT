# utils/binance_client.py

import os
import ccxt.async_support as ccxt
from dotenv import load_dotenv

load_dotenv()

def get_binance_client():
    """
    Initializes and returns the Binance exchange client.
    """
    api_key = os.getenv('BINANCE_API_KEY')
    api_secret = os.getenv('BINANCE_API_SECRET')

    config = {
        'options': {
            'defaultType': 'spot',
        },
    }

    # Only add API keys if they are not the default placeholders
    if api_key and api_key != 'your_binance_api_key':
        config['apiKey'] = api_key
    if api_secret and api_secret != 'your_binance_api_secret':
        config['secret'] = api_secret

    exchange = ccxt.binance(config)
    return exchange

async def fetch_historical_data(client, symbol, timeframe, limit):
    """
    Fetches historical OHLCV data for a given symbol.
    """
    return await client.fetch_ohlcv(symbol, timeframe, limit=limit)

async def create_order(client, symbol, order_type, side, amount, price=None):
    """
    Creates an order on Binance.
    """
    params = {}
    if price:
        params['price'] = price
    return await client.create_order(symbol, order_type, side, amount, params=params)
