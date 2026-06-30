#!/usr/bin/env python3
"""render_email.py — 把 bug_analysis 各 JSON 渲染成自包含 HTML 邮件正文。

吃 submissions/overdue/severe/closures 四份 JSON + render_charts 的图清单（envelope），
产单个 HTML 文件。图片以 base64 直接内嵌进 HTML（data URI），邮件自包含、
email skill 的 send --html 可直接发送、web 邮箱打开即见图。

五块内容：
    一、提交情况        按提交人/项目（数量+占比）+ 零提交点名
    二、严重-本周       本组本周提交的严重缺陷明细（C-a）
    三、严重-全库未关闭 全库当前未关闭的严重缺陷（C-b）
    四、跟踪不及时      overdue 明细表（纯表格，不出图，给人对质用）
    五、本周关闭        本组本周关闭的缺陷，按人/项目

用法：
    render_email.py --submissions sub.json --overdue ovd.json \\
        --severe sev.json --closures cls.json --charts charts.json [--out <dir>]

依赖：
    ~/.bicv/common.json（output_root + skills 子目录映射）
    不连数据库、不依赖 matplotlib。

兼容性：base64 内嵌图在 QQ/网易/Gmail 等主流 web 邮箱正常显示；Outlook 桌面版
可能屏蔽 data URI 图，若需最强兼容可后续改走 email skill 的 CID related 内嵌。
"""

from __future__ import annotations

import argparse
import base64
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

COMMON_CONFIG_NAME = "common.json"
SKILL_NAME = "bug_analysis"
DEFAULT_OUTPUT_SUBDIR = "bug_analysis"

_IMG_MIME = {
    "png": "image/png",
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "gif": "image/gif",
}


class RenderError(Exception):
    """渲染过程错误（配置/IO）。"""


# ---------------------------------------------------------------------------
# Config / IO
# ---------------------------------------------------------------------------


def _load_common_config() -> dict[str, Any]:
    path = Path.home() / ".bicv" / COMMON_CONFIG_NAME
    if not path.exists():
        raise RenderError(
            f"配置文件不存在: {path}\n请创建 ~/.bicv/{COMMON_CONFIG_NAME}，至少包含 output_root"
        )
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise RenderError(f"配置文件 JSON 格式错误: {path}\n{exc}") from exc


def resolve_output_dir(custom: str | None) -> Path:
    if custom:
        out_dir = Path(custom).expanduser()
    else:
        cfg = _load_common_config()
        root = cfg.get("output_root")
        if not root:
            raise RenderError(f"[{COMMON_CONFIG_NAME}] 缺少 output_root")
        subdir = (cfg.get("skills", {}) or {}).get(SKILL_NAME, DEFAULT_OUTPUT_SUBDIR)
        out_dir = Path(str(root)).expanduser() / str(subdir)
    out_dir.mkdir(parents=True, exist_ok=True)
    return out_dir


def read_json_file(path_str: str) -> dict[str, Any]:
    path = Path(path_str).expanduser()
    if not path.exists():
        raise RenderError(f"输入文件不存在: {path}")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise RenderError(f"JSON 解析失败: {path}\n{exc}") from exc


# ---------------------------------------------------------------------------
# Pure data helpers（不依赖 HTML，便于单测）
# ---------------------------------------------------------------------------


def merge_counter(*counters: dict[str, Any] | None) -> dict[str, int]:
    out: dict[str, int] = {}
    for counter in counters:
        for key, val in (counter or {}).items():
            out[key] = out.get(key, 0) + int(val)
    return out


def sort_desc(counter: dict[str, int]) -> list[tuple[str, int]]:
    return sorted(counter.items(), key=lambda kv: (-int(kv[1]), kv[0]))


def _fmt_pct(n: int, total: int) -> str:
    return f"{n / total:.0%}" if total else "0%"


# 禅道 severity 数字 → SABC（DB 实证：1-4，1=最严重=S）
_ZT_SEVERITY_LABEL = {1: "S", 2: "A", 3: "B", 4: "C"}


