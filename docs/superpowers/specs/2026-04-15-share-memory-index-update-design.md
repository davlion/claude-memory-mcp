# Design: MEMORY.md Index Update on `share_memory`

**Date:** 2026-04-15
**Status:** Approved

## Background

`share_memory` pushes a memory file to target VMs/projects. Without a corresponding
MEMORY.md entry on the target, the file is invisible — Claude on that machine won't
know to load it. This design extends `share_memory` to automatically append an index
entry to each target's MEMORY.md after a successful file push.

## Approach

After each successful file push, `share_memory` reads the target's MEMORY.md, checks
whether the filename is already listed, and if not, appends the entry and pushes the
updated MEMORY.md. The same logic runs in `_process_pending_shares` when a queued
push is retried.

## Frontmatter Parsing

A new helper `_parse_frontmatter(content: str) -> dict` extracts `name` and
`description` from the YAML block between `---` delimiters. No external YAML library —
plain line-by-line `key: value` extraction.

The MEMORY.md entry line is built from the result:

```
- [Name](filename.md) — description
```

Fallbacks:
- `name` absent → filename stem (e.g. `feedback_debugging`)
- `description` absent → entry has no ` — ` suffix
- Frontmatter absent entirely → filename stem, no description

Parsing is done once, before the VM loop, from `source_content` (already resolved from
cache or `content=` override).

## Push Flow Changes in `share_memory`

After a successful file rsync to a target, two additional steps:

1. **Read target MEMORY.md**
   - Remote: `ssh <opts> user@host "cat \"$HOME/.../memory/MEMORY.md\" 2>/dev/null || echo __NOT_FOUND__"`
   - Localhost: direct `Path.read_text()`, missing → empty string
2. **Check and append**
   - If the filename appears anywhere in MEMORY.md content: skip, no push.
   - Otherwise: append the entry line and push updated MEMORY.md via rsync (same SSH
     opts, `--timeout=5`).

The result entry for a pushed destination gains a `memory_index` field:

| Value | Meaning |
|---|---|
| `"updated"` | Entry appended and pushed |
| `"already_present"` | Filename found in existing index; no change |
| `"error: <reason>"` | Read or push of MEMORY.md failed |

MEMORY.md update failures are **non-fatal**. The file push is still reported as
`"pushed"`; only `memory_index` reflects the failure. There is no retry for MEMORY.md
failures — they surface in the result for the caller to handle.

No change to `skipped` or `error` results — if the file wasn't pushed, MEMORY.md is
not touched.

## Queue Integration

`_process_pending_shares` runs the same MEMORY.md update logic after each successful
file push. Queue entries already carry `file` and `content`, so no schema changes are
needed.

MEMORY.md update failures in queue processing are also non-fatal. The queue entry is
removed (push succeeded); `memory_index: "error: ..."` appears in the sync_now result.

## No Locking or Synchronization

MEMORY.md updates are plain file overwrites. There is no locking, no atomic
read-modify-write, and no coordination between concurrent `share_memory` calls or
between a push and an in-progress sync. Last writer wins. This is acceptable: there is
a single user who can only issue one command at a time.

## Edge Cases

- **MEMORY.md missing on target** — treat as empty, create with the single entry line.
- **SSH timeout reading MEMORY.md** — skip update, report `memory_index: "error: timed out"`.
- **rsync fails pushing MEMORY.md** — non-fatal, `memory_index: "error: ..."`.
- **Filename already in index** — `memory_index: "already_present"`, no push.
- **broadcast=True, src==dest destination skipped** — file push skipped, no index update.

## Implementation Notes

- All logic in `server.py`. No new files.
- `_parse_frontmatter` is a module-level helper alongside the other `_` helpers.
- MEMORY.md update reuses `_ssh_opts` and the same rsync pattern as the file push.
- For localhost targets, MEMORY.md is read and written directly (no SSH/rsync).

## Test Plan

### Happy path
- File pushed, frontmatter has `name` + `description` → entry appended, `memory_index: "updated"`
- File pushed via `content=` override → frontmatter from that content drives the entry
- Queue entry retried successfully → MEMORY.md also updated, `memory_index: "updated"`

### Guards and errors
- Filename already in target MEMORY.md → `memory_index: "already_present"`, index not pushed
- MEMORY.md missing on target → created with the single entry line
- SSH read of MEMORY.md times out → `memory_index: "error: timed out"`, file result unaffected
- rsync push of MEMORY.md fails → `memory_index: "error: ..."`, file result still `"pushed"`
- File push skipped (exists, `overwrite=False`) → no MEMORY.md update attempted
- File push skipped (src==dest) → no MEMORY.md update attempted

### Edge cases
- Frontmatter missing `description` → entry is `- [Name](file.md)` with no ` — ` suffix
- Frontmatter missing `name` → filename stem used as display name
- Frontmatter absent entirely → filename stem, no description
- Broadcast mode: each destination gets its own independent MEMORY.md check/update
