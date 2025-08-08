import pandas as pd
import pandas_ta as ta
from logger import get_logger

logger = get_logger(__name__)

# Define periods for indicators (can be moved to environment variables if needed)
EMA_LONG_PERIOD = 50
EMA_SHORT_PERIOD = 9
RSI_PERIOD = 14
VOLUME_SMA_PERIOD = 20
MACD_FAST_PERIOD = 12
MACD_SLOW_PERIOD = 26
MACD_SIGNAL_PERIOD = 9

def is_hammer(open_price, high_price, low_price, close_price):
    """Checks for a Hammer candlestick pattern."""
    body = abs(close_price - open_price)
    upper_shadow = high_price - max(open_price, close_price)
    lower_shadow = min(open_price, close_price) - low_price
    
    # Hammer criteria: small body, long lower shadow, little/no upper shadow
    return (body < (high_price - low_price) * 0.3 and # Small body
            lower_shadow > 2 * body and # Long lower shadow
            upper_shadow < body) # Little/no upper shadow

def is_shooting_star(open_price, high_price, low_price, close_price):
    """Checks for a Shooting Star candlestick pattern."""
    body = abs(close_price - open_price)
    upper_shadow = high_price - max(open_price, close_price)
    lower_shadow = min(open_price, close_price) - low_price
    
    # Shooting Star criteria: small body, long upper shadow, little/no lower shadow
    return (body < (high_price - low_price) * 0.3 and # Small body
            upper_shadow > 2 * body and # Long upper shadow
            lower_shadow < body) # Little/no lower shadow

def is_bullish_engulfing(c1_open, c1_close, c2_open, c2_close):
    """Checks for a Bullish Engulfing pattern (c1 is current, c2 is previous)."""
    # Previous candle (c2) is bearish, current candle (c1) is bullish
    return (c2_close < c2_open and # c2 is bearish
            c1_close > c1_open and # c1 is bullish
            c1_open < c2_close and # c1 opens below c2 close
            c1_close > c2_open) # c1 closes above c2 open (engulfs)

def is_bearish_engulfing(c1_open, c1_close, c2_open, c2_close):
    """Checks for a Bearish Engulfing pattern (c1 is current, c2 is previous)."""
    # Previous candle (c2) is bullish, current candle (c1) is bearish
    return (c2_close > c2_open and # c2 is bullish
            c1_close < c1_open and # c1 is bearish
            c1_open > c2_close and # c1 opens above c2 close
            c1_close < c2_open) # c1 closes below c2 open (engulfs)


