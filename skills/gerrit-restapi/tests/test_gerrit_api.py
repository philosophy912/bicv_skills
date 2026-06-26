"""Tests for gerrit_api.py — helpers, request_json, build_url, cmd_* and main."""

from __future__ import annotations

import base64
import contextlib
import json
from pathlib import Path
from unittest import mock

import gerrit_api
import pytest

from system_config import ServiceError

# A canned GerritTarget that doesn't need a real config file.
MOCK_TARGET = gerrit_api.GerritTarget(
    url="http://gerrit.mock", auth=("user", "pass"), system_name="mock"
)

MOCK_TARGET_NO_AUTH = gerrit_api.GerritTarget(
    url="http://gerrit.mock", auth=None, system_name="mock"
)


def _mock_target_patch(target=MOCK_TARGET):
    return mock.patch("gerrit_api._target", return_value=target)


def _urlopen_cm(body: bytes):
    """Build a mock urlopen returning a context manager with the given body."""
    cm = mock.MagicMock()
    cm.read.return_value = body
    cm.__enter__.return_value = cm
    m = mock.patch("urllib.request.urlopen")
    patcher = m.start()
    patcher.return_value = cm
    return patcher, cm


# ===================================================================
# strip_xssi_prefix
# ===================================================================


class TestStripXssi:
    def test_strips_prefix(self):
        assert gerrit_api.strip_xssi_prefix(")]}'" + '{"a":1}') == '{"a":1}'

    def test_no_prefix_unchanged(self):
        assert gerrit_api.strip_xssi_prefix('{"a":1}') == '{"a":1}'

    def test_empty_string(self):
        assert gerrit_api.strip_xssi_prefix("") == ""


# ===================================================================
# encode_change_id / encode_path_id
# ===================================================================


class TestEncoders:
    def test_encode_change_id_tilde(self):
        # ~ must be encoded to %7E
        assert gerrit_api.encode_change_id("proj~branch~I123") == "proj%7Ebranch%7EI123"

    def test_encode_change_id_special_chars(self):
        out = gerrit_api.encode_change_id("a b/c")
        assert " " not in out
        assert "%20" in out
        # '/' also quoted since safe=""
        assert "%2F" in out

    def test_encode_path_id_special_chars(self):
        assert gerrit_api.encode_path_id("a/b c") == "a%2Fb%20c"

    def test_encode_path_id_plain(self):
        assert gerrit_api.encode_path_id("plain") == "plain"


# ===================================================================
# build_url
# ===================================================================


class TestBuildUrl:
    def test_no_auth_no_prefix(self):
        assert gerrit_api.build_url("http://gerrit", "/changes/") == "http://gerrit/changes/"

    def test_with_auth_adds_a_prefix(self):
        assert (
            gerrit_api.build_url("http://gerrit", "/changes/", auth=("u", "p"))
            == "http://gerrit/a/changes/"
        )

    def test_force_auth_prefix(self):
        assert (
            gerrit_api.build_url("http://gerrit", "/changes/", force_auth_prefix=True)
            == "http://gerrit/a/changes/"
        )

    def test_with_params(self):
        url = gerrit_api.build_url(
            "http://gerrit", "/changes/", params={"q": "status:open", "n": 5}
        )
        assert "q=status%3Aopen" in url
        assert "n=5" in url

    def test_with_auth_and_params(self):
        url = gerrit_api.build_url("http://gerrit", "/changes/", auth=("u", "p"), params={"n": 1})
        assert "/a/changes/" in url
        assert "n=1" in url

    def test_doseq_params(self):
        url = gerrit_api.build_url("http://gerrit", "/changes/", params={"o": ["A", "B"]})
        assert "o=A" in url
        assert "o=B" in url


# ===================================================================
# request_json
# ===================================================================


