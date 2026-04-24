#!/usr/bin/env python3
"""
DiscogsMonitor/init.py

Scans prices from all URLs in watchlist.json and saves the baseline state
to the scans/ directory. Run once before using check.py for the first time.
"""

import json
import os
import random
import sys
import time

import config
from discogs_lib import (
    scan_file_name,
    fetch_listings,
    normalize_sort_url,
    save_scan_atomic,
)


def log(msg: str):
    print(msg)


def sleep_with_jitter(base_delay: int, jitter: int) -> None:
    """Sleep with optional random jitter to avoid fixed request cadence."""
    delay = base_delay + (random.randint(0, jitter) if jitter > 0 else 0)
    time.sleep(delay)


def load_watchlist() -> list[dict]:
    """Load and validate watchlist."""
    if not os.path.exists(config.WATCHLIST_FILE):
        log(f"[ERROR] File {config.WATCHLIST_FILE} not found.")
        sys.exit(1)
    
    try:
        with open(config.WATCHLIST_FILE, encoding="utf-8") as f:
            data = json.load(f)
    except json.JSONDecodeError as e:
        log(f"[ERROR] Invalid JSON in {config.WATCHLIST_FILE}: {e}")
        sys.exit(1)
    
    if not isinstance(data, list):
        log("[ERROR] watchlist.json must be a list of objects.")
        sys.exit(1)
    
    validated = []
    for idx, item in enumerate(data):
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
        log("[ERROR] No valid items in watchlist after validation.")
        sys.exit(1)
    
    return validated


