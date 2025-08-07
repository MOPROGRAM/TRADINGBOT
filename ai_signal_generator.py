import joblib
import pandas as pd
import pandas_ta as ta
import os
import json
from logger import get_logger

logger = get_logger(__name__)
MODEL_PATH = 'trading_model.pkl'

def get_ai_signal(candles_primary):
    """
    Loads the trained model and returns a buy signal prediction.
    """
    if not os.path.exists(MODEL_PATH):
        logger.warning("AI model not found. Skipping AI signal.")
        # Default to a neutral signal if model doesn't exist
        return False

    try:
        model = joblib.load(MODEL_PATH)
    except Exception as e:
        logger.error(f"Error loading AI model: {e}")
        return False

    # Feature Engineering (must match the features used in training)
    df = pd.DataFrame(candles_primary, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
    
    if len(df) < 50: # Need enough data for indicators
        logger.warning("Not enough candle data to generate AI features.")
        return False

    # Create features - This block MUST match the logic in train_model.py
    df.ta.macd(fast=12, slow=26, signal=9, append=True)
    df.ta.rsi(length=14, append=True)
    df.ta.ema(length=50, append=True)
    df['volume_change'] = df['volume'].pct_change()
    df['close_change'] = df['close'].pct_change()
    
    df = df.dropna()

    if df.empty:
        logger.warning("DataFrame is empty after feature creation and dropping NaNs.")
        return False

    # Get the feature names from the model info file
    try:
        with open('model_info.json', 'r') as f:
            model_info = json.load(f)
        feature_names = model_info['features_used']
    except Exception as e:
        logger.error(f"Could not read model info or feature names: {e}")
        # Fallback to a default list if file is not available
        feature_names = [col for col in df.columns if 'MACD' in col or 'RSI' in col or 'EMA' in col or 'change' in col]


    # Get the latest features for prediction
    latest_features = df[feature_names].iloc[-1:]

    # Get prediction
    try:
        prediction = model.predict(latest_features)
        if prediction[0] == 1:
            logger.info("AI model confirms BUY signal.")
            return True
        else:
            logger.info("AI model does not confirm BUY signal.")
            return False
    except Exception as e:
        logger.error(f"Error during AI prediction: {e}")
        return False
