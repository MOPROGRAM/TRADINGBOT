# main.py - Entry point for the AI Trading Bot

import asyncio
import time
import pandas as pd
from datetime import datetime, timedelta
import uvicorn
from utils.binance_client import get_binance_client, fetch_historical_data, create_order
from utils.telegram_notifier import send_telegram_message
from strategies.ai_strategy import AIStrategy
from shared_state import bot_state
from websocket_manager import binance_websocket_client
from ai_bot_dashboard.main import app as fastapi_app
import os

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
            # --- Wait for the first price update from WebSocket ---
            current_price = bot_state.get_state().get("current_price")
            if not current_price:
                print("Waiting for first price update from WebSocket...")
                await asyncio.sleep(5)
                continue

            # Fetch historical data for decision making (less frequent)
            historical_data_df = pd.DataFrame(await fetch_historical_data(client, SYMBOL, TIMEFRAME, 200), columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
            strategy._calculate_features(historical_data_df)
            
            if historical_data_df.empty:
                await asyncio.sleep(60 * 15)
                continue
            
            current_atr = historical_data_df['ATRr_14'].iloc[-1]

            # Update shared state with balance and position info (example)
            # In a real bot, you'd fetch this periodically
            balance_info = await client.fetch_balance()
            bot_state.update_state("balance", {
                "USDT": balance_info['USDT']['free'],
                "XLM": balance_info['XLM']['free']
            })
            bot_state.update_state("has_position", has_position)
            bot_state.update_state("position", {"entry_price": entry_price} if has_position else {})

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
            prediction = strategy.predict(historical_data_df)
            signal = prediction[-1] if len(prediction) > 0 else 0
            
            if signal == 1 and not has_position:
                print("Buy signal received. Placing market buy order.")
                order = await create_order(client, SYMBOL, 'market', 'buy', ORDER_AMOUNT)
                entry_price = order.get('price', current_price)
                stop_loss_price = entry_price - (current_atr * atr_multiplier)
                send_telegram_message(f"🚀 BUY SIGNAL: Placed market buy order for {ORDER_AMOUNT} {SYMBOL}.\nEntry Price: {entry_price:.4f}\nInitial Stop-Loss: {stop_loss_price:.4f}")
                has_position = True
                bot_state.update_state("signal", "Buy")
                bot_state.update_state("signal_reason", f"AI Model Prediction: Buy at {current_price:.4f}")
            elif signal == -1 and has_position:
                breakeven_price = entry_price * (1 + 2 * fee_rate)
                if current_price > breakeven_price:
                    print("Sell signal received. Placing market sell order.")
                    order = await create_order(client, SYMBOL, 'market', 'sell', ORDER_AMOUNT)
                    send_telegram_message(f"🛑 SELL SIGNAL: Placed market sell order for {ORDER_AMOUNT} {SYMBOL}.\nOrder details: {order}")
                    has_position = False
                    entry_price = 0
                    bot_state.update_state("signal", "Sell")
                    bot_state.update_state("signal_reason", f"AI Model Prediction: Sell at {current_price:.4f}")
                else:
                    print(f"Hold signal: Current price {current_price:.4f} is below breakeven {breakeven_price:.4f}")
                    bot_state.update_state("signal", "Hold")
                    bot_state.update_state("signal_reason", f"Waiting for price > breakeven {breakeven_price:.4f}")
            else:
                print("Hold signal received. No action taken.")
                bot_state.update_state("signal", "Hold")
                bot_state.update_state("signal_reason", "AI Model Prediction: Hold")

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

if __name__ == "__main__":
    # This file is not meant to be run directly anymore.
    # The bot logic is started by ai_bot_dashboard/main.py
    print("This script is not intended to be run directly. Run ai_bot_dashboard/main.py instead.")
