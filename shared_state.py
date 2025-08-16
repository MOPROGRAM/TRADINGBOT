# shared_state.py

import threading

# A thread-safe dictionary to hold the bot's live state.
# This allows the bot, dashboard, and websocket client to communicate.
class BotState:
    def __init__(self):
        self._lock = threading.Lock()
        self._state = {
            "current_price": None,
            "balance": {},
            "position": {},
            "has_position": False,
            "pnl": 0.0,
            "signal": "Initializing...",
            "signal_reason": "Waiting for bot...",
            "last_update": None,
        }

    def get_state(self):
        with self._lock:
            return self._state.copy()

    def update_state(self, key, value):
        with self._lock:
            self._state[key] = value

# Global instance of the bot state
bot_state = BotState()
