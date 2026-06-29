"""Tests for zentao_api.py — helpers, request_json, CLI parsing, commands."""

from __future__ import annotations

import contextlib
import json
from unittest import mock

import pytest
import zentao_api

from system_config import ServiceError

# Convenience: a canned ZentaoTarget that doesn't need a real config file.
MOCK_TARGET = zentao_api.ZentaoTarget(
    url="http://mock.z.com", auth=("admin", "pass"), system_name="mock"
)


def _mock_target_patch():
    return mock.patch("zentao_api._target", return_value=MOCK_TARGET)


def _confirm_yes():
    return mock.patch("builtins.input", return_value="y")


def _confirm_no():
    return mock.patch("builtins.input", return_value="n")


def _auth_patch():
    return mock.patch("zentao_api.get_token", return_value="mock_token")


# ===================================================================
# _build_url
# ===================================================================


class TestBuildUrl:
    def test_plain(self):
        url = zentao_api._build_url("http://zentao.example.com", "/bugs")
        assert url == "http://zentao.example.com/api.php/v2/bugs"

    def test_with_params(self):
        url = zentao_api._build_url(
            "http://zentao.example.com", "/bugs", params={"page": 1, "limit": 20}
        )
        assert "page=1" in url
        assert "limit=20" in url
        assert "api.php/v2/bugs" in url

    def test_base_url_trailing_slash(self):
        url = zentao_api._build_url("http://zentao.example.com/", "/bugs")
        assert url == "http://zentao.example.com/api.php/v2/bugs"


# ===================================================================
# request_json
# ===================================================================


class TestRequestJson:
    def test_get_returns_parsed_json(self):
        with mock.patch("urllib.request.urlopen") as m:
            cm = mock.MagicMock()
            cm.read.return_value = b'{"status": "success", "data": {"id": 1}}'
            cm.__enter__.return_value = cm
            m.return_value = cm

            result = zentao_api.request_json("GET", "http://zentao.example.com", "/bugs/1")

            assert result == {"status": "success", "data": {"id": 1}}

    def test_post_with_payload(self):
        with mock.patch("urllib.request.urlopen") as m:
            cm = mock.MagicMock()
            cm.read.return_value = b'{"status": "success", "data": {"id": 42}}'
            cm.__enter__.return_value = cm
            m.return_value = cm

            result = zentao_api.request_json(
                "POST",
                "http://zentao.example.com",
                "/bugs",
                payload={"product": 1, "title": "test"},
            )
            assert result["data"]["id"] == 42

            call_args = m.call_args[0][0]
            sent = json.loads(call_args.data)
            assert sent == {"product": 1, "title": "test"}

    def test_put_request(self):
        with mock.patch("urllib.request.urlopen") as m:
            cm = mock.MagicMock()
            cm.read.return_value = b'{"status": "success"}'
            cm.__enter__.return_value = cm
            m.return_value = cm

            result = zentao_api.request_json(
                "PUT",
                "http://zentao.example.com",
                "/bugs/1",
                payload={"title": "updated"},
            )
            assert result["status"] == "success"
            assert m.call_args[0][0].method == "PUT"

    def test_delete_request(self):
        with mock.patch("urllib.request.urlopen") as m:
            cm = mock.MagicMock()
            cm.read.return_value = b'{"status": "success"}'
            cm.__enter__.return_value = cm
            m.return_value = cm

            result = zentao_api.request_json("DELETE", "http://zentao.example.com", "/bugs/1")
            assert result["status"] == "success"
            assert m.call_args[0][0].method == "DELETE"

    def test_returns_none_for_empty_body(self):
        with mock.patch("urllib.request.urlopen") as m:
            cm = mock.MagicMock()
            cm.read.return_value = b""
            cm.__enter__.return_value = cm
            m.return_value = cm

            result = zentao_api.request_json("GET", "http://zentao.example.com", "/bugs")
            assert result is None

    def test_http_error_raises_zentao_error(self):
        with mock.patch("urllib.request.urlopen") as m:
            from urllib.error import HTTPError

            exc = HTTPError("http://example.com", 404, "Not Found", {}, None)
            m.side_effect = exc

            with pytest.raises(ServiceError) as exc_info:
                zentao_api.request_json("GET", "http://zentao.example.com", "/bugs/999")
            assert exc_info.value.status_code == 404

    def test_url_error_raises_zentao_error(self):
        with mock.patch("urllib.request.urlopen") as m:
            from urllib.error import URLError

            m.side_effect = URLError("Connection refused")

            with pytest.raises(ServiceError) as exc_info:
                zentao_api.request_json("GET", "http://zentao.example.com", "/bugs")
            assert "网络错误" in str(exc_info.value)

    def test_non_json_response_raises_zentao_error(self):
        with mock.patch("urllib.request.urlopen") as m:
            cm = mock.MagicMock()
            cm.read.return_value = b"not json"
            cm.__enter__.return_value = cm
            m.return_value = cm

            with pytest.raises(ServiceError) as exc_info:
                zentao_api.request_json("GET", "http://zentao.example.com", "/bugs")
            assert "JSON" in str(exc_info.value)

    def test_bearer_token_in_header(self):
        with mock.patch("urllib.request.urlopen") as m:
            cm = mock.MagicMock()
            cm.read.return_value = b"{}"
            cm.__enter__.return_value = cm
            m.return_value = cm

            zentao_api.request_json("GET", "http://zentao.example.com", "/bugs", token="mytoken")
            req = m.call_args[0][0]
            # urllib.request.Request stores headers as a case-insensitive dict
            assert req.get_header("Authorization") == "Bearer mytoken"

    def test_content_type_header(self):
        with mock.patch("urllib.request.urlopen") as m:
            cm = mock.MagicMock()
            cm.read.return_value = b"{}"
            cm.__enter__.return_value = cm
            m.return_value = cm

            zentao_api.request_json("POST", "http://zentao.example.com", "/bugs", payload={"a": 1})
            req = m.call_args[0][0]
            content_type = req.get_header("Content-type")
            assert content_type and "application/json" in content_type


# ===================================================================
# Token management
# ===================================================================


class TestGetToken:
    def test_get_token_returns_token_string(self):
        target = zentao_api.ZentaoTarget(url="http://zentao.example.com", auth=("admin", "pass"))
        with mock.patch("zentao_api.request_json") as m:
            m.return_value = {"token": "eyJ0eXAi"}
            token = zentao_api.get_token(target)
            assert token == "eyJ0eXAi"

    def test_get_token_caches_token(self):
        target = zentao_api.ZentaoTarget(url="http://zentao.example.com", auth=("admin", "pass"))
        with mock.patch("zentao_api.request_json") as m:
            m.return_value = {"token": "cached_token"}
            zentao_api.get_token(target)
            zentao_api.get_token(target)
            assert m.call_count == 1

    def test_get_token_http_error(self):
        target = zentao_api.ZentaoTarget(url="http://zentao.example.com", auth=("admin", "pass"))
        with mock.patch("zentao_api.request_json") as m:
            m.return_value = {"no_token": True}
            with pytest.raises(ServiceError) as exc_info:
                zentao_api.get_token(target)
            assert "token" in str(exc_info.value).lower()


class TestTokenRefresh:
    def test_401_triggers_token_refresh(self):
        """request_json raises 401, then get_token(force=True) returns new token, retry succeeds."""
        target = zentao_api.ZentaoTarget(url="http://z.com", auth=("admin", "p"))

        real_with_auth = zentao_api.request_json_with_auth

        with mock.patch.object(zentao_api, "get_token") as gt:
            gt.side_effect = ["first_token", "refreshed_token"]

            # Mock request_json so the first call after each get_token raises 401,
            # and the retry call succeeds.
            original_calls = [0]

            def fake_req_json(method, url, path, **kw):
                original_calls[0] += 1
                if original_calls[0] == 1:
                    raise ServiceError("expired", status_code=401)
                return {"status": "success"}

            with mock.patch.object(zentao_api, "request_json", side_effect=fake_req_json):
                result = real_with_auth("GET", "http://z.com", "/bugs", target=target)
                assert result == {"status": "success"}

            # get_token called twice: once cached, once force-refreshed
            assert gt.call_count == 2

    def test_force_token_flag_bypasses_cache(self):
        target = zentao_api.ZentaoTarget(url="http://zentao.example.com", auth=("admin", "pass"))
        target._zentao_token = "old_token"
        with mock.patch("zentao_api.request_json") as m:
            m.return_value = {"token": "new_token"}
            token = zentao_api.get_token(target, force=True)
            assert token == "new_token"


# ===================================================================
# Danger confirmation
# ===================================================================


