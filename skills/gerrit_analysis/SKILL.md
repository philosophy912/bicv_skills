---
name: gerrit_analysis
description: |
  分析配置的用户列表在指定时间段内提交并入库（status:merged）的代码情况：按人统计 merged change
  数、patch set 数、增删行数、创建到入库时长、review 评论数与被打回次数，并做 **AI 评审前置合规
  检查**（Code-Review +2 必须晚于 AI 评审结论，违规逐一列举），最后给出每个 change 的明细清单。
  当用户要「看近期团队入库了哪些代码」「统计某段时间内 merged 的 change」
  「分析入库代码量、review 效率，或 +2 是否抢在 AI 评审之前」时使用。
---

# Gerrit 入库代码分析

## 核心约定

- **分析对象**：`~/.bicv/gerrit_analysis.json` 里 `users` 列出的 Gerrit 账号**邮箱**。
- **入库定义**：`status:merged`（不统计 open / abandoned）。
- **时间窗口**：用户 prompt 给定时间段；未给则默认滚动 24 小时（now-24h 到 now）。
  详见 [references/time-window.md](references/time-window.md)。
- **AI 评审前置合规**：每个 merged change 若出现 Code-Review +2，该 +2 的时间点必须晚于 AI 评审结论，
  否则算违规。详见 [references/pipeline.md](references/pipeline.md) 阶段 3。
- **依赖**：全部 Gerrit 调用走 gerrit-restapi skill 的 `scripts/gerrit_api.py`。本 skill 不含脚本。

## 配置

- 认证：`~/.bicv/gerrit.json`（复用 gerrit-restapi）
- 分析对象与规则：`~/.bicv/gerrit_analysis.json`
- 输出位置：`~/.bicv/common.json`

配置详情见 [references/config.md](references/config.md)。

## References 路由

| 需要了解 | 读 |
|---|---|
| 四阶段 pipeline（collect → fetch → analyze → report）| [references/pipeline.md](references/pipeline.md) |
| 时间窗口解析约定 | [references/time-window.md](references/time-window.md) |
| 配置字段和 schema | [references/config.md](references/config.md) |

## 默认执行

用户不指定阶段时，一气呵成跑 collect → fetch → analyze → report。用户显式说「只跑某阶段」时，基于
运行目录里已有产物重跑该阶段。

## 前置检查

1. gerrit-restapi skill 已安装，`gerrit_api.py` 可用且支持 `query-changes --json --option`。
2. `~/.bicv/gerrit.json` 存在且配置了目标 Gerrit。
3. `~/.bicv/gerrit_analysis.json` 存在且 `users` 非空。不存在则用 AskUserQuestion 收集。
4. 确认/创建 `~/.bicv/common.json`。

## 禁止

- 不绕过 gerrit-restapi skill 直接发 HTTP 请求；所有 Gerrit 调用走 `gerrit_api.py`。
- 不在本 skill 内复制 gerrit 调用代码。
- 指标计算与合规判定的主体逻辑见 [references/pipeline.md](references/pipeline.md) 阶段 3。
