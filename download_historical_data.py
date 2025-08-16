# download_historical_data.py

import asyncio
import pandas as pd
from datetime import datetime, timedelta
from utils.binance_client import get_binance_client

async def download_data(symbol, timeframe, years, filename):
    """
    Downloads historical data for a given symbol and saves it to a CSV file.
    """
    client = get_binance_client()
    
    # Calculate start date
    since = client.parse8601((datetime.now() - timedelta(days=years * 365)).isoformat())
    
    all_ohlcv = []
    
    print(f"Starting download for {symbol}...")
    
    while True:
        try:
            ohlcv = await client.fetch_ohlcv(symbol, timeframe, since, limit=1000)
            if len(ohlcv) > 0:
                since = ohlcv[-1][0] + 1
                all_ohlcv.extend(ohlcv)
                print(f"Fetched {len(ohlcv)} candles... Total: {len(all_ohlcv)}")
            else:
                break
        except Exception as e:
            print(f"An error occurred: {e}. Retrying...")
            await asyncio.sleep(5)

    await client.close()
    
    # Save to CSV
    df = pd.DataFrame(all_ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
    df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
    df.to_csv(filename, index=False)
    print(f"\nData saved to {filename}")

if __name__ == "__main__":
    SYMBOL = 'XLM/USDT'
    TIMEFRAME = '15m'
    YEARS = 1
    FILENAME = f"{SYMBOL.replace('/', '_')}_{TIMEFRAME}_{YEARS}y.csv"
    
    asyncio.run(download_data(SYMBOL, TIMEFRAME, YEARS, FILENAME))
