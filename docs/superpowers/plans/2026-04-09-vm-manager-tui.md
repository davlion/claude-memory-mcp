# VM Manager TUI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build an InquirerPy-based TUI (`manage-vms.py`) for managing VM configurations, replacing the bash VM prompting in `install.sh`.

**Architecture:** Single Python file at project root that reads/writes `~/.claude-memories/config.json` and `~/.claude-memories/validation.json`. Supports interactive TUI mode (default) and non-interactive `--test-all` mode. `install.sh` delegates VM configuration to this tool.

**Tech Stack:** Python 3, InquirerPy, subprocess, argparse, json, pathlib

---

### Task 1: Install InquirerPy and scaffold manage-vms.py with config I/O

**Files:**
- Create: `manage-vms.py`
- Create: `tests/test_manage_vms.py`

- [ ] **Step 1: Install InquirerPy into the venv**

Run:
```bash
.venv/bin/pip install InquirerPy
```

- [ ] **Step 2: Write tests for config loading/saving and validation I/O**

```python
"""Tests for manage-vms.py config and validation I/O."""

import json
from pathlib import Path

import pytest

from manage_vms import load_config, save_config, load_validation, save_validation

DEFAULT_CONFIG = {
    "vms": [],
    "local_cache": "~/.claude-memories",
    "sync_interval_minutes": 5,
}


class TestLoadConfig:
    def test_creates_default_when_missing(self, tmp_path):
        config_path = tmp_path / "config.json"
        config = load_config(config_path)
        assert config == DEFAULT_CONFIG
        assert config_path.exists()

    def test_loads_existing(self, tmp_path):
        config_path = tmp_path / "config.json"
        data = {"vms": [{"name": "vm1"}], "local_cache": "~/.claude-memories", "sync_interval_minutes": 5}
        config_path.write_text(json.dumps(data), encoding="utf-8")
        config = load_config(config_path)
        assert config["vms"] == [{"name": "vm1"}]

    def test_exits_on_corrupt(self, tmp_path):
        config_path = tmp_path / "config.json"
        config_path.write_text("not json!", encoding="utf-8")
        with pytest.raises(SystemExit):
            load_config(config_path)


class TestSaveConfig:
    def test_writes_json(self, tmp_path):
        config_path = tmp_path / "config.json"
        data = {"vms": [], "local_cache": "~/.claude-memories", "sync_interval_minutes": 5}
        save_config(config_path, data)
        assert json.loads(config_path.read_text(encoding="utf-8")) == data

    def test_sets_permissions(self, tmp_path):
        config_path = tmp_path / "config.json"
        save_config(config_path, DEFAULT_CONFIG)
        assert oct(config_path.stat().st_mode & 0o777) == "0o600"


class TestLoadValidation:
    def test_returns_empty_when_missing(self, tmp_path):
        val_path = tmp_path / "validation.json"
        assert load_validation(val_path) == {}

    def test_loads_existing(self, tmp_path):
        val_path = tmp_path / "validation.json"
        data = {"vm1": {"ssh": True, "paths": {}, "last_tested": "2026-04-09T10:00:00"}}
        val_path.write_text(json.dumps(data), encoding="utf-8")
        assert load_validation(val_path) == data

    def test_returns_empty_on_corrupt(self, tmp_path):
        val_path = tmp_path / "validation.json"
        val_path.write_text("bad", encoding="utf-8")
        assert load_validation(val_path) == {}


class TestSaveValidation:
    def test_writes_and_prunes(self, tmp_path):
        val_path = tmp_path / "validation.json"
        validation = {
            "vm1": {"ssh": True, "paths": {}, "last_tested": "2026-04-09T10:00:00"},
            "old-vm": {"ssh": False, "paths": {}, "last_tested": "2026-04-01T10:00:00"},
        }
        vm_names = ["vm1"]
        save_validation(val_path, validation, vm_names)
        saved = json.loads(val_path.read_text(encoding="utf-8"))
        assert "vm1" in saved
        assert "old-vm" not in saved
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_manage_vms.py -v`
Expected: ImportError — `manage_vms` module not found.

