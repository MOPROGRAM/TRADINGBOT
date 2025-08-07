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

# ATR-based SL/TP parameters
ATR_PERIOD = int(os.getenv('ATR_PERIOD', 14))
ATR_SL_MULTIPLIER = float(os.getenv('ATR_SL_MULTIPLIER', 1.5))
ATR_TP_MULTIPLIER = float(os.getenv('ATR_TP_MULTIPLIER', 3.0))
ATR_TRAILING_TP_ACTIVATION_MULTIPLIER = float(os.getenv('ATR_TRAILING_TP_ACTIVATION_MULTIPLIER', 2.0))
ATR_TRAILING_SL_MULTIPLIER = float(os.getenv('ATR_TRAILING_SL_MULTIPLIER', 1.0))

# MACD Parameters
MACD_FAST_PERIOD = int(os.getenv('MACD_FAST_PERIOD', 12))
MACD_SLOW_PERIOD = int(os.getenv('MACD_SLOW_PERIOD', 26))
MACD_SIGNAL_PERIOD = int(os.getenv('MACD_SIGNAL_PERIOD', 9))

def calculate_atr(candles, period=ATR_PERIOD):
    """
    Calculates the Average True Range (ATR) from candle data.
    """
    if len(candles) < period:
        logger.warning(f"Not enough candles ({len(candles)}) to calculate ATR for period {period}.")
        return None

    df = pd.DataFrame(candles, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
    atr = ta.atr(df['high'], df['low'], df['close'], length=period)
    return atr.iloc[-1] if not atr.empty else None

def calculate_macd(candles, fast_period=MACD_FAST_PERIOD, slow_period=MACD_SLOW_PERIOD, signal_period=MACD_SIGNAL_PERIOD):
    """
    Calculates MACD, MACD Signal Line, and MACD Histogram.
    """
    if len(candles) < max(fast_period, slow_period, signal_period):
        logger.warning(f"Not enough candles ({len(candles)}) to calculate MACD.")
        return None, None, None

    df = pd.DataFrame(candles, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
    
    # Calculate MACD using pandas_ta
    macd_data = ta.macd(df['close'], fast=fast_period, slow=slow_period, signal=signal_period)
    
    if macd_data.empty:
        return None, None, None

    # The columns are typically named MACD_fast_slow_signal, MACDH_fast_slow_signal, MACDS_fast_slow_signal
    # Use .get() for safe access in case a column is missing
    last_row = macd_data.iloc[-1]
    macd_line = last_row.get(f'MACD_{fast_period}_{slow_period}_{signal_period}')
    macd_histogram = last_row.get(f'MACDH_{fast_period}_{slow_period}_{signal_period}')
    macd_signal = last_row.get(f'MACDS_{fast_period}_{slow_period}_{signal_period}')

    return macd_line, macd_signal, macd_histogram


def check_buy_signal(candles_primary, candles_trend):
    """
    Checks for buy signal using Multi-Timeframe Analysis.
    Primary candles are for entry signals, trend candles are for trend confirmation.
    """
    # --- Data Validation ---
    if not all(isinstance(c, list) and len(c) == 6 for c in candles_primary):
        logger.warning("Malformed primary candle data received. Skipping signal check.")
        return False, "Malformed primary candle data"
    if not all(isinstance(c, list) and len(c) == 6 for c in candles_trend):
        logger.warning("Malformed trend candle data received. Skipping signal check.")
        return False, "Malformed trend candle data"
    # --- End Validation ---

    if len(candles_primary) < 50 or len(candles_trend) < 50:
        return False, "Not enough candle data for full analysis."

    # Convert to DataFrames for pandas_ta
    df_primary = pd.DataFrame(candles_primary, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
    df_trend = pd.DataFrame(candles_trend, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
    
    # --- 1. Pre-filter: Exclude very low volatility markets on primary timeframe ---
    atr = ta.atr(df_primary['high'], df_primary['low'], df_primary['close'], length=14)
    atr_percent = (atr.iloc[-1] / df_primary['close'].iloc[-1]) * 100
    if atr_percent < 0.1:
        return False, f"Market too choppy (ATR: {atr_percent:.3f}%)"

    # --- 2. Strategy Conditions ---
    # Condition 1: Trend Filter (Price must be above a long-term EMA on the TREND timeframe)
    long_ema_trend = ta.ema(df_trend['close'], length=TREND_EMA_PERIOD)
    trend_ok = df_primary['close'].iloc[-1] > long_ema_trend.iloc[-1]

    # Condition 2: Volume Confirmation (on PRIMARY timeframe)
    volume_sma = df_primary['volume'].rolling(window=VOLUME_SMA_PERIOD).mean().iloc[-1]
    latest_volume = df_primary['volume'].iloc[-1]
    volume_ok = latest_volume > (volume_sma * 0.8)

    # Condition 3: RSI Confirmation for Buy (on PRIMARY timeframe)
    rsi = ta.rsi(df_primary['close'], length=14)
    latest_rsi = rsi.iloc[-1]
    rsi_ok = BUY_RSI_LEVEL < latest_rsi < BUY_RSI_UPPER_LEVEL

    # Condition 4: MACD Confirmation for Buy (on PRIMARY timeframe)
    macd_line, macd_signal, _ = calculate_macd(candles_primary)
    macd_ok = False
    if macd_line is not None and macd_signal is not None:
        # Check if MACD line is above the signal line (positive momentum)
        if macd_line > macd_signal:
            macd_ok = True

    # Condition 5: AI Confirmation
    ai_ok = get_ai_signal(candles_primary)
    
    # --- 3. Final Decision & Reason ---
    all_conditions_met = trend_ok and volume_ok and rsi_ok and macd_ok and ai_ok
    
    # Build the reason string for the UI
    reason_str = (
        f"Trend(1h) > EMA({TREND_EMA_PERIOD}): {'✅' if trend_ok else '❌'} | "
        f"Volume(5m): {'✅' if volume_ok else '❌'} | "
        f"{BUY_RSI_LEVEL} < RSI < {BUY_RSI_UPPER_LEVEL}: {'✅' if rsi_ok else '❌'} | "
        f"MACD > Signal: {'✅' if macd_ok else '❌'} | "
        f"AI Signal: {'✅' if ai_ok else '❌'}"
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
    if not all(isinstance(c, list) and len(c) == 6 for c in candles):
        logger.warning("Malformed candle data received for sell check.")
        return False, "Malformed candle data"
    if len(candles) < 50: # Need enough for all indicators
        return False, "Not enough candles for full sell analysis."

    df = pd.DataFrame(candles, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])

    # --- Calculate all sell indicators ---

    # Condition 1: Strong 3-Candle Reversal
    c1_close, c2_close, c3_close = df['close'].iloc[-3:]
    c1_low, c2_low, c3_low = df['low'].iloc[-3:]
    reversal_ok = (c1_close > c2_close > c3_close and c1_low > c2_low > c3_low)

    # Condition 2: Price Below Short-Term EMA & RSI Confirmation
    short_ema = ta.ema(df['close'], length=EXIT_EMA_PERIOD)
    rsi = ta.rsi(df['close'], length=14)
    price_below_ema = df['close'].iloc[-1] < short_ema.iloc[-1]
    rsi_confirms = rsi.iloc[-1] < EXIT_RSI_LEVEL
    ema_rsi_ok = price_below_ema and rsi_confirms

    # Condition 3: MACD Sell Signal (MACD line crosses below Signal line)
    macd_line, macd_signal, _ = calculate_macd(candles)
    macd_ok = False
    if macd_line is not None and macd_signal is not None and macd_line < macd_signal:
        macd_data_prev = ta.macd(df['close'].iloc[:-1], fast=MACD_FAST_PERIOD, slow=MACD_SLOW_PERIOD, signal=MACD_SIGNAL_PERIOD)
        if not macd_data_prev.empty:
            prev_last_row = macd_data_prev.iloc[-1]
            prev_macd_line = prev_last_row.get(f'MACD_{MACD_FAST_PERIOD}_{MACD_SLOW_PERIOD}_{MACD_SIGNAL_PERIOD}')
            prev_macd_signal = prev_last_row.get(f'MACDS_{MACD_FAST_PERIOD}_{MACD_SLOW_PERIOD}_{MACD_SIGNAL_PERIOD}')
            if prev_macd_line is not None and prev_macd_signal is not None and prev_macd_line >= prev_macd_signal:
                macd_ok = True

    # --- Final Decision & Reason ---
    any_condition_met = reversal_ok or ema_rsi_ok or macd_ok
    
    reason_str = (
        f"Reversal Pattern: {'✅' if reversal_ok else '❌'} | "
        f"Price < EMA({EXIT_EMA_PERIOD}) & RSI < {EXIT_RSI_LEVEL}: {'✅' if ema_rsi_ok else '❌'} | "
        f"MACD Crossover Down: {'✅' if macd_ok else '❌'}"
    )

    if any_condition_met:
        logger.info(f"SELL SIGNAL: {reason_str}")
        return True, reason_str
    else:
        logger.info(f"No Sell Signal: {reason_str}")
        return False, reason_str

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
