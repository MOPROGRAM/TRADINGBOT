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

def check_sell_signal(candles):
    """
    Checks for a sell signal based on RSI, EMA crossover, and price reversal.
    """
    analysis_details = []

    if not candles or len(candles) < max(EXIT_EMA_PERIOD_LONG, TREND_EMA_PERIOD, ATR_PERIOD, 100):
        reason = f"Insufficient candles ({len(candles)}) for sell signal analysis."
        logger.warning(reason)
        return False, reason

    df = pd.DataFrame(candles, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
    for col in ['high', 'low', 'close']:
        df[col] = pd.to_numeric(df[col], errors='coerce')
    df.dropna(subset=['high', 'low', 'close'], inplace=True)

    if len(df) < max(EXIT_EMA_PERIOD_LONG, TREND_EMA_PERIOD, ATR_PERIOD, 100):
        reason = f"Insufficient valid candles ({len(df)}) after cleaning for sell signal analysis."
        logger.warning(reason)
        return False, reason

    # Calculate Indicators
    df['rsi'] = ta.rsi(df['close'], length=14)
    df['ema_short'] = ta.ema(df['close'], length=EXIT_EMA_PERIOD_SHORT)
    df['ema_long'] = ta.ema(df['close'], length=EXIT_EMA_PERIOD_LONG)
    df['ema_trend'] = ta.ema(df['close'], length=TREND_EMA_PERIOD)

    last_close = df['close'].iloc[-1]
    last_rsi = df['rsi'].iloc[-1]
    last_ema_short = df['ema_short'].iloc[-1]
    last_ema_long = df['ema_long'].iloc[-1]
    last_ema_trend = df['ema_trend'].iloc[-1]

    prev_ema_short = df['ema_short'].iloc[-2]
    prev_ema_long = df['ema_long'].iloc[-2]

    sell_signal_triggered = False

    # Condition 1: RSI overbought exit
    if last_rsi > EXIT_RSI_LEVEL:
        sell_signal_triggered = True
        analysis_details.append(f"RSI ({last_rsi:.2f}) > Exit Level ({EXIT_RSI_LEVEL})")

    # Condition 2: EMA Crossover (short EMA crosses below long EMA)
    if prev_ema_short > prev_ema_long and last_ema_short < last_ema_long:
        sell_signal_triggered = True
        analysis_details.append(f"EMA Short ({last_ema_short:.4f}) crossed below EMA Long ({last_ema_long:.4f})")

    # Condition 3: Price below Trend EMA (confirmation of downtrend)
    if last_close < last_ema_trend:
        if not sell_signal_triggered: # Only add if not already triggered by other conditions
            sell_signal_triggered = True
            analysis_details.append(f"Price ({last_close:.4f}) is below Trend EMA ({last_ema_trend:.4f})")
        else:
            analysis_details.append(f"Confirmed by Price ({last_close:.4f}) below Trend EMA ({last_ema_trend:.4f})")

    # Condition 4: Reversal Drop from recent high
    # Look back a reasonable period for a recent high (e.g., 20 candles)
    lookback_period = 20
    if len(df) >= lookback_period:
        recent_high = df['high'].iloc[-lookback_period:-1].max()
        if recent_high and last_close < recent_high * (1 - REVERSAL_DROP_PERCENTAGE):
            sell_signal_triggered = True
            analysis_details.append(f"Price dropped {REVERSAL_DROP_PERCENTAGE*100:.1f}% from recent high ({recent_high:.4f})")

    if sell_signal_triggered:
        return True, " | ".join(analysis_details)
    else:
        return False, "No sell signal."

def check_sl_tp(current_price, state, sl_price, tp_price, trailing_sl_price, trailing_tp_activation_price):
    """
    Checks if Stop Loss (SL), Take Profit (TP), or Trailing Stop Loss (TSL) conditions are met.
    """
    if not state.get('has_position'):
        return None, "No position to check SL/TP."

    entry_price = state['position'].get('entry_price')
    if entry_price is None:
        return None, "Entry price not set in state."

    # Check Trailing Stop Loss first (if activated)
    if trailing_sl_price is not None and current_price <= trailing_sl_price:
        logger.info(f"Trailing Stop Loss triggered: Current Price {current_price:.4f} <= Trailing SL {trailing_sl_price:.4f}")
        return "TTP", "Trailing Stop Loss triggered."

    # Check Stop Loss
    if sl_price is not None and current_price <= sl_price:
        logger.info(f"Stop Loss triggered: Current Price {current_price:.4f} <= SL {sl_price:.4f}")
        return "SL", "Stop Loss triggered."

    # Check Take Profit
    if tp_price is not None and current_price >= tp_price:
        logger.info(f"Take Profit triggered: Current Price {current_price:.4f} >= TP {tp_price:.4f}")
        return "TP", "Take Profit triggered."

    return None, "No SL/TP/TSL triggered."
