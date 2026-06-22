# config 规范

每个需要凭据/连接的 skill，在用户家目录下放一个 JSON 配置文件，声明一个或多个"系统"实例（多个 Gerrit / 多套 Jenkins / 多组 MySQL 等）。

## 文件位置

```
~/.bicv/<config_name>.json
```

`<config_name>` 由各 skill 内部固定，例如：

| skill | config_name |
|---|---|
| gerrit-restapi | `gerrit.json` |
| jenkins-restapi | `jenkins.json` |
| zentao-restapi | `zentao.json` |
| mysql | `database.json` |

文件必须位于用户家目录下（实现会校验路径必须 `relative_to(Path.home())`，防止路径穿越）。

## 文件结构

```json
{
  "systems": {
    "<system-name>": {
      "url": "https://...",
      "username": "...",
      "password": "..."
    },
    "<another-system>": {
      "url": "https://...",
      "username": "...",
      "http_password": "..."
    }
  }
}
```

**顶层必须有 `systems` 对象**，键是系统名（自己取，`--system foo` 时用），值是该系统的连接配置。

## 各 skill 字段

### gerrit-restapi (`~/.bicv/gerrit.json`)

| 字段 | 必填 | 说明 |
|---|---|---|
| `url` | ✅ | Gerrit 服务地址，例 `https://gerrit.example.com` |
| `username` | ✅ | HTTP 用户名 |
| `http_password` | ✅ | HTTP 密码（在 Gerrit 个人设置里生成） |
| `verify_ssl` | — | 是否校验 SSL 证书，默认 `true` |

密码字段读的是 `http_password`（不是 `password`）。

### jenkins-restapi (`~/.bicv/jenkins.json`)

| 字段 | 必填 | 说明 |
|---|---|---|
| `url` | ✅ | Jenkins 服务地址 |
| `username` | ✅ | 用户名 |
| `password` | ✅ | API token 或密码 |

### zentao-restapi (`~/.bicv/zentao.json`)

| 字段 | 必填 | 说明 |
|---|---|---|
| `url` | ✅ | 禅道服务地址 |
| `username` | ✅ | 用户名 |
| `password` | ✅ | 密码 |

### mysql (`~/.bicv/database.json`)

| 字段 | 必填 | 说明 |
|---|---|---|
| `host` | ✅ | MySQL 主机 |
| `port` | — | 端口，默认 `3306` |
| `username` | ✅ | 用户名 |
| `password` | — | 密码 |
| `database` | — | 默认数据库（CLI 可用 `-d` 覆盖） |

## 多系统实例

同一个 JSON 文件里可以放多个系统，键名就是 `--system` 用的标识：

```json
{
  "systems": {
    "prod": {
      "url": "https://gerrit.prod.example.com",
      "username": "lizhe",
      "http_password": "xxx"
    },
    "staging": {
      "url": "https://gerrit.staging.example.com",
      "username": "lizhe",
      "http_password": "yyy"
    }
  }
}
```

CLI 调用时通过 `--system prod` / `--system staging` 切换。也支持按 URL 别名模糊匹配。

## 加载机制

`services_config.load_systems_config(config_name)` 在脚本启动时调用：

1. 路径必须是 `~/.bicv/<config_name>`，否则报 `ServiceError`
2. 文件不存在 → 报 `Cannot find config file: <path>`
3. JSON 解析失败 → 报 `Config file is not valid JSON: <path>`
4. 顶层没有 `systems` 字典 → 报 `Config file is missing a systems object`

调用方根据 `ServiceError` 提示用户在正确位置创建文件。

## 安全说明

自用环境，凭据**明文存储**。`~/.bicv/` 不进任何仓库。整机备份 / 云同步需自行注意权限。

## 为什么放在 `~/.bicv/` 而不是各 skill 目录

- 仓库保持纯净，可安全提交 / 分发
- 集中管理，便于查看 / 备份 / 清理
- plugin 安装会把 skill 文件复制到平台 cache 目录，依赖相对路径的本地文件会丢失