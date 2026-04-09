---
name: memory-sync-status
description: Use when asked whether memory sync is working, when sync seems stale, or to diagnose memory not updating across VMs
---

# Memory Sync Status

Check whether the launchd memory sync job is running correctly.

## Steps

**1. Check launchd job is loaded:**
```bash
launchctl list | grep claude.memory-sync
```
- PID column `-` = not currently running (normal between intervals)
- Exit code `0` = last run succeeded
- Missing line = job not loaded → reinstall via `manage_vms.py`

**2. Check last-sync.json for per-VM status:**
```bash
cat ~/.claude-memories/last-sync.json | jq .
```
- `last_sync`: timestamp of last attempt (UTC)
- `success: true/false`: whether rsync succeeded
- Stale if `last_sync` is >15 min ago

**3. Check sync.log for errors:**
```bash
tail -50 ~/.claude-memories/sync.log
```
- Each run logs `sync started` and `sync complete`
- rsync failures log: `ERROR: rsync failed for <vm>:<path>`
- Empty log = job has never run (check launchctl)

## Quick Diagnosis

| Symptom | Likely cause |
|---------|-------------|
| log empty | Job never ran; check `launchctl list` |
| `success: false` in last-sync.json | rsync/SSH failure; check log for ERROR line |
| last_sync >15 min ago | Job not loaded or VM unreachable |
| job not in `launchctl list` | Reinstall via manage_vms.py → Install launchd sync job |

## Reinstall Job

Run `manage_vms.py` and select **Install launchd sync job**, or manually:
```bash
launchctl load ~/Library/LaunchAgents/com.claude.memory-sync.plist
```
