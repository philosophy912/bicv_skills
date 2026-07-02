"""Tests for report.py — analyses merge, nodes, cards, webhook send, CLI."""

from __future__ import annotations

import io
import json
import subprocess
import urllib.error
from unittest import mock

import report


def _proc(stdout: str = "", stderr: str = "", returncode: int = 0) -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(args=[], returncode=returncode, stdout=stdout, stderr=stderr)


def _build(job: str, number: int, **extra) -> dict:
    base = {"job": job, "number": number, "result": "FAILURE", "url": f"u/{number}/"}
    base.update(extra)
    return base


def _report(builds, nodes=None, since_hours=24):
    from collections import Counter

    c = Counter(b.get("category", "unknown") for b in builds)
    cat = {k: c.get(k, 0) for k in report.CATEGORIES}
    non_ignored = [b for b in builds if b.get("category") != "ignored"]
    r = {
        "generated_at": "2026-06-28T22:00:00",
        "window": {"start": "2026-06-27T22:00:00", "end": "2026-06-28T22:00:00"},
        "system": "default",
        "since_hours": since_hours,
        "summary": {"total_failed": len(non_ignored), "by_category": cat, "errors": 0},
        "builds": builds,
    }
    if nodes is not None:
        r["nodes"] = nodes
    return r


class _FakeResp:
    """模拟 urllib 的响应对象（有 read() 返回 bytes）。"""

    def __init__(self, body):
        self._body = body.encode("utf-8") if isinstance(body, str) else body

    def read(self):
        return self._body


# ===================================================================
# load_analyses
# ===================================================================


class TestLoadAnalyses:
    def test_missing_file_returns_empty(self, tmp_path):
        assert report.load_analyses(str(tmp_path / "nope.json")) == {}

    def test_loads_entries(self, tmp_path):
        p = tmp_path / "a.json"
        p.write_text(
            json.dumps([{"job": "J", "number": 1, "category": "scm"}, {"job": "K", "number": 2}]),
            encoding="utf-8",
        )
        out = report.load_analyses(str(p))
        assert set(out) == {("J", 1), ("K", 2)}

    def test_loads_entries_with_utf8_bom(self, tmp_path):
        # Windows PowerShell 保存的 analyses.json 常带 BOM，读取侧用 utf-8-sig 自动剥离。
        p = tmp_path / "a.json"
        p.write_text(
            "﻿" + json.dumps([{"job": "J", "number": 1, "category": "scm"}]),
            encoding="utf-8",
        )
        out = report.load_analyses(str(p))
        assert list(out) == [("J", 1)]

    def test_non_list_raises(self, tmp_path):
        p = tmp_path / "a.json"
        p.write_text(json.dumps({"not": "list"}), encoding="utf-8")
        try:
            report.load_analyses(str(p))
        except ValueError as exc:
            assert "list" in str(exc)
        else:
            raise AssertionError("expected ValueError")

    def test_entries_missing_keys_skipped(self, tmp_path):
        p = tmp_path / "a.json"
        p.write_text(json.dumps([{"category": "scm"}, {"job": "J", "number": 1}]), encoding="utf-8")
        out = report.load_analyses(str(p))
        assert list(out) == [("J", 1)]


# ===================================================================
# merge_builds
# ===================================================================


class TestMergeBuilds:
    def test_with_analysis(self):
        builds = [_build("J", 1)]
        analyses = {
            ("J", 1): {
                "category": "scm",
                "confidence": "high",
                "evidence": "ev",
                "log_excerpt": "ex",
            }
        }
        report.merge_builds(builds, analyses)
        assert builds[0]["category"] == "scm" and builds[0]["evidence"] == "ev"

    def test_missing_analysis_defaults_unknown(self):
        builds = [_build("J", 1)]
        report.merge_builds(builds, {})
        assert builds[0]["category"] == "unknown"
        assert builds[0]["confidence"] == "low"
        assert "未判定" in builds[0]["evidence"]

    def test_nonstandard_category_normalized_to_unknown(self):
        # agent 写入的非标准 category（如 'infra'）归一化为 unknown，
        # 保证 by_category 四类之和 == total_failed
        builds = [_build("J", 1)]
        analyses = {("J", 1): {"category": "infra", "evidence": "x"}}
        report.merge_builds(builds, analyses)
        assert builds[0]["category"] == "unknown"

    def test_ignored_category_preserved(self):
        # ignored（用户主动中止 / 配置忽略）是合法判定，不归一化为 unknown
        builds = [_build("J", 1)]
        analyses = {("J", 1): {"category": "ignored", "evidence": "Aborted by 张三"}}
        report.merge_builds(builds, analyses)
        assert builds[0]["category"] == "ignored"


