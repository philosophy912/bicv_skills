"""Tests for bug_analysis.py — config loading, window resolution,
SQL helpers, sub-commands (submissions/overdue/severe/closures), and CLI."""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from decimal import Decimal
from unittest import mock

import bug_analysis
import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _valid_config(**overrides):
    """Build a valid analysis config dict (already-loaded shape)."""
    cfg = {
        "zentao": {
            "instance_id": 1,
            "users": ["张三-NJD-SW", "李四-NJD-SW"],
            "ignored_projects": [],
        },
        "redmine": {
            "instance_id": 2,
            "users": ["王五_LM"],
            "ignored_projects": [],
        },
    }
    cfg.update(overrides)
    return cfg


def _mock_conn(rows_per_query=None):
    """Build a mock MySQL connection. rows_per_query is a list of row lists
    for successive queries; default returns [] for each execute."""
    conn = mock.MagicMock()
    conn.is_connected.return_value = True

    cursor = mock.MagicMock()
    if rows_per_query is not None:
        cursor.fetchall.side_effect = rows_per_query
    else:
        cursor.fetchall.return_value = []
    conn.cursor.return_value = cursor
    return conn, cursor


def _write_config(tmp_path, cfg_dict):
    bicv = tmp_path / ".bicv"
    bicv.mkdir(exist_ok=True)
    (bicv / "bug_analysis.json").write_text(json.dumps(cfg_dict), encoding="utf-8")


# ---------------------------------------------------------------------------
# Config loading
# ===========================================================================


class TestLoadAnalysisConfig:
    def test_valid_config(self, tmp_path):
        _write_config(tmp_path, _valid_config())
        with mock.patch.object(bug_analysis.Path, "home", return_value=tmp_path):
            result = bug_analysis.load_analysis_config()
        assert result["zentao"]["users"] == ["张三-NJD-SW", "李四-NJD-SW"]
        # ignored_projects 缺省补空列表
        assert result["zentao"]["ignored_projects"] == []

    def test_valid_config_with_utf8_bom(self, tmp_path):
        # Windows PowerShell 保存的 bug_analysis.json 常带 BOM，读取侧用 utf-8-sig 自动剥离。
        bicv = tmp_path / ".bicv"
        bicv.mkdir()
        (bicv / "bug_analysis.json").write_text("﻿" + json.dumps(_valid_config()), encoding="utf-8")
        with mock.patch.object(bug_analysis.Path, "home", return_value=tmp_path):
            result = bug_analysis.load_analysis_config()
        assert result["zentao"]["users"] == ["张三-NJD-SW", "李四-NJD-SW"]

    def test_missing_config_file_raises(self, tmp_path):
        with (
            mock.patch.object(bug_analysis.Path, "home", return_value=tmp_path),
            pytest.raises(bug_analysis.ConfigError, match="配置文件不存在"),
        ):
            bug_analysis.load_analysis_config()

    def test_invalid_json_raises(self, tmp_path):
        _write_config(tmp_path, _valid_config())
        (tmp_path / ".bicv" / "bug_analysis.json").write_text("{bad json", encoding="utf-8")
        with (
            mock.patch.object(bug_analysis.Path, "home", return_value=tmp_path),
            pytest.raises(bug_analysis.ConfigError, match="JSON 格式错误"),
        ):
            bug_analysis.load_analysis_config()

    def test_missing_zentao_section_raises(self, tmp_path):
        _write_config(tmp_path, {"redmine": {"instance_id": 2, "users": ["x"]}})
        with (
            mock.patch.object(bug_analysis.Path, "home", return_value=tmp_path),
            pytest.raises(bug_analysis.ConfigError, match="缺少 'zentao'"),
        ):
            bug_analysis.load_analysis_config()

    def test_missing_redmine_section_raises(self, tmp_path):
        _write_config(tmp_path, {"zentao": {"instance_id": 1, "users": ["x"]}})
        with (
            mock.patch.object(bug_analysis.Path, "home", return_value=tmp_path),
            pytest.raises(bug_analysis.ConfigError, match="缺少 'redmine'"),
        ):
            bug_analysis.load_analysis_config()

    def test_missing_instance_id_raises(self, tmp_path):
        _write_config(
            tmp_path,
            {
                "zentao": {"users": ["x"]},
                "redmine": {"instance_id": 2, "users": ["y"]},
            },
        )
        with (
            mock.patch.object(bug_analysis.Path, "home", return_value=tmp_path),
            pytest.raises(bug_analysis.ConfigError, match="instance_id 是必填项"),
        ):
            bug_analysis.load_analysis_config()

    def test_empty_users_raises(self, tmp_path):
        _write_config(
            tmp_path,
            {
                "zentao": {"instance_id": 1, "users": []},
                "redmine": {"instance_id": 2, "users": ["y"]},
            },
        )
        with (
            mock.patch.object(bug_analysis.Path, "home", return_value=tmp_path),
            pytest.raises(bug_analysis.ConfigError, match="users 必须是非空列表"),
        ):
            bug_analysis.load_analysis_config()

    def test_users_not_list_raises(self, tmp_path):
        _write_config(
            tmp_path,
            {
                "zentao": {"instance_id": 1, "users": "张三"},
                "redmine": {"instance_id": 2, "users": ["y"]},
            },
        )
        with (
            mock.patch.object(bug_analysis.Path, "home", return_value=tmp_path),
            pytest.raises(bug_analysis.ConfigError, match="users 必须是非空列表"),
        ):
            bug_analysis.load_analysis_config()

    def test_users_whitespace_stripped(self, tmp_path):
        _write_config(
            tmp_path,
            {
                "zentao": {"instance_id": 1, "users": ["  张三  ", "李四", ""]},
                "redmine": {"instance_id": 2, "users": ["y"]},
            },
        )
        with mock.patch.object(bug_analysis.Path, "home", return_value=tmp_path):
            result = bug_analysis.load_analysis_config()
        assert result["zentao"]["users"] == ["张三", "李四"]

    def test_ignored_projects_not_list_raises(self, tmp_path):
        _write_config(
            tmp_path,
            {
                "zentao": {"instance_id": 1, "users": ["x"], "ignored_projects": "僵尸"},
                "redmine": {"instance_id": 2, "users": ["y"]},
            },
        )
        with (
            mock.patch.object(bug_analysis.Path, "home", return_value=tmp_path),
            pytest.raises(bug_analysis.ConfigError, match="ignored_projects 必须是列表"),
        ):
            bug_analysis.load_analysis_config()

    def test_overdue_days_in_config_ignored(self, tmp_path):
        # overdue_days 已改为固定常量，配置里残留该字段不再校验、不影响加载
        cfg = _valid_config()
        cfg["overdue_days"] = 999
        _write_config(tmp_path, cfg)
        with mock.patch.object(bug_analysis.Path, "home", return_value=tmp_path):
            result = bug_analysis.load_analysis_config()
        assert "overdue_days" not in result or result.get("overdue_days") == 999


