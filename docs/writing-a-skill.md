# 如何新增一个 skill

## 1. 复制模板

```bash
cp -r skills/_template skills/<你的 skill 名>
```

## 2. 编辑 SKILL.md

填好 frontmatter：

- `name`：与目录名一致
- `description`：**最关键**——模型据此判断何时调用本 skill，写清「做什么 + 何时用」

正文里也把用到的脚本、配置位置说清楚（用户读 SKILL.md 才知怎么填配置）。

## 3. 写脚本

脚本放 `scripts/`。读取配置统一通过 `shared.system_config.load_systems_config()`：

```python
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
from shared.system_config import ServiceError, load_systems_config

config = load_systems_config("<skill-name>.json")
systems = config["systems"]
# 按 --system 参数挑选，或默认取唯一一个
```

不需要配置的 skill（纯本地工具），脚本不依赖 `shared.system_config` 即可。

> ⚠️ **不要用相对路径或硬编码 `~/.bicv/` 绝对路径**——走 `shared.system_config` 是约定，能让 plugin 安装到不同平台 cache 目录后仍正常工作。完整规范见 [config 规范](specs/config-spec.md)。

## 4. 多系统实例

如果你的 skill 可能配置多套连接（例如多个 Gerrit、多个 MySQL），`systems` 字典里放多个 key，让用户用 `--system <name>` 切换。如果只有一套，约定一个固定名字（如 `default`），调用方传 `--system default`。

## 5. marketplace 注册

当前所有 skill 打包在一个 plugin（`bicv-skills`），从 `skills/` 自动加载，**无需手动注册**。

如果想加新 plugin（拆分成多个 marketplace），编辑：

- `.claude-plugin/marketplace.json`（Claude Code 侧）
- `.agents/plugins/marketplace.json`（Codex 侧）

## 6. 本地测试

```bash
# 配置 ~/.bicv/<skill-name>.json（手写或用其它工具）
mkdir -p ~/.bicv && vim ~/.bicv/<skill-name>.json

# 验证脚本能加载配置
python skills/<你的 skill 名>/scripts/<xxx>.py --system <name>
```