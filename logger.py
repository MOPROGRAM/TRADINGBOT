import logging
import os
from logging.handlers import RotatingFileHandler
from dotenv import load_dotenv

load_dotenv()

# Constants for live log
LIVE_LOG_FILE = 'live_bot.log'
LIVE_LOG_MAX_BYTES = 1024 * 1024  # 1 MB
LIVE_LOG_BACKUP_COUNT = 1

def get_logger(name):
    log_level = os.getenv('LOG_LEVEL', 'INFO').upper()
    logger = logging.getLogger(name)
    
    if not logger.handlers:
        logger.setLevel(log_level)
        formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
        
        # Console Handler
        ch = logging.StreamHandler()
        ch.setFormatter(formatter)
        logger.addHandler(ch)
        
        # File Handler for all logs
        fh = logging.FileHandler('trading_bot.log')
        fh.setFormatter(formatter)
        logger.addHandler(fh)

        # Rotating File Handler for live view on web UI
        # This handler will only capture INFO level logs from the 'bot' logger
        if name == 'bot':
            rfh = RotatingFileHandler(
                LIVE_LOG_FILE, 
                maxBytes=LIVE_LOG_MAX_BYTES, 
                backupCount=LIVE_LOG_BACKUP_COUNT
            )
            rfh.setFormatter(formatter)
            logger.addHandler(rfh)

    return logger
