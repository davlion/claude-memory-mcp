"""MCP server exposing Claude Code memory files synced from VMs."""

import json
import subprocess
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


def _read_sync_data(cache: Path) -> dict:
    """Read last-sync.json, returning {} on any error."""
    path = cache / "last-sync.json"
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass
    return {}


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
            "project": proj_name,
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
    for vm, proj_dir, proj_name in _iter_projects(cache):
        if proj_name == project:
            mem_dir = proj_dir / "memory"
            if not mem_dir.is_dir():
                return json.dumps({"project": project, "vm": vm, "index": "", "memories": []})
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
            return json.dumps({"project": project, "vm": vm, "index": index, "memories": memories}, indent=2)
    return json.dumps({"error": f"Project '{project}' not found"})


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
            "stale": age_minutes is not None and age_minutes > 15,
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


if __name__ == "__main__":
    mcp.run()