class TestRequestJson:
    def test_get_returns_parsed_json(self):
        with mock.patch("urllib.request.urlopen") as m:
            cm = mock.MagicMock()
            cm.read.return_value = b")]}'" + b'{"_number": 1}'
            cm.__enter__.return_value = cm
            m.return_value = cm

            result = gerrit_api.request_json("GET", "http://gerrit", "/changes/")
            assert result == {"_number": 1}

    def test_get_strips_xssi_prefix(self):
        with mock.patch("urllib.request.urlopen") as m:
            cm = mock.MagicMock()
            cm.read.return_value = b')]}\'\n{"a": 2}'
            cm.__enter__.return_value = cm
            m.return_value = cm
            assert gerrit_api.request_json("GET", "http://gerrit", "/x") == {"a": 2}

    def test_post_with_payload(self):
        with mock.patch("urllib.request.urlopen") as m:
            cm = mock.MagicMock()
            cm.read.return_value = b")]}'" + b'{"id": "42"}'
            cm.__enter__.return_value = cm
            m.return_value = cm

            result = gerrit_api.request_json(
                "POST", "http://gerrit", "/changes/", payload={"project": "p"}
            )
            assert result == {"id": "42"}

            req = m.call_args[0][0]
            assert req.method == "POST"
            sent = json.loads(req.data)
            assert sent == {"project": "p"}
            ct = req.get_header("Content-type")
            assert ct and "application/json" in ct

    def test_empty_body_returns_none(self):
        with mock.patch("urllib.request.urlopen") as m:
            cm = mock.MagicMock()
            cm.read.return_value = b")]}'"  # xssi prefix then empty
            cm.__enter__.return_value = cm
            m.return_value = cm
            assert gerrit_api.request_json("GET", "http://gerrit", "/x") is None

    def test_empty_body_truly_empty(self):
        with mock.patch("urllib.request.urlopen") as m:
            cm = mock.MagicMock()
            cm.read.return_value = b""
            cm.__enter__.return_value = cm
            m.return_value = cm
            assert gerrit_api.request_json("GET", "http://gerrit", "/x") is None

    def test_auth_sets_basic_header(self):
        with mock.patch("urllib.request.urlopen") as m:
            cm = mock.MagicMock()
            cm.read.return_value = b")]}'{}"
            cm.__enter__.return_value = cm
            m.return_value = cm

            gerrit_api.request_json("GET", "http://gerrit", "/x", auth=("alice", "secret"))
            req = m.call_args[0][0]
            expected = base64.b64encode(b"alice:secret").decode("ascii")
            assert req.get_header("Authorization") == f"Basic {expected}"

    def test_force_auth_prefix_in_url(self):
        with mock.patch("urllib.request.urlopen") as m:
            cm = mock.MagicMock()
            cm.read.return_value = b")]}'{}"
            cm.__enter__.return_value = cm
            m.return_value = cm

            gerrit_api.request_json("POST", "http://gerrit", "/changes/", force_auth_prefix=True)
            req = m.call_args[0][0]
            assert req.full_url == "http://gerrit/a/changes/"

    def test_http_error_raises_gerrit_error(self):
        from urllib.error import HTTPError

        with mock.patch("urllib.request.urlopen") as m:
            exc = HTTPError("http://gerrit", 404, "Not Found", {}, None)
            m.side_effect = exc
            with pytest.raises(ServiceError) as ei:
                gerrit_api.request_json("GET", "http://gerrit", "/changes/999")
            assert ei.value.status_code == 404

    def test_url_error_raises_gerrit_error(self):
        from urllib.error import URLError

        with mock.patch("urllib.request.urlopen") as m:
            m.side_effect = URLError("Connection refused")
            with pytest.raises(ServiceError) as ei:
                gerrit_api.request_json("GET", "http://gerrit", "/changes/")
            assert "网络错误" in str(ei.value)

    def test_non_json_response_raises_gerrit_error(self):
        with mock.patch("urllib.request.urlopen") as m:
            cm = mock.MagicMock()
            cm.read.return_value = b")]}'not json at all"
            cm.__enter__.return_value = cm
            m.return_value = cm
            with pytest.raises(ServiceError) as ei:
                gerrit_api.request_json("GET", "http://gerrit", "/x")
            assert "JSON" in str(ei.value)

    def test_accept_header_set(self):
        with mock.patch("urllib.request.urlopen") as m:
            cm = mock.MagicMock()
            cm.read.return_value = b")]}'{}"
            cm.__enter__.return_value = cm
            m.return_value = cm
            gerrit_api.request_json("GET", "http://gerrit", "/x")
            req = m.call_args[0][0]
            assert req.get_header("Accept") == "application/json"

    def test_method_uppercased(self):
        with mock.patch("urllib.request.urlopen") as m:
            cm = mock.MagicMock()
            cm.read.return_value = b")]}'{}"
            cm.__enter__.return_value = cm
            m.return_value = cm
            gerrit_api.request_json("post", "http://gerrit", "/x")
            assert m.call_args[0][0].method == "POST"


# ===================================================================
# print_error
# ===================================================================


class TestPrintError:
    def test_with_response_text(self, capsys):
        err = ServiceError("请求失败", status_code=400, response_text=")]}'" + "bad")
        rc = gerrit_api.print_error(err)
        captured = capsys.readouterr()
        assert captured.out == ""
        payload = json.loads(captured.err)
        assert payload["error"]["message"] == "请求失败"
        assert payload["error"]["status_code"] == 400
        assert payload["error"]["details"] == "bad"  # XSSI 前缀已剥离
        assert rc == 1

    def test_without_response_text(self, capsys):
        err = ServiceError("出错了")
        rc = gerrit_api.print_error(err)
        captured = capsys.readouterr()
        payload = json.loads(captured.err)
        assert payload["error"]["message"] == "出错了"
        assert payload["error"]["details"] is None
        assert rc == 1

    def test_empty_response_text_not_printed(self, capsys):
        err = ServiceError("err", response_text="")
        rc = gerrit_api.print_error(err)
        captured = capsys.readouterr()
        payload = json.loads(captured.err)
        assert payload["error"]["message"] == "err"
        assert payload["error"]["details"] is None  # 空响应不进 details
        assert rc == 1


# ===================================================================
# Helpers for command tests
# ===================================================================


@contextlib.contextmanager
def patched_request_json(return_value=None, side_effect=None):
    with mock.patch("gerrit_api.request_json") as m:
        if side_effect is not None:
            m.side_effect = side_effect
        else:
            m.return_value = return_value
        yield m


# ===================================================================
# cmd_query_changes
# ===================================================================


