# Jenkins Remote Access API 参考

本文档是 Jenkins REST API 的完整参考手册。

## 认证方式

### HTTP Basic Auth（推荐）

使用用户名和 API Token：

```bash
curl -u "username:api-token" "https://jenkins.example.com/api/json"
```

> 注意：所有凭证必须通过 `~/.bicv/jenkins.json` 配置文件管理，不支持环境变量方式。

## API 端点

### 基础端点

| 端点 | 说明 |
|------|------|
| `/api/json` | 顶级 API 入口，获取全局信息 |
| `/api/xml` | XML 格式 |
| `/api/python` | Python 兼容 JSON |

### Job 相关端点

| 端点 | 说明 |
|------|------|
| `/job/{JOBNAME}/` | Job 首页 |
| `/job/{JOBNAME}/api/json` | Job 详情 |
| `/job/{JOBNAME}/build` | 触发构建 (POST) |
| `/job/{JOBNAME}/buildWithParameters` | 带参数触发构建 (POST) |
| `/job/{JOBNAME}/config.xml` | Job 配置 XML |
| `/job/{JOBNAME}/disable` | 禁用 Job (POST) |
| `/job/{JOBNAME}/enable` | 启用 Job (POST) |
| `/job/{JOBNAME}/doDelete` | 删除 Job (POST) |

### 构建相关端点

| 端点 | 说明 |
|------|------|
| `/job/{JOBNAME}/lastBuild/api/json` | 最后一次构建 |
| `/job/{JOBNAME}/lastSuccessfulBuild/api/json` | 最近成功构建 |
| `/job/{JOBNAME}/lastFailedBuild/api/json` | 最近失败构建 |
| `/job/{JOBNAME}/lastStableBuild/api/json` | 最近稳定构建 |
| `/job/{JOBNAME}/{BUILDNUMBER}/api/json` | 指定构建详情 |
| `/job/{JOBNAME}/{BUILDNUMBER}/consoleText` | 完整构建日志 |
| `/job/{JOBNAME}/{BUILDNUMBER}/logText/progressiveText` | 渐进式日志 |
| `/job/{JOBNAME}/{BUILDNUMBER}/stop` | 停止构建 (POST) |

### 视图相关端点

| 端点 | 说明 |
|------|------|
| `/view/{VIEWNAME}/api/json` | 视图信息 |
| `/view/{VIEWNAME}/job/{JOBNAME}/` | 视图中的 Job |

### 其他端点

| 端点 | 说明 |
|------|------|
| `/queue/api/json` | 构建队列信息 |
| `/computer/api/json` | 所有节点信息 |
| `/computer/{NODENAME}/api/json` | 指定节点信息 |
| `/system/api/json` | 系统信息 |
| `/pluginManager/api/json` | 插件信息 |
| `/createItem` | 创建 Job (POST) |

## 构建参数

### String Parameters

```bash
curl -X POST "https://jenkins.example.com/job/JOBNAME/buildWithParameters" \
     -u "username:token" \
     --data "id=123" --data "verbosity=high"
```

### File Parameter

```bash
curl -X POST "https://jenkins.example.com/job/JOBNAME/buildWithParameters" \
     -u "username:token" \
     --form "FILE_PARAM=@/path/to/file"
```

## 创建/复制 Job

### 创建 Job

```bash
curl -X POST "https://jenkins.example.com/createItem?name=NEW_JOB" \
     -u "username:token" \
     -H "Content-Type: application/xml" \
     --data "@config.xml"
```

### 复制 Job

```bash
curl -X POST "https://jenkins.example.com/createItem?name=NEW_JOB&mode=copy&from=EXISTING_JOB" \
     -u "username:token"
```

### 更新 Job 配置

```bash
curl -X POST "https://jenkins.example.com/job/JOBNAME/config.xml" \
     -u "username:token" \
     -H "Content-Type: application/xml" \
     --data "@new_config.xml"
```

## CSRF 防护

Jenkins 默认启用 CSRF 防护。

### 获取 Crumb

```bash
curl -s "https://jenkins.example.com/crumbIssuer/api/json" -u "username:token"
```

响应示例：
```json
{
  "crumbRequestField": "Jenkins-Crumb",
  "crumb": "abc123..."
}
```

### 使用 Crumb

```bash
curl -X POST "https://jenkins.example.com/job/JOBNAME/build" \
     -u "username:token" \
     -H "Jenkins-Crumb: abc123..."
```

## XPath 选择器

XML API 支持 XPath 查询：

```bash
# 基本查询
curl "https://jenkins.example.com/job/JOBNAME/api/xml?xpath=//displayName"

# 排除节点
curl "https://jenkins.example.com/job/JOBNAME/api/xml?exclude=//healthReport"

# 多重排除
curl "https://jenkins.example.com/job/JOBNAME/api/xml?exclude=//healthReport&exclude=//lastBuild"
```

## Depth 控制

```bash
# depth=0 基本信息（默认）
curl "https://jenkins.example.com/job/JOBNAME/api/json?depth=0"

# depth=1 更多嵌套数据
curl "https://jenkins.example.com/job/JOBNAME/api/json?depth=1"
```

## 响应格式

### JSON（格式化输出）

```bash
curl "https://jenkins.example.com/job/JOBNAME/api/json?pretty=true"
```

### Python 兼容 JSON

```bash
curl "https://jenkins.example.com/job/JOBNAME/api/python"
```

## 响应代码

| 代码 | 说明 |
|------|------|
| 200 | 成功 |
| 302 | 重定向 |
| 403 | 禁止访问（权限不足或 CSRF） |
| 404 | 未找到（Job/构建不存在） |
| 405 | 方法不支持 |
| 422 | 参数错误 |
| 500 | 服务器内部错误 |

## 常见错误

| 错误 | 原因 | 解决方案 |
|------|------|----------|
| 403 Forbidden | CSRF 或权限不足 | 使用 Crumb 或检查权限 |
| 404 Not Found | Job/构建不存在 | 检查 URL 拼写 |
| 405 Method Not Allowed | 不支持的 HTTP 方法 | 使用 POST 而非 GET |
| 422 Unprocessable Entity | 参数错误 | 检查构建参数 |

## Python 封装库

- **python-jenkins**: 通用封装库
- **JenkinsAPI**: 面向对象封装
- **api4jenkins**: REST API 封装
- **aiojenkins**: 异步版本

## 相关链接

- [官方文档](https://www.jenkins.io/doc/book/using/remote-access-api/)
- [GitHub 源码](https://github.com/jenkins-infra/jenkins.io)
