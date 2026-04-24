# DiscogsMonitor

A Python script that monitors Discogs marketplace listings and sends a push notification via [ntfy](https://ntfy.sh) whenever a new listing appears.

## How it works

Discogs listing pages are sorted newest-first (`listed,desc`). The script saves a baseline snapshot of current listings using listing IDs and stable metadata, then on every subsequent run compares the live page against that snapshot. New offers are detected by unique item identifiers.

## Project structure

```
DiscogsMonitor/
├── init.py            # One-time baseline scan – run before first use
├── check.py           # Detects new listings and sends notifications
├── discogs_lib.py     # Shared utilities (parsing, URL validation, etc)
├── config.py          # Configuration from environment variables
├── start.sh           # Setup script: runs init, registers cron job, sends test push
├── watchlist.json     # List of releases to monitor
├── scans/             # Created automatically by init.py
└── logs/              # Created automatically (with automatic rotation)
    └── check.log
```

## Requirements

- Python 3.10+
- `requests`, `beautifulsoup4`, and `cloudscraper` (installed automatically by `start.sh`)
  - `cloudscraper` - bypasses Cloudflare protection on Discogs
- `curl` (for push notifications in `start.sh`)
- [ntfy](https://ntfy.sh) app on your phone

## Setup

### 1. Configure watchlist.json

Add the releases you want to monitor. The `link` should point to the marketplace page:

```json
[
  {
    "name": "My Favourite Record",
    "link": "https://www.discogs.com/sell/release/RELEASE_ID?sort=listed%2Cdesc&limit=25"
  }
]
```

**Note**: The script automatically validates and normalizes the `sort` query parameter to newest-first (`sort=listed,desc`), including URL-encoded variants (for example `sort=listed%2Cdesc`). If `sort` is missing, it is added automatically.

How to find the link:
1. Open a release page on Discogs
2. Click **For Sale**
3. Set sorting to **Listed Newest**
4. Copy the URL from the address bar

### 2. [Optional] Configure environment variables

Edit `.env` or export variables before running:

```bash
# Paths
export DISCOGS_WATCHLIST=/path/to/watchlist.json       # default: ./watchlist.json
export DISCOGS_SCANS_DIR=/path/to/scans                # default: ./scans
export DISCOGS_LOGS_DIR=/path/to/logs                  # default: ./logs
export DISCOGS_LOG_MAX_SIZE=5242880                     # 5MB, rotate when exceeded
export DISCOGS_LOG_BACKUPS=5                           # Keep 5 old log files

# Scraping
export DISCOGS_TIMEOUT=15                              # Request timeout (seconds)
export DISCOGS_RETRIES=2                               # Retry attempts for generic network/server errors
export DISCOGS_RETRIES_403=5                           # Retry attempts specifically for 403/429 responses
export DISCOGS_403_COOLDOWN=600                        # Cooldown after repeated 403/429 before continuing checks (seconds)
export DISCOGS_DELAY=15                                # Base delay between requests (seconds)
export DISCOGS_DELAY_JITTER=20                         # Random extra delay per request (0..N seconds) => 15-35s by default
export DISCOGS_STARTUP_JITTER=180                      # Random delay before each check run (0..N seconds)

# ntfy base URL
export DISCOGS_NTFY_URL=https://ntfy.sh                # or your self-hosted instance

# optional: set topic non-interactively for start.sh
export DISCOGS_NTFY_TOPIC=your-unique-topic
```

### 3. Install the ntfy app

Install [ntfy](https://ntfy.sh) on your phone and create your own unique topic (for example `my-discogs-alerts-2026`).
Subscribe to that topic in the app.

Set the same value in `config.py` (`NTFY_TOPIC = "..."`) or provide `DISCOGS_NTFY_TOPIC` when running `start.sh`.

If `NTFY_TOPIC` is empty, `start.sh` will prompt you for a topic and save it to `config.py` automatically.

Alternatively, [self-host ntfy](https://docs.ntfy.sh/install/) on your homelab and set `DISCOGS_NTFY_URL`.

### 4. Run the setup script

```bash
chmod +x start.sh
./start.sh
```

`start.sh` will:
1. Check for Python, curl, and required libraries (installing them if needed)
2. Run `init.py` to save the current state of all watched listings and send the baseline summary notification
3. Add `check.py` to your user crontab (no sudo required), running every 15 minutes
4. Print the resulting configuration summary and cron schedule

## Manual usage

Run the baseline scan manually:
```bash
python3 init.py
```

If `NTFY_TOPIC` is configured, `init.py` also sends a short completion summary after the baseline scan finishes.

Run a check manually:
```bash
python3 check.py
```

## Detection logic

| Situation | Result |
|---|---|
| New list is longer than saved | First N entries are reported as new |
| Same length but top entry changed | Entries not present before are reported as new |
| List was empty, now has listings | All current listings are reported as new |
| List is empty or unchanged | No notification |

### Watchlist changes without re-running init

- If you remove an item from `watchlist.json`, the old scan file remains on disk but is ignored.
- If you add or replace an item and its scan file is missing, `check.py` now bootstraps a baseline for that item automatically (without sending a "new listing" alert on that first run).
- Re-running `init.py` is still recommended after bigger watchlist edits to keep scan files clean and synchronized.

## Error handling

| Situation | Behaviour |
|---|---|
| Page unreachable / timeout | Push notification sent about the failure; scan file unchanged |
| No listings on page | Saves empty list; notifies when first listing appears |
| Push notification fails | Scan file is still updated to keep state in sync; push failure is logged |
| Missing scan file | Baseline is auto-created from current listings for that item |
| Missing `watchlist.json` | Script exits with an error |

## Stopping the monitor

```bash
crontab -e
# Remove the line containing "discogs-monitor"
```

## A note on rate limiting

Discogs may block excessive traffic. The script uses randomized browser-like request headers, session warmup, retry/backoff, and jittered timing. With a 15-minute cron interval and e.g. 10 releases, that's roughly one request every 90 seconds on average, with small random offsets to avoid a perfectly regular pattern. If you start getting 429/403 errors, increase `DISCOGS_DELAY`, `DISCOGS_DELAY_JITTER`, `DISCOGS_STARTUP_JITTER`, and (if needed) `DISCOGS_403_COOLDOWN`.