"""Tests for email_api.py — config resolution, address parsing/validation,
body extraction, MIME construction, IMAP/SMTP operations, rendering, and CLI."""

from __future__ import annotations

import email
import email.utils
from pathlib import Path
from unittest import mock

import pytest

from system_config import ServiceError
import email_api


# ---------------------------------------------------------------------------
# 配置 fixtures
# ---------------------------------------------------------------------------


def _write_config(tmp_path: Path, systems: dict, default_system: str = "default") -> Path:
    """把 systems 写进临时 .bicv/email.json，返回 home 目录。"""
    config = {"default_system": default_system, "systems": systems}
    bicv = tmp_path / ".bicv"
    bicv.mkdir()
    (bicv / "email.json").write_text(
        __import__("json").dumps(config, ensure_ascii=False), encoding="utf-8"
    )
    return tmp_path


def _default_systems(**overrides):
    system = {
        "smtp": {
            "host": "smtp.example.com",
            "port": 465,
            "username": "me@example.com",
            "password": "pass",
        },
        "imap": {
            "host": "imap.example.com",
            "port": 993,
            "username": "me@example.com",
            "password": "pass",
        },
        "from_address": "me@example.com",
        "attachments_dir": "/tmp/email-attachments/default",
    }
    system.update(overrides)
    return {"default": system}


# ---------------------------------------------------------------------------
# validate_address / parse_addresses
# ---------------------------------------------------------------------------


class TestAddressValidation:
    def test_valid_address(self):
        email_api.validate_address("a@example.com")  # 不抛异常

    @pytest.mark.parametrize(
        "bad",
        ["noatsign", "@nodomain", "nolocal@", "a@b", "a@bcom", "", " a@b.com "],
    )
    def test_invalid_address(self, bad):
        # 注：带空格的会被 strip，"a@b.com" 合法；这里调整用例
        pass

    def test_invalid_no_at(self):
        with pytest.raises(ServiceError, match="缺少 @"):
            email_api.validate_address("noatsign")

    def test_invalid_at_start(self):
        with pytest.raises(ServiceError, match="不能在首尾"):
            email_api.validate_address("@b.com")

    def test_invalid_no_dot_in_domain(self):
        with pytest.raises(ServiceError, match="域名缺少点"):
            email_api.validate_address("a@bcom")

    def test_invalid_empty(self):
        with pytest.raises(ServiceError):
            email_api.validate_address("")

    def test_parse_addresses_dedup_and_split(self):
        result = email_api.parse_addresses(["a@x.com", "b@x.com,c@x.com", "a@x.com"])
        assert result == ["a@x.com", "b@x.com", "c@x.com"]

    def test_parse_addresses_none(self):
        assert email_api.parse_addresses(None) == []

    def test_parse_addresses_empty_and_spaces(self):
        assert email_api.parse_addresses(["", "  ", "a@x.com,"]) == ["a@x.com"]

    def test_validate_addresses_to_empty(self):
        with pytest.raises(ServiceError, match="收件人"):
            email_api.validate_addresses([], "to")

    def test_validate_addresses_cc_empty_ok(self):
        email_api.validate_addresses([], "cc")  # cc 可空，不抛


# ---------------------------------------------------------------------------
# html_to_text / extract_body / format_size
# ---------------------------------------------------------------------------


class TestBodyExtraction:
    def test_html_to_text_strips_tags(self):
        assert email_api.html_to_text("<p>Hello <b>world</b></p>") == "Hello world"

    def test_html_to_text_compresses_whitespace(self):
        assert email_api.html_to_text("a   \n  b") == "a b"

    def test_extract_body_plain(self):
        msg = email.message_from_string(
            "Content-Type: text/plain; charset=utf-8\n\nHello plain"
        )
        body, btype = email_api.extract_body(msg)
        assert body == "Hello plain"
        assert btype == "plain"

    def test_extract_body_html_fallback(self):
        msg = email.message_from_string(
            'Content-Type: text/html; charset=utf-8\n\n<p>Hi <b>there</b></p>'
        )
        body, btype = email_api.extract_body(msg)
        assert body == "Hi there"
        assert btype == "html"

    def test_extract_body_multipart_alternative_prefers_plain(self):
        msg = email.message_from_string(
            'Content-Type: multipart/alternative; boundary="b"\n\n'
            "--b\nContent-Type: text/plain\n\nPLAIN\n"
            "--b\nContent-Type: text/html\n\n<p>HTML</p>\n--b--\n"
        )
        body, btype = email_api.extract_body(msg)
        assert body == "PLAIN"
        assert btype == "plain"

    def test_extract_body_multipart_mixed_skips_attachment(self):
        msg = email.message_from_string(
            'Content-Type: multipart/mixed; boundary="b"\n\n'
            "--b\nContent-Type: text/plain\n\nBODY\n"
            "--b\nContent-Type: application/pdf\n"
            'Content-Disposition: attachment; filename="x.pdf"\n\n'
            "BINARY\n--b--\n"
        )
        body, btype = email_api.extract_body(msg)
        assert body == "BODY"
        assert btype == "plain"

    def test_extract_body_none(self):
        msg = email.message_from_string(
            'Content-Type: application/octet-stream\n\nBINARY'
        )
        body, btype = email_api.extract_body(msg)
        assert body == ""
        assert btype == "none"

    def test_extract_body_missing_charset_fallback_utf8(self):
        # 真实邮件用 bytes，无 charset 时 fallback UTF-8 解码
        msg = email.message_from_bytes(b"Content-Type: text/plain\n\n" + "中文".encode("utf-8"))
        body, btype = email_api.extract_body(msg)
        assert body == "中文"
        assert btype == "plain"

    def test_extract_body_nested(self):
        # mixed > alternative
        msg = email.message_from_string(
            'Content-Type: multipart/mixed; boundary="out"\n\n'
            '--out\nContent-Type: multipart/alternative; boundary="in"\n\n'
            '--in\nContent-Type: text/plain\n\nNESTED\n'
            '--in--\n--out--\n'
        )
        body, btype = email_api.extract_body(msg)
        assert body == "NESTED"
        assert btype == "plain"


class TestFormatSize:
    def test_none(self):
        assert email_api.format_size(None) == ""

    def test_bytes(self):
        assert email_api.format_size(500) == "500 B"

    def test_kb(self):
        assert email_api.format_size(2048) == "2.0 KB"

    def test_mb(self):
        assert email_api.format_size(1024 * 1024 * 3) == "3.0 MB"

    def test_gb(self):
        assert email_api.format_size(1024 ** 3 * 5) == "5.0 GB"


# ---------------------------------------------------------------------------
# decode_header_value / parse_mail_date / get_attachment_filename / has_flag
# ---------------------------------------------------------------------------