# ---------------------------------------------------------------------------
# get_mysql_connection
# ===========================================================================


class TestGetMysqlConnection:
    def _write_mysql_config(self, tmp_path, systems):
        bicv = tmp_path / ".bicv"
        bicv.mkdir(exist_ok=True)
        (bicv / "mysql.json").write_text(json.dumps({"systems": systems}), encoding="utf-8")

    def test_successful_connection(self, tmp_path):
        self._write_mysql_config(
            tmp_path,
            {
                "ticket": {
                    "host": "h",
                    "port": 9999,
                    "database": "ticket",
                    "username": "u",
                    "password": "p",
                }
            },
        )
        with (
            mock.patch.object(bug_analysis.Path, "home", return_value=tmp_path),
            mock.patch("bug_analysis.mysql.connector.connect") as m,
        ):
            m.return_value = "CONN"
            result = bug_analysis.get_mysql_connection(system_name="ticket")
        assert result == "CONN"
        assert m.call_args.kwargs["host"] == "h"
        assert m.call_args.kwargs["database"] == "ticket"
        assert m.call_args.kwargs["ssl_disabled"] is True

    def test_system_not_found_raises(self, tmp_path):
        self._write_mysql_config(tmp_path, {"other": {"host": "h", "username": "u"}})
        with (
            mock.patch.object(bug_analysis.Path, "home", return_value=tmp_path),
            pytest.raises(bug_analysis.ConfigError, match="不存在"),
        ):
            bug_analysis.get_mysql_connection(system_name="ticket")

    def test_empty_systems_raises(self, tmp_path):
        self._write_mysql_config(tmp_path, {})
        with (
            mock.patch.object(bug_analysis.Path, "home", return_value=tmp_path),
            pytest.raises(bug_analysis.ConfigError, match="systems 字典为空"),
        ):
            bug_analysis.get_mysql_connection(system_name="ticket")

    def test_missing_host_raises(self, tmp_path):
        self._write_mysql_config(tmp_path, {"ticket": {"username": "u"}})
        with (
            mock.patch.object(bug_analysis.Path, "home", return_value=tmp_path),
            pytest.raises(bug_analysis.ConfigError, match="缺少 host"),
        ):
            bug_analysis.get_mysql_connection(system_name="ticket")

    def test_connection_error_raises(self, tmp_path):
        self._write_mysql_config(
            tmp_path, {"ticket": {"host": "h", "username": "u", "password": "p"}}
        )
        with (
            mock.patch.object(bug_analysis.Path, "home", return_value=tmp_path),
            mock.patch("bug_analysis.mysql.connector.connect") as m,
        ):
            m.side_effect = bug_analysis.MySQLError("refused")
            with pytest.raises(bug_analysis.ConfigError, match="MySQL 连接失败"):
                bug_analysis.get_mysql_connection(system_name="ticket")

    def test_uses_default_database_when_missing(self, tmp_path):
        self._write_mysql_config(tmp_path, {"ticket": {"host": "h", "username": "u"}})
        with (
            mock.patch.object(bug_analysis.Path, "home", return_value=tmp_path),
            mock.patch("bug_analysis.mysql.connector.connect") as m,
        ):
            m.return_value = "CONN"
            bug_analysis.get_mysql_connection(system_name="ticket")
        assert m.call_args.kwargs["database"] == "ticket"


