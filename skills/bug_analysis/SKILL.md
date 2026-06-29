---
name: bug_analysis
description: |
  分析测试组（配置的用户列表）在指定时间段内提交的缺陷、以及当前超期未处理的缺陷。
  支持禅道（zentao_bug）和 Redmine（redmine_issue）双系统，数据从数据库 ticket 库直查。
  两个子命令：submissions（窗口内提交情况）和 overdue（当前超期：指派 >7 天且用户组无任何 action）。
  当用户要「看测试组上周提了多少 bug」「检查有没有超期未处理的缺陷」时使用。
---

# Bug 分析

本技能从 `ticket` 数据库直查禅道（`zentao_bug`）和 Redmine（`redmine_issue`）的缺陷数据，
按配置的用户组统计提交情况和超期跟踪情况。

## 核心约定

- **双系统**：禅道（instance_id=1）和 Redmine（instance_id=2）各自独立用户组，分别查询后合并报告。
- **提交情况**：窗口内 `openedBy`（禅道）/ `author_name`（Redmine）命中用户组的缺陷。
- **超期判定**：缺陷当前指派给用户组成员，且用户组最后一条 action 距今 > `overdue_days` 天。
- **停用项目过滤（仅 overdue）**：排除 `project` 表中 `is_active=0` 的停用项目。submissions 不过滤。
- **时间窗口**：由 agent 从用户 prompt 解析，通过 `--since`/`--until` 传入脚本；未指定时默认近 7 天。
- **依赖**：查询脚本 `scripts/bug_analysis.py`（DB 连接复用 `~/.bicv/mysql.json`）；渲染脚本 `scripts/render_charts.py`（依赖 matplotlib）和 `scripts/render_report.py`。

## 配置

- MySQL 连接：`~/.bicv/mysql.json`（含 `ticket` 系统）
- 分析配置：`~/.bicv/bug_analysis.json`（overdue_days / zentao.users / redmine.users）
- 输出目录：`~/.bicv/common.json`

配置引导详见 [references/config.md](references/config.md)。

## References 路由

| 需要了解 | 读 |
|---|---|
| 子命令 `submissions` / `overdue` 用法和 JSON 信封 | [references/commands.md](references/commands.md) |
| 图片渲染（render_charts.py）| [references/charts.md](references/charts.md) |
| Markdown 报告（render_report.py）| [references/report.md](references/report.md) |
| 首次使用配置引导 + 所有 schema | [references/config.md](references/config.md) |
| 配置文件 schema 定义 | [references/config-schema.md](references/config-schema.md) |

## Agent 编排流程

脚本只提供原子数据查询（JSON 输出），**报告措辞和汇总由 agent 完成**。典型流程：

1. agent 从用户 prompt 解析时间窗口（如「上周」→ since/until）。
2. 调 `submissions --since ... --until ...`，stdout 存为 `sub.json`。
3. 调 `overdue`，stdout 存为 `ovd.json`。
4. 调 `render_charts.py --submissions sub.json --overdue ovd.json` 生成 PNG。
5. 调 `render_report.py --submissions sub.json --overdue ovd.json` 生成 Markdown 表格报告。
6. 读两份 JSON + 图片/报告路径，在终端给用户汇总。
7. 报表重点：按人/按项目汇总提交数；超期明细逐一列出（缺陷ID、模块、指派人、天数）。

## 禁止

- 不绕过 mysql skill 或本脚本直接发 SQL 到 ticket 库；所有查询走 `bug_analysis.py`。
- 不在 agent 对话中现场发明 SQL 模板——查询逻辑已封装在脚本内。
