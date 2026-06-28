"""Tests for collect.py — config, prefilter, per-job collection, pipeline, CLI."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from unittest import mock

import collect


def _proc(stdout: str = "", stderr: str = "", returncode: int = 0) -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(args=[], returncode=returncode, stdout=stdout, stderr=stderr)


# ===================================================================
# load_run_root
# ===================================================================


class TestLoadRunRoot:
    def test_missing_config_returns_defaults(self, tmp_path):
        with mock.patch("collect.Path.home", return_value=tmp_path):
            root, subdir = collect.load_run_root()
        assert subdir == collect.DEFAULT_SKILL_SUBDIR
        assert root.endswith(".bicv/output")

    def test_reads_config_values(self, tmp_path):
        (tmp_path / ".bicv").mkdir()
        (tmp_path / ".bicv" / "common.json").write_text(
            json.dumps(
                {"output_root": str(tmp_path / "out"), "skills": {"jenkins_daily_analysis": "jda"}}
            ),
            encoding="utf-8",
        )
        with mock.patch("collect.Path.home", return_value=tmp_path):
            root, subdir = collect.load_run_root()
        assert root == str(tmp_path / "out")
        assert subdir == "jda"

    def test_corrupt_json_falls_back(self, tmp_path):
        (tmp_path / ".bicv").mkdir()
        (tmp_path / ".bicv" / "common.json").write_text("{not json", encoding="utf-8")
        with mock.patch("collect.Path.home", return_value=tmp_path):
            _, subdir = collect.load_run_root()
        assert subdir == collect.DEFAULT_SKILL_SUBDIR

    def test_partial_config_fills_defaults(self, tmp_path):
        (tmp_path / ".bicv").mkdir()
        (tmp_path / ".bicv" / "common.json").write_text("{}", encoding="utf-8")
        with mock.patch("collect.Path.home", return_value=tmp_path):
            root, subdir = collect.load_run_root()
        assert subdir == collect.DEFAULT_SKILL_SUBDIR
        assert root.endswith(".bicv/output")


# ===================================================================
# make_rundir
# ===================================================================


class TestMakeRundir:
    def test_creates_rundir_with_logs(self, tmp_path):
        rundir = collect.make_rundir(str(tmp_path), "sub")
        assert rundir.startswith(str(tmp_path / "sub"))
        assert Path(rundir).is_dir()
        assert (Path(rundir) / "logs").is_dir()


# ===================================================================
# run_jenkins_cli
# ===================================================================


class TestRunJenkinsCli:
    def test_command_with_system(self):
        with mock.patch("collect.subprocess.run") as m:
            m.return_value = _proc(stdout="{}")
            collect.run_jenkins_cli("/p/cli.py", ["list-jobs"], "prod")
        cmd = m.call_args.args[0]
        assert cmd[0] == sys.executable
        assert "/p/cli.py" in cmd
        assert "list-jobs" in cmd
        assert "--system" in cmd and "prod" in cmd

    def test_command_without_system(self):
        with mock.patch("collect.subprocess.run") as m:
            m.return_value = _proc()
            collect.run_jenkins_cli("/c", ["list-builds"])
        cmd = m.call_args.args[0]
        assert "--system" not in cmd


# ===================================================================
# parse_json_envelope
# ===================================================================


class TestParseJsonEnvelope:
    def test_returns_data(self):
        assert collect.parse_json_envelope('{"system":"d","data":[1,2]}') == [1, 2]

    def test_missing_data_returns_none(self):
        assert collect.parse_json_envelope('{"system":"d"}') is None


# ===================================================================
# should_skip_job
# ===================================================================


class TestShouldSkipJob:
    def test_disabled_skipped(self):
        assert collect.should_skip_job({"color": "disabled"}, False) is True

    def test_notbuilt_skipped(self):
        assert collect.should_skip_job({"color": "notbuilt"}, False) is True

    def test_blue_not_skipped(self):
        assert collect.should_skip_job({"color": "blue"}, False) is False

    def test_no_prefilter_never_skips(self):
        assert collect.should_skip_job({"color": "disabled"}, True) is False


# ===================================================================
# collect_one_job
# ===================================================================


def _fake_cli_factory(by_job: dict, *, list_jobs_error: bool = False):
    """Build a fake run_jenkins_cli returning per-job list-builds data."""

    def fake(cli, subcommand, system=None, timeout=180):
        if subcommand[0] == "list-builds":
            job = subcommand[2]
            return _proc(stdout=json.dumps({"system": "default", "data": by_job.get(job, [])}))
        return _proc(returncode=1, stderr="unexpected subcommand")

    return fake


class TestCollectOneJob:
    def test_ok_attaches_job(self):
        data = [{"number": 7, "result": "FAILURE", "timestamp": 1, "duration": 1, "url": "u"}]
        with mock.patch("collect.run_jenkins_cli", side_effect=_fake_cli_factory({"J": data})):
            status, payload = collect.collect_one_job("/c", None, "J", 24)
        assert status == "ok"
        assert payload[0]["job"] == "J"
        assert payload[0]["number"] == 7

    def test_empty(self):
        with mock.patch("collect.run_jenkins_cli", side_effect=_fake_cli_factory({"J": []})):
            status, payload = collect.collect_one_job("/c", None, "J", 24)
        assert status == "empty"
        assert payload is None

    def test_nonzero_returncode_is_error(self):
        with mock.patch("collect.run_jenkins_cli", return_value=_proc(returncode=2, stderr="boom")):
            status, payload = collect.collect_one_job("/c", None, "J", 24)
        assert status == "error"
        assert "exit 2" in payload and "boom" in payload

    def test_timeout_is_error(self):
        with mock.patch(
            "collect.run_jenkins_cli", side_effect=subprocess.TimeoutExpired(["x"], 180)
        ):
            status, payload = collect.collect_one_job("/c", None, "J", 24)
        assert status == "error" and payload == "timeout"

    def test_generic_exception_is_error(self):
        with mock.patch("collect.run_jenkins_cli", side_effect=OSError("nope")):
            status, payload = collect.collect_one_job("/c", None, "J", 24)
        assert status == "error" and "OSError" in payload

    def test_invalid_json_is_error(self):
        with mock.patch("collect.run_jenkins_cli", return_value=_proc(stdout="not json")):
            status, payload = collect.collect_one_job("/c", None, "J", 24)
        assert status == "error" and "invalid JSON" in payload

    def test_unexpected_shape_is_error(self):
        with mock.patch(
            "collect.run_jenkins_cli",
            return_value=_proc(stdout=json.dumps({"system": "d", "data": {"x": 1}})),
        ):
            status, payload = collect.collect_one_job("/c", None, "J", 24)
        assert status == "error" and "unexpected data shape" in payload

    def test_non_dict_builds_filtered(self):
        data = [{"number": 1}, "junk", 3]
        with mock.patch("collect.run_jenkins_cli", side_effect=_fake_cli_factory({"J": data})):
            status, payload = collect.collect_one_job("/c", None, "J", 24)
        assert status == "ok"
        assert len(payload) == 1 and payload[0]["number"] == 1


# ===================================================================
# cmd_collect
# ===================================================================


class TestCmdCollect:
    def _jobs_envelope(self, jobs):
        return _proc(stdout=json.dumps({"system": "default", "data": {"jobs": jobs}}))

    def test_full_pipeline_with_prefilter_and_errors(self, tmp_path, capsys):
        jobs = [
            {"name": "ACTIVE", "url": "u", "color": "blue"},
            {"name": "DEAD", "url": "u", "color": "disabled"},
            {"name": "BROKEN", "url": "u", "color": "red"},
        ]

        def fake(cli, subcommand, system=None, timeout=180):
            if subcommand[0] == "list-jobs":
                return self._jobs_envelope(jobs)
            if subcommand[0] == "list-builds":
                job = subcommand[2]
                if job == "ACTIVE":
                    return _proc(
                        stdout=json.dumps(
                            {
                                "system": "default",
                                "data": [
                                    {
                                        "number": 3,
                                        "result": "FAILURE",
                                        "timestamp": 3,
                                        "url": "u/3/",
                                    },
                                    {
                                        "number": 1,
                                        "result": "FAILURE",
                                        "timestamp": 1,
                                        "url": "u/1/",
                                    },
                                ],
                            }
                        )
                    )
                if job == "BROKEN":
                    return _proc(returncode=1, stderr="HTTP 404")
                return _proc(stdout=json.dumps({"system": "default", "data": []}))
            return _proc(returncode=1, stderr="nope")

        args = mock.MagicMock(
            cli="/c", system=None, since_hours=24, workers=4, no_prefilter=False, rundir=None
        )
        with (
            mock.patch("collect.run_jenkins_cli", side_effect=fake),
            mock.patch("collect.load_run_root", return_value=(str(tmp_path), "sub")),
        ):
            rc = collect.cmd_collect(args)

        assert rc == 0
        out = capsys.readouterr().out
        assert "jobs_total=3" in out and "prefilter_skipped=1" in out and "scanned=2" in out
        assert "failed_builds=2" in out and "errors=1" in out

        data = json.loads((tmp_path / "sub").glob("*/builds.json").__next__().read_text("utf-8"))
        assert [b["number"] for b in data["builds"]] == [1, 3]  # sorted by number
        assert data["builds"][0]["job"] == "ACTIVE"
        assert data["errors"] == [{"job": "BROKEN", "error": mock.ANY}]
        assert data["errors"][0]["error"].startswith("exit 1")
        assert data["prefilter"] == {
            "enabled": True,
            "skipped_count": 1,
            "skipped_colors": ["disabled"],
        }

    def test_no_prefilter_scans_all(self, tmp_path, capsys):
        jobs = [{"name": "DEAD", "url": "u", "color": "disabled"}]

        def fake(cli, subcommand, system=None, timeout=180):
            if subcommand[0] == "list-jobs":
                return self._jobs_envelope(jobs)
            return _proc(stdout=json.dumps({"system": "default", "data": []}))

        args = mock.MagicMock(
            cli="/c", system="prod", since_hours=12, workers=2, no_prefilter=True, rundir=None
        )
        with (
            mock.patch("collect.run_jenkins_cli", side_effect=fake),
            mock.patch("collect.load_run_root", return_value=(str(tmp_path), "sub")),
        ):
            rc = collect.cmd_collect(args)
        assert rc == 0
        out = capsys.readouterr().out
        assert "prefilter_skipped=0" in out and "scanned=1" in out
        data = json.loads((tmp_path / "sub").glob("*/builds.json").__next__().read_text("utf-8"))
        assert data["system"] == "prod"
        assert data["since_hours"] == 12
        assert data["prefilter"]["enabled"] is False

    def test_reuses_rundir(self, tmp_path):
        rundir = tmp_path / "existing"
        rundir.mkdir()

        def fake(cli, subcommand, system=None, timeout=180):
            if subcommand[0] == "list-jobs":
                return self._jobs_envelope([])
            return _proc(stdout=json.dumps({"system": "default", "data": []}))

        args = mock.MagicMock(
            cli="/c", system=None, since_hours=24, workers=2, no_prefilter=False, rundir=str(rundir)
        )
        with mock.patch("collect.run_jenkins_cli", side_effect=fake):
            rc = collect.cmd_collect(args)
        assert rc == 0
        assert (rundir / "builds.json").exists()

    def test_list_jobs_nonzero_returns_1(self, tmp_path, capsys):
        args = mock.MagicMock(
            cli="/c", system=None, since_hours=24, workers=2, no_prefilter=False, rundir=None
        )
        with (
            mock.patch("collect.run_jenkins_cli", return_value=_proc(returncode=1, stderr="nope")),
            mock.patch("collect.load_run_root", return_value=(str(tmp_path), "sub")),
        ):
            rc = collect.cmd_collect(args)
        assert rc == 1
        assert "list-jobs failed" in capsys.readouterr().err

    def test_list_jobs_timeout_returns_1(self, tmp_path, capsys):
        args = mock.MagicMock(
            cli="/c", system=None, since_hours=24, workers=2, no_prefilter=False, rundir=None
        )
        with (
            mock.patch(
                "collect.run_jenkins_cli", side_effect=subprocess.TimeoutExpired(["x"], 180)
            ),
            mock.patch("collect.load_run_root", return_value=(str(tmp_path), "sub")),
        ):
            rc = collect.cmd_collect(args)
        assert rc == 1
        assert "timeout" in capsys.readouterr().err

    def test_list_jobs_invalid_json_returns_1(self, tmp_path, capsys):
        args = mock.MagicMock(
            cli="/c", system=None, since_hours=24, workers=2, no_prefilter=False, rundir=None
        )
        with (
            mock.patch("collect.run_jenkins_cli", return_value=_proc(stdout="notjson")),
            mock.patch("collect.load_run_root", return_value=(str(tmp_path), "sub")),
        ):
            rc = collect.cmd_collect(args)
        assert rc == 1
        assert "invalid JSON" in capsys.readouterr().err

    def test_list_jobs_non_list_data_treated_empty(self, tmp_path, capsys):
        # data 存在但不是 list（理论上不会发生，仍要兜底为空而非崩溃）
        args = mock.MagicMock(
            cli="/c", system=None, since_hours=24, workers=2, no_prefilter=False, rundir=None
        )
        with (
            mock.patch(
                "collect.run_jenkins_cli",
                return_value=_proc(stdout=json.dumps({"system": "d", "data": {"jobs": "x"}})),
            ),
            mock.patch("collect.load_run_root", return_value=(str(tmp_path), "sub")),
        ):
            rc = collect.cmd_collect(args)
        assert rc == 0
        assert "jobs_total=0" in capsys.readouterr().out


# ===================================================================
# build_parser / main
# ===================================================================


class TestParserAndMain:
    def test_required_cli(self):
        with mock.patch.object(sys, "argv", ["collect.py"]):
            try:
                collect.build_parser().parse_args()
            except SystemExit as exc:
                assert exc.code != 0
            else:
                raise AssertionError("expected SystemExit for missing --cli")

    def test_defaults(self):
        with mock.patch.object(sys, "argv", ["collect.py", "--cli", "/c"]):
            args = collect.build_parser().parse_args()
        assert args.cli == "/c"
        assert args.since_hours == 24 and args.workers == 20 and args.no_prefilter is False

    def test_main_invokes_cmd_collect(self):
        args = mock.MagicMock()
        with (
            mock.patch("collect.build_parser") as bp,
            mock.patch("collect.cmd_collect", return_value=7) as cc,
        ):
            bp.return_value.parse_args.return_value = args
            assert collect.main() == 7
        cc.assert_called_once_with(args)