# ===================================================================
# fetch_nodes
# ===================================================================


class TestFetchNodes:
    def _envelope(self, computers, total=3):
        return _proc(
            stdout=json.dumps({"system": "d", "data": {"total": total, "computers": computers}})
        )

    def test_normal(self):
        computers = [
            {"name": "n1", "offline": False, "temporarilyOffline": False},
            {
                "name": "n2",
                "offline": True,
                "temporarilyOffline": False,
                "offlineCauseReason": "broken",
            },
            {"name": "n3", "offline": True, "temporarilyOffline": True},
        ]
        with mock.patch("report.run_jenkins_cli", return_value=self._envelope(computers)):
            result = report.fetch_nodes("/c", None)
        assert result is not None
        total, sys_off, manual = result
        assert total == 3 and len(sys_off) == 1 and manual == 1
        assert sys_off[0]["name"] == "n2"

    def test_timeout_returns_none(self):
        with mock.patch(
            "report.run_jenkins_cli", side_effect=subprocess.TimeoutExpired(["x"], 180)
        ):
            assert report.fetch_nodes("/c", None) is None

    def test_exception_returns_none(self):
        with mock.patch("report.run_jenkins_cli", side_effect=OSError("x")):
            assert report.fetch_nodes("/c", None) is None

    def test_nonzero_returns_none(self):
        with mock.patch("report.run_jenkins_cli", return_value=_proc(returncode=1, stderr="e")):
            assert report.fetch_nodes("/c", None) is None

    def test_invalid_json_returns_none(self):
        with mock.patch("report.run_jenkins_cli", return_value=_proc(stdout="notjson")):
            assert report.fetch_nodes("/c", None) is None

    def test_non_dict_data_returns_none(self):
        with mock.patch(
            "report.run_jenkins_cli",
            return_value=_proc(stdout=json.dumps({"system": "d", "data": []})),
        ):
            assert report.fetch_nodes("/c", None) is None


# ===================================================================
# load_notify_config
# ===================================================================


class TestLoadNotifyConfig:
    def test_missing_file(self, tmp_path):
        assert report.load_notify_config(tmp_path / "nope.json") is None

    def test_no_notify_key(self, tmp_path):
        p = tmp_path / "c.json"
        p.write_text(json.dumps({"ignore_jobs": []}), encoding="utf-8")
        assert report.load_notify_config(p) is None

    def test_notify_without_webhook_url(self, tmp_path):
        p = tmp_path / "c.json"
        p.write_text(json.dumps({"notify": {"secret": "x"}}), encoding="utf-8")
        assert report.load_notify_config(p) is None

    def test_defaults_enabled_true_secret_empty(self, tmp_path):
        p = tmp_path / "c.json"
        p.write_text(json.dumps({"notify": {"webhook_url": "https://h/x"}}), encoding="utf-8")
        cfg = report.load_notify_config(p)
        assert cfg == {
            "webhook_url": "https://h/x",
            "secret": "",
            "enabled": True,
            "ca_bundle": "",
            "verify_ssl": True,
        }

    def test_explicit_secret_and_disabled(self, tmp_path):
        p = tmp_path / "c.json"
        p.write_text(
            json.dumps({"notify": {"webhook_url": "https://h/y", "secret": "s", "enabled": False}}),
            encoding="utf-8",
        )
        cfg = report.load_notify_config(p)
        assert cfg == {
            "webhook_url": "https://h/y",
            "secret": "s",
            "enabled": False,
            "ca_bundle": "",
            "verify_ssl": True,
        }

    def test_ca_bundle_and_verify_ssl(self, tmp_path):
        p = tmp_path / "c.json"
        p.write_text(
            json.dumps(
                {
                    "notify": {
                        "webhook_url": "https://h/z",
                        "ca_bundle": "/ca.pem",
                        "verify_ssl": False,
                    }
                }
            ),
            encoding="utf-8",
        )
        cfg = report.load_notify_config(p)
        assert cfg["ca_bundle"] == "/ca.pem" and cfg["verify_ssl"] is False

    def test_corrupt_json(self, tmp_path):
        p = tmp_path / "c.json"
        p.write_text("{not json", encoding="utf-8")
        assert report.load_notify_config(p) is None

    def test_non_dict_root(self, tmp_path):
        p = tmp_path / "c.json"
        p.write_text(json.dumps([1, 2]), encoding="utf-8")
        assert report.load_notify_config(p) is None

    def test_utf8_bom(self, tmp_path):
        p = tmp_path / "c.json"
        p.write_text("﻿" + json.dumps({"notify": {"webhook_url": "https://h/z"}}), encoding="utf-8")
        assert report.load_notify_config(p) == {
            "webhook_url": "https://h/z",
            "secret": "",
            "enabled": True,
            "ca_bundle": "",
            "verify_ssl": True,
        }


