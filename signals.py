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
    Checks for buy signal using Multi-Timeframe Analysis with dynamic thresholds.
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

        # --- Dynamic Threshold Adjustment based on Volatility ---
    current_atr = calculate_atr(candles_primary)
    last_close_primary = df_primary['close'].iloc[-1]
    
    # Default static thresholds
    buy_rsi_level_dynamic = BUY_RSI_LEVEL
    adx_trend_strength_dynamic = adx_trend_strength
    volume_multiplier_dynamic = VOLUME_CONFIRMATION_MULTIPLIER

    if current_atr and last_close_primary > 0:
        volatility_ratio = (current_atr / last_close_primary) * 100
        
        HIGH_VOLATILITY_THRESHOLD = 1.5
        LOW_VOLATILITY_THRESHOLD = 0.7
        
        if volatility_ratio > HIGH_VOLATILITY_THRESHOLD:
            buy_rsi_level_dynamic = BUY_RSI_LEVEL - 5
            adx_trend_strength_dynamic = adx_trend_strength + 5
            volume_multiplier_dynamic = VOLUME_CONFIRMATION_MULTIPLIER + 0.5
            logger.info(f"High volatility detected (ATR: {volatility_ratio:.2f}%). Stricter thresholds: ADX > {adx_trend_strength_dynamic}, Vol > {volume_multiplier_dynamic}x")
        elif volatility_ratio < LOW_VOLATILITY_THRESHOLD:
            buy_rsi_level_dynamic = BUY_RSI_LEVEL
            adx_trend_strength_dynamic = adx_trend_strength - 5
            volume_multiplier_dynamic = VOLUME_CONFIRMATION_MULTIPLIER - 0.4
            logger.info(f"Low volatility detected (ATR: {volatility_ratio:.2f}%). Relaxed thresholds: ADX > {adx_trend_strength_dynamic}, Vol > {volume_multiplier_dynamic}x")
        else:
            logger.info(f"Normal volatility detected (ATR: {volatility_ratio:.2f}%). Using default thresholds.")

    # Calculate Indicators for Primary Timeframe on closed candles
    df_primary_closed['rsi'] = ta.rsi(df_primary_closed['close'], length=14)
    df_primary_closed['ema_short'] = ta.ema(df_primary_closed['close'], length=EXIT_EMA_PERIOD_SHORT)
    df_primary_closed['ema_long'] = ta.ema(df_primary_closed['close'], length=EXIT_EMA_PERIOD_LONG)
    df_primary_closed['volume_sma'] = ta.sma(df_primary_closed['volume'], length=VOLUME_SMA_PERIOD)
    adx_df = ta.adx(df_primary_closed['high'], df_primary_closed['low'], df_primary_closed['close'], length=14)
    if adx_df is not None and not adx_df.empty:
        df_primary_closed['adx'] = adx_df[f'ADX_14']
        df_primary_closed['dmp'] = adx_df[f'DMP_14']
        df_primary_closed['dmn'] = adx_df[f'DMN_14']
    else:
        df_primary_closed['adx'] = np.nan
        df_primary_closed['dmp'] = np.nan
        df_primary_closed['dmn'] = np.nan

    # Get the latest values from the indicators calculated on closed candles
    last_rsi_primary = df_primary_closed['rsi'].iloc[-1]
    last_ema_short_primary = df_primary_closed['ema_short'].iloc[-1]
    last_ema_long_primary = df_primary_closed['ema_long'].iloc[-1]
    last_adx = df_primary_closed['adx'].iloc[-1]
    last_dmp = df_primary_closed['dmp'].iloc[-1]
    last_dmn = df_primary_closed['dmn'].iloc[-1]
    last_volume_primary = df_primary_closed['volume'].iloc[-1] # New: Last volume
    last_volume_sma_primary = df_primary_closed['volume_sma'].iloc[-1] # New: Last volume SMA
    prev_ema_short_primary = df_primary_closed['ema_short'].iloc[-2]
    prev_ema_long_primary = df_primary_closed['ema_long'].iloc[-2]


    # Calculate Trend EMA for 15-min and 1-hour timeframes on their respective closed candles
    df_15min_closed['ema_trend'] = ta.ema(df_15min_closed['close'], length=TREND_EMA_PERIOD)
    df_trend_closed['ema_trend'] = ta.ema(df_trend_closed['close'], length=TREND_EMA_PERIOD)

    last_ema_trend_15min = df_15min_closed['ema_trend'].iloc[-1]
    last_ema_trend_1h = df_trend_closed['ema_trend'].iloc[-1]

    # --- Condition Checks ---
    # Safety Brake: Prevent buying if price is too far above the long-term trend EMA
    PRICE_DEVIATION_LIMIT = 0.025 # 2.5%
    cond0_price_not_overextended = last_close_primary < (last_ema_trend_1h * (1 + PRICE_DEVIATION_LIMIT))
    if cond0_price_not_overextended:
        analysis_details.append(f"✅ Price is not overextended from 1h EMA.")
    else:
        analysis_details.append(f"❌ Safety Brake: Price ({last_close_primary:.4f}) is too far above 1h EMA ({last_ema_trend_1h:.4f}). Entry blocked.")
        # If the safety brake is on, no need to check other conditions
        return False, " | ".join(analysis_details)

    cond1_rsi_in_range = buy_rsi_level_dynamic < last_rsi_primary < BUY_RSI_UPPER_LEVEL
    if cond1_rsi_in_range:
        analysis_details.append(f"✅ RSI ({last_rsi_primary:.2f}) is in the dynamic buy zone ({buy_rsi_level_dynamic}-{BUY_RSI_UPPER_LEVEL}).")
    else:
        analysis_details.append(f"❌ RSI ({last_rsi_primary:.2f}) is outside the dynamic buy zone ({buy_rsi_level_dynamic}-{BUY_RSI_UPPER_LEVEL}).")

    cond2_ema_crossover = prev_ema_short_primary < prev_ema_long_primary and last_ema_short_primary >= last_ema_long_primary
    # Corrected logic for EMA crossover analysis text
    if cond2_ema_crossover:
        analysis_details.append(f"✅ Bullish EMA crossover confirmed (Short {last_ema_short_primary:.4f} > Long {last_ema_long_primary:.4f}).")
    elif last_ema_short_primary > last_ema_long_primary:
        analysis_details.append(f"❌ No recent Bullish EMA crossover (Short {last_ema_short_primary:.4f} > Long {last_ema_long_primary:.4f}).")
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
    cond4_adx_strong_trend = last_adx is not None and not pd.isna(last_adx) and last_adx > adx_trend_strength_dynamic
    if last_adx is None or pd.isna(last_adx):
        analysis_details.append(f"⚠️ ADX could not be calculated.")
    elif cond4_adx_strong_trend:
        analysis_details.append(f"✅ ADX ({last_adx:.2f}) indicates a strong trend (>{adx_trend_strength_dynamic}).")
    else:
        analysis_details.append(f"❌ ADX ({last_adx:.2f}) indicates a weak or no trend (must be >{adx_trend_strength_dynamic}).")

    # New: Volume Confirmation Condition
    cond5_volume_confirmation = last_volume_primary > (last_volume_sma_primary * volume_multiplier_dynamic)
    if cond5_volume_confirmation:
        analysis_details.append(f"✅ Volume ({last_volume_primary:.2f}) is {volume_multiplier_dynamic:.1f}x above SMA ({last_volume_sma_primary:.2f}).")
    else:
        analysis_details.append(f"❌ Volume ({last_volume_primary:.2f}) is not {volume_multiplier_dynamic:.1f}x above SMA ({last_volume_sma_primary:.2f}).")

    # New: DMI Confirmation
    cond6_dmi_confirmation = last_dmp > last_dmn
    if cond6_dmi_confirmation:
        analysis_details.append(f"✅ DMI Confirmation (DI+ {last_dmp:.2f} > DI- {last_dmn:.2f}).")
    else:
        analysis_details.append(f"❌ DMI Confirmation (DI+ {last_dmp:.2f} <= DI- {last_dmn:.2f}).")

    # A buy signal is triggered only if all conditions are met (including the safety brake checked earlier).
    buy_signal_triggered = cond1_rsi_in_range and cond2_ema_crossover and cond3_price_above_trend and cond4_adx_strong_trend and cond5_volume_confirmation and cond6_dmi_confirmation

    return buy_signal_triggered, " | ".join(analysis_details)

