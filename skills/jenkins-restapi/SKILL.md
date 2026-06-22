---
name: jenkins-restapi
description: |
  Jenkins 自动化服务器的 REST API 技能。当需要与 Jenkins 进行交互、查询构建状态、触发任务、管理 Jobs 等操作时使用此技能。所有调用必须通过仓库内的单一 Python 脚本执行；若接口未实现，必须先在该脚本内补充子命令后再执行。禁止直接内联 curl、临时 Python 请求代码或其他一次性 HTTP 调用。
---

# Jenkins REST API 技能

本技能通过 Jenkins Remote Access API 与目标实例交互。

## 首次使用：配置引导

首次使用本技能时，先检查配置文件 `~/.bicv/jenkins.json` 是否存在。

**若配置不存在**，使用 AskUserQuestion 引导用户完成配置，生成 `~/.bicv/jenkins.json`：

1. 询问 Jenkins 服务器地址（示例：`http://10.100.193.154:8080`）
2. 询问 Jenkins 用户名
3. 询问 Jenkins API Token（在 Jenkins 用户设置 → API Token 中生成）

```json
{
  "default_system": "default",
  "systems": {
    "default": {
      "url": "<用户输入的地址>",
      "aliases": ["default", "main"],
      "username": "<用户名>",
      "password": "<API Token>"
    }
  }
}
```

> API Token 保存到本地配置文件，不会上传到代码仓库。

## 强制执行约束

本技能的所有实际 API 调用必须遵守以下规则：

1. **只能通过单脚本执行**：只允许执行 `scripts/jenkins_api.py` 发起 Jenkins API 请求。
2. **禁止内联请求**：禁止直接执行内联 `curl` 命令、`python -c`、临时 heredoc 脚本、一次性 `urllib/request` 代码，或任何绕过 `scripts/jenkins_api.py` 的 HTTP 调用。
3. **接口缺失时先补子命令**：如果现有脚本不覆盖目标 API，必须先在 `scripts/jenkins_api.py` 中新增子命令，再通过该脚本执行；不能直接手写临时请求。
4. **优先复用现有脚本**：已有脚本能满足需求时，必须直接调用已有脚本，不得重复实现一次性命令。
5. **只支持 Python 标准库 HTTP**：新增或修改单入口脚本时，只使用 Python 标准库；不要引入 `requests`、`httpx`、`curl` 或其他额外 HTTP 依赖。

如果用户请求执行 Jenkins REST 操作，默认流程应为：

1. 在 `references/` 中确认接口和参数。
2. 检查 `scripts/jenkins_api.py` 中是否已有对应子命令。
3. 有子命令则直接执行该脚本。
4. 无子命令则先在该脚本中补充子命令，再执行。

## 认证与配置

### Jenkins 服务器配置

| 配置项 | 说明 | 获取方式 |
|--------|------|---------|
| `url` | Jenkins 服务地址 | 例如: `http://10.100.193.154:8080` |
| `username` | Jenkins 用户名 | Jenkins Web UI 个人信息页 |
| `password` | API Token 或密码 | 推荐使用用户 API Token |

获取 API Token 的常见步骤：
1. 登录 Jenkins Web UI
2. 打开用户个人设置页
3. 在 `API Token` 区域创建或复制 token
4. 执行时使用 `用户名:Token`

### 连接配置

连接配置仅通过 `~/.bicv/jenkins.json` 文件管理，不支持环境变量方式。

配置加载优先级：
1. 显式参数：`--system`、`--jenkins`、`--user`
2. `~/.bicv/jenkins.json` 中的 `default_system`

### 多 Jenkins 系统配置

默认配置文件路径为 `~/.bicv/jenkins.json`。脚本不接受 `--config`；只能读取这个固定路径。

通过 `jenkins.json` 可以定义一个默认 Jenkins 系统，并扩展多个命名系统。

```json
{
  "default_system": "default",
  "systems": {
    "default": {
      "url": "https://jenkins.example.com",
      "aliases": ["default", "main", "主系统"],
      "username": "your_username",
      "password": "your_token"
    },
    "backup": {
      "url": "https://jenkins-backup.example.com",
      "aliases": ["backup", "备系统"],
      "username": "backup_username",
      "password": "backup_token"
    }
  }
}
```

关键字段：`url`、`aliases`、`username`、`password`。

解析规则：
1. 未指定 `--system` 时，优先使用 `default_system`
2. 指定 `--system foo` 时，按系统名、`aliases`、URL 主机名、URL 中的域名匹配
3. `--user` 覆盖配置文件中的认证信息
4. 配置文件缺失时脚本直接报错退出

