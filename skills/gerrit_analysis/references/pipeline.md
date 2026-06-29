# Gerrit 分析 — 四阶段 Pipeline

## 运行目录结构

每次运行落到 `<output_root>/<skills.gerrit_analysis>/<本地时间戳>/`，时间戳格式
`YYYY-MM-DD_HHMMSS`（本地时间）。多次运行互不覆盖。

```
<run-dir>/
├── changes.json      # collect 产物（全部用户的 merged change）
├── details/          # fetch 产物，每 change 一个 <_number>.json（labels + messages + revisions）
├── report.json       # analyze 产物（全局汇总 + AI 评审违规列表）
└── report.md         # report 产物（归档）
```

每个阶段都把产物落盘，因此**任意阶段可基于已有产物单独重跑**用于调试：用户说「只跑 analyze」时，
跳过 collect/fetch，直接读现有 `changes.json` / `details/`。

---

## 阶段 1：collect —— 按人收集 merged change

1. 读 `gerrit_analysis.json` 的 `users`、`ignore_projects`。
2. 解析时间窗口：用户 prompt 带时间段 → 换算成 UTC 的 `after:"yyyy-MM-dd HH:mm:ss"` 与
   `before:"yyyy-MM-dd HH:mm:ss"`；没带 → 用 now-24h 到 now（同样换算 UTC）。
3. 对每个 user 调：
   ```bash
   python3 gerrit_api.py query-changes --json \
     --query 'owner:<email> status:merged after:"<start>" before:"<end>"' \
     --limit 500 --option DETAILED_ACCOUNTS \
     [--system <name>]
   ```
   - `--json`：纯 JSON 输出完整 ChangeInfo（含 `_number` / `project` / `branch` / `subject` /
     `status` / `owner` / `created` / `updated` / `insertions` / `deletions`）。
   - `--option DETAILED_ACCOUNTS`：让 `owner` 含 `name` / `email` / `username`，便于展示；拿不到
     （权限不足）则回退用命中的 `owner_query` 值。
   - `--limit 500`：避免截断；若返回结果接近 500，提示用户该 user 可能还有更多 change。
   - **分批并行**：一次并发多个 user 的 `query-changes` 调用（并行 Bash），避免逐个串行太慢。
4. **容错**：单个 user 查询失败（认证、网络、API 报错）**不中断**整体 collect，把失败的 user 记进
   `changes.json` 的 `errors[]` 段（含 user 名与错误原因），继续其它 user。
5. 落盘 `changes.json`：

```json
{
  "generated_at": "2026-06-25T14:30:00",
  "window": {"start": "2026-06-24T14:30:00Z", "end": "2026-06-25T14:30:00Z"},
  "system": "default",
  "changes": [
    {
      "_number": 12345,
      "project": "infra/foo",
      "branch": "master",
      "subject": "feat: add bar",
      "status": "MERGED",
      "owner": {"name": "Li Zhe", "email": "lizhe@bicv.com", "username": "lizhe"},
      "created": "2026-06-20T03:00:00Z",
      "updated": "2026-06-24T18:00:00Z",
      "insertions": 120,
      "deletions": 30,
      "owner_query": "lizhe@bicv.com"
    }
  ],
  "errors": [
    {"user": "zhangsan@bicv.com", "error": "HTTP 401: unauthorized"}
  ]
}
```

> 每个 change 附 `owner_query`：collect 时命中的那个邮箱，用于 analyze 阶段按人归类。

---

## 阶段 2：fetch —— 拉取评审详情

1. 读 `changes.json` 的 `changes[]`。
2. 对每个 change 调（**分批并行**）：
   ```bash
   python3 gerrit_api.py get-change --change-id <_number> \
     --option ALL_REVISIONS --option MESSAGES --option DETAILED_LABELS [--system <name>]
   ```
   写入 `details/<_number>.json`。`get-change` 输出含 `System:` / `变更详情:` 前导行（走
   `print_json_result`），**落盘前剥离前导、只存纯 JSON**（取首个 `{` 起的 JSON 块）。用途：
   - `ALL_REVISIONS`：数 `revisions` 数 = patch set 数。
   - `MESSAGES`：评论时间线，用于 review 评论数 + AI 评审识别（文本含 `ai_review.keywords`）。
   - `DETAILED_LABELS`：`labels.Code-Review.all` 投票历史（含 `value` / `date` / `tag`），用于
     定位 +2 时间点，以及通过 `tag == ai_review.vote_tag` 识别 AI 评审投票。
3. **容错**：单个 change 的拉取失败不中断，在 `changes.json` 对应条目记 `fetch_error`，该条在
   analyze 阶段对应维度标 `unknown`。

> `--change-id` 用 collect 拿到的 `_number`（整数）。Gerrit 端点 `/changes/{change-id}` 接受数字
> change-id，`gerrit_api.py` 的 `encode_change_id` 对纯数字保持原样。

---

## 阶段 3：analyze —— 计算各维度指标

agent 读 `changes.json` + `details/`，**先应用 `ignore_projects`**（project 命中忽略列表的 change
归 `ignored`，不进统计），然后按 `owner_query` 分组，每人计算下列指标。

**数量统计**
- merged change 数
- patch set 总数（details 里 revisions 数之和；拉取失败的 change 计 `unknown`）
- 涉及的 project 数 / branch 数

**代码量**
- insertions / deletions 总和（取 ChangeInfo 的 change 级汇总 `insertions` / `deletions`）

