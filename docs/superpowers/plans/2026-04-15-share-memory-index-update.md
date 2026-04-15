# MEMORY.md Index Update on share_memory Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** When `share_memory` successfully pushes a file, append an entry to the target's MEMORY.md so the shared file becomes visible to Claude on that machine.

**Architecture:** Three new module-level helpers (`_parse_frontmatter`, `_memory_index_line`, `_update_memory_index`) added to `server.py` after `_ssh_opts`. `share_memory` and `_process_pending_shares` each call `_update_memory_index` after a successful file push and add a `memory_index` field to the result entry.

**Tech Stack:** Python 3.14, subprocess/rsync/SSH (same as existing), pytest + unittest.mock

---

## File Structure

- Modify: `server.py` — add 3 helpers, wire into `share_memory` and `_process_pending_shares`
- Modify: `tests/test_server.py` — add tests for new helpers and wired-in behavior

Key locations in `server.py`:
- Helpers go after `_ssh_opts` (line ~241)
- Wire-in for `share_memory`: line ~622 (`if proc.returncode == 0:` in the file push block)
- Wire-in for `_process_pending_shares`: line ~207 (`if proc.returncode == 0:` in queue retry)

---

### Task 1: _parse_frontmatter and _memory_index_line helpers

**Files:**
- Modify: `server.py` — add two helpers after `_ssh_opts`
- Modify: `tests/test_server.py` — add `TestParseFrontmatter` and `TestMemoryIndexLine` classes

- [ ] **Step 1: Write the failing tests**

Add these two classes to `tests/test_server.py`, just before `class TestListProjects`:

```python
# ── _parse_frontmatter ─────────────────────────────────────────────────────


class TestParseFrontmatter:

    def test_full_frontmatter(self):
        content = "---\nname: Debugging\ndescription: Measure before fixing\ntype: feedback\n---\nBody.\n"
        result = server._parse_frontmatter(content)
        assert result["name"] == "Debugging"
        assert result["description"] == "Measure before fixing"
        assert result["type"] == "feedback"

    def test_missing_description(self):
        content = "---\nname: Debugging\ntype: feedback\n---\nBody.\n"
        result = server._parse_frontmatter(content)
        assert result["name"] == "Debugging"
        assert "description" not in result

    def test_missing_name(self):
        content = "---\ndescription: Measure before fixing\n---\nBody.\n"
        result = server._parse_frontmatter(content)
        assert result["description"] == "Measure before fixing"
        assert "name" not in result

    def test_no_frontmatter(self):
        content = "Just some markdown without frontmatter.\n"
        assert server._parse_frontmatter(content) == {}

    def test_empty_content(self):
        assert server._parse_frontmatter("") == {}


# ── _memory_index_line ─────────────────────────────────────────────────────


class TestMemoryIndexLine:

    def test_full_frontmatter(self):
        content = "---\nname: Debugging discipline\ndescription: Measure before fixing\n---\nBody.\n"
        line = server._memory_index_line("feedback_debugging.md", content)
        assert line == "- [Debugging discipline](feedback_debugging.md) — Measure before fixing"

    def test_missing_description(self):
        content = "---\nname: Debugging discipline\n---\nBody.\n"
        line = server._memory_index_line("feedback_debugging.md", content)
        assert line == "- [Debugging discipline](feedback_debugging.md)"

    def test_missing_name_uses_stem(self):
        content = "---\ndescription: Measure before fixing\n---\nBody.\n"
        line = server._memory_index_line("feedback_debugging.md", content)
        assert line == "- [feedback_debugging](feedback_debugging.md) — Measure before fixing"

    def test_no_frontmatter_uses_stem(self):
        content = "Just markdown.\n"
        line = server._memory_index_line("feedback_debugging.md", content)
        assert line == "- [feedback_debugging](feedback_debugging.md)"
```

- [ ] **Step 2: Run tests and confirm they fail**

```bash
cd /Users/dav/src/claude-memory-mcp && .venv/bin/python -m pytest tests/test_server.py::TestParseFrontmatter tests/test_server.py::TestMemoryIndexLine -v 2>&1 | tail -15
```

Expected: `AttributeError: module 'server' has no attribute '_parse_frontmatter'`

- [ ] **Step 3: Add helpers to server.py**

Add after `_ssh_opts` (after line 241, before the `@mcp.tool()` decorator for `list_projects`):

```python
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
```

- [ ] **Step 4: Run tests and confirm they pass**

```bash
cd /Users/dav/src/claude-memory-mcp && .venv/bin/python -m pytest tests/test_server.py::TestParseFrontmatter tests/test_server.py::TestMemoryIndexLine -v 2>&1 | tail -15
```

