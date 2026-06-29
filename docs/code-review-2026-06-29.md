# 代码审查发现 — 非单元测试脚本

- **审查日期**：2026-06-29
- **审查范围**：`skills/*/scripts/` 下的生产脚本（排除 `tests/`、`conftest.py`）
- **审查方式**：`/code-review` 全量审查（correctness 多角度），并行子 agent + 主 agent `Read` 验证
- **处置说明**：每条发现末尾有「处置」栏；本轮已处置完毕（`[x] 修复` 已修复并验证、`[x] 不处理` 暂不处理），文末有汇总表

---

## 一、覆盖范围

**完整读取**
- `bug_analysis/`：bug_analysis.py、render_charts.py、render_report.py
- `mysql/scripts/mysql_query.py`
- `jenkins_analysis/scripts/collect.py`
- `jenkins-restapi/scripts/jenkins_api.py`
- `gerrit-restapi/scripts/gerrit_api.py`
- `zentao-restapi/scripts/zentao_api.py`（DANGER 映射 / 确认机制 / create·update-bug / update-task / build 命令）
- `email/scripts/email_api.py`（附件 / 发送 / SMTP·IMAP 连接段）

**grep + 分段抽样**
- `zentao_api.py`、`email_api.py` 其余部分

**已确认无问题**
- `render_charts.py`（孤儿分页清理、matplotlib figure close、字体降级均处理得当）
- 3 份 `system_config.py`（md5 完全一致：`04772d5c…`）
- `email/`、`mysql/` 下无遗留 `system_config.py`

**红线检查（CLAUDE.md）**
- ✅ 红线①：gerrit/jenkins/zentao 三份 `system_config.py` 一致；email/mysql 用 `_email_config.py`/`_mysql_config.py`，无遗留
- ✅ 红线②：zentao 全部写命令均有 `@with_confirm` 装饰器（含 `create-build:988`），危险等级确认机制健全
- ✅ 红线③：mysql 白名单 = `SELECT/INSERT/UPDATE/WITH`，本次审查未连真实服务

> **澄清一处子 agent 误报**：子 agent 曾报告 `create-build` 无确认，经核实第 988 行 `@with_confirm("create-build", "创建版本")` 确实存在，已剔除。

---

## 二、发现清单（按严重度）

### 🔴 写入正确性

#### 1. update-* 命令字段名与 create-* 不一致（下划线 vs 驼峰）
- **位置**：`skills/zentao-restapi/scripts/zentao_api.py:307`（update-bug）、`:412`（update-task），疑似同源波及 update-story/project/execution
- **问题**：`update-bug` 用 `assigned_to`（下划线）作 payload key，而 `create-bug:298` 用 `assignedTo`（驼峰）。禅道 v2 REST API 用驼峰字段名，下划线字段不识别
- **触发**：`update-bug --id 5 --assigned-to user1` → PUT body 含 `{"assigned_to":"user1"}` → 禅道不认 → **指派人静默不更新**，用户以为改了
- **状态**：✅ 已确认（update-bug:307、update-task:412 均已读码核实）
- **建议**：update 系列统一映射为驼峰；建议核查 update-story/project/execution 是否同源（含 `pm` vs `PM` 大小写）
- **处置**：`[x] 修复`

---

### 🟠 数据正确性

#### 2. collect 默认 limit=50 导致高频失败 job 静默丢数据
- **位置**：`skills/jenkins_analysis/scripts/collect.py:92` + `skills/jenkins-restapi/scripts/jenkins_api.py:238,457`
- **问题**：`collect_one_job` 调 `list-builds` 不传 `--limit`，jenkins_api 默认 50，并用 Jenkins tree range `{0,50}` 在**服务端先截断**；时间窗过滤在截断之后才做
- **触发**：高频 job 在 24h 窗口内 >50 次失败 → 只拿到最新 50 条 → 窗口内较早的失败被静默丢弃 → **报告失败总数偏低**
- **状态**：✅ 已确认
- **建议**：collect 传一个足够大的 `--limit`（如 `--limit 0` 走 jenkins_api 的"不限"分支，或显式大值），并在文档说明
- **处置**：`[x] 修复`

