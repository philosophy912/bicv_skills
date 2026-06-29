#!/usr/bin/env python3
"""report 阶段编排：合并 builds.json + agent 的 analyses.json（+ 可选节点检查），
拼装 report.json，并按 assets/report-template.md 渲染 report.md。

判定（category/evidence 等）由 agent 在 analyze 阶段写入 analyses.json，本脚本只做
合并与渲染——不调 LLM、不做模式匹配。

analyses.json 格式（agent 写，每条对应 builds.json 的一条失败构建）::

    [
      {"job": "APP", "number": 7, "category": "scm",
       "confidence": "high", "evidence": "...", "log_excerpt": "..."}
    ]

用法（agent 编排）::

    python3 report.py --rundir <run-dir> [--analyses <path>] [--cli <jenkins_api.py>] [--system <name>]
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from collections import Counter, defaultdict
from typing import Any

from collect import parse_json_envelope, run_jenkins_cli  # 复用编排层公共 helper

REPRESENTATIVE_LIMIT = 5
CATEGORIES = ("scm", "compile", "other", "unknown")


def load_analyses(path: str) -> dict[tuple[str, Any], dict[str, Any]]:
    """读 analyses.json，返回 ``{(job, number): entry}``；文件不存在返回空 dict。"""
    if not os.path.isfile(path):
        return {}
    with open(path, encoding="utf-8") as fh:
        data = json.loads(fh.read())
    if not isinstance(data, list):
        raise ValueError("analyses.json must be a list of objects")
    out: dict[tuple[str, Any], dict[str, Any]] = {}
    for entry in data:
        if isinstance(entry, dict) and "job" in entry and "number" in entry:
            out[(entry["job"], entry["number"])] = entry
    return out


def merge_builds(
    builds: list[dict[str, Any]], analyses: dict[tuple[str, Any], dict[str, Any]]
) -> list[dict[str, Any]]:
    """把 analyses 判定合并进 builds；缺失判定的条目归 unknown。"""
    for b in builds:
        entry = analyses.get((b["job"], b["number"]))
        if entry:
            # 归一化：agent 写入的非标准 category（如 'infra'）统一归 unknown，
            # 保证 by_category 四类之和 == total_failed，统计自洽
            category = entry.get("category", "unknown")
            b["category"] = category if category in CATEGORIES else "unknown"
            b["confidence"] = entry.get("confidence", "low")
            b["evidence"] = entry.get("evidence", "")
            b["log_excerpt"] = entry.get("log_excerpt", "")
        else:
            b["category"] = "unknown"
            b["confidence"] = "low"
            b["evidence"] = "未判定（analyses.json 缺该条）"
            b["log_excerpt"] = ""
    return builds


def pick_representatives(
    builds: list[dict[str, Any]], limit: int = REPRESENTATIVE_LIMIT
) -> list[dict[str, Any]]:
    """代表条目选取：每个 job 至少 1 条，再按 job 失败数从多到少补齐到 limit。

    解决「同 job 大量重复失败挤掉其它 job 不同失败模式」的代表性问题：先保证每个
    job 出现一次，名额富余时优先给失败数多的 job 多列。
    """
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for b in builds:
        groups[b["job"]].append(b)
    for g in groups.values():
        g.sort(key=lambda b: b.get("number", 0))
    picked: list[dict[str, Any]] = []
    # 第一轮：每个 job 取 1 条（job 字典序）
    for job in sorted(groups):
        if len(picked) >= limit:
            break
        picked.append(groups[job][0])
    # 第二轮：按 job 失败数降序、再按 job 名，补齐剩余名额
    if len(picked) >= limit:
        return picked
    order = sorted(groups, key=lambda j: (-len(groups[j]), j))
    for job in order:
        for b in groups[job][1:]:
            if len(picked) >= limit:
                break
            picked.append(b)
        if len(picked) >= limit:
            break
    return picked


def fetch_nodes(cli: str, system: str | None) -> tuple[int, list[dict], int] | None:
    """调 list-nodes，返回 (total, 系统自发掉线列表, 人为临时离线数)；失败返回 None。"""
    try:
        proc = run_jenkins_cli(cli, ["list-nodes"], system)
    except subprocess.TimeoutExpired:
        return None
    except Exception:
        return None
    if proc.returncode != 0:
        return None
    try:
        data = parse_json_envelope(proc.stdout)
    except (json.JSONDecodeError, AttributeError):
        return None
    if not isinstance(data, dict):
        return None
    computers = data.get("computers", []) if isinstance(data.get("computers"), list) else []
    sys_off = [c for c in computers if c.get("offline") and not c.get("temporarilyOffline")]
    manual = [c for c in computers if c.get("offline") and c.get("temporarilyOffline")]
    return data.get("total", len(computers)), sys_off, len(manual)


def _fmt_window(window: dict[str, str]) -> str:
    s = window.get("start", "").replace("T", " ")
    e = window.get("end", "").replace("T", " ")
    return f"{s} ~ {e}"


def render_report_md(report: dict[str, Any], rundir: str) -> str:
    """按 assets/report-template.md 渲染 report.md 文本。"""
    summary = report["summary"]
    bc = summary["by_category"]
    builds = report["builds"]
    window = report.get("window", {})
    nodes = report.get("nodes")
    since = report.get("since_hours", 24)
    line: list[str] = []

    line.append("# Jenkins 失败构建分析报告\n")
    line.append(f"**时间窗口**：{_fmt_window(window)}（滚动 {since}h）")
    line.append(f"**生成时间**：{report.get('generated_at', '')}")
    line.append(f"**Jenkins 实例**：{report.get('system', 'default')}\n")

    line.append("## 顶部统计\n")
    line.append("| 总失败数 | scm | compile | other | unknown | collect 错误 |")
    line.append("|---|---|---|---|---|---|")
    line.append(
        f"| {summary['total_failed']} | {bc['scm']} | {bc['compile']} | {bc['other']} | "
        f"{bc['unknown']} | {summary['errors']} |\n"
    )
    line.append(
        "> `总失败数 = scm + compile + other + unknown`；`collect 错误` 单列，不计入失败。\n"
    )

    cat_builds = {
        c: sorted(
            [b for b in builds if b.get("category") == c], key=lambda b: (b["job"], b["number"])
        )
        for c in CATEGORIES
    }

    # 一、scm（全列）
    scm = cat_builds["scm"]
    line.append(f"## 一、scm 失败明细（{len(scm)} 条）\n")
    if scm:
        line.append("| 序 | Job | #构建 | 判定依据 | 构建链接 |")
        line.append("|---|---|---|---|---|")
        for i, b in enumerate(scm, 1):
            line.append(
                f"| {i} | {b['job']} | #{b['number']} | {b['evidence']} | [打开]({b.get('url', '')}) |"
            )
    else:
        line.append("（无）")
    line.append("")

    # 二/三/四：compile / other / unknown（各最多 REPRESENTATIVE_LIMIT 条代表）
    meta = [("二", "compile 失败"), ("三", "other 失败"), ("四", "unknown")]
    for prefix, name in meta:
        cat = name.replace(" 失败", "")
        lst = cat_builds[cat]
        suffix = (
            f"，此处列代表 {REPRESENTATIVE_LIMIT} 条" if len(lst) > REPRESENTATIVE_LIMIT else ""
        )
        line.append(f"## {prefix}、{name}（{len(lst)} 条{suffix}）\n")
        if lst:
            reps = pick_representatives(lst)
            line.append("| Job | #构建 | 判定依据 | 构建链接 |")
            line.append("|---|---|---|---|")
            for b in reps:
                line.append(
                    f"| {b['job']} | #{b['number']} | {b['evidence']} | [打开]({b.get('url', '')}) |"
                )
            if len(lst) > len(reps):
                line.append(f"\n> 完整 {len(lst)} 条见 `report.json`。")
        else:
            line.append("（无）")
        line.append("")

    # 节点掉线检查
    line.append("## 节点掉线检查\n")
    if nodes is None:
        line.append("> 未执行节点检查（未提供 --cli 或 list-nodes 失败）。\n")
    else:
        line.append(
            "> 仅报**系统自发掉线**（`offline==true` 且 `temporarilyOffline==false`）；"
            "人为临时离线（`temporarilyOffline==true`）已忽略。来源：`jenkins_api.py list-nodes`（一次快照）。\n"
        )
        line.append("| 总节点 | 系统自发掉线 | 人为临时离线（忽略） |")
        line.append("|---|---|---|")
        line.append(
            f"| {nodes['total']} | {len(nodes['details'])} | {nodes['manual_offline_count']} |\n"
        )
        line.append("系统自发掉线节点明细：\n")
        if nodes["details"]:
            line.append("| 节点 | 掉线原因 | 执行器数 |")
            line.append("|---|---|---|")
            for n in nodes["details"]:
                line.append(f"| {n['name']} | {n['offlineCauseReason']} | {n['numExecutors']} |")
        else:
            line.append("（无系统自发掉线节点）")
        line.append("")

    # 产物路径
    line.append("## 产物路径\n")
    line.append(f"- 汇总 JSON：`{rundir}/report.json`")
    line.append(f"- 本报告：`{rundir}/report.md`")
    line.append(f"- 失败构建清单：`{rundir}/builds.json`")
    line.append(f"- 日志目录：`{rundir}/logs/`（每条 `<job>__<number>.log`）")
    return "\n".join(line) + "\n"


def cmd_report(args: argparse.Namespace) -> int:
    rundir = args.rundir
    builds_file = os.path.join(rundir, "builds.json")
    if not os.path.isfile(builds_file):
        print(f"error: builds.json not found at {builds_file}", file=sys.stderr)
        return 1
    with open(builds_file, encoding="utf-8") as fh:
        builds_data = json.load(fh)
    builds = builds_data.get("builds", [])
    if not isinstance(builds, list):
        print("error: builds.json has no builds[] list", file=sys.stderr)
        return 1

    analyses_path = args.analyses or os.path.join(rundir, "analyses.json")
    try:
        analyses = load_analyses(analyses_path)
    except (json.JSONDecodeError, ValueError) as exc:
        print(f"error: analyses.json invalid: {exc}", file=sys.stderr)
        return 1
    merge_builds(builds, analyses)

    # 节点检查（可选）
    nodes_section: dict[str, Any] | None = None
    if args.cli:
        result = fetch_nodes(args.cli, args.system)
        if result is not None:
            total, sys_off, manual = result
            nodes_section = {
                "total": total,
                "details": [
                    {
                        "name": c.get("name"),
                        "offlineCauseReason": c.get("offlineCauseReason", ""),
                        "numExecutors": c.get("numExecutors"),
                    }
                    for c in sys_off
                ],
                "manual_offline_count": manual,
            }

    cat = Counter(b.get("category") for b in builds)
    summary = {
        "total_failed": len(builds),
        "by_category": {c: cat.get(c, 0) for c in CATEGORIES},
        "errors": len(builds_data.get("errors", [])),
    }
    report = {
        "generated_at": builds_data.get("generated_at", ""),
        "window": builds_data.get("window", {"start": "", "end": ""}),
        "system": builds_data.get("system", "default"),
        "since_hours": builds_data.get("since_hours", 24),
        "summary": summary,
        "builds": builds,
    }
    if nodes_section is not None:
        report["nodes"] = nodes_section

    with open(os.path.join(rundir, "report.json"), "w", encoding="utf-8") as fh:
        json.dump(report, fh, ensure_ascii=False, indent=2)
    md = render_report_md(report, rundir)
    with open(os.path.join(rundir, "report.md"), "w", encoding="utf-8") as fh:
        fh.write(md)

    print(f"summary: total={summary['total_failed']} by_category={summary['by_category']}")
    if nodes_section is not None:
        print(
            f"nodes: total={nodes_section['total']} "
            f"sys_offline={len(nodes_section['details'])} manual={nodes_section['manual_offline_count']}"
        )
    print(f"written: {rundir}/report.json + report.md")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="report: 合并 builds + analyses 渲染 report.json/report.md"
    )
    parser.add_argument("--rundir", required=True, help="运行目录（含 builds.json）")
    parser.add_argument(
        "--analyses", default=None, help="analyses.json 路径；缺省取 <rundir>/analyses.json"
    )
    parser.add_argument("--cli", default=None, help="jenkins_api.py 路径；提供则附带节点掉线检查")
    parser.add_argument("--system", default=None, help="Jenkins 实例名（透传给 jenkins_api.py）")
    return parser


def main() -> int:
    return cmd_report(build_parser().parse_args())


if __name__ == "__main__":
    raise SystemExit(main())
