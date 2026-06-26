#!/usr/bin/env python3
"""Render bug analysis JSON into a Markdown report (tables).

把 ``bug_analysis.py`` 的 submissions / overdue 子命令输出的 JSON 渲染成
表格形式的 Markdown 报告。只吃 JSON、不连库、不依赖 matplotlib，与
``render_charts.py``（出 PNG）职责分离、可独立运行。

报告内容（表格）：
    一、本周提交：按提交人 + 按项目（数量、占比）
    二、超期未处理：按指派人 + 超期明细（含缺陷 ID，按天数降序）

用法：
    render_report.py --submissions sub.json --overdue ovd.json [--out <dir>]

依赖：
    ~/.bicv/common.json（output_root + skills 子目录映射）
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

COMMON_CONFIG_NAME = "common.json"
SKILL_NAME = "bug_daily_analysis"
DEFAULT_OUTPUT_SUBDIR = "bug_daily_analysis"


class ReportError(Exception):
    """报告生成错误（配置/IO）。"""


# ---------------------------------------------------------------------------
# Config / IO
# ---------------------------------------------------------------------------


def _load_common_config() -> dict[str, Any]:
    """从 ~/.bicv/common.json 加载配置。"""
    path = Path.home() / ".bicv" / COMMON_CONFIG_NAME
    if not path.exists():
        raise ReportError(
            f"配置文件不存在: {path}\n请创建 ~/.bicv/{COMMON_CONFIG_NAME}，至少包含 output_root"
        )
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ReportError(f"配置文件 JSON 格式错误: {path}\n{exc}") from exc


def resolve_output_dir(custom: str | None) -> Path:
    """解析输出目录：--out 优先，否则 common.json 的 output_root/skills[bug_daily_analysis]。"""
    if custom:
        out_dir = Path(custom).expanduser()
    else:
        cfg = _load_common_config()
        root = cfg.get("output_root")
        if not root:
            raise ReportError(f"[{COMMON_CONFIG_NAME}] 缺少 output_root")
        subdir = (cfg.get("skills", {}) or {}).get(SKILL_NAME, DEFAULT_OUTPUT_SUBDIR)
        out_dir = Path(str(root)).expanduser() / str(subdir)
    out_dir.mkdir(parents=True, exist_ok=True)
    return out_dir


def read_json_file(path_str: str) -> dict[str, Any]:
    """读取并解析输入 JSON 文件。"""
    path = Path(path_str).expanduser()
    if not path.exists():
        raise ReportError(f"输入文件不存在: {path}")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ReportError(f"JSON 解析失败: {path}\n{exc}") from exc


# ---------------------------------------------------------------------------
# Pure data helpers
# ---------------------------------------------------------------------------


def merge_counter(*counters: dict[str, Any] | None) -> dict[str, int]:
    """合并多个 {name: count}，同名累加（跨禅道/Redmine 系统）。"""
    out: dict[str, int] = {}
    for counter in counters:
        for key, val in (counter or {}).items():
            out[key] = out.get(key, 0) + int(val)
    return out


def _overdue_rows(data: dict[str, Any]) -> list[dict[str, Any]]:
    """合并禅道/Redmine 超期明细（含缺陷 ID Z-/R- 前缀），按超期天数降序。"""
    specs = [
        ("zentao", "Z", "id", "projectName", "module", "assignedTo"),
        ("redmine", "R", "issue_id", "project_name", "subject", "assigned_to_name"),
    ]
    rows: list[dict[str, Any]] = []
    for sys_key, prefix, id_key, proj_key, mod_key, assign_key in specs:
        section = data.get(sys_key) or {}
        items = section.get("bugs") or section.get("issues") or []
        for item in items:
            raw_id = item.get(id_key, "")
            bug_id = f"{prefix}-{raw_id}" if raw_id not in ("", None) else ""
            days = item.get("days_since_action", "")
            try:
                days_val = int(days)
            except (TypeError, ValueError):
                days_val = 0
            rows.append(
                {
                    "id": bug_id,
                    "project": item.get(proj_key, ""),
                    "module": item.get(mod_key, ""),
                    "assignee": item.get(assign_key, ""),
                    "days": days_val,
                }
            )
    rows.sort(key=lambda r: (-r["days"], str(r["assignee"]), str(r["project"])))
    return rows


def _short_window(data: dict[str, Any]) -> str:
    """从 submissions 的 window 提取 'MM-DD~MM-DD' 短串。"""
    window = data.get("window") or {}

    def _md(value: Any) -> str:
        s = str(value or "")[:10]
        return s[5:] if len(s) >= 10 else s

    start, end = _md(window.get("start")), _md(window.get("end"))
    return f"{start}~{end}" if start and end else ""


def _fmt_pct(n: int, total: int) -> str:
    return f"{n / total:.0%}" if total else "0%"


# ---------------------------------------------------------------------------
# Report builder
# ---------------------------------------------------------------------------


def build_report(sub_data: dict[str, Any] | None, ovd_data: dict[str, Any] | None) -> str:
    """生成 Markdown 报告字符串（提交按人/项目 + 超期按人/明细含缺陷 ID）。"""
    lines: list[str] = ["# 缺陷分析报告", ""]

    window = _short_window(sub_data or {})
    lines.append(f"**时间窗口**：{window}" if window else "**时间窗口**：—")
    lines.append(f"**生成时间**：{datetime.now().strftime('%Y-%m-%d %H:%M')}")

    if sub_data:
        zt = sub_data.get("zentao") or {}
        rm = sub_data.get("redmine") or {}
        sub_total = int(zt.get("total", 0)) + int(rm.get("total", 0))
        lines += ["", "## 一、本周提交情况", ""]
        lines.append(
            f"测试组共提交 **{sub_total}** 条缺陷"
            f"（禅道 {zt.get('total', 0)} / Redmine {rm.get('total', 0)}）。"
        )

        by_user = merge_counter(zt.get("by_user"), rm.get("by_user"))
        lines += ["", "### 按提交人", "", "| 排名 | 提交人 | 数量 | 占比 |", "|---|---|---|---|"]
        for i, (u, c) in enumerate(sorted(by_user.items(), key=lambda kv: (-kv[1], kv[0])), 1):
            lines.append(f"| {i} | {u} | {c} | {_fmt_pct(c, sub_total)} |")

        by_proj = merge_counter(zt.get("by_project"), rm.get("by_project"))
        lines += ["", "### 按项目", "", "| 排名 | 项目 | 数量 | 占比 |", "|---|---|---|---|"]
        for i, (p, c) in enumerate(sorted(by_proj.items(), key=lambda kv: (-kv[1], kv[0])), 1):
            lines.append(f"| {i} | {p} | {c} | {_fmt_pct(c, sub_total)} |")

    if ovd_data:
        ozt = ovd_data.get("zentao") or {}
        orm = ovd_data.get("redmine") or {}
        ovd_total = int(ozt.get("total", 0)) + int(orm.get("total", 0))
        lines += ["", "## 二、超期未处理（已过滤停用项目）", ""]
        lines.append(
            f"当前超期 **{ovd_total}** 条"
            f"（禅道 {ozt.get('total', 0)} / Redmine {orm.get('total', 0)}，"
            f"阈值 > {ovd_data.get('overdue_days', 7)} 天无 action）。"
        )
        lines += [
            "",
            "> 已排除停用项目（`project.is_active=0`）的陈年缺陷，未收录项目按在研保留。",
        ]

        ovd_by_user = merge_counter(ozt.get("by_user"), orm.get("by_user"))
        lines += ["", "### 按指派人", "", "| 指派人 | 超期条数 |", "|---|---|"]
        for u, c in sorted(ovd_by_user.items(), key=lambda kv: (-kv[1], kv[0])):
            lines.append(f"| {u} | {c} |")

        rows = _overdue_rows(ovd_data)
        lines += [
            "",
            f"### 超期明细（{len(rows)} 条，按超期天数降序）",
            "",
            "| 缺陷ID | 项目 | 模块/主题 | 指派人 | 超期天数 |",
            "|---|---|---|---|---|",
        ]
        for r in rows:
            lines.append(
                f"| {r['id']} | {r['project']} | {r['module']} | {r['assignee']} | {r['days']} |"
            )

    lines.append("")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def cmd_report(args: argparse.Namespace) -> int:
    """入口：解析目录 → 读 JSON → 生成 MD → 落盘 → 打印 JSON 信封。"""
    try:
        out_dir = resolve_output_dir(args.out)
    except ReportError as exc:
        print(f"输出目录错误: {exc}", file=sys.stderr)
        return 1

    if not args.submissions and not args.overdue:
        print("错误: 至少需要 --submissions 或 --overdue 之一", file=sys.stderr)
        return 1

    try:
        sub_data = read_json_file(args.submissions) if args.submissions else None
        ovd_data = read_json_file(args.overdue) if args.overdue else None
    except ReportError as exc:
        print(f"输入错误: {exc}", file=sys.stderr)
        return 1

    md = build_report(sub_data, ovd_data)
    date_tag = datetime.now().strftime("%Y%m%d")
    out_path = out_dir / f"report_{date_tag}.md"
    out_path.write_text(md, encoding="utf-8")

    envelope = {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "report_path": str(out_path),
    }
    print(json.dumps(envelope, ensure_ascii=False, indent=2))
    return 0


def build_parser() -> argparse.ArgumentParser:
    """构建 CLI 参数解析器。"""
    parser = argparse.ArgumentParser(
        description="把 bug_analysis 的 JSON 渲染成 Markdown 表格报告（含缺陷 ID）",
    )
    parser.add_argument("--submissions", help="submissions 子命令输出的 JSON 文件路径")
    parser.add_argument("--overdue", help="overdue 子命令输出的 JSON 文件路径")
    parser.add_argument(
        "--out",
        help="输出目录（默认: common.json 的 output_root/bug_daily_analysis）",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """入口：解析参数 → 生成报告。"""
    args = build_parser().parse_args(argv)
    return cmd_report(args)


if __name__ == "__main__":
    raise SystemExit(main())
