"""Tests for jenkins_api.py — helpers, request layer, commands, CLI, main."""

from __future__ import annotations

import base64
import contextlib
import json
from unittest import mock
from urllib import error

import jenkins_api
import pytest

JenkinsError = jenkins_api.JenkinsError
JenkinsTarget = jenkins_api.JenkinsTarget

# A canned JenkinsTarget with auth so request_text sets Basic headers.
MOCK_TARGET = JenkinsTarget(url="http://jenkins.mock", auth=("user", "token"), system_name="mock")
# A target without auth, for the no-auth branches.
NO_AUTH_TARGET = JenkinsTarget(url="http://jenkins.mock", auth=None)


def _mock_target_patch():
    return mock.patch("jenkins_api._target", return_value=MOCK_TARGET)


def _urlopen_cm(body: bytes = b"{}"):
    """Build a mock urlopen returning a context manager that yields a response."""
    cm = mock.MagicMock()
    cm.read.return_value = body
    cm.__enter__.return_value = cm
    return cm


def _http_error(code: int, body: bytes = b"err body"):
    return error.HTTPError(
        "http://jenkins.mock",
        code,
        "Error",
        {},  # type: ignore[arg-type]
        mock.MagicMock(read=mock.MagicMock(return_value=body)),
    )


# ===================================================================
# get_crumb
# ===================================================================


class TestGetCrumb:
    def test_no_auth_returns_none(self):
        target = JenkinsTarget(url="http://jenkins.mock", auth=None)
        assert jenkins_api.get_crumb(target) is None

    def test_returns_crumb_pair(self):
        body = json.dumps({"crumbRequestField": "Jenkins-Crumb", "crumb": "abc123"}).encode()
        with mock.patch("jenkins_api.request_json", return_value=json.loads(body)):
            result = jenkins_api.get_crumb(MOCK_TARGET)
        assert result == ("Jenkins-Crumb", "abc123")

    def test_403_returns_none(self):
        with mock.patch(
            "jenkins_api.request_json", side_effect=JenkinsError("fail", status_code=403)
        ):
            assert jenkins_api.get_crumb(MOCK_TARGET) is None

    def test_404_returns_none(self):
        with mock.patch(
            "jenkins_api.request_json", side_effect=JenkinsError("fail", status_code=404)
        ):
            assert jenkins_api.get_crumb(MOCK_TARGET) is None

    def test_other_status_reraises(self):
        with mock.patch(
            "jenkins_api.request_json", side_effect=JenkinsError("fail", status_code=500)
        ):
            with pytest.raises(JenkinsError):
                jenkins_api.get_crumb(MOCK_TARGET)

    def test_non_dict_data_returns_none(self):
        with mock.patch("jenkins_api.request_json", return_value=["not", "a", "dict"]):
            assert jenkins_api.get_crumb(MOCK_TARGET) is None

    def test_missing_fields_returns_none(self):
        with mock.patch(
            "jenkins_api.request_json", return_value={"crumbRequestField": "Jenkins-Crumb"}
        ):
            assert jenkins_api.get_crumb(MOCK_TARGET) is None

    def test_empty_field_values_returns_none(self):
        with mock.patch(
            "jenkins_api.request_json", return_value={"crumbRequestField": "", "crumb": ""}
        ):
            assert jenkins_api.get_crumb(MOCK_TARGET) is None


# ===================================================================
# encode_job_segment
# ===================================================================


class TestEncodeJobSegment:
    def test_plain_name(self):
        assert jenkins_api.encode_job_segment("my-job") == "job/my-job"

    def test_folder_path(self):
        # each segment is prefixed with job/
        assert jenkins_api.encode_job_segment("folder/job") == "job/folder/job/job"

    def test_segments_get_quoted(self):
        # special chars are percent-encoded
        result = jenkins_api.encode_job_segment("a b/c")
        assert "a%20b" in result
        assert result == "job/a%20b/job/c"

    def test_empty_name_raises(self):
        with pytest.raises(JenkinsError):
            jenkins_api.encode_job_segment("")

    def test_only_slashes_raises(self):
        with pytest.raises(JenkinsError):
            jenkins_api.encode_job_segment("///")


# ===================================================================
# build_url
# ===================================================================


class TestBuildUrl:
    def test_plain(self):
        assert jenkins_api.build_url("http://j", "/api/json") == "http://j/api/json"

    def test_with_params(self):
        url = jenkins_api.build_url("http://j", "/api/json", params={"depth": 1})
        assert url == "http://j/api/json?depth=1"

    def test_no_params(self):
        assert jenkins_api.build_url("http://j", "/api/json", params=None) == "http://j/api/json"

    def test_multiple_params_doseq(self):
        url = jenkins_api.build_url("http://j", "/api/json", params={"a": ["x", "y"], "b": "z"})
        assert "a=x" in url and "a=y" in url and "b=z" in url


# ===================================================================
# request_text
# ===================================================================


