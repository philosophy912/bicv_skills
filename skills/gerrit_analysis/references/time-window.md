# 时间窗口解析约定

- 用户说「上周」「最近 3 天」「6/1 到 6/25」→ agent 用 Python `datetime` 换算本地时间区间，再转
  UTC 字符串拼到 `after:` / `before:` 谓词。
- 没给时间词 → 默认 `[now-24h, now]`。
- Gerrit 查询字符串里时间值要用双引号包住，如 `after:"2026-06-24 14:30:00"`。
- 落入窗口的字段取 change 的 `updated` 时间（merged change 的 updated ≈ 实际入库时间）。
- Gerrit 时间谓词为 **UTC**，格式 `yyyy-MM-dd HH:mm:ss`；agent 用本地时间换算成 UTC 后拼接。
