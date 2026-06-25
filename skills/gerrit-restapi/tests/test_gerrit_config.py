"""Tests for system_config.py — the HTTP-service config base shared by
gerrit / jenkins / zentao.

Covers ServiceError, ServiceTarget, parse_auth, load_systems_config,
auth_from_system, system_matches, find_system, resolve_target, and the
print_* helpers. All filesystem access is isolated via tmp_path + monkeypatch
of Path.home; no real ~/.bicv/*.json is ever read.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import system_config as sc
from system_config import ServiceError, ServiceTarget

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write_config(tmp_path: Path, data: dict, name: str = "gerrit.json") -> Path:
    bicv = tmp_path / ".bicv"
    bicv.mkdir(exist_ok=True)
    (bicv / name).write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return tmp_path


def _systems(**overrides) -> dict:
    system = {
        "url": "https://gerrit.example.com",
        "username": "me",
        "http_password": "secret",
    }
    system.update(overrides)
    return {"default": system}


def _full_config(systems: dict | None = None, default: str = "default") -> dict:
    return {"default_system": default, "systems": systems or _systems()}


# ===========================================================================
# ServiceError / ServiceTarget
# ===========================================================================


class TestServiceError:
    def test_str_no_status(self):
        assert str(ServiceError("boom")) == "boom"

    def test_str_with_status(self):
        assert str(ServiceError("boom", status_code=500)) == "boom (HTTP 500)"


class TestServiceTarget:
    def test_fields(self):
        t = ServiceTarget(url="https://x", auth=("u", "p"), system_name="s")
        assert t.url == "https://x"
        assert t.auth == ("u", "p")
        assert t.system_name == "s"

    def test_defaults(self):
        t = ServiceTarget(url="https://x", auth=None)
        assert t.system_name is None


# ===========================================================================
# parse_auth
# ===========================================================================


class TestParseAuth:
    def test_valid_user_token(self):
        assert sc.parse_auth("alice:token123") == ("alice", "token123")

    def test_valid_user_password(self):
        assert sc.parse_auth("bob:pass:with:colons") == ("bob", "pass:with:colons")

    def test_missing_separator_raises(self):
        with pytest.raises(ServiceError, match="username:token or username:password"):
            sc.parse_auth("noseparator")


# ===========================================================================
# load_systems_config
# ===========================================================================


class TestLoadSystemsConfig:
    def test_loads_valid_config(self, tmp_path, monkeypatch):
        home = _write_config(tmp_path, _full_config())
        monkeypatch.setattr(Path, "home", lambda: home)
        data = sc.load_systems_config("gerrit.json")
        assert "default" in data["systems"]
        assert data["_config_path"].endswith("gerrit.json")

    def test_missing_file_raises(self, tmp_path, monkeypatch):
        (tmp_path / ".bicv").mkdir()
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        with pytest.raises(ServiceError, match="Cannot find config file"):
            sc.load_systems_config("gerrit.json")

    def test_invalid_json_raises(self, tmp_path, monkeypatch):
        bicv = tmp_path / ".bicv"
        bicv.mkdir()
        (bicv / "gerrit.json").write_text("{not json", encoding="utf-8")
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        with pytest.raises(ServiceError, match="not valid JSON"):
            sc.load_systems_config("gerrit.json")

    def test_missing_systems_key_raises(self, tmp_path, monkeypatch):
        home = _write_config(tmp_path, {"default_system": "default"})
        monkeypatch.setattr(Path, "home", lambda: home)
        with pytest.raises(ServiceError, match="missing a systems object"):
            sc.load_systems_config("gerrit.json")

    def test_systems_not_dict_raises(self, tmp_path, monkeypatch):
        home = _write_config(tmp_path, {"systems": ["not", "a", "dict"]})
        monkeypatch.setattr(Path, "home", lambda: home)
        with pytest.raises(ServiceError, match="missing a systems object"):
            sc.load_systems_config("gerrit.json")


# ===========================================================================
# auth_from_system
# ===========================================================================


class TestAuthFromSystem:
    def test_extracts_user_password(self):
        sc_conf = {"username": "me", "password": "secret"}
        assert sc.auth_from_system(sc_conf) == ("me", "secret")

    def test_custom_password_key(self):
        sc_conf = {"username": "me", "http_password": "tok"}
        assert sc.auth_from_system(sc_conf, "http_password") == ("me", "tok")

    def test_missing_username_returns_none(self):
        assert sc.auth_from_system({"password": "p"}) is None

    def test_missing_password_returns_none(self):
        assert sc.auth_from_system({"username": "u"}) is None

    def test_none_config_returns_none(self):
        assert sc.auth_from_system(None) is None


# ===========================================================================
# system_matches
# ===========================================================================


class TestSystemMatches:
    def test_exact_name_match(self):
        assert sc.system_matches("default", "default", {"url": "https://x"}) is True

    def test_case_insensitive_name(self):
        assert sc.system_matches("DEFAULT", "default", {"url": "https://x"}) is True

    def test_alias_match(self):
        sc_conf = {"url": "https://x", "aliases": ["gerrit1", "g1"]}
        assert sc.system_matches("g1", "default", sc_conf) is True

    def test_hostname_match(self):
        sc_conf = {"url": "https://gerrit.example.com/r"}
        assert sc.system_matches("gerrit.example.com", "default", sc_conf) is True

    def test_url_match(self):
        sc_conf = {"url": "https://gerrit.example.com"}
        assert sc.system_matches("https://gerrit.example.com", "default", sc_conf) is True

    def test_no_match(self):
        assert sc.system_matches("nope", "default", {"url": "https://x"}) is False

    def test_empty_selector(self):
        assert sc.system_matches("   ", "default", {"url": "https://x"}) is False

    def test_aliases_not_list_ignored(self):
        assert sc.system_matches("g1", "default", {"url": "https://x", "aliases": "g1"}) is False

    def test_empty_url_not_matched(self):
        # url key missing / empty -> no hostname comparison
        assert sc.system_matches("x", "default", {}) is False


# ===========================================================================
# find_system
# ===========================================================================


class TestFindSystem:
    def test_exact_key_returns_config(self):
        systems = {"default": {"url": "https://x"}}
        name, c = sc.find_system("default", systems, "/path")
        assert name == "default"
        assert c == {"url": "https://x"}

    def test_alias_fallback_match(self):
        systems = {"default": {"url": "https://x", "aliases": ["g1"]}}
        name, _ = sc.find_system("g1", systems, "/path")
        assert name == "default"

    def test_no_match_raises(self):
        with pytest.raises(ServiceError, match="does not exist"):
            sc.find_system("nope", {"default": {"url": "https://x"}}, "/path")

    def test_multiple_matches_raises(self):
        systems = {
            "a": {"url": "https://gerrit.example.com"},
            "b": {"url": "https://gerrit.example.com"},
        }
        with pytest.raises(ServiceError, match="matches multiple configs"):
            sc.find_system("gerrit.example.com", systems, "/path")

    def test_non_dict_system_value_skipped(self):
        systems = {"default": {"url": "https://x"}, "broken": "notadict"}
        name, _ = sc.find_system("default", systems, "/path")
        assert name == "default"


# ===========================================================================
# resolve_target
# ===========================================================================


class TestResolveTarget:
    def test_resolve_from_config_default_system(self, tmp_path, monkeypatch):
        home = _write_config(tmp_path, _full_config())
        monkeypatch.setattr(Path, "home", lambda: home)
        t = sc.resolve_target(
            None, None, None, config_name="gerrit.json", password_key="http_password"
        )
        assert t.url == "https://gerrit.example.com"
        assert t.auth == ("me", "secret")
        assert t.system_name == "default"

    def test_explicit_system_overrides_default(self, tmp_path, monkeypatch):
        systems = {
            "default": {"url": "https://a.example.com", "username": "u", "http_password": "p"},
            "other": {"url": "https://b.example.com", "username": "u", "http_password": "p"},
        }
        home = _write_config(tmp_path, _full_config(systems=systems))
        monkeypatch.setattr(Path, "home", lambda: home)
        t = sc.resolve_target(
            None, None, "other", config_name="gerrit.json", password_key="http_password"
        )
        assert t.url == "https://b.example.com"

    def test_url_override(self, tmp_path, monkeypatch):
        home = _write_config(tmp_path, _full_config())
        monkeypatch.setattr(Path, "home", lambda: home)
        t = sc.resolve_target(
            "https://override.example.com",
            None,
            None,
            config_name="gerrit.json",
            password_key="http_password",
        )
        assert t.url == "https://override.example.com"

    def test_user_override_takes_precedence(self, tmp_path, monkeypatch):
        home = _write_config(tmp_path, _full_config())
        monkeypatch.setattr(Path, "home", lambda: home)
        t = sc.resolve_target(
            None, "cliuser:clipass", None, config_name="gerrit.json", password_key="http_password"
        )
        assert t.auth == ("cliuser", "clipass")

    def test_no_system_and_no_default_raises(self, tmp_path, monkeypatch):
        home = _write_config(tmp_path, {"systems": {"default": {"url": "https://x"}}})
        monkeypatch.setattr(Path, "home", lambda: home)
        with pytest.raises(ServiceError, match="No --system specified"):
            sc.resolve_target(None, None, None, config_name="gerrit.json")

    def test_missing_url_raises(self, tmp_path, monkeypatch):
        systems = {"default": {"username": "u", "password": "p"}}
        home = _write_config(tmp_path, _full_config(systems=systems))
        monkeypatch.setattr(Path, "home", lambda: home)
        with pytest.raises(ServiceError, match="missing url field"):
            sc.resolve_target(None, None, None, config_name="gerrit.json")

    def test_missing_auth_raises(self, tmp_path, monkeypatch):
        systems = {"default": {"url": "https://x"}}  # no username/password
        home = _write_config(tmp_path, _full_config(systems=systems))
        monkeypatch.setattr(Path, "home", lambda: home)
        with pytest.raises(ServiceError, match="requires auth"):
            sc.resolve_target(None, None, None, config_name="gerrit.json")

    def test_unknown_system_raises(self, tmp_path, monkeypatch):
        home = _write_config(tmp_path, _full_config())
        monkeypatch.setattr(Path, "home", lambda: home)
        with pytest.raises(ServiceError, match="does not exist"):
            sc.resolve_target(None, None, "ghost", config_name="gerrit.json")


# ===========================================================================
# print helpers
# ===========================================================================


class TestPrintHelpers:
    def test_print_error_message(self, capsys):
        rc = sc.print_error(ServiceError("boom"))
        out = capsys.readouterr().out
        assert "boom" in out
        assert rc == 1

    def test_print_error_with_response_text(self, capsys):
        rc = sc.print_error(ServiceError("boom", response_text="  detail  "))
        out = capsys.readouterr().out
        assert "detail" in out
        assert rc == 1

    def test_print_system_with_name(self, capsys):
        sc.print_system(ServiceTarget(url="https://x", auth=None, system_name="s"))
        assert "System: s" in capsys.readouterr().out

    def test_print_system_without_name(self, capsys):
        sc.print_system(ServiceTarget(url="https://x", auth=None))
        assert capsys.readouterr().out == ""

    def test_print_json_result_with_heading(self, capsys):
        t = ServiceTarget(url="https://x", auth=None, system_name="s")
        rc = sc.print_json_result(t, {"k": "v"}, heading="Title")
        out = capsys.readouterr().out
        assert "System: s" in out
        assert "Title" in out
        assert '"k": "v"' in out
        assert rc == 0

    def test_print_json_result_no_heading(self, capsys):
        t = ServiceTarget(url="https://x", auth=None, system_name="s")
        rc = sc.print_json_result(t, [1, 2])
        out = capsys.readouterr().out
        assert "[\n  1," in out
        assert rc == 0
