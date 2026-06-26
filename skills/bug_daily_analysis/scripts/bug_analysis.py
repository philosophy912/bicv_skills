#!/usr/bin/env python3
"""Bug Daily Analysis — 测试组缺陷提交与超期跟踪。

两个子命令：
    submissions  – 按提交时间框，查用户组提交的缺陷（禅道+Redmine）
    overdue      – 当前超期未处理的缺陷（指派>N天、用户组无任何 action）

依赖：
    mysql-connector-python（与 mysql skill 共享）
    ~/.bicv/bug_daily_analysis.json（用户组 + 规则）
    ~/.bicv/mysql.json（DB 连接，system=ticket）
"""

from __future__ import annotations

import argparse
import json
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

CONFIG_NAME = "bug_daily_analysis.json"
MYSQL_CONFIG_NAME = "mysql.json"


class ConfigError(Exception):
    """配置加载错误。"""


def _load_json_config(filename: str) -> dict[str, Any]:
    """从 ~/.bicv/<filename> 加载 JSON 配置。"""
    path = Path.home() / ".bicv" / filename
    if not path.exists():
        raise ConfigError(f"配置文件不存在: {path}\n请创建 ~/.bicv/{filename}")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ConfigError(f"配置文件 JSON 格式错误: {path}\n{exc}") from exc


def _validate_users(section: dict[str, Any], sys_name: str) -> list[str]:
    """校验并返回 user 列表。"""
    users = section.get("users")
    if not isinstance(users, list) or not users:
        raise ConfigError(f"[{CONFIG_NAME}] {sys_name}.users 必须是非空列表")
    return [str(u).strip() for u in users if str(u).strip()]


def load_analysis_config() -> dict[str, Any]:
    """加载并校验 bug_daily_analysis.json。"""
    config = _load_json_config(CONFIG_NAME)

    for sys_name in ("zentao", "redmine"):
        section = config.get(sys_name)
        if not isinstance(section, dict):
            raise ConfigError(
                f"[{CONFIG_NAME}] 缺少 '{sys_name}' 段，需配置 instance_id 和 users 列表"
            )
        if "instance_id" not in section:
            raise ConfigError(f"[{CONFIG_NAME}] {sys_name}.instance_id 是必填项")
        # Validate users — store cleaned list
        section["users"] = _validate_users(section, sys_name)

    overdue_days = config.get("overdue_days", 7)
    try:
        overdue_days = int(overdue_days)
    except (TypeError, ValueError) as exc:
        raise ConfigError(
            f"[{CONFIG_NAME}] overdue_days 必须是正整数，当前值: {overdue_days!r}"
        ) from exc
    if overdue_days <= 0:
        raise ConfigError(f"[{CONFIG_NAME}] overdue_days 必须是正整数，当前值: {overdue_days}")
    config["overdue_days"] = overdue_days

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
    """把用户名列表拼成 SQL IN 子句（值来自可信配置文件，做最小转义）。"""
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


def _resolve_window(args: argparse.Namespace) -> tuple[str, str]:
    """解析时间窗口，返回 (since, until) 字符串（YYYY-MM-DD HH:MM:SS）。"""
    if args.until:
        until = args.until
    else:
        until = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    if args.since:
        since = args.since
    else:
        since = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d 00:00:00")

    if len(since) == 10:  # date only
        since += " 00:00:00"
    if len(until) == 10:
        until += " 23:59:59"

    return since, until


# ---------------------------------------------------------------------------
# submissions sub-command
# ---------------------------------------------------------------------------


def cmd_submissions(conn: Any, config: dict[str, Any], args: argparse.Namespace) -> int:
    """窗口内用户组提交的缺陷。"""
    since, until = _resolve_window(args)

    result: dict[str, Any] = {
        "window": {"start": since, "end": until},
    }

    # --- Zentao ---
    zt_cfg = config["zentao"]
    zt_users = zt_cfg["users"]
    zt_instance = zt_cfg["instance_id"]

    if zt_users:
        zt_sql = (
            "SELECT id, project, projectName, module, type, severity, pri,"
            "       status, openedBy, assignedTo, resolution,"
            "       openedDate, resolvedDate, closedDate, activatedCount"
            f" FROM zentao_bug"
            f" WHERE instance_id = {zt_instance}"
            f"   AND TRIM(openedBy) IN {_in_clause(zt_users)}"
            f"   AND openedDate >= '{since}'"
            f"   AND openedDate <  '{until}'"
            f"   AND deleted = '0'"
            f" ORDER BY openedDate DESC"
        )
        zt_rows = _execute_query(conn, zt_sql)

        by_user: dict[str, int] = {}
        by_project: dict[str, int] = {}
        for row in zt_rows:
            u = row.get("openedBy") or "unknown"
            p = row.get("projectName") or f"project-{row.get('project', '?')}"
            by_user[u] = by_user.get(u, 0) + 1
            by_project[p] = by_project.get(p, 0) + 1

        result["zentao"] = {
            "instance_id": zt_instance,
            "total": len(zt_rows),
            "by_user": by_user,
            "by_project": by_project,
            "bugs": zt_rows,
        }
    else:
        result["zentao"] = {"instance_id": zt_instance, "total": 0, "bugs": []}

    # --- Redmine ---
    rm_cfg = config["redmine"]
    rm_users = rm_cfg["users"]
    rm_instance = rm_cfg["instance_id"]

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
            f" ORDER BY created_on DESC"
        )
        rm_rows = _execute_query(conn, rm_sql)

        by_user_rm: dict[str, int] = {}
        by_project_rm: dict[str, int] = {}
        for row in rm_rows:
            u = row.get("author_name") or "unknown"
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
# overdue sub-command
# ---------------------------------------------------------------------------


