#!/usr/bin/env python3
"""Render bug analysis JSON into PNG charts.

把 ``bug_analysis.py`` 的 submissions / overdue 子命令输出的 JSON 渲染成
横向条形图与明细表格图。所有查询逻辑仍在 ``bug_analysis.py``，本脚本只负责
「吃 JSON → 出图」，职责分离、不连数据库。

四类图（按数据有无按需生成，可分页、不截断）：
    submissions_by_user     缺陷提交 · 按提交人（横向条形图）
    submissions_by_project  缺陷提交 · 按项目（横向条形图）
    overdue_by_user         超期缺陷 · 按指派人计数（横向条形图）
    overdue_detail          超期缺陷明细（表格图）

用法：
    render_charts.py --submissions sub.json --overdue ovd.json [--out <dir>]

依赖：
    matplotlib（中文字体优先探测系统已装 CJK 字体，找不到回退
    ``assets/fonts/`` 下的字体文件，再找不到报错指引）
    ~/.bicv/common.json（output_root + skills 子目录映射）
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from datetime import datetime
from pathlib import Path
from typing import Any

# --- matplotlib guard（必须在 import pyplot 前 set backend）---
try:
    import matplotlib

    matplotlib.use("Agg")  # 非交互后端，无需显示窗口
    import matplotlib.pyplot as plt
    from matplotlib import font_manager
except ImportError:
    print(
        "Error: matplotlib is not installed.\nInstall it with: pip install matplotlib",
        file=sys.stderr,
    )
    sys.exit(1)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

COMMON_CONFIG_NAME = "common.json"
SKILL_NAME = "bug_daily_analysis"
DEFAULT_OUTPUT_SUBDIR = "bug_daily_analysis"

# 条形图/表格的分页阈值：超过则拆成多张图（不截断、不合并「其他」）
BAR_PAGE_SIZE = 25
TABLE_PAGE_SIZE = 30

# 候选中文字体名（macOS / Windows / Linux 常见 CJK），按优先级探测
FONT_CANDIDATES = [
    "PingFang SC",
    "Heiti SC",
    "STHeiti",
    "Hiragino Sans GB",
    "Arial Unicode MS",
    "Microsoft YaHei",
    "SimHei",
    "Microsoft JhengHei",
    "Noto Sans CJK SC",
    "Noto Sans SC",
    "Source Han Sans SC",
    "Source Han Sans CN",
    "WenQuanYi Micro Hei",
    "WenQuanYi Zen Hei",
]

ASSETS_FONTS_DIR = Path(__file__).resolve().parent.parent / "assets" / "fonts"


class RenderError(Exception):
    """渲染过程错误（配置/字体/IO）。"""


# ---------------------------------------------------------------------------
# Config / output dir
# ---------------------------------------------------------------------------


def _load_common_config() -> dict[str, Any]:
    """从 ~/.bicv/common.json 加载配置。"""
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
    """解析输出目录：--out 优先，否则 common.json 的 output_root/skills[bug_daily_analysis]。"""
    if custom:
        out_dir = Path(custom).expanduser()
    else:
        cfg = _load_common_config()
        root = cfg.get("output_root")
        if not root:
            raise RenderError(f"[{COMMON_CONFIG_NAME}] 缺少 output_root")
        skills_map = cfg.get("skills", {}) or {}
        subdir = skills_map.get(SKILL_NAME, DEFAULT_OUTPUT_SUBDIR)
        out_dir = Path(str(root)).expanduser() / str(subdir)
    out_dir.mkdir(parents=True, exist_ok=True)
    return out_dir


# ---------------------------------------------------------------------------
# Font resolution
# ---------------------------------------------------------------------------


def _find_cjk_font() -> str | None:
    """探测可用中文字体：先系统已装字体名，再 assets/fonts/ 下的字体文件。"""
    available = {f.name for f in font_manager.fontManager.ttflist}
    for cand in FONT_CANDIDATES:
        if cand in available:
            return cand
    if ASSETS_FONTS_DIR.is_dir():
        for pattern in ("*.otf", "*.ttf", "*.ttc"):
            for f in sorted(ASSETS_FONTS_DIR.glob(pattern)):
                return str(f)
    return None


def resolve_font() -> str:
    """返回可用的中文字体名/路径；找不到抛 RenderError 并给指引。"""
    font = _find_cjk_font()
    if font:
        return font
    raise RenderError(
        "未找到中文字体，中文会渲染成方块 ☐☐☐。解决方法（任选其一）：\n"
        "  1) 安装思源黑体 / Noto Sans CJK / PingFang 等中文字体；\n"
        f"  2) 把一个开源中文字体文件放到 {ASSETS_FONTS_DIR} 下。"
    )


def _apply_font(font_name: str) -> None:
    """把选定字体应用到 matplotlib 全局。"""
    # 若是文件路径，先注册进 fontManager
    if font_name.endswith((".otf", ".ttf", ".ttc")) and Path(font_name).exists():
        try:
            font_manager.fontManager.addfont(font_name)
            font_name = Path(font_name).name
        except Exception:
            # 注册失败也不致命，仍尝试按名引用
            pass
    plt.rcParams["font.sans-serif"] = [font_name]
    plt.rcParams["axes.unicode_minus"] = False


# ---------------------------------------------------------------------------
# Pure data helpers（不依赖 matplotlib，便于单测）
# ---------------------------------------------------------------------------


def sort_desc(counter: dict[str, int]) -> list[tuple[str, int]]:
    """按值降序、同值按名升序。"""
    return sorted(counter.items(), key=lambda kv: (-int(kv[1]), kv[0]))


def merge_counter(*counters: dict[str, Any] | None) -> dict[str, int]:
    """合并多个 {name: count}，同名累加（跨禅道/Redmine 系统）。"""
    out: dict[str, int] = {}
    for counter in counters:
        for key, val in (counter or {}).items():
            out[key] = out.get(key, 0) + int(val)
    return out


def paginate(items: Sequence[Any], per_page: int) -> list[list[Any]]:
    """把序列切成每页 per_page 条；空序列返回 []。per_page<=0 视为不分页。"""
    items = list(items)
    if not items:
        return []
    if per_page <= 0:
        return [items]
    return [items[i : i + per_page] for i in range(0, len(items), per_page)]


def truncate_label(text: Any, max_chars: int = 18) -> str:
    """超长文本截断 + 省略号（按字符数，适配中文）。"""
    s = str(text)
    return s if len(s) <= max_chars else s[: max_chars - 1] + "…"


def _short_window(data: dict[str, Any]) -> str:
    """从 submissions 的 window 提取 'MM-DD~MM-DD' 短串用于标题。"""
    window = data.get("window") or {}

    def _md(value: Any) -> str:
        s = str(value or "")[:10]
        return s[5:] if len(s) >= 10 else s  # YYYY-MM-DD -> MM-DD

    start, end = _md(window.get("start")), _md(window.get("end"))
    return f"{start}~{end}" if start and end else ""


# ---------------------------------------------------------------------------
# Drawing primitives（依赖 matplotlib，单测整体 mock plt）
# ---------------------------------------------------------------------------


def render_bar(
    data: list[tuple[str, int]],
    title: str,
    out_path: Path,
    font: str,
    xlabel: str = "数量",
) -> Path:
    """画一张横向条形图（data 已按降序排好，最多者居顶）。返回 out_path。"""
    if not data:
        return out_path
    _apply_font(font)
    # 反转使最大值在顶部
    pairs = list(reversed(data))
    labels = [truncate_label(name) for name, _ in pairs]
    values = [int(v) for _, v in pairs]
    n = len(pairs)

    fig, ax = plt.subplots(figsize=(8, max(3.0, 0.42 * n + 1.2)))
    ax.barh(range(n), values, color="#4C78A8")
    ax.set_yticks(range(n))
    ax.set_yticklabels(labels, fontsize=9)
    for i, v in enumerate(values):
        ax.text(v, i, f" {v}", va="center", fontsize=8)
    ax.set_title(title, fontsize=13)
    ax.set_xlabel(xlabel, fontsize=10)
    ax.margins(x=0.12)
    ax.spines[["top", "right"]].set_visible(False)
    fig.tight_layout()
    fig.savefig(out_path, dpi=150)
    plt.close(fig)
    return out_path


def render_table(
    rows: list[dict[str, Any]],
    columns: list[tuple[str, str]],
    title: str,
    out_path: Path,
    font: str,
) -> Path:
    """画一张明细表格图。columns = [(表头, 字段名)]。返回 out_path。"""
    if not rows:
        return out_path
    _apply_font(font)
    cell_text = [[truncate_label(row.get(key, ""), 32) for _, key in columns] for row in rows]
    col_labels = [header for header, _ in columns]
    n = len(rows)

    fig, ax = plt.subplots(figsize=(10, max(2.0, 0.34 * n + 1.6)))
    ax.axis("off")
    table = ax.table(
        cellText=cell_text,
        colLabels=col_labels,
        loc="center",
        cellLoc="left",
        colLoc="left",
    )
    table.auto_set_font_size(False)
    table.set_fontsize(9)
    table.scale(1, 1.5)
    ax.set_title(title, fontsize=13, loc="left")
    fig.tight_layout()
    fig.savefig(out_path, dpi=150)
    plt.close(fig)
    return out_path


# ---------------------------------------------------------------------------
# Section renderers：把数据拆页、生成文件、返回路径列表
# ---------------------------------------------------------------------------


def _clear_old_pages(out_dir: Path, stem: str) -> None:
    """删除同 stem 的旧输出（stem.png 及 stem_p*.png），避免重新渲染页数变少时残留孤儿页。"""
    for p in out_dir.glob(f"{stem}.png"):
        p.unlink()
    for p in out_dir.glob(f"{stem}_p*.png"):
        p.unlink()


def _emit_bars(
    counter: dict[str, int],
    title: str,
    out_dir: Path,
    stem: str,
    font: str,
    page_size: int = BAR_PAGE_SIZE,
) -> list[str]:
    """把一个计数分布排序、分页、逐页画条形图，返回生成的文件路径列表。"""
    _clear_old_pages(out_dir, stem)
    sorted_items = sort_desc(counter)
    pages = paginate(sorted_items, page_size)
    paths: list[str] = []
    total = len(pages)
    for idx, page in enumerate(pages, start=1):
        suffix = f"_p{idx}" if total > 1 else ""
        out_path = out_dir / f"{stem}{suffix}.png"
        page_title = title if total <= 1 else f"{title} ({idx}/{total})"
        render_bar(page, page_title, out_path, font)
        paths.append(str(out_path))
    return paths


def _emit_table(
    rows: list[dict[str, Any]],
    columns: list[tuple[str, str]],
    title: str,
    out_dir: Path,
    stem: str,
    font: str,
    page_size: int = TABLE_PAGE_SIZE,
) -> list[str]:
    """把明细行分页、逐页画表格图，返回生成的文件路径列表。"""
    _clear_old_pages(out_dir, stem)
    pages = paginate(rows, page_size)
    paths: list[str] = []
    total = len(pages)
    for idx, page in enumerate(pages, start=1):
        suffix = f"_p{idx}" if total > 1 else ""
        out_path = out_dir / f"{stem}{suffix}.png"
        page_title = title if total <= 1 else f"{title} ({idx}/{total})"
        render_table(page, columns, page_title, out_path, font)
        paths.append(str(out_path))
    return paths


def render_submissions(
    data: dict[str, Any], out_dir: Path, font: str, date_tag: str
) -> dict[str, list[str]]:
    """渲染 submissions 数据：按人 + 按项目两张条形图（合并禅道/Redmine）。"""
    charts: dict[str, list[str]] = {}
    zt = data.get("zentao") or {}
    rm = data.get("redmine") or {}
    window = _short_window(data)
    suffix = f"（{window}）" if window else ""

    by_user = merge_counter(zt.get("by_user"), rm.get("by_user"))
    if by_user:
        charts["submissions_by_user"] = _emit_bars(
            by_user,
            f"缺陷提交 · 按提交人{suffix}",
            out_dir,
            f"bug_submissions_by_user_{date_tag}",
            font,
        )

    by_project = merge_counter(zt.get("by_project"), rm.get("by_project"))
    if by_project:
        charts["submissions_by_project"] = _emit_bars(
            by_project,
            f"缺陷提交 · 按项目{suffix}",
            out_dir,
            f"bug_submissions_by_project_{date_tag}",
            font,
        )
    return charts


def _overdue_rows(data: dict[str, Any]) -> list[dict[str, Any]]:
    """合并禅道/Redmine 超期明细为统一行结构（含缺陷 ID），按超期天数降序。

    缺陷 ID 带系统前缀（Z- 禅道 / R- Redmine），避免两系统数字 id 混淆。
    """
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


def render_overdue(
    data: dict[str, Any], out_dir: Path, font: str, date_tag: str
) -> dict[str, list[str]]:
    """渲染 overdue 数据：按指派人计数条形图 + 明细表格图。"""
    charts: dict[str, list[str]] = {}
    zt = data.get("zentao") or {}
    rm = data.get("redmine") or {}

    by_user = merge_counter(zt.get("by_user"), rm.get("by_user"))
    if by_user:
        charts["overdue_by_user"] = _emit_bars(
            by_user,
            "超期缺陷 · 按指派人",
            out_dir,
            f"bug_overdue_by_user_{date_tag}",
            font,
        )

    rows = _overdue_rows(data)
    if rows:
        charts["overdue_detail"] = _emit_table(
            rows,
            [
                ("缺陷ID", "id"),
                ("项目", "project"),
                ("模块/主题", "module"),
                ("指派人", "assignee"),
                ("超期天数", "days"),
            ],
            "超期缺陷明细",
            out_dir,
            f"bug_overdue_detail_{date_tag}",
            font,
        )
    return charts


# ---------------------------------------------------------------------------
# IO + CLI
# ---------------------------------------------------------------------------


def read_json_file(path_str: str) -> dict[str, Any]:
    """读取并解析输入 JSON 文件。"""
    path = Path(path_str).expanduser()
    if not path.exists():
        raise RenderError(f"输入文件不存在: {path}")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise RenderError(f"JSON 解析失败: {path}\n{exc}") from exc


def cmd_render(args: argparse.Namespace) -> int:
    """入口编排：解析字体/目录 → 读 JSON → 逐板块出图 → 打印 JSON 信封。"""
    try:
        font = resolve_font()
    except RenderError as exc:
        print(f"字体错误: {exc}", file=sys.stderr)
        return 1

    try:
        out_dir = resolve_output_dir(args.out)
    except RenderError as exc:
        print(f"输出目录错误: {exc}", file=sys.stderr)
        return 1

    if not args.submissions and not args.overdue:
        print("错误: 至少需要 --submissions 或 --overdue 之一", file=sys.stderr)
        return 1

    try:
        sub_data = read_json_file(args.submissions) if args.submissions else None
        ovd_data = read_json_file(args.overdue) if args.overdue else None
    except RenderError as exc:
        print(f"输入错误: {exc}", file=sys.stderr)
        return 1

    date_tag = datetime.now().strftime("%Y%m%d")
    charts: dict[str, list[str]] = {}
    try:
        if sub_data:
            charts.update(render_submissions(sub_data, out_dir, font, date_tag))
        if ovd_data:
            charts.update(render_overdue(ovd_data, out_dir, font, date_tag))
    except RenderError as exc:
        print(f"渲染失败: {exc}", file=sys.stderr)
        return 1

    envelope = {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "output_dir": str(out_dir),
        "charts": charts,
    }
    print(json.dumps(envelope, ensure_ascii=False, indent=2))
    return 0


def build_parser() -> argparse.ArgumentParser:
    """构建 CLI 参数解析器。"""
    parser = argparse.ArgumentParser(
        description="把 bug_analysis 的 JSON 渲染成 PNG 图表（条形图 + 明细表）",
    )
    parser.add_argument("--submissions", help="submissions 子命令输出的 JSON 文件路径")
    parser.add_argument("--overdue", help="overdue 子命令输出的 JSON 文件路径")
    parser.add_argument(
        "--out",
        help="输出目录（默认: common.json 的 output_root/bug_daily_analysis）",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """入口：解析参数 → 渲染。"""
    args = build_parser().parse_args(argv)
    return cmd_render(args)


if __name__ == "__main__":
    raise SystemExit(main())
