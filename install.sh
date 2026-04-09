#!/bin/bash
# Interactive installer for claude-memory-mcp on macOS.
# Creates dirs, SSH key, config.json, launchd plist, and prints Claude Desktop instructions.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
MEMORY_DIR="$HOME/.claude-memories"
SSH_KEY="$HOME/.ssh/claude_memory_ed25519"
CONFIG_FILE="$MEMORY_DIR/config.json"
PLIST_NAME="com.claude.memory-sync"
PLIST_DIR="$HOME/Library/LaunchAgents"
PLIST_PATH="$PLIST_DIR/$PLIST_NAME.plist"
SYNC_LOG="$MEMORY_DIR/sync.log"

# ── Pre-flight: check required tools ──────────────────────────────────
# Tools that ship with macOS but we still verify
missing_system=()
for cmd in ssh-keygen ssh rsync launchctl; do
    if ! command -v "$cmd" &>/dev/null; then
        missing_system+=("$cmd")
    fi
done

# Tools that typically need to be installed
missing_install=()
for cmd in jq ssh-copy-id python3; do
    if ! command -v "$cmd" &>/dev/null; then
        missing_install+=("$cmd")
    fi
done

if (( ${#missing_system[@]} || ${#missing_install[@]} )); then
    echo "Error: the following required tools are not found:"
    for cmd in "${missing_system[@]}"; do
        echo "  - $cmd  (expected macOS system tool)"
    done
    for cmd in "${missing_install[@]}"; do
        echo "  - $cmd"
    done
    if (( ${#missing_install[@]} )); then
        echo ""
        echo "Install with:  brew install ${missing_install[*]}"
    fi
    exit 1
fi

# ── Intro ───────────────────────────────────────────────────────────────
echo "========================================"
echo "  claude-memory-mcp installer"
echo "========================================"
echo ""
VENV_DIR="$SCRIPT_DIR/.venv"

echo "This script will:"
echo "  1. Create $MEMORY_DIR directory"
echo "  2. Set up a Python venv and install the mcp package"
echo "  3. Generate an SSH keypair at $SSH_KEY (if needed)"
echo "  4. Ask you for VM details and build config.json"
echo "  5. Install a launchd plist to sync every 5 minutes"
echo "  6. Show how to configure Claude Desktop"
echo ""
read -rp "Press Enter to continue (Ctrl-C to abort)..."
echo ""

# ── 1. Create directories ──────────────────────────────────────────────
echo "--- Creating directories ---"
if [[ -d "$MEMORY_DIR" ]]; then
    echo "  $MEMORY_DIR already exists, skipping."
else
    mkdir -p "$MEMORY_DIR"
    chmod 700 "$MEMORY_DIR"
    echo "  Created $MEMORY_DIR"
fi

mkdir -p "$HOME/.ssh"

# ── 2. Python venv ────────────────────────────────────────────────────
echo ""
echo "--- Python virtual environment ---"
if [[ -d "$VENV_DIR" ]] && "$VENV_DIR/bin/python3" -c "import mcp" &>/dev/null; then
    echo "  $VENV_DIR already exists with mcp package, skipping."
else
    echo "  Creating venv at $VENV_DIR ..."
    python3 -m venv "$VENV_DIR"
    "$VENV_DIR/bin/pip" install --quiet mcp
    echo "  Installed mcp package into venv."
fi

# ── 3. SSH keypair ─────────────────────────────────────────────────────
echo ""
echo "--- SSH keypair ---"
if [[ -f "$SSH_KEY" ]]; then
    echo "  $SSH_KEY already exists, skipping."
else
    ssh-keygen -t ed25519 -f "$SSH_KEY" -N "" -C "claude-memory-sync"
    echo "  Generated $SSH_KEY"
fi
echo ""

# ── 3. Gather VM details interactively ─────────────────────────────────
echo "--- VM configuration ---"
echo "Enter details for each VM you want to sync memories from."
echo ""

vms_json="[]"
add_more="y"

while [[ "$add_more" =~ ^[Yy] ]]; do
    read -rp "  VM name (e.g. dev-vm): " vm_name
    read -rp "  Hostname or IP (e.g. dev-vm.local or 192.168.1.50): " vm_host
    read -rp "  SSH username: " vm_user
    echo "  Memory paths — these are the Claude project memory directories on the VM."
    echo "  Example: ~/.claude/projects/-home-dav-src-myproject/memory"
    read -rp "  Comma-separated memory paths: " vm_paths_raw

    # Build JSON array of paths
    IFS=',' read -ra path_arr <<< "$vm_paths_raw"
    paths_json="[]"
    for p in "${path_arr[@]}"; do
        trimmed=$(echo "$p" | xargs)  # trim whitespace
        paths_json=$(echo "$paths_json" | jq --arg p "$trimmed" '. + [$p]')
    done

    # Append this VM to the array
    vms_json=$(echo "$vms_json" | jq \
        --arg name "$vm_name" \
        --arg host "$vm_host" \
        --arg user "$vm_user" \
        --arg key "~/.ssh/claude_memory_ed25519" \
        --argjson paths "$paths_json" \
        '. + [{name: $name, host: $host, user: $user, ssh_key: $key, memory_paths: $paths}]')

    echo ""
    read -rp "  Add another VM? (y/N): " add_more
    add_more="${add_more:-n}"
    echo ""
done

# ── 4. Write config.json ───────────────────────────────────────────────
echo "--- Writing config.json ---"
config_json=$(jq -n \
    --argjson vms "$vms_json" \
    '{vms: $vms, local_cache: "~/.claude-memories", sync_interval_minutes: 5}')

if [[ -f "$CONFIG_FILE" ]]; then
    echo "  $CONFIG_FILE already exists."
    read -rp "  Overwrite? (y/N): " overwrite
    if [[ ! "$overwrite" =~ ^[Yy] ]]; then
        echo "  Keeping existing config.json."
    else
        echo "$config_json" > "$CONFIG_FILE"
        chmod 600 "$CONFIG_FILE"
        echo "  Wrote $CONFIG_FILE"
    fi
else
    echo "$config_json" > "$CONFIG_FILE"
    echo "  Wrote $CONFIG_FILE"
fi
echo ""

# ── 5. Install launchd plist ───────────────────────────────────────────
echo "--- Installing launchd plist ---"
mkdir -p "$PLIST_DIR"

cat > "$PLIST_PATH" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>${PLIST_NAME}</string>
    <key>ProgramArguments</key>
    <array>
        <string>/bin/bash</string>
        <string>${SCRIPT_DIR}/sync.sh</string>
    </array>
    <key>StartInterval</key>
    <integer>300</integer>
    <key>RunAtLoad</key>
    <true/>
    <key>StandardOutPath</key>
    <string>${SYNC_LOG}</string>
    <key>StandardErrorPath</key>
    <string>${SYNC_LOG}</string>
</dict>
</plist>
PLIST

echo "  Wrote $PLIST_PATH"

# Load (or reload) the plist
if launchctl list "$PLIST_NAME" &>/dev/null; then
    launchctl unload "$PLIST_PATH" 2>/dev/null || true
fi
launchctl load "$PLIST_PATH" 2>/dev/null && echo "  Loaded launchd job." || echo "  (Could not load plist — load it manually with: launchctl load \"$PLIST_PATH\")"
echo ""

# ── 6. Claude Desktop instructions ────────────────────────────────────
echo "========================================"
echo "  Setup complete!"
echo "========================================"
echo ""
echo "--- SSH key ---"
echo "Copy the public key to each VM so sync.sh can connect:"
echo ""

vm_count=$(echo "$vms_json" | jq 'length')
for (( i=0; i<vm_count; i++ )); do
    vm_user=$(echo "$vms_json" | jq -r ".[$i].user")
    vm_host=$(echo "$vms_json" | jq -r ".[$i].host")
    echo "  ssh-copy-id -i $SSH_KEY ${vm_user}@${vm_host}"
done

echo ""
echo "--- Claude Desktop configuration ---"
echo "Add (or merge) the following into:"
echo "  ~/Library/Application Support/Claude/claude_desktop_config.json"
echo ""
cat <<EOF
{
  "mcpServers": {
    "claude-memory": {
      "command": "${VENV_DIR}/bin/python3",
      "args": ["${SCRIPT_DIR}/server.py"]
    }
  }
}
EOF
echo ""

# ── 7. Offer to copy SSH key to VMs ───────────────────────────────────
echo ""
read -rp "Would you like to copy the SSH key to your VMs now? (y/N): " copy_keys
if [[ "$copy_keys" =~ ^[Yy] ]]; then
    for (( i=0; i<vm_count; i++ )); do
        vm_user=$(echo "$vms_json" | jq -r ".[$i].user")
        vm_host=$(echo "$vms_json" | jq -r ".[$i].host")
        vm_name=$(echo "$vms_json" | jq -r ".[$i].name")
        echo ""
        echo "  Copying key to ${vm_name} (${vm_user}@${vm_host})..."
        ssh-copy-id -i "$SSH_KEY" "${vm_user}@${vm_host}" || echo "  Failed to copy key to ${vm_name}. You can do it manually later."
    done
fi

echo ""
echo "Done! Sync will run every 5 minutes. Check $SYNC_LOG for output."
