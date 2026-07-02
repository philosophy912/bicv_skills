#!/usr/bin/env python3
"""report 阶段编排：合并 builds.json + agent 的 analyses.json（+ 可选节点检查），
拼装 report.json，并按配置把关键信息以飞书卡片发到群（替代原 report.md）。

判定（category/evidence 等）由 agent 在 analyze 阶段写入 analyses.json，本脚本只做
合并、卡片构造与发送——不调 LLM、不做模式匹配。

卡片策略：scm/compile/other/unknown 四类各成一组，每组按每 5 条拆成多张卡（ceil(N/5)），
**某类 0 条则跳过不发该类卡片**；节点掉线仅当存在系统自发掉线时发一张。
所有卡 POST 到飞书**自定义机器人 webhook**（``{"msg_type":"interactive","card":...}``），
无需 lark-cli；配了 ``secret`` 则按官方加签算法签名。

analyses.json 格式（agent 写，每条对应 builds.json 的一条失败构建）::

    [
      {"job": "APP", "number": 7, "category": "scm",
       "confidence": "high", "evidence": "...", "log_excerpt": "..."}
    ]

用法（agent 编排）::

    python3 report.py --rundir <run-dir> [--analyses <path>] [--cli <jenkins_api.py>] [--system <name>]
                      [--no-notify] [--dry-run]
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import hmac
import json
import os
import ssl
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter
from pathlib import Path
from typing import Any

from collect import parse_json_envelope, run_jenkins_cli  # 复用编排层公共 helper

CARD_CHUNK_SIZE = 5
CATEGORIES = ("scm", "compile", "other", "unknown")
# ignored 不进 by_category（顶部统计四类不含它），但属合法判定：
# 用户主动中止 / 配置忽略的构建保留在 report.json，仅不计入统计、不在报告单独列表。
IGNORED = "ignored"
# 各分类卡片头部配色（飞书 interactive header.template）
CATEGORY_TEMPLATE = {"scm": "red", "compile": "orange", "other": "grey", "unknown": "blue"}
NOTIFY_CONFIG_PATH = Path.home() / ".bicv" / "jenkins_analysis.json"


def load_analyses(path: str) -> dict[tuple[str, Any], dict[str, Any]]:
    """读 analyses.json，返回 ``{(job, number): entry}``；文件不存在返回空 dict。"""
    if not os.path.isfile(path):
        return {}
    with open(path, encoding="utf-8-sig") as fh:
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
            # 保证 by_category 四类之和 == total_failed（ignored 不计入，见 build_report）。
            # ignored 是合法判定（用户中止 / 配置忽略），原样保留，仅不进统计。
            category = entry.get("category", "unknown")
            if category in CATEGORIES or category == IGNORED:
                b["category"] = category
            else:
                b["category"] = "unknown"
            b["confidence"] = entry.get("confidence", "low")
            b["evidence"] = entry.get("evidence", "")
            b["log_excerpt"] = entry.get("log_excerpt", "")
        else:
            b["category"] = "unknown"
            b["confidence"] = "low"
            b["evidence"] = "未判定（analyses.json 缺该条）"
            b["log_excerpt"] = ""
    return builds


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


# ===================================================================
# 飞书卡片构造
# ===================================================================


def load_notify_config(path: Path | None = None) -> dict[str, Any] | None:
    """读 ~/.bicv/jenkins_analysis.json 的 notify 字段。

    返回 ``{"webhook_url", "secret", "enabled", "ca_bundle", "verify_ssl"}``；文件缺失/损坏/无
    notify/无 webhook_url 返回 None。``secret`` 缺省空串（不加签）；``enabled`` 缺省 True；
    ``ca_bundle`` 缺省空（用 urllib 默认 CA）；``verify_ssl`` 缺省 True。
    """
    p = path or NOTIFY_CONFIG_PATH
    if not p.exists():
        return None
    try:
        cfg = json.loads(p.read_text(encoding="utf-8-sig"))
    except (json.JSONDecodeError, OSError):
        return None
    if not isinstance(cfg, dict):
        return None
    notify = cfg.get("notify")
    if not isinstance(notify, dict) or not notify.get("webhook_url"):
        return None
    return {
        "webhook_url": notify["webhook_url"],
        "secret": notify.get("secret", ""),
        "enabled": bool(notify.get("enabled", True)),
        "ca_bundle": notify.get("ca_bundle", ""),
        "verify_ssl": bool(notify.get("verify_ssl", True)),
    }


def _div(text: str) -> dict[str, Any]:
    """构造一个 lark_md 文本 div 元素。"""
    return {"tag": "div", "text": {"tag": "lark_md", "content": text}}


def build_category_card(
    report: dict[str, Any], category: str, chunk: list[dict[str, Any]], idx: int, total: int
) -> dict[str, Any]:
    """构造一张分类卡片（interactive）。

    - 标题：``Jenkins 失败分析 · {category} · {N} 条 · {idx}/{total}``
    - 顶部：总失败数 + 四类计数 + 窗口/实例
    - 正文：本 chunk 最多 5 条明细（job / #构建 / 判定依据 / 构建链接）；空 chunk 显示「本类无失败」
    """
    bc = report["summary"]["by_category"]
    total_failed = report["summary"]["total_failed"]
    window = report.get("window", {})
    since = report.get("since_hours", 24)
    system = report.get("system", "default")
    title = f"Jenkins 失败分析 · {category} · {bc[category]} 条 · {idx}/{total}"
    elements: list[dict[str, Any]] = [
        _div(
            f"**总失败 {total_failed}** ｜ scm {bc['scm']} / compile {bc['compile']} "
            f"/ other {bc['other']} / unknown {bc['unknown']}"
        ),
        _div(f"窗口：{_fmt_window(window)}（滚动 {since}h） ｜ 实例：{system}"),
        {"tag": "hr"},
    ]
    if chunk:
        for b in chunk:
            url = b.get("url", "")
            link = f" [打开]({url})" if url else ""
            if category == "compile":
                # compile 仅列 job + 链接（编译失败一看 job 名即知，细节看构建链接）
                elements.append(_div(f"**{b['job']} #{b['number']}**{link}"))
            else:
                # 其它类带 evidence（判定依据），便于定位根因
                elements.append(
                    _div(f"**{b['job']} #{b['number']}**{link}\n{b.get('evidence', '')}")
                )
    else:
        elements.append(_div("本类无失败构建。"))
    return {
        "config": {"wide_screen_mode": True},
        "header": {
            "title": {"tag": "plain_text", "content": title},
            "template": CATEGORY_TEMPLATE[category],
        },
        "elements": elements,
    }


def build_nodes_card(report: dict[str, Any]) -> dict[str, Any] | None:
    """构造节点掉线卡片；仅当存在系统自发掉线节点时返回卡片，否则 None。"""
    nodes = report.get("nodes")
    if not nodes or not nodes.get("details"):
        return None
    total = nodes["total"]
    sys_off = len(nodes["details"])
    title = f"节点掉线 · 系统自发掉线 {sys_off}/{total}"
    elements: list[dict[str, Any]] = [
        _div(
            f"总节点 {total} ｜ 系统自发掉线 {sys_off} ｜ "
            f"人为临时离线（忽略）{nodes.get('manual_offline_count', 0)}"
        ),
        {"tag": "hr"},
    ]
    for n in nodes["details"]:
        elements.append(
            _div(
                f"**{n['name']}** ｜ 执行器 {n.get('numExecutors')}\n"
                f"{n.get('offlineCauseReason', '')}"
            )
        )
    return {
        "config": {"wide_screen_mode": True},
        "header": {"title": {"tag": "plain_text", "content": title}, "template": "red"},
        "elements": elements,
    }


def _chunks(lst: list[dict[str, Any]], size: int = CARD_CHUNK_SIZE) -> list[list[dict[str, Any]]]:
    """按 size 切片；空列表返回 ``[]``（0 条不发卡，由调用方跳过）。"""
    if not lst:
        return []
    return [lst[i : i + size] for i in range(0, len(lst), size)]


def build_all_cards(report: dict[str, Any]) -> list[dict[str, Any]]:
    """构造全部待发卡片：四类各一组（按 5 条拆分，0 条跳过）+ 可选节点卡。"""
    cards: list[dict[str, Any]] = []
    cat_builds = {
        c: sorted(
            [b for b in report["builds"] if b.get("category") == c],
            key=lambda b: (b["job"], b["number"]),
        )
        for c in CATEGORIES
    }
    for cat in CATEGORIES:
        chunks = _chunks(cat_builds[cat])
        total = len(chunks)
        for i, ch in enumerate(chunks, 1):
            cards.append(build_category_card(report, cat, ch, i, total))
    nodes_card = build_nodes_card(report)
    if nodes_card is not None:
        cards.append(nodes_card)
    return cards


# ===================================================================
# webhook 发送
# ===================================================================


def _sign_webhook(secret: str, timestamp: int) -> str:
    """飞书自定义机器人加签：hmac_sha256(key="timestamp\\nsecret") → base64。

    官方算法：以 ``f"{timestamp}\\n{secret}"`` 为 HMAC key、空消息，sha256 digest 后 base64。
    """
    string_to_sign = f"{timestamp}\n{secret}"
    digest = hmac.new(string_to_sign.encode("utf-8"), digestmod=hashlib.sha256).digest()
    return base64.b64encode(digest).decode("utf-8")


def _append_query(url: str, params: dict[str, str]) -> str:
    """在 URL 上追加 query 参数（保留原有 query，如 webhook 自带的 token）。"""
    parsed = urllib.parse.urlparse(url)
    q = dict(urllib.parse.parse_qsl(parsed.query))
    q.update(params)
    return urllib.parse.urlunparse(parsed._replace(query=urllib.parse.urlencode(q)))


def _build_ssl_context(ca_bundle: str = "", verify_ssl: bool = True) -> ssl.SSLContext | None:
    """按配置构造 SSL context，应对 TLS 拦截代理（公司 CA 不在 Python 默认 CA bundle）。

    - ``verify_ssl=False`` → 不验证（webhook URL 本身即凭据，内网/代理环境可接受）
    - 指定 ``ca_bundle`` → 用该 CA 文件
    - 默认 → ``None``（urllib 用系统默认验证）
    """
    if not verify_ssl:
        return ssl._create_unverified_context()
    if ca_bundle:
        return ssl.create_default_context(cafile=ca_bundle)
    return None


def send_card(
    card: dict[str, Any],
    webhook_url: str,
    secret: str = "",
    dry_run: bool = False,
    urlopen: Any = None,
    ssl_context: ssl.SSLContext | None = None,
) -> bool:
    """把一张卡 POST 到飞书自定义机器人 webhook；dry_run 只打印不发。返回是否成功。

    - payload: ``{"msg_type":"interactive","card": <卡片>}``
    - 配了 ``secret``：URL 追加 ``timestamp`` / ``sign``（官方加签）
    - 成功判定：响应 ``code==0`` 或 ``StatusCode==0``（任一存在且非 0 视为失败）

    ``urlopen`` 仅测试注入（替换 urllib.request.urlopen）；生产路径走 urllib。
    ``ssl_context`` 由 notify_cards 按配置构造（见 _build_ssl_context）。
    """
    payload = json.dumps({"msg_type": "interactive", "card": card}, ensure_ascii=False)
    if dry_run:
        print(f"[dry-run] card to {webhook_url}:\n{payload}", file=sys.stderr)
        return True
    url = webhook_url
    if secret:
        timestamp = int(time.time())
        url = _append_query(
            url, {"timestamp": str(timestamp), "sign": _sign_webhook(secret, timestamp)}
        )
    req = urllib.request.Request(
        url,
        data=payload.encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    open_fn = urlopen or urllib.request.urlopen
    try:
        resp = open_fn(req, timeout=20, context=ssl_context)
    except urllib.error.HTTPError as exc:
        text = exc.read().decode("utf-8", "replace")
        print(f"error: webhook HTTP {exc.code}: {text}", file=sys.stderr)
        return False
    except (urllib.error.URLError, OSError) as exc:
        print(f"error: webhook send failed: {exc}", file=sys.stderr)
        return False
    try:
        result = json.loads(resp.read().decode("utf-8", "replace"))
    except (ValueError, AttributeError):
        # 响应非 JSON 但 HTTP 成功，保守计为发送成功
        return True
    code = result.get("code")
    status = result.get("StatusCode")
    if (code is not None and code != 0) or (status is not None and status != 0):
        print(f"error: webhook rejected: {result}", file=sys.stderr)
        return False
    return True


def notify_cards(
    report: dict[str, Any], cfg: dict[str, Any], dry_run: bool = False, urlopen: Any = None
) -> int:
    """构造并依次发送全部卡片；返回成功发送数。单卡失败不中断。

    按 ``cfg`` 的 ``ca_bundle`` / ``verify_ssl`` 构造 SSL context（应对公司代理/TLS 拦截环境）。
    """
    ssl_context = _build_ssl_context(cfg.get("ca_bundle", ""), cfg.get("verify_ssl", True))
    cards = build_all_cards(report)
    sent = 0
    for card in cards:
        if send_card(
            card, cfg["webhook_url"], cfg.get("secret", ""), dry_run, urlopen, ssl_context
        ):
            sent += 1
    print(f"notify: {sent}/{len(cards)} cards sent")
    return sent


# ===================================================================
# 主流程
# ===================================================================


def cmd_report(args: argparse.Namespace) -> int:
    rundir = args.rundir
    builds_file = os.path.join(rundir, "builds.json")
    if not os.path.isfile(builds_file):
        print(f"error: builds.json not found at {builds_file}", file=sys.stderr)
        return 1
    with open(builds_file, encoding="utf-8-sig") as fh:
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

    # ignored（用户中止 / 配置忽略）不计入顶部统计：total_failed 与 by_category
    # 均只覆盖 scm/compile/other/unknown 四类，四类之和 == total_failed。
    non_ignored = [b for b in builds if b.get("category") != IGNORED]
    cat = Counter(b.get("category") for b in non_ignored)
    summary = {
        "total_failed": len(non_ignored),
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

    # 通知：发飞书卡片（除非 --no-notify）
    if not args.no_notify:
        cfg = load_notify_config()
        if cfg and cfg.get("enabled", True):
            notify_cards(report, cfg, args.dry_run)
        elif cfg:
            print("notify: disabled by config (enabled=false)", file=sys.stderr)
        # 无 notify 配置时静默跳过（兼容只生成 report.json 的用法）

    print(f"summary: total={summary['total_failed']} by_category={summary['by_category']}")
    if nodes_section is not None:
        print(
            f"nodes: total={nodes_section['total']} "
            f"sys_offline={len(nodes_section['details'])} manual={nodes_section['manual_offline_count']}"
        )
    print(f"written: {rundir}/report.json")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="report: 合并 builds + analyses 渲染 report.json，并按配置发飞书卡片"
    )
    parser.add_argument("--rundir", required=True, help="运行目录（含 builds.json）")
    parser.add_argument(
        "--analyses", default=None, help="analyses.json 路径；缺省取 <rundir>/analyses.json"
    )
    parser.add_argument("--cli", default=None, help="jenkins_api.py 路径；提供则附带节点掉线检查")
    parser.add_argument("--system", default=None, help="Jenkins 实例名（透传给 jenkins_api.py）")
    parser.add_argument(
        "--no-notify",
        action="store_true",
        help="跳过飞书卡片发送（仅生成 report.json）",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="只打印卡片 JSON 不真发（不调 webhook）",
    )
    return parser


def main() -> int:
    return cmd_report(build_parser().parse_args())


if __name__ == "__main__":
    raise SystemExit(main())
