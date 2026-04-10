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
echo "  2. Set up a Python venv and install dependencies"
echo "  3. Generate an SSH keypair at $SSH_KEY (if needed)"
echo "  4. Launch the VM manager to configure your VMs"
echo "  5. Install a launchd plist to sync every hour"
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
if [[ -d "$VENV_DIR" ]] && "$VENV_DIR/bin/python3" -c "import mcp; import InquirerPy" &>/dev/null; then
    echo "  $VENV_DIR already exists with required packages, skipping."
else
    echo "  Creating venv at $VENV_DIR ..."
    python3 -m venv "$VENV_DIR"
    "$VENV_DIR/bin/pip" install --quiet mcp InquirerPy
    echo "  Installed mcp and InquirerPy packages into venv."
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

# ── 4. VM configuration via TUI ──────────────────────────────────────
echo "--- VM configuration ---"
echo "Launching VM manager..."
echo ""
"$VENV_DIR/bin/python3" "$SCRIPT_DIR/manage_vms.py" --config "$CONFIG_FILE"
echo ""

# ── 5. Install launchd plist (if VMs configured) ─────────────────────
vm_count=$(jq '.vms | length' "$CONFIG_FILE")
if (( vm_count > 0 )); then
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
    <integer>3600</integer>
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
    if launchctl list "$PLIST_NAME" &>/dev/null; then
        launchctl unload "$PLIST_PATH" 2>/dev/null || true
    fi
    launchctl load "$PLIST_PATH" 2>/dev/null && echo "  Loaded launchd job." || echo "  (Could not load plist — load it manually with: launchctl load \"$PLIST_PATH\")"
    echo ""
else
    echo "--- Skipping launchd plist (no VMs configured) ---"
    echo "  Run ./manage_vms.py to add VMs later."
    echo "  The sync job will be installed when you add your first VM."
    echo ""
fi

# ── 6. Claude Desktop configuration ───────────────────────────────────
DESKTOP_CONFIG="$HOME/Library/Application Support/Claude/claude_desktop_config.json"
echo "--- Claude Desktop configuration ---"
if [[ -f "$DESKTOP_CONFIG" ]]; then
    existing=$(cat "$DESKTOP_CONFIG")
    if echo "$existing" | jq -e '.mcpServers["claude-memory"]' &>/dev/null; then
        echo "  claude-memory MCP entry already present, skipping."
    else
        updated=$(echo "$existing" | jq \
            --arg cmd "${VENV_DIR}/bin/python3" \
            --arg srv "${SCRIPT_DIR}/server.py" \
            '.mcpServers["claude-memory"] = {"command": $cmd, "args": [$srv]}')
        echo "$updated" > "$DESKTOP_CONFIG"
        echo "  Added claude-memory to $DESKTOP_CONFIG"
        echo "  Restart Claude Desktop to activate the MCP server."
    fi
else
    mkdir -p "$(dirname "$DESKTOP_CONFIG")"
    cat > "$DESKTOP_CONFIG" <<EOF
{
  "mcpServers": {
    "claude-memory": {
      "command": "${VENV_DIR}/bin/python3",
      "args": ["${SCRIPT_DIR}/server.py"]
    }
  }
}
EOF
    echo "  Created $DESKTOP_CONFIG"
    echo "  Restart Claude Desktop to activate the MCP server."
fi

echo ""
echo "========================================"
echo "  Setup complete!"
echo "========================================"
echo ""
echo "To manage VMs later, run: ./manage_vms.py"
echo "Sync log: $SYNC_LOG"
echo ""