class TestRequestText:
    def test_get_returns_text(self):
        with mock.patch("urllib.request.urlopen") as m:
            m.return_value = _urlopen_cm(b"hello world")
            result = jenkins_api.request_text("GET", MOCK_TARGET, "/api/json")
        assert result == "hello world"

    def test_non_utf8_bytes_replaced_not_raised(self):
        # consoleText may contain non-UTF-8 bytes (GBK/binary from embedded builds);
        # decoding must not crash, invalid bytes become U+FFFD.
        with mock.patch("urllib.request.urlopen") as m:
            m.return_value = _urlopen_cm(b"err \xd5\xc0\xce ok")
            result = jenkins_api.request_text("GET", MOCK_TARGET, "/consoleText")
        assert "err " in result and " ok" in result
        assert "�" in result

    def test_basic_auth_header(self):
        with mock.patch("urllib.request.urlopen") as m:
            m.return_value = _urlopen_cm(b"{}")
            jenkins_api.request_text("GET", MOCK_TARGET, "/api/json")
            req = m.call_args[0][0]
            expected = base64.b64encode(b"user:token").decode("ascii")
            assert req.get_header("Authorization") == f"Basic {expected}"

    def test_no_auth_no_header(self):
        with mock.patch("urllib.request.urlopen") as m:
            m.return_value = _urlopen_cm(b"{}")
            jenkins_api.request_text("GET", NO_AUTH_TARGET, "/api/json")
            req = m.call_args[0][0]
            assert req.get_header("Authorization") is None

    def test_default_accept_header(self):
        with mock.patch("urllib.request.urlopen") as m:
            m.return_value = _urlopen_cm(b"{}")
            jenkins_api.request_text("GET", MOCK_TARGET, "/api/json")
            req = m.call_args[0][0]
            assert req.get_header("Accept") == "application/json"

    def test_custom_headers_not_overriding_accept(self):
        with mock.patch("urllib.request.urlopen") as m:
            m.return_value = _urlopen_cm(b"{}")
            jenkins_api.request_text(
                "GET",
                MOCK_TARGET,
                "/api/json",
                headers={"Accept": "text/plain"},
            )
            req = m.call_args[0][0]
            assert req.get_header("Accept") == "text/plain"

    def test_include_crumb_adds_header(self):
        crumb_pair = ("Jenkins-Crumb", "abc123")
        with mock.patch("jenkins_api.get_crumb", return_value=crumb_pair) as gc:
            with mock.patch("urllib.request.urlopen") as m:
                m.return_value = _urlopen_cm(b"{}")
                jenkins_api.request_text("POST", MOCK_TARGET, "/build", include_crumb=True)
                req = m.call_args[0][0]
                assert req.get_header("Jenkins-crumb") == "abc123"
        gc.assert_called_once_with(MOCK_TARGET)

    def test_include_crumb_none_skips_header(self):
        with mock.patch("jenkins_api.get_crumb", return_value=None):
            with mock.patch("urllib.request.urlopen") as m:
                m.return_value = _urlopen_cm(b"{}")
                jenkins_api.request_text("POST", NO_AUTH_TARGET, "/build", include_crumb=True)
                req = m.call_args[0][0]
                assert req.get_header("Jenkins-crumb") is None

    def test_method_uppercased(self):
        with mock.patch("urllib.request.urlopen") as m:
            m.return_value = _urlopen_cm(b"{}")
            jenkins_api.request_text("post", MOCK_TARGET, "/api/json")
            assert m.call_args[0][0].method == "POST"

    def test_body_and_params_in_url(self):
        with mock.patch("urllib.request.urlopen") as m:
            m.return_value = _urlopen_cm(b"{}")
            jenkins_api.request_text(
                "POST",
                MOCK_TARGET,
                "/build",
                params={"depth": 1},
                body=b"data",
            )
            req = m.call_args[0][0]
            assert req.data == b"data"
            assert "depth=1" in req.full_url

    def test_http_error_raises_jenkins_error_with_status_and_body(self):
        with mock.patch("urllib.request.urlopen") as m:
            m.side_effect = _http_error(500, b"server boom")
            with pytest.raises(JenkinsError) as exc_info:
                jenkins_api.request_text("GET", MOCK_TARGET, "/api/json")
            assert exc_info.value.status_code == 500
            assert exc_info.value.response_text == "server boom"

    def test_url_error_raises_jenkins_error(self):
        with mock.patch("urllib.request.urlopen") as m:
            m.side_effect = error.URLError("Connection refused")
            with pytest.raises(JenkinsError) as exc_info:
                jenkins_api.request_text("GET", MOCK_TARGET, "/api/json")
            assert "Connection refused" in str(exc_info.value)


# ===================================================================
# request_json
# ===================================================================


