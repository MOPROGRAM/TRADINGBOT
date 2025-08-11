import os
import json
import asyncio
from dotenv import load_dotenv
from datetime import datetime, timedelta
import ccxt # Import ccxt to catch its exceptions

from logger import get_logger
from exchange import (
    get_exchange, fetch_candles, get_current_price, 
    create_market_buy_order, create_market_sell_order, 
    get_account_balance, fetch_last_buy_trade,
    start_websocket_client, stop_websocket_client, websocket_client
)
import signals
from state import load_state, save_state, clear_state, save_trade_history, get_default_state
from notifier import send_telegram_message
from shared_state import strategy_params
import tempfile
import atexit # For graceful shutdown

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
ATR_TRAILING_TP_ACTIVATION_MULTIPLIER = float(os.getenv('ATR_TRAILING_TP_ACTIVIFIER', 2.0))
ATR_TRAILING_SL_MULTIPLIER = float(os.getenv('ATR_TRAILING_SL_MULTIPLIER', 1.0))
ADX_TREND_STRENGTH = 25 # Hardcoded ADX trend strength threshold

POLL_SECONDS = int(os.getenv('POLL_SECONDS', 10))
DRY_RUN = os.getenv('DRY_RUN', 'True').lower() == 'true'
MIN_TRADE_USDT = float(os.getenv('MIN_TRADE_USDT', 10.0)) # New: Minimum trade amount in quote currency
SIGNAL_EXPIRATION_MINUTES = int(os.getenv('SIGNAL_EXPIRATION_MINUTES', 5)) # New: How long a signal remains valid

async def initialize_bot():
    """
    Initializes strategy parameters and waits for WebSocket data.
    """
    strategy_params["timeframe"] = TIMEFRAME
    strategy_params["trend_timeframe"] = TREND_TIMEFRAME
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
    strategy_params["buy_rsi_level"] = signals.BUY_RSI_LEVEL
    strategy_params["min_trade_usdt"] = MIN_TRADE_USDT
    strategy_params["adx_trend_strength"] = ADX_TREND_STRENGTH # Add ADX to strategy params
    logger.info(f"Strategy parameters initialized: {strategy_params}")
    
    # First, populate cache with historical data
    exchange = get_exchange()
    websocket_client.populate_historical_candles(exchange, SYMBOL)

    # Now, start the live WebSocket client
    start_websocket_client()
    atexit.register(stop_websocket_client)

    # Optional: Wait for the first LIVE candle to ensure connection is truly active
    # This is a good practice to make sure we don't start the loop with only historical data.
    logger.info("Waiting for live data stream to confirm connection...")
    live_data_ready = await websocket_client.wait_for_all_kline_data(timeout=60)
    if not live_data_ready:
        logger.critical("WebSocket connected but did not receive a live candle within the timeout. Exiting.")
        stop_websocket_client()
        exit(1)

    logger.info("Historical data populated and live stream confirmed. Starting main bot loop.")


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
    if not isinstance(balance, dict):
        logger.error(f"get_account_balance returned a non-dictionary type: {type(balance)}. Resetting to empty dict.")
        balance = {}

    base_currency = symbol.split('/')[0]
    base_currency_balance = balance.get(base_currency, 0)
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
                'sl_price': None,
                'tp_price': None,
                'trailing_sl_price': None
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
                'entry_price': current_price,
                'size': base_currency_balance,
                'timestamp': None,
                'highest_price_after_tp': None,
                'sl_price': None,
                'tp_price': None,
                'trailing_sl_price': None
            }
            save_state(state)
            msg = (f"⚠️ <b>State Sync (Fallback)</b>\nFound position, but no trade history.\n"
                   f"Re-created state with approximate entry price. PnL will be inaccurate.")
            send_telegram_message(msg)
            logger.info("Successfully synced position using fallback.")

