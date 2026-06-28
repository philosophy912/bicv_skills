#!/usr/bin/env python3
"""Single-entry Jenkins Remote API script."""

from __future__ import annotations

import argparse
import base64
import json
import sys
import time
from typing import Any
from urllib import error, parse, request

from system_config import (
    ServiceError,
    ServiceTarget,
    print_error,
    print_json_result,
    resolve_target,
)

JenkinsError = ServiceError
JenkinsTarget = ServiceTarget


def get_crumb(target: JenkinsTarget) -> tuple[str, str] | None:
    if target.auth is None:
        return None

    try:
        data = request_json("GET", target, "/crumbIssuer/api/json")
    except JenkinsError as err:
        if err.status_code in (403, 404):
            return None
        raise

    if not isinstance(data, dict):
        return None

    field_name = data.get("crumbRequestField")
    crumb = data.get("crumb")
    if isinstance(field_name, str) and isinstance(crumb, str) and field_name and crumb:
        return field_name, crumb
    return None


def encode_job_segment(job_name: str) -> str:
    segments = [segment for segment in job_name.split("/") if segment]
    if not segments:
        raise JenkinsError("Job name must not be empty")
    return "/".join(f"job/{parse.quote(segment, safe='')}" for segment in segments)


def build_url(base_url: str, path: str, params: dict[str, Any] | None = None) -> str:
    url = f"{base_url}{path}"
    if params:
        query = parse.urlencode(params, doseq=True)
        url = f"{url}?{query}"
    return url


def request_text(
    method: str,
    target: JenkinsTarget,
    path: str,
    *,
    params: dict[str, Any] | None = None,
    body: bytes | None = None,
    headers: dict[str, str] | None = None,
    include_crumb: bool = False,
) -> str:
    url = build_url(target.url, path, params)
    req_headers = dict(headers or {})
    req_headers.setdefault("Accept", "application/json")

    if target.auth is not None:
        token = base64.b64encode(f"{target.auth[0]}:{target.auth[1]}".encode()).decode("ascii")
        req_headers["Authorization"] = f"Basic {token}"

    if include_crumb:
        crumb = get_crumb(target)
        if crumb is not None:
            req_headers[crumb[0]] = crumb[1]

    req = request.Request(url, data=body, headers=req_headers, method=method.upper())
    try:
        with request.urlopen(req) as response:
            # consoleText 等响应可能含非 UTF-8 字节（嵌入式编译输出的 GBK/二进制字节），
            # 用 replace 容错解码避免 UnicodeDecodeError；JSON 请求里替换字符不影响解析。
            return response.read().decode("utf-8", errors="replace")
    except error.HTTPError as exc:
        response_text = exc.read().decode("utf-8", errors="replace")
        raise JenkinsError(
            "Request failed", status_code=exc.code, response_text=response_text
        ) from exc
    except error.URLError as exc:
        raise JenkinsError(f"Network error: {exc.reason}") from exc


def request_json(
    method: str,
    target: JenkinsTarget,
    path: str,
    *,
    params: dict[str, Any] | None = None,
    payload: dict[str, Any] | None = None,
    include_crumb: bool = False,
) -> Any:
    headers: dict[str, str] = {}
    body = None
    if payload is not None:
        body = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json; charset=utf-8"

    text = request_text(
        method,
        target,
        path,
        params=params,
        body=body,
        headers=headers,
        include_crumb=include_crumb,
    ).strip()
    if not text:
        return None

    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise JenkinsError("Response is not valid JSON", response_text=text) from exc


def add_common_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--jenkins", help="Explicit Jenkins base URL")
    parser.add_argument(
        "--system", help="Configured Jenkins system name; defaults to default_system"
    )
    parser.add_argument("--user", help="Auth in username:token or username:password format")


def add_job_arg(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--job", required=True, help="Jenkins job name; folders use path-like names"
    )


