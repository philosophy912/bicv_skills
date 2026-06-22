---
name: <skill-name>
description: <一句话说明这个 skill 做什么、何时该调用它——模型据此判断是否使用本 skill。>
---

# <Skill 标题>

<正文：这个 skill 的规则、流程、约束。模型调用本 skill 时会读到这些内容。>

## 用到的脚本

- `scripts/<xxx>.py` — <说明>，从 `~/.bicv/<skill-name>.json` 读取配置。

## 配置

本 skill 需要在 `~/.bicv/<skill-name>.json` 里配置连接信息。结构必须是：

```json
{
  "systems": {
    "<system-name>": {
      "url": "https://...",
      "username": "...",
      "password": "..."
    }
  }
}
```

`<system-name>` 是你自己起的标识，CLI 调用时通过 `--system <system-name>` 选择。详见 [config 规范](../../docs/config-spec.md)。

> ⚠️ **不要用相对路径读配置**——plugin 安装后文件会被复制到平台 cache 目录，相对路径会失效。通过 `shared.system_config.load_systems_config("<skill-name>.json")` 读取即可，路径解析交给它。