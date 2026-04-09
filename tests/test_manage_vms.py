"""Tests for manage_vms.py config/validation I/O, colors, status, and SSH testing."""

import json
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from manage_vms import (
    load_config, save_config, load_validation, save_validation,
    color_green, color_yellow, color_red,
    vm_status, vm_status_label,
    test_vm_connection as _test_vm_connection,
)

DEFAULT_CONFIG = {
    "vms": [],
    "local_cache": "~/.claude-memories",
    "sync_interval_minutes": 5,
}


# ── Config I/O ───────────────────────────────────────────────────────────

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


# ── Colors ───────────────────────────────────────────────────────────────

class TestColors:
    def test_green(self):
        assert color_green("ok") == "\033[32mok\033[0m"

    def test_yellow(self):
        assert color_yellow("warn") == "\033[33mwarn\033[0m"

    def test_red(self):
        assert color_red("fail") == "\033[31mfail\033[0m"


# ── Validation status ────────────────────────────────────────────────────

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


# ── SSH testing ──────────────────────────────────────────────────────────

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
        result = _test_vm_connection(self._make_vm())
        assert result["ssh"] is False
        assert result["paths"] == {}

    @patch("manage_vms.subprocess.run")
    def test_ssh_ok_all_paths_found(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0)
        result = _test_vm_connection(self._make_vm())
        assert result["ssh"] is True
        assert all(result["paths"].values())

    @patch("manage_vms.subprocess.run")
    def test_ssh_ok_path_missing(self, mock_run):
        mock_run.side_effect = [
            MagicMock(returncode=0),  # ssh echo ok
            MagicMock(returncode=1),  # test -d fails
        ]
        vm = self._make_vm(paths=["/missing/path"])
        result = _test_vm_connection(vm)
        assert result["ssh"] is True
        assert result["paths"]["/missing/path"] is False

    @patch("manage_vms.subprocess.run")
    def test_result_has_last_tested(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0)
        result = _test_vm_connection(self._make_vm())
        assert "last_tested" in result
