import os
import json
from dotenv import load_dotenv

from logger import get_logger
from exchange import get_exchange, fetch_candles, get_current_price, create_market_buy_order, create_market_sell_order, get_account_balance, fetch_last_buy_trade
from signals import check_buy_signal, check_sell_signal, check_sl_tp
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
SL_PERCENT = float(os.getenv('STOP_LOSS_PERCENT', 0.5))
TP_PERCENT = float(os.getenv('TAKE_PROFIT_PERCENT', 1.5))
TRAILING_TP_PERCENT = float(os.getenv('TRAILING_TAKE_PROFIT_PERCENT', 1.0))
TRAILING_TP_ACTIVATION_PERCENT = float(os.getenv('TRAILING_TAKE_PROFIT_ACTIVATION_PERCENT', 0.5))
TRAILING_SL_PERCENT = float(os.getenv('TRAILING_STOP_LOSS_PERCENT', 0.5))
POLL_SECONDS = int(os.getenv('POLL_SECONDS', 10))
DRY_RUN = os.getenv('DRY_RUN', 'True').lower() == 'true'

def initialize_strategy_params():
    """
    Populates the shared state with the bot's current strategy parameters.
    """
    strategy_params["timeframe"] = TIMEFRAME
    # The periods are hardcoded in signals.py, so we'll reflect that.
    strategy_params["buy_signal_period"] = 10 
    strategy_params["sell_signal_period"] = 7
    strategy_params["sl_percent"] = SL_PERCENT
    strategy_params["tp_percent"] = TP_PERCENT
    strategy_params["trailing_tp_percent"] = TRAILING_TP_PERCENT
    strategy_params["trailing_tp_activation_percent"] = TRAILING_TP_ACTIVATION_PERCENT
    strategy_params["trailing_sl_percent"] = TRAILING_SL_PERCENT
    logger.info(f"Strategy parameters initialized: {strategy_params}")

def sync_position_with_exchange(exchange, symbol):
    """
    Checks the exchange for an existing position and syncs it with the local state.
    This is useful if the bot restarts and needs to pick up an existing trade.
    """
    logger.info("Syncing position state with exchange...")
    state = load_state()

    # If local state already has a position, trust it for now.
    if state.get('has_position'):
        logger.info("Local state already shows a position. Skipping sync.")
        return

    # Check balance on the exchange
    balance = get_account_balance(exchange)
    base_currency = symbol.split('/')[0]
    
    # Check if we have a significant amount of the base currency
    base_currency_balance = balance.get(base_currency, {}).get('free', 0)
    
    # Define a minimum amount to be considered a position, to avoid dust
    # This threshold might need adjustment depending on the asset.
    min_position_amount = 1 

    if base_currency_balance > min_position_amount:
        logger.warning(f"Found {base_currency_balance:.6f} {base_currency} on exchange without a local state. Attempting to sync from trade history.")
        
        last_buy_trade = fetch_last_buy_trade(exchange, symbol)
        
        if last_buy_trade:
            # Found a historical buy trade, let's use its data
            entry_price = last_buy_trade['price']
            entry_timestamp = last_buy_trade['datetime']
            entry_size = last_buy_trade['amount']
            
            # A check to see if the balance roughly matches the last trade size
            if abs(base_currency_balance - entry_size) / entry_size > 0.05: # 5% tolerance
                 logger.warning(f"The current balance ({base_currency_balance}) does not closely match the last trade size ({entry_size}). Using current balance.")
                 entry_size = base_currency_balance


            state['has_position'] = True
            state['position']['entry_price'] = entry_price
            state['position']['size'] = entry_size
            state['position']['timestamp'] = entry_timestamp
            state['position']['highest_price_after_tp'] = None
            save_state(state)
            
            msg = (f"✅ <b>State Sync</b>\nFound an existing {base_currency} position.\n"
                   f"Synced from last buy trade at ${entry_price:.4f} on {entry_timestamp}.")
            send_telegram_message(msg)
            # status_messages.append(msg) # No longer used
            logger.info("Successfully synced position from exchange trade history.")

        else:
            # Fallback to old method if no trade history is found
            logger.error("Could not find a recent buy trade in history. Falling back to approximation.")
            current_price = get_current_price(exchange, symbol)
            if not current_price:
                logger.error("Cannot re-create state: failed to fetch current price for fallback.")
                return

            state['has_position'] = True
            state['position']['entry_price'] = current_price # Approximation!
            state['position']['size'] = base_currency_balance
            state['position']['timestamp'] = None
            state['position']['highest_price_after_tp'] = None
            save_state(state)
            
            msg = (f"⚠️ <b>State Sync (Fallback)</b>\nFound an existing position, but no trade history.\n"
                   f"Re-created state with approximate entry price. PnL will be inaccurate.")
            send_telegram_message(msg)
            # status_messages.append(msg) # No longer used
            logger.info("Successfully synced position from exchange using fallback.")

