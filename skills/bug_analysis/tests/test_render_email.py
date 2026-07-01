"""Tests for render_email.py — data helpers, HTML helpers, base64 image
embedding, section/overall builders, output dir, read_json, and CLI envelope."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from unittest import mock

import pytest
import render_email as re

# ---------------------------------------------------------------------------
# Payloads
# ---------------------------------------------------------------------------


def _sub_payload() -> dict:
    return {
        "window": {"start": "2026-06-22 00:00:00", "end": "2026-06-26 23:59:59"},
        "zentao": {
            "instance_id": 1,
            "total": 2,
            "by_user": {"张三": 2},
            "by_project": {"P1": 2},
            "severe": {
                "total": 1,
                "bugs": [
                    {
                        "id": 10,
                        "projectName": "P1",
                        "module": "m",
                        "openedBy": "张三",
                        "status": "激活",
                    }
                ],
            },
            "zero_submission_users": ["李四"],
            "bugs": [],
        },
        "redmine": {
            "instance_id": 2,
            "total": 1,
            "by_user": {"王五": 1},
            "by_project": {"P2": 1},
            "severe": {
                "total": 1,
                "issues": [
                    {
                        "issue_id": 20,
                        "project_name": "P2",
                        "subject": "s",
                        "author_name": "王五",
                        "status_name": "新建",
                    }
                ],
            },
            "zero_submission_users": [],
            "issues": [],
        },
    }


def _ovd_payload() -> dict:
    return {
        "overdue_days": 7,
        "zentao": {
            "total": 1,
            "bugs": [
                {
                    "id": 5,
                    "projectName": "P1",
                    "module": "m",
                    "assignedTo": "张三",
                    "days_since_action": 16,
                }
            ],
        },
        "redmine": {"total": 0, "issues": []},
    }


def _sev_payload() -> dict:
    return {
        "severe_values": {"zentao": ["1"], "redmine": ["严重-A"]},
        "zentao": {
            "total": 1,
            "bugs": [
                {"id": 30, "projectName": "P3", "module": "x", "openedBy": "赵六", "status": "激活"}
            ],
        },
        "redmine": {
            "total": 1,
            "issues": [
                {
                    "issue_id": 40,
                    "project_name": "P4",
                    "subject": "t",
                    "author_name": "钱七",
                    "status_name": "进行中",
                }
            ],
        },
    }


def _cls_payload() -> dict:
    return {
        "window": {"start": "2026-06-22 00:00:00", "end": "2026-06-26 23:59:59"},
        "zentao": {
            "instance_id": 1,
            "total": 1,
            "by_user": {"张三": 1},
            "by_project": {"P1": 1},
            "bugs": [{"id": 50, "projectName": "P1", "closedBy": "张三"}],
        },
        "redmine": {"total": 0, "by_user": {}, "by_project": {}, "issues": []},
    }


# ---------------------------------------------------------------------------
# Pure helpers
# ===========================================================================


class TestPureHelpers:
    def test_merge_counter(self):
        assert re.merge_counter({"a": 2}, {"a": 1, "b": 3}, None) == {"a": 3, "b": 3}

    def test_sort_desc(self):
        assert re.sort_desc({"a": 1, "b": 3}) == [("b", 3), ("a", 1)]

    def test_fmt_pct(self):
        assert re._fmt_pct(2, 4) == "50%"
        assert re._fmt_pct(1, 0) == "0%"

    def test_short_window(self):
        assert re._short_window(_sub_payload()) == "06-22~06-26"

    def test_short_window_empty(self):
        assert re._short_window({}) == ""

    def test_zero_users_merges_systems(self):
        assert re._zero_users(_sub_payload()) == ["李四"]


class TestOverdueRows:
    def test_merge_and_sort(self):
        rows = re._overdue_rows(_ovd_payload())
        assert rows[0]["id"] == "Z-5"
        assert rows[0]["days"] == 16

    def test_non_numeric_days_zero(self):
        data = {
            "zentao": {
                "bugs": [
                    {
                        "id": 1,
                        "projectName": "P",
                        "module": "M",
                        "assignedTo": "A",
                        "days_since_action": "N/A",
                    }
                ]
            }
        }
        assert re._overdue_rows(data)[0]["days"] == 0

    def test_redmine_uses_subject_and_prefix(self):
        data = {
            "redmine": {
                "issues": [
                    {
                        "issue_id": 99,
                        "project_name": "P",
                        "subject": "主题",
                        "assigned_to_name": "A",
                        "days_since_action": 5,
                    }
                ]
            }
        }
        rows = re._overdue_rows(data)
        assert rows[0]["id"] == "R-99"
        assert rows[0]["title"] == "主题"

    def test_zt_severity_label_and_new_fields(self):
        data = {
            "zentao": {
                "bugs": [
                    {
                        "id": 1,
                        "projectName": "P",
                        "title": "标题",
                        "assignedTo": "A",
                        "severity": 1,
                        "last_user_action": "2026-06-01",
                        "days_since_action": 16,
                    }
                ]
            }
        }
        r = re._overdue_rows(data)[0]
        assert r["title"] == "标题"
        assert r["severity"] == "S"  # severity=1 → S
        assert r["last_action"] == "2026-06-01"

    def test_rm_severity_label_suffix(self):
        # Redmine「立刻-A」→ A、「高-B」→ B
        data = {
            "redmine": {
                "issues": [
                    {
                        "issue_id": 1,
                        "project_name": "P",
                        "subject": "s",
                        "assigned_to_name": "A",
                        "priority_name": "立刻-A",
                        "days_since_action": 5,
                    }
                ]
            }
        }
        assert re._overdue_rows(data)[0]["severity"] == "A"


class TestSevereDetailRows:
    def test_submissions_path(self):
        rows = re._severe_detail_rows(_sub_payload(), ["severe"], ["severe"])
        ids = [r[0] for r in rows]
        assert "Z-10" in ids and "R-20" in ids

    def test_severe_command_path(self):
        rows = re._severe_detail_rows(_sev_payload(), [], [])
        ids = [r[0] for r in rows]
        assert "Z-30" in ids and "R-40" in ids

    def test_empty(self):
        assert re._severe_detail_rows({}, [], []) == []


class TestClosureRows:
    def test_merge(self):
        rows = re._closure_rows(_cls_payload())
        assert rows == [("Z-50", "P1", "张三")]

    def test_redmine_closed_by(self):
        data = {"redmine": {"issues": [{"issue_id": 7, "project_name": "P", "closed_by": "王五"}]}}
        assert re._closure_rows(data) == [("R-7", "P", "王五")]


class TestAllChartPaths:
    def test_collects_dedup(self):
        m = {"a": ["/p1.png", "/p2.png"], "b": ["/p1.png", "/p3.png"]}
        assert re.all_chart_paths(m) == ["/p1.png", "/p2.png", "/p3.png"]

    def test_empty(self):
        assert re.all_chart_paths({}) == []


# ---------------------------------------------------------------------------
# HTML helpers
# ===========================================================================


class TestHtmlHelpers:
    def test_esc(self):
        assert re._esc("a<b>&c") == "a&lt;b&gt;&amp;c"

    def test_esc_none(self):
        assert re._esc(None) == ""

    def test_html_table_with_rows(self):
        html = re._html_table(["A", "B"], [("1", "2")])
        assert "<th>A</th>" in html and "<td>1</td>" in html

    def test_html_table_empty(self):
        assert re._html_table(["A"], []) == "<p>（无）</p>"


class TestImgInline:
    def test_embeds_base64(self, tmp_path):
        img = tmp_path / "u.png"
        img.write_bytes(b"\x89PNG\r\n\x1a\n")
        html = re._img_inline(str(img))
        assert "data:image/png;base64," in html
        assert "alt='u.png'" in html

    def test_missing_returns_empty(self):
        assert re._img_inline("/no/such.png") == ""

    def test_jpg_mime(self, tmp_path):
        img = tmp_path / "x.jpg"
        img.write_bytes(b"\xff\xd8")
        assert "data:image/jpeg;base64," in re._img_inline(str(img))


class TestSectionImages:
    def test_embeds_existing(self, tmp_path):
        img = tmp_path / "u.png"
        img.write_bytes(b"\x89PNG")
        html = re._section_images({"x": [str(img)]}, ["x"])
        assert "data:image/png;base64," in html

    def test_missing_name_skips(self):
        assert re._section_images({}, ["nope"]) == ""

    def test_missing_file_skipped(self):
        # 图文件不存在 → 跳过（不报错、不输出 img）
        assert re._section_images({"x": ["/no/such.png"]}, ["x"]) == ""


# ---------------------------------------------------------------------------
# build_email_html
# ===========================================================================


class TestBuildEmailHtml:
    def test_all_sections_present(self):
        html = re.build_email_html(
            _sub_payload(), _ovd_payload(), _sev_payload(), _cls_payload(), None
        )
        assert "一、本周提交情况" in html
        assert "二、严重-本周" in html
        assert "三、严重-本组未关闭" in html
        assert "四、跟踪不及时" in html
        assert "五、本周关闭" in html

    def test_zero_submission_listed(self):
        html = re.build_email_html(_sub_payload(), None, None, None, None)
        assert "零提交" in html
        assert "李四" in html

    def test_images_embedded_base64(self, tmp_path):
        img = tmp_path / "bug_u.png"
        img.write_bytes(b"\x89PNG")
        charts = {"submissions_by_user": [str(img)]}
        html = re.build_email_html(_sub_payload(), None, None, None, charts)
        assert "data:image/png;base64," in html

    def test_no_data_returns_minimal_html(self):
        html = re.build_email_html(None, None, None, None, None)
        assert "缺陷分析周报" in html
        assert "一、本周提交情况" not in html

    def test_severe_detail_in_html(self):
        html = re.build_email_html(_sub_payload(), None, None, None, None)
        assert "Z-10" in html

    def test_overdue_table_in_html(self):
        html = re.build_email_html(None, _ovd_payload(), None, None, None)
        assert "Z-5" in html and "16" in html


# ---------------------------------------------------------------------------
# Output dir / read_json
# ===========================================================================


class TestResolveOutputDir:
    def test_custom(self, tmp_path):
        d = re.resolve_output_dir(str(tmp_path / "out"))
        assert d.exists() and d == tmp_path / "out"

    def test_common_config(self, tmp_path):
        bicv = tmp_path / ".bicv"
        bicv.mkdir()
        (bicv / "common.json").write_text(
            json.dumps({"output_root": str(tmp_path / "root"), "skills": {"bug_analysis": "bda"}})
        )
        with mock.patch.object(re.Path, "home", return_value=tmp_path):
            d = re.resolve_output_dir(None)
        assert d == tmp_path / "root" / "bda" and d.exists()

    def test_common_config_with_utf8_bom(self, tmp_path):
        # Windows PowerShell 保存的 common.json 常带 BOM，读取侧用 utf-8-sig 自动剥离。
        bicv = tmp_path / ".bicv"
        bicv.mkdir()
        (bicv / "common.json").write_text(
            "﻿" + json.dumps({"output_root": str(tmp_path / "root")}), encoding="utf-8"
        )
        with mock.patch.object(re.Path, "home", return_value=tmp_path):
            d = re.resolve_output_dir(None)
        assert d == tmp_path / "root" / "bug_analysis"

    def test_missing_output_root_raises(self, tmp_path):
        bicv = tmp_path / ".bicv"
        bicv.mkdir()
        (bicv / "common.json").write_text(json.dumps({}))
        with mock.patch.object(re.Path, "home", return_value=tmp_path):
            with pytest.raises(re.RenderError, match="output_root"):
                re.resolve_output_dir(None)

    def test_missing_config_raises(self, tmp_path):
        with mock.patch.object(re.Path, "home", return_value=tmp_path):
            with pytest.raises(re.RenderError, match="配置文件不存在"):
                re.resolve_output_dir(None)

    def test_bad_json_raises(self, tmp_path):
        bicv = tmp_path / ".bicv"
        bicv.mkdir()
        (bicv / "common.json").write_text("{bad")
        with mock.patch.object(re.Path, "home", return_value=tmp_path):
            with pytest.raises(re.RenderError, match="JSON"):
                re.resolve_output_dir(None)


class TestReadJson:
    def test_ok(self, tmp_path):
        f = tmp_path / "a.json"
        f.write_text(json.dumps({"x": 1}))
        assert re.read_json_file(str(f)) == {"x": 1}

    def test_ok_with_utf8_bom(self, tmp_path):
        # Windows PowerShell 保存的 JSON 常带 BOM，读取侧用 utf-8-sig 自动剥离。
        f = tmp_path / "a.json"
        f.write_text("﻿" + json.dumps({"x": 1}), encoding="utf-8")
        assert re.read_json_file(str(f)) == {"x": 1}

    def test_missing_raises(self):
        with pytest.raises(re.RenderError, match="不存在"):
            re.read_json_file("/no/such.json")

    def test_bad_json_raises(self, tmp_path):
        f = tmp_path / "a.json"
        f.write_text("{bad")
        with pytest.raises(re.RenderError, match="JSON"):
            re.read_json_file(str(f))


# ---------------------------------------------------------------------------
# cmd_render_email / main
# ===========================================================================


def _ns(**kw) -> argparse.Namespace:
    base = {
        "submissions": None,
        "overdue": None,
        "severe": None,
        "closures": None,
        "charts": None,
        "out": None,
    }
    base.update(kw)
    return argparse.Namespace(**base)


class TestCmdRenderEmail:
    def test_no_input_returns_1(self):
        assert re.cmd_render_email(_ns()) == 1

    def test_outdir_error_returns_1(self):
        with mock.patch.object(re, "resolve_output_dir", side_effect=re.RenderError("no dir")):
            assert re.cmd_render_email(_ns(submissions="x")) == 1

    def test_input_file_error_returns_1(self, tmp_path):
        with mock.patch.object(re, "resolve_output_dir", return_value=tmp_path):
            assert re.cmd_render_email(_ns(submissions="/nope.json")) == 1

    def test_success_full(self, tmp_path, capsys):
        sub = tmp_path / "s.json"
        sub.write_text(json.dumps(_sub_payload()))
        ovd = tmp_path / "o.json"
        ovd.write_text(json.dumps(_ovd_payload()))
        sev = tmp_path / "v.json"
        sev.write_text(json.dumps(_sev_payload()))
        cls = tmp_path / "c.json"
        cls.write_text(json.dumps(_cls_payload()))
        img = tmp_path / "bug_u.png"
        img.write_bytes(b"\x89PNG")
        charts = tmp_path / "ch.json"
        charts.write_text(json.dumps({"charts": {"submissions_by_user": [str(img)]}}))

        rc = re.cmd_render_email(
            _ns(
                submissions=str(sub),
                overdue=str(ovd),
                severe=str(sev),
                closures=str(cls),
                charts=str(charts),
                out=str(tmp_path),
            )
        )
        assert rc == 0
        out = json.loads(capsys.readouterr().out)
        assert ".html" in out["html_path"]
        assert str(img) in out["images"]
        html = Path(out["html_path"]).read_text("utf-8")
        assert "缺陷分析周报" in html and "data:image/png;base64," in html

    def test_success_submissions_only(self, tmp_path, capsys):
        sub = tmp_path / "s.json"
        sub.write_text(json.dumps(_sub_payload()))
        rc = re.cmd_render_email(_ns(submissions=str(sub), out=str(tmp_path)))
        assert rc == 0
        out = json.loads(capsys.readouterr().out)
        assert "html_path" in out
        assert out["images"] == []


class TestMain:
    def test_main_success(self, tmp_path):
        sub = tmp_path / "s.json"
        sub.write_text(json.dumps(_sub_payload()))
        assert re.main(["--submissions", str(sub), "--out", str(tmp_path)]) == 0

    def test_main_no_input(self):
        assert re.main([]) == 1


# ---------------------------------------------------------------------------
# parser
# ===========================================================================


def test_build_parser_registers_all_args():
    ns = re.build_parser().parse_args(
        [
            "--submissions",
            "a",
            "--overdue",
            "b",
            "--severe",
            "c",
            "--closures",
            "d",
            "--charts",
            "e",
            "--out",
            "f",
        ]
    )
    assert ns.submissions == "a" and ns.overdue == "b" and ns.severe == "c"
    assert ns.closures == "d" and ns.charts == "e" and ns.out == "f"
