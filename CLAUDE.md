# CLAUDE.md

本文件是给 AI agent（Claude Code / Codex / Hermes）的项目协作指南。开始工作前先读完。

## 项目是什么

`bicv_skills` 是一套跨 **Claude Code / Codex / Hermes** 的 skill 能力包。每个 skill 封装一个内部系统（Gerrit / Jenkins / 禅道 / MySQL …）的 REST API 操作，通过 `npx skills add philosophy912/bicv_skills -y -g` 安装到各 agent 的 skills 目录。

- 每个 skill 自包含：`SKILL.md` + `scripts/` + 可选 `references/`
- 每个 skill 各持一份 `scripts/system_config.py`（凭据/配置解析底座），互不依赖
- 凭据统一存在 `~/.bicv/<skill>.json`，多实例用 `--system <name>` 切换
- 安装/结构规范见 [README](README.md)，配置规范见 [docs/config-spec.md](docs/config-spec.md)

## 仓库结构

```
skills/
├── gerrit-restapi/     # Gerrit REST API
├── jenkins-restapi/    # Jenkins Remote API
├── zentao-restapi/     # 禅道 v2 REST API
└── mysql/              # MySQL（仅 SELECT/INSERT/UPDATE）
docs/
├── config-spec.md      # ~/.bicv/*.json 配置规范
├── writing-a-skill.md  # 如何新增 skill
└── testing-guide.md    # ⚠️ 测试指南（必读）
```

## ⚠️ 测试是硬性要求

**每个 skill 脚本的单元测试行覆盖率必须 ≥ 90%。** 这不是建议，是准入门槛。

- 新增脚本 → 必须同时写测试到 90%+
- 修改脚本 → 必须跑测试确认未掉覆盖率，新增分支补对应用例
- 覆盖率按 skill 主脚本文件衡量；`system_config.py` 不计入单 skill 指标（由全量测试合并覆盖）
- 提交前在仓库根跑 `python3 -m pytest`，`fail_under = 90` 会卡住不达标的合并

**测试怎么写、怎么跑，见 [docs/testing-guide.md](docs/testing-guide.md)。** 写任何测试前先读这份指南。

核心规范速记：

- 全部 mock（urlopen / mysql.connector.connect / `_target` / `input`），**绝不连真实服务**
- 参考 `skills/zentao-restapi/tests/test_zentao_api.py` 的风格
- 单 skill 验证：`cd skills/<name> && python3 -m pytest --cov=<module> --cov-report=term-missing -q`（只 `--cov=<module>`，不要加 `system_config`）

## 改脚本时的红线

1. **`system_config.py` 同名模块从路径冲突问题**：email 和 mysql 的该文件已改名为 `_email_config.py` / `_mysql_config.py`，不要在它们下面再创建 `system_config.py`。gerrit/jenkins/zentao 的 `system_config.py` 内容相同（HTTP 服务专用），改一处需同步另外两处。
2. **脚本里的 SQL/危险操作拦截不要放松**：mysql skill 严禁 DELETE/DROP 等；zentao 写操作的危险等级确认不能跳过。
3. **不发起真实网络请求**——脚本本身没问题（用户运行时才连），但写测试或验证时必须 mock。

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

## 安装方式（用户侧，非开发）

```bash
npx skills add philosophy912/bicv_skills -y -g --agent claude-code codex hermes-agent openclaw
```

本仓库只支持这四个 agent（`--agent` 显式限定），不装到其它 agent。详见 [README](README.md)。开发时不需要安装，直接在仓库内改 `skills/` 即可。