class TestRequestJson:
    def test_get_returns_parsed_json(self):
        with mock.patch("jenkins_api.request_text", return_value='{"jobs": [], "mode": "NORMAL"}'):
            result = jenkins_api.request_json("GET", MOCK_TARGET, "/api/json")
        assert result == {"jobs": [], "mode": "NORMAL"}

    def test_post_with_payload(self):
        captured = {}

        def fake_request_text(method, target, path, **kw):
            captured["body"] = kw.get("body")
            captured["headers"] = kw.get("headers")
            return '{"status": "ok"}'

        with mock.patch("jenkins_api.request_text", side_effect=fake_request_text):
            result = jenkins_api.request_json(
                "POST",
                MOCK_TARGET,
                "/create",
                payload={"name": "x"},
            )
        assert result == {"status": "ok"}
        assert json.loads(captured["body"]) == {"name": "x"}
        assert "application/json" in captured["headers"]["Content-Type"]

    def test_empty_body_returns_none(self):
        with mock.patch("jenkins_api.request_text", return_value="   "):
            result = jenkins_api.request_json("GET", MOCK_TARGET, "/api/json")
        assert result is None

    def test_strips_whitespace_before_parse(self):
        with mock.patch("jenkins_api.request_text", return_value='  {"a": 1}  '):
            result = jenkins_api.request_json("GET", MOCK_TARGET, "/api/json")
        assert result == {"a": 1}

    def test_non_json_response_raises(self):
        with mock.patch("jenkins_api.request_text", return_value="not json"):
            with pytest.raises(JenkinsError) as exc_info:
                jenkins_api.request_json("GET", MOCK_TARGET, "/api/json")
            assert "not valid JSON" in str(exc_info.value)
            assert exc_info.value.response_text == "not json"

    def test_passes_include_crumb(self):
        with mock.patch("jenkins_api.request_text", return_value="{}") as rt:
            jenkins_api.request_json("POST", MOCK_TARGET, "/build", include_crumb=True)
            _, kw = rt.call_args
            assert kw["include_crumb"] is True

    def test_no_payload_no_content_type(self):
        captured = {}

        def fake_request_text(method, target, path, **kw):
            captured["body"] = kw.get("body")
            captured["headers"] = kw.get("headers")
            return "{}"

        with mock.patch("jenkins_api.request_text", side_effect=fake_request_text):
            jenkins_api.request_json("GET", MOCK_TARGET, "/api/json")
        assert captured["body"] is None
        assert captured["headers"] == {}


# ===================================================================
# parse_params
# ===================================================================


class TestParseParams:
    def test_single_key_value(self):
        assert jenkins_api.parse_params(["BRANCH=main"]) == {"BRANCH": "main"}

    def test_multiple_key_values(self):
        result = jenkins_api.parse_params(["BRANCH=main", "DEBUG=true"])
        assert result == {"BRANCH": "main", "DEBUG": "true"}

    def test_empty_value_allowed(self):
        assert jenkins_api.parse_params(["KEY="]) == {"KEY": ""}

    def test_missing_equals_raises(self):
        with pytest.raises(JenkinsError):
            jenkins_api.parse_params(["NOSEP"])

    def test_empty_list_returns_empty(self):
        assert jenkins_api.parse_params([]) == {}

    def test_value_contains_equals(self):
        # only the first '=' is the separator
        assert jenkins_api.parse_params(["URL=http://x?a=b"]) == {"URL": "http://x?a=b"}


# ===================================================================
# Command tests
# ===================================================================


class TestCmdListJobs:
    def test_lists_jobs(self, capsys):
        with contextlib.ExitStack() as stack:
            stack.enter_context(_mock_target_patch())
            rj = stack.enter_context(mock.patch("jenkins_api.request_json"))
            rj.return_value = {
                "jobs": [
                    {"name": "job-a", "url": "http://j/job-a", "color": "blue"},
                    {"name": "job-b", "url": "http://j/job-b", "color": "red"},
                ]
            }
            args = mock.MagicMock(jenkins=None, user=None, system=None)
            rc = jenkins_api.cmd_list_jobs(args)
        out = capsys.readouterr().out
        assert rc == 0
        payload = json.loads(out)
        jobs = payload["data"]["jobs"]
        assert len(jobs) == 2
        assert [j["name"] for j in jobs] == ["job-a", "job-b"]
        assert [j["color"] for j in jobs] == ["blue", "red"]
        assert [j["url"] for j in jobs] == ["http://j/job-a", "http://j/job-b"]

    def test_no_jobs_key(self, capsys):
        with contextlib.ExitStack() as stack:
            stack.enter_context(_mock_target_patch())
            rj = stack.enter_context(mock.patch("jenkins_api.request_json"))
            rj.return_value = {}
            args = mock.MagicMock(jenkins=None, user=None, system=None)
            rc = jenkins_api.cmd_list_jobs(args)
        out = capsys.readouterr().out
        assert rc == 0
        assert json.loads(out)["data"]["jobs"] == []

    def test_non_dict_response(self, capsys):
        with contextlib.ExitStack() as stack:
            stack.enter_context(_mock_target_patch())
            rj = stack.enter_context(mock.patch("jenkins_api.request_json"))
            rj.return_value = []
            args = mock.MagicMock(jenkins=None, user=None, system=None)
            rc = jenkins_api.cmd_list_jobs(args)
        assert rc == 0
        assert json.loads(capsys.readouterr().out)["data"]["jobs"] == []

    def test_job_missing_fields(self, capsys):
        with contextlib.ExitStack() as stack:
            stack.enter_context(_mock_target_patch())
            rj = stack.enter_context(mock.patch("jenkins_api.request_json"))
            rj.return_value = {"jobs": [{}]}
            args = mock.MagicMock(jenkins=None, user=None, system=None)
            jenkins_api.cmd_list_jobs(args)
        out = capsys.readouterr().out
        job = json.loads(out)["data"]["jobs"][0]
        assert job["color"] == "unknown"
        assert job["name"] == "N/A"


