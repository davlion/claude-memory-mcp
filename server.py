"""MCP server exposing Claude Code memory files synced from VMs."""

import json
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("claude-memory")

CACHE_DIR = Path.home() / ".claude-memories"


def _cache_dir() -> Path:
    """Return cache directory, respecting config.json if present."""
    config = CACHE_DIR / "config.json"
    if config.exists():
        try:
            data = json.loads(config.read_text(encoding="utf-8"))
            if "local_cache" in data:
                return Path(data["local_cache"]).expanduser()
        except json.JSONDecodeError:
            pass
    return CACHE_DIR


def _iter_projects(cache: Path):
    """Yield (vm_name, project_dir, project_name) for every project in cache."""
    for vm_dir in sorted(cache.iterdir()):
        if not vm_dir.is_dir() or vm_dir.name.startswith(".") or vm_dir.name.endswith(".json"):
            continue
        for proj_dir in sorted(vm_dir.iterdir()):
            if proj_dir.is_dir():
                name = proj_dir.name.lstrip("-")
                yield vm_dir.name, proj_dir, name


def _short_name(name: str) -> str:
    """Return a human-friendly project name by stripping leading path components.

    'Users-dav-src-bakers-game-annotator' -> 'bakers-game-annotator'
    'Volumes-My-Shared-Files-underwater-pickleball' -> 'underwater-pickleball'
    """
    parts = name.split("-")
    # Skip the root prefix (Users/Volumes/home) and the next component (username/volume)
    for prefix in ("Users", "Volumes", "home"):
        if parts and parts[0] == prefix:
            parts = parts[2:]  # drop prefix + username/volume
            break
    # Skip optional intermediate directory (src, alpha, work, projects, code)
    if parts and parts[0] in ("src", "alpha", "work", "projects", "code"):
        parts = parts[1:]
    return "-".join(parts) if parts else name


def _find_project(cache: Path, query: str):
    """Return (vm, proj_dir, proj_name) for query, using exact then suffix match."""
    exact = suffix = None
    for vm, proj_dir, proj_name in _iter_projects(cache):
        if proj_name == query:
            exact = (vm, proj_dir, proj_name)
            break
        if proj_name.endswith(query) and suffix is None:
            suffix = (vm, proj_dir, proj_name)
    return exact or suffix


def _read_sync_data(cache: Path) -> dict:
    """Read last-sync.json, returning {} on any error."""
    path = cache / "last-sync.json"
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass
    return {}


def _read_pending_shares(cache: Path) -> list:
    """Read pending-shares.json, returning [] on missing or corrupt."""
    path = cache / "pending-shares.json"
    if not path.exists():
        return []
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []


def _write_pending_shares(cache: Path, entries: list) -> None:
    """Write pending-shares.json, or delete it if entries is empty."""
    path = cache / "pending-shares.json"
    if not entries:
        path.unlink(missing_ok=True)
    else:
        path.write_text(json.dumps(entries, indent=2) + "\n", encoding="utf-8")


