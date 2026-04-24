#!/usr/bin/env python3
"""
DiscogsMonitor/check.py

Checks Discogs listings against the saved baseline and sends a push
notification via ntfy when new listings appear.

Intended to be run every 5 minutes via cron (set up by start.sh):
    */5 * * * * cd /path/to/project && python3 check.py >> logs/check.log 2>&1
"""

import json
import logging
import logging.handlers
import os
import random
import sys
import time

import requests

import config
from discogs_lib import (
    scan_file_name,
    fetch_listings,
    normalize_sort_url,
    save_scan_atomic,
)

# ─────────────────────────── LOGGING ──────────────────────────────────────────

# Create logs directory if needed
os.makedirs(config.LOGS_DIR, exist_ok=True)

# Setup rotating file logger
logger = logging.getLogger("discogsmonitor")
logger.setLevel(logging.DEBUG)

handler = logging.handlers.RotatingFileHandler(
    config.LOG_FILE,
    maxBytes=config.LOG_MAX_SIZE,
    backupCount=config.LOG_BACKUP_COUNT,
)
formatter = logging.Formatter("[%(asctime)s] %(message)s", datefmt="%Y-%m-%d %H:%M:%S")
handler.setFormatter(formatter)
logger.addHandler(handler)

# Also print to console
console = logging.StreamHandler(sys.stdout)
console.setFormatter(formatter)
logger.addHandler(console)


def log(msg: str):
    """Log a message to file and console."""
    logger.info(msg)


def sleep_with_jitter(base_delay: int, jitter: int) -> None:
    """Sleep with optional random jitter to avoid fixed request cadence."""
    delay = base_delay + (random.randint(0, jitter) if jitter > 0 else 0)
    time.sleep(delay)


# ─────────────────────────── FUNCTIONS ───────────────────────────────────────



def load_scan(scan_file: str) -> dict | None:
    if not os.path.exists(scan_file):
        return None
    with open(scan_file, encoding="utf-8") as f:
        try:
            return json.load(f)
        except json.JSONDecodeError as exc:
            log(f"[ERROR] Invalid JSON in '{scan_file}': {exc}")
            return None


def build_scan_data(idx: int, name: str, url: str, items: list[dict], status: str = "ok") -> dict:
    """Build normalized scan file payload."""
    return {
        "id": idx,
        "name": name,
        "url": url,
        "status": status,
        "items": items,
        "prices": [
            {
                "currency": item["currency"],
                "value": item["value"],
                "text": item["price_text"],
            }
            for item in items
        ],
    }


def save_scan(scan_file: str, data: dict):
    """Save scan data atomically using temp file + rename to prevent corruption."""
    try:
        save_scan_atomic(scan_file, data)
    except Exception as exc:
        log(f"[ERROR] Failed to save scan file '{scan_file}': {exc}")
        raise


def sanitize_header(text: str) -> str:
    """Remove emoji and non-ASCII chars from HTTP header (must be ASCII-safe)."""
    sanitized = "".join(c for c in text if ord(c) < 128)
    return sanitized.strip()  # Remove leading/trailing whitespace


def send_push(title: str, body: str, priority: str = "default", tags: str = ""):
    """
    Sends a push notification via ntfy.sh (or a self-hosted instance).
    priority: min / low / default / high / urgent
    tags: ntfy emoji tags, e.g. "cd,new" – https://docs.ntfy.sh/emojis/
    Raises an exception on failure.
    Note: HTTP headers must be ASCII-safe, so emoji are removed from title.
    Emoji in body and tags are preserved.
    """
    if not config.NTFY_TOPIC.strip():
        raise ValueError("NTFY_TOPIC is empty. Set it in config.py before sending notifications.")

    url = f"{config.NTFY_BASE_URL}/{config.NTFY_TOPIC}"
    headers = {
        "Title": sanitize_header(title),  # HTTP headers: ASCII only
        "Priority": priority,
    }
    if tags:
        headers["Tags"] = tags
    resp = requests.post(url, data=body, headers=headers, timeout=10)
    resp.raise_for_status()


