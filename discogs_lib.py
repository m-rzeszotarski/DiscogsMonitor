#!/usr/bin/env python3
"""
discogs_lib.py

Shared utilities for parsing Discogs marketplace listings.
Used by both init.py and check.py to avoid code duplication.
"""

import hashlib
import json
import os
import re
import tempfile
import time
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from typing import Optional

import requests
import cloudscraper
from bs4 import BeautifulSoup


scraper = cloudscraper.create_scraper(delay=10, captcha={"provider": "auto"})


def sanitize_filename(value: str) -> str:
    """Convert text to safe filename: lowercase, alphanumeric + dashes."""
    safe = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return safe[:50] or "item"


def scan_file_name(name: str, url: str) -> str:
    """Generate filename for scan data based on release name and URL."""
    digest = hashlib.sha1(url.encode("utf-8")).hexdigest()[:10]
    return f"{sanitize_filename(name)}-{digest}.json"


def save_scan_atomic(scan_file: str, data: dict) -> None:
    """Save scan data atomically using temp file + rename to prevent corruption."""
    try:
        # Create temp file in same directory to ensure filesystem is same
        temp_fd, temp_path = tempfile.mkstemp(dir=os.path.dirname(scan_file), text=True)
        try:
            with os.fdopen(temp_fd, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            # Atomic rename
            os.replace(temp_path, scan_file)
        except Exception:
            # Clean up temp file if something goes wrong
            try:
                os.unlink(temp_path)
            except Exception:
                pass
            raise
    except Exception as exc:
        raise IOError(f"Failed to save scan file '{scan_file}': {exc}") from exc


def build_item_url(href: str) -> str:
    """Convert relative Discogs URL to absolute."""
    href = href.strip()
    if href.startswith("/"):
        return f"https://www.discogs.com{href}"
    return href


def extract_text(element) -> str:
    """Extract and clean text from HTML element."""
    if not element:
        return ""
    return " ".join(element.stripped_strings).strip()


def parse_price_value(raw_value: str) -> Optional[float]:
    """Try to parse price value from string."""
    try:
        return float(raw_value)
    except (ValueError, TypeError):
        return None


def validate_sort_url(url: str) -> bool:
    """Verify URL has query parameter sort=listed,desc (any URL encoding)."""
    try:
        params = parse_qsl(urlsplit(url).query, keep_blank_values=True)
    except ValueError:
        return False

    for key, value in params:
        if key.lower() == "sort":
            return value.lower() == "listed,desc"
    return False


def normalize_sort_url(url: str) -> str:
    """Ensure URL contains sort=listed,desc while preserving other parameters."""
    parts = urlsplit(url)
    params = parse_qsl(parts.query, keep_blank_values=True)

    normalized = []
    sort_set = False
    for key, value in params:
        if key.lower() == "sort":
            if not sort_set:
                normalized.append((key, "listed,desc"))
                sort_set = True
            continue
        normalized.append((key, value))

    if not sort_set:
        normalized.append(("sort", "listed,desc"))

    query = urlencode(normalized, doseq=True)
    return urlunsplit((parts.scheme, parts.netloc, parts.path, query, parts.fragment))


def extract_seller_info(row) -> tuple[str, str]:
    """
    Extract seller name and ID from row.
    Returns (seller_name, seller_id) tuple.
    """
    # Try primary selector
    seller_element = row.select_one(".seller_block a[href^='/seller/']")
    if seller_element:
        seller = extract_text(seller_element)
        seller_href = seller_element.get("href", "")
        seller_id = seller_href.split("/")[-1] if "/seller/" in seller_href else ""
        return seller, seller_id

    # Try fallback: data-seller-username + data-seller-id
    show_shipping = row.select_one(".show-shipping-methods")
    if show_shipping:
        seller = show_shipping.get("data-seller-username", "").strip()
        seller_id = show_shipping.get("data-seller-id", "").strip()
        return seller, seller_id

    return "", ""


def fetch_listings(
    url: str,
    headers: dict,
    timeout: int = 15,
    retries: int = 1,
    max_retry_delay: int = 30,
) -> list[dict]:
    """
    Fetches a Discogs marketplace page and extracts all listing items from current page.
    Uses cloudscraper to bypass Cloudflare protection.
    
    Args:
        url: Discogs marketplace URL (should contain sort=listed%2Cdesc)
        headers: HTTP headers for requests (not used - cloudscraper handles it)
        timeout: Request timeout in seconds
        retries: Number of request attempts (including first)
        max_retry_delay: Maximum delay between retries in seconds
    
    Returns:
        List of listing dicts with item details from current page
    
    Raises:
        ValueError: If URL doesn't have proper sort parameter
        requests.RequestException: On network/HTTP errors
    """
    if not validate_sort_url(url):
        raise ValueError(
            f"URL must contain sort=listed%2Cdesc (newest-first sorting).\n"
            f"Got: {url}"
        )

    last_exc = None
    for attempt in range(1, max(1, retries) + 1):
        try:
            resp = scraper.get(url, timeout=timeout)
            resp.raise_for_status()
            break
        except requests.HTTPError as exc:
            last_exc = exc
            status_code = exc.response.status_code if exc.response is not None else None
            is_retryable = status_code in {403, 429, 500, 502, 503, 504}
            if not is_retryable or attempt >= max(1, retries):
                raise
        except requests.RequestException as exc:
            last_exc = exc
            if attempt >= max(1, retries):
                raise

        delay = min(max_retry_delay, 2 ** (attempt - 1))
        time.sleep(delay)

    if last_exc is not None and "resp" not in locals():
        raise last_exc

    soup = BeautifulSoup(resp.text, "html.parser")

    # Try primary selector
    rows = soup.select("table.table_block.mpitems.push_down.table_responsive tbody tr")
    if not rows:
        rows = soup.select("tr.shortcut_navigable")

    listings = []
    seen_keys = set()

    for row in rows:
        listing = _parse_row(row, seen_keys)
        if listing:
            listings.append(listing)

    return listings


def _parse_row(row, seen_keys: set) -> Optional[dict]:
    """
    Parse a single marketplace table row into listing dict.
    Returns None if row is invalid or duplicate.
    """
    try:
        price_span = row.find("span", class_="price")
        if not price_span:
            return None

        currency = price_span.get("data-currency", "").strip()
        raw_val = price_span.get("data-pricevalue", "")
        value = parse_price_value(raw_val)

        if value is None or not currency:
            return None

        title_link = row.select_one("a.item_description_title")
        title = extract_text(title_link)
        item_url = build_item_url(title_link.get("href", "")) if title_link else ""

        if not title:
            return None

        # Extract item ID
        item_id_elem = row.select_one("[data-item-id]")
        item_id = item_id_elem.get("data-item-id", "").strip() if item_id_elem else ""

        # Extract seller info
        seller, seller_id = extract_seller_info(row)

        shipping_text = extract_text(row.select_one("span.item_shipping"))
        condition = extract_text(row.select_one("p.item_condition"))
        price_text = extract_text(price_span)

        # Determine unique key (prefer item_id > url > fallback)
        if item_id:
            key = f"item:{item_id}"
        elif item_url:
            key = f"url:{item_url}"
        else:
            key = f"{currency}:{value}:{title}"

        if key in seen_keys:
            return None

        seen_keys.add(key)

        return {
            "key": key,
            "item_id": item_id,
            "item_url": item_url,
            "title": title,
            "seller": seller,
            "seller_id": seller_id,
            "currency": currency,
            "value": value,
            "price_text": price_text,
            "shipping": shipping_text,
            "condition": condition,
        }

    except (AttributeError, ValueError, TypeError):
        return None