def _process_pending_shares(cache: Path, config: dict) -> list:
    """Process pending-shares queue: push entries for now-reachable VMs.

    Returns list of result dicts (one per entry attempted).
    Removes successfully pushed entries from the queue.
    """
    entries = _read_pending_shares(cache)
    if not entries:
        return []

    all_vms = {vm["name"]: vm for vm in config.get("vms", [])}
    results = []
    remaining = []

    with tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False,
                                     encoding="utf-8") as tf:
        tmp_file = tf.name

    try:
        for entry in entries:
            vm_name = entry["target_vm"]
            mem_path = entry["memory_path"]
            file = entry["file"]
            content = entry["content"]
            overwrite = entry.get("overwrite", False)

            vm_config = all_vms.get(vm_name)
            if vm_config is None:
                # VM removed from config — discard entry
                results.append({
                    "target_vm": vm_name, "memory_path": mem_path, "file": file,
                    "status": "discarded", "reason": "VM no longer in config",
                })
                continue

            host = vm_config["host"]
            user = vm_config["user"]

            # Reachability check
            try:
                nc = subprocess.run(
                    ["nc", "-z", "-w2", host, "22"],
                    capture_output=True,
                )
                reachable = nc.returncode == 0
            except subprocess.TimeoutExpired:
                reachable = False

            if not reachable:
                remaining.append(entry)
                results.append({
                    "target_vm": vm_name, "memory_path": mem_path, "file": file,
                    "status": "still_unreachable",
                })
                continue

            # Write content to temp file
            Path(tmp_file).write_text(content, encoding="utf-8")

            dest_file = f"{mem_path.rstrip('/')}/{file}"
            remote_dest = dest_file.replace("~", "$HOME")

            # Existence check
            try:
                check = subprocess.run(
                    ["ssh"] + _ssh_opts(vm_config)
                    + [f"{user}@{host}",
                       f'test -f "{remote_dest}" && cat "{remote_dest}" '
                       f'|| echo __NOT_FOUND__'],
                    capture_output=True, text=True, timeout=10,
                )
                file_exists = "__NOT_FOUND__" not in check.stdout
            except subprocess.TimeoutExpired:
                remaining.append(entry)
                results.append({
                    "target_vm": vm_name, "memory_path": mem_path, "file": file,
                    "status": "error", "error": "timed out during existence check",
                })
                continue

            if file_exists and not overwrite:
                remaining.append(entry)
                results.append({
                    "target_vm": vm_name, "memory_path": mem_path, "file": file,
                    "status": "skipped", "reason": "exists (overwrite=False)",
                })
                continue

            # Push
            ssh_e = "ssh " + " ".join(_ssh_opts(vm_config))
            rsync_cmd = [
                "rsync", "-az", "--timeout=5",
                "-e", ssh_e,
                tmp_file,
                f"{user}@{host}:{dest_file}",
            ]
            try:
                proc = subprocess.run(rsync_cmd, capture_output=True, text=True, timeout=30)
            except subprocess.TimeoutExpired:
                remaining.append(entry)
                results.append({
                    "target_vm": vm_name, "memory_path": mem_path, "file": file,
                    "status": "error", "error": "timed out during rsync",
                })
                continue

            if proc.returncode == 0:
                results.append({
                    "target_vm": vm_name, "memory_path": mem_path, "file": file,
                    "status": "pushed",
                })
            else:
                remaining.append(entry)
                results.append({
                    "target_vm": vm_name, "memory_path": mem_path, "file": file,
                    "status": "error", "error": (proc.stdout + proc.stderr).strip(),
                })
    finally:
        Path(tmp_file).unlink(missing_ok=True)

    _write_pending_shares(cache, remaining)
    return results


def _proj_name_from_path(mem_path: str) -> str:
    """Extract the project name from a memory_path config entry.

    '~/.claude/projects/-Users-dav-src-myapp/memory' -> 'Users-dav-src-myapp'
    """
    return Path(mem_path).parent.name.lstrip("-")


def _ssh_opts(vm_config: dict) -> list[str]:
    """Return SSH options list for rsync/ssh subprocess calls."""
    key = str(Path(vm_config["ssh_key"]).expanduser())
    return [
        "-i", key,
        "-o", "ConnectTimeout=5",
        "-o", "StrictHostKeyChecking=accept-new",
        "-o", "BatchMode=yes",
    ]


def _parse_frontmatter(content: str) -> dict:
    """Extract key/value pairs from YAML frontmatter (between --- delimiters)."""
    lines = content.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}
    fields = {}
    for line in lines[1:]:
        if line.strip() == "---":
            break
        if ":" in line:
            key, _, value = line.partition(":")
            fields[key.strip()] = value.strip()
    return fields


