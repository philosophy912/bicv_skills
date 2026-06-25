"""电子邮件收发技能脚本。

通过 SMTP_SSL 发送邮件、IMAP4_SSL 读取和管理邮件。纯标准库实现，零依赖。

子命令：
  send             发送邮件（支持纯文本/HTML、附件、抄送/密送）
  list             列出邮件摘要（默认最新 100 封）
  read             读取单封邮件完整内容
  search           按发件人/主题/日期搜索邮件
  folders          列出服务器所有文件夹
  mark-read        标记邮件已读/未读
  save-attachments 下载单封邮件的附件到配置的 attachments_dir

配置见 ~/.bicv/email.json，结构见 references/config-schema.md。
"""

from __future__ import annotations

import argparse
import email
import email.utils
import imaplib
import json
import mimetypes
import os
import re
import smtplib
import sys
from email.header import Header, decode_header
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Any

from _email_config import ServiceError, load_systems_config

# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------

CONFIG_NAME = "email.json"
DEFAULT_SMTP_PORT = 465
DEFAULT_IMAP_PORT = 993
CONNECTION_TIMEOUT = 60
LIST_DEFAULT_LIMIT = 100
SEARCH_DEFAULT_LIMIT = 20
MAX_LIMIT = 500
DEFAULT_FOLDER = "INBOX"
DEFAULT_SUBJECT = "(无主题)"
ATTACHMENT_FALLBACK_PREFIX = "attachment"

CONFIG_PATH_HINT = f"~/.bicv/{CONFIG_NAME}"


# ---------------------------------------------------------------------------
# 配置解析
# ---------------------------------------------------------------------------


class EmailConnectionConfig:
    """解析后的 email 连接配置。"""

    def __init__(
        self,
        *,
        smtp_host: str,
        smtp_port: int,
        smtp_username: str,
        smtp_password: str,
        imap_host: str | None,
        imap_port: int | None,
        imap_username: str | None,
        imap_password: str | None,
        from_address: str,
        attachments_dir: str | None,
        system_name: str | None,
    ):
        self.smtp_host = smtp_host
        self.smtp_port = smtp_port
        self.smtp_username = smtp_username
        self.smtp_password = smtp_password
        self.imap_host = imap_host
        self.imap_port = imap_port
        self.imap_username = imap_username
        self.imap_password = imap_password
        self.from_address = from_address
        self.attachments_dir = attachments_dir
        self.system_name = system_name


def _require_field(system_name: str, block: dict, key: str, block_name: str) -> str:
    value = str(block.get(key, "")).strip()
    if not value:
        raise ServiceError(
            f"system {system_name!r} 的 {block_name} 配置缺少 {key} 字段；请检查 {CONFIG_PATH_HINT}"
        )
    return value


def _resolve_block(
    system_name: str, system_config: dict, block_name: str, require: bool
) -> dict | None:
    block = system_config.get(block_name)
    if not isinstance(block, dict):
        if require:
            raise ServiceError(
                f"system {system_name!r} 缺少 {block_name} 配置块；请检查 {CONFIG_PATH_HINT}"
            )
        return None
    return block


def resolve_email_config(
    system: str | None = None,
    *,
    config_name: str = CONFIG_NAME,
    need_imap: bool = False,
    need_attachments_dir: bool = False,
) -> EmailConnectionConfig:
    """从 ~/.bicv/<config_name> 解析 email 连接配置。

    *need_imap* 为 True 时校验 imap 块完整；*need_attachments_dir* 为 True 时
    校验 attachments_dir 存在。send 只需要 smtp+from_address；收信子命令需要
    imap；save-attachments 额外需要 attachments_dir。
    """
    config_data = load_systems_config(config_name)
    systems = config_data["systems"]

    configured_system = system or str(config_data.get("default_system", "")).strip()
    if not configured_system:
        raise ServiceError(f"未指定 --system 且 {CONFIG_PATH_HINT} 中没有 default_system")

    if configured_system not in systems:
        names = ", ".join(systems.keys())
        raise ServiceError(
            f"system {configured_system!r} 不存在于 {CONFIG_PATH_HINT}。可选：{names}"
        )

    system_config = systems[configured_system]
    if not isinstance(system_config, dict):
        raise ServiceError(
            f"system {configured_system!r} 的配置不是对象；请检查 {CONFIG_PATH_HINT}"
        )

    # smtp 块（发信必需，始终校验）
    smtp_block = _resolve_block(configured_system, system_config, "smtp", require=True)
    assert smtp_block is not None
    smtp_host = _require_field(configured_system, smtp_block, "host", "smtp")
    smtp_username = _require_field(configured_system, smtp_block, "username", "smtp")
    smtp_password = _require_field(configured_system, smtp_block, "password", "smtp")
    try:
        smtp_port = int(smtp_block.get("port", DEFAULT_SMTP_PORT))
    except (TypeError, ValueError) as exc:
        raise ServiceError(f"system {configured_system!r} 的 smtp.port 不是合法整数") from exc

    # imap 块（收信必需）
    imap_host = imap_port = imap_username = imap_password = None
    imap_block = _resolve_block(configured_system, system_config, "imap", require=need_imap)
    if imap_block is not None:
        imap_host = _require_field(configured_system, imap_block, "host", "imap")
        imap_username = _require_field(configured_system, imap_block, "username", "imap")
        imap_password = _require_field(configured_system, imap_block, "password", "imap")
        try:
            imap_port = int(imap_block.get("port", DEFAULT_IMAP_PORT))
        except (TypeError, ValueError) as exc:
            raise ServiceError(f"system {configured_system!r} 的 imap.port 不是合法整数") from exc

    # from_address
    from_address = str(system_config.get("from_address", "")).strip()
    if not from_address:
        raise ServiceError(
            f"system {configured_system!r} 缺少 from_address 字段；请检查 {CONFIG_PATH_HINT}"
        )
    validate_address(from_address)

    # attachments_dir
    attachments_dir = str(system_config.get("attachments_dir", "")).strip() or None
    if need_attachments_dir and not attachments_dir:
        raise ServiceError(
            f"system {configured_system!r} 缺少 attachments_dir 字段；"
            f"save-attachments 需要该字段指定附件保存目录，请检查 {CONFIG_PATH_HINT}"
        )

    return EmailConnectionConfig(
        smtp_host=smtp_host,
        smtp_port=smtp_port,
        smtp_username=smtp_username,
        smtp_password=smtp_password,
        imap_host=imap_host,
        imap_port=imap_port,
        imap_username=imap_username,
        imap_password=imap_password,
        from_address=from_address,
        attachments_dir=attachments_dir,
        system_name=configured_system,
    )


