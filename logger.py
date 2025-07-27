import logging
import os
from dotenv import load_dotenv

load_dotenv()

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
        
        # File Handler
        fh = logging.FileHandler('trading_bot.log')
        fh.setFormatter(formatter)
        logger.addHandler(fh)

    return logger
