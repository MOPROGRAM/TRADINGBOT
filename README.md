# Python Price Action Trading Bot

This is a sophisticated trading bot for Binance Spot that trades based on pure price action signals. It includes a real-time web interface for monitoring.

## Features

- **Trading Strategy**: 3-candle price action for XLM/USDT on the 5-minute timeframe.
- **Risk Management**: Stop-loss and take-profit levels.
- **Notifications**: Real-time alerts via Telegram for every trade and error.
- **Web Interface**: A modern dashboard built with FastAPI to monitor the bot's status, current price, open positions, and PnL.
- **Persistence**: Saves the trading state, so it can be resumed after a restart.
- **Dry Run Mode**: Simulate trading without using real funds.

## Project Structure

```
/
├── bot.py              # Main trading bot logic
├── signals.py          # Buy/sell signal generation
├── exchange.py         # CCXT integration for Binance
├── notifier.py         # Telegram notifications
├── state.py            # State management (position, etc.)
├── logger.py           # Structured logging
├── web/                # Web interface files
│   ├── main.py         # FastAPI backend
│   ├── templates/
│   │   └── index.html  # Frontend HTML
│   └── static/
│       └── style.css   # Frontend CSS
├── .env.example        # Example environment variables
├── requirements.txt    # Python dependencies
└── README.md           # This file
```

## Setup and Installation

### 1. Clone the Repository

```bash
git clone https://github.com/moprogram/tradingbot.git
cd tradingbot
```

### 2. Create a Virtual Environment and Install Dependencies

```bash
python -m venv venv
source venv/bin/activate  # On Windows use `venv\Scripts\activate`
pip install -r requirements.txt
```

### 3. Configure Environment Variables

Create a `.env` file by copying the example file:

```bash
cp .env.example .env
```

Now, edit the `.env` file with your credentials and desired settings.

#### `.env` Configuration

```
# Binance API Credentials
BINANCE_API_KEY=YOUR_API_KEY
BINANCE_API_SECRET=YOUR_API_SECRET

# Telegram Bot Credentials
TELEGRAM_BOT_TOKEN=YOUR_BOT_TOKEN
TELEGRAM_CHAT_ID=YOUR_CHAT_ID

# Trading Parameters
SYMBOL=XLM/USDT
TIMEFRAME=5m
AMOUNT_USDT=5.0
STOP_LOSS_PERCENT=1.5
TAKE_PROFIT_PERCENT=3.0

# Bot Configuration
POLL_SECONDS=10
DRY_RUN=True
LOG_LEVEL=INFO
```

**How to get your credentials:**

- **Binance API Keys**:
  1. Log in to your Binance account.
  2. Go to **API Management**.
  3. Create a new API key. Ensure that **Enable Spot & Margin Trading** is checked.
  4. For security, it's recommended to restrict API key access to your IP address.

- **Telegram Bot Token and Chat ID**:
  1. **Create a bot**: Talk to the `@BotFather` on Telegram. Send `/newbot` and follow the instructions. You will receive a bot token.
  2. **Get Chat ID**: Talk to `@userinfobot` on Telegram and it will give you your chat ID.

## How to Run the Bot

### Running in Dry Run Mode (Recommended First)

By default, `DRY_RUN` is set to `True` in the `.env` file. This will simulate trades without using real money.

1.  **Start the Trading Bot**:
    ```bash
    python bot.py
    ```

2.  **Start the Web Interface**:
    In a separate terminal:
    ```bash
    python web/main.py
    ```
    Then, open your browser to `http://localhost:8000`.

### Running in Live Mode

**⚠️ Warning: Use live mode at your own risk. Ensure your logic is well-tested in dry run mode first.**

1.  Edit your `.env` file and set `DRY_RUN=False`.
2.  Run the bot and web interface as described above.

## Testing

The project includes a testing script to verify the signal logic.

### Signal Testing Script

A script `test_signals.py` will be provided to simulate candle patterns and check if the `check_buy_signal` and `check_sell_signal` functions work as expected.

*(This section will be updated with the test script)*

---

*Disclaimer: This bot is for educational purposes only. Trading cryptocurrencies involves significant risk. The author is not responsible for any financial losses.*
