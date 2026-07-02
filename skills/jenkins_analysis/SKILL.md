---
name: jenkins_analysis
description: |
  分析过去 24 小时（滚动窗口，now-24h 到 now）Jenkins 全部 freestyle job 的失败构建，
  判定每个失败是不是 scm（git/svn 拉代码）问题，输出分类报告。
  当用户要「看昨天 Jenkins 编译报错是不是拉代码问题」「分析近 24 小时 Jenkins 失败构建」
  「统计 scm 失败」时使用。
---

# Jenkins 失败构建分析

## 核心约定

- **时间窗口**：滚动窗口 `[now - 24h, now]`，`now` 取脚本运行时刻。**不是**自然日的「昨天 00:00 ~ 今天 00:00」。
- **范围**：全部 freestyle job（`list-jobs` 拿到的所有 job）。
- **失败定义**：`result != SUCCESS` 且 `result != None`（排除仍在运行的构建）。
- **判定方式**：分类由 agent 读日志后判定，判定依据来自 `references/` 下的失败模式清单。collect/fetch/report 有脚本；analyze 无脚本。
- **依赖**：全部 Jenkins 调用走 jenkins-restapi skill 的 `scripts/jenkins_api.py`。collect/fetch/report 脚本通过 `--cli <jenkins_api.py 路径>` 定位。

## 配置

- 认证：`~/.bicv/jenkins.json`（复用 jenkins-restapi）
- 分析规则：`~/.bicv/jenkins_analysis.json`（ignore_jobs / scm_jobs / since_hours / notify）
- 输出位置：`~/.bicv/common.json`

配置详情和四阶段 Pipeline 见 [references/pipeline.md](references/pipeline.md)。

## References 路由

| 需要了解 | 读 |
|---|---|
| 四阶段 pipeline（collect → fetch → analyze → report）+ 配置 + 节点掉线 | [references/pipeline.md](references/pipeline.md) |
| scm 失败特征模式 | [references/scm-failure-patterns.md](references/scm-failure-patterns.md) |
| compile 失败特征模式 | [references/compile-failure-patterns.md](references/compile-failure-patterns.md) |
| other 失败特征模式 | [references/other-failure-patterns.md](references/other-failure-patterns.md) |

## 默认执行

用户不指定阶段时，一气呵成跑 collect → fetch → analyze → report：

```bash
CLI=<jenkins_api.py 路径>
RUN=$(python3 skills/jenkins_analysis/scripts/collect.py --cli "$CLI" \
      | sed -n 's/^rundir=//p')
python3 skills/jenkins_analysis/scripts/fetch.py --cli "$CLI" --rundir "$RUN"
# ↓ analyze：agent 读 $RUN/logs/*.log + references/*.md，写 $RUN/analyses.json
python3 skills/jenkins_analysis/scripts/report.py --rundir "$RUN" --cli "$CLI"
# ↑ report：生成 report.json，并按 ~/.bicv/jenkins_analysis.json 的 notify 配置
#   把四类失败 + 节点掉线以飞书卡片发到群（--no-notify 可跳过，--dry-run 只预览）
```

用户显式说「只跑某阶段」时，基于运行目录里已有产物重跑该阶段。

## 前置检查

1. jenkins-restapi skill 已安装（`jenkins_api.py` 可用），路径作为各脚本的 `--cli`。
2. `~/.bicv/jenkins.json` 存在且配置了目标 Jenkins。
3. 确认/创建 `~/.bicv/common.json`。
4. **发飞书卡片前**：目标飞书群已添加**自定义机器人**（群设置 → 群机器人 → 添加自定义机器人），
   拿到其 webhook URL（若勾选了加签，一并记下 `secret`）。report 通过 webhook 直接 POST，**不依赖 lark-cli**。
5. **发飞书卡片前**：`~/.bicv/jenkins_analysis.json` 配了 `notify.webhook_url`（飞书群**自定义机器人**
   的 webhook URL，形如 `https://open.feishu.cn/open-apis/bot/v2/hook/<id>`；可选 `secret` 启用加签）。
   未配则 report 阶段只生成 report.json 不发卡片。

## 禁止

- 不绕过 `jenkins_api.py` 直接发 HTTP 请求。
- 不在脚本里硬编码 LLM 调用或 job 名做判定——分类由 agent 按 references 模式完成。
- 不把判定逻辑写死进 `analyses.json` 之外的地方——`references/*.md` 是唯一可扩展的模式源。
