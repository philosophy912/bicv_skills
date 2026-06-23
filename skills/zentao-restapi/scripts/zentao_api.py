#!/usr/bin/env python3
"""ZenTao REST API single-entry script."""

import argparse
import json
from typing import Any, Callable
from urllib import error, parse, request

from system_config import (
    ServiceError,
    ServiceTarget,
    resolve_target,
    print_error as _print_error,
    print_system,
    print_json_result,
)

ZentaoError = ServiceError
ZentaoTarget = ServiceTarget

# ---------------------------------------------------------------------------
# Danger levels for write operations
# ---------------------------------------------------------------------------
DANGER_CRITICAL = "CRITICAL"
DANGER_HIGH = "HIGH"
DANGER_MEDIUM = "MEDIUM"

DANGER_CRITICAL_OPS: dict[str, str] = {
    "delete-bug": "永久删除 Bug 及其关联数据",
    "delete-task": "永久删除任务及其关联数据",
    "delete-story": "永久删除需求及其关联数据",
    "delete-project": "永久删除项目",
    "delete-execution": "永久删除执行",
    "delete-testcase": "永久删除测试用例",
    "delete-testtask": "永久删除测试单",
    "delete-release": "永久删除发布",
}

DANGER_HIGH_OPS: dict[str, str] = {
    "create-bug": "创建新的 Bug 记录",
    "create-task": "创建新的任务",
    "create-story": "创建新的需求",
    "create-project": "创建新的项目",
    "create-execution": "创建新的执行",
    "create-testcase": "创建新的测试用例",
    "create-testtask": "创建新的测试单",
    "create-release": "创建新的发布",
    "create-user": "创建新用户",
    "update-bug": "修改 Bug 信息",
    "update-task": "修改任务信息",
    "update-story": "修改需求信息",
    "update-project": "修改项目信息",
    "update-execution": "修改执行信息",
    "update-testcase": "修改测试用例",
    "update-testtask": "修改测试单",
    "update-release": "修改发布",
    "close-bug": "关闭 Bug",
    "close-task": "关闭任务",
    "close-story": "关闭需求",
    "resolve-bug": "解决 Bug",
    "activate-bug": "激活 Bug",
    "activate-task": "激活任务",
    "activate-story": "激活需求",
    "change-story": "变更需求",
    "finish-task": "完成任务",
    "start-task": "启动任务",
}


def confirm_dangerous(operation: str, description: str, resource: str) -> None:
    level = DANGER_CRITICAL if operation in DANGER_CRITICAL_OPS else DANGER_HIGH
    print(f"\n⚠️  高危操作确认 [级别: {level}]")
    print(f"操作: {operation}")
    print(f"资源: {resource}")
    print(f"影响: {description}")
    answer = input("确认执行? (y/N): ").strip().lower()
    if answer != "y":
        print("已取消操作")
        raise SystemExit(0)


# ---------------------------------------------------------------------------
# URL / request helpers
# ---------------------------------------------------------------------------

API_PATH_PREFIX = "/api.php/v2"


def _build_url(zentao_url: str, path: str, *, params: dict[str, Any] | None = None) -> str:
    url = f"{zentao_url.rstrip('/')}{API_PATH_PREFIX}{path}"
    if params:
        query = parse.urlencode(params, doseq=True)
        url = f"{url}?{query}"
    return url


def request_json(
    method: str,
    zentao_url: str,
    path: str,
    *,
    token: str | None = None,
    params: dict[str, Any] | None = None,
    payload: dict[str, Any] | None = None,
) -> Any:
    url = _build_url(zentao_url, path, params=params)
    headers = {"Accept": "application/json"}
    data = None

    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json; charset=utf-8"

    if token is not None:
        headers["Authorization"] = f"Bearer {token}"

    req = request.Request(url, data=data, headers=headers, method=method.upper())

    try:
        with request.urlopen(req) as resp:
            body = resp.read().decode("utf-8")
    except error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise ZentaoError("请求失败", status_code=exc.code, response_text=body) from exc
    except error.URLError as exc:
        raise ZentaoError(f"网络错误: {exc.reason}") from exc

    body = body.strip()
    if not body:
        return None

    try:
        return json.loads(body)
    except json.JSONDecodeError as exc:
        raise ZentaoError("响应不是合法 JSON", response_text=body) from exc


# ---------------------------------------------------------------------------
# Token management
# ---------------------------------------------------------------------------


def get_token(target: ZentaoTarget, *, force: bool = False) -> str:
    if not force and hasattr(target, "_zentao_token"):
        return target._zentao_token

    payload = {"account": target.auth[0], "password": target.auth[1]}
    result = request_json("POST", target.url, "/tokens", payload=payload)
    if not isinstance(result, dict) or "token" not in result:
        raise ZentaoError("获取 Token 失败: 响应中未找到 token 字段", response_text=json.dumps(result, ensure_ascii=False))
    token = str(result["token"])
    target._zentao_token = token
    return token


def request_json_with_auth(
    method: str,
    zentao_url: str,
    path: str,
    *,
    target: ZentaoTarget,
    params: dict[str, Any] | None = None,
    payload: dict[str, Any] | None = None,
    force_token: bool = False,
) -> Any:
    token = get_token(target, force=force_token)
    try:
        return request_json(method, zentao_url, path, token=token, params=params, payload=payload)
    except ZentaoError as exc:
        if exc.status_code == 401 and not force_token:
            token = get_token(target, force=True)
            return request_json(method, zentao_url, path, token=token, params=params, payload=payload)
        raise


# ---------------------------------------------------------------------------
# Output helpers
# ---------------------------------------------------------------------------


def print_error(err: ServiceError) -> int:
    return _print_error(err)


# ---------------------------------------------------------------------------
# Common args
# ---------------------------------------------------------------------------


def add_common_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--zentao", help="显式指定禅道地址")
    parser.add_argument("--system", help="配置文件中的禅道系统名；未提供时使用默认系统")
    parser.add_argument("--user", help="认证信息，格式为 username:password")


def add_page_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--page", type=int, help="页码（从 1 开始）")
    parser.add_argument("--limit", type=int, help="每页记录数")


# ---------------------------------------------------------------------------
# Target resolution
# ---------------------------------------------------------------------------


def _target(args: argparse.Namespace) -> ZentaoTarget:
    return resolve_target(
        args.zentao if hasattr(args, "zentao") else None,
        args.user if hasattr(args, "user") else None,
        args.system if hasattr(args, "system") else None,
        config_name="zentao.json",
    )