class TestCmdQueryChanges:
    def test_empty_result(self, capsys):
        with _mock_target_patch(), patched_request_json(return_value=[]):
            args = mock.MagicMock(query="status:open", limit=25, json=False, option=[])
            rc = gerrit_api.cmd_query_changes(args)
            out = capsys.readouterr().out
            assert json.loads(out)["data"] == []
            assert rc == 0

    def test_with_results(self, capsys):
        changes = [
            {"_number": 1, "subject": "first", "work_in_progress": False},
            {"_number": 2, "subject": "second", "work_in_progress": True},
        ]
        with _mock_target_patch(), patched_request_json(return_value=changes) as rj:
            args = mock.MagicMock(query="status:open", limit=25, json=False, option=[])
            rc = gerrit_api.cmd_query_changes(args)
            out = capsys.readouterr().out
            payload = json.loads(out)
            assert payload["data"] == changes
            assert rc == 0
            _, kwargs = rj.call_args
            assert kwargs["params"]["q"] == "status:open"
            assert kwargs["params"]["n"] == 25

    def test_json_output(self, capsys):
        changes = [{"_number": 1, "subject": "first"}]
        with _mock_target_patch(), patched_request_json(return_value=changes):
            args = mock.MagicMock(query="status:open", limit=25, json=True, option=[])
            rc = gerrit_api.cmd_query_changes(args)
            out = capsys.readouterr().out
            assert rc == 0
            assert json.loads(out)["data"] == changes  # 信封内即原始 changes 列表

    def test_json_with_options(self, capsys):
        changes = [{"_number": 1, "subject": "first"}]
        with _mock_target_patch(), patched_request_json(return_value=changes) as rj:
            args = mock.MagicMock(
                query="status:open", limit=25, json=True, option=["CURRENT_REVISION", "MESSAGES"]
            )
            gerrit_api.cmd_query_changes(args)
            _, kwargs = rj.call_args
            assert kwargs["params"]["o"] == ["CURRENT_REVISION", "MESSAGES"]

    def test_options_without_json(self, capsys):
        changes = [{"_number": 1, "subject": "first", "work_in_progress": False}]
        with _mock_target_patch(), patched_request_json(return_value=changes) as rj:
            args = mock.MagicMock(query="status:open", limit=25, json=False, option=["MESSAGES"])
            rc = gerrit_api.cmd_query_changes(args)
            out = capsys.readouterr().out
            assert rc == 0
            assert json.loads(out)["data"] == changes  # --json 与否默认都是 JSON 信封
            _, kwargs = rj.call_args
            assert kwargs["params"]["o"] == ["MESSAGES"]

    def test_no_options_omits_o(self, capsys):
        changes = [{"_number": 1, "subject": "first", "work_in_progress": False}]
        with _mock_target_patch(), patched_request_json(return_value=changes) as rj:
            args = mock.MagicMock(query="status:open", limit=25, json=False, option=[])
            gerrit_api.cmd_query_changes(args)
            _, kwargs = rj.call_args
            assert "o" not in kwargs["params"]


# ===================================================================
# cmd_get_change_details
# ===================================================================


class TestCmdGetChangeDetails:
    def test_full_details(self, capsys):
        details = {
            "_number": 7,
            "subject": "subj",
            "status": "MERGED",
            "project": "p",
            "branch": "main",
            "owner": {"email": "o@example.com"},
            "reviewers": {"REVIEWER": [{"name": "rev1"}]},
            "labels": {"Code-Review": {"approved": {"name": "Alice"}}},
            "messages": [
                {"author": {"name": "Bob"}, "date": "2024-01-01", "message": "line1\nline2"},
                {"author": {}, "date": "2024-01-02", "message": "msg2"},
            ],
        }
        with _mock_target_patch(), patched_request_json(return_value=details) as rj:
            args = mock.MagicMock(change_id="proj~main~I1")
            rc = gerrit_api.cmd_get_change_details(args)
            out = capsys.readouterr().out
            assert "7" in out
            assert "subj" in out
            assert "MERGED" in out
            assert "o@example.com" in out
            assert "rev1" in out
            assert "Code-Review" in out
            assert "Alice" in out
            assert "line1" in out
            assert rc == 0
            # change id encoded
            path = rj.call_args[0][2]
            assert "proj%7Emain%7EI1" in path

    def test_missing_optional_fields(self, capsys):
        # 字段缺失时仍原样输出原始 detail，不再补 "N/A"
        details = {"_number": 3, "subject": "s", "status": "NEW"}
        with _mock_target_patch(), patched_request_json(return_value=details):
            args = mock.MagicMock(change_id="x~y~z")
            rc = gerrit_api.cmd_get_change_details(args)
            out = capsys.readouterr().out
            assert rc == 0
            assert json.loads(out)["data"] == details

    def test_label_rejected_fallback(self, capsys):
        # 原始 detail 透传：rejected 投票人信息原样保留在 data 中
        details = {
            "_number": 1,
            "subject": "s",
            "status": "X",
            "labels": {"V": {"rejected": {"name": "Rex"}}},
        }
        with _mock_target_patch(), patched_request_json(return_value=details):
            args = mock.MagicMock(change_id="a~b~c")
            gerrit_api.cmd_get_change_details(args)
            out = capsys.readouterr().out
            assert json.loads(out)["data"]["labels"]["V"]["rejected"]["name"] == "Rex"

    def test_message_empty_message_field(self, capsys):
        details = {
            "_number": 1,
            "subject": "s",
            "status": "X",
            "messages": [{"author": {}, "date": "d", "message": ""}],
        }
        with _mock_target_patch(), patched_request_json(return_value=details):
            args = mock.MagicMock(change_id="a~b~c")
            rc = gerrit_api.cmd_get_change_details(args)
            assert rc == 0


# ===================================================================
# cmd_get_change / list_reviewers / list_revisions
# ===================================================================


