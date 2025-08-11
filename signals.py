import os
import numpy as np
import pandas as pd
import pandas_ta as ta
from logger import get_logger
from scipy.signal import find_peaks

logger = get_logger(__name__)

# Read signal-specific parameters from environment variables
VOLUME_SMA_PERIOD = int(os.getenv('VOLUME_SMA_PERIOD', 20))
EXIT_EMA_PERIOD_SHORT = int(os.getenv('EXIT_EMA_PERIOD_SHORT', 9))
EXIT_EMA_PERIOD_LONG = int(os.getenv('EXIT_EMA_PERIOD_LONG', 21))
TREND_EMA_PERIOD = int(os.getenv('TREND_EMA_PERIOD', 50))
EXIT_RSI_LEVEL = int(os.getenv('EXIT_RSI_LEVEL', 65))
BUY_RSI_LEVEL = int(os.getenv('BUY_RSI_LEVEL', 55))
BUY_RSI_UPPER_LEVEL = int(os.getenv('BUY_RSI_UPPER_LEVEL', 70)) # New RSI upper level for buy signal
REVERSAL_DROP_PERCENTAGE = float(os.getenv('REVERSAL_DROP_PERCENTAGE', 0.01)) # 1.0% drop for reversal confirmation (increased from 0.5%)
VOLUME_CONFIRMATION_MULTIPLIER = float(os.getenv('VOLUME_CONFIRMATION_MULTIPLIER', 1.5)) # Volume must be X times average for confirmation

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

    df = pd.DataFrame(candles, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume', 'is_closed'])
    
    # Use only closed candles for ATR calculation
    df_closed = df[df['is_closed']].copy()

    if len(df_closed) < period:
        logger.warning(f"Not enough closed candles ({len(df_closed)}) to calculate ATR for period {period}.")
        return None

    # --- Robust Data Cleaning ---
    for col in ['high', 'low', 'close']:
        df[col] = pd.to_numeric(df[col], errors='coerce')
    df.dropna(subset=['high', 'low', 'close'], inplace=True)
    
    if len(df_closed) < period:
        logger.warning(f"Not enough valid candles ({len(df_closed)}) to calculate ATR after cleaning.")
        return None

    atr = ta.atr(df_closed['high'], df_closed['low'], df_closed['close'], length=period)
    
    # Final validation of the result
    if atr is None or atr.empty or pd.isna(atr.iloc[-1]):
        return None
    
    return atr.iloc[-1]

def is_valid_candle(c):
    # Checks if candle is a list of 7, and OHLCV are numeric.
    # Also checks for None values in the numeric parts.
    return isinstance(c, list) and len(c) == 7 and \
           all(isinstance(val, (int, float)) and val is not None for val in c[1:6])

def check_buy_signal(candles_primary, candles_15min, candles_trend, adx_trend_strength=25):
    """
    Checks for buy signal using Multi-Timeframe Analysis.
    Primary candles are for entry signals (5-min), candles_15min for 15-min trend,
    and candles_trend for 1-hour trend confirmation.
    """
    analysis_details = []

    # Filter out invalid candles early
    candles_primary = [c for c in candles_primary if is_valid_candle(c)]
    candles_15min = [c for c in candles_15min if is_valid_candle(c)]
    candles_trend = [c for c in candles_trend if is_valid_candle(c)]

    # Data validation for primary candles
    if not candles_primary or len(candles_primary) < max(VOLUME_SMA_PERIOD, TREND_EMA_PERIOD, 100):
        reason = f"Insufficient primary candles ({len(candles_primary)}) for buy signal analysis."
        logger.warning(reason)
        return False, reason

    df_primary = pd.DataFrame(candles_primary, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume', 'is_closed'])
    
    # Use all data for price checks, but only closed candles for indicators
    df_primary_closed = df_primary[df_primary['is_closed']].copy()

    for col in ['high', 'low', 'close']:
        df_primary[col] = pd.to_numeric(df_primary[col], errors='coerce')
    df_primary_closed.dropna(subset=['high', 'low', 'close'], inplace=True)

    if len(df_primary_closed) < max(VOLUME_SMA_PERIOD, TREND_EMA_PERIOD, 100):
        reason = f"Insufficient valid closed primary candles ({len(df_primary_closed)}) for buy signal analysis."
        logger.warning(reason)
        return False, reason

    # Data validation for 15-min candles
    if not candles_15min or len(candles_15min) < TREND_EMA_PERIOD:
        reason = f"Insufficient 15-min candles ({len(candles_15min)}) for buy signal analysis."
        logger.warning(reason)
        return False, reason

    df_15min = pd.DataFrame(candles_15min, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume', 'is_closed'])
    df_15min_closed = df_15min[df_15min['is_closed']].copy()
    for col in ['high', 'low', 'close']:
        df_15min[col] = pd.to_numeric(df_15min[col], errors='coerce')
    df_15min_closed.dropna(subset=['high', 'low', 'close'], inplace=True)

    if len(df_15min_closed) < TREND_EMA_PERIOD:
        reason = f"Insufficient valid closed 15-min candles ({len(df_15min_closed)}) for buy signal analysis."
        logger.warning(reason)
        return False, reason

    # Data validation for trend candles
    if not candles_trend or len(candles_trend) < TREND_EMA_PERIOD:
        reason = f"Insufficient trend candles ({len(candles_trend)}) for buy signal analysis."
        logger.warning(reason)
        return False, reason

    df_trend = pd.DataFrame(candles_trend, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume', 'is_closed'])
    df_trend_closed = df_trend[df_trend['is_closed']].copy()
    for col in ['high', 'low', 'close']:
        df_trend[col] = pd.to_numeric(df_trend[col], errors='coerce')
    df_trend_closed.dropna(subset=['high', 'low', 'close'], inplace=True)

    if len(df_trend_closed) < TREND_EMA_PERIOD:
        reason = f"Insufficient valid closed trend candles ({len(df_trend_closed)}) for buy signal analysis."
        logger.warning(reason)
        return False, reason

    # Calculate Indicators for Primary Timeframe on closed candles
    df_primary_closed['rsi'] = ta.rsi(df_primary_closed['close'], length=14)
    df_primary_closed['ema_short'] = ta.ema(df_primary_closed['close'], length=EXIT_EMA_PERIOD_SHORT)
    df_primary_closed['ema_long'] = ta.ema(df_primary_closed['close'], length=EXIT_EMA_PERIOD_LONG)
    adx_df = ta.adx(df_primary_closed['high'], df_primary_closed['low'], df_primary_closed['close'], length=14)
    df_primary_closed['adx'] = adx_df[f'ADX_14'] if adx_df is not None and not adx_df.empty else np.nan

    # Get the latest values from the indicators calculated on closed candles
    last_rsi_primary = df_primary_closed['rsi'].iloc[-1]
    last_ema_short_primary = df_primary_closed['ema_short'].iloc[-1]
    last_ema_long_primary = df_primary_closed['ema_long'].iloc[-1]
    last_adx = df_primary_closed['adx'].iloc[-1]
    prev_ema_short_primary = df_primary_closed['ema_short'].iloc[-2]
    prev_ema_long_primary = df_primary_closed['ema_long'].iloc[-2]

    # Get the latest close price from the original dataframe (which includes the live, non-closed candle)
    last_close_primary = df_primary['close'].iloc[-1]

    # Calculate Trend EMA for 15-min and 1-hour timeframes on their respective closed candles
    df_15min_closed['ema_trend'] = ta.ema(df_15min_closed['close'], length=TREND_EMA_PERIOD)
    df_trend_closed['ema_trend'] = ta.ema(df_trend_closed['close'], length=TREND_EMA_PERIOD)

    last_ema_trend_15min = df_15min_closed['ema_trend'].iloc[-1]
    last_ema_trend_1h = df_trend_closed['ema_trend'].iloc[-1]

    # --- Condition Checks ---
    # Each condition is now evaluated independently and contributes to the analysis details.
    cond1_rsi_in_range = BUY_RSI_LEVEL < last_rsi_primary < BUY_RSI_UPPER_LEVEL
    if cond1_rsi_in_range:
        analysis_details.append(f"✅ RSI ({last_rsi_primary:.2f}) is in the buy zone ({BUY_RSI_LEVEL}-{BUY_RSI_UPPER_LEVEL}).")
    else:
        analysis_details.append(f"❌ RSI ({last_rsi_primary:.2f}) is outside the buy zone ({BUY_RSI_LEVEL}-{BUY_RSI_UPPER_LEVEL}).")

    cond2_ema_crossover = prev_ema_short_primary < prev_ema_long_primary and last_ema_short_primary >= last_ema_long_primary
    # Corrected logic for EMA crossover analysis text
    if last_ema_short_primary > last_ema_long_primary:
        if cond2_ema_crossover:
            analysis_details.append(f"✅ Bullish EMA crossover confirmed (Short {last_ema_short_primary:.4f} > Long {last_ema_long_primary:.4f}).")
        else:
            analysis_details.append(f"✅ Short EMA ({last_ema_short_primary:.4f}) is above Long EMA ({last_ema_long_primary:.4f}).")
    else:
        analysis_details.append(f"❌ Short EMA ({last_ema_short_primary:.4f}) is not above Long EMA ({last_ema_long_primary:.4f}).")


    cond3_price_above_trend = last_close_primary > last_ema_trend_15min and last_close_primary > last_ema_trend_1h
    if cond3_price_above_trend:
        analysis_details.append(f"✅ Live Price ({last_close_primary:.4f}) is above 15m & 1h trend EMAs.")
    else:
        # Provide more specific feedback on which trend check failed
        if last_close_primary <= last_ema_trend_15min:
            analysis_details.append(f"❌ Live Price ({last_close_primary:.4f}) is not above 15m Trend EMA ({last_ema_trend_15min:.4f}).")
        if last_close_primary <= last_ema_trend_1h:
            analysis_details.append(f"❌ Live Price ({last_close_primary:.4f}) is not above 1h Trend EMA ({last_ema_trend_1h:.4f}).")

    # New: ADX Trend Strength Condition
    cond4_adx_strong_trend = last_adx is not None and not pd.isna(last_adx) and last_adx > adx_trend_strength
    if last_adx is None or pd.isna(last_adx):
        analysis_details.append(f"⚠️ ADX could not be calculated.")
    elif cond4_adx_strong_trend:
        analysis_details.append(f"✅ ADX ({last_adx:.2f}) indicates a strong trend (>{adx_trend_strength}).")
    else:
        analysis_details.append(f"❌ ADX ({last_adx:.2f}) indicates a weak or no trend (must be >{adx_trend_strength}).")

    # A buy signal is triggered only if all four conditions are met.
    buy_signal_triggered = cond1_rsi_in_range and cond2_ema_crossover and cond3_price_above_trend and cond4_adx_strong_trend

    return buy_signal_triggered, " | ".join(analysis_details)

def check_sell_signal(candles):
    """
    Checks for a sell signal based on bearish RSI divergence, EMA crossover, and price reversal.
    """
    analysis_details = []

    if not candles or len(candles) < max(EXIT_EMA_PERIOD_LONG, TREND_EMA_PERIOD, ATR_PERIOD, 100):
        reason = f"Insufficient candles ({len(candles)}) for sell signal analysis."
        logger.warning(reason)
        return False, reason

    df = pd.DataFrame(candles, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume', 'is_closed'])
    df_closed = df[df['is_closed']].copy()

    for col in ['high', 'low', 'close', 'volume']:
        df[col] = pd.to_numeric(df[col], errors='coerce')
    df_closed.dropna(subset=['high', 'low', 'close', 'volume'], inplace=True)

    if len(df_closed) < max(EXIT_EMA_PERIOD_LONG, TREND_EMA_PERIOD, ATR_PERIOD, 100):
        reason = f"Insufficient valid closed candles ({len(df_closed)}) for sell signal analysis."
        logger.warning(reason)
        return False, reason

    # Calculate Indicators on closed candles
    df_closed['rsi'] = ta.rsi(df_closed['close'], length=14)
    df_closed['ema_short'] = ta.ema(df_closed['close'], length=EXIT_EMA_PERIOD_SHORT)
    df_closed['ema_long'] = ta.ema(df_closed['close'], length=EXIT_EMA_PERIOD_LONG)
    df_closed['ema_trend'] = ta.ema(df_closed['close'], length=TREND_EMA_PERIOD)

    # --- Bearish RSI Divergence Check ---
    cond1_bearish_divergence = False
    # Look for peaks in the last 60 candles for divergence
    lookback_period_divergence = 60
    if len(df_closed) > lookback_period_divergence:
        price_data = df_closed['close'].tail(lookback_period_divergence)
        rsi_data = df_closed['rsi'].tail(lookback_period_divergence)
        
        # Find peaks (local maxima)
        price_peaks, _ = find_peaks(price_data, distance=5, prominence=0.001)
        rsi_peaks, _ = find_peaks(rsi_data, distance=5, prominence=1)

        if len(price_peaks) >= 2 and len(rsi_peaks) >= 2:
            # Get the last two peaks
            last_price_peak_idx = price_data.index[price_peaks[-1]]
            prev_price_peak_idx = price_data.index[price_peaks[-2]]
            last_rsi_peak_idx = rsi_data.index[rsi_peaks[-1]]
            prev_rsi_peak_idx = rsi_data.index[rsi_peaks[-2]]

            # Check for higher high in price and lower high in RSI
            if df_closed['close'][last_price_peak_idx] > df_closed['close'][prev_price_peak_idx] and \
               df_closed['rsi'][last_rsi_peak_idx] < df_closed['rsi'][prev_rsi_peak_idx]:
                cond1_bearish_divergence = True

    if cond1_bearish_divergence:
        analysis_details.append(f"✅ Bearish RSI Divergence detected.")
    else:
        analysis_details.append(f"❌ No Bearish RSI Divergence.")

    # --- Other Sell Conditions ---
    last_ema_short = df_closed['ema_short'].iloc[-1]
    last_ema_long = df_closed['ema_long'].iloc[-1]
    prev_ema_short = df_closed['ema_short'].iloc[-2]
    prev_ema_long = df_closed['ema_long'].iloc[-2]
    last_close = df['close'].iloc[-1]
    last_ema_trend = df_closed['ema_trend'].iloc[-1]

    cond2_ema_crossunder = prev_ema_short > prev_ema_long and last_ema_short < last_ema_long
    if last_ema_short < last_ema_long:
        if cond2_ema_crossunder:
            analysis_details.append(f"✅ Bearish EMA crossunder confirmed (Short EMA {last_ema_short:.4f} < Long EMA {last_ema_long:.4f}).")
        else:
            analysis_details.append(f"✅ Short EMA ({last_ema_short:.4f}) is below Long EMA ({last_ema_long:.4f}), but no recent crossunder.")
    else:
        analysis_details.append(f"❌ Short EMA ({last_ema_short:.4f}) is not below Long EMA ({last_ema_long:.4f}).")

    lookback_period_reversal = 20
    cond3_reversal_drop = False
    if len(df_closed) >= lookback_period_reversal:
        recent_high = df_closed['high'].iloc[-lookback_period_reversal:-1].max()
        if recent_high and last_close < recent_high * (1 - REVERSAL_DROP_PERCENTAGE):
            cond3_reversal_drop = True
    if cond3_reversal_drop:
        analysis_details.append(f"✅ Price dropped more than {REVERSAL_DROP_PERCENTAGE:.1%} from recent high.")
    else:
        analysis_details.append(f"❌ No significant price drop from recent high.")

    # A sell signal is triggered if any of the primary exit conditions are met
    sell_signal_triggered = cond1_bearish_divergence or cond2_ema_crossunder or cond3_reversal_drop

    return sell_signal_triggered, " | ".join(analysis_details)

def check_sl_tp(current_price, state, sl_price, tp_price, trailing_sl_price, trailing_tp_activation_price):
    """
    Checks if Stop Loss (SL), Take Profit (TP), or Trailing Stop Loss (TSL) conditions are met.
    """
    if not state.get('has_position'):
        return None, "No position to check SL/TP."

    entry_price = state['position'].get('entry_price')
    if entry_price is None:
        return None, "Entry price not set in state."

    # Check Trailing Stop Loss first (if activated)
    if trailing_sl_price is not None and current_price <= trailing_sl_price:
        logger.info(f"Trailing Stop Loss triggered: Current Price {current_price:.4f} <= Trailing SL {trailing_sl_price:.4f}")
        return "TTP", "Trailing Stop Loss triggered."

    # Check Stop Loss
    if sl_price is not None and current_price <= sl_price:
        logger.info(f"Stop Loss triggered: Current Price {current_price:.4f} <= SL {sl_price:.4f}")
        return "SL", "Stop Loss triggered."

    # Check Take Profit
    if tp_price is not None and current_price >= tp_price:
        logger.info(f"Take Profit triggered: Current Price {current_price:.4f} >= TP {tp_price:.4f}")
        return "TP", "Take Profit triggered."

    return None, "No SL/TP/TSL triggered."
