# Bug 分析 — 图片渲染（render_charts.py）

把 `bug_analysis.py` 的 JSON 输出渲染成 PNG 图表，**只吃 JSON、不连库**。

```bash
# 先把子命令输出存成文件
python3 scripts/bug_analysis.py submissions --since 2026-06-22 --until 2026-06-26 > sub.json
python3 scripts/bug_analysis.py closures    --since 2026-06-22 --until 2026-06-26 > cls.json

# 渲染（submissions 必给；closures 给了才出对比图）
python3 scripts/render_charts.py --submissions sub.json --closures cls.json
python3 scripts/render_charts.py --submissions sub.json --out /some/dir
```

### 产出（4 张图，按数据有无按需生成；禅道 + Redmine 合并）

| 图 key | 类型 | 说明 |
|---|---|---|
| `submissions_by_user` | 横向条形图 | 本周提交按提交人，降序，最多者居顶；超 25 条分页 |
| `submissions_by_project` | 饼图 | 本周提交按项目；前 9 + 「其他」聚合（饼图项太多无法辨认） |
| `severe_ratio` | 饼图 | 本周严重 vs 非严重占比（取自 submissions 的 severe） |
| `submissions_vs_closures` | 分组对比柱状图 | 提交 vs 关闭，按人并列双柱（需 `--closures`） |
| `closures_by_user` | 饼图 | 本周关闭按关闭人，前 9 + 「其他」（需 `--closures`） |

> **overdue 不出图** —— 跟踪不及时走纯表格（在 render_email 里），给人对质用。

### 其它

- **条形图不截断**：超 25 条自动分页（`_p1/_p2…`），数据一条不丢。饼图做「前 9 + 其他」聚合。
- **输出目录**：默认 `~/.bicv/common.json` 的 `output_root/bug_analysis`（可在 `common.json` 的 `skills` 里映射别名）；`--out` 可覆盖。
- **中文字体**：优先探测系统已装 CJK 字体（PingFang / Noto / 思源 / 雅黑 / SimHei …）；找不到回退 `assets/fonts/` 下字体；再找不到报错指引。
- 返回 JSON 信封：`{"generated_at", "output_dir", "charts": {<图key>: [<png 路径>…]}}`，供 render_email 的 `--charts` 读取。
