import json
import os
from logger import get_logger

logger = get_logger(__name__)

STATE_FILE = 'trading_state.json'
HISTORY_FILE = 'trade_history.json'

def save_state(state):
    try:
        with open(STATE_FILE, 'w') as f:
            json.dump(state, f, indent=4)
        logger.info(f"Saved state: {state}")
    except IOError as e:
        logger.error(f"Error saving state to {STATE_FILE}: {e}")

def load_state():
    if not os.path.exists(STATE_FILE):
        logger.warning(f"{STATE_FILE} not found. Initializing and saving default state.")
        default_state = get_default_state()
        save_state(default_state)
        return default_state
    
    try:
        with open(STATE_FILE, 'r') as f:
            state = json.load(f)
            logger.info(f"Loaded state: {state}")
            return state
    except (IOError, json.JSONDecodeError) as e:
        logger.error(f"Error loading state from {STATE_FILE}: {e}. Using default state.")
        return get_default_state()

def get_default_state():
    return {
        "has_position": False,
        "position": {
            "entry_price": None,
            "size": None,
            "timestamp": None,
            "highest_price_after_tp": None
        }
    }

def clear_state():
    save_state(get_default_state())

def load_trade_history():
    if not os.path.exists(HISTORY_FILE):
        return []
    try:
        with open(HISTORY_FILE, 'r') as f:
            return json.load(f)
    except (IOError, json.JSONDecodeError) as e:
        logger.error(f"Error loading trade history from {HISTORY_FILE}: {e}")
        return []

def save_trade_history(trade):
    history = load_trade_history()
    history.insert(0, trade) # Add new trade to the beginning
    try:
        with open(HISTORY_FILE, 'w') as f:
            json.dump(history, f, indent=4)
        logger.info(f"Saved new trade to history: {trade}")
    except IOError as e:
        logger.error(f"Error saving trade history to {HISTORY_FILE}: {e}")
