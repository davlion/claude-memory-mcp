#!/usr/bin/env python3
"""VM Manager TUI for claude-memory-mcp."""

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from InquirerPy import inquirer

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


# ── TUI actions ─────────────────────────────────────────────────────────

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


def action_add_vm(config: dict, config_path: Path, validation: dict, val_path: Path) -> None:
    """Prompt for VM details and add to config."""
    vms = config.get("vms", [])
    existing_names = {vm["name"] for vm in vms}

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

    if SSH_KEY.exists():
        copy_key = inquirer.confirm(message=f"Copy SSH key to {user}@{host}?", default=True).execute()
        if copy_key:
            _copy_ssh_key(new_vm)

    print(f"\n  Testing connection to {name}...")
    result = test_vm_connection(new_vm)
    validation[name] = result
    save_validation(val_path, validation, [vm["name"] for vm in config["vms"]])
    print_test_result(name, result)

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

    subprocess.run(["launchctl", "unload", str(plist_path)], capture_output=True)
    proc = subprocess.run(["launchctl", "load", str(plist_path)], capture_output=True)
    if proc.returncode == 0:
        print("  Launchd sync job installed.")
    else:
        print(f"  Could not load plist. Load manually: launchctl load \"{plist_path}\"")


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


# ── Main menu ───────────────────────────────────────────────────────────

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


# ── CLI entry point ─────────────────────────────────────────────────────

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