def load_items_from_scan(scan_data: dict | None) -> list[dict]:
    if not scan_data:
        return []

    items = scan_data.get("items")
    if isinstance(items, list) and items:
        return items

    # Backwards compatibility with older scan files.
    prices = scan_data.get("prices", [])
    converted = []
    for p in prices:
        currency = p.get("currency", "")
        value = p.get("value")
        text = p.get("text", "")
        try:
            value = float(value)
        except (TypeError, ValueError):
            continue
        key = f"{currency}:{value}:{text}"
        converted.append({"key": key, "currency": currency, "value": value, "price_text": text})
    return converted


def detect_new_items(old_items: list[dict], new_items: list[dict]) -> list[dict]:
    """
    Compare previous and current listings and return any new entries.
    """
    if not old_items and new_items:
        return new_items

    if not new_items:
        return []

    old_keys = {item["key"] for item in old_items if item.get("key")}
    if not old_keys:
        return new_items

    return [item for item in new_items if item["key"] not in old_keys]


def load_watchlist() -> list[dict]:
    """Load watchlist with validation."""
    if not os.path.exists(config.WATCHLIST_FILE):
        log(f"[ERROR] {config.WATCHLIST_FILE} not found.")
        sys.exit(1)
    
    try:
        with open(config.WATCHLIST_FILE, encoding="utf-8") as f:
            watchlist = json.load(f)
    except json.JSONDecodeError as e:
        log(f"[ERROR] Invalid JSON in {config.WATCHLIST_FILE}: {e}")
        sys.exit(1)
    
    if not isinstance(watchlist, list):
        log(f"[ERROR] {config.WATCHLIST_FILE} must contain a JSON array.")
        sys.exit(1)
    
    validated = []
    for idx, item in enumerate(watchlist):
        name = item.get("name", f"item_{idx}").strip()
        url = item.get("link", "").strip()
        
        if not name or not url:
            log(f"[SKIP] #{idx} missing 'name' or 'link' field.")
            continue
        
        normalized_url = normalize_sort_url(url)
        if normalized_url != url:
            log(f"[WARN] #{idx} '{name}' URL had non-standard sort parameter - normalizing")
            url = normalized_url
        
        validated.append({"name": name, "link": url})
    
    if not validated:
        log("[ERROR] No valid items in watchlist.")
        sys.exit(1)
    
    return validated


