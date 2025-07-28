from logger import get_logger

logger = get_logger(__name__)

def check_buy_signal(candles):
    """
    Checks for a 3-candle uptrend pattern.
    Candles are [timestamp, open, high, low, close].
    """
    if len(candles) < 3:
        return False

    c1, c2, c3 = candles[-3:]
    
    # Deconstruct candles for readability
    _, _, high1, low1, close1 = c1
    _, _, high2, low2, close2 = c2
    _, _, high3, low3, close3 = c3

    # Price action rules for a stronger BUY signal (3-candle confirmation)
    is_strong_uptrend = (
        close1 < close2 < close3 and  # Closing prices are successively higher
        low1 < low2 < low3 and        # Lows are successively higher
        high1 < high2 < high3         # Highs are successively higher
    )

    if is_strong_uptrend:
        logger.info("Strong 3-candle buy signal detected.")
    
    return is_strong_uptrend

def check_sell_signal(candles):
    """
    Checks for a 3-candle downtrend pattern for trend reversal.
    """
    if len(candles) < 3:
        return False

    c1, c2, c3 = candles[-3:]

    # Deconstruct candles
    _, _, high1, low1, close1 = c1
    _, _, high2, low2, close2 = c2
    _, _, high3, low3, close3 = c3

    # Price action rules for a stronger SELL signal (3-candle confirmation)
    is_strong_downtrend = (
        close1 > close2 > close3 and  # Closing prices are successively lower
        low1 > low2 > low3 and        # Lows are successively lower
        high1 > high2 > high3         # Highs are successively lower
    )

    if is_strong_downtrend:
        logger.info("Strong 3-candle sell signal (downtrend) detected.")

    return is_strong_downtrend

def check_sl_tp(current_price, position_state, sl_percent, tp_percent, trailing_tp_percent, trailing_tp_activation_percent):
    """
    Checks for Stop Loss, Take Profit, or Trailing Take Profit conditions.
    """
    if not position_state["has_position"]:
        return None, None

    entry_price = position_state["position"]["entry_price"]
    highest_price = position_state["position"].get("highest_price", entry_price)

    # Stop Loss Check
    sl_price = entry_price * (1 - sl_percent / 100)
    if current_price <= sl_price:
        logger.info(f"Stop Loss triggered at {current_price:.4f} (SL price: {sl_price:.4f})")
        return "SL", sl_price

    # Trailing Take Profit Logic
    activation_price = entry_price * (1 + trailing_tp_activation_percent / 100)
    is_trailing_active = current_price > activation_price

    # If trailing TP is active, it takes precedence over the fixed TP.
    if is_trailing_active:
        # Define the trailing stop price based on the highest price reached
        trailing_sl_price = highest_price * (1 - trailing_tp_percent / 100)
        
        # Check if the current price has dropped below the trailing stop price
        if current_price < trailing_sl_price:
            pnl = ((current_price - entry_price) / entry_price) * 100
            logger.info(f"Trailing Take Profit triggered at {current_price:.4f}. "
                        f"Highest price was {highest_price:.4f}. PnL: {pnl:.2f}%")
            return "TTP", current_price # TTP for Trailing Take Profit
    
    # Standard Take Profit Check (only if trailing is not yet active)
    else:
        tp_price = entry_price * (1 + tp_percent / 100)
        if current_price >= tp_price:
            logger.info(f"Take Profit triggered at {current_price:.4f} (TP price: {tp_price:.4f})")
            return "TP", tp_price

    return None, None
