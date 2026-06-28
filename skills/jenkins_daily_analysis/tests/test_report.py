"""Tests for report.py — analyses merge, representative picking, nodes, rendering, CLI."""

from __future__ import annotations

import json
import subprocess
from unittest import mock

import report


def _proc(stdout: str = "", stderr: str = "", returncode: int = 0) -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(args=[], returncode=returncode, stdout=stdout, stderr=stderr)


def _build(job: str, number: int, **extra) -> dict:
    base = {"job": job, "number": number, "result": "FAILURE", "url": f"u/{number}/"}
    base.update(extra)
    return base


# ===================================================================
# load_analyses
# ===================================================================


class TestLoadAnalyses:
    def test_missing_file_returns_empty(self, tmp_path):
        assert report.load_analyses(str(tmp_path / "nope.json")) == {}

    def test_loads_entries(self, tmp_path):
        p = tmp_path / "a.json"
        p.write_text(
            json.dumps([{"job": "J", "number": 1, "category": "scm"}, {"job": "K", "number": 2}]),
            encoding="utf-8",
        )
        out = report.load_analyses(str(p))
        assert set(out) == {("J", 1), ("K", 2)}

    def test_non_list_raises(self, tmp_path):
        p = tmp_path / "a.json"
        p.write_text(json.dumps({"not": "list"}), encoding="utf-8")
        try:
            report.load_analyses(str(p))
        except ValueError as exc:
            assert "list" in str(exc)
        else:
            raise AssertionError("expected ValueError")

    def test_entries_missing_keys_skipped(self, tmp_path):
        p = tmp_path / "a.json"
        p.write_text(json.dumps([{"category": "scm"}, {"job": "J", "number": 1}]), encoding="utf-8")
        out = report.load_analyses(str(p))
        assert list(out) == [("J", 1)]


# ===================================================================
# merge_builds
# ===================================================================


class TestMergeBuilds:
    def test_with_analysis(self):
        builds = [_build("J", 1)]
        analyses = {
            ("J", 1): {
                "category": "scm",
                "confidence": "high",
                "evidence": "ev",
                "log_excerpt": "ex",
            }
        }
        report.merge_builds(builds, analyses)
        assert builds[0]["category"] == "scm" and builds[0]["evidence"] == "ev"

    def test_missing_analysis_defaults_unknown(self):
        builds = [_build("J", 1)]
        report.merge_builds(builds, {})
        assert builds[0]["category"] == "unknown"
        assert builds[0]["confidence"] == "low"
        assert "未判定" in builds[0]["evidence"]


# ===================================================================
# pick_representatives
# ===================================================================


class TestPickRepresentatives:
    def test_single_job_caps_at_limit(self):
        builds = [_build("J", n) for n in range(1, 8)]
        picked = report.pick_representatives(builds, limit=5)
        assert len(picked) == 5
        assert {b["number"] for b in picked} == {1, 2, 3, 4, 5}

    def test_every_job_represented(self):
        # jobA 6 条 + jobB 1 条，limit=5 → 必须含 jobB
        builds = [_build("jobA", n) for n in range(1, 7)] + [_build("jobB", 1)]
        picked = report.pick_representatives(builds, limit=5)
        assert len(picked) == 5
        assert any(b["job"] == "jobB" for b in picked)
        assert sum(1 for b in picked if b["job"] == "jobA") == 4

    def test_fewer_than_limit_returns_all(self):
        builds = [_build("J", 1), _build("J", 2)]
        picked = report.pick_representatives(builds, limit=5)
        assert len(picked) == 2

    def test_empty(self):
        assert report.pick_representatives([], limit=5) == []

    def test_more_jobs_than_limit_breaks_first_round(self):
        # 6 个 job 各 1 条，limit=5 → 第一轮取满 5 个 job 即停
        builds = [_build(f"job{n}", 1) for n in range(6)]
        picked = report.pick_representatives(builds, limit=5)
        assert len(picked) == 5
        assert len({b["job"] for b in picked}) == 5

    def test_fill_order_by_failure_count(self):
        # 三个 job 各多条，limit=4：每 job 1 条占 3 席，剩 1 席给失败最多的 jobA
        builds = [_build("jobA", n) for n in range(1, 4)]
        builds += [_build("jobB", n) for n in range(1, 3)]
        builds += [_build("jobC", 1)]
        picked = report.pick_representatives(builds, limit=4)
        assert len(picked) == 4
        # jobA 应出现两次（3 条，失败最多）
        assert sum(1 for b in picked if b["job"] == "jobA") == 2


# ===================================================================
# fetch_nodes
# ===================================================================