class TestConfirmDangerous:
    def test_confirm_yes_continues(self):
        with mock.patch("builtins.input", return_value="y"):
            zentao_api.confirm_dangerous("delete-bug", "永久删除 Bug", "Bug ID=1")

    def test_confirm_no_raises_system_exit(self):
        with mock.patch("builtins.input", return_value="n"), pytest.raises(SystemExit):
            zentao_api.confirm_dangerous("delete-bug", "永久删除 Bug", "Bug ID=1")

    def test_confirm_empty_raises_system_exit(self):
        with mock.patch("builtins.input", return_value=""), pytest.raises(SystemExit):
            zentao_api.confirm_dangerous("delete-bug", "永久删除 Bug", "Bug ID=1")

    def test_confirm_y_uppercase_continues(self):
        with mock.patch("builtins.input", return_value="Y"):
            zentao_api.confirm_dangerous("delete-bug", "永久删除 Bug", "Bug ID=1")

    def test_confirm_eof_raises_system_exit(self):
        with mock.patch("builtins.input", side_effect=EOFError), pytest.raises(SystemExit):
            zentao_api.confirm_dangerous("delete-bug", "永久删除 Bug", "Bug ID=1")

    def test_confirm_keyboard_interrupt_raises_system_exit(self):
        with (
            mock.patch("builtins.input", side_effect=KeyboardInterrupt),
            pytest.raises(SystemExit),
        ):
            zentao_api.confirm_dangerous("delete-bug", "永久删除 Bug", "Bug ID=1")


class TestDeleteConfirmation:
    def test_delete_bug_prompts_confirmation(self):
        with (
            _confirm_yes(),
            _auth_patch(),
            _mock_target_patch(),
            mock.patch("zentao_api.request_json_with_auth") as rj,
        ):
            rj.return_value = {"status": "success"}
            args = mock.MagicMock(id=1, zentao=None, system=None, user=None)
            zentao_api.cmd_delete_bug(args)

    def test_delete_task_prompts_confirmation(self):
        with (
            _confirm_yes(),
            _auth_patch(),
            _mock_target_patch(),
            mock.patch("zentao_api.request_json_with_auth") as rj,
        ):
            rj.return_value = {"status": "success"}
            args = mock.MagicMock(id=1, zentao=None, system=None, user=None)
            zentao_api.cmd_delete_task(args)

    def test_delete_story_prompts_confirmation(self):
        with (
            _confirm_yes(),
            _auth_patch(),
            _mock_target_patch(),
            mock.patch("zentao_api.request_json_with_auth") as rj,
        ):
            rj.return_value = {"status": "success"}
            args = mock.MagicMock(id=1, zentao=None, system=None, user=None)
            zentao_api.cmd_delete_story(args)


# ===================================================================
# Bug commands
# ===================================================================


class _CmdMixin:
    """Provides (confirmed, auth, target) helpers for command tests."""

    @staticmethod
    def _enter_default(stack):
        stack.enter_context(_mock_target_patch())
        stack.enter_context(_auth_patch())

    @staticmethod
    def _enter_write(stack):
        stack.enter_context(_confirm_yes())
        stack.enter_context(_mock_target_patch())
        stack.enter_context(_auth_patch())


class TestCmdListBugs(_CmdMixin):
    def test_list_bugs_calls_api(self):
        with contextlib.ExitStack() as stack:
            _CmdMixin._enter_default(stack)
            rj = stack.enter_context(mock.patch("zentao_api.request_json_with_auth"))
            rj.return_value = {"status": "success", "data": []}
            args = mock.MagicMock(
                product=None,
                project=None,
                page=None,
                limit=None,
                zentao=None,
                system=None,
                user=None,
            )
            zentao_api.cmd_list_bugs(args)
            rj.assert_called_once()

    def test_list_bugs_with_product_filter(self):
        with contextlib.ExitStack() as stack:
            _CmdMixin._enter_default(stack)
            rj = stack.enter_context(mock.patch("zentao_api.request_json_with_auth"))
            rj.return_value = {"status": "success"}
            args = mock.MagicMock(
                product=1, project=None, page=None, limit=None, zentao=None, system=None, user=None
            )
            zentao_api.cmd_list_bugs(args)

    def test_list_bugs_with_pagination(self):
        with contextlib.ExitStack() as stack:
            _CmdMixin._enter_default(stack)
            rj = stack.enter_context(mock.patch("zentao_api.request_json_with_auth"))
            rj.return_value = {"status": "success"}
            args = mock.MagicMock(
                product=None, project=None, page=2, limit=10, zentao=None, system=None, user=None
            )
            zentao_api.cmd_list_bugs(args)
            _, kwargs = rj.call_args
            assert kwargs["params"]["page"] == 2
            assert kwargs["params"]["limit"] == 10

    def test_list_bugs_empty_result(self):
        with contextlib.ExitStack() as stack:
            _CmdMixin._enter_default(stack)
            rj = stack.enter_context(mock.patch("zentao_api.request_json_with_auth"))
            rj.return_value = {"status": "success", "data": []}
            args = mock.MagicMock(
                product=None,
                project=None,
                page=None,
                limit=None,
                zentao=None,
                system=None,
                user=None,
            )
            rc = zentao_api.cmd_list_bugs(args)
            assert rc == 0


class TestCmdGetBug(_CmdMixin):
    def test_get_bug_by_id(self):
        with contextlib.ExitStack() as stack:
            _CmdMixin._enter_default(stack)
            rj = stack.enter_context(mock.patch("zentao_api.request_json_with_auth"))
            rj.return_value = {"status": "success", "data": {"id": 1, "title": "test"}}
            args = mock.MagicMock(id=1, zentao=None, system=None, user=None)
            rc = zentao_api.cmd_get_bug(args)
            assert rc == 0

    def test_get_bug_not_found(self):
        with contextlib.ExitStack() as stack:
            _CmdMixin._enter_default(stack)
            rj = stack.enter_context(mock.patch("zentao_api.request_json_with_auth"))
            rj.side_effect = ServiceError("请求失败", status_code=404)
            args = mock.MagicMock(id=999, zentao=None, system=None, user=None)
            with pytest.raises(ServiceError):
                zentao_api.cmd_get_bug(args)


class TestCmdCreateBug(_CmdMixin):
    def test_create_bug_with_required_fields(self):
        with contextlib.ExitStack() as stack:
            _CmdMixin._enter_write(stack)
            rj = stack.enter_context(mock.patch("zentao_api.request_json_with_auth"))
            rj.return_value = {"status": "success", "data": {"id": 42}}
            args = mock.MagicMock(
                product=1,
                title="Test Bug",
                severity=None,
                pri=None,
                type=None,
                assigned_to=None,
                zentao=None,
                system=None,
                user=None,
            )
            rc = zentao_api.cmd_create_bug(args)
            assert rc == 0

    def test_create_bug_with_all_fields(self):
        with contextlib.ExitStack() as stack:
            _CmdMixin._enter_write(stack)
            rj = stack.enter_context(mock.patch("zentao_api.request_json_with_auth"))
            rj.return_value = {"status": "success", "data": {"id": 42}}
            args = mock.MagicMock(
                product=1,
                title="Test",
                severity=3,
                pri=2,
                type="codeerror",
                assigned_to="dev1",
                zentao=None,
                system=None,
                user=None,
            )
            zentao_api.cmd_create_bug(args)
            _, kwargs = rj.call_args
            assert kwargs["payload"]["severity"] == 3
            assert kwargs["payload"]["pri"] == 2

    def test_create_bug_returns_created_id(self):
        with contextlib.ExitStack() as stack:
            _CmdMixin._enter_write(stack)
            rj = stack.enter_context(mock.patch("zentao_api.request_json_with_auth"))
            rj.return_value = {"status": "success", "data": {"id": 42}}
            args = mock.MagicMock(
                product=1,
                title="Test",
                severity=None,
                pri=None,
                type=None,
                assigned_to=None,
                zentao=None,
                system=None,
                user=None,
            )
            rc = zentao_api.cmd_create_bug(args)
            assert rc == 0


class TestCmdResolveBug(_CmdMixin):
    def test_resolve_bug_with_resolution(self):
        with contextlib.ExitStack() as stack:
            _CmdMixin._enter_write(stack)
            rj = stack.enter_context(mock.patch("zentao_api.request_json_with_auth"))
            rj.return_value = {"status": "success"}
            args = mock.MagicMock(
                id=1, resolution="fixed", build=None, zentao=None, system=None, user=None
            )
            rc = zentao_api.cmd_resolve_bug(args)
            assert rc == 0


class TestCmdDeleteBug(_CmdMixin):
    def test_delete_bug_requires_confirmation(self):
        with (
            _confirm_no(),
            mock.patch("zentao_api.request_json_with_auth") as rj,
        ):
            with pytest.raises(SystemExit):
                args = mock.MagicMock(id=1, zentao=None, system=None, user=None)
                zentao_api.cmd_delete_bug(args)
            rj.assert_not_called()

    def test_delete_bug_cancelled_by_user(self):
        with (
            _confirm_no(),
            mock.patch("zentao_api.request_json_with_auth") as rj,
        ):
            with pytest.raises(SystemExit):
                args = mock.MagicMock(id=1, zentao=None, system=None, user=None)
                zentao_api.cmd_delete_bug(args)
            rj.assert_not_called()


class TestCmdCloseBug(_CmdMixin):
    def test_close_bug(self):
        with contextlib.ExitStack() as stack:
            _CmdMixin._enter_write(stack)
            rj = stack.enter_context(mock.patch("zentao_api.request_json_with_auth"))
            rj.return_value = {"status": "success"}
            args = mock.MagicMock(id=1, zentao=None, system=None, user=None)
            rc = zentao_api.cmd_close_bug(args)
            assert rc == 0