def get_ai_signal(candles_primary):
    """
    Generates buy and sell signals based on predefined rules and patterns.
    Returns (is_buy_signal, is_sell_signal)
    """
    is_buy_signal = False
    is_sell_signal = False
    
    df = pd.DataFrame(candles_primary, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
    
    # --- Robust Data Cleaning ---
    for col in ['open', 'high', 'low', 'close', 'volume']:
        df[col] = pd.to_numeric(df[col], errors='coerce')
    df.dropna(inplace=True)

    if len(df) < max(EMA_LONG_PERIOD, RSI_PERIOD, VOLUME_SMA_PERIOD, MACD_SLOW_PERIOD, 2): # Need enough data for all indicators and patterns
        logger.warning("Not enough valid candle data for AI rule-based analysis.")
        return False, False

    # Calculate Indicators
    df['ema_long'] = ta.ema(df['close'], length=EMA_LONG_PERIOD)
    df['ema_short'] = ta.ema(df['close'], length=EMA_SHORT_PERIOD)
    df['rsi'] = ta.rsi(df['close'], length=RSI_PERIOD)
    df['volume_sma'] = df['volume'].rolling(window=VOLUME_SMA_PERIOD).mean()
    
    macd_data = ta.macd(df['close'], fast=MACD_FAST_PERIOD, slow=MACD_SLOW_PERIOD, signal=MACD_SIGNAL_PERIOD)
    if not macd_data.empty:
        df['macd_line'] = macd_data[f'MACD_{MACD_FAST_PERIOD}_{MACD_SLOW_PERIOD}_{MACD_SIGNAL_PERIOD}']
        df['macd_signal'] = macd_data[f'MACDs_{MACD_FAST_PERIOD}_{MACD_SLOW_PERIOD}_{MACD_SIGNAL_PERIOD}']
    else:
        df['macd_line'] = None
        df['macd_signal'] = None

    df = df.dropna() # Drop rows with NaN from indicator calculations

    if df.empty:
        logger.warning("DataFrame is empty after indicator calculation and dropping NaNs.")
        return False, False

    # Get latest values
    last_candle = df.iloc[-1]
    prev_candle = df.iloc[-2] if len(df) >= 2 else None

    current_price = last_candle['close']
    ema_long = last_candle['ema_long']
    ema_short = last_candle['ema_short']
    rsi = last_candle['rsi']
    volume_sma = last_candle['volume_sma']
    macd_line = last_candle['macd_line']
    macd_signal = last_candle['macd_signal']
    latest_volume = last_candle['volume']

    # --- Buy Signal Rules ---
    buy_conditions = []
    buy_reasons = []

    # Rule 1: Uptrend (Price above long EMA)
    if current_price > ema_long:
        buy_conditions.append(True)
        buy_reasons.append("Uptrend (Price > EMA50)")
    else:
        buy_conditions.append(False)
        buy_reasons.append("No Uptrend (Price <= EMA50)")

    # Rule 2: Positive Momentum (RSI & MACD)
    if rsi > 50 and rsi < 70: # RSI between 50 and 70
        buy_conditions.append(True)
        buy_reasons.append(f"RSI (50-70): {rsi:.2f}")
    else:
        buy_conditions.append(False)
        buy_reasons.append(f"RSI not (50-70): {rsi:.2f}")

    if macd_line is not None and macd_signal is not None and macd_line > macd_signal:
        buy_conditions.append(True)
        buy_reasons.append(f"MACD > Signal ({macd_line:.4f} > {macd_signal:.4f})")
    else:
        buy_conditions.append(False)
        buy_reasons.append(f"MACD not > Signal")

    # Rule 3: Volume Confirmation
    if latest_volume > (volume_sma * 0.8): # Volume is at least 80% of SMA
        buy_conditions.append(True)
        buy_reasons.append(f"Volume Confirmed (Latest: {latest_volume:.2f}, SMA: {volume_sma:.2f})")
    else:
        buy_conditions.append(False)
        buy_reasons.append(f"Volume Not Confirmed")

    # Rule 4: Candlestick Patterns (Optional/Confirmatory)
    candlestick_buy_pattern = False
    if prev_candle is not None:
        if is_bullish_engulfing(last_candle['open'], last_candle['close'], prev_candle['open'], prev_candle['close']):
            candlestick_buy_pattern = True
            buy_reasons.append("Bullish Engulfing Pattern")
        elif is_hammer(last_candle['open'], last_candle['high'], last_candle['low'], last_candle['close']):
            candlestick_buy_pattern = True
            buy_reasons.append("Hammer Pattern")
    
    if candlestick_buy_pattern:
        buy_conditions.append(True)
    else:
        buy_conditions.append(False)
        buy_reasons.append("No Bullish Pattern") # Add this if no pattern found

    # Final Buy Signal Decision: All core conditions must be met, plus optional pattern
    # For a robust buy, let's require Uptrend, RSI, MACD, and Volume. Candlestick is a bonus.
    if (buy_conditions[0] and buy_conditions[1] and buy_conditions[2] and buy_conditions[3]):
        is_buy_signal = True
        logger.info(f"AI BUY SIGNAL: {' | '.join(buy_reasons)}")
    else:
        logger.info(f"AI No Buy Signal: {' | '.join(buy_reasons)}")


    # --- Sell Signal Rules ---
    sell_conditions = []
    sell_reasons = []

    # Rule 1: Downtrend (Price below short EMA)
    if current_price < ema_short:
        sell_conditions.append(True)
        sell_reasons.append(f"Downtrend (Price < EMA{EMA_SHORT_PERIOD})")
    else:
        sell_conditions.append(False)
        sell_reasons.append(f"No Downtrend (Price >= EMA{EMA_SHORT_PERIOD})")

    # Rule 2: Negative Momentum (RSI & MACD)
    if rsi < 50: # RSI below 50
        sell_conditions.append(True)
        sell_reasons.append(f"RSI < 50: {rsi:.2f}")
    else:
        sell_conditions.append(False)
        sell_reasons.append(f"RSI not < 50: {rsi:.2f}")

    if macd_line is not None and macd_signal is not None and macd_line < macd_signal:
        sell_conditions.append(True)
        sell_reasons.append(f"MACD < Signal ({macd_line:.4f} < {macd_signal:.4f})")
    else:
        sell_conditions.append(False)
        sell_reasons.append(f"MACD not < Signal")

    # Rule 3: Overbought Exit (RSI drops from over 70)
    if rsi < 70 and prev_candle is not None and ta.rsi(df['close'].iloc[:-1], length=RSI_PERIOD).iloc[-1] > 70:
        sell_conditions.append(True)
        sell_reasons.append(f"RSI Dropping from Overbought (Current: {rsi:.2f})")
    else:
        sell_conditions.append(False)
        sell_reasons.append(f"RSI not dropping from Overbought")

    # Rule 4: Candlestick Patterns (Optional/Confirmatory)
    candlestick_sell_pattern = False
    if prev_candle is not None:
        if is_bearish_engulfing(last_candle['open'], last_candle['close'], prev_candle['open'], prev_candle['close']):
            candlestick_sell_pattern = True
            sell_reasons.append("Bearish Engulfing Pattern")
        elif is_shooting_star(last_candle['open'], last_candle['high'], last_candle['low'], last_candle['close']):
            candlestick_sell_pattern = True
            sell_reasons.append("Shooting Star Pattern")
    
    if candlestick_sell_pattern:
        sell_conditions.append(True)
    else:
        sell_conditions.append(False)
        sell_reasons.append("No Bearish Pattern") # Add this if no pattern found

    # Final Sell Signal Decision: At least one core condition must be met, plus optional pattern
    # For a robust sell, let's require Downtrend, RSI, MACD, or RSI dropping from overbought. Candlestick is a bonus.
    if (sell_conditions[0] and sell_conditions[1] and sell_conditions[2]) or sell_conditions[3] or candlestick_sell_pattern:
        is_sell_signal = True
        logger.info(f"AI SELL SIGNAL: {' | '.join(sell_reasons)}")
    else:
        logger.info(f"AI No Sell Signal: {' | '.join(sell_reasons)}")

    return is_buy_signal, is_sell_signal
