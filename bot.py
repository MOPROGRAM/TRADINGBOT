import os
from dotenv import load_dotenv

from logger import get_logger
from exchange import get_exchange, fetch_candles, get_current_price, create_market_buy_order, create_market_sell_order, get_account_balance
from signals import check_buy_signal, check_sell_signal, check_sl_tp
from state import load_state, save_state, clear_state, save_trade_history
from notifier import send_telegram_message

# Load environment variables
load_dotenv()
logger = get_logger(__name__)

# Constants from .env
SYMBOL = os.getenv('SYMBOL', 'XLM/USDT')
TIMEFRAME = os.getenv('TIMEFRAME', '5m')
SL_PERCENT = float(os.getenv('STOP_LOSS_PERCENT', 0.5))
TP_PERCENT = float(os.getenv('TAKE_PROFIT_PERCENT', 1.5))
POLL_SECONDS = int(os.getenv('POLL_SECONDS', 10))
DRY_RUN = os.getenv('DRY_RUN', 'True').lower() == 'true'

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
        logger.warning(f"Found {base_currency_balance} {base_currency} on exchange without a local state. Re-creating state.")
        
        # We have a position, but no local state. Re-create it.
        # WARNING: We don't know the original entry price. We'll use the current price as an approximation.
        # This means PnL calculations for this trade will be inaccurate until it's closed and a new one starts.
        current_price = get_current_price(exchange, symbol)
        if not current_price:
            logger.error("Cannot re-create state: failed to fetch current price.")
            return

        state['has_position'] = True
        state['position']['entry_price'] = current_price # Approximation!
        state['position']['size'] = base_currency_balance
        state['position']['timestamp'] = None # We don't know the original timestamp
        state['position']['highest_price_after_tp'] = None
        save_state(state)
        
        msg = (f"⚠️ <b>State Sync</b>\nFound an existing {base_currency} position on the exchange.\n"
               f"Re-created local state. Entry price is an approximation. PnL will be inaccurate for this trade.")
        send_telegram_message(msg)
        logger.info("Successfully synced position from exchange.")

def run_bot_tick():
    """
    Runs a single check of the trading bot logic.
    """
    logger.info("Running bot tick...")
    
    exchange = get_exchange()
    
    # Sync position with exchange at the start of each tick
    # This ensures we don't miss trades if the bot restarts
    sync_position_with_exchange(exchange, SYMBOL)

    state = load_state()

    try:
        current_price = get_current_price(exchange, SYMBOL)
        if not current_price:
            logger.warning("Could not fetch current price.")
            return

        # Check for SL/TP first if we have a position
        if state['has_position']:
            # --- Trailing Stop Logic ---
            highest_price = state['position'].get('highest_price_after_tp')
            if highest_price and current_price > highest_price:
                state['position']['highest_price_after_tp'] = current_price
                save_state(state)
                logger.info(f"Trailing stop updated. New highest price: {current_price:.4f}")

            reason, price = check_sl_tp(current_price, state, SL_PERCENT, TP_PERCENT)
            
            if reason in ["SL", "TP"]:
                # Sell for Stop Loss or Take Profit
                sell_order = create_market_sell_order(exchange, SYMBOL, state['position']['size'])
                if sell_order:
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
                    
                    msg = f"✅ <b>{reason} SELL</b>\nSymbol: <code>{SYMBOL}</code>\nPrice: <code>${current_price:.4f}</code>\nPnL: <code>{pnl_percent:.2f}%</code>"
                    send_telegram_message(msg)
                    logger.info(msg)
                    clear_state()
                else:
                    logger.error("Failed to create sell order for SL/TP.")
                return # End tick after action

        # Position Management
        if not state['has_position']:
            # Fetch candles for signal checks ONLY when we don't have a position
            candles = fetch_candles(exchange, SYMBOL, TIMEFRAME, limit=2)
            if not candles or len(candles) < 2:
                logger.warning("Could not fetch enough candles for signal check.")
                return

            # Check for BUY signal
            if check_buy_signal(candles):
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
                        
                        msg = f"🟢 <b>BUY</b>\nSymbol: <code>{SYMBOL}</code>\nPrice: <code>${buy_order['price']:.4f}</code>"
                        send_telegram_message(msg)
                        logger.info(msg)
        else:
            # Fetch candles for signal checks ONLY when we have a position
            candles = fetch_candles(exchange, SYMBOL, TIMEFRAME, limit=2)
            if not candles or len(candles) < 2:
                logger.warning("Could not fetch enough candles for signal check.")
                return
            # Check for SELL signal (trend reversal)
            if check_sell_signal(candles):
                balance = get_account_balance(exchange)
                base_currency = SYMBOL.split('/')[0]
                size = balance.get(base_currency, {}).get('free', 0)
                if size > 0:
                    sell_order = create_market_sell_order(exchange, SYMBOL, size)
                    if sell_order:
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
                        "reason": "Trend Reversal",
                        "timestamp": sell_order['datetime']
                    }
                    save_trade_history(trade_record)
                    # --- End Record ---

                    msg = f"🔻 <b>Trend Reversal SELL</b>\nSymbol: <code>{SYMBOL}</code>\nPrice: <code>${current_price:.4f}</code>\nPnL: <code>{pnl_percent:.2f}%</code>"
                    send_telegram_message(msg)
                    logger.info(msg)
                    clear_state()

    except Exception as e:
        error_msg = f"⚠️ <b>Bot Error</b>\nAn unexpected error occurred: <code>{e}</code>"
        logger.error(f"An unexpected error occurred during bot tick: {e}", exc_info=True)
        send_telegram_message(error_msg)
