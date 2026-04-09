# VM Manager TUI Design

## Overview

A single-file Python TUI (`manage-vms.py`) using InquirerPy that replaces the bash VM prompting in `install.sh` and serves as the ongoing tool for managing VM configurations. Reads and writes `~/.claude-memories/config.json`.

## CLI Interface

- `manage-vms.py` — launches interactive TUI (default)
- `manage-vms.py --config PATH` — override config file path
- `manage-vms.py --test-all` — non-interactive, test all VMs, exit with 0 if all pass, non-zero if any fail

## Config File

Path: `~/.claude-memories/config.json` (overridable via `--config`).

If the file does not exist, creates it with:

```json
{
  "vms": [],
  "local_cache": "~/.claude-memories",
  "sync_interval_minutes": 5
}
```

SSH key path is always `~/.ssh/claude_memory_ed25519`.

## Main Menu

Runs in a loop until the user picks "Done":

```
claude-memory-mcp: VM Manager

> List VMs
  Add VM
  Add memory paths to VM
  Remove VM
  Test connection (select VM)
  Test all connections
  Copy SSH key
  Done
```

Menu items that require existing VMs ("Add memory paths", "Remove VM", "Test connection", "Copy SSH key") are hidden when the VM list is empty.

## Actions

### List VMs

Prints a table of all configured VMs: name, host, user, memory path count, and validation status. VM names are color-coded by validation state (see Validation section). If no VMs configured, prints "No VMs configured."

### Add VM

1. Prompt for name (reject duplicates), host, and user.
2. If other VMs exist, offer "Copy memory paths from an existing VM?"
   - Yes: show VM selector, copy all its memory paths.
   - No: prompt for paths one at a time with "Add another?" loop.
3. Either way, offer to add additional paths after copying.
4. Save config.
5. Offer to copy SSH key to the new VM.
6. Run connection + path validation test automatically.

### Add Memory Paths to VM

1. Select a VM from the list.
2. Prompt for new paths one at a time with "Add another?" loop.
3. Skip duplicates with a note ("path already configured, skipping").
4. Save config.

### Remove VM

1. Select a VM from the list.
2. Confirm with "Are you sure?"
3. Remove and save config.
4. Removing the last VM is allowed (results in empty `vms` array).

### Test Connection (Select VM)

1. Select a VM from the list.
2. Run SSH connection test, then path existence checks.
3. Update validation state.
4. Print results (see Validation section for output format).

### Test All Connections

Run the connection + path test for every VM. Report results per-VM. Update all validation states. Also available non-interactively via `--test-all`.

### Copy SSH Key

1. Select a VM from the list.
2. Run `ssh-copy-id -i ~/.ssh/claude_memory_ed25519 user@host`.
3. On failure, report the error (don't abort).
4. On success, automatically run connection + path validation test.

### Done

1. If any VMs are not validated (red or yellow), print a warning listing them.
2. Offer "Copy SSH key to all unvalidated VMs?"
3. If accepted, run ssh-copy-id + connection test for each.
4. Exit.

Ctrl-C at the main menu is treated as "Done" (with the unvalidated VM check).

## Validation

Validation state is persisted to `~/.claude-memories/validation.json` and loaded on TUI launch, so status survives across runs. VMs not present in the file are treated as unvalidated.

```json
{
  "dev-vm": {
    "ssh": true,
    "paths": {
      "~/.claude/projects/-home-dav-src-foo/memory": true,
      "~/.claude/projects/-home-dav-src-bar/memory": false
    },
    "last_tested": "2026-04-09T14:30:00"
  }
}
```

The file is written after each test. Entries for VMs that have been removed from config are pruned on save.

### Three-tier status

- **Green** — SSH connection succeeded and all memory paths found.
- **Yellow** — SSH connection succeeded but some memory paths not found.
- **Red** — SSH connection failed.

### Test procedure

1. `ssh -o ConnectTimeout=5 -o BatchMode=yes -i <key> user@host echo ok`
2. If SSH fails: mark red, stop.
3. For each memory path: `ssh ... test -d <path>` and report found/not found.
4. If all paths found: green. If some missing: yellow.

### Output format

```
dev-vm: SSH OK
  ~/.claude/projects/-home-dav-src-foo/memory — found
  ~/.claude/projects/-home-dav-src-bar/memory — NOT FOUND
```

### Color coding

Green/yellow/red ANSI colors are used everywhere VM names appear: list table, selection menus, and the warning on Done.

## Integration with install.sh

### Changes to install.sh

- Remove the `prompt_vm` bash function.
- Remove the bash VM prompting loop and config.json writing step.
- Remove the `--add-vm` flag handler.
- Remove the SSH key copy offer at the end.
- Add `InquirerPy` to the venv pip install (alongside `mcp`).
- After SSH keygen, call `"$VENV_DIR/bin/python3" "$SCRIPT_DIR/manage-vms.py" --config "$CONFIG_FILE"` to drop the user into the TUI.
- After the TUI exits, check if any VMs were configured:
  - **Yes**: install the launchd plist and continue as before.
  - **No**: skip the launchd plist. Print: "No VMs configured. Run `./manage-vms.py` to add VMs later. The sync job will be installed when you add your first VM."
- Still show the Claude Desktop config instructions regardless.
- Update step numbering and intro text.

### First VM trigger for launchd

When `manage-vms.py` adds the first VM to a previously-empty config, it offers to install/reload the launchd plist (shelling out to `launchctl` the same way `install.sh` does).

## Error Handling

- **Config corrupt/unreadable**: print error and exit. Do not silently overwrite.
- **SSH key missing**: warn and suggest running `install.sh`.
- **Duplicate VM name**: reject with message, re-prompt.
- **Duplicate memory path**: skip with note.
- **ssh-copy-id fails**: report error, don't abort.
- **Connection timeout**: 5 seconds, report failure, move on.
- **Ctrl-C**: catch `KeyboardInterrupt`, treat as "Done".

## Dependencies

- **InquirerPy**: menus, text prompts, confirmations. Installed in the project venv.
- **ANSI escape codes**: green/yellow/red color coding. No extra library needed.
- Standard library: `json`, `subprocess`, `argparse`, `pathlib`.

## File Layout

One new file at project root: `manage-vms.py`. No other new files.