class TestFetchNodes:
    def _envelope(self, computers, total=3):
        return _proc(
            stdout=json.dumps({"system": "d", "data": {"total": total, "computers": computers}})
        )

    def test_normal(self):
        computers = [
            {"name": "n1", "offline": False, "temporarilyOffline": False},
            {
                "name": "n2",
                "offline": True,
                "temporarilyOffline": False,
                "offlineCauseReason": "broken",
            },
            {"name": "n3", "offline": True, "temporarilyOffline": True},
        ]
        with mock.patch("report.run_jenkins_cli", return_value=self._envelope(computers)):
            result = report.fetch_nodes("/c", None)
        assert result is not None
        total, sys_off, manual = result
        assert total == 3 and len(sys_off) == 1 and manual == 1
        assert sys_off[0]["name"] == "n2"

    def test_timeout_returns_none(self):
        with mock.patch(
            "report.run_jenkins_cli", side_effect=subprocess.TimeoutExpired(["x"], 180)
        ):
            assert report.fetch_nodes("/c", None) is None

    def test_exception_returns_none(self):
        with mock.patch("report.run_jenkins_cli", side_effect=OSError("x")):
            assert report.fetch_nodes("/c", None) is None

    def test_nonzero_returns_none(self):
        with mock.patch("report.run_jenkins_cli", return_value=_proc(returncode=1, stderr="e")):
            assert report.fetch_nodes("/c", None) is None

    def test_invalid_json_returns_none(self):
        with mock.patch("report.run_jenkins_cli", return_value=_proc(stdout="notjson")):
            assert report.fetch_nodes("/c", None) is None

    def test_non_dict_data_returns_none(self):
        with mock.patch(
            "report.run_jenkins_cli",
            return_value=_proc(stdout=json.dumps({"system": "d", "data": []})),
        ):
            assert report.fetch_nodes("/c", None) is None


# ===================================================================
# render_report_md
# ===================================================================


class TestRenderReportMd:
    def _report(self, builds, nodes=None, since_hours=24):
        cat = {}
        from collections import Counter

        c = Counter(b.get("category", "unknown") for b in builds)
        for k in report.CATEGORIES:
            cat[k] = c.get(k, 0)
        r = {
            "generated_at": "2026-06-28T22:00:00",
            "window": {"start": "2026-06-27T22:00:00", "end": "2026-06-28T22:00:00"},
            "system": "default",
            "since_hours": since_hours,
            "summary": {"total_failed": len(builds), "by_category": cat, "errors": 0},
            "builds": builds,
        }
        if nodes is not None:
            r["nodes"] = nodes
        return r

    def test_empty_builds_and_no_nodes(self):
        md = report.render_report_md(self._report([]), "/r")
        assert (
            "总失败数 | 0 | 0 | 0 | 0 | 0 | 0" in md.replace("\n", " ").replace("| ", "|", 1)
            or "0 | 0 | 0 | 0 | 0 | 0" in md
        )
        assert "（无）" in md
        assert "未执行节点检查" in md

    def test_scm_full_and_other_representatives(self):
        builds = [
            {
                "job": "SCM",
                "number": n,
                "result": "FAILURE",
                "url": "u",
                "category": "scm",
                "evidence": "ev",
                "confidence": "high",
            }
            for n in range(1, 4)
        ]
        # other: jobA 6 + jobB 1 → jobB 必须进代表
        builds += [
            {
                "job": "jobA",
                "number": n,
                "result": "FAILURE",
                "url": "u",
                "category": "other",
                "evidence": "ea",
                "confidence": "high",
            }
            for n in range(1, 7)
        ]
        builds += [
            {
                "job": "jobB",
                "number": 1,
                "result": "FAILURE",
                "url": "u",
                "category": "other",
                "evidence": "eb",
                "confidence": "high",
            }
        ]
        md = report.render_report_md(self._report(builds), "/r")
        # scm 全列 3 条
        assert "scm 失败明细（3 条）" in md
        # other 标题含「此处列代表 5 条」
        assert "other 失败（7 条，此处列代表 5 条）" in md
        # jobB 出现在代表里
        assert "| jobB |" in md
        # 完整 7 条见 report.json 提示
        assert "完整 7 条见" in md

    def test_nodes_with_details(self):
        nodes = {
            "total": 60,
            "details": [{"name": "auto_test_2", "offlineCauseReason": "broken", "numExecutors": 1}],
            "manual_offline_count": 9,
        }
        md = report.render_report_md(self._report([], nodes=nodes), "/r")
        assert "| 60 | 1 | 9 |" in md
        assert "| auto_test_2 | broken | 1 |" in md

    def test_nodes_empty_details(self):
        nodes = {"total": 60, "details": [], "manual_offline_count": 0}
        md = report.render_report_md(self._report([], nodes=nodes), "/r")
        assert "（无系统自发掉线节点）" in md


# ===================================================================
# cmd_report
# ===================================================================