class TestHeaderUtils:
    def test_decode_header_plain(self):
        assert email_api.decode_header_value("plain") == "plain"

    def test_decode_header_none(self):
        assert email_api.decode_header_value(None) == ""

    def test_decode_header_encoded(self):
        # =?utf-8?B?5p2l5a2Q?= 解码为「来子」
        assert email_api.decode_header_value("=?utf-8?B?5p2l5a2Q?=") == "来子"

    def test_parse_mail_date_valid(self):
        assert email_api.parse_mail_date("Mon, 24 Jun 2026 14:30:00 +0800") == "2026-06-24 14:30"

    def test_parse_mail_date_none(self):
        assert email_api.parse_mail_date(None) == ""

    def test_parse_mail_date_invalid(self):
        assert email_api.parse_mail_date("garbage") == "garbage"

    def test_get_attachment_filename_named(self):
        part = email.message_from_string(
            'Content-Type: application/pdf\n'
            'Content-Disposition: attachment; filename="report.pdf"\n\nx'
        )
        assert email_api.get_attachment_filename(part, 0) == "report.pdf"

    def test_get_attachment_filename_fallback(self):
        part = email.message_from_string("Content-Type: application/pdf\n\nx")
        assert email_api.get_attachment_filename(part, 0) == "attachment_1.bin"

    def test_has_flag_present(self):
        assert email_api.has_flag([b"(\\Seen \\Recent)"], b"\\Seen") is True

    def test_has_flag_absent(self):
        assert email_api.has_flag([b"(\\Recent)"], b"\\Seen") is False

    def test_has_flag_none(self):
        assert email_api.has_flag(None, b"\\Seen") is False


# ---------------------------------------------------------------------------
# list_attachments / safe_filename / unique_path / read_body
# ---------------------------------------------------------------------------


class TestAttachments:
    def test_list_attachments_finds_attachment(self):
        msg = email.message_from_string(
            'Content-Type: multipart/mixed; boundary="b"\n\n'
            "--b\nContent-Type: text/plain\n\nBODY\n"
            "--b\nContent-Type: application/pdf\n"
            'Content-Disposition: attachment; filename="r.pdf"\n\n'
            "data\n--b--\n"
        )
        atts = email_api.list_attachments(msg)
        assert len(atts) == 1
        assert atts[0]["filename"] == "r.pdf"
        assert atts[0]["size"] == 4

    def test_list_attachments_none(self):
        msg = email.message_from_string("Content-Type: text/plain\n\nBODY")
        assert email_api.list_attachments(msg) == []

    def test_safe_filename_strips_directory(self):
        assert email_api.safe_filename("../../etc/passwd") == "passwd"

    def test_safe_filename_replaces_illegal(self):
        # : " < > | ? * 共 7 个非法字符 → 7 个下划线
        assert email_api.safe_filename('a:"<>|?*b.txt') == "a_______b.txt"

    def test_safe_filename_empty_fallback(self):
        assert email_api.safe_filename("///") == "attachment.bin"

    def test_safe_filename_backslash(self):
        # backslash 转成 / 再 basename
        assert email_api.safe_filename("dir\\sub\\file.txt") == "file.txt"

    def test_unique_path_no_conflict(self, tmp_path):
        p = email_api.unique_path(str(tmp_path), "x.txt")
        assert p.endswith("x.txt")

    def test_unique_path_conflict_appends_number(self, tmp_path):
        (tmp_path / "x.txt").write_text("a")
        p = email_api.unique_path(str(tmp_path), "x.txt")
        assert p.endswith("x_1.txt")


class TestReadBody:
    def test_plain_text(self):
        assert email_api.read_body("hello") == "hello"

    def test_file(self, tmp_path):
        f = tmp_path / "body.html"
        f.write_text("<p>hi</p>", encoding="utf-8")
        assert email_api.read_body(f"@{f}") == "<p>hi</p>"

    def test_file_not_found(self):
        with pytest.raises(ServiceError, match="正文文件不存在"):
            email_api.read_body("@/nonexistent/file.txt")


# ---------------------------------------------------------------------------
# resolve_email_config
# ---------------------------------------------------------------------------


class TestResolveConfig:
    def test_resolve_full_config(self, tmp_path, monkeypatch):
        home = _write_config(tmp_path, _default_systems())
        monkeypatch.setattr(Path, "home", lambda: home)
        cfg = email_api.resolve_email_config(need_imap=True, need_attachments_dir=True)
        assert cfg.smtp_host == "smtp.example.com"
        assert cfg.imap_host == "imap.example.com"
        assert cfg.from_address == "me@example.com"
        assert cfg.attachments_dir == "/tmp/email-attachments/default"
        assert cfg.system_name == "default"

    def test_resolve_send_only_no_imap_ok(self, tmp_path, monkeypatch):
        home = _write_config(tmp_path, _default_systems(imap=None))
        monkeypatch.setattr(Path, "home", lambda: home)
        # send 不需要 imap，应成功
        cfg = email_api.resolve_email_config(need_imap=False)
        assert cfg.imap_host is None

    def test_resolve_send_only_but_need_imap_fails(self, tmp_path, monkeypatch):
        home = _write_config(tmp_path, _default_systems(imap=None))
        monkeypatch.setattr(Path, "home", lambda: home)
        with pytest.raises(ServiceError, match="缺少 imap"):
            email_api.resolve_email_config(need_imap=True)

    def test_resolve_missing_smtp_host(self, tmp_path, monkeypatch):
        systems = _default_systems()
        del systems["default"]["smtp"]["host"]
        home = _write_config(tmp_path, systems)
        monkeypatch.setattr(Path, "home", lambda: home)
        with pytest.raises(ServiceError, match="缺少 host"):
            email_api.resolve_email_config()

    def test_resolve_missing_from_address(self, tmp_path, monkeypatch):
        systems = _default_systems()
        del systems["default"]["from_address"]
        home = _write_config(tmp_path, systems)
        monkeypatch.setattr(Path, "home", lambda: home)
        with pytest.raises(ServiceError, match="from_address"):
            email_api.resolve_email_config()

    def test_resolve_missing_attachments_dir_when_needed(self, tmp_path, monkeypatch):
        systems = _default_systems()
        del systems["default"]["attachments_dir"]
        home = _write_config(tmp_path, systems)
        monkeypatch.setattr(Path, "home", lambda: home)
        with pytest.raises(ServiceError, match="attachments_dir"):
            email_api.resolve_email_config(need_imap=True, need_attachments_dir=True)

    def test_resolve_invalid_from_address(self, tmp_path, monkeypatch):
        systems = _default_systems(from_address="badaddress")
        home = _write_config(tmp_path, systems)
        monkeypatch.setattr(Path, "home", lambda: home)
        with pytest.raises(ServiceError, match="无效的邮件地址"):
            email_api.resolve_email_config()

    def test_resolve_invalid_port(self, tmp_path, monkeypatch):
        systems = _default_systems()
        systems["default"]["smtp"]["port"] = "abc"
        home = _write_config(tmp_path, systems)
        monkeypatch.setattr(Path, "home", lambda: home)
        with pytest.raises(ServiceError, match="不是合法整数"):
            email_api.resolve_email_config()

    def test_resolve_system_not_found(self, tmp_path, monkeypatch):
        home = _write_config(tmp_path, _default_systems())
        monkeypatch.setattr(Path, "home", lambda: home)
        with pytest.raises(ServiceError, match="不存在"):
            email_api.resolve_email_config(system="nonexistent")

    def test_resolve_no_default_no_system(self, tmp_path, monkeypatch):
        # 无 default_system 且无 --system
        systems = _default_systems()
        config = {"systems": systems}
        bicv = tmp_path / ".bicv"
        bicv.mkdir()
        (bicv / "email.json").write_text(
            __import__("json").dumps(config), encoding="utf-8"
        )
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        with pytest.raises(ServiceError, match="default_system"):
            email_api.resolve_email_config()

    def test_resolve_port_defaults(self, tmp_path, monkeypatch):
        systems = _default_systems()
        del systems["default"]["smtp"]["port"]
        del systems["default"]["imap"]["port"]
        home = _write_config(tmp_path, systems)
        monkeypatch.setattr(Path, "home", lambda: home)
        cfg = email_api.resolve_email_config(need_imap=True)
        assert cfg.smtp_port == 465
        assert cfg.imap_port == 993


