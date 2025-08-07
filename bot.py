import os
import json
from dotenv import load_dotenv
from datetime import datetime, timedelta

from logger import get_logger
from exchange import get_exchange, fetch_candles, get_current_price, create_market_buy_order, create_market_sell_order, get_account_balance, fetch_last_buy_trade
import signals
from state import load_state, save_state, clear_state, save_trade_history
from notifier import send_telegram_message
from shared_state import strategy_params
import tempfile

# Load environment variables
load_dotenv()
logger = get_logger(__name__)

# Constants from .env
SYMBOL = os.getenv('SYMBOL', 'XLM/USDT')
TIMEFRAME = os.getenv('TIMEFRAME', '5m')
TREND_TIMEFRAME = os.getenv('TREND_TIMEFRAME', '1h') # New: For multi-timeframe analysis
# ATR-based SL/TP parameters
ATR_PERIOD = int(os.getenv('ATR_PERIOD', 14))
ATR_SL_MULTIPLIER = float(os.getenv('ATR_SL_MULTIPLIER', 1.5))
ATR_TP_MULTIPLIER = float(os.getenv('ATR_TP_MULTIPLIER', 3.0))
ATR_TRAILING_TP_ACTIVATION_MULTIPLIER = float(os.getenv('ATR_TRAILING_TP_ACTIVATION_MULTIPLIER', 2.0))
ATR_TRAILING_SL_MULTIPLIER = float(os.getenv('ATR_TRAILING_SL_MULTIPLIER', 1.0))

POLL_SECONDS = int(os.getenv('POLL_SECONDS', 10))
DRY_RUN = os.getenv('DRY_RUN', 'True').lower() == 'true'
COOL_DOWN_PERIOD_MINUTES = int(os.getenv('COOL_DOWN_PERIOD_MINUTES', 30)) # New: Cool-down period after a loss
MIN_TRADE_USDT = float(os.getenv('MIN_TRADE_USDT', 10.0)) # New: Minimum trade amount in quote currency

def initialize_strategy_params():
    """
    Populates the shared state with the bot's current strategy parameters.
    """
    strategy_params["timeframe"] = TIMEFRAME
    strategy_params["trend_timeframe"] = TREND_TIMEFRAME # Add new timeframe to web status
    strategy_params["buy_signal_period"] = signals.VOLUME_SMA_PERIOD
    strategy_params["sell_signal_period"] = signals.EXIT_EMA_PERIOD
    strategy_params["trend_ema_period"] = signals.TREND_EMA_PERIOD
    strategy_params["exit_rsi_level"] = signals.EXIT_RSI_LEVEL
    strategy_params["atr_period"] = ATR_PERIOD
    strategy_params["atr_sl_multiplier"] = ATR_SL_MULTIPLIER
    strategy_params["atr_tp_multiplier"] = ATR_TP_MULTIPLIER
    strategy_params["atr_trailing_tp_activation_multiplier"] = ATR_TRAILING_TP_ACTIVATION_MULTIPLIER
    strategy_params["atr_trailing_sl_multiplier"] = ATR_TRAILING_SL_MULTIPLIER
    strategy_params["buy_rsi_level"] = signals.BUY_RSI_LEVEL # Add new RSI buy level
    strategy_params["cool_down_period_minutes"] = COOL_DOWN_PERIOD_MINUTES # Add cool-down period
    strategy_params["min_trade_usdt"] = MIN_TRADE_USDT # Add minimum trade amount
    strategy_params["macd_fast_period"] = signals.MACD_FAST_PERIOD
    strategy_params["macd_slow_period"] = signals.MACD_SLOW_PERIOD
    strategy_params["macd_signal_period"] = signals.MACD_SIGNAL_PERIOD
    logger.info(f"Strategy parameters initialized: {strategy_params}")

