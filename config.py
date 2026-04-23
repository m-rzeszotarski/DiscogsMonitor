#!/usr/bin/env python3
"""
config.py

Configuration management for Discogs Monitor.
Loads settings from environment variables with defaults.
"""

import os
import sys
from pathlib import Path


def _get_int_env(key: str, default: int, min_val: int = 1) -> int:
    """Safely parse integer env vars with validation."""
    try:
        value = int(os.getenv(key, str(default)))
        if value < min_val:
            print(f"Warning: {key}={value} is less than minimum {min_val}, using {default}", file=sys.stderr)
            return default
        return value
    except ValueError:
        print(f"Warning: {key} value is not an integer, using default {default}", file=sys.stderr)
        return default


# Paths
BASE_DIR = Path(__file__).parent
WATCHLIST_FILE = os.getenv("DISCOGS_WATCHLIST", str(BASE_DIR / "watchlist.json"))
SCANS_DIR = os.getenv("DISCOGS_SCANS_DIR", str(BASE_DIR / "scans"))
LOGS_DIR = os.getenv("DISCOGS_LOGS_DIR", str(BASE_DIR / "logs"))
LOG_FILE = os.path.join(LOGS_DIR, "check.log")
LOG_MAX_SIZE = _get_int_env("DISCOGS_LOG_MAX_SIZE", 5242880, min_val=1000)  # 5MB default
LOG_BACKUP_COUNT = _get_int_env("DISCOGS_LOG_BACKUPS", 5, min_val=1)  # Keep 5 old logs

# ntfy.sh configuration (set your own unique topic)
NTFY_TOPIC = ""
NTFY_BASE_URL = os.getenv("DISCOGS_NTFY_URL", "https://ntfy.sh")

# Scraping configuration
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}
REQUEST_TIMEOUT = _get_int_env("DISCOGS_TIMEOUT", 15, min_val=5)  # seconds
REQUEST_RETRIES = _get_int_env("DISCOGS_RETRIES", 3, min_val=1)
DELAY_BETWEEN = _get_int_env("DISCOGS_DELAY", 3, min_val=1)  # seconds between requests

# Retry configuration
MAX_RETRY_DELAY = 30  # seconds - exponential backoff cap