class TestCmdGetChange:
    def test_with_option(self):
        with _mock_target_patch(), patched_request_json(return_value={"x": 1}) as rj:
            args = mock.MagicMock(change_id="a~b~c", option=["CURRENT_REVISION"])
            rc = gerrit_api.cmd_get_change(args)
            _, kwargs = rj.call_args
            assert kwargs["params"] == {"o": ["CURRENT_REVISION"]}
            assert rc == 0

    def test_without_option(self):
        with _mock_target_patch(), patched_request_json(return_value={"x": 1}) as rj:
            args = mock.MagicMock(change_id="a~b~c", option=[])
            gerrit_api.cmd_get_change(args)
            _, kwargs = rj.call_args
            assert kwargs["params"] is None


class TestCmdListReviewers:
    def test_calls_api(self):
        with _mock_target_patch(), patched_request_json(return_value=[]) as rj:
            args = mock.MagicMock(change_id="a~b~c")
            gerrit_api.cmd_list_reviewers(args)
            path = rj.call_args[0][2]
            assert "/reviewers/" in path


class TestCmdListRevisions:
    def test_extracts_revisions(self):
        result = {"revisions": {"sha1": {}}}
        with _mock_target_patch(), patched_request_json(return_value=result) as rj:
            args = mock.MagicMock(change_id="a~b~c", option=[])
            rc = gerrit_api.cmd_list_revisions(args)
            _, kwargs = rj.call_args
            assert "ALL_REVISIONS" in kwargs["params"]["o"]
            assert rc == 0

    def test_non_dict_result(self):
        with _mock_target_patch(), patched_request_json(return_value=None):
            args = mock.MagicMock(change_id="a~b~c", option=None)
            rc = gerrit_api.cmd_list_revisions(args)
            assert rc == 0


# ===================================================================
# cmd_get_revision (branch logic incl. current fallback)
# ===================================================================


class TestCmdGetRevision:
    def test_found_by_revision_id(self):
        result = {"revisions": {"sha1": {"_number": 1}}}
        with _mock_target_patch(), patched_request_json(return_value=result):
            args = mock.MagicMock(change_id="a~b~c", revision_id="sha1", option=[])
            rc = gerrit_api.cmd_get_revision(args)
            assert rc == 0

    def test_current_fallback(self):
        result = {
            "current_revision": "sha2",
            "revisions": {"sha2": {"_number": 2}},
        }
        with _mock_target_patch(), patched_request_json(return_value=result):
            args = mock.MagicMock(change_id="a~b~c", revision_id="current", option=[])
            rc = gerrit_api.cmd_get_revision(args)
            assert rc == 0

    def test_current_fallback_missing_current_revision(self):
        result = {"revisions": {}}
        with _mock_target_patch(), patched_request_json(return_value=result):
            args = mock.MagicMock(change_id="a~b~c", revision_id="current", option=[])
            with pytest.raises(ServiceError):
                gerrit_api.cmd_get_revision(args)

    def test_not_found(self):
        result = {"revisions": {"sha1": {}}}
        with _mock_target_patch(), patched_request_json(return_value=result):
            args = mock.MagicMock(change_id="a~b~c", revision_id="missing", option=[])
            with pytest.raises(ServiceError):
                gerrit_api.cmd_get_revision(args)

    def test_non_dict_result_raises(self):
        with _mock_target_patch(), patched_request_json(return_value=None):
            args = mock.MagicMock(change_id="a~b~c", revision_id="current", option=[])
            with pytest.raises(ServiceError):
                gerrit_api.cmd_get_revision(args)


# ===================================================================
# cmd_add_reviewer
# ===================================================================


class TestCmdAddReviewer:
    def test_success_with_email(self, capsys):
        with (
            _mock_target_patch(),
            patched_request_json(return_value={"reviewer": {"email": "r@x.com"}}) as rj,
        ):
            args = mock.MagicMock(change_id="a~b~c", reviewer="r@x.com", state="REVIEWER")
            rc = gerrit_api.cmd_add_reviewer(args)
            out = capsys.readouterr().out
            assert "r@x.com" in out
            assert rc == 0
            _, kwargs = rj.call_args
            assert kwargs["force_auth_prefix"] is True
            assert kwargs["payload"]["state"] == "REVIEWER"

    def test_success_no_email_fallback(self, capsys):
        with _mock_target_patch(), patched_request_json(return_value=None):
            args = mock.MagicMock(change_id="a~b~c", reviewer="alice", state="CC")
            rc = gerrit_api.cmd_add_reviewer(args)
            out = capsys.readouterr().out
            assert "alice" in out
            assert "CC" in out
            assert rc == 0


# ===================================================================
# cmd_list_projects (query / non-query branches)
# ===================================================================


