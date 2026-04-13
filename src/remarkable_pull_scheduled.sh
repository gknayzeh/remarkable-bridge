#!/usr/bin/env bash
#
# Scheduled remarkable-pull wrapper.
# Called by systemd timer. Handles logging and ntfy notifications.
#

set -euo pipefail

PROJECT_DIR="$HOME/dev/tools/remarkable-bridge"
LOG_DIR="$HOME/.local/share/remarkable-bridge"
LOG_FILE="${LOG_DIR}/pull.log"
NTFY_TOPIC="remarkable"

# These MUST be set in the systemd unit environment
NTFY_URL="${NTFY_URL:-http://localhost:2586}"
NTFY_USER="${NTFY_USER:-}"
NTFY_PASS="${NTFY_PASS:-}"

mkdir -p "$LOG_DIR"

log() {
    echo "[$(date -Iseconds)] $*" | tee -a "$LOG_FILE"
}

notify() {
    local title="$1"
    local message="$2"
    local priority="${3:-default}"
    local tags="${4:-}"

    if [[ -z "$NTFY_USER" || -z "$NTFY_PASS" ]]; then
        log "NTFY_USER/NTFY_PASS not set, skipping notification"
        return
    fi

    curl -s \
        -u "${NTFY_USER}:${NTFY_PASS}" \
        -H "Title: ${title}" \
        -H "Priority: ${priority}" \
        -H "Tags: ${tags}" \
        -d "${message}" \
        "${NTFY_URL}/${NTFY_TOPIC}" \
        >> "$LOG_FILE" 2>&1 || true
}

# Rotate log if over 1MB
if [[ -f "$LOG_FILE" ]] && [[ $(stat -c%s "$LOG_FILE" 2>/dev/null || stat -f%z "$LOG_FILE" 2>/dev/null) -gt 1048576 ]]; then
    mv "$LOG_FILE" "${LOG_FILE}.1"
    log "Log rotated"
fi

log "=== remarkable-pull starting ==="

cd "$PROJECT_DIR"

# Capture output
output=$("$HOME/.local/bin/uv" run src/remarkable_pull.py -v 2>&1) || {
    exit_code=$?
    log "FAILED (exit ${exit_code})"
    log "$output"
    notify \
        "reMarkable Pull Failed" \
        "Exit code: ${exit_code}. Check log on server." \
        "high" \
        "warning,remarkable"
    exit $exit_code
}

log "$output"

# Parse output for summary — extract from the "Done." line
done_line=$(echo "$output" | grep "^Done\." | tail -1)
pulled=$(echo "$done_line" | grep -oP '\d+(?= pulled)' || echo "0")
errors=$(echo "$done_line" | grep -oP '\d+(?= errors)' || echo "0")
skipped=$(echo "$done_line" | grep -oP '\d+(?= skipped)' || echo "0")
conflicts=$(echo "$output" | grep -c "CONFLICT" || true)

log "Done: ${pulled} pulled, ${errors} errors, ${skipped} skipped, ${conflicts} conflicts"

if [[ "$pulled" -gt 0 ]]; then
    msg="${pulled} new/updated"
    [[ "$conflicts" -gt 0 ]] && msg="${msg}, ${conflicts} conflict(s)"
    notify \
        "reMarkable Notes Pulled" \
        "$msg" \
        "default" \
        "notebook,remarkable"
elif [[ "$errors" -gt 0 ]]; then
    notify \
        "reMarkable Pull Errors" \
        "${errors} error(s). Check server log." \
        "high" \
        "warning,remarkable"
fi
# No notification if nothing changed (avoid spam)

log "=== remarkable-pull complete ==="

# ─── Reading progress sync ────────────────────────────────────
log "=== progress-sync starting ==="

progress_output=$("$HOME/.local/bin/uv" run src/remarkable_progress_sync.py -v 2>&1) || {
    exit_code=$?
    log "progress-sync FAILED (exit ${exit_code})"
    log "$progress_output"
    notify \
        "Reading Progress Sync Failed" \
        "Exit code: ${exit_code}. Check log on server." \
        "high" \
        "warning,remarkable"
    # Don't exit — notebook pull already succeeded
}

log "$progress_output"

progress_synced=$(echo "$progress_output" | grep -oP '\d+(?= synced)' || echo "0")
if [[ "$progress_synced" -gt 0 ]]; then
    log "Progress synced for ${progress_synced} book(s)"
fi

log "=== progress-sync complete ==="
