import os
import numpy as np
import pandas as pd
import pandas_ta as ta
from logger import get_logger

logger = get_logger(__name__)

# Read signal-specific parameters from environment variables
VOLUME_SMA_PERIOD = int(os.getenv('VOLUME_SMA_PERIOD', 20))
EXIT_EMA_PERIOD_SHORT = int(os.getenv('EXIT_EMA_PERIOD_SHORT', 9))
EXIT_EMA_PERIOD_LONG = int(os.getenv('EXIT_EMA_PERIOD_LONG', 21))
TREND_EMA_PERIOD = int(os.getenv('TREND_EMA_PERIOD', 50))
EXIT_RSI_LEVEL = int(os.getenv('EXIT_RSI_LEVEL', 65))
BUY_RSI_LEVEL = int(os.getenv('BUY_RSI_LEVEL', 55))
BUY_RSI_UPPER_LEVEL = int(os.getenv('BUY_RSI_UPPER_LEVEL', 70)) # New RSI upper level for buy signal
REVERSAL_DROP_PERCENTAGE = float(os.getenv('REVERSAL_DROP_PERCENTAGE', 0.01)) # 1.0% drop for reversal confirmation (increased from 0.5%)

# ATR-based SL/TP parameters
ATR_PERIOD = int(os.getenv('ATR_PERIOD', 14))
ATR_SL_MULTIPLIER = float(os.getenv('ATR_SL_MULTIPLIER', 1.5))
ATR_TP_MULTIPLIER = float(os.getenv('ATR_TP_MULTIPLIER', 3.0))
ATR_TRAILING_TP_ACTIVATION_MULTIPLIER = float(os.getenv('ATR_TRAILING_TP_ACTIVATION_MULTIPLIER', 2.0))
ATR_TRAILING_SL_MULTIPLIER = float(os.getenv('ATR_TRAILING_SL_MULTIPLIER', 1.0))

def calculate_atr(candles, period=ATR_PERIOD):
    """
    Calculates the Average True Range (ATR) from candle data.
    """
    if len(candles) < period:
        logger.warning(f"Not enough candles ({len(candles)}) to calculate ATR for period {period}.")
        return None

    df = pd.DataFrame(candles, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
    # --- Robust Data Cleaning ---
    for col in ['high', 'low', 'close']:
        df[col] = pd.to_numeric(df[col], errors='coerce')
    df.dropna(subset=['high', 'low', 'close'], inplace=True)
    
    if len(df) < period:
        logger.warning(f"Not enough valid candles ({len(df)}) to calculate ATR after cleaning.")
        return None

    atr = ta.atr(df['high'], df['low'], df['close'], length=period)
    
    # Final validation of the result
    if atr is None or atr.empty or pd.isna(atr.iloc[-1]):
        return None
    
    return atr.iloc[-1]

def check_buy_signal(candles_primary, candles_15min, candles_trend):
    """
    Checks for buy signal using Multi-Timeframe Analysis.
    Primary candles are for entry signals (5-min), candles_15min for 15-min trend,
    and candles_trend for 1-hour trend confirmation.
    """
    # --- Data Validation ---
    def is_valid_candle(c):
        # Checks if candle is a list of 6, and OHLCV are numeric.
        # Also checks for None values in the numeric parts.
        return isinstance(c, list) and len(c) == 6 and \
               all(isinstance(val, (int, float)) and val is not None for val in c[1:])