**效率指标**
- 创建→入库时长：`updated - created`（merged change 的 updated ≈ 入库时间）；给人均 / 中位数。
  Gerrit 时间戳格式为 `yyyy-MM-dd HH:mm:ss.nnnnnnnnn`（**UTC**，纳秒精度），解析时截断到微秒或
  用字符串切片处理；`created`/`updated` 在 collect 的 ChangeInfo 里已有，无需额外请求。
- review 评论数：details 里 `messages` 总数（粗略代表 review 活跃度）。
- 被打回次数：`patch set 数 - 1`（第一个 patch set 是初始提交，之后每个新 patch set 通常是回应
  review 的再提交；属近似指标，在报告里注明）。

**AI 评审前置合规**（核心规则）

对每个 merged change，从 `details/<_number>.json` 取数判定：

1. **+2 时间点 `t_plus2`**：`labels.Code-Review.all` 里 `value == 2` 的投票中**最早**的 `date`
   （含其 `_account_id` 作 `plus2_by`）。若无 +2 投票 → 该 change 不涉及本规则，分类 `no_plus2`。
2. **AI 评审时间点 `t_ai`**：取下列两者中的**最早** `date`：
   - `messages` 里 `message` 文本**含任一** `ai_review.keywords` 的评论；
   - 任一 label 的 `all` 里 `tag == ai_review.vote_tag` 的投票。
   - 都没有 → `t_ai = None`（无 AI 评审）。
3. **违规判定（时序违规）**：`t_plus2` 存在 **且**（`t_ai` 为 None **或** `t_plus2 < t_ai`）→
   `violation`（违规）。
4. 合规分类：`violation`（+2 早于 AI / 无 AI 却 +2）/ `compliant`（+2 晚于 AI）/ `no_plus2`（无 +2）。
5. 每条违规记录：`_number` / project / subject / owner / `plus2_at` / `plus2_by`（`_account_id`，有
   `name` 则附）/ `ai_at`（或 `null`）/ `lead_seconds`（`t_ai - t_plus2` 的秒数；`t_ai` 为 None 则
   `null`；**正值 = +2 抢在 AI 之前 N 秒（违规），负值 = +2 晚于 AI（合规）**）/ url。

> 时间戳均为 UTC `yyyy-MM-dd HH:mm:ss.nnnnnnnnn`，比较时按字符串切片到秒或解析为 datetime。
> 投票人通常只有 `_account_id`（非 owner 时拿不到 name），报告里展示 ID 即可。

**明细清单**：每个 change 列 project / branch / subject / owner / merge(updated) 时间 / insertions
/ deletions / patch set 数 / 合规分类 / Gerrit change url。

落盘 `report.json`（全局一份，`changes[]` 用 `owner_query` + `_number` 区分）：

```json
{
  "generated_at": "2026-06-25T14:31:00",
  "window": {"start": "...", "end": "..."},
  "system": "default",
  "summary": {
    "total_merged": 18,
    "by_user": {
      "lizhe@bicv.com": {"changes": 12, "insertions": 540, "deletions": 80, "patch_sets": 16, "projects": 4, "violations": 2},
      "zhangsan@bicv.com": {"changes": 6, "insertions": 200, "deletions": 15, "patch_sets": 7, "projects": 2, "violations": 0}
    },
    "compliance": {"violation": 3, "compliant": 10, "no_plus2": 5},
    "ignored": 1,
    "errors": 0
  },
  "changes": [
    {
      "_number": 206675,
      "owner_query": "lizhe@bicv.com",
      "project": "QA/devops",
      "branch": "master",
      "subject": "fix(scm): 未匹配qa_projects时跳过打包而非失败",
      "merged_at": "2026-06-25T09:34:06Z",
      "hours_to_merge": 0.018,
      "insertions": 185,
      "deletions": 13,
      "patch_sets": 1,
      "review_messages": 5,
      "compliance": "violation",
      "plus2_at": "2026-06-25 09:34:03",
      "plus2_by": {"_account_id": 1000001},
      "ai_at": "2026-06-25 09:34:40",
      "lead_seconds": 37,
      "url": "http://gerrit.example.com/c/QA/devops/+/206675"
    }
  ]
}
```

> `lead_seconds` 为「AI 评审 − +2」秒差：**正值或 `null` = 违规**（+2 没等 AI）；上例 +2 比 AI 早
> 37 秒，`lead_seconds: 37`，分类 `violation`。

---

## 阶段 4：report —— 呈现

1. **终端 Markdown 摘要**（直接在对话里输出）：
   - 顶部统计：窗口时间、总 merged 数、ignore 数、collect 错误数。
   - **AI 评审合规**（核心诉求，**优先列出**）：违规数 / 合规数 / 无 +2 数；**违规明细逐一列出**
     ——每条 change 的 `project · subject · #_number`、+2 时间与投票人、AI 评审时间（或「无 AI
     评审」）、提前秒数、Gerrit url。
   - **按人汇总表**（按邮箱分组）：每人 changes / +行 / -行 / patch set 数 / 人均入库时长 / 该人
     违规数；展示时优先用 `owner.name`（来自 DETAILED_ACCOUNTS），姓名缺失则用邮箱。
   - **明细清单**：每条 change 的 `project · branch · subject · merge 时间 · +行/-行 · patch set 数
     · 合规分类`，附 Gerrit change url。
   - 末尾指向 `report.json`、`report.md`、`details/` 路径供深挖。
2. **落盘 `report.md`**：与终端摘要同内容，归档到运行目录，方便转发与后续 agent 读取。