def execute_sell_and_record_trade(exchange, state, reason, current_price):
    """
    Executes a market sell order and records the trade details.
    Returns True if successful, False otherwise.
    """
    logger.info(f"Executing sell for reason: {reason}")
    sell_order = create_market_sell_order(exchange, SYMBOL, state['position']['size'])
    
    if not sell_order:
        logger.error(f"Failed to create sell order for {reason}.")
        return False

    # --- Record Trade History ---
    entry_price = state['position']['entry_price']
    exit_price = sell_order['price']
    pnl_percent = ((exit_price - entry_price) / entry_price) * 100
    trade_record = {
        "symbol": SYMBOL,
        "entry_price": entry_price,
        "exit_price": exit_price,
        "size": state['position']['size'],
        "pnl_percent": pnl_percent,
        "reason": reason,
        "timestamp": sell_order['datetime']
    }
    save_trade_history(trade_record)
    # --- End Record ---
    
    msg = f"✅ <b>{reason.upper()} SELL</b>\nSymbol: <code>{SYMBOL}</code>\nPrice: <code>${current_price:.4f}</code>\nPnL: <code>{pnl_percent:.2f}%</code>"
    send_telegram_message(msg)
    logger.info(msg)
    clear_state()
    return True

def write_web_status(status_data):
    """Atomically writes the bot status to a JSON file for the web UI."""
    try:
        # Use a temporary file and atomic rename to prevent read/write race conditions
        with tempfile.NamedTemporaryFile('w', dir='.', delete=False) as tf:
            json.dump(status_data, tf)
            temp_path = tf.name
        
        os.rename(temp_path, 'web_status.json')
        logger.info("web_status.json updated successfully.")
    except Exception as e:
        logger.error(f"Failed to write web_status.json: {e}")
    finally:
        if 'temp_path' in locals() and os.path.exists(temp_path):
            os.remove(temp_path)


