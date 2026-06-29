# Bug 分析 — 图片渲染（render_charts.py）

把 `bug_analysis.py` 的 JSON 输出渲染成 PNG 图表，**只吃 JSON、不连库**，职责与查询脚本分离。

```bash
# 先把两个子命令的输出存成文件
python3 scripts/bug_analysis.py submissions --since 2026-06-22 --until 2026-06-26 > sub.json
python3 scripts/bug_analysis.py overdue > ovd.json

# 渲染成图片（可只传其中一个）
python3 scripts/render_charts.py --submissions sub.json --overdue ovd.json
python3 scripts/render_charts.py --submissions sub.json --out /some/dir
```

### 产出

- **4 类图**（按数据有无按需生成；禅道 + Redmine 合并统计）：
  - `submissions_by_user` / `submissions_by_project`：横向条形图，按数降序，最多者居顶。
  - `overdue_by_user`：超期按指派人计数（横向条形图）。
  - `overdue_detail`：超期明细表格图（**缺陷ID** / 项目 / 模块 / 指派人 / 超期天数，按天数降序）；缺陷ID 带 `Z-`（禅道）/ `R-`（Redmine）前缀。
- **不截断**：条形图超 25 条、表格超 30 行自动 **分页** 成多张（`_p1/_p2…`），数据一条不丢。
- **输出目录**：默认 `~/.bicv/common.json` 的 `output_root/bug_analysis`（可在 `common.json` 的 `skills` 里映射别名）；`--out` 可覆盖。
- 返回 JSON 信封：`{"generated_at", "output_dir", "charts": {<板块>: [<png 路径>…]}}`。

### 中文字体

优先探测系统已装 CJK 字体（PingFang / Noto / 思源 / 雅黑 / SimHei …）；全找不到时回退到 `assets/fonts/` 下的字体文件；再找不到则报错指引。