class TestCmdListProjects:
    def test_query_path_with_limit_and_start(self):
        with _mock_target_patch(), patched_request_json(return_value={}) as rj:
            args = mock.MagicMock(
                query="name:foo",
                limit=5,
                start=2,
                branch=None,
                prefix=None,
                regex=None,
                match=None,
                description=False,
                tree=False,
                project_type=None,
                state=None,
                all_projects=False,
            )
            gerrit_api.cmd_list_projects(args)
            _, kwargs = rj.call_args
            assert kwargs["params"]["query"] == "name:foo"
            assert kwargs["params"]["limit"] == 5
            assert kwargs["params"]["start"] == 2

    def test_query_path_without_limit_start(self):
        with _mock_target_patch(), patched_request_json(return_value={}) as rj:
            args = mock.MagicMock(
                query="name:foo",
                limit=None,
                start=None,
                branch=None,
                prefix=None,
                regex=None,
                match=None,
                description=False,
                tree=False,
                project_type=None,
                state=None,
                all_projects=False,
            )
            gerrit_api.cmd_list_projects(args)
            _, kwargs = rj.call_args
            assert "limit" not in kwargs["params"]
            assert "start" not in kwargs["params"]

    def test_non_query_path_all_flags(self):
        with _mock_target_patch(), patched_request_json(return_value={}) as rj:
            args = mock.MagicMock(
                query=None,
                limit=10,
                start=3,
                branch="main",
                prefix="p",
                regex="^r",
                match="m",
                description=True,
                tree=True,
                project_type="CODE",
                state="ACTIVE",
                all_projects=True,
            )
            gerrit_api.cmd_list_projects(args)
            _, kwargs = rj.call_args
            p = kwargs["params"]
            assert p["n"] == 10
            assert p["S"] == 3
            assert p["b"] == "main"
            assert p["p"] == "p"
            assert p["r"] == "^r"
            assert p["m"] == "m"
            assert p["d"] is True
            assert p["t"] is True
            assert p["type"] == "CODE"
            assert p["state"] == "ACTIVE"
            assert p["all"] is True

    def test_non_query_path_no_flags_no_params(self):
        with _mock_target_patch(), patched_request_json(return_value={}) as rj:
            args = mock.MagicMock(
                query=None,
                limit=None,
                start=None,
                branch=None,
                prefix=None,
                regex=None,
                match=None,
                description=False,
                tree=False,
                project_type=None,
                state=None,
                all_projects=False,
            )
            gerrit_api.cmd_list_projects(args)
            _, kwargs = rj.call_args
            assert kwargs["params"] is None


# ===================================================================
# cmd_get_project / cmd_list_branches / cmd_get_branch
# ===================================================================


class TestCmdGetProject:
    def test_calls_api(self):
        with _mock_target_patch(), patched_request_json(return_value={}) as rj:
            args = mock.MagicMock(project_name="proj/name")
            gerrit_api.cmd_get_project(args)
            path = rj.call_args[0][2]
            assert path == "/projects/proj%2Fname"


class TestCmdListBranches:
    def test_all_filters(self):
        with _mock_target_patch(), patched_request_json(return_value=[]) as rj:
            args = mock.MagicMock(project_name="p", limit=5, start=2, match="m", regex="^r")
            gerrit_api.cmd_list_branches(args)
            _, kwargs = rj.call_args
            p = kwargs["params"]
            assert p["n"] == 5
            assert p["s"] == 2
            assert p["m"] == "m"
            assert p["r"] == "^r"

    def test_no_filters(self):
        with _mock_target_patch(), patched_request_json(return_value=[]) as rj:
            args = mock.MagicMock(project_name="p", limit=None, start=None, match=None, regex=None)
            gerrit_api.cmd_list_branches(args)
            _, kwargs = rj.call_args
            assert kwargs["params"] is None


class TestCmdGetBranch:
    def test_calls_api(self):
        with _mock_target_patch(), patched_request_json(return_value={}) as rj:
            args = mock.MagicMock(project_name="p", branch_id="refs/heads/main")
            gerrit_api.cmd_get_branch(args)
            path = rj.call_args[0][2]
            assert path.endswith("/branches/refs%2Fheads%2Fmain")


# ===================================================================
# cmd_query_accounts / cmd_get_account / cmd_get_account_detail
# ===================================================================


class TestCmdQueryAccounts:
    def test_all_options(self):
        with _mock_target_patch(), patched_request_json(return_value=[]) as rj:
            args = mock.MagicMock(
                query="name:alice",
                limit=5,
                start=1,
                suggest=True,
                details=True,
                all_emails=True,
            )
            gerrit_api.cmd_query_accounts(args)
            _, kwargs = rj.call_args
            p = kwargs["params"]
            assert p["q"] == "name:alice"
            assert p["n"] == 5
            assert p["S"] == 1
            assert p["suggest"] is True
            assert "DETAILS" in p["o"]
            assert "ALL_EMAILS" in p["o"]

    def test_minimal(self):
        with _mock_target_patch(), patched_request_json(return_value=[]) as rj:
            args = mock.MagicMock(
                query="name:b",
                limit=None,
                start=None,
                suggest=False,
                details=False,
                all_emails=False,
            )
            gerrit_api.cmd_query_accounts(args)
            _, kwargs = rj.call_args
            p = kwargs["params"]
            assert "o" not in p
            assert "suggest" not in p


class TestCmdGetAccount:
    def test_calls_api(self):
        with _mock_target_patch(), patched_request_json(return_value={}) as rj:
            args = mock.MagicMock(account_id="self")
            gerrit_api.cmd_get_account(args)
            assert rj.call_args[0][2] == "/accounts/self"


class TestCmdGetAccountDetail:
    def test_calls_api(self):
        with _mock_target_patch(), patched_request_json(return_value={}) as rj:
            args = mock.MagicMock(account_id="alice")
            gerrit_api.cmd_get_account_detail(args)
            assert rj.call_args[0][2] == "/accounts/alice/detail"


# ===================================================================
# cmd_list_groups (query / non-query branches) + get + members
# ===================================================================


