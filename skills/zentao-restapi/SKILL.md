---
name: zentao-restapi
description: |
  禅道（ZenTao）项目管理软件的 REST API 技能。用于通过禅道开放接口（v2）操作 Bug、任务、需求、测试用例等资源。当用户需要与禅道系统交互时使用此技能。已有子命令时优先通过 scripts/zentao_api.py 执行；接口未实现时允许扩展脚本或编写临时请求。
---

# 禅道 REST API 技能

本技能通过禅道 v2 REST API 与目标实例交互。

## 首次使用：配置引导

首次使用本技能时，先检查配置文件 `~/.bicv/zentao.json` 是否存在。

**若配置不存在**，使用 AskUserQuestion 引导用户完成配置，生成 `~/.bicv/zentao.json`：

1. 询问禅道服务器地址（示例：`http://zentao.example.com`）
2. 询问禅道用户名（账号）
3. 询问禅道密码

```json
{
  "default_system": "default",
  "systems": {
    "default": {
      "url": "<用户输入的地址>",
      "username": "<用户名>",
      "password": "<密码>"
    }
  }
}
```

> 密码保存到本地配置文件，不会上传到代码仓库。

## 执行策略

### 优先复用已有脚本

当 `scripts/zentao_api.py` 已包含目标接口的子命令时，**必须**直接调用该脚本，不得重复实现。

### 接口未实现时的选择

1. **扩展脚本**（推荐）：在 `scripts/zentao_api.py` 中新增子命令，再执行。
2. **临时请求**（允许）：自行编写 `curl` 或临时脚本完成请求。适合一次性探索或不常用的接口。

### 环境约束

- **脚本标准库**：扩展 `scripts/zentao_api.py` 时，只使用 Python 标准库；不要引入 `requests`、`httpx` 等第三方库。
- **认证复用**：临时请求通过 `~/.bicv/zentao.json` 获取认证信息。

### 默认执行流程

1. 在 `references/` 中确认接口和参数。
2. 检查 `scripts/zentao_api.py` 中是否已有对应子命令。
3. **有子命令**：直接执行该脚本。
4. **无子命令**：若该接口预计会重复使用，优先在脚本中新增子命令；否则可编写临时请求。

## 认证与配置

### 禅道服务器配置

配置文件路径：`~/.bicv/zentao.json`

```json
{
  "default_system": "default",
  "systems": {
    "default": {
      "url": "http://zentao.example.com",
      "username": "your_account",
      "password": "your_password"
    }
  }
}
```

关键字段：`url`、`username`、`password`。

### 认证方式

禅道 v2 API 使用 Bearer Token 认证：
1. 调用 `POST /api.php/v2/tokens` 获取 token
2. 后续请求在 `Authorization: Bearer {token}` 中携带
3. Token 过期返回 401，自动重新获取

### 配置加载优先级

1. 显式参数：`--system`、`--zentao`、`--user`
2. `~/.bicv/zentao.json` 中的 `default_system`

详细 API 协议见 `references/禅道API协议.md`。

## 响应格式

禅道 v2 API 返回标准 JSON 响应：

```json
{
  "status": "success",
  "data": { ... },
  "md5": "..."
}
```

详细的请求/响应结构见 API 协议文档。

## 参考文档

`references/` 下保存禅道 REST API 参考全集，不代表这些端点当前都已有实现。

### 当前实现覆盖范围

| 域 | 子命令数 | 说明 |
|------|---------|------|
| Token | 1 | `get-token` |
| Bug 管理 | 8 | 增删改查、解决、关闭、激活 |
| 任务管理 | 9 | 增删改查、启动、完成、关闭、激活 |
| 需求管理 | 8 | 增删改查、变更、关闭、激活 |
| 产品/项目管理 | 7 | 产品/项目列表、详情、增删改 |
| 执行管理 | 5 | 执行列表、详情、增删改 |
| 测试用例 | 5 | 用例列表、详情、增删改 |
| 测试单 | 4 | 测试单列表、详情、增删 |
| 其他 | 15 | 用户、部门、发布、版本、反馈等 |

完整子命令列表见 `scripts/zentao_api.py --help`。

## 使用方式

代表性命令：

```bash
# Token 管理
python3 scripts/zentao_api.py get-token

# Bug 管理
python3 scripts/zentao_api.py list-bugs --product 1
python3 scripts/zentao_api.py create-bug --product 1 --title "登录页面崩溃" --severity 3

# 任务管理
python3 scripts/zentao_api.py list-tasks --project 1
python3 scripts/zentao_api.py create-task --project 1 --name "实现用户注册" --estimate 8

# 需求管理
python3 scripts/zentao_api.py list-stories --product 1
python3 scripts/zentao_api.py create-story --product 1 --title "支持第三方登录"

# 测试用例
python3 scripts/zentao_api.py list-testcases --product 1
python3 scripts/zentao_api.py get-testcase --id 100
python3 scripts/zentao_api.py create-testcase --product 1 --title "验证用户登录功能"
```

## 高危操作确认

在使用本技能执行写操作（POST/PUT/DELETE）前，必须先判断操作的危险等级。所有 **严重** 和 **高危** 操作在执行前**必须征得用户确认**。

确认规则见 `references/禅道API协议.md#高危操作确认矩阵`。

## 详细参考

### references/ 目录

- `禅道API协议.md`：认证、请求、响应格式、分页、高危操作确认矩阵
- `Bug管理.md`、`任务管理.md`、`需求管理.md` 等：各领域 API 参考
- `config-schema.md`：本 skill 配置文件 `~/.bicv/zentao.json` 的字段说明

### scripts/ 目录

- `zentao_api.py`：单入口脚本，包含已实现的全部子命令