# ---------------------------------------------------------------------------
# _DecimalEncoder
# ===========================================================================


class TestDecimalEncoder:
    def test_decimal_int(self):
        raw = json.dumps({"v": Decimal("10")}, cls=bug_analysis._DecimalEncoder)
        assert json.loads(raw) == {"v": 10}

    def test_decimal_float(self):
        raw = json.dumps({"v": Decimal("3.14")}, cls=bug_analysis._DecimalEncoder)
        assert json.loads(raw) == {"v": 3.14}

    def test_datetime_to_string(self):
        dt = datetime(2026, 6, 26, 10, 0, 0)
        raw = json.dumps({"t": dt}, cls=bug_analysis._DecimalEncoder)
        assert json.loads(raw) == {"t": "2026-06-26 10:00:00"}

    def test_non_serialisable_raises_typeerror(self):
        with pytest.raises(TypeError):
            json.dumps({"x": object()}, cls=bug_analysis._DecimalEncoder)


# ---------------------------------------------------------------------------
# _in_clause
# ===========================================================================


class TestInClause:
    def test_basic(self):
        result = bug_analysis._in_clause(["张三", "李四"])
        assert result == "('张三', '李四')"

    def test_escape_single_quote(self):
        result = bug_analysis._in_clause(["O'Brien"])
        assert result == "('O\\'Brien')"

    def test_escape_backslash(self):
        result = bug_analysis._in_clause(["a\\b"])
        assert result == "('a\\\\b')"

    def test_empty_list(self):
        assert bug_analysis._in_clause([]) == "()"


# ---------------------------------------------------------------------------
# project exclusion clauses
# ===========================================================================


class TestProjectExclusion:
    def test_inactive_zentao_clause(self):
        s = bug_analysis._exclude_inactive_project_clause("zentao", 1, "b", "projectName")
        assert "NOT EXISTS" in s
        assert "p.system_type = 'zentao'" in s
        assert "p.instance_id = 1" in s
        assert "TRIM(b.projectName)" in s
        assert "p.is_active = 0" in s

    def test_inactive_redmine_clause_uses_project_name_col(self):
        s = bug_analysis._exclude_inactive_project_clause("redmine", 2, "ri", "project_name")
        assert "p.system_type = 'redmine'" in s
        assert "TRIM(ri.project_name)" in s

    def test_ignored_empty_returns_empty(self):
        assert bug_analysis._exclude_ignored_projects_clause("b", "projectName", []) == ""

    def test_ignored_non_empty(self):
        s = bug_analysis._exclude_ignored_projects_clause("b", "projectName", ["僵尸A", "僵尸B"])
        assert "NOT IN" in s
        assert "'僵尸A'" in s and "'僵尸B'" in s
        assert "TRIM(b.projectName)" in s

    def test_project_exclusion_combines_both(self):
        s = bug_analysis._project_exclusion("zentao", 1, "b", "projectName", ["僵尸A"])
        assert "NOT EXISTS" in s and "is_active = 0" in s
        assert "NOT IN" in s and "'僵尸A'" in s


# ---------------------------------------------------------------------------
# _execute_query
# ===========================================================================