#### 3. report.py by_category 只统计四类，自定义 category 计入 total 却不进明细
- **位置**：`skills/jenkins_analysis/scripts/report.py:277,159`
- **问题**：`by_category` 只覆盖 `CATEGORIES`(scm/compile/other/unknown)，agent 若在 analyses.json 写入其它 category（如 `infra`）→ 该构建计入 `total_failed`，却在四个明细区都不出现
- **触发**：agent 越界分类 → 顶部统计表 `total_failed ≠ 各类别之和`，行列不自洽，且该构建在报告里"消失"
- **状态**：✅ 代码逻辑已确认（实际触发取决于 agent 是否遵守 4 类约束）
- **建议**：归一化未知 category 到 `unknown`，或在统计层显式校验/报错
- **处置**：`[x] 修复`

#### 4. bug_analysis.py 的 --since/--until 直接拼接 SQL
- **位置**：`skills/bug_analysis/scripts/bug_analysis.py:245-246, 283-284, 351, 398`
- **问题**：`--since`/`--until` 用 f-string 直接拼进 SQL，既未转义，也不经过 mysql skill 的 `validate_sql`（bug_analysis 直接 `_execute_query`）。`_in_clause` 对用户名做了转义，但时间参数没有
- **触发**：`--since "x' OR '1'='1"` → 改变查询语义（自跑 ticket 库、SELECT 只读，威胁有限，但绕过了项目自己的 SQL 拦截层）
- **状态**：✅ 已确认
- **建议**：时间参数做格式校验（`YYYY-MM-DD[ HH:MM:SS]`）或参数化查询
- **处置**：`[x] 修复`

#### 5. render_report.py Markdown 表格未转义 `|` 和换行
- **位置**：`skills/bug_analysis/scripts/render_report.py:205,168,173`
- **问题**：MD 表格单元格直接插值，未转义 `|`（列分隔）和换行
- **触发**：Redmine `subject` 或项目名含 `|` / 换行 → Markdown 表格错列、断裂
- **状态**：✅ 已确认
- **建议**：单元格内 `|` → `\|`、换行 → `<br>` 或空格
- **处置**：`[x] 修复`

---

### 🟡 健壮性 / 安全

#### 6. jenkins_api.py / gerrit_api.py 的 urlopen 无 timeout
- **位置**：`skills/jenkins-restapi/scripts/jenkins_api.py:87`、`skills/gerrit-restapi/scripts/gerrit_api.py:86`
- **问题**：`request.urlopen(req)` 未传 `timeout` 参数
- **触发**：CLI 直连时 Jenkins/Gerrit 响应卡住（慢查询/半开连接）→ 进程**永久挂起**，需手动 kill（pipeline 里有 subprocess timeout 兜底，但直接调命令时无保护）
- **状态**：✅ 已确认
- **建议**：`urlopen(req, timeout=N)`（email skill 的 SMTP/IMAP 已有 `CONNECTION_TIMEOUT`，可参照）
- **处置**：`[x] 修复`

#### 7. 超期状态口径：Zentao 与 Redmine 不一致
- **位置**：`skills/bug_analysis/scripts/bug_analysis.py:349`（Zentao）vs `:396`（Redmine）
- **问题**：Zentao overdue 只排除 `status != '已关闭'`；Redmine 排除 `status_name NOT IN ('已关闭','已拒绝')`。Zentao 未排除"已解决/已拒绝"
- **触发**：Zentao 侧"已解决/已拒绝"状态的 bug 也被计入超期 → 跨系统口径偏差，超期数不可比
- **状态**：⚠️ 待业务确认（可能是有意为之）
- **建议**：与业务对齐两系统排除的状态集合
- **处置**：`[x] 不处理`

