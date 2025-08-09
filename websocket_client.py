import asyncio
import json
import websockets
import threading
import time
from collections import deque
from logger import get_logger

logger = get_logger(__name__)

class BinanceWebSocketClient:
    def __init__(self, symbol: str, kline_intervals: list, max_len: int = 500):
        self.symbol = symbol.lower().replace('/', '') # e.g., "xlmusdt"
        self.kline_intervals = kline_intervals # e.g., ['5m', '15m', '1h']
        self.max_len = max_len # Max number of candles to store
        
        self.kline_data = {interval: deque(maxlen=max_len) for interval in kline_intervals}
        self.ticker_data = {} # Stores latest ticker data
        self.lock = threading.Lock() # For thread-safe access to data
        self.websocket_threads = []
        self.running = False
        self.initialized = threading.Event() # Event to signal when the first ticker is received

    async def _connect_kline_websocket(self, interval: str):
        uri = f"wss://stream.binance.com:9443/ws/{self.symbol}@kline_{interval}"
        logger.info(f"Connecting to kline WebSocket: {uri}")
        while self.running:
            try:
                async with websockets.connect(uri) as websocket:
                    logger.info(f"Connected to kline WebSocket for {self.symbol}@{interval}")
                    while self.running:
                        message = await websocket.recv()
                        data = json.loads(message)
                        if 'k' in data:
                            kline = data['k']
                            # [timestamp, open, high, low, close, volume, close_time, quote_asset_volume, number_of_trades, taker_buy_base_asset_volume, taker_buy_quote_asset_volume, ignore]
                            candle = [
                                kline['t'], # timestamp
                                float(kline['o']), # open
                                float(kline['h']), # high
                                float(kline['l']), # low
                                float(kline['c']), # close
                                float(kline['v'])  # volume
                            ]
                            with self.lock:
                                self.kline_data[interval].append(candle)
                                # logger.debug(f"Received {interval} kline: {candle[0]} - {candle[4]}")
            except websockets.exceptions.ConnectionClosed:
                logger.warning(f"Kline WebSocket for {self.symbol}@{interval} closed. Reconnecting in 5s...")
                await asyncio.sleep(5)
            except Exception as e:
                logger.error(f"An unexpected error occurred in kline WebSocket for {self.symbol}@{interval}: {e}", exc_info=True)
                logger.info("Reconnecting in 10s...")
                await asyncio.sleep(10)

    async def _connect_ticker_websocket(self):
        uri = f"wss://stream.binance.com:9443/ws/{self.symbol}@ticker"
        logger.info(f"Connecting to ticker WebSocket: {uri}")
        while self.running:
            try:
                async with websockets.connect(uri) as websocket:
                    logger.info(f"Connected to ticker WebSocket for {self.symbol}")
                    while self.running:
                        message = await websocket.recv()
                        data = json.loads(message)
                        if 'c' in data: # 'c' is the close price (last price)
                            with self.lock:
                                self.ticker_data['last_price'] = float(data['c'])
                                self.ticker_data['timestamp'] = data['E'] # Event time
                                if not self.initialized.is_set():
                                    self.initialized.set() # Signal that we have received the first ticker
                                # logger.debug(f"Received ticker: {self.ticker_data['last_price']}")
            except websockets.exceptions.ConnectionClosed:
                logger.warning(f"Ticker WebSocket for {self.symbol} closed. Reconnecting in 5s...")
                await asyncio.sleep(5)
            except Exception as e:
                logger.error(f"An unexpected error occurred in ticker WebSocket for {self.symbol}: {e}", exc_info=True)
                logger.info("Reconnecting in 10s...")
                await asyncio.sleep(10)

    def _run_websocket_loop(self, coro):
        """Helper to run an async coroutine in a new event loop."""
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(coro)
        loop.close()

    def start(self):
        if self.running:
            logger.warning("WebSocket client is already running.")
            return

        self.running = True
        logger.info("Starting Binance WebSocket client...")

        # Start kline threads
        for interval in self.kline_intervals:
            thread = threading.Thread(target=self._run_websocket_loop, args=(self._connect_kline_websocket(interval),))
            thread.daemon = True
            thread.start()
            self.websocket_threads.append(thread)
            time.sleep(0.1) # Small delay to avoid immediate rate limits on connection

        # Start ticker thread
        ticker_thread = threading.Thread(target=self._run_websocket_loop, args=(self._connect_ticker_websocket(),))
        ticker_thread.daemon = True
        ticker_thread.start()
        self.websocket_threads.append(ticker_thread)
        
        logger.info("All WebSocket threads started.")

    def stop(self):
        if not self.running:
            logger.warning("WebSocket client is not running.")
            return

        logger.info("Stopping Binance WebSocket client...")
        self.running = False
        # Give some time for loops to exit
        time.sleep(1) 
        # Threads are daemon, so they will exit when main program exits.
        # No need to explicitly join them unless we want to wait for them.
        self.websocket_threads = [] # Clear references
        logger.info("Binance WebSocket client stopped.")

    def get_kline_data(self, interval: str) -> list:
        with self.lock:
            return list(self.kline_data.get(interval, []))

    def get_latest_price(self) -> float:
        with self.lock:
            return self.ticker_data.get('last_price')

    def get_all_kline_data(self) -> dict:
        with self.lock:
            return {interval: list(data) for interval, data in self.kline_data.items()}

# Example Usage (for testing)
if __name__ == "__main__":
    # This part is for local testing of the WebSocket client
    # It won't run when imported by other modules
    logger.info("Running WebSocket client test...")
    client = BinanceWebSocketClient(symbol="BTC/USDT", kline_intervals=['1m', '5m'])
    client.start()

    try:
        while True:
            latest_price = client.get_latest_price()
            kline_1m = client.get_kline_data('1m')
            kline_5m = client.get_kline_data('5m')

            print(f"Latest Price: {latest_price}")
            if kline_1m:
                print(f"Latest 1m candle close: {kline_1m[-1][4]}")
            if kline_5m:
                print(f"Latest 5m candle close: {kline_5m[-1][4]}")
            
            time.sleep(5) # Print every 5 seconds
    except KeyboardInterrupt:
        logger.info("Test interrupted by user.")
    finally:
        client.stop()
        logger.info("WebSocket client test finished.")
