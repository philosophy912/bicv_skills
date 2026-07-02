# 开发环境与跨平台支持

> 本仓库在 **macOS** 上开发，但所有 skill 脚本必须**同时支持 macOS / Linux / Windows**（Windows 含 `cmd` 与 `PowerShell` 两种终端）。写/改脚本前先读完本文件。

## Python 版本

- **目标版本：Python ≥ 3.10**（`pyproject.toml` 的 `[tool.ruff] target-version = "py310"`）
- 仅用 3.10+ 标准库 + 各 skill 显式声明的外部依赖（如 mysql skill 的 `mysql-connector-python`）
- 命令名：macOS/Linux 一般是 `python3`；Windows 通常是 `python`（或 `py -3`）。**本文档示例统一写 `python3`，Windows 用户自行替换为 `python`**
- 不打包成 wheel——通过 `npx skills add` 以源码形式安装到各 agent

## 跨平台编码规范（硬性）

### 1. 子进程调用

- 调外部 Python 脚本一律用 `[sys.executable, "<path>", ...]`，**不要**硬编码 `python3`、**不要** `shell=True`
  - 范例：`skills/jenkins_analysis/scripts/collect.py` 的 `run_jenkins_cli`
  - `sys.executable` 三平台都解析到当前解释器，避免命令名差异
- 调系统命令用 `subprocess.run([...], shell=False)`（列表传参）
- **禁止** `os.system` / `subprocess.run(..., shell=True)`：`cmd` / `PowerShell` / `bash` 语法互不兼容

### 2. 路径

- 用 `os.path` 或 `pathlib.Path`，**不要**硬编码 `/tmp`、`C:\`、分隔符 `/` 或 `\`
- 配置统一走 `~/.bicv/<skill>.json`，用 `Path.home()` 解析（三平台都正确：mac/Linux `/Users/<u>`、Windows `C:\Users\<u>`）
- 文件名避免 Windows 非法字符 `\ : * ? " < > |`——jenkins_analysis 把 job 名里的 `/` 替成 `__`（`<job>__<number>.log`）就是为此

### 3. Shebang

- 脚本顶部保留 `#!/usr/bin/env python3`（mac/Linux 用；Windows 忽略，靠 `python xxx.py` 或文件关联）
- 不依赖 shebang 做跨平台分发——安装侧 `npx skills` 已处理软链/junction

### 4. 编码与输出

- 读写文件显式 `encoding="utf-8"`（Windows `cmd` 默认 GBK，不显式声明会乱码/报错）
- 读配置用 `utf-8-sig` 自动剥离 Windows PowerShell 保存的 BOM（仓库已统一这么做）
- 输出中文 OK，但避免 ANSI 颜色码（除非确认终端支持）

## 开发环境配置（macOS）

```bash
# 1. python 3.10+（mac 自带或 brew install python@3.10）
python3 --version

# 2. 开发依赖（pytest/cov/ruff）
pip install pytest pytest-cov ruff

# 3. 克隆后自检
python3 -m pytest            # 全量测试（CI 等价，fail_under=90）
ruff check skills/ && ruff format skills/ --check   # 静态检查
```

## Windows 运行注意

- **命令名**：本文档/CI 里的 `python3`，在 Windows 上换成 `python`（或 `py -3`）
- **终端**：`cmd` 与 `PowerShell` 路径分隔都是 `\`，但 PowerShell 命令更接近 bash；**脚本本身不依赖终端类型**（只调 Python 标准库）
- **`~` 展开**：`Path.home()` 在 Windows 解析到 `C:\Users\<user>`
- **路径长度/字符**：避免 workspace 含全角字符或超长路径
- **行尾**：`pyproject.toml` 强制 `[tool.ruff.format] line-ending = "lf"`——git 配置 `core.autocrlf=false`，避免 CRLF 干扰

## 外部 CLI 依赖

- 各 skill 若依赖外部 CLI（如某些 skill 调 `lark-cli`、`mysql` 客户端），**必须**：
  1. 在该 skill 的 `SKILL.md`「前置检查」声明
  2. 脚本里用 `shutil.which(<cli>)` 做存在性检查，缺失时打 warning 并优雅降级（不崩溃）
- `jenkins_analysis` 的 report 已改为直接 POST webhook（`urllib`），**不依赖** `lark-cli`

## 平台支持矩阵

| 能力 | macOS | Linux | Windows cmd | Windows PowerShell |
|---|---|---|---|---|
| Python 脚本执行 | ✓ `python3` | ✓ `python3` | ✓ `python` | ✓ `python` |
| `~/.bicv/*.json` 配置 | ✓ | ✓ | ✓ | ✓ |
| `npx skills add` 安装 | 软链 | 软链 | directory junction | directory junction |
| 子进程调 Python 脚本 | `sys.executable` | `sys.executable` | `sys.executable` | `sys.executable` |
