import os
import numpy as np
import pandas as pd
import pandas_ta as ta
from logger import get_logger
from ai_signal_generator import get_ai_signal

logger = get_logger(__name__)

# Read signal-specific parameters from environment variables
VOLUME_SMA_PERIOD = int(os.getenv('VOLUME_SMA_PERIOD', 20))
EXIT_EMA_PERIOD = int(os.getenv('EXIT_EMA_PERIOD', 9))
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

def check_buy_signal(candles_primary, candles_trend):
    """
    Checks for buy signal using Multi-Timeframe Analysis.
    Primary candles are for entry signals, trend candles are for trend confirmation.
    """
    # --- Data Validation ---
    def is_valid_candle(c):
        # Checks if candle is a list of 6, and OHLCV are numeric
        return isinstance(c, list) and len(c) == 6 and all(isinstance(val, (int, float)) for val in c[1:])

    if not all(is_valid_candle(c) for c in candles_primary):
        logger.warning("Malformed or incomplete primary candle data received. Skipping signal check.")
        return False, "Malformed primary candle data"
    if not all(is_valid_candle(c) for c in candles_trend):
        logger.warning("Malformed or incomplete trend candle data received. Skipping signal check.")
        return False, "Malformed trend candle data"
    # --- End Validation ---

    if len(candles_primary) < 50 or len(candles_trend) < 50:
        return False, "Not enough candle data for full analysis."

    # --- Robust Data Cleaning ---
    df_primary = pd.DataFrame(candles_primary, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
    df_trend = pd.DataFrame(candles_trend, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
    
    for df in [df_primary, df_trend]:
        for col in ['open', 'high', 'low', 'close', 'volume']:
            df[col] = pd.to_numeric(df[col], errors='coerce')
        df.dropna(inplace=True)

    # Re-check length after cleaning
    if len(df_primary) < 50 or len(df_trend) < 50:
        return False, "Not enough valid candle data after cleaning."
    
    # --- 1. Pre-filter: Exclude very low volatility markets on primary timeframe ---
    atr = ta.atr(df_primary['high'], df_primary['low'], df_primary['close'], length=14)
    # Validate ATR calculation before use
    if atr is None or atr.empty or pd.isna(atr.iloc[-1]):
        return False, "Could not calculate ATR for pre-filter."
    
    atr_percent = (atr.iloc[-1] / df_primary['close'].iloc[-1]) * 100
    if atr_percent < 0.1:
        return False, f"Market too choppy (ATR: {atr_percent:.3f}%)"

    # --- 2. Strategy Conditions ---
    # Calculate all indicators first
    long_ema_trend = ta.ema(df_trend['close'], length=TREND_EMA_PERIOD)
    volume_sma = df_primary['volume'].rolling(window=VOLUME_SMA_PERIOD).mean().iloc[-1]
    rsi = ta.rsi(df_primary['close'], length=14)
    
    # --- Validate Indicators ---
    if long_ema_trend is None or long_ema_trend.empty or pd.isna(long_ema_trend.iloc[-1]):
        return False, "Could not calculate trend EMA."
    if pd.isna(volume_sma):
        return False, "Could not calculate volume SMA."
    if rsi is None or rsi.empty or pd.isna(rsi.iloc[-1]):
        return False, "Could not calculate RSI."
    
    # --- Apply Strategy Conditions ---
    # Condition 1: Current price on 5m frame > EMA(50) on 1h frame (Uptrend)
    trend_ok = df_primary['close'].iloc[-1] > long_ema_trend.iloc[-1]

    # Condition 2: RSI between 55 and 70 (Positive momentum without overbought)
    latest_rsi = rsi.iloc[-1]
    rsi_ok = BUY_RSI_LEVEL < latest_rsi < BUY_RSI_UPPER_LEVEL

    # Condition 3: Current trading volume >= 80% of SMA(20) of trading volume
    latest_volume = df_primary['volume'].iloc[-1]
    volume_ok = latest_volume >= (volume_sma * 0.8)

    # Condition 4: AI signal generator returns "buy"
    ai_buy_ok, _ = get_ai_signal(candles_primary)
    
    # --- 3. Final Decision & Reason ---
    all_conditions_met = trend_ok and rsi_ok and volume_ok and ai_buy_ok
    
    # Build the reason string for the UI
    reason_str = (
        f"Price(5m) > EMA({TREND_EMA_PERIOD})(1h): {'✅' if trend_ok else '❌'} (Price: {df_primary['close'].iloc[-1]:.4f}, EMA: {long_ema_trend.iloc[-1]:.4f}) | "
        f"{BUY_RSI_LEVEL} < RSI < {BUY_RSI_UPPER_LEVEL}: {'✅' if rsi_ok else '❌'} (Current: {latest_rsi:.2f}) | "
        f"Volume(5m) >= 80% SMA({VOLUME_SMA_PERIOD}): {'✅' if volume_ok else '❌'} (Latest: {latest_volume:.2f}, SMA: {volume_sma:.2f}) | "
        f"AI Buy Signal: {'✅' if ai_buy_ok else '❌'}"
    )

    if all_conditions_met:
        logger.info(f"BUY SIGNAL: {reason_str}")
        return True, reason_str
    else:
        logger.info(f"No Buy Signal: {reason_str}")
        return False, reason_str

def check_sell_signal(candles):
    """
    Checks for multiple sell conditions and returns a detailed breakdown.
    """
    # --- Data Validation ---
    def is_valid_candle(c):
        # Checks if candle is a list of 6, and OHLCV are numeric
        return isinstance(c, list) and len(c) == 6 and all(isinstance(val, (int, float)) for val in c[1:])

    if not all(is_valid_candle(c) for c in candles):
        logger.warning("Malformed or incomplete candle data received for sell check.")
        return False, "Malformed candle data"
    if len(candles) < 50: # Need enough for all indicators
        return False, "Not enough candles for full sell analysis."

    # --- Robust Data Cleaning ---
    df = pd.DataFrame(candles, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
    for col in ['open', 'high', 'low', 'close', 'volume']:
        df[col] = pd.to_numeric(df[col], errors='coerce')
    df.dropna(inplace=True)

    # Re-check length after cleaning
    if len(df) < 50:
        return False, "Not enough valid candles after cleaning data."

    # --- Calculate all sell indicators ---
    short_ema = ta.ema(df['close'], length=EXIT_EMA_PERIOD)
    rsi = ta.rsi(df['close'], length=14)
    
    # --- Validate Indicators ---
    if short_ema is None or short_ema.empty or pd.isna(short_ema.iloc[-1]):
        return False, "Could not calculate exit EMA."
    if rsi is None or rsi.empty or pd.isna(rsi.iloc[-1]):
        return False, "Could not calculate RSI for sell."

    # Condition 1: Reversal Pattern
    reversal_pattern_met = check_three_bearish_candles(candles)

    # Confirmation for Reversal Pattern: RSI < 50 OR Current Price < EMA(9)
    rsi_confirms_reversal = rsi.iloc[-1] < 50
    price_below_ema_confirms_reversal = df['close'].iloc[-1] < short_ema.iloc[-1]
    reversal_confirmation_met = rsi_confirms_reversal or price_below_ema_confirms_reversal

    # Combined Reversal Condition
    full_reversal_ok = reversal_pattern_met and reversal_confirmation_met

    # Condition 2: AI Sell Signal
    _, ai_sell_ok = get_ai_signal(candles)
    
    # --- Final Decision & Reason ---
    # Sell signal if EITHER Reversal Pattern OR AI Sell Signal is met
    any_condition_met = full_reversal_ok or ai_sell_ok
    
    reason_str = (
        f"Reversal Pattern (3 bearish candles + >=1% drop): {'✅' if reversal_pattern_met else '❌'} | "
        f"Reversal Confirmation (RSI < 50 OR Price < EMA({EXIT_EMA_PERIOD})): {'✅' if reversal_confirmation_met else '❌'} (RSI: {rsi.iloc[-1]:.2f}, Price: {df['close'].iloc[-1]:.4f}, EMA: {short_ema.iloc[-1]:.4f}) | "
        f"AI Sell Signal: {'✅' if ai_sell_ok else '❌'}"
    )

    if any_condition_met:
        logger.info(f"SELL SIGNAL: {reason_str}")
        return True, reason_str
    else:
        logger.info(f"No Sell Signal: {reason_str}")
        return False, reason_str

def check_three_bearish_candles(candles: list) -> bool:
    """
    Checks for a 3-candle bearish reversal pattern on the 5-minute timeframe.
    Conditions:
    1. Last 3 candles: each closed lower than the previous.
    2. Last 3 candles: each has a lower low than the previous.
    3. Total drop from the first to the third candle >= 1%.
    """
    if len(candles) < 3:
        return False

    # Get the last 3 candles
    # Ensure candles are sorted by timestamp in ascending order
    # Assuming candles are already in ascending order (oldest to newest)
    c1 = candles[-3] # Oldest of the three
    c2 = candles[-2] # Middle
    c3 = candles[-1] # Latest

    # Extract close and low prices
    # Ensure these are numeric
    try:
        c1_close, c1_low = float(c1[4]), float(c1[3])
        c2_close, c2_low = float(c2[4]), float(c2[3])
        c3_close, c3_low = float(c3[4]), float(c3[3])
    except (ValueError, IndexError):
        logger.warning("Invalid candle data format for bearish candle check.")
        return False

    # Condition 1: Each candle closed lower than the previous
    closes_lower = (c3_close < c2_close) and (c2_close < c1_close)

    # Condition 2: Each candle has a lower low than the previous
    lows_lower = (c3_low < c2_low) and (c2_low < c1_low)

    # Condition 3: Total drop from the first to the third candle >= 1%
    # Calculate drop from the open of the first candle to the close of the third candle
    # Or from the close of the first candle to the close of the third candle
    # The request says "مجموع الانخفاض من الشمعة الأولى إلى الثالثة ≥ 1%."
    # This implies (oldest_close - latest_close) / oldest_close >= 0.01
    if c1_close == 0: # Avoid division by zero
        percentage_drop_ok = False
    else:
        percentage_drop = (c1_close - c3_close) / c1_close
        percentage_drop_ok = percentage_drop >= REVERSAL_DROP_PERCENTAGE

    return closes_lower and lows_lower and percentage_drop_ok

def check_sl_tp(current_price, position_state, sl_price, tp_price, trailing_sl_price, trailing_tp_activation_price):
    """
    Checks for Stop Loss, Take Profit, or Trailing Take Profit conditions using absolute prices.
    """
    if not position_state["has_position"]:
        return None, None

    entry_price = position_state["position"]["entry_price"]
    highest_price = position_state["position"].get("highest_price_after_tp", entry_price)

    # Stop Loss Check
    if sl_price is not None and current_price <= sl_price:
        logger.info(f"Stop Loss triggered at {current_price:.4f} (SL price: {sl_price:.4f})")
        return "SL", sl_price

    # Trailing Take Profit Logic
    is_trailing_active = trailing_tp_activation_price is not None and current_price > trailing_tp_activation_price

    if is_trailing_active:
        if trailing_sl_price is not None and current_price < trailing_sl_price:
            pnl = ((current_price - entry_price) / entry_price) * 100
            logger.info(f"Trailing Take Profit triggered at {current_price:.4f}. "
                        f"Highest price was {highest_price:.4f}. PnL: {pnl:.2f}%")
            return "TTP", current_price
    else:
        # Regular Take Profit Check (only if trailing is not active)
        if tp_price is not None and current_price >= tp_price:
            logger.info(f"Take Profit triggered at {current_price:.4f} (TP price: {tp_price:.4f})")
            return "TP", tp_price

    return None, None