# ===================================================================
# _chunks
# ===================================================================


class TestChunks:
    def test_empty_returns_empty_list(self):
        # 0 条 → []（不发卡，由调用方跳过）
        assert report._chunks([]) == []

    def test_under_size_one_chunk(self):
        items = [{"x": i} for i in range(3)]
        assert report._chunks(items) == [items]

    def test_exact_multiple(self):
        items = [{"x": i} for i in range(10)]
        out = report._chunks(items)
        assert len(out) == 2 and len(out[0]) == 5 and len(out[1]) == 5

    def test_over_size_splits(self):
        # 16 条 → 4 张：5/5/5/1
        items = [{"x": i} for i in range(16)]
        out = report._chunks(items)
        assert [len(c) for c in out] == [5, 5, 5, 1]


# ===================================================================
# build_category_card
# ===================================================================


class TestBuildCategoryCard:
    def test_title_and_header_template(self):
        r = _report([_build("J", 1, category="scm", evidence="e")])
        card = report.build_category_card(r, "scm", r["builds"], 1, 1)
        assert card["header"]["template"] == "red"
        assert "scm" in card["header"]["title"]["content"]
        assert "1 条" in card["header"]["title"]["content"]
        assert "1/1" in card["header"]["title"]["content"]

    def test_summary_line_in_elements(self):
        r = _report([_build("J", 1, category="compile", evidence="e")])
        card = report.build_category_card(r, "compile", r["builds"], 1, 1)
        joined = json.dumps(card["elements"], ensure_ascii=False)
        assert "总失败 1" in joined
        assert "scm 0" in joined and "compile 1" in joined

    def test_empty_chunk_shows_none_message(self):
        r = _report([])
        card = report.build_category_card(r, "scm", [], 1, 1)
        joined = json.dumps(card["elements"], ensure_ascii=False)
        assert "本类无失败" in joined

    def test_chunk_entries_rendered(self):
        builds = [_build("JOB", n, category="scm", evidence=f"ev{n}") for n in range(1, 4)]
        r = _report(builds)
        card = report.build_category_card(r, "scm", builds, 1, 1)
        joined = json.dumps(card["elements"], ensure_ascii=False)
        assert "**JOB #1**" in joined
        assert "[打开](u/1/)" in joined
        # scm/other/unknown 明细带 evidence（判定依据）
        assert "ev1" in joined

    def test_compile_chunk_omits_evidence(self):
        # compile 明细只列 job + 链接，不带 evidence（细节看构建链接）
        builds = [_build("JOB", n, category="compile", evidence=f"ev{n}") for n in range(1, 4)]
        r = _report(builds)
        card = report.build_category_card(r, "compile", builds, 1, 1)
        joined = json.dumps(card["elements"], ensure_ascii=False)
        assert "**JOB #1**" in joined
        assert "ev1" not in joined