- [ ] **Step 4: Implement config and validation I/O in manage-vms.py**

```python
#!/usr/bin/env python3
"""VM Manager TUI for claude-memory-mcp."""

import json
import os
import sys
from pathlib import Path

SSH_KEY = Path.home() / ".ssh" / "claude_memory_ed25519"

DEFAULT_CONFIG = {
    "vms": [],
    "local_cache": "~/.claude-memories",
    "sync_interval_minutes": 5,
}


def load_config(config_path: Path) -> dict:
    """Load config.json, creating default if missing. Exit on corruption."""
    if not config_path.exists():
        save_config(config_path, DEFAULT_CONFIG)
        return dict(DEFAULT_CONFIG)
    try:
        return json.loads(config_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        print(f"Error: cannot read {config_path}: {e}", file=sys.stderr)
        sys.exit(1)


def save_config(config_path: Path, config: dict) -> None:
    """Write config.json with restricted permissions."""
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
    os.chmod(config_path, 0o600)


def load_validation(val_path: Path) -> dict:
    """Load validation.json, returning {} if missing or corrupt."""
    if not val_path.exists():
        return {}
    try:
        return json.loads(val_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def save_validation(val_path: Path, validation: dict, vm_names: list[str]) -> None:
    """Write validation.json, pruning entries for VMs no longer in config."""
    pruned = {k: v for k, v in validation.items() if k in vm_names}
    val_path.write_text(json.dumps(pruned, indent=2) + "\n", encoding="utf-8")
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_manage_vms.py -v`
Expected: All 9 tests PASS.

- [ ] **Step 6: Commit**

```bash
git add manage-vms.py tests/test_manage_vms.py
git commit -m "feat: scaffold manage-vms.py with config and validation I/O"
```

---

### Task 2: ANSI color helpers and validation status logic

**Files:**
- Modify: `manage-vms.py`
- Modify: `tests/test_manage_vms.py`

- [ ] **Step 1: Write tests for color helpers and status derivation**

Add to `tests/test_manage_vms.py`:

```python
from manage_vms import color_green, color_yellow, color_red, vm_status, vm_status_label


class TestColors:
    def test_green(self):
        assert color_green("ok") == "\033[32mok\033[0m"

    def test_yellow(self):
        assert color_yellow("warn") == "\033[33mwarn\033[0m"

    def test_red(self):
        assert color_red("fail") == "\033[31mfail\033[0m"


class TestVmStatus:
    def test_no_validation_data(self):
        assert vm_status({}, "vm1") == "red"

    def test_ssh_failed(self):
        validation = {"vm1": {"ssh": False, "paths": {}, "last_tested": ""}}
        assert vm_status(validation, "vm1") == "red"

    def test_all_paths_found(self):
        validation = {"vm1": {"ssh": True, "paths": {"/a": True, "/b": True}, "last_tested": ""}}
        assert vm_status(validation, "vm1") == "green"

    def test_some_paths_missing(self):
        validation = {"vm1": {"ssh": True, "paths": {"/a": True, "/b": False}, "last_tested": ""}}
        assert vm_status(validation, "vm1") == "yellow"

    def test_ssh_ok_no_paths(self):
        validation = {"vm1": {"ssh": True, "paths": {}, "last_tested": ""}}
        assert vm_status(validation, "vm1") == "green"


class TestVmStatusLabel:
    def test_green_label(self):
        label = vm_status_label("green")
        assert "validated" in label
        assert "\033[32m" in label

    def test_yellow_label(self):
        label = vm_status_label("yellow")
        assert "partial" in label
        assert "\033[33m" in label

    def test_red_label(self):
        label = vm_status_label("red")
        assert "not validated" in label
        assert "\033[31m" in label
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_manage_vms.py::TestColors -v`
Expected: ImportError.

- [ ] **Step 3: Implement color helpers and status logic**

Add to `manage-vms.py` after the I/O functions:

