# Jenkins 失败构建分析报告

> **本文件是 report 阶段的输出样板**，约束「终端 Markdown 摘要」与落盘 `report.md`（两者同内容）。
> 以下为示例数据，实际以 `report.json` 为准。填写约束见文末「填写约束」一节。

**时间窗口**：2026-06-24 14:30 ~ 2026-06-25 14:30（滚动 24h）
**生成时间**：2026-06-25 14:31
**Jenkins 实例**：default

## 顶部统计

| 总失败数 | scm | compile | other | unknown | collect 错误 |
|---|---|---|---|---|---|
| 12 | 3 | 6 | 2 | 1 | 0 |

> `总失败数 = scm + compile + other + unknown`；`collect 错误` 单列，不计入失败。

## 一、scm 失败明细（3 条）

| 序 | Job | #构建 | 判定依据 | 构建链接 |
|---|---|---|---|---|
| 1 | SELF_TICKET_RECORD | #88 | 配置 scm_jobs 强制归类 | [打开](http://jenkins.../SELF_TICKET_RECORD/88/) |
| 2 | infra/build-foo | #1234 | 命中 scm 模式：fatal: could not read Username (line 842) | [打开](http://jenkins.../job/infra/job/build-foo/1234/) |
| 3 | platform/pull-deps | #456 | 命中 scm 模式：svn: E170013 Unable to connect (line 120) | [打开](http://jenkins.../platform/job/pull-deps/456/) |

## 二、compile 失败（6 条，此处列代表 5 条）

| Job | #构建 | 判定依据 | 构建链接 |
|---|---|---|---|
| app/portal | #770 | error: use of undeclared identifier 'foo' (line 312) | [打开](...) |
| ... | | | |

> 完整 6 条见 `report.json`。

## 三、other 失败（2 条）

| Job | #构建 | 判定依据 | 构建链接 |
|---|---|---|---|
| env/provision | #12 | No space left on device (line 88) | [打开](...) |
| net/gateway | #301 | npm ERR! network timeout (line 204) | [打开](...) |

## 四、unknown（1 条）

| Job | #构建 | 判定依据 | 构建链接 |
|---|---|---|---|
| misc/legacy | #3 | 日志无明显根因，疑似上游级联失败 | [打开](...) |

## 节点掉线检查

> 仅报**系统自发掉线**（`offline==true` 且 `temporarilyOffline==false`）；人为临时离线（`temporarilyOffline==true`）属运维主动操作，已忽略。来源：`jenkins_api.py list-nodes`（一次快照）。

| 总节点 | 系统自发掉线 | 人为临时离线（忽略） |
|---|---|---|
| 8 | 2 | 0 |

系统自发掉线节点明细：

| 节点 | 掉线原因 | 执行器数 |
|---|---|---|
| bug-10 | Connection was broken | 4 |

> 无系统自发掉线节点时本节写「（无系统自发掉线节点）」。

## 产物路径

- 汇总 JSON：`<run-dir>/report.json`
- 本报告：`<run-dir>/report.md`
- 失败构建清单：`<run-dir>/builds.json`
- 日志目录：`<run-dir>/logs/`（每条 `<job>__<number>.log`）

---

## 填写约束（给 agent：勿把本节带进产出的 `report.md`）

- **节顺序固定**：顶部统计 → 一、scm 明细 → 二、compile → 三、other → 四、unknown → 节点掉线检查 → 产物路径。某类为 0 条时**保留节标题**，正文写「（无）」，不得删节。
- **条目排序**：各类内部按 job 字典序、同 job 按 build number 升序。
- **scm 全列**：本 skill 核心诉求，逐条列出、不截断。
- **compile / other / unknown 各最多 5 条代表条目**，其余在 `report.json` 查。代表条目按
  **job 分组**选取：先保证每个 job 至少出 1 条（job 字典序），名额富余时按 job 失败数从多到
  少补齐到 5。目的：避免同 job 大量重复失败把其它 job 的不同失败模式挤出代表样本（report.py
  的 `pick_representatives` 已实现该算法）。
- **表格列头固定**：不得增删列。`构建链接` 用构建 `url` 渲染成 `[打开](url)`。
- **不展示置信度**：`confidence` 只记录在 `report.json`，报告表格不单独列。
- **不展示 ignored**：用户主动中止 / 配置忽略的构建仍在 `report.json`（`category == "ignored"`），报告不单独列表、不计入顶部统计。
- **日志摘要不进报告**：完整日志靠 `log_file`（`logs/<job>__<number>.log`）引用；`log_excerpt` 只留 `report.json`，不在本报告展开。
- **证据带行号**：`判定依据` 尽量指出命中特征 + 日志行号，如「命中 scm 模式：fatal: could not read Username (line 842)」。
- **取数来源**：顶部统计取 `report.json.summary`。
- **节点掉线检查**：只列**系统自发掉线**节点（`offline==true` 且 `temporarilyOffline==false`，name + `offlineCauseReason` + `numExecutors`）；人为临时离线（`temporarilyOffline==true`）忽略、不计入统计。统计行三列：总节点 / 系统自发掉线 / 人为临时离线（忽略）。无系统自发掉线写「（无系统自发掉线节点）」。数据来自 `list-nodes`，一次快照。
