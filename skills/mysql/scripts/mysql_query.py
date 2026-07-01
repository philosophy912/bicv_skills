#!/usr/bin/env python3
"""MySQL Query Script — INSERT, UPDATE, SELECT only.

No DELETE, DROP, TRUNCATE, ALTER, CREATE, GRANT, REVOKE, SHOW, DESCRIBE.

Supports multiple MySQL server instances via ``~/.bicv/mysql.json`` and the
local ``system_config`` module (same path-traversal protection and system
matching as Gerrit / Jenkins).

Usage:
    python3 mysql_query.py select "SELECT * FROM users LIMIT 10"
    python3 mysql_query.py select "SELECT * FROM users LIMIT 10" --system prod
    python3 mysql_query.py insert @queries/insert_user.sql
    python3 mysql_query.py update @queries/update_user.sql
    python3 mysql_query.py select "SELECT 1" -d my_database
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from decimal import Decimal
from pathlib import Path
from typing import Any

# --- config module (local copy, same path-traversal protection and system
# matching as Gerrit / Jenkins) ----------------------------------------------
from _mysql_config import (
    MySQLConnectionConfig,
    ServiceError,
    print_error,
    resolve_mysql_config,
)

# --- mysql-connector guard (only needed at runtime) -------------------------
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
# SQL validation
# ---------------------------------------------------------------------------

BLOCKED_PATTERNS: tuple[str, ...] = (
    r"\bDELETE\b",
    r"\bDROP\b",
    r"\bTRUNCATE\b",
    r"\bALTER\b",
    r"\bCREATE\b",
    r"\bGRANT\b",
    r"\bREVOKE\b",
    r"\bSHOW\b",
    r"\bDESCRIBE\b",
)

_STRING_RE: re.Pattern[str] = re.compile(
    r"'(?:''|\\'|[^'])*'"
    r'|"(?:""|\\"|[^"])*"'
    r"|`(?:``|[^`])*`",
)


def validate_sql(sql: str) -> tuple[bool, str | None]:
    """Validate SQL to ensure it only contains allowed operations.

    Strips comments and string literals before checking for blocked keywords
    so that values like ``SELECT 'DELETE flag' FROM t`` are not falsely rejected.
    """
    sql_upper = sql.upper()

    # MySQL 条件注释 /*!...*/ 是可执行注释，不能当普通注释删除（否则其中的
    # DELETE 等关键词会绕过检测）。直接拒绝含条件注释的 SQL。
    if re.search(r"/\*\s*!", sql):
        return False, "CONDITIONAL COMMENT"

    sql_clean = re.sub(r"--.*$", "", sql_upper, flags=re.MULTILINE)
    sql_clean = re.sub(r"/\*.*?\*/", "", sql_clean, flags=re.DOTALL)
    sql_clean = _STRING_RE.sub("", sql_clean)

    for pattern in BLOCKED_PATTERNS:
        match = re.search(pattern, sql_clean)
        if match:
            return False, match.group()

    sql_stripped = sql_clean.strip()
    allowed_starts = ("SELECT", "INSERT", "UPDATE", "WITH")
    if not any(sql_stripped.startswith(k) for k in allowed_starts):
        return False, sql_stripped.split()[0] if sql_stripped else "UNKNOWN"

    return True, None


# ---------------------------------------------------------------------------
# SQL source helpers
# ---------------------------------------------------------------------------


def read_sql_file(sql_source: str) -> str:
    """Read SQL from a file (``@path``) or return *sql_source* as-is.

    ``@path`` 由用户显式指定、按原样读取（不做目录限制）；拒绝含 NUL 字节的
    路径以防截断攻击。注意：与 ``_mysql_config`` 的凭据解析不同，本函数不施加
    路径遍历限制——用户对自己指定的 SQL 文件负责。
    """
    if not sql_source.startswith("@"):
        return sql_source

    file_path = sql_source[1:]
    if "\x00" in file_path:
        raise ServiceError(f"SQL file path contains NUL byte: {file_path!r}")
    try:
        return Path(file_path).read_text(encoding="utf-8-sig")
    except FileNotFoundError as exc:
        raise ServiceError(f"SQL file not found: {file_path}") from exc
    except OSError as exc:
        raise ServiceError(f"Error reading SQL file {file_path}: {exc}") from exc


# ---------------------------------------------------------------------------
# MySQL connection
# ---------------------------------------------------------------------------


def get_connection(
    config: MySQLConnectionConfig,
    database: str | None = None,
) -> Any:
    """Create a MySQL connection from resolved *config*."""
    host = config.host
    port = config.port
    user = config.username
    password = config.password

    if not host or not user:
        missing: list[str] = []
        if not host:
            missing.append("host")
        if not user:
            missing.append("username")
        raise ServiceError(
            f"Missing required connection parameters in ~/.bicv/mysql.json: {', '.join(missing)}"
        )

    target_db = database or config.database
    if not target_db:
        raise ServiceError(
            "No database specified; set 'database' in ~/.bicv/mysql.json or use -d flag"
        )

    try:
        connection = mysql.connector.connect(
            host=host,
            port=port,
            database=target_db,
            user=user,
            password=password or "",
            ssl_disabled=True,
        )
        return connection
    except MySQLError as exc:
        raise ServiceError(f"Error connecting to MySQL at {host}:{port}: {exc}") from exc


# ---------------------------------------------------------------------------
# Output formatting
# ---------------------------------------------------------------------------


class _DecimalEncoder(json.JSONEncoder):
    """JSON encoder that converts Decimal to int or float."""

    def default(self, o: Any) -> Any:
        if isinstance(o, Decimal):
            return int(o) if o == int(o) else float(o)
        return super().default(o)


def format_results(columns: list[str], rows: list[tuple[Any, ...]]) -> None:
    """Format and print query results as a table.

    目前 execute_query 走 JSON 信封路径，不再调用本函数；保留供未来
    ``--format human`` 表格输出使用。
    """
    if not columns:
        return

    widths = [len(str(col)) for col in columns]
    formatted_rows: list[list[str]] = []
    for row in rows:
        formatted_row = [str(val) for val in row]
        for i, val in enumerate(formatted_row):
            widths[i] = max(widths[i], len(val))
        formatted_rows.append(formatted_row)

    header = " | ".join(str(col).ljust(widths[i]) for i, col in enumerate(columns))
    print(header)
    print("-" * len(header))

    for row in formatted_rows:
        print(" | ".join(val.ljust(widths[i]) for i, val in enumerate(row)))


# ---------------------------------------------------------------------------
# Query execution
# ---------------------------------------------------------------------------


def execute_query(
    connection: Any,
    sql: str,
    operation: str,
) -> dict[str, Any]:
    """Execute a SQL query and return a structured result dict.

    select -> ``{"columns", "rows", "total", "truncated"}``
    insert/update -> ``{"affected_rows"}``

    由 main() 包成 ``{"system", "data": <本 dict>}`` 信封输出到 stdout。
    """
    is_valid, blocked_keyword = validate_sql(sql)
    if not is_valid:
        raise ServiceError(
            f"Operation '{blocked_keyword}' is not permitted by this skill.\n"
            f"Only SELECT, INSERT, and UPDATE operations are allowed."
        )

    cursor = connection.cursor()
    try:
        if operation == "select":
            cursor.execute(sql)

            columns = [desc[0] for desc in cursor.description] if cursor.description else []

            BATCH_SIZE = 1000
            rows: list[tuple[Any, ...]] = []
            total = 0

            while True:
                batch = cursor.fetchmany(BATCH_SIZE)
                if not batch:
                    break
                rows.extend(batch)
                total += len(batch)

            truncated = False
            if total > 10000:
                rows = rows[:10000]
                truncated = True

            return {
                "columns": columns,
                "rows": [list(r) for r in rows],
                "total": total,
                "truncated": truncated,
            }

        else:
            cursor.execute(sql)
            connection.commit()
            return {"affected_rows": cursor.rowcount}

    except MySQLError as exc:
        connection.rollback()
        raise ServiceError(f"Error executing query: {exc}") from exc
    finally:
        cursor.close()


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "MySQL Query Tool — SELECT, INSERT, UPDATE only. "
            "Blocked: DELETE, DROP, TRUNCATE, ALTER, CREATE, "
            "GRANT, REVOKE, SHOW, DESCRIBE."
        ),
    )
    parser.add_argument(
        "operation",
        choices=["select", "insert", "update"],
        help="Type of SQL operation",
    )
    parser.add_argument(
        "sql",
        help="SQL query or @filename for SQL file",
    )
    parser.add_argument(
        "-d",
        "--database",
        dest="database",
        default=None,
        help="Target database (overrides default database)",
    )
    parser.add_argument(
        "--system",
        dest="system",
        default=None,
        help=("MySQL system name from ~/.bicv/mysql.json (default: uses default_system)"),
    )
    return parser


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    config = resolve_mysql_config(system=args.system, config_name="mysql.json")
    sql = read_sql_file(args.sql)
    connection = get_connection(config, args.database)

    try:
        result = execute_query(connection, sql, args.operation)
        print(
            json.dumps(
                {"system": config.system_name, "data": result},
                ensure_ascii=False,
                indent=2,
                cls=_DecimalEncoder,
            )
        )
        return 0
    finally:
        if connection.is_connected():
            connection.close()


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except ServiceError as err:
        raise SystemExit(print_error(err)) from err