def sync_position_with_exchange(exchange, symbol):
    """
    Checks the exchange for an existing position and syncs it with the local state.
    """
    logger.info("Syncing position state with exchange...")
    state = load_state()

    if state.get('has_position'):
        logger.info("Local state already shows a position. Skipping sync.")
        return

    balance = get_account_balance(exchange)
    base_currency = symbol.split('/')[0]
    base_currency_balance = balance.get(base_currency, {}).get('free', 0)
    min_position_amount = 1 

    if base_currency_balance > min_position_amount:
        logger.warning(f"Found {base_currency_balance:.6f} {base_currency} on exchange. Attempting to sync from trade history.")
        last_buy_trade = fetch_last_buy_trade(exchange, symbol)
        
        if last_buy_trade:
            entry_price = last_buy_trade['price']
            entry_timestamp = last_buy_trade['datetime']
            entry_size = last_buy_trade['amount']
            
            if abs(base_currency_balance - entry_size) / entry_size > 0.05:
                 logger.warning(f"Balance ({base_currency_balance}) does not match last trade size ({entry_size}). Using current balance.")
                 entry_size = base_currency_balance

            state['has_position'] = True
            state['position'] = {
                'entry_price': entry_price,
                'size': entry_size,
                'timestamp': entry_timestamp,
                'highest_price_after_tp': None,
                'sl_price': None, # Will be calculated on first tick
                'tp_price': None, # Will be calculated on first tick
                'trailing_sl_price': None # Will be calculated on first tick
            }
            save_state(state)
            msg = (f"✅ <b>State Sync</b>\nFound existing position.\n"
                   f"Synced from last buy trade at ${entry_price:.4f} on {entry_timestamp}.")
            send_telegram_message(msg)
            logger.info("Successfully synced position from exchange trade history.")
        else:
            logger.error("Could not find a recent buy trade. Falling back to approximation.")
            current_price = get_current_price(exchange, symbol)
            if not current_price:
                logger.error("Cannot re-create state: failed to fetch current price.")
                return

            state['has_position'] = True
            state['position'] = {
                'entry_price': current_price, # Approximation
                'size': base_currency_balance,
                'timestamp': None,
                'highest_price_after_tp': None,
                'sl_price': None, # Will be calculated on first tick
                'tp_price': None, # Will be calculated on first tick
                'trailing_sl_price': None # Will be calculated on first tick
            }
            save_state(state)
            msg = (f"⚠️ <b>State Sync (Fallback)</b>\nFound position, but no trade history.\n"
                   f"Re-created state with approximate entry price. PnL will be inaccurate.")
            send_telegram_message(msg)
            logger.info("Successfully synced position using fallback.")

def execute_sell_and_record_trade(exchange, state, reason, current_price):
    """
    Executes a market sell order using the current available balance and records the trade details.
    This is more robust against state inconsistencies or precision issues.
    """
    logger.info(f"Executing sell for reason: {reason}")
    
    # --- Robust Sell Logic ---
    # 1. Get the actual available balance from the exchange right before selling.
    balance = get_account_balance(exchange)
    base_currency = SYMBOL.split('/')[0]
    actual_sell_amount = balance.get(base_currency, {}).get('free', 0)
    
    if actual_sell_amount < 1: # Ensure there's a sellable amount
        logger.error(f"Attempted to sell but found no sellable balance for {base_currency}.")
        # Clear the state as it's inconsistent with the exchange.
        send_telegram_message(f"⚠️ <b>State Mismatch</b>\nBot had a position for {base_currency}, but balance is zero. Clearing state.")
        clear_state()
        return False

    logger.info(f"State size was {state['position']['size']}, actual balance is {actual_sell_amount}. Selling actual balance.")
    # 2. Create the sell order using the actual balance.
    sell_order = create_market_sell_order(exchange, SYMBOL, actual_sell_amount)
    
    if not sell_order:
        logger.error(f"Failed to create sell order for {reason}.")
        return False

    entry_price = state['position']['entry_price']
    exit_price = sell_order['price']
    pnl_percent = ((exit_price - entry_price) / entry_price) * 100
    
    # 3. Record the trade with the actual sold amount for accuracy.
    trade_record = {
        "symbol": SYMBOL,
        "entry_price": entry_price,
        "exit_price": exit_price,
        "size": sell_order['amount'], # Use the amount from the successful order
        "pnl_percent": pnl_percent,
        "reason": reason,
        "timestamp": sell_order['datetime']
    }
    save_trade_history(trade_record)
    
    msg = f"✅ <b>{reason.upper()} SELL</b>\nSymbol: <code>{SYMBOL}</code>\nPrice: <code>${current_price:.4f}</code>\nPnL: <code>{pnl_percent:.2f}%</code>"
    send_telegram_message(msg)
    logger.info(msg)
    
    # If it was a losing trade, record the timestamp for cool-down
    if pnl_percent < 0:
        state['last_loss_timestamp'] = datetime.now().isoformat()
        save_state(state) # Save state immediately after recording loss timestamp
        logger.info(f"Recorded last loss at {state['last_loss_timestamp']}")

    clear_state()
    return True

