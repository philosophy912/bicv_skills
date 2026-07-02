#!/usr/bin/env python3
"""collect 阶段编排：并发拉每个 job 近 N 小时的失败构建，合并成 builds.json。

编排层 —— 通过 subprocess 调用 jenkins-restapi 的 jenkins_api.py 子命令完成实际
Jenkins 调用，不复制任何 HTTP 代码。失败分类留给 agent（analyze 阶段）。

用法（agent 编排）::

    python3 collect.py --cli <jenkins_api.py 路径> [--system <name>] \
        [--since-hours 24] [--workers 20] [--no-prefilter] [--rundir <dir>]
"""

from __future__ import annotations

import argparse
import concurrent.futures
import datetime
import json
import os
import subprocess
import sys
from collections import Counter
from pathlib import Path
from typing import Any

SKILL_KEY = "jenkins_analysis"
DEFAULT_SKILL_SUBDIR = "jenkins_analysis"
DEFAULT_OUTPUT_ROOT = "~/.bicv/output"
# 这些 color 的 job 在滚动窗口内基本不会产生新构建，collect 默认跳过以减少无效调用：
#   disabled —— job 被禁用；notbuilt —— 从未构建过。
# --no-prefilter 可强制全量扫描（兜底，防 color 与实际构建时间不一致漏报）。
PREFILTER_SKIP_COLORS = frozenset({"disabled", "notbuilt"})


def load_run_root() -> tuple[str, str]:
    """从 ~/.bicv/common.json 解析输出根目录与 skill 子目录；缺失/损坏则回退默认值。"""
    cfg_path = Path.home() / ".bicv" / "common.json"
    root = os.path.expanduser(DEFAULT_OUTPUT_ROOT)
    subdir = DEFAULT_SKILL_SUBDIR
    if cfg_path.exists():
        try:
            cfg = json.loads(cfg_path.read_text(encoding="utf-8-sig"))
            root = os.path.expanduser(cfg.get("output_root", DEFAULT_OUTPUT_ROOT))
            subdir = cfg.get("skills", {}).get(SKILL_KEY, DEFAULT_SKILL_SUBDIR)
        except (json.JSONDecodeError, OSError):
            pass
    return root, subdir


ANALYSIS_CONFIG_PATH = Path.home() / ".bicv" / "jenkins_analysis.json"


def load_since_hours(path: Path | None = None) -> float | None:
    """读 ~/.bicv/jenkins_analysis.json 的 since_hours（>0 的数）；缺失/无效返回 None。"""
    p = path or ANALYSIS_CONFIG_PATH
    if not p.exists():
        return None
    try:
        cfg = json.loads(p.read_text(encoding="utf-8-sig"))
    except (json.JSONDecodeError, OSError):
        return None
    if not isinstance(cfg, dict):
        return None
    val = cfg.get("since_hours")
    if isinstance(val, bool):  # bool 是 int 子类，排除
        return None
    if isinstance(val, (int, float)) and val > 0:
        return float(val)
    return None


def make_rundir(output_root: str, subdir: str) -> str:
    """创建并返回带本地时间戳的运行目录 <root>/<subdir>/YYYY-MM-DD_HHMMSS/（含 logs/）。"""
    ts = datetime.datetime.now().strftime("%Y-%m-%d_%H%M%S")
    rundir = os.path.join(output_root, subdir, ts)
    os.makedirs(os.path.join(rundir, "logs"), exist_ok=True)
    return rundir


def run_jenkins_cli(
    cli: str, subcommand: list[str], system: str | None = None, timeout: float = 180
) -> subprocess.CompletedProcess[str]:
    """subprocess 调用 jenkins_api.py 子命令，返回 CompletedProcess。"""
    cmd = [sys.executable, cli, *subcommand]
    if system:
        cmd += ["--system", system]
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)


def parse_json_envelope(stdout: str) -> Any:
    """解析 jenkins_api.py 的 JSON 信封，返回 ``data`` 字段内容（list 或 dict）。"""
    return json.loads(stdout).get("data")


def should_skip_job(job: dict[str, Any], no_prefilter: bool) -> bool:
    """color 预筛：disabled/notbuilt 默认跳过；no_prefilter=True 时一律不跳。"""
    if no_prefilter:
        return False
    return job.get("color") in PREFILTER_SKIP_COLORS


def collect_one_job(
    cli: str, system: str | None, job_name: str, since_hours: float
) -> tuple[str, Any]:
    """对单个 job 调 list-builds，返回 ``(status, payload)``。

    - ``ok``    —— payload 为失败构建列表（每条已补 ``job`` 字段）
    - ``empty`` —— payload 为 None（窗口内无失败构建）
    - ``error`` —— payload 为错误描述字符串
    """
    try:
        proc = run_jenkins_cli(
            cli,
            [
                "list-builds",
                "--job",
                job_name,
                "--since-hours",
                str(since_hours),
                "--result",
                "!SUCCESS",
                # limit=0 走 jenkins_api 的“不限”分支（不带 tree range），
                # 避免默认 50 在服务端截断后丢失高频 job 窗口内的较早失败
                "--limit",
                "0",
            ],
            system,
        )
    except subprocess.TimeoutExpired:
        return "error", "timeout"
    except Exception as exc:
        return "error", f"{type(exc).__name__}: {exc}"
    if proc.returncode != 0:
        lines = (proc.stderr or proc.stdout or "").strip().splitlines()
        return "error", f"exit {proc.returncode}: {lines[-1] if lines else ''}"
    try:
        data = parse_json_envelope(proc.stdout)
    except (json.JSONDecodeError, AttributeError):
        return "error", "invalid JSON from list-builds"
    if not isinstance(data, list):
        return "error", f"unexpected data shape: {type(data).__name__}"
    if not data:
        return "empty", None
    items = [dict(b, job=job_name) for b in data if isinstance(b, dict)]
    return "ok", items