def execute_sell_and_record_trade(exchange, state, reason, current_price):
    """
    Executes a market sell order using the current available balance and records the trade details.
    """
    logger.info(f"Executing sell for reason: {reason}")
    
    balance = get_account_balance(exchange)
    base_currency = SYMBOL.split('/')[0]
    actual_sell_amount = balance.get(base_currency, 0)
    
    if actual_sell_amount < 1:
        logger.error(f"Attempted to sell but found no sellable balance for {base_currency}.")
        send_telegram_message(f"⚠️ <b>State Mismatch</b>\nBot had a position for {base_currency}, but balance is zero. Clearing state.")
        clear_state()
        return False

    logger.info(f"State size was {state['position']['size']}, actual balance is {actual_sell_amount}. Selling actual balance.")
    sell_order = create_market_sell_order(exchange, SYMBOL, actual_sell_amount)
    
    if not sell_order:
        logger.error(f"Failed to create sell order for {reason}.")
        return False

    entry_price = state['position']['entry_price']
    exit_price = sell_order['price']
    pnl_percent = ((exit_price - entry_price) / entry_price) * 100
    
    trade_record = {
        "symbol": SYMBOL,
        "entry_price": entry_price,
        "exit_price": exit_price,
        "size": sell_order['amount'],
        "pnl_percent": pnl_percent,
        "reason": reason,
        "timestamp": sell_order['datetime']
    }
    save_trade_history(trade_record)
    
    msg = f"✅ <b>{reason.upper()} SELL</b>\nSymbol: <code>{SYMBOL}</code>\nPrice: <code>${current_price:.4f}</code>\nPnL: <code>{pnl_percent:.2f}%</code>"
    send_telegram_message(msg)
    logger.info(msg)
    
    last_signal_state = state.get('previous_buy_signal', False)
    new_state = get_default_state()
    new_state['previous_buy_signal'] = last_signal_state
    save_state(new_state)
    logger.info(f"State cleared, but previous_buy_signal ({last_signal_state}) was preserved.")
    
    return True

def write_web_status(status_data):
    """Atomically writes the bot status to a JSON file for the web UI."""
    data_to_write = {
        "signal": "N/A",
        "signal_reason": "Initializing...",
        "analysis_details": "Waiting for data...",
        "live_candles": [],
        "connection_status": websocket_client.get_connection_status() # Add connection status
    }
    data_to_write.update(status_data)

    try:
        with tempfile.NamedTemporaryFile('w', dir='.', delete=False) as tf:
            json.dump(data_to_write, tf)
            temp_path = tf.name
        os.rename(temp_path, 'web_status.json')
        # logger.info("web_status.json updated.") # Reduce log noise
    except Exception as e:
        logger.error(f"Failed to write web_status.json: {e}")
        if 'temp_path' in locals() and os.path.exists(temp_path):
            os.remove(temp_path)

def handle_in_position(exchange, state, current_price, candles):
    """
    Handles the logic when the bot is in a position.
    """
    if current_price is None:
        logger.error("handle_in_position called with a None current_price.")
        return "Error", "Price is None", False, "Critical error: Current price data is missing."

    entry_price = state['position'].get('entry_price')

    if entry_price is None or not isinstance(entry_price, (int, float)):
        logger.critical(f"Position state is corrupt: entry_price is '{entry_price}'. Clearing state.")
        send_telegram_message("CRITICAL ERROR: Position state corrupt. State cleared.")
        clear_state()
        return "Error", "Corrupt State", True, "Critical error: entry_price was missing."
    
    current_atr = signals.calculate_atr(candles)
    if current_atr is not None:
        if state['position']['sl_price'] is None or state['position']['tp_price'] is None:
            state['position']['sl_price'] = entry_price - (current_atr * ATR_SL_MULTIPLIER)
            state['position']['tp_price'] = entry_price + (current_atr * ATR_TP_MULTIPLIER)
            state['position']['trailing_sl_price'] = entry_price - (current_atr * ATR_SL_MULTIPLIER)
            save_state(state)
            logger.info(f"Initial ATR-based SL/TP set. SL: {state['position']['sl_price']:.4f}, TP: {state['position']['tp_price']:.4f}")
        
        activation_price = entry_price + (current_atr * ATR_TRAILING_TP_ACTIVATION_MULTIPLIER)
        if current_price > activation_price:
            highest_price = state['position'].get('highest_price_after_tp', entry_price)
            if current_price > highest_price:
                state['position']['highest_price_after_tp'] = current_price
                new_trailing_sl = current_price - (current_atr * ATR_TRAILING_SL_MULTIPLIER)
                state['position']['trailing_sl_price'] = max(state['position']['sl_price'], new_trailing_sl, state['position']['trailing_sl_price'] or 0)
                save_state(state)
                logger.info(f"Trailing stop updated. New highest price: {current_price:.4f}, New Trailing SL: {state['position']['trailing_sl_price']:.4f}")

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
            return "Sold", reason, True, f"Exit Reason: {reason}"

    is_sell_signal, analysis_details = signals.check_sell_signal(candles)
    if is_sell_signal:
        if execute_sell_and_record_trade(exchange, state, "Signal", current_price):
            return "Sold", "Exit Signal", True, analysis_details
    
    return "Waiting (in position)", "No exit signal.", False, analysis_details

