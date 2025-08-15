# --- Bot & Strategy Parameters (Hardcoded) ---
# This file centralizes all strategy and bot configurations
# to avoid circular imports.

# -- Main Strategy Parameters --
SYMBOL = 'XLM/USDT'
TIMEFRAME = '15m'
TREND_TIMEFRAME = '1h'

# -- Indicator Settings --
TREND_SMA_PERIOD = 50
RSI_PERIOD = 14
RSI_BUY_LEVEL = 40

# -- Risk Management --
ATR_PERIOD = 14
ATR_SL_MULTIPLIER = 1.5
ATR_TP_MULTIPLIER = 3.0
ATR_TRAILING_TP_ACTIVATION_MULTIPLIER = 2.0
ATR_TRAILING_SL_MULTIPLIER = 1.0
SLIPPAGE_PERCENTAGE = 0.001 # Estimated slippage percentage (0.1%)

# -- General Bot Settings --
POLL_SECONDS = 10
DRY_RUN = False # Set to False for live trading, True for paper trading
MIN_TRADE_USDT = 10.0 # Minimum trade amount in quote currency
PENDING_BUY_CONFIRMATION_TIMEOUT_SECONDS = 120 # Timeout for pending buy