def _severity_label(row: dict[str, Any], kind: str) -> str:
    """严重程度显示：禅道 severity→SABC；Redmine priority_name 取末尾字母 ABCD。"""
    if kind == "zt":
        raw = row.get("severity", "")
        try:
            return _ZT_SEVERITY_LABEL.get(int(raw), str(raw))
        except (TypeError, ValueError):
            return str(raw)
    # Redmine「立刻-A」→ A
    name = str(row.get("priority_name", ""))
    return name[-1] if name else ""


def _short_window(data: dict[str, Any]) -> str:
    window = data.get("window") or {}

    def _md(value: Any) -> str:
        s = str(value or "")[:10]
        return s[5:] if len(s) >= 10 else s

    start, end = _md(window.get("start")), _md(window.get("end"))
    return f"{start}~{end}" if start and end else ""


def _overdue_rows(data: dict[str, Any]) -> list[dict[str, Any]]:
    """合并禅道/Redmine 超期明细（含 Z-/R- 前缀），按超期天数降序。"""
    specs = [
        ("zentao", "Z", "id", "projectName", "title", "assignedTo", "zt", "last_user_action"),
        (
            "redmine",
            "R",
            "issue_id",
            "project_name",
            "subject",
            "assigned_to_name",
            "rm",
            "last_user_action",
        ),
    ]
    rows: list[dict[str, Any]] = []
    for sys_key, prefix, id_key, proj_key, title_key, assign_key, kind, last_key in specs:
        section = data.get(sys_key) or {}
        items = section.get("bugs") or section.get("issues") or []
        for item in items:
            raw_id = item.get(id_key, "")
            bug_id = f"{prefix}-{raw_id}" if raw_id not in ("", None) else ""
            try:
                days_val = int(item.get("days_since_action", 0))
            except (TypeError, ValueError):
                days_val = 0
            rows.append(
                {
                    "id": bug_id,
                    "project": item.get(proj_key, ""),
                    "title": item.get(title_key, ""),
                    "severity": _severity_label(item, kind),
                    "assignee": item.get(assign_key, ""),
                    "last_action": item.get(last_key, ""),
                    "days": days_val,
                }
            )
    rows.sort(key=lambda r: (-r["days"], str(r["assignee"]), str(r["project"])))
    return rows


def _severe_detail_rows(
    data: dict[str, Any], zt_path: list[str], rm_path: list[str]
) -> list[tuple]:
    """提取严重缺陷明细行：(缺陷ID, 项目, 标题, 提交人, 严重程度, 状态)。

    zt_path/rm_path 指定取禅道/Redmine 明细的嵌套路径（submissions 的 severe 在
    zentao.severe.bugs；severe 子命令直接在 zentao.bugs）。
    """
    rows: list[tuple] = []

    def _collect(section: dict[str, Any], path: list[str], kind: str) -> None:
        node: Any = section
        for k in path:
            node = (node or {}).get(k) if isinstance(node, dict) else None
        items = node.get("bugs" if kind == "zt" else "issues", []) if isinstance(node, dict) else []
        for item in items:
            if kind == "zt":
                rows.append(
                    (
                        f"Z-{item.get('id', '')}",
                        item.get("projectName", ""),
                        item.get("title", ""),
                        item.get("openedBy", ""),
                        _severity_label(item, "zt"),
                        item.get("status", ""),
                    )
                )
            else:
                rows.append(
                    (
                        f"R-{item.get('issue_id', '')}",
                        item.get("project_name", ""),
                        item.get("subject", ""),
                        item.get("author_name", ""),
                        _severity_label(item, "rm"),
                        item.get("status_name", ""),
                    )
                )

    _collect(data.get("zentao") or {}, zt_path, "zt")
    _collect(data.get("redmine") or {}, rm_path, "rm")
    return rows


def _closure_rows(data: dict[str, Any]) -> list[tuple]:
    """提取关闭明细行：(缺陷ID, 项目, 关闭人)。"""
    rows: list[tuple] = []
    for item in (data.get("zentao") or {}).get("bugs") or []:
        rows.append(
            (f"Z-{item.get('id', '')}", item.get("projectName", ""), item.get("closedBy", ""))
        )
    for item in (data.get("redmine") or {}).get("issues") or []:
        rows.append(
            (
                f"R-{item.get('issue_id', '')}",
                item.get("project_name", ""),
                item.get("closed_by") or item.get("user_name", ""),
            )
        )
    return rows


