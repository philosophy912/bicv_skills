# Bug 每日分析 — Markdown 报告（render_report.py）

把 `bug_analysis.py` 的 JSON 渲染成**表格形式**的 Markdown 报告，便于一眼定位问题。只吃 JSON、不连库、不依赖 matplotlib，可独立运行。

```bash
python3 scripts/render_report.py --submissions sub.json --overdue ovd.json
```

### 产出

- 落盘 `report_<YYYYMMDD>.md` 到输出目录（同 `render_charts.py`，走 `common.json`）。
- 表格内容：
  - **一、本周提交**：按提交人、按项目（数量 + 占比，降序）。
  - **二、超期未处理**：按指派人计数 + 超期明细（**缺陷ID** / 项目 / 模块 / 指派人 / 超期天数，按天数降序）。
- 缺陷ID 带 `Z-`（禅道）/ `R-`（Redmine）前缀，跨系统不撞号、可定位。
- 返回 JSON 信封：`{"generated_at", "report_path"}`。