# ===================================================================
# build_nodes_card
# ===================================================================


class TestBuildNodesCard:
    def test_no_nodes_returns_none(self):
        assert report.build_nodes_card(_report([])) is None

    def test_empty_details_returns_none(self):
        r = _report([], nodes={"total": 60, "details": [], "manual_offline_count": 0})
        assert report.build_nodes_card(r) is None

    def test_with_details(self):
        nodes = {
            "total": 60,
            "details": [{"name": "auto_test_2", "offlineCauseReason": "broken", "numExecutors": 1}],
            "manual_offline_count": 9,
        }
        r = _report([], nodes=nodes)
        card = report.build_nodes_card(r)
        assert card is not None
        assert card["header"]["template"] == "red"
        title = card["header"]["title"]["content"]
        assert "系统自发掉线 1/60" in title
        joined = json.dumps(card["elements"], ensure_ascii=False)
        assert "总节点 60" in joined
        assert "人为临时离线（忽略）9" in joined
        assert "**auto_test_2**" in joined
        assert "broken" in joined


# ===================================================================
# build_all_cards
# ===================================================================


class TestBuildAllCards:
    def test_empty_builds_no_cards(self):
        # 0 失败：四类均 0 条 → 不发任何卡；无节点卡 → 0 张
        cards = report.build_all_cards(_report([]))
        assert cards == []

    def test_category_split_into_chunks(self):
        # scm 7 条 → 2 张；其余 0 条不发 = 2 张
        builds = [_build("S", n, category="scm", evidence="e") for n in range(1, 8)]
        cards = report.build_all_cards(_report(builds))
        scm_cards = [c for c in cards if "scm" in c["header"]["title"]["content"]]
        assert len(scm_cards) == 2
        assert "1/2" in scm_cards[0]["header"]["title"]["content"]
        assert "2/2" in scm_cards[1]["header"]["title"]["content"]
        # 其它类 0 条不发
        assert len(cards) == 2

    def test_zero_category_not_emitted(self):
        # compile 有、其它 0：只发 compile 那一类
        builds = [
            _build("C", 1, category="compile", evidence="e"),
            _build("C", 2, category="compile", evidence="e"),
        ]
        cards = report.build_all_cards(_report(builds))
        assert len(cards) == 1
        assert "compile" in cards[0]["header"]["title"]["content"]

    def test_nodes_card_appended_when_present(self):
        nodes = {
            "total": 10,
            "details": [{"name": "n", "offlineCauseReason": "x", "numExecutors": 1}],
            "manual_offline_count": 0,
        }
        cards = report.build_all_cards(_report([], nodes=nodes))
        # 0 分类卡（四类均 0 条）+ 1 节点卡
        assert len(cards) == 1
        assert "节点掉线" in cards[-1]["header"]["title"]["content"]

    def test_category_order_preserved(self):
        builds = [
            _build("A", 1, category="other"),
            _build("B", 1, category="scm"),
            _build("C", 1, category="compile"),
            _build("D", 1, category="unknown"),
        ]
        cards = report.build_all_cards(_report(builds))
        order = [c["header"]["title"]["content"] for c in cards]
        # 顺序固定 scm/compile/other/unknown
        pos = {
            cat: next(i for i, t in enumerate(order) if f"· {cat} ·" in t)
            for cat in report.CATEGORIES
        }
        assert pos["scm"] < pos["compile"] < pos["other"] < pos["unknown"]


# ===================================================================
# _sign_webhook / _append_query
# ===================================================================


class TestSignWebhook:
    def test_matches_official_algorithm(self):
        # 官方：hmac_sha256(key="timestamp\nsecret") → base64；用独立重算交叉验证
        import base64
        import hashlib
        import hmac

        ts = 1700000000
        secret = "abc123"
        expected = base64.b64encode(
            hmac.new(f"{ts}\n{secret}".encode(), digestmod=hashlib.sha256).digest()
        ).decode()
        assert report._sign_webhook(secret, ts) == expected

    def test_different_secret_yields_different_sign(self):
        assert report._sign_webhook("a", 1) != report._sign_webhook("b", 1)


