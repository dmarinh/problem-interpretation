"""
Logging Configuration

Centralized logging setup for the application.
"""

import logging
import sys
from typing import Optional

from app.config import settings


def setup_logging(
    level: Optional[str] = None,
    format_string: Optional[str] = None,
) -> None:
    """
    Configure application logging.
    
    Args:
        level: Log level (uses settings.log_level if not provided)
        format_string: Custom format string
    """
    log_level = level or settings.log_level.value
    
    if format_string is None:
        format_string = (
            "%(asctime)s | %(levelname)-8s | %(name)s:%(lineno)d | %(message)s"
        )
    
    # Configure root logger
    logging.basicConfig(
        level=log_level,
        format=format_string,
        handlers=[
            logging.StreamHandler(sys.stdout),
        ],
    )
    
    # Set specific loggers
    logging.getLogger("uvicorn").setLevel(log_level)
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("chromadb").setLevel(logging.WARNING)
    logging.getLogger("sentence_transformers").setLevel(logging.WARNING)
    
    logger = logging.getLogger(__name__)
    logger.info(f"Logging configured at {log_level} level")


def get_logger(name: str) -> logging.Logger:
    """
    Get a logger with the given name.
    
    Args:
        name: Logger name (typically __name__)
        
    Returns:
        Configured logger
    """
    return logging.getLogger(name)