class TestCmdListNodes:
    def test_lists_all_nodes(self, capsys):
        with contextlib.ExitStack() as stack:
            stack.enter_context(_mock_target_patch())
            rj = stack.enter_context(mock.patch("jenkins_api.request_json"))
            rj.return_value = {
                "computer": [
                    {"displayName": "Built-In Node", "offline": False, "numExecutors": 2},
                    {
                        "displayName": "bug-10",
                        "offline": True,
                        "offlineCauseReason": "Connection was broken",
                        "temporarilyOffline": False,
                        "idle": True,
                        "numExecutors": 4,
                    },
                ]
            }
            args = mock.MagicMock(jenkins=None, user=None, system=None, offline=False)
            rc = jenkins_api.cmd_list_nodes(args)
        out = capsys.readouterr().out
        assert rc == 0
        payload = json.loads(out)["data"]
        assert payload["total"] == 2
        assert payload["offlineCount"] == 1
        assert [n["name"] for n in payload["computers"]] == ["Built-In Node", "bug-10"]
        offline = payload["computers"][1]
        assert offline["offline"] is True
        assert offline["offlineCauseReason"] == "Connection was broken"
        args_called, kwargs = rj.call_args
        assert args_called[2] == "/computer/api/json"
        assert "computer[displayName" in kwargs["params"]["tree"]

    def test_offline_filter_only_returns_offline(self, capsys):
        with contextlib.ExitStack() as stack:
            stack.enter_context(_mock_target_patch())
            rj = stack.enter_context(mock.patch("jenkins_api.request_json"))
            rj.return_value = {
                "computer": [
                    {"displayName": "node-up", "offline": False},
                    {"displayName": "node-down", "offline": True, "offlineCauseReason": "lost"},
                ]
            }
            args = mock.MagicMock(jenkins=None, user=None, system=None, offline=True)
            rc = jenkins_api.cmd_list_nodes(args)
        payload = json.loads(capsys.readouterr().out)["data"]
        assert rc == 0
        assert payload["total"] == 2
        assert payload["offlineCount"] == 1
        assert [n["name"] for n in payload["computers"]] == ["node-down"]

    def test_no_computer_key(self, capsys):
        with contextlib.ExitStack() as stack:
            stack.enter_context(_mock_target_patch())
            rj = stack.enter_context(mock.patch("jenkins_api.request_json"))
            rj.return_value = {}
            args = mock.MagicMock(jenkins=None, user=None, system=None, offline=False)
            rc = jenkins_api.cmd_list_nodes(args)
        payload = json.loads(capsys.readouterr().out)["data"]
        assert rc == 0
        assert payload["computers"] == []
        assert payload["total"] == 0

    def test_non_dict_response(self, capsys):
        with contextlib.ExitStack() as stack:
            stack.enter_context(_mock_target_patch())
            rj = stack.enter_context(mock.patch("jenkins_api.request_json"))
            rj.return_value = []
            args = mock.MagicMock(jenkins=None, user=None, system=None, offline=False)
            rc = jenkins_api.cmd_list_nodes(args)
        assert rc == 0
        assert json.loads(capsys.readouterr().out)["data"]["computers"] == []

    def test_node_missing_fields_and_null_reason(self, capsys):
        with contextlib.ExitStack() as stack:
            stack.enter_context(_mock_target_patch())
            rj = stack.enter_context(mock.patch("jenkins_api.request_json"))
            rj.return_value = {"computer": [{"offlineCauseReason": None}]}
            args = mock.MagicMock(jenkins=None, user=None, system=None, offline=False)
            jenkins_api.cmd_list_nodes(args)
        node = json.loads(capsys.readouterr().out)["data"]["computers"][0]
        assert node["name"] == "N/A"
        assert node["offline"] is False
        assert node["offlineCauseReason"] == ""
        assert node["numExecutors"] == 0

    def test_non_dict_computer_entry_skipped(self, capsys):
        with contextlib.ExitStack() as stack:
            stack.enter_context(_mock_target_patch())
            rj = stack.enter_context(mock.patch("jenkins_api.request_json"))
            rj.return_value = {"computer": ["junk", {"displayName": "ok", "offline": False}]}
            args = mock.MagicMock(jenkins=None, user=None, system=None, offline=False)
            jenkins_api.cmd_list_nodes(args)
        payload = json.loads(capsys.readouterr().out)["data"]
        assert payload["total"] == 1
        assert payload["computers"][0]["name"] == "ok"


class TestCmdGetJob:
    def test_get_job_no_depth(self, capsys):
        with contextlib.ExitStack() as stack:
            stack.enter_context(_mock_target_patch())
            rj = stack.enter_context(mock.patch("jenkins_api.request_json"))
            rj.return_value = {"name": "job-a"}
            args = mock.MagicMock(job="job-a", depth=None, jenkins=None, user=None, system=None)
            rc = jenkins_api.cmd_get_job(args)
        assert rc == 0
        _, kw = rj.call_args
        assert kw["params"] is None

    def test_get_job_with_depth(self, capsys):
        with contextlib.ExitStack() as stack:
            stack.enter_context(_mock_target_patch())
            rj = stack.enter_context(mock.patch("jenkins_api.request_json"))
            rj.return_value = {"name": "job-a"}
            args = mock.MagicMock(job="job-a", depth=2, jenkins=None, user=None, system=None)
            jenkins_api.cmd_get_job(args)
        _, kw = rj.call_args
        assert kw["params"] == {"depth": 2}


