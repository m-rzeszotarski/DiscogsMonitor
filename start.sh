#!/usr/bin/env bash
# start.sh – initialises Discogs Monitor and registers check.py in crontab
#
# Usage:
#   chmod +x start.sh
#   ./start.sh
#
# Does NOT require sudo – each user has their own crontab.

set -euo pipefail

# ─────────────────────────── CONFIG ──────────────────────────────────────────

NTFY_BASE_URL="${DISCOGS_NTFY_URL:-https://ntfy.sh}"

# Scans interval [min]
CRON_INTERVAL=5

# Python interpreter
PYTHON="${PYTHON:-python3}"

# ─────────────────────────────────────────────────────────────────────────────

# Absolute path
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CONFIG_FILE="$SCRIPT_DIR/config.py"

INIT_SCRIPT="$SCRIPT_DIR/init.py"
CHECK_SCRIPT="$SCRIPT_DIR/check.py"
LOG_DIR="${DISCOGS_LOGS_DIR:-$SCRIPT_DIR/logs}"
LOG_FILE="$LOG_DIR/check.log"
CRON_JOB="*/$CRON_INTERVAL * * * * cd \"$SCRIPT_DIR\" && export DISCOGS_NTFY_URL=\"$NTFY_BASE_URL\" && $PYTHON \"$CHECK_SCRIPT\" 2>&1"
CRON_MARKER="# discogs-monitor"

# ─────────────────────── Helper functions ────────────────────────────────────

info()    { echo "[INFO]  $*"; }
success() { echo "[OK]    $*"; }
error()   { echo "[ERROR] $*" >&2; }

send_push() {
    local title="$1"
    local body="$2"
    local priority="${3:-default}"
    local tags="${4:-}"
    local NTFY_TOPIC=$($PYTHON -c "import sys; sys.path.insert(0, '$SCRIPT_DIR'); from config import NTFY_TOPIC; print(NTFY_TOPIC)")
    if [[ -z "${NTFY_TOPIC// /}" ]]; then
        error "NTFY_TOPIC is empty in config.py"
        return 1
    fi

    curl -s \
        -H "Title: $title" \
        -H "Priority: $priority" \
        ${tags:+-H "Tags: $tags"} \
        -d "$body" \
        "$NTFY_BASE_URL/$NTFY_TOPIC" \
        --max-time 10 \
        -o /dev/null
}

get_config_topic() {
    $PYTHON -c "import sys; sys.path.insert(0, '$SCRIPT_DIR'); from config import NTFY_TOPIC; print(NTFY_TOPIC)"
}

set_config_topic() {
    local topic="$1"
    TOPIC="$topic" CONFIG_PATH="$CONFIG_FILE" $PYTHON <<'PY'
import os
import re
from pathlib import Path

path = Path(os.environ["CONFIG_PATH"])
topic = os.environ["TOPIC"]
text = path.read_text(encoding="utf-8")
updated, count = re.subn(r'(?m)^NTFY_TOPIC\s*=\s*".*"\s*$', f'NTFY_TOPIC = "{topic}"', text)
if count != 1:
    raise SystemExit("Could not update NTFY_TOPIC in config.py")
path.write_text(updated, encoding="utf-8")
PY
}

ensure_ntfy_topic() {
    local current_topic
    current_topic="$(get_config_topic)"

    if [[ -n "${DISCOGS_NTFY_TOPIC:-}" ]]; then
        if [[ "$current_topic" != "$DISCOGS_NTFY_TOPIC" ]]; then
            info "Setting ntfy topic from DISCOGS_NTFY_TOPIC env var."
            set_config_topic "$DISCOGS_NTFY_TOPIC"
            success "ntfy topic updated in config.py"
        fi
        return
    fi

    if [[ -n "${current_topic// /}" ]]; then
        return
    fi

    echo ""
    info "NTFY_TOPIC is empty in config.py"
    echo "Choose your unique ntfy topic (letters, digits, ., _, -)."

    while true; do
        read -r -p "Enter ntfy topic: " topic
        if [[ -z "${topic// /}" ]]; then
            error "Topic cannot be empty."
            continue
        fi
        if [[ ! "$topic" =~ ^[A-Za-z0-9._-]+$ ]]; then
            error "Invalid topic. Allowed characters: letters, digits, ., _, -"
            continue
        fi
        set_config_topic "$topic"
        success "ntfy topic saved to config.py"
        break
    done
}

# ─────────────────────── Requirements check ──────────────────────────────────

echo "========================================"
echo " Discogs Monitor - setup"
echo "========================================"
echo ""