def main():
    watchlist = load_watchlist()

    os.makedirs(config.SCANS_DIR, exist_ok=True)
    log(f"[INFO] Using '{config.SCANS_DIR}' directory. Existing scan files will be updated.")

    errors = []

    for idx, item in enumerate(watchlist):
        name = item.get("name", f"item_{idx}")
        url = item.get("link", "")

        if not url:
            log(f"[SKIP] #{idx} '{name}' – missing 'link' field.")
            continue

        log(f"[{idx}] Scanning: {name}")
        log(f"      URL: {url}")

        try:
            items = fetch_listings(
                url,
                config.HEADERS,
                config.REQUEST_TIMEOUT,
                retries=config.REQUEST_RETRIES,
                max_retry_delay=config.MAX_RETRY_DELAY,
            )
            status = "ok"
            log(f"      Found {len(items)} listing(s).")
        except ValueError as val_exc:
            items = []
            status = f"error: {val_exc}"
            log(f"      [URL ERROR] {val_exc}")
            errors.append({"id": idx, "name": name, "error": str(val_exc)})
        except Exception as exc:
            items = []
            status = f"error: {exc}"
            log(f"      [ERROR] {exc}")
            errors.append({"id": idx, "name": name, "error": str(exc)})

        scan_data = {
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

        scan_file = os.path.join(config.SCANS_DIR, scan_file_name(name, url))
        try:
            save_scan_atomic(scan_file, scan_data)
            log(f"      Saved → {scan_file}\n")
        except Exception as exc:
            log(f"      [ERROR] Failed to save scan file: {exc}\n")

        if idx < len(watchlist) - 1:
            sleep_with_jitter(config.DELAY_BETWEEN, config.DELAY_JITTER)

    # Summary
    log("=" * 50)
    log(f"Init complete. Scanned {len(watchlist)} item(s).")
    if errors:
        log(f"Errors ({len(errors)}):")
        for e in errors:
            log(f"  #{e['id']} '{e['name']}': {e['error']}")
    else:
        log("No errors.")




if __name__ == "__main__":
    main()#!/usr/bin/env python3
"""
DiscogsMonitor/init.py

Scans prices from all URLs in watchlist.json and saves the baseline state
to the scans/ directory. Run once before using check.py for the first time.
"""

import json
import os
import random
import sys
import time

import config
from discogs_lib import (
    scan_file_name,
    fetch_listings,
    normalize_sort_url,
    save_scan_atomic,
)


def log(msg: str):
    print(msg)


def sleep_with_jitter(base_delay: int, jitter: int) -> None:
    """Sleep with optional random jitter to avoid fixed request cadence."""
    delay = base_delay + (random.randint(0, jitter) if jitter > 0 else 0)
    time.sleep(delay)


def load_watchlist() -> list[dict]:
    """Load and validate watchlist."""
    if not os.path.exists(config.WATCHLIST_FILE):
        log(f"[ERROR] File {config.WATCHLIST_FILE} not found.")
        sys.exit(1)
    
    try:
        with open(config.WATCHLIST_FILE, encoding="utf-8") as f:
            data = json.load(f)
    except json.JSONDecodeError as e:
        log(f"[ERROR] Invalid JSON in {config.WATCHLIST_FILE}: {e}")
        sys.exit(1)
    
    if not isinstance(data, list):
        log("[ERROR] watchlist.json must be a list of objects.")
        sys.exit(1)
    
    validated = []
    for idx, item in enumerate(data):
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
        log("[ERROR] No valid items in watchlist after validation.")
        sys.exit(1)
    
    return validated


def main():
    watchlist = load_watchlist()

    os.makedirs(config.SCANS_DIR, exist_ok=True)
    log(f"[INFO] Using '{config.SCANS_DIR}' directory. Existing scan files will be updated.")

    errors = []

    for idx, item in enumerate(watchlist):
        name = item.get("name", f"item_{idx}")
        url = item.get("link", "")

        if not url:
            log(f"[SKIP] #{idx} '{name}' – missing 'link' field.")
            continue

        log(f"[{idx}] Scanning: {name}")
        log(f"      URL: {url}")

        try:
            items = fetch_listings(
                url,
                config.HEADERS,
                config.REQUEST_TIMEOUT,
                retries=config.REQUEST_RETRIES,
                max_retry_delay=config.MAX_RETRY_DELAY,
            )
            status = "ok"
            log(f"      Found {len(items)} listing(s).")
        except ValueError as val_exc:
            items = []
            status = f"error: {val_exc}"
            log(f"      [URL ERROR] {val_exc}")
            errors.append({"id": idx, "name": name, "error": str(val_exc)})
        except Exception as exc:
            items = []
            status = f"error: {exc}"
            log(f"      [ERROR] {exc}")
            errors.append({"id": idx, "name": name, "error": str(exc)})

        scan_data = {
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

        scan_file = os.path.join(config.SCANS_DIR, scan_file_name(name, url))
        try:
            save_scan_atomic(scan_file, scan_data)
            log(f"      Saved → {scan_file}\n")
        except Exception as exc:
            log(f"      [ERROR] Failed to save scan file: {exc}\n")

        if idx < len(watchlist) - 1:
            sleep_with_jitter(config.DELAY_BETWEEN, config.DELAY_JITTER)

    # Summary
    log("=" * 50)
    log(f"Init complete. Scanned {len(watchlist)} item(s).")
    if errors:
        log(f"Errors ({len(errors)}):")
        for e in errors:
            log(f"  #{e['id']} '{e['name']}': {e['error']}")
    else:
        log("No errors.")




if __name__ == "__main__":
    main()#!/usr/bin/env python3
"""
DiscogsMonitor/init.py

Scans prices from all URLs in watchlist.json and saves the baseline state
to the scans/ directory. Run once before using check.py for the first time.
"""

import json
import os
import sys
import time

import config
from discogs_lib import (
    scan_file_name,
    fetch_listings,
    normalize_sort_url,
    save_scan_atomic,
)


def log(msg: str):
    print(msg)


def load_watchlist() -> list[dict]:
    """Load and validate watchlist."""
    if not os.path.exists(config.WATCHLIST_FILE):
        log(f"[ERROR] File {config.WATCHLIST_FILE} not found.")
        sys.exit(1)
    
    try:
        with open(config.WATCHLIST_FILE, encoding="utf-8") as f:
            data = json.load(f)
    except json.JSONDecodeError as e:
        log(f"[ERROR] Invalid JSON in {config.WATCHLIST_FILE}: {e}")
        sys.exit(1)
    
    if not isinstance(data, list):
        log("[ERROR] watchlist.json must be a list of objects.")
        sys.exit(1)
    
    validated = []
    for idx, item in enumerate(data):
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
        log("[ERROR] No valid items in watchlist after validation.")
        sys.exit(1)
    
    return validated


def main():
    watchlist = load_watchlist()

    os.makedirs(config.SCANS_DIR, exist_ok=True)
    log(f"[INFO] Using '{config.SCANS_DIR}' directory. Existing scan files will be updated.")

    errors = []

    for idx, item in enumerate(watchlist):
        name = item.get("name", f"item_{idx}")
        url = item.get("link", "")

        if not url:
            log(f"[SKIP] #{idx} '{name}' – missing 'link' field.")
            continue

        log(f"[{idx}] Scanning: {name}")
        log(f"      URL: {url}")

        try:
            items = fetch_listings(
                url,
                config.HEADERS,
                config.REQUEST_TIMEOUT,
                retries=config.REQUEST_RETRIES,
                max_retry_delay=config.MAX_RETRY_DELAY,
            )
            status = "ok"
            log(f"      Found {len(items)} listing(s).")
        except ValueError as val_exc:
            items = []
            status = f"error: {val_exc}"
            log(f"      [URL ERROR] {val_exc}")
            errors.append({"id": idx, "name": name, "error": str(val_exc)})
        except Exception as exc:
            items = []
            status = f"error: {exc}"
            log(f"      [ERROR] {exc}")
            errors.append({"id": idx, "name": name, "error": str(exc)})

        scan_data = {
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

        scan_file = os.path.join(config.SCANS_DIR, scan_file_name(name, url))
        try:
            save_scan_atomic(scan_file, scan_data)
            log(f"      Saved → {scan_file}\n")
        except Exception as exc:
            log(f"      [ERROR] Failed to save scan file: {exc}\n")

        if idx < len(watchlist) - 1:
            time.sleep(config.DELAY_BETWEEN)

    # Summary
    log("=" * 50)
    log(f"Init complete. Scanned {len(watchlist)} item(s).")
    if errors:
        log(f"Errors ({len(errors)}):")
        for e in errors:
            log(f"  #{e['id']} '{e['name']}': {e['error']}")
    else:
        log("No errors.")




if __name__ == "__main__":
    main()
