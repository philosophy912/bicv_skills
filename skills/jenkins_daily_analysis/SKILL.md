---
name: jenkins_daily_analysis
description: |
  分析过去 24 小时（滚动窗口，now-24h 到 now）Jenkins 全部 freestyle job 的失败构建，
  判定每个失败是不是 scm（git/svn 拉代码）问题，输出分类报告。流程分 collect → fetch →
  analyze → report 四阶段，每阶段落盘中间产物，可基于产物单独重跑、方便调试。collect/
  fetch/report 是 skill 内编排脚本（subprocess 调 jenkins-restapi 的 jenkins_api.py 子命令，
  不复制 HTTP 代码）；analyze 由 agent 读控制台日志、按 references/ 模式判定，产出
  analyses.json。当用户要「看昨天 Jenkins 编译报错是不是拉代码问题」「分析近 24 小时
  Jenkins 失败构建」「统计 scm 失败」时使用。
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
- **依赖**：所有 Jenkins 调用通过 jenkins-restapi skill 的 `scripts/jenkins_api.py` 子命令
  完成。本 skill 的 collect/fetch/report 脚本通过 `--cli <jenkins_api.py 路径>` 定位它，
  使用前确认 jenkins-restapi skill 已安装。

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
- 若 `~/.bicv/common.json` 不存在，按缺省值落盘并在开始时提示用户。

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
├── analyses.json    # analyze 产物（agent 写，每条失败构建的判定）
├── report.json      # report 产物（全局汇总）
└── report.md        # report 产物（归档）
```

## 信封结构速查（jenkins_api.py 子命令输出）

编排脚本解析 `jenkins_api.py` 的 JSON 信封时，**不同子命令的 `data` 形状不同**，务必区分：

| 子命令 | 信封形状 | 关键字段 |
|---|---|---|
| `list-jobs` | `data` 是 **dict** `{"jobs": [...]}` | 每条 `name / url / color` |
| `list-builds` | `data` 是 **数组** `[...]` | 每条 `number / timestamp / result / duration / url`，**无 `job` 字段**（collect 脚本按 job 补） |
| `get-console-log --raw` | 直接输出 consoleText 原文（不包信封） | 日志全文 |
| `list-nodes` | `data` 是 **dict** `{"total","offlineCount","computers":[...]}` | 每条 `name / offline / temporarilyOffline / idle / numExecutors / offlineCauseReason` |

## 四阶段 pipeline

每个阶段都把产物落盘，因此**任意阶段可基于已有产物单独重跑**用于调试：用户说「只跑
analyze」时，跳过 collect/fetch，直接读现有 `builds.json` / `logs/`。

下方命令中 `<jenkins_api.py>` 指向 jenkins-restapi 的 `scripts/jenkins_api.py`（仓库内为
`skills/jenkins-restapi/scripts/jenkins_api.py`，安装后取实际安装路径）。

### 阶段 1：collect —— 收集失败构建（脚本）

```bash
python3 skills/jenkins_daily_analysis/scripts/collect.py \
    --cli <jenkins_api.py> [--system <name>] \
    [--since-hours 24] [--workers 20] [--no-prefilter] [--rundir <dir>]
```

脚本逻辑（`scripts/collect.py`）：

1. 调 `list-jobs` 拿全部 job（含 `color`）。
2. **color 预筛**：默认跳过 `color == disabled / notbuilt` 的 job——它们在滚动窗口内基本
   无新构建，扫描纯属浪费（本次实测 208 个 job 里 83 个 disabled，预筛省掉 ~40% 调用）。
   `--no-prefilter` 可强制全量（兜底：极少数情况下 disabled job 禁用前的构建时间戳仍落在
   窗口内）。`builds.json.prefilter` 记录跳过数量与 color 集合，便于审计。
3. 对剩余 job 并发（`--workers`，默认 20）调 `list-builds --job <name> --since-hours 24
   --result !SUCCESS`。
4. **容错**：单个 job 的 `list-builds` 失败不中断，记进 `builds.json` 的 `errors[]`。
5. 空结果跳过；`list-builds` 的 `data` 是数组、**无 `job` 字段**，脚本按 job 补上再合并。
6. 落盘 `builds.json`：

```json
{
  "generated_at": "2026-06-28T22:16:46",
  "window": {"start": "2026-06-27T22:16:46", "end": "2026-06-28T22:16:46"},
  "system": "default",
  "since_hours": 24,
  "prefilter": {"enabled": true, "skipped_count": 86, "skipped_colors": ["disabled", "notbuilt"]},
  "builds": [
    {"job": "infra/build-foo", "number": 1234, "result": "FAILURE",
     "timestamp": 1750857600000, "duration": 45000, "url": "http://jenkins.../1234/"}
  ],
  "errors": [
    {"job": "legacy/old-job", "error": "exit 1: HTTP 404: ..."}
  ]
}
```

### 阶段 2：fetch —— 拉取控制台日志（脚本）

```bash
python3 skills/jenkins_daily_analysis/scripts/fetch.py \
    --cli <jenkins_api.py> --rundir <run-dir> [--system <name>] [--workers 20]
