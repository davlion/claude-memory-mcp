# Design: `share_memory` MCP Tool

**Date:** 2026-04-15
**Status:** Approved

## Background

claude-memory-mcp is a one-way read system: it rsyncs memory files from remote VMs to a local
cache, then exposes them to Claude Desktop via MCP tools and resources. All data flows inbound.

Occasionally a memory written on one VM is universally valuable — e.g. a debugging feedback
memory that applies to every project on every machine. This design adds on-demand outbound
pushing of a single memory file to other VMs and/or other projects on the same machine.

## Tool Signature

```python
share_memory(
    file: str,
    source_project: str,
    broadcast: bool = False,
    target_vms: list[str] | None = None,
    content: str | None = None,
    overwrite: bool = False,
) -> str
```

## Parameters

| Parameter | Default | Description |
|---|---|---|
| `file` | required | Memory filename to push, e.g. `feedback_debugging.md`. Cannot be `MEMORY.md`. |
| `source_project` | required | Short project name; resolved via existing `_find_project` fuzzy match. Used to locate the source file in the local cache. |
| `broadcast` | `False` | `False`: push only to the matching project on each target VM. `True`: push to every `memory_path` on each target VM. |
| `target_vms` | all configured VMs | Optional list of VM names to narrow scope. Defaults to all VMs in `config.json`, including localhost. |
| `content` | use cached file | If provided, push this content instead of the cached file. Enables in-conversation editing before sharing. |
| `overwrite` | `False` | If `False`, skip destinations where the file already exists and include the existing content in the result. If `True`, overwrite unconditionally. |

## Behavior

### Source resolution

1. If `content` is provided, use it directly (write to a temp file for rsync).
2. Otherwise, locate `<cache>/<vm>/<project>/memory/<file>` via `_find_project`. Return an
   error if the file is not found.

### Target resolution

For each VM in scope (all configured VMs, or `target_vms` if specified):

- **Targeted mode** (`broadcast=False`): find the VM's `memory_path` whose project component
  suffix-matches `source_project`. If none found, record `skipped: project not on this VM`.
- **Broadcast mode** (`broadcast=True`): iterate all `memory_paths` on the VM.

### src == dest guard

Skip any destination where `vm == source_vm AND project_path == source_project_path`. This is
programmer/user error regardless of whether `content` was provided. Return a clear error entry:
`"skipped: source and destination are the same file"`.

### Reachability

For non-localhost VMs, perform the same `nc -z -w2 <host> 22` reachability check used by
`sync.sh`. Record `skipped: unreachable` for offline VMs (earsvm offline is expected and not
an error).

Localhost (`localhost` / `127.0.0.1`) skips the reachability check — it is always available.
Localhost is a valid target in broadcast mode for pushing to other projects on the same machine.

### Conflict handling

For each destination path, check existence via SSH (or direct stat for localhost):

```bash
ssh <opts> <user>@<host> "test -f <dest>/<file> && cat <dest>/<file> || echo __NOT_FOUND__"
```

- File does not exist: proceed with rsync.
- File exists and `overwrite=False`: record `skipped: exists` and include existing content in
  result so the caller can review.
- File exists and `overwrite=True`: proceed with rsync.

### Push mechanism

```bash
rsync -az --timeout=5 -e "ssh <opts>" <tmpfile_or_source> <user>@<host>:<dest>/
```

Uses the same SSH key (`~/.ssh/claude_memory_ed25519`) and options as `sync.sh`.
For localhost, use direct rsync without SSH.

The push is immediate — no waiting for the next launchd sync cycle.

### Local cache

`share_memory` does not modify the local cache. The pushed file will appear in the cache
after the next `sync_now` call or the next hourly launchd run.

### MEMORY.md guard

`MEMORY.md` cannot be used as the `file` argument. Return an error immediately:
`"MEMORY.md is the index file and cannot be shared directly"`.

## Return value

JSON array, one entry per destination attempted:

```json
[
  {
    "vm": "lume-claude-sandbox",
    "project": "claude-memory-mcp",
    "dest": "~/.claude/projects/-Users-dav-src-claude-memory-mcp/memory/feedback_debugging.md",
    "status": "pushed"
  },
  {
    "vm": "lume-claude-sandbox",
    "project": "bakers-game-annotator",
    "dest": "~/.claude/projects/-Users-dav-src-bakers-game-annotator/memory/feedback_debugging.md",
    "status": "skipped",
    "reason": "exists",
    "existing_content": "---\nname: ...\n..."
  },
  {
    "vm": "earsvm",
    "status": "skipped",
    "reason": "unreachable"
  }
]
```

## Implementation notes

- All logic lives in `server.py`. No new files.
- Reuses `_find_project`, `_cache_dir`, and the SSH opts pattern from existing tools.
- `content` is written to a `tempfile.NamedTemporaryFile` for rsync, deleted after.
- Timeout per rsync call: 5 seconds (consistent with `sync.sh`).
- Overall tool timeout: 60 seconds (consistent with `sync_now`).

## Test plan

Unit tests in `tests/test_server.py`, following existing pattern: mock filesystem via `tmp_path`
+ `monkeypatch`, mock `subprocess.run` for rsync and SSH calls, mock `config.json` via a
`mock_config` fixture.

### Source resolution
- File found in cache → proceeds to push
- File not found in cache → error result
- `MEMORY.md` as `file` argument → immediate error
- `content=` provided → that content is used; cached file ignored

### Target scoping
- `target_vms` narrows to listed VMs only
- Default includes all configured VMs including localhost
- localhost skips nc reachability check

### src == dest guard
- Same VM + same project → `skipped: source and destination are the same file`
- Same VM + different project (broadcast mode) → proceeds normally

### Reachability
- Non-localhost VM unreachable (nc fails) → `skipped: unreachable`
- Non-localhost VM reachable → proceeds

### Targeted mode
- Matching project found on target VM → attempts push
- No matching project on target VM → `skipped: project not on this VM`

### Broadcast mode
- All `memory_paths` on VM attempted
- Path matching src is skipped (src == dest), others proceed

### Conflict handling
- File absent on dest → `pushed`
- File exists, `overwrite=False` → `skipped: exists` with existing content in result
- File exists, `overwrite=True` → `pushed`
- rsync subprocess fails → `error` with stderr in result

### Return shape
- JSON array, one entry per destination attempted
- Each entry has `vm`, `project`, `dest`, `status`, and optional `reason` / `existing_content` / `error`

## Out of scope

- Pushing `MEMORY.md` index files (guarded)
- Automatic/scheduled pushing (by design: on-demand only)
- Merging conflicting memory files (skip+warn is sufficient for now)
- Creating new projects on target VMs (only pushes to paths already in config)
