#!/usr/bin/env python3
"""Gerrit REST API single-entry script."""

import argparse
import base64
import json
from typing import Any, Callable
from urllib import error, parse, request

from system_config import (
    ServiceError,
    ServiceTarget,
    resolve_target,
    print_system,
    print_json_result,
)

GerritError = ServiceError
GerritTarget = ServiceTarget

XSSI_PREFIX = ")]}'"


def strip_xssi_prefix(text: str) -> str:
    if text.startswith(XSSI_PREFIX):
        return text[len(XSSI_PREFIX) :]
    return text


def encode_change_id(change_id: str) -> str:
    return parse.quote(change_id, safe="").replace("~", "%7E")


def encode_path_id(value: str) -> str:
    return parse.quote(value, safe="")


def build_url(
    gerrit_url: str,
    path: str,
    *,
    auth: tuple[str, str] | None = None,
    force_auth_prefix: bool = False,
    params: dict[str, Any] | None = None,
) -> str:
    prefix = "/a" if (auth is not None or force_auth_prefix) else ""
    url = f"{gerrit_url}{prefix}{path}"
    if params:
        query = parse.urlencode(params, doseq=True)
        url = f"{url}?{query}"
    return url


def request_json(
    method: str,
    gerrit_url: str,
    path: str,
    *,
    auth: tuple[str, str] | None = None,
    force_auth_prefix: bool = False,
    params: dict[str, Any] | None = None,
    payload: dict[str, Any] | None = None,
) -> Any:
    url = build_url(
        gerrit_url,
        path,
        auth=auth,
        force_auth_prefix=force_auth_prefix,
        params=params,
    )
    headers = {"Accept": "application/json"}
    data = None

    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json; charset=utf-8"

    if auth is not None:
        token = base64.b64encode(f"{auth[0]}:{auth[1]}".encode("utf-8")).decode("ascii")
        headers["Authorization"] = f"Basic {token}"

    req = request.Request(url, data=data, headers=headers, method=method.upper())

    try:
        with request.urlopen(req) as resp:
            body = resp.read().decode("utf-8")
    except error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise GerritError("请求失败", status_code=exc.code, response_text=body) from exc
    except error.URLError as exc:
        raise GerritError(f"网络错误: {exc.reason}") from exc

    body = strip_xssi_prefix(body).strip()
    if not body:
        return None

    try:
        return json.loads(body)
    except json.JSONDecodeError as exc:
        raise GerritError("响应不是合法 JSON", response_text=body) from exc


def print_error(err: ServiceError) -> int:
    print(f"错误: {err}")
    if err.response_text:
        print(strip_xssi_prefix(err.response_text).strip())
    return 1


def add_common_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--gerrit", help="显式指定 Gerrit 地址")
    parser.add_argument("--system", help="配置文件中的 Gerrit 系统名；未提供时使用默认系统")
    parser.add_argument("--user", help="认证信息，格式为 username:password")


def add_range_args(parser: argparse.ArgumentParser, *, limit_name: str = "--limit", start_name: str = "--start") -> None:
    parser.add_argument(limit_name, type=int, help="返回结果数量限制")
    parser.add_argument(start_name, type=int, help="起始偏移")


def add_change_options_arg(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--option",
        action="append",
        default=[],
        help="重复传入 Gerrit ChangeInfo 的 o 参数，例如 CURRENT_REVISION、MESSAGES、ALL_REVISIONS",
    )


def _target(args: argparse.Namespace) -> GerritTarget:
    return resolve_target(
        args.gerrit if hasattr(args, "gerrit") else None,
        args.user if hasattr(args, "user") else None,
        args.system if hasattr(args, "system") else None,
        config_name="gerrit.json",
        password_key="http_password",
    )


def cmd_query_changes(args: argparse.Namespace) -> int:
    target = _target(args)
    changes = request_json(
        "GET",
        target.url,
        "/changes/",
        auth=target.auth,
        params={"q": args.query, "n": args.limit},
    )

    if not changes:
        print("没有找到匹配的变更")
        return 0

    print_system(target)
    print(f"找到 {len(changes)} 个变更:\n")
    for change in changes:
        wip = "[WIP] " if change.get("work_in_progress") else ""
        print(f"- {change['_number']}: {wip}{change['subject']}")
    return 0