class TestCmdReport:
    def _setup(self, tmp_path, builds, analyses=None):
        (tmp_path / "builds.json").write_text(
            json.dumps(
                {
                    "generated_at": "2026-06-28T22:00:00",
                    "window": {"start": "s", "end": "e"},
                    "system": "default",
                    "since_hours": 24,
                    "builds": builds,
                    "errors": [],
                }
            ),
            encoding="utf-8",
        )
        if analyses is not None:
            (tmp_path / "analyses.json").write_text(json.dumps(analyses), encoding="utf-8")

    def test_full_pipeline_with_nodes(self, tmp_path, capsys):
        builds = [_build("J", 1), _build("K", 2)]
        analyses = [
            {
                "job": "J",
                "number": 1,
                "category": "scm",
                "confidence": "high",
                "evidence": "ev",
                "log_excerpt": "ex",
            }
        ]
        self._setup(tmp_path, builds, analyses)

        node_env = _proc(
            stdout=json.dumps(
                {
                    "system": "d",
                    "data": {
                        "total": 2,
                        "computers": [
                            {
                                "name": "n1",
                                "offline": True,
                                "temporarilyOffline": False,
                                "offlineCauseReason": "x",
                                "numExecutors": 1,
                            }
                        ],
                    },
                }
            )
        )
        args = mock.MagicMock(rundir=str(tmp_path), analyses=None, cli="/c", system=None)
        with mock.patch("report.run_jenkins_cli", return_value=node_env):
            rc = report.cmd_report(args)
        assert rc == 0
        out = capsys.readouterr().out
        assert "by_category=" in out and "nodes:" in out

        rep = json.loads((tmp_path / "report.json").read_text("utf-8"))
        assert rep["summary"]["by_category"]["scm"] == 1
        assert rep["summary"]["by_category"]["unknown"] == 1  # K 缺判定
        assert rep["nodes"]["total"] == 2
        assert (tmp_path / "report.md").exists()

    def test_no_cli_no_nodes(self, tmp_path, capsys):
        builds = [_build("J", 1)]
        analyses = [
            {
                "job": "J",
                "number": 1,
                "category": "compile",
                "confidence": "high",
                "evidence": "ev",
                "log_excerpt": "ex",
            }
        ]
        self._setup(tmp_path, builds, analyses)
        args = mock.MagicMock(rundir=str(tmp_path), analyses=None, cli=None, system=None)
        rc = report.cmd_report(args)
        assert rc == 0
        rep = json.loads((tmp_path / "report.json").read_text("utf-8"))
        assert "nodes" not in rep

    def test_missing_builds_json(self, tmp_path, capsys):
        args = mock.MagicMock(rundir=str(tmp_path), analyses=None, cli=None, system=None)
        rc = report.cmd_report(args)
        assert rc == 1
        assert "builds.json not found" in capsys.readouterr().err

    def test_builds_not_list(self, tmp_path, capsys):
        (tmp_path / "builds.json").write_text(json.dumps({"builds": "x"}), encoding="utf-8")
        args = mock.MagicMock(rundir=str(tmp_path), analyses=None, cli=None, system=None)
        rc = report.cmd_report(args)
        assert rc == 1
        assert "no builds[]" in capsys.readouterr().err

    def test_invalid_analyses(self, tmp_path, capsys):
        self._setup(tmp_path, [_build("J", 1)])
        (tmp_path / "analyses.json").write_text("{not list", encoding="utf-8")
        args = mock.MagicMock(rundir=str(tmp_path), analyses=None, cli=None, system=None)
        rc = report.cmd_report(args)
        assert rc == 1
        assert "analyses.json invalid" in capsys.readouterr().err

    def test_missing_analyses_all_unknown(self, tmp_path):
        self._setup(tmp_path, [_build("J", 1)])  # 不写 analyses.json
        args = mock.MagicMock(rundir=str(tmp_path), analyses=None, cli=None, system=None)
        rc = report.cmd_report(args)
        assert rc == 0
        rep = json.loads((tmp_path / "report.json").read_text("utf-8"))
        assert rep["summary"]["by_category"]["unknown"] == 1


# ===================================================================
# build_parser / main
# ===================================================================


class TestParserAndMain:
    def test_required_rundir(self):
        import sys

        with mock.patch.object(sys, "argv", ["report.py"]):
            try:
                report.build_parser().parse_args()
            except SystemExit as exc:
                assert exc.code != 0
            else:
                raise AssertionError("expected SystemExit")

    def test_defaults(self):
        import sys

        with mock.patch.object(sys, "argv", ["report.py", "--rundir", "/r"]):
            args = report.build_parser().parse_args()
        assert args.rundir == "/r" and args.cli is None and args.analyses is None

    def test_main_invokes_cmd_report(self):
        args = mock.MagicMock()
        with (
            mock.patch("report.build_parser") as bp,
            mock.patch("report.cmd_report", return_value=0) as cc,
        ):
            bp.return_value.parse_args.return_value = args
            assert report.main() == 0
        cc.assert_called_once_with(args)
