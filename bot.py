import os
import json
import asyncio
from dotenv import load_dotenv
from datetime import datetime, timedelta
import ccxt # Import ccxt to catch its exceptions

from logger import get_logger
from exchange import get_exchange, fetch_candles, get_current_price, create_market_buy_order, create_market_sell_order, get_account_balance, fetch_last_buy_trade
import signals
from state import load_state, save_state, clear_state, save_trade_history, get_default_state
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
MIN_TRADE_USDT = float(os.getenv('MIN_TRADE_USDT', 10.0)) # New: Minimum trade amount in quote currency
SIGNAL_EXPIRATION_MINUTES = int(os.getenv('SIGNAL_EXPIRATION_MINUTES', 5)) # New: How long a signal remains valid

def initialize_strategy_params():
    """
    Populates the shared state with the bot's current strategy parameters.
    """
    strategy_params["timeframe"] = TIMEFRAME
    strategy_params["trend_timeframe"] = TREND_TIMEFRAME # Add new timeframe to web status
    strategy_params["buy_signal_period"] = signals.VOLUME_SMA_PERIOD
    strategy_params["sell_signal_period_short"] = signals.EXIT_EMA_PERIOD_SHORT
    strategy_params["sell_signal_period_long"] = signals.EXIT_EMA_PERIOD_LONG
    strategy_params["trend_ema_period"] = signals.TREND_EMA_PERIOD
    strategy_params["exit_rsi_level"] = signals.EXIT_RSI_LEVEL
    strategy_params["atr_period"] = ATR_PERIOD
    strategy_params["atr_sl_multiplier"] = ATR_SL_MULTIPLIER
    strategy_params["atr_tp_multiplier"] = ATR_TP_MULTIPLIER
    strategy_params["atr_trailing_tp_activation_multiplier"] = ATR_TRAILING_TP_ACTIVATION_MULTIPLIER
    strategy_params["atr_trailing_sl_multiplier"] = ATR_TRAILING_SL_MULTIPLIER
    strategy_params["buy_rsi_level"] = signals.BUY_RSI_LEVEL # Add new RSI buy level
    strategy_params["min_trade_usdt"] = MIN_TRADE_USDT # Add minimum trade amount
    logger.info(f"Strategy parameters initialized: {strategy_params}")

async def sync_position_with_exchange(exchange, symbol):
    """
    Checks the exchange for an existing position and syncs it with the local state.
    """
    logger.info("Syncing position state with exchange...")
    state = load_state()

    if state.get('has_position'):
        logger.info("Local state already shows a position. Skipping sync.")
        return

    balance = await get_account_balance(exchange)
    base_currency = symbol.split('/')[0]
    base_currency_balance = balance.get(base_currency, {}).get('free', 0)
    min_position_amount = 1 

    if base_currency_balance > min_position_amount:
        logger.warning(f"Found {base_currency_balance:.6f} {base_currency} on exchange. Attempting to sync from trade history.")
        last_buy_trade = await fetch_last_buy_trade(exchange, symbol)
        
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
            current_price = await get_current_price(exchange, symbol)
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

async def execute_sell_and_record_trade(exchange, state, reason, current_price):
    """
    Executes a market sell order using the current available balance and records the trade details.
    This is more robust against state inconsistencies or precision issues.
    """
    logger.info(f"Executing sell for reason: {reason}")
    
    # --- Robust Sell Logic ---
    # 1. Get the actual available balance from the exchange right before selling.
    balance = await get_account_balance(exchange)
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
    sell_order = await create_market_sell_order(exchange, SYMBOL, actual_sell_amount)
    
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
    
    # --- Custom State Clearing to preserve signal state ---
    # Preserve the last signal state to prevent immediate re-buy
    last_signal_state = state.get('previous_buy_signal', False)
    new_state = load_state() # Load the latest state just in case
    new_state = get_default_state() # Get a clean default state
    new_state['previous_buy_signal'] = last_signal_state # Re-apply the signal state
    save_state(new_state)
    logger.info(f"State cleared, but previous_buy_signal ({last_signal_state}) was preserved.")
    
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

