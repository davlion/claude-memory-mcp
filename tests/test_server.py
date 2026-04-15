"""Unit tests for server.py MCP tools with mock filesystem."""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

import server


@pytest.fixture
def cache_dir(tmp_path, monkeypatch):
    """Create a mock cache directory and patch _cache_dir to return it."""
    monkeypatch.setattr(server, "_cache_dir", lambda: tmp_path)
    return tmp_path


@pytest.fixture
def populated_cache(cache_dir):
    """Set up a cache directory with two VMs and projects containing memory files."""
    # VM 1: dev-vm with project "myapp"
    proj1 = cache_dir / "dev-vm" / "-myapp" / "memory"
    proj1.mkdir(parents=True)
    (proj1 / "MEMORY.md").write_text("# MyApp Memory Index\n- architecture.md\n", encoding="utf-8")
    (proj1 / "architecture.md").write_text("MyApp uses a microservices architecture.\n", encoding="utf-8")
    (proj1 / "decisions.md").write_text("We decided to use PostgreSQL for persistence.\n", encoding="utf-8")

    # VM 1: dev-vm with project "utils"
    proj2 = cache_dir / "dev-vm" / "-utils" / "memory"
    proj2.mkdir(parents=True)
    (proj2 / "MEMORY.md").write_text("# Utils Index\n", encoding="utf-8")

    # VM 2: staging-vm with project "webapp"
    proj3 = cache_dir / "staging-vm" / "-webapp" / "memory"
    proj3.mkdir(parents=True)
    (proj3 / "MEMORY.md").write_text("# Webapp Index\n", encoding="utf-8")
    (proj3 / "setup.md").write_text("The webapp runs on port 8080 with PostgreSQL backend.\n", encoding="utf-8")

    # last-sync.json
    sync = {
        "dev-vm": {"last_sync": "2026-04-09T10:00:00Z", "success": True},
        "staging-vm": {"last_sync": "2026-04-08T15:00:00Z", "success": False},
    }
    (cache_dir / "last-sync.json").write_text(json.dumps(sync), encoding="utf-8")

    return cache_dir


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
    monkeypatch.setattr(server, "CACHE_DIR", tmp_path)  # share_memory reads CACHE_DIR directly for config

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


# ── list_projects ──────────────────────────────────────────────────────────


class TestListProjects:
    def test_empty_cache(self, cache_dir):
        result = json.loads(list_projects())
        assert result == []

    def test_cache_dir_does_not_exist(self, tmp_path, monkeypatch):
        monkeypatch.setattr(server, "_cache_dir", lambda: tmp_path / "nonexistent")
        result = json.loads(list_projects())
        assert result == []

    def test_lists_all_projects(self, populated_cache):
        result = json.loads(list_projects())
        assert len(result) == 3
        names = {r["project"] for r in result}
        assert names == {"myapp", "utils", "webapp"}

    def test_memory_count(self, populated_cache):
        result = json.loads(list_projects())
        by_project = {r["project"]: r for r in result}
        # myapp has MEMORY.md + architecture.md + decisions.md = 3
        assert by_project["myapp"]["memory_count"] == 3
        # utils has just MEMORY.md = 1
        assert by_project["utils"]["memory_count"] == 1
        # webapp has MEMORY.md + setup.md = 2
        assert by_project["webapp"]["memory_count"] == 2

    def test_last_sync_included(self, populated_cache):
        result = json.loads(list_projects())
        by_project = {r["project"]: r for r in result}
        assert by_project["myapp"]["last_sync"] == "2026-04-09T10:00:00Z"
        assert by_project["webapp"]["last_sync"] == "2026-04-08T15:00:00Z"

    def test_vm_name_included(self, populated_cache):
        result = json.loads(list_projects())
        by_project = {r["project"]: r for r in result}
        assert by_project["myapp"]["vm"] == "dev-vm"
        assert by_project["webapp"]["vm"] == "staging-vm"

    def test_skips_dotfiles_and_json(self, cache_dir):
        # Create dirs that should be skipped
        (cache_dir / ".hidden").mkdir()
        (cache_dir / "something.json").mkdir()
        # Create a valid project
        mem = cache_dir / "vm1" / "-proj" / "memory"
        mem.mkdir(parents=True)
        (mem / "MEMORY.md").write_text("index", encoding="utf-8")
        result = json.loads(list_projects())
        assert len(result) == 1
        assert result[0]["project"] == "proj"

    def test_project_without_memory_dir(self, cache_dir):
        (cache_dir / "vm1" / "-proj").mkdir(parents=True)
        result = json.loads(list_projects())
        assert len(result) == 1
        assert result[0]["memory_count"] == 0