def add_build_number_arg(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--number", default="lastBuild", help="Build number or Jenkins selector")


def _target(args: argparse.Namespace) -> JenkinsTarget:
    return resolve_target(
        args.jenkins if hasattr(args, "jenkins") else None,
        args.user if hasattr(args, "user") else None,
        args.system if hasattr(args, "system") else None,
        config_name="jenkins.json",
        password_key="password",
    )


def cmd_list_jobs(args: argparse.Namespace) -> int:
    target = _target(args)
    data = request_json("GET", target, "/api/json", params={"tree": "jobs[name,url,color]"})
    jobs = data.get("jobs", []) if isinstance(data, dict) else []
    result = [
        {
            "name": job.get("name", "N/A"),
            "url": job.get("url", "N/A"),
            "color": job.get("color", "unknown"),
        }
        for job in jobs
    ]
    print(
        json.dumps(
            {"system": target.system_name, "data": {"jobs": result}},
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


def cmd_get_job(args: argparse.Namespace) -> int:
    target = _target(args)
    path = f"/{encode_job_segment(args.job)}/api/json"
    params: dict[str, Any] = {}
    if args.depth is not None:
        params["depth"] = args.depth
    return print_json_result(target, request_json("GET", target, path, params=params or None))


def cmd_get_build_info(args: argparse.Namespace) -> int:
    target = _target(args)
    path = f"/{encode_job_segment(args.job)}/{parse.quote(args.number, safe='')}/api/json"
    return print_json_result(target, request_json("GET", target, path))


def cmd_get_console_log(args: argparse.Namespace) -> int:
    target = _target(args)
    path = f"/{encode_job_segment(args.job)}/{parse.quote(args.number, safe='')}/consoleText"
    text = request_text("GET", target, path)
    if args.raw:
        sys.stdout.write(text)
        return 0
    print(
        json.dumps(
            {
                "system": target.system_name,
                "data": {"job": args.job, "number": args.number, "log": text},
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


def matches_result_filter(result: Any, spec: str) -> bool:
    """Return True if a build's ``result`` matches a ``--result`` filter spec.

    ``spec`` is either a literal result value (e.g. ``FAILURE``) or a negation
    prefixed with ``!`` (e.g. ``!SUCCESS``). A negation keeps builds whose
    result is set and not equal to the negated value — so ``!SUCCESS`` yields
    FAILURE/UNSTABLE/ABORTED but excludes still-running builds (result is
    ``None``).
    """
    if spec.startswith("!"):
        wanted = spec[1:]
        return result is not None and result != wanted
    return result == spec


def cmd_list_builds(args: argparse.Namespace) -> int:
    target = _target(args)
    path = f"/{encode_job_segment(args.job)}/api/json"
    tree_fields = "builds[number,timestamp,result,duration,url]"
    limit = args.limit
    tree_spec = f"{tree_fields}{{0,{limit}}}" if limit and limit > 0 else tree_fields
    data = request_json("GET", target, path, params={"tree": tree_spec})
    builds = data.get("builds", []) if isinstance(data, dict) else []

    cutoff_ms: int | None = None
    if args.since_hours is not None:
        cutoff_ms = int(time.time() * 1000) - int(args.since_hours * 3600 * 1000)

    result_spec = args.result
    filtered: list[dict[str, Any]] = []
    for build in builds:
        if not isinstance(build, dict):
            continue
        timestamp = build.get("timestamp")
        if cutoff_ms is not None and (
            not isinstance(timestamp, (int, float)) or timestamp < cutoff_ms
        ):
            continue
        if result_spec and not matches_result_filter(build.get("result"), result_spec):
            continue
        filtered.append(
            {
                "number": build.get("number"),
                "timestamp": timestamp,
                "result": build.get("result"),
                "duration": build.get("duration"),
                "url": build.get("url"),
            }
        )

    print(
        json.dumps(
            {"system": target.system_name, "data": filtered},
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


def parse_params(param_values: list[str]) -> dict[str, str]:
    params: dict[str, str] = {}
    for item in param_values:
        key, sep, value = item.partition("=")
        if not sep:
            raise JenkinsError(f"Invalid --param value {item!r}; expected KEY=VALUE")
        params[key] = value
    return params


def cmd_build_job(args: argparse.Namespace) -> int:
    target = _target(args)
    params = parse_params(args.param)
    path = (
        f"/{encode_job_segment(args.job)}/buildWithParameters"
        if params
        else f"/{encode_job_segment(args.job)}/build"
    )
    body = None
    headers = None
    if params:
        body = parse.urlencode(params).encode("utf-8")
        headers = {"Content-Type": "application/x-www-form-urlencoded; charset=utf-8"}

    response = request_text(
        "POST",
        target,
        path,
        body=body,
        headers=headers,
        include_crumb=True,
    )
    result: dict[str, Any] = {"job": args.job, "action": "triggered"}
    if response.strip():
        result["response"] = response.strip()
    print(
        json.dumps(
            {"system": target.system_name, "data": result},
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


def cmd_list_queue(args: argparse.Namespace) -> int:
    target = _target(args)
    return print_json_result(target, request_json("GET", target, "/queue/api/json"))


def cmd_list_nodes(args: argparse.Namespace) -> int:
    target = _target(args)
    tree_spec = (
        "computer[displayName,offline,offlineCauseReason,temporarilyOffline,idle,numExecutors]"
    )
    data = request_json("GET", target, "/computer/api/json", params={"tree": tree_spec})
    computers = data.get("computer", []) if isinstance(data, dict) else []
    nodes = [
        {
            "name": c.get("displayName", "N/A"),
            "offline": bool(c.get("offline", False)),
            "temporarilyOffline": bool(c.get("temporarilyOffline", False)),
            "idle": bool(c.get("idle", True)),
            "numExecutors": c.get("numExecutors", 0),
            "offlineCauseReason": c.get("offlineCauseReason", "") or "",
        }
        for c in computers
        if isinstance(c, dict)
    ]
    offline_nodes = [n for n in nodes if n["offline"]]
    shown = offline_nodes if args.offline else nodes
    print(
        json.dumps(
            {
                "system": target.system_name,
                "data": {
                    "total": len(nodes),
                    "offlineCount": len(offline_nodes),
                    "computers": shown,
                },
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


def cmd_disable_job(args: argparse.Namespace) -> int:
    target = _target(args)
    path = f"/{encode_job_segment(args.job)}/disable"
    request_text("POST", target, path, include_crumb=True)
    print(
        json.dumps(
            {"system": target.system_name, "data": {"job": args.job, "action": "disabled"}},
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


def cmd_enable_job(args: argparse.Namespace) -> int:
    target = _target(args)
    path = f"/{encode_job_segment(args.job)}/enable"
    request_text("POST", target, path, include_crumb=True)
    print(
        json.dumps(
            {"system": target.system_name, "data": {"job": args.job, "action": "enabled"}},
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


def cmd_stop_build(args: argparse.Namespace) -> int:
    target = _target(args)
    path = f"/{encode_job_segment(args.job)}/{parse.quote(args.number, safe='')}/stop"
    request_text("POST", target, path, include_crumb=True)
    print(
        json.dumps(
            {
                "system": target.system_name,
                "data": {"job": args.job, "number": args.number, "action": "stopped"},
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Jenkins Remote API single-entry CLI")
    subparsers = parser.add_subparsers(dest="command", required=True)

    list_jobs = subparsers.add_parser("list-jobs", help="List Jenkins jobs")
    add_common_args(list_jobs)
    list_jobs.set_defaults(handler=cmd_list_jobs)

    get_job = subparsers.add_parser("get-job", help="Get a job payload from /api/json")
    add_common_args(get_job)
    add_job_arg(get_job)
    get_job.add_argument("--depth", type=int, help="Optional Jenkins API depth parameter")
    get_job.set_defaults(handler=cmd_get_job)

    get_build_info = subparsers.add_parser("get-build-info", help="Get build info JSON")
    add_common_args(get_build_info)
    add_job_arg(get_build_info)
    add_build_number_arg(get_build_info)
    get_build_info.set_defaults(handler=cmd_get_build_info)

    get_console_log = subparsers.add_parser("get-console-log", help="Get full consoleText")
    add_common_args(get_console_log)
    add_job_arg(get_console_log)
    add_build_number_arg(get_console_log)
    get_console_log.add_argument(
        "--raw",
        action="store_true",
        help="直接输出 consoleText 原文（不包 JSON 信封），适合管道",
    )
    get_console_log.set_defaults(handler=cmd_get_console_log)

    list_builds = subparsers.add_parser(
        "list-builds",
        help="List builds of a job within a time window, optionally filtered by result",
    )
    add_common_args(list_builds)
    add_job_arg(list_builds)
    list_builds.add_argument(
        "--since-hours",
        type=float,
        default=24,
        help="Only return builds newer than now - N hours (default: 24)",
    )
    list_builds.add_argument(
        "--limit",
        type=int,
        default=50,
        help="Max builds to fetch via Jenkins tree range (default: 50; 0 = no limit)",
    )
    list_builds.add_argument(
        "--result",
        default=None,
        help="Filter by result, e.g. FAILURE; or !SUCCESS to keep all non-SUCCESS "
        "results (FAILURE/UNSTABLE/ABORTED, excludes running builds)",
    )
    list_builds.set_defaults(handler=cmd_list_builds)

    build_job = subparsers.add_parser("build-job", help="Trigger a Jenkins build")
    add_common_args(build_job)
    add_job_arg(build_job)
    build_job.add_argument(
        "--param",
        action="append",
        default=[],
        help="Build parameter in KEY=VALUE format; repeat as needed",
    )
    build_job.set_defaults(handler=cmd_build_job)

    list_queue = subparsers.add_parser("list-queue", help="Inspect the Jenkins build queue")
    add_common_args(list_queue)
    list_queue.set_defaults(handler=cmd_list_queue)

    list_nodes = subparsers.add_parser(
        "list-nodes",
        help="List Jenkins agent nodes (computers) with offline status",
    )
    add_common_args(list_nodes)
    list_nodes.add_argument(
        "--offline",
        action="store_true",
        help="Only show offline (lost) nodes",
    )
    list_nodes.set_defaults(handler=cmd_list_nodes)

    disable_job = subparsers.add_parser("disable-job", help="Disable a Jenkins job")
    add_common_args(disable_job)
    add_job_arg(disable_job)
    disable_job.set_defaults(handler=cmd_disable_job)

    enable_job = subparsers.add_parser("enable-job", help="Enable a Jenkins job")
    add_common_args(enable_job)
    add_job_arg(enable_job)
    enable_job.set_defaults(handler=cmd_enable_job)

    stop_build = subparsers.add_parser("stop-build", help="Stop a running build")
    add_common_args(stop_build)
    add_job_arg(stop_build)
    add_build_number_arg(stop_build)
    stop_build.set_defaults(handler=cmd_stop_build)

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    try:
        return args.handler(args)
    except JenkinsError as err:
        return print_error(err)


if __name__ == "__main__":
    raise SystemExit(main())