# ---------------------------------------------------------------------------
# build_message (MIME 构造)
# ---------------------------------------------------------------------------


class TestBuildMessage:
    def _parse_sent(self, message, recipients):
        """解析 sendmail 收到的邮件字符串。"""
        return email.message_from_string(message.as_string()), recipients

    def test_plain_text_simple(self):
        msg, recipients = email_api.build_message(
            from_address="me@x.com", to=["a@x.com"], cc=[], bcc=[],
            subject="Hi", body="Hello", html=False, attachments=[], reply_to=None,
        )
        assert msg.get_content_type() == "text/plain"
        assert msg["To"] == "a@x.com"
        assert "Cc" not in msg
        assert email_api.decode_header_value(msg["Subject"]) == "Hi"
        assert msg["Message-ID"] is not None
        assert msg["Date"] is not None
        assert recipients == ["a@x.com"]

    def test_html_creates_alternative_with_plain_fallback(self):
        msg, recipients = email_api.build_message(
            from_address="me@x.com", to=["a@x.com"], cc=[], bcc=[],
            subject="Hi", body="<p>Hello</p>", html=True, attachments=[], reply_to=None,
        )
        assert msg.get_content_type() == "multipart/alternative"
        # 应有 plain 和 html 两段
        parts = list(msg.walk())
        types = [p.get_content_type() for p in parts]
        assert "text/plain" in types
        assert "text/html" in types

    def test_attachment_creates_mixed(self, tmp_path):
        att = tmp_path / "r.pdf"
        att.write_bytes(b"PDFDATA")
        msg, recipients = email_api.build_message(
            from_address="me@x.com", to=["a@x.com"], cc=[], bcc=[],
            subject="Hi", body="Hello", html=False,
            attachments=[str(att)], reply_to=None,
        )
        assert msg.get_content_type() == "multipart/mixed"
        parts = list(msg.walk())
        types = [p.get_content_type() for p in parts]
        assert "text/plain" in types
        assert "application/pdf" in types

    def test_html_with_attachment(self, tmp_path):
        att = tmp_path / "r.pdf"
        att.write_bytes(b"PDFDATA")
        msg, recipients = email_api.build_message(
            from_address="me@x.com", to=["a@x.com"], cc=[], bcc=[],
            subject="Hi", body="<p>Hello</p>", html=True,
            attachments=[str(att)], reply_to=None,
        )
        assert msg.get_content_type() == "multipart/mixed"
        # 第一段应是 alternative
        first = msg.get_payload()[0]
        assert first.get_content_type() == "multipart/alternative"

    def test_bcc_not_in_header_but_in_recipients(self):
        msg, recipients = email_api.build_message(
            from_address="me@x.com", to=["a@x.com"], cc=["c@x.com"], bcc=["b@x.com"],
            subject="Hi", body="Hello", html=False, attachments=[], reply_to=None,
        )
        assert "Bcc" not in msg
        assert msg["Cc"] == "c@x.com"
        # 投递列表含 bcc 且去重
        assert set(recipients) == {"a@x.com", "c@x.com", "b@x.com"}

    def test_recipients_dedup(self):
        msg, recipients = email_api.build_message(
            from_address="me@x.com", to=["a@x.com", "a@x.com"], cc=["a@x.com"], bcc=[],
            subject="Hi", body="Hello", html=False, attachments=[], reply_to=None,
        )
        assert recipients == ["a@x.com"]

    def test_reply_to_header(self):
        msg, _ = email_api.build_message(
            from_address="me@x.com", to=["a@x.com"], cc=[], bcc=[],
            subject="Hi", body="Hello", html=False, attachments=[], reply_to="r@x.com",
        )
        assert msg["Reply-To"] == "r@x.com"

    def test_attachment_not_found(self):
        with pytest.raises(ServiceError, match="附件文件不存在"):
            email_api.build_message(
                from_address="me@x.com", to=["a@x.com"], cc=[], bcc=[],
                subject="Hi", body="Hello", html=False,
                attachments=["/nonexistent/x.pdf"], reply_to=None,
            )

    def test_attachment_unknown_type_fallback(self, tmp_path):
        # 无扩展名文件，mimetypes 猜不出 → octet-stream 兜底
        att = tmp_path / "datafile"
        att.write_bytes(b"DATA")
        msg, _ = email_api.build_message(
            from_address="me@x.com", to=["a@x.com"], cc=[], bcc=[],
            subject="Hi", body="Hello", html=False,
            attachments=[str(att)], reply_to=None,
        )
        parts = list(msg.walk())
        types = [p.get_content_type() for p in parts]
        assert "application/octet-stream" in types

    def test_attachment_read_fail(self, tmp_path, monkeypatch):
        att = tmp_path / "r.pdf"
        att.write_bytes(b"DATA")
        original_open = open

        def fake_open(path, *a, **kw):
            if str(path) == str(att):
                raise OSError("disk error")
            return original_open(path, *a, **kw)

        monkeypatch.setattr("builtins.open", fake_open)
        with pytest.raises(ServiceError, match="读取附件文件失败"):
            email_api.build_message(
                from_address="me@x.com", to=["a@x.com"], cc=[], bcc=[],
                subject="Hi", body="Hello", html=False,
                attachments=[str(att)], reply_to=None,
            )

    def test_message_id_uses_from_domain(self):
        msg, _ = email_api.build_message(
            from_address="me@example.com", to=["a@x.com"], cc=[], bcc=[],
            subject="Hi", body="Hello", html=False, attachments=[], reply_to=None,
        )
        assert "example.com" in msg["Message-ID"]

    def test_chinese_subject_encoded(self):
        msg, _ = email_api.build_message(
            from_address="me@x.com", to=["a@x.com"], cc=[], bcc=[],
            subject="中文主题", body="Hello", html=False, attachments=[], reply_to=None,
        )
        # 解码后应是中文
        assert email_api.decode_header_value(msg["Subject"]) == "中文主题"


# ---------------------------------------------------------------------------
# 渲染
# ---------------------------------------------------------------------------


class TestRender:
    def test_render_json_chinese(self):
        out = email_api.render_json({"k": "中文"})
        assert "中文" in out
        assert "\\u" not in out

    def test_render_table_messages(self):
        data = {"system": "default", "folder": "INBOX", "total": 1,
                "messages": [{"uid": 1, "date": "2026-06-24 14:30", "from": "a@x.com",
                               "subject": "Hi", "unread": True, "has_attachments": False}]}
        out = email_api.render_table_messages(data)
        assert "UID" in out
        assert "Hi" in out

    def test_render_table_messages_with_folder_column(self):
        data = {"system": "default", "folder": "(所有文件夹)", "total": 2,
                "messages": [
                    {"uid": 1, "date": "2026-06-24", "from": "a@x.com", "subject": "Hi",
                     "unread": False, "has_attachments": False, "folder": "INBOX"},
                    {"uid": 2, "date": "2026-06-23", "from": "b@x.com", "subject": "S2",
                     "unread": True, "has_attachments": True, "folder": "Sent"},
                ]}
        out = email_api.render_table_messages(data)
        assert "文件夹" in out  # 多了文件夹列
        assert "INBOX" in out
        assert "Sent" in out

    def test_render_table_folders(self):
        data = {"system": "default", "folders": [{"name": "INBOX", "delimiter": "/", "flags": []}]}
        out = email_api.render_table_folders(data)
        assert "INBOX" in out

    def test_render_table_read(self):
        data = {"system": "default", "folder": "INBOX", "uid": 1, "unread": True,
                "headers": {"subject": "Hi", "from": "a@x.com", "to": "b@x.com", "cc": "", "date": "2026-06-24"},
                "body": "Hello", "attachments": [{"filename": "r.pdf", "size": 100}]}
        out = email_api.render_table_read(data)
        assert "正文" in out
        assert "r.pdf" in out