def _memory_index_line(file: str, content: str) -> str:
    """Build a MEMORY.md entry line from a file's frontmatter content."""
    meta = _parse_frontmatter(content)
    name = meta.get("name") or file.removesuffix(".md")
    description = meta.get("description", "")
    if description:
        return f"- [{name}]({file}) — {description}"
    return f"- [{name}]({file})"


@mcp.tool()
def list_projects() -> str:
    """List all known projects across all VMs with last-sync time and memory count."""
    cache = _cache_dir()
    if not cache.exists():
        return json.dumps([])
    sync_data = _read_sync_data(cache)
    results = []
    for vm, proj_dir, proj_name in _iter_projects(cache):
        mem_dir = proj_dir / "memory"
        count = len(list(mem_dir.glob("*.md"))) if mem_dir.is_dir() else 0
        last_sync = sync_data.get(vm, {}).get("last_sync", "unknown")
        results.append({
            "vm": vm,
            "project": _short_name(proj_name),
            "last_sync": last_sync,
            "memory_count": count,
        })
    return json.dumps(results, indent=2)


@mcp.tool()
def read_memories(project: str) -> str:
    """Read MEMORY.md index and all memory files for a project."""
    cache = _cache_dir()
    if not cache.exists():
        return json.dumps({"error": "Cache directory not found"})
    match = _find_project(cache, project)
    if not match:
        return json.dumps({"error": f"Project '{project}' not found"})
    vm, proj_dir, proj_name = match
    mem_dir = proj_dir / "memory"
    if not mem_dir.is_dir():
        return json.dumps({"project": proj_name, "vm": vm, "index": "", "memories": []})
    index_path = mem_dir / "MEMORY.md"
    index = index_path.read_text(encoding="utf-8") if index_path.exists() else ""
    memories = []
    for f in sorted(mem_dir.glob("*.md")):
        if f.name == "MEMORY.md":
            continue
        try:
            memories.append({"file": f.name, "content": f.read_text(encoding="utf-8")})
        except OSError:
            memories.append({"file": f.name, "content": "[read error]"})
    return json.dumps({"project": proj_name, "vm": vm, "index": index, "memories": memories}, indent=2)


@mcp.tool()
def search_memories(query: str) -> str:
    """Full-text case-insensitive search across all memory files from all projects."""
    cache = _cache_dir()
    if not cache.exists():
        return json.dumps([])
    q = query.lower()
    results = []
    for vm, proj_dir, proj_name in _iter_projects(cache):
        mem_dir = proj_dir / "memory"
        if not mem_dir.is_dir():
            continue
        for f in sorted(mem_dir.glob("*.md")):
            try:
                content = f.read_text(encoding="utf-8")
            except OSError:
                continue
            if q in content.lower():
                # Extract a context window around the match
                idx = content.lower().index(q)
                start = max(0, idx - 80)
                end = min(len(content), idx + len(query) + 80)
                match_ctx = content[start:end].replace("\n", " ")
                if start > 0:
                    match_ctx = "..." + match_ctx
                if end < len(content):
                    match_ctx = match_ctx + "..."
                results.append({
                    "vm": vm,
                    "project": proj_name,
                    "file": f.name,
                    "match": match_ctx,
                })
    return json.dumps(results, indent=2)


@mcp.tool()
def sync_status() -> str:
    """Show which VMs are reachable and when each was last synced."""
    cache = _cache_dir()
    sync_data = _read_sync_data(cache)
    results = []
    for vm, info in sorted(sync_data.items()):
        results.append({
            "vm": vm,
            "last_sync": info.get("last_sync", "unknown"),
            "reachable": info.get("success", False),
        })
    return json.dumps(results, indent=2)