# ── read_memories ──────────────────────────────────────────────────────────


class TestReadMemories:
    def test_reads_project_memories(self, populated_cache):
        result = json.loads(read_memories("myapp"))
        assert result["project"] == "myapp"
        assert result["vm"] == "dev-vm"
        assert "MyApp Memory Index" in result["index"]
        files = {m["file"] for m in result["memories"]}
        assert files == {"architecture.md", "decisions.md"}

    def test_excludes_memory_md_from_memories_list(self, populated_cache):
        result = json.loads(read_memories("myapp"))
        files = [m["file"] for m in result["memories"]]
        assert "MEMORY.md" not in files

    def test_project_not_found(self, populated_cache):
        result = json.loads(read_memories("nonexistent"))
        assert "error" in result
        assert "not found" in result["error"]

    def test_cache_dir_missing(self, tmp_path, monkeypatch):
        monkeypatch.setattr(server, "_cache_dir", lambda: tmp_path / "gone")
        result = json.loads(read_memories("anything"))
        assert "error" in result

    def test_project_without_memory_dir(self, cache_dir):
        (cache_dir / "vm1" / "-bare").mkdir(parents=True)
        result = json.loads(read_memories("bare"))
        assert result["project"] == "bare"
        assert result["index"] == ""
        assert result["memories"] == []

    def test_project_without_index(self, cache_dir):
        mem = cache_dir / "vm1" / "-noindex" / "memory"
        mem.mkdir(parents=True)
        (mem / "notes.md").write_text("some notes", encoding="utf-8")
        result = json.loads(read_memories("noindex"))
        assert result["index"] == ""
        assert len(result["memories"]) == 1
        assert result["memories"][0]["file"] == "notes.md"


# ── search_memories ────────────────────────────────────────────────────────


class TestSearchMemories:
    def test_finds_matching_content(self, populated_cache):
        result = json.loads(search_memories("postgresql"))
        assert len(result) == 2
        projects = {r["project"] for r in result}
        assert projects == {"myapp", "webapp"}

    def test_case_insensitive(self, populated_cache):
        result = json.loads(search_memories("POSTGRESQL"))
        assert len(result) == 2

    def test_no_matches(self, populated_cache):
        result = json.loads(search_memories("xyznonexistent"))
        assert result == []

    def test_empty_cache(self, cache_dir):
        result = json.loads(search_memories("anything"))
        assert result == []

    def test_cache_dir_missing(self, tmp_path, monkeypatch):
        monkeypatch.setattr(server, "_cache_dir", lambda: tmp_path / "gone")
        result = json.loads(search_memories("test"))
        assert result == []

    def test_match_context_included(self, populated_cache):
        result = json.loads(search_memories("microservices"))
        assert len(result) == 1
        assert "microservices" in result[0]["match"]
        assert result[0]["file"] == "architecture.md"
        assert result[0]["project"] == "myapp"

    def test_match_in_memory_index(self, populated_cache):
        # "architecture.md" appears in MEMORY.md index
        result = json.loads(search_memories("architecture.md"))
        matches = [r for r in result if r["file"] == "MEMORY.md"]
        assert len(matches) == 1


# ── sync_status ────────────────────────────────────────────────────────────


