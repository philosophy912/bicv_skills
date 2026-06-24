# email 使用指南

## 常见邮箱配置速查

| 邮箱 | SMTP | IMAP |
|---|---|---|
| QQ 邮箱 | smtp.qq.com:465 | imap.qq.com:993 |
| Foxmail | smtp.qq.com:465 | imap.qq.com:993 |
| 网易 163 | smtp.163.com:465 | imap.163.com:993 |
| 网易企业邮箱 | smtphz.qiye.163.com:465 | imaphz.qiye.163.com:993 |
| Gmail | smtp.gmail.com:465 | imap.gmail.com:993（⚠️ 需 OAuth2，本 skill 首版不支持纯密码登录） |

> **授权码获取**：QQ/网易等邮箱需在邮箱网页端「设置 → 账号」里开启 SMTP/IMAP 服务，获取「授权码」作为 password 填入配置（不是登录密码）。
> **固定 SSL**：本 skill 写死使用 SMTP_SSL / IMAP4_SSL，端口默认 465 / 993。

## 子命令详解

### send — 发送邮件

```bash
python3 scripts/email_api.py send --to <收件人> --subject <主题> --body <正文> [选项]
```

参数：
- `--to`（必填）：收件人，可多次传或逗号分隔（自动去重）
- `--subject`：主题，默认 `(无主题)`
- `--body`（必填）：正文，`@file` 前缀从文件读取
- `--html`：正文按 HTML 发送（自动生成纯文本兜底）
- `--cc`：抄送，多值
- `--bcc`：密送，多值（不写进邮件头，实际投递包含）
- `--attach`：附件路径，可多次
- `--reply-to`：Reply-To 回复地址
- `--system`：指定邮箱实例

#### 正文从文件读取（推荐，Agent 生成 HTML 时）

```bash
# Agent 生成 HTML 正文写到临时文件，再传给 --body
python3 scripts/email_api.py send --to a@x.com --subject "周报" --body @/tmp/weekly.html --html
```

```bash
# 纯文本正文直接传
python3 scripts/email_api.py send --to a@x.com --subject Hi --body "短消息"
```

#### 带附件

```bash
python3 scripts/email_api.py send --to a@x.com --subject "报表" --body "见附件" \
  --attach ./report.pdf --attach ./data.xlsx
```

#### 抄送 + 密送

```bash
python3 scripts/email_api.py send --to a@x.com,b@x.com --cc c@x.com --bcc d@x.com \
  --subject "通知" --body "内容"
```

输出（JSON）：

```json
{
  "status": "sent",
  "system": "default",
  "from": "me@qq.com",
  "to": ["a@x.com"],
  "cc": [],
  "bcc": [],
  "subject": "通知",
  "attachments": [],
  "message_id": "<...@qq.com>"
}
```

### list — 列出邮件摘要

```bash
python3 scripts/email_api.py list [选项]
```

参数：
- `--folder`：文件夹，默认 `INBOX`
- `--limit`：数量上限，默认 `100`，最大 `500`
- `--unread-only`：只列未读
- `--format`：`json`（默认）/ `table`
- `--system`：指定邮箱实例

```bash
python3 scripts/email_api.py list
python3 scripts/email_api.py list --unread-only
python3 scripts/email_api.py list --limit 20 --folder Sent
python3 scripts/email_api.py list --format table
```

摘要字段：`uid`、`date`、`from`、`subject`、`unread`、`has_attachments`、`size`

### read — 读取单封邮件

```bash
python3 scripts/email_api.py read --uid <UID> [选项]
```

参数：`--uid`（必填）、`--folder`、`--format`、`--system`

```bash
python3 scripts/email_api.py read --uid 123
python3 scripts/email_api.py read --uid 123 --folder Sent --format table
```

输出：邮件头 + 正文 + 附件清单。不下载附件，不标记已读。

### search — 搜索邮件

```bash
python3 scripts/email_api.py search [--from <发件人>] [--subject <主题>] [--since <日期>] [选项]
```

参数：
- `--from`：发件人关键词
- `--subject`：主题关键词
- `--since`：日期，格式 `YYYY-MM-DD`
- `--limit`：默认 `20`，最大 `500`
- `--folder`、`--format`、`--system`

> 多条件为 AND（同时满足），至少给一个条件。不支持正文搜索（IMAP `BODY` 搜索服务端支持不稳）。

```bash
python3 scripts/email_api.py search --from gerrit
python3 scripts/email_api.py search --subject "代码审查" --since 2026-06-01
```

### folders — 列出文件夹

```bash
python3 scripts/email_api.py folders [--format json|table] [--system NAME]
```

```bash
python3 scripts/email_api.py folders
python3 scripts/email_api.py folders --format table
```

### mark-read — 标记已读/未读

```bash
python3 scripts/email_api.py mark-read --uid <UID> [--unread] [--folder FOLDER] [--system NAME]
```

```bash
python3 scripts/email_api.py mark-read --uid 123          # 标记已读
python3 scripts/email_api.py mark-read --uid 123 --unread  # 标记未读
```

批量标记由上层 Agent 循环调用。

### save-attachments — 下载附件

```bash
python3 scripts/email_api.py save-attachments --uid <UID> [--folder FOLDER] [--system NAME]
```

附件落地到配置的 `attachments_dir`（每个 system 各自一个）。

安全处理：
- 只取 basename 防路径穿越
- 非法字符替换为 `_`
- 重名自动追加序号（`report.pdf` → `report_1.pdf`）
- 目录不存在自动创建
- 0 字节附件跳过，列入 `skipped`

输出（JSON）：

```json
{
  "system": "default",
  "folder": "INBOX",
  "uid": 123,
  "save_dir": "/Users/<user>/Downloads/email-attachments/default",
  "attachments": [
    {"original_filename": "report.pdf", "saved_as": "report.pdf", "size": 12345}
  ],
  "skipped": []
}
```

## 多实例切换

```bash
# 用 work 实例发信
python3 scripts/email_api.py send --to client@x.com --subject Hi --body Hello --system work

# 查 work 实例收件箱
python3 scripts/email_api.py list --system work
```

## 错误处理

- 成功退出码 0，失败退出码 1
- 错误信息走 stderr（`Error: <信息>`），正常结果走 stdout
- 配置缺失/字段不完整会报错并提示缺哪个字段
- 文件夹不存在会提示用 `folders` 子命令查看可用列表
- 发信/收信失败即报错退出，不做自动重试（重试由上层 Agent 调度）