class TestExecuteQuery:
    def test_returns_dict_list(self):
        conn, cursor = _mock_conn()
        cursor.fetchall.return_value = [{"id": 1}, {"id": 2}]
        result = bug_analysis._execute_query(conn, "SELECT id FROM t")
        assert result == [{"id": 1}, {"id": 2}]
        cursor.close.assert_called_once()

    def test_empty_result(self):
        conn, _ = _mock_conn()
        result = bug_analysis._execute_query(conn, "SELECT 1")
        assert result == []


# ---------------------------------------------------------------------------
# _resolve_window
# ===========================================================================


class TestResolveWindow:
    def test_explicit_both(self):
        args = mock.Mock(since="2026-06-01", until="2026-06-26")
        since, until = bug_analysis._resolve_window(args)
        assert since == "2026-06-01 00:00:00"
        assert until == "2026-06-26 23:59:59"

    def test_explicit_with_time(self):
        args = mock.Mock(since="2026-06-01 08:00:00", until="2026-06-26 17:00:00")
        since, until = bug_analysis._resolve_window(args)
        assert since == "2026-06-01 08:00:00"
        assert until == "2026-06-26 17:00:00"

    def test_default_until_is_now(self):
        args = mock.Mock(since="2026-06-01", until=None)
        _, until = bug_analysis._resolve_window(args)
        parsed = datetime.strptime(until, "%Y-%m-%d %H:%M:%S")
        assert abs((datetime.now() - parsed).total_seconds()) < 10

    def test_default_since_is_7_days_ago(self):
        args = mock.Mock(since=None, until=None)
        since, _ = bug_analysis._resolve_window(args)
        parsed = datetime.strptime(since, "%Y-%m-%d %H:%M:%S")
        expected = (datetime.now() - timedelta(days=7)).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        assert abs((parsed - expected).total_seconds()) < 10

    def test_invalid_since_format_raises(self):
        args = mock.Mock(since="x' OR '1'='1", until=None)
        with pytest.raises(bug_analysis.ConfigError):
            bug_analysis._resolve_window(args)

    def test_invalid_until_format_raises(self):
        args = mock.Mock(since=None, until="2026/06/01")
        with pytest.raises(bug_analysis.ConfigError):
            bug_analysis._resolve_window(args)


# ---------------------------------------------------------------------------
# severe / zero-submission helpers
# ===========================================================================


class TestSevereAndZeroHelpers:
    def test_zero_submission_partial(self):
        users = ["张三", "李四", "王五"]
        by_user = {"张三": 2, "李四": 1}
        assert bug_analysis._zero_submission_users(users, by_user) == ["王五"]

    def test_zero_submission_all_submitted(self):
        users = ["张三", "李四"]
        by_user = {"张三": 1, "李四": 1}
        assert bug_analysis._zero_submission_users(users, by_user) == []

    def test_zero_submission_none_submitted(self):
        users = ["张三", "李四"]
        assert bug_analysis._zero_submission_users(users, {}) == ["张三", "李四"]

    def test_zero_submission_strips_keys(self):
        # DB 返回的 key 可能带空白，比对时 strip
        users = ["张三"]
        by_user = {"  张三  ": 1}
        assert bug_analysis._zero_submission_users(users, by_user) == []

    def test_severe_zt_severity_is_one(self):
        # 禅道 severity=1（数字）= 严重
        assert bug_analysis.is_severe({"severity": 1}, "zt") is True
        assert bug_analysis.is_severe({"severity": 2}, "zt") is False
        assert bug_analysis.is_severe({"severity": 4}, "zt") is False

    def test_severe_zt_string_digit(self):
        # severity 存字符串 "1" 也按数字匹配
        assert bug_analysis.is_severe({"severity": "1"}, "zt") is True

    def test_severe_zt_invalid_returns_false(self):
        assert bug_analysis.is_severe({"severity": "abc"}, "zt") is False
        assert bug_analysis.is_severe({}, "zt") is False

    def test_severe_rm_ends_with_a(self):
        # Redmine priority_name 以 -A 结尾 = 严重
        assert bug_analysis.is_severe({"priority_name": "立刻-A"}, "rm") is True
        assert bug_analysis.is_severe({"priority_name": "高-B"}, "rm") is False
        assert bug_analysis.is_severe({"priority_name": "一般-C"}, "rm") is False
        assert bug_analysis.is_severe({"priority_name": ""}, "rm") is False


# ---------------------------------------------------------------------------
# cmd_submissions
# ===========================================================================


