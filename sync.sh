#!/bin/bash
# Sync Claude Code memory files from VMs to local cache.
# Runs via launchd every 5 minutes on Mac.

CONFIG="${HOME}/.claude-memories/config.json"
if [[ ! -f "$CONFIG" ]]; then
    echo "Config not found: $CONFIG" >&2
    exit 1
fi

LOCAL_CACHE=$(jq -r '.local_cache // "~/.claude-memories"' "$CONFIG" | sed "s|~|$HOME|")
mkdir -p "$LOCAL_CACHE"

# Read existing sync data or start fresh
SYNC_FILE="$LOCAL_CACHE/last-sync.json"
[[ -f "$SYNC_FILE" ]] && sync_data=$(cat "$SYNC_FILE") || sync_data="{}"

vm_count=$(jq '.vms | length' "$CONFIG")
for (( i=0; i<vm_count; i++ )); do
    name=$(jq -r ".vms[$i].name" "$CONFIG")
    host=$(jq -r ".vms[$i].host" "$CONFIG")
    user=$(jq -r ".vms[$i].user" "$CONFIG")
    key=$(jq -r ".vms[$i].ssh_key" "$CONFIG" | sed "s|~|$HOME|")
    ssh_opts="-i $key -o ConnectTimeout=5 -o StrictHostKeyChecking=accept-new -o BatchMode=yes"
    success=true

    path_count=$(jq ".vms[$i].memory_paths | length" "$CONFIG")
    for (( j=0; j<path_count; j++ )); do
        mem_path=$(jq -r ".vms[$i].memory_paths[$j]" "$CONFIG")
        # project name = second-to-last path component (e.g. -home-dav-src-doa)
        project=$(basename "$(dirname "$mem_path")")
        dest="$LOCAL_CACHE/$name/$project/memory/"
        mkdir -p "$dest"

        if ! rsync -az --delete --timeout=5 \
            -e "ssh $ssh_opts" \
            "$user@$host:$mem_path/" "$dest" 2>/dev/null; then
            success=false
        fi
    done

    ts=$(date -u +"%Y-%m-%dT%H:%M:%S")
    sync_data=$(echo "$sync_data" | jq \
        --arg vm "$name" --arg ts "$ts" --argjson ok "$success" \
        '.[$vm] = {"last_sync": $ts, "success": $ok}')
done

echo "$sync_data" > "$SYNC_FILE"