class TestSyncStatus:
    def test_returns_sync_info(self, populated_cache):
        result = json.loads(sync_status())
        assert len(result) == 2
        by_vm = {r["vm"]: r for r in result}
        assert by_vm["dev-vm"]["last_sync"] == "2026-04-09T10:00:00Z"
        assert by_vm["dev-vm"]["reachable"] is True
        assert by_vm["staging-vm"]["reachable"] is False

    def test_no_sync_file(self, cache_dir):
        result = json.loads(sync_status())
        assert result == []

    def test_corrupt_sync_file(self, cache_dir):
        (cache_dir / "last-sync.json").write_text("not json!", encoding="utf-8")
        result = json.loads(sync_status())
        assert result == []

    def test_missing_cache_dir(self, tmp_path, monkeypatch):
        monkeypatch.setattr(server, "_cache_dir", lambda: tmp_path / "gone")
        result = json.loads(sync_status())
        assert result == []


# ── all_projects_index resource ────────────────────────────────────────────


class TestAllProjectsIndex:
    def test_no_cache(self, tmp_path, monkeypatch):
        monkeypatch.setattr(server, "_cache_dir", lambda: tmp_path / "nonexistent")
        result = all_projects_index()
        assert "No memory cache" in result

    def test_empty_cache(self, cache_dir):
        result = all_projects_index()
        assert "No projects" in result

    def test_contains_all_projects(self, populated_cache):
        result = all_projects_index()
        assert "myapp" in result
        assert "utils" in result
        assert "webapp" in result

    def test_contains_index_content(self, populated_cache):
        result = all_projects_index()
        assert "MyApp Memory Index" in result
        assert "Webapp Index" in result

    def test_contains_vm_and_sync_metadata(self, populated_cache):
        result = all_projects_index()
        assert "dev-vm" in result
        assert "staging-vm" in result
        assert "2026-04-09T10:00:00Z" in result

    def test_separated_by_divider(self, populated_cache):
        result = all_projects_index()
        assert "---" in result

    def test_no_index_file(self, cache_dir):
        mem = cache_dir / "vm1" / "-bare" / "memory"
        mem.mkdir(parents=True)
        result = all_projects_index()
        assert "bare" in result
        assert "no MEMORY.md index" in result


# ── project_memory_resource resource ───────────────────────────────────────


