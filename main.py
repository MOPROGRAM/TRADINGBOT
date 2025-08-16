# main.py - Entry point for the AI Trading Bot

import asyncio
import time
import pandas as pd
from datetime import datetime, timedelta
from utils.binance_client import get_binance_client, fetch_historical_data, create_order
from utils.telegram_notifier import send_telegram_message
from strategies.ai_strategy import AIStrategy

SYMBOL = 'XLM/USDT'
TIMEFRAME = '15m'
ORDER_AMOUNT = 100  # Example: 100 XLM

async def main_loop():
    """
    The main operational loop for the trading bot.
    """
    client = get_binance_client()
    strategy = AIStrategy()
    
    # Initial training
    print("Performing initial model training...")
    historical_data = await fetch_historical_data(client, SYMBOL, TIMEFRAME, 1000)
    strategy.train(historical_data)
    print("Initial training complete.")
    last_training_time = datetime.now()

    has_position = False
    entry_price = 0
    fee_rate = 0.001
    atr_multiplier = 2.5 # Multiplier for ATR-based stop-loss
    stop_loss_price = 0

    while True:
        try:
            # Fetch latest data for prediction and ATR
            latest_data_df = pd.DataFrame(await fetch_historical_data(client, SYMBOL, TIMEFRAME, 100), columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
            strategy._calculate_features(latest_data_df) # Calculate all features including ATR
            
            if latest_data_df.empty:
                await asyncio.sleep(60 * 15)
                continue

            current_price = latest_data_df['close'].iloc[-1]
            current_atr = latest_data_df['ATRr_14'].iloc[-1]

            # --- Dynamic Trailing Stop-Loss Logic ---
            if has_position:
                new_stop_loss = current_price - (current_atr * atr_multiplier)
                if new_stop_loss > stop_loss_price:
                    stop_loss_price = new_stop_loss
                    print(f"Trailing stop-loss updated to: {stop_loss_price:.4f}")

                if current_price < stop_loss_price:
                    print(f"--- Trailing Stop-Loss Hit ---")
                    order = await create_order(client, SYMBOL, 'market', 'sell', ORDER_AMOUNT)
                    send_telegram_message(f"🛑 TRAILING STOP-LOSS HIT: Selling at {current_price:.4f}.\nOrder details: {order}")
                    has_position = False
                    entry_price = 0
                    await asyncio.sleep(60 * 15) # Wait for next candle
                    continue

            # --- Signal-based Trading Logic ---
            prediction = strategy.predict(latest_data_df)
            signal = prediction[-1] if len(prediction) > 0 else 0
            
            if signal == 1 and not has_position:
                print("Buy signal received. Placing market buy order.")
                order = await create_order(client, SYMBOL, 'market', 'buy', ORDER_AMOUNT)
                entry_price = order.get('price', current_price)
                stop_loss_price = entry_price - (current_atr * atr_multiplier)
                send_telegram_message(f"🚀 BUY SIGNAL: Placed market buy order for {ORDER_AMOUNT} {SYMBOL}.\nEntry Price: {entry_price:.4f}\nInitial Stop-Loss: {stop_loss_price:.4f}")
                has_position = True
            elif signal == -1 and has_position:
                breakeven_price = entry_price * (1 + 2 * fee_rate)
                if current_price > breakeven_price:
                    print("Sell signal received. Placing market sell order.")
                    order = await create_order(client, SYMBOL, 'market', 'sell', ORDER_AMOUNT)
                    send_telegram_message(f"🛑 SELL SIGNAL: Placed market sell order for {ORDER_AMOUNT} {SYMBOL}.\nOrder details: {order}")
                    has_position = False
                    entry_price = 0
                else:
                    print(f"Hold signal: Current price {current_price:.4f} is below breakeven {breakeven_price:.4f}")
            else:
                print("Hold signal received. No action taken.")

            # --- Periodic Retraining Logic ---
            if datetime.now() - last_training_time > timedelta(days=7):
                print("\n--- Starting scheduled weekly model retraining ---")
                send_telegram_message("🤖 Starting scheduled weekly model retraining...")
                try:
                    # Fetch a larger dataset for retraining
                    training_data = await fetch_historical_data(client, SYMBOL, TIMEFRAME, 1500)
                    strategy.train(training_data)
                    last_training_time = datetime.now()
                    print("--- Model retraining complete! ---")
                    send_telegram_message("✅ Model retraining complete!")
                except Exception as train_e:
                    print(f"An error occurred during retraining: {train_e}")
                    send_telegram_message(f"⚠️ ERROR: Model retraining failed: {train_e}")

        except Exception as e:
            print(f"An error occurred: {e}")
            send_telegram_message(f"⚠️ ERROR: An error occurred in the bot: {e}")
        
        await asyncio.sleep(60 * 15) # Wait for the next 15-minute candle

def run():
    """
    Main function to start the AI Trading Bot.
    """
    print("AI Trading Bot starting...")
    asyncio.run(main_loop())

if __name__ == "__main__":
    run()