def _zero_users(data: dict[str, Any]) -> list[str]:
    """合并禅道/Redmine 的零提交人名单。"""
    out: list[str] = []
    for sys_key in ("zentao", "redmine"):
        out.extend(((data.get(sys_key) or {}).get("zero_submission_users")) or [])
    return out


def all_chart_paths(charts_map: dict[str, list[str]]) -> list[str]:
    """收集 charts_map 里所有图路径（去重保序），供 envelope 汇总。"""
    seen: set[str] = set()
    out: list[str] = []
    for paths in charts_map.values():
        for p in paths:
            if p not in seen:
                seen.add(p)
                out.append(p)
    return out


# ---------------------------------------------------------------------------
# HTML helpers
# ---------------------------------------------------------------------------


def _esc(value: Any) -> str:
    s = str(value) if value is not None else ""
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


# 表头文本 → 列宽 class（table-layout:fixed 下控制各列宽度）
_COL_WIDTH = {
    "排名": "w-rank",
    "缺陷ID": "w-id",
    "项目": "w-proj",
    "标题": "w-title",
    "严重程度": "w-sev",
    "指派人": "w-who",
    "关闭人": "w-who",
    "提交人": "w-who",
    "最后修改时间": "w-when",
    "超期天数": "w-days",
    "数量": "w-days",
    "占比": "w-days",
}


def _html_table(headers: list[str], rows: list[tuple], wrap_idx: int | None = None) -> str:
    """渲染表格。wrap_idx 指定哪一列允许换行（长文本如标题），其余列 nowrap 不挤。"""
    if not rows:
        return "<p>（无）</p>"
    colgroup = "".join(f'<col class="{_COL_WIDTH.get(h, "w-title")}">' for h in headers)
    head = "".join(f"<th>{_esc(h)}</th>" for h in headers)

    def _cell(i: int, c: Any) -> str:
        cls = ' class="wrap"' if i == wrap_idx else ""
        return f"<td{cls}>{_esc(c)}</td>"

    body = "".join("<tr>" + "".join(_cell(i, c) for i, c in enumerate(r)) + "</tr>" for r in rows)
    return (
        f"<table><colgroup>{colgroup}</colgroup><thead><tr>{head}</tr></thead>"
        f"<tbody>{body}</tbody></table>"
    )


def _img_inline(path: str) -> str:
    """把图片文件 base64 内嵌为 data URI；文件不存在返回空串。"""
    p = Path(path).expanduser()
    if not p.exists():
        return ""
    data = base64.b64encode(p.read_bytes()).decode("ascii")
    mime = _IMG_MIME.get(p.suffix.lower().lstrip("."), "image/png")
    return f"<img src='data:{mime};base64,{data}' alt='{_esc(p.name)}'/>"


def _section_images(charts_map: dict[str, list[str]], names: list[str]) -> str:
    imgs: list[str] = []
    for n in names:
        for p in charts_map.get(n, []):
            imgs.append(_img_inline(p))
    return "".join(imgs)


_HEADER_STYLE = (
    "<style>"
    "body{font-family:-apple-system,'Segoe UI',sans-serif;color:#222;max-width:900px;margin:auto}"
    "h1{font-size:20px}h2{font-size:16px;border-bottom:2px solid #4C78A8;padding-bottom:4px;margin-top:24px}"
    "table{border-collapse:collapse;margin:8px 0 16px;font-size:13px;width:100%;table-layout:fixed}"
    "th{background:#4C78A8;color:#fff;text-align:left}"
    "td,th{border:1px solid #ccc;padding:4px 8px;white-space:nowrap;vertical-align:top;overflow:hidden;text-overflow:ellipsis}"
    "td.wrap{white-space:normal;overflow:visible;text-overflow:clip}"
    "col.w-id{width:80px}col.w-proj{width:120px}col.w-title{width:40%}col.w-sev{width:60px}"
    "col.w-who{width:110px}col.w-when{width:140px}col.w-days{width:60px}col.w-rank{width:50px}"
    "img{max-width:100%;height:auto;margin:8px 0}"
    ".zero{color:#c00}"
    "</style>"
)