if ! command -v "$PYTHON" &>/dev/null; then
    error "Python not found ('$PYTHON'). Install Python 3 or set the PYTHON env var."
    exit 1
fi
success "Python: $($PYTHON --version)"

if ! command -v curl &>/dev/null; then
    error "curl not found. Install it: sudo apt install curl"
    exit 1
fi
success "curl: $(curl --version | head -1)"

info "Checking Python dependencies..."
if ! $PYTHON -c "import requests, bs4, cloudscraper" 2>/dev/null; then
    info "Dependencies missing – installing..."
    $PYTHON -m pip install --quiet --user requests beautifulsoup4 cloudscraper
    success "Dependencies installed."
else
    success "Dependencies OK (requests, beautifulsoup4, cloudscraper)."
fi

if [[ ! -f "$SCRIPT_DIR/watchlist.json" ]]; then
    error "watchlist.json not found in $SCRIPT_DIR"
    exit 1
fi
success "watchlist.json found."

ensure_ntfy_topic

# ─────────────────────── Log directory ───────────────────────────────────────

mkdir -p "$LOG_DIR"
success "Log directory: $LOG_DIR"

# ─────────────────────── Run init.py ─────────────────────────────────────────

echo ""
info "Running init.py..."
echo "----------------------------------------"
cd "$SCRIPT_DIR"
if $PYTHON "$INIT_SCRIPT"; then
    echo "----------------------------------------"
    success "init.py completed successfully."
else
    echo "----------------------------------------"
    error "init.py failed."
    send_push "Discogs Monitor - init failed" \
        "init.py exited with an error. Check the output." \
        "high" "warning" || true
    exit 1
fi

# ─────────────────────── Register cron job ───────────────────────────────────

echo ""
info "Configuring crontab..."

CURRENT_CRON="$(crontab -l 2>/dev/null || true)"

if echo "$CURRENT_CRON" | grep -qF "$CRON_MARKER"; then
    info "Entry already exists in crontab - updating."
    NEW_CRON="$(echo "$CURRENT_CRON" | grep -v "$CRON_MARKER" | grep -v "$CHECK_SCRIPT")"
else
    NEW_CRON="$CURRENT_CRON"
fi

(
    echo "$NEW_CRON"
    echo "$CRON_JOB $CRON_MARKER"
) | grep -v '^$' | crontab -   # strip leading blank lines

success "Crontab updated. Job scheduled every $CRON_INTERVAL minutes."

echo ""
info "Current crontab:"
crontab -l

# ─────────────────────── Test push notification ──────────────────────────────

echo ""
info "Sending test push notification via ntfy..."

WATCHLIST_COUNT=$($PYTHON -c "
import json
with open('$SCRIPT_DIR/watchlist.json') as f:
    data = json.load(f)
print(len(data))
")

PUSH_BODY="Monitor started successfully!

Watching: $WATCHLIST_COUNT record(s)
Check interval: every $CRON_INTERVAL minutes
Log file: $LOG_FILE"

if send_push "🎵 Discogs Monitor - started!" "$PUSH_BODY" "default" "white_check_mark"; then
    NTFY_TOPIC=$($PYTHON -c "import sys; sys.path.insert(0, '$SCRIPT_DIR'); from config import NTFY_TOPIC; print(NTFY_TOPIC)")
    success "Test push sent to topic: $NTFY_TOPIC"
else
    error "Failed to send test push (check your ntfy configuration and connection)."
fi

# ─────────────────────── Summary ─────────────────────────────────────────────

echo ""
echo "========================================"
echo " All done!"
echo "========================================"
echo ""

# Values from Python config
DISPLAY_NTFY_URL=$NTFY_BASE_URL
DISPLAY_NTFY_TOPIC=$($PYTHON -c "import sys; sys.path.insert(0, '$SCRIPT_DIR'); from config import NTFY_TOPIC; print(NTFY_TOPIC)")
DISPLAY_LOG_DIR=$LOG_DIR

echo "  ntfy URL:      $DISPLAY_NTFY_URL"
echo "  ntfy topic:    $DISPLAY_NTFY_TOPIC"
echo "  Logs:          $DISPLAY_LOG_DIR"
echo "  Interval:      every $CRON_INTERVAL minutes"
echo ""
echo "  To stop monitoring:"
echo "    crontab -e   (remove the line containing 'discogs-monitor')"
echo ""
echo "  To trigger a check manually:"
echo "    cd \"$SCRIPT_DIR\" && $PYTHON check.py"
echo ""