def write_web_status(status_data):
    """Atomically writes the bot status to a JSON file for the web UI."""
    # Ensure all keys have default values
    data_to_write = {
        "signal": "N/A",
        "signal_reason": "Initializing...",
        "analysis_details": "Waiting for data...",
        "live_candles": [],
    }
    data_to_write.update(status_data)

    try:
        with tempfile.NamedTemporaryFile('w', dir='.', delete=False) as tf:
            json.dump(data_to_write, tf)
            temp_path = tf.name
        os.rename(temp_path, 'web_status.json')
        logger.info("web_status.json updated.")
    except Exception as e:
        logger.error(f"Failed to write web_status.json: {e}")
        if 'temp_path' in locals() and os.path.exists(temp_path):
            os.remove(temp_path)

def handle_in_position(exchange, state, current_price, candles):
    """
    Handles the logic when the bot is in a position.
    Returns: signal, signal_reason, trade_executed, analysis_details
    """
    # --- Critical Validation ---
    if current_price is None:
        logger.error("handle_in_position was called with a None current_price.")
        # Return a clear error state that can be displayed in the UI
        return "Error", "Price is None", False, "Critical error: Current price data is missing."

    entry_price = state['position']['entry_price']
    
    # Calculate ATR and update SL/TP prices if not set or if ATR changes significantly
    current_atr = signals.calculate_atr(candles)
    if current_atr is not None:
        # Initialize or update SL/TP prices based on ATR
        if state['position']['sl_price'] is None or state['position']['tp_price'] is None:
            state['position']['sl_price'] = entry_price - (current_atr * ATR_SL_MULTIPLIER)
            state['position']['tp_price'] = entry_price + (current_atr * ATR_TP_MULTIPLIER)
            state['position']['trailing_sl_price'] = entry_price - (current_atr * ATR_SL_MULTIPLIER) # Initial trailing SL
            save_state(state)
            logger.info(f"Initial ATR-based SL/TP set. SL: {state['position']['sl_price']:.4f}, TP: {state['position']['tp_price']:.4f}")
        
        # Update trailing SL if price moves favorably
        activation_price = entry_price + (current_atr * ATR_TRAILING_TP_ACTIVATION_MULTIPLIER)
        if current_price > activation_price:
            highest_price = state['position'].get('highest_price_after_tp', entry_price)
            if current_price > highest_price:
                state['position']['highest_price_after_tp'] = current_price
                # Trailing SL moves up with the highest price
                new_trailing_sl = current_price - (current_atr * ATR_TRAILING_SL_MULTIPLIER)
                # Ensure trailing SL never moves below the initial SL or previous trailing SL
                state['position']['trailing_sl_price'] = max(state['position']['sl_price'], new_trailing_sl, state['position']['trailing_sl_price'] or 0)
                save_state(state)
                logger.info(f"Trailing stop updated. New highest price: {current_price:.4f}, New Trailing SL: {state['position']['trailing_sl_price']:.4f}")

    # Check for SL/TP/TTP exit using the calculated absolute prices
    reason, _ = signals.check_sl_tp(
        current_price, 
        state, 
        sl_price=state['position']['sl_price'], 
        tp_price=state['position']['tp_price'], 
        trailing_sl_price=state['position']['trailing_sl_price'],
        trailing_tp_activation_price=entry_price + (current_atr * ATR_TRAILING_TP_ACTIVATION_MULTIPLIER) if current_atr else None
    )
    if reason in ["SL", "TP", "TTP"]:
        if execute_sell_and_record_trade(exchange, state, reason, current_price):
            # For SL/TP, the reason is clear and doesn't need a full breakdown.
            return "Sold", reason, True, f"Exit Reason: {reason}"

    # 3. Check for trend reversal SELL signal
    is_sell_signal, analysis_details = signals.check_sell_signal(candles)
    if is_sell_signal:
        # The sell reason is the detailed analysis itself
        if execute_sell_and_record_trade(exchange, state, "Signal", current_price):
            return "Sold", "Exit Signal", True, analysis_details
    
    return "Waiting (in position)", "No exit signal.", False, analysis_details

