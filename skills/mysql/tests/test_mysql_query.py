"""Tests for mysql_query.py — SQL validation, file reading, connection,
result formatting, query execution, CLI parsing, and main()."""

from __future__ import annotations

from unittest import mock

import mysql_query
import pytest
from mysql.connector import Error as MySQLError

from _mysql_config import MySQLConnectionConfig, ServiceError

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _config(**overrides):
    """Build a MySQLConnectionConfig with sane defaults."""
    defaults = dict(
        host="db.example.com",
        port=3306,
        database="appdb",
        username="dbuser",
        password="dbpass",
        system_name=None,
    )
    defaults.update(overrides)
    return MySQLConnectionConfig(**defaults)


def _mock_cursor(*, description=None, rowcount=0, batches=None):
    """Build a mock cursor.

    *batches* is a list of batches (each a list of row tuples) returned
    successively by ``fetchmany``. After the batches are exhausted,
    ``fetchmany`` returns ``[]`` to terminate the fetch loop.
    """
    cursor = mock.MagicMock()
    cursor.description = description
    cursor.rowcount = rowcount
    if batches is None:
        batches = [[]]
    it = iter(list(batches) + [[]])

    def _fetchmany(size):
        try:
            return next(it)
        except StopIteration:
            return []

    cursor.fetchmany.side_effect = _fetchmany
    return cursor


def _mock_connection(cursor):
    conn = mock.MagicMock()
    conn.cursor.return_value = cursor
    conn.is_connected.return_value = True
    return conn


# ===========================================================================
# validate_sql
# ===========================================================================


class TestValidateSqlAllowed:
    @pytest.mark.parametrize(
        "sql",
        [
            "SELECT * FROM users",
            "INSERT INTO users (id) VALUES (1)",
            "UPDATE users SET name='x' WHERE id=1",
            "WITH cte AS (SELECT 1) SELECT * FROM cte",
            "  select * from t",  # lowercase + leading whitespace
            "/* leading comment */ SELECT 1",
            "-- comment\nSELECT 1",
        ],
    )
    def test_allowed_starts(self, sql):
        ok, kw = mysql_query.validate_sql(sql)
        assert ok is True
        assert kw is None


class TestValidateSqlBlocked:
    @pytest.mark.parametrize(
        "sql,keyword",
        [
            ("DELETE FROM users WHERE id=1", "DELETE"),
            ("DROP TABLE users", "DROP"),
            ("TRUNCATE TABLE users", "TRUNCATE"),
            ("ALTER TABLE users ADD col INT", "ALTER"),
            ("CREATE TABLE users (id INT)", "CREATE"),
            ("GRANT SELECT ON *.* TO 'x'@'%'", "GRANT"),
            ("REVOKE ALL FROM 'x'@'%'", "REVOKE"),
            ("SHOW TABLES", "SHOW"),
            ("DESCRIBE users", "DESCRIBE"),
        ],
    )
    def test_blocked_keywords(self, sql, keyword):
        ok, kw = mysql_query.validate_sql(sql)
        assert ok is False
        assert kw == keyword


class TestValidateSqlFalseNegatives:
    def test_delete_inside_string_literal_passes(self):
        # The word DELETE appears inside a string literal — must NOT be blocked.
        ok, kw = mysql_query.validate_sql("SELECT 'DELETE flag' FROM t")
        assert ok is True
        assert kw is None

    def test_drop_inside_double_quoted_string_passes(self):
        ok, kw = mysql_query.validate_sql('SELECT "DROP this" FROM t')
        assert ok is True
        assert kw is None

    def test_create_inside_backtick_identifier_passes(self):
        ok, kw = mysql_query.validate_sql("SELECT `CREATE` FROM t")
        assert ok is True
        assert kw is None

    def test_keyword_in_line_comment_not_blocked(self):
        ok, kw = mysql_query.validate_sql("SELECT 1 -- DELETE everything\nFROM dual")
        assert ok is True
        assert kw is None

    def test_keyword_in_block_comment_not_blocked(self):
        ok, kw = mysql_query.validate_sql("SELECT 1 /* DROP TABLE x */ FROM dual")
        assert ok is True
        assert kw is None