async def handle_in_position(exchange, state, current_price, candles):
    """
    Handles the logic when the bot is in a position.
    Returns: signal, signal_reason, trade_executed, analysis_details
    """
    # --- Critical Validation ---
    if current_price is None:
        logger.error("handle_in_position was called with a None current_price.")
        return "Error", "Price is None", False, "Critical error: Current price data is missing."

    entry_price = state['position'].get('entry_price')

    # --- Final, definitive check for state corruption ---
    if entry_price is None or not isinstance(entry_price, (int, float)):
        logger.critical(f"Position state is corrupt: entry_price is '{entry_price}'. Clearing state.")
        send_telegram_message("CRITICAL ERROR: Position state corrupt (entry_price is missing or invalid). State has been cleared.")
        clear_state()
        # Return True for trade_executed to halt further processing in this tick
        return "Error", "Corrupt State", True, "Critical error: entry_price was missing. State cleared."
    
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
            # --- Definitive Fix ---
            # Initialize highest_price to entry_price if it's None to prevent TypeError
            highest_price = state['position'].get('highest_price_after_tp')
            if highest_price is None:
                highest_price = entry_price

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
        if await execute_sell_and_record_trade(exchange, state, reason, current_price):
            # For SL/TP, the reason is clear and doesn't need a full breakdown.
            return "Sold", reason, True, f"Exit Reason: {reason}"

    # 3. Check for trend reversal SELL signal
    is_sell_signal, analysis_details = signals.check_sell_signal(candles)
    if is_sell_signal:
        # The sell reason is the detailed analysis itself
        if await execute_sell_and_record_trade(exchange, state, "Signal", current_price):
            return "Sold", "Exit Signal", True, analysis_details
    
    return "Waiting (in position)", "No exit signal.", False, analysis_details

async def handle_no_position(exchange, state, balance, current_price, candles_primary, candles_trend):
    """
    Handles the logic when the bot is not in a position, using multi-timeframe data and signal crossing.
    Returns: signal, signal_reason, analysis_details
    """
    # Get current signal state and previous signal state
    is_buy_signal, analysis_details = signals.check_buy_signal(candles_primary, candles_trend)
    previous_buy_signal = state.get('previous_buy_signal', False)

    # Update the state with the current signal for the next tick
    state['previous_buy_signal'] = is_buy_signal
    save_state(state)

    # --- Signal Crossing Logic ---
    # We only buy if the signal has just turned from False to True
    if is_buy_signal and not previous_buy_signal:
        logger.info("BUY SIGNAL CROSSOVER DETECTED: Signal changed from False to True.")
        quote_currency = SYMBOL.split('/')[1]
        amount_usdt = balance.get(quote_currency, {}).get('free', 0)
        
        if amount_usdt < MIN_TRADE_USDT:
            reason = f"Insufficient balance ({amount_usdt:.2f} {quote_currency}) for trade."
            logger.info(f"Not enough {quote_currency} balance ({amount_usdt:.2f}) for minimum trade ({MIN_TRADE_USDT:.2f}).")
            return "Waiting (no position)", reason, analysis_details

        if amount_usdt > 1: # Still keep this check for very small dust amounts
            buy_order = await create_market_buy_order(exchange, SYMBOL, amount_usdt)
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
                
                # Clear any pending buy signal after successful execution
                if 'pending_buy_signal' in new_state:
                    del new_state['pending_buy_signal']

                save_state(new_state)
                msg = f"🟢 <b>BUY</b>\nSymbol: <code>{SYMBOL}</code>\nPrice: <code>${buy_order['price']:.4f}</code>\nReason: {analysis_details}"
                send_telegram_message(msg)
                logger.info(msg)
                return "Buy", analysis_details, analysis_details
    
    # If buy signal is generated but not executed (e.g., insufficient balance), store it as pending
    if is_buy_signal:
        state['pending_buy_signal'] = {
            'timestamp': datetime.now().isoformat(),
            'price_at_signal': current_price,
            'analysis_details': analysis_details
        }
        save_state(state)
        return "Pending Buy", analysis_details, analysis_details

    # If buy signal is active but didn't cross over, just report it
    elif is_buy_signal:
        return "Waiting (Signal Active)", "Buy signal is active, but no crossover.", analysis_details

    return "Waiting (no position)", "No buy signal.", analysis_details

