import os
import ccxt
import pandas as pd
import pandas_ta as ta
import joblib
import json
from datetime import datetime
from sklearn.model_selection import train_test_split
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import classification_report

# --- Configuration ---
SYMBOL = 'XLM/USDT'
TIMEFRAME = '5m'
LIMIT = 2000  # Number of candles to fetch for training
MODEL_PATH = 'trading_model.pkl'
MODEL_INFO_PATH = 'model_info.json'
TARGET_RETURN = 0.005  # 0.5% return
HOLDING_PERIOD = 12      # Look 12 candles (1 hour) into the future

def fetch_data(symbol, timeframe, limit):
    """Fetches historical candle data from Binance."""
    print(f"Fetching {limit} candles for {symbol} on {timeframe} timeframe...")
    try:
        exchange = ccxt.binance()
        ohlcv = exchange.fetch_ohlcv(symbol, timeframe, limit=limit)
        df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
        print("Data fetched successfully.")
        return df
    except Exception as e:
        print(f"Error fetching data: {e}")
        return None

def create_features(df):
    """Creates features for the model from the candle data."""
    print("Creating features...")
    df.ta.macd(fast=12, slow=26, signal=9, append=True)
    df.ta.rsi(length=14, append=True)
    df.ta.ema(length=50, append=True)
    df['volume_change'] = df['volume'].pct_change()
    df['close_change'] = df['close'].pct_change()
    
    # Add more features here if needed
    
    df = df.dropna()
    print("Features created.")
    return df

def create_target(df, target_return, holding_period):
    """Creates the target variable for the model."""
    print("Creating target variable...")
    df['future_price'] = df['close'].shift(-holding_period)
    df['price_change'] = (df['future_price'] - df['close']) / df['close']
    df['target'] = (df['price_change'] > target_return).astype(int)
    df = df.dropna(subset=['target', 'future_price'])
    print("Target variable created.")
    return df

def train_model(df):
    """Trains the RandomForestClassifier model."""
    print("Training model...")
    features = [col for col in df.columns if 'MACD' in col or 'RSI' in col or 'EMA' in col or 'change' in col]
    X = df[features]
    y = df['target']

    X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=42, stratify=y)

    print(f"Training data size: {len(X_train)}")
    print(f"Test data size: {len(X_test)}")
    print(f"Buy signal distribution in training data: \n{y_train.value_counts(normalize=True)}")

    model = RandomForestClassifier(n_estimators=100, random_state=42, class_weight='balanced')
    model.fit(X_train, y_train)

    # Evaluate model
    y_pred = model.predict(X_test)
    print("\n--- Classification Report ---")
    print(classification_report(y_test, y_pred))
    print("---------------------------\n")

    # Save model
    joblib.dump(model, MODEL_PATH)
    print(f"Model saved to {MODEL_PATH}")

    # Save model info
    model_info = {
        'last_trained_date': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'symbol': SYMBOL,
        'timeframe': TIMEFRAME,
        'features_used': features
    }
    with open(MODEL_INFO_PATH, 'w') as f:
        json.dump(model_info, f, indent=4)
    print(f"Model info saved to {MODEL_INFO_PATH}")


if __name__ == '__main__':
    data = fetch_data(SYMBOL, TIMEFRAME, LIMIT)
    if data is not None:
        featured_data = create_features(data)
        targeted_data = create_target(featured_data, TARGET_RETURN, HOLDING_PERIOD)
        if not targeted_data.empty:
            train_model(targeted_data)
        else:
            print("Could not create target variable. Aborting training.")