class TestValidateSqlEdgeCases:
    def test_non_allowed_start_returns_false_with_keyword(self):
        ok, kw = mysql_query.validate_sql("EXPLAIN SELECT * FROM users")
        assert ok is False
        assert kw == "EXPLAIN"

    def test_empty_string_returns_false(self):
        ok, kw = mysql_query.validate_sql("")
        assert ok is False
        assert kw == "UNKNOWN"

    def test_whitespace_only_returns_false(self):
        ok, kw = mysql_query.validate_sql("   \n\t  ")
        assert ok is False
        assert kw == "UNKNOWN"

    def test_blocked_keyword_takes_precedence_over_allowed_start(self):
        # Even though it starts with SELECT, the embedded DROP must block it.
        ok, kw = mysql_query.validate_sql("SELECT * FROM a; DROP TABLE b")
        assert ok is False
        assert kw == "DROP"


# ===========================================================================
# read_sql_file
# ===========================================================================


class TestReadSqlFile:
    def test_plain_sql_returned_as_is(self):
        sql = "SELECT * FROM users"
        assert mysql_query.read_sql_file(sql) == sql

    def test_at_prefix_reads_file(self, tmp_path):
        f = tmp_path / "q.sql"
        f.write_text("SELECT 1;", encoding="utf-8")
        assert mysql_query.read_sql_file(f"@{f}") == "SELECT 1;"

    def test_missing_file_raises_service_error(self):
        with pytest.raises(ServiceError) as exc_info:
            mysql_query.read_sql_file("@/no/such/path/here.sql")
        assert "SQL file not found" in str(exc_info.value)

    def test_oserror_raises_service_error(self, tmp_path):
        # A directory is not a readable file -> OSError (IsADirectoryError).
        with pytest.raises(ServiceError) as exc_info:
            mysql_query.read_sql_file(f"@{tmp_path}")
        assert "Error reading SQL file" in str(exc_info.value)


# ===========================================================================
# get_connection
# ===========================================================================


class TestGetConnection:
    def test_missing_host_raises(self):
        cfg = _config(host="")
        with pytest.raises(ServiceError) as exc_info:
            mysql_query.get_connection(cfg)
        assert "host" in str(exc_info.value)

    def test_missing_username_raises(self):
        cfg = _config(username="")
        with pytest.raises(ServiceError) as exc_info:
            mysql_query.get_connection(cfg)
        assert "username" in str(exc_info.value)

    def test_missing_both_host_and_username_lists_both(self):
        cfg = _config(host="", username="")
        with pytest.raises(ServiceError) as exc_info:
            mysql_query.get_connection(cfg)
        msg = str(exc_info.value)
        assert "host" in msg
        assert "username" in msg

    def test_no_database_raises(self):
        cfg = _config(database=None)
        with pytest.raises(ServiceError) as exc_info:
            mysql_query.get_connection(cfg, database=None)
        assert "No database specified" in str(exc_info.value)

    def test_database_flag_overrides_missing_config_db(self):
        cfg = _config(database=None)
        with mock.patch("mysql_query.mysql.connector.connect") as m:
            m.return_value = "CONN"
            result = mysql_query.get_connection(cfg, database="flagdb")
        assert result == "CONN"
        _, kwargs = m.call_args
        assert kwargs["database"] == "flagdb"
        assert kwargs["host"] == "db.example.com"
        assert kwargs["user"] == "dbuser"
        assert kwargs["password"] == "dbpass"
        assert kwargs["port"] == 3306
        assert kwargs["ssl_disabled"] is True

    def test_successful_connection_uses_config_db(self):
        cfg = _config()
        with mock.patch("mysql_query.mysql.connector.connect") as m:
            m.return_value = "CONN"
            result = mysql_query.get_connection(cfg)
        assert result == "CONN"
        assert m.call_args.kwargs["database"] == "appdb"

    def test_empty_password_passes_blank(self):
        cfg = _config(password="")
        with mock.patch("mysql_query.mysql.connector.connect") as m:
            m.return_value = "CONN"
            mysql_query.get_connection(cfg)
        assert m.call_args.kwargs["password"] == ""

    def test_connection_failure_raises_service_error(self):
        cfg = _config()
        with mock.patch("mysql_query.mysql.connector.connect") as m:
            m.side_effect = MySQLError("conn refused")
            with pytest.raises(ServiceError) as exc_info:
                mysql_query.get_connection(cfg)
        assert "Error connecting to MySQL" in str(exc_info.value)


