# MySQL Quick Reference

## Connection Configuration

连接配置仅通过 `~/.bicv/mysql.json` 文件管理，不支持环境变量方式。

配置加载优先级：

1. `--system` CLI 参数 → 匹配 `~/.bicv/mysql.json` 中的指定系统
2. `~/.bicv/mysql.json` 中的 `default_system`

创建 `~/.bicv/mysql.json` 管理多个 MySQL 服务器：

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

## Multi-Instance Switching

```bash
# 使用默认系统 (default_system)
python3 scripts/mysql_query.py select "SELECT 1"

# 切换到指定系统
python3 scripts/mysql_query.py select "SELECT 1" --system prod-ro
python3 scripts/mysql_query.py select "SELECT COUNT(*) FROM orders" --system dev
```

## SQL File Format

创建 `.sql` 文件存储复杂查询：

```sql
-- queries/get_user_orders.sql
SELECT
    o.id,
    o.order_date,
    o.total_amount,
    u.name as customer_name
FROM orders o
JOIN users u ON o.user_id = u.id
WHERE o.user_id = 1
ORDER BY o.order_date DESC
LIMIT 20;
```

## SELECT Examples

```bash
# 基本查询
python3 scripts/mysql_query.py select "SELECT * FROM users WHERE id = 1"

# 多条件查询
python3 scripts/mysql_query.py select "SELECT id, name, email FROM users WHERE status = 'active' ORDER BY created_at DESC LIMIT 10"

# JOIN 查询
python3 scripts/mysql_query.py select "SELECT o.id, u.name, o.total_amount FROM orders o JOIN users u ON o.user_id = u.id"

# 聚合查询
python3 scripts/mysql_query.py select "SELECT COUNT(*), status FROM orders GROUP BY status"

# 使用 SQL 文件
python3 scripts/mysql_query.py select @queries/get_users.sql

# 查询指定 MySQL 实例
python3 scripts/mysql_query.py select "SELECT * FROM users LIMIT 5" --system prod-ro
```

## INSERT Examples

```bash
# 单条插入
python3 scripts/mysql_query.py insert "INSERT INTO users (name, email) VALUES ('John', 'john@example.com')"

# 批量插入
python3 scripts/mysql_query.py insert "INSERT INTO products (name, price) VALUES ('Widget', 29.99), ('Gadget', 49.99)"

# 从文件插入
python3 scripts/mysql_query.py insert @queries/insert_order.sql
```

## UPDATE Examples

```bash
# 更新单条（必须带 WHERE）
python3 scripts/mysql_query.py update "UPDATE users SET email = 'new@example.com' WHERE id = 1"

# 条件更新
python3 scripts/mysql_query.py update "UPDATE users SET status = 'inactive' WHERE last_login < '2024-01-01'"

# 使用文件
python3 scripts/mysql_query.py update @queries/update_status.sql
```

## Cross-Database Operations

```bash
# 查询其他数据库
python3 scripts/mysql_query.py select "SELECT * FROM other_db.users LIMIT 5" -d other_database

# 跨数据库 JOIN（需要权限）
python3 scripts/mysql_query.py select "SELECT a.id, b.name FROM db1.orders a JOIN db2.users b ON a.user_id = b.id"
```

## Security Restrictions

| 允许的操作 | 禁止的操作 |
|-----------|-----------|
| SELECT | DELETE |
| INSERT | DROP |
| UPDATE | TRUNCATE |
| | ALTER |
| | CREATE |
| | GRANT |
| | REVOKE |

**绕过防护的方式均被阻止**，包括：
- SQL 注释：`DELETE /* comment */ FROM users` → 被阻止
- 大小写混用：`DeLeTe FROM users` → 被阻止
- 空格混淆：`DELETE  FROM users` → 被阻止

## Best Practices

1. **UPDATE 必须带 WHERE 条件** — 避免批量更新事故
2. **SELECT 先验证** — 确认返回预期结果后再进行 INSERT/UPDATE
3. **使用 SQL 文件** — 复杂查询存入文件，便于维护和审计
4. **结果集截断** — 大结果集（>10000行）自动截断显示
5. **跨数据库确认** — 使用 `-d` 参数前确认目标数据库存在
6. **多实例隔离** — 通过 `--system` 切换实例，避免连接到错误的环境

## Error Handling

| 错误信息 | 解决方案 |
|---------|---------|
| `Missing required connection parameters` | 检查 `~/.bicv/mysql.json` 配置文件是否存在且格式正确 |
| `Error connecting to MySQL` | 确认 MySQL 服务运行中、防火墙放行、凭证正确 |
| `Access denied` | 检查用户名/密码、数据库权限 |
| `Unknown database` | 确认数据库名存在或使用 `-d` 指定正确数据库 |
| `Operation 'XXX' is not permitted` | 该操作被安全策略阻止，检查 SQL 是否包含禁止关键词 |
