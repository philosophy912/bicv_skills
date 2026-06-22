#!/usr/bin/env python3
"""
会话分析器 — 对比和分析 session 录制数据。

用法:
  python3 analyzer.py list                          # 列出所有录制
  python3 analyzer.py stats <file.jsonl>             # 单次运行统计
  python3 analyzer.py compare <f1.jsonl> <f2.jsonl>  # 两次运行对比
  python3 analyzer.py errors <file.jsonl>            # 提取所有错误
"""

import json
import sys
from pathlib import Path
from collections import defaultdict

LOG_DIR = Path.home() / ".bicv" / "session-logs"
INDEX_FILE = LOG_DIR / "index.json"


# ── 数据加载 ─────────────────────────────────────────

def load_jsonl(path: Path) -> list[dict]:
    records = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    records.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
    return records


def load_index() -> dict:
    if INDEX_FILE.exists():
        return json.loads(INDEX_FILE.read_text(encoding="utf-8"))
    return {"sessions": {}}


# ── 统计计算 ─────────────────────────────────────────

def compute_stats(records: list[dict]) -> dict:
    """从记录中提取统计数据"""
    stages = defaultdict(lambda: {
        "tool_calls": 0, "errors": 0, "first_seen": None, "last_seen": None
    })
    total_errors = 0
    total_calls = 0
    tool_distribution = defaultdict(int)
    session_start = None
    session_end = None

    for r in records:
        t = r.get("type")

        if t == "session_start":
            session_start = r.get("started_at")
        elif t == "session_end":
            session_end = r.get("ended_at")

        elif t == "tool_call":
            total_calls += 1
            stage = r.get("stage") or "unknown"
            tool = r.get("tool", "unknown")

            stages[stage]["tool_calls"] += 1
            stages[stage]["first_seen"] = stages[stage]["first_seen"] or r.get("timestamp")
            stages[stage]["last_seen"] = r.get("timestamp")
            tool_distribution[tool] += 1

            if r.get("is_error"):
                total_errors += 1
                stages[stage]["errors"] += 1

    return {
        "session_start": session_start,
        "session_end": session_end,
        "total_tool_calls": total_calls,
        "total_errors": total_errors,
        "error_rate": f"{total_errors / total_calls * 100:.1f}%" if total_calls else "N/A",
        "stages": dict(stages),
        "tools": dict(tool_distribution),
    }


# ── 输出格式化 ───────────────────────────────────────

def print_stats(stats: dict, filepath: str) -> None:
    print(f"\n{'='*60}")
    print(f"  Session: {Path(filepath).stem}")
    print(f"{'='*60}")
    print(f"  开始时间 : {stats['session_start'] or 'N/A'}")
    print(f"  结束时间 : {stats['session_end'] or 'N/A'}")
    print(f"  Tool 调用: {stats['total_tool_calls']}")
    print(f"  错误数   : {stats['total_errors']}")
    print(f"  错误率   : {stats['error_rate']}")
    print()
    print(f"  {'阶段':<15} {'调用数':>6} {'错误':>6}")
    print(f"  {'-'*15} {'-'*6} {'-'*6}")
    for stage in ["validate", "normalize", "classify", "testpoint", "testcase", "export", "unknown"]:
        if stage in stats["stages"]:
            s = stats["stages"][stage]
            print(f"  {stage:<15} {s['tool_calls']:>6} {s['errors']:>6}")
    print()
    print(f"  Tool 分布:")
    for tool, count in sorted(stats["tools"].items(), key=lambda x: -x[1]):
        print(f"    {tool:<20} {count:>6}")
    print()


