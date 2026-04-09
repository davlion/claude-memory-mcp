# Claude Memory MCP Server — Plan

## Goal

Give Claude Desktop (Mac) read-only access to Claude Code memory files
from multiple VMs on the LAN. Any Claude Chat conversation can ask
"what do you know about my projects?" and get current memory context.

## Architecture

```
┌──────────────────────────────────────────────────┐
│  Mac (Claude Desktop)                            │
│                                                  │
│  Claude Desktop ──stdio──► claude-memory-mcp     │
│                            (Python, auto-start)  │
│                                 │                │
│                                 ▼                │
│                          ~/.claude-memories/      │
│                          ├── vm1/                │
│                          │   └── project-a/      │
│                          │       └── memory/     │
│                          ├── vm2/                │
│                          │   └── project-b/      │
│                          │       └── memory/     │
│                          └── last-sync.json      │
│                                 ▲                │
│                                 │                │
│                          rsync cron (5 min)      │
│                                 │                │
└─────────────────────────────────┼────────────────┘
                                  │ SSH
                    ┌─────────────┼─────────────┐
                    ▼             ▼             ▼
                  VM1           VM2           VM3
          ~/.claude/projects/  (same)        (same)
```

## Components

### 1. Config file (`~/.claude-memories/config.json`)

```json
{
  "vms": [
    {
      "name": "dev-vm",
      "host": "dev-vm.local",
      "user": "dav",
      "ssh_key": "~/.ssh/claude_memory_ed25519",
      "memory_paths": [
        "~/.claude/projects/-home-dav-src-doa/memory",
        "~/.claude/projects/-home-dav-src-other/memory"
      ]
    },
    {
      "name": "build-vm",
      "host": "192.168.1.50",
      "user": "dav",
      "ssh_key": "~/.ssh/claude_memory_ed25519",
      "memory_paths": [
        "~/.claude/projects/-home-dav-src-firmware/memory"
      ]
    }
  ],
  "local_cache": "~/.claude-memories",
  "sync_interval_minutes": 5
}
```

### 2. Sync script (`claude-memory-sync.sh`)

Runs via launchd every 5 minutes on the Mac.

For each VM in config:
1. SSH with 5-second connect timeout
2. If unreachable, skip silently (VM is off — normal)
3. If reachable, rsync the memory paths to local cache
4. Write `last-sync.json` with timestamps per VM

```bash
for vm in config.vms:
    rsync -az --timeout=5 \
      -e "ssh -i $key -o ConnectTimeout=5 -o StrictHostKeyChecking=accept-new" \
      $user@$host:$path/ \
      $local_cache/$vm_name/$project_name/
```

Handles:
- VM offline → rsync fails silently, stale cache remains (better than nothing)
- New files → synced on next run
- Deleted files → `--delete` flag keeps cache in sync
- SSH key not accepted → logged to stderr, doesn't crash

### 3. MCP server (`claude-memory-mcp`)

Python, uses the `mcp` SDK. Runs as a subprocess spawned by Claude Desktop.

**Tools exposed:**

#### `list_projects`
Returns list of all known projects across all VMs with last-sync time.
```
→ [{"vm": "dev-vm", "project": "doa", "last_sync": "2026-04-09T10:30:00", "memory_count": 6}]
```

#### `read_memories(project)` 
Returns MEMORY.md index + all referenced memory file contents for a project.
```
→ {"project": "doa", "vm": "dev-vm", "index": "...", "memories": [{"file": "user_profile.md", "content": "..."}]}
```

#### `search_memories(query)`
Full-text search across all memory files from all projects.
```
→ [{"vm": "dev-vm", "project": "doa", "file": "project_rpi5_status.md", "match": "...context..."}]
```

#### `sync_status`
Shows which VMs are reachable and when each was last synced.
```
→ [{"vm": "dev-vm", "last_sync": "2026-04-09T10:30:00", "reachable": true}]
```

### 4. Claude Desktop config

Add to `~/.claude/claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "claude-memory": {
      "command": "python3",
      "args": ["/path/to/claude-memory-mcp/server.py"],
      "env": {}
    }
  }
}
```

Claude Desktop auto-spawns MCP servers on startup. No manual start needed.

### 5. SSH keypair setup

```bash
ssh-keygen -t ed25519 -f ~/.ssh/claude_memory_ed25519 -N "" -C "claude-memory-sync"
# Copy public key to each VM:
ssh-copy-id -i ~/.ssh/claude_memory_ed25519.pub dav@dev-vm.local
```

Read-only by nature — rsync only reads from VMs.

### 6. launchd plist (auto-start sync on Mac)

`~/Library/LaunchAgents/com.claude.memory-sync.plist`

Runs sync script every 5 minutes, starts at login.

## Files to create (separate repo)

```
claude-memory-mcp/
├── README.md
├── server.py              # MCP server (~100 lines)
├── sync.sh                # rsync script (~30 lines)
├── config.example.json    # example config
├── install.sh             # setup script:
│                          #   - creates ~/.claude-memories/
│                          #   - generates SSH keypair
│                          #   - installs launchd plist
│                          #   - configures Claude Desktop
├── requirements.txt       # mcp SDK
└── tests/
    └── test_server.py     # unit tests with mock filesystem
```

## Install steps (one-time)

1. `git clone` the repo
2. `./install.sh` — interactive, asks for VM hostnames
3. Copy SSH public key to each VM (install.sh can do this)
4. Restart Claude Desktop
5. Ask Claude Chat: "What do you know about my projects?"

## Limitations

- Read-only (by design for v1)
- 5-minute sync delay (memories won't appear instantly)
- VMs must be reachable via SSH from Mac
- No conflict resolution needed (read-only)
- If all VMs are off, Chat sees stale cached data (with timestamps)

## Future extensions (not for v1)

- Write-back via SSH (needs conflict resolution)
- Webhook on memory file change (instant sync instead of polling)
- Claude Code hook that triggers sync on memory write
- Web UI to browse memories
