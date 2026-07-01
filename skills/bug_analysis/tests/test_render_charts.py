"""Tests for render_charts.py — font resolution, pagination, pie/grouped-bar
primitives, section renderers, and the CLI envelope."""

from __future__ import annotations

import argparse
import json
import types
from pathlib import Path
from unittest import mock

import pytest
import render_charts as rc

# ---------------------------------------------------------------------------
# Fixtures / payloads
# ---------------------------------------------------------------------------


def _submissions_payload() -> dict:
    return {
        "window": {"start": "2026-06-22 00:00:00", "end": "2026-06-26 23:59:59"},
        "zentao": {
            "instance_id": 1,
            "total": 3,
            "by_user": {"郭礼香": 2, "周嘉敏": 1},
            "by_project": {"B30X-F09": 2, "N53TB": 1},
            "severe": {"total": 1, "bugs": []},
            "bugs": [],
        },
        "redmine": {
            "instance_id": 2,
            "total": 1,
            "by_user": {"郭礼香": 1},
            "by_project": {"B30X-F09": 1},
            "severe": {"total": 0, "issues": []},
            "issues": [],
        },
    }


def _closures_payload() -> dict:
    return {
        "window": {"start": "2026-06-22 00:00:00", "end": "2026-06-26 23:59:59"},
        "zentao": {
            "instance_id": 1,
            "total": 2,
            "by_user": {"郭礼香": 2},
            "by_project": {"B30X-F09": 2},
            "bugs": [],
        },
        "redmine": {
            "instance_id": 2,
            "total": 0,
            "by_user": {},
            "by_project": {},
            "issues": [],
        },
    }


def _fonts(*names: str) -> list:
    return [types.SimpleNamespace(name=n) for n in names]


# ---------------------------------------------------------------------------
# Pure helpers
# ===========================================================================


class TestPureHelpers:
    def test_sort_desc_value_then_name(self):
        assert rc.sort_desc({"a": 3, "b": 1, "c": 3}) == [("a", 3), ("c", 3), ("b", 1)]

    def test_merge_counter_accumulates_and_skips_none(self):
        assert rc.merge_counter({"a": 2}, {"a": 1, "b": 3}, None) == {"a": 3, "b": 3}

    def test_paginate_empty(self):
        assert rc.paginate([], 5) == []

    def test_paginate_single_page(self):
        assert rc.paginate([1, 2, 3], 5) == [[1, 2, 3]]

    def test_paginate_multi_page(self):
        assert rc.paginate(list(range(7)), 3) == [[0, 1, 2], [3, 4, 5], [6]]

    def test_paginate_zero_size_means_no_paging(self):
        assert rc.paginate([1, 2], 0) == [[1, 2]]

    def test_truncate_label_short_unchanged(self):
        assert rc.truncate_label("短") == "短"

    def test_truncate_label_long_ellipsis(self):
        out = rc.truncate_label("abcdefghij", 5)
        assert out.endswith("…") and len(out) == 5

    def test_short_window_formats(self):
        d = {"window": {"start": "2026-06-22 00:00:00", "end": "2026-06-26 23:59:59"}}
        assert rc._short_window(d) == "06-22~06-26"

    def test_short_window_empty(self):
        assert rc._short_window({}) == ""


class TestTopNWithOther:
    def test_under_n_no_merge(self):
        assert rc.top_n_with_other({"a": 2, "b": 1}, 9) == [("a", 2), ("b", 1)]

    def test_over_n_merges_other(self):
        counter = {f"p{i}": 10 - i for i in range(12)}  # 12 项
        out = rc.top_n_with_other(counter, 9)
        assert len(out) == 10  # 9 + 其他
        assert out[-1] == ("其他", sum(10 - i for i in range(9, 12)))

    def test_empty(self):
        assert rc.top_n_with_other({}, 9) == []


# ---------------------------------------------------------------------------
# Font resolution
# ===========================================================================


class TestFindCjkFont:
    def test_hit_candidate(self):
        with mock.patch.object(rc.font_manager.fontManager, "ttflist", _fonts("PingFang SC")):
            assert rc._find_cjk_font() == "PingFang SC"

    def test_miss_no_assets_returns_none(self, tmp_path):
        with (
            mock.patch.object(rc.font_manager.fontManager, "ttflist", _fonts("SomeFont")),
            mock.patch.object(rc, "ASSETS_FONTS_DIR", tmp_path),
        ):
            assert rc._find_cjk_font() is None

    def test_assets_fallback(self, tmp_path):
        fonts = tmp_path / "fonts"
        fonts.mkdir()
        (fonts / "Noto.otf").write_text("")
        with (
            mock.patch.object(rc.font_manager.fontManager, "ttflist", _fonts("X")),
            mock.patch.object(rc, "ASSETS_FONTS_DIR", fonts),
        ):
            assert rc._find_cjk_font().endswith("Noto.otf")


