from logger import get_logger

logger = get_logger(__name__)

def check_buy_signal(candles):
    """
    Checks for a 2-candle uptrend pattern.
    Candles are [timestamp, open, high, low, close].
    """
    if len(candles) < 2:
        return False

    c1, c2 = candles[-2:]
    
    # Deconstruct candles for readability
    _, _, high1, low1, close1 = c1
    _, _, high2, low2, close2 = c2

    # Price action rules for BUY
    is_uptrend = (
        close1 < close2 and
        high1 < high2 and
        low1 < low2
    )

    if is_uptrend:
        logger.info("Buy signal detected.")
    
    return is_uptrend

def check_sell_signal(candles):
    """
    Checks for a 2-candle downtrend pattern.
    """
    if len(candles) < 2:
        return False

    c1, c2 = candles[-2:]

    # Deconstruct candles
    _, _, high1, low1, close1 = c1
    _, _, high2, low2, close2 = c2

    # Price action rules for SELL
    is_downtrend = (
        close1 > close2 and
        high1 > high2 and
        low1 > low2
    )

    if is_downtrend:
        logger.info("Sell signal (downtrend) detected.")

    return is_downtrend

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

    # Standard Take Profit Check
    tp_price = entry_price * (1 + tp_percent / 100)
    if current_price >= tp_price:
        logger.info(f"Take Profit triggered at {current_price:.4f} (TP price: {tp_price:.4f})")
        return "TP", tp_price

    # Trailing Take Profit Logic
    # 1. Check if trailing TP is activated
    activation_price = entry_price * (1 + trailing_tp_activation_percent / 100)
    if current_price > activation_price:
        # 2. Define the trailing stop price based on the highest price reached
        trailing_sl_price = highest_price * (1 - trailing_tp_percent / 100)
        
        # 3. Check if the current price has dropped below the trailing stop price
        if current_price < trailing_sl_price:
            pnl = ((current_price - entry_price) / entry_price) * 100
            logger.info(f"Trailing Take Profit triggered at {current_price:.4f}. "
                        f"Highest price was {highest_price:.4f}. PnL: {pnl:.2f}%")
            return "TTP", current_price # TTP for Trailing Take Profit

    return None, None