# ---------------------------------------------------------------------------
# 地址校验与解析
# ---------------------------------------------------------------------------


def validate_address(addr: str) -> None:
    """轻量校验邮件地址：含 @、@ 不在首尾、域名有点。不合法抛 ServiceError。"""
    addr = addr.strip()
    if "@" not in addr:
        raise ServiceError(f"无效的邮件地址（缺少 @）: {addr!r}")
    local, _, domain = addr.rpartition("@")
    if not local or not domain:
        raise ServiceError(f"无效的邮件地址（@ 不能在首尾）: {addr!r}")
    if "." not in domain:
        raise ServiceError(f"无效的邮件地址（域名缺少点）: {addr!r}")


def parse_addresses(values: list[str] | None) -> list[str]:
    """解析多值地址参数：append 收集 + 逗号 split + strip + 去空 + 去重。

    输入可能形如 ['a@x.com', 'b@x.com,c@x.com']，输出 ['a@x.com','b@x.com','c@x.com']。
    """
    if not values:
        return []
    seen: set[str] = set()
    result: list[str] = []
    for raw in values:
        for part in raw.split(","):
            addr = part.strip()
            if addr and addr not in seen:
                seen.add(addr)
                result.append(addr)
    return result


def validate_addresses(addresses: list[str], field_name: str) -> None:
    """校验一组地址，任一不合法抛 ServiceError。"""
    for addr in addresses:
        validate_address(addr)
    if field_name == "to" and not addresses:
        raise ServiceError("收件人(--to)不能为空")


# ---------------------------------------------------------------------------
# 纯函数：正文提取、HTML 转纯文本、大小格式化
# ---------------------------------------------------------------------------


_HTML_TAG_RE = re.compile(r"<[^>]+>")


def html_to_text(html: str) -> str:
    """最简 HTML→纯文本：去掉标签，压缩空白。"""
    text = _HTML_TAG_RE.sub("", html)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _decode_payload(part) -> str:
    """解码单个 text part 的 payload 为字符串。"""
    charset = part.get_content_charset() or "utf-8"
    payload = part.get_payload(decode=True)
    if payload is None:
        # 可能是 multipart，取 raw 字符串
        raw = part.get_payload()
        return str(raw) if isinstance(raw, str) else ""
    try:
        return payload.decode(charset, errors="replace")
    except (LookupError, TypeError):
        return payload.decode("utf-8", errors="replace")


def extract_body(msg) -> tuple[str, str]:
    """从邮件中提取正文，返回 (body, body_type)。

    递归遍历所有 part，收集 text/plain 和 text/html。
    优先返回 plain（多个拼接），没有返回 html 剥离标签后的纯文本。
    body_type 为 'plain' 或 'html' 或 'none'。
    """
    plains: list[str] = []
    htmls: list[str] = []

    def walk(part):
        if part.is_multipart():
            for sub in part.get_payload():
                walk(sub)
            return
        ctype = part.get_content_type()
        if ctype == "text/plain":
            plains.append(_decode_payload(part))
        elif ctype == "text/html":
            htmls.append(_decode_payload(part))

    walk(msg)

    if plains:
        return "\n".join(p for p in plains if p), "plain"
    if htmls:
        return html_to_text("\n".join(h for h in htmls if h)), "html"
    return "", "none"


def format_size(size: int | None) -> str:
    """字节数转人类可读格式（1024 进制，1 位小数）。None 返回空串。"""
    if size is None:
        return ""
    if size < 1024:
        return f"{size} B"
    units = ["KB", "MB", "GB", "TB"]
    value = float(size)
    for unit in units:
        value /= 1024.0
        if value < 1024:
            return f"{value:.1f} {unit}"
    return f"{value:.1f} TB"


# ---------------------------------------------------------------------------
# 邮件解析辅助
# ---------------------------------------------------------------------------


def decode_header_value(value: str | None) -> str:
    """解码邮件头（处理 RFC 2047 =?utf-8?B?...?= 编码）。"""
    if not value:
        return ""
    parts = decode_header(value)
    chunks: list[str] = []
    for text, charset in parts:
        if isinstance(text, bytes):
            try:
                chunks.append(text.decode(charset or "utf-8", errors="replace"))
            except (LookupError, TypeError):
                chunks.append(text.decode("utf-8", errors="replace"))
        else:
            chunks.append(text)
    return "".join(chunks)