class TestResolveFont:
    def test_found(self):
        with mock.patch.object(rc, "_find_cjk_font", return_value="PingFang SC"):
            assert rc.resolve_font() == "PingFang SC"

    def test_missing_raises(self):
        with mock.patch.object(rc, "_find_cjk_font", return_value=None):
            with pytest.raises(rc.RenderError, match="中文字体"):
                rc.resolve_font()


class TestApplyFont:
    def test_name_only_sets_rcparams(self):
        with mock.patch.object(rc, "plt") as m_plt:
            rc._apply_font("PingFang SC")
        assert m_plt.rcParams.__setitem__.call_count >= 1

    def test_path_font_registers(self, tmp_path):
        f = tmp_path / "my.ttf"
        f.write_text("")
        with mock.patch.object(rc, "font_manager") as m_fm, mock.patch.object(rc, "plt"):
            rc._apply_font(str(f))
        m_fm.fontManager.addfont.assert_called_once_with(str(f))

    def test_path_font_addfont_failure_swallowed(self, tmp_path):
        f = tmp_path / "my.ttf"
        f.write_text("")
        with mock.patch.object(rc, "font_manager") as m_fm, mock.patch.object(rc, "plt"):
            m_fm.fontManager.addfont.side_effect = RuntimeError("nope")
            rc._apply_font(str(f))  # 不应抛


# ---------------------------------------------------------------------------
# Output dir
# ===========================================================================


class TestResolveOutputDir:
    def test_custom(self, tmp_path):
        d = rc.resolve_output_dir(str(tmp_path / "out"))
        assert d.exists() and d == tmp_path / "out"

    def test_common_config_with_mapping(self, tmp_path):
        bicv = tmp_path / ".bicv"
        bicv.mkdir()
        (bicv / "common.json").write_text(
            json.dumps({"output_root": str(tmp_path / "root"), "skills": {"bug_analysis": "bda"}})
        )
        with mock.patch.object(rc.Path, "home", return_value=tmp_path):
            d = rc.resolve_output_dir(None)
        assert d == tmp_path / "root" / "bda" and d.exists()

    def test_common_config_with_utf8_bom(self, tmp_path):
        # Windows PowerShell 保存的 common.json 常带 BOM，读取侧用 utf-8-sig 自动剥离。
        bicv = tmp_path / ".bicv"
        bicv.mkdir()
        (bicv / "common.json").write_text(
            "﻿" + json.dumps({"output_root": str(tmp_path / "root")}), encoding="utf-8"
        )
        with mock.patch.object(rc.Path, "home", return_value=tmp_path):
            d = rc.resolve_output_dir(None)
        assert d == tmp_path / "root" / "bug_analysis"

    def test_default_subdir_when_unmapped(self, tmp_path):
        bicv = tmp_path / ".bicv"
        bicv.mkdir()
        (bicv / "common.json").write_text(json.dumps({"output_root": str(tmp_path / "root")}))
        with mock.patch.object(rc.Path, "home", return_value=tmp_path):
            d = rc.resolve_output_dir(None)
        assert d == tmp_path / "root" / "bug_analysis"

    def test_missing_output_root_raises(self, tmp_path):
        bicv = tmp_path / ".bicv"
        bicv.mkdir()
        (bicv / "common.json").write_text(json.dumps({}))
        with mock.patch.object(rc.Path, "home", return_value=tmp_path):
            with pytest.raises(rc.RenderError, match="output_root"):
                rc.resolve_output_dir(None)

    def test_missing_config_raises(self, tmp_path):
        with mock.patch.object(rc.Path, "home", return_value=tmp_path):
            with pytest.raises(rc.RenderError, match="配置文件不存在"):
                rc.resolve_output_dir(None)

    def test_bad_json_raises(self, tmp_path):
        bicv = tmp_path / ".bicv"
        bicv.mkdir()
        (bicv / "common.json").write_text("{bad")
        with mock.patch.object(rc.Path, "home", return_value=tmp_path):
            with pytest.raises(rc.RenderError, match="JSON"):
                rc.resolve_output_dir(None)