# ---------------------------------------------------------------------------
# Danger confirmation wrapper
# ---------------------------------------------------------------------------


def with_confirm(cmd_name: str, resource_desc: str) -> Callable:
    """Decorator that prompts danger confirmation before executing a command."""

    def decorator(fn: Callable) -> Callable:
        def wrapper(args: argparse.Namespace) -> int:
            if cmd_name in DANGER_CRITICAL_OPS:
                confirm_dangerous(cmd_name, DANGER_CRITICAL_OPS[cmd_name], resource_desc)
            elif cmd_name in DANGER_HIGH_OPS:
                confirm_dangerous(cmd_name, DANGER_HIGH_OPS[cmd_name], resource_desc)
            return fn(args)

        return wrapper

    return decorator


# ===================================================================
# Commands
# ===================================================================


def cmd_get_token(args: argparse.Namespace) -> int:
    target = _target(args)
    token = get_token(target, force=args.force)
    print_system(target)
    print(f"Token: {token}")
    return 0


# -- Bug management -----------------------------------------------------------


def cmd_list_bugs(args: argparse.Namespace) -> int:
    target = _target(args)
    params: dict[str, Any] = {}
    if args.product is not None:
        params["product"] = args.product
    if args.project is not None:
        params["project"] = args.project
    if args.page is not None:
        params["page"] = args.page
    if args.limit is not None:
        params["limit"] = args.limit
    result = request_json_with_auth("GET", target.url, "/bugs", target=target, params=params or None)
    return print_json_result(target, result, "Bug 列表:")


def cmd_get_bug(args: argparse.Namespace) -> int:
    target = _target(args)
    result = request_json_with_auth("GET", target.url, f"/bugs/{args.id}", target=target)
    return print_json_result(target, result, "Bug 详情:")


@with_confirm("create-bug", "创建 Bug")
def cmd_create_bug(args: argparse.Namespace) -> int:
    target = _target(args)
    payload = {"product": args.product, "title": args.title}
    if args.severity is not None:
        payload["severity"] = args.severity
    if args.pri is not None:
        payload["pri"] = args.pri
    if args.type is not None:
        payload["type"] = args.type
    if args.assigned_to is not None:
        payload["assignedTo"] = args.assigned_to
    result = request_json_with_auth("POST", target.url, "/bugs", target=target, payload=payload)
    return print_json_result(target, result, "Bug 创建结果:")


@with_confirm("update-bug", "修改 Bug")
def cmd_update_bug(args: argparse.Namespace) -> int:
    target = _target(args)
    payload: dict[str, Any] = {}
    for key in ("title", "severity", "pri", "type", "status", "assigned_to"):
        val = getattr(args, key, None)
        if val is not None:
            payload[key] = val
    if args.keywords is not None:
        payload["keywords"] = args.keywords
    result = request_json_with_auth("PUT", target.url, f"/bugs/{args.id}", target=target, payload=payload)
    return print_json_result(target, result, "Bug 修改结果:")


@with_confirm("resolve-bug", "解决 Bug")
def cmd_resolve_bug(args: argparse.Namespace) -> int:
    target = _target(args)
    payload = {"resolution": args.resolution}
    if args.build is not None:
        payload["build"] = args.build
    result = request_json_with_auth("PUT", target.url, f"/bugs/{args.id}", target=target, payload=payload)
    return print_json_result(target, result, "Bug 解决结果:")


@with_confirm("close-bug", "关闭 Bug")
def cmd_close_bug(args: argparse.Namespace) -> int:
    target = _target(args)
    result = request_json_with_auth("PUT", target.url, f"/bugs/{args.id}", target=target, payload={"status": "closed"})
    return print_json_result(target, result, "Bug 关闭结果:")


@with_confirm("activate-bug", "激活 Bug")
def cmd_activate_bug(args: argparse.Namespace) -> int:
    target = _target(args)
    result = request_json_with_auth("PUT", target.url, f"/bugs/{args.id}", target=target, payload={"status": "active"})
    return print_json_result(target, result, "Bug 激活结果:")


@with_confirm("delete-bug", "删除 Bug")
def cmd_delete_bug(args: argparse.Namespace) -> int:
    target = _target(args)
    result = request_json_with_auth("DELETE", target.url, f"/bugs/{args.id}", target=target)
    return print_json_result(target, result, "Bug 删除结果:")


# -- Task management ----------------------------------------------------------


def cmd_list_tasks(args: argparse.Namespace) -> int:
    target = _target(args)
    params: dict[str, Any] = {}
    if args.project is not None:
        params["project"] = args.project
    if args.execution is not None:
        params["execution"] = args.execution
    if args.assigned_to is not None:
        params["assignedTo"] = args.assigned_to
    if args.status is not None:
        params["status"] = args.status
    if args.page is not None:
        params["page"] = args.page
    if args.limit is not None:
        params["limit"] = args.limit
    result = request_json_with_auth("GET", target.url, "/tasks", target=target, params=params or None)
    return print_json_result(target, result, "任务列表:")


def cmd_get_task(args: argparse.Namespace) -> int:
    target = _target(args)
    result = request_json_with_auth("GET", target.url, f"/tasks/{args.id}", target=target)
    return print_json_result(target, result, "任务详情:")


@with_confirm("create-task", "创建任务")
def cmd_create_task(args: argparse.Namespace) -> int:
    target = _target(args)
    payload = {"project": args.project, "name": args.name}
    if args.execution is not None:
        payload["execution"] = args.execution
    if args.assigned_to is not None:
        payload["assignedTo"] = args.assigned_to
    if args.estimate is not None:
        payload["estimate"] = args.estimate
    if args.type is not None:
        payload["type"] = args.type
    if args.pri is not None:
        payload["pri"] = args.pri
    if args.desc is not None:
        payload["desc"] = args.desc
    result = request_json_with_auth("POST", target.url, "/tasks", target=target, payload=payload)
    return print_json_result(target, result, "任务创建结果:")


@with_confirm("update-task", "修改任务")
def cmd_update_task(args: argparse.Namespace) -> int:
    target = _target(args)
    payload: dict[str, Any] = {}
    for key in ("name", "assigned_to", "estimate", "consumed", "left", "status", "pri", "type", "desc"):
        val = getattr(args, key, None)
        if val is not None:
            payload[key] = val
    result = request_json_with_auth("PUT", target.url, f"/tasks/{args.id}", target=target, payload=payload)
    return print_json_result(target, result, "任务修改结果:")


