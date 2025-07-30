import numpy as np
import pandas as pd
import pandas_ta as ta
from logger import get_logger

logger = get_logger(__name__)

def check_buy_signal(candles, volume_sma_period=10):
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

    # --- 2. Core Conditions (Old Strategy) ---
    # Price Action Check
    c1_close, c2_close, c3_close = df['close'].iloc[-3:]
    c1_low, c2_low, c3_low = df['low'].iloc[-3:]
    price_action_ok = (c1_close < c2_close < c3_close and c1_low < c2_low < c3_low)

    # Volume Check
    volume_sma = df['volume'].rolling(window=volume_sma_period).mean().iloc[-1]
    latest_volume = df['volume'].iloc[-1]
    volume_ok = latest_volume > (volume_sma * 0.8)

    # --- 3. Confirmation Filters (New Strategy) ---
    # Breakout Check
    last_10_high = df['high'].iloc[-11:-1].max()
    breakout_ok = df['close'].iloc[-1] > last_10_high

    # RSI Check
    rsi = ta.rsi(df['close'], length=14)
    rsi_ok = rsi.iloc[-1] > 50

    # MACD Check
    macd = ta.macd(df['close'])
    macd_hist_ok = macd['MACDh_12_26_9'].iloc[-1] > 0

    # --- 4. Final Decision & Reason ---
    core_conditions_met = price_action_ok and volume_ok
    
    # Build the reason string for the UI
    reason_str = (
        f"Core: [Price {'OK' if price_action_ok else 'FAIL'} | Vol {'OK' if volume_ok else 'FAIL'}] | "
        f"Confirm: [Breakout {'OK' if breakout_ok else 'NO'} | "
        f"RSI>50 {'OK' if rsi_ok else 'NO'} | "
        f"MACD>0 {'OK' if macd_hist_ok else 'NO'}]"
    )

    if core_conditions_met:
        logger.info(f"BUY SIGNAL: {reason_str}")
        return True, reason_str
    else:
        logger.info(f"No Buy Signal: {reason_str}")
        return False, reason_str

def check_sell_signal(candles, exit_ema_period=7):
    """
    Checks for two sell conditions:
    1. A sharp 3-candle downtrend pattern for trend reversal.
    2. Price closing below a short-term EMA, indicating loss of momentum.
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

    # --- Condition 2: Price Below Short-Term EMA (Loss of Momentum) ---
    if len(candles) < exit_ema_period:
        logger.warning(f"Not enough candles for exit EMA ({exit_ema_period}). Skipping this check.")
        return False, f"Not enough candles for EMA (need >= {exit_ema_period})"

    weights = np.exp(np.linspace(-1., 0., exit_ema_period))
    weights /= weights.sum()
    ema = np.convolve(closes, weights, mode='full')[:len(closes)]
    ema[:exit_ema_period] = ema[exit_ema_period]
    
    latest_ema = ema[-1]
    
    if closes[-1] < latest_ema:
        reason = f"SELL SIGNAL: Price ({closes[-1]:.4f}) crossed below {exit_ema_period}-EMA ({latest_ema:.4f})."
        logger.info(reason)
        return True, reason

    return False, "No sell condition met"

def check_sl_tp(current_price, position_state, sl_percent, tp_percent, trailing_tp_percent, trailing_tp_activation_percent, trailing_sl_percent):
    """
    Checks for Stop Loss, Take Profit, or Trailing Take Profit conditions.
    """
    if not position_state["has_position"]:
        return None, None

    entry_price = position_state["position"]["entry_price"]
    # Use 'highest_price_after_tp' to match the key set in bot.py
    highest_price = position_state["position"].get("highest_price_after_tp", entry_price)

    # Stop Loss Check
    sl_price = entry_price * (1 - sl_percent / 100)
    if current_price <= sl_price:
        logger.info(f"Stop Loss triggered at {current_price:.4f} (SL price: {sl_price:.4f})")
        return "SL", sl_price

    # Trailing Take Profit Logic
    activation_price = entry_price * (1 + trailing_tp_activation_percent / 100)
    is_trailing_active = current_price > activation_price

    if is_trailing_active:
        # Correctly use the trailing_sl_percent parameter for the calculation
        trailing_sl_price = highest_price * (1 - trailing_sl_percent / 100)
        
        if current_price < trailing_sl_price:
            pnl = ((current_price - entry_price) / entry_price) * 100
            logger.info(f"Trailing Take Profit triggered at {current_price:.4f}. "
                        f"Highest price was {highest_price:.4f}. PnL: {pnl:.2f}%")
            return "TTP", current_price
    
    else:
        tp_price = entry_price * (1 + tp_percent / 100)
        if current_price >= tp_price:
            logger.info(f"Take Profit triggered at {current_price:.4f} (TP price: {tp_price:.4f})")
            return "TP", tp_price

    return None, None