Expected: 9 PASSED

- [ ] **Step 5: Confirm full suite still passes**

```bash
cd /Users/dav/src/claude-memory-mcp && .venv/bin/python -m pytest tests/test_server.py -v 2>&1 | tail -5
```

Expected: 60 passed

- [ ] **Step 6: Commit**

```bash
git add server.py tests/test_server.py
git commit -m "feat: add _parse_frontmatter and _memory_index_line helpers"
```

---

### Task 2: _update_memory_index helper

**Files:**
- Modify: `server.py` — add `_update_memory_index` after `_memory_index_line`
- Modify: `tests/test_server.py` — add `TestUpdateMemoryIndex` class

- [ ] **Step 1: Write the failing tests**

Add this class to `tests/test_server.py` after `TestMemoryIndexLine`:

```python
# ── _update_memory_index ───────────────────────────────────────────────────


class TestUpdateMemoryIndex:

    VM_CONFIG = {
        "name": "remote-vm",
        "host": "192.168.1.100",
        "user": "testuser",
        "ssh_key": "~/.ssh/claude_memory_ed25519",
    }
    INDEX_LINE = "- [Debugging](feedback_debugging.md) — Measure before fixing"

    # ── localhost path ──────────────────────────────────────────────────────

    def test_localhost_appends_to_existing_index(self, tmp_path):
        """Appends entry to existing MEMORY.md when file not already listed."""
        mem_dir = tmp_path / "memory"
        mem_dir.mkdir()
        (mem_dir / "MEMORY.md").write_text("- [Other](other.md)\n", encoding="utf-8")
        # Use absolute path — expanduser() is a no-op for paths without ~
        mem_path = str(mem_dir)

        result = server._update_memory_index(
            mem_path, "feedback_debugging.md", self.INDEX_LINE,
            self.VM_CONFIG, "testuser", "localhost", is_local=True,
        )

        assert result == "updated"
        content = (mem_dir / "MEMORY.md").read_text(encoding="utf-8")
        assert self.INDEX_LINE in content

    def test_localhost_creates_missing_index(self, tmp_path):
        """Creates MEMORY.md from scratch when it doesn't exist."""
        mem_dir = tmp_path / "memory"
        mem_dir.mkdir()
        mem_path = str(mem_dir)

        result = server._update_memory_index(
            mem_path, "feedback_debugging.md", self.INDEX_LINE,
            self.VM_CONFIG, "testuser", "localhost", is_local=True,
        )

        assert result == "updated"
        content = (mem_dir / "MEMORY.md").read_text(encoding="utf-8")
        assert self.INDEX_LINE in content

    def test_localhost_already_present(self, tmp_path):
        """Returns 'already_present' when filename is already in MEMORY.md."""
        mem_dir = tmp_path / "memory"
        mem_dir.mkdir()
        (mem_dir / "MEMORY.md").write_text(
            "- [Debugging](feedback_debugging.md)\n", encoding="utf-8"
        )
        mem_path = str(mem_dir)

        result = server._update_memory_index(
            mem_path, "feedback_debugging.md", self.INDEX_LINE,
            self.VM_CONFIG, "testuser", "localhost", is_local=True,
        )

        assert result == "already_present"

    # ── remote path ─────────────────────────────────────────────────────────

    def test_remote_appends_when_not_present(self):
        """Reads remote MEMORY.md via SSH, appends entry, pushes via rsync."""
        rsync_called = []

        def fake_run(cmd, **kwargs):
            m = MagicMock()
            m.returncode = 0
            if cmd[0] == "ssh":
                m.stdout = "- [Other](other.md)\n"
            else:
                m.stdout = ""
                rsync_called.append(True)
            m.stderr = ""
            return m

        with patch("subprocess.run", side_effect=fake_run):
            result = server._update_memory_index(
                "~/.claude/projects/-Users-dav-src-myapp/memory",
                "feedback_debugging.md", self.INDEX_LINE,
                self.VM_CONFIG, "testuser", "192.168.1.100", is_local=False,
            )

        assert result == "updated"
        assert rsync_called

    def test_remote_missing_index_creates_it(self):
        """Creates MEMORY.md on remote when SSH returns __NOT_FOUND__."""
        rsync_called = []

        def fake_run(cmd, **kwargs):
            m = MagicMock()
            m.returncode = 0
            if cmd[0] == "ssh":
                m.stdout = "__NOT_FOUND__\n"
            else:
                m.stdout = ""
                rsync_called.append(True)
            m.stderr = ""
            return m

        with patch("subprocess.run", side_effect=fake_run):
            result = server._update_memory_index(
                "~/.claude/projects/-Users-dav-src-myapp/memory",
                "feedback_debugging.md", self.INDEX_LINE,
                self.VM_CONFIG, "testuser", "192.168.1.100", is_local=False,
            )

        assert result == "updated"
        assert rsync_called

    def test_remote_already_present(self):
        """Returns 'already_present' when filename found in remote MEMORY.md."""
        def fake_run(cmd, **kwargs):
            m = MagicMock()
            m.returncode = 0
            m.stdout = "- [Debugging](feedback_debugging.md)\n"
            m.stderr = ""
            return m

        with patch("subprocess.run", side_effect=fake_run):
            result = server._update_memory_index(
                "~/.claude/projects/-Users-dav-src-myapp/memory",
                "feedback_debugging.md", self.INDEX_LINE,
                self.VM_CONFIG, "testuser", "192.168.1.100", is_local=False,
            )

        assert result == "already_present"

    def test_remote_ssh_timeout_returns_error(self):
        """SSH timeout reading MEMORY.md returns error string."""
        def fake_run(cmd, **kwargs):
            raise subprocess.TimeoutExpired(cmd, 10)

        with patch("subprocess.run", side_effect=fake_run):
            result = server._update_memory_index(
                "~/.claude/projects/-Users-dav-src-myapp/memory",
                "feedback_debugging.md", self.INDEX_LINE,
                self.VM_CONFIG, "testuser", "192.168.1.100", is_local=False,
            )

        assert result.startswith("error:")
        assert "timed out" in result
```