#### 8. mysql validate_sql 把 MySQL 条件注释 `/*!…*/` 当普通注释删除
- **位置**：`skills/mysql/scripts/mysql_query.py:81`
- **问题**：`re.sub(r"/\*.*?\*/", "")` 会把 MySQL 5+ **可执行**的条件注释 `/*!50000 …*/` 一并删掉，从而隐藏其中的 `DELETE` 等关键词绕过静态检测
- **触发**：构造含条件注释的 SQL → 危险关键词被清洗 → 通过校验。受 mysql-connector 默认单语句限制，实际执行 DELETE 较难，但拦截层存在盲区
- **状态**：⚠️ PLAUSIBLE（机制真实，利用难度较高）
- **建议**：条件注释单独处理（拒绝或保留原样再检测）
- **处置**：`[x] 修复`

#### 9. email 大附件整文件读入内存
- **位置**：`skills/email/scripts/email_api.py:571-572`
- **问题**：`open(path,"rb").read()` 把附件整体读入内存
- **触发**：发送数百 MB 级附件 → 内存暴涨 / OOM
- **状态**：✅ 已确认
- **建议**：MIME 本身需完整内容，可加附件大小上限并提前报错；或文档标注限制
- **处置**：`[x] 修复`

---

### ⚪ 低危

#### 10. mysql read_sql_file 无路径遍历防护（与 docstring 不符）
- **位置**：`skills/mysql/scripts/mysql_query.py:102-113`
- **问题**：`read_sql_file`(`@path`) 直接 `Path(file_path).read_text()`，无遍历检查；但 docstring 声称"same path-traversal protection as Gerrit/Jenkins"
- **触发**：`@../../etc/passwd` 可读任意文件（内容非 SQL，执行失败，影响小）
- **状态**：✅ 已确认（主要是文档与实现不符）
- **建议**：补防护，或修正 docstring
- **处置**：`[x] 修复`

#### 11. zentao 确认 prompt 的 input() 未捕获 EOF/Ctrl+C
- **位置**：`skills/zentao-restapi/scripts/zentao_api.py:78`（配合 main 的异常捕获）
- **问题**：`confirm_dangerous` 的 `input()` 在 Ctrl+D/Ctrl+C 抛 `EOFError`/`KeyboardInterrupt`，main 只捕 `ZentaoError` → 打印堆栈而非干净退出
- **触发**：危险确认时 Ctrl+C → traceback
- **状态**：✅ 已确认
- **建议**：main 增捕 `KeyboardInterrupt`/`EOFError`，或 confirm 内捕获
- **处置**：`[x] 修复`

#### 12. zentao 401 重试不区分写操作，可能重复创建
- **位置**：`skills/zentao-restapi/scripts/zentao_api.py`（request_json_with_auth 的 401 重试）
- **问题**：401 时重新取 token 并重试，POST/PUT 写操作若服务端已执行却回 401 → 重试可能重复创建
- **触发**：token 过期边界 + 写操作 → Bug/任务被创建两次
- **状态**：⚠️ PLAUSIBLE（取决于禅道在 token 过期时是否已执行）
- **建议**：写操作 401 不自动重试，提示用户
- **处置**：`[x] 修复`

#### 13. fetch.py 直接取 build 键，脏数据会中断整批 fetch
- **位置**：`skills/jenkins_analysis/scripts/fetch.py:43,94`
- **问题**：`build["job"]`/`build["number"]` 直接取键，无兜底
- **触发**：builds.json 被手工编辑或上游异常导致某条缺键 → KeyError → 整批 fetch 崩溃，已抓日志无法落盘
- **状态**：⚠️ 鲁棒性（正常流程 collect 总会补 `job`，风险低）
- **建议**：单条异常跳过并记 error，不影响整体
- **处置**：`[x] 修复`

---

## 三、处置汇总表

> 请在「处置」列填写：`修复` / `不修` / `修复`，可补充原因。