@with_confirm("start-task", "启动任务")
def cmd_start_task(args: argparse.Namespace) -> int:
    target = _target(args)
    result = request_json_with_auth("PUT", target.url, f"/tasks/{args.id}", target=target, payload={"status": "doing"})
    return print_json_result(target, result, "任务启动结果:")


@with_confirm("finish-task", "完成任务")
def cmd_finish_task(args: argparse.Namespace) -> int:
    target = _target(args)
    result = request_json_with_auth("PUT", target.url, f"/tasks/{args.id}", target=target, payload={"status": "done"})
    return print_json_result(target, result, "任务完成结果:")


@with_confirm("close-task", "关闭任务")
def cmd_close_task(args: argparse.Namespace) -> int:
    target = _target(args)
    result = request_json_with_auth("PUT", target.url, f"/tasks/{args.id}", target=target, payload={"status": "closed"})
    return print_json_result(target, result, "任务关闭结果:")


@with_confirm("activate-task", "激活任务")
def cmd_activate_task(args: argparse.Namespace) -> int:
    target = _target(args)
    result = request_json_with_auth("PUT", target.url, f"/tasks/{args.id}", target=target, payload={"status": "wait"})
    return print_json_result(target, result, "任务激活结果:")


@with_confirm("delete-task", "删除任务")
def cmd_delete_task(args: argparse.Namespace) -> int:
    target = _target(args)
    result = request_json_with_auth("DELETE", target.url, f"/tasks/{args.id}", target=target)
    return print_json_result(target, result, "任务删除结果:")


# -- Story management ---------------------------------------------------------


def cmd_list_stories(args: argparse.Namespace) -> int:
    target = _target(args)
    params: dict[str, Any] = {}
    if args.product is not None:
        params["product"] = args.product
    if args.page is not None:
        params["page"] = args.page
    if args.limit is not None:
        params["limit"] = args.limit
    result = request_json_with_auth("GET", target.url, "/stories", target=target, params=params or None)
    return print_json_result(target, result, "需求列表:")


def cmd_get_story(args: argparse.Namespace) -> int:
    target = _target(args)
    result = request_json_with_auth("GET", target.url, f"/stories/{args.id}", target=target)
    return print_json_result(target, result, "需求详情:")


@with_confirm("create-story", "创建需求")
def cmd_create_story(args: argparse.Namespace) -> int:
    target = _target(args)
    payload = {"product": args.product, "title": args.title}
    if args.desc is not None:
        payload["desc"] = args.desc
    if args.pri is not None:
        payload["pri"] = args.pri
    if args.assigned_to is not None:
        payload["assignedTo"] = args.assigned_to
    result = request_json_with_auth("POST", target.url, "/stories", target=target, payload=payload)
    return print_json_result(target, result, "需求创建结果:")


@with_confirm("update-story", "修改需求")
def cmd_update_story(args: argparse.Namespace) -> int:
    target = _target(args)
    payload: dict[str, Any] = {}
    for key in ("title", "desc", "pri", "status", "assigned_to"):
        val = getattr(args, key, None)
        if val is not None:
            payload[key] = val
    result = request_json_with_auth("PUT", target.url, f"/stories/{args.id}", target=target, payload=payload)
    return print_json_result(target, result, "需求修改结果:")


@with_confirm("change-story", "变更需求")
def cmd_change_story(args: argparse.Namespace) -> int:
    target = _target(args)
    result = request_json_with_auth("PUT", target.url, f"/stories/{args.id}", target=target, payload={"status": "changed"})
    return print_json_result(target, result, "需求变更结果:")


@with_confirm("close-story", "关闭需求")
def cmd_close_story(args: argparse.Namespace) -> int:
    target = _target(args)
    result = request_json_with_auth("PUT", target.url, f"/stories/{args.id}", target=target, payload={"status": "closed"})
    return print_json_result(target, result, "需求关闭结果:")


@with_confirm("activate-story", "激活需求")
def cmd_activate_story(args: argparse.Namespace) -> int:
    target = _target(args)
    result = request_json_with_auth("PUT", target.url, f"/stories/{args.id}", target=target, payload={"status": "active"})
    return print_json_result(target, result, "需求激活结果:")


@with_confirm("delete-story", "删除需求")
def cmd_delete_story(args: argparse.Namespace) -> int:
    target = _target(args)
    result = request_json_with_auth("DELETE", target.url, f"/stories/{args.id}", target=target)
    return print_json_result(target, result, "需求删除结果:")


# -- Product management -------------------------------------------------------


def cmd_list_products(args: argparse.Namespace) -> int:
    target = _target(args)
    params: dict[str, Any] = {}
    if args.page is not None:
        params["page"] = args.page
    if args.limit is not None:
        params["limit"] = args.limit
    result = request_json_with_auth("GET", target.url, "/products", target=target, params=params or None)
    return print_json_result(target, result, "产品列表:")


def cmd_get_product(args: argparse.Namespace) -> int:
    target = _target(args)
    result = request_json_with_auth("GET", target.url, f"/products/{args.id}", target=target)
    return print_json_result(target, result, "产品详情:")


# -- Project management -------------------------------------------------------


def cmd_list_projects(args: argparse.Namespace) -> int:
    target = _target(args)
    params: dict[str, Any] = {}
    if args.page is not None:
        params["page"] = args.page
    if args.limit is not None:
        params["limit"] = args.limit
    if args.status is not None:
        params["status"] = args.status
    result = request_json_with_auth("GET", target.url, "/projects", target=target, params=params or None)
    return print_json_result(target, result, "项目列表:")


def cmd_get_project(args: argparse.Namespace) -> int:
    target = _target(args)
    result = request_json_with_auth("GET", target.url, f"/projects/{args.id}", target=target)
    return print_json_result(target, result, "项目详情:")


@with_confirm("create-project", "创建项目")
def cmd_create_project(args: argparse.Namespace) -> int:
    target = _target(args)
    payload = {"name": args.name}
    if args.code is not None:
        payload["code"] = args.code
    if args.begin is not None:
        payload["begin"] = args.begin
    if args.end is not None:
        payload["end"] = args.end
    if args.desc is not None:
        payload["desc"] = args.desc
    if args.pm is not None:
        payload["PM"] = args.pm
    result = request_json_with_auth("POST", target.url, "/projects", target=target, payload=payload)
    return print_json_result(target, result, "项目创建结果:")