# ---------------------------------------------------------------------------
# Section builders
# ---------------------------------------------------------------------------


def _section_submissions(data: dict[str, Any], charts_map: dict[str, list[str]]) -> str:
    zt = data.get("zentao") or {}
    rm = data.get("redmine") or {}
    total = int(zt.get("total", 0)) + int(rm.get("total", 0))
    parts = [
        "<h2>一、本周提交情况</h2>",
        f"<p>测试组共提交 <b>{total}</b> 条缺陷"
        f"（禅道 {zt.get('total', 0)} / Redmine {rm.get('total', 0)}）。</p>",
    ]
    by_user = merge_counter(zt.get("by_user"), rm.get("by_user"))
    user_rows = [(i, u, c, _fmt_pct(c, total)) for i, (u, c) in enumerate(sort_desc(by_user), 1)]
    parts.append("<h3>按提交人</h3>")
    parts.append(_html_table(["排名", "提交人", "数量", "占比"], user_rows))

    by_project = merge_counter(zt.get("by_project"), rm.get("by_project"))
    proj_rows = [(i, p, c, _fmt_pct(c, total)) for i, (p, c) in enumerate(sort_desc(by_project), 1)]
    parts.append("<h3>按项目</h3>")
    parts.append(_html_table(["排名", "项目", "数量", "占比"], proj_rows))

    zero = _zero_users(data)
    if zero:
        parts.append(
            "<h3>零提交（需关注）</h3><p class='zero'>" + "、".join(_esc(u) for u in zero) + "</p>"
        )
    parts.append(_section_images(charts_map, ["submissions_by_user", "submissions_by_project"]))
    return "".join(parts)


def _section_severe_this_week(data: dict[str, Any], charts_map: dict[str, list[str]]) -> str:
    zt_severe = int(((data.get("zentao") or {}).get("severe") or {}).get("total", 0))
    rm_severe = int(((data.get("redmine") or {}).get("severe") or {}).get("total", 0))
    total = zt_severe + rm_severe
    rows = _severe_detail_rows(data, ["severe"], ["severe"])
    return "".join(
        [
            "<h2>二、严重-本周</h2>",
            f"<p>本周提交的严重缺陷 <b>{total}</b> 条（禅道 {zt_severe} / Redmine {rm_severe}）。</p>",
            _html_table(["缺陷ID", "项目", "标题", "提交人", "严重程度", "状态"], rows, wrap_idx=2),
            _section_images(charts_map, ["severe_ratio"]),
        ]
    )


def _section_severe_open(data: dict[str, Any]) -> str:
    zt = data.get("zentao") or {}
    rm = data.get("redmine") or {}
    total = int(zt.get("total", 0)) + int(rm.get("total", 0))
    rows = _severe_detail_rows(data, [], [])
    return "".join(
        [
            "<h2>三、严重-本组未关闭</h2>",
            f"<p>本组提交的、当前未关闭的严重缺陷 <b>{total}</b> 条"
            f"（禅道 {zt.get('total', 0)} / Redmine {rm.get('total', 0)}）。</p>",
            _html_table(["缺陷ID", "项目", "标题", "提交人", "严重程度", "状态"], rows, wrap_idx=2),
        ]
    )


def _section_overdue(data: dict[str, Any]) -> str:
    zt = data.get("zentao") or {}
    rm = data.get("redmine") or {}
    total = int(zt.get("total", 0)) + int(rm.get("total", 0))
    days = data.get("overdue_days", 7)
    rows = [
        (
            r["id"],
            r["project"],
            r["title"],
            r["severity"],
            r["assignee"],
            r["last_action"],
            r["days"],
        )
        for r in _overdue_rows(data)
    ]
    return "".join(
        [
            "<h2>四、跟踪不及时</h2>",
            f"<p>当前超期 <b>{total}</b> 条（指派给本组后超过 {days} 天无 action 的缺陷，已过滤停用项目）。</p>",
            _html_table(
                ["缺陷ID", "项目", "标题", "严重程度", "指派人", "最后修改时间", "超期天数"],
                rows,
                wrap_idx=2,
            ),
        ]
    )


