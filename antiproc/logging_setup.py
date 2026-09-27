"""
logging_setup.py — Rotating log to %APPDATA%\\AntiProcPet\\app.log
plus console output when run from a terminal.
"""

import logging
import sys
from logging.handlers import RotatingFileHandler

from antiproc.config import get_appdata_dir


def setup_logging(level: int = logging.INFO) -> logging.Logger:
    logger = logging.getLogger("antiproc")
    if logger.handlers:
        return logger  # Already set up

    logger.setLevel(level)
    fmt = logging.Formatter(
        "%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # File handler — rotating, 2 MB max, keep 3 backups
    log_file = get_appdata_dir() / "app.log"
    fh = RotatingFileHandler(
        log_file, maxBytes=2 * 1024 * 1024, backupCount=3, encoding="utf-8"
    )
    fh.setFormatter(fmt)
    logger.addHandler(fh)

    # Console handler (only when attached to a terminal)
    ch = logging.StreamHandler(sys.stdout)
    ch.setFormatter(fmt)
    logger.addHandler(ch)

    return logger