```python
# ── ANSI colors ──────────────────────────────────────────────────────────

def color_green(text: str) -> str:
    return f"\033[32m{text}\033[0m"

def color_yellow(text: str) -> str:
    return f"\033[33m{text}\033[0m"

def color_red(text: str) -> str:
    return f"\033[31m{text}\033[0m"


# ── Validation status ────────────────────────────────────────────────────

def vm_status(validation: dict, vm_name: str) -> str:
    """Return 'green', 'yellow', or 'red' for a VM's validation state."""
    info = validation.get(vm_name)
    if not info or not info.get("ssh"):
        return "red"
    paths = info.get("paths", {})
    if paths and not all(paths.values()):
        return "yellow"
    return "green"


def vm_status_label(status: str) -> str:
    """Return a colored status label string."""
    if status == "green":
        return color_green("validated")
    if status == "yellow":
        return color_yellow("partial")
    return color_red("not validated")


def colored_vm_name(vm_name: str, validation: dict) -> str:
    """Return VM name colored by its validation status."""
    status = vm_status(validation, vm_name)
    if status == "green":
        return color_green(vm_name)
    if status == "yellow":
        return color_yellow(vm_name)
    return color_red(vm_name)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_manage_vms.py -v`
Expected: All tests PASS.

- [ ] **Step 5: Commit**

```bash
git add manage-vms.py tests/test_manage_vms.py
git commit -m "feat: add ANSI color helpers and validation status logic"
```

---

### Task 3: SSH test and path validation functions

**Files:**
- Modify: `manage-vms.py`
- Modify: `tests/test_manage_vms.py`

- [ ] **Step 1: Write tests for test_vm_connection**

Add to `tests/test_manage_vms.py`:

```python
from unittest.mock import patch, MagicMock
from manage_vms import test_vm_connection


class TestTestVmConnection:
    def _make_vm(self, name="vm1", host="host1", user="user1", paths=None):
        return {
            "name": name,
            "host": host,
            "user": user,
            "ssh_key": "~/.ssh/claude_memory_ed25519",
            "memory_paths": paths or ["/home/user1/.claude/projects/-proj/memory"],
        }

    @patch("manage_vms.subprocess.run")
    def test_ssh_fails(self, mock_run):
        mock_run.return_value = MagicMock(returncode=1)
        result = test_vm_connection(self._make_vm())
        assert result["ssh"] is False
        assert result["paths"] == {}

    @patch("manage_vms.subprocess.run")
    def test_ssh_ok_all_paths_found(self, mock_run):
        # First call: ssh echo ok (success). Second call: test -d (success).
        mock_run.return_value = MagicMock(returncode=0)
        result = test_vm_connection(self._make_vm())
        assert result["ssh"] is True
        assert all(result["paths"].values())

    @patch("manage_vms.subprocess.run")
    def test_ssh_ok_path_missing(self, mock_run):
        # ssh echo ok succeeds, test -d fails
        mock_run.side_effect = [
            MagicMock(returncode=0),  # ssh echo ok
            MagicMock(returncode=1),  # test -d fails
        ]
        vm = self._make_vm(paths=["/missing/path"])
        result = test_vm_connection(vm)
        assert result["ssh"] is True
        assert result["paths"]["/missing/path"] is False

    @patch("manage_vms.subprocess.run")
    def test_result_has_last_tested(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0)
        result = test_vm_connection(self._make_vm())
        assert "last_tested" in result
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_manage_vms.py::TestTestVmConnection -v`
Expected: ImportError.

- [ ] **Step 3: Implement test_vm_connection**

Add to `manage-vms.py`:

```python
import subprocess
from datetime import datetime, timezone


def _ssh_base_args(vm: dict) -> list[str]:
    """Return common SSH args for a VM."""
    key = str(Path(vm["ssh_key"]).expanduser())
    return [
        "ssh",
        "-i", key,
        "-o", "ConnectTimeout=5",
        "-o", "BatchMode=yes",
        "-o", "StrictHostKeyChecking=accept-new",
        f"{vm['user']}@{vm['host']}",
    ]


def test_vm_connection(vm: dict) -> dict:
    """Test SSH connectivity and path existence for a VM. Returns validation entry."""
    result = {"ssh": False, "paths": {}, "last_tested": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")}

    # Test SSH
    try:
        proc = subprocess.run(
            _ssh_base_args(vm) + ["echo", "ok"],
            capture_output=True, timeout=10,
        )
        if proc.returncode != 0:
            return result
    except (subprocess.TimeoutExpired, OSError):
        return result

    result["ssh"] = True

    # Test each memory path
    for path in vm.get("memory_paths", []):
        try:
            proc = subprocess.run(
                _ssh_base_args(vm) + ["test", "-d", path],
                capture_output=True, timeout=10,
            )
            result["paths"][path] = proc.returncode == 0
        except (subprocess.TimeoutExpired, OSError):
            result["paths"][path] = False

    return result


def print_test_result(vm_name: str, result: dict) -> None:
    """Print test results for a single VM."""
    if not result["ssh"]:
        print(f"  {color_red(vm_name)}: SSH FAILED")
        return
    has_missing = any(not v for v in result["paths"].values())
    name_colored = color_yellow(vm_name) if has_missing else color_green(vm_name)
    print(f"  {name_colored}: SSH OK")
    for path, found in result["paths"].items():
        status = "found" if found else color_red("NOT FOUND")
        print(f"    {path} — {status}")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_manage_vms.py -v`
Expected: All tests PASS.

- [ ] **Step 5: Commit**

```bash
git add manage-vms.py tests/test_manage_vms.py
git commit -m "feat: add SSH and path validation functions"
```

---

### Task 4: Implement all TUI menu actions

**Files:**
- Modify: `manage-vms.py`

This task implements the interactive menu actions. These use InquirerPy prompts which are difficult to unit test meaningfully (they require terminal interaction). The core logic (config I/O, validation, SSH testing) is already tested. This task wires them together with the TUI.

- [ ] **Step 1: Add the list_vms action**

Add to `manage-vms.py`:

```python
from InquirerPy import inquirer


def action_list_vms(config: dict, validation: dict) -> None:
    """Print a table of all configured VMs."""
    vms = config.get("vms", [])
    if not vms:
        print("\n  No VMs configured.\n")
        return
    print()
    print(f"  {'Name':<20} {'Host':<25} {'User':<15} {'Paths':<6} {'Status'}")
    print(f"  {'─' * 20} {'─' * 25} {'─' * 15} {'─' * 6} {'─' * 15}")
    for vm in vms:
        name = vm["name"]
        status = vm_status(validation, name)
        label = vm_status_label(status)
        name_col = colored_vm_name(name, validation)
        print(f"  {name_col:<29} {vm['host']:<25} {vm['user']:<15} {len(vm.get('memory_paths', [])):<6} {label}")
    print()
```

Note: `name_col` padding is 29 (20 visible chars + 9 for ANSI escape codes `\033[XXm` + `\033[0m`).

- [ ] **Step 2: Add the action_add_vm function**