def handle_no_position(exchange, balance, current_price, candles_primary, candles_trend):
    """
    Handles the logic when the bot is not in a position, using multi-timeframe data.
    Returns: signal, signal_reason, analysis_details
    """
    state = load_state() # Ensure we have the latest state for cool-down check
    last_loss_timestamp_str = state.get('last_loss_timestamp')

    if last_loss_timestamp_str:
        last_loss_time = datetime.fromisoformat(last_loss_timestamp_str)
        time_since_last_loss = datetime.now() - last_loss_time
        
        if time_since_last_loss < timedelta(minutes=COOL_DOWN_PERIOD_MINUTES):
            remaining_cooldown = timedelta(minutes=COOL_DOWN_PERIOD_MINUTES) - time_since_last_loss
            reason = f"Cool-down active. Wait {int(remaining_cooldown.total_seconds() / 60)} mins."
            logger.info(f"In cool-down period. Remaining: {int(remaining_cooldown.total_seconds() / 60)} minutes.")
            return "Cool-down", reason, reason

    is_buy_signal, analysis_details = signals.check_buy_signal(candles_primary, candles_trend)
    if is_buy_signal:
        quote_currency = SYMBOL.split('/')[1]
        amount_usdt = balance.get(quote_currency, {}).get('free', 0)
        
        if amount_usdt < MIN_TRADE_USDT:
            reason = f"Insufficient balance ({amount_usdt:.2f} {quote_currency}) for trade."
            logger.info(f"Not enough {quote_currency} balance ({amount_usdt:.2f}) for minimum trade ({MIN_TRADE_USDT:.2f}).")
            return "Waiting (no position)", reason, analysis_details

        if amount_usdt > 1: # Still keep this check for very small dust amounts
            buy_order = create_market_buy_order(exchange, SYMBOL, amount_usdt)
            if buy_order:
                new_state = load_state()
                new_state['has_position'] = True
                new_state['position'] = {
                    'entry_price': buy_order['price'],
                    'size': buy_order['amount'],
                    'timestamp': buy_order['datetime'],
                    'highest_price_after_tp': None,
                    'sl_price': None, # Will be calculated on first tick after buy
                    'tp_price': None, # Will be calculated on first tick after buy
                    'trailing_sl_price': None # Will be calculated on first tick after buy
                }
                # Clear last_loss_timestamp after a successful buy
                if 'last_loss_timestamp' in new_state:
                    del new_state['last_loss_timestamp']
                save_state(new_state)
                msg = f"🟢 <b>BUY</b>\nSymbol: <code>{SYMBOL}</code>\nPrice: <code>${buy_order['price']:.4f}</code>\nReason: {analysis_details}"
                send_telegram_message(msg)
                logger.info(msg)
                return "Buy", analysis_details, analysis_details
    
    return "Waiting (no position)", "No buy signal.", analysis_details

def run_bot_tick():
    """
    Runs a single check of the trading bot logic.
    """
    logger.info("--- Running bot tick ---")
    
    signal = "Initializing"
    signal_reason = "Bot tick started."
    analysis_details = "Initializing..."
    candles_primary = []

    try:
        exchange = get_exchange()
        state = load_state()

        # --- State Validation ---
        balance = get_account_balance(exchange)
        base_currency = SYMBOL.split('/')[0]
        base_currency_balance = balance.get(base_currency, {}).get('free', 0)
        min_position_amount = 1

        if state.get('has_position'):
            position_size = state['position'].get('size', 0)
            if base_currency_balance < position_size * 0.9:
                logger.warning(f"Position mismatch: state size {position_size}, exchange balance {base_currency_balance}. Clearing state.")
                send_telegram_message("⚠️ <b>State Mismatch</b>\nPosition closed outside bot. Clearing state.")
                clear_state()
                state = load_state()
        elif base_currency_balance >= min_position_amount:
            logger.warning("No local state, but found position on exchange. Syncing...")
            sync_position_with_exchange(exchange, SYMBOL)
            state = load_state()

        # --- Fetch Data ---
        current_price = get_current_price(exchange, SYMBOL)
        candles_primary = fetch_candles(exchange, SYMBOL, TIMEFRAME, limit=100)
        candles_trend = fetch_candles(exchange, SYMBOL, TREND_TIMEFRAME, limit=100)
        
        if not current_price or not candles_primary or len(candles_primary) < 50 or not candles_trend or len(candles_trend) < 50:
            signal, signal_reason = "Data Error", "Failed to fetch price or candle data for one or both timeframes."
            analysis_details = signal_reason
        else:
            # --- Main Logic ---
            if state.get('has_position'):
                # Note: handle_in_position still uses primary candles for SL/TP/Exit signals
                signal, signal_reason, trade_executed, analysis_details = handle_in_position(exchange, state, current_price, candles_primary)
                if trade_executed:
                    return # Bot tick is done for now
            else:
                signal, signal_reason, analysis_details = handle_no_position(exchange, balance, current_price, candles_primary, candles_trend)

    except Exception as e:
        logger.error(f"Bot tick error: {e}", exc_info=True)
        send_telegram_message(f"⚠️ <b>Bot Error</b>\n<code>{e}</code>")
        signal, signal_reason, analysis_details = "Error", str(e), str(e)
    finally:
        write_web_status({
            "signal": signal, 
            "signal_reason": signal_reason, 
            "analysis_details": analysis_details,
            "live_candles": candles_primary
        })

# Initialize parameters on startup
initialize_strategy_params()