def main():
    if config.CHECK_STARTUP_JITTER > 0:
        startup_delay = random.randint(0, config.CHECK_STARTUP_JITTER)
        if startup_delay > 0:
            log(f"[INFO] Startup jitter: sleeping {startup_delay}s before check.")
            time.sleep(startup_delay)

    log("=== Starting check ===")

    if not os.path.exists(config.SCANS_DIR):
        log(f"[ERROR] '{config.SCANS_DIR}' directory not found. Run init.py first.")
        try:
            send_push(
                "DiscogsMonitor – critical error",
                f"'{config.SCANS_DIR}' directory not found.\nRun init.py first.",
                priority="urgent",
                tags="warning",
            )
        except Exception as push_exc:
            log(f"[PUSH ERROR] {push_exc}")
        sys.exit(1)

    watchlist = load_watchlist()
    overall_errors = []

    for idx, item in enumerate(watchlist):
        name = item.get("name", f"item_{idx}")
        url = item.get("link", "")

        if not url:
            log(f"[SKIP] #{idx} '{name}' – missing 'link' field.")
            continue

        log(f"[{idx}] Checking: {name}")

        scan_file = os.path.join(config.SCANS_DIR, scan_file_name(name, url))
        legacy_scan_file = os.path.join(config.SCANS_DIR, f"{idx}.json")
        if not os.path.exists(scan_file) and os.path.exists(legacy_scan_file):
            scan_file = legacy_scan_file

        old_scan = load_scan(scan_file)
        if old_scan is None:
            log("      No scan file found. Bootstrapping baseline from current listings.")
            try:
                bootstrap_items = fetch_listings(
                    url,
                    config.HEADERS,
                    config.REQUEST_TIMEOUT,
                    retries=config.RETRIES_ON_403,
                    max_retry_delay=config.MAX_RETRY_DELAY,
                )
                bootstrap_scan = build_scan_data(idx, name, url, bootstrap_items)
                save_scan(scan_file, bootstrap_scan)
                log(f"      Baseline created with {len(bootstrap_items)} listing(s).")
            except Exception as exc:
                err_msg = str(exc)
                log(f"      [BOOTSTRAP ERROR] {err_msg}")
                overall_errors.append(f"#{idx} '{name}': bootstrap error: {err_msg}")
            continue

        old_items = load_items_from_scan(old_scan)

        # ── Fetch current listings ────────────────────────────────────────────
        try:
            new_items = fetch_listings(
                url,
                config.HEADERS,
                config.REQUEST_TIMEOUT,
                retries=config.REQUEST_RETRIES,
                max_retry_delay=config.MAX_RETRY_DELAY,
            )
            log(f"      Current listings: {len(new_items)}, previous: {len(old_items)}")
        except ValueError as val_exc:
            # URL validation error
            log(f"      [URL ERROR] {val_exc}")
            overall_errors.append(f"#{idx} '{name}': {val_exc}")
            if idx < len(watchlist) - 1:
                sleep_with_jitter(config.DELAY_BETWEEN, config.DELAY_JITTER)
            continue
        except requests.HTTPError as http_exc:
            # Handle HTTP errors specifically
            status_code = http_exc.response.status_code if http_exc.response is not None else 0
            err_msg = f"HTTP {status_code}: {str(http_exc)}"
            log(f"      [HTTP ERROR] {err_msg}")
            overall_errors.append(f"#{idx} '{name}': {err_msg}")
            
            # If 403/429 (rate limit), sleep MUCH longer and skip remaining items
            if status_code in {403, 429}:
                wait_time = 120  # 2 minutes on rate limit
                log(f"      Rate limited (HTTP {status_code}). Stopping scan and waiting {wait_time}s...")
                time.sleep(wait_time)
                break  # Exit the watchlist loop entirely
            
            if idx < len(watchlist) - 1:
                sleep_with_jitter(config.DELAY_BETWEEN, config.DELAY_JITTER)
            continue
        except Exception as exc:
            err_msg = str(exc)
            log(f"      [SCRAPING ERROR] {err_msg}")
            overall_errors.append(f"#{idx} '{name}': {err_msg}")

            try:
                send_push(
                    f"DiscogsMonitor – scan error: {name}",
                    f"Failed to fetch page.\n\nError: {err_msg}\n\nURL: {url}",
                    priority="high",
                    tags="warning",
                )
                log(f"      Error push sent.")
            except Exception as push_exc:
                log(f"      [PUSH ERROR] {push_exc}")

            if idx < len(watchlist) - 1:
                sleep_with_jitter(config.DELAY_BETWEEN, config.DELAY_JITTER)
            continue

        # ── Compare with the previous scan ───────────────────────────────────
        new_items_found = detect_new_items(old_items, new_items)

        if new_items_found:
            log(f"      ✓ Found {len(new_items_found)} new listing(s)!")

            new_list_str = "\n".join(
                f"→ {item['title']} | {item['price_text']} | {item['seller']}"
                for item in new_items_found
            )
            body = (
                f"{len(new_items_found)} new listing(s)!\n\n"
                f"{new_list_str}\n\n"
                f"Total listings: {len(new_items)}\n"
                f"{url}"
            )

            # ── Send push notification ────────────────────────────────────────
            try:
                send_push(
                    f"🎵 New listing: {name}",
                    body,
                    priority="high",
                    tags="cd,new",
                )
                log(f"      Push sent.")
            except Exception as push_exc:
                log(f"      [PUSH ERROR] {push_exc}")
                overall_errors.append(f"#{idx} '{name}': push error: {push_exc}")

            # ── Update scan file (ALWAYS, regardless of push result) ──────────
            new_scan = build_scan_data(idx, name, url, new_items)
            save_scan(scan_file, new_scan)
            log(f"      Scan file updated.")

        else:
            log(f"      No new listings.")
            # Update scan file if list length changed or status was not ok
            if old_scan.get("status", "ok") != "ok" or len(new_items) != len(old_items):
                new_scan = build_scan_data(idx, name, url, new_items)
                save_scan(scan_file, new_scan)

        if idx < len(watchlist) - 1:
            sleep_with_jitter(config.DELAY_BETWEEN, config.DELAY_JITTER)

    log("=== Check complete ===")
    if overall_errors:
        log(f"Errors this run ({len(overall_errors)}):")
        for e in overall_errors:
            log(f"  {e}")


if __name__ == "__main__":
    main()
