import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

from config import settings


def setup_logging():
    """Set up comprehensive logging with both file and console handlers"""
    logs_dir = Path("logs")
    logs_dir.mkdir(exist_ok=True)

    detailed_formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(funcName)s:%(lineno)d - %(message)s'
    )
    simple_formatter = logging.Formatter(
        '%(asctime)s - %(levelname)s - %(message)s'
    )

    root_logger = logging.getLogger()

    # Set logging level based on environment
    if settings.is_production:
        log_level = logging.INFO
    else:
        log_level = logging.DEBUG

    root_logger.setLevel(log_level)
    root_logger.handlers.clear()

    file_handler = RotatingFileHandler(
        logs_dir / "climbing_app.log",
        maxBytes=10*1024*1024,
        backupCount=5,
        encoding='utf-8'
    )
    file_handler.setLevel(log_level)
    file_handler.setFormatter(detailed_formatter)
    root_logger.addHandler(file_handler)

    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(log_level)
    console_handler.setFormatter(simple_formatter)
    root_logger.addHandler(console_handler)

    app_logger = logging.getLogger("climbing_app")
    app_logger.setLevel(log_level)

    return app_logger 
