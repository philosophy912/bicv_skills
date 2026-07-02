# Jenkins 分析 — 四阶段 Pipeline + 配置

## 分析规则配置（~/.bicv/jenkins_analysis.json）

判定分类时读取本配置，用于覆盖/忽略特定 job：

```json
{
  "ignore_jobs": [],
  "scm_jobs": ["SELF_TICKET_RECORD"],
  "since_hours": 24,
  "notify": {
    "webhook_url": "https://open.feishu.cn/open-apis/bot/v2/hook/xxxx",
    "secret": "可选，启用加签时填",
    "enabled": true
  }
}
```

- `ignore_jobs`：要**完全忽略**的 job 名（精确匹配），归为 `ignored`。collect 仍收集，仅 analyze 忽略。
- `since_hours`：查询窗口时长（小时），以 collect 运行时刻为终点往前推。命令行 `--since-hours` 可覆盖；
  缺省此字段时回退默认 24。例 `24` → `[now-24h, now]`。
- `scm_jobs`：**强制归 scm** 的 job 名。典型如 `SELF_TICKET_RECORD`。
- `notify`：飞书卡片通知。`webhook_url`（群**自定义机器人**的 webhook URL，必填）、
  `secret`（启用加签时填，可选）、`enabled`（默认 `true`）。缺失或无 `webhook_url` → 不发通知，
  仅生成 report.json。发送走 webhook 直接 POST，不依赖 lark-cli。
- 配置文件不存在时按空列表处理。

## 输出位置（~/.bicv/common.json）

```json
{
  "output_root": "~/.bicv/output",
  "skills": {
    "jenkins_analysis": "jenkins_analysis"
  }
}
```

- `output_root` 缺省 `~/.bicv/output`；`skills.jenkins_analysis` 缺省 `jenkins_analysis`。
- 每次运行落到 `<output_root>/<skills.jenkins_analysis>/<本地时间戳>/`。

运行目录结构：

```
<run-dir>/
├── builds.json      # collect 产物
├── logs/            # fetch 产物，每条失败构建一个 .log
├── analyses.json    # analyze 产物（agent 写，每条失败构建的判定）
└── report.json      # report 产物（全局汇总，卡片数据源）
```

---

## 信封结构速查（jenkins_api.py 子命令输出）

| 子命令 | 信封形状 | 关键字段 |
|---|---|---|
| `list-jobs` | `data` 是 **dict** `{"jobs": [...]}` | 每条 `name / url / color` |
| `list-builds` | `data` 是 **数组** `[...]` | 每条 `number / timestamp / result / duration / url`，**无 `job` 字段**（collect 脚本按 job 补） |
| `get-console-log --raw` | 直接输出 consoleText 原文（不包信封） | 日志全文 |
| `list-nodes` | `data` 是 **dict** `{"total","offlineCount","computers":[...]}` | 每条 `name / offline / temporarilyOffline / idle / numExecutors / offlineCauseReason` |

---

## 阶段 1：collect —— 收集失败构建（脚本）

```bash
python3 skills/jenkins_analysis/scripts/collect.py \
    --cli <jenkins_api.py> [--system <name>] \
    [--since-hours 24] [--workers 20] [--no-prefilter] [--rundir <dir>]
```

脚本逻辑（`scripts/collect.py`）：

1. 调 `list-jobs` 拿全部 job（含 `color`）。
2. **color 预筛**：默认跳过 `color == disabled / notbuilt` 的 job（本次实测 208 个 job 里 83 个 disabled，预筛省掉 ~40% 调用）。`--no-prefilter` 可强制全量。
3. 对剩余 job 并发（`--workers`，默认 20）调 `list-builds --job <name> --since-hours 24 --result !SUCCESS`。
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

---

## 阶段 2：fetch —— 拉取控制台日志（脚本）

```bash
python3 skills/jenkins_analysis/scripts/fetch.py \
    --cli <jenkins_api.py> --rundir <run-dir> [--system <name>] [--workers 20]
```

脚本逻辑（`scripts/fetch.py`）：

1. 读 `builds.json` 的 `builds[]`。
2. 对每条并发调 `get-console-log --job <job> --number <number> --raw`，原文写入
   `logs/<job>__<number>.log`。
   - **文件名约定**：job 名里的 `/` 替换成 `__`，job 名与 build number 之间也用 `__`
     连接。例：`infra/build-foo` #1234 → `infra__build-foo__1234.log`。
   - **容错**：单条日志拉取失败不中断，在 `builds.json` 对应条目记 `fetch_error`，并跳过
     写文件；该条在 analyze 阶段归为 `unknown`。成功的条目补 `log_file` 字段。

---

## 阶段 3：analyze —— 判定分类（agent）

