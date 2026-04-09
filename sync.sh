#!/bin/bash

# sync.sh - Sync Claude Code memory files from VMs to local cache
# Reads config from ~/.claude-memories/config.json
# Updates last-sync.json with per-VM timestamps

set -e

CONFIG_FILE="${HOME}/.claude-memories/config.json"
SYNC_LOG="${HOME}/.claude-memories/last-sync.json"

# Ensure config exists
if [[ ! -f "$CONFIG_FILE" ]]; then
    echo "Error: Config file not found at $CONFIG_FILE" >&2
    exit 1
fi

# Initialize sync log if it doesn't exist
if [[ ! -f "$SYNC_LOG" ]]; then
    echo "{}" > "$SYNC_LOG"
fi

# Extract and expand paths from JSON config
LOCAL_CACHE=$(jq -r '.local_cache' "$CONFIG_FILE" | sed "s|~|$HOME|g")

# Create cache directory if needed
mkdir -p "$LOCAL_CACHE"

# Temporary file for updated sync log
TEMP_LOG=$(mktemp)
trap "rm -f $TEMP_LOG" EXIT

# Start with existing sync log
cp "$SYNC_LOG" "$TEMP_LOG"

# Process each VM
jq -c '.vms[]' "$CONFIG_FILE" | while read -r vm_config; do
    vm_name=$(echo "$vm_config" | jq -r '.name')
    vm_host=$(echo "$vm_config" | jq -r '.host')
    vm_user=$(echo "$vm_config" | jq -r '.user')
    ssh_key=$(echo "$vm_config" | jq -r '.ssh_key' | sed "s|~|$HOME|g")

    # Check if VM is reachable via SSH
    if ! timeout 5 ssh -i "$ssh_key" \
        -o ConnectTimeout=5 \
        -o StrictHostKeyChecking=accept-new \
        "$vm_user@$vm_host" exit 2>/dev/null; then
        # VM is offline or unreachable - skip silently, keep existing cache
        continue
    fi

    # VM is reachable, sync each memory path
    sync_success=true
    echo "$vm_config" | jq -c '.memory_paths[]' | while read -r memory_path; do
        memory_path=$(echo "$memory_path" | tr -d '"')

        # Extract project_name from second-to-last component
        # e.g., ~/.claude/projects/-home-dav-src-doa/memory -> -home-dav-src-doa
        project_name=$(echo "$memory_path" | rev | cut -d'/' -f2 | rev)

        # Build destination path
        dest_path="$LOCAL_CACHE/$vm_name/$project_name/memory/"

        # Create destination directory
        mkdir -p "$dest_path"

        # Perform rsync with timeout and error handling
        remote_path="${vm_user}@${vm_host}:${memory_path}/"
        if ! rsync -az --delete --timeout=5 \
            -e "ssh -i $ssh_key -o ConnectTimeout=5 -o StrictHostKeyChecking=accept-new" \
            "$remote_path" "$dest_path" 2>/dev/null; then
            sync_success=false
        fi
    done

    # Update sync log for this VM
    timestamp=$(date -u +"%Y-%m-%dT%H:%M:%S")
    if [[ "$sync_success" == true ]]; then
        jq --arg vm "$vm_name" --arg ts "$timestamp" \
            '.[$vm] = {"last_sync": $ts, "success": true}' "$TEMP_LOG" > "$TEMP_LOG.tmp"
    else
        jq --arg vm "$vm_name" --arg ts "$timestamp" \
            '.[$vm] = {"last_sync": $ts, "success": false}' "$TEMP_LOG" > "$TEMP_LOG.tmp"
    fi
    mv "$TEMP_LOG.tmp" "$TEMP_LOG"
done

# Write final sync log
mv "$TEMP_LOG" "$SYNC_LOG"
