from logger import get_logger

logger = get_logger(__name__)

def check_buy_signal(candles, **kwargs):
    """
    A simplified buy signal that always returns True.
    """
    logger.info("Simplified buy signal: always returning True.")
    return True

def is_market_bullish(btc_candles, **kwargs):
    """
    A simplified market filter that always returns True.
    """
    logger.info("Simplified market filter: always returning True.")
    return True

def check_sell_signal(candles, **kwargs):
    """
    A simplified sell signal that always returns False.
    """
    return False

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

    if is_trailing_active:
        trailing_sl_price = highest_price * (1 - trailing_tp_percent / 100)
        
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