# ---------------------------------------------------------------------------
# Drawing primitives（整体 mock plt）
# ===========================================================================


class TestRenderBar:
    def test_calls_savefig_and_returns_path(self, tmp_path):
        fig, ax = mock.MagicMock(), mock.MagicMock()
        with mock.patch.object(rc, "plt") as m_plt:
            m_plt.subplots.return_value = (fig, ax)
            out = tmp_path / "bar.png"
            res = rc.render_bar([("郭礼香", 17), ("周嘉敏", 14)], "标题", out, "PingFang SC")
        assert res == out
        fig.savefig.assert_called_once_with(out, dpi=150)
        m_plt.close.assert_called_once_with(fig)

    def test_empty_data_returns_path_without_drawing(self, tmp_path):
        out = tmp_path / "x.png"
        with mock.patch.object(rc, "plt"):
            assert rc.render_bar([], "t", out, "f") == out


class TestRenderPie:
    def test_calls_savefig_and_returns_path(self, tmp_path):
        fig, ax = mock.MagicMock(), mock.MagicMock()
        with mock.patch.object(rc, "plt") as m_plt:
            m_plt.subplots.return_value = (fig, ax)
            out = tmp_path / "pie.png"
            res = rc.render_pie([("A", 3), ("B", 1)], "标题", out, "f")
        assert res == out
        ax.pie.assert_called_once()
        fig.savefig.assert_called_once_with(out, dpi=150)

    def test_empty_data_returns_path(self, tmp_path):
        out = tmp_path / "x.png"
        with mock.patch.object(rc, "plt"):
            assert rc.render_pie([], "t", out, "f") == out


class TestRenderGroupedBar:
    def test_calls_savefig_and_returns_path(self, tmp_path):
        fig, ax = mock.MagicMock(), mock.MagicMock()
        with mock.patch.object(rc, "plt") as m_plt:
            m_plt.subplots.return_value = (fig, ax)
            out = tmp_path / "g.png"
            res = rc.render_grouped_bar({"A": 3}, {"A": 1, "B": 2}, "标题", out, "f")
        assert res == out
        assert ax.bar.call_count == 2  # 提交 + 关闭两组
        fig.savefig.assert_called_once_with(out, dpi=150)

    def test_empty_returns_path_without_drawing(self, tmp_path):
        out = tmp_path / "x.png"
        with mock.patch.object(rc, "plt"):
            assert rc.render_grouped_bar({}, {}, "t", out, "f") == out


# ---------------------------------------------------------------------------
# Emit (pagination + filename)
# ===========================================================================


class TestClearOldPages:
    def test_removes_matching_old_files(self, tmp_path):
        (tmp_path / "stem.png").write_text("old")
        (tmp_path / "stem_p1.png").write_text("old")
        (tmp_path / "stem_p2.png").write_text("old")
        (tmp_path / "other.png").write_text("keep")
        rc._clear_old_pages(tmp_path, "stem")
        assert {p.name for p in tmp_path.iterdir()} == {"other.png"}

    def test_no_match_is_noop(self, tmp_path):
        (tmp_path / "other.png").write_text("x")
        rc._clear_old_pages(tmp_path, "stem")  # 不应抛
        assert (tmp_path / "other.png").exists()


class TestEmitBars:
    def test_single_page_no_suffix(self, tmp_path):
        with mock.patch.object(rc, "render_bar", return_value=Path("x")) as m:
            paths = rc._emit_bars({"a": 1}, "t", tmp_path, "stem", "f")
        assert paths == [str(tmp_path / "stem.png")]
        assert m.call_count == 1

    def test_multi_page_suffix(self, tmp_path):
        counter = {f"u{i}": i for i in range(30)}  # 30 > BAR_PAGE_SIZE(25)
        with mock.patch.object(rc, "render_bar", return_value=Path("x")) as m:
            paths = rc._emit_bars(counter, "t", tmp_path, "stem", "f")
        assert len(paths) == 2
        assert paths[0].endswith("stem_p1.png") and paths[1].endswith("stem_p2.png")
        assert m.call_count == 2

    def test_clears_old_pages_before_rendering(self, tmp_path):
        (tmp_path / "stem_p1.png").write_text("old")
        (tmp_path / "stem_p2.png").write_text("old")
        with mock.patch.object(rc, "render_bar", return_value=Path("x")):
            paths = rc._emit_bars({"a": 1}, "t", tmp_path, "stem", "f")
        assert paths == [str(tmp_path / "stem.png")]
        assert not (tmp_path / "stem_p1.png").exists()
        assert not (tmp_path / "stem_p2.png").exists()


