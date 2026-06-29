# Bug 分析 — 子命令与输出格式

## `submissions` — 窗口内用户组提交的缺陷

```bash
python3 scripts/bug_analysis.py submissions --since "2026-06-19" --until "2026-06-26"
python3 scripts/bug_analysis.py submissions --since "2026-06-19"  # until 默认当前时间
python3 scripts/bug_analysis.py submissions  # 默认近 7 天
```

输出 JSON 信封：
```json
{
  "window": {"start": "2026-06-19 00:00:00", "end": "2026-06-26 23:59:59"},
  "zentao": {
    "instance_id": 1,
    "total": 42,
    "by_user": {"周少波-NJD-SW": 25, "刘洁-NJD-SW": 17},
    "by_project": {"B30X-F09": 20, "N53TB": 22},
    "bugs": [...]
  },
  "redmine": {
    "instance_id": 2,
    "total": 10,
    "by_user": {...},
    "by_project": {...},
    "issues": [...]
  }
}
```

## `overdue` — 当前超期未处理的缺陷

```bash
python3 scripts/bug_analysis.py overdue
```

输出 JSON 信封：
```json
{
  "generated_at": "2026-06-26 10:00:00",
  "overdue_days": 7,
  "zentao": {
    "instance_id": 1,
    "total": 5,
    "by_user": {"周少波-NJD-SW": 3, "刘洁-NJD-SW": 2},
    "bugs": [
      {
        "id": 12345,
        "projectName": "B30X-F09",
        "module": "carlink",
        "assignedTo": "周少波-NJD-SW",
        "last_user_action": "2026-06-10 08:00:00",
        "days_since_action": 16
      }
    ]
  },
  "redmine": {...}
}
```