def cmd_get_change_details(args: argparse.Namespace) -> int:
    target = _target(args)
    details = request_json(
        "GET",
        target.url,
        f"/changes/{encode_change_id(args.change_id)}/detail",
        auth=target.auth,
        params={"o": ["CURRENT_REVISION", "CURRENT_COMMIT", "DETAILED_LABELS"]},
    )

    print_system(target)
    print(f"变更详情 - {details['_number']}:\n")
    print(f"主题: {details['subject']}")
    print(f"状态: {details['status']}")
    print(f"项目: {details.get('project', 'N/A')}")
    print(f"分支: {details.get('branch', 'N/A')}")

    owner = details.get("owner", {})
    owner_name = owner.get("email") or owner.get("name") or owner.get("username") or "N/A"
    print(f"所有者: {owner_name}")

    reviewers = details.get("reviewers", {}).get("REVIEWER", [])
    if reviewers:
        print("\n审阅者:")
        for reviewer in reviewers:
            name = reviewer.get("email") or reviewer.get("name") or reviewer.get("username") or "N/A"
            print(f"  - {name}")

    labels = details.get("labels", {})
    if labels:
        print("\n标签投票:")
        for label, info in labels.items():
            approved = info.get("approved", {})
            rejected = info.get("rejected", {})
            summary = approved.get("name") or rejected.get("name") or "无汇总"
            print(f"  - {label}: {summary}")

    messages = details.get("messages", [])
    if messages:
        print("\n最近消息:")
        for msg in messages[-3:]:
            author = msg.get("author", {}).get("name", "Gerrit")
            timestamp = msg.get("date", "无日期")
            first_line = msg.get("message", "").splitlines()[0] if msg.get("message") else ""
            print(f"  - [{timestamp}] ({author}): {first_line}")
    return 0


def cmd_get_change(args: argparse.Namespace) -> int:
    target = _target(args)
    params = {"o": args.option} if args.option else None
    result = request_json(
        "GET",
        target.url,
        f"/changes/{encode_change_id(args.change_id)}",
        auth=target.auth,
        params=params,
    )
    return print_json_result(target, result, "变更详情:")


def cmd_list_reviewers(args: argparse.Namespace) -> int:
    target = _target(args)
    result = request_json(
        "GET",
        target.url,
        f"/changes/{encode_change_id(args.change_id)}/reviewers/",
        auth=target.auth,
    )
    return print_json_result(target, result, "审阅者列表:")


def cmd_list_revisions(args: argparse.Namespace) -> int:
    target = _target(args)
    options = ["ALL_REVISIONS"] + list(args.option or [])
    result = request_json(
        "GET",
        target.url,
        f"/changes/{encode_change_id(args.change_id)}",
        auth=target.auth,
        params={"o": options},
    )
    revisions = result.get("revisions", {}) if isinstance(result, dict) else {}
    return print_json_result(target, revisions, "Patch Set 列表:")


def cmd_get_revision(args: argparse.Namespace) -> int:
    target = _target(args)
    options = ["ALL_REVISIONS"] + list(args.option or [])
    result = request_json(
        "GET",
        target.url,
        f"/changes/{encode_change_id(args.change_id)}",
        auth=target.auth,
        params={"o": options},
    )
    revisions = result.get("revisions", {}) if isinstance(result, dict) else {}
    revision = revisions.get(args.revision_id)

    if revision is None and args.revision_id == "current":
        current_revision = result.get("current_revision") if isinstance(result, dict) else None
        if current_revision:
            revision = revisions.get(current_revision)

    if revision is None:
        raise GerritError(f"未找到 revision: {args.revision_id}")
    return print_json_result(target, revision, "Patch Set 详情:")


def cmd_add_reviewer(args: argparse.Namespace) -> int:
    target = _target(args)
    auth = target.auth
    result = request_json(
        "POST",
        target.url,
        f"/changes/{encode_change_id(args.change_id)}/reviewers",
        auth=auth,
        force_auth_prefix=True,
        payload={"reviewer": args.reviewer, "state": args.state},
    )
    reviewer = result.get("reviewer", {}).get("email") if isinstance(result, dict) else None
    print_system(target)
    print(f"成功添加 {reviewer or args.reviewer} 为 {args.state}")
    return 0