# ===========================================================================
# format_results
# ===========================================================================


class TestFormatResults:
    def test_empty_columns_returns_without_output(self, capsys):
        mysql_query.format_results([], [(1, 2)])
        out = capsys.readouterr().out
        assert out == ""

    def test_multi_column_multi_row_alignment(self, capsys):
        columns = ["id", "name"]
        rows = [(1, "al"), (22, "bob")]
        mysql_query.format_results(columns, rows)
        out = capsys.readouterr().out
        lines = out.rstrip("\n").split("\n")
        # Header: "id".ljust(2) + " | " + "name".ljust(4) -> "id | name"
        assert lines[0] == "id | name"
        assert lines[1] == "-" * len(lines[0])
        # Column widths: id = max(2, 1, 2) = 2; name = max(4, 2, 3) = 4.
        # values left-justified to those widths.
        assert lines[2] == "1  | al  "
        assert lines[3] == "22 | bob "

    def test_single_column_single_row(self, capsys):
        mysql_query.format_results(["cnt"], [(5,)])
        out = capsys.readouterr().out
        assert "cnt" in out
        assert "5" in out


# ===========================================================================
# execute_query
# ===========================================================================


class TestExecuteQuerySelect:
    def test_select_normal_path(self, capsys):
        cursor = _mock_cursor(
            description=[("id",), ("name",)],
            batches=[[(1, "al"), (2, "bob")]],
        )
        conn = _mock_connection(cursor)
        mysql_query.execute_query(conn, "SELECT id, name FROM t", "select")
        out = capsys.readouterr().out
        assert "id" in out and "name" in out
        assert "2 row(s) returned" in out
        conn.commit.assert_not_called()
        cursor.close.assert_called_once()

    def test_select_description_none_columns_empty(self, capsys):
        # cursor.description is None -> columns == [] -> format_results is a no-op,
        # but the "N row(s) returned" line still prints.
        cursor = _mock_cursor(description=None, batches=[[(1,), (2,)]])
        conn = _mock_connection(cursor)
        mysql_query.execute_query(conn, "SELECT 1", "select")
        out = capsys.readouterr().out
        assert "2 row(s) returned" in out
        # No table header printed since columns is empty.
        assert " | " not in out

    def test_select_fetchmany_multiple_batches(self, capsys):
        # Two non-empty batches then an empty one to terminate.
        batch1 = [(i,) for i in range(1000)]
        batch2 = [(i,) for i in range(1000, 1500)]
        cursor = _mock_cursor(
            description=[("n",)],
            batches=[batch1, batch2],
        )
        conn = _mock_connection(cursor)
        mysql_query.execute_query(conn, "SELECT n FROM t", "select")
        out = capsys.readouterr().out
        assert "1500 row(s) returned" in out
        # fetchmany called until it returned []
        assert cursor.fetchmany.call_count >= 3

    def test_select_truncated_over_10000_rows(self, capsys):
        # 3 batches of 5000 = 15000 total -> truncation branch.
        batches = [[(i,) for i in range(k * 5000, (k + 1) * 5000)] for k in range(3)]
        cursor = _mock_cursor(description=[("n",)], batches=batches)
        conn = _mock_connection(cursor)
        mysql_query.execute_query(conn, "SELECT n FROM big", "select")
        out = capsys.readouterr().out
        assert "showing first 10000 of 15000 rows" in out
        assert "truncated for display" in out

    def test_select_zero_rows(self, capsys):
        cursor = _mock_cursor(description=[("id",)], batches=[[]])
        conn = _mock_connection(cursor)
        mysql_query.execute_query(conn, "SELECT id FROM empty", "select")
        out = capsys.readouterr().out
        assert "0 row(s) returned" in out