class TestCmdGetBuildInfo:
    def test_get_build_info(self, capsys):
        with contextlib.ExitStack() as stack:
            stack.enter_context(_mock_target_patch())
            rj = stack.enter_context(mock.patch("jenkins_api.request_json"))
            rj.return_value = {"id": "5", "result": "SUCCESS"}
            args = mock.MagicMock(job="job-a", number="5", jenkins=None, user=None, system=None)
            rc = jenkins_api.cmd_get_build_info(args)
        assert rc == 0
        args_called, _ = rj.call_args
        assert "/job/job-a/5/api/json" in args_called[2]

    def test_get_build_info_lastbuild(self, capsys):
        with contextlib.ExitStack() as stack:
            stack.enter_context(_mock_target_patch())
            rj = stack.enter_context(mock.patch("jenkins_api.request_json"))
            rj.return_value = {"id": "10"}
            args = mock.MagicMock(
                job="job-a", number="lastBuild", jenkins=None, user=None, system=None
            )
            jenkins_api.cmd_get_build_info(args)
        args_called, _ = rj.call_args
        assert "/job/job-a/lastBuild/api/json" in args_called[2]


class TestCmdGetConsoleLog:
    def test_get_console_log_json(self, capsys):
        with contextlib.ExitStack() as stack:
            stack.enter_context(_mock_target_patch())
            rt = stack.enter_context(mock.patch("jenkins_api.request_text"))
            rt.return_value = "line1\nline2\n"
            args = mock.MagicMock(
                job="job-a", number="3", raw=False, jenkins=None, user=None, system=None
            )
            rc = jenkins_api.cmd_get_console_log(args)
        out = capsys.readouterr().out
        assert rc == 0
        payload = json.loads(out)
        assert payload["data"]["log"] == "line1\nline2\n"
        assert payload["data"]["job"] == "job-a"
        assert payload["data"]["number"] == "3"
        args_called, _ = rt.call_args
        assert "/job/job-a/3/consoleText" in args_called[2]
        assert rt.call_args.kwargs == {}

    def test_get_console_log_raw(self, capsys):
        with contextlib.ExitStack() as stack:
            stack.enter_context(_mock_target_patch())
            rt = stack.enter_context(mock.patch("jenkins_api.request_text"))
            rt.return_value = "line1\nline2\n"
            args = mock.MagicMock(
                job="job-a", number="3", raw=True, jenkins=None, user=None, system=None
            )
            rc = jenkins_api.cmd_get_console_log(args)
        assert rc == 0
        assert capsys.readouterr().out == "line1\nline2\n"


# ===================================================================
# matches_result_filter
# ===================================================================


class TestMatchesResultFilter:
    def test_literal_match(self):
        assert jenkins_api.matches_result_filter("FAILURE", "FAILURE") is True

    def test_literal_no_match(self):
        assert jenkins_api.matches_result_filter("SUCCESS", "FAILURE") is False

    def test_negation_keeps_other_results(self):
        assert jenkins_api.matches_result_filter("FAILURE", "!SUCCESS") is True
        assert jenkins_api.matches_result_filter("UNSTABLE", "!SUCCESS") is True
        assert jenkins_api.matches_result_filter("ABORTED", "!SUCCESS") is True

    def test_negation_excludes_negated_value(self):
        assert jenkins_api.matches_result_filter("SUCCESS", "!SUCCESS") is False

    def test_negation_excludes_none_running_build(self):
        # running builds have result=None; !SUCCESS must not pick them up
        assert jenkins_api.matches_result_filter(None, "!SUCCESS") is False

    def test_literal_against_none(self):
        assert jenkins_api.matches_result_filter(None, "FAILURE") is False


# ===================================================================
# cmd_list_builds
# ===================================================================