class TestCmdSubmissions:
    def _zt_row(self, **extra):
        row = {
            "id": 1,
            "projectName": "P1",
            "openedBy": "张三-NJD-SW",
            "project": 820,
            "module": "m",
            "type": "t",
            "severity": 3,
            "pri": 1,
            "status": "激活",
            "assignedTo": "李四-NJD-SW",
            "resolution": "",
            "openedDate": "2026-06-20",
            "resolvedDate": None,
            "closedDate": None,
            "activatedCount": 0,
        }
        row.update(extra)
        return row

    def _rm_row(self, **extra):
        row = {
            "issue_id": 2,
            "project_name": "P2",
            "author_name": "王五_LM",
            "project_id": 5,
            "tracker_name": "Bug",
            "status_name": "新建",
            "priority_name": "Normal",
            "assigned_to_name": "王五_LM",
            "subject": "s",
            "created_on": "2026-06-20",
            "updated_on": None,
            "closed_on": None,
            "done_ratio": 0,
        }
        row.update(extra)
        return row

    def test_normal_output_with_severe_and_zero(self, capsys):
        config = _valid_config()
        conn, _ = _mock_conn(rows_per_query=[[self._zt_row()], [self._rm_row()]])
        args = mock.Mock(since="2026-06-19", until="2026-06-26")
        bug_analysis.cmd_submissions(conn, config, args)
        payload = json.loads(capsys.readouterr().out)
        assert payload["zentao"]["total"] == 1
        assert payload["zentao"]["by_user"] == {"张三-NJD-SW": 1}
        # 李四没提交（配置 users 含李四，但本周只张三提交）
        assert payload["zentao"]["zero_submission_users"] == ["李四-NJD-SW"]
        # severity=3 不是严重（严重=1）→ severe 空
        assert payload["zentao"]["severe"]["total"] == 0
        assert payload["redmine"]["total"] == 1
        assert payload["redmine"]["zero_submission_users"] == []

    def test_severe_filtering(self, capsys):
        config = _valid_config()
        rows = [self._zt_row(id=1, severity=1), self._zt_row(id=2, severity=3)]
        conn, _ = _mock_conn(rows_per_query=[rows, []])
        args = mock.Mock(since=None, until=None)
        bug_analysis.cmd_submissions(conn, config, args)
        payload = json.loads(capsys.readouterr().out)
        assert payload["zentao"]["severe"]["total"] == 1
        assert payload["zentao"]["severe"]["bugs"][0]["id"] == 1

    def test_redmine_severe_filtering(self, capsys):
        config = _valid_config()
        rows = [
            self._rm_row(issue_id=1, priority_name="严重-A"),
            self._rm_row(issue_id=2, priority_name="一般-C"),
        ]
        conn, _ = _mock_conn(rows_per_query=[[], rows])
        args = mock.Mock(since=None, until=None)
        bug_analysis.cmd_submissions(conn, config, args)
        payload = json.loads(capsys.readouterr().out)
        assert payload["redmine"]["severe"]["total"] == 1
        assert payload["redmine"]["severe"]["issues"][0]["issue_id"] == 1

    def test_empty_zentao_users_skips_query(self, capsys):
        config = _valid_config(zentao={"instance_id": 1, "users": []})
        conn, _ = _mock_conn(rows_per_query=[[]])
        args = mock.Mock(since=None, until=None)
        bug_analysis.cmd_submissions(conn, config, args)
        payload = json.loads(capsys.readouterr().out)
        assert payload["zentao"]["total"] == 0
        assert payload["zentao"]["severe"]["total"] == 0

    def test_empty_redmine_users_skips_query(self, capsys):
        config = _valid_config(redmine={"instance_id": 2, "users": []})
        conn, _ = _mock_conn(rows_per_query=[[]])
        args = mock.Mock(since=None, until=None)
        bug_analysis.cmd_submissions(conn, config, args)
        payload = json.loads(capsys.readouterr().out)
        assert payload["redmine"]["total"] == 0

    def test_multiple_users_aggregation(self, capsys):
        config = _valid_config()
        conn, _ = _mock_conn(
            rows_per_query=[
                [
                    self._zt_row(id=1, openedBy="张三-NJD-SW", projectName="P1"),
                    self._zt_row(id=2, openedBy="李四-NJD-SW", projectName="P1"),
                    self._zt_row(id=3, openedBy="张三-NJD-SW", projectName="P2"),
                ],
                [],
            ]
        )
        args = mock.Mock(since=None, until=None)
        bug_analysis.cmd_submissions(conn, config, args)
        payload = json.loads(capsys.readouterr().out)
        assert payload["zentao"]["by_user"] == {"张三-NJD-SW": 2, "李四-NJD-SW": 1}
        assert payload["zentao"]["by_project"] == {"P1": 2, "P2": 1}
        assert payload["zentao"]["zero_submission_users"] == []

    def test_submissions_sql_applies_project_filter(self):
        config = _valid_config()
        config["zentao"]["ignored_projects"] = ["僵尸项目A"]
        config["redmine"]["ignored_projects"] = ["僵尸项目B"]
        conn, cursor = _mock_conn(rows_per_query=[[], []])
        args = mock.Mock(since=None, until=None)
        bug_analysis.cmd_submissions(conn, config, args)
        calls = cursor.execute.call_args_list
        zt_sql = calls[0][0][0]
        assert "NOT EXISTS" in zt_sql and "is_active = 0" in zt_sql
        assert "NOT IN" in zt_sql and "'僵尸项目A'" in zt_sql
        rm_sql = calls[1][0][0]
        assert "NOT EXISTS" in rm_sql and "'僵尸项目B'" in rm_sql