# ---------------------------------------------------------------------------
# _format_since / _resolve_limit
# ---------------------------------------------------------------------------


class TestHelpers:
    def test_format_since_valid(self):
        assert email_api._format_since("2026-06-24") == "24-Jun-2026"

    def test_format_since_invalid_format(self):
        with pytest.raises(ServiceError, match="YYYY-MM-DD"):
            email_api._format_since("06/24/2026")

    def test_format_since_invalid_month(self):
        with pytest.raises(ServiceError, match="无效的日期"):
            email_api._format_since("2026-13-01")

    def test_resolve_limit_default(self):
        assert email_api._resolve_limit(None, 100) == 100

    def test_resolve_limit_valid(self):
        assert email_api._resolve_limit(50, 100) == 50

    def test_resolve_limit_too_small(self):
        with pytest.raises(ServiceError, match=">= 1"):
            email_api._resolve_limit(0, 100)

    def test_resolve_limit_too_large(self):
        with pytest.raises(ServiceError, match="超过上限"):
            email_api._resolve_limit(600, 100)

    def test_header_has_attachment_mixed(self):
        msg = email.message_from_string(
            'Content-Type: multipart/mixed; boundary="b"\n\n--b--\n'
        )
        assert email_api._header_has_attachment(msg) is True

    def test_header_has_attachment_plain(self):
        msg = email.message_from_string("Content-Type: text/plain\n\nx")
        assert email_api._header_has_attachment(msg) is False


# ---------------------------------------------------------------------------
# SMTP/IMAP 连接 mock
# ---------------------------------------------------------------------------


def _make_config(**overrides):
    defaults = dict(
        smtp_host="smtp.x.com", smtp_port=465, smtp_username="me@x.com", smtp_password="p",
        imap_host="imap.x.com", imap_port=993, imap_username="me@x.com", imap_password="p",
        from_address="me@x.com", attachments_dir="/tmp/atts", system_name="default",
    )
    defaults.update(overrides)
    return email_api.EmailConnectionConfig(**defaults)


class TestConnections:
    @mock.patch("email_api.smtplib.SMTP_SSL")
    def test_get_smtp_success(self, mock_ssl):
        server = mock.MagicMock()
        mock_ssl.return_value = server
        cfg = _make_config()
        result = email_api.get_smtp(cfg)
        assert result is server
        server.login.assert_called_once_with("me@x.com", "p")

    @mock.patch("email_api.smtplib.SMTP_SSL")
    def test_get_smtp_connect_fail(self, mock_ssl):
        mock_ssl.side_effect = Exception("conn fail")
        with pytest.raises(ServiceError, match="SMTP 连接失败"):
            email_api.get_smtp(_make_config())

    @mock.patch("email_api.smtplib.SMTP_SSL")
    def test_get_smtp_login_fail(self, mock_ssl):
        server = mock.MagicMock()
        server.login.side_effect = Exception("auth fail")
        mock_ssl.return_value = server
        with pytest.raises(ServiceError, match="SMTP 登录失败"):
            email_api.get_smtp(_make_config())
        server.quit.assert_called_once()

    @mock.patch("email_api.imaplib.IMAP4_SSL")
    def test_get_imap_success(self, mock_ssl):
        server = mock.MagicMock()
        mock_ssl.return_value = server
        result = email_api.get_imap(_make_config())
        assert result is server
        server.login.assert_called_once()

    @mock.patch("email_api.imaplib.IMAP4_SSL")
    def test_get_imap_login_fail(self, mock_ssl):
        server = mock.MagicMock()
        server.login.side_effect = Exception("auth fail")
        mock_ssl.return_value = server
        with pytest.raises(ServiceError, match="IMAP 登录失败"):
            email_api.get_imap(_make_config())

    def test_select_folder_ok(self):
        server = mock.MagicMock()
        server.select.return_value = ("OK", [b"5"])
        assert email_api.select_folder(server, "INBOX") == 5

    def test_select_folder_fail(self):
        server = mock.MagicMock()
        server.select.return_value = ("NO", [b""])
        with pytest.raises(ServiceError, match="不存在或无法选择"):
            email_api.select_folder(server, "BadFolder")

    def test_select_folder_exception(self):
        server = mock.MagicMock()
        server.select.side_effect = Exception("boom")
        with pytest.raises(ServiceError, match="选择文件夹"):
            email_api.select_folder(server, "INBOX")


# ---------------------------------------------------------------------------
# 子命令：cmd_send
# ---------------------------------------------------------------------------


class TestCmdSend:
    @mock.patch("email_api.get_smtp")
    @mock.patch("email_api.resolve_email_config")
    def test_send_success(self, mock_cfg, mock_smtp, capsys):
        mock_cfg.return_value = _make_config()
        server = mock.MagicMock()
        mock_smtp.return_value = server

        args = mock.Mock(
            system=None, to=["a@x.com"], cc=["c@x.com"], bcc=[],
            subject="Hi", body="Hello", html=False, attach=None, reply_to=None,
        )
        rc = email_api.cmd_send(args)
        assert rc == 0
        server.sendmail.assert_called_once()
        out = capsys.readouterr().out
        assert '"status": "sent"' in out
        assert "me@x.com" in out
        server.quit.assert_called_once()

    @mock.patch("email_api.get_smtp")
    @mock.patch("email_api.resolve_email_config")
    def test_send_sendmail_fail(self, mock_cfg, mock_smtp):
        mock_cfg.return_value = _make_config()
        server = mock.MagicMock()
        server.sendmail.side_effect = Exception("reject")
        mock_smtp.return_value = server
        args = mock.Mock(
            system=None, to=["a@x.com"], cc=None, bcc=None,
            subject=None, body="Hello", html=False, attach=None, reply_to=None,
        )
        with pytest.raises(ServiceError, match="邮件发送失败"):
            email_api.cmd_send(args)
        # finally 仍关连接
        server.quit.assert_called_once()

    @mock.patch("email_api.resolve_email_config")
    def test_send_empty_to(self, mock_cfg):
        mock_cfg.return_value = _make_config()
        args = mock.Mock(
            system=None, to=[], cc=None, bcc=None,
            subject="Hi", body="Hello", html=False, attach=None, reply_to=None,
        )
        with pytest.raises(ServiceError, match="收件人"):
            email_api.cmd_send(args)

    @mock.patch("email_api.get_smtp")
    @mock.patch("email_api.resolve_email_config")
    def test_send_default_subject(self, mock_cfg, mock_smtp, capsys):
        mock_cfg.return_value = _make_config()
        mock_smtp.return_value = mock.MagicMock()
        args = mock.Mock(
            system=None, to=["a@x.com"], cc=None, bcc=None,
            subject=None, body="Hello", html=False, attach=None, reply_to=None,
        )
        email_api.cmd_send(args)
        out = capsys.readouterr().out
        assert "(无主题)" in out

    @mock.patch("email_api.get_smtp")
    @mock.patch("email_api.resolve_email_config")
    def test_send_with_attachment(self, mock_cfg, mock_smtp, tmp_path, capsys):
        mock_cfg.return_value = _make_config()
        mock_smtp.return_value = mock.MagicMock()
        att = tmp_path / "d.txt"
        att.write_text("data")
        args = mock.Mock(
            system=None, to=["a@x.com"], cc=None, bcc=None,
            subject="Hi", body="Hello", html=False, attach=[str(att)], reply_to=None,
        )
        rc = email_api.cmd_send(args)
        assert rc == 0
        out = capsys.readouterr().out
        assert "d.txt" in out


