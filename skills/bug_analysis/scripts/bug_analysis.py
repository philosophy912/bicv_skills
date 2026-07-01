#!/usr/bin/env python3
"""Bug Analysis — 测试组缺陷提交、超期跟踪、严重缺陷、关闭统计。

四个子命令：
    submissions  – 按提交时间框，查用户组提交的缺陷（含本周严重 + 零提交人）
    overdue      – 当前超期未处理（指派后本组 7 天无 action，阈值固定）
    severe       – 全库当前未关闭的严重缺陷（不限本组，整体质量视角）
    closures     – 本周用户组关闭的缺陷（禅道 closedBy / Redmine journal）

严重判定（DB 实证后硬编码）：禅道 ``severity=1``（数字 1-4，1=最严重），
Redmine ``priority_name LIKE '%-A'``（形如「立刻-A」，A 后缀=最高级）。不进配置。
僵尸项目黑名单走配置（ignored_projects），与 is_active=0 叠加，四块查询全套。

依赖：
    mysql-connector-python（与 mysql skill 共享）
    ~/.bicv/bug_analysis.json（用户组 + 僵尸项目黑名单）
    ~/.bicv/mysql.json（DB 连接，system=ticket）
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

# --- mysql-connector guard ---
try:
    import mysql.connector
    from mysql.connector import Error as MySQLError
except ImportError:
    print(
        "Error: mysql-connector-python is not installed.\n"
        "Install it with: pip install mysql-connector-python",
        file=sys.stderr,
    )
    sys.exit(1)

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

CONFIG_NAME = "bug_analysis.json"
MYSQL_CONFIG_NAME = "mysql.json"

# 超期阈值固定 7 天（grilling 确认，不入配置）。
OVERDUE_DAYS = 7

# 严重判定（DB 实证：禅道 severity 存数字 1-4，1=最严重；Redmine priority_name
# 形如「立刻-A」，A 后缀=最高级）。硬编码，不入配置。
ZENTAO_SEVERE_SEVERITY = 1
REDMINE_SEVERE_SUFFIX = "-A"


class ConfigError(Exception):
    """配置加载错误。"""


def _load_json_config(filename: str) -> dict[str, Any]:
    """从 ~/.bicv/<filename> 加载 JSON 配置。"""
    path = Path.home() / ".bicv" / filename
    if not path.exists():
        raise ConfigError(f"配置文件不存在: {path}\n请创建 ~/.bicv/{filename}")
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError as exc:
        raise ConfigError(f"配置文件 JSON 格式错误: {path}\n{exc}") from exc


def _validate_users(section: dict[str, Any], sys_name: str) -> list[str]:
    """校验并返回 user 列表。"""
    users = section.get("users")
    if not isinstance(users, list) or not users:
        raise ConfigError(f"[{CONFIG_NAME}] {sys_name}.users 必须是非空列表")
    return [str(u).strip() for u in users if str(u).strip()]


def _validate_str_list(section: dict[str, Any], key: str, sys_name: str) -> list[str]:
    """可选字符串列表字段（ignored_projects）：缺省空，存在则必须是 list。"""
    raw = section.get(key)
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise ConfigError(f"[{CONFIG_NAME}] {sys_name}.{key} 必须是列表")
    return [str(x).strip() for x in raw if str(x).strip()]


def load_analysis_config() -> dict[str, Any]:
    """加载并校验 bug_analysis.json。"""
    config = _load_json_config(CONFIG_NAME)

    for sys_name in ("zentao", "redmine"):
        section = config.get(sys_name)
        if not isinstance(section, dict):
            raise ConfigError(
                f"[{CONFIG_NAME}] 缺少 '{sys_name}' 段，需配置 instance_id 和 users 列表"
            )
        if "instance_id" not in section:
            raise ConfigError(f"[{CONFIG_NAME}] {sys_name}.instance_id 是必填项")
        section["users"] = _validate_users(section, sys_name)
        # 僵尸项目黑名单（可选）—— is_active=0 之外的、主观判定的僵尸项目
        section["ignored_projects"] = _validate_str_list(section, "ignored_projects", sys_name)

    return config


def get_mysql_connection(*, system_name: str = "ticket") -> Any:
    """从 ~/.bicv/mysql.json 创建 MySQL 连接（默认 system=ticket）。"""
    mysql_config = _load_json_config(MYSQL_CONFIG_NAME)
    systems = mysql_config.get("systems", {})
    if not isinstance(systems, dict) or not systems:
        raise ConfigError(f"[{MYSQL_CONFIG_NAME}] systems 字典为空或缺失")

    # Use explicit system_name, or default_system, or "ticket"
    if system_name not in systems:
        configured = system_name or mysql_config.get("default_system", "")
        if configured not in systems:
            available = ", ".join(systems.keys())
            raise ConfigError(
                f"[{MYSQL_CONFIG_NAME}] system '{system_name}' 不存在。可选: {available}"
            )
        system_name = configured

    sys_cfg = systems[system_name]
    host = str(sys_cfg.get("host", "")).strip()
    port = int(sys_cfg.get("port", 3306))
    database = str(sys_cfg.get("database", "")).strip() or "ticket"
    username = str(sys_cfg.get("username", "")).strip()
    password = str(sys_cfg.get("password", "")).strip()

    if not host or not username:
        raise ConfigError(f"[{MYSQL_CONFIG_NAME}] system '{system_name}' 缺少 host 或 username")

    try:
        conn = mysql.connector.connect(
            host=host,
            port=port,
            database=database,
            user=username,
            password=password or "",
            ssl_disabled=True,
        )
        return conn
    except MySQLError as exc:
        raise ConfigError(f"MySQL 连接失败 ({host}:{port}): {exc}") from exc


# ---------------------------------------------------------------------------
# Decimal-aware JSON
# ---------------------------------------------------------------------------


class _DecimalEncoder(json.JSONEncoder):
    """Decimal → int/float，datetime → ISO 字符串。"""

    def default(self, o: Any) -> Any:
        if isinstance(o, Decimal):
            return int(o) if o == int(o) else float(o)
        if isinstance(o, datetime):
            return o.strftime("%Y-%m-%d %H:%M:%S")
        return super().default(o)


# ---------------------------------------------------------------------------
# SQL helpers
# ---------------------------------------------------------------------------


def _in_clause(values: list[str]) -> str:
    """把字符串列表拼成 SQL IN 子句（值来自可信配置文件，做最小转义）。"""
    escaped = ", ".join("'" + v.replace("\\", "\\\\").replace("'", "\\'") + "'" for v in values)
    return f"({escaped})"


def _exclude_inactive_project_clause(
    system_type: str, instance_id: int, alias: str, name_col: str
) -> str:
    """NOT EXISTS 子句：排除 project 表中 is_active=0 的停用项目。

    关联键用 project_name（external_project_id 与缺陷的 project id 非同一套 id），
    库内 project_name 与 projectName/project_name 存在 collation 混用，需统一。
    未收录在 project 表的项目不匹配子查询，故保留（按在研处理，不漏）。
    """
    return (
        " AND NOT EXISTS ("
        " SELECT 1 FROM project p"
        f" WHERE p.system_type = '{system_type}'"
        f" AND p.instance_id = {instance_id}"
        " AND TRIM(p.project_name) COLLATE utf8mb4_unicode_ci"
        f" = TRIM({alias}.{name_col}) COLLATE utf8mb4_unicode_ci"
        " AND p.is_active = 0)"
    )


def _exclude_ignored_projects_clause(alias: str, name_col: str, ignored: list[str]) -> str:
    """NOT IN 子句：排除配置文件黑名单里的僵尸项目（值来自可信配置）。"""
    if not ignored:
        return ""
    return f" AND TRIM({alias}.{name_col}) COLLATE utf8mb4_unicode_ci NOT IN {_in_clause(ignored)}"


def _project_exclusion(
    system_type: str, instance_id: int, alias: str, name_col: str, ignored: list[str]
) -> str:
    """组合：is_active=0 自动排除 + 配置黑名单手动排除（四块查询全套）。"""
    return _exclude_inactive_project_clause(
        system_type, instance_id, alias, name_col
    ) + _exclude_ignored_projects_clause(alias, name_col, ignored)


def _execute_query(conn: Any, sql: str) -> list[dict[str, Any]]:
    """执行 SELECT 查询，返回 dict 列表。"""
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute(sql)
        return cursor.fetchall()
    finally:
        cursor.close()


# ---------------------------------------------------------------------------
# Window helpers
# ---------------------------------------------------------------------------


_WINDOW_DT_RE = re.compile(r"^\d{4}-\d{2}-\d{2}( \d{2}:\d{2}:\d{2})?$")


def _validate_window_dt(value: str, flag: str) -> str:
    """校验时间参数格式（YYYY-MM-DD 或 YYYY-MM-DD HH:MM:SS），防 SQL 注入。"""
    if not _WINDOW_DT_RE.match(value):
        raise ConfigError(
            f"参数 {flag} 格式应为 'YYYY-MM-DD' 或 'YYYY-MM-DD HH:MM:SS'，当前: {value!r}"
        )
    return value


def _resolve_window(args: argparse.Namespace) -> tuple[str, str]:
    """解析时间窗口，返回 (since, until) 字符串（YYYY-MM-DD HH:MM:SS）。"""
    if args.until:
        until = _validate_window_dt(args.until, "--until")
    else:
        until = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    if args.since:
        since = _validate_window_dt(args.since, "--since")
    else:
        since = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d 00:00:00")

    if len(since) == 10:  # date only
        since += " 00:00:00"
    if len(until) == 10:
        until += " 23:59:59"

    return since, until


# ---------------------------------------------------------------------------
# Common: 零提交 + 严重判定
# ---------------------------------------------------------------------------


def _zero_submission_users(users: list[str], by_user: dict[str, int]) -> list[str]:
    """配置 users 中本周零提交的人（按 strip 后比对，保序）。"""
    submitted = {str(k).strip() for k in by_user}
    return [u for u in users if u not in submitted]


def is_severe(row: dict[str, Any], kind: str) -> bool:
    """判定单条缺陷是否严重。

    - kind='zt'：禅道 severity == 1（DB 存数字 1-4，1=最严重）
    - kind='rm'：Redmine priority_name 以 '-A' 结尾（形如「立刻-A」，A 后缀=最高级）
    """
    if kind == "zt":
        try:
            return int(row.get("severity", 0)) == ZENTAO_SEVERE_SEVERITY
        except (TypeError, ValueError):
            return False
    return str(row.get("priority_name", "")).endswith(REDMINE_SEVERE_SUFFIX)


# ---------------------------------------------------------------------------
# submissions sub-command
# ---------------------------------------------------------------------------


def cmd_submissions(conn: Any, config: dict[str, Any], args: argparse.Namespace) -> int:
    """窗口内用户组提交的缺陷（含本周严重 + 零提交人）。"""
    since, until = _resolve_window(args)

    result: dict[str, Any] = {
        "window": {"start": since, "end": until},
    }

    # --- Zentao ---
    zt_cfg = config["zentao"]
    zt_users = zt_cfg["users"]
    zt_instance = zt_cfg["instance_id"]
    zt_ignored = zt_cfg.get("ignored_projects", [])

    if zt_users:
        zt_sql = (
            "SELECT id, project, projectName, module, title, type, severity, pri,"
            "       status, openedBy, assignedTo, resolution,"
            "       openedDate, resolvedDate, closedDate, activatedCount"
            f" FROM zentao_bug"
            f" WHERE instance_id = {zt_instance}"
            f"   AND TRIM(openedBy) IN {_in_clause(zt_users)}"
            f"   AND openedDate >= '{since}'"
            f"   AND openedDate <  '{until}'"
            f"   AND deleted = '0'"
            + _project_exclusion("zentao", zt_instance, "zentao_bug", "projectName", zt_ignored)
            + " ORDER BY openedDate DESC"
        )
        zt_rows = _execute_query(conn, zt_sql)

        by_user: dict[str, int] = {}
        by_project: dict[str, int] = {}
        for row in zt_rows:
            u = row.get("openedBy") or "unknown"
            p = row.get("projectName") or f"project-{row.get('project', '?')}"
            by_user[u] = by_user.get(u, 0) + 1
            by_project[p] = by_project.get(p, 0) + 1

        zt_severe = [r for r in zt_rows if is_severe(r, "zt")]
        result["zentao"] = {
            "instance_id": zt_instance,
            "total": len(zt_rows),
            "by_user": by_user,
            "by_project": by_project,
            "bugs": zt_rows,
            "severe": {"total": len(zt_severe), "bugs": zt_severe},
            "zero_submission_users": _zero_submission_users(zt_users, by_user),
        }
    else:
        result["zentao"] = {
            "instance_id": zt_instance,
            "total": 0,
            "bugs": [],
            "severe": {"total": 0, "bugs": []},
            "zero_submission_users": list(zt_users),
        }

    # --- Redmine ---
    rm_cfg = config["redmine"]
    rm_users = rm_cfg["users"]
    rm_instance = rm_cfg["instance_id"]
    rm_ignored = rm_cfg.get("ignored_projects", [])

    if rm_users:
        rm_sql = (
            "SELECT record_id, issue_id, project_id, project_name, tracker_name,"
            "       status_name, priority_name, author_name, assigned_to_name,"
            "       subject, created_on, updated_on, closed_on, done_ratio"
            f" FROM redmine_issue"
            f" WHERE instance_id = {rm_instance}"
            f"   AND TRIM(author_name) IN {_in_clause(rm_users)}"
            f"   AND created_on >= '{since}'"
            f"   AND created_on <  '{until}'"
            + _project_exclusion(
                "redmine", rm_instance, "redmine_issue", "project_name", rm_ignored
            )
            + " ORDER BY created_on DESC"
        )
        rm_rows = _execute_query(conn, rm_sql)

        by_user_rm: dict[str, int] = {}
        by_project_rm: dict[str, int] = {}
        for row in rm_rows:
            u = row.get("author_name") or "unknown"
            p = row.get("project_name") or f"project-{row.get('project_id', '?')}"
            by_user_rm[u] = by_user_rm.get(u, 0) + 1
            by_project_rm[p] = by_project_rm.get(p, 0) + 1

        rm_severe = [r for r in rm_rows if is_severe(r, "rm")]
        result["redmine"] = {
            "instance_id": rm_instance,
            "total": len(rm_rows),
            "by_user": by_user_rm,
            "by_project": by_project_rm,
            "issues": rm_rows,
            "severe": {"total": len(rm_severe), "issues": rm_severe},
            "zero_submission_users": _zero_submission_users(rm_users, by_user_rm),
        }
    else:
        result["redmine"] = {
            "instance_id": rm_instance,
            "total": 0,
            "issues": [],
            "severe": {"total": 0, "issues": []},
            "zero_submission_users": list(rm_users),
        }

    print(json.dumps(result, ensure_ascii=False, indent=2, cls=_DecimalEncoder))
    return 0


# ---------------------------------------------------------------------------
# overdue sub-command
# ---------------------------------------------------------------------------


def cmd_overdue(conn: Any, config: dict[str, Any], args: argparse.Namespace) -> int:
    """当前超期未处理的缺陷（指派 > OVERDUE_DAYS 天，用户组无 action）。"""
    result: dict[str, Any] = {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "overdue_days": OVERDUE_DAYS,
    }

    # --- Zentao ---
    zt_cfg = config["zentao"]
    zt_users = zt_cfg["users"]
    zt_instance = zt_cfg["instance_id"]
    zt_ignored = zt_cfg.get("ignored_projects", [])

    if zt_users:
        user_in = _in_clause(zt_users)
        zt_sql = (
            "SELECT b.id, b.project, b.projectName, b.module, b.title, b.severity, b.pri,"
            "       b.status, b.assignedTo, b.openedBy, b.openedDate,"
            "       b.resolution, b.activatedCount,"
            "       COALESCE(GREATEST("
            "           COALESCE(last_assigned.t, b.openedDate),"
            "           COALESCE(last_act.action_date, b.openedDate)"
            "       ), b.openedDate) AS last_user_action,"
            "       DATEDIFF(NOW(), COALESCE(GREATEST("
            "           COALESCE(last_assigned.t, b.openedDate),"
            "           COALESCE(last_act.action_date, b.openedDate)"
            "       ), b.openedDate)) AS days_since_action"
            " FROM zentao_bug b"
            " LEFT JOIN ("
            "     SELECT zentao_bug_id, MAX(date) AS action_date"
            "     FROM zentao_bug_action"
            f"     WHERE instance_id = {zt_instance}"
            f"       AND TRIM(actor) IN {user_in}"
            "     GROUP BY zentao_bug_id"
            " ) last_act ON b.id = last_act.zentao_bug_id"
            " LEFT JOIN ("
            "     SELECT ah.zentao_bug_id, MAX(a.date) AS t"
            "     FROM zentao_bug_action_history ah"
            "     JOIN zentao_bug_action a"
            "       ON ah.instance_id = a.instance_id AND ah.action_id = a.action_id"
            f"     WHERE ah.instance_id = {zt_instance}"
            f"       AND ah.field = '指派给'"
            f"       AND TRIM(ah.new) IN {user_in}"
            "     GROUP BY ah.zentao_bug_id"
            " ) last_assigned ON b.id = last_assigned.zentao_bug_id"
            f" WHERE b.instance_id = {zt_instance}"
            f"   AND b.deleted = '0'"
            f"   AND b.status != '已关闭'"
            f"   AND TRIM(b.assignedTo) IN {user_in}"
            f"   AND DATEDIFF(NOW(), COALESCE(GREATEST("
            f"       COALESCE(last_assigned.t, b.openedDate),"
            f"       COALESCE(last_act.action_date, b.openedDate)"
            f"   ), b.openedDate)) > {OVERDUE_DAYS}"
            + _project_exclusion("zentao", zt_instance, "b", "projectName", zt_ignored)
            + " ORDER BY last_user_action ASC"
        )
        zt_rows = _execute_query(conn, zt_sql)

        by_user_zt: dict[str, int] = {}
        for row in zt_rows:
            u = row.get("assignedTo") or "unknown"
            by_user_zt[u] = by_user_zt.get(u, 0) + 1

        result["zentao"] = {
            "instance_id": zt_instance,
            "total": len(zt_rows),
            "by_user": by_user_zt,
            "bugs": zt_rows,
        }
    else:
        result["zentao"] = {"instance_id": zt_instance, "total": 0, "bugs": []}

    # --- Redmine ---
    rm_cfg = config["redmine"]
    rm_users = rm_cfg["users"]
    rm_instance = rm_cfg["instance_id"]
    rm_ignored = rm_cfg.get("ignored_projects", [])

    if rm_users:
        user_in_rm = _in_clause(rm_users)
        rm_sql = (
            "SELECT ri.issue_id, ri.project_id, ri.project_name, ri.tracker_name,"
            "       ri.status_name, ri.priority_name, ri.author_name,"
            "       ri.assigned_to_name, ri.subject,"
            "       ri.created_on, ri.updated_on, ri.closed_on,"
            "       COALESCE(GREATEST("
            "           COALESCE(last_assigned.t, ri.created_on),"
            "           COALESCE(last_j.created_on, ri.created_on)"
            "       ), ri.created_on) AS last_user_action,"
            "       DATEDIFF(NOW(), COALESCE(GREATEST("
            "           COALESCE(last_assigned.t, ri.created_on),"
            "           COALESCE(last_j.created_on, ri.created_on)"
            "       ), ri.created_on)) AS days_since_action"
            " FROM redmine_issue ri"
            " LEFT JOIN ("
            "     SELECT issue_id, MAX(created_on) AS created_on"
            "     FROM redmine_issue_journal"
            f"     WHERE instance_id = {rm_instance}"
            f"       AND TRIM(user_name) IN {user_in_rm}"
            "     GROUP BY issue_id"
            " ) last_j ON ri.issue_id = last_j.issue_id"
            " LEFT JOIN ("
            "     SELECT j.issue_id, MAX(j.created_on) AS t"
            "     FROM redmine_issue_journal j"
            "     JOIN redmine_issue_journal_detail jd"
            "       ON j.journal_id = jd.journal_id AND j.instance_id = jd.instance_id"
            f"     WHERE j.instance_id = {rm_instance}"
            f"       AND jd.name = 'assigned_to_id'"
            "       AND jd.new_value IN ("
            "           SELECT DISTINCT assigned_to_id FROM redmine_issue"
            f"           WHERE instance_id = {rm_instance}"
            f"             AND TRIM(assigned_to_name) IN {user_in_rm}"
            "       )"
            "     GROUP BY j.issue_id"
            " ) last_assigned ON ri.issue_id = last_assigned.issue_id"
            f" WHERE ri.instance_id = {rm_instance}"
            f"   AND ri.status_name NOT IN ('已关闭', '已拒绝')"
            f"   AND TRIM(ri.assigned_to_name) IN {user_in_rm}"
            f"   AND DATEDIFF(NOW(), COALESCE(GREATEST("
            f"       COALESCE(last_assigned.t, ri.created_on),"
            f"       COALESCE(last_j.created_on, ri.created_on)"
            f"   ), ri.created_on)) > {OVERDUE_DAYS}"
            + _project_exclusion("redmine", rm_instance, "ri", "project_name", rm_ignored)
            + " ORDER BY last_user_action ASC"
        )
        rm_rows = _execute_query(conn, rm_sql)

        by_user_rm: dict[str, int] = {}
        for row in rm_rows:
            u = row.get("assigned_to_name") or "unknown"
            by_user_rm[u] = by_user_rm.get(u, 0) + 1

        result["redmine"] = {
            "instance_id": rm_instance,
            "total": len(rm_rows),
            "by_user": by_user_rm,
            "issues": rm_rows,
        }
    else:
        result["redmine"] = {"instance_id": rm_instance, "total": 0, "issues": []}

    print(json.dumps(result, ensure_ascii=False, indent=2, cls=_DecimalEncoder))
    return 0


# ---------------------------------------------------------------------------
# severe sub-command — 全库当前未关闭的严重缺陷
# ---------------------------------------------------------------------------


def cmd_severe(conn: Any, config: dict[str, Any], args: argparse.Namespace) -> int:
    """本组提交的、当前未关闭的严重缺陷。

    严重判定硬编码：禅道 severity=1，Redmine priority_name LIKE '%-A'。
    限定本组提交：禅道 openedBy∈users，Redmine author_name∈users。
    """
    result: dict[str, Any] = {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }

    # --- Zentao ---
    zt_cfg = config["zentao"]
    zt_instance = zt_cfg["instance_id"]
    zt_ignored = zt_cfg.get("ignored_projects", [])

    zt_sql = (
        "SELECT id, project, projectName, module, title, type, severity, pri,"
        "       status, openedBy, assignedTo, resolution, openedDate,"
        "       resolvedDate, closedDate, activatedCount"
        f" FROM zentao_bug"
        f" WHERE instance_id = {zt_instance}"
        f"   AND deleted = '0'"
        f"   AND status != '已关闭'"
        f"   AND severity = {ZENTAO_SEVERE_SEVERITY}"
        f"   AND TRIM(openedBy) IN {_in_clause(zt_cfg['users'])}"
        + _project_exclusion("zentao", zt_instance, "zentao_bug", "projectName", zt_ignored)
        + " ORDER BY openedDate DESC"
    )
    zt_rows = _execute_query(conn, zt_sql)
    result["zentao"] = {
        "instance_id": zt_instance,
        "total": len(zt_rows),
        "bugs": zt_rows,
    }

    # --- Redmine ---
    rm_cfg = config["redmine"]
    rm_instance = rm_cfg["instance_id"]
    rm_ignored = rm_cfg.get("ignored_projects", [])

    rm_sql = (
        "SELECT record_id, issue_id, project_id, project_name, tracker_name,"
        "       status_name, priority_name, author_name, assigned_to_name,"
        "       subject, created_on, updated_on, closed_on, done_ratio"
        f" FROM redmine_issue"
        f" WHERE instance_id = {rm_instance}"
        f"   AND status_name != '已关闭'"
        f"   AND priority_name LIKE '%{REDMINE_SEVERE_SUFFIX}'"
        f"   AND TRIM(author_name) IN {_in_clause(rm_cfg['users'])}"
        + _project_exclusion("redmine", rm_instance, "redmine_issue", "project_name", rm_ignored)
        + " ORDER BY created_on DESC"
    )
    rm_rows = _execute_query(conn, rm_sql)
    result["redmine"] = {
        "instance_id": rm_instance,
        "total": len(rm_rows),
        "issues": rm_rows,
    }

    print(json.dumps(result, ensure_ascii=False, indent=2, cls=_DecimalEncoder))
    return 0


# ---------------------------------------------------------------------------
# closures sub-command — 本周用户组关闭的缺陷
# ---------------------------------------------------------------------------


def cmd_closures(conn: Any, config: dict[str, Any], args: argparse.Namespace) -> int:
    """窗口内用户组关闭的缺陷（禅道 closedBy / Redmine journal 关闭人）。"""
    since, until = _resolve_window(args)

    result: dict[str, Any] = {
        "window": {"start": since, "end": until},
    }

    # --- Zentao ---
    zt_cfg = config["zentao"]
    zt_users = zt_cfg["users"]
    zt_instance = zt_cfg["instance_id"]
    zt_ignored = zt_cfg.get("ignored_projects", [])

    if zt_users:
        zt_sql = (
            "SELECT id, project, projectName, module, title, severity, pri, status,"
            "       openedBy, assignedTo, closedBy, resolution,"
            "       openedDate, resolvedDate, closedDate"
            f" FROM zentao_bug"
            f" WHERE instance_id = {zt_instance}"
            f"   AND deleted = '0'"
            f"   AND TRIM(closedBy) IN {_in_clause(zt_users)}"
            f"   AND closedDate >= '{since}'"
            f"   AND closedDate <  '{until}'"
            + _project_exclusion("zentao", zt_instance, "zentao_bug", "projectName", zt_ignored)
            + " ORDER BY closedDate DESC"
        )
        zt_rows = _execute_query(conn, zt_sql)

        by_user_zt: dict[str, int] = {}
        by_project_zt: dict[str, int] = {}
        for row in zt_rows:
            u = row.get("closedBy") or "unknown"
            p = row.get("projectName") or f"project-{row.get('project', '?')}"
            by_user_zt[u] = by_user_zt.get(u, 0) + 1
            by_project_zt[p] = by_project_zt.get(p, 0) + 1

        result["zentao"] = {
            "instance_id": zt_instance,
            "total": len(zt_rows),
            "by_user": by_user_zt,
            "by_project": by_project_zt,
            "bugs": zt_rows,
        }
    else:
        result["zentao"] = {"instance_id": zt_instance, "total": 0, "bugs": []}

    # --- Redmine ---
    rm_cfg = config["redmine"]
    rm_users = rm_cfg["users"]
    rm_instance = rm_cfg["instance_id"]
    rm_ignored = rm_cfg.get("ignored_projects", [])

    if rm_users:
        # 关闭人 = 把 status 改成「已关闭」那条 journal 的 user_name；
        # 「已关闭」的 status_id 从 redmine_issue 反查（库里未同步 is_closed 标志）。
        rm_sql = (
            "SELECT ri.issue_id, ri.project_id, ri.project_name, ri.tracker_name,"
            "       ri.status_name, ri.priority_name, ri.author_name,"
            "       ri.assigned_to_name, ri.subject, ri.created_on, ri.closed_on,"
            "       j.user_name AS closed_by, j.created_on AS closed_at"
            " FROM redmine_issue_journal j"
            " JOIN redmine_issue_journal_detail jd"
            "   ON j.journal_id = jd.journal_id AND j.instance_id = jd.instance_id"
            " JOIN redmine_issue ri"
            "   ON j.issue_id = ri.issue_id AND j.instance_id = ri.instance_id"
            f" WHERE j.instance_id = {rm_instance}"
            f"   AND TRIM(j.user_name) IN {_in_clause(rm_users)}"
            f"   AND jd.name = 'status_id'"
            "   AND jd.new_value IN ("
            "       SELECT DISTINCT ri2.status_id FROM redmine_issue ri2"
            f"       WHERE ri2.instance_id = {rm_instance} AND ri2.status_name = '已关闭'"
            "   )"
            f"   AND j.created_on >= '{since}'"
            f"   AND j.created_on <  '{until}'"
            + _project_exclusion("redmine", rm_instance, "ri", "project_name", rm_ignored)
            + " ORDER BY j.created_on DESC"
        )
        rm_rows = _execute_query(conn, rm_sql)

        by_user_rm: dict[str, int] = {}
        by_project_rm: dict[str, int] = {}
        for row in rm_rows:
            u = row.get("closed_by") or row.get("user_name") or "unknown"
            p = row.get("project_name") or f"project-{row.get('project_id', '?')}"
            by_user_rm[u] = by_user_rm.get(u, 0) + 1
            by_project_rm[p] = by_project_rm.get(p, 0) + 1

        result["redmine"] = {
            "instance_id": rm_instance,
            "total": len(rm_rows),
            "by_user": by_user_rm,
            "by_project": by_project_rm,
            "issues": rm_rows,
        }
    else:
        result["redmine"] = {"instance_id": rm_instance, "total": 0, "issues": []}

    print(json.dumps(result, ensure_ascii=False, indent=2, cls=_DecimalEncoder))
    return 0


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    """构建 CLI 参数解析器。"""
    parser = argparse.ArgumentParser(
        description="Bug Analysis — 测试组缺陷提交/超期/严重/关闭分析",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    sub_p = sub.add_parser("submissions", help="窗口内用户组提交的缺陷（含严重+零提交）")
    sub_p.add_argument("--since", help="开始时间 (YYYY-MM-DD 或 YYYY-MM-DD HH:MM:SS)")
    sub_p.add_argument("--until", help="结束时间 (默认: 当前时间)")

    sub.add_parser("overdue", help="当前超期未处理的缺陷（固定 7 天阈值）")

    sub.add_parser("severe", help="全库当前未关闭的严重缺陷")

    sub_c = sub.add_parser("closures", help="窗口内用户组关闭的缺陷")
    sub_c.add_argument("--since", help="开始时间 (YYYY-MM-DD 或 YYYY-MM-DD HH:MM:SS)")
    sub_c.add_argument("--until", help="结束时间 (默认: 当前时间)")

    return parser


_COMMANDS = {
    "submissions": cmd_submissions,
    "overdue": cmd_overdue,
    "severe": cmd_severe,
    "closures": cmd_closures,
}


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    """入口：解析参数 → 加载配置 → 连接 DB → 执行子命令。"""
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        config = load_analysis_config()
    except ConfigError as exc:
        print(f"配置错误: {exc}", file=sys.stderr)
        return 1

    try:
        conn = get_mysql_connection(system_name="ticket")
    except ConfigError as exc:
        print(f"数据库连接错误: {exc}", file=sys.stderr)
        return 1

    try:
        return _COMMANDS[args.command](conn, config, args)
    finally:
        if conn.is_connected():
            conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