- [ ] **Step 2: Run tests and confirm they fail**

```bash
cd /Users/dav/src/claude-memory-mcp && .venv/bin/python -m pytest tests/test_server.py::TestUpdateMemoryIndex -v 2>&1 | tail -15
```

Expected: `AttributeError: module 'server' has no attribute '_update_memory_index'`

- [ ] **Step 3: Add _update_memory_index to server.py**

Add after `_memory_index_line`:

```python
def _update_memory_index(
    mem_path: str,
    file: str,
    index_line: str,
    vm_config: dict,
    user: str,
    host: str,
    is_local: bool,
) -> str:
    """Append index_line to target MEMORY.md if file is not already listed.

    Returns 'updated', 'already_present', or 'error: <reason>'.
    No locking — last writer wins; caller is responsible for avoiding races.
    """
    if is_local:
        local_index = Path(mem_path).expanduser() / "MEMORY.md"
        try:
            existing = local_index.read_text(encoding="utf-8") if local_index.exists() else ""
        except OSError as e:
            return f"error: {e}"
        if file in existing:
            return "already_present"
        try:
            local_index.write_text(existing + index_line + "\n", encoding="utf-8")
        except OSError as e:
            return f"error: {e}"
        return "updated"

    # Remote: SSH cat to read, rsync to push
    remote_index = f"{mem_path}/MEMORY.md".replace("~", "$HOME")
    try:
        check = subprocess.run(
            ["ssh"] + _ssh_opts(vm_config)
            + [f"{user}@{host}",
               f'cat "{remote_index}" 2>/dev/null || echo __NOT_FOUND__'],
            capture_output=True, text=True, timeout=10,
        )
    except subprocess.TimeoutExpired:
        return "error: timed out reading MEMORY.md"

    existing = "" if "__NOT_FOUND__" in check.stdout else check.stdout
    if file in existing:
        return "already_present"

    updated = existing + index_line + "\n"
    with tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False,
                                     encoding="utf-8") as tf:
        tf.write(updated)
        tmp_index = tf.name

    try:
        ssh_e = "ssh " + " ".join(_ssh_opts(vm_config))
        proc = subprocess.run(
            ["rsync", "-az", "--timeout=5", "-e", ssh_e,
             tmp_index, f"{user}@{host}:{mem_path}/MEMORY.md"],
            capture_output=True, text=True, timeout=10,
        )
        if proc.returncode == 0:
            return "updated"
        return f"error: {(proc.stdout + proc.stderr).strip()}"
    except subprocess.TimeoutExpired:
        return "error: timed out pushing MEMORY.md"
    finally:
        Path(tmp_index).unlink(missing_ok=True)
```

- [ ] **Step 4: Run tests and confirm they pass**

```bash
cd /Users/dav/src/claude-memory-mcp && .venv/bin/python -m pytest tests/test_server.py::TestUpdateMemoryIndex -v 2>&1 | tail -15
```

Expected: 8 PASSED

