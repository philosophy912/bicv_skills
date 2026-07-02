# email 配置

配置文件位置和顶层结构见 [config 规范](../../../docs/spec/config-spec.md)。本文件仅说明本 skill 特有的字段。

## config_name

`email.json`，即 `~/.bicv/email.json`。

## 字段

每个 system 包含收发两套独立配置：

| 字段 | 必填 | 说明 |
|---|---|---|
| `smtp.host` | ✅ | SMTP 服务器地址 |
| `smtp.port` | — | SMTP 端口，默认 `465` |
| `smtp.username` | ✅ | SMTP 登录用户名 |
| `smtp.password` | ✅ | SMTP 密码或授权码 |
| `imap.host` | 收信✅ | IMAP 服务器地址 |
| `imap.port` | — | IMAP 端口，默认 `993` |
| `imap.username` | 收信✅ | IMAP 登录用户名 |
| `imap.password` | 收信✅ | IMAP 密码或授权码 |
| `from_address` | ✅ | 发件人地址（邮件 From 头） |
| `attachments_dir` | save-attachments✅ | 附件保存目录，每个 system 各自一个 |

> 收发凭据分开存放：企业邮箱常见 SMTP/IMAP 主机或账号不同。大多数个人邮箱两者相同。
> `use_ssl` 固定为 true（写死 SMTP_SSL / IMAP4_SSL），无需配置。
> 「必填」按子命令区分：`send` 只需 smtp + from_address；收信子命令需要 imap；`save-attachments` 额外需要 attachments_dir。允许「只发不收」的配置。

## 示例

### 单实例

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

### 多实例

```json
{
  "default_system": "personal",
  "systems": {
    "personal": {
      "smtp": { "host": "smtp.qq.com", "port": 465, "username": "me@qq.com", "password": "授权码" },
      "imap": { "host": "imap.qq.com", "port": 993, "username": "me@qq.com", "password": "授权码" },
      "from_address": "me@qq.com",
      "attachments_dir": "/Users/<user>/Downloads/email-attachments/personal"
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

用 `--system work` 切换到 work 实例。
