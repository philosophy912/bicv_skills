"""Tests for fetch.py — filename rule, per-build fetch, pipeline, CLI."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from unittest import mock

import fetch


def _proc(stdout: str = "", stderr: str = "", returncode: int = 0) -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(args=[], returncode=returncode, stdout=stdout, stderr=stderr)


def _write_builds(rundir: Path, builds: list) -> Path:
    builds_file = rundir / "builds.json"
    builds_file.write_text(
        json.dumps({"generated_at": "t", "window": {"start": "s", "end": "e"}, "builds": builds}),
        encoding="utf-8",
    )
    return builds_file


# ===================================================================
# log_filename
# ===================================================================


class TestLogFilename:
    def test_plain_job(self):
        assert fetch.log_filename("APP", 12) == "APP__12.log"

    def test_folder_job_slashes_doubled(self):
        assert fetch.log_filename("infra/build-foo", 1234) == "infra__build-foo__1234.log"

    def test_single_underscore_preserved(self):
        assert fetch.log_filename("A_B", 9) == "A_B__9.log"


# ===================================================================
# fetch_one
# ===================================================================


class TestFetchOne:
    def test_ok_returns_text(self):
        with mock.patch("fetch.run_jenkins_cli", return_value=_proc(stdout="log body")):
            (job, number), ok, payload = fetch.fetch_one("/c", None, {"job": "J", "number": 1})
        assert job == "J" and number == 1 and ok is True and payload == "log body"

    def test_nonzero_is_error(self):
        with mock.patch("fetch.run_jenkins_cli", return_value=_proc(returncode=3, stderr="nope")):
            (_, _), ok, payload = fetch.fetch_one("/c", None, {"job": "J", "number": 1})
        assert ok is False and "exit 3" in payload and "nope" in payload

    def test_timeout_is_error(self):
        with mock.patch("fetch.run_jenkins_cli", side_effect=subprocess.TimeoutExpired(["x"], 300)):
            (_, _), ok, payload = fetch.fetch_one("/c", None, {"job": "J", "number": 1})
        assert ok is False and payload == "timeout"

    def test_generic_exception_is_error(self):
        with mock.patch("fetch.run_jenkins_cli", side_effect=ValueError("bad")):
            (_, _), ok, payload = fetch.fetch_one("/c", None, {"job": "J", "number": 1})
        assert ok is False and "ValueError" in payload

    def test_missing_keys_is_error(self):
        # 脏条目（缺 number）返回错误而非抛 KeyError
        (_, _), ok, payload = fetch.fetch_one("/c", None, {"job": "J"})
        assert ok is False and "缺少" in payload


# ===================================================================
# cmd_fetch
# ===================================================================


class TestCmdFetch:
    def test_pipeline_writes_logs_and_updates_builds(self, tmp_path, capsys):
        builds = [
            {"job": "GOOD", "number": 1, "result": "FAILURE", "url": "u/1/"},
            {"job": "BAD", "number": 2, "result": "FAILURE", "url": "u/2/"},
        ]
        _write_builds(tmp_path, builds)

        def fake_fetch_one(cli, system, b):
            if b["job"] == "GOOD":
                return (b["job"], b["number"]), True, "good log"
            return (b["job"], b["number"]), False, "exit 1: boom"

        args = mock.MagicMock(cli="/c", system=None, workers=4, rundir=str(tmp_path))
        with mock.patch("fetch.fetch_one", side_effect=fake_fetch_one):
            rc = fetch.cmd_fetch(args)
        assert rc == 0
        out = capsys.readouterr().out
        assert "fetched ok=1 err=1" in out

        # 日志文件写入
        assert (tmp_path / "logs" / "GOOD__1.log").read_text("utf-8") == "good log"
        assert not (tmp_path / "logs" / "BAD__2.log").exists()

        # builds.json 回写
        data = json.loads((tmp_path / "builds.json").read_text("utf-8"))
        by_job = {b["job"]: b for b in data["builds"]}
        assert by_job["GOOD"]["log_file"] == "GOOD__1.log"
        assert "fetch_error" not in by_job["GOOD"]
        assert by_job["BAD"]["fetch_error"] is True
        assert "log_file" not in by_job["BAD"]

    def test_reads_builds_json_with_utf8_bom(self, tmp_path, capsys):
        # Windows PowerShell 保存的 builds.json 常带 BOM，读取侧用 utf-8-sig 自动剥离。
        builds_file = tmp_path / "builds.json"
        builds_file.write_text(
            "﻿"
            + json.dumps({"generated_at": "t", "window": {"start": "s", "end": "e"}, "builds": []}),
            encoding="utf-8",
        )
        args = mock.MagicMock(cli="/c", system=None, workers=4, rundir=str(tmp_path))
        with mock.patch("fetch.fetch_one"):
            rc = fetch.cmd_fetch(args)
        assert rc == 0
        assert "fetched ok=0 err=0" in capsys.readouterr().out

    def test_missing_builds_json_returns_1(self, tmp_path, capsys):
        args = mock.MagicMock(cli="/c", system=None, workers=4, rundir=str(tmp_path))
        rc = fetch.cmd_fetch(args)
        assert rc == 1
        assert "builds.json not found" in capsys.readouterr().err

    def test_builds_not_list_returns_1(self, tmp_path, capsys):
        (tmp_path / "builds.json").write_text(json.dumps({"builds": "notalist"}), encoding="utf-8")
        args = mock.MagicMock(cli="/c", system=None, workers=4, rundir=str(tmp_path))
        rc = fetch.cmd_fetch(args)
        assert rc == 1
        assert "no builds[]" in capsys.readouterr().err

    def test_empty_builds(self, tmp_path, capsys):
        _write_builds(tmp_path, [])
        args = mock.MagicMock(cli="/c", system=None, workers=4, rundir=str(tmp_path))
        with mock.patch("fetch.fetch_one") as m:
            rc = fetch.cmd_fetch(args)
        assert rc == 0
        assert "fetched ok=0 err=0" in capsys.readouterr().out
        m.assert_not_called()

    def test_dirty_entry_marked_and_skipped(self, tmp_path, capsys):
        # builds.json 含缺 number 的脏条目：不崩溃，标记 fetch_error，其余正常处理
        builds = [
            {"job": "GOOD", "number": 1, "result": "FAILURE"},
            {"job": "DIRTY"},  # 缺 number
        ]
        _write_builds(tmp_path, builds)

        def fake_fetch_one(cli, system, b):
            return (b.get("job"), b.get("number")), True, "log"

        args = mock.MagicMock(cli="/c", system=None, workers=4, rundir=str(tmp_path))
        with mock.patch("fetch.fetch_one", side_effect=fake_fetch_one):
            rc = fetch.cmd_fetch(args)
        assert rc == 0
        out = capsys.readouterr().out
        # GOOD 成功(ok)，DIRTY 缺键算 err
        assert "fetched ok=1 err=1" in out
        with open(tmp_path / "builds.json", encoding="utf-8") as fh:
            data = json.load(fh)
        dirty = next(b for b in data["builds"] if b["job"] == "DIRTY")
        assert dirty.get("fetch_error") is True


# ===================================================================
# build_parser / main
# ===================================================================


class TestParserAndMain:
    def test_required_args(self):
        with mock.patch.object(sys, "argv", ["fetch.py"]):
            try:
                fetch.build_parser().parse_args()
            except SystemExit as exc:
                assert exc.code != 0
            else:
                raise AssertionError("expected SystemExit for missing --cli/--rundir")

    def test_defaults(self):
        with mock.patch.object(sys, "argv", ["fetch.py", "--cli", "/c", "--rundir", "/r"]):
            args = fetch.build_parser().parse_args()
        assert args.cli == "/c" and args.rundir == "/r" and args.workers == 20

    def test_main_invokes_cmd_fetch(self):
        args = mock.MagicMock()
        with (
            mock.patch("fetch.build_parser") as bp,
            mock.patch("fetch.cmd_fetch", return_value=3) as cc,
        ):
            bp.return_value.parse_args.return_value = args
            assert fetch.main() == 3
        cc.assert_called_once_with(args)
