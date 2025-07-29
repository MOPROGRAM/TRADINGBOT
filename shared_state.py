# This file holds shared state between the web server and the bot logic
# to avoid circular imports.

# Global variable to hold status messages for the web UI
status_messages = []

# Holds the current signal calculated by the bot
current_signal = "Initializing"

# Holds the candles used for the latest signal calculation
live_candles = []

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
