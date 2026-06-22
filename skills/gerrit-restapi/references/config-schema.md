# gerrit-restapi 配置

配置文件位置和顶层结构见 [config 规范](../../../docs/config-spec.md)。本文件仅说明本 skill 特有的字段。

## config_name

`gerrit.json`，即 `~/.bicv/gerrit.json`。

## 字段

| 字段 | 必填 | 说明 |
|---|---|---|
| `url` | ✅ | Gerrit 服务地址，例 `https://gerrit.example.com` |
| `username` | ✅ | HTTP 用户名 |
| `http_password` | ✅ | HTTP 密码（在 Gerrit 个人设置 → HTTP Password 生成） |
| `verify_ssl` | — | 是否校验 SSL 证书，默认 `true` |

> 密码字段读的是 `http_password`，不是 `password`。

## 示例

```json
{
  "systems": {
    "default": {
      "url": "https://gerrit.example.com",
      "username": "lizhe",
      "http_password": "xxxx"
    }
  }
}
```