class TestEmitSingle:
    def test_empty_returns_empty(self, tmp_path):
        draw = mock.MagicMock()
        assert rc._emit_single([], "t", tmp_path, "stem", "f", draw) == []
        draw.assert_not_called()

    def test_non_empty_calls_draw(self, tmp_path):
        draw = mock.MagicMock(return_value=Path("x"))
        paths = rc._emit_single([("A", 1)], "t", tmp_path, "stem", "f", draw)
        assert paths == [str(tmp_path / "stem.png")]
        draw.assert_called_once()

    def test_clears_old_pages(self, tmp_path):
        (tmp_path / "stem.png").write_text("old")
        (tmp_path / "stem_p1.png").write_text("old")
        draw = mock.MagicMock(return_value=Path("x"))
        rc._emit_single([("A", 1)], "t", tmp_path, "stem", "f", draw)
        assert not (tmp_path / "stem_p1.png").exists()


# ---------------------------------------------------------------------------
# Section renderers
# ===========================================================================


class TestSectionRenderers:
    def test_submissions_emits_three(self, tmp_path):
        with (
            mock.patch.object(rc, "render_bar", return_value=Path("x")),
            mock.patch.object(rc, "render_pie", return_value=Path("y")),
        ):
            charts = rc.render_submissions(
                _submissions_payload(), tmp_path, "PingFang SC", "20260626"
            )
        assert {
            "submissions_by_user",
            "submissions_by_project",
            "severe_ratio",
        } <= set(charts)

    def test_submissions_empty_skips(self, tmp_path):
        with (
            mock.patch.object(rc, "render_bar") as m_bar,
            mock.patch.object(rc, "render_pie") as m_pie,
        ):
            charts = rc.render_submissions(
                {"window": {}, "zentao": {"by_user": {}}, "redmine": {}}, tmp_path, "f", "d"
            )
        assert charts == {}
        m_bar.assert_not_called()
        m_pie.assert_not_called()

    def test_submissions_severe_ratio_skipped_when_zero_total(self, tmp_path):
        # total=0 时不画严重占比饼
        data = {
            "window": {},
            "zentao": {"by_user": {"A": 1}, "total": 0, "severe": {"total": 0}},
            "redmine": {},
        }
        with (
            mock.patch.object(rc, "render_bar", return_value=Path("x")),
            mock.patch.object(rc, "render_pie", return_value=Path("y")),
        ):
            charts = rc.render_submissions(data, tmp_path, "f", "d")
        # total=0 → severe_ratio 不出；by_user 有值但 by_project 空 → 只出 by_user
        assert "severe_ratio" not in charts
        assert "submissions_by_user" in charts

    def test_vs_closures_emits(self, tmp_path):
        with (
            mock.patch.object(rc, "render_grouped_bar", return_value=Path("x")),
            mock.patch.object(rc, "render_pie", return_value=Path("y")),
        ):
            charts = rc.render_vs_closures(
                _submissions_payload(), _closures_payload(), tmp_path, "f", "20260626"
            )
        assert "submissions_vs_closures" in charts
        assert "closures_by_user" in charts

    def test_vs_closures_empty_skips(self, tmp_path):
        with mock.patch.object(rc, "render_grouped_bar") as m:
            charts = rc.render_vs_closures(None, None, tmp_path, "f", "d")
        assert charts == {}
        m.assert_not_called()


# ---------------------------------------------------------------------------
# read_json_file
# ===========================================================================


class TestReadJson:
    def test_ok(self, tmp_path):
        f = tmp_path / "a.json"
        f.write_text(json.dumps({"x": 1}))
        assert rc.read_json_file(str(f)) == {"x": 1}

    def test_ok_with_utf8_bom(self, tmp_path):
        # Windows PowerShell 保存的 JSON 常带 BOM，读取侧用 utf-8-sig 自动剥离。
        f = tmp_path / "a.json"
        f.write_text("﻿" + json.dumps({"x": 1}), encoding="utf-8")
        assert rc.read_json_file(str(f)) == {"x": 1}

    def test_missing_raises(self):
        with pytest.raises(rc.RenderError, match="不存在"):
            rc.read_json_file("/no/such/file.json")

    def test_bad_json_raises(self, tmp_path):
        f = tmp_path / "a.json"
        f.write_text("{bad")
        with pytest.raises(rc.RenderError, match="JSON"):
            rc.read_json_file(str(f))


# ---------------------------------------------------------------------------
# cmd_render / main
# ===========================================================================


