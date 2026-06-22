#!/usr/bin/env python3
"""Single-entry Jenkins Remote API script."""

from __future__ import annotations

import argparse
import base64
import json
import sys
from pathlib import Path
from typing import Any
from urllib import error, parse, request

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
from shared.system_config import (
    ServiceError,
    ServiceTarget,
    resolve_target,
    print_error,
    print_system,
    print_json_result,
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
        token = base64.b64encode(f"{target.auth[0]}:{target.auth[1]}".encode("utf-8")).decode("ascii")
        req_headers["Authorization"] = f"Basic {token}"

    if include_crumb:
        crumb = get_crumb(target)
        if crumb is not None:
            req_headers[crumb[0]] = crumb[1]

    req = request.Request(url, data=body, headers=req_headers, method=method.upper())
    try:
        with request.urlopen(req) as response:
            return response.read().decode("utf-8")
    except error.HTTPError as exc:
        response_text = exc.read().decode("utf-8", errors="replace")
        raise JenkinsError("Request failed", status_code=exc.code, response_text=response_text) from exc
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
    parser.add_argument("--system", help="Configured Jenkins system name; defaults to default_system")
    parser.add_argument("--user", help="Auth in username:token or username:password format")


def add_job_arg(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--job", required=True, help="Jenkins job name; folders use path-like names")


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

    print_system(target)
    print(f"Found {len(jobs)} jobs:\n")
    for job in jobs:
        print(f"- [{job.get('color', 'unknown')}] {job.get('name', 'N/A')}")
        print(f"  {job.get('url', 'N/A')}")
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
    print_system(target)
    print(text)
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
    path = f"/{encode_job_segment(args.job)}/buildWithParameters" if params else f"/{encode_job_segment(args.job)}/build"
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
    print_system(target)
    print(f"Triggered build for job: {args.job}")
    if response.strip():
        print(response.strip())
    return 0


def cmd_list_queue(args: argparse.Namespace) -> int:
    target = _target(args)
    return print_json_result(target, request_json("GET", target, "/queue/api/json"))


def cmd_disable_job(args: argparse.Namespace) -> int:
    target = _target(args)
    path = f"/{encode_job_segment(args.job)}/disable"
    request_text("POST", target, path, include_crumb=True)
    print_system(target)
    print(f"Disabled job: {args.job}")
    return 0


def cmd_enable_job(args: argparse.Namespace) -> int:
    target = _target(args)
    path = f"/{encode_job_segment(args.job)}/enable"
    request_text("POST", target, path, include_crumb=True)
    print_system(target)
    print(f"Enabled job: {args.job}")
    return 0


def cmd_stop_build(args: argparse.Namespace) -> int:
    target = _target(args)
    path = f"/{encode_job_segment(args.job)}/{parse.quote(args.number, safe='')}/stop"
    request_text("POST", target, path, include_crumb=True)
    print_system(target)
    print(f"Requested stop for {args.job} build {args.number}")
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
    get_console_log.set_defaults(handler=cmd_get_console_log)

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