# ---------------------------------------------------------------------------
# cmd_overdue
# ===========================================================================


class TestCmdOverdue:
    def _zt_row(self, **extra):
        row = {
            "id": 1,
            "projectName": "P1",
            "module": "m",
            "severity": 3,
            "pri": 1,
            "status": "激活",
            "assignedTo": "张三-NJD-SW",
            "openedBy": "李四-NJD-SW",
            "openedDate": "2026-06-01",
            "resolution": "",
            "activatedCount": 0,
            "last_user_action": "2026-06-10",
            "days_since_action": 16,
        }
        row.update(extra)
        return row

    def _rm_row(self, **extra):
        row = {
            "issue_id": 2,
            "project_name": "P2",
            "tracker_name": "Bug",
            "status_name": "新建",
            "priority_name": "Normal",
            "author_name": "x",
            "assigned_to_name": "王五_LM",
            "subject": "s",
            "created_on": "2026-06-01",
            "updated_on": None,
            "closed_on": None,
            "last_user_action": "2026-06-05",
            "days_since_action": 21,
        }
        row.update(extra)
        return row

    def test_normal_output(self, capsys):
        config = _valid_config()
        conn, _ = _mock_conn(rows_per_query=[[self._zt_row()], [self._rm_row()]])
        rc = bug_analysis.cmd_overdue(conn, config, mock.Mock())
        assert rc == 0
        payload = json.loads(capsys.readouterr().out)
        assert payload["overdue_days"] == 7  # 固定常量
        assert payload["zentao"]["total"] == 1
        assert payload["zentao"]["by_user"] == {"张三-NJD-SW": 1}
        assert payload["redmine"]["total"] == 1

    def test_empty_zentao_users(self, capsys):
        config = _valid_config(zentao={"instance_id": 1, "users": []})
        conn, _ = _mock_conn(rows_per_query=[[]])
        rc = bug_analysis.cmd_overdue(conn, config, mock.Mock())
        assert rc == 0
        payload = json.loads(capsys.readouterr().out)
        assert payload["zentao"]["total"] == 0

    def test_empty_redmine_users(self, capsys):
        config = _valid_config(redmine={"instance_id": 2, "users": []})
        conn, _ = _mock_conn(rows_per_query=[[]])
        rc = bug_analysis.cmd_overdue(conn, config, mock.Mock())
        assert rc == 0
        payload = json.loads(capsys.readouterr().out)
        assert payload["redmine"]["total"] == 0

    def test_decimal_days_since_action_serialises(self, capsys):
        config = _valid_config()
        conn, _ = _mock_conn(rows_per_query=[[self._zt_row(days_since_action=Decimal("16"))], []])
        bug_analysis.cmd_overdue(conn, config, mock.Mock())
        payload = json.loads(capsys.readouterr().out)
        assert payload["zentao"]["bugs"][0]["days_since_action"] == 16

    def test_overdue_sql_applies_project_filter(self):
        config = _valid_config()
        config["zentao"]["ignored_projects"] = ["僵尸X"]
        conn, cursor = _mock_conn(rows_per_query=[[], []])
        bug_analysis.cmd_overdue(conn, config, mock.Mock())
        calls = cursor.execute.call_args_list
        zt_sql = calls[0][0][0]
        assert "NOT EXISTS" in zt_sql and "is_active = 0" in zt_sql
        assert "NOT IN" in zt_sql and "'僵尸X'" in zt_sql
        assert f"> {bug_analysis.OVERDUE_DAYS}" in zt_sql


# ---------------------------------------------------------------------------
# cmd_severe
# ===========================================================================