class TestCmdActivateBug(_CmdMixin):
    def test_activate_bug(self):
        with contextlib.ExitStack() as stack:
            _CmdMixin._enter_write(stack)
            rj = stack.enter_context(mock.patch("zentao_api.request_json_with_auth"))
            rj.return_value = {"status": "success"}
            args = mock.MagicMock(id=1, zentao=None, system=None, user=None)
            rc = zentao_api.cmd_activate_bug(args)
            assert rc == 0


# ===================================================================
# Task commands
# ===================================================================


class TestCmdListTasks(_CmdMixin):
    def test_list_tasks_by_project(self):
        with contextlib.ExitStack() as stack:
            _CmdMixin._enter_default(stack)
            rj = stack.enter_context(mock.patch("zentao_api.request_json_with_auth"))
            rj.return_value = {"status": "success"}
            args = mock.MagicMock(
                project=1,
                execution=None,
                assigned_to=None,
                status=None,
                page=None,
                limit=None,
                zentao=None,
                system=None,
                user=None,
            )
            zentao_api.cmd_list_tasks(args)
            _, kwargs = rj.call_args
            assert kwargs["params"]["project"] == 1

    def test_list_tasks_by_execution(self):
        with contextlib.ExitStack() as stack:
            _CmdMixin._enter_default(stack)
            rj = stack.enter_context(mock.patch("zentao_api.request_json_with_auth"))
            rj.return_value = {"status": "success"}
            args = mock.MagicMock(
                project=None,
                execution=5,
                assigned_to=None,
                status=None,
                page=None,
                limit=None,
                zentao=None,
                system=None,
                user=None,
            )
            zentao_api.cmd_list_tasks(args)
            _, kwargs = rj.call_args
            assert kwargs["params"]["execution"] == 5

    def test_list_tasks_with_pagination(self):
        with contextlib.ExitStack() as stack:
            _CmdMixin._enter_default(stack)
            rj = stack.enter_context(mock.patch("zentao_api.request_json_with_auth"))
            rj.return_value = {"status": "success"}
            args = mock.MagicMock(
                project=None,
                execution=None,
                assigned_to=None,
                status=None,
                page=2,
                limit=20,
                zentao=None,
                system=None,
                user=None,
            )
            zentao_api.cmd_list_tasks(args)
            _, kwargs = rj.call_args
            assert kwargs["params"]["page"] == 2


class TestCmdGetTask(_CmdMixin):
    def test_get_task_by_id(self):
        with contextlib.ExitStack() as stack:
            _CmdMixin._enter_default(stack)
            rj = stack.enter_context(mock.patch("zentao_api.request_json_with_auth"))
            rj.return_value = {"status": "success", "data": {"id": 1}}
            args = mock.MagicMock(id=1, zentao=None, system=None, user=None)
            rc = zentao_api.cmd_get_task(args)
            assert rc == 0


class TestCmdCreateTask(_CmdMixin):
    def test_create_task_with_name(self):
        with contextlib.ExitStack() as stack:
            _CmdMixin._enter_write(stack)
            rj = stack.enter_context(mock.patch("zentao_api.request_json_with_auth"))
            rj.return_value = {"status": "success"}
            args = mock.MagicMock(
                project=1,
                name="New Task",
                execution=None,
                assigned_to=None,
                estimate=None,
                type=None,
                pri=None,
                desc=None,
                zentao=None,
                system=None,
                user=None,
            )
            rc = zentao_api.cmd_create_task(args)
            assert rc == 0

    def test_create_task_with_estimate(self):
        with contextlib.ExitStack() as stack:
            _CmdMixin._enter_write(stack)
            rj = stack.enter_context(mock.patch("zentao_api.request_json_with_auth"))
            rj.return_value = {"status": "success"}
            args = mock.MagicMock(
                project=1,
                name="Task",
                execution=None,
                assigned_to=None,
                estimate=8.0,
                type=None,
                pri=None,
                desc=None,
                zentao=None,
                system=None,
                user=None,
            )
            zentao_api.cmd_create_task(args)
            _, kwargs = rj.call_args
            assert kwargs["payload"]["estimate"] == 8.0


class TestCmdStartTask(_CmdMixin):
    def test_start_task_by_id(self):
        with contextlib.ExitStack() as stack:
            _CmdMixin._enter_write(stack)
            rj = stack.enter_context(mock.patch("zentao_api.request_json_with_auth"))
            rj.return_value = {"status": "success"}
            args = mock.MagicMock(id=1, zentao=None, system=None, user=None)
            rc = zentao_api.cmd_start_task(args)
            assert rc == 0


class TestCmdFinishTask(_CmdMixin):
    def test_finish_task(self):
        with contextlib.ExitStack() as stack:
            _CmdMixin._enter_write(stack)
            rj = stack.enter_context(mock.patch("zentao_api.request_json_with_auth"))
            rj.return_value = {"status": "success"}
            args = mock.MagicMock(id=1, zentao=None, system=None, user=None)
            rc = zentao_api.cmd_finish_task(args)
            assert rc == 0


class TestCmdDeleteTask(_CmdMixin):
    def test_delete_task_requires_confirmation(self):
        with (
            _confirm_no(),
            mock.patch("zentao_api.request_json_with_auth") as rj,
        ):
            with pytest.raises(SystemExit):
                args = mock.MagicMock(id=1, zentao=None, system=None, user=None)
                zentao_api.cmd_delete_task(args)
            rj.assert_not_called()


# ===================================================================
# Story commands
# ===================================================================


class TestCmdListStories(_CmdMixin):
    def test_list_stories_by_product(self):
        with contextlib.ExitStack() as stack:
            _CmdMixin._enter_default(stack)
            rj = stack.enter_context(mock.patch("zentao_api.request_json_with_auth"))
            rj.return_value = {"status": "success"}
            args = mock.MagicMock(
                product=1, page=None, limit=None, zentao=None, system=None, user=None
            )
            zentao_api.cmd_list_stories(args)
            _, kwargs = rj.call_args
            assert kwargs["params"]["product"] == 1

    def test_list_stories_pagination(self):
        with contextlib.ExitStack() as stack:
            _CmdMixin._enter_default(stack)
            rj = stack.enter_context(mock.patch("zentao_api.request_json_with_auth"))
            rj.return_value = {"status": "success"}
            args = mock.MagicMock(product=1, page=1, limit=10, zentao=None, system=None, user=None)
            zentao_api.cmd_list_stories(args)
            _, kwargs = rj.call_args
            assert kwargs["params"]["limit"] == 10


class TestCmdCreateStory(_CmdMixin):
    def test_create_story(self):
        with contextlib.ExitStack() as stack:
            _CmdMixin._enter_write(stack)
            rj = stack.enter_context(mock.patch("zentao_api.request_json_with_auth"))
            rj.return_value = {"status": "success"}
            args = mock.MagicMock(
                product=1,
                title="New Story",
                desc=None,
                pri=None,
                assigned_to=None,
                zentao=None,
                system=None,
                user=None,
            )
            rc = zentao_api.cmd_create_story(args)
            assert rc == 0


class TestCmdChangeStory(_CmdMixin):
    def test_change_story_by_id(self):
        with contextlib.ExitStack() as stack:
            _CmdMixin._enter_write(stack)
            rj = stack.enter_context(mock.patch("zentao_api.request_json_with_auth"))
            rj.return_value = {"status": "success"}
            args = mock.MagicMock(id=1, zentao=None, system=None, user=None)
            rc = zentao_api.cmd_change_story(args)
            assert rc == 0


class TestCmdUpdateStory(_CmdMixin):
    def test_update_story(self):
        with contextlib.ExitStack() as stack:
            _CmdMixin._enter_write(stack)
            rj = stack.enter_context(mock.patch("zentao_api.request_json_with_auth"))
            rj.return_value = {"status": "success"}
            args = mock.MagicMock(
                id=1,
                title="updated",
                desc=None,
                pri=None,
                status=None,
                assigned_to=None,
                zentao=None,
                system=None,
                user=None,
            )
            rc = zentao_api.cmd_update_story(args)
            assert rc == 0


# ===================================================================
# Test case commands
# ===================================================================


class TestCmdListTestcases(_CmdMixin):
    def test_list_testcases_by_product(self):
        with contextlib.ExitStack() as stack:
            _CmdMixin._enter_default(stack)
            rj = stack.enter_context(mock.patch("zentao_api.request_json_with_auth"))
            rj.return_value = {"status": "success"}
            args = mock.MagicMock(
                product=1,
                project=None,
                execution=None,
                page=None,
                limit=None,
                zentao=None,
                system=None,
                user=None,
            )
            zentao_api.cmd_list_testcases(args)
            _, kwargs = rj.call_args
            assert kwargs["params"]["product"] == 1

    def test_list_testcases_by_execution(self):
        with contextlib.ExitStack() as stack:
            _CmdMixin._enter_default(stack)
            rj = stack.enter_context(mock.patch("zentao_api.request_json_with_auth"))
            rj.return_value = {"status": "success"}
            args = mock.MagicMock(
                product=None,
                project=None,
                execution=5,
                page=None,
                limit=None,
                zentao=None,
                system=None,
                user=None,
            )
            zentao_api.cmd_list_testcases(args)
            _, kwargs = rj.call_args
            assert kwargs["params"]["execution"] == 5


