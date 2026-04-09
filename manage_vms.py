#!/usr/bin/env python3
"""VM Manager TUI for claude-memory-mcp."""

import json
import os
import subprocess
import sys
from datetime import datetime, timezone
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


# ── SSH testing ──────────────────────────────────────────────────────────

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