class TestCmdSevere:
    def test_normal_output(self, capsys):
        config = _valid_config()
        conn, _ = _mock_conn(
            rows_per_query=[
                [
                    {
                        "id": 1,
                        "projectName": "P1",
                        "severity": "1",
                        "status": "激活",
                        "openedDate": "2026-06-01",
                        "project": 1,
                    }
                ],
                [
                    {
                        "issue_id": 2,
                        "project_name": "P2",
                        "priority_name": "严重-A",
                        "status_name": "新建",
                        "created_on": "2026-06-01",
                        "project_id": 5,
                    }
                ],
            ]
        )
        rc = bug_analysis.cmd_severe(conn, config, mock.Mock())
        assert rc == 0
        payload = json.loads(capsys.readouterr().out)
        assert payload["zentao"]["total"] == 1
        assert payload["redmine"]["total"] == 1

    def test_severe_sql_uses_severity_one_and_project_filter(self):
        config = _valid_config()
        config["zentao"]["ignored_projects"] = ["僵尸S"]
        conn, cursor = _mock_conn(rows_per_query=[[], []])
        bug_analysis.cmd_severe(conn, config, mock.Mock())
        calls = cursor.execute.call_args_list
        zt_sql = calls[0][0][0]
        assert "severity = 1" in zt_sql
        assert "status != '已关闭'" in zt_sql
        assert "TRIM(openedBy) IN" in zt_sql  # 限定本组提交
        assert "NOT EXISTS" in zt_sql and "'僵尸S'" in zt_sql
        # 全库查询：WHERE 不按本组 openedBy 限制
        assert "TRIM(assignedTo) IN" not in zt_sql

    def test_severe_sql_redmine(self):
        config = _valid_config()
        conn, cursor = _mock_conn(rows_per_query=[[], []])
        bug_analysis.cmd_severe(conn, config, mock.Mock())
        calls = cursor.execute.call_args_list
        rm_sql = calls[1][0][0]
        assert "priority_name LIKE '%-A'" in rm_sql
        assert "status_name != '已关闭'" in rm_sql
        assert "TRIM(author_name) IN" in rm_sql  # 限定本组提交


# ---------------------------------------------------------------------------
# cmd_closures
# ===========================================================================


class TestCmdClosures:
    def test_normal_output(self, capsys):
        config = _valid_config()
        conn, _ = _mock_conn(
            rows_per_query=[
                [
                    {
                        "id": 1,
                        "projectName": "P1",
                        "closedBy": "张三-NJD-SW",
                        "closedDate": "2026-06-20",
                        "project": 1,
                    }
                ],
                [
                    {
                        "issue_id": 2,
                        "project_name": "P2",
                        "closed_by": "王五_LM",
                        "closed_at": "2026-06-20",
                        "project_id": 5,
                    }
                ],
            ]
        )
        args = mock.Mock(since="2026-06-19", until="2026-06-26")
        rc = bug_analysis.cmd_closures(conn, config, args)
        assert rc == 0
        payload = json.loads(capsys.readouterr().out)
        assert payload["window"]["start"] == "2026-06-19 00:00:00"
        assert payload["zentao"]["total"] == 1
        assert payload["zentao"]["by_user"] == {"张三-NJD-SW": 1}
        assert payload["zentao"]["by_project"] == {"P1": 1}
        assert payload["redmine"]["total"] == 1
        assert payload["redmine"]["by_user"] == {"王五_LM": 1}

    def test_empty_zentao_users(self, capsys):
        config = _valid_config(zentao={"instance_id": 1, "users": []})
        conn, _ = _mock_conn(rows_per_query=[[]])
        args = mock.Mock(since=None, until=None)
        bug_analysis.cmd_closures(conn, config, args)
        payload = json.loads(capsys.readouterr().out)
        assert payload["zentao"]["total"] == 0

    def test_closures_sql_zentao(self):
        config = _valid_config()
        config["zentao"]["ignored_projects"] = ["僵尸C"]
        conn, cursor = _mock_conn(rows_per_query=[[], []])
        args = mock.Mock(since="2026-06-19", until="2026-06-26")
        bug_analysis.cmd_closures(conn, config, args)
        calls = cursor.execute.call_args_list
        zt_sql = calls[0][0][0]
        assert "TRIM(closedBy) IN" in zt_sql
        assert "closedDate >= '2026-06-19 00:00:00'" in zt_sql
        assert "NOT IN" in zt_sql and "'僵尸C'" in zt_sql

    def test_closures_sql_redmine_journal_join(self):
        config = _valid_config()
        conn, cursor = _mock_conn(rows_per_query=[[], []])
        args = mock.Mock(since="2026-06-19", until="2026-06-26")
        bug_analysis.cmd_closures(conn, config, args)
        calls = cursor.execute.call_args_list
        rm_sql = calls[1][0][0]
        assert "redmine_issue_journal j" in rm_sql
        assert "redmine_issue_journal_detail jd" in rm_sql
        assert "jd.name = 'status_id'" in rm_sql
        assert "jd.new_value IN" in rm_sql
        assert "ri2.status_name = '已关闭'" in rm_sql
        assert "TRIM(j.user_name) IN" in rm_sql