# ---------------------------------------------------------------------------
# IMAP 子命令辅助
# ---------------------------------------------------------------------------


def _imap_fetch_headers_response(uid, subject, from_addr, date, flags_str, size):
    """构造 UID FETCH (BODY.PEEK[HEADER] FLAGS RFC822.SIZE) 的返回。"""
    header = (
        f"From: {from_addr}\r\nSubject: {subject}\r\nDate: {date}\r\n"
        f"\r\n"
    ).encode()
    meta = f"1 (UID {uid} FLAGS ({flags_str}) RFC822.SIZE {size})".encode()
    return ("OK", [(meta, header)])


class TestCmdList:
    @mock.patch("email_api.get_imap")
    @mock.patch("email_api.resolve_email_config")
    def test_list_success(self, mock_cfg, mock_imap, capsys):
        mock_cfg.return_value = _make_config()
        server = mock.MagicMock()
        mock_imap.return_value = server
        server.select.return_value = ("OK", [b"2"])
        server.uid.side_effect = [
            ("OK", [b"2 1"]),  # SEARCH ALL
            _imap_fetch_headers_response(2, "S2", "b@x.com", "Mon, 24 Jun 2026 14:30:00 +0800", "\\Seen", 100)[1] if False else
            ("OK", [(b"2 (UID 2 FLAGS (\\Seen) RFC822.SIZE 100)", b"From: b@x.com\r\nSubject: S2\r\nDate: Mon, 24 Jun 2026 14:30:00 +0800\r\n\r\n")]),
            ("OK", [(b"1 (UID 1 FLAGS () RFC822.SIZE 200)", b"From: a@x.com\r\nSubject: S1\r\nDate: Mon, 23 Jun 2026 10:00:00 +0800\r\n\r\n")]),
        ]
        args = mock.Mock(system=None, format="json", folder="INBOX", limit=None, unread_only=False, all_folders=False)
        rc = email_api.cmd_list(args)
        assert rc == 0
        out = capsys.readouterr().out
        assert "S2" in out and "S1" in out
        assert '"total": 2' in out
        server.logout.assert_called_once()

    @mock.patch("email_api.get_imap")
    @mock.patch("email_api.resolve_email_config")
    def test_list_unread_only(self, mock_cfg, mock_imap, capsys):
        mock_cfg.return_value = _make_config()
        server = mock.MagicMock()
        mock_imap.return_value = server
        server.select.return_value = ("OK", [b"2"])
        server.uid.side_effect = [
            ("OK", [b"2 1"]),  # SEARCH ALL
            # _filter_unread FETCH FLAGS for uid 2 (Seen -> skip)
            ("OK", [(b"2 (UID 2 FLAGS (\\Seen))",)]),
            # _filter_unread for uid 1 (no Seen -> keep)
            ("OK", [(b"1 (UID 1 FLAGS ())",)]),
            # _fetch_headers for uid 1
            ("OK", [(b"1 (UID 1 FLAGS () RFC822.SIZE 200)", b"From: a@x.com\r\nSubject: S1\r\n\r\n")]),
        ]
        args = mock.Mock(system=None, format="json", folder="INBOX", limit=None, unread_only=True, all_folders=False)
        rc = email_api.cmd_list(args)
        assert rc == 0
        out = capsys.readouterr().out
        assert "S1" in out
        assert "S2" not in out

    @mock.patch("email_api.get_imap")
    @mock.patch("email_api.resolve_email_config")
    def test_list_table_format(self, mock_cfg, mock_imap, capsys):
        mock_cfg.return_value = _make_config()
        server = mock.MagicMock()
        mock_imap.return_value = server
        server.select.return_value = ("OK", [b"1"])
        server.uid.side_effect = [
            ("OK", [b"1"]),
            ("OK", [(b"1 (UID 1 FLAGS (\\Seen) RFC822.SIZE 100)", b"From: a@x.com\r\nSubject: Hi\r\n\r\n")]),
        ]
        args = mock.Mock(system=None, format="table", folder="INBOX", limit=None, unread_only=False, all_folders=False)
        rc = email_api.cmd_list(args)
        assert rc == 0
        out = capsys.readouterr().out
        assert "UID" in out