def _section_closures(data: dict[str, Any], charts_map: dict[str, list[str]]) -> str:
    zt = data.get("zentao") or {}
    rm = data.get("redmine") or {}
    total = int(zt.get("total", 0)) + int(rm.get("total", 0))
    return "".join(
        [
            "<h2>五、本周关闭</h2>",
            f"<p>本组本周关闭 <b>{total}</b> 条缺陷"
            f"（禅道 {zt.get('total', 0)} / Redmine {rm.get('total', 0)}）。</p>",
            _section_images(charts_map, ["closures_by_user", "submissions_vs_closures"]),
        ]
    )


# ---------------------------------------------------------------------------
# Report builder
# ---------------------------------------------------------------------------


def build_email_html(
    sub: dict[str, Any] | None,
    ovd: dict[str, Any] | None,
    sev: dict[str, Any] | None,
    cls: dict[str, Any] | None,
    charts_map: dict[str, list[str]] | None,
) -> str:
    """生成自包含 HTML 邮件正文字符串（图 base64 内嵌）。"""
    charts_map = charts_map or {}
    parts = ["<html><head><meta charset='utf-8'>", _HEADER_STYLE, "</head><body>"]

    window = _short_window(sub or {})
    parts.append("<h1>缺陷分析周报</h1>")
    parts.append(
        f"<p><b>时间窗口</b>：{_esc(window) or '—'}"
        f" ｜ <b>生成时间</b>：{_esc(datetime.now().strftime('%Y-%m-%d %H:%M'))}</p>"
    )

    if sub:
        parts.append(_section_submissions(sub, charts_map))
        parts.append(_section_severe_this_week(sub, charts_map))
    if sev:
        parts.append(_section_severe_open(sev))
    if ovd:
        parts.append(_section_overdue(ovd))
    if cls:
        parts.append(_section_closures(cls, charts_map))

    parts.append("</body></html>")
    return "".join(parts)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def cmd_render_email(args: argparse.Namespace) -> int:
    try:
        out_dir = resolve_output_dir(args.out)
    except RenderError as exc:
        print(f"输出目录错误: {exc}", file=sys.stderr)
        return 1

    if not any([args.submissions, args.overdue, args.severe, args.closures]):
        print("错误: 至少需要 --submissions/--overdue/--severe/--closures 之一", file=sys.stderr)
        return 1

    try:
        sub = read_json_file(args.submissions) if args.submissions else None
        ovd = read_json_file(args.overdue) if args.overdue else None
        sev = read_json_file(args.severe) if args.severe else None
        cls = read_json_file(args.closures) if args.closures else None
        charts_map = (read_json_file(args.charts) or {}).get("charts", {}) if args.charts else {}
    except RenderError as exc:
        print(f"输入错误: {exc}", file=sys.stderr)
        return 1

    html = build_email_html(sub, ovd, sev, cls, charts_map)

    date_tag = datetime.now().strftime("%Y%m%d")
    html_path = out_dir / f"email_{date_tag}.html"
    html_path.write_text(html, encoding="utf-8")

    envelope = {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "html_path": str(html_path),
        "images": all_chart_paths(charts_map),
    }
    print(json.dumps(envelope, ensure_ascii=False, indent=2))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="把 bug_analysis 的 JSON 渲染成自包含 HTML 邮件正文（图 base64 内嵌）",
    )
    parser.add_argument("--submissions", help="submissions 子命令输出的 JSON")
    parser.add_argument("--overdue", help="overdue 子命令输出的 JSON")
    parser.add_argument("--severe", help="severe 子命令输出的 JSON")
    parser.add_argument("--closures", help="closures 子命令输出的 JSON")
    parser.add_argument("--charts", help="render_charts 输出的 envelope JSON（提供则内嵌图）")
    parser.add_argument("--out", help="输出目录（默认: common.json 的 output_root/bug_analysis）")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return cmd_render_email(args)


if __name__ == "__main__":
    raise SystemExit(main())