class TestAppendQuery:
    def test_preserves_existing_token(self):
        # webhook URL 自带 token，追加 timestamp/sign 不能丢
        url = "https://open.feishu.cn/open-apis/bot/v2/hook/xxx?token=abc"
        out = report._append_query(url, {"timestamp": "111", "sign": "yyy"})
        assert "token=abc" in out
        assert "timestamp=111" in out
        assert "sign=yyy" in out

    def test_no_existing_query(self):
        assert report._append_query("https://h/x", {"a": "1"}) == "https://h/x?a=1"


class TestBuildSslContext:
    def test_default_returns_none(self):
        assert report._build_ssl_context() is None

    def test_verify_off_returns_unverified(self):
        import ssl

        ctx = report._build_ssl_context("", False)
        assert isinstance(ctx, ssl.SSLContext)
        assert ctx.check_hostname is False  # 不验证

    def test_ca_bundle_uses_cafile(self):
        with mock.patch("report.ssl.create_default_context") as m:
            report._build_ssl_context("/some/ca.pem", True)
        m.assert_called_once_with(cafile="/some/ca.pem")


# ===================================================================
# send_card
# ===================================================================


class TestSendCard:
    def test_dry_run_does_not_open(self):
        urlopen = mock.Mock()
        ok = report.send_card({"x": 1}, "https://h/x", "", dry_run=True, urlopen=urlopen)
        assert ok is True
        urlopen.assert_not_called()

    def test_success_code_zero(self):
        urlopen = mock.Mock(return_value=_FakeResp('{"code":0,"msg":"success"}'))
        ok = report.send_card({"x": 1}, "https://h/x", "", urlopen=urlopen)
        assert ok is True
        urlopen.assert_called_once()
        req = urlopen.call_args[0][0]
        assert req.get_method() == "POST"
        assert req.header_items()  # 有 header（Content-Type）

    def test_success_legacy_status_code_zero(self):
        urlopen = mock.Mock(return_value=_FakeResp('{"StatusCode":0,"StatusMessage":"ok"}'))
        assert report.send_card({"x": 1}, "https://h/x", "", urlopen=urlopen) is True

    def test_rejected_nonzero_code(self, capsys):
        urlopen = mock.Mock(return_value=_FakeResp('{"code":19021,"msg":"sign mismatch"}'))
        ok = report.send_card({"x": 1}, "https://h/x", "wrong", urlopen=urlopen)
        assert ok is False
        assert "webhook rejected" in capsys.readouterr().err

    def test_http_error(self, capsys):
        fp = io.BytesIO(b'{"code":400}')
        err = urllib.error.HTTPError("u", 400, "Bad", {}, fp)
        urlopen = mock.Mock(side_effect=err)
        ok = report.send_card({"x": 1}, "https://h/x", "", urlopen=urlopen)
        assert ok is False
        assert "webhook HTTP 400" in capsys.readouterr().err

    def test_url_error(self, capsys):
        urlopen = mock.Mock(side_effect=urllib.error.URLError("timeout"))
        ok = report.send_card({"x": 1}, "https://h/x", "", urlopen=urlopen)
        assert ok is False
        assert "webhook send failed" in capsys.readouterr().err

    def test_secret_appends_sign_to_url(self):
        urlopen = mock.Mock(return_value=_FakeResp('{"code":0}'))
        report.send_card({"x": 1}, "https://h/x?token=t", "sec", urlopen=urlopen)
        url = urlopen.call_args[0][0].full_url
        assert "timestamp=" in url and "sign=" in url and "token=t" in url

    def test_no_secret_keeps_url_clean(self):
        urlopen = mock.Mock(return_value=_FakeResp('{"code":0}'))
        report.send_card({"x": 1}, "https://h/x?token=t", "", urlopen=urlopen)
        assert "sign=" not in urlopen.call_args[0][0].full_url

    def test_non_json_response_counts_as_success(self):
        # 响应非 JSON 但 HTTP 成功（飞书异常情况），保守计为发送成功
        urlopen = mock.Mock(return_value=_FakeResp("not json"))
        assert report.send_card({"x": 1}, "https://h/x", "", urlopen=urlopen) is True

    def test_ssl_context_passed_to_urlopen(self):
        # ssl_context 透传到 urlopen 的 context kwarg（公司代理/CA 场景）
        urlopen = mock.Mock(return_value=_FakeResp('{"code":0}'))
        ctx = mock.Mock()
        report.send_card({"x": 1}, "https://h/x", "", urlopen=urlopen, ssl_context=ctx)
        assert urlopen.call_args.kwargs.get("context") is ctx


