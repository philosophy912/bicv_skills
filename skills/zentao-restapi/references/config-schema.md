# zentao-restapi 配置

配置文件位置和顶层结构见 [config 规范](../../../docs/config-spec.md)。本文件仅说明本 skill 特有的字段。

## config_name

`zentao.json`，即 `~/.bicv/zentao.json`。

## 字段

| 字段 | 必填 | 说明 |
|---|---|---|
| `url` | ✅ | 禅道服务地址 |
| `username` | ✅ | 用户名 |
| `password` | ✅ | 密码 |

## 示例

```json
{
  "systems": {
    "default": {
      "url": "https://zentao.example.com",
      "username": "lizhe",
      "password": "xxxx"
    }
  }
}
```