```python
def action_add_vm(config: dict, config_path: Path, validation: dict, val_path: Path) -> None:
    """Prompt for VM details and add to config."""
    vms = config.get("vms", [])
    existing_names = {vm["name"] for vm in vms}

    # Name
    while True:
        name = inquirer.text(message="VM name (e.g. dev-vm):").execute()
        if not name.strip():
            print("  Name cannot be empty.")
            continue
        if name in existing_names:
            print(f"  VM '{name}' already exists.")
            continue
        break

    host = inquirer.text(message="Hostname or IP:").execute()
    user = inquirer.text(message="SSH username:").execute()

    # Memory paths — copy from existing or enter manually
    memory_paths = []
    if vms:
        copy = inquirer.confirm(message="Copy memory paths from an existing VM?", default=True).execute()
        if copy:
            source_name = inquirer.select(
                message="Copy paths from:",
                choices=[vm["name"] for vm in vms],
            ).execute()
            source = next(vm for vm in vms if vm["name"] == source_name)
            memory_paths = list(source.get("memory_paths", []))
            print(f"  Copied {len(memory_paths)} path(s) from {source_name}.")

    # Add paths manually
    while True:
        path = inquirer.text(message="Memory path (empty to stop):").execute()
        if not path.strip():
            break
        path = path.strip()
        if path in memory_paths:
            print(f"  Path already configured, skipping.")
            continue
        memory_paths.append(path)

    if not memory_paths:
        print("  Warning: no memory paths configured for this VM.")

    new_vm = {
        "name": name,
        "host": host,
        "user": user,
        "ssh_key": "~/.ssh/claude_memory_ed25519",
        "memory_paths": memory_paths,
    }
    config["vms"].append(new_vm)
    save_config(config_path, config)
    print(f"\n  Added '{name}'.")

    # Offer to copy SSH key
    if SSH_KEY.exists():
        copy_key = inquirer.confirm(message=f"Copy SSH key to {user}@{host}?", default=True).execute()
        if copy_key:
            _copy_ssh_key(new_vm)

    # Auto-test
    print(f"\n  Testing connection to {name}...")
    result = test_vm_connection(new_vm)
    validation[name] = result
    save_validation(val_path, validation, [vm["name"] for vm in config["vms"]])
    print_test_result(name, result)

    # First VM: offer to install launchd
    if len(config["vms"]) == 1:
        _offer_launchd_install()


def _copy_ssh_key(vm: dict) -> None:
    """Run ssh-copy-id for a VM."""
    key = str(SSH_KEY)
    try:
        proc = subprocess.run(
            ["ssh-copy-id", "-i", key, f"{vm['user']}@{vm['host']}"],
            timeout=30,
        )
        if proc.returncode == 0:
            print(f"  Key copied to {vm['name']}.")
        else:
            print(f"  Failed to copy key to {vm['name']}.")
    except (subprocess.TimeoutExpired, OSError) as e:
        print(f"  Failed to copy key to {vm['name']}: {e}")


def _offer_launchd_install() -> None:
    """Offer to install/reload the launchd plist."""
    script_dir = Path(__file__).resolve().parent
    plist_name = "com.claude.memory-sync"
    plist_dir = Path.home() / "Library" / "LaunchAgents"
    plist_path = plist_dir / f"{plist_name}.plist"
    sync_log = Path.home() / ".claude-memories" / "sync.log"

    install = inquirer.confirm(message="Install launchd sync job (every 5 min)?", default=True).execute()
    if not install:
        return

    plist_dir.mkdir(parents=True, exist_ok=True)
    plist_content = f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>{plist_name}</string>
    <key>ProgramArguments</key>
    <array>
        <string>/bin/bash</string>
        <string>{script_dir / "sync.sh"}</string>
    </array>
    <key>StartInterval</key>
    <integer>300</integer>
    <key>RunAtLoad</key>
    <true/>
    <key>StandardOutPath</key>
    <string>{sync_log}</string>
    <key>StandardErrorPath</key>
    <string>{sync_log}</string>
</dict>
</plist>"""
    plist_path.write_text(plist_content, encoding="utf-8")

    # Reload
    subprocess.run(["launchctl", "unload", str(plist_path)], capture_output=True)
    proc = subprocess.run(["launchctl", "load", str(plist_path)], capture_output=True)
    if proc.returncode == 0:
        print("  Launchd sync job installed.")
    else:
        print(f"  Could not load plist. Load manually: launchctl load \"{plist_path}\"")
```

- [ ] **Step 3: Add remaining actions**