def parse_mail_date(date_str: str | None) -> str:
    """解析邮件 Date 头，返回 YYYY-MM-DD HH:MM 本地时间。失败返回原串。"""
    if not date_str:
        return ""
    try:
        dt = email.utils.parsedate_to_datetime(date_str)
        if dt is None:
            return date_str
        return dt.strftime("%Y-%m-%d %H:%M")
    except (TypeError, ValueError):
        return date_str


def get_attachment_filename(part, index: int) -> str:
    """取附件文件名：Content-Disposition.filename 优先，None 用兜底名。"""
    filename = part.get_filename()
    if filename:
        filename = decode_header_value(filename)
    if not filename:
        filename = f"{ATTACHMENT_FALLBACK_PREFIX}_{index + 1}.bin"
    return filename


def has_flag(flags: list[bytes] | None, flag: bytes) -> bool:
    """判断 IMAP FLAGS 列表里是否含某标志（如 b'\\Seen'）。

    flags 可能形如 [b'(\\Seen \\Recent)'] 或 [b'\\Seen', b'\\Recent']，
    统一按空白 split 并剥掉括号后比较。
    """
    if not flags:
        return False
    target = flag.decode().strip().strip("()")
    for f in flags:
        if isinstance(f, (bytes, bytearray)):
            text = f.decode("utf-8", errors="replace")
        elif isinstance(f, str):
            text = f
        else:
            continue
        for token in text.replace("(", " ").replace(")", " ").split():
            if token.strip() == target:
                return True
    return False


def list_attachments(msg) -> list[dict]:
    """枚举邮件里的附件，返回 [{filename, size}]。size 来自 payload 字节数。"""
    attachments: list[dict] = []
    index = 0

    def walk(part):
        nonlocal index
        if part.is_multipart():
            for sub in part.get_payload():
                walk(sub)
            return
        ctype = part.get_content_type()
        disposition = str(part.get("Content-Disposition", "")).lower()
        # 附件：Content-Disposition 含 attachment，或非 text/* 且有文件名
        is_attachment = "attachment" in disposition
        if not is_attachment and ctype.startswith("text/"):
            return
        filename = part.get_filename()
        if not is_attachment and not filename:
            return
        name = get_attachment_filename(part, index)
        payload = part.get_payload(decode=True)
        size = len(payload) if payload is not None else 0
        attachments.append({"filename": name, "size": size})
        index += 1

    walk(msg)
    return attachments


# ---------------------------------------------------------------------------
# 附件落地安全处理
# ---------------------------------------------------------------------------

# 操作系统文件名非法字符（跨平台保守集合）
_ILLEGAL_CHARS_RE = re.compile(r'[\x00-\x1f<>:"/\\|?*]')


def safe_filename(filename: str) -> str:
    """basename 剥目录 + 非法字符替换 _，防路径穿越。"""
    # basename：取最后一层，剥掉一切目录成分
    name = os.path.basename(filename.replace("\\", "/"))
    name = _ILLEGAL_CHARS_RE.sub("_", name).strip()
    if not name:
        name = f"{ATTACHMENT_FALLBACK_PREFIX}.bin"
    return name


def unique_path(directory: str, filename: str) -> str:
    """在 directory 下为 filename 生成不冲突的路径，重名追加序号。"""
    base, ext = os.path.splitext(filename)
    candidate = os.path.join(directory, filename)
    counter = 1
    while os.path.exists(candidate):
        candidate = os.path.join(directory, f"{base}_{counter}{ext}")
        counter += 1
    return candidate


# ---------------------------------------------------------------------------
# --body 读取
# ---------------------------------------------------------------------------


def read_body(body_arg: str) -> str:
    """读取 --body 参数：@前缀读文件，否则当文本。文件不存在报错。"""
    if body_arg.startswith("@"):
        path = body_arg[1:]
        if not os.path.exists(path):
            raise ServiceError(f"正文文件不存在: {path}")
        try:
            with open(path, encoding="utf-8") as f:
                return f.read()
        except OSError as exc:
            raise ServiceError(f"读取正文文件失败: {path}: {exc}") from exc
    return body_arg


# ---------------------------------------------------------------------------
# 连接
# ---------------------------------------------------------------------------


def get_smtp(config: EmailConnectionConfig):
    """建立 SMTP_SSL 连接并登录，返回 server 实例。失败抛 ServiceError。"""
    try:
        server = smtplib.SMTP_SSL(config.smtp_host, config.smtp_port, timeout=CONNECTION_TIMEOUT)
    except Exception as exc:
        raise ServiceError(f"SMTP 连接失败 ({config.smtp_host}:{config.smtp_port}): {exc}") from exc
    try:
        server.login(config.smtp_username, config.smtp_password)
    except Exception as exc:
        try:
            server.quit()
        except Exception:
            pass
        raise ServiceError(f"SMTP 登录失败: {exc}") from exc
    return server


def get_imap(config: EmailConnectionConfig):
    """建立 IMAP4_SSL 连接并登录，返回 server 实例。失败抛 ServiceError。"""
    try:
        server = imaplib.IMAP4_SSL(config.imap_host, config.imap_port, timeout=CONNECTION_TIMEOUT)
    except Exception as exc:
        raise ServiceError(f"IMAP 连接失败 ({config.imap_host}:{config.imap_port}): {exc}") from exc
    try:
        server.login(config.imap_username, config.imap_password)
    except Exception as exc:
        try:
            server.logout()
        except Exception:
            pass
        raise ServiceError(f"IMAP 登录失败: {exc}") from exc
    return server


