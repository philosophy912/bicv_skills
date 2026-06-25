---
name: jenkins_daily_analysis
description: |
  分析过去 24 小时（滚动窗口，now-24h 到 now）Jenkins 全部 freestyle job 的失败构建，
  判定每个失败是不是 scm（git/svn 拉代码）问题，输出分类报告。流程分 collect → fetch →
  analyze → report 四阶段，每阶段落盘中间产物，可基于产物单独重跑、方便调试。本 skill 不
  含脚本，全程由 agent 编排，依赖 jenkins-restapi skill 的 CLI 子命令完成实际 Jenkins 调用。
  当用户要「看昨天 Jenkins 编译报错是不是拉代码问题」「分析近 24 小时 Jenkins 失败构建」
  「统计 scm 失败」时使用。
---

# Jenkins 每日失败构建分析

本技能扫描 Jenkins 上**全部 freestyle job** 在过去 24 小时内的失败构建（result 为
FAILURE / UNSTABLE / ABORTED），逐个拉取控制台日志，判定失败是否源于 **scm（拉代码）**
环节，并产出分类报告。

## 核心约定

- **时间窗口**：滚动窗口 `[now - 24h, now]`，`now` 取脚本运行时刻。**不是**自然日的
  「昨天 00:00 ~ 今天 00:00」。
- **范围**：全部 freestyle job（`list-jobs` 拿到的所有 job）。环境不存在多分支 pipeline，
  无需递归展开。
- **失败定义**：`result != SUCCESS` 且 `result != None`（排除仍在运行的构建）。
- **判定方式**：分类由 agent 读日志后判定（不是硬规则、不在脚本里调 LLM），判定依据来自
  `references/` 下的失败模式清单，可扩展。
- **依赖**：本 skill 不含脚本，所有 Jenkins 调用通过 jenkins-restapi skill 的
  `scripts/jenkins_api.py` 子命令完成。使用前确认 jenkins-restapi skill 已安装。

## 输出位置（~/.bicv/common.json）

落盘路径不写死，统一由 `~/.bicv/common.json` 配置：

```json
{
  "output_root": "~/.bicv/output",
  "skills": {
    "jenkins_daily_analysis": "jenkins_daily_analysis"
  }
}
```

- `output_root` 缺省 `~/.bicv/output`；`skills.jenkins_daily_analysis` 缺省
  `jenkins_daily_analysis`。
- 每次运行落到
  `<output_root>/<skills.jenkins_daily_analysis>/<本地时间戳>/`，时间戳格式
  `YYYY-MM-DD_HHMMSS`（本地时间，Python `datetime.now().strftime`）。多次运行互不覆盖，
  方便回看历史。
- 若 `~/.bicv/common.json` 不存在，先按缺省值创建目录并在开始时提示用户。

## 分析规则配置（~/.bicv/jenkins_daily_analysis.json）

判定分类时读取本配置，用于覆盖/忽略特定 job，免去改代码：

```json
{
  "ignore_jobs": [],
  "scm_jobs": ["SELF_TICKET_RECORD"]
}
```

- `ignore_jobs`：列出要**完全忽略**的 job 名（精确匹配）。这些 job 的失败不纳入任何分类统计，
  归为 `ignored`。用于排除已知噪声 job。collect 仍会收集（保留数据完整性），仅 analyze 阶段
  忽略——因此改配置后只需重跑 analyze，不必重新 collect。
- `scm_jobs`：列出**强制归 scm** 的 job 名（精确匹配）。这些 job 无论日志根因如何都归 scm。
  典型如 `SELF_TICKET_RECORD`（ticket 同步失败、调外部系统 API 报错，按业务归属归 scm）。
- 配置文件不存在时按空列表处理（不影响默认判定）。

运行目录结构：

```
<run-dir>/
├── builds.json      # collect 产物
├── logs/            # fetch 产物，每条失败构建一个 .log
├── report.json      # analyze 产物（全局汇总）
└── report.md        # report 产物（归档）
```

## 四阶段 pipeline

每个阶段都把产物落盘，因此**任意阶段可基于已有产物单独重跑**用于调试：用户说「只跑
analyze」时，跳过 collect/fetch，直接读现有 `builds.json` / `logs/`。

### 阶段 1：collect —— 收集失败构建

1. 调 `jenkins_api.py list-jobs` 拿到全部 job 名。
2. 对每个 job 调 `jenkins_api.py list-builds --job <name> --since-hours 24 --result !SUCCESS`
   （时间窗口与 result 过滤由脚本侧完成，agent 拿到的就是窗口内的失败构建）。
   - **分批并行**：一次并发约 10~20 个 job 的 `list-builds` 调用，避免单线程太慢，也避免
     对 Jenkins 压力过大。可用并行 Bash 调用实现。
3. **容错**：单个 job 的 `list-builds` 失败（job 被禁用、无构建历史、API 报错）**不中断**
   整体 collect，把失败的 job 记进 `builds.json` 的 `errors[]` 段（含 job 名与错误原因），
   继续其它 job。
4. **空结果跳过**：某 job 在窗口内无失败构建（`list-builds` 返回 `[]`）则不进 `builds`。
5. 落盘 `builds.json`：

```json
{
  "generated_at": "2026-06-25T14:30:00",
  "window": {"start": "2026-06-24T14:30:00", "end": "2026-06-25T14:30:00"},
  "system": "default",
  "builds": [
    {
      "job": "infra/build-foo",
      "number": 1234,
      "result": "FAILURE",
      "timestamp": 1750857600000,
      "duration": 45000,
      "url": "http://jenkins.../job/infra/job/build-foo/1234/"
    }
  ],
  "errors": [
    {"job": "legacy/old-job", "error": "HTTP 404: job not found"}
  ]
}
```