def handle_no_position(exchange, state, balance, current_price, candles_primary, candles_15min, candles_trend):
    """
    Handles the logic when the bot is not in a position.
    """
    is_buy_signal, analysis_details = signals.check_buy_signal(
        candles_primary, 
        candles_15min, 
        candles_trend,
        adx_trend_strength=ADX_TREND_STRENGTH
    )
    previous_buy_signal = state.get('previous_buy_signal', False)

    state['previous_buy_signal'] = is_buy_signal
    save_state(state)

    if is_buy_signal and not previous_buy_signal:
        logger.info("BUY SIGNAL CROSSOVER DETECTED.")
        quote_currency = SYMBOL.split('/')[1]
        amount_usdt = balance.get(quote_currency, 0)
        
        if amount_usdt < MIN_TRADE_USDT:
            reason = f"Insufficient balance ({amount_usdt:.2f} {quote_currency})."
            logger.info(reason)
            return "Waiting (no position)", reason, analysis_details

        buy_order = create_market_buy_order(exchange, SYMBOL, amount_usdt)
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
            if 'pending_buy_signal' in new_state:
                del new_state['pending_buy_signal']
            save_state(new_state)
            msg = f"🟢 <b>BUY</b>\nSymbol: <code>{SYMBOL}</code>\nPrice: <code>${buy_order['price']:.4f}</code>\nReason: {analysis_details}"
            send_telegram_message(msg)
            logger.info(msg)
            return "Buy", analysis_details, analysis_details
    
    if is_buy_signal:
        return "Waiting (Signal Active)", "Buy signal is active, but no crossover.", analysis_details

    return "Waiting (no position)", "No buy signal.", analysis_details

async def run_bot_tick():
    """
    Runs a single check of the trading bot logic, now async.
    """
    logger.info("--- Running bot tick ---")
    
    signal = "Initializing"
    signal_reason = "Bot tick started."
    analysis_details = "Initializing..."
    candles_primary, candles_15min, candles_trend = [], [], []
    current_price = None
    balance = {}

    try:
        exchange = get_exchange()
        state = load_state()

        balance = get_account_balance(exchange)
        if not isinstance(balance, dict):
            logger.error(f"get_account_balance returned non-dict: {type(balance)}. Setting to empty dict.")
            balance = {}
        
        base_currency = SYMBOL.split('/')[0]
        base_currency_balance = balance.get(base_currency, 0)
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

        current_price = get_current_price(exchange, SYMBOL)
        candles_primary = fetch_candles(exchange, SYMBOL, TIMEFRAME, limit=200)
        candles_15min = fetch_candles(exchange, SYMBOL, '15m', limit=200)
        candles_trend = fetch_candles(exchange, SYMBOL, TREND_TIMEFRAME, limit=100)

        required_lengths = {
            "price": current_price is not None,
            "primary": len(candles_primary) >= 50,
            "15min": len(candles_15min) >= 200,
            "trend": len(candles_trend) >= 50
        }

        if not all(required_lengths.values()):
            missing = [k for k, v in required_lengths.items() if not v]
            signal, signal_reason = "Data Error", f"Insufficient data for: {', '.join(missing)}. Waiting for WebSocket cache."
            analysis_details = signal_reason
            logger.warning(signal_reason)
        else:
            if state.get('has_position'):
                signal, signal_reason, trade_executed, analysis_details = handle_in_position(exchange, state, current_price, candles_primary)
                if trade_executed:
                    return
            else:
                signal, signal_reason, analysis_details = handle_no_position(exchange, state, balance, current_price, candles_primary, candles_15min, candles_trend)

    except ccxt.BaseError as e:
        logger.error(f"Bot tick CCXT error: {e}", exc_info=True)
        send_telegram_message(f"⚠️ <b>Bot CCXT Error</b>\n<code>{e}</code>")
        signal, signal_reason, analysis_details = "Error", str(e), str(e)
    except Exception as e:
        logger.error(f"Bot tick generic error: {e}", exc_info=True)
        send_telegram_message(f"⚠️ <b>Bot Generic Error</b>\n<code>{e}</code>")
        signal, signal_reason, analysis_details = "Error", str(e), str(e)
    finally:
        write_web_status({
            "signal": signal, 
            "signal_reason": signal_reason, 
            "analysis_details": analysis_details,
            "live_candles": candles_primary,
            "current_price": current_price,
            "balance": balance,
            "state": load_state() # Send full state to UI
        })

async def main_loop():
    """The main async loop for the bot."""
    await initialize_bot()
    while True:
        await run_bot_tick()
        await asyncio.sleep(POLL_SECONDS)

if __name__ == "__main__":
    try:
        asyncio.run(main_loop())
    except KeyboardInterrupt:
        logger.info("Bot stopped by user.")
    finally:
        stop_websocket_client()
        logger.info("Shutdown complete.")
