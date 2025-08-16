# backtest.py

import pandas as pd
from strategies.ai_strategy import AIStrategy
from utils.binance_client import get_binance_client, fetch_historical_data
import asyncio

import os

async def run_backtest():
    """
    Runs a backtest of the AI strategy on historical data.
    """
    symbol = 'XLM/USDT'
    timeframe = '15m'
    years = 1
    data_filename = f"{symbol.replace('/', '_')}_{timeframe}_{years}y.csv"

    # Check if historical data exists, otherwise fetch it
    if not os.path.exists(data_filename):
        print(f"Data file {data_filename} not found.")
        print("Please run 'py download_historical_data.py' first to download the data.")
        return

    print(f"Loading historical data from {data_filename}...")
    df_full = pd.read_csv(data_filename)
    
    # Ensure correct data types for all columns
    numeric_cols = ['open', 'high', 'low', 'close', 'volume']
    for col in numeric_cols:
        df_full[col] = pd.to_numeric(df_full[col], errors='coerce')
    df_full.dropna(inplace=True) # Drop rows where conversion might have failed
    
    # Convert timestamp back to milliseconds for ccxt compatibility if needed, but we'll use the df directly
    df_full['timestamp'] = pd.to_datetime(df_full['timestamp'])
    # The historical_data format for training needs to be a list of lists
    historical_data = df_full[['timestamp', 'open', 'high', 'low', 'close', 'volume']].to_numpy()
    # Convert timestamp to milliseconds for training function
    historical_data[:, 0] = df_full['timestamp'].apply(lambda x: int(x.timestamp() * 1000))

    # Initialize and train the strategy
    strategy = AIStrategy()
    strategy.train(historical_data)

    # Simulate trading
    df_features = strategy._calculate_features(df_full.copy())
    
    signals = strategy.predict(df_features)
    
    # Align signals with the original dataframe
    aligned_features, df = df_features.align(df_full, 'right', axis=0)
    df['signal'] = 0
    df.iloc[-len(signals):, df.columns.get_loc('signal')] = signals
    
    # Add only the new feature columns to the main dataframe
    feature_cols = [col for col in aligned_features.columns if col not in df.columns]
    df = pd.concat([df, aligned_features[feature_cols]], axis=1)

    # Print backtest period
    start_date = pd.to_datetime(df['timestamp'].iloc[0], unit='ms')
    end_date = pd.to_datetime(df['timestamp'].iloc[-1], unit='ms')
    print(f"\nBacktest Period: {start_date} to {end_date}")

    initial_balance = 1000
    balance = initial_balance
    position = 0
    entry_price = 0
    trades = []
    fee_rate = 0.001 # 0.1% fee per trade
    slippage_rate = 0.0005 # 0.05% slippage
    atr_multiplier = 2.5 # Multiplier for ATR-based stop-loss
    stop_loss_price = 0
    
    for i, row in df.iterrows():
        # --- Dynamic Trailing Stop-Loss Logic (based on ATR) ---
        if position > 0:
            # ATR value for the current candle
            current_atr = row['ATRr_14']
            
            # Update stop-loss if price moves up
            new_stop_loss = row['close'] - (current_atr * atr_multiplier)
            if new_stop_loss > stop_loss_price:
                stop_loss_price = new_stop_loss
            
            # Check if stop-loss is hit
            if row['close'] < stop_loss_price:
                exit_price = stop_loss_price # Sell at the stop price
                sell_value = (position * exit_price) * (1 - fee_rate)
                buy_value = entry_price * position / (1 - fee_rate)
                trade_pnl = sell_value - buy_value
                balance = sell_value
                pnl_percent = ((exit_price - entry_price) / entry_price) * 100
                trades.append({'pnl': trade_pnl, 'pnl_percent': pnl_percent})
                position = 0
                print(f"--- Trailing Stop-Loss Hit ---")
                print(f"Entry: {entry_price:.4f}, Exit: {exit_price:.4f} | PnL: {trade_pnl:.2f} ({pnl_percent:.2f}%)")
                continue # Skip the regular signal check for this candle

        # --- Signal-based Trading Logic ---
        if row['signal'] == 1 and position == 0: # Buy signal
            buy_price = row['close'] * (1 + slippage_rate)
            position = (balance / buy_price) * (1 - fee_rate)
            entry_price = buy_price
            # Initial stop-loss based on ATR at entry
            initial_atr = row['ATRr_14']
            stop_loss_price = buy_price - (initial_atr * atr_multiplier)
            balance = 0
            print(f"Buying at {entry_price:.4f}")
        elif row['signal'] == -1 and position > 0: # Sell signal
            exit_price = row['close'] * (1 - slippage_rate)
            
            # Breakeven price check (must cover two fees)
            breakeven_price = entry_price * (1 + 2 * fee_rate)
            if exit_price > breakeven_price:
                sell_value = (position * exit_price) * (1 - fee_rate)
                buy_value = entry_price * position / (1 - fee_rate)
                trade_pnl = sell_value - buy_value
                balance = sell_value
                pnl_percent = ((exit_price - entry_price) / entry_price) * 100
                trades.append({'pnl': trade_pnl, 'pnl_percent': pnl_percent})
                position = 0
                print(f"Selling at {exit_price:.4f} | PnL: {trade_pnl:.2f} ({pnl_percent:.2f}%)")
            else:
                print(f"Hold signal: Exit price {exit_price:.4f} is below breakeven {breakeven_price:.4f}")

    final_balance = balance + position * df['close'].iloc[-1]
    
    # --- Summary ---
    print("\n--- Backtest Summary ---")
    print(f"Initial Balance: {initial_balance}")
    print(f"Final Balance: {final_balance:.2f}")
    print(f"Total Profit/Loss: {((final_balance - initial_balance) / initial_balance) * 100:.2f}%")
    
    if trades:
        winning_trades = [t for t in trades if t['pnl'] > 0]
        losing_trades = [t for t in trades if t['pnl'] <= 0]
        win_rate = len(winning_trades) / len(trades) * 100
        total_trades = len(trades)
        avg_pnl = sum(t['pnl_percent'] for t in trades) / total_trades
        
        print(f"Backtest Duration: {end_date - start_date}")
        print(f"Total Trades: {total_trades}")
        print(f"Winning Trades: {len(winning_trades)}")
        print(f"Losing Trades: {len(losing_trades)}")
        print(f"Win Rate: {win_rate:.2f}%")
        print(f"Average PnL per trade: {avg_pnl:.2f}%")

if __name__ == "__main__":
    asyncio.run(run_backtest())