def _ns(**kw) -> argparse.Namespace:
    base = {"submissions": None, "closures": None, "out": None}
    base.update(kw)
    return argparse.Namespace(**base)


class TestCmdRender:
    def test_no_input_returns_1(self):
        assert rc.cmd_render(_ns()) == 1

    def test_font_error_returns_1(self, capsys):
        with mock.patch.object(rc, "resolve_font", side_effect=rc.RenderError("no font")):
            assert rc.cmd_render(_ns(submissions="x")) == 1
        assert "字体错误" in capsys.readouterr().err

    def test_outdir_error_returns_1(self):
        with (
            mock.patch.object(rc, "resolve_font", return_value="f"),
            mock.patch.object(rc, "resolve_output_dir", side_effect=rc.RenderError("no dir")),
        ):
            assert rc.cmd_render(_ns(submissions="x")) == 1

    def test_input_file_error_returns_1(self, tmp_path):
        with (
            mock.patch.object(rc, "resolve_font", return_value="f"),
            mock.patch.object(rc, "resolve_output_dir", return_value=tmp_path),
        ):
            assert rc.cmd_render(_ns(submissions="/nope.json")) == 1

    def test_render_error_returns_1(self, tmp_path):
        sub = tmp_path / "s.json"
        sub.write_text(json.dumps(_submissions_payload()))
        with (
            mock.patch.object(rc, "resolve_font", return_value="f"),
            mock.patch.object(rc, "resolve_output_dir", return_value=tmp_path),
            mock.patch.object(rc, "render_submissions", side_effect=rc.RenderError("boom")),
        ):
            assert rc.cmd_render(_ns(submissions=str(sub))) == 1

    def test_success_submissions_only(self, tmp_path, capsys):
        sub = tmp_path / "s.json"
        sub.write_text(json.dumps(_submissions_payload()))
        with (
            mock.patch.object(rc, "resolve_font", return_value="PingFang SC"),
            mock.patch.object(rc, "resolve_output_dir", return_value=tmp_path),
            mock.patch.object(rc, "render_bar", return_value=Path("x")),
            mock.patch.object(rc, "render_pie", return_value=Path("y")),
        ):
            code = rc.cmd_render(_ns(submissions=str(sub)))
        assert code == 0
        out = json.loads(capsys.readouterr().out)
        assert "submissions_by_user" in out["charts"]
        assert out["output_dir"] == str(tmp_path)

    def test_success_with_closures(self, tmp_path, capsys):
        sub = tmp_path / "s.json"
        sub.write_text(json.dumps(_submissions_payload()))
        cls = tmp_path / "c.json"
        cls.write_text(json.dumps(_closures_payload()))
        with (
            mock.patch.object(rc, "resolve_font", return_value="f"),
            mock.patch.object(rc, "resolve_output_dir", return_value=tmp_path),
            mock.patch.object(rc, "render_bar", return_value=Path("x")),
            mock.patch.object(rc, "render_pie", return_value=Path("y")),
            mock.patch.object(rc, "render_grouped_bar", return_value=Path("z")),
        ):
            code = rc.cmd_render(_ns(submissions=str(sub), closures=str(cls)))
        assert code == 0
        charts = json.loads(capsys.readouterr().out)["charts"]
        assert {
            "submissions_by_user",
            "submissions_by_project",
            "severe_ratio",
            "submissions_vs_closures",
            "closures_by_user",
        } <= set(charts)


class TestMain:
    def test_main_success(self, tmp_path):
        sub = tmp_path / "s.json"
        sub.write_text(json.dumps(_submissions_payload()))
        with (
            mock.patch.object(rc, "resolve_font", return_value="f"),
            mock.patch.object(rc, "resolve_output_dir", return_value=tmp_path),
            mock.patch.object(rc, "render_bar", return_value=Path("x")),
            mock.patch.object(rc, "render_pie", return_value=Path("y")),
        ):
            assert rc.main(["--submissions", str(sub), "--out", str(tmp_path)]) == 0

    def test_main_font_error(self):
        with mock.patch.object(rc, "resolve_font", side_effect=rc.RenderError("x")):
            assert rc.main(["--submissions", "a.json"]) == 1


# ---------------------------------------------------------------------------
# parser
# ===========================================================================


def test_build_parser_registers_all_args():
    ns = rc.build_parser().parse_args(["--submissions", "a", "--closures", "b", "--out", "c"])
    assert ns.submissions == "a" and ns.closures == "b" and ns.out == "c"