```python
def action_add_memory_paths(config: dict, config_path: Path) -> None:
    """Add memory paths to an existing VM."""
    vms = config.get("vms", [])
    vm_name = inquirer.select(
        message="Select VM:",
        choices=[vm["name"] for vm in vms],
    ).execute()
    vm = next(v for v in vms if v["name"] == vm_name)
    existing = set(vm.get("memory_paths", []))
    added = 0

    while True:
        path = inquirer.text(message="Memory path (empty to stop):").execute()
        if not path.strip():
            break
        path = path.strip()
        if path in existing:
            print("  Path already configured, skipping.")
            continue
        vm.setdefault("memory_paths", []).append(path)
        existing.add(path)
        added += 1

    if added:
        save_config(config_path, config)
        print(f"  Added {added} path(s) to {vm_name}.")
    else:
        print("  No paths added.")


def action_remove_vm(config: dict, config_path: Path, validation: dict, val_path: Path) -> None:
    """Remove a VM from config."""
    vms = config.get("vms", [])
    vm_name = inquirer.select(
        message="Select VM to remove:",
        choices=[vm["name"] for vm in vms],
    ).execute()
    confirm = inquirer.confirm(message=f"Remove '{vm_name}'? This cannot be undone.", default=False).execute()
    if not confirm:
        print("  Cancelled.")
        return
    config["vms"] = [vm for vm in vms if vm["name"] != vm_name]
    save_config(config_path, config)
    save_validation(val_path, validation, [vm["name"] for vm in config["vms"]])
    print(f"  Removed '{vm_name}'.")


def action_test_connection(config: dict, validation: dict, val_path: Path) -> None:
    """Test connection to a single VM."""
    vms = config.get("vms", [])
    vm_name = inquirer.select(
        message="Select VM to test:",
        choices=[vm["name"] for vm in vms],
    ).execute()
    vm = next(v for v in vms if v["name"] == vm_name)
    print(f"\n  Testing {vm_name}...")
    result = test_vm_connection(vm)
    validation[vm_name] = result
    save_validation(val_path, validation, [v["name"] for v in vms])
    print_test_result(vm_name, result)
    print()


def action_test_all(config: dict, validation: dict, val_path: Path) -> None:
    """Test connections to all VMs."""
    vms = config.get("vms", [])
    print()
    for vm in vms:
        print(f"  Testing {vm['name']}...")
        result = test_vm_connection(vm)
        validation[vm["name"]] = result
        print_test_result(vm["name"], result)
    save_validation(val_path, validation, [v["name"] for v in vms])
    print()


def action_copy_ssh_key(config: dict, validation: dict, val_path: Path) -> None:
    """Copy SSH key to a VM, then test connection."""
    if not SSH_KEY.exists():
        print(f"\n  SSH key not found at {SSH_KEY}. Run install.sh first.\n")
        return
    vms = config.get("vms", [])
    vm_name = inquirer.select(
        message="Select VM:",
        choices=[vm["name"] for vm in vms],
    ).execute()
    vm = next(v for v in vms if v["name"] == vm_name)
    _copy_ssh_key(vm)
    print(f"  Testing connection...")
    result = test_vm_connection(vm)
    validation[vm_name] = result
    save_validation(val_path, validation, [v["name"] for v in vms])
    print_test_result(vm_name, result)
    print()
```

- [ ] **Step 4: Commit**

```bash
git add manage-vms.py
git commit -m "feat: implement all TUI menu actions"
```

---

### Task 5: Main menu loop and CLI argument handling

**Files:**
- Modify: `manage-vms.py`

- [ ] **Step 1: Implement the Done action with unvalidated VM check**

Add to `manage-vms.py`:

```python
def action_done(config: dict, validation: dict, val_path: Path) -> bool:
    """Handle exit. Returns True if should exit."""
    vms = config.get("vms", [])
    unvalidated = [vm for vm in vms if vm_status(validation, vm["name"]) != "green"]
    if not unvalidated:
        return True

    print("\n  Warning: the following VMs are not fully validated:")
    for vm in unvalidated:
        status = vm_status(validation, vm["name"])
        print(f"    {colored_vm_name(vm['name'], validation)} — {vm_status_label(status)}")

    if not SSH_KEY.exists():
        print(f"\n  SSH key not found at {SSH_KEY}. Skipping key copy offer.\n")
        return True

    copy_all = inquirer.confirm(
        message="Copy SSH key to all unvalidated VMs?",
        default=False,
    ).execute()
    if copy_all:
        for vm in unvalidated:
            print(f"\n  Copying key to {vm['name']}...")
            _copy_ssh_key(vm)
            print(f"  Testing connection...")
            result = test_vm_connection(vm)
            validation[vm["name"]] = result
            save_validation(val_path, validation, [v["name"] for v in config["vms"]])
            print_test_result(vm["name"], result)
    print()
    return True
```

