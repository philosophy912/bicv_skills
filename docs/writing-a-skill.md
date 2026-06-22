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

脚本放 `scripts/`，依赖 `shared.system_config`：

```python
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
from shared.system_config import ServiceError, load_systems_config  # noqa: E402

CONFIG_NAME = "<skill-name>.json"  # 与 skill 目录名一致


def get_system(system_name: str | None = None) -> dict:
    try:
        config = load_systems_config(CONFIG_NAME)
    except ServiceError as exc:
        sys.exit(
            f"[{CONFIG_NAME}] 无法加载配置：{exc}\n"
            f"请创建 ~/.bicv/{CONFIG_NAME}，结构见 docs/config-spec.md"
        )

    systems = config["systems"]
    if system_name is None:
        return systems
    if system_name not in systems:
        names = ", ".join(systems.keys())
        sys.exit(f"[{CONFIG_NAME}] system {system_name!r} 不存在。可选：{names}")
    return systems[system_name]
```

`shared/` 在 `skills/shared/`，`sys.path` 注入用的是「脚本 → skill 根 → `skills/`」即 `parent.parent.parent`，这样 plugin 复制到平台 cache 后路径仍正确。

参考完整示例：`skills/_template/scripts/example.py`。

## 4. 写配置说明

每个 skill 在自己的 `references/config-schema.md` 里声明：

- `config_name`：本 skill 用的配置文件名（例 `gerrit.json`）
- 字段表：本 skill 支持哪些字段、是否必填、说明
- 示例 JSON

格式参考 `skills/gerrit-restapi/references/config-schema.md`。

通用规范（路径、顶层 `systems` 结构、加载机制）见 [config 规范](config-spec.md)。

## 5. 多系统实例

如果可能配置多套连接（多个 Gerrit、多个 MySQL 等），`systems` 字典里放多个 key，让用户用 `--system <name>` 切换。如果只有一套，约定一个固定名字（通常叫 `default`）。

## 6. 注册

当前所有 skill 打包在一个 plugin（`bicv-skills`），从 `skills/` 自动加载，**无需手动注册**。

只在拆分成多个 plugin 时才需要编辑：

- `.claude-plugin/marketplace.json`（Claude Code 侧）
- `.agents/plugins/marketplace.json`（Codex 侧）

## 7. 本地测试

```bash
mkdir -p ~/.bicv && vim ~/.bicv/<skill-name>.json
python skills/<你的 skill 名>/scripts/<xxx>.py --system <name>
```