# jenkins-restapi 配置

配置文件位置和顶层结构见 [config 规范](../../../docs/spec/config-spec.md)。本文件仅说明本 skill 特有的字段。

## config_name

`jenkins.json`，即 `~/.bicv/jenkins.json`。

## 字段

| 字段 | 必填 | 说明 |
|---|---|---|
| `url` | ✅ | Jenkins 服务地址 |
| `username` | ✅ | 用户名 |
| `password` | ✅ | API token 或密码 |

## 示例

```json
{
  "systems": {
    "default": {
      "url": "https://jenkins.example.com",
      "username": "lizhe",
      "password": "11abcdef..."
    }
  }
}
```