class TestCmdGetTestcase(_CmdMixin):
    def test_get_testcase_by_id(self):
        with contextlib.ExitStack() as stack:
            _CmdMixin._enter_default(stack)
            rj = stack.enter_context(mock.patch("zentao_api.request_json_with_auth"))
            rj.return_value = {"status": "success", "data": {"id": 1}}
            args = mock.MagicMock(id=1, zentao=None, system=None, user=None)
            rc = zentao_api.cmd_get_testcase(args)
            assert rc == 0


class TestCmdCreateTestcase(_CmdMixin):
    def test_create_testcase(self):
        with contextlib.ExitStack() as stack:
            _CmdMixin._enter_write(stack)
            rj = stack.enter_context(mock.patch("zentao_api.request_json_with_auth"))
            rj.return_value = {"status": "success"}
            args = mock.MagicMock(
                product=1,
                title="TC",
                type=None,
                stage=None,
                pri=None,
                precondition=None,
                steps=None,
                zentao=None,
                system=None,
                user=None,
            )
            rc = zentao_api.cmd_create_testcase(args)
            assert rc == 0


class TestCmdDeleteTestcase(_CmdMixin):
    def test_delete_testcase_requires_confirmation(self):
        with (
            _confirm_no(),
            mock.patch("zentao_api.request_json_with_auth") as rj,
        ):
            with pytest.raises(SystemExit):
                args = mock.MagicMock(id=1, zentao=None, system=None, user=None)
                zentao_api.cmd_delete_testcase(args)
            rj.assert_not_called()


# ===================================================================
# Test task commands
# ===================================================================


class TestCmdListTesttasks(_CmdMixin):
    def test_list_testtasks(self):
        with contextlib.ExitStack() as stack:
            _CmdMixin._enter_default(stack)
            rj = stack.enter_context(mock.patch("zentao_api.request_json_with_auth"))
            rj.return_value = {"status": "success"}
            args = mock.MagicMock(
                product=None,
                project=None,
                execution=None,
                page=None,
                limit=None,
                zentao=None,
                system=None,
                user=None,
            )
            zentao_api.cmd_list_testtasks(args)
            rj.assert_called_once()


class TestCmdCreateTesttask(_CmdMixin):
    def test_create_testtask(self):
        with contextlib.ExitStack() as stack:
            _CmdMixin._enter_write(stack)
            rj = stack.enter_context(mock.patch("zentao_api.request_json_with_auth"))
            rj.return_value = {"status": "success"}
            args = mock.MagicMock(
                product=1,
                name="Test Run",
                project=None,
                execution=None,
                begin=None,
                end=None,
                desc=None,
                zentao=None,
                system=None,
                user=None,
            )
            rc = zentao_api.cmd_create_testtask(args)
            assert rc == 0


# ===================================================================
# CLI parsing
# ===================================================================


class TestCli:
    def test_help_shows_all_subcommands(self):
        parser = zentao_api.build_parser()
        choices = parser._subparsers._actions[-1].choices
        for cmd in (
            "list-bugs",
            "get-bug",
            "create-bug",
            "delete-bug",
            "list-tasks",
            "get-task",
            "create-task",
            "delete-task",
            "list-stories",
            "get-story",
            "create-story",
            "delete-story",
            "list-products",
            "get-product",
            "list-projects",
            "get-project",
            "list-testcases",
            "get-testcase",
        ):
            assert cmd in choices, f"Missing: {cmd}"

    def test_missing_subcommand_exits(self):
        with pytest.raises(SystemExit):
            zentao_api.build_parser().parse_args([])

    def test_list_bugs_subcommand_exists(self):
        args = zentao_api.build_parser().parse_args(["list-bugs"])
        assert args.command == "list-bugs"

    def test_get_bug_subcommand_requires_id(self):
        with pytest.raises(SystemExit):
            zentao_api.build_parser().parse_args(["get-bug"])

    def test_create_bug_subcommand_requires_product_and_title(self):
        with pytest.raises(SystemExit):
            zentao_api.build_parser().parse_args(["create-bug"])

    def test_common_args_present(self):
        args = zentao_api.build_parser().parse_args(
            ["list-bugs", "--zentao", "http://z", "--system", "s", "--user", "u:p"]
        )
        assert args.zentao == "http://z"
        assert args.system == "s"
        assert args.user == "u:p"

    def test_get_token_subcommand(self):
        args = zentao_api.build_parser().parse_args(["get-token", "--force"])
        assert args.command == "get-token"
        assert args.force is True

    def test_products_and_projects_subcommands(self):
        args = zentao_api.build_parser().parse_args(["list-products"])
        assert args.command == "list-products"
        args = zentao_api.build_parser().parse_args(["get-product", "--id", "1"])
        assert args.command == "get-product"


# ===================================================================
# Error handling
# ===================================================================


class TestZentaoError:
    def test_error_message(self):
        err = zentao_api.ZentaoError("出错啦")
        assert "出错啦" in str(err)

    def test_error_with_status_code(self):
        err = zentao_api.ZentaoError("请求失败", status_code=500)
        assert "500" in str(err)

    def test_error_str_format(self):
        err = zentao_api.ZentaoError("失败", status_code=403, response_text="forbidden")
        assert "403" in str(err)


class TestPrintError:
    def test_print_error_with_status(self, capsys):
        err = ServiceError("请求失败", status_code=404)
        rc = zentao_api.print_error(err)
        captured = capsys.readouterr()
        assert captured.out == ""  # stdout 保持空，错误走 stderr
        payload = json.loads(captured.err)
        assert payload["error"]["message"] == "请求失败"
        assert payload["error"]["status_code"] == 404
        assert rc == 1

    def test_print_error_without_status(self, capsys):
        err = ServiceError("未知错误")
        rc = zentao_api.print_error(err)
        captured = capsys.readouterr()
        payload = json.loads(captured.err)
        assert payload["error"]["message"] == "未知错误"
        assert payload["error"]["status_code"] is None
        assert rc == 1

    def test_print_error_returns_1(self):
        rc = zentao_api.print_error(ServiceError("err"))
        assert rc == 1


# ===================================================================
# Output formatting
# ===================================================================


class TestPrintJsonResult:
    def test_prints_json_with_indent(self, capsys):
        target = zentao_api.ZentaoTarget(url="http://z.com", auth=None)
        rc = zentao_api.print_json_result(target, {"key": "value"}, "Result:")
        out = capsys.readouterr().out
        payload = json.loads(out)
        assert payload == {"system": None, "data": {"key": "value"}}
        assert "Result:" not in out  # heading 不再打印
        assert rc == 0

    def test_prints_heading(self, capsys):
        target = zentao_api.ZentaoTarget(url="http://z.com", auth=None, system_name="test")
        zentao_api.print_json_result(target, {}, "Heading:")
        out = capsys.readouterr().out
        payload = json.loads(out)
        assert payload == {"system": "test", "data": {}}
        assert "Heading:" not in out

    def test_prints_system_name(self, capsys):
        target = zentao_api.ZentaoTarget(url="http://z.com", auth=None, system_name="my-system")
        zentao_api.print_json_result(target, {})
        out = capsys.readouterr().out
        payload = json.loads(out)
        assert payload["system"] == "my-system"


# ===================================================================
# Additional coverage — appended for >=90% line coverage
# ===================================================================


class TestRequestJsonWithAuthErrors:
    def test_non_401_error_propagates(self):
        target = zentao_api.ZentaoTarget(url="http://z.com", auth=("a", "b"))
        with mock.patch.object(zentao_api, "get_token", return_value="t"):
            with mock.patch.object(zentao_api, "request_json") as rj:
                rj.side_effect = ServiceError("boom", status_code=500)
                with pytest.raises(ServiceError) as exc_info:
                    zentao_api.request_json_with_auth("GET", "http://z.com", "/bugs", target=target)
                assert exc_info.value.status_code == 500
            # No retry / force refresh for non-401
            assert rj.call_count == 1

    def test_401_with_force_token_does_not_retry(self):
        target = zentao_api.ZentaoTarget(url="http://z.com", auth=("a", "b"))
        with mock.patch.object(zentao_api, "get_token", return_value="t") as gt:
            with mock.patch.object(zentao_api, "request_json") as rj:
                rj.side_effect = ServiceError("expired", status_code=401)
                with pytest.raises(ServiceError):
                    zentao_api.request_json_with_auth(
                        "GET", "http://z.com", "/bugs", target=target, force_token=True
                    )
                assert rj.call_count == 1
            # force_token path calls get_token only once
            assert gt.call_count == 1

    def test_write_op_401_does_not_retry(self):
        """写操作(POST)遇 401 不自动重试，避免重复创建；直接抛 401 且不刷新 token。"""
        target = zentao_api.ZentaoTarget(url="http://z.com", auth=("a", "b"))
        with mock.patch.object(zentao_api, "get_token", return_value="t") as gt:
            with mock.patch.object(zentao_api, "request_json") as rj:
                rj.side_effect = ServiceError("expired", status_code=401)
                with pytest.raises(ServiceError) as exc_info:
                    zentao_api.request_json_with_auth(
                        "POST", "http://z.com", "/bugs", target=target, payload={"x": 1}
                    )
                assert exc_info.value.status_code == 401
                assert "重复创建" in exc_info.value.message
                # 写操作不重试：request_json 只调一次，get_token 不重新刷新
                assert rj.call_count == 1
            assert gt.call_count == 1


