# Gerrit REST API 协议详情

## 概述

Gerrit Code Review 提供了一套类 REST API，可通过 HTTP 访问。该 API 适用于构建自动化工具以及支持一些临时脚本场景。

## 认证

### 匿名访问

默认情况下，所有 REST 端点都假设为匿名访问，结果筛选对应匿名用户可读的内容（可能什么都没有）。

### HTTP Basic 认证

用户（或程序）可以通过在端点 URL 前添加 `/a/` 前缀来进行 HTTP 密码认证。例如要认证访问 `/projects/`，请求 URL `/a/projects/`。Gerrit 将使用用户账户设置页面中的 HTTP 密码进行 HTTP Basic 认证。这种认证方式绕过 XSRF 令牌的需求。

### Access Token 认证

授权 cookie 可以通过 URL 中的 `access_token` 查询参数提供。使用有效的 `access_token` 时不需要 XSRF 令牌。

## CORS

如果管理员配置了 `site.allowOriginRegex`，则支持跨站脚本。

来自允许来源的已批准 Web 应用程序可以依赖 CORS 预检来授权需要 cookie 认证的请求或突变操作（POST、PUT、DELETE）。突变需要有效的 XSRF 令牌在 `X-Gerrit-Auth` 请求头中。

应用程序也可以使用 URL 中的 `access_token`（见上文）来授权请求。作为 POST 发送且内容类型为 `text/plain` 的突变可以跳过 CORS 预检。Gerrit 接受额外的查询参数 `$m` 来覆盖正确的方法（PUT、POST、DELETE）和 `$ct` 来指定实际的内容类型，例如 `application/json; charset=UTF-8`。

**示例**:
```
POST /changes/42/topic?$m=PUT&$ct=application/json%3B%20charset%3DUTF-8&access_token=secret HTTP/1.1
Content-Type: text/plain
Content-Length: 23

{"topic": "new-topic"}
```

## 前置条件

客户端可以通过在请求 HTTP 头中添加 `If-None-Match: *` 来请求 PUT 创建新资源而不是覆盖现有资源。如果命名资源已存在，服务器将返回 HTTP 412 Precondition Failed。

## 向后兼容性

REST API 会定期扩展（例如添加新的 REST 端点或 JSON 实体中的新字段）。REST API 的调用者必须能够处理这些情况（例如忽略 REST 响应中的未知字段）。尽量避免不兼容的更改，但在极少数情况下可能会发生。如果发生，会在发布说明中宣布。

## 输出格式

JSON 响应使用 UTF-8 编码，使用内容类型 `application/json`。

默认情况下，大多数 API 返回格式化 JSON（pretty-printed），使用额外的空白使输出对人类更易读。

可以通过设置 `pp=0` 查询参数或设置 `Accept` HTTP 请求头来包含 `application/json` 来请求紧凑 JSON：

```http
GET /projects/ HTTP/1.0
Accept: application/json
```

生成（和解析）非格式化的紧凑格式更高效，因此工具应尽可能请求它。

### XSSI 防护

为了防止跨站脚本包含（XSSI）攻击，JSON 响应体以一个魔术前缀行开头，在馈送到 JSON 解析器之前必须将其剥离：

```
)]}'
[ ... valid JSON ... ]
```

如果 HTTP `Accept-Encoding` 请求头设置为 `gzip`，响应将被服务器 gzip 压缩。这可以节省大型响应的网络传输时间。

## 输入格式

未知的 JSON 参数将被 Gerrit 直接忽略而不会导致异常。这也适用于区分大小写的参数，如映射键。

## 时间戳

时间戳使用 UTC 格式：`'yyyy-mm-dd hh:mm:ss.fffffffff'`，其中 `'ffffffffff'` 表示纳秒。

## 编码

REST 调用 URL 中出现的所有 ID（例如项目名称、组名称）必须进行 URL 编码。

## 响应代码

Gerrit REST 端点使用 HTTP 状态码。大多数错误响应的响应体将是纯文本的人类可读错误消息。

### 400 Bad Request

当请求由于格式错误而未被服务器理解时返回"400 Bad Request"。例如，当需要 JSON 输入但请求的 'Content-Type' 不是 'application/json' 或请求体不包含有效 JSON 时返回"400 Bad Request"。当必填输入字段未设置或设置了不能一起使用的选项时也会返回"400 Bad Request"。

### 403 Forbidden

当操作不允许因为调用用户没有足够的权限时返回"403 Forbidden"。例如，某些 REST 端点需要调用用户具有某些全局能力。当 `self` 用作账户 ID 且 REST 调用未经过认证时也会返回"403 Forbidden"。

### 404 Not Found

当 URL 指定的资源未找到或对调用用户不可见时返回"404 Not Found"。如果 URL 包含不存在的 ID 或视图，则无法找到资源。

### 405 Method Not Allowed

当资源存在但不支持操作时返回"405 Method Not Allowed"。例如，某些 `/groups/` 端点仅支持 Gerrit 内部组；如果对外部组调用它们，则响应为"405 Method Not Allowed"。

### 409 Conflict

当请求无法完成因为资源的当前状态不允许操作时返回"409 Conflict"。例如，如果你尝试提交已放弃的变更，则会因状态不允许提交操作而失败并返回"409 Conflict"。如果你尝试创建但名称已被现有资源占用，也会返回"409 Conflict"。

### 412 Precondition Failed

当请求头字段的前置条件未满足时返回"412 Precondition Failed"。

### 422 Unprocessable Entity

当请求体中指定的资源 ID 无法解析时返回"422 Unprocessable Entity"。

### 429 Too Many Requests

当请求耗尽任何设置的配额限制时返回"429 Too Many Requests"。根据耗尽的配额，可以以指数退避重试。

## 请求追踪

通过设置 `trace=<trace-id>` 请求参数可以为每个 REST 端点启用追踪。建议使用正在调查的问题 ID 作为追踪 ID。

也可以省略追踪 ID 并获取生成的唯一追踪 ID。

请求追踪也可以通过设置 `X-Gerrit-Trace` 头来启用。

启用追踪会产生写入 `error_log` 的额外调试信息日志。所有对应追踪请求的日志都关联追踪 ID。追踪 ID 在 REST 响应的 `X-Gerrit-Trace` 头中返回。

## 设置截止时间

调用 REST 端点时，客户端可以设置请求应被中止的截止时间。为此必须在请求上设置 `X-Gerrit-Deadline` 头。值必须使用标准时间单位缩写（'ms'、'sec'、'min' 等）。

设置请求上的截止时间会覆盖主机上配置的任何服务器端截止时间。

## X-Gerrit-UpdatedRef

只有当请求头中设置了 "X-Gerrit-UpdatedRef-Enabled" 为 "true" 时才启用此功能。

对于每个写入 REST 请求，我们返回 X-Gerrit-UpdatedRef 头，作为当前请求中更新的 ref（在当前请求中涉及的 ref 事务中）。

这些头的格式为 `PROJECT_NAME~REF_NAME~OLD_SHA-1~NEW_SHA-1`。项目和 ref 名称是 URL 编码的，必须使用 %7E 表示 '~'。

新的 SHA-1 `0000000000000000000000000000000000000000` 被视为已删除的 ref。如果新的 SHA-1 不是 `0000000000000000000000000000000000000000`，则 ref 被更新或创建。如果旧的 SHA-1 是 `0000000000000000000000000000000000000000`，则 ref 被创建。