def cmd_collect(args: argparse.Namespace) -> int:
    output_root, subdir = load_run_root()
    rundir = args.rundir or make_rundir(output_root, subdir)
    os.makedirs(os.path.join(rundir, "logs"), exist_ok=True)
    # since_hours 优先级：命令行 > 配置（~/.bicv/jenkins_analysis.json）> 默认 24
    since = args.since_hours if args.since_hours is not None else (load_since_hours() or 24)

    # 1. list-jobs
    try:
        proc = run_jenkins_cli(args.cli, ["list-jobs"], args.system)
    except subprocess.TimeoutExpired:
        print("error: list-jobs timeout", file=sys.stderr)
        return 1
    if proc.returncode != 0:
        print(f"error: list-jobs failed: {proc.stderr.strip()}", file=sys.stderr)
        return 1
    try:
        envelope = parse_json_envelope(proc.stdout)
    except (json.JSONDecodeError, AttributeError):
        print("error: list-jobs returned invalid JSON", file=sys.stderr)
        return 1
    # list-jobs 信封: data 是 {"jobs": [...]}；非预期形状兜底为空，避免遍历崩
    jobs_raw = envelope.get("jobs", []) if isinstance(envelope, dict) else []
    jobs = jobs_raw if isinstance(jobs_raw, list) else []
    skipped = [j for j in jobs if should_skip_job(j, args.no_prefilter)]
    targets = [j for j in jobs if not should_skip_job(j, args.no_prefilter)]
    target_names = [j.get("name", "") for j in targets if j.get("name")]

    # 2. 并发 list-builds
    builds: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as pool:
        future_map = {
            pool.submit(collect_one_job, args.cli, args.system, name, since): name
            for name in target_names
        }
        for fut in concurrent.futures.as_completed(future_map):
            name = future_map[fut]
            status, payload = fut.result()
            if status == "ok":
                builds.extend(payload)
            elif status == "error":
                errors.append({"job": name, "error": payload})

    builds.sort(key=lambda b: (b.get("job", ""), b.get("number", 0)))
    errors.sort(key=lambda e: e["job"])

    now = datetime.datetime.now()
    start = now - datetime.timedelta(hours=since)
    result = {
        "generated_at": now.strftime("%Y-%m-%dT%H:%M:%S"),
        "window": {
            "start": start.strftime("%Y-%m-%dT%H:%M:%S"),
            "end": now.strftime("%Y-%m-%dT%H:%M:%S"),
        },
        "system": args.system or "default",
        "since_hours": since,
        "prefilter": {
            "enabled": not args.no_prefilter,
            "skipped_count": len(skipped),
            "skipped_colors": sorted({j.get("color") for j in skipped}),
        },
        "builds": builds,
        "errors": errors,
    }
    out_path = os.path.join(rundir, "builds.json")
    with open(out_path, "w", encoding="utf-8") as fh:
        json.dump(result, fh, ensure_ascii=False, indent=2)

    by_result = Counter(b.get("result") for b in builds)
    print(f"rundir={rundir}")
    print(f"jobs_total={len(jobs)} prefilter_skipped={len(skipped)} scanned={len(target_names)}")
    print(f"failed_builds={len(builds)} errors={len(errors)} by_result={dict(by_result)}")
    print(f"jobs_with_failures={len({b.get('job') for b in builds})}")
    print(f"written={out_path}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="collect: 并发收集 Jenkins 近 N 小时失败构建为 builds.json"
    )
    parser.add_argument("--cli", required=True, help="jenkins-restapi 的 jenkins_api.py 路径")
    parser.add_argument("--system", default=None, help="Jenkins 实例名（透传给 jenkins_api.py）")
    parser.add_argument(
        "--since-hours",
        type=float,
        default=None,
        help="滚动窗口小时数；缺省读 ~/.bicv/jenkins_analysis.json 的 since_hours，再缺省 24",
    )
    parser.add_argument("--workers", type=int, default=20, help="list-builds 并发数（默认 20）")
    parser.add_argument(
        "--no-prefilter",
        action="store_true",
        help="禁用 color 预筛，全量扫描（兜底，防漏报）",
    )
    parser.add_argument(
        "--rundir",
        default=None,
        help="复用已有运行目录；缺省则新建 <root>/<subdir>/<时间戳>/",
    )
    return parser


def main() -> int:
    return cmd_collect(build_parser().parse_args())


if __name__ == "__main__":
    raise SystemExit(main())