### 认证说明

认证信息由 `scripts/jenkins_api.py` 读取。执行时只通过脚本参数和 `~/.bicv/jenkins.json` 完成认证，不得直接编写临时 HTTP 请求代码。

## CSRF 防护

Jenkins 常见 POST 操作需要 crumb。`scripts/jenkins_api.py` 会在需要时自动请求 `/crumbIssuer/api/json` 并附加 crumb 头。

详细协议、响应码、depth 参数与常见端点见 `references/jenkins-remote-api.md`。

## 参考文档

`references/` 下保存 Jenkins Remote API 参考资料，不代表这些端点当前都已有实现。

### 当前实现覆盖范围

当前 `scripts/jenkins_api.py` 已实现以下子命令与端点：

| 子命令 | 方法 | 端点 |
|------|------|------|
| `list-jobs` | `GET` | `/api/json` |
| `get-job` | `GET` | `/job/{job}/api/json` |
| `get-build-info` | `GET` | `/job/{job}/{build}/api/json` |
| `get-console-log` | `GET` | `/job/{job}/{build}/consoleText` |
| `build-job` | `POST` | `/job/{job}/build` or `/job/{job}/buildWithParameters` |
| `list-queue` | `GET` | `/queue/api/json` |
| `disable-job` | `POST` | `/job/{job}/disable` |
| `enable-job` | `POST` | `/job/{job}/enable` |
| `stop-build` | `POST` | `/job/{job}/{build}/stop` |

处理原则：
1. 先看 `references/*.md` 确认目标 endpoint
2. 再看 `scripts/jenkins_api.py` 是否已有对应子命令
3. 没有实现时，先补新子命令，再执行

## 环境与工具选择

### 运行前提

| 环境 | 运行方式 | 说明 |
|------|----------|------|
| Linux | `python3` | 依赖 Python 3 标准库 |
| macOS | `python3` | 依赖 Python 3 标准库 |
| Windows | `python3` | 依赖 Python 3 标准库 |

### Python 环境检查

执行脚本前，只检查 Python 3 是否可用；不需要额外安装第三方库。

```bash
python3 --version
```

```powershell
python3 --version
```

## 使用方式

代表性命令：

```bash
# 只读查询
python3 scripts/jenkins_api.py list-jobs
python3 scripts/jenkins_api.py get-job --job "folder/demo" --depth 1
python3 scripts/jenkins_api.py get-build-info --job "folder/demo" --number lastSuccessfulBuild
python3 scripts/jenkins_api.py get-console-log --job "folder/demo" --number 42
python3 scripts/jenkins_api.py list-queue

# 写操作
python3 scripts/jenkins_api.py build-job --job "folder/demo" --user "username:token"
python3 scripts/jenkins_api.py build-job --job "folder/demo" --param env=prod --param region=cn --user "username:token"
python3 scripts/jenkins_api.py stop-build --job "folder/demo" --number 42 --user "username:token"
```

## 安全审查：高危与严重操作确认机制

在使用本技能执行任何写操作（POST/PUT/DELETE）前，必须先判断操作的危险等级。所有 **严重** 和 **高危** 操作在执行前**必须征得用户确认**。

### 确认规则

1. **每次操作独立确认**：针对每一个具体的严重或高危操作，都必须单独向用户确认。不能因为某种类型的操作已确认过一次，后续同类型操作就跳过确认。
2. **确认内容明确**：确认时必须告知用户即将执行的具体 API 接口、HTTP 方法、目标资源以及对系统的影响。
3. **用户明确同意后方可执行**：只有用户明确回复"确认"、"执行"、"同意"等肯定答复后，才能执行操作。用户拒绝或无响应时不得执行。

完整高危矩阵见 `references/safety-confirmation-matrix.md`。

## 详细参考

### references/ 目录

关键参考：
- `jenkins-remote-api.md`：Remote API 协议、认证、Crumb、depth 与常见端点
- `safety-confirmation-matrix.md`：高危/严重操作确认矩阵
- `config-schema.md`：本 skill 配置文件 `~/.bicv/jenkins.json` 的字段说明

### scripts/ 目录

| 目录 | 文件 | 用途 |
|------|------|------|
| `scripts/` | `jenkins_api.py` | 单入口脚本，包含已实现的全部子命令，并只使用 Python 标准库访问 HTTP 接口 |