def cmd_list_projects(args: argparse.Namespace) -> int:
    target = _target(args)
    params: dict[str, Any] = {}

    if args.query:
        params["query"] = args.query
        if args.limit is not None:
            params["limit"] = args.limit
        if args.start is not None:
            params["start"] = args.start
    else:
        if args.limit is not None:
            params["n"] = args.limit
        if args.start is not None:
            params["S"] = args.start
        if args.branch:
            params["b"] = args.branch
        if args.prefix:
            params["p"] = args.prefix
        if args.regex:
            params["r"] = args.regex
        if args.match:
            params["m"] = args.match
        if args.description:
            params["d"] = True
        if args.tree:
            params["t"] = True
        if args.project_type:
            params["type"] = args.project_type
        if args.state:
            params["state"] = args.state
        if args.all_projects:
            params["all"] = True

    result = request_json("GET", target.url, "/projects/", auth=target.auth, params=params or None)
    return print_json_result(target, result, "项目列表:")


def cmd_get_project(args: argparse.Namespace) -> int:
    target = _target(args)
    result = request_json(
        "GET",
        target.url,
        f"/projects/{encode_path_id(args.project_name)}",
        auth=target.auth,
    )
    return print_json_result(target, result, "项目详情:")


def cmd_list_branches(args: argparse.Namespace) -> int:
    target = _target(args)
    params: dict[str, Any] = {}
    if args.limit is not None:
        params["n"] = args.limit
    if args.start is not None:
        params["s"] = args.start
    if args.match:
        params["m"] = args.match
    if args.regex:
        params["r"] = args.regex

    result = request_json(
        "GET",
        target.url,
        f"/projects/{encode_path_id(args.project_name)}/branches/",
        auth=target.auth,
        params=params or None,
    )
    return print_json_result(target, result, "分支列表:")


def cmd_get_branch(args: argparse.Namespace) -> int:
    target = _target(args)
    result = request_json(
        "GET",
        target.url,
        f"/projects/{encode_path_id(args.project_name)}/branches/{encode_path_id(args.branch_id)}",
        auth=target.auth,
    )
    return print_json_result(target, result, "分支详情:")


def cmd_query_accounts(args: argparse.Namespace) -> int:
    target = _target(args)
    params: dict[str, Any] = {"q": args.query}
    if args.limit is not None:
        params["n"] = args.limit
    if args.start is not None:
        params["S"] = args.start
    if args.suggest:
        params["suggest"] = True
    options: list[str] = []
    if args.details:
        options.append("DETAILS")
    if args.all_emails:
        options.append("ALL_EMAILS")
    if options:
        params["o"] = options

    result = request_json("GET", target.url, "/accounts/", auth=target.auth, params=params)
    return print_json_result(target, result, "账号列表:")


def cmd_get_account(args: argparse.Namespace) -> int:
    target = _target(args)
    result = request_json(
        "GET",
        target.url,
        f"/accounts/{encode_path_id(args.account_id)}",
        auth=target.auth,
    )
    return print_json_result(target, result, "账号详情:")


def cmd_get_account_detail(args: argparse.Namespace) -> int:
    target = _target(args)
    result = request_json(
        "GET",
        target.url,
        f"/accounts/{encode_path_id(args.account_id)}/detail",
        auth=target.auth,
    )
    return print_json_result(target, result, "账号详细信息:")


def cmd_list_groups(args: argparse.Namespace) -> int:
    target = _target(args)
    params: dict[str, Any] = {}

    if args.query:
        params["query"] = args.query
        if args.limit is not None:
            params["limit"] = args.limit
        if args.start is not None:
            params["start"] = args.start
    else:
        if args.limit is not None:
            params["n"] = args.limit
        if args.start is not None:
            params["S"] = args.start
        if args.owned_by:
            params["owned-by"] = args.owned_by
        if args.owned:
            params["owned"] = True
        if args.group:
            params["g"] = args.group
        if args.suggest:
            params["suggest"] = args.suggest
        if args.project:
            params["p"] = args.project
        if args.match:
            params["m"] = args.match
        if args.regex:
            params["r"] = args.regex

    options: list[str] = []
    if args.includes:
        options.append("INCLUDES")
    if args.members:
        options.append("MEMBERS")
    if options:
        params["o"] = options

    result = request_json("GET", target.url, "/groups/", auth=target.auth, params=params or None)
    return print_json_result(target, result, "用户组列表:")