def select_folder(server, folder: str) -> int:
    """选择文件夹，返回邮件总数。失败抛 ServiceError 并提示用 folders 查。"""
    try:
        status, data = server.select(folder)
    except Exception as exc:
        raise ServiceError(
            f"选择文件夹 {folder!r} 失败: {exc}；可用 folders 子命令查看所有文件夹"
        ) from exc
    if status != "OK":
        raise ServiceError(f"文件夹 {folder!r} 不存在或无法选择；可用 folders 子命令查看所有文件夹")
    try:
        return int(data[0])
    except (TypeError, ValueError, IndexError):
        return 0


# ---------------------------------------------------------------------------
# 邮件构造（发信）
# ---------------------------------------------------------------------------


def build_message(
    *,
    from_address: str,
    to: list[str],
    cc: list[str],
    bcc: list[str],
    subject: str,
    body: str,
    html: bool,
    attachments: list[str],
    reply_to: str | None,
) -> tuple[Any, list[str]]:
    """构造邮件对象，返回 (message, recipients)。

    recipients 是实际投递列表（to + cc + bcc 去重）。
    """
    has_attach = bool(attachments)
    plain_fallback = html_to_text(body) if html else None

    if has_attach:
        message = MIMEMultipart("mixed")
        if html:
            alt = MIMEMultipart("alternative")
            alt.attach(MIMEText(plain_fallback or "", "plain", "utf-8"))
            alt.attach(MIMEText(body, "html", "utf-8"))
            message.attach(alt)
        else:
            message.attach(MIMEText(body, "plain", "utf-8"))
    elif html:
        message = MIMEMultipart("alternative")
        message.attach(MIMEText(plain_fallback or "", "plain", "utf-8"))
        message.attach(MIMEText(body, "html", "utf-8"))
    else:
        message = MIMEText(body, "plain", "utf-8")

    message["From"] = from_address
    message["To"] = ", ".join(to)
    if cc:
        message["Cc"] = ", ".join(cc)
    if reply_to:
        message["Reply-To"] = reply_to
    message["Subject"] = Header(subject, "utf-8").encode()
    message["Date"] = email.utils.formatdate(localtime=True)
    domain = from_address.rpartition("@")[2] or "localhost"
    message["Message-ID"] = email.utils.make_msgid(domain=domain)

    for path in attachments:
        if not os.path.exists(path):
            raise ServiceError(f"附件文件不存在: {path}")
        try:
            with open(path, "rb") as f:
                content = f.read()
        except OSError as exc:
            raise ServiceError(f"读取附件文件失败: {path}: {exc}") from exc
        filename = os.path.basename(path)
        mime_type, _ = mimetypes.guess_type(path)
        if mime_type and mime_type != "application/octet-stream":
            sub_type = mime_type.split("/", 1)[1]
            part = MIMEApplication(content, _subtype=sub_type)
        else:
            part = MIMEApplication(content)
        part.add_header(
            "Content-Disposition",
            "attachment",
            filename=("utf-8", "", filename),
        )
        message.attach(part)

    # 实际投递列表：to + cc + bcc 去重（Bcc 不写进头）
    recipients: list[str] = []
    seen: set[str] = set()
    for addr in to + cc + bcc:
        if addr not in seen:
            seen.add(addr)
            recipients.append(addr)

    return message, recipients


# ---------------------------------------------------------------------------
# IMAP 操作辅助
# ---------------------------------------------------------------------------


def _fetch_headers(server, uids: list[bytes]) -> list[dict]:
    """FETCH 多封邮件的 header + flags + size，返回摘要 dict 列表。"""
    results: list[dict] = []
    for uid in uids:
        status, data = server.uid("FETCH", uid, "(BODY.PEEK[HEADER] FLAGS RFC822.SIZE)")
        if status != "OK" or not data or data[0] is None:
            continue
        raw = data[0]
        flags: list[bytes] = []
        size: int | None = None
        if isinstance(raw, tuple) and len(raw) >= 2:
            header_bytes = raw[1] if isinstance(raw[1], (bytes, bytearray)) else b""
            # 解析随后的 FLAGS/SIZE（在 raw[0] 字符串里）
            meta = (
                raw[0].decode("utf-8", errors="replace")
                if isinstance(raw[0], bytes)
                else str(raw[0])
            )
        elif isinstance(raw, (bytes, bytearray)):
            header_bytes = bytes(raw)
            meta = ""
        else:
            continue

        # 从 meta 提取 FLAGS 和 SIZE
        flag_match = re.search(r"FLAGS \(([^)]*)\)", meta)
        if flag_match:
            flags = [f.strip().encode() for f in flag_match.group(1).split() if f.strip()]
        size_match = re.search(r"RFC822\.SIZE (\d+)", meta)
        if size_match:
            size = int(size_match.group(1))

        msg = email.message_from_bytes(header_bytes)
        subject = decode_header_value(msg.get("Subject", ""))
        from_addr = decode_header_value(msg.get("From", ""))
        date = parse_mail_date(msg.get("Date", ""))
        unread = not has_flag(flags, b"\\Seen")
        has_attach = _header_has_attachment(msg)

        results.append(
            {
                "uid": int(uid),
                "date": date,
                "from": from_addr,
                "subject": subject,
                "unread": unread,
                "has_attachments": has_attach,
                "size": size,
            }
        )
    return results