class TestCmdListBuilds:
    def _args(self, **overrides):
        defaults = {
            "job": "job-a",
            "since_hours": 24,
            "limit": 50,
            "result": None,
            "jenkins": None,
            "user": None,
            "system": None,
        }
        defaults.update(overrides)
        return mock.MagicMock(**defaults)

    def test_emits_json_envelope(self, capsys):
        builds = [
            {
                "number": 3,
                "timestamp": 9_999_999_999_999,
                "result": "FAILURE",
                "duration": 1000,
                "url": "http://j/job-a/3",
            },
            {
                "number": 2,
                "timestamp": 9_999_999_999_998,
                "result": "SUCCESS",
                "duration": 500,
                "url": "http://j/job-a/2",
            },
        ]
        with contextlib.ExitStack() as stack:
            stack.enter_context(_mock_target_patch())
            rj = stack.enter_context(mock.patch("jenkins_api.request_json"))
            rj.return_value = {"builds": builds}
            rc = jenkins_api.cmd_list_builds(self._args())
        out = capsys.readouterr().out
        assert rc == 0
        parsed = json.loads(out)["data"]
        assert isinstance(parsed, list)
        assert len(parsed) == 2
        assert parsed[0]["number"] == 3
        assert parsed[0]["result"] == "FAILURE"

    def test_tree_range_applied_when_limit_positive(self):
        with contextlib.ExitStack() as stack:
            stack.enter_context(_mock_target_patch())
            rj = stack.enter_context(mock.patch("jenkins_api.request_json"))
            rj.return_value = {"builds": []}
            jenkins_api.cmd_list_builds(self._args(limit=30))
        _, kw = rj.call_args
        assert "{0,30}" in kw["params"]["tree"]

    def test_tree_no_range_when_limit_zero(self):
        with contextlib.ExitStack() as stack:
            stack.enter_context(_mock_target_patch())
            rj = stack.enter_context(mock.patch("jenkins_api.request_json"))
            rj.return_value = {"builds": []}
            jenkins_api.cmd_list_builds(self._args(limit=0))
        _, kw = rj.call_args
        assert "{0" not in kw["params"]["tree"]

    def test_since_hours_filters_old_builds(self, capsys):
        now_ms = 1_700_000_000 * 1000
        with mock.patch("jenkins_api.time.time", return_value=1_700_000_000):
            with contextlib.ExitStack() as stack:
                stack.enter_context(_mock_target_patch())
                rj = stack.enter_context(mock.patch("jenkins_api.request_json"))
                rj.return_value = {
                    "builds": [
                        {"number": 5, "timestamp": now_ms - 1000, "result": "FAILURE"},
                        {"number": 4, "timestamp": now_ms - 100 * 3600 * 1000, "result": "FAILURE"},
                    ]
                }
                rc = jenkins_api.cmd_list_builds(self._args(since_hours=24))
        parsed = json.loads(capsys.readouterr().out)["data"]
        assert rc == 0
        assert [b["number"] for b in parsed] == [5]

    def test_since_hours_zero_keeps_nothing(self, capsys):
        now_ms = 1_700_000_000 * 1000
        with mock.patch("jenkins_api.time.time", return_value=1_700_000_000):
            with contextlib.ExitStack() as stack:
                stack.enter_context(_mock_target_patch())
                rj = stack.enter_context(mock.patch("jenkins_api.request_json"))
                rj.return_value = {
                    "builds": [{"number": 1, "timestamp": now_ms - 1, "result": "FAILURE"}]
                }
                rc = jenkins_api.cmd_list_builds(self._args(since_hours=0))
        assert rc == 0
        assert json.loads(capsys.readouterr().out)["data"] == []

    def test_build_without_timestamp_dropped_when_filtering(self, capsys):
        with mock.patch("jenkins_api.time.time", return_value=1_700_000_000):
            with contextlib.ExitStack() as stack:
                stack.enter_context(_mock_target_patch())
                rj = stack.enter_context(mock.patch("jenkins_api.request_json"))
                rj.return_value = {
                    "builds": [
                        {"number": 1, "result": "FAILURE"},
                        {
                            "number": 2,
                            "timestamp": 1_700_000_000 * 1000 - 1000,
                            "result": "FAILURE",
                        },
                    ]
                }
                rc = jenkins_api.cmd_list_builds(self._args(since_hours=24))
        parsed = json.loads(capsys.readouterr().out)["data"]
        assert rc == 0
        assert [b["number"] for b in parsed] == [2]

    def test_result_negation_success(self, capsys):
        with mock.patch("jenkins_api.time.time", return_value=1_700_000_000):
            with contextlib.ExitStack() as stack:
                stack.enter_context(_mock_target_patch())
                rj = stack.enter_context(mock.patch("jenkins_api.request_json"))
                rj.return_value = {
                    "builds": [
                        {"number": 1, "timestamp": 1_700_000_000 * 1000, "result": "SUCCESS"},
                        {"number": 2, "timestamp": 1_700_000_000 * 1000, "result": "FAILURE"},
                        {"number": 3, "timestamp": 1_700_000_000 * 1000, "result": None},
                    ]
                }
                rc = jenkins_api.cmd_list_builds(self._args(since_hours=24, result="!SUCCESS"))
        parsed = json.loads(capsys.readouterr().out)["data"]
        assert rc == 0
        assert [b["number"] for b in parsed] == [2]

    def test_result_literal_filter(self, capsys):
        with mock.patch("jenkins_api.time.time", return_value=1_700_000_000):
            with contextlib.ExitStack() as stack:
                stack.enter_context(_mock_target_patch())
                rj = stack.enter_context(mock.patch("jenkins_api.request_json"))
                rj.return_value = {
                    "builds": [
                        {"number": 1, "timestamp": 1_700_000_000 * 1000, "result": "FAILURE"},
                        {"number": 2, "timestamp": 1_700_000_000 * 1000, "result": "ABORTED"},
                    ]
                }
                rc = jenkins_api.cmd_list_builds(self._args(since_hours=24, result="ABORTED"))
        parsed = json.loads(capsys.readouterr().out)["data"]
        assert rc == 0
        assert [b["number"] for b in parsed] == [2]

    def test_non_dict_response(self, capsys):
        with contextlib.ExitStack() as stack:
            stack.enter_context(_mock_target_patch())
            rj = stack.enter_context(mock.patch("jenkins_api.request_json"))
            rj.return_value = []
            rc = jenkins_api.cmd_list_builds(self._args())
        assert rc == 0
        assert json.loads(capsys.readouterr().out)["data"] == []

    def test_non_dict_build_entry_skipped(self, capsys):
        with mock.patch("jenkins_api.time.time", return_value=1_700_000_000):
            with contextlib.ExitStack() as stack:
                stack.enter_context(_mock_target_patch())
                rj = stack.enter_context(mock.patch("jenkins_api.request_json"))
                rj.return_value = {
                    "builds": [
                        "not-a-dict",
                        {"number": 9, "timestamp": 1_700_000_000 * 1000, "result": "FAILURE"},
                    ]
                }
                rc = jenkins_api.cmd_list_builds(self._args(since_hours=24))
        parsed = json.loads(capsys.readouterr().out)["data"]
        assert rc == 0
        assert [b["number"] for b in parsed] == [9]