class TestCmdListGroups:
    def test_query_path_with_limit_start(self):
        with _mock_target_patch(), patched_request_json(return_value={}) as rj:
            args = mock.MagicMock(
                query="name:g",
                limit=3,
                start=1,
                owned_by=None,
                owned=False,
                group=None,
                suggest=None,
                project=None,
                match=None,
                regex=None,
                includes=False,
                members=False,
            )
            gerrit_api.cmd_list_groups(args)
            _, kwargs = rj.call_args
            p = kwargs["params"]
            assert p["query"] == "name:g"
            assert p["limit"] == 3
            assert p["start"] == 1

    def test_non_query_path_all_flags(self):
        with _mock_target_patch(), patched_request_json(return_value={}) as rj:
            args = mock.MagicMock(
                query=None,
                limit=5,
                start=2,
                owned_by="o",
                owned=True,
                group="g",
                suggest="s",
                project="p",
                match="m",
                regex="^r",
                includes=True,
                members=True,
            )
            gerrit_api.cmd_list_groups(args)
            _, kwargs = rj.call_args
            p = kwargs["params"]
            assert p["n"] == 5
            assert p["S"] == 2
            assert p["owned-by"] == "o"
            assert p["owned"] is True
            assert p["g"] == "g"
            assert p["suggest"] == "s"
            assert p["p"] == "p"
            assert p["m"] == "m"
            assert p["r"] == "^r"
            assert "INCLUDES" in p["o"]
            assert "MEMBERS" in p["o"]

    def test_non_query_path_no_flags_no_params(self):
        with _mock_target_patch(), patched_request_json(return_value={}) as rj:
            args = mock.MagicMock(
                query=None,
                limit=None,
                start=None,
                owned_by=None,
                owned=False,
                group=None,
                suggest=None,
                project=None,
                match=None,
                regex=None,
                includes=False,
                members=False,
            )
            gerrit_api.cmd_list_groups(args)
            _, kwargs = rj.call_args
            assert kwargs["params"] is None


class TestCmdGetGroup:
    def test_calls_api(self):
        with _mock_target_patch(), patched_request_json(return_value={}) as rj:
            args = mock.MagicMock(group_id="Administrators")
            gerrit_api.cmd_get_group(args)
            assert rj.call_args[0][2] == "/groups/Administrators"


class TestCmdListGroupMembers:
    def test_recursive(self):
        with _mock_target_patch(), patched_request_json(return_value=[]) as rj:
            args = mock.MagicMock(group_id="g", recursive=True)
            gerrit_api.cmd_list_group_members(args)
            _, kwargs = rj.call_args
            assert kwargs["params"] == {"recursive": True}

    def test_non_recursive(self):
        with _mock_target_patch(), patched_request_json(return_value=[]) as rj:
            args = mock.MagicMock(group_id="g", recursive=False)
            gerrit_api.cmd_list_group_members(args)
            _, kwargs = rj.call_args
            assert kwargs["params"] is None


# ===================================================================
# cmd_list_change_messages / cmd_get_topic
# ===================================================================


class TestCmdListChangeMessages:
    def test_calls_api(self):
        with _mock_target_patch(), patched_request_json(return_value=[]) as rj:
            args = mock.MagicMock(change_id="a~b~c")
            gerrit_api.cmd_list_change_messages(args)
            assert "/messages/" in rj.call_args[0][2]


class TestCmdGetTopic:
    def test_calls_api(self):
        with _mock_target_patch(), patched_request_json(return_value={}) as rj:
            args = mock.MagicMock(change_id="a~b~c")
            gerrit_api.cmd_get_topic(args)
            assert rj.call_args[0][2].endswith("/topic")


# ===================================================================
# cmd_list_files (mutex validation + filter branches)
# ===================================================================


class TestCmdListFiles:
    def _args(self, **over):
        defaults = dict(
            change_id="a~b~c",
            revision_id="current",
            reviewed=False,
            query=None,
            parent=None,
            base=None,
        )
        defaults.update(over)
        # 'parent' is a reserved attribute on MagicMock; build then assign.
        parent_val = defaults.pop("parent")
        args = mock.MagicMock(**defaults)
        args.parent = parent_val
        return args

    def test_mutex_too_many(self):
        with _mock_target_patch(), patched_request_json(return_value={}):
            args = self._args(reviewed=True, query="q")
            with pytest.raises(ServiceError):
                gerrit_api.cmd_list_files(args)

    def test_reviewed(self):
        with _mock_target_patch(), patched_request_json(return_value={}) as rj:
            gerrit_api.cmd_list_files(self._args(reviewed=True))
            _, kwargs = rj.call_args
            assert kwargs["params"]["reviewed"] is True

    def test_query(self):
        with _mock_target_patch(), patched_request_json(return_value={}) as rj:
            gerrit_api.cmd_list_files(self._args(query="path"))
            _, kwargs = rj.call_args
            assert kwargs["params"]["q"] == "path"

    def test_parent(self):
        with _mock_target_patch(), patched_request_json(return_value={}) as rj:
            gerrit_api.cmd_list_files(self._args(parent=1))
            _, kwargs = rj.call_args
            assert kwargs["params"]["parent"] == 1

    def test_base(self):
        with _mock_target_patch(), patched_request_json(return_value={}) as rj:
            gerrit_api.cmd_list_files(self._args(base="sha"))
            _, kwargs = rj.call_args
            assert kwargs["params"]["base"] == "sha"

    def test_no_filters(self):
        with _mock_target_patch(), patched_request_json(return_value={}) as rj:
            gerrit_api.cmd_list_files(self._args())
            _, kwargs = rj.call_args
            assert kwargs["params"] is None

    def test_path_encodes_revision_and_change(self):
        with _mock_target_patch(), patched_request_json(return_value={}) as rj:
            gerrit_api.cmd_list_files(self._args(change_id="p~b~c", revision_id="cur/rent"))
            path = rj.call_args[0][2]
            assert "p%7Eb%7Ec" in path
            assert "cur%2Frent" in path


# ===================================================================
# cmd_post_review / cmd_create_change
# ===================================================================


