# share_memory Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a `share_memory` MCP tool that pushes a single memory file from one VM/project to others on-demand, with broadcast mode, conflict handling, and optional content override.

**Architecture:** All logic lives in `server.py` as a new `@mcp.tool()`. It reads `config.json` for VM/SSH/path info, resolves the source file from the local cache, then rsyncs it to each target destination immediately. Tests follow the existing mock-filesystem pattern in `test_server.py`, adding `unittest.mock.patch` for subprocess calls.

**Tech Stack:** Python 3.14, FastMCP, pytest, unittest.mock (stdlib), rsync/SSH (same key as sync.sh)

---

### Task 1: Install pytest and verify test suite runs

**Files:**
- Run: `.venv/bin/pip install pytest`

- [ ] **Step 1: Install pytest into the venv**

```bash
/Users/dav/src/claude-memory-mcp/.venv/bin/pip install pytest
```

Expected: `Successfully installed pytest-...`

- [ ] **Step 2: Run existing tests to confirm green baseline**

```bash
cd /Users/dav/src/claude-memory-mcp && .venv/bin/python -m pytest tests/test_server.py -v
```

Expected: All existing tests pass (no failures).

---

### Task 2: Add test fixtures for share_memory

**Files:**
- Modify: `tests/test_server.py` — add `share_with_config` fixture at top of file, after existing fixtures

- [ ] **Step 1: Add the fixture**

Add after the existing `populated_cache` fixture (after line 46, before the `# ── list_projects` comment):

```python
@pytest.fixture
def share_with_config(tmp_path, monkeypatch):
    """Cache + config.json wired up for share_memory tests.

    Layout:
      tmp_path/
        config.json
        local/
          -Users-dav-src-myapp/memory/
            feedback_debugging.md   ← source file
            MEMORY.md
          -Users-dav-src-otherapp/memory/
            MEMORY.md
        remote-vm/
          -Users-dav-src-myapp/memory/
            MEMORY.md
          -Users-dav-src-otherapp/memory/
            MEMORY.md
    """
    monkeypatch.setattr(server, "_cache_dir", lambda: tmp_path)
    monkeypatch.setattr(server, "CACHE_DIR", tmp_path)

    config = {
        "local_cache": str(tmp_path),
        "vms": [
            {
                "name": "local",
                "host": "localhost",
                "user": "testuser",
                "ssh_key": "~/.ssh/claude_memory_ed25519",
                "memory_paths": [
                    "~/.claude/projects/-Users-dav-src-myapp/memory",
                    "~/.claude/projects/-Users-dav-src-otherapp/memory",
                ],
            },
            {
                "name": "remote-vm",
                "host": "192.168.1.100",
                "user": "testuser",
                "ssh_key": "~/.ssh/claude_memory_ed25519",
                "memory_paths": [
                    "~/.claude/projects/-Users-dav-src-myapp/memory",
                    "~/.claude/projects/-Users-dav-src-otherapp/memory",
                ],
            },
        ],
    }
    (tmp_path / "config.json").write_text(json.dumps(config), encoding="utf-8")

    for vm in ("local", "remote-vm"):
        for proj in ("-Users-dav-src-myapp", "-Users-dav-src-otherapp"):
            mem = tmp_path / vm / proj / "memory"
            mem.mkdir(parents=True)
            (mem / "MEMORY.md").write_text(f"# {proj} index\n", encoding="utf-8")

    source = tmp_path / "local" / "-Users-dav-src-myapp" / "memory" / "feedback_debugging.md"
    source.write_text("---\nname: debugging\ntype: feedback\n---\nMeasure before fixing.\n",
                      encoding="utf-8")

    return tmp_path
```

- [ ] **Step 2: Add share_memory import at bottom of test file**

At the very bottom of `tests/test_server.py`, alongside the existing tool imports:

```python
share_memory = server.share_memory
```

- [ ] **Step 3: Run tests to confirm no regressions**