class TestCmdBuildJob:
    def test_build_without_params(self, capsys):
        with contextlib.ExitStack() as stack:
            stack.enter_context(_mock_target_patch())
            rt = stack.enter_context(mock.patch("jenkins_api.request_text"))
            rt.return_value = ""
            args = mock.MagicMock(job="job-a", param=[], jenkins=None, user=None, system=None)
            rc = jenkins_api.cmd_build_job(args)
        out = capsys.readouterr().out
        assert rc == 0
        payload = json.loads(out)
        assert payload["data"] == {"job": "job-a", "action": "triggered"}
        args_called, kwargs = rt.call_args
        assert "/job/job-a/build" in args_called[2]
        assert kwargs["body"] is None
        assert kwargs["headers"] is None
        assert kwargs["include_crumb"] is True

    def test_build_with_params(self, capsys):
        with contextlib.ExitStack() as stack:
            stack.enter_context(_mock_target_patch())
            rt = stack.enter_context(mock.patch("jenkins_api.request_text"))
            rt.return_value = "Queued"
            args = mock.MagicMock(
                job="job-a",
                param=["BRANCH=main", "DEBUG=true"],
                jenkins=None,
                user=None,
                system=None,
            )
            rc = jenkins_api.cmd_build_job(args)
        out = capsys.readouterr().out
        assert rc == 0
        payload = json.loads(out)
        assert payload["data"]["job"] == "job-a"
        assert payload["data"]["action"] == "triggered"
        assert payload["data"]["response"] == "Queued"
        args_called, kwargs = rt.call_args
        assert "/job/job-a/buildWithParameters" in args_called[2]
        assert kwargs["body"] == b"BRANCH=main&DEBUG=true"
        assert "x-www-form-urlencoded" in kwargs["headers"]["Content-Type"]
        assert kwargs["include_crumb"] is True


class TestCmdListQueue:
    def test_list_queue(self, capsys):
        with contextlib.ExitStack() as stack:
            stack.enter_context(_mock_target_patch())
            rj = stack.enter_context(mock.patch("jenkins_api.request_json"))
            rj.return_value = {"items": [{"id": 1}]}
            args = mock.MagicMock(jenkins=None, user=None, system=None)
            rc = jenkins_api.cmd_list_queue(args)
        assert rc == 0
        args_called, _ = rj.call_args
        assert args_called[2] == "/queue/api/json"


class TestCmdDisableJob:
    def test_disable_job(self, capsys):
        with contextlib.ExitStack() as stack:
            stack.enter_context(_mock_target_patch())
            rt = stack.enter_context(mock.patch("jenkins_api.request_text"))
            rt.return_value = ""
            args = mock.MagicMock(job="job-a", jenkins=None, user=None, system=None)
            rc = jenkins_api.cmd_disable_job(args)
        out = capsys.readouterr().out
        assert rc == 0
        assert json.loads(out)["data"] == {"job": "job-a", "action": "disabled"}
        args_called, kwargs = rt.call_args
        assert "/job/job-a/disable" in args_called[2]
        assert kwargs["include_crumb"] is True


class TestCmdEnableJob:
    def test_enable_job(self, capsys):
        with contextlib.ExitStack() as stack:
            stack.enter_context(_mock_target_patch())
            rt = stack.enter_context(mock.patch("jenkins_api.request_text"))
            rt.return_value = ""
            args = mock.MagicMock(job="job-a", jenkins=None, user=None, system=None)
            rc = jenkins_api.cmd_enable_job(args)
        out = capsys.readouterr().out
        assert rc == 0
        assert json.loads(out)["data"] == {"job": "job-a", "action": "enabled"}
        args_called, kwargs = rt.call_args
        assert "/job/job-a/enable" in args_called[2]
        assert kwargs["include_crumb"] is True


class TestCmdStopBuild:
    def test_stop_build(self, capsys):
        with contextlib.ExitStack() as stack:
            stack.enter_context(_mock_target_patch())
            rt = stack.enter_context(mock.patch("jenkins_api.request_text"))
            rt.return_value = ""
            args = mock.MagicMock(job="job-a", number="7", jenkins=None, user=None, system=None)
            rc = jenkins_api.cmd_stop_build(args)
        out = capsys.readouterr().out
        assert rc == 0
        assert json.loads(out)["data"] == {
            "job": "job-a",
            "number": "7",
            "action": "stopped",
        }
        args_called, kwargs = rt.call_args
        assert "/job/job-a/7/stop" in args_called[2]
        assert kwargs["include_crumb"] is True


# ===================================================================
# CLI parser
# ===================================================================


