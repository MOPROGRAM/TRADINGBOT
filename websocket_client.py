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
        self.kline_initialized = {interval: threading.Event() for interval in kline_intervals} # Event for each kline interval
        
        # New: Reconnection attempt counters and max delays
        self._kline_reconnection_attempts = {interval: 0 for interval in kline_intervals}
        self._ticker_reconnection_attempts = 0
        self._max_reconnect_delay = 60 # Max delay in seconds
        self.connection_status = {
            "ticker": "disconnected",
            **{interval: "disconnected" for interval in kline_intervals}
        }

    async def _connect_kline_websocket(self, interval: str):
        uri = f"wss://stream.binance.com:9443/ws/{self.symbol}@kline_{interval}"
        logger.info(f"Connecting to kline WebSocket: {uri}")
        while self.running:
            try:
                async with websockets.connect(uri) as websocket:
                    logger.info(f"Connected to kline WebSocket for {self.symbol}@{interval}")
                    self.connection_status[interval] = "connected"
                    self._kline_reconnection_attempts[interval] = 0 # Reset on successful connection
                    while self.running:
                        message = await websocket.recv()
                        data = json.loads(message)
                        if 'k' in data:
                            kline = data['k']
                            if 't' in kline and 'o' in kline and 'h' in kline and 'l' in kline and 'c' in kline and 'v' in kline: # Ensure all keys are present
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
                                    if not self.kline_initialized[interval].is_set():
                                        self.kline_initialized[interval].set()
                                        logger.info(f"Initial {interval} kline data received and cached.")
                                    # logger.debug(f"Received {interval} kline: {candle[0]} - {candle[4]}")
                            else:
                                logger.warning(f"Incomplete kline data received for {self.symbol}@{interval}: {kline}")
                        else:
                            logger.warning(f"Unexpected message format for kline {self.symbol}@{interval}: {data}")
            except websockets.exceptions.ConnectionClosed as e:
                self.connection_status[interval] = "disconnected"
                self._kline_reconnection_attempts[interval] += 1
                delay = min(2 ** self._kline_reconnection_attempts[interval], self._max_reconnect_delay)
                logger.warning(f"Kline WebSocket for {self.symbol}@{interval} closed ({e}). Reconnecting in {delay}s (attempt {self._kline_reconnection_attempts[interval]})...")
                await asyncio.sleep(delay)
            except Exception as e:
                self.connection_status[interval] = "disconnected"
                self._kline_reconnection_attempts[interval] += 1
                delay = min(2 ** self._kline_reconnection_attempts[interval], self._max_reconnect_delay)
                logger.error(f"An unexpected error occurred in kline WebSocket for {self.symbol}@{interval}: {e}", exc_info=True)
                logger.info(f"Reconnecting in {delay}s (attempt {self._kline_reconnection_attempts[interval]})...")
                await asyncio.sleep(delay)
            finally:
                if self.running: # Only update status if still intended to be running
                    self.connection_status[interval] = "connecting"
                else:
                    self.connection_status[interval] = "stopped"

    async def _connect_ticker_websocket(self):
        uri = f"wss://stream.binance.com:9443/ws/{self.symbol}@ticker"
        logger.info(f"Connecting to ticker WebSocket: {uri}")
        while self.running:
            try:
                async with websockets.connect(uri) as websocket:
                    logger.info(f"Connected to ticker WebSocket for {self.symbol}")
                    self.connection_status["ticker"] = "connected"
                    self._ticker_reconnection_attempts = 0 # Reset on successful connection
                    while self.running:
                        message = await websocket.recv()
                        data = json.loads(message)
                        if 'c' in data and 'E' in data: # 'c' is the close price (last price), 'E' is event time
                            with self.lock:
                                self.ticker_data['last_price'] = float(data['c'])
                                self.ticker_data['timestamp'] = data['E'] # Event time
                                if not self.initialized.is_set():
                                    self.initialized.set() # Signal that we have received the first ticker
                                    logger.info("Initial ticker data received.")
                                # logger.debug(f"Received ticker: {self.ticker_data['last_price']}")
                        else:
                            logger.warning(f"Incomplete ticker data received for {self.symbol}: {data}")
            except websockets.exceptions.ConnectionClosed as e:
                self.connection_status["ticker"] = "disconnected"
                self._ticker_reconnection_attempts += 1
                delay = min(2 ** self._ticker_reconnection_attempts, self._max_reconnect_delay)
                logger.warning(f"Ticker WebSocket for {self.symbol} closed ({e}). Reconnecting in {delay}s (attempt {self._ticker_reconnection_attempts})...")
                await asyncio.sleep(delay)
            except Exception as e:
                self.connection_status["ticker"] = "disconnected"
                self._ticker_reconnection_attempts += 1
                delay = min(2 ** self._ticker_reconnection_attempts, self._max_reconnect_delay)
                logger.error(f"An unexpected error occurred in ticker WebSocket for {self.symbol}: {e}", exc_info=True)
                logger.info(f"Reconnecting in {delay}s (attempt {self._ticker_reconnection_attempts})...")
                await asyncio.sleep(delay)
            finally:
                if self.running: # Only update status if still intended to be running
                    self.connection_status["ticker"] = "connecting"
                else:
                    self.connection_status["ticker"] = "stopped"

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

    async def wait_for_all_kline_data(self, timeout: int = 60):
        """Waits until initial kline data for all specified intervals has been received."""
        logger.info(f"Waiting for initial kline data for intervals: {self.kline_intervals} (timeout: {timeout}s)")
        start_time = time.time()
        while self.running and (time.time() - start_time < timeout or timeout == 0):
            all_ready = True
            for interval in self.kline_intervals:
                if not self.kline_initialized[interval].is_set():
                    all_ready = False
                    logger.info(f"Still waiting for {interval} kline data...")
                    break
            if all_ready:
                logger.info("All required kline data intervals initialized.")
                return True
            await asyncio.sleep(1) # Check every second
        logger.warning(f"Timeout waiting for all kline data to initialize after {timeout} seconds.")
        return False

    def get_kline_data(self, interval: str) -> list:
        with self.lock:
            return list(self.kline_data.get(interval, []))

    def get_latest_price(self) -> float:
        with self.lock:
            return self.ticker_data.get('last_price')

    def get_all_kline_data(self) -> dict:
        with self.lock:
            return {interval: list(data) for interval, data in self.kline_data.items()}

    def get_connection_status(self) -> dict:
        """Returns the current connection status for all streams."""
        return self.connection_status

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