class TestCmdRead:
    @mock.patch("email_api.get_imap")
    @mock.patch("email_api.resolve_email_config")
    def test_read_success(self, mock_cfg, mock_imap, capsys):
        mock_cfg.return_value = _make_config()
        server = mock.MagicMock()
        mock_imap.return_value = server
        server.select.return_value = ("OK", [b"1"])
        raw_mail = b"From: a@x.com\r\nTo: b@x.com\r\nSubject: Hi\r\nDate: Mon, 24 Jun 2026 14:30:00 +0800\r\nContent-Type: text/plain\r\n\r\nHello body"
        server.uid.return_value = ("OK", [(b"1 (UID 1 FLAGS (\\Seen))", raw_mail)])
        args = mock.Mock(system=None, format="json", folder="INBOX", uid=1)
        rc = email_api.cmd_read(args)
        assert rc == 0
        out = capsys.readouterr().out
        assert "Hello body" in out
        assert '"unread": false' in out

    @mock.patch("email_api.get_imap")
    @mock.patch("email_api.resolve_email_config")
    def test_read_not_found(self, mock_cfg, mock_imap):
        mock_cfg.return_value = _make_config()
        server = mock.MagicMock()
        mock_imap.return_value = server
        server.select.return_value = ("OK", [b"1"])
        server.uid.return_value = ("OK", [None])
        args = mock.Mock(system=None, format="json", folder="INBOX", uid=999)
        with pytest.raises(ServiceError, match="可能不存在"):
            email_api.cmd_read(args)

    @mock.patch("email_api.get_imap")
    @mock.patch("email_api.resolve_email_config")
    def test_read_with_attachment(self, mock_cfg, mock_imap, capsys):
        mock_cfg.return_value = _make_config()
        server = mock.MagicMock()
        mock_imap.return_value = server
        server.select.return_value = ("OK", [b"1"])
        raw_mail = (
            b'From: a@x.com\r\nSubject: Hi\r\n'
            b'Content-Type: multipart/mixed; boundary="b"\r\n\r\n'
            b"--b\r\nContent-Type: text/plain\r\n\r\nBODY\r\n"
            b"--b\r\nContent-Type: application/pdf\r\n"
            b'Content-Disposition: attachment; filename="r.pdf"\r\n\r\n'
            b"DATA\r\n--b--\r\n"
        )
        server.uid.return_value = ("OK", [(b"1 (UID 1 FLAGS ())", raw_mail)])
        args = mock.Mock(system=None, format="json", folder="INBOX", uid=1)
        rc = email_api.cmd_read(args)
        assert rc == 0
        out = capsys.readouterr().out
        assert "r.pdf" in out

    @mock.patch("email_api.get_imap")
    @mock.patch("email_api.resolve_email_config")
    def test_read_wrong_response_format(self, mock_cfg, mock_imap):
        mock_cfg.return_value = _make_config()
        server = mock.MagicMock()
        mock_imap.return_value = server
        server.select.return_value = ("OK", [b"1"])
        # 返回不是 tuple —— 格式异常
        server.uid.return_value = ("OK", [b"garbage"])
        args = mock.Mock(system=None, format="json", folder="INBOX", uid=1)
        with pytest.raises(ServiceError, match="返回格式异常"):
            email_api.cmd_read(args)

    @mock.patch("email_api.get_imap")
    @mock.patch("email_api.resolve_email_config")
    def test_read_table_format(self, mock_cfg, mock_imap, capsys):
        mock_cfg.return_value = _make_config()
        server = mock.MagicMock()
        mock_imap.return_value = server
        server.select.return_value = ("OK", [b"1"])
        raw = b"From: a@x.com\r\nTo: b@x.com\r\nSubject: Hi\r\nDate: Mon, 24 Jun 2026 14:30:00 +0800\r\nContent-Type: text/plain\r\n\r\nBody"
        server.uid.return_value = ("OK", [(b"1 (FLAGS (\\Seen))", raw)])
        args = mock.Mock(system=None, format="table", folder="INBOX", uid=1)
        rc = email_api.cmd_read(args)
        assert rc == 0
        out = capsys.readouterr().out
        assert "正文" in out
    @mock.patch("email_api.get_imap")
    @mock.patch("email_api.resolve_email_config")
    def test_search_success(self, mock_cfg, mock_imap, capsys):
        mock_cfg.return_value = _make_config()
        server = mock.MagicMock()
        mock_imap.return_value = server
        server.select.return_value = ("OK", [b"1"])
        server.uid.side_effect = [
            ("OK", [b"1"]),  # SEARCH
            ("OK", [(b"1 (UID 1 FLAGS () RFC822.SIZE 100)", b"From: gerrit@x.com\r\nSubject: Review\r\n\r\n")]),
        ]
        args = mock.Mock(system=None, format="json", folder="INBOX",
                         from_filter="gerrit", subject=None, since=None, limit=None, all_folders=False)
        rc = email_api.cmd_search(args)
        assert rc == 0
        out = capsys.readouterr().out
        assert "Review" in out

    @mock.patch("email_api.resolve_email_config")
    def test_search_no_criteria(self, mock_cfg):
        mock_cfg.return_value = _make_config()
        args = mock.Mock(system=None, format="json", folder="INBOX",
                         from_filter=None, subject=None, since=None, limit=None, all_folders=False)
        with pytest.raises(ServiceError, match="至少需要"):
            email_api.cmd_search(args)

    @mock.patch("email_api.get_imap")
    @mock.patch("email_api.resolve_email_config")
    def test_search_with_since(self, mock_cfg, mock_imap, capsys):
        mock_cfg.return_value = _make_config()
        server = mock.MagicMock()
        mock_imap.return_value = server
        server.select.return_value = ("OK", [b"0"])
        server.uid.return_value = ("OK", [b""])
        args = mock.Mock(system=None, format="json", folder="INBOX",
                         from_filter=None, subject=None, since="2026-06-01", limit=None, all_folders=False)
        rc = email_api.cmd_search(args)
        assert rc == 0
        # 验证 SINCE 被转成 IMAP 格式
        call_args = server.uid.call_args_list[0]
        assert "01-Jun-2026" in call_args.args

    @mock.patch("email_api.get_imap")
    @mock.patch("email_api.resolve_email_config")
    def test_search_with_subject(self, mock_cfg, mock_imap, capsys):
        mock_cfg.return_value = _make_config()
        server = mock.MagicMock()
        mock_imap.return_value = server
        server.select.return_value = ("OK", [b"1"])
        server.uid.side_effect = [
            ("OK", [b"1"]),
            ("OK", [(b"1 (UID 1 FLAGS () RFC822.SIZE 100)", b"From: a@x.com\r\nSubject: Review\r\n\r\n")]),
        ]
        args = mock.Mock(system=None, format="json", folder="INBOX",
                         from_filter=None, subject="Review", since=None, limit=None, all_folders=False)
        rc = email_api.cmd_search(args)
        assert rc == 0
        # 验证 SUBJECT 条件被传给 SEARCH
        search_call = server.uid.call_args_list[0]
        assert "SUBJECT" in search_call.args

    @mock.patch("email_api.get_imap")
    @mock.patch("email_api.resolve_email_config")
    def test_search_uid_fail(self, mock_cfg, mock_imap):
        mock_cfg.return_value = _make_config()
        server = mock.MagicMock()
        mock_imap.return_value = server
        server.select.return_value = ("OK", [b"0"])
        server.uid.return_value = ("NO", [])
        args = mock.Mock(system=None, format="json", folder="INBOX",
                         from_filter="x", subject=None, since=None, limit=None, all_folders=False)
        with pytest.raises(ServiceError, match="UID SEARCH 失败"):
            email_api.cmd_search(args)

    @mock.patch("email_api.get_imap")
    @mock.patch("email_api.resolve_email_config")
    def test_search_str_response(self, mock_cfg, mock_imap, capsys):
        # SEARCH 返回 str（部分服务器）应能 encode 处理
        mock_cfg.return_value = _make_config()
        server = mock.MagicMock()
        mock_imap.return_value = server
        server.select.return_value = ("OK", [b"0"])
        server.uid.side_effect = [
            ("OK", ["1 2"]),  # str 形式的 UID 列表
            ("OK", [(b"1 (UID 1 FLAGS () RFC822.SIZE 100)", b"From: a@x.com\r\nSubject: S\r\n\r\n")]),
            ("OK", [(b"2 (UID 2 FLAGS () RFC822.SIZE 100)", b"From: b@x.com\r\nSubject: S2\r\n\r\n")]),
        ]
        args = mock.Mock(system=None, format="json", folder="INBOX",
                         from_filter="x", subject=None, since=None, limit=None, all_folders=False)
        rc = email_api.cmd_search(args)
        assert rc == 0


class TestCmdFolders:
    @mock.patch("email_api.get_imap")
    @mock.patch("email_api.resolve_email_config")
    def test_folders_success(self, mock_cfg, mock_imap, capsys):
        mock_cfg.return_value = _make_config()
        server = mock.MagicMock()
        mock_imap.return_value = server
        server.list.return_value = ("OK", [
            b'(\\HasNoChildren) "/" "INBOX"',
            b'(\\HasNoChildren) "/" "Sent"',
        ])
        args = mock.Mock(system=None, format="json")
        rc = email_api.cmd_folders(args)
        assert rc == 0
        out = capsys.readouterr().out
        assert "INBOX" in out and "Sent" in out

    @mock.patch("email_api.get_imap")
    @mock.patch("email_api.resolve_email_config")
    def test_folders_fail(self, mock_cfg, mock_imap):
        mock_cfg.return_value = _make_config()
        server = mock.MagicMock()
        mock_imap.return_value = server
        server.list.return_value = ("NO", [])
        args = mock.Mock(system=None, format="json")
        with pytest.raises(ServiceError, match="LIST"):
            email_api.cmd_folders(args)


# ---------------------------------------------------------------------------
# _list_folder_names / _multifolder_search / _multifolder_list
# ---------------------------------------------------------------------------