agent 逐条读 `logs/<job>__<number>.log`，按下列顺序判定（**先命中先归类，单 category，
scm 优先**）。判定前先读 `~/.bicv/jenkins_analysis.json` 的 `ignore_jobs` / `scm_jobs`：

0. **最先：用户主动中止 或 配置忽略 → 忽略**。
   - 若 `result == ABORTED` 且日志含 `Aborted by <用户>` 行 → `category: "ignored"`，evidence 记
     中止者。
   - 若 job 名在配置 `ignore_jobs` 列表里 → `category: "ignored"`，evidence 注明「配置忽略」。
   - 若 ABORTED 但无「Aborted by <用户>」行（如超时/上游失败被系统中止），仍按下列规则判根因。
1. **配置强制 scm**：若 job 名在配置 `scm_jobs` 列表里 → `category: "scm"`。
2. 查 `references/scm-failure-patterns.md`：命中任一 scm 失败特征 → `category: "scm"`。
3. 否则查 `references/compile-failure-patterns.md` → `category: "compile"`。
4. 否则查 `references/other-failure-patterns.md`（环境/依赖/超时/OOM）→ `category: "other"`。
5. 都不命中 → `category: "unknown"`，仍需给一句 `evidence` 说明看到了什么。

agent 把每条判定写入 `<run-dir>/analyses.json`：

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

字段说明：
- `category`：`scm` / `compile` / `other` / `unknown` / `ignored`
- `confidence`：`high`（明确命中）/ `medium`（模糊）/ `low`（推断）
- `evidence`：一句话判定依据，scm 类尽量指出命中的特征与日志位置
- `log_excerpt`：agent 截取的最有代表性片段，**≤ 20 行**。完整日志留在 `logs/`

> 判定逻辑可扩展：新增失败模式只需往对应 `references/*.md` 追加条目，无需改代码。

---

## 阶段 4：report —— 呈现（脚本）

```bash
python3 skills/jenkins_analysis/scripts/report.py \
    --rundir <run-dir> [--analyses <path>] [--cli <jenkins_api.py>] [--system <name>]
```

脚本逻辑（`scripts/report.py`）：

1. 读 `builds.json` + `analyses.json`，按 `job + number` 合并判定进每条 build；`analyses.json`
   缺失或某条未判定则归 `unknown`。
2. 若提供 `--cli`，附带调一次 `list-nodes` 做节点掉线检查（见下），结果嵌入 `report.json` 的
   `nodes` 字段；未提供则跳过。
3. 落盘 `report.json`：

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

4. **发飞书卡片**（若 `~/.bicv/jenkins_analysis.json` 配了 `notify` 且未传 `--no-notify`）：
   直接 POST `{"msg_type":"interactive","card":...}` 到配置的 webhook URL（自定义机器人）——

   - **四类各一组**：scm / compile / other / unknown，每类按 **每 5 条拆成多张卡**（`ceil(N/5)`，
     **某类 0 条则跳过不发**）。每张卡含：标题（类别 + 条数 + 第 i/k 张）、
     顶部统计（总失败 + 四类计数 + 窗口/实例）、最多 5 条明细（job / #构建 / 判定依据 / 构建链接）。
   - **节点掉线卡**：仅当存在系统自发掉线节点时发一张，标题含 `系统自发掉线 n/总节点`。
   - 配了 `secret` 则按官方加签（`timestamp` + `sign` 追加到 URL）；单卡失败不中断，记 stderr warning。
   - `--dry-run` 只打印卡片 JSON 不真发（不依赖 lark-cli 已装）；`--no-notify` 跳过发送仅生成 report.json。
   - 无 `notify` 配置时静默跳过（兼容只生成 report.json 的用法）。

---

## 节点掉线检查（独立检查项）

除失败构建分析外，本 skill 还能检查 Jenkins 挂载节点（agent/computer）的掉线情况。
report 脚本提供 `--cli` 时自动附带；也可单独跑 `jenkins_api.py list-nodes`。

- **掉线 = `offline == true`**（一次快照，取 `/computer/api/json` 当前状态）。
  `offline==true` 又分两类：**系统自发掉线**（`temporarilyOffline==false`，节点连接中断）
  与**人为临时离线**（`temporarilyOffline==true`，运维主动操作，属预期内状态）。
- **报告口径：只报系统自发掉线**（`offline==true` 且 `temporarilyOffline==false`）。人为临时离线不纳入明细、不计入统计。
- 报告统计行写「总节点 / 系统自发掉线 / 人为临时离线（忽略）」三列；明细逐个列出系统自发掉线节点（name + `offlineCauseReason` + `numExecutors`）。
- `Built-In Node`（master）通常在线，若它系统自发掉线属严重故障，同样列出。
- **单独跑**：用户说「只查节点 / 检查节点掉线」时，直接调 `list-nodes` 并按上述口径列结果，无需跑 collect/fetch/analyze。