### 阶段 2：fetch —— 拉取控制台日志

1. 读 `builds.json` 的 `builds[]`。
2. 对每条调 `jenkins_api.py get-console-log --job <job> --number <number>`，把输出写入
   `logs/<job>__<number>.log`。
   - **文件名约定**：job 名里的 `/` 替换成 `__`，job 名与 build number 之间也用 `__`
     连接。例：`infra/build-foo` #1234 → `infra__build-foo__1234.log`。job 名里原本的单
     下划线保留，仅以双下划线作分隔符，避免歧义。report 里仍保留原始 `job` 字段，文件名
     只是落盘 key。
   - **分批并行**：同 collect，并发拉日志。
   - **容错**：单条日志拉取失败不中断，在 `builds.json` 对应条目记 `fetch_error`，该条在
     analyze 阶段归为 `unknown`。

### 阶段 3：analyze —— 判定分类

agent 逐条读 `logs/<job>__<number>.log`，按下列顺序判定（**先命中先归类，单 category，
scm 优先**）。判定前先读 `~/.bicv/jenkins_daily_analysis.json` 的 `ignore_jobs` / `scm_jobs`：

0. **最先：用户主动中止 或 配置忽略 → 忽略**。
   - 若 `result == ABORTED` 且日志含 `Aborted by <用户>` 行 → `category: "ignored"`，evidence 记
     中止者。这类是用户手动点的停止，不算失败。
   - 若 job 名在配置 `ignore_jobs` 列表里 → `category: "ignored"`，evidence 注明「配置忽略」。
   - 注意区分「用户主动中止」与「系统自动中止」：只有出现 `Aborted by <具体用户>` 才算；若
     ABORTED 但无此行（如超时/上游失败被系统中止），仍按下列规则判根因。
1. **配置强制 scm**：若 job 名在配置 `scm_jobs` 列表里 → `category: "scm"`，evidence 注明
   「配置 scm_jobs」。
2. 查 `references/scm-failure-patterns.md`：命中任一 scm 失败特征 → `category: "scm"`。
3. 否则查 `references/compile-failure-patterns.md` → `category: "compile"`。
4. 否则查 `references/other-failure-patterns.md`（环境/依赖/超时/OOM）→ `category: "other"`。
5. 都不命中 → `category: "unknown"`，仍需给一句 `evidence` 说明看到了什么。

每条给出：
- `category`：`scm` / `compile` / `other` / `unknown` / `ignored` 之一。
- `confidence`：`high`（明确命中模式）/ `medium`（模糊命中）/ `low`（靠推断）。
- `evidence`：一句话说明判定依据，scm 类尽量指出命中的特征与日志位置（如「命中 scm 模式：
  fatal: could not read Username (line 842)」）。
- `log_excerpt`：agent 截取的最有代表性片段，**≤ 20 行**。完整日志留在 `logs/` 靠文件名
  引用，不塞进 report。

落盘 `report.json`（**全局一份**，`builds[]` 用 `job` 字段区分）：

```json
{
  "generated_at": "2026-06-25T14:31:00",
  "window": {"start": "...", "end": "..."},
  "system": "default",
  "summary": {
    "total_failed": 12,
    "by_category": {"scm": 3, "compile": 6, "other": 2, "unknown": 1},
    "errors": 0
  },
  "builds": [
    {
      "job": "infra/build-foo",
      "number": 1234,
      "result": "FAILURE",
      "timestamp": 1750857600000,
      "url": "http://jenkins.../1234/",
      "log_file": "infra__build-foo__1234.log",
      "category": "scm",
      "confidence": "high",
      "evidence": "命中 scm 模式：fatal: could not read Username (line 842)",
      "log_excerpt": "..."
    }
  ]
}
```

> 判定逻辑可扩展：新增失败模式只需往对应 `references/*.md` 追加条目，无需改任何代码。
> 这是本 skill 把分类交回 agent、模式外置到 references 的设计意图。

### 阶段 4：report —— 呈现

1. **终端 Markdown 摘要**（直接在对话里输出）：
   - 顶部统计：窗口时间、总失败数、各 category 计数、collect 错误数。
   - **scm 类明细优先列出**（本 skill 核心诉求）：每条列出 job、number、confidence、
     evidence、构建 url。
   - compile / other / unknown 各给汇总计数 + 若干代表条目。
   - 末尾指向 `report.json`、`report.md`、`logs/` 路径供深挖。
2. **落盘 `report.md`**：与终端摘要同内容，归档到运行目录，方便转发与后续 agent 读取。

## 默认执行

用户不指定阶段时，默认**一气呵成**跑 collect → fetch → analyze → report。用户显式说
「只跑某阶段」时，基于运行目录里已有产物重跑该阶段（需用户指明或由 agent 选取最近一次
运行目录）。

## 前置检查

1. 确认 jenkins-restapi skill 已安装（`jenkins_api.py` 可用）。未安装则提示用户先装。
2. 确认 `~/.bicv/jenkins.json` 存在且配置了目标 Jenkins（复用 jenkins-restapi 的配置引导）。
   多实例用 `--system <name>` 切换，本 skill 透传该参数给所有 jenkins 子命令。
3. 确认/创建 `~/.bicv/common.json`（见「输出位置」）。

## 禁止

- 不绕过 jenkins-restapi skill 直接发 HTTP 请求；所有 Jenkins 调用走 `jenkins_api.py`。
- 不在本 skill 内复制 jenkins 调用代码。
- 不在脚本里硬编码 LLM 调用——分类由 agent 自身能力完成。