def cmd_get_group(args: argparse.Namespace) -> int:
    target = _target(args)
    result = request_json(
        "GET",
        target.url,
        f"/groups/{encode_path_id(args.group_id)}",
        auth=target.auth,
    )
    return print_json_result(target, result, "用户组详情:")


def cmd_list_group_members(args: argparse.Namespace) -> int:
    target = _target(args)
    params = {"recursive": True} if args.recursive else None
    result = request_json(
        "GET",
        target.url,
        f"/groups/{encode_path_id(args.group_id)}/members/",
        auth=target.auth,
        params=params,
    )
    return print_json_result(target, result, "用户组成员:")


def cmd_list_change_messages(args: argparse.Namespace) -> int:
    target = _target(args)
    result = request_json(
        "GET",
        target.url,
        f"/changes/{encode_change_id(args.change_id)}/messages/",
        auth=target.auth,
    )
    return print_json_result(target, result, "变更消息列表:")


def cmd_get_topic(args: argparse.Namespace) -> int:
    target = _target(args)
    result = request_json(
        "GET",
        target.url,
        f"/changes/{encode_change_id(args.change_id)}/topic",
        auth=target.auth,
    )
    return print_json_result(target, result, "变更 Topic:")


def cmd_list_files(args: argparse.Namespace) -> int:
    target = _target(args)
    selected = [bool(args.reviewed), bool(args.query), args.parent is not None, args.base is not None]
    if sum(selected) > 1:
        raise GerritError("--reviewed、--query、--parent、--base 互斥，只能传一个")

    params: dict[str, Any] = {}
    if args.reviewed:
        params["reviewed"] = True
    if args.query:
        params["q"] = args.query
    if args.parent is not None:
        params["parent"] = args.parent
    if args.base is not None:
        params["base"] = args.base

    result = request_json(
        "GET",
        target.url,
        f"/changes/{encode_change_id(args.change_id)}/revisions/{encode_path_id(args.revision_id)}/files/",
        auth=target.auth,
        params=params or None,
    )
    return print_json_result(target, result, "文件列表:")


def cmd_post_review(args: argparse.Namespace) -> int:
    target = _target(args)
    auth = target.auth
    request_json(
        "POST",
        target.url,
        f"/changes/{encode_change_id(args.change_id)}/revisions/{encode_path_id(args.revision)}/review",
        auth=auth,
        force_auth_prefix=True,
        payload={"message": args.message},
    )
    print_system(target)
    print("审查已发布")
    return 0