def run_bot_tick():
    """
    Runs a single check of the trading bot logic.
    """
    logger.info("Running bot tick...")
    
    # Define local variables for the current state
    signal = "Initializing"
    signal_reason = "Bot tick just started."
    candles = []

    try:
        exchange = get_exchange()
        state = load_state()

        # --- Real-time State Validation ---
        # This is the source of truth. Always check the actual balance.
        balance = get_account_balance(exchange)
        base_currency = SYMBOL.split('/')[0]
        base_currency_balance = balance.get(base_currency, {}).get('free', 0)
        min_position_amount = 1 # Minimum amount to be considered a real position

        if state.get('has_position'):
            position_size = state['position'].get('size', 0)
            # If our current balance is less than 90% of the recorded position size, we assume it was sold.
            if base_currency_balance < position_size * 0.9:
                logger.warning(f"State file shows a position of size {position_size}, but balance on exchange is only {base_currency_balance}. "
                               "This means the position was likely closed outside the bot. Clearing local state.")
                
                msg = (f"⚠️ <b>State Mismatch</b>\nLocal state showed an open position, but exchange balance is significantly lower.\n"
                       f"Assuming position is closed. Clearing local state to resync.")
                send_telegram_message(msg)
                # status_messages.append(msg) # No longer used
                
                # We don't know the exit details, so we can't create a perfect trade record.
                # The most important thing is to clear the state to allow new trades.
                clear_state()
                state = load_state() # Reload the cleared state

        elif not state.get('has_position') and base_currency_balance >= min_position_amount:
            logger.warning("Local state is empty, but found a position on the exchange. Running sync logic...")
            # This will attempt to find the entry price from trade history
            sync_position_with_exchange(exchange, SYMBOL)
            state = load_state() # Reload the potentially updated state
        # --- End of Real-time State Validation ---

        # --- Fetch all required data at the beginning ---
        current_price = get_current_price(exchange, SYMBOL)
        # Fetch more candles for indicator calculations (e.g., RSI, MACD)
        candles = fetch_candles(exchange, SYMBOL, TIMEFRAME, limit=100)
        
        # --- End of data fetching ---
        if not current_price or not candles or len(candles) < 50: # Ensure enough data for indicators
            signal = "Data Error"
            signal_reason = "Failed to fetch price or enough candle data for analysis."
        else:
            # Check for SL/TP first if we have a position
            if state['has_position']:
                # --- Trailing Stop Logic ---
                entry_price = state['position']['entry_price']
                activation_price = entry_price * (1 + TRAILING_TP_ACTIVATION_PERCENT / 100)
                
                # Check if trailing stop loss is active and update the highest price accordingly
                if current_price > activation_price:
                    highest_price = state['position'].get('highest_price_after_tp')
                    
                    # Initialize or update the highest price
                    if not highest_price or current_price > highest_price:
                        state['position']['highest_price_after_tp'] = current_price
                        save_state(state)
                        logger.info(f"Trailing stop price updated. New highest price: {current_price:.4f}")

                reason, price = check_sl_tp(current_price, state, SL_PERCENT, TP_PERCENT, TRAILING_TP_PERCENT, TRAILING_TP_ACTIVATION_PERCENT, TRAILING_SL_PERCENT)
                
                if reason in ["SL", "TP", "TTP"]:
                    if execute_sell_and_record_trade(exchange, state, reason, current_price):
                        return # End tick after successful action

            # Position Management
            if not state['has_position']:
            # Check for BUY signal
            is_buy_signal, buy_reason = check_buy_signal(candles)
            if is_buy_signal:
                signal = "Buy"
                signal_reason = buy_reason
                balance = get_account_balance(exchange)
                quote_currency = SYMBOL.split('/')[1]
                amount_usdt = balance.get(quote_currency, {}).get('free', 0)
                if amount_usdt > 1: # Ensure we have enough to trade
                    buy_order = create_market_buy_order(exchange, SYMBOL, amount_usdt)
                    if buy_order:
                        # Re-initialize state to ensure it's clean
                        state = load_state() # Use a fresh default state
                        state['has_position'] = True
                        state['position']['entry_price'] = buy_order['price']
                        state['position']['size'] = buy_order['amount']
                        state['position']['timestamp'] = buy_order['datetime']
                        state['position']['highest_price_after_tp'] = None # Ensure this is reset
                        save_state(state)
                        
                        msg = f"🟢 <b>BUY</b>\nSymbol: <code>{SYMBOL}</code>\nPrice: <code>${buy_order['price']:.4f}</code>\nReason: {buy_reason}"
                        send_telegram_message(msg)
                        logger.info(msg)
            else:
                signal = "Waiting (no position)"
                signal_reason = buy_reason or "No buy signal detected."
        else:
            # Check for SELL signal (trend reversal)
            is_sell_signal, sell_reason = check_sell_signal(candles)
            if is_sell_signal:
                signal = "Sell"
                signal_reason = sell_reason
                if execute_sell_and_record_trade(exchange, state, sell_reason, current_price):
                    # After a successful trade, update status and exit tick
                    write_web_status({"signal": "Sold", "signal_reason": sell_reason, "live_candles": candles})
                    return
            else:
                signal = "Waiting (in position)"
                signal_reason = sell_reason or "No sell signal detected."

    except Exception as e:
        error_msg = f"⚠️ <b>Bot Error</b>\nAn unexpected error occurred: <code>{e}</code>"
        logger.error(f"An unexpected error occurred during bot tick: {e}", exc_info=True)
        send_telegram_message(error_msg)
        signal = "Error"
        signal_reason = f"An unexpected error occurred: {e}"
    finally:
        # Always write the final status to the file
        write_web_status({"signal": signal, "signal_reason": signal_reason, "live_candles": candles})

# Initialize parameters once on startup
initialize_strategy_params()
