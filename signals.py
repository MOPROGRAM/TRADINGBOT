import os
import numpy as np
import pandas as pd
import pandas_ta as ta
from logger import get_logger

logger = get_logger(__name__)

# Read signal-specific parameters from environment variables
VOLUME_SMA_PERIOD = int(os.getenv('VOLUME_SMA_PERIOD', 20))
EXIT_EMA_PERIOD = int(os.getenv('EXIT_EMA_PERIOD', 9))
TREND_EMA_PERIOD = int(os.getenv('TREND_EMA_PERIOD', 50))
EXIT_RSI_LEVEL = int(os.getenv('EXIT_RSI_LEVEL', 65))

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
    atr = ta.atr(df['high'], df['low'], df['close'], length=period)
    return atr.iloc[-1] if not atr.empty else None



def check_buy_signal(candles):
    """
    Checks for a 3-candle uptrend pattern confirmed by high volume.
    Candles are [timestamp, open, high, low, close, volume].
    """
    # --- Data Validation ---
    if not all(isinstance(c, list) and len(c) == 6 for c in candles):
        logger.warning("Malformed candle data received. Skipping signal check.")
        return False, "Malformed candle data"
    # --- End Validation ---

    if len(candles) < 50: # Need enough data for indicators
        return False, "Not enough candle data for full analysis."

    # Convert to DataFrame for pandas_ta
    df = pd.DataFrame(candles, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
    
    # --- 1. Pre-filter: Exclude very low volatility markets ---
    # Calculate Average True Range (ATR) as a percentage of the closing price
    atr = ta.atr(df['high'], df['low'], df['close'], length=14)
    atr_percent = (atr.iloc[-1] / df['close'].iloc[-1]) * 100
    if atr_percent < 0.1: # If ATR is less than 0.1% of the price, market is too flat
        return False, f"Market too choppy (ATR: {atr_percent:.3f}%)"

    # --- 2. New Strategy Conditions ---
    # Condition 1: Trend Filter (Price must be above a long-term EMA)
    long_ema = ta.ema(df['close'], length=TREND_EMA_PERIOD)
    trend_ok = df['close'].iloc[-1] > long_ema.iloc[-1]

    # Condition 2: Price Action (3-candle uptrend)
    c1_close, c2_close, c3_close = df['close'].iloc[-3:]
    c1_low, c2_low, c3_low = df['low'].iloc[-3:]
    price_action_ok = (c1_close < c2_close < c3_close and c1_low < c2_low < c3_low)

    # Condition 3: Volume Confirmation
    volume_sma = df['volume'].rolling(window=VOLUME_SMA_PERIOD).mean().iloc[-1]
    latest_volume = df['volume'].iloc[-1]
    volume_ok = latest_volume > (volume_sma * 0.8)

    # --- 3. Final Decision & Reason ---
    all_conditions_met = trend_ok and price_action_ok and volume_ok
    
    # Build the reason string for the UI
    reason_str = (
        f"Trend > EMA({TREND_EMA_PERIOD}): {'✅' if trend_ok else '❌'} | "
        f"Price Action: {'✅' if price_action_ok else '❌'} | "
        f"Volume: {'✅' if volume_ok else '❌'}"
    )

    if all_conditions_met:
        logger.info(f"BUY SIGNAL: {reason_str}")
        return True, reason_str
    else:
        logger.info(f"No Buy Signal: {reason_str}")
        return False, reason_str

def check_sell_signal(candles):
    """
    Checks for two sell conditions:
    1. A sharp 3-candle downtrend pattern for trend reversal.
    2. Price closing below a short-term EMA, confirmed by RSI, indicating loss of momentum.
    """
    # --- Data Validation ---
    if not all(isinstance(c, list) and len(c) == 6 for c in candles):
        logger.warning("Malformed candle data received. Skipping signal check.")
        return False, "Malformed candle data"
    # --- End Validation ---

    if len(candles) < 3:
        return False, "Not enough candles for sell check (need >= 3)"

    closes = np.array([c[4] for c in candles])
    lows = np.array([c[3] for c in candles])

    # --- Condition 1: Strong 3-Candle Reversal ---
    c1_close, c2_close, c3_close = closes[-3:]
    c1_low, c2_low, c3_low = lows[-3:]

    is_strong_downtrend = (
        c1_close > c2_close > c3_close and
        c1_low > c2_low > c3_low
    )

    if is_strong_downtrend:
        reason = f"SELL SIGNAL: Strong 3-candle reversal (Closes: {c1_close:.4f} > {c2_close:.4f} > {c3_close:.4f})"
        logger.info(reason)
        return True, reason

    # --- Condition 2: Price Below Short-Term EMA & RSI Confirmation ---
    if len(candles) >= EXIT_EMA_PERIOD:
        df = pd.DataFrame(candles, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        
        # Calculate short-term EMA
        short_ema = ta.ema(df['close'], length=EXIT_EMA_PERIOD)
        latest_ema = short_ema.iloc[-1]
        
        # Calculate RSI
        rsi = ta.rsi(df['close'], length=14)
        latest_rsi = rsi.iloc[-1]

        price_below_ema = df['close'].iloc[-1] < latest_ema
        rsi_confirms = latest_rsi < EXIT_RSI_LEVEL

        if price_below_ema and rsi_confirms:
            reason = (f"SELL SIGNAL: Price < {EXIT_EMA_PERIOD}-EMA ({df['close'].iloc[-1]:.4f} < {latest_ema:.4f}) "
                      f"& RSI < {EXIT_RSI_LEVEL} ({latest_rsi:.1f})")
            logger.info(reason)
            return True, reason

    return False, "No sell condition met"

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