class TestCmdPostReview:
    def test_success(self, capsys):
        with _mock_target_patch(), patched_request_json(return_value=None) as rj:
            args = mock.MagicMock(change_id="a~b~c", revision="current", message="lgtm")
            rc = gerrit_api.cmd_post_review(args)
            out = capsys.readouterr().out
            payload = json.loads(out)
            assert payload["data"]["posted"] is True
            assert payload["data"]["message"] == "lgtm"
            assert rc == 0
            _, kwargs = rj.call_args
            assert kwargs["force_auth_prefix"] is True
            assert kwargs["payload"]["message"] == "lgtm"
            # revision is path-encoded (current has no special chars → unchanged)
            assert "/revisions/current/review" in rj.call_args[0][2]

    def test_revision_path_encoded(self):
        # revision with special chars must be percent-encoded in the URL
        with _mock_target_patch(), patched_request_json(return_value=None) as rj:
            args = mock.MagicMock(change_id="a~b~c", revision="curr ent", message="lgtm")
            gerrit_api.cmd_post_review(args)
            # encode_path_id("curr ent") == "curr%20ent"
            assert "/revisions/curr%20ent/review" in rj.call_args[0][2]


class TestCmdCreateChange:
    def test_success_with_id(self, capsys):
        with _mock_target_patch(), patched_request_json(return_value={"id": "proj~main~I1"}) as rj:
            args = mock.MagicMock(project="proj", branch="main", subject="subj")
            rc = gerrit_api.cmd_create_change(args)
            out = capsys.readouterr().out
            assert "proj~main~I1" in out
            assert rc == 0
            _, kwargs = rj.call_args
            assert kwargs["payload"]["project"] == "proj"

    def test_success_without_id_fallback(self, capsys):
        with _mock_target_patch(), patched_request_json(return_value=None):
            args = mock.MagicMock(project="proj", branch="main", subject="mysubj")
            rc = gerrit_api.cmd_create_change(args)
            out = capsys.readouterr().out
            assert "mysubj" in out
            assert rc == 0


# ===================================================================
# _target / add_*_args helpers
# ===================================================================


class TestTarget:
    def test_target_calls_resolve(self):
        with mock.patch("gerrit_api.resolve_target") as rt:
            rt.return_value = MOCK_TARGET
            args = mock.MagicMock(gerrit="g", user="u:p", system="s")
            t = gerrit_api._target(args)
            rt.assert_called_once()
            kw = rt.call_args.kwargs
            assert kw["config_name"] == "gerrit.json"
            assert kw["password_key"] == "http_password"
            assert t is MOCK_TARGET

    def test_target_missing_attrs(self):
        # args without gerrit/user/system attrs should not crash (hasattr guards)
        with mock.patch("gerrit_api.resolve_target") as rt:
            rt.return_value = MOCK_TARGET
            args = argparse.Namespace()
            gerrit_api._target(args)
            a, _kw = rt.call_args
            assert a[0] is None
            assert a[1] is None
            assert a[2] is None


import argparse  # noqa: E402  (placed here to keep test grouping readable)


class TestAddArgsHelpers:
    def test_add_common_args(self):
        p = argparse.ArgumentParser()
        gerrit_api.add_common_args(p)
        ns = p.parse_args(["--gerrit", "g", "--system", "s", "--user", "u:p"])
        assert ns.gerrit == "g"
        assert ns.system == "s"
        assert ns.user == "u:p"

    def test_add_range_args_default_names(self):
        p = argparse.ArgumentParser()
        gerrit_api.add_range_args(p)
        ns = p.parse_args(["--limit", "5", "--start", "2"])
        assert ns.limit == 5
        assert ns.start == 2

    def test_add_range_args_custom_names(self):
        p = argparse.ArgumentParser()
        gerrit_api.add_range_args(p, limit_name="--n", start_name="--S")
        ns = p.parse_args(["--n", "9", "--S", "3"])
        assert ns.n == 9
        assert ns.S == 3

    def test_add_change_options_arg_append(self):
        p = argparse.ArgumentParser()
        gerrit_api.add_change_options_arg(p)
        ns = p.parse_args(["--option", "A", "--option", "B"])
        assert ns.option == ["A", "B"]

    def test_add_change_options_arg_default_empty(self):
        p = argparse.ArgumentParser()
        gerrit_api.add_change_options_arg(p)
        ns = p.parse_args([])
        assert ns.option == []


# ===================================================================
# build_parser (subcommand registration)
# ===================================================================