class TestExecuteQueryWrite:
    def test_insert_path_commits_and_prints_rowcount(self, capsys):
        cursor = _mock_cursor(rowcount=3)
        conn = _mock_connection(cursor)
        mysql_query.execute_query(conn, "INSERT INTO t (a) VALUES (1)", "insert")
        out = capsys.readouterr().out
        assert "3 row(s) affected" in out
        conn.commit.assert_called_once()
        cursor.close.assert_called_once()

    def test_update_path_commits_and_prints_rowcount(self, capsys):
        cursor = _mock_cursor(rowcount=7)
        conn = _mock_connection(cursor)
        mysql_query.execute_query(conn, "UPDATE t SET a=1 WHERE b=2", "update")
        out = capsys.readouterr().out
        assert "7 row(s) affected" in out
        conn.commit.assert_called_once()


class TestExecuteQueryErrors:
    def test_invalid_sql_raises_service_error(self):
        cursor = _mock_cursor()
        conn = _mock_connection(cursor)
        with pytest.raises(ServiceError) as exc_info:
            mysql_query.execute_query(conn, "DELETE FROM t", "delete")
        assert "not permitted" in str(exc_info.value)
        # validate_sql runs before cursor is even opened
        conn.cursor.assert_not_called()

    def test_mysql_error_rolls_back_and_raises(self):
        cursor = _mock_cursor()
        cursor.execute.side_effect = MySQLError("boom")
        conn = _mock_connection(cursor)
        with pytest.raises(ServiceError) as exc_info:
            mysql_query.execute_query(conn, "SELECT * FROM t", "select")
        assert "Error executing query" in str(exc_info.value)
        conn.rollback.assert_called_once()
        cursor.close.assert_called_once()

    def test_mysql_error_on_write_path_rolls_back(self):
        cursor = _mock_cursor(rowcount=0)
        cursor.execute.side_effect = MySQLError("write boom")
        conn = _mock_connection(cursor)
        with pytest.raises(ServiceError):
            mysql_query.execute_query(conn, "INSERT INTO t (a) VALUES (1)", "insert")
        conn.rollback.assert_called_once()
        conn.commit.assert_not_called()
        cursor.close.assert_called_once()


# ===========================================================================
# build_parser
# ===========================================================================


class TestBuildParser:
    def test_parses_select_operation(self):
        args = mysql_query.build_parser().parse_args(["select", "SELECT 1", "--system", "prod"])
        assert args.operation == "select"
        assert args.sql == "SELECT 1"
        assert args.system == "prod"
        assert args.database is None

    def test_parses_database_flag(self):
        args = mysql_query.build_parser().parse_args(["select", "SELECT 1", "-d", "mydb"])
        assert args.database == "mydb"

    def test_invalid_operation_exits(self):
        with pytest.raises(SystemExit):
            mysql_query.build_parser().parse_args(["delete", "DELETE FROM t"])

    def test_missing_sql_exits(self):
        with pytest.raises(SystemExit):
            mysql_query.build_parser().parse_args(["select"])

    def test_no_args_exits(self):
        with pytest.raises(SystemExit):
            mysql_query.build_parser().parse_args([])


# ===========================================================================
# main
# ===========================================================================