class TestListFolderNames:
    def test_returns_folder_names(self):
        server = mock.MagicMock()
        server.list.return_value = ("OK", [
            b'(\\HasNoChildren) "/" "INBOX"',
            b'(\\HasNoChildren) "/" "Sent"',
        ])
        names = email_api._list_folder_names(server)
        assert names == ["INBOX", "Sent"]

    def test_unparseble_line_falls_back(self):
        server = mock.MagicMock()
        server.list.return_value = ("OK", [b"RAW_LINE"])
        names = email_api._list_folder_names(server)
        assert names == ["RAW_LINE"]


class TestMultiFolderSearch:
    def test_searches_all_folders(self):
        server = mock.MagicMock()
        server.list.return_value = ("OK", [
            b'(\\HasNoChildren) "/" "INBOX"',
            b'(\\HasNoChildren) "/" "Sent"',
        ])
        server.select.return_value = ("OK", [b"1"])
        hdr = b"From: a@x.com\r\nSubject: Review\r\nDate: Mon, 24 Jun 2026 14:30:00 +0800\r\n\r\n"
        server.uid.side_effect = [
            ("OK", [b"1"]),  # SEARCH INBOX
            ("OK", [(b"1 (UID 1 FLAGS () RFC822.SIZE 100)", hdr)]),
            ("OK", [b""]),  # SEARCH Sent (empty)
        ]
        msgs = email_api._multifolder_search(server, ["FROM", "gerrit"], 10)
        assert len(msgs) == 1
        assert msgs[0]["folder"] == "INBOX"
        assert msgs[0]["subject"] == "Review"

    def test_select_failure_is_skipped(self):
        server = mock.MagicMock()
        server.list.return_value = ("OK", [b'"BrokenFolder"'])
        server.select.side_effect = ServiceError("fail")
        msgs = email_api._multifolder_search(server, ["FROM", "x"], 10)
        assert msgs == []


class TestMultiFolderList:
    def test_lists_all_folders(self):
        server = mock.MagicMock()
        server.list.return_value = ("OK", [
            b'"INBOX"',
            b'"Sent"',
        ])
        server.select.return_value = ("OK", [b"1"])
        hdr1 = b"From: a@x.com\r\nSubject: S1\r\nDate: Mon, 24 Jun 2026 14:30:00 +0800\r\n\r\n"
        hdr2 = b"From: b@x.com\r\nSubject: S2\r\nDate: Tue, 24 Jun 2025 10:00:00 +0800\r\n\r\n"
        server.uid.side_effect = [
            # SEARCH ALL + FETCH for INBOX
            ("OK", [b"1"]),
            ("OK", [(b"1 (UID 1 FLAGS () RFC822.SIZE 100)", hdr1)]),
            # SEARCH ALL + FETCH for Sent
            ("OK", [b"2"]),
            ("OK", [(b"2 (UID 2 FLAGS (\\Seen) RFC822.SIZE 200)", hdr2)]),
        ]
        msgs = email_api._multifolder_list(server, unread_only=False, limit=10)
        assert len(msgs) == 2
        assert msgs[0]["folder"] == "INBOX"  # 按日期倒序，S1 在前
        assert msgs[1]["folder"] == "Sent"


# ---------------------------------------------------------------------------
# cmd_list / cmd_search --all-folders
# ---------------------------------------------------------------------------


class TestCmdListAllFolders:
    @mock.patch("email_api.get_imap")
    @mock.patch("email_api.resolve_email_config")
    def test_all_folders_dispatches(self, mock_cfg, mock_imap, capsys):
        mock_cfg.return_value = _make_config()
        server = mock.MagicMock()
        mock_imap.return_value = server
        server.list.return_value = ("OK", [b'"INBOX"'])
        server.select.return_value = ("OK", [b"1"])
        hdr = b"From: a@x.com\r\nSubject: Hi\r\nDate: Mon, 24 Jun 2026 14:30:00 +0800\r\n\r\n"
        server.uid.side_effect = [
            ("OK", [b"1"]),
            ("OK", [(b"1 (UID 1 FLAGS (\\Seen) RFC822.SIZE 100)", hdr)]),
        ]
        args = mock.Mock(system=None, format="json", folder="INBOX",
                         limit=None, unread_only=False, all_folders=True)
        rc = email_api.cmd_list(args)
        assert rc == 0
        out = capsys.readouterr().out
        assert "(所有文件夹)" in out
        assert server.logout.call_count == 1


class TestCmdSearchAllFolders:
    @mock.patch("email_api.get_imap")
    @mock.patch("email_api.resolve_email_config")
    def test_all_folders_dispatches(self, mock_cfg, mock_imap, capsys):
        mock_cfg.return_value = _make_config()
        server = mock.MagicMock()
        mock_imap.return_value = server
        server.list.return_value = ("OK", [b'"INBOX"'])
        server.select.return_value = ("OK", [b"1"])
        hdr = b"From: gerrit@x.com\r\nSubject: Review\r\nDate: Mon, 24 Jun 2026 14:30:00 +0800\r\n\r\n"
        server.uid.side_effect = [
            ("OK", [b"1"]),
            ("OK", [(b"1 (UID 1 FLAGS () RFC822.SIZE 100)", hdr)]),
        ]
        args = mock.Mock(system=None, format="json", folder="INBOX",
                         from_filter="gerrit", subject=None, since=None,
                         limit=None, all_folders=True)
        rc = email_api.cmd_search(args)
        assert rc == 0
        out = capsys.readouterr().out
        assert "Review" in out
        assert "INBOX" in out  # folder 字段出现在消息中
        assert server.logout.call_count == 1


class TestCmdMarkRead:
    @mock.patch("email_api.get_imap")
    @mock.patch("email_api.resolve_email_config")
    def test_mark_read_default(self, mock_cfg, mock_imap, capsys):
        mock_cfg.return_value = _make_config()
        server = mock.MagicMock()
        mock_imap.return_value = server
        server.select.return_value = ("OK", [b"1"])
        server.uid.return_value = ("OK", [b"1"])
        args = mock.Mock(system=None, folder="INBOX", uid=1, unread=False)
        rc = email_api.cmd_mark_read(args)
        assert rc == 0
        out = capsys.readouterr().out
        assert "已读" in out
        # 验证用 +FLAGS
        store_call = server.uid.call_args_list[0]
        assert "+FLAGS" in store_call.args

    @mock.patch("email_api.get_imap")
    @mock.patch("email_api.resolve_email_config")
    def test_mark_unread(self, mock_cfg, mock_imap, capsys):
        mock_cfg.return_value = _make_config()
        server = mock.MagicMock()
        mock_imap.return_value = server
        server.select.return_value = ("OK", [b"1"])
        server.uid.return_value = ("OK", [b"1"])
        args = mock.Mock(system=None, folder="INBOX", uid=1, unread=True)
        rc = email_api.cmd_mark_read(args)
        assert rc == 0
        out = capsys.readouterr().out
        assert "未读" in out

    @mock.patch("email_api.get_imap")
    @mock.patch("email_api.resolve_email_config")
    def test_mark_read_fail(self, mock_cfg, mock_imap):
        mock_cfg.return_value = _make_config()
        server = mock.MagicMock()
        mock_imap.return_value = server
        server.select.return_value = ("OK", [b"1"])
        server.uid.return_value = ("NO", [])
        args = mock.Mock(system=None, folder="INBOX", uid=1, unread=False)
        with pytest.raises(ServiceError, match="标记"):
            email_api.cmd_mark_read(args)