class TestCmdGetToken:
    def test_get_token_prints_token(self, capsys):
        with (
            _mock_target_patch(),
            mock.patch("zentao_api.get_token", return_value="abc123"),
        ):
            args = mock.MagicMock(force=True, zentao=None, system=None, user=None)
            rc = zentao_api.cmd_get_token(args)
            out = capsys.readouterr().out
            assert rc == 0
            assert "abc123" in out

    def test_get_token_force_false(self, capsys):
        with (
            _mock_target_patch(),
            mock.patch("zentao_api.get_token", return_value="tk") as gt,
        ):
            args = mock.MagicMock(force=False, zentao=None, system=None, user=None)
            zentao_api.cmd_get_token(args)
            gt.assert_called_once()
            assert gt.call_args.kwargs["force"] is False


class TestMain:
    def test_main_dispatches_to_handler(self):
        with mock.patch.object(zentao_api, "build_parser") as bp:
            args = mock.MagicMock()
            args.handler = mock.Mock(return_value=0)
            bp.return_value.parse_args.return_value = args
            assert zentao_api.main() == 0
            args.handler.assert_called_once_with(args)

    def test_main_handles_zentao_error(self):
        with mock.patch.object(zentao_api, "build_parser") as bp:
            args = mock.MagicMock()
            args.handler = mock.Mock(side_effect=ServiceError("boom", status_code=500))
            bp.return_value.parse_args.return_value = args
            assert zentao_api.main() == 1

    def test_main_handles_system_exit(self):
        with mock.patch.object(zentao_api, "build_parser") as bp:
            args = mock.MagicMock()
            args.handler = mock.Mock(side_effect=SystemExit(2))
            bp.return_value.parse_args.return_value = args
            assert zentao_api.main() == 2

    def test_main_handles_system_exit_none_code(self):
        with mock.patch.object(zentao_api, "build_parser") as bp:
            args = mock.MagicMock()
            args.handler = mock.Mock(side_effect=SystemExit())
            bp.return_value.parse_args.return_value = args
            assert zentao_api.main() == 0


# -- Bug command branch coverage ---------------------------------------------


class TestCmdBugBranches:
    def test_list_bugs_with_project_filter(self):
        with contextlib.ExitStack() as stack:
            _CmdMixin._enter_default(stack)
            rj = stack.enter_context(mock.patch("zentao_api.request_json_with_auth"))
            rj.return_value = {"status": "success"}
            args = mock.MagicMock(
                product=None, project=7, page=None, limit=None, zentao=None, system=None, user=None
            )
            zentao_api.cmd_list_bugs(args)
            _, kwargs = rj.call_args
            assert kwargs["params"]["project"] == 7

    def test_update_bug_all_fields(self):
        with contextlib.ExitStack() as stack:
            _CmdMixin._enter_write(stack)
            rj = stack.enter_context(mock.patch("zentao_api.request_json_with_auth"))
            rj.return_value = {"status": "success"}
            args = mock.MagicMock(
                id=1,
                title="t",
                severity=2,
                pri=3,
                type="codeerror",
                status="active",
                assigned_to="u",
                keywords="kw",
                zentao=None,
                system=None,
                user=None,
            )
            rc = zentao_api.cmd_update_bug(args)
            assert rc == 0
            _, kwargs = rj.call_args
            assert kwargs["payload"]["keywords"] == "kw"
            assert kwargs["payload"]["assignedTo"] == "u"

    def test_resolve_bug_with_build(self):
        with contextlib.ExitStack() as stack:
            _CmdMixin._enter_write(stack)
            rj = stack.enter_context(mock.patch("zentao_api.request_json_with_auth"))
            rj.return_value = {"status": "success"}
            args = mock.MagicMock(
                id=1, resolution="fixed", build=5, zentao=None, system=None, user=None
            )
            rc = zentao_api.cmd_resolve_bug(args)
            assert rc == 0
            _, kwargs = rj.call_args
            assert kwargs["payload"]["build"] == 5


# -- Task command full coverage ----------------------------------------------


class TestCmdTaskBranches:
    def test_list_tasks_by_assigned_to_and_status(self):
        with contextlib.ExitStack() as stack:
            _CmdMixin._enter_default(stack)
            rj = stack.enter_context(mock.patch("zentao_api.request_json_with_auth"))
            rj.return_value = {"status": "success"}
            args = mock.MagicMock(
                project=None,
                execution=None,
                assigned_to="dev1",
                status="doing",
                page=None,
                limit=None,
                zentao=None,
                system=None,
                user=None,
            )
            zentao_api.cmd_list_tasks(args)
            _, kwargs = rj.call_args
            assert kwargs["params"]["assignedTo"] == "dev1"
            assert kwargs["params"]["status"] == "doing"

    def test_list_tasks_with_limit(self):
        with contextlib.ExitStack() as stack:
            _CmdMixin._enter_default(stack)
            rj = stack.enter_context(mock.patch("zentao_api.request_json_with_auth"))
            rj.return_value = {"status": "success"}
            args = mock.MagicMock(
                project=None,
                execution=None,
                assigned_to=None,
                status=None,
                page=1,
                limit=50,
                zentao=None,
                system=None,
                user=None,
            )
            zentao_api.cmd_list_tasks(args)
            _, kwargs = rj.call_args
            assert kwargs["params"]["limit"] == 50

    def test_create_task_all_optional(self):
        with contextlib.ExitStack() as stack:
            _CmdMixin._enter_write(stack)
            rj = stack.enter_context(mock.patch("zentao_api.request_json_with_auth"))
            rj.return_value = {"status": "success"}
            args = mock.MagicMock(
                project=1,
                name="T",
                execution=2,
                assigned_to="u",
                estimate=4.0,
                type="devel",
                pri=2,
                desc="d",
                zentao=None,
                system=None,
                user=None,
            )
            zentao_api.cmd_create_task(args)
            _, kwargs = rj.call_args
            assert kwargs["payload"]["execution"] == 2
            assert kwargs["payload"]["estimate"] == 4.0
            assert kwargs["payload"]["pri"] == 2
            assert kwargs["payload"]["desc"] == "d"

    def test_update_task_all_fields(self):
        with contextlib.ExitStack() as stack:
            _CmdMixin._enter_write(stack)
            rj = stack.enter_context(mock.patch("zentao_api.request_json_with_auth"))
            rj.return_value = {"status": "success"}
            args = mock.MagicMock(
                id=1,
                name="n",
                assigned_to="u",
                estimate=1.0,
                consumed=2.0,
                left=3.0,
                status="doing",
                pri=1,
                type="devel",
                desc="d",
                zentao=None,
                system=None,
                user=None,
            )
            rc = zentao_api.cmd_update_task(args)
            assert rc == 0
            _, kwargs = rj.call_args
            payload = kwargs["payload"]
            assert payload["consumed"] == 2.0
            assert payload["left"] == 3.0
            assert payload["type"] == "devel"

    def test_close_task(self):
        with contextlib.ExitStack() as stack:
            _CmdMixin._enter_write(stack)
            rj = stack.enter_context(mock.patch("zentao_api.request_json_with_auth"))
            rj.return_value = {"status": "success"}
            args = mock.MagicMock(id=1, zentao=None, system=None, user=None)
            rc = zentao_api.cmd_close_task(args)
            assert rc == 0
            _, kwargs = rj.call_args
            assert kwargs["payload"]["status"] == "closed"

    def test_activate_task(self):
        with contextlib.ExitStack() as stack:
            _CmdMixin._enter_write(stack)
            rj = stack.enter_context(mock.patch("zentao_api.request_json_with_auth"))
            rj.return_value = {"status": "success"}
            args = mock.MagicMock(id=1, zentao=None, system=None, user=None)
            rc = zentao_api.cmd_activate_task(args)
            assert rc == 0
            _, kwargs = rj.call_args
            assert kwargs["payload"]["status"] == "wait"

    def test_delete_task_confirmed(self):
        with contextlib.ExitStack() as stack:
            _CmdMixin._enter_write(stack)
            rj = stack.enter_context(mock.patch("zentao_api.request_json_with_auth"))
            rj.return_value = {"status": "success"}
            args = mock.MagicMock(id=1, zentao=None, system=None, user=None)
            rc = zentao_api.cmd_delete_task(args)
            assert rc == 0


# -- Story command full coverage ---------------------------------------------