class TestProjectMemoryResource:
    def test_reads_all_files(self, populated_cache):
        result = project_memory_resource("myapp")
        assert "MEMORY.md" in result
        assert "architecture.md" in result
        assert "decisions.md" in result
        assert "MyApp Memory Index" in result
        assert "microservices" in result

    def test_project_not_found(self, populated_cache):
        result = project_memory_resource("nonexistent")
        assert "not found" in result

    def test_no_memory_dir(self, cache_dir):
        (cache_dir / "vm1" / "-bare").mkdir(parents=True)
        result = project_memory_resource("bare")
        assert "No memory directory" in result

    def test_no_cache(self, tmp_path, monkeypatch):
        monkeypatch.setattr(server, "_cache_dir", lambda: tmp_path / "gone")
        result = project_memory_resource("anything")
        assert "unavailable" in result

    def test_separated_by_divider(self, populated_cache):
        result = project_memory_resource("myapp")
        assert "---" in result


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

    def test_unreachable_vm_queues_entry(self, share_with_config, tmp_path):
        """Unreachable VM gets a queue entry in pending-shares.json."""
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

        assert result[0]["status"] == "queued"
        queue_path = tmp_path / "pending-shares.json"
        assert queue_path.exists()
        entries = json.loads(queue_path.read_text(encoding="utf-8"))
        assert len(entries) == 1
        assert entries[0]["target_vm"] == "remote-vm"
        assert entries[0]["file"] == "feedback_debugging.md"
        assert entries[0]["memory_path"] == "~/.claude/projects/-Users-dav-src-myapp/memory"
        assert entries[0]["overwrite"] is False
        assert "queued_at" in entries[0]

    def test_unreachable_vm_queue_entry_has_content(self, share_with_config, tmp_path):
        """Queue entry captures file content at queue time."""
        def fake_run(cmd, **kwargs):
            m = MagicMock()
            m.returncode = 1 if cmd[0] == "nc" else 0
            m.stdout = ""
            m.stderr = ""
            return m

        with patch("subprocess.run", side_effect=fake_run):
            share_memory("feedback_debugging.md", "myapp", target_vms=["remote-vm"])

        entries = json.loads(
            (tmp_path / "pending-shares.json").read_text(encoding="utf-8")
        )
        assert entries[0]["content"] == (
            "---\nname: debugging\ntype: feedback\n---\nMeasure before fixing.\n"
        )

    def test_unreachable_broadcast_queues_all_paths(self, share_with_config, tmp_path):
        """Broadcast mode queues one entry per memory_path on unreachable VM."""
        def fake_run(cmd, **kwargs):
            m = MagicMock()
            m.returncode = 1 if cmd[0] == "nc" else 0
            m.stdout = ""
            m.stderr = ""
            return m

        with patch("subprocess.run", side_effect=fake_run):
            share_memory(
                "feedback_debugging.md", "myapp",
                target_vms=["remote-vm"],
                broadcast=True
            )

        entries = json.loads(
            (tmp_path / "pending-shares.json").read_text(encoding="utf-8")
        )
        paths = {e["memory_path"] for e in entries}
        assert "~/.claude/projects/-Users-dav-src-myapp/memory" in paths
        assert "~/.claude/projects/-Users-dav-src-otherapp/memory" in paths

    def test_no_project_on_vm_not_queued(self, share_with_config, tmp_path, monkeypatch):
        """VM with no matching project is not queued (skipped as before)."""
        config_no_match = {
            "local_cache": str(tmp_path),
            "vms": [
                {
                    "name": "no-myapp-vm",
                    "host": "192.168.1.200",
                    "user": "testuser",
                    "ssh_key": "~/.ssh/claude_memory_ed25519",
                    "memory_paths": ["~/.claude/projects/-Users-dav-src-unrelated/memory"],
                }
            ],
        }
        (tmp_path / "config.json").write_text(json.dumps(config_no_match), encoding="utf-8")

        def fake_run(cmd, **kwargs):
            m = MagicMock()
            m.returncode = 0
            m.stdout = ""
            m.stderr = ""
            return m

        with patch("subprocess.run", side_effect=fake_run):
            result = json.loads(share_memory("feedback_debugging.md", "myapp"))

        assert result[0]["status"] == "skipped"
        assert not (tmp_path / "pending-shares.json").exists()


# ── sync_now pending shares processing ────────────────────────────────────