async def run_bot_tick():
    """
    Runs a single check of the trading bot logic.
    """
    logger.info("--- Running bot tick ---")
    
    signal = "Initializing"
    signal_reason = "Bot tick started."
    analysis_details = "Initializing..."
    candles_primary = []
    last_buy_signal_time = None # New: To store the timestamp of the last buy signal
    last_sell_signal_time = None # New: To store the timestamp of the last sell signal

    try:
        exchange = get_exchange()
        state = load_state()

        # --- State Validation ---
        balance = await get_account_balance(exchange)
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
            await sync_position_with_exchange(exchange, SYMBOL)
            state = load_state()

        # --- Fetch Data from WebSocket Cache ---
        current_price = await get_current_price(exchange, SYMBOL)
        candles_primary = await fetch_candles(exchange, SYMBOL, TIMEFRAME, limit=200) # Fetch more for trend analysis
        # For the trend timeframe, we might still need a REST call if not watched by websocket,
        # or we can derive it from the primary candles if the library supports it.
        # For simplicity, we'll continue to fetch it via REST for now.
        candles_trend = await exchange.fetch_ohlcv(SYMBOL, TREND_TIMEFRAME, limit=100)

        if not current_price or not candles_primary or len(candles_primary) < 50 or not candles_trend or len(candles_trend) < 50:
            signal, signal_reason = "Data Error", "Failed to fetch price or candle data for one or both timeframes."
            analysis_details = signal_reason
        else:
            # --- Main Logic ---
            if state.get('has_position'):
                # Note: handle_in_position still uses primary candles for SL/TP/Exit signals
                signal, signal_reason, trade_executed, analysis_details = await handle_in_position(exchange, state, current_price, candles_primary)
                if trade_executed:
                    # If a trade was executed (sell), update the sell signal time
                    if signal == "Sold": # Assuming "Sold" is the signal when a sell trade occurs
                        last_sell_signal_time = datetime.now().isoformat()
                    # Clear any pending sell signal after successful execution
                    state = load_state() # Reload state to ensure latest
                    if 'pending_sell_signal' in state:
                        del state['pending_sell_signal']
                        save_state(state)
                    return # Bot tick is done for now
            else:
                # Pass the state to handle_no_position
                signal, signal_reason, analysis_details = await handle_no_position(exchange, state, balance, current_price, candles_primary, candles_trend)
                # If a buy signal was generated, update the buy signal time
                if signal == "Buy": # Assuming "Buy" is the signal when a buy trade occurs
                    last_buy_signal_time = datetime.now().isoformat()

        # --- Review Pending Signals (if any) ---
        state = load_state() # Reload state to get latest
        
        # Review pending BUY signal
        pending_buy = state.get('pending_buy_signal')
        if pending_buy:
            signal_time = datetime.fromisoformat(pending_buy['timestamp'])
            time_since_signal = datetime.now() - signal_time
            
            if time_since_signal > timedelta(minutes=SIGNAL_EXPIRATION_MINUTES):
                logger.info(f"Pending BUY signal expired. Time since signal: {time_since_signal.total_seconds()/60:.1f} mins.")
                # Re-evaluate current buy conditions
                re_evaluate_buy, re_eval_details = signals.check_buy_signal(candles_primary, candles_trend)
                if re_evaluate_buy:
                    logger.info("Expired BUY signal still valid. Attempting re-entry.")
                    # Attempt to buy again (logic from handle_no_position)
                    quote_currency = SYMBOL.split('/')[1]
                    amount_usdt = balance.get(quote_currency, {}).get('free', 0)
                    if amount_usdt >= MIN_TRADE_USDT:
                        buy_order = await create_market_buy_order(exchange, SYMBOL, amount_usdt)
                        if buy_order:
                            new_state = load_state()
                            new_state['has_position'] = True
                            new_state['position'] = {
                                'entry_price': buy_order['price'],
                                'size': buy_order['amount'],
                                'timestamp': buy_order['datetime'],
                                'highest_price_after_tp': None,
                                'sl_price': None,
                                'tp_price': None,
                                'trailing_sl_price': None
                            }
                            if 'pending_buy_signal' in new_state: del new_state['pending_buy_signal']
                            save_state(new_state)
                            msg = f"🟢 <b>RE-ENTRY BUY</b>\nSymbol: <code>{SYMBOL}</code>\nPrice: <code>${buy_order['price']:.4f}</code>\nReason: {re_eval_details}"
                            send_telegram_message(msg)
                            logger.info(msg)
                            signal, signal_reason, analysis_details = "Re-Entry Buy", re_eval_details, re_eval_details
                        else:
                            signal, signal_reason, analysis_details = "Re-Entry Failed", "Could not execute re-entry buy order.", re_eval_details
                    else:
                        signal, signal_reason, analysis_details = "Re-Entry Skipped", "Insufficient balance for re-entry.", re_eval_details
                else:
                    logger.info("Expired BUY signal no longer valid. Discarding.")
                    del state['pending_buy_signal']
                    save_state(state)
                    signal, signal_reason, analysis_details = "Discarded Buy", "Expired signal no longer valid.", re_eval_details
            else:
                signal, signal_reason, analysis_details = "Pending Buy", "Waiting for execution or expiration.", pending_buy['analysis_details']

        # Review pending SELL signal (if any) - similar logic to buy
        pending_sell = state.get('pending_sell_signal')
        if pending_sell:
            signal_time = datetime.fromisoformat(pending_sell['timestamp'])
            time_since_signal = datetime.now() - signal_time
            
            if time_since_signal > timedelta(minutes=SIGNAL_EXPIRATION_MINUTES):
                logger.info(f"Pending SELL signal expired. Time since signal: {time_since_signal.total_seconds()/60:.1f} mins.")
                # Re-evaluate current sell conditions
                re_evaluate_sell, re_eval_details = signals.check_sell_signal(candles_primary) # Assuming sell signal uses primary candles
                if re_evaluate_sell:
                    logger.info("Expired SELL signal still valid. Attempting re-exit.")
                    # Attempt to sell again (logic from execute_sell_and_record_trade)
                    if await execute_sell_and_record_trade(exchange, state, "Re-Entry Sell Signal", current_price):
                        signal, signal_reason, analysis_details = "Re-Entry Sell", re_eval_details, re_eval_details
                    else:
                        signal, signal_reason, analysis_details = "Re-Entry Sell Failed", "Could not execute re-entry sell order.", re_eval_details
                else:
                    logger.info("Expired SELL signal no longer valid. Discarding.")
                    del state['pending_sell_signal']
                    save_state(state)
                    signal, signal_reason, analysis_details = "Discarded Sell", "Expired signal no longer valid.", re_eval_details
            else:
                signal, signal_reason, analysis_details = "Pending Sell", "Waiting for execution or expiration.", pending_sell['analysis_details']

    except ccxt.base.errors.DDoSProtection as e:
        logger.error(f"Bot tick DDoSProtection error: {e}", exc_info=True)
        send_telegram_message(f"⚠️ <b>Bot Error (DDoS Protection)</b>\n<code>{e}</code>")
        signal, signal_reason, analysis_details = "DDoS Protection", str(e), str(e)
    except Exception as e:
        logger.error(f"Bot tick error: {e}", exc_info=True)
        send_telegram_message(f"⚠️ <b>Bot Error</b>\n<code>{e}</code>")
        signal, signal_reason, analysis_details = "Error", str(e), str(e)
    finally:
        # Ensure exchange connection is closed
        try:
            await exchange.close()
            logger.info("Exchange connection closed.")
        except Exception as e:
            logger.error(f"Error closing exchange connection: {e}")

        write_web_status({
            "signal": signal, 
            "signal_reason": signal_reason, 
            "analysis_details": analysis_details,
            "live_candles": candles_primary,
            "last_buy_signal_time": last_buy_signal_time, # Add to web status
            "last_sell_signal_time": last_sell_signal_time # Add to web status
        })

# Initialize parameters on startup
initialize_strategy_params()
