"""Unit tests for server.py MCP tools with mock filesystem."""

import json
from pathlib import Path

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


# ── Helper: import tool functions at module level ──────────────────────────

# The MCP decorator wraps the functions, but we can still call them directly.
list_projects = server.list_projects
read_memories = server.read_memories
search_memories = server.search_memories
sync_status = server.sync_status