@with_confirm("update-project", "修改项目")
def cmd_update_project(args: argparse.Namespace) -> int:
    target = _target(args)
    payload: dict[str, Any] = {}
    for key in ("name", "code", "begin", "end", "desc", "status", "pm"):
        val = getattr(args, key, None)
        if val is not None:
            payload[key] = val
    result = request_json_with_auth("PUT", target.url, f"/projects/{args.id}", target=target, payload=payload)
    return print_json_result(target, result, "项目修改结果:")


@with_confirm("delete-project", "删除项目")
def cmd_delete_project(args: argparse.Namespace) -> int:
    target = _target(args)
    result = request_json_with_auth("DELETE", target.url, f"/projects/{args.id}", target=target)
    return print_json_result(target, result, "项目删除结果:")


# -- Execution management -----------------------------------------------------


def cmd_list_executions(args: argparse.Namespace) -> int:
    target = _target(args)
    params: dict[str, Any] = {}
    if args.project is not None:
        params["project"] = args.project
    if args.page is not None:
        params["page"] = args.page
    if args.limit is not None:
        params["limit"] = args.limit
    result = request_json_with_auth("GET", target.url, "/executions", target=target, params=params or None)
    return print_json_result(target, result, "执行列表:")


def cmd_get_execution(args: argparse.Namespace) -> int:
    target = _target(args)
    result = request_json_with_auth("GET", target.url, f"/executions/{args.id}", target=target)
    return print_json_result(target, result, "执行详情:")


@with_confirm("create-execution", "创建执行")
def cmd_create_execution(args: argparse.Namespace) -> int:
    target = _target(args)
    payload = {"project": args.project, "name": args.name}
    if args.begin is not None:
        payload["begin"] = args.begin
    if args.end is not None:
        payload["end"] = args.end
    if args.desc is not None:
        payload["desc"] = args.desc
    if args.pm is not None:
        payload["PM"] = args.pm
    result = request_json_with_auth("POST", target.url, "/executions", target=target, payload=payload)
    return print_json_result(target, result, "执行创建结果:")


@with_confirm("update-execution", "修改执行")
def cmd_update_execution(args: argparse.Namespace) -> int:
    target = _target(args)
    payload: dict[str, Any] = {}
    for key in ("name", "begin", "end", "desc", "status", "pm"):
        val = getattr(args, key, None)
        if val is not None:
            payload[key] = val
    result = request_json_with_auth("PUT", target.url, f"/executions/{args.id}", target=target, payload=payload)
    return print_json_result(target, result, "执行修改结果:")


@with_confirm("delete-execution", "删除执行")
def cmd_delete_execution(args: argparse.Namespace) -> int:
    target = _target(args)
    result = request_json_with_auth("DELETE", target.url, f"/executions/{args.id}", target=target)
    return print_json_result(target, result, "执行删除结果:")


# -- Test case management -----------------------------------------------------


def cmd_list_testcases(args: argparse.Namespace) -> int:
    target = _target(args)
    params: dict[str, Any] = {}
    if args.product is not None:
        params["product"] = args.product
    if args.project is not None:
        params["project"] = args.project
    if args.execution is not None:
        params["execution"] = args.execution
    if args.page is not None:
        params["page"] = args.page
    if args.limit is not None:
        params["limit"] = args.limit
    result = request_json_with_auth("GET", target.url, "/testcases", target=target, params=params or None)
    return print_json_result(target, result, "测试用例列表:")


def cmd_get_testcase(args: argparse.Namespace) -> int:
    target = _target(args)
    result = request_json_with_auth("GET", target.url, f"/testcases/{args.id}", target=target)
    return print_json_result(target, result, "测试用例详情:")


@with_confirm("create-testcase", "创建测试用例")
def cmd_create_testcase(args: argparse.Namespace) -> int:
    target = _target(args)
    payload = {"product": args.product, "title": args.title}
    if args.type is not None:
        payload["type"] = args.type
    if args.stage is not None:
        payload["stage"] = args.stage
    if args.pri is not None:
        payload["pri"] = args.pri
    if args.precondition is not None:
        payload["precondition"] = args.precondition
    if args.steps is not None:
        payload["steps"] = args.steps
    result = request_json_with_auth("POST", target.url, "/testcases", target=target, payload=payload)
    return print_json_result(target, result, "测试用例创建结果:")


@with_confirm("update-testcase", "修改测试用例")
def cmd_update_testcase(args: argparse.Namespace) -> int:
    target = _target(args)
    payload: dict[str, Any] = {}
    for key in ("title", "type", "stage", "pri", "precondition", "steps", "status"):
        val = getattr(args, key, None)
        if val is not None:
            payload[key] = val
    result = request_json_with_auth("PUT", target.url, f"/testcases/{args.id}", target=target, payload=payload)
    return print_json_result(target, result, "测试用例修改结果:")


@with_confirm("delete-testcase", "删除测试用例")
def cmd_delete_testcase(args: argparse.Namespace) -> int:
    target = _target(args)
    result = request_json_with_auth("DELETE", target.url, f"/testcases/{args.id}", target=target)
    return print_json_result(target, result, "测试用例删除结果:")


# -- Test task management -----------------------------------------------------


def cmd_list_testtasks(args: argparse.Namespace) -> int:
    target = _target(args)
    params: dict[str, Any] = {}
    if args.product is not None:
        params["product"] = args.product
    if args.project is not None:
        params["project"] = args.project
    if args.execution is not None:
        params["execution"] = args.execution
    if args.page is not None:
        params["page"] = args.page
    if args.limit is not None:
        params["limit"] = args.limit
    result = request_json_with_auth("GET", target.url, "/testtasks", target=target, params=params or None)
    return print_json_result(target, result, "测试单列表:")


def cmd_get_testtask(args: argparse.Namespace) -> int:
    target = _target(args)
    result = request_json_with_auth("GET", target.url, f"/testtasks/{args.id}", target=target)
    return print_json_result(target, result, "测试单详情:")


@with_confirm("create-testtask", "创建测试单")
def cmd_create_testtask(args: argparse.Namespace) -> int:
    target = _target(args)
    payload = {"product": args.product, "name": args.name}
    if args.project is not None:
        payload["project"] = args.project
    if args.execution is not None:
        payload["execution"] = args.execution
    if args.begin is not None:
        payload["begin"] = args.begin
    if args.end is not None:
        payload["end"] = args.end
    if args.desc is not None:
        payload["desc"] = args.desc
    result = request_json_with_auth("POST", target.url, "/testtasks", target=target, payload=payload)
    return print_json_result(target, result, "测试单创建结果:")


