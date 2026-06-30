# Bug 分析 — 子命令与输出格式

四个子命令，每个输出 JSON 信封到 stdout，由 agent 编排组合 + 渲染。

## `submissions` — 窗口内用户组提交的缺陷（含本周严重 + 零提交）

```bash
python3 scripts/bug_analysis.py submissions --since "2026-06-19" --until "2026-06-26"
python3 scripts/bug_analysis.py submissions --since "2026-06-19"  # until 默认当前时间
python3 scripts/bug_analysis.py submissions                      # 默认近 7 天
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
    "bugs": [...],
    "severe": {"total": 3, "bugs": [...]},
    "zero_submission_users": ["彭许芳-CQD-SW"]
  },
  "redmine": {
    "instance_id": 2,
    "total": 10,
    "by_user": {...}, "by_project": {...},
    "issues": [...],
    "severe": {"total": 1, "issues": [...]},
    "zero_submission_users": []
  }
}
```

- `severe`：本周提交里命中严重判定（禅道 `severity=1` / Redmine `priority_name` 以 `-A` 结尾）的子集（C-a）。
- `zero_submission_users`：配置 `users` 中本周零提交的人（不区分角色，名单即应提交者）。

## `severe` — 本组提交的未关闭严重缺陷（C-b）

```bash
python3 scripts/bug_analysis.py severe
```

本组提交的、当前未关闭的严重缺陷（`openedBy`/`author_name` ∈ 用户组 + 未关闭 + 严重）。严重判定硬编码：禅道 `status != '已关闭'` + `severity = 1`，Redmine `status_name != '已关闭'` + `priority_name LIKE '%-A'`。

```json
{
  "generated_at": "2026-06-26 10:00:00",
  "zentao": {"instance_id": 1, "total": 5, "bugs": [...]},
  "redmine": {"instance_id": 2, "total": 2, "issues": [...]}
}
```

## `overdue` — 当前超期未处理（跟踪不及时）

```bash
python3 scripts/bug_analysis.py overdue
```

阈值**固定 7 天**（不入配置）。指派给本组后用户组全程无 action、距今 >7 天。

```json
{
  "generated_at": "2026-06-26 10:00:00",
  "overdue_days": 7,
  "zentao": {
    "instance_id": 1, "total": 5,
    "by_user": {"周少波-NJD-SW": 3},
    "bugs": [{"id": 12345, "projectName": "B30X-F09", "module": "carlink",
              "assignedTo": "周少波-NJD-SW", "days_since_action": 16}]
  },
  "redmine": {...}
}
```

## `closures` — 窗口内用户组关闭的缺陷

```bash
python3 scripts/bug_analysis.py closures --since "2026-06-19" --until "2026-06-26"
python3 scripts/bug_analysis.py closures                      # 默认近 7 天
```

本组关的：禅道 `closedBy ∈ users` + `closedDate` 在窗口；Redmine 取把 `status` 改成「已关闭」那条 journal 的 `user_name`（`created_on` 在窗口）。

```json
{
  "window": {"start": "...", "end": "..."},
  "zentao": {"instance_id": 1, "total": 8, "by_user": {...}, "by_project": {...}, "bugs": [...]},
  "redmine": {"instance_id": 2, "total": 3, "by_user": {...}, "by_project": {...}, "issues": [...]}
}
```