```bash
cd /Users/dav/src/claude-memory-mcp && .venv/bin/python -m pytest tests/test_server.py -v
```

Expected: All existing tests still pass.

- [ ] **Step 4: Commit**

```bash
git add tests/test_server.py
git commit -m "test: add share_with_config fixture for share_memory tests"
```

---

### Task 3: Tests for early guards and source resolution

**Files:**
- Modify: `tests/test_server.py` — add `TestShareMemory` class

- [ ] **Step 1: Write the failing tests**

Add this class after the `TestProjectMemoryResource` class (before the `# ── Helper` comment at the bottom):

```python
# ── share_memory ───────────────────────────────────────────────────────────


class TestShareMemory:
    def test_memory_md_guard(self, share_with_config):
        result = json.loads(share_memory("MEMORY.md", "myapp"))
        assert "error" in result
        assert "index file" in result["error"]

    def test_source_project_not_found(self, share_with_config):
        with patch("subprocess.run") as mock_run:
            result = json.loads(share_memory("feedback_debugging.md", "nonexistent"))
        assert "error" in result
        assert "not found" in result["error"]

    def test_source_file_not_found(self, share_with_config):
        with patch("subprocess.run") as mock_run:
            result = json.loads(share_memory("nosuchfile.md", "myapp"))
        assert "error" in result
        assert "not found" in result["error"]

    def test_content_override_used_instead_of_cached_file(self, share_with_config):
        """When content= is provided, that content is pushed (cached file ignored)."""
        pushed_content = []

        def fake_run(cmd, **kwargs):
            m = MagicMock()
            m.returncode = 0
            m.stdout = "__NOT_FOUND__\n"
            m.stderr = ""
            if cmd[0] == "rsync":
                # Capture the temp file content that rsync would push
                src = cmd[-2]  # rsync src path
                try:
                    pushed_content.append(Path(src).read_text(encoding="utf-8"))
                except OSError:
                    pass
            return m

        with patch("subprocess.run", side_effect=fake_run):
            result = json.loads(share_memory(
                "feedback_debugging.md", "myapp",
                target_vms=["remote-vm"],
                content="CUSTOM CONTENT"
            ))

        assert any(r["status"] == "pushed" for r in result)
        assert pushed_content and pushed_content[0] == "CUSTOM CONTENT"
```

- [ ] **Step 2: Add missing import at top of test file**

Add after `import pytest` at the top of `tests/test_server.py`:

```python
from pathlib import Path
from unittest.mock import MagicMock, patch
```

- [ ] **Step 3: Run tests and confirm they fail**

```bash
cd /Users/dav/src/claude-memory-mcp && .venv/bin/python -m pytest tests/test_server.py::TestShareMemory -v
```

