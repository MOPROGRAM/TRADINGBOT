import json
import os
from logger import get_logger

logger = get_logger(__name__)

STATE_FILE = 'trading_state.json'

def save_state(state):
    try:
        with open(STATE_FILE, 'w') as f:
            json.dump(state, f, indent=4)
        logger.info(f"Saved state: {state}")
    except IOError as e:
        logger.error(f"Error saving state to {STATE_FILE}: {e}")

def load_state():
    if not os.path.exists(STATE_FILE):
        logger.warning(f"{STATE_FILE} not found. Initializing with default state.")
        return get_default_state()
    
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
            "timestamp": None
        }
    }

def clear_state():
    save_state(get_default_state())