@with_confirm("update-testtask", "修改测试单")
def cmd_update_testtask(args: argparse.Namespace) -> int:
    target = _target(args)
    payload: dict[str, Any] = {}
    for key in ("name", "begin", "end", "desc", "status"):
        val = getattr(args, key, None)
        if val is not None:
            payload[key] = val
    result = request_json_with_auth("PUT", target.url, f"/testtasks/{args.id}", target=target, payload=payload)
    return print_json_result(target, result, "测试单修改结果:")


@with_confirm("delete-testtask", "删除测试单")
def cmd_delete_testtask(args: argparse.Namespace) -> int:
    target = _target(args)
    result = request_json_with_auth("DELETE", target.url, f"/testtasks/{args.id}", target=target)
    return print_json_result(target, result, "测试单删除结果:")


# -- User management ----------------------------------------------------------


def cmd_list_users(args: argparse.Namespace) -> int:
    target = _target(args)
    params: dict[str, Any] = {}
    if args.page is not None:
        params["page"] = args.page
    if args.limit is not None:
        params["limit"] = args.limit
    if args.dept is not None:
        params["dept"] = args.dept
    result = request_json_with_auth("GET", target.url, "/users", target=target, params=params or None)
    return print_json_result(target, result, "用户列表:")


def cmd_get_user(args: argparse.Namespace) -> int:
    target = _target(args)
    result = request_json_with_auth("GET", target.url, f"/users/{args.id}", target=target)
    return print_json_result(target, result, "用户详情:")


@with_confirm("create-user", "创建用户")
def cmd_create_user(args: argparse.Namespace) -> int:
    target = _target(args)
    payload: dict[str, Any] = {"account": args.account, "realname": args.realname, "password": args.password}
    if args.email is not None:
        payload["email"] = args.email
    if args.phone is not None:
        payload["phone"] = args.phone
    if args.dept is not None:
        payload["dept"] = args.dept
    if args.role is not None:
        payload["role"] = args.role
    result = request_json_with_auth("POST", target.url, "/users", target=target, payload=payload)
    return print_json_result(target, result, "用户创建结果:")


# -- Department management ----------------------------------------------------


def cmd_list_departments(args: argparse.Namespace) -> int:
    target = _target(args)
    params: dict[str, Any] = {}
    if args.page is not None:
        params["page"] = args.page
    if args.limit is not None:
        params["limit"] = args.limit
    result = request_json_with_auth("GET", target.url, "/departments", target=target, params=params or None)
    return print_json_result(target, result, "部门列表:")


# -- Release management -------------------------------------------------------


def cmd_list_releases(args: argparse.Namespace) -> int:
    target = _target(args)
    params: dict[str, Any] = {}
    if args.product is not None:
        params["product"] = args.product
    if args.page is not None:
        params["page"] = args.page
    if args.limit is not None:
        params["limit"] = args.limit
    result = request_json_with_auth("GET", target.url, "/releases", target=target, params=params or None)
    return print_json_result(target, result, "发布列表:")


def cmd_get_release(args: argparse.Namespace) -> int:
    target = _target(args)
    result = request_json_with_auth("GET", target.url, f"/releases/{args.id}", target=target)
    return print_json_result(target, result, "发布详情:")


@with_confirm("create-release", "创建发布")
def cmd_create_release(args: argparse.Namespace) -> int:
    target = _target(args)
    payload: dict[str, Any] = {"product": args.product, "name": args.name}
    if args.build is not None:
        payload["build"] = args.build
    if args.date is not None:
        payload["date"] = args.date
    if args.desc is not None:
        payload["desc"] = args.desc
    result = request_json_with_auth("POST", target.url, "/releases", target=target, payload=payload)
    return print_json_result(target, result, "发布创建结果:")


@with_confirm("update-release", "修改发布")
def cmd_update_release(args: argparse.Namespace) -> int:
    target = _target(args)
    payload: dict[str, Any] = {}
    for key in ("name", "build", "date", "desc", "status"):
        val = getattr(args, key, None)
        if val is not None:
            payload[key] = val
    result = request_json_with_auth("PUT", target.url, f"/releases/{args.id}", target=target, payload=payload)
    return print_json_result(target, result, "发布修改结果:")


@with_confirm("delete-release", "删除发布")
def cmd_delete_release(args: argparse.Namespace) -> int:
    target = _target(args)
    result = request_json_with_auth("DELETE", target.url, f"/releases/{args.id}", target=target)
    return print_json_result(target, result, "发布删除结果:")


# -- Build management ---------------------------------------------------------


def cmd_list_builds(args: argparse.Namespace) -> int:
    target = _target(args)
    params: dict[str, Any] = {}
    if args.product is not None:
        params["product"] = args.product
    if args.page is not None:
        params["page"] = args.page
    if args.limit is not None:
        params["limit"] = args.limit
    result = request_json_with_auth("GET", target.url, "/builds", target=target, params=params or None)
    return print_json_result(target, result, "版本列表:")


def cmd_get_build(args: argparse.Namespace) -> int:
    target = _target(args)
    result = request_json_with_auth("GET", target.url, f"/builds/{args.id}", target=target)
    return print_json_result(target, result, "版本详情:")


@with_confirm("create-build", "创建版本")
def cmd_create_build(args: argparse.Namespace) -> int:
    target = _target(args)
    payload: dict[str, Any] = {"product": args.product, "name": args.name}
    if args.project is not None:
        payload["project"] = args.project
    if args.builder is not None:
        payload["builder"] = args.builder
    if args.date is not None:
        payload["date"] = args.date
    if args.desc is not None:
        payload["desc"] = args.desc
    result = request_json_with_auth("POST", target.url, "/builds", target=target, payload=payload)
    return print_json_result(target, result, "版本创建结果:")


