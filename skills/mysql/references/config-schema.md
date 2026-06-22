# mysql 配置

配置文件位置和顶层结构见 [config 规范](../../../docs/config-spec.md)。本文件仅说明本 skill 特有的字段。

## config_name

`mysql.json`，即 `~/.bicv/mysql.json`。

## 字段

| 字段 | 必填 | 说明 |
|---|---|---|
| `host` | ✅ | MySQL 主机 |
| `port` | — | 端口，默认 `3306` |
| `username` | ✅ | 用户名 |
| `password` | — | 密码 |
| `database` | — | 默认数据库（CLI 可用 `-d` 覆盖） |

## 示例

```json
{
  "systems": {
    "default": {
      "host": "127.0.0.1",
      "port": 3306,
      "username": "root",
      "password": "xxxx",
      "database": "app"
    }
  }
}
```