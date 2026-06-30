# bug_analysis 配置说明

## 配置文件

`~/.bicv/bug_analysis.json`

## 字段

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `zentao` | object | 是 | 禅道系统配置 |
| `zentao.instance_id` | int | 是 | ticket 库 instance 表的禅道实例 ID（当前为 1） |
| `zentao.users` | list[str] | 是 | 禅道测试组成员姓名列表，格式与 `zentao_bug.openedBy`/`assignedTo`/`closedBy` 完全一致 |
| `zentao.ignored_projects` | list[str] | 否 | 禅道僵尸项目黑名单（`projectName` 原样值） |
| `redmine` | object | 是 | Redmine 系统配置 |
| `redmine.instance_id` | int | 是 | Redmine 实例 ID（当前为 2） |
| `redmine.users` | list[str] | 是 | Redmine 成员姓名列表，格式与 `author_name`/`assigned_to_name` 一致 |
| `redmine.ignored_projects` | list[str] | 否 | Redmine 僵尸项目黑名单 |
| `recipients` | object | 否 | 邮件收件人（agent 发周报时读） |
| `recipients.to` | list[str] | 否 | 收件人邮箱列表 |

> **严重判定不进配置**（DB 实证后硬编码）：禅道 `severity = 1`（DB 存数字 1-4，1=最严重），Redmine `priority_name LIKE '%-A'`（形如「立刻-A」，A 后缀=最高级）。
>
> **`overdue_days` 固定常量 7**（不入配置）；配置里残留该字段会被忽略。
>
> **僵尸项目过滤**（四块查询全套）= DB `project.is_active=0` 自动排除 **+** `ignored_projects` 黑名单手动补充。未收录在 `project` 表或不在黑名单的项目按在研保留。

## 示例

```json
{
  "zentao": {
    "instance_id": 1,
    "users": ["周少波-NJD-SW", "刘洁-NJD-SW", "彭许芳-CQD-SW"],
    "ignored_projects": []
  },
  "redmine": {
    "instance_id": 2,
    "users": ["夏思平_LM", "莫晓宇_FCE"],
    "ignored_projects": []
  },
  "recipients": {
    "to": ["lizhe@bicv.com"]
  }
}
```

## 姓名来源

- **禅道**：`zentao_bug.openedBy` / `assignedTo` / `closedBy` 字段实际值。格式通常为「姓名-地域-职能」（如「周少波-NJD-SW」）或「公司-姓名」。
- **Redmine**：`redmine_issue.author_name` / `assigned_to_name` 字段实际值。格式不一：纯姓名、`姓名_职能`（如「夏思平_LM」）、`姓名--chery` 等。

> 配置里的 users 直接跟 DB 字段值匹配，不 join 用户表。