- [ ] **Step 2: Implement the main menu loop**

```python
def main_menu(config_path: Path) -> None:
    """Run the interactive TUI main menu loop."""
    config = load_config(config_path)
    val_path = config_path.parent / "validation.json"
    validation = load_validation(val_path)

    print("\n  claude-memory-mcp: VM Manager\n")

    while True:
        vms = config.get("vms", [])
        has_vms = len(vms) > 0

        choices = ["List VMs", "Add VM"]
        if has_vms:
            choices.extend([
                "Add memory paths to VM",
                "Remove VM",
                "Test connection (select VM)",
                "Test all connections",
                "Copy SSH key",
            ])
        choices.append("Done")

        try:
            action = inquirer.select(
                message="Choose action:",
                choices=choices,
            ).execute()
        except KeyboardInterrupt:
            action = "Done"

        if action == "List VMs":
            action_list_vms(config, validation)
        elif action == "Add VM":
            action_add_vm(config, config_path, validation, val_path)
        elif action == "Add memory paths to VM":
            action_add_memory_paths(config, config_path)
        elif action == "Remove VM":
            action_remove_vm(config, config_path, validation, val_path)
        elif action == "Test connection (select VM)":
            action_test_connection(config, validation, val_path)
        elif action == "Test all connections":
            action_test_all(config, validation, val_path)
        elif action == "Copy SSH key":
            action_copy_ssh_key(config, validation, val_path)
        elif action == "Done":
            if action_done(config, validation, val_path):
                break
```

- [ ] **Step 3: Implement CLI argument parsing and main entry point**

```python
import argparse


def run_test_all(config_path: Path) -> int:
    """Non-interactive: test all VMs, return 0 if all green, 1 otherwise."""
    config = load_config(config_path)
    val_path = config_path.parent / "validation.json"
    validation = load_validation(val_path)
    vms = config.get("vms", [])

    if not vms:
        print("No VMs configured.")
        return 1

    all_green = True
    for vm in vms:
        print(f"Testing {vm['name']}...")
        result = test_vm_connection(vm)
        validation[vm["name"]] = result
        print_test_result(vm["name"], result)
        if vm_status(validation, vm["name"]) != "green":
            all_green = False

    save_validation(val_path, validation, [v["name"] for v in vms])
    return 0 if all_green else 1


def main():
    default_config = Path.home() / ".claude-memories" / "config.json"
    parser = argparse.ArgumentParser(description="Manage VMs for claude-memory-mcp")
    parser.add_argument("--config", type=Path, default=default_config, help="Path to config.json")
    parser.add_argument("--test-all", action="store_true", help="Test all VM connections and exit")
    args = parser.parse_args()

    if args.test_all:
        sys.exit(run_test_all(args.config))
    else:
        main_menu(args.config)


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Manually test the TUI**

Run: `.venv/bin/python3 manage-vms.py --config /tmp/test-config.json`
Expected: Menu appears with "List VMs", "Add VM", "Done". Adding a VM works, list shows it.

- [ ] **Step 5: Commit**

```bash
git add manage-vms.py
git commit -m "feat: add main menu loop and CLI argument handling"
```

---

### Task 6: Update install.sh to use manage-vms.py

**Files:**
- Modify: `install.sh`

- [ ] **Step 1: Remove bash VM prompting code**

Remove from `install.sh`:
- The `prompt_vm()` function (lines 16-40)
- The `--add-vm` handler block (lines 74-107)
- The VM gathering loop "step 4" (lines 162-177)
- The config.json writing "step 4" (lines 179-199)
- The SSH key instructions and copy offer at the end (lines 244-284)

- [ ] **Step 2: Add InquirerPy to venv install**

Replace:
```bash
    "$VENV_DIR/bin/pip" install --quiet mcp
    echo "  Installed mcp package into venv."