class TestSyncNowPendingShares:

    def _make_queue(self, tmp_path, entries):
        """Write pending-shares.json with given entries."""
        (tmp_path / "pending-shares.json").write_text(
            json.dumps(entries), encoding="utf-8"
        )

    def _base_entry(self, vm="remote-vm", path="~/.claude/projects/-Users-dav-src-myapp/memory"):
        return {
            "queued_at": "2026-04-15T10:00:00Z",
            "file": "feedback_debugging.md",
            "content": "Measure before fixing.\n",
            "target_vm": vm,
            "memory_path": path,
            "overwrite": False,
        }

    def test_empty_queue_no_error(self, share_with_config, tmp_path):
        """sync_now with no pending-shares.json returns pending_shares: []."""
        def fake_run(cmd, **kwargs):
            m = MagicMock()
            m.returncode = 0
            m.stdout = "sync complete"
            m.stderr = ""
            return m

        with patch("subprocess.run", side_effect=fake_run):
            with patch("pathlib.Path.exists", return_value=False):
                result = json.loads(sync_now())

        assert result.get("pending_shares", []) == []

    def test_reachable_vm_entry_pushed_and_removed(self, share_with_config, tmp_path):
        """When queued VM becomes reachable, entry is pushed and removed from queue."""
        self._make_queue(tmp_path, [self._base_entry()])

        rsync_called = []

        def fake_run(cmd, **kwargs):
            m = MagicMock()
            m.returncode = 0
            m.stdout = "__NOT_FOUND__\n" if cmd[0] == "ssh" else "sync complete"
            m.stderr = ""
            if cmd[0] == "rsync":
                rsync_called.append(True)
            return m

        with patch("subprocess.run", side_effect=fake_run):
            result = json.loads(sync_now())

        assert rsync_called
        pending = result.get("pending_shares", [])
        assert any(e["status"] == "pushed" for e in pending)
        # Queue file should be gone (empty queue)
        assert not (tmp_path / "pending-shares.json").exists()

    def test_still_unreachable_entry_stays_in_queue(self, share_with_config, tmp_path):
        """Entry for still-unreachable VM stays in pending-shares.json."""
        self._make_queue(tmp_path, [self._base_entry()])

        def fake_run(cmd, **kwargs):
            m = MagicMock()
            # sync.sh succeeds but nc for pending shares fails
            if cmd[0] == "nc":
                m.returncode = 1
            else:
                m.returncode = 0
                m.stdout = "sync complete"
                m.stderr = ""
            return m

        with patch("subprocess.run", side_effect=fake_run):
            result = json.loads(sync_now())

        pending = result.get("pending_shares", [])
        assert any(e["status"] == "still_unreachable" for e in pending)
        # Entry should remain in queue
        assert (tmp_path / "pending-shares.json").exists()
        remaining = json.loads(
            (tmp_path / "pending-shares.json").read_text(encoding="utf-8")
        )
        assert len(remaining) == 1

    def test_mixed_queue_partial_processing(self, share_with_config, tmp_path):
        """Some entries pushed, some remain when VMs have different reachability."""
        self._make_queue(tmp_path, [
            self._base_entry(vm="remote-vm"),
            self._base_entry(vm="earsvm", path="~/.claude/projects/-Users-dav-src-myapp/memory"),
        ])

        def fake_run(cmd, **kwargs):
            m = MagicMock()
            m.returncode = 0
            m.stdout = "__NOT_FOUND__\n" if cmd[0] == "ssh" else "sync complete"
            m.stderr = ""
            # earsvm unreachable
            if cmd[0] == "nc" and "earsvm" in str(cmd):
                m.returncode = 1
            return m

        # Need earsvm in config — patch it in
        config = json.loads((tmp_path / "config.json").read_text())
        config["vms"].append({
            "name": "earsvm",
            "host": "earsvm.local",
            "user": "testuser",
            "ssh_key": "~/.ssh/claude_memory_ed25519",
            "memory_paths": ["~/.claude/projects/-Users-dav-src-myapp/memory"],
        })
        (tmp_path / "config.json").write_text(json.dumps(config), encoding="utf-8")

        with patch("subprocess.run", side_effect=fake_run):
            result = json.loads(sync_now())

        pending = result.get("pending_shares", [])
        statuses = {e["target_vm"]: e["status"] for e in pending}
        assert statuses.get("remote-vm") == "pushed"
        assert statuses.get("earsvm") == "still_unreachable"

        # Only earsvm entry should remain
        remaining = json.loads(
            (tmp_path / "pending-shares.json").read_text(encoding="utf-8")
        )
        assert len(remaining) == 1
        assert remaining[0]["target_vm"] == "earsvm"


# ── Helper: import tool and resource functions at module level ─────────────

# The MCP decorator wraps the functions, but we can still call them directly.
list_projects = server.list_projects
read_memories = server.read_memories
search_memories = server.search_memories
sync_status = server.sync_status
all_projects_index = server.all_projects_index
project_memory_resource = server.project_memory_resource
share_memory = server.share_memory
sync_now = server.sync_now
