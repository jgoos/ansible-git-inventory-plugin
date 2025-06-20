#!/bin/bash

# Ansible Inventory Update Script for Cron
# This script clones/updates the git repository containing hosts_* files
# and should be run via cron to keep the local inventory directory updated

set -euo pipefail

# Configuration
REPO_URL="${REPO_URL:-https://github.com/your-company/ansible-inventory.git}"
REPO_BRANCH="${REPO_BRANCH:-main}"
LOCAL_DIR="${LOCAL_DIR:-/var/lib/ansible/inventory}"
REPO_PATH="${REPO_PATH:-environments}"  # Path within repo where hosts_* files are located
LOG_FILE="${LOG_FILE:-/var/log/ansible-inventory-update.log}"
LOCK_FILE="/tmp/ansible-inventory-update.lock"

# Logging function
log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1" | tee -a "$LOG_FILE"
}

# Check if another instance is running
if [ -f "$LOCK_FILE" ]; then
    PID=$(cat "$LOCK_FILE")
    if kill -0 "$PID" 2>/dev/null; then
        log "ERROR: Another instance is already running (PID: $PID)"
        exit 1
    else
        log "WARNING: Stale lock file found, removing it"
        rm -f "$LOCK_FILE"
    fi
fi

# Create lock file
echo $$ > "$LOCK_FILE"

# Cleanup function
cleanup() {
    rm -f "$LOCK_FILE"
}
trap cleanup EXIT

log "Starting inventory update from $REPO_URL"

# Create directory if it doesn't exist
mkdir -p "$(dirname "$LOCAL_DIR")"

# Clone or update repository
if [ -d "$LOCAL_DIR/.git" ]; then
    log "Repository exists, updating..."
    cd "$LOCAL_DIR"
    
    # Check if we're on the right branch
    CURRENT_BRANCH=$(git rev-parse --abbrev-ref HEAD)
    if [ "$CURRENT_BRANCH" != "$REPO_BRANCH" ]; then
        log "Switching from branch $CURRENT_BRANCH to $REPO_BRANCH"
        git checkout "$REPO_BRANCH"
    fi
    
    # Pull latest changes
    if git pull origin "$REPO_BRANCH"; then
        log "Successfully updated repository"
    else
        log "ERROR: Failed to pull latest changes"
        exit 1
    fi
else
    log "Repository doesn't exist, cloning..."
    if git clone --branch "$REPO_BRANCH" "$REPO_URL" "$LOCAL_DIR"; then
        log "Successfully cloned repository"
    else
        log "ERROR: Failed to clone repository"
        exit 1
    fi
fi

# The repository should already have the correct structure with environment directories
# containing hosts files, so no additional copying is needed

# Count hosts files in environment directories
HOST_FILES=0
ENV_DIRS_FOUND=0

for env_dir in prod acc tst qas dev staging; do
    ENV_PATH="$LOCAL_DIR/$env_dir"
    if [ -d "$ENV_PATH" ]; then
        ENV_DIRS_FOUND=$((ENV_DIRS_FOUND + 1))
        ENV_HOST_FILES=$(find "$ENV_PATH" -name "hosts*" -type f | wc -l)
        HOST_FILES=$((HOST_FILES + ENV_HOST_FILES))
        if [ "$ENV_HOST_FILES" -gt 0 ]; then
            log "Found $ENV_HOST_FILES hosts files in $env_dir/ directory"
        fi
    fi
done

# Also check for any additional pattern files if REPO_PATH is specified
if [ "$REPO_PATH" != "." ] && [ "$REPO_PATH" != "" ]; then
    FULL_REPO_PATH="$LOCAL_DIR/$REPO_PATH"
    if [ -d "$FULL_REPO_PATH" ] && [ "$FULL_REPO_PATH" != "$LOCAL_DIR" ]; then
        log "Checking additional path: $REPO_PATH"
        ADDITIONAL_FILES=$(find "$FULL_REPO_PATH" -name "hosts*" -type f | wc -l)
        HOST_FILES=$((HOST_FILES + ADDITIONAL_FILES))
        if [ "$ADDITIONAL_FILES" -gt 0 ]; then
            log "Found $ADDITIONAL_FILES additional hosts files in $REPO_PATH"
        fi
    fi
fi

log "Found $ENV_DIRS_FOUND environment directories with total $HOST_FILES hosts files"

# Verify we have hosts files
if [ "$HOST_FILES" -eq 0 ]; then
    log "WARNING: No hosts_* files found after update"
else
    log "Inventory update completed successfully with $HOST_FILES files"
fi

# Optional: Test ansible inventory
if command -v ansible-inventory >/dev/null 2>&1; then
    if [ -f "/etc/ansible/ansible.cfg" ] || [ -f "$HOME/.ansible.cfg" ] || [ -f "./ansible.cfg" ]; then
        log "Testing inventory syntax..."
        if ansible-inventory --list >/dev/null 2>&1; then
            log "Inventory syntax test passed"
        else
            log "WARNING: Inventory syntax test failed"
        fi
    fi
fi

log "Inventory update process completed" 