# websocket_manager.py

import asyncio
import json
import websockets
from shared_state import bot_state
from datetime import datetime

SYMBOL = 'XLM/USDT'
STREAM_NAME = f"{SYMBOL.lower()}@ticker"

async def binance_websocket_client():
    """
    Connects to Binance WebSocket and updates the shared state with the latest price.
    """
    uri = f"wss://stream.binance.com:9443/ws/{STREAM_NAME}"
    
    while True:
        try:
            async with websockets.connect(uri) as websocket:
                print("--- WebSocket Client Connected ---")
                while True:
                    message = await websocket.recv()
                    data = json.loads(message)
                    if 'c' in data: # 'c' is the close price in the ticker stream
                        price = float(data['c'])
                        bot_state.update_state("current_price", price)
                        bot_state.update_state("last_update", datetime.now().isoformat())
                        # print(f"New price for {SYMBOL}: {price}") # Uncomment for debugging
        except Exception as e:
            print(f"WebSocket Error: {e}. Reconnecting in 5 seconds...")
            await asyncio.sleep(5)

if __name__ == "__main__":
    asyncio.run(binance_websocket_client())
