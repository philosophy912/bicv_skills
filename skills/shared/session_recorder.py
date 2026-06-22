#!/usr/bin/env python3
"""
会话录制器 — 由 Claude Code hook 系统自动触发。

触发方式:
  PostToolUse hook → python3 session_recorder.py tool
  Stop hook       → python3 session_recorder.py end

数据来源:
  - stdin: Claude Code hook 传入的 JSON (tool_name, tool_input, session_id 等)
  - 环境变量: CLAUDE_SESSION_ID, CLAUDE_PROJECT_PATH
  - 命令行参数: "tool" 或 "end"

输出:
  ~/.bicv/session-logs/YYYY-MM-DD-{session_short_id}.jsonl
"""

import json
import os
import sys
import time
import hashlib
from datetime import datetime, timezone, timedelta
from pathlib import Path

# ── 配置 ─────────────────────────────────────────────

LOG_DIR = Path.home() / ".bicv" / "session-logs"
INDEX_FILE = LOG_DIR / "index.json"
STAGE_KEYWORDS = [
    "validate", "normalize", "classify",
    "testpoint", "testcase", "export",
]

# ── 工具函数 ─────────────────────────────────────────

def tz() -> timezone:
    return timezone(timedelta(hours=8))  # CST


def now_iso() -> str:
    return datetime.now(tz()).isoformat()


def short_id(session_id: str) -> str:
    """8 位短 ID"""
    return hashlib.md5(session_id.encode()).hexdigest()[:8]


def ensure_dir() -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)


def read_stdin() -> dict | None:
    """从 stdin 读取 hook 传入的 JSON"""
    try:
        return json.load(sys.stdin)
    except (json.JSONDecodeError, Exception):
        return None


def guess_stage(text: str) -> str | None:
    """从文本中推断当前 pipeline 阶段"""
    text_lower = text.lower()
    for kw in STAGE_KEYWORDS:
        if kw in text_lower:
            return kw
    return None


def summarize(text: str, max_len: int = 120) -> str:
    """截断文本"""
    if not text:
        return ""
    text = str(text)
    if len(text) <= max_len:
        return text
    return text[:max_len] + "..."


# ── 录制逻辑 — tool call ─────────────────────────────

def handle_tool_call(data: dict) -> None:
    ensure_dir()

    session_id = os.environ.get("CLAUDE_SESSION_ID", "unknown")
    sid = short_id(session_id)
    today = datetime.now(tz()).strftime("%Y-%m-%d")
    log_path = LOG_DIR / f"{today}-{sid}.jsonl"

    tool_name = data.get("tool_name", "")
    tool_input = data.get("tool_input", {})
    tool_result = data.get("tool_result", "")

    # 推断阶段
    input_text = json.dumps(tool_input) if isinstance(tool_input, dict) else str(tool_input)
    stage = guess_stage(input_text)

    # 如果没有从 input 推断出来，尝试从 result 推断
    if stage is None:
        result_text = tool_result if isinstance(tool_result, str) else json.dumps(tool_result)
        stage = guess_stage(result_text) if result_text else None

    # 判断是否出错
    is_error = False
    error_msg = None
    if isinstance(tool_result, dict):
        if tool_result.get("is_error") or tool_result.get("isError"):
            is_error = True
            error_msg = tool_result.get("error", str(tool_result))
    elif isinstance(tool_result, str):
        error_keywords = ["error", "Error", "failed", "Failed", "timeout", "Traceback"]
        if any(kw in tool_result for kw in error_keywords):
            is_error = True
            error_msg = summarize(tool_result, 200)

    # 提取 subagent 名称
    subagent = None
    if isinstance(tool_input, dict):
        subagent = tool_input.get("subagent_type") or tool_input.get("description")

    record = {
        "type": "tool_call",
        "session_id": session_id,
        "sid": sid,
        "stage": stage,
        "tool": tool_name,
        "subagent": subagent,
        "input_summary": summarize(json.dumps(tool_input) if isinstance(tool_input, dict) else str(tool_input)),
        "output_summary": summarize(tool_result if isinstance(tool_result, str) else json.dumps(tool_result)),
        "is_error": is_error,
        "error_msg": error_msg,
        "timestamp": now_iso(),
    }

    with open(log_path, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")

    # 更新索引
    update_index(session_id, sid, log_path)


# ── 录制逻辑 — session end ───────────────────────────

def handle_session_end(data: dict | None = None) -> None:
    ensure_dir()

    session_id = os.environ.get("CLAUDE_SESSION_ID", "unknown")
    sid = short_id(session_id)
    today = datetime.now(tz()).strftime("%Y-%m-%d")
    log_path = LOG_DIR / f"{today}-{sid}.jsonl"

    # 检查是否有记录
    if log_path.exists():
        # 追加 session_end 标记
        end_record = {
            "type": "session_end",
            "session_id": session_id,
            "sid": sid,
            "ended_at": now_iso(),
        }
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(end_record, ensure_ascii=False) + "\n")

        # 更新索引状态为 completed
        update_index(session_id, sid, log_path, status="completed")


# ── 索引管理 ──────────────────────────────────────────

def update_index(session_id: str, sid: str, log_path: Path,
                 status: str = "recording") -> None:
    """维护 session 索引文件"""
    index = {"sessions": {}}
    if INDEX_FILE.exists():
        try:
            index = json.loads(INDEX_FILE.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, Exception):
            index = {"sessions": {}}

    if sid not in index.setdefault("sessions", {}):
        index["sessions"][sid] = {
            "session_id": session_id,
            "started_at": now_iso(),
            "log_file": str(log_path),
            "status": status,
        }
    else:
        index["sessions"][sid]["status"] = status
        index["sessions"][sid]["last_updated"] = now_iso()

    INDEX_FILE.write_text(json.dumps(index, ensure_ascii=False, indent=2), encoding="utf-8")


# ── 入口 ──────────────────────────────────────────────

def main() -> None:
    mode = sys.argv[1] if len(sys.argv) > 1 else "tool"

    if mode == "end":
        data = read_stdin()
        handle_session_end(data)
    else:
        data = read_stdin()
        if data:
            handle_tool_call(data)


if __name__ == "__main__":
    main()
