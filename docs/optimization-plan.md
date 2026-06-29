<!--
  优化方案 — 结合安装方式（npx skills add）和项目实际约束制定
  2026-06-29 初始版本
  待审核后按优先级逐步执行
-->

# Skills 仓库优化方案

## 前提与约束

- **安装方式**：`npx skills add` 将各 skill 目录独立拷贝到 agent 的 skills 目录，无跨 skill 共享依赖。每个 skill 必须自包含。
- **测试硬性要求**：所有 skill 主脚本行覆盖率 ≥ 90%，全量测试 `python3 -m pytest` 通过才能合并。
- **脚本纯标准库**：除 mysql 需 `mysql-connector-python` 外，所有 API 脚本只用 Python 标准库。

---

## 一、system_config.py 三份拷贝

### 结论：当前设计合理，不需要改。

`system_config.py`（216 行）在 gerrit-restapi / jenkins-restapi / zentao-restapi 中各持一份完全相同的拷贝。

**不需要优化的理由：**

1. `npx skills add` 没有 skill 间依赖机制，每个 skill 安装后独立存在，不存在可被多个 skill 共同 import 的共享路径。
2. 若引入构建期拷贝同步脚本，增加的复杂度（额外 CI 检查、安装脚本改造）大于它消除的微风险。
3. 该模块接口稳定、改动频率极低，内部注释已标注「改一处需同步另外三处」。

---

## 二、SKILL.md 体积瘦身（P1）

### 问题

总计 77KB SKILL.md 内容，每次 agent 加载一个 skill 就消耗全部指令到上下文。最重的是：

| Skill | 行数 | 大小 |
|---|---|---|
| gerrit_daily_analysis | 303 | 16KB |
| jenkins_daily_analysis | 299 | 16KB |

这些文件把完整命令行参数、JSON 信封示例、四阶段 pipeline 细节都写进 SKILL.md。按照 skill 渐进披露规范，SKILL.md 应保留路由指令与核心约束，操作手册应移到 `references/`。

### 方案

**gerrit_daily_analysis**：四阶段编排逻辑拆分到 references：

```
references/
├── pipeline-overview.md     # 四阶段总览、运行目录结构
├── stage-1-collect.md       # collect — 查询语法、容错约定
├── stage-2-fetch.md         # fetch — option 组合、落盘格式
├── stage-3-analyze.md       # analyze — 指标计算、AI 合规判定规则
├── stage-4-report.md        # report — 邮件模板、图表约定
└── time-window.md           # 时间窗口解析约定
```

SKILL.md 精简到约 80 行：一句话说明 + references 路由表 + 核心约束 + 配置路径 + 禁止规则。

**jenkins_daily_analysis**：同理，四阶段流程和 JSON 信封表移出：

```
references/
├── pipeline-overview.md     # 四阶段总览
├── stage-3-analyze.md       # 判定规则（scm/compile/other + ignore/scm_jobs 配置）
└── node-check.md            # 节点掉线检查说明
```

SKILL.md 精简到约 100 行。

**bug_daily_analysis**（9KB）：JSON 信封示例可移到 references/。

**其他 skill**：gerrit-restapi、jenkins-restapi、zentao-restapi、email、mysql 已经较轻（5-10KB），可以不动。

### 收益

- 每次 skill 加载节省 200+ 行 token
- 渐进披露更清晰：agent 先看 SKILL.md 判命中，再按 references 路由深入
- 不影响行为，路由标注已存在于现有 references/ 文件名中

### 执行注意

移出内容时必须保证触发关键词和禁用规则留在 SKILL.md。

---

## 三、gerrit_daily_analysis 零脚本（P2）

### 问题

该 skill 只有 SKILL.md，编排全部由 agent 完成。对比：

| Skill | 脚本数 | 测试文件数 |
|---|---|---|
| jenkins_daily_analysis | 3（collect / fetch / report）| 3 |
| gerrit_daily_analysis | 0 | 0 |

后果：不同 agent/模型输出不可复现；指标计算依赖 agent 解析容易出错；无测试卡回归。

### 方案

不写全套脚本（太大，与 agent 合理分工冲突），推荐一个轻量 `analyze.py`：

- 输入：`changes.json` + `details/`
- 输出：`report.json`（含指标汇总、AI 合规判定、明细清单）
- 确定性计算从 agent 手中接过：merge 时长、patch set 数、评论数、时间戳比较判定合规

Agent 保留：时间窗口解析、调 gerrit-restapi 子命令、落盘产物、读 report.json 生成终端摘要。

预估：约 200-300 行 Python + 对应测试，ROI 最好。

### 收益

核心指标可测试、可复现；编排链路缩短，容错性提升。

---

## 四、email/scripts/.coverage 路径偏差（P3）

### 问题

`email/scripts/.coverage`（52KB）在 scripts/ 子目录，而其他 skill 的 .coverage 都在 skill 根目录。email 的 conftest.py 把 `scripts/` 加入 sys.path，可能导致 pytest 输出路径偏移。

不影响 git（gitignore 已覆盖），但暗示单 skill 覆盖率报告可能路径错位。

### 方案

```bash
rm skills/email/scripts/.coverage
```

在 email skill 目录重跑一次 `pytest --cov=email_api --cov-report=term-missing` 确认路径正常即可。

---

## 五、zentao-restapi references 薄（P3，长期积累）

zentao-restapi references 只 2 个文件（5KB），gerrit-restapi 有 11 个。但 zentao_api.py 自身最厚（1475 行），禅道 API 风格扁平，一个协议文件够用。

不强行补齐。新增端点时按需补对应域参考即可。当前状态够用。

---

## 六、配置模块命名不一致（P4，不处理）

| skill | 模块 |
|---|---|
| gerrit/jenkins/zentao | `system_config` |
| email | `_email_config` |
| mysql | `_mysql_config` |

历史遗留差异，不影响功能。不处理。

---

## 优先级总结

| 优先级 | 条目 | 工作量 | 收益 |
|---|---|---|---|
| P1 | SKILL.md 瘦身 | 4-6h | token 节省 |
| P2 | gerrit_daily_analysis 加 analyze.py | 3-5h | 可测试性 + 可靠性 |
| P3 | email .coverage 清理 | 1 分钟 | 清洁度 |
| P3 | zentao references | 随需积累 | - |
| P4 | 命名一致性 | 不处理 | - |