# ===================================================================
# Parser
# ===================================================================


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="禅道 REST API 单入口脚本")
    subparsers = parser.add_subparsers(dest="command", required=True)

    # Token
    p = subparsers.add_parser("get-token", help="获取/刷新访问令牌")
    add_common_args(p)
    p.add_argument("--force", action="store_true", help="强制刷新 token（忽略缓存）")
    p.set_defaults(handler=cmd_get_token)

    # -- Bug management --
    p = subparsers.add_parser("list-bugs", help="列出 Bug")
    add_common_args(p)
    add_page_args(p)
    p.add_argument("--product", type=int, help="按产品筛选")
    p.add_argument("--project", type=int, help="按项目筛选")
    p.set_defaults(handler=cmd_list_bugs)

    p = subparsers.add_parser("get-bug", help="获取 Bug 详情")
    add_common_args(p)
    p.add_argument("--id", type=int, required=True, help="Bug ID")
    p.set_defaults(handler=cmd_get_bug)

    p = subparsers.add_parser("create-bug", help="创建 Bug")
    add_common_args(p)
    p.add_argument("--product", type=int, required=True, help="产品 ID")
    p.add_argument("--title", required=True, help="Bug 标题")
    p.add_argument("--severity", type=int, help="严重程度 (1-4)")
    p.add_argument("--pri", type=int, help="优先级 (1-4)")
    p.add_argument("--type", help="Bug 类型")
    p.add_argument("--assigned-to", help="指派给")
    p.set_defaults(handler=cmd_create_bug)

    p = subparsers.add_parser("update-bug", help="修改 Bug")
    add_common_args(p)
    p.add_argument("--id", type=int, required=True, help="Bug ID")
    p.add_argument("--title", help="Bug 标题")
    p.add_argument("--severity", type=int, help="严重程度 (1-4)")
    p.add_argument("--pri", type=int, help="优先级 (1-4)")
    p.add_argument("--type", help="Bug 类型")
    p.add_argument("--status", help="状态")
    p.add_argument("--assigned-to", help="指派给")
    p.add_argument("--keywords", help="关键词")
    p.set_defaults(handler=cmd_update_bug)

    p = subparsers.add_parser("resolve-bug", help="解决 Bug")
    add_common_args(p)
    p.add_argument("--id", type=int, required=True, help="Bug ID")
    p.add_argument("--resolution", required=True, help="解决方案 (fixed/postponed/bydesign/notrepro/duplicate/external)")
    p.add_argument("--build", help="解决的版本")
    p.set_defaults(handler=cmd_resolve_bug)

    p = subparsers.add_parser("close-bug", help="关闭 Bug")
    add_common_args(p)
    p.add_argument("--id", type=int, required=True, help="Bug ID")
    p.set_defaults(handler=cmd_close_bug)

    p = subparsers.add_parser("activate-bug", help="激活 Bug")
    add_common_args(p)
    p.add_argument("--id", type=int, required=True, help="Bug ID")
    p.set_defaults(handler=cmd_activate_bug)

    p = subparsers.add_parser("delete-bug", help="删除 Bug")
    add_common_args(p)
    p.add_argument("--id", type=int, required=True, help="Bug ID")
    p.set_defaults(handler=cmd_delete_bug)

    # -- Task management --
    p = subparsers.add_parser("list-tasks", help="列出任务")
    add_common_args(p)
    add_page_args(p)
    p.add_argument("--project", type=int, help="按项目筛选")
    p.add_argument("--execution", type=int, help="按执行筛选")
    p.add_argument("--assigned-to", help="按指派给筛选")
    p.add_argument("--status", help="按状态筛选")
    p.set_defaults(handler=cmd_list_tasks)

    p = subparsers.add_parser("get-task", help="获取任务详情")
    add_common_args(p)
    p.add_argument("--id", type=int, required=True, help="任务 ID")
    p.set_defaults(handler=cmd_get_task)

    p = subparsers.add_parser("create-task", help="创建任务")
    add_common_args(p)
    p.add_argument("--project", type=int, required=True, help="项目 ID")
    p.add_argument("--name", required=True, help="任务名称")
    p.add_argument("--execution", type=int, help="执行 ID")
    p.add_argument("--assigned-to", help="指派给")
    p.add_argument("--estimate", type=float, help="预计工时（小时）")
    p.add_argument("--type", help="任务类型")
    p.add_argument("--pri", type=int, help="优先级")
    p.add_argument("--desc", help="任务描述")
    p.set_defaults(handler=cmd_create_task)

    p = subparsers.add_parser("update-task", help="修改任务")
    add_common_args(p)
    p.add_argument("--id", type=int, required=True, help="任务 ID")
    p.add_argument("--name", help="任务名称")
    p.add_argument("--assigned-to", help="指派给")
    p.add_argument("--estimate", type=float, help="预计工时")
    p.add_argument("--consumed", type=float, help="消耗工时")
    p.add_argument("--left", type=float, help="剩余工时")
    p.add_argument("--status", help="状态")
    p.add_argument("--pri", type=int, help="优先级")
    p.add_argument("--type", help="任务类型")
    p.add_argument("--desc", help="任务描述")
    p.set_defaults(handler=cmd_update_task)

    p = subparsers.add_parser("start-task", help="启动任务")
    add_common_args(p)
    p.add_argument("--id", type=int, required=True, help="任务 ID")
    p.set_defaults(handler=cmd_start_task)

    p = subparsers.add_parser("finish-task", help="完成任务")
    add_common_args(p)
    p.add_argument("--id", type=int, required=True, help="任务 ID")
    p.set_defaults(handler=cmd_finish_task)

    p = subparsers.add_parser("close-task", help="关闭任务")
    add_common_args(p)
    p.add_argument("--id", type=int, required=True, help="任务 ID")
    p.set_defaults(handler=cmd_close_task)

    p = subparsers.add_parser("activate-task", help="激活任务")
    add_common_args(p)
    p.add_argument("--id", type=int, required=True, help="任务 ID")
    p.set_defaults(handler=cmd_activate_task)

    p = subparsers.add_parser("delete-task", help="删除任务")
    add_common_args(p)
    p.add_argument("--id", type=int, required=True, help="任务 ID")
    p.set_defaults(handler=cmd_delete_task)

    # -- Story management --
    p = subparsers.add_parser("list-stories", help="列出需求")
    add_common_args(p)
    add_page_args(p)
    p.add_argument("--product", type=int, required=True, help="产品 ID")
    p.set_defaults(handler=cmd_list_stories)

    p = subparsers.add_parser("get-story", help="获取需求详情")
    add_common_args(p)
    p.add_argument("--id", type=int, required=True, help="需求 ID")
    p.set_defaults(handler=cmd_get_story)

    p = subparsers.add_parser("create-story", help="创建需求")
    add_common_args(p)
    p.add_argument("--product", type=int, required=True, help="产品 ID")
    p.add_argument("--title", required=True, help="需求标题")
    p.add_argument("--desc", help="需求描述")
    p.add_argument("--pri", type=int, help="优先级")
    p.add_argument("--assigned-to", help="指派给")
    p.set_defaults(handler=cmd_create_story)

    p = subparsers.add_parser("update-story", help="修改需求")
    add_common_args(p)
    p.add_argument("--id", type=int, required=True, help="需求 ID")
    p.add_argument("--title", help="需求标题")
    p.add_argument("--desc", help="需求描述")
    p.add_argument("--pri", type=int, help="优先级")
    p.add_argument("--status", help="状态")
    p.add_argument("--assigned-to", help="指派给")
    p.set_defaults(handler=cmd_update_story)

    p = subparsers.add_parser("change-story", help="变更需求")
    add_common_args(p)
    p.add_argument("--id", type=int, required=True, help="需求 ID")
    p.set_defaults(handler=cmd_change_story)

    p = subparsers.add_parser("close-story", help="关闭需求")
    add_common_args(p)
    p.add_argument("--id", type=int, required=True, help="需求 ID")
    p.set_defaults(handler=cmd_close_story)

    p = subparsers.add_parser("activate-story", help="激活需求")
    add_common_args(p)
    p.add_argument("--id", type=int, required=True, help="需求 ID")
    p.set_defaults(handler=cmd_activate_story)

    p = subparsers.add_parser("delete-story", help="删除需求")
    add_common_args(p)
    p.add_argument("--id", type=int, required=True, help="需求 ID")
    p.set_defaults(handler=cmd_delete_story)

    # -- Product management --
    p = subparsers.add_parser("list-products", help="列出产品")
    add_common_args(p)
    add_page_args(p)
    p.set_defaults(handler=cmd_list_products)

    p = subparsers.add_parser("get-product", help="获取产品详情")
    add_common_args(p)
    p.add_argument("--id", type=int, required=True, help="产品 ID")
    p.set_defaults(handler=cmd_get_product)

    # -- Project management --
    p = subparsers.add_parser("list-projects", help="列出项目")
    add_common_args(p)
    add_page_args(p)
    p.add_argument("--status", help="按状态筛选")
    p.set_defaults(handler=cmd_list_projects)

    p = subparsers.add_parser("get-project", help="获取项目详情")
    add_common_args(p)
    p.add_argument("--id", type=int, required=True, help="项目 ID")
    p.set_defaults(handler=cmd_get_project)

    p = subparsers.add_parser("create-project", help="创建项目")
    add_common_args(p)
    p.add_argument("--name", required=True, help="项目名称")
    p.add_argument("--code", help="项目代号")
    p.add_argument("--begin", help="开始日期 (YYYY-MM-DD)")
    p.add_argument("--end", help="结束日期 (YYYY-MM-DD)")
    p.add_argument("--desc", help="项目描述")
    p.add_argument("--pm", help="项目负责人")
    p.set_defaults(handler=cmd_create_project)

    p = subparsers.add_parser("update-project", help="修改项目")
    add_common_args(p)
    p.add_argument("--id", type=int, required=True, help="项目 ID")
    p.add_argument("--name", help="项目名称")
    p.add_argument("--code", help="项目代号")
    p.add_argument("--begin", help="开始日期")
    p.add_argument("--end", help="结束日期")
    p.add_argument("--desc", help="项目描述")
    p.add_argument("--status", help="项目状态")
    p.add_argument("--pm", help="项目负责人")
    p.set_defaults(handler=cmd_update_project)

    p = subparsers.add_parser("delete-project", help="删除项目")
    add_common_args(p)
    p.add_argument("--id", type=int, required=True, help="项目 ID")
    p.set_defaults(handler=cmd_delete_project)

    # -- Execution management --
    p = subparsers.add_parser("list-executions", help="列出执行/迭代")
    add_common_args(p)
    add_page_args(p)
    p.add_argument("--project", type=int, help="按项目筛选")
    p.set_defaults(handler=cmd_list_executions)

    p = subparsers.add_parser("get-execution", help="获取执行详情")
    add_common_args(p)
    p.add_argument("--id", type=int, required=True, help="执行 ID")
    p.set_defaults(handler=cmd_get_execution)

    p = subparsers.add_parser("create-execution", help="创建执行/迭代")
    add_common_args(p)
    p.add_argument("--project", type=int, required=True, help="项目 ID")
    p.add_argument("--name", required=True, help="执行名称")
    p.add_argument("--begin", help="开始日期")
    p.add_argument("--end", help="结束日期")
    p.add_argument("--desc", help="执行描述")
    p.add_argument("--pm", help="执行负责人")
    p.set_defaults(handler=cmd_create_execution)

    p = subparsers.add_parser("update-execution", help="修改执行")
    add_common_args(p)
    p.add_argument("--id", type=int, required=True, help="执行 ID")
    p.add_argument("--name", help="执行名称")
    p.add_argument("--begin", help="开始日期")
    p.add_argument("--end", help="结束日期")
    p.add_argument("--desc", help="执行描述")
    p.add_argument("--status", help="状态")
    p.add_argument("--pm", help="执行负责人")
    p.set_defaults(handler=cmd_update_execution)

    p = subparsers.add_parser("delete-execution", help="删除执行")
    add_common_args(p)
    p.add_argument("--id", type=int, required=True, help="执行 ID")
    p.set_defaults(handler=cmd_delete_execution)

    # -- Test case management --
    p = subparsers.add_parser("list-testcases", help="列出测试用例")
    add_common_args(p)
    add_page_args(p)
    p.add_argument("--product", type=int, help="按产品筛选")
    p.add_argument("--project", type=int, help="按项目筛选")
    p.add_argument("--execution", type=int, help="按执行筛选")
    p.set_defaults(handler=cmd_list_testcases)

    p = subparsers.add_parser("get-testcase", help="获取测试用例详情")
    add_common_args(p)
    p.add_argument("--id", type=int, required=True, help="测试用例 ID")
    p.set_defaults(handler=cmd_get_testcase)

    p = subparsers.add_parser("create-testcase", help="创建测试用例")
    add_common_args(p)
    p.add_argument("--product", type=int, required=True, help="产品 ID")
    p.add_argument("--title", required=True, help="用例标题")
    p.add_argument("--type", help="用例类型")
    p.add_argument("--stage", help="用例阶段")
    p.add_argument("--pri", type=int, help="优先级")
    p.add_argument("--precondition", help="前置条件")
    p.add_argument("--steps", help="测试步骤（JSON 字符串）")
    p.set_defaults(handler=cmd_create_testcase)

    p = subparsers.add_parser("update-testcase", help="修改测试用例")
    add_common_args(p)
    p.add_argument("--id", type=int, required=True, help="测试用例 ID")
    p.add_argument("--title", help="用例标题")
    p.add_argument("--type", help="用例类型")
    p.add_argument("--stage", help="用例阶段")
    p.add_argument("--pri", type=int, help="优先级")
    p.add_argument("--precondition", help="前置条件")
    p.add_argument("--steps", help="测试步骤")
    p.add_argument("--status", help="用例状态")
    p.set_defaults(handler=cmd_update_testcase)

    p = subparsers.add_parser("delete-testcase", help="删除测试用例")
    add_common_args(p)
    p.add_argument("--id", type=int, required=True, help="测试用例 ID")
    p.set_defaults(handler=cmd_delete_testcase)

    # -- Test task management --
    p = subparsers.add_parser("list-testtasks", help="列出测试单")
    add_common_args(p)
    add_page_args(p)
    p.add_argument("--product", type=int, help="按产品筛选")
    p.add_argument("--project", type=int, help="按项目筛选")
    p.add_argument("--execution", type=int, help="按执行筛选")
    p.set_defaults(handler=cmd_list_testtasks)

    p = subparsers.add_parser("get-testtask", help="获取测试单详情")
    add_common_args(p)
    p.add_argument("--id", type=int, required=True, help="测试单 ID")
    p.set_defaults(handler=cmd_get_testtask)

    p = subparsers.add_parser("create-testtask", help="创建测试单")
    add_common_args(p)
    p.add_argument("--product", type=int, required=True, help="产品 ID")
    p.add_argument("--name", required=True, help="测试单名称")
    p.add_argument("--project", type=int, help="项目 ID")
    p.add_argument("--execution", type=int, help="执行 ID")
    p.add_argument("--begin", help="开始日期")
    p.add_argument("--end", help="结束日期")
    p.add_argument("--desc", help="测试单描述")
    p.set_defaults(handler=cmd_create_testtask)

    p = subparsers.add_parser("update-testtask", help="修改测试单")
    add_common_args(p)
    p.add_argument("--id", type=int, required=True, help="测试单 ID")
    p.add_argument("--name", help="测试单名称")
    p.add_argument("--begin", help="开始日期")
    p.add_argument("--end", help="结束日期")
    p.add_argument("--desc", help="测试单描述")
    p.add_argument("--status", help="状态")
    p.set_defaults(handler=cmd_update_testtask)

    p = subparsers.add_parser("delete-testtask", help="删除测试单")
    add_common_args(p)
    p.add_argument("--id", type=int, required=True, help="测试单 ID")
    p.set_defaults(handler=cmd_delete_testtask)

    # -- User management --
    p = subparsers.add_parser("list-users", help="列出用户")
    add_common_args(p)
    add_page_args(p)
    p.add_argument("--dept", type=int, help="按部门筛选")
    p.set_defaults(handler=cmd_list_users)

    p = subparsers.add_parser("get-user", help="获取用户详情")
    add_common_args(p)
    p.add_argument("--id", type=int, required=True, help="用户 ID")
    p.set_defaults(handler=cmd_get_user)

    p = subparsers.add_parser("create-user", help="创建用户")
    add_common_args(p)
    p.add_argument("--account", required=True, help="用户账号")
    p.add_argument("--realname", required=True, help="用户真实姓名")
    p.add_argument("--password", required=True, help="用户密码")
    p.add_argument("--email", help="邮箱")
    p.add_argument("--phone", help="手机号")
    p.add_argument("--dept", type=int, help="部门 ID")
    p.add_argument("--role", help="角色")
    p.set_defaults(handler=cmd_create_user)

    # -- Department management --
    p = subparsers.add_parser("list-departments", help="列出部门")
    add_common_args(p)
    add_page_args(p)
    p.set_defaults(handler=cmd_list_departments)

    # -- Release management --
    p = subparsers.add_parser("list-releases", help="列出发布")
    add_common_args(p)
    add_page_args(p)
    p.add_argument("--product", type=int, help="按产品筛选")
    p.set_defaults(handler=cmd_list_releases)

    p = subparsers.add_parser("get-release", help="获取发布详情")
    add_common_args(p)
    p.add_argument("--id", type=int, required=True, help="发布 ID")
    p.set_defaults(handler=cmd_get_release)

    p = subparsers.add_parser("create-release", help="创建发布")
    add_common_args(p)
    p.add_argument("--product", type=int, required=True, help="产品 ID")
    p.add_argument("--name", required=True, help="发布名称")
    p.add_argument("--build", type=int, help="版本 ID")
    p.add_argument("--date", help="发布日期 (YYYY-MM-DD)")
    p.add_argument("--desc", help="发布描述")
    p.set_defaults(handler=cmd_create_release)

    p = subparsers.add_parser("update-release", help="修改发布")
    add_common_args(p)
    p.add_argument("--id", type=int, required=True, help="发布 ID")
    p.add_argument("--name", help="发布名称")
    p.add_argument("--build", type=int, help="版本 ID")
    p.add_argument("--date", help="发布日期")
    p.add_argument("--desc", help="发布描述")
    p.add_argument("--status", help="状态")
    p.set_defaults(handler=cmd_update_release)

    p = subparsers.add_parser("delete-release", help="删除发布")
    add_common_args(p)
    p.add_argument("--id", type=int, required=True, help="发布 ID")
    p.set_defaults(handler=cmd_delete_release)

    # -- Build management --
    p = subparsers.add_parser("list-builds", help="列出版本")
    add_common_args(p)
    add_page_args(p)
    p.add_argument("--product", type=int, help="按产品筛选")
    p.set_defaults(handler=cmd_list_builds)

    p = subparsers.add_parser("get-build", help="获取版本详情")
    add_common_args(p)
    p.add_argument("--id", type=int, required=True, help="版本 ID")
    p.set_defaults(handler=cmd_get_build)

    p = subparsers.add_parser("create-build", help="创建版本")
    add_common_args(p)
    p.add_argument("--product", type=int, required=True, help="产品 ID")
    p.add_argument("--name", required=True, help="版本名称")
    p.add_argument("--project", type=int, help="项目 ID")
    p.add_argument("--builder", help="构建者")
    p.add_argument("--date", help="构建日期 (YYYY-MM-DD)")
    p.add_argument("--desc", help="版本描述")
    p.set_defaults(handler=cmd_create_build)

    return parser


# ===================================================================
# Entry point
# ===================================================================


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    handler: Callable[[argparse.Namespace], int] = args.handler
    try:
        return handler(args)
    except (ZentaoError, SystemExit) as err:
        if isinstance(err, SystemExit):
            return err.code if err.code is not None else 0
        return print_error(err)


if __name__ == "__main__":
    raise SystemExit(main())