# ===================================================================
# notify_cards
# ===================================================================


class TestNotifyCards:
    def _cfg(self):
        return {"webhook_url": "https://h/x", "secret": "", "enabled": True}

    def _four(self):
        # 四类各 1 条 → 4 张卡（0 条类不发）
        return [
            _build("J", 1, category="scm"),
            _build("J", 2, category="compile"),
            _build("J", 3, category="other"),
            _build("J", 4, category="unknown"),
        ]

    def test_counts_sent(self, capsys):
        urlopen = mock.Mock(return_value=_FakeResp('{"code":0}'))
        sent = report.notify_cards(_report(self._four()), self._cfg(), urlopen=urlopen)
        assert sent == 4
        assert urlopen.call_count == 4
        assert "4/4 cards sent" in capsys.readouterr().out

    def test_partial_failure_does_not_abort(self, capsys):
        urlopen = mock.Mock(
            side_effect=[
                _FakeResp('{"code":0}'),
                _FakeResp('{"code":19021}'),
                _FakeResp('{"code":0}'),
                _FakeResp('{"code":0}'),
            ]
        )
        sent = report.notify_cards(_report(self._four()), self._cfg(), urlopen=urlopen)
        assert sent == 3
        assert urlopen.call_count == 4

    def test_dry_run(self, capsys):
        urlopen = mock.Mock()
        sent = report.notify_cards(
            _report(self._four()), self._cfg(), dry_run=True, urlopen=urlopen
        )
        assert sent == 4
        urlopen.assert_not_called()
        assert "4/4 cards sent" in capsys.readouterr().out

    def test_zero_builds_sends_nothing(self, capsys):
        # 四类均 0 条 → 0 张卡，notify 只打印 0/0
        urlopen = mock.Mock(return_value=_FakeResp('{"code":0}'))
        sent = report.notify_cards(_report([]), self._cfg(), urlopen=urlopen)
        assert sent == 0
        urlopen.assert_not_called()
        assert "0/0 cards sent" in capsys.readouterr().out


# ===================================================================
# cmd_report
# ===================================================================