class TestCli:
    def test_all_subcommands_present(self):
        parser = jenkins_api.build_parser()
        choices = parser._subparsers._actions[-1].choices
        for cmd in (
            "list-jobs",
            "get-job",
            "get-build-info",
            "get-console-log",
            "list-builds",
            "build-job",
            "list-queue",
            "list-nodes",
            "disable-job",
            "enable-job",
            "stop-build",
        ):
            assert cmd in choices, f"Missing: {cmd}"

    def test_missing_subcommand_exits(self):
        with pytest.raises(SystemExit):
            jenkins_api.build_parser().parse_args([])

    def test_get_job_requires_job(self):
        with pytest.raises(SystemExit):
            jenkins_api.build_parser().parse_args(["get-job"])

    def test_common_args(self):
        args = jenkins_api.build_parser().parse_args(
            ["list-jobs", "--jenkins", "http://j", "--system", "s", "--user", "u:t"]
        )
        assert args.jenkins == "http://j"
        assert args.system == "s"
        assert args.user == "u:t"

    def test_get_job_depth_default_none(self):
        args = jenkins_api.build_parser().parse_args(["get-job", "--job", "x"])
        assert args.depth is None

    def test_get_job_depth_int(self):
        args = jenkins_api.build_parser().parse_args(["get-job", "--job", "x", "--depth", "3"])
        assert args.depth == 3

    def test_build_number_default(self):
        args = jenkins_api.build_parser().parse_args(["get-build-info", "--job", "x"])
        assert args.number == "lastBuild"

    def test_build_job_param_append(self):
        args = jenkins_api.build_parser().parse_args(
            ["build-job", "--job", "x", "--param", "A=1", "--param", "B=2"]
        )
        assert args.param == ["A=1", "B=2"]

    def test_build_job_param_default_empty(self):
        args = jenkins_api.build_parser().parse_args(["build-job", "--job", "x"])
        assert args.param == []

    def test_list_builds_defaults(self):
        args = jenkins_api.build_parser().parse_args(["list-builds", "--job", "x"])
        assert args.since_hours == 24
        assert args.limit == 50
        assert args.result is None
        assert args.handler is jenkins_api.cmd_list_builds

    def test_list_builds_custom_values(self):
        args = jenkins_api.build_parser().parse_args(
            [
                "list-builds",
                "--job",
                "x",
                "--since-hours",
                "12",
                "--limit",
                "10",
                "--result",
                "!SUCCESS",
            ]
        )
        assert args.since_hours == 12
        assert args.limit == 10
        assert args.result == "!SUCCESS"

    def test_list_builds_requires_job(self):
        with pytest.raises(SystemExit):
            jenkins_api.build_parser().parse_args(["list-builds"])

    def test_handler_dispatch(self):
        args = jenkins_api.build_parser().parse_args(["list-queue"])
        assert args.handler is jenkins_api.cmd_list_queue

    def test_list_nodes_offline_default_false(self):
        args = jenkins_api.build_parser().parse_args(["list-nodes"])
        assert args.offline is False
        assert args.handler is jenkins_api.cmd_list_nodes

    def test_list_nodes_offline_flag(self):
        args = jenkins_api.build_parser().parse_args(["list-nodes", "--offline"])
        assert args.offline is True


# ===================================================================
# main()
# ===================================================================


class TestMain:
    def test_success_path(self, capsys):
        with mock.patch.object(jenkins_api, "build_parser") as bp:
            bp.return_value.parse_args.return_value = mock.MagicMock(
                handler=mock.MagicMock(return_value=0)
            )
            rc = jenkins_api.main()
        assert rc == 0

    def test_jenkins_error_path(self, capsys):
        handler = mock.MagicMock(side_effect=JenkinsError("boom", status_code=500))
        with mock.patch.object(jenkins_api, "build_parser") as bp:
            bp.return_value.parse_args.return_value = mock.MagicMock(handler=handler)
            rc = jenkins_api.main()
        captured = capsys.readouterr()
        assert rc == 1
        assert captured.out == ""  # stdout 保持空，错误走 stderr
        payload = json.loads(captured.err)
        assert payload["error"]["message"] == "boom"
        assert payload["error"]["status_code"] == 500

    def test_main_invokes_real_handler(self, capsys):
        # End-to-end via the real parser, with _target + urlopen mocked.
        with (
            mock.patch("jenkins_api._target", return_value=MOCK_TARGET),
            mock.patch("urllib.request.urlopen") as m,
            mock.patch("sys.argv", ["jenkins_api", "list-jobs"]),
        ):
            m.return_value = _urlopen_cm(
                json.dumps({"jobs": [{"name": "a", "url": "u", "color": "blue"}]}).encode()
            )
            rc = jenkins_api.main()
        assert rc == 0
        payload = json.loads(capsys.readouterr().out)
        assert len(payload["data"]["jobs"]) == 1
        assert payload["data"]["jobs"][0]["name"] == "a"

    def test_main_jenkins_error_via_real_path(self, capsys):
        # Real path that raises JenkinsError (HTTPError -> JenkinsError) and is
        # caught by main's try/except.
        with (
            mock.patch("jenkins_api._target", return_value=MOCK_TARGET),
            mock.patch("urllib.request.urlopen") as m,
            mock.patch("sys.argv", ["jenkins_api", "list-jobs"]),
        ):
            m.side_effect = _http_error(404, b"nope")
            rc = jenkins_api.main()
        assert rc == 1
        captured = capsys.readouterr()
        assert captured.out == ""
        payload = json.loads(captured.err)
        assert payload["error"]["status_code"] == 404