def cmd_overdue(conn: Any, config: dict[str, Any], args: argparse.Namespace) -> int:
    """当前超期未处理的缺陷（指派 > overdue_days 天，用户组无 action）。"""
    overdue_days = config["overdue_days"]

    result: dict[str, Any] = {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "overdue_days": overdue_days,
    }

    # --- Zentao ---
    zt_cfg = config["zentao"]
    zt_users = zt_cfg["users"]
    zt_instance = zt_cfg["instance_id"]

    if zt_users:
        user_in = _in_clause(zt_users)
        zt_sql = (
            "SELECT b.id, b.project, b.projectName, b.module, b.severity, b.pri,"
            "       b.status, b.assignedTo, b.openedBy, b.openedDate,"
            "       b.resolution, b.activatedCount,"
            "       COALESCE(last_act.action_date, b.openedDate) AS last_user_action,"
            "       DATEDIFF(NOW(), COALESCE(last_act.action_date, b.openedDate))"
            "         AS days_since_action"
            " FROM zentao_bug b"
            " LEFT JOIN ("
            "     SELECT zentao_bug_id, MAX(date) AS action_date"
            "     FROM zentao_bug_action"
            f"     WHERE instance_id = {zt_instance}"
            f"       AND TRIM(actor) IN {user_in}"
            "     GROUP BY zentao_bug_id"
            " ) last_act ON b.id = last_act.zentao_bug_id"
            f" WHERE b.instance_id = {zt_instance}"
            f"   AND b.deleted = '0'"
            f"   AND b.status != '已关闭'"
            f"   AND TRIM(b.assignedTo) IN {user_in}"
            f"   AND DATEDIFF(NOW(), COALESCE(last_act.action_date, b.openedDate))"
            f"     > {overdue_days}"
            + _exclude_inactive_project_clause("zentao", zt_instance, "b", "projectName")
            + " ORDER BY last_act.action_date ASC"
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

    if rm_users:
        user_in_rm = _in_clause(rm_users)
        rm_sql = (
            "SELECT ri.issue_id, ri.project_id, ri.project_name, ri.tracker_name,"
            "       ri.status_name, ri.priority_name, ri.author_name,"
            "       ri.assigned_to_name, ri.subject,"
            "       ri.created_on, ri.updated_on, ri.closed_on,"
            "       COALESCE(last_j.created_on, ri.created_on) AS last_user_action,"
            "       DATEDIFF(NOW(), COALESCE(last_j.created_on, ri.created_on))"
            "         AS days_since_action"
            " FROM redmine_issue ri"
            " LEFT JOIN ("
            "     SELECT issue_id, MAX(created_on) AS created_on"
            "     FROM redmine_issue_journal"
            f"     WHERE instance_id = {rm_instance}"
            f"       AND TRIM(user_name) IN {user_in_rm}"
            "     GROUP BY issue_id"
            " ) last_j ON ri.issue_id = last_j.issue_id"
            f" WHERE ri.instance_id = {rm_instance}"
            f"   AND ri.status_name NOT IN ('已关闭', '已拒绝')"
            f"   AND TRIM(ri.assigned_to_name) IN {user_in_rm}"
            f"   AND DATEDIFF(NOW(), COALESCE(last_j.created_on, ri.created_on))"
            f"     > {overdue_days}"
            + _exclude_inactive_project_clause("redmine", rm_instance, "ri", "project_name")
            + " ORDER BY last_j.created_on ASC"
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
# CLI
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    """构建 CLI 参数解析器。"""
    parser = argparse.ArgumentParser(
        description="Bug Daily Analysis — 测试组缺陷提交与超期跟踪",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    sub_p = sub.add_parser("submissions", help="窗口内用户组提交的缺陷")
    sub_p.add_argument("--since", help="开始时间 (YYYY-MM-DD 或 YYYY-MM-DD HH:MM:SS)")
    sub_p.add_argument("--until", help="结束时间 (默认: 当前时间)")

    sub.add_parser("overdue", help="当前超期未处理的缺陷")

    return parser


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
        if args.command == "submissions":
            return cmd_submissions(conn, config, args)
        return cmd_overdue(conn, config, args)
    finally:
        if conn.is_connected():
            conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