class TestCmdStoryBranches:
    def test_get_story(self):
        with contextlib.ExitStack() as stack:
            _CmdMixin._enter_default(stack)
            rj = stack.enter_context(mock.patch("zentao_api.request_json_with_auth"))
            rj.return_value = {"status": "success", "data": {"id": 1}}
            args = mock.MagicMock(id=1, zentao=None, system=None, user=None)
            rc = zentao_api.cmd_get_story(args)
            assert rc == 0

    def test_create_story_all_optional(self):
        with contextlib.ExitStack() as stack:
            _CmdMixin._enter_write(stack)
            rj = stack.enter_context(mock.patch("zentao_api.request_json_with_auth"))
            rj.return_value = {"status": "success"}
            args = mock.MagicMock(
                product=1,
                title="S",
                desc="d",
                pri=2,
                assigned_to="u",
                zentao=None,
                system=None,
                user=None,
            )
            zentao_api.cmd_create_story(args)
            _, kwargs = rj.call_args
            assert kwargs["payload"]["desc"] == "d"
            assert kwargs["payload"]["assignedTo"] == "u"

    def test_close_story(self):
        with contextlib.ExitStack() as stack:
            _CmdMixin._enter_write(stack)
            rj = stack.enter_context(mock.patch("zentao_api.request_json_with_auth"))
            rj.return_value = {"status": "success"}
            args = mock.MagicMock(id=1, zentao=None, system=None, user=None)
            rc = zentao_api.cmd_close_story(args)
            assert rc == 0
            _, kwargs = rj.call_args
            assert kwargs["payload"]["status"] == "closed"

    def test_activate_story(self):
        with contextlib.ExitStack() as stack:
            _CmdMixin._enter_write(stack)
            rj = stack.enter_context(mock.patch("zentao_api.request_json_with_auth"))
            rj.return_value = {"status": "success"}
            args = mock.MagicMock(id=1, zentao=None, system=None, user=None)
            rc = zentao_api.cmd_activate_story(args)
            assert rc == 0
            _, kwargs = rj.call_args
            assert kwargs["payload"]["status"] == "active"

    def test_delete_story_confirmed(self):
        with contextlib.ExitStack() as stack:
            _CmdMixin._enter_write(stack)
            rj = stack.enter_context(mock.patch("zentao_api.request_json_with_auth"))
            rj.return_value = {"status": "success"}
            args = mock.MagicMock(id=1, zentao=None, system=None, user=None)
            rc = zentao_api.cmd_delete_story(args)
            assert rc == 0


# -- Product commands --------------------------------------------------------


class TestCmdProducts:
    def test_list_products_pagination(self):
        with contextlib.ExitStack() as stack:
            _CmdMixin._enter_default(stack)
            rj = stack.enter_context(mock.patch("zentao_api.request_json_with_auth"))
            rj.return_value = {"status": "success"}
            args = mock.MagicMock(page=1, limit=10, zentao=None, system=None, user=None)
            zentao_api.cmd_list_products(args)
            _, kwargs = rj.call_args
            assert kwargs["params"]["page"] == 1

    def test_list_products_no_params(self):
        with contextlib.ExitStack() as stack:
            _CmdMixin._enter_default(stack)
            rj = stack.enter_context(mock.patch("zentao_api.request_json_with_auth"))
            rj.return_value = {"status": "success"}
            args = mock.MagicMock(page=None, limit=None, zentao=None, system=None, user=None)
            rc = zentao_api.cmd_list_products(args)
            assert rc == 0
            _, kwargs = rj.call_args
            assert kwargs["params"] is None

    def test_get_product(self):
        with contextlib.ExitStack() as stack:
            _CmdMixin._enter_default(stack)
            rj = stack.enter_context(mock.patch("zentao_api.request_json_with_auth"))
            rj.return_value = {"status": "success", "data": {"id": 1}}
            args = mock.MagicMock(id=1, zentao=None, system=None, user=None)
            rc = zentao_api.cmd_get_product(args)
            assert rc == 0


# -- Project commands --------------------------------------------------------


class TestCmdProjects:
    def test_list_projects_with_status(self):
        with contextlib.ExitStack() as stack:
            _CmdMixin._enter_default(stack)
            rj = stack.enter_context(mock.patch("zentao_api.request_json_with_auth"))
            rj.return_value = {"status": "success"}
            args = mock.MagicMock(
                page=None, limit=None, status="wait", zentao=None, system=None, user=None
            )
            zentao_api.cmd_list_projects(args)
            _, kwargs = rj.call_args
            assert kwargs["params"]["status"] == "wait"

    def test_list_projects_with_pagination(self):
        with contextlib.ExitStack() as stack:
            _CmdMixin._enter_default(stack)
            rj = stack.enter_context(mock.patch("zentao_api.request_json_with_auth"))
            rj.return_value = {"status": "success"}
            args = mock.MagicMock(
                page=2, limit=15, status=None, zentao=None, system=None, user=None
            )
            zentao_api.cmd_list_projects(args)
            _, kwargs = rj.call_args
            assert kwargs["params"]["page"] == 2
            assert kwargs["params"]["limit"] == 15

    def test_list_projects_no_params(self):
        with contextlib.ExitStack() as stack:
            _CmdMixin._enter_default(stack)
            rj = stack.enter_context(mock.patch("zentao_api.request_json_with_auth"))
            rj.return_value = {"status": "success"}
            args = mock.MagicMock(
                page=None, limit=None, status=None, zentao=None, system=None, user=None
            )
            rc = zentao_api.cmd_list_projects(args)
            assert rc == 0

    def test_get_project(self):
        with contextlib.ExitStack() as stack:
            _CmdMixin._enter_default(stack)
            rj = stack.enter_context(mock.patch("zentao_api.request_json_with_auth"))
            rj.return_value = {"status": "success"}
            args = mock.MagicMock(id=1, zentao=None, system=None, user=None)
            rc = zentao_api.cmd_get_project(args)
            assert rc == 0

    def test_create_project_all_fields(self):
        with contextlib.ExitStack() as stack:
            _CmdMixin._enter_write(stack)
            rj = stack.enter_context(mock.patch("zentao_api.request_json_with_auth"))
            rj.return_value = {"status": "success"}
            args = mock.MagicMock(
                name="P",
                code="c",
                begin="2026-01-01",
                end="2026-12-31",
                desc="d",
                pm="m",
                zentao=None,
                system=None,
                user=None,
            )
            rc = zentao_api.cmd_create_project(args)
            assert rc == 0
            _, kwargs = rj.call_args
            assert kwargs["payload"]["PM"] == "m"
            assert kwargs["payload"]["code"] == "c"

    def test_update_project_all_fields(self):
        with contextlib.ExitStack() as stack:
            _CmdMixin._enter_write(stack)
            rj = stack.enter_context(mock.patch("zentao_api.request_json_with_auth"))
            rj.return_value = {"status": "success"}
            args = mock.MagicMock(
                id=1,
                name="n",
                code="c",
                begin="b",
                end="e",
                desc="d",
                status="s",
                pm="p",
                zentao=None,
                system=None,
                user=None,
            )
            rc = zentao_api.cmd_update_project(args)
            assert rc == 0
            _, kwargs = rj.call_args
            assert kwargs["payload"]["PM"] == "p"

    def test_delete_project_confirmed(self):
        with contextlib.ExitStack() as stack:
            _CmdMixin._enter_write(stack)
            rj = stack.enter_context(mock.patch("zentao_api.request_json_with_auth"))
            rj.return_value = {"status": "success"}
            args = mock.MagicMock(id=1, zentao=None, system=None, user=None)
            rc = zentao_api.cmd_delete_project(args)
            assert rc == 0

    def test_delete_project_cancelled(self):
        with (
            _confirm_no(),
            mock.patch("zentao_api.request_json_with_auth") as rj,
        ):
            with pytest.raises(SystemExit):
                args = mock.MagicMock(id=1, zentao=None, system=None, user=None)
                zentao_api.cmd_delete_project(args)
            rj.assert_not_called()


# -- Execution commands ------------------------------------------------------