def cmd_create_change(args: argparse.Namespace) -> int:
    target = _target(args)
    auth = target.auth
    result = request_json(
        "POST",
        target.url,
        "/changes/",
        auth=auth,
        force_auth_prefix=True,
        payload={"project": args.project, "branch": args.branch, "subject": args.subject},
    )
    change_id = result.get("id") if isinstance(result, dict) else None
    print_system(target)
    print(f"创建成功: {change_id or args.subject}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Gerrit REST API 单入口脚本")
    subparsers = parser.add_subparsers(dest="command", required=True)

    query_changes = subparsers.add_parser("query-changes", help="查询 Gerrit 变更列表")
    add_common_args(query_changes)
    query_changes.add_argument("--query", required=True, help="查询字符串")
    query_changes.add_argument("--limit", type=int, default=25, help="返回结果数量限制")
    query_changes.set_defaults(handler=cmd_query_changes)

    get_change_details = subparsers.add_parser("get-change-details", help="获取 Gerrit 变更详情")
    add_common_args(get_change_details)
    get_change_details.add_argument("--change-id", required=True, help="变更 ID，格式为 project~branch~Change-Id")
    get_change_details.set_defaults(handler=cmd_get_change_details)

    get_change = subparsers.add_parser("get-change", help="获取变更基础详情")
    add_common_args(get_change)
    get_change.add_argument("--change-id", required=True, help="变更 ID，格式为 project~branch~Change-Id")
    add_change_options_arg(get_change)
    get_change.set_defaults(handler=cmd_get_change)

    list_reviewers = subparsers.add_parser("list-reviewers", help="列出变更审阅者")
    add_common_args(list_reviewers)
    list_reviewers.add_argument("--change-id", required=True, help="变更 ID，格式为 project~branch~Change-Id")
    list_reviewers.set_defaults(handler=cmd_list_reviewers)

    list_revisions = subparsers.add_parser("list-revisions", help="列出变更的所有 patch set")
    add_common_args(list_revisions)
    list_revisions.add_argument("--change-id", required=True, help="变更 ID，格式为 project~branch~Change-Id")
    add_change_options_arg(list_revisions)
    list_revisions.set_defaults(handler=cmd_list_revisions)

    get_revision = subparsers.add_parser("get-revision", help="获取单个 patch set 详情")
    add_common_args(get_revision)
    get_revision.add_argument("--change-id", required=True, help="变更 ID，格式为 project~branch~Change-Id")
    get_revision.add_argument("--revision-id", required=True, help="revision SHA、patch set 编号对应 SHA，或 current")
    add_change_options_arg(get_revision)
    get_revision.set_defaults(handler=cmd_get_revision)

    list_projects = subparsers.add_parser("list-projects", help="列出 Gerrit 项目")
    add_common_args(list_projects)
    list_projects.add_argument("--query", help="项目查询语句")
    list_projects.add_argument("--prefix", help="按项目前缀筛选")
    list_projects.add_argument("--regex", help="按正则筛选项目")
    list_projects.add_argument("--match", help="按子串筛选项目")
    list_projects.add_argument("--branch", help="仅返回包含该分支的项目")
    list_projects.add_argument("--description", action="store_true", help="返回项目描述")
    list_projects.add_argument("--tree", action="store_true", help="返回项目继承树信息")
    list_projects.add_argument("--project-type", choices=["ALL", "CODE", "PERMISSIONS"], help="项目类型筛选")
    list_projects.add_argument("--state", help="按项目状态筛选")
    list_projects.add_argument("--all-projects", action="store_true", help="包含隐藏项目")
    add_range_args(list_projects)
    list_projects.set_defaults(handler=cmd_list_projects)

    get_project = subparsers.add_parser("get-project", help="获取 Gerrit 项目详情")
    add_common_args(get_project)
    get_project.add_argument("--project-name", required=True, help="项目名")
    get_project.set_defaults(handler=cmd_get_project)

    list_branches = subparsers.add_parser("list-branches", help="列出项目分支")
    add_common_args(list_branches)
    list_branches.add_argument("--project-name", required=True, help="项目名")
    list_branches.add_argument("--match", help="按子串筛选分支")
    list_branches.add_argument("--regex", help="按正则筛选分支")
    add_range_args(list_branches)
    list_branches.set_defaults(handler=cmd_list_branches)

    get_branch = subparsers.add_parser("get-branch", help="获取单个分支详情")
    add_common_args(get_branch)
    get_branch.add_argument("--project-name", required=True, help="项目名")
    get_branch.add_argument("--branch-id", required=True, help="分支名或完整 ref")
    get_branch.set_defaults(handler=cmd_get_branch)

    query_accounts = subparsers.add_parser("query-accounts", help="查询 Gerrit 账号")
    add_common_args(query_accounts)
    query_accounts.add_argument("--query", required=True, help="账号查询字符串")
    query_accounts.add_argument("--suggest", action="store_true", help="启用账号联想")
    query_accounts.add_argument("--details", action="store_true", help="返回 DETAILS 字段")
    query_accounts.add_argument("--all-emails", action="store_true", help="返回 ALL_EMAILS 字段")
    query_accounts.add_argument("--limit", type=int, help="返回结果数量限制")
    query_accounts.add_argument("--start", type=int, help="起始偏移")
    query_accounts.set_defaults(handler=cmd_query_accounts)

    get_account = subparsers.add_parser("get-account", help="获取账号详情")
    add_common_args(get_account)
    get_account.add_argument("--account-id", required=True, help="账号 ID、邮箱、用户名或 self")
    get_account.set_defaults(handler=cmd_get_account)

    get_account_detail = subparsers.add_parser("get-account-detail", help="获取账号详细信息")
    add_common_args(get_account_detail)
    get_account_detail.add_argument("--account-id", required=True, help="账号 ID、邮箱、用户名或 self")
    get_account_detail.set_defaults(handler=cmd_get_account_detail)

    list_groups = subparsers.add_parser("list-groups", help="列出 Gerrit 用户组")
    add_common_args(list_groups)
    list_groups.add_argument("--query", help="用户组查询语句")
    list_groups.add_argument("--owned-by", help="按 owner group 过滤")
    list_groups.add_argument("--owned", action="store_true", help="只返回当前用户拥有的组")
    list_groups.add_argument("--group", help="与 --owned 搭配检查某个组")
    list_groups.add_argument("--suggest", help="按前缀联想用户组")
    list_groups.add_argument("--project", help="联想时提供项目上下文")
    list_groups.add_argument("--match", help="按子串筛选用户组")
    list_groups.add_argument("--regex", help="按正则筛选用户组")
    list_groups.add_argument("--includes", action="store_true", help="返回直接子组")
    list_groups.add_argument("--members", action="store_true", help="返回直接成员")
    add_range_args(list_groups)
    list_groups.set_defaults(handler=cmd_list_groups)

    get_group = subparsers.add_parser("get-group", help="获取用户组详情")
    add_common_args(get_group)
    get_group.add_argument("--group-id", required=True, help="组 ID、UUID 或组名")
    get_group.set_defaults(handler=cmd_get_group)

    list_group_members = subparsers.add_parser("list-group-members", help="列出用户组成员")
    add_common_args(list_group_members)
    list_group_members.add_argument("--group-id", required=True, help="组 ID、UUID 或组名")
    list_group_members.add_argument("--recursive", action="store_true", help="递归解析包含的子组成员")
    list_group_members.set_defaults(handler=cmd_list_group_members)

    list_change_messages = subparsers.add_parser("list-change-messages", help="列出变更消息")
    add_common_args(list_change_messages)
    list_change_messages.add_argument("--change-id", required=True, help="变更 ID，格式为 project~branch~Change-Id")
    list_change_messages.set_defaults(handler=cmd_list_change_messages)

    get_topic = subparsers.add_parser("get-topic", help="获取变更 Topic")
    add_common_args(get_topic)
    get_topic.add_argument("--change-id", required=True, help="变更 ID，格式为 project~branch~Change-Id")
    get_topic.set_defaults(handler=cmd_get_topic)

    list_files = subparsers.add_parser("list-files", help="列出 patch set 文件")
    add_common_args(list_files)
    list_files.add_argument("--change-id", required=True, help="变更 ID，格式为 project~branch~Change-Id")
    list_files.add_argument("--revision-id", required=True, help="revision SHA、patch set 编号对应 SHA，或 current")
    list_files.add_argument("--reviewed", action="store_true", help="仅返回已标记 reviewed 的文件路径")
    list_files.add_argument("--query", help="按文件路径子串筛选")
    list_files.add_argument("--parent", type=int, help="按父提交编号查看文件差异")
    list_files.add_argument("--base", help="按指定 patch set 作为基线查看文件差异")
    list_files.set_defaults(handler=cmd_list_files)

    add_reviewer = subparsers.add_parser("add-reviewer", help="为 Gerrit 变更添加审阅者")
    add_common_args(add_reviewer)
    add_reviewer.add_argument("--change-id", required=True, help="变更 ID，格式为 project~branch~Change-Id")
    add_reviewer.add_argument("--reviewer", required=True, help="审阅者邮箱或用户名")
    add_reviewer.add_argument("--state", default="REVIEWER", choices=["REVIEWER", "CC"], help="添加类型")
    add_reviewer.set_defaults(handler=cmd_add_reviewer)

    post_review = subparsers.add_parser("post-review", help="为 Gerrit 变更发布审查评论")
    add_common_args(post_review)
    post_review.add_argument("--change-id", required=True, help="变更 ID，格式为 project~branch~Change-Id")
    post_review.add_argument("--message", required=True, help="审查消息")
    post_review.add_argument("--revision", default="current", help="修订版本，默认 current")
    post_review.set_defaults(handler=cmd_post_review)

    create_change = subparsers.add_parser("create-change", help="创建 Gerrit 变更")
    add_common_args(create_change)
    create_change.add_argument("--project", required=True, help="项目名")
    create_change.add_argument("--branch", required=True, help="目标分支")
    create_change.add_argument("--subject", required=True, help="变更主题")
    create_change.set_defaults(handler=cmd_create_change)

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    handler: Callable[[argparse.Namespace], int] = args.handler
    try:
        return handler(args)
    except GerritError as err:
        return print_error(err)


if __name__ == "__main__":
    raise SystemExit(main())
