import os
import pandas as pd
import pandas_ta as ta
from logger import get_logger

logger = get_logger(__name__)

# --- Parameters for the 15m SMA Strategy (Hardcoded) ---
TREND_SMA_PERIOD = 50
RSI_PERIOD = 14
RSI_BUY_LEVEL = 40 # Buy when RSI crosses above this level from a local bottom

# --- ATR Parameters (Hardcoded) ---
ATR_PERIOD = 14

def is_valid_candle(c):
    """Checks if a candle has the correct format and numeric values."""
    return isinstance(c, list) and len(c) == 7 and \
           all(isinstance(val, (int, float)) and val is not None for val in c[1:6])

def calculate_atr(candles, period=ATR_PERIOD):
    """
    Calculates the Average True Range (ATR) from candle data.
    """
    if len(candles) < period:
        return None

    df = pd.DataFrame(candles, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume', 'is_closed'])
    df_closed = df[df['is_closed']].copy()

    if len(df_closed) < period:
        return None

    for col in ['high', 'low', 'close']:
        df_closed[col] = pd.to_numeric(df_closed[col], errors='coerce')
    df_closed.dropna(subset=['high', 'low', 'close'], inplace=True)
    
    if len(df_closed) < period:
        return None
        
    atr = ta.atr(df_closed['high'], df_closed['low'], df_closed['close'], length=period)
    
    if atr is None or atr.empty or pd.isna(atr.iloc[-1]):
        return None
    
    return atr.iloc[-1]

def check_buy_signal(candles_15m, candles_1h):
    """
    Checks for a buy signal based on the 15m SMA strategy.
    - Price must be above SMA50 on 15m and 1h timeframes.
    - RSI on 15m must cross up from a local bottom (below RSI_BUY_LEVEL).
    """
    analysis_details = []

    # --- Data Validation ---
    candles_15m = [c for c in candles_15m if is_valid_candle(c)]
    candles_1h = [c for c in candles_1h if is_valid_candle(c)]

    if len(candles_15m) < TREND_SMA_PERIOD or len(candles_1h) < TREND_SMA_PERIOD:
        reason = f"Insufficient data: 15m candles ({len(candles_15m)}), 1h candles ({len(candles_1h)}). Need at least {TREND_SMA_PERIOD}."
        return False, reason

    df_15m = pd.DataFrame(candles_15m, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume', 'is_closed'])
    df_1h = pd.DataFrame(candles_1h, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume', 'is_closed'])

    # Use only closed candles for indicator calculations
    df_15m_closed = df_15m[df_15m['is_closed']].copy()
    df_1h_closed = df_1h[df_1h['is_closed']].copy()

    if len(df_15m_closed) < TREND_SMA_PERIOD or len(df_1h_closed) < TREND_SMA_PERIOD:
        reason = f"Insufficient closed candles for analysis."
        return False, reason

    # --- Indicator Calculation ---
    df_15m_closed['sma50'] = ta.sma(df_15m_closed['close'], length=TREND_SMA_PERIOD)
    df_1h_closed['sma50'] = ta.sma(df_1h_closed['close'], length=TREND_SMA_PERIOD)
    df_15m_closed['rsi'] = ta.rsi(df_15m_closed['close'], length=RSI_PERIOD)

    # --- Get Latest Values ---
    last_close = df_15m['close'].iloc[-1]
    last_sma_15m = df_15m_closed['sma50'].iloc[-1]
    last_sma_1h = df_1h_closed['sma50'].iloc[-1]
    last_rsi = df_15m_closed['rsi'].iloc[-1]
    prev_rsi = df_15m_closed['rsi'].iloc[-2]

    # --- Condition Checks ---
    cond1_price_above_sma_15m = last_close > last_sma_15m
    if cond1_price_above_sma_15m:
        analysis_details.append(f"✅ Price ({last_close:.4f}) > 15m SMA50 ({last_sma_15m:.4f})")
    else:
        analysis_details.append(f"❌ Price ({last_close:.4f}) <= 15m SMA50 ({last_sma_15m:.4f})")

    cond2_price_above_sma_1h = last_close > last_sma_1h
    if cond2_price_above_sma_1h:
        analysis_details.append(f"✅ Price ({last_close:.4f}) > 1h SMA50 ({last_sma_1h:.4f})")
    else:
        analysis_details.append(f"❌ Price ({last_close:.4f}) <= 1h SMA50 ({last_sma_1h:.4f})")

    cond3_rsi_crossover = prev_rsi <= RSI_BUY_LEVEL and last_rsi > RSI_BUY_LEVEL
    if cond3_rsi_crossover:
        analysis_details.append(f"✅ RSI crossed up from local bottom ({last_rsi:.2f} > {RSI_BUY_LEVEL})")
    else:
        analysis_details.append(f"❌ RSI ({last_rsi:.2f}) has not crossed up from a local bottom.")

    buy_signal = cond1_price_above_sma_15m and cond2_price_above_sma_1h and cond3_rsi_crossover
    return buy_signal, " | ".join(analysis_details)


def check_sell_signal(candles_15m):
    """
    Checks for a sell signal based on the 15m SMA strategy.
    - The ONLY sell signal is a clear close below the SMA50 on the 15m timeframe.
    """
    analysis_details = []

    # --- Data Validation ---
    candles_15m = [c for c in candles_15m if is_valid_candle(c)]
    if len(candles_15m) < TREND_SMA_PERIOD:
        return False, f"Insufficient 15m candles ({len(candles_15m)}) for sell signal."

    df_15m = pd.DataFrame(candles_15m, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume', 'is_closed'])
    
    # We need the second to last candle to be closed to confirm a "clear break"
    if len(df_15m) < 2 or not df_15m.iloc[-2]['is_closed']:
        return False, "Waiting for previous candle to close to confirm SMA break."

    df_15m_closed = df_15m[df_15m['is_closed']].copy()
    if len(df_15m_closed) < TREND_SMA_PERIOD:
        return False, "Insufficient closed 15m candles for sell signal."

    # --- Indicator Calculation ---
    df_15m_closed['sma50'] = ta.sma(df_15m_closed['close'], length=TREND_SMA_PERIOD)

    # --- Get Latest Values ---
    # Check the last CLOSED candle's price against the SMA
    last_closed_price = df_15m_closed['close'].iloc[-1]
    last_sma_15m = df_15m_closed['sma50'].iloc[-1]

    # --- Condition Check ---
    cond_price_below_sma = last_closed_price < last_sma_15m
    if cond_price_below_sma:
        analysis_details.append(f"✅ SELL: Last closed price ({last_closed_price:.4f}) broke below 15m SMA50 ({last_sma_15m:.4f})")
    else:
        analysis_details.append(f"❌ No Sell: Price ({last_closed_price:.4f}) is still above 15m SMA50 ({last_sma_15m:.4f})")

    return cond_price_below_sma, " | ".join(analysis_details)


def check_sl_tp(current_price, state, sl_price, tp_price, trailing_sl_price):
    """
    Checks if Stop Loss (SL), Take Profit (TP), or Trailing Stop Loss (TSL) conditions are met.
    This function is kept for the ATR-based trailing stop.
    """
    if not state.get('has_position'):
        return None, "No position to check."

    entry_price = state['position'].get('entry_price')
    if entry_price is None:
        return None, "Entry price not set."

    # Trailing Stop Loss is the primary exit mechanism besides the SMA break signal
    if trailing_sl_price is not None and current_price <= trailing_sl_price:
        logger.info(f"Trailing Stop Loss triggered: Current Price {current_price:.4f} <= TSL {trailing_sl_price:.4f}")
        return "TTP", "Trailing Stop Loss triggered."

    # A regular SL is also checked as a safety net
    if sl_price is not None and current_price <= sl_price:
        logger.info(f"Stop Loss triggered: Current Price {current_price:.4f} <= SL {sl_price:.4f}")
        return "SL", "Stop Loss triggered."
        
    # TP is less relevant in this trend-following strategy, but kept for safety
    if tp_price is not None and current_price >= tp_price:
        logger.info(f"Take Profit triggered: Current Price {current_price:.4f} >= TP {tp_price:.4f}")
        return "TP", "Take Profit triggered."

    return None, "No SL/TP/TSL triggered."