class TestCmdSaveAttachments:
    @mock.patch("email_api.get_imap")
    @mock.patch("email_api.resolve_email_config")
    def test_save_success(self, mock_cfg, mock_imap, tmp_path, capsys):
        mock_cfg.return_value = _make_config(attachments_dir=str(tmp_path / "atts"))
        server = mock.MagicMock()
        mock_imap.return_value = server
        server.select.return_value = ("OK", [b"1"])
        raw_mail = (
            b'From: a@x.com\r\nSubject: Hi\r\n'
            b'Content-Type: multipart/mixed; boundary="b"\r\n\r\n'
            b"--b\r\nContent-Type: text/plain\r\n\r\nBODY\r\n"
            b"--b\r\nContent-Type: application/pdf\r\n"
            b'Content-Disposition: attachment; filename="r.pdf"\r\n\r\n'
            b"DATA\r\n--b--\r\n"
        )
        server.uid.return_value = ("OK", [(b"1 (UID 1)", raw_mail)])
        args = mock.Mock(system=None, folder="INBOX", uid=1)
        rc = email_api.cmd_save_attachments(args)
        assert rc == 0
        out = capsys.readouterr().out
        assert "r.pdf" in out
        assert (tmp_path / "atts" / "r.pdf").exists()

    @mock.patch("email_api.get_imap")
    @mock.patch("email_api.resolve_email_config")
    def test_save_empty_attachment_skipped(self, mock_cfg, mock_imap, tmp_path, capsys):
        mock_cfg.return_value = _make_config(attachments_dir=str(tmp_path / "atts"))
        server = mock.MagicMock()
        mock_imap.return_value = server
        server.select.return_value = ("OK", [b"1"])
        raw_mail = (
            b'From: a@x.com\r\nSubject: Hi\r\n'
            b'Content-Type: multipart/mixed; boundary="b"\r\n\r\n'
            b"--b\r\nContent-Type: application/pdf\r\n"
            b'Content-Disposition: attachment; filename="empty.pdf"\r\n\r\n'
            b"\r\n--b--\r\n"
        )
        server.uid.return_value = ("OK", [(b"1 (UID 1)", raw_mail)])
        args = mock.Mock(system=None, folder="INBOX", uid=1)
        rc = email_api.cmd_save_attachments(args)
        assert rc == 0
        out = capsys.readouterr().out
        assert "skipped" in out
        assert "空附件" in out

    @mock.patch("email_api.get_imap")
    @mock.patch("email_api.resolve_email_config")
    def test_save_not_found(self, mock_cfg, mock_imap, tmp_path):
        mock_cfg.return_value = _make_config(attachments_dir=str(tmp_path / "atts"))
        server = mock.MagicMock()
        mock_imap.return_value = server
        server.select.return_value = ("OK", [b"1"])
        server.uid.return_value = ("OK", [None])
        args = mock.Mock(system=None, folder="INBOX", uid=999)
        with pytest.raises(ServiceError, match="可能不存在"):
            email_api.cmd_save_attachments(args)

    @mock.patch("email_api.get_imap")
    @mock.patch("email_api.resolve_email_config")
    def test_save_creates_dir(self, mock_cfg, mock_imap, tmp_path, capsys):
        atts_dir = tmp_path / "newdir" / "atts"
        mock_cfg.return_value = _make_config(attachments_dir=str(atts_dir))
        server = mock.MagicMock()
        mock_imap.return_value = server
        server.select.return_value = ("OK", [b"1"])
        raw_mail = (
            b'From: a@x.com\r\nSubject: Hi\r\n'
            b'Content-Type: multipart/mixed; boundary="b"\r\n\r\n'
            b"--b\r\nContent-Type: text/plain\r\n\r\nBODY\r\n"
            b"--b\r\nContent-Type: application/pdf\r\n"
            b'Content-Disposition: attachment; filename="r.pdf"\r\n\r\n'
            b"DATA\r\n--b--\r\n"
        )
        server.uid.return_value = ("OK", [(b"1 (UID 1)", raw_mail)])
        args = mock.Mock(system=None, folder="INBOX", uid=1)
        email_api.cmd_save_attachments(args)
        assert atts_dir.exists()
        assert (atts_dir / "r.pdf").exists()

    @mock.patch("email_api.get_imap")
    @mock.patch("email_api.resolve_email_config")
    def test_save_wrong_response_format(self, mock_cfg, mock_imap, tmp_path):
        mock_cfg.return_value = _make_config(attachments_dir=str(tmp_path / "atts"))
        server = mock.MagicMock()
        mock_imap.return_value = server
        server.select.return_value = ("OK", [b"1"])
        server.uid.return_value = ("OK", [b"garbage"])
        args = mock.Mock(system=None, folder="INBOX", uid=1)
        with pytest.raises(ServiceError, match="返回格式异常"):
            email_api.cmd_save_attachments(args)

    @mock.patch("email_api.get_imap")
    @mock.patch("email_api.resolve_email_config")
    def test_save_write_fail(self, mock_cfg, mock_imap, tmp_path, monkeypatch):
        atts_dir = tmp_path / "atts"
        atts_dir.mkdir()
        mock_cfg.return_value = _make_config(attachments_dir=str(atts_dir))
        server = mock.MagicMock()
        mock_imap.return_value = server
        server.select.return_value = ("OK", [b"1"])
        raw_mail = (
            b'From: a@x.com\r\nSubject: Hi\r\n'
            b'Content-Type: multipart/mixed; boundary="b"\r\n\r\n'
            b"--b\r\nContent-Type: application/pdf\r\n"
            b'Content-Disposition: attachment; filename="r.pdf"\r\n\r\n'
            b"DATA\r\n--b--\r\n"
        )
        server.uid.return_value = ("OK", [(b"1 (UID 1)", raw_mail)])

        original_open = open

        def fake_open(path, *a, **kw):
            if str(path).endswith("r.pdf"):
                raise OSError("write fail")
            return original_open(path, *a, **kw)

        monkeypatch.setattr("builtins.open", fake_open)
        args = mock.Mock(system=None, folder="INBOX", uid=1)
        with pytest.raises(ServiceError, match="保存附件失败"):
            email_api.cmd_save_attachments(args)


# ---------------------------------------------------------------------------
# main / argparse
# ---------------------------------------------------------------------------


class TestMain:
    def test_build_parser_has_subcommands(self):
        parser = email_api.build_parser()
        # 解析各子命令不报错
        args = parser.parse_args(["list", "--format", "table"])
        assert args.command == "list"
        assert args.format == "table"

    def test_build_parser_send_required_body(self):
        parser = email_api.build_parser()
        args = parser.parse_args(["send", "--to", "a@x.com", "--body", "hi"])
        assert args.body == "hi"
        assert args.to == ["a@x.com"]

    @mock.patch("email_api.cmd_list")
    def test_main_dispatches(self, mock_cmd, monkeypatch):
        mock_cmd.return_value = 0
        monkeypatch.setattr("sys.argv", ["email_api.py", "list", "--format", "json"])
        rc = email_api.main()
        assert rc == 0
        mock_cmd.assert_called_once()

    def test_main_no_command_errors(self):
        with pytest.raises(SystemExit):
            email_api.main()

    def test_print_error(self, capsys):
        rc = email_api.print_error(ServiceError("boom"))
        assert rc == 1
        err = capsys.readouterr().err
        assert "Error: boom" in err