Expected: `AttributeError: module 'server' has no attribute 'share_memory'` (or similar — tests fail because the function doesn't exist yet).

---

### Task 4: Tests for target scoping, reachability, and src==dest guard

**Files:**
- Modify: `tests/test_server.py` — extend `TestShareMemory` with more test methods

- [ ] **Step 1: Add target scoping and guard tests**

Add these methods inside the `TestShareMemory` class, after `test_content_override_used_instead_of_cached_file`:

```python
    def test_target_vms_narrows_scope(self, share_with_config):
        """Only VMs in target_vms are attempted."""
        attempted_vms = []

        def fake_run(cmd, **kwargs):
            m = MagicMock()
            m.returncode = 0
            m.stdout = "__NOT_FOUND__\n"
            m.stderr = ""
            if "192.168.1.100" in str(cmd):
                attempted_vms.append("remote-vm")
            return m

        with patch("subprocess.run", side_effect=fake_run):
            result = json.loads(share_memory(
                "feedback_debugging.md", "myapp",
                target_vms=["remote-vm"]
            ))

        vms_in_result = {r["vm"] for r in result if "vm" in r}
        assert vms_in_result == {"remote-vm"}

    def test_src_dest_same_vm_and_project_skipped(self, share_with_config):
        """Pushing a file to the same vm+project it came from is skipped with clear message."""
        with patch("subprocess.run") as mock_run:
            result = json.loads(share_memory(
                "feedback_debugging.md", "myapp",
                target_vms=["local"]
            ))

        # local/myapp is the source — targeted push back to it should be skipped
        assert len(result) == 1
        assert result[0]["status"] == "skipped"
        assert "same file" in result[0]["reason"]

    def test_broadcast_skips_src_but_pushes_others(self, share_with_config):
        """In broadcast mode, src project is skipped but other projects on same VM proceed."""
        def fake_run(cmd, **kwargs):
            m = MagicMock()
            m.returncode = 0
            m.stdout = "__NOT_FOUND__\n"
            m.stderr = ""
            return m

        with patch("subprocess.run", side_effect=fake_run):
            result = json.loads(share_memory(
                "feedback_debugging.md", "myapp",
                target_vms=["local"],
                broadcast=True
            ))

        statuses = {r.get("dest", ""): r["status"] for r in result}
        # otherapp on local should be pushed
        assert any("otherapp" in dest and status == "pushed"
                   for dest, status in statuses.items())
        # myapp on local should be skipped (src==dest)
        assert any("myapp" in dest and status == "skipped"
                   for dest, status in statuses.items())

    def test_unreachable_vm_skipped(self, share_with_config):
        """Non-localhost VM that fails nc check is recorded as skipped:unreachable."""
        def fake_run(cmd, **kwargs):
            m = MagicMock()
            m.returncode = 1 if cmd[0] == "nc" else 0
            m.stdout = ""
            m.stderr = ""
            return m

        with patch("subprocess.run", side_effect=fake_run):
            result = json.loads(share_memory(
                "feedback_debugging.md", "myapp",
                target_vms=["remote-vm"]
            ))

        assert len(result) == 1
        assert result[0]["vm"] == "remote-vm"
        assert result[0]["status"] == "skipped"
        assert result[0]["reason"] == "unreachable"

    def test_localhost_skips_nc_check(self, share_with_config):
        """localhost is attempted without nc reachability check."""
        nc_called = []

        def fake_run(cmd, **kwargs):
            m = MagicMock()
            m.returncode = 0
            m.stdout = "__NOT_FOUND__\n"
            m.stderr = ""
            if cmd[0] == "nc":
                nc_called.append(True)
            return m

        with patch("subprocess.run", side_effect=fake_run):
            share_memory("feedback_debugging.md", "myapp",
                         target_vms=["local"], broadcast=True)

        assert not nc_called

    def test_no_matching_project_on_vm_without_project(self, share_with_config, tmp_path, monkeypatch):
        """Targeted mode skips VM when no memory_path matches source_project."""
        config_no_match = {
            "local_cache": str(tmp_path),
            "vms": [
                {
                    "name": "no-myapp-vm",
                    "host": "192.168.1.200",
                    "user": "testuser",
                    "ssh_key": "~/.ssh/claude_memory_ed25519",
                    "memory_paths": [
                        "~/.claude/projects/-Users-dav-src-unrelated/memory",
                    ],
                }
            ],
        }
        (tmp_path / "config.json").write_text(json.dumps(config_no_match), encoding="utf-8")

        def fake_run(cmd, **kwargs):
            m = MagicMock()
            m.returncode = 0  # reachable
            m.stdout = ""
            m.stderr = ""
            return m

        with patch("subprocess.run", side_effect=fake_run):
            result = json.loads(share_memory("feedback_debugging.md", "myapp"))

        assert len(result) == 1
        assert result[0]["status"] == "skipped"
        assert "project not on this VM" in result[0]["reason"]
```

- [ ] **Step 2: Run tests and confirm they still fail (no implementation yet)**

```bash
cd /Users/dav/src/claude-memory-mcp && .venv/bin/python -m pytest tests/test_server.py::TestShareMemory -v 2>&1 | head -30
```

Expected: Failures due to missing `share_memory` function.

---

### Task 5: Tests for conflict handling and push

**Files:**
- Modify: `tests/test_server.py` — extend `TestShareMemory` with conflict and push tests

- [ ] **Step 1: Add conflict and push tests**

Add these methods inside `TestShareMemory`, after the project-not-found tests:

```python
    def test_file_absent_on_dest_is_pushed(self, share_with_config):
        """File that doesn't exist on destination is rsynced successfully."""
        def fake_run(cmd, **kwargs):
            m = MagicMock()
            m.returncode = 0
            m.stdout = "__NOT_FOUND__\n"
            m.stderr = ""
            return m

        with patch("subprocess.run", side_effect=fake_run):
            result = json.loads(share_memory(
                "feedback_debugging.md", "myapp",
                target_vms=["remote-vm"]
            ))

        assert any(r["status"] == "pushed" for r in result)

    def test_file_exists_overwrite_false_skips_with_content(self, share_with_config):
        """When file exists on dest and overwrite=False, skip and return existing content."""
        existing = "---\nname: old\n---\nOld content.\n"

        def fake_run(cmd, **kwargs):
            m = MagicMock()
            m.returncode = 0
            m.stdout = existing
            m.stderr = ""
            return m

        with patch("subprocess.run", side_effect=fake_run):
            result = json.loads(share_memory(
                "feedback_debugging.md", "myapp",
                target_vms=["remote-vm"]
            ))

        skipped = [r for r in result if r.get("status") == "skipped" and r.get("reason") == "exists"]
        assert len(skipped) == 1
        assert skipped[0]["existing_content"] == existing

    def test_file_exists_overwrite_true_pushes(self, share_with_config):
        """When file exists on dest and overwrite=True, rsync proceeds."""
        existing = "---\nname: old\n---\nOld content.\n"
        rsync_called = []

        def fake_run(cmd, **kwargs):
            m = MagicMock()
            m.returncode = 0
            m.stdout = existing
            m.stderr = ""
            if cmd[0] == "rsync":
                rsync_called.append(True)
            return m

        with patch("subprocess.run", side_effect=fake_run):
            result = json.loads(share_memory(
                "feedback_debugging.md", "myapp",
                target_vms=["remote-vm"],
                overwrite=True
            ))

        assert rsync_called
        assert any(r["status"] == "pushed" for r in result)

    def test_rsync_failure_recorded_as_error(self, share_with_config):
        """When rsync exits non-zero, record status=error with message."""
        def fake_run(cmd, **kwargs):
            m = MagicMock()
            if cmd[0] == "rsync":
                m.returncode = 11
                m.stdout = ""
                m.stderr = "rsync: connection unexpectedly closed"
            else:
                m.returncode = 0
                m.stdout = "__NOT_FOUND__\n"
                m.stderr = ""
            return m

        with patch("subprocess.run", side_effect=fake_run):
            result = json.loads(share_memory(
                "feedback_debugging.md", "myapp",
                target_vms=["remote-vm"]
            ))

        errors = [r for r in result if r.get("status") == "error"]
        assert len(errors) == 1
        assert "rsync" in errors[0]["error"]

    def test_result_shape(self, share_with_config):
        """Each result entry has required fields."""
        def fake_run(cmd, **kwargs):
            m = MagicMock()
            m.returncode = 0
            m.stdout = "__NOT_FOUND__\n"
            m.stderr = ""
            return m

        with patch("subprocess.run", side_effect=fake_run):
            result = json.loads(share_memory(
                "feedback_debugging.md", "myapp",
                target_vms=["remote-vm"]
            ))

        assert len(result) > 0
        for entry in result:
            assert "vm" in entry
            assert "status" in entry
            pushed = [r for r in result if r["status"] == "pushed"]
            for r in pushed:
                assert "project" in r
                assert "dest" in r
```

- [ ] **Step 2: Run all TestShareMemory tests — confirm they all fail**

```bash
cd /Users/dav/src/claude-memory-mcp && .venv/bin/python -m pytest tests/test_server.py::TestShareMemory -v 2>&1 | tail -20
```

Expected: All `TestShareMemory` tests fail with `AttributeError: module 'server' has no attribute 'share_memory'`.

- [ ] **Step 3: Commit the tests**

```bash
git add tests/test_server.py
git commit -m "test: add TestShareMemory tests (all failing — no implementation yet)"
```

---

### Task 6: Implement share_memory

**Files:**
- Modify: `server.py` — add `share_memory` tool after `memory_sync_health`

- [ ] **Step 1: Add required imports at top of server.py**

After the existing imports, add:

```python
import tempfile
```

(The other imports — `json`, `subprocess`, `Path` — are already present.)

- [ ] **Step 2: Add the share_memory tool**

Add this function after `memory_sync_health` (before the `@mcp.resource` decorators):

```python
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

    def _ssh_opts(vm_config: dict) -> list[str]:
        key = str(Path(vm_config["ssh_key"]).expanduser())
        return [
            "-i", key,
            "-o", "ConnectTimeout=5",
            "-o", "StrictHostKeyChecking=accept-new",
            "-o", "BatchMode=yes",
        ]

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

            # Reachability check (non-localhost only)
            if not is_local:
                nc = subprocess.run(
                    ["nc", "-z", "-w2", host, "22"],
                    capture_output=True,
                )
                if nc.returncode != 0:
                    results.append({"vm": vm_name, "status": "skipped", "reason": "unreachable"})
                    continue

            memory_paths = vm_config.get("memory_paths", [])

            # Targeted vs broadcast
            if broadcast:
                targets = memory_paths
            else:
                targets = [
                    mp for mp in memory_paths
                    if _proj_name_from_path(mp).endswith(source_project)
                    or _proj_name_from_path(mp) == source_project
                ]
                if not targets:
                    results.append({
                        "vm": vm_name,
                        "status": "skipped",
                        "reason": "project not on this VM",
                    })
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

                # Check existence
                if is_local:
                    local_path = Path(mem_path.replace("~", str(Path.home()))) / file
                    file_exists = local_path.exists()
                    existing_content = (
                        local_path.read_text(encoding="utf-8") if file_exists else None
                    )
                else:
                    check = subprocess.run(
                        ["ssh"] + _ssh_opts(vm_config)
                        + [f"{user}@{host}",
                           f"test -f {mem_path}/{file} && cat {mem_path}/{file} "
                           f"|| echo __NOT_FOUND__"],
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
                    local_dest = Path(mem_path.replace("~", str(Path.home()))) / file
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
    finally:
        Path(tmp_file).unlink(missing_ok=True)

    return json.dumps(results, indent=2)


def _proj_name_from_path(mem_path: str) -> str:
    """Extract the project name from a memory_path config entry.

    '~/.claude/projects/-Users-dav-src-myapp/memory' -> 'Users-dav-src-myapp'
    """
    return Path(mem_path).parent.name.lstrip("-")
```

- [ ] **Step 3: Run the TestShareMemory tests**

```bash
cd /Users/dav/src/claude-memory-mcp && .venv/bin/python -m pytest tests/test_server.py::TestShareMemory -v
```

Expected: Most tests pass. Note any failures and fix them before moving on.

- [ ] **Step 4: Run the full test suite**

```bash
cd /Users/dav/src/claude-memory-mcp && .venv/bin/python -m pytest tests/test_server.py -v
```

Expected: All tests pass, no regressions in existing tests.

- [ ] **Step 5: Commit**

```bash
git add server.py tests/test_server.py
git commit -m "feat: add share_memory MCP tool for on-demand memory file distribution"
```