# ---------------------------------------------------------------------------
# build_parser
# ===========================================================================


class TestBuildParser:
    def test_submissions_subcommand(self):
        args = bug_analysis.build_parser().parse_args(
            ["submissions", "--since", "2026-06-01", "--until", "2026-06-26"]
        )
        assert args.command == "submissions"
        assert args.since == "2026-06-01"
        assert args.until == "2026-06-26"

    def test_overdue_subcommand(self):
        args = bug_analysis.build_parser().parse_args(["overdue"])
        assert args.command == "overdue"

    def test_severe_subcommand(self):
        args = bug_analysis.build_parser().parse_args(["severe"])
        assert args.command == "severe"

    def test_closures_subcommand(self):
        args = bug_analysis.build_parser().parse_args(["closures", "--since", "2026-06-01"])
        assert args.command == "closures"
        assert args.since == "2026-06-01"

    def test_no_subcommand_exits(self):
        with pytest.raises(SystemExit):
            bug_analysis.build_parser().parse_args([])


# ---------------------------------------------------------------------------
# main
# ===========================================================================


class TestMain:
    def test_config_error_returns_1(self, capsys):
        with (
            mock.patch("sys.argv", ["bug_analysis.py", "overdue"]),
            mock.patch.object(
                bug_analysis,
                "load_analysis_config",
                side_effect=bug_analysis.ConfigError("bad config"),
            ),
        ):
            rc = bug_analysis.main()
        assert rc == 1
        assert "配置错误" in capsys.readouterr().err

    def test_connection_error_returns_1(self, capsys):
        with (
            mock.patch("sys.argv", ["bug_analysis.py", "overdue"]),
            mock.patch.object(bug_analysis, "load_analysis_config", return_value=_valid_config()),
            mock.patch.object(
                bug_analysis, "get_mysql_connection", side_effect=bug_analysis.ConfigError("no db")
            ),
        ):
            rc = bug_analysis.main()
        assert rc == 1
        assert "数据库连接错误" in capsys.readouterr().err

    def test_overdue_success_closes_connection(self, capsys):
        conn, _ = _mock_conn(rows_per_query=[[], []])
        with (
            mock.patch("sys.argv", ["bug_analysis.py", "overdue"]),
            mock.patch.object(bug_analysis, "load_analysis_config", return_value=_valid_config()),
            mock.patch.object(bug_analysis, "get_mysql_connection", return_value=conn),
        ):
            rc = bug_analysis.main()
        assert rc == 0
        conn.is_connected.assert_called()
        conn.close.assert_called_once()

    def test_severe_success(self, capsys):
        conn, _ = _mock_conn(rows_per_query=[[], []])
        with (
            mock.patch("sys.argv", ["bug_analysis.py", "severe"]),
            mock.patch.object(bug_analysis, "load_analysis_config", return_value=_valid_config()),
            mock.patch.object(bug_analysis, "get_mysql_connection", return_value=conn),
        ):
            rc = bug_analysis.main()
        assert rc == 0

    def test_closures_success(self, capsys):
        conn, _ = _mock_conn(rows_per_query=[[], []])
        with (
            mock.patch("sys.argv", ["bug_analysis.py", "closures", "--since", "2026-06-01"]),
            mock.patch.object(bug_analysis, "load_analysis_config", return_value=_valid_config()),
            mock.patch.object(bug_analysis, "get_mysql_connection", return_value=conn),
        ):
            rc = bug_analysis.main()
        assert rc == 0

    def test_connection_not_closed_if_disconnected(self, capsys):
        conn, _ = _mock_conn(rows_per_query=[[], []])
        conn.is_connected.return_value = False
        with (
            mock.patch("sys.argv", ["bug_analysis.py", "overdue"]),
            mock.patch.object(bug_analysis, "load_analysis_config", return_value=_valid_config()),
            mock.patch.object(bug_analysis, "get_mysql_connection", return_value=conn),
        ):
            bug_analysis.main()
        conn.close.assert_not_called()
