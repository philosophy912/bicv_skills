# assets/fonts — 中文字体兜底目录

`scripts/render_charts.py` 渲染 PNG 时，优先探测系统已装的中文字体（PingFang /
Noto Sans CJK / 思源黑体 / 微软雅黑 / SimHei 等）。若系统一个都没装，会回退到
**本目录**下的字体文件。

## 何时需要补字体

仅当目标机器没有任何中文字体时才需要。把任意一个开源中文字体文件放进本目录即可被自动识别：

- 推荐 **思源黑体 / Noto Sans CJK SC**（OFL 许可证，可商用）
- 支持 `.otf` / `.ttf` / `.ttc`

为控制 skill 体积，仓库默认 **不内置** 字体二进制；在 macOS / 主流 Linux /
Windows 上系统字体通常已足够，无需放置。

> 放入字体后无需改代码：`render_charts.py` 的 `_find_cjk_font()` 会按
> `*.otf → *.ttf → *.ttc` 顺序自动发现并作为最终兜底。
