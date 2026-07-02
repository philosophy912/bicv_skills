# 第三方依赖规范

> skill 脚本需要第三方库（如 `mysql-connector-python`）时的声明、安装与运行时处理规范。
> 范例参考 `skills/mysql/`（requirements.txt + try/except guard + SKILL.md 前置检查）。

## 核心原则

1. **最小依赖**：优先用 Python 标准库（`urllib` / `email` / `imaplib` / `smtplib` / `sqlite3` / `json` 等）。只有标准库做不到时才引入第三方（如 MySQL 连接、复杂图表渲染）。
2. **skill 自包含**：每个 skill 的第三方依赖放在**该 skill 自己的** `scripts/requirements.txt`，不依赖全局。
3. **不自动安装**：脚本检测到依赖缺失时**只提示安装命令并退出**（`sys.exit(1)`），绝不擅自 `pip install`（避免污染用户环境 / 权限问题 / 网络不可达）。

## 1. 声明依赖

- **位置**：`skills/<skill-name>/scripts/requirements.txt`
- **格式**：pip 标准，每行一个包名；必要时 pin 版本
- 无第三方依赖的 skill **不需要**建该文件（不要建空文件）

```text
# skills/mysql/scripts/requirements.txt
mysql-connector-python
```

版本固定策略：
- 默认**不 pin**（用最新稳定版，`pip install` 自动选）
- 已知 break / 对行为敏感的依赖才 pin：`package>=1.2`（下限）或 `package==1.2.3`（精确）

## 2. 脚本运行时 guard（必须）

所有第三方库的 `import` 必须用 `try/except ImportError` 包裹，缺失时打印**安装命令**后退出。模板：

```python
import sys

try:
    import mysql.connector
    from mysql.connector import Error as MySQLError
except ImportError:
    print(
        "Error: mysql-connector-python is not installed.\n"
        "Install it with: pip install -r scripts/requirements.txt",
        file=sys.stderr,
    )
    sys.exit(1)
```

- 提示必须含**具体包名**和**安装命令**（`pip install -r scripts/requirements.txt`）
- 不要让裸 `ModuleNotFoundError` 直接抛给用户（信息不够 actionable）
- guard 放在脚本顶部、其他逻辑之前（缺依赖时秒退）

## 3. SKILL.md 前置检查（必须）

有第三方依赖的 skill，其 `SKILL.md` 必须有「前置检查 / 安装依赖」段，明确告诉用户/agent：

```markdown
## 前置检查 / 安装依赖

```bash
pip3 install -r scripts/requirements.txt      # Windows 用 pip
```
```

## 4. 安装方式（执行时）

### 用户手动

读该 skill 的 `SKILL.md` 前置检查，按命令装：

```bash
# macOS / Linux
pip3 install -r skills/<skill-name>/scripts/requirements.txt

# Windows（cmd / PowerShell，命令是 pip 不是 pip3）
pip install -r skills\<skill-name>\scripts\requirements.txt
```

### agent 编排时（Claude Code / Codex / Hermes）

agent 在**首次调用某 skill 的脚本前**，按以下顺序处理依赖：

1. 检查 `skills/<skill-name>/scripts/requirements.txt` 是否存在
2. 若存在，先执行 `pip install -r skills/<skill-name>/scripts/requirements.txt`（已装则 pip 跳过，幂等）
3. 再调用脚本

> 这样保证脚本运行时依赖已就绪，不会触发 guard 退出。agent 不应依赖"先跑报错再装"的回环。

## 5. 全局 vs skill 级

- **仓库根 `pyproject.toml`**：只放**开发/测试工具**（pytest / pytest-cov / ruff），**不放** skill 运行时依赖（因为本项目不打包成 wheel，靠 `npx skills add` 源码分发）
- **各 skill 的 `scripts/requirements.txt`**：放该 skill 的运行时第三方依赖

## 6. 跨平台注意

- `pip` 三平台通用；命令名差异：mac/Linux 多为 `pip3`，Windows 多为 `pip`
- 依赖若含 C 扩展（如某些数据库驱动），Windows 可能需要预编译 wheel——优先选有官方 wheel 的包（`mysql-connector-python` 有官方 Windows wheel）
- 不要在脚本里调系统包管理器（`apt` / `brew` / `winget`）装 Python 库——一律走 pip
