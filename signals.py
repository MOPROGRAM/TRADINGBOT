import numpy as np
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

    if len(candles) < volume_sma_period + 1:
        logger.warning(f"Not enough candle data to calculate volume SMA (need > {volume_sma_period}).")
        return False, f"Not enough candles for SMA (need > {volume_sma_period})"

    closes = np.array([c[4] for c in candles])
    lows = np.array([c[3] for c in candles])
    volumes = np.array([c[5] for c in candles])

    # --- Price Action Check (3-candle uptrend) ---
    c1_close, c2_close, c3_close = closes[-3:]
    c1_low, c2_low, c3_low = lows[-3:]

    price_action_signal = (
        c1_close < c2_close < c3_close and
        c1_low < c2_low < c3_low
    )

    # --- Volume Confirmation Check (More Active Strategy) ---
    volume_sma = np.mean(volumes[-(volume_sma_period):])
    latest_volume = volumes[-1]
    volume_threshold = volume_sma * 0.8
    volume_signal = latest_volume > volume_threshold

    # --- Combine Reasons for a Full Analysis ---
    reasons = []
    if not price_action_signal:
        reasons.append("Price action failed (no 3-candle uptrend)")
    else:
        reasons.append("Price action OK")

    if not volume_signal:
        reasons.append(f"Volume failed (Vol: {latest_volume:.2f} <= 80% SMA: {volume_threshold:.2f})")
    else:
        reasons.append("Volume OK")

    final_reason = " | ".join(reasons)

    # Final decision
    if price_action_signal and volume_signal:
        success_reason = f"BUY SIGNAL: 3-candle uptrend with volume confirmation (Vol: {latest_volume:.2f} > {volume_threshold:.2f})"
        logger.info(success_reason)
        return True, success_reason
    else:
        logger.info(f"No buy signal: {final_reason}")
        return False, final_reason

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
