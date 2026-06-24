---
name: email
description: 电子邮件收发技能，通过 SMTP 发送邮件、IMAP 读取和管理邮件。支持发送带附件的纯文本/HTML 邮件，列出/搜索/读取收件箱邮件，标记已读，按需下载附件。当用户需要发邮件、收邮件、查看收件箱、搜索邮件、下载附件时使用此技能。通过 scripts/email_api.py 执行，配置存于 ~/.bicv/email.json，支持多邮箱实例切换。
---

# Email Skill

> **平台提示：** Windows 用户请将命令中的 `python3` 替换为 `python`。

## 首次使用：配置引导

首次使用本技能时，先检查配置文件 `~/.bicv/email.json` 是否存在。

**若配置不存在**，使用 AskUserQuestion 引导用户完成配置，生成 `~/.bicv/email.json`：

1. 询问 SMTP 服务器地址（示例：`smtp.qq.com`）
2. 询问 SMTP 端口（默认 `465`）
3. 询问 SMTP 用户名（邮箱地址）
4. 询问 SMTP 密码或授权码
5. 询问 IMAP 服务器地址（示例：`imap.qq.com`）
6. 询问 IMAP 端口（默认 `993`）
7. 询问 IMAP 用户名/密码（通常与 SMTP 相同）
8. 询问发件人地址（from_address）
9. 询问附件保存目录（attachments_dir）

```json
{
  "default_system": "default",
  "systems": {
    "default": {
      "smtp": {
        "host": "smtp.qq.com",
        "port": 465,
        "username": "me@qq.com",
        "password": "授权码"
      },
      "imap": {
        "host": "imap.qq.com",
        "port": 993,
        "username": "me@qq.com",
        "password": "授权码"
      },
      "from_address": "me@qq.com",
      "attachments_dir": "/Users/<user>/Downloads/email-attachments/default"
    }
  }
}
```

> 密码/授权码保存到本地配置文件，不会上传到代码仓库。

## Overview

提供电子邮件收发能力：SMTP_SSL 发信、IMAP4_SSL 收信。纯 Python 标准库实现，零依赖。支持通过 `~/.bicv/email.json` 配置多个邮箱实例，通过 `--system` 参数切换。所有连接固定使用 SSL。

## When to Use This Skill

- 发送邮件（纯文本/HTML、带附件、抄送/密送）
- 列出收件箱邮件摘要
- 读取单封邮件完整内容
- 按发件人/主题/日期搜索邮件
- 查看邮箱文件夹列表
- 标记邮件已读/未读
- 下载邮件附件

## 连接配置

配置文件路径：`~/.bicv/email.json`

```json
{
  "default_system": "default",
  "systems": {
    "default": {
      "smtp": {
        "host": "smtp.qq.com",
        "port": 465,
        "username": "me@qq.com",
        "password": "授权码"
      },
      "imap": {
        "host": "imap.qq.com",
        "port": 993,
        "username": "me@qq.com",
        "password": "授权码"
      },
      "from_address": "me@qq.com",
      "attachments_dir": "/Users/<user>/Downloads/email-attachments/default"
    },
    "work": {
      "smtp": { "host": "smtp.company.com", "port": 465, "username": "me@company.com", "password": "pwd" },
      "imap": { "host": "imap.company.com", "port": 993, "username": "me@company.com", "password": "pwd" },
      "from_address": "me@company.com",
      "attachments_dir": "/Users/<user>/Downloads/email-attachments/work"
    }
  }
}
```

关键字段：
- `smtp`/`imap`：收发各自独立的连接配置（host/port/username/password），port 默认 465/993
- `from_address`：发件人地址（邮件 From 头）
- `attachments_dir`：附件保存目录，每个 system 各自一个，避免多实例冲突

配置加载优先级：
1. `--system` CLI 参数 → 匹配指定邮箱
2. `~/.bicv/email.json` 中的 `default_system`

使用 `--system` 切换实例：

```bash
python3 scripts/email_api.py list --system work
python3 scripts/email_api.py send --to a@x.com --subject Hi --body Hello --system work
```

## 当前实现覆盖范围

