import os
import sys
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pathlib import Path

# Add project root to the Python path
sys.path.append(str(Path(__file__).parent.parent))

from exchange import get_exchange, get_current_price
from state import load_state
from logger import get_logger

logger = get_logger(__name__)
app = FastAPI()

# Mount static files
app.mount("/static", StaticFiles(directory="web/static"), name="static")

# Setup templates
templates = Jinja2Templates(directory="web/templates")

# Load symbol from environment
SYMBOL = os.getenv('SYMBOL', 'XLM/USDT')

@app.get("/", response_class=HTMLResponse)
async def read_root(request: Request):
    return templates.TemplateResponse("index.html", {"request": request, "symbol": SYMBOL})

@app.get("/api/status")
async def get_status():
    try:
        exchange = get_exchange()
        current_price = get_current_price(exchange, SYMBOL)
        state = load_state()
        
        pnl = 0
        if state.get('has_position') and state.get('position', {}).get('entry_price'):
            entry_price = state['position']['entry_price']
            if entry_price > 0:
                pnl = ((current_price - entry_price) / entry_price) * 100

        return {
            "symbol": SYMBOL,
            "current_price": current_price,
            "position": state.get('position', {}),
            "has_position": state.get('has_position', False),
            "pnl": pnl
        }
    except Exception as e:
        logger.error(f"Error in /api/status: {e}", exc_info=True)
        return {"error": str(e)}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