def _header_has_attachment(msg) -> bool:
    """从 header 判断邮件是否含附件。"""
    ctype = msg.get_content_type()
    if ctype == "multipart/mixed" or ctype == "multipart/related":
        return True
    # 检查各 part 的 Content-Disposition
    if msg.is_multipart():
        for part in msg.walk():
            disposition = str(part.get("Content-Disposition", "")).lower()
            if "attachment" in disposition:
                return True
    return False


# ---------------------------------------------------------------------------
# 渲染
# ---------------------------------------------------------------------------


def render_json(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False, indent=2)


def render_table_messages(data: dict) -> str:
    """list/search 的 table 渲染。"""
    messages = data.get("messages", [])
    # 若消息含 folder 字段（来自 --all-folders），多显示一列
    has_folder = any(m.get("folder") for m in messages)
    if has_folder:
        lines = [
            f"System: {data.get('system', '')}  Folder: {data.get('folder', '')}  共 {data.get('total', 0)} 封"
        ]
        lines.append("文件夹  |  UID  |  日期  |  发件人  |  主题  |  未读  |  附件")
        for m in messages:
            unread = "是" if m.get("unread") else "否"
            attach = "有" if m.get("has_attachments") else "无"
            lines.append(
                f"{m.get('folder', '')}  |  {m.get('uid')}  |  {m.get('date')}  |  {m.get('from')}  |  "
                f"{m.get('subject')}  |  {unread}  |  {attach}"
            )
    else:
        lines = [
            f"System: {data.get('system', '')}  Folder: {data.get('folder', '')}  共 {data.get('total', 0)} 封"
        ]
        lines.append("UID  |  日期  |  发件人  |  主题  |  未读  |  附件")
        for m in messages:
            unread = "是" if m.get("unread") else "否"
            attach = "有" if m.get("has_attachments") else "无"
            lines.append(
                f"{m.get('uid')}  |  {m.get('date')}  |  {m.get('from')}  |  "
                f"{m.get('subject')}  |  {unread}  |  {attach}"
            )
    return "\n".join(lines)


def render_table_folders(data: dict) -> str:
    lines = [f"System: {data.get('system', '')}"]
    lines.append("文件夹")
    for f in data.get("folders", []):
        lines.append(f.get("name", ""))
    return "\n".join(lines)


def render_table_read(data: dict) -> str:
    h = data.get("headers", {})
    lines = [
        f"System: {data.get('system', '')}  Folder: {data.get('folder', '')}  UID: {data.get('uid')}",
        f"主题: {h.get('subject', '')}",
        f"发件人: {h.get('from', '')}",
        f"收件人: {h.get('to', '')}",
        f"抄送: {h.get('cc', '')}",
        f"日期: {h.get('date', '')}",
        f"未读: {'是' if data.get('unread') else '否'}",
        "",
        "正文:",
        data.get("body", ""),
        "",
        "附件:",
    ]
    attachments = data.get("attachments", [])
    if not attachments:
        lines.append("(无)")
    else:
        for a in attachments:
            lines.append(f"- {a.get('filename')} ({format_size(a.get('size'))})")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 子命令实现
# ---------------------------------------------------------------------------


def cmd_send(args) -> int:
    config = resolve_email_config(system=args.system, need_imap=False)

    to = parse_addresses(args.to)
    cc = parse_addresses(args.cc)
    bcc = parse_addresses(args.bcc)
    validate_addresses(to, "to")
    validate_addresses(cc, "cc")
    validate_addresses(bcc, "bcc")

    body = read_body(args.body)
    subject = args.subject if args.subject is not None else DEFAULT_SUBJECT

    message, recipients = build_message(
        from_address=config.from_address,
        to=to,
        cc=cc,
        bcc=bcc,
        subject=subject,
        body=body,
        html=args.html,
        attachments=args.attach or [],
        reply_to=args.reply_to,
    )

    server = get_smtp(config)
    try:
        server.sendmail(config.from_address, recipients, message.as_string())
    except Exception as exc:
        raise ServiceError(f"邮件发送失败: {exc}") from exc
    finally:
        try:
            server.quit()
        except Exception:
            pass

    result = {
        "status": "sent",
        "system": config.system_name,
        "from": config.from_address,
        "to": to,
        "cc": cc,
        "bcc": bcc,
        "subject": subject,
        "attachments": [os.path.basename(p) for p in (args.attach or [])],
        "message_id": message["Message-ID"],
    }
    print(render_json(result))
    return 0


def _collect_uids(server) -> list[bytes]:
    """UID SEARCH ALL 返回所有 UID，倒序（UID 大的在前）。"""
    status, data = server.uid("SEARCH", None, "ALL")
    if status != "OK":
        raise ServiceError("UID SEARCH 失败")
    raw = data[0] if data and data[0] else b""
    if isinstance(raw, str):
        raw = raw.encode()
    uids = [u for u in raw.split() if u]
    uids.reverse()  # UID 大的（新邮件）在前
    return uids


