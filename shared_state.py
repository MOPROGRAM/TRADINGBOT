import threading

# This file holds shared state between the web server and the bot logic
# to avoid circular imports.

# A lock to ensure thread-safe access to shared data
shared_lock = threading.Lock()

# Global variable to hold status messages for the web UI
status_messages = []

# Holds the current signal calculated by the bot
current_signal = "Initializing"
current_signal_reason = "Waiting for data..."

# Holds the parameters of the current strategy
strategy_params = {
    "timeframe": "N/A",
    "buy_signal_period": "N/A",
    "sell_signal_period": "N/A",
    "sl_percent": "N/A",
    "tp_percent": "N/A",
    "trailing_tp_percent": "N/A",
    "trailing_tp_activation_percent": "N/A",
}

# Holds the latest candle data for the web UI
live_candles = []