- [ ] **Step 5: Confirm full suite still passes**

```bash
cd /Users/dav/src/claude-memory-mcp && .venv/bin/python -m pytest tests/test_server.py -v 2>&1 | tail -5
```

Expected: 69 passed

- [ ] **Step 6: Commit**

```bash
git add server.py tests/test_server.py
git commit -m "feat: add _update_memory_index helper"
```

---

### Task 3: Wire _update_memory_index into share_memory

**Files:**
- Modify: `server.py` — call `_update_memory_index` after successful push in `share_memory`
- Modify: `tests/test_server.py` — add tests to `TestShareMemory`

- [ ] **Step 1: Write the failing tests**

Add these methods to `TestShareMemory` (after `test_result_shape`):

```python
    def test_pushed_result_has_memory_index_updated(self, share_with_config, tmp_path):
        """Pushed result includes memory_index: 'updated' when file not in target index."""
        # share_with_config MEMORY.md files contain '# {proj} index\n' — no feedback_debugging entry
        def fake_run(cmd, **kwargs):
            m = MagicMock()
            m.returncode = 0
            m.stdout = "__NOT_FOUND__\n" if cmd[0] == "ssh" else ""
            m.stderr = ""
            return m

        with patch("subprocess.run", side_effect=fake_run):
            result = json.loads(share_memory(
                "feedback_debugging.md", "myapp", target_vms=["remote-vm"]
            ))

        pushed = [r for r in result if r.get("status") == "pushed"]
        assert pushed, "Expected at least one pushed result"
        assert pushed[0]["memory_index"] == "updated"

    def test_pushed_result_has_memory_index_already_present(self, share_with_config, tmp_path):
        """Pushed result includes memory_index: 'already_present' when file is in target index."""
        # Put the filename in the remote-vm MEMORY.md
        remote_memory = tmp_path / "remote-vm" / "-Users-dav-src-myapp" / "memory" / "MEMORY.md"
        remote_memory.write_text(
            "- [Debugging](feedback_debugging.md)\n", encoding="utf-8"
        )

        def fake_run(cmd, **kwargs):
            m = MagicMock()
            m.returncode = 0
            # SSH existence check for the file: not found (so push proceeds)
            # SSH cat of MEMORY.md: return existing content
            if cmd[0] == "ssh":
                cmd_str = " ".join(str(c) for c in cmd)
                if "MEMORY.md" in cmd_str:
                    m.stdout = "- [Debugging](feedback_debugging.md)\n"
                else:
                    m.stdout = "__NOT_FOUND__\n"
            else:
                m.stdout = ""
            m.stderr = ""
            return m

        with patch("subprocess.run", side_effect=fake_run):
            result = json.loads(share_memory(
                "feedback_debugging.md", "myapp", target_vms=["remote-vm"]
            ))

        pushed = [r for r in result if r.get("status") == "pushed"]
        assert pushed
        assert pushed[0]["memory_index"] == "already_present"

    def test_skipped_result_has_no_memory_index(self, share_with_config):
        """Skipped results (file exists, overwrite=False) do not include memory_index."""
        existing = "---\nname: old\n---\nOld content.\n"

        def fake_run(cmd, **kwargs):
            m = MagicMock()
            m.returncode = 0
            m.stdout = existing if cmd[0] == "ssh" else ""
            m.stderr = ""
            return m

        with patch("subprocess.run", side_effect=fake_run):
            result = json.loads(share_memory(
                "feedback_debugging.md", "myapp", target_vms=["remote-vm"]
            ))

        skipped = [r for r in result if r.get("status") == "skipped"]
        assert skipped
        assert "memory_index" not in skipped[0]
```

- [ ] **Step 2: Run tests and confirm they fail**

```bash
cd /Users/dav/src/claude-memory-mcp && .venv/bin/python -m pytest tests/test_server.py::TestShareMemory::test_pushed_result_has_memory_index_updated tests/test_server.py::TestShareMemory::test_pushed_result_has_memory_index_already_present tests/test_server.py::TestShareMemory::test_skipped_result_has_no_memory_index -v 2>&1 | tail -15
```

Expected: the first two fail (no `memory_index` key in result), the third passes (already no `memory_index` on skipped results).

- [ ] **Step 3: Wire _update_memory_index into share_memory**

In `server.py`, find the successful push block in `share_memory` (after `proc = subprocess.run(rsync_cmd, ...)`, around line 622):

```python
                    proc = subprocess.run(rsync_cmd, capture_output=True, text=True, timeout=5)
                    if proc.returncode == 0:
                        results.append({
                            "vm": vm_name,
                            "project": proj_display,
                            "dest": dest_file,
                            "status": "pushed",
                        })
```

