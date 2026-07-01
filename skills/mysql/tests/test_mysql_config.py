"""Tests for _mysql_config.py — config loading, system matching, MySQL resolution.

All filesystem access is isolated via tmp_path + monkeypatch of Path.home;
no real ~/.bicv/mysql.json is ever read.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import _mysql_config as cfg
from _mysql_config import MySQLConnectionConfig, ServiceError

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write_config(tmp_path: Path, data: dict, name: str = "mysql.json") -> Path:
    """Write *data* as ~/.bicv/<name> under *tmp_path*; return the home dir."""
    bicv = tmp_path / ".bicv"
    bicv.mkdir(exist_ok=True)
    (bicv / name).write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return tmp_path


def _systems(**overrides) -> dict:
    system = {
        "host": "db.example.com",
        "port": 3306,
        "database": "appdb",
        "username": "dbuser",
        "password": "dbpass",
    }
    system.update(overrides)
    return {"prod": system}


def _full_config(systems: dict | None = None, default: str = "prod") -> dict:
    return {"default_system": default, "systems": systems or _systems()}


# ===========================================================================
# ServiceError
# ===========================================================================


class TestServiceError:
    def test_str_no_status(self):
        assert str(ServiceError("boom")) == "boom"

    def test_str_with_status(self):
        assert str(ServiceError("boom", status_code=500)) == "boom (HTTP 500)"


# ===========================================================================
# load_systems_config
# ===========================================================================


class TestLoadSystemsConfig:
    def test_loads_valid_config(self, tmp_path, monkeypatch):
        home = _write_config(tmp_path, _full_config())
        monkeypatch.setattr(Path, "home", lambda: home)
        data = cfg.load_systems_config("mysql.json")
        assert "prod" in data["systems"]
        assert data["_config_path"].endswith("mysql.json")

    def test_loads_config_with_utf8_bom(self, tmp_path, monkeypatch):
        # Windows PowerShell 保存的配置常带 UTF-8 BOM，读取侧用 utf-8-sig 自动剥离。
        bicv = tmp_path / ".bicv"
        bicv.mkdir()
        (bicv / "mysql.json").write_text(
            "﻿" + json.dumps(_full_config(), ensure_ascii=False),
            encoding="utf-8",
        )
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        data = cfg.load_systems_config("mysql.json")
        assert "prod" in data["systems"]

    def test_missing_file_raises(self, tmp_path, monkeypatch):
        # .bicv exists but mysql.json does not
        (tmp_path / ".bicv").mkdir()
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        with pytest.raises(ServiceError, match="Cannot find config file"):
            cfg.load_systems_config("mysql.json")

    def test_invalid_json_raises(self, tmp_path, monkeypatch):
        bicv = tmp_path / ".bicv"
        bicv.mkdir()
        (bicv / "mysql.json").write_text("{not json", encoding="utf-8")
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        with pytest.raises(ServiceError, match="not valid JSON"):
            cfg.load_systems_config("mysql.json")

    def test_missing_systems_key_raises(self, tmp_path, monkeypatch):
        home = _write_config(tmp_path, {"default_system": "prod"})
        monkeypatch.setattr(Path, "home", lambda: home)
        with pytest.raises(ServiceError, match="missing a systems object"):
            cfg.load_systems_config("mysql.json")

    def test_systems_not_dict_raises(self, tmp_path, monkeypatch):
        home = _write_config(tmp_path, {"systems": ["not", "a", "dict"]})
        monkeypatch.setattr(Path, "home", lambda: home)
        with pytest.raises(ServiceError, match="missing a systems object"):
            cfg.load_systems_config("mysql.json")


# ===========================================================================
# system_matches
# ===========================================================================


class TestSystemMatches:
    def test_exact_name_match(self):
        assert cfg.system_matches("prod", "prod", {"host": "x"}) is True

    def test_case_insensitive_name(self):
        assert cfg.system_matches("PROD", "prod", {"host": "x"}) is True

    def test_alias_match(self):
        sc = {"host": "x", "aliases": ["production", "live"]}
        assert cfg.system_matches("live", "prod", sc) is True

    def test_host_match(self):
        assert cfg.system_matches("db.example.com", "prod", {"host": "db.example.com"}) is True

    def test_no_match(self):
        assert cfg.system_matches("staging", "prod", {"host": "db.example.com"}) is False

    def test_empty_selector(self):
        assert cfg.system_matches("   ", "prod", {"host": "x"}) is False

    def test_aliases_not_list_ignored(self):
        # aliases must be a list; a string alias is ignored
        assert (
            cfg.system_matches("production", "prod", {"host": "x", "aliases": "production"})
            is False
        )


# ===========================================================================
# find_system
# ===========================================================================


class TestFindSystem:
    def test_exact_key_returns_config(self):
        systems = {"prod": {"host": "x"}}
        name, sc = cfg.find_system("prod", systems, "/path")
        assert name == "prod"
        assert sc == {"host": "x"}

    def test_alias_fallback_match(self):
        systems = {"prod": {"host": "db.example.com", "aliases": ["live"]}}
        name, _ = cfg.find_system("live", systems, "/path")
        assert name == "prod"

    def test_no_match_raises(self):
        with pytest.raises(ServiceError, match="does not exist"):
            cfg.find_system("nope", {"prod": {"host": "x"}}, "/path")

    def test_multiple_matches_raises(self):
        systems = {
            "prod": {"host": "db.example.com"},
            "stage": {"host": "db.example.com"},
        }
        with pytest.raises(ServiceError, match="matches multiple configs"):
            cfg.find_system("db.example.com", systems, "/path")

    def test_non_dict_system_value_skipped(self):
        # A non-dict system value should not crash find_system
        systems = {"prod": {"host": "x"}, "broken": "notadict"}
        name, _ = cfg.find_system("prod", systems, "/path")
        assert name == "prod"


# ===========================================================================
# resolve_mysql_config
# ===========================================================================


class TestResolveMysqlConfig:
    def test_resolve_full(self, tmp_path, monkeypatch):
        home = _write_config(tmp_path, _full_config())
        monkeypatch.setattr(Path, "home", lambda: home)
        c = cfg.resolve_mysql_config()
        assert isinstance(c, MySQLConnectionConfig)
        assert c.host == "db.example.com"
        assert c.port == 3306
        assert c.database == "appdb"
        assert c.system_name == "prod"

    def test_explicit_system_overrides_default(self, tmp_path, monkeypatch):
        systems = {
            "prod": {"host": "p.example.com", "username": "u", "password": "p"},
            "stage": {"host": "s.example.com", "username": "u", "password": "p"},
        }
        home = _write_config(tmp_path, _full_config(systems=systems))
        monkeypatch.setattr(Path, "home", lambda: home)
        c = cfg.resolve_mysql_config(system="stage")
        assert c.host == "s.example.com"
        assert c.system_name == "stage"

    def test_default_port_when_missing(self, tmp_path, monkeypatch):
        systems = {"prod": {"host": "x", "username": "u", "password": "p"}}
        home = _write_config(tmp_path, _full_config(systems=systems))
        monkeypatch.setattr(Path, "home", lambda: home)
        assert cfg.resolve_mysql_config().port == 3306

    def test_database_none_when_missing(self, tmp_path, monkeypatch):
        systems = {"prod": {"host": "x", "username": "u", "password": "p"}}
        home = _write_config(tmp_path, _full_config(systems=systems))
        monkeypatch.setattr(Path, "home", lambda: home)
        assert cfg.resolve_mysql_config().database is None

    def test_no_system_and_no_default_raises(self, tmp_path, monkeypatch):
        home = _write_config(tmp_path, {"systems": {"prod": {"host": "x"}}})
        monkeypatch.setattr(Path, "home", lambda: home)
        with pytest.raises(ServiceError, match="No --system specified"):
            cfg.resolve_mysql_config()

    def test_missing_host_raises(self, tmp_path, monkeypatch):
        systems = {"prod": {"username": "u", "password": "p"}}
        home = _write_config(tmp_path, _full_config(systems=systems))
        monkeypatch.setattr(Path, "home", lambda: home)
        with pytest.raises(ServiceError, match="missing host field"):
            cfg.resolve_mysql_config()

    def test_invalid_port_raises(self, tmp_path, monkeypatch):
        systems = {"prod": {"host": "x", "port": "notanint", "username": "u", "password": "p"}}
        home = _write_config(tmp_path, _full_config(systems=systems))
        monkeypatch.setattr(Path, "home", lambda: home)
        with pytest.raises(ServiceError, match="Invalid port value"):
            cfg.resolve_mysql_config()

    def test_unknown_system_raises(self, tmp_path, monkeypatch):
        home = _write_config(tmp_path, _full_config())
        monkeypatch.setattr(Path, "home", lambda: home)
        with pytest.raises(ServiceError, match="does not exist"):
            cfg.resolve_mysql_config(system="ghost")


# ===========================================================================
# print_error
# ===========================================================================


class TestPrintError:
    def test_prints_message(self, capsys):
        rc = cfg.print_error(ServiceError("boom"))
        captured = capsys.readouterr()
        assert captured.out == ""  # stdout 保持空，错误走 stderr
        payload = json.loads(captured.err)
        assert payload["error"]["message"] == "boom"
        assert rc == 1

    def test_prints_response_text(self, capsys):
        err = ServiceError("boom", response_text="  body detail  ")
        rc = cfg.print_error(err)
        captured = capsys.readouterr()
        payload = json.loads(captured.err)
        assert "body detail" in payload["error"]["details"]
        assert rc == 1

    def test_no_response_text(self, capsys):
        rc = cfg.print_error(ServiceError("boom"))
        captured = capsys.readouterr()
        payload = json.loads(captured.err)
        assert payload["error"]["message"] == "boom"
        assert payload["error"]["details"] is None
        assert rc == 1