def _list_folder_names(server) -> list[str]:
    """列出 IMAP 服务器上所有文件夹名称。从已连接 server 获取。"""
    status, data = server.list()
    if status != "OK":
        raise ServiceError("LIST 文件夹失败")
    folders: list[str] = []
    for item in data:
        if not item:
            continue
        line = (
            item.decode("utf-8", errors="replace")
            if isinstance(item, (bytes, bytearray))
            else str(item)
        )
        # 格式: (\HasNoChildren) "/" "INBOX"  也可能是 (\HasNoChildren) "/" INBOX（不带引号）
        m = re.match(r'\(([^)]*)\)\s+"([^"]*)"\s+"?([^"]+)"?$', line)
        if m:
            name = m.group(3)
        else:
            # 备选：提取最后一组以空格分隔的值
            parts = line.rsplit(" ", 1)
            name = parts[-1].strip('"') if len(parts) > 1 else line.strip('"')
        folders.append(name)
    return folders


def _multifolder_search(server, criteria: list[str], limit: int) -> list[dict]:
    """在所有文件夹中执行 UID SEARCH，汇总结果。单连接内完成。"""
    folders = _list_folder_names(server)
    all_messages: list[dict] = []
    for folder in folders:
        try:
            select_folder(server, folder)
        except ServiceError:
            continue
        status, data = server.uid("SEARCH", None, *criteria)
        if status != "OK":
            continue
        raw = data[0] if data and data[0] else b""
        if isinstance(raw, str):
            raw = raw.encode()
        uids = [u for u in raw.split() if u]
        uids.reverse()
        uids = uids[:limit]
        msgs = _fetch_headers(server, uids)
        for m in msgs:
            m["folder"] = folder
        all_messages.extend(msgs)
    # 按日期降序排列，最新邮件在前
    all_messages.sort(key=lambda m: m.get("date", ""), reverse=True)
    return all_messages[:limit]


def _multifolder_list(server, unread_only: bool, limit: int) -> list[dict]:
    """在所有文件夹中列出邮件，汇总结果。单连接内完成。"""
    folders = _list_folder_names(server)
    all_messages: list[dict] = []
    for folder in folders:
        try:
            select_folder(server, folder)
        except ServiceError:
            continue
        uids = _collect_uids(server)
        if unread_only:
            uids = _filter_unread(server, uids)
        uids = uids[:limit]
        msgs = _fetch_headers(server, uids)
        for m in msgs:
            m["folder"] = folder
        all_messages.extend(msgs)
    all_messages.sort(key=lambda m: m.get("date", ""), reverse=True)
    return all_messages[:limit]


def cmd_list(args) -> int:
    config = resolve_email_config(system=args.system, need_imap=True)
    limit = _resolve_limit(args.limit, LIST_DEFAULT_LIMIT)

    server = get_imap(config)
    try:
        if args.all_folders:
            messages = _multifolder_list(server, unread_only=args.unread_only, limit=limit)
            folder_display = "(所有文件夹)"
        else:
            select_folder(server, args.folder)
            uids = _collect_uids(server)
            if args.unread_only:
                uids = _filter_unread(server, uids)
            uids = uids[:limit]
            messages = _fetch_headers(server, uids)
            folder_display = args.folder
    finally:
        _safe_logout(server)

    data = {
        "system": config.system_name,
        "folder": folder_display,
        "total": len(messages),
        "messages": messages,
    }
    _print_format(args.format, data, render_table_messages)
    return 0


def _filter_unread(server, uids: list[bytes]) -> list[bytes]:
    """从 UID 列表里筛出未读（不含 \\Seen）。"""
    result: list[bytes] = []
    for uid in uids:
        status, data = server.uid("FETCH", uid, "(FLAGS)")
        if status != "OK" or not data or data[0] is None:
            continue
        meta = data[0]
        if isinstance(meta, tuple):
            meta = meta[0]
        meta_str = (
            meta.decode("utf-8", errors="replace")
            if isinstance(meta, (bytes, bytearray))
            else str(meta)
        )
        if "\\Seen" not in meta_str:
            result.append(uid)
    return result


def cmd_read(args) -> int:
    config = resolve_email_config(system=args.system, need_imap=True)

    server = get_imap(config)
    try:
        select_folder(server, args.folder)
        status, data = server.uid("FETCH", str(args.uid), "(BODY.PEEK[] FLAGS)")
        if status != "OK" or not data or data[0] is None:
            raise ServiceError(f"读取 UID {args.uid} 失败，邮件可能不存在")
        raw = data[0]
        if not isinstance(raw, tuple) or len(raw) < 2:
            raise ServiceError(f"读取 UID {args.uid} 失败：返回格式异常")
        meta = (
            raw[0].decode("utf-8", errors="replace")
            if isinstance(raw[0], (bytes, bytearray))
            else str(raw[0])
        )
        raw_bytes = raw[1] if isinstance(raw[1], (bytes, bytearray)) else b""
        flags: list[bytes] = []
        flag_match = re.search(r"FLAGS \(([^)]*)\)", meta)
        if flag_match:
            flags = [f.strip().encode() for f in flag_match.group(1).split() if f.strip()]
        msg = email.message_from_bytes(raw_bytes)
    finally:
        _safe_logout(server)

    body, _ = extract_body(msg)
    attachments = list_attachments(msg)
    unread = not has_flag(flags, b"\\Seen")

    data_out = {
        "system": config.system_name,
        "folder": args.folder,
        "uid": args.uid,
        "headers": {
            "from": decode_header_value(msg.get("From", "")),
            "to": decode_header_value(msg.get("To", "")),
            "cc": decode_header_value(msg.get("Cc", "")),
            "subject": decode_header_value(msg.get("Subject", "")),
            "date": parse_mail_date(msg.get("Date", "")),
        },
        "body": body,
        "attachments": attachments,
        "unread": unread,
    }
    _print_format(args.format, data_out, render_table_read)
    return 0