@mcp.tool()
def sync_now() -> str:
    """Trigger an immediate memory sync from all VMs."""
    sync_sh = Path(__file__).parent / "sync.sh"
    if not sync_sh.exists():
        return json.dumps({"error": f"sync.sh not found at {sync_sh}"})
    try:
        proc = subprocess.run(
            ["/bin/bash", str(sync_sh)],
            capture_output=True, text=True, timeout=60
        )
        cache = _cache_dir()
        config_path = cache / "config.json"
        try:
            config = json.loads(config_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            config = {}

        pending_results = _process_pending_shares(cache, config)

        return json.dumps({
            "success": proc.returncode == 0,
            "output": (proc.stdout + proc.stderr).strip() or "(no output)",
            "pending_shares": pending_results,
        })
    except subprocess.TimeoutExpired:
        return json.dumps({"error": "sync timed out after 60s"})
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp.tool()
def memory_sync_health() -> str:
    """Check whether the memory sync job is healthy: launchd status, per-VM sync age, and recent log errors."""
    cache = _cache_dir()
    result = {}

    # 1. launchd job status
    try:
        proc = subprocess.run(
            ["launchctl", "list"],
            capture_output=True, text=True, timeout=5
        )
        job_line = next(
            (l for l in proc.stdout.splitlines() if "com.claude.memory-sync" in l),
            None
        )
        if job_line:
            parts = job_line.split()
            result["launchd"] = {
                "loaded": True,
                "pid": parts[0] if parts[0] != "-" else None,
                "last_exit_code": int(parts[1]) if len(parts) > 1 else None,
            }
        else:
            result["launchd"] = {"loaded": False}
    except Exception as e:
        result["launchd"] = {"error": str(e)}

    # 2. Per-VM sync status + staleness
    sync_data = _read_sync_data(cache)
    now = datetime.now(timezone.utc)
    vms = []
    for vm, info in sorted(sync_data.items()):
        last_sync = info.get("last_sync", "")
        age_minutes = None
        try:
            ts = datetime.fromisoformat(last_sync).replace(tzinfo=timezone.utc)
            age_minutes = round((now - ts).total_seconds() / 60, 1)
        except ValueError:
            pass
        vms.append({
            "vm": vm,
            "last_sync": last_sync,
            "age_minutes": age_minutes,
            "success": info.get("success", False),
            "stale": age_minutes is not None and age_minutes > 90,
        })
    result["vms"] = vms

    # 3. Recent log — last 20 lines, flag any ERROR lines
    log_path = cache / "sync.log"
    if log_path.exists():
        lines = log_path.read_text(encoding="utf-8").splitlines()
        recent = lines[-20:]
        result["recent_log"] = recent
        result["errors"] = [l for l in recent if "ERROR" in l]
    else:
        result["recent_log"] = []
        result["errors"] = []
        result["log_missing"] = True

    return json.dumps(result, indent=2)


@mcp.tool()
def share_memory(
    file: str,
    source_project: str,
    broadcast: bool = False,
    target_vms: list[str] | None = None,
    content: str | None = None,
    overwrite: bool = False,
) -> str:
    """Push a memory file from one project to other VMs and/or projects on-demand.

    Args:
        file: Memory filename to push, e.g. 'feedback_debugging.md'. Cannot be 'MEMORY.md'.
        source_project: Short project name (fuzzy-matched) identifying the source in cache.
        broadcast: False = push to matching project only; True = push to all projects on each VM.
        target_vms: VM names to target; defaults to all configured VMs.
        content: If provided, push this content instead of the cached file.
        overwrite: If False, skip destinations where file already exists (and report content).
    """
    if file == "MEMORY.md":
        return json.dumps({"error": "MEMORY.md is the index file and cannot be shared directly"})

    # Read config for VM list, SSH keys, memory paths
    config_path = CACHE_DIR / "config.json"
    try:
        config = json.loads(config_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        return json.dumps({"error": f"Cannot read config: {e}"})

    all_vms = {vm["name"]: vm for vm in config.get("vms", [])}

    # Resolve source
    cache = _cache_dir()
    source_match = _find_project(cache, source_project)

    if content is not None:
        source_content = content
        source_vm_name = source_match[0] if source_match else None
        source_proj_dir = source_match[1] if source_match else None
    else:
        if source_match is None:
            return json.dumps({"error": f"Project '{source_project}' not found in cache"})
        source_vm_name, source_proj_dir, _ = source_match
        source_file = source_proj_dir / "memory" / file
        if not source_file.exists():
            return json.dumps({"error": f"File '{file}' not found in project '{source_project}'"})
        source_content = source_file.read_text(encoding="utf-8")

    # Determine scope
    if target_vms is not None:
        scope = [n for n in target_vms if n in all_vms]
    else:
        scope = list(all_vms.keys())

    results = []

    with tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False, encoding="utf-8") as tf:
        tf.write(source_content)
        tmp_file = tf.name

    try:
        for vm_name in scope:
            vm_config = all_vms[vm_name]
            host = vm_config["host"]
            user = vm_config["user"]
            is_local = host in ("localhost", "127.0.0.1")

            # Calculate targets (needed whether reachable or not, for queueing)
            memory_paths = vm_config.get("memory_paths", [])
            if broadcast:
                targets = memory_paths
            else:
                exact = [mp for mp in memory_paths if _proj_name_from_path(mp) == source_project]
                suffix = [mp for mp in memory_paths if _proj_name_from_path(mp).endswith(source_project)]
                targets = exact if exact else suffix
                if not targets:
                    results.append({
                        "vm": vm_name,
                        "status": "skipped",
                        "reason": "project not on this VM",
                    })
                    continue

            # Reachability check (non-localhost only)
            if not is_local:
                try:
                    nc = subprocess.run(
                        ["nc", "-z", "-w2", host, "22"],
                        capture_output=True,
                    )
                    reachable = nc.returncode == 0
                except subprocess.TimeoutExpired:
                    reachable = False

                if not reachable:
                    # Queue each target path for retry on next sync
                    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
                    pending = _read_pending_shares(cache)
                    for mem_path in targets:
                        pending.append({
                            "queued_at": ts,
                            "file": file,
                            "content": source_content,
                            "target_vm": vm_name,
                            "memory_path": mem_path,
                            "overwrite": overwrite,
                        })
                        results.append({
                            "vm": vm_name,
                            "project": Path(mem_path).parent.name.lstrip("-"),
                            "dest": f"{mem_path.rstrip('/')}/{file}",
                            "status": "queued",
                            "reason": "unreachable — added to pending-shares queue",
                        })
                    _write_pending_shares(cache, pending)
                    continue

            for mem_path in targets:
                proj_encoded = Path(mem_path).parent.name  # e.g. -Users-dav-src-myapp
                proj_display = proj_encoded.lstrip("-")
                dest_file = f"{mem_path.rstrip('/')}/{file}"

                # src == dest guard
                if (source_vm_name is not None
                        and source_proj_dir is not None
                        and vm_name == source_vm_name
                        and proj_encoded == source_proj_dir.name):
                    results.append({
                        "vm": vm_name,
                        "project": proj_display,
                        "dest": dest_file,
                        "status": "skipped",
                        "reason": "source and destination are the same file",
                    })
                    continue

                try:
                    # Check existence
                    if is_local:
                        local_path = Path(mem_path).expanduser() / file
                        file_exists = local_path.exists()
                        existing_content = (
                            local_path.read_text(encoding="utf-8") if file_exists else None
                        )
                    else:
                        remote_dest = f"{mem_path}/{file}".replace("~", "$HOME")
                        check = subprocess.run(
                            ["ssh"] + _ssh_opts(vm_config)
                            + [f"{user}@{host}",
                               f'test -f "{remote_dest}" && cat "{remote_dest}" '
                               f'|| echo __NOT_FOUND__'],
                            capture_output=True, text=True, timeout=10,
                        )
                        if "__NOT_FOUND__" in check.stdout:
                            file_exists = False
                            existing_content = None
                        else:
                            file_exists = True
                            existing_content = check.stdout

                    if file_exists and not overwrite:
                        results.append({
                            "vm": vm_name,
                            "project": proj_display,
                            "dest": dest_file,
                            "status": "skipped",
                            "reason": "exists",
                            "existing_content": existing_content,
                        })
                        continue

                    # Push
                    if is_local:
                        local_dest = Path(mem_path).expanduser() / file
                        rsync_cmd = ["rsync", "-az", "--timeout=5", tmp_file, str(local_dest)]
                    else:
                        ssh_e = "ssh " + " ".join(_ssh_opts(vm_config))
                        rsync_cmd = [
                            "rsync", "-az", "--timeout=5",
                            "-e", ssh_e,
                            tmp_file,
                            f"{user}@{host}:{mem_path}/{file}",
                        ]

                    proc = subprocess.run(rsync_cmd, capture_output=True, text=True, timeout=5)
                    if proc.returncode == 0:
                        results.append({
                            "vm": vm_name,
                            "project": proj_display,
                            "dest": dest_file,
                            "status": "pushed",
                        })
                    else:
                        results.append({
                            "vm": vm_name,
                            "project": proj_display,
                            "dest": dest_file,
                            "status": "error",
                            "error": (proc.stdout + proc.stderr).strip(),
                        })

                except subprocess.TimeoutExpired:
                    results.append({
                        "vm": vm_name,
                        "project": proj_display,
                        "dest": dest_file,
                        "status": "error",
                        "error": "timed out",
                    })
    finally:
        Path(tmp_file).unlink(missing_ok=True)

    return json.dumps(results, indent=2)


@mcp.resource("memory://index")
def all_projects_index() -> str:
    """Summary stubs for all synced projects — one MEMORY.md index per project.

    Exposed as an MCP resource so clients (e.g. Claude Desktop) can embed memory
    context directly into conversations without an explicit tool call.
    """
    cache = _cache_dir()
    if not cache.exists():
        return "No memory cache found. Use the sync_now tool to sync from VMs."
    sync_data = _read_sync_data(cache)
    sections = []
    for vm, proj_dir, proj_name in _iter_projects(cache):
        mem_dir = proj_dir / "memory"
        index_path = mem_dir / "MEMORY.md"
        last_sync = sync_data.get(vm, {}).get("last_sync", "unknown")
        non_index = [f for f in mem_dir.glob("*.md") if f.name != "MEMORY.md"] if mem_dir.is_dir() else []
        header = f"## {proj_name}  (VM: {vm} · synced: {last_sync} · {len(non_index)} memory files)"
        if index_path.exists():
            try:
                body = index_path.read_text(encoding="utf-8").strip()
            except OSError:
                body = "(index unreadable)"
        else:
            body = "(no MEMORY.md index)"
        sections.append(f"{header}\n\n{body}")
    return "\n\n---\n\n".join(sections) if sections else "No projects synced yet."


@mcp.resource("memory://project/{name}")
def project_memory_resource(name: str) -> str:
    """Full memory content for a named project (MEMORY.md index + all memory files).

    URI example: memory://project/myapp
    """
    cache = _cache_dir()
    if not cache.exists():
        return f"Cache not found — project '{name}' unavailable."
    match = _find_project(cache, name)
    if not match:
        return f"Project '{name}' not found in cache."
    _, proj_dir, proj_name = match
    mem_dir = proj_dir / "memory"
    if not mem_dir.is_dir():
        return f"No memory directory for project '{proj_name}'."
    parts = []
    for f in sorted(mem_dir.glob("*.md")):
        try:
            parts.append(f"### {f.name}\n\n{f.read_text(encoding='utf-8').strip()}")
        except OSError:
            parts.append(f"### {f.name}\n\n(read error)")
    return "\n\n---\n\n".join(parts) if parts else f"No memory files for '{proj_name}'."


@mcp.prompt()
def load_memories(project: str) -> str:
    """Load all memory files for a specific project into the conversation context."""
    return project_memory_resource(project)


if __name__ == "__main__":
    mcp.run()
