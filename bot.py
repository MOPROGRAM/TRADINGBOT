import os
import time
from dotenv import load_dotenv

from logger import get_logger
from exchange import get_exchange, fetch_candles, get_current_price, create_market_buy_order, create_market_sell_order
from signals import check_buy_signal, check_sell_signal, check_sl_tp
from state import load_state, save_state, clear_state
from notifier import send_telegram_message

# Load environment variables
load_dotenv()
logger = get_logger(__name__)

# Constants from .env
SYMBOL = os.getenv('SYMBOL', 'XLM/USDT')
TIMEFRAME = os.getenv('TIMEFRAME', '5m')
AMOUNT_USDT = float(os.getenv('AMOUNT_USDT', 5.0))
SL_PERCENT = float(os.getenv('STOP_LOSS_PERCENT', 1.5))
TP_PERCENT = float(os.getenv('TAKE_PROFIT_PERCENT', 3.0))
POLL_SECONDS = int(os.getenv('POLL_SECONDS', 10))
DRY_RUN = os.getenv('DRY_RUN', 'True').lower() == 'true'

def run_bot():
    logger.info("Starting trading bot...")
    if DRY_RUN:
        logger.info("DRY RUN mode is enabled. No real trades will be executed.")
    
    exchange = get_exchange()
    state = load_state()

    while True:
        try:
            current_price = get_current_price(exchange, SYMBOL)
            if not current_price:
                time.sleep(POLL_SECONDS)
                continue

            # Check for SL/TP first if we have a position
            if state['has_position']:
                reason, price = check_sl_tp(current_price, state, SL_PERCENT, TP_PERCENT)
                if reason:
                    sell_order = create_market_sell_order(exchange, SYMBOL, state['position']['size'])
                    if sell_order:
                        msg = f"✅ {reason} SELL {SYMBOL} @ ${current_price:.4f}"
                        send_telegram_message(msg)
                        logger.info(msg)
                        clear_state()
                        state = load_state() # Reload state
                    else:
                        logger.error("Failed to create sell order for SL/TP.")
                    time.sleep(POLL_SECONDS)
                    continue

            # Fetch candles for signal checks
            candles = fetch_candles(exchange, SYMBOL, TIMEFRAME, limit=3)
            if not candles or len(candles) < 3:
                logger.warning("Could not fetch enough candles. Retrying...")
                time.sleep(POLL_SECONDS)
                continue

            # Position Management
            if not state['has_position']:
                # Check for BUY signal
                if check_buy_signal(candles):
                    buy_order = create_market_buy_order(exchange, SYMBOL, AMOUNT_USDT)
                    if buy_order:
                        state['has_position'] = True
                        state['position']['entry_price'] = buy_order['price']
                        state['position']['size'] = buy_order['amount']
                        state['position']['timestamp'] = buy_order['datetime']
                        save_state(state)
                        
                        msg = f"🟢 BUY {SYMBOL} @ ${buy_order['price']:.4f}"
                        send_telegram_message(msg)
                        logger.info(msg)
            else:
                # Check for SELL signal (trend reversal)
                if check_sell_signal(candles):
                    sell_order = create_market_sell_order(exchange, SYMBOL, state['position']['size'])
                    if sell_order:
                        msg = f"🔻 Trend Reversal SELL {SYMBOL} @ ${current_price:.4f}"
                        send_telegram_message(msg)
                        logger.info(msg)
                        clear_state()
                        state = load_state() # Reload state

        except Exception as e:
            error_msg = f"⚠️ An unexpected error occurred: {e}"
            logger.error(error_msg, exc_info=True)
            send_telegram_message(error_msg)

        time.sleep(POLL_SECONDS)

if __name__ == "__main__":
    run_bot()
