# bug_analysis 配置说明

## 配置文件

`~/.bicv/bug_analysis.json`

## 字段

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `overdue_days` | int | 否 | 超期阈值（天），默认 7。指派后超过此天数无用户组 action 则算超期 |
| `zentao` | object | 是 | 禅道系统配置 |
| `zentao.instance_id` | int | 是 | ticket 库 instance 表的禅道实例 ID（当前为 1） |
| `zentao.users` | list[str] | 是 | 禅道测试组成员姓名列表，格式必须和 `zentao_bug.openedBy` / `assignedTo` 完全一致 |
| `redmine` | object | 是 | Redmine 系统配置 |
| `redmine.instance_id` | int | 是 | ticket 库 instance 表的 Redmine 实例 ID（当前为 2） |
| `redmine.users` | list[str] | 是 | Redmine 测试组成员姓名列表，格式必须和 `redmine_issue.author_name` / `assigned_to_name` 完全一致 |

## 示例

```json
{
  "overdue_days": 7,
  "zentao": {
    "instance_id": 1,
    "users": ["周少波-NJD-SW", "刘洁-NJD-SW", "彭许芳-CQD-SW"]
  },
  "redmine": {
    "instance_id": 2,
    "users": ["夏思平_LM", "莫晓宇_FCE"]
  }
}
```

## 姓名来源

- **禅道**：`zentao_bug.openedBy` / `assignedTo` 字段实际值。格式通常为「姓名-地域-职能」（如「周少波-NJD-SW」）或「公司-姓名」（如「信必优-张鲁震」）。
- **Redmine**：`redmine_issue.author_name` / `assigned_to_name` 字段实际值。格式不一：纯姓名、`姓名_职能`（如「夏思平_LM」）、`姓名--chery` 等。

> 注意：禅道 `zentao_user` 表有 `realname` 字段，但 `bug` 主表的 `openedBy` **不是** realname、而是直接存展示名。配置里的 users 直接跟 `openedBy` / `author_name` 匹配，不需要 join `zentao_user`。