class TestMain:
    def test_success_path_closes_connection(self, capsys):
        cfg = _config(system_name="prod")
        conn = mock.MagicMock()
        conn.is_connected.return_value = True

        with (
            mock.patch("sys.argv", ["mysql_query.py", "select", "SELECT 1"]),
            mock.patch("mysql_query.resolve_mysql_config", return_value=cfg),
            mock.patch("mysql_query.read_sql_file", return_value="SELECT 1"),
            mock.patch("mysql_query.get_connection", return_value=conn),
            mock.patch("mysql_query.execute_query") as ex,
        ):
            rc = mysql_query.main()

        assert rc == 0
        ex.assert_called_once_with(conn, "SELECT 1", "select")
        # System name printed
        out = capsys.readouterr().out
        assert "System: prod" in out
        # finally block closed the connection
        conn.is_connected.assert_called_once()
        conn.close.assert_called_once()

    def test_success_path_skips_close_when_not_connected(self):
        cfg = _config(system_name=None)
        conn = mock.MagicMock()
        conn.is_connected.return_value = False

        with (
            mock.patch("sys.argv", ["mysql_query.py", "select", "SELECT 1"]),
            mock.patch("mysql_query.resolve_mysql_config", return_value=cfg),
            mock.patch("mysql_query.read_sql_file", return_value="SELECT 1"),
            mock.patch("mysql_query.get_connection", return_value=conn),
            mock.patch("mysql_query.execute_query"),
        ):
            rc = mysql_query.main()
        assert rc == 0
        conn.is_connected.assert_called_once()
        conn.close.assert_not_called()

    def test_no_system_name_not_printed(self, capsys):
        cfg = _config(system_name=None)
        conn = mock.MagicMock()
        conn.is_connected.return_value = True
        with (
            mock.patch("sys.argv", ["mysql_query.py", "select", "SELECT 1"]),
            mock.patch("mysql_query.resolve_mysql_config", return_value=cfg),
            mock.patch("mysql_query.read_sql_file", return_value="SELECT 1"),
            mock.patch("mysql_query.get_connection", return_value=conn),
            mock.patch("mysql_query.execute_query"),
        ):
            mysql_query.main()
        out = capsys.readouterr().out
        assert "System:" not in out

    def test_service_error_path_still_closes_connection(self):
        """execute_query raises ServiceError; the finally block must still run."""
        cfg = _config()
        conn = mock.MagicMock()
        conn.is_connected.return_value = True

        with (
            mock.patch("sys.argv", ["mysql_query.py", "select", "SELECT 1"]),
            mock.patch("mysql_query.resolve_mysql_config", return_value=cfg),
            mock.patch("mysql_query.read_sql_file", return_value="SELECT 1"),
            mock.patch("mysql_query.get_connection", return_value=conn),
            mock.patch(
                "mysql_query.execute_query",
                side_effect=ServiceError("boom"),
            ),
            pytest.raises(ServiceError),
        ):
            mysql_query.main()

        # finally block still checked connection state and closed it
        conn.is_connected.assert_called_once()
        conn.close.assert_called_once()

    def test_main_passes_args_through(self):
        """main() wires args.operation / args.sql / args.database correctly."""
        cfg = _config()
        conn = mock.MagicMock()
        conn.is_connected.return_value = True

        with (
            mock.patch("sys.argv", ["mysql_query.py", "update", "@q.sql", "-d", "x"]),
            mock.patch("mysql_query.resolve_mysql_config", return_value=cfg),
            mock.patch("mysql_query.read_sql_file", return_value="UPDATE t SET a=1") as rsql,
            mock.patch("mysql_query.get_connection", return_value=conn) as gc,
            mock.patch("mysql_query.execute_query") as ex,
        ):
            rc = mysql_query.main()

        assert rc == 0
        rsql.assert_called_once_with("@q.sql")
        gc.assert_called_once_with(cfg, "x")
        ex.assert_called_once_with(conn, "UPDATE t SET a=1", "update")
