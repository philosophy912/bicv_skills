# CLAUDE.md

本文件是给 AI agent（Claude Code / Codex / Hermes）的项目协作指南。开始工作前先读完。

## 项目是什么

`bicv_skills` 是一套跨 **Claude Code / Codex / Hermes** 的 skill 能力包。每个 skill 封装一个内部系统（Gerrit / Jenkins / 禅道 / MySQL …）的 REST API 操作，通过 `npx skills add philosophy912/bicv_skills -y -g` 安装到各 agent 的 skills 目录。

- 每个 skill 自包含：`SKILL.md` + `scripts/` + 可选 `references/`
- 每个 skill 各持一份 `scripts/system_config.py`（凭据/配置解析底座），互不依赖
- 凭据统一存在 `~/.bicv/<skill>.json`，多实例用 `--system <name>` 切换
- 安装/结构规范见 [README](README.md)，配置规范见 [docs/spec/config-spec.md](docs/spec/config-spec.md)

## 仓库结构

```
skills/
├── gerrit-restapi/     # Gerrit REST API
├── jenkins-restapi/    # Jenkins Remote API
├── zentao-restapi/     # 禅道 v2 REST API
└── mysql/              # MySQL（仅 SELECT/INSERT/UPDATE）
docs/
├── reference/          # 参考资料（开发环境 / 跨平台 / Python 版本）
├── spec/               # 技术文档（配置规范 / 写 skill / 测试指南 / 优化方案）
└── issue/              # 缺陷文档（修复缺陷必写：问题 / 根因 / 方案）
temp/                   # 临时草稿（git 忽略，不提交）
```

## 开发环境与跨平台

- 开发环境：**任意操作系统**（macOS / Linux / Windows 均可）；所有 skill 必须同时支持 **macOS / Linux / Windows**（Windows 含 `cmd` 与 `PowerShell` 两种终端）。
- **Python ≥ 3.10**（`pyproject.toml` 的 ruff `target-version = py310`）。
- 跨平台编码硬性规范（子进程用 `sys.executable`、路径用 `pathlib`/`os.path`、禁 `os.system`/`shell=True`、文件 IO 显式 `utf-8`）、Windows 注意、平台支持矩阵，详见 [docs/reference/environment.md](docs/reference/environment.md)。

## ⚠️ 测试是硬性要求

**每个 skill 脚本的单元测试行覆盖率必须 ≥ 90%。** 这不是建议，是准入门槛。

- 新增脚本 → 必须同时写测试到 90%+
- 修改脚本 → 必须跑测试确认未掉覆盖率，新增分支补对应用例
- 覆盖率按 skill 主脚本文件衡量；`system_config.py` 不计入单 skill 指标（由全量测试合并覆盖）
- 提交前在仓库根跑 `python3 -m pytest`，`fail_under = 90` 会卡住不达标的合并

**测试怎么写、怎么跑，见 [docs/spec/testing-guide.md](docs/spec/testing-guide.md)。** 写任何测试前先读这份指南。

核心规范速记：

- 全部 mock（urlopen / mysql.connector.connect / `_target` / `input`），**绝不连真实服务**
- 参考 `skills/zentao-restapi/tests/test_zentao_api.py` 的风格
- 单 skill 验证：`cd skills/<name> && python3 -m pytest --cov=<module> --cov-report=term-missing -q`（只 `--cov=<module>`，不要加 `system_config`）

## 改脚本时的红线

1. **`system_config.py` 同名模块从路径冲突问题**：email 和 mysql 的该文件已改名为 `_email_config.py` / `_mysql_config.py`，不要在它们下面再创建 `system_config.py`。gerrit/jenkins/zentao 的 `system_config.py` 内容相同（HTTP 服务专用），改一处需同步另外两处。
2. **脚本里的 SQL/危险操作拦截不要放松**：mysql skill 严禁 DELETE/DROP 等；zentao 写操作的危险等级确认不能跳过。
3. **不发起真实网络请求**——脚本本身没问题（用户运行时才连），但写测试或验证时必须 mock。
4. **第三方依赖每 skill 自持**：引入第三方库时，① 在该 skill 的 `scripts/requirements.txt` 声明；② 脚本里 `try/except ImportError` 友好提示安装命令（**不要**裸抛 `ModuleNotFoundError`）；③ `SKILL.md` 前置检查写安装命令；④ **不**擅自 `pip install`（只提示，让用户/agent 装）。详见 [docs/spec/dependencies.md](docs/spec/dependencies.md)。

## 修复缺陷的文档要求

修复任何**缺陷（bug）**时，**必须**在 `docs/issue/` 下新建一个 md 文档（文件名 `issue-<日期>-<简述>.md`，如 `issue-2026-07-02-card-500.md`），至少包含：

- **问题描述**：现象、复现步骤、影响范围
- **根本原因**：定位到的具体代码 / 逻辑根因（不是表象）
- **解决方案**：怎么改的、为什么这么改
- **验证**：怎么确认修复有效（新增测试用例 / 手动验证结果）

模板见 [docs/issue/TEMPLATE.md](docs/issue/TEMPLATE.md)。纯新增功能、文档、重构类改动不需要写 issue 文档。

## 常用命令

```bash
# 跑全部测试（CI 等价）
python3 -m pytest

# 单 skill 测试 + 覆盖率
cd skills/<skill-name>
python3 -m pytest --cov=<module> --cov-report=term-missing -q

# 脚本自检（不连真实服务，验证 import 和 --help）
python3 skills/<skill-name>/scripts/<xxx>_api.py --help

# Ruff 静态检查（提交前必过）
ruff check skills/
ruff format skills/ --check
```

## 提交与推送

提交信息用 `coccm` 生成（不要手写 commit message），用户已配置 alias：

```bash
alias cmy="coccm commit -y"
alias cma="coccm commit --amend -y"
alias commit="git add . && cmy && git pr && git psa"
```

- **普通提交**：`git add <files>` → `cmy`（= `coccm commit -y`，自动生成 commit message）。
- **追加修改到上一次提交**：`cma`（= `coccm commit --amend -y`）。
- 推送到 GitHub：`cmy` 之后直接 `git push`（用户惯用 `git push` 推送）。
- 一次性提交+PR+推送：`commit`（add 全部 → cmy → git pr → git psa）。

注意：`commit` alias 会 `git add .` 把工作区所有改动暂存（含会话前已存在的无关改动，如 jenkins_analysis 的本地修改），提交前先确认 `git status` 范围。默认当前分支为 main，直接推送 main。

- **提交前必查文档同步**：本次改动是否需要更新 `docs/spec/` 下的设计/技术文档，或 `README.md`？涉及**行为变化 / 新功能 / 配置字段 / 接口变动 / 跨平台支持**时，必须同步相关文档并与代码一起提交。修复缺陷另需按上节写 `docs/issue/` 文档。

## 安装方式（用户侧，非开发）

```bash
npx skills add philosophy912/bicv_skills -y -g --agent claude-code codex hermes-agent openclaw
```

本仓库只支持这四个 agent（`--agent` 显式限定），不装到其它 agent。详见 [README](README.md)。开发时不需要安装，直接在仓库内改 `skills/` 即可。