def print_compare(stats1: dict, stats2: dict, f1: str, f2: str) -> None:
    print(f"\n{'='*60}")
    print(f"  对比分析")
    print(f"  基准: {Path(f1).stem}")
    print(f"  当前: {Path(f2).stem}")
    print(f"{'='*60}")

    # 指标对比
    metrics = [
        ("Tool 调用", "total_tool_calls", "{}"),
        ("错误数", "total_errors", "{}"),
    ]
    print()
    print(f"  {'指标':<15} {'基准':>10} {'当前':>10} {'变化':>10}")
    print(f"  {'-'*15} {'-'*10} {'-'*10} {'-'*10}")
    for name, key, fmt in metrics:
        v1 = stats1[key]
        v2 = stats2[key]
        delta = v2 - v1
        sign = "+" if delta > 0 else ""
        print(f"  {name:<15} {fmt.format(v1):>10} {fmt.format(v2):>10} {sign + str(delta):>10}")

    # 错误率
    print(f"  {'错误率':<15} {stats1['error_rate']:>10} {stats2['error_rate']:>10}")

    # 阶段级对比
    print()
    print(f"  {'阶段':<15} {'基准调用':>8} {'当前调用':>8} {'基准错误':>8} {'当前错误':>8}")
    print(f"  {'-'*15} {'-'*8} {'-'*8} {'-'*8} {'-'*8}")
    all_stages = sorted(set(list(stats1["stages"].keys()) + list(stats2["stages"].keys())))
    for stage in all_stages:
        s1 = stats1["stages"].get(stage, {"tool_calls": 0, "errors": 0})
        s2 = stats2["stages"].get(stage, {"tool_calls": 0, "errors": 0})
        print(f"  {stage:<15} {s1['tool_calls']:>8} {s2['tool_calls']:>8} {s1['errors']:>8} {s2['errors']:>8}")
    print()


def print_errors(records: list[dict]) -> None:
    errors = [r for r in records if r.get("type") in ("tool_call", "error_detail") and r.get("is_error")]
    if not errors:
        print("  没有错误记录。")
        return

    print(f"\n  共 {len(errors)} 条错误:")
    print(f"  {'-'*60}")
    for i, e in enumerate(errors, 1):
        print(f"  [{i}] {e.get('stage', '?')}/{e.get('tool', '?')}")
        print(f"      时间: {e.get('timestamp', '?')}")
        print(f"      错误: {e.get('error_msg', 'N/A')}")
        if e.get("subagent"):
            print(f"      子代理: {e['subagent']}")
        print()


def print_list() -> None:
    index = load_index()
    sessions = index.get("sessions", {})
    if not sessions:
        print("  暂无录制。")
        return

    print(f"\n  {'短ID':<10} {'状态':<12} {'开始时间':<28} {'文件'}")
    print(f"  {'-'*10} {'-'*12} {'-'*28} {'-'*40}")
    for sid, info in sorted(sessions.items(), key=lambda x: x[1].get("started_at", ""), reverse=True):
        status = info.get("status", "?")
        started = info.get("started_at", "?")
        logf = info.get("log_file", "?")
        print(f"  {sid:<10} {status:<12} {started:<28} {logf}")
    print()


# ── 入口 ──────────────────────────────────────────────

def main() -> None:
    if len(sys.argv) < 2:
        print("用法: analyzer.py <command> [args]")
        print("  list                      列出所有录制")
        print("  stats <file.jsonl>        单次运行统计")
        print("  compare <f1> <f2>         两次运行对比")
        print("  errors <file.jsonl>       提取错误")
        sys.exit(1)

    cmd = sys.argv[1]

    if cmd == "list":
        print_list()

    elif cmd == "stats":
        if len(sys.argv) < 3:
            print("用法: analyzer.py stats <file.jsonl>")
            sys.exit(1)
        path = Path(sys.argv[2])
        if not path.exists():
            print(f"文件不存在: {path}")
            sys.exit(1)
        records = load_jsonl(path)
        stats = compute_stats(records)
        print_stats(stats, str(path))

    elif cmd == "compare":
        if len(sys.argv) < 4:
            print("用法: analyzer.py compare <file1.jsonl> <file2.jsonl>")
            sys.exit(1)
        p1, p2 = Path(sys.argv[2]), Path(sys.argv[3])
        for p in [p1, p2]:
            if not p.exists():
                print(f"文件不存在: {p}")
                sys.exit(1)
        s1 = compute_stats(load_jsonl(p1))
        s2 = compute_stats(load_jsonl(p2))
        print_compare(s1, s2, str(p1), str(p2))

    elif cmd == "errors":
        if len(sys.argv) < 3:
            print("用法: analyzer.py errors <file.jsonl>")
            sys.exit(1)
        path = Path(sys.argv[2])
        if not path.exists():
            print(f"文件不存在: {path}")
            sys.exit(1)
        print_errors(load_jsonl(path))

    else:
        print(f"未知命令: {cmd}")
        sys.exit(1)


if __name__ == "__main__":
    main()
