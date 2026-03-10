"""Simple logging system for Kaiwu backend.

Provides logging initialization with file and console output support.
Each run overwrites the log file (mode='w').
"""
import logging
from pathlib import Path
from typing import Optional


def init_logging(log_level: str = "INFO", log_file: Optional[str] = None) -> None:
    """
    Initialize the logging system.
    
    Args:
        log_level: Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL).
        log_file: Path to log file. If None, only console output is enabled.
                  Each run overwrites the file (mode='w').
    
    Behavior:
        - Outputs to console (always)
        - Outputs to file if log_file is provided
        - File is overwritten on each run (not appended)
        - Format: %(asctime)s [%(levelname)s] %(name)s: %(message)s
    """
    # Clear any existing handlers
    root_logger = logging.getLogger()
    root_logger.handlers.clear()
    
    # Set up handlers
    handlers: list[logging.Handler] = [logging.StreamHandler()]
    
    if log_file:
        log_path = Path(log_file)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        handlers.append(logging.FileHandler(log_file, mode='w', encoding='utf-8'))
    
    # Configure logging
    logging.basicConfig(
        level=getattr(logging, log_level.upper(), logging.INFO),
        format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
        handlers=handlers
    )
