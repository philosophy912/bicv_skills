# Bug 分析 — HTML 邮件周报（render_email.py）

把四份 JSON + render_charts 的图清单渲染成**自包含 HTML 邮件**（图 base64 内嵌），供 email skill 发送。只吃 JSON、不连库、不依赖 matplotlib。

```bash
python3 scripts/render_email.py \
  --submissions sub.json --overdue ovd.json \
  --severe sev.json --closures cls.json \
  --charts charts.json
```

### 产出

- 落盘 `email_<YYYYMMDD>.html`（图以 `data:image/png;base64,...` 内嵌，邮件自包含）。
- 五块内容：
  1. **本周提交情况**：按提交人 / 按项目（数量+占比）+ 零提交点名（红色）。
  2. **严重-本周**：明细表（缺陷ID / 项目 / 模块 / 提交人 / 状态）。
  3. **严重-本组未关闭**：本组提交的当前未关闭严重缺陷明细表。
  4. **跟踪不及时**：纯表格明细（缺陷ID / 项目 / 模块 / 指派人 / 超期天数），按天数降序，给人对质。
  5. **本周关闭**：按关闭人饼图（+ 提交 vs 关闭对比柱）。
- 缺陷ID 带 `Z-`（禅道）/ `R-`（Redmine）前缀，跨系统不撞号。
- 返回 JSON 信封：`{"generated_at", "html_path", "images": [...]}`。

### 发送（agent 编排）

读 `~/.bicv/bug_analysis.json` 的 `recipients.to`，调 email skill：

```bash
python3 ~/.claude/skills/email/scripts/email_api.py send \
  --to <to> \
  --subject "【缺陷分析报告 2026-06-22~2026-06-28】" \
  --body @email_<日期>.html --html --system <email 实例>
```

> 图 base64 内嵌，QQ/网易/Gmail web 邮箱打开即看；Outlook 桌面版可能屏蔽 data URI 图。
