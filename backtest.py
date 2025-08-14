import os
import ccxt
import pandas as pd
from datetime import datetime, timedelta
import time
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Import necessary functions from the existing codebase
# We will need to adapt them or use them as is.
from exchange import get_exchange, SYMBOL, TIMEFRAME
from signals import check_buy_signal, check_sell_signal
from logger import get_logger

logger = get_logger(__name__)

def fetch_historical_data(exchange, symbol, timeframe, since, limit=500):
    """
    Fetches historical OHLCV data from the exchange since a specific timestamp.
    """
    all_candles = []
    while since < exchange.milliseconds():
        try:
            logger.info(f"Fetching candles for {symbol} starting from {exchange.iso8601(since)}")
            candles = exchange.fetch_ohlcv(symbol, timeframe, since, limit)
            if not candles:
                logger.info("No more data to fetch.")
                break
            
            all_candles.extend(candles)
            since = candles[-1][0] + 1  # Move to the timestamp of the next candle
            
            # Respect exchange rate limits
            time.sleep(exchange.rateLimit / 1000)

        except (ccxt.RateLimitExceeded, ccxt.DDoSProtection) as e:
            logger.error(f"Rate limit exceeded: {e}. Sleeping...")
            time.sleep(60) # Sleep for a minute and retry
        except Exception as e:
            logger.error(f"An error occurred while fetching historical data: {e}")
            break
            
    return all_candles

def run_backtest():
    """
    Main function to run the backtesting process.
    """
    logger.info("--- Starting Backtest ---")
    
    # 1. Initialize Exchange
    exchange = get_exchange()
    
    # 2. Fetch Historical Data for 1 year for all required timeframes
    one_year_ago = datetime.now() - timedelta(days=365)
    since_timestamp = int(one_year_ago.timestamp() * 1000)
    
    timeframes_to_fetch = {
        'primary': TIMEFRAME,
        '15min': '15m',
        'trend': '1h'
    }
    
    dfs = {}
    for name, tf in timeframes_to_fetch.items():
        logger.info(f"Fetching historical data for {SYMBOL} on timeframe {tf} for the last year...")
        candles = fetch_historical_data(exchange, SYMBOL, tf, since_timestamp)
        if not candles:
            logger.error(f"Failed to fetch historical data for {tf}. Aborting backtest.")
            return
        
        df = pd.DataFrame(candles, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
        df.set_index('timestamp', inplace=True)
        # Add a 'is_closed' column, for backtesting all historical candles are considered closed
        df['is_closed'] = True
        dfs[name] = df
        logger.info(f"Successfully fetched {len(df)} candles for {tf} from {df.index.min()} to {df.index.max()}")

    # Use the primary dataframe for the main loop
    df_primary = dfs['primary']

    # --- Backtesting Logic ---
    initial_balance = 1000.0  # Start with 1000 USDT
    balance = initial_balance
    in_market = False
    asset_amount = 0
    trades = []
    
    # We need enough history for the longest indicator period, e.g., 100
    required_candles_history = 100

    for i in range(required_candles_history, len(df_primary)):
        current_time = df_primary.index[i]
        current_price = df_primary['close'].iloc[i]

        # Get corresponding candle history for all timeframes up to the current time
        # We need to reset the index to include the timestamp in the list
        primary_hist = df_primary.iloc[:i].reset_index().values.tolist()
        # For other timeframes, we need to find the candles that occurred before the current primary candle's time
        fifteen_min_hist = dfs['15min'][dfs['15min'].index < current_time].reset_index().values.tolist()
        trend_hist = dfs['trend'][dfs['trend'].index < current_time].reset_index().values.tolist()

        # Check for signals with custom backtest settings
        buy_signal, buy_reason = check_buy_signal(primary_hist, fifteen_min_hist, trend_hist, adx_trend_strength=20)
        if not in_market and buy_signal:
            # Simulate Buy
            asset_amount = balance / current_price
            in_market = True
            trades.append({'time': current_time, 'type': 'buy', 'price': current_price, 'balance': balance})
            logger.info(f"BUY signal at {current_time}: Price={current_price:.4f}, Balance={balance:.2f}. Reason: {buy_reason}")
            balance = 0 # All in

        # Sell signal logic can also be customized if needed, for now using default
        sell_signal, sell_reason = check_sell_signal(primary_hist, adx_trend_strength=20)
        if in_market and sell_signal:
            # Simulate Sell
            balance = asset_amount * current_price
            in_market = False
            trades.append({'time': current_time, 'type': 'sell', 'price': current_price, 'balance': balance})
            logger.info(f"SELL signal at {current_time}: Price={current_price:.4f}, Balance={balance:.2f}. Reason: {sell_reason}")
            asset_amount = 0

    # --- Calculate and Display Results ---
    logger.info("\n--- Backtest Results ---")
    
    final_balance = balance
    if in_market:
        # If still in market at the end, calculate value based on the last price
        final_balance = asset_amount * df_primary['close'].iloc[-1]

    total_return = (final_balance - initial_balance) / initial_balance * 100
    
    logger.info(f"Initial Balance: {initial_balance:.2f} USDT")
    logger.info(f"Final Balance:   {final_balance:.2f} USDT")
    logger.info(f"Total Return:    {total_return:.2f}%")
    logger.info(f"Total Trades:    {len(trades)}")
    
    # Optional: Print trades
    # for trade in trades:
    #     logger.info(f"  - {trade['time']} | {trade['type'].upper()} at {trade['price']:.4f} | New Balance: {trade['balance']:.2f}")


    logger.info("--- Backtest Finished ---")


if __name__ == "__main__":
    run_backtest()