def cmd_search(args) -> int:
    config = resolve_email_config(system=args.system, need_imap=True)
    limit = _resolve_limit(args.limit, SEARCH_DEFAULT_LIMIT)

    if not args.from_filter and not args.subject and not args.since:
        raise ServiceError("search 至少需要 --from / --subject / --since 中的一个条件")

    criteria: list[str] = []
    if args.from_filter:
        criteria += ["FROM", args.from_filter]
    if args.subject:
        criteria += ["SUBJECT", args.subject]
    if args.since:
        criteria += ["SINCE", _format_since(args.since)]

    server = get_imap(config)
    try:
        if args.all_folders:
            messages = _multifolder_search(server, criteria, limit)
            folder_display = "(所有文件夹)"
        else:
            select_folder(server, args.folder)
            status, data = server.uid("SEARCH", None, *criteria)
            if status != "OK":
                raise ServiceError("UID SEARCH 失败")
            raw = data[0] if data and data[0] else b""
            if isinstance(raw, str):
                raw = raw.encode()
            uids = [u for u in raw.split() if u]
            uids.reverse()
            uids = uids[:limit]
            messages = _fetch_headers(server, uids)
            folder_display = args.folder
    finally:
        _safe_logout(server)

    data_out = {
        "system": config.system_name,
        "folder": folder_display,
        "total": len(messages),
        "messages": messages,
    }
    _print_format(args.format, data_out, render_table_messages)
    return 0


def _format_since(date_str: str) -> str:
    """校验 YYYY-MM-DD 并转成 IMAP 日期格式 01-Jun-2021。"""
    try:
        y, m, d = date_str.split("-")
        year, month, day = int(y), int(m), int(d)
    except ValueError as exc:
        raise ServiceError(f"无效的日期格式，请用 YYYY-MM-DD: {date_str!r}") from exc
    if not (1 <= month <= 12 and 1 <= day <= 31):
        raise ServiceError(f"无效的日期: {date_str!r}")
    months = [
        "Jan",
        "Feb",
        "Mar",
        "Apr",
        "May",
        "Jun",
        "Jul",
        "Aug",
        "Sep",
        "Oct",
        "Nov",
        "Dec",
    ]
    return f"{day:02d}-{months[month - 1]}-{year}"


def cmd_folders(args) -> int:
    config = resolve_email_config(system=args.system, need_imap=True)

    server = get_imap(config)
    try:
        names = _list_folder_names(server)
    finally:
        _safe_logout(server)

    folders = [{"name": n, "delimiter": "/", "flags": []} for n in names]

    data_out = {"system": config.system_name, "folders": folders}
    _print_format(args.format, data_out, render_table_folders)
    return 0


def cmd_mark_read(args) -> int:
    config = resolve_email_config(system=args.system, need_imap=True)

    server = get_imap(config)
    try:
        select_folder(server, args.folder)
        if args.unread:
            status, _ = server.uid("STORE", str(args.uid), "-FLAGS", "(\\Seen)")
            action = "未读"
        else:
            status, _ = server.uid("STORE", str(args.uid), "+FLAGS", "(\\Seen)")
            action = "已读"
        if status != "OK":
            raise ServiceError(f"标记 UID {args.uid} 失败")
    finally:
        _safe_logout(server)

    print(json.dumps({"status": "ok", "uid": args.uid, "marked": action}, ensure_ascii=False))
    return 0


def cmd_save_attachments(args) -> int:
    config = resolve_email_config(system=args.system, need_imap=True, need_attachments_dir=True)

    save_dir = config.attachments_dir
    assert save_dir is not None
    os.makedirs(save_dir, exist_ok=True)

    server = get_imap(config)
    try:
        select_folder(server, args.folder)
        status, data = server.uid("FETCH", str(args.uid), "(BODY.PEEK[])")
        if status != "OK" or not data or data[0] is None:
            raise ServiceError(f"读取 UID {args.uid} 失败，邮件可能不存在")
        raw = data[0]
        if not isinstance(raw, tuple) or len(raw) < 2:
            raise ServiceError(f"读取 UID {args.uid} 失败：返回格式异常")
        raw_bytes = raw[1] if isinstance(raw[1], (bytes, bytearray)) else b""
        msg = email.message_from_bytes(raw_bytes)
    finally:
        _safe_logout(server)

    saved: list[dict] = []
    skipped: list[dict] = []
    index = 0

    def walk(part):
        nonlocal index
        if part.is_multipart():
            for sub in part.get_payload():
                walk(sub)
            return
        ctype = part.get_content_type()
        disposition = str(part.get("Content-Disposition", "")).lower()
        is_attachment = "attachment" in disposition
        if not is_attachment and ctype.startswith("text/"):
            return
        if not is_attachment and not part.get_filename():
            return

        filename = get_attachment_filename(part, index)
        payload = part.get_payload(decode=True)
        size = len(payload) if payload is not None else 0
        if size == 0:
            skipped.append({"original_filename": filename, "reason": "空附件"})
            index += 1
            return
        safe_name = safe_filename(filename)
        target = unique_path(save_dir, safe_name)
        try:
            with open(target, "wb") as f:
                f.write(payload)
        except OSError as exc:
            raise ServiceError(f"保存附件失败: {filename}: {exc}") from exc
        saved.append(
            {"original_filename": filename, "saved_as": os.path.basename(target), "size": size}
        )
        index += 1

    walk(msg)

    data_out = {
        "system": config.system_name,
        "folder": args.folder,
        "uid": args.uid,
        "save_dir": save_dir,
        "attachments": saved,
        "skipped": skipped,
    }
    print(render_json(data_out))
    return 0


