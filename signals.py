import pandas as pd
import pandas_ta as ta
from logger import get_logger

logger = get_logger(__name__)

def check_buy_signal(candles, volume_sma_period=20):
    """
    Checks for a 3-candle uptrend pattern confirmed by high volume.
    Candles are [timestamp, open, high, low, close, volume].
    """
    if len(candles) < volume_sma_period + 1:
        logger.warning(f"Not enough candle data to calculate volume SMA (need > {volume_sma_period}).")
        return False

    # Create a DataFrame
    df = pd.DataFrame(candles, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
    
    # --- Price Action Check (3-candle uptrend) ---
    c1, c2, c3 = df.iloc[-3], df.iloc[-2], df.iloc[-1]
    
    price_action_signal = (
        c1['close'] < c2['close'] < c3['close'] and
        c1['low'] < c2['low'] < c3['low']
    )

    if not price_action_signal:
        return False # No need to check volume if price action fails

    # --- Volume Confirmation Check ---
    # Calculate the simple moving average of the volume
    df['volume_sma'] = ta.sma(df['volume'], length=volume_sma_period)
    
    # Get the latest volume and its SMA
    latest_volume = c3['volume']
    latest_volume_sma = df['volume_sma'].iloc[-1]

    volume_signal = latest_volume > latest_volume_sma

    if volume_signal:
        logger.info(f"Volume confirmation: Latest volume ({latest_volume:.2f}) > {volume_sma_period}-period SMA ({latest_volume_sma:.2f})")
    else:
        logger.info(f"Volume check failed: Latest volume ({latest_volume:.2f}) <= {volume_sma_period}-period SMA ({latest_volume_sma:.2f})")
        return False

    # If both price action and volume signals are true
    logger.info("BUY SIGNAL CONFIRMED: 3-candle uptrend with high volume.")
    return True

def is_market_bullish(btc_candles, ema_period=50):
    """
    Checks if the overall market is bullish based on a reference symbol's trend.
    A simple check: is the current price above the specified EMA period?
    """
    if len(btc_candles) < ema_period:
        logger.warning(f"Not enough market filter candle data to calculate EMA (need > {ema_period}).")
        return False # Default to neutral/bearish if not enough data

    df = pd.DataFrame(btc_candles, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
    
    # Calculate the Exponential Moving Average
    df['ema'] = ta.ema(df['close'], length=ema_period)
    
    # Get the latest close price and the latest EMA value
    latest_price = df['close'].iloc[-1]
    latest_ema = df['ema'].iloc[-1]
    
    is_bullish = latest_price > latest_ema
    
    if is_bullish:
        logger.info(f"Market Filter: BULLISH (BTC Price ${latest_price:.2f} > {ema_period}-EMA ${latest_ema:.2f})")
    else:
        logger.info(f"Market Filter: BEARISH (BTC Price ${latest_price:.2f} <= {ema_period}-EMA ${latest_ema:.2f})")
        
    return is_bullish

def check_sell_signal(candles, exit_ema_period=9):
    """
    Checks for two sell conditions:
    1. A sharp 3-candle downtrend pattern for trend reversal.
    2. Price closing below a short-term EMA, indicating loss of momentum.
    """
    if len(candles) < 3:
        return False # Not enough data for even the basic check

    # --- Condition 1: Strong 3-Candle Reversal ---
    c1, c2, c3 = candles[-3:]
    # Deconstruct the last candle for EMA check
    _, _, _, _, latest_close, _ = c3

    is_strong_downtrend = (
        c1[4] > c2[4] > c3[4] and  # Closing prices are successively lower
        c1[3] > c2[3] > c3[3]    # Lows are successively lower
    )

    if is_strong_downtrend:
        logger.info("SELL SIGNAL: Strong 3-candle reversal pattern detected.")
        return True

    # --- Condition 2: Price Below Short-Term EMA (Loss of Momentum) ---
    if len(candles) < exit_ema_period:
        logger.warning(f"Not enough candles for exit EMA ({exit_ema_period}). Skipping this check.")
        return False

    df = pd.DataFrame(candles, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
    df['exit_ema'] = ta.ema(df['close'], length=exit_ema_period)
    
    latest_ema = df['exit_ema'].iloc[-1]
    
    if latest_close < latest_ema:
        logger.info(f"SELL SIGNAL: Price ({latest_close:.4f}) crossed below {exit_ema_period}-EMA ({latest_ema:.4f}).")
        return True

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
