# Bug 分析 — 配置引导

## 1. MySQL 连接

依赖 mysql skill，确认能运行：
```bash
python3 skills/mysql/scripts/mysql_query.py select "SELECT 1" --system ticket
```

`~/.bicv/mysql.json` 需包含 `ticket` 系统：
```json
{
  "systems": {
    "ticket": {
      "host": "<host>",
      "port": 9999,
      "database": "ticket",
      "username": "<username>",
      "password": "<password>"
    }
  }
}
```

## 2. 分析配置文件（~/.bicv/bug_analysis.json）

```json
{
  "overdue_days": 7,
  "zentao": {
    "instance_id": 1,
    "users": ["周少波-NJD-SW", "刘洁-NJD-SW"]
  },
  "redmine": {
    "instance_id": 2,
    "users": ["夏思平_LM", "莫晓宇_FCE"]
  }
}
```

> `users` 里的姓名必须和数据库里 `openedBy` / `assignedTo`（禅道）或 `author_name` / `assigned_to_name`（Redmine）的实际存储格式**完全一致**（精确匹配）。配什么查什么，不做模糊匹配。

## 3. 输出目录（~/.bicv/common.json）

```json
{
  "output_root": "/path/to/output",
  "skills": {
    "bug_analysis": "bug_analysis"
  }
}
```

- `output_root`（必填）：所有 skill 的输出根目录。
- `skills["bug_analysis"]`（可选）：指定本 skill 的子目录名；未配置时默认回退到 `"bug_analysis"`。
- 实际输出路径 = `output_root / <子目录>/`，脚本会自动创建。
- `render_charts.py --out <dir>` 可临时覆盖（优先级最高）。
