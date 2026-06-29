#!/usr/bin/env python3
"""fetch 阶段编排：读 builds.json，并发拉每条失败构建的 console log 到 logs/。

编排层 —— 通过 subprocess 调用 jenkins_api.py 的 ``get-console-log --raw``，
不复制 HTTP 代码。单条日志拉取失败不中断整体，记 ``fetch_error`` 后由 analyze 归 unknown。

用法（agent 编排）::

    python3 fetch.py --cli <jenkins_api.py 路径> --rundir <run-dir> \
        [--system <name>] [--workers 20]
"""

from __future__ import annotations

import argparse
import concurrent.futures
import json
import os
import subprocess
import sys
from typing import Any

from collect import run_jenkins_cli  # 复用编排层公共 helper


def log_filename(job: str, number: Any) -> str:
    """落盘 key：job 名里的 ``/`` 替换为 ``__``，job 与 number 间用 ``__`` 连接。

    job 名内原有的单下划线保留，仅以双下划线作分隔符。
    """
    safe = str(job).replace("/", "__")
    return f"{safe}__{number}.log"


def fetch_one(
    cli: str, system: str | None, build: dict[str, Any]
) -> tuple[tuple[str, Any], bool, str]:
    """拉单条构建日志，返回 ``((job, number), ok, payload)``。

    ok=True 时 payload 为日志原文；ok=False 时 payload 为错误描述。fetch_one 不写
    文件，由调用方决定落盘，便于测试。
    """
    job = build.get("job")
    number = build.get("number")
    if job is None or number is None:
        return (job, number), False, "build 缺少 'job' 或 'number' 字段"
    try:
        proc = run_jenkins_cli(
            cli,
            ["get-console-log", "--job", job, "--number", str(number), "--raw"],
            system,
            timeout=300,
        )
    except subprocess.TimeoutExpired:
        return (job, number), False, "timeout"
    except Exception as exc:
        return (job, number), False, f"{type(exc).__name__}: {exc}"
    if proc.returncode != 0:
        lines = (proc.stderr or proc.stdout or "").strip().splitlines()
        return (job, number), False, f"exit {proc.returncode}: {lines[-1] if lines else ''}"
    return (job, number), True, proc.stdout


def cmd_fetch(args: argparse.Namespace) -> int:
    rundir = args.rundir
    builds_file = os.path.join(rundir, "builds.json")
    logdir = os.path.join(rundir, "logs")
    if not os.path.isfile(builds_file):
        print(f"error: builds.json not found at {builds_file}", file=sys.stderr)
        return 1
    os.makedirs(logdir, exist_ok=True)
    with open(builds_file, encoding="utf-8") as fh:
        data = json.load(fh)
    builds = data.get("builds", [])
    if not isinstance(builds, list):
        print("error: builds.json has no builds[] list", file=sys.stderr)
        return 1

    results: dict[tuple[str, Any], tuple[bool, str]] = {}
    errs: list[tuple[str, Any, str]] = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as pool:
        future_map = {pool.submit(fetch_one, args.cli, args.system, b): b for b in builds}
        for fut in concurrent.futures.as_completed(future_map):
            (job, number), ok, payload = fut.result()
            results[(job, number)] = (ok, payload)
            if ok:
                with open(
                    os.path.join(logdir, log_filename(job, number)), "w", encoding="utf-8"
                ) as fh:
                    fh.write(payload)
            else:
                errs.append((job, number, payload))

    # 回写 builds.json：成功的补 log_file，失败的记 fetch_error（analyze 归 unknown）
    okn = errn = 0
    for b in builds:
        job = b.get("job")
        number = b.get("number")
        # 脏数据（缺 job/number）标记 fetch_error 跳过，不中断整批回写
        if job is None or number is None:
            b["fetch_error"] = True
            errn += 1
            continue
        key = (job, number)
        ok, _ = results.get(key, (False, "not run"))
        if ok:
            b.pop("fetch_error", None)
            b["log_file"] = log_filename(job, number)
            okn += 1
        else:
            b["fetch_error"] = True
            errn += 1
    data["builds"] = builds
    with open(builds_file, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=2)

    print(f"fetched ok={okn} err={errn}")
    for fn in sorted(os.listdir(logdir)):
        print(f"  {fn}: {os.path.getsize(os.path.join(logdir, fn))} bytes")
    for job, number, info in sorted(errs):
        print(f"  ERR {log_filename(job, number)}: {info}", file=sys.stderr)
    print(f"updated={builds_file}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="fetch: 并发拉取 builds.json 中失败构建的 console log 到 logs/"
    )
    parser.add_argument("--cli", required=True, help="jenkins-restapi 的 jenkins_api.py 路径")
    parser.add_argument("--rundir", required=True, help="运行目录（含 builds.json）")
    parser.add_argument("--system", default=None, help="Jenkins 实例名（透传给 jenkins_api.py）")
    parser.add_argument("--workers", type=int, default=20, help="get-console-log 并发数（默认 20）")
    return parser


def main() -> int:
    return cmd_fetch(build_parser().parse_args())


if __name__ == "__main__":
    raise SystemExit(main())