class TestBuildParser:
    SUBCOMMANDS = [
        "query-changes",
        "get-change-details",
        "get-change",
        "list-reviewers",
        "list-revisions",
        "get-revision",
        "list-projects",
        "get-project",
        "list-branches",
        "get-branch",
        "query-accounts",
        "get-account",
        "get-account-detail",
        "list-groups",
        "get-group",
        "list-group-members",
        "list-change-messages",
        "get-topic",
        "list-files",
        "add-reviewer",
        "post-review",
        "create-change",
    ]

    def test_all_subcommands_registered(self):
        parser = gerrit_api.build_parser()
        choices = parser._subparsers._actions[-1].choices
        for cmd in self.SUBCOMMANDS:
            assert cmd in choices, f"Missing subcommand: {cmd}"

    def test_missing_subcommand_exits(self):
        with pytest.raises(SystemExit):
            gerrit_api.build_parser().parse_args([])

    def test_query_changes_required_query(self):
        with pytest.raises(SystemExit):
            gerrit_api.build_parser().parse_args(["query-changes"])

    def test_query_changes_parses(self):
        args = gerrit_api.build_parser().parse_args(
            ["query-changes", "--query", "status:open", "--limit", "10"]
        )
        assert args.command == "query-changes"
        assert args.query == "status:open"
        assert args.limit == 10
        assert args.handler is gerrit_api.cmd_query_changes

    def test_query_changes_parses_json_options(self):
        args = gerrit_api.build_parser().parse_args(
            [
                "query-changes",
                "--query",
                "status:open",
                "--json",
                "--option",
                "CURRENT_REVISION",
                "--option",
                "MESSAGES",
            ]
        )
        assert args.json is True
        assert args.option == ["CURRENT_REVISION", "MESSAGES"]
        assert args.limit == 25

    def test_get_revision_parses(self):
        args = gerrit_api.build_parser().parse_args(
            ["get-revision", "--change-id", "a~b~c", "--revision-id", "current"]
        )
        assert args.revision_id == "current"

    def test_list_files_parses(self):
        args = gerrit_api.build_parser().parse_args(
            ["list-files", "--change-id", "a~b~c", "--revision-id", "current", "--reviewed"]
        )
        assert args.reviewed is True

    def test_add_reviewer_state_choices(self):
        args = gerrit_api.build_parser().parse_args(
            ["add-reviewer", "--change-id", "a~b~c", "--reviewer", "r@x.com", "--state", "CC"]
        )
        assert args.state == "CC"
        with pytest.raises(SystemExit):
            gerrit_api.build_parser().parse_args(
                ["add-reviewer", "--change-id", "a~b~c", "--reviewer", "r", "--state", "BAD"]
            )

    def test_post_review_default_revision(self):
        args = gerrit_api.build_parser().parse_args(
            ["post-review", "--change-id", "a~b~c", "--message", "m"]
        )
        assert args.revision == "current"

    def test_list_projects_project_type_choices(self):
        with pytest.raises(SystemExit):
            gerrit_api.build_parser().parse_args(["list-projects", "--project-type", "BAD"])
        args = gerrit_api.build_parser().parse_args(["list-projects", "--project-type", "CODE"])
        assert args.project_type == "CODE"

    def test_common_args_present(self):
        args = gerrit_api.build_parser().parse_args(
            ["list-projects", "--gerrit", "http://g", "--system", "s", "--user", "u:p"]
        )
        assert args.gerrit == "http://g"
        assert args.system == "s"
        assert args.user == "u:p"

    def test_create_change_required_fields(self):
        with pytest.raises(SystemExit):
            gerrit_api.build_parser().parse_args(["create-change", "--project", "p"])
        args = gerrit_api.build_parser().parse_args(
            ["create-change", "--project", "p", "--branch", "main", "--subject", "s"]
        )
        assert args.project == "p"


# ===================================================================
# main()
# ===================================================================


class TestMain:
    def test_success_path(self):
        with mock.patch("sys.argv", ["gerrit_api.py", "query-changes", "--query", "x"]):
            with mock.patch("gerrit_api.cmd_query_changes", return_value=0) as h:
                rc = gerrit_api.main()
                assert rc == 0
                h.assert_called_once()

    def test_gerrit_error_path(self, capsys):
        def handler(args):
            raise ServiceError("boom", status_code=500, response_text="body")

        # Force the handler by patching the cmd used by query-changes
        with mock.patch("sys.argv", ["gerrit_api.py", "query-changes", "--query", "x"]):
            with mock.patch("gerrit_api.cmd_query_changes", side_effect=handler):
                rc = gerrit_api.main()
                captured = capsys.readouterr()
                assert rc == 1
                assert captured.out == ""
                payload = json.loads(captured.err)
                assert payload["error"]["message"] == "boom"
                assert payload["error"]["status_code"] == 500
                assert payload["error"]["details"] == "body"

    def test_main_invokes_real_handler_through_target(self):
        # End-to-end-ish: real handler, but mock _target + request_json
        with mock.patch("sys.argv", ["gerrit_api.py", "query-changes", "--query", "x"]):
            with _mock_target_patch(), patched_request_json(return_value=[]):
                rc = gerrit_api.main()
                assert rc == 0


# ===================================================================
# Module entrypoint (__main__ raises SystemExit(main()))
# ===================================================================


class TestMainEntrypoint:
    def test_dunder_main_entrypoint(self, tmp_path, monkeypatch):
        """Executing the script as __main__ runs main() and exits 0 on success."""
        import runpy

        # Redirect HOME to a temp dir with a minimal gerrit.json config so
        # resolve_target doesn't touch the real ~/.bicv/gerrit.json.
        bicv = tmp_path / ".bicv"
        bicv.mkdir()
        (bicv / "gerrit.json").write_text(
            json.dumps(
                {
                    "default_system": "mock",
                    "systems": {
                        "mock": {
                            "url": "http://gerrit.mock",
                            "username": "user",
                            "http_password": "pass",
                        }
                    },
                }
            ),
            encoding="utf-8",
        )
        monkeypatch.setenv("HOME", str(tmp_path))
        monkeypatch.setattr("sys.argv", ["gerrit_api.py", "query-changes", "--query", "x"])

        with mock.patch("urllib.request.urlopen") as m:
            cm = mock.MagicMock()
            cm.read.return_value = b")]}'[]"
            cm.__enter__.return_value = cm
            m.return_value = cm

            with pytest.raises(SystemExit) as ei:
                runpy.run_path(
                    str(Path(gerrit_api.__file__).resolve()),
                    run_name="__main__",
                )
            assert ei.value.code == 0
