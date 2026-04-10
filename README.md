# claude-memory-mcp

Give Claude Desktop read-only access to Claude Code memory files stored on VMs across your LAN.

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
│                          rsync (hourly + on-demand) │
│                                 │                │
└─────────────────────────────────┼────────────────┘
                                  │ SSH
                    ┌─────────────┼─────────────┐
                    ▼             ▼             ▼
                  VM1           VM2           VM3
          ~/.claude/projects/  (same)        (same)
```

A sync script (`sync.sh`) rsyncs memory files from your VMs to a local cache via SSH every hour. An MCP server (`server.py`) exposes that cache to Claude Desktop via stdio. Sync can also be triggered on-demand via the `sync_now` MCP tool.

## Quick Start

```bash
# 1. Clone the repo
git clone https://github.com/youruser/claude-memory-mcp
cd claude-memory-mcp

# 2. Run the interactive installer
./install.sh
# - Asks for VM hostnames/usernames
# - Generates SSH key
# - Installs launchd sync job (every hour)
# - Automatically adds MCP server entry to Claude Desktop config

# 3. Copy the SSH public key to each VM
ssh-copy-id -i ~/.ssh/claude_memory_ed25519.pub user@your-vm.local

# 4. Restart Claude Desktop

# 5. Ask Claude:
#    "What do you know about my projects?"
#    "Check memory sync health"
```

## MCP Tools

| Tool | Description |
|------|-------------|
| `list_projects` | Lists all known projects across all VMs with last-sync time and memory file count |
| `read_memories` | Returns the MEMORY.md index and all referenced memory file contents for a project |
| `search_memories` | Full-text search across all memory files from all projects |
| `sync_status` | Shows which VMs were reachable and when each was last synced |
| `sync_now` | Trigger an immediate memory sync from all VMs |
| `memory_sync_health` | Full health check: launchd job status, per-VM sync age, and any recent errors from the sync log |

## Configuration

Configuration lives at `~/.claude-memories/config.json`. See `config.example.json` for a template.

```json
{
  "vms": [
    {
      "name": "dev-vm",
      "host": "dev-vm.local",
      "user": "dav",
      "ssh_key": "~/.ssh/claude_memory_ed25519",
      "memory_paths": [
        "~/.claude/projects/-home-dav-src-myproject/memory"
      ]
    }
  ],
  "local_cache": "~/.claude-memories",
  "sync_interval_minutes": 5
}
```

Each entry in `vms` needs:
- `name` — a short label used as the cache subdirectory name
- `host` — hostname or IP of the VM
- `user` — SSH username
- `ssh_key` — path to the private key used for syncing
- `memory_paths` — list of paths on the VM to sync (Claude Code stores memories under `~/.claude/projects/<encoded-path>/memory/`)

Do not commit `config.json` — it is listed in `.gitignore`.

## Security Considerations

- **Memory file contents**: Claude Code memory files may contain sensitive personal information, project details, API keys, and preferences. Review what Claude has stored before syncing it off-VM.
- **MCP client access**: The MCP server exposes all synced files to any MCP client connected to Claude Desktop. There is no per-file or per-project access control.
- **config.json**: Contains your network topology — hostnames, IPs, and usernames. Never commit it to version control. It is excluded by `.gitignore`.
- **SSH key**: The generated key (`~/.ssh/claude_memory_ed25519`) grants SSH read access to the Claude memory directories on your VMs. Protect it like any other SSH private key. Do not share it or check it in.
- **No open port**: The MCP server communicates with Claude Desktop via stdio only. It does not open any network port.
- **Cache permissions**: The cache directory (`~/.claude-memories/`) is created with `700` permissions (owner read/write/execute only).

## Claude Code Skills

This repo includes Claude Code skills that make working with the memory sync system easier.

### memory-sync-status

Diagnoses whether memory sync is working: checks launchd job status, per-VM sync timestamps, and the sync log for errors.

**Install:**
```bash
mkdir -p ~/.claude/skills/memory-sync-status
cp skills/memory-sync-status/SKILL.md ~/.claude/skills/memory-sync-status/SKILL.md
```

**Usage:** Ask Claude Code "is memory sync working?" and it will walk through the diagnosis automatically.

## Requirements

- macOS (uses launchd for the sync cron job)
- Python 3.8+
- `jq` (used by `sync.sh`)
- SSH access to each VM from your Mac

Install Python dependencies:

```bash
pip3 install -r requirements.txt
```

## Limitations

- **Read-only**: The MCP server cannot write or update memory files on VMs (by design for v1).
- **Hourly sync**: Changes made on a VM will not appear in Claude Desktop until the next sync cycle. Use `sync_now` to pull immediately.
- **VMs must be SSH-reachable**: If a VM is off or unreachable, the last synced cache is used. Stale data is served with its timestamp so Claude knows how fresh it is.
