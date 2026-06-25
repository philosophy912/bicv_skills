"""Tests for _email_config.py — ServiceError and load_systems_config.

All filesystem access is isolated via tmp_path + monkeypatch of Path.home;
no real ~/.bicv/email.json is ever read.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import _email_config as cfg
from _email_config import ServiceError

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write_config(tmp_path: Path, data: dict, name: str = "email.json") -> Path:
    bicv = tmp_path / ".bicv"
    bicv.mkdir(exist_ok=True)
    (bicv / name).write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return tmp_path


def _systems() -> dict:
    return {
        "default": {
            "smtp": {
                "host": "smtp.example.com",
                "port": 465,
                "username": "me@x.com",
                "password": "p",
            },
            "imap": {
                "host": "imap.example.com",
                "port": 993,
                "username": "me@x.com",
                "password": "p",
            },
            "from_address": "me@x.com",
        }
    }


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
        home = _write_config(tmp_path, {"default_system": "default", "systems": _systems()})
        monkeypatch.setattr(Path, "home", lambda: home)
        data = cfg.load_systems_config("email.json")
        assert "default" in data["systems"]
        assert data["_config_path"].endswith("email.json")

    def test_missing_file_raises(self, tmp_path, monkeypatch):
        (tmp_path / ".bicv").mkdir()
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        with pytest.raises(ServiceError, match="Cannot find config file"):
            cfg.load_systems_config("email.json")

    def test_invalid_json_raises(self, tmp_path, monkeypatch):
        bicv = tmp_path / ".bicv"
        bicv.mkdir()
        (bicv / "email.json").write_text("{not json", encoding="utf-8")
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        with pytest.raises(ServiceError, match="not valid JSON"):
            cfg.load_systems_config("email.json")

    def test_missing_systems_key_raises(self, tmp_path, monkeypatch):
        home = _write_config(tmp_path, {"default_system": "default"})
        monkeypatch.setattr(Path, "home", lambda: home)
        with pytest.raises(ServiceError, match="missing a systems object"):
            cfg.load_systems_config("email.json")

    def test_systems_not_dict_raises(self, tmp_path, monkeypatch):
        home = _write_config(tmp_path, {"systems": "notadict"})
        monkeypatch.setattr(Path, "home", lambda: home)
        with pytest.raises(ServiceError, match="missing a systems object"):
            cfg.load_systems_config("email.json")