| 类别 | 子命令 | 说明 |
|------|--------|------|
| 发信 | `send` | 纯文本/HTML、附件、抄送/密送 |
| 收信-列表 | `list` | 最新邮件摘要，默认 100 封 |
| 收信-读取 | `read` | 单封邮件完整内容 |
| 收信-搜索 | `search` | 按发件人/主题/日期 |
| 收信-文件夹 | `folders` | 列出所有文件夹 |
| 收信-标记 | `mark-read` | 标记已读/未读 |
| 收信-附件 | `save-attachments` | 下载邮件附件 |

完整子命令列表见 `scripts/email_api.py --help`。

## Operations

### 发送邮件（SMTP）

```bash
# 纯文本邮件
python3 scripts/email_api.py send --to a@x.com --subject "通知" --body "内容"

# HTML 邮件（正文从文件读取，Agent 生成 HTML 写临时文件）
python3 scripts/email_api.py send --to a@x.com --subject "报告" --body @report.html --html

# 带附件
python3 scripts/email_api.py send --to a@x.com --subject "报表" --body "见附件" --attach ./report.pdf

# 多收件人 + 抄送 + 密送
python3 scripts/email_api.py send --to a@x.com --to b@x.com --cc c@x.com --bcc d@x.com \
  --subject "周会" --body "请准时参加"

# --body 直接传文本 或 @文件
python3 scripts/email_api.py send --to a@x.com --subject Hi --body "短文本"
python3 scripts/email_api.py send --to a@x.com --subject Hi --body @body.txt
```

发信参数：
- `--to`（必填，多值）、`--subject`（默认 `(无主题)`）、`--body`（必填，支持 `@file`）
- 可选：`--html`、`--cc`、`--bcc`、`--attach`（多值）、`--reply-to`、`--system`
- From 地址用配置 `from_address`，命令行不可覆盖

### 列出邮件（IMAP）

```bash
# 最新 100 封摘要
python3 scripts/email_api.py list

# 只看未读
python3 scripts/email_api.py list --unread-only

# 指定数量和文件夹
python3 scripts/email_api.py list --limit 20 --folder Sent

# 表格格式（给人看）
python3 scripts/email_api.py list --format table
```

### 读取单封邮件

```bash
python3 scripts/email_api.py read --uid 123
python3 scripts/email_api.py read --uid 123 --folder Sent --format table
```

### 搜索邮件

```bash
python3 scripts/email_api.py search --from gerrit
python3 scripts/email_api.py search --subject review --limit 20
python3 scripts/email_api.py search --since 2026-06-01 --from boss
```

### 文件夹列表

```bash
python3 scripts/email_api.py folders
```

### 标记已读/未读

```bash
python3 scripts/email_api.py mark-read --uid 123
python3 scripts/email_api.py mark-read --uid 123 --unread
```

### 下载附件

```bash
# 落地到配置的 attachments_dir
python3 scripts/email_api.py save-attachments --uid 123
```

## 输出格式

- `--format json`（默认）：结构化 JSON，便于程序解析
- `--format table`：纯文本表格，便于人阅读
- 支持 `--format` 的子命令：`list`、`read`、`search`、`folders`
- 动作类子命令（`send`、`mark-read`、`save-attachments`）固定输出 JSON

## 安全说明

- **发信直接发送，不弹确认**：本技能定位为编排层的原子能力，确认/重试由上层 Agent 负责，不在脚本内阻塞等待用户输入
- **附件落地安全**：`save-attachments` 落地时只取文件 basename（防路径穿越）、非法字符替换、重名追加序号；0 字节附件跳过并列入 `skipped`
- **附件保存目录**：由配置 `attachments_dir` 决定，每个邮箱实例各自一个目录
- **不标记已读**：`list`/`read` 用 `BODY.PEEK` 读取，不改变邮件已读状态；标记已读是 `mark-read` 的专属职责
- **凭据明文存储**：自用环境，`~/.bicv/` 不进任何仓库

## Scripts

### scripts/email_api.py

单入口脚本，包含全部子命令：

```bash
python3 scripts/email_api.py <子命令> [参数] [--system NAME]
```

特性：
- 从 `~/.bicv/email.json` 读取连接配置
- 支持多邮箱实例（`--system` 切换）
- SMTP_SSL/IMAP4_SSL 固定 SSL 连接
- 全文统一 UID 定位邮件
- 中文主题/正文/附件名正确处理
- 失败即报错退出（退出码 1，错误信息走 stderr）

详细示例和常见邮箱配置参考：`references/usage_guide.md`

配置文件 `~/.bicv/email.json` 的字段说明：`references/config-schema.md`