class TestCmdExecutions:
    def test_list_executions_with_project(self):
        with contextlib.ExitStack() as stack:
            _CmdMixin._enter_default(stack)
            rj = stack.enter_context(mock.patch("zentao_api.request_json_with_auth"))
            rj.return_value = {"status": "success"}
            args = mock.MagicMock(
                project=3, page=None, limit=None, zentao=None, system=None, user=None
            )
            zentao_api.cmd_list_executions(args)
            _, kwargs = rj.call_args
            assert kwargs["params"]["project"] == 3

    def test_list_executions_with_pagination(self):
        with contextlib.ExitStack() as stack:
            _CmdMixin._enter_default(stack)
            rj = stack.enter_context(mock.patch("zentao_api.request_json_with_auth"))
            rj.return_value = {"status": "success"}
            args = mock.MagicMock(
                project=None, page=3, limit=25, zentao=None, system=None, user=None
            )
            zentao_api.cmd_list_executions(args)
            _, kwargs = rj.call_args
            assert kwargs["params"]["page"] == 3

    def test_list_executions_no_params(self):
        with contextlib.ExitStack() as stack:
            _CmdMixin._enter_default(stack)
            rj = stack.enter_context(mock.patch("zentao_api.request_json_with_auth"))
            rj.return_value = {"status": "success"}
            args = mock.MagicMock(
                project=None, page=None, limit=None, zentao=None, system=None, user=None
            )
            rc = zentao_api.cmd_list_executions(args)
            assert rc == 0

    def test_get_execution(self):
        with contextlib.ExitStack() as stack:
            _CmdMixin._enter_default(stack)
            rj = stack.enter_context(mock.patch("zentao_api.request_json_with_auth"))
            rj.return_value = {"status": "success"}
            args = mock.MagicMock(id=1, zentao=None, system=None, user=None)
            rc = zentao_api.cmd_get_execution(args)
            assert rc == 0

    def test_create_execution_all_fields(self):
        with contextlib.ExitStack() as stack:
            _CmdMixin._enter_write(stack)
            rj = stack.enter_context(mock.patch("zentao_api.request_json_with_auth"))
            rj.return_value = {"status": "success"}
            args = mock.MagicMock(
                project=1,
                name="E",
                begin="b",
                end="e",
                desc="d",
                pm="p",
                zentao=None,
                system=None,
                user=None,
            )
            rc = zentao_api.cmd_create_execution(args)
            assert rc == 0
            _, kwargs = rj.call_args
            assert kwargs["payload"]["PM"] == "p"

    def test_update_execution_all_fields(self):
        with contextlib.ExitStack() as stack:
            _CmdMixin._enter_write(stack)
            rj = stack.enter_context(mock.patch("zentao_api.request_json_with_auth"))
            rj.return_value = {"status": "success"}
            args = mock.MagicMock(
                id=1,
                name="n",
                begin="b",
                end="e",
                desc="d",
                status="s",
                pm="p",
                zentao=None,
                system=None,
                user=None,
            )
            rc = zentao_api.cmd_update_execution(args)
            assert rc == 0
            _, kwargs = rj.call_args
            assert kwargs["payload"]["PM"] == "p"

    def test_delete_execution_confirmed(self):
        with contextlib.ExitStack() as stack:
            _CmdMixin._enter_write(stack)
            rj = stack.enter_context(mock.patch("zentao_api.request_json_with_auth"))
            rj.return_value = {"status": "success"}
            args = mock.MagicMock(id=1, zentao=None, system=None, user=None)
            rc = zentao_api.cmd_delete_execution(args)
            assert rc == 0


# -- Test case command full coverage -----------------------------------------


class TestCmdTestcaseBranches:
    def test_list_testcases_by_project_and_pagination(self):
        with contextlib.ExitStack() as stack:
            _CmdMixin._enter_default(stack)
            rj = stack.enter_context(mock.patch("zentao_api.request_json_with_auth"))
            rj.return_value = {"status": "success"}
            args = mock.MagicMock(
                product=None,
                project=2,
                execution=None,
                page=1,
                limit=5,
                zentao=None,
                system=None,
                user=None,
            )
            zentao_api.cmd_list_testcases(args)
            _, kwargs = rj.call_args
            assert kwargs["params"]["project"] == 2
            assert kwargs["params"]["limit"] == 5

    def test_list_testcases_no_params(self):
        with contextlib.ExitStack() as stack:
            _CmdMixin._enter_default(stack)
            rj = stack.enter_context(mock.patch("zentao_api.request_json_with_auth"))
            rj.return_value = {"status": "success"}
            args = mock.MagicMock(
                product=None,
                project=None,
                execution=None,
                page=None,
                limit=None,
                zentao=None,
                system=None,
                user=None,
            )
            rc = zentao_api.cmd_list_testcases(args)
            assert rc == 0

    def test_create_testcase_all_fields(self):
        with contextlib.ExitStack() as stack:
            _CmdMixin._enter_write(stack)
            rj = stack.enter_context(mock.patch("zentao_api.request_json_with_auth"))
            rj.return_value = {"status": "success"}
            args = mock.MagicMock(
                product=1,
                title="TC",
                type="unit",
                stage="ut",
                pri=1,
                precondition="pre",
                steps="[]",
                zentao=None,
                system=None,
                user=None,
            )
            zentao_api.cmd_create_testcase(args)
            _, kwargs = rj.call_args
            payload = kwargs["payload"]
            assert payload["type"] == "unit"
            assert payload["stage"] == "ut"
            assert payload["precondition"] == "pre"
            assert payload["steps"] == "[]"

    def test_update_testcase_all_fields(self):
        with contextlib.ExitStack() as stack:
            _CmdMixin._enter_write(stack)
            rj = stack.enter_context(mock.patch("zentao_api.request_json_with_auth"))
            rj.return_value = {"status": "success"}
            args = mock.MagicMock(
                id=1,
                title="t",
                type="unit",
                stage="ut",
                pri=1,
                precondition="pre",
                steps="[]",
                status="normal",
                zentao=None,
                system=None,
                user=None,
            )
            rc = zentao_api.cmd_update_testcase(args)
            assert rc == 0
            _, kwargs = rj.call_args
            assert kwargs["payload"]["status"] == "normal"

    def test_delete_testcase_confirmed(self):
        with contextlib.ExitStack() as stack:
            _CmdMixin._enter_write(stack)
            rj = stack.enter_context(mock.patch("zentao_api.request_json_with_auth"))
            rj.return_value = {"status": "success"}
            args = mock.MagicMock(id=1, zentao=None, system=None, user=None)
            rc = zentao_api.cmd_delete_testcase(args)
            assert rc == 0


# -- Test task command full coverage -----------------------------------------


class TestCmdTesttaskBranches:
    def test_list_testtasks_with_filters(self):
        with contextlib.ExitStack() as stack:
            _CmdMixin._enter_default(stack)
            rj = stack.enter_context(mock.patch("zentao_api.request_json_with_auth"))
            rj.return_value = {"status": "success"}
            args = mock.MagicMock(
                product=1,
                project=2,
                execution=3,
                page=1,
                limit=5,
                zentao=None,
                system=None,
                user=None,
            )
            zentao_api.cmd_list_testtasks(args)
            _, kwargs = rj.call_args
            assert kwargs["params"]["product"] == 1
            assert kwargs["params"]["execution"] == 3

    def test_list_testtasks_no_params(self):
        with contextlib.ExitStack() as stack:
            _CmdMixin._enter_default(stack)
            rj = stack.enter_context(mock.patch("zentao_api.request_json_with_auth"))
            rj.return_value = {"status": "success"}
            args = mock.MagicMock(
                product=None,
                project=None,
                execution=None,
                page=None,
                limit=None,
                zentao=None,
                system=None,
                user=None,
            )
            rc = zentao_api.cmd_list_testtasks(args)
            assert rc == 0

    def test_get_testtask(self):
        with contextlib.ExitStack() as stack:
            _CmdMixin._enter_default(stack)
            rj = stack.enter_context(mock.patch("zentao_api.request_json_with_auth"))
            rj.return_value = {"status": "success"}
            args = mock.MagicMock(id=1, zentao=None, system=None, user=None)
            rc = zentao_api.cmd_get_testtask(args)
            assert rc == 0

    def test_create_testtask_all_fields(self):
        with contextlib.ExitStack() as stack:
            _CmdMixin._enter_write(stack)
            rj = stack.enter_context(mock.patch("zentao_api.request_json_with_auth"))
            rj.return_value = {"status": "success"}
            args = mock.MagicMock(
                product=1,
                name="TT",
                project=2,
                execution=3,
                begin="b",
                end="e",
                desc="d",
                zentao=None,
                system=None,
                user=None,
            )
            rc = zentao_api.cmd_create_testtask(args)
            assert rc == 0
            _, kwargs = rj.call_args
            assert kwargs["payload"]["execution"] == 3

    def test_update_testtask_all_fields(self):
        with contextlib.ExitStack() as stack:
            _CmdMixin._enter_write(stack)
            rj = stack.enter_context(mock.patch("zentao_api.request_json_with_auth"))
            rj.return_value = {"status": "success"}
            args = mock.MagicMock(
                id=1,
                name="n",
                begin="b",
                end="e",
                desc="d",
                status="s",
                zentao=None,
                system=None,
                user=None,
            )
            rc = zentao_api.cmd_update_testtask(args)
            assert rc == 0
            _, kwargs = rj.call_args
            assert kwargs["payload"]["status"] == "s"

    def test_delete_testtask_confirmed(self):
        with contextlib.ExitStack() as stack:
            _CmdMixin._enter_write(stack)
            rj = stack.enter_context(mock.patch("zentao_api.request_json_with_auth"))
            rj.return_value = {"status": "success"}
            args = mock.MagicMock(id=1, zentao=None, system=None, user=None)
            rc = zentao_api.cmd_delete_testtask(args)
            assert rc == 0


# -- User & department commands ----------------------------------------------