def check_sell_signal(candles, adx_trend_strength=25):
    """
    Checks for a sell signal using an enhanced, dynamic confirmation mechanism.
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
    df_closed['volume_sma'] = ta.sma(df_closed['volume'], length=VOLUME_SMA_PERIOD)
    adx_df = ta.adx(df_closed['high'], df_closed['low'], df_closed['close'], length=14)
    if adx_df is not None and not adx_df.empty:
        df_closed['adx'] = adx_df[f'ADX_14']
        df_closed['dmp'] = adx_df[f'DMP_14']
        df_closed['dmn'] = adx_df[f'DMN_14']
    else:
        df_closed['adx'] = np.nan
        df_closed['dmp'] = np.nan
        df_closed['dmn'] = np.nan
    
    # --- New: On-Balance Volume (OBV) for sell confirmation ---
    df_closed['obv'] = ta.obv(df_closed['close'], df_closed['volume'])
    df_closed['obv_sma'] = ta.sma(df_closed['obv'], length=10) # Short-term SMA of OBV

    # --- Dynamic Thresholds for Sell Signal based on Volatility ---
    current_atr = calculate_atr(candles)
    last_close = df['close'].iloc[-1]
    
    # Default number of conditions required to trigger a sell
    required_conditions = 2 
    
    if current_atr and last_close > 0:
        volatility_ratio = (current_atr / last_close) * 100
        
        HIGH_VOLATILITY_THRESHOLD = 1.5
        LOW_VOLATILITY_THRESHOLD = 0.7

        if volatility_ratio > HIGH_VOLATILITY_THRESHOLD:
            required_conditions = 1 # Quick exit in high volatility
            logger.info(f"High volatility detected for sell. Required conditions: {required_conditions}")
        elif volatility_ratio < LOW_VOLATILITY_THRESHOLD:
            required_conditions = 3 # Patient exit in low volatility
            logger.info(f"Low volatility detected for sell. Required conditions: {required_conditions}")

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
    last_close = df['close'].iloc[-1] # Use last_close from original df for live price
    last_ema_trend = df_closed['ema_trend'].iloc[-1]
    last_adx = df_closed['adx'].iloc[-1]
    last_dmp = df_closed['dmp'].iloc[-1]
    last_dmn = df_closed['dmn'].iloc[-1]

    cond2_ema_crossunder = prev_ema_short > prev_ema_long and last_ema_short < last_ema_long
    if cond2_ema_crossunder:
        analysis_details.append(f"✅ Bearish EMA crossunder confirmed (Short EMA {last_ema_short:.4f} < Long EMA {last_ema_long:.4f}).")
    elif last_ema_short < last_ema_long:
        analysis_details.append(f"❌ No recent Bearish EMA crossunder (Short EMA {last_ema_short:.4f} < Long EMA {last_ema_long:.4f}).")
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

    # New: ADX Weakness Condition for Sell
    cond5_adx_weakness = last_adx is not None and not pd.isna(last_adx) and last_adx < adx_trend_strength
    if last_adx is None or pd.isna(last_adx):
        analysis_details.append(f"⚠️ ADX could not be calculated for weakness check.")
    elif cond5_adx_weakness:
        analysis_details.append(f"✅ ADX ({last_adx:.2f}) indicates trend weakness (below {adx_trend_strength}).")
    else:
        analysis_details.append(f"❌ ADX ({last_adx:.2f}) does not indicate trend weakness (above {adx_trend_strength}).")

    # --- Enhanced Sell Confirmation with OBV ---
    last_obv = df_closed['obv'].iloc[-1]
    last_obv_sma = df_closed['obv_sma'].iloc[-1]
    
    # Condition 1: OBV should be trending down, indicating distribution.
    cond_obv_trending_down = last_obv < last_obv_sma
    if cond_obv_trending_down:
        analysis_details.append(f"✅ OBV ({last_obv:.2f}) is below its SMA ({last_obv_sma:.2f}), confirming selling pressure.")
    else:
        analysis_details.append(f"❌ OBV ({last_obv:.2f}) is not below its SMA ({last_obv_sma:.2f}), indicating weak selling pressure.")

    # Condition 2: A recent bearish candle with high volume (original confirmation)
    cond_high_volume_bearish_candle = False
    if len(df_closed) >= VOLUME_SMA_PERIOD:
        last_closed_candle = df_closed.iloc[-1]
        if last_closed_candle['close'] < last_closed_candle['open'] and \
           last_closed_candle['volume'] > df_closed['volume_sma'].iloc[-1] * VOLUME_CONFIRMATION_MULTIPLIER:
            cond_high_volume_bearish_candle = True

    if cond_high_volume_bearish_candle:
        analysis_details.append(f"✅ High-volume bearish candle detected.")
    else:
        analysis_details.append(f"❌ No recent high-volume bearish candle.")

    # New: DMI Confirmation for Sell
    cond6_dmi_confirmation = last_dmn > last_dmp
    if cond6_dmi_confirmation:
        analysis_details.append(f"✅ DMI Confirmation (DI- {last_dmn:.2f} > DI+ {last_dmp:.2f}).")
    else:
        analysis_details.append(f"❌ DMI Confirmation (DI- {last_dmn:.2f} <= DI+ {last_dmp:.2f}).")

    # A sell signal requires a dynamic number of primary conditions AND strong volume confirmation from OBV AND DMI confirmation.
    primary_conditions_met = sum([cond1_bearish_divergence, cond2_ema_crossunder, cond3_reversal_drop, cond5_adx_weakness])
    volume_confirmation_met = cond_obv_trending_down and cond_high_volume_bearish_candle
    
    sell_signal_triggered = (primary_conditions_met >= required_conditions) and volume_confirmation_met and cond6_dmi_confirmation

    return sell_signal_triggered, " | ".join(analysis_details)

def check_sl_tp(current_price, state, sl_price, tp_price, trailing_sl_price):
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

def check_ema_tsl(current_price, candles):
    """
    Checks if the price has crossed below the short-term EMA, acting as a dynamic trailing stop.
    """
    if not candles or len(candles) < EXIT_EMA_PERIOD_SHORT:
        return False, "Insufficient data for EMA TSL."

    df = pd.DataFrame(candles, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume', 'is_closed'])
    df_closed = df[df['is_closed']].copy()

    if len(df_closed) < EXIT_EMA_PERIOD_SHORT:
        return False, "Insufficient closed candles for EMA TSL."

    for col in ['close']:
        df_closed[col] = pd.to_numeric(df_closed[col], errors='coerce')
    df_closed.dropna(subset=['close'], inplace=True)

    if len(df_closed) < EXIT_EMA_PERIOD_SHORT:
        return False, "Insufficient valid closed candles for EMA TSL."

    ema_short = ta.ema(df_closed['close'], length=EXIT_EMA_PERIOD_SHORT)
    if ema_short is None or ema_short.empty:
        return False, "Could not calculate short EMA."

    last_ema_short = ema_short.iloc[-1]

    if current_price < last_ema_short:
        reason = f"EMA TSL triggered: Price ({current_price:.4f}) < EMA-{EXIT_EMA_PERIOD_SHORT} ({last_ema_short:.4f})."
        logger.info(reason)
        return True, reason
    
    return False, f"Price ({current_price:.4f}) >= EMA-{EXIT_EMA_PERIOD_SHORT} ({last_ema_short:.4f})."