# ---------------------------------------------------------------------------
# 通用辅助
# ---------------------------------------------------------------------------


def _resolve_limit(limit: int | None, default: int) -> int:
    if limit is None:
        return default
    if limit < 1:
        raise ServiceError(f"--limit 必须 >= 1，当前: {limit}")
    if limit > MAX_LIMIT:
        raise ServiceError(f"--limit 超过上限 {MAX_LIMIT}，当前: {limit}")
    return limit


def _safe_logout(server) -> None:
    try:
        server.logout()
    except Exception:
        pass


def _print_format(fmt: str, data: dict, table_renderer) -> None:
    if fmt == "table":
        print(table_renderer(data))
    else:
        print(render_json(data))


def print_error(err: ServiceError) -> int:
    print(f"Error: {err}", file=sys.stderr)
    return 1


# ---------------------------------------------------------------------------
# argparse
# ---------------------------------------------------------------------------


def add_system_arg(p: argparse.ArgumentParser) -> None:
    p.add_argument(
        "--system",
        default=None,
        help="配置文件中的邮箱系统名；未提供时使用 default_system",
    )


def add_format_arg(p: argparse.ArgumentParser) -> None:
    p.add_argument(
        "--format",
        choices=["json", "table"],
        default="json",
        help="输出格式：json（默认，给程序）或 table（给人看）",
    )


def add_folder_arg(p: argparse.ArgumentParser) -> None:
    p.add_argument(
        "--folder",
        default=DEFAULT_FOLDER,
        help=f"文件夹名，默认 {DEFAULT_FOLDER}",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="email_api.py",
        description="电子邮件收发（SMTP 发 / IMAP 收）",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # send
    p = sub.add_parser("send", help="发送邮件")
    add_system_arg(p)
    p.add_argument("--to", action="append", help="收件人（可多次或逗号分隔）")
    p.add_argument("--cc", action="append", help="抄送（可多次或逗号分隔）")
    p.add_argument("--bcc", action="append", help="密送（可多次或逗号分隔）")
    p.add_argument("--subject", default=None, help="主题，默认 (无主题)")
    p.add_argument("--body", required=True, help="正文；@file 前缀从文件读取")
    p.add_argument("--html", action="store_true", help="正文按 HTML 发送")
    p.add_argument("--attach", action="append", help="附件路径（可多次）")
    p.add_argument("--reply-to", default=None, help="Reply-To 回复地址")
    p.set_defaults(func=cmd_send)

    # list
    p = sub.add_parser("list", help="列出邮件摘要")
    add_system_arg(p)
    add_format_arg(p)
    add_folder_arg(p)
    p.add_argument(
        "--limit",
        type=int,
        default=None,
        help=f"数量上限，默认 {LIST_DEFAULT_LIMIT}，最大 {MAX_LIMIT}",
    )
    p.add_argument("--unread-only", action="store_true", help="只列未读")
    p.add_argument(
        "--all-folders", action="store_true", help="遍历所有文件夹（单连接），忽略 --folder"
    )
    p.set_defaults(func=cmd_list)

    # read
    p = sub.add_parser("read", help="读取单封邮件")
    add_system_arg(p)
    add_format_arg(p)
    add_folder_arg(p)
    p.add_argument("--uid", type=int, required=True, help="邮件 UID")
    p.set_defaults(func=cmd_read)

    # search
    p = sub.add_parser("search", help="搜索邮件")
    add_system_arg(p)
    add_format_arg(p)
    add_folder_arg(p)
    p.add_argument("--from", dest="from_filter", default=None, help="发件人关键词")
    p.add_argument("--subject", default=None, help="主题关键词")
    p.add_argument("--since", default=None, help="日期，格式 YYYY-MM-DD")
    p.add_argument(
        "--limit",
        type=int,
        default=None,
        help=f"数量上限，默认 {SEARCH_DEFAULT_LIMIT}，最大 {MAX_LIMIT}",
    )
    p.add_argument(
        "--all-folders", action="store_true", help="遍历所有文件夹（单连接），忽略 --folder"
    )
    p.set_defaults(func=cmd_search)

    # folders
    p = sub.add_parser("folders", help="列出所有文件夹")
    add_system_arg(p)
    add_format_arg(p)
    p.set_defaults(func=cmd_folders)

    # mark-read
    p = sub.add_parser("mark-read", help="标记邮件已读/未读")
    add_system_arg(p)
    add_folder_arg(p)
    p.add_argument("--uid", type=int, required=True, help="邮件 UID")
    p.add_argument("--unread", action="store_true", help="标记为未读（默认标记已读）")
    p.set_defaults(func=cmd_mark_read)

    # save-attachments
    p = sub.add_parser("save-attachments", help="下载邮件附件")
    add_system_arg(p)
    add_folder_arg(p)
    p.add_argument("--uid", type=int, required=True, help="邮件 UID")
    p.set_defaults(func=cmd_save_attachments)

    return parser


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    parser = build_parser()
    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except ServiceError as err:
        raise SystemExit(print_error(err)) from err
