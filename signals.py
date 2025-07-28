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

def check_sl_tp(current_price, position, sl_percent, tp_percent):
    """
    Checks for Stop Loss or Take Profit conditions.
    """
    if not position["has_position"]:
        return None, None

    entry_price = position["position"]["entry_price"]
    
    # Stop Loss Check
    sl_price = entry_price * (1 - sl_percent / 100)
    if current_price <= sl_price:
        logger.info(f"Stop Loss triggered at {current_price:.4f} (SL price: {sl_price:.4f})")
        return "SL", sl_price

    # Take Profit Check
    tp_price = entry_price * (1 + tp_percent / 100)
    if current_price >= tp_price:
        logger.info(f"Take Profit triggered at {current_price:.4f} (TP price: {tp_price:.4f})")
        return "TP", tp_price

    return None, None
