# 如何新增一个 skill

## 1. 起骨架

参考一个最接近的现有 skill 复制改：

```bash
# 例：要写一个新的 REST API skill，参考 zentao-restapi
cp -r skills/zentao-restapi skills/<你的 skill 名>
# 然后删掉它的 scripts/zentao_api.py、tests/、references/，只留骨架（SKILL.md + scripts/system_config.py + conftest.py）
```

每个 skill 目录至少要有：

```
skills/<你的 skill 名>/
├── SKILL.md                # frontmatter + 使用说明
├── scripts/
│   ├── <xxx>_api.py        # 主脚本
│   └── system_config.py    # 配置解析底座（从现有 skill 复制，不要改）
├── conftest.py             # 把 scripts/ 加入 sys.path（放 skill 根目录）
├── tests/
│   └── test_<xxx>_api.py   # ⚠️ 必须有，覆盖率 ≥90%
├── references/             # 可选：参考文档（判定依据、API 协议、config-schema 等）
└── assets/                 # 可选：产物资源（输出模板、字体兜底等）
```

**可选目录 `references/` 与 `assets/` 的分工**（都有就用，按语义放，别混）：

- **`references/`** — 判定依据 / 参考文档：agent 编排时**读**的东西。如失败模式清单、API 协议、`config-schema.md`、安全确认矩阵。
- **`assets/`** — 产物资源 / 模板：作为最终输出**模板或兜底素材**的东西。如报告骨架 `report-template.md`、中文字体兜底 `assets/fonts/`。

> 例：`jenkins_analysis` 把失败模式清单放 `references/`、输出样板放 `assets/report-template.md`；`bug_analysis` 的字体兜底放 `assets/fonts/`。

`system_config.py` 直接从任一现有 skill 的 `scripts/` 复制，保持 4 份一致，**不要改它**。

## 2. 编辑 SKILL.md

填好 frontmatter：

- `name`：与目录名一致
- `description`：**最关键**——模型据此判断何时调用本 skill，写清「做什么 + 何时用」

正文里也把用到的脚本、配置位置说清楚（用户读 SKILL.md 才知怎么填配置）。

## 3. 写脚本

脚本放 `scripts/`，依赖同目录的 `system_config.py`：

```python
import sys

from system_config import ServiceError, load_systems_config  # noqa: E402

CONFIG_NAME = "<skill-name>.json"  # 与 skill 目录名一致


def get_system(system_name: str | None = None) -> dict:
    try:
        config = load_systems_config(CONFIG_NAME)
    except ServiceError as exc:
        sys.exit(
            f"[{CONFIG_NAME}] 无法加载配置：{exc}\n"
            f"请创建 ~/.bicv/{CONFIG_NAME}，结构见 docs/spec/config-spec.md"
        )

    systems = config["systems"]
    if system_name is None:
        return systems
    if system_name not in systems:
        names = ", ".join(systems.keys())
        sys.exit(f"[{CONFIG_NAME}] system {system_name!r} 不存在。可选：{names}")
    return systems[system_name]
```

`system_config.py` 与脚本同处 `scripts/` 目录，运行时 Python 自动把脚本所在目录加入 `sys.path`，无需手动注入路径。每个 skill 各持一份 `system_config.py`，互不依赖——这样 `npx skills` 把各 skill 独立软链接到不同目录时仍能正常 import。

参考完整示例：`skills/zentao-restapi/scripts/zentao_api.py`。

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

新 skill 只要放在 `skills/<skill-name>/SKILL.md`（带 YAML frontmatter 的 `name` / `description`），就会被 `npx skills add` 自动发现并安装，**无需手动注册**、无需维护 manifest。

需要读写 `~/.bicv/<skill>.json` 配置的 skill，把 `system_config.py` 放在 `scripts/` 下与脚本同目录，脚本里直接 `from system_config import ...` 即可（从现有 skill 复制，保持一致）。

安装命令见 [README](../README.md#安装)。

## 7. 写测试（⚠️ 必做）

每个 skill 脚本必须有单元测试，**行覆盖率 ≥ 90%**。详见 [测试指南](testing-guide.md)。

```bash
cd skills/<你的 skill 名>
python3 -m pytest --cov=<module> --cov-report=term-missing -q
```

参考 `skills/zentao-restapi/tests/test_zentao_api.py` 的风格。不达标不算完成。

## 8. 本地测试（手动验证脚本可跑）

```bash
mkdir -p ~/.bicv && vim ~/.bicv/<skill-name>.json
python skills/<你的 skill 名>/scripts/<xxx>.py --system <name>
```