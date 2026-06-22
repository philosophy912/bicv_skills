---
name: mysql
description: MySQL 数据库操作技能，支持 INSERT、UPDATE、SELECT 操作及多 MySQL 实例切换。注意：此技能仅允许 INSERT、UPDATE、SELECT 操作，严格禁止 DELETE、DROP、TRUNCATE、ALTER、CREATE 等危险操作。
---

# MySQL Skill

> **平台提示：** Windows 用户请将命令中的 `python3` 替换为 `python`，`pip3` 替换为 `pip`。

## 首次使用：配置引导

首次使用本技能时，先检查配置文件 `~/.bicv/database.json` 是否存在。

**若配置不存在**，使用 AskUserQuestion 引导用户完成配置，生成 `~/.bicv/database.json`：

1. 询问 MySQL 主机地址（示例：`10.0.0.1`）
2. 询问 MySQL 端口（默认 3306）
3. 询问默认数据库名
4. 询问 MySQL 用户名
5. 询问 MySQL 密码

```json
{
  "default_system": "default",
  "systems": {
    "default": {
      "host": "<主机地址>",
      "port": 3306,
      "database": "<数据库名>",
      "username": "<用户名>",
      "password": "<密码>"
    }
  }
}
```

> 密码保存到本地配置文件，不会上传到代码仓库。

## Overview

提供 MySQL 数据库的 INSERT、UPDATE、SELECT 操作能力。支持通过 `~/.bicv/database.json` 配置多个 MySQL 服务器实例，通过 `--system` 参数在实例间切换。所有凭证不硬编码。

## When to Use This Skill

- 查询 MySQL 数据库中的数据
- 向数据库插入新记录
- 更新现有数据
- 在不同 MySQL 服务器实例间切换操作

## Prerequisites

安装依赖库：

```bash
pip3 install -r scripts/requirements.txt
```

## 连接配置

连接配置仅通过 `~/.bicv/database.json` 文件管理，不支持环境变量方式。

### 配置文件（支持多实例）

创建 `~/.bicv/database.json`：

```json
{
  "default_system": "dev",
  "systems": {
    "dev": {
      "host": "10.0.0.1",
      "port": 3306,
      "database": "dev_db",
      "username": "dev_user",
      "password": "dev_pass"
    },
    "prod-ro": {
      "host": "10.0.0.2",
      "port": 3306,
      "database": "prod_db",
      "username": "readonly",
      "password": "readonly_pass"
    }
  }
}
```

配置加载优先级：

1. `--system` CLI 参数 → 匹配 `~/.bicv/database.json` 中的指定系统
2. `~/.bicv/database.json` 中的 `default_system`

使用 `--system` 切换实例：

```bash
python3 scripts/mysql_query.py select "SELECT 1" --system dev
python3 scripts/mysql_query.py select "SELECT COUNT(*) FROM orders" --system prod-ro
```

## Operations

### SELECT - 查询数据

```bash
python3 scripts/mysql_query.py select "SELECT * FROM users LIMIT 10"
python3 scripts/mysql_query.py select "SELECT id, name, email FROM users WHERE status = 'active'"
python3 scripts/mysql_query.py select @queries/get_users.sql
python3 scripts/mysql_query.py select "SELECT * FROM users" --system prod-ro
```

### INSERT - 插入数据

```bash
python3 scripts/mysql_query.py insert "INSERT INTO orders (user_id, total_amount) VALUES (1, 99.99)"
python3 scripts/mysql_query.py insert "INSERT INTO products (name, price) VALUES ('Widget', 29.99), ('Gadget', 49.99)"
```

### UPDATE - 更新数据

```bash
# 必须带 WHERE 条件
python3 scripts/mysql_query.py update "UPDATE users SET email = 'new@example.com' WHERE id = 1"
python3 scripts/mysql_query.py update @queries/update_status.sql
```

### Cross-Database Query

```bash
python3 scripts/mysql_query.py select "SELECT * FROM other_db.users LIMIT 5" -d other_database
```

## Security Restrictions

强制执行以下安全限制：

| 允许的操作 | 禁止的操作 |
|-----------|-----------|
| SELECT | DELETE |
| INSERT | DROP |
| UPDATE | TRUNCATE |
| | ALTER |
| | CREATE |
| | GRANT |
| | REVOKE |
| | SHOW |
| | DESCRIBE |

禁止操作会被脚本直接拒绝并返回错误。

## Scripts

### scripts/mysql_query.py

主脚本，支持所有允许的 SQL 操作：

```bash
python3 scripts/mysql_query.py <select|insert|update> <sql_or_file> [-d DATABASE] [--system NAME]
```

特性：
- 从 `~/.bicv/database.json` 读取数据库连接信息
- 支持多个 MySQL 服务器实例（通过 `--system` 切换）
- 支持直接 SQL 或 `@file` 引用
- SELECT 结果格式化输出（带表头和行数）
- 自动阻止危险操作（DELETE/DROP/TRUNCATE/ALTER/CREATE）
- 支持跨数据库查询（`-d` 参数覆盖默认数据库）

详细示例和最佳实践参考：`references/usage_guide.md`

配置文件 `~/.bicv/database.json` 的字段说明：`references/config-schema.md`
