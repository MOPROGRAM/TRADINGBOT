# train_model.py

import asyncio
from strategies.ai_strategy import AIStrategy
from download_historical_data import download_data
import pandas as pd
import os

async def main():
    """
    Downloads the latest data and retrains the model.
    """
    SYMBOL = 'XLM/USDT'
    TIMEFRAME = '15m'
    YEARS = 1
    FILENAME = f"{SYMBOL.replace('/', '_')}_{TIMEFRAME}_{YEARS}y.csv"
    
    # Step 1: Download the latest 1 year of data
    print("--- Step 1: Downloading latest historical data ---")
    await download_data(SYMBOL, TIMEFRAME, YEARS, FILENAME)
    
    # Step 2: Load the data and train the model
    print("\n--- Step 2: Training the model ---")
    if not os.path.exists(FILENAME):
        print(f"Error: Data file {FILENAME} not found after download attempt.")
        return
        
    df = pd.read_csv(FILENAME)
    historical_data = df[['timestamp', 'open', 'high', 'low', 'close', 'volume']].to_numpy()
    # Convert timestamp to milliseconds for training function
    df['timestamp'] = pd.to_datetime(df['timestamp'])
    historical_data[:, 0] = df['timestamp'].apply(lambda x: int(x.timestamp() * 1000))

    strategy = AIStrategy()
    strategy.train(historical_data)
    
    print("\n--- Model retraining complete! ---")
    print(f"The model has been updated and saved to '{strategy.model_path}'.")
    print("The main bot will now use this new model on its next run.")

if __name__ == "__main__":
    asyncio.run(main())
