---
name: bug_daily_analysis
description: |
  分析测试组（配置的用户列表）在指定时间段内提交的缺陷、以及当前超期未处理的缺陷。
  支持禅道（zentao_bug）和 Redmine（redmine_issue）双系统，数据从数据库 ticket 库直查。
  两个子命令：submissions（窗口内提交情况）和 overdue（当前超期：指派 >7 天且用户组无任何 action）。
  当用户要「看测试组上周提了多少 bug」「检查有没有超期未处理的缺陷」时使用。
---

# Bug 每日分析

本技能从 `ticket` 数据库直查禅道（`zentao_bug`）和 Redmine（`redmine_issue`）的缺陷数据，
按配置的用户组统计提交情况和超期跟踪情况。

## 核心约定

- **双系统**：禅道（instance_id=1）和 Redmine（instance_id=2）各自独立用户组，分别查询后合并报告。
- **提交情况**：窗口内 `openedBy`（禅道）/ `author_name`（Redmine）命中用户组的缺陷。
- **超期判定（当前型）**：缺陷当前指派给用户组成员，且用户组**最后一条 action（含评论）距今 > overdue_days 天**；用户组曾碰过就不算（既往不咎）。
  - 禅道 action 取 `zentao_bug_action`（`actor`/`date`）；Redmine 取 `redmine_issue_journal`（`user_name`/`created_on`）。
  - 无用户组 action 时，用缺陷创建时间作 fallback。
- **时间窗口**：由 agent 从用户 prompt 解析（如「上周」「6/1~6/25」），通过 `--since`/`--until` 传入脚本；未指定时默认近 7 天。
- **依赖**：查询脚本 `scripts/bug_analysis.py`（DB 连接复用 `~/.bicv/mysql.json`，system=ticket）；渲染脚本 `scripts/render_charts.py`（依赖 matplotlib，吃 JSON 出 PNG，输出目录走 `~/.bicv/common.json`）。

## 首次使用：配置引导

### 1. 确认 mysql skill 已安装

本 skill 依赖 `mysql-connector-python`。确认能运行：
```bash
python3 skills/mysql/scripts/mysql_query.py select "SELECT 1" --system ticket
```

### 2. 创建分析配置文件

若 `~/.bicv/bug_daily_analysis.json` 不存在，使用 AskUserQuestion 引导用户创建：

**询问：** 禅道测试组成员的姓名列表（逗号分隔）、Redmine 测试组成员的姓名列表（逗号分隔）、超期天数（默认 7）。

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

### 3. 确认 MySQL 连接

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

### 4. 确认输出目录

渲染脚本 `render_charts.py` 的图片默认输出到 `~/.bicv/common.json` 配置的目录（与 gerrit/jenkins daily_analysis 共用同一份配置）。规则：

- **`output_root`**（必填）：所有 skill 的输出根目录。
- **`skills` 映射**（可选）：`skills["bug_daily_analysis"]` 指定本 skill 的子目录名；**未配置时默认回退到 `"bug_daily_analysis"`**。
- 实际输出路径 = `output_root / <子目录>/`，脚本会自动创建。
- `render_charts.py --out <dir>` 可临时覆盖（优先级最高）。

示例 `~/.bicv/common.json`：

```json
{
  "output_root": "/path/to/output",
  "skills": {
    "bug_daily_analysis": "bug_daily_analysis"
  }
}
```

## 子命令

### `submissions` — 窗口内用户组提交的缺陷

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

### `overdue` — 当前超期未处理的缺陷

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

## 图片渲染（render_charts.py）

把 `bug_analysis.py` 的 JSON 输出渲染成 PNG 图表，**只吃 JSON、不连库**，职责与查询脚本分离。

### 用法

```bash
# 先把两个子命令的输出存成文件
python3 scripts/bug_analysis.py submissions --since 2026-06-22 --until 2026-06-26 > sub.json
python3 scripts/bug_analysis.py overdue > ovd.json

# 渲染成图片（可只传其中一个）
python3 scripts/render_charts.py --submissions sub.json --overdue ovd.json
python3 scripts/render_charts.py --submissions sub.json --out /some/dir
```

### 产出

- **4 类图**（按数据有无按需生成；禅道 + Redmine 合并统计）：
  - `submissions_by_user` / `submissions_by_project`：横向条形图，按数降序，最多者居顶。
  - `overdue_by_user`：超期按指派人计数（横向条形图）。
  - `overdue_detail`：超期明细表格图（项目 / 模块 / 指派人 / 超期天数，按天数降序）。
- **不截断**：条形图超 25 条、表格超 30 行自动 **分页** 成多张（`_p1/_p2…`），数据一条不丢。
- **输出目录**：默认 `~/.bicv/common.json` 的 `output_root/bug_daily_analysis`（可在 `common.json` 的 `skills` 里映射别名）；`--out` 可覆盖。
- 返回 JSON 信封：`{"generated_at", "output_dir", "charts": {<板块>: [<png 路径>…]}}`。

### 中文字体

优先探测系统已装 CJK 字体（PingFang / Noto / 思源 / 雅黑 / SimHei …）；全找不到时回退到 `assets/fonts/` 下的字体文件（见该目录 README）；再找不到则报错指引，不静默出豆腐块。仓库默认不内置字体二进制。

## agent 编排流程

脚本只提供原子数据查询（JSON 输出），**报告措辞和汇总由 agent 完成**。

典型流程：
1. agent 从用户 prompt 解析时间窗口（如「上周」→ since/until）。
2. 调 `submissions --since ... --until ...`，stdout 存为 `sub.json`。
3. 调 `overdue`，stdout 存为 `ovd.json`。
4. 调 `render_charts.py --submissions sub.json --overdue ovd.json` 生成 PNG（见上「图片渲染」）。
5. 读两份 JSON + 图片清单，汇总成终端 Markdown 报告 + 落盘 `report.md`（可内嵌图片路径）。
6. 报表重点：按人/按项目汇总提交数；超期明细逐一列出（模块、指派人、天数）。

## 禁止

- 不绕过 mysql skill 或本脚本直接发 SQL 到 ticket 库；所有查询走 `bug_analysis.py`。
- 不在 agent 对话中现场发明 SQL 模板——查询逻辑已封装在脚本内。