Replace with:

```python
                    proc = subprocess.run(rsync_cmd, capture_output=True, text=True, timeout=5)
                    if proc.returncode == 0:
                        index_line = _memory_index_line(file, source_content)
                        memory_index = _update_memory_index(
                            mem_path, file, index_line, vm_config, user, host, is_local
                        )
                        results.append({
                            "vm": vm_name,
                            "project": proj_display,
                            "dest": dest_file,
                            "status": "pushed",
                            "memory_index": memory_index,
                        })
```

- [ ] **Step 4: Run tests and confirm they pass**

```bash
cd /Users/dav/src/claude-memory-mcp && .venv/bin/python -m pytest tests/test_server.py::TestShareMemory::test_pushed_result_has_memory_index_updated tests/test_server.py::TestShareMemory::test_pushed_result_has_memory_index_already_present tests/test_server.py::TestShareMemory::test_skipped_result_has_no_memory_index -v 2>&1 | tail -15
```

Expected: 3 PASSED

- [ ] **Step 5: Confirm full suite still passes**

```bash
cd /Users/dav/src/claude-memory-mcp && .venv/bin/python -m pytest tests/test_server.py -v 2>&1 | tail -5
```

Expected: 72 passed

- [ ] **Step 6: Commit**

```bash
git add server.py tests/test_server.py
git commit -m "feat: update MEMORY.md index after successful share_memory push"
```

---

### Task 4: Wire _update_memory_index into _process_pending_shares

**Files:**
- Modify: `server.py` — call `_update_memory_index` after successful push in `_process_pending_shares`
- Modify: `tests/test_server.py` — add test to `TestSyncNowPendingShares`

- [ ] **Step 1: Write the failing test**

Add this method to `TestSyncNowPendingShares`:

```python
    def test_retried_push_updates_memory_index(self, share_with_config, tmp_path):
        """After queue retry push succeeds, result includes memory_index."""
        self._make_queue(tmp_path, [self._base_entry()])

        def fake_run(cmd, **kwargs):
            m = MagicMock()
            m.returncode = 0
            if cmd[0] == "ssh":
                cmd_str = " ".join(str(c) for c in cmd)
                if "MEMORY.md" in cmd_str:
                    m.stdout = "__NOT_FOUND__\n"
                else:
                    m.stdout = "__NOT_FOUND__\n"
            else:
                m.stdout = "sync complete"
            m.stderr = ""
            return m

        with patch("subprocess.run", side_effect=fake_run):
            result = json.loads(sync_now())

        pending = result.get("pending_shares", [])
        pushed = [e for e in pending if e.get("status") == "pushed"]
        assert pushed
        assert "memory_index" in pushed[0]
```

- [ ] **Step 2: Run test and confirm it fails**

```bash
cd /Users/dav/src/claude-memory-mcp && .venv/bin/python -m pytest "tests/test_server.py::TestSyncNowPendingShares::test_retried_push_updates_memory_index" -v 2>&1 | tail -10
```

Expected: FAILED — `memory_index` key not present in result.

- [ ] **Step 3: Wire _update_memory_index into _process_pending_shares**

In `server.py`, find the successful push block in `_process_pending_shares` (around line 207):

```python
            if proc.returncode == 0:
                results.append({
                    "target_vm": vm_name, "memory_path": mem_path, "file": file,
                    "status": "pushed",
                })
```

Replace with:

```python
            if proc.returncode == 0:
                is_local = host in ("localhost", "127.0.0.1")
                index_line = _memory_index_line(file, content)
                memory_index = _update_memory_index(
                    mem_path, file, index_line, vm_config, user, host, is_local
                )
                results.append({
                    "target_vm": vm_name, "memory_path": mem_path, "file": file,
                    "status": "pushed",
                    "memory_index": memory_index,
                })
```

- [ ] **Step 4: Run test and confirm it passes**

```bash
cd /Users/dav/src/claude-memory-mcp && .venv/bin/python -m pytest "tests/test_server.py::TestSyncNowPendingShares::test_retried_push_updates_memory_index" -v 2>&1 | tail -10
```

Expected: PASSED

- [ ] **Step 5: Confirm full suite passes**

```bash
cd /Users/dav/src/claude-memory-mcp && .venv/bin/python -m pytest tests/test_server.py -v 2>&1 | tail -5
```

Expected: 73 passed

- [ ] **Step 6: Commit**

```bash
git add server.py tests/test_server.py
git commit -m "feat: update MEMORY.md index after pending-shares queue retry"
```
