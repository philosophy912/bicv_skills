# 禅道 REST API 协议

## API 版本

当前使用的是禅道 v2 REST API。

```
Base URL: {zentao_url}/api.php/v2/
```

示例：
```
http://10.100.193.157:8081/api.php/v2/
```

## 认证机制

### Bearer Token 认证

禅道 v2 API 使用 Bearer Token 进行认证：

1. **获取 Token**：`POST /api.php/v2/tokens`
   - 请求体：`{"account": "your_username", "password": "your_password"}`
   - 响应：`{"token": "eyJ0eXAiOiJKV1Qi..."}`
   - Token 是一个 JWT 格式的字符串

2. **使用 Token**：在后续请求的 HTTP Header 中携带
   ```
   Authorization: Bearer eyJ0eXAiOiJKV1Qi...
   ```

### Token 刷新

Token 有一定有效期，过期后 API 会返回 HTTP 401。客户端应在收到 401 后：

1. 重新调用 `POST /api.php/v2/tokens` 获取新 token
2. 使用新 token 重试原始请求

## 请求头格式

| Header | 值 | 说明 |
|--------|-----|------|
| `Content-Type` | `application/json; charset=utf-8` | POST/PUT 请求必填 |
| `Authorization` | `Bearer {token}` | 已认证请求必填（除获取 token 外） |
| `Accept` | `application/json` | 可选 |

### 示例

```python
headers = {
    "Content-Type": "application/json; charset=utf-8",
    "Authorization": "Bearer eyJ0eXAiOiJKV1Qi..."
}
```

## 响应格式

### 成功响应

```json
{
    "status": "success",
    "data": { ... },
    "md5": "e59c3d1c4e3b1d0b7c8a9f5e6d4c3b2a"
}
```

- `status`：固定为 `"success"`
- `data`：响应数据体，可以是对象、数组或 null
- `md5`：data 字段的 MD5 校验值

### 错误响应

```json
{
    "status": "fail",
    "data": null,
    "md5": "..."
}
```

```json
{
    "status": "error",
    "data": "错误消息",
    "md5": "..."
}
```

## 分页机制

支持分页的列表接口统一使用 `page` 和 `limit` 参数：

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `page` | int | 1 | 页码，从 1 开始 |
| `limit` | int | 20 | 每页记录数 |

### 分页响应

```json
{
    "status": "success",
    "data": {
        "page": 1,
        "total": 100,
        "limit": 20,
        "items": [ ... ]
    },
    "md5": "..."
}
```

## 写入类操作通用确认要求

所有对系统有变更的操作（POST / PUT / DELETE）在执行前必须获得用户明确确认。

### 确认流程

1. 向用户展示待执行操作的详细信息（API 路径、HTTP 方法、参数）
2. 等待用户输入 `y` 或 `Y` 确认
3. 用户输入 `n`、`N` 或直接回车，取消操作

### 确认提示格式

```
⚠️ 高危操作确认
操作: DELETE /api.php/v2/bugs/{id}
资源: Bug ID={id}
影响: 永久删除 Bug 及其关联数据
确认执行? (y/N):
```

## 高危操作确认矩阵

### 严重级别（每次单独确认）

| 操作 | HTTP方法 | 影响 |
|------|----------|------|
| `delete-bug` | DELETE | 永久删除 Bug 及其关联数据 |
| `delete-task` | DELETE | 永久删除任务及其关联数据 |
| `delete-story` | DELETE | 永久删除需求及其关联数据 |
| `delete-project` | DELETE | 永久删除项目 |
| `delete-execution` | DELETE | 永久删除执行 |
| `delete-testcase` | DELETE | 永久删除测试用例 |
| `delete-testtask` | DELETE | 永久删除测试单 |
| `delete-release` | DELETE | 永久删除发布 |

### 高危级别（每次单独确认）

| 操作 | HTTP方法 | 影响 |
|------|----------|------|
| `create-bug` | POST | 创建新的 Bug 记录 |
| `create-task` | POST | 创建新的任务 |
| `create-story` | POST | 创建新的需求 |
| `create-project` | POST | 创建新的项目 |
| `create-execution` | POST | 创建新的执行 |
| `create-testcase` | POST | 创建新的测试用例 |
| `create-testtask` | POST | 创建新的测试单 |
| `create-release` | POST | 创建新的发布 |
| `update-bug` | PUT | 修改 Bug 信息 |
| `update-task` | PUT | 修改任务信息 |
| `update-story` | PUT | 修改需求信息 |
| `update-project` | PUT | 修改项目信息 |
| `update-execution` | PUT | 修改执行信息 |
| `close-bug` | PUT | 关闭 Bug |
| `close-task` | PUT | 关闭任务 |
| `close-story` | PUT | 关闭需求 |
| `resolve-bug` | PUT | 解决 Bug |
| `activate-bug` | PUT | 激活 Bug |
| `activate-task` | PUT | 激活任务 |
| `activate-story` | PUT | 激活需求 |
| `change-story` | PUT | 变更需求 |
| `finish-task` | PUT | 完成任务 |
| `start-task` | PUT | 启动任务 |
| `update-testcase` | PUT | 修改测试用例 |
| `update-testtask` | PUT | 修改测试单 |
| `update-release` | PUT | 修改发布 |

### 注意

> **拒绝默认**：对于任何 DELETE 请求，如果用户没有明确输入 `y` 或 `Y`，默认**不执行**。
>
> **每次独立确认**：每一个具体的严重或高危操作，都必须单独向用户确认，不能批量跳过。