| # | 严重度 | 文件 | 一句话 | 处置 |
|---|---|---|---|---|
| 1 | 🔴 | zentao_api.py:307,412 | update-* 字段名 assigned_to vs assignedTo，指派人静默不更新 | `[x] 修复` |
| 2 | 🟠 | collect.py:92 | 默认 limit=50 丢失高频失败 | `[x] 修复` |
| 3 | 🟠 | report.py:277,159 | 自定义 category 计入 total 却不进明细 | `[x] 修复` |
| 4 | 🟠 | bug_analysis.py:245 | --since/--until 拼 SQL（注入） | `[x] 修复` |
| 5 | 🟠 | render_report.py:205 | MD 表格未转义 \| 和换行 | `[x] 修复` |
| 6 | 🟡 | jenkins_api.py:87, gerrit_api.py:86 | urlopen 无 timeout | `[x] 修复` |
| 7 | 🟡 | bug_analysis.py:349 vs 396 | 超期状态口径 Zentao/Redmine 不一致 | `[x] 不处理` |
| 8 | 🟡 | mysql_query.py:81 | 条件注释 /*!…*/ 绕过 validate_sql | `[x] 修复` |
| 9 | 🟡 | email_api.py:571 | 大附件整读内存 OOM | `[x] 修复` |
| 10 | ⚪ | mysql_query.py:102 | read_sql_file 无路径遍历防护（文档不符） | `[x] 修复` |
| 11 | ⚪ | zentao_api.py:78 | input() EOF/Ctrl+C 未捕获 | `[x] 修复` |
| 12 | ⚪ | zentao_api.py | 401 重试可能重复创建 | `[x] 修复` |
| 13 | ⚪ | fetch.py:43,94 | 脏数据 KeyError 中断整批 fetch | `[x] 修复` |

---

## 四、修复记录（2026-06-29）

- **验证**：`python3 -m pytest` 全量 **945 passed**，`fail_under=90` 通过；各 skill 覆盖率均 ≥ 93%（zentao 99%、jenkins_analysis 99%、gerrit 100%、jenkins 99%、bug_analysis 98-99%、mysql 95%、email 93%）
- **改动文件**：
  - `zentao-restapi/scripts/zentao_api.py` — #1 update-* 字段名改驼峰（assigned_to→assignedTo、pm→PM）；#6 urlopen 加 `REQUEST_TIMEOUT`；#11 confirm 捕获 EOF/Ctrl+C；#12 写操作 401 不自动重试
  - `zentao-restapi/tests/test_zentao_api.py` — 同步断言 + 补 confirm EOF / 写 401 用例
  - `jenkins_analysis/scripts/collect.py` — #2 list-builds 传 `--limit 0`（不限）
  - `jenkins_analysis/scripts/report.py` — #3 非标准 category 归一化为 unknown
  - `jenkins_analysis/scripts/fetch.py` — #13 缺 job/number 兜底跳过，不中断整批
  - `jenkins_analysis/tests/test_fetch.py` / `test_report.py` — 补缺键 / 归一化用例
  - `bug_analysis/scripts/bug_analysis.py` — #4 `--since`/`--until` 格式校验防 SQL 注入
  - `bug_analysis/scripts/render_report.py` — #5 MD 表格单元格转义 `|` 与换行
  - `bug_analysis/tests/test_bug_analysis.py` / `test_render_report.py` — 补校验 / 转义用例
  - `jenkins-restapi/scripts/jenkins_api.py` + `gerrit-restapi/scripts/gerrit_api.py` — #6 urlopen 加 `REQUEST_TIMEOUT`
  - `mysql/scripts/mysql_query.py` — #8 拒绝 MySQL 条件注释 `/*!…*/`；#10 read_sql_file 加 NUL 防护 + 修正 docstring
  - `mysql/tests/test_mysql_query.py` — 补条件注释 / NUL 用例
  - `email/scripts/email_api.py` — #9 附件大小上限（25 MB）防 OOM
  - `email/tests/test_email_api.py` — 补大附件用例
- **未处理**：#7（Zentao/Redmine 超期状态口径不一致）经确认暂不处理，待业务对齐两系统排除的状态集合
