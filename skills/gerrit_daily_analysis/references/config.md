# Gerrit 每日分析 — 配置详情

## 1. 认证（~/.bicv/gerrit.json，复用 gerrit-restapi）

复用 gerrit-restapi 的配置，字段见 gerrit-restapi 的 `references/config-schema.md`。多实例用
`--system <name>` 切换，本 skill 透传该参数给所有 gerrit 子命令。

## 2. 分析对象与规则（~/.bicv/gerrit_daily_analysis.json）

```json
{
  "users": ["lizhe@bicv.com", "zhangsan@bicv.com"],
  "ignore_projects": [],
  "ai_review": {
    "keywords": ["AI评审意见", "风险等级L1"],
    "vote_tag": "AI"
  }
}
```

- `users`（**必填**）：要分析的 owner **邮箱**列表。每个邮箱直接拼到 `owner:` 谓词后
  （如 `owner:lizhe@bicv.com`）。collect 阶段对每个邮箱各发一次查询。邮箱必须是该账号在 Gerrit
  注册的邮箱（primary 或 secondary），否则查不到；同一人有多个注册邮箱时需都列出。
- `ignore_projects`（选填，缺省 `[]`）：要**完全忽略**的 project 名（精确匹配）。这些 project 的
  change 不纳入任何统计，归为 `ignored`。collect 仍会收集（保留数据完整性），仅 analyze 阶段忽略
  ——因此改配置后只需重跑 analyze，不必重新 collect。
- `ai_review`（选填，控制 AI 评审识别，整段缺省时用下列默认值）：
  - `keywords`：message 文本**含任一关键词**即判定为 AI 评审评论。默认
    `["AI评审意见", "风险等级L1"]`，取自 bicv AI 评审 message 的稳定开头「AI评审意见如下（风险
    等级L1~L5）」。
  - `vote_tag`：label 投票的 `tag` 字段**等于该值**即判定为 AI 评审投票，默认 `"AI"`。
  - 两条**任一命中**即视为该 change 存在 AI 评审。
- 配置文件不存在或 `users` 为空 → 提示用户创建（用 AskUserQuestion 收集 users 列表）。

## 3. 输出位置（~/.bicv/common.json）

```json
{
  "output_root": "~/.bicv/output",
  "skills": {
    "gerrit_daily_analysis": "gerrit_daily_analysis"
  }
}
```

- `output_root` 缺省 `~/.bicv/output`；`skills.gerrit_daily_analysis` 缺省 `gerrit_daily_analysis`。
- 每次运行落到 `<output_root>/<skills.gerrit_daily_analysis>/<本地时间戳>/`。
- 若 `~/.bicv/common.json` 不存在，先按缺省值创建目录并在开始时提示用户。