class TestCmdUsers:
    def test_list_users_with_dept_and_pagination(self):
        with contextlib.ExitStack() as stack:
            _CmdMixin._enter_default(stack)
            rj = stack.enter_context(mock.patch("zentao_api.request_json_with_auth"))
            rj.return_value = {"status": "success"}
            args = mock.MagicMock(page=1, limit=20, dept=5, zentao=None, system=None, user=None)
            zentao_api.cmd_list_users(args)
            _, kwargs = rj.call_args
            assert kwargs["params"]["dept"] == 5

    def test_list_users_no_params(self):
        with contextlib.ExitStack() as stack:
            _CmdMixin._enter_default(stack)
            rj = stack.enter_context(mock.patch("zentao_api.request_json_with_auth"))
            rj.return_value = {"status": "success"}
            args = mock.MagicMock(
                page=None, limit=None, dept=None, zentao=None, system=None, user=None
            )
            rc = zentao_api.cmd_list_users(args)
            assert rc == 0

    def test_get_user(self):
        with contextlib.ExitStack() as stack:
            _CmdMixin._enter_default(stack)
            rj = stack.enter_context(mock.patch("zentao_api.request_json_with_auth"))
            rj.return_value = {"status": "success"}
            args = mock.MagicMock(id=1, zentao=None, system=None, user=None)
            rc = zentao_api.cmd_get_user(args)
            assert rc == 0

    def test_create_user_all_fields(self):
        with contextlib.ExitStack() as stack:
            _CmdMixin._enter_write(stack)
            rj = stack.enter_context(mock.patch("zentao_api.request_json_with_auth"))
            rj.return_value = {"status": "success"}
            args = mock.MagicMock(
                account="acc",
                realname="rn",
                password="pw",
                email="e@x.com",
                phone="123",
                dept=1,
                role="dev",
                zentao=None,
                system=None,
                user=None,
            )
            rc = zentao_api.cmd_create_user(args)
            assert rc == 0
            _, kwargs = rj.call_args
            payload = kwargs["payload"]
            assert payload["email"] == "e@x.com"
            assert payload["dept"] == 1
            assert payload["role"] == "dev"


class TestCmdDepartments:
    def test_list_departments_pagination(self):
        with contextlib.ExitStack() as stack:
            _CmdMixin._enter_default(stack)
            rj = stack.enter_context(mock.patch("zentao_api.request_json_with_auth"))
            rj.return_value = {"status": "success"}
            args = mock.MagicMock(page=1, limit=10, zentao=None, system=None, user=None)
            zentao_api.cmd_list_departments(args)
            _, kwargs = rj.call_args
            assert kwargs["params"]["page"] == 1

    def test_list_departments_no_params(self):
        with contextlib.ExitStack() as stack:
            _CmdMixin._enter_default(stack)
            rj = stack.enter_context(mock.patch("zentao_api.request_json_with_auth"))
            rj.return_value = {"status": "success"}
            args = mock.MagicMock(page=None, limit=None, zentao=None, system=None, user=None)
            rc = zentao_api.cmd_list_departments(args)
            assert rc == 0


# -- Release commands --------------------------------------------------------


class TestCmdReleases:
    def test_list_releases_with_product(self):
        with contextlib.ExitStack() as stack:
            _CmdMixin._enter_default(stack)
            rj = stack.enter_context(mock.patch("zentao_api.request_json_with_auth"))
            rj.return_value = {"status": "success"}
            args = mock.MagicMock(
                product=1, page=None, limit=None, zentao=None, system=None, user=None
            )
            zentao_api.cmd_list_releases(args)
            _, kwargs = rj.call_args
            assert kwargs["params"]["product"] == 1

    def test_list_releases_with_pagination(self):
        with contextlib.ExitStack() as stack:
            _CmdMixin._enter_default(stack)
            rj = stack.enter_context(mock.patch("zentao_api.request_json_with_auth"))
            rj.return_value = {"status": "success"}
            args = mock.MagicMock(
                product=None, page=1, limit=10, zentao=None, system=None, user=None
            )
            zentao_api.cmd_list_releases(args)
            _, kwargs = rj.call_args
            assert kwargs["params"]["page"] == 1
            assert kwargs["params"]["limit"] == 10

    def test_list_releases_no_params(self):
        with contextlib.ExitStack() as stack:
            _CmdMixin._enter_default(stack)
            rj = stack.enter_context(mock.patch("zentao_api.request_json_with_auth"))
            rj.return_value = {"status": "success"}
            args = mock.MagicMock(
                product=None, page=None, limit=None, zentao=None, system=None, user=None
            )
            rc = zentao_api.cmd_list_releases(args)
            assert rc == 0

    def test_get_release(self):
        with contextlib.ExitStack() as stack:
            _CmdMixin._enter_default(stack)
            rj = stack.enter_context(mock.patch("zentao_api.request_json_with_auth"))
            rj.return_value = {"status": "success"}
            args = mock.MagicMock(id=1, zentao=None, system=None, user=None)
            rc = zentao_api.cmd_get_release(args)
            assert rc == 0

    def test_create_release_all_fields(self):
        with contextlib.ExitStack() as stack:
            _CmdMixin._enter_write(stack)
            rj = stack.enter_context(mock.patch("zentao_api.request_json_with_auth"))
            rj.return_value = {"status": "success"}
            args = mock.MagicMock(
                product=1,
                name="R",
                build=2,
                date="2026-01-01",
                desc="d",
                zentao=None,
                system=None,
                user=None,
            )
            rc = zentao_api.cmd_create_release(args)
            assert rc == 0
            _, kwargs = rj.call_args
            assert kwargs["payload"]["build"] == 2
            assert kwargs["payload"]["date"] == "2026-01-01"

    def test_update_release_all_fields(self):
        with contextlib.ExitStack() as stack:
            _CmdMixin._enter_write(stack)
            rj = stack.enter_context(mock.patch("zentao_api.request_json_with_auth"))
            rj.return_value = {"status": "success"}
            args = mock.MagicMock(
                id=1,
                name="n",
                build=2,
                date="d",
                desc="desc",
                status="s",
                zentao=None,
                system=None,
                user=None,
            )
            rc = zentao_api.cmd_update_release(args)
            assert rc == 0
            _, kwargs = rj.call_args
            assert kwargs["payload"]["build"] == 2

    def test_delete_release_confirmed(self):
        with contextlib.ExitStack() as stack:
            _CmdMixin._enter_write(stack)
            rj = stack.enter_context(mock.patch("zentao_api.request_json_with_auth"))
            rj.return_value = {"status": "success"}
            args = mock.MagicMock(id=1, zentao=None, system=None, user=None)
            rc = zentao_api.cmd_delete_release(args)
            assert rc == 0


# -- Build commands ----------------------------------------------------------


class TestCmdBuilds:
    def test_list_builds_with_product(self):
        with contextlib.ExitStack() as stack:
            _CmdMixin._enter_default(stack)
            rj = stack.enter_context(mock.patch("zentao_api.request_json_with_auth"))
            rj.return_value = {"status": "success"}
            args = mock.MagicMock(
                product=1, page=None, limit=None, zentao=None, system=None, user=None
            )
            zentao_api.cmd_list_builds(args)
            _, kwargs = rj.call_args
            assert kwargs["params"]["product"] == 1

    def test_list_builds_with_pagination(self):
        with contextlib.ExitStack() as stack:
            _CmdMixin._enter_default(stack)
            rj = stack.enter_context(mock.patch("zentao_api.request_json_with_auth"))
            rj.return_value = {"status": "success"}
            args = mock.MagicMock(
                product=None, page=1, limit=10, zentao=None, system=None, user=None
            )
            zentao_api.cmd_list_builds(args)
            _, kwargs = rj.call_args
            assert kwargs["params"]["page"] == 1
            assert kwargs["params"]["limit"] == 10

    def test_list_builds_no_params(self):
        with contextlib.ExitStack() as stack:
            _CmdMixin._enter_default(stack)
            rj = stack.enter_context(mock.patch("zentao_api.request_json_with_auth"))
            rj.return_value = {"status": "success"}
            args = mock.MagicMock(
                product=None, page=None, limit=None, zentao=None, system=None, user=None
            )
            rc = zentao_api.cmd_list_builds(args)
            assert rc == 0

    def test_get_build(self):
        with contextlib.ExitStack() as stack:
            _CmdMixin._enter_default(stack)
            rj = stack.enter_context(mock.patch("zentao_api.request_json_with_auth"))
            rj.return_value = {"status": "success"}
            args = mock.MagicMock(id=1, zentao=None, system=None, user=None)
            rc = zentao_api.cmd_get_build(args)
            assert rc == 0

    def test_create_build_all_fields(self):
        with contextlib.ExitStack() as stack:
            _CmdMixin._enter_write(stack)
            rj = stack.enter_context(mock.patch("zentao_api.request_json_with_auth"))
            rj.return_value = {"status": "success"}
            args = mock.MagicMock(
                product=1,
                name="B",
                project=2,
                builder="me",
                date="2026-01-01",
                desc="d",
                zentao=None,
                system=None,
                user=None,
            )
            rc = zentao_api.cmd_create_build(args)
            assert rc == 0
            _, kwargs = rj.call_args
            assert kwargs["payload"]["builder"] == "me"
            assert kwargs["payload"]["project"] == 2
