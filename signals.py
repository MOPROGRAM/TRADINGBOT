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

def is_valid_candle(c):
    # Checks if candle is a list of 6, and OHLCV are numeric.
    # Also checks for None values in the numeric parts.
    return isinstance(c, list) and len(c) == 6 and \
           all(isinstance(val, (int, float)) and val is not None for val in c[1:])

def check_buy_signal(candles_primary, candles_15min, candles_trend):
    """
    Checks for buy signal using Multi-Timeframe Analysis.
    Primary candles are for entry signals (5-min), candles_15min for 15-min trend,
    and candles_trend for 1-hour trend confirmation.
    """
    analysis_details = []

    # Filter out invalid candles early
    candles_primary = [c for c in candles_primary if is_valid_candle(c)]
    candles_15min = [c for c in candles_15min if is_valid_candle(c)]
    candles_trend = [c for c in candles_trend if is_valid_candle(c)]

    # Data validation for primary candles
    if not candles_primary or len(candles_primary) < max(VOLUME_SMA_PERIOD, TREND_EMA_PERIOD, 100):
        reason = f"Insufficient primary candles ({len(candles_primary)}) for buy signal analysis."
        logger.warning(reason)
        return False, reason

    df_primary = pd.DataFrame(candles_primary, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
    for col in ['high', 'low', 'close']:
        df_primary[col] = pd.to_numeric(df_primary[col], errors='coerce')
    df_primary.dropna(subset=['high', 'low', 'close'], inplace=True)

    if len(df_primary) < max(VOLUME_SMA_PERIOD, TREND_EMA_PERIOD, 100):
        reason = f"Insufficient valid primary candles ({len(df_primary)}) after cleaning for buy signal analysis."
        logger.warning(reason)
        return False, reason

    # Data validation for 15-min candles
    if not candles_15min or len(candles_15min) < TREND_EMA_PERIOD:
        reason = f"Insufficient 15-min candles ({len(candles_15min)}) for buy signal analysis."
        logger.warning(reason)
        return False, reason

    df_15min = pd.DataFrame(candles_15min, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
    for col in ['high', 'low', 'close']:
        df_15min[col] = pd.to_numeric(df_15min[col], errors='coerce')
    df_15min.dropna(subset=['high', 'low', 'close'], inplace=True)

    if len(df_15min) < TREND_EMA_PERIOD:
        reason = f"Insufficient valid 15-min candles ({len(df_15min)}) after cleaning for buy signal analysis."
        logger.warning(reason)
        return False, reason

    # Data validation for trend candles
    if not candles_trend or len(candles_trend) < TREND_EMA_PERIOD:
        reason = f"Insufficient trend candles ({len(candles_trend)}) for buy signal analysis."
        logger.warning(reason)
        return False, reason

    df_trend = pd.DataFrame(candles_trend, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
    for col in ['high', 'low', 'close']:
        df_trend[col] = pd.to_numeric(df_trend[col], errors='coerce')
    df_trend.dropna(subset=['high', 'low', 'close'], inplace=True)

    if len(df_trend) < TREND_EMA_PERIOD:
        reason = f"Insufficient valid trend candles ({len(df_trend)}) after cleaning for buy signal analysis."
        logger.warning(reason)
        return False, reason

    # Calculate Indicators for Primary Timeframe
    df_primary['rsi'] = ta.rsi(df_primary['close'], length=14)
    df_primary['ema_short'] = ta.ema(df_primary['close'], length=EXIT_EMA_PERIOD_SHORT) # Using EXIT_EMA_PERIOD_SHORT for buy signal short EMA
    df_primary['ema_long'] = ta.ema(df_primary['close'], length=EXIT_EMA_PERIOD_LONG) # Using EXIT_EMA_PERIOD_LONG for buy signal long EMA

    last_close_primary = df_primary['close'].iloc[-1]
    last_rsi_primary = df_primary['rsi'].iloc[-1]
    last_ema_short_primary = df_primary['ema_short'].iloc[-1]
    last_ema_long_primary = df_primary['ema_long'].iloc[-1]

    prev_ema_short_primary = df_primary['ema_short'].iloc[-2]
    prev_ema_long_primary = df_primary['ema_long'].iloc[-2]

    # Calculate Trend EMA for 15-min and 1-hour timeframes
    df_15min['ema_trend'] = ta.ema(df_15min['close'], length=TREND_EMA_PERIOD)
    df_trend['ema_trend'] = ta.ema(df_trend['close'], length=TREND_EMA_PERIOD)

    last_ema_trend_15min = df_15min['ema_trend'].iloc[-1]
    last_ema_trend_1h = df_trend['ema_trend'].iloc[-1]

    buy_signal_triggered = False

    # Condition 1: RSI within buy range
    if BUY_RSI_LEVEL < last_rsi_primary < BUY_RSI_UPPER_LEVEL:
        buy_signal_triggered = True
        analysis_details.append(f"Primary RSI ({last_rsi_primary:.2f}) is within buy range ({BUY_RSI_LEVEL}-{BUY_RSI_UPPER_LEVEL})")

    # Condition 2: EMA Crossover (short EMA crosses above long EMA) on primary timeframe
    if prev_ema_short_primary < prev_ema_long_primary and last_ema_short_primary > last_ema_long_primary:
        buy_signal_triggered = True
        analysis_details.append(f"Primary EMA Short ({last_ema_short_primary:.4f}) crossed above EMA Long ({last_ema_long_primary:.4f})")

    # Condition 3: Price above Trend EMA on multiple timeframes (confirmation of uptrend)
    if last_close_primary > last_ema_trend_15min and last_close_primary > last_ema_trend_1h:
        if not buy_signal_triggered: # Only add if not already triggered by other conditions
            buy_signal_triggered = True
            analysis_details.append(f"Price ({last_close_primary:.4f}) is above 15-min Trend EMA ({last_ema_trend_15min:.4f}) and 1-hour Trend EMA ({last_ema_trend_1h:.4f})")
        else:
            analysis_details.append(f"Confirmed by Price ({last_close_primary:.4f}) above 15-min Trend EMA ({last_ema_trend_15min:.4f}) and 1-hour Trend EMA ({last_ema_trend_1h:.4f})")

    if buy_signal_triggered:
        return True, " | ".join(analysis_details)
    else:
        return False, "No buy signal."

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