```

With:
```bash
    "$VENV_DIR/bin/pip" install --quiet mcp InquirerPy
    echo "  Installed mcp and InquirerPy packages into venv."
```

Also update the existing-venv check to verify InquirerPy:
```bash
if [[ -d "$VENV_DIR" ]] && "$VENV_DIR/bin/python3" -c "import mcp; import InquirerPy" &>/dev/null; then
```

- [ ] **Step 3: Replace VM steps with TUI call**

After the SSH keypair step, replace the removed VM steps with:

```bash
# ── 3. VM configuration via TUI ──────────────────────────────────────
echo "--- VM configuration ---"
echo "Launching VM manager..."
echo ""
"$VENV_DIR/bin/python3" "$SCRIPT_DIR/manage-vms.py" --config "$CONFIG_FILE"
echo ""
```

- [ ] **Step 4: Make launchd install conditional on VMs existing**

Replace the unconditional launchd plist install with:

```bash
# ── 4. Install launchd plist (if VMs configured) ─────────────────────
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
    if launchctl list "$PLIST_NAME" &>/dev/null; then
        launchctl unload "$PLIST_PATH" 2>/dev/null || true
    fi
    launchctl load "$PLIST_PATH" 2>/dev/null && echo "  Loaded launchd job." || echo "  (Could not load plist — load it manually with: launchctl load \"$PLIST_PATH\")"
    echo ""
else
    echo "--- Skipping launchd plist (no VMs configured) ---"
    echo "  Run ./manage-vms.py to add VMs later."
    echo "  The sync job will be installed when you add your first VM."
    echo ""
fi
```

- [ ] **Step 5: Update intro text**

Replace the intro echo block with:

```bash
echo "This script will:"
echo "  1. Create $MEMORY_DIR directory"
echo "  2. Set up a Python venv and install dependencies"
echo "  3. Generate an SSH keypair at $SSH_KEY (if needed)"
echo "  4. Launch the VM manager to configure your VMs"
echo "  5. Install a launchd plist to sync every 5 minutes"
echo "  6. Show how to configure Claude Desktop"
```

- [ ] **Step 6: Simplify the closing output**

Replace the closing section (after launchd) with:

```bash
# ── 5. Claude Desktop instructions ────────────────────────────────────
echo "========================================"
echo "  Setup complete!"
echo "========================================"
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
echo "To manage VMs later, run: ./manage-vms.py"
echo "Sync log: $SYNC_LOG"
echo ""
```

- [ ] **Step 7: Verify the full install.sh reads cleanly**

Read through the modified `install.sh` end-to-end and verify the flow is:
1. Pre-flight checks
2. Intro
3. Create directories
4. Python venv (mcp + InquirerPy)
5. SSH keypair
6. VM manager TUI
7. Launchd plist (conditional)
8. Claude Desktop instructions

- [ ] **Step 8: Commit**

```bash
git add install.sh
git commit -m "refactor: install.sh delegates VM config to manage-vms.py TUI"
```

---

### Task 7: Add validation.json to .gitignore and final cleanup

**Files:**
- Modify: `.gitignore`

- [ ] **Step 1: Add validation.json to .gitignore**

Add `validation.json` to `.gitignore` (after `last-sync.json`).

- [ ] **Step 2: Make manage-vms.py executable**

Run:
```bash
chmod +x manage-vms.py
```

- [ ] **Step 3: Run full test suite**

Run: `.venv/bin/pytest tests/ -v`
Expected: All tests PASS (existing server tests + new manage_vms tests).

- [ ] **Step 4: Manual end-to-end test**

Run: `.venv/bin/python3 manage-vms.py --config /tmp/e2e-test-config.json`

Test the full flow:
1. Add a VM (verify it appears in config)
2. List VMs (verify table renders with red status)
3. Test connection (verify status updates)
4. Add memory paths
5. Remove VM
6. Done (verify unvalidated warning)

- [ ] **Step 5: Commit and push**

```bash
git add .gitignore manage-vms.py
git commit -m "chore: add validation.json to gitignore, make manage-vms.py executable"
git push origin master
```
