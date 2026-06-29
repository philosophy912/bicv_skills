"""Tests for render_report.py — config/IO, helpers, report builder, CLI."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from unittest import mock

import pytest
import render_report as rr

# ---------------------------------------------------------------------------
# Fixtures / payloads
# ---------------------------------------------------------------------------


def _submissions_payload() -> dict:
    return {
        "window": {"start": "2026-06-22 00:00:00", "end": "2026-06-26 23:59:59"},
        "zentao": {
            "instance_id": 1,
            "total": 3,
            "by_user": {"郭礼香": 2, "周嘉敏": 1},
            "by_project": {"B30X-F09": 2, "N53TB": 1},
            "bugs": [],
        },
        "redmine": {
            "instance_id": 2,
            "total": 1,
            "by_user": {"郭礼香": 1},
            "by_project": {"B30X-F09": 1},
            "issues": [],
        },
    }


def _overdue_payload() -> dict:
    return {
        "generated_at": "2026-06-26 10:00:00",
        "overdue_days": 7,
        "zentao": {
            "instance_id": 1,
            "total": 2,
            "by_user": {"郭礼香": 2},
            "bugs": [
                {
                    "id": 12345,
                    "projectName": "B30X-F09",
                    "module": "carlink",
                    "assignedTo": "郭礼香",
                    "days_since_action": 16,
                },
            ],
        },
        "redmine": {
            "instance_id": 2,
            "total": 1,
            "by_user": {"王五": 1},
            "issues": [
                {
                    "issue_id": 99,
                    "project_name": "P",
                    "subject": "S",
                    "assigned_to_name": "王五",
                    "days_since_action": 20,
                },
            ],
        },
    }


# ---------------------------------------------------------------------------
# Pure helpers
# ===========================================================================


class TestPureHelpers:
    def test_merge_counter(self):
        assert rr.merge_counter({"a": 2}, {"a": 1, "b": 3}, None) == {"a": 3, "b": 3}

    def test_short_window_formats(self):
        d = {"window": {"start": "2026-06-22 00:00:00", "end": "2026-06-26 23:59:59"}}
        assert rr._short_window(d) == "06-22~06-26"

    def test_short_window_empty(self):
        assert rr._short_window({}) == ""

    def test_fmt_pct_normal(self):
        assert rr._fmt_pct(1, 4) == "25%"

    def test_fmt_pct_zero_total(self):
        assert rr._fmt_pct(0, 0) == "0%"

    def test_md_cell_escapes_pipe_and_newline(self):
        # | 转义、换行转空格，避免破坏 Markdown 表格
        assert rr._md_cell("a|b") == "a\\|b"
        assert rr._md_cell("a\nb") == "a b"
        assert rr._md_cell(5) == "5"

    def test_overdue_rows_merge_id_prefix_and_sort(self):
        rows = rr._overdue_rows(_overdue_payload())
        assert len(rows) == 2
        assert rows[0]["id"] == "R-99"  # 20 天 > 16 天
        assert rows[1]["id"] == "Z-12345"

    def test_overdue_rows_non_numeric_days(self):
        data = {
            "zentao": {
                "bugs": [
                    {
                        "id": 1,
                        "projectName": "P",
                        "module": "M",
                        "assignedTo": "A",
                        "days_since_action": "N/A",
                    }
                ]
            }
        }
        assert rr._overdue_rows(data)[0]["days"] == 0


# ---------------------------------------------------------------------------
# resolve_output_dir
# ===========================================================================


class TestResolveOutputDir:
    def test_custom(self, tmp_path):
        d = rr.resolve_output_dir(str(tmp_path / "out"))
        assert d.exists() and d == tmp_path / "out"

    def test_common_config_with_mapping(self, tmp_path):
        bicv = tmp_path / ".bicv"
        bicv.mkdir()
        (bicv / "common.json").write_text(
            json.dumps({"output_root": str(tmp_path / "root"), "skills": {"bug_analysis": "bda"}})
        )
        with mock.patch.object(rr.Path, "home", return_value=tmp_path):
            d = rr.resolve_output_dir(None)
        assert d == tmp_path / "root" / "bda" and d.exists()

    def test_default_subdir_when_unmapped(self, tmp_path):
        bicv = tmp_path / ".bicv"
        bicv.mkdir()
        (bicv / "common.json").write_text(json.dumps({"output_root": str(tmp_path / "root")}))
        with mock.patch.object(rr.Path, "home", return_value=tmp_path):
            d = rr.resolve_output_dir(None)
        assert d == tmp_path / "root" / "bug_analysis"

    def test_missing_output_root_raises(self, tmp_path):
        bicv = tmp_path / ".bicv"
        bicv.mkdir()
        (bicv / "common.json").write_text(json.dumps({}))
        with mock.patch.object(rr.Path, "home", return_value=tmp_path):
            with pytest.raises(rr.ReportError, match="output_root"):
                rr.resolve_output_dir(None)

    def test_missing_config_raises(self, tmp_path):
        with mock.patch.object(rr.Path, "home", return_value=tmp_path):
            with pytest.raises(rr.ReportError, match="配置文件不存在"):
                rr.resolve_output_dir(None)

    def test_bad_json_raises(self, tmp_path):
        bicv = tmp_path / ".bicv"
        bicv.mkdir()
        (bicv / "common.json").write_text("{bad")
        with mock.patch.object(rr.Path, "home", return_value=tmp_path):
            with pytest.raises(rr.ReportError, match="JSON"):
                rr.resolve_output_dir(None)


# ---------------------------------------------------------------------------
# read_json_file
# ===========================================================================


class TestReadJson:
    def test_ok(self, tmp_path):
        f = tmp_path / "a.json"
        f.write_text(json.dumps({"x": 1}))
        assert rr.read_json_file(str(f)) == {"x": 1}

    def test_missing_raises(self):
        with pytest.raises(rr.ReportError, match="不存在"):
            rr.read_json_file("/no/such/file.json")

    def test_bad_json_raises(self, tmp_path):
        f = tmp_path / "a.json"
        f.write_text("{bad")
        with pytest.raises(rr.ReportError, match="JSON"):
            rr.read_json_file(str(f))


# ---------------------------------------------------------------------------
# build_report
# ===========================================================================


class TestBuildReport:
    def test_submissions_only(self):
        md = rr.build_report(_submissions_payload(), None)
        assert "缺陷分析报告" in md
        assert "本周提交情况" in md
        assert "按提交人" in md and "按项目" in md
        assert "超期" not in md

    def test_overdue_only_has_ids(self):
        md = rr.build_report(None, _overdue_payload())
        assert "超期未处理" in md
        assert "缺陷ID" in md
        assert "Z-12345" in md
        assert "R-99" in md
        assert "本周提交" not in md

    def test_both_sections(self):
        md = rr.build_report(_submissions_payload(), _overdue_payload())
        assert "本周提交情况" in md and "超期未处理" in md

    def test_empty_only_title(self):
        md = rr.build_report(None, None)
        assert "缺陷分析报告" in md
        assert "本周提交" not in md
        assert "超期" not in md


# ---------------------------------------------------------------------------
# cmd_report / main
# ===========================================================================


def _ns(**kw) -> argparse.Namespace:
    base = {"submissions": None, "overdue": None, "out": None}
    base.update(kw)
    return argparse.Namespace(**base)


class TestCmdReport:
    def test_no_input_returns_1(self):
        assert rr.cmd_report(_ns()) == 1

    def test_outdir_error_returns_1(self):
        with mock.patch.object(rr, "resolve_output_dir", side_effect=rr.ReportError("no dir")):
            assert rr.cmd_report(_ns(submissions="x")) == 1

    def test_input_file_error_returns_1(self, tmp_path):
        with mock.patch.object(rr, "resolve_output_dir", return_value=tmp_path):
            assert rr.cmd_report(_ns(submissions="/nope.json")) == 1

    def test_success_writes_report(self, tmp_path, capsys):
        sub = tmp_path / "s.json"
        sub.write_text(json.dumps(_submissions_payload()))
        with mock.patch.object(rr, "resolve_output_dir", return_value=tmp_path):
            code = rr.cmd_report(_ns(submissions=str(sub)))
        assert code == 0
        out = json.loads(capsys.readouterr().out)
        report = Path(out["report_path"])
        assert report.exists()
        assert "本周提交情况" in report.read_text(encoding="utf-8")


class TestMain:
    def test_main_success(self, tmp_path):
        sub = tmp_path / "s.json"
        sub.write_text(json.dumps(_submissions_payload()))
        with mock.patch.object(rr, "resolve_output_dir", return_value=tmp_path):
            assert rr.main(["--submissions", str(sub), "--out", str(tmp_path)]) == 0

    def test_main_dir_error(self):
        with mock.patch.object(rr, "resolve_output_dir", side_effect=rr.ReportError("x")):
            assert rr.main(["--submissions", "a.json"]) == 1


def test_build_parser_registers_all_args():
    ns = rr.build_parser().parse_args(["--submissions", "a", "--overdue", "b", "--out", "c"])
    assert ns.submissions == "a" and ns.overdue == "b" and ns.out == "c"
