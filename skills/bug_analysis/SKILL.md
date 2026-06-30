---
name: bug_analysis
description: |
  分析测试组（配置的用户列表）在指定时间段内的缺陷提交、严重缺陷、跟踪及时性、
  以及本周关闭情况，最终渲染成图文 HTML 邮件周报发出。支持禅道（zentao_bug）
  和 Redmine（redmine_issue）双系统，数据从 ticket 库直查。
  四个子命令：submissions（提交+本周严重+零提交）、severe（全库未关闭严重）、
  overdue（跟踪不及时，固定 7 天阈值）、closures（本周关闭）。
  当用户要「出本周缺陷周报」「看测试组提了多少 bug、哪些严重、谁跟踪不及时」并
  「发邮件」时使用。
---

# Bug 分析（周报 → 邮件）

本技能从 `ticket` 数据库直查禅道（`zentao_bug`）和 Redmine（`redmine_issue`）的缺陷数据，
覆盖五块信息，最终产出图文 HTML 邮件周报（图 base64 内嵌，web 邮箱打开即看）。

## 五块信息

1. **本周提交情况** — 本组提交数，按人/项目（数量+占比）+ **零提交点名**。
2. **严重-本周**（C-a）— 本周本组提交的严重缺陷（禅道 `severity∈severe_severities` / Redmine `priority_name∈severe_priorities`）。
3. **严重-本组未关闭**（C-b）— 本组提交的、当前未关闭的严重缺陷（禅道 `severity=1` / Redmine `priority_name` 以 `-A` 结尾）。
4. **跟踪不及时**（overdue）— 当前指派给本组、超过 7 天无 action 的缺陷，纯表格（给人对质）。阈值 **固定 7 天，不入配置**。
5. **本周关闭** — 本组本周关闭的缺陷（禅道 `closedBy` / Redmine journal 关闭人）。

## 核心约定

- **双系统**：禅道（instance_id=1）和 Redmine（instance_id=2）各自独立用户组，分别查询后合并。
- **严重判定硬编码**（DB 实证）：禅道 `severity = 1`（数字 1-4，1=最严重），Redmine `priority_name` 以 `-A` 结尾（形如「立刻-A」，最高级）。不进配置。
- **未关闭口径**：禅道 `status != '已关闭'`，Redmine `status_name != '已关闭'`（含 active + resolved，不窄到 active）。报告措辞用「未关闭」。
- **僵尸项目过滤**（四块全套）：先排 DB `project.is_active=0`，再排配置黑名单 `ignored_projects`。
- **时间窗口**：agent 从用户 prompt 解析（「上周」「6/1~6/25」），通过 `--since`/`--until` 传入；未指定默认近 7 天。提交/严重-本周/关闭按时间字段框；overdue、严重-全库未关闭是当前快照（不框窗口）。
- **依赖**：`scripts/bug_analysis.py`（DB 查询，复用 `~/.bicv/mysql.json`）、`scripts/render_charts.py`（PNG，依赖 matplotlib）、`scripts/render_email.py`（HTML，图 base64 内嵌）。发邮件用全局 `email` skill 的 `email_api.py`。

## 配置

- MySQL 连接：`~/.bicv/mysql.json`（含 `ticket` 系统）
- 分析配置：`~/.bicv/bug_analysis.json`（zentao/redmine 的 users / ignored_projects；recipients 邮件列表）
- 输出目录：`~/.bicv/common.json`（output_root + skills 子目录映射）
- 发件邮箱：`~/.bicv/email.json`（SMTP 凭据，email skill 用）

配置引导详见 [references/config.md](references/config.md)。

## References 路由

| 需要了解 | 读 |
|---|---|
| 四个子命令用法和 JSON 信封 | [references/commands.md](references/commands.md) |
| 图片渲染（render_charts.py，4 张图）| [references/charts.md](references/charts.md) |
| HTML 邮件（render_email.py，五块）| [references/report.md](references/report.md) |
| 首次使用配置引导 | [references/config.md](references/config.md) |
| 配置文件 schema 定义 | [references/config-schema.md](references/config-schema.md) |

## Agent 编排流程（产出周报邮件）

脚本只提供原子数据查询 + 渲染，**报告措辞/收件人/发送由 agent 编排**。典型流程：

1. agent 从用户 prompt 解析时间窗口（如「上周」→ since/until）。
2. `bug_analysis.py submissions --since ... --until ...` → `sub.json`（提交 + 本周严重 + 零提交）。
3. `bug_analysis.py severe` → `sev.json`（全库未关闭严重）。
4. `bug_analysis.py overdue` → `ovd.json`（跟踪不及时）。
5. `bug_analysis.py closures --since ... --until ...` → `cls.json`（本周关闭）。
6. `render_charts.py --submissions sub.json --closures cls.json` → `charts.json`（+ PNG 图）。
7. `render_email.py --submissions sub.json --overdue ovd.json --severe sev.json --closures cls.json --charts charts.json` → `email_<日期>.html`（自包含，图已 base64 内嵌）。
8. 从 `~/.bicv/bug_analysis.json` 读 `recipients.to`，调 email skill 发送：

```bash
python3 ~/.claude/skills/email/scripts/email_api.py send \
  --to <to> \
  --subject "缺陷分析周报 <日期>" \
  --body @<email_日期.html> \
  --html \
  --system <email.json 里的实例名>
```

> 图用 base64 内嵌，QQ/网易/Gmail web 邮箱打开即看。Outlook 桌面版可能屏蔽 data URI 图，若需最强兼容可后续改走 email skill 的 CID related 内嵌。

## 禁止

- 不绕过 mysql skill 或本脚本直接发 SQL 到 ticket 库；所有查询走 `bug_analysis.py`。
- 不在 agent 对话中现场发明 SQL 模板——查询逻辑已封装在脚本内。