class TestCmdReport:
    def _setup(self, tmp_path, builds, analyses=None):
        (tmp_path / "builds.json").write_text(
            json.dumps(
                {
                    "generated_at": "2026-06-28T22:00:00",
                    "window": {"start": "s", "end": "e"},
                    "system": "default",
                    "since_hours": 24,
                    "builds": builds,
                    "errors": [],
                }
            ),
            encoding="utf-8",
        )
        if analyses is not None:
            (tmp_path / "analyses.json").write_text(json.dumps(analyses), encoding="utf-8")

    def _args(self, tmp_path, **over):
        base = dict(
            rundir=str(tmp_path),
            analyses=None,
            cli=None,
            system=None,
            no_notify=True,
            dry_run=False,
        )
        base.update(over)
        return mock.MagicMock(**base)

    def test_full_pipeline_with_nodes(self, tmp_path, capsys):
        builds = [_build("J", 1), _build("K", 2)]
        analyses = [
            {
                "job": "J",
                "number": 1,
                "category": "scm",
                "confidence": "high",
                "evidence": "ev",
                "log_excerpt": "ex",
            }
        ]
        self._setup(tmp_path, builds, analyses)

        node_env = _proc(
            stdout=json.dumps(
                {
                    "system": "d",
                    "data": {
                        "total": 2,
                        "computers": [
                            {
                                "name": "n1",
                                "offline": True,
                                "temporarilyOffline": False,
                                "offlineCauseReason": "x",
                                "numExecutors": 1,
                            }
                        ],
                    },
                }
            )
        )
        args = self._args(tmp_path, cli="/c")
        with mock.patch("report.run_jenkins_cli", return_value=node_env):
            rc = report.cmd_report(args)
        assert rc == 0
        out = capsys.readouterr().out
        assert "by_category=" in out and "nodes:" in out

        rep = json.loads((tmp_path / "report.json").read_text("utf-8"))
        assert rep["summary"]["by_category"]["scm"] == 1
        assert rep["summary"]["by_category"]["unknown"] == 1  # K 缺判定
        assert rep["nodes"]["total"] == 2

    def test_ignored_excluded_from_summary(self, tmp_path, capsys):
        # ignored（用户中止 / 配置忽略）不计入 total_failed / by_category，但仍保留在 builds
        builds = [_build("ABORT", 1), _build("SCM", 2)]
        analyses = [
            {
                "job": "ABORT",
                "number": 1,
                "category": "ignored",
                "confidence": "high",
                "evidence": "Aborted by 张三",
                "log_excerpt": "",
            },
            {
                "job": "SCM",
                "number": 2,
                "category": "scm",
                "confidence": "high",
                "evidence": "ev",
                "log_excerpt": "ex",
            },
        ]
        self._setup(tmp_path, builds, analyses)
        rc = report.cmd_report(self._args(tmp_path))
        assert rc == 0
        rep = json.loads((tmp_path / "report.json").read_text("utf-8"))
        s = rep["summary"]
        assert s["total_failed"] == 1  # 仅 scm，ignored 不计入
        assert s["by_category"] == {"scm": 1, "compile": 0, "other": 0, "unknown": 0}
        # ignored 仍保留在 report.json 的 builds 里（category == "ignored"）
        cats = {b["job"]: b["category"] for b in rep["builds"]}
        assert cats == {"ABORT": "ignored", "SCM": "scm"}

    def test_no_cli_no_nodes(self, tmp_path, capsys):
        builds = [_build("J", 1)]
        analyses = [
            {
                "job": "J",
                "number": 1,
                "category": "compile",
                "confidence": "high",
                "evidence": "ev",
                "log_excerpt": "ex",
            }
        ]
        self._setup(tmp_path, builds, analyses)
        rc = report.cmd_report(self._args(tmp_path))
        assert rc == 0
        rep = json.loads((tmp_path / "report.json").read_text("utf-8"))
        assert "nodes" not in rep

    def test_reads_builds_json_with_utf8_bom(self, tmp_path):
        # Windows PowerShell 保存的 builds.json 常带 BOM，读取侧用 utf-8-sig 自动剥离。
        (tmp_path / "builds.json").write_text(
            "﻿"
            + json.dumps(
                {
                    "generated_at": "t",
                    "window": {"start": "s", "end": "e"},
                    "system": "default",
                    "since_hours": 24,
                    "builds": [_build("J", 1)],
                    "errors": [],
                }
            ),
            encoding="utf-8",
        )
        rc = report.cmd_report(self._args(tmp_path))
        assert rc == 0
        rep = json.loads((tmp_path / "report.json").read_text("utf-8"))
        assert rep["summary"]["by_category"]["unknown"] == 1

    def test_missing_builds_json(self, tmp_path, capsys):
        rc = report.cmd_report(self._args(tmp_path))
        assert rc == 1
        assert "builds.json not found" in capsys.readouterr().err

    def test_builds_not_list(self, tmp_path, capsys):
        (tmp_path / "builds.json").write_text(json.dumps({"builds": "x"}), encoding="utf-8")
        rc = report.cmd_report(self._args(tmp_path))
        assert rc == 1
        assert "no builds[]" in capsys.readouterr().err

    def test_invalid_analyses(self, tmp_path, capsys):
        self._setup(tmp_path, [_build("J", 1)])
        (tmp_path / "analyses.json").write_text("{not list", encoding="utf-8")
        rc = report.cmd_report(self._args(tmp_path))
        assert rc == 1
        assert "analyses.json invalid" in capsys.readouterr().err

    def test_missing_analyses_all_unknown(self, tmp_path):
        self._setup(tmp_path, [_build("J", 1)])  # 不写 analyses.json
        rc = report.cmd_report(self._args(tmp_path))
        assert rc == 0
        rep = json.loads((tmp_path / "report.json").read_text("utf-8"))
        assert rep["summary"]["by_category"]["unknown"] == 1

    def test_notify_invoked_when_config_enabled(self, tmp_path, capsys):
        # 配置 enabled=True → 调 notify_cards → POST webhook（注入 urlopen 验证被调）
        self._setup(tmp_path, [_build("J", 1, category="scm", evidence="e")])
        cfg = {"webhook_url": "https://h/x", "secret": "", "enabled": True}
        fake = mock.Mock(return_value=_FakeResp('{"code":0}'))
        args = self._args(tmp_path, no_notify=False)
        with (
            mock.patch("report.load_notify_config", return_value=cfg),
            mock.patch("report.urllib.request.urlopen", fake),
        ):
            rc = report.cmd_report(args)
        assert rc == 0
        fake.assert_called()  # 真发了卡片
        assert "cards sent" in capsys.readouterr().out

    def test_notify_skipped_when_disabled(self, tmp_path, capsys):
        self._setup(tmp_path, [_build("J", 1)])
        cfg = {"webhook_url": "https://h/x", "secret": "", "enabled": False}
        args = self._args(tmp_path, no_notify=False)
        with (
            mock.patch("report.load_notify_config", return_value=cfg),
            mock.patch("report.urllib.request.urlopen") as fake,
        ):
            rc = report.cmd_report(args)
        assert rc == 0
        fake.assert_not_called()
        assert "disabled by config" in capsys.readouterr().err

    def test_notify_skipped_when_no_config(self, tmp_path, capsys):
        # 无 notify 配置：静默跳过，不报错
        self._setup(tmp_path, [_build("J", 1)])
        args = self._args(tmp_path, no_notify=False)
        with (
            mock.patch("report.load_notify_config", return_value=None),
            mock.patch("report.urllib.request.urlopen") as fake,
        ):
            rc = report.cmd_report(args)
        assert rc == 0
        fake.assert_not_called()

    def test_no_notify_flag_overrides_config(self, tmp_path, capsys):
        self._setup(tmp_path, [_build("J", 1)])
        args = self._args(tmp_path, no_notify=True)
        with (
            mock.patch("report.load_notify_config") as loader,
            mock.patch("report.urllib.request.urlopen") as fake,
        ):
            rc = report.cmd_report(args)
        assert rc == 0
        loader.assert_not_called()
        fake.assert_not_called()


# ===================================================================
# build_parser / main
# ===================================================================


class TestParserAndMain:
    def test_required_rundir(self):
        import sys

        with mock.patch.object(sys, "argv", ["report.py"]):
            try:
                report.build_parser().parse_args()
            except SystemExit as exc:
                assert exc.code != 0
            else:
                raise AssertionError("expected SystemExit")

    def test_defaults(self):
        import sys

        with mock.patch.object(sys, "argv", ["report.py", "--rundir", "/r"]):
            args = report.build_parser().parse_args()
        assert args.rundir == "/r"
        assert args.cli is None and args.analyses is None
        assert args.no_notify is False and args.dry_run is False

    def test_flags(self):
        import sys

        with mock.patch.object(
            sys, "argv", ["report.py", "--rundir", "/r", "--no-notify", "--dry-run"]
        ):
            args = report.build_parser().parse_args()
        assert args.no_notify is True and args.dry_run is True

    def test_main_invokes_cmd_report(self):
        args = mock.MagicMock()
        with (
            mock.patch("report.build_parser") as bp,
            mock.patch("report.cmd_report", return_value=0) as cc,
        ):
            bp.return_value.parse_args.return_value = args
            assert report.main() == 0
        cc.assert_called_once_with(args)
