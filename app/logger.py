import sys
import logging
from pathlib import Path
from logging.handlers import RotatingFileHandler

LOGS_DIR = Path(__file__).resolve().parent.parent / "logs"
LOGS_DIR.mkdir(parents=True, exist_ok=True)
MAIN_LOG_FILE = LOGS_DIR / "operator.log"

def setup_logger(name: str = "ReelOperator") -> logging.Logger:
    logger = logging.getLogger(name)
    if logger.handlers:
        return logger

    logger.setLevel(logging.INFO)

    formatter = logging.Formatter(
        "[%(asctime)s] [%(levelname)s] [%(name)s:%(funcName)s]: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )

    # Console handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    # Rotating file handler (5MB, 5 backups)
    file_handler = RotatingFileHandler(
        MAIN_LOG_FILE,
        maxBytes=5 * 1024 * 1024,
        backupCount=5,
        encoding="utf-8"
    )
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    return logger

app_logger = setup_logger()