```

脚本逻辑（`scripts/fetch.py`）：

1. 读 `builds.json` 的 `builds[]`。
2. 对每条并发调 `get-console-log --job <job> --number <number> --raw`，原文写入
   `logs/<job>__<number>.log`。
   - **文件名约定**：job 名里的 `/` 替换成 `__`，job 名与 build number 之间也用 `__`
     连接。例：`infra/build-foo` #1234 → `infra__build-foo__1234.log`。job 名里原本的单
     下划线保留，仅以双下划线作分隔符，避免歧义。report 里仍保留原始 `job` 字段，文件名
     只是落盘 key。
   - **容错**：单条日志拉取失败不中断，在 `builds.json` 对应条目记 `fetch_error`，并跳过
     写文件；该条在 analyze 阶段归为 `unknown`。成功的条目补 `log_file` 字段。

### 阶段 3：analyze —— 判定分类（agent）

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

agent 把每条判定写入 `<run-dir>/analyses.json`（**每条对应 `builds.json` 的一条失败构建**，
report 脚本按 `job + number` 匹配；缺失的条目会被 report 脚本归 `unknown` 兜底）：

```json
[
  {
    "job": "infra/build-foo",
    "number": 1234,
    "category": "scm",
    "confidence": "high",
    "evidence": "命中 scm 模式：fatal: could not read Username (line 842)",
    "log_excerpt": "..."
  }
]
```

每条字段：
- `category`：`scm` / `compile` / `other` / `unknown` / `ignored` 之一。
- `confidence`：`high`（明确命中模式）/ `medium`（模糊命中）/ `low`（靠推断）。
- `evidence`：一句话说明判定依据，scm 类尽量指出命中的特征与日志位置（如「命中 scm 模式：
  fatal: could not read Username (line 842)」）。
- `log_excerpt`：agent 截取的最有代表性片段，**≤ 20 行**。完整日志留在 `logs/` 靠文件名
  引用，不塞进 report。

> 判定逻辑可扩展：新增失败模式只需往对应 `references/*.md` 追加条目，无需改任何代码。
> 这是本 skill 把分类交回 agent、模式外置到 references 的设计意图。

### 阶段 4：report —— 呈现（脚本）

```bash
python3 skills/jenkins_daily_analysis/scripts/report.py \
    --rundir <run-dir> [--analyses <path>] [--cli <jenkins_api.py>] [--system <name>]
```

脚本逻辑（`scripts/report.py`）：

1. 读 `builds.json` + `analyses.json`，按 `job + number` 合并判定进每条 build；`analyses.json`
   缺失或某条未判定则归 `unknown`。`generated_at` / `window` / `system` 复用 `builds.json`
   （口径统一为采集时刻，不再另取）。
2. 若提供 `--cli`，附带调一次 `list-nodes` 做节点掉线检查（见下），结果嵌入 `report.json` 的
   `nodes` 字段；未提供则跳过，报告「节点掉线检查」节注明未执行。
3. 落盘 `report.json`（全局汇总，`builds[]` 用 `job` 字段区分）：

```json
{
  "generated_at": "2026-06-28T22:16:46",
  "window": {"start": "...", "end": "..."},
  "system": "default",
  "since_hours": 24,
  "summary": {
    "total_failed": 12,
    "by_category": {"scm": 3, "compile": 6, "other": 2, "unknown": 1},
    "errors": 0
  },
  "builds": [
    {"job": "infra/build-foo", "number": 1234, "result": "FAILURE",
     "url": "http://jenkins.../1234/", "log_file": "infra__build-foo__1234.log",
     "category": "scm", "confidence": "high",
     "evidence": "命中 scm 模式：fatal: could not read Username (line 842)",
     "log_excerpt": "..."}
  ],
  "nodes": {"total": 60, "details": [...], "manual_offline_count": 9}
}
```

4. **按 [`assets/report-template.md`](assets/report-template.md) 渲染 `report.md`**——
   节顺序、表格列头、scm 全列 / 其余各类代表条目上限、日志摘要不进报告等约束见该模板。

**输出格式严格遵循模板**：终端 Markdown 摘要（agent 直接在对话里复述 `report.md` 关键内容）
与落盘 `report.md` 同内容。模板里「compile/other/unknown 代表条目」用**按 job 分组、每个 job
至少 1 条、再按失败数补齐到上限**的算法选取（避免同 job 大量重复失败挤掉其它 job 的不同
失败模式），scm 类逐条全列。

## 节点掉线检查（独立检查项）

除失败构建分析外，本 skill 还能检查 Jenkins 挂载节点（agent/computer）的掉线情况——
report 脚本提供 `--cli` 时自动附带；也可单独跑 `jenkins_api.py list-nodes`。

```bash
# 列出全部节点（含在线/掉线状态）
python3 <jenkins_api.py> list-nodes
# 只看掉线节点（"丢失"的节点）
python3 <jenkins_api.py> list-nodes --offline
```

- **掉线 = `offline == true`**（一次快照，取 `/computer/api/json` 当前状态；不做历史对比）。`offline==true` 又分两类：**系统自发掉线**（`temporarilyOffline==false`，节点连接中断/agent 挂了）与**人为临时离线**（`temporarilyOffline==true`，运维主动「Mark this node temporarily offline」停的，属预期内状态）。
- **报告口径：只报系统自发掉线**（`offline==true` 且 `temporarilyOffline==false`）。人为临时离线不纳入明细、不计入统计、不展示——它是运维主动操作，不构成需要排查的异常。
- `list-nodes --offline` 返回**所有** `offline==true` 节点（含人为临时离线）；report 脚本按 `temporarilyOffline` 自行过滤。
- 报告统计行写「总节点 / 系统自发掉线 / 人为临时离线（忽略）」三列；明细逐个列出系统自发掉线节点（name + `offlineCauseReason` + `numExecutors`）。
- `Built-In Node`（master）通常在线，若它系统自发掉线属严重故障，同样列出。
- **单独跑**：用户说「只查节点 / 检查节点掉线」时，直接调 `list-nodes` 并按上述口径列结果，无需跑 collect/fetch/analyze。

## 默认执行

用户不指定阶段时，默认**一气呵成**跑 collect → fetch → analyze → report：

```bash
CLI=<jenkins_api.py 路径>
RUN=$(python3 skills/jenkins_daily_analysis/scripts/collect.py --cli "$CLI" \
      | sed -n 's/^rundir=//p')
python3 skills/jenkins_daily_analysis/scripts/fetch.py --cli "$CLI" --rundir "$RUN"
# ↓ analyze：agent 读 $RUN/logs/*.log + references/*.md，写 $RUN/analyses.json
python3 skills/jenkins_daily_analysis/scripts/report.py --rundir "$RUN" --cli "$CLI"
```

（analyze 是 agent 自身职责，无脚本——agent 在 collect/fetch 后读日志写 `analyses.json`，再跑
report。）用户显式说「只跑某阶段」时，基于运行目录里已有产物重跑该阶段（需用户指明或由 agent
选取最近一次运行目录）。

## 前置检查

1. 确认 jenkins-restapi skill 已安装（`jenkins_api.py` 可用），并把其路径作为各脚本的
   `--cli`。未安装则提示用户先装。
2. 确认 `~/.bicv/jenkins.json` 存在且配置了目标 Jenkins（复用 jenkins-restapi 的配置引导）。
   多实例用 `--system <name>` 切换，本 skill 透传该参数给所有脚本/子命令。
3. 确认/创建 `~/.bicv/common.json`（见「输出位置」）。

## 禁止

- 不绕过 jenkins_api.py 直接发 HTTP 请求；所有 Jenkins 调用走 `jenkins_api.py` 子命令
  （collect/fetch/report 脚本也只是 subprocess 调它，不复制 HTTP 代码）。
- 不在脚本里硬编码 LLM 调用或硬编码 job 名做判定——分类由 agent 自身能力、按 references
  模式完成；脚本只负责机械编排与渲染。
- 不把判定逻辑写死进 `analyses.json` 之外的地方——`references/*.md` 是唯一可扩展的模式源。
