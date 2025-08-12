import asyncio
import requests
from logger import get_logger

logger = get_logger(__name__)

# Cache for the Fear & Greed Index to avoid hitting the API on every single tick
fng_cache = {
    "value": None,
    "class": None,
    "timestamp": None
}
CACHE_DURATION_SECONDS = 3600  # Cache for 1 hour

def fetch_fng_index_sync():
    """
    Synchronous function to fetch the Fear & Greed Index.
    This is designed to be run in a separate thread to avoid blocking asyncio.
    """
    url = "https://api.alternative.me/fng/?limit=1"
    try:
        response = requests.get(url, timeout=10)
        response.raise_for_status()  # Raise an exception for bad status codes
        data = response.json()
        if "data" in data and len(data["data"]) > 0:
            fng_data = data["data"][0]
            value = int(fng_data["value"])
            classification = fng_data["value_classification"]
            logger.info(f"Successfully fetched Fear & Greed Index: {value} ({classification})")
            return value, classification
    except requests.exceptions.RequestException as e:
        logger.error(f"Error fetching Fear & Greed Index: {e}")
    except (KeyError, IndexError, ValueError) as e:
        logger.error(f"Error parsing Fear & Greed Index response: {e}")
    return None, None

async def get_fear_and_greed_index():
    """
    Asynchronously gets the Fear & Greed Index, using a cache to limit API calls.
    Runs the synchronous blocking call in a separate thread.
    """
    from datetime import datetime, timedelta

    now = datetime.now()
    
    # Check cache first
    if fng_cache["timestamp"] and (now - fng_cache["timestamp"]).total_seconds() < CACHE_DURATION_SECONDS:
        # logger.info("Returning cached Fear & Greed Index.") # Reduce log noise
        return fng_cache["value"], fng_cache["class"]

    logger.info("Fetching new Fear & Greed Index from API...")
    # Run the synchronous function in a thread pool
    value, classification = await asyncio.to_thread(fetch_fng_index_sync)

    if value is not None:
        fng_cache["value"] = value
        fng_cache["class"] = classification
        fng_cache["timestamp"] = now

    return fng_cache["value"], fng_cache["